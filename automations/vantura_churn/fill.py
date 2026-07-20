"""Vantura Master Sales Board writers — Churn tabs + Carlos's Activations.

Golden rules (runbook Part 5/6/9), enforced here:
  * LIVE sheet only, API writes — never a copy.
  * On a churn tab, ONLY B5:B7 and the hidden helper block R2:AE<cap> are
    touched. The control box (A4:D7 beyond B5:B7), the F4:L12 tiers chart,
    the C3 dropdown, and the R99+ customer-notes lookup table are never
    written.
  * Each tab's helper capacity comes from ITS OWN C5 SUMIF formula
    ($AD$2:$AD$25 on Carlos, $AD$2:$AD$40 on Atef). If a day's disconnect
    list ever outgrows it we raise instead of silently truncating.
  * Activations: notes (col P) are preserved by SPM before the overwrite,
    the basic filter is reset to show all rows (a rep-filtered view would
    scramble a paste) and re-spanned to the new data, and everything is
    center-aligned (Carlos's standing preference).
"""
from __future__ import annotations

import re

import gspread

from automations.recruiting_report.fill import open_by_key, _retry

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
TAB_CHURN_CARLOS = "Churn"
TAB_CHURN_ATEF = "Churn - Atef"
TAB_ACTIVATIONS = "Activations"

# Carlos's duplicate of the Churn tab, where the 2026-07-19 rebuild (activation
# rates + per-rep list) is being built. Run with --preview to fill THIS instead
# of the live tab, so the daily job keeps updating 'Churn' untouched.
TAB_CHURN_PREVIEW = "LUCY CHURN"

U_FORMULA = ('=IFERROR($AE{r}/IF($AD{r}="Wireless",$B$5,'
             'IF($AD{r}="Air",$B$6,$B$7)),"")')
AC_FORMULA = '=IFERROR(VLOOKUP($V{r},$R$100:$S$500,2,FALSE),"")'

CENTER = {"horizontalAlignment": "CENTER"}
# The tab's header navy (sampled from the 'Days Left' header row).
HEADER_BG = {"red": 0.09803922, "green": 0.23529412, "blue": 0.39607844}


def open_sheet():
    return open_by_key(SHEET_ID)


def helper_capacity(ws: gspread.Worksheet) -> int:
    """Last helper row this tab's own formulas can see, read from C5's
    SUMIF range (e.g. $AD$2:$AD$25 → 25). The A16 FILTER uses the same
    bound, so writing past it would show wrong counts AND a truncated list."""
    c5 = _retry(lambda: ws.get("C5", value_render_option="FORMULA"))[0][0]
    m = re.search(r"\$AD\$2:\$AD\$(\d+)", str(c5))
    if not m:
        raise RuntimeError(f"{ws.title}!C5 is not the expected SUMIF "
                           f"formula (got: {c5!r}) — refusing to guess the "
                           "helper range.")
    return int(m.group(1))


# Activation-rate colour bands (Megan 2026-07-19). Carlos's Loom misspoke on
# the 31-60 floor ("anything below is green"); these are the agreed bands.
# NB: deliberately NOT the view's own 'Activation Color' column — Tableau
# bands 31-60 differently and would call 74.6% red where these call it yellow.
BANDS = {
    "0-30": [(0.75, "green"), (0.65, "yellow"), (0.0, "red")],
    "31-60": [(0.80, "green"), (0.70, "yellow"), (0.0, "red")],
}
# Match the tiers chart already on the tab.
BAND_BG = {"green": {"red": 0.576, "green": 0.769, "blue": 0.490},
           "yellow": {"red": 1.0, "green": 0.851, "blue": 0.400},
           "red": {"red": 0.878, "green": 0.400, "blue": 0.400}}

# The per-rep list lives clear of the hidden helper block (R:AE) — Carlos's
# stub headers at P1:R1 put the 31-60 caption INSIDE the hidden range, so it
# was invisible on the tab.
REP_LIST_COL = "AG"
REP_STUB_RANGE = "P1:R1"


def band_for(rate, which: str) -> str:
    """Colour name for a rate under `which` band set, or None when blank."""
    if rate is None:
        return None
    for floor, name in BANDS[which]:
        if rate >= floor:
            return name
    return "red"


