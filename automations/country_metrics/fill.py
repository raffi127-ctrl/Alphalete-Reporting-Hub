"""Write the gathered Country Metrics data into the Sheet.

Label-driven (no hardcoded rows/cols): section anchors are found by the
section name in column A; metric rows by their column-A label within the
section; the week column by matching the date header in row 1. Only the mapped
metric cells are written; AT&T AIR and every formula cell (Sales (ALL), AVG
Units, % of Owners over 100, COUNTRY's owner counts) are skipped — both by
design (we never produce those keys) and by a hard formula-cell guard.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from automations.recruiting_report import fill as rfill

# Real Sheet ('ATT Program - Focus Report'). The validated tab was promoted to
# the official 'Country Metrics' (the prior one is archived as
# '_Country Metrics (OLD)', hidden) — Eve, 2026-05-28.
SHEET_ID = "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE"
TAB = "Country Metrics"

SECTIONS = ("COUNTRY", "RAF", "STARR", "ARON", "PAT", "WAYNE", "SAM")
PERCENT_KEYS = {"rolling4", "act3060", "churn030", "abp", "gig1", "sched6"}


def open_ws():
    return rfill.open_by_key(SHEET_ID).worksheet(TAB)


def _col_a1(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def classify(label: str) -> Optional[str]:
    """Column-A label -> metric_key (or None). Skips header/formula rows."""
    l = (label or "").strip().lower()
    if l.startswith("jep"):
        return "jep"
    if "abp mix" in l:
        return "abp"
    if "1gig" in l:
        return "gig1"
    if "rolling 4" in l:
        return "rolling4"
    if "30-60" in l and "activation" in l:
        return "act3060"
    if "0-30" in l and "churn" in l:
        return "churn030"
    if "6+ days" in l or "scheduled 6+" in l:
        return "sched6"
    if "new internet count" in l:
        return "newint"
    if "upgrade internet count" in l:
        return "upgrade"
    if l == "video sales":
        return "video"
    if "at&t air" in l:
        return "air"          # intentionally left blank
    if l == "wireless":
        return "wireless"
    if l.startswith("sales (all)"):
        return "salesall"     # formula
    if "total owners" in l:
        return "totalowners"
    if "avg units" in l:
        return "avg"          # formula
    if l == "owners over 100":
        return "ownersover100"
    if "% of owners over 100" in l:
        return "pctover100"   # formula
    return None


WRITE_KEYS = {"rolling4", "act3060", "churn030", "abp", "gig1", "jep", "sched6",
              "newint", "upgrade", "video", "wireless", "totalowners", "ownersover100"}


def find_week_col(row1: list[str], week: dt.date) -> Optional[int]:
    """1-based column whose row-1 header date == week."""
    for i, v in enumerate(row1):
        v = (v or "").strip()
        for fmt in ("%m/%d/%y", "%m/%d/%Y"):
            try:
                if dt.datetime.strptime(v, fmt).date() == week:
                    return i + 1
            except ValueError:
                continue
    return None


def locate_sections(col_a: list[str]) -> dict[str, int]:
    """section name -> 1-based anchor row."""
    out = {}
    for i, v in enumerate(col_a):
        name = (v or "").strip().upper()
        if name in SECTIONS and name not in out:
            out[name] = i + 1
    return out


def section_metric_rows(col_a: list[str], anchor: int, end: int) -> dict[str, int]:
    """metric_key -> 1-based row, scanning col A from anchor+1 to end-1."""
    out = {}
    for r in range(anchor, end - 1):      # r is 0-based index; rows anchor+1..end-1
        if r >= len(col_a):
            break
        key = classify(col_a[r])
        if key and key not in out:
            out[key] = r + 1
    return out


def write(ws, data: dict, week: dt.date, dry_run: bool, logfn=print) -> dict:
    col_a = ws.col_values(1)
    row1 = ws.row_values(1)
    week_col = find_week_col(row1, week)
    if not week_col:
        raise RuntimeError(f"no column in row 1 with date header {week.isoformat()}")
    colL = _col_a1(week_col)
    logfn(f"week {week.isoformat()} -> column {colL}")

    anchors = locate_sections(col_a)
    missing_sections = [s for s in SECTIONS if s not in anchors]
    if missing_sections:
        logfn(f"  WARNING: sections not found in col A: {missing_sections}")
    ordered = sorted(anchors.values())

    # Style the target week's column to match the PREVIOUS week's (borders,
    # bold, number formats) so every new weekending is visually identical to
    # the prior one. Self-propagating: next week copies this one (Eve,
    # 2026-05-28 — V/5-24 had come in without the bold + number formats that
    # U/5-17 has). Skipped on dry-run and for the first week column.
    if not dry_run and ordered and week_col > 2:
        end_row = max(ordered) + 17
        ws.spreadsheet.batch_update({"requests": [{
            "copyPaste": {
                "source": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": end_row,
                           "startColumnIndex": week_col - 2, "endColumnIndex": week_col - 1},
                "destination": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": end_row,
                                "startColumnIndex": week_col - 1, "endColumnIndex": week_col},
                "pasteType": "PASTE_FORMAT",
            }
        }]})
        logfn(f"  styled column {colL} to match {_col_a1(week_col - 1)} (formatting)")

    # Formula-cell guard: never overwrite a cell that currently holds a formula.
    last_row = (max(ordered) + 20) if ordered else len(col_a)
    fcol = ws.get_values(f"{colL}1:{colL}{last_row}", value_render_option="FORMULA")
    formula_rows = {i + 1 for i, r in enumerate(fcol)
                    if r and isinstance(r[0], str) and r[0].startswith("=")}

    updates, skipped_formula, log = [], [], []
    for section in SECTIONS:
        if section not in anchors:
            continue
        anchor = anchors[section]
        nxt = next((a for a in ordered if a > anchor), len(col_a) + 1)
        rows = section_metric_rows(col_a, anchor, nxt)
        sdata = data.get(section, {})
        for key, row in rows.items():
            if key not in WRITE_KEYS:
                continue
            if key not in sdata or sdata[key] is None:
                continue
            if row in formula_rows:
                skipped_formula.append(f"{section}.{key} ({colL}{row})")
                continue
            val = sdata[key]
            updates.append({"range": f"{colL}{row}", "values": [[val]]})
            log.append(f"  {section:<8} {key:<14} {colL}{row} <- {val}")

    for line in log:
        logfn(line)
    if skipped_formula:
        logfn(f"  skipped {len(skipped_formula)} formula cell(s): {', '.join(skipped_formula)}")

    if dry_run:
        logfn(f"[DRY-RUN] would write {len(updates)} cells")
    elif updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        logfn(f"[OK] wrote {len(updates)} cells")
    else:
        logfn("nothing to write")
    return {"written": len(updates), "skipped_formula": skipped_formula}
