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
    # Jairo Ruiz's tab (10/8) has the names in the column after "1st Round
    # Interviewer" -- where every other South Shore tab says "Full Name" --
    # with its header left blank. Read a blank header there as Full Name
    # rather than editing someone else's tab.
    if config.COL_NAME not in head and config.COL_INTERVIEWER in head:
        i = head.index(config.COL_INTERVIEWER) + 1
        if i < len(head) and not head[i]:
            head[i] = config.COL_NAME
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
# slack_sdk's 30 s default is too short for a reply carrying a day's
# screenshots: 10/2 five of Khalil's 23 re-posted days died with "The read
# operation timed out" in files_upload_v2, part-posted.
SLACK_TIMEOUT_S = 180


def _client():
    from automations.shared import slack_metrics_post as smp
    cl = smp._client()
    cl.timeout = SLACK_TIMEOUT_S
    return cl


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


def _print_day_posts(cl, day: dt.date) -> None:
    """Samuel 10/21: "no thread found" for days, and only Lucy (the mini) can
    read his channel -- so say what WAS posted that day, to see the new wording."""
    lo, hi = _day_bounds(day)
    for ch in source_channels():
        try:
            msgs = cl.conversations_history(channel=ch, oldest=str(lo), latest=str(hi),
                                            limit=50).get("messages", [])
        except Exception as e:                   # noqa: BLE001 — diagnostics only
            print(f"  !! {ch}: {type(e).__name__}: {str(e)[-80:]}")
            continue
        print(f"  !! {ch} on {day}: {len(msgs)} post(s); the pattern looks for "
              f"{[s['thread_re'].pattern for s in config.SOURCES]}")
        for m in msgs[:12]:
            text = " ".join((m.get("text") or "").split())[:90]
            print(f"  !!   {m.get('reply_count', 0)} replies | {text}")


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


def candidate_block(text: str, name: str) -> str:
    """The candidate's part of a Slack reply: the line with their name and
    the lines under it, up to the next "•" bullet. Khalil 10/21: the name sits
    alone on its line ("• Guadalupe Flores") and the ad is on the next one, so
    the name line alone found no ad for a blank sheet title."""
    lines = text.splitlines()
    i = next((i for i, ln in enumerate(lines) if _fold(name) in _fold(ln)), None)
    if i is None:
        return ""
    out = [lines[i]]
    for ln in lines[i + 1:]:
        if ln.lstrip().startswith("•"):
            break
        out.append(ln)
    return "\n".join(out)


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


# ---- rows off Slack (config.ROWS_FROM_SLACK) ---------------------------------
# Ana's reply in Valeria's thread (10/21), one per candidate:
#   "Devin Hyatt – AT&amp;T Team Member – YES – 1:15 – :star::star::star::star:☆ (4/5)"
# then the description. Before 10/15 there was no ad: "*Leeann Rolon – YES –
# 1:15 PM –* :star:..." -- that row has a blank title.
_DASH = re.compile(r"\s+[–—-]\s+")
_SLACK_ROWS: Dict[tuple, List[Dict[str, str]]] = {}


def slack_row(text: str, day: dt.date) -> Optional[Dict[str, str]]:
    """The sheet-shaped row for one candidate's reply, None if no line reads
    "Name – YES/NO – ..." or "Name – Ad – ..."."""
    for ln in (text or "").replace("&amp;", "&").replace("*", "").splitlines():
        parts = [p.strip() for p in _DASH.split(ln.strip(" •_"))]
        if len(parts) < 2 or not _fold(parts[0]):
            continue
        verdict = next((p for p in parts[1:] if _fold(p) in ("yes", "no")), "")
        title = parts[1] if _fold(parts[1]) not in ("yes", "no") else ""
        # Ivonne Zarate 10/20: "Name – Ad – 4:15 – :star:x3", the YES/NO left out.
        if not verdict and not (len(parts) >= 3 and re.match(r"[A-Za-z]", title)):
            continue
        out_of = re.search(r"\((\d)\s*/\s*5\)", ln)
        stars = out_of.group(1) if out_of else str(ln.count(":star:") or "")
        return {config.COL_DATE: day.strftime("%m/%d/%Y"), config.COL_NAME: parts[0],
                config.COL_TITLE: title, config.COL_INTERVIEWER: "",
                config.COL_QUALIFY: {"yes": "Qualify", "no": "Disqualify"}.get(_fold(verdict), ""),
                config.COL_STARS: stars}
    return None


