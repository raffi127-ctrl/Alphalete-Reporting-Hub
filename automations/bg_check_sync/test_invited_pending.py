"""Offline tests for the invited-but-not-taken tracker. No portal, no inbox."""
import datetime as dt
import unittest

from automations.bg_check_sync import invited_pending as ip


def _inv(first, last, sent, status="Delivered", email=""):
    return ip.Invite(first=first, last=last, sent=sent, status=status, email=email)


TODAY = dt.date(2026, 9, 28)


class BucketTests(unittest.TestCase):
    def test_waiting_words(self):
        for s in ("Delivered", "Email Delivered", "Sent", "Opened", "In Progress"):
            self.assertEqual(ip.bucket_for(s), "WAITING", s)

    def test_stuck_words(self):
        for s in ("Bounced", "Expired", "Cancelled", "Undeliverable"):
            self.assertEqual(ip.bucket_for(s), "STUCK", s)

    def test_done_and_unknown(self):
        self.assertEqual(ip.bucket_for("Completed"), "DONE")
        self.assertEqual(ip.bucket_for("Flibbergibbet"), "UNKNOWN")
        self.assertEqual(ip.bucket_for(""), "UNKNOWN")


class CollapseTests(unittest.TestCase):
    def test_multiple_invites_collapse_to_one_person(self):
        invites = [
            _inv("Rizul", "Chauhan", "2026-09-25"),
            _inv("Rizul", "Chauhan", "2026-09-28"),
        ]
        people = ip.collapse(invites)
        self.assertEqual(len(people), 1)
        p = people[0]
        self.assertEqual(p.count, 2)
        # Outstanding age is measured from the FIRST invite, not the latest.
        self.assertEqual(p.first_sent, dt.date(2026, 9, 25))
        self.assertEqual(p.last_sent, dt.date(2026, 9, 28))
        self.assertEqual(p.days_outstanding(TODAY), 3)

    def test_oldest_outstanding_sorts_first(self):
        invites = [
            _inv("Dana", "Kolar", "2026-09-27"),
            _inv("Marcus", "Webb", "2026-09-20"),
        ]
        people = ip.collapse(invites)
        self.assertEqual([p.last for p in people], ["Webb", "Kolar"])

    def test_later_delivered_beats_earlier_bounce(self):
        # Re-sent after a bounce and it went through -> ball's back in their court.
        invites = [
            _inv("Sam", "Lee", "2026-09-20", status="Bounced"),
            _inv("Sam", "Lee", "2026-09-24", status="Delivered"),
        ]
        p = ip.collapse(invites)[0]
        self.assertEqual(p.bucket, "WAITING")

    def test_all_bounced_stays_stuck(self):
        invites = [
            _inv("Ana", "Diaz", "2026-09-20", status="Bounced"),
            _inv("Ana", "Diaz", "2026-09-24", status="Expired"),
        ]
        p = ip.collapse(invites)[0]
        self.assertEqual(p.bucket, "STUCK")


class PendingExclusionTests(unittest.TestCase):
    def test_fadv_event_drops_person(self):
        invites = [_inv("Rizul", "Chauhan", "2026-09-25")]
        # They show as invited in the portal but a result email already exists.
        keys = {"chauhan|rizul"}
        self.assertEqual(ip.pending(invites, event_keys=keys), [])

    def test_completed_table_drops_person(self):
        invites = [_inv("Rizul", "Chauhan", "2026-09-25")]
        self.assertEqual(ip.pending(invites, done_keys={"chauhan|rizul"}), [])

    def test_survivor_stays(self):
        invites = [
            _inv("Rizul", "Chauhan", "2026-09-25"),
            _inv("Dana", "Kolar", "2026-09-27"),
        ]
        out = ip.pending(invites, event_keys={"chauhan|rizul"})
        self.assertEqual([p.last for p in out], ["Kolar"])


class RenderTests(unittest.TestCase):
    def test_empty_says_nothing_outstanding(self):
        text = ip.render([], today=TODAY)
        self.assertIn("Nothing outstanding", text)

    def test_split_and_flag(self):
        invites = [
            _inv("Marcus", "Webb", "2026-09-20"),               # 8d -> ⏰
            _inv("Dana", "Kolar", "2026-09-27"),                # 1d -> no flag
            _inv("Priya", "Nadella", "2026-09-22", status="Bounced"),
        ]
        people = ip.pending(invites)
        text = ip.render(people, today=TODAY, stale_days=3)
        self.assertIn("Waiting on the applicant", text)
        self.assertIn("Invite stuck", text)
        self.assertIn("⏰ Marcus Webb", text)
        self.assertNotIn("⏰ Dana Kolar", text)
        self.assertIn("Nadella", text)


if __name__ == "__main__":
    unittest.main()
