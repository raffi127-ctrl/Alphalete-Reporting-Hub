"""The org card is a FORM, the office card is the board pick-list.

Two cards share one cadence and one recognition sheet, so the thing worth
pinning is that they stay apart: #top-leaders-alphalete-org never shows Raf's
Sales Board reps, and #alphalete-lvl1-chat never grows a typing form
(Megan 2026-11-17). Plus the Block Kit limits that make a Slack button "do
nothing" when they're broken ([[reference_slack_form_limits]]).

    python -m unittest automations.promotion_checkin.test_org_card
"""
from __future__ import annotations

import unittest

from . import config as C
from . import icds as I
from . import message as M


def _action_ids(blocks):
    out = []
    for b in blocks:
        for el in b.get("elements", []) or []:
            if el.get("action_id"):
                out.append(el["action_id"])
        acc = b.get("accessory") or {}
        if acc.get("action_id"):
            out.append(acc["action_id"])
    return out


class OrgCardIsAForm(unittest.TestCase):
    def test_org_card_has_an_add_button_and_no_pick_list(self):
        ids = _action_ids(M.build_org_message("WE 11.22"))
        self.assertIn(C.ACTION_ADD, ids)
        self.assertNotIn(C.ACTION_PICK, ids)      # no board reps on this card
        self.assertNotIn(C.ACTION_SUBMIT, ids)

    def test_office_card_keeps_the_board_pick_list_and_no_form(self):
        reps = [type("R", (), {"name": "Jordan Reyes", "field": "5th wk+"})()]
        ids = _action_ids(M.build_message("WE 11.22", {"Velocity": reps}))
        self.assertIn(C.ACTION_PICK, ids)
        self.assertIn(C.ACTION_SUBMIT, ids)
        self.assertNotIn(C.ACTION_ADD, ids)       # the form is org-only

    def test_the_two_cards_post_to_different_channels(self):
        self.assertTrue(C.LVL1_CHANNEL_IDS)
        self.assertTrue(C.ORG_CHANNEL_IDS)
        self.assertFalse(set(C.LVL1_CHANNEL_IDS) & set(C.ORG_CHANNEL_IDS))


class TheForm(unittest.TestCase):
    def setUp(self):
        self.view = M.manual_modal("WE 11.22", channel="C1", ts="1.2")

    def test_asks_for_name_trainer_icd_and_level(self):
        got = {b.get("block_id") for b in self.view["blocks"]}
        for field in (C.FIELD_FIRST, C.FIELD_LAST, C.FIELD_TRAINER,
                      C.FIELD_ICD, C.FIELD_LEVEL):
            self.assertIn(field, got)

    def test_name_and_trainer_are_typed_icd_and_level_are_picked(self):
        kind = {b["block_id"]: b["element"]["type"]
                for b in self.view["blocks"] if b.get("block_id")}
        self.assertEqual(kind[C.FIELD_FIRST], "plain_text_input")
        self.assertEqual(kind[C.FIELD_LAST], "plain_text_input")
        self.assertEqual(kind[C.FIELD_TRAINER], "plain_text_input")
        self.assertEqual(kind[C.FIELD_ICD], "static_select")
        self.assertEqual(kind[C.FIELD_LEVEL], "static_select")

    def test_slack_block_kit_limits(self):
        # A modal over a limit is REFUSED by views.open and the button looks dead.
        self.assertLessEqual(len(self.view["title"]["text"]), 24)
        self.assertLessEqual(len(self.view["blocks"]), 100)
        self.assertLessEqual(len(self.view["private_metadata"]), 3000)
        for b in self.view["blocks"]:
            el = b.get("element") or {}
            opts = el.get("options") or []
            self.assertLessEqual(len(opts), 100, b.get("block_id"))
            for o in opts:
                self.assertLessEqual(len(o["text"]["text"]), 75)
                self.assertLessEqual(len(o["value"]), 75)
            ph = (el.get("placeholder") or {}).get("text", "")
            self.assertLessEqual(len(ph), 150)


class TheIcdList(unittest.TestCase):
    def test_pulls_our_orgs_icds_and_skips_shut_down_offices(self):
        labels = [lbl for (lbl, _v) in I.icd_choices(force=True)]
        self.assertGreater(len(labels), 40)
        self.assertIn("Marcellus Butler", labels)
        self.assertIn("Tre Mitchell", labels)          # the name people use
        self.assertNotIn("Brian Tran", labels)         # office shut down (skip)
        self.assertNotIn("Country Stats", labels)      # not a person at all
        self.assertEqual(labels, sorted(labels, key=str.lower))

    def test_rafs_icd_writes_the_owner_name_the_sheet_already_uses(self):
        picked = dict(I.icd_choices(force=True))
        self.assertEqual(picked["Raf Hidalgo"], C.OWNER)

    def test_the_org_cards_removes_cannot_reach_rafs_rows(self):
        from . import handler as H
        scope = {s.lower() for s in H._org_owner_scope()}
        self.assertNotIn(C.OWNER.lower(), scope)
        self.assertIn("marcellus butler", scope)


if __name__ == "__main__":
    unittest.main()
