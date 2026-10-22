"""Line Up picture + Car Ride names (Raf, Loom 2026-10-22).

Ask: "at 11:45 Central for my office, it automatically takes a screenshot of
the lineup ... from the numbers all the way to column Car Ride #5 ... posted on
Alphalete Sales and ... the A-Players chat. And then at 8:45 p.m. at night, it
copies all these names ... posted on this Car Ride chat."

Source: `Alphalete SALES BOARD 2025` -> tab `Line Up WE <m>.<d>` (this week's
Sunday). The car-ride box is col A ('#') through the 'Car Ride #5' header, both
found BY LABEL on the header row (the row whose col A is '#'). A car ride is a
numbered row with at least one name; the empty numbered rows and the reference
blocks underneath ('Rep names from Sales Board', notes) are left out.

  --photo  (11:45)  picture of the box -> #alphalete-sales + Knocking Chat A-Players
  --names  (20:45)  the names as text  -> the Car Ride iMessage chat

WHY A TEMP TAB: the box has empty numbered rows in the middle (12-20 today).
To leave them out of the picture we hide them on a throwaway COPY of the tab,
export, and delete the copy -- the live tab (people edit it all day) is never
touched. Same trick as sales_boards.render.

LUCY 1 (Raf's machine: its Messages app is in both chats, its Slack token posts
as Lucy). One send per slot per day (lock file).

  python -m automations.lineup_post.run --photo            # dry run: saves the PNG
  python -m automations.lineup_post.run --names            # dry run: prints the text
  python -m automations.lineup_post.run --photo --send     # really posts
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from automations.alphalete_sales_board.config import SPREADSHEET_ID  # noqa: E402

SLACK_CHANNEL = "C068PH3RFSM"                  # #alphalete-sales
PHOTO_GROUPS = ["Knocking Chat A-Players"]
# The room Raf adds Lucy to in the Loom. Resolved by NAME on every send
# (text_post.resolve_group raises on 0 or 2+ matches, never guesses).
NAMES_GROUPS = ["Car Ride"]

TAB_PREFIX = "Line Up WE"
LAST_HEADER = "car ride #5"

OUT_DIR = REPO / "output" / "lineup_post"
STATE_PATH = (Path.home() / ".config" / "recruiting-report"
              / "lineup_post_sent.json")


def _ct_today() -> dt.date:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Chicago")).date()
    except Exception:  # noqa: BLE001
        return dt.date.today()


def tab_name(day: dt.date) -> str:
    sunday = day + dt.timedelta(days=(6 - day.weekday()))
    return "%s %d.%d" % (TAB_PREFIX, sunday.month, sunday.day)


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def struck_cells(sh, tab: str, nrows: int, ncols: int):
    """{(row, col)} 1-based of cells whose text is crossed out -- on this board
    a crossed-out name is someone who is NOT riding, so the names text drops
    them (the picture shows them crossed out, exactly as the sheet does)."""
    from gspread.utils import rowcol_to_a1
    meta = sh.fetch_sheet_metadata(params={
        "includeGridData": "true",
        "ranges": "'%s'!A1:%s" % (tab, rowcol_to_a1(nrows, ncols)),
        "fields": "sheets(data(startRow,startColumn,rowData(values("
                  "effectiveFormat/textFormat/strikethrough,textFormatRuns))))"})
    out = set()
    for d in meta["sheets"][0].get("data", []):
        r0, c0 = d.get("startRow", 0), d.get("startColumn", 0)
        for i, rd in enumerate(d.get("rowData", [])):
            for j, v in enumerate(rd.get("values", [])):
                tf = v.get("effectiveFormat", {}).get("textFormat", {})
                runs = v.get("textFormatRuns") or []
                if tf.get("strikethrough") or (
                        runs and all(r.get("format", {}).get("strikethrough")
                                     for r in runs)):
                    out.add((r0 + i + 1, c0 + j + 1))
    return out


def find_box(grid, struck=frozenset()):
    """(header_row, last_col, rows) -- 1-based. rows = [(row, '#', [names])].
    Names in `struck` cells are left out; a row whose names are ALL struck is
    still a car ride (it keeps its spot in the picture)."""
    hdr = None
    for i, r in enumerate(grid, 1):
        if r and _norm(r[0]) == "#":
            hdr = i
            break
    if hdr is None:
        raise SystemExit("Line Up: no header row with '#' in col A")
    heads = [_norm(c).lower() for c in grid[hdr - 1]]
    if LAST_HEADER not in heads:
        raise SystemExit("Line Up: no '%s' header on row %d: %r"
                         % (LAST_HEADER, hdr, grid[hdr - 1]))
    last_col = heads.index(LAST_HEADER) + 1
    rows = []
    for i in range(hdr + 1, len(grid) + 1):
        r = grid[i - 1] + [""] * last_col
        num = _norm(r[0])
        if not num.isdigit():
            if rows and not num:
                # first un-numbered row after the box = the box is over
                if not any(_norm(c) for c in r[1:last_col]):
                    break
            continue
        cells = [(j + 1, _norm(c)) for j, c in enumerate(r[1:last_col], 1) if _norm(c)]
        if cells:
            rows.append((i, num, [n for col, n in cells if (i, col) not in struck]))
    if not rows:
        raise SystemExit("Line Up: the car-ride box is empty")
    return hdr, last_col, rows


def names_text(rows, day: dt.date) -> str:
    lines = ["Car Rides - %s %d/%d" % (day.strftime("%a"), day.month, day.day)]
    for _, num, names in rows:
        if not names:
            continue
        lines.append("%s. %s" % (num, ", ".join(names)))
    return "\n".join(lines)


def render_photo(sh, ws, hdr, last_col, rows, day: dt.date) -> Path:
    from gspread.utils import rowcol_to_a1
    from automations.pnl_office.run import _token
    from automations.sales_boards import render as R

    last_row = rows[-1][0]
    keep = {r for r, _, _ in rows}
    hide = [r for r in range(hdr + 1, last_row + 1) if r not in keep]
    tmp = sh.duplicate_sheet(ws.id, insert_sheet_index=len(sh.worksheets()),
                             new_sheet_name="_lineup_tmp_%s" % day.strftime("%m%d%H%M%S"))
    try:
        R.set_rows_hidden(sh, tmp.id, hide, True)
        rng = "A%d:%s" % (hdr, rowcol_to_a1(last_row, last_col))
        img = R.export(SPREADSHEET_ID, tmp.id, rng, _token())
    finally:
        sh.del_worksheet(tmp)
    title = "Line Up - %s %d/%d" % (day.strftime("%A"), day.month, day.day)
    img = R.stitch([R.title_bar(img.width, title), img], gap=0)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / ("lineup_%s.png" % day.isoformat())
    img.save(out)
    return out


def _sent() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _mark(key: str) -> None:
    d = _sent()
    d[key] = dt.datetime.now().isoformat(timespec="seconds")
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(d, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--photo", action="store_true", help="11:45 picture")
    g.add_argument("--names", action="store_true", help="8:45 PM names text")
    ap.add_argument("--send", action="store_true", help="really post (default: dry run)")
    ap.add_argument("--force", action="store_true", help="send even if already sent today")
    ap.add_argument("--tab", help="read this tab instead of this week's")
    a = ap.parse_args(argv)

    day = _ct_today()
    slot = "photo" if a.photo else "names"
    key = "%s|%s" % (day.isoformat(), slot)
    if a.send and not a.force and key in _sent():
        print("already sent %s today (%s) - nothing to do" % (slot, _sent()[key]))
        return 0

    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(SPREADSHEET_ID)
    tab = a.tab or tab_name(day)
    ws = sh.worksheet(tab)
    grid = ws.get_values("A1:Z80")
    hdr, last_col, rows = find_box(grid)
    if a.names:
        hdr, last_col, rows = find_box(
            grid, struck_cells(sh, tab, rows[-1][0], last_col))
    print("%s: %d car rides (rows %d-%d)" % (tab, len(rows), rows[0][0], rows[-1][0]))

    from automations.b2b_dispositions import text_post
    if not a.send and sys.platform != "darwin":
        # resolving the iMessage room needs Messages (a Mac); on Windows a dry
        # run only shows what would go out.
        class _Preview:
            @staticmethod
            def send_text_to_group(grp, body, dry_run=True):
                return {"resolved_name": "(not checked - not a Mac)"}
            send_to_group = staticmethod(
                lambda grp, text, imgs, dry_run=True: {"resolved_name": "(not checked - not a Mac)"})
        text_post = _Preview()
    if a.names:
        body = names_text(rows, day)
        print(body)
        for grp in NAMES_GROUPS:
            r = text_post.send_text_to_group(grp, body, dry_run=not a.send)
            print("%s -> %s (%s)" % ("TEXT" if a.send else "PREVIEW", grp,
                                     r.get("resolved_name")))
    else:
        png = render_photo(sh, ws, hdr, last_col, rows, day)
        print("picture: %s" % png)
        caption = "Line Up - %s %d/%d" % (day.strftime("%A"), day.month, day.day)
        from automations.shared import slack_metrics_post as smp
        r = smp.post_reply_with_image(png, comment=caption, channel_id=SLACK_CHANNEL,
                                      top_level=True, mirror=False, dry_run=not a.send,
                                      file_name=png.name)
        print("%s -> #alphalete-sales %s" % ("SLACK" if a.send else "PREVIEW", r))
        for grp in PHOTO_GROUPS:
            r = text_post.send_to_group(grp, caption, [png], dry_run=not a.send)
            print("%s -> %s (%s)" % ("TEXT" if a.send else "PREVIEW", grp,
                                     r.get("resolved_name")))
    if a.send:
        _mark(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
