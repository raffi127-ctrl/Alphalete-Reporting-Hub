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
# Carlos's churn tab. PROMOTED 2026-07-19 (Megan) from the old "Churn" tab to
# "LUCY CHURN" — the rebuild carrying the activation-rate cells and the
# per-rep list. The daily run writes THIS tab now.
TAB_CHURN_CARLOS = "LUCY CHURN"
# The tab it replaced. No longer written; left in place on purpose so the
# team keeps its history (and as a fallback if the rebuild has to be backed
# out). Never delete it.
TAB_CHURN_RETIRED = "Churn"
TAB_CHURN_ATEF = "Churn - Atef"
TAB_ACTIVATIONS = "Activations"

# Formula templates. Column letters are filled in from helper_bounds() at
# write time — they are NOT fixed: the block moves when a column left of it
# is added or removed.
U_FORMULA = ('=IFERROR(${rem}{r}/IF(${key}{r}="Wireless",$B$5,'
             'IF(${key}{r}="Air",$B$6,$B$7)),"")')
AC_FORMULA = ('=IFERROR(VLOOKUP(${cust}{r},${n0}$100:${n1}$500,2,FALSE),"")')

CENTER = {"horizontalAlignment": "CENTER"}


def _rgb(hexstr: str) -> dict:
    h = hexstr.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255,
            "blue": int(h[4:6], 16) / 255}


# ---------------------------------------------------------------- palette
# One cohesive scheme for the churn tab (Megan 2026-07-19: "more aesthetic and
# better to look at"). Three deliberate levels of hierarchy, all in the navy
# family so the status colours are the only thing that shouts:
#   NAVY      page + column headers   (the tab's existing identity colour)
#   NAVY_MID  section headers         (was a loud #B6D7A8 green that fought it)
#   SLATE     sub-headers             (pale, lets the tier ramp read)
# The status ramp is the same hues as before, desaturated — a scale people
# scan every morning shouldn't be neon.
NAVY = "#193C65"
NAVY_MID = "#3E6491"
SLATE = "#E3EAF2"
GREEN = "#A9D18E"
GREEN_PALE = "#CBE3B7"
AMBER = "#FFE08A"
PEACH = "#F8CB9B"
ROSE = "#F2A9A9"
RED_DEEP = "#CC6A70"

HEADER_BG = _rgb(NAVY)
WHITE_TEXT = {"foregroundColor": {"red": 1, "green": 1, "blue": 1}}
# Best → worst. The Wireless chart has 6 tiers, AIR/AWB has 5.
TIER_RAMP_6 = [GREEN, GREEN_PALE, AMBER, PEACH, ROSE, RED_DEEP]
TIER_RAMP_5 = [GREEN, GREEN_PALE, AMBER, ROSE, RED_DEEP]


def open_sheet():
    return open_by_key(SHEET_ID)


# Helper-block column offsets from its FIRST column (the block is 14 wide).
H_LINES, H_CHURN_F, H_CUSTOMER = 2, 3, 4
H_NOTES_F, H_KEY, H_REMAINING = 11, 12, 13
H_WIDTH = 14
# Gap between the helper block and the per-rep list.
REP_GAP = 2


def _col_idx(letter: str) -> int:
    """Column letter → 0-based index."""
    n = 0
    for ch in letter:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def helper_bounds(ws: gspread.Worksheet) -> dict:
    """Where the helper block ACTUALLY is, derived from the tab's own
    formulas — never hardcoded.

    Deleting a column left of the block shifts it and Google silently
    rewrites A16/C5 to match, so a constant like 'R:AE' goes stale without
    anything looking broken. (Happened 2026-07-19 on LUCY CHURN: two empty
    stub columns were removed and the block moved R:AE → P:AC.)

    Returns {'f0': 0-based first column, 'cap': last helper row}.
    """
    a16 = _retry(lambda: ws.get("A16", value_render_option="FORMULA"))
    f = str(a16[0][0]) if a16 and a16[0] else ""
    m = re.search(r"FILTER\(\s*\$([A-Z]{1,2})\$(\d+):\$([A-Z]{1,2})\$(\d+)\s*,"
                  r"\s*\$([A-Z]{1,2})\$\d+:\$([A-Z]{1,2})\$(\d+)", f)
    if not m:
        raise RuntimeError(
            f"{ws.title}!A16 is not the expected FILTER formula (got: {f!r}) "
            "— refusing to guess where the helper block lives.")
    f0, key_col, cap = _col_idx(m.group(1)), _col_idx(m.group(5)), int(m.group(7))
    if key_col - f0 != H_KEY:
        raise RuntimeError(
            f"{ws.title}: helper block looks reshaped — FILTER starts at "
            f"{m.group(1)} but its key column is {m.group(5)} "
            f"(expected offset {H_KEY}, got {key_col - f0}).")
    return {"f0": f0, "cap": cap}


