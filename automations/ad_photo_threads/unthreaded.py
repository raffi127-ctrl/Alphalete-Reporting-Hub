"""Eve 10/21: a 1st round that lands on no ad thread is said out loud.

Khalil's Dallas/Frisco and Denton ads went two weeks without a thread and
nobody knew: his channel keeps only the ads on its list (config._TITLE_ONLY),
and a row with a blank Ad Title goes nowhere in any office. After the evening
post, the office's indeed-photos channel gets one @channel message listing
the interviews from the last LOOKBACK_DAYS (today left out: the sheet is
still being filled in) that have no thread. Each interview is said once
(state[channel]["unthreaded_said"]); a row fixed later just drops off.
"""
import datetime as dt
from collections import Counter
from typing import Callable, Dict, List, Optional, Tuple

from automations.ad_photo_threads import collect, config, post

LOOKBACK_DAYS = 7
_blank = collect.blank_title     # a blank title the Call List couldn't fill either


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


def message(missing: List[Tuple[dt.date, "collect.Candidate"]], title_only: bool) -> str:
    """The channel post, or "" when there's nothing to say."""
    blank = [(d, c) for d, c in missing if _blank(c.title_raw)]
    typed = Counter(c.title_raw.strip() for _, c in missing if not _blank(c.title_raw))
    if not blank and not typed:
        return ""
    n = len(blank) + sum(typed.values())
    lines = [f"<!channel> {n} 1st round{'s' if n != 1 else ''} didn't land on any ad thread:"]
    if blank:
        who = ", ".join(f"{c.name.strip()} ({d.month}/{d.day})" for d, c in blank)
        lines.append(f"• *No Ad Title in the sheet:* {who}. Please fill in their Ad Title.")
    if typed:
        ask = ("Is this a new ad? Reply here and it gets its own thread."
               if title_only else "It reads like a cut-off or misspelling of a running "
               "ad, so it wasn't guessed. Please check the spelling in the sheet.")
        for t, k in typed.most_common():
            lines.append(f"• *Ad not recognized:* \"{t}\" ({k}). {ask}")
    return "\n".join(lines)


def check(day: dt.date, channel: str, *, title_only: bool, cl=None, build=None,
          cache: Optional[dict] = None, apply: bool = True) -> Dict[str, object]:
    """Find, say the new ones in `channel` (only with `apply`), remember them."""
    cl = cl or collect._client()
    missing = find(day, build=build, cl=cl, cache=cache)
    state = post._load_state()
    said = set(state.get(channel, {}).get("unthreaded_said", []))
    new = [(d, c) for d, c in missing if _key(d, c) not in said]
    text = message(new, title_only)
    if text and apply:
        cl.chat_postMessage(channel=channel, text=text)
        state = post._load_state()
        keep = state.setdefault(channel, {}).setdefault("unthreaded_said", [])
        keep += [_key(d, c) for d, c in new]
        cutoff = (day - dt.timedelta(days=LOOKBACK_DAYS + 7)).isoformat()
        keep[:] = sorted(k for k in set(keep) if k >= cutoff)
        post._save_state(state)
    return {"missing": len(missing), "new": len(new), "text": text, "posted": bool(text and apply)}
