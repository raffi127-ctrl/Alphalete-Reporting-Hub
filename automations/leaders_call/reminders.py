"""Leader's Call countdown — 3 Monday posts to the same channels as the deck.

Carlos Hidalgo, 2026-11-02: "can you make it so it sends 3 messages? one 15 mins
prior, one 5 mins prior and one as the call is starting?"

One LaunchAgent (com.alphalete.leaders-call-reminders) fires at 8:45, 8:55 and
9:00pm Central on Mondays; launchd can't pass a different argument per time, so
the clock picks the message — same shape as owners_call_reminder._is_final_time.

A fire outside its short window posts NOTHING. launchd catches up after a sleeping
machine (and this fleet has a history of jobs firing hours late), and "starts in
15 minutes" sent at 10pm is worse than no message.

    python -m automations.leaders_call.reminders                  # dry-run, by the clock
    python -m automations.leaders_call.reminders --slot 5         # dry-run that message
    python -m automations.leaders_call.reminders --send           # post (the plist)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from automations.leaders_call.run import CALL_TIME, FINAL_CHANNELS, ZOOM_URL

CENTRAL = ZoneInfo("America/Chicago")
STATE_DIR = Path(__file__).resolve().parents[2] / "output" / "leaders_call"
MONDAY = 0

# (minutes before the call, first minute it may post, last minute it may post)
# Minutes count from midnight Central. Keep these in step with the plist.
SLOTS = (
    (15, 20 * 60 + 45, 20 * 60 + 48),
    (5, 20 * 60 + 55, 20 * 60 + 58),
    (0, 21 * 60, 21 * 60 + 10),
)


def slot_for(now: dt.datetime):
    """Which reminder is due at `now` (Central)? 15, 5, 0 — or None for no post."""
    if now.weekday() != MONDAY:
        return None
    minute = now.hour * 60 + now.minute
    for slot, first, last in SLOTS:
        if first <= minute <= last:
            return slot
    return None


def message_for(slot: int) -> str:
    # Never reuse the deck's "Leader's Call — Weekly Recognition" header:
    # run._find_deck_ts finds the deck thread by that text, and a late --repost
    # would land under a reminder instead of the deck.
    if slot == 0:
        return f":rotating_light: The Leader's Call is starting NOW!  {ZOOM_URL}"
    return (f":wolf: The Leader's Call starts in {slot} minutes — "
            f"{CALL_TIME} tonight!  {ZOOM_URL}")


def _load_sent(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def send(slot: int, *, dry_run: bool, day: dt.date, client=None) -> int:
    """Post one reminder to every channel. A channel that already got this slot
    today is skipped, so a second fire can't double-post and a retry only fills
    the channel that failed. Returns 0, or 1 if any channel failed."""
    text = message_for(slot)
    state_path = STATE_DIR / f"reminders-{day.isoformat()}.json"
    sent = _load_sent(state_path)
    done = sent.setdefault(str(slot), [])
    failed = []
    for chan, cid in FINAL_CHANNELS:
        if dry_run:
            print(f"  [dry-run] WOULD post to #{chan} ({cid}): {text}", flush=True)
            continue
        if cid in done:
            print(f"  #{chan}: already posted this one today — skipped", flush=True)
            continue
        try:
            if client is None:
                from automations.shared import slack_metrics_post as smp
                client = smp._client()
            resp = client.chat_postMessage(channel=cid, text=text,
                                           unfurl_links=False, unfurl_media=False)
            if not resp.get("ok"):
                raise RuntimeError("ok=false")
            done.append(cid)
            print(f"  #{chan}: posted ✓", flush=True)
        except Exception as e:  # noqa: BLE001 — one channel must not stop the other
            print(f"  #{chan}: FAILED — {type(e).__name__}: {str(e)[:140]}", flush=True)
            failed.append(chan)
    if not dry_run:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(sent), encoding="utf-8")
    if failed:
        print(f"❌ Reminder failed in: {', '.join(failed)} — is Lucy a member?", flush=True)
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Leader's Call countdown posts.")
    ap.add_argument("--send", action="store_true",
                    help="Actually post (default is a dry-run).")
    ap.add_argument("--slot", type=int, choices=[15, 5, 0],
                    help="Pick the message by hand instead of by the clock.")
    args = ap.parse_args(argv)
    now = dt.datetime.now(CENTRAL)
    slot = args.slot if args.slot is not None else slot_for(now)
    if slot is None:
        print(f"Not a reminder time ({now:%a %H:%M} CT) — nothing to post.", flush=True)
        return 0
    return send(slot, dry_run=not args.send, day=now.date())


if __name__ == "__main__":
    sys.exit(main())
