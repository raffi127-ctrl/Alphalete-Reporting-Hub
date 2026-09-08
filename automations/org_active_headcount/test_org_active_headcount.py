"""Unit tests for the pure planners — no Sheet, no Tableau, no network.

Everything that decides WHAT to write is a pure function over a grid, so the
cases that actually bite (a box gaining an ICD, a totals row with no label, a
week that has to roll twice, an ICD the source never mentions) are all testable
without touching the workbook. Run:

    python -m unittest automations.org_active_headcount.test_org_active_headcount
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.org_active_headcount import fill, rollover, skeleton_repair, sort
from automations.org_active_headcount import sources as src
from automations.org_active_headcount import structure as st


def _box(campaign, names, weeks=("WE 08.30", "WE 08.23", "WE 08.16")):
    """One campaign box as rows: header, triplet, one row per ICD, totals."""
    header = [campaign, "", "Total for week", "", ""] + list(weeks)
    triplet = ["", "", "Total this week", "Last week", "Delta"]
    reps = [[str(i), n, "", "=F", "=Iferror(0,0)"] + [""] * len(weeks)
            for i, n in enumerate(names, 1)]
    totals = ["Captainship", "", "=SUM()", "=F", ""] + ["=SUM()"] * len(weeks)
    return [header, triplet, *reps, totals]


def _grid(*boxes):
    out = []
    for b in boxes:
        out.extend(b)
        out.append([])            # the blank spacer the real tab has
    return out


class FindBoxes(unittest.TestCase):
    def test_finds_each_box_with_its_roster_and_totals_row(self):
        grid = _grid(_box("B2B", ["Atef Choudhury", "Eveliz Wright"]),
                     _box("BOX", ["Ryan Mcspadden"]))
        boxes = st.find_boxes(grid)
        self.assertEqual([b["campaign"] for b in boxes], ["B2B", "BOX"])
        self.assertEqual([n for _, n in boxes[0]["rows"]],
                         ["Atef Choudhury", "Eveliz Wright"])
        # totals row is the first row past the roster, wherever that lands
        self.assertEqual(boxes[0]["total_row"], boxes[0]["rows"][-1][0] + 1)

    def test_totals_row_with_no_label_is_still_found(self):
        """BOX and Retail Internet ship with a blank col A on their totals row.
        The finder is structural, so a missing label must not lose the box."""
        grid = _grid(_box("BOX", ["Ryan Mcspadden"]))
        grid[3][0] = ""                                   # blank the label
        box = st.find_boxes(grid)[0]
        self.assertEqual(box["total_row"], 4)

    def test_an_added_icd_moves_the_totals_row_with_it(self):
        """The whole point of finding by label: a new ICD must not need a code
        change, and must not leave the totals row behind."""
        small = st.find_boxes(_grid(_box("B2B", ["A One"])))[0]
        big = st.find_boxes(_grid(_box("B2B", ["A One", "B Two", "C Three"])))[0]
        self.assertEqual(big["total_row"], small["total_row"] + 2)

    def test_a_stray_total_for_week_label_is_not_a_box(self):
        grid = [["Not a box", "", "Total for week"], ["", "", "something else"]]
        self.assertEqual(st.find_boxes(grid), [])


class WeekLabels(unittest.TestCase):
    """C's week is not stored anywhere - it is derived from the newest history
    week that HAS DATA, which is the only signal the reserved empty columns
    cannot corrupt."""

    def _tab(self, weeks, filled):
        g = _grid(_box("B2B", ["A One", "B Two"], weeks))
        for lbl, val in filled.items():
            c = 5 + list(weeks).index(lbl)
            g[2][c] = val
        return g

    def test_we_label_is_zero_padded(self):
        self.assertEqual(st.we_label(dt.date(2026, 9, 6)), "WE 09.06")

    def test_reserved_empty_columns_do_not_set_the_position(self):
        """The leftmost HEADER is a week that has not happened. Reading it as
        the tab's position put the roll two weeks off and still produced a
        confident plan."""
        g = self._tab(("WE 9.20", "WE 9.13", "WE 08.23"), {"WE 08.23": "7"})
        self.assertEqual(rollover.newest_filled(g), "WE 08.23")
        self.assertEqual(rollover.live_week(g), "WE 09.06")

    def test_no_roll_when_c_already_holds_the_target(self):
        g = self._tab(("WE 9.20", "WE 08.23"), {"WE 08.23": "7"})
        self.assertFalse(rollover.needs_roll(g, dt.date(2026, 9, 7)))

    def test_rolls_once_the_week_moves_on(self):
        g = self._tab(("WE 9.20", "WE 08.23"), {"WE 08.23": "7"})
        self.assertTrue(rollover.needs_roll(g, dt.date(2026, 9, 14)))

    def test_an_empty_tab_never_rolls(self):
        g = self._tab(("WE 9.20", "WE 08.23"), {})
        self.assertFalse(rollover.needs_roll(g, dt.date(2026, 9, 14)))


class Roll(unittest.TestCase):
    def setUp(self):
        self.weeks = ("WE 08.30", "WE 08.23", "WE 08.16")
        self.grid = _grid(_box("B2B", ["A One", "B Two"], self.weeks))
        for r, c_val, d_val in ((2, "11", "9"), (3, "22", "20")):
            self.grid[r][2] = c_val      # C, this week
            self.grid[r][3] = d_val      # D, last week (a VALUE, not a formula)

    def test_d_moves_out_to_its_own_week_and_c_moves_into_d(self):
        plan, need = rollover.plan_roll(self.grid, "WE 08.30", "WE 09.06")
        self.assertEqual(need, [])
        p = dict(plan)
        self.assertEqual(p["F3"], "9")      # D's week parked in its column
        self.assertEqual(p["D3"], "11")     # C moved into D
        self.assertEqual(p["C3"], "")       # C cleared for the fill
        self.assertEqual(p["F1"], "WE 08.30")

    def test_it_never_writes_the_totals_row(self):
        """Its =IF(COUNT()) / =SUM() and the Delta re-derive themselves; writing
        them back as literals freezes each on today's number."""
        plan, _ = rollover.plan_roll(self.grid, "WE 08.30", "WE 09.06")
        touched = {a1 for a1, _ in plan}
        for cell in ("C5", "D5", "E5", "F5"):
            self.assertNotIn(cell, touched)

    def test_a_week_with_no_column_is_reported_not_guessed(self):
        plan, need = rollover.plan_roll(self.grid, "WE 09.06", "WE 09.13")
        self.assertEqual(need, ["WE 09.06"])
        self.assertEqual(plan, [])

    def test_a_new_column_lands_in_date_order(self):
        """Newest-first, so it goes immediately left of the first OLDER week -
        which for an ordinary roll is right after the Delta, where Eve asked."""
        reqs = rollover.plan_insert(self.grid, "WE 09.06", 99)
        at = reqs[0]["insertDimension"]["range"]["startIndex"]
        self.assertEqual(at, 5)                      # col F, before WE 08.30

    def test_a_future_week_does_not_displace_an_older_one(self):
        g = _grid(_box("B2B", ["A One"], ("WE 9.20", "WE 08.23")))
        at = rollover.plan_insert(g, "WE 08.30", 99)[0]
        self.assertEqual(at["insertDimension"]["range"]["startIndex"], 6)  # col G


