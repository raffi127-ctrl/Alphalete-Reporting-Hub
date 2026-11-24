"""The board steps an office's own computer does for itself.

    python -m pytest automations/icd_onboarding/test_eco_steps.py -q
"""
import datetime as dt
import inspect

import pytest

from automations.icd_onboarding import eco_steps as ES

MON = dt.date(2026, 11, 22)


def _account(monkeypatch, phones=(), emails=(), token=True):
    from automations.second_round_contacts import contacts as K
    monkeypatch.setattr(ES, "reception_account", lambda key: "recep@example.com")
    monkeypatch.setattr(K, "has_token", lambda a: token)
    monkeypatch.setattr(K, "token_file", lambda a: "tok.json")
    monkeypatch.setattr(K, "service", lambda a: object())
    monkeypatch.setattr(K, "existing_index",
                        lambda svc: ({p: "x" for p in phones},
                                     {e: "x" for e in emails}))


def _board(monkeypatch, rows):
    monkeypatch.setattr(ES.F, "rows_anywhere", lambda key, week, log=print: rows)
    got = {}

    def fake_apply(key, week, source, verdicts, *, dry_run=True, log=print):
        got.update(verdicts)
        return len(verdicts)
    monkeypatch.setattr(ES.F, "apply_anywhere", fake_apply)
    return got


def test_the_step_reaches_the_board_the_way_that_works_on_both_machines():
    """`rows_anywhere` / `apply_anywhere` are the pair that choose gspread on a
    Lucy and the RELAY on an office machine. The step body knows no difference,
    which is the only reason one implementation is correct in both places."""
    src = inspect.getsource(ES.contacts)
    assert "rows_anywhere" in src and "apply_anywhere" in src
    assert "board_for" not in src and "open_board" not in src, \
        "an office Mac has no Google access at all"


def test_the_hub_runner_delegates_rather_than_keeping_a_second_copy():
    """A Hub copy and an office copy of the same step would drift, and the one
    that drifted would be the one nobody was reading."""
    from automations.icd_onboarding import run as R
    src = inspect.getsource(R.from_contacts)
    assert "eco_steps" in src
    assert "existing_index" not in src, "the body belongs in eco_steps"


def test_no_token_is_a_skip_that_ticks_nothing(monkeypatch):
    """A box without the token is not broken; it is not the one that does this
    job. Nothing is ticked on the way past, so a skipped pass can never read
    as 'nobody has been contacted'."""
    _account(monkeypatch, token=False)
    got = _board(monkeypatch, [{"Name": "Ada", "Last Name": "Lovelace",
                                "Phone": "(555) 010-0100", "Contact Added": ""}])
    said = []
    assert ES.contacts("raf", MON, dry_run=True,
                       log=lambda *a: said.append(" ".join(map(str, a)))) == 0
    assert got == {}
    assert any("no Contacts token" in s for s in said), said


def test_no_reception_account_ticks_nothing(monkeypatch):
    monkeypatch.setattr(ES, "reception_account", lambda key: "")
    got = _board(monkeypatch, [{"Name": "Ada", "Last Name": "L"}])
    said = []
    assert ES.contacts("raf", MON, dry_run=True,
                       log=lambda *a: said.append(" ".join(map(str, a)))) == 0
    assert got == {}


def test_a_read_that_throws_is_unread_not_an_empty_account(monkeypatch):
    from automations.second_round_contacts import contacts as K
    _account(monkeypatch)
    monkeypatch.setattr(K, "existing_index",
                        lambda svc: (_ for _ in ()).throw(RuntimeError("502")))
    got = _board(monkeypatch, [{"Name": "Ada", "Last Name": "L",
                                "Phone": "(555) 010-0100", "Contact Added": ""}])
    said = []
    assert ES.contacts("raf", MON, dry_run=True,
                       log=lambda *a: said.append(" ".join(map(str, a)))) == 0
    assert got == {}
    assert any("could not read" in s for s in said), said


