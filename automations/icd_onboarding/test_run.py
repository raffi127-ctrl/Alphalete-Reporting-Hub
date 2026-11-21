"""The runner: one office, every step, nothing stopping on one failure.

The rules here are about a run that is PARTLY able to work. A morning where
OwnerVille is down should still tick Blue Ink, and a source that could not be
read must leave its column alone rather than reporting everyone as behind.
"""
from __future__ import annotations

import datetime as dt

from automations.icd_onboarding import board as B
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


def test_the_sources_that_tick_as_they_act_are_not_steps_here():
    """Every source is a step of its own EXCEPT the two that already know the
    answer at the moment they do the thing:

      * `apex` ticks as it saves a record, so running it from here would be
        asking it to redo work it had already recorded;
      * `appstream` is the seed's own second read -- who of the scheduled
        turned up -- and opening that session is the slow part, so it ticks
        inside `seed` rather than as another job.
    """
    names = [n for n, _ in R.STEPS]
    assert "apex" not in names and "appstream" not in names
    from automations.icd_onboarding import fillers as F
    assert set(F.SOURCES) - set(names) == {"apex", "appstream"}


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
    """A step nobody runs never fills; a step two boxes run races itself.

    EXCEPT the ones in R.UNROUTED: R.HAND_RUN_ONLY (read-only probes) and
    R.OWN_CLOCK (scheduled, but on their own LaunchAgent rather than hourly),
    each with a reason written beside it. That list is the exception, so a new
    unrouted step fails here until somebody says why it is not hourly.
    """
    seen = [s for steps in R.STEPS_BY_MACHINE.values() for s in steps]
    scheduled = {n for n, _ in R.STEPS} - set(R.UNROUTED)
    assert sorted(seen) == sorted(scheduled)
    assert len(seen) == len(set(seen)), "a step is routed to two machines"
    for name in R.UNROUTED:
        assert name in {n for n, _ in R.STEPS}, name
        assert name not in seen, "%s is unrouted but on a machine's list" % name


def test_a_step_on_its_own_clock_has_a_launchagent_that_exists():
    """OWN_CLOCK is a promise that something fires it. An entry here with no
    plist on disk is a step nobody runs, dressed up as a scheduled one."""
    import pathlib
    import plistlib
    deploy = pathlib.Path(__file__).resolve().parents[2] / "deploy"
    for name in R.OWN_CLOCK:
        hits = [p for p in deploy.glob("com.alphalete.*.plist")
                if name.replace("_", "-") in p.name]
        assert hits, "%s is on its own clock but has no LaunchAgent" % name
        for p in hits:
            d = plistlib.load(p.open("rb"))     # unparseable = a card that cries wolf
            assert d.get("StartCalendarInterval"), "%s has no clock" % p.name


def test_hand_run_and_own_clock_do_not_overlap():
    assert not (set(R.HAND_RUN_ONLY) & set(R.OWN_CLOCK))


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


def test_a_fully_ticked_week_never_touches_the_contacts_account(monkeypatch):
    """Megan, 2026-11-11: "ours will be much larger than anyone else's" --
    Alphalete's reception Gmail holds ~16,000 contacts, which is 17 API pages,
    29 times a day on the half-hourly run. A tick never comes off, so once
    everybody on the week is ticked the answer cannot change."""
    from automations.second_round_contacts import contacts as K
    rows = [{"Name": "Ada", "Last Name": "F", "Phone": "555-201-3344",
             "Email": "", "Contact Added": "11/11/2026"}]
    seen = _contacts_board(monkeypatch, rows, phones=["5552013344"])

    def _boom(*a, **k):
        raise AssertionError("the account must not be read at all")
    monkeypatch.setattr(K, "service", _boom)
    monkeypatch.setattr(K, "existing_index", _boom)
    said = []
    assert R.from_contacts("raf", MONDAY, dry_run=True,
                           log=lambda *a: said.append(" ".join(map(str, a)))) == 0
    assert seen == {}
    assert any("already ticked" in s for s in said), said


