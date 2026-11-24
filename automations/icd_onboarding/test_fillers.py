"""What a source may and may not tick.

Each of these is a rule that already exists in one of the automations being
wired up. They are tested here because this is now the one place all five go
through, so a rule lost here is a rule lost everywhere.
"""
from __future__ import annotations

import datetime as dt

import pytest

from automations.icd_onboarding import board as B
from automations.icd_onboarding import fillers as F

MONDAY = dt.date(2026, 11, 2)


def _row(name, off="", **steps):
    r = {"Week of": B.week_label(MONDAY), "Name": name.split()[0],
         "Last Name": " ".join(name.split()[1:]), "Classroom": "",
         B.TERMINATED_AT: off}
    for s in B.STEPS:
        r[s] = steps.get(s.replace(" ", "_"), "")
    return r


# --------------------------------------------------------------- on only

def test_only_a_yes_ticks():
    rows = [_row("Ada Fournier")]
    got = F.plan(rows, "ownerville", {"Ada Fournier": {"Digi Docs": True,
                                                       "UID Request": False}})
    assert list(got) == ["Digi Docs"]
    assert list(got["Digi Docs"]) == ["Ada Fournier"]


def test_unread_is_not_undone():
    """done_columns answers None when it could not read the header. That means
    the page did not load, not that the step is outstanding."""
    rows = [_row("Ada Fournier")]
    assert F.plan(rows, "ownerville", {"Ada Fournier": {"Digi Docs": None}}) == {}


def test_a_no_never_clears_an_existing_tick():
    rows = [_row("Ada Fournier", Digi_Docs="11/03/2026")]
    assert F.plan(rows, "ownerville", {"Ada Fournier": {"Digi Docs": False}}) == {}


def test_an_already_ticked_step_is_not_ticked_again():
    """So running this hourly writes nothing on the hours nothing happened."""
    rows = [_row("Ada Fournier", Digi_Docs="11/03/2026")]
    assert F.plan(rows, "ownerville", {"Ada Fournier": {"Digi Docs": True}}) == {}


# ------------------------------------------------- a source stays in its lane

def test_a_source_cannot_tick_somebody_elses_column():
    """Blue Ink has no business touching Owner Submit. A wiring mistake should
    surface here, not as a wrong tick on a real person."""
    rows = [_row("Ada Fournier")]
    with pytest.raises(ValueError, match="may not tick"):
        F.plan(rows, "blueink", {"Ada Fournier": {"Owner Submit": True}})


def test_the_ownerville_columns_are_all_ones_the_sweep_actually_fills():
    """Every column the ownerville source claims, the sweep really writes.

    A column the sweep does not fill is a column everybody learns to ignore,
    so this is the drift check -- but it is measured against
    `ov_table.TABLE_COLUMNS`, which is what the sweep READS the View Progress
    table into, rather than `config.COLUMNS`, which is only the tick columns
    on Alphalete's own OBCL tab.

    Two kinds sit outside that tab and still come off the same read:
      * OV BG Status -- a STATE, not a tick: what OwnerVille thinks of the
        background check, which is what the Owner Submit button waits on
        (Megan, 2026-11-11);
      * the OV_GATES -- login created, drug test, service: gates that held
        Owner Submit with no column anywhere to say so (Megan, 2026-11-24).
    """
    from automations.obcl_ov_sweep import config as OV
    from automations.obcl_ov_sweep import ov_table

    claimed = set(F.SOURCES["ownerville"])
    assert set(OV.COLUMNS) <= claimed
    outside = claimed - set(OV.COLUMNS)
    assert outside == {"OV BG Status", *B.OV_GATES}
    assert "OV BG Status" in B.STATUS_STEPS, "it advances, it is not ticked"
    # The gates are read by the sweep, not just named here.
    for gate in B.OV_GATES:
        assert gate in ov_table.TABLE_COLUMNS, \
            "%s is claimed but the sweep reads no OwnerVille header for it" % gate


