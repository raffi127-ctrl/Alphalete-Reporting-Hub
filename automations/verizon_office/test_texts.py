import datetime as dt
import unittest

from automations.verizon_office import texts as T


def _reply(text, name="x.png", ts="1"):
    return {"ts": ts, "text": text, "files": [{"name": name, "url_private": "https://files/" + name}]}


class MatchTests(unittest.TestCase):
    def test_matches_each_item_on_its_caption(self):
        day = dt.date(2026, 11, 16)
        replies = [_reply(":moneybag: Revenue Board — Nov 16", "rb.png"),
                   _reply(":chart_with_downwards_trend: Churn Rates by Rep — Nov 16", "cr.png"),
                   _reply(":wolf: *VERIZON CHURN* — 11/16", "ct.png"),
                   _reply(":clipboard: *Verizon Wireless Comp Grid*", "cg.png"),
                   _reply(":new: Rep Activations — Nov 16 (1 of 2)", "ra.png")]
        got = T.match_thread_items(replies, day)
        self.assertEqual({k: v["name"] for k, v in got.items()},
                         {"revenue_board": "rb.png", "churn_by_rep": "cr.png", "churn_tab": "ct.png", "comp_grid": "cg.png"})

    def test_newest_matching_reply_wins(self):
        day = dt.date(2026, 11, 16)
        replies = [_reply("Revenue Board — Nov 16", "old.png", "1"), _reply("Revenue Board — Nov 16", "new.png", "2")]
        self.assertEqual(T.match_thread_items(replies, day)["revenue_board"]["name"], "new.png")

    def test_comp_grid_only_on_its_day(self):
        self.assertIn("comp_grid", [k for k, _, _ in T.wanted(dt.date(2026, 11, 16))])
        self.assertNotIn("comp_grid", [k for k, _, _ in T.wanted(dt.date(2026, 11, 17))])
        got = T.match_thread_items([_reply("Verizon Wireless Comp Grid")], dt.date(2026, 11, 17))
        self.assertNotIn("comp_grid", got)

    def test_missing_item_is_none(self):
        got = T.match_thread_items([_reply("Revenue Board — Nov 16")], dt.date(2026, 11, 17))
        self.assertIsNone(got["churn_by_rep"])

    def test_groups_come_off_office_channels(self):
        from unittest import mock
        dests = [{"group": "Verizon", "chat_guid": "g1", "require_handles": ["+1555"], "cadence_min": 60},
                 {"group": "VZ Leaders", "channel_id": "imessage:VZ Leaders"}]
        with mock.patch("automations.icd_alerts.post.approved_texts", return_value={"nicolas": dests}):
            g = T.groups(log=lambda *_: None)
        self.assertEqual(g, [{"group": "Verizon", "chat_guid": "g1", "require_handles": ["+1555"]}, "VZ Leaders"])

    def test_groups_fall_back_when_the_sheet_is_unreadable(self):
        from unittest import mock
        with mock.patch("automations.icd_alerts.post.approved_texts", side_effect=RuntimeError("403")):
            g = T.groups(log=lambda *_: None)
        self.assertEqual(len(g), 2)
        self.assertEqual(g[0]["group"], "Verizon")
        self.assertTrue(g[0].get("require_handles"))
        self.assertEqual(g[1], "Verizon Leaders")


if __name__ == "__main__":
    unittest.main()
