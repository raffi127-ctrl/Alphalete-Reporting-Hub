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
only that week's tab and puts it back in date order. In front of them, a
"Week over Week" tab (Rafael, 2026-10-19: "like the focus report, to see WoW if
they're getting better scores or worse"): one row per interviewer, her Week
Avg from each weekly tab side by side, and the change from her week before.

    python -m automations.first_round_scorecards.board                 # this week, print only
    python -m automations.first_round_scorecards.board --write         # ... and write the Sheet tab
    python -m automations.first_round_scorecards.board --week 2026-09-21 --write
    python -m automations.first_round_scorecards.board --wow-only --sheet <copy id>   # just the WoW tab

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
                out.append({"interviewer": person["name"], "date": day["name"], "doc": d["id"],
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


# ---- "Week over Week" -----------------------------------------------------
# Rafael 2026-10-19: see week over week whether each interviewer is getting
# better or worse, like the Focus Report. Built from the weekly tabs' own
# "Week Avg" / "Interviews" columns (found by header, not position), so it
# shows exactly what each week's tab shows and needs no extra Drive reads.
WOW_TAB = "Week over Week"
WOW_WEEKS = 8                # most recent weekly tabs shown, oldest left
WOW_REGULAR = 3              # fewer interviews than this in those weeks: listed below the regulars


def read_weeks(svc=None, sheet_id: str = BOARD_SHEET_ID,
               near: Optional[dt.date] = None) -> Dict[dt.date, Dict[str, Dict]]:
    """{week Monday: {interviewer: {office, avg, n}}} from every 'WE m.d' tab;
    the TEAM line is kept under "TEAM"."""
    svc = svc or _sheets()
    near = near or dt.date.today()
    meta = svc.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets.properties").execute()
    weeks = {t: tab_week(t, near) for t in (s["properties"]["title"] for s in meta["sheets"])}
    weeks = {t: w for t, w in weeks.items() if w}
    if not weeks:
        return {}
    got = svc.spreadsheets().values().batchGet(
        spreadsheetId=sheet_id, ranges=[f"'{t}'!A3:Z" for t in weeks]).execute()
    out: Dict[dt.date, Dict[str, Dict]] = {}
    for (title, week), vr in zip(weeks.items(), got.get("valueRanges", [])):
        grid = vr.get("values", [])
        if not grid:
            continue
        head = [h.strip() for h in grid[0]]
        try:
            c_name, c_avg, c_n = (head.index("Interviewer"), head.index("Week Avg"),
                                  head.index("Interviews"))
        except ValueError:
            print(f"  {title}: no Interviewer / Week Avg / Interviews header - left out")
            continue
        c_off = head.index("Office") if "Office" in head else None
        people: Dict[str, Dict] = {}
        for row in grid[1:]:
            row = row + [""] * (len(head) - len(row))
            name = str(row[c_name]).strip()
            try:
                avg, n = int(float(row[c_avg])), int(float(row[c_n] or 0))
            except (TypeError, ValueError):
                continue
            if name:
                people[name] = {"office": str(row[c_off]).strip() if c_off is not None else "",
                                "avg": avg, "n": n}
        out[week] = people
    return out


def wow_lines(weeks: Dict[dt.date, Dict[str, Dict]], m: Optional[Dict[str, str]] = None,
              last: int = WOW_WEEKS):
    """(shown week Mondays oldest first, lines, team avgs). A line is
    {name, office, avgs: [avg|None per week], n, change}: change = her latest
    week with a score minus the week with a score before it (None with only
    one). Names a "Same person?" YES folded are joined (weighted by
    interviews). Best latest score first; names heard only once or twice
    (mostly a misheard name) under the regulars, the unnamed Zooms last."""
    m = m or {}
    shown = sorted(weeks)[-last:]
    by: Dict[str, Dict] = {}
    for i, w in enumerate(shown):
        for raw, p in weeks[w].items():
            if raw == "TEAM":
                continue
            name = m.get(raw, raw)
            b = by.setdefault(name, {"name": name, "office": "", "sum": [0] * len(shown),
                                     "cnt": [0] * len(shown), "n": 0})
            k = max(p["n"], 1)
            b["sum"][i] += p["avg"] * k
            b["cnt"][i] += k
            b["n"] += p["n"]
            if p["office"]:
                b["office"] = p["office"]            # oldest first: the latest office wins
    lines = []
    for b in by.values():
        avgs = [round(s / c) if c else None for s, c in zip(b["sum"], b["cnt"])]
        had = [a for a in avgs if a is not None]
        lines.append({"name": b["name"], "office": b["office"], "avgs": avgs, "n": b["n"],
                      "change": had[-1] - had[-2] if len(had) >= 2 else None,
                      "latest": had[-1] if had else 0})
    lines.sort(key=lambda p: (bool(_NOT_A_PERSON.match(p["name"])), p["n"] < WOW_REGULAR,
                              -p["latest"], p["name"]))
    team = [weeks[w].get("TEAM", {}).get("avg") for w in shown]
    return shown, lines, team


def _change(c: Optional[int]) -> str:
    if c is None:
        return ""
    return f"▲ +{c}" if c > 0 else (f"▼ {c}" if c < 0 else "= 0")


def wow_values(shown: List[dt.date], lines: List[Dict], team: List) -> List[List]:
    head = ["#", "Interviewer", "Office"] + [tab_name(w) for w in shown] + [
        "Change vs her week before", "Interviews (all weeks shown)"]
    out = [["1st Round Scorecards — Week over Week"],
           ["Each interviewer's weekly average score (out of 100), oldest week left, newest "
            "right — the newest week is still filling in. Over 50 green · 50 blue · under 50 red. "
            "▲ = better than her week before, ▼ = worse."],
           head]
    for i, p in enumerate(lines, 1):
        out.append([i, p["name"], p["office"]] + ["" if a is None else a for a in p["avgs"]]
                   + [_change(p["change"]), p["n"]])
    out.append(["", "TEAM", ""] + ["" if a is None else a for a in team]
               + ["", sum(p["n"] for p in lines)])
    return out


def write_wow(grid: List[List], sheet_id: str = BOARD_SHEET_ID, svc=None) -> str:
    """(Re)write the Week over Week tab as the FIRST tab -> its link."""
    svc = svc or _sheets()
    meta = svc.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets.properties").execute()
    tabs = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    gid = tabs.get(WOW_TAB)
    if gid is None:
        r = svc.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": [
            {"addSheet": {"properties": {"title": WOW_TAB, "index": 0,
                                         "gridProperties": {"frozenRowCount": 3}}}}]}).execute()
        gid = r["replies"][0]["addSheet"]["properties"]["sheetId"]
    ncol, nrow = len(grid[2]), len(grid)
    nweeks = ncol - 5
    change_col = 3 + nweeks
    rgb = lambda c: dict(zip(("red", "green", "blue"), c))  # noqa: E731

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

    up, down = (0.05, 0.50, 0.15), (0.75, 0.10, 0.10)
    rows = [{"values": [cell(grid[0][0], bold=True, size=14, fg=WHITE, bg=NAVY)]
             + [cell("", bg=NAVY)] * (ncol - 1)},
            {"values": [cell(grid[1][0], italic=True, fg=(0.35, 0.35, 0.35), bg=PALE, wrap=True)]
             + [cell("", bg=PALE)] * (ncol - 1)},
            {"values": [cell(h, bold=True, fg=WHITE, bg=BLUE, center=i not in (1, 2), wrap=True)
                        for i, h in enumerate(grid[2])]}]
    for j, line in enumerate(grid[3:]):
        team = line[1] == "TEAM"
        band = TEAM_BG if team else (BAND if j % 2 else WHITE)
        vals = []
        for i, v in enumerate(line):
            fg = None
            if i == change_col and isinstance(v, str):
                fg = up if v.startswith("▲") else (down if v.startswith("▼") else None)
            vals.append(cell(v, bold=team or i in (1, change_col), center=i not in (1, 2), fg=fg,
                             bg=(_color(v) if 3 <= i < change_col else None) or band))
        rows.append({"values": vals})
    thin = {"style": "SOLID", "color": rgb((0.80, 0.80, 0.80))}
    edge = {"style": "SOLID_MEDIUM", "color": rgb(NAVY)}
    widths = [40, 150, 240] + [80] * nweeks + [130, 110]
    reqs = [{"unmergeCells": {"range": {"sheetId": gid}}},
            {"updateCells": {"range": {"sheetId": gid}, "fields": "*"}},
            {"updateCells": {"start": {"sheetId": gid, "rowIndex": 0, "columnIndex": 0},
                             "rows": rows, "fields": "*"}},
            {"mergeCells": {"range": rng(0, 1), "mergeType": "MERGE_ALL"}},
            {"mergeCells": {"range": rng(1, 2), "mergeType": "MERGE_ALL"}},
            {"updateBorders": {"range": rng(2, nrow), "top": edge, "bottom": edge, "left": edge,
                               "right": edge, "innerHorizontal": thin, "innerVertical": thin}},
            {"updateBorders": {"range": rng(nrow - 1, nrow), "top": edge}},
            {"updateSheetProperties": {"properties": {"sheetId": gid, "index": 0,
                                                      "gridProperties": {"frozenRowCount": 3,
                                                                         "hideGridlines": True}},
                                       "fields": "index,gridProperties.frozenRowCount,"
                                                 "gridProperties.hideGridlines"}},
            *[{"updateDimensionProperties": {
                "range": {"sheetId": gid, "dimension": "ROWS", "startIndex": a, "endIndex": a + 1},
                "properties": {"pixelSize": px}, "fields": "pixelSize"}}
              for a, px in ((0, 40), (1, 36), (2, 40))]]
    reqs += [{"updateDimensionProperties": {
        "range": {"sheetId": gid, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
        "properties": {"pixelSize": w}, "fields": "pixelSize"}} for i, w in enumerate(widths)]
    svc.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": reqs}).execute()
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={gid}"


def update_wow(answers: Optional[List[List[str]]] = None, sheet_id: str = BOARD_SHEET_ID,
               write_sheet: bool = True) -> str:
    svc = _sheets()
    if answers is None:
        answers = read_same(svc, sheet_id)
    grid = wow_values(*wow_lines(read_weeks(svc, sheet_id), merges(answers)))
    for line in grid:
        print("  ".join("" if v is None else str(v) for v in line))
    return write_wow(grid, sheet_id, svc) if write_sheet else ""


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
    try:                                   # the WoW tab never stops the weekly board
        update_wow(answers)
    except Exception as exc:  # noqa: BLE001
        print(f"  Week over Week tab not updated: {exc}")
    try:                                   # nor does the 2nd round retention tab
        from automations.first_round_scorecards import retention
        retention.update()
    except Exception as exc:  # noqa: BLE001
        print(f"  2nd Rd Retention tab not updated: {exc}")
    return link


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_round_scorecards.board")
    ap.add_argument("--week", help="any day of the week, YYYY-MM-DD (default: this week)")
    ap.add_argument("--write", action="store_true", help="write the Sheet tab (default: print only)")
    ap.add_argument("--wow-only", action="store_true",
                    help="only (re)build the Week over Week tab from the weekly tabs")
    ap.add_argument("--sheet", default=BOARD_SHEET_ID, help="--wow-only: workbook id (a test copy)")
    args = ap.parse_args(argv)
    if args.wow_only:
        print(update_wow(sheet_id=args.sheet, write_sheet=args.write)
              or "DRY-RUN: Sheet not written")
        return 0
    day = (dt.date.fromisoformat(args.week) if args.week
           else dt.datetime.now(dt.timezone.utc).astimezone(fathom.CT).date())
    link = update(day, write_sheet=args.write)
    print(link or "DRY-RUN: Sheet not written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
