"""Pins the judgement calls in the SMS audit — the places where a small change
turns a real finding into noise, or hides one.

  python -m unittest automations.sms_audit.test_analyze
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.sms_audit import analyze as A
from automations.sms_audit import rebuttals as RB


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
        # the last message in the window is at 5pm, so the 9am ones are well
        # past the two-hour threshold
        recs = [
            _rec([["Out", "", "hi", "09/23 9:00 AM"], ["In", "", "C", "09/23 9:01 AM"]]),
            _rec([["Out", "", "hi", "09/23 9:00 AM"],
                  ["In", "", "I'm ready for zoom call .", "09/23 9:01 AM"]],
                 name="Left Waiting"),
            _rec([["In", "", "are you there?", "09/23 9:00 AM"],
                  ["Out", "", "yes!", "09/23 5:00 PM"]]),
        ]
        out = A.unanswered(A.as_items(recs))
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
        found = A.anomalies(A.as_items([_rec(th)]))
        self.assertNotIn("Over the carrier limit — 4+ separate texts with no reply between",
                         found)

    def test_four_real_sends_with_no_reply_is_flagged(self):
        th = [["Out", "", "a", "09/23 9:00 AM"], ["Out", "", "b", "09/23 10:00 AM"],
              ["Out", "", "c", "09/23 11:00 AM"], ["Out", "", "d", "09/23 12:00 PM"]]
        found = A.anomalies(A.as_items([_rec(th)]))
        self.assertIn("Over the carrier limit — 4+ separate texts with no reply between",
                      found)

    def test_a_reply_resets_the_run(self):
        th = [["Out", "", "a", "09/23 9:00 AM"], ["Out", "", "b", "09/23 10:00 AM"],
              ["In", "", "hi", "09/23 10:30 AM"],
              ["Out", "", "c", "09/23 11:00 AM"], ["Out", "", "d", "09/23 12:00 PM"]]
        found = A.anomalies(A.as_items([_rec(th)]))
        self.assertNotIn("Over the carrier limit — 4+ separate texts with no reply between",
                         found)


class LookAlikeLinkTest(unittest.TestCase):
    """Raf's Friendly Reminder 1 sends 'us02web.zоom.us' with a CYRILLIC о. It
    resolves to nothing, and it is invisible to anyone reading the template."""

    def test_a_cyrillic_o_in_the_host_is_caught(self):
        th = [["Out", "Friendly Reminder 1",
               "join now https://us02web.zоom.us/j/2935077152", "09/23 8:10 AM"]]
        found = A.anomalies(A.as_items([_rec(th)]))
        key = "Dead link — the web address is spelled with a look-alike letter"
        self.assertIn(key, found)
        self.assertIn("CYRILLIC", found[key][0])

    def test_a_normal_zoom_link_is_left_alone(self):
        th = [["Out", "Friendly Reminder 1",
               "join now https://us02web.zoom.us/j/2935077152", "09/23 8:10 AM"]]
        found = A.anomalies(A.as_items([_rec(th)]))
        self.assertNotIn("Dead link — the web address is spelled with a look-alike letter",
                         found)


class QuietHoursTest(unittest.TestCase):
    """Early morning and late night are counted apart: early is the best
    send window either office has, late has no upside to weigh against it."""

    def test_the_seven_am_blast_groups_by_time_and_template_not_by_name(self):
        recs = [_rec([["Out", "First Interview Confirmation", "x", "09/23 7:00 AM"]],
                     name="A"),
                _rec([["Out", "First Interview Confirmation", "x", "09/23 7:00 AM"]],
                     name="B")]
        found = A.anomalies(A.as_items(recs))
        hits = found["Sent before 8am"]
        self.assertEqual(len(hits), 2)
        self.assertEqual(len(set(hits)), 1)  # one cause, not two findings
        self.assertIn("7:00 AM", hits[0])

    def test_business_hours_are_not_flagged(self):
        found = A.anomalies(A.as_items([_rec([["Out", "", "x", "09/23 10:00 AM"]])]))
        self.assertNotIn("Sent before 8am", found)
        self.assertNotIn("Sent after 9pm", found)


class OptOutTest(unittest.TestCase):
    def test_texting_after_not_interested_is_flagged(self):
        th = [["In", "", "I'm no longer interested", "09/23 9:00 AM"],
              ["Out", "", "see you tomorrow!", "09/23 9:05 AM"]]
        found = A.anomalies(A.as_items([_rec(th)]))
        self.assertIn("Kept texting after they asked us to stop / said no", found)

    def test_stopping_when_asked_is_not_flagged(self):
        th = [["Out", "", "hi", "09/23 9:00 AM"],
              ["In", "", "stop", "09/23 9:01 AM"]]
        found = A.anomalies(A.as_items([_rec(th)]))
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


def _log_row(direction, when, body, sent_by="", applicant="+14698762121",
             applicant_name="Jane Doe", sms_type="", status="Delivered"):
    """One SMS List Report row. The office's own Bandwidth number sits opposite
    the applicant on every row, and which side is which flips with direction."""
    office, office_name = "+14695891180", "ALPHALETE MARKETING, INC. Bandwidth"
    inbound = direction == "In"
    return {"type": direction, "queued_at": when, "sent_at": when,
            "sender": applicant_name if inbound else office_name,
            "sender_phone": applicant if inbound else office,
            "recipient": office_name if inbound else applicant_name,
            "recipient_phone": office if inbound else applicant,
            "source": "AI Messaging" if sent_by == "AI Messaging" else "",
            "sms_type": sms_type, "body": body, "status": status,
            "sent_by": sent_by}


class PhoneJoinTest(unittest.TestCase):
    """The calendar gives 11 bare digits, the log gives E.164. A join that
    misses reads as 'this applicant was never booked' — the worst available
    wrong answer, because it is invisible."""

    def test_the_two_spellings_meet(self):
        self.assertEqual(A.phone10("+14698762121"), A.phone10("14698762121"))
        self.assertEqual(A.phone10("(469) 876-2121"), "4698762121")

    def test_a_junk_number_does_not_become_a_key(self):
        self.assertEqual(A.phone10("0000"), "")
        self.assertEqual(A.phone10(""), "")

    def test_booked_index_keys_on_the_normalised_number(self):
        idx = A.booked_index([_rec([], name="Jane")
                              | {"phone": "14698762121"}])
        self.assertIn("4698762121", idx)


class ConversationGroupingTest(unittest.TestCase):
    def test_the_applicant_is_the_key_not_the_office(self):
        rows = [_log_row("Out", "09-23-2026 09:00 AM", "hi", sent_by="AI Messaging"),
                _log_row("In", "09-23-2026 09:05 AM", "hello?")]
        convos = A.log_conversations(rows)
        self.assertEqual(list(convos), ["4698762121"])
        self.assertEqual(len(convos["4698762121"]["msgs"]), 2)

    def test_two_applicants_stay_apart(self):
        rows = [_log_row("In", "09-23-2026 09:00 AM", "a"),
                _log_row("In", "09-23-2026 09:01 AM", "b",
                         applicant="+19085361289", applicant_name="Sue")]
        self.assertEqual(len(A.log_conversations(rows)), 2)

    def test_booking_state_comes_from_the_calendar_join(self):
        rows = [_log_row("In", "09-23-2026 09:00 AM", "hello?")]
        booked = A.booked_index([_rec([], booked_by="A. Messaging",
                                      status="Interview Completed")
                                 | {"phone": "14698762121"}])
        c = A.log_conversations(rows, booked)["4698762121"]
        self.assertTrue(c["booked"])
        self.assertEqual(c["outcome"], "Interview Completed")

    def test_an_unbooked_conversation_is_still_a_conversation(self):
        rows = [_log_row("In", "09-23-2026 09:00 AM", "hello?")]
        c = A.log_conversations(rows, {})["4698762121"]
        self.assertFalse(c["booked"])


class SentByTest(unittest.TestCase):
    """'Sent By' is the column the calendar walk does not have. It is why the
    log can answer 'how quick are our HUMAN recruiters' without inferring."""

    def test_ai_messaging_is_the_automation(self):
        self.assertTrue(A.is_ai({"sent_by": "AI Messaging", "source": "AI Messaging"}))

    def test_a_named_person_is_not(self):
        self.assertFalse(A.is_ai({"sent_by": "E. Gonzalez", "source": ""}))

    def test_reply_speed_splits_on_the_real_sender(self):
        rows = [_log_row("In", "09-23-2026 09:00 AM", "hello?"),
                _log_row("Out", "09-23-2026 09:01 AM", "hi", sent_by="AI Messaging"),
                _log_row("In", "09-23-2026 10:00 AM", "one more thing"),
                _log_row("Out", "09-23-2026 10:30 AM", "sure", sent_by="V. Rodea")]
        lanes = A.log_reply_speed(A.log_conversations(rows))
        self.assertEqual(lanes["ai"], [1.0])
        self.assertEqual(lanes["human"], [30.0])


class FunnelTest(unittest.TestCase):
    def test_everyone_texted_counts_not_just_the_booked(self):
        rows = [_log_row("Out", "09-23-2026 09:00 AM", "hi", sent_by="AI Messaging"),
                _log_row("Out", "09-23-2026 09:00 AM", "hi", sent_by="AI Messaging",
                         applicant="+19085361289", applicant_name="Sue"),
                _log_row("In", "09-23-2026 09:05 AM", "yes")]
        booked = A.booked_index([_rec([], booked_by="A. Messaging",
                                      status="Interview Completed")
                                 | {"phone": "14698762121"}])
        f = A.funnel(A.log_conversations(rows, booked))
        self.assertEqual(f["contacted"], 2)
        self.assertEqual(f["replied"], 1)
        self.assertEqual(f["booked"], 1)
        self.assertEqual(f["booked_ai"], 1)
        self.assertEqual(f["never_booked"], 1)
        self.assertEqual(f["shown_ai"], 1)

    def test_a_no_show_is_booked_but_not_shown(self):
        rows = [_log_row("Out", "09-23-2026 09:00 AM", "hi")]
        booked = A.booked_index([_rec([], booked_by="E. Gonzalez", status="No Show")
                                 | {"phone": "14698762121"}])
        f = A.funnel(A.log_conversations(rows, booked))
        self.assertEqual((f["booked_human"], f["shown_human"]), (1, 0))


class LogTimestampTest(unittest.TestCase):
    def test_the_log_carries_its_own_year(self):
        self.assertEqual(A._log_ts("09-26-2026 10:16 AM").year, 2026)

    def test_midnight_is_not_noon(self):
        self.assertEqual(A._log_ts("09-26-2026 12:01 AM").hour, 0)
        self.assertEqual(A._log_ts("09-26-2026 12:01 PM").hour, 12)


class BookingsOnlyTest(unittest.TestCase):
    """A --bookings-only walk has no thread, so the Directions template that
    normally corroborates Booked By is absent. Absent is not contradictory —
    treating it as a disagreement would red-flag every row of a healthy pull."""

    def test_no_thread_is_unconfirmed_not_disagreeing(self):
        recs = [_rec([], booked_by="A. Messaging"),
                _rec([], booked_by="E. Gonzalez")]
        mix = A.booking_mix(recs)
        self.assertEqual(mix["disagree"], 0)
        self.assertEqual(mix["unconfirmed"], 2)

    def test_booked_by_is_still_trusted_without_a_thread(self):
        recs = [_rec([], booked_by="A. Messaging"),
                _rec([], booked_by="A. Messaging"),
                _rec([], booked_by="E. Gonzalez")]
        mix = A.booking_mix(recs)
        self.assertEqual((mix["ai"], mix["human"]), (2, 1))

    def test_a_real_disagreement_is_still_caught(self):
        recs = [_rec([["Out", "Directions", "x", "09/23 9:00 AM"]],
                     booked_by="A. Messaging")]
        mix = A.booking_mix(recs)
        self.assertEqual((mix["disagree"], mix["unconfirmed"]), (1, 0))


class AnswerNotNextMessageTest(unittest.TestCase):
    """An ANSWER is a free-typed reply within two hours. The first version
    took the next outbound message full stop and produced nonsense: "Is this
    a real job / who are you?" answered by the "3rd Left Message - Call List"
    template, "What is the job?" answered by "Directions" — scheduled blasts
    that fired on their own timer minutes later (Megan 2026-09-26)."""

    def _one(self, thread):
        return A.question_responses([_rec(thread)])[0]

    def test_a_scheduled_template_is_not_an_answer(self):
        row = self._one([
            ["In", "", "is this a real job?", "09/23 9:00 AM"],
            ["Out", "3rd Left Message - Call List", "hi there", "09/23 9:05 AM"]])
        self.assertEqual(row["answered"], 0)
        self.assertEqual(row["no_reply"], 1)
        self.assertEqual(row["blast"], "3rd Left Message - Call List")

    def test_a_typed_reply_is_an_answer(self):
        row = self._one([
            ["In", "", "what is the pay?", "09/23 9:00 AM"],
            ["Out", "", "Our HR manager goes over pay on the call.", "09/23 9:04 AM"]])
        self.assertEqual(row["answered"], 1)
        self.assertEqual(row["no_reply"], 0)
        self.assertIn("HR manager", row["reply"])

    def test_a_typed_reply_two_days_later_is_not_an_answer(self):
        row = self._one([
            ["In", "", "what is the pay?", "09/23 9:00 AM"],
            ["Out", "", "hey, still interested?", "09/25 9:00 AM"]])
        self.assertEqual(row["answered"], 0)
        self.assertEqual(row["no_reply"], 1)

    def test_a_typed_reply_after_a_blast_still_counts(self):
        # the blast fired first, a person then actually answered inside the
        # window — that is an answer, and the blast is not the story
        row = self._one([
            ["In", "", "is this remote?", "09/23 9:00 AM"],
            ["Out", "Friendly Reminder 1", "starting soon", "09/23 9:01 AM"],
            ["Out", "", "Yes, the first round is over Zoom.", "09/23 9:20 AM"]])
        self.assertEqual(row["answered"], 1)
        self.assertEqual(row["no_reply"], 0)

    def test_the_applicants_name_is_folded_out_of_the_answer(self):
        rows = A.question_responses([
            _rec([["In", "", "what is the pay?", "09/23 9:00 AM"],
                  ["Out", "", "Thanks Ashley, HR covers pay.", "09/23 9:01 AM"]],
                 name="Ashley Smith"),
            _rec([["In", "", "what is the pay?", "09/23 9:00 AM"],
                  ["Out", "", "Thanks Marco, HR covers pay.", "09/23 9:01 AM"]],
                 name="Marco Diaz")])
        self.assertEqual(rows[0]["answered"], 2)
        self.assertEqual(rows[0]["reply_n"], 2)     # ONE response, not two
        self.assertIn("[name]", rows[0]["reply"])


class JoinMissTest(unittest.TestCase):
    def test_a_booking_with_no_messages_is_reported(self):
        convos = {"4698762121": {"phone": "4698762121", "msgs": []}}
        booked = {"4698762121": {}, "5550001111": {}}
        self.assertEqual(A.join_misses(convos, booked), ["5550001111"])

    def test_a_clean_join_reports_nothing(self):
        convos = {"4698762121": {"phone": "4698762121", "msgs": []}}
        self.assertEqual(A.join_misses(convos, {"4698762121": {}}), [])


class SuffixPairingTest(unittest.TestCase):
    """A backfilled column must take BOTH halves from the same pull. It did
    not once: load_office honoured --suffix and load_log did not, so WE 9/4
    got its reply speeds, questions and flags from the week of 9/25 and the
    two columns came out identical (Megan spotted it: "these are identical")."""

    def test_a_suffixed_log_that_does_not_exist_returns_nothing(self):
        rows, src = A.load_log("11580", "definitely-not-a-real-pull")
        self.assertEqual(rows, [])
        self.assertIn("no output/", src)

    def test_a_suffixed_load_never_falls_back_to_the_current_week(self):
        # the unsuffixed file may well exist; a suffixed ask must not take it
        rows, src = A.load_log("11580", "0904")
        if rows:
            self.assertIn("_0904", src)
        else:
            self.assertIn("no output/", src)


LATER = dt.date(2026, 9, 30)   # well past the fixtures' one day, so the
                               # booking-lag hold-out is not what is under test


class DropoffTest(unittest.TestCase):
    """Megan's real question: why isn't each office booking more. Every
    unbooked conversation lands in exactly ONE bucket, so the columns add up
    and the biggest leak is the biggest number."""

    def _c(self, msgs, booked=False):
        return {"phone": "4698762121", "name": "Jane", "booked": booked,
                "booked_by": "", "outcome": "", "msgs": msgs}

    def _m(self, d, mins, body="hi", status="Delivered", template=""):
        return {"when": dt.datetime(2026, 9, 21, 9, 0) + dt.timedelta(minutes=mins),
                "dir": d, "template": template, "body": body, "sent_by": "",
                "source": "", "status": status}

    def test_one_text_and_silence_is_its_own_bucket(self):
        d = A.dropoff({"a": self._c([self._m("Out", 0)])}, window_end=LATER)
        self.assertEqual(d["buckets"]["one text only"], 1)

    def test_several_texts_and_silence_is_a_different_bucket(self):
        d = A.dropoff({"a": self._c([self._m("Out", 0), self._m("Out", 60),
                                     self._m("Out", 120)])}, window_end=LATER)
        self.assertEqual(d["buckets"]["never replied"], 1)
        self.assertNotIn("one text only", d["buckets"])

    def test_they_spoke_last_is_the_fixable_one(self):
        d = A.dropoff({"a": self._c([self._m("Out", 0),
                                     self._m("In", 5, "can we do friday?")])}, window_end=LATER)
        self.assertEqual(d["buckets"]["we never answered"], 1)

    def test_a_polite_sign_off_is_not_us_ignoring_them(self):
        d = A.dropoff({"a": self._c([self._m("Out", 0), self._m("In", 5, "thanks!")])}, window_end=LATER)
        self.assertEqual(d["buckets"]["talked, then stopped"], 1)

    def test_a_decline_is_not_a_leak(self):
        d = A.dropoff({"a": self._c([self._m("Out", 0),
                                     self._m("In", 5, "not interested")])}, window_end=LATER)
        self.assertEqual(d["buckets"]["said no"], 1)

    def test_texts_that_all_failed_mean_they_never_saw_us(self):
        d = A.dropoff({"a": self._c([self._m("Out", 0, status="Error"),
                                     self._m("Out", 60, status="Error")])}, window_end=LATER)
        self.assertEqual(d["buckets"]["never reached them"], 1)

    def test_a_booked_person_is_not_a_dropoff(self):
        d = A.dropoff({"a": self._c([self._m("Out", 0)], booked=True)}, window_end=LATER)
        self.assertEqual(sum(d["buckets"].values()), 0)

    def test_every_unbooked_person_lands_in_exactly_one_bucket(self):
        convos = {
            "a": self._c([self._m("Out", 0)]),
            "b": self._c([self._m("Out", 0), self._m("Out", 60), self._m("Out", 90)]),
            "c": self._c([self._m("Out", 0), self._m("In", 5, "friday?")]),
            "d": self._c([self._m("Out", 0), self._m("In", 5, "not interested")]),
            "e": self._c([self._m("Out", 0, status="Error")]),
            "f": self._c([self._m("Out", 0)], booked=True),
        }
        self.assertEqual(sum(A.dropoff(convos, window_end=LATER)["buckets"].values()), 5)

    def test_the_follow_up_curve_splits_on_how_many_we_sent(self):
        convos = {"a": self._c([self._m("Out", 0)]),
                  "b": self._c([self._m("Out", 0), self._m("Out", 60)], booked=True)}
        curve = A.dropoff(convos, window_end=LATER)["curve"]
        self.assertEqual(curve["one"]["people"], 1)
        self.assertEqual(curve["one"]["booked"], 0)
        self.assertEqual(curve["many"]["people"], 1)
        self.assertEqual(curve["many"]["booked"], 1)


class LeftWaitingThresholdTest(unittest.TestCase):
    """Megan: "for more than 5 min? 10? days?" — there was no threshold, so
    somebody who texted four minutes before the pull counted as ignored.
    Two hours now, measured against the END OF THE DATA rather than the
    clock, so re-reading an old pull cannot reclassify people."""

    def _items(self, last_in_minutes_before_end):
        end = dt.datetime(2026, 9, 25, 17, 0)
        t = end - dt.timedelta(minutes=last_in_minutes_before_end)
        return [("Late Texter", [(end - dt.timedelta(hours=9), "Out", "", "hi"),
                                 (t, "In", "", "can we do friday?")]),
                ("Anchor", [(end, "Out", "", "…")])]

    def test_a_message_from_four_minutes_ago_is_not_being_ignored(self):
        self.assertEqual(A.unanswered(self._items(4)), [])

    def test_a_message_from_this_morning_is(self):
        out = A.unanswered(self._items(6 * 60))
        self.assertEqual([u["name"] for u in out], ["Late Texter"])

    def test_the_clock_is_the_end_of_the_data_not_today(self):
        # re-reading a month-old pull must give the same answer it gave then
        self.assertEqual(A.unanswered(self._items(4)), [])
        self.assertEqual(len(A.unanswered(self._items(180))), 1)

    def test_the_threshold_is_adjustable(self):
        self.assertEqual(len(A.unanswered(self._items(30), min_wait_min=10)), 1)
        self.assertEqual(len(A.unanswered(self._items(30), min_wait_min=120)), 0)


class BookingLagTest(unittest.TestCase):
    """Megan: "are you sure they weren't called and then booked?" A booking
    lands 0-5 days after the first text, so anyone first contacted near the
    end of the window may book in the NEXT week's calendar, which this pull
    cannot see. Calling them "never booked" is a claim the data cannot
    support, so they are held out of every bucket and out of the curve."""

    def _c(self, first_out_day, n_out=1, booked=False):
        msgs = [{"when": dt.datetime(2026, 9, first_out_day, 9, 0) + dt.timedelta(hours=i),
                 "dir": "Out", "template": "", "body": "hi", "sent_by": "",
                 "source": "", "status": "Delivered"} for i in range(n_out)]
        return {"phone": "469876212%d" % first_out_day, "name": "x",
                "booked": booked, "booked_by": "", "outcome": "", "msgs": msgs}

    def test_a_contact_on_the_last_day_is_not_called_a_failure(self):
        convos = {"a": self._c(25)}
        d = A.dropoff(convos, window_end=dt.date(2026, 9, 25))
        self.assertEqual(d["buckets"]["too soon to tell"], 1)
        self.assertNotIn("one text only", d["buckets"])

    def test_a_contact_early_in_the_week_had_its_chance(self):
        convos = {"a": self._c(21)}
        d = A.dropoff(convos, window_end=dt.date(2026, 9, 25))
        self.assertEqual(d["buckets"]["one text only"], 1)
        self.assertNotIn("too soon to tell", d["buckets"])

    def test_the_late_ones_are_out_of_the_follow_up_curve_too(self):
        convos = {"early": self._c(21), "late": self._c(25)}
        curve = A.dropoff(convos, window_end=dt.date(2026, 9, 25))["curve"]
        self.assertEqual(curve["one"]["people"], 1)   # the late one is excluded

    def test_someone_who_booked_is_never_too_soon(self):
        convos = {"a": self._c(25, booked=True)}
        d = A.dropoff(convos, window_end=dt.date(2026, 9, 25))
        self.assertEqual(sum(d["buckets"].values()), 0)


class ColdListTest(unittest.TestCase):
    """Megan: "there should be a 2nd section below for the cold list." The
    log says which is which outright — Source "Mass SMS" is the bulk
    re-engagement blast. Holding the two in one number is what made Raf's
    office look broken: the blast books at 8%, the live flow at 74%."""

    def _row(self, phone, source, direction="Out"):
        return {"type": direction, "sent_at": "09-21-2026 09:00 AM",
                "queued_at": "09-21-2026 09:00 AM", "source": source,
                "sms_type": "", "body": "hi", "status": "Delivered",
                "sent_by": "", "sender": "office", "sender_phone": "+14695891180",
                "recipient": "them", "recipient_phone": phone}

    def _convos(self, rows, booked=()):
        return A.log_conversations(rows, {p: {"booked_by": "", "status": ""}
                                          for p in booked})

    def test_mass_sms_recipients_are_the_cold_list(self):
        rows = [self._row("+14690000001", "Mass SMS"),
                self._row("+14690000002", "AI Messaging")]
        out = A.lanes(self._convos(rows), rows)
        self.assertEqual(out["cold"]["people"], 1)
        self.assertEqual(out["live"]["people"], 1)

    def test_one_blast_puts_a_person_in_the_cold_lane_for_good(self):
        # they got the blast AND normal follow-up; they are still cold-sourced
        rows = [self._row("+14690000001", "Mass SMS"),
                self._row("+14690000001", "AI Messaging")]
        out = A.lanes(self._convos(rows), rows)
        self.assertEqual(out["cold"]["people"], 1)
        self.assertEqual(out["live"]["people"], 0)

    def test_an_office_with_no_blast_has_an_empty_cold_lane(self):
        # Carlos runs none, which is most of why his booking rate looks better
        rows = [self._row("+14690000001", "AI Messaging")]
        out = A.lanes(self._convos(rows), rows)
        self.assertEqual(out["cold"]["people"], 0)
        self.assertEqual(out["live"]["people"], 1)


class DeliveryReasonTest(unittest.TestCase):
    """Megan: "we need to know why it never reached them." """

    def _row(self, phone, status, at="09-21-2026 09:00 AM"):
        return {"type": "Out", "sent_at": at, "queued_at": at, "source": "",
                "sms_type": "", "body": "hi", "status": status, "sent_by": "",
                "sender": "office", "sender_phone": "+14695891180",
                "recipient": "them", "recipient_phone": phone}

    def test_each_status_is_counted_by_its_own_name(self):
        d = A.delivery_reasons([self._row("+14690000001", "Delivered"),
                                self._row("+14690000002", "Failed"),
                                self._row("+14690000003", "Dummy Phone")])
        self.assertEqual(d["by_status"]["Failed"], 1)
        self.assertEqual(d["by_status"]["Dummy Phone"], 1)
        self.assertEqual(d["undelivered"], 2)

    def test_the_failure_rate_is_split_first_text_vs_later(self):
        # the pattern that explains most of them: the carrier starts refusing
        # once we have already sent several
        rows = [self._row("+14690000001", "Delivered", "09-21-2026 09:00 AM"),
                self._row("+14690000001", "Failed", "09-21-2026 10:00 AM"),
                self._row("+14690000001", "Failed", "09-21-2026 11:00 AM")]
        d = A.delivery_reasons(rows)
        self.assertEqual(d["first_rate"], 0.0)
        self.assertEqual(d["later_rate"], 100.0)

    def test_no_messages_gives_no_rate_rather_than_zero(self):
        d = A.delivery_reasons([])
        self.assertIsNone(d["first_rate"])


class SendWindowTest(unittest.TestCase):
    """Megan: "is the response rate to them lower or higher? I think this
    might be a positive and not an issue." It is higher — 38% before 8am
    against 31% in the day for Raf — so early sending is reported as
    performance, not as a fault."""

    def _convo(self, hours, reply_after=None):
        base = dt.datetime(2026, 9, 21, 0, 0)
        msgs = [{"when": base + dt.timedelta(hours=h), "dir": "Out",
                 "template": "", "body": "hi", "sent_by": "", "source": "",
                 "status": "Delivered"} for h in hours]
        if reply_after is not None:
            msgs.append({"when": base + dt.timedelta(hours=reply_after, minutes=30),
                         "dir": "In", "template": "", "body": "yes", "sent_by": "",
                         "source": "", "status": "Delivered"})
        return {"a": {"phone": "4698762121", "name": "x", "booked": False,
                      "booked_by": "", "outcome": "", "msgs": msgs}}

    def test_the_day_splits_into_bands_an_office_can_act_on(self):
        w = A.send_windows(self._convo([7, 10, 14, 19, 22]))
        self.assertEqual(w["6-8am"]["sent"], 1)
        self.assertEqual(w["8am-12pm"]["sent"], 1)
        self.assertEqual(w["12-5pm"]["sent"], 1)
        self.assertEqual(w["5-9pm"]["sent"], 1)
        self.assertEqual(w["after 9pm"]["sent"], 1)

    def test_a_reply_within_two_hours_counts_for_that_window(self):
        w = A.send_windows(self._convo([7], reply_after=7))
        self.assertEqual(w["6-8am"]["replied"], 1)

    def test_an_undelivered_text_cannot_be_replied_to(self):
        c = self._convo([7])
        c["a"]["msgs"][0]["status"] = "Failed"
        self.assertEqual(A.send_windows(c)["6-8am"]["sent"], 0)


class BestHourTest(unittest.TestCase):
    """Megan: "notate the timeframe that the office has the highest response
    rate." Thin hours are dropped — a 4-send hour at 100% would take the top
    slot every week and send the office to the wrong time."""

    def _convos(self, spec):
        """spec: {hour: (sent, replied)}"""
        base, out = dt.datetime(2026, 9, 21, 0, 0), {}
        i = 0
        for hour, (sent, replied) in spec.items():
            for k in range(sent):
                i += 1
                msgs = [{"when": base + dt.timedelta(hours=hour), "dir": "Out",
                         "template": "", "body": "hi", "sent_by": "", "source": "",
                         "status": "Delivered"}]
                if k < replied:
                    msgs.append({"when": base + dt.timedelta(hours=hour, minutes=10),
                                 "dir": "In", "template": "", "body": "y",
                                 "sent_by": "", "source": "", "status": "Delivered"})
                out[str(i)] = {"phone": str(i), "name": "x", "booked": False,
                               "booked_by": "", "outcome": "", "msgs": msgs}
        return out

    def test_a_thin_hour_cannot_win(self):
        convos = self._convos({7: (4, 4), 13: (100, 40)})
        self.assertEqual(A.best_hours_label(convos), "1pm (40%)")

    def test_hours_are_ranked_by_rate_not_volume(self):
        convos = self._convos({7: (60, 30), 13: (400, 40)})
        self.assertTrue(A.best_hours_label(convos).startswith("7am (50%)"))

    def test_the_clock_reads_like_a_person_wrote_it(self):
        self.assertEqual(A.clock(7), "7am")
        self.assertEqual(A.clock(13), "1pm")
        self.assertEqual(A.clock(0), "12am")
        self.assertEqual(A.clock(12), "12pm")


class TextsToBookTest(unittest.TestCase):
    """Megan 2026-09-26: "how many texts do people who book for a 1st round
    receive from us on average BEFORE setting up the interview — so the
    directional / 2nd interview texts wouldn't be counted here." The booking
    moment is the earliest post-booking template: Directions and the
    confirmations cannot fire until an interview exists."""

    def _c(self, seq, booked=True):
        """seq: [(minutes, 'In'|'Out', template)]"""
        base = dt.datetime(2026, 9, 21, 9, 0)
        return {"phone": "4698762121", "name": "x", "booked": booked,
                "booked_by": "", "outcome": "",
                "msgs": [{"when": base + dt.timedelta(minutes=m), "dir": d,
                          "template": t, "body": "x", "sent_by": "",
                          "source": "", "status": "Delivered"}
                         for m, d, t in seq]}

    def test_texts_after_the_booking_are_not_counted(self):
        out = A.texts_to_book({"a": self._c([
            (0, "Out", ""), (5, "In", ""), (10, "Out", ""),
            (20, "Out", "Directions"),          # <- booked here
            (30, "Out", "Friendly Reminder 1"),
            (40, "Out", "2nd Interview Invite")])})
        self.assertEqual(out["average"], 2.0)

    def test_inbound_messages_are_not_texts_we_sent(self):
        out = A.texts_to_book({"a": self._c([
            (0, "Out", ""), (1, "In", ""), (2, "In", ""),
            (10, "Out", "Directions AI")])})
        self.assertEqual(out["average"], 1.0)

    def test_a_marker_with_nothing_before_it_is_not_a_zero(self):
        """Superseded by CarriedInBookingTest: a thread whose first in-window
        message IS the booking marker was booked before the window opened, so
        its opening texts are outside the pull and it cannot be scored."""
        self.assertIsNone(A.texts_to_book({"a": self._c([(0, "Out", "Directions")])}))

    def test_people_who_never_booked_are_not_in_it(self):
        self.assertIsNone(A.texts_to_book({"a": self._c([(0, "Out", "")], booked=False)}))

    def test_a_booking_with_no_marker_is_left_out_not_counted_as_zero(self):
        # no Directions, no confirmation — we cannot say when it was booked,
        # and guessing zero would drag the average down
        self.assertIsNone(A.texts_to_book({"a": self._c([(0, "Out", ""), (5, "Out", "")])}))

    def test_the_earliest_marker_wins_not_the_last(self):
        out = A.texts_to_book({"a": self._c([
            (0, "Out", ""), (10, "Out", "First Interview Confirmation"),
            (20, "Out", ""), (30, "Out", "Directions")])})
        self.assertEqual(out["average"], 1.0)


class BreakdownSumsToParentTest(unittest.TestCase):
    """A + expansion that does not add up to the row above it is worse than
    no expansion. The unreachable reasons are tallied inside the same loop
    that fills the bucket, so they cannot drift — computed separately they
    did: the parent applied the too-recent hold-out and the second pass did
    not, and 87 expanded into 110."""

    def _c(self, day, statuses, booked=False):
        base = dt.datetime(2026, 9, day, 9, 0)
        return {"phone": "469876212%d" % day, "name": "x", "booked": booked,
                "booked_by": "", "outcome": "",
                "msgs": [{"when": base + dt.timedelta(minutes=i * 10), "dir": "Out",
                          "template": "", "body": "x", "sent_by": "", "source": "",
                          "status": st} for i, st in enumerate(statuses)]}

    def test_the_reasons_add_up_to_the_bucket(self):
        convos = {"a": self._c(21, ["Failed", "Failed"]),
                  "b": self._c(22, ["Requeued"]),
                  "c": self._c(23, ["Dummy Phone"])}
        d = A.dropoff(convos, window_end=dt.date(2026, 9, 30))
        self.assertEqual(sum(d["unreached_why"].values()),
                         d["buckets"]["never reached them"])

    def test_a_held_out_person_is_in_neither(self):
        # texted on the last day: too recent to judge, so not in the bucket
        # AND not in the breakdown
        convos = {"late": self._c(25, ["Failed"])}
        d = A.dropoff(convos, window_end=dt.date(2026, 9, 25))
        self.assertEqual(d["buckets"].get("never reached them", 0), 0)
        self.assertEqual(sum(d["unreached_why"].values()), 0)

    def test_a_person_is_filed_under_their_commonest_failure(self):
        convos = {"a": self._c(21, ["Failed", "Failed", "Requeued"])}
        d = A.dropoff(convos, window_end=dt.date(2026, 9, 30))
        self.assertEqual(d["unreached_why"]["Failed"], 1)
        self.assertEqual(d["unreached_why"]["Requeued"], 0)


class CarriedInBookingTest(unittest.TestCase):
    """Megan: "this doesn't seem likely because when an applicant's resume is
    processed they are automatically sent a text?" Right — a booking with no
    text before it was almost always booked BEFORE the window opened, so its
    opening texts are outside the pull. 94 of Raf's 111 had their first
    in-window message at Monday 06:45, a confirmation for last week's
    interview. Counting those as "booked with zero texts" was wrong."""

    def _c(self, seq):
        base = dt.datetime(2026, 9, 21, 9, 0)
        return {"phone": "4698762121", "name": "x", "booked": True,
                "booked_by": "", "outcome": "",
                "msgs": [{"when": base + dt.timedelta(minutes=m), "dir": d,
                          "template": t, "body": "x", "sent_by": "",
                          "source": "", "status": "Delivered"}
                         for m, d, t in seq]}

    def test_a_marker_with_nothing_before_it_is_carried_in(self):
        out = A.texts_to_book({"a": self._c([(0, "Out", "First Interview Confirmation")])})
        self.assertIsNone(out)   # nothing measurable at all

    def test_it_is_counted_separately_not_as_zero(self):
        out = A.texts_to_book({
            "carried": self._c([(0, "Out", "First Interview Confirmation")]),
            "real": self._c([(0, "Out", ""), (10, "Out", ""),
                             (20, "Out", "Directions")])})
        self.assertEqual(out["carried_in"], 1)
        self.assertEqual(out["n"], 1)
        self.assertEqual(out["average"], 2.0)

    def test_a_genuine_phone_booking_still_counts_as_zero(self):
        # they DID say something first — we just never texted before booking
        out = A.texts_to_book({"a": self._c([(0, "In", ""), (10, "Out", "Directions")])})
        self.assertEqual(out["zero"], 1)
        self.assertEqual(out["carried_in"], 0)


class ApplicantReplySpeedTest(unittest.TestCase):
    """Megan 2026-09-27: "shouldn't this be how fast the applicant replies? or
    maybe avg response time of an applicant." The section measures OUR speed;
    theirs is the other half — it is how long the conversation window stays
    open, and a recruiter answering an hour later has missed them."""

    def _c(self, seq):
        base = dt.datetime(2026, 9, 21, 9, 0)
        return {"phone": "4698762121", "name": "x", "booked": False,
                "booked_by": "", "outcome": "",
                "msgs": [{"when": base + dt.timedelta(minutes=m), "dir": d,
                          "template": "", "body": "x", "sent_by": "",
                          "source": "", "status": st}
                         for m, d, st in seq]}

    def test_it_measures_from_our_text_to_their_answer(self):
        gaps = A.applicant_reply_speed({"a": self._c([
            (0, "Out", "Delivered"), (12, "In", "Delivered")])})
        self.assertEqual(gaps, [12.0])

    def test_a_text_that_never_arrived_cannot_be_answered(self):
        self.assertEqual(A.applicant_reply_speed({"a": self._c([
            (0, "Out", "Failed"), (12, "In", "Delivered")])}), [])

    def test_an_answer_two_days_later_is_not_a_reply_to_that_text(self):
        self.assertEqual(A.applicant_reply_speed({"a": self._c([
            (0, "Out", "Delivered"), (60 * 48, "In", "Delivered")])}), [])

    def test_our_own_messages_are_not_their_replies(self):
        self.assertEqual(A.applicant_reply_speed({"a": self._c([
            (0, "Out", "Delivered"), (5, "Out", "Delivered")])}), [])


class TextErrorTest(unittest.TestCase):
    """Megan 2026-09-27: "can you see if there are any texts that are
    answered grammatically incorrect… and who sent the text". Typos come from
    the corpus itself — a word used twice all week that is one edit from a
    word used twenty-five times — filtered against a system word list,
    because rarity alone flagged "Oct", "info" and "area"."""

    def _convos(self, msgs, name="Jane Doe"):
        base = dt.datetime(2026, 9, 21, 9, 0)
        return {"a": {"phone": "4698762121", "name": name, "booked": False,
                      "booked_by": "", "outcome": "",
                      "msgs": [{"when": base + dt.timedelta(minutes=i),
                                "dir": "Out", "template": "", "body": b,
                                "sent_by": who, "source": "", "status": "Delivered"}
                               for i, (b, who) in enumerate(msgs)]}}

    def test_a_doubled_word_is_caught_with_its_sender(self):
        errs = A.text_errors(self._convos([("We are in the the Frisco area.", "Dee")]))
        d = [e for e in errs if e["kind"] == "doubled word"]
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["sender"], "Dee")

    def test_a_missing_space_after_a_full_stop_is_caught(self):
        errs = A.text_errors(self._convos([("not a remote position.Are you in?", "Sandy")]))
        self.assertTrue([e for e in errs if e["kind"] == "missing space"])

    def test_a_template_is_not_a_persons_typing(self):
        base = dt.datetime(2026, 9, 21, 9, 0)
        convos = {"a": {"phone": "1", "name": "x", "booked": False,
                        "booked_by": "", "outcome": "",
                        "msgs": [{"when": base, "dir": "Out",
                                  "template": "Directions", "body": "the the",
                                  "sent_by": "Sandy", "source": "",
                                  "status": "Delivered"}]}}
        self.assertEqual(A.text_errors(convos), [])

    def test_an_applicants_own_message_is_not_our_mistake(self):
        base = dt.datetime(2026, 9, 21, 9, 0)
        convos = {"a": {"phone": "1", "name": "x", "booked": False,
                        "booked_by": "", "outcome": "",
                        "msgs": [{"when": base, "dir": "In", "template": "",
                                  "body": "the the", "sent_by": "", "source": "",
                                  "status": "Delivered"}]}}
        self.assertEqual(A.text_errors(convos), [])

    def test_a_real_word_is_never_a_typo(self):
        if not A.spellcheck_available():
            self.skipTest("no word list on this machine")
        self.assertTrue(A._known("info", A._dictionary()))
        self.assertTrue(A._known("rescheduled", A._dictionary()))
        self.assertFalse(A._known("intrested", A._dictionary()))


class DodgedQuestionTest(unittest.TestCase):
    """Megan 2026-09-27: "we need to know if someone asks a direct question
    and the recruiter skirts around it or doesn't answer it in a professional
    way." """

    def _convos(self, q, a, who="Sandy"):
        base = dt.datetime(2026, 9, 21, 9, 0)
        return {"a": {"phone": "1", "name": "x", "booked": False,
                      "booked_by": "", "outcome": "",
                      "msgs": [
                          {"when": base, "dir": "In", "template": "", "body": q,
                           "sent_by": "", "source": "", "status": "Delivered"},
                          {"when": base + dt.timedelta(minutes=5), "dir": "Out",
                           "template": "", "body": a, "sent_by": who,
                           "source": "", "status": "Delivered"}]}}

    def test_an_off_topic_answer_is_a_dodge(self):
        out = A.dodged_questions(self._convos(
            "Is this position salary based or commission based?",
            "You can call this number or text us at anytime."))
        self.assertEqual([x["kind"] for x in out], ["dodged"])
        self.assertEqual(out[0]["sender"], "Sandy")

    def test_an_on_topic_answer_is_not(self):
        out = A.dodged_questions(self._convos(
            # Megan 2026-09-27 ruled out the word "base"; the wording here
            # is the current approved line, so the fixture does not teach
            # copy the business has moved off.
            "What is the pay?", "Weekly pay ranging from $1,000-$1,500."))
        self.assertEqual(out, [])

    def test_yes_answers_a_yes_no_question_without_repeating_it(self):
        # "is it fine if I wear regular clothes?" -> "That is totally fine!"
        out = A.dodged_questions(self._convos(
            "is it fine if I have regular clothes on?", "That is totally fine!"))
        self.assertEqual(out, [])

    def test_pushing_the_answer_to_a_call_is_flagged_separately(self):
        out = A.dodged_questions(self._convos(
            "What is the pay?", "The hiring manager will go over that on the call."))
        self.assertEqual([x["kind"] for x in out], ["deflected"])

    def test_texting_shorthand_is_flagged(self):
        out = A.dodged_questions(self._convos(
            "What is the pay?", "idk, weekly pay is $1,000-$1,500"))
        self.assertIn("informal", [x["kind"] for x in out])

    def test_a_question_with_no_known_vocabulary_is_left_alone(self):
        out = A.dodged_questions(self._convos(
            "Did you know my maiden name is Pena?", "Ha, small world!"))
        self.assertEqual(out, [])


