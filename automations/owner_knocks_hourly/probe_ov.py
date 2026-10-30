"""READ-ONLY: do these owners' reps actually log knocks in OwnerVille?

Eve 2026-10-29: Jairo's, Drew's and Omar's Lucy ECO relay their knocks grid
empty almost every day -- is that their OwnerVille (nobody dispositions), or
the ECO read? This answers it from OUR side: impersonate each office on a
Lucy, read the last week's Disposition grid under BOTH campaigns (RES AT&T 3,
NDS 1), and count reps and knocks per day.

Omar was a rep under Salik Mallick until 10/26, so Salik's office is read too,
and any of Omar's SELLING reps (from his ECO sales relay) who knock under
Salik are named -- that is where his crew's knocks would be hiding.

Prints only; no Sheet, no Slack, no text.

    python -m automations.owner_knocks_hourly.probe_ov
    python -m automations.owner_knocks_hourly.probe_ov --days 3
    python -m automations.owner_knocks_hourly.probe_ov --colten

--colten (Raf 2026-10-30: "All of Jairo's reps are under Colten ... Leads are
under Colten and they distribute the leads to the reps from Colten's
Ownerville"): reads Colten's office instead, and names which of its knocking
reps are on Jairo's sales board (Miami book, tab JAIRO). Colten's ECO relay
showed only 5-10 reps a day of ~250 on the two boards -- this checks that
against OwnerVille itself.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, List

OFFICES = [
    # "Jairo J Ruiz Busquet" (office_metrics' knocks_office) is "name not
    # found" in Office Access on 10/29 -- try the plain name too.
    ("Jairo", "Jairo J Ruiz Busquet"),
    ("Jairo2", "Jairo Ruiz"),
    ("Drew", "Precision management Drew Tepper"),
    ("Omar", "Omar Mohamad"),
    ("Salik (Omar's old office)", "Salik Mallick"),
]
CAMPAIGNS = [("RES AT&T", "3"), ("NDS", "1")]

COLTEN_OFFICES = [("Colten", "Colten Wright")]
MIAMI_BOOK = "1KoKMoYy7oWWPHENFFvkT4qFg5z_m4m03nhvgvVTNKRY"
JAIRO_TAB = "JAIRO"


def _days(n: int) -> List[dt.date]:
    out, d = [], dt.date.today()
    while len(out) < n:
        d -= dt.timedelta(days=1)
        if d.weekday() != 6:        # no Sunday knocking
            out.append(d)
    return sorted(out)


def _knocks(rows: List[Dict]) -> int:
    from automations.icd_alerts import knocks_map as KM
    return sum(KM._int(r.get("Total Knocks")) for r in rows)


def _omar_sellers(days: List[dt.date]) -> set:
    try:
        from automations.icd_sales_board import relay_read as R
        relay = R.read_all().get("omar") or {}
        return {" ".join(n.split()).lower()
                for d in days for n in (relay.get(d) or {})}
    except Exception as e:  # noqa: BLE001
        print("(Omar's sales relay unreadable: %s)" % e)
        return set()


def _words(name) -> List[str]:
    return "".join(c for c in str(name or "").lower()
                   if c.isalpha() or c == " ").split()


def _jairo_board() -> List[List[str]]:
    """Column B of Jairo's board, as words ("Carlos Tucker PA" keeps its
    team tag, so a rep matches on first name + a later name)."""
    try:
        from automations.recruiting_report.fill import open_by_key
        col = open_by_key(MIAMI_BOOK).worksheet(JAIRO_TAB).col_values(2)
    except Exception as e:  # noqa: BLE001
        print("(Jairo's board unreadable: %s)" % e)
        return []
    return [w for w in (_words(n) for n in col[3:]) if len(w) >= 2]


def _on_board(rep, board: List[List[str]]) -> bool:
    a = _words(rep)
    if len(a) < 2:
        return False
    return any(a[0] == b[0] and (a[1] == b[1] or a[-1] in b[1:])
               for b in board)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=6)
    ap.add_argument("--colten", action="store_true",
                    help="read Colten's office; split out Jairo's reps")
    args = ap.parse_args(argv)
    offices = COLTEN_OFFICES if args.colten else OFFICES
    board = _jairo_board() if args.colten else []
    if args.colten:
        print("Jairo's board: %d names" % len(board))
    from automations.rashad_metrics.knocks_pull import pull_offices_days

    days = _days(args.days)
    jobs, labels = [], []
    for label, name in offices:
        for cname, cid in CAMPAIGNS:
            jobs.append((name, days, cid))
            labels.append((label, name, cname))
    print("days: %s .. %s" % (days[0], days[-1]))
    pulled = pull_offices_days(jobs, verbose=False, priority="normal")
    sellers = set() if args.colten else _omar_sellers(days)
    summary = []
    for (label, name, cname), (_n, by_day, err) in zip(labels, pulled):
        print("\n=== %s (%s) — campaign %s ===" % (label, name, cname))
        short = "%s %s" % (label.split()[0], cname.replace("RES ", ""))
        if err is not None:
            print("  PULL FAILED: %s: %s" % (type(err).__name__, str(err)[:300]))
            summary.append("%s FAIL(%s)" % (short, "no access" if "access"
                                             in str(err) else type(err).__name__))
            continue
        all_rows = [r for d in days for r in ((by_day or {}).get(d) or [])]
        summary.append("%s %dd/%dk" % (
            short, sum(1 for d in days if (by_day or {}).get(d)),
            _knocks(all_rows)))
        for d in days:
            rows = (by_day or {}).get(d) or []
            reps = [r.get("Rep") for r in rows if r.get("Rep")]
            line = "  %s %s: %d rep(s), %d knocks" % (
                d.strftime("%a"), d, len(reps), _knocks(rows))
            if board:
                mine = [r for r in rows if _on_board(r.get("Rep"), board)]
                line += " | Jairo's: %d rep(s), %d knocks" % (
                    len(mine), _knocks(mine))
            if reps:
                line += "  e.g. %s" % ", ".join(reps[:4])
            print(line)
        if board:
            mine = [r for r in all_rows if _on_board(r.get("Rep"), board)]
            summary.append("Jairo's %dk" % _knocks(mine))
        if label.startswith("Salik") and sellers:
            hit = sorted({r.get("Rep") for d in days
                          for r in ((by_day or {}).get(d) or [])
                          if " ".join(str(r.get("Rep") or "").split()).lower()
                          in sellers})
            print("  Omar's selling reps knocking HERE: %s"
                  % (", ".join(hit) or "none"))
            if hit:
                summary.append("Omar-sellers@Salik:%s" % ",".join(hit))
    # ONE LINE, LAST: the queue's status cell only shows the tail of a log.
    # "Nd/Mk" = days with any rep on the grid / knocks over the window.
    print("SUMMARY %d days: %s" % (len(days), " | ".join(summary)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
