"""OwnerVille on the office's own machine, with the office's own login.

Megan, 2026-11-24: "the OV sweep would happen on the ECO machine."

    python -m pytest automations/icd_alerts/test_ov_session.py -q
"""
import pytest

from automations.icd_alerts import ov_session as S


class _Ctx:
    def __init__(self):
        self.pages, self.closed = [], False

    def new_page(self):
        page = object()
        self.pages.append(page)
        return page

    def close(self):
        self.closed = True


@pytest.fixture
def ov(monkeypatch):
    """`ov_read`, with every browser call stubbed."""
    from automations.icd_alerts import ov_read as OV
    ctx = _Ctx()
    monkeypatch.setattr(OV, "_context", lambda p, headless, quiet=False: ctx)
    monkeypatch.setattr(OV, "_has_session", lambda p, log=print: True)
    monkeypatch.setattr(OV, "ov_hold_message", lambda: "")
    monkeypatch.setattr(OV, "_is_v2", lambda page: False)
    monkeypatch.setattr(OV, "_choose_client",
                        lambda page, cid, campaign, log=print: True)
    import sys
    import types
    fake = types.ModuleType("patchright.sync_api")

    class _PW:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False
    fake.sync_playwright = lambda: _PW()
    pkg = types.ModuleType("patchright")
    pkg.sync_api = fake
    monkeypatch.setitem(sys.modules, "patchright", pkg)
    monkeypatch.setitem(sys.modules, "patchright.sync_api", fake)
    return OV, ctx


def test_a_live_session_is_reused_and_opens_no_window(ov):
    """A sweep that signed in every time would spend its strikes and reach
    OwnerVille's lock page."""
    OV, ctx = ov
    seen = []
    OV._context = lambda p, headless, quiet=False: (seen.append(headless) or ctx)
    with S.ownerville_here(log=lambda *a: None) as page:
        assert page is not None
    assert seen == [True], "headless, because the session was live"


def test_the_context_is_always_closed(ov):
    """The profile is shared with the knocks read; a context left behind is a
    profile the next sweep finds locked."""
    OV, ctx = ov
    with S.ownerville_here(log=lambda *a: None):
        pass
    assert ctx.closed is True


def test_it_closes_even_when_the_caller_raises(ov):
    OV, ctx = ov
    with pytest.raises(ValueError):
        with S.ownerville_here(log=lambda *a: None):
            raise ValueError("the read went wrong")
    assert ctx.closed is True


def test_a_sign_in_on_hold_refuses_instead_of_opening_a_window(ov):
    """Jenny (Figspire), 2026-10-12: a saved login kept failing, the agent
    retried every sweep, and Lucy's window sat on OwnerVille's "Account
    Permanently Locked" page 134 times in one day. No window at all while the
    sign-in is held -- the window IS the popup the owner keeps closing."""
    OV, ctx = ov
    OV._has_session = lambda p, log=print: False
    OV.ov_hold_message = lambda: "OwnerVille shows Lucy a LOCKED page"
    with pytest.raises(S.OwnervilleUnavailable) as e:
        with S.ownerville_here(log=lambda *a: None):
            pass
    assert "LOCKED" in str(e.value)


def test_it_raises_rather_than_handing_back_a_dead_page(ov):
    """A caller handed a page that cannot work reports "no rows", and "I could
    not look" must never read as "nobody has done anything"."""
    OV, ctx = ov
    OV._has_session = lambda p, log=print: False
    OV.ov_hold_message = lambda: "held"
    with pytest.raises(S.OwnervilleUnavailable):
        with S.ownerville_here(log=lambda *a: None):
            pytest.fail("it must not yield a page here")


def test_a_v2_page_whose_switcher_refuses_is_an_error_not_an_empty_read(ov):
    """V2 ignores the URL pin server-side: Jamis (2026-10-06) got no grid at
    all, Roshan (2026-10-08) got the wrong campaign's rows. If the client
    cannot be chosen, whose rows the page would serve is unknown."""
    OV, ctx = ov
    OV._is_v2 = lambda page: True
    OV._choose_client = lambda page, cid, campaign, log=print: False
    with pytest.raises(S.OwnervilleUnavailable) as e:
        with S.ownerville_here(campaign="att", log=lambda *a: None):
            pass
    assert "whose rows" in str(e.value)


def test_the_campaign_is_this_offices_own_and_never_a_callers():
    """An office reading another campaign's rows is indistinguishable from an
    office with nothing on."""
    import inspect
    src = inspect.getsource(S.ownerville_here)
    assert "C.CAMPAIGN_IDS" in src and "C.campaign_id()" in src


def test_it_does_not_reimplement_the_hold_or_the_quiet_window():
    """Everything hard here is already solved in `ov_read`; a second copy is
    what drifts."""
    import inspect
    src = inspect.getsource(S)
    assert "OV._has_session" in src and "OV.ov_hold_message" in src
    assert "OV._context" in src
    assert "OV_RETRY_MINUTES" not in src, "the hold's own numbers stay in ov_read"