def helper_capacity(ws: gspread.Worksheet) -> int:
    """Last helper row this tab's formulas can see. Writing past it would
    show wrong counts AND a truncated list."""
    return helper_bounds(ws)["cap"]


# Activation-rate colour bands (Megan 2026-07-19). Carlos's Loom misspoke on
# the 31-60 floor ("anything below is green"); these are the agreed bands.
# NB: deliberately NOT the view's own 'Activation Color' column — Tableau
# bands 31-60 differently and would call 74.6% red where these call it yellow.
BANDS = {
    "0-30": [(0.75, "green"), (0.65, "yellow"), (0.0, "red")],
    "31-60": [(0.80, "green"), (0.70, "yellow"), (0.0, "red")],
}
# Same hues as the tiers chart so the whole tab reads as one scale.
BAND_BG = {"green": _rgb(GREEN), "yellow": _rgb(AMBER), "red": _rgb(ROSE)}

def rep_list_col(ws: gspread.Worksheet) -> int:
    """0-based column for the per-rep list: just right of the helper block.

    Derived, not a constant — a hardcoded 'AG' silently writes into the
    wrong place once a column left of it is inserted or deleted.
    """
    b = helper_bounds(ws)
    return b["f0"] + H_WIDTH + REP_GAP - 1


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


