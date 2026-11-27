"""Card step 4.2: the side-by-side test week.

Megan 2026-11-27: "run it for the next week and make sure it matches before
taking it live", then "Lucy first" (a Lucy's AppStream login stays signed in;
the move to the offices' own computers comes at the end).

Each evening, Mon-Sat after 7:00 PM Central (the interviewers have typed the
day by then), once a day:
  1. fills the TEST COPY's week from AppStream (run.fill_week), so the copy
     always shows what the automation would have written;
  2. compares this week so far: AppStream vs what the interviewers typed on
     the REAL ARS tab (read only, never written);
  3. sends Megan, and only Megan, a short summary in a Lucy DM (11/27: previews
     go to her alone, never a test channel).

    python -m automations.interviewer_retention.parallel --office 11280            # print only
    python -m automations.interviewer_retention.parallel --office 11280 --dm       # and DM Megan
    python -m automations.interviewer_retention.parallel --office 11280 --due --dm # the timer's tick
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Dict, List
from zoneinfo import ZoneInfo

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.interviewer_retention import boxes as bx
from automations.interviewer_retention import check as ck
from automations.interviewer_retention import compare as cmp
from automations.interviewer_retention import read as rd
from automations.interviewer_retention import run as runner
from automations.interviewer_retention import write as wr

CENTRAL = ZoneInfo("America/Chicago")
AFTER = dt.time(19, 0)
MEGAN = "U04G5HJBGFN"                      # resources/owner-slack-ids.md
LEDGER = rd.OUT_DIR / "parallel_done.json"
COPY_URL = f"https://docs.google.com/spreadsheets/d/{wr.TEST_COPY}/edit"


def _done() -> List[str]:
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8")).get("days", [])
    except Exception:  # noqa: BLE001
        return []


def _mark(day: dt.date) -> None:
    rd.OUT_DIR.mkdir(parents=True, exist_ok=True)
    days = (_done() + [day.isoformat()])[-60:]
    LEDGER.write_text(json.dumps({"days": days}, indent=1), encoding="utf-8")


def due(now: dt.datetime) -> bool:
    return now.weekday() < 6 and now.time() >= AFTER and now.date().isoformat() not in _done()


def summary(office: str, owner: str, day: dt.date, mine: Dict, theirs: Dict, flags: List[str]) -> str:
    t = {b: (cmp._tot(mine[b], b), cmp._tot(theirs[b], b)) for b in ck.BLOCKS}
    pair = lambda b, k: f"{t[b][0][k]} / {t[b][1][k]}"            # noqa: E731
    agree = total = 0
    for b in ck.BLOCKS:
        c1, c2 = cmp._cells(mine[b]), cmp._cells(theirs[b])
        for key in set(c1) | set(c2):
            total += 1
            agree += int(c1.get(key, 0) == c2.get(key, 0))
    monday = runner.week_of(day) - dt.timedelta(days=6)
    lines = [f":test_tube: *Interviewer Retention: test week*  {owner} ({office}), "
             f"Mon {monday.month}/{monday.day} to {day:%a} {day.month}/{day.day}",
             "_AppStream / typed by the interviewers_",
             f"• Qualified {pair('qualified', 'Q')}  ·  Disqualified {pair('qualified', 'Di')}  ·  "
             f"Declined {pair('qualified', 'De')}",
             f"• Answered {pair('answered', 'A')}  ·  Booked to 2nd {pair('answered', 'B')}",
             f"• 2nd round: Booked {pair('second', 'B')}  ·  Showed {pair('second', 'S')}  ·  "
             f"No Show {pair('second', 'NS')}  ·  Reschedule {pair('second', 'RR')}  ·  "
             f"Cancelled {pair('second', 'C')}",
             f"• Per interviewer, per day: {100 * agree / max(total, 1):.0f}% identical"]
    lines += [f":warning: {f}" for f in flags]
    lines.append(f"<{COPY_URL}|Test copy> (the real ARS tab is not touched)")
    return "\n".join(lines)


def dm_megan(text: str) -> str:
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    channel = client.conversations_open(users=MEGAN)["channel"]["id"]
    return client.chat_postMessage(channel=channel, text=text).get("ts", "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="interviewer_retention.parallel")
    ap.add_argument("--office", default="11280")
    ap.add_argument("--date", default="", help="YYYY-MM-DD (default: today, Central)")
    ap.add_argument("--due", action="store_true", help="the timer's tick: only Mon-Sat after 7 PM CT, once a day")
    ap.add_argument("--dm", action="store_true", help="send the summary to Megan's DM")
    a = ap.parse_args(argv)
    now = dt.datetime.now(CENTRAL)
    if a.due and not due(now):
        return 0
    day = dt.date.fromisoformat(a.date) if a.date else now.date()

    got = runner.fill_week(a.office, day, sheet=wr.TEST_COPY, dry_run=False, show=lambda *x: None)
    from automations.recruiting_report.fill import open_by_key
    real = open_by_key(got["wb_id"]).worksheet(got["tab"])
    typed = ck.interviews(real.get_all_values(value_render_option="UNFORMATTED_VALUE"))
    theirs = bx.week(typed, got["anchor"])
    text = summary(a.office, got["owner"], day, got["boxes"], theirs, got["flags"])
    print(text)
    if a.dm:
        dm_megan(text)
        print("sent to Megan's DM")
    if a.due:
        _mark(now.date())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
