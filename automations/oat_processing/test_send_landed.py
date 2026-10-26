"""A send counts only when AppStream proves it (Megan 2026-10-25: "we want ALL
apps being pushed").

On 10/14, 10/18 and 10/19 Atef's queue sat at 45 / 86 / 75 all evening while
every run reported 40-55 "sent": the walk called a click "sent" when no error
showed 2.5s later, and those clicks were never saved. These pin the rule that
replaced it -- proof is the applicant leaving the slot or the queue total
dropping; anything else is retried once, then reported as "didn't stick" and
left in the queue. No browser, no AppStream: every page call is faked.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.oat_processing import run as OAT


class _Page:
    def wait_for_timeout(self, ms):
        pass


def _patch(names, totals, body=""):
    """read_current_name returns `names` in order (last one repeats), and
    _queue_total returns `totals` in order (last one repeats)."""
    names, totals = list(names), list(totals)

    def nxt(seq):
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return [mock.patch.object(OAT, "read_current_name",
                              side_effect=lambda p: nxt(names)),
            mock.patch.object(OAT, "_queue_total",
                              side_effect=lambda p: nxt(totals)),
            mock.patch.object(OAT, "_body", return_value=body)]


class SendLanded(unittest.TestCase):

    def _run(self, names, totals, body="", before=5):
        ps = _patch(names, totals, body)
        for p in ps:
            p.start()
        try:
            return OAT._send_landed(_Page(), "Jorge Banos", before,
                                    timeout_ms=300)
        finally:
            for p in ps:
                p.stop()

    def test_a_new_name_in_the_slot_is_sent(self):
        self.assertEqual(self._run(["Jorge Banos", "Angie Jimenez"], [5]),
                         "sent")

    def test_the_last_one_leaving_drops_the_total(self):
        self.assertEqual(self._run(["Jorge Banos", ""], [5, 4]), "sent")

    def test_still_there_is_unknown_never_sent(self):
        # Atef's 10/19: the same person, the same total, no error.
        self.assertEqual(self._run(["Jorge Banos"], [5]), "unknown")

    def test_a_blank_read_alone_is_not_proof(self):
        self.assertEqual(self._run([""], [5]), "unknown")

    def test_the_refusal_panel_is_refused(self):
        self.assertEqual(self._run(["Jorge Banos"], [5],
                                   body="cannot send to ai"), "refused")


class DoSendAi(unittest.TestCase):

    def _send(self, landed):
        a = mock.Mock(first_name="Jorge", last_name="Banos")
        clicks = []
        ps = [mock.patch.object(OAT, "read_current_applicant",
                                return_value=mock.Mock()),
              mock.patch.object(OAT, "_has_dup_signal", return_value=False),
              mock.patch.object(OAT, "_guard_office_now", return_value=True),
              mock.patch.object(OAT, "untick_send_boxes"),
              mock.patch.object(OAT, "_queue_total", return_value=5),
              mock.patch.object(OAT, "_click_first",
                                side_effect=lambda *a_, **k: clicks.append(1)
                                or True),
              mock.patch.object(OAT, "_send_landed", side_effect=landed)]
        for p in ps:
            p.start()
        try:
            return OAT.do_send_ai(_Page(), a, True), len(clicks)
        finally:
            for p in ps:
                p.stop()

    def test_proven_send_counts_once(self):
        self.assertEqual(self._send(["sent"]), ("sent", 1))

    def test_unproven_is_retried_once_then_counts_if_it_lands(self):
        self.assertEqual(self._send(["unknown", "sent"]), ("sent", 2))

    def test_unproven_twice_is_never_called_sent(self):
        out, clicks = self._send(["unknown", "unknown"])
        self.assertEqual((out, clicks), ("send_unconfirmed", 2))
        self.assertFalse(out.startswith("sent"))   # never counted as pushed

    def test_not_a_mutation_so_nobody_is_written_off(self):
        self.assertNotIn("send_unconfirmed",
                         ("sent", "sent_override", "removed"))


class WhyItDidNotLand(unittest.TestCase):

    def test_the_message_on_screen_is_logged(self):
        logged = []
        page = mock.Mock()
        fr = mock.Mock()
        fr.evaluate.return_value = ["Duplicate applicant found - already on "
                                    "the call list"]
        page.frames = [fr]
        with mock.patch.object(OAT, "_red_messages", return_value=[]), \
             mock.patch.object(OAT, "_shot"), \
             mock.patch.object(OAT, "_log", side_effect=logged.append):
            OAT._why_not_landed(page, "Keren Ospina")
        self.assertIn("Duplicate applicant found", logged[0])
        self.assertIn("Keren Ospina", logged[0])

    def test_nothing_on_screen_says_so(self):
        logged = []
        page = mock.Mock(frames=[])
        with mock.patch.object(OAT, "_red_messages", return_value=[]), \
             mock.patch.object(OAT, "_shot"), \
             mock.patch.object(OAT, "_log", side_effect=logged.append):
            OAT._why_not_landed(page, "Keren Ospina")
        self.assertIn("no message at all", logged[0])


class FormerReps(unittest.TestCase):
    """Megan 2026-10-26: a former rep who reapplies more than 9 months later
    is pushed through (Keren Ospina, Brought On Board (Retired) 11/13/2025)."""

    TODAY = __import__("datetime").date(2026, 10, 26)

    def rows(self, *pairs):
        return [{"status": s, "entered": d} for s, d in pairs]

    def test_keren_is_pushed(self):
        self.assertTrue(OAT.former_rep_ok(self.rows(
            ("Brought On Board (Retired)", "November 13, 2025"),
            ("Brought On Board (Retired)", "November 13, 2025")), self.TODAY))

    def test_under_nine_months_is_not(self):
        self.assertFalse(OAT.former_rep_ok(self.rows(
            ("Brought On Board (Retired)", "March 1, 2026")), self.TODAY))

    def test_exactly_the_cutoff_day_is_not_yet(self):
        self.assertFalse(OAT.former_rep_ok(self.rows(
            ("Brought On Board (Retired)", "January 26, 2026")), self.TODAY))
        self.assertTrue(OAT.former_rep_ok(self.rows(
            ("Brought On Board (Retired)", "January 25, 2026")), self.TODAY))

    def test_any_other_status_leaves_it_for_a_person(self):
        self.assertFalse(OAT.former_rep_ok(self.rows(
            ("Brought On Board (Retired)", "November 13, 2025"),
            ("Second Round Showed Up", "November 13, 2025")), self.TODAY))

    def test_an_unreadable_date_leaves_it_for_a_person(self):
        self.assertFalse(OAT.former_rep_ok(self.rows(
            ("Brought On Board (Retired)", "")), self.TODAY))

    def test_no_table_is_not_a_former_rep(self):
        self.assertFalse(OAT.former_rep_ok([], self.TODAY))

    def test_the_send_overwrites_a_former_rep(self):
        a = mock.Mock(first_name="Keren", last_name="Ospina")
        ps = [mock.patch.object(OAT, "read_current_applicant",
                                return_value=mock.Mock()),
              mock.patch.object(OAT, "_has_dup_signal", return_value=False),
              mock.patch.object(OAT, "_guard_office_now", return_value=True),
              mock.patch.object(OAT, "untick_send_boxes"),
              mock.patch.object(OAT, "_queue_total", return_value=5),
              mock.patch.object(OAT, "_click_first", return_value=True),
              mock.patch.object(OAT, "_send_landed", return_value="unknown"),
              mock.patch.object(OAT, "read_dup_rows", side_effect=[self.rows(
                  ("Brought On Board (Retired)", "November 13, 2025")), []]),
              mock.patch.object(OAT, "former_rep_ok", return_value=True),
              mock.patch.object(OAT, "_try_overwrite_send", return_value=True)]
        for p in ps:
            p.start()
        try:
            # Keren 10/26: the table is on screen at load, gone after the
            # click (second read returns []) -- the load read still counts.
            self.assertEqual(OAT.do_send_ai(_Page(), a, True), "sent_override")
        finally:
            for p in ps:
                p.stop()


if __name__ == "__main__":
    unittest.main()
