"""Fill the `Rep Count 24-26` tab from parsed Archey headcounts.

Layout (found by label, never hardcoded indices):
  row 1            headers: A 'ICD Owner Name' | B 'Org Leader' |
                   C 'Headcount Goal' | D.. 'WE m/d/yy' (Saturdays)
  active rows      between the header and the 'No longer active' divider,
                   grouped by Org Leader (Carlos / Colten / Rafael)
  'No longer active'
  inactive rows    between that divider and the 'TOTAL' row
  'TOTAL'
  'Org Ongoing Data'
  per-leader block 'Colten Wright Headcount' / 'ICD Count' / 'Avg per ICD',
                   then Rafael, then Carlos, then
                   'TOTAL Organization Headcount' / 'TOTAL ICD Count' /
                   'TOTAL Avg per ICD'  (all hardcoded VALUES, we recompute)
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional

import gspread
from gspread.utils import rowcol_to_a1

from automations.recruiting_report import fill as rfill
from automations.residential_rep_count.parse import norm_name

SPREADSHEET_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
REAL_TAB = "Rep Count 24-26"
SANDBOX_TAB = "Rep Count 24-26 SANDBOX"

# RC captainships that own active rows on this sheet, in the order the Org
# Ongoing Data block lists them.
ONGOING_ORDER = ["Colten Wright", "Rafael Hidalgo", "Carlos Hidalgo"]

ZERO_STREAK_TO_INACTIVE = 3   # 0 this many weeks running -> "No longer active"


def we_label(d: dt.date) -> str:
    """Saturday date -> 'WE m/d/yy' (no leading zeros, 2-digit year),
    matching the existing column headers (e.g. 'WE 6/20/26')."""
    return f"WE {d.month}/{d.day}/{d.strftime('%y')}"


def we_label_to_date(label: str) -> Optional[dt.date]:
    """'WE 6/20/26' -> date(2026, 6, 20); None if it doesn't parse."""
    m = re.match(r"\s*WE\s+(\d{1,2})/(\d{1,2})/(\d{2})\s*$", label or "")
    if not m:
        return None
    return dt.date(2000 + int(m.group(3)), int(m.group(1)), int(m.group(2)))


def open_tab(sandbox: bool = True):
    sh = rfill.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(SANDBOX_TAB if sandbox else REAL_TAB), sh


# ---------- layout discovery ----------

def _find_row(grid: List[List[str]], pred, start: int = 0) -> Optional[int]:
    for i in range(start, len(grid)):
        if pred(grid[i]):
            return i
    return None


def resolve_layout(grid: List[List[str]]) -> dict:
    a = lambda r: (r[0] if r else "").strip()
    header = _find_row(grid, lambda r: a(r).lower() == "icd owner name")
    if header is None:
        raise ValueError("no 'ICD Owner Name' header row")
    nla = _find_row(grid, lambda r: "no longer active" in a(r).lower(), header + 1)
    total = _find_row(grid, lambda r: a(r).lower() == "total", (nla or header) + 1)
    ongoing = _find_row(grid, lambda r: "org ongoing data" in a(r).lower(),
                        (total or 0) + 1)
    if nla is None or total is None:
        raise ValueError("missing 'No longer active' divider or 'TOTAL' row")
    # WE columns: header cells starting 'WE '
    we_cols = {}
    for j, h in enumerate(grid[header]):
        if (h or "").strip().lower().startswith("we "):
            we_cols[(h or "").strip()] = j
    return {
        "header": header,
        "nla": nla,                            # 'No longer active' divider row
        "active": (header + 1, nla - 1),       # inclusive 0-based row range
        "inactive": (nla + 1, total - 1),
        "total": total,
        "ongoing": ongoing,
        "we_cols": we_cols,
    }


def ongoing_rows(grid: List[List[str]], ongoing_start: int) -> dict:
    """Map each ongoing label -> 0-based row index, found by col-A label."""
    want = {}
    labels = {
        **{f"{ldr} headcount".lower(): ("hc", ldr) for ldr in ONGOING_ORDER},
        "total organization headcount": ("total_hc", None),
        "total icd count": ("total_icd", None),
        "total avg per icd": ("total_avg", None),
    }
    rows = {}
    last_leader = None
    for i in range(ongoing_start, len(grid)):
        lbl = (grid[i][0] if grid[i] else "").strip().lower()
        if lbl in labels:
            kind, ldr = labels[lbl]
            rows[(kind, ldr)] = i
            if kind == "hc":
                last_leader = ldr
        elif lbl == "icd count" and last_leader:
            rows[("icd", last_leader)] = i
        elif lbl == "avg per icd" and last_leader:
            rows[("avg", last_leader)] = i
    return rows


# ---------- matching ----------

def _aliases():
    try:
        from automations.focus_office_att import aliases as al
        return al, al.load_aliases()
    except Exception as e:
        print(f"⚠ alias lookup unavailable ({e}); matching on exact names only")
        return None, {}


def build_matcher(email_data: Dict[str, dict]):
    al, raw = _aliases()

    def lookup(sheet_name: str) -> Optional[dict]:
        key = norm_name(sheet_name)
        if key in email_data:
            return email_data[key]
        if al is not None:
            for cand in al.get_search_candidates(sheet_name, raw):
                k = norm_name(cand)
                if k in email_data:
                    return email_data[k]
        return None

    return lookup


