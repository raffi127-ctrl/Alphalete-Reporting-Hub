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


class BoxJoin(unittest.TestCase):
    """The Box board dropped 'Total Rep Count' on 9/16: Selling fills in (Eve)."""

    def test_selling_when_no_total(self):
        from automations.org_active_headcount.tracker_readings import box_join
        sales = [{"owner": "Joy Gray", "grand_total": 112},
                 {"owner": "Roshan Ahmad", "grand_total": 90}]
        metrics = [{"rank": 1, "selling_rep_count": 23, "total_rep_count": None,
                    "sales_ele": 78, "sales_gas": 34},
                   {"rank": 2, "selling_rep_count": 18, "total_rep_count": None,
                    "sales_ele": 90, "sales_gas": 0}]
        self.assertEqual(box_join(sales, metrics), {"Joy Gray": 23, "Roshan Ahmad": 18})

    def test_total_wins_when_printed(self):
        from automations.org_active_headcount.tracker_readings import box_join
        got = box_join([{"owner": "Abel Draper", "grand_total": 8}],
                       [{"rank": 1, "selling_rep_count": 2, "total_rep_count": 3,
                         "sales_ele": 8, "sales_gas": 0}])
        self.assertEqual(got, {"Abel Draper": 3})


class PickTrackerTie(unittest.TestCase):
    """Both strip and band readings fit yesterday's window: the nearer wins."""

    def test_nearer_reading_wins(self):
        from automations.org_active_headcount.daily import pick_tracker
        reading = {"A": [{"owner": "HAMMAD HAQUE", "rep_count": 8}],
                   "B": [{"owner": "HAMMAD HAQUE", "rep_count": 18}]}
        self.assertEqual(pick_tracker("Muhammad Haque", "att_country", reading, 8), 8)

    def test_equal_gap_is_dash(self):
        from automations.org_active_headcount.daily import pick_tracker
        reading = {"A": [{"owner": "HAMMAD HAQUE", "rep_count": 7}],
                   "B": [{"owner": "HAMMAD HAQUE", "rep_count": 9}]}
        self.assertEqual(pick_tracker("Muhammad Haque", "att_country", reading, 8), "-")


if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------
# 2026-09-20. Eve tidied the tab by hand: she painted RUNNING WEEK / LAST
# WEEK'S / PREVIOUS WEEK'S black on black, moved the Campaign helper column out
# to the delta box, and turned the delta box's 'Total for week' caption into a
# live 'by <last day filled>'. Three finders were anchored on exactly those
# cells, and all three broke at once — the fill silently dropped from 33 cells
# a day to 1, the Tuesday roll raised a bare StopIteration, and the mail's
# second picture could not be built. Nothing here is about the layout she
# chose; it is about not anchoring on cells a person is expected to edit.
# --------------------------------------------------------------------------

def _hc_grid(*, week_cols: bool):
    """A miniature of the tab: summary, Ongoing block, daily block, history.
    `week_cols` adds the three columns the redesign removed."""
    tail = ["RUNNING WEEK TOTALS", "LAST WEEK'S TOTALS", "PREVIOUS WEEK'S TOTALS"] \
        if week_cols else ["", "", ""]
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    g = [
        ["", "ORG ACTIVE HEADCOUNT"],
        [],
        ["", "Headcount Summary - This Week"],
        ["", "Headcount"] + days,                                  # day names, no Totals
        ["", ""] + ["10", "20", "30", "", "", "", ""],
        [],
        ["", "All Campaigns: Mon-Sun"] + days,                     # day names, no Totals
        ["", "HC (Last Week)"] + ["1", "2", "3", "", "", "", ""],
        ["", "HC (4 Week AVG)"] + ["1", "2", "3", "", "", "", ""],
        [],
        ["All Campaings Ongoing Headcount", "", "WE 09.20", "WE 09.13"],
        [],
        ["1", "Rafael Hidalgo", "30", "50"],
        ["2", "Jairo Ruiz", "20", "41"],
        ["TOTALS", "", "50", "91"],
        [],
        ["All Campaigns HC", ""] + days + tail + ["Campaign"],
        ["", ""] + ["14", "15", "16", "17", "18", "19", "20"],
        ["1", "Rafael Hidalgo", "10", "20", "30", "", "", "", ""]
        + (["30", "50", "53"] if week_cols else ["", "", ""]) + ["Fiber"],
        ["2", "Jairo Ruiz", "5", "12", "20", "", "", "", ""]
        + (["20", "41", "43"] if week_cols else ["", "", ""]) + ["NDS"],
        ["Totals", ""] + ["15", "32", "50", "", "", "", ""]
        + (["50", "91", "96"] if week_cols else ["", "", ""]),
        ["WE 9.13", ""] + ["11", "22", "33", "44", "55", "66", "91"]
        + (["91"] if week_cols else []),
        [],
        # the delta box: 'Total for week' + one This/Last/Delta triplet per day
        ["All Campaings Ongoing Headcount", "", "Total for week", "", ""]
        + [c for d in days for c in (d, "", "")],
        ["", "", "Total this week", "Last week", "Delta"]
        + ["This week", "Last week", "Delta"] * 7,
        ["1", "Rafael Hidalgo"] + [""] * 26,
        ["2", "Jairo Ruiz"] + [""] * 26,
        [],
    ]
    return [list(r) for r in g]