def apply_theme(ws: gspread.Worksheet, log=print) -> None:
    """Restyle the churn tab's header + tiers chart to the palette above.

    Scope is deliberately limited: the ROLLOFF LIST (the "orders part") and
    its conditional 7-day red flag are NOT touched — that colour carries
    meaning and Megan asked for it left alone. Neither are the tier NUMBER
    and impact columns, which carry manual highlighting.

    Everything is located by LABEL, not fixed cells — the tiers chart has
    already moved once when columns were inserted.
    """
    grid = _retry(lambda: ws.get("A1:R14"))
    hdr_row = None
    tier_cols = []          # (col_idx, n_tiers) for each "Churn Tiers …" block
    for ri, row in enumerate(grid, start=1):
        for ci, val in enumerate(row):
            s = str(val or "").strip()
            if s.startswith("Churn Tiers"):
                tier_cols.append((ci, ri))
            if s == "Tier":
                hdr_row = ri
    if not tier_cols or hdr_row is None:
        log("  ⚠ theme skipped: couldn't find the 'Churn Tiers' chart by label")
        return

    reqs = []

    def bg(r0, r1, c0, c1, colour, text=None):
        cell = {"backgroundColor": _rgb(colour)}
        fields = "userEnteredFormat.backgroundColor"
        if text:
            cell["textFormat"] = text
            fields += ",userEnteredFormat.textFormat"
        reqs.append({"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": r0, "endRowIndex": r1,
                      "startColumnIndex": c0, "endColumnIndex": c1},
            "cell": {"userEnteredFormat": cell}, "fields": fields}})

    # Section headers ("Churn Tiers Wireless" / "… AIR & AWB") — mid navy,
    # white text, so they sit UNDER the page header rather than competing.
    for ci, ri in tier_cols:
        bg(ri - 1, ri + 1, ci, ci + 4, NAVY_MID, dict(WHITE_TEXT, bold=True))
    # Sub-header row ("Tier | 0-30 Day | … Impact") — pale slate, dark text.
    first_c = min(c for c, _ in tier_cols)
    last_c = max(c for c, _ in tier_cols) + 4
    bg(hdr_row - 1, hdr_row, first_c, last_c, SLATE,
       {"bold": True, "foregroundColor": _rgb(NAVY)})

    # The percentage bands themselves, best → worst. Column of each block is
    # its "0-30 Day" column = the tier column + 1.
    for ci, _ri in tier_cols:
        pct_col = ci + 1
        n = sum(1 for r in grid[hdr_row:hdr_row + 8]
                if len(r) > pct_col and str(r[pct_col] or "").strip())
        ramp = TIER_RAMP_6 if n >= 6 else TIER_RAMP_5
        for k in range(min(n, len(ramp))):
            bg(hdr_row + k, hdr_row + k + 1, pct_col, pct_col + 1, ramp[k])

    # ------------------------------------------------ the filter control
    # Megan 2026-07-19: "it's very hard to see where you can choose what to
    # filter by — needs to be very clear." It was plain white text in a plain
    # white cell, indistinguishable from its own label. Give it an obvious
    # input-box affordance: slate fill, thick navy border, and a spelled-out
    # label + hint either side. Cell derived, never assumed.
    target = viewing_cell(ws)                       # e.g. "B3"
    tcol = _col_idx(re.match(r"([A-Z]{1,2})", target).group(1))
    trow = int(re.search(r"(\d+)", target).group(1))
    navy_border = {"style": "SOLID_THICK", "color": _rgb(NAVY)}

    reqs.append({"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": trow - 1,
                  "endRowIndex": trow, "startColumnIndex": tcol,
                  "endColumnIndex": tcol + 1},
        "cell": {"userEnteredFormat": {
            "backgroundColor": _rgb(SLATE),
            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
            "textFormat": {"bold": True, "fontSize": 12,
                           "foregroundColor": _rgb(NAVY)},
            "borders": {"top": navy_border, "bottom": navy_border,
                        "left": navy_border, "right": navy_border}}},
        "fields": "userEnteredFormat.backgroundColor,"
                  "userEnteredFormat.horizontalAlignment,"
                  "userEnteredFormat.verticalAlignment,"
                  "userEnteredFormat.textFormat,userEnteredFormat.borders"}})
    # Label to its left, hint to its right — both plain so the control is the
    # only thing that looks clickable.
    if tcol > 0:
        reqs.append({"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": trow - 1,
                      "endRowIndex": trow, "startColumnIndex": tcol - 1,
                      "endColumnIndex": tcol},
            "cell": {"userEnteredFormat": {
                "horizontalAlignment": "RIGHT",
                "textFormat": {"bold": True, "fontSize": 11,
                               "foregroundColor": _rgb(NAVY)}}},
            "fields": "userEnteredFormat.horizontalAlignment,"
                      "userEnteredFormat.textFormat"}})
    reqs.append({"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": trow - 1,
                  "endRowIndex": trow, "startColumnIndex": tcol + 1,
                  "endColumnIndex": tcol + 2},
        "cell": {"userEnteredFormat": {
            "horizontalAlignment": "LEFT",
            "textFormat": {"italic": True, "fontSize": 10,
                           "foregroundColor": _rgb("#6B7C93")}}},
        "fields": "userEnteredFormat.horizontalAlignment,"
                  "userEnteredFormat.textFormat"}})

    # The tier-NUMBER columns carry a stray pale-peach fill on one cell
    # (present on the live tab too, and it marks tier 6 while Carlos sits at
    # tier 4 — decorative, not a marker). Flatten them so the ramp beside
    # them is the only colour in the chart.
    for ci, _ri in tier_cols:
        bg(hdr_row, hdr_row + 6, ci, ci + 1, "#FFFFFF")

    _retry(lambda: ws.spreadsheet.batch_update({"requests": reqs}))

    # Spell out what the control does. The dropdown VALUE has to stay an exact
    # member of the validation list (strict), so the wording goes in the cells
    # either side of it, never in the control itself.
    label_cell = f"{_colletter(tcol - 1)}{trow}" if tcol > 0 else None
    hint_cell = f"{_colletter(tcol + 1)}{trow}"
    # Label kept SHORT — column A is sized for "Days Left" and anything
    # longer gets clipped at the sheet edge. The hint carries the detail.
    text_updates = [{"range": hint_cell,
                     "values": [["◀ pick a product to filter "
                                 "the rolloff list below"]]}]
    if label_cell:
        text_updates.append({"range": label_cell, "values": [["Filter:"]]})
    _retry(lambda: ws.batch_update(text_updates,
                                   value_input_option="USER_ENTERED"))

    # Churn % gradient rules still ran the old neon ramp
    # (#6AA84F -> #FFD966 -> #990000). Re-point them at the palette, keeping
    # each rule's own thresholds — those are per-product and load-bearing.
    meta = _retry(lambda: ws.spreadsheet.fetch_sheet_metadata(
        {"fields": "sheets(properties(sheetId),conditionalFormats)"}))
    grad_reqs = []
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] != ws.id:
            continue
        for idx, rule in enumerate(s.get("conditionalFormats", [])):
            g = rule.get("gradientRule")
            if not g:
                continue
            new = {k: dict(g[k]) for k in ("minpoint", "midpoint", "maxpoint")
                   if k in g}
            for k, colour in (("minpoint", GREEN), ("midpoint", AMBER),
                              ("maxpoint", RED_DEEP)):
                if k in new:
                    # Set BOTH: the API returns the legacy `color` and the
                    # newer `colorStyle`, and colorStyle WINS. Writing only
                    # `color` leaves the old ramp in place with no error.
                    new[k]["color"] = _rgb(colour)
                    new[k]["colorStyle"] = {"rgbColor": _rgb(colour)}
            grad_reqs.append({"updateConditionalFormatRule": {
                "sheetId": ws.id, "index": idx,
                "rule": {"ranges": rule["ranges"], "gradientRule": new}}})
    if grad_reqs:
        _retry(lambda: ws.spreadsheet.batch_update({"requests": grad_reqs}))

    log(f"  ✓ {ws.title}: theme applied ({len(tier_cols)} tier block(s), "
        f"{len(grad_reqs)} gradient rule(s), rolloff list untouched)")