def test_it_matches_on_the_phone(monkeypatch):
    _account(monkeypatch, phones=("5550100100",))
    got = _board(monkeypatch, [{"Name": "Ada", "Last Name": "Lovelace",
                                "Phone": "(555) 010-0100", "Contact Added": ""}])
    ES.contacts("raf", MON, dry_run=True, log=lambda *a: None)
    assert got == {"Ada Lovelace": {"Contact Added": True}}


def test_it_falls_back_to_the_email(monkeypatch):
    _account(monkeypatch, emails=("ada@example.com",))
    got = _board(monkeypatch, [{"Name": "Ada", "Last Name": "Lovelace",
                                "Email": "Ada@Example.com", "Contact Added": ""}])
    ES.contacts("raf", MON, dry_run=True, log=lambda *a: None)
    assert got == {"Ada Lovelace": {"Contact Added": True}}


def test_it_never_matches_on_the_name(monkeypatch):
    """An applicant types their own name into ApplicantStream, so the two
    sides disagree over Mike/Michael, a middle name or an accent -- and a name
    match that is wrong ticks a step for somebody nobody ever rang."""
    _account(monkeypatch, phones=("5559999999",), emails=("someone@example.com",))
    got = _board(monkeypatch, [{"Name": "Ada", "Last Name": "Lovelace",
                                "Phone": "", "Email": "", "Contact Added": ""}])
    ES.contacts("raf", MON, dry_run=True, log=lambda *a: None)
    assert got == {}


def test_somebody_already_ticked_is_not_looked_up_again(monkeypatch):
    """A tick never comes off, so once everybody on the week is ticked the
    answer cannot change -- and the read is the WHOLE account, 8,000-odd
    contacts, 29 times a day."""
    _account(monkeypatch, phones=("5550100100",))
    got = _board(monkeypatch, [{"Name": "Done", "Last Name": "Already",
                                "Phone": "(555) 010-0100",
                                "Contact Added": "11/20/2026"}])
    said = []
    assert ES.contacts("raf", MON, dry_run=True,
                       log=lambda *a: said.append(" ".join(map(str, a)))) == 0
    assert got == {}
    assert any("already ticked" in s for s in said), said


def test_somebody_marked_off_the_board_is_left_alone(monkeypatch):
    _account(monkeypatch, phones=("5550100100",))
    got = _board(monkeypatch, [{"Name": "Gone", "Last Name": "Away",
                                "Phone": "(555) 010-0100", "Contact Added": "",
                                ES.B.TERMINATED_AT: "11/21/2026"}])
    ES.contacts("raf", MON, dry_run=True, log=lambda *a: None)
    assert got == {}


def test_one_step_never_costs_the_others(monkeypatch):
    """An office needing two things done and getting one would look done."""
    def boom(key, week, *, dry_run=True, log=print):
        raise RuntimeError("the account would not open")
    monkeypatch.setattr(ES, "STEPS",
                        (("first", boom),
                         ("second", lambda k, w, *, dry_run=True, log=print: 3)))
    said = []
    assert ES.run_once("raf", MON, log=said.append) == 3
    assert any("would not open" in s for s in said), said


def test_the_offices_are_this_machines_own(monkeypatch):
    from automations.icd_alerts import config as C
    monkeypatch.setattr(C, "enrollments",
                        lambda: [{"office_key": "jamis"},
                                 {"office_key": "jamis10"}])
    assert ES.offices() == ["jamis"]


def test_every_step_takes_the_same_four_things():
    """`run_once` and the CLI both call them the same way; a step with its own
    signature would fail only when it was its turn."""
    for name, fn in ES.STEPS:
        sig = inspect.signature(fn)
        assert list(sig.parameters)[:2] == ["office_key", "week_start"], name
        assert "dry_run" in sig.parameters and "log" in sig.parameters, name


def test_the_cli_is_dry_until_told_otherwise(monkeypatch):
    """Every new report runs --dry-run until the output is confirmed."""
    seen = {}
    monkeypatch.setattr(ES, "STEPS", (("contacts", lambda k, w, *, dry_run=True,
                                       log=print: seen.setdefault("dry", dry_run) and 0),))
    monkeypatch.setattr(ES, "offices", lambda: ["raf"])
    ES.main(["--week", "2026-11-22"])
    assert seen["dry"] is True
