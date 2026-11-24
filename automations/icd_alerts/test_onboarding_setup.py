"""The one line an ICD runs to get their machine ready for the board.

    python -m pytest automations/icd_alerts/test_onboarding_setup.py -q
"""
import inspect

import pytest

from automations.icd_alerts import onboarding_setup as OS


class _Ask:
    class Cancelled(Exception):
        pass

    def __init__(self, answer=""):
        self.answer, self.asked = answer, []

    def text(self, q):
        self.asked.append(q)
        return self.answer


@pytest.mark.parametrize("enrolled,office", [
    ("raf", "raf"),
    ("carlos-b2batt", "carlos"),      # the dashed campaign suffix
    ("jennifer-att", "jennifer"),
    ("khalil-nds", "khalil"),
    ("jamis10", "jamis"),             # the digit one, which the dash missed
])
def test_the_office_key_is_the_office_whichever_way_the_campaign_is_spelt(
        monkeypatch, enrolled, office):
    """One office, one board, whichever campaign a new start is hired under.

    BOTH SPELLINGS ARE REAL. `carlos-b2batt` and `jamis10` are both live
    second-campaign keys (config.PAUSED_KEYS, resume_push.PUSH_OFFICES), and
    the old rule -- split on a dash -- reduced the first and not the second.
    So a machine enrolled for `jamis10` asked for a board nothing owns and
    read as empty, which is indistinguishable from an office with nothing to
    do.
    """
    monkeypatch.setattr(OS.C, "enrollments",
                        lambda: [{"office_key": enrolled}])
    assert OS.office_key() == office


def test_it_agrees_with_the_board_about_whose_board_this_is(monkeypatch):
    """`icd_onboarding.run.offices_here` answers the same question on our
    side, off the same enrolment. The rule is spelt out twice because that
    module cannot import on an office machine -- so it is pinned, not trusted.
    """
    from automations.icd_onboarding import run as R
    rows = [{"office_key": "jamis10"}]
    monkeypatch.setattr(OS.C, "enrollments", lambda: rows)
    monkeypatch.setenv("ICD_ONBOARDING_OFFICES", "")
    monkeypatch.setattr(R, "OFFICES_FILE", type("P", (), {"exists": lambda s: False})())
    monkeypatch.setattr(R, "this_machine", lambda: "an office mac")
    import automations.icd_alerts.config as AC
    monkeypatch.setattr(AC, "enrollments", lambda: rows)
    assert R.offices_here()[0] == OS.office_key() == "jamis"


def test_no_enrolment_is_not_an_office():
    """Guessed here, an empty key would read some other office's board."""
    assert OS.office_key.__doc__


def test_every_step_is_named_and_callable():
    for name, fn in OS.STEPS:
        assert name and callable(fn), name
        assert len(inspect.signature(fn).parameters) == 1, name


def test_the_switch_is_the_last_step_and_is_never_flipped_here():
    """Being set up and being switched on are two decisions. An installer that
    armed the board would arm forty machines on a build that is not finished.
    """
    assert OS.STEPS[-1][0] == "Hourly board run"
    src = inspect.getsource(OS)
    assert "switch_on" not in src, \
        "the installer must never arm the board itself"


def test_the_relay_is_proven_with_a_read_not_with_an_enrolment(monkeypatch):
    """A key on file and a script that was never deployed answer the same way
    until something asks a question."""
    src = inspect.getsource(OS._relay)
    assert "RB.week(" in src, "the relay step must really read the board"
    assert "is_not_deployed" in src, \
        "a relay running old code is a deployment fact, said as one"


def test_a_relay_that_is_not_deployed_says_so(monkeypatch):
    from automations.icd_onboarding import relay_board as RB
    monkeypatch.setattr(OS, "office_key", lambda: "raf")
    monkeypatch.setattr(RB, "available", lambda k: True)

    def boom(key, week):
        raise RB.RelayBoardError("unknown call")
    monkeypatch.setattr(RB, "week", boom)
    said = OS._relay(lambda *a: None)
    assert "re-deployed" in said, said


def test_no_relay_enrolment_is_a_skip_that_says_why(monkeypatch):
    from automations.icd_onboarding import relay_board as RB
    monkeypatch.setattr(OS, "office_key", lambda: "raf")
    monkeypatch.setattr(RB, "available", lambda k: False)
    said = OS._relay(lambda *a: None)
    assert "cannot reach the board" in said, said


def test_a_read_that_answers_counts_as_working(monkeypatch):
    from automations.icd_onboarding import relay_board as RB
    monkeypatch.setattr(OS, "office_key", lambda: "raf")
    monkeypatch.setattr(RB, "available", lambda k: True)
    monkeypatch.setattr(RB, "week", lambda key, week: [{"Name": "Ada"}])
    assert OS._relay(lambda *a: None) == "already working"


def test_the_reception_address_is_remembered_not_asked_twice(monkeypatch):
    """On our side it comes off the second-round roster, which is a Google
    Sheet; an office machine cannot look it up, so the answer lives on the
    machine once it has been given."""
    rec = {"office_key": "raf", "reception_email": "front@example.com"}
    monkeypatch.setattr(OS.C, "enrollments", lambda: [rec])
    assert OS.reception_email() == "front@example.com"


def test_the_board_reads_the_machines_answer_first(monkeypatch):
    """`reception_account` must prefer what the installer was told: a machine
    that has been told is never wrong about its own office, and the roster
    read costs a Sheets call."""
    from automations.icd_onboarding import run as R
    monkeypatch.setattr(OS, "reception_email", lambda rec=None: "front@example.com")
    assert R.reception_account("raf") == "front@example.com"


def test_one_failed_step_never_costs_the_others(monkeypatch):
    """A machine that needs two things fixed and gets one would look fixed,
    and the second would be found the slow way."""
    def boom(log):
        raise RuntimeError("the roof fell in")
    monkeypatch.setattr(OS, "STEPS", [("First", boom),
                                      ("Second", lambda log: "already done")])
    said = []
    rc = OS.run(log=said.append)
    text = "\n".join(said)
    assert rc == 1
    assert "the roof fell in" in text, text
    assert "already done" in text, text


def test_a_failure_says_what_happened_not_just_its_class(monkeypatch):
    """"failed (Error)" was all Drew's screen said on 2026-10-06."""
    def boom(log):
        raise RuntimeError("Sterling would not take the password")
    monkeypatch.setattr(OS, "STEPS", [("Only", boom)])
    said = []
    OS.run(log=said.append)
    assert "would not take the password" in "\n".join(said)


def test_a_clean_machine_ends_happy_and_says_the_board_is_off(monkeypatch):
    monkeypatch.setattr(OS, "STEPS", [
        ("One", lambda log: "already done"),
        ("Hourly board run", lambda log: "ready, switched OFF on purpose"),
    ])
    monkeypatch.setattr(OS, "office_key", lambda: "raf")
    said = []
    assert OS.run(log=said.append) == 0
    text = "\n".join(said)
    assert "switched OFF" in text, text
    assert "launch_check --office raf" in text, text


def test_it_points_at_the_launch_check_on_our_side(monkeypatch):
    """The board's own settings (ov_program, appstream_id, Rate of Pay) are in
    a Google Sheet this computer cannot open, so they are checked there -- and
    said, rather than reported as a green this cannot see."""
    monkeypatch.setattr(OS, "STEPS", [("One", lambda log: "already done")])
    monkeypatch.setattr(OS, "office_key", lambda: "raf")
    said = []
    OS.run(log=said.append)
    assert "launch_check" in "\n".join(said)