def hide_helper_columns(ws: gspread.Worksheet, log=print) -> bool:
    """Hide the helper block, matching the live tabs.

    Duplicating a churn tab does NOT carry the hidden state over, so a fresh
    copy shows all 14 columns of raw per-account scratch sitting right of
    the report. Idempotent; returns True when it actually changed something.
    """
    b = helper_bounds(ws)
    first = b["f0"]
    last = first + H_WIDTH
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
    log(f"  ✓ {ws.title}: hid helper columns "
        f"{_colletter(first)}:{_colletter(last - 1)}")
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

    _retry(lambda: ws.batch_update(updates, value_input_option="USER_ENTERED"))

    # Per-rep list: 0-30 day ONLY, greatest → least, and ONLY reps that
    # actually have 0-30 data (Megan 2026-07-20). A rep with no 0-30 sales
    # has an undefined rate, not 0%, so they're dropped from the list rather
    # than shown blank. [[feedback_one_gig_blank_is_na]]
    ranked = sorted(
        ((rep, v) for rep, v in reps.items() if v["0-30"]["rate"] is not None),
        key=lambda kv: (-kv[1]["0-30"]["rate"], kv[0]))
    rows = [["Rep Name", "0-30 Day Activation Rate"]]
    for rep, v in ranked:
        rows.append([rep, _pct(v["0-30"])])
    rep_c0 = rep_list_col(ws)
    rep_first = _colletter(rep_c0)
    end = len(rows)

    # Wipe the OLD block first — it was 3 columns wide (0-30 + 31-60) and
    # could be longer than the new list, so both the dropped 31-60 column and
    # any surplus rows must clear (values AND their band fills).
    old_end = _colletter(rep_c0 + 2)
    _retry(lambda: ws.batch_clear(
        [f"{rep_first}1:{old_end}{ws.row_count}"]))
    _retry(lambda: ws.spreadsheet.batch_update({"requests": [{"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": 0,
                  "endRowIndex": ws.row_count, "startColumnIndex": rep_c0,
                  "endColumnIndex": rep_c0 + 3},
        "cell": {"userEnteredFormat": {}}, "fields": "userEnteredFormat"}}]}))

    _retry(lambda: ws.batch_update(
        [{"range": f"{rep_first}1:{_colletter(rep_c0 + 1)}{end}",
          "values": rows}], value_input_option="USER_ENTERED"))

    def _bg(row0, col0, colour):
        return {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": row0,
                      "endRowIndex": row0 + 1, "startColumnIndex": col0,
                      "endColumnIndex": col0 + 1},
            "cell": {"userEnteredFormat": {
                "backgroundColor": BAND_BG[colour]}},
            "fields": "userEnteredFormat.backgroundColor"}}

    # Office E5/F5 percent + band (both buckets stay at office level).
    fmt_reqs = [{"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": 4, "endRowIndex": 5,
                  "startColumnIndex": 4, "endColumnIndex": 6},
        "cell": {"userEnteredFormat": {
            "numberFormat": {"type": "PERCENT", "pattern": "0.0%"},
            "horizontalAlignment": "CENTER"}},
        "fields": "userEnteredFormat.numberFormat,"
                  "userEnteredFormat.horizontalAlignment"}}]
    for ci, key in ((4, "0-30"), (5, "31-60")):
        c = band_for(office[key]["rate"], key)
        if c:
            fmt_reqs.append(_bg(4, ci, c))

    # Rep 0-30 column: percent, centred, banded.
    fmt_reqs.append({"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": end,
                  "startColumnIndex": rep_c0 + 1, "endColumnIndex": rep_c0 + 2},
        "cell": {"userEnteredFormat": {
            "numberFormat": {"type": "PERCENT", "pattern": "0.0%"},
            "horizontalAlignment": "CENTER"}},
        "fields": "userEnteredFormat.numberFormat,"
                  "userEnteredFormat.horizontalAlignment"}})
    for i, (_rep, v) in enumerate(ranked):
        c = band_for(v["0-30"]["rate"], "0-30")
        if c:
            fmt_reqs.append(_bg(1 + i, rep_c0 + 1, c))
    # Rate column fixed width; name column auto-fits (names run past 30 chars).
    fmt_reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                  "startIndex": rep_c0 + 1, "endIndex": rep_c0 + 2},
        "properties": {"pixelSize": 120}, "fields": "pixelSize"}})
    # Header (navy / white / Arial 12), matching the tab's other headers.
    fmt_reqs.append({"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1,
                  "startColumnIndex": rep_c0, "endColumnIndex": rep_c0 + 2},
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
    # Rep-name cells: white fill (only the rate cells carry band colours),
    # left-aligned.
    fmt_reqs.append({"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": end,
                  "startColumnIndex": rep_c0, "endColumnIndex": rep_c0 + 1},
        "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 1, "green": 1, "blue": 1},
            "horizontalAlignment": "LEFT"}},
        "fields": "userEnteredFormat.backgroundColor,"
                  "userEnteredFormat.horizontalAlignment"}})
    # Auto-fit the name column LAST, so it measures the finished cells.
    fmt_reqs.append({"autoResizeDimensions": {"dimensions": {
        "sheetId": ws.id, "dimension": "COLUMNS",
        "startIndex": rep_c0, "endIndex": rep_c0 + 1}}})
    _retry(lambda: ws.spreadsheet.batch_update({"requests": fmt_reqs}))

    o30, o60 = office["0-30"], office["31-60"]
    log(f"  ✓ {ws.title}: 0-30 {o30['activated']}/{o30['sold']} "
        f"= {o30['rate']:.1%} ({band_for(o30['rate'], '0-30')}), "
        f"31-60 {o60['activated']}/{o60['sold']} = {o60['rate']:.1%} "
        f"({band_for(o60['rate'], '31-60')}), "
        f"{len(ranked)} reps with 0-30 data listed")


