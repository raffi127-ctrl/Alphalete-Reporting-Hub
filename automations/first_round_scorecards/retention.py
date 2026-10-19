"""2nd Rd Retention tab on the 1st Round Scorecards Board -- did the audits help?

Rafael, 2026-10-19 (#l10-alphalete, "AI 1st rd Auditor" thread): "a report that
shows us how the 2nd rd retention has increased or decreased on the team
because of this". Eve: keep it updating, not a one-time picture.

One row per week, newest on top: the team's average 1st round score (the TEAM
line of that week's 'WE m.d' tab) next to the team's 2nd round retention
(2nd rounds showed / booked) and the change from the week before, plus a line
chart of the retention. Rebuilt after every board update.

WHERE RETENTION COMES FROM -- ARS Management 2.0 -> 'Interviewers Retention
(Interviewer)': a stack of weekly blocks, newest on top, each one marked
'INTERVIEWERS RETENTION' in col C with its week in col A ('10/11' = the week
that STARTS Sunday 10/11). The team number is the sum of the block's
'2nd R SHOWED' over the sum of its '2nd R BOOKED' (columns found by header).
Two quirks of that tab, read as they are (it's not ours to fix):
  - some weeks have no header of their own: after a block's AVERAGES row the
    next week's rows just continue -> that is the week before;
  - the labels have no year: a label is the latest such date not after
    today (so '12/28' further down is last year's).
The block for a week appears the Monday after it closes, so the week being
graded now has no retention yet.

    python -m automations.first_round_scorecards.retention                  # print only
    python -m automations.first_round_scorecards.retention --write --sheet <copy id>
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.first_round_scorecards import board

ARS_SHEET = "1l4Q0SreuddKZrgXwb9MytF-EdPZH-H1hLsa69epq-n8"     # ARS Management 2.0
ARS_TAB = "Interviewers Retention (Interviewer)"
TAB = "2nd Rd Retention"
AUDITS_FROM = dt.date(2026, 9, 27)  # first week with audits (they started Thu Oct 1)
WEEKS = 16                          # rows shown
BOOKED, SHOWED = "2nd R BOOKED", "2nd R SHOWED"


def _num(x) -> Optional[float]:
    try:
        return float(str(x).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def _label(text: str, near: dt.date) -> Optional[dt.date]:
    """'10/11' -> the Sunday it names (the year that puts it closest to, and
    not after, `near`)."""
    try:
        m, d = (int(p) for p in text.strip().split("/")[:2])
        dates = [dt.date(y, m, d) for y in (near.year - 1, near.year)]
    except (ValueError, TypeError):
        return None
    past = [x for x in dates if x <= near]
    return max(past) if past else None


def parse(values: List[List[str]], near: dt.date) -> List[Dict]:
    """[{week: Sunday, booked, showed}] newest first, this year's run only."""
    weeks: List[Dict] = []
    cur, head, ended = None, None, False
    for r in values:
        r = list(r) + [""] * 30
        if "INTERVIEWERS RETENTION" in str(r[2]).upper():
            sun = _label(r[0], near)
            if sun is None or (weeks and sun >= weeks[-1]["week"]):
                break                               # dates must keep going back
            cur = {"week": sun, "booked": 0.0, "showed": 0.0}
            weeks.append(cur)
            head, ended = None, False
            continue
        if cur is None:
            continue
        first = str(r[0]).strip().upper()
        if first == "INTERVIEWER":
            head = [str(h).strip() for h in r]
            continue
        if first == "AVERAGES":
            ended = True
            continue
        if not head or BOOKED not in head or SHOWED not in head:
            continue
        if not (str(r[0]).strip() or str(r[1]).strip()):
            continue
        if ended:                                   # a week with no header: the one before
            cur = {"week": cur["week"] - dt.timedelta(days=7), "booked": 0.0, "showed": 0.0}
            weeks.append(cur)
            ended = False
        cur["booked"] += _num(r[head.index(BOOKED)]) or 0
        cur["showed"] += _num(r[head.index(SHOWED)]) or 0
    return [w for w in weeks if w["booked"]]


def rows(ret: List[Dict], scores: Dict[dt.date, Dict[str, Dict]], last: int = WEEKS) -> List[Dict]:
    """Newest first: {week, audits, score, booked, showed, pct, change}.
    The board's weeks are keyed by Monday; a retention week starts the Sunday before."""
    ret = sorted(ret, key=lambda w: w["week"])[-last - 1:]
    out, prev = [], None
    for w in ret:
        pct = 100 * w["showed"] / w["booked"]
        # before Oct 1 only the pilot (Valentina's Zoom) was graded: not a team score
        team = (scores.get(w["week"] + dt.timedelta(days=1), {}).get("TEAM", {}).get("avg")
                if w["week"] >= AUDITS_FROM else None)
        out.append({**w, "audits": w["week"] >= AUDITS_FROM, "score": team, "pct": pct,
                    "change": None if prev is None else pct - prev})
        prev = pct
    return list(reversed(out[-last:]))


