"""One office, one answer -- whichever way its campaign key is spelt.

    python -m pytest automations/icd_alerts/test_base_office_key.py -q
"""
import pytest

from automations.icd_alerts import config as C


@pytest.mark.parametrize("key,office", [
    # The plain shape: the owner's first name, which is how enroll mints it.
    ("raf", "raf"),
    ("carlos", "carlos"),
    # The DASHED campaign suffix.
    ("carlos-b2batt", "carlos"),
    ("jennifer-att", "jennifer"),
    ("khalil-nds", "khalil"),
    # The DIGIT one. This is the shape `key.split("-")[0]` missed, and it is
    # not hypothetical: `jamis10` is Jamis's Box key beside his AT&T `jamis`
    # (config.PAUSED_KEYS, resume_push.PUSH_OFFICES).
    ("jamis10", "jamis"),
    # Spelling and spacing an ICD might type.
    ("  Jamis10 ", "jamis"),
    ("CARLOS-B2BATT", "carlos"),
])
def test_every_campaign_reduces_to_its_office(key, office):
    assert C.base_office_key(key) == office


def test_nothing_is_nothing():
    for empty in ("", "   ", None):
        assert C.base_office_key(empty) == ""


def test_a_key_that_does_not_start_with_letters_is_left_alone():
    """Reducing it to "" would read some OTHER office's board. The one thing
    worse than no answer is a confident wrong one -- so an unrecognised shape
    keeps its own name and fails loudly downstream instead."""
    assert C.base_office_key("11580") == "11580"
    assert C.base_office_key("-att") == "-att"


def test_the_two_callers_that_decide_whose_board_it_is_agree(monkeypatch):
    """`offices_here` (ours) and `onboarding_setup.office_key` (the office's
    own computer) must never hold two opinions about this. They cannot share
    an import -- `icd_onboarding.run` reaches Google Sheets through its
    siblings and an office Mac has none -- so they share `config` instead."""
    from automations.icd_alerts import onboarding_setup as OS
    from automations.icd_onboarding import run as R

    rows = [{"office_key": "jamis10"}]
    monkeypatch.setenv("ICD_ONBOARDING_OFFICES", "")
    monkeypatch.setattr(R, "OFFICES_FILE",
                        type("P", (), {"exists": lambda s: False})())
    monkeypatch.setattr(R, "this_machine", lambda: "an office mac")
    monkeypatch.setattr(C, "enrollments", lambda: rows)
    monkeypatch.setattr(OS.C, "enrollments", lambda: rows)
    assert R.offices_here() == ["jamis"]
    assert OS.office_key() == "jamis"


def test_two_campaigns_on_one_machine_are_one_board(monkeypatch):
    """An office running AT&T and Box has ONE onboarding board, and a new
    start is on it whichever campaign hired them."""
    from automations.icd_onboarding import run as R
    rows = [{"office_key": "jamis"}, {"office_key": "jamis10"}]
    monkeypatch.setenv("ICD_ONBOARDING_OFFICES", "")
    monkeypatch.setattr(R, "OFFICES_FILE",
                        type("P", (), {"exists": lambda s: False})())
    monkeypatch.setattr(R, "this_machine", lambda: "an office mac")
    monkeypatch.setattr(C, "enrollments", lambda: rows)
    assert R.offices_here() == ["jamis"]


def test_the_wide_forward_allowance_is_matched_on_the_office(monkeypatch):
    """`code_answer.SCOPE_WIDE_OK` names offices, not campaigns: a second
    campaign's key must not turn an expected whole-inbox forward into a fault
    somebody gets told about."""
    from automations.icd_alerts import code_answer as CA
    assert C.base_office_key("carlos-b2batt") in CA.SCOPE_WIDE_OK
    assert C.base_office_key("carlos") in CA.SCOPE_WIDE_OK