def viewing_cell(ws: gspread.Worksheet) -> str:
    """Which cell the rolloff FILTER actually watches, read from A16.

    Derived rather than hardcoded because it MOVES: the live tab filters on
    $C$3, Carlos's rebuild repointed it to $B$3 (2026-07-19). Whichever cell
    the formula names is the one that must carry the dropdown.
    """
    f = _retry(lambda: ws.get("A16", value_render_option="FORMULA"))
    formula = str(f[0][0]) if f and f[0] else ""
    m = re.search(r"\$([A-Z]{1,2})\$(\d+)\s*\)?\s*$", formula)
    if not m:
        m = re.search(r"=\s*\$([A-Z]{1,2})\$(\d+)", formula)
    if not m:
        raise RuntimeError(
            f"{ws.title}!A16 is not the expected FILTER formula "
            f"(got: {formula!r}) — refusing to guess which cell the "
            "'Viewing:' dropdown belongs on.")
    return f"{m.group(1)}{m.group(2)}"


def repair_viewing_dropdown(ws: gspread.Worksheet, log=print) -> dict:
    """Put the product dropdown back on the cell the FILTER reads.

    Adding the activation-rate headers left the tab with the validation on
    one cell (C3) and the FILTER pointing at another (B3), so choosing a
    product did nothing. This moves the ONE_OF_LIST rule onto the FILTER's
    cell, carries the current selection across, and clears the orphan.

    Idempotent: re-running when everything already lines up is a no-op.
    """
    target = viewing_cell(ws)
    tcol = re.match(r"([A-Z]{1,2})(\d+)", target).group(1)
    trow = int(re.match(r"([A-Z]{1,2})(\d+)", target).group(2))
    tcol_i = gspread.utils.a1_to_rowcol(f"{tcol}1")[1] - 1

    # Scan the row for cells carrying a ONE_OF_LIST rule, so we find the
    # orphan wherever it drifted to rather than assuming it sits in C.
    scan_end = max(tcol_i + 3, 6)
    meta = _retry(lambda: ws.spreadsheet.fetch_sheet_metadata({
        "includeGridData": True,
        "ranges": [f"{ws.title}!A{trow}:{_colletter(scan_end)}{trow}"],
        "fields": "sheets(data(startColumn,rowData(values("
                  "formattedValue,dataValidation))))",
    }))
    vals = (meta["sheets"][0].get("data", [{}])[0]
            .get("rowData", [{}])[0].get("values", []))
    start_col = meta["sheets"][0].get("data", [{}])[0].get("startColumn", 0)

    rule = None
    holders, selection = [], None
    for i, v in enumerate(vals):
        ci = start_col + i
        dv = v.get("dataValidation")
        if dv and dv.get("condition", {}).get("type") == "ONE_OF_LIST":
            holders.append(ci)
            rule = rule or dv
        if ci == tcol_i:
            selection = v.get("formattedValue")
        elif dv and not selection:
            selection = v.get("formattedValue")

    if rule is None:
        raise RuntimeError(
            f"{ws.title}: no product dropdown found on row {trow} — nothing "
            "to move. Rebuild it by hand rather than letting this guess the "
            "allowed values.")
    if holders == [tcol_i]:
        log(f"  ✓ {ws.title}: dropdown already on {target}; nothing to fix")
        return {"target": target, "moved": False, "cleared": []}

    def _cell_range(ci):
        return {"sheetId": ws.id, "startRowIndex": trow - 1, "endRowIndex": trow,
                "startColumnIndex": ci, "endColumnIndex": ci + 1}

    reqs = [{"setDataValidation": {"range": _cell_range(tcol_i),
                                   "rule": rule}}]
    # Clear the orphan rule + its stale text so only one control remains.
    cleared = []
    for ci in holders:
        if ci == tcol_i:
            continue
        reqs.append({"setDataValidation": {"range": _cell_range(ci)}})
        cleared.append(_colletter(ci))
    _retry(lambda: ws.spreadsheet.batch_update({"requests": reqs}))

    allowed = [c["userEnteredValue"]
               for c in rule["condition"].get("values", [])]
    if selection not in allowed:
        selection = allowed[0] if allowed else selection
    updates = [{"range": target, "values": [[selection]]}]
    for c in cleared:
        updates.append({"range": f"{c}{trow}", "values": [[""]]})
    _retry(lambda: ws.batch_update(updates, value_input_option="USER_ENTERED"))

    log(f"  ✓ {ws.title}: dropdown moved to {target} (= {selection!r}), "
        f"cleared {', '.join(c + str(trow) for c in cleared) or 'nothing'}")
    return {"target": target, "moved": True, "cleared": cleared,
            "selection": selection, "allowed": allowed}


