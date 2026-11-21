"""python -m unittest automations.raf_daily_update.test_day1"""
import datetime as dt
import unittest

from automations.raf_daily_update import day1 as D
from automations.raf_daily_update import layout as L
from automations.raf_daily_update.test_layout import HDR


def obcl_grid(rows):
    """One OBCL block: a date in col A, then a header, then the rows."""
    g = [["11/9/2026"],
         ["Name", "Last Name", "2nd Round Interviewer", "Final Status"]]
    for first, last, status in rows:
        g.append([first, last, "Hank Tran", status])
    return g


def tab(rows):
    """A month tab: HDR plus rows keyed the way layout.resolve names them."""
    lay = L.resolve(HDR)
    grid = [HDR]
    for r in rows:
        raw = [""] * 14
        for k, v in r.items():
            raw[lay[k]] = v
        grid.append(raw)
    return grid, lay


class ShowedMap(unittest.TestCase):
    def test_megans_rule_is_not_restated_here(self):
        m = D.showed_map(obcl_grid([
            ("Mirsha", "Ruiz", "Showed Up To CR"),
            ("Juan", "Meneses", "Owner submitted"),
            ("Stacy", "Alberty", "Terminated"),
            ("Trevor", "Woods", "No Show"),
            ("Alex", "Bastias", ""),
        ]))
        # owner submitted + terminated both showed (Megan, 2026-10-01)
        self.assertEqual(m["mirsha ruiz"], "YES")
        self.assertEqual(m["juan meneses"], "YES")
        self.assertEqual(m["stacy alberty"], "YES")
        self.assertEqual(m["trevor woods"], "NO")
        # undecided is ABSENT, not a NO — the sweep must leave it blank
        self.assertNotIn("alex bastias", m)

    def test_a_showed_week_beats_an_earlier_no_show(self):
        m = D.showed_map(obcl_grid([("Ever", "Teran", "No Show"),
                                    ("Ever", "Teran", "Owner submitted")]))
        self.assertEqual(m["ever teran"], "YES")


class Pending(unittest.TestCase):
    TODAY = dt.date(2026, 11, 20)

    def rows(self, extra=None):
        base = [
            # a BOB whose start has passed, K empty -> owed
            {"date": "11/2/26", "first": "Mirsha", "last": "Ruiz",
             "status": "BOB", "bob_date": "11/9"},
            # start still ahead -> not owed yet
            {"date": "11/18/26", "first": "Later", "last": "Start",
             "status": "BOB", "bob_date": "11/25"},
            # K already typed -> never touched
            {"date": "11/2/26", "first": "Typed", "last": "Already",
             "status": "BOB", "bob_date": "11/9", "day1": "YES"},
            # not a BOB -> no start day at all
            {"date": "11/2/26", "first": "Said", "last": "No",
             "status": "Leader said no: issues with schedule"},
            {"date": "11/2/26", "first": "Never", "last": "Came",
             "status": "NO SHOW"},
        ]
        return base + (extra or [])

    def test_only_started_bobs_with_an_empty_cell(self):
        grid, lay = tab(self.rows())
        got = [(n, name) for n, name, _ in
               D.pending(grid, lay, 2026, self.TODAY)]
        self.assertEqual(got, [(2, "Mirsha Ruiz")])

    def test_a_bob_with_no_start_date_is_not_owed(self):
        grid, lay = tab(self.rows([
            {"date": "11/2/26", "first": "No", "last": "Date",
             "status": "BOB", "bob_date": ""}]))
        self.assertNotIn("No Date",
                         [n for _, n, _ in D.pending(grid, lay, 2026, self.TODAY)])


class StartDate(unittest.TestCase):
    def test_a_january_start_from_a_december_interview(self):
        # the tab is December's; '1/4' means next January, not ten months ago
        self.assertEqual(D.start_date("1/4", dt.date(2026, 12, 28)),
                         dt.date(2027, 1, 4))

    def test_the_ordinary_case_keeps_the_tabs_year(self):
        self.assertEqual(D.start_date("11/9", dt.date(2026, 11, 2)),
                         dt.date(2026, 11, 9))
        self.assertIsNone(D.start_date("", dt.date(2026, 11, 2)))

    def test_a_next_year_start_is_not_owed_an_answer_yet(self):
        grid, lay = tab([{"date": "12/28/26", "first": "Mayely",
                          "last": "Becerra", "status": "BOB",
                          "bob_date": "1/4"}])
        self.assertEqual(D.pending(grid, lay, 2026, dt.date(2026, 11, 20)), [])


class ClassroomNames(unittest.TestCase):
    def test_a_blank_trainer_still_counts_as_attendance(self):
        # the row's EXISTENCE is the attendance; classroom_trainers drops
        # these, which is why this sweep does not reuse it
        grid = [["", "", ""],
                ["Classroom", "Trainers", ""],
                ["Lioney Garcia", "", ""],
                ["Miguel Govea", "Benjamin Kushpit", ""],
                ["", "", ""]]
        self.assertEqual(D.classroom_names(grid),
                         ["lioney garcia", "miguel govea"])

    def test_the_boards_week_tag_comes_off(self):
        # 'Lioney Garcia (Wk 2)' on the board is 'Lioney Garcia' on the sheet
        grid = [["Classroom", "Trainers"], ["Lioney Garcia (Wk 2)", "B K"]]
        self.assertEqual(D.classroom_names(grid), ["lioney garcia"])
        self.assertEqual(D._fold("Lioney Garcia"), "lioney garcia")

    def test_no_block_is_no_names_not_a_crash(self):
        self.assertEqual(D.classroom_names([["Name", "Week"], ["a", "b"]]), [])


