"""Human-readable scoring ledger for the Texas de Brazil ("Steak on the Line")
monthly competition.

The poster shows only each rep's TOTAL. This writes the full point-by-point
math to its own Google Sheet — one tab per month — so anyone can see exactly
who earned what and, just as important, who's LOSING points on Late / Off. Each
run overwrites the current month's tab with the live standings; past months stay
frozen as their own tabs, so you keep month-over-month history.

Every point column adds up, left to right, to the Total column — the row is its
own audit trail. This is a WRITE-ONLY mirror of what the board already computes;
it never feeds numbers back into the report.

Own Sheet (not the shared library): 'Texas de Brazil — Scoring Log'. The report
writes it as alphaletereporting@ (the shared reporting login), so that account
must have edit access; link-viewers get the live read-only board that gets
posted with the PDF each day.

Kept 3.9-safe (the mini runs Python 3.9): no PEP 604 unions, no match.
"""
from __future__ import annotations

import datetime

from automations.recruiting_report import fill as _fill

SHEET_ID = "1zlgrL36ly67xl_XU5okJ6yjHbpcx1F_eurtA09m-DaM"

# (Header, board-dict key). These point columns sum, in order, to Total — so a
# reader can add across a row and land on the Total cell. att_p is deliberately
# split into Here / Late / Off so the losses are visible on their own.
POINT_COLS = [
    ("New Internet", "int_p"),
    ("2nd Round", "acc_p"),
    ("New Start Showed", "show_p"),
    ("3+ Internet Day", "i3_p"),
    ("3+ Energy Day", "e5_p"),
    ("DTV", "dtv_p"),
    ("New Line", "nl_p"),
    ("Energy", "eng_p"),
    ("Here / On-Time / Dress", "here_p"),
    ("Late", "late_p"),
    ("Off / STF / No-Answer", "off_p"),
    ("Break-a-Leader", "brk_p"),
    ("Car Ride", "car_p"),
    ("Adjustment", "adj_p"),
]
HEADERS = ["Rank", "Rep", "Total"] + [h for h, _ in POINT_COLS]
_N_COLS = len(HEADERS)

# 0-based indexes of the two penalty columns (for red-font formatting).
_LATE_IDX = HEADERS.index("Late")
_OFF_IDX = HEADERS.index("Off / STF / No-Answer")