def test_somebody_removed_is_not_a_reason_to_keep_reading(monkeypatch):
    """A removed row has no tick and never will. Counting it as outstanding
    would make the expensive read happen for ever."""
    from automations.second_round_contacts import contacts as K
    rows = [{"Name": "Ada", "Last Name": "F", "Phone": "555-201-3344",
             "Email": "", "Contact Added": "11/11/2026"},
            {"Name": "Bruno", "Last Name": "C", "Phone": "555-999-0000",
             "Email": "", "Contact Added": "", "Terminated": "11/10/2026"}]
    _contacts_board(monkeypatch, rows, phones=["5552013344"])

    def _boom(*a, **k):
        raise AssertionError("the account must not be read at all")
    monkeypatch.setattr(K, "service", _boom)
    monkeypatch.setattr(K, "existing_index", _boom)
    assert R.from_contacts("raf", MONDAY, dry_run=True, log=lambda *a: None) == 0


def test_one_person_still_missing_is_enough_to_read(monkeypatch):
    """The saving is only safe because it cannot hide somebody."""
    rows = [{"Name": "Ada", "Last Name": "F", "Phone": "555-201-3344",
             "Email": "", "Contact Added": "11/11/2026"},
            {"Name": "Bruno", "Last Name": "C", "Phone": "555-999-0000",
             "Email": "", "Contact Added": ""}]
    seen = _contacts_board(monkeypatch, rows,
                           phones=["5552013344", "5559990000"])
    assert R.from_contacts("raf", MONDAY, dry_run=True, log=lambda *a: None) == 1
    # only the one that needed it -- the already-ticked row is not re-written
    assert seen == {"Bruno C": {"Contact Added": True}}


# ------------------------------------------- seeded from who is DUE to start

def test_the_seed_reads_the_scheduled_row_and_has_no_fallback_for_it():
    """Megan, 2026-11-15: the board's week is the week somebody starts in the
    office, so it is seeded from who is SCHEDULED. The calendar walk answers
    who SHOWED UP — standing in for this read it would quietly seed a
    different set of people, so there is deliberately no fallback here."""
    import ast
    import pathlib

    src = pathlib.Path(R.__file__).read_text()
    body = ast.get_source_segment(src, next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "seed"))
    code = [l for l in body.splitlines() if not l.strip().startswith("#")]
    joined = "\n".join(code)
    assert "read_scheduled_week(" in joined, "the scheduled row is the seed"

    at = next(i for i, l in enumerate(code) if "read_scheduled_week(" in l)
    # No try/except wrapped around it: the lines before it must not open one.
    assert not any(l.strip().startswith("try:") for l in code[max(0, at - 3):at]), \
        "an unread scheduled row must raise, not fall back to a different row"
    assert "fdot.read_week(" in joined, \
        "the walk stays the fallback for the SHOWED-UP read, which it answers"


def test_showing_up_ticks_the_row_and_never_takes_anybody_off():
    """ON ONLY, like every other tick. Somebody absent on Monday may walk in
    on Tuesday; marking them off is a person's call, and "No Show" is one of
    the reasons the panel offers."""
    import inspect
    from automations.icd_onboarding import board as B

    src = inspect.getsource(R._tick_showed_up)
    code = [l for l in src.splitlines() if not l.strip().startswith("#")]
    joined = "\n".join(code)
    assert "True" in joined and "False" not in joined, \
        "it only ever says yes"
    assert "terminat" not in joined.lower() and "remove" not in joined.lower()
    assert B.SHOWED_UP in joined or "SHOWED_UP" in joined


def test_an_unread_showed_up_row_ticks_nobody_rather_than_emptying_it():
    got = R._tick_showed_up("raf", MONDAY, None, dry_run=True,
                            log=lambda *a: None)
    assert got == 0


