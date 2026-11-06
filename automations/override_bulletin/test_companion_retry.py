"""The RCs/NCs companion is retried on every pass after the DD send, not once.

Thu 2026-11-05: the DD bulletin went out, the companion's ONE try at 15:00 died
on the Sheets per-minute read quota (429 inside dd_data.load), and the 16:00
pass printed "already sent this week, nothing to do" — so the Up and Coming RCs
and NCs email never went. The "already sent" branch now retries the companion;
send_rcs_ncs's own per-week marker makes that a no-op once it is out.
"""
import pytest

from automations.override_bulletin import review_gate as RG


@pytest.fixture
def sent_week(monkeypatch):
    calls = []
    monkeypatch.setattr(RG, "already_sent", lambda *a, **k: True)
    monkeypatch.setattr(RG, "send_companion",
                        lambda distro=False, verbose=True: calls.append(distro))
    return calls


def test_a_sending_pass_retries_the_companion(sent_week):
    assert RG.main(["--check", "--send", "--distro"]) == 0
    assert sent_week == [True]


def test_soft_launch_mode_is_kept(sent_week):
    assert RG.main(["--check", "--send"]) == 0
    assert sent_week == [False]


def test_a_check_without_send_never_sends(sent_week):
    assert RG.main(["--check"]) == 0
    assert sent_week == []


# --- the sender's exit code, which the retry above leans on --------------------
# The first cut of the retry faked send_companion, so it never saw that
# `send.py --rcs-ncs --send` EXITS 1 when the week is already out. Every pass
# after the 18:00 send on Thu 2026-11-05 then read as "RCs and NCs failed".

from automations.override_bulletin import send as S


def _exit_for(monkeypatch, result):
    monkeypatch.setattr(S, "send_rcs_ncs", lambda **_k: result)
    return S.main(["--rcs-ncs", "--send", "--notify"])


def test_already_sent_is_a_clean_exit(monkeypatch):
    assert _exit_for(monkeypatch, {"published": False,
                                   "reason": "already sent"}) == 0


def test_a_hard_block_still_fails(monkeypatch):
    assert _exit_for(monkeypatch, {"published": False,
                                   "reason": "hard block"}) == 1


def test_a_real_send_is_clean(monkeypatch):
    assert _exit_for(monkeypatch, {"published": True}) == 0