class Sort(unittest.TestCase):
    def _grid(self):
        g = _grid(_box("B2B", ["A One", "B Two", "C Three"]))
        for row, val in ((2, "5"), (3, "20"), (4, "12")):
            g[row][2] = val
        return g

    def test_one_request_per_box_over_the_roster_only(self):
        reqs = sort.plan_sorts(self._grid(), 99)
        self.assertEqual(len(reqs), 1)
        r = reqs[0]["sortRange"]["range"]
        self.assertEqual((r["startRowIndex"], r["endRowIndex"]), (2, 5))

    def test_column_a_is_never_in_the_range(self):
        """It is the rank gutter: the numbers stay 1..N while people move."""
        r = sort.plan_sorts(self._grid(), 99)[0]["sortRange"]["range"]
        self.assertEqual(r["startColumnIndex"], 1)       # col B

    def test_the_range_reaches_the_last_history_column(self):
        """History has to travel with its owner."""
        r = sort.plan_sorts(self._grid(), 99)[0]["sortRange"]["range"]
        self.assertEqual(r["endColumnIndex"], 8)         # C/D/E + 3 week cols

    def test_it_sorts_on_this_week_descending_then_name(self):
        specs = sort.plan_sorts(self._grid(), 99)[0]["sortRange"]["sortSpecs"]
        self.assertEqual(specs[0], {"dimensionIndex": 2, "sortOrder": "DESCENDING"})
        self.assertEqual(specs[1], {"dimensionIndex": 1, "sortOrder": "ASCENDING"})

    def test_a_one_row_box_is_left_alone(self):
        self.assertEqual(sort.plan_sorts(_grid(_box("B2B", ["Only One"])), 99), [])