class GrammarAndPrecisionTest(unittest.TestCase):
    """Megan 2026-09-27, on one of Sandy's texts: "this has way more issues
    than spacing." It held six — a bare verb, two misspellings, two missing
    spaces and a your/you're — and the checker had found one."""

    SANDY = ("We offer a weekly salary pay for the role the base salary is "
             "determine on your backround experience plus bonuses or "
             "commission.Is an average between $800-$1200 weekly.Does that "
             "fall between the rage your looking for?")

    def _convos(self, body, who="Sandy"):
        """One message, plus a handful of ordinary ones carrying the words a
        correction is drawn from. The checker takes its corrections from the
        office's OWN vocabulary, so a one-message corpus has nothing to
        suggest — which is the design, not a gap: a dictionary search for
        near-matches produced "callback → fallback" and "paid → pail"."""
        base = dt.datetime(2026, 9, 21, 9, 0)
        filler = ("Your background and experience are a great fit, and we "
                  "are interested in your background for this role.")
        msgs = [{"when": base + dt.timedelta(minutes=i), "dir": "Out",
                 "template": "", "body": filler, "sent_by": who,
                 "source": "", "status": "Delivered"} for i in range(6)]
        msgs.append({"when": base + dt.timedelta(minutes=30), "dir": "Out",
                     "template": "", "body": body, "sent_by": who,
                     "source": "", "status": "Delivered"})
        return {"a": {"phone": "1", "name": "Jane Doe", "booked": False,
                      "booked_by": "", "outcome": "", "msgs": msgs}}

    def test_that_one_text_yields_several_kinds(self):
        kinds = {e["kind"] for e in A.text_errors(self._convos(self.SANDY))}
        for expected in ("spelling", "grammar", "missing space", "verb form"):
            self.assertIn(expected, kinds, expected)

    def test_a_misspelling_is_caught_even_when_the_right_word_is_rare(self):
        """"background" appears six times in the week; requiring a COMMON
        near-match meant "backround" was never flagged."""
        if not A.spellcheck_available():
            self.skipTest("no word list on this machine")
        details = [e["detail"] for e in A.text_errors(self._convos(self.SANDY))]
        self.assertTrue(any("backround" in d for d in details), details)

    def test_your_youre_is_caught(self):
        details = [e["detail"] for e in A.text_errors(
            self._convos("Your welcome, let me know what your looking for"))]
        self.assertTrue(any("you're" in d for d in details), details)

    def test_a_curly_apostrophe_is_still_an_apostrophe(self):
        # "wasn’t" was being read as the non-word "wasn"
        errs = A.text_errors(self._convos("This wasn’t an easy decision."))
        self.assertEqual([e for e in errs if e["kind"] == "spelling"], [])

    def test_a_link_is_not_prose(self):
        errs = A.text_errors(self._convos(
            "Here is the link https://us02web.zoom.us/j/123 and "
            "noreply@blueinkmail.com"))
        self.assertEqual([e for e in errs if e["kind"] == "spelling"], [])

    def test_house_vocabulary_is_not_a_typo(self):
        # a word the office uses constantly is not one person's slip
        body = "Your onboarding packet is ready."
        convos = self._convos(body)
        for i in range(6):
            convos["p%d" % i] = self._convos(body)["a"]
        details = [e["detail"] for e in A.text_errors(convos)
                   if e["kind"] == "spelling"]
        self.assertFalse(any("onboarding" in d for d in details), details)


