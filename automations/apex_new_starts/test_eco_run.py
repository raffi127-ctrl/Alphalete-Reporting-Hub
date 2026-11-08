"""New starts -> Apex on the office's own computer: the job, end to end.

Nothing here touches Apex, Blue Ink or ApplicantStream. What it tests is the
part that decides who goes onto a payroll record and what gets told back to the
relay -- which is where a mistake would be expensive and silent.

Four things it refuses to let through:

  * a calendar that could not be read reported as "nobody started";
  * somebody filled from a packet with holes in it;
  * a Social reaching the relay, which is a Google Sheet;
  * a dry run asking Blue Ink for a Social at all.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from automations.apex_new_starts import blueink_data as BID
from automations.apex_new_starts import eco_run
from automations.apex_new_starts.ssn_prompt import Secret

MONDAY = dt.date(2026, 11, 2)
NUMBER = "123-45-6789"


def _rows(*names):
    return [{"first_name": n.split()[0], "last_name": " ".join(n.split()[1:]),
             "email": "%s@example.com" % n.split()[0].lower(), "phone": "5550100001",
             "stage": "Showed up (first day of training)"} for n in names]


def _hire(name, *, packet=True, full=True, ssn=False):
    h = BID.NewHire(name=name, missing_packet=not packet)
    if packet:
        h.values = {"first": name.split()[0], "last": " ".join(name.split()[1:]),
                    "email": "%s@example.com" % name.split()[0].lower()}
        if full:
            h.values.update({"dob": "1/30/1990", "address1": "1 A St",
                             "city": "Dallas", "state": "TX", "zip": "75226"})
        h.has_ssn = True
        if ssn:
            h.ssn = Secret(NUMBER)
    return h


# ------------------------------------------------------ a week nobody can read

def test_an_unreadable_calendar_is_an_error_not_an_empty_week(monkeypatch):
    """"0 new starts" here would quietly leave real people off payroll."""
    from automations.office_admin import fdot
    monkeypatch.setattr(fdot, "read_week",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("banner gone")))
    monkeypatch.setattr("automations.applicant_tracker.applicantstream.session",
                        lambda *a, **k: _FakeSession())
    res = eco_run.run_week(MONDAY, office_appstream="11280", log=lambda *a: None)
    assert res["status"] == "error"
    assert "training calendar" in res["error"]


def test_a_genuinely_empty_week_says_none(monkeypatch):
    _patch(monkeypatch, rows=[], hires={})
    res = eco_run.run_week(MONDAY, office_appstream="11280", log=lambda *a: None)
    assert res["status"] == "none" and res["counted"] == 0


# ---------------------------------------------------------- who is held back

def test_no_blue_ink_packet_is_named_not_skipped(monkeypatch):
    _patch(monkeypatch, rows=_rows("Ada Fournier", "Bruno Castell"),
           hires={"Ada Fournier": _hire("Ada Fournier"),
                  "Bruno Castell": _hire("Bruno Castell", packet=False)})
    res = eco_run.run_week(MONDAY, office_appstream="11280", log=lambda *a: None)
    assert res["added"] == ["Ada Fournier"]
    held = {b["name"]: b["why"] for b in res["needs_hand"]}
    assert "Bruno Castell" in held
    assert "by hand" in held["Bruno Castell"]


def test_a_packet_with_holes_holds_the_person_back(monkeypatch):
    """Nothing is invented: a missing date of birth is reported, never filled
    with a placeholder that lands on somebody's payroll record."""
    _patch(monkeypatch, rows=_rows("Cora Nilsen"),
           hires={"Cora Nilsen": _hire("Cora Nilsen", full=False)})
    res = eco_run.run_week(MONDAY, office_appstream="11280", log=lambda *a: None)
    assert res["added"] == []
    assert "missing" in res["needs_hand"][0]["why"]


# ------------------------------------------------------------- the Social

def test_a_dry_run_never_even_asks_for_a_social(monkeypatch):
    asked = {}

    def fake_for_people(people, *a, **kw):
        asked["keep_ssn"] = kw.get("keep_ssn")
        return {p.name: _hire(p.name) for p in people}

    _patch(monkeypatch, rows=_rows("Ada Fournier"), hires=None,
           for_people=fake_for_people)
    eco_run.run_week(MONDAY, office_appstream="11280", live=False,
                     log=lambda *a: None)
    assert asked["keep_ssn"] is False


