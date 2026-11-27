import unittest

from automations.rc_contact_sync import resend_failed as R

OWN = "9450000000"
CUST, REP, OTHER = "2145550001", "2145550099", "2145550002"


def msg(i, t, to, text, status="Delivered", direction="Outbound", att=None):
    return {"id": str(i), "creationTime": "2026-11-27T%s:00Z" % t, "direction": direction,
            "messageStatus": status, "to": [{"phoneNumber": "+1" + n} for n in to],
            "from": {"phoneNumber": "+1" + OWN}, "subject": text, "attachments": att or []}


class Plan(unittest.TestCase):
    def acts(self, msgs, already=()):
        return [(r["msg"]["id"], r["action"]) for r in R.plan(msgs, OWN, already)]

    def test_failed_alone_is_resent_to_the_same_chain(self):
        p = R.plan([msg(1, "10:00", [CUST, REP], "Hello Pat Example", "SendingFailed")], OWN)
        self.assertEqual(p[0]["action"], "resend")
        self.assertEqual(set(p[0]["chain"]), {CUST, REP})

    def test_already_resent_by_hand_is_skipped(self):
        self.assertEqual(self.acts([msg(1, "10:00", [CUST, REP], "Hello Pat Example", "SendingFailed"),
                                    msg(2, "11:00", [CUST, REP], "Hello Pat Example!")]),
                         [("1", "skip")])

    def test_resent_one_to_one_without_rep_counts(self):
        self.assertEqual(self.acts([msg(1, "10:00", [CUST, REP], "Hello Pat Example", "SendingFailed"),
                                    msg(2, "11:00", [CUST], "Hello Pat Example")]),
                         [("1", "skip")])

    def test_same_words_to_another_customer_with_same_rep_do_not_count(self):
        self.assertEqual(self.acts([msg(1, "10:00", [CUST, REP], "Hello! your device has been delivered", "SendingFailed"),
                                    msg(2, "11:00", [OTHER, REP], "Hello! your device has been delivered")]),
                         [("1", "resend")])

    def test_different_later_text_does_not_count(self):
        self.assertEqual(self.acts([msg(1, "10:00", [CUST], "Your order number is 99-1", "SendingFailed"),
                                    msg(2, "11:00", [CUST], "Did you get the phones yet?")]),
                         [("1", "resend")])

    def test_repeat_failures_resend_once_and_state_blocks_rerun(self):
        ms = [msg(1, "10:00", [CUST], "Hi Pat", "SendingFailed"), msg(2, "10:05", [CUST], "Hi Pat", "SendingFailed")]
        self.assertEqual(self.acts(ms), [("1", "resend"), ("2", "skip")])
        self.assertEqual(self.acts(ms[:1], already=["1"]), [("1", "skip")])

    def test_carrier_refusal_is_not_resent(self):
        self.assertEqual(self.acts([msg(1, "10:00", [CUST], "Hi Pat", "DeliveryFailed")]), [("1", "skip")])

    def test_test_text_and_two_customer_thread_not_resent(self):
        self.assertEqual(self.acts([msg(1, "10:00", [CUST], "ff", "SendingFailed")]), [("1", "skip")])
        names = {CUST: "Pat Example", OTHER: "Sam Sample - Line 2"}
        p = R.plan([msg(1, "10:00", [CUST, OTHER], "call 833-555-0100", "SendingFailed")], OWN, names=names)
        self.assertEqual(p[0]["action"], "skip")
        p = R.plan([msg(1, "10:00", [CUST, OTHER], "Hello! I see that your device(s) have been delivered!",
                        "SendingFailed")], OWN, names=names)
        self.assertEqual(p[0]["action"], "resend")

    def test_inbound_and_delivered_ignored(self):
        self.assertEqual(self.acts([msg(1, "10:00", [CUST], "Hi"), msg(2, "10:01", [OWN], "hey", direction="Inbound")]), [])


if __name__ == "__main__":
    unittest.main()
