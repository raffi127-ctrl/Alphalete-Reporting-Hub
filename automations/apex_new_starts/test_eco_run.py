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
from automations.icd_onboarding import board as B
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


def _armed(monkeypatch, *, added=(), blocked=()):
    """Open the save gate and stand in for the driven engine.

    The gate is the real behaviour -- a live run refuses until somebody has
    watched one record save. These tests are about what happens AFTER that, so
    they arm it deliberately and never touch Apex.
    """
    monkeypatch.setenv("APEX_FILL_PROVEN", "1")
    monkeypatch.setattr(eco_run, "_genders_for",
                        lambda people, log=print: {})

    class _S:
        page = object()
        def require_login(self):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    monkeypatch.setattr(eco_run.apex, "ApexSession", lambda *a, **k: _S())
    monkeypatch.setattr(eco_run, "fill_week",
                        lambda page, ready, hires, week, genders=None, log=print:
                        {"added": list(added), "blocked": [dict(b) for b in blocked]})


def test_one_person_apex_refuses_does_not_stop_the_rest(monkeypatch):
    _patch(monkeypatch, rows=_rows("Ada Fournier", "Dev Rao"),
           hires={"Ada Fournier": _hire("Ada Fournier", ssn=True),
                  "Dev Rao": _hire("Dev Rao", ssn=True)})

    _armed(monkeypatch, added=["Dev Rao"],
           blocked=[{"name": "Ada Fournier", "why": "employment: Apex refused it"}])
    res = eco_run.run_week(MONDAY, office_appstream="11280", live=True,
                           log=lambda *a: None)
    assert res["added"] == ["Dev Rao"]
    held = {b["name"]: b["why"] for b in res["needs_hand"]}
    assert "Ada Fournier" in held


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


def _patch(monkeypatch, *, rows, hires, for_people=None, removed=(),
           genders=None):
    from automations.office_admin import fdot
    monkeypatch.setattr(fdot, "read_week", lambda *a, **k: rows)
    monkeypatch.setattr("automations.applicant_tracker.applicantstream.session",
                        lambda *a, **k: _FakeSession())
    monkeypatch.setattr(BID, "for_people",
                        for_people or (lambda people, *a, **k: dict(hires or {})))
    monkeypatch.setattr(eco_run, "fill_one", lambda *a, **k: None)
    # The board read is a GOOGLE SHEETS call. Unpatched, every one of these
    # tests opened Raf's live onboarding board -- about 67 seconds, and a unit
    # test that depends on today's real data (noticed 2026-11-11).
    monkeypatch.setattr(eco_run, "_removed_on_the_board",
                        lambda office_key, monday, log=print: set(removed))
    # The GENDER read is a Sheets call too, and it is read before the plan now
    # -- Apex refuses the profile tab without one. These people have one
    # unless a test says otherwise, because that is the ordinary case; the
    # test for a blank gender passes genders={}.
    if genders is None:
        genders = {("%s %s" % (r.get("first_name", ""),
                               r.get("last_name", ""))).strip(): "Female"
                   for r in rows}
    monkeypatch.setattr(eco_run, "_genders_for",
                        lambda people, log=print: dict(genders))


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


def test_a_box_that_did_not_take_its_value_raises(monkeypatch):
    """The READ-BACK is the judge now. Apex's own validation stopped being
    one when the create form was rewritten: it leaves "User Name is
    required." on screen over a filled box, and that refused four correct
    fills in a row (Luis Frias, 2026-11-24)."""
    class Page:
        def evaluate(self, js, spec):
            return {"done": [], "missed": [], "errors": [],
                    "readback": {"$ctrl.user.FirstName": ""},
                    "salaryTouched": False, "passwordResetTicked": False}
    with pytest.raises(RuntimeError, match="did not take"):
        eco_run.fill_one(eco_run.Starter(name="Ada Fournier"),
                         {"first": "Ada"}, None,
                         log=lambda *a: None, page=Page())


def test_a_stale_message_over_a_filled_box_does_not_raise():
    said = []

    class Page:
        def evaluate(self, js, spec):
            return {"done": ["FirstName"], "missed": [],
                    "errors": ["User Name is required."],
                    "readback": {"$ctrl.user.FirstName": "Ada"},
                    "salaryTouched": False, "passwordResetTicked": False}
    got = eco_run.fill_one(eco_run.Starter(name="Ada Fournier"),
                           {"first": "Ada"}, None,
                           log=said.append, page=Page())
    assert got["done"] == ["FirstName"]
    assert any("every value IS in" in s for s in said), said


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


def test_saving_goes_through_save_tab_and_nothing_else(monkeypatch):
    """The APEX_FILL_PROVEN gate is cleared (Megan, 2026-11-24: "clear the
    gate") -- it asked for one watched save and got one. What replaces it is
    not nothing: `save_tab` is the only way a Save is pressed, and it refuses
    an incomplete tab, a wrong value, or a form Angular still calls invalid,
    and proves the save by watching for the POST."""
    pressed = []

    class Page:
        def evaluate(self, js, spec=None):
            return {"done": ["FirstName"], "missed": [], "errors": [],
                    "readback": {"$ctrl.user.FirstName": "Ada"},
                    "salaryTouched": False, "passwordResetTicked": False}

    from automations.apex_new_starts import drive
    monkeypatch.setattr(drive, "save_tab",
                        lambda *a, **k: pressed.append(a) or True)
    got = eco_run.fill_one(eco_run.Starter(name="Ada Fournier"),
                           {"first": "Ada"}, None,
                           log=lambda *a: None, page=Page(), save=True)
    assert got["saved"] is True
    assert len(pressed) == 1


