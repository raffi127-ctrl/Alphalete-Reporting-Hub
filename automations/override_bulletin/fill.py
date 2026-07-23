"""Assemble and write the weekly override numbers (phases 2-4 orchestration).

Reads the sheet roster (Active-ICD = YES is the who-list — see FILL_SOURCES.md),
pulls each number source for the target week, assembles section-1 (regular +
captain/special) and section-2 (captain/special breakdown), and writes them into
the newly-rolled week column. Anyone active we can't match in a source is
collected and returned for the email summary — never silently zeroed.

DRY-RUN by default; --write refused against the live tab (same guard as scaffold).
The Tableau pulls run on Lucy 1; this module is import-safe anywhere.
"""
from __future__ import annotations

import re

from automations.override_bulletin.pulls import _norm_name

LIVE_TAB = "Org Overrides Ongoing Report"
SANDBOX_TAB = "Copy of Org Overrides Ongoing Report"
WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"

# Section-2 leader rows: the captain and (optional) special sub-rows under each.
# Detected from the sheet, but the shape is: a leader name row with a =SUM() over
# the 1-2 sub-rows immediately below labelled "Captain Override" / "Special
# Override". read_captains() derives these live so an inserted row can't misalign.
_SUB_LABELS = ("captain override", "special override", "special overrides")


def _newest_week_col(header):
    """0-based index of the newest (leftmost) dated week column."""
    for i, h in enumerate(header):
        if re.match(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$", (h or "").strip()):
            return i
    return None


def read_roster(ws):
    """{normalized_name: (row_1based, active_bool, display_name)} for the ALL ORG
    section. active = Active-ICD (col B) == YES. Stops at the CAPTAIN/SPECIAL
    header. The YES names are the who-list to fill."""
    vals = ws.get_all_values()
    out = {}
    for r, row in enumerate(vals[1:], start=2):
        name = (row[0] if row else "").strip()
        low = name.lower()
        if "captain/special" in low:
            break
        if not name or low == "total" or "credico" in low:
            continue
        active = (row[1].strip().upper() == "YES") if len(row) > 1 else False
        out[_norm_name(name)] = (r, active, name)
    return out


def read_captains(ws):
    """{normalized_name: {'total': row, 'captain': row, 'special': row|None}} for
    the CAPTAIN/SPECIAL section — derived live from the =SUM leader rows and the
    labelled sub-rows below each."""
    vals = ws.get_all_values()
    # find the section-2 header
    start = next((i for i, row in enumerate(vals)
                  if row and "captain/special" in (row[0] or "").lower()), None)
    if start is None:
        return {}
    out, cur = {}, None
    for r in range(start + 1, len(vals)):
        name = (vals[r][0] if vals[r] else "").strip()
        low = name.lower()
        if not name:
            break
        if low in _SUB_LABELS:
            if cur is None:
                continue
            key = "captain" if "captain" in low else "special"
            out[cur][key] = r + 1
        else:                                   # a leader name row
            cur = _norm_name(name)
            out[cur] = {"total": r + 1, "captain": None, "special": None}
    return out


def assemble(week_mdy, roster, captains, *, regular, captain, special, ws=None):
    """Build the per-person write plan for the target week.

    regular/captain/special are {normalized_name: amount} from the pulls.
    Returns (section1, section2, unmatched):
      section1 = {row: value}    — ALL ORG weekly cell per active person
      section2 = {row: value}    — CAPTAIN/SPECIAL captain & special sub-rows
      unmatched = [display_name] — active people absent from the regular pull
    """
    from automations.override_bulletin.pulls import raf_captain_override
    section1, section2, unmatched = {}, {}, []

    # Section 2 first — captain/special per captain — so section 1 can add them.
    cap_special_total = {}
    for key, rows in captains.items():
        cap = captain.get(key)
        # Raf's captain override comes from the Raf PNL, not the DD pull.
        if key == _norm_name("Rafael Hidalgo"):
            cap = raf_captain_override(week_mdy, ws=None)
        spc = special.get(key)
        if rows.get("captain") and cap is not None:
            section2[rows["captain"]] = cap
        if rows.get("special") and spc is not None:
            section2[rows["special"]] = spc
        cap_special_total[key] = (cap or 0) + (spc or 0)

    # Section 1 — each active person: regular + their captain/special total.
    for key, (row, active, disp) in roster.items():
        if not active:
            continue
        reg = regular.get(key)
        if reg is None and cap_special_total.get(key, 0) == 0:
            unmatched.append(disp)               # active but nowhere in the pulls
            continue
        total = (reg or 0) + cap_special_total.get(key, 0)
        section1[row] = round(total, 2)
    return section1, section2, unmatched


def _col_letter(idx0):
    s, n = "", idx0
    while True:
        s = chr(65 + n % 26) + s
        n = n // 26 - 1
        if n < 0:
            break
    return s


def write_week(ws, section1, section2, *, dry_run=True):
    """Write the assembled numbers into the newest (leftmost) week column.
    section1/section2 are {row: value}. DRY-RUN prints; a real write is refused
    against the live tab. Returns the target column letter."""
    header = ws.row_values(1)
    idx = _newest_week_col(header)
    col = _col_letter(idx)
    cells = {**section1, **section2}
    if dry_run:
        print(f"[dry-run] would write {len(cells)} cell(s) to column {col} "
              f"({ws.title!r}):")
        for row in sorted(cells)[:8]:
            print(f"    {col}{row} = {cells[row]}")
        if len(cells) > 8:
            print(f"    … +{len(cells) - 8} more")
        return col
    if ws.title == LIVE_TAB:
        raise RuntimeError(f"refusing to write the live tab {LIVE_TAB!r} — sandbox only")
    ws.batch_update([{"range": f"{col}{row}", "values": [[val]]}
                     for row, val in cells.items()],
                    value_input_option="USER_ENTERED")
    return col
