"""The day block of the morning photo is found BY HEADER, at any width.

The block was `Apps Int Int Up DTV NL TK Cx Roll Call` for a year, and
`capture._day_block` counted six columns across to find Cx and seven to find
Roll Call. When the Talk-To trio landed between TK and Cx the block became
eleven wide: six across became 'Total Talk-To's' and the roll-call probe landed
on '% of TT's per knock', so the morning post silently lost Cx and the roll call.

These tests pin the property that matters: the SAME seven metrics and the real
Roll Call come back from both layouts, and the trio is never photographed.
"""
import datetime as dt
import unittest

from automations.alphalete_production import capture


OLD = ["Apps", "Int", "Int Up", "DTV", "NL", "TK", "Cx", "Roll Call"]
NEW = ["Apps", "Int", "Int Up", "DTV", "NL", "TK",
       "Total Talk-To's", "% of TT's per knock", "AVG app per TT",
       "Cx", "Roll Call"]
DAYS = ["MON", "TUES", "WED", "THU", "FRI", "SAT", "SUN"]
# Mon 2026-09-07 .. Sun 2026-09-13
WEEK = [dt.date(2026, 9, 7) + dt.timedelta(days=i) for i in range(7)]


def grid(block):
    """A board with a running-week block then the seven day blocks."""
    r1 = ["", "", "", "RUNNING WEEK TOTALS", "", ""]
    r2 = ["", "", "", "", "", ""]
    r3 = ["#", "", "Rep", "APPS", "INT", "NL"]
    for day, date in zip(DAYS, WEEK):
        r1 += [day] + [""] * (len(block) - 1)
        r2 += [str(date.day)] + [""] * (len(block) - 1)
        r3 += list(block)
    r1 += ["Trainer"]
    r2 += [""]
    r3 += [""]
    return [r1, r2, r3]


class DayBlockByHeader(unittest.TestCase):
    def test_old_layout_unchanged(self):
        dc = capture._day_block(grid(OLD), WEEK[2])          # Wednesday
        heads = [grid(OLD)[2][c] for c in dc.metrics]
        self.assertEqual(heads, ["Apps", "Int", "Int Up", "DTV", "NL", "TK", "Cx"])
        self.assertEqual(grid(OLD)[2][dc.roll_call], "Roll Call")

    def test_trio_does_not_change_the_photo(self):
        """Eleven columns wide, the SAME seven are shot -- and Cx survives."""
        g = grid(NEW)
        dc = capture._day_block(g, WEEK[2])
        self.assertEqual([g[2][c] for c in dc.metrics],
                         ["Apps", "Int", "Int Up", "DTV", "NL", "TK", "Cx"])
        self.assertEqual(g[2][dc.roll_call], "Roll Call")

    def test_trio_is_never_photographed(self):
        g = grid(NEW)
        dc = capture._day_block(g, WEEK[2])
        shot = {g[2][c] for c in dc.metrics}
        for h in ("Total Talk-To's", "% of TT's per knock", "AVG app per TT"):
            self.assertNotIn(h, shot)

    def test_sunday_is_not_truncated(self):
        """The last block has no next banner to stop at -- it used to be the
        one that lost columns."""
        g = grid(NEW)
        dc = capture._day_block(g, WEEK[6])
        self.assertEqual([g[2][c] for c in dc.metrics],
                         ["Apps", "Int", "Int Up", "DTV", "NL", "TK", "Cx"])
        self.assertEqual(g[2][dc.roll_call], "Roll Call")

    def test_apps_is_the_filter_and_sort_anchor(self):
        for block in (OLD, NEW):
            g = grid(block)
            dc = capture._day_block(g, WEEK[3])
            self.assertEqual(g[2][dc.apps], "Apps")
            self.assertEqual(dc.metrics[0], dc.apps)

    def test_energy_era_tab_still_reads(self):
        """'EN' was the sixth column before the TK rename; old tabs still shoot."""
        g = grid(["Apps", "Int", "Int Up", "DTV", "NL", "EN", "Cx", "Roll Call"])
        dc = capture._day_block(g, WEEK[1])
        self.assertEqual([g[2][c] for c in dc.metrics],
                         ["Apps", "Int", "Int Up", "DTV", "NL", "EN", "Cx"])

    def test_unknown_day_is_named_in_the_error(self):
        with self.assertRaises(RuntimeError):
            capture._day_block(grid(NEW), dt.date(2026, 9, 20))


if __name__ == "__main__":
    unittest.main()
