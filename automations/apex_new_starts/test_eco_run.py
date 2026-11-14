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
    monkeypatch.setattr(eco_run, "_genders_from_board",
                        lambda office_key, monday, log=print: {})

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
    monkeypatch.setattr(eco_run, "_genders_from_board",
                        lambda office_key, monday, log=print: dict(genders))


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

def test_a_live_run_refuses_until_somebody_has_watched_one_save(monkeypatch):
    """Nothing in this repo has ever saved an Apex record unwatched. The gate
    is not a formality -- a half-right save lands on a real person's payroll
    record and there is no undo."""
    monkeypatch.delenv("APEX_FILL_PROVEN", raising=False)
    _patch(monkeypatch, rows=_rows("Ada Fournier"),
           hires={"Ada Fournier": _hire("Ada Fournier", ssn=True)})
    touched = []
    monkeypatch.setattr(eco_run, "fill_week",
                        lambda *a, **k: touched.append(a) or {"added": [], "blocked": []})
    res = eco_run.run_week(MONDAY, office_appstream="11280", office_key="raf",
                           live=True, log=lambda *a: None)
    assert res["status"] == "error"
    assert "never been watched" in res["error"]
    assert touched == [], "Apex must not be opened at all"
    assert res["added"] == []


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
    from automations.apex_new_starts import values as V
    monkeypatch.setattr(V, "apex_values",
                        lambda c, hire, office_key="": {
                            "dob": "10/25/2002", "address1": "x",
                            "city": "Dallas", "zip": "75262",
                            "rate": "12.00", "gender": "Female"})
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


def test_the_gender_board_is_read_once_not_twice():
    """It was read a second time further down, after the gate, for the engine
    path -- the same Sheets call for the same answer."""
    import inspect
    src = inspect.getsource(eco_run.run_week)
    assert src.count("_genders_from_board(") == 1, src.count("_genders_from_board(")
