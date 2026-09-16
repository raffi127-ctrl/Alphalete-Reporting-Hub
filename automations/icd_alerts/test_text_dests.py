"""An ICD's board can also go to an iMessage group.

"not instead- this is in addition to" (Megan 2026-09-15). A text destination
is therefore just another destination: it rides the cadence, the due check and
the per-destination sent markers that already exist, instead of a second
posting pass that drifts from the first.

What these pin is the handful of ways that can go quietly wrong.
"""
from __future__ import annotations

import json
import pathlib
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


class ChangingCadenceMustNotUnapproveAnOffice(unittest.TestCase):
    """"Knocks: Wanted" belongs to the OFFICE. Their machine re-sends what it
    was installed with on every sweep, and the relay treats a disagreement as
    "they are asking for somewhere different" -- which clears the approval.

    Cyrus's cadence was changed on 2026-09-15 by editing both columns so the
    sheet would not contradict itself. His machine put its own number back,
    the relay un-approved him, and his board posted nothing for the rest of
    the day without a word.
    """

    def test_it_writes_only_our_column(self):
        import inspect
        src = inspect.getsource(P.set_knocks_cadence)
        self.assertIn("K%d:L%d", src, "it does not write the approved column")
        for theirs in ("CH_KN_WANTED", "CH_KN_JSON"):
            self.assertNotIn("range_name=\"%s" % theirs, src)
        # The office's columns must not be written at all.
        body = src.split('"""')[-1]
        self.assertNotIn("CH_KN_WANTED", body,
                         "it writes the office's own column, which is what "
                         "un-approved Cyrus")

    def test_the_reason_is_written_down(self):
        import inspect
        doc = inspect.getdoc(P.set_knocks_cadence) or ""
        self.assertIn("OUR COLUMN ONLY", doc)


class WeDoNotChaseAnApprovalThatCannotExist(unittest.TestCase):
    """Energy Wells and NDS have no sales anywhere, so the pending notice
    must not ask Megan to approve a room for them. It once told her that
    "carlos hidalgo (carlos) asked for their credit-check alerts in Not sure
    yet" and handed her a command that cannot do anything. Chasing approvals
    that do not exist is how the real ones get skimmed past.

    BOX USED TO BE ON THAT LIST AND IS NOT ANY MORE (2026-09-15). It had no
    SaraPlus, which at the time meant no sales at all. It now sells through
    My Service Cloud, so a Box office has sales, has hype lines and needs a
    room for them -- and leaving it excluded would have kept Ryan's and
    Carlos's answers off the pending list forever, with each of them having
    answered at install and simply never hearing back.
    """

    def test_a_box_office_is_chased_now_that_it_has_sales(self):
        self.assertTrue(P._campaign_has_alerts("carlos"))
        self.assertTrue(P._campaign_has_alerts("ryan"))

    def test_an_att_campaign_still_is(self):
        self.assertTrue(P._campaign_has_alerts("carlos-b2batt"))

    def test_an_office_we_cannot_place_is_still_chased(self):
        # Dropping it silently would be the worse failure.
        self.assertTrue(P._campaign_has_alerts("nobody-we-know"))

    def test_the_filter_is_applied(self):
        import inspect
        src = inspect.getsource(P.notify_pending)
        self.assertIn("_campaign_has_alerts", src)


class ATextFollowsTheBoardItCopies(unittest.TestCase):
    """The form never asks a cadence for a group chat -- it is the SAME board,
    "as well as" Slack, not a separate schedule -- so text destinations arrive
    with none.

    Zero is not "no cadence" in is_due(): it means the fixed 2:00/5:15/9:00
    slots. Carlos's group got exactly one text, at 14:05, because that happened
    to be just past a slot; his second campaign was approved at 14:50 and would
    have sent nothing at all until 17:15 (2026-09-15).
    """

    def test_a_text_inherits_the_boards_cadence(self):
        import inspect
        from automations.icd_alerts import knocks_post as KP
        src = inspect.getsource(KP.run)
        self.assertIn("beat", src)
        i = src.index("beat = next(")
        self.assertIn("cadence_min", src[i:i + 400])

    def test_zero_cadence_means_fixed_slots_not_every_tick(self):
        # Pin the behaviour this works around, so nobody "simplifies" it.
        import datetime as dt
        from automations.icd_alerts import knocks_post as KP
        noon = dt.datetime(2026, 9, 15, 12, 0)
        self.assertFalse(KP.is_due({"cadence_min": 0}, None, noon),
                         "zero cadence is being treated as always-due")

    def test_a_real_cadence_is_left_alone(self):
        import datetime as dt
        from automations.icd_alerts import knocks_post as KP
        noon = dt.datetime(2026, 9, 15, 12, 0)
        self.assertTrue(KP.is_due({"cadence_min": 30}, None, noon),
                        "a destination that has never posted must be due")


