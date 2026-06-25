"""Daily Rep Breakdown - ATT Program — the one-click daily runner.

This is the Hub-button entrypoint. It orchestrates the full pipeline:

  Monday:   full wipe -> scrape ALL days -> Tableau -> full cosmetic pass
  Tue-Sun:  re-scrape yesterday + today -> incremental -> Tableau -> skip-unchanged
  Both:     refresh tab colors + desktop notification on success/failure

Why Monday is special: per Raf, each Monday the previous week is
overwritten so terminated reps drop off. A wipe gives a clean slate.
Mid-week, reps are never removed -- a rep terminated Wednesday keeps
their Mon/Tue data visible, and a rep who first appears Wednesday is
added.

Why mid-week re-scrapes yesterday: a same-day scrape only ever sees a
partial day, so today's numbers are always incomplete until tomorrow's
run re-pulls the now-finished day.

Prereq: debug Chrome at :9222 with ownerville logged in. Tableau SSO is
bootstrapped automatically from the ownerville session (step7).

Run:
    .venv/bin/python -m automations.focus_office_att.daily
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

from automations.recruiting_report import fill as _fill

DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"
CDP_URL = "http://localhost:9222"
WORKSPACE = Path(__file__).resolve().parents[2]
# The interpreter currently running this file — correct on macOS, Windows,
# and Linux. (A hardcoded ".venv/bin/python" only exists on macOS/Linux;
# Windows venvs put it at ".venv\Scripts\python.exe".)
PYTHON = sys.executable
LOG_DIR = WORKSPACE / "output" / "logs"
SCRAPE_RESULTS = WORKSPACE / "output" / "focus_office_scrape_results.json"
# Resume checkpoint written by run_all_owners (Phase 2). That module owns
# it; daily.py only deletes it — after the Monday wipe (a wipe blanks the
# sheet, so a resume would skip owners whose data is now gone) and after a
# fully successful run. A file that survives a run means it was interrupted.
RUN_CHECKPOINT = WORKSPACE / "output" / "focus_office_run_checkpoint.json"

TABLEAU_ONLY_MARK = "\U0001f539"  # blue diamond emoji

# Tabs that are not owner reports — never scraped, never colored.
NON_OWNER_TABS = {"Template", "Raf play"}

# Tab colors
AMBER = {"red": 0.96, "green": 0.69, "blue": 0.26}       # pending OV access
LIGHT_BLUE = {"red": 0.62, "green": 0.76, "blue": 0.91}  # has Tableau-only reps


def _q(title: str) -> str:
    """A1-notation-safe single-quoted tab title (escapes embedded quotes)."""
    return "'" + title.replace("'", "''") + "'"


# ----------------------------------------------------------------------
# Pre-flight
# ----------------------------------------------------------------------
def _chrome_ok() -> tuple[bool, str]:
    """Return (ok, message). ok=True iff debug Chrome is reachable AND an
    ownerville tab is open (logged-in session is assumed if the tab is
    on a v2.ownerville.com URL with an rqst param)."""
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json", timeout=4) as r:
            tabs = json.loads(r.read())
    except Exception:
        return False, "Debug Chrome isn't running on port 9222."
    ov = [t for t in tabs if "ownerville" in (t.get("url") or "").lower()]
    if not ov:
        return False, "Chrome is open but no ownerville tab is logged in."
    return True, "Chrome + ownerville OK."


# ----------------------------------------------------------------------
# Future-day wipe — Tue-Sat: clear cells for days AFTER today this week.
# Without this, last week's Wed-Sun data lingers in the same columns when
# the week rolls over (since the column headers change but the cell values
# don't until something writes them). Sunday has nothing to clear.
# ----------------------------------------------------------------------
def wipe_future_day_blocks(sh, today: "dt.date") -> int:
    """Clear cells in day-blocks for days AFTER `today` (this week).
    Each day spans 12 cols starting at col 13 (Mon). Clears both values
    and userEnteredFormat in the CURRENT zone only (rows 3 .. just above the
    LAST WEEK block) — NOT rows 3-200, which used to reach into the frozen
    LAST WEEK block and wipe its later days a column at a time as the week
    progressed (by Thursday last week's Fri-Sun were gone — Megan 2026-06-18).
    No-op on Sunday."""
    dow = today.weekday()    # 0=Mon..6=Sun
    first_future_col = 13 + (dow + 1) * 12   # 0-indexed column to start clearing
    if first_future_col > 96:
        return 0   # Sun — nothing after today
    tabs = [t for t in sh.worksheets() if t.title not in NON_OWNER_TABS]
    if not tabs:
        return 0
    # A1 letters for the range
    def _coletter(c: int) -> str:
        s = ""
        while c > 0:
            c, r = divmod(c - 1, 26)
            s = chr(65 + r) + s
        return s
    # Stop ABOVE the frozen LAST WEEK block so its (complete) later days are
    # never clobbered. LAST_WEEK_LABEL_ROW-1 is the last current-zone row.
    last_cur_row = LAST_WEEK_LABEL_ROW - 1
    rng = f"{_coletter(first_future_col)}3:{_coletter(96)}{last_cur_row}"
    sh.values_batch_clear(body={"ranges": [f"{_q(t.title)}!{rng}" for t in tabs]})
    sh.batch_update({"requests": [
        {"updateCells": {
            "range": {"sheetId": t.id,
                      "startRowIndex": 2, "endRowIndex": last_cur_row,
                      "startColumnIndex": first_future_col - 1,
                      "endColumnIndex": 96},
            "fields": "userEnteredFormat",
        }} for t in tabs
    ]})
    return len(tabs)


# Day-block column-group ranges (0-indexed half-open) — Mon..Sun.
# These match the pre-existing depth=2 column groups Sheets already has on
# every owner tab, exactly. Each block is 11 cols; the 1-col gap between
# blocks (col 24, 36, 48, ...) is where the group's +/- toggle button
# lives, so it's intentionally NOT part of the group.
_DAY_BLOCK_RANGES = [
    (13, 24),  # Mon = N:X
    (25, 36),  # Tue = Z:AJ
    (37, 48),  # Wed = AL:AV
    (49, 60),  # Thu = AX:BH
    (61, 72),  # Fri = BJ:BT
    (73, 84),  # Sat = BV:CF
    (85, 96),  # Sun = CH:CR
]


def set_day_column_collapsed(sh, today: "dt.date") -> int:
    """Collapse day-block column GROUPS for days AFTER today; expand days
    up to and including today. Uses the pre-existing depth=2 column groups
    so the +/- toggle button stays visible at the top — Megan wants the
    user to be able to expand a collapsed day with one click, not just
    have the columns silently hidden.

    Sets BOTH the group's `collapsed` flag AND the underlying columns'
    `hiddenByUser` flag in the same batch — the Sheets API doesn't tie
    them together automatically (a group can be marked collapsed while
    its columns stay visible, which is what was breaking the visual
    effect before). The collapsed flag drives the +/- button, the
    hiddenByUser flag actually hides the columns; together they give
    Megan the expand-on-click UX she asked for. Idempotent."""
    dow = today.weekday()    # 0=Mon..6=Sun
    tabs = [t for t in sh.worksheets() if t.title not in NON_OWNER_TABS]
    if not tabs:
        return 0
    requests = []
    for t in tabs:
        for day_idx, (start, end) in enumerate(_DAY_BLOCK_RANGES):
            should_collapse = (day_idx > dow)
            # 1. Group's collapsed state (controls the +/- button glyph).
            requests.append({"updateDimensionGroup": {
                "dimensionGroup": {
                    "range": {"sheetId": t.id, "dimension": "COLUMNS",
                              "startIndex": start, "endIndex": end},
                    "depth": 2,
                    "collapsed": should_collapse,
                },
                "fields": "collapsed",
            }})
            # 2. Columns' hiddenByUser (actually hides them visually).
            requests.append({"updateDimensionProperties": {
                "range": {"sheetId": t.id, "dimension": "COLUMNS",
                          "startIndex": start, "endIndex": end},
                "properties": {"hiddenByUser": should_collapse},
                "fields": "hiddenByUser",
            }})
    sh.batch_update({"requests": requests})
    return len(tabs)


# ----------------------------------------------------------------------
# Monday wipe
# ----------------------------------------------------------------------
def wipe_all_owner_tabs(sh) -> int:
    """Clear the CURRENT-week block (rows 3..CURRENT_ZONE_LAST_ROW=109) + its
    formatting on every owner tab. Scoped to 109 so the frozen LAST WEEK block (rows 110+) is
    NEVER erased — the rollover runs first to freeze last week, then this
    clears only the current week for the fresh fill. Leaves rows 1-2 (banners
    + headers) + conditional rules. Monday-only.

    Batched: one values-clear + one format-clear covering ALL tabs."""
    tabs = [t for t in sh.worksheets() if t.title not in NON_OWNER_TABS]
    if not tabs:
        return 0
    last = CURRENT_ZONE_LAST_ROW   # current week occupies rows 3..last
    # A basic FILTER (the report recycles inactive reps via a filter) makes
    # values_batch_clear SKIP the filter-hidden rows — so stale/aggregate reps
    # survive the wipe and linger. Capture + clear every tab's filter first,
    # wipe, then restore.
    meta = sh.fetch_sheet_metadata(
        {"fields": "sheets(properties.sheetId,basicFilter)"})
    filters = {s["properties"]["sheetId"]: s["basicFilter"]
               for s in meta.get("sheets", []) if s.get("basicFilter")}
    if filters:
        sh.batch_update({"requests": [{"clearBasicFilter": {"sheetId": sid}}
                                      for sid in filters]})
    sh.values_batch_clear(body={"ranges": [f"{_q(t.title)}!A3:CR{last}" for t in tabs]})
    sh.batch_update({"requests": [
        {"updateCells": {
            "range": {"sheetId": t.id, "startRowIndex": 2, "endRowIndex": last,
                      "startColumnIndex": 0, "endColumnIndex": 96},
            "fields": "userEnteredFormat",
        }}
        for t in tabs
    ]})
    if filters:
        sh.batch_update({"requests": [{"setBasicFilter": {"filter": bf}}
                                      for bf in filters.values()]})
    return len(tabs)


def set_current_week_dates(ws, monday: "dt.date") -> int:
    """Set the current-week row-1 date labels to the week starting `monday`:
    the C1 weekly banner + each day-block cell ('Mon m/d' … 'Sun m/d').

    WHY: the report READS row 1 to map day columns but never WROTE it, so a
    rollover left last week's dates in the current block and the labels drifted
    a week behind (Megan 2026-06-15). Call this right after the week shifts so
    the fresh current week shows the correct dates. Robust: it finds whichever
    cells already hold a weekday/banner label and rewrites only those (no
    hardcoded columns). Idempotent; returns the count of cells set."""
    import re as _re
    from gspread.utils import rowcol_to_a1
    by_wd = {(monday + dt.timedelta(days=i)).strftime("%a"):
             monday + dt.timedelta(days=i) for i in range(7)}
    md = lambda d: f"{d.month}/{d.day}"
    banner = (f"Weekly Total Mon {md(by_wd['Mon'])} - Sun {md(by_wd['Sun'])} "
              "(Weekend hours excluded from averages)")
    row1 = ws.get("A1:CR1")[0]
    updates = []
    for c, v in enumerate(row1, 1):
        s = str(v).strip()
        if not s:
            continue
        m = _re.match(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b", s)
        if m:
            updates.append({"range": rowcol_to_a1(1, c),
                            "values": [[f"{m.group(1)} {md(by_wd[m.group(1)])}"]]})
        elif "Weekly Total" in s:
            updates.append({"range": rowcol_to_a1(1, c), "values": [[banner]]})
    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    return len(updates)


def set_all_current_week_dates(sh, monday: "dt.date", logfn=print) -> int:
    """Apply set_current_week_dates to every owner tab. Per-tab try/except +
    light pacing so one tab can't abort the relabel. Returns tabs set."""
    import time
    tabs = [t for t in sh.worksheets() if t.title not in NON_OWNER_TABS]
    n = 0
    for ws in tabs:
        try:
            set_current_week_dates(ws, monday)
            n += 1
            time.sleep(0.3)
        except Exception as e:
            logfn(f"  {ws.title}: date relabel failed — {type(e).__name__}")
    return n


def _shift_already_done(sh, monday: "dt.date") -> bool:
    """True if the top chart already shows the week starting `monday` — i.e.
    the Tuesday shift already ran today. Guards against a SECOND shift nesting
    the blocks (the double-rollover that corrupted the sheet 2026-06-15).
    Checks one owner tab's Monday day-cell (M1)."""
    try:
        tabs = [t for t in sh.worksheets() if t.title not in NON_OWNER_TABS]
        if not tabs:
            return False
        v = (tabs[0].acell("M1").value or "").strip()
        return v == f"Mon {monday.month}/{monday.day}"
    except Exception:
        return False


LAST_WEEK_LABEL = "LAST WEEK"
# FIXED layout (Megan 2026-05-31, sized for 100 reps — the unused headroom is
# hidden anyway, so a big allowance costs nothing visually): header r2 + up to
# 100 rep rows (3-102) + OFFICE TOTALS + 4 summary all land at/above row 107,
# so the LAST WEEK separator pins at row 110 with headroom. The current-week
# wipe is scoped to stop above row 110 so the frozen block survives.
LAST_WEEK_LABEL_ROW = 110       # 1-based
LAST_WEEK_HEADER_ROW = 111      # frozen block's first row
CURRENT_ZONE_LAST_ROW = 109     # current week occupies rows 3..109
COND_LASTWEEK_END_ROW = 230     # conditional coloring for the frozen block ends here


def _find_label_row(col_b, label: str):
    """1-based row of `label` in column-B values, or None."""
    up = label.strip().upper()
    for i, v in enumerate(col_b, start=1):
        if isinstance(v, str) and v.strip().upper() == up:
            return i
    return None


# Frozen block layout (row 1-based): 110 = LAST WEEK label, 111 = dates (copy of
# row 1), 112 = column header (copy of row 2), 113+ = frozen reps/totals/summary.
LAST_WEEK_DATES_ROW = 111
LAST_WEEK_COLHDR_ROW = 112
LAST_WEEK_DATA_ROW = 113


def _normalize_lastweek_conditional(ws) -> None:
    """Re-range every conditional-format rule so the day-block/weekly colors
    cover the current-week zone (rows 3..109) AND the frozen DATA (rows
    113..230) but SKIP the LAST WEEK label (110) + the frozen date row (111) +
    the frozen column-header row (112) — so the label row is white past C and
    the two frozen header rows keep their own styling. Preserves each rule's
    column spans + format; only the ROW spans change. Run after the snapshot
    copy (which otherwise leaves the rules auto-extended/split)."""
    meta = ws.spreadsheet.fetch_sheet_metadata(
        {"ranges": [ws.title], "fields": "sheets.conditionalFormats"})
    cfs = meta["sheets"][0].get("conditionalFormats", [])
    requests = []
    for idx, cf in enumerate(cfs):
        # Unique column spans this rule paints (dedupe across its sub-ranges).
        col_spans = sorted({(r.get("startColumnIndex", 0), r.get("endColumnIndex", 96))
                            for r in cf.get("ranges", [])})
        new_ranges = []
        for c0, c1 in col_spans:
            new_ranges.append({"sheetId": ws.id, "startRowIndex": 2,
                               "endRowIndex": CURRENT_ZONE_LAST_ROW,
                               "startColumnIndex": c0, "endColumnIndex": c1})
            new_ranges.append({"sheetId": ws.id, "startRowIndex": LAST_WEEK_DATA_ROW - 1,
                               "endRowIndex": COND_LASTWEEK_END_ROW,
                               "startColumnIndex": c0, "endColumnIndex": c1})
        rule = {k: v for k, v in cf.items() if k != "ranges"}
        rule["ranges"] = new_ranges
        requests.append({"updateConditionalFormatRule":
                         {"sheetId": ws.id, "index": idx, "rule": rule}})
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})


