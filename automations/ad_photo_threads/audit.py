"""1st Round Audit (Rafael 2026-10-22, by email): "interviewers report -
qualified / answered, threads with screenshots and ad titles -- please lets
make sure that stuff is still being posted ... can you create an audit that
sends us a message of this stuff isn't done".

Started for Aya's office, whose 1st rounds pass from Candela to Aya's own
admin on 10/23. Every weekday evening (config.AUDIT_AFTER, office clock) the
nightly tick checks THAT day:

  sheet  (the office's ARS REPORT tab)   a row per candidate, Qualify filled,
                                         Answer Call filled on every Qualified
                                         row, Ad Title filled
  Slack  (the office's 1st-rounds thread) the thread is up, every candidate
                                         has a screenshot and their ad title

Quiet when it's all done: a message goes out only when something is missing
(config.AUDIT_TO; "preview" = Eve's DM, which also gets an all-clear so she
can see it ran). Once per office per day (state[channel]["audit_done"]).
"""
import datetime as dt
import re
from typing import Dict, List, Optional

from automations.ad_photo_threads import collect, config, post

COL_ANSWER = "Answer Call"
EVE = "U088E2KJEV8"
# "_*Job ad:*_ Entry Level AT&T Associate, ..." -- how Candela labels it; an
# ad named anywhere in the block counts too (TitleBook.find_in_text).
# Markup can sit between the label and its colon ("_*Job ad*_:").
_AD_LABEL = re.compile(r"\b(job\s*)?ad\s*(title)?[\s*_]*[:\-]", re.I)
_PLACEHOLDER = {"", "-", "--", "n/a", "na", "none", "?", "."}
LIST_MAX = 8                      # names shown per line, then "+N more"


def _blank(s: str) -> bool:
    return (s or "").strip().lower() in _PLACEHOLDER


def _names(xs: List[str]) -> str:
    shown = ", ".join(xs[:LIST_MAX])
    return shown + (f" +{len(xs) - LIST_MAX} more" if len(xs) > LIST_MAX else "")


def check_rows(rows: List[Dict[str, str]]) -> Dict[str, List[str]]:
    """The sheet half, on the day's rows of the office's tab."""
    named = [r for r in rows if not _blank(r.get(config.COL_NAME, ""))]
    return {
        "no_qualify": [r[config.COL_NAME] for r in named if _blank(r.get(config.COL_QUALIFY, ""))],
        "no_answer": [r[config.COL_NAME] for r in named
                      if r.get(config.COL_QUALIFY, "").strip().lower() == "qualify"
                      and _blank(r.get(COL_ANSWER, ""))],
        "no_title": [r[config.COL_NAME] for r in named if _blank(r.get(config.COL_TITLE, ""))],
    }


def has_ad(block: str, book) -> bool:
    return bool(block) and (bool(_AD_LABEL.search(block)) or book.find_in_text(block) is not None)


def check_thread(cl, day: dt.date, todays: List["collect.Candidate"], book) -> Dict[str, object]:
    """The Slack half: who has no screenshot, who has no ad title in the thread."""
    src = config.SOURCES[0]
    parent = collect.find_thread(cl, src["thread_re"], day)
    if not parent:
        return {"thread": False, "no_photo": [], "not_in_thread": [], "no_ad": []}
    msgs = collect._replies(cl, parent["ts"], parent.get("_channel"))
    loose = collect.first_name_matches(msgs, todays, book)
    seen: Dict[int, dict] = {}            # id(candidate) -> {"img": bool, "ad": bool}
    for i, msg in enumerate(msgs):
        text = msg.get("text") or ""
        imgs = bool(collect._images(msg))
        for _, c in collect._full_named(msg, todays) + loose.get(i, []):
            s = seen.setdefault(id(c), {"img": False, "ad": False})
            s["img"] |= imgs
            s["ad"] |= has_ad(collect.candidate_block(text, c.name), book) or \
                any(has_ad(collect.candidate_block(text, n), book) for n in c.alt_names)
    # Last try, for the audit only: a reply line that STARTS with the first
    # name ("• Melissa K" for the sheet's Melissa Kutemeier, 10/22), when that
    # first name is on one line of the thread and one unmatched candidate.
    rest = [c for c in todays if id(c) not in seen and collect._fold(c.name).split()]
    firsts = [collect._fold(c.name).split()[0] for c in rest]
    for c, first in zip(rest, firsts):
        if len(first) < 3 or firsts.count(first) > 1:
            continue
        hits = [(msg, ln) for msg in msgs for ln in (msg.get("text") or "").splitlines()
                if re.match(rf"{re.escape(first)}\b", collect._fold(ln))]
        if len(hits) == 1:
            msg, ln = hits[0]
            seen[id(c)] = {"img": bool(collect._images(msg)),
                           "ad": has_ad(collect.candidate_block(msg.get("text") or "", ln.strip()), book)}
    out = {"thread": True, "no_photo": [], "not_in_thread": [], "no_ad": []}
    for c in todays:
        s = seen.get(id(c))
        if s is None:
            out["not_in_thread"].append(c.name)
            continue
        if not s["img"]:
            out["no_photo"].append(c.name)
        if not s["ad"]:
            out["no_ad"].append(c.name)
    return out