def test_a_save_that_does_not_go_through_is_not_reported_as_one(monkeypatch):
    class Page:
        def evaluate(self, js, spec=None):
            return {"done": ["FirstName"], "missed": [], "errors": [],
                    "readback": {"$ctrl.user.FirstName": "Ada"},
                    "salaryTouched": False, "passwordResetTicked": False}

    from automations.apex_new_starts import drive
    monkeypatch.setattr(drive, "save_tab", lambda *a, **k: False)
    with pytest.raises(RuntimeError, match="would not save"):
        eco_run.fill_one(eco_run.Starter(name="Ada Fournier"),
                         {"first": "Ada"}, None,
                         log=lambda *a: None, page=Page(), save=True)


def test_save_is_still_off_by_default(monkeypatch):
    """Clearing the gate did not arm anything. `save` stays False unless a
    caller asks, and the supervised run never asks."""
    import inspect
    sig = inspect.signature(eco_run.fill_one)
    assert sig.parameters["save"].default is False
    from automations.apex_new_starts import supervised as SUP
    assert "save=False" in inspect.getsource(SUP)


# ------------------------------------------- only where it has been switched on

def test_apex_is_off_for_every_office_except_rafs():
    """Megan, 2026-11-08: "we should only test on Raf's". This job creates
    payroll records, so off is the default and switching an office on is a
    deliberate edit."""
    from automations.office_admin import config as OC
    on = {k: o.apex_mode for k, o in OC.OFFICES.items() if o.apex_mode != "off"}
    assert set(on) == {"raf"}, "only Raf's office may run this yet, got %r" % on
    assert on["raf"] != "live", "and not live until a save has been watched"


def test_an_office_that_is_off_refuses_the_job_rather_than_running_it():
    from automations.icd_alerts import office_jobs as OJ
    res = OJ.work({"kind": "apex_week", "mode": "dry",
                   "payload": {"week_start": "2026-11-02"}},
                  "omar", log=lambda *a: None)
    assert res["status"] == "error"
    assert "not switched on" in res["error"]


def test_the_office_package_ships_what_the_job_needs():
    """The sweep runs on office Macs, which only have the files package.py
    lists. A job whose import fails answers 'error' and looks like a bug in
    the report rather than a missing file."""
    import pathlib, re
    src = pathlib.Path("automations/icd_alerts/package.py").read_text()
    listed = set(re.findall(r'"(automations/[^"]+)"', src))
    for need in ("automations/apex_new_starts/eco_run.py",
                 "automations/apex_new_starts/values.py",
                 "automations/apex_new_starts/blueink_data.py",
                 "automations/office_admin/fdot.py",
                 "automations/blueink_docs/blueink.py",
                 "automations/applicant_tracker/applicantstream.py"):
        assert need in listed, "%s never reaches the office computers" % need
    assert "automations/apex_new_starts/run.py" not in listed, (
        "run.py pulls the sales board and Google Sheets — values.py exists so "
        "it does not have to ship")


# --------------------------------------- telling the board what it saved

def test_a_live_run_ticks_added_to_apex_for_whoever_it_saved(monkeypatch):
    """The run knows who it saved at the moment it saves them."""
    told = {}
    from automations.icd_onboarding import fillers as F
    monkeypatch.setattr(F, "tick",
                        lambda office, week, source, names, **kw:
                        told.update(office=office, source=source,
                                    names=list(names), dry=kw.get("dry_run")) or 0)
    _patch(monkeypatch, rows=_rows("Ada Fournier", "Dev Rao"),
           hires={"Ada Fournier": _hire("Ada Fournier", ssn=True),
                  "Dev Rao": _hire("Dev Rao", ssn=True)})
    _armed(monkeypatch, added=["Ada Fournier", "Dev Rao"])
    eco_run.run_week(MONDAY, office_appstream="11280", office_key="raf",
                     live=True, log=lambda *a: None)
    assert told["office"] == "raf" and told["source"] == "apex"
    assert sorted(told["names"]) == ["Ada Fournier", "Dev Rao"]
    assert told["dry"] is False, "a live run really ticks"


def test_a_dry_run_tells_the_board_nothing(monkeypatch):
    called = []
    from automations.icd_onboarding import fillers as F
    monkeypatch.setattr(F, "tick", lambda *a, **k: called.append(a) or 0)
    _patch(monkeypatch, rows=_rows("Ada Fournier"),
           hires={"Ada Fournier": _hire("Ada Fournier")})
    eco_run.run_week(MONDAY, office_appstream="11280", office_key="raf",
                     live=False, log=lambda *a: None)
    assert called == [], "nothing happened, so there is nothing to say"


