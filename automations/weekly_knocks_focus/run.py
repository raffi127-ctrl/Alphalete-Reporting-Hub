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
# Eve 2026-09-14: "roll out para todas las oficinas de las que tengamos tab en
# el focus report y hagamos knocks report". --all walks every office the
# weekly knocks report covers; one without a tab or without the box is skipped.
# ON HOLD the same night: 'Kash Rai - Test Eve' is where RAFAEL approves before
# anything reaches the other tabs, and he hasn't yet. Back to True with his OK.
ROLLOUT = False
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


def _tab_for(office: str, pss_owner: Optional[str] = None) -> Optional[str]:
    """Office -> Focus Report tab, via office-mapping.json (confirmed and
    sales_only entries). Tried in order: the ownerville office name against
    as_owner / sheet_tab ('Akashdeep Rai' is as_owner of 'Kash Rai'), then the
    board's PSS owner, which is the name the Focus Report knows the office by
    when ownerville's differs ('Muhammad Waqar' sells as 'Salik Mallick';
    'Next Horizon Group, Inc. Nii Tagoe' as 'Nii Tagoe')."""
    from automations.recruiting_report import fill
    mapping = fill.load_mapping()
    entries = mapping.get("confirmed", []) + mapping.get("sales_only", [])
    for name in (office, pss_owner):
        want = str(name or "").strip().lower()
        if not want:
            continue
        for c in entries:
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


def _place_picture(ws, week_sunday: dt.date, week_col: int, png: Path,
                   live: bool) -> bool:
    import gspread

    sh = ws.spreadsheet
    values = ws.get_all_values()
    col_a = [r[0] if r else "" for r in values]
    meta = sh.fetch_sheet_metadata({
        "fields": "sheets(properties(sheetId,title,gridProperties),merges)"})
    sheet = next(s for s in meta["sheets"]
                 if s["properties"]["sheetId"] == ws.id)
    grid = sheet["properties"].get("gridProperties", {})
    frozen = int(grid.get("frozenColumnCount", 0))
    start_col = PL.start_column(week_col, frozen)

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
    end_col, end_row = PL.block(col_px, row_px, start_col, anchor, img_w, img_h,
                                max_col=int(grid.get("columnCount", 0)) or None)

    top_left = gspread.utils.rowcol_to_a1(anchor, start_col)
    bottom_right = gspread.utils.rowcol_to_a1(end_row, end_col)
    old_merges = PL.merges_on_row(sheet.get("merges", []), ws.id, anchor,
                                  frozen + 1)
    print(f"    picture: {png.name} ({img_w}x{img_h}) -> {top_left}:{bottom_right}"
          f" ({'new block' if fresh else 'moves the one on row ' + str(anchor)})",
          flush=True)
    if end_row > int(grid.get("rowCount", 0)):
        print(f"[wkf] ❌ picture needs rows to {end_row} but the tab stops at "
              f"{grid.get('rowCount')} — not adding rows (workbook cell cap).",
              flush=True)
        return False
    # The block may only land on empty cells — last week's block is ours and
    # comes apart first, so its cells don't count.
    if not PL.area_is_empty(values, anchor, end_row, start_col, end_col,
                            ignore=old_merges):
        print(f"[wkf] ❌ cells in {top_left}:{bottom_right} are not empty — "
              "not placing the picture over data.", flush=True)
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
    # Last week's =IMAGE sits in its block's top-left cell; once unmerged it
    # would draw as a stray picture, so it is cleared (unless it IS this
    # week's top-left, which the write below replaces anyway).
    stale = [gspread.utils.rowcol_to_a1(m["startRowIndex"] + 1,
                                        m["startColumnIndex"] + 1)
             for m in old_merges]
    stale = [a1 for a1 in stale if a1 != top_left]
    if stale:
        ws.batch_clear(stale)
    label = f"Weekly Knock Dispositions — WE {week_sunday.month}/{week_sunday.day}/{week_sunday.year % 100}"
    ws.batch_update([
        {"range": f"A{anchor}", "values": [[PL.MARKER]]},
        {"range": f"B{anchor}", "values": [[label]]},
        {"range": top_left, "values": [[f'=IMAGE("{url}", 1)']]},
    ], value_input_option="USER_ENTERED")
    print(f"[wkf] ✅ picture in at {top_left}:{bottom_right} ({url}).", flush=True)
    return True


