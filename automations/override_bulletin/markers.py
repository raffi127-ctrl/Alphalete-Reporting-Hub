"""Period markers (P#-YYYY) for the late-arriving Special + Credico overrides.

The two annotation rows — "Credico Overrides" and "Special Overrides" — carry one
marker per period, in the week column that absorbed that period's payment, going
back to P11-2024. They do two jobs:

  1. a permanent PLACEMENT record (which week absorbed which period's money) —
     the only thing that explains a sudden Credico spike in one week;
  2. a pending flag: **red = the money hasn't arrived yet**, black = placed.

So the SHEET IS THE STATE — no state file. Reading the marker's text colour tells
us what's outstanding, and flipping red→black after placing is what stops a period
being added twice (Credico is ADDED into an owner's existing weekly cell).

Rules (Megan 2026-07-23):
  * Placement is NOT derived. The marker says which week a period belongs in. The
    spacing is period-based (4-5 weeks), NOT "last week of the month" — P1→1.25,
    P2→2.22, P3→3.29, P4→4.26, P5→5.31, P6→7.5 — so guessing would misplace money.
  * A period present in the ledger with NO marker is REPORTED, never placed.

Dry-run by default; writes refuse the live tab (same guard as fill/scaffold).
"""
from __future__ import annotations

import re

from automations.override_bulletin import fill as F
from automations.override_bulletin.pulls import _norm_name, _num_locale

CREDICO = "credico"
SPECIAL = "special"
_ROW_LABELS = {CREDICO: "credico overrides", SPECIAL: "special overrides"}
_PERIOD = re.compile(r"^P(\d{1,2})-(\d{4})$")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def _is_red(cell):
    fg = (cell.get("effectiveFormat", {}).get("textFormat", {})
              .get("foregroundColor", {}) or {})
    r, g, b = fg.get("red", 0), fg.get("green", 0), fg.get("blue", 0)
    return r > 0.5 and g < 0.4 and b < 0.4


def read_markers(ws):
    """[{kind, period, week, row, col, pending}] for both annotation rows.

    Rows are located by their column-A label (never a hardcoded index) and the
    week by the row-1 header over the marker's column."""
    sh = ws.spreadsheet
    vals = ws.get_all_values()
    header = vals[0] if vals else []
    rows = {}
    for kind, label in _ROW_LABELS.items():
        # The label ALONE is ambiguous: "Special Overrides" is also Carlos's
        # special sub-row inside the captain block (row 56), and the section header
        # "CAPTAIN/SPECIAL OVERRIDES ONLY" contains it too. So among the rows whose
        # label matches, take the one that actually carries P#-YYYY markers — that
        # identifies the annotation row regardless of template changes.
        for i, r in enumerate(vals):
            if not r or " ".join((r[0] or "").split()).lower() != label:
                continue
            if any(_PERIOD.match((c or "").strip()) for c in r[1:]):
                rows[kind] = i + 1                     # 1-based
                break
    if not rows:
        return []
    # ZZ, not BZ: the week columns run back to 2024, and a short range silently
    # drops the oldest markers.
    kinds = list(rows)
    ranges = [f"'{ws.title}'!A{rows[k]}:ZZ{rows[k]}" for k in kinds]
    meta = sh.fetch_sheet_metadata({
        "includeGridData": True, "ranges": ranges,
        "fields": ("sheets.data.rowData.values(formattedValue,"
                   "effectiveFormat.textFormat.foregroundColor)")})
    # The API may return one `sheets` entry per range OR a single sheet holding one
    # `data` block per range. Flatten (sheet, data) pairs in request order and map
    # them to kinds positionally, so either shape is handled — keying off
    # sheets[idx] alone mislabels every marker with the first kind.
    blocks = [d for sheet in meta.get("sheets", []) for d in sheet.get("data", [])]
    out = []
    for idx, data in enumerate(blocks):
        kind = kinds[idx] if idx < len(kinds) else None
        if kind is None:
            continue
        for rowdata in data.get("rowData", []):
            for ci, cell in enumerate(rowdata.get("values", [])):
                v = (cell.get("formattedValue") or "").strip()
                if not _PERIOD.match(v):
                    continue
                out.append({
                    "kind": kind, "period": v, "row": rows[kind], "col": ci,
                    "week": (header[ci].strip() if ci < len(header) else ""),
                    "pending": _is_red(cell),
                })
    return out


def ledger_needles(kind, period):
    """Explanation substrings that identify this period's ledger rows.

    Special carries the period verbatim ('P6-2026 Special Override'). Credico is
    MONTH-labelled ('June 2026 Standard Overrides - Credico'), so we map P<n> to
    month n and require BOTH the month-year and 'credico' — never just 'credico',
    which matches every period at once."""
    m = _PERIOD.match(period)
    if not m:
        return []
    n, year = int(m.group(1)), m.group(2)
    if kind == SPECIAL:
        return [[period]]
    month = _MONTHS[n - 1] if 1 <= n <= 12 else None
    cands = [[period]]                                  # in case it's period-labelled
    if month:
        cands.insert(0, [f"{month} {year}", "credico"])
    return cands