def test_the_gates_are_writable_without_being_steps():
    """Megan, 2026-11-24, asked for the columns so the board explains a hold.

    In STEPS they would change every office's "4 of 10 done" to a denominator
    of 13 and put three columns on the PRINTED chase sheet, whose key reads "a
    blank cell is one to tick off here" -- and nobody ticks a drug test on
    paper."""
    assert len(B.STEPS) == 10
    for gate in B.OV_GATES:
        assert gate not in B.STEPS, "%s must not be counted as a step" % gate
        assert gate in B.TICKS, "%s is written by the sweep" % gate
        assert gate in B.COLUMNS, "%s needs a column on the board" % gate
        assert gate not in B.BY_HAND


def test_the_gates_sit_before_the_thing_they_gate():
    before = B.COLUMNS.index(B.OV_GATES[0])
    assert before > B.COLUMNS.index("OV BG Status")
    assert B.COLUMNS.index(B.OV_GATES[-1]) < B.COLUMNS.index("Owner Submit")


def test_the_background_check_is_not_added_a_second_time():
    """It is already on the board as OV BG Status, read off that same cell.
    Two names for one OwnerVille cell is worse than the gap it would close."""
    from automations.obcl_ov_sweep import ov_table
    assert "Background Check" not in B.COLUMNS
    assert ov_table.TABLE_COLUMNS["Login Created"] == ("login created",)
    assert "background check" not in [
        h for g in B.OV_GATES for h in ov_table.TABLE_COLUMNS[g]]


def test_every_source_column_is_one_a_machine_may_WRITE():
    """TICKS, not STEPS: `Showed Up` is a machine-written fact about a row
    rather than a step anybody works through, and a source claiming a by-hand
    column (Classroom, Gender, Location) is a wiring mistake that would type
    over somebody's own answer."""
    for source, cols in F.SOURCES.items():
        for c in cols:
            assert c in B.TICKS, \
                "%s claims %r, which no machine may write" % (source, c)
            assert c not in B.BY_HAND, \
                "%s claims %r, which a person fills" % (source, c)


def test_the_sources_cover_every_step_exactly_once():
    seen = [c for cols in F.SOURCES.values() for c in cols]
    assert sorted(c for c in seen if c in B.STEPS) == sorted(B.STEPS), \
        "every step has exactly one owner"
    assert sorted(seen) == sorted(B.TICKS), \
        "and every machine-written column has one, steps or not"


def test_an_unknown_source_is_refused():
    with pytest.raises(ValueError, match="not a source"):
        F.plan([], "guesswork", {})


# ----------------------------------------------------- people who have left

def test_somebody_marked_off_is_never_ticked():
    """They left. Ticking their steps puts them back on the chase list and on
    the printed sheet."""
    rows = [_row("Ada Fournier", off="11/06/2026")]
    assert F.plan(rows, "ownerville", {"Ada Fournier": {"Digi Docs": True}}) == {}


def test_somebody_not_on_the_board_is_ignored_quietly():
    """OwnerVille carries the whole office; the board is this week."""
    rows = [_row("Ada Fournier")]
    assert F.plan(rows, "ownerville", {"Someone Else": {"Digi Docs": True}}) == {}


def test_names_are_matched_past_spelling():
    rows = [_row("Esme Vance Hale")]
    got = F.plan(rows, "blueink", {"esme  vance-hale": {"Blue Ink": True}})
    assert list(got["Blue Ink"]) == ["Esme Vance Hale"]


# ------------------------------------------------------------- the dry run

def test_a_dry_run_names_everybody_it_would_tick():
    """A count on its own cannot be checked against anything."""
    rows = [_row("Ada Fournier"), _row("Bruno Castell")]
    got = F.plan(rows, "ownerville", {"Ada Fournier": {"Digi Docs": True},
                                      "Bruno Castell": {"Digi Docs": True}})
    said = F.describe(got)
    assert "Ada Fournier" in said and "Bruno Castell" in said and "Digi Docs" in said


