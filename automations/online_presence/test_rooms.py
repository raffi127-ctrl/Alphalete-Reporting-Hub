"""Creating the office's Slack room when the sign-up says "create one for me".

    python -m unittest automations.online_presence.test_rooms

Slack and the sheet are fakes: nothing real is created.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.online_presence import rooms, signup


class FakeTab:
    def __init__(self, rows):
        self.rows = [list(r) for r in rows]
        self.writes = []

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def update_cell(self, r, c, v):
        self.writes.append((r, c, v))
        self.rows[r - 1][c - 1] = v


class FakeSlack:
    def __init__(self, taken=None):
        self.created, self.invited, self.taken = [], [], taken

    def conversations_create(self, name, is_private):
        if self.taken:
            raise Exception("The request to the Slack API failed. 'error': 'name_taken'")
        self.created.append((name, is_private))
        return {"channel": {"id": "C0NEWROOM1"}}

    def conversations_list(self, **kw):
        return {"channels": [{"name": self.taken, "id": "C0OLDROOM1"}] if self.taken else []}

    def conversations_invite(self, channel, users):
        self.invited.append((channel, users.split(",")))

    def auth_test(self):
        return {"user_id": "U0BCG8F9B5Z"}           # running as Lucy


def _sheet(room="create us one", channel="", business="Kash Marketing", owner="Kash Rai"):
    head = signup.HEADER
    row = [""] * len(head)
    for k, v in {"Business Name": business, "Owner": owner, "Slack Room": room,
                 "Slack Channel": channel, "Status": "PENDING"}.items():
        row[head.index(k)] = v
    return FakeTab([head, row])


class Name(unittest.TestCase):
    def test_company_name_lucyeco_social(self):
        self.assertEqual(rooms.channel_name("Palace Acquisitions"),
                         "palace-acquisitions-lucyeco-social")
        self.assertEqual(rooms.channel_name("M Coast, LLC."), "m-coast-llc-lucyeco-social")
        self.assertEqual(rooms.channel_name("Kash Marketing"), "kash-marketing-lucyeco-social")
        self.assertLessEqual(len(rooms.channel_name("x" * 200)), 80)


class Creates(unittest.TestCase):
    def _run(self, tab, cl, live=True, button=None):
        self.button = mock.Mock(return_value=button or {"action": "pinned"})
        with mock.patch("automations.shared.slack_metrics_post._load_bot_token",
                        side_effect=Exception("no Lucy app token here")), \
                mock.patch("automations.online_presence.post_form.add_button", self.button):
            return rooms.run(live=live, cl=cl, tab=tab)

    def test_private_room_right_people_and_written_back(self):
        tab, cl = _sheet(), FakeSlack()
        res = self._run(tab, cl)
        self.assertEqual(cl.created, [("kash-marketing-lucyeco-social", True)])
        users = cl.invited[0][1]
        from automations.online_presence.post_form import JIRAIYA
        for who in (rooms.MEGAN, rooms.EVE, rooms.HUBPOSTER, JIRAIYA, "U046XBPN0G2"):   # Kash = the ICD
            self.assertIn(who, users)
        self.assertEqual(self.button.call_args.args, ("C0NEWROOM1",))      # 📸 button pinned
        self.assertEqual(res[0]["button"], "pinned")
        self.assertNotIn("U0BCG8F9B5Z", users)       # Lucy made it, so she's already in
        head = signup.HEADER
        self.assertEqual(tab.rows[1][head.index("Slack Channel")], "C0NEWROOM1")
        self.assertEqual(tab.rows[1][head.index("Slack Room")], "created")
        self.assertEqual(res[0]["missed"], [])

    def test_button_trouble_is_reported_but_the_channel_stays(self):
        tab, cl = _sheet(), FakeSlack()
        res = self._run(tab, cl, button={"action": "no_jiraiya_token",
                                         "error": "Jiraiya's token isn't on this machine"})
        self.assertEqual(cl.created, [("kash-marketing-lucyeco-social", True)])
        self.assertEqual(tab.rows[1][signup.HEADER.index("Slack Channel")], "C0NEWROOM1")
        self.assertTrue(any("New post button not added" in m for m in res[0]["missed"]))

    def test_dry_makes_nothing(self):
        tab, cl = _sheet(), FakeSlack()
        res = self._run(tab, cl, live=False)
        self.assertEqual(res[0]["action"], "would_create")
        self.assertEqual((cl.created, cl.invited, tab.writes), ([], [], []))

    def test_already_has_a_room_or_already_made(self):
        for tab in (_sheet(room="existing", channel="C0THEIRS01"),
                    _sheet(room="created", channel="C0NEWROOM1")):
            cl = FakeSlack()
            self.assertEqual(self._run(tab, cl), [])
            self.assertEqual(cl.created, [])

    def test_name_taken_reuses_never_makes_a_second(self):
        tab, cl = _sheet(), FakeSlack(taken="kash-marketing-lucyeco-social")
        res = self._run(tab, cl)
        self.assertEqual(res[0]["id"], "C0OLDROOM1")
        self.assertEqual(cl.created, [])

    def test_icd_we_cant_place_is_named_not_guessed(self):
        tab, cl = _sheet(owner="Somebody Nobody Knows Zzq"), FakeSlack()
        with mock.patch("automations.online_presence.setup.resolve_person",
                        side_effect=lambda n, c=None: (_ for _ in ()).throw(ValueError(n))):
            res = self._run(tab, cl)
        self.assertIn("Somebody Nobody Knows Zzq", res[0]["missed"])


class Ping(unittest.TestCase):
    class Cl(FakeSlack):
        def __init__(self):
            super().__init__(); self.posts = []

        def chat_postMessage(self, **kw):
            self.posts.append(kw)
            return {"ts": "1.%d" % len(self.posts)}

    def test_announced_once_in_the_alerts_channel_short_header_detail_in_thread(self):
        tab, cl = _sheet(), self.Cl()
        res = rooms.ping_new(live=True, cl=cl, tab=tab)
        self.assertEqual(len(res), 1)
        self.assertEqual([p["channel"] for p in cl.posts], [rooms.SOCIAL_ALERTS] * 2)
        self.assertIn("Kash Marketing", cl.posts[0]["text"])
        self.assertNotIn("thread_ts", cl.posts[0])              # header
        self.assertEqual(cl.posts[1]["thread_ts"], "1.1")        # detail in the thread
        self.assertIn("--from-signup", cl.posts[1]["text"])
        self.assertTrue(tab.rows[1][signup.HEADER.index("Pinged At")])
        self.assertEqual(rooms.ping_new(live=True, cl=cl, tab=tab), [])   # never twice
        self.assertEqual(len(cl.posts), 2)

    def test_dry_announces_nothing(self):
        tab, cl = _sheet(), self.Cl()
        self.assertEqual(rooms.ping_new(live=False, cl=cl, tab=tab)[0]["action"], "would_ping")
        self.assertEqual(cl.posts, [])


class LivePassSkipsDryOffices(unittest.TestCase):
    def test_dry_office_is_not_run_on_a_live_pass(self):
        from automations.online_presence import run, offices
        dry = offices.Presence(key="kash", business_name="K", slack_channel="C1")
        with mock.patch.object(offices, "load", return_value={"kash": dry}), \
                mock.patch.object(run, "run_office", side_effect=AssertionError("ran")), \
                mock.patch("automations.online_presence.rooms.ping_new", return_value=[]), \
                mock.patch("automations.online_presence.rooms.run", return_value=[]), \
                mock.patch("automations.online_presence.relay.answered", return_value=[]), \
                mock.patch("automations.online_presence.timing.record"), \
                mock.patch("automations.online_presence.review_alerts.check", return_value=[]), \
                mock.patch("automations.online_presence.key_watch.check", return_value=[]), \
                mock.patch("automations.online_presence.email_alerts.check", return_value=[]):
            self.assertEqual(run.main(["--live"]), 0)


if __name__ == "__main__":
    unittest.main()
