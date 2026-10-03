"""python -m unittest automations.owner_rep_audit.test_owner_rep_audit"""
import datetime as dt
import unittest

from automations.owner_rep_audit import config as C
from automations.owner_rep_audit import messages as M
from automations.owner_rep_audit import replies as R
from automations.owner_rep_audit import run
from automations.owner_rep_audit.roster import granted
from automations.owner_rep_audit.slack_ops import find_owner, find_rep


class Parse(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(R.parse("3, 7 and 12", 10, False),
                         (R.SELECT, [3, 7], [12]))
        self.assertEqual(R.parse("#2", 5, False), (R.SELECT, [2], []))

    def test_remove_needs_a_selection(self):
        self.assertEqual(R.parse("REMOVE", 5, False)[0], R.UNCLEAR)
        self.assertEqual(R.parse("remove!", 5, True)[0], R.CONFIRM)

    def test_remove_with_numbers_is_a_new_selection(self):
        self.assertEqual(R.parse("remove 2", 5, True), (R.SELECT, [2], []))

    def test_none_and_chatter(self):
        self.assertEqual(R.parse("None", 5, False)[0], R.NONE)
        self.assertEqual(R.parse("all still active", 5, False)[0], R.NONE)
        for t in ("ok", "all good thanks", "let me check", "yes remove them"):
            self.assertEqual(R.parse(t, 5, True)[0], R.UNCLEAR, t)

    def test_only_out_of_range(self):
        self.assertEqual(R.parse("40", 5, False), (R.UNCLEAR, [], [40]))


class Flow(unittest.TestCase):
    def office(self):
        return {"owner": "Kash Rai", "office": "22177", "status": "sent",
                "selected": [], "reps": [{"name": "Ann Lee"},
                                         {"name": "Bo Diaz"}]}

    def test_select_then_remove(self):
        o, day = self.office(), dt.date(2026, 11, 2)
        st, text, picked = run.apply_reply(o, "2", day)
        self.assertEqual((st, picked), ("selected", []))
        self.assertIn("Bo Diaz", text)
        o["status"] = st
        st, text, picked = run.apply_reply(o, "REMOVE", day)
        self.assertEqual((st, picked, o["confirmed_on"]),
                         ("done", ["Bo Diaz"], "11/2"))

    def test_chatter_after_selection_keeps_selection(self):
        o = self.office()
        run.apply_reply(o, "1", dt.date(2026, 11, 2))
        o["status"] = "selected"
        st, text, picked = run.apply_reply(o, "ok", dt.date(2026, 11, 2))
        self.assertEqual((st, picked), ("selected", []))
        self.assertIn(C.CONFIRM_WORD, text)

    def test_calendar(self):
        self.assertEqual(run.due(None, dt.date(2026, 11, 1)), ["start", "summary"])
        self.assertEqual(run.due({}, dt.date(2026, 11, 2)), ["poll", "summary"])
        self.assertEqual(run.due({}, dt.date(2026, 11, 4)),
                         ["poll", "remind", "summary"])
        self.assertEqual(run.due({"reminded": True}, dt.date(2026, 11, 9)),
                         ["poll", "summary", "close"])
        self.assertEqual(run.due({"reminded": True, "closed": True},
                                 dt.date(2026, 11, 20)), ["poll", "summary"])


class Posts(unittest.TestCase):
    def test_evelyn_is_tagged_with_the_lists(self):
        text = M.pending_for_evelyn([
            {"owner": "Kash Rai", "office": "22177", "slack_id": "U1",
             "status": "sent", "reps": ["Ann Lee", "Bo Diaz"]},
            {"owner": "Jo Doe", "office": "1", "status": "no_slack",
             "reps": ["Cy"]}])
        self.assertIn(f"<@{C.EVELYN}>", text.splitlines()[0])
        self.assertIn("> 2. Bo Diaz", text)
        self.assertIn("no Slack account found", text)

    def test_summary(self):
        text = M.summary([
            {"owner": "A", "office": "1", "status": "done",
             "removed": ["X", "Y"], "confirmed_on": "11/3",
             "ov_pending": ["X", "Y"]},
            {"owner": "B", "office": "2", "status": "done", "removed": []},
            {"owner": "C", "office": "3", "status": "sent", "removed": []}])
        self.assertTrue(text.startswith(
            f"{C.SUMMARY_HEAD}: 2 people removed from AO across 1 offices"))
        self.assertIn("> X", text)
        self.assertIn("✅ Nobody left: B (2)", text)
        self.assertIn("⚠️ No reply yet: C (3)", text)
        self.assertIn("OwnerVille by hand: X, Y", text)

    def test_monthly_title(self):
        self.assertEqual(M.thread_title(run.month_label(dt.date(2026, 10, 1))),
                         "AO Workspace: Terminations in other Offices - October 2026")


class Matching(unittest.TestCase):
    users = [{"id": "U1", "name": "Kash Rai", "email": "k@x.com"},
             {"id": "U2", "name": "Ann Lee", "email": "ann@x.com"},
             {"id": "U3", "name": "Ann Lee", "email": "other@x.com"},
             {"id": "U4", "name": "Old Rep", "email": "", "deleted": True}]

    def test_owner_unique_name_only(self):
        self.assertEqual(find_owner("Kash Rai", self.users), "U1")
        self.assertIsNone(find_owner("Ann Lee", self.users))   # two of them

    def test_rep_by_email_then_name(self):
        self.assertEqual(find_rep({"name": "Ann Lee", "email": "ANN@x.com"},
                                  self.users)["id"], "U2")
        self.assertIsNone(find_rep({"name": "Ann Lee", "email": ""}, self.users))
        self.assertIsNone(find_rep({"name": "Old Rep", "email": ""}, self.users))

    def test_granted(self):
        self.assertTrue(granted("View"))
        self.assertFalse(granted("Send Request"))
        self.assertFalse(granted("Request Sent"))
        self.assertFalse(granted(""))


if __name__ == "__main__":
    unittest.main()
