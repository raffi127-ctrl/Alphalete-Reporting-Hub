"""1st Round Scorecards Board -- every interviewer's average, by day and week.

Rafael, 2026-10-02: "a scorecard, similar to the sales board, of all the
interviewers": one row per interviewer, her average score each day Mon-Fri,
the week's average and how many interviews it's over. Best week first.

Read straight from the audit docs the daily post already writes
(1st rd Transcribes / <interviewer> / <yyyy-mm-dd> / <doc>): each doc has
"Scorecard: N / 100" and "Office: X". So the board needs no state of its own,
a --refresh that rewrote a doc shows up here, and any past week can be built.
Already-read docs are cached by modifiedTime, so a re-run only exports the new
ones. One tab per week ("Week of Sep 28"), newest first; a re-run rewrites
only that week's tab and puts it back in date order.

    python -m automations.first_round_scorecards.board                 # this week, print only
    python -m automations.first_round_scorecards.board --write         # ... and write the Sheet tab
    python -m automations.first_round_scorecards.board --week 2026-09-21 --write

SANDBOX (Eve's rule for new reports): BOARD_SHEET_ID is the TEST workbook
until Eve says "use the real Sheet".
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.first_round_scorecards import drive_auth, fathom

BOARD_SHEET_ID = "1bPPYSr73QWwfzsW3BziyJyXysnj-segpCGUE1P447-s"  # TEST - 1st Round Scorecards Board
FOLDER_MIME = "application/vnd.google-apps.folder"
CACHE = Path(__file__).resolve().parents[2] / "output" / "first_round_scorecards" / "board_cache.json"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")
_SCORE = re.compile(r"Scorecard:\s*(\d+)\s*/\s*100")
_OFFICE = re.compile(r"Office:\s*(.+?)\s*·")
# a thread with no name said in the intro lands under its Zoom ("ZOOM 13",
# "Drew's Zoom") or "Main Funnel": still on the board, so nothing is lost, but
# at the bottom -- it's a Zoom, not a person to coach
_NOT_A_PERSON = re.compile(r"^(ZOOM \d+|.*'s Zoom|Main Funnel)$", re.I)
GREEN, YELLOW, RED = (0.72, 0.88, 0.72), (1.0, 0.90, 0.60), (0.96, 0.72, 0.72)
NAVY, BLUE, PALE = (0.12, 0.23, 0.42), (0.24, 0.40, 0.65), (0.91, 0.94, 0.98)
WHITE, BAND, TEAM_BG = (1, 1, 1), (0.94, 0.94, 0.94), (0.85, 0.89, 0.95)


def monday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def _kids(svc, parent: str, folders: bool) -> List[Dict]:
    q = (f"'{parent}' in parents and trashed = false and mimeType "
         f"{'=' if folders else '!='} '{FOLDER_MIME}'")
    out, tok = [], None
    while True:
        r = svc.files().list(q=q, fields="nextPageToken,files(id,name,modifiedTime)",
                             pageSize=1000, pageToken=tok).execute()
        out += r.get("files", [])
        tok = r.get("nextPageToken")
        if not tok:
            return out


def _cache() -> Dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def parse_doc(text: str) -> Dict:
    """{score, office} from an audit doc's text (score None = not found)."""
    s = _SCORE.search(text)
    o = _OFFICE.search(text)
    return {"score": int(s.group(1)) if s else None,
            "office": o.group(1).strip() if o else ""}


def scores(week_of: dt.date, svc=None) -> List[Dict]:
    """[{interviewer, date, score, office}] for every audit doc that week."""
    svc = svc or drive_auth.service()
    days = {(week_of + dt.timedelta(days=i)).isoformat() for i in range(len(DAYS))}
    cache = _cache()
    out = []
    for person in _kids(svc, drive_auth.AUDIT_FOLDER_ID, True):
        for day in _kids(svc, person["id"], True):
            if day["name"] not in days:
                continue
            for d in _kids(svc, day["id"], False):
                hit = cache.get(d["id"])
                if not hit or hit.get("modified") != d["modifiedTime"]:
                    text = svc.files().export(fileId=d["id"], mimeType="text/plain").execute()
                    hit = {"modified": d["modifiedTime"],
                           **parse_doc(text.decode("utf-8", "replace"))}
                    cache[d["id"]] = hit
                if hit["score"] is None:
                    print(f"  no score in {person['name']}/{day['name']}/{d['name']} - left out")
                    continue
                out.append({"interviewer": person["name"], "date": day["name"],
                            "score": hit["score"], "office": hit["office"]})
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return out


