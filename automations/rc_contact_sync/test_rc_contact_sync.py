"""Pure-logic tests. NO network, NO browser, NO Slack — safe to run anywhere.
[[feedback_no_blind_test_sweeps]]

  python -m pytest automations/rc_contact_sync/test_rc_contact_sync.py -q
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.rc_contact_sync import ringcentral as RC
from automations.rc_contact_sync import run as R
from automations.rc_contact_sync import sara
from automations.rc_contact_sync import verify_code as VC

# The header row and four rows exactly as the live grid showed them
# (Carlos's Loom, 2026-09-02).
HEADERS = ["", "", "Order ID", "Order Date", "Order Time", "User Name",
           "Employee ID", "Business Name", "Viewing Type", "Business Type"]
ROWS = [
    ["View Customer", "Modify", "DSI269931154", "9/01/2026", "13:11:25",
     "FERNANDO SALAZAR", "", "BOTANICA Y DULCERIA SAGRADO CORAZON DE JESUS",
     "", "sole-prop"],
    ["View Customer", "Modify", "DSI269961203", "9/01/2026", "15:01:02",
     "JACOB ISAIAH ORTEGA", "", "BABER GAUT SHOPS", "", "sole-prop"],
]


class TestPhones(unittest.TestCase):
    def test_norm_phone_agrees_across_formats(self):
        for v in ("(214) 845-6450", "+12148456450", "214.845.6450",
                  "1-214-845-6450"):
            self.assertEqual(RC.norm_phone(v), "2148456450", v)

    def test_e164(self):
        self.assertEqual(RC.e164("(214) 845-6450"), "+12148456450")
        self.assertEqual(RC.e164("12148456450"), "+12148456450")
        self.assertEqual(RC.e164(""), "")

    def test_short_or_missing_numbers_do_not_become_a_match(self):
        self.assertEqual(RC.norm_phone("ext 134"), "134")
        self.assertEqual(RC.norm_phone(""), "")


class TestNames(unittest.TestCase):
    def test_split_name_title_cases_saraplus_caps(self):
        self.assertEqual(RC.split_name("FERNANDO SALAZAR"),
                         ("Fernando", "Salazar"))
        self.assertEqual(RC.split_name("JACOB ISAIAH ORTEGA"),
                         ("Jacob", "Isaiah Ortega"))

    def test_split_name_uses_the_house_casing(self):
        """shared.name_case is canonical, so this matches every other report's
        spelling of a name rather than inventing a second rule."""
        self.assertEqual(RC.split_name("Maria de la Cruz"),
                         ("Maria", "De La Cruz"))

    def test_split_name_empty(self):
        self.assertEqual(RC.split_name(""), ("", ""))


class TestAddressBookIndex(unittest.TestCase):
    def test_every_phone_field_is_indexed(self):
        book = [{"id": 1, "businessPhone": "+12148456450"},
                {"id": 2, "mobilePhone": "(469) 555-0111"}]
        idx = RC.index_by_phone(book)
        self.assertEqual(idx["2148456450"]["id"], 1)
        self.assertEqual(idx["4695550111"]["id"], 2)

    def test_a_contact_with_no_number_is_not_indexed(self):
        self.assertEqual(RC.index_by_phone([{"id": 3, "company": "X"}]), {})


class TestIdentity(unittest.TestCase):
    """The wrong-but-valid token is the failure that would look green."""
    ME = {"name": "Taylor Miller", "email": "taylormkmiller7@gmail.com",
          "extension_number": "134", "account_id": "111"}

    def test_the_right_user_passes(self):
        RC.assert_identity(self.ME, "taylormkmiller7@gmail.com")

    def test_case_and_padding_do_not_matter(self):
        RC.assert_identity(self.ME, "  TaylorMKMiller7@Gmail.com ")

    def test_another_user_in_the_same_account_is_refused(self):
        carlos = dict(self.ME, name="Carlos Hidalgo",
                      email="carloshidalgo349@gmail.com", extension_number="101")
        with self.assertRaises(RC.RCError) as cm:
            RC.assert_identity(carlos, "taylormkmiller7@gmail.com")
        self.assertIn("Carlos Hidalgo", str(cm.exception))

    def test_a_token_with_no_email_is_refused(self):
        with self.assertRaises(RC.RCError):
            RC.assert_identity(dict(self.ME, email=""),
                               "taylormkmiller7@gmail.com")

    def test_an_empty_expectation_turns_the_check_off(self):
        """Deliberate opt-out lives in the creds file, not in a code change."""
        RC.assert_identity(dict(self.ME, email="someone@else.com"), "")


class TestTexted(unittest.TestCase):
    def _sms(self, frm, to, body=""):
        return {"from": {"phoneNumber": frm},
                "to": [{"phoneNumber": to}], "subject": body}

    def test_matches_on_phone_either_direction(self):
        inbound = [self._sms("+12148456450", "+19725550134")]
        outbound = [self._sms("+19725550134", "+12148456450")]
        self.assertTrue(RC.texted(inbound, "(214) 845-6450", []))
        self.assertTrue(RC.texted(outbound, "(214) 845-6450", []))

    def test_matches_on_business_name_when_the_number_differs(self):
        msgs = [self._sms("+15125550000", "+19725550134",
                          "Hi, this is Baber Gaut Shops about the install")]
        self.assertTrue(RC.texted(msgs, "2148456450", ["Baber Gaut Shops"]))

    def test_no_match_is_no_match(self):
        msgs = [self._sms("+15125550000", "+19725550134", "wrong number")]
        self.assertFalse(RC.texted(msgs, "2148456450", ["Baber Gaut Shops"]))

    def test_short_names_never_match(self):
        """A 2-3 letter name would match half the day's traffic."""
        msgs = [self._sms("+15125550000", "+19725550134", "on my way")]
        self.assertFalse(RC.texted(msgs, "2148456450", ["Ay", "M"]))

    def test_a_customer_with_no_phone_still_matches_by_name(self):
        msgs = [self._sms("+15125550000", "+19725550134",
                          "Botanica Y Dulceria confirmed")]
        self.assertTrue(RC.texted(msgs, "", ["Botanica Y Dulceria"]))


