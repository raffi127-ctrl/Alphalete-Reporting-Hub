import datetime as dt
import unittest

from automations.rc_contact_sync import followup as F

HDR = ["Week Ending", "Rep", "Customer", "Order Date", "DSI #", "Wireless Order #", "Line",
       "Phone #", "Line Status"]
WE = dt.date(2026, 11, 1)


def row(**kw):
    base = {"Week Ending": "11/01/2026", "Rep": "Andrew De La Torre", "Customer": "Thomas Blake",
            "Order Date": "10/27/2026", "DSI #": "DSI1", "Wireless Order #": "99-1", "Line": "3",
            "Phone #": "214-555-0003", "Line Status": "Delivered"}
    base.update(kw)
    return [base[h] for h in HDR]


def msg(day, hh, mm, tag, body=""):
    return {"when": dt.datetime(2026, 11, day, hh, mm), "tag": tag, "body": body}


class Pending(unittest.TestCase):
    def test_only_pending_lines_of_that_week_but_every_phone_of_the_order(self):
        rows = [row(Line="1", **{"Phone #": "214-555-0001", "Line Status": "Active"}),
                row(Line="3"),
                row(Line="4", **{"Phone #": "214-555-0004", "Line Status": "Shipped"}),
                row(Customer="Done Deal", **{"DSI #": "DSI2", "Line Status": "Cancelled"}),
                row(Customer="Other Week", **{"DSI #": "DSI3", "Week Ending": "11/08/2026"})]
        out = F.pending_customers(HDR, rows, WE)
        self.assertEqual([o["customer"] for o in out], ["Thomas Blake"])
        self.assertEqual(out[0]["lines"], [("3", "Delivered"), ("4", "Shipped")])
        self.assertEqual(len(out[0]["phones"]), 3)            # the Active line's number counts too

    def test_blank_status_is_pending_and_header_resolved(self):
        shuffled = list(reversed(HDR))
        r = dict(zip(HDR, row(**{"Line Status": ""})))
        out = F.pending_customers(shuffled, [[r[h] for h in shuffled]], WE)
        self.assertEqual(out[0]["lines"], [("3", "(blank)")])


class TabPhones(unittest.TestCase):
    def test_every_number_of_a_named_customer(self):
        rows = [row(Line="1", **{"Phone #": "214-555-0001", "Line Status": "Active"}), row(Line="3"),
                row(Customer="Someone Else", **{"Phone #": "214-555-0009"})]
        out = F.tab_phones(HDR, rows, ["thomas", "Blake"])
        self.assertEqual((out["name"], out["rep"], len(out["phones"])), ("Thomas Blake", "Andrew De La Torre", 2))
        self.assertEqual(out["lines"], ["L1 Active", "L3 Delivered"])
        self.assertEqual(F.tab_phones(HDR, rows, ["nobody"])["phones"], [])


class Conversations(unittest.TestCase):
    def test_answered_conversation_and_its_length(self):
        c = F.conversations([msg(9, 10, 0, "IN", "ipad sim wont swap"), msg(9, 10, 12, "OUT", "try this"),
                             msg(9, 10, 40, "IN", "ok thanks")])
        self.assertEqual(len(c), 1)
        self.assertEqual((c[0]["minutes"], c[0]["n_in"], c[0]["n_us"]), (40, 2, 1))
        self.assertTrue(c[0]["answered"])
        self.assertEqual(c[0]["reply_minutes"], 12)
        self.assertEqual(c[0]["last_tag"], "IN")

    def test_auto_text_is_not_an_answer_and_gap_splits(self):
        c = F.conversations([msg(2, 7, 0, "AUTO", "Hello! I see that your device(s) have been delivered"),
                             msg(2, 9, 0, "IN", "nothing delivered yet"),
                             msg(5, 9, 0, "REP", "hey checking in")])
        self.assertEqual(len(c), 2)
        self.assertFalse(c[0]["answered"])                    # nobody wrote back in that run
        self.assertEqual((c[0]["n_in"], c[0]["n_us"], c[0]["n_auto"]), (1, 0, 1))
        self.assertFalse(c[1]["first_in"])                    # three days later, ours alone

    def test_lone_auto_text_is_no_conversation(self):
        self.assertEqual(F.conversations([msg(2, 7, 0, "AUTO", "x")]), [])

    def test_a_reply_before_the_customer_wrote_does_not_count(self):
        c = F.conversations([msg(3, 8, 0, "OUT", "hi, checking in"), msg(3, 8, 30, "IN", "phones never came")])
        self.assertFalse(c[0]["answered"])


class Verdicts(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(F.verdict([], []), "NO CONTACT FROM THE CUSTOMER")
        open_ = F.conversations([msg(2, 9, 0, "IN", "help")])
        self.assertEqual(F.verdict(open_, []), "WAITING ON US: no reply to the latest conversation")
        ok = F.conversations([msg(2, 9, 0, "IN", "help"), msg(2, 9, 5, "OUT", "on it")])
        self.assertEqual(F.verdict(ok, []), "ANSWERED")
        last = F.conversations([msg(2, 9, 0, "IN", "help"), msg(2, 9, 5, "OUT", "on it"), msg(2, 9, 9, "IN", "still broken")])
        self.assertTrue(F.verdict(last, []).startswith("WAITING ON US: answered at first"))
        # a closing "thanks" after our reply is simply answered
        done = F.conversations([msg(2, 9, 0, "IN", "help"), msg(2, 9, 5, "OUT", "on it"), msg(2, 9, 9, "IN", "Thanks!")])
        self.assertEqual(F.verdict(done, []), "ANSWERED")
        # 11/15: "Ok" and a tapback need no reply; a next-day text from us is a late answer
        self.assertEqual(F.verdict(F.conversations([msg(2, 9, 0, "IN", "Ok")]), []), "ANSWERED")
        self.assertTrue(F.needs_no_reply("Liked “Hey Chris, as a friendly reminder”"))
        self.assertFalse(F.needs_no_reply("Ask Taylor to phone me 469-435-9609"))
        late = F.conversations([msg(9, 16, 46, "IN", "Ask Taylor to phone me"), msg(10, 10, 50, "OUT", "hi Thomas")])
        self.assertEqual(late[0]["late_minutes"], 18 * 60 + 4)
        self.assertEqual(F.verdict(late, []), "ANSWERED LATE (18 h 04 min after the customer's text)")
        # an old unanswered ask with newer answered talk still shows
        old = F.conversations([msg(1, 9, 0, "IN", "where is my phone"), msg(5, 9, 0, "IN", "hello?"), msg(5, 9, 5, "OUT", "here")])
        self.assertEqual(F.verdict(old, []), "ANSWERED LATE (4 d 0 h after the customer's text)")
        calls = [{"when": dt.datetime(2026, 11, 3, 14, 0), "inbound": True, "result": "Missed", "seconds": 0},
                 {"when": dt.datetime(2026, 11, 3, 15, 0), "inbound": True, "result": "Accepted", "seconds": 245}]
        self.assertEqual(F.verdict([], calls), "2 inbound call(s), 1 not picked up")
        self.assertEqual(F.call_line(calls[1]), "11/03 15:00  IN  call  Accepted  4:05")

    def test_span(self):
        self.assertEqual([F.span(0), F.span(12), F.span(125), F.span(27 * 60)],
                         ["under a minute", "12 min", "2 h 05 min", "1 d 3 h"])


if __name__ == "__main__":
    unittest.main()