def test_a_board_that_cannot_be_ticked_never_fails_the_run(monkeypatch):
    """The payroll records are already saved. Raising here would report a
    failure for work that succeeded and send somebody looking for people who
    are in fact in Apex."""
    from automations.icd_onboarding import fillers as F
    monkeypatch.setattr(F, "tick",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no board")))
    _patch(monkeypatch, rows=_rows("Ada Fournier"),
           hires={"Ada Fournier": _hire("Ada Fournier", ssn=True)})
    _armed(monkeypatch, added=["Ada Fournier"])
    said = []
    res = eco_run.run_week(MONDAY, office_appstream="11280", office_key="raf",
                           live=True, log=said.append)
    assert res["status"] == "filled"
    assert res["added"] == ["Ada Fournier"]
    assert any("ARE saved" in s for s in said), "and it says so plainly"


def test_an_office_key_nobody_passed_is_simply_skipped(monkeypatch):
    from automations.icd_onboarding import fillers as F
    monkeypatch.setattr(F, "tick",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    _patch(monkeypatch, rows=_rows("Ada Fournier"),
           hires={"Ada Fournier": _hire("Ada Fournier", ssn=True)})
    eco_run.run_week(MONDAY, office_appstream="11280", live=True,
                     log=lambda *a: None)


def test_the_sweep_passes_the_office_key_through():
    import inspect
    from automations.icd_alerts import office_jobs as OJ
    assert "office_key=office_key" in inspect.getsource(OJ.work)


# ------------------------------- only people still on the onboarding checklist

def test_somebody_removed_on_the_board_never_reaches_apex(monkeypatch):
    """Megan, 2026-11-11: "you should only add those then NOT removed from the
    OBCL". The calendar says who showed up for training; the board says who is
    still going through onboarding, and between the two somebody quits,
    no-shows or fails a check. An Apex record is payroll with no undo."""
    seen = []
    monkeypatch.setattr(eco_run, "plan",
                        lambda people, hires, log=print, office_key="":
                        seen.append([p.name for p in people])
                        or {"ready": [], "blocked": []})
    _patch(monkeypatch, rows=_rows("Ada Fournier", "Dev Rao"),
           hires={"Ada Fournier": _hire("Ada Fournier"),
                  "Dev Rao": _hire("Dev Rao")},
           removed=[B._fold("Dev Rao")])
    eco_run.run_week(MONDAY, office_appstream="11280", office_key="raf",
                     live=False, log=lambda *a: None)
    assert seen == [["Ada Fournier"]], seen


def test_a_board_that_cannot_be_read_refuses_rather_than_adding_everybody(monkeypatch):
    """"I could not look" must never pass for "nobody was removed" -- that is
    how somebody the ICD took off lands on payroll."""
    def _boom(*a, **k):
        raise RuntimeError("Sheets said no")
    _patch(monkeypatch, rows=_rows("Ada Fournier"),
           hires={"Ada Fournier": _hire("Ada Fournier")})
    monkeypatch.setattr(eco_run, "_removed_on_the_board", _boom)
    res = eco_run.run_week(MONDAY, office_appstream="11280", office_key="raf",
                           live=False, log=lambda *a: None)
    assert res["status"] == "error"
    assert "removed is unknown" in res["error"], res["error"]


def test_everyone_removed_is_a_week_with_nobody_not_a_crash(monkeypatch):
    _patch(monkeypatch, rows=_rows("Ada Fournier"),
           hires={"Ada Fournier": _hire("Ada Fournier")},
           removed=[B._fold("Ada Fournier")])
    res = eco_run.run_week(MONDAY, office_appstream="11280", office_key="raf",
                           live=False, log=lambda *a: None)
    assert res["status"] == "none"


# --------------------------------------------- the gate, and what it stands for

def test_a_live_run_no_longer_stops_at_the_watched_save_gate(monkeypatch):
    """The gate is cleared. What still stands between a live run and a
    payroll record is `plan` (which holds anybody with a gap), the board's
    removals, and `save_tab`'s own refusals -- not a flag."""
    monkeypatch.delenv("APEX_FILL_PROVEN", raising=False)
    _patch(monkeypatch, rows=_rows("Ada Fournier"),
           hires={"Ada Fournier": _hire("Ada Fournier", ssn=True)})
    touched = []
    monkeypatch.setattr(eco_run, "fill_week",
                        lambda *a, **k: touched.append(a) or {"added": [], "blocked": []})
    res = eco_run.run_week(MONDAY, office_appstream="11280", office_key="raf",
                           live=True, log=lambda *a: None)
    assert res["status"] != "error" or "never been watched" not in (
        res.get("error") or "")


def test_a_live_run_is_still_off_for_every_office_but_rafs():
    """Clearing the gate did not switch anybody on. This is what keeps a
    live run from reaching anyone else's payroll."""
    from automations.office_admin import config as OC
    on = {k: o.apex_mode for k, o in OC.OFFICES.items() if o.apex_mode != "off"}
    assert set(on) == {"raf"}, "only Raf's office may run this, got %r" % on


def test_the_payload_is_built_with_the_engines_own_field_map():
    """Writing a second values-to-page mapping here is how the two copies of
    this would start disagreeing about which Apex box a value belongs in."""
    import inspect
    src = inspect.getsource(eco_run.payload_for)
    assert "rows_for" in src, "it has to use filler.rows_for"


def test_silence_about_a_person_is_never_a_save():
    """The engine reports per person. Somebody it said nothing about did not
    go in -- counting them as added would tick a board for a payroll record
    that does not exist."""
    got = eco_run._from_report(
        [{"name": "Ada Fournier", "ok": True}],
        ["Ada Fournier", "Dev Rao"], log=lambda *a: None)
    assert got["added"] == ["Ada Fournier"]
    assert [b["name"] for b in got["blocked"]] == ["Dev Rao"]


def test_a_report_that_came_back_empty_blocks_everybody():
    got = eco_run._from_report(None, ["Ada Fournier"], log=lambda *a: None)
    assert got["added"] == []
    assert got["blocked"][0]["name"] == "Ada Fournier"


def test_an_office_with_no_rate_holds_the_person_back(monkeypatch):
    """Apex REFUSES the save without a Rate of Pay -- the first completed
    record bounced on exactly that. And the rate is the office's own, so a
    missing one must hold the person back, not quietly pay them Alphalete's
    (Megan, 2026-11-12)."""
    from automations.apex_new_starts import values as V
    monkeypatch.setattr(V, "apex_values",
                        lambda c, hire, office_key="": {
                            "dob": "10/25/2002", "address1": "x",
                            "city": "Dallas", "zip": "75262",
                            "gender": "Female"})
    person = eco_run.Starter(name="Ada Fournier", email="a@b.c")
    got = eco_run.plan([person], {"Ada Fournier": _hire("Ada Fournier")},
                       log=lambda *a: None, office_key="someone")
    assert got["ready"] == []
    why = got["blocked"][0]["why"]
    assert "Rate of Pay" in why and "enrolment" in why, why


def test_a_rate_that_is_there_lets_them_through(monkeypatch):
    """The two state answers are in here because they hold too (2026-11-22):
    what lets somebody through is a COMPLETE set, not a rate on its own."""
    from automations.apex_new_starts import values as V
    monkeypatch.setattr(V, "apex_values",
                        lambda c, hire, office_key="": {
                            "dob": "10/25/2002", "address1": "x",
                            "city": "Dallas", "zip": "75262",
                            "rate": "12.00", "gender": "Female",
                            "pay_state": "Texas", "tax_state": "Texas"})
    person = eco_run.Starter(name="Ada Fournier", email="a@b.c")
    got = eco_run.plan([person], {"Ada Fournier": _hire("Ada Fournier")},
                       log=lambda *a: None, office_key="jacob")
    assert [p.name for p, _ in got["ready"]] == ["Ada Fournier"]


def test_nobody_without_a_gender_is_started():
    """Megan, 2026-11-13: "we need to only run on the ones I gave you genders
    for." Apex refuses the profile tab without one, so starting such a person
    does not fail early -- it saves the employment tab and THEN stops, leaving
    a part-filled record that looks half done. They are held before anything
    is typed, and nothing guesses a gender."""
    import datetime as dt
    from automations.apex_new_starts import blueink_data as BID
    from automations.apex_new_starts import eco_run as E

    who = E.Starter(name="Ada Fournier", hire_date=dt.date(2026, 11, 9))
    hire = BID.NewHire(name="Ada Fournier", values={
        "first": "Ada", "last": "Fournier", "dob": "01/02/1990",
        "address1": "1 Main St", "city": "Plano", "state": "TX",
        "zip": "75075", "filing_single": "True"})
    got = E.plan([who], {"Ada Fournier": hire}, log=lambda *a: None,
                 office_key="raf")
    assert got["ready"] == [], "no gender means not ready"
    assert len(got["blocked"]) == 1
    why = got["blocked"][0]["why"]
    assert "gender" in why.lower(), why
    assert "guess" in why.lower(), "and it says why nothing fills it"


def test_the_boards_gender_reaches_the_plan(monkeypatch):
    """It lives on the BOARD, and people are built from the training
    calendar, which has no such column. Without carrying it across, holding
    anybody without a gender would hold EVERYBODY -- including the ones
    somebody had just typed in (2026-11-13)."""
    _patch(monkeypatch, rows=_rows("Ada Fournier", "Bruno Castell"),
           hires={"Ada Fournier": _hire("Ada Fournier"),
                  "Bruno Castell": _hire("Bruno Castell")},
           genders={"Ada Fournier": "Female"})     # Bruno has none
    res = eco_run.run_week(MONDAY, office_appstream="11280",
                           log=lambda *a: None)
    assert res["added"] == ["Ada Fournier"], res
    held = {b["name"]: b["why"] for b in res["needs_hand"]}
    assert "Bruno Castell" in held
    assert "gender" in held["Bruno Castell"].lower(), held["Bruno Castell"]


def test_the_gender_is_worked_out_once_not_twice():
    """It was worked out a second time further down, after the gate, for the
    engine path -- the same answer twice. Off the board since 2026-11-24, so
    it is no longer a Sheets call, but doing it twice would still mean two
    different lists of "names it would not call" in one run's log."""
    import inspect
    src = inspect.getsource(eco_run.run_week)
    assert src.count("_genders_for(") == 1, src.count("_genders_for(")


def _answered(monkeypatch):
    """An office that HAS given its two state answers.

    The real `apex_values` drops pay_state and tax_state for an office that
    has not, and since 2026-11-22 that holds the person back -- correctly, but
    it would make every test below fail for a reason that is not what it is
    testing. 0 of 41 offices have answered them, so without this the name
    tests would only ever be testing the state hold.
    """
    from automations.icd_onboarding import office_steps as OS
    monkeypatch.setattr(OS, "apex_unanswered", lambda *a, **k: [])
    monkeypatch.setattr(OS, "apex_settings",
                        lambda *a, **k: {"pay_state": "Texas",
                                         "tax_state": "Texas"})
    monkeypatch.setattr(OS, "rate_of_pay", lambda *a, **k: "10.00")


def _chrisjen():
    """The packet and AppStream disagree about his surname."""
    import datetime as dt
    from automations.apex_new_starts import blueink_data as BID
    from automations.apex_new_starts import eco_run as E
    who = E.Starter(name="Chrisjen Davis", gender="Male",
                    hire_date=dt.date(2026, 11, 9))
    hire = BID.NewHire(name="Chrisjen Davis", values={
        "first": "Chrisjen", "last": "Dav", "dob": "09/28/2005",
        "address1": "3701 James Pitt rd", "city": "McKinney",
        "state": "TX", "zip": "75071", "filing_single": "True"})
    return who, hire


def test_a_disagreeing_name_travels_as_a_dispute_not_a_block(monkeypatch):
    """Chrisjen Davis wrote "Dav" in the Last Name box of his own I-9, so the
    packet said Chrisjen Dav while AppStream -- which seeds the board -- said
    Chrisjen Davis.

    It is NOT a block on its own. Megan, 2026-11-15: "UNLESS you find it in
    the pending where it matches app stream and you can just know it's
    correct". Being on Apex's Pending list under AppStream's spelling is the
    confirmation, and only the triage can see that -- so the dispute rides
    along to be settled there.
    """
    from automations.apex_new_starts import eco_run as E
    _answered(monkeypatch)
    who, hire = _chrisjen()
    got = E.plan([who], {"Chrisjen Davis": hire}, log=lambda *a: None,
                 office_key="raf")
    assert [p.name for p, _ in got["ready"]] == ["Chrisjen Davis"], got
    said = got["ready"][0][1]["_name_dispute"]
    assert "Dav" in said and "Davis" in said, "say what each source claims"


def test_a_disputed_name_is_never_typed_into_the_form():
    """`values` is what gets typed. A marker in it must not reach a box, and
    must not be read out as a field in the before-the-browser printout."""
    import ast
    import inspect
    import pathlib
    from automations.apex_new_starts import drive as D
    from automations.apex_new_starts import supervised as S

    tree = ast.parse(pathlib.Path(D.__file__).read_text())
    keys = {n.slice.value for n in ast.walk(tree)
            if isinstance(n, ast.Subscript)
            and isinstance(n.slice, ast.Constant)
            and isinstance(n.slice.value, str)}
    assert "_name_dispute" not in keys, "drive must not type the marker"

    assert all("_name_dispute" not in line
               for line in inspect.getsource(S._describe).splitlines()
               if not line.strip().startswith("#"))
    shown = S._describe({"first": "Chrisjen", "last": "Dav",
                         "_name_dispute": "packet says Dav"})
    assert not any("dispute" in line for line in shown), shown


def test_pending_settles_a_dispute_and_appstream_wins():
    """On the COMPLETE path they were FOUND on Pending under AppStream's
    spelling -- somebody already put them there under that name -- so that
    spelling is the right one and it is what gets typed, not the packet's."""
    import ast
    import pathlib
    from automations.apex_new_starts import supervised as S

    src = pathlib.Path(S.__file__).read_text()
    body = ast.get_source_segment(src, next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "_complete"))
    code = "\n".join(l for l in body.splitlines()
                      if not l.strip().startswith("#"))
    assert '_name_dispute' in code, "_complete has to settle it"
    assert 'person.name' in code, "AppStream's spelling is the one typed"
    assert '"last"' in code and '"first"' in code


def test_creating_somebody_on_a_disputed_name_is_refused():
    """Not on Pending either means nothing here can tell which spelling is
    right, and a wrong surname on a NEW payroll record never matches them
    again. An admin says which, then it runs."""
    import ast
    import pathlib
    from automations.apex_new_starts import supervised as S

    src = pathlib.Path(S.__file__).read_text()
    body = ast.get_source_segment(src, next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "run"))
    code = [l for l in body.splitlines()
            if not l.strip().startswith("#")]
    where = [i for i, l in enumerate(code) if "_name_dispute" in l]
    assert where, "run() has to check for a dispute"
    after = "\n".join(code[where[0]:where[0] + 12])
    assert "drive.ADD" in "\n".join(code[max(0, where[0] - 2):where[0] + 2])
    assert "return 1" in after, "it refuses, it does not create them"