class TestGridParsing(unittest.TestCase):
    def _tables(self, headers=None, rows=None):
        return [{"index": 0, "headers": ["nav", "junk"], "rows": [["a", "b"]]},
                {"index": 1, "headers": headers or HEADERS,
                 "rows": rows if rows is not None else ROWS}]

    def test_columns_are_found_by_label_not_position(self):
        got = sara.parse_tables(self._tables())
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["User Name"], "FERNANDO SALAZAR")
        self.assertEqual(got[0]["Business Name"],
                         "BOTANICA Y DULCERIA SAGRADO CORAZON DE JESUS")
        self.assertEqual(got[1]["Order ID"], "DSI269961203")

    def test_a_reordered_grid_still_reads_correctly(self):
        """The whole point of by-label lookup: SaraPlus moves a column and the
        rep is still the rep."""
        headers = ["", "", "Order Date", "Business Name", "Order ID",
                   "User Name", "Order Time"]
        rows = [["View Customer", "Modify", "9/01/2026", "BABER GAUT SHOPS",
                 "DSI269961203", "JACOB ISAIAH ORTEGA", "15:01:02"]]
        got = sara.parse_tables(self._tables(headers, rows))
        self.assertEqual(got[0]["User Name"], "JACOB ISAIAH ORTEGA")
        self.assertEqual(got[0]["Business Name"], "BABER GAUT SHOPS")

    def test_a_missing_column_raises_instead_of_guessing(self):
        headers = [h for h in HEADERS if h != "Business Name"]
        with self.assertRaises(sara.SaraError):
            sara.parse_tables(self._tables(headers, [r[:9] for r in ROWS]))

    def test_footer_and_spacer_rows_are_dropped(self):
        rows = ROWS + [[], ["", "", "", "", "", "Totals", "", "", "", ""]]
        self.assertEqual(len(sara.parse_tables(self._tables(None, rows))), 2)

    def test_row_index_is_kept_for_the_view_customer_click(self):
        got = sara.parse_tables(self._tables())
        self.assertEqual([r["_row"] for r in got], [0, 1])