def _colletter(ci: int) -> str:
    s = ""
    ci += 1
    while ci:
        ci, r = divmod(ci - 1, 26)
        s = chr(65 + r) + s
    return s


def hide_helper_columns(ws: gspread.Worksheet, log=print) -> bool:
    """Hide the helper block, matching the live tabs.

    Duplicating a churn tab does NOT carry the hidden state over, so a fresh
    copy shows R:AE — 14 columns of raw per-account scratch sitting right of
    the report. Idempotent; returns True when it actually changed something.
    """
    first = gspread.utils.a1_to_rowcol("R1")[1] - 1
    cap = helper_capacity(ws)          # AE is the last helper column
    last = gspread.utils.a1_to_rowcol("AE1")[1]
    meta = _retry(lambda: ws.spreadsheet.fetch_sheet_metadata(
        {"fields": "sheets(properties(sheetId),data(columnMetadata("
                   "hiddenByUser)))"}))
    cm = []
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == ws.id:
            cm = s.get("data", [{}])[0].get("columnMetadata", [])
            break
    if all(c.get("hiddenByUser") for c in cm[first:last] or [{}]):
        return False
    _retry(lambda: ws.spreadsheet.batch_update({"requests": [{
        "updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": first, "endIndex": last},
            "properties": {"hiddenByUser": True},
            "fields": "hiddenByUser"}}]}))
    log(f"  ✓ {ws.title}: hid helper columns R:AE (cap {cap})")
    return True


