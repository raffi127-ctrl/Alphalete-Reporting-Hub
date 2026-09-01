"""The two PNGs that ride along with the post, in Evelyn's order.

  1. the Energy Sales Board — the same 'Energy Sales Board' image the 4:33am
     Alphalete Production post carries, RE-RENDERED. Not reused: the board's
     day cells are filled by the 'Alphalete Reporting' account 2-3 hours AFTER
     that post, so the 4:34am picture of them is routinely out of date by the
     time this check runs. Rendering it here is what makes 'Sales Board: N'
     and the picture agree.
  2. the webform rows for that sale day — Timestamp / rep / manager / customer,
     sorted by rep, so anyone tagged can see for themselves which of their
     sales did land.

Both are Google-Sheets PDF exports of a THROWAWAY DUPLICATE of the tab, never
of the live tab, so the office's own filters and column widths are untouched
and nothing we do can be seen by anyone working in the sheet. The duplicate is
deleted in a `finally` — including the webform's, which lives in a workbook
whose only other tabs hold the form's real responses.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from automations.alphalete_production import capture as C
from automations.alphalete_production import pages as PAGES
from automations.energy_crossref import webform as W

TMP_TAB = "_energy_crossref_tmp"


def energy_board_png(day: dt.date, out_dir: Path) -> Path:
    """The Energy leaderboard for `day`, as the daily post renders it.

    capture_all frames everything off 'yesterday', so it is handed the day AFTER
    the sale day — that is the same call the 4:33am post makes."""
    # The section was RETIRED from the daily post on 2026-09-01 along with this
    # whole report, so SECTIONS no longer carries it — a bare next() would raise
    # StopIteration with nothing to read. Both modules are stood down, so this
    # is only reachable by someone deleting energy_crossref/DISABLED for a
    # backfill; say what to do instead of dying opaquely.
    spec = next((s for s in PAGES.SECTIONS if s["id"] == "energy_board"), None)
    if spec is None:
        raise RuntimeError(
            "no 'energy_board' section in alphalete_production.pages — it was "
            "retired 2026-09-01 when the Energy program ended. Re-add the entry "
            "there (the 'energy' recipe in capture.py is still intact) if you "
            "need this image again.")
    # capture_all returns (captures, grid, tab title) — only the captures matter
    # here, and each capture is (meta, png path).
    out, _grid, _tab = C.capture_all([spec], day + dt.timedelta(days=1), out_dir)
    if not out:
        raise RuntimeError(
            "the Energy Sales Board section failed to render — capture_all "
            "swallows a section's error to protect the daily post, so the "
            "reason is on the line above starting '[alphalete_production]'")
    return out[0][1]


def _sweep(ss) -> None:
    for w in ss.worksheets():
        if w.title == TMP_TAB:
            try:
                ss.batch_update({"requests": [{"deleteSheet": {"sheetId": w.id}}]})
            except Exception:
                pass


def webform_png(day: dt.date, out_dir: Path, *, sheet_id: str = W.SHEET_ID,
                tab: str = W.TAB) -> Path | None:
    """The day's webform rows — cols Timestamp..Customer, sorted by rep name.

    None when nobody filed a form for `day`: a header row on its own is a
    picture of nothing, and the bullet already says 0.
    """
    from automations.recruiting_report.fill import open_by_key

    ss = open_by_key(sheet_id)
    _sweep(ss)                                   # orphan from a crashed run
    src = ss.worksheet(tab)
    grid = src.get_all_values()
    cols = W.header_cols(grid[0])
    rows = W.read_rows(grid)
    if not [s for s in rows if s.sale_date == day]:
        return None

    # Timestamp | rep | manager | customer — the four Evelyn shows. Taken from
    # the header lookup, not A:D, so a new form question inserted in the middle
    # can't silently shift the picture one column over.
    show = [cols["timestamp"], cols["rep"], cols["manager"], cols["customer"]]
    ncols = max(len(grid[0]), max(show) + 1)
    last_row = len(grid)

    rep = ss.batch_update({"requests": [{"duplicateSheet": {
        "sourceSheetId": src.id, "insertSheetIndex": 0,
        "newSheetName": TMP_TAB}}]})
    gid = rep["replies"][0]["duplicateSheet"]["properties"]["sheetId"]
    try:
        # Filter the SALE DATE column to this day only, then sort by rep name.
        # Sheets' hiddenValues match the cell's DISPLAYED text, so the list is
        # built by parsing every value that's actually on the tab rather than by
        # guessing this day's format ('8/13/2026' vs '08/13/2026').
        seen = {str(r[cols["sale_date"]]).strip()
                for r in grid[1:] if cols["sale_date"] < len(r)}
        hidden = sorted(v for v in seen if W.parse_date(v) != day)
        reqs = C._hide_cols(gid, set(show), ncols)
        # Widen the four shown columns to their content. The live tab's customer
        # column is narrower than the names people type, so without this the
        # picture cuts off exactly the field a rep uses to recognise their own
        # sale ("SRIRAM NARESH KUMAR YELISET…").
        reqs += [{"autoResizeDimensions": {"dimensions": {
            "sheetId": gid, "dimension": "COLUMNS",
            "startIndex": c, "endIndex": c + 1}}} for c in sorted(show)]
        reqs.append({"setBasicFilter": {"filter": {
            "range": {"sheetId": gid, "startRowIndex": 0,
                      "endRowIndex": last_row, "startColumnIndex": 0,
                      "endColumnIndex": ncols},
            "sortSpecs": [{"dimensionIndex": cols["rep"],
                           "sortOrder": "ASCENDING"}],
            "filterSpecs": [{"columnIndex": cols["sale_date"],
                             "filterCriteria": {"hiddenValues": hidden}}]}}})
        ss.batch_update({"requests": reqs})
        left = C.col_letter(min(show))
        right = C.col_letter(max(show))
        token = C._access_token()
        return C._export_png(gid, f"{left}1:{right}{last_row}",
                             out_dir / f"webform_{day:%Y%m%d}.png", token,
                             sheet_id=sheet_id)
    finally:
        try:
            ss.batch_update({"requests": [{"deleteSheet": {"sheetId": gid}}]})
        except Exception:
            pass