def rollover_to_last_week(sh, only=None, logfn=print) -> int:
    """Freeze each tab's current-week block (reps + OFFICE TOTALS + summary)
    into a fixed 'LAST WEEK' block at LAST_WEEK_LABEL_ROW (110), so last week's data 'stays
    there' when the new week is wiped (Raf, 2026-05-31). The snapshot is
    static VALUES (formulas frozen to numbers) + the formatting, so it
    survives the current-week wipe. Current + last week only — the new
    snapshot overwrites the prior LAST WEEK block.

    Returns the count of tabs rolled over. Run on Monday BEFORE the (scoped)
    current-week clear."""
    tabs = [t for t in sh.worksheets() if t.title not in NON_OWNER_TABS]
    if only:
        tabs = [t for t in tabs if t.title in only]
    n = 0
    for ws in tabs:
        col_b = ws.col_values(2)
        end_row = _find_label_row(col_b, "% ON BOARD")   # current block's last row
        if not end_row:
            logfn(f"  {ws.title}: no summary block — skipping rollover")
            continue
        sid = ws.id
        # Snapshot includes the date header (row 1) so the frozen block carries
        # last week's dates. Source rows 1..end_row → dest from LAST_WEEK_DATES_ROW (111).
        block_rows = end_row                             # rows 1..end_row inclusive
        frozen_bottom = LAST_WEEK_DATES_ROW - 1 + block_rows   # last frozen row
        cur_office_totals = end_row - 4                  # OFFICE TOTALS in current block
        frozen_rep_start = LAST_WEEK_DATA_ROW            # 113
        frozen_rep_end = LAST_WEEK_DATES_ROW + (cur_office_totals - 1) - 1  # last frozen rep
        THICK = {"style": "SOLID_THICK", "color": {"red": 0, "green": 0, "blue": 0}}
        WHITE = {"red": 1, "green": 1, "blue": 1}
        # Wipe everything below the current block (headroom + old frozen block)
        # first — values + format — so re-running at a new position can't leave
        # an old block orphaned in the (hidden) headroom.
        clear_from = end_row + 1
        ws.spreadsheet.values_batch_clear(
            body={"ranges": [f"{_q(ws.title)}!A{clear_from}:CR400"]})
        # The tab carries a basic FILTER (the report filters inactive reps out
        # of view). copyPaste skips filtered rows then tiles to fill the dest —
        # which duplicated the whole block on a filtered tab (Rafael) — and
        # sortRange/copyPaste even error on a filtered range. Capture + clear
        # the filter for the snapshot, restore it after.
        bf = ws.spreadsheet.fetch_sheet_metadata(
            {"ranges": [ws.title], "fields": "sheets.basicFilter"}
        )["sheets"][0].get("basicFilter")
        if bf:
            ws.spreadsheet.batch_update({"requests": [{"clearBasicFilter": {"sheetId": sid}}]})
        # Snapshot VALUES by read+write (row-exact; UNFORMATTED freezes formulas
        # to their computed values).
        cur_vals = ws.get(f"A1:CR{end_row}", value_render_option="UNFORMATTED_VALUE")
        cur_vals = [(r + [""] * (96 - len(r)))[:96] for r in cur_vals]
        ws.update(cur_vals, f"A{LAST_WEEK_DATES_ROW}", value_input_option="RAW")
        src = {"sheetId": sid, "startRowIndex": 0, "endRowIndex": end_row,
               "startColumnIndex": 0, "endColumnIndex": 96}
        dst = {"sheetId": sid, "startRowIndex": LAST_WEEK_DATES_ROW - 1,
               "endRowIndex": LAST_WEEK_DATES_ROW - 1 + block_rows,
               "startColumnIndex": 0, "endColumnIndex": 96}
        requests = [
            {"unmergeCells": {
                "range": {"sheetId": sid, "startRowIndex": clear_from - 1,
                          "endRowIndex": 400, "startColumnIndex": 0, "endColumnIndex": 96}}},
            {"updateCells": {
                "range": {"sheetId": sid, "startRowIndex": clear_from - 1,
                          "endRowIndex": 400, "startColumnIndex": 0, "endColumnIndex": 96},
                "fields": "userEnteredFormat"}},
            # With the filter cleared, the bulk format paste is row-exact (1:1).
            {"copyPaste": {"source": src, "destination": dst, "pasteType": "PASTE_FORMAT"}},
            # Sort the frozen reps by SUM Total Apps (col C) highest→lowest.
            {"sortRange": {
                "range": {"sheetId": sid, "startRowIndex": frozen_rep_start - 1,
                          "endRowIndex": frozen_rep_end, "startColumnIndex": 0, "endColumnIndex": 96},
                "sortSpecs": [{"dimensionIndex": 2, "sortOrder": "DESCENDING"}]}},
            # Unmerge the label cells (A–B) — if row 1 carried an A1:B1 access/
            # error banner, the format paste copies that merge here and would
            # swallow the label write (Rafael). Then clear A + write the label
            # in B.
            {"unmergeCells": {
                "range": {"sheetId": sid, "startRowIndex": LAST_WEEK_DATES_ROW - 1,
                          "endRowIndex": LAST_WEEK_DATES_ROW, "startColumnIndex": 0, "endColumnIndex": 2}}},
            # 'LAST WEEK' yellow label in B (A cleared of any copied banner) —
            # KEEPS the weekly date-range banner (C, with the weekend-hours note)
            # + the day-block dates to its right (Megan's template).
            {"updateCells": {
                "range": {"sheetId": sid, "startRowIndex": LAST_WEEK_DATES_ROW - 1,
                          "endRowIndex": LAST_WEEK_DATES_ROW, "startColumnIndex": 0, "endColumnIndex": 2},
                "rows": [{"values": [
                    {"userEnteredValue": {"stringValue": ""}},
                    {"userEnteredValue": {"stringValue": LAST_WEEK_LABEL},
                     "userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 11}}},
                ]}],
                "fields": "userEnteredValue,userEnteredFormat.textFormat"}},
            {"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": LAST_WEEK_DATES_ROW - 1,
                          "endRowIndex": LAST_WEEK_DATES_ROW, "startColumnIndex": 0, "endColumnIndex": 2},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 1, "blue": 0}}},
                "fields": "userEnteredFormat.backgroundColor"}},
            # Bold border box around the whole frozen block (Megan's template).
            {"updateBorders": {
                "range": {"sheetId": sid, "startRowIndex": LAST_WEEK_DATES_ROW - 1,
                          "endRowIndex": frozen_bottom, "startColumnIndex": 0, "endColumnIndex": 96},
                "top": THICK, "bottom": THICK, "left": THICK, "right": THICK}},
            # Collapse the headroom: current block + 1 spacer visible, the
            # frozen block visible.
            {"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 2, "endIndex": end_row + 1},
                "properties": {"hiddenByUser": False}, "fields": "hiddenByUser"}},
            {"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "ROWS",
                          "startIndex": LAST_WEEK_LABEL_ROW - 1, "endIndex": frozen_bottom + 2},
                "properties": {"hiddenByUser": False}, "fields": "hiddenByUser"}},
        ]
        # Hide the unused headroom ONLY if there is any — a near-50-rep office
        # (e.g. Rafael, 52 reps) fills the zone to row 59 with no gap, and an
        # empty hide range is a 400 error.
        if end_row + 1 < LAST_WEEK_LABEL_ROW - 1:
            requests.append({"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "ROWS",
                          "startIndex": end_row + 1, "endIndex": LAST_WEEK_LABEL_ROW - 1},
                "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})
        ws.spreadsheet.batch_update({"requests": requests})
        # Re-sequence the frozen # (col A): the snapshot copied the current
        # block's computed numbers and the sortRange above scrambles those
        # static values. Number the frozen reps 1..N in their sorted order
        # (the current block's # is a =ROW()-2 formula that self-renumbers;
        # the frozen block's is static, so it must be redone here).
        froz_b = ws.col_values(2)
        seq, k = [], 0
        for r in range(frozen_rep_start, frozen_rep_end + 1):
            nm = froz_b[r - 1] if r - 1 < len(froz_b) else ""
            if nm and nm.strip():
                k += 1
                seq.append([k])
            else:
                seq.append([""])
        if seq:
            ws.update(seq, f"A{frozen_rep_start}", value_input_option="RAW")
        # Normalize conditional ranges LAST (the format paste auto-splits them).
        _normalize_lastweek_conditional(ws)
        # Restore the basic filter we cleared for the snapshot.
        if bf:
            ws.spreadsheet.batch_update({"requests": [{"setBasicFilter": {"filter": bf}}]})
        n += 1
        logfn(f"  {ws.title}: froze rows 1-{end_row} → LAST WEEK (dates r{LAST_WEEK_DATES_ROW}, "
              f"sorted by app sum), border + dates")
    return n


def rollover_all_tabs(sh, logfn=print) -> int:
    """Freeze EVERY owner tab's last week, one tab at a time with 429 backoff +
    pacing. Doing it per-tab means a rate-limit or one bad tab can't abort the
    whole freeze — which, on Monday BEFORE the scoped wipe, would otherwise
    leave un-frozen tabs and lose their last week. Returns tabs frozen."""
    import time
    titles = [t.title for t in sh.worksheets() if t.title not in NON_OWNER_TABS]
    n = 0
    for title in titles:
        for attempt in range(5):
            try:
                n += rollover_to_last_week(sh, only=[title], logfn=logfn)
                break
            except Exception as e:
                if "429" in str(e) and attempt < 4:
                    time.sleep(30)
                    continue
                logfn(f"  {title}: rollover ERROR (skipped) — "
                      f"{type(e).__name__}: {str(e)[:80]}")
                break
        time.sleep(1)
    return n


def collapse_headroom(sh, only=None, logfn=print) -> int:
    """Re-hide the unused rows between the current-week summary (3 spacers) and
    the LAST WEEK block, so each tab reads current → 3 rows → LAST WEEK
    with the headroom collapsed. Runs at the END of every run (the day's fill
    moves the summary row). Per-tab 429 backoff + pacing so a rate-limit
    doesn't abort the whole pass. No-op on tabs without a frozen block."""
    import time
    tabs = [t for t in sh.worksheets() if t.title not in NON_OWNER_TABS]
    if only:
        tabs = [t for t in tabs if t.title in only]
    n = 0
    for ws in tabs:
        for attempt in range(4):
            try:
                col_b = ws.col_values(2)
                end_row = _find_label_row(col_b, "% ON BOARD")
                if not end_row:
                    break
                if not any(isinstance(v, str) and v.strip().upper() == LAST_WEEK_LABEL
                           for v in col_b[LAST_WEEK_LABEL_ROW - 1:]):
                    break   # no frozen block below → nothing to collapse
                sid = ws.id
                # Anchor on the ACTUAL LAST WEEK row (not the fixed constant)
                # so the gap survives layout drift.
                lw_row = next((i for i, v in enumerate(col_b, 1)
                               if isinstance(v, str) and v.strip().upper() == LAST_WEEK_LABEL), None)
                if not lw_row:
                    break
                # Leave exactly 3 visible spacer rows between the current
                # summary and the LAST WEEK block; hide the rest of the
                # headroom (Megan 2026-06-16).
                reqs = [
                    {"updateDimensionProperties": {
                        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 2, "endIndex": end_row + 3},
                        "properties": {"hiddenByUser": False}, "fields": "hiddenByUser"}},
                    {"updateDimensionProperties": {
                        "range": {"sheetId": sid, "dimension": "ROWS",
                                  "startIndex": lw_row - 1, "endIndex": 240},
                        "properties": {"hiddenByUser": False}, "fields": "hiddenByUser"}},
                ]
                if end_row + 3 < lw_row - 1:
                    reqs.append({"updateDimensionProperties": {
                        "range": {"sheetId": sid, "dimension": "ROWS",
                                  "startIndex": end_row + 3, "endIndex": lw_row - 1},
                        "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})
                ws.spreadsheet.batch_update({"requests": reqs})
                n += 1
                break
            except Exception as e:
                if "429" in str(e) and attempt < 3:
                    time.sleep(20)
                    continue
                logfn(f"  {ws.title}: collapse skipped — {type(e).__name__}")
                break
        time.sleep(0.5)
    return n


# ----------------------------------------------------------------------
# No-access banner — visible warning ON the tab itself
# ----------------------------------------------------------------------
# Light red bg + dark red bold text — same palette as the financial
# "Not Found In Email" marker so the visual language stays consistent.
_BANNER_BG = {"red": 1.0, "green": 0.78, "blue": 0.76}
_BANNER_FG = {"red": 0.78, "green": 0.15, "blue": 0.12}


def _banner_text_for(status: str) -> str:
    """Pick the right actionable banner text from a per-owner failure
    status string written to scrape_results.json by run_all_owners.

    Each status maps to ONE action a viewer can take — Megan/Raf
    shouldn't have to decode raw status strings like 'exception:
    TimeoutError:...'; the log has those for debugging."""
    s = (status or "").lower()
    # OV's "Office Access" table only lists offices the current login HAS
    # access to. If a name isn't in the table, the user doesn't have
    # access — confirmed by Megan 2026-05-31 (Melik El Jaiez, Salik Mallick
    # are genuine access gaps). Same banner as an explicit impersonate
    # denial; the fix is the same (request OV access). The "all tabs showed
    # this" complaint was a stale-banner bug (Phase-3 failure skipped the
    # clear), now fixed — not a wording problem.
    if "name not found" in s or "no ov access" in s or "impersonate denied" in s:
        return "❌ NO OWNERVILLE ACCESS — request access"
    if "access request pending" in s or "request sent" in s:
        return "⏳ OWNERVILLE ACCESS REQUEST PENDING — waiting on approval"
    if "no impersonate button" in s or "office may be disabled" in s:
        return "❌ OFFICE DISABLED IN OWNERVILLE — check OV"
    if "ov page error" in s:
        return "❌ OWNERVILLE UI ERROR — retry later"
    if "couldn't reach office access" in s:
        return "❌ COULDN'T REACH OWNERVILLE — retry later"
    if s.startswith("exception:") or "timeout" in s:
        return "❌ OWNERVILLE PULL ERROR — retry later"
    # Legacy / unknown status (e.g. older "impersonate failed" before the
    # status string got more specific) — show a generic, still-actionable
    # message rather than a misleading one.
    return "❌ COULDN'T PULL FROM OWNERVILLE — check log"


def mark_no_access_tabs(sh, pending_results: dict) -> dict:
    """Stamp a per-failure banner on tabs whose OV scrape failed, and
    clear it from tabs that scraped OK.

    `pending_results` is `{tab_name: status_string}` — only entries where
    status != "ok" should be passed in (filtering happens at the call
    site). The banner text is chosen per-status by `_banner_text_for`
    so the viewer knows what to do (add alias vs request access vs retry).

    Banner lives at A1:B1 — those cells are empty by design (col C
    onward holds the merged weekly/per-day banners and is off-limits;
    row 2 holds the column headers). Merged into a single visible cell
    with light-red bg + dark-red bold text. Idempotent."""
    tabs = [t for t in sh.worksheets() if t.title not in NON_OWNER_TABS]
    if not tabs:
        return {"marked": 0, "cleared": 0}
    requests = []
    marked = cleared = 0
    for t in tabs:
        status = pending_results.get(t.title)
        is_pending = bool(status)
        # Unmerge first — safe to do on a non-merged range (Sheets ignores).
        # Lets us re-write A1:B1 cleanly in either branch.
        requests.append({"unmergeCells": {
            "range": {"sheetId": t.id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": 2},
        }})
        if is_pending:
            requests.append({"mergeCells": {
                "range": {"sheetId": t.id, "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": 2},
                "mergeType": "MERGE_ALL",
            }})
            requests.append({"updateCells": {
                "range": {"sheetId": t.id, "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": 1},
                "fields": "userEnteredValue,userEnteredFormat",
                "rows": [{"values": [{
                    "userEnteredValue": {"stringValue": _banner_text_for(status)},
                    "userEnteredFormat": {
                        "backgroundColor": _BANNER_BG,
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                        "textFormat": {
                            "foregroundColor": _BANNER_FG,
                            "bold": True, "fontSize": 11,
                        },
                        "wrapStrategy": "WRAP",
                    },
                }]}],
            }})
            marked += 1
        else:
            # Wipe the banner — blank the cells + clear formatting
            requests.append({"updateCells": {
                "range": {"sheetId": t.id, "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": 2},
                "fields": "userEnteredValue,userEnteredFormat",
                "rows": [{"values": [
                    {"userEnteredValue": {"stringValue": ""}, "userEnteredFormat": {}},
                    {"userEnteredValue": {"stringValue": ""}, "userEnteredFormat": {}},
                ]}],
            }})
            cleared += 1
    sh.batch_update({"requests": requests})
    return {"marked": marked, "cleared": cleared}


def _refresh_pending_banners(sh, say) -> None:
    """Stamp/clear the per-owner OV-access banners from Phase-2 scrape
    results. Banners depend on ownerville access (Phase 2) only, so this is
    safe to run before Phase 3 — and MUST, so a Phase-3 failure can't leave
    a good scrape's tabs showing stale 'NO OWNERVILLE ACCESS' banners."""
    try:
        pending_results: dict = {}
        if SCRAPE_RESULTS.exists():
            try:
                data = json.loads(SCRAPE_RESULTS.read_text())
                pending_results = {o: s for o, s in data.get("results", {}).items()
                                   if s != "ok" and o not in NON_OWNER_TABS}
            except Exception:
                pending_results = {}
        counts = mark_no_access_tabs(sh, pending_results)
        say(f"  banner marked on {counts['marked']} tab(s), "
            f"cleared on {counts['cleared']} tab(s)")
    except Exception as e:
        say(f"  banner refresh failed (non-fatal): {e}")


# ----------------------------------------------------------------------
# Tab colors
# ----------------------------------------------------------------------
def refresh_tab_colors(sh) -> dict:
    """Recolor owner tabs:
      - amber      = owner not scraped OK this run (pending OV access)
      - light blue = tab has Tableau-only reps (a sale but no OV activity)
      - no color   = fully matched

    Pending status is read from focus_office_scrape_results.json (written
    by run_all_owners). Self-maintaining: when an owner's access lands and
    they scrape OK, they drop out of the pending set automatically."""
    pending: set[str] = set()
    if SCRAPE_RESULTS.exists():
        try:
            data = json.loads(SCRAPE_RESULTS.read_text())
            pending = {o for o, s in data.get("results", {}).items() if s != "ok"}
        except Exception:
            pending = set()
    pending -= NON_OWNER_TABS

    owner_tabs = [ws for ws in sh.worksheets() if ws.title not in NON_OWNER_TABS]
    # One batched read of column B for every non-pending owner tab. Pending
    # tabs go amber without needing their contents, so they're not read.
    to_read = [ws for ws in owner_tabs if ws.title not in pending]
    col_b: dict[str, list[str]] = {}
    if to_read:
        resp = sh.values_batch_get([f"{_q(ws.title)}!B:B" for ws in to_read])
        for ws, vr in zip(to_read, resp.get("valueRanges", [])):
            col_b[ws.title] = [(row[0] if row else "")
                               for row in vr.get("values", [])]

    counts = {"amber": 0, "light_blue": 0, "none": 0}
    requests = []
    for ws in owner_tabs:
        if ws.title in pending:
            requests.append({"updateSheetProperties": {
                "properties": {"sheetId": ws.id, "tabColor": AMBER},
                "fields": "tabColor",
            }})
            counts["amber"] += 1
            continue
        has_tableau_only = any(
            TABLEAU_ONLY_MARK in (v or "") for v in col_b.get(ws.title, [])
        )
        if has_tableau_only:
            requests.append({"updateSheetProperties": {
                "properties": {"sheetId": ws.id, "tabColor": LIGHT_BLUE},
                "fields": "tabColor",
            }})
            counts["light_blue"] += 1
        else:
            requests.append({"updateSheetProperties": {
                "properties": {"sheetId": ws.id, "tabColorStyle": {"rgbColor": {}}},
                "fields": "tabColorStyle",
            }})
            counts["none"] += 1

    if requests:
        sh.batch_update({"requests": requests})
    return counts


# ----------------------------------------------------------------------
# Desktop notifications — cross-platform (macOS + Windows)
# ----------------------------------------------------------------------
_NOTIFY_TITLE = "Daily Rep Breakdown - ATT Program"
_IS_WINDOWS = sys.platform.startswith("win")
_IS_MAC = sys.platform == "darwin"


def _win_popup(message: str, *, failure: bool) -> None:
    """Show a Windows popup via a .NET MessageBox (built into Windows — no
    install needed). The script is base64-encoded and passed via
    -EncodedCommand so quotes/newlines in the message can't break it.
    Fire-and-forget (Popen) so the run never blocks on the popup."""
    icon = "Warning" if failure else "Information"
    safe = message.replace("'", "''")  # PowerShell single-quote escape
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "[System.Windows.Forms.MessageBox]::Show("
        f"'{safe}','{_NOTIFY_TITLE}','OK','{icon}') | Out-Null"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    subprocess.Popen(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
         "-EncodedCommand", encoded]
    )


def _notify_success(msg: str) -> None:
    try:
        if _IS_WINDOWS:
            _win_popup(msg, failure=False)
        elif _IS_MAC:
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{msg}" with title "{_NOTIFY_TITLE}"'],
                check=False, timeout=10,
            )
    except Exception:
        pass


def _notify_failure(headline: str, detail: str, log_file: str) -> None:
    try:
        if _IS_WINDOWS:
            _win_popup(f"{headline}\n\n{detail}\n\nLog: {log_file}",
                       failure=True)
        elif _IS_MAC:
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{headline} Tap for details." '
                 f'with title "{_NOTIFY_TITLE}" sound name "Sosumi"'],
                check=False, timeout=10,
            )
            dialog = (
                f'display dialog "{headline}\n\n{detail}\n\nLog: {log_file}" '
                f'buttons {{"OK"}} default button 1 with icon caution'
            )
            subprocess.run(["osascript", "-e", dialog], check=False, timeout=120)
    except Exception:
        pass