def _num(v):
    """Whole numbers as ints; keep one decimal only when it actually has one."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    return int(round(f)) if abs(f - round(f)) < 1e-9 else round(f, 1)


def build_rows(board):
    """board (from build_board) -> list of display rows, already ranked as the
    board is. Each row: [rank, name, total, <one cell per POINT_COLS>]."""
    rows = []
    for i, r in enumerate(board, 1):
        cells = [i, r.get("name", ""), _num(r.get("total", 0))]
        cells += [_num(r.get(key, 0)) for _, key in POINT_COLS]
        rows.append(cells)
    return rows


def _tab_title(month_name, comp_year):
    return "%s %s" % (month_name, comp_year)


def _a1_col(idx0):
    """0-based column index -> A1 letter(s)."""
    n = idx0 + 1
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def sheet_url(gid=None):
    base = "https://docs.google.com/spreadsheets/d/%s/edit" % SHEET_ID
    return base + ("#gid=%s" % gid if gid is not None else "")


def _get_or_make(sh, title, rows_needed):
    import gspread as _gs
    try:
        return sh.worksheet(title)
    except _gs.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=max(rows_needed, 60), cols=_N_COLS)


# ---- template-copy support -------------------------------------------------
# Megan keeps a design tab (default name 'TEMPLATE') with her own formatting and
# a preview panel. Each month we DUPLICATE it, then fill the data UNDER whatever
# header row it has — matched by label, never by fixed column — so her layout and
# preview survive untouched. Extra columns she adds are left alone.
TEMPLATE_TAB = "TEMPLATE"

# Every label we write, and the synonyms we'll still recognize in her header row.
_COL_SYNONYMS = {
    "Rank": ["rank", "#", "place", "pos"],
    "Rep": ["rep", "name", "rep name"],
    "Total": ["total", "total points", "points", "pts", "score"],
    "New Internet": ["new internet", "internet", "new int", "int"],
    "2nd Round": ["2nd round", "2nd rd", "second round", "accepts", "accept"],
    "New Start Showed": ["new start showed", "new start", "showed", "show"],
    "3+ Internet Day": ["3+ internet day", "3+ int day", "3+ internet", "int bonus"],
    "3+ Energy Day": ["3+ energy day", "3+ eng day", "3+ energy", "energy bonus"],
    "DTV": ["dtv"],
    "New Line": ["new line", "new lines", "nl"],
    "Energy": ["energy", "eng"],
    "Here / On-Time / Dress": ["here / on-time / dress", "here", "here/on-time/dress", "attendance", "here on time dress"],
    "Late": ["late"],
    "Off / STF / No-Answer": ["off / stf / no-answer", "off", "off/stf", "off stf no answer", "stf"],
    "Break-a-Leader": ["break-a-leader", "break a leader", "break", "bal"],
    "Car Ride": ["car ride", "car-ride", "car"],
    "Adjustment": ["adjustment", "adj", "manual"],
}


def _norm_h(s):
    return " ".join(str(s).strip().lower().replace("_", " ").split())


def _find_header_row(values):
    """Locate the header row + map each of OUR labels -> that row's 0-based column,
    by matching header text (synonyms allowed). Returns (row_idx0, {label: col0})
    or (None, {}) if no convincing header row is found."""
    syn_to_label = {}
    for label, syns in _COL_SYNONYMS.items():
        for s in syns:
            syn_to_label[_norm_h(s)] = label
    best = (None, {}, 0)
    for i, row in enumerate(values[:12]):   # header lives near the top
        found = {}
        for j, cell in enumerate(row):
            if not isinstance(cell, str) or not cell.strip():
                continue
            lab = syn_to_label.get(_norm_h(cell))
            if lab and lab not in found:
                found[lab] = j
        # need at least Rep+Total and a few point columns to trust it
        if "Rep" in found and "Total" in found and len(found) >= 5 and len(found) > best[2]:
            best = (i, found, len(found))
    return best[0], best[1]


def _resolve_month_ws(sh, title):
    """Return (ws, mode). mode: 'template' if freshly duplicated from TEMPLATE or
    an existing month tab (label-fill); 'raw' if we had to build a plain grid."""
    import gspread as _gs
    try:
        return sh.worksheet(title), "template"      # refresh existing month tab
    except _gs.WorksheetNotFound:
        pass
    try:
        tmpl = sh.worksheet(TEMPLATE_TAB)
        new = sh.duplicate_sheet(source_sheet_id=tmpl.id, new_sheet_name=title,
                                 insert_sheet_index=1)
        return new, "template"
    except _gs.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=80, cols=_N_COLS), "raw"


def _contiguous_runs(cols_sorted):
    """[2,3,4,7,8] -> [[2,3,4],[7,8]] so we write each solid block in one range."""
    runs = []
    for c in cols_sorted:
        if runs and c == runs[-1][-1] + 1:
            runs[-1].append(c)
        else:
            runs.append([c])
    return runs


def _fill_template(ws, rows):
    """Label-anchored fill: find the header row, clear old data below it in the
    mapped columns only (preserves any preview panel), then write the ranked rows
    as contiguous column blocks. Returns False if no header row is recognizable
    (caller then raw-fills)."""
    values = ws.get_all_values()
    hrow, cmap = _find_header_row(values)
    if hrow is None:
        return False
    order = ["Rank", "Rep", "Total"] + [h for h, _ in POINT_COLS]
    idx_of = {lab: i for i, lab in enumerate(order)}
    col_to_label = {col0: lab for lab, col0 in cmap.items()}
    cols_sorted = sorted(col_to_label)

    start = hrow + 1                       # 0-based first data row
    span = max(len(rows) + 8, 60)          # generous clear window
    reqs = []
    for run in _contiguous_runs(cols_sorted):
        c0, c1 = run[0], run[-1]
        # clear this block
        clr = [["" for _ in run] for _ in range(span)]
        reqs.append({"range": "%s%d:%s%d" % (_a1_col(c0), start + 1, _a1_col(c1), start + span),
                     "values": clr})
        # fill this block from the ranked rows
        block = []
        for r in rows:
            block.append([r[idx_of[col_to_label[c]]] for c in run])
        if block:
            reqs.append({"range": "%s%d:%s%d" % (_a1_col(c0), start + 1, _a1_col(c1), start + len(block)),
                         "values": block})
    ws.batch_update(reqs, value_input_option="RAW")
    return True


def _write_readme(sh):
    """Idempotent 'How points work' tab so the sheet explains itself."""
    title = "How Points Work"
    lines = [
        ["Texas de Brazil — Scoring Log"],
        ["One tab per month. Each run overwrites the CURRENT month with live standings; past months stay frozen."],
        ["Every point column below adds up, left to right, to the Total column."],
        [""],
        ["Column", "Points"],
        ["New Internet", "+2 each"],
        ["2nd Round (accept)", "+5 each"],
        ["New Start Showed", "+10 each"],
        ["3+ Internet Day (bonus)", "+10 per day with 3+ internet"],
        ["3+ Energy Day (bonus)", "+10 per day with 3+ energy"],
        ["DTV", "+1 each"],
        ["New Line", "+1 each"],
        ["Energy", "+1 each"],
        ["Here / On-Time / Dress", "+3 each"],
        ["Late", "-5 each"],
        ["Off / STF / No-Answer", "-10 each"],
        ["Break-a-Leader", "+15 to promoter AND +15 to the new leader"],
        ["Car Ride", "+10 (top car-ride leader of the week)"],
        ["Adjustment", "manual +/- correction"],
    ]
    ws = _get_or_make(sh, title, len(lines))
    ws.clear()
    ws.update("A1", lines, value_input_option="RAW")
    try:
        ws.format("A1", {"textFormat": {"bold": True, "fontSize": 13}})
        ws.format("A5:B5", {"textFormat": {"bold": True}})
    except Exception:
        pass
    return ws


def write_board(board, period, month_name, comp_year, through=None,
                dry_run=False):
    """Upsert this month's tab with the ranked point-by-point ledger.

    Returns {'ok','tab','gid','url','reps','dry_run'}. Never raises — a logging
    failure must not take down the report's delivery."""
    rows = build_rows(board)
    title = _tab_title(month_name, comp_year)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    thru = through.isoformat() if hasattr(through, "isoformat") else (through or "n/a")
    banner = "Texas de Brazil — %s   •   updated %s   •   sales through %s   •   %d reps" % (
        month_name.upper() + " " + str(comp_year), stamp, thru, len(rows))

    if dry_run:
        return {"ok": True, "tab": title, "gid": None, "url": sheet_url(),
                "reps": len(rows), "dry_run": True}

    try:
        sh = _fill.open_by_key(SHEET_ID)
        _write_readme(sh)
        ws, mode = _resolve_month_ws(sh, title)

        if mode == "template":
            # Duplicate of Megan's TEMPLATE (or an existing month tab): fill under
            # her header labels, leave her formatting + preview panel alone.
            filled = _fill_template(ws, rows)
            if not filled:
                mode = "raw"          # header not recognizable -> fall back
        if mode == "raw":
            last_col = _a1_col(_N_COLS - 1)
            grid = [[banner] + [""] * (_N_COLS - 1), HEADERS] + rows
            ws.clear()
            ws.update("A1", grid, value_input_option="RAW")
            try:
                ws.format("A1:%s1" % last_col, {"textFormat": {"bold": True, "fontSize": 11}})
                ws.format("A2:%s2" % last_col, {
                    "textFormat": {"bold": True, "foregroundColor": {"red": 0.90, "green": 0.75, "blue": 0.35}},
                    "backgroundColor": {"red": 0.12, "green": 0.12, "blue": 0.12},
                    "horizontalAlignment": "CENTER"})
                if rows:
                    end = len(grid)
                    for idx in (_LATE_IDX, _OFF_IDX):
                        col = _a1_col(idx)
                        ws.format("%s3:%s%d" % (col, col, end),
                                  {"textFormat": {"foregroundColor": {"red": 0.75, "green": 0.10, "blue": 0.10}}})
                    ctot = _a1_col(2)
                    ws.format("%s3:%s%d" % (ctot, ctot, end), {"textFormat": {"bold": True}})
                ws.freeze(rows=2, cols=2)
            except Exception:
                pass

        return {"ok": True, "tab": title, "gid": ws.id, "url": sheet_url(ws.id),
                "reps": len(rows), "mode": mode, "dry_run": False}
    except Exception as e:  # noqa: BLE001 — logging must never break delivery
        return {"ok": False, "tab": title, "gid": None, "url": sheet_url(),
                "reps": len(rows), "error": "%s: %s" % (type(e).__name__, e)}