def test_the_same_name_spelled_differently_is_not_a_disagreement(monkeypatch):
    """"McCrobie" and "Mccrobie" are one name written two ways. Holding on
    that would stop everybody."""
    import datetime as dt
    from automations.apex_new_starts import blueink_data as BID
    from automations.apex_new_starts import eco_run as E

    _answered(monkeypatch)
    who = E.Starter(name="Alexandria Mccrobie", gender="Female",
                    hire_date=dt.date(2026, 11, 9))
    hire = BID.NewHire(name="Alexandria Mccrobie", values={
        "first": "Alexandria", "last": "McCrobie", "dob": "04/04/2007",
        "address1": "704 green coral Dr", "city": "Little elm",
        "state": "TX", "zip": "75068", "filing_single": "True"})
    got = E.plan([who], {"Alexandria Mccrobie": hire}, log=lambda *a: None,
                 office_key="raf")
    assert [p.name for p, _ in got["ready"]] == ["Alexandria Mccrobie"], got


def test_the_engine_path_settles_a_dispute_by_where_they_were_found():
    """The supervised rehearsal is not what the ECO run uses. Both have to
    settle a disputed name the same way, or the thing that runs by itself at
    4am behaves differently from the thing that was watched working."""
    import ast
    import pathlib
    from automations.apex_new_starts import eco_run as E

    src = pathlib.Path(E.__file__).read_text()
    body = ast.get_source_segment(src, next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "fill_week"))
    code = [l for l in body.splitlines() if not l.strip().startswith("#")]
    joined = "\n".join(code)
    assert "_name_dispute" in joined, "fill_week has to settle it"
    assert "drive.COMPLETE" in joined and "drive.ADD" in joined

    at = next(i for i, l in enumerate(code) if "to_add = [" in l)
    create = "\n".join(code[at:at + 4])
    assert "not in disputed" in create, \
        "a disputed name is never given a NEW payroll record"


