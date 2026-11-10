"""Offline tests — no model, no AppStream, no Sheets, no Slack.

    python -m unittest automations.applicant_replies.test_applicant_replies
"""
from __future__ import annotations

import ast
import datetime as dt
import unittest
from pathlib import Path

from automations.applicant_replies import config as C
from automations.applicant_replies import draft as D
from automations.applicant_replies import facts as F
from automations.applicant_replies import guard as G
from automations.applicant_replies import triage as T

T0 = dt.datetime(2026, 10, 1, 10, 0)
PKG = Path(__file__).resolve().parent


def msg(mins, d, body, ai=False):
    return {"when": T0 + dt.timedelta(minutes=mins), "dir": d, "body": body,
            "sent_by": "AI Messaging" if ai else ("" if d == "In" else "Dani Pena"),
            "source": "AI Messaging" if ai else "", "template": "", "status": ""}


def convo(*msgs):
    return {"phone": "9725550101", "name": "Test", "msgs": list(msgs)}


def reason(*msgs, log_end=None):
    t = T.turns(convo(*msgs))[-1]
    return T.classify(t, log_end)[0]


class Triage(unittest.TestCase):
    def test_opt_out_beats_everything(self):
        self.assertEqual(reason(msg(0, "In", "Not interested, please call me never")),
                         "opt_out")

    def test_spanish(self):
        self.assertEqual(reason(msg(0, "In", "Hola, ¿es trabajo de oficina?")),
                         "spanish")

    def test_scam(self):
        self.assertEqual(reason(msg(0, "In", "Is this a scam?")), "scam")

    def test_call_me(self):
        self.assertEqual(reason(msg(0, "In", "Can you call me instead")), "call_me")

    def test_ai_dodge(self):
        self.assertEqual(reason(
            msg(0, "In", "Is this commission or hourly pay?"),
            msg(2, "Out", "The Hiring Manager can answer compensation "
                          "questions. What's the best email?", ai=True)), "dodged")

    def test_ai_good_answer_left_alone(self):
        self.assertIsNone(reason(
            msg(0, "In", "What are the hours?"),
            msg(2, "Out", "Our shifts range from 8am - 8pm, Monday - Saturday.",
                ai=True)))

    def test_recruiter_reply_left_alone(self):
        self.assertIsNone(reason(msg(0, "In", "What is the pay?"),
                                 msg(5, "Out", "anything at all")))

    def test_unanswered(self):
        self.assertEqual(reason(msg(0, "In", "What is the pay?"),
                                msg(C.WAIT_MINUTES + 30, "Out", "hi")),
                         "unanswered")

    def test_closer_is_not_unanswered(self):
        self.assertIsNone(reason(msg(0, "In", "Ok thanks!")))

    def test_log_end_too_soon_is_unknown(self):
        self.assertIsNone(reason(msg(0, "In", "What is the pay?"),
                                 log_end=T0 + dt.timedelta(minutes=3)))

    def test_two_word_spanish(self):
        self.assertEqual(reason(msg(0, "In", "De que es el trabajo")), "spanish")

    def test_english_is_not_spanish(self):
        self.assertNotEqual(reason(msg(0, "In", "What time is the interview?")),
                            "spanish")

    def test_withdraw_is_opt_out(self):
        self.assertEqual(reason(msg(0, "In", "I'd like to withdraw my application")),
                         "opt_out")

    def test_no_one_called_is_call_me(self):
        self.assertEqual(reason(msg(0, "In", "Hi Dani, I didn't receive any calls")),
                         "call_me")

    def test_booking_talk_is_scheduling_not_lucys(self):
        self.assertEqual(reason(msg(0, "In", "i can do 4pm"),
                                msg(C.WAIT_MINUTES + 20, "Out", "x")),
                         "scheduling")
        self.assertIsNone(reason(msg(0, "In", "i can do 4pm"),
                                 msg(5, "Out", "Booked!", ai=True)))

    def test_reaction_ignored(self):
        self.assertIsNone(reason(msg(0, "In", "Liked “No worries! See you then.”")))

    def test_two_phrase_closers(self):
        for q in ("Ok thanks!", "You too and enjoy your weekend",
                  "Of course. Thank you, and likewise!"):
            self.assertIsNone(reason(msg(0, "In", q)), q)

    def test_burst_is_one_turn(self):
        ts = T.turns(convo(msg(0, "In", "Hi"), msg(1, "In", "where is it?"),
                           msg(3, "Out", "x")))
        self.assertEqual(len(ts), 1)
        self.assertEqual(ts[0]["q"], "Hi where is it?")
        self.assertEqual(int(ts[0]["wait_min"]), 2)


