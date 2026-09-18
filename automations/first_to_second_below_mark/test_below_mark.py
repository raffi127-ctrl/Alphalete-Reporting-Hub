"""Pins the things that would silently break this report.

    python -m unittest automations.first_to_second_below_mark.test_below_mark

Everything here is offline: the weekly boxes are built as fixtures, so the
geometry is exercised without opening a Sheet.

The four hazards:
 1. Both source tabs move their weekly boxes DOWN every week, so every lookup
    keys off marker text, never a row number -- and the retention tab's two
    column labels are swapped ('INTERVIEWER' holds the owner).
 2. The two tabs label the SAME week seven days apart (9/13 vs 9/20).
 3. 'Qualified' is a column header TWICE, once per group.
 4. Exactly 40% has to read RED, which only holds while the <=40% rule is added
    ahead of the >=40% one.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import unittest

from automations.first_to_second_below_mark import ars_reports as ars
from automations.first_to_second_below_mark import columns as cols
from automations.first_to_second_below_mark import run as rep
from automations.first_to_second_below_mark import source as src


# ------------------------------------------------------- retention tab fixture
def _block(week: str, rows):
    """One weekly box shaped exactly like the retention tab writes it."""
    head = [week, "", " INTERVIEWERS RETENTION (Interviewers breakdown)"] + [""] * 14
    sub = ["", "OFFICE", "WEEKLY TOTAL"] + [""] * 14
    cols_row = ["INTERVIEWER", "", "QUALIFIED", "DISQUALIFIED", "DECLINED",
                "QUALIFIED %", "Qualified % GOAL", "ANSWERED & BOOKED",
                "ANSWER BOOKED %", "CONVERTION", "1st to 2nd booked %",
                "Goal For 1st to 2nd booked %", "2nd R BOOKED", "2nd R SHOWED",
                "2nd SHOWED %", "TYPE OF 2ND R", ""]
    return [head, sub, cols_row] + rows


def _row(owner, interviewer, pct="", goal=""):
    r = [""] * 17
    r[0], r[1], r[10], r[11] = owner, interviewer, pct, goal
    return r


class ParseBlocks(unittest.TestCase):
    def setUp(self):
        self.values = (
            _block("9/13", [
                _row("Kash Rai", "Daniela Yepes", "47%", "60%"),
                _row("", "Perla Falabella"),                  # same owner, 2nd interviewer
                _row("Jairo Ruiz", "Gonzalo Serrano", "38%", "50%"),
                ["AVERAGES", "", "2,486"] + [""] * 14,        # ends the block
                [""] * 17,
            ])
            + _block("9/6", [
                _row("Kash Rai", "Daniela Yepes", "52%", "60%"),
                # the owner's own row left the goal blank; a continuation row has it
                _row("Blue Mendoza", "Florencia Nams", "47%"),
                _row("", "Karla Garcia", "", "60%"),
            ])
        )
        self.weeks = src.parse_blocks(self.values)

    def test_blocks_are_found_by_marker_not_by_row(self):
        self.assertEqual([w.label for w in self.weeks], ["9/13", "9/6"])
        self.assertEqual(self.weeks[1].header_row, 9)   # 8 rows of block one above it

    def test_owner_comes_from_the_column_headed_interviewer(self):
        names = [o.name for o in self.weeks[0].owners]
        self.assertEqual(names, ["Kash Rai", "Jairo Ruiz"])   # not the interviewers

    def test_continuation_rows_join_their_owner(self):
        kash = self.weeks[0].owners[0]
        self.assertEqual(kash.interviewers, ["Daniela Yepes", "Perla Falabella"])

    def test_averages_row_is_not_an_owner(self):
        self.assertNotIn("AVERAGES", [o.name.upper() for o in self.weeks[0].owners])

    def test_goal_is_a_number_not_percent_text(self):
        self.assertEqual(self.weeks[0].owners[0].goal, 0.6)
        self.assertEqual(self.weeks[0].owners[1].goal, 0.5)

    def test_goal_falls_back_to_a_continuation_row(self):
        blue = self.weeks[1].owners[1]
        self.assertEqual(blue.name, "Blue Mendoza")
        self.assertEqual(blue.goal, 0.6)

    def test_pick_week_defaults_to_the_newest(self):
        self.assertEqual(src.pick_week(self.weeks, None).label, "9/13")
        self.assertEqual(src.pick_week(self.weeks, "9/6").label, "9/6")

    def test_a_date_in_a1_still_picks_its_week(self):
        # Sheets parses the label '9/13' into a date, so A1 can come back as
        # '9/13/2026' or '09/13'. All three have to reach the same block.
        for lab in ("9/13", "09/13", "9/13/2026", " 9/13 "):
            self.assertEqual(src.pick_week(self.weeks, lab).label, "9/13", lab)

    def test_unknown_week_is_a_clear_exit_not_a_wrong_week(self):
        with self.assertRaises(SystemExit):
            src.pick_week(self.weeks, "1/1")

    def test_repeated_labels_stay_unique_for_the_dropdown(self):
        weeks = src.parse_blocks(_block("9/13", [_row("A", "x", "1%", "50%")])
                                 + _block("9/13", [_row("B", "y", "2%", "50%")]))
        self.assertEqual([w.label for w in weeks], ["9/13", "9/13 (2)"])

    def test_dropdown_skips_the_weeks_that_have_no_goal_column(self):
        weeks = src.parse_blocks(
            _block("9/13", [_row("A", "x", "1%", "50%")])
            + _block("3/15", [_row("B", "y", "2%")]))      # old box, no goal
        self.assertEqual(rep.selectable_weeks(weeks), ["9/13"])


# ------------------------------------------------------- ARS REPORT geometry
def _ars_box(label, day_values, block_col=14, box_row=45, per_day=("Q", "Di", "De", "QR", "DR")):
    """A Window holding one weekly box: header row, Interviewer row, two data
    rows. `day_values` is {day: [(interviewer, [five cells]), ...]}."""
    stride = len(per_day)
    width = 1 + len(ars.DAYS) * stride
    rows = max(ars.BOX_STRIDE + 1,
               2 + max((len(v) for v in day_values.values()), default=0))
    grid = [["" for _ in range(width)] for _ in range(rows)]
    grid[0][0] = label
    grid[1][0] = "Interviewer"
    for d, day in enumerate(ars.DAYS):
        c = 1 + d * stride
        grid[0][c] = day
        for k, h in enumerate(per_day):
            grid[1][c + k] = h
        for i, (name, cells) in enumerate(day_values.get(day, [])):
            grid[2 + i][0] = name
            for k, v in enumerate(cells):
                grid[2 + i][c + k] = v
    return ars.Window(grid, row0=box_row, col0=block_col)


class ArsGeometry(unittest.TestCase):
    def test_the_two_tabs_label_the_same_week_seven_days_apart(self):
        self.assertEqual(ars.ars_week_label("9/13", year_hint=2026), "9/20")
        self.assertEqual(ars.ars_week_label("12/28", year_hint=2025), "1/4")

    def test_a_bad_week_label_is_refused_not_guessed(self):
        with self.assertRaises(ValueError):
            ars.ars_week_label("last week")

    def test_week_box_is_found_by_its_label_not_by_stepping_six_rows(self):
        win = _ars_box("9/20", {"Thursday": [("Estefanny", ["2", "2", "0", "50%", "50%"])]})
        self.assertEqual(ars.find_week_box(win, 14, "9/20"), 45)
        self.assertIsNone(ars.find_week_box(win, 14, "9/13"))

    def test_slashed_dates_compare_regardless_of_padding_or_year(self):
        win = _ars_box("09/20/2026", {})
        self.assertEqual(ars.find_week_box(win, 14, "9/20"), 45)

    def test_day_columns_are_found_by_the_day_name(self):
        win = _ars_box("9/20", {
            "Monday": [("Estefanny", ["7", "7", "3", "41%", "59%"])],
            "Thursday": [("Estefanny", ["2", "2", "0", "50%", "50%"])]})
        mon = ars.read_day(win, 14, 45, "Monday")
        thu = ars.read_day(win, 14, 45, "Thursday")
        self.assertEqual([mon[0].get(k) for k in ("Q", "Di", "De")], ["7", "7", "3"])
        self.assertEqual([thu[0].get(k) for k in ("Q", "Di", "De")], ["2", "2", "0"])

    def test_an_all_zero_interviewer_row_is_empty(self):
        win = _ars_box("9/20", {"Monday": [("Andrea", ["0", "0", "0", "0%", "0%"]),
                                           ("Estefanny", ["5", "1", "0", "83%", "17%"])]})
        rows = ars.read_day(win, 14, 45, "Monday")
        self.assertTrue(rows[0].is_empty())
        self.assertFalse(rows[1].is_empty())

    def test_a_seven_column_answered_day_reads_the_same_as_a_five_column_one(self):
        """SOUTH SHORE's ANSWERED block is Q|B|NC|BR|NCR; ARS REPORT (1)-(5) is
        Q|A|B|NC|AR|BR|NCR. Reading by position put the A column under Booked."""
        five = _ars_box("9/20", {"Thursday": [("Est", ["6", "6", "0", "100%", "0%"])]},
                        per_day=("Q", "B", "NC", "BR", "NCR"))
        seven = _ars_box("9/20", {"Thursday": [("Est", ["6", "5", "6", "0",
                                                        "83%", "100%", "0%"])]},
                         per_day=("Q", "A", "B", "NC", "AR", "BR", "NCR"))
        for win in (five, seven):
            row = ars.read_day(win, 14, 45, "Thursday")[0]
            self.assertEqual(row.get("Q"), "6")
            self.assertEqual(row.get("B"), "6")
            self.assertEqual(row.get("NC"), "0")
            self.assertEqual(row.get("BR"), "100%")

    def test_an_extra_owner_row_is_read_not_cut_off(self):
        win = _ars_box("9/20", {"Monday": [("Gabriela", ["10", "2", "4", "63%", "38%"]),
                                           ("Nicole", ["9", "1", "6", "56%", "44%"]),
                                           ("Owner", ["1", "0", "0", "100%", "0%"])]})
        self.assertEqual([r.interviewer for r in ars.read_day(win, 14, 45, "Monday")],
                         ["Gabriela", "Nicole", "Owner"])

    def test_percent_and_count_cells_both_parse(self):
        self.assertEqual(ars._as_number("36%"), 0.36)
        self.assertEqual(ars._as_number("2,486"), 2486)
        self.assertIsNone(ars._as_number(""))

    def test_accents_and_spelling_do_not_block_a_tab_match(self):
        index = {ars._key("José Velasquez"): ("SOUTH SHORE", "José Velasquez"),
                 ars._key("Juan Botero"): ("ARS 3", "Juan Botero")}
        self.assertEqual(ars.find_tab("José Velasquez", index, {})[1], "José Velasquez")
        # a surname the retention tab carries but the tab title drops
        self.assertEqual(ars.find_tab("Juan Botero Berrio", index, {})[1], "Juan Botero")

    def test_a_different_first_name_never_fuzzy_matches(self):
        index = {ars._key("Marvin Williams"): ("ARS 4", "Marvin Williams")}
        self.assertIsNone(ars.find_tab("Chris Williams", index, {}))

    def test_an_alias_outranks_an_exact_name_collision(self):
        # 'Drew Tepper' is a real tab that stopped being filled; the live one is
        # ' Drew Tepper New'. The alias has to win or the report reads the stale tab.
        index = {ars._key("Drew Tepper"): ("SOUTH SHORE", "Drew Tepper"),
                 ars._key(" Drew Tepper New"): ("SOUTH SHORE", " Drew Tepper New")}
        self.assertEqual(ars.find_tab("Drew Tepper", index, {})[1], "Drew Tepper")
        self.assertEqual(
            ars.find_tab("Drew Tepper", index, {"Drew Tepper": " Drew Tepper New"})[1],
            " Drew Tepper New")

    def test_an_alias_reaches_a_tab_the_matcher_will_not(self):
        index = {ars._key("Christopher Williams"): ("ARS 1", "Christopher Williams")}
        self.assertIsNone(ars.find_tab("Chris Williams", index, {}))
        self.assertEqual(
            ars.find_tab("Chris Williams", index,
                         {"Chris Williams": "Christopher Williams"})[1],
            "Christopher Williams")


# ------------------------------------------------------------ column resolution
class ColumnResolution(unittest.TestCase):
    def setUp(self):
        self.cols = cols.resolve(rep.DEFAULT_HEADERS)

    def test_every_field_resolves(self):
        self.assertEqual(cols.missing(self.cols), [])

    def test_the_two_qualified_columns_go_to_different_groups(self):
        self.assertEqual(self.cols["qualified"], 6)        # G, next to Disqualified
        self.assertEqual(self.cols["ab_qualified"], 11)    # L, next to Booked
        self.assertNotEqual(self.cols["qualified"], self.cols["ab_qualified"])

    def test_the_groups_stay_contiguous(self):
        self.assertEqual(
            [self.cols[f] for f in ("qualified", "disqualified", "declined",
                                    "qualified_ret", "declined_ret")],
            [6, 7, 8, 9, 10])
        self.assertEqual(
            [self.cols[f] for f in ("ab_qualified", "booked", "not_contacted",
                                    "booked_ret", "not_contacted_ret")],
            [11, 12, 13, 14, 15])

    def test_a_truncated_header_row_is_a_strict_prefix(self):
        # The self-heal in run() only fires when what came back is a prefix of
        # the known header row; this pins that the two agree cell for cell.
        short = list(rep.DEFAULT_HEADERS[:-1])
        self.assertEqual([cols.norm(h) for h in short],
                         [cols.norm(h) for h in rep.DEFAULT_HEADERS][:len(short)])
        self.assertEqual(cols.missing(cols.resolve(short)), ["office"])

    def test_a_wrapped_header_still_matches(self):
        self.assertEqual(self.cols["booked_ret"], 14)      # 'Booked\nRetention'

    def test_inserting_a_column_moves_the_rest_without_breaking_them(self):
        shifted = ["Spacer"] + list(rep.DEFAULT_HEADERS)
        moved = cols.resolve(shifted)
        self.assertEqual(moved["owner"], 1)
        self.assertEqual(moved["ab_qualified"], 12)
        self.assertEqual(cols.missing(moved), [])


# ------------------------------------------------------------------- the alert
class AlertFilter(unittest.TestCase):
    def _row(self, shown, pct):
        col = cols.resolve(rep.DEFAULT_HEADERS)
        r = [""] * len(rep.DEFAULT_HEADERS)
        r[col["owner"]] = "Someone"
        r[col["first_showed"]] = shown
        r[col["retention"]] = pct
        return r

    def test_only_offices_at_or_under_the_mark_are_listed(self):
        rows = [self._row(10, 0.2), self._row(10, 0.55), self._row(10, 0.4)]
        kept = rep.below_the_mark(rows, rep.DEFAULT_HEADERS)
        self.assertEqual([r[4] for r in kept], [0.2, 0.4])   # 0.55 drops out

    def test_an_office_with_no_interviews_that_day_is_not_flagged(self):
        # 0 of 0 is undefined, not bad -- flagging it would bury the real ones.
        rows = [self._row(0, 0), self._row("", ""), self._row(3, 0.0)]
        kept = rep.below_the_mark(rows, rep.DEFAULT_HEADERS)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0][2], 3)

    def test_worst_retention_sorts_to_the_top(self):
        rows = [self._row(10, 0.38), self._row(10, 0.05), self._row(10, 0.22)]
        got = rep.worst_first(rows, rep.DEFAULT_HEADERS)
        self.assertEqual([r[4] for r in got], [0.05, 0.22, 0.38])

    def test_rows_without_a_reading_sort_last_not_as_zero(self):
        blank = self._row(10, "")
        rows = [blank, self._row(10, 0.3)]
        got = rep.worst_first(rows, rep.DEFAULT_HEADERS)
        self.assertEqual(got[0][4], 0.3)
        self.assertIs(got[1], blank)

    def test_the_threshold_matches_the_colour_rule(self):
        self.assertEqual(rep.THRESHOLD, 0.40)


# ------------------------------------------------------------------ the colours
class ColourRule(unittest.TestCase):
    """The bands come from Camila's 'Qualify Color Goals' sheet and depend on
    the office's OWN goal, so every rule has to read the Goal column."""

    def plan(self, first_data_row=4):
        return dict(rep.cf_plan(rep.DEFAULT_HEADERS, first_data_row))

    def test_every_coloured_column_is_covered(self):
        got = sorted(self.plan())
        self.assertEqual(got, [4, 9, 10, 14, 15])   # E, J, K, O, P

    def test_exactly_forty_percent_reads_red(self):
        red, yellow = self.plan()[4]
        self.assertIn("<=0.4", red[0])
        self.assertEqual(red[1], rep.CF_RED)
        self.assertEqual(red[2], rep.CF_RED_FG)
        self.assertIn(">=0.4", yellow[0])
        self.assertEqual(yellow[1], rep.CF_YELLOW)

    def test_the_qualify_bands_differ_by_the_offices_goal(self):
        green, grey, red = self.plan()[9]
        self.assertIn("$F4<0.55,J4>=0.6,J4<=0.7", green[0])      # 50% goal
        self.assertIn("$F4>=0.55,J4>=0.65,J4<=0.8", green[0])    # 60% goal
        self.assertIn("$F4<0.55,J4>=0.55,J4<0.6", grey[0])
        self.assertIn("$F4>=0.55,J4>=0.6,J4<0.65", grey[0])

    def test_over_qualifying_is_red_too(self):
        # Red is "not in either band", so 85% on a 60% goal is red, not green.
        red = self.plan()[9][2]
        self.assertTrue(red[0].startswith('=AND(J4<>"",NOT('))
        self.assertEqual(red[1], rep.CF_RED)

    def test_declined_retention_is_judged_through_its_complement(self):
        green, _, red = self.plan()[10]
        self.assertIn("(1-K4)", green[0])
        # but emptiness is tested on the cell itself: (1-K4) is 1 on a blank row
        self.assertTrue(red[0].startswith('=AND(K4<>""'))

    def test_the_answer_book_band_covers_both_o_and_p(self):
        # P uses the same band because Rafael's own ARS workbook applies it to
        # the matching NCR columns.
        for column, letter in ((14, "O"), (15, "P")):
            green, grey, red = self.plan()[column]
            for formula, _, _ in (green, grey, red):
                self.assertNotIn("$F", formula)     # no goal dependency
                self.assertIn(letter, formula)
            self.assertIn(">=0.8", green[0])
            self.assertIn(">=0.75", grey[0])
            self.assertIn("<0.75", red[0])

    def test_column_e_keeps_the_flat_forty_percent_floor(self):
        # The goal-dependent bands are for J/K/O/P; E is the headline alert.
        for formula, _, _ in self.plan()[4]:
            self.assertNotIn("$F", formula)
        self.assertEqual(rep.THRESHOLD, 0.40)

    def test_no_rule_paints_a_blank_row(self):
        for rules in self.plan().values():
            for formula, bg, _ in rules:
                if bg in (rep.CF_RED,) and "NOT(" in formula or "<=0.4" in formula:
                    self.assertIn('<>""', formula)

    def test_the_formulas_follow_the_header_row_that_was_found(self):
        plan = self.plan(first_data_row=7)
        self.assertIn("$F7", plan[9][0][0])
        self.assertIn("J7", plan[9][0][0])

    def test_rules_land_on_their_own_column_only(self):
        reqs = rep._cf_requests(1, [], list(rep.DEFAULT_HEADERS), 10)
        for r in reqs:
            rule = r["addConditionalFormatRule"]["rule"]
            rng = rule["ranges"][0]
            self.assertEqual(rng["endColumnIndex"] - rng["startColumnIndex"], 1)
            self.assertEqual(rng["startRowIndex"], rep.FIRST_DATA_ROW - 1)

    def test_only_our_own_rules_are_dropped(self):
        mine = {"ranges": [{"startColumnIndex": 4, "endColumnIndex": 5}]}
        someone_elses = {"ranges": [{"startColumnIndex": 2, "endColumnIndex": 3}]}
        reqs = rep._cf_requests(1, [someone_elses, mine, mine],
                                list(rep.DEFAULT_HEADERS), 10)
        dels = [r["deleteConditionalFormatRule"]["index"] for r in reqs
                if "deleteConditionalFormatRule" in r]
        self.assertEqual(dels, [2, 1])       # index 0 is not ours; highest first

    def test_this_report_only_ever_formats_its_own_two_rows_and_the_data(self):
        """Rows 1 and 2 are this report's. The header row is Eve's and must not
        be restyled -- twice it lost her group banners and her formatting."""
        for fdr in (4, 7):
            header_row = fdr - 1
            for r in rep._fmt_requests(1, list(rep.DEFAULT_HEADERS), 5, ["9/13"],
                                       first_data_row=fdr):
                cell = r.get("repeatCell")
                if not cell:
                    continue
                start = cell["range"]["startRowIndex"] + 1      # 1-indexed
                self.assertNotEqual(start, header_row,
                                    f"repaints the header row at {header_row}")
                if start > rep.OWN_ROWS:
                    self.assertNotIn("backgroundColor",
                                     cell["cell"].get("userEnteredFormat", {}))

    def test_row_one_past_the_title_is_left_alone(self):
        # Eve types her group banners into G1 / L1; a band across the row ate them.
        for r in rep._fmt_requests(1, list(rep.DEFAULT_HEADERS), 5, ["9/13"]):
            cell = r.get("repeatCell")
            if not cell or cell["range"]["startRowIndex"] != 0:
                continue
            self.assertLessEqual(cell["range"]["endColumnIndex"], 3)

    def test_row_two_past_column_a_is_left_alone(self):
        # Eve's group banners live in G2 and L2; a full-width status row ate them.
        for r in rep._fmt_requests(1, list(rep.DEFAULT_HEADERS), 5, ["9/13"]):
            cell = r.get("repeatCell")
            if not cell or cell["range"]["startRowIndex"] != rep.STATUS_ROW - 1:
                continue
            self.assertEqual(cell["range"]["endColumnIndex"], 1)

    def test_formatting_below_the_data_is_stripped_not_just_the_values(self):
        # A shorter fill used to leave the colour bands running down the tab.
        reqs = rep._fmt_requests(1, list(rep.DEFAULT_HEADERS), 5, ["9/13"],
                                 first_data_row=4, clear_to_row=60)
        wipes = [r["repeatCell"] for r in reqs
                 if r.get("repeatCell", {}).get("fields") == "userEnteredFormat"]
        self.assertEqual(len(wipes), 1)
        self.assertEqual(wipes[0]["range"]["startRowIndex"], 8)   # after 5 rows
        self.assertEqual(wipes[0]["range"]["endRowIndex"], 60)
        self.assertEqual(wipes[0]["cell"]["userEnteredFormat"], {})

    def test_the_wipe_never_eats_the_data_block(self):
        for n in (0, 1, 11):
            for r in rep._fmt_requests(1, list(rep.DEFAULT_HEADERS), n, ["9/13"],
                                       first_data_row=4, clear_to_row=200):
                cell = r.get("repeatCell")
                if not cell or cell.get("fields") != "userEnteredFormat":
                    continue
                self.assertGreaterEqual(cell["range"]["startRowIndex"],
                                        4 - 1 + max(n, 1))

    def test_nothing_is_copied_over_the_header_row(self):
        for fdr in (4, 7):
            for r in rep._fmt_requests(1, list(rep.DEFAULT_HEADERS), 5, ["9/13"],
                                       first_data_row=fdr):
                cp = r.get("copyPaste")
                if not cp:
                    continue
                self.assertGreaterEqual(cp["destination"]["startRowIndex"], fdr - 1)


