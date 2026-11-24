"""The OwnerVille session, whichever way this machine has one.

Megan, 2026-11-24: "the OV sweep would happen on the ECO machine."

    python -m pytest automations/icd_onboarding/test_ov_anywhere.py -q
"""
import contextlib

import pytest

from automations.icd_onboarding import fillers as F
from automations.icd_onboarding import ov_anywhere as OVA


@contextlib.contextmanager
def _fake(label, seen):
    seen.append(label)
    yield label


def test_an_office_machine_uses_its_own_ownerville(monkeypatch):
    """Its own login, its own session -- nothing queues behind another
    office, which is the whole reason the contention dissolves."""
    seen = []
    monkeypatch.setattr(F, "on_office_machine", lambda k="": True)
    import automations.icd_alerts.ov_session as OVS
    monkeypatch.setattr(OVS, "ownerville_here",
                        lambda **kw: _fake("office", seen))
    with OVA.session_anywhere("raf", log=lambda *a: None) as page:
        assert page == "office"
    assert seen == ["office"]


def test_a_lucy_keeps_the_hub_session(monkeypatch):
    """One machine serves many offices there, and the Hub session is the thing
    that stops two runs reading each other's rows."""
    seen = []
    monkeypatch.setattr(F, "on_office_machine", lambda k="": False)
    import automations.shared.tableau_patchright as TP
    monkeypatch.setattr(TP, "ownerville_session",
                        lambda **kw: _fake("hub", seen))
    with OVA.session_anywhere("raf", log=lambda *a: None) as page:
        assert page == "hub"
    assert seen == ["hub"]


def test_the_branch_is_not_a_guess():
    """`on_office_machine` answers it the one way that is true: a LucyEco
    enrolment for that office is installed, which is exactly the machine with
    the office's own login and no Google access."""
    import inspect
    src = inspect.getsource(OVA.session_anywhere)
    assert "on_office_machine" in src
    for guess in ("platform.", "hostname", "getenv"):
        assert guess not in src, guess


def test_the_hub_import_is_inside_its_own_branch():
    """`shared.tableau_patchright` cannot ship, so an office machine must never
    reach the line that imports it."""
    import inspect
    src = inspect.getsource(OVA.session_anywhere)
    at_office = src.index("ownerville_here")
    at_hub = src.index("tableau_patchright")
    assert at_office < at_hub, "the office branch returns before the Hub import"
    assert "return" in src[at_office:at_hub]


def test_nothing_was_looked_at_has_one_answer_on_both_machines():
    """A held sign-in on an office box and a busy session on a Lucy mean the
    same thing -- no rows were seen -- so no step may record an answer."""
    names = {c.__name__ for c in OVA.unavailable()}
    assert "OwnervilleUnavailable" in names
    assert "OwnervilleBusy" in names


def test_the_presses_go_through_it():
    """The press was the thing queueing behind three other jobs on Lucy 3."""
    import inspect
    from automations.icd_onboarding import presses as P
    # `_press` is the shared body both presses delegate to -- it is where the
    # session is opened, so that is where this looks. Asserting on
    # `press_owner_submit` itself passed on nothing but a delegation line.
    for fn in (P._press, P.uid_reasons):
        src = inspect.getsource(fn)
        assert "session_anywhere" in src, fn.__name__
    whole = inspect.getsource(P)
    assert "from automations.shared.tableau_patchright import ownerville_session" \
        not in whole, "nothing here opens the Hub session directly any more"


def test_the_campaign_still_comes_from_the_office(monkeypatch):
    """The campaign IS the roster: falling back to Alphalete's would look an
    ICD's new start up on somebody else's campaign and find nobody."""
    seen = {}
    monkeypatch.setattr(F, "on_office_machine", lambda k="": True)
    import automations.icd_alerts.ov_session as OVS

    @contextlib.contextmanager
    def fake(**kw):
        seen.update(kw)
        yield "page"
    monkeypatch.setattr(OVS, "ownerville_here", fake)
    with OVA.session_anywhere("raf", campaign="RES-AT&T",
                              log=lambda *a: None):
        pass
    assert seen.get("campaign") == "RES-AT&T"


def test_every_ownerville_opening_on_the_board_goes_through_it():
    """The three that queued behind each other on Lucy 3: the five-column read
    and both presses. An opening that still reaches for the Hub session
    directly is one office still waiting for another's turn -- and it would
    also be the line that breaks the moment this ships to an office machine,
    because `tableau_patchright` is not there.
    """
    import ast
    import pathlib as _p

    root = _p.Path(__file__).resolve().parent
    offenders = []
    for path in sorted(root.glob("*.py")):
        if path.name.startswith("test_") or path.name == "ov_anywhere.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module == "automations.shared.tableau_patchright" and any(
                    a.name == "ownerville_session" for a in node.names):
                offenders.append("%s:%d" % (path.name, node.lineno))
    assert not offenders, (
        "these open the Hub's OwnerVille session directly instead of "
        "ov_anywhere.session_anywhere: " + ", ".join(offenders))


def test_a_debugging_flag_cannot_put_a_browser_on_an_owners_screen(monkeypatch):
    """`--show` is a flag for looking at a Lucy. On an office's own computer
    whether a window opens is the session's call and nobody else's -- it opens
    one only when a sign-in genuinely needs it, and hides it."""
    seen = {}
    monkeypatch.setattr(F, "on_office_machine", lambda k="": True)
    import automations.icd_alerts.ov_session as OVS

    @contextlib.contextmanager
    def fake(**kw):
        seen.update(kw)
        yield "page"
    monkeypatch.setattr(OVS, "ownerville_here", fake)
    with OVA.session_anywhere("raf", headless=False, log=lambda *a: None):
        pass
    assert seen.get("headless") is True, \
        "headless=False from a caller must not reach an office machine"


def test_show_still_works_on_a_lucy(monkeypatch):
    seen = {}
    monkeypatch.setattr(F, "on_office_machine", lambda k="": False)
    import automations.shared.tableau_patchright as TP

    @contextlib.contextmanager
    def fake(**kw):
        seen.update(kw)
        yield "page"
    monkeypatch.setattr(TP, "ownerville_session", fake)
    with OVA.session_anywhere("", headless=False, log=lambda *a: None):
        pass
    assert seen.get("headless") is False


def test_the_sweep_opens_no_ownerville_of_its_own():
    """The job that lost its whole 30-minute wait at 08:00 on 2026-11-24,
    behind focus_office_att, captainship_drafts and a second copy of itself."""
    import ast
    import pathlib as _p
    path = (_p.Path(__file__).resolve().parents[1] / "obcl_ov_sweep" / "run.py")
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(
                a.name == "ownerville_session" for a in node.names):
            raise AssertionError(
                "obcl_ov_sweep/run.py:%d still opens the Hub session directly"
                % node.lineno)
