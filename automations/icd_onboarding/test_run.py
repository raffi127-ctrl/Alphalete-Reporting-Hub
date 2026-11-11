"""The runner: one office, every step, nothing stopping on one failure.

The rules here are about a run that is PARTLY able to work. A morning where
OwnerVille is down should still tick Blue Ink, and a source that could not be
read must leave its column alone rather than reporting everyone as behind.
"""
from __future__ import annotations

import datetime as dt

from automations.icd_onboarding import run as R

MONDAY = dt.date(2026, 11, 2)


def test_one_source_failing_does_not_stop_the_others(monkeypatch):
    ran = []

    def ok(name):
        def fn(office, week, *, dry_run=True, log=print):
            ran.append(name)
            return 1
        return fn

    def boom(office, week, *, dry_run=True, log=print):
        raise RuntimeError("OwnerVille is having a morning")

    monkeypatch.setattr(R, "STEPS", (("seed", ok("seed")),
                                     ("ownerville", boom),
                                     ("blueink", ok("blueink"))))
    got = R.for_office("raf", MONDAY, log=lambda *a: None)
    assert ran == ["seed", "blueink"], "the rest still ran"
    assert got["seed"] == 1 and got["blueink"] == 1
    assert "RuntimeError" in got["ownerville"], "and the failure is reported"


def test_an_office_with_no_ov_programme_is_skipped_not_guessed(monkeypatch):
    """A guess reads an empty table, which looks exactly like nobody having
    done anything."""
    said = []
    monkeypatch.setattr(R, "_ov_program", lambda k: "")
    n = R.from_ownerville("omar", MONDAY, log=said.append)
    assert n == 0
    assert any("rather than guessing" in s for s in said)


def test_an_office_with_no_appstream_id_does_not_seed(monkeypatch):
    said = []
    monkeypatch.setattr(R, "_appstream_id", lambda k: "")
    assert R.seed("nowhere", MONDAY, log=said.append) == 0
    assert any("no ApplicantStream id" in s for s in said)


def test_a_dry_run_is_the_default():
    import inspect
    for name, fn in R.STEPS:
        assert inspect.signature(fn).parameters["dry_run"].default is True, name
    assert inspect.signature(R.for_office).parameters["dry_run"].default is True


def test_only_runs_just_the_named_steps(monkeypatch):
    ran = []

    def mk(name):
        def fn(office, week, *, dry_run=True, log=print):
            ran.append(name)
            return 0
        return fn

    monkeypatch.setattr(R, "STEPS", (("seed", mk("seed")), ("blueink", mk("blueink"))))
    R.for_office("raf", MONDAY, only=["blueink"], log=lambda *a: None)
    assert ran == ["blueink"]


def test_apex_is_not_run_here_because_it_ticks_as_it_acts():
    """The Apex run knows at the moment it saves a record, so running it from
    here would be asking it to redo work it already recorded."""
    names = [n for n, _ in R.STEPS]
    assert "apex" not in names
    from automations.icd_onboarding import fillers as F
    assert set(F.SOURCES) - set(names) == {"apex"}


def test_contacts_is_a_LOOKUP_even_though_the_sync_could_tick_as_it_adds():
    """An as-it-happens tick cannot backfill, and that is most of this column.

    Somebody contacted at their second round three weeks ago is never re-added,
    so a tick that only fires on creation leaves them blank for ever -- while
    on the real OBCL Contact Added is true for nearly everybody. Reading the
    sync's own record answers for them too (Megan, 2026-11-09: "connect to
    Eve's already built automation").
    """
    import inspect
    names = [n for n, _ in R.STEPS]
    assert "contacts" in names
    src = inspect.getsource(R.from_contacts)
    # THE ACCOUNT ITSELF, not the sync's notes about what it did. The state
    # file read 98 contacts and matched 0 of Raf's 21 (2026-11-08), and could
    # not say whether the sync had run or had been about other offices.
    assert "existing_index" in src, "it has to ask the account"
    assert "STATE_PATH" not in src, "the state file is what it believes, not what is"


def test_no_token_for_the_account_ticks_nothing_rather_than_claiming_nobody():
    """It runs where that account's token is. Anywhere else it is unread --
    never 'nobody has been contacted'."""
    import inspect
    src = inspect.getsource(R.from_contacts)
    assert "has_token" in src and "return 0" in src
    # and a read that THROWS is unread too, not an empty account
    assert "could not read" in src


# ----------------------------------- closing the incomplete OwnerVille read