class Fill(unittest.TestCase):
    def test_writes_only_column_c(self):
        grid = _grid(_box("B2B", ["Atef Choudhury"]))
        updates, _ = fill.plan(grid, {"B2B": {"atefchoudhury": 25}})
        self.assertEqual(updates, [("C3", 25)])

    def test_an_icd_the_source_skips_is_reported_not_zeroed(self):
        grid = _grid(_box("B2B", ["Atef Choudhury", "Ghost Rep"]))
        updates, missing = fill.plan(grid, {"B2B": {"atefchoudhury": 25}})
        self.assertEqual(updates, [("C3", 25)])
        self.assertEqual(missing, {"B2B": ["Ghost Rep"]})

    def test_a_real_zero_is_written(self):
        grid = _grid(_box("B2B", ["Atef Choudhury"]))
        updates, missing = fill.plan(grid, {"B2B": {"atefchoudhury": 0}})
        self.assertEqual(updates, [("C3", 0)])
        self.assertEqual(missing, {})

    def test_a_campaign_with_no_pull_is_left_alone(self):
        grid = _grid(_box("B2B", ["Atef Choudhury"]),
                     _box("BOX", ["Ryan Mcspadden"]))
        updates, missing = fill.plan(grid, {"B2B": {"atefchoudhury": 25}})
        self.assertEqual(updates, [("C3", 25)])
        self.assertEqual(missing, {})          # BOX skipped, not reported empty

    def test_aliases_are_applied_before_matching(self):
        grid = _grid(_box("ATT Fiber Team", ["Muhammad Haque"]))
        updates, missing = fill.plan(
            grid, {"ATT Fiber Team": {src.norm("Hammad Haque"): 10}})
        self.assertEqual(updates, [("C3", 10)])
        self.assertEqual(missing, {})


