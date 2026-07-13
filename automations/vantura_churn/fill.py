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

U_FORMULA = ('=IFERROR($AE{r}/IF($AD{r}="Wireless",$B$5,'
             'IF($AD{r}="Air",$B$6,$B$7)),"")')
AC_FORMULA = '=IFERROR(VLOOKUP($V{r},$R$100:$S$500,2,FALSE),"")'

CENTER = {"horizontalAlignment": "CENTER"}


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