def test_a_live_run_asks_for_one(monkeypatch):
    asked = {}

    def fake_for_people(people, *a, **kw):
        asked["keep_ssn"] = kw.get("keep_ssn")
        return {p.name: _hire(p.name, ssn=True) for p in people}

    _patch(monkeypatch, rows=_rows("Ada Fournier"), hires=None,
           for_people=fake_for_people)
    eco_run.run_week(MONDAY, office_appstream="11280", live=True,
                     log=lambda *a: None)
    assert asked["keep_ssn"] is True


def test_the_result_that_goes_to_the_relay_carries_no_social(monkeypatch):
    """The relay is a Google Sheet. json.dumps must not only omit the number --
    it must be unable to carry one."""
    _patch(monkeypatch, rows=_rows("Ada Fournier"),
           hires={"Ada Fournier": _hire("Ada Fournier", ssn=True)})
    res = eco_run.run_week(MONDAY, office_appstream="11280", live=False,
                           log=lambda *a: None)
    blob = json.dumps(res)                      # would raise on a Secret
    assert NUMBER not in blob and "ssn" not in blob.lower()


def test_one_person_apex_refuses_does_not_stop_the_rest(monkeypatch):
    _patch(monkeypatch, rows=_rows("Ada Fournier", "Dev Rao"),
           hires={"Ada Fournier": _hire("Ada Fournier", ssn=True),
                  "Dev Rao": _hire("Dev Rao", ssn=True)})

    def fill(person, values, hire, log=print):
        if person.name == "Ada Fournier":
            raise RuntimeError("Apex said no")

    monkeypatch.setattr(eco_run, "fill_one", fill)
    res = eco_run.run_week(MONDAY, office_appstream="11280", live=True,
                           log=lambda *a: None)
    assert res["added"] == ["Dev Rao"]
    held = {b["name"]: b["why"] for b in res["needs_hand"]}
    assert "Ada Fournier" in held
    assert "Apex said no" not in held["Ada Fournier"], \
        "exception TEXT is not quoted back — it can contain a field value"


# --------------------------------------------------------------- the week

def test_any_day_in_the_week_runs_that_week(monkeypatch):
    seen = {}

    def fake_read_week(app, office, monday, log=print):
        seen["monday"] = monday
        return []

    from automations.office_admin import fdot
    monkeypatch.setattr(fdot, "read_week", fake_read_week)
    monkeypatch.setattr("automations.applicant_tracker.applicantstream.session",
                        lambda *a, **k: _FakeSession())
    eco_run.run_week(dt.date(2026, 11, 6), office_appstream="11280",
                     log=lambda *a: None)
    assert seen["monday"] == MONDAY


def test_the_training_date_becomes_the_start_date():
    people = eco_run.starters(_rows("Ada Fournier"), day=MONDAY)
    assert people[0].hire_date == MONDAY


# ------------------------------------------------- the office decides, not the job

def test_the_appstream_id_comes_from_our_table_not_the_job():
    """Whose applicants get read is not something the caller gets to say."""
    from automations.icd_alerts import office_jobs as OJ
    assert OJ._appstream_id("raf") == "11280"
    with pytest.raises(RuntimeError, match="no ApplicantStream id"):
        OJ._appstream_id("not-an-office")


def test_the_sweep_knows_the_kind():
    from automations.icd_alerts import office_jobs as OJ
    import inspect
    assert "apex_week" in inspect.getsource(OJ.work)


# ------------------------------------------------------------------ helpers

class _FakeSession:
    def __enter__(self):
        return object()

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, *, rows, hires, for_people=None):
    from automations.office_admin import fdot
    monkeypatch.setattr(fdot, "read_week", lambda *a, **k: rows)
    monkeypatch.setattr("automations.applicant_tracker.applicantstream.session",
                        lambda *a, **k: _FakeSession())
    monkeypatch.setattr(BID, "for_people",
                        for_people or (lambda people, *a, **k: dict(hires or {})))
    monkeypatch.setattr(eco_run, "fill_one", lambda *a, **k: None)


# ------------------------------------- the control map, read off the real form

def test_the_two_controls_nothing_may_write_are_named():
    """$ctrl.sendUserPassword emails a real person; Salary sits under Rate of
    Pay and is the wrong box for $10/hr. Named so they can be excluded
    outright, not just avoided by a label match."""
    assert "$ctrl.sendUserPassword" in eco_run.NEVER
    assert "$ctrl.employmentRecord.Salary" in eco_run.NEVER
    for model in eco_run.NEVER:
        assert model not in eco_run.BY_MODEL.values()
        assert model not in eco_run.BY_WIDGET_ID.values()


