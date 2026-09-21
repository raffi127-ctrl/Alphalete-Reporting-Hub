"""Build one day's photos-per-ad, READ-ONLY (sheet + Slack; nothing is written).

Spine = the sheet: every candidate row for the day gives name + ad title.
Slack gives the picture: the reply in the day's 1st-rounds thread that names
the candidate carries their Zoom screenshot(s).

Pairing a picture with a person, per reply:
  * 1 candidate named                 -> every image in the reply is theirs
  * N candidates and exactly N images -> paired in the order they're written
    (interviewers list the people and paste the shots in the same order)
  * fewer/more images than people     -> it's the slot's GROUP call (each reply
    is one time slot, 2-3 candidates on one Zoom): every image goes to every
    candidate named, flagged `shared` so the post can say "group call"
  * images but no sheet candidate named -> "check by hand"
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from automations.ad_photo_threads import config
from automations.ad_photo_threads.titles import TitleBook

CENTRAL = ZoneInfo("America/Chicago")


def central_today() -> dt.date:
    return dt.datetime.now(CENTRAL).date()


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.replace("&amp;", "&").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9& ]+", " ", s)).strip()


def _parse_date(s: str) -> Optional[dt.date]:
    try:
        return dt.datetime.strptime((s or "").strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


@dataclass
class Candidate:
    name: str
    title_raw: str
    interviewer: str
    qualify: str
    stars: str
    source: str
    ad: Optional[str] = None          # TitleBook key; None = couldn't tell
    images: List[dict] = field(default_factory=list)
    shared: bool = False              # images are the slot's group call
    reply_ts: Optional[str] = None


@dataclass
class DayReport:
    day: dt.date
    book: TitleBook
    candidates: List[Candidate] = field(default_factory=list)
    unpaired: List[dict] = field(default_factory=list)   # {source, names, images, ts}
    missing_threads: List[str] = field(default_factory=list)
    missing_tabs: List[str] = field(default_factory=list)

    def by_ad(self) -> Dict[Optional[str], List[Candidate]]:
        out: Dict[Optional[str], List[Candidate]] = {}
        for c in self.candidates:
            out.setdefault(c.ad, []).append(c)
        return out


# ---- sheet -------------------------------------------------------------------
def _read_tab(sh, tab: str) -> List[Dict[str, str]]:
    from automations.recruiting_report.fill import _retry
    rows = _retry(lambda: sh.worksheet(tab).get_all_values())
    head = [h.strip() for h in rows[0]]
    need = [config.COL_DATE, config.COL_NAME, config.COL_TITLE]
    for h in need:
        if h not in head:
            raise RuntimeError(f"tab {tab!r} has no {h!r} header — did the template change?")
    idx = {h: head.index(h) for h in head if h}
    out = []
    for r in rows[1:]:
        r = r + [""] * (len(head) - len(r))
        out.append({h: r[i].strip() for h, i in idx.items()})
    return out


# ---- slack -------------------------------------------------------------------
def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def _day_bounds(day: dt.date):
    start = dt.datetime.combine(day, dt.time(0), CENTRAL)
    return start.timestamp(), (start + dt.timedelta(days=1)).timestamp()


def find_thread(cl, thread_re, day: dt.date) -> Optional[dict]:
    """The day's parent post, matched on its wording and posted that day (CT)."""
    lo, hi = _day_bounds(day)
    resp = cl.conversations_history(channel=config.SOURCE_CHANNEL_ID,
                                    oldest=str(lo), latest=str(hi), limit=200)
    hits = [m for m in resp.get("messages", [])
            if thread_re.search(m.get("text", "") or "")]
    return min(hits, key=lambda m: float(m["ts"])) if hits else None


def _replies(cl, ts: str) -> List[dict]:
    out, cursor = [], None
    while True:
        r = cl.conversations_replies(channel=config.SOURCE_CHANNEL_ID, ts=ts,
                                     limit=200, cursor=cursor)
        out += r.get("messages", [])
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return [m for m in out if m.get("ts") != ts]


def _images(msg: dict) -> List[dict]:
    return [f for f in (msg.get("files") or [])
            if str(f.get("mimetype", "")).startswith("image/")]


# ---- the day -----------------------------------------------------------------
def build(day: dt.date, *, sh=None, cl=None) -> DayReport:
    from automations.recruiting_report.fill import open_by_key
    sh = sh or open_by_key(config.SHEET_ID)
    cl = cl or _client()

    have = {w.title for w in sh.worksheets()}
    sources = [s for s in config.SOURCES if s["tab"] in have]
    tabs = {s["tab"]: _read_tab(sh, s["tab"]) for s in sources}
    since = day - dt.timedelta(days=config.TITLE_LOOKBACK_DAYS)
    book = TitleBook(
        r[config.COL_TITLE] for rows in tabs.values() for r in rows
        if (_parse_date(r[config.COL_DATE]) or dt.date.min) >= since)
    rep = DayReport(day=day, book=book)
    rep.missing_tabs = [s["label"] for s in config.SOURCES if s["tab"] not in have]

    for src in sources:
        todays = [Candidate(name=r[config.COL_NAME],
                            title_raw=r[config.COL_TITLE],
                            interviewer=r.get(config.COL_INTERVIEWER, ""),
                            qualify=r.get(config.COL_QUALIFY, ""),
                            stars=r.get(config.COL_STARS, ""),
                            source=src["label"])
                  for r in tabs[src["tab"]]
                  if _parse_date(r[config.COL_DATE]) == day and r[config.COL_NAME]]
        rep.candidates += todays
        for c in todays:
            c.ad = book.resolve(c.title_raw)

        parent = find_thread(cl, src["thread_re"], day)
        if not parent:
            if todays:
                rep.missing_threads.append(src["label"])
            continue

        for msg in _replies(cl, parent["ts"]):
            text = _fold(msg.get("text", ""))
            named = sorted(((text.find(_fold(c.name)), c) for c in todays
                            if _fold(c.name) and _fold(c.name) in text),
                           key=lambda p: p[0])
            named = [c for _, c in named]
            imgs = _images(msg)
            for c in named:
                if c.ad is None:     # blank/unclear sheet title: try the Slack line
                    line = next((ln for ln in (msg.get("text") or "").splitlines()
                                 if _fold(c.name) in _fold(ln)), "")
                    c.ad = book.find_in_text(line)
            if not imgs:
                continue
            if len(named) == 1:
                named[0].images += imgs
                named[0].reply_ts = msg["ts"]
            elif named and len(named) == len(imgs):
                for c, f in zip(named, imgs):
                    c.images.append(f)
                    c.reply_ts = msg["ts"]
            elif named:
                for c in named:
                    c.images += imgs
                    c.shared = True
                    c.reply_ts = msg["ts"]
            else:
                rep.unpaired.append({"source": src["label"],
                                     "names": [c.name for c in named],
                                     "images": imgs, "ts": msg["ts"],
                                     "text": msg.get("text", "")})
    return rep
