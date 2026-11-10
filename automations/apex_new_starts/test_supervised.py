"""The supervised Apex rehearsal — what it must never do."""
from __future__ import annotations

import datetime as dt
import inspect

from automations.apex_new_starts import eco_run as ECO
from automations.apex_new_starts import supervised as SUP

SUNDAY = dt.date(2026, 11, 8)


# ------------------------------------------------- it never presses Save

def test_nothing_here_can_save():
    """The whole value of this run is that a person saw the record before it
    existed, so a flag to skip that would make it pointless."""
    src = inspect.getsource(SUP)
    assert "save=False" in src
    assert "save=True" not in src
    assert "APEX_FILL_PROVEN" not in src, "this run must not set the gate"


def test_it_does_not_click_the_save_button():
    src = inspect.getsource(SUP)
    for bad in ("saveButton", "saveHere", '"save"', "'save'"):
        assert bad not in src, bad


# ------------------------------------------------------- no Social, ever

def test_no_social_is_fetched():
    """keep_ssn off means there is nothing that could reach a log or a sheet."""
    src = inspect.getsource(SUP.run)
    assert "keep_ssn=False" in src
    assert "keep_ssn=True" not in src


def test_it_never_asks_for_a_social():
    src = inspect.getsource(SUP)
    assert "ssn_prompt" not in src and "Secret" not in src


# ------------------------------- the duplicate check stays with the operator

def test_it_does_not_navigate_to_the_form_itself():
    """Clicking our own way to Add Employee would walk past the All Employees
    check and teach the operator it was handled."""
    src = inspect.getsource(SUP)
    assert "Add Employee" in src          # it is asked for, in words
    assert ".click()" not in src          # and never pressed


def test_the_operator_is_told_what_a_duplicate_costs():
    """"Check first" without the reason gets skipped on a busy morning."""
    said = inspect.getsource(SUP.wait_for_form)
    assert "second" in said and "payroll record" in said


# ------------------------------------- it watches for the form it will fill

def test_the_readiness_check_is_the_field_it_fills():
    """A separate selector here could drift from what gets typed."""
    assert ECO.BY_MODEL["first"] in SUP.FORM_READY


# ------------------------------------------ the week is the board's week

def test_the_week_is_normalised_to_the_boards_sunday():
    from automations.icd_onboarding import board as B
    src = inspect.getsource(SUP.main)
    assert "week_start_of" in src
    assert B.week_start_of(dt.date(2026, 11, 10)) == SUNDAY


# ------------------------------------------- a name that is not on the board

def _board(monkeypatch, rows):
    from automations.icd_onboarding import board as B
    from automations.icd_onboarding import fillers as F
    from automations.icd_onboarding import sheet as S

    class _WS:
        def get_all_values(self):
            return []
    monkeypatch.setattr(F, "workbook_for", lambda k: "BOOK")
    monkeypatch.setattr(S, "open_board", lambda book, create=False: _WS())
    monkeypatch.setattr(S, "rows_of", lambda grid: rows)
    monkeypatch.setattr(B, "for_week", lambda rows, week: rows)


def test_a_name_that_is_not_on_the_week_is_refused(monkeypatch):
    _board(monkeypatch, [{"Name": "Ada", "Last Name": "F", "Email": "",
                          "Phone": "", "Start": ""}])
    said = []
    assert SUP._board_person("raf", "Bruno Castell", SUNDAY,
                             log=said.append) is None
    assert any("Ada F" in s for s in said), "it should say who IS on the week"


def test_the_person_is_found_however_the_name_is_spaced(monkeypatch):
    _board(monkeypatch, [{"Name": "Ada", "Last Name": "F",
                          "Email": "ada@example.com", "Phone": "555",
                          "Start": "11/09/2026"}])
    got = SUP._board_person("raf", "  ada   f ", SUNDAY, log=lambda *a: None)
    assert got is not None
    assert got.name == "Ada F"
    assert got.hire_date == dt.date(2026, 11, 9)
    assert got.email == "ada@example.com"


def test_an_unreadable_start_date_falls_back_to_the_week(monkeypatch):
    """A blank Start must not crash the rehearsal, and must not invent a date
    from somewhere else."""
    _board(monkeypatch, [{"Name": "Ada", "Last Name": "F", "Email": "",
                          "Phone": "", "Start": ""}])
    got = SUP._board_person("raf", "Ada F", SUNDAY, log=lambda *a: None)
    assert got.hire_date == SUNDAY


# --------------------------------------------- what it prints before opening

def test_the_plan_is_printed_before_the_browser_opens():
    """So a wrong date of birth is caught without a half-filled form on
    screen."""
    src = inspect.getsource(SUP.run)
    assert src.index("_describe(values)") < src.index("ApexSession")


def test_the_password_box_is_called_out():
    """It DEFAULTS TO TICKED and saving with it on emails a brand new rep."""
    src = inspect.getsource(SUP.run)
    assert "password-reset" in src and "TICKED" in src


# ------------------------- the password-change screen is clearable, not fatal

def test_signin_does_not_treat_the_password_gate_as_the_end():
    """ApexSession.require_login raises on it and closes the window the person
    could have cleared it in -- which is what happened on 2026-11-10: a fresh
    sign-in went password -> 2FA -> change-password and the run exited with
    that screen in front of her."""
    src = inspect.getsource(SUP.signin)
    assert "password_gate" in src
    # The CODE, not the docstring -- which names require_login to explain why.
    body = src.split('"""', 2)[-1]
    assert "raise" not in body
    assert "require_login" not in body


def test_signin_says_to_change_it_in_lucys_window():
    """Clearing the gate in her own browser leaves THIS profile just as stale
    and the next run back on the same message."""
    src = inspect.getsource(SUP.signin)
    assert "this window" in src


def test_signin_types_no_password():
    src = inspect.getsource(SUP.signin)
    assert "no password is read" in src
    body = src.split('"""', 2)[-1]
    for bad in ("fill(", "type(", "password=", "creds"):
        assert bad not in body, bad


def test_the_gate_error_names_the_next_command():
    """A diagnosis on its own sends you to your own browser."""
    src = inspect.getsource(SUP.main)
    assert "PasswordChangeRequired" in src and "--signin" in src


def test_signin_needs_no_person(monkeypatch):
    called = []
    monkeypatch.setattr(SUP, "signin", lambda: called.append(True) or 0)
    assert SUP.main(["--signin"]) == 0
    assert called


def test_a_fill_still_needs_a_person(capsys):
    import pytest
    with pytest.raises(SystemExit):
        SUP.main(["--office", "raf"])
