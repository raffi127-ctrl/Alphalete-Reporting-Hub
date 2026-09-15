"""Only a change of ROOMS may un-approve an office.

The relay compared the whole request as a STRING, so any difference cleared
the approval. That bit twice on 2026-09-15:

  * Cyrus's cadence was changed 15 -> 30 on our side. His machine put 15 back
    on its next sweep, the approval was cleared, and his board posted nothing
    for the rest of the day. It then read as "no destination approved yet" --
    which is also what a brand new office looks like.
  * An approval written by our own tooling spells the same rooms differently
    from the way a laptop sends them (channel_id vs channel), which would have
    un-approved Carlos the moment the relay was redeployed.

An approval is for the rooms a person checked. This is the JS _sameRooms()
ported, so the rule is checked here rather than only in a script nobody can
run tests against.
"""
from __future__ import annotations

import json
import unittest


def rooms(j):
    out = []
    try:
        v = json.loads(j or "[]")
    except ValueError:
        return out
    for d in (v or []):
        if isinstance(d, str):
            i = d
        else:
            i = str(d.get("channel") or d.get("channel_id") or d.get("channel_name") or "")
        i = i.strip().lower().lstrip("#")
        if i:
            out.append(i)
    return sorted(out)

def same(a, b):
    return rooms(a) == rooms(b)


class OnlyARoomChangeUnapproves(unittest.TestCase):

    OURS = json.dumps([
        {"channel_id": "C07J46MQNUX", "channel_name": "#alphalete-gp-sales",
         "cadence_min": 60},
        {"channel_id": "C0AJQA8P716", "channel_name": "#a-players-b2b",
         "cadence_min": 60}])
    HIS = json.dumps([
        {"channel": "C07J46MQNUX", "cadence_min": 60, "label": "Once an hour"},
        {"channel": "C0AJQA8P716", "cadence_min": 60, "label": "Once an hour"}])
    C15 = json.dumps([{"channel": "#ambient-sales-1", "cadence_min": 15,
                       "label": "Every 15 minutes"}])
    C30 = json.dumps([{"channel": "#ambient-sales-1", "cadence_min": 30,
                       "label": "Every 30 minutes"}])

    def test_our_spelling_and_theirs_are_the_same_rooms(self):
        self.assertTrue(same(self.OURS, self.HIS),
                        "an approval would be cleared because we write "
                        "channel_id where a laptop writes channel")

    def test_a_cadence_change_is_not_a_room_change(self):
        self.assertTrue(same(self.C15, self.C30),
                        "changing how often a board posts switches the "
                        "office off, which is what happened to Cyrus")

    def test_a_different_room_still_unapproves(self):
        self.assertFalse(same(self.C30, json.dumps(
            [{"channel": "#somewhere-else", "cadence_min": 30}])))

    def test_an_added_room_still_unapproves(self):
        self.assertFalse(same(self.C30, json.dumps(
            [{"channel": "#ambient-sales-1"}, {"channel": "#extra"}])))

    def test_the_js_and_this_stay_together(self):
        import pathlib as _p
        gs = (_p.Path(__file__).resolve().parents[2]
              / "resources" / "icd-alerts-relay.gs").read_text()
        self.assertIn("function _sameRooms(", gs)
        self.assertIn("if (!sameRoomsKn)", gs)


if __name__ == "__main__":
    unittest.main()
