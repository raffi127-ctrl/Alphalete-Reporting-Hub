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
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

from automations.ad_photo_threads import collect, config, post
from automations.ad_photo_threads import second_rounds as sr
from automations.ad_photo_threads import weekly

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "output" / "ad_photo_threads"

COLS = [("Ad title", 520), ("Seen", 70), ("Invited back", 120), ("Removed", 110),
        ("Avg stars", 90), ("2nd sched.", 95), ("2nd showed", 100), ("2nd retention", 120)]
NUM_COLS = len(COLS) - 1


# ---- numbers -----------------------------------------------------------------
def ad_row(title: str, pairs: List[tuple], seconds: Optional[list]) -> dict:
    cands = [c for _, c in pairs]
    s = post.day_stats(cands)
    n, removed = s["n"], s["removed"]
    k = sr.counts(pairs, seconds) if seconds is not None else None
    return {"title": title, "seen": n, "back": n - removed, "removed": removed,
            "avg": (sum(s["stars"]) / len(s["stars"])) if s["stars"] else None,
            "second": k}


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


def cells(r: dict) -> List[str]:
    k = r["second"]
    if k is None:
        r2 = ["-", "-", "-"]
    else:
        ret = sr.retention(k)
        # Only 2nd rounds already marked show / no-show, so sched - showed =
        # no-shows and the % adds up (the text says "counted through ...").
        r2 = [str(k["scheduled"] - k["pending"]), str(k["showed"]),
              f"{ret:.0f}%" if ret is not None else "-"]
    return [r["title"], str(r["seen"]), _pct(r["back"], r["seen"]),
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
            tx = x + 8 if i == 0 else x + w - 8 - d.textlength(name, font=fb)
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
            for i, (text, (_, w)) in enumerate(zip(cells(r), COLS)):
                font = fb if last else f
                color = INK
                if i == len(COLS) - 1 and b:
                    d.rounded_rectangle([x + 14, y + 3, x + w - 2, y + ROW_H - 3],
                                        radius=5, fill=b[1])
                    color, font = b[2], fb
                if i == 0:
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
