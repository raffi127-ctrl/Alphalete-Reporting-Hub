"""python -m unittest automations.terminated_reps.test_auto_deactivate"""
import datetime as dt
import unittest
from unittest import mock

from automations.terminated_reps import auto_deactivate as ad
from automations.terminated_reps import slack_post
from automations.terminated_reps.deactivate import Pending

D = dt.date(2026, 10, 12)


def _o(**kw):
    o = ad.Outcome("Ana Lopez", 10, D)
    o.__dict__.update(kw)
    return o


class Cli:
    def __init__(self, chans=()):
        self.chans = [{"name": c} for c in chans]

    def users_conversations(self, **kw):
        return {"channels": self.chans}


def _users(**member):
    m = {"id": "U1", "profile": {"email": "ana@x.com", "real_name": "Ana Lopez"}}
    m.update(member)
    return {"ana@x.com": [m]}


class SlackLookup(unittest.TestCase):
    def test_clean_match_is_cleared(self):
        o = _o(email="ana@x.com")
        self.assertEqual(ad.slack_lookup(o, Cli(), _users())["id"], "U1")
        self.assertTrue(o.cleared)

    def test_other_office_channel_vetoes(self):
        o = _o(email="ana@x.com")
        cli = Cli(["kash-rai-office-recruiting-22177"])
        self.assertIsNone(ad.slack_lookup(o, cli, _users()))
        self.assertFalse(o.cleared)
        self.assertIn("moved office", o.slack)

    def test_raf_channel_is_fine(self):
        o = _o(email="ana@x.com")
        self.assertIsNotNone(ad.slack_lookup(o, Cli(["rafs-office-recruiting-11280"]), _users()))

    def test_admin_goes_to_eve(self):
        o = _o(email="ana@x.com")
        self.assertIsNone(ad.slack_lookup(o, Cli(), _users(is_admin=True)))
        self.assertIn("admin", o.slack)

    def test_already_deactivated(self):
        o = _o(email="ana@x.com")
        self.assertIsNone(ad.slack_lookup(o, Cli(), _users(deleted=True)))
        self.assertEqual(o.slack, "already")

    def test_no_account_clears(self):
        o = _o(email="new@x.com")
        self.assertIsNone(ad.slack_lookup(o, Cli(), _users()))
        self.assertTrue(o.cleared)
        self.assertTrue(o.needs_eve)

    def test_no_email_never_clears(self):
        o = _o(email="")
        self.assertIsNone(ad.slack_lookup(o, Cli(), _users()))
        self.assertFalse(o.cleared)


class Render(unittest.TestCase):
    def test_done_lines(self):
        txt = slack_post.render_done([_o(ov="done", slack="done"),
                                      _o(ov="done", slack="already")], D)
        self.assertIn("OwnerVille retired · Slack deactivated", txt)
        self.assertEqual(txt.count("Slack deactivated"), 1)

    def test_checklist_carries_reason_and_tag(self):
        p = Pending("Ana Lopez", D, 10, True, True)
        txt = slack_post.render_pending([p], dt.date(2026, 10, 18),
                                        {10: "Slack: no Slack account with a@x.com"})
        self.assertIn("no Slack account", txt)
        self.assertIn("<@U088E2KJEV8>", txt)

    def test_checklist_without_reasons_unchanged(self):
        p = Pending("Ana Lopez", D, 10, True, True)
        txt = slack_post.render_pending([p], dt.date(2026, 10, 18))
        self.assertIn("OwnerVille + Slack", txt)
        self.assertNotIn("<@", txt)


if __name__ == "__main__":
    unittest.main()
