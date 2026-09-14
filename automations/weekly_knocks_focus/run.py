"""Weekly Knocks -> ATT Program - Focus Report (box numbers + board image).

    python -m automations.weekly_knocks_focus.run --office "Akashdeep Rai" --tab "Kash Rai - Test Eve"
    python -m automations.weekly_knocks_focus.run --office "Akashdeep Rai" --tab "Kash Rai - Test Eve" --live
    python -m automations.weekly_knocks_focus.run 2026-09-12 --office "Akashdeep Rai" --tab "Kash Rai - Test Eve"

Rafael (via Eve, 2026-09-14): each week, every office's Weekly Knock
Dispositions board also lands in its Focus Report tab —
  1. the OFFICE TOTALS row, into the 'WEEKLY KNOCKS DATA' box, one column per
     week (box.py), and
  2. the board picture itself, ONE per tab: last week's comes off, this week's
     goes in, next to the newest week column.

No new pull. The Sunday weekly_knock_dispositions run (Lucy 1) already renders
each board; it now also leaves `weekly_knock_dispositions_<saturday>.json`
(headers + totals) next to the PNG, and this reads those two files. So it runs
on THE SAME MACHINE as that report.

The picture goes through the Focus Report's own Apps Script
(appsscript/weekly_board_image.gs) — =IMAGE() would need a public link to a
board full of rep names. Its URL + key live in
~/.config/recruiting-report/weekly-knocks-focus-webapp.json
({"url": ..., "key": ...}), never in git.

PREVIEW ONLY for now (CLAUDE.md: one preview tab before rollout). --live writes
only to PREVIEW_TABS until ROLLOUT flips, so nothing lands on a real owner tab
by accident. Dry-run is the default.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import io
import json
import sys
from pathlib import Path
from typing import List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.weekly_knocks_focus import box as BX

REPORT_ID = "weekly_knocks_focus"
PREVIEW_TABS = {"Kash Rai - Test Eve"}
ROLLOUT = False                      # flips after Eve's "looks good, roll out"
IMAGE_TAG = "WEEKLY_KNOCKS_BOARD"
# The board is drawn at 2x (total_knocks.render.SCALE). Sent at most this wide
# so the upload stays far under Apps Script's blob limit; shown at DISPLAY_W.
MAX_UPLOAD_W = 2400
DISPLAY_W = 1200
WEBAPP_CONFIG = (Path.home() / ".config" / "recruiting-report"
                 / "weekly-knocks-focus-webapp.json")
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


def _png_bytes(path: Path) -> bytes:
    from PIL import Image
    img = Image.open(path)
    if img.width > MAX_UPLOAD_W:
        img = img.resize((MAX_UPLOAD_W, round(img.height * MAX_UPLOAD_W / img.width)),
                         Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _post_image(tab: str, row: int, col: int, png: Path) -> dict:
    import requests
    cfg = json.loads(WEBAPP_CONFIG.read_text(encoding="utf-8-sig"))
    body = {"key": cfg["key"], "tab": tab, "row": row, "col": col,
            "png_b64": base64.b64encode(_png_bytes(png)).decode("ascii"),
            "name": png.name, "tag": IMAGE_TAG, "width": DISPLAY_W}
    resp = requests.post(cfg["url"], data=json.dumps(body),
                         headers={"Content-Type": "application/json"},
                         timeout=180)
    try:
        return resp.json()
    except ValueError:
        return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}


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
    img_col = week_col + 1
    img_at = gspread.utils.rowcol_to_a1(header, img_col)
    print(f"    image: {png.name if png.exists() else 'MISSING PNG'} -> {img_at} "
          "(replaces last week's)", flush=True)
    if not live:
        return True

    if updates:
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
    if not WEBAPP_CONFIG.exists():
        print(f"[wkf] ❌ image skipped: no {WEBAPP_CONFIG} — the Focus Report "
              "Apps Script isn't deployed/configured on this machine yet.",
              flush=True)
        return False
    res = _post_image(tab, header, img_col, png)
    if not res.get("ok"):
        print(f"[wkf] ❌ image failed: {res.get('error')}", flush=True)
        return False
    print(f"[wkf] ✅ image in at {img_at} (removed {res.get('removed', 0)} old, "
          f"{res.get('width')}x{res.get('height')}).", flush=True)
    return True


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog=REPORT_ID, description=(
        "Weekly Knock Dispositions totals + board image -> the office's "
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
