"""Step 9 — the approval gate between building the week and entering it in Apex.

JD asked for "some sort of manual check before I update it". This is that check,
built the same shape as the bulletin and sales-board gates so there is one review
habit in the channel and not several:

    review_gate.py --post            post the week's review call in #l10-alphalete,
                                     then reply in-thread tagging JD with the link
    review_gate.py --check           has JD ticked it? exit 0 = approved
    review_gate.py                   dry run: print exactly what would be posted

WHO APPROVES: **JD ONLY** (Megan, 2026-09-04). A checkmark from anyone else leaves
the gate closed and releases nothing. Slack reports who reacted, so that is
enforceable rather than a convention. Note there are TWO "JD Mascorro" accounts in
this workspace; the live one is josh.mascorro17@gmail.com — tagging the other
would post into silence.

WHY THIS ONE NEEDS NO --refresh. The bulletin gate posts a PDF snapshot, so a
sheet corrected after the link went out needs the PDF rebuilt under the same link
or people approve a stale document. This gate links the LIVE workbook, so a
correction is visible the moment it is made and there is nothing to refresh. The
trade is the opposite risk — what JD ticked is not frozen — so --check reports
when the workbook was last modified against when the post went up.

WEEKLY, KEYED ON THE WEEK ENDING. The post's title carries "WE MM/DD/YY", which
is what makes it unique; --check finds --post's message by that title without
either run having to tell the other anything.
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

#: JD Mascorro, josh.mascorro17@gmail.com. The workspace also holds a second
#: "JD Mascorro" (U068T4LA0C8, jd.alphaletemarketing@gmail.com) which is NOT the
#: account he uses — confirmed by Megan 2026-09-04.
APPROVERS: Dict[str, str] = {"U05094TTPKQ": "JD Mascorro"}

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
    tags = " ".join(f"<@{uid}>" for uid in APPROVERS)
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
    outside APPROVERS falls through and the gate stays shut — that is the whole
    enforcement."""
    for rx in msg.get("reactions", []):
        if rx.get("name") not in APPROVE_EMOJI:
            continue
        for uid in rx.get("users", []):
            if uid in APPROVERS:
                return uid, APPROVERS[uid]
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
    """0 if JD has ticked it, 1 otherwise."""
    msg = _find_post(week, channel)
    if not msg:
        print(f"— no review post found for WE {week_label(week)}. Run --post first.")
        return 1
    who = _approver_of(msg)
    if not who:
        got = [f":{r['name']}: x{r['count']}" for r in msg.get("reactions", [])]
        print(f"— not approved yet (reactions: {', '.join(got) or 'none'}; "
              f"only {', '.join(APPROVERS.values())} can release this one)")
        return 1

    print(f"✓ approved by {who[1]} for WE {week_label(week)}")
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
                  f"what JD ticked is not what is in it now.")
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
    ap.add_argument("--check", action="store_true", help="has JD ticked it?")
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
    print(f"\n  approver: {', '.join(APPROVERS.values())} "
          f"({', '.join(APPROVERS)})")
    print("\n(dry run — nothing sent; add --post to send)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