class DoubledWordTest(unittest.TestCase):
    """Megan 2026-09-27: "we work with AT&T so this isn't a double word
    here." The & splits the brand into a token that matches the preceding
    preposition, so "at AT&T" looked like "at at"."""

    def _errs(self, body):
        base = dt.datetime(2026, 9, 21, 9, 0)
        return A.text_errors({"a": {
            "phone": "1", "name": "x", "booked": False, "booked_by": "",
            "outcome": "", "msgs": [{"when": base, "dir": "Out", "template": "",
                                     "body": body, "sent_by": "Jorge",
                                     "source": "", "status": "Delivered"}]}})

    def test_at_att_is_not_a_doubled_word(self):
        errs = self._errs("this is George with the Talent Team at AT&T.")
        self.assertEqual([e for e in errs if e["kind"] == "doubled word"], [])

    def test_a_word_before_any_acronym_is_not_doubled(self):
        errs = self._errs("send it to IT for review")
        self.assertEqual([e for e in errs if e["kind"] == "doubled word"], [])

    def test_a_real_repeat_is_still_caught(self):
        errs = self._errs("We are in the the Frisco area.")
        self.assertTrue([e for e in errs if e["kind"] == "doubled word"])


class ShortYesIsAnAnswerTest(unittest.TestCase):
    """A short, direct yes IS the answer, wherever the question word sits.
    "My apologies… is it fine if I have regular clothes on?" answered "That
    is totally fine!" was called a dodge because the reply carries no
    clothing words and the question does not OPEN with "is"."""

    def _convos(self, q, a):
        base = dt.datetime(2026, 9, 21, 9, 0)
        return {"a": {"phone": "1", "name": "Jose", "booked": False,
                      "booked_by": "", "outcome": "",
                      "msgs": [
                          {"when": base, "dir": "In", "template": "", "body": q,
                           "sent_by": "", "source": "", "status": "Delivered"},
                          {"when": base + dt.timedelta(minutes=3), "dir": "Out",
                           "template": "", "body": a, "sent_by": "Erika",
                           "source": "", "status": "Delivered"}]}}

    def test_a_yes_buried_mid_question_still_counts(self):
        out = A.dodged_questions(self._convos(
            "My apologies, I'm on campus, is it fine if I have regular "
            "clothes on?", "That is totally fine!"))
        self.assertEqual(out, [])

    def test_a_choice_question_is_not_answered_by_yes(self):
        out = A.dodged_questions(self._convos(
            "Is this position salary based or commission based?",
            "That is totally fine!"))
        self.assertEqual([x["kind"] for x in out], ["dodged"])

    def test_a_long_reply_is_judged_on_its_content_not_its_opening(self):
        out = A.dodged_questions(self._convos(
            "What is the pay?",
            "Yes! " + "We will go over everything about the role and the "
            "team and the office and the schedule when you come in. " * 2))
        self.assertEqual([x["kind"] for x in out], ["dodged"])

    def test_the_question_and_reply_are_kept_whole(self):
        q = ("Hi there, before we talk I wanted to ask one thing. "
             "What is the pay for this role? " + "I ask because I am "
             "comparing a few offers at the moment. " * 4)
        out = A.dodged_questions(self._convos(q, "You can call this number."))
        self.assertTrue(out)
        self.assertEqual(out[0]["question"], " ".join(q.split()))


