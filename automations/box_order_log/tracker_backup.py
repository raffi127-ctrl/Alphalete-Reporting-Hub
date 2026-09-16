"""BACK-UP daily BOX counts for when the Order Log view falls behind.

Why (2026-09-16): `BoxOrderLog` stopped at 9/10 while `BoxDailyTracker-RepLvl`
in the SAME workbook already had every sale through 9/14 — the Order Log view
was broken on its own, and everything that confirms BOX sales from it
(the Vantura Sales Board's morning pass) had nothing to confirm with. Eve's
call: keep the Order Log as the source, and fall back to the Rep Lvl tracker
when the log doesn't reach the day.

What it writes: a hidden "Lucy Box Tracker" tab on the Vantura board —
    Rep Name | Sale Date (M/D/YYYY) | Sales
one row per rep per day, Carlos's owner only. Rows for the days this pull
covers are replaced; older days are kept, so the tab keeps a few weeks.

Checked against the board on 2026-09-16: Mon 9/14 Joelle 3, Cinthya 2,
Esmeralda 2, Elizabeth 1, Gary 1 — identical to the Slack-filled cells.

TRAPS on this view (see alphalete_org_report/opt_box_daily.py for the long
version):
  * `Owner Name` is an EXCLUSIVE filter — never slice by URL; pull the whole
    grid and keep Carlos's rows here.
  * `Sale Date Weekending` can't be pinned, and the saved default is not
    stable (the same URL opened on WE 9/20 and then on WE 9/13, minutes
    apart). So the dates come from the export's own day headers, never from
    today — a pull that landed on last week simply doesn't cover yesterday,
    and the reader treats that as "no back-up", not as zero.
  * The day headers carry no year: 'Mon (09-14)'.

    python -m automations.box_order_log.tracker_backup              # dry-run
    python -m automations.box_order_log.tracker_backup --write
    python -m automations.box_order_log.tracker_backup --from-file x.csv
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "B2BBOXEnergyTracker/BoxDailyTracker-RepLvl?:iid=1")
CROSSTAB_SHEET = "Daily Tracker Sales - Rep Lvl"
OWNER = "carlos hidalgo"
TAB = "Lucy Box Tracker"
HEADER = ["Rep Name", "Sale Date", "Sales"]
COVERED = "(day covered)"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"

# English on the Lucys; the Spanish short names are what the same view shows
# in a Spanish browser, kept so a hand-exported file parses too.
_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5,
             "sun": 6, "lun": 0, "mar": 1, "mié": 2, "mie": 2, "jue": 3,
             "vie": 4, "sáb": 5, "sab": 5, "dom": 6}
_DAY_HDR = re.compile(r"^(\w{3})\.?\s*\((\d{1,2})-(\d{1,2})\)$")
_GRAND = ("grand total", "total", "total general")


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def _mdy(d: dt.date) -> str:
    return "{}/{}/{}".format(d.month, d.day, d.year)


def day_of(header: str, today: dt.date) -> Optional[dt.date]:
    """'Mon (09-14)' -> the date. The year is today's, stepped back one when
    that would put the day in the future (a January pull of December), and
    the weekday has to agree — a header that doesn't is not a day column."""
    m = _DAY_HDR.match(str(header or "").strip().lstrip("﻿"))
    if not m:
        return None
    wd = _WEEKDAYS.get(m.group(1).casefold())
    if wd is None:
        return None
    mm, dd = int(m.group(2)), int(m.group(3))
    for year in (today.year, today.year - 1):
        try:
            d = dt.date(year, mm, dd)
        except ValueError:
            continue
        if d.weekday() == wd and d <= today + dt.timedelta(days=1):
            return d
    return None


def parse(rows, today: Optional[dt.date] = None,
          owner: str = OWNER) -> Tuple[Dict[Tuple[str, dt.date], int],
                                       List[dt.date]]:
    """({(rep, day): sales}, [days the pull covers]) for one owner.

    `days` is every day column in the export, whether or not the owner sold
    that day — a covered day with no row for a rep means that rep sold 0.
    A blank cell is no sale; a '0' is Tableau's own zero (a sale that fell
    off) and counts as 0 too.
    """
    today = today or dt.date.today()
    hdr_i, cols = None, {}
    for i, row in enumerate(rows[:4]):
        found = {j: day_of(h, today) for j, h in enumerate(row)}
        found = {j: d for j, d in found.items() if d}
        if found:
            hdr_i, cols = i, found
            break
    if hdr_i is None:
        return {}, []
    names = [_norm(h) for h in rows[hdr_i]]
    i_rep = names.index("rep name") if "rep name" in names else 0
    i_own = names.index("owner name") if "owner name" in names else 1
    out: Dict[Tuple[str, dt.date], int] = {}
    for r in rows[hdr_i + 1:]:
        rep = str(r[i_rep] if i_rep < len(r) else "").strip()
        own = _norm(r[i_own] if i_own < len(r) else "")
        if not rep or _norm(rep) in _GRAND or own != owner:
            continue
        for j, d in cols.items():
            v = str(r[j] if j < len(r) else "").strip().replace(",", "")
            if not v:
                continue
            try:
                n = int(float(v))
            except ValueError:
                continue
            out[(rep, d)] = out.get((rep, d), 0) + n
    return out, sorted(set(cols.values()))


