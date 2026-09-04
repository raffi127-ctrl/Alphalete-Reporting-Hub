"""Steps 4 & 5 — put the week's DD and order log into tabs 1 and 2.

JD does this by hand twice: Tableau -> Direct Deposit ICD view -> DD Detail ->
Download -> Crosstab -> CSV -> paste; then the same again for the order log.
It is the slowest stretch of his Loom, most of it spent watching downloads.

Both crosstabs are already automated pulls elsewhere in the Hub, so neither
download needs doing by hand:

    DD        DirectDepositICDVIEWVersion2_0 / "ORG DD Detail"
    order log ATTTRACKER2_1-D2D/ORDERLOG    / "A.Order Log"  (ALLREPS)

Each is served from the harvest cache when today's pull is already primed, and
falls back to a live Tableau download otherwise — the same seam the office
metrics reports use. `--from-file` takes an already-downloaded crosstab instead,
which is both the test path and JD's escape hatch if Tableau automation breaks:
he downloads the way he does today and points this at the file.

TWO THINGS THIS CHECKS THAT A PASTE DOES NOT:

  * THE DD IS THE RIGHT WEEK. Tableau silently ignores a mis-valued filter and
    hands back its default latest week, so a paste can look perfect and be the
    wrong week entirely. The dominant `cl.DD Week` has to sit within a few days
    of the week being built, or nothing is written. (The DD week runs Saturday;
    a workbook named for Sunday 8.30 carries DD week 8/29.)

  * THE COLUMNS ARE STILL THERE. Every downstream formula finds its column by
    header text, so a renamed or dropped column doesn't error — it quietly
    yields blanks all the way to somebody's paycheck. The headers the workbook
    depends on are asserted present before the write.

Rows land so the HEADER row falls where each tab expects it (DD row 1, order
log row 2), rather than assuming the export's own leading blank lines.

    python -m automations.commission_sheet.sources --week 8.30
    python -m automations.commission_sheet.sources --week 8.30 --write
    python -m automations.commission_sheet.sources --week 8.30 \\
        --dd-file out/dd.tsv --order-log-file out/ol.tsv --write
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from automations.commission_sheet import config as C
from automations.commission_sheet.names import nrm

#: How far the DD week may sit from the workbook's week ending. The DD week is
#: the Saturday, the workbook is named for the Sunday, so 1 day is normal and
#: anything approaching a whole week apart is the wrong pull.
DD_WEEK_TOLERANCE_DAYS = 3

#: Columns the workbook's formulas look up by name. Missing one means silent
#: blanks downstream, so the write is refused instead.
DD_REQUIRED = [C.DD_REP, C.DD_CUSTOMER, C.DD_PRODUCTION_LOOKUP, C.DD_SALE_DATE,
               C.DD_TOTAL_TO_ICD, "cl.DD Week"]
OL_REQUIRED = [C.OL_SPM, C.OL_CUSTOMER, C.OL_REP, C.OL_SPE]

SCRATCH = Path("/tmp")


def read_crosstab(path: Path) -> List[List[str]]:
    """Tableau exports UTF-16 tab-separated, sometimes UTF-8/comma."""
    from automations.override_bulletin.pulls import read_crosstab as _read
    return _read(str(path))


def header_row_index(rows: Sequence[Sequence[str]], required: Sequence[str]) -> int:
    """Index of the row that carries the column headers.

    Found by CONTENT, not position: exports vary in how many banner or blank
    lines they put on top, and guessing an offset is how a whole sheet ends up
    one row out."""
    want = {nrm(r) for r in required}
    best, best_hits = -1, 0
    for i, row in enumerate(rows[:10]):
        hits = len(want & {nrm(c) for c in row})
        if hits > best_hits:
            best, best_hits = i, hits
    if best_hits < max(2, len(want) // 2):
        raise RuntimeError(
            f"No header row found in the first 10 lines — looked for "
            f"{list(required)}. Is this the right crosstab?")
    return best


def missing_columns(header: Sequence[str], required: Sequence[str]) -> List[str]:
    have = {nrm(c) for c in header}
    return [r for r in required if nrm(r) not in have]


def _parse_date(text) -> Optional[dt.date]:
    text = str(text or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%b %d, %Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def dominant_dd_week(rows: Sequence[Sequence[str]], header_idx: int
                     ) -> Tuple[Optional[dt.date], int, int]:
    """(most common cl.DD Week, its count, total rows counted)."""
    header = list(rows[header_idx])
    try:
        col = [nrm(c) for c in header].index(nrm("cl.DD Week"))
    except ValueError:
        return None, 0, 0
    counts = collections.Counter()
    for row in rows[header_idx + 1:]:
        if col < len(row):
            d = _parse_date(row[col])
            if d:
                counts[d] += 1
    if not counts:
        return None, 0, 0
    week, n = counts.most_common(1)[0]
    return week, n, sum(counts.values())


def fetch_dd(out: Optional[Path] = None) -> Path:
    """Harvest cache if primed, else a live Tableau download (JD's own path:
    the unfiltered DD Detail, which defaults to the latest week)."""
    from automations.harvest import adapter as _hv
    from automations.pay_structure.dd_pull import DD_SHEET, DD_VIEW
    out = Path(out or SCRATCH / "commission_dd.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    if _hv.try_cache_view(DD_VIEW, DD_SHEET, out) is None:
        from automations.shared.tableau_patchright import download_crosstab_patchright
        download_crosstab_patchright(DD_VIEW, DD_SHEET, out)
    return out


def fetch_order_log(out: Optional[Path] = None) -> Path:
    from automations.harvest import adapter as _hv
    from automations.uploaded import order_log as _ol
    out = Path(out or SCRATCH / "commission_order_log.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    url = _ol.ALLREPS_VIEW_URL_TMPL.format(start=_ol.START_DATE.isoformat(),
                                           end=_ol.END_DATE.isoformat())
    if _hv.try_cache_view(url, _ol.CROSSTAB_SHEET, out) is None:
        from automations.shared.tableau_patchright import download_crosstab_patchright
        download_crosstab_patchright(url, _ol.CROSSTAB_SHEET, out)
    return out


def _assess(path: Path, required: Sequence[str], label: str) -> Dict:
    rows = read_crosstab(path)
    if not rows:
        raise RuntimeError(f"{label}: {path} is empty")
    idx = header_row_index(rows, required)
    header = list(rows[idx])
    return {"path": path, "rows": rows, "header_idx": idx, "header": header,
            "missing": missing_columns(header, required),
            "data_rows": max(0, len(rows) - idx - 1), "label": label}


def plan(week: dt.date, dd_file: Optional[Path] = None,
         ol_file: Optional[Path] = None, workbook_id: str = C.WORKBOOK_ID) -> Dict:
    dd = _assess(dd_file or fetch_dd(), DD_REQUIRED, "DD")
    dd_week, n, total = dominant_dd_week(dd["rows"], dd["header_idx"])
    dd["week"] = dd_week
    dd["week_count"] = n
    dd["week_total"] = total
    dd["week_ok"] = bool(dd_week and abs((dd_week - week).days) <= DD_WEEK_TOLERANCE_DAYS)

    ol = _assess(ol_file or fetch_order_log(), OL_REQUIRED, "Order log")
    return {"week": week, "dd": dd, "ol": ol, "workbook_id": workbook_id}


def report(p: Dict) -> str:
    dd, ol = p["dd"], p["ol"]
    out = [f"\nBuilding week ending {p['week']:%a %d %b %Y}",
           f"\n  DD         {dd['data_rows']:>6} row(s)   header on line "
           f"{dd['header_idx'] + 1}   {dd['path']}"]
    if dd["week"]:
        drift = (dd["week"] - p["week"]).days
        mark = "OK" if dd["week_ok"] else "WRONG WEEK"
        out.append(f"             dominant cl.DD Week {dd['week']:%m/%d/%Y} "
                   f"({dd['week_count']}/{dd['week_total']} rows, "
                   f"{drift:+d} day(s))  {mark}")
    else:
        out.append("             !! no readable cl.DD Week — cannot confirm the week")
    if dd["missing"]:
        out.append(f"             !! missing column(s): {dd['missing']}")

    out.append(f"\n  Order log  {ol['data_rows']:>6} row(s)   header on line "
               f"{ol['header_idx'] + 1}   {ol['path']}")
    if ol["missing"]:
        out.append(f"             !! missing column(s): {ol['missing']}")

    blockers = _blockers(p)
    out.append("\n  READY" if not blockers else "\n  BLOCKED")
    for b in blockers:
        out.append(f"    ✗ {b}")
    return "\n".join(out)


def _blockers(p: Dict) -> List[str]:
    dd, ol = p["dd"], p["ol"]
    out = []
    if not dd["week_ok"]:
        out.append(f"the DD is week {dd['week']} but this workbook is for "
                   f"{p['week']} — wrong pull, refusing to paste it")
    if dd["missing"]:
        out.append(f"DD is missing {dd['missing']}")
    if ol["missing"]:
        out.append(f"order log is missing {ol['missing']}")
    if dd["data_rows"] <= 0:
        out.append("DD has no data rows")
    if ol["data_rows"] <= 0:
        out.append("order log has no data rows")
    return out


def _write_tab(sh, tab: str, rows: List[List[str]], header_idx: int,
               header_row: int) -> int:
    """Write so the crosstab's header lands on the tab's expected header row."""
    ws = sh.worksheet(tab)
    pad = header_row - 1                       # blank rows above the header
    body = rows[header_idx:]
    width = max(len(r) for r in body)
    grid = [[""] * width for _ in range(pad)]
    grid += [list(r) + [""] * (width - len(r)) for r in body]
    ws.clear()
    ws.update(values=grid, range_name="A1", value_input_option="USER_ENTERED")
    return len(body) - 1


def apply(p: Dict) -> Dict:
    blockers = _blockers(p)
    if blockers:
        raise RuntimeError("Refusing to write: " + "; ".join(blockers))
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(p["workbook_id"])
    dd_n = _write_tab(sh, C.TAB_DD, p["dd"]["rows"], p["dd"]["header_idx"],
                      C.DD_HEADER_ROW)
    ol_n = _write_tab(sh, C.TAB_ORDER_LOG, p["ol"]["rows"], p["ol"]["header_idx"],
                      C.OL_HEADER_ROW)
    return {"dd": dd_n, "ol": ol_n}


def _parse_week(text: str) -> dt.date:
    m = re.match(r"^\s*(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\s*$", text)
    if not m:
        raise argparse.ArgumentTypeError(f"Use M.D (e.g. 8.30), got {text!r}")
    month, day = int(m.group(1)), int(m.group(2))
    year = int(m.group(3)) if m.group(3) else dt.date.today().year
    year += 2000 if year < 100 else 0
    return dt.date(year, month, day)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--week", type=_parse_week, required=True,
                    help="week ending as M.D (e.g. 8.30)")
    ap.add_argument("--workbook", default=C.WORKBOOK_ID)
    ap.add_argument("--dd-file", type=Path, help="use this crosstab instead of pulling")
    ap.add_argument("--order-log-file", type=Path, help="ditto for the order log")
    ap.add_argument("--write", action="store_true", help="paste into the workbook")
    args = ap.parse_args(argv)

    p = plan(args.week, dd_file=args.dd_file, ol_file=args.order_log_file,
             workbook_id=args.workbook)
    print(report(p))
    if not args.write:
        print("\n(dry run — nothing written; add --write to paste)")
        return 0 if not _blockers(p) else 1
    done = apply(p)
    print(f"\nPasted {done['dd']} DD row(s) and {done['ol']} order-log row(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
