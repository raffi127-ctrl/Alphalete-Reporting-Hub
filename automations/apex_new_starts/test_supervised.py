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

def test_the_social_is_fetched_and_never_echoed():
    """It used to be withheld, which was right while this run only reached the
    employment tab. Apex will not save the TAX tab without a Social, so the
    rehearsal could not finish the thing it exists to rehearse (Megan,
    2026-11-13: "I can't save it without a social").

    Fetching it changes nothing about custody -- see test_ssn_custody for the
    unwrap-site and never-logged rules."""
    src = inspect.getsource(SUP.run)
    assert "keep_ssn=True" in src
    assert "keep_ssn=False" not in src


def test_nobody_is_ever_ASKED_to_type_a_social():
    """This guarantee survives the change above. It comes off the signed
    packet, never from a person at a keyboard: an operator typing twenty-two
    Socials is the thing this whole report exists to stop."""
    # THE CALLS, read off the syntax tree. Comments and docstrings here
    # explain the custody rules and the old keyboard wait, and naturally use
    # these words -- an explanation of a thing is not the thing. Slicing
    # strings got that wrong; the tree cannot.
    import ast
    import pathlib
    tree = ast.parse(pathlib.Path(SUP.__file__).read_text(encoding="utf-8"))
    called = set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        called.add(f.id if isinstance(f, ast.Name)
                   else f.attr if isinstance(f, ast.Attribute) else "")
    assert not any("ssn" in c.lower() and "prompt" in c.lower() for c in called), \
        "nothing here prompts for one"
    # The ONE input() in this module holds the window open at the end --
    # "press Return when you are done". Banning input() outright would ban
    # that, which is not what this rule is about: no VALUE is ever typed in
    # at a prompt, least of all a Social.
    prompts = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "input"]
    assert len(prompts) == 1, "only the window-hold may wait on a keyboard"
    asked = prompts[0].args[0].value if prompts[0].args else ""
    assert "Return" in asked and "social" not in asked.lower(), asked
    # and the module does not even import the prompt
    imported = {a.name for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) for a in n.names}
    imported |= {a.name for n in ast.walk(tree)
                 if isinstance(n, ast.Import) for a in n.names}
    assert not any("ssn_prompt" in i for i in imported), imported


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
    from automations.icd_onboarding import sheet as S

    class _WS:
        def get_all_values(self):
            return []
    # `board_for`, because that is the one way the code reaches a board now:
    # patching `open_board` still passed while the real `board_for` ran and
    # answered None, which is how this read an empty board for an office with
    # a book of their own (2026-11-24).
    monkeypatch.setattr(S, "board_for",
                        lambda key, week=None, create=False: _WS())
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
                "https://apex.herbjoyent.com/Account/ChangePassword",
                # THE LIVE ONE, 2026-11-10 (screenshot from Megan, signed in as
                # Rafael Hidalgo with the left nav on screen). A pattern written
                # without the "Manage" segment read it as the login page.
                "https://apex.herbjoyent.com/Identity/Account/Manage/ChangePassword",
                "https://apex.herbjoyent.com/Account/Manage/ChangePassword"):
        assert _sess(url).signed_in() is True, url


def test_it_is_still_recognised_as_the_prompt():
    """It has to be asked about: a URL load from it redirects back, so
    navigation has to be in-app."""
    for url in ("https://apex.herbjoyent.com/Identity/Account/ChangePassword",
                "https://apex.herbjoyent.com/Identity/Account/Manage/ChangePassword"):
        assert _sess(url).password_gate() is True, url


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
    for url in ("https://apex.herbjoyent.com/Identity/Account/ChangePassword",
                "https://apex.herbjoyent.com/Identity/Account/Manage/ChangePassword"):
        assert _sess(url).on_signin_step() == "", url


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


def test_the_run_follows_the_sign_in_into_another_tab():
    """__enter__ keeps pages[0], and Apex's sign-in can finish in a tab of its
    own -- the old page then sits on the login URL for ever while the real
    session is one tab away."""
    from automations.apex_new_starts import apex as AX
    src = inspect.getsource(AX.ApexSession._adopt_signed_in_page)
    assert "ctx.pages" in src
    assert "self.page = page" in src
    assert "_adopt_signed_in_page" in inspect.getsource(AX.ApexSession.require_login)


# --------------------------- the sign-in survives the browser closing