def test_the_search_is_only_asked_about_this_weeks_people():
    """The page gives one page of a hundred-odd; searching the whole roster
    one at a time would never finish. The board is a couple of dozen."""
    import inspect
    src = inspect.getsource(R.from_ownerville)
    assert "_board_names" in src
    assert "lookup_person" in src


def test_the_search_has_a_time_budget():
    """It is one request per person against a slow server; without a budget a
    bad morning turns into an hour."""
    import inspect
    sig = inspect.signature(R.from_ownerville)
    assert "budget_s" in sig.parameters
    src = inspect.getsource(R.from_ownerville)
    assert "SEARCH_BUDGET_S" in src
    assert "time budget reached" in src


def test_one_name_failing_the_search_does_not_stop_the_others():
    import inspect
    src = inspect.getsource(R.from_ownerville)
    body = src[src.index("for name in missing"):]
    assert "except Exception" in body and "continue" not in body.split("got += 1")[0][-80:]


def test_somebody_the_search_never_finds_is_reported_not_ticked():
    """They get no verdict at all, which leaves their columns alone — unread
    is never 'not done'."""
    import inspect
    src = inspect.getsource(R.from_ownerville)
    assert "still not found in OwnerVille" in src


def test_the_search_skips_people_it_cannot_learn_anything_about(monkeypatch):
    """One request per person against a slow server (~23s each, measured), so
    asking about people who gain nothing is how a run spends its whole budget
    and still leaves somebody out."""
    from automations.icd_onboarding import board as B
    from automations.icd_onboarding import sheet as S
    from automations.icd_onboarding import fillers as F

    cols = list(F.columns_for("ownerville"))
    def row(name, **kw):
        r = {"Week of": B.week_label(MONDAY), "Name": name.split()[0],
             "Last Name": " ".join(name.split()[1:]), B.TERMINATED_AT: ""}
        for c in B.STEPS:
            r[c] = ""
        r.update(kw)
        return r

    rows = [row("Ada Fournier"),
            row("Bruno Castell", **{B.TERMINATED_AT: "11/06/2026"}),
            row("Cora Nilsen", **{c: "x" for c in cols})]
    monkeypatch.setattr(S, "rows_of", lambda grid: rows)
    monkeypatch.setattr(F, "workbook_for", lambda k: object())
    class WS:
        def get_all_values(self): return []
    monkeypatch.setattr(S, "open_board", lambda book, create=False: WS())

    got = R._board_names("raf", MONDAY, columns=cols)
    assert got == ["Ada Fournier"], (
        "the marked-off and the already-complete are not worth a request")


# ------------------------------------- a credential this box was never given

def test_sterling_is_skipped_not_failed_without_the_password(tmp_path, monkeypatch):
    """It reads ONE inbox shared by every office and writes through Sheets, so
    it runs wherever the password is, once — not on each office's machine. A
    box without it is not broken, and failing the hourly run over it makes
    every other step's result read like an outage (Lucy 2, 2026-11-10)."""
    from automations.icd_onboarding import bg_status as BG
    monkeypatch.setattr(BG, "APP_PW_PATH", str(tmp_path / "nope"))
    called = []
    monkeypatch.setattr(BG, "run", lambda *a, **k: called.append(1))
    said = []
    assert R.from_sterling("raf", MONDAY, log=said.append) == 0
    assert not called, "it must not open the inbox without a password"
    assert any("skipped" in s for s in said)


def test_sterling_runs_where_the_password_is(tmp_path, monkeypatch):
    from automations.icd_onboarding import bg_status as BG
    pw = tmp_path / "gmail-app-password-lucysterling"
    pw.write_text("abcd efgh ijkl mnop")
    monkeypatch.setattr(BG, "APP_PW_PATH", str(pw))
    monkeypatch.setattr(BG, "run", lambda *a, **k: 7)
    assert R.from_sterling("raf", MONDAY, log=lambda *a: None) == 7


# --------------------------------------------- each step where its data is

def test_every_routed_step_is_a_real_step():
    """A typo here would silently run nothing on that machine."""
    known = {n for n, _ in R.STEPS}
    for machine, steps in R.STEPS_BY_MACHINE.items():
        assert set(steps) <= known, machine


def test_the_routed_machines_cover_every_step_exactly_once():
    """A step nobody runs never fills; a step two boxes run races itself."""
    seen = [s for steps in R.STEPS_BY_MACHINE.values() for s in steps]
    assert sorted(seen) == sorted({n for n, _ in R.STEPS})
    assert len(seen) == len(set(seen)), "a step is routed to two machines"


