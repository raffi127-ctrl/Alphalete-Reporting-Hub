"""Weekly Knocks -> ATT Program - Focus Report (box numbers + board picture).

    python -m automations.weekly_knocks_focus.run --office "Akashdeep Rai" --tab "Kash Rai - Test Eve"
    python -m automations.weekly_knocks_focus.run --office "Akashdeep Rai" --tab "Kash Rai - Test Eve" --live
    python -m automations.weekly_knocks_focus.run 2026-09-12 --office "Akashdeep Rai" --tab "Kash Rai - Test Eve"

Rafael (via Eve, 2026-09-14): each week, every office's Weekly Knock
Dispositions board also lands in its Focus Report tab —
  1. the OFFICE TOTALS row, into the 'WEEKLY KNOCKS DATA' box, one column per
     week (box.py), and
  2. the board picture, ONE per tab, under everything else on the tab
     (placement.py): last week's picture is replaced, never stacked.

No new pull. The Sunday weekly_knock_dispositions run (Lucy 1) already renders
each board; it also leaves `weekly_knock_dispositions_<saturday>.json`
(headers + totals) next to the PNG, and this reads those two files. So it runs
on THE SAME MACHINE as that report.

THE PICTURE IS A PUBLIC DRIVE FILE (Eve 2026-09-14). =IMAGE() only draws a
link anyone can open, so the PNG goes to alphaletereporting's Drive (the
drive.file token review_gate already uses) shared "anyone with the link can
view". Eve chose this knowing it: the Focus Report itself is shared the same
way, so the picture exposes nothing the tab doesn't. The Apps Script route
(no public link) needed an interactive Google authorization nobody could give.
Last week's file for the tab is trashed when the new one goes in.

PREVIEW ONLY for now (CLAUDE.md: one preview tab before rollout). --live writes
only to PREVIEW_TABS until ROLLOUT flips, so nothing lands on a real owner tab
by accident. Dry-run is the default.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.weekly_knocks_focus import box as BX
from automations.weekly_knocks_focus import placement as PL

REPORT_ID = "weekly_knocks_focus"
PREVIEW_TABS = {"Kash Rai - Test Eve"}
ROLLOUT = False                      # flips after Eve's "looks good, roll out"
# The board is drawn at 2x (total_knocks.render.SCALE); no reader needs more
# than this many source pixels for a picture shown PL.DISPLAY_W wide.
MAX_UPLOAD_W = 2400
DRIVE_FOLDER = "Weekly Knocks Boards - Focus Report"
REPO_ROOT = Path(__file__).resolve().parents[2]
BOARD_DIR = REPO_ROOT / "output" / "weekly_knock_dispositions"


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


def _saturday(anchor: Optional[dt.date]) -> dt.date:
    from automations.shared.report_week import week_ending
    from automations.total_knocks.pull import central_today
    sunday = (week_ending(anchor) if anchor
              else week_ending(central_today() - dt.timedelta(days=1)))
    return sunday - dt.timedelta(days=1)


def _tab_for(office: str) -> Optional[str]:
    """Office (ownerville name) -> Focus Report tab, via office-mapping.json:
    'Akashdeep Rai' is as_owner of the 'Kash Rai' tab."""
    from automations.recruiting_report import fill
    want = office.strip().lower()
    for c in fill.load_mapping().get("confirmed", []):
        if want in (str(c.get("as_owner", "")).strip().lower(),
                    str(c.get("sheet_tab", "")).strip().lower()):
            return c["sheet_tab"]
    return None


def _png(path: Path) -> Tuple[bytes, int, int]:
    """(png bytes, width, height), scaled down to MAX_UPLOAD_W."""
    from PIL import Image
    img = Image.open(path)
    if img.width > MAX_UPLOAD_W:
        img = img.resize((MAX_UPLOAD_W,
                          round(img.height * MAX_UPLOAD_W / img.width)),
                         Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), img.width, img.height


def _upload(tab: str, week_sunday: dt.date, png_bytes: bytes) -> str:
    """Upload this week's picture for `tab`, share it anyone-can-view, trash
    the tab's older pictures. Returns the new Drive file id."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    from automations.fiber_activations import drive_auth

    svc = build("drive", "v3", credentials=drive_auth.load_credentials(),
                cache_discovery=False)
    folder_mime = "application/vnd.google-apps.folder"
    found = svc.files().list(
        q=(f"name = '{DRIVE_FOLDER}' and mimeType = '{folder_mime}' "
           "and trashed = false"),
        spaces="drive", fields="files(id)").execute().get("files", [])
    folder = (found[0]["id"] if found else svc.files().create(
        body={"name": DRIVE_FOLDER, "mimeType": folder_mime},
        fields="id").execute()["id"])

    prefix = f"{tab} - WE "
    name = f"{prefix}{week_sunday.isoformat()}.png"
    media = MediaIoBaseUpload(io.BytesIO(png_bytes), mimetype="image/png",
                              resumable=False)
    file_id = svc.files().create(body={"name": name, "parents": [folder]},
                                 media_body=media, fields="id").execute()["id"]
    svc.permissions().create(fileId=file_id,
                             body={"type": "anyone", "role": "reader"}).execute()

    # ONE picture per tab: every other file of this tab goes to the trash —
    # including an earlier upload of the SAME week, since a re-run gets a new
    # file (and a new link =IMAGE can't serve stale from its cache).
    safe = prefix.replace("\\", "\\\\").replace("'", "\\'")
    old = svc.files().list(
        q=(f"'{folder}' in parents and trashed = false "
           f"and name contains '{safe}'"),
        spaces="drive", fields="files(id,name)").execute().get("files", [])
    for f in old:
        if f["id"] != file_id and f["name"].startswith(prefix):
            svc.files().update(fileId=f["id"], body={"trashed": True}).execute()
            print(f"    trashed last picture: {f['name']}", flush=True)
    return file_id


