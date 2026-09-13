"""Unit tests. NOTHING HERE TOUCHES A SHEET, BLUE INK OR MESSAGES.

Every sheet read is a fake grid and every send path is a stub -- some test_*.py
in this repo really do send, and that is a trap worth not adding to.
[[no blind test sweeps]]

    python -m unittest automations.birthday_reminders.test_birthday_reminders
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.birthday_reminders import backfill as BF
from automations.birthday_reminders import config as C
from automations.birthday_reminders import liveness as L
from automations.birthday_reminders import run as R
from automations.birthday_reminders import store as S


class FakeWS:
    def __init__(self, grid):
        self.grid = [list(r) for r in grid]
        self.appended = []

    def get_all_values(self):
        return [list(r) for r in self.grid]

    def append_rows(self, rows, **_kw):
        self.appended += [list(r) for r in rows]
        self.grid += [list(r) for r in rows]


HEAD = ["Rep Name", "Birthday (MM/DD)", "Source", "Added", "Skip", "Notes"]


def fake_store(rows):
    """Patch store._open to serve `rows` under the real headers."""
    ws = FakeWS([HEAD] + rows)
    return mock.patch.object(S, "_open", lambda *a, **k: (None, ws)), ws


class MMDD(unittest.TestCase):
    def test_every_shape_blueink_produces(self):
        for raw in ("6/28/2004", "06-28-04", "2004-06-28", " 6/28/2004 "):
            self.assertEqual(S.mmdd(raw), "06/28", raw)

    def test_leap_day_is_a_real_birthday_and_survives(self):
        """02/29 must validate. The check year is 2024 precisely so it does."""
        self.assertEqual(S.mmdd("2/29/2000"), "02/29")

    def test_a_transposed_date_is_refused_not_stored_wrong(self):
        """'28/06/2004' as D/M would store month 28. A birthday we admit we
        don't have beats one quietly landing on the wrong day."""
        self.assertEqual(S.mmdd("28/06/2004"), "")
        self.assertEqual(S.mmdd("13/40/2000"), "")

    def test_junk_is_empty_never_an_exception(self):
        for raw in ("", None, "nonsense", "6/28"):
            self.assertEqual(S.mmdd(raw), "")


class StoreReads(unittest.TestCase):
    def test_columns_are_found_by_label_not_index(self):
        """A column inserted by hand must not rot the read."""
        ws = FakeWS([["Notes", "Rep Name", "zzz", "Birthday (MM/DD)"],
                     ["n", "Ann Lee", "x", "06/28"]])
        with mock.patch.object(S, "_open", lambda *a, **k: (None, ws)):
            got = S.load()
        self.assertEqual([(e.name, e.mmdd) for e in got], [("Ann Lee", "06/28")])

    def test_a_missing_required_column_is_a_loud_error(self):
        ws = FakeWS([["Rep Name", "Notes"], ["Ann Lee", ""]])
        with mock.patch.object(S, "_open", lambda *a, **k: (None, ws)):
            with self.assertRaises(S.StoreError) as e:
                S.load()
        self.assertIn("Birthday (MM/DD)", str(e.exception))

    def test_blank_names_are_skipped_and_rows_are_numbered(self):
        patch, _ws = fake_store([["Ann Lee", "06/28", "", "", "", ""],
                                 ["", "", "", "", "", ""],
                                 ["Bob Cruz", "09/14", "", "", "", ""]])
        with patch:
            got = S.load()
        self.assertEqual([e.name for e in got], ["Ann Lee", "Bob Cruz"])
        self.assertEqual([e.row for e in got], [2, 4])

    def test_skip_column_opts_a_person_out(self):
        patch, _ws = fake_store([["Ann Lee", "09/14", "", "", "x", ""],
                                 ["Bob Cruz", "09/14", "", "", "", ""]])
        with patch:
            got = S.birthdays_on(S.load(), "09/14")
        self.assertEqual([e.name for e in got], ["Bob Cruz"])