class ATextIsTheBoardAndNothingElse(unittest.TestCase):
    """Megan 2026-09-15: "we dont need that intro text on any texts - just the
    chart photo is fine".

    In Slack the heading earns its place -- it is what the channel preview
    shows and what dates the post. In a group text the picture arrives whole,
    with the time already printed across the top of the board, so the sentence
    above it is only something to scroll past.
    """

    def test_the_slack_heading_is_not_sent(self):
        """Asserted the LITERAL `send_to_group(group, "")` for about ten
        minutes, which was the implementation at the time and stopped being
        true the moment the gap list became the caption. The rule is that the
        Slack heading is not texted -- not that nothing is."""
        import inspect
        from automations.icd_alerts import knocks_post as KP
        src = inspect.getsource(KP.run)
        i = src.index("_text(P.text_group_of")
        # THE _text CALL ONLY. A 200-character window ran past the `else:`
        # into the Slack _upload(..., comment) beside it, so the assertion
        # failed on the line it is meant to protect.
        call = src[i:src.index("else:", i)]
        self.assertNotIn("comment", call,
                         "the Slack heading is still being texted")
        self.assertIn("_gaps_text", call)

    def test_slack_still_gets_its_comment(self):
        import inspect
        from automations.icd_alerts import knocks_post as KP
        src = inspect.getsource(KP.run)
        self.assertIn("_upload(d[\"channel_id\"], boards, comment)", src,
                      "the Slack post lost its heading too")


class TheTextCarriesTheGapList(unittest.TestCase):
    """Megan 2026-09-15, seeing Carlos's first text beside Raf's: "we're
    missing this part on these texts though".

    A board photo on a phone is a wall of small numbers. The list above it is
    the part somebody acts on, and it is the reason these go out as texts at
    all rather than sitting in Slack.
    """

    def _now(self):
        import datetime as dt
        return dt.datetime(2026, 9, 15, 16, 0)

    def test_reps_over_the_threshold_are_listed_longest_first(self):
        from automations.icd_alerts import knocks_post as KP
        rows = [{"Rep": "Short Gap", "Last Knock": "3:50 PM"},
                {"Rep": "Long Gap", "Last Knock": "2:00 PM"},
                {"Rep": "Middle Gap", "Last Knock": "3:20 PM"}]
        txt = KP._gaps_text(None, rows, self._now())
        self.assertIn("15 min of gaps", txt)
        self.assertIn("Long Gap - 120 min", txt)
        self.assertIn("Middle Gap - 40 min", txt)
        # Under the line, so absent entirely.
        self.assertNotIn("Short Gap", txt)
        self.assertLess(txt.index("Long Gap"), txt.index("Middle Gap"))

    def test_nobody_over_the_line_sends_no_text_at_all(self):
        from automations.icd_alerts import knocks_post as KP
        rows = [{"Rep": "Busy", "Last Knock": "3:55 PM"}]
        self.assertEqual(KP._gaps_text(None, rows, self._now()), "",
                         "a quiet stretch would send a header with nothing "
                         "under it")

    def test_a_missing_last_knock_is_skipped_not_guessed(self):
        from automations.icd_alerts import knocks_post as KP
        rows = [{"Rep": "No Data", "Last Knock": ""},
                {"Rep": "Real", "Last Knock": "2:00 PM"}]
        txt = KP._gaps_text(None, rows, self._now())
        self.assertNotIn("No Data", txt)
        self.assertIn("Real", txt)

    def test_a_clock_reading_ahead_is_refused(self):
        # Bad data must not produce a negative or enormous gap.
        from automations.icd_alerts import knocks_post as KP
        self.assertIsNone(KP._minutes_since("11:59 PM", self._now()))

    def test_the_board_heading_is_not_the_caption(self):
        import inspect
        from automations.icd_alerts import knocks_post as KP
        src = inspect.getsource(KP.run)
        i = src.index("_text(P.text_group_of")
        self.assertIn("_gaps_text", src[i:i + 200],
                      "the text still carries the Slack heading instead of "
                      "the gap list")


