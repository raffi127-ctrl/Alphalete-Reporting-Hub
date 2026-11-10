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

def test_signin_never_waits_on_the_standing_prompt():
    """Apex lands EVERY signed-in session on change-password and the prompt
    never needs actioning (Megan, 2026-11-10: "apex ALWAYS goes to reset pw --
    you have to use the NAV on the left"). Waiting on it waits for ever."""
    body = inspect.getsource(SUP.signin).split('"""', 2)[-1]
    assert "password_gate" not in body
    assert "raise" not in body


def test_signin_never_asks_for_a_new_password():
    """An earlier version told her to set one there. It is not a wall."""
    src = inspect.getsource(SUP.signin)
    assert "IGNORE THAT" in src
    # The CODE: the docstring names the old wrong advice to explain itself.
    body = src.split('"""', 2)[-1]
    assert "set the new" not in body and "new password" not in body


def test_signin_types_no_password():
    src = inspect.getsource(SUP.signin)
    assert "no password is read" in src
    body = src.split('"""', 2)[-1]
    for bad in ("fill(", "type(", "password=", "creds"):
        assert bad not in body, bad


def test_being_logged_out_names_the_next_command():
    src = inspect.getsource(SUP.main)
    assert "NotLoggedIn" in src and "--signin" in src


def test_the_standing_prompt_is_not_caught_as_a_failure():
    """It is where a good session lives, not an error."""
    src = inspect.getsource(SUP.main)
    assert "PasswordChangeRequired" not in src


def test_the_operator_is_told_to_use_the_nav_not_a_url():
    """A URL typed from the change-password page redirects straight back to
    it, so "go to /roster" is advice that cannot work."""
    src = inspect.getsource(SUP.wait_for_form)
    assert "LEFT-HAND NAV" in src and "redirects" in src


def test_signin_needs_no_person(monkeypatch):
    called = []
    monkeypatch.setattr(SUP, "signin", lambda: called.append(True) or 0)
    assert SUP.main(["--signin"]) == 0
    assert called


def test_a_fill_still_needs_a_person(capsys):
    import pytest
    with pytest.raises(SystemExit):
        SUP.main(["--office", "raf"])


# ------------- the standing change-password page is a good session, not a wall

class _FakePage:
    def __init__(self, url):
        self.url = url

    def wait_for_timeout(self, _ms):
        pass


def _sess(url):
    from automations.apex_new_starts import apex as AX
    s = AX.ApexSession.__new__(AX.ApexSession)
    s.page = _FakePage(url)
    s.log = lambda *a: None
    return s


def test_the_change_password_page_counts_as_signed_in():
    """Megan, 2026-11-10: "apex ALWAYS goes to reset pw -- you have to use the
    NAV on the left." Calling it logged-out made `check_apex` print "❌ Apex"
    on a perfectly good login."""
    for url in ("https://apex.herbjoyent.com/Identity/Account/ChangePassword",
                "https://apex.herbjoyent.com/Account/ChangePassword"):
        assert _sess(url).signed_in() is True, url


def test_it_is_still_recognised_as_the_prompt():
    """It has to be asked about: a URL load from it redirects back, so
    navigation has to be in-app."""
    s = _sess("https://apex.herbjoyent.com/Identity/Account/ChangePassword")
    assert s.password_gate() is True


def test_the_real_sign_in_screens_are_still_not_signed_in():
    """Both prefixes -- a check written for /Identity only once waved a
    half-finished 2FA straight through."""
    for url in ("https://apex.herbjoyent.com/Identity/Account/Login",
                "https://apex.herbjoyent.com/Account/SendCode?ReturnUrl=/roster",
                "https://apex.herbjoyent.com/Identity/Account/VerifyCode"):
        assert _sess(url).signed_in() is False, url
        assert _sess(url).password_gate() is False, url


def test_the_prompt_is_not_announced_as_a_step_still_to_come():
    """It is where a finished sign-in lands, so listing it as a step had the
    wait loop reporting progress backwards."""
    s = _sess("https://apex.herbjoyent.com/Identity/Account/ChangePassword")
    assert s.on_signin_step() == ""


def test_nothing_raises_on_the_prompt_any_more():
    from automations.apex_new_starts import apex as AX
    src = inspect.getsource(AX.ApexSession.require_login)
    assert "PasswordChangeRequired" not in src


def test_the_old_exception_still_imports():
    """run.py and other callers still name it in an except clause."""
    from automations.apex_new_starts import apex as AX
    assert issubclass(AX.PasswordChangeRequired, RuntimeError)


# ------------------------- the filled form outlives the run either way

def test_no_keyboard_does_not_close_the_filled_form():
    """`input()` raises EOFError the instant stdin is not a tty, which used to
    close the browser as soon as the fill finished -- nobody would ever have
    got to press Save."""
    src = inspect.getsource(SUP._hold_open)
    assert "isatty" in src
    assert "EOFError" in src
    assert "wait_for_timeout" in src, "it has to actually wait, not return"


def test_the_run_ends_by_holding_the_window_open():
    src = inspect.getsource(SUP.run)
    assert "_hold_open" in src
    assert "input(" not in src, "the wait belongs in _hold_open, both paths"


def test_a_closed_window_ends_the_wait():
    """Closing it IS the person saying they are done."""
    src = inspect.getsource(SUP._hold_open)
    assert "Window closed" in src