# ----------------------------------------------------------------------
# Phase runners (subprocess — each phase has its own CLI entrypoint)
# ----------------------------------------------------------------------
# Phase-level hard caps. A phase that exceeds these is killed (the scrape
# resumes from its checkpoint on the next run) so a single hung owner or a
# stuck Tableau load can never silently stall the whole report for an hour
# (Eve's run sat at 62 min before someone stopped it, 2026-05-31). Generous
# vs. the ~15 min normal total, so a legit slow Monday won't false-trip.
PHASE_TIMEOUT_EXIT = 124  # conventional "timed out" exit code
PHASE2_TIMEOUT_S = 60 * 60  # was 40 — a full 30-owner scrape (~1.5 min/owner of
# impersonation overhead, incl. the heavy master owner) runs ~48 min and got
# killed at owner 26 (Eve 2026-06-18). The checkpoint resumes a kill, but bump
# the cap so a normal full run completes without tripping it + filing a glitch.
PHASE3_TIMEOUT_S = 35 * 60  # was 20 — heavy days (big fills + Tableau retries) ran over (Megan 2026-06-07)

# Daily Rep BD report pull custom view (Phase 3 Tableau source) — surfaced as
# the "where to look" link in the Hub's failure-help callout.
_DAILY_RB_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                  "ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/"
                  "f081e40f-dd21-4a09-8981-c7cce17b5381/DailyRepBDreportpull")
