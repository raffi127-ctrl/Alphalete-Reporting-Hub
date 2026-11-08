"""The board's rules, which are mostly about what it must NOT do.

Every one of these exists because the thing it forbids would quietly lose work
somebody did by hand, or quietly put a terminated person back on a list that
ends in a payroll record.
"""
from __future__ import annotations

import datetime as dt

import pytest

from automations.icd_onboarding import board as B

MONDAY = dt.date(2026, 11, 2)


def _cal(*names):
    return [{"first_name": n.split()[0], "last_name": " ".join(n.split()[1:]),
             "email": n.split()[0].lower() + "@example.com", "phone": "5550100001"}
            for n in names]


# ------------------------------------------------------------- seeding

def test_the_seed_fills_identity_and_nothing_else():
    """Every other column belongs to the automation that owns that step.
    Writing a blank here would be this module claiming to know something."""
    rows = B.seed_rows(_cal("Ada Fournier"), started=MONDAY)
    assert rows[0]["Name"] == "Ada" and rows[0]["Last Name"] == "Fournier"
    assert rows[0]["Start"] == "11/02/2026"
    for col in B.TICKS:
        assert col not in rows[0], "%s is not the seed's to write" % col
    assert B.CLASSROOM not in rows[0], "the classroom is the ICD's to set"


def test_a_second_seed_adds_newcomers_and_rewrites_nobody():
    """Somebody's hand-typed cell is worth more than a tidy re-seed."""
    existing = [dict(B.seed_rows(_cal("Ada Fournier"), MONDAY)[0],
                     **{"Blue Ink": "✓", "Final Status": ""})]
    got = B.merge(existing, B.seed_rows(_cal("Ada Fournier", "Bruno Castell"), MONDAY))
    assert [r["Name"] for r in got["add"]] == ["Bruno"]
    assert got["keep"] == 1


def test_somebody_the_icd_marked_off_does_not_come_back():
    """The calendar will go on saying they showed up for training. The board
    is the only thing that knows they left -- that is why it exists."""
    gone = dict(B.seed_rows(_cal("Ada Fournier"), MONDAY)[0],
                **{B.TERMINATED_AT: "11/06/2026"})
    got = B.merge([gone], B.seed_rows(_cal("Ada Fournier"), MONDAY))
    assert got["add"] == [], "they were marked off; the seed must not re-add them"
    assert got["left"] == [B.person_key(gone)]


def test_people_are_matched_on_email_not_spelling():
    a = B.seed_rows(_cal("Esme Vance"), MONDAY)[0]
    b = dict(a, Name="Esmé", **{"Last Name": "Vance-Hale"})
    assert B.person_key(a) == B.person_key(b)


# --------------------------------------------------------- hide, never delete

def test_terminated_rows_are_hidden_not_dropped():
    rows = [dict(B.seed_rows(_cal("Ada Fournier"), MONDAY)[0]),
            dict(B.seed_rows(_cal("Bruno Castell"), MONDAY)[0],
                 **{B.TERMINATED_AT: "11/06/2026"})]
    assert [r["Name"] for r in B.visible(rows)] == ["Ada"]
    assert [r["Name"] for r in B.visible(rows, show_terminated=True)] == ["Ada", "Bruno"]
    assert len(rows) == 2, "the row itself is still there"


# ------------------------------------------------------------- ticks go on

def test_a_tick_is_never_taken_off():
    rows = [dict(B.seed_rows(_cal("Ada Fournier"), MONDAY)[0], **{"Blue Ink": "✓"}),
            dict(B.seed_rows(_cal("Bruno Castell"), MONDAY)[0])]
    plan = B.tick_plan(rows, "Blue Ink", ["Bruno Castell"])
    assert plan == [1], "only the untouched one"
    assert B.tick_plan(rows, "Blue Ink", []) == [], "nobody named = nothing cleared"


def test_an_already_ticked_row_is_not_rewritten():
    rows = [dict(B.seed_rows(_cal("Ada Fournier"), MONDAY)[0], **{"Digi Docs": "✓"})]
    assert B.tick_plan(rows, "Digi Docs", ["Ada Fournier"]) == []