class Guard(unittest.TestCase):
    O = "11580"   # Grand Prairie, no move on file

    def setUp(self):
        F.office(self.O)

    def ok(self, text, reason=None):
        return G.check(self.O, text, None, reason)[1]

    def test_clean_answer_passes(self):
        self.assertEqual(self.ok("Our shifts range from 8am - 8pm, Monday - "
                                 "Saturday. Does that work for you?"), [])

    def test_approved_call_line_passes(self):
        self.assertEqual(self.ok("Of course - I'll have someone from our team "
                                 "give you a call."), [])

    def test_timed_call_held(self):
        self.assertTrue(self.ok("I'll have someone give you a call shortly!"))

    def test_base_pay_held(self):
        self.assertTrue(self.ok("There is a base pay plus commission."))

    def test_deflection_held(self):
        self.assertTrue(self.ok("The hiring manager can go over that with you."))

    def test_shouting_held(self):
        self.assertTrue(self.ok("You applied to our ENTRY LEVEL ROLE AT "
                                "ALPHALETE TODAY"))

    def test_wrong_address_held(self):
        self.assertTrue(self.ok("Our office is at 3100 Premier Dr, Suite 207."))

    def test_protected_wording_held(self):
        self.assertTrue(self.ok("We hire young people ready to work."))

    def test_placeholder_held(self):
        self.assertTrue(self.ok("You applied to our [Role] position."))

    def test_reply_to_opt_out_held(self):
        self.assertTrue(self.ok("Sorry to hear that!", reason="opt_out"))
        self.assertEqual(self.ok("", reason="opt_out"), [])

    def test_curly_quotes_are_fixed_not_held(self):
        text, probs = G.check(self.O, "That’s right — it’s a "
                              "small group interview.", None)
        self.assertEqual(probs, [])
        self.assertNotIn("’", text)

    def test_too_long_held(self):
        self.assertTrue(self.ok("This is fine. " * 30))


class Facts(unittest.TestCase):
    def test_moved_office_uses_new_address_after_the_move(self):
        txt, _ = F.block("11280", dt.date(2026, 10, 20))
        self.assertIn("Plano", txt)
        txt, _ = F.block("11280", dt.date(2026, 9, 20))
        self.assertIn("Irving", txt)

    def test_raf_gets_raf_pay_line(self):
        txt, gaps = F.block("11280")
        self.assertIn("$1,000-$1,500", txt)
        self.assertNotIn("pay range", gaps)

    def test_other_office_without_pay_has_a_gap_not_rafs_number(self):
        txt, gaps = F.block("11580")
        self.assertNotIn("$1,000", txt.split("Company-wide")[0])
        self.assertIn("pay range", gaps)

    def test_company_name_raf_only(self):
        self.assertIn("Alphalete Marketing, Inc.", F.block("23965")[0])
        txt, gaps = F.block("11580")
        self.assertNotIn("Alphalete", txt)
        self.assertIn("company name", gaps)

    def test_unknown_office(self):
        txt, gaps = F.block("99999")
        self.assertIsNone(txt)
        self.assertTrue(gaps)

    def test_prompt_never_carries_old_wording(self):
        txt, _ = F.block("11280")
        whole = D.SYSTEM + txt
        self.assertNotRegex(whole.lower(), r"base (salary|pay) is")
        self.assertNotIn("ALPHALETE", whole)


class NeverSends(unittest.TestCase):
    """Shadow only (Megan 2026-10-20). If a send path is ever added, it must
    come with an account in ENABLED_OFFICES and this test changed on purpose."""

    BANNED_IMPORTS = ("playwright", "slack_sdk", "automations.shared.slack",
                      "automations.oat_processing", "automations.applicant_push",
                      "smtplib", "requests")
    BANNED_TEXT = ("btn-sms-send", "ta_smsChat", "chat.postMessage",
                   "send_message", "imessage")

    def test_no_accounts_enabled(self):
        self.assertEqual(C.ENABLED_OFFICES, frozenset())

    def test_no_send_path(self):
        for f in PKG.glob("*.py"):
            if f.name.startswith("test_"):
                continue
            src = f.read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(src)):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for n in names:
                    for b in self.BANNED_IMPORTS:
                        self.assertFalse(n.startswith(b),
                                         "{} imports {}".format(f.name, n))
            for b in self.BANNED_TEXT:
                self.assertNotIn(b, src, "{} mentions {}".format(f.name, b))


if __name__ == "__main__":
    unittest.main()
