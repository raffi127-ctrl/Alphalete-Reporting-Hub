"""1st Round Scorecards Board -- every interviewer's average, by day and week.

Rafael, 2026-10-02: "a scorecard, similar to the sales board, of all the
interviewers": one row per interviewer, her average score each day Mon-Fri,
the week's average and how many interviews it's over. Best week first.

Read straight from the audit docs the daily post already writes
(1st rd Transcribes / <interviewer> / <yyyy-mm-dd> / <doc>): each doc has
"Scorecard: N / 100" and "Office: X". So the board needs no state of its own,
a --refresh that rewrote a doc shows up here, and any past week can be built.
Already-read docs are cached by modifiedTime, so a re-run only exports the new
ones. One tab per week ("WE 10.4", the Sunday it ends), newest first; a re-run rewrites
only that week's tab and puts it back in date order.

    python -m automations.first_round_scorecards.board                 # this week, print only
    python -m automations.first_round_scorecards.board --write         # ... and write the Sheet tab
    python -m automations.first_round_scorecards.board --week 2026-09-21 --write

BOARD_SHEET_ID is the real board (Eve, 2026-10-05: the test workbook became
the real one, same link, "TEST" dropped from its name).
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

from automations.first_round_scorecards import drive_auth, fathom, grade

BOARD_SHEET_ID = "1bPPYSr73QWwfzsW3BziyJyXysnj-segpCGUE1P447-s"  # 1st Round Scorecards Board (real)
FOLDER_MIME = "application/vnd.google-apps.folder"
CACHE = Path(__file__).resolve().parents[2] / "output" / "first_round_scorecards" / "board_cache.json"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")
_SCORE = re.compile(r"Scorecard:\s*(\d+)\s*/\s*100")
_OFFICE = re.compile(r"Office:\s*(.+?)\s*·")
# "3. Did she say the schedule is 9-5? — YES 🚩" (and "— NO" for a missed must-do)
_ITEM = re.compile(r"^\d+\.\s*(.+?)\s+—\s+(YES|NO)\b", re.M)
_TIME = re.compile(r"(\d{1,2}:\d{2} [AP]M)")
PARSE_VERSION = 2               # bump when parse_doc reads more: the cache re-reads every doc
# a thread with no name said in the intro lands under its Zoom ("ZOOM 13",
# "Drew's Zoom") or "Main Funnel": still on the board, so nothing is lost, but
# at the bottom -- it's a Zoom, not a person to coach
_NOT_A_PERSON = re.compile(r"^(ZOOM \d+|.*'s Zoom|Main Funnel)$", re.I)
# Camila 2026-10-05: under 50 red, exactly 50 blue, over 50 green
GREEN, BLUE_50, RED = (0.72, 0.88, 0.72), (0.74, 0.84, 0.96), (0.96, 0.72, 0.72)
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
    """{score, office, flags, missed, coaching} from an audit doc's text
    (score None = not found). flags = red flags that happened, missed =
    must-dos not done, both as the short labels of the Slack post."""
    s = _SCORE.search(text)
    o = _OFFICE.search(text)
    kinds = {q: (key, kind) for key, q, kind in grade.ITEMS}
    flags, missed = [], []
    for q, yes in _ITEM.findall(text):
        key, kind = kinds.get(q.strip(), (None, None))
        if kind == "red" and yes == "YES":
            flags.append(grade.SHORT[key])
        elif kind == "must" and yes == "NO":
            missed.append(grade.SHORT[key])
    coaching, inside = [], False
    for line in text.splitlines():
        if line.strip().startswith("Coaching points"):
            inside = True
        elif inside and line.lstrip().startswith("*"):
            coaching.append(line.lstrip()[1:].strip())
        elif inside and coaching:
            break
    return {"score": int(s.group(1)) if s else None,
            "office": o.group(1).strip() if o else "",
            "flags": flags, "missed": missed, "coaching": coaching}


def scores(week_of: dt.date, svc=None) -> List[Dict]:
    """[{interviewer, date, time, score, office, flags, missed, coaching}]
    for every audit doc that week."""
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
                if (not hit or hit.get("modified") != d["modifiedTime"]
                        or hit.get("v") != PARSE_VERSION):
                    text = svc.files().export(fileId=d["id"], mimeType="text/plain").execute()
                    hit = {"modified": d["modifiedTime"], "v": PARSE_VERSION,
                           **parse_doc(text.decode("utf-8", "replace"))}
                    cache[d["id"]] = hit
                if hit["score"] is None:
                    print(f"  no score in {person['name']}/{day['name']}/{d['name']} - left out")
                    continue
                t = _TIME.search(d["name"])
                out.append({"interviewer": person["name"], "date": day["name"],
                            "time": (dt.datetime.strptime(t.group(1), "%I:%M %p").strftime("%H:%M")
                                     if t else ""),
                            **{k: hit.get(k) or ([] if k in ("flags", "missed", "coaching") else "")
                               for k in ("score", "office", "flags", "missed", "coaching")}})
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return out


def _avg(xs: List[int]) -> Optional[int]:
    return round(sum(xs) / len(xs)) if xs else None


def _tally(labels: List[str]) -> str:
    """'pay different from the script ×3, retail ×1' -- most often first."""
    n: Dict[str, int] = {}
    for x in labels:
        n[x] = n.get(x, 0) + 1
    return ", ".join(f"{x} ×{c}" for x, c in sorted(n.items(), key=lambda kv: (-kv[1], kv[0])))


def _first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text.strip())
    return (m.group(1) if m else text).strip()


def table(week_of: dt.date, rows: List[Dict]) -> List[Dict]:
    """One line per interviewer: {name, offices, days: [avg|None]*5, counts,
    week, n, flags, missed, coaching}, best week first, the unnamed Zooms
    last. Camila 10/2: score, red flags and coaching tips in one place --
    flags/missed are the week's tallies, coaching = the first sentence of
    the top 2 points of her LATEST interview (what to work on now)."""
    by: Dict[str, Dict] = {}
    for r in sorted(rows, key=lambda r: (r["date"], r.get("time") or "")):
        p = by.setdefault(r["interviewer"], {"name": r["interviewer"], "per_day": {}, "offices": {},
                                             "flags": [], "missed": [], "coaching": []})
        p["per_day"].setdefault(r["date"], []).append(r["score"])
        if r["office"]:
            p["offices"][r["office"]] = p["offices"].get(r["office"], 0) + 1
        p["flags"] += r.get("flags") or []
        p["missed"] += r.get("missed") or []
        if r.get("coaching"):
            p["coaching"] = r["coaching"]          # rows are oldest first: the latest wins
    out = []
    for p in by.values():
        dates = [(week_of + dt.timedelta(days=i)).isoformat() for i in range(len(DAYS))]
        every = [s for d in dates for s in p["per_day"].get(d, [])]
        out.append({"name": p["name"],
                    "offices": ", ".join(sorted(p["offices"], key=lambda o: -p["offices"][o])),
                    "days": [_avg(p["per_day"].get(d, [])) for d in dates],
                    "counts": [len(p["per_day"].get(d, [])) for d in dates],
                    "week": _avg(every), "n": len(every),
                    "flags": _tally(p["flags"]) or "none",
                    "missed": _tally(p["missed"]) or "none",
                    "coaching": "\n".join(f"• {_first_sentence(c)}" for c in p["coaching"][:2])})
    out.sort(key=lambda p: (bool(_NOT_A_PERSON.match(p["name"])), -(p["week"] or 0), p["name"]))
    return out


def tab_name(week_of: dt.date) -> str:
    """'WE 10.4': the Sunday the week ends, like the other weekly reports' tabs."""
    sun = week_of + dt.timedelta(days=6)
    return f"WE {sun.month}.{sun.day}"


