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


# --------------------------------- the one step that ACTS, 2026-11-24

def test_owner_submit_is_last_in_the_pass():
    """`ownerville` runs before it so the press works off what OwnerVille says
    this minute, not an hour-old board."""
    names = [n for n, _ in ES.STEPS]
    assert names.index("ownerville") < names.index("owner_submit")
    assert names[-2:] == ["owner_submit", "no_shows"], names


def test_no_office_is_armed_to_press():
    """The confirm box attests a criminal background check was reviewed AND
    PASSED, and there is no unsubmit. Alphalete keeps the switch it has had
    since 2026-09-22; everybody else is named one at a time, and nobody is."""
    from automations.obcl_ov_sweep import config as OVC
    assert OVC.OWNER_SUBMIT_LIVE_OFFICES == frozenset()
    assert OVC.owner_submit_live("omar") is False
    assert OVC.owner_submit_live("raf") is True


def test_the_gate_fails_closed_for_an_unknown_office():
    """The mistake it guards against is unfixable, so the default is no."""
    from automations.obcl_ov_sweep import config as OVC
    for key in ("someone", "SOMEONE", " someone ", "jamis10"):
        assert OVC.owner_submit_live(key) is False, key


def test_the_press_asks_the_gate_per_office():
    """Not the module constant: inheriting September's switch would have armed
    forty offices at once."""
    import inspect
    from automations.icd_onboarding import presses as P
    src = inspect.getsource(P.press_owner_submit)
    assert "owner_submit_live(office_key)" in src
    assert "live_gate=OVC.OWNER_SUBMIT_LIVE," not in src


def test_the_press_body_is_not_copied_into_eco_steps():
    """It is shared with the Hub side and its session is already routed, so a
    copy here would just be a second place for the press to live."""
    import ast
    import inspect
    # THE CODE, NOT THE PROSE -- and the docstring stripped by AST, not by
    # `getsource().replace(getdoc())`. getdoc DEDENTS, so that replace never
    # matches the raw source and the prose stays in: my first two attempts
    # both failed on this function's own docstring, which names the very
    # mechanics it is explaining are NOT here. test_fillers' invariant warns
    # about exactly this and I walked into it anyway.
    fn = ast.parse(inspect.getsource(ES.owner_submit).lstrip()).body[0]
    body = fn.body[1:] if isinstance(
        getattr(fn.body[0], "value", None), ast.Constant) else fn.body
    code = "\n".join(ast.unparse(n) for n in body)
    assert "press_owner_submit" in code
    for mechanic in ("session_anywhere", "submit_one", "candidates("):
        assert mechanic not in code, mechanic


def test_nothing_on_an_office_machine_imports_the_sweeps_runner():
    """`obcl_ov_sweep/run.py` imports gspread. Three separate reaches for
    `PROFILE_DIR` -- a PATH -- dragged it in before the constant moved to
    `config`; the shipped-closure test caught each one."""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parent
    for name in ("eco_steps.py", "presses.py", "sessions.py"):
        tree = ast.parse((root / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and \
                    node.module == "automations.obcl_ov_sweep.run":
                raise AssertionError("%s:%d imports the sweep's runner"
                                     % (name, node.lineno))
