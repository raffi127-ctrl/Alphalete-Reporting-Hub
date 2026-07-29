"""Post the Weekly Promotion Check-In (or preview it).

    # read-only text preview (no Slack, no writes) — DEFAULT:
    python -m automations.promotion_checkin.run

    # DM the LIVE interactive card to one person to test-drive it:
    python -m automations.promotion_checkin.run --dm "Megan"

    # post to #alphalete-lvl1-chat for real (Monday 6pm):
    python -m automations.promotion_checkin.run --post
    # the 7:15pm final call:
    python -m automations.promotion_checkin.run --post --final-call

Whether a click actually WRITES the recognition sheet is controlled by the
PROMO_WRITE env var (the handler reads it), so a --dm test card can be left in
preview (writes nothing) until you flip it on.
"""
from __future__ import annotations

import argparse
import sys

from . import config as C
from . import board as B
from . import message as M


def _web():
    from automations.due_diligence.watch import _client
    return _client()


def _load():
    tab, week, reps = B.load_board()
    return week, B.eligible(reps)


def build_blocks(final_call: bool = False, preview: bool = False):
    week, elig = _load()
    return week, elig, M.build_message(week, B.by_team(elig),
                                       final_call=final_call, preview=preview)


def post(*, channel: str = None, dm_user: str = None, final_call: bool = False,
         preview: bool = False):
    week, elig, blocks = build_blocks(final_call, preview=preview)
    web = _web()
    ch = channel or C.CHANNEL_ID
    where = f"channel {ch}"
    if dm_user:
        from automations.shared.slack_metrics_post import _resolve_user_id
        uid = _resolve_user_id(web, dm_user)
        ch = web.conversations_open(users=uid)["channel"]["id"]
        where = f"DM to {dm_user}"
    fallback = f"Weekly Promotion Check-In — {week} — {len(elig)} reps eligible"
    resp = web.chat_postMessage(channel=ch, blocks=blocks, text=fallback)
    print(f"✅ Posted ({where}) — {len(elig)} eligible reps · ts={resp['ts']}")
    # A live channel post is a scheduled report -> mark the Hub card green.
    # [[feedback_launchd_reports_must_publish]] (skip for a preview DM).
    if not dm_user and not preview:
        try:
            from automations.day_orchestrator import hub_publish
            hub_publish.publish_done("promo_checkin", "Weekly Promotion Check-In",
                                     status="success")
        except Exception:
            pass
    return resp


def preview_text():
    week, elig = _load()
    groups = B.by_team(elig)
    print(f"WEEK: {week}   ELIGIBLE REPS: {len(elig)}\n")
    for team, reps in groups.items():
        print(f"  {team} ({len(reps)})")
        for r in reps:
            print(f"     {r.name:28} {r.level:12} → {r.next_level or '—':10} "
                  f"[{r.recognition or '—'}]  trainer: {r.trainer}")
    print("\nAt submit, each picked rep appends one row to the current "
          "recognition tab:\n  Rep | Trainer(board) | Owner="
          f"{C.OWNER!r} | Recognition(next level) | Notes(blank)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Weekly Promotion Check-In.")
    ap.add_argument("--post", action="store_true",
                    help="Post the live card to the channel (default: text preview only).")
    ap.add_argument("--final-call", action="store_true",
                    help="Post the 7:15pm final-call variant.")
    ap.add_argument("--dm", metavar="USER",
                    help="DM the live card to this user (id/email/name) to test it.")
    ap.add_argument("--channel", help="Override the channel id.")
    args = ap.parse_args()

    if args.dm:
        # A DM is a test-drive: preview-stamped, so a click never writes the sheet.
        post(dm_user=args.dm, final_call=args.final_call, preview=True)
    elif args.post:
        post(channel=args.channel, final_call=args.final_call, preview=False)
    else:
        preview_text()
    return 0


if __name__ == "__main__":
    sys.exit(main())
