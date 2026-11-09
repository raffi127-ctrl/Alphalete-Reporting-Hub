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
    assert "Bruno" in shown and "marked off" in shown


def test_the_count_of_people_marked_off_is_offered(page):
    people = [_person("Ada Fournier"), _person("Bruno Castell", off="11/06/2026")]
    assert "show 1 marked off" in _show(page, people)


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
    assert page.locator(".bd-mark").count() == 1
    assert page.locator(".bd-cls").count() == 1
    assert page.locator("#bd-print").count() == 1
