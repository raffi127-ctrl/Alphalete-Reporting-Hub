"""/personality: the real question file loads, scores right, and the branch
never swallows another Jiraiya feature's envelope. Sends nothing."""
import json
import unittest

from automations.personality import bot as B


class Req:
    def __init__(self, type_, payload):
        self.type, self.payload = type_, payload


class QuestionFileTest(unittest.TestCase):

    def setUp(self):
        self.data = B.load()

    def test_forty_rows_no_sample_left(self):
        self.assertEqual(len(self.data["rows"]), 40)
        self.assertFalse(B.is_sample(self.data))

    def test_every_row_is_one_letter(self):
        # Megan's sheet: all four words in a row share a first letter. A word
        # that slid into the wrong row breaks this.
        for i, r in enumerate(self.data["rows"], 1):
            self.assertEqual(len({r[t][0].lower() for t in B.TYPES}), 1, i)

    def test_one_row_per_popup_with_counter(self):
        m = B.modal(self.data)
        self.assertEqual(m["blocks"][1]["text"]["text"], "1/40")
        btns = [b for b in m["blocks"] if b.get("block_id") == "row1"][0]
        self.assertEqual(sorted(e["text"]["text"] for e in btns["elements"]),
                         sorted(self.data["rows"][0][t] for t in B.TYPES))
        self.assertFalse(any(b.get("block_id") == "nav" for b in m["blocks"]))
        m7 = B.modal(self.data, "0123012")
        self.assertIn({"type": "header", "text": {"type": "plain_text",
                                                  "text": "8/40"}}, m7["blocks"])
        self.assertTrue(any(b.get("block_id") == "nav" for b in m7["blocks"]))
        self.assertLessEqual(len(m["title"]["text"]), 24)

    def test_choices_are_shuffled_not_in_type_order(self):
        # Listed in type order, the first button would always be Popular.
        firsts = set()
        for n in range(40):
            row = [b for b in B.modal(self.data, "0" * n)["blocks"]
                   if b.get("block_id") == "row{}".format(n + 1)][0]
            firsts.add(row["elements"][0]["value"])
        self.assertGreater(len(firsts), 1)

    def test_every_word_has_a_plain_meaning_shown(self):
        for n, r in enumerate(self.data["rows"], 1):
            for t in B.TYPES:
                self.assertTrue(r.get("means", {}).get(t), (n, t))
        txt = json.dumps(B.modal(self.data)["blocks"], ensure_ascii=False)
        self.assertIn("*Analytical* — ", txt)

    def test_tap_and_back(self):
        self.assertEqual(B.step("01", {"action_id": B.PICK + "_perfect",
                                       "value": "2"}), "012")
        self.assertEqual(B.step("012", {"action_id": B.BACK}), "01")
        self.assertEqual(B.step("", {"action_id": B.BACK}), "")


class ScoringTest(unittest.TestCase):

    def test_clear_winner_and_second(self):
        ans = {i: "powerful" for i in range(1, 21)}
        ans.update({i: "perfect" for i in range(21, 33)})
        ans.update({i: "popular" for i in range(33, 41)})
        s = B.score(ans)
        self.assertEqual(s, {"popular": 8, "powerful": 20, "perfect": 12,
                             "peaceful": 0})
        self.assertEqual(B.ranked(s), [["powerful"], ["perfect"]])
        txt = B.result_text(B.load(), s)
        self.assertIn("You're a Powerful Choleric!", txt)
        self.assertIn("Powerful Choleric*\n\nYou're a born leader.", txt)
        self.assertIn("_The classic description:_ Ambitious", txt)
        self.assertNotIn("Words you picked", txt)   # Megan cut it 10/24
        self.assertNotIn("door", txt.lower())     # B2B too, not just D2D
        self.assertIn("Secondary: *Perfect Melancholy", txt)
        # strengths, then weaknesses, at the very bottom
        self.assertLess(txt.index("*In the field:*"),
                        txt.index("Your strengths*"))
        self.assertLess(txt.index("Your strengths*"),
                        txt.index("Watch out for*"))
        self.assertIn("• Confident close", txt)
        self.assertIn("Building your team_\n• Takes charge", txt)
        self.assertIn("• Builds a team fast", txt)

    def test_tie_is_said_as_a_tie(self):
        ans = {i: ("popular" if i <= 20 else "peaceful") for i in range(1, 41)}
        txt = B.result_text(B.load(), B.score(ans))
        self.assertIn("even mix", txt)
        self.assertIn("Popular Sanguine", txt)
        self.assertIn("Peaceful Phlegmatic", txt)

    def test_answers_read_from_the_string(self):
        self.assertEqual(B.answers_of("23"), {1: "perfect", 2: "peaceful"})