def tab_week(title: str, near: dt.date) -> Optional[dt.date]:
    """'WE 10.4' -> that week's Monday (the year closest to `near`), else None."""
    m = re.fullmatch(r"WE (\d{1,2})\.(\d{1,2})", title.strip())
    if not m:
        return None
    try:
        suns = [dt.date(y, int(m.group(1)), int(m.group(2)))
                for y in (near.year - 1, near.year, near.year + 1)]
    except ValueError:
        return None
    return min(suns, key=lambda d: abs((d - near).days)) - dt.timedelta(days=6)


def tab_index(week_of: dt.date, titles: List[str]) -> int:
    """Newest week first: this week's tab goes after every newer week's tab
    (so writing an old week doesn't push the current one off the front)."""
    return sum(1 for t in titles if t != tab_name(week_of)
               and (tab_week(t, week_of) or dt.date.min) > week_of)


def values(week_of: dt.date, lines: List[Dict]) -> List[List]:
    fri = week_of + dt.timedelta(days=4)
    head = ["#", "Interviewer", "Office"] + [
        f"{d} {(week_of + dt.timedelta(days=i)):%m/%d}" for i, d in enumerate(DAYS)
    ] + ["Week Avg", "Interviews", "🚩 Red flags (week)", "Most missed (week)",
         "Coaching tips (latest interview)"]
    every = [(p["week"], p["n"]) for p in lines if p["n"]]
    team = round(sum(w * n for w, n in every) / sum(n for _, n in every)) if every else ""
    out = [[f"1st Round Scorecards — Week of {week_of:%b} {week_of.day} – {fri:%b} {fri.day}, {fri.year}"],
           ["Average score per interview (out of 100). Over 50 green · 50 blue · under 50 red. "
            "Each name's audits are in 1st rd Transcribes / <name>."],
           head]
    for i, p in enumerate(lines, 1):
        out.append([i, p["name"], p["offices"]] + ["" if a is None else a for a in p["days"]]
                   + [p["week"], p["n"], p["flags"], p["missed"], p["coaching"]])
    out.append(["", "TEAM", ""] + [""] * len(DAYS) + [team, sum(p["n"] for p in lines), "", "", ""])
    return out


