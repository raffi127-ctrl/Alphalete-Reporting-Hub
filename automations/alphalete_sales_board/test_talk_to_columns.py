"""The Talk-To column planner, on paper grids -- no Sheet, no network.

What these pin down is the part that can quietly do the wrong thing: WHERE the
three columns go. Everything else in the module is a batchUpdate.
"""
import unittest

from automations.alphalete_sales_board import talk_to_columns as T

BASE = ["Apps", "Int", "Int Up", "DTV", "NL", "TK", "Cx", "Roll Call"]
WIDE = ["Apps", "Int", "Int Up", "DTV", "NL", "TK",
        "Total Talk-To's", "% of TT's per knock", "AVG app per TT",
        "Cx", "Roll Call"]
DAYS = ["MON", "TUES", "WED", "THU", "FRI", "SAT", "SUN"]


def grid(**wide):
    """Three header rows: two leading columns, then one block per weekday.

    `wide=` says which days already carry the trio; `blank=` (a list) says which
    days are as WIDE as the template but still have blank sub-headers -- what an
    interrupted run leaves behind.
    """
    blank = wide.pop("blank", [])
    r1, r3 = ["", ""], ["#", "Name"]
    for d in DAYS:
        cols = WIDE if wide.get(d) else BASE
        if d in blank:
            cols = BASE[:6] + ["", "", ""] + BASE[6:]
        r1 += [d] + [""] * (len(cols) - 1)
        r3 += cols
    return [r1, [""] * len(r1), r3]


class DayBlocks(unittest.TestCase):
    def test_one_block_per_weekday_bounded_by_the_next_label(self):
        b = T.day_blocks(grid(THU=True))
        self.assertEqual(sorted(b), sorted(DAYS))
        self.assertEqual(b["MON"], (3, 10))            # eight columns
        self.assertEqual(b["THU"], (27, 37))           # eleven
        self.assertEqual(b["SUN"][1], len(grid(THU=True)[0]))

    def test_sub_header_lookup_stays_inside_its_block(self):
        g = grid(THU=True)
        b = T.day_blocks(g)
        self.assertEqual(T.sub_col(g, b["MON"], "TK"), 8)
        self.assertIsNone(T.sub_col(g, b["MON"], "Total Talk-To's"))
        self.assertEqual(T.sub_col(g, b["THU"], "Total Talk-To's"), 33)


class Plan(unittest.TestCase):
    def test_the_widened_day_is_the_template_and_the_rest_are_todo(self):
        day, col, todo = T.plan(grid(THU=True))
        self.assertEqual(day, "THU")
        self.assertEqual(col, 33)
        self.assertEqual([t[0] for t in todo],
                         ["MON", "TUES", "WED", "FRI", "SAT", "SUN"])
        self.assertTrue(all(t[2] for t in todo))       # all need the insert

    def test_columns_land_right_after_TK_never_after_Cx(self):
        g = grid(THU=True)
        _, _, todo = T.plan(g)
        for lab, anchor, _ in todo:
            self.assertEqual(T._cell(g, T.SUB_ROW, anchor), "TK")
            self.assertEqual(T._cell(g, T.SUB_ROW, anchor + 1), "Cx")

    def test_an_interrupted_run_pastes_instead_of_inserting_again(self):
        _, _, todo = T.plan(grid(THU=True, blank=["SUN"]))
        needs = dict((lab, ins) for lab, _, ins in todo)
        self.assertFalse(needs["SUN"])                 # already wide enough
        self.assertTrue(needs["MON"])

    def test_a_day_that_already_has_the_trio_is_left_alone(self):
        _, _, todo = T.plan(grid(THU=True, MON=True))
        self.assertNotIn("MON", [t[0] for t in todo])

    def test_no_template_means_nothing_to_copy_from(self):
        day, col, todo = T.plan(grid())
        self.assertIsNone(day)
        self.assertIsNone(col)

    def test_a_block_with_no_TK_is_skipped_not_guessed(self):
        g = grid(THU=True)
        g[T.SUB_ROW - 1][7] = "EN"                     # MON still says EN
        _, _, todo = T.plan(g)
        self.assertNotIn("MON", [t[0] for t in todo])


WEEK_COLS = ["APPS", "INT", "INT UP", "DTV", "NL", "TK",
             "AVG Total Knocks per day", "Total Talk-To's",
             "AVG TT's per day", "% of TT's per knock", "AVG TTs per app", "Cx"]


def week_grid():
    """The running-week block in front of the seven day blocks."""
    g = grid(THU=True)
    r1 = ["", "", T.WEEK_BLOCK] + [""] * (len(WEEK_COLS) - 1) + \
         ["LAST WEEK'S TOTALS"] + g[0][2:]
    r3 = ["#", "Name"] + list(WEEK_COLS) + ["APPS"] + g[2][2:]
    return [r1, [""] * len(r1), r3]


