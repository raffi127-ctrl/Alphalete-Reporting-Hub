"""Carlos's B2B Ongoing Cancels — parse + write 'Lucy Cancel Rates'.

Carlos asked for this on the Loom (2:21-2:45): "the ongoing cancel report… if
they could live on my spreadsheet, that'd be great."

WEEKLY, NOT DAILY — deliberate, and worth knowing before comparing this to
Raf's. The screenshot Carlos pointed at is Raf's D2D Ongoing Cancel, which is a
running sum with one column per DAY (Sat 7/18, Fri 7/17, …). Carlos's own view
(CarlosLOExpCancels, Megan-supplied 2026-07-20) reports by WEEK ENDING instead:

    Owner & Office | Rep | <metric> | WE (07/18) | WE (07/11) | … | 6 Week Average

and carries none of the D2D running-sum captions, so automations/ongoing_cancel
cannot parse it — its parser keys off
"Running Sum of Canceled Internet Orders along sp.Order Date", which is absent
here. Megan 2026-07-20: build it weekly, she will confirm with Carlos whether he
wants daily. Re-pointing later is a URL plus a renderer, not a rebuild.

The metric is a ROW dimension (column 2, unnamed): each rep has three rows —
"Cancel Rates", "Canceled Orders", "Unit Count". We keep all three: the rate is
what Carlos reads, and the two counts are what let a total be recomputed
correctly (summing counts, never averaging rates).
"""
from __future__ import annotations

import collections
import datetime as dt
import re
from typing import Dict, List, Optional, Sequence

VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER-B2B/B2BCancelRates/3e58bc13-abea-4563-9481-360d0b9759ed/"
    "CarlosLOExpCancels?:iid=1"
)
CROSSTAB_SHEET = "Cancel Rates Sheet"      # the dialog's real name; the other
                                           # thumb is "zzz Last Refresh"

COL_OWNER = "Owner & Office"
COL_REP = "Rep"
METRIC_RATE = "Cancel Rates"
METRIC_CANCELS = "Canceled Orders"
METRIC_UNITS = "Unit Count"
AVG_COL = "6 Week Average"

TAB = "Lucy Cancel Rates"
OWNER_PREFIX = "CARLOS HIDALGO"

# "WE (07/18)" -> 07/18
_WE_RE = re.compile(r"WE\s*\((\d{1,2})/(\d{1,2})\)")


def _norm(v) -> str:
    # The owner cell carries an embedded CR before the office suffix
    # ('CARLOS HIDALGO\r [alphalete …]'), so strip whitespace INCLUDING \r —
    # a plain .strip() on the whole string leaves the CR mid-value.
    return "" if v is None else str(v).replace("\r", " ").strip()


def owner_name(value: str) -> str:
    """'CARLOS HIDALGO\\r [alphalete specialized marketing inc(tx]' -> 'CARLOS HIDALGO'."""
    s = _norm(value).split("\n")[0]
    if "[" in s:
        s = s.split("[", 1)[0]
    return s.strip()


def week_columns(header: Sequence[str]) -> List[tuple]:
    """[(index, 'WE (07/18)', date_or_None)] in the order the export gives —
    newest first, matching how Carlos reads it."""
    out = []
    for i, h in enumerate(header):
        m = _WE_RE.search(_norm(h))
        if m:
            out.append((i, _norm(h), (int(m.group(1)), int(m.group(2)))))
    return out


