"""One-off: make Daily Focus tabs read like the ATT Program - Focus Report.

Raf (via Eve, 2026-11-17): the Daily Focus Report should look like the
daily-focus rows of the Monday 1on1s, i.e. the ATT Program tab wording
and order:

  * labels renamed (APPS / PULL, Duplicate/Already Interviewed, 1ST BOOKED,
    1ST SHOWED, 1st Retention, Retention 1st showed Booked for 2nd,
    2ND BOOKED, 2ND SHOWED, 2ND Retention, BOB Conversion);
  * Booked/Scheduled ABOVE Showed (1st rds, 2nd rds, New Starts): the two
    rows swap, numbers travel with their label, and so does the grey
    "Next Week" cell;
  * Duplicate % goes pink like the ATT tab, 2nd-round blue = ATT blue.

Works on both blocks of every section (Current Week A:J, Last Week L:S),
finds everything by the col-C / col-L label, never by row number. Safe to
re-run: an already-converted section is left alone. Backs the tab up to
output/ before writing. daily_focus.py reads both the old and new labels.

  python -m automations.recruiting_report.daily_focus_att_layout --tab TEMPLATE --dry-run
  python -m automations.recruiting_report.daily_focus_att_layout --tab TEMPLATE
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from gspread.utils import rowcol_to_a1

from automations.recruiting_report import fill
from automations.recruiting_report.daily_focus import DAILY_FOCUS_SPREADSHEET_ID

ROOT = Path(__file__).resolve().parents[2]

# canonical key -> new label
NEW_LABEL = {
    "pull": "APPS / PULL",
    "removed": "Duplicate/Already Interviewed",
    "dup_pct": "Duplicate %",
    "first_showed": "1ST SHOWED",
    "first_booked": "1ST BOOKED",
    "first_ret": "1st Retention",
    "first_to_2nd": "Retention 1st showed Booked for 2nd",
    "second_showed": "2ND SHOWED",
    "second_booked": "2ND BOOKED",
    "second_ret": "2ND Retention",
    "bob_pct": "BOB Conversion",
    "ns_showed": "New Starts Showed",
    "ns_sched": "New Starts Scheduled",
    "ns_ret": "New Start Retention",
}
# lowercased, stripped label (old or new) -> canonical key
CANON = {
    "sent to call list - apps / pull": "pull", "apps / pull": "pull",
    "removed from process emails": "removed",
    "duplicate/already interviewed": "removed",
    "duplicate %": "dup_pct",
    "1st rds showed up": "first_showed", "1st showed": "first_showed",
    "1st rds scheduled": "first_booked", "1st booked": "first_booked",
    "1st rd retention": "first_ret", "1st retention": "first_ret",
    "% of 1st rds booked for 2nd": "first_to_2nd",
    "retention 1st showed booked for 2nd": "first_to_2nd",
    "2nd rds showed up": "second_showed", "2nd showed": "second_showed",
    "2nd rds scheduled": "second_booked", "2nd booked": "second_booked",
    "2nd rd retention": "second_ret", "2nd retention": "second_ret",
    "bob %": "bob_pct", "bob conversion": "bob_pct",
    "new starts showed": "ns_showed", "new starts scheduled": "ns_sched",
    "new start retention": "ns_ret",
}
PAIRS = [("first_booked", "first_showed"), ("second_booked", "second_showed"),
         ("ns_sched", "ns_showed")]
ANCHOR = "office focus report"
SECTION_SPAN = 22          # metric rows sit within 22 rows of the anchor
# (label col, first col, last col) 0-based: Current Week A:J, Last Week L:S
BLOCKS = [(2, 0, 9), (11, 11, 18)]

PINK, LIGHT_PINK = "#ffabbb", "#ffe6dd"
OLD_BLUE, ATT_BLUE = "#4dd0e1", "#90dcee"


def _hex(color) -> str:
    if not color:
        return ""
    # the API drops zero channels, so black arrives as {"rgbColor": {}}
    c = color["rgbColor"] if "rgbColor" in color else color
    return "#%02x%02x%02x" % tuple(round(c.get(k, 0) * 255) for k in ("red", "green", "blue"))


def _rgb(hexstr: str) -> dict:
    h = hexstr.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def _canon(label) -> str:
    return CANON.get(" ".join(str(label or "").split()).lower(), "")


def plan(values, bgs, sheet_id):
    """values/bgs: 2-D lists (row-major, 0-based). Returns (value_updates, format_requests, notes)."""
    def cell(r, c):
        return values[r][c] if r < len(values) and c < len(values[r]) else ""

    def bg(r, c):
        return bgs[r][c] if r < len(bgs) and c < len(bgs[r]) else ""

    vals, fmts, notes = {}, [], []

    def set_bg(r, c, hexstr):
        fmts.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": r, "endRowIndex": r + 1,
                      "startColumnIndex": c, "endColumnIndex": c + 1},
            "cell": {"userEnteredFormat": {"backgroundColorStyle": {"rgbColor": _rgb(hexstr)}}},
            "fields": "userEnteredFormat.backgroundColorStyle"}})

    for lab, c0, c1 in BLOCKS:
        anchors = [r for r in range(len(values))
                   if " ".join(str(cell(r, lab)).split()).lower() == ANCHOR]
        for a in anchors:
            rows = {}
            for r in range(a + 1, min(a + SECTION_SPAN, len(values))):
                k = _canon(cell(r, lab))
                if k and k not in rows:
                    rows[k] = r
                if " ".join(str(cell(r, lab)).split()).lower() == ANCHOR:
                    break
            # 1) swap Showed/Booked pairs so Booked sits on top
            for booked, showed in PAIRS:
                if booked in rows and showed in rows and rows[showed] < rows[booked]:
                    top, bot = rows[showed], rows[booked]
                    for c in range(c0, c1 + 1):
                        vals[(top, c)], vals[(bot, c)] = cell(bot, c), cell(top, c)
                    # the grey Next Week cell (last col) travels with its row
                    if bg(top, c1) != bg(bot, c1):
                        set_bg(top, c1, bg(bot, c1) or "#ffffff")
                        set_bg(bot, c1, bg(top, c1) or "#ffffff")
                    rows[booked], rows[showed] = top, bot
            # 2) rename labels (after the swap, by where each canonical now sits)
            for k, r in rows.items():
                if k in NEW_LABEL and str(vals.get((r, lab), cell(r, lab))).strip() != NEW_LABEL[k]:
                    vals[(r, lab)] = NEW_LABEL[k]
            # 3) colours: Duplicate % pink, 2nd-round blue -> ATT blue
            if "dup_pct" in rows:
                r = rows["dup_pct"]
                label_cols = list(range(c0, lab + 1)) + [c1 - 1]   # goals+label, Total
                for c in range(c0, c1):                            # never the Next Week col
                    want = PINK if c in label_cols else LIGHT_PINK
                    if bg(r, c) != want:
                        set_bg(r, c, want)
            for k in ("second_booked", "second_showed"):
                if k in rows:
                    for c in range(c0, c1 + 1):
                        if bg(rows[k], c) == OLD_BLUE:
                            set_bg(rows[k], c, ATT_BLUE)
            notes.append(f"block col {lab + 1} section row {a + 1}: {len(rows)} labels")
    updates = [{"range": rowcol_to_a1(r + 1, c + 1), "values": [[v]]}
               for (r, c), v in sorted(vals.items()) if v != cell(r, c)]
    return updates, fmts, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tab", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sh = fill.open_by_key(DAILY_FOCUS_SPREADSHEET_ID)
    ws = sh.worksheet(args.tab)
    rng = f"'{args.tab}'!A1:S{ws.row_count}"
    values = ws.get(f"A1:S{ws.row_count}", value_render_option="FORMULA")
    meta = sh.client.request("get", f"https://sheets.googleapis.com/v4/spreadsheets/{sh.id}", params={
        "ranges": rng,
        "fields": "sheets(data(rowData(values(userEnteredFormat(backgroundColorStyle)))))"}).json()
    rowdata = meta["sheets"][0]["data"][0].get("rowData", [])
    bgs = [[_hex(v.get("userEnteredFormat", {}).get("backgroundColorStyle")) for v in row.get("values", [])]
           for row in rowdata]

    updates, fmts, notes = plan(values, bgs, ws.id)
    print("\n".join(notes))
    print(f"{args.tab}: {len(updates)} cell value changes, {len(fmts)} colour changes")
    if args.dry_run:
        for u in updates[:60]:
            print("  ", u["range"], u["values"][0][0])
        return 0

    out = ROOT / "output" / f"daily_focus_att_layout_backup_{args.tab.replace(' ', '_')}_{dt.datetime.now():%Y-%m-%d_%H%M%S}.json"
    out.write_text(json.dumps({"tab": args.tab, "values": values, "bg": bgs}), encoding="utf-8")
    print("backup:", out)
    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    if fmts:
        sh.batch_update({"requests": fmts})
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