class RunningWeekBlock(unittest.TestCase):
    def test_the_block_ends_at_the_next_row1_label(self):
        g = week_grid()
        lo, hi = T.running_block(g)
        self.assertEqual(T._cell(g, T.SUB_ROW, lo), "APPS")
        self.assertEqual(T._cell(g, T.SUB_ROW, hi), "Cx")
        self.assertEqual(hi - lo + 1, len(WEEK_COLS))

    def test_the_shared_names_resolve_INSIDE_the_week_block(self):
        """'Total Talk-To's' and '% of TT's per knock' exist in the week block
        AND in every day block. Scoped lookup is what keeps them apart."""
        g = week_grid()
        wk = T.running_block(g)
        thu = T.day_blocks(g)["THU"]
        for h in (T.WEEK_TT, T.WEEK_PCT):
            a, b = T.sub_col(g, wk, h), T.sub_col(g, thu, h)
            self.assertTrue(a and b)
            self.assertNotEqual(a, b)
            self.assertLess(a, thu[0])          # the week one is to the LEFT

    def test_sunday_is_not_a_working_day(self):
        g = week_grid()
        blocks = T.day_blocks(g)
        work = [lab for lab in blocks if lab.upper() != "SUN"]
        self.assertEqual(len(work), 6)
        self.assertIn("SAT", work)


class EmptyCells(unittest.TestCase):
    """Three states, kept apart on purpose: `-` when there is no denominator to
    divide by, 0 when the zero is real, blank only on a row with no rep."""

    def test_a_row_with_no_rep_stays_blank(self):
        out = T._no_rep(7, "=A7/B7", "C")
        # ONE leading '=' -- the wrapped expression must lose its own.
        self.assertEqual(out, '=IF($C7="","",A7/B7)')

    def test_the_cant_measure_marker_is_a_dash(self):
        self.assertEqual(T.CANT_MEASURE, '"-"')


class TeamCriterion(unittest.TestCase):
    """The Teams block has three row shapes. The day count may only be built
    for the ones SUMPRODUCT can actually reproduce."""

    def test_a_plain_team_row_gives_an_array_test(self):
        out = T._team_test('=SUMIFS($E:$E,$DI:$DI,$C166)', 4, 78)
        self.assertEqual(out, "($DI$4:$DI$78=$C166)")

    def test_a_wildcard_row_is_refused(self):
        """SUMPRODUCT compares literally, so '*Andrew*' would match nothing and
        hand back a confident average built on a zero denominator."""
        self.assertIsNone(
            T._team_test('=SUMIFS(E:E,$DI:$DI,"*Andrews Full Crew*")', 4, 78))

    def test_the_totals_row_has_no_criterion(self):
        self.assertIsNone(T._team_test('=SUM($E$166:$E$180)', 4, 78))


class DayWorked(unittest.TestCase):
    """The day count has to grow one day at a time as the week runs, without
    anybody advancing a counter."""

    EXPR = T.day_worked_expr(31, 36, 41, 7)          # AE apps, AJ tk, AO roll

    def test_the_roll_call_letters_that_are_out(self):
        for letter in ('"X"', '"T"'):
            self.assertIn('%s7=%s' % ("AE", letter), self.EXPR)

    def test_a_day_still_ahead_needs_a_trace_to_count(self):
        """Apps reads 0.00 on a day that has not happened -- a NUMBER, so the
        letter test alone counts it and mid-week every average divides by six."""
        self.assertIn('AO7<>""', self.EXPR)          # a roll call, or
        self.assertIn("N(AJ7)>0", self.EXPR)         # knocks, or
        self.assertIn("AE7<>0", self.EXPR)           # a non-zero Apps

    def test_knocks_are_tested_as_a_NUMBER_not_as_non_empty(self):
        """On the TOTALS row an untouched day's TK is a SUMIF reading 0, not a
        blank; `TK<>""` there would count Thursday as a working day all week."""
        self.assertNotIn('AJ7<>""', self.EXPR)


class InsertOrder(unittest.TestCase):
    """Seeding inserts into several blocks at once. Every insert shifts what is
    to its RIGHT, so the rightmost anchor has to go first."""

    # As `seed` collects them: the day blocks, then RUNNING WEEK TOTALS — which
    # is the LEFTMOST of the lot.
    JOBS = [("MON", 36, 3, 1), ("TUES", 44, 3, 1), ("SUN", 84, 3, 1),
            (T.WEEK_BLOCK, 9, 5, 1)]

    def test_the_leftmost_block_is_widened_LAST(self):
        self.assertEqual([j[0] for j in T.insert_order(self.JOBS)],
                         ["SUN", "TUES", "MON", T.WEEK_BLOCK])

    def test_reversing_the_list_is_NOT_the_same_thing(self):
        """The bug: `reversed(jobs)` ran RUNNING WEEK first and its five columns
        pushed every day anchor five to the right, so each trio landed beside
        'Apps' instead of 'TK'."""
        self.assertNotEqual([j[0] for j in reversed(self.JOBS)],
                            [j[0] for j in T.insert_order(self.JOBS)])

    def test_anchors_stay_valid_as_the_inserts_go_in(self):
        done = []
        for _lab, anchor, n, _s in T.insert_order(self.JOBS):
            # nothing already inserted may sit at or left of this anchor
            self.assertTrue(all(a > anchor for a, _n in done), (anchor, done))
            done.append((anchor, n))


class ColumnLetters(unittest.TestCase):
    def test_round_trip_past_Z(self):
        for col, want in ((1, "A"), (26, "Z"), (27, "AA"), (56, "BD"), (82, "CD")):
            self.assertEqual(T._col_letter(col), want)


if __name__ == "__main__":
    unittest.main()