def _avg(xs: List[int]) -> Optional[int]:
    return round(sum(xs) / len(xs)) if xs else None


def table(week_of: dt.date, rows: List[Dict]) -> List[Dict]:
    """One line per interviewer: {name, offices, days: [avg|None]*5, counts,
    week, n}, best week first, the unnamed Zooms last."""
    by: Dict[str, Dict] = {}
    for r in rows:
        p = by.setdefault(r["interviewer"], {"name": r["interviewer"], "per_day": {}, "offices": {}})
        p["per_day"].setdefault(r["date"], []).append(r["score"])
        if r["office"]:
            p["offices"][r["office"]] = p["offices"].get(r["office"], 0) + 1
    out = []
    for p in by.values():
        dates = [(week_of + dt.timedelta(days=i)).isoformat() for i in range(len(DAYS))]
        every = [s for d in dates for s in p["per_day"].get(d, [])]
        out.append({"name": p["name"],
                    "offices": ", ".join(sorted(p["offices"], key=lambda o: -p["offices"][o])),
                    "days": [_avg(p["per_day"].get(d, [])) for d in dates],
                    "counts": [len(p["per_day"].get(d, [])) for d in dates],
                    "week": _avg(every), "n": len(every)})
    out.sort(key=lambda p: (bool(_NOT_A_PERSON.match(p["name"])), -(p["week"] or 0), p["name"]))
    return out


def tab_name(week_of: dt.date) -> str:
    return f"Week of {week_of:%b} {week_of.day}"


def tab_week(title: str, near: dt.date) -> Optional[dt.date]:
    """'Week of Sep 28' -> that Monday (the year closest to `near`), else None."""
    m = re.fullmatch(r"Week of (\w{3}) (\d{1,2})", title)
    if not m:
        return None
    try:
        days = [dt.datetime.strptime(f"{m.group(1)} {m.group(2)} {y}", "%b %d %Y").date()
                for y in (near.year - 1, near.year, near.year + 1)]
    except ValueError:
        return None
    return min(days, key=lambda d: abs((d - near).days))


def tab_index(week_of: dt.date, titles: List[str]) -> int:
    """Newest week first: this week's tab goes after every newer week's tab
    (so writing an old week doesn't push the current one off the front)."""
    return sum(1 for t in titles if t != tab_name(week_of)
               and (tab_week(t, week_of) or dt.date.min) > week_of)


def values(week_of: dt.date, lines: List[Dict]) -> List[List]:
    fri = week_of + dt.timedelta(days=4)
    head = ["#", "Interviewer", "Office"] + [
        f"{d} {(week_of + dt.timedelta(days=i)):%m/%d}" for i, d in enumerate(DAYS)
    ] + ["Week Avg", "Interviews"]
    every = [(p["week"], p["n"]) for p in lines if p["n"]]
    team = round(sum(w * n for w, n in every) / sum(n for _, n in every)) if every else ""
    out = [[f"1st Round Scorecards — Week of {week_of:%b} {week_of.day} – {fri:%b} {fri.day}, {fri.year}"],
           ["Average score per interview (out of 100). 90+ green · 70–89 yellow · under 70 red. "
            "Each name's audits are in 1st rd Transcribes / <name>."],
           head]
    for i, p in enumerate(lines, 1):
        out.append([i, p["name"], p["offices"]] + ["" if a is None else a for a in p["days"]]
                   + [p["week"], p["n"]])
    out.append(["", "TEAM", ""] + [""] * len(DAYS) + [team, sum(p["n"] for p in lines)])
    return out


def _color(v) -> Optional[tuple]:
    if not isinstance(v, int):
        return None
    return GREEN if v >= 90 else (YELLOW if v >= 70 else RED)


