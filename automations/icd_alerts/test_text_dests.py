"""An ICD's board can also go to an iMessage group.

"not instead- this is in addition to" (Megan 2026-09-15). A text destination
is therefore just another destination: it rides the cadence, the due check and
the per-destination sent markers that already exist, instead of a second
posting pass that drifts from the first.

What these pin is the handful of ways that can go quietly wrong.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from automations.icd_alerts import post as P


def _channels_rows(approved_json, approved="TRUE", office="cyrus"):
    """One Office Channels row, padded out to the text columns."""
    head = ["h"] * (P.CH_TX_APPROVED + 1)
    row = [""] * (P.CH_TX_APPROVED + 1)
    row[P.CH_OFFICE] = office
    row[P.CH_TX_APPROVED_JSON] = json.dumps(approved_json)
    row[P.CH_TX_APPROVED] = approved
    return [head, row]


def _book(rows):
    tab = mock.MagicMock()
    tab.get_all_values.return_value = rows
    book = mock.MagicMock()
    book.worksheet.return_value = tab
    return book


class ATextDestinationLooksLikeAChannel(unittest.TestCase):
    """Shaped like approved_knocks() on purpose, so the posting pass can
    concatenate the two and treat them the same."""

    def test_it_carries_the_group_name_not_an_id(self):
        out = P.approved_texts(_book(_channels_rows(
            [{"group": "B2B Box Dispositions", "cadence_min": 30}])))
        d = out["cyrus"][0]
        self.assertEqual(d["channel_name"], "B2B Box Dispositions")
        self.assertEqual(d["channel_id"], "imessage:B2B Box Dispositions")
        self.assertEqual(d["cadence_min"], 30)

    def test_a_bare_string_group_still_works(self):
        out = P.approved_texts(_book(_channels_rows(["Admin Staff"])))
        self.assertEqual(out["cyrus"][0]["channel_name"], "Admin Staff")

    def test_unapproved_is_not_served(self):
        self.assertEqual(
            P.approved_texts(_book(_channels_rows(
                [{"group": "Admin Staff"}], approved="FALSE"))), {})

    def test_a_blank_name_is_dropped_rather_than_sent_nowhere(self):
        # A name that matches no chat delivers nothing and reports success.
        self.assertEqual(
            P.approved_texts(_book(_channels_rows([{"group": "  "}]))), {})

    def test_the_prefix_round_trips(self):
        self.assertTrue(P.is_text_dest("imessage:Admin Staff"))
        self.assertFalse(P.is_text_dest("C09AVM17PAR"))
        self.assertEqual(P.text_group_of("imessage:Admin Staff"),
                         "Admin Staff")


class NothingEverStoresAChatId(unittest.TestCase):
    """A group's chat id is regenerated whenever its membership changes, and a
    stale id does NOT raise -- Messages sends into a thread nobody can see.
    That is how the Texas de Brazil texts went missing for weeks, and Carlos
    is actively adding people to these groups."""

    def test_an_id_is_never_produced_as_the_address(self):
        out = P.approved_texts(_book(_channels_rows(
            [{"group": "Admin Staff",
              "chat_id": "any;+;da1e42ef23df4ff1bb67c6e3b1d10773"}])))
        blob = json.dumps(out)
        self.assertNotIn("any;+;", blob,
                         "a stored chat id reached the send path")

    def test_the_source_says_why(self):
        import inspect
        doc = inspect.getdoc(P.approved_texts) or ""
        self.assertIn("name", doc.lower())


class AMachineThatCannotTextSaysSo(unittest.TestCase):
    """Silently dropping a text destination is a board somebody is waiting for
    that never arrives and never errors."""

    def _run(self, can_text):
        from automations.icd_alerts import knocks_post as KP
        lines = []
        book = mock.MagicMock()
        book.worksheet.side_effect = Exception("no knocks tab")
        with mock.patch.object(KP.P, "RELAY_SPREADSHEET_ID", "x"), \
                mock.patch("automations.recruiting_report.fill.open_by_key",
                           return_value=book):
            KP.run(send=False, log=lines.append)
        return lines

    def test_it_is_announced_not_swallowed(self):
        from automations.icd_alerts import knocks_post as KP
        lines = []
        with mock.patch.object(KP.P, "approved_knocks", return_value={}), \
                mock.patch.object(KP.P, "approved_texts",
                                  return_value={"cyrus": [{"channel_id": "imessage:X"}]}), \
                mock.patch.object(KP, "_can_text", return_value=False):
            tab = mock.MagicMock()
            tab.get_all_values.return_value = [["h"]]
            book = mock.MagicMock()
            book.worksheet.return_value = tab
            with mock.patch("automations.recruiting_report.fill.open_by_key",
                            return_value=book):
                KP.run(send=False, log=lines.append)
        self.assertTrue(
            any("cannot send iMessage" in l for l in lines),
            "a machine that cannot text dropped the destination in silence")


class TheSendPicksTheRightRoute(unittest.TestCase):

    def test_a_text_dest_goes_to_text_not_slack(self):
        from automations.icd_alerts import knocks_post as KP
        # The branch is on the prefix, so this is the whole contract.
        self.assertTrue(P.is_text_dest("imessage:Admin Staff"))
        src = __import__("inspect").getsource(KP.run)
        self.assertIn("P.is_text_dest(d[\"channel_id\"])", src)
        self.assertIn("_text(P.text_group_of", src)

    def test_texting_reuses_the_production_sender(self):
        from automations.icd_alerts import knocks_post as KP
        src = __import__("inspect").getsource(KP._text)
        # Its own AppleScript here would miss the by-name rule and the
        # image delay, both of which fail silently.
        self.assertIn("text_post", src)
        self.assertNotIn("osascript", src)


class ATextThatCannotSendIsLoud(unittest.TestCase):
    """The silent-failure class. A group name is typed on a form, cannot be
    verified from the machine that approves it, and a near-miss delivers
    nothing while reporting success. A line in a run log is not where anybody
    would find that."""

    def test_a_failed_text_reaches_the_ops_channel(self):
        from automations.icd_alerts import knocks_post as KP
        src = __import__("inspect").getsource(KP.run)
        self.assertIn("is_text_dest", src)
        i = src.index("FAILED to post to")
        self.assertIn("OPS_CHANNEL", src[i:i + 1200],
                      "a text that failed to send only wrote to the log")

    def test_a_failed_slack_room_does_not_ping_ops(self):
        # Slack failures are visible other ways and already have handling;
        # pinging for both would make the channel noise.
        from automations.icd_alerts import knocks_post as KP
        src = __import__("inspect").getsource(KP.run)
        i = src.index("FAILED to post to")
        seg = src[i:i + 1200]
        self.assertLess(seg.index("is_text_dest"), seg.index("OPS_CHANNEL"),
                        "ops is pinged before the text check, so every Slack "
                        "failure would ping too")


class TheApprovalReadsTheSignupNotTheRelay(unittest.TestCase):
    """A group chat name never needs to reach the ICD's laptop -- their
    machine hands in counts and WE post. Routing it through the relay would
    mean an Apps Script change and an office waiting on its own machine to
    tell us something it already typed on the form."""

    def test_cmd_texts_reads_the_signup_store(self):
        from automations.icd_alerts import approve as A
        src = __import__("inspect").getsource(A.cmd_texts)
        self.assertIn("signup_store.get", src)

    def test_an_office_that_did_not_ask_is_refused(self):
        from automations.icd_alerts import approve as A
        rec = mock.MagicMock()
        rec.text_groups = []
        out = []
        with mock.patch("automations.icd_signup.store.get", return_value=rec), \
                mock.patch("builtins.print", side_effect=lambda *a: out.append(" ".join(map(str, a)))):
            rc = A.cmd_texts("cyrus")
        self.assertEqual(rc, 1)
        self.assertTrue(any("did not ask" in l for l in out))

    def test_an_unverifiable_name_is_called_unverified(self):
        # Approving from a machine that cannot see Messages must not print
        # something that reads like a check was done.
        from automations.icd_alerts import approve as A
        rec = mock.MagicMock()
        rec.text_groups = ["Admin Staff"]
        out = []
        with mock.patch("automations.icd_signup.store.get", return_value=rec), \
                mock.patch("automations.gap_alerts.config.can_text",
                           return_value=False), \
                mock.patch.object(A, "_write_texts_approval"), \
                mock.patch("builtins.print",
                           side_effect=lambda *a: out.append(" ".join(map(str, a)))):
            rc = A.cmd_texts("cyrus")
        self.assertEqual(rc, 0)
        self.assertTrue(any("UNVERIFIED" in l for l in out))

if __name__ == "__main__":
    unittest.main()
