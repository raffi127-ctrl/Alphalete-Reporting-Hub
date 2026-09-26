"""Pins the judgement calls in the SMS audit — the places where a small change
turns a real finding into noise, or hides one.

  python -m unittest automations.sms_audit.test_analyze
"""
from __future__ import annotations

import unittest

from automations.sms_audit import analyze as A


def _rec(thread, booked_by="A. Messaging", status="Interview Completed",
         date="09-23-2026", name="Test Applicant"):
    return {"date": date, "time": "8:15 AM", "name": name, "phone": "15550000000",
            "board": "Indeed", "booked_by": booked_by, "status": status,
            "thread": thread}


class CloserTest(unittest.TestCase):
    """A thread that ends on 'thanks' is finished. A thread that ends on a
    question is somebody left waiting. Counting the first as the second buries
    the handful that matter under a pile of polite sign-offs."""

    def test_sign_offs_are_not_unanswered(self):
        for said in ("C", "c", "ok", "Okay!", "yes", "Thank you very much",
                     "Thanks so much!", "👍", "see you tomorrow", "Got it"):
            self.assertTrue(A.CLOSER.match(said), said)

    def test_a_real_message_is_not_a_sign_off(self):
        for said in ("I'm ready for zoom call .", "Cancel", "Yes, tomorrow works",
                     "I'm no longer interested", "Can I reschedule?"):
            self.assertFalse(A.CLOSER.match(said), said)

    def test_unanswered_counts_only_the_ones_left_hanging(self):
        recs = [
            _rec([["Out", "", "hi", "09/23 9:00 AM"], ["In", "", "C", "09/23 9:01 AM"]]),
            _rec([["Out", "", "hi", "09/23 9:00 AM"],
                  ["In", "", "I'm ready for zoom call .", "09/23 9:01 AM"]],
                 name="Left Waiting"),
            _rec([["In", "", "are you there?", "09/23 9:00 AM"],
                  ["Out", "", "yes!", "09/23 9:02 AM"]]),
        ]
        out = A.unanswered(recs)
        self.assertEqual([u["name"] for u in out], ["Left Waiting"])


class QuestionBucketTest(unittest.TestCase):
    """A stem alternation followed by \\b silently matches nothing —
    '\\breschedul\\b' never fires on 'reschedule'. That bug quietly moved 34
    reschedule questions into the 'didn't fit a bucket' pile."""

    def _bucket(self, text):
        import re
        for label, pat in A.QUESTION_BUCKETS:
            if re.search(pat, text, re.I):
                return label
        return None

    def test_stems_match_their_full_words(self):
        self.assertEqual(self._bucket("Can I reschedule for 9:45 ?"),
                         "Can we reschedule / a different time?")

    def test_a_link_problem_beats_a_timing_word(self):
        # the Zoom bucket sits ABOVE the (much wider) reschedule bucket on
        # purpose: "what time does the zoom link open" is a link question
        self.assertEqual(self._bucket("the zoom link is not working, what time?"),
                         "How do I join the Zoom / link trouble?")

    def test_pay_and_location_are_separate_asks(self):
        self.assertEqual(self._bucket("how much does it pay?"), "What is the pay?")
        self.assertEqual(self._bucket("Is this remote?"),
                         "Is this remote / where is the office?")


class BookingMixTest(unittest.TestCase):
    def test_a_messaging_plus_directions_ai_is_the_automation(self):
        recs = [_rec([["Out", "Directions AI", "all set", "09/23 9:00 AM"]],
                     booked_by="A. Messaging"),
                _rec([["Out", "Directions", "all set", "09/23 9:00 AM"]],
                     booked_by="E. Gonzalez")]
        mix = A.booking_mix(recs)
        self.assertEqual((mix["ai"], mix["human"], mix["disagree"]), (1, 1, 0))

    def test_the_two_signals_disagreeing_is_reported_not_averaged(self):
        recs = [_rec([["Out", "Directions", "all set", "09/23 9:00 AM"]],
                     booked_by="A. Messaging")]
        mix = A.booking_mix(recs)
        self.assertEqual(mix["disagree"], 1)


class CarrierBurstTest(unittest.TestCase):
    """AppStream's deliverability checklist: more than 3 messages with no reply
    is how a number gets flagged. A text and its follow-up link go out in the
    same second and land as one message, so counting raw rows made every
    ordinary confirmation trip the rule — 167 of 185 threads, which tells
    nobody anything."""

    def test_paired_sends_inside_two_minutes_count_once(self):
        th = [["Out", "First Interview Confirmation", "we're set", "09/23 7:00 AM"],
              ["Out", "First Interview Confirmation", "here's the link", "09/23 7:00 AM"],
              ["Out", "Friendly Reminder 1", "starting in 5", "09/23 8:10 AM"],
              ["Out", "Friendly Reminder 1", "link again", "09/23 8:10 AM"]]
        found = A.anomalies([_rec(th)])
        self.assertNotIn("Over the carrier limit — 4+ separate texts with no reply between",
                         found)

    def test_four_real_sends_with_no_reply_is_flagged(self):
        th = [["Out", "", "a", "09/23 9:00 AM"], ["Out", "", "b", "09/23 10:00 AM"],
              ["Out", "", "c", "09/23 11:00 AM"], ["Out", "", "d", "09/23 12:00 PM"]]
        found = A.anomalies([_rec(th)])
        self.assertIn("Over the carrier limit — 4+ separate texts with no reply between",
                      found)

    def test_a_reply_resets_the_run(self):
        th = [["Out", "", "a", "09/23 9:00 AM"], ["Out", "", "b", "09/23 10:00 AM"],
              ["In", "", "hi", "09/23 10:30 AM"],
              ["Out", "", "c", "09/23 11:00 AM"], ["Out", "", "d", "09/23 12:00 PM"]]
        found = A.anomalies([_rec(th)])
        self.assertNotIn("Over the carrier limit — 4+ separate texts with no reply between",
                         found)