def _pool(lines: List[Dict], audits: bool) -> Optional[float]:
    g = [x for x in lines if x["audits"] == audits]
    b = sum(x["booked"] for x in g)
    return 100 * sum(x["showed"] for x in g) / b if b else None


def values(lines: List[Dict]) -> List[List]:
    before, after = _pool(lines, False), _pool(lines, True)
    fmt = lambda p: "—" if p is None else f"{p:.1f}%"   # noqa: E731
    out = [["2nd Round Retention vs 1st Round Scores — did the audits help?"],
           [f"Retention = 2nd rounds showed ÷ booked, whole team. Before audits: {fmt(before)} · "
            f"Since audits (from the week of Sep 27): {fmt(after)}. A week shows up here the "
            "Monday after it ends. Source: ARS Management 2.0 → Interviewers Retention (Interviewer)."],
           ["Week (Sun–Sat)", "Audits?", "Team 1st round score", "2nd rds booked",
            "2nd rds showed", "2nd rd retention", "vs week before"]]
    for x in lines:
        sat = x["week"] + dt.timedelta(days=6)
        ch = x["change"]
        out.append([f"{x['week']:%b} {x['week'].day} – {sat:%b} {sat.day}",
                    "Yes" if x["audits"] else "No",
                    "" if x["score"] is None else x["score"],
                    int(x["booked"]), int(x["showed"]), round(x["pct"] / 100, 3),
                    "" if ch is None else ("▲ +" if ch > 0 else ("▼ " if ch < 0 else "= "))
                    + f"{ch:.1f} pts"])
    return out