def update_activation_rates(ws: gspread.Worksheet, office: dict, reps: dict,
                            log=print) -> None:
    """Write the two office activation rates + the per-rep list.

    The office rates are OFFICE-WIDE, not per product, so they go in E5/F5
    only — repeating them down the Wireless/Air/Internet rows would read as
    a per-product breakdown the source doesn't support.
    """
    def _pct(d):
        return "" if d["rate"] is None else round(d["rate"], 4)

    updates = [
        {"range": "E5", "values": [[_pct(office["0-30"])]]},
        {"range": "F5", "values": [[_pct(office["31-60"])]]},
    ]

    # Per-rep list. Reps with NO activity in a bucket get a blank, not a 0% —
    # zero sales is undefined mix, not a zero rate. [[feedback_one_gig_blank_is_na]]
    ordered = sorted(reps.items(),
                     key=lambda kv: (kv[1]["0-30"]["rate"] is None,
                                     -(kv[1]["0-30"]["rate"] or 0),
                                     kv[0]))
    rows = [["Rep Name", "0-30 Day Activation Rate",
             "31-60 Day Activation Rate"]]
    for rep, v in ordered:
        rows.append([rep, _pct(v["0-30"]), _pct(v["31-60"])])
    last_col = _colletter(gspread.utils.a1_to_rowcol(f"{REP_LIST_COL}1")[1] + 1)
    end = len(rows)
    updates.append({"range": f"{REP_LIST_COL}1:{last_col}{end}",
                    "values": rows})
    _retry(lambda: ws.batch_update(updates, value_input_option="USER_ENTERED"))

    # Clear Carlos's stub headers now that the real list has a home — VALUES
    # AND FORMAT. Clearing values alone leaves the dark header fill behind as
    # a floating bar to the right of the tiers chart.
    try:
        _retry(lambda: ws.batch_clear([REP_STUB_RANGE]))
        p0 = gspread.utils.a1_to_rowcol("P1")[1] - 1
        _retry(lambda: ws.spreadsheet.batch_update({"requests": [
            {"repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": 0,
                          "endRowIndex": 1, "startColumnIndex": p0,
                          "endColumnIndex": p0 + 3},
                "cell": {"userEnteredFormat": {}},
                "fields": "userEnteredFormat"}}]}))
    except Exception:  # noqa: BLE001
        pass

    # Percent format + banding.
    fmt_reqs = [{"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": 4, "endRowIndex": 5,
                  "startColumnIndex": 4, "endColumnIndex": 6},
        "cell": {"userEnteredFormat": {
            "numberFormat": {"type": "PERCENT", "pattern": "0.0%"},
            "horizontalAlignment": "CENTER"}},
        "fields": "userEnteredFormat.numberFormat,"
                  "userEnteredFormat.horizontalAlignment"}}]
    rep_c0 = gspread.utils.a1_to_rowcol(f"{REP_LIST_COL}1")[1] - 1
    fmt_reqs.append({"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": end,
                  "startColumnIndex": rep_c0 + 1, "endColumnIndex": rep_c0 + 3},
        "cell": {"userEnteredFormat": {
            "numberFormat": {"type": "PERCENT", "pattern": "0.0%"},
            "horizontalAlignment": "CENTER"}},
        "fields": "userEnteredFormat.numberFormat,"
                  "userEnteredFormat.horizontalAlignment"}})

    def _bg(row0, col0, colour):
        return {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": row0,
                      "endRowIndex": row0 + 1, "startColumnIndex": col0,
                      "endColumnIndex": col0 + 1},
            "cell": {"userEnteredFormat": {
                "backgroundColor": BAND_BG[colour]}},
            "fields": "userEnteredFormat.backgroundColor"}}

    for ci, key in ((4, "0-30"), (5, "31-60")):
        c = band_for(office[key]["rate"], key)
        if c:
            fmt_reqs.append(_bg(4, ci, c))
    for i, (_rep, v) in enumerate(ordered):
        for off, key in ((1, "0-30"), (2, "31-60")):
            c = band_for(v[key]["rate"], key)
            if c:
                fmt_reqs.append(_bg(1 + i, rep_c0 + off, c))
    # Widen the rep columns — full names run to ~30 chars and the default
    # width truncates both them and the two rate headers.
    for off, px in ((0, 210), (1, 120), (2, 120)):
        fmt_reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": rep_c0 + off,
                      "endIndex": rep_c0 + off + 1},
            "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    # Header styled like the tab's other headers (navy / white / Arial 12) —
    # the rep columns otherwise inherit whatever fill was sitting in them.
    fmt_reqs.append({"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1,
                  "startColumnIndex": rep_c0, "endColumnIndex": rep_c0 + 3},
        "cell": {"userEnteredFormat": {
            "wrapStrategy": "WRAP", "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
            "backgroundColor": HEADER_BG,
            "textFormat": {"bold": True, "fontFamily": "Arial", "fontSize": 12,
                           "foregroundColor": {"red": 1, "green": 1,
                                               "blue": 1}}}},
        "fields": "userEnteredFormat.wrapStrategy,"
                  "userEnteredFormat.horizontalAlignment,"
                  "userEnteredFormat.verticalAlignment,"
                  "userEnteredFormat.backgroundColor,"
                  "userEnteredFormat.textFormat"}})
    # Rep-name cells: clear any inherited fill so only the rate cells carry
    # the band colours.
    fmt_reqs.append({"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": end,
                  "startColumnIndex": rep_c0, "endColumnIndex": rep_c0 + 1},
        "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 1, "green": 1, "blue": 1},
            "horizontalAlignment": "LEFT"}},
        "fields": "userEnteredFormat.backgroundColor,"
                  "userEnteredFormat.horizontalAlignment"}})
    _retry(lambda: ws.spreadsheet.batch_update({"requests": fmt_reqs}))

    o30, o60 = office["0-30"], office["31-60"]
    log(f"  ✓ {ws.title}: 0-30 {o30['activated']}/{o30['sold']} "
        f"= {o30['rate']:.1%} ({band_for(o30['rate'], '0-30')}), "
        f"31-60 {o60['activated']}/{o60['sold']} = {o60['rate']:.1%} "
        f"({band_for(o60['rate'], '31-60')}), {len(reps)} reps listed")