def message(owner: str, day: dt.date, n_rows: int, sheet: Dict[str, List[str]],
            thread: Dict[str, object]) -> str:
    """The post, or "" when everything is done."""
    when = f"{day:%A} {day.month}/{day.day}"
    lines = []
    if not thread["thread"]:
        lines.append("• *No 1st rounds thread* in Slack today.")
    if n_rows == 0:
        lines.append("• *Interviewers report:* no rows for today in the sheet.")
    for key, what in (("no_qualify", "Qualify is blank"),
                      ("no_answer", "Qualified but Answer Call is blank"),
                      ("no_title", "Ad Title is blank")):
        if sheet.get(key):
            lines.append(f"• *Interviewers report – {what}* ({len(sheet[key])}): {_names(sheet[key])}")
    for key, what in (("not_in_thread", "Not posted in the thread"),
                      ("no_photo", "No screenshot"),
                      ("no_ad", "No ad title in the thread")):
        if thread.get(key):
            lines.append(f"• *{what}* ({len(thread[key])}): {_names(thread[key])}")
    if not lines:
        return ""
    return f"*1st Round Audit – {owner} – {when}*\nNot done yet:\n" + "\n".join(lines)


def run(o: dict, day: dt.date, *, cl=None, cache: Optional[dict] = None) -> Dict[str, object]:
    """Read the office's sheet + thread for `day`; return the counts and text."""
    from automations.recruiting_report.fill import open_by_key
    config.use(o)
    cl = cl or collect._client()
    cache = {} if cache is None else cache
    sh = cache.get("_sh") or open_by_key(config.SHEET_ID)
    cache["_sh"] = sh
    tabs = collect.read_tabs(sh, cache)
    tab = config.SOURCES[0]["tab"]
    rows = [r for r in tabs.get(tab, []) if collect._parse_date(r.get(config.COL_DATE, "")) == day]
    book = collect.make_book(tabs, day)
    todays = [collect.Candidate(name=r[config.COL_NAME], title_raw=r.get(config.COL_TITLE, ""),
                                interviewer=r.get(config.COL_INTERVIEWER, ""),
                                qualify=r.get(config.COL_QUALIFY, ""),
                                stars=r.get(config.COL_STARS, ""), source=tab)
              for r in rows if not _blank(r.get(config.COL_NAME, ""))]
    for c in todays:
        c.ad = book.resolve(c.title_raw)
    sheet = check_rows(rows)
    thread = check_thread(cl, day, todays, book)
    return {"rows": len(rows), "sheet": sheet, "thread": thread,
            "text": message(o["owner"], day, len(rows), sheet, thread)}


def _done(channel: str, day: dt.date) -> bool:
    return day.isoformat() in post._load_state().get(channel, {}).get("audit_done", [])


def _mark_done(channel: str, day: dt.date) -> None:
    state = post._load_state()
    done = state.setdefault(channel, {}).setdefault("audit_done", [])
    done.append(day.isoformat())
    done[:] = sorted(set(done))[-30:]
    post._save_state(state)


def if_due(o: dict, now: dt.datetime, *, force_day: Optional[dt.date] = None,
           to: Optional[str] = None) -> Optional[str]:
    """The tick's entry. Due once per office per weekday after AUDIT_AFTER on
    the office's clock; `force_day` skips the clock and the once-a-day lock
    (a manual re-check). Returns where it posted, or None."""
    if not config.audit_on(o["key"]):
        return None
    day = force_day or now.date()
    if not force_day:
        if day.weekday() not in config.POST_WEEKDAYS or (now.hour, now.minute) < config.AUDIT_AFTER:
            return None
        if _done(o["live_channel"], day):
            return None
    cl = collect._client()
    got = run(o, day, cl=cl)
    to = to or config.AUDIT_TO
    preview = to == "preview"
    text = got["text"]
    if preview:
        text = ("[PREVIEW – only you see this] " + (text or
                f"*1st Round Audit – {o['owner']} – {day.month}/{day.day}*: all done "
                f"({got['rows']} rows). Nothing would be posted."))
    print(text or f"[audit] {o['owner']} {day}: all done ({got['rows']} rows)")
    where = None
    if text:
        if preview:
            where = cl.conversations_open(users=EVE)["channel"]["id"]
        else:
            where = to
            tags = " ".join(f"<@{u}>" for u in config.AUDIT_TAG)
            text = f"{tags} {text}".strip()
        cl.chat_postMessage(channel=where, text=text, unfurl_links=False)
    if not force_day:
        _mark_done(o["live_channel"], day)
    return where