# ---------- the fill ----------

def fill_week(ws, grid: List[List[str]], email_data: Dict[str, dict],
              we_date: dt.date, dry_run: bool = True) -> dict:
    """Compute every cell to write for the given Saturday week. Returns a
    report dict; performs the batched write unless dry_run."""
    lay = resolve_layout(grid)
    label = we_label(we_date)
    log: List[str] = []
    updates: List[dict] = []

    # 1) Locate / create the week column — inserted in chronological position,
    # inheriting the prior week's formatting (number format, borders, fill).
    if label in lay["we_cols"]:
        wk = lay["we_cols"][label]
        log.append(f"week column {label!r} exists at col {wk + 1}")
    else:
        dated = sorted(
            ((d, c) for l, c in lay["we_cols"].items()
             if (d := we_label_to_date(l)) is not None),
            key=lambda dc: dc[0])
        wk = next((c for d, c in dated if d > we_date), None)
        if wk is None:                      # newest week -> append at the end
            wk = (max(lay["we_cols"].values()) + 1) if lay["we_cols"] else 3
        log.append(f"NEW week column {label!r} -> col {wk + 1} "
                   "(inherits prior week's format)")
        if not dry_run:
            reqs = [{"insertDimension": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                          "startIndex": wk, "endIndex": wk + 1},
                "inheritFromBefore": True}}]
            # insertDimension's inheritFromBefore can drop BORDERS, so also
            # copy the full per-cell format from the previous week's column
            # (only when the left neighbor really is a WE week column).
            left_hdr = (grid[lay["header"]][wk - 1]
                        if wk - 1 < len(grid[lay["header"]]) else "")
            if wk >= 1 and left_hdr.strip().lower().startswith("we "):
                reqs.append({"copyPaste": {
                    "source": {"sheetId": ws.id, "startRowIndex": 0,
                               "endRowIndex": len(grid), "startColumnIndex": wk - 1,
                               "endColumnIndex": wk},
                    "destination": {"sheetId": ws.id, "startRowIndex": 0,
                                    "endRowIndex": len(grid), "startColumnIndex": wk,
                                    "endColumnIndex": wk + 1},
                    "pasteType": "PASTE_FORMAT"}})
            rfill._retry(ws.spreadsheet.batch_update, {"requests": reqs})
        updates.append({"range": rowcol_to_a1(lay["header"] + 1, wk + 1),
                        "values": [[label]]})

    lookup = build_matcher(email_data)

    # 2) Active ICDs: write each one's Unique Headcount.
    a0, a1 = lay["active"]
    leader_hc: Dict[str, int] = {l: 0 for l in ONGOING_ORDER}
    leader_icd: Dict[str, int] = {l: 0 for l in ONGOING_ORDER}
    total_icd = 0
    unmatched: List[str] = []
    active_names: List[str] = []

    # Active section is finalized by the structural phase BEFORE this runs
    # (new ICDs added, churned ICDs moved out, returning ICDs moved in), so
    # here we simply fill each active row's Unique Headcount for the week.
    for ri in range(a0, a1 + 1):
        row = grid[ri] if ri < len(grid) else []
        name = (row[0] if row else "").strip()
        if not name:
            continue
        active_names.append(name)
        leader = (row[1] if len(row) > 1 else "").strip()
        rec = lookup(name)
        hc = rec["headcount"] if rec else 0
        if rec is None:
            unmatched.append(name)
        updates.append({"range": rowcol_to_a1(ri + 1, wk + 1),
                        "values": [[hc]]})
        # tallies (count an ICD toward ICD Count only if it pulled >=1)
        if hc >= 1:
            total_icd += 1
        for l in ONGOING_ORDER:
            if norm_name(leader) == norm_name(l):
                leader_hc[l] += hc
                if hc >= 1:
                    leader_icd[l] += 1
                break

    # 4) TOTAL row + Org Ongoing Data block.
    total_hc = sum(leader_hc[l] for l in ONGOING_ORDER)
    updates.append({"range": rowcol_to_a1(lay["total"] + 1, wk + 1),
                    "values": [[total_hc]]})
    log.append(f"TOTAL headcount = {total_hc} across {total_icd} ICDs")

    orows = ongoing_rows(grid, lay["ongoing"]) if lay["ongoing"] else {}
    def put(key, val):
        r = orows.get(key)
        if r is not None:
            updates.append({"range": rowcol_to_a1(r + 1, wk + 1),
                            "values": [[val]]})
    for l in ONGOING_ORDER:
        hc = leader_hc[l]
        n = leader_icd[l]
        put(("hc", l), hc)
        put(("icd", l), n)
        put(("avg", l), round(hc / n, 1) if n else 0)
        log.append(f"  {l}: HC {hc} / {n} ICDs / avg "
                   f"{round(hc / n, 1) if n else 0}")
    put(("total_hc", None), total_hc)
    put(("total_icd", None), total_icd)
    put(("total_avg", None), round(total_hc / total_icd, 1) if total_icd else 0)

    # 5) Write (worksheet-scoped) unless dry-run.
    if not dry_run and updates:
        rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")

    return {
        "label": label,
        "updates": updates,
        "log": log,
        "unmatched": unmatched,
        "leader_hc": leader_hc,
        "leader_icd": leader_icd,
        "total_hc": total_hc,
        "total_icd": total_icd,
        "active_names": active_names,
    }