def update_churn_tab(ws: gspread.Worksheet, bases: dict,
                     helper_rows: list[list], log=print) -> None:
    b = helper_bounds(ws)
    f0, cap = b["f0"], b["cap"]
    first, last = _colletter(f0), _colletter(f0 + H_WIDTH - 1)
    n = len(helper_rows)
    if n > cap - 1:
        raise RuntimeError(
            f"{ws.title}: {n} disconnect rows but the tab's formulas only "
            f"cover {first}2:{last}{cap} ({cap - 1} rows). Extend the C5:C7 "
            "SUMIF and A16 FILTER ranges on the sheet, then re-run.")

    cols = {"rem": _colletter(f0 + H_REMAINING), "key": _colletter(f0 + H_KEY),
            "cust": _colletter(f0 + H_CUSTOMER),
            "n0": _colletter(f0), "n1": _colletter(f0 + 1)}
    block = []
    for i, row in enumerate(helper_rows):
        r = i + 2
        vals = list(row)
        vals[H_CHURN_F] = U_FORMULA.format(r=r, **cols)
        vals[H_NOTES_F] = AC_FORMULA.format(r=r, **cols)
        block.append(vals)
    # Pad to full capacity — one write both fills and clears yesterday's tail.
    block += [[""] * H_WIDTH for _ in range(cap - 1 - n)]

    _retry(lambda: ws.batch_update([
        {"range": "B5:B7",
         "values": [[bases["Wireless"]], [bases["Air"]], [bases["Internet"]]]},
        {"range": f"{first}2:{last}{cap}", "values": block},
    ], value_input_option="USER_ENTERED"))
    _retry(lambda: ws.format(f"{first}2:{last}{cap}", CENTER))
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


