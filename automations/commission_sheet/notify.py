"""Step 9 — tell JD the week is ready for review.

JD asked for "some sort of manual check before I update it". Today that check is
just him looking: nothing downstream is released or sent on his say-so, so this
posts a notification and stops there (Megan, 2026-09-04).

    notify.py --post          post it
    notify.py                 dry run: print exactly what would be posted

It posts one clean line to #l10-alphalete:

    Payroll Commission Processing Ready for Review WE MM/DD/YY

and then replies IN-THREAD tagging JD with the workbook link — two messages on
purpose, so the channel stays scannable while the ping and the link he actually
needs sit together in the thread.

Careful with the tag: the workspace holds TWO "JD Mascorro" accounts. The live
one is josh.mascorro17@gmail.com; tagging the other posts into silence. A test
pins which one we use.

Re-running is safe. A post for a week that already has one is not duplicated —
the title carries "WE MM/DD/YY", which is what makes it unique and what lets a
later run find it without either run recording anything.

NOT A GATE, for now. `--check` below reads whether JD has ticked the post, but
nothing consults it: no step refuses to run without his tick. It exists because
step 11 (entering payroll in Apex) is the thing that will eventually want
gating, and reading reactions is the part worth having ready. Until something
actually calls it, treat this module as a notification.
"""
from __future__ import annotations

import argparse
import datetime as dt
from typing import Dict, List, Optional, Tuple

from automations.commission_sheet import config as C

#: #l10-alphalete — Megan, 2026-09-04. Hardcoded like the other gates: the
#: reporting token can neither create a channel nor look one up by name, and a
#: rename keeps the id.
REVIEW_CHANNEL = "C075PCEL92M"

#: Who gets tagged. JD Mascorro, josh.mascorro17@gmail.com. The workspace also
#: holds a second "JD Mascorro" (U068T4LA0C8, jd.alphaletemarketing@gmail.com)
#: which is NOT the account he uses — confirmed by Megan 2026-09-04.
NOTIFY: Dict[str, str] = {"U05094TTPKQ": "JD Mascorro"}

#: Any of Slack's ticks: nobody should have to remember which green check is
#: "the" one, and picking the wrong one must not silently read as "not yet".
APPROVE_EMOJI = {"white_check_mark", "heavy_check_mark",
                 "ballot_box_with_check", "check"}

TITLE = "Payroll Commission Processing Ready for Review WE {week}"


def week_label(week: dt.date) -> str:
    """MM/DD/YY, zero-padded (Megan's wording). Built by hand rather than with
    strftime because %-m and %-d are not portable to Windows."""
    return f"{week.month:02d}/{week.day:02d}/{week.year % 100:02d}"


def title_for(week: dt.date) -> str:
    return TITLE.format(week=week_label(week))


def sheet_link(workbook_id: str = C.WORKBOOK_ID) -> str:
    return f"https://docs.google.com/spreadsheets/d/{workbook_id}/edit"


def reply_for(workbook_id: str = C.WORKBOOK_ID) -> str:
    tags = " ".join(f"<@{uid}>" for uid in NOTIFY)
    return f"{tags} {sheet_link(workbook_id)}"


def _client():
    from automations.shared.slack_metrics_post import _client as c
    return c()


def _find_post(week: dt.date, channel: str = REVIEW_CHANNEL) -> Optional[dict]:
    """This week's post, by title. Another report's message in the same channel
    can never be mistaken for it."""
    want = title_for(week)
    hist = _client().conversations_history(channel=channel, limit=100)
    for m in hist.get("messages", []):
        if (m.get("text") or "").lstrip("*").startswith(want):
            return m
    return None


def _approver_of(msg: dict) -> Optional[Tuple[str, str]]:
    """(id, name) of the first AUTHORISED tick, else None. A tick from anyone
    outside NOTIFY falls through and the gate stays shut — that is the whole
    enforcement."""
    for rx in msg.get("reactions", []):
        if rx.get("name") not in APPROVE_EMOJI:
            continue
        for uid in rx.get("users", []):
            if uid in NOTIFY:
                return uid, NOTIFY[uid]
    return None


