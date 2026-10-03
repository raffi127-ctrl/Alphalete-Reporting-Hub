"""Carlos's fourteen, read off RAF'S SaraPlus, texted to CARLOS'S chats.

Carlos 2026-09-29: "can you check his SaraPlus for credit checks and sales for
those 14 people? And send that out on the chat that you would normally send
out on the SAL-2" -- NEW A Players and ATT B2B Leaders, the rooms his own
SaraPlus standings already go to. "This shouldn't negatively affect anything
that is getting posted on Rafael's stuff."

SO IT IS PURELY ADDITIVE. The sweep already scrapes every seller on Raf's code
(`agents`) and every credit-check count (`records`); calc.calculate drops
Carlos's reps from Raf's board, and this reads the same scrape a second time
for exactly those reps. No second login, nothing on Raf's board, his texts or
his Slack changes, and the call in run.sweep is wrapped so a failure here can
only cost this feed.

THE ROSTER IS THE ONE LIST (total_knocks.guests.GUEST_REPS) -- the same
fourteen the knock boards split on, matched the same way.

WHAT GOES OUT, only when something moved:
  * SAL-7 -- the fourteen's sales standings, 🔥 on who just sold. The first
    sweep of a day settles quietly (standings once, no flames), exactly like
    Raf's own board, so a mid-day start never announces old sales as new.
  * SAL-8 -- a credit-check line per rep whose count went up.
Both ride one text per sweep, so a sale and its credit check arrive together.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

from automations.alphalete_sales_board import calc
from automations.alphalete_sales_board import config as C
from automations.alphalete_sales_board import notify as N
from automations.alphalete_sales_board import state as S
from automations.shared.name_case import titlecase_name
from automations.total_knocks import guests

GUEST = "Carlos Hidalgo"
GROUPS = ["NEW A Players", "ATT B2B Leaders"]     # SAL-2's chats
SECTION = "_guest_sales"                          # listed in state.prune
HEADER = "Fiber Team Sales"


def is_guest(name: str) -> bool:
    return guests.guest_for(C.GUEST_HOST, str(name or "")) == GUEST


def guest_sales(agents: List[Dict]) -> Dict[str, Dict[str, int]]:
    """{rep: metrics} for the fourteen, reps with a zero day left out."""
    out = {}
    for a in agents:
        name = str(a.get("name", ""))
        if not is_guest(name):
            continue
        m = calc.metrics_for(a)
        if any(m.values()):
            out[titlecase_name(name)] = m
    return out


def message(today: Dict[str, Dict[str, int]], prev, records: Dict[str, int],
            rec_gained: Dict[str, int], *, raf_baseline: bool) -> str:
    """The one text for this sweep, or "" when nothing of theirs moved."""
    first = prev is None
    fired = [] if first else sorted(
        rep for rep, m in today.items()
        if any(int(m.get(k, 0)) > int(((prev or {}).get(rep) or {}).get(k, 0))
               for k in S.METRICS))
    parts = []
    if today and (fired or first):
        parts.append("%s\n\n%s" % (HEADER, N.leaderboard(today, fired)))
    # Credit checks ride Raf's own records state, so they are real deltas
    # from the first run of this feed -- only Raf's own settling pass (no
    # state for the day at all) holds them back, as it does in his room.
    checks = {rep: up for rep, up in rec_gained.items() if is_guest(rep)}
    if checks and not raf_baseline:
        parts.append("\n".join(
            "Fiber — " + N.records_line(rep, records.get(rep, up), up).replace(":mag:", "\U0001F50D")
            for rep, up in sorted(checks.items())))
    return "\n\n".join(parts)


def run(data: Dict, day: dt.date, agents: List[Dict], records: Dict[str, int],
        rec_gained: Dict[str, int], *, raf_baseline: bool, send: bool,
        apply_writes: bool, log=print) -> Dict:
    """Text what moved for the fourteen; return `data` with their state
    folded in (saved by the sweep, on a real run only)."""
    today = guest_sales(agents)
    prev = (data.get(SECTION) or {}).get(day.isoformat())
    body = message(today, prev, records, rec_gained, raf_baseline=raf_baseline)
    if body:
        for group in GROUPS:
            # One room failing must not cost the other its text.
            try:
                N.text_group(group, body, dry_run=not send, log=log)
            except Exception as e:  # noqa: BLE001
                log("  guest feed -> %s FAILED: %s: %s"
                    % (group, type(e).__name__, str(e)[:160]))
    else:
        log("guest feed: nothing new for %s's reps" % GUEST)
    if apply_writes:
        was = dict(prev or {})
        for rep, m in today.items():
            old = was.get(rep) or {}
            was[rep] = {k: max(int(m.get(k, 0)), int(old.get(k, 0)))
                        for k in S.METRICS}
        data.setdefault(SECTION, {})[day.isoformat()] = was
    return data


def standings_now(day: Optional[dt.date] = None) -> str:
    """READ-ONLY: the fourteen's standings as of the last sweep, from the
    state file -- no SaraPlus login. For 'who has a sale right now'."""
    day = day or dt.date.today()
    data = S.load()
    today = (data.get(SECTION) or {}).get(day.isoformat()) or {}
    if not today:
        return "no sales recorded for %s's reps on %s yet" % (GUEST, day.isoformat())
    return "%s (as of last sweep)\n\n%s" % (HEADER, N.leaderboard(today, []))