class StoreWrites(unittest.TestCase):
    def test_append_skips_someone_already_on_the_tab(self):
        patch, ws = fake_store([["Ann Lee", "06/28", "", "", "", ""]])
        with patch:
            res = S.append([S.Entry(name="Ann\tLee", mmdd="06/28")], dry_run=False)
        self.assertEqual(res["added"], [])
        self.assertEqual(ws.appended, [])

    def test_a_disagreeing_birthday_is_a_conflict_never_an_overwrite(self):
        """Two different dates for one person is a question for a human."""
        patch, ws = fake_store([["Ann Lee", "06/28", "", "", "", ""]])
        with patch:
            res = S.append([S.Entry(name="Ann Lee", mmdd="07/01")], dry_run=False)
        self.assertEqual(res["conflicts"], [("Ann Lee", "06/28", "07/01")])
        self.assertEqual(ws.appended, [])

    def test_a_new_person_lands_in_the_labelled_columns(self):
        patch, ws = fake_store([])
        with patch:
            S.append([S.Entry(name="Bob Cruz", mmdd="09/14", source="blueink",
                              added="2026-09-13")], dry_run=False)
        self.assertEqual(ws.appended,
                         [["Bob Cruz", "09/14", "blueink", "2026-09-13", "", ""]])

    def test_dry_run_writes_nothing(self):
        patch, ws = fake_store([])
        with patch:
            res = S.append([S.Entry(name="Bob Cruz", mmdd="09/14")], dry_run=True)
        self.assertEqual(ws.appended, [])
        self.assertEqual(res["added"], ["Bob Cruz"])
        self.assertEqual(res["wrote"], 0)

    def test_a_batch_does_not_add_the_same_person_twice(self):
        patch, ws = fake_store([])
        with patch:
            S.append([S.Entry(name="Bob Cruz", mmdd="09/14"),
                      S.Entry(name="bob  cruz", mmdd="09/14")], dry_run=False)
        self.assertEqual(len(ws.appended), 1)

    def test_no_usable_birthday_is_skipped_not_written_blank(self):
        patch, ws = fake_store([])
        with patch:
            res = S.append([S.Entry(name="Bob Cruz", mmdd="")], dry_run=False)
        self.assertEqual(ws.appended, [])
        self.assertEqual(res["skipped"], [("Bob Cruz", "no usable birthday")])


WEEK = dt.date(2026, 9, 7)          # Monday of the week ending Sun 9/13


def live(**kw):
    base = dict(active=set(), contradicted=set(), terminated={},
                tab="Sales Board WE 9.13", week_start=WEEK)
    base.update(kw)
    return L.Liveness(**base)


class Suppression(unittest.TestCase):
    def test_on_the_board_unmarked_is_the_only_yes(self):
        self.assertTrue(live(active={"ann lee"}).verdict("Ann Lee").allowed)

    def test_absent_from_the_board_is_a_no_even_with_a_clean_record(self):
        """Absence from a terminated LIST is not evidence of anything -- it is
        also what a missed filing looks like. Presence on the board is."""
        v = live(active={"bob cruz"}).verdict("Ann Lee")
        self.assertFalse(v.allowed)
        self.assertIn("not on the current week's board", v.why)

    def test_a_rehire_back_on_the_board_is_allowed(self):
        """The case a `name in terminated` test gets wrong forever. 64 names on
        'Terminated Reps' hold more than one row -- Myra Singleton 7/31 and 8/3.
        A stale termination must not mute somebody who is working again."""
        v = live(active={"myra singleton"},
                 terminated={"myra singleton": dt.date(2026, 8, 3)}).verdict("Myra Singleton")
        self.assertTrue(v.allowed)

    def test_a_termination_filed_THIS_week_beats_the_board(self):
        """Board says working, tracker says gone, same week -> fail closed."""
        v = live(active={"ann lee"},
                 terminated={"ann lee": dt.date(2026, 9, 9)}).verdict("Ann Lee")
        self.assertFalse(v.allowed)
        self.assertIn("2026-09-09", v.why)

    def test_a_contradicted_row_is_skipped(self):
        """A Check means the board says both things at once."""
        v = live(active={"kaleb muvunyi"},
                 contradicted={"kaleb muvunyi"}).verdict("Kaleb Muvunyi")
        self.assertFalse(v.allowed)
        self.assertIn("contradicts", v.why)

    def test_a_degraded_read_allows_nobody(self):
        """An unsent reminder costs nothing; a wrong one costs an apology."""
        v = L.Liveness(degraded="sales board unreadable").verdict("Ann Lee")
        self.assertFalse(v.allowed)
        self.assertIn("couldn't verify", v.why)

    def test_names_match_through_tabs_nicknames_and_double_spaces(self):
        """122 of 2527 tracker rows carry a literal TAB inside the name and 310
        carry parentheses. Raw string equality would miss every one."""
        lv = live(active={"ann lee"})
        for spelling in ("Ann\tLee", "ann  lee", "Ann Lee (NC)", "ANN LEE",
                         "Ann\xa0Lee"):
            self.assertTrue(lv.verdict(spelling).allowed, spelling)

    def test_a_blank_name_is_never_allowed(self):
        self.assertFalse(live(active={""}).verdict("").allowed)

    def test_a_termination_with_no_date_still_vetoes_someone_absent(self):
        v = live(terminated={"ann lee": None}).verdict("Ann Lee")
        self.assertFalse(v.allowed)
        self.assertIn("(no date)", v.why)