def test_the_sign_in_is_saved_outside_the_repo():
    """A `git pull` replaces the repo copy, and the ICD app may be installed
    where the user cannot write."""
    from automations.apex_new_starts import apex as AX
    assert ".config" in str(AX.STATE_PATH) and "lucy-reports" in str(AX.STATE_PATH)
    repo = str(__import__("pathlib").Path(AX.__file__).resolve().parents[2])
    assert not str(AX.STATE_PATH).startswith(repo)


def test_a_logged_out_session_never_overwrites_a_good_one():
    """Saving on the way out of a failed run would throw away the sign-in the
    previous run earned."""
    from automations.apex_new_starts import apex as AX
    src = inspect.getsource(AX.ApexSession._save_state)
    assert "if not self.signed_in():" in src
    assert "return" in src


def test_the_saved_sign_in_is_owner_only():
    from automations.apex_new_starts import apex as AX
    assert "chmod(0o600)" in inspect.getsource(AX.ApexSession._save_state)


def test_it_is_restored_before_the_first_page_load():
    """Restored after the goto, the first page would still be the login one."""
    from automations.apex_new_starts import apex as AX
    src = inspect.getsource(AX.ApexSession.__enter__)
    assert "_restore_state" in src
    assert src.index("_restore_state") < src.index("goto(ROSTER_URL")


def test_a_broken_state_file_is_not_fatal():
    """No state yet is the normal first run."""
    from automations.apex_new_starts import apex as AX
    src = inspect.getsource(AX.ApexSession._restore_state)
    assert "except Exception" in src and "return" in src


def test_saving_never_fails_the_run():
    from automations.apex_new_starts import apex as AX
    src = inspect.getsource(AX.ApexSession.__exit__)
    assert "_save_state" in src
    assert "except Exception" in src


# ------------------------------------------- the path that actually runs often

def test_it_rehearses_the_COMPLETE_path_not_only_the_create():
    """Megan, 2026-11-11, after both checks landed on somebody already on
    Pending: an ICD's people arrive there by themselves once they are in
    OwnerVille, so completing runs twenty-odd times a week and creating is
    rare. Rehearsing only the create was rehearsing the wrong thing."""
    import inspect
    from automations.apex_new_starts import supervised as SUP
    src = inspect.getsource(SUP.run)
    assert "drive.triage" in src, "it has to ask which one they need"
    assert "drive.COMPLETE" in src and "drive.ADD" in src


def test_the_complete_rehearsal_never_calls_runPerson():
    """runPerson saves each of the three tabs as it goes. That is the whole
    point of it -- and exactly what must not happen while somebody is still
    deciding whether to trust the thing."""
    import inspect
    from automations.apex_new_starts import drive
    from automations.apex_new_starts import supervised as SUP
    # The tab walk moved into drive.complete_person so the rehearsal and the
    # unattended week run the SAME code -- so the rule has to be checked
    # where that code is, not only here.
    for fn in (SUP._complete, drive.complete_person, drive.fill_employment,
               drive.fill_profile, drive.fill_tax):
        src = inspect.getsource(fn)
        assert "__ansRunPerson" not in src, "%s must not save" % fn.__name__
    # and the rehearsal's own pause is what stands between a filled tab and a
    # saved one: it hands complete_person a callback that waits for a person.
    # The callback WAITS for a save, it does not press one. Apex will not
    # let a filled tab be left unsaved, so the walk has to pause there --
    # and it pauses on the save itself, which it watches for, not on a
    # keypress in a terminal Megan could not find.
    src = inspect.getsource(SUP._complete)
    assert "drive.wait_for_save(" in src, "it waits for the save"
    assert "input()" not in src, "nothing waits on a keyboard"
    assert ".click(" not in src, "nothing here may press Save"
    assert "_hold_open(page, log=log)" in src, "the window stays open to read"


def test_neither_path_safe_means_nothing_is_typed():
    """In Apex but not on Pending: creating duplicates a real payroll record,
    completing has nowhere to start."""
    import inspect
    from automations.apex_new_starts import supervised as SUP
    src = inspect.getsource(SUP.run)
    assert "SECOND" in src and "Nothing was typed" in src


def test_both_paths_share_one_field_map():
    """A second values-to-page mapping is how two callers come to disagree
    about which Apex box a value belongs in."""
    import inspect
    from automations.apex_new_starts import supervised as SUP
    assert "rows_for" in inspect.getsource(SUP._pages)


