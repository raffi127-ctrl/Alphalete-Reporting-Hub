"""Ad Scorecard, 2nd picture: the whole funnel per ad (Raf 2026-11-12, thread
"AD Score Card - Edit" in Colten's indeed-photos channel):

  "On this report can we do a 2nd screenshot. on this 2nd screenshot, can we
  include total applies, 1st rds scheduled, 1st rds showed, job offered,
  BOB #, New starts scheduled, new starts showed."

Two sources, each for what only it has:
  * the interviewers' sheet (same rows as the 1st picture): 1st rds showed
    (= the 1st picture's "Seen"), "Offered Positon" = YES, "BOB" = BOB --
    counted by the 1st-round date, like everything else on the scorecard;
  * AppStream's Source Report (p=702, the Indeed Source Report's scrape) for
    the office: applies, 1st rds scheduled, new starts scheduled / showed.
    AppStream counts an event only when the APPLY date is in the window too,
    so the window runs from the Monday / the 1st through LOOKAHEAD days after
    the day -- a new start booked for next week still counts. Its ads are
    matched to the sheet's by title (TitleBook); an AppStream ad nobody
    interviewed from gets its own row with "-" in the sheet columns.

AppStream down / office not set -> the AppStream columns show "-" and the
picture still goes out (the sheet half is the same numbers as picture 1).

Every office with "scorecard": True gets it (Eve 11/12 "aplicalo a todos"),
from its own AppStream office (its source's office_id; "scorecard_funnel_office"
overrides). "scorecard_funnel_offers": False (Raf -- his tab never fills
Offered / BOB) shows those two columns as "-".
By hand (PNG + printed table, nothing posted):
    python -m automations.ad_photo_threads.funnel --office colten --date 2026-11-06
    python -m automations.ad_photo_threads.funnel --office colten --date 2026-11-06 --no-appstream

Python 3.9-safe (runs on the Lucys).
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image, ImageDraw

from automations.ad_photo_threads import collect, config, post
from automations.ad_photo_threads import scorecard as sc

LOOKAHEAD_DAYS = 14
COL_OFFERED = "Offered Positon"        # (sic) -- the sheet's own header
COL_BOB = "BOB"

COLS = [("#", 40), ("Ad title", 430), ("City", 160), ("Applies", 80),
        ("1st sched.", 95), ("1st showed", 100), ("Job offered", 110), ("BOB", 70),
        ("New starts sched.", 150), ("New starts showed", 150)]
LEFT = {1, 2}
APP_KEYS = ("apps", "b1", "nb", "ns")    # AppStream's numbers on a row
SHEET_KEYS = ("s1", "offered", "bob")


# ---- numbers -----------------------------------------------------------------
def sheet_counts(tabs: Dict[str, List[Dict[str, str]]], book, start: dt.date,
                 end: dt.date) -> Dict[str, dict]:
    """{ad key: {s1, offered, bob}} from the interviewers' rows dated
    [start, end] -- the same rows (and keys) as the 1st picture."""
    out: Dict[str, dict] = {}
    for src in config.SOURCES:
        for r in tabs.get(src["tab"], []):
            d = collect._parse_date(r.get(config.COL_DATE, ""))
            if not d or not (start <= d <= end) or not r.get(config.COL_NAME):
                continue
            key = book.resolve(r.get(config.COL_TITLE, ""))
            if not key:
                continue
            k = out.setdefault(key, {"s1": 0, "offered": 0, "bob": 0})
            k["s1"] += 1
            k["offered"] += (r.get(COL_OFFERED) or "").strip().lower() == "yes"
            k["bob"] += (r.get(COL_BOB) or "").strip().lower() == "bob"
    return out


def match(app_ads: List[dict], book, keys) -> Dict[str, dict]:
    """AppStream ads (parse.load_table records) summed onto sheet ad keys.
    An ad the sheet doesn't know keeps its own "~title|city" key."""
    keys = set(keys)
    out: Dict[str, dict] = {}
    for a in app_ads:
        title, city = a.get("title") or "", a.get("city") or ""
        key = None
        for cand in (f"{title} - {city}" if city else None, title):
            if cand:
                k = book.resolve(cand)
                if k in keys:
                    key = k
                    break
        if key is None:
            key = f"~{title}|{city}"
        got = out.setdefault(key, {k: 0 for k in APP_KEYS})
        if key.startswith("~"):
            got.setdefault("title", title)
            got.setdefault("city", city)
        rec = a.get("rec") or {}
        for k in APP_KEYS:
            got[k] += int(rec.get(k) or 0)
    return out