_DAILY_RB_CARD_ID = "daily-rep-breakdown"


def _daily_manifest_fail(phase: str) -> None:
    """Write the standard failure manifest (why/fix/link/message) for the Daily
    Rep Breakdown card so the Hub shows what failed + how to fix it. Best-effort
    — never raises. `phase` is 'phase2' (ownerville scrape) or 'phase3'
    (Tableau pull)."""
    try:
        from automations.shared import run_manifest as _rm
        if phase == "phase2":
            _rm.write_manifest(
                _DAILY_RB_CARD_ID, failed=["Phase 2 — ownerville scrape"],
                retry_args=[], kind="phase",
                note="ownerville scrape (Phase 2) failed.",
                remediation=_rm.make_remediation(
                    reason="The ownerville scrape (Phase 2) didn't complete — it "
                           "timed out or the Chrome/ownerville session dropped.",
                    fix="Make sure Report Chrome is running and signed in to "
                        "ownerville, then Run Again — Phase 2 resumes from its "
                        "checkpoint, so finished owners aren't re-scraped.",
                    link="",
                    message="The Daily Rep Breakdown report failed at the "
                            "ownerville scrape step — the browser session likely "
                            "dropped. Re-running with Report Chrome signed in "
                            "should resume it."))
        else:  # phase3
            _rm.write_manifest(
                _DAILY_RB_CARD_ID, failed=["Phase 3 — Tableau pull"],
                retry_args=[], kind="phase",
                note="Tableau pull (Phase 3) failed.",
                remediation=_rm.make_remediation(
                    reason="The ownerville scrape finished, but the Tableau "
                           "sale-type pull (Phase 3) failed — usually a "
                           "transient Tableau load, or the 'Daily Rep BD report "
                           "pull' custom view changed.",
                    fix="Open the Daily Rep BD report pull view in Tableau, "
                        "confirm it loads, then Run Again — Phase 2 won't "
                        "re-scrape (only the Tableau step re-runs).",
                    link=_DAILY_RB_VIEW,
                    message="The Daily Rep Breakdown report failed at its "
                            "Tableau step (the scrape finished). Can someone "
                            "confirm the 'Daily Rep BD report pull' view loads? "
                            "A re-run usually clears a transient load."))
    except Exception:
        pass


