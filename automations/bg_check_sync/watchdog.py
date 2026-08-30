"""Watchdog for bg_check_sync — catch a silent scheduler stall fast.

bg_check_sync writes a heartbeat file at the end of every successful run. This
watchdog (its own tiny launchd job, a couple times a day) checks that heartbeat:
if it's older than STALE_HOURS during the daytime, it DMs Raf via Lucy so a
stall is caught in minutes instead of by noticing the OBCL is stale by hand
(which is how the 2026-07-20 → 22 outage was found).

Anti-spam: alerts at most once per COOLDOWN_HOURS. Never raises — a watchdog
that crashes is worse than useless.

    python -m automations.bg_check_sync.watchdog            # check + alert if stale
    python -m automations.bg_check_sync.watchdog --dry-run  # print, never DM
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HEARTBEAT = REPO_ROOT / "output" / "logs" / "bg-check-sync.heartbeat"
LAST_ALERT = REPO_ROOT / "output" / "logs" / "bg-check-sync.watchdog-alert"

RAF_SLACK_ID = "U045Z8N0ZQC"   # Rafael Hidalgo (creator of #rafs-office-recruiting, retired)
STALE_HOURS = 6.0              # main runs are 11:30 + 16:00, so >6h stale = a miss
COOLDOWN_HOURS = 6.0           # don't re-ping more than once per this window
DAY_START, DAY_END = 8, 21     # only alert 8am–9pm Central (mini local time)

# The scheduled passes, and the hour by which each must have landed. A flat
# "is the heartbeat <6h old" test CANNOT see a lost afternoon pass: at the 17:00
# check a clean 11:30 run is only 5.5h old, so it reads "ok", and by the next
# check (12:45 tomorrow) that day's 11:30 run has already refreshed the
# heartbeat. The 2026-08-17 4pm crash sat in exactly that blind spot — it only
# surfaced when Megan noticed the tile wasn't green. So on the afternoon check
# we require a heartbeat from AFTER the 16:00 pass, not merely a recent one.
PASSES = [(11, 30), (16, 0)]
GRACE_MINUTES = 45             # a pass has this long to finish before it's "missed"


def _age_hours(path: Path):
    """Hours since the ISO timestamp in `path`, or None if missing/unreadable."""
    if not path.exists():
        return None
    try:
        ts = dt.datetime.fromisoformat(path.read_text().strip())
    except Exception:  # noqa: BLE001
        return None
    ref = dt.datetime.now(ts.tzinfo) if ts.tzinfo else dt.datetime.now()
    return (ref - ts).total_seconds() / 3600.0


def _missed_pass(now: dt.datetime) -> str | None:
    """Name of the most recent scheduled pass that should have finished by now
    but left no heartbeat behind, or None if every due pass has landed."""
    if not HEARTBEAT.exists():
        return None            # the flat staleness test already covers "never ran"
    try:
        beat = dt.datetime.fromisoformat(HEARTBEAT.read_text().strip())
    except Exception:  # noqa: BLE001
        return None
    for hh, mm in reversed(PASSES):
        due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now < due + dt.timedelta(minutes=GRACE_MINUTES):
            continue           # not due yet (or still inside its grace window)
        if beat < due:
            # Built by hand, not strftime: %-I is glibc-only and these have to
            # read the same on the mini and on Windows.
            hour12 = due.hour % 12 or 12
            return f"{hour12}:{due.minute:02d}{'am' if due.hour < 12 else 'pm'}"
        return None            # newest due pass landed — earlier ones are moot
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print, never DM")
    args = ap.parse_args(argv)

    now = dt.datetime.now()
    if not (DAY_START <= now.hour < DAY_END):
        print("[watchdog] outside daytime window — skip")
        return 0

    age = _age_hours(HEARTBEAT)
    missed = _missed_pass(now)

    if age is not None and age <= STALE_HOURS and missed is None:
        print(f"[watchdog] ok — bg_check_sync last ran {age:.1f}h ago")
        return 0

    last = "never (no heartbeat found)" if age is None else f"{age:.1f}h ago"
    if missed:
        headline = (f":warning: *BG Check Sync missed its {missed} pass today* — "
                    f"last successful run was {last}.")
    else:
        headline = (":warning: *BG Check Sync looks stalled* — last successful "
                    f"run was {last}.")
    msg = (f"{headline} The OBCL isn't auto-updating. Fix: `lucy logtail "
           "bg-check-sync` to see why it died, then `lucy rerun "
           "bg_check_sync_post` to catch up (or `lucy install_bg_check_sync` "
           "if it fell off the scheduler).")

    if args.dry_run:
        print(f"[watchdog] STALE ({last}) — would DM Raf:\n{msg}")
        return 0

    # anti-spam: skip if we already alerted within the cooldown
    alerted = _age_hours(LAST_ALERT)
    if alerted is not None and alerted < COOLDOWN_HOURS:
        print(f"[watchdog] stale ({last}) but alerted {alerted:.1f}h ago — cooldown")
        return 0

    try:
        from automations.shared import slack_metrics_post as smp
        client = smp._client()  # Lucy user token (on the mini)
        ch = client.conversations_open(users=RAF_SLACK_ID)["channel"]["id"]
        client.chat_postMessage(channel=ch, text=msg)
        LAST_ALERT.parent.mkdir(parents=True, exist_ok=True)
        LAST_ALERT.write_text(now.isoformat())
        print(f"[watchdog] ALERTED Raf — bg_check_sync stale ({last})")
    except Exception as e:  # noqa: BLE001 — never let the watchdog itself crash
        print(f"[watchdog] alert FAILED ({type(e).__name__}: {str(e)[:120]})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