class DailyBlockFoundByShape(unittest.TestCase):
    """`find_daily` anchored on the 'RUNNING WEEK TOTALS' header. It now anchors
    on the block's SHAPE, so the three columns can be hidden, renamed or
    removed without taking the block with them."""

    def test_finds_the_block_when_the_three_columns_are_gone(self):
        from automations.org_active_headcount.daily import find_daily
        dl = find_daily(_hc_grid(week_cols=False))
        self.assertEqual(dl["hdr"], 17)
        self.assertEqual([n for _, n, _ in dl["rows"]], ["Rafael Hidalgo", "Jairo Ruiz"])
        self.assertEqual(dl["totals"], 21)
        self.assertIsNone(dl["run"])
        self.assertIsNone(dl["lastw"])
        self.assertIsNone(dl["prevw"])

    def test_still_reads_a_tab_that_has_them(self):
        """The live tab keeps the three columns until the sandbox is signed off,
        so the same code has to read both shapes."""
        from automations.org_active_headcount.daily import find_daily
        dl = find_daily(_hc_grid(week_cols=True))
        self.assertEqual(dl["hdr"], 17)
        self.assertEqual((dl["run"], dl["lastw"], dl["prevw"]), (10, 11, 12))

    def test_the_summary_blocks_are_not_mistaken_for_it(self):
        """Rows 4 and 8 of the real tab carry all seven day names too. They are
        rejected because no col-A 'Totals' row closes them — if that ever broke,
        the fill would write the day numbers into the summary."""
        from automations.org_active_headcount.daily import find_daily
        for week_cols in (True, False):
            self.assertEqual(find_daily(_hc_grid(week_cols=week_cols))["hdr"], 17)

    def test_the_roll_skips_the_freeze_and_ends_the_history_row_on_sunday(self):
        from automations.org_active_headcount.daily import plan_roll, find_daily
        g = _hc_grid(week_cols=False)
        p = plan_roll(g, g, dt.date(2026, 9, 20), dt.date(2026, 9, 27))
        # the history row is the seven day totals, with nothing after Sunday
        self.assertEqual(p["stack_values"], ["15", "32", "50", "", "", "", ""])
        self.assertEqual(p["last_col"], find_daily(g)["days"][-1])
        # and nothing is written into the columns that no longer exist
        touched = {a1 for a1, _ in p["values"]}
        self.assertFalse([a for a in touched if a[0] in "JKL" and a[1:].isdigit()
                          and 17 <= int(a[1:]) <= 21])

    def test_a_tab_that_still_has_them_still_freezes_k_and_l(self):
        from automations.org_active_headcount.daily import plan_roll
        g = _hc_grid(week_cols=True)
        p = plan_roll(g, g, dt.date(2026, 9, 20), dt.date(2026, 9, 27))
        w = dict(p["values"])
        self.assertEqual(w["K19"], "30")      # LAST WEEK'S <- RUNNING WEEK
        self.assertEqual(w["L19"], "50")      # PREVIOUS WEEK'S <- LAST WEEK'S
        self.assertEqual(p["stack_values"][-1], "50")