class WhenIsAnsweredByATimeTest(unittest.TestCase):
    """Megan 2026-09-27, on "Yes when will that be?" answered "Are you
    available tomorrow at 9:45?": "she's clarifying so looks like an
    answer." A question about WHEN is answered by a time, whatever bucket
    the question landed in."""

    def _convos(self, q, a):
        base = dt.datetime(2026, 9, 21, 9, 0)
        return {"a": {"phone": "1", "name": "Tiffani", "booked": False,
                      "booked_by": "", "outcome": "",
                      "msgs": [
                          {"when": base, "dir": "In", "template": "", "body": q,
                           "sent_by": "", "source": "", "status": "Delivered"},
                          {"when": base + dt.timedelta(minutes=2), "dir": "Out",
                           "template": "", "body": a, "sent_by": "Tiffani B",
                           "source": "", "status": "Delivered"}]}}

    def test_a_clock_time_answers_when(self):
        self.assertEqual(A.dodged_questions(self._convos(
            "Yes when will that be?", "Are you available tomorrow at 9:45?")), [])

    def test_a_weekday_answers_when(self):
        self.assertEqual(A.dodged_questions(self._convos(
            "when will that be?", "We can do Thursday if that works.")), [])

    def test_a_when_question_with_no_time_in_the_reply_is_still_a_dodge(self):
        out = A.dodged_questions(self._convos(
            "What is the pay and when will that be?",
            "Our headquarters are in Irving."))
        self.assertEqual([x["kind"] for x in out], ["dodged"])


