"""The Chrome extension: is it the same engine, and does it read the clipboard?

Megan, 2026-11-06: "we just made an extension to send out background checks. i
want this to function as an extension as well instead of a bookmark - it seems
smoother."

Two things can go wrong with that move and neither is visible by looking:

  1. The extension's copy of the run engine drifts from filler.py. The engine
     types values onto real payroll records, and a fork's symptom is a wrong
     value on a real employee -- so `engine.js` is GENERATED, and the first
     test here fails the moment the file on disk stops matching.

  2. The week's list is read wrongly off the clipboard. The bookmarklet RAN
     that text; the extension parses it instead, so the parser is now load-
     bearing and gets the real `--button` output as its fixture.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from automations.apex_new_starts import build_extension as BX
from automations.apex_new_starts import filler

pytest.importorskip("patchright.sync_api")

from automations.apex_new_starts.test_form_match import FORM as STAGE_ONE_FORM

EXT = Path(__file__).resolve().parents[2] / "extension" / "apex-new-starts"

PEOPLE = [
    {"name": "Aundre Browder", "start": "09/07/2026",
     "pages": {"new": {"First Name": "Aundre", "Last Name": "Browder",
                       "User Name": "aundre@example.com",
                       "Account Email": "aundre@example.com",
                       "Hire Date": "09/07/2026", "Position": "Sales Rep",
                       "Rate of Pay": "10.00", "State Working In": "Texas",
                       "Basis of Pay": "Commissions", "Pay Frequency": "Weekly",
                       "Department": "400 Sales"}}},
    {"name": "Emily Flores Castaneda", "start": "09/07/2026",
     "pages": {"new": {"First Name": "Emily", "Last Name": "Flores Castaneda"}}},
]


@pytest.fixture
def page():
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page()
        yield pg
        browser.close()


# ---------------------------------------------------------------- one engine

def test_engine_js_is_what_the_builder_would_write():
    """The whole reason engine.js is generated. If this fails, nobody has to
    guess which copy is right: run the builder."""
    on_disk = (EXT / "engine.js").read_text(encoding="utf-8")
    assert on_disk == BX.engine_js(), (
        "extension/apex-new-starts/engine.js has drifted from filler.py. "
        "Run: python -m automations.apex_new_starts.build_extension")


def test_the_generated_engine_parses_and_defines_itself(page):
    page.set_content("<body></body>")
    page.evaluate((EXT / "engine.js").read_text(encoding="utf-8"))
    assert page.evaluate("typeof window.__ansEngine") == "function"


def test_the_extension_engine_fills_a_page_like_the_bookmarklet_does(page):
    """Parity, on the screen it actually types into.

    Flat `fields` rather than per-page ones for the same reason the
    bookmarklet's own tests use them: page scoping keys off the Apex URL, which
    a fixture page does not have.
    """
    flat = [{"name": "Aundre Browder",
             "fields": {"First Name": "Aundre", "Last Name": "Browder"}}]
    page.set_content(STAGE_ONE_FORM)
    page.evaluate((EXT / "engine.js").read_text(encoding="utf-8"))
    page.evaluate("d => window.__ansEngine({week:'WE 11.8', build:'x', data:d})",
                  flat)
    page.locator("#ansfill").click()
    page.wait_for_timeout(1200)
    assert page.locator("#f1").input_value() == "Aundre"
    assert page.locator("#f3").input_value() == "Browder"


def test_the_week_shows_the_week_it_was_given(page):
    page.set_content(STAGE_ONE_FORM)
    page.evaluate((EXT / "engine.js").read_text(encoding="utf-8"))
    page.evaluate("d => window.__ansEngine("
                  "{week:'WE 11.8', build:'Nov 06 09:12', data:d})", PEOPLE)
    assert "WE 11.8" in page.locator("#anspanel").inner_text()


# ------------------------------------------------------- reading the setup

def _parse(pg, text):
    pg.set_content("<body></body>")
    pg.evaluate((EXT / "setup.js").read_text(encoding="utf-8"))
    return pg.evaluate("t => window.ApexSetup.parse(t)", text)


def _setup_text(people, week="WE 11.8", **kw):
    """Exactly what the Hub puts on the clipboard."""
    return filler.build_js(people, week, kw.get("build", "Nov 06 09:12"),
                           kw.get("notice", ""), kw.get("start", ""))[
        len("javascript:"):]


def test_it_reads_the_real_hub_clipboard_text(page):
    got = _parse(page, _setup_text(PEOPLE))
    assert got["ok"] is True
    assert got["week"] == "WE 11.8"
    assert got["build"] == "Nov 06 09:12"
    assert [p["name"] for p in got["data"]] == [p["name"] for p in PEOPLE]


def test_a_two_word_surname_survives_the_parse(page):
    """Commas and spaces inside the embedded JSON are why this is a balanced
    scan and not a regex."""
    got = _parse(page, _setup_text(PEOPLE))
    assert got["data"][1]["name"] == "Emily Flores Castaneda"


def test_an_address_holding_a_semicolon_does_not_cut_the_list_short(page):
    people = [{"name": "Test Person",
               "pages": {"profile": {"Street Address": "1 A St; Apt 2",
                                     "City": "Dallas"}}}]
    got = _parse(page, _setup_text(people))
    assert got["ok"] is True
    assert got["data"][0]["pages"]["profile"]["Street Address"] == "1 A St; Apt 2"


def test_the_notice_comes_through_so_the_red_banner_still_shows(page):
    got = _parse(page, _setup_text(PEOPLE, notice="TYPE BY HAND: Lian Reyes"))
    assert "Lian Reyes" in got["notice"]


def test_the_start_date_comes_through(page):
    got = _parse(page, _setup_text(PEOPLE, start="09/28/2026"))
    assert got["start"] == "09/28/2026"


def test_a_plain_json_payload_is_accepted_too(page):
    """So the Hub can stop shipping code on the clipboard later without the
    extension needing a change."""
    got = _parse(page, json.dumps({"week": "WE 11.8", "people": PEOPLE,
                                   "start": "09/28/2026"}))
    assert got["ok"] is True and got["week"] == "WE 11.8"
    assert len(got["data"]) == 2


def test_something_else_on_the_clipboard_says_what_to_do(page):
    got = _parse(page, "https://apex.herbjoyent.com/roster")
    assert got["ok"] is False
    assert "Get this week" in got["error"]


def test_an_empty_clipboard_says_so(page):
    assert _parse(page, "   ")["ok"] is False


def test_a_setup_with_nobody_in_it_is_refused(page):
    """Rather than opening a panel that says 0 people and looks broken."""
    got = _parse(page, _setup_text([]))
    assert got["ok"] is False
    assert "nobody" in got["error"]


def test_no_social_can_ride_in_on_the_clipboard(page):
    """Socials are typed at run time and are in no file and no payload. This
    pins that the thing the extension STORES cannot carry one."""
    got = _parse(page, _setup_text(PEOPLE))
    blob = json.dumps(got["data"]).lower()
    for word in ("ssn", "social", "sec"):
        assert word not in blob


# --------------------------------------------------------------- the wiring

def test_the_engine_runs_in_the_pages_own_world():
    """Kendo and Angular live in the page. An isolated-world engine would find
    every dropdown unsettable -- the Marital Status failure, by construction."""
    m = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    main = [c for c in m["content_scripts"] if "engine.js" in c["js"]]
    assert len(main) == 1
    assert main[0]["world"] == "MAIN"
    assert "main.js" in main[0]["js"], "the bridge must share the page world"


def test_the_half_that_holds_the_list_is_isolated():
    m = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    iso = [c for c in m["content_scripts"] if "loader.js" in c["js"]]
    assert len(iso) == 1 and iso[0]["world"] == "ISOLATED"
    assert "setup.js" in iso[0]["js"], "the parser must share the loader's world"


def test_it_only_ever_touches_apex():
    m = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert m["host_permissions"] == ["https://apex.herbjoyent.com/*"]
    for c in m["content_scripts"]:
        assert c["matches"] == ["https://apex.herbjoyent.com/*"]


def test_every_file_the_manifest_names_exists():
    m = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    named = [m["action"]["default_popup"]]
    for c in m["content_scripts"]:
        named += c["js"] + c.get("css", [])
    named += list(m["icons"].values())
    for rel in named:
        assert (EXT / rel).exists(), f"manifest names a missing file: {rel}"