def rows_for(sheet: Dict[str, dict], app: Optional[Dict[str, dict]],
             titles: Dict[str, str]) -> List[dict]:
    """One row per ad: sheet ads first (most 1st rounds showed), then
    AppStream-only ads (most applies). `app` None = AppStream not read."""
    rows = []
    for key in set(sheet) | set(app or {}):
        s, a = sheet.get(key), (app or {}).get(key)
        if key.startswith("~"):
            title, city = a["title"], a["city"]
        else:
            title, city = sc.title_city(titles.get(key, key))
        if app is not None and a is None:
            a = {k: 0 for k in APP_KEYS}
        if a is not None and not s and not any(a[k] for k in APP_KEYS):
            continue
        rows.append({"title": title, "city": city, "sheet": s, "app": a})
    rows.sort(key=lambda r: (r["sheet"] is None, -(r["sheet"] or {}).get("s1", 0),
                             -(r["app"] or {}).get("apps", 0), r["title"].lower()))
    return rows


def total(rows: List[dict], app_read: bool) -> dict:
    s = {k: sum((r["sheet"] or {}).get(k, 0) for r in rows) for k in SHEET_KEYS}
    a = ({k: sum((r["app"] or {}).get(k, 0) for r in rows) for k in APP_KEYS}
         if app_read else None)
    return {"title": "TOTAL", "city": "", "sheet": s, "app": a}


def cells(r: dict, n: Optional[int]) -> List[str]:
    s, a = r["sheet"], r["app"]

    def g(d, k):
        return str(d[k]) if d is not None else "-"
    return [str(n) if n is not None else "", r["title"], r["city"],
            g(a, "apps"), g(a, "b1"), g(s, "s1"),
            g(s if config.SCORECARD_FUNNEL_OFFERS else None, "offered"),
            g(s if config.SCORECARD_FUNNEL_OFFERS else None, "bob"),
            g(a, "nb"), g(a, "ns")]


# ---- AppStream ---------------------------------------------------------------
def appstream_ads(office_id: str, start: dt.date, end: dt.date) -> List[dict]:
    """The office's Source Report for [start, end], per ad (title, city, rec)."""
    from automations.applicant_tracker.applicantstream import session
    from automations.indeed_source_report import fetch, parse
    with session() as app:
        app.select_office(office_id)
        tok = fetch.token(app.page)
        html, _owner, _n = fetch.source_report(app.page, tok, f"{start:%m-%d-%Y}",
                                               f"{end:%m-%d-%Y}")
    return parse.load_table(html)