class JobTitleAnswersTheRoleTest(unittest.TestCase):
    """Megan 2026-09-27: "What position?" answered "This is for the Entry
    Level Account Representative." Naming the job IS naming the role, even
    without the word "position" in the reply."""

    def _pair(self, q, a):
        base = dt.datetime(2026, 9, 21, 9, 0)
        return {"a": {"phone": "1", "name": "Maria", "booked": False,
                      "booked_by": "", "outcome": "",
                      "msgs": [
                          {"when": base, "dir": "In", "template": "", "body": q,
                           "sent_by": "", "source": "", "status": "Delivered"},
                          {"when": base + dt.timedelta(minutes=2), "dir": "Out",
                           "template": "", "body": a, "sent_by": "M",
                           "source": "", "status": "Delivered"}]}}

    def test_a_job_title_answers_what_position(self):
        self.assertEqual(A.dodged_questions(self._pair(
            "What position?",
            "This is for the Entry Level Account Representative.")), [])

    def test_other_titles_count_too(self):
        for title in ("Sales Associate", "Brand Ambassador",
                      "Appointment Setter", "Account Manager"):
            self.assertEqual(A.dodged_questions(self._pair(
                "What position is this for?", "It is the " + title)), [],
                title)

    def test_a_reply_naming_no_job_is_still_a_dodge(self):
        out = A.dodged_questions(self._pair(
            "What position?", "Our office is in Irving, see you then!"))
        self.assertEqual([x["kind"] for x in out], ["dodged"])