def amounts_for(rows, kind, period, *, owner_col, expl_col, amt_col):
    """{owner: amount} for one period, or None if the ledger has no such rows yet
    (=> still pending; leave the marker red)."""
    hdr = rows[0]
    from automations.override_bulletin.pulls import _hdr_col
    oc, ec, ac = (_hdr_col(hdr, c) for c in (owner_col, expl_col, amt_col))
    if None in (oc, ec, ac):
        return None
    for needles in ledger_needles(kind, period):
        out, cur = {}, None
        for r in rows[1:]:
            nm = (r[oc] or "").strip() if oc < len(r) else ""
            if nm:
                cur = _norm_name(nm)
            expl = (r[ec] or "") if ec < len(r) else ""
            low = expl.lower()
            if cur and all(n.lower() in low for n in needles):
                v = _num_locale(r[ac]) if ac < len(r) else None
                if v is not None:
                    out[cur] = round(out.get(cur, 0) + v, 2)
        if out:
            return out
    return None


def plan_placements(ws, ledger_rows, *, aliases=None, owner_col, expl_col, amt_col):
    """What to do about every marker. Returns (to_place, still_pending, orphans).

    to_place      — pending markers whose money has now landed
    still_pending — pending markers the ledger still doesn't carry
    orphans       — periods present in the ledger with NO marker (report, never
                    place: we don't know which week they belong to)
    """
    markers = read_markers(ws)
    to_place, still_pending = [], []
    for mk in markers:
        if not mk["pending"]:
            continue
        amts = amounts_for(ledger_rows, mk["kind"], mk["period"],
                           owner_col=owner_col, expl_col=expl_col, amt_col=amt_col)
        if amts:
            mk = {**mk, "amounts": F.rekey(amts, aliases) if aliases else amts}
            to_place.append(mk)
        else:
            still_pending.append(mk)
    known = {(m["kind"], m["period"]) for m in markers}
    orphans = []
    for kind in (CREDICO, SPECIAL):
        for per in sorted(_periods_in_ledger(ledger_rows, kind, expl_col=expl_col)):
            if (kind, per) not in known:
                orphans.append({"kind": kind, "period": per})
    return to_place, still_pending, orphans


def _periods_in_ledger(rows, kind, *, expl_col):
    """Period labels the ledger mentions for this kind (used to spot orphans)."""
    from automations.override_bulletin.pulls import _hdr_col
    ec = _hdr_col(rows[0], expl_col)
    found = set()
    if ec is None:
        return found
    for r in rows[1:]:
        expl = (r[ec] or "") if ec < len(r) else ""
        low = expl.lower()
        if kind == SPECIAL and "special override" in low:
            m = re.search(r"\bP(\d{1,2})-(\d{4})\b", expl)
            if m:
                found.add(f"P{int(m.group(1))}-{m.group(2)}")
        elif kind == CREDICO and "credico" in low:
            for i, mon in enumerate(_MONTHS, start=1):
                m = re.search(rf"\b{mon}\s+(\d{{4}})\b", expl)
                if m:
                    found.add(f"P{i}-{m.group(1)}")
    return found


def apply_placements(ws, to_place, *, roster, captains, dry_run=True):
    """Write each landed period into its marked week, then flip the marker black.

    Credico ADDS to the owner's existing weekly cell (it's part of the section-1
    regular component); Special sets the captain's Special-Override sub-row. The
    red->black flip is what makes this safe to re-run — a black marker is never
    reprocessed, so nothing is added twice."""
    if not dry_run and ws.title == F.LIVE_TAB:
        raise RuntimeError(f"refusing to write the live tab {F.LIVE_TAB!r} — sandbox only")
    vals = ws.get_all_values()
    updates, fmts, log = [], [], []
    for mk in to_place:
        col_letter = F._col_letter(mk["col"])
        for owner, amt in mk["amounts"].items():
            if mk["kind"] == CREDICO:
                hit = roster.get(owner)
                if not hit:
                    log.append(f"  ! {mk['period']} credico: {owner} not on the roster")
                    continue
                row = hit[0]
                cur = 0.0
                if row - 1 < len(vals) and mk["col"] < len(vals[row - 1]):
                    cur = _num_locale(vals[row - 1][mk["col"]]) or 0.0
                new = round(cur + amt, 2)
                log.append(f"  {mk['period']} credico {owner}: {cur} + {amt} = {new}")
            else:
                caps = captains.get(owner) or {}
                row = caps.get("special")
                if not row:
                    log.append(f"  ! {mk['period']} special: no Special row for {owner}")
                    continue
                new = round(amt, 2)
                log.append(f"  {mk['period']} special {owner}: = {new}")
            updates.append({"range": f"{col_letter}{row}", "values": [[new]]})
        # marker goes black once its money is placed
        fmts.append({"range": f"{col_letter}{mk['row']}",
                     "format": {"textFormat": {"foregroundColor":
                                               {"red": 0, "green": 0, "blue": 0}}}})
    if dry_run:
        print(f"[dry-run] would place {len(updates)} cell(s) and un-red "
              f"{len(fmts)} marker(s) on {ws.title!r}:")
        for line in log:
            print(line)
        return updates, fmts
    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    for f in fmts:
        ws.format(f["range"], f["format"])
    for line in log:
        print(line)
    return updates, fmts
