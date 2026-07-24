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


def load_alias_map():
    """Load the shared 'ICD Aliases' table once. Name-spelling mismatches belong
    there, never in a per-report patch (CLAUDE.md). Returns {} on failure — the
    report still runs, it just matches on raw names."""
    try:
        from automations.focus_office_att.aliases import load_aliases
        return load_aliases()
    except Exception as e:  # noqa: BLE001
        print(f"⚠ couldn't load 'ICD Aliases' ({e}) — matching on raw names")
        return {}


def canon(name, aliases):
    """Normalized CANONICAL key for a person.

    Both sides of every match go through this — the sheet roster AND the Tableau
    sources — so one person's two spellings collapse to one key. E.g. the roster's
    'Muhammad Hammad Ul Haque' and the source's 'HAMMAD HAQUE' both resolve to
    'Hammad Haque'; without this the report silently left him blank."""
    if not aliases:
        return _norm_name(name)
    from automations.focus_office_att.aliases import alias_to_canonical
    return _norm_name(alias_to_canonical(name, aliases))


def rekey(d, aliases):
    """Rekey a {source_name: amount} dict onto canonical keys (summing if two
    spellings of the same person both appear in the source)."""
    out = {}
    for k, v in (d or {}).items():
        ck = canon(k, aliases)
        out[ck] = round(out.get(ck, 0) + v, 2) if isinstance(v, (int, float)) else v
    return out


def _newest_week_col(header):
    """0-based index of the newest (leftmost) dated week column."""
    for i, h in enumerate(header):
        if re.match(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$", (h or "").strip()):
            return i
    return None


def read_roster(ws, aliases=None):
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
        out[canon(name, aliases)] = (r, active, name)
    return out


def read_captains(ws, aliases=None):
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
            cur = canon(name, aliases)
            out[cur] = {"total": r + 1, "captain": None, "special": None}
    return out


def assemble(week_mdy, roster, captains, *, regular, captain, special, ws=None,
             aliases=None):
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
        if key == canon("Rafael Hidalgo", aliases):
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
        missing = reg is None and cap_special_total.get(key, 0) == 0
        if missing:
            # FILL-BUT-FLAG. Verified against the live tab's 7.12 column: the VA
            # writes $0.00 for people with no row in the source (Abel Draper,
            # Cinthya Reyes, Jacob Dover, Roshan Ahmad, Valeria Tristan), so we
            # match her and keep the column complete. But they ALWAYS stay on the
            # reported list: a NAME MISMATCH looks exactly like a genuine zero —
            # that is how Hammad was silently losing $1,532.25 a week before the
            # ICD-Aliases wiring. A $0 here is a prompt to check, not a fact.
            unmatched.append(disp)
        total = (reg or 0) + cap_special_total.get(key, 0)
        section1[row] = round(total, 2)
    return section1, section2, unmatched


def week_col(ws, label, header=None):
    """0-based index of the column whose row-1 header is this week label, or None.
    Weeks are found BY LABEL, never by position (a rolled column shifts indices)."""
    header = header if header is not None else ws.row_values(1)
    want = (label or "").strip()
    for i, h in enumerate(header):
        if (h or "").strip() == want:
            return i
    return None


def week_is_filled(ws, label, *, min_rows=3):
    """Has this week's column actually been filled in?

    A rolled-but-empty column still HAS a header, so presence alone can't gate the
    run (that would make it hold forever on an empty week). Mirrors pnl_office's
    fill-gate: count data cells that aren't blank/$0."""
    vals = ws.get_all_values()
    if not vals:
        return False
    i = week_col(ws, label, header=vals[0])
    if i is None:
        return False
    n = 0
    for r in vals[1:]:
        if i < len(r):
            c = (r[i] or "").strip()
            if c and c not in ("$0.00", "0", "$0", "-", "$-"):
                n += 1
    return n >= min_rows


def clear_week(ws, label, roster, captains, *, dry_run=True):
    """Blank the cells THIS REPORT writes in `label`'s column, so the week can be
    filled again from scratch.

    Needed because `week_is_filled` gates the run: a column left holding a bad
    fill (or, as happened on the sandbox, a copy of the previous week carried in
    by the roll) makes every later pass HOLD on 'already filled' and the week
    never gets its real numbers.

    Only the mapped cells are touched — the same rows `assemble` would write.
    Structural formulas (the =SUM leader rows, the Total row, the col-D year
    total) and the week header are left alone, and no other week's column is read
    or changed."""
    header = ws.row_values(1)
    idx = week_col(ws, label, header=header)
    if idx is None:
        raise ValueError(f"no column headed {label!r} on {ws.title!r}")
    col = _col_letter(idx)
    rows = sorted(
        [r for r, _a, _d in roster.values()]
        + [c[k] for c in captains.values() for k in ("captain", "special") if c.get(k)])
    ranges = [f"{col}{r}" for r in rows]
    if dry_run:
        print(f"[dry-run] would clear {len(ranges)} cell(s) in column {col} "
              f"({label}) on {ws.title!r}: {ranges[0]}…{ranges[-1]}")
        return ranges
    if ws.title == LIVE_TAB:
        raise RuntimeError(f"refusing to clear the live tab {LIVE_TAB!r} — sandbox only")
    ws.batch_clear(ranges)
    print(f"cleared {len(ranges)} cell(s) in column {col} ({label}) on {ws.title!r}")
    return ranges


def _col_letter(idx0):
    s, n = "", idx0
    while True:
        s = chr(65 + n % 26) + s
        n = n // 26 - 1
        if n < 0:
            break
    return s


def write_week(ws, section1, section2, *, week_label=None, dry_run=True):
    """Write the assembled numbers into `week_label`'s column (falling back to the
    newest column only when no label is given).

    Targeting BY LABEL matters: the run resolves which week to fill from the
    source, which is not necessarily the newest column on the tab — writing to
    the newest one would silently overwrite a different week.
    DRY-RUN prints; a real write is refused against the live tab."""
    header = ws.row_values(1)
    idx = week_col(ws, week_label, header=header) if week_label else None
    if idx is None:
        if week_label:
            raise ValueError(
                f"no column headed {week_label!r} on {ws.title!r} — roll the week "
                f"first (scaffold), don't write into another week's column")
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