def test_a_disputed_name_not_on_pending_goes_back_as_an_ask():
    """A refusal that only reaches a log reaches nobody. Megan, 2026-11-15:
    "that 'alert' needs to go back to the admin to approve the correct name
    so that you can run it"."""
    import ast
    import inspect
    import pathlib
    from automations.apex_new_starts import eco_run as E

    assert "fillers" in inspect.getsource(E._ask_the_board)
    assert "dry_run=False" in inspect.getsource(E._ask_the_board)

    src = pathlib.Path(E.__file__).read_text()
    body = ast.get_source_segment(src, next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "run_week"))
    code = "\n".join(l for l in body.splitlines()
                     if not l.strip().startswith("#"))
    assert "_ask_the_board(" in code, "run_week has to send the ask"

    # And ONLY an ask goes to the board -- not every held person. A gender
    # nobody has typed in is not an admin decision about a name.
    at = code.index("_ask_the_board(")
    assert 'b.get("ask")' in code[at:at + 320], code[at:at + 320]


# ------------------------------------------ a missing office key is not an answer

def test_no_office_key_is_not_an_office_with_nobody_removed():
    """The OBCL's removals are the gate between the training calendar and a
    payroll record. A blank key used to return an empty removal set, which the
    caller cannot tell apart from "I looked and nobody was removed" -- so a
    person the ICD took off the board would go to Apex. It raises instead, and
    run_week already turns a removal read it could not do into an error."""
    with pytest.raises(RuntimeError) as e:
        eco_run._removed_on_the_board("", MONDAY, log=lambda *a: None)
    assert "no office key" in str(e.value)


