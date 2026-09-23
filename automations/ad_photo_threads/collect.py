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
from automations.ad_photo_threads.titles import TitleBook, norm

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
    # How Slack spelled them when it differs from the sheet (first-name match)
    # — the Zoom tile may carry that spelling, so the cropper looks for both.
    alt_names: List[str] = field(default_factory=list)
    # What the interviewer wrote about them in the 1st-rounds reply (Raf
    # 2026-09-22: "include the written description per candidate that the
    # interviewer writes"), with the name / stars / ✅ / ad title taken off.
    notes: List[str] = field(default_factory=list)


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


def source_channels() -> List[str]:
    """The office's recruiting channel(s). A list when the 1st rounds moved
    channel (Rashad 2026-09-23: from #rashad-reed-office-recruiting-23411 to
    #23411-elevate-specialized-acquisitions-inc-rashad-reed on 9/24), so old
    days are still found where they were posted."""
    ch = config.SOURCE_CHANNEL_ID
    return [ch] if isinstance(ch, str) else list(ch)


def find_thread(cl, thread_re, day: dt.date) -> Optional[dict]:
    """The day's parent post, matched on its wording and posted that day (CT),
    in whichever of the office's channels has it. Carries `_channel`."""
    lo, hi = _day_bounds(day)
    hits = []
    for ch in source_channels():
        resp = cl.conversations_history(channel=ch, oldest=str(lo),
                                        latest=str(hi), limit=200)
        hits += [dict(m, _channel=ch) for m in resp.get("messages", [])
                 if thread_re.search(m.get("text", "") or "")]
    return min(hits, key=lambda m: float(m["ts"])) if hits else None


def _replies(cl, ts: str, channel: Optional[str] = None) -> List[dict]:
    channel = channel or source_channels()[0]
    out, cursor = [], None
    while True:
        r = cl.conversations_replies(channel=channel, ts=ts,
                                     limit=200, cursor=cursor)
        out += r.get("messages", [])
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return [m for m in out if m.get("ts") != ts]


def _images(msg: dict) -> List[dict]:
    return [f for f in (msg.get("files") or [])
            if str(f.get("mimetype", "")).startswith("image/")]


def _full_named(msg: dict, todays: List[Candidate]) -> List[tuple]:
    """(position, candidate) for every sheet name written out in full."""
    text = _fold(msg.get("text", ""))
    return [(text.find(_fold(c.name)), c) for c in todays
            if _fold(c.name) and _fold(c.name) in text]


def first_name_matches(msgs: List[dict], todays: List[Candidate],
                       book: TitleBook) -> Dict[int, List[tuple]]:
    """Sheet candidates NO reply names in full, found by first name instead:
    {message index: [(position, candidate)]}.

    9/21: the sheet had "Pedro Menendez", the interviewer wrote "Pedro Moreno"
    in Slack — same person, same ad, and he went out with no photo. Same
    night "Breija Smith" was "Breia Smith", so the LAST name is tried when
    the first doesn't settle it. Only taken when there's no doubt: exactly
    one line in the whole thread has that name AND names the candidate's
    ad, and no other unmatched candidate on that ad shares it."""
    full = {id(c) for m in msgs for _, c in _full_named(m, todays)}
    loose = [c for c in todays if id(c) not in full and c.ad and _fold(c.name).split()]
    out: Dict[int, List[tuple]] = {}
    for c in loose:
        hits = []
        for part in (0, -1):                       # first name, then last name
            word = _fold(c.name).split()[part]
            if len(word) < 3 or sum(1 for o in loose if o.ad == c.ad
                                    and _fold(o.name).split()[part] == word) > 1:
                continue
            hits = []
            for i, m in enumerate(msgs):
                text = _fold(m.get("text", ""))
                for ln in (m.get("text") or "").splitlines():
                    fl = _fold(ln)
                    if re.search(rf"\b{re.escape(word)}\b", fl) \
                            and book.find_in_text(ln) == c.ad:
                        hits.append((i, text.find(fl) if fl in text else 0, ln))
            if len(hits) == 1:
                break
        if len(hits) == 1:
            i, pos, ln = hits[0]
            out.setdefault(i, []).append((pos, c))
            spelled = re.split(r"\s[-–—]\s|:", ln.strip(" •*-\t"), maxsplit=1)[0].strip()
            if spelled and _fold(spelled) != _fold(c.name) and len(spelled) <= 40:
                c.alt_names.append(spelled)
    return out


