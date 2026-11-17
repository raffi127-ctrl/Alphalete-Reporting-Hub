"""Phone normalization, name handling, and cancel/disconnect dedup. Offline."""
from __future__ import annotations

import unittest

from automations.cancel_feedback import config as C
from automations.cancel_feedback import source as S


def _cx(name, phone, owner="Aya Al-Khafaji", rep="Rep A"):
    return {"Customer Name": name, "Customer Phone": phone, "_owner": owner,
            "Rep": rep, "Status Date": "11/16/2026"}


def _dx(name, phone, owner="Aya Al-Khafaji", rep="Rep A", reason="Non-payment"):
    d = _cx(name, phone, owner, rep)
    d["Eligibility Reason"] = reason
    return d


class TestPhone(unittest.TestCase):
    def test_ten_digits(self):
        self.assertEqual(S.normalize_phone("214-845-6450"), "+12148456450")

    def test_leading_one(self):
        self.assertEqual(S.normalize_phone("1 (214) 845-6450"), "+12148456450")

    def test_blank_and_bad(self):
        for bad in ("", "   ", "555-1234", "abc", "0123456789", "211-555-0000"):
            self.assertIsNone(S.normalize_phone(bad), bad)


class TestName(unittest.TestCase):
    def test_first_token_titlecased(self):
        self.assertEqual(S.first_name("JOHN DOE"), "John")
        self.assertEqual(S.first_name("maria-elena cruz"), "Maria-elena")

    def test_empty(self):
        self.assertEqual(S.first_name(""), "there")

    def test_render_uses_first(self):
        msg = C.render(S.first_name("John Doe"))
        self.assertIn("Hi John,", msg)
        self.assertNotIn("Reply STOP", msg)   # no opt-out line, by request


class TestUnify(unittest.TestCase):
    def test_dedup_by_phone_merges_kind(self):
        out = S.unify([_cx("John Doe", "214-555-0001")],
                      [_dx("John Doe", "(214) 555-0001", reason="Price")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["kind"], "cancel+disconnect")
        self.assertEqual(out[0]["reason"], "Price")   # disconnect reason kept

    def test_separate_numbers_separate_rows(self):
        out = S.unify([_cx("A", "214-555-0001")], [_dx("B", "214-555-0002")])
        self.assertEqual(len(out), 2)

    def test_unusable_phone_dropped(self):
        out = S.unify([_cx("No Phone", "")],
                      [_dx("Bad", "12")])
        self.assertEqual(out, [])

    def test_cancel_only_has_no_reason(self):
        out = S.unify([_cx("Solo", "214-555-0009")], [])
        self.assertEqual(out[0]["kind"], "cancel")
        self.assertEqual(out[0]["reason"], "")
        self.assertEqual(out[0]["first"], "Solo")


class TestScope(unittest.TestCase):
    def test_test_scope_is_rafael_only(self):
        self.assertEqual(C.owners_for_scope("test"), {"Rafael Hidalgo"})

    def test_full_scope_is_captainship_without_starr(self):
        try:
            full = C.owners_for_scope("full")
        except ModuleNotFoundError as e:   # Tableau browser dep (Lucy-only)
            self.skipTest("source roster dep not installed locally: %s" % e)
        self.assertIn("Rafael Hidalgo", full)
        self.assertIn("Aya Al-Khafaji", full)
        self.assertGreater(len(full), 20)
        self.assertNotIn("Jason Strid", full)     # Starr is a different captainship
        self.assertNotIn("Sahil Multani", full)


class TestSelect(unittest.TestCase):
    def _c(self, phone, name="Cust"):
        return {"phone": phone, "customer_name": name, "first": name, "rep": "",
                "owner": "Rafael Hidalgo", "kind": "cancel", "reason": ""}

    def test_skips_already_texted_and_opted_out(self):
        from automations.cancel_feedback import run as R
        customers = [self._c("+12148450001", "A"), self._c("+12148450002", "B"),
                     self._c("+12148450003", "C")]
        to_text, skipped = R.select_recipients(
            customers, texted={"+12148450002"}, opted={"+12148450003"})
        self.assertEqual([c["customer_name"] for c in to_text], ["A"])
        self.assertEqual({why for _, why in skipped}, {"already-texted", "opted-out"})


class TestQuietHours(unittest.TestCase):
    def test_window(self):
        import datetime as dt
        from automations.cancel_feedback import run as R
        base = dt.datetime(2026, 11, 17)
        self.assertFalse(R._within_quiet_hours(base.replace(hour=7)))
        self.assertTrue(R._within_quiet_hours(base.replace(hour=8)))
        self.assertTrue(R._within_quiet_hours(base.replace(hour=20)))
        self.assertFalse(R._within_quiet_hours(base.replace(hour=21)))


class TestOptOut(unittest.TestCase):
    def test_keywords(self):
        from automations.cancel_feedback import ringcentral as rc
        for yes in ("STOP", "stop.", "Stop", "unsubscribe", "Cancel", "quit"):
            self.assertTrue(rc.is_opt_out(yes), yes)
        for no in ("The install never showed", "price was too high", ""):
            self.assertFalse(rc.is_opt_out(no), no)


if __name__ == "__main__":
    unittest.main()
