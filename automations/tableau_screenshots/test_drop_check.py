"""The drop check: a day can have ARRIVED (coverage date, settled total) and
still be half-loaded. Built from 2026-10-01, so the numbers are the real ones:
NDS Wednesday 956 (finished 1,362) and Fiber Wednesday 7 (finished 126) went to
23 channels after both passed the gate.
"""
import datetime as dt
import unittest
from unittest import mock

from automations.tableau_screenshots import freshness as fr

WED = dt.date(2026, 9, 30)

NDS = "\n".join([
    "\t\tLine New/Port/Air\tvs Prev Wk Line New/Port/Air %\tvs 4 Wk Avg Line "
    "New/Port/Air %\t1 Wk Prev New/Port/Air\t4 Wk Avg New/Port/Air\t1 Yr Prev "
    "New/Port/Air",
    "Monday\t09/28 - 09/30\t1,110\t-2%\t2%\t1,133\t1,091\t1,090",
    "Tuesday\t09/28 - 09/30\t1,171\t-8%\t5%\t1,274\t1,117\t1,326",
    "Wednesday\t09/28 - 09/30\t956\t-20%\t-17%\t1,198\t1,154\t1,177",
    "Thursday\t09/28 - 09/30\t\t\t\t\t\t",
    "Total\tTotal\t3,230\t-10%\t-4%\t3,598\t3,360\t3,588",
])


def fiber(wed: str) -> str:
    return "\n".join([
        "Order WE\tMon\tTue\tWed\tThu\tFri\tSat\tSun\tTotal",
        f"10/4/2026\t143\t146\t{wed}\t\t\t\t\t296",
        "9/27/2026\t171\t186\t171\t164\t135\t127\t21\t975",
        "9/20/2026\t184\t200\t169\t180\t172\t117\t21\t1,043",
        "9/13/2026\t186\t191\t176\t191\t154\t118\t32\t1,048",
        "9/6/2026\t219\t191\t197\t216\t219\t149\t16\t1,207",
        "8/30/2026\t212\t206\t206\t195\t188\t154\t45\t1,206",
    ])


class TestNdsSameDay(unittest.TestCase):
    def test_this_mornings_956_is_held(self):
        why = fr.same_day_avg_shortfall(NDS, WED, 956.0, frac=0.85)
        self.assertIsNotNone(why)
        self.assertIn(fr.DROP_MARK, why)
        self.assertIn("83%", why)
        # stale_boards only HOLDS on this substring
        self.assertIn("not refreshed", why)

    def test_finished_day_passes(self):
        self.assertIsNone(fr.same_day_avg_shortfall(NDS, WED, 1362.0, frac=0.85))

    def test_mon_and_tue_pass(self):
        self.assertIsNone(fr.same_day_avg_shortfall(
            NDS, dt.date(2026, 9, 28), 1110.0, frac=0.85))
        self.assertIsNone(fr.same_day_avg_shortfall(
            NDS, dt.date(2026, 9, 29), 1171.0, frac=0.85))

    def test_no_avg_column_is_silent(self):
        self.assertIsNone(fr.same_day_avg_shortfall(
            "Wednesday\t09/28\t956", WED, 956.0, frac=0.85))


class TestFiberHistory(unittest.TestCase):
    def test_this_mornings_7_is_held(self):
        why = fr.history_shortfall(fiber("7"), WED, frac=0.5)
        self.assertIsNotNone(why)
        self.assertIn(fr.DROP_MARK, why)
        self.assertIn("not refreshed", why)

    def test_finished_126_passes(self):
        # 126 is only 72% of a normal Wednesday -- Fiber swings, which is why
        # its floor is 0.5 and not NDS's 0.85.
        self.assertIsNone(fr.history_shortfall(fiber("126"), WED, frac=0.5))

    def test_blank_day_is_zero_not_unreadable(self):
        self.assertIsNotNone(fr.history_shortfall(fiber(""), WED, frac=0.5))

    def test_sunday_never_judged(self):
        self.assertIsNone(fr.history_shortfall(
            fiber("7"), dt.date(2026, 9, 27), frac=0.5))

    def test_thin_history_is_silent(self):
        text = "\n".join(fiber("7").splitlines()[:3])     # 1 prior week
        self.assertIsNone(fr.history_shortfall(text, WED, frac=0.5))