# ---- the interviewer's description -----------------------------------------
NOTE_MAX = 400        # a runaway line (a whole reply on one line) gets cut
_STARS = re.compile(r"(\d\s*)?((:star:|⭐)\s*)+", re.I)
_STAR_WORDS = re.compile(r"\b[1-5]\s*stars?\b", re.I)
_SHORTCODE = re.compile(r":[a-z0-9_+'-]+:", re.I)
_EMOJI = re.compile("[☀-➿\U0001F300-\U0001FAFF️]")
_TAIL = re.compile(r"(\s*(\bapplied to\b|\bfor\b|\b[1-5]\b|[-–—,;:?|./]))+\s*$", re.I)


def _slack_plain(text: str) -> str:
    """Slack markup to plain words: <@U1|Jorge> -> @Jorge, <url|label> -> label,
    and no * _ ~ that would bold/italicize half of our own reply."""
    t = re.sub(r"<@[A-Z0-9]+\|([^>]+)>", r"@\1", text or "")
    t = re.sub(r"<[^>|]+\|([^>]+)>", r"\1", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"[*_~`]", "", t)


def candidate_line(text: str, c: Candidate) -> str:
    """The line of a reply that is about `c` (sheet spelling or the one Slack
    used), "" if none."""
    for ln in (text or "").splitlines():
        fl = _fold(ln)
        if any(_fold(n) and _fold(n) in fl for n in [c.name] + c.alt_names):
            return ln
    return ""


def note_from_line(line: str, c: Candidate, book: Optional[TitleBook] = None) -> str:
    """Just the description out of an interviewer's line. Every interviewer
    writes it their own way (9/21 thread):
        • Angie Barron  - Dallas, sales, ... - can start asap - 3 stars :star:- Entry Level Sales Manager ? Garland TX:white_check_mark:
        • Brandon Freeman: Nevada Tx, ..., can start next week :white_check_mark:3:star:Entry Level Assistant Manager, McKinney, TX
        Devon Patrick - customer service - november 1st :white_check_mark::star::star::star::star:- Entry Level ...
    so: drop the name up front, the stars and emoji, and everything from the
    ad title on (the thread is already that ad). A ❌ reason ("declined, not
    willing to relocate") stays — it's the part Raf wants most."""
    t = _slack_plain(line)
    t = _STARS.sub(" ", t)
    t = _SHORTCODE.sub(" ", t)
    t = _EMOJI.sub(" ", t)
    t = _STAR_WORDS.sub(" ", t)
    for n in [c.name] + c.alt_names:
        m = re.search(r"\s+".join(map(re.escape, n.split())), t, re.I) if n.split() else None
        if m:
            t = t[m.end():]
            break
    # The ad title: cut at the first word where the rest of the line starts
    # with an ad: this candidate's (the book's key or the sheet's own typing)
    # or any running ad — 9/21 Shane Patrick's sheet row named a different ad
    # than his Slack line did. First 3 words survive a cut-off paste.
    keys = [c.ad or "", norm(c.title_raw)] + list(book.ads if book else [])
    heads = {" ".join(k.split()[:3]) for k in keys if k}
    heads.discard("")
    for m in re.finditer(r"\S+", t):
        rest = norm(t[m.start():])
        if any(rest.startswith(h) for h in heads):
            t = t[:m.start()]
            break
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s+([,;])", r"\1", t)
    t = re.sub(r"(\s*[-–—]\s*){2,}", " - ", t)
    t = _TAIL.sub("", t).strip(" \t•·:;,-–—|?")
    if len(t) > NOTE_MAX:
        t = t[:NOTE_MAX].rsplit(" ", 1)[0] + "…"
    return t


def _add_note(c: Candidate, text: str, book: Optional[TitleBook] = None) -> None:
    n = note_from_line(candidate_line(text, c), c, book)
    if n and n not in c.notes:
        c.notes.append(n)


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

        msgs = _replies(cl, parent["ts"], parent.get("_channel"))
        loose = first_name_matches(msgs, todays, book)
        for i, msg in enumerate(msgs):
            named = sorted(_full_named(msg, todays) + loose.get(i, []),
                           key=lambda p: p[0])
            named = [c for _, c in named]
            imgs = _images(msg)
            for c in named:
                _add_note(c, msg.get("text", ""), book)
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