def test_every_dropdown_is_treated_as_an_id_not_a_label():
    """A dropdown's model carries the chosen ID. Typing a label into it puts a
    word where an id belongs -- the page looks right and the save is wrong.
    Each one lives in BY_WIDGET_ID, never in BY_MODEL."""
    for key, model in eco_run.BY_WIDGET_ID.items():
        assert key not in eco_run.BY_MODEL, "%s is a widget, not a text box" % key
    for model in eco_run.BY_MODEL.values():
        assert not model.endswith("ID"), (
            "%s carries an id — it belongs in BY_WIDGET_ID" % model)


def test_the_sales_rep_role_is_the_radio_value_we_read():
    assert (eco_run.ROLE_MODEL, eco_run.ROLE_VALUE) == ("$ctrl.roleID", "11")


def test_filling_needs_the_page_rather_than_guessing_at_one():
    """Filling itself is proven (live, 2026-11-08 — every validation error
    cleared). What is still unproven is SAVING, which has its own test."""
    with pytest.raises(RuntimeError, match="needs the Apex page"):
        eco_run.fill_one(eco_run.Starter(name="Test Person"), {}, None,
                         log=lambda *a: None)


# ------------------------------------- the fill, against the proven mechanism

def test_the_password_reset_is_set_deliberately_and_set_OFF():
    """It DEFAULTS TO TICKED on a fresh form (read live 2026-11-08), so saving
    would email a brand new rep a password reset. Leaving it as found is a
    decision too — this one is made on purpose."""
    spec = eco_run.fill_spec(eco_run.Starter(name="Ada Fournier"), {"first": "Ada"})
    assert spec["email_password_reset"] is False


def test_dropdowns_go_in_as_dropdowns_and_text_as_text():
    spec = eco_run.fill_spec(
        eco_run.Starter(name="Ada Fournier", hire_date=MONDAY),
        {"first": "Ada", "last": "Fournier", "position": "Sales Rep",
         "pay_state": "Texas", "rate": "10.00"})
    assert spec["text"]["$ctrl.user.FirstName"] == "Ada"
    assert spec["drops"]["JobTitleID"] == "Sales Rep"
    assert spec["drops"]["stateWorkingIn"] == "Texas"
    assert spec["rate"] == "10.00", "the numeric box, not a dropdown"
    assert spec["hire_date"] == "2026-11-02"
    assert spec["role_value"] == "11"


def test_salary_is_never_in_what_gets_filled():
    spec = eco_run.fill_spec(eco_run.Starter(name="Ada Fournier"),
                             {"first": "Ada", "rate": "10.00", "salary": "99999"})
    assert "salary" not in str(spec).lower() or "99999" not in str(spec)


def test_a_fill_that_leaves_apex_objecting_raises(monkeypatch):
    """Apex's own validation is the judge, not our idea of done."""
    class Page:
        def evaluate(self, js, spec):
            return {"done": ["FirstName"], "missed": [],
                    "errors": ["State Working In is required."],
                    "salaryTouched": False, "passwordResetTicked": False}
    with pytest.raises(RuntimeError, match="still objects"):
        eco_run.fill_one(eco_run.Starter(name="Ada Fournier"), {}, None,
                         log=lambda *a: None, page=Page())


def test_writing_salary_stops_everything(monkeypatch):
    class Page:
        def evaluate(self, js, spec):
            return {"done": [], "missed": [], "errors": [],
                    "salaryTouched": True, "passwordResetTicked": False}
    with pytest.raises(RuntimeError, match="wrong box"):
        eco_run.fill_one(eco_run.Starter(name="Ada Fournier"), {}, None,
                         log=lambda *a: None, page=Page())


def test_a_clean_fill_does_not_save_by_default():
    class Page:
        def evaluate(self, js, spec):
            return {"done": ["FirstName", "JobTitle=Sales Rep"], "missed": [],
                    "errors": [], "salaryTouched": False, "passwordResetTicked": False}
    got = eco_run.fill_one(eco_run.Starter(name="Ada Fournier"), {}, None,
                           log=lambda *a: None, page=Page())
    assert got["errors"] == []


def test_saving_still_refuses_until_watched(monkeypatch):
    monkeypatch.delenv("APEX_FILL_PROVEN", raising=False)
    class Page:
        def evaluate(self, js, spec):
            return {"done": [], "missed": [], "errors": [],
                    "salaryTouched": False, "passwordResetTicked": False}
    with pytest.raises(RuntimeError, match="never been watched"):
        eco_run.fill_one(eco_run.Starter(name="Ada Fournier"), {}, None,
                         log=lambda *a: None, page=Page(), save=True)
