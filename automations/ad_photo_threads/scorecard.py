"""Ad scorecard (Raf 2026-10-09, Loom on the Funnel 1 channel):

  "can we get like a weekly scorecard maybe on Friday for the week, and then
  for the month, saying here's all the ad titles you have ... in one row the
  ad title, and then columns: how many people you saw from this ad, how many
  you invited back, removed, your average star rating, second round showed
  ... also put at the beginning how many ad titles ... a quick count."

One post in the office's photos channel (not inside an ad thread): a line with
the ad-title count, and a PNG with two tables -- THIS WEEK (Monday .. day) and
THIS MONTH (the 1st .. day) -- one row per ad, biggest first, a total row at
the bottom. Same numbers as the ad threads: the interviewers' sheet for the
1st rounds, the tracker's 2R tab for the 2nd rounds (second_rounds.py).

When: config.SCORECARD_WEEKDAYS after the evening ad threads, for offices with
"scorecard": True. By hand:
    python -m automations.ad_photo_threads.run --office rafael --scorecard           # PNG + text, no post
    python -m automations.ad_photo_threads.run --office rafael --scorecard --dm U088E2KJEV8

Python 3.9-safe (runs on the mini).
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

from automations.ad_photo_threads import collect, config, post
from automations.ad_photo_threads import second_rounds as sr
from automations.ad_photo_threads import weekly

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "output" / "ad_photo_threads"

# Raf 10/10: "Can we label the ads 1, 2, 3" + "a column for city please".
COLS = [("#", 40), ("Ad title", 430), ("City", 160), ("Seen", 70), ("Invited back", 120), ("Removed", 110),
        ("Avg stars", 90), ("2nd sched.", 95), ("2nd showed", 100), ("2nd retention", 120)]
LEFT = {1, 2}          # title + city read left to right; numbers right-aligned


# ---- numbers -----------------------------------------------------------------
def ad_row(title: str, pairs: List[tuple], seconds: Optional[list]) -> dict:
    cands = [c for _, c in pairs]
    s = post.day_stats(cands)
    n, removed = s["n"], s["removed"]
    k = sr.counts(pairs, seconds) if seconds is not None else None
    return {"title": title, "seen": n, "back": n - removed, "removed": removed,
            "avg": (sum(s["stars"]) / len(s["stars"])) if s["stars"] else None,
            "second": k}


# Where the ad runs, as the title spells it at the end:
#   "AT&T Sales Agent – McKinney TX"                    -> McKinney, TX
#   "Entry level Sales Manager, Allen, TX"              -> Allen, TX
#   "Wireless Service Associate - Spanish Required – Mesquite TX (Dallas County)"
#                                                       -> Mesquite, TX
#   "Marketing Campaigns - Entry Level at Alphalete Marketing · Dallas-Fort Worth Metroplex"
#                                                       -> Dallas-Fort Worth
#   "Event Marketing & Sales Assistant (Spanish Required) – 2 locations" -> 2 locations
# A city is 1-4 capitalised words after " – " / " - " / ","; a title with
# no city at its end keeps its whole name and a blank city.
_CITY_ST = re.compile(
    r"(?:\s+[–-]\s+|\s*,\s*)"
    r"([A-Z][A-Za-z.']*(?:[ -][A-Za-z.']+){0,3}),?\s+([A-Z]{2})"
    r"(?:\s*\([^)]*\)?)?[\s,]*$")
_CITY_DOT = re.compile(r"\s+·\s+([^·]+?)\s*$")
_LOCATIONS = re.compile(r"\s+[–-]\s+(\d+\s+locations?)\s*$", re.I)


def split_city(title: str) -> tuple:
    """(title without its city, city) -- city "" when the title names none."""
    t = (title or "").strip()
    m = _CITY_ST.search(t)
    if m and m.start() > 0:
        return t[:m.start()].rstrip(" ,–-"), f"{m.group(1)}, {m.group(2)}"
    for rx in (_CITY_DOT, _LOCATIONS):
        m = rx.search(t)
        if m and m.start() > 0:
            return (t[:m.start()].rstrip(" ,–-"),
                    re.sub(r"\s+metroplex$", "", m.group(1).strip(), flags=re.I))
    return t, ""


def table(history: Dict[str, List[tuple]], titles: Dict[str, str],
          start: dt.date, end: dt.date, seconds: Optional[list]) -> List[dict]:
    """One row per ad with 1st rounds in [start, end]. Eve 10/9 (to Raf):
    "sorting them from highest to lowest on 2nd retention" -- best retention
    first, more people who showed breaking a tie (so 6 of 6 beats 1 of 1), ads
    with no 2nd rounds yet at the bottom, most people seen first."""
    rows = []
    for key, hist in history.items():
        pairs = [(d, c) for d, c in hist if start <= d <= end]
        if pairs:
            rows.append(ad_row(titles.get(key, key), pairs, seconds))
    rows.sort(key=_rank)
    return rows


def _ret(r: dict) -> Optional[float]:
    return sr.retention(r["second"]) if r["second"] is not None else None


def _rank(r: dict) -> tuple:
    ret = _ret(r)
    showed = r["second"]["showed"] if r["second"] is not None else 0
    return (ret is None, -(ret or 0), -showed, -r["seen"], r["title"].lower())


def total_row(history: Dict[str, List[tuple]], start: dt.date, end: dt.date,
              seconds: Optional[list]) -> dict:
    pairs = [(d, c) for hist in history.values() for d, c in hist if start <= d <= end]
    return ad_row("TOTAL", pairs, seconds)


def _pct(k: int, n: int) -> str:
    return f"{k} ({round(100.0 * k / n):.0f}%)" if n else str(k)


def cells(r: dict, n: Optional[int] = None) -> List[str]:
    """One row as shown; `n` = the ad's number in its table (None = TOTAL)."""
    k = r["second"]
    if k is None:
        r2 = ["-", "-", "-"]
    else:
        ret = sr.retention(k)
        # Only 2nd rounds already marked show / no-show, so sched - showed =
        # no-shows and the % adds up (the text says "counted through ...").
        r2 = [str(k["scheduled"] - k["pending"]), str(k["showed"]),
              f"{ret:.0f}%" if ret is not None else "-"]
    title, city = split_city(r["title"]) if n is not None else (r["title"], "")
    return [str(n) if n is not None else "", title, city, str(r["seen"]), _pct(r["back"], r["seen"]),
            _pct(r["removed"], r["seen"]),
            f"{r['avg']:.1f}" if r["avg"] is not None else "-"] + r2


