"""A Hub row that did not land must not mark the day published.

2026-10-26: gap alerts ticked clean 100+ times on Lucy 1, yet the didn't-run
watcher posted "Knocks & Dispositions (self-serve) — didn't run today". The
once-a-day Hub row is written by hub_activity.log_completed, which swallows
every error and answers False — and _publish_hub_once marked the day done
without looking at that answer, so one failed write cost the whole day.
"""
import datetime as dt

from automations.gap_alerts import run as R
from automations.shared import hub_activity

DAY = dt.date(2026, 10, 26)


def _wire(monkeypatch, answers):
    state = {}
    calls = []
    monkeypatch.setattr(R, "_state", lambda: state)
    monkeypatch.setattr(R, "_save_state", lambda d: None)

    def fake(*a, **k):
        calls.append(a)
        return answers.pop(0)
    monkeypatch.setattr(hub_activity, "log_completed", fake)
    return state, calls


def test_a_failed_write_leaves_the_day_unmarked_and_retries(monkeypatch):
    state, calls = _wire(monkeypatch, [False, True])
    R._publish_hub_once(DAY)
    assert not (state.get("_hub") or {}).get(DAY.isoformat())
    R._publish_hub_once(DAY)          # next good tick
    assert state["_hub"][DAY.isoformat()] is True
    assert len(calls) == 2


def test_a_landed_write_is_once_a_day(monkeypatch):
    state, calls = _wire(monkeypatch, [True])
    R._publish_hub_once(DAY)
    R._publish_hub_once(DAY)
    assert len(calls) == 1