def slack_rows(cl=None) -> List[Dict[str, str]]:
    """Every candidate in the office's daily threads since THREADS_SINCE, as
    sheet rows. Read once per process per office."""
    memo = (tuple(source_channels()), tuple(s["thread_re"].pattern for s in config.SOURCES))
    if memo in _SLACK_ROWS:
        return _SLACK_ROWS[memo]
    cl = cl or _client()
    since = dt.datetime.combine(dt.date.fromisoformat(config.THREADS_SINCE), dt.time(0), CENTRAL)
    rows: List[Dict[str, str]] = []
    for ch in source_channels():
        cursor = None
        while True:
            resp = cl.conversations_history(channel=ch, oldest=str(since.timestamp()),
                                            limit=200, cursor=cursor)
            for m in resp.get("messages", []):
                if not any(s["thread_re"].search(m.get("text", "") or "") for s in config.SOURCES):
                    continue
                day = dt.datetime.fromtimestamp(float(m["ts"]), CENTRAL).date()
                for reply in _replies(cl, m["ts"], ch):
                    row = slack_row(reply.get("text") or "", day)
                    if row:
                        rows.append(row)
            cursor = (resp.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
    _SLACK_ROWS[memo] = rows
    return rows


# ---- the day -----------------------------------------------------------------
def read_tabs(sh, cache: Optional[dict] = None) -> Dict[str, List[Dict[str, str]]]:
    """The office's source tabs that exist, {tab: rows}. With `cache` (a dict
    kept by the caller) the sheet is read once for a whole week of days --
    the weekly layout builds Monday..today every evening (Sheets quota)."""
    if cache is not None and "_tabs" in cache:
        return cache["_tabs"]
    if config.ROWS_FROM_SLACK:
        tabs = {s["tab"]: slack_rows() for s in config.SOURCES}
        if cache is not None:
            cache["_tabs"] = tabs
        return tabs
    have = {w.title for w in sh.worksheets()}
    tabs = {s["tab"]: _read_tab(sh, s["tab"]) for s in config.SOURCES if s["tab"] in have}
    if cache is not None:
        cache["_tabs"] = tabs
    return tabs


def make_book(tabs: Dict[str, List[Dict[str, str]]], day: dt.date) -> TitleBook:
    """The ads as of `day`: every title typed in the last TITLE_LOOKBACK_DAYS."""
    since = day - dt.timedelta(days=config.TITLE_LOOKBACK_DAYS)
    return TitleBook(
        (r[config.COL_TITLE] for rows in tabs.values() for r in rows
         if (_parse_date(r[config.COL_DATE]) or dt.date.min) >= since),
        aliases=getattr(config, "TITLE_ALIASES", None),
        only=getattr(config, "TITLE_ONLY", None))


# ---- the ad AppStream saw ----------------------------------------------------
# Eve 10/24 ("no podes resolver vos antes de mandarlos?"): a blank Ad Title the
# Slack line didn't fill either is looked up on the Call List tab --
# applicant_tracker's morning import of AppStream, with the ad each applicant
# answered. Used only when it's ONE ad the office already has a thread for:
# checked against 10 offices' typed titles (10/24) it agreed 93-97% (Isaiah
# 72%: city-less vs city ads), and most misses were people who applied to two
# ads -- those stay in the channel note. Org offices only (applicant_tracker's
# OFFICE_IDS); Drew, Mercy, Jennifer... aren't imported, so they still get it.
CALL_LIST_DAYS = 60
# Typed as a placeholder, not an ad or a name (Aya's "-", George's "N/A").
_PLACEHOLDER = {"", "-", "--", "n/a", "na", "none", "?", "."}
_CALL_LIST: Optional[Dict[tuple, List[tuple]]] = None


def blank_title(s: str) -> bool:
    return (s or "").strip().lower() in _PLACEHOLDER


def _call_list() -> Dict[tuple, List[tuple]]:
    """{(office id, folded full name): [(date, ad)]}. Read once per process."""
    global _CALL_LIST
    if _CALL_LIST is None:
        from automations.ad_sales_board import names
        from automations.funnel_board.roster import CAPTAINSHIP, ORG
        from automations.recruiting_report.fill import _retry, open_by_key
        oid: Dict[str, str] = {}
        for name, office_id, owner in list(ORG) + list(CAPTAINSHIP):
            oid[names._key(owner)] = oid[names._key(name)] = office_id
        for drift, name in names._ALIASES.items():
            oid[drift] = oid.get(names._key(name), "")
        ws = open_by_key(names.TRACKER_ID).worksheet("Call List")
        rows = _retry(lambda: ws.get("A2:I", value_render_option="UNFORMATTED_VALUE"))
        out: Dict[tuple, List[tuple]] = {}
        for r in rows:
            r = list(r) + [""] * (9 - len(r))
            d, o = names._serial_date(r[7]), oid.get(names._key(r[0]))
            if d and o:
                out.setdefault((o, _fold(f"{r[1]} {r[2]}")), []).append(
                    (d, names.strip_wrapper(str(r[8]))))
        _CALL_LIST = out
    return _CALL_LIST


def call_list_ad(c: Candidate, day: dt.date, office_ids, book: TitleBook,
                 seen: Optional[Dict[tuple, List[tuple]]] = None) -> Optional[str]:
    """The one running ad AppStream has `c` applying to by `day`, else None."""
    seen = _call_list() if seen is None else seen
    since = day - dt.timedelta(days=CALL_LIST_DAYS)
    keys = {book.resolve(ad) for o in office_ids
            for d, ad in seen.get((o, _fold(c.name)), []) if since <= d <= day}
    keys = {k for k in keys if k and book.running(k)}
    return keys.pop() if len(keys) == 1 else None


def build(day: dt.date, *, sh=None, cl=None, cache: Optional[dict] = None) -> DayReport:
    from automations.recruiting_report.fill import open_by_key
    if cache is not None and "_tabs" in cache:
        sh = sh or cache.get("_sh")
    sh = sh or open_by_key(config.SHEET_ID)
    if cache is not None:
        cache["_sh"] = sh
    cl = cl or _client()

    tabs = read_tabs(sh, cache)
    have = set(tabs)
    sources = [s for s in config.SOURCES if s["tab"] in have]
    book = make_book(tabs, day)
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
                _print_day_posts(cl, day)
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
                    c.ad = book.find_in_text(candidate_block(msg.get("text") or "", c.name))
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

    blank = [c for c in rep.candidates if c.ad is None and blank_title(c.title_raw)]
    if blank:
        oids = {s["office_id"] for s in sources if s.get("office_id")}
        try:
            for c in blank:
                c.ad = call_list_ad(c, day, oids, book)
                if c.ad:
                    print(f"  ad from the Call List: {c.name} -> {c.ad}")
        except Exception as e:                # noqa: BLE001 -- never costs the post
            print(f"  call list ad lookup failed: {type(e).__name__}: {str(e)[:160]}")
        for c in blank:
            if c.ad is None:
                c.ad = appstream_ad(c, day, book)
    return rep


def appstream_ad(c: Candidate, day: dt.date, book: TitleBook,
                 found: Optional[Dict[str, str]] = None) -> Optional[str]:
    """The ad appstream_ads.py read off `c`'s AppStream record (kept in the
    state file), as an ad key. One ad per record, straight from Indeed's mail,
    so unlike the Call List it may start the ad's thread if it has none."""
    from automations.ad_photo_threads import appstream_ads
    if found is None:
        from automations.ad_photo_threads import post
        found = (post._load_state().get(config.LIVE_CHANNEL_ID) or {}).get("appstream_ads") or {}
    ad = found.get(appstream_ads.key(day, c.name))
    return book.resolve(ad) if ad else None