class NonPersonRows(unittest.TestCase):
    """The board's 'still working' list is name CELLS, not just reps. Read live
    on WE 9.13 it held 169 rows, 10 of which were labels or team names."""

    def test_section_labels_and_team_names_are_not_people(self):
        for label in ("TOTALS", "% of Reps on the Board", "Goal", "Teams",
                      "Ceaseless", "Alphaletes", "Hashiras", "Zach's",
                      "Alphaletes Totals", ""):
            self.assertFalse(BF.is_person(label), label)

    def test_real_names_survive_including_the_messy_ones(self):
        for name in ("Alyssa Moreno", "Amjad Malhas",
                     "Oluwafeyisayo (Faye) Akinrinola", "Christian\tWilliams",
                     "Madison  (Mae)      Collis"):
            self.assertTrue(BF.is_person(name), name)


class SiteSource(unittest.TestCase):
    """The Sheet is being retired (Megan, 2026-09-13). The site roster answers
    the same question directly, so the swap must be a source choice only."""

    class FakeRep:
        def __init__(self, name, status="Active", terminated_on=""):
            self.name, self.status, self.terminated_on = name, status, terminated_on

        @property
        def is_terminated(self):
            return self.status == "Terminated"

    def test_a_seeded_roster_that_never_records_terminations_is_not_trusted(self):
        """Read live 2026-09-13: 61 reps on the site roster, ALL 'Active', while
        the board knew of 2453 terminations. Switching that day would have
        texted the exact people this report exists to skip."""
        reps = [self.FakeRep("Ann Lee"), self.FakeRep("Bob Cruz")]
        self.assertFalse(L.is_maintained(reps))
        sentinel = L.Liveness(active=set(), tab="Sales Board WE 9.13")
        with mock.patch.object(L, "site_roster", lambda *a, **k: reps), \
             mock.patch.object(L, "_from_sheet", lambda *a, **k: sentinel):
            got = L.read(dt.date(2026, 9, 13), logfn=lambda *a: None)
        self.assertIs(got, sentinel)

    def test_one_terminated_rep_is_the_evidence_the_roster_is_in_use(self):
        reps = [self.FakeRep("Ann Lee"),
                self.FakeRep("Gone Guy", "Terminated", "2026-01-02")]
        self.assertTrue(L.is_maintained(reps))
        with mock.patch.object(L, "site_roster", lambda *a, **k: reps), \
             mock.patch.object(L, "_from_sheet",
                               side_effect=AssertionError("read the sheet")):
            got = L.read(dt.date(2026, 9, 13), logfn=lambda *a: None)
        self.assertTrue(got.verdict("Ann Lee").allowed)
        self.assertFalse(got.verdict("Gone Guy").allowed)

    def test_the_site_roster_is_preferred_when_it_has_one(self):
        reps = [self.FakeRep("Ann Lee"),
                self.FakeRep("Gone Guy", "Terminated", "2026-01-02")]
        with mock.patch.object(L, "site_roster", lambda *a, **k: reps), \
             mock.patch.object(L, "_from_sheet",
                               side_effect=AssertionError("read the sheet")):
            got = L.read(dt.date(2026, 9, 13), logfn=lambda *a: None)
        self.assertTrue(got.verdict("Ann Lee").allowed)
        self.assertIn("site roster", got.tab)

    def test_it_falls_back_to_the_sheet_until_the_site_has_a_roster(self):
        sentinel = L.Liveness(active={"ann lee"}, tab="Sales Board WE 9.13")
        with mock.patch.object(L, "site_roster", lambda *a, **k: []), \
             mock.patch.object(L, "_from_sheet", lambda *a, **k: sentinel):
            got = L.read(dt.date(2026, 9, 13), logfn=lambda *a: None)
        self.assertIs(got, sentinel)

    def test_a_terminated_status_vetoes_and_carries_its_date(self):
        reps = [self.FakeRep("Ann Lee", "Terminated", "2026-06-01")]
        with mock.patch.object(L, "site_roster", lambda *a, **k: reps):
            v = L.read(dt.date(2026, 9, 13), logfn=lambda *a: None).verdict("Ann Lee")
        self.assertFalse(v.allowed)
        self.assertIn("2026-06-01", v.why)

    def test_being_OFF_today_does_not_cancel_your_birthday(self):
        """The site's NOT_IN_FIELD also covers OFF/O-NA/FFP -- right for 'did
        they roll a zero', wrong here. Only 'Terminated' vetoes.

        FFP is Megan's explicit call, 2026-09-13: "moving forward you will just
        get the DOB and won't have FFP so they can have a birthday alert."
        """
        for status in ("OFF", "O-NA", "FFP", "Roadtrip", "New Start", "STF"):
            reps = [self.FakeRep("Ann Lee", status),
                    self.FakeRep("Gone Guy", "Terminated", "2026-01-02")]
            with mock.patch.object(L, "site_roster", lambda *a, **k: reps):
                v = L.read(dt.date(2026, 9, 13), logfn=lambda *a: None).verdict("Ann Lee")
            self.assertTrue(v.allowed, status)

    def test_someone_absent_from_the_roster_is_still_refused(self):
        reps = [self.FakeRep("Bob Cruz"),
                self.FakeRep("Gone Guy", "Terminated", "2026-01-02")]
        with mock.patch.object(L, "site_roster", lambda *a, **k: reps):
            v = L.read(dt.date(2026, 9, 13), logfn=lambda *a: None).verdict("Ann Lee")
        self.assertFalse(v.allowed)

    def test_source_site_never_silently_reads_the_sheet(self):
        with mock.patch.object(L, "site_roster", lambda *a, **k: []), \
             mock.patch.object(L, "_from_sheet",
                               side_effect=AssertionError("read the sheet")):
            got = L.read(dt.date(2026, 9, 13), source="site", logfn=lambda *a: None)
        self.assertFalse(got.verdict("Ann Lee").allowed)
        self.assertIn("no roster", got.degraded)


