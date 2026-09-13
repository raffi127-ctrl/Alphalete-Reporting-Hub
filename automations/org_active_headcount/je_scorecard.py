"""Retail JE daily headcount off the JE REP Scorecard — Eve's rule, 2026-09-12.

THE RULE. Tableau `JEWeeklyTracker_17559651319030` -> view `JEREPScorecard`.
Pick the 'ICD Owner' filter = the owner, and COUNT how many reps belong to that
owner — the number is not printed in any column, it is a count of rep rows. The
next day, the same. The workbook only shows the CURRENT week, so JE has no
history to recover: the breakdown is collected day by day from the first run.

THIS FIRST VERSION ONLY PROBES. Nobody has looked at this view from code yet, so
before a count is trusted we need to see what its .csv export actually carries:
which columns, whether 'ICD Owner' is one of them (one download for every owner)
or the filter has to be driven per owner, and what dates it covers. `--probe`
downloads the export once and copies its header + rows into the 'HC JE Probe'
tab of the Mini Control workbook (a laptop can read that; `logtail` returns 470
characters). It writes nothing to the headcount board.

    python -m automations.org_active_headcount.je_scorecard --probe
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "output" / "_hc_je"
WORKBOOK = "JEWeeklyTracker_17559651319030"
VIEW = "JEREPScorecard"
VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            f"{WORKBOOK}/{VIEW}")
PROBE_TAB = "HC JE Probe"
# The dashboard TITLE says 'WTD Sales per Rep per Day'; the worksheet the
# Crosstab dialog offers is named differently (probe 2026-09-12: only
# ['Last Update', 'WTD Sales by Rep (2)']).
REP_SHEET = "WTD Sales by Rep (2)"
BOARD_OWNERS = ["Aiysha Mariano", "Alex Nicholas", "Brandon Stallkamp"]
OWNER_FILTER = "ICD Owner"


def download(params=None) -> Path:
    from automations.alphalete_org_report.tableau_http import download_view_csv
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    return download_view_csv(WORKBOOK, VIEW, OUT / f"je_rep_scorecard_{stamp}.csv",
                             params=params)


def probe() -> None:
    # Pulling a view this way passes the freshness gate, which would open a
    # staleness thread for a view nothing reads yet (see
    # project_je-opt-monday-fill-misses-sunday: probes dirtied that thread).
    os.environ.setdefault("ALPHALETE_SKIP_FRESHNESS", "1")
    # 1st probe (2026-09-12): the .csv endpoint only returns the dashboard's
    # first sheet — 'Last Update' ("Latest Sales Data Update: 9/11/2026"), with
    # or without the ICD Owner param. The rep table is another worksheet, so go
    # through the Crosstab dialog. Asking for a sheet that does not exist makes
    # the dialog error LIST every worksheet ("saw N thumb(s): [...]") — that is
    # the sheet census; then download each one that is not 'Last Update'.
    #
    # 2nd probe (same day): that dialog never opened — the viz toolbar's
    # Download button did not render in 120s on Lucy 1, so there was no
    # thumbnail list to read. So this 3rd probe does not depend on the toolbar:
    #   a) the vizportal API (getWorkbooks / getViews, the calls the Tableau UI
    #      itself makes — see recruiting_report/probe_b2b_views) lists every
    #      published view of the workbook;
    #   b) the view page is opened once to record which toolbar buttons exist
    #      and the text the dashboard renders;
    #   c) AFTER the browser closes (tableau_http cannot run inside a live
    #      session), the .csv endpoint is tried on every view found in (a).
    #
    # 3rd probe (same day) answered it: the view is 'JUST ENERGY - Sales per
    # Rep per Day' with an 'ICD Owner' filter and the worksheet 'WTD Sales per
    # Rep per Day'; the Download button DOES exist (it just renders late).
    # So this 4th probe downloads that worksheet's crosstab unfiltered and once
    # per board owner, filtering by URL, to see the rep rows it would count.
    import re
    from urllib.parse import quote
    from automations.shared.tableau_patchright import (
        tableau_session, download_crosstab_patchright)
    from automations.org_active_headcount.pull import _read_crosstab
    rows_out = []
    runs = [("(All)", VIEW_URL)] + [
        (o, f"{VIEW_URL}?{quote(OWNER_FILTER)}={quote(o)}") for o in BOARD_OWNERS]
    with tableau_session(verbose=False) as page:
        for label, url in runs:
            safe = re.sub(r"[^A-Za-z0-9]+", "_", label)
            try:
                path = download_crosstab_patchright(
                    url, REP_SHEET, OUT / f"je_reps_{safe}.csv", verbose=False, page=page)
                rows = _read_crosstab(path)
                print(f"{label}: {len(rows)} row(s)", flush=True)
                rows_out.append([f"== {REP_SHEET} | ICD Owner = {label}", f"{len(rows)} rows"])
                rows_out.extend(rows[:150])
            except Exception as e:                                 # noqa: BLE001
                print(f"{label}: FAILED {type(e).__name__}: {e}", flush=True)
                rows_out.append([f"== {REP_SHEET} | ICD Owner = {label}", "FAILED",
                                 f"{type(e).__name__}: {e}"[:300]])
    _to_sheet(PROBE_TAB, rows_out or [["probe produced nothing"]])


COUNTS_TAB = "HC JE Counts"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _num(s) -> float:
    try:
        return float(str(s).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def _key(s) -> str:
    return " ".join(str(s or "").lower().split())


def count_by_owner(rows, owners):
    """{owner: {'reps': [...], 'with_rows': n, 'with_sales': n, 'by_day': [n x7]}}.

    Pure — no I/O. `rows` is the 'WTD Sales by Rep (2)' crosstab: a header row
    carrying 'Rep Name', an ICD column, 'Grand Total' and the weekday columns,
    then one row per (rep, ICD). A rep can have a second row under another ICD
    with no numbers; only the row under the OWNER counts for that owner.

    Three readings, because 'count the reps of that owner' can mean more than
    one thing and Eve checks it by hand on the filtered view:
      with_rows  — distinct reps listed under the owner at all
      with_sales — of those, reps whose row has a Grand Total > 0
      by_day[i]  — reps that sold on any day up to weekday i (the running count
                   a snapshot taken that day would have shown)
    """
    hdr_i = next(i for i, r in enumerate(rows)
                 if any(_key(c) == "rep name" for c in r))
    hdr = [_key(c) for c in rows[hdr_i]]
    rep_c = hdr.index("rep name")
    icd_c = next(i for i, h in enumerate(hdr) if "icd" in h)
    tot_c = hdr.index("grand total") if "grand total" in hdr else None
    day_c = [hdr.index(d.lower()) if d.lower() in hdr else None for d in DAYS]
    out = {}
    for owner in owners:
        mine = [r for r in rows[hdr_i + 1:]
                if len(r) > max(rep_c, icd_c) and _key(r[icd_c]) == _key(owner)
                and _key(r[rep_c]) not in ("", "grand total")]
        reps = {}
        for r in mine:
            days = [_num(r[c]) if c is not None and c < len(r) else 0.0 for c in day_c]
            tot = _num(r[tot_c]) if tot_c is not None and tot_c < len(r) else sum(days)
            prev = reps.get(_key(r[rep_c]))
            if prev:
                days = [a + b for a, b in zip(prev["days"], days)]
                tot += prev["total"]
            reps[_key(r[rep_c])] = {"name": r[rep_c].strip(), "total": tot, "days": days}
        by_day = []
        for i in range(7):
            by_day.append(sum(1 for v in reps.values() if sum(v["days"][:i + 1]) > 0))
        out[owner] = {"reps": sorted(reps.values(), key=lambda v: -v["total"]),
                      "with_rows": len(reps),
                      "with_sales": sum(1 for v in reps.values() if v["total"] > 0),
                      "by_day": by_day}
    return out


def counts() -> None:
    """Download the rep sheet ONCE and write the per-owner counts, plus every
    rep behind each count so the number can be checked against the view."""
    os.environ.setdefault("ALPHALETE_SKIP_FRESHNESS", "1")
    from automations.shared.tableau_patchright import (
        tableau_session, download_crosstab_patchright)
    from automations.org_active_headcount.pull import _read_crosstab
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    with tableau_session(verbose=False) as page:
        path = download_crosstab_patchright(
            VIEW_URL, REP_SHEET, OUT / f"je_reps_counts_{stamp}.csv", verbose=False, page=page)
    rows = _read_crosstab(path)
    res = count_by_owner(rows, BOARD_OWNERS)
    table = [["owner", "reps listed", "reps with sales"] + [f"sold by {d[:3]}" for d in DAYS]]
    for owner, r in res.items():
        table.append([owner, r["with_rows"], r["with_sales"]] + r["by_day"])
        print(f"{owner}: listed {r['with_rows']}, with sales {r['with_sales']}, "
              f"by day {r['by_day']}", flush=True)
    table.append([])
    table.append(["owner", "rep", "week total"] + [d[:3] for d in DAYS])
    for owner, r in res.items():
        for v in r["reps"]:
            table.append([owner, v["name"], v["total"]] + v["days"])
    table.append([])
    table.append([f"source: {VIEW_URL} -> '{REP_SHEET}', {len(rows)} crosstab rows, "
                  f"downloaded {stamp}"])
    _to_sheet(COUNTS_TAB, table)


def _to_sheet(title, rows) -> None:
    from automations.org_active_headcount.tracker_readings import _to_sheet as write
    write(title, rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probe", action="store_true",
                    help="download the export and copy it to the 'HC JE Probe' tab")
    ap.add_argument("--counts", action="store_true",
                    help="count each board owner's reps into the 'HC JE Counts' tab")
    a = ap.parse_args(argv)
    if a.counts:
        counts()
    elif a.probe:
        probe()
    else:
        ap.error("pass --counts or --probe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
