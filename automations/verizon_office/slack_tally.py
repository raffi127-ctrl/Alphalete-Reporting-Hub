"""Live Verizon sales off the office's own running tally in #alphalete-gp-sales.

    python -m automations.verizon_office.slack_tally                 # preview today
    python -m automations.verizon_office.slack_tally --send          # relay as 'nicolas'

WHAT THE OFFICE POSTS (read 2026-11-06). Every time a rep closes, someone
reposts the WHOLE list with that rep bumped up:

    Verizon :fire:
    At&t :fire:
    SAMANTHA :drop_of_blood:
    JAYDEN :drop_of_blood::drop_of_blood::drop_of_blood::drop_of_blood:
    Jacob :calling::calling::calling:
    16/50:fire::fire:

  :drop_of_blood: = one VERIZON LINE (Nico's reps; Megan 2026-11-06: "the
                    number of emojis is the number of lines")
  :calling:       = one AT&T sale (Carlos's NDS reps) -- NOT counted here
  "16/50"         = the room's combined total vs the goal -- not used

Nico 2026-11-06: "It has to be tracking from slack that's how it does it now."

THE DAY. Sales run from about noon; a list posted before 10:00 CT (e.g. 08:09
on 11/6, 44/50) is LAST NIGHT's final reposted, so it belongs to the previous
day. Each rep's count for the day is the MAX seen in that day's lists: a stale
copy reposted with a lower number must never take a sale away.

NAMES. The list uses first names (or a surname: BAUTISTA). They are matched to
the office's full names from the newest Credico Sales Verification; a name that
matches nobody, or more than one rep, keeps its list spelling and is reported --
never guessed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

CHANNEL = "C07J46MQNUX"          # #alphalete-gp-sales (Nico + Carlos share it)
OFFICE_KEY = "nicolas"
TZ = ZoneInfo("America/Chicago")
DAY_STARTS = dt.time(10, 0)      # earlier posts are last night's list reposted
VZ = ":drop_of_blood:"
# LIST NAME -> Credico full name, ONLY where the evidence is the numbers
# themselves: the 11/5 tally matched Credico's Sales Verification Thursday
# column rep for rep (Megan's session 2026-11-06).
REP_ALIASES = {
    "SAMANTHA": "Brandy Ahumada Ruiz",   # tally 3 = Credico Thu 3; Slack "Samantha Ruiz" samanthaahumada817@
    "BAUTISTA": "William Bautista",      # tally 6 = William Thu 6 (Richard 0); posts as bautista4.inc@
}
_LINE = re.compile(r"^\s*[*_~]*([A-Za-zÀ-ÿ'][A-Za-zÀ-ÿ' .-]*?)[*_~]*\s*((?::drop_of_blood:\s*)+)")


def is_tally(text: str) -> bool:
    return VZ in (text or "") and bool(re.search(r"\bverizon\b", text or "", re.I))


def parse(text: str) -> Dict[str, int]:
    """{LIST NAME: verizon sales} from one tally post."""
    out: Dict[str, int] = {}
    for line in (text or "").splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        if not name or name.lower() in ("verizon", "at&t", "att"):
            continue
        n = m.group(2).count(VZ)
        out[name.upper()] = max(out.get(name.upper(), 0), n)
    return out


def sales_day(when: dt.datetime) -> dt.date:
    local = when.astimezone(TZ)
    return local.date() - dt.timedelta(days=1) if local.time() < DAY_STARTS else local.date()


def day_counts(posts: Iterable[Tuple[dt.datetime, str]], day: dt.date) -> Dict[str, int]:
    """MAX per rep over the day's tally posts (a stale repost never lowers it)."""
    best: Dict[str, int] = {}
    for when, text in posts:
        if sales_day(when) != day or not is_tally(text):
            continue
        for name, n in parse(text).items():
            best[name] = max(best.get(name, 0), n)
    return best


def match_names(counts: Dict[str, int], roster: List[str]) -> Tuple[Dict[str, int], List[str]]:
    """List names -> roster full names. A list name matches a rep when it equals
    their first name or any surname word; zero or 2+ matches keep the list
    spelling and are reported."""
    out: Dict[str, int] = {}
    unmatched: List[str] = []
    for name, n in counts.items():
        if name.upper() in REP_ALIASES:
            full = REP_ALIASES[name.upper()]
            out[full] = out.get(full, 0) + n
            continue
        key = name.lower()
        hits = [r for r in roster if key in [w.lower() for w in r.split()]]
        first = [r for r in hits if r.split()[0].lower() == key]
        pick = first if len(first) == 1 else hits
        if len(pick) == 1:
            out[pick[0]] = out.get(pick[0], 0) + n
        else:
            unmatched.append(f"{name} ({'no match' if not pick else 'matches ' + ', '.join(pick)})")
            out[name.title()] = out.get(name.title(), 0) + n
    return out, unmatched


def roster() -> List[str]:
    """Nico's reps, full names, from the newest Credico Sales Verification."""
    from automations.verizon_office import offices as OF, parse as SV, run as RUN
    import glob
    path = None
    try:
        path = RUN.fetch(OF.get(OFFICE_KEY), "sales", since_days=30)
    except Exception:  # noqa: BLE001 — fall back to the copy on disk
        path = None
    if not path:
        local = sorted(glob.glob("output/_verizon_inventory/outlook/Sales Verification*.xlsx"))
        path = local[-1] if local else None
    if not path:
        return []
    names = set()
    for w in SV.read_sales_verification(path).weeks:
        names.update(r.name for r in w.reps)
    return sorted(names)


