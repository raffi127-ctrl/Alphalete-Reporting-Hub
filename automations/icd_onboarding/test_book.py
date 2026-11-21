"""Each ICD's own onboarding workbook, a tab per week.

python -m pytest automations/icd_onboarding/test_book.py
"""
from __future__ import annotations

import datetime as dt

from automations.icd_onboarding import board as B
from automations.icd_onboarding import book as K


class TestTabNames:
    def test_a_week_is_named_for_its_monday(self):
        # every day of the week of 11/23 lands on the same tab
        for d in range(7):
            when = dt.date(2026, 11, 23) + dt.timedelta(days=d)
            assert K.tab_name(when) == "OBCL 11.23", when

    def test_the_name_round_trips(self):
        monday = dt.date(2026, 11, 23)
        assert K.week_of(K.tab_name(monday), 2026) == monday

    def test_no_leading_zeroes(self):
        """The D2D OBCL writes 11.2, not 11.02 -- match what they read."""
        assert K.tab_name(dt.date(2026, 11, 2)) == "OBCL 11.2"

    def test_somebody_elses_tab_is_not_ours(self):
        for t in ("Sheet1", "Onboarding", "2nd Rds", "D2D OBCL 11.23",
                  "OBCL", "", None):
            assert K.week_of(t, 2026) is None, t

    def test_a_hand_typed_tab_still_reads(self):
        assert K.week_of("  obcl  11.23 ", 2026) == dt.date(2026, 11, 23)

    def test_an_impossible_date_is_not_a_week(self):
        assert K.week_of("OBCL 13.45", 2026) is None


class TestThePicker:
    def test_it_lists_only_the_week_tabs(self):
        got = K.weeks_in(["OBCL 11.16", "OBCL 11.23", "Notes", "Sheet1"],
                         2026)
        assert sorted(got) == [dt.date(2026, 11, 16), dt.date(2026, 11, 23)]
        assert got[dt.date(2026, 11, 23)] == "OBCL 11.23"

    def test_an_empty_book_offers_nothing(self):
        assert K.weeks_in([], 2026) == {}


class TestWhereTheBookIs:
    def test_the_id_column_is_the_one_that_already_exists(self):
        """`Onboarding Sheet` is on the Office Settings tab already -- one
        place, so there is no second list of sheet ids to drift."""
        from automations.office_admin import relay_admins as RA
        assert K.ID_COLUMN in RA.SET_HEAD

    def test_the_book_is_named_for_the_owner(self):
        assert K.BOOK_NAME % "Rafael Hidalgo" == \
            "LucyECO Onboarding - Rafael Hidalgo"


class TestTheHeadersMatchTheBoard:
    def test_a_new_week_is_laid_with_the_board_s_own_columns(self):
        """The extension reads these by label, so a tab laid with anything
        else is a week it cannot show."""
        from automations.icd_onboarding import sheet as S
        want = list(B.COLUMNS) + list(S.PAST_THE_CHART)
        assert want[0] == B.WEEK
        assert B.FUNNEL in want
        assert len(set(want)) == len(want), "a duplicated header"


class TestNoFlagDay:
    """board_for picks the new shape only where it exists."""

    def test_no_week_means_the_old_tab(self, monkeypatch):
        """The new shape is a tab PER WEEK. With no week there is no tab to
        choose, so the stacked tab is the only honest answer."""
        from automations.icd_onboarding import sheet as S
        seen = {}
        monkeypatch.setattr(S, "open_board",
                            lambda wb, create=True: seen.setdefault("old", True))
        monkeypatch.setattr("automations.icd_onboarding.fillers.workbook_for",
                            lambda k: object())
        monkeypatch.setattr(K, "open_book",
                            lambda *a, **k: (_ for _ in ()).throw(
                                AssertionError("must not be asked")))
        S.board_for("raf", None)
        assert seen.get("old")

    def test_an_office_with_no_book_stays_on_the_old_tab(self, monkeypatch):
        from automations.icd_onboarding import sheet as S
        seen = {}
        monkeypatch.setattr(K, "open_book", lambda *a, **k: None)
        monkeypatch.setattr(S, "open_board",
                            lambda wb, create=True: seen.setdefault("old", True))
        monkeypatch.setattr("automations.icd_onboarding.fillers.workbook_for",
                            lambda k: object())
        S.board_for("raf", dt.date(2026, 11, 23))
        assert seen.get("old")

    def test_an_office_with_a_book_gets_its_week_tab(self, monkeypatch):
        from automations.icd_onboarding import sheet as S
        book = object()
        got = {}
        monkeypatch.setattr(K, "open_book", lambda *a, **k: book)
        monkeypatch.setattr(K, "open_week",
                            lambda b, w, create=True: got.setdefault("w", w))
        monkeypatch.setattr(S, "open_board", lambda *a, **k: (
            _ for _ in ()).throw(AssertionError("old tab must not be used")))
        S.board_for("raf", dt.date(2026, 11, 23))
        assert got["w"] == dt.date(2026, 11, 23)