class Message(unittest.TestCase):
    def test_one_name(self):
        got = R.compose(["Ann Lee"], dt.date(2026, 9, 14))
        self.assertIn("Birthday tomorrow (Monday 9/14): Ann Lee", got)

    def test_several_names_read_as_a_list(self):
        got = R.compose(["Ann Lee", "Bob Cruz"], dt.date(2026, 9, 14))
        self.assertIn("Birthdays tomorrow (Monday 9/14): Ann Lee, Bob Cruz", got)

    def test_the_emoji_is_a_real_character_not_a_shortcode(self):
        """iMessage renders ':cake:' literally."""
        got = R.compose(["Ann Lee"], dt.date(2026, 9, 14))
        self.assertIn("\U0001F382", got)
        self.assertNotIn(":cake:", got)

    def test_the_date_never_uses_a_windows_hostile_strftime(self):
        """'%-m' is a no-op on Windows and these run on both."""
        self.assertEqual(R._mdy(dt.date(2026, 1, 5)), "1/5")


class Planning(unittest.TestCase):
    def _plan(self, rows, liveness):
        patch, _ws = fake_store(rows)
        with patch, mock.patch.object(L, "read", lambda *a, **k: liveness):
            return R.plan(dt.date(2026, 9, 13), logfn=lambda *a: None)

    def test_tomorrows_birthday_with_a_working_rep_is_a_send(self):
        p = self._plan([["Ann Lee", "09/14", "", "", "", ""]],
                       live(active={"ann lee"}))
        self.assertEqual([v.name for v in p["send"]], ["Ann Lee"])
        self.assertIn("Ann Lee", p["text"])

    def test_a_terminated_rep_produces_a_skip_and_no_text(self):
        p = self._plan([["Ann Lee", "09/14", "", "", "", ""]],
                       live(active={"bob cruz"},
                            terminated={"ann lee": dt.date(2026, 6, 1)}))
        self.assertEqual(p["send"], [])
        self.assertEqual(p["text"], "")
        self.assertIn("terminated 2026-06-01", p["skip"][0].why)

    def test_todays_birthday_is_not_tomorrows(self):
        """The ping is the DAY BEFORE -- that is the whole point."""
        p = self._plan([["Ann Lee", "09/13", "", "", "", ""]],
                       live(active={"ann lee"}))
        self.assertEqual(p["send"], [])

    def test_an_opted_out_person_is_reported_not_silently_dropped(self):
        p = self._plan([["Ann Lee", "09/14", "", "", "no thanks", ""]],
                       live(active={"ann lee"}))
        self.assertEqual(p["send"], [])
        self.assertEqual(p["opted_out"], ["Ann Lee"])

    def test_no_birthdays_does_not_read_the_board_at_all(self):
        """Most days nobody has a birthday. Don't spend a board read on it."""
        patch, _ws = fake_store([["Ann Lee", "01/01", "", "", "", ""]])
        with patch, mock.patch.object(L, "read",
                                      side_effect=AssertionError("read the board")):
            p = R.plan(dt.date(2026, 9, 13), logfn=lambda *a: None)
        self.assertEqual(p["send"], [])


