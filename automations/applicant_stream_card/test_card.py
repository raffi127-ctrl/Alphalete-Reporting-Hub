# -*- coding: utf-8 -*-
"""python -m unittest automations.applicant_stream_card.test_card

No network, no files: every input is built here."""
from __future__ import annotations

import datetime as dt
import unittest

from automations.applicant_stream_card import card as C
from automations.applicant_stream_card import fixes as F
from automations.applicant_stream_card import stream_stats as S


def rec(slot, push, book, by, status, board="Indeed", moved=False):
    acts = [["Send to Call List", "Process Emails", push, "Jen (CC)"],
            ["Send to AI", "Call List", push, "Jen (CC)"],
            ["Assign First Interview", "Call List", book, by]]
    if moved:
        acts.append(["Reschedule First Interview", "Calendar", book, by])
    d, t = slot.split(" ", 1)
    return {"date": d, "time": t, "status": status, "board": board,
            "booked_by": "A. Messaging" if by == "AI Messaging" else by,
            "actions": repr(acts)}


def office_week():
    """40 AI bookings same day (30 show), 40 human two days late (12 show)."""
    out = []
    for i in range(40):
        out.append(rec("10-06-2026 1:00 PM", "10-06-2026 08:00 AM",
                       "10-06-2026 09:00 AM", "AI Messaging",
                       "Interview Completed" if i < 30 else "No Show"))
        out.append(rec("10-09-2026 9:00 AM", "10-06-2026 08:00 AM",
                       "10-08-2026 10:00 AM", "Jorge Pena (CC)",
                       "Interview Completed" if i < 12 else "No Show",
                       board="LinkedIn"))
    return out


class StatsTest(unittest.TestCase):
    def setUp(self):
        self.s = S.summary(office_week())

    def test_reads_the_repr_action_list(self):
        t = S.timeline(office_week()[0])
        self.assertEqual(t["booked"], dt.datetime(2026, 10, 6, 9, 0))
        self.assertTrue(t["ai"])

    def test_ai_vs_human_split(self):
        w = self.s["who"]
        self.assertEqual((w["ai_n"], w["human_n"]), (40, 40))
        self.assertAlmostEqual(w["ai_share"], 50.0)
        self.assertAlmostEqual(w["ai_show"], 75.0)
        self.assertAlmostEqual(w["human_show"], 30.0)

    def test_days_to_book(self):
        d = self.s["days"]
        # 40 at 1h, 40 at 50h -> average 25.5h
        self.assertAlmostEqual(d["push_to_book"]["avg_h"], 25.5)
        self.assertAlmostEqual(d["late_share"], 50.0)
        self.assertAlmostEqual(d["same_day_share"], 50.0)

    def test_top_booking_hour(self):
        self.assertIn(self.s["times"]["top_hours"][0][0], ("9am", "10am"))

    def test_drivers_ranked_and_tested(self):
        dr = self.s["drivers"]
        self.assertTrue(dr and dr[0]["real"])
        self.assertAlmostEqual(dr[0]["gap"], 45.0)

    def test_small_groups_are_not_drivers(self):
        self.assertEqual(S.retention_drivers(S.timelines(office_week()[:6])),
                         [])

    def test_no_outcome_is_not_a_no_show(self):
        self.assertIsNone(S.shown({"status": ""}))
        self.assertFalse(S.shown({"status": "No Show"}))
        self.assertTrue(S.shown({"status": "Brought on Board"}))


class FixesTest(unittest.TestCase):
    def test_template_walkthrough_names_the_template_and_the_answer(self):
        f = F.template("WRONG ADDRESS",
                       "Directions / Directions: sends “3000 Premier”",
                       {"office": "11280",
                        "address": "3100 Premier Dr Suite 207, Irving TX"})
        joined = " ".join(f["steps"])
        self.assertIn("Directions / Directions", joined)
        self.assertIn("3100 Premier Dr Suite 207", joined)
        self.assertIn("Activate again", joined)

    def test_email_templates_go_to_the_email_page(self):
        f = F.template("SHOUTING", "Email / On Hold: “ALPHALETE”",
                       {})
        self.assertIn("Email Templates", f["steps"][0])

    def test_preferences_against_the_standard(self):
        got = F.check_preferences({"offered_buffer": "60",
                                   "accepted_buffer": "5",
                                   "ghosting_threshold": "60"})
        self.assertEqual([g["kind"] for g in got], ["PREF accepted_buffer"])
        self.assertEqual(F.check_preferences({"offered_buffer": "180",
                                              "accepted_buffer": "300",
                                              "ghosting_threshold": "60"}),
                         [])

    def test_routing_summary(self):
        rows = [{"name": "Pay", "routing": "Clarify"}] * 40
        self.assertEqual(F.routing_summary(rows)["kind"], "ROUTING")
        rows = [{"name": "x", "routing": "Don't Escalate"}] * 31
        self.assertIsNone(F.routing_summary(rows))


class CardTest(unittest.TestCase):
    def _items(self, n, kind="NO OPT-OUT"):
        return [F.template(kind, "Await Call / T{}: x".format(i), {})
                for i in range(n)]

    def test_same_kind_folds_into_one_walkthrough(self):
        got = C.fold(self._items(5))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["count"], 5)
        self.assertIn("T4", got[0]["found"])

    def test_no_data_is_grey_never_green(self):
        c = C.build("1", info_skipped=["templates not pulled"])
        info = c["lines"][0]
        self.assertEqual(info["dot"], C.GREY)
        self.assertTrue(all(ln["dot"] != C.GREEN for ln in c["lines"]
                            if ln["key"] in ("who", "speed", "recruiters")))

    def test_wrong_info_goes_first(self):
        c = C.build("1", info_items=[F.template(
            "WRONG ROOM", "Confirm / A: zoom", {})],
            word_items=self._items(1, "SHOUTING"))
        self.assertEqual(c["todo"][0]["item"]["kind"], "WRONG ROOM")
        self.assertEqual(c["lines"][0]["dot"], C.RED)

    def test_old_pull_is_flagged(self):
        now = dt.datetime(2026, 11, 12)
        c = C.build("1", sources=[("AI Settings", dt.date(2026, 10, 1), "tab"),
                                  ("Texts", dt.date(2026, 11, 11), "file")],
                    now=now)
        self.assertEqual([f["what"] for f in c["stale"]], ["AI Settings"])
        self.assertIn("Re-pull before sending", C.render(c))

    def test_renders(self):
        html = C.render(C.build("11280", stats=S.summary(office_week())))
        self.assertIn("Applicant Stream Grade Card", html)
        self.assertIn("AI vs recruiters", html)


if __name__ == "__main__":
    unittest.main()
