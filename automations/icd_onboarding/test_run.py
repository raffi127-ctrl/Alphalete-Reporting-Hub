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
    # Eve's record, not a second Google Contacts call of our own.
    assert "second_round_contacts" in src and "STATE_PATH" in src
    assert "contacts" not in src.split("def from_contacts")[0]


def test_an_absent_state_file_ticks_nothing_rather_than_claiming_nobody():
    """It runs where the contact sync runs. Anywhere else the file is simply
    missing, which is unread -- never 'nobody has been added'."""
    import inspect
    src = inspect.getsource(R.from_contacts)
    assert "exists()" in src and "return 0" in src


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
    monkeypatch.setattr(S, "open_board", lambda book, create=False: object())
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
