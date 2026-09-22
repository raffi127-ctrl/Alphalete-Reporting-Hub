"""The 2am catch-up: re-read yesterday's SALES once the day is finished.

Megan 2026-09-22: "run them all for their sales boards 12-12 with a 2am final
catch up sweep". Reading until midnight still leaves the orders that post
late — SaraPlus and My Service Cloud keep settling after the last in-window
read — and a machine that stopped early leaves a partial day in the relay as
if it were the whole thing. Once it is past 2am the previous day is as final
as it gets on the ICD's side, so read it once and overwrite that day's row.

The same shape as closeout.py (the knocks close-out): a small state file, a
cap on attempts so a broken login does not spend the night failing, and
nothing that can cost the machine's normal sweep. Every day, Sunday included,
because the sales board runs seven days a week.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Callable, Optional

STATE = Path.home() / ".config" / "lucy-reports" / "sales_closeout.json"
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
    except Exception:  # noqa: BLE001 — at worst a day read twice: harmless
        pass


def due(now: Optional[dt.datetime] = None) -> Optional[dt.date]:
    """Yesterday, if it is past the catch-up hour and still owed."""
    from automations.icd_alerts import config as C
    now = now or dt.datetime.now()
    after = now.replace(hour=C.SALES_CATCHUP_AFTER_HHMM[0],
                        minute=C.SALES_CATCHUP_AFTER_HHMM[1],
                        second=0, microsecond=0)
    if now < after:
        return None
    day = now.date() - dt.timedelta(days=1)
    rec = _read().get(day.isoformat()) or {}
    if rec.get("done") or int(rec.get("attempts") or 0) >= MAX_ATTEMPTS:
        return None
    return day


def _record(day: dt.date, *, done: bool) -> None:
    state = _read()
    rec = state.get(day.isoformat()) or {}
    rec["attempts"] = int(rec.get("attempts") or 0) + 1
    rec["done"] = done
    rec["last"] = dt.datetime.now().isoformat(timespec="seconds")
    state[day.isoformat()] = rec
    cutoff = (day - dt.timedelta(days=14)).isoformat()
    _write({k: v for k, v in state.items() if k >= cutoff})


def maybe_run(read_day: Callable[[dt.date], int], *,
              now: Optional[dt.datetime] = None, log=print) -> Optional[dt.date]:
    """Re-read yesterday's sales if owed. Returns the day closed out.

    `read_day` is handed in (the agent's own sales read) so this can be
    tested without a browser. It returns 0 when the read and relay worked.
    NEVER RAISES — it runs ahead of the machine's real work."""
    day = due(now)
    if day is None:
        return None
    log("final sales read for %s — the day is over" % day.isoformat())
    try:
        rc = read_day(day)
    except Exception as e:  # noqa: BLE001
        _record(day, done=False)
        log("could not finish %s's sales (%s); the evening numbers stand."
            % (day.isoformat(), type(e).__name__))
        return None
    _record(day, done=(rc == 0))
    log(("sales for %s finalised ✅" if rc == 0 else
         "final sales read for %s did not complete; will retry.")
        % day.isoformat())
    return day if rc == 0 else None
