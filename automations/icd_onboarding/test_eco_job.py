"""The clock the onboarding board runs on, on an office's own computer.

    python -m pytest automations/icd_onboarding/test_eco_job.py -q
"""
import datetime as dt
import time

import pytest

from automations.icd_onboarding import eco_job as J


@pytest.fixture(autouse=True)
def _own_dir(tmp_path, monkeypatch):
    """Never read or write the real machine's state."""
    monkeypatch.setattr(J, "_app_dir", lambda: tmp_path)


def test_nothing_runs_until_it_is_switched_on(monkeypatch):
    """THE WHOLE POINT, until Megan says the build is done: a machine that is
    set up and not armed does nothing, and that is correct rather than
    broken ([[feedback_onboarding_nothing_live_till_built]])."""
    started = []
    monkeypatch.setattr(J, "_start", lambda a, log: started.append(a) or True)
    monkeypatch.setattr(J, "offices", lambda: ["raf"])
    assert J.switched_on() is False
    assert J.maybe_run(log=lambda *a: None) is False
    assert started == []


def test_switched_on_and_due_starts_the_board(monkeypatch):
    started = []
    monkeypatch.setattr(J, "_start", lambda a, log: started.append(a) or True)
    monkeypatch.setattr(J, "offices", lambda: ["raf"])
    monkeypatch.setattr(J, "no_shows_due", lambda *a, **k: False)
    J.switch_on("test")
    noon = dt.datetime(2026, 11, 24, 12, 0)
    assert J.maybe_run(log=lambda *a: None, now=noon) is True
    assert started == [["--write"]]


def test_a_machine_with_no_office_never_starts_anything(monkeypatch):
    """An enrolment for nothing is not a board to run."""
    started = []
    monkeypatch.setattr(J, "_start", lambda a, log: started.append(a) or True)
    monkeypatch.setattr(J, "offices", lambda: [])
    J.switch_on("test")
    assert J.maybe_run(log=lambda *a: None) is False
    assert started == []


def test_only_one_pass_at_a_time(monkeypatch):
    """Two passes would drive the same ApplicantStream and OwnerVille profile,
    and the second would find it held and read nothing -- the same guard the
    Lucys' wrapper gets from pgrep."""
    started = []
    monkeypatch.setattr(J, "_start", lambda a, log: started.append(a) or True)
    monkeypatch.setattr(J, "offices", lambda: ["raf"])
    monkeypatch.setattr(J, "no_shows_due", lambda *a, **k: False)
    J.switch_on("test")
    noon = dt.datetime(2026, 11, 24, 12, 0)
    assert J.maybe_run(log=lambda *a: None, now=noon) is True
    assert J.maybe_run(log=lambda *a: None, now=noon) is False
    assert len(started) == 1


def test_a_stale_lock_is_a_crash_not_a_run():
    """A lock with a time in it survives a kill -9, which pgrep cannot tell
    from 'never started'."""
    J._take_lock()
    assert J._lock_held() is True
    old = time.time() - (J.STALE_LOCK_MINUTES + 1) * 60
    J.lock_path().write_text("%.0f" % old, encoding="utf-8")
    assert J._lock_held() is False


def test_a_board_that_has_never_run_is_due():
    """Nothing has run yet is not "it ran 0 seconds ago"."""
    assert J.board_due(dt.datetime(2026, 11, 24, 3, 0), {}) is True


def test_the_board_follows_the_banded_clock(monkeypatch):
    """15 minutes 8-noon, 30 noon-3, hourly the rest (Megan, 2026-11-24).
    One definition, in `cadence` -- this holds the clock to it rather than
    keeping a second copy of the numbers."""
    from automations.icd_onboarding import cadence as CAD

    def ran(minutes_ago, at):
        return J.board_due(at, {"board": at.timestamp() - minutes_ago * 60})

    morning = dt.datetime(2026, 11, 24, 9, 0)
    assert CAD.every_minutes(morning) == 15
    assert ran(10, morning) is False
    assert ran(16, morning) is True

    afternoon = dt.datetime(2026, 11, 24, 13, 0)
    assert CAD.every_minutes(afternoon) == 30
    assert ran(16, afternoon) is False
    assert ran(31, afternoon) is True

    evening = dt.datetime(2026, 11, 24, 18, 0)
    assert CAD.every_minutes(evening) == 60
    assert ran(31, evening) is False
    assert ran(61, evening) is True