def _color(v) -> Optional[tuple]:
    if not isinstance(v, int):
        return None
    return GREEN if v > 50 else (BLUE_50 if v == 50 else RED)


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

    def cell(v, *, bold=False, bg=None, center=False, size=None, fg=None, italic=False,
             wrap=False):
        text = {"bold": bold, "italic": italic}
        if size:
            text["fontSize"] = size
        if fg:
            text["foregroundColor"] = rgb(fg)
        fmt = {"textFormat": text, "verticalAlignment": "MIDDLE",
               "horizontalAlignment": "CENTER" if center else "LEFT",
               "wrapStrategy": "WRAP" if wrap else "OVERFLOW_CELL"}
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
    week_col = 3 + len(DAYS)                 # the day averages sit between 3 and here
    text_from = week_col + 2                 # red flags, most missed, coaching: wrapped text
    for j, line in enumerate(grid[3:]):
        team = line[1] == "TEAM"
        # every other row light gray, so a long list stays easy to follow
        band = TEAM_BG if team else (BAND if j % 2 else WHITE)
        rows.append({"values": [cell(v, bold=team or i in (1, week_col),
                                     center=i not in (1, 2) and i < text_from,
                                     wrap=i >= text_from,
                                     bg=(_color(v) if 3 <= i <= week_col else None) or band)
                                for i, v in enumerate(line)]})
    thin = {"style": "SOLID", "color": rgb((0.80, 0.80, 0.80))}
    edge = {"style": "SOLID_MEDIUM", "color": rgb(NAVY)}
    widths = [40, 150, 240] + [85] * len(DAYS) + [95, 95, 230, 230, 420]
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
                "range": {"sheetId": gid, "dimension": "ROWS", "startIndex": 2, "endIndex": 3},
                "properties": {"pixelSize": 30}, "fields": "pixelSize"}},
            # rows grow with the wrapped coaching text
            {"autoResizeDimensions": {"dimensions": {
                "sheetId": gid, "dimension": "ROWS", "startIndex": 3, "endIndex": nrow}}}]
    reqs += [{"updateDimensionProperties": {
        "range": {"sheetId": gid, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
        "properties": {"pixelSize": w}, "fields": "pixelSize"}} for i, w in enumerate(widths)]
    svc.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": reqs}).execute()
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={gid}"


# ---- "Same person?" -------------------------------------------------------
# The interviewer's name comes from the intro in the recording, and the
# transcript mishears it: "Eva" one day, "Iva" the next, same office -> two
# rows with half a week each. Lucy lists the likely pairs herself (same
# office, similar names); Camila or Perla only pick YES / NO (Eve, 2026-10-02:
# they say whether it's the same person, they don't build the list). A YES
# folds the second name into the first on every week's board. Rows are only
# ever appended -- an answer someone gave is never rewritten.
SAME_TAB = "Same person?"
SAME_HEAD = ["Name on the board", "Other name Lucy heard", "Office", "Interviews (first name)",
             "Interviews (other name)", "Same person?"]
SAME_SIMILAR = 0.5           # difflib ratio: Eva/Iva 0.67, Emilia/Evelia 0.67, Camila/Candela 0.62


def _sheets():
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=drive_auth.load_credentials(), cache_discovery=False)


