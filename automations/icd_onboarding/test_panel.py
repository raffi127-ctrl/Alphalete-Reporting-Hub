"""The board as the ICD sees it in the icon.

Run against the real board.js in a browser, because the panel is where the
rules become visible: a step that reads done when it is not, or somebody who
disappears instead of being marked off, is a person who gets missed — which is
the whole thing this is meant to stop.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("patchright.sync_api")

from automations.icd_onboarding import board as B

PANEL = Path(__file__).resolve().parents[2] / "extension" / "apex-new-starts" / "board.js"


@pytest.fixture
def page():
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page()
        pg.set_content("<body><div id='root'></div></body>")
        pg.evaluate("() => { window.chrome = {runtime: {sendMessage: (m, cb) => cb({ok: true})}}; }")
        pg.evaluate(PANEL.read_text(encoding="utf-8"))
        yield pg
        browser.close()


def _person(name, classroom="", off="", **steps):
    row = {"Week of": "11/02/2026", "Name": name.split()[0],
           "Last Name": " ".join(name.split()[1:]), "Classroom": classroom,
           "Terminated": off}
    for s in B.STEPS:
        row[s] = steps.get(s.replace(" ", "_"), "")
    return row


def _show(pg, people, show_off=False):
    pg.evaluate("""([people, showOff]) => {
        LucyBoard.state.people = people;
        LucyBoard.state.week = '11/02/2026';
        LucyBoard.state.weeks = ['11/02/2026'];
        LucyBoard.state.showOff = showOff;
        LucyBoard.render(document.getElementById('root'));
    }""", [people, show_off])
    return pg.inner_text("#root")


def test_the_panel_and_python_agree_on_the_steps(page):
    """Two lists of the same nine steps. If they drift the board shows the
    wrong thing rather than erroring, so this is the thing that catches it."""
    js = page.evaluate("() => LucyBoard.remaining({})")
    assert js == list(B.STEPS)


def test_the_bands_match_the_printout(page):
    for left, want in ((0, "done"), (1, "close"), (2, "close"), (3, "behind")):
        done = {s: "x" for s in list(B.STEPS)[:len(B.STEPS) - left]}
        got = page.evaluate("p => LucyBoard.band(p)", done)
        assert got == want, "%d left should be %s" % (left, want)
        assert got == B.band_of({"remaining": ["x"] * left})


def test_somebody_marked_off_is_hidden_until_asked_for(page):
    people = [_person("Ada Fournier"), _person("Bruno Castell", off="11/06/2026")]
    assert "Bruno" not in _show(page, people)
    shown = _show(page, people, show_off=True)
    assert "Bruno" in shown and "removed" in shown


def test_the_count_of_people_marked_off_is_offered(page):
    people = [_person("Ada Fournier"), _person("Bruno Castell", off="11/06/2026")]
    assert "show 1 removed" in _show(page, people)


def test_one_group_per_classroom_with_no_classroom_last(page):
    people = [_person("Ada Fournier", "Tuesday AM"), _person("Bruno Castell")]
    heads = page.evaluate("() => LucyBoard.grouped(LucyBoard.state.people).map(g => g.classroom)")
    _show(page, people)
    heads = page.evaluate("() => LucyBoard.grouped(LucyBoard.state.people.filter(p => !p.Terminated)).map(g => g.classroom)")
    assert heads == ["Tuesday AM", "No classroom yet"]


def test_whoever_is_furthest_behind_comes_first(page):
    nearly = _person("Ada Fournier", "A", **{s.replace(" ", "_"): "x" for s in B.STEPS[:8]})
    fresh = _person("Bruno Castell", "A")
    _show(page, [nearly, fresh])
    order = page.evaluate("() => LucyBoard.grouped(LucyBoard.state.people)[0].people"
                          ".map(p => p.Name)")
    assert order == ["Bruno", "Ada"]


def test_a_finished_person_reads_done_not_missing(page):
    done = _person("Ada Fournier", "A", **{s.replace(" ", "_"): "x" for s in B.STEPS})
    text = _show(page, [done])
    assert "Ada Fournier" in text and "done" in text


def test_the_summary_counts_only_people_still_on_the_board(page):
    people = [_person("Ada Fournier"), _person("Bruno Castell", off="11/06/2026")]
    _show(page, people)
    got = page.evaluate("() => LucyBoard.counts()")
    assert got["live"] == 1 and got["off"] == 1
    assert got["outstanding"] == len(B.STEPS), "the one marked off is not chased"


def test_the_week_picker_offers_every_week(page):
    page.evaluate("""() => {
        LucyBoard.state.people = [];
        LucyBoard.state.weeks = ['11/09/2026', '11/02/2026'];
        LucyBoard.state.week = '11/09/2026';
        LucyBoard.render(document.getElementById('root'));
    }""")
    opts = page.eval_on_selector_all("#bd-week option", "els => els.map(e => e.textContent)")
    assert opts == ["11/09/2026", "11/02/2026"]


def test_every_person_offers_mark_off_and_a_classroom_box(page):
    _show(page, [_person("Ada Fournier")])
    assert page.locator(".bd-ask").count() == 1
    assert page.locator(".bd-cls").count() == 1
    assert page.locator(".bd-loc").count() == 1
    assert page.locator("#bd-print").count() == 1


def test_removing_somebody_asks_why_before_it_does_anything(page):
    """Megan, 2026-11-11: "when it's clicked we make them have a reason why".
    The press opens the question; nothing is written until a reason is picked,
    so a mis-click on a small button costs nothing."""
    _show(page, [_person("Ada Fournier")])
    assert page.locator(".whyrow").count() == 1
    assert page.locator(".whyrow:not([hidden])").count() == 0, "asks nothing yet"
    page.locator(".bd-ask").first.click()
    assert page.locator(".whyrow:not([hidden])").count() == 1
    offered = page.eval_on_selector_all(
        ".whyrow:not([hidden]) .bd-why", "els => els.map(e => e.textContent)")
    assert offered == list(B.REMOVAL_REASONS)
    assert page.locator(".whyrow:not([hidden]) .bd-other").count() == 1
    page.locator(".whyrow:not([hidden]) .bd-nvm").click()
    assert page.locator(".whyrow:not([hidden])").count() == 0, "cancel closes it"


def test_a_sign_in_error_is_somewhere_it_can_actually_be_seen():
    """It used to render inside #home, which is hidden until you ARE signed
    in — so a failed sign-in looked like nothing happening at all, which is
    exactly how it was reported (Megan, 2026-11-09: "it just clears out the
    pw")."""
    html = (Path(__file__).resolve().parents[2] / "extension" /
            "apex-new-starts" / "popup.html").read_text(encoding="utf-8")
    before_home = html.split('id="home"')[0]
    assert 'id="msg"' in before_home, (
        "#msg must sit outside the signed-in section, or sign-in errors are "
        "invisible")


def test_a_background_check_code_says_what_it_means_on_hover(page):
    """Megan asked for this twice: two letters mean nothing to somebody who
    does not already have the list. The browser's own `title` waits about a
    second and often never shows, so the panel carries its own tooltip and the
    meaning has to be ON the cell, not only in a colour."""
    _show(page, [_person("Ada Fournier", "A", BG_Status="Complete")])
    cell = page.locator("td.bg").first
    assert cell.inner_text().strip() == "C"
    tip = cell.get_attribute("data-tip") or ""
    assert "Complete" in tip and "NOT a pass" in tip, tip
    cell.hover()
    shown = page.locator(".bd-tip:not([hidden])")
    assert shown.count() == 1, "the tooltip has to actually appear"
    assert "Complete" in shown.inner_text()


def test_every_background_check_status_has_a_meaning(page):
    """A code with no explanation is the thing this exists to prevent."""
    _show(page, [_person("Ada Fournier")])
    got = page.evaluate("Object.values(window.LucyBoard.BG || {})"
                        ".map(g => [g.code, g.name, g.means])")
    assert got, "the status table is not reachable"
    for code, name, means in got:
        assert code and name and means, (code, name, means)


def _removed(name, why, classroom="A"):
    row = _person(name, classroom, off="11/10/2026")
    row[B.REMOVED_WHY] = why
    return row


def test_removed_people_are_grouped_by_reason(page):
    """Megan, 2026-11-11: "same reasons should be grouped together". Four No
    Shows under one heading is a fact about the week; the same four scattered
    down a list is something somebody has to count by hand."""
    people = [_person("Ada Fournier", "A"),
              _removed("Bruno Castell", "No Show"),
              _removed("Cara Dunne", "No Show"),
              _removed("Dane Ellis", "Failed BG")]
    _show(page, people, show_off=True)
    heads = page.eval_on_selector_all("tr.sep", "els => els.map(e => e.textContent)")
    assert heads == ["Removed \u00b7 Failed BG (1)", "Removed \u00b7 No Show (2)"], heads
    # the reason is on the row itself too, not only in the heading above it
    assert "Failed BG" in page.inner_text("tr.b-gone td.gonewhy")


def test_a_removal_with_no_reason_is_not_hidden(page):
    """An older row from before the reason existed still has to show up --
    under a heading that says plainly that nobody recorded one."""
    _show(page, [_person("Ada Fournier", "A"),
                 _person("Bruno Castell", "A", off="11/10/2026")],
          show_off=True)
    heads = page.eval_on_selector_all("tr.sep", "els => els.map(e => e.textContent)")
    assert heads == ["Removed \u00b7 No reason recorded (1)"], heads


def test_live_people_are_numbered_down_the_left(page):
    """Megan, 2026-11-11: "we need them numbered on the left" -- so two people
    on the phone can say "number 7" and mean the same row. Each removal group
    counts from 1 again, which is what makes its heading's count readable."""
    people = [_person("Ada Fournier", "A"), _person("Bruno Castell", "A"),
              _removed("Cara Dunne", "No Show"),
              _removed("Dane Ellis", "No Show")]
    _show(page, people, show_off=True)
    nums = page.eval_on_selector_all("td.no", "els => els.map(e => e.textContent)")
    assert nums == ["1", "2", "1", "2"], nums


def test_other_lets_somebody_type_a_reason_and_refuses_a_blank_one(page):
    """Megan, 2026-11-11: an Other option they can free type. A blank one is
    not a reason, though -- saving nothing would record a removal nobody can
    explain later, which is the whole point of asking."""
    _show(page, [_person("Ada Fournier", "A")])
    page.locator(".bd-ask").first.click()
    page.locator(".bd-other").first.click()
    assert not page.locator(".whypick").first.is_visible(), "the buttons give way"
    assert page.locator(".bd-whytext").first.is_visible()
    page.evaluate("""() => {
        const seen = [], old = window.chrome.runtime.sendMessage;
        window.chrome.runtime.sendMessage = (m, cb) => { seen.push(m); old(m, cb); };
        window.__seen = seen;
    }""")
    page.locator(".bd-whysave").first.click()
    assert page.evaluate("() => window.__seen.length") == 0, "a blank is not saved"
    page.locator(".bd-whytext").first.fill("Moved out of state")
    page.locator(".bd-whysave").first.click()
    # A plain wait, not wait_for_function: that one polls in an isolated
    # world where the page's own window.__seen does not exist.
    page.wait_for_timeout(500)
    sent = page.evaluate("() => window.__seen[0]")
    assert sent["call"] == "board_mark"
    assert sent["extra"]["action"] == "terminate"
    assert sent["extra"]["reason"] == "Moved out of state"