class TheGapListIsAutomaticForEveryTextOffice(unittest.TestCase):
    """Megan 2026-09-15: "when someone enrolls in the knock texts we should
    auto include those time gaps".

    It is not a setting, a column, or a question on the form. Every office
    that enrols for texts gets the gap list, because it is the half of the
    message that is actionable -- and an office that had to ask for it is an
    office that would be sent a board photo and nothing to do about it.
    """

    def test_no_per_office_flag_gates_it(self):
        import inspect
        from automations.icd_alerts import knocks_post as KP
        src = inspect.getsource(KP.run)
        i = src.index("_text(P.text_group_of")
        call = src[i:src.index("else:", i)]
        self.assertIn("_gaps_text", call)
        # No conditional between the send and the gap list.
        for gate in ("if ", "gaps_enabled", "wants_gaps", ".get(\"gaps\""):
            self.assertNotIn(gate, call,
                             "the gap list is behind a per-office condition")

    def test_a_brand_new_office_gets_it_with_no_configuration(self):
        import datetime as dt
        from automations.icd_alerts import knocks_post as KP
        # An office nobody has set anything up for.
        rows = [{"Rep": "Someone", "Last Knock": "2:00 PM"}]
        txt = KP._gaps_text(None, rows, dt.datetime(2026, 9, 15, 16, 0))
        self.assertIn("15 min of gaps", txt)
        self.assertIn("Someone - 120 min", txt)

    def test_the_form_does_not_ask_about_it(self):
        import pathlib
        form = (pathlib.Path(__file__).resolve().parents[2]
                / "icd_signup" / "app.py").read_text()
        self.assertNotIn("gap", form.lower().split("selling hours")[0],
                         "the form asks about gaps, which makes an automatic "
                         "thing look optional")


class TheClockMarksWhoJustWentQuiet(unittest.TestCase):
    """Megan 2026-09-15: "these new time gap texts don't have the clock emoji
    like Raf's do- they alert to who is new on the list".

    It passed previous=set() and first_of_day=True, and gap_text computes
    `new = not first_of_day and name not in previous` -- so the marker could
    never fire. Without it the list is undifferentiated and reads the same at
    2pm as at 6pm; the clock is what makes it "these two JUST went quiet".
    """

    def setUp(self):
        import tempfile, datetime as dt
        from automations.icd_alerts import knocks_post as KP
        self.KP, self.dt = KP, dt
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._orig, KP.OUT_DIR = KP.OUT_DIR, self.tmp
        self.now = dt.datetime(2026, 9, 15, 16, 0)
        self.office = mock.MagicMock()
        self.office.key = "carlos"

    def tearDown(self):
        self.KP.OUT_DIR = self._orig

    def _rows(self, *reps):
        # Every rep 120 minutes over, so they all qualify.
        return [{"Rep": r, "Last Knock": "2:00 PM"} for r in reps]

    def test_the_first_list_of_the_day_marks_nobody(self):
        txt = self.KP._gaps_text(self.office, self._rows("Ashley Maye"),
                                 self.now)
        self.assertIn("Ashley Maye", txt)
        self.assertNotIn("⏰", txt,
                         "the first list of the day marked everyone as newly "
                         "quiet")

    def test_a_name_that_appears_later_gets_the_clock(self):
        self.KP._gaps_text(self.office, self._rows("Ashley Maye"), self.now)
        txt = self.KP._gaps_text(
            self.office, self._rows("Ashley Maye", "Ruby Flores"), self.now)
        ruby = [l for l in txt.splitlines() if "Ruby" in l][0]
        ashley = [l for l in txt.splitlines() if "Ashley" in l][0]
        self.assertIn("⏰", ruby, "the new name has no clock")
        self.assertNotIn("⏰", ashley,
                         "a name that was already on the list is marked new")

    def test_each_office_remembers_its_own_list(self):
        other = mock.MagicMock()
        other.key = "ryan"
        self.KP._gaps_text(self.office, self._rows("Ashley Maye"), self.now)
        # Ryan has sent nothing today, so his first list marks nobody.
        txt = self.KP._gaps_text(other, self._rows("Ashley Maye"), self.now)
        self.assertNotIn("⏰", txt,
                         "one office's list silenced another's first send")

    def test_tomorrow_starts_over(self):
        self.KP._gaps_text(self.office, self._rows("Ashley Maye"), self.now)
        tomorrow = self.now + self.dt.timedelta(days=1)
        txt = self.KP._gaps_text(
            self.office, self._rows("Ashley Maye", "Ruby Flores"), tomorrow)
        self.assertNotIn("⏰", txt,
                         "yesterday's list is being used as today's baseline")