# ---------------------------------------------------------------------------
# PER-DAY month tab (Megan's TEMPLATE layout: '#', 'REP NAME', 'MONTH TOTALS',
# then one column per calendar day). Auto-creates the month tab from TEMPLATE and
# fills the daily grid, sorted highest->lowest. This is the layout wired into the
# daily run (build_board attaches r['days'] = [{'d': iso, 'tot': swing}, ...]).
# ---------------------------------------------------------------------------
_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}


def _month_num(name):
    return _MONTHS.get(str(name).strip().title(), 1)


def _rng(r0, c0, r1, c1):
    return "%s%d:%s%d" % (_a1_col(c0), r0 + 1, _a1_col(c1), r1 + 1)


def _locate_daygrid(values):
    """Find the header row + the rank/name/total columns and the run of day
    columns after 'MONTH TOTALS'. Robust to the template placeholder ('MM/DD/YY')
    or already-filled dates. Returns (hrow, rank_c, name_c, total_c, [day_cols])."""
    for i, row in enumerate(values[:5]):
        m = {_norm_h(c): j for j, c in enumerate(row) if isinstance(c, str) and c.strip()}
        name_c = next((m[k] for k in ("rep name", "rep", "name") if k in m), None)
        total_c = next((m[k] for k in ("month totals", "total", "total points", "points") if k in m), None)
        if name_c is not None and total_c is not None:
            rank_c = next((m[k] for k in ("#", "rank", "place", "pos") if k in m), None)
            day_cols = []
            hdr = row
            c = total_c + 1
            while c < len(hdr) and str(hdr[c]).strip() and len(day_cols) < 40:
                day_cols.append(c); c += 1
            return i, rank_c, name_c, total_c, day_cols
    return None, None, None, None, []