class TestSlackMessage(unittest.TestCase):
    """A header post carrying Carlos's wording, and the names in ITS thread."""

    def test_the_header_carries_no_markup_of_its_own(self):
        """ensure_named_thread bolds the title and appends the date; markup
        here would render as **double** stars."""
        self.assertNotIn("*", R.thread_title())
        self.assertIn("wrap up text", R.thread_title())

    def test_all_messaged_says_so(self):
        self.assertIn("All 4 customers were messaged",
                      R.missing_names_reply([], 4))

    def test_missing_are_grouped_under_their_rep(self):
        missing = [
            {"rep": "FERNANDO SALAZAR", "business": "BABER GAUT SHOPS",
             "customer_name": "JOSE GAUT", "phone": "(214) 845-6450"},
            {"rep": "FERNANDO SALAZAR", "business": "DAS FINANCIAL SERVICES",
             "customer_name": "", "phone": ""},
        ]
        msg = R.missing_names_reply(missing, 5)
        self.assertIn("2 of 5 customers", msg)
        self.assertEqual(msg.count("*Fernando Salazar*"), 1)
        self.assertIn("Baber Gaut Shops — Jose Gaut — (214) 845-6450", msg)
        self.assertIn("no phone on file", msg)

    def test_reps_are_bold_text_never_mentions(self):
        """A name lookup in this workspace eventually tags the wrong person."""
        msg = R.missing_names_reply(
            [{"rep": "FERNANDO SALAZAR", "business": "X SHOP", "phone": ""}], 1)
        self.assertNotIn("<@", msg)
        self.assertNotIn("@Fernando", msg)

    def test_an_order_with_no_rep_still_gets_reported(self):
        msg = R.missing_names_reply(
            [{"rep": "", "business": "X SHOP", "phone": ""}], 1)
        self.assertIn(R.NO_REP, msg)

    def test_singular_grammar(self):
        self.assertIn("The 1 customer was messaged", R.missing_names_reply([], 1))
        self.assertIn("1 of 2 customers never got a message",
                      R.missing_names_reply([{"rep": "A B", "business": "X"}], 2))


class TestVerificationCode(unittest.TestCase):
    """Pulling the SaraPlus login code out of an email. No IMAP here."""

    def test_labelled_forms(self):
        for text, want in [
            ("Your SaraPlus verification code is 481920", "481920"),
            ("Security code: 4820", "4820"),
            ("392014 is your SaraPlus login code", "392014"),
            ("One-time code\n\n  228841", "228841"),
        ]:
            self.assertEqual(VC.extract_code(text), want, text)

    def test_a_labelled_code_wins_over_a_stray_six_digit_run(self):
        """An order id or a phone number in the footer must not be read as
        the code."""
        text = ("Order 269931 shipped.\nYour verification code is 481920.\n"
                "Call 2148456450.")
        self.assertEqual(VC.extract_code(text), "481920")

    def test_no_code_is_none_not_a_guess(self):
        self.assertIsNone(VC.extract_code("Order DSI269931154 shipped"))
        self.assertIsNone(VC.extract_code(""))

    def test_html_mail_is_flattened_before_matching(self):
        import email as _email
        msg = _email.message_from_string(
            "Subject: SaraPlus\nContent-Type: text/html\n\n"
            "<p>Your <b>verification code</b> is <span>481920</span></p>")
        self.assertEqual(VC.extract_code(VC._body_text(msg)), "481920")

    def test_the_subject_line_is_searched_too(self):
        import email as _email
        msg = _email.message_from_string(
            "Subject: 481920 is your SaraPlus login code\n\nThanks.")
        self.assertEqual(VC.extract_code(VC._body_text(msg)), "481920")


if __name__ == "__main__":
    unittest.main()
