"""Dry-run preview: consolidate a start-week's roster from BOTH D2D OBCL tabs,
run the real parser over a set of fadv emails, and print the forward-only diff
(what col K WOULD change to) plus the flag lists. Writes nothing.

Usage:
    python -m automations.bg_check_sync.preview --week 7/20/2026 \
        --events output/bg_events_sample_2026-07-20.json
"""
from __future__ import annotations

import argparse
import json
import sys

from automations.recruiting_report import fill
from automations.bg_check_sync import parse, match

SPREADSHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
ROLLING_TAB = "D2D OBCL"


def _dated_tab_name(week_date: str) -> str:
    # "7/20/2026" -> "D2D OBCL 7.20"
    m, d, *_ = week_date.strip().split("/")
    return f"D2D OBCL {int(m)}.{int(d)}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", required=True, help="start-week date header, e.g. 7/20/2026")
    ap.add_argument("--events", required=True, help="JSON list of {sender,subject,body,date}")
    args = ap.parse_args(argv)

    sh = fill.open_by_key(SPREADSHEET_ID)

    # --- build the consolidated roster (rolling block UNION dated tab) --------
    people = []
    rolling_vals = fill._retry(sh.worksheet(ROLLING_TAB).get_all_values)
    people += match.roster_block_from_rolling(rolling_vals, args.week, ROLLING_TAB)

    dated_name = _dated_tab_name(args.week)
    try:
        dated_vals = fill._retry(sh.worksheet(dated_name).get_all_values)
        people += match.roster_from_dated_tab(dated_vals, dated_name)
        dated_note = f"{dated_name} (found)"
    except Exception:
        dated_note = f"{dated_name} (not built yet)"

    roster = match.consolidate(people)

    # --- parse the emails ----------------------------------------------------
    raw = json.load(open(args.events, encoding="utf-8"))
    events = []
    for e in raw:
        ev = parse.classify(e.get("sender", ""), e.get("subject", ""),
                            e.get("body", ""), e.get("date", ""))
        if ev:
            events.append(ev)

    matched = match.match_events_to_people(roster, events)

    # --- decide + report -----------------------------------------------------
    changes, no_change, flags, adjudicate = [], [], [], []
    for p in sorted(roster, key=lambda x: (x.last.lower(), x.first.lower())):
        d = match.decide(p, matched[p.key])
        if d.new_status:
            changes.append(d)
        else:
            no_change.append(d)
        if d.flag:
            flags.append(d)
        if d.needs_adjudication:
            adjudicate.append(d)

    print(f"Week {args.week}  |  roster sources: {ROLLING_TAB} block + {dated_note}")
    print(f"Consolidated roster: {len(roster)} people  |  emails parsed: {len(events)}")
    print(f"Roster members with >=1 matched email: "
          f"{sum(1 for k in matched if matched[k])}\n")

    print(f"=== PROPOSED COL-K CHANGES ({len(changes)}) ===")
    for d in changes:
        locs = ", ".join(f"{t}!K{r}" for t, r in d.person.locations)
        print(f"  {d.person.last}, {d.person.first:16} {d.person.current or '(blank)':16}"
              f" -> {d.new_status:16} [{locs}]")

    print(f"\n=== NEEDS HUMAN PASS/FAIL CONFIRMATION ({len(adjudicate)}) ===")
    for d in adjudicate:
        print(f"  {d.person.last}, {d.person.first:16} report back (no Score email)")

    print(f"\n=== FLAGS — sheet says terminal but no matching email ({len(flags)}) ===")
    for d in flags:
        print(f"  {d.person.last}, {d.person.first:16} {d.flag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
