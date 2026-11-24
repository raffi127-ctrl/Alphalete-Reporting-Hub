"""--office picks the session and the campaign, never the sheet.

Megan, 2026-11-24: "the OV sweep would happen on the ECO machine."

    python -m pytest automations/obcl_ov_sweep/test_office_key.py -q
"""
import pytest

from automations.obcl_ov_sweep import config, run


def test_alphalete_is_the_default_and_keeps_its_campaign():
    assert run.ALPHALETE_KEY == "raf"
    assert run._programme("raf") == config.CAMPAIGN
    assert run._programme("") == config.CAMPAIGN


def test_another_offices_campaign_comes_off_their_own_ov_program(monkeypatch):
    """The campaign IS the roster: a fallback to Alphalete's would look an
    ICD's new start up on somebody else's campaign, find nobody, and report
    "not in OwnerVille" -- the wrong answer to act on."""
    from automations.office_admin import config as OC

    class _O:
        ov_program = "RES-SomebodyElse"
    monkeypatch.setattr(OC, "office", lambda k: _O())
    assert run._programme("someone") == "RES-SomebodyElse"


def test_no_ov_program_is_an_empty_answer_not_alphaletes(monkeypatch):
    from automations.office_admin import config as OC
    monkeypatch.setattr(OC, "office", lambda k: None)
    assert run._programme("someone") == ""


def test_an_unreadable_office_table_is_also_empty(monkeypatch):
    from automations.office_admin import config as OC
    monkeypatch.setattr(OC, "office",
                        lambda k: (_ for _ in ()).throw(OSError("no")))
    assert run._programme("someone") == ""


# ----------------------------------------- and the sheet stays Alphalete's

def test_another_offices_key_is_refused_at_the_sheet():
    """Pointing this job at another office would read THEIR OwnerVille and
    tick ALPHALETE'S sheet. The refusal names the thing that does do their
    office instead."""
    with pytest.raises(RuntimeError) as e:
        run._open_tab("", "someone")
    said = str(e.value)
    assert "Alphalete's D2D OBCL" in said
    assert "--only ownerville" in said, \
        "it has to say what DOES fill that office's five columns"


def test_alphalete_is_not_refused(monkeypatch):
    seen = []
    monkeypatch.setattr(run, "_open_tab_alphalete",
                        lambda tab="": seen.append(tab) or ("ws", []))
    run._open_tab("", "raf")
    run._open_tab("", "")
    assert len(seen) == 2


def test_the_session_and_the_campaign_both_take_the_office():
    """The whole point: with `raf` on Raf's own machine it reads HIS
    OwnerVille with HIS login and queues behind nobody."""
    import inspect
    # The submit opens its own session in `_submit`, so the office has to be
    # PASSED there -- it is not in `main`'s scope. Getting that wrong was a
    # NameError waiting for the first owner-submit pass.
    assert "session_anywhere(office_key" in inspect.getsource(run.main)
    sub = inspect.getsource(run._submit)
    assert "session_anywhere(office_key" in sub
    assert "office_key" in [a for a in inspect.signature(run._submit).parameters]


def test_a_missing_campaign_stops_the_run_before_it_opens_anything():
    """A refusal after the browser is open has already spent the session this
    change exists to stop queueing for."""
    import inspect
    src = inspect.getsource(run.main)
    at_refusal = src.index("refusing rather than reading")
    at_session = src.index("session_anywhere")
    assert at_refusal < at_session
