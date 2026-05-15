"""Re-color the Focus Office Template using CONDITIONAL FORMATTING so
colors only appear on rows that have a rep name in col A. As reps get
added or removed, the formatting auto-adjusts — no need to know upfront
how many reps each owner has.

Palette:
  - Rep Name col (A) → bold text on pale-gray rail
  - Weekly Total Apps col (B) → warm gold + bold (the headline)
  - Daily Total Apps cols → light cream + bold
  - Breakdown cols (collapsible) → pale gray ('these are the details')
  - Headers (rows 1-2) stay deep navy / pale blue (already applied)
  - Frozen: rows 1-2 + col 1

Run:
    .venv/bin/python -m automations.focus_office_att.recolor_template
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from automations.recruiting_report import fill as _fill

DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"
TEMPLATE_TAB = "Template"

DAY_COLUMNS = [
    # (day, total_apps_col, breakdown_group_start, breakdown_group_end)
    # All cols shifted +1 vs the original layout when the leading '#' col
    # was added. Mon's Total Apps lives at col M (13), not L (12); Sun's
    # New Lines lives at CR (96), not CQ (95).
    ("Mon", 13, 14, 24),
    ("Tue", 25, 26, 36),
    ("Wed", 37, 38, 48),
    ("Thu", 49, 50, 60),
    ("Fri", 61, 62, 72),
    ("Sat", 73, 74, 84),
    ("Sun", 85, 86, 96),
]
WEEKLY_TOTAL_APPS_COL = 2
WEEKLY_TOTAL_BREAKDOWN_START = 3
WEEKLY_TOTAL_BREAKDOWN_END = 12   # was 11; col L (SUM New Lines) needs pale-gray too

# Last data col across the full sheet (Sun's New Lines = col CR / 96).
# Used so the OFFICE TOTALS gold rule paints the whole row, not just the
# Weekly Total block.
LAST_DATA_COL = 96
# Col I (1-based 9) = SUM New INT — Raf wants ≥6 green / ≤5 red on this
# col for at-a-glance quota tracking.
SUM_NEW_INT_COL = 9

WHITE         = {"red": 1.00, "green": 1.00, "blue": 1.00}
PALE_GRAY     = {"red": 0.97, "green": 0.97, "blue": 0.98}
PALE_BLUE     = {"red": 0.85, "green": 0.91, "blue": 0.97}   # alt day-block tint
PALE_LAVENDER = {"red": 0.92, "green": 0.88, "blue": 0.96}   # weekly block tint
WARM_GOLD     = {"red": 0.95, "green": 0.78, "blue": 0.36}
LIGHT_CREAM   = {"red": 1.00, "green": 0.96, "blue": 0.86}
REP_NAME_BG   = {"red": 0.94, "green": 0.95, "blue": 0.97}
LIGHT_GREEN   = {"red": 0.85, "green": 0.94, "blue": 0.83}   # ≥6 INTs
LIGHT_RED     = {"red": 0.96, "green": 0.80, "blue": 0.80}   # ≤5 INTs
DEEP_NAVY     = {"red": 0.13, "green": 0.20, "blue": 0.35}   # OFFICE TOTALS bg
WHITE_TEXT    = {"red": 1.00, "green": 1.00, "blue": 1.00}   # OFFICE TOTALS text

# How many rows to apply the conditional rules across. 100 covers
# any realistic rep count per owner; conditional rules only paint
# rows where col A is populated, so empty rows stay clean.
COND_TOP_ROW = 3
COND_BOT_ROW = 100


def _setup_logging() -> logging.Logger:
    import datetime as dt
    log_dir = Path(__file__).resolve().parent.parent.parent / "output" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"focus-office-att-{dt.date.today().isoformat()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
        force=True,
    )
    return logging.getLogger("focus-office-att-recolor")


def _cf_rule(sheet_id: int, start_col: int, end_col: int,
             bg: dict, bold: bool = False,
             condition_formula: str | None = None,
             text_color: dict | None = None,
             font_size: int | None = None) -> dict:
    """Conditional formatting rule: paint cells in [start_col, end_col)
    based on condition_formula (defaults to '$B<>""' — paint rep rows).

    Checks col B rather than col A because col A has a formula that
    auto-numbers rows (=IF($B<>"",ROW()-2,"")) — the formula's value is
    "" when there's no rep, but some Sheets conditional-formatting paths
    treat formula-empty differently from truly-empty cells. Anchoring on
    col B (the actual rep name) is unambiguous."""
    fmt = {"backgroundColor": bg}
    text_format: dict = {}
    if bold:
        text_format["bold"] = True
    if text_color is not None:
        text_format["foregroundColor"] = text_color
    if font_size is not None:
        text_format["fontSize"] = font_size
    if text_format:
        fmt["textFormat"] = text_format
    if condition_formula is None:
        condition_formula = f"=$B{COND_TOP_ROW}<>\"\""
    return {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [{
                    "sheetId": sheet_id,
                    "startRowIndex": COND_TOP_ROW - 1,
                    "endRowIndex": COND_BOT_ROW,
                    "startColumnIndex": start_col - 1,
                    "endColumnIndex": end_col,
                }],
                "booleanRule": {
                    "condition": {
                        "type": "CUSTOM_FORMULA",
                        "values": [{"userEnteredValue": condition_formula}],
                    },
                    "format": fmt,
                },
            },
            "index": 0,
        },
    }


def build_visual_rule_requests(sheet_id: int) -> list[dict]:
    """The conditional-formatting rules that paint the Focus Office tabs
    (pale gray / warm gold / light cream). NONE of these are green or
    red — those colors live in older manually-added rules that the
    pipeline wipes via clear_conditional_formatting.

    Returns a list of addConditionalFormatRule requests, callable for
    any owner tab — not just Template. Used by both this script (for
    Template) and the per-owner pipeline (post-fill, after clearing).
    """
    requests: list[dict] = []
    # Rep Name col (A) — bold + pale-gray rail
    requests.append(_cf_rule(sheet_id, 1, 1, REP_NAME_BG, bold=True))
    # Weekly Total Apps col — gold + bold
    requests.append(_cf_rule(sheet_id, WEEKLY_TOTAL_APPS_COL, WEEKLY_TOTAL_APPS_COL,
                             WARM_GOLD, bold=True))
    # Weekly Total block:
    #   - SUM Total Apps (col C) = LIGHT_CREAM bold, mirroring the
    #     per-day Total Apps headline pattern.
    #   - Breakdown cols (D..L) = PALE_LAVENDER, the weekly block's own
    #     distinct tint so it doesn't blur into day blocks.
    requests.append(_cf_rule(sheet_id, 3, 3, LIGHT_CREAM, bold=True))
    requests.append(_cf_rule(sheet_id, 4, WEEKLY_TOTAL_BREAKDOWN_END,
                             PALE_LAVENDER))
    # Each day's Total Apps + breakdown. Breakdown blocks alternate
    # between PALE_GRAY (Mon/Wed/Fri/Sun) and PALE_BLUE (Tue/Thu/Sat) so
    # adjacent day-blocks read as their own zebra stripes — Raf needs to
    # tell day boundaries apart at a glance. Total Apps cols stay
    # LIGHT_CREAM uniformly to mark the start of every day.
    DAY_BREAKDOWN_TINTS = [PALE_GRAY, PALE_BLUE]
    for i, (_short, ta_col, gs, ge) in enumerate(DAY_COLUMNS):
        requests.append(_cf_rule(sheet_id, ta_col, ta_col, LIGHT_CREAM, bold=True))
        requests.append(_cf_rule(sheet_id, gs, ge, DAY_BREAKDOWN_TINTS[i % 2]))
    # SUM New INT (col I) — green if rep hit ≥6 INTs this week, red if
    # ≤5. Per Raf: at-a-glance quota tracking. $B<>"" condition skips
    # OFFICE TOTALS row (which has empty col B), so the totals cell stays
    # gold via the rule below. Added BEFORE the OFFICE TOTALS gold rule
    # so gold lands at higher priority (index 0) and wins the totals row.
    requests.append(_cf_rule(
        sheet_id, SUM_NEW_INT_COL, SUM_NEW_INT_COL, LIGHT_GREEN, bold=True,
        condition_formula=f'=AND($B{COND_TOP_ROW}<>"", I{COND_TOP_ROW}>=6)',
    ))
    requests.append(_cf_rule(
        sheet_id, SUM_NEW_INT_COL, SUM_NEW_INT_COL, LIGHT_RED, bold=True,
        condition_formula=f'=AND($B{COND_TOP_ROW}<>"", I{COND_TOP_ROW}<=5)',
    ))
    # OFFICE TOTALS row — paint the FULL row (cols A-CR) deep navy with
    # white bold text when col C contains the label. Reads as one solid
    # 'totals bar' across the whole row. (Top border is applied as a
    # static format in write_office_totals_row, since CF can't set borders.)
    totals_condition = f'=$C{COND_TOP_ROW}="OFFICE TOTALS"'
    requests.append(_cf_rule(sheet_id, 1, LAST_DATA_COL,
                             DEEP_NAVY, bold=True,
                             condition_formula=totals_condition,
                             text_color=WHITE_TEXT))
    return requests


def main() -> int:
    log = _setup_logging()
    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)
    ws = sh.worksheet(TEMPLATE_TAB)
    sheet_id = ws.id

    requests = []

    # 1. Freeze rows 1-2 + col 1
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": 2, "frozenColumnCount": 1},
            },
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
        },
    })

    # 2. Wipe ALL static cell backgrounds + borders in rows 3-200 (clears my
    #    over-eager prior formatting). Conditional rules below take over.
    requests.append({
        "repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 2, "endRowIndex": 200},
            "cell": {"userEnteredFormat": {"backgroundColor": WHITE}},
            "fields": "userEnteredFormat.backgroundColor",
        },
    })
    requests.append({
        "updateBorders": {
            "range": {"sheetId": sheet_id, "startRowIndex": 2, "endRowIndex": 200,
                      "startColumnIndex": 0, "endColumnIndex": 100},
            "innerHorizontal": {"style": "NONE"},
            "innerVertical": {"style": "NONE"},
            "top": {"style": "NONE"}, "bottom": {"style": "NONE"},
            "left": {"style": "NONE"}, "right": {"style": "NONE"},
        },
    })

    # 3. Wipe any existing conditional rules so re-runs don't stack.
    # We have to fetch the count first, then delete from highest index down.
    md = sh.fetch_sheet_metadata(params={"fields": "sheets(properties,conditionalFormats)"})
    for s in md.get("sheets", []):
        if s["properties"].get("sheetId") == sheet_id:
            existing = s.get("conditionalFormats", [])
            for i in range(len(existing) - 1, -1, -1):
                requests.append({
                    "deleteConditionalFormatRule": {
                        "sheetId": sheet_id, "index": i,
                    },
                })
            break

    # 4. Conditional rules — only paint rows where col A is non-blank.
    requests.extend(build_visual_rule_requests(sheet_id))

    sh.batch_update({"requests": requests})
    log.info("recolored template — %d requests "
             "(conditional rules paint only rows with a rep name in col A)",
             len(requests))
    return 0


if __name__ == "__main__":
    sys.exit(main())