def fetch(day: dt.date) -> List[Tuple[dt.datetime, str]]:
    """The channel's posts for `day` (plus the next morning's early reposts)."""
    from automations.shared import slack_metrics_post as S
    start = dt.datetime.combine(day, DAY_STARTS, TZ)
    end = start + dt.timedelta(days=1)
    client = S._client()
    out, cursor = [], None
    while True:
        r = client.conversations_history(channel=CHANNEL, oldest=str(start.timestamp()),
                                         latest=str(end.timestamp()), limit=200, cursor=cursor)
        for m in r.get("messages", []):
            if m.get("bot_id") or m.get("subtype"):
                continue
            out.append((dt.datetime.fromtimestamp(float(m["ts"]), dt.timezone.utc), m.get("text", "")))
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return out


def run(day: dt.date, *, send: bool, log=print) -> int:
    counts = day_counts(fetch(day), day)
    sales, unmatched = match_names(counts, roster())
    log("Verizon tally %s: %d rep(s), %d line(s)" % (day, len(sales), sum(sales.values())))
    for rep, n in sorted(sales.items(), key=lambda kv: -kv[1]):
        log("  %-28s %d" % (rep, n))
    if unmatched:
        log("  ⚠ names not matched to the Credico roster: " + "; ".join(unmatched))
    if not send:
        log("preview — nothing sent")
        return 0
    # NO LINES YET STILL RELAYS -- an empty reading. The owner sales texts list
    # only offices that relayed today (no row = "agent did not run"), and Megan
    # 2026-11-07: "nico should be listed at 0 then on the sales text".
    from automations.icd_alerts import offices as O, relay as R
    from automations.verizon_office import house_feed as HF
    key = HF._relay_key(OFFICE_KEY)
    if not key:
        log("✗ no active %r key on Relay Keys — nothing sent" % OFFICE_KEY)
        return 1
    rec = {"office_key": OFFICE_KEY, "relay_key": key, "relay_url": O.RELAY_URL, "campaign": "verizon"}
    # NOTHING POSTED YET = every Credico rep at 0, not an empty reading: the
    # relay reader drops an empty sales cell as "no reading", and the owner
    # texts list only offices with one (Megan 2026-11-07: "nico should be
    # listed at 0"). The same shape an AT&T office has before its first sale.
    payload_sales = ({r: {"Lines": n} for r, n in sales.items()} if sales
                     else {r: {"Lines": 0} for r in roster()})
    body = R.payload({}, day, rec, sales=payload_sales)
    body["agent"] = "verizon_slack_tally"
    R._post(rec["relay_url"], json.dumps(body).encode("utf-8"))
    log("✓ relayed %d seller(s) as %s%s" % (len(sales), OFFICE_KEY,
                                         "" if sales else " (none yet: an empty reading, so he shows at 0)"))
    return 0


# RUNS ON LUCY 4 as its own 5-minute job (com.alphalete.verizon-slack-tally),
# NOT inside Lucy 1's poster -- Megan 2026-11-07: "don't do it on lucy 1 as
# that's the most weighed down machine" -- and never on the office's machine,
# which must not hold Lucy's Slack sign-in. LIVE_OFFICES gates tick(); empty
# until Nico is on ECO ("we can't take anything live until ..."). Add
# "nicolas" the day he is, then `lucy rerun install_verizon_slack_tally_agent`.
LIVE_OFFICES: tuple = ("nicolas",)   # Nico on ECO 2026-11-07
EVERY_MINUTES = 5
_STATE = None


def tick(*, send: bool, log=print) -> int:
    """One poster tick: relay the tally at most every EVERY_MINUTES, only for
    LIVE_OFFICES, only in the sales day's hours (12:00-00:59 CT)."""
    global _STATE
    if OFFICE_KEY not in LIVE_OFFICES:
        return 0
    import os
    from pathlib import Path
    now = dt.datetime.now(TZ)
    if 1 <= now.hour < 12:
        return 0
    _STATE = _STATE or Path(os.path.expanduser("~/.config/recruiting-report/verizon_tally_last"))
    try:
        last = dt.datetime.fromisoformat(_STATE.read_text().strip())
        if now - last < dt.timedelta(minutes=EVERY_MINUTES):
            return 0
    except (OSError, ValueError):
        pass
    try:
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        _STATE.write_text(now.isoformat())
    except OSError:
        pass
    return run(sales_day(dt.datetime.now(dt.timezone.utc)), send=send, log=log)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default: today's sales day)")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--tick", action="store_true", help="the Lucy 4 job: LIVE_OFFICES only, gated + throttled")
    a = ap.parse_args(argv)
    if a.tick:
        return tick(send=a.send)
    day = dt.date.fromisoformat(a.date) if a.date else sales_day(dt.datetime.now(dt.timezone.utc))
    return run(day, send=a.send)


if __name__ == "__main__":
    sys.exit(main())