# --------------------------------------------------------------- the two pickers
class Pickers(unittest.TestCase):
    def test_a_tab_in_its_own_layout_is_not_mistaken_for_a_migrated_one(self):
        own = [["Owner Name", "Inteviewer Name"], ["Jose Velasquez", "Estafany"]]
        self.assertFalse(rep.is_migrated(own))
        self.assertIsNone(rep.selected_week_label(own, 1))
        self.assertIsNone(rep.selected_day(own, 1))

    def test_a_migrated_tab_is_recognised_by_its_banner(self):
        migrated = [["9/6", "Tuesday", rep.BANNER_TITLE], ["status"], ["Owner Name"]]
        self.assertTrue(rep.is_migrated(migrated))
        self.assertEqual(rep.selected_week_label(migrated, 3), "9/6")
        self.assertEqual(rep.selected_day(migrated, 3), "Tuesday")

    def test_a_group_banner_in_row_one_does_not_block_recognition(self):
        # Eve's 'QUALIFIED RETENTION' sits further along row 1 and must not
        # stop the tab being seen as already migrated (which would insert
        # another two rows on every run).
        migrated = [["9/6", "Tuesday", rep.BANNER_TITLE, "", "", "",
                     "QUALIFIED RETENTION"], ["status"], ["Owner Name"]]
        self.assertTrue(rep.is_migrated(migrated))

    def test_a_junk_day_in_b1_falls_back_instead_of_crashing(self):
        self.assertIsNone(rep.selected_day(
            [["9/6", "Caturday", rep.BANNER_TITLE], [], []], 3))

    def test_a_look_back_left_in_the_pickers_cannot_freeze_the_tab(self):
        # The scheduled runs pass --now, which ignores A1/B1. Without it someone
        # checking last Monday would leave the tab stuck on Monday for good.
        import inspect
        src = inspect.getsource(rep.run)
        self.assertIn("if now:", src)
        self.assertIn("ignoring the pickers", src)
        sh = (pathlib.Path(rep.REPO_ROOT) / "deploy" / "below_the_mark.sh")
        self.assertIn("--now", sh.read_text(encoding="utf-8"))

    def test_the_dm_only_goes_out_on_a_clean_fill(self):
        # A failed fill leaves the PREVIOUS pass on the tab; DMing that picture
        # would tell five people the day is fine when the run never finished.
        sh = (pathlib.Path(rep.REPO_ROOT) / "deploy" / "below_the_mark.sh"
              ).read_text(encoding="utf-8")
        self.assertIn("slack_post --post", sh)
        self.assertIn('if [ "$ST" -eq 0 ]', sh)
        self.assertIn("NOT sending the DM", sh)
        self.assertIn("--dry-run", sh)          # a dry run never DMs either

    def test_every_recipient_is_a_slack_id_not_a_name(self):
        from automations.first_to_second_below_mark import slack_post as sp
        self.assertEqual(len(sp.RECIPIENTS), 5)
        for uid in sp.RECIPIENTS:
            self.assertRegex(uid, r"^U[A-Z0-9]{8,}$")
        self.assertEqual(len(set(sp.RECIPIENTS)), 5)

    def test_the_day_defaults_to_today(self):
        self.assertEqual(rep.default_day(dt.date(2026, 9, 17)), "Thursday")

    def test_the_weekend_falls_back_to_friday(self):
        self.assertEqual(rep.default_day(dt.date(2026, 9, 19)), "Friday")
        self.assertEqual(rep.default_day(dt.date(2026, 9, 20)), "Friday")


if __name__ == "__main__":
    unittest.main()


class AliasFile(unittest.TestCase):
    """`save_alias` used to write back `load_aliases()`, which strips the
    underscore keys -- so adding one alias deleted the '_note' explaining what
    belongs in the file (2026-09-17)."""

    def test_save_alias_keeps_the_note(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "owner-tab-aliases.json"
            path.write_text(json.dumps({"_note": "keep me", "A B": "A Bee"}),
                            encoding="utf-8")
            orig = ars.TAB_ALIASES
            ars.TAB_ALIASES = path
            try:
                ars.save_alias("Nii Tagoe", "Nii Teiko")
                data = json.loads(path.read_text(encoding="utf-8"))
                read_back = ars.load_aliases()
            finally:
                ars.TAB_ALIASES = orig
        self.assertEqual(data["_note"], "keep me")
        self.assertEqual(data["Nii Tagoe"], "Nii Teiko")
        self.assertEqual(data["A B"], "A Bee")          # existing rows survive
        self.assertNotIn("_note", read_back)            # reads still hide it