def test_showing_up_is_not_an_onboarding_step():
    """It is nothing anybody works through, so it is no column on the printed
    chase sheet and no part of "4 of 10 done"."""
    from automations.icd_onboarding import board as B

    assert B.SHOWED_UP in B.COLUMNS
    assert B.SHOWED_UP in B.TICKS, "a machine writes it"
    assert B.SHOWED_UP not in B.STEPS
    assert B.SHOWED_UP not in B.BY_HAND
    assert B.SHOWED_UP not in B.SHORT, "not a heading on the printed sheet"


def test_the_panel_knows_it_too_and_only_says_so_once_the_day_has_come():
    """"not in yet" on somebody due Thursday reads as a problem when it is
    not one."""
    import pathlib
    js = pathlib.Path("extension/apex-new-starts/board.js").read_text()
    assert "const SHOWED_UP = 'Showed Up'" in js
    assert "dueAlready" in js and "not in yet" in js
    steps = js.split("const STEPS = [", 1)[1].split("]", 1)[0]
    assert "Showed Up" not in steps, "not one of the step columns"


def test_a_dry_run_tells_the_hub_nothing():
    """It writes no cell, so there is nothing to report as done -- and a
    read-only probe whose source could not be reached must not turn this
    card RED for everybody. It did, on 2026-11-15: the AppStream credential
    is deliberately not on Megan's Mac, so the probe failed there and the
    live Hub card went red on the strength of a question."""
    import ast
    import pathlib

    src = pathlib.Path(R.__file__).read_text()
    body = ast.get_source_segment(src, next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "main"))
    code = [l for l in body.splitlines() if not l.strip().startswith("#")]
    joined = "\n".join(code)
    assert "nothing_to_report()" in joined
    at = next(i for i, l in enumerate(code) if "nothing_to_report()" in l)
    before = "\n".join(code[max(0, at - 8):at])
    assert "not a.write" in before, "only on a dry run"
    # ...and before any step runs, so a step that raises cannot beat it.
    assert at < next(i for i, l in enumerate(code) if "for_office(" in l)


def test_the_hub_hook_has_a_name_for_having_nothing_to_say():
    from automations.shared import hub_autopublish as H
    assert H.nothing_to_report() is None
    assert H.already_reported() is True


class TestTheLabelledFunnelWinsDedupe:
    """Aalya Vasquez and Zachary Murphy are on 11280 AND 23965 (2026-11-20).

    The office's own account is read first and carries no label, so
    first-wins threw away the only copy that said where they came from and
    they landed on the board with a blank Funnel.
    """

    def _people(self):
        own = {"first_name": "Aalya", "last_name": "Vasquez",
               "email": "a@x.com"}
        theirs = {"first_name": "Aalya", "last_name": "Vasquez",
                  "email": "a@x.com", B.FUNNEL: "Algemar Kennel El Paso"}
        return own, theirs

    def test_the_same_person_keeps_the_funnel_that_names_itself(self):
        own, theirs = self._people()
        people, seen = [own], {R._person_key(own)}
        # what the loop does when the second funnel offers the same person
        key = R._person_key(theirs)
        assert key in seen
        for held in people:
            if R._person_key(held) == key and not str(
                    held.get(B.FUNNEL) or "").strip():
                held[B.FUNNEL] = theirs[B.FUNNEL]
                break
        assert people[0][B.FUNNEL] == "Algemar Kennel El Paso"
        assert len(people) == 1, "still one row, not two"

    def test_the_key_is_the_email(self):
        own, theirs = self._people()
        assert R._person_key(own) == R._person_key(theirs) == "a@x.com"

    def test_a_different_person_is_not_merged(self):
        own, _ = self._people()
        other = {"first_name": "Zachary", "last_name": "Murphy",
                 "email": "z@x.com"}
        assert R._person_key(own) != R._person_key(other)