class HelpersThatMoved(unittest.TestCase):
    """The two cells whose text a person is expected to change."""

    def test_campaign_is_read_by_name_from_wherever_it_sits(self):
        """Moved out of the daily block, it still has to reach the ICDs — this
        is the one that took the fill down to a single cell."""
        from automations.org_active_headcount.daily import find_daily
        g = _hc_grid(week_cols=True)
        for r in (17, 18, 19):                       # drop the in-block column
            g[r - 1][-1] = ""
        g += [[], ["", "", "", "", "", "", "Campaign"],
              ["1", "Rafael Hidalgo", "", "", "", "", "Fiber"],
              ["2", "Jairo Ruiz", "", "", "", "", "NDS"]]
        rows = {n: c for _, n, c in find_daily(g)["rows"]}
        self.assertEqual(rows, {"Rafael Hidalgo": "fiber", "Jairo Ruiz": "nds"})

    def test_the_delta_box_is_found_though_its_caption_changed(self):
        """'Total for week' is now a live 'by Friday'. Anchoring on it is what
        made the Tuesday roll raise StopIteration."""
        from automations.org_active_headcount.daily import find_delta
        g = _hc_grid(week_cols=True)
        hdr = next(r for r in range(1, len(g) + 1)
                   if g[r - 1] and g[r - 1][0] == "All Campaings Ongoing Headcount"
                   and "Total for week" in g[r - 1])
        g[hdr - 1][2] = "by Friday"
        dx = find_delta(g)
        self.assertEqual(dx["hdr"], hdr)
        self.assertEqual([n for _, n in dx["rows"]], ["Rafael Hidalgo", "Jairo Ruiz"])


class SortsEveryBoxByThisWeek(unittest.TestCase):
    """Eve, 2026-09-20: "con cada corrida ordenar de mayor a menor quien tiene
    numero mas grande"."""

    def _reqs(self, g):
        from automations.org_active_headcount.daily import sort_requests
        return [r["sortRange"] for r in sort_requests(1, g)]

    def test_each_box_ranks_on_its_own_this_week_column(self):
        from automations.org_active_headcount.daily import find_daily
        g = _hc_grid(week_cols=True)
        keys = [(r["sortSpecs"][0]["dimensionIndex"] + 1,
                 r["sortSpecs"][0]["sortOrder"]) for r in self._reqs(g)]
        # Ongoing -> C, daily -> RUNNING WEEK TOTALS, delta -> its week triplet
        self.assertEqual(keys, [(3, "DESCENDING"),
                                (find_daily(g)["run"], "DESCENDING"),
                                (3, "DESCENDING")])

    def test_the_rank_gutter_stays_put(self):
        """Column A numbers the rows 1..N. It must not travel with the people,
        or the ranking would sort itself into nonsense."""
        for r in self._reqs(_hc_grid(week_cols=True)):
            self.assertEqual(r["range"]["startColumnIndex"], 1)

    def test_the_delta_box_carries_its_campaign_column(self):
        """The Campaign helper sits to the RIGHT of the last day triplet. Left
        out of the range it would stay still while the names move under it, and
        every ICD would end up reading another ICD's tracker — the same silent
        break as when the column was moved in the first place."""
        g = _hc_grid(week_cols=True)
        hdr = next(r for r in range(1, len(g) + 1)
                   if g[r - 1] and g[r - 1][0] == "All Campaings Ongoing Headcount"
                   and "Total for week" in g[r - 1])
        for r, camp in ((hdr + 2, "Fiber"), (hdr + 3, "NDS")):
            g[r - 1] = g[r - 1] + [""] * (27 - len(g[r - 1]))
            g[r - 1][26] = camp                       # col AA
        delta = self._reqs(g)[-1]
        self.assertEqual(delta["range"]["startRowIndex"], hdr + 1)
        self.assertGreaterEqual(delta["range"]["endColumnIndex"], 27)