class SpellcheckPrecisionTest(unittest.TestCase):
    """web2 is a 1934 BASE-FORM word list. It has no "paid", "using",
    "planning", "callback", "coordinate" or "download" in it, so treating
    "absent from the dictionary" as "misspelled" flagged ordinary words and
    then matched them to whatever sat one letter away — "using → suing",
    "paid → pail", "callback → fallback" (Megan 2026-09-27: "I think this
    spelling is correct?").

    The dictionary is a VETO now, never the source of a correction: a word
    it contains is never a typo, and a correction only ever comes from what
    this office actually writes."""

    def _corpus(self, body):
        base = dt.datetime(2026, 9, 21, 9, 0)
        filler = "We will join the Zoom using the browser, standby please."
        msgs = [{"when": base + dt.timedelta(minutes=i), "dir": "Out",
                 "template": "", "body": filler, "sent_by": "Dee",
                 "source": "", "status": "Delivered"} for i in range(6)]
        msgs.append({"when": base + dt.timedelta(minutes=30), "dir": "Out",
                     "template": "", "body": body, "sent_by": "Dee",
                     "source": "", "status": "Delivered"})
        return {"a": {"phone": "1", "name": "x", "booked": False,
                      "booked_by": "", "outcome": "", "msgs": msgs}}

    def _spellings(self, body):
        return [e["detail"] for e in A.text_errors(self._corpus(body))
                if e["kind"] == "spelling"]

    def test_ordinary_modern_words_are_not_typos(self):
        for word in ("standby", "using", "download", "callback", "paid",
                     "planning", "coordinate"):
            self.assertEqual(
                self._spellings("You can join {} now".format(word)), [],
                word)

    def test_a_correction_is_always_named(self):
        for detail in self._spellings("Sorry, I will be on standbi"):
            self.assertIn("→", detail)

    def test_a_transposition_is_one_typo(self):
        # "perfer" for "prefer" is the commonest slip there is
        self.assertTrue(A._edit1("perfer", "prefer"))
        self.assertTrue(A._edit1("teh", "the"))

    def test_spanish_is_not_spellchecked_against_an_english_list(self):
        self.assertEqual(self._spellings(
            "¿A qué correo te envío el enlace de Zoom?"), [])
        self.assertEqual(self._spellings(
            "Te dejaron entrar de nuevo pero no respondiste."), [])


class FoldRepeatsTest(unittest.TestCase):
    """Megan 2026-09-27: count the things there are to FIX, not the sends.

    Raf's 565 lowercase-'i' texts were six messages — 560 of them one saved
    line of Dante's. Per send, one unfixed sentence read as a team-wide
    collapse in writing standards and buried Carlos's 34 separate mistakes."""

    COPY = ("Hey {} , I tried calling a few times about your application. "
            "My names Dani, so i wanted to see you were still looking?")

    def _e(self, name, sender="Dante", kind="lowercase i", detail="i"):
        return {"kind": kind, "sender": sender, "detail": detail,
                "body": self.COPY.format(name), "name": name}

    def test_one_saved_line_to_many_people_is_one_entry(self):
        got = A._fold_repeats([self._e("Preston"), self._e("Cassandra"),
                               self._e("Mia")])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["sent"], 3)

    def test_it_folds_even_when_no_name_is_on_record(self):
        # 13 of Dante's 564 went to applicants with no name stored, so the
        # name stayed in the body and each keyed as its own message.
        a, b = self._e("Preston"), self._e("Christopher")
        b["name"] = ""
        self.assertEqual(len(A._fold_repeats([a, b])), 1)

    def test_two_people_sending_the_same_copy_stay_apart(self):
        a, b = self._e("Preston"), self._e("Preston", sender="Leticia")
        got = A._fold_repeats([a, b])
        self.assertEqual(len(got), 2)
        self.assertEqual({x["sent"] for x in got}, {1})

    def test_two_different_mistakes_in_one_message_stay_apart(self):
        a = self._e("Preston")
        b = self._e("Preston", kind="spelling", detail="intrested → interested")
        self.assertEqual(len(A._fold_repeats([a, b])), 2)

    def test_genuinely_different_messages_are_not_merged(self):
        a = self._e("Preston")
        b = dict(a, body="Your welcome, see you then")
        self.assertEqual(len(A._fold_repeats([a, b])), 2)

    def test_every_entry_carries_a_sent_count(self):
        for e in A._fold_repeats([self._e("Preston")]):
            self.assertEqual(e["sent"], 1)

    def test_the_signature_ignores_capitalised_words_only(self):
        # names are capitalised; the copy's lowercase words are its identity
        self.assertEqual(A._same_copy("Hey Preston , so i wanted", ""),
                         A._same_copy("Hey Cassandra , so i wanted", ""))
        self.assertNotEqual(A._same_copy("so i wanted", ""),
                            A._same_copy("so i needed", ""))


class ShoutingFalsePositiveTest(unittest.TestCase):
    """Megan 2026-10-01: the expandable examples exist so a recruiter can
    argue with a count. The first three they would have argued with were
    all ours, so each is pinned here."""

    def test_a_job_ad_title_in_caps_is_not_shouting(self):
        # all 14 of Aisha Ceron's "shouts" in 11280 were this string
        self.assertIsNone(RB.shouts(
            "Congrats on being invited to a second interview for the "
            "ENTRY LEVEL CUSTOMER REPRESENTATIVE role!"))

    def test_the_company_signature_is_not_shouting(self):
        self.assertIsNone(RB.shouts("Sent by ALPHALETE MARKETING, INC"))
        self.assertIsNone(RB.shouts("VANTURA SOLUTIONS LLC"))

    def test_an_uppercased_email_is_not_shouting(self):
        self.assertIsNone(RB.shouts(
            "Could you please verify that your email address is "
            "VEGAMARTHA01@GMAIL.COM?"))

    def test_real_shouting_still_counts(self):
        self.assertEqual(RB.shouts("You MUST BE ON TIME"), "MUST BE ON TIME")
        self.assertEqual(
            RB.shouts("DO NOT BE LATE for KAYLA.TERAN6122@GMAIL.COM"), "LATE")


class PersonaTest(unittest.TestCase):
    """Megan 2026-10-01 asked what "4 different names front this office"
    meant. Checking turned up three bugs behind it, each pinned here."""

    def setUp(self):
        from automations.sms_audit import templates as T
        self.T = T

    def test_a_lowercase_lead_in_still_finds_the_name(self):
        self.assertEqual(
            self.T.PERSONA.findall("Hey, It's Dani reaching out again."),
            ["Dani"])

    def test_the_name_must_still_be_capitalised(self):
        # re.I on the whole pattern caught "Dani reaching" and "you"
        self.assertEqual(self.T.PERSONA.findall("it's you I wanted"), [])

    def test_a_first_name_folds_into_the_full_name(self):
        import collections
        folded = self.T.fold_personas(
            collections.Counter({"Dani": 2, "Dani Pena": 1}))
        self.assertEqual(dict(folded), {"Dani Pena": 3})

    def test_two_danis_do_not_fold(self):
        import collections
        folded = self.T.fold_personas(
            collections.Counter({"Dani": 1, "Dani Pena": 1, "Dani Lamb": 1}))
        self.assertEqual(folded["Dani"], 1)

    def test_a_deactivated_template_names_nobody(self):
        bodies = [("Await Call", "#1", "Hey, this is Aisha with Alphalete!"),
                  ("No Answer", "#1", "Hey, this is Dani Pena.")]
        states = {"Await Call": "Not Activated", "No Answer": "Activated"}
        _f, personas = self.T.lint(bodies, states, None)
        self.assertEqual(dict(personas), {"Dani Pena": 1})


class EscalationCallPromiseTest(unittest.TestCase):
    """Megan 2026-10-01: escalation IS the handoff. Promising a call is
    fine; promising WHEN is what gets broken."""

    def setUp(self):
        from automations.sms_audit import escalations as E
        self.E = E

    def test_a_timed_promise_is_a_finding(self):
        for m in ("we can have a member from our team give you a call "
                  "shortly!",
                  "Someone will reach out to you within the hour.",
                  "We will call you back today."):
            self.assertTrue(self.E.ESC_CALL_PROMISE.search(m), m)

    def test_the_bare_handoff_is_not(self):
        for m in ("Of course — I'll have someone from our team give you a "
                  "call.",
                  "Thanks for letting us know. Please share the applicant's "
                  "best contact number, and a member of our team can follow "
                  "up directly."):
            self.assertIsNone(self.E.ESC_CALL_PROMISE.search(m), m)

    def test_a_question_applicants_ask_met_with_silence_is_a_finding(self):
        rows = [{"name": "Confusion About Role Type", "category": "",
                 "description": "", "message": "", "routing": "Silent"}]
        kinds = [k for k, _m in self.E.lint(rows)]
        self.assertIn("SILENT AND BLANK", kinds)