def test_the_classroom_is_not_a_machine_column():
    """It is the ICD's: they say who goes on which printed sheet."""
    rows = B.seed_rows(_cal("Ada Fournier"), MONDAY)
    with pytest.raises(ValueError, match="not a column a machine may write"):
        B.tick_plan(rows, B.CLASSROOM, ["Ada Fournier"])
    assert B.CLASSROOM not in B.TICKS


def test_there_is_no_final_status_column():
    """Megan, 2026-11-08: "I don't think that we need a final status on this."
    Terminating is something the ICD DOES in the panel, so it is row state and
    never a box on the chart."""
    assert "Final Status" not in B.COLUMNS
    assert B.TERMINATED_AT not in B.COLUMNS


def test_the_identity_columns_are_not_tickable_either():
    rows = B.seed_rows(_cal("Ada Fournier"), MONDAY)
    for col in ("Name", "Email", "Start"):
        with pytest.raises(ValueError):
            B.tick_plan(rows, col, ["Ada Fournier"])


# ------------------------------------------------------------------ the week

def test_the_tab_is_named_for_the_monday_whichever_day_is_given():
    assert B.tab_name(dt.date(2026, 11, 8)) == "Week of 11.02"
    assert B.tab_name(dt.date(2026, 11, 2)) == "Week of 11.02"


def test_the_columns_come_from_the_real_obcl():
    for col in ("Contact Added", "BG Status", "Digi Docs", "Onboarding Quizzes",
                "Blue Ink", "Headshot Photo", "UID Request", "Owner Submit",
                "Added to APEX"):
        assert col in B.COLUMNS


# --------------------------------------------------- the printed chart

def _row(name, classroom="", **steps):
    r = dict(B.seed_rows(_cal(name), MONDAY)[0])
    r[B.CLASSROOM] = classroom
    r.update(steps)
    return r


def test_remaining_lists_only_the_steps_still_outstanding():
    r = _row("Ada Fournier", "A", **{"Blue Ink": "✓", "BG Status": "Passed"})
    left = B.remaining(r)
    assert "Blue Ink" not in left and "BG Status" not in left
    assert "Digi Docs" in left and "Added to APEX" in left
    assert left == [c for c in B.STEPS if c in left], "kept in step order"


def test_a_blank_step_is_a_gap_not_a_quiet_zero():
    """A step nobody can see is a step nobody chases."""
    assert len(B.remaining(_row("Ada Fournier"))) == len(B.STEPS)


def test_one_sheet_per_classroom():
    rows = [_row("Ada Fournier", "Tuesday AM"), _row("Bruno Castell", "Tuesday AM"),
            _row("Cora Nilsen", "Thursday PM")]
    got = B.sheets(rows)
    assert [s["classroom"] for s in got] == ["Thursday AM".replace("AM", "PM"), "Tuesday AM"] \
        or [s["classroom"] for s in got] == ["Thursday PM", "Tuesday AM"]
    assert [len(s["people"]) for s in got] == [1, 2]


def test_people_with_no_classroom_land_on_a_sheet_of_their_own_LAST():
    """It is a job to do, not a classroom — it should not head the stack."""
    rows = [_row("Ada Fournier", "Tuesday AM"), _row("Bruno Castell")]
    got = B.sheets(rows)
    assert got[-1]["classroom"] == B.UNASSIGNED
    assert got[-1]["people"][0]["name"] == "Bruno Castell"


def test_the_sheet_leads_with_whoever_has_most_outstanding():
    rows = [_row("Ada Fournier", "A", **{c: "✓" for c in B.STEPS[:8]}),
            _row("Bruno Castell", "A")]
    people = B.sheets(rows)[0]["people"]
    assert people[0]["name"] == "Bruno Castell", "most left first"
    assert people[1]["done"] == 8


def test_somebody_finished_still_appears_with_nothing_left():
    """Dropping them would make the sheet say they left, not that they're done."""
    rows = [_row("Ada Fournier", "A", **{c: "✓" for c in B.STEPS})]
    sheet = B.sheets(rows)[0]
    assert sheet["people"][0]["remaining"] == []
    assert sheet["everyone_done"] is True
    assert sheet["outstanding"] == 0


