"""Spectrum knocks -> Google Sheet: one row per rep per day, newest day on top.

Tab "Daily" in the sheet below. Each run writes ONE day: rows already on the
tab for that same day are replaced (so a re-run never doubles a day), every
other day is kept. Only reps who knocked at least one door get a row.

Columns are found by their header label, never by position. If the tab has no
header yet, the default one is written.

SANDBOX until Eve says "use the real Sheet":
    python -m automations.spectrum_knocks.fill              # yesterday
    python -m automations.spectrum_knocks.fill 2026-11-17   # a date
    python -m automations.spectrum_knocks.fill 2026-11-17 --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
from typing import List, Optional

from automations.recruiting_report.fill import open_by_key
from automations.spectrum_knocks import pull

# Sandbox: "Spectrum Knocks - TEST" (Eve's Drive, shared with alphaletereporting).
SHEET_ID = "1-7uiilLUBsxYXWdRyJ3ysS8IiSUphwvM-NpoBuh0wGE"
TAB = "Daily"

BREAK_COL = f"Breaks ({pull.BREAK_MINUTES}+ min)"
HEADER = (["Date", "Rep", "Doors"] + pull.COLUMNS
          + ["First Door", "Last Door", "Hours Knocking", BREAK_COL,
             "Longest Break (min)"])


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def _date_key(s: str) -> dt.date:
    """'11/17/2026', or a bare sheet serial like '46343' if the cell lost its
    date format — both must match the same day, or a re-run doubles it."""
    txt = str(s).strip()
    try:
        return dt.datetime.strptime(txt, "%m/%d/%Y").date()
    except ValueError:
        pass
    try:
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(float(txt)))
    except ValueError:
        return dt.date.min


def _worksheet(sh):
    titles = [w.title for w in sh.worksheets()]
    if TAB in titles:
        return sh.worksheet(TAB)
    if titles == ["Sheet1"]:  # brand-new sandbox: rename the blank first tab
        ws = sh.worksheet("Sheet1")
        ws.update_title(TAB)
        return ws
    return sh.add_worksheet(TAB, rows=1000, cols=len(HEADER))


def build_rows(day: dt.date, summary: List[dict], header: List[str]) -> List[list]:
    by_label = {_norm(h): i for i, h in enumerate(header)}
    out = []
    for line in summary:
        if not line["Doors"]:
            continue
        row = [""] * len(header)
        values = dict(line)
        values["Date"] = day.strftime("%m/%d/%Y")
        for label, val in values.items():
            i = by_label.get(_norm(label))
            if i is not None:
                row[i] = val
        out.append(row)
    return out


def fill(day: dt.date, summary: List[dict], *, sheet_id: str = SHEET_ID,
         dry_run: bool = False) -> int:
    sh = open_by_key(sheet_id)
    ws = _worksheet(sh)
    values = ws.get_all_values()
    header = values[0] if values and any(values[0]) else []
    if not header:
        header = list(HEADER)
    missing = [h for h in HEADER if _norm(h) not in {_norm(x) for x in header}]
    if missing:
        raise RuntimeError(f"Tab '{TAB}' header is missing {missing}")
    date_i = [_norm(h) for h in header].index("date")
    stamp = day.strftime("%m/%d/%Y")
    kept = [r + [""] * (len(header) - len(r)) for r in values[1:]
            if any(c.strip() for c in r) and _date_key(r[date_i]) != day]
    new = build_rows(day, summary, header)
    body = new + kept
    body.sort(key=lambda r: _date_key(r[date_i]), reverse=True)  # stable: day's order kept
    if dry_run:
        print(f"[dry-run] would write {len(new)} rows for {stamp} "
              f"(+{len(kept)} rows from other days) to '{TAB}'")
        return len(new)
    end_row = max(len(values), len(body) + 1)
    blank = [[""] * len(header) for _ in range(end_row - 1 - len(body))]
    if ws.row_count < end_row:
        ws.add_rows(end_row - ws.row_count)
    ws.update(values=[header] + body + blank, range_name="A1",
              value_input_option="USER_ENTERED")
    _style(sh, ws, header, body, date_i, end_row)
    return len(new)


# --- Look ------------------------------------------------------------------
_HEADER_BG = {"red": 0.0, "green": 0.27, "blue": 0.53}      # Spectrum navy
_DAY_BG = [{"red": 1, "green": 1, "blue": 1},                # alternate days
           {"red": 0.93, "green": 0.95, "blue": 0.98}]
_GREEN = {"red": 0.80, "green": 0.92, "blue": 0.80}
_RED = {"red": 0.98, "green": 0.82, "blue": 0.80}
_LONG_BREAK_MIN = 60


def _style(sh, ws, header, body, date_i, end_row) -> None:
    """Header bar, one shade per day, a line between days, sales in green,
    breaks of an hour+ in red. Rebuilt from scratch every run."""
    sid = ws.id
    ncols = len(header)
    lab = [_norm(h) for h in header]

    def rng(r0, r1, c0=0, c1=ncols):
        return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}

    meta = sh.fetch_sheet_metadata(
        {"fields": "sheets(properties.sheetId,conditionalFormats)"})
    n_rules = next((len(s.get("conditionalFormats", [])) for s in meta["sheets"]
                    if s["properties"]["sheetId"] == sid), 0)
    reqs = [{"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}}
            for _ in range(n_rules)]

    # Clean slate below the header, then the header bar.
    reqs.append({"repeatCell": {
        "range": rng(1, end_row),
        "cell": {"userEnteredFormat": {
            "backgroundColor": _DAY_BG[0],
            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
            "textFormat": {"fontSize": 10, "bold": False}}},
        "fields": "userEnteredFormat"}})
    reqs.append({"updateBorders": {"range": rng(1, end_row),
                                   "top": {"style": "NONE"},
                                   "innerHorizontal": {
                                       "style": "SOLID",
                                       "color": {"red": 0.88, "green": 0.88, "blue": 0.88}}}})
    reqs.append({"repeatCell": {
        "range": rng(0, 1),
        "cell": {"userEnteredFormat": {
            "backgroundColor": _HEADER_BG, "wrapStrategy": "WRAP",
            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
            "textFormat": {"bold": True, "fontSize": 10,
                           "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
        "fields": "userEnteredFormat"}})

    # One shade per day + a line where a new day starts.
    start, shade = 0, 0
    for i in range(1, len(body) + 1):
        if i == len(body) or body[i][date_i] != body[start][date_i]:
            r0, r1 = start + 1, i + 1
            reqs.append({"repeatCell": {
                "range": rng(r0, r1),
                "cell": {"userEnteredFormat": {"backgroundColor": _DAY_BG[shade]}},
                "fields": "userEnteredFormat.backgroundColor"}})
            reqs.append({"updateBorders": {"range": rng(r0, r1), "top": {
                "style": "SOLID_MEDIUM",
                "color": {"red": 0.6, "green": 0.6, "blue": 0.6}}}})
            reqs.append({"repeatCell": {
                "range": rng(r0, r1, date_i, date_i + 1),
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold"}})
            start, shade = i, 1 - shade

    # Number formats (the clean slate above wipes them). The date MUST stay
    # mm/dd/yyyy: the next run reads it back to find that day's rows.
    for col, pattern, kind in (("date", "mm/dd/yyyy", "DATE"),
                               ("first door", "h:mm AM/PM", "TIME"),
                               ("last door", "h:mm AM/PM", "TIME")):
        if col in lab:
            c = lab.index(col)
            reqs.append({"repeatCell": {
                "range": rng(1, end_row, c, c + 1),
                "cell": {"userEnteredFormat": {"numberFormat": {
                    "type": kind, "pattern": pattern}}},
                "fields": "userEnteredFormat.numberFormat"}})

    # Rep names left-aligned and bold; Doors bold.
    for name in ("rep", "doors"):
        if name in lab:
            c = lab.index(name)
            fmt = {"textFormat": {"bold": True}}
            if name == "rep":
                fmt["horizontalAlignment"] = "LEFT"
            reqs.append({"repeatCell": {
                "range": rng(1, end_row, c, c + 1),
                "cell": {"userEnteredFormat": fmt},
                "fields": "userEnteredFormat(textFormat.bold,horizontalAlignment)"}})

    # Sales green, long breaks red.
    def rule(col, cond, value, color):
        if col not in lab:
            return
        c = lab.index(col)
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [rng(1, end_row, c, c + 1)],
            "booleanRule": {"condition": {"type": cond,
                                          "values": [{"userEnteredValue": str(value)}]},
                            "format": {"backgroundColor": color,
                                       "textFormat": {"bold": True}}}}}})
    rule("sold", "NUMBER_GREATER", 0, _GREEN)
    rule("mobile sold", "NUMBER_GREATER", 0, _GREEN)
    rule("longest break (min)", "NUMBER_GREATER_THAN_EQ", _LONG_BREAK_MIN, _RED)

    # Sizes, frozen header + rep column.
    widths = {"date": 95, "rep": 170}
    for c, h in enumerate(lab):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": c, "endIndex": c + 1},
            "properties": {"pixelSize": widths.get(h, 92)},
            "fields": "pixelSize"}})
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 44}, "fields": "pixelSize"}})
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": sid, "gridProperties": {
            "frozenRowCount": 1, "frozenColumnCount": 2, "hideGridlines": True}},
        "fields": "gridProperties(frozenRowCount,frozenColumnCount,hideGridlines)"}})
    sh.batch_update({"requests": reqs})


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    day = (dt.date.fromisoformat(a.date) if a.date
           else dt.date.today() - dt.timedelta(days=1))
    summary = pull.run(day)
    n = fill(day, summary, dry_run=a.dry_run)
    print(f"Spectrum knocks {day}: {n} rep rows -> "
          f"https://docs.google.com/spreadsheets/d/{SHEET_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
