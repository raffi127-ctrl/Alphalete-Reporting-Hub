"""Rep Gap Alerts -- "Reps Over 15 Min Gap", texted every 10 minutes.

    python -m automations.gap_alerts.run                      # PREVIEW (renders,
                                                              # resolves, sends nothing)
    python -m automations.gap_alerts.run --send               # text the group
    python -m automations.gap_alerts.run --force --only rafael
    python -m automations.gap_alerts.run --probe              # dump the raw rows

WHAT IT IS. Carlos has had this card since July as the bottom panel of the
hourly B2B Dispositions post. Raf wants the same signal for his office, on its
own, faster: JUST the gap card, straight into the "Alphalete Partners" iMessage
group, every ten minutes of the selling day. No Today's Activity panel, no Slack
post, no thread. (It shipped at five minutes on 2026-08-26; Raf moved it to ten
the next day -- the cadence lives in config.TICK_MINUTES.)

WHY IT RUNS ON LUCY 1. Because that is where iMessage is set up (Megan). Lucy 1
is the busiest runner, but the group only exists in ITS Messages -- Megan added
alphaletereporting@ to the Partners chat on 8/26, which is what put the room on
that machine at all. Same reason alphalete_sales_board lives there.

THE LOAD IS FENCED, the same four ways the sales-board sweep is:
  1. its OWN browser profile (uploaded/.browser_profile_gap_alerts) so it can never
     collide with the .browser_profile the 4am batch holds;
  2. headless, and one page load per tick -- the card comes from a JSON
     endpoint, not a screenshot, so there is no rendering to wait on;
  3. it only runs inside the knocking window -- Mon-Fri 1:30pm-8:30pm,
     Saturday 10:00am-5:00pm, Sunday not at all;
  4. a pid lock, so a slow tick is SKIPPED rather than stacked. At ~48 runs a
     day an overlapping-run bug becomes 96.

NEVER TEXTS AN EMPTY CARD. If nobody is over the threshold that is good news,
not news -- and a "no reps over 15 min gap" picture arriving all afternoon is
how a room learns to mute the alert that matters.
[[feedback_never_post_blank]]

Python 3.9-safe (Lucy runtime). Cross-platform except the iMessage leg, which
only runs under --send.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.b2b_dispositions import capture as cap
from automations.gap_alerts import config as C

HUB_CARD_ID = "gap-alerts"
HUB_CARD_NAME = "Rep Gap Alerts (15-min gaps -> Partners chat)"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "gap_alerts"

# One alert after this many consecutive failed ticks, then a cooldown. A live
# outage would otherwise post an incident every tick all afternoon, and three
# ticks is ~30 minutes -- long enough to be a real outage and short enough that
# a dead ownerville session is caught the same hour.
FAIL_STREAK = 3
ALERT_COOLDOWN_HOURS = 2
FAIL_PATH = Path.home() / ".config" / "recruiting-report" / "gap_alerts_fails.json"
CORRECTIONS_CHANNEL = "C0BK5PRG259"  # #claudecorrections-and-requests


def _log(msg: str) -> None:
    print("[gap-alerts] %s" % msg, flush=True)


# --- singleton lock ----------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


class Lock:
    """Skip this tick if the last one is still going. Waiting would just queue
    behind the next tick; there is another one in ten minutes."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or C.LOCK_PATH
        self.held = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                pid = int(self.path.read_text().strip() or 0)
            except (ValueError, OSError):
                pid = 0
            if pid and _pid_alive(pid):
                return self
            try:
                self.path.unlink()
            except OSError:
                pass
        self.path.write_text(str(os.getpid()))
        self.held = True
        return self

    def __exit__(self, *exc):
        if self.held:
            try:
                self.path.unlink()
            except OSError:
                pass


