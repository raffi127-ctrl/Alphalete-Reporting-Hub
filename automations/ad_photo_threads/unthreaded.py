"""Eve 10/21: a 1st round that lands on no ad thread is said out loud.

Khalil's Dallas/Frisco and Denton ads went two weeks without a thread and
nobody knew: his channel keeps only the ads on its list (config._TITLE_ONLY),
and a row with a blank Ad Title goes nowhere in any office.

Eve 10/29: no more @channel note. A blank Ad Title is first looked up on
AppStream for appstream_ads.MAX_TRIES evenings (appstream_ads.py); only the
ones still nowhere after that -- and the ones whose typed Ad Title matches no
ad -- go to ONE pinned thread per channel ("1st rounds with no ad",
state[channel]["unplaced"]), one reply per evening with that evening's new
names. Whoever knows where they go finds them there. A name that later lands
on its ad is struck through in its reply. Interviews from the last
LOOKBACK_DAYS (today left out: the sheet is still being filled in).
"""
import datetime as dt
from typing import Callable, Dict, List, Optional, Tuple

from automations.ad_photo_threads import collect, config, post

LOOKBACK_DAYS = 7
_blank = collect.blank_title     # a blank title the Call List couldn't fill either

# Eve 10/29: each new reply in the "no ad" thread tags the recruiting team.
TAG_USERS = [
    "U07FWSYP3NV",   # Camila Hornos Kraschinsky
    "U07R68ZGHT6",   # Perla Falabella
]

HEADER = ("\U0001F4CC *1st rounds with no ad*\n"
          "Lucy couldn't place these 1st rounds on any ad thread (sheet, Slack, "
          "Call List and AppStream checked for {n} evenings). If you know where "
          "one goes, put the ad in the *Ad Title* column of the interviewers "
          "sheet. Names that later land on their ad get crossed out here.")


def find(day: dt.date, *, build: Optional[Callable] = None, cl=None,
         cache: Optional[dict] = None) -> List[Tuple[dt.date, "collect.Candidate"]]:
    """(day, candidate) for every interview in the window with no ad."""
    build = build or collect.build
    cache = {} if cache is None else cache
    out = []
    for n in range(LOOKBACK_DAYS, 0, -1):
        d = day - dt.timedelta(days=n)
        if d.weekday() not in config.POST_WEEKDAYS:
            continue
        rep = build(d, cl=cl, cache=cache)
        out += [(d, c) for c in rep.candidates if c.ad is None and not _blank(c.name)]
    return out


def _key(d: dt.date, c) -> str:
    return f"{d.isoformat()}|{c.name.strip().lower()}"


def still_trying(d: dt.date, c, ch_state: dict, lookup_on: bool) -> bool:
    """A blank Ad Title AppStream hasn't given up on yet: not said yet."""
    if not lookup_on or not _blank(c.title_raw):
        return False
    from automations.ad_photo_threads import appstream_ads
    return not appstream_ads.gave_up(ch_state, appstream_ads.key(d, c.name))


def line(d: dt.date, c, title_only: bool) -> str:
    """One name in the pinned thread, with why it's there."""
    who = f"{c.name.strip()} ({d.month}/{d.day})"
    if _blank(c.title_raw):
        return f"• {who}: no Ad Title in the sheet, not found on AppStream"
    why = ("not one of this channel's ads (new ad?)" if title_only
           else "doesn't match a running ad (cut off or misspelled?)")
    return f"• {who}: Ad Title \"{c.title_raw.strip()}\" {why}"


def reply_text(day: dt.date, lines: List[str]) -> str:
    tags = " ".join(f"<@{u}>" for u in TAG_USERS)
    return f"{tags} *{day.month}/{day.day}*\n" + "\n".join(lines)


def _struck(text: str) -> str:
    """A line crossed out as placed (once)."""
    return text if text.startswith("~") else f"~{text}~ ✅ placed"


def _thread(cl, channel: str, slot: dict) -> str:
    """The pinned thread's ts, opening (and pinning) it if it's gone."""
    ts = slot.get("ts")
    if ts and post._thread_alive(cl, channel, ts):
        return ts
    from automations.ad_photo_threads import appstream_ads
    r = cl.chat_postMessage(channel=channel, text=HEADER.format(n=appstream_ads.MAX_TRIES))
    ts = r["ts"]
    err = post._pin(cl, channel, ts, True)
    if err:
        print(f"  no-ad thread: pin failed: {err}")
    slot.clear()
    slot.update({"ts": ts, "said": [], "replies": {}})
    return ts


def check(day: dt.date, channel: str, *, title_only: bool, cl=None, build=None,
          cache: Optional[dict] = None, apply: bool = True,
          lookup_on: bool = False) -> Dict[str, object]:
    """Add the new no-ad interviews to the channel's pinned thread (only
    with `apply`) and cross out the ones that have landed since."""
    cl = cl or collect._client()
    missing = find(day, build=build, cl=cl, cache=cache)
    state = post._load_state()
    ch_state = state.get(channel, {})
    if lookup_on is None:
        lookup_on = config.appstream_ads_on(config.ACTIVE_KEY) if hasattr(config, "ACTIVE_KEY") \
            else bool(config.APPSTREAM_ADS_OFFICES)
    slot = ch_state.get("unplaced") or {}
    said = set(slot.get("said") or [])
    waiting = {_key(d, c) for d, c in missing if still_trying(d, c, ch_state, lookup_on)}
    give_up = [(d, c) for d, c in missing if _key(d, c) not in waiting]
    new = [(d, c) for d, c in give_up if _key(d, c) not in said]
    lines = [line(d, c, title_only) for d, c in new]
    # Said, still in the window, no longer missing = it landed on its ad.
    cutoff = (day - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    now_missing = {_key(d, c) for d, c in missing}
    placed = [k for k in said if k >= cutoff and k not in now_missing]
    text = reply_text(day, lines) if lines else ""
    out = {"missing": len(missing), "waiting": len(waiting), "new": len(new),
           "placed": len(placed), "text": text, "posted": False}
    if not apply or not (lines or placed):
        return out
    state = post._load_state()
    slot = state.setdefault(channel, {}).setdefault("unplaced", {})
    ts = _thread(cl, channel, slot)
    replies = slot.setdefault("replies", {})      # reply ts -> [[key, line], ...]
    for rts, rows in replies.items():
        hit = [r for r in rows if r[0] in placed and not r[1].startswith("~")]
        if not hit:
            continue
        for r in hit:
            r[1] = _struck(r[1])
        try:
            cl.chat_update(channel=channel, ts=rts,
                           text=reply_text(dt.date.fromisoformat(rows[0][2]),
                                           [r[1] for r in rows]))
        except Exception as e:                    # noqa: BLE001 -- never costs the new names
            print(f"  no-ad thread: strike-through failed: {type(e).__name__}: {str(e)[:120]}")
    if lines:
        r = cl.chat_postMessage(channel=channel, thread_ts=ts, text=text)
        replies[r["ts"]] = [[_key(d, c), ln, day.isoformat()] for (d, c), ln in zip(new, lines)]
        slot["said"] = sorted(set(slot.get("said") or []) | {_key(d, c) for d, c in new})
        out["posted"] = True
    # Keep the bookkeeping small: replies whose names are all out of the window.
    old = (day - dt.timedelta(days=LOOKBACK_DAYS + 14)).isoformat()
    slot["replies"] = {k: v for k, v in replies.items() if any(r[0] >= old for r in v)}
    slot["said"] = [k for k in slot.get("said") or [] if k >= old]
    post._save_state(state)
    return out
