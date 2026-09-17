"""Close out yesterday: the office's own machine delivers the FINISHED day.

WHY THIS EXISTS. The metrics thread's knocks board is built from whatever
this machine last relayed for that day, and the agent's own selling window
ends at 21:30 -- so "the finished day" was really "the day as of the last
in-window sweep". Usually that is close enough (Kash's last knock on
2026-09-16 was 9:09pm, inside it). Sometimes it is not, and the two ways it
misses both happened in one week:

  * a machine that stopped early. Cyrus's agent died at 14:52 on 2026-09-15
    against a day that ends at 20:30; Khalil's at 16:58 on 09-16. Each left a
    two-thirds day sitting in the relay as if it were the whole thing.
  * a rep still knocking after 21:30, which nothing in-window can ever see.

Once the day is OVER, none of that matters: OwnerVille has the final number
regardless of when this machine happened to stop. So read it once, in the new
day, and overwrite that day's relay row with the real total.

WHY IT RUNS AT THE TOP OF THE NEW DAY rather than at, say, 6am. The knocks
board is read by the metrics thread at about 06:50 Central, which on an
Eastern office's clock is 07:50 -- and the agent does not start its own day
until 10:00 local. Firing as soon as the local date flips leaves the whole
night to retry before anybody needs the answer, instead of one chance in a
morning that may already be too late.

WHAT IT ASSUMES, AND WHERE THAT IS FALSE. Almost every ECO machine is a
DESKTOP (Megan 2026-09-17): on AC, never closed and carried home, held awake
by the caffeinate agent -- so launchd keeps firing through the night and this
runs. Cyrus's is the one laptop, and a shut laptop on battery sleeps whatever
we assert. That is expected, not a fault: a day this never closed out simply
keeps the in-window row, and the reporting side falls back to its own scrape
exactly as it did before this existed.

NOTHING HERE IS ALLOWED TO COST A SWEEP. It runs before the selling-window
gate, on a machine doing nothing else at the time, and every failure path
returns quietly and leaves the day to be retried.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Callable, Optional

STATE = Path.home() / ".config" / "lucy-reports" / "closeout.json"

# HOW MANY TIMES TO TRY ONE DAY BEFORE LEAVING IT. The job wakes every few
# minutes all night, so an office whose OwnerVille login has expired would
# otherwise spend the night failing -- and every failure is a fault report
# with somebody's name on it. Six attempts is a real chance at a transient
# outage and nowhere near a night of them; after that the in-window row
# stands and the reporting side scrapes, which is what used to happen anyway.
MAX_ATTEMPTS = 6


def _read() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001 — no state is the same as fresh state
        return {}


def _write(data: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(data, indent=2))
    except Exception:  # noqa: BLE001 — a state file we cannot write is at
        pass           # worst a day closed out twice, which is harmless


def previous_selling_day(today: dt.date) -> Optional[dt.date]:
    """The day before `today`, if there was anything to knock on it.

    Monday closes out nothing: Sunday is not a selling day anywhere in the
    org, and asking OwnerVille for an empty Sunday would relay a blank row
    over nothing and report it as a quiet day.
    """
    day = today - dt.timedelta(days=1)
    return None if day.weekday() == 6 else day


def due(today: Optional[dt.date] = None) -> Optional[dt.date]:
    """The day this machine still owes a closing read for, or None."""
    today = today or dt.date.today()
    day = previous_selling_day(today)
    if day is None:
        return None
    state = _read()
    rec = state.get(day.isoformat()) or {}
    if rec.get("done"):
        return None
    if int(rec.get("attempts") or 0) >= MAX_ATTEMPTS:
        return None
    return day


def _record(day: dt.date, *, done: bool) -> None:
    state = _read()
    rec = state.get(day.isoformat()) or {}
    rec["attempts"] = int(rec.get("attempts") or 0) + 1
    rec["done"] = done
    rec["last"] = dt.datetime.now().isoformat(timespec="seconds")
    state[day.isoformat()] = rec
    # A fortnight is plenty to keep; this file is read on every wake.
    cutoff = (day - dt.timedelta(days=14)).isoformat()
    _write({k: v for k, v in state.items() if k >= cutoff})


def maybe_run(read_day: Callable[[dt.date], int], *,
              today: Optional[dt.date] = None, log=print) -> Optional[dt.date]:
    """Re-read yesterday if it is still owed. Returns the day closed out.

    `read_day` is the agent's own knocks command, handed in rather than
    imported, so this module can be tested without a browser anywhere near
    it. It returns 0 when the read and the relay both worked.

    NEVER RAISES. This runs ahead of the machine's real work.
    """
    day = due(today)
    if day is None:
        return None
    log("closing out %s — the day is over, so this is its final number"
        % day.isoformat())
    try:
        rc = read_day(day)
    except Exception as e:  # noqa: BLE001
        _record(day, done=False)
        log("could not close out %s (%s) — the in-window numbers stand and "
            "the report side will scrape if it needs to."
            % (day.isoformat(), type(e).__name__))
        return None
    if rc == 0:
        _record(day, done=True)
        log("closed out %s ✅" % day.isoformat())
        return day
    _record(day, done=False)
    log("close-out of %s did not complete; will try again on the next wake."
        % day.isoformat())
    return None