class SummaryRepair(unittest.TestCase):
    def _tab(self):
        summary = [
            ["", "Headcount Summary"],
            ["", "Campaign", "This Week", "Last week", "Prior Week",
             "2 Weeks Prior", "3 Weeks Prior", "Grand Total"],
            ["", "B2B"], ["", "BOX"], ["", "Grand Total"],
            [], ["", "RAF ORG - Current vs Prior Weeks"],
            ["", "", "This Week", "Last week", "Prior Week",
             "2 Weeks Prior", "3 Weeks Prior", "Grand Total"],
            ["", "This Week vs"], ["", "vs 4 WeekAVG"], [],
        ]
        weeks = ("WE 08.30", "WE 08.23", "WE 08.16", "WE 08.09")
        return summary + _grid(_box("B2B", ["A One"], weeks),
                               _box("BOX", ["B Two"], weeks))

    def test_each_summary_row_points_at_its_own_box(self):
        plan = dict(skeleton_repair.plan(self._tab()))
        b2b_total, box_total = 15, 20
        self.assertEqual(plan["C3"], f"=C{b2b_total}")
        self.assertEqual(plan["C4"], f"=C{box_total}")   # not B2B's row

    def test_prior_week_reads_the_second_history_column_not_the_first(self):
        """'Last week' is =F; reading F again for 'Prior Week' showed the same
        week twice and pushed every later column one week too new."""
        plan = dict(skeleton_repair.plan(self._tab()))
        self.assertEqual(plan["D3"], "=D15")     # Last week  -> the box's D
        self.assertEqual(plan["E3"], "=G15")     # Prior Week -> G, not F
        self.assertEqual(plan["F3"], "=H15")
        self.assertEqual(plan["G3"], "=I15")

    def test_grand_total_column_becomes_a_four_week_average(self):
        plan = dict(skeleton_repair.plan(self._tab()))
        self.assertEqual(plan["H3"], "=AVERAGE(D3:G3)")
        self.assertEqual(plan["H2"], "4 Week AVG")

    def test_grand_total_row_still_sums_the_campaigns(self):
        """Eve, 2026-09-07: count by campaign. A rep on two campaigns is two
        active heads here, on purpose."""
        plan = dict(skeleton_repair.plan(self._tab()))
        self.assertEqual(plan["C5"], "=SUM(C3:C4)")

    def test_the_vs_row_has_no_broken_references(self):
        plan = dict(skeleton_repair.plan(self._tab()))
        self.assertNotIn("#REF!", "".join(str(v) for v in plan.values()))

    def test_the_vs_block_starts_at_last_week_and_divides(self):
        """Eve's layout: no 'This Week' column of its own, and each cell is this
        week's grand total DIVIDED BY that column's."""
        plan = dict(skeleton_repair.plan(self._tab()))
        self.assertNotIn("B9", plan)      # the row LABEL is Eve's, never rewritten
        self.assertEqual(plan["C8"], "Last week")
        self.assertEqual(plan["C9"], "=IFERROR($C$5/D5,0)")
        self.assertEqual(plan["G8"], "4 Week AVG")
        self.assertEqual(plan["G9"], "=IFERROR($C$5/H5,0)")

    def test_the_vs_block_header_is_found_not_offset(self):
        """It sits directly above the row, however far the two blocks drift."""
        tab = self._tab()
        tab.insert(6, [])                       # push the block down one row
        plan = dict(skeleton_repair.plan(tab))
        self.assertEqual(plan["C9"], "Last week")

    def test_the_old_vs_4_week_avg_row_is_retired(self):
        plan = dict(skeleton_repair.plan(self._tab()))
        self.assertEqual(plan["C10"], "")
        self.assertEqual(plan["B10"], "")

    def test_an_unnamed_totals_row_gets_its_label(self):
        tab = self._tab()
        tab[19][0] = ""                                   # blank BOX's label
        plan = dict(skeleton_repair.plan(tab))
        self.assertEqual(plan["A20"], "Captainship")

    def test_a_rank_chain_is_replaced_by_a_literal(self):
        tab = self._tab()
        formulas = [list(r) for r in tab]
        formulas[13][0] = "=A13+1"                        # a chained rank
        plan = dict(skeleton_repair.plan(tab, formulas))
        self.assertEqual(plan["A14"], 1)

    def test_a_summary_row_naming_a_box_that_is_gone_fails_loudly(self):
        tab = self._tab()
        tab[3][1] = "Frontier"                            # no such box
        with self.assertRaises(ValueError):
            skeleton_repair.plan(tab)

    def test_a_renamed_box_still_matches_its_summary_row(self):
        """Eve appended ' Headcount' to every box label on 2026-09-07. The
        summary keeps the short name, so the join has to tolerate the suffix -
        exact matching turned the whole fill into a silent no-op."""
        tab = self._tab()
        for i, row in enumerate(tab):
            if row and row[0] == "B2B":
                tab[i][0] = "B2B Headcount"
        plan = dict(skeleton_repair.plan(tab))
        self.assertEqual(plan["C3"], "=C15")      # still points at B2B's totals


if __name__ == "__main__":
    unittest.main()