def _daily_manifest_ok() -> None:
    """Finalize the manifest after a pipeline that didn't crash. NOT always
    'clean': any owner that couldn't be scraped (not in ownerville / no access)
    is surfaced as the manifest's failed list, so the run reads INCOMPLETE and
    the email lists exactly who was skipped — even though the pipeline itself
    'succeeded' (Megan 2026-06-25: "give a breakdown of what wasn't accessible
    even if the report was successful" — e.g. Melik El Jaiez isn't in OV).
    Fully clean only when every owner scraped OK. Best-effort."""
    try:
        from automations.shared import run_manifest as _rm
        bad: dict = {}
        if SCRAPE_RESULTS.exists():
            try:
                data = json.loads(SCRAPE_RESULTS.read_text())
                bad = {o: s for o, s in data.get("results", {}).items()
                       if s != "ok" and o not in NON_OWNER_TABS}
            except Exception:
                bad = {}
        if bad:
            owners = sorted(bad)
            detail = "; ".join(f"{o} ({bad[o]})" for o in owners)
            _rm.write_manifest(_DAILY_RB_CARD_ID, failed=owners, retry_args=[],
                               kind="owner",
                               note=f"{len(owners)} owner(s) not scraped — {detail}")
        else:
            _rm.mark_clean(_DAILY_RB_CARD_ID, kind="phase")
    except Exception:
        pass