# ---- picture -----------------------------------------------------------------
def render(sections: List[tuple], heading: str, sub: str, out: Path) -> Path:
    """`sections` = [(label, rows, total)]. Same look as picture 1, no
    retention colours (nothing here is a retention)."""
    width = sum(w for _, w in COLS) + sc.PAD * 2
    height = sc.PAD + 40 + 28 + sum(44 + sc.ROW_H * (len(rows) + 2) + 16
                                    for _, rows, _ in sections) + sc.PAD
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    f, fb = sc._font(15), sc._font(15, True)
    d.text((sc.PAD, sc.PAD), heading, font=sc._font(24, True), fill=sc.INK)
    d.text((sc.PAD, sc.PAD + 38), sub, font=sc._font(14), fill=sc.MUTED)
    y = sc.PAD + 40 + 28
    for label, rows, tot in sections:
        y += 12
        d.text((sc.PAD, y), label, font=sc._font(17, True), fill=sc.HEAD_BG)
        y += 32
        x = sc.PAD
        d.rectangle([sc.PAD, y, width - sc.PAD, y + sc.ROW_H], fill=sc.HEAD_BG)
        for i, (name, w) in enumerate(COLS):
            tx = x + 8 if i in LEFT else x + w - 8 - d.textlength(name, font=fb)
            d.text((tx, y + 7), name, font=fb, fill="white")
            x += w
        y += sc.ROW_H
        for n, r in enumerate(rows + [tot]):
            last = n == len(rows)
            if last:
                d.rectangle([sc.PAD, y, width - sc.PAD, y + sc.ROW_H], fill=sc.TOTAL_BG)
            elif n % 2:
                d.rectangle([sc.PAD, y, width - sc.PAD, y + sc.ROW_H], fill=sc.ALT_BG)
            d.line([sc.PAD, y + sc.ROW_H, width - sc.PAD, y + sc.ROW_H], fill=(225, 229, 234))
            x = sc.PAD
            font = fb if last else f
            for i, (text, (_, w)) in enumerate(zip(cells(r, None if last else n + 1), COLS)):
                if i in LEFT:
                    d.text((x + 8, y + 7), sc._fit(d, text, font, w - 16), font=font, fill=sc.INK)
                else:
                    d.text((x + w - 8 - d.textlength(text, font=font), y + 7), text,
                           font=font, fill=sc.INK)
                x += w
            y += sc.ROW_H
        y += 16
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def build(day: dt.date, office_id: str = "", *, cache: Optional[dict] = None,
          use_appstream: bool = True) -> dict:
    from automations.recruiting_report.fill import open_by_key
    cache = {} if cache is None else cache
    sh = cache.get("_sh") or open_by_key(config.SHEET_ID)
    cache["_sh"] = sh
    tabs = collect.read_tabs(sh, cache)
    book = collect.make_book(tabs, day)
    monday, first = post.week_monday(day), day.replace(day=1)
    titles = {}
    out = {"day": day, "monday": monday, "first": first, "app_error": ""}
    for name, start in (("week", monday), ("month", first)):
        sheet = sheet_counts(tabs, book, start, day)
        titles.update({k: book.display(k) for k in sheet})
        app = None
        if office_id and use_appstream and not out["app_error"]:
            try:
                ads = appstream_ads(office_id, start, day + dt.timedelta(days=LOOKAHEAD_DAYS))
                app = match(ads, book, sheet.keys())
            except Exception as e:                # noqa: BLE001 -- "-" columns, still post
                out["app_error"] = f"{type(e).__name__}: {str(e)[:160]}"
                print(f"funnel: AppStream failed, its columns go out as '-': {out['app_error']}")
        rows = rows_for(sheet, app, titles)
        out[name] = rows
        out[name + "_total"] = total(rows, app is not None)
    return out


def make(day: dt.date, owner: str, office_id: str = "", out_dir: Path = sc.OUT_DIR, *,
         cache=None, use_appstream: bool = True) -> Path:
    f = build(day, office_id, cache=cache, use_appstream=use_appstream)
    md = sc._md
    week_label = f"THIS WEEK · {md(f['monday'])} - {md(day)} · {len(f['week'])} ads"
    month_label = f"THIS MONTH · {f['first']:%B} 1 - {day.day} · {len(f['month'])} ads"
    sub = ("Applies, 1st sched. and new starts from ApplicantStream · 1st showed, "
           "job offered and BOB from the interviewers' sheet")
    if f["app_error"] or not office_id or not use_appstream:
        sub = "ApplicantStream not read this time (\"-\") · 1st showed, job offered " \
              "and BOB from the interviewers' sheet"
    return render([(week_label, f["week"], f["week_total"]),
                   (month_label, f["month"], f["month_total"])],
                  f"Ad Scorecard · Funnel · {owner}", sub,
                  out_dir / f"scorecard_funnel_{config.LIVE_CHANNEL_ID}_{day.isoformat()}.png")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", required=True)
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, Central)")
    ap.add_argument("--no-appstream", action="store_true")
    a = ap.parse_args(argv)
    o = config.office(a.office)
    config.use(o)
    day = dt.date.fromisoformat(a.date) if a.date else collect.central_today()
    png = make(day, o["owner"], config.SCORECARD_FUNNEL_OFFICE,
               use_appstream=not a.no_appstream)
    print("PNG:", png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
