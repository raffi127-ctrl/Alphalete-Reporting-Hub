"""Who OwnerVille's search has already said it does not have.

THE COST THIS EXISTS TO CUT. Measured on Lucy 3, 2026-11-19: the `ownerville`
step took 10m19s of a 19m19s run. The log said why --

    ownerville: 29 of this week's 29 were not on page one
    time budget reached; 10 not searched this run
    searched 19 in 515s — 21 still not found in OwnerVille

-- so each name costs ~27 seconds, and TWENTY-ONE OF TWENTY-NINE were not
there at all. Most of that time is spent looking for new starts nobody has
added to OwnerVille yet, and the next run spends it again, and the one after
that. The budget then runs out and ten people are never searched, so the time
is not only wasted, it crowds out the names that would have been found.

So a miss is remembered for a while. Not for ever: somebody added at 2pm has
to be picked up the same day, which is the whole point of the board scanning
through the day. A name is re-searched once its miss goes stale, and until
then the budget goes to names that have never been asked about.

WHY NOT REMEMBER THE HITS INSTEAD. A hit does not need remembering: a person
who is in OwnerVille comes back on page one of the table read, before any
search happens. It is only the absences that cost.

NEVER A REASON TO TICK ANYTHING. This decides what to SEARCH FOR, nothing
else. A remembered miss means "do not spend 27 seconds asking again yet", and
never "this person is not in OwnerVille" -- unread stays unread, which is the
rule the whole board rests on.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from automations.icd_onboarding import board as B

# LONGER THAN THE GAP BETWEEN RUNS, or it saves nothing. Hourly today and
# headed for every 15 minutes, so two hours means a name nobody has added is
# asked about once or twice a day instead of fifteen times -- while anybody
# genuinely added is still picked up within two hours.
COOLDOWN_MIN = 120

PATH = Path(__file__).resolve().parents[2] / "output" / "ov_misses.json"


def _load() -> Dict[str, str]:
    try:
        if PATH.exists():
            got = json.loads(PATH.read_text(encoding="utf-8"))
            return got if isinstance(got, dict) else {}
    except Exception:          # noqa: BLE001 -- a bad cache is not a failure
        pass
    return {}


def _save(state: Dict[str, str]) -> None:
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(state, indent=1, sort_keys=True),
                        encoding="utf-8")
    except Exception:          # noqa: BLE001 -- never lose a run to the cache
        pass


def _key(office_key: str, week_start, name: str) -> str:
    """Per office AND per week: the same person in a later week is a new
    question, and two offices can hold the same name."""
    return "%s|%s|%s" % (str(office_key).strip().lower(), week_start,
                         B._fold(name))


def fresh(office_key: str, week_start, names: Iterable[str],
          now: Optional[dt.datetime] = None) -> List[str]:
    """The names worth searching for: never asked, or asked long enough ago."""
    now = now or dt.datetime.now()
    state = _load()
    out = []
    for name in names:
        said = state.get(_key(office_key, week_start, name))
        if not said:
            out.append(name)
            continue
        try:
            when = dt.datetime.fromisoformat(said)
        except (TypeError, ValueError):
            out.append(name)                  # unreadable: ask again
            continue
        if (now - when).total_seconds() >= COOLDOWN_MIN * 60:
            out.append(name)
    return out


def remember(office_key: str, week_start, names: Iterable[str],
             now: Optional[dt.datetime] = None) -> int:
    """Record that the search did not find these. Returns how many."""
    names = list(names)
    if not names:
        return 0
    now = now or dt.datetime.now()
    state = _load()
    for name in names:
        state[_key(office_key, week_start, name)] = now.isoformat(
            timespec="seconds")
    _save(state)
    return len(names)


def forget(office_key: str, week_start, names: Iterable[str]) -> int:
    """Drop a remembered miss -- for anyone the search DID find, so a person
    added to OwnerVille stops being treated as absent the moment they appear."""
    names = list(names)
    if not names:
        return 0
    state = _load()
    gone = 0
    for name in names:
        if state.pop(_key(office_key, week_start, name), None) is not None:
            gone += 1
    if gone:
        _save(state)
    return gone