class ShortKey(unittest.TestCase):
    def test_a_second_surname_and_an_accent_do_not_make_a_stranger(self):
        # WE 11.15 board 'Mirsha Ruiz Gómez' = sheet 'Mirsha Ruiz'
        self.assertEqual(D.short_key("Mirsha Ruiz Gómez"), "mirsha|ruiz")
        self.assertEqual(D.short_key("Mirsha Ruiz"), "mirsha|ruiz")
        self.assertEqual(D.short_key("Juan Meneses Landinez"), "juan|meneses")

    def test_a_typo_is_still_a_miss(self):
        # 'Trevor Wooda' vs 'Trevor Woods': obviously one person, and we
        # still refuse to say so rather than risk merging two real people
        self.assertNotEqual(D.short_key("Trevor Wooda"),
                            D.short_key("Trevor Woods"))

    def test_one_word_has_no_short_key(self):
        self.assertEqual(D.short_key("Madonna"), "")
        self.assertEqual(D.short_key(""), "")

    def test_the_short_key_finds_the_longer_board_name(self):
        ans = D.index({"mirsha ruiz gómez": "YES"})
        self.assertEqual(D.look_up(ans, "Mirsha Ruiz"), "YES")
        self.assertEqual(D.look_up(ans, "Trevor Woods"), "")

    def test_a_shared_short_key_is_dropped_not_guessed(self):
        ans = D.index({"maria garcia lopez": "YES", "maria garcia ruiz": "NO"})
        self.assertEqual(D.look_up(ans, "Maria Garcia"), "")
        # but two spellings that AGREE are still usable
        ans = D.index({"maria garcia lopez": "YES", "maria garcia ruiz": "YES"})
        self.assertEqual(D.look_up(ans, "Maria Garcia"), "YES")

    def test_a_full_name_match_wins_over_the_short_key(self):
        ans = D.index({"mirsha ruiz": "NO", "mirsha ruiz gómez": "YES"})
        self.assertEqual(D.look_up(ans, "Mirsha Ruiz"), "NO")


class BoardWinsOverTheObcl(unittest.TestCase):
    def test_the_register_beats_a_stale_status(self):
        # Megan 2026-10-01: on the board = attended, whatever else is marked
        grid, lay = tab([{"date": "11/2/26", "first": "Lioney",
                          "last": "Garcia", "status": "BOB",
                          "bob_date": "11/9"}])
        owed = D.pending(grid, lay, 2026, dt.date(2026, 11, 20))
        self.assertEqual(len(owed), 1)
        obcl = D.showed_map(obcl_grid([("Lioney", "Garcia", "No Show")]))
        self.assertEqual(obcl["lioney garcia"], "NO")
        merged = dict(obcl)
        merged.update({"lioney garcia": "YES"})     # read_board's layer
        self.assertEqual(merged["lioney garcia"], "YES")


class Months(unittest.TestCase):
    def test_the_month_before_is_swept_too(self):
        # someone interviewed 10/30 starts in November; their row is October's
        self.assertEqual(D._months(dt.date(2026, 11, 20)),
                         [dt.date(2026, 10, 1), dt.date(2026, 11, 1)])
        self.assertEqual(D._months(dt.date(2026, 1, 4)),
                         [dt.date(2025, 12, 1), dt.date(2026, 1, 1)])


class RidesTheReadQuota(unittest.TestCase):
    """2026-11-21: the 5pm sweep died on a Sheets 429 straight after Raf's
    Daily Update spent the account's per-minute reads. It now waits longer
    and runs the (fill-empty-only) sweep again."""

    QUOTA = RuntimeError("APIError: [429]: Quota exceeded for quota metric "
                         "'Read requests' and limit 'Read requests per minute "
                         "per user'")

    def _run(self, outcomes):
        from unittest import mock
        calls, slept = [], []

        def fake_sweep(*a, **k):
            calls.append(a)
            out = outcomes[len(calls) - 1]
            if isinstance(out, Exception):
                raise out
            return out

        with mock.patch.object(D, "sweep", fake_sweep):
            try:
                n = D.sweep_riding_quota("sid", dt.date(2026, 11, 1), True,
                                         waits=(120, 240), sleep=slept.append)
            except Exception as e:  # noqa: BLE001
                n = e
        return n, calls, slept

    def test_quota_then_clean_fills(self):
        n, calls, slept = self._run([self.QUOTA, 7])
        self.assertEqual(n, 7)
        self.assertEqual(slept, [120])

    def test_quota_every_time_still_fails(self):
        n, calls, slept = self._run([self.QUOTA] * 3)
        self.assertIsInstance(n, RuntimeError)
        self.assertEqual(len(calls), 3)
        self.assertEqual(slept, [120, 240])

    def test_other_errors_are_not_retried(self):
        n, calls, slept = self._run([KeyError("no tab"), 1])
        self.assertIsInstance(n, KeyError)
        self.assertEqual(len(calls), 1)
        self.assertEqual(slept, [])


if __name__ == "__main__":
    unittest.main()