def test_contacts_runs_where_the_contact_sync_runs():
    """Its state file is local to that box. Read from anywhere else it is
    simply absent, and the column never fills."""
    assert "contacts" in R.STEPS_BY_MACHINE["Lucy 1"]
    assert "contacts" not in R.STEPS_BY_MACHINE["Lucy 3"]


def test_ownerville_runs_where_rafs_ownerville_is():
    assert "ownerville" in R.STEPS_BY_MACHINE["Lucy 3"]
    assert "ownerville" not in R.STEPS_BY_MACHINE["Lucy 1"]


def test_a_machine_that_is_not_routed_runs_everything(monkeypatch):
    """An ICD's own computer holds all of its office's logins."""
    monkeypatch.delenv("ICD_ONBOARDING_STEPS", raising=False)
    from automations.shared import hub_identity as HI
    monkeypatch.setattr(HI, "machine_name", lambda: "some ICD's iMac")
    assert R.steps_here() == ()


def test_the_env_var_wins(monkeypatch):
    monkeypatch.setenv("ICD_ONBOARDING_STEPS", "seed, blueink")
    assert R.steps_here() == ("seed", "blueink")


# ------------------------------------- the box has to KNOW which box it is

def test_a_lucy_with_no_marker_is_still_recognised_by_hostname(monkeypatch):
    """The bug this exists to stop: `machine_name()` falls back to the
    hostname when the `.machine-profile` marker is missing, that misses both
    routing tables, and the box quietly runs EVERY step instead of its own
    two -- reading nothing and ticking nothing on four of them, which looks
    exactly like a quiet day."""
    monkeypatch.delenv("ICD_ONBOARDING_STEPS", raising=False)
    monkeypatch.delenv("ICD_ONBOARDING_OFFICES", raising=False)
    from automations.shared import hub_identity as HI
    monkeypatch.setattr(HI, "machine_name", lambda: "Lucys-Mac-mini.local")
    assert R.this_machine() == "Lucy 3"
    assert R.steps_here() == R.STEPS_BY_MACHINE["Lucy 3"]


def test_the_lucy_hostnames_are_not_guessed_from_the_word_lucy(monkeypatch):
    """`Lucys-Mac-mini.local` is Lucy 3 and `Lucys-MacBook-Neo` is Lucy 2;
    `Lucys-Mac-mini-2.local` is Lucy 4, not Lucy 2."""
    from automations.shared import hub_identity as HI
    for host, want in (("Alphaletes-Mac-mini.local", "Lucy 1"),
                       ("Lucys-MacBook-Neo.local", "Lucy 2"),
                       ("Lucys-Mac-mini.local", "Lucy 3"),
                       ("Lucys-Mac-mini-2.local", "Lucy 4")):
        monkeypatch.setattr(HI, "machine_name", lambda h=host: h)
        assert R.this_machine() == want, host


def test_the_marker_still_wins_when_it_is_there(monkeypatch):
    from automations.shared import hub_identity as HI
    monkeypatch.setattr(HI, "machine_name", lambda: "Lucy 2")
    assert R.this_machine() == "Lucy 2"


def test_an_unknown_machine_is_not_quietly_called_a_lucy(monkeypatch):
    """`mini_control._machine_profile()` defaults to "Lucy 1"; doing that here
    would have an ICD's own computer running Alphalete's split -- four steps
    it has no logins for, and none of its own."""
    monkeypatch.delenv("ICD_ONBOARDING_STEPS", raising=False)
    from automations.shared import hub_identity as HI
    monkeypatch.setattr(HI, "machine_name", lambda: "Some-Office-iMac.local")
    assert R.this_machine() not in R.STEPS_BY_MACHINE
    assert R.steps_here() == ()


def test_identity_failing_outright_runs_everything(monkeypatch):
    """A box that cannot name itself is treated as an ICD box, not as a Lucy
    with somebody else's steps."""
    monkeypatch.delenv("ICD_ONBOARDING_STEPS", raising=False)
    from automations.shared import hub_identity as HI

    def boom():
        raise OSError("no")
    monkeypatch.setattr(HI, "machine_name", boom)
    assert R.this_machine() == ""
    assert R.steps_here() == ()


# --------------------------- Contact Added matches on the phone, not the name