class TemplateLabelTest(unittest.TestCase):
    def setUp(self):
        from automations.sms_audit import templates as T
        self.T = T

    def test_a_section_is_not_repeated_inside_its_own_name(self):
        bodies = [("Await Call AI", "Await Call AI Template #1", "hi STOP")]
        _f, _p = self.T.lint(bodies, {"Await Call AI": "Activated"}, None)
        found = self.T.lint(
            [("Await Call AI", "Await Call AI Template #1", "hi")],
            {"Await Call AI": "Activated"}, None)[0]
        self.assertEqual(found[0][1], "Await Call AI Template #1")

    def test_two_bodies_under_one_name_are_told_apart(self):
        """First Interview Confirmation holds the message AND the
        'Here's the link again' follow-up, both under one name."""
        bodies = [("First Interview Confirmation", "Tmpl #1", "all set"),
                  ("First Interview Confirmation", "Tmpl #1",
                   "Here is the link again: https://x")]
        got = [m for _k, m in self.T.lint(
            bodies, {"First Interview Confirmation": "Activated"}, None)[0]]
        self.assertNotEqual(got[0], got[1])
        self.assertIn("Here is the link again", got[1])


class SmsTextTest(unittest.TestCase):
    def setUp(self):
        from automations.sms_audit import sms_text as X
        self.X = X

    def test_one_curly_quote_halves_the_room(self):
        plain = self.X.measure("a" * 150)
        self.assertEqual(plain["segments"], 1)
        curly = self.X.measure("a" * 149 + "’")
        self.assertEqual(curly["segments"], 3)
        self.assertTrue(curly["unicode"])

    def test_clean_swaps_it_back(self):
        fixed = self.X.clean("Here’s the link — now")
        self.assertEqual(fixed, "Here's the link - now")
        self.assertFalse(self.X.measure(fixed)["unicode"])

    def test_plain_ascii_counts_160_to_a_segment(self):
        self.assertEqual(self.X.measure("a" * 160)["segments"], 1)
        self.assertEqual(self.X.measure("a" * 161)["segments"], 2)


class MovingOfficeTest(unittest.TestCase):
    """Megan 2026-10-01: "we are moving to a new frisco locatoin tomorrow".
    Changing the address must not make six weeks of correct messages
    wrong, and must not let a stale one pass afterwards."""

    def setUp(self):
        import datetime as dt
        self.dt = dt
        RB.set_address_history(
            "11280",
            current="7250 Dallas Pkwy, Suite 400, Frisco, Texas 75034",
            previous="3100 Premier Drive, Suite 207, Irving, Texas 75063",
            changed=dt.date(2026, 10, 2))
        self.old = "Our office is at 3100 Premier Dr, Suite 207, Irving, TX."
        self.new = "Our office is at 7250 Dallas Pkwy, Suite 400, Frisco, TX."

    def tearDown(self):
        RB.ADDRESS_HISTORY.pop("11280", None)

    def test_the_old_address_was_right_before_the_move(self):
        self.assertIsNone(
            RB.wrong_address("11280", self.old, self.dt.date(2026, 9, 25)))

    def test_the_old_address_is_wrong_after_the_move(self):
        self.assertIsNotNone(
            RB.wrong_address("11280", self.old, self.dt.date(2026, 10, 3)))

    def test_the_new_address_is_right_after_the_move(self):
        self.assertIsNone(
            RB.wrong_address("11280", self.new, self.dt.date(2026, 10, 3)))

    def test_an_office_that_never_moved_is_unaffected(self):
        self.assertIsNone(RB.wrong_address(
            "11580", "We are at 1901 N Highway 360, Suite 610."))


class ProofreadTest(unittest.TestCase):
    """Megan 2026-10-01 caught "...over text but It's entry level..." by eye
    in a canned message. The grammar checks only ever ran on recruiter
    typing, so nothing was watching the templates or the AI's answers."""

    def test_a_capital_mid_sentence_is_caught(self):
        kinds = [k for k, _d in A.proofread(
            "The full listing will be on your Indeed profile, it's a lot to "
            "review over text but It's entry level with full paid training!")]
        self.assertIn("capital mid-sentence", kinds)

    def test_the_corrected_version_is_clean(self):
        self.assertEqual(A.proofread(
            "Happy to explain! You'd be meeting AT&T customers face to face. "
            "It's entry level with full paid training. The full listing is on "
            "your Indeed profile - too much to fit in a text!"), [])

    def test_a_proper_noun_after_a_lowercase_word_is_not_a_mistake(self):
        for ok in ("our client AT&T is the carrier",
                   "we are hiring for Alphalete Marketing",
                   "meet us in Irving on Tuesday"):
            self.assertEqual(
                [k for k, _d in A.proofread(ok) if k == "capital mid-sentence"],
                [], ok)

    def test_every_approved_escalation_message_is_clean(self):
        for m in ("No problem at all - I'll take you off our list. Thanks for "
                  "letting us know, and best of luck!",
                  "Happy to help! We're at 3100 Premier Dr, Suite 207, Irving "
                  "TX 75063. See you there!",
                  "Thanks for checking! Our records show an application for "
                  "the adPostingTitle role through jobBoard. Does that sound "
                  "right?"):
            self.assertEqual(A.proofread(m), [], m)


class PayWordingTest(unittest.TestCase):
    """Ruling 1 is narrower than it first reads: only the word "base" is out.
    Megan confirmed on 2026-10-01, shown the live message."""

    def _kinds(self, msg):
        from automations.sms_audit import escalations as E
        return [k for k, _m in E.lint([{"name": "Compensation", "category": "",
                                        "description": "", "routing": "Clarify",
                                        "message": msg}])]

    def test_the_live_message_passes(self):
        self.assertNotIn("PAY WORDING", self._kinds(
            "On average, our employees earn between $1,000 to $1,500 per "
            "week, depending on background/experience. Was there a specific "
            "pay rate you were seeking?"))

    def test_a_figure_under_the_floor_is_a_fault(self):
        self.assertIn("PAY WORDING", self._kinds(
            "On average, our employees earn between $800 to $1,500 per week."))

    def test_the_word_base_is_a_fault(self):
        self.assertIn("PAY WORDING", self._kinds(
            "We offer a weekly base salary plus commission."))


class AiSettingsTest(unittest.TestCase):
    """Megan 2026-10-01: "I checked multiple offices, all were not set
    correctly." 11280's state that morning is the fixture."""

    def setUp(self):
        from automations.sms_audit import ai_settings as S
        self.S = S
        self.office = {"office": "11280", "r1_mode": "Zoom",
                       "r2_mode": "In person",
                       "address": "3100 Premier Drive, Suite 207, Irving, "
                                  "Texas 75063"}
        self.bad_info = {
            "ai_assistant_name": "Aisha", "escalation_contact_name": "Aisha",
            "escalation_contact_title": "Hiring Manager",
            "interview_type": "Zoom Meeting",
            "office_address1": "3100 Premier Dr"}
        self.bad_prefs = {"offered_buffer": "15", "accepted_buffer": "10",
                          "ghosting_threshold": "45"}

    def _kinds(self, **kw):
        kw.setdefault("office", self.office)
        kw.setdefault("median_reply", 26.0)
        return [k for k, _m in self.S.lint(
            kw.pop("info", self.bad_info), kw.pop("prefs", self.bad_prefs),
            **kw)]

    def test_it_finds_every_fault_11280_had(self):
        got = self._kinds(template_names=["Dani Pena"])
        for expect in ("WINDOW TOO SHORT", "SAME NAME", "NAME MISMATCH",
                       "WRONG TITLE", "ONE INTERVIEW TYPE", "ADDRESS"):
            self.assertIn(expect, got, expect)

    def test_the_window_is_the_difference_not_either_number(self):
        self.assertEqual(self.S.window({"offered_buffer": "60",
                                        "accepted_buffer": "5"}), 55)
        self.assertEqual(self.S.window({"offered_buffer": "15",
                                        "accepted_buffer": "10"}), 5)

    def test_a_corrected_office_is_quiet(self):
        good = {"ai_assistant_name": "Aisha",
                "escalation_contact_name": "Lucy",
                "escalation_contact_title": "Talent Coordinator",
                "interview_type": "Zoom Meeting",
                "office_address1": "3100 Premier Dr, Suite 207"}
        prefs = {"offered_buffer": "60", "accepted_buffer": "5",
                 "ghosting_threshold": "60"}
        office = dict(self.office, r2_mode="Zoom")
        self.assertEqual(
            self.S.lint(good, prefs, office, 26.0, ["Aisha"]), [])

    def test_matching_the_template_signature_is_not_a_fault(self):
        """It is the state AppStream's own setup video asks for."""
        good = {"ai_assistant_name": "Aisha",
                "escalation_contact_name": "Lucy",
                "escalation_contact_title": "Talent Coordinator",
                "office_address1": "3100 Premier Dr, Suite 207"}
        kinds = [k for k, _m in self.S.lint(
            good, {"offered_buffer": "60", "accepted_buffer": "5"},
            dict(self.office, r2_mode="Zoom"), 26.0, ["Aisha"])]
        self.assertNotIn("AI IS A REAL PERSON", kinds)

    def test_a_real_sender_lending_their_name_IS_a_fault(self):
        good = {"ai_assistant_name": "Aisha",
                "escalation_contact_name": "Lucy",
                "escalation_contact_title": "Talent Coordinator",
                "office_address1": "3100 Premier Dr, Suite 207"}
        kinds = [k for k, _m in self.S.lint(
            good, {"offered_buffer": "60", "accepted_buffer": "5"},
            dict(self.office, r2_mode="Zoom"), 26.0, ["Aisha"],
            human_senders=["Aisha Ceron", "Jorge Pena"])]
        self.assertIn("AI IS A REAL PERSON", kinds)

    def test_a_new_office_with_no_history_is_not_guessed_at(self):
        good = {"ai_assistant_name": "Nova",
                "escalation_contact_name": "Lucy",
                "escalation_contact_title": "Talent Coordinator",
                "office_address1": "3100 Premier Dr, Suite 207"}
        office = dict(self.office, r2_mode="Zoom")
        self.assertEqual(self.S.lint(
            good, {"offered_buffer": "60", "accepted_buffer": "5"},
            office, None, None), [])
        kinds = [k for k, _m in self.S.lint(
            good, {"offered_buffer": "15", "accepted_buffer": "10"},
            office, None, None)]
        self.assertIn("WINDOW TOO SHORT", kinds)

    def test_not_pulled_is_said_not_passed(self):
        self.assertEqual(
            [k for k, _m in self.S.lint(None, None, self.office)],
            ["NOT PULLED"])