def test_run_reaches_the_triage_without_a_NameError(monkeypatch):
    """The source-text tests above all passed while `run` had no `drive` in
    scope at all -- it crashed on the live run, after signing in, at the first
    line that used it (2026-11-11). Reading the source is not running it."""
    from automations.apex_new_starts import supervised as SUP

    class _Page:
        url = "https://apex.example/roster"  # already there: to_roster returns at once
        def evaluate(self, *a, **k):
            return True
        def wait_for_timeout(self, *a, **k):
            pass

    class _S:
        page = _Page()
        def require_login(self):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    import automations.apex_new_starts.apex as AX
    monkeypatch.setattr(AX, "ApexSession", lambda *a, **k: _S())

    person = SUP.ECO.Starter(name="Ada Fournier", email="a@b.c",
                             hire_date=dt.date(2026, 11, 8))
    monkeypatch.setattr(SUP, "_board_person",
                        lambda office, name, week, log=print: person)
    monkeypatch.setattr(SUP.BID, "for_people", lambda *a, **k: {})
    monkeypatch.setattr(SUP.ECO, "plan",
                        lambda people, hires, log=print, office_key="",
                        watched=False:
                        {"ready": [(person, {"first": "Ada"})], "blocked": []})
    reached = {}
    def _load(page, people, week, log=print):
        reached["loaded"] = True
        return list(drive.ENTRY_POINTS)

    def _triage(page, people, log=print):
        reached["triaged"] = True
        return {"Ada Fournier": {"need": drive.BY_HAND, "why": "test"}}

    from automations.apex_new_starts import drive
    monkeypatch.setattr(SUP.drive, "load", _load)
    monkeypatch.setattr(SUP.drive, "triage", _triage)
    monkeypatch.setattr(SUP.drive, "to_roster", lambda page, log=print: True)
    monkeypatch.setattr(SUP.drive, "keep_loaded",
                        lambda page, people=None, week="", log=print: True)

    rc = SUP.run("raf", "Ada Fournier", dt.date(2026, 11, 8), log=lambda *a: None)
    assert reached.get("loaded"), "run never reached drive.load"
    assert isinstance(rc, int)


def test_the_complete_rehearsal_opens_the_record_before_filling_it():
    """doPage fills whatever page is showing. On the roster that is nothing,
    which is exactly what the first run did (2026-11-11)."""
    import inspect
    from automations.apex_new_starts import drive
    src = inspect.getsource(drive.complete_person)
    assert src.index("go_tab(") < src.index("fill_employment("), \
        "move first, then fill"
    # and the move waits for a box that tab actually owns -- the loading
    # message clears before the fields exist, which is the trap that cost a
    # day on the employment tab.
    assert src.index("wait_for_field") < src.index("fill_employment(")
    assert "edit/%s" in inspect.getsource(drive.go_tab)
    assert dict((t[0], t[1]) for t in drive.TABS)["employment record"] \
        == "employment-record"


def test_the_summary_names_only_the_tabs_it_filled():
    """It printed "ALL THREE TABS ARE FILLED" and listed all three after
    reaching only the first (2026-11-12). Somebody about to press Save reads
    that line, and a tab it never opened is not a tab to go and save."""
    import inspect
    from automations.apex_new_starts import supervised as SUP
    src = inspect.getsource(SUP._complete)
    # THE LINES IT PRINTS, not the comments explaining why. A comment that
    # records the bug is not the bug.
    code = "\n".join(l for l in src.splitlines()
                      if not l.strip().startswith("#"))
    assert "ALL THREE TABS" not in code, "it cannot claim three tabs"
    assert "NOT reached" in code, "and say what it did not reach"
    assert "Stopped before" in code, "and that it stopped early"
    # FILLED IS NOT SAVED: a tab it filled and nobody saved says so, rather
    # than being counted as done (2026-11-13).
    assert 'got.get("saved")' in code, "it has to read what actually saved"
    assert "FILLED BUT NOT SAVED" in code


