"""Ad Scorecard from AppStream's Source Report (Raf 2026-10-10, Slack thread
"Source Reporting Data"):

  "The report is based off how ads titles the AI found? ... Wouldn't we rather
  just have it use source report? Using source report you could also have it
  pull what account it's on" -> Carlos's Loom (10/13): the ad comes straight
  from AppStream ('Ad (Subject Line)'), no reading photos.

Same idea as the photo-based Ad Scorecard (ad_photo_threads/scorecard.py):
one row per ad, LAST WEEK + THIS MONTH, coloured by 2nd-round retention. The
numbers are AppStream's own: the Ad Sales Board already pulls the Source
Report (p=702) per office every week into the hidden 'Ad Sales Data' tab, so
this reads that tab -- no extra AppStream login. One row per account + ad +
city: the account is the Indeed inbox the ad posts from.

PREVIEW ONLY for now (PNG to output/, nothing posted or written):
    python -m automations.ad_source_scorecard.run                       # Rafael, last full week
    python -m automations.ad_source_scorecard.run --manager "Carlos Hidalgo" --date 2026-10-18

Python 3.9-safe (the mini runs it).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image, ImageDraw

from automations.ad_photo_threads.scorecard import (
    BANDS, INK, LEGEND_H, MUTED, PAD, ROW_H, _fit, _font, band)
from automations.ad_sales_board import sheet

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "output" / "ad_source_scorecard"

# 'Ad Sales Data' headers this reads -- found by NAME, never by position.
H = {"manager": "Manager", "account": "Account", "title": "Ad Title",
     "city": "City", "week": "Week Start", "apps": "Pull",
     "scl": "To Call List", "names": "Names", "b1": "FR Booked", "s1": "FR Showed",
     "b2": "SR Booked", "s2": "SR Showed", "day1": "Day1 Showed"}
NUMS = ("apps", "scl", "b1", "s1", "b2", "s2", "day1")
# A row only counts as an ad when someone from it got somewhere. The inbox
# also catches newsletters, Indeed codes, tickets... (Pull/Removed only).
FUNNEL = ("scl", "b1", "s1", "b2", "s2", "day1")

COLS = [("#", 40), ("Account", 170), ("Ad title", 380), ("City", 150),
        ("Apps", 65), ("To call list", 105), ("1st booked", 95),
        ("1st showed", 100), ("Avg stars", 90), ("2nd booked", 100), ("2nd showed", 100),
        ("2nd retention", 120), ("Day 1", 70)]
LEFT = {1, 2, 3}
# Eve 10/19: must not be mistaken for the photo Ad Scorecard (navy headers).
# This one wears purple + an "APPSTREAM" tag; retention colours stay the same
# so green/red mean the same thing on both.
HEAD_BG = (91, 44, 131)
ALT_BG = (247, 244, 251)
TOTAL_BG = (234, 226, 244)
TAG = "APPSTREAM SOURCE REPORT"


def _int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def load(manager: str) -> List[dict]:
    """Every per-ad row of `manager` on 'Ad Sales Data' (band, TOTAL and
    unmatched-names rows have no account and are skipped)."""
    vals = sheet.get_values(sheet.session(), sheet.data_range("A1:BZ"))
    head = vals[0]
    idx = {k: head.index(name) for k, name in H.items()}
    out = []
    for raw in vals[1:]:
        r = raw + [""] * (len(head) - len(raw))
        if r[idx["manager"]] != manager or not str(r[idx["account"]]).strip():
            continue
        try:
            week = dt.date.fromisoformat(str(r[idx["week"]])[:10])
        except ValueError:
            continue
        row = {k: str(r[idx[k]]).strip() for k in ("account", "title", "city")}
        row["names"] = [n.strip() for n in str(r[idx["names"]]).split(",") if n.strip()]
        row["week"] = week
        row.update({k: _int(r[idx[k]]) for k in NUMS})
        if any(row[k] for k in FUNNEL):
            out.append(row)
    return out


# ---- stars (Eve 10/19) -------------------------------------------------------
# AppStream keeps no rating. The interviewers type one per candidate in the
# ARS sheet ('Star Rating', same column the photo Ad Scorecard averages), so
# each ad's call-list names are looked up there. A name spelled differently in
# the two places simply has no star -- the column says how many were rated.
def _fold(s: str) -> str:
    from automations.ad_photo_threads.collect import _fold as fold
    return fold(s)


# manager -> their tabs in the ARS sheet (ad_photo_threads.config SOURCES /
# RAF_FUNNEL_2 / RAF_FUNNEL_3). Another manager = another line.
STAR_TABS = {"Rafael Hidalgo": ["Rafael Hidalgo", "Raf Hidalgo 2nd funnel",
                                "Raf Hidalgo 3rd Funnel"]}


def load_stars(manager: str) -> Dict[str, int]:
    """folded full name -> star rating, from every ARS tab of `manager`'s
    office(s) (Raf: funnels 1-3). Latest typed rating wins."""
    from automations.ad_photo_threads import collect, config
    from automations.ad_photo_threads.post import _star_num
    from automations.recruiting_report.fill import open_by_key
    tabs = STAR_TABS.get(manager, [])
    out: Dict[str, int] = {}
    if not tabs:
        return out
    sh = open_by_key(config.SHEET_ID)
    for tab in tabs:
        for r in collect._read_tab(sh, tab):
            n = _star_num(r.get(config.COL_STARS, ""))
            if n and 1 <= n <= 5 and r.get(config.COL_NAME):
                out[_fold(r[config.COL_NAME])] = n
    return out


def table(rows: List[dict], start: dt.date, end: dt.date,
          stars: Optional[Dict[str, int]] = None) -> tuple:
    """(ad rows ranked, total) for the weeks STARTING in [start, end]."""
    stars = stars or {}
    acc: Dict[tuple, dict] = {}
    for r in rows:
        if not start <= r["week"] <= end:
            continue
        key = (r["account"], r["title"], r["city"])
        a = acc.setdefault(key, dict(zip(("account", "title", "city"), key),
                                     stars=[], **{k: 0 for k in NUMS}))
        for k in NUMS:
            a[k] += r[k]
        a["stars"] += [stars[f] for f in map(_fold, r["names"]) if f in stars]
    ads = sorted(acc.values(), key=_rank)
    total = {"account": "", "title": "TOTAL", "city": "",
             "stars": [x for a in ads for x in a["stars"]],
             **{k: sum(a[k] for a in ads) for k in NUMS}}
    return ads, total


def retention(r: dict) -> Optional[float]:
    return 100.0 * r["s2"] / r["b2"] if r["b2"] else None


def _rank(r: dict) -> tuple:
    ret = retention(r)
    return (ret is None, -(ret or 0), -r["s2"], -r["b1"], r["title"].lower())


def _pct(k: int, n: int) -> str:
    return f"{k} ({round(100.0 * k / n):.0f}%)" if n else str(k)


def cells(r: dict, n: Optional[int]) -> List[str]:
    ret = retention(r)
    return [str(n) if n else "", r["account"], r["title"], r["city"],
            str(r["apps"]), str(r["scl"]), str(r["b1"]), _pct(r["s1"], r["b1"]),
            f"{sum(r['stars']) / len(r['stars']):.1f}" if r["stars"] else "-",
            str(r["b2"]), str(r["s2"]), f"{ret:.0f}%" if ret is not None else "-",
            str(r["day1"])]


def render(sections: List[tuple], heading: str, sub: str, out: Path) -> Path:
    """Same look as the photo Ad Scorecard: legend, one table per section,
    rows tinted by 2nd retention, TOTAL last."""
    width = sum(w for _, w in COLS) + PAD * 2
    height = PAD + 68 + LEGEND_H + sum(44 + ROW_H * (len(rows) + 2) + 16
                                       for _, rows, _ in sections) + PAD
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    f, fb, lf = _font(15), _font(15, True), _font(14, True)
    d.rectangle([0, 0, width, 6], fill=HEAD_BG)
    tf = _font(13, True)
    tw = d.textlength(TAG, font=tf) + 20
    d.rounded_rectangle([PAD, PAD, PAD + tw, PAD + 26], radius=5, fill=HEAD_BG)
    d.text((PAD + 10, PAD + 5), TAG, font=tf, fill="white")
    d.text((PAD + tw + 12, PAD - 1), heading, font=_font(24, True), fill=INK)
    d.text((PAD, PAD + 38), sub, font=_font(14), fill=MUTED)
    y = PAD + 68
    x = PAD
    d.text((x, y + 4), "2nd retention:", font=lf, fill=INK)
    x += d.textlength("2nd retention:", font=lf) + 12
    for _, strong, ink, _, name in BANDS:
        w = d.textlength(name, font=lf) + 20
        d.rounded_rectangle([x, y, x + w, y + 24], radius=5, fill=strong)
        d.text((x + 10, y + 4), name, font=lf, fill=ink)
        x += w + 8
    d.text((x + 4, y + 4), "white = no 2nd rounds booked", font=_font(14), fill=MUTED)
    y += LEGEND_H
    for label, rows, total in sections:
        y += 12
        d.text((PAD, y), label, font=_font(17, True), fill=HEAD_BG)
        y += 32
        d.rectangle([PAD, y, width - PAD, y + ROW_H], fill=HEAD_BG)
        x = PAD
        for i, (name, w) in enumerate(COLS):
            tx = x + 8 if i in LEFT else x + w - 8 - d.textlength(name, font=fb)
            d.text((tx, y + 7), name, font=fb, fill="white")
            x += w
        y += ROW_H
        for n, r in enumerate(rows + [total]):
            last = n == len(rows)
            b = band(retention(r))
            if last:
                d.rectangle([PAD, y, width - PAD, y + ROW_H], fill=TOTAL_BG)
            elif b:
                d.rectangle([PAD, y, width - PAD, y + ROW_H], fill=b[3])
                d.rectangle([PAD, y, PAD + 5, y + ROW_H], fill=b[1])
            elif n % 2:
                d.rectangle([PAD, y, width - PAD, y + ROW_H], fill=ALT_BG)
            d.line([PAD, y + ROW_H, width - PAD, y + ROW_H], fill=(225, 229, 234))
            x = PAD
            for i, (text, (_, w)) in enumerate(zip(cells(r, None if last else n + 1), COLS)):
                font, color = (fb if last else f), INK
                if COLS[i][0] == "2nd retention" and b:
                    d.rounded_rectangle([x + 14, y + 3, x + w - 2, y + ROW_H - 3],
                                        radius=5, fill=b[1])
                    color, font = b[2], fb
                if i in LEFT:
                    d.text((x + 8, y + 7), _fit(d, text, font, w - 16), font=font, fill=color)
                else:
                    d.text((x + w - 8 - d.textlength(text, font=font), y + 7), text,
                           font=font, fill=color)
                x += w
            y += ROW_H
        y += 16
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def _md(d: dt.date) -> str:
    return f"{d.month}/{d.day}"


def build(manager: str, day: dt.date) -> dict:
    """LAST WEEK = the Mon-Sun week that ended on or before `day`; THIS MONTH =
    every week that STARTS in that week's month (the data is weekly, so a week
    crossing the 1st counts in the month it starts in)."""
    sunday = day - dt.timedelta(days=(day.weekday() + 1) % 7)
    monday = sunday - dt.timedelta(days=6)
    first = monday.replace(day=1)
    rows = load(manager)
    stars = load_stars(manager)
    week = table(rows, monday, monday, stars)
    month = table(rows, first, monday, stars)
    m_start = min((r["week"] for r in rows if first <= r["week"] <= monday), default=monday)
    return {"manager": manager, "monday": monday, "sunday": sunday, "sections": [
        (f"LAST WEEK  {_md(monday)} - {_md(sunday)}  ·  {len(week[0])} ads", *week),
        (f"{monday.strftime('%B').upper()}  {_md(m_start)} - {_md(sunday)}  ·  "
         f"{len(month[0])} ads", *month),
    ]}


def make(manager: str, day: dt.date, out_dir: Path = OUT_DIR,
         sc: Optional[dict] = None) -> Path:
    sc = sc or build(manager, day)
    sections, sunday = sc["sections"], sc["sunday"]
    heading = f"AppStream Ad Scorecard · {manager}"
    sub = ("One row per ad + account (the Indeed inbox it posts from). "
           "Counts as AppStream's Source Report logs them that week. "
           "Avg stars = the interviewers' ratings in the ARS sheet.")
    out = out_dir / f"{manager.split()[0].lower()}_{sunday.isoformat()}.png"
    return render(sections, heading, sub, out)


# ---- the Sheet tab (same numbers as the PNG) ---------------------------------
SHEET_HEAD = ["#", "Account", "Ad title", "City", "Apps", "To call list",
              "1st booked", "1st showed", "1st show %", "Avg stars",
              "2nd booked", "2nd showed", "2nd retention", "Day 1"]
_SHEET_WIDTHS = [40, 190, 380, 150, 60, 85, 80, 80, 80, 75, 80, 80, 95, 60]
_PCT = (8, 12)


def sheet_row(r: dict, n: Optional[int]) -> list:
    ret = retention(r)
    return [n or "", r["account"], r["title"], r["city"], r["apps"], r["scl"],
            r["b1"], r["s1"], round(r["s1"] / r["b1"], 4) if r["b1"] else "",
            round(sum(r["stars"]) / len(r["stars"]), 1) if r["stars"] else "",
            r["b2"], r["s2"], round(ret / 100.0, 4) if ret is not None else "",
            r["day1"]]


def _rgb(c: tuple) -> dict:
    return {"red": c[0] / 255.0, "green": c[1] / 255.0, "blue": c[2] / 255.0}


def write_sheet(sc: dict, book_id: str, tab: str) -> str:
    """Rewrite `tab` of `book_id` whole (added as the LAST tab if missing)."""
    from automations.recruiting_report.fill import open_by_key
    ncol = len(SHEET_HEAD)
    rows, kinds = [], []

    def add(values, kind, b=None):
        rows.append(list(values) + [""] * (ncol - len(values)))
        kinds.append((len(rows) - 1, kind, b))

    add(["", TAG, f"AppStream Ad Scorecard · {sc['manager']}"], "title")
    add(["", f"Updated {_md(dt.date.today())} · AppStream Source Report, one row "
         "per ad + account · Avg stars = the interviewers' ratings (ARS sheet)"], "sub")
    add(["", "2nd retention colours:", ""] + [b[4] for b in BANDS]
        + ["white = no 2nd rounds booked"], "legend")
    for label, ads, total in sc["sections"]:
        add([], "blank")
        add(["", label], "section")
        add(SHEET_HEAD, "head")
        for n, r in enumerate(ads, 1):
            add(sheet_row(r, n), "ad", band(retention(r)))
        add(sheet_row(total, None), "total", band(retention(total)))

    sh = open_by_key(book_id)
    try:
        ws = sh.worksheet(tab)
    except Exception:                          # noqa: BLE001 — WorksheetNotFound
        ws = sh.add_worksheet(title=tab, rows=len(rows) + 20, cols=ncol)
    if ws.row_count < len(rows) + 5:
        ws.add_rows(len(rows) + 5 - ws.row_count)
    if ws.col_count < ncol:
        ws.add_cols(ncol - ws.col_count)
    gid = ws.id
    whole = {"sheetId": gid, "startRowIndex": 0, "endRowIndex": ws.row_count,
             "startColumnIndex": 0, "endColumnIndex": ws.col_count}
    reqs = [{"unmergeCells": {"range": whole}},
            {"repeatCell": {"range": whole, "cell": {"userEnteredFormat": {}},
                            "fields": "userEnteredFormat"}},
            {"updateSheetProperties": {"properties": {"sheetId": gid,
                                                      "tabColor": _rgb(HEAD_BG)},
                                       "fields": "tabColor"}}]

    def paint(r, fmt, c0=0, c1=ncol):
        reqs.append({"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": r, "endRowIndex": r + 1,
                      "startColumnIndex": c0, "endColumnIndex": c1},
            "cell": {"userEnteredFormat": fmt},
            "fields": ",".join("userEnteredFormat." + k for k in fmt)}})

    def strong(r, b, c0, c1):
        paint(r, {"backgroundColor": _rgb(b[1]), "horizontalAlignment": "CENTER",
                  "textFormat": {"bold": True, "foregroundColor": _rgb(b[2])}}, c0, c1)

    white = _rgb((255, 255, 255))
    for r, kind, b in kinds:
        if kind == "title":
            paint(r, {"backgroundColor": _rgb(HEAD_BG), "horizontalAlignment": "CENTER",
                      "textFormat": {"bold": True, "foregroundColor": white}}, 1, 2)
            paint(r, {"textFormat": {"bold": True, "fontSize": 16,
                                     "foregroundColor": _rgb(INK)}}, 2, ncol)
        elif kind == "sub":
            paint(r, {"textFormat": {"italic": True, "foregroundColor": _rgb(MUTED)}})
        elif kind == "legend":
            paint(r, {"textFormat": {"bold": True}}, 1, 2)
            for i, bb in enumerate(BANDS):
                strong(r, bb, 3 + i, 4 + i)
            paint(r, {"textFormat": {"italic": True, "foregroundColor": _rgb(MUTED)}},
                  3 + len(BANDS), 4 + len(BANDS))
        elif kind == "section":
            paint(r, {"textFormat": {"bold": True, "fontSize": 12,
                                     "foregroundColor": _rgb(HEAD_BG)}})
        elif kind == "head":
            paint(r, {"backgroundColor": _rgb(HEAD_BG), "wrapStrategy": "WRAP",
                      "verticalAlignment": "MIDDLE", "horizontalAlignment": "CENTER",
                      "textFormat": {"bold": True, "foregroundColor": white}})
        elif kind in ("ad", "total"):
            if kind == "total":
                paint(r, {"backgroundColor": _rgb(TOTAL_BG), "textFormat": {"bold": True}})
            elif b:
                paint(r, {"backgroundColor": _rgb(b[3])})
                paint(r, {"backgroundColor": _rgb(b[1])}, 0, 1)
            paint(r, {"horizontalAlignment": "CENTER"}, 0, 1)
            for c in _PCT:
                paint(r, {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}, c, c + 1)
            paint(r, {"numberFormat": {"type": "NUMBER", "pattern": "0.0"}}, 9, 10)
            if b:
                strong(r, b, 12, 13)
                paint(r, {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}, 12, 13)
    for c, w in enumerate(_SHEET_WIDTHS):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": gid, "dimension": "COLUMNS",
                      "startIndex": c, "endIndex": c + 1},
            "properties": {"pixelSize": w}, "fields": "pixelSize"}})
    ws.clear()
    ws.update(values=rows, range_name="A1", value_input_option="RAW")
    sh.batch_update({"requests": reqs})
    return f"https://docs.google.com/spreadsheets/d/{book_id}/edit#gid={gid}"


def updated_today(book_id: str, tab: str) -> bool:
    """Backup plan (Eve 10/19, Lucy 1 was down that day): a second Lucy runs
    the same command later with --if-stale; it only writes when the main
    Lucy's 'Updated M/D' line (B2) is not today's."""
    from automations.recruiting_report.fill import open_by_key
    try:
        cell = open_by_key(book_id).worksheet(tab).acell("B2").value or ""
    except Exception:                          # noqa: BLE001 — no tab yet = stale
        return False
    return cell.startswith(f"Updated {_md(dt.date.today())} ")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--manager", default="Rafael Hidalgo")
    ap.add_argument("--date", type=dt.date.fromisoformat, default=dt.date.today(),
                    help="any day; the scorecard covers the last full Mon-Sun week")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--sheet", metavar="BOOK_ID",
                    help="also rewrite the tab in this workbook (a SANDBOX copy while testing)")
    ap.add_argument("--tab", default="AppStream Ad Scorecard")
    ap.add_argument("--if-stale", action="store_true",
                    help="backup Lucy: do nothing if the tab already says it was updated today")
    a = ap.parse_args(argv)
    if a.sheet and a.if_stale and updated_today(a.sheet, a.tab):
        print("tab already updated today (main Lucy ran) - nothing to do")
        return 0
    sc = build(a.manager, a.date)
    print(make(a.manager, a.date, a.out_dir, sc))
    if a.sheet:
        print(write_sheet(sc, a.sheet, a.tab))
    return 0


if __name__ == "__main__":
    sys.exit(main())
