"""Raf's knocking KPIs (2026-10-20): the tab parses into the scales he said
out loud, and each value lands green / gray / red where he put it."""
import unittest

from automations.shared import knock_kpis as K

# The "Knocking KPI's" tab as it read on 2026-10-20.
TAB = [
    ["", "AVG Knocks per hr", "AVG Doors / Rep", "Talk Toos",
     "AVG Talk too's per app + MOnday - sat avg talk to's per app",
     "Monday - Friday AVG first knock", "Mon - Fri AVG hrs knock / Day"],
    ["Green", "22+", "125+", "25+", "16 or less", "1:30 or prior", "4hrs+"],
    ["Grey", "20-21.9", "100-124.9", "20-24.9", "16.1-20.9", "1:31 - 1:59",
     "3hrs - 3hrs 59mins"],
    ["Red", "19.9", "99.9", "19.9", "21+", "2:00 or later",
     "2hrs 59mins or less"],
]


class TabParse(unittest.TestCase):
    def test_tab_matches_the_loom(self):
        self.assertEqual(K.scales_from_grid(TAB, logfn=lambda *_: None),
                         K.DEFAULTS)

    def test_unreadable_cell_keeps_default(self):
        grid = [r[:] for r in TAB]
        grid[1][1] = "lots"
        out = K.scales_from_grid(grid, logfn=lambda *_: None)
        self.assertEqual(out["knocks_hr"], K.DEFAULTS["knocks_hr"])

    def test_raf_moves_a_bound(self):
        grid = [r[:] for r in TAB]
        grid[1][2] = "140+"
        out = K.scales_from_grid(grid, logfn=lambda *_: None)
        self.assertEqual(out["doors"].green, 140)


class Colors(unittest.TestCase):
    S = K.DEFAULTS

    def c(self, kpi, text):
        return self.S[kpi].color(K.parse_value(kpi, text))

    def test_higher_is_better(self):
        self.assertEqual(self.c("knocks_hr", "22.0"), K.GREEN)
        self.assertEqual(self.c("knocks_hr", "20"), K.GRAY)
        self.assertEqual(self.c("knocks_hr", "19.9"), K.RED)
        self.assertEqual(self.c("doors", "1,125"), K.GREEN)
        self.assertEqual(self.c("doors", "100"), K.GRAY)
        self.assertEqual(self.c("talk_tos", "19"), K.RED)

    def test_talk_tos_per_app_lower_is_better(self):
        self.assertEqual(self.c("tt_per_app", "16.00"), K.GREEN)
        self.assertEqual(self.c("tt_per_app", "16.1"), K.GRAY)
        self.assertEqual(self.c("tt_per_app", "21"), K.RED)

    def test_first_knock(self):
        self.assertEqual(self.c("first_knock", "1:30 PM"), K.GREEN)
        self.assertEqual(self.c("first_knock", "10:36 AM"), K.GREEN)
        self.assertEqual(self.c("first_knock", "1:59 PM"), K.GRAY)
        self.assertEqual(self.c("first_knock", "2:00 PM"), K.RED)
        self.assertEqual(self.c("first_knock", "3:28 PM"), K.RED)

    def test_hours(self):
        self.assertEqual(self.c("hours", "4h 0m"), K.GREEN)
        self.assertEqual(self.c("hours", "3h 59m"), K.GRAY)
        self.assertEqual(self.c("hours", "3h 0m"), K.GRAY)
        self.assertEqual(self.c("hours", "2h 59m"), K.RED)


class Cells(unittest.TestCase):
    def test_skips_summary_rows_blanks_and_saturday_first_knock(self):
        hdr = ["#", "Rep", "First Knock", "Total Knocks"]
        rows = [["", "TOTAL", "1:00 PM", "900"],
                ["1", "A", "1:10 PM", "130"],
                ["2", "B", "", "90"]]
        cols = {"First Knock": "first_knock", "Total Knocks": "doors"}
        out = K.cell_colors(hdr, rows, K.DEFAULTS, cols, {0})
        self.assertEqual(out, {(1, 2): K.GREEN, (1, 3): K.GREEN,
                               (2, 3): K.RED})
        sat = K.cell_colors(hdr, rows, K.DEFAULTS, cols, {0}, saturday=True)
        self.assertNotIn((1, 2), sat)


class Scope(unittest.TestCase):
    def test_every_office_gets_the_scale(self):
        K._CACHE["scales"] = dict(K.DEFAULTS)
        try:
            self.assertEqual(K.for_office("Cody Someone"), K.DEFAULTS)
        finally:
            K._CACHE.clear()


if __name__ == "__main__":
    unittest.main()