def _kill_process_tree(proc: "subprocess.Popen") -> None:
    """Kill a subprocess AND its descendants (the patchright browser),
    cross-platform. Killing just the direct child leaves the browser holding
    the stdout pipe, so the parent's read never returns."""
    import os
    import signal as _signal
    pid = proc.pid
    if _IS_WINDOWS:
        # /T = whole tree, /F = force. taskkill is always present on Windows.
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=20)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return
    # POSIX: the child was started with start_new_session=True, so its PGID
    # == its PID; signal the whole group.
    try:
        os.killpg(os.getpgid(pid), _signal.SIGTERM)
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
        return
    except Exception:
        pass
    try:
        os.killpg(os.getpgid(pid), _signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _run_phase(module: str, extra_args: list[str], log_fh,
               timeout_s: int | None = None) -> int:
    """Run a pipeline module as a subprocess. Streams its output line by
    line to BOTH the run log file and this process's stdout — so the Hub,
    which captures daily.py's stdout, shows live per-owner progress (the
    scraper's "[i/N]" markers) instead of just the phase headline.

    If `timeout_s` is set, a watchdog kills the subprocess after that many
    seconds and we return PHASE_TIMEOUT_EXIT — never blocking forever.
    Returns the process exit code."""
    # -u (unbuffered) so the child's per-owner progress streams live instead
    # of sitting in a block buffer until the pipe fills — otherwise the Hub's
    # live log looks frozen on a perfectly healthy run, and a real stall gives
    # no clue where it stopped.
    cmd = [PYTHON, "-u", "-m", module, *extra_args]
    header = f"\n$ {' '.join(cmd)}\n"
    log_fh.write(header)
    log_fh.flush()
    print(header, end="", flush=True)
    # Start the child in its OWN process group/session so the watchdog can
    # kill the whole TREE — the scraper spawns a patchright browser as a
    # grandchild, and killing only the direct child leaves the browser alive
    # holding the stdout pipe open (the read below would block forever, so the
    # timeout wouldn't actually unstick us). Eve runs this on Windows, so the
    # tree-kill has to work there too (taskkill /T), not just on macOS.
    popen_kw = {}
    if _IS_WINDOWS:
        popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kw["start_new_session"] = True
    # stdin=DEVNULL: a phase must NEVER inherit the terminal's TTY. The owner
    # scraper falls back to an interactive input() when a tab name doesn't match
    # ownerville; spawned from a rebuild/orchestrator that still has a TTY, that
    # prompt would HANG the whole unattended run until the phase watchdog killed
    # it (Megan 2026-06-25: Melik El Jaiez stalled the 6/15 rebuild at owner
    # 19/28). Closed stdin → isatty() is False → it auto-skips + flags instead.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL,
                            text=True, bufsize=1, cwd=str(WORKSPACE), **popen_kw)
    timed_out = {"hit": False}
    timer = None
    if timeout_s:
        import threading

        def _kill_hung():
            timed_out["hit"] = True
            _kill_process_tree(proc)

        timer = threading.Timer(timeout_s, _kill_hung)
        timer.daemon = True
        timer.start()
    try:
        for line in proc.stdout:
            log_fh.write(line)
            log_fh.flush()
            print(line, end="", flush=True)
        proc.wait()
    finally:
        if timer:
            timer.cancel()
    if timed_out["hit"]:
        msg = (f"\n⏱ phase '{module}' exceeded {timeout_s // 60} min — killed. "
               f"Progress is checkpointed; click Run Again to resume.\n")
        log_fh.write(msg)
        log_fh.flush()
        print(msg, end="", flush=True)
        return PHASE_TIMEOUT_EXIT
    return proc.returncode


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> int:
    from automations.focus_office_att._ratelimit import install as _install_pacing
    _install_pacing()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    log_path = LOG_DIR / f"focus-office-daily-{stamp}.log"
    today = dt.date.today()
    # CADENCE (Megan 2026-06-15): the week SHIFTS on TUESDAY, not Monday.
    #   Monday    — the just-finished week is still the top chart; finalize it
    #               (scrape LAST week so Sunday's numbers settle). No rollover.
    #   Tuesday   — SHIFT: freeze last week into LAST WEEK, relabel the top to
    #               the new week, clear it, then scrape the new week (Mon+Tue).
    #   Wed–Sun   — incremental fill of the current week.
    dow = today.weekday()                       # 0=Mon .. 6=Sun
    is_shift_day = (dow == 1)                    # Tuesday
    this_monday = today - dt.timedelta(days=dow)
    last_monday = this_monday - dt.timedelta(days=7)
    mode = ("TUESDAY shift" if is_shift_day
            else "MONDAY finalize-last-week" if dow == 0
            else "mid-week incremental")

    with open(log_path, "w") as log:
        def say(m: str) -> None:
            print(m, flush=True)
            log.write(m + "\n")
            log.flush()

        say(f"=== Daily Rep Breakdown - ATT Program — {today.isoformat()} "
            f"({mode}) ===")

        # Phase 2 (run_all_owners) and Phase 3 (step7_download_tableau) both
        # self-auth via patchright now — no more debug-Chrome pre-flight gate.
        sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)

        # 2. Tuesday SHIFT (freeze last week + start new week), else future-day wipe
        if is_shift_day:
            # Idempotency guard: if the top chart already shows THIS week's
            # dates, the shift ran already today — skip it. Without this, a
            # second run re-rolls the (now-current) week on top of the frozen
            # block and NESTS them (the corruption of 2026-06-15).
            if _shift_already_done(sh, this_monday):
                say("Tuesday shift already done (top chart is this week) — skipping.")
            else:
                # Freeze the just-finished week into each tab's LAST WEEK block
                # BEFORE wiping the current week (Raf: keep last week's data).
                say("Tuesday: freezing last week into the LAST WEEK block...")
                try:
                    n = rollover_all_tabs(sh, logfn=say)
                    say(f"  froze last week on {n} tab(s)")
                except Exception as e:
                    say(f"  rollover failed (non-fatal): {e}")
                say("Tuesday: clearing the current week for the new week...")
                try:
                    n = wipe_all_owner_tabs(sh)
                    say(f"  cleared current week on {n} tab(s)")
                    try:
                        RUN_CHECKPOINT.unlink(missing_ok=True)
                    except Exception:
                        pass
                except Exception as e:
                    say(f"  wipe failed: {e}")
                    _notify_failure("Focus Office Tuesday wipe failed.",
                                    str(e), str(log_path))
                    return 1
                # Relabel row 1 to the NEW week — the report never wrote these,
                # which is why labels drifted (Megan 2026-06-15).
                say(f"Tuesday: setting new-week dates (Mon {this_monday.month}/"
                    f"{this_monday.day})...")
                try:
                    n = set_all_current_week_dates(sh, this_monday, logfn=say)
                    say(f"  set new-week dates on {n} tab(s)")
                except Exception as e:
                    say(f"  date relabel failed (non-fatal): {e}")
        else:
            # Tue-Sun: clear cells for days AFTER today so last week's
            # Wed-Sun stale data doesn't leak into this week (the column
            # headers roll over but cell values don't until something
            # writes them). Sunday no-ops.
            say("Clearing future-day blocks (post-today, this week)...")
            try:
                n = wipe_future_day_blocks(sh, today)
                say(f"  cleared future blocks on {n} tab(s)")
            except Exception as e:
                say(f"  future-day clear failed (non-fatal): {e}")

        # Collapse future-day column GROUPS so empty days are hidden
        # behind a +/- toggle the user can click to peek at them.
        # Idempotent — runs every day so collapse state tracks the date.
        say("Collapsing future-day column groups...")
        try:
            n = set_day_column_collapsed(sh, today)
            say(f"  collapse state set on {n} tab(s)")
        except Exception as e:
            say(f"  collapse set failed (non-fatal): {e}")

        # 3. Phase 2 — ownerville scrape (week depends on the cadence)
        say("Phase 2: ownerville scrape...")
        if is_shift_day:
            phase2_args = []                       # full scrape of the new week
        elif dow == 0:                             # Monday: finalize LAST week
            phase2_args = ["--week-start", last_monday.isoformat()]
        else:                                      # Wed-Sun: incremental
            phase2_args = ["--daily-window"]
        rc2 = _run_phase("automations.focus_office_att.run_all_owners",
                         phase2_args, log, timeout_s=PHASE2_TIMEOUT_S)
        if rc2 == PHASE_TIMEOUT_EXIT:
            say(f"  Phase 2 TIMED OUT after {PHASE2_TIMEOUT_S // 60} min — "
                f"likely one owner hung the scrape.")
            _notify_failure(
                "Focus Office scrape (Phase 2) timed out.",
                f"The ownerville scrape ran past {PHASE2_TIMEOUT_S // 60} min "
                "and was stopped — usually one owner's page hung. Progress is "
                "checkpointed, so click Run Again to resume where it left off.",
                str(log_path))
            _daily_manifest_fail("phase2")
            return 1
        # run_all_owners exits non-zero when SOME owners were skipped — that's
        # expected (pending-access owners). A genuine failure = no results
        # file written.
        if not SCRAPE_RESULTS.exists():
            say("  Phase 2 crashed — no results file written.")
            _notify_failure("Focus Office scrape (Phase 2) crashed.",
                            "ownerville scrape didn't complete. "
                            "Chrome/ownerville session may have dropped.",
                            str(log_path))
            _daily_manifest_fail("phase2")
            return 1
        say(f"  Phase 2 done (exit {rc2}).")

        # Clear/stamp the OV-access banners NOW, from Phase-2 results. These
        # reflect ownerville access (Phase 2) — NOT the Tableau pull (Phase 3)
        # — so they must run before Phase 3 can return early. Otherwise a good
        # scrape whose Phase 3 fails leaves every tab showing a stale
        # "NO OWNERVILLE ACCESS" banner (Megan 2026-05-31).
        say("Stamping per-failure banners on pending tabs...")
        _refresh_pending_banners(sh, say)

        # 4. Phase 3 — Tableau download + fill (Monday finalizes LAST week, so
        # pull last week's Tableau to match; every other day uses the current
        # week, step7's default).
        say("Phase 3: Tableau auto-download (CSV) + Sheet fill...")
        phase3_args = ["--format", "csv", "--fill"]
        if dow == 0:
            phase3_args += ["--week-ending", (last_monday + dt.timedelta(days=6)).isoformat()]
        rc3 = _run_phase("automations.focus_office_att.step7_download_tableau",
                         phase3_args, log,
                         timeout_s=PHASE3_TIMEOUT_S)
        if rc3 == PHASE_TIMEOUT_EXIT:
            say(f"  Phase 3 TIMED OUT after {PHASE3_TIMEOUT_S // 60} min.")
            _notify_failure(
                "Focus Office Tableau pull (Phase 3) timed out.",
                "The ownerville scrape completed; only the Tableau sale-type "
                "pull hung. Click Run Again — Phase 2 won't re-scrape.",
                str(log_path))
            try:
                refresh_tab_colors(sh)
            except Exception:
                pass
            _daily_manifest_fail("phase3")
            return 1
        if rc3 != 0:
            say(f"  Phase 3 failed (exit {rc3}).")
            _notify_failure(
                "Focus Office Tableau pull (Phase 3) failed.",
                "ownerville scrape DID complete — only the Tableau sale-type "
                "data is missing. Usually a transient patchright/Tableau "
                "load issue — click Run Again.",
                str(log_path))
            # Phase 2 data is still good — colors still worth refreshing.
            try:
                refresh_tab_colors(sh)
            except Exception:
                pass
            _daily_manifest_fail("phase3")
            return 1
        say("  Phase 3 done.")

        # 5. Tab colors
        say("Refreshing tab colors...")
        try:
            counts = refresh_tab_colors(sh)
            say(f"  amber={counts['amber']} (pending access), "
                f"light blue={counts['light_blue']} (Tableau-only reps), "
                f"plain={counts['none']}")
        except Exception as e:
            say(f"  tab-color refresh failed (non-fatal): {e}")

        # Re-extend the LAST WEEK conditional shading. The per-owner design
        # pass (Phase 2/3) runs reset_conditional_formatting, which re-ranges
        # the column shading to the CURRENT zone only — leaving the frozen
        # block unshaded (the white-frozen-block bug, 2026-06-16). This must
        # be the LAST conditional op of the run.
        say("Re-extending LAST WEEK conditional shading...")
        import time as _t
        _nc = 0
        for ws in sh.worksheets():
            if ws.title in NON_OWNER_TABS:
                continue
            for _att in range(3):
                try:
                    _normalize_lastweek_conditional(ws)
                    _nc += 1
                    break
                except Exception as e:
                    if "429" in str(e) and _att < 2:
                        _t.sleep(20)
                        continue
                    say(f"  {ws.title}: shading re-extend skipped — {type(e).__name__}")
                    break
            _t.sleep(0.4)
        say(f"  re-extended on {_nc} tab(s)")

        # Re-collapse the headroom now the new fill set the rep count / summary
        # row, so each tab reads current → spacer → LAST WEEK cleanly.
        say("Collapsing LAST WEEK headroom...")
        try:
            n = collapse_headroom(sh, logfn=say)
            say(f"  collapsed on {n} tab(s)")
        except Exception as e:
            say(f"  headroom collapse failed (non-fatal): {e}")

        # (Banners already refreshed right after Phase 2 — see above.)
        say("=== DONE ===")
        # Pipeline finished cleanly — clear the Phase-2 resume checkpoint
        # so the next run starts fresh instead of resuming.
        try:
            RUN_CHECKPOINT.unlink(missing_ok=True)
        except Exception:
            pass

    _notify_success(
        f"{'Tuesday shift' if is_shift_day else 'Daily'} run complete — "
        f"all 30 tabs refreshed.")
    _daily_manifest_ok()   # clear any prior failure manifest
    return 0


if __name__ == "__main__":
    sys.exit(main())