def test_apply_is_dry_by_default():
    import inspect
    assert inspect.signature(F.apply).parameters["dry_run"].default is True


def test_a_status_lands_as_its_own_words_not_a_date():
    """Megan, 2026-11-09: "We should just have Background Status: xStatus"."""
    rows = [_row("Ada Fournier")]
    got = F.plan(rows, "sterling", {"Ada Fournier": {"BG Status": "Passed"}})
    assert got == {"BG Status": {"Ada Fournier": "Passed"}}


def test_a_plain_yes_still_lands_as_a_date():
    rows = [_row("Ada Fournier")]
    got = F.plan(rows, "blueink", {"Ada Fournier": {"Blue Ink": True}})
    written = got["Blue Ink"]["Ada Fournier"]
    assert written.count("/") == 2, "a tick is a date: %r" % written


# ------------------------------- ticking from the job that does the thing

def test_a_single_column_source_can_tick_by_name(monkeypatch):
    """The contact sync knows WHO it just added; it should not have to build a
    verdict dict to say so."""
    seen = {}

    def fake_apply(book, week, source, verdicts, **kw):
        seen.update({"source": source, "verdicts": verdicts, "dry": kw.get("dry_run")})
        return 0

    monkeypatch.setattr(F, "apply", fake_apply)
    monkeypatch.setattr(F, "workbook_for", lambda k: object())
    F.tick("raf", MONDAY, "contacts", ["Ada Fournier", "Bruno Castell"],
           log=lambda *a: None)
    assert seen["verdicts"] == {"Ada Fournier": {"Contact Added": True},
                                "Bruno Castell": {"Contact Added": True}}
    assert seen["dry"] is True, "dry unless asked"


def test_a_multi_column_source_must_say_which(monkeypatch):
    monkeypatch.setattr(F, "workbook_for", lambda k: object())
    n = len(F.SOURCES["ownerville"])
    with pytest.raises(ValueError, match="owns %d columns" % n):
        F.tick("raf", MONDAY, "ownerville", ["Ada Fournier"], log=lambda *a: None)


def test_an_office_with_no_board_is_reported_not_silently_skipped(monkeypatch):
    said = []
    monkeypatch.setattr(F, "workbook_for",
                        lambda k: (_ for _ in ()).throw(RuntimeError("no office %r" % k)))
    n = F.tick("nowhere", MONDAY, "contacts", ["Ada Fournier"], log=said.append)
    assert n == 0
    assert any("nowhere" in s for s in said), "a silent miss is a tick nobody notices"


def test_raf_resolves_even_though_he_has_no_metrics_workbook():
    import inspect
    src = inspect.getsource(F.workbook_for)
    assert "ALL_IN_ONE_RAF" in src, "Alphalete is not an ICD and has no metrics book"
# ------------------------------------------- which OwnerVille programme

def test_the_ov_programme_is_per_office_not_alphaletes():
    """ICDs are in different programmes (Megan, 2026-11-09). RES-AT&T is
    Alphalete's, and inheriting it for an ICD reads an empty table — which
    looks exactly like nobody having done anything."""
    import inspect
    from automations.obcl_ov_sweep import ov_table
    assert "campaign" in inspect.signature(ov_table.read_table).parameters
    from automations.office_admin import config as OC
    assert hasattr(OC.Office("k", "o", "1"), "ov_program")
    assert OC.office("raf").ov_program == "RES-AT&T"


def test_an_office_with_no_programme_set_does_not_inherit_alphaletes():
    from automations.office_admin import config as OC
    assert OC.office("omar").ov_program == "", (
        "blank until somebody says which — a guess here reads an empty table")