def parse(grid: List[list], owner_prefix: str = OWNER_PREFIX) -> dict:
    """Crosstab grid -> {'weeks': [...], 'reps': {rep: {week: {...}}}, 'total': {...}}.

    Raises when the expected columns are missing rather than returning an empty
    result — the failure this whole build keeps hitting is a parser that finds
    nothing and reports success.
    """
    if not grid:
        raise ValueError("cancel crosstab is empty")
    hdr = [_norm(h).lstrip("﻿") for h in grid[0]]
    if COL_REP not in hdr:
        raise ValueError(
            "cancel crosstab has no {!r} column. Header: {}".format(COL_REP, hdr))
    weeks = week_columns(hdr)
    if not weeks:
        raise ValueError(
            "cancel crosstab has no 'WE (mm/dd)' columns — the view's shape "
            "moved. Header: {}".format(hdr))

    oi = hdr.index(COL_OWNER) if COL_OWNER in hdr else None
    ri = hdr.index(COL_REP)
    # The metric sits in the unnamed column just left of the first week.
    mi = weeks[0][0] - 1

    reps: "collections.OrderedDict[str, dict]" = collections.OrderedDict()
    total: Dict[str, dict] = {}
    for row in grid[1:]:
        if len(row) <= mi:
            continue
        rep = _norm(row[ri])
        metric = _norm(row[mi])
        if not rep or not metric:
            continue
        owner = owner_name(row[oi]) if oi is not None else ""
        is_total = (rep.lower() == "total"
                    or owner.lower().startswith("grand total"))
        if not is_total and owner_prefix and owner and \
                not owner.upper().startswith(owner_prefix.upper()):
            continue
        bucket = total if is_total else reps.setdefault(rep, {})
        for idx, label, _d in weeks:
            cell = _norm(row[idx]) if idx < len(row) else ""
            bucket.setdefault(label, {})[metric] = cell

    if not reps:
        raise ValueError(
            "parsed 0 reps for {!r} — wrong view, or the owner slice matched "
            "nothing".format(owner_prefix))
    return {"weeks": [w[1] for w in weeks], "reps": reps, "total": total}


def _pct_value(raw: str) -> Optional[float]:
    s = _norm(raw).replace("%", "")
    if not s:
        return None
    try:
        return float(s) / 100.0
    except ValueError:
        return None


def build_grid(parsed: dict, generated: str) -> List[List[str]]:
    """The visible tab: one row per rep, one column pair per week ending."""
    weeks = parsed["weeks"]
    ncol = 1 + 2 * len(weeks)

    head = ["ONGOING CANCELS — weekly"] + [""] * (ncol - 1)
    sub = ["Updated " + generated] + [""] * (ncol - 1)
    hdr1 = ["Rep"]
    for w in weeks:
        hdr1 += [w, ""]
    hdr2 = [""]
    for _ in weeks:
        hdr2 += ["%", "cancels/units"]

    rows: List[List[str]] = [head, sub, hdr1, hdr2]

    def emit(label, data):
        row = [label]
        for w in weeks:
            d = (data or {}).get(w, {})
            rate = _norm(d.get(METRIC_RATE))
            c = _norm(d.get(METRIC_CANCELS))
            u = _norm(d.get(METRIC_UNITS))
            row.append(rate)
            # Show the counts behind the rate. "0% " with no denominator is
            # indistinguishable from "no data", which is the complaint that
            # started the churn work.
            row.append("{}/{}".format(c or "0", u.split(".")[0] or "0")
                       if (c or u) else "")
        return row

    if parsed.get("total"):
        rows.append(emit("Office Total", parsed["total"]))
    # Worst first — the point of the report is who is cancelling, so sorting by
    # the newest week's rate puts the answer at the top instead of making Carlos
    # scan 40 alphabetical rows for it.
    def _key(item):
        d = item[1].get(weeks[0], {}) if weeks else {}
        v = _pct_value(d.get(METRIC_RATE))
        return (-(v if v is not None else -1), item[0])

    for rep, data in sorted(parsed["reps"].items(), key=_key):
        rows.append(emit(rep, data))
    return rows


def summary(parsed: dict) -> Dict[str, object]:
    weeks = parsed["weeks"]
    newest = weeks[0] if weeks else None
    flagged = []
    for rep, d in parsed["reps"].items():
        v = _pct_value((d.get(newest) or {}).get(METRIC_RATE)) if newest else None
        if v is not None and v > 0:
            flagged.append((rep, v))
    flagged.sort(key=lambda x: -x[1])
    return {"weeks": len(weeks), "reps": len(parsed["reps"]),
            "newest_week": newest, "with_cancels": len(flagged),
            "worst": flagged[:5]}
