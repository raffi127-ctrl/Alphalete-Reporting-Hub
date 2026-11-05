"""Stations picture, every morning (Raf, #l10-alphalete thread, 2026-11-05).

Ask: "can we get our stations tab automatically posted on Alphalete sales and
our Alphalete A-Team chat everyday at 10:00 CEN". And: "If the AI can read up
where the reps names are posted that would be cool" -- the picture stops at the
last column and the last row that have a name, so empty stations and the empty
numbered rows underneath stay out of it. Stations made up only of road-trip
reps (the tab's 'Roadtrips' list) stay out too, like Raf's example.

Source: `Alphalete SALES BOARD 2025` -> tab `Stations`. Everything is found BY
LABEL in col A: the 'Where?' row says how wide the stations block is (it runs
until the first blank, so the 'Entry LVL Station' / 'Leaders Meetings' tables
further right are never read), the 'Running it' row is where names start, and
names end at the first row under it with nothing in col A.

Empty spots INSIDE the picture stay, the same as Raf's example (a numbered row
with nobody on it in the middle of the block). The picture is exported straight
from the live tab; nothing on the tab is written, so people can edit it all day.

LUCY 1 (its Messages app is in the A-Team chat, its Slack token posts as Lucy).
One send per room per day (lock file).

  python -m automations.stations_post.run            # dry run: saves the PNG
  python -m automations.stations_post.run --send     # really posts

Python 3.9-safe (Lucy runtime).
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

TAB = "Stations"
SLACK_CHANNEL = "C068PH3RFSM"                  # #alphalete-sales
# Resolved by NAME on every send (text_post.resolve_group raises on 0 or 2+
# matches, never guesses). Full name on the phone: "Alphalete A-Team Chat" +
# two flames; the match is "contains", so the emojis stay out. Raf moved
# everything OFF this chat on 2026-09-28; this one he asked for by name.
GROUPS = ["Alphalete A-Team Chat"]

OUT_DIR = REPO / "output" / "stations_post"
STATE_PATH = (Path.home() / ".config" / "recruiting-report"
              / "stations_post_sent.json")


def _ct_today() -> dt.date:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Chicago")).date()
    except Exception:  # noqa: BLE001
        return dt.date.today()


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _row_labeled(grid, label: str) -> int:
    """1-based row whose col A is `label`. Raises rather than guess a row."""
    for i, r in enumerate(grid, 1):
        if r and _norm(r[0]).rstrip("?").lower() == label:
            return i
    raise SystemExit("Stations: no '%s' row in col A -- template changed?" % label)


def _roadtrip_names(grid, after_row: int) -> set:
    """Lowercased names under the 'Roadtrips' header below the block. Raises if
    the header is gone: without it, road trips would leak into the picture."""
    for i in range(after_row, len(grid)):
        heads = [_norm(c).lower() for c in grid[i]]
        if "roadtrips" in heads:
            col = heads.index("roadtrips")
            return {_norm(r[col]).lower() for r in grid[i + 1:]
                    if col < len(r) and _norm(r[col])}
    raise SystemExit("Stations: no 'Roadtrips' list under the block -- template changed?")


def find_box(grid):
    """(last_row, last_col), 1-based: where the names stop. The block's width
    comes from the 'Where?' row; 'Running it' counts as a name, because a
    station with a leader and no reps yet is still a station.

    A station whose reps are ALL on the tab's 'Roadtrips' list doesn't count
    (Raf's example 2026-11-05 leaves them out; Eve confirmed), leader included.
    One office rep in the station keeps it in the picture."""
    where = _row_labeled(grid, "where")
    running = _row_labeled(grid, "running it")

    cols = grid[where - 1]
    width = 1
    while width < len(cols) and _norm(cols[width]):
        width += 1                 # col index (0-based) of the first blank

    block_end = running
    while block_end < len(grid) and grid[block_end] and _norm(grid[block_end][0]):
        block_end += 1             # first row with no number: the block is over

    away = _roadtrip_names(grid, block_end)
    last_row, last_col = 0, 0
    for j in range(1, width):
        reps = [(i, _norm(grid[i - 1][j])) for i in range(running + 1, block_end + 1)
                if j < len(grid[i - 1]) and _norm(grid[i - 1][j])]
        if reps and all(n.lower() in away for _, n in reps):
            continue
        leader = j < len(grid[running - 1]) and _norm(grid[running - 1][j])
        if reps or leader:
            last_col = j + 1
        if reps:
            last_row = max(last_row, reps[-1][0])
    if last_row <= running:
        # Only leaders, or nothing: not a board anyone can read their name on.
        raise SystemExit("Stations: no rep names on the tab -- nothing to post")
    return last_row, last_col


def caption(day: dt.date) -> str:
    return "Stations - %s %d/%d" % (day.strftime("%A"), day.month, day.day)


def render_photo(ws, last_row: int, last_col: int, day: dt.date) -> Path:
    from gspread.utils import rowcol_to_a1
    from automations.pnl_office.run import _token
    from automations.sales_boards import render as R

    img = R.export(SPREADSHEET_ID, ws.id,
                   "A1:%s" % rowcol_to_a1(last_row, last_col), _token())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / ("stations_%s.png" % day.isoformat())
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
    ap.add_argument("--send", action="store_true", help="really post (default: dry run)")
    ap.add_argument("--force", action="store_true", help="send even if already sent today")
    a = ap.parse_args(argv)

    day = _ct_today()
    # One mark per room: a retry after one room failed must not double-post
    # in the room that already got it.
    done = _sent() if a.send and not a.force else {}
    slack_key = "%s|slack" % day.isoformat()
    todo = [g for g in GROUPS if "%s|%s" % (day.isoformat(), g) not in done]
    if slack_key in done and not todo:
        print("already sent today (%s) - nothing to do" % done[slack_key])
        return 0

    from automations.recruiting_report.fill import open_by_key
    ws = open_by_key(SPREADSHEET_ID).worksheet(TAB)
    last_row, last_col = find_box(ws.get_values("A1:AH80"))
    png = render_photo(ws, last_row, last_col, day)
    print("picture: %s (names end at row %d, col %d)" % (png, last_row, last_col))

    text = caption(day)
    failed = 0
    if slack_key not in done:
        from automations.shared import slack_metrics_post as smp
        try:
            r = smp.post_reply_with_image(png, comment=text, channel_id=SLACK_CHANNEL,
                                          top_level=True, mirror=False, dry_run=not a.send,
                                          file_name=png.name)
            print("%s -> #alphalete-sales %s" % ("SLACK" if a.send else "PREVIEW", r))
            if a.send:
                _mark(slack_key)
        except Exception as e:  # noqa: BLE001 -- one room never blocks the other
            failed += 1
            print("FAILED #alphalete-sales: %s: %s" % (type(e).__name__, e))

    if not a.send and sys.platform != "darwin":
        # Resolving the iMessage room needs Messages (a Mac).
        print("PREVIEW -> %s (not checked - not a Mac)" % ", ".join(todo))
        return 0

    from automations.b2b_dispositions import text_post
    for grp in todo:
        try:
            r = text_post.send_to_group(grp, text, [png], dry_run=not a.send)
            print("%s -> %s (%s)" % ("TEXT" if a.send else "PREVIEW", grp,
                                     r.get("resolved_name")))
            if a.send:
                _mark("%s|%s" % (day.isoformat(), grp))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("FAILED %s: %s: %s" % (grp, type(e).__name__, e))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
