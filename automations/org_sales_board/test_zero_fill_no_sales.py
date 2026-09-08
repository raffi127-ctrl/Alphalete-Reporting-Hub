"""A completed day NOBODY sold on must land as 0, not as a blank cell.

WHY: 2026-09-08, Retail NL and Retail Internet both went out BLANK for Mon 9/7
— the one Monday nobody sold retail — and the run reported clean, so the review
link carried two empty boxes. The day list used to be built from the pull, and a
day with no sales has no rows in the pull, so there was nothing to fill and
nothing to say. Blank reads as "we don't know" (which is what a dead view looks
like); the real answer was 0, the same 0 the VAs type by hand.

The cases that must still NOT fill are the point of the file: a pull that parsed
nobody (a source that did not answer — the SARA-silence failure), and the
most recent day of a day-behind section, which has not published yet.

Run:  .venv/Scripts/python -m unittest \
        automations.org_sales_board.test_zero_fill_no_sales
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.org_sales_board import fill_section as fs


TUE = dt.date(2026, 9, 8)          # reporting week Mon 9/7 – Sun 9/13
MON = dt.date(2026, 9, 7)
WED = dt.date(2026, 9, 9)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
        "Sunday"]


def grid(label: str = "Retail NL", names=("Akib Chowdhury", "Ana Griffin")):
    """Minimal one-section board: header / day numbers / ICD rows / Totals."""
    g = [[""] * 12]                                  # row 1 filler
    g.append([label, ""] + DAYS + ["RUNNING WEEK TOTALS", "LAST WEEK'S", ""])
    g.append(["", ""] + [str(7 + i) for i in range(7)] + ["", "", ""])
    for i, n in enumerate(names, start=1):
        g.append([str(i), n] + [""] * 10)
    g.append(["Totals", ""] + [""] * 10)
    return g


def writes(plan):
    """{A1: value} for the planned writes."""
    return {u["range"]: u["values"][0][0] for u in plan.updates}


# One SARA scrape, two metrics: the owners are there, Wireless Lines sold,
# Internet did not. Shape is {owner: {measure: {date: n}}}.
SARA_PULL = {
    "akib chowdhury": {"Wireless Lines": {MON: 3}},
    "ana griffin": {"Wireless Lines": {MON: 1}},
}


class NobodySoldTest(unittest.TestCase):
    def test_metric_absent_from_the_pull_fills_zero(self):
        # Retail Internet: nobody sold one all week. Every ICD's Monday cell
        # must be a 0 — that is the cell that went out blank on 2026-09-08.
        spec = fs.SectionSpec(label="Retail Internet", metric="Internet",
                              day_behind=False)
        plan = fs.plan_section_fill(grid("Retail Internet"), spec, SARA_PULL,
                                    raw_aliases={}, today=TUE)
        w = writes(plan)
        self.assertEqual(w["C4"], 0)
        self.assertEqual(w["C5"], 0)

    def test_the_other_metric_still_gets_its_real_numbers(self):
        spec = fs.SectionSpec(label="Retail NL", metric="Wireless Lines",
                              day_behind=False)
        plan = fs.plan_section_fill(grid(), spec, SARA_PULL,
                                    raw_aliases={}, today=TUE)
        w = writes(plan)
        self.assertEqual(w["C4"], 3)
        self.assertEqual(w["C5"], 1)

    def test_today_and_future_days_stay_blank(self):
        # Tuesday is in progress and Wed–Sun haven't happened: they are cleared,
        # never zero-filled.
        spec = fs.SectionSpec(label="Retail Internet", metric="Internet",
                              day_behind=False)
        plan = fs.plan_section_fill(grid("Retail Internet"), spec, SARA_PULL,
                                    raw_aliases={}, today=TUE)
        w = writes(plan)
        for col in ("D", "E", "F", "G", "H", "I"):
            self.assertEqual(w[f"{col}4"], "", col)

    def test_running_total_stays_a_formula(self):
        spec = fs.SectionSpec(label="Retail Internet", metric="Internet",
                              day_behind=False)
        plan = fs.plan_section_fill(grid("Retail Internet"), spec, SARA_PULL,
                                    raw_aliases={}, today=TUE)
        self.assertEqual(writes(plan)["J4"], "=SUM(C4:I4)")


class SourceDidNotAnswerTest(unittest.TestCase):
    def test_empty_pull_writes_nothing(self):
        # No owners parsed at all = a dead view / expired session / empty
        # crosstab. Zeros here would be numbers we invented.
        spec = fs.SectionSpec(label="Retail NL", metric="Wireless Lines",
                              day_behind=False)
        plan = fs.plan_section_fill(grid(), spec, {}, raw_aliases={}, today=TUE)
        self.assertEqual(plan.updates, [])

    def test_empty_pull_says_why_in_the_log(self):
        spec = fs.SectionSpec(label="Retail NL", metric="Wireless Lines",
                              day_behind=False)
        plan = fs.plan_section_fill(grid(), spec, {}, raw_aliases={}, today=TUE)
        self.assertTrue(any("NO owners" in line for line in plan.log), plan.log)


class EmptyViewIsAnAnswerTest(unittest.TestCase):
    """What actually happened on 2026-09-08: the pull did not come back empty,
    it RAISED — Tableau leaves the sales worksheet out of the Crosstab dialog
    when the pinned week has no rows, so the dialog listed only the workbook's
    'Z_Last Refresh' utility sheet and both retail sections were skipped."""

    THE_ERROR = RuntimeError(
        "Couldn't find the 'Sara Plus Sales ICD (by day)' sheet in the "
        "Crosstab dialog — saw 1 thumb(s): ['Z_Last Refresh']. The view may "
        "have changed.")
    A_RENAME = RuntimeError(
        "Couldn't find the 'Sara Plus Sales ICD (by day)' sheet in the "
        "Crosstab dialog — saw 2 thumb(s): ['Z_Last Refresh', 'Sara Plus "
        "Sales ICD v2']. The view may have changed.")

    def test_only_utility_sheets_is_an_empty_week(self):
        from automations.org_sales_board import section_pull as sp
        self.assertTrue(sp.is_empty_crosstab_dialog(self.THE_ERROR))

    def test_a_data_sheet_in_the_list_is_still_a_real_failure(self):
        from automations.org_sales_board import section_pull as sp
        self.assertFalse(sp.is_empty_crosstab_dialog(self.A_RENAME))

    def test_empty_pull_from_the_source_fills_zero(self):
        # EmptyPull() = "Tableau rendered the view and it had no rows". Falsy
        # like {}, but it means something completely different.
        spec = fs.SectionSpec(label="Retail NL", metric="Wireless Lines",
                              day_behind=False)
        plan = fs.plan_section_fill(grid(), spec, fs.EmptyPull(),
                                    raw_aliases={}, today=TUE)
        w = writes(plan)
        self.assertEqual(w["C4"], 0)
        self.assertEqual(w["C5"], 0)

    def test_empty_pull_does_not_cry_alias(self):
        spec = fs.SectionSpec(label="Retail NL", metric="Wireless Lines",
                              day_behind=False)
        plan = fs.plan_section_fill(grid(), spec, fs.EmptyPull(),
                                    raw_aliases={}, today=TUE)
        self.assertFalse(any("verify/alias" in line for line in plan.log),
                         plan.log)

    def test_an_empty_pull_is_still_a_dict(self):
        p = fs.EmptyPull()
        self.assertEqual(len(p), 0)
        self.assertFalse(p)
        self.assertEqual(list(p.keys()), [])


class DayBehindTest(unittest.TestCase):
    def test_day_behind_section_does_not_zero_yesterday(self):
        # BOX at 4am Wednesday: Tuesday has not published yet, so Tuesday is
        # not owed. Monday is.
        spec = fs.SectionSpec(label="BOX", metric="count", day_behind=True)
        plan = fs.plan_section_fill(grid("BOX"), spec,
                                    {"akib chowdhury": {"count": {}}},
                                    raw_aliases={}, today=WED)
        w = writes(plan)
        self.assertEqual(w["C4"], 0)          # Monday: owed
        # Tuesday is neither owed nor future: the cell is left exactly as it
        # was, so the 14:30 catchup can put the real number in it.
        self.assertNotIn("D4", w)
        self.assertNotIn("D5", w)

    def test_day_behind_still_writes_the_days_the_pull_does_have(self):
        # The pull is what proves a day-behind day landed — Monday's numbers on
        # a Tuesday are real and must go in.
        spec = fs.SectionSpec(label="BOX", metric="count", day_behind=True)
        plan = fs.plan_section_fill(grid("BOX"), spec,
                                    {"akib chowdhury": {"count": {MON: 2}}},
                                    raw_aliases={}, today=TUE)
        self.assertEqual(writes(plan)["C4"], 2)

    def test_lagging_flag_defaults_off_the_shared_list(self):
        # Nobody passes day_behind in production: it comes from the same list
        # the email gate reads, so the two can't drift.
        self.assertTrue(fs.is_day_behind(
            fs.SectionSpec(label="BOX", metric="count")))
        self.assertTrue(fs.is_day_behind(
            fs.SectionSpec(label="Retail JE", metric="Closed Won")))
        self.assertFalse(fs.is_day_behind(fs.RETAIL_NL))
        self.assertFalse(fs.is_day_behind(fs.RETAIL_INTERNET))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
