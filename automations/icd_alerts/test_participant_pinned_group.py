"""A group pinned to its PARTICIPANTS, because its name cannot be used.

Cyrus's managing-partners chat is renamed by its own members several times an
hour -- Raf watched it cycle "Ambient Managing Partners 🔥" / "1️⃣🎉" /
"Ambient Partners" within minutes, and by the time it was looked up on the
mini it was "1️⃣🐦‍🔥", a fifth name nobody had mentioned.

Keying that destination on the name breaks THREE ways, and only the first is
loud:
  * the lookup raises and nothing sends;
  * the address string is also the per-room CADENCE MARKER, so a rename mints
    a fresh one, reads as "never posted" and fires a board instantly -- a
    rename storm becomes a text storm;
  * it is also the gap list's ⏰ key, so the clock marks quietly stop.

A stored chat id is not the answer either (see AChatIdIsNeverTrustedOnItsOwn
in test_text_dests): a membership change mints a new one and a stale one sends
into a thread nobody can see. So the participants are the key, and these pin
that the three breakages above cannot come back.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.b2b_dispositions import text_post as tp
from automations.icd_alerts import post as P

GUID = "any;+;4a0f39ca3b224acc906a049b63bc4c45"
# The three unsaved numbers Raf listed. The named members are deliberately
# NOT required: they are the people most likely to be re-saved, merged or to
# appear under a second handle.
PINS = ["+13195609495", "+19039311920", "+19453843860"]
# What the chat actually holds on the mini (8 non-Lucy handles).
LIVE = ["+13195609495", "+14197697114", "+14699203385", "+15744012682",
        "+18083547900", "+19039311920", "+19453843860", "+19459850781"]


def _chat(cid, name, handles):
    return {"id": cid, "name": name, "handles": list(handles)}


def _dest(**kw):
    d = {"group": "Ambient Managing Partners", "chat_guid": GUID,
         "require_handles": list(PINS), "cadence_min": 15}
    d.update(kw)
    return d


class TheNameIsNeverConsulted(unittest.TestCase):

    def _resolve(self, chats):
        with mock.patch.object(tp, "list_chats", return_value=chats):
            return tp.resolve_dest(_dest())

    def test_it_is_found_under_any_of_the_five_names(self):
        for name in ("Ambient Managing Partners 🔥", "1️⃣🎉",
                     "Ambient Partners", "1️⃣🐦‍🔥", ""):
            got = self._resolve([_chat(GUID, name, LIVE)])
            self.assertEqual(got["id"], GUID,
                             "a rename to %r lost the group" % name)

    def test_the_address_does_not_change_when_the_name_does(self):
        first = P.text_dest_address("1️⃣🎉", PINS)
        second = P.text_dest_address("Ambient Partners", PINS)
        self.assertEqual(first, second,
                         "the cadence marker moved with the display name, so "
                         "a rename would re-post a board immediately")
        self.assertTrue(first.startswith("imessage:handles:"))

    def test_the_address_is_stable_however_the_numbers_are_written(self):
        self.assertEqual(
            P.text_dest_address("g", ["+1 (319) 560-9495", "9039311920",
                                      "+19453843860"]),
            P.text_dest_address("g", PINS),
            "two spellings of the same roster gave two addresses")

    def test_a_name_keyed_group_keeps_exactly_the_address_it_has_today(self):
        # Seven live groups depend on this marker not moving.
        self.assertEqual(P.text_dest_address("Alphalete Partners", []),
                         "imessage:Alphalete Partners")
        self.assertEqual(P.text_dest_address("Reporting", None),
                         "imessage:Reporting")


class MembershipChurnDoesNotBreakIt(unittest.TestCase):

    def test_a_ninth_member_joining_is_fine(self):
        """Raf adds people to these groups. A destination that breaks when
        somebody joins is a destination that breaks."""
        with mock.patch.object(tp, "list_chats", return_value=[
                _chat(GUID, "whatever", LIVE + ["+15550001111"])]):
            self.assertEqual(tp.resolve_dest(_dest())["id"], GUID)

    def test_a_reminted_id_self_heals_instead_of_sending_nowhere(self):
        """THE TEXAS DE BRAZIL FAILURE, made loud. The configured id no longer
        exists; the group is found by its people and the send goes to the live
        chat rather than into a defunct thread."""
        with mock.patch.object(tp, "list_chats", return_value=[
                _chat("any;+;NEWID", "1️⃣🎉", LIVE)]):
            got = tp.resolve_dest(_dest())
        self.assertEqual(got["id"], "any;+;NEWID")

    def test_losing_the_pinned_members_refuses_loudly(self):
        with mock.patch.object(tp, "list_chats", return_value=[
                _chat(GUID, "1️⃣🎉", ["+14197697114"])]):
            with self.assertRaises(tp.GroupTextError) as e:
                tp.resolve_dest(_dest())
        self.assertIn("rename is NOT the cause", str(e.exception),
                      "the error should stop somebody chasing the name")

    def test_two_chats_with_the_same_people_are_broken_by_the_guid(self):
        with mock.patch.object(tp, "list_chats", return_value=[
                _chat("any;+;OTHER", "decoy", LIVE),
                _chat(GUID, "1️⃣🎉", LIVE)]):
            self.assertEqual(tp.resolve_dest(_dest())["id"], GUID)

    def test_and_refuses_when_the_guid_matches_neither(self):
        with mock.patch.object(tp, "list_chats", return_value=[
                _chat("any;+;ONE", "a", LIVE),
                _chat("any;+;TWO", "b", LIVE)]):
            with self.assertRaises(tp.GroupTextError):
                tp.resolve_dest(_dest())


class TheOtherSevenGroupsAreUntouched(unittest.TestCase):
    """A destination with no `require_handles` must take the original path --
    resolve by name, every send, exactly as it does today."""

    def test_it_goes_to_resolve_group(self):
        with mock.patch.object(tp, "resolve_group",
                               return_value={"id": "any;+;x", "name": "Reporting",
                                             "participants": "3"}) as rg, \
                mock.patch.object(tp, "list_chats") as lc:
            tp.resolve_dest({"group": "Reporting", "cadence_min": 15})
        rg.assert_called_once_with("Reporting")
        lc.assert_not_called()

    def test_an_empty_pin_list_is_not_a_pin(self):
        with mock.patch.object(tp, "resolve_group",
                               return_value={"id": "1", "name": "n",
                                             "participants": "2"}) as rg:
            tp.resolve_dest({"group": "Reporting", "require_handles": []})
        rg.assert_called_once()


class TheSendCarriesBothHalves(unittest.TestCase):
    """The chart AND the typed list: send_to_group takes the images and the
    caption, and resolves through the destination."""

    def test_the_board_and_caption_reach_the_resolved_chat(self):
        sent = {}

        def fake_osascript(script, timeout=300):
            sent.setdefault("scripts", []).append(script)
            return ""

        with mock.patch.object(tp, "list_chats", return_value=[
                _chat(GUID, "1️⃣🐦‍🔥", LIVE)]), \
                mock.patch.object(tp, "_osascript", fake_osascript):
            res = tp.send_to_group("Ambient Managing Partners",
                                   "*15 min of gaps*\n\nA - 40 min",
                                   [], dry_run=True, dest=_dest())
        self.assertTrue(res["ok"])
        self.assertEqual(res["chat_id"], GUID)
        self.assertEqual(res["participants"], str(len(LIVE)))

    def test_the_scoreboard_text_resolves_the_same_way(self):
        with mock.patch.object(tp, "list_chats", return_value=[
                _chat(GUID, "1️⃣🎉", LIVE)]):
            res = tp.send_text_to_group("Ambient Managing Partners",
                                        "TOTALS: 3", dry_run=True,
                                        dest=_dest())
        self.assertTrue(res["ok"])
        self.assertEqual(res["chat_id"], GUID)


class TheDestTravelsThroughTheBoardSend(unittest.TestCase):
    """knocks_post._text has to hand the DESTINATION over, not a name --
    otherwise a participant-pinned group is looked up by a name that is wrong
    within the hour."""

    def test_text_passes_dest_through(self):
        from automations.icd_alerts import knocks_post as KP
        with mock.patch.object(tp, "send_to_group") as send:
            KP._text(_dest(), ["/tmp/board.png"], "caption")
        self.assertEqual(send.call_args.kwargs.get("dest"), _dest())

    def test_a_plain_name_still_works(self):
        from automations.icd_alerts import knocks_post as KP
        with mock.patch.object(tp, "send_to_group") as send:
            KP._text("Reporting", ["/tmp/board.png"], "caption")
        self.assertIsNone(send.call_args.kwargs.get("dest"))
        self.assertEqual(send.call_args.args[0], "Reporting")


if __name__ == "__main__":
    unittest.main()