def fill_month_tab(board, period, month_name, comp_year, dry_run=False):
    """Auto-create '<Month> <Year>' from TEMPLATE (once) and fill the per-day grid
    ranked highest->lowest: rank, name, MONTH TOTALS (full competition total), and
    each day's point swing in its date column. Only the grid columns are touched,
    so any preview panel to the side survives. Never raises."""
    import datetime
    title = "%s %s" % (month_name, comp_year)
    rows = sorted(board, key=lambda r: (-r.get("total", 0), r.get("name", "")))
    if dry_run:
        return {"ok": True, "tab": title, "reps": len(rows), "url": sheet_url(), "dry_run": True}
    try:
        import gspread as _gs
        yr, mo = int(comp_year), _month_num(month_name)
        import calendar as _cal
        ndays = _cal.monthrange(yr, mo)[1]
        sh = _fill.open_by_key(SHEET_ID)
        try:
            ws = sh.worksheet(title)
        except _gs.WorksheetNotFound:
            tmpl = sh.worksheet(TEMPLATE_TAB)
            ws = sh.duplicate_sheet(source_sheet_id=tmpl.id, new_sheet_name=title, insert_sheet_index=1)
        hrow, rank_c, name_c, total_c, day_cols = _locate_daygrid(ws.get_all_values())
        if name_c is None or total_c is None:
            return {"ok": False, "tab": title, "url": sheet_url(),
                    "error": "template header not found (need 'REP NAME' + 'MONTH TOTALS')"}

        cols = [c for c in [rank_c, name_c, total_c] if c is not None] + day_cols
        first_c, last_c = min(cols), max(cols)
        width = last_c - first_c + 1
        start = hrow + 1                                   # 0-based first data row
        height = max(len(rows) + 6, 60)                    # extra rows clear stale reps
        block = [["" for _ in range(width)] for _ in range(height)]
        iso_of = {k: datetime.date(yr, mo, k + 1).isoformat() for k in range(ndays)}
        for i, r in enumerate(rows):
            daymap = {d["d"]: d["tot"] for d in r.get("days", [])}
            if rank_c is not None:
                block[i][rank_c - first_c] = i + 1
            block[i][name_c - first_c] = r.get("name", "")
            block[i][total_c - first_c] = round(r.get("total", 0))
            for k, ci in enumerate(day_cols):
                if k < ndays:
                    v = daymap.get(iso_of[k])
                    if v:
                        block[i][ci - first_c] = round(v)
        reqs = [{"range": _rng(start, first_c, start + height - 1, last_c), "values": block}]
        if day_cols:
            hspan = ["" for _ in range(day_cols[-1] - day_cols[0] + 1)]
            for k, ci in enumerate(day_cols):
                if k < ndays:
                    hspan[ci - day_cols[0]] = "%d/%d/%s" % (mo, k + 1, str(yr)[2:])
            reqs.append({"range": _rng(hrow, day_cols[0], hrow, day_cols[-1]), "values": [hspan]})
        ws.batch_update(reqs, value_input_option="USER_ENTERED")
        try:
            ws.freeze(rows=hrow + 1, cols=(name_c + 1))
        except Exception:
            pass
        return {"ok": True, "tab": title, "gid": ws.id, "url": sheet_url(ws.id),
                "reps": len(rows), "days_filled": ndays, "dry_run": False}
    except Exception as e:  # noqa: BLE001 — logging must never break delivery
        return {"ok": False, "tab": title, "url": sheet_url(),
                "error": "%s: %s" % (type(e).__name__, e)}
