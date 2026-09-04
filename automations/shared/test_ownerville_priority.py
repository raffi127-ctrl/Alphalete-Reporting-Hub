"""An enrolled post outranks an ad-hoc request for the ownerville session.

Megan 2026-09-03: "the post should take priority over the individual request.
We can delay the request if needed. We shouldn't just go blank for an enrolled
service."

The lock on its own is fair, and fair is wrong: on 2026-09-03 three `/knocks`
run back-to-back in Slack took the session through Raf's window and gap_alerts
lost the 8:15, 8:25 and 8:28 ticks to them. A 15-minute board people are
enrolled in went quiet so an ad-hoc lookup could go first.

RESERVATION, NOT PREEMPTION — a holder mid-scrape is never interrupted. Yanking
the session out from under an impersonated pull is exactly how a board ends up
carrying another office's reps.
"""
import os
import time

import pytest

from automations.shared import tableau_patchright as T


@pytest.fixture(autouse=True)
def _own_file(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "OWNERVILLE_PRIORITY_FILE",
                        tmp_path / ".ownerville_session.wanted")
    yield


def test_no_reservation_by_default():
    assert not T._reservation_active()


def test_a_live_reservation_from_another_process_is_active(monkeypatch):
    # PPID is a real, living process that is not us.
    T.OWNERVILLE_PRIORITY_FILE.write_text("%d,%.0f" % (os.getppid(),
                                                       time.time()))
    assert T._reservation_active()


def test_our_own_reservation_is_not_something_to_yield_to():
    """Otherwise a scheduled job would wait for itself, forever."""
    T._reserve_session()
    assert not T._reservation_active()


def test_a_dead_reserver_reserves_nothing():
    """A scheduled job killed mid-wait must not wedge `/knocks` shut."""
    T.OWNERVILLE_PRIORITY_FILE.write_text("999999,%.0f" % time.time())
    assert not T._reservation_active()


def test_a_stale_reservation_expires():
    """Belt and braces for the case where the pid gets reused."""
    old = time.time() - (T._OV_RESERVATION_TTL_S + 60)
    T.OWNERVILLE_PRIORITY_FILE.write_text("%d,%.0f" % (os.getppid(), old))
    assert not T._reservation_active()


def test_ttl_outlasts_the_scheduled_waiters_own_budget():
    """The reservation must not lapse while its owner is still queueing —
    gap_alerts waits 240s for the session."""
    from automations.gap_alerts import config as C
    assert T._OV_RESERVATION_TTL_S > C.OWNERVILLE_SESSION_WAIT_S


def test_garbage_never_blocks_anybody():
    for junk in ("", "not-a-reservation", "12,", ",99", "abc,def"):
        T.OWNERVILLE_PRIORITY_FILE.write_text(junk)
        assert not T._reservation_active()


def test_unreserve_only_removes_our_own():
    T.OWNERVILLE_PRIORITY_FILE.write_text("%d,%.0f" % (os.getppid(),
                                                       time.time()))
    T._unreserve_session()
    assert T.OWNERVILLE_PRIORITY_FILE.exists(), (
        "clearing somebody else's reservation would hand their slot away")
    T._reserve_session()
    T._unreserve_session()
    assert not T.OWNERVILLE_PRIORITY_FILE.exists()


def test_gap_alerts_asks_for_scheduled_priority():
    """Both of its pulls — the board and the gap list. Either one left at the
    default is a tick that can still lose its slot to a slash command."""
    import inspect
    from automations.gap_alerts import run as R
    for fn in (R.pull_boards_many, R.gap_rows_many):
        assert 'priority="scheduled"' in inspect.getsource(fn), fn.__name__


def test_on_demand_is_the_default():
    """`/knocks` and everything else must yield without being told to —
    a priority scheme nobody remembers to opt into protects nothing."""
    import inspect
    sig = inspect.signature(T.ownerville_session)
    assert sig.parameters["priority"].default == "normal"
    sig = inspect.signature(T._acquire_session_lock)
    assert sig.parameters["priority"].default == "normal"
