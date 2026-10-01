"""/aca must never swallow another feature's envelope.

Jiraiya is ONE listener for /dd, /knocks, the promotion buttons and now
/aca. A branch that acks something it does not own takes that feature down
silently, so `wants()` is asked before anything is acked and is pinned here
against every shape the other features send."""
import unittest

from automations.sms_audit import aca_bot as B


class Req:
    def __init__(self, type_, payload):
        self.type, self.payload = type_, payload


class WantsTest(unittest.TestCase):

    def test_it_claims_its_own_command(self):
        self.assertTrue(B.wants(Req("slash_commands", {"command": "/aca"})))
        self.assertTrue(B.wants(Req("slash_commands", {"command": "aca"})))
        self.assertTrue(B.wants(Req("slash_commands", {"command": "/ACA"})))

    def test_it_leaves_other_commands_alone(self):
        for cmd in ("/dd", "/knocks", "/promo", "/something"):
            self.assertFalse(B.wants(Req("slash_commands", {"command": cmd})),
                             cmd)

    def test_it_claims_only_its_own_modals(self):
        self.assertTrue(B.wants(Req("interactive", {
            "type": "view_submission", "view": {"callback_id": "aca_form"}})))
        self.assertTrue(B.wants(Req("interactive", {
            "type": "view_submission", "view": {"callback_id": "aca_confirm"}})))
        for other in ("dd_form", "knocks_form", "promo_remove_modal"):
            self.assertFalse(B.wants(Req("interactive", {
                "type": "view_submission", "view": {"callback_id": other}})),
                other)

    def test_it_claims_only_its_own_button(self):
        self.assertTrue(B.wants(Req("interactive", {
            "type": "block_actions",
            "actions": [{"action_id": "aca_change_btn"}]})))
        self.assertFalse(B.wants(Req("interactive", {
            "type": "block_actions",
            "actions": [{"action_id": "promo_remove"}]})))

    def test_an_empty_or_odd_payload_is_not_ours(self):
        self.assertFalse(B.wants(Req("interactive", {})))
        self.assertFalse(B.wants(Req("events_api", {"type": "message"})))


class ModalTest(unittest.TestCase):

    def test_the_form_asks_for_everything_a_check_needs(self):
        ids = {b.get("block_id") for b in B.form_modal()["blocks"]}
        for need in ("office", "address", "phone", "zoom", "email"):
            self.assertIn(need, ids, need)

    def test_a_returning_office_is_read_back_not_retyped(self):
        v = B.confirm_modal({"office": "11280", "label": "Raf",
                             "address": "3100 Premier Drive, Suite 207",
                             "email": "x@y.com", "updated": "2026-10-01"})
        self.assertEqual(v["callback_id"], B.CONFIRM)
        self.assertEqual(v["private_metadata"], "11280")
        text = str(v)
        self.assertIn("3100 Premier Drive, Suite 207", text)
        self.assertIn("still correct", text)

    def test_a_blank_field_says_the_check_is_off(self):
        v = B.confirm_modal({"office": "9", "address": "", "phone": ""})
        self.assertIn("not running", str(v))

    def test_change_it_reopens_the_form_prefilled(self):
        m = B.form_modal({"office": "11280", "address": "A Street"})
        vals = {b["block_id"]: b["element"].get("initial_value")
                for b in m["blocks"] if b.get("block_id")}
        self.assertEqual(vals["office"], "11280")
        self.assertEqual(vals["address"], "A Street")


if __name__ == "__main__":
    unittest.main()