def read_same(svc=None, sheet_id: str = BOARD_SHEET_ID) -> List[List[str]]:
    """The tab's answer rows ([] when the tab doesn't exist yet)."""
    svc = svc or _sheets()
    try:
        got = svc.spreadsheets().values().get(spreadsheetId=sheet_id,
                                              range=f"'{SAME_TAB}'!A3:F").execute()
    except Exception as exc:  # noqa: BLE001
        if "Unable to parse range" in str(exc):
            return []
        raise
    return [(r + [""] * 6)[:6] for r in got.get("values", [])]


def merges(answers: List[List[str]]) -> Dict[str, str]:
    """{other name: name it folds into} for every YES (chains resolved)."""
    out = {r[1].strip(): r[0].strip() for r in answers
           if r[5].strip().upper() == "YES" and r[0].strip() and r[1].strip()}
    for k in list(out):
        seen = {k}
        while out[k] in out and out[k] not in seen:
            seen.add(out[k])
            out[k] = out[out[k]]
    return out


def _plain(name: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", name)
                   if unicodedata.category(c) != "Mn").casefold().strip()


def apply_merges(rows: List[Dict], m: Dict[str, str]) -> List[Dict]:
    """YES answers first; then names that differ only by accents or capitals
    ('Ángela' / 'Angela') join on their own -- nobody needs to be asked."""
    rows = [{**r, "interviewer": m.get(r["interviewer"], r["interviewer"])} for r in rows]
    n: Dict[str, int] = {}
    for r in rows:
        n[r["interviewer"]] = n.get(r["interviewer"], 0) + 1
    main: Dict[str, str] = {}
    for name in sorted(n, key=lambda x: (-n[x], x)):
        main.setdefault(_plain(name), name)
    return [{**r, "interviewer": main[_plain(r["interviewer"])]} for r in rows]


def candidates(rows: List[Dict], answers: List[List[str]]) -> List[List]:
    """New pairs to ask about: two named interviewers (not a Zoom) who served
    the same office with similar names, not asked before in either order.
    The one with more interviews is the name kept."""
    import difflib
    asked = {frozenset((r[0].strip(), r[1].strip())) for r in answers}
    n: Dict[str, int] = {}
    offices: Dict[str, set] = {}
    for r in rows:
        if _NOT_A_PERSON.match(r["interviewer"]):
            continue
        n[r["interviewer"]] = n.get(r["interviewer"], 0) + 1
        if r["office"]:
            offices.setdefault(r["interviewer"], set()).add(r["office"])
    names = sorted(n, key=lambda x: (-n[x], x))
    out = []
    # each name is asked about ONCE, next to the busiest similar name above it
    # (Elfina 9 / Alfina 1 / Lucina 1 / Ulfina 1 = 3 rows, not every pair);
    # a YES chain folds the rest in (merges())
    for i, b in enumerate(names):
        best = None
        for a in names[:i]:
            shared = offices.get(a, set()) & offices.get(b, set())
            ratio = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
            if shared and ratio >= SAME_SIMILAR:
                best = (a, shared)
                break                              # names[] is busiest first
        if best and frozenset((best[0], b)) not in asked:
            a, shared = best
            out.append([a, b, ", ".join(sorted(shared)), n[a], n[b], ""])
            asked.add(frozenset((a, b)))
    return out


