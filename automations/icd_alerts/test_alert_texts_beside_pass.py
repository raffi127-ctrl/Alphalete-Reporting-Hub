"""The credit-check poster's texts go out BESIDE the pass, not in front of it.

    python -m pytest automations/icd_alerts/test_alert_texts_beside_pass.py

Carlos 2026-11-19: "anything we could do to speed up ... the sales alert text
messages". Each office's texts used to be sent inline, before its Slack
alert, so a text waiting on Messages held up the Slack line for that office
and every office after it. No Messages.app here: the sender is stubbed.
"""
from __future__ import annotations

import inspect
import threading
import time

import pytest

from automations.icd_alerts import post as P
from automations.shared import messages_lock as ml


@pytest.fixture(autouse=True)
def _private_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "LOCK_PATH", tmp_path / "m.lock")


def _slow_sender(calls, delay=0.3, fail_for=()):
    def send(group, text, dry_run=True, dest=None):
        if group in fail_for:
            raise RuntimeError("no chat holds all of those numbers")
        time.sleep(delay)
        calls.append((group, text, dry_run,
                      ml._priority_path().exists() if ml._fcntl else None))
        return {"ok": True}
    return send


def test_queueing_a_text_does_not_wait_for_it():
    calls, logs = [], []
    out = P._TextSender(send=True, log=logs.append,
                        sender=_slow_sender(calls, delay=0.5))
    t0 = time.monotonic()
    out.add("carlos-b2batt", "standings", "NEW A Players", "board")
    out.add("carlos-b2batt", "standings", "ATT B2B Leaders", "board")
    assert time.monotonic() - t0 < 0.2, "the Slack alert would be waiting"
    out.finish()
    assert [c[0] for c in calls] == ["NEW A Players", "ATT B2B Leaders"]
    assert out.sent == 2 and out.failed == 0


def test_finish_waits_until_every_text_is_out():
    calls = []
    out = P._TextSender(send=True, log=lambda *_: None,
                        sender=_slow_sender(calls, delay=0.2))
    for g in ("a", "b", "c"):
        out.add("k", "standings", g, "x")
    out.finish()
    assert len(calls) == 3


def test_order_is_kept_so_a_group_never_gets_an_older_board_last():
    calls = []
    out = P._TextSender(send=True, log=lambda *_: None,
                        sender=_slow_sender(calls, delay=0.05))
    for n in range(6):
        out.add("k", "standings", "grp", "board %d" % n)
    out.finish()
    assert [c[1] for c in calls] == ["board %d" % n for n in range(6)]


def test_one_failed_group_does_not_cost_the_rest_and_is_logged():
    calls, logs = [], []
    out = P._TextSender(send=True, log=logs.append,
                        sender=_slow_sender(calls, delay=0.01, fail_for={"gone"}))
    out.add("jacob", "standings", "gone", "x")
    out.add("jacob", "Sara standings", "still here", "y")
    out.finish()
    assert [c[0] for c in calls] == ["still here"]
    assert out.failed == 1
    assert any("FAILED to text standings to 'gone'" in l for l in logs)
    assert any("Sara standings -> text group 'still here'" in l for l in logs)


@pytest.mark.skipif(ml._fcntl is None, reason="no Messages on Windows")
def test_a_live_send_holds_priority_only_while_a_text_is_in_hand():
    calls = []
    out = P._TextSender(send=True, log=lambda *_: None,
                        sender=_slow_sender(calls, delay=0.05))
    out.add("k", "standings", "g", "x")
    deadline = time.monotonic() + 3
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.2)                       # the queue is empty again
    assert calls[0][3] is True, "the boards were not asked to stand aside"
    assert not ml._priority_path().exists(), "priority held with nothing to send"
    out.finish()


def test_a_dry_run_asks_nobody_to_stand_aside():
    calls = []
    out = P._TextSender(send=False, log=lambda *_: None,
                        sender=_slow_sender(calls, delay=0.01))
    out.add("k", "standings", "g", "x")
    out.finish()
    assert calls and calls[0][2] is True          # dry_run passed through
    assert not calls[0][3]


def test_nothing_queued_starts_no_thread():
    before = threading.active_count()
    out = P._TextSender(send=True, log=lambda *_: None)
    out.finish()
    assert threading.active_count() == before


def test_the_pass_itself_never_sends_a_text():
    src = inspect.getsource(P._run)
    assert "send_text_to_group" not in src
    assert src.count("texts_out.add(") == 2      # standings + Sara list


def test_run_waits_for_the_texts_even_when_the_pass_fails(monkeypatch):
    finished = []
    monkeypatch.setattr(P._TextSender, "finish",
                        lambda self: finished.append(True))

    def boom(*a, **k):
        raise RuntimeError("sheets 503")
    monkeypatch.setattr(P, "_run", boom)
    with pytest.raises(RuntimeError):
        P.run(send=False, log=lambda *_: None)
    assert finished == [True]
