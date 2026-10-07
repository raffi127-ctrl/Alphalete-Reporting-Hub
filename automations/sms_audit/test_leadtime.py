# -*- coding: utf-8 -*-
"""Lead time: the booked-at moment comes from the confirmation text.

Run: python -m unittest automations.sms_audit.test_leadtime
"""
import unittest

from automations.sms_audit import leadtime as LT


def out(sent, phone, body):
    return {"type": "Out", "sent_at": sent, "recipient_phone": phone,
            "body": body}


def rec(date, time, phone, status, by="A. Messaging", name="Someone"):
    return {"date": date, "time": time, "phone": phone, "status": status,
            "booked_by": by, "name": name}


CONF = "Hi Sam, your interview is all set for Mon Oct 05 9:45 AM! Camera On."


class SlotParsing(unittest.TestCase):
    def test_reads_the_slot_out_of_a_confirmation(self):
        got = LT._slot_in(CONF, 2026)
        self.assertEqual((got.month, got.day, got.hour, got.minute),
                         (10, 5, 9, 45))

    def test_reads_the_moved_wording(self):
        got = LT._slot_in(
            "Hey Sam - your appointment has been moved to Tue Oct 06 2:15 PM.",
            2026)
        self.assertEqual((got.day, got.hour), (6, 14))

    def test_reads_the_second_round_wording(self):
        got = LT._slot_in(
            "Congrats! You're scheduled for Tuesday Oct 06 9:30 AM.", 2026)
        self.assertEqual((got.day, got.hour, got.minute), (6, 9, 30))

    def test_an_ordinary_text_names_no_slot(self):
        self.assertIsNone(LT._slot_in("Hey, are you still interested?", 2026))


class Buckets(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(LT.bucket_of(0), "under 2 hrs")
        self.assertEqual(LT.bucket_of(119), "under 2 hrs")
        self.assertEqual(LT.bucket_of(120), "2-6 hrs")
        self.assertEqual(LT.bucket_of(1439), "6-24 hrs")
        self.assertEqual(LT.bucket_of(1440), "more than a day")
        self.assertEqual(LT.bucket_of(99999), "more than a day")


class Measure(unittest.TestCase):
    def test_lead_is_confirmation_to_slot(self):
        res = LT.measure("x",
                         recs=[rec("10-05-2026", "9:45 AM", "9995551234",
                                   "Interview Completed")],
                         log=[out("10-05-2026 08:45 AM", "+19995551234", CONF)])
        self.assertTrue(res["ok"])
        self.assertEqual(res["matched"], 1)
        self.assertAlmostEqual(res["rows"][0]["lead"], 60.0)
        self.assertEqual(res["rows"][0]["shown"], True)

    def test_earliest_confirmation_wins_when_resent(self):
        res = LT.measure("x",
                         recs=[rec("10-05-2026", "9:45 AM", "9995551234",
                                   "No Show")],
                         log=[out("10-05-2026 09:40 AM", "+19995551234", CONF),
                              out("10-05-2026 07:45 AM", "+19995551234", CONF)])
        self.assertAlmostEqual(res["rows"][0]["lead"], 120.0)
        self.assertEqual(res["rows"][0]["shown"], False)

    def test_a_confirmation_for_a_different_slot_does_not_match(self):
        res = LT.measure("x",
                         recs=[rec("10-07-2026", "9:45 AM", "9995551234",
                                   "No Show")],
                         log=[out("10-05-2026 08:45 AM", "+19995551234", CONF)])
        self.assertFalse(res["ok"])
        self.assertIn("unmatched", res["why"])

    def test_unmatched_are_counted_not_guessed(self):
        res = LT.measure(
            "x",
            recs=[rec("10-05-2026", "9:45 AM", "9995551234", "No Show"),
                  rec("10-05-2026", "3:15 PM", "9995559999", "No Show")],
            log=[out("10-05-2026 08:45 AM", "+19995551234", CONF)])
        self.assertEqual(res["matched"], 1)
        self.assertEqual(res["unmatched"], 1)

    def test_phone_formats_match_on_the_last_ten_digits(self):
        res = LT.measure("x",
                         recs=[rec("10-05-2026", "9:45 AM", "(999) 555-1234",
                                   "Brought on Board")],
                         log=[out("10-05-2026 08:45 AM", "19995551234", CONF)])
        self.assertEqual(res["matched"], 1)

    def test_late_share_and_buckets(self):
        late = ("Hi Sam, your interview is all set for Mon Oct 05 9:45 AM!")
        res = LT.measure(
            "x",
            recs=[rec("10-05-2026", "9:45 AM", "9995551111", "No Show"),
                  rec("10-05-2026", "9:45 AM", "9995552222",
                      "Interview Completed")],
            log=[out("10-03-2026 08:45 AM", "+19995551111", late),   # 2 days
                 out("10-05-2026 08:45 AM", "+19995552222", late)])  # 1 hr
        self.assertAlmostEqual(res["late_share"], 50.0)
        names = [b["label"] for b in res["buckets"]]
        self.assertIn("under 2 hrs", names)
        self.assertIn("more than a day", names)

    def test_no_records_is_not_ok(self):
        self.assertFalse(LT.measure("x", recs=[], log=[])["ok"])

    def test_no_log_is_not_ok(self):
        res = LT.measure("x", recs=[rec("10-05-2026", "9:45 AM", "1", "x")],
                         log=[])
        self.assertFalse(res["ok"])
        self.assertIn("SMS log", res["why"])


class ByBooker(unittest.TestCase):
    def test_groups_and_sorts_by_late_share(self):
        res = LT.measure(
            "x",
            recs=[rec("10-05-2026", "9:45 AM", "999555%04d" % i,
                      "No Show" if i % 2 else "Interview Completed",
                      by="L. Robinson" if i < 20 else "A. Messaging")
                  for i in range(40)],
            log=[out("10-03-2026 08:45 AM" if i < 20
                     else "10-05-2026 08:45 AM",
                     "999555%04d" % i, CONF) for i in range(40)])
        rows = LT.by_booker(res)
        self.assertEqual(rows[0][0], "L. Robinson")
        self.assertAlmostEqual(rows[0][2], 100.0)
        self.assertAlmostEqual(rows[1][2], 0.0)

    def test_small_bookers_are_left_out(self):
        res = LT.measure("x",
                         recs=[rec("10-05-2026", "9:45 AM", "9995551234",
                                   "No Show")],
                         log=[out("10-05-2026 08:45 AM", "+19995551234", CONF)])
        self.assertEqual(LT.by_booker(res), [])


if __name__ == "__main__":
    unittest.main()