def test_a_programme_ownerville_does_not_have_fails_loudly():
    """Selecting a campaign that is not in the dropdown selects nothing, and
    the table then reads empty. That must raise, not return no rows."""
    import inspect
    from automations.obcl_ov_sweep import ov_table
    src = inspect.getsource(ov_table.read_table)
    assert "has no %r programme" in src
    assert "It offers:" in src


def _apex_row(first="Chrisjen", last="Davis", **cells):
    row = {"Name": first, "Last Name": last, "Added to APEX": ""}
    row.update(cells)
    return row


def test_an_ask_goes_in_the_steps_own_column():
    """A step waiting on a person says so where the leader is already
    looking. Megan, 2026-11-15, on a name two sources spell differently:
    "that 'alert' needs to go back to the admin to approve the correct name
    so that you can run it"."""
    got = F.plan([_apex_row()], "apex",
                 {"Chrisjen Davis": {"Added to APEX": F.ALERT_PREFIX
                                     + "approve the surname"}})
    assert got == {"Added to APEX": {"Chrisjen Davis":
                                     "NEEDS: approve the surname"}}, got


def test_the_real_date_lands_on_top_of_an_ask():
    """Without this the ask would wedge the step shut: an answered cell is
    never written again, so the step would read "NEEDS" forever after it had
    actually run."""
    got = F.plan([_apex_row(**{"Added to APEX": "NEEDS: approve the surname"})],
                 "apex", {"Chrisjen Davis": {"Added to APEX": True}})
    assert list(got["Added to APEX"]) == ["Chrisjen Davis"], got
    assert not F.is_alert(got["Added to APEX"]["Chrisjen Davis"])


def test_an_ask_never_overwrites_an_answer_or_another_ask():
    done = F.plan([_apex_row(**{"Added to APEX": "11/15/2026"})], "apex",
                  {"Chrisjen Davis": {"Added to APEX": "NEEDS: anything"}})
    assert done == {}, "a step that is DONE is not reopened by an ask"
    asked = F.plan([_apex_row(**{"Added to APEX": "NEEDS: approve the surname"})],
                   "apex", {"Chrisjen Davis": {"Added to APEX": "NEEDS: other"}})
    assert asked == {}, "the same ask is not rewritten every run"


def test_an_ask_is_one_line_and_nothing_without_words():
    """It lands in a spreadsheet cell a person reads down a column."""
    import datetime as dt
    seen = {}

    def fake_apply(_book, _week, source, verdicts, **kw):
        seen.update({"source": source, "verdicts": verdicts, "kw": kw})
        return 1

    old_apply, old_book = F.apply, F.workbook_for
    F.apply, F.workbook_for = fake_apply, (lambda _k: object())
    try:
        n = F.alert("raf", dt.date(2026, 11, 9), "apex",
                    {"Chrisjen Davis": "packet says Dav,\n  AppStream says Davis",
                     "": "no name", "Nobody": "   "},
                    dry_run=False)
    finally:
        F.apply, F.workbook_for = old_apply, old_book
    assert n == 1
    said = seen["verdicts"]
    assert list(said) == ["Chrisjen Davis"], "no name and no words write nothing"
    text = said["Chrisjen Davis"]["Added to APEX"]
    assert text == "NEEDS: packet says Dav, AppStream says Davis", text
    assert seen["kw"]["dry_run"] is False