def run_office(office: str, saturday: dt.date, tab: Optional[str],
               live: bool, pss_owner: Optional[str] = None,
               skip_missing: bool = False) -> bool:
    """True when the office's box + picture landed (or would, dry-run).

    `skip_missing` (the --all sweep): an office with no Focus Report tab, or a
    tab without the box, is skipped with a line and counts as fine — the sweep
    covers every office the weekly knocks report posts, and not all of them
    have a Focus Report tab (Isaiah Revelle) or that layout (Raf's master tab).
    A MISSING BOARD is never skipped: that means Sunday's run didn't render
    an office it should have."""
    import gspread
    from automations.recruiting_report import fill

    tab = tab or _tab_for(office, pss_owner)
    if not tab:
        print(f"[wkf] {'⤳' if skip_missing else '❌'} {office}: no Focus Report "
              "tab in office-mapping.json" + (" — skipped." if skip_missing else "."),
              flush=True)
        return skip_missing

    stem = f"weekly_knock_dispositions_{saturday.isoformat()}"
    board_json = BOARD_DIR / _slug(office) / f"{stem}.json"
    png = BOARD_DIR / _slug(office) / f"{stem}.png"
    if not board_json.exists():
        print(f"[wkf] ❌ {office}: no {board_json.name} — the weekly_knock_"
              "dispositions run for that week didn't render this office on "
              "this machine.", flush=True)
        return False
    data = json.loads(board_json.read_text(encoding="utf-8"))
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
        print(f"[wkf] {'⤳' if skip_missing else '❌'} {office}: tab '{tab}' has "
              f"no '{BX.BOX_HEADER}' box" + (" — skipped." if skip_missing else "."),
              flush=True)
        return skip_missing

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
    return _place_picture(ws, week_sunday, week_col, png, live)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog=REPORT_ID, description=(
        "Weekly Knock Dispositions totals + board picture -> the office's "
        "Focus Report tab."))
    ap.add_argument("date", nargs="?", default=None,
                    help="any day in the wanted Mon-Sat week (default: last "
                         "completed week)")
    ap.add_argument("--office", action="append", default=None,
                    help="ownerville office name, e.g. 'Akashdeep Rai' "
                         "(repeatable). Wins over --all, so a rerun of the "
                         "scheduled step can target one office.")
    ap.add_argument("--all", action="store_true",
                    help="every office weekly_knock_dispositions covers; "
                         "offices without a Focus Report tab or box are skipped")
    ap.add_argument("--tab", default=None,
                    help="write to THIS tab instead of the office's own "
                         "(the preview tab); only with --office")
    ap.add_argument("--live", action="store_true", help="write (default: dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="plan only (default)")
    args = ap.parse_args(argv)
    live = args.live and not args.dry_run          # the safe flag wins
    anchor = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else None)
    saturday = _saturday(anchor)

    from automations.weekly_knock_dispositions.offices import enabled
    if args.office:
        wanted = [(o, None, args.tab, False) for o in args.office]
        pss = {c["name"]: c.get("pss_owner") for c in enabled(None)}
        wanted = [(o, pss.get(o), t, s) for o, _p, t, s in wanted]
    elif args.all:
        wanted = [(c["name"], c.get("pss_owner"), None, True) for c in enabled(None)]
    else:
        ap.error("pass --office NAME or --all")
    results = {name: run_office(name, saturday, tab, live, pss_owner=pss_owner,
                                skip_missing=skip)
               for name, pss_owner, tab, skip in wanted}
    failed = [n for n, ok in results.items() if not ok]
    print(f"[wkf] {'⚠' if failed else '✅'} {'LIVE' if live else 'DRY-RUN'} done — "
          f"{len(results) - len(failed)}/{len(results)} ok"
          + (f"; failed: {', '.join(failed)}" if failed else ""), flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
