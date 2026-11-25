"""A slow OwnerVille page gets one more pass before anybody is told.

WHY (Eve, 2026-11-25). raf's owner submit posted "couldn't owner submit 2 new
starts -- do it by hand" for Jerry Esebanme and Kameron Frazier, both with
`TimeoutError: ... waiting for navigation to finish`. The very next pass found
both of them in seconds -- and neither was even ready to submit (background
check, drug test, AT&T courses still open). The alert asked a person to do by
hand something that could not be done, because one page load was slow.

So a timeout is a HICCUP, not a refusal: it is remembered, and the alert goes
out only when the SAME person hiccups on the next pass too. A pass that reaches
them cleanly forgets it. Refusals OwnerVille actually gave (confirm box, save,
re-open) still alert the first time -- those are real.

Per office, per press, per name. Kept on the machine that runs the board, the
same way `ov_misses` is: the next pass of that office runs on that machine.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from automations.icd_onboarding import board as B

# What a slow or half-loaded page looks like from Playwright. OwnerVille's own
# answers about a person never contain these.
HICCUP_MARKS = ("TimeoutError", "Timeout ", "waiting for navigation",
                "Target page, context or browser has been closed",
                "Execution context was destroyed")

# A hiccup older than this is not "the last pass" any more (overnight gap, a
# board that skipped a day): a fresh timeout after it starts the count again.
WINDOW_H = 18

PATH = Path(__file__).resolve().parents[2] / "output" / "press_hiccups.json"


def is_hiccup(detail: str) -> bool:
    detail = str(detail or "")
    return any(m in detail for m in HICCUP_MARKS)


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


def _key(office_key: str, what: str, name: str) -> str:
    return "%s|%s|%s" % (str(office_key).strip().lower(),
                         str(what).strip().lower(), B._fold(name))


def settle(office_key: str, what: str, hiccups: Iterable[str],
           clean: Iterable[str],
           now: Optional[dt.datetime] = None) -> List[str]:
    """Record this pass and return who has now hiccuped TWICE IN A ROW.

    `hiccups`: names whose lookup timed out this pass.
    `clean`:   names this pass reached without a hiccup (forgotten).
    The returned names are the ones to alert on; they stay remembered, so a
    third timeout keeps alerting (the incident thread updates, not re-posts).
    """
    now = now or dt.datetime.now()
    state = _load()
    before = dict(state)
    repeat: List[str] = []
    for name in clean:
        state.pop(_key(office_key, what, name), None)
    for name in hiccups:
        k = _key(office_key, what, name)
        said = state.get(k)
        try:
            when = dt.datetime.fromisoformat(said) if said else None
        except (TypeError, ValueError):
            when = None
        if when and (now - when).total_seconds() <= WINDOW_H * 3600:
            repeat.append(name)
        state[k] = now.isoformat(timespec="seconds")
    if state != before:
        _save(state)
    return repeat
