"""Offline tests for the OwnerVille grid read. No browser, no network.

The stub page returns what the real one returns -- a header list and a list of
cell lists -- so these pin the part that turns a DataTables grid into rows: the
bit that has silently published 2 reps of 22 elsewhere in this repo.
"""
from __future__ import annotations

import datetime as dt
import re
import unittest

from automations.shared import ownerville_knocks as K


class _Page:
    """The two evaluate() shapes read_rows depends on, and nothing else."""

    def __init__(self, headers, rows):
        self.headers, self.rows = headers, rows

    def wait_for_function(self, *a, **kw):
        return None

    def wait_for_timeout(self, *a, **kw):
        return None

    def evaluate(self, script, *args):
        if "thead" in script:
            return list(self.headers)
        if "_processing" in script:
            return len(self.rows)
        if "tbody tr" in script:
            return [list(r) for r in self.rows]
        return []


class ReadRowsTests(unittest.TestCase):
    HEADERS = ["Rep", "Total Knocks", "No answer", "Sale"]

    def test_rows_are_keyed_by_the_grids_own_headers(self):
        page = _Page(self.HEADERS, [["Ana Griffin", "42", "30", "2"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertEqual(rows, [{"rep": "Ana Griffin", "total knocks": "42",
                                 "no answer": "30", "sale": "2"}])

    def test_blank_rows_are_dropped(self):
        """DataTables renders a 'no data available' row that is not a rep."""
        page = _Page(self.HEADERS, [["", "", "", ""],
                                    ["Ian Rodriguez", "10", "8", "1"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rep"], "Ian Rodriguez")

    def test_an_empty_day_is_rows_not_an_error(self):
        """Nobody has knocked yet is a real answer every single morning."""
        page = _Page(self.HEADERS, [])
        self.assertEqual(K.read_rows(page, log=lambda *_: None), [])

    def test_a_grid_that_never_built_is_an_error_not_an_empty_day(self):
        """No headers means the page is not the grid -- almost always a
        sign-in that did not go through. Reporting it as a quiet day is how an
        office silently stops having a board."""
        page = _Page([], [])
        with self.assertRaises(K.OwnervilleError):
            K.read_rows(page, log=lambda *_: None)

    def test_extra_cells_beyond_the_headers_do_not_crash(self):
        page = _Page(self.HEADERS, [["Ana", "1", "2", "3", "surprise"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertEqual(rows[0]["sale"], "3")

    def test_short_rows_do_not_crash(self):
        page = _Page(self.HEADERS, [["Ana", "1"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertEqual(rows[0], {"rep": "Ana", "total knocks": "1"})

    def test_headers_are_normalised_so_spacing_changes_do_not_break_us(self):
        page = _Page(["Rep", "Total   Knocks "], [["Ana", "5"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertIn("total knocks", rows[0])


class HeaderIndexTests(unittest.TestCase):
    def test_index_maps_normalised_header_to_position(self):
        page = _Page(["Rep", "Total Knocks", "Sale"], [])
        self.assertEqual(K.header_index(page),
                         {"rep": 0, "total knocks": 1, "sale": 2})

    def test_missing_table_yields_an_empty_index(self):
        self.assertEqual(K.header_index(_Page([], [])), {})


if __name__ == "__main__":
    unittest.main()


class CadenceTests(unittest.TestCase):
    """Per-destination cadence: the owners' room every 15 minutes and the rep
    channel once an hour is a normal answer, so 'is this due?' is a question
    about ONE room and its own last post."""

    def setUp(self):
        from automations.icd_alerts import knocks_post as KP
        self.KP = KP
        self.now = dt.datetime(2026, 9, 11, 15, 0)

    def test_never_posted_is_due(self):
        """So an approval takes effect on the next tick, not an hour later."""
        self.assertTrue(self.KP.is_due({"cadence_min": 60}, None, self.now))

    def test_interval_waits_its_full_cadence(self):
        last = self.now - dt.timedelta(minutes=45)
        self.assertFalse(self.KP.is_due({"cadence_min": 60}, last, self.now))
        self.assertTrue(self.KP.is_due({"cadence_min": 30}, last, self.now))

    def test_two_rooms_on_one_office_are_judged_separately(self):
        last_hourly = self.now - dt.timedelta(minutes=20)
        self.assertTrue(self.KP.is_due({"cadence_min": 15}, last_hourly, self.now))
        self.assertFalse(self.KP.is_due({"cadence_min": 60}, last_hourly, self.now))

    def test_fixed_times_fire_just_after_a_slot(self):
        at_slot = dt.datetime(2026, 9, 11, 14, 5)
        self.assertTrue(self.KP.is_due({"cadence_min": 0}, None, at_slot))

    def test_fixed_times_do_not_fire_twice_for_one_slot(self):
        at_slot = dt.datetime(2026, 9, 11, 14, 5)
        already = dt.datetime(2026, 9, 11, 14, 1)
        self.assertFalse(self.KP.is_due({"cadence_min": 0}, already, at_slot))

    def test_fixed_times_are_quiet_between_slots(self):
        between = dt.datetime(2026, 9, 11, 16, 0)
        self.assertFalse(self.KP.is_due({"cadence_min": 0}, None, between))


class FieldHoursTests(unittest.TestCase):
    def setUp(self):
        from automations.icd_alerts import knocks_post as KP
        from automations.icd_alerts import offices as O
        self.KP, self.office = KP, O.get("kash")

    def test_sunday_is_off_for_everyone(self):
        self.assertFalse(self.KP.in_field_hours(
            self.office, dt.datetime(2026, 9, 13, 15, 0)))

    def test_a_weekday_afternoon_is_in(self):
        self.assertTrue(self.KP.in_field_hours(
            self.office, dt.datetime(2026, 9, 11, 15, 0)))

    def test_a_weekday_morning_is_out(self):
        self.assertFalse(self.KP.in_field_hours(
            self.office, dt.datetime(2026, 9, 11, 9, 0)))

    def test_saturday_ends_earlier_than_a_weekday(self):
        self.assertTrue(self.KP.in_field_hours(
            self.office, dt.datetime(2026, 9, 12, 17, 0)))
        self.assertFalse(self.KP.in_field_hours(
            self.office, dt.datetime(2026, 9, 12, 21, 0)))


class ClockTests(unittest.TestCase):
    def test_twelve_hour_clock_without_a_gnu_extension(self):
        from automations.icd_alerts.knocks_post import _clock
        self.assertEqual(_clock(dt.datetime(2026, 9, 11, 20, 5)), "8:05 PM")
        self.assertEqual(_clock(dt.datetime(2026, 9, 11, 0, 30)), "12:30 AM")
        self.assertEqual(_clock(dt.datetime(2026, 9, 11, 12, 0)), "12:00 PM")


class MapTests(unittest.TestCase):
    """The re-key is the part that decides WHICH BOARD gets drawn, because
    knocks_shape() reads the row's KEYS. Flattening every office onto one
    fixed set of fields would draw a plausible-looking board with every
    disposition blank."""

    FIBER = {"id": "101", "rep": "Ana Griffin", "total knocks": "42",
             "no answer": "30", "talk to - not interested": "5",
             "presentation – not interested": "2", "come back": "3",
             "sale": "2", "do not knock": "0", "first knock": "1:35 PM",
             "last knock": "7:42 PM"}
    WIRELESS = {"id": "201", "rep": "Ian", "total knocks": "20",
                "no answer": "10", "not interested": "4", "come back": "2",
                "first knock": "2:00 PM", "last knock": "8:00 PM"}

    def setUp(self):
        from automations.icd_alerts import knocks_map as M
        from automations.total_knocks import pull as TP
        self.M, self.TP = M, TP

    def test_a_fiber_office_reads_as_the_house_board(self):
        self.assertEqual(self.M.shape_of(self.M.to_rows([self.FIBER])), "house")

    def test_a_wireless_office_keeps_its_own_shape(self):
        self.assertEqual(self.M.shape_of(self.M.to_rows([self.WIRELESS])),
                         "wireless")

    def test_total_talk_to_is_calculated_for_the_split(self):
        row = self.M.to_rows([self.FIBER])[0]
        self.assertEqual(row[self.TP.COL_TOTAL_TALK_TO], 12)

    def test_total_talk_to_is_NOT_invented_without_the_split(self):
        """A wireless grid has Come Back and none of the other four. Summing
        'the parts that happen to be here' publishes a number that is wrong in
        the believable direction."""
        row = self.M.to_rows([self.WIRELESS])[0]
        self.assertNotIn(self.TP.COL_TOTAL_TALK_TO, row)

    def test_counts_become_ints_and_times_stay_text(self):
        row = self.M.to_rows([self.FIBER])[0]
        self.assertEqual(row[self.TP.COL_TOTAL_KNOCKS], 42)
        self.assertEqual(row[self.TP.COL_FIRST_KNOCK], "1:35 PM")

    def test_gaps_merge_by_badge_id(self):
        rows = self.M.to_rows(
            [self.FIBER], [{"id": "101", "gaps": "3", "totalGapMinutes": 47}])
        self.assertEqual(rows[0][self.TP.COL_GAPS], 3)
        self.assertEqual(rows[0][self.TP.COL_TOTAL_GAPS], 47)

    def test_a_rep_with_no_tracker_row_keeps_gaps_BLANK_not_zero(self):
        """'Did not clock in' and 'stood still for zero minutes' are different
        facts, and the board draws them differently."""
        rows = self.M.to_rows([self.FIBER], [{"id": "999", "gaps": "1"}])
        self.assertNotIn(self.TP.COL_GAPS, rows[0])

    def test_a_totals_line_is_not_a_person(self):
        rows = self.M.to_rows([self.FIBER, {"rep": "TOTAL", "total knocks": "42"}])
        self.assertEqual(len(rows), 1)

    def test_gaps_phrase_is_parsed_as_a_count(self):
        self.assertEqual(self.M._gaps_count("3 gaps"), 3)
        self.assertEqual(self.M._gaps_count(""), 0)


class EmptyGridTests(unittest.TestCase):
    """DataTables' empty state is ONE cell spanning the table, carrying real
    text. An all-cells-blank test misses it and it arrives looking exactly
    like a rep whose name is that sentence -- read off the live grid on a
    legitimately quiet morning, 2026-09-11."""

    HEADERS = ["ID", "Rep", "Total Knocks", "No answer", "Sale", "Come Back"]

    def test_the_empty_state_row_is_not_a_rep(self):
        page = _Page(self.HEADERS, [["No data available in table"]])
        self.assertEqual(K.read_rows(page, log=lambda *_: None), [])

    def test_other_empty_state_wordings_too(self):
        for text in ("No matching records found", "No records found",
                     "Nothing found"):
            page = _Page(self.HEADERS, [[text]])
            self.assertEqual(K.read_rows(page, log=lambda *_: None), [], text)

    def test_a_real_short_row_is_still_kept(self):
        """A genuine rep row that happens to be short must survive."""
        page = _Page(self.HEADERS, [["7", "Ana Griffin", "12"]])
        rows = K.read_rows(page, log=lambda *_: None)
        self.assertEqual(rows[0]["rep"], "Ana Griffin")

    def test_a_full_width_row_is_never_second_guessed(self):
        page = _Page(self.HEADERS, [["7", "No answer", "1", "2", "3", "4"]])
        self.assertEqual(len(K.read_rows(page, log=lambda *_: None)), 1)


class PerOfficeHoursTests(unittest.TestCase):
    """Each office carries its own window. A single org-wide one posted into
    both of these offices' quiet time (Megan supplied the real hours
    2026-09-12): Kash's Saturday starts 45 minutes earlier than Cyrus's and
    ends an hour later."""

    def setUp(self):
        from automations.icd_alerts import offices as O
        self.O, self.kash, self.cyrus = O, O.get("kash"), O.get("cyrus")

    def test_weekday_window_is_shared_and_ends_at_830(self):
        for o in (self.kash, self.cyrus):
            self.assertTrue(self.O.in_field_hours(o, dt.datetime(2026, 9, 11, 13, 30)))
            self.assertTrue(self.O.in_field_hours(o, dt.datetime(2026, 9, 11, 20, 30)))
            self.assertFalse(self.O.in_field_hours(o, dt.datetime(2026, 9, 11, 20, 31)))
            self.assertFalse(self.O.in_field_hours(o, dt.datetime(2026, 9, 11, 13, 29)))

    def test_saturdays_genuinely_differ(self):
        early = dt.datetime(2026, 9, 12, 10, 30)      # Kash in, Cyrus not yet
        late = dt.datetime(2026, 9, 12, 16, 30)       # Kash in, Cyrus done
        self.assertTrue(self.O.in_field_hours(self.kash, early))
        self.assertFalse(self.O.in_field_hours(self.cyrus, early))
        self.assertTrue(self.O.in_field_hours(self.kash, late))
        self.assertFalse(self.O.in_field_hours(self.cyrus, late))

    def test_sunday_is_off_for_everyone(self):
        for o in (self.kash, self.cyrus):
            self.assertFalse(self.O.in_field_hours(o, dt.datetime(2026, 9, 13, 15, 0)))

    def test_the_board_asks_the_same_question_as_the_roster(self):
        """knocks_post must not keep its own idea of when an office is out."""
        from automations.icd_alerts import knocks_post as KP
        when = dt.datetime(2026, 9, 12, 16, 30)
        self.assertEqual(KP.in_field_hours(self.cyrus, when),
                         self.O.in_field_hours(self.cyrus, when))


class FirstKnockGreenTests(unittest.TestCase):
    """First knock goes green against the OFFICE's start, on THAT day.

    A flat 1:30 PM target greened every Saturday first-knock on every board,
    because no office starts at 1:30 on a Saturday (Megan 2026-09-12: "if the
    office is set to start at 10:15 then first knock being green at 10:15 or
    sooner")."""

    def setUp(self):
        from automations.total_knocks import render as R
        from automations.icd_alerts import offices as O
        self.R, self.O = R, O
        self.sat, self.fri = dt.date(2026, 9, 12), dt.date(2026, 9, 11)

    def test_saturday_uses_the_saturday_start(self):
        self.assertEqual(self.R.first_knock_target(self.O.get("kash"), self.sat),
                         10 * 60 + 30)
        self.assertEqual(self.R.first_knock_target(self.O.get("cyrus"), self.sat),
                         11 * 60 + 15)

    def test_weekdays_use_the_weekday_start(self):
        for key in ("kash", "cyrus"):
            self.assertEqual(
                self.R.first_knock_target(self.O.get(key), self.fri), 13 * 60 + 30)

    def test_an_office_with_no_hours_keeps_the_old_flat_target(self):
        """Every board we do not hold hours for must be unchanged."""
        self.assertEqual(self.R.first_knock_target(None, self.sat),
                         self.R.FIRST_KNOCK_TARGET_MIN)

    def test_a_malformed_start_falls_back_rather_than_crashing(self):
        from automations.icd_alerts.offices import AlertOffice, Channel
        bad = AlertOffice(key="x", owner="O", label="X", channels=(),
                          timezone="America/Chicago", sat_start="not a time")
        self.assertEqual(self.R.first_knock_target(bad, self.sat),
                         self.R.FIRST_KNOCK_TARGET_MIN)


class DoubleBoardTests(unittest.TestCase):
    """An office posting its own board from its own laptop must drop off the
    9 PM end-of-day roster, or its channel gets two boards -- the collision
    that put two in #alphalete-lvl1-chat four minutes apart on 9/3."""

    def test_an_approved_icd_channel_counts_as_already_served(self):
        from automations.knocks_intraday import roster
        from automations.icd_alerts import offices as O
        taken = roster.disposition_channels()
        for key in ("kash", "cyrus"):
            # Only meaningful once that office has been approved somewhere.
            from automations.icd_alerts import post as P
            dests = (P.approved_knocks() or {}).get(key) or []
            for d in dests:
                self.assertIn(d["channel_id"], taken, key)

    def test_the_eod_roster_excludes_them(self):
        from automations.knocks_intraday import roster
        from automations.icd_alerts import post as P
        keys = [getattr(o, "key", o) for o in roster.enrolled("eod")]
        for key in ("kash", "cyrus"):
            if (P.approved_knocks() or {}).get(key):
                self.assertNotIn(key, keys, key)


class ShippedClosureTests(unittest.TestCase):
    """Every module the agent imports must actually be in the package.

    sale_hype.py was not, and it imports LAZILY inside read_day -- so the
    package imported cleanly and would have failed at sweep time on someone
    else's laptop, which is the worst place to find out (2026-09-12)."""

    def test_every_import_the_agent_makes_is_shipped(self):
        import ast
        from pathlib import Path
        from automations.icd_alerts.package import AGENT_FILES
        shipped = set(AGENT_FILES)
        # The builder writes these two itself rather than copying them.
        shipped |= {"automations/__init__.py",
                    "automations/shared/__init__.py"}
        repo = Path(__file__).resolve().parents[2]

        def wanted(module, names):
            """Every repo path an import statement could be reaching for."""
            out = []
            if module and module.startswith("automations"):
                base = module.replace(".", "/")
                out.append(base + ".py")                  # a module
                out.append(base + "/__init__.py")         # a package
                for n in names:                           # from pkg import mod
                    out.append("%s/%s.py" % (base, n))
            return out

        missing = []
        for rel in AGENT_FILES:
            tree = ast.parse((repo / rel).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    paths = wanted(node.module or "",
                                   [a.name for a in node.names])
                elif isinstance(node, ast.Import):
                    paths = []
                    for a in node.names:
                        paths += wanted(a.name, [])
                else:
                    continue
                if paths and not any(q in shipped for q in paths):
                    missing.append((rel, paths[0]))
        self.assertEqual(sorted(set(missing)), [],
                         "shipped code imports something not in the package")

    def test_the_sale_module_specifically_is_shipped(self):
        from automations.icd_alerts.package import AGENT_FILES
        self.assertIn("automations/shared/sale_hype.py", AGENT_FILES)


class UpdateScriptTests(unittest.TestCase):
    """update.sh carries a HARDCODED file list, generated from AGENT_FILES.
    It went stale the moment a file was added to the package and not to it --
    the update ran, said "up to date", and left the machine without the module
    it needed (2026-09-12)."""

    def _script(self):
        from pathlib import Path
        return (Path(__file__).resolve().parent / "update.sh").read_text()

    def test_the_manifest_matches_what_the_package_ships(self):
        from pathlib import Path
        from automations.icd_alerts.package import AGENT_FILES
        txt = (Path(__file__).resolve().parent / "agent_files.txt").read_text()
        listed = [l.strip() for l in txt.splitlines()
                  if l.strip() and not l.startswith("#")]
        self.assertEqual(set(listed), set(AGENT_FILES),
                         "agent_files.txt has drifted from the package")

    def test_the_script_carries_no_baked_in_list(self):
        """A list inside the script goes stale behind GitHub's CDN cache, and
        a stale update reports success while installing the wrong thing."""
        self.assertNotIn('FILES=(', self._script())
        self.assertIn("agent_files.txt", self._script())

    def test_every_fetch_busts_the_cache(self):
        self.assertIn("?t=$BUST", self._script())

    def test_it_refuses_when_lucy_is_not_installed(self):
        self.assertIn("is not installed on this computer", self._script())

    def test_it_proves_the_agent_still_starts(self):
        """A syntax error in a file we just replaced would otherwise show up
        as silence at the next tick."""
        self.assertIn("import automations.icd_alerts.run", self._script())

    def test_a_failed_download_does_not_half_replace_a_file(self):
        self.assertIn(".new", self._script())


class RafsBoardUnchangedTests(unittest.TestCase):
    """Raf's reports must not change (Megan 2026-09-12). Everything the ICD
    boards needed was added as an opt-in with the old behaviour as default, so
    a caller that passes nothing gets exactly what it got before."""

    def test_the_first_knock_target_is_unchanged_without_an_office(self):
        from automations.total_knocks import render as R
        self.assertEqual(R.first_knock_target(None, dt.date(2026, 9, 12)),
                         R.FIRST_KNOCK_TARGET_MIN)

    def test_the_new_render_argument_defaults_to_off(self):
        import inspect
        from automations.total_knocks import render as R
        for fn in (R.render_knocks_boards, R.render_total_knocks):
            self.assertIsNone(
                inspect.signature(fn).parameters["first_knock_green_at"].default,
                fn.__name__)

    def test_rafs_first_knock_follows_his_own_saturday(self):
        """The ONE change his board gets (Megan 2026-09-12): first knock, not
        the knock count. A flat 1:30 PM greened every Saturday first-knock,
        because his Saturday starts at 10:45."""
        import datetime as dt
        from automations.gap_alerts.run import _first_knock_goal
        self.assertEqual(_first_knock_goal(dt.date(2026, 9, 11)), 13 * 60 + 30)
        self.assertEqual(_first_knock_goal(dt.date(2026, 9, 12)), 10 * 60 + 45)

    def test_a_day_with_no_window_invents_no_target(self):
        import datetime as dt
        from automations.gap_alerts.run import _first_knock_goal
        self.assertIsNone(_first_knock_goal(dt.date(2026, 9, 13)))

    def test_the_board_and_the_capture_read_the_same_window(self):
        """They must not disagree about when Saturday starts."""
        import datetime as dt
        from automations.gap_alerts import config as C
        from automations.gap_alerts.run import _first_knock_goal
        (h, m), _ = C.window_for(5)
        self.assertEqual(_first_knock_goal(dt.date(2026, 9, 12)), h * 60 + m)

    def test_rafs_knock_target_is_a_flat_140(self):
        """Megan 2026-09-12: "knock count stays the same". The renderer's
        default varies by day; this explicit value overrides it on purpose,
        and was briefly changed to None on the mistaken belief that the flat
        number was a leftover."""
        from automations.gap_alerts import config as C
        self.assertEqual(C.KNOCKS_GREEN_AT, 140)

    def test_raf_keeps_his_9pm_board(self):
        """The dedupe drops offices that post their OWN board. Raf does not."""
        from automations.knocks_intraday import roster
        keys = [getattr(o, "key", o) for o in roster.enrolled("eod")]
        self.assertIn("raf", keys)


class ChanComparisonTests(unittest.TestCase):
    """Chan's LAST week on an ICD board. His same-day line is impossible
    there: the numbers come off the office's own laptop, which cannot see his
    office at all. Raf set the shape (via Megan 2026-09-12): "Saturday to
    Saturday. And then Monday - Friday it can just be chans avg for Monday -
    Friday." """

    def setUp(self):
        from automations.icd_alerts import chan
        self.chan = chan

    def test_a_week_runs_monday_to_saturday(self):
        # Any day this week compares to the week that ended the prior Saturday.
        for d in (dt.date(2026, 9, 7), dt.date(2026, 9, 11), dt.date(2026, 9, 12)):
            self.assertEqual(self.chan.last_week_saturday(d), dt.date(2026, 9, 5))

    def test_sunday_belongs_to_the_week_that_just_ended(self):
        self.assertEqual(self.chan.last_week_saturday(dt.date(2026, 9, 13)),
                         dt.date(2026, 9, 5))

    def test_monday_moves_on_to_the_new_week(self):
        self.assertEqual(self.chan.last_week_saturday(dt.date(2026, 9, 14)),
                         dt.date(2026, 9, 12))

    def test_the_weekday_average_divides_by_the_days_actually_pulled(self):
        """A week missing Wednesday must average over four days, not five --
        dividing by five would quietly report Chan 20% slower than he was."""
        from automations.total_knocks import pull as TP
        by_day = {"2026-08-31": [{TP.COL_TOTAL_KNOCKS: 100}],
                  "2026-09-01": [{TP.COL_TOTAL_KNOCKS: 200}],
                  "2026-09-03": [{TP.COL_TOTAL_KNOCKS: 300}]}
        days = ["2026-08-31", "2026-09-01", "2026-09-02",
                "2026-09-03", "2026-09-04"]
        rows = self.chan._average_rows(by_day, days)
        self.assertEqual(rows[0][TP.COL_TOTAL_KNOCKS], 200)   # 600 / 3

    def test_an_empty_week_averages_to_nothing_rather_than_zero(self):
        """A zero line would read as 'Chan knocked nothing', which is a claim.
        No line at all is the truth: we do not have his week."""
        self.assertEqual(self.chan._average_rows({}, ["2026-09-01"]), [])

    def test_the_label_says_which_period_it_is(self):
        """A comparison whose period is ambiguous is read as today's."""
        self.assertIn("Sat", self.chan.LABEL_SAT)
        self.assertIn("M-F", self.chan.LABEL_WEEK)

    def test_the_posting_path_never_pulls(self):
        """The poster holds a lock and the boards queue behind it. A cold
        cache must cost the comparison line, not a twenty-minute-late board --
        and the first tick after a deploy is exactly when it is cold."""
        import inspect
        from automations.icd_alerts import chan
        src = inspect.getsource(chan.comparison_for)
        self.assertNotIn("pull=True", src)
        # _week only pulls when explicitly asked.
        self.assertIn("if not pull:", inspect.getsource(chan._week))

    def test_warming_is_its_own_command(self):
        from automations.icd_alerts import chan
        self.assertTrue(callable(chan.warm))