def write_same(new: List[List], svc=None, sheet_id: str = BOARD_SHEET_ID) -> None:
    """Make the tab if needed (last, with a YES/NO dropdown) and append `new`."""
    svc = svc or _sheets()
    meta = svc.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets.properties").execute()
    tabs = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    if SAME_TAB not in tabs:
        r = svc.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": [
            {"addSheet": {"properties": {"title": SAME_TAB, "index": len(tabs),
                                         "gridProperties": {"frozenRowCount": 2}}}}]}).execute()
        gid = r["replies"][0]["addSheet"]["properties"]["sheetId"]
        rgb = lambda c: dict(zip(("red", "green", "blue"), c))  # noqa: E731
        head = [{"userEnteredValue": {"stringValue": h},
                 "userEnteredFormat": {"backgroundColor": rgb(BLUE), "horizontalAlignment": "CENTER",
                                       "wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE",
                                       "textFormat": {"bold": True, "foregroundColor": rgb(WHITE)}}}
                for h in SAME_HEAD]
        title = [{"userEnteredValue": {"stringValue":
                  "Lucy heard these names in the same office and thinks they may be ONE person "
                  "(the recording misheard the name). Pick YES or NO in the last column. "
                  "YES = the board joins them under the first name."},
                  "userEnteredFormat": {"backgroundColor": rgb(NAVY), "wrapStrategy": "WRAP",
                                        "textFormat": {"bold": True, "foregroundColor": rgb(WHITE)}}}]
        svc.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": [
            {"updateCells": {"start": {"sheetId": gid, "rowIndex": 0, "columnIndex": 0},
                             "rows": [{"values": title}, {"values": head}], "fields": "*"}},
            {"mergeCells": {"range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1,
                                      "startColumnIndex": 0, "endColumnIndex": 6},
                            "mergeType": "MERGE_ALL"}},
            {"updateDimensionProperties": {"range": {"sheetId": gid, "dimension": "ROWS",
                                                     "startIndex": 0, "endIndex": 1},
                                           "properties": {"pixelSize": 48}, "fields": "pixelSize"}},
            {"setDataValidation": {"range": {"sheetId": gid, "startRowIndex": 2, "endRowIndex": 500,
                                             "startColumnIndex": 5, "endColumnIndex": 6},
                                   "rule": {"condition": {"type": "ONE_OF_LIST", "values": [
                                       {"userEnteredValue": "YES"}, {"userEnteredValue": "NO"}]},
                                       "showCustomUi": True, "strict": True}}},
            *[{"updateDimensionProperties": {"range": {"sheetId": gid, "dimension": "COLUMNS",
                                                       "startIndex": i, "endIndex": i + 1},
                                             "properties": {"pixelSize": w}, "fields": "pixelSize"}}
              for i, w in enumerate([170, 170, 240, 110, 110, 120])],
        ]}).execute()
    if new:
        svc.spreadsheets().values().append(
            spreadsheetId=sheet_id, range=f"'{SAME_TAB}'!A3:F", valueInputOption="RAW",
            insertDataOption="INSERT_ROWS", body={"values": new}).execute()


# the week's rows the last update() read: run.py lists the day's low scorers
# from them (every doc of the day, names already merged)
LAST_ROWS: List[Dict] = []


def update(day: dt.date, *, write_sheet: bool = True) -> str:
    week_of = monday(day)
    rows = scores(week_of)
    answers = read_same() if write_sheet else []
    rows = apply_merges(rows, merges(answers))
    global LAST_ROWS
    LAST_ROWS = rows
    grid = values(week_of, table(week_of, rows))
    for line in grid:
        print("  ".join("" if v is None else str(v) for v in line))
    if not write_sheet:
        return ""
    link = write(week_of, grid)
    new = candidates(rows, answers)
    for c in new:
        print(f"  same person? {c[0]} / {c[1]} ({c[2]})")
    write_same(new)
    return link


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