def test_a_wrong_value_stops_the_run_instead_of_asking_for_a_save():
    """It printed "WRONG -- DO NOT SAVE" and then, four lines later, "Press
    SAVE on this tab". Kyle's Rate of Pay went in at $10.10 because the
    second line is the one that reads like an instruction (2026-11-13).

    Two contradictory messages are worse than one wrong one."""
    from automations.apex_new_starts import supervised as SUP
    src = inspect.getsource(SUP._complete)
    # THE CODE, not the comment that explains it. The note above this very
    # check quotes both messages, and a comment saying what went wrong is not
    # the thing going wrong (fourth time this has caught me out today).
    stop = "\n".join(l for l in src.split("def saved(", 1)[1].splitlines()
                      if not l.strip().startswith("#"))
    assert stop.index("DO NOT SAVE THIS TAB") < stop.index("Press SAVE"), \
        "it must refuse before it ever asks"
    head = stop[:stop.index("Press SAVE")]
    assert "return False" in head, "and stop, not carry on to the ask"


def test_the_armed_save_still_refuses_a_tab_that_is_wrong():
    """Megan, 2026-11-15: "arm the automatic save". Pressing Save does not
    lower the bar -- save_tab refuses on its own when a required box is
    empty, a value is not what was asked for, or Apex objects, so the code
    presses Save only on a tab that is already right."""
    import inspect
    from automations.apex_new_starts import supervised as SUP
    src = inspect.getsource(SUP._complete)
    assert "drive.save_tab(page, apex_id, got, log=log)" in src
    # and it is OFF unless asked for
    sig = inspect.signature(SUP._complete).parameters
    assert sig["press_save"].default is False
    assert inspect.signature(SUP.run).parameters["press_save"].default is False


def test_the_run_says_which_mode_it_is_in():
    """Somebody watching a run that presses Save itself needs to know that is
    what they are watching."""
    import inspect
    from automations.apex_new_starts import supervised as SUP
    src = inspect.getsource(SUP._complete)
    assert "THIS RUN PRESSES SAVE ITSELF." in src


# ------------------------------- a namesake is not a duplicate payroll record

# Luis Frias, 2026-11-24: a first-name search for "Luis" returned 30 rows, the
# fallback accepted them, and the run reported "in Apex but not on Pending" --
# refusing a create Megan had asked for by name. The fallback is for a
# MISTYPED surname (McCrob for McCrobie), never for a different person.

def test_a_truncated_surname_still_matches():
    from automations.apex_new_starts.drive import _close_surname
    assert _close_surname("McCrobie", "mccrob")
    assert _close_surname("McCrob", "mccrobie")


def test_a_different_surname_does_not():
    from automations.apex_new_starts.drive import _close_surname
    assert not _close_surname("Frias", "rodriguez")
    assert not _close_surname("Frias", "ramirez")


def test_a_short_near_miss_does_not():
    """Three letters is too few to call two surnames the same person."""
    from automations.apex_new_starts.drive import _close_surname
    assert not _close_surname("Lee", "li")
    assert not _close_surname("Ngo", "ng")


def test_the_fallback_reads_the_names_not_just_a_count():
    """A count cannot tell a namesake from a typo."""
    from automations.apex_new_starts import drive
    body = inspect.getsource(drive.triage)
    assert "roster_surnames" in body
    assert "_close_surname" in body


# --------------------------- the fill may not start on a half-loaded page

# 2026-11-24: the first control was on the page, jQuery was not, and the fill
# threw "$ is not a function" at Hire Date -- after the text boxes had already
# taken their values.

def test_drivable_wants_jquery():
    """jQuery only: Kendo is reached through its `.data()` here and is not a
    dependable global, and requiring it turned a crash into a silent wait."""
    body = inspect.getsource(SUP._drivable)
    assert "window.jQuery" in body
    assert "window.kendo &&" not in body


def test_drivable_is_false_when_the_page_cannot_be_asked():
    class Dead:
        def evaluate(self, *a, **k):
            raise RuntimeError("navigating")

    assert SUP._drivable(Dead()) is False


def test_the_wait_reports_jquery_but_does_not_block_on_it():
    """The live form has neither global, so blocking meant never filling
    (Megan, 2026-11-24: "nothing is filling"). It warns instead."""
    body = inspect.getsource(SUP.wait_for_form)
    assert "_drivable" in body
    assert "count() > 0 and _drivable" not in body


def test_the_fill_no_longer_reaches_for_jquery_at_all():
    """It did, and `window.jQuery` is undefined on the create form, so the
    whole fill died part-done at Hire Date. The dropdowns are clicked from
    Python now and nothing in the JS wants a library."""
    import re
    js = re.sub(r"/\*.*?\*/", "", ECO.FILL_JS, flags=re.S)
    assert "jQuery" not in js
    assert "$(" not in js


# ------------------------- somebody the board never got is still addable

