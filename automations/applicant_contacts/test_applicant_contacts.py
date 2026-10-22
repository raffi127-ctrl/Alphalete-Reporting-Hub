"""python -m unittest automations.applicant_contacts.test_applicant_contacts"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.applicant_contacts import contacts as K
from automations.applicant_contacts import dm
from automations.applicant_contacts import extract as X

RAF = "U045Z8N0ZQC"


class TriggerTest(unittest.TestCase):
    def ev(self, **kw):
        base = {"type": "message", "channel_type": "im", "user": RAF,
                "text": "", "ts": "1.0", "channel": "D1"}
        base.update(kw)
        return base

    def test_phone_or_email_or_picture_triggers(self):
        self.assertTrue(dm.wants(self.ev(text="Juan Perez 214-555-0101")))
        self.assertTrue(dm.wants(self.ev(text="juan <mailto:j@x.com|j@x.com>")))
        self.assertTrue(dm.wants(self.ev(subtype="file_share", files=[
            {"mimetype": "image/png"}])))

    def test_dd_name_reply_and_knocks_do_not(self):
        self.assertFalse(dm.wants(self.ev(text="Adalberto Celaya")))
        self.assertFalse(dm.wants(self.ev(text="knocks Alex Touati yesterday")))
        self.assertFalse(dm.wants(self.ev(text="thanks")))

    def test_only_allowed_people_and_only_dms(self):
        self.assertFalse(dm.wants(self.ev(user="U0STRANGER", text="214-555-0101")))
        self.assertFalse(dm.wants(self.ev(channel_type="channel",
                                          text="214-555-0101")))
        self.assertFalse(dm.wants(self.ev(bot_id="B1", text="214-555-0101")))
        self.assertFalse(dm.wants(self.ev(subtype="message_changed",
                                          text="214-555-0101")))


class CleanTest(unittest.TestCase):
    def test_normalizes(self):
        out = X.clean([{"first_name": "JUAN", "last_name": "mcKenzie",
                        "phone": "+1 (214) 555-0101", "email": "Juan@X.com."}])
        self.assertEqual(out, [{"first_name": "Juan", "last_name": "mcKenzie",
                                "phone": "2145550101", "email": "juan@x.com"}])

    def test_unreadable_phone_and_email_dropped_not_guessed(self):
        out = X.clean([{"first_name": "Ana", "last_name": "", "phone": "214-55",
                        "email": "ana at gmail"}])
        self.assertEqual(out[0]["phone"], "")
        self.assertEqual(out[0]["email"], "")

    def test_empty_entries_dropped(self):
        self.assertEqual(X.clean([{"first_name": "", "last_name": "",
                                   "phone": "", "email": ""}]), [])


class PlanTest(unittest.TestCase):
    def a(self, **kw):
        base = {"first_name": "Juan", "last_name": "Perez", "phone": "", "email": ""}
        base.update(kw)
        return base

    def test_add_exists_skip(self):
        rows = K.plan([self.a(phone="2145550101"),
                       self.a(first_name="Ana", email="ana@x.com"),
                       self.a(first_name="", last_name="", phone="2145550199"),
                       self.a(first_name="Bo"),
                       self.a(first_name="Cy", phone="9725550000")],
                      phones={"2145550101": "Juan P (reception)"},
                      emails={})
        self.assertEqual([r["status"] for r in rows],
                         ["exists", "add", "skip", "skip", "add"])
        self.assertIn("Juan P (reception)", rows[0]["why"])
        self.assertEqual(rows[2]["why"], "no name")
        self.assertEqual(rows[3]["why"], "no phone or email")

    def test_same_person_twice_in_one_message_added_once(self):
        rows = K.plan([self.a(phone="2145550101"), self.a(phone="2145550101")],
                      {}, {})
        self.assertEqual([r["status"] for r in rows], ["add", "exists"])

    def test_body(self):
        b = K.person_body(self.a(phone="2145550101", email="j@x.com"), "Raf",
                          dt.date(2026, 10, 22))
        self.assertEqual(b["phoneNumbers"][0]["value"], "+12145550101")
        self.assertEqual(b["emailAddresses"][0]["value"], "j@x.com")
        self.assertNotIn("memberships", b)          # general list, no group
        self.assertIn("Raf, 10/22/2026", b["biographies"][0]["value"])

    def test_summary(self):
        rows = K.plan([self.a(phone="2145550101")], {}, {})
        self.assertIn("Added: *Juan Perez* · (214) 555-0101",
                      K.summary(rows, write=True))
        self.assertIn("Would add", K.summary(rows, write=False))
        self.assertIn("couldn't find", K.summary([], write=True))


if __name__ == "__main__":
    unittest.main()