def post(week: dt.date, workbook_id: str = C.WORKBOOK_ID,
         channel: str = REVIEW_CHANNEL, verbose: bool = True) -> str:
    """Post the review call, then reply in-thread tagging JD with the link.

    Two messages on purpose: the channel gets one clean scannable line, and the
    tag that pings JD sits in the thread with the link he actually needs."""
    existing = _find_post(week, channel)
    if existing:
        who = _approver_of(existing)
        if verbose:
            print(f"— already posted for WE {week_label(week)} "
                  f"(ts={existing['ts']})"
                  + (f", approved by {who[1]}" if who else ", not yet approved"))
        return existing["ts"]

    cli = _client()
    top = cli.chat_postMessage(channel=channel, text=title_for(week),
                               unfurl_links=False)
    cli.chat_postMessage(channel=channel, thread_ts=top["ts"],
                         text=reply_for(workbook_id), unfurl_links=False)
    if verbose:
        print(f"✓ posted to {channel} ts={top['ts']} and replied with the link")
    return top["ts"]


def check(week: dt.date, workbook_id: str = C.WORKBOOK_ID,
          channel: str = REVIEW_CHANNEL) -> int:
    """0 if JD has ticked the post, 1 otherwise.

    NOTHING CALLS THIS TODAY — no step refuses to run without his tick. It is
    here for whenever the Apex entry wants gating; until then it is a way to
    ask "has he looked at it yet", not a control."""
    msg = _find_post(week, channel)
    if not msg:
        print(f"— no review post found for WE {week_label(week)}. Run --post first.")
        return 1
    who = _approver_of(msg)
    if not who:
        got = [f":{r['name']}: x{r['count']}" for r in msg.get("reactions", [])]
        print(f"— not ticked yet (reactions: {', '.join(got) or 'none'})")
        return 1

    print(f"✓ ticked by {who[1]} for WE {week_label(week)}")
    # The link is to the LIVE workbook, so what was ticked is not frozen. Say
    # plainly whether it moved after the post went up.
    try:
        from automations.commission_sheet.drive_auth import service
        meta = service().files().get(fileId=workbook_id, fields="modifiedTime",
                                     supportsAllDrives=True).execute()
        modified = dt.datetime.fromisoformat(
            meta["modifiedTime"].replace("Z", "+00:00"))
        posted = dt.datetime.fromtimestamp(float(msg["ts"]), dt.timezone.utc)
        if modified > posted:
            mins = int((modified - posted).total_seconds() // 60)
            print(f"  note: the workbook was edited {mins} min after the post — "
                  f"what JD saw is not what is in it now.")
    except Exception as e:  # noqa: BLE001 — never fail the gate on a metadata read
        print(f"  (could not read the workbook's modified time: {type(e).__name__})")
    return 0


def _parse_week(text: str) -> dt.date:
    import re
    m = re.match(r"^\s*(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\s*$", text)
    if not m:
        raise argparse.ArgumentTypeError(f"Use M.D (e.g. 9.6), got {text!r}")
    month, day = int(m.group(1)), int(m.group(2))
    year = int(m.group(3)) if m.group(3) else dt.date.today().year
    year += 2000 if year < 100 else 0
    return dt.date(year, month, day)


def _last_sunday(today: Optional[dt.date] = None) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--week", type=_parse_week, default=None,
                    help="week ending as M.D (default: the Sunday just gone)")
    ap.add_argument("--workbook", default=C.WORKBOOK_ID)
    ap.add_argument("--channel", default=REVIEW_CHANNEL)
    ap.add_argument("--post", action="store_true", help="post it")
    ap.add_argument("--check", action="store_true",
                    help="has JD ticked the post? (reports only — gates nothing)")
    args = ap.parse_args(argv)

    week = args.week or _last_sunday()
    if args.check:
        return check(week, args.workbook, args.channel)
    if args.post:
        post(week, args.workbook, args.channel)
        return 0

    print(f"\nWould post to {args.channel} (#l10-alphalete):\n")
    print(f"  {title_for(week)}")
    print(f"\n  └ reply in thread:\n     {reply_for(args.workbook)}")
    print(f"\n  tagging: {', '.join(NOTIFY.values())} ({', '.join(NOTIFY)})")
    print("\n(dry run — nothing sent; add --post to send)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
