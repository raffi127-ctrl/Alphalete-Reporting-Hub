"""Second source: the D2D ORDER LOG, one row per sale.

WHY WE MOVED HERE. PRODUCT SALES SUMMARY 4WK is filtered by a DISCRETE week
dropdown ('Sale Date Week Ending'), and that filter is silently discarded when
sent in the url: the export comes back from Tableau's own default window, so on
2026-08-14 the module wrote another period's numbers into Sanborn's row (21
units Tue-Fri where the asked-for week is 10 units Mon-Thu). Driving the control
instead is not an option either -- that dashboard's quick filters expose no
aria-label, so there is nothing for a pre_export hook to grab.

The ORDER LOG has neither problem:
  * its date filters are a RANGE (Start Date / End Date), the shape that
    already works over the url in att_order_log;
  * it downloads as a DIRECT .csv, so the flaky Crosstab dialog -- the one that
    kept coming back with zero sheets -- is out of the picture entirely;
  * it is one row per sale, carrying the rep name, so the rep is selected HERE,
    in code, against a column we can see. No url filter to trust.

Cross-checking is therefore possible in a way it never was with the summary: a
day's count is a number of ROWS we can name, not a cell we hope was filtered.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from pathlib import Path
from typing import Dict, List

VIEW_CSV = ("https://us-east-1.online.tableau.com/t/sci/views/"
            "ATTTRACKER2_1-D2D/ORDERLOG.csv")

# Column captions we need. Looked up by label at read time, never by position:
# the same log in the B2B workbook exports 47 columns and the order drifts.
# Several spellings are accepted because the two workbooks caption them
# differently (att_order_log reads 'sp.Order Date (copy)').
REP_COLUMNS = ("Rep", "Rep Name", "sp.Rep", "Sales Rep")
DATE_COLUMNS = ("sp.Order Date (copy)", "Order Date", "sp.Order Date",
                "Sale Date")
PRODUCT_COLUMNS = ("Product Type (Broken Out)", "Product Type",
                   "sp.Product Type (Broken Out)")

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"]


def csv_url(start: dt.date, end: dt.date) -> str:
    """Range date filters, ISO -- the form att_order_log proved works."""
    return (f"{VIEW_CSV}?:refresh=yes"
            f"&Start%20Date={start.isoformat()}&End%20Date={end.isoformat()}")


def _norm(s: str) -> str:
    return " ".join(str(s or "").replace(" ", " ").split()).strip()


def read_rows(path) -> List[List[str]]:
    for enc, delim in (("utf-8-sig", ","), ("utf-16", "\t"), ("utf-8", "\t")):
        try:
            with open(path, "r", encoding=enc, newline="") as fh:
                rows = [r for r in csv.reader(fh, delimiter=delim)]
            if any(len(r) > 1 for r in rows):
                return rows
        except (UnicodeError, UnicodeDecodeError):
            continue
    raise RuntimeError(f"could not decode the order log at {path}")


def _find_col(header: List[str], candidates) -> int:
    low = [_norm(h).lower() for h in header]
    for want in candidates:
        w = want.lower()
        if w in low:
            return low.index(w)
    # Loose second pass: the caption sometimes carries a prefix or a suffix.
    for want in candidates:
        w = want.lower()
        for j, h in enumerate(low):
            if w in h or h in w:
                return j
    return -1


def _parse_date(s: str):
    t = _norm(s)
    if not t:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%B %d, %Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def _rep_matches(cell: str, rep: str) -> bool:
    """'Andrew Sanborn' should also match 'Sanborn, Andrew' and
    'Andrew Sanborn Roadtrip' -- the same person is spelled three ways across
    ownerville, Tableau and the board (see the module memory)."""
    a = set(re.sub(r"[^a-z ]", " ", _norm(cell).lower()).split())
    b = set(re.sub(r"[^a-z ]", " ", _norm(rep).lower()).split())
    return bool(b) and b <= a


def daily_counts(path, rep: str, product_to_metric: Dict[str, str],
                 start: dt.date = None, end: dt.date = None) -> tuple:
    """-> ({weekday: {metric: n}}, stats)

    Counts ROWS, so every number is traceable back to named sales.

    `start`/`end` are not a second filter -- they are the PROOF that the first
    one applied. Tableau restores whatever state the signed-in user last left
    on a view, and Lucy 2 signs in as Carlos Hidalgo, so a url filter can be
    accepted, ignored, and silently answered with his remembered window (that
    is how January data reached this module). A sale dated outside the window
    we asked for is that failure, visible: stats['out_of_range'] counts them and
    the caller HOLDs. Row dates make it checkable; the summary crosstab, which
    only ever showed weekday names, could not be checked at all.
    """
    rows = read_rows(path)
    if not rows:
        raise RuntimeError("the order log export is empty")
    header = rows[0]
    ci_rep = _find_col(header, REP_COLUMNS)
    ci_date = _find_col(header, DATE_COLUMNS)
    ci_prod = _find_col(header, PRODUCT_COLUMNS)
    missing = [name for name, idx in (("rep", ci_rep), ("date", ci_date),
                                      ("product", ci_prod)) if idx < 0]
    if missing:
        raise RuntimeError(
            "order log is missing the {} column(s). Header was: {}".format(
                "/".join(missing), header[:25]))

    out: Dict[str, Dict[str, int]] = {}
    stats = {"rows": 0, "mine": 0, "reps_seen": set(), "unmapped": [],
             "no_date": 0, "out_of_range": 0, "dates_seen": []}
    for r in rows[1:]:
        if len(r) <= max(ci_rep, ci_date, ci_prod):
            continue
        stats["rows"] += 1
        stats["reps_seen"].add(_norm(r[ci_rep]))
        if not _rep_matches(r[ci_rep], rep):
            continue
        d = _parse_date(r[ci_date])
        if d is None:
            stats["no_date"] += 1
            continue
        if d not in stats["dates_seen"]:
            stats["dates_seen"].append(d)
        # The window check, on OUR side of the wire. See the docstring: a url
        # date filter can be answered with somebody's remembered window, and on
        # this workbook that window was January.
        if (start and d < start) or (end and d > end):
            stats["out_of_range"] += 1
            continue
        prod = _norm(r[ci_prod]).upper()
        metric = product_to_metric.get(prod)
        if metric is None:
            if prod and prod not in stats["unmapped"]:
                stats["unmapped"].append(prod)
            continue
        stats["mine"] += 1
        day = WEEKDAYS[d.weekday()]
        out.setdefault(day, {})
        out[day][metric] = out[day].get(metric, 0) + 1
    stats["reps_seen"] = len(stats["reps_seen"])
    ds = sorted(stats["dates_seen"])
    stats["dates_seen"] = f"{ds[0]} .. {ds[-1]}" if ds else "(ninguna)"
    return out, stats
