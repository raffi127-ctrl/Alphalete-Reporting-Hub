"""python -m unittest automations.late_join_audit.test_run"""
import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from automations.late_join_audit import run

DAY = dt.date(2026, 9, 29)
PT = ZoneInfo("America/Los_Angeles")          # Lucy 2's browser clock
HDR = ["SECTION", "FIRST INTERVIEWS	Brought on Board: 0 | Interview Completed: ", "Time",
       "First Name", "Last Name", "Phone", "Cell Phone", "Email", "Rating", "Booked by",
       "Job Board", "Show Up", "Done By", "Vetted By", "Remove", "Follow Up Status",
       "Follow Up By", "Follow Up Time", "", "Action"]
# the two Late Joins the 9/29 probe read off Drew's office (22583), cell for cell
SHACTY = ["ROW", HDR[1], "4:15 PM", "Shacty", "Amezquita", "407-437-3830", "",
          "nallelyv407@gmail.com", "", "AI Messaging at 09/28 03:07 PM", "Indeed",
          "Yes No ; ( )1 ; (x)2", "SELECT=None", "Daneisy Hernandez", "", "SELECT=Late Join",
          "Mariana Echeverry", "Tue,29 01:16 PM", "", "Reschedule 1st | Pause"]
SHAWN = ["ROW", HDR[1], "4:30 PM", "Shawn", "Lattimore", "407-668-2263", "",
         "chickalow67@gmail.com", "", "Nicole Williams APT at 09/25 01:38 PM", "Indeed",
         "Yes No ; (x)1 ; ( )2", "SELECT=None", "Esprit Soriano", "", "SELECT=Late Join",
         "Gabriela Sorto", "Tue,29 01:35 PM", "", "Schedule 2nd | Disqualify | Decline | Pause"]
SECOND = ["SECTION", "SECOND INTERVIEWS", "Time", "Follow Up Status"]
SECOND_ROW = ["ROW", "SECOND INTERVIEWS", "9:00 AM", "SELECT=Late Join"]


def rows(*r):
    return run.rows_to_late_joins([SECOND, SECOND_ROW, HDR, *r], "Drew Tepper", "22583",
                                  DAY, PT)


class LateJoinTest(unittest.TestCase):
    def test_shacty_marked_one_minute_after_is_too_early(self):
        # 01:16 PM on Lucy 2's Pacific browser = 4:16 PM in Drew's Eastern
        # office, as Analay saw it
        r = rows(SHACTY)[0]
        self.assertEqual((r["slot"], r["marked"], r["minutes"]), ("4:15 PM", "4:16 PM", 1))
        self.assertTrue(r["too_early"])
        self.assertEqual(r["by"], "Mariana Echeverry")
        self.assertFalse(r["showed_up"])

    def test_shawn_at_five_minutes_is_within_the_rule_but_showed_up(self):
        r = rows(SHAWN)[0]
        self.assertEqual(r["minutes"], 5)
        self.assertFalse(r["too_early"])
        self.assertTrue(r["showed_up"])
        self.assertIn("⚠️ AppStream says they showed up", run._line(r))

    def test_only_first_interviews(self):
        self.assertEqual(len(rows(SHACTY, SHAWN)), 2)

    def test_other_statuses_ignored(self):
        other = list(SHACTY)
        other[15] = "SELECT=None"
        self.assertEqual(rows(other), [])

    def test_central_office_priscilla(self):
        # Raf's office (Central): 06:49 AM on Lucy's clock = 8:49 AM there,
        # as #rafs-office-recruiting-11280 said at the time
        row = list(SHACTY)
        row[2], row[17] = "8:45 AM", "Tue,29 06:49 AM"
        r = run.rows_to_late_joins([HDR, row], "Rafael Hidalgo", "11280", DAY,
                                   ZoneInfo(run.MARK_TZ))[0]
        self.assertEqual((r["marked"], r["minutes"]), ("8:49 AM", 4))

    def test_mark_on_the_next_day(self):
        m = run.parse_marked("Wed,30 08:01 AM", DAY, PT)
        self.assertEqual(m.date(), dt.date(2026, 9, 30))

    def test_one_thread_per_office_summary_first(self):
        data = {"late": rows(SHACTY, SHAWN), "read": ["22583"], "failed": {}}
        (key, got), = run.by_office(data)
        self.assertEqual(key, ("Drew Tepper", "22583"))
        self.assertEqual(run.thread_title("Drew Tepper"), "Drew Tepper's Late Join Audit")
        text = run.summary_text(got)
        self.assertIn("*2 Late Joins* · ❌ *1 marked before the 5-min grace*", text)
        self.assertIn("• Mariana Echeverry: 1 Late Join · ❌ 1 too early", text)
        self.assertIn("• Gabriela Sorto: 1 Late Join", text)
        self.assertIn("⚠️ 1 marked Late Join but AppStream says they showed up", text)
        self.assertTrue(run._line(got[0]).startswith("❌ *Shacty Amezquita* · slot 4:15 PM · "
                                                     "marked 4:16 PM (1 min after) by "
                                                     "Mariana Echeverry"))

    def test_offices_include_colten(self):
        ids = [o for _, o in run.offices()]
        self.assertIn("14733", ids)
        self.assertIn("22583", ids)
        self.assertNotIn("", ids)


if __name__ == "__main__":
    unittest.main()