def write(grid: List[List], sheet_id: str = board.BOARD_SHEET_ID, svc=None) -> str:
    """(Re)write the tab right after Week over Week, with a line chart."""
    svc = svc or board._sheets()
    meta = svc.spreadsheets().get(spreadsheetId=sheet_id,
                                  fields="sheets(properties,charts.chartId)").execute()
    tabs = {s["properties"]["title"]: s for s in meta["sheets"]}
    pos = 1 if board.WOW_TAB in tabs else 0
    if TAB in tabs:
        gid = tabs[TAB]["properties"]["sheetId"]
        old_charts = [c["chartId"] for c in tabs[TAB].get("charts", [])]
    else:
        r = svc.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": [
            {"addSheet": {"properties": {"title": TAB, "index": pos,
                                         "gridProperties": {"frozenRowCount": 3}}}}]}).execute()
        gid, old_charts = r["replies"][0]["addSheet"]["properties"]["sheetId"], []
    ncol, nrow = len(grid[2]), len(grid)
    rgb = lambda c: dict(zip(("red", "green", "blue"), c))  # noqa: E731
    up, down = (0.05, 0.50, 0.15), (0.75, 0.10, 0.10)
    AUD = (0.91, 0.94, 0.98)

    def cell(v, *, bold=False, bg=None, center=False, size=None, fg=None, italic=False,
             wrap=False, pct=False):
        text = {"bold": bold, "italic": italic}
        if size:
            text["fontSize"] = size
        if fg:
            text["foregroundColor"] = rgb(fg)
        f = {"textFormat": text, "verticalAlignment": "MIDDLE",
             "horizontalAlignment": "CENTER" if center else "LEFT",
             "wrapStrategy": "WRAP" if wrap else "OVERFLOW_CELL"}
        if bg:
            f["backgroundColor"] = rgb(bg)
        if pct:
            f["numberFormat"] = {"type": "PERCENT", "pattern": "0.0%"}
        val = {"numberValue": v} if isinstance(v, (int, float)) else {"stringValue": str(v)}
        return {"userEnteredValue": val, "userEnteredFormat": f}

    def rng(r0, r1, c0=0, c1=ncol):
        return {"sheetId": gid, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}

    out = [{"values": [cell(grid[0][0], bold=True, size=14, fg=board.WHITE, bg=board.NAVY)]
            + [cell("", bg=board.NAVY)] * (ncol - 1)},
           {"values": [cell(grid[1][0], italic=True, fg=(0.35, 0.35, 0.35), bg=board.PALE,
                            wrap=True)] + [cell("", bg=board.PALE)] * (ncol - 1)},
           {"values": [cell(h, bold=True, fg=board.WHITE, bg=board.BLUE, center=i > 0, wrap=True)
                       for i, h in enumerate(grid[2])]}]
    for line in grid[3:]:
        band = AUD if line[1] == "Yes" else board.WHITE      # the audit weeks stand out
        vals = []
        for i, v in enumerate(line):
            fg = None
            if i == 6 and isinstance(v, str):
                fg = up if v.startswith("▲") else (down if v.startswith("▼") else None)
            vals.append(cell(v, center=i > 0, bold=i in (5, 6), fg=fg, pct=i == 5,
                             bg=(board._color(v) if i == 2 else None) or band))
        out.append({"values": vals})
    thin = {"style": "SOLID", "color": rgb((0.80, 0.80, 0.80))}
    edge = {"style": "SOLID_MEDIUM", "color": rgb(board.NAVY)}
    widths = [150, 80, 120, 110, 110, 120, 130]
    reqs = [{"deleteEmbeddedObject": {"objectId": c}} for c in old_charts]
    reqs += [{"unmergeCells": {"range": {"sheetId": gid}}},
             {"updateCells": {"range": {"sheetId": gid}, "fields": "*"}},
             {"updateCells": {"start": {"sheetId": gid, "rowIndex": 0, "columnIndex": 0},
                              "rows": out, "fields": "*"}},
             {"mergeCells": {"range": rng(0, 1), "mergeType": "MERGE_ALL"}},
             {"mergeCells": {"range": rng(1, 2), "mergeType": "MERGE_ALL"}},
             {"updateBorders": {"range": rng(2, nrow), "top": edge, "bottom": edge, "left": edge,
                                "right": edge, "innerHorizontal": thin, "innerVertical": thin}},
             {"updateSheetProperties": {"properties": {"sheetId": gid, "index": pos,
                                                       "gridProperties": {"frozenRowCount": 3,
                                                                          "hideGridlines": True}},
                                        "fields": "index,gridProperties.frozenRowCount,"
                                                  "gridProperties.hideGridlines"}},
             *[{"updateDimensionProperties": {
                 "range": {"sheetId": gid, "dimension": "ROWS", "startIndex": a, "endIndex": a + 1},
                 "properties": {"pixelSize": px}, "fields": "pixelSize"}}
               for a, px in ((0, 40), (1, 52), (2, 40))]]
    reqs += [{"updateDimensionProperties": {
        "range": {"sheetId": gid, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
        "properties": {"pixelSize": w}, "fields": "pixelSize"}} for i, w in enumerate(widths)]
    if nrow > 3:
        src = lambda c: {"sourceRange": {"sources": [rng(2, nrow, c, c + 1)]}}  # noqa: E731
        reqs.append({"addChart": {"chart": {
            "spec": {"title": "2nd round retention by week",
                     "basicChart": {
                         "chartType": "LINE", "legendPosition": "NO_LEGEND", "headerCount": 1,
                         "axis": [{"position": "BOTTOM_AXIS", "title": "Week"},
                                  {"position": "LEFT_AXIS", "title": "Retention",
                                   # zoomed in: the weekly moves are a few points
                                   "viewWindowOptions": {"viewWindowMode": "EXPLICIT",
                                                         "viewWindowMin": 0.5,
                                                         "viewWindowMax": 0.7}}],
                         "domains": [{"domain": src(0), "reversed": True}],
                         "series": [{"series": src(5), "targetAxis": "LEFT_AXIS",
                                     "color": rgb((0.16, 0.47, 0.84)),
                                     "pointStyle": {"shape": "CIRCLE", "size": 6}}]}},
            "position": {"overlayPosition": {
                "anchorCell": {"sheetId": gid, "rowIndex": 2, "columnIndex": ncol + 1},
                "widthPixels": 640, "heightPixels": 360}}}}})
    svc.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": reqs}).execute()
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={gid}"


def update(sheet_id: str = board.BOARD_SHEET_ID, write_sheet: bool = True,
           today: Optional[dt.date] = None) -> str:
    today = today or dt.date.today()
    svc = board._sheets()
    got = svc.spreadsheets().values().get(spreadsheetId=ARS_SHEET,
                                          range=f"'{ARS_TAB}'!A1:Z").execute()
    lines = rows(parse(got.get("values", []), today), board.read_weeks(svc, sheet_id, today))
    grid = values(lines)
    for line in grid:
        print("  ".join(str(v) for v in line))
    return write(grid, sheet_id, svc) if write_sheet else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_round_scorecards.retention")
    ap.add_argument("--write", action="store_true", help="write the tab (default: print only)")
    ap.add_argument("--sheet", default=board.BOARD_SHEET_ID, help="board workbook id (a test copy)")
    a = ap.parse_args(argv)
    print(update(a.sheet, a.write) or "DRY-RUN: Sheet not written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