class StartScreenTest(unittest.TestCase):

    def sub(self, name, owner):
        return Req("interactive", {"type": "view_submission", "view": {
            "callback_id": B.START, "state": {"values": {
                "name": {"v": {"value": name}},
                "owner": {"v": {"value": owner}}}}}})

    def test_asks_name_then_owner(self):
        m = B.start_modal(B.load(), "Jo Smith")
        ids = [b.get("block_id") for b in m["blocks"]]
        self.assertEqual(ids[1:], ["name", "owner"])
        self.assertEqual(m["blocks"][1]["element"]["initial_value"],
                         "Jo Smith")

    def test_blank_boxes_are_errors_not_a_start(self):
        a = B.ack(self.sub("  ", ""))
        self.assertEqual(a["response_action"], "errors")
        self.assertEqual(set(a["errors"]), {"name", "owner"})

    def test_start_carries_name_and_owner_to_every_row(self):
        a = B.ack(self.sub(" Jo  Smith ", "Raf Hidalgo"))
        self.assertEqual(a["response_action"], "update")
        self.assertEqual(B.meta_of(a["view"]),
                         {"n": "Jo Smith", "o": "Raf Hidalgo", "p": ""})
        nxt = B.modal(B.load(), "01", B.meta_of(a["view"]))
        self.assertEqual(B.meta_of(nxt)["o"], "Raf Hidalgo")

    def test_row_taps_ack_plain(self):
        self.assertIsNone(B.ack(Req("interactive", {
            "type": "block_actions", "view": {"callback_id": B.FORM}})))


class ShareTest(unittest.TestCase):

    S = {"popular": 11, "powerful": 4, "perfect": 10, "peaceful": 15}

    def test_own_copy_has_header_and_share_button(self):
        b = B.result_blocks(B.load(), self.S, {"n": "Jo", "o": "Raf"})
        self.assertEqual(b[0]["type"], "header")
        self.assertIn("You're a Peaceful Phlegmatic!", b[0]["text"]["text"])
        btn = b[-1]["elements"][0]
        self.assertEqual(btn["action_id"], B.SHARE)
        self.assertEqual(json.loads(btn["value"])["s"], [11, 4, 10, 15])
        self.assertTrue(all(len(x["text"]["text"]) <= 3000
                            for x in b if x["type"] == "section"))

    def test_shared_copy_names_them_and_has_no_button(self):
        b = B.result_blocks(B.load(), self.S, {}, share=False, name="Jo")
        self.assertIn("Jo is a Peaceful Phlegmatic!", b[0]["text"]["text"])
        self.assertNotEqual(b[-1]["type"], "actions")

    def test_share_clicks_and_form_are_ours(self):
        self.assertTrue(B.wants(Req("interactive", {
            "type": "block_actions", "actions": [{"action_id": B.SHARE}]})))
        self.assertTrue(B.wants(Req("interactive", {
            "type": "view_submission",
            "view": {"callback_id": B.SHARE_FORM}})))

    def test_share_sends_to_picked_people_not_self(self):
        sent = []

        class Web:
            def chat_postMessage(self, **kw):
                sent.append(kw)
        val = json.dumps({"s": [11, 4, 10, 15], "n": "Jo", "o": "Raf"})
        B._share(Web(), "U_ME", val, ["U_LEAD", "U_ME"])
        self.assertEqual([m["channel"] for m in sent], ["U_LEAD", "U_ME"])
        self.assertIn("Jo is a Peaceful Phlegmatic!", sent[0]["text"])
        self.assertIn("<@U_LEAD>", sent[1]["text"])


class SheetRowTest(unittest.TestCase):

    def test_row_lines_up_with_header(self):
        import datetime as dt
        s = {"popular": 11, "powerful": 4, "perfect": 10, "peaceful": 15}
        row = B.sheet_row(B.load(), "U1", {"n": "Jo", "o": "Raf"}, s,
                          dt.datetime(2026, 10, 24, 15, 5))
        self.assertEqual(len(row), len(B.SHEET_HEADER))
        r = dict(zip(B.SHEET_HEADER, row))
        self.assertEqual(r["Primary"], "Peaceful Phlegmatic")
        self.assertEqual(r["Secondary"], "Popular Sanguine")
        self.assertEqual((r["Name"], r["ICD Owner"]), ("Jo", "Raf"))
        self.assertNotIn("Description", r)   # Megan: sheet = who + result

    def test_tie_keeps_both(self):
        s = {"popular": 20, "powerful": 0, "perfect": 0, "peaceful": 20}
        r = dict(zip(B.SHEET_HEADER, B.sheet_row(B.load(), "U1", {}, s)))
        self.assertEqual(r["Primary"], "Popular Sanguine + Peaceful Phlegmatic")
        self.assertEqual(r["Secondary"], "")


class WantsTest(unittest.TestCase):

    def test_claims_its_own(self):
        self.assertTrue(B.wants(Req("slash_commands",
                                    {"command": "/personality"})))
        self.assertTrue(B.wants(Req("interactive", {
            "type": "block_actions",
            "view": {"callback_id": B.FORM}})))

    def test_leaves_others_alone(self):
        for cmd in ("/dd", "/knocks", "/aca", "/recruiting-audit"):
            self.assertFalse(B.wants(Req("slash_commands", {"command": cmd})))
        for cb in ("dd_form", "knocks_form", "aca_form", "promo_remove_modal",
                   B.FORM):
            self.assertFalse(B.wants(Req("interactive", {
                "type": "view_submission", "view": {"callback_id": cb}})))
        self.assertFalse(B.wants(Req("interactive", {"type": "block_actions",
                                                     "actions": []})))
        for cb in ("aca_form", "knocks_form"):
            self.assertFalse(B.wants(Req("interactive", {
                "type": "block_actions", "view": {"callback_id": cb}})))
        self.assertFalse(B.wants(Req("events_api", {"event": {}})))


if __name__ == "__main__":
    unittest.main()