def _contacts_board(monkeypatch, rows, phones=(), emails=()):
    """One board and one reception account, and no network."""
    from automations.icd_onboarding import sheet as S
    from automations.second_round_contacts import contacts as K
    monkeypatch.setattr(R, "reception_account", lambda key: "recep@example.com")
    monkeypatch.setattr(K, "has_token", lambda a: True)
    monkeypatch.setattr(K, "token_file", lambda a: "tok.json")
    monkeypatch.setattr(K, "service", lambda a: object())
    monkeypatch.setattr(K, "existing_index",
                        lambda svc: ({p: "x" for p in phones},
                                     {e: "x" for e in emails}))
    monkeypatch.setattr(R.F, "workbook_for", lambda key: "BOOK")
    class _WS:
        def get_all_values(self):
            return []
    monkeypatch.setattr(S, "open_board", lambda book, create=False: _WS())
    monkeypatch.setattr(S, "rows_of", lambda grid: rows)
    monkeypatch.setattr(R.B, "for_week", lambda rows, week: rows)
    seen = {}
    monkeypatch.setattr(R.F, "apply",
                        lambda book, week, step, verdicts, **k:
                        (seen.update(verdicts), len(verdicts))[1])
    return seen


def test_a_contact_is_matched_by_phone_when_the_name_disagrees(monkeypatch):
    """An applicant types their own name into ApplicantStream, so the board
    and the account disagree over Mike/Michael, a middle name or an accent.
    The phone is the same ten digits in both -- and a name-only match answered
    0 of 21 on Raf's week of 11/08 while 98 contacts sat on record."""
    rows = [{"Name": "Mike", "Last Name": "Ruiz-Soto",
             "Phone": "(555) 201-3344", "Email": ""}]
    seen = _contacts_board(monkeypatch, rows, phones=["5552013344"])
    assert R.from_contacts("raf", MONDAY, dry_run=True, log=lambda *a: None) == 1
    assert seen == {"Mike Ruiz-Soto": {"Contact Added": True}}


def test_a_contact_is_matched_by_email_when_there_is_no_phone(monkeypatch):
    rows = [{"Name": "Ada", "Last Name": "F", "Phone": "",
             "Email": "Ada.F@Example.com"}]
    seen = _contacts_board(monkeypatch, rows, emails=["ada.f@example.com"])
    assert R.from_contacts("raf", MONDAY, dry_run=True, log=lambda *a: None) == 1
    assert "Ada F" in seen


def test_somebody_not_in_the_account_is_left_blank(monkeypatch):
    """Unread and not-done are the same cell here, so a false tick is the one
    thing this must not do."""
    rows = [{"Name": "Nobody", "Last Name": "Here",
             "Phone": "555-000-0000", "Email": "no@example.com"}]
    seen = _contacts_board(monkeypatch, rows, phones=["5552013344"])
    assert R.from_contacts("raf", MONDAY, dry_run=True, log=lambda *a: None) == 0
    assert seen == {}


def test_a_matching_NAME_alone_never_ticks(monkeypatch):
    """The name is not a match. Two different people share one often enough,
    and a wrong tick here says somebody was contacted who never was."""
    rows = [{"Name": "Michael", "Last Name": "Soto",
             "Phone": "555-999-8888", "Email": "other@example.com"}]
    seen = _contacts_board(monkeypatch, rows, phones=["5552013344"],
                           emails=["michael.soto@example.com"])
    assert R.from_contacts("raf", MONDAY, dry_run=True, log=lambda *a: None) == 0
    assert seen == {}


def test_an_office_with_no_reception_account_is_said_not_ticked(monkeypatch):
    """Every ICD gets their own reception Gmail (Megan, 2026-11-11). One that
    has not been given one yet is UNREAD, not a week where nobody was rung."""
    monkeypatch.setattr(R, "reception_account", lambda key: "")
    said = []
    assert R.from_contacts("raf", MONDAY, dry_run=True,
                           log=lambda *a: said.append(" ".join(map(str, a)))) == 0
    assert any("no reception account" in s for s in said), said


def test_an_account_this_machine_has_no_token_for_is_skipped(monkeypatch):
    from automations.second_round_contacts import contacts as K
    monkeypatch.setattr(R, "reception_account", lambda key: "recep@example.com")
    monkeypatch.setattr(K, "has_token", lambda a: False)
    monkeypatch.setattr(K, "token_file", lambda a: "tok.json")
    said = []
    assert R.from_contacts("raf", MONDAY, dry_run=True,
                           log=lambda *a: said.append(" ".join(map(str, a)))) == 0
    assert any("no Contacts token" in s for s in said), said