def write(week_of: dt.date, grid: List[List], sheet_id: str = BOARD_SHEET_ID) -> str:
    """(Re)write that week's tab, newest week first -> the tab's link."""
    from googleapiclient.discovery import build
    svc = build("sheets", "v4", credentials=drive_auth.load_credentials(), cache_discovery=False)
    name = tab_name(week_of)
    meta = svc.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets.properties").execute()
    tabs = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    gid = tabs.get(name)
    pos = tab_index(week_of, list(tabs))
    if gid is None:
        r = svc.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": [
            {"addSheet": {"properties": {"title": name, "index": pos,
                                         "gridProperties": {"frozenRowCount": 3}}}}]}).execute()
        gid = r["replies"][0]["addSheet"]["properties"]["sheetId"]
    ncol, nrow = len(grid[2]), len(grid)

    def rgb(c):
        return dict(zip(("red", "green", "blue"), c))

    def cell(v, *, bold=False, bg=None, center=False, size=None, fg=None, italic=False):
        text = {"bold": bold, "italic": italic}
        if size:
            text["fontSize"] = size
        if fg:
            text["foregroundColor"] = rgb(fg)
        fmt = {"textFormat": text, "verticalAlignment": "MIDDLE",
               "horizontalAlignment": "CENTER" if center else "LEFT"}
        if bg:
            fmt["backgroundColor"] = rgb(bg)
        val = {"numberValue": v} if isinstance(v, (int, float)) else {"stringValue": str(v)}
        return {"userEnteredValue": val, "userEnteredFormat": fmt}

    def rng(r0, r1, c0=0, c1=ncol):
        return {"sheetId": gid, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}

    rows = [{"values": [cell(grid[0][0], bold=True, size=14, fg=WHITE, bg=NAVY)]
             + [cell("", bg=NAVY)] * (ncol - 1)},
            {"values": [cell(grid[1][0], italic=True, fg=(0.35, 0.35, 0.35), bg=PALE)]
             + [cell("", bg=PALE)] * (ncol - 1)},
            {"values": [cell(h, bold=True, fg=WHITE, bg=BLUE, center=i not in (1, 2))
                        for i, h in enumerate(grid[2])]}]
    for j, line in enumerate(grid[3:]):
        team = line[1] == "TEAM"
        # every other row light gray, so a long list stays easy to follow
        band = TEAM_BG if team else (BAND if j % 2 else WHITE)
        rows.append({"values": [cell(v, bold=team or i in (1, ncol - 2), center=i not in (1, 2),
                                     bg=(_color(v) if 3 <= i < ncol - 1 else None) or band)
                                for i, v in enumerate(line)]})
    thin = {"style": "SOLID", "color": rgb((0.80, 0.80, 0.80))}
    edge = {"style": "SOLID_MEDIUM", "color": rgb(NAVY)}
    widths = [40, 150, 240] + [85] * len(DAYS) + [95, 95]
    reqs = [{"unmergeCells": {"range": {"sheetId": gid}}},
            {"updateCells": {"range": {"sheetId": gid}, "fields": "*"}},
            {"updateCells": {"start": {"sheetId": gid, "rowIndex": 0, "columnIndex": 0},
                             "rows": rows, "fields": "*"}},
            {"mergeCells": {"range": rng(0, 1), "mergeType": "MERGE_ALL"}},
            {"mergeCells": {"range": rng(1, 2), "mergeType": "MERGE_ALL"}},
            {"updateBorders": {"range": rng(2, nrow), "top": edge, "bottom": edge, "left": edge,
                               "right": edge, "innerHorizontal": thin, "innerVertical": thin}},
            {"updateBorders": {"range": rng(nrow - 1, nrow), "top": edge}},
            {"updateSheetProperties": {"properties": {"sheetId": gid, "index": pos,
                                                      "gridProperties": {"frozenRowCount": 3,
                                                                         "hideGridlines": True}},
                                       "fields": "index,gridProperties.frozenRowCount,"
                                                 "gridProperties.hideGridlines"}},
            {"updateDimensionProperties": {
                "range": {"sheetId": gid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 40}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {
                "range": {"sheetId": gid, "dimension": "ROWS", "startIndex": 2, "endIndex": nrow},
                "properties": {"pixelSize": 28}, "fields": "pixelSize"}}]
    reqs += [{"updateDimensionProperties": {
        "range": {"sheetId": gid, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
        "properties": {"pixelSize": w}, "fields": "pixelSize"}} for i, w in enumerate(widths)]
    svc.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": reqs}).execute()
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={gid}"


def update(day: dt.date, *, write_sheet: bool = True) -> str:
    week_of = monday(day)
    grid = values(week_of, table(week_of, scores(week_of)))
    for line in grid:
        print("  ".join("" if v is None else str(v) for v in line))
    return write(week_of, grid) if write_sheet else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_round_scorecards.board")
    ap.add_argument("--week", help="any day of the week, YYYY-MM-DD (default: this week)")
    ap.add_argument("--write", action="store_true", help="write the Sheet tab (default: print only)")
    args = ap.parse_args(argv)
    day = (dt.date.fromisoformat(args.week) if args.week
           else dt.datetime.now(dt.timezone.utc).astimezone(fathom.CT).date())
    link = update(day, write_sheet=args.write)
    print(link or "DRY-RUN: Sheet not written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
