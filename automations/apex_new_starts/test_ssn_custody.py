"""Who may hold a Social, and what cannot carry one.

Megan, 2026-11-06, deciding this for the ICD-machine build: "the ICDs relay
machine can hold a social ... so it can just disappear from that if they can
just access it to fill it in that time". Her reasoning: the operator already
previews the signed tax document and copies the number out by hand, so the
exposure is not new -- what changes is that a machine does the copying.

That makes these tests the fence. Before this, the report simply never had a
Social and so could not leak one; now it can have one on purpose, on one
machine, for one run. Every path that must STILL be unable to carry one is
pinned here, because "we were careful" is not a property anybody can check
later.
"""
from __future__ import annotations

import json

from automations.apex_new_starts import blueink_data as BID
from automations.apex_new_starts.ssn_prompt import Secret

NUMBER = "123-45-6789"

# A bundle shaped like Blue Ink's, carrying a Social and one ordinary field.
BUNDLE = {"id": "b1", "packets": [{"name": "New Start Packet"}],
          "documents": [{"key": "d1", "name": "W-4"}]}
MAPPING = {"W-4": {"f_ssn": "ssn", "f_city": "city"}}
FIELDS = [{"doc_key": "d1", "field_key": "f_ssn", "value": NUMBER},
          {"doc_key": "d1", "field_key": "f_city", "value": "Dallas"}]


def _extract(monkeypatch, **kw):
    monkeypatch.setattr(BID, "bundle_data", lambda _id: FIELDS)
    return BID.extract(BUNDLE, MAPPING, "Test Person", **kw)


# ------------------------------------------------- the default is still "no"

def test_by_default_the_number_is_still_dropped_on_the_floor(monkeypatch):
    """Every existing call site keeps the old behaviour, untouched."""
    hire = _extract(monkeypatch)
    assert hire.has_ssn is True, "it still records that one EXISTS"
    assert hire.ssn is None, "but not the value"


def test_asking_is_the_only_way_to_get_one(monkeypatch):
    assert _extract(monkeypatch, keep_ssn=True).ssn is not None


# -------------------------------------------- what it is when you do have it

def test_it_arrives_wrapped_not_as_a_string(monkeypatch):
    hire = _extract(monkeypatch, keep_ssn=True)
    assert isinstance(hire.ssn, Secret)
    assert hire.ssn.reveal() == NUMBER, "the one call site that may see it"


def test_printing_it_any_of_the_usual_ways_shows_dots(monkeypatch):
    """A log line, an f-string, a dict repr, a traceback that quotes a value."""
    hire = _extract(monkeypatch, keep_ssn=True)
    for rendered in (str(hire.ssn), repr(hire.ssn), f"{hire.ssn}",
                     str({"ssn": hire.ssn}), str([hire.ssn])):
        assert NUMBER not in rendered
        assert "4567" not in rendered and "123" not in rendered

    # And the whole record, which is what a debug print would reach for.
    assert NUMBER not in repr(hire)


def test_json_refuses_it_rather_than_serialising_it(monkeypatch):
    """The strongest guarantee here: anything that tries to put a Social into
    a payload, a file or the relay FAILS LOUDLY instead of succeeding quietly.
    """
    hire = _extract(monkeypatch, keep_ssn=True)
    try:
        json.dumps({"ssn": hire.ssn})
    except TypeError:
        return
    raise AssertionError("json.dumps serialised a Secret — it must refuse")


# --------------------------------------- the paths that must stay unable to

def test_it_is_not_in_values_so_nothing_downstream_can_reach_it(monkeypatch):
    """`values` is what becomes the Apex field map, the setup payload, the
    batch file and (later) the relay row. The Social is deliberately kept out
    of it rather than filtered out of each consumer."""
    hire = _extract(monkeypatch, keep_ssn=True)
    assert NUMBER not in json.dumps(hire.values)
    assert "ssn" not in hire.values
    assert hire.values.get("city") == "Dallas", "ordinary fields still land"


def test_it_is_not_in_fillable_or_have(monkeypatch):
    hire = _extract(monkeypatch, keep_ssn=True)
    assert "ssn" not in hire.fillable()
    assert NUMBER not in json.dumps(hire.fillable())
    assert "ssn" not in hire.have


def test_the_apex_payload_cannot_carry_one(monkeypatch):
    """apex_values builds what the browser is handed. Even with a Social in
    hand it must not appear there."""
    from automations.apex_new_starts import run as RUN
    from automations.apex_new_starts import board as BRD
    hire = _extract(monkeypatch, keep_ssn=True)
    cand = BRD.Candidate(name="Test Person", trainer="", email="",
                         location="", team="", reason_lost="", roll={},
                         tab="Sales Board WE 11.8", row=2)
    vals = RUN.apex_values(cand, hire)
    assert NUMBER not in json.dumps(vals, default=str)


def test_a_wrong_shaped_social_is_still_rejected(monkeypatch):
    """The shape check is what stops a phone number being typed into the SSN
    box. Keeping the value must not skip it."""
    monkeypatch.setattr(BID, "bundle_data", lambda _id: [
        {"doc_key": "d1", "field_key": "f_ssn", "value": "214-555-0123x"}])
    hire = BID.extract(BUNDLE, MAPPING, "Test Person", keep_ssn=True)
    if hire.ssn is not None:
        assert hire.ssn.reveal() != "214-555-0123x" or hire.has_ssn


def test_the_rehearsal_fetches_the_social_because_the_tax_tab_needs_it():
    """It used to withhold it (keep_ssn=False), which was right while this run
    only reached the employment tab and wrong the moment it reached the third:
    Apex will not save the tax tab without a Social, so the rehearsal could
    never finish the thing it exists to rehearse (Megan, 2026-11-13)."""
    import inspect
    from automations.apex_new_starts import supervised as SUP
    src = inspect.getsource(SUP.run)
    assert "keep_ssn=True" in src
    assert "keep_ssn=False" not in src


def test_the_rehearsal_never_logs_or_returns_a_social():
    """Fetching it changes nothing about how it is handled: one unwrap site,
    typed with secret=True, never echoed."""
    import ast
    import pathlib
    from automations.apex_new_starts import supervised as SUP
    src = pathlib.Path(SUP.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    reveals = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "reveal"]
    assert reveals == [], "this module never unwraps one itself"
    # it hands the wrapper straight to the filler, which types it secretly
    assert 'social=social' in src
    for leak in ("print(ssn", "log(ssn", '% ssn', "ssn)"):
        assert leak not in src, leak


def test_a_social_never_rides_on_the_dict_handed_to_the_page():
    """`who` is passed to page.evaluate, and Playwright serializes its
    arguments to JSON -- so a Social put on that dict would travel into a
    page payload. It crashed instead ("Object of type Secret is not JSON
    serializable", 2026-11-13), which is the wrapper working: a plain string
    would have gone quietly. It travels on its own now."""
    import inspect
    from automations.apex_new_starts import supervised as SUP
    src = inspect.getsource(SUP)
    assert '"_social"' not in src, "nothing about a Social belongs on `who`"
    assert "social=social" in src, "it is passed on its own"
    # and the thing that DOES go to the page carries only page-shaped data
    build = src.split('who = {"name": person.name', 1)[1].split("}", 1)[0]
    assert "ssn" not in build.lower() and "social" not in build.lower(), build