def merge(existing: List[List[str]], counts: Dict[Tuple[str, dt.date], int],
          days: List[dt.date]) -> List[List[str]]:
    """The tab's new body: old rows for days this pull does NOT cover, plus
    this pull's rows. Zero counts are dropped — no row = no sale."""
    fresh = {_mdy(d) for d in days}
    keep = [r[:3] for r in existing[1:]
            if len(r) >= 3 and r[1].strip() and r[1].strip() not in fresh]
    # One marker row per covered day: a day nobody sold on has no rep rows,
    # and the reader has to tell "covered, zero" from "not in the pull".
    new = [[COVERED, _mdy(d), "0"] for d in days]
    new += [[rep, _mdy(d), str(n)] for (rep, d), n in counts.items() if n > 0]

    def key(r):
        m, d, y = (int(x) for x in r[1].split("/"))
        return (dt.date(y, m, d), r[0].casefold())
    return [HEADER] + sorted(keep + new, key=key)


def pull(dest: Path, verbose: bool = True) -> Path:
    from automations.shared.tableau_patchright import tableau_session
    from automations.recruiting_report.opt_phase import drive_crosstab_dialog
    with tableau_session(verbose=verbose) as page:
        drive_crosstab_dialog(page, VIEW_URL, CROSSTAB_SHEET, dest,
                              verbose=verbose)
    return dest


def write(body: List[List[str]]) -> None:
    from automations.recruiting_report.fill import _retry
    from . import sheet
    ws = sheet._ensure_tab(sheet._open(), TAB, hidden=True, cols=3)
    _retry(lambda: ws.clear())
    _retry(lambda: ws.update(body, "A1:C{}".format(len(body)),
                             value_input_option="RAW"))


def read_tab(sh) -> List[List[str]]:
    import gspread
    try:
        return sh.worksheet(TAB).get_all_values()
    except gspread.WorksheetNotFound:
        return []


def covers(rows: List[List[str]], day: dt.date) -> bool:
    return any(len(r) >= 2 and r[0] == COVERED and r[1].strip() == _mdy(day)
               for r in rows[1:])


def counts_for(rows: List[List[str]], day: dt.date) -> Dict[str, int]:
    """{rep name: sales} off the tab for one covered day."""
    out: Dict[str, int] = {}
    for r in rows[1:]:
        if len(r) < 3 or r[0] == COVERED or r[1].strip() != _mdy(day):
            continue
        try:
            out[r[0]] = out.get(r[0], 0) + int(float(r[2]))
        except ValueError:
            continue
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true",
                    help="write the tab (default: dry-run, print only)")
    ap.add_argument("--from-file", metavar="CSV",
                    help="parse this crosstab instead of pulling Tableau")
    a = ap.parse_args(argv)

    today = dt.date.today()
    if a.from_file:
        src = Path(a.from_file)
    else:
        src = pull(OUTPUT_DIR / "box_tracker_replvl_{}.csv".format(
            today.isoformat()))
    from automations.alphalete_org_report.opt_nds import _read_tab_csv
    counts, days = parse(_read_tab_csv(src), today)
    if not days:
        print("tracker back-up: no day columns in the export — nothing to "
              "write", flush=True)
        return 1
    print("tracker back-up: export covers {} .. {}; {} sale(s) for Carlos"
          .format(days[0], days[-1], sum(counts.values())), flush=True)
    for (rep, d), n in sorted(counts.items(), key=lambda kv: (kv[0][1],
                                                              kv[0][0])):
        print("  {}  {:<32} {}".format(_mdy(d), rep, n), flush=True)
    if not a.write:
        print("DRY RUN — re-run with --write to fill '{}'".format(TAB),
              flush=True)
        return 0
    from . import sheet
    body = merge(read_tab(sheet._open()), counts, days)
    write(body)
    print("tracker back-up: wrote {} row(s) to '{}'".format(len(body) - 1,
                                                          TAB), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