# ---- picture -----------------------------------------------------------------
_FONTS = {
    False: ["/System/Library/Fonts/Supplemental/Arial.ttf", "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    True: ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
}


def _font(size: int, bold: bool = False):
    for path in _FONTS[bold]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:                        # noqa: BLE001 — next candidate
            continue
    return ImageFont.load_default()


def _fit(draw, text: str, font, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


INK = (33, 37, 41)
MUTED = (108, 117, 125)
HEAD_BG = (31, 58, 96)
ALT_BG = (244, 247, 251)
TOTAL_BG = (226, 234, 245)
# Eve 10/9: "a little colour would help identify higher retention %". Each
# row is tinted by its 2nd retention band, the retention cell carries the
# band's strong colour, and a legend under the title says what they mean.
# (band floor, strong cell bg, cell text, light row tint, legend label)
BANDS = [
    (70, (30, 132, 73), (255, 255, 255), (226, 244, 232), "70%+"),
    (50, (130, 201, 146), (20, 70, 35), (240, 249, 242), "50-69%"),
    (30, (246, 190, 92), (110, 60, 0), (254, 246, 230), "30-49%"),
    (0, (226, 86, 86), (255, 255, 255), (252, 234, 234), "under 30%"),
]
LEGEND_H = 30


def band(ret: Optional[float]) -> Optional[tuple]:
    if ret is None:
        return None
    return next(b for b in BANDS if ret >= b[0])
ROW_H, PAD = 30, 20


def render(sections: List[tuple], heading: str, sub: str, out: Path) -> Path:
    """`sections` = [(label, rows, total)]; one table per section."""
    width = sum(w for _, w in COLS) + PAD * 2
    height = PAD + 40 + 28 + LEGEND_H + sum(44 + ROW_H * (len(rows) + 2) + 16
                                 for _, rows, _ in sections) + PAD
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    f, fb = _font(15), _font(15, True)
    d.text((PAD, PAD), heading, font=_font(24, True), fill=INK)
    d.text((PAD, PAD + 38), sub, font=_font(14), fill=MUTED)
    y = PAD + 40 + 28
    lf = _font(14, True)
    x = PAD
    d.text((x, y + 4), "2nd retention:", font=lf, fill=INK)
    x += d.textlength("2nd retention:", font=lf) + 12
    for _, strong, ink, _, name in BANDS:
        w = d.textlength(name, font=lf) + 20
        d.rounded_rectangle([x, y, x + w, y + 24], radius=5, fill=strong)
        d.text((x + 10, y + 4), name, font=lf, fill=ink)
        x += w + 8
    d.text((x + 4, y + 4), "white = no 2nd rounds yet", font=_font(14), fill=MUTED)
    y += LEGEND_H
    for label, rows, total in sections:
        y += 12
        d.text((PAD, y), label, font=_font(17, True), fill=HEAD_BG)
        y += 32
        x = PAD
        d.rectangle([PAD, y, width - PAD, y + ROW_H], fill=HEAD_BG)
        for i, (name, w) in enumerate(COLS):
            tx = x + 8 if i in LEFT else x + w - 8 - d.textlength(name, font=fb)
            d.text((tx, y + 7), name, font=fb, fill="white")
            x += w
        y += ROW_H
        for n, r in enumerate(rows + [total]):
            last = n == len(rows)
            b = band(_ret(r))
            if last:
                d.rectangle([PAD, y, width - PAD, y + ROW_H], fill=TOTAL_BG)
            elif b:
                d.rectangle([PAD, y, width - PAD, y + ROW_H], fill=b[3])
                d.rectangle([PAD, y, PAD + 5, y + ROW_H], fill=b[1])
            d.line([PAD, y + ROW_H, width - PAD, y + ROW_H], fill=(225, 229, 234))
            x = PAD
            for i, (text, (_, w)) in enumerate(zip(cells(r, None if last else n + 1),
                                                   COLS)):
                font = fb if last else f
                color = INK
                if i == len(COLS) - 1 and b:
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


# ---- the post ----------------------------------------------------------------
def _md(d: dt.date) -> str:
    return f"{d.month}/{d.day}"


def build(day: dt.date, *, sh=None, cache: Optional[dict] = None) -> dict:
    """Everything the post needs for `day` (current office, config.use)."""
    from automations.recruiting_report.fill import open_by_key
    cache = {} if cache is None else cache
    sh = sh or cache.get("_sh") or open_by_key(config.SHEET_ID)
    cache["_sh"] = sh
    tabs = collect.read_tabs(sh, cache)
    book = collect.make_book(tabs, day)
    monday, first = post.week_monday(day), day.replace(day=1)
    history = weekly.ad_history(book, min(monday, first), day, cache=cache)
    titles = {k: book.display(k) for k in history}
    seconds = weekly.load_seconds()
    week = table(history, titles, monday, day, seconds)
    month = table(history, titles, first, day, seconds)
    return {"day": day, "monday": monday, "first": first, "seconds": seconds,
            "week": week, "month": month,
            "week_total": total_row(history, monday, day, seconds),
            "month_total": total_row(history, first, day, seconds)}


def text(sc: dict, owner: str) -> str:
    day, monday = sc["day"], sc["monday"]
    lines = [f"*📊 Ad Scorecard · {owner} · {weekly.week_tag(monday)}*",
             f"📋 *{len(sc['week'])} ad titles* had 1st rounds this week "
             f"({_md(monday)}-{_md(day)}) · *{len(sc['month'])}* this month"]
    if sc["seconds"] is not None:
        lines.append(f"_2nd rounds counted through {_md(day - dt.timedelta(days=1))} "
                     f"(AppStream marks show / no-show the next morning)._")
    return "\n".join(lines)


def make(day: dt.date, owner: str, out_dir: Path = OUT_DIR, *, cache=None) -> tuple:
    sc = build(day, cache=cache)
    monday, first = sc["monday"], sc["first"]
    week_label = f"THIS WEEK · {_md(monday)} - {_md(day)} · {len(sc['week'])} ad titles"
    month_label = f"THIS MONTH · {first:%B} 1 - {day.day} · {len(sc['month'])} ad titles"
    png = render([(week_label, sc["week"], sc["week_total"]),
                  (month_label, sc["month"], sc["month_total"])],
                 f"Ad Scorecard · {owner}",
                 f"1st rounds from the interviewers' sheet · 2nd rounds from ApplicantStream",
                 out_dir / f"scorecard_{config.LIVE_CHANNEL_ID}_{day.isoformat()}.png")
    return text(sc, owner), png


# ---- the spreadsheet tab ------------------------------------------------------
# Raf 10/10: "Can we add this in a spreadsheet format to my 'all in one local
# office' spreadsheet please?" Same two tables as the PNG, in the office's
# `scorecard_book`, tab config.SCORECARD_TAB. The tab is OURS: every run
# rewrites it whole (values + colours), so it always shows this week + this
# month. Numbers go in as numbers and % as real percents, so it sorts/sums.
SHEET_HEAD = ["#", "Ad title", "City", "Seen", "Invited back", "Invited back %",
              "Removed", "Removed %", "Avg stars", "2nd sched.", "2nd showed",
              "2nd retention"]
_PCT_COLS = (5, 7, 11)
_SHEET_WIDTHS = [40, 430, 170, 60, 80, 95, 75, 85, 75, 80, 85, 95]


def sheet_row(r: dict, n: Optional[int]) -> list:
    """One row as numbers; `n` = the ad's number (None = TOTAL)."""
    k = r["second"]
    title, city = split_city(r["title"]) if n is not None else (r["title"], "")
    seen = r["seen"]
    if k is None:
        r2 = ["", "", ""]
    else:
        ret = sr.retention(k)
        r2 = [k["scheduled"] - k["pending"], k["showed"],
              round(ret / 100.0, 4) if ret is not None else ""]
    return [n if n is not None else "", title, city, seen, r["back"],
            round(r["back"] / seen, 4) if seen else "", r["removed"],
            round(r["removed"] / seen, 4) if seen else "",
            round(r["avg"], 1) if r["avg"] is not None else ""] + r2


def _rgb(c: tuple) -> dict:
    return {"red": c[0] / 255.0, "green": c[1] / 255.0, "blue": c[2] / 255.0}


def sheet_grid(sc: dict, owner: str) -> tuple:
    """(rows of values, [(row index, kind, band)]); kind = title / sub /
    legend / blank / section / head / ad / total. Pure, so it's testable."""
    day, monday, first = sc["day"], sc["monday"], sc["first"]
    rows, kinds = [], []

    def add(values, kind, b=None):
        rows.append(list(values) + [""] * (len(SHEET_HEAD) - len(values)))
        kinds.append((len(rows) - 1, kind, b))

    add([f"Ad Scorecard · {owner}"], "title")
    sub = f"Updated {_md(day)} · 1st rounds from the interviewers' sheet"
    if sc["seconds"] is not None:
        sub += (f" · 2nd rounds from ApplicantStream, counted through "
                f"{_md(day - dt.timedelta(days=1))}")
    add([sub], "sub")
    add(["", "2nd retention colours:", ""] + [b[4] for b in BANDS]
        + ["white = no 2nd rounds yet"], "legend")
    for label, ads, total in (
            (f"THIS WEEK · {_md(monday)} - {_md(day)} · {len(sc['week'])} ad titles",
             sc["week"], sc["week_total"]),
            (f"THIS MONTH · {first:%B} 1 - {day.day} · {len(sc['month'])} ad titles",
             sc["month"], sc["month_total"])):
        add([], "blank")
        add(["", label], "section")
        add(SHEET_HEAD, "head")
        for n, r in enumerate(ads, 1):
            add(sheet_row(r, n), "ad", band(_ret(r)))
        add(sheet_row(total, None), "total", band(_ret(total)))
    return rows, kinds


def write_sheet(sc: dict, owner: str, book_id: str, tab: str) -> str:
    """Rewrite `tab` in workbook `book_id` (added as the book's first tab if
    missing). Returns the tab's URL."""
    from automations.recruiting_report.fill import open_by_key
    rows, kinds = sheet_grid(sc, owner)
    ncol = len(SHEET_HEAD)
    sh = open_by_key(book_id)
    try:
        ws = sh.worksheet(tab)
    except Exception:                          # noqa: BLE001 — WorksheetNotFound
        ws = sh.add_worksheet(title=tab, rows=len(rows) + 20, cols=ncol, index=0)
    if ws.row_count < len(rows) + 5:
        ws.add_rows(len(rows) + 5 - ws.row_count)
    if ws.col_count < ncol:
        ws.add_cols(ncol - ws.col_count)
    gid = ws.id
    whole = {"sheetId": gid, "startRowIndex": 0, "endRowIndex": ws.row_count,
             "startColumnIndex": 0, "endColumnIndex": ws.col_count}
    reqs = [{"unmergeCells": {"range": whole}},
            {"repeatCell": {"range": whole, "cell": {"userEnteredFormat": {}},
                            "fields": "userEnteredFormat"}}]

    def paint(r, fmt, c0=0, c1=ncol):
        reqs.append({"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": r, "endRowIndex": r + 1,
                      "startColumnIndex": c0, "endColumnIndex": c1},
            "cell": {"userEnteredFormat": fmt},
            "fields": "userEnteredFormat(" + ",".join(fmt) + ")"}})

    def strong(r, b, c0, c1):
        paint(r, {"backgroundColor": _rgb(b[1]), "horizontalAlignment": "CENTER",
                  "textFormat": {"bold": True, "foregroundColor": _rgb(b[2])}}, c0, c1)

    for r, kind, b in kinds:
        if kind == "title":
            paint(r, {"textFormat": {"bold": True, "fontSize": 16,
                                     "foregroundColor": _rgb(INK)}})
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
                      "textFormat": {"bold": True, "foregroundColor": _rgb((255, 255, 255))}})
        elif kind in ("ad", "total"):
            if kind == "total":
                paint(r, {"backgroundColor": _rgb(TOTAL_BG), "textFormat": {"bold": True}})
            elif b:
                paint(r, {"backgroundColor": _rgb(b[3])})
                paint(r, {"backgroundColor": _rgb(b[1])}, 0, 1)
            paint(r, {"horizontalAlignment": "CENTER"}, 0, 1)
            for c in _PCT_COLS:
                paint(r, {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}, c, c + 1)
            paint(r, {"numberFormat": {"type": "NUMBER", "pattern": "0.0"}}, 8, 9)
            if b:
                strong(r, b, ncol - 1, ncol)
                paint(r, {"numberFormat": {"type": "PERCENT", "pattern": "0%"}},
                      ncol - 1, ncol)
    for c, w in enumerate(_SHEET_WIDTHS):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": gid, "dimension": "COLUMNS",
                      "startIndex": c, "endIndex": c + 1},
            "properties": {"pixelSize": w}, "fields": "pixelSize"}})
    ws.clear()
    sh.batch_update({"requests": reqs})
    ws.update(values=rows, range_name="A1", value_input_option="RAW")
    return f"https://docs.google.com/spreadsheets/d/{book_id}/edit#gid={gid}"