# --- state (hub pill only; the card itself is stateless) ---------------------
def _state() -> Dict:
    try:
        return json.loads(C.STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(data: Dict) -> None:
    C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = C.STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    tmp.replace(C.STATE_PATH)


def _sent_too_recently(key: str):
    """Minutes since this office's last SENT card, or None if that was long
    enough ago (or never). See config.MIN_SEND_GAP_MINUTES for why."""
    stamp = (_state().get("_last_sent") or {}).get(key)
    if not stamp:
        return None
    try:
        age = (dt.datetime.now()
               - dt.datetime.fromisoformat(stamp)).total_seconds() / 60.0
    except ValueError:
        return None
    # A clock that went backwards (DST, an NTP correction) must not wedge the
    # alert shut for an hour — treat a negative age as "long enough ago".
    if age < 0 or age >= C.MIN_SEND_GAP_MINUTES:
        return None
    return age


def _mark_sent(key: str) -> None:
    data = _state()
    data.setdefault("_last_sent", {})[key] = dt.datetime.now().isoformat(
        timespec="seconds")
    _save_state(data)


def _publish_hub_once(day: dt.date) -> None:
    """The first good tick of the day paints the card; every later tick stays
    quiet. A green pill repainted all afternoon would say nothing.
    [[feedback_launchd_reports_must_publish]]"""
    data = _state()
    key = day.isoformat()
    if (data.get("_hub") or {}).get(key):
        return
    try:
        from automations.shared import hub_activity
        hub_activity.log_completed(HUB_CARD_ID, HUB_CARD_NAME, status="success")
        data.setdefault("_hub", {})[key] = True
        _save_state(data)
    except Exception as e:  # noqa: BLE001 — the Hub row must never fail a tick
        _log("hub publish skipped: %s: %s" % (type(e).__name__, str(e)[:120]))


# --- failure streak ----------------------------------------------------------
def _fails() -> Dict:
    try:
        return json.loads(FAIL_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _write_fails(data: Dict) -> None:
    try:
        FAIL_PATH.parent.mkdir(parents=True, exist_ok=True)
        FAIL_PATH.write_text(json.dumps(data, indent=1))
    except OSError:
        pass


def _record_failure(err: str, *, dry_run: bool) -> None:
    """Count it, and speak once the streak says this is not a blip.

    A five-minute job that dies quietly is the worst kind: the room simply
    stops getting cards and reads that as "nobody has a gap".
    """
    data = _fails()
    data["streak"] = int(data.get("streak", 0)) + 1
    data["last_error"] = err[:400]
    data["last_at"] = dt.datetime.now().isoformat(timespec="seconds")
    streak = data["streak"]
    _log("failure #%d: %s" % (streak, err[:200]))

    should_alert = streak >= FAIL_STREAK
    last_alert = data.get("alerted_at")
    if should_alert and last_alert:
        try:
            age = (dt.datetime.now()
                   - dt.datetime.fromisoformat(last_alert)).total_seconds() / 3600.0
            if age < ALERT_COOLDOWN_HOURS:
                should_alert = False
        except ValueError:
            pass

    if should_alert and not dry_run:
        try:
            # One emoji-free line in the channel, the detail in the thread —
            # the house format for #claudecorrections.
            from automations.shared import slack_metrics_post as smp
            client = smp._client()
            resp = client.chat_postMessage(
                channel=CORRECTIONS_CHANNEL,
                text=("Rep Gap Alerts has failed %d ticks in a row — the "
                      "Partners chat is not getting gap cards." % streak))
            client.chat_postMessage(
                channel=CORRECTIONS_CHANNEL, thread_ts=resp["ts"],
                text=("```\n%s\n```\nRe-run once the cause is clear:\n"
                      "`lucy rerun gap_alerts`" % err[:1500]))
            data["alerted_at"] = dt.datetime.now().isoformat(timespec="seconds")
        except Exception as e:  # noqa: BLE001 — an alert must never crash a tick
            _log("alert failed: %s: %s" % (type(e).__name__, str(e)[:120]))

    _write_fails(data)


def _clear_failures() -> None:
    data = _fails()
    if data.get("streak"):
        _log("recovered after %d failed tick(s)" % data["streak"])
        _write_fails({"streak": 0,
                      "recovered_at": dt.datetime.now().isoformat(timespec="seconds")})


# --- the pull ----------------------------------------------------------------
def _pin_campaign(page, rqst: str, campaign_id: str) -> None:
    """Sticky-campaign guard. TeleMapper pages are scoped to whatever campaign
    the session last had selected -- by ANY job on this box -- so every tick
    re-pins it. Best-effort, same as the knocks and WKD pulls."""
    if not campaign_id:
        return
    try:
        page.goto("https://v2.ownerville.com/index.cfm?p=%d&rqst=%s"
                  "&invD2DClientId=%s" % (C.PAGE_TIME_TRACKER, rqst, campaign_id),
                  wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(800)
    except Exception as e:  # noqa: BLE001
        _log("  campaign pin failed (%s) — continuing on the session's current "
             "campaign" % type(e).__name__)


def gap_rows(page, cfg: Dict, day: dt.date) -> List[Dict]:
    """Reps over the gap threshold for one office, newest-inactive last.

    Sorted by MINUTES INACTIVE, longest first -- not alphabetically like the
    B2B card. On a five-minute tick the person who has been dark for two hours
    is the whole point of the message, and a phone shows the top of an image.
    """
    rqst = cap.capture_rqst(page)
    impersonated = False
    if cfg.get("ov") == "impersonate":
        # Dead for Raf (his login IS office 11280) and live the day a second
        # office is added. Impersonation is ALWAYS exited in the finally below,
        # or the next office on this page reads the previous one's numbers.
        from automations.focus_office_att.aliases import load_aliases
        from automations.focus_office_att.run_all_owners import (
            _exit_impersonation, _find_owner_and_impersonate,
            _navigate_to_office_access)
        _exit_impersonation(page)
        _navigate_to_office_access(page)
        rqst, reason = _find_owner_and_impersonate(page, cfg["name"],
                                                   load_aliases())
        if not rqst:
            raise RuntimeError("Couldn't impersonate %r: %s"
                               % (cfg["name"], reason))
        impersonated = True
    try:
        _pin_campaign(page, rqst, cfg.get("campaign_id", ""))
        rows = cap.fetch_time_tracking(page, rqst, day.strftime("%m/%d/%Y"))
    finally:
        if impersonated:
            from automations.focus_office_att.run_all_owners import (
                _exit_impersonation)
            _exit_impersonation(page)
    over = [r for r in rows
            if cap._int(r.get("minutesSinceLastKnock")) > C.GAP_THRESHOLD_MIN]
    over.sort(key=lambda r: -cap._int(r.get("minutesSinceLastKnock")))
    return over


def render(cfg: Dict, reps: List[Dict], out_dir: Path, slot: str) -> Path:
    """The card, with its own title bar. ONE image per tick and no accompanying
    text: send_to_group would post the caption as a second message, and over a
    day of ticks that doubles what the room scrolls past. The time lives on
    the card instead, so a reader can tell a fresh one from one that scrolled."""
    out_dir.mkdir(parents=True, exist_ok=True)
    bare = out_dir / ("gaps_%s_raw.png" % cfg["key"])
    cap.render_gap_card(reps, bare)
    who = (" — %s" % cfg["label"]) if cfg.get("label") else ""
    titled = out_dir / ("gaps_%s.png" % cfg["key"])
    return cap.add_title_header(bare, "%s%s — %s" % (C.CARD_TITLE, who, slot),
                                titled)


def tick(day: dt.date, *, send: bool, only: str = "",
         headless: bool = True) -> List[str]:
    """One pass. Returns the list of failures (empty = clean)."""
    offices = [o for o in C.enabled()
               if not only or o["key"] in {k.strip().lower()
                                           for k in only.split(",")}]
    if not offices:
        return ["no office matched --only %r" % only]
    slot = C.slot_label()
    out_dir = OUTPUT_DIR / day.strftime("%Y-%m-%d")

    from automations.shared.tableau_patchright import ownerville_session
    from automations.b2b_dispositions import text_post as tp

    failures = []
    seen_names = []
    with ownerville_session(headless=headless, verbose=False,
                            profile_dir=C.PROFILE_DIR) as page:
        for cfg in offices:
            try:
                reps = gap_rows(page, cfg, day)
            except Exception as e:  # noqa: BLE001
                failures.append("%s: %s: %s" % (cfg["key"], type(e).__name__,
                                                str(e)[:200]))
                _log("%s PULL FAILED: %s: %s"
                     % (cfg["key"], type(e).__name__, str(e)[:200]))
                continue

            if not reps:
                _log("%s: nobody over %d min at %s — nothing sent (an empty "
                     "card is not news)" % (cfg["key"], C.GAP_THRESHOLD_MIN,
                                            slot))
                continue

            recent = _sent_too_recently(cfg["key"])
            if recent is not None and send:
                _log("%s: last card went out %.1f min ago — skipping this tick "
                     "(min gap %d min). The room already has this."
                     % (cfg["key"], recent, C.MIN_SEND_GAP_MINUTES))
                continue

            seen_names += [str(r.get("name") or "").strip() for r in reps]
            png = render(cfg, reps, out_dir, slot)
            _log("%s: %d rep(s) over %d min -> %s"
                 % (cfg["key"], len(reps), C.GAP_THRESHOLD_MIN, png.name))
            try:
                # Resolution runs on a dry run too — it is read-only and it is
                # the half most likely to be wrong (Lucy removed from the chat,
                # the room renamed). A preview that skipped it proves nothing.
                res = tp.send_to_group(cfg["group"], "", [png],
                                       dry_run=not send)
                _log("  %s -> %r (%s participants)%s"
                     % ("TEXT" if send else "PREVIEW", res.get("resolved_name"),
                        res.get("participants"), "" if send else " — nothing sent"))
                if send:
                    # Stamped only after Messages actually took it, so a failed
                    # send never blocks the next tick from trying again.
                    _mark_sent(cfg["key"])
            except Exception as e:  # noqa: BLE001
                failures.append("%s text: %s: %s" % (cfg["key"],
                                                     type(e).__name__,
                                                     str(e)[:200]))
                _log("  TEXT FAILED: %s: %s" % (type(e).__name__, str(e)[:200]))
    _terminated_check_once(day, seen_names)
    return failures


def _terminated_check_once(day: dt.date, names: List[str]) -> None:
    """Flag anyone on the card who is on the 'Terminated ICDs' tab — ONCE a day,
    not on every tick. Advisory only: it never fails a tick, and it never
    changes what the card says.
    [[feedback_terminated_icd_check]]"""
    names = [n for n in dict.fromkeys(names) if n]
    if not names:
        return
    data = _state()
    key = day.isoformat()
    if (data.get("_terminated") or {}).get(key):
        return
    try:
        from automations.shared import terminated_icds as ti
        ti.alert_terminated(names, report_label="Rep Gap Alerts")
        data.setdefault("_terminated", {})[key] = True
        _save_state(data)
    except Exception as e:  # noqa: BLE001 — advisory, never fatal
        _log("terminated check skipped: %s: %s" % (type(e).__name__, str(e)[:120]))


def probe(day: dt.date, cfg: Dict, headless: bool = True) -> int:
    """READ-ONLY: what the Time Tracker endpoint actually returns right now.
    The one-pass answer when the card looks wrong or comes back empty."""
    from automations.shared.tableau_patchright import ownerville_session
    with ownerville_session(headless=headless, verbose=False,
                            profile_dir=C.PROFILE_DIR) as page:
        rqst = cap.capture_rqst(page)
        _pin_campaign(page, rqst, cfg.get("campaign_id", ""))
        rows = cap.fetch_time_tracking(page, rqst, day.strftime("%m/%d/%Y"))
    _log("office=%s rows=%d" % (cfg["key"], len(rows)))
    if rows:
        _log("keys=%s" % sorted(rows[0].keys()))
    for r in rows[:40]:
        _log("  %-28s gap=%-5s last=%s"
             % (str(r.get("name"))[:28], r.get("minutesSinceLastKnock"),
                r.get("lastKnockDate")))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--send", action="store_true",
                    help="text the group (default: render + resolve only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit preview (the default; here for the house flag)")
    ap.add_argument("--only", default="",
                    help="comma-separated office keys (default: all enabled)")
    ap.add_argument("--date", help="YYYY-MM-DD (default today)")
    ap.add_argument("--force", action="store_true",
                    help="run outside the selling-day window")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument("--probe", action="store_true",
                    help="READ-ONLY: dump the raw Time Tracker rows")
    args = ap.parse_args(argv)

    day = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
           if args.date else dt.date.today())
    send = args.send and not args.dry_run

    if args.probe:
        # Ahead of the window gate on purpose: you diagnose when you can, not
        # only between noon and 8.
        cfg = C.office(args.only) if args.only else C.enabled()[0]
        if not cfg:
            _log("no office %r" % args.only)
            return 1
        return probe(day, cfg, headless=not args.headed)

    if not args.force and not C.in_selling_window():
        _log("outside today's window (%s) — nothing to do" % C.window_label())
        return 0

    with Lock() as lock:
        if not lock.held:
            _log("another tick is still running — skipping this one")
            return 0
        failures = tick(day, send=send, only=args.only,
                        headless=not args.headed)

    if failures:
        _record_failure("; ".join(failures), dry_run=not send)
        _log("=== done (%d failure(s)) ===" % len(failures))
        return 1

    _clear_failures()
    if send:
        _publish_hub_once(day)
    _log("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