class LookAlikeLinkTest(unittest.TestCase):
    """Raf's Friendly Reminder 1 sends 'us02web.zоom.us' with a CYRILLIC о. It
    resolves to nothing, and it is invisible to anyone reading the template."""

    def test_a_cyrillic_o_in_the_host_is_caught(self):
        th = [["Out", "Friendly Reminder 1",
               "join now https://us02web.zоom.us/j/2935077152", "09/23 8:10 AM"]]
        found = A.anomalies([_rec(th)])
        key = "Dead link — the web address is spelled with a look-alike letter"
        self.assertIn(key, found)
        self.assertIn("CYRILLIC", found[key][0])

    def test_a_normal_zoom_link_is_left_alone(self):
        th = [["Out", "Friendly Reminder 1",
               "join now https://us02web.zoom.us/j/2935077152", "09/23 8:10 AM"]]
        found = A.anomalies([_rec(th)])
        self.assertNotIn("Dead link — the web address is spelled with a look-alike letter",
                         found)


class QuietHoursTest(unittest.TestCase):
    def test_the_seven_am_blast_groups_by_time_and_template_not_by_name(self):
        recs = [_rec([["Out", "First Interview Confirmation", "x", "09/23 7:00 AM"]],
                     name="A"),
                _rec([["Out", "First Interview Confirmation", "x", "09/23 7:00 AM"]],
                     name="B")]
        found = A.anomalies(recs)
        hits = found["Texted outside 8am–9pm (TCPA quiet hours)"]
        self.assertEqual(len(hits), 2)
        self.assertEqual(len(set(hits)), 1)  # one cause, not two findings
        self.assertIn("7:00 AM", hits[0])

    def test_business_hours_are_not_flagged(self):
        found = A.anomalies([_rec([["Out", "", "x", "09/23 10:00 AM"]])])
        self.assertNotIn("Texted outside 8am–9pm (TCPA quiet hours)", found)


class OptOutTest(unittest.TestCase):
    def test_texting_after_not_interested_is_flagged(self):
        th = [["In", "", "I'm no longer interested", "09/23 9:00 AM"],
              ["Out", "", "see you tomorrow!", "09/23 9:05 AM"]]
        found = A.anomalies([_rec(th)])
        self.assertIn("Kept texting after they asked us to stop / said no", found)

    def test_stopping_when_asked_is_not_flagged(self):
        th = [["Out", "", "hi", "09/23 9:00 AM"],
              ["In", "", "stop", "09/23 9:01 AM"]]
        found = A.anomalies([_rec(th)])
        self.assertNotIn("Kept texting after they asked us to stop / said no", found)


class ReplySpeedTest(unittest.TestCase):
    def test_a_next_day_blast_is_not_a_reply(self):
        th = [["In", "", "hello?", "09/23 9:00 AM"],
              ["Out", "First Interview Confirmation", "x", "09/25 7:00 AM"]]
        buckets, first = A.reply_speed([_rec(th)])
        self.assertEqual(buckets["template"], [])
        self.assertEqual(first, [])

    def test_typed_replies_split_by_who_booked(self):
        th = [["In", "", "hello?", "09/23 9:00 AM"],
              ["Out", "", "hi!", "09/23 9:02 AM"]]
        buckets, _ = A.reply_speed([_rec(th, booked_by="A. Messaging"),
                                    _rec(th, booked_by="E. Gonzalez")])
        self.assertEqual(len(buckets["typed"]), 2)
        self.assertEqual(len(buckets["typed_ai_thread"]), 1)
        self.assertEqual(len(buckets["typed_human_thread"]), 1)


class TimestampTest(unittest.TestCase):
    def test_the_year_comes_off_the_booking_row(self):
        rec = _rec([["Out", "", "x", "09/23 8:15 AM"]], date="09-23-2026")
        self.assertEqual(A.messages(rec)[0][0].year, 2026)

    def test_an_unreadable_stamp_drops_the_message_not_the_thread(self):
        rec = _rec([["Out", "", "x", "garbage"], ["Out", "", "y", "09/23 8:15 AM"]])
        self.assertEqual(len(A.messages(rec)), 1)


if __name__ == "__main__":
    unittest.main()