def sheet_done(book_id: str, day: dt.date) -> bool:
    return day.isoformat() in (post._load_state().get("_scorecard_sheets", {})
                               .get(book_id) or [])


def mark_sheet_done(book_id: str, day: dt.date) -> None:
    state = post._load_state()
    got = state.setdefault("_scorecard_sheets", {}).setdefault(book_id, [])
    if day.isoformat() not in got:
        got.append(day.isoformat())
        del got[:-14]
    post._save_state(state)


def done(channel: str, day: dt.date) -> bool:
    return day.isoformat() in (post._load_state().get(channel, {}).get("scorecards") or [])


def publish(day: dt.date, channel: str, owner: str, *, cl=None, record: bool = True) -> str:
    """Post the scorecard (text + PNG) as its own message in `channel`."""
    cl = cl or collect._client()
    msg, png = make(day, owner)
    r = cl.files_upload_v2(channel=channel, file=str(png), filename=png.name,
                           title=f"Ad Scorecard {day.isoformat()}", initial_comment=msg)
    if record:
        state = post._load_state()
        got = state.setdefault(channel, {}).setdefault("scorecards", [])
        if day.isoformat() not in got:
            got.append(day.isoformat())
        post._save_state(state)
    return str((r.get("file") or {}).get("id", ""))


def due(o: dict, day: dt.date) -> bool:
    return bool(o.get("scorecard")) and day.weekday() in config.SCORECARD_WEEKDAYS \
        and day.isoformat() >= config.SCORECARD_FROM