def att(wed: str) -> str:
    """AT&T "Current Vs Prior Weeks", as the 10/1 11:47 dump read it."""
    return "\n".join([
        "\tMonday\tTuesday\tWednesday\tGrand Total",
        f"Sales (This Week)\t1,287\t1,362\t{wed}\t4,029",
        "vs Prior Wk \t7%\t14%\t10%\t11%",
        "vs 4 wk avg\t-2%\t5%\t7%\t3%",
        "Sales (Last Week)\t1,198\t1,190\t1,258\t3,646",
        "Sales (4 wk avg)\t1,315\t1,296\t1,292\t3,902",
    ])


class TestAttVsAvg(unittest.TestCase):
    def test_this_mornings_1110_is_held(self):
        why = fr.vs_avg_sheet_shortfall(att("1,110"), WED, frac=0.88)
        self.assertIsNotNone(why)
        self.assertIn(fr.DROP_MARK, why)
        self.assertIn("86%", why)
        self.assertIn("not refreshed", why)

    def test_finished_1380_passes(self):
        self.assertIsNone(fr.vs_avg_sheet_shortfall(att("1,380"), WED, frac=0.88))

    def test_blank_day_is_zero(self):
        self.assertIsNotNone(fr.vs_avg_sheet_shortfall(att(""), WED, frac=0.88))

    def test_weekday_not_on_sheet_is_silent(self):
        self.assertIsNone(fr.vs_avg_sheet_shortfall(
            att("1,110"), dt.date(2026, 10, 1), frac=0.88))      # Thursday

    def test_wired_on_the_att_extract(self):
        conf = fr.EXTRACTS["tableau:tracker_att"]["stable_total"]
        self.assertEqual(conf["avg_sheet"], "Current Vs Prior Weeks")


class TestGateWiring(unittest.TestCase):
    """The history check runs AFTER a passing coverage date and turns it into a
    hold; a passing history keeps the old READY verdict."""

    def _run(self, history_text):
        cfg = fr.EXTRACTS["tableau:tracker_quantum"]
        last = "Last SFDC Object Update: 9/30/2026 | Latest Activities Data Update: 9/30/2026"
        texts = iter([last, history_text])
        with mock.patch("automations.shared.tableau_patchright."
                        "download_crosstab_patchright", return_value="x"), \
             mock.patch.object(fr, "_read_crosstab_text",
                               side_effect=lambda p: next(texts)):
            return fr._check_last_update("tableau:tracker_quantum", cfg, WED)

    def test_coverage_ok_but_drop_holds(self):
        ok, why = self._run(fiber("7"))
        self.assertFalse(ok)
        self.assertIn(fr.DROP_MARK, why)

    def test_coverage_ok_and_full_day_ready(self):
        ok, why = self._run(fiber("126"))
        self.assertTrue(ok)
        self.assertIn("reaches 2026-09-30", why)


class TestDownstream(unittest.TestCase):
    def test_nds_lists_other_reports(self):
        names = fr.downstream_reports("tableau:tracker_nds")
        self.assertTrue(names, "NDS workbook feeds other scheduled reports")
        self.assertNotIn("Tableau Country Trackers", names)

    def test_alert_section_only_for_drops(self):
        from automations.tableau_screenshots import run
        self.assertEqual(run._drop_alert_lines(
            {"nds": "only reaches 2026-09-29 — extract not refreshed"}), [])
        lines = run._drop_alert_lines(
            {"nds": "DROP Wed: ... — extract not refreshed"})
        text = "\n".join(lines)
        self.assertIn("PART-LOADED", text)
        self.assertIn("NDS-SNRES-ATT-OOFWorkbook", text)
        self.assertIn("--no-freshness-gate", text)


if __name__ == "__main__":
    unittest.main()
