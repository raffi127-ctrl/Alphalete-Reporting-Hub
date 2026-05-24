"""Write the financial section into the focus-report Google Sheets.

For each ICD tab across the focus-report spreadsheets, match the tab to an
office in the parsed FINANCIAL SUMMARY data and write the financial rows into
the latest week columns. Only ever writes the mapped financial cells.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional, Tuple

import gspread

from automations.recruiting_report import fill as rfill
from .parse import FINANCIAL_METRICS, norm_name

# The focus-report spreadsheets the financial section fills.
OUTPUT_SHEETS = {
    "ATT Program - Focus Report":          "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE",
    "Carlos 1on1s - Focus Report":         "1KLF8diMJ8pwIQWW9IqN7CL288t1l9VGUKxzBcMl8Of4",
    "Alphalete Org 1on1s - Focus Reports": "1C6BLttOSZhs_dREySac19XkxnMl-Ab_sYacNSl2l6AQ",
}

# How far below the 'Total Funds Available' anchor the financial rows run.
_SECTION_SPAN = 12
# The FINANCIAL SUMMARY files arrive a week late: a file dated week-ending
# 5/16 carries the work people actually did the week before, which the sheet
# tracks under the 5/24 column. Shift every parsed file-week by this many
# days before matching to a sheet column. Megan/Eve 2026-05-22: the
# previous run left col U (5/24) empty while S/T got the same data twice
# because the matcher rounded 5/16 to col T (5/17) instead of jumping
# forward to U (5/24).
_WEEK_OFFSET_DAYS = 7
# Tabs whose financial section is intentionally NOT filled. Raf's personal
# financials live in a separate, larger report (permanent skip).
_SKIP_TABS = {"raf hidalgo", "rafael hidalgo"}
# ICDs not needed on the financial pull for now (Megan, 2026-05-18) — held
# back pending their own files / source; revisit later. Jacob Dover's data is
# "coming soon"; Coel Reif + German Lopez use a different report (not listed
# here — handled separately once Megan provides those files).
_SKIP_FINANCIAL = {
    "melik el jaiez", "jacob dover", "tevin sterling", "jc pascual",
    "oren shezaf", "nicholas weldon", "joseph logan", "jr young",
    "jason strid", "tony chavez", "stergios kasapidis", "chan park",
    "milly villagrana", "starr rodenhurst",
}
# A tab-name campaign suffix, e.g. ' - NDS' / ' - BOX' / ' - B2B'.
_CAMPAIGN_SUFFIX = re.compile(r"\s*-\s*[A-Za-z0-9/&]+\s*$")


def _norm(s) -> str:
    """Lowercase, trim, collapse whitespace, drop spaces around %/ — so
    'Operating %' and 'Operating%' match."""
    s = str(s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"\s*([%/])\s*", r"\1", s)


def _tab_to_name(tab: str) -> str:
    """ICD name from a tab title — drops a leading 'x -' (archived marker)
    and a trailing ' - <campaign>' (NDS / BOX / B2B / ...)."""
    t = re.sub(r"^\s*x\s*-\s*", "", tab or "", flags=re.I)
    t = _CAMPAIGN_SUFFIX.sub("", t)
    return t.strip()


def _match_owner(tab: str, by_owner: Dict[str, List[dict]],
                 bridge: Optional[Dict[str, List[str]]] = None) -> List[dict]:
    """Match a Sheet tab to its financial office(s). Returns a LIST — most
    owners have one office, but a multi-location owner (Ryan: CO + TX) has
    several, each filled into its own row-set on the tab. Empty list = no
    match. The financial files spell names legally (RAFAEL HIDALGO) while
    tabs use nicknames (Raf Hidalgo) — `bridge` maps a normalized tab name
    to alternate names (the recruiting mapping's AppStream owner)."""
    name = _tab_to_name(tab)
    cands = [name]
    m = re.match(r"^(.*?)\s*\((.+?)\)\s*$", name)
    if m:
        cands += [m.group(2).strip(), m.group(1).strip()]
    # Skip intentionally-unfilled tabs — checked against every candidate so a
    # 'Jacob Dover (Tevin Sterling)' tab is caught by either name. Uses _norm
    # (not norm_name) so an initial like 'JR' isn't dropped as a 'Jr' suffix.
    if any(_norm(c) in _SKIP_TABS | _SKIP_FINANCIAL for c in cands):
        return []
    if bridge:
        cands += bridge.get(norm_name(tab), [])
        cands += bridge.get(norm_name(name), [])
    for c in cands:
        hit = by_owner.get(norm_name(c))
        if hit:
            return hit
    # Same-surname subset fallback — one name has an extra middle name.
    tw = norm_name(name).split()
    if len(tw) >= 2:
        for key, offices in by_owner.items():
            kw = key.split()
            if kw and kw[-1] == tw[-1] and (set(tw) <= set(kw) or set(kw) <= set(tw)):
                return offices
    return []


def _date_columns(header_row: List[str]) -> Dict[dt.date, int]:
    """{date -> 0-indexed column} for every date-looking header cell."""
    out: Dict[dt.date, int] = {}
    for i, h in enumerate(header_row):
        txt = str(h or "").strip()
        for fmt in ("%m/%d/%y", "%m/%d/%Y", "%-m/%-d/%y"):
            try:
                out[dt.datetime.strptime(txt, fmt).date()] = i
                break
            except ValueError:
                pass
    return out


def _closest_col(date_cols: Dict[dt.date, int], target: dt.date,
                 tol_days: int = 4) -> Optional[int]:
    """Column whose header date is closest to `target`, within tol_days."""
    best, best_diff = None, tol_days + 1
    for d, c in date_cols.items():
        diff = abs((d - target).days)
        if diff < best_diff:
            best, best_diff = c, diff
    return best


def fill_financial_for_tab(ws: gspread.Worksheet, offices, weeks: List[dt.date],
                           dry_run: bool) -> List[str]:
    """Write the financial rows for one ICD tab. `offices` is a list — one
    office for most ICDs, several for a multi-location owner (Ryan: CO + TX).
    Each office is routed to its own row-set: a tab with multiple 'Total
    Funds Available' anchors is split into blocks tagged by the state code
    in column A ('CO' / 'TX'), and each office fills the block matching its
    state. Single-block tabs fill from the (single) office unchanged."""
    if isinstance(offices, dict):           # tolerate the old single-office call
        offices = [offices]
    tab = ws.title
    grid = rfill._retry(ws.get_all_values)
    if not grid:
        return [f"[skip] {tab}: empty tab"]
    date_cols = _date_columns(grid[0])
    col_a = [(r[0] if len(r) > 0 else "") for r in grid]
    col_b = [(r[1] if len(r) > 1 else "") for r in grid]

    tfa = _norm("Total Funds Available")
    anchors = [j for j, v in enumerate(col_b) if _norm(v).startswith(tfa)]
    if not anchors:
        return [f"[skip] {tab}: no financial section"]
    # Each block: (anchor_row, state_marker from col A, end_row exclusive).
    blocks = []
    for i, a in enumerate(anchors):
        nxt = anchors[i + 1] if i + 1 < len(anchors) else len(col_b)
        end = min(a + _SECTION_SPAN, nxt, len(col_b))
        blocks.append((a, str(col_a[a] or "").strip().upper(), end))

    # Shift each file-week forward before matching to a sheet column —
    # FINANCIAL SUMMARY files arrive a week late, so 5/16 file data lands in
    # the 5/24 sheet column.
    shifted_weeks = [w + dt.timedelta(days=_WEEK_OFFSET_DAYS) for w in weeks]
    wk_cols = [_closest_col(date_cols, w) for w in shifted_weeks]
    if not any(c is not None for c in wk_cols):
        return [f"[skip] {tab}: no matching week columns for {shifted_weeks}"]

    multi_office = len(offices) > 1

    def _block_for(office) -> Optional[tuple]:
        """Pick the block this office fills. One block → use it. Several →
        match the office's state to the block's column-A marker. If a
        multi-block tab has no matching state, fall back to the first block
        for a lone office (old behavior), but skip when several offices
        could clobber each other."""
        if len(blocks) == 1:
            return blocks[0]
        st = (office.get("state") or "").upper()
        if st:
            for blk in blocks:
                if blk[1] and blk[1] == st:
                    return blk
        return None if multi_office else blocks[0]

    updates: List[Tuple[str, object]] = []
    parts: List[str] = []
    for office in offices:
        blk = _block_for(office)
        if blk is None:
            parts.append(f"({office.get('state') or office['office']}: no matching block)")
            continue
        anchor, _state, end = blk
        section = [(_norm(col_b[j]), j) for j in range(anchor, end)
                   if col_b[j].strip()]

        def _find_row(metric_label: str, section=section) -> Optional[int]:
            ml = _norm(metric_label)
            for lbl, j in section:
                if lbl == ml or lbl.startswith(ml) or ml.startswith(lbl):
                    return j
            return None

        n0 = len(updates)
        for out_label, xl_label in FINANCIAL_METRICS.items():
            row = _find_row(out_label)
            if row is None:
                continue
            vals = office["metrics"].get(xl_label)
            if not vals:
                continue
            for wk, col in zip(weeks, wk_cols):
                if col is None:
                    continue
                v = vals.get(wk)
                if v is None:
                    continue
                updates.append((gspread.utils.rowcol_to_a1(row + 1, col + 1), v))
        tag = _state or office["office"]
        parts.append(f"{tag}: {len(updates) - n0} cells")

    if not updates:
        return [f"[skip] {tab}: nothing to write ({'; '.join(parts)})"]
    summary = "; ".join(parts)
    if dry_run:
        return [f"[DRY-RUN] {tab} ← {summary}: {len(updates)} cells"]
    rfill._retry(ws.batch_update,
                 [{"range": a1, "values": [[v]]} for a1, v in updates],
                 value_input_option="USER_ENTERED")
    return [f"[OK] {tab} ← {summary}: wrote {len(updates)} cells"]