def update_churn_tab(ws: gspread.Worksheet, bases: dict,
                     helper_rows: list[list], log=print) -> None:
    cap = helper_capacity(ws)
    n = len(helper_rows)
    if n > cap - 1:
        raise RuntimeError(
            f"{ws.title}: {n} disconnect rows but the tab's formulas only "
            f"cover R2:AE{cap} ({cap - 1} rows). Extend the C5:C7 SUMIF and "
            "A16 FILTER ranges on the sheet, then re-run.")

    block = []
    for i, row in enumerate(helper_rows):
        r = i + 2
        vals = list(row)
        vals[3] = U_FORMULA.format(r=r)
        vals[11] = AC_FORMULA.format(r=r)
        block.append(vals)
    # Pad to full capacity — one write both fills and clears yesterday's tail.
    block += [[""] * 14 for _ in range(cap - 1 - n)]

    _retry(lambda: ws.batch_update([
        {"range": "B5:B7",
         "values": [[bases["Wireless"]], [bases["Air"]], [bases["Internet"]]]},
        {"range": f"R2:AE{cap}", "values": block},
    ], value_input_option="USER_ENTERED"))
    _retry(lambda: ws.format(f"R2:AE{cap}", CENTER))
    log(f"  ✓ {ws.title}: B5:B7 = {bases['Wireless']}/{bases['Air']}/"
        f"{bases['Internet']}, helper rows = {n} (capacity {cap - 1})")


# ----------------------------------------------------------- activations
def _reset_basic_filter(ws: gspread.Worksheet, n_rows: int) -> None:
    """Re-create the mandatory header filter spanning the new data, with no
    criteria (all rows visible). Uses the API's setBasicFilter — the
    'Filter for everyone' kind, per the runbook."""
    body = {"requests": [{"setBasicFilter": {"filter": {
        "range": {"sheetId": ws.id, "startRowIndex": 0,
                  "endRowIndex": n_rows + 1,
                  "startColumnIndex": 0, "endColumnIndex": 16},
    }}}]}
    _retry(lambda: ws.spreadsheet.batch_update(body))


def update_activations(ws: gspread.Worksheet, rows: list[list],
                       log=print) -> None:
    # 1. Preserve notes keyed by SPM (col O → P).
    existing = _retry(lambda: ws.get("O2:P"))
    notes = {r[0].strip(): r[1].strip() for r in existing
             if len(r) > 1 and r[0].strip() and r[1].strip()}
    old_last = len(_retry(lambda: ws.col_values(1)))

    # 2. Re-key the preserved notes onto the new rows.
    matched = set()
    out = []
    for r in rows:
        r = list(r)
        note = notes.get(str(r[14]).strip(), "")
        if note:
            matched.add(str(r[14]).strip())
        r[15] = note
        out.append(r)
    dropped = {k: v for k, v in notes.items() if k not in matched}
    if dropped:
        log(f"  ⚠ {len(dropped)} note(s) aged off with their orders: "
            + "; ".join(f"{k}: {v[:40]}" for k, v in dropped.items()))

    # 3. Paste first, clear the tail second (never leave the tab blank).
    n = len(out)
    _retry(lambda: ws.batch_update(
        [{"range": f"A2:P{n + 1}", "values": out}],
        value_input_option="USER_ENTERED"))
    if old_last > n + 1:
        _retry(lambda: ws.batch_clear([f"A{n + 2}:P{old_last + 20}"]))

    # 4. Center-align + filter over the fresh extent.
    _retry(lambda: ws.format(f"A1:P{max(n + 1, old_last)}", CENTER))
    _reset_basic_filter(ws, n)

    # 5. Per-rep summary: a rep new to the data must exist in the R-column
    #    list or the summary total silently under-counts (runbook 6.5).
    summary = _retry(lambda: ws.get("R2:R40"))
    listed = {r[0].strip() for r in summary if r and r[0].strip()}
    data_reps = {str(r[0]).strip() for r in out if str(r[0]).strip()}
    missing = sorted(data_reps - listed)
    if missing:
        first_empty = 2 + len([r for r in summary if r and r[0].strip()])
        tmpl_row = first_empty - 1
        tmpl = _retry(lambda: ws.get(
            f"S{tmpl_row}:Y{tmpl_row}", value_render_option="FORMULA"))[0]
        updates = []
        for j, rep in enumerate(missing):
            rr = first_empty + j
            formulas = [re.sub(rf"(?<![0-9]){tmpl_row}(?![0-9])", str(rr),
                               str(f)) for f in tmpl]
            updates.append({"range": f"R{rr}", "values": [[rep]]})
            updates.append({"range": f"S{rr}:Y{rr}", "values": [formulas]})
        _retry(lambda: ws.batch_update(updates,
                                       value_input_option="USER_ENTERED"))
        log(f"  ⚠ added new rep(s) to the summary: {', '.join(missing)}")

    log(f"  ✓ {ws.title}: {n} rows / {sum(int(r[2]) for r in out)} apps, "
        f"{len(matched)} note(s) preserved, filter + centering reset")