# Megan, 2026-11-24: "Frias isn't in payroll at all so he's one that would
# need added" -- and he was on no week of the board, so the run opened nothing.

def _bundles(monkeypatch, bundles):
    monkeypatch.setattr(SUP.BID, "search_bundles", lambda *a, **k: bundles)


def test_it_refuses_an_unsigned_packet(monkeypatch):
    said = []
    _bundles(monkeypatch, [{"id": "x", "status": "se",
                            "packets": [{"name": "Luis Frias",
                                         "email": "a@b.c"}]}])
    got = SUP._packet_person("Luis Frias", dt.date(2026, 11, 22),
                             log=said.append)
    assert got is None
    assert any("not signed" in s for s in said)


def test_a_signed_packet_becomes_a_starter(monkeypatch):
    _bundles(monkeypatch, [{"id": "ZUNqcm1C4i", "status": "co",
                            "created": "2026-11-23T15:40:17Z",
                            "packets": [{"name": "Luis Frias",
                                         "email": "luismanuel8089@gmail.com"}]}])
    got = SUP._packet_person("Luis Frias", dt.date(2026, 11, 22),
                             start=dt.date(2026, 11, 23), log=lambda *a: None)
    assert got is not None
    assert got.name == "Luis Frias"
    assert got.hire_date == dt.date(2026, 11, 23)
    assert got.source == "blue ink packet"


def test_a_stranger_with_the_same_surname_is_not_them(monkeypatch):
    _bundles(monkeypatch, [{"id": "y", "status": "co",
                            "packets": [{"name": "Maria Frias",
                                         "email": "m@b.c"}]}])
    got = SUP._packet_person("Luis Frias", dt.date(2026, 11, 22),
                             log=lambda *a: None)
    assert got is None


def test_the_board_is_still_tried_first():
    """The packet is a fallback, not a replacement: a board row carries a real
    start date and a packet does not."""
    body = inspect.getsource(SUP.run)
    assert body.index("_board_person") < body.index("_packet_person")


# ------------------- it opens the create form instead of waiting on a person

# Megan, 2026-11-24: "why wait 10 min?" -- the wait predated `triage` doing
# the All Employees duplicate check itself, so it was asking her to redo a
# check the run had already run and reported.

def test_the_add_path_presses_the_button_itself():
    body = inspect.getsource(SUP.run)
    assert "press_add_employee" in body
    assert body.index("press_add_employee") < body.index("wait_for_form")


def test_the_wait_is_still_there_as_the_fallback():
    """A roster this cannot press must still be openable by hand."""
    body = inspect.getsource(SUP.run)
    assert "wait_for_form" in body


def test_pressing_add_is_only_reached_after_the_roster_came_back_empty():
    """It must never be pressed on somebody the roster found: that is a second
    payroll record for a real employee."""
    body = inspect.getsource(SUP.run)
    head = body[:body.index("press_add_employee")]
    assert 'need.get("need") != drive.ADD' in head


def test_the_button_is_marked_then_clicked_not_text_matched():
    """`:text-is()` does not click Apex's Angular buttons -- the same reason
    Apply Filters and the roster tabs are marked first."""
    from automations.apex_new_starts import drive
    body = inspect.getsource(drive.press_add_employee)
    assert "data-ans-add" in body
    assert "page.click" in body


def test_it_returns_false_rather_than_raising_on_a_page_it_cannot_read():
    from automations.apex_new_starts import drive

    class Dead:
        def evaluate(self, *a, **k):
            raise RuntimeError("navigating")

    said = []
    assert drive.press_add_employee(Dead(), log=said.append) is False
    assert said


def test_the_dropdowns_are_clicked_from_python():
    """Kendo paints a span over a display:none <select> and Angular holds the
    model. Neither is addressable on a page with no globals, so writing the
    value left the box reading "Select" (Megan, 2026-11-24: "this isn't
    filled"). Only a real click runs Kendo's handler."""
    body = inspect.getsource(ECO.fill_one)
    assert "pick_dropdown" in body
    assert "drops={}" in body, "the JS must not try the dropdowns itself"


def test_a_dropdown_counts_only_when_the_box_reads_it_back():
    """A click that opened nothing must not pass for a choice."""
    from automations.apex_new_starts import drive
    body = inspect.getsource(drive.pick_dropdown)
    assert "k-input" in body
    assert "clicked %r but the box reads" in body