def test_it_runs_overnight_now_rather_than_stopping_at_half_eight():
    """The old 6:30am-8:30pm window existed because every pass cost the same.
    Banded, an overnight pass is one hourly read -- and a 7am answer is on the
    board by 8 instead of waiting for the half hour."""
    night = dt.datetime(2026, 11, 24, 2, 0)
    assert J.board_due(night, {"board": night.timestamp() - 61 * 60}) is True


def test_the_no_shows_walk_fires_at_or_after_its_slot_not_inside_one_minute():
    """IT SHIPPED AT 19:30 AND NEVER RAN. A walk that only fires in one
    minute meets whatever else is running that minute and is lost; a machine
    can also be asleep at 21:15."""
    assert J.no_shows_due(dt.datetime(2026, 11, 24, 21, 14), {}) is False
    assert J.no_shows_due(dt.datetime(2026, 11, 24, 21, 15), {}) is True
    assert J.no_shows_due(dt.datetime(2026, 11, 24, 23, 59), {}) is True


def test_the_no_shows_walk_runs_once_a_day():
    done = {"no_shows_day": dt.date(2026, 11, 24).isoformat()}
    assert J.no_shows_due(dt.datetime(2026, 11, 24, 22, 0), done) is False
    assert J.no_shows_due(dt.datetime(2026, 11, 25, 22, 0), done) is True


def test_the_no_shows_walk_goes_first_when_both_are_due(monkeypatch):
    """They drive the SAME ApplicantStream profile, and the walk is the one
    with a deadline: Blue Ink mails documents at 7:30 the next morning and
    must not mail them to somebody who did not come."""
    started = []
    monkeypatch.setattr(J, "_start", lambda a, log: started.append(a) or True)
    monkeypatch.setattr(J, "offices", lambda: ["raf"])
    monkeypatch.setattr(J, "steps_here", lambda: ["contacts", "no_shows"])
    J.switch_on("test")
    at_night = dt.datetime(2026, 11, 24, 21, 30)
    assert J.maybe_run(log=lambda *a: None, now=at_night) is True
    assert started == [["--only", "no_shows", "--write"]]


def test_a_step_this_copy_does_not_have_is_never_asked_for(monkeypatch):
    """The no-shows walk is a seven-page ApplicantStream read whose ECO reader
    is not built yet. Asking for it anyway would start a pass with nothing to
    do every night AND mark the day done, so the walk would be skipped for
    real on the day it finally lands."""
    started = []
    monkeypatch.setattr(J, "_start", lambda a, log: started.append(a) or True)
    monkeypatch.setattr(J, "offices", lambda: ["raf"])
    monkeypatch.setattr(J, "steps_here", lambda: ["contacts"])
    J.switch_on("test")
    at_night = dt.datetime(2026, 11, 24, 21, 30)
    J.maybe_run(log=lambda *a: None, now=at_night)
    assert ["--only", "no_shows", "--write"] not in started, \
        "a step this copy does not have must never be asked for"
    assert J.no_shows_due(at_night, J._load()) is True, \
        "and the day must NOT have been marked done"


def test_nothing_runs_on_a_copy_with_no_steps_at_all(monkeypatch):
    started = []
    monkeypatch.setattr(J, "_start", lambda a, log: started.append(a) or True)
    monkeypatch.setattr(J, "offices", lambda: ["raf"])
    monkeypatch.setattr(J, "steps_here", lambda: [])
    J.switch_on("test")
    assert J.maybe_run(log=lambda *a: None,
                       now=dt.datetime(2026, 11, 24, 12, 0)) is False
    assert started == []


def test_what_it_can_do_comes_from_eco_steps():
    """`icd_onboarding.run` is the Hub's runner and cannot ship, so the clock
    asks the module that CAN -- and both answer off the same enrolment."""
    from automations.icd_onboarding import eco_steps as ES
    assert J.steps_here() == [n for n, _ in ES.STEPS]


def test_the_write_flag_is_on_the_scheduled_pass():
    """A scheduled pass that forgot --write would read everything and tick
    nothing, which looks exactly like a week with nothing to do."""
    import inspect
    src = inspect.getsource(J.maybe_run)
    assert '"--write"' in src


def test_an_unreadable_switch_is_off(monkeypatch):
    monkeypatch.setattr(J, "on_path", lambda: (_ for _ in ()).throw(OSError("no")))
    assert J.switched_on() is False
