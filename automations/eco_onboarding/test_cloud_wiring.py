"""The form has to work for OWNERS, not just on this Mac.

On a laptop the store finds an oauth token in the home directory. On Streamlit
Community Cloud there is no home directory and no token -- credentials arrive
as st.secrets -- and Cloud installs nothing but streamlit unless the app folder
carries a requirements.txt. Both failures are silent in the same way: the page
renders, the office list looks empty or stale, and a Save button saves nowhere.
metric_request's own deps file was written after exactly that (its comment says
so), so this is a repeat, not a hypothetical.
"""
from __future__ import annotations

from pathlib import Path

from automations.eco_onboarding import store

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "eco_onboarding"


class _FakeClient:
    def __init__(self):
        self.opened = []

    def open_by_key(self, key):
        self.opened.append(key)
        return "book:" + key


def test_an_injected_client_is_the_one_that_opens_the_book():
    fake = _FakeClient()
    try:
        store.set_client(fake)
        assert store._book() == "book:" + store.relay_id()
        assert fake.opened == [store.relay_id()]
    finally:
        store.set_client(None)


def test_a_passed_book_still_wins_over_the_client():
    """office_admin and the onboarding board pass their own already-open book.
    Injecting a client must not take that over -- opening the same workbook a
    second time is a whole extra read against a quota the fleet shares."""
    fake = _FakeClient()
    try:
        store.set_client(fake)
        assert store._book("their book") == "their book"
        assert fake.opened == []
    finally:
        store.set_client(None)


def test_the_relay_id_is_not_a_second_copy():
    from automations.icd_alerts import post as P
    assert store.relay_id() == P.RELAY_SPREADSHEET_ID


def test_the_form_declares_its_cloud_deps():
    req = APP / "requirements.txt"
    assert req.exists(), (
        "eco_onboarding/ has no requirements.txt, so Streamlit Cloud installs "
        "only streamlit: gspread fails to import and the form silently saves "
        "nowhere")
    text = req.read_text(encoding="utf-8").lower()
    for dep in ("streamlit", "gspread", "google-auth"):
        assert dep in text, f"{dep} missing from eco_onboarding/requirements.txt"


def test_the_form_injects_the_client_before_it_reads():
    """The order matters and is easy to break by moving a line: a read above
    the injection runs with no credentials on Cloud and caches the failure."""
    src = (APP / "app.py").read_text(encoding="utf-8")
    inject = src.index("store.set_client(")
    for first_read in ("store.offices()", "store.read("):
        assert src.index(first_read) > inject, (
            f"{first_read} appears before store.set_client() in app.py")
