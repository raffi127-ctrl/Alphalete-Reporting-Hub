"""Audit every Carlos ICD tab for common errors in the OPT block:
  - Missing values (cell expected to have data, but blank)
  - Bad-range values (percents > 100% or < 0%, ranks <= 0)
  - Format mismatches (PERCENT cell showing 600% because value is 6 not 0.06)
  - Duplicate adjacent values (suggests row-drift stale write)
  - "No Access" / "No Data In Tableau" markers (informational)

Read-only — no edits. Prints per-tab issues + a summary tally.

Run:
    CAPTAINSHIP=Carlos .venv/bin/python -m automations.recruiting_report._audit_carlos
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from automations.recruiting_report import fill as _fill
from automations.recruiting_report.opt_phase_carlos import (
    metric_row_for_tab, ROW_TO_LABEL, _carlos_icd_tabs, _current_we_sunday,
)
from automations.focus_office_att.daily import _q


# Per-metric expectation for plausibility checks.
# (kind, min, max) — kind is "pct" (0-1), "count" (>= 0 int), "avg" (>= 0 float),
# "rank" (1+ int), "money" (>= 0 dollars), "text" (string OK), or "any".
METRIC_KIND = {
    29: ("count", 0, 200),       # Active Headcount (≤200 reps)
    33: ("count", 0, 100000),    # New Internets
    34: ("count", 0, 100000),    # Voice Sales
    35: ("count", 0, 100000),    # Wireless
    36: ("count", 0, 100000),    # New Lines
    37: ("count", 0, 200000),    # Total Apps
    38: ("avg",   0, 1000),      # AVG Apps Per Headcount
    39: ("avg",   0, 1000),      # AVG New INT Sales
    40: ("avg",   0, 1000),      # National AVG Apps
    41: ("rank",  1, 200),       # Scorecard Ranking
    43: ("pct",   0, 1),         # 0-30 Day Cancel Rate
    44: ("pct",   0, 1),         # Activation %
    45: ("pct",   0, 1),         # 0-30 Day Churn
    46: ("pct",   0, 1),         # 30 Day Churn
    47: ("pct",   0, 1),         # 60 Day Churn
    48: ("pct",   0, 1),         # 90 Day Churn
    49: ("pct",   0, 1),         # 120 Day churn
    50: ("pct",   0, 1),         # Penetration Rate
    51: ("money", 0, 10_000_000),  # Direct Deposit
}

MARKERS = {"No Access", "No Data In Tableau"}


def main() -> None:
    sh = _fill.open_sheet()
    icd_tabs = _carlos_icd_tabs()
    we = _current_we_sunday()
    print(f"Auditing {len(icd_tabs)} Carlos ICD tab(s) for WE {we.isoformat()}\n")

    # Batch-read row 1 (dates) + col B (labels) for every tab in 1 call
    ranges = []
    for t in icd_tabs:
        ranges.append(f"{_q(t)}!1:1")
        ranges.append(f"{_q(t)}!B:B")
    resp = sh.values_batch_get(ranges)
    vrs = resp.get("valueRanges", [])

    target_col_by_tab: dict = {}
    row_remap_by_tab: dict = {}
    for idx, t in enumerate(icd_tabs):
        row1 = vrs[idx * 2].get("values", [])
        col_b = [r[0] if r else "" for r in vrs[idx * 2 + 1].get("values", [])]
        if row1:
            mapping = _fill.find_sunday_columns([row1[0]], header_row_idx=0)
            target_col_by_tab[t] = mapping.get(we)
        remap = {}
        for c, label in ROW_TO_LABEL.items():
            a = metric_row_for_tab(col_b, label)
            if a:
                remap[c] = a
        row_remap_by_tab[t] = remap

    # For each tab, batch-fetch the current-week column cells for each
    # expected metric (with format info) and validate.
    import gspread.utils as _gu
    total_issues = 0
    issue_tabs = 0
    for tab in icd_tabs:
        target_col = target_col_by_tab.get(tab)
        remap = row_remap_by_tab.get(tab, {})
        if not target_col:
            print(f"\n=== {tab} ===\n  ⚠ no col for WE {we.isoformat()}")
            issue_tabs += 1
            total_issues += 1
            continue

        # Build a list of (canonical_row, actual_row) pairs
        col_a1 = _gu.rowcol_to_a1(1, target_col).rstrip("1")
        ranges_to_read = []
        canonical_list = []
        for canonical, actual in remap.items():
            ranges_to_read.append(f"{_q(tab)}!{col_a1}{actual}")
            canonical_list.append((canonical, actual))

        # Fetch UNFORMATTED + FORMATTED in one go each
        rf = sh.values_batch_get(ranges_to_read,
                                 params={"valueRenderOption": "FORMATTED_VALUE"})
        ru = sh.values_batch_get(ranges_to_read,
                                 params={"valueRenderOption": "UNFORMATTED_VALUE"})
        fvs = [v.get("values", [[None]])[0][0] if v.get("values") else None
               for v in rf.get("valueRanges", [])]
        uvs = [v.get("values", [[None]])[0][0] if v.get("values") else None
               for v in ru.get("valueRanges", [])]

        tab_issues: list[str] = []
        for (canonical, actual), fv, uv in zip(canonical_list, fvs, uvs):
            label = ROW_TO_LABEL.get(canonical)
            label_str = label if isinstance(label, str) else label[0]
            kind, lo, hi = METRIC_KIND.get(canonical, ("any", None, None))

            # Marker text — informational, not an error
            if uv in MARKERS or fv in MARKERS:
                continue

            # Missing
            if uv in (None, ""):
                tab_issues.append(f"row {actual} ({label_str}): MISSING")
                continue

            # Numeric checks
            try:
                num = float(uv)
            except (TypeError, ValueError):
                # String value where we expect a number
                if kind != "text" and kind != "money":
                    tab_issues.append(
                        f"row {actual} ({label_str}): text {fv!r} where {kind} expected"
                    )
                continue

            if kind == "pct":
                if num < 0 or num > 1:
                    tab_issues.append(
                        f"row {actual} ({label_str}): {fv} (raw={num:g}) — "
                        f"out of percent range. Format may be wrong."
                    )
            elif kind in ("count", "rank"):
                if num < lo or num > hi:
                    tab_issues.append(
                        f"row {actual} ({label_str}): {fv} (raw={num:g}) — "
                        f"out of expected {kind} range [{lo}, {hi}]"
                    )
                if kind == "rank" and num <= 0:
                    tab_issues.append(
                        f"row {actual} ({label_str}): rank {fv} <= 0"
                    )
            elif kind == "avg":
                if num < lo or num > hi:
                    tab_issues.append(
                        f"row {actual} ({label_str}): {fv} (raw={num:g}) — "
                        f"out of expected avg range [{lo}, {hi}]"
                    )
            elif kind == "money":
                if num < 0:
                    tab_issues.append(
                        f"row {actual} ({label_str}): negative money {fv}"
                    )

        # Detect adjacent-row duplicates (suggests leftover stale write)
        for i in range(len(canonical_list) - 1):
            (c1, a1), (c2, a2) = canonical_list[i], canonical_list[i + 1]
            v1, v2 = uvs[i], uvs[i + 1]
            if a2 == a1 + 1 and v1 == v2 and v1 not in (None, "", 0) and v1 not in MARKERS:
                label1 = ROW_TO_LABEL.get(c1)
                label2 = ROW_TO_LABEL.get(c2)
                l1 = label1 if isinstance(label1, str) else label1[0]
                l2 = label2 if isinstance(label2, str) else label2[0]
                tab_issues.append(
                    f"rows {a1} ({l1}) + {a2} ({l2}) both = {v1!r} — possible stale dup"
                )

        # Missing canonical rows (label not found on this tab)
        for canonical in ROW_TO_LABEL:
            if canonical not in remap:
                label = ROW_TO_LABEL[canonical]
                label_str = label if isinstance(label, str) else label[0]
                tab_issues.append(
                    f"label {label_str!r} not found in column B"
                )

        if tab_issues:
            print(f"=== {tab} ({len(tab_issues)} issue(s)) ===")
            for issue in tab_issues:
                print(f"  {issue}")
            print()
            issue_tabs += 1
            total_issues += len(tab_issues)

    print()
    print(f"AUDIT SUMMARY: {total_issues} issue(s) across {issue_tabs}/{len(icd_tabs)} tab(s)")


if __name__ == "__main__":
    main()