class PullAiSettingsLabelTest(unittest.TestCase):
    """The scrape reads fields by their visible label, so the label->key
    map is the one thing that silently empties the audit if the page
    rewords something. These are the labels as they appear today."""

    LABELS = {
        "Name your AI Assitant *": "ai_assistant_name",
        "Escalation Contact Title *": "escalation_contact_title",
        "Escalation Contact Person Name *": "escalation_contact_name",
        "How long are your interviews? *": "interview_length",
        "Office Name": "office_name",
        "AI Recruiting Company Name *": "ai_company_name",
        "Office Address *": "office_address1",
        "Office City *": "office_city",
        "Office State *": "office_state",
        "Office Zip *": "office_zip",
        "Office Phone *": "office_phone",
        "Timeslot Buffer - For Times Offered by AI (in minutes) *":
            "offered_buffer",
        "Timeslot Buffer - For Times Accepted by Candidates (in minutes) *":
            "accepted_buffer",
        "Ghosting Threshold (In minutes) *": "ghosting_threshold",
    }

    @staticmethod
    def norm(s):
        """Same normalisation the injected JS does."""
        import re as _re
        return _re.sub(r"\s+", " ",
                       _re.sub(r"[^A-Za-z0-9 ]", " ", s or "")).strip().lower()

    def test_every_real_label_maps_to_a_key(self):
        from automations.sms_audit import pull_ai_settings as P
        for label, key in self.LABELS.items():
            self.assertEqual(P.FIELDS.get(self.norm(label)), key, label)

    def test_their_typo_and_the_fixed_spelling_both_work(self):
        from automations.sms_audit import pull_ai_settings as P
        for spelling in ("Name your AI Assitant", "Name your AI Assistant"):
            self.assertEqual(P.FIELDS.get(self.norm(spelling)),
                             "ai_assistant_name", spelling)

    def test_buffers_and_threshold_land_in_preferences(self):
        """main() routes a key to preferences by its suffix, so the suffix
        is load-bearing."""
        from automations.sms_audit import pull_ai_settings as P
        prefs = {k for k in P.FIELDS.values()
                 if k.endswith(("_buffer", "_threshold"))}
        self.assertEqual(prefs, {"offered_buffer", "accepted_buffer",
                                 "ghosting_threshold"})


class AddressHistoryWiringTest(unittest.TestCase):
    """The date-aware address check existed but nothing populated it, so
    it was dead outside its own tests. Megan's office moved 2026-10-02."""

    def setUp(self):
        from automations.sms_audit import icd_audit as IA
        self.IA = IA
        self.row = {
            "office": "TESTMOVE",
            "address": "7250 Dallas Pkwy, Suite 400, Frisco, Texas 75034",
            "address_prev": "3100 Premier Drive, Suite 207, Irving, Texas 75063",
            "address_changed": "10-02-2026"}

    def tearDown(self):
        RB.ADDRESS_HISTORY.pop("TESTMOVE", None)

    def test_the_office_row_drives_the_history(self):
        import datetime as dt
        self.assertEqual(self.IA.apply_address_history(self.row),
                         dt.date(2026, 10, 2))
        old = "We are at 3100 Premier Dr, Suite 207, Irving TX."
        self.assertIsNone(
            RB.wrong_address("TESTMOVE", old, dt.date(2026, 9, 25)))
        self.assertIsNotNone(
            RB.wrong_address("TESTMOVE", old, dt.date(2026, 10, 3)))

    def test_an_office_that_never_moved_sets_one_address(self):
        row = dict(self.row, address_prev="", address_changed="")
        self.assertIsNone(self.IA.apply_address_history(row))
        self.assertIsNone(RB.wrong_address(
            "TESTMOVE", "We are at 7250 Dallas Pkwy, Suite 400."))

    def test_a_blank_address_changes_nothing(self):
        self.assertIsNone(self.IA.apply_address_history(
            {"office": "TESTMOVE", "address": ""}))

    def test_a_date_we_cannot_read_does_not_silently_backdate(self):
        """A garbled date must not leave the OLD address looking current."""
        row = dict(self.row, address_changed="soon")
        self.assertIsNone(self.IA.apply_address_history(row))
        self.assertIsNotNone(RB.wrong_address(
            "TESTMOVE", "We are at 3100 Premier Dr, Suite 207."))


class CoachingTakesTheMessageDateTest(unittest.TestCase):
    def test_every_coaching_test_accepts_a_date(self):
        for label, test in A.COACHING:
            try:
                test("11280", "hello there", None)
            except TypeError as e:  # noqa: PERF203
                self.fail("{} does not take a date: {}".format(label, e))


class OfficeHeaderMigrationTest(unittest.TestCase):
    """2026-10-05: save() writes a row positionally in COLUMNS order. When
    a column was ADDED, the live header still had the old one, so every
    value after it landed one cell left of its label — the old address
    under 'phone', the move date under 'zoom'. Nothing errored, the row
    read back wrong, and the move-aware address check silently did
    nothing on the day the office moved."""

    class FakeWS:
        def __init__(self, rows):
            self.rows = [list(r) for r in rows]

        def get_all_values(self):
            return [list(r) for r in self.rows]

        def update(self, values=None, range_name=None, raw=True):
            start = int(range_name[1:]) - 1
            for i, row in enumerate(values):
                while len(self.rows) <= start + i:
                    self.rows.append([])
                self.rows[start + i] = list(row)

    def test_adding_a_column_relabels_without_moving_data(self):
        from automations.sms_audit import offices as O
        old = ["office", "icd_name", "owner", "address", "phone", "zoom",
               "zoom_id", "job_ad_cities", "active"]
        ws = self.FakeWS([
            old,
            ["11280", "Rafael Hidalgo", "Rafael Hidalgo", "3100 Premier Dr",
             "", "https://zoom/x", "2935077152", "Irving", "yes"]])
        hdr = O._migrate(ws, list(old))
        self.assertEqual(hdr, O.COLUMNS)
        row = dict(zip(ws.rows[0], ws.rows[1]))
        # every value kept its MEANING, not its position
        self.assertEqual(row["address"], "3100 Premier Dr")
        self.assertEqual(row["zoom"], "https://zoom/x")
        self.assertEqual(row["zoom_id"], "2935077152")
        self.assertEqual(row["job_ad_cities"], "Irving")
        self.assertEqual(row["active"], "yes")
        # and the new columns exist, empty rather than borrowed
        self.assertEqual(row["address_prev"], "")
        self.assertEqual(row["address_changed"], "")

    def test_a_header_already_correct_is_left_alone(self):
        from automations.sms_audit import offices as O
        ws = self.FakeWS([list(O.COLUMNS),
                          ["11280"] + [""] * (len(O.COLUMNS) - 1)])
        before = [list(r) for r in ws.rows]
        self.assertEqual(O._migrate(ws, list(O.COLUMNS)), list(O.COLUMNS))
        self.assertEqual(ws.rows, before)


class LinksAreNotProse(unittest.TestCase):
    """A URL must not be proofread.

    The survey link every office sends ends ".../AlphaleteFirstRound?
    OfficeID=11280", which NO_SPACE reads as "nd?Of". On 2026-10-06 that
    put Miroslava Santos, Alphalete Floater and Alphalete Interviewers at
    the top of the recruiter typing table on nothing but their own link."""

    SURVEY = "https://www.surveymonkey.com/r/AlphaleteFirstRound?OfficeID=11280"

    def test_the_survey_link_is_clean(self):
        self.assertEqual(A.proofread(self.SURVEY), [])

    def test_a_zoom_link_is_clean(self):
        self.assertEqual(
            A.proofread("Zoom: https://us02web.zoom.us/j/2935077152"), [])

    def test_an_email_address_is_clean(self):
        self.assertEqual(
            A.proofread("Email me at first.Last@alphalete.com please"), [])

    def test_a_real_missing_space_still_fires(self):
        self.assertIn(
            ("missing space", "ow.Go"),
            A.proofread("Thank you for letting us know.Good luck!"))

    def test_a_real_fault_beside_a_link_still_fires(self):
        self.assertIn(
            ("missing space", "re.Ne"),
            A.proofread("See https://x.co/a?Bc here.Next week works"))

    def test_a_lowercase_i_in_a_link_is_not_a_fault(self):
        self.assertEqual(A.proofread("Join https://zoom.us/i/99 now"), [])

    def test_a_real_lowercase_i_still_fires(self):
        self.assertIn(("lowercase i", "i on its own"),
                      A.proofread("No i do not have you on the schedule"))


class BucketFalsePositives(unittest.TestCase):
    """Megan 2026-10-06 on Kevin Isik: "he didnt ask what to wear or
    bring?" He had not — the bucket fired on the bare word "resume"."""

    KEVIN = ("kevin.isik200@gmail.com and question, will my work dates be "
             "the ones i provided on my resume and will their be training?")

    def test_mentioning_a_resume_is_not_asking_what_to_bring(self):
        self.assertNotIn("What should I wear / bring?", A.buckets_of(self.KEVIN))

    def test_that_question_is_about_training(self):
        self.assertIn("Hours, training, is it paid?", A.buckets_of(self.KEVIN))

    def test_actually_asking_to_bring_a_resume_still_counts(self):
        for q in ("Should I bring a resume?", "do i need to bring my resume"):
            self.assertIn("What should I wear / bring?", A.buckets_of(q), q)

    def test_the_plain_dress_questions_still_count(self):
        for q in ("what should i wear", "is it business casual?"):
            self.assertIn("What should I wear / bring?", A.buckets_of(q), q)