def test_a_removal_read_that_fails_stops_the_run(monkeypatch):
    _patch(monkeypatch, rows=_rows("Ada Fournier"),
           hires={"Ada Fournier": _hire("Ada Fournier")})
    monkeypatch.setattr(eco_run, "_removed_on_the_board",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no key")))
    res = eco_run.run_week(MONDAY, office_appstream="11280", office_key="",
                           log=lambda *a: None)
    assert res["status"] == "error" and "removed is unknown" in res["error"]


def test_a_name_it_will_not_call_is_left_out_and_said_out_loud():
    """Gender is guessed from the first name at the moment Apex is typed
    (Megan, 2026-11-24). A name the guesser will not call is LEFT OUT, exactly
    as a blank column was -- the engine then leaves that box alone and says it
    missed it, rather than picking one. The unsure list is the load-bearing
    half: a guess here lands on a payroll record, so "no idea" has to look
    different from an answer.
    """
    class _P:
        def __init__(self, first, last):
            self.first_name, self.last_name = first, last

    said = []
    got = eco_run._genders_for([_P("Jessica", "Hale"), _P("Xyzzy", "Quine")],
                               log=said.append)
    told = " ".join(said)
    assert got.get("Jessica Hale"), got
    assert "Xyzzy Quine" not in got
    assert "would not call" in told and "Xyzzy Quine" in told, told


def test_nobody_to_guess_for_is_not_an_error():
    said = []
    assert eco_run._genders_for([], log=said.append) == {}


# ------------------------------------- the two answers that land on a tax record

def test_an_office_with_no_state_answers_holds_the_person_back(monkeypatch):
    """`values.apex_values` DROPS pay_state and tax_state for an office that
    has not answered them, so Texas cannot reach a Florida office's tax
    record. For a month the drop worked and the hold did not: this list never
    named the two fields, so on 2026-11-22 all 26 of Raf's week came back
    "ready" with no State Working In and no State to be taxed in -- which a
    live run either gets refused for mid-save, leaving a part-filled payroll
    record, or lands as a blank state on a tax record.

    A dropped value and a held person are one decision. This is the half that
    went missing."""
    from automations.apex_new_starts import values as V
    monkeypatch.setattr(V, "apex_values",
                        lambda c, hire, office_key="": {
                            "dob": "10/25/2002", "address1": "x",
                            "city": "Dallas", "zip": "75262",
                            "rate": "12.00", "gender": "Female"})
    person = eco_run.Starter(name="Ada Fournier", email="a@b.c")
    got = eco_run.plan([person], {"Ada Fournier": _hire("Ada Fournier")},
                       log=lambda *a: None, office_key="someone")
    assert got["ready"] == []
    why = got["blocked"][0]["why"]
    assert "State Working In" in why and "State to be taxed in" in why, why


def test_each_gap_says_where_its_answer_lives(monkeypatch):
    """The packet, the enrolment form and the board are three different
    places and three different people. One message saying "missing
    pay_state" sends somebody to read a packet that was never going to have
    it."""
    from automations.apex_new_starts import values as V
    monkeypatch.setattr(V, "apex_values",
                        lambda c, hire, office_key="": {"city": "Dallas"})
    person = eco_run.Starter(name="Ada Fournier", email="a@b.c")
    got = eco_run.plan([person], {"Ada Fournier": _hire("Ada Fournier")},
                       log=lambda *a: None, office_key="someone")
    why = got["blocked"][0]["why"]
    assert "their packet is missing" in why, why
    assert "this office's enrolment has no" in why, why
    assert "no gender on the board" in why, why
    # and the packet gaps are named as packet gaps, not lumped in with ours
    assert "dob" in why.split("this office")[0], why


# ---------------------------------------- the create form, as Apex rewrote it

# probe_create, 2026-11-24, on the live /employees/new: window.jQuery,
# window.$, window.kendo and window.angular are ALL undefined. The ng-model
# attributes are still in the markup as dead text, so the old fill found every
# element, reported no misses, and Apex refused to save because no binding had
# heard anything (Megan: "nothing is filling").

def _code_only(js):
    """The JS with its /* */ comments stripped. The comments NAME the globals
    that are gone, so asserting over the whole string fails on its own
    explanation."""
    import re
    return re.sub(r"/\*.*?\*/", "", js, flags=re.S)


def test_the_fill_needs_no_framework():
    js = _code_only(eco_run.FILL_JS)
    assert "window.jQuery" not in js
    assert "window.$" not in js
    assert "kendo" not in js.lower()
    assert "$(" not in js


def test_it_sets_both_boxes_of_a_paired_control():
    """User Name, Account Email and Rate of Pay are each a visible input with
    no id over the real one that carries the value the form posts. Setting
    one and not the other is what produced "User Name is required" on a form
    that looked filled."""
    js = eco_run.FILL_JS
    assert "const twin =" in js
    body = js.split("const setText =", 1)[1].split("};", 1)[0]
    assert "twin(el)" in body and "put(t, val)" in body


def test_a_dropdown_mirrors_its_choice_into_the_hidden_input():
    """The <select> has no name, so it does not post -- the hidden input
    beside it does."""
    body = eco_run.FILL_JS.split("const setDrop =", 1)[1].split("};", 1)[0]
    assert "sel.value = o.value" in body
    assert "put(idEl, o.value)" in body


def test_an_unknown_option_names_every_option_it_does_have():
    body = eco_run.FILL_JS.split("const setDrop =", 1)[1].split("};", 1)[0]
    assert "it offers: " in body


def test_hire_date_fills_the_picker_as_well_as_the_date_box():
    body = eco_run.FILL_JS.split("if (spec.hire_date)", 1)[1]
    assert "twin(real)" in body
    assert "m + '/' + d + '/' + y" in body, "the visible picker reads MM/dd/yyyy"


def test_salary_is_still_never_written():
    """Salary sits directly under Rate of Pay and is the wrong box for $10/hr."""
    js = eco_run.FILL_JS
    assert "salaryTouched" in js
    assert "put(salary" not in js


def test_the_password_reset_box_is_still_set_deliberately():
    js = eco_run.FILL_JS
    assert "$ctrl.sendUserPassword" in js
    assert "passwordResetTicked" in js


def test_the_spec_shape_did_not_change():
    """fill_spec and its tests are unchanged on purpose: only the DOM
    mechanics moved, so a spec built for the old page still drives the new
    one."""
    person = eco_run.Starter(name="Ada Fournier", hire_date=dt.date(2026, 11, 23))
    spec = eco_run.fill_spec(person, {"first": "Ada", "position": "Sales Rep",
                                      "rate": "10.00"})
    assert set(spec) == {"text", "drops", "hire_date", "rate", "role_value",
                         "email_password_reset"}
    assert spec["text"] == {"$ctrl.user.FirstName": "Ada"}
    assert spec["drops"] == {"JobTitleID": "Sales Rep"}
    assert spec["hire_date"] == "2026-11-23"


# ------------------- the verdict is the read-back, not the red messages

def test_unfilled_names_a_box_that_did_not_take():
    spec = {"text": {"$ctrl.userName": "a@b.c"}, "drops": {},
            "hire_date": "", "rate": ""}
    assert eco_run.unfilled(spec, {"$ctrl.userName": ""}) == ["userName"]
    assert eco_run.unfilled(spec, {"$ctrl.userName": "a@b.c"}) == []


def test_unfilled_matches_a_dropdown_by_its_suffix():
    spec = {"text": {}, "drops": {"JobTitleID": "Sales Rep"},
            "hire_date": "", "rate": ""}
    assert eco_run.unfilled(
        spec, {"$ctrl.employmentRecord.JobTitleID": "5"}) == []
    assert eco_run.unfilled(
        spec, {"$ctrl.employmentRecord.JobTitleID": ""}) == ["JobTitleID"]


def test_unfilled_covers_hire_date_and_rate():
    spec = {"text": {}, "drops": {}, "hire_date": "2026-11-23", "rate": "10.00"}
    assert sorted(eco_run.unfilled(spec, {})) == ["HireDate", "PayRate"]
    assert eco_run.unfilled(spec, {
        "$ctrl.employmentRecord.HireDate": "2026-11-23",
        "$ctrl.employmentRecord.PayRate": "10"}) == []


def test_a_stale_red_message_no_longer_refuses_a_filled_form():
    """Four correct fills in a row were thrown away for "User Name is
    required" over a User Name box holding the right address."""
    import inspect
    body = inspect.getsource(eco_run.fill_one)
    assert "unfilled(" in body
    assert body.index("unfilled(") < body.index('got.get("errors")')
    assert "Apex still objects" not in body


# ------------------- gender is assumed from the name, and only where clear

def test_an_unwatched_run_still_holds_a_person_with_no_gender(monkeypatch):
    """Nobody is there to say, and a coin flip lands on a payroll record."""
    from automations.apex_new_starts import values as V
    monkeypatch.setattr(V, "apex_values",
                        lambda c, hire, office_key="": {
                            "dob": "1/1/2000", "address1": "a", "city": "b",
                            "zip": "1", "rate": "10", "pay_state": "Texas",
                            "tax_state": "Texas", "gender": ""})
    person = eco_run.Starter(name="Kimble Townsend")
    got = eco_run.plan([person], {"Kimble Townsend": _hire("Kimble Townsend")},
                       log=lambda *a: None, office_key="raf")
    assert got["ready"] == []
    assert "no gender" in got["blocked"][0]["why"]


def test_a_watched_run_fills_everything_else_and_names_the_one_box(monkeypatch):
    """Megan, 2026-11-24: "remember that we're assuming gender based on
    name". The guesser will not call "Kimble", and holding the whole record
    for one dropdown is the wrong trade when somebody is reading the form."""
    from automations.apex_new_starts import values as V
    monkeypatch.setattr(V, "apex_values",
                        lambda c, hire, office_key="": {
                            "dob": "1/1/2000", "address1": "a", "city": "b",
                            "zip": "1", "rate": "10", "pay_state": "Texas",
                            "tax_state": "Texas", "gender": ""})
    person = eco_run.Starter(name="Kimble Townsend")
    got = eco_run.plan([person], {"Kimble Townsend": _hire("Kimble Townsend")},
                       log=lambda *a: None, office_key="raf", watched=True)
    assert len(got["ready"]) == 1
    assert got["ready"][0][1]["_set_yourself"] == "Gender"


def test_a_watched_run_still_holds_on_anything_else(monkeypatch):
    """Only gender is handed to the person. A missing address or rate is a
    real gap and still holds, watched or not."""
    from automations.apex_new_starts import values as V
    monkeypatch.setattr(V, "apex_values",
                        lambda c, hire, office_key="": {
                            "dob": "1/1/2000", "address1": "", "city": "b",
                            "zip": "1", "rate": "10", "pay_state": "Texas",
                            "tax_state": "Texas", "gender": ""})
    person = eco_run.Starter(name="Kimble Townsend")
    got = eco_run.plan([person], {"Kimble Townsend": _hire("Kimble Townsend")},
                       log=lambda *a: None, office_key="raf", watched=True)
    assert got["ready"] == []


# ------------- the pop-up: names and assumed gender, confirmed before Send

# Megan, 2026-11-24: "when someone pushes the button to send to apex - we
# should pop up the names and gender we assume - then the admin/icd sending
# can change if they want before hitting send."

def test_a_preview_opens_nothing_and_lists_who_with_what_gender(monkeypatch):
    _patch(monkeypatch, rows=_rows("Ada Fournier"),
           hires={"Ada Fournier": _hire("Ada Fournier", ssn=True)})
    touched = []
    monkeypatch.setattr(eco_run, "fill_week",
                        lambda *a, **k: touched.append(a) or {"added": [], "blocked": []})
    res = eco_run.run_week(MONDAY, office_appstream="11280", office_key="raf",
                           live=True, preview=True, log=lambda *a: None)
    assert res["status"] == "preview"
    assert touched == [], "a preview must not open Apex"
    assert res["added"] == []
    names = [p["name"] for p in res["people"]]
    assert "Ada Fournier" in names
    assert set(res["people"][0]) == {"name", "gender", "from"}


def test_a_confirmed_gender_beats_the_guess(monkeypatch):
    """The guesser calls "Ada" Female. A person who says Male is answering,
    not guessing, and an answer is never re-guessed."""
    _patch(monkeypatch, rows=_rows("Ada Fournier"),
           hires={"Ada Fournier": _hire("Ada Fournier", ssn=True)})
    monkeypatch.setattr(eco_run, "fill_week",
                        lambda *a, **k: {"added": [], "blocked": []})
    res = eco_run.run_week(MONDAY, office_appstream="11280", office_key="raf",
                           live=True, preview=True,
                           genders={"Ada Fournier": "Male"},
                           log=lambda *a: None)
    row = [p for p in res["people"] if p["name"] == "Ada Fournier"][0]
    assert row["gender"] == "Male"
    assert row["from"] == "confirmed"


def test_the_preview_says_where_each_gender_came_from(monkeypatch):
    """A guess and an answer must not look the same in the pop-up, or the
    person has no way to know which ones need their attention."""
    # genders={} = the guesser called nobody, which is what it really does
    # for "Kimble" (gender_suggest.suggest("Kimble") is "").
    _patch(monkeypatch, rows=_rows("Kimble Townsend"),
           hires={"Kimble Townsend": _hire("Kimble Townsend", ssn=True)},
           genders={})
    monkeypatch.setattr(eco_run, "fill_week",
                        lambda *a, **k: {"added": [], "blocked": []})
    res = eco_run.run_week(MONDAY, office_appstream="11280", office_key="raf",
                           live=True, preview=True, log=lambda *a: None)
    row = [p for p in res["people"] if p["name"] == "Kimble Townsend"][0]
    assert row["from"] == "unknown", "the guesser will not call Kimble"
    assert row["gender"] == ""


def test_the_real_guesser_will_not_call_kimble():
    """The fixture above stands in for this; this is the fact behind it."""
    from automations.icd_onboarding import gender_suggest as GS
    assert GS.suggest("Kimble") == ""
    assert GS.suggest("Luis") == "Male"


def test_the_job_passes_both_through(monkeypatch):
    """A gender answer cannot add or remove anybody -- who is in the week is
    still read off the office's own calendar."""
    import inspect
    from automations.icd_alerts import office_jobs as OJ
    body = inspect.getsource(OJ.work)
    assert 'payload.get("genders")' in body
    assert 'payload.get("preview")' in body
    assert 'payload.get("people")' not in body.split("apex_week")[-1][:800]