def test_terminated_people_are_off_the_printout_unless_asked_for():
    rows = [_row("Ada Fournier", "A"),
            _row("Bruno Castell", "A", **{B.TERMINATED_AT: "11/06/2026"})]
    assert [p["name"] for p in B.sheets(rows)[0]["people"]] == ["Ada Fournier"]
    both = B.sheets(rows, show_terminated=True)[0]["people"]
    assert len(both) == 2


# ------------------------------------------------------- the printout itself

def test_each_person_gets_a_checklist_not_a_run_on_line():
    """Megan, 2026-11-08: "what's needed in like a bulleted form that they can
    check off". Nine steps on one comma-separated line is not checkable."""
    rows = [_row("Ada Fournier", "Tuesday AM", **{"Blue Ink": "✓"})]
    text = B.print_text(B.sheets(rows))
    boxes = [l for l in text.splitlines() if "[ ]" in l]
    assert len(boxes) == len(B.STEPS) - 1
    assert all(l.count("[ ]") == 1 for l in boxes), "one step per line"
    assert "Blue Ink" not in text, "a done step is not on the list to tick"


def test_the_html_gives_every_outstanding_step_its_own_box():
    rows = [_row("Ada Fournier", "A", **{c: "✓" for c in B.STEPS[:7]})]
    html = B.print_html(B.sheets(rows), week="Week of 11.02")
    assert html.count("class='box'") == 2
    assert "Owner Submit" in html and "Added to APEX" in html
    assert "Week of 11.02" in html


def test_each_classroom_starts_a_new_sheet_of_paper():
    """One printed sheet per classroom is the request, so the page break is
    not decoration."""
    rows = [_row("Ada Fournier", "Tuesday AM"), _row("Cora Nilsen", "Thursday PM")]
    html = B.print_html(B.sheets(rows))
    assert html.count("class='sheet'") == 2
    assert "page-break-after: always" in html


def test_somebody_finished_prints_with_no_boxes():
    rows = [_row("Ada Fournier", "A", **{c: "✓" for c in B.STEPS})]
    html = B.print_html(B.sheets(rows))
    assert "class='box'" not in html
    assert "t-done'>done<" in html


def test_a_name_with_an_ampersand_does_not_break_the_page():
    rows = [_row("Ada Fournier", "R&D <b>")]
    html = B.print_html(B.sheets(rows))
    assert "R&amp;D &lt;b&gt;" in html and "<b>" not in html.split("<style>")[1]


# ---------------------------------------------------------- colour coding

def test_the_bands_are_by_how_much_is_left():
    assert B.band_of({"remaining": []}) == "done"
    assert B.band_of({"remaining": ["a"]}) == "close"
    assert B.band_of({"remaining": ["a", "b"]}) == "close"
    assert B.band_of({"remaining": ["a", "b", "c"]}) == "behind"


def test_the_colour_is_never_the_only_thing_saying_it():
    """These get printed. A sheet that says it only in colour says nothing on a
    mono printer, or to anyone who cannot pick the shades apart."""
    rows = [_row("Ada Fournier", "A", **{c: "✓" for c in B.STEPS[:8]}),
            _row("Bruno Castell", "A")]
    html = B.print_html(B.sheets(rows))
    assert "class='tag t-close'>close<" in html
    assert "class='tag t-behind'>behind<" in html
    text = B.print_text(B.sheets(rows))
    assert "[CLOSE]" in text and "[BEHIND]" in text


def test_every_band_has_a_colour_and_they_differ():
    assert set(B.BAND_COLOUR) == {"done", "close", "behind"}
    washes = {v["wash"] for v in B.BAND_COLOUR.values()}
    assert len(washes) == 3


def test_the_sheet_carries_a_key_so_the_colours_mean_something():
    html = B.print_html(B.sheets([_row("Ada Fournier", "A")]))
    assert "class='key'" in html
    for word in ("done", "close", "behind"):
        assert word in html