class Sending(unittest.TestCase):
    def _run(self, group, **kw):
        patch, _ws = fake_store([["Ann Lee", "09/14", "", "", "", ""]])
        with patch, \
             mock.patch.object(L, "read", lambda *a, **k: live(active={"ann lee"})), \
             mock.patch.object(C, "GROUP_ADMIN_STAFF", group), \
             mock.patch.object(R, "_publish", lambda *a, **k: None):
            return R.run(today=dt.date(2026, 9, 13), logfn=lambda *a: None, **kw)

    def test_no_configured_chat_refuses_rather_than_guessing(self):
        """Megan is still getting the chat name. Until then: no send, exit 1."""
        self.assertEqual(self._run(""), 1)

    def test_a_configured_chat_goes_through_text_post(self):
        from automations.b2b_dispositions import text_post
        with mock.patch.object(text_post, "send_text_to_group",
                               return_value={"resolved_name": "Admin Staff",
                                             "participants": 4}) as send:
            self.assertEqual(self._run("Admin Staff", dry_run=True), 0)
        self.assertEqual(send.call_args.args[0], "Admin Staff")
        self.assertTrue(send.call_args.kwargs["dry_run"])

    def test_a_chat_lucy_was_removed_from_is_a_loud_failure(self):
        from automations.b2b_dispositions import text_post
        with mock.patch.object(text_post, "send_text_to_group",
                               side_effect=text_post.GroupTextError("no group")):
            self.assertEqual(self._run("Admin Staff"), 1)


if __name__ == "__main__":
    unittest.main()