def _place_picture(ws, week_sunday: dt.date, png: Path, live: bool) -> bool:
    import gspread

    sh = ws.spreadsheet
    values = ws.get_all_values()
    col_a = [r[0] if r else "" for r in values]
    meta = sh.fetch_sheet_metadata({
        "fields": "sheets(properties(sheetId,title,gridProperties),merges)"})
    sheet = next(s for s in meta["sheets"]
                 if s["properties"]["sheetId"] == ws.id)
    grid = sheet["properties"].get("gridProperties", {})
    start_col = max(3, int(grid.get("frozenColumnCount", 0)) + 1)

    anchor = PL.find_marker(col_a)
    fresh = anchor is None
    if fresh:
        anchor = PL.last_used_row(values) + PL.GAP_ROWS + 1

    png_bytes, img_w, img_h = _png(png)
    dims = sh.fetch_sheet_metadata({
        "ranges": [f"'{ws.title}'!A1:{gspread.utils.rowcol_to_a1(grid.get('rowCount', 1000), grid.get('columnCount', 26))}"],
        "includeGridData": True,
        "fields": "sheets(data(columnMetadata(pixelSize),rowMetadata(pixelSize)))"})
    data = dims["sheets"][0]["data"][0]
    col_px = [c.get("pixelSize") for c in data.get("columnMetadata", [])]
    row_px = [r.get("pixelSize") for r in data.get("rowMetadata", [])]
    end_col, end_row = PL.block(col_px, row_px, start_col, anchor, img_w, img_h)

    top_left = gspread.utils.rowcol_to_a1(anchor, start_col)
    bottom_right = gspread.utils.rowcol_to_a1(end_row, end_col)
    print(f"    picture: {png.name} ({img_w}x{img_h}) -> {top_left}:{bottom_right}"
          f" ({'new block' if fresh else 'replaces the one at row ' + str(anchor)})",
          flush=True)
    if end_row > int(grid.get("rowCount", 0)):
        print(f"[wkf] ❌ picture needs rows to {end_row} but the tab stops at "
              f"{grid.get('rowCount')} — not adding rows (workbook cell cap).",
              flush=True)
        return False
    old_merges = PL.merges_at(sheet.get("merges", []), ws.id, anchor, start_col)
    # A NEW block may only land on empty cells. An existing block is ours, but
    # a taller picture this week can reach below it: that part must be empty.
    old_end = max((m["endRowIndex"] for m in old_merges), default=anchor)
    check_from = anchor if fresh else old_end + 1
    if check_from <= end_row and not PL.area_is_empty(
            values, check_from, end_row, start_col, end_col):
        print(f"[wkf] ❌ cells in {gspread.utils.rowcol_to_a1(check_from, start_col)}"
              f":{bottom_right} are not empty — not placing the picture over data.",
              flush=True)
        return False
    if not live:
        return True

    file_id = _upload(ws.title, week_sunday, png_bytes)
    url = f"https://lh3.googleusercontent.com/d/{file_id}"
    requests = [{"unmergeCells": {"range": {k: m[k] for k in (
        "sheetId", "startRowIndex", "endRowIndex",
        "startColumnIndex", "endColumnIndex")}}} for m in old_merges]
    requests.append({"mergeCells": {"mergeType": "MERGE_ALL", "range": {
        "sheetId": ws.id, "startRowIndex": anchor - 1, "endRowIndex": end_row,
        "startColumnIndex": start_col - 1, "endColumnIndex": end_col}}})
    sh.batch_update({"requests": requests})
    label = f"Weekly Knock Dispositions — WE {week_sunday.month}/{week_sunday.day}/{week_sunday.year % 100}"
    ws.batch_update([
        {"range": f"A{anchor}", "values": [[PL.MARKER]]},
        {"range": f"B{anchor}", "values": [[label]]},
        {"range": top_left, "values": [[f'=IMAGE("{url}", 1)']]},
    ], value_input_option="USER_ENTERED")
    print(f"[wkf] ✅ picture in at {top_left}:{bottom_right} ({url}).", flush=True)
    return True