# Row-relative references in the summary formulas: $R2, $S2, $T2 … $Y2.
# Absolute ranges ($A$2:$A$500, $C$2:$C$500) must NOT be rewritten, so match
# only "$<col><digits>" for the summary's own columns — a bare number regex
# would happily corrupt "$A$2" and "$C$500".
_SUMMARY_REF = re.compile(r"\$([R-Y])(\d+)")


def dedupe_activation_summary(ws: gspread.Worksheet, log=print) -> int:
    """Compact the per-rep summary (R:Y), keeping each rep's FIRST row.

    The old R2:R40 lookup couldn't see past row 40, so reps below it were
    re-appended on every run — the list reached 49 rows with duplicates and
    gaps. update_activations() no longer creates them; this clears the ones
    already there. Returns how many rows were removed.
    """
    last = ws.row_count
    grid = _retry(lambda: ws.get(f"R2:Y{last}", value_render_option="FORMULA"))
    seen, keep = set(), []
    for row in grid:
        name = str(row[0]).strip() if row else ""
        if not name or name in seen:
            continue
        seen.add(name)
        keep.append(list(row) + [""] * (8 - len(row)))
    if not keep:
        log("  ⚠ summary is empty — nothing to dedupe")
        return 0

    old_last = 1 + len(grid)
    block = []
    for i, row in enumerate(keep):
        rr = i + 2
        block.append([row[0]] + [
            _SUMMARY_REF.sub(lambda m: f"${m.group(1)}{rr}", str(c))
            for c in row[1:8]])
    _retry(lambda: ws.batch_update(
        [{"range": f"R2:Y{len(block) + 1}", "values": block}],
        value_input_option="USER_ENTERED"))
    removed = old_last - (len(block) + 1)
    if removed > 0:
        _retry(lambda: ws.batch_clear([f"R{len(block) + 2}:Y{old_last}"]))
    log(f"  ✓ {ws.title}: summary compacted to {len(block)} unique rep(s) "
        f"({removed} duplicate/blank row(s) removed)")
    return removed


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
    # Read the WHOLE column, not a fixed R2:R40 window. The list outgrew 40
    # rows on 2026-07-19 and everything past it became invisible to this
    # check: those reps looked "missing" and were re-appended on EVERY run,
    # so the summary silently accumulated duplicates (Veimar Perez Rodriguez
    # reached 3 copies) and the new rows landed on top of existing ones.
    summary = _retry(lambda: ws.get(f"R2:R{ws.row_count}"))
    listed = {r[0].strip() for r in summary if r and r[0].strip()}
    data_reps = {str(r[0]).strip() for r in out if str(r[0]).strip()}
    missing = sorted(data_reps - listed)
    if missing:
        # Position from the LAST populated row, not a count — a count is wrong
        # the moment the column has a gap in it.
        last_used = 1
        for i, r in enumerate(summary, start=2):
            if r and r[0].strip():
                last_used = i
        first_empty = last_used + 1
        tmpl_row = last_used
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