class TestUidRequestAdvances:
    """RQ is a waypoint, not a destination (Megan 2026-11-20)."""

    def _rows(self, uid=""):
        return [{"Name": "Jaime", "Last Name": "Molina", "UID Request": uid}]

    def test_requested_writes_rq_not_a_date(self):
        got = F.plan(self._rows(), "ownerville",
                     {"Jaime Molina": {"UID Request": "RQ"}})
        assert got["UID Request"]["Jaime Molina"] == "RQ"

    def test_a_granted_uid_replaces_rq(self):
        # the trap: fillers writes a tick ONCE, so without ranking the cell
        # would still say RQ the day AT&T answered
        got = F.plan(self._rows(uid="RQ"), "ownerville",
                     {"Jaime Molina": {"UID Request": True}})
        assert "UID Request" in got
        assert got["UID Request"]["Jaime Molina"] != "RQ"

    def test_rq_never_pulls_back_a_granted_uid(self):
        got = F.plan(self._rows(uid="11/14/2026"), "ownerville",
                     {"Jaime Molina": {"UID Request": "RQ"}})
        assert got == {}

    def test_rq_is_not_rewritten_over_itself(self):
        got = F.plan(self._rows(uid="RQ"), "ownerville",
                     {"Jaime Molina": {"UID Request": "RQ"}})
        assert got == {}


# ------------------------------ apply_anywhere reaches the office's OWN board

def test_apply_anywhere_tells_apply_which_office_it_is(monkeypatch):
    """Otherwise `apply` falls to its own office_key="" and opens the old
    stacked tab instead of the office's week tab.

    2026-11-22: a live ownerville pass said "ticked 12" and Jaime Molina's six
    columns were still blank on the board, because all twelve cells went to
    the tab nobody reads any more. The count was of writes that happened --
    just not where anybody was looking.
    """
    seen = {}

    def fake_apply(workbook, week_start, source, verdicts, **kw):
        seen.update(kw)
        return 0

    monkeypatch.setattr(F, "apply", fake_apply)
    monkeypatch.setattr(F, "workbook_for", lambda k: object())
    monkeypatch.setattr(F, "on_office_machine", lambda k: False)
    F.apply_anywhere("raf", MONDAY, "ownerville", {}, dry_run=False)
    assert seen.get("office_key") == "raf", (
        "apply was not told the office, so it writes to the stacked tab")


def test_reading_and_writing_reach_the_same_sheet(monkeypatch):
    """THE INVARIANT THAT WAS MISSING, 2026-11-24.

    `apply` resolved the board with `sheet.board_for`, which knows about an
    office's own per-week book; `rows_anywhere` used
    `open_board(workbook_for(...))`, the old stacked tab. So the writes landed
    on the right tab and the reads came back empty, and every step that reads
    before it writes quietly did nothing -- Blue Ink, Contact Added and Added
    to APEX all read 0 of 32 on a week with 32 people on it.

    Silence, not an error, which is why it survived: a step with nobody to
    write about looks exactly like a step with nothing to do.
    """
    import inspect
    import re

    def code(fn):
        """The source with comments and docstring removed, so prose in either
        cannot satisfy -- or fail -- this test. The first version of this
        check failed on the comment explaining the bug it was pinning."""
        src = inspect.getsource(fn)
        src = src.replace(inspect.getdoc(fn) or "\0", "")
        return "\n".join(re.sub(r"#.*$", "", ln) for ln in src.splitlines())

    for fn in (F.rows_anywhere, F.apply):
        src = code(fn)
        assert "board_for" in src, \
            "%s must reach the board the one way that knows about a per-week " \
            "book" % fn.__name__
        assert "open_board(workbook_for(" not in src, \
            "%s still reaches for the old stacked tab" % fn.__name__


def test_rows_anywhere_asks_for_the_week_it_was_given(monkeypatch):
    """A per-week book has a tab PER WEEK, so the week has to reach
    `board_for` -- passing only the office key silently gets the old tab."""
    import datetime as dt
    from automations.icd_onboarding import sheet as S

    seen = {}

    def fake_board_for(office_key, week_start=None, *, create=False):
        seen["office"], seen["week"] = office_key, week_start
        return None

    monkeypatch.setattr(S, "board_for", fake_board_for)
    monkeypatch.setattr(F, "on_office_machine", lambda k: False)
    assert F.rows_anywhere("raf", dt.date(2026, 11, 22),
                           log=lambda *a: None) == []
    assert seen == {"office": "raf", "week": dt.date(2026, 11, 22)}