def run_office(office: str, saturday: dt.date, tab: Optional[str],
               live: bool) -> bool:
    import gspread
    from automations.recruiting_report import fill

    stem = f"weekly_knock_dispositions_{saturday.isoformat()}"
    board_json = BOARD_DIR / _slug(office) / f"{stem}.json"
    png = BOARD_DIR / _slug(office) / f"{stem}.png"
    if not board_json.exists():
        print(f"[wkf] ❌ {office}: no {board_json.name} — the weekly_knock_"
              "dispositions run for that week didn't render this office on "
              "this machine.", flush=True)
        return False
    data = json.loads(board_json.read_text(encoding="utf-8"))

    tab = tab or _tab_for(office)
    if not tab:
        print(f"[wkf] ❌ {office}: no Focus Report tab in office-mapping.json.",
              flush=True)
        return False
    if live and not ROLLOUT and tab not in PREVIEW_TABS:
        print(f"[wkf] ❌ {office}: '{tab}' is not a preview tab and the "
              f"rollout isn't on — preview tabs: {sorted(PREVIEW_TABS)}.",
              flush=True)
        return False

    ws = fill.worksheet_ci(fill.open_sheet(), tab)
    col_b = ws.col_values(2)
    week_sunday = saturday + dt.timedelta(days=1)
    week_col = fill.find_sunday_columns([ws.row_values(1)], 0).get(week_sunday)
    if week_col is None:
        print(f"[wkf] ❌ {tab}: no row-1 column for WE {week_sunday}.", flush=True)
        return False
    header, updates, missing = BX.plan(data["headers"], data["totals"], col_b)
    if header is None:
        print(f"[wkf] ❌ {tab}: no '{BX.BOX_HEADER}' box.", flush=True)
        return False

    col_letter = gspread.utils.rowcol_to_a1(1, week_col)[:-1]
    mode = "LIVE" if live else "DRY-RUN"
    print(f"[wkf] {mode} {office} -> '{tab}' WE {week_sunday} "
          f"(column {col_letter}), box at row {header}", flush=True)
    for row, label, value in updates:
        print(f"    {col_letter}{row:<4} {label:<34} {value}", flush=True)
    if missing:
        print(f"    ⚠ no box row for: {', '.join(missing)}", flush=True)

    if live and updates:
        ws.batch_update([{"range": f"{col_letter}{row}", "values": [[value]]}
                         for row, _l, value in updates],
                        value_input_option="USER_ENTERED")
        two_dec = {BX.norm(x) for x in BX.TWO_DECIMAL_LABELS}
        for row, label, _v in updates:
            if BX.norm(label) in two_dec:
                ws.format(f"{col_letter}{row}",
                          {"numberFormat": {"type": "NUMBER", "pattern": "0.00"}})
        print(f"[wkf] ✅ wrote {len(updates)} box cell(s).", flush=True)

    if not png.exists():
        print(f"[wkf] ❌ {office}: board PNG missing ({png}).", flush=True)
        return False
    return _place_picture(ws, week_sunday, png, live)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog=REPORT_ID, description=(
        "Weekly Knock Dispositions totals + board picture -> the office's "
        "Focus Report tab."))
    ap.add_argument("date", nargs="?", default=None,
                    help="any day in the wanted Mon-Sat week (default: last "
                         "completed week)")
    ap.add_argument("--office", action="append", required=True,
                    help="ownerville office name, e.g. 'Akashdeep Rai' (repeatable)")
    ap.add_argument("--tab", default=None,
                    help="write to THIS tab instead of the office's own "
                         "(the preview tab)")
    ap.add_argument("--live", action="store_true", help="write (default: dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="plan only (default)")
    args = ap.parse_args(argv)
    live = args.live and not args.dry_run          # the safe flag wins
    anchor = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else None)
    saturday = _saturday(anchor)
    ok = all([run_office(o, saturday, args.tab, live) for o in args.office])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
