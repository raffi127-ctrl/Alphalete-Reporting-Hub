"""Box offices sign into My Service Cloud, as AT&T offices sign into SaraPlus.

Box, Energy Wells and NDS have no SaraPlus, so until now the knocks board was
their ENTIRE product -- nothing at all on the days their reps were selling
rather than knocking. This is the other half for Box.

These pin the two things that went wrong for every campaign that is not AT&T:
the question being asked of the MACHINE rather than the campaign, and a login
that is required being treated as optional.
"""
from __future__ import annotations

import pathlib
import unittest
from unittest import mock

from automations.icd_alerts import config as C
from automations.shared import servicecloud as SC

HERE = pathlib.Path(__file__).resolve().parent
SETUP = (HERE / "dist" / "setup.py").read_text()


class WhoSignsIntoIt(unittest.TestCase):

    def _with(self, campaigns):
        rows = [{"office_key": "o%d" % i, "campaign": c}
                for i, c in enumerate(campaigns)]
        return mock.patch.object(C, "enrollments", return_value=rows)

    def test_a_box_office_does(self):
        with self._with(["b2b_box"]):
            self.assertTrue(C.uses_servicecloud())

    def test_an_att_office_does_not(self):
        for camp in ("att", "b2b_att"):
            with self._with([camp]):
                self.assertFalse(C.uses_servicecloud(),
                                 "%s would be asked for a login it has no "
                                 "account for" % camp)

    def test_nds_and_energy_are_not_guessed_in(self):
        # They have no Service Cloud account either, and asking would repeat
        # exactly the mistake that cost Carlos his SaraPlus question.
        for camp in ("nds", "energy"):
            with self._with([camp]):
                self.assertFalse(C.uses_servicecloud())

    def test_carlos_runs_both_and_needs_both(self):
        with self._with(["b2b_box", "b2b_att"]):
            self.assertTrue(C.uses_servicecloud())
            self.assertTrue(C.uses_saraplus())

    def test_it_asks_any_campaign_not_the_first(self):
        # install() returns rows[0]; a machine whose Box campaign enrolled
        # second must still be asked.
        with self._with(["b2b_att", "b2b_box"]):
            self.assertTrue(C.uses_servicecloud())


class TheInstallerAsksForIt(unittest.TestCase):

    def test_there_is_a_question(self):
        self.assertIn("def ask_for_servicecloud(", SETUP)

    def test_it_is_required(self):
        i = SETUP.index("def ask_for_servicecloud(")
        self.assertIn("required=True", SETUP[i:i + 700],
                      "the login a Box office sells through is optional")

    def test_it_asks_about_the_campaign_not_the_machine(self):
        i = SETUP.index("SERVICECLOUD_CAMPAIGNS")
        seg = SETUP[max(0, i - 400):i + 200]
        self.assertIn("this_campaign", seg,
                      "it asks the machine, which answers for whichever "
                      "campaign enrolled first")


class ALoginThatLandsOnTheResetPageIsNotALogin(unittest.TestCase):
    """SaraPlus taught this the expensive way: a session that lands on the
    password page still renders, still parses, and reports every rep at zero
    -- which reads as a quiet day rather than a broken account."""

    def test_the_reset_page_is_recognised(self):
        self.assertTrue(SC._is_password_reset(
            "https://myservicecloud.net/user/index/request-password-reset"))
        self.assertFalse(SC._is_password_reset("https://myservicecloud.net/"))

    def test_signed_in_is_false_while_a_password_box_is_on_screen(self):
        page = mock.MagicMock()
        page.url = "https://myservicecloud.net/sign-in"
        page.query_selector.return_value = object()      # password box present
        self.assertFalse(SC.signed_in(page))

    def test_signed_in_is_true_once_it_is_gone(self):
        page = mock.MagicMock()
        page.url = "https://myservicecloud.net/dashboard"
        page.query_selector.return_value = None
        self.assertTrue(SC.signed_in(page))

    def test_a_refused_login_says_what_the_office_can_do(self):
        page = mock.MagicMock()
        page.url = "https://myservicecloud.net/sign-in"
        page.query_selector.return_value = object()
        with self.assertRaises(SC.AccountProblem) as e:
            SC.sign_in(page, "someone@example.com", "x", log=lambda *_: None)
        msg = str(e.exception)
        self.assertIn("someone@example.com", msg)
        self.assertIn("installer", msg,
                      "the message does not tell the office how to fix it")


if __name__ == "__main__":
    unittest.main()


class ABoxOfficeWithoutItIsNotAllSet(unittest.TestCase):
    """The same guard SaraPlus has. Without this login a Box office gets a
    knocks board and no sales at all -- which is the state every Box office
    was in before today, and the state that looks exactly like a quiet week.
    """

    def _problems(self, files, sara, sc):
        import tempfile
        src, keep = [], False
        for line in SETUP.splitlines():
            if line.startswith("def install_problems("):
                keep = True
            elif keep and line.startswith("def ") and "install_problems" not in line:
                break
            if keep:
                src.append(line)
        tmp = pathlib.Path(tempfile.mkdtemp())
        for f in files:
            (tmp / f).write_text("{}")
        ns = {"CONFIG_DIR": tmp}
        exec("\n".join(src), ns)
        with mock.patch.object(C, "uses_saraplus", return_value=sara), \
                mock.patch.object(C, "uses_servicecloud", return_value=sc):
            return ns["install_problems"](None)

    def test_box_with_no_servicecloud_login_is_blocked(self):
        blocking, _ = self._problems(
            ["install.json", "ownerville-creds.json"], sara=False, sc=True)
        self.assertTrue(any("Service Cloud" in b for b in blocking),
                        "a Box office was told All set with no way to read "
                        "its sales")

    def test_box_with_it_is_fine(self):
        blocking, _ = self._problems(
            ["install.json", "ownerville-creds.json",
             "servicecloud-creds.json"], sara=False, sc=True)
        self.assertEqual(blocking, [])

    def test_an_att_office_is_not_asked_for_it(self):
        blocking, _ = self._problems(
            ["install.json", "saraplus-creds.json", "ownerville-creds.json"],
            sara=True, sc=False)
        self.assertEqual(blocking, [],
                         "an AT&T office is blocked on a login it has no "
                         "account for")

    def test_carlos_needs_both(self):
        blocking, _ = self._problems(
            ["install.json", "ownerville-creds.json", "saraplus-creds.json"],
            sara=True, sc=True)
        self.assertTrue(any("Service Cloud" in b for b in blocking))


class WhatTheLiveGridShowedThatTheDescriptionDidNot(unittest.TestCase):
    """Ryan listed five substatuses that mean sold. The live Contracts grid
    carries at least three he did not mention -- "Accepted by Supplier",
    "PDF Generated", "TPV Sent".

    "Accepted by Supplier" reads as MORE complete than "Submitted to
    supplier". If it is a sale and we do not count it, every Box office's
    number comes out low with nothing on the board to say why. Guessing it in
    would inflate a number people are paid on. Neither is ours to decide, so
    it is flagged and left out until somebody who sells these says.
    """

    LIVE = ["TPV Passed", "Submitted to Supplier", "PDF Generated",
            "Cancelled by Supplier", "TPV Sent", "Accepted by Supplier"]

    def test_the_ones_ruled_out_are_not_counted(self):
        for s in ("PDF Generated", "TPV Sent", "Cancelled by Supplier"):
            self.assertFalse(SC.is_completed(s),
                             "%r was counted against the decision" % s)

    def test_a_decision_is_silent_rather_than_reported_daily(self):
        # They were flagged while undecided. Reporting a settled question
        # every day is how the report that matters gets skimmed past.
        self.assertEqual(SC.unknown_statuses(self.LIVE), [],
                         "a ruled-on status is still being reported")

    def test_a_genuinely_NEW_status_is_still_loud(self):
        # Box adding one would otherwise drop those contracts out of every
        # Box office's number with nothing to say why.
        self.assertEqual(SC.unknown_statuses(self.LIVE + ["Awaiting QC"]),
                         ["Awaiting QC"])

    def test_the_five_we_were_told_still_count(self):
        for s in ("TPV Passed", "Ready for booking", "In Progress",
                  "Missing Documents", "Submitted to supplier"):
            self.assertTrue(SC.is_completed(s))

    def test_a_cancelled_contract_is_never_a_sale(self):
        self.assertFalse(SC.is_completed("Cancelled by Supplier"))

    def test_accepted_by_supplier_counts(self):
        """It was absent from the list we were first given, and it reads as
        further along than "Submitted to supplier" which we already counted.
        Asked rather than assumed -- Ryan McSpadden, 2026-09-15: "No that
        should count my bad". Left out it would have made every Box office's
        sales read low with nothing on the board to say why."""
        self.assertTrue(SC.is_completed("Accepted by Supplier"))
        self.assertNotIn("accepted by supplier", SC.KNOWN_NOT_COUNTED)

    def test_all_six_the_office_named_are_sales(self):
        for s in ("TPV Passed", "Ready for booking", "In Progress",
                  "Missing Documents", "Submitted to supplier",
                  "Accepted by Supplier"):
            self.assertTrue(SC.is_completed(s), "%r stopped counting" % s)

    def test_the_columns_a_read_needs_are_named(self):
        """I first recorded the Agent and Initiated Date columns as MISSING.
        They were behind the column chooser, not absent -- and "this office
        can only have a total, not a per-rep board" would have been a worse
        thing to build on than a blank."""
        self.assertEqual(SC.COL_AGENT, "Agent")
        self.assertEqual(SC.COL_INITIATED, "Initiated Date")
        self.assertEqual(SC.COL_SUBSTATUS, "Contract Substatus")

    def test_start_date_is_not_mistaken_for_the_sale_date(self):
        # It is when the SERVICE starts -- APR 2027, JUN 2028.
        self.assertEqual(SC.COL_NOT_THE_SALE_DATE, "Start Date")
        self.assertNotEqual(SC.COL_INITIATED, SC.COL_NOT_THE_SALE_DATE)


class AwaitingSignatureIsTheCreditCheck(unittest.TestCase):
    """Megan asked "is there a 'credit check' like presale logged step like
    Sara+ has?" and Ryan answered "Awaiting Signature would be the closest
    thing" (2026-09-15).

    On the AT&T side the credit check is the FAST alert -- it lands within
    minutes of a rep working a door, so the channel shows activity all
    afternoon rather than a handful of closes at the end. A contract awaiting
    signature is the same moment in Box's shape.
    """

    def test_it_is_a_presale(self):
        self.assertTrue(SC.is_presale("Awaiting Signature"))
        self.assertTrue(SC.is_presale("awaiting signature"))

    def test_it_is_NOT_counted_as_a_sale(self):
        # It is the step before one, exactly as a credit check is. Counting it
        # would inflate the sales number with work that has not closed.
        self.assertFalse(SC.is_completed("Awaiting Signature"))

    def test_a_sale_is_not_a_presale(self):
        for s in ("TPV Passed", "Accepted by Supplier",
                  "Submitted to supplier"):
            self.assertFalse(SC.is_presale(s),
                             "%r would be announced twice" % s)

    def test_it_is_not_flagged_as_unrecognised(self):
        self.assertEqual(SC.unknown_statuses(["Awaiting Signature"]), [])

    def test_the_three_buckets_do_not_overlap(self):
        self.assertFalse(SC.COMPLETED_STATUSES & SC.PRESALE_STATUSES)
        self.assertFalse(SC.COMPLETED_STATUSES & SC.KNOWN_NOT_COUNTED)
        self.assertFalse(SC.PRESALE_STATUSES & SC.KNOWN_NOT_COUNTED)


class VolumeIsShownNotCounted(unittest.TestCase):
    """Decided 2026-09-15: the Box board carries a count AND a volume, so
    neither office has to lose the argument -- Carlos reads the count, Ryan
    gets both.

    But "2 sales - 69,248" is ONE sale line where the second number describes
    the first. Anything that sums a rep's metrics must sum the sales and never
    the volume, or one contract reads as fifty-one thousand of something.
    """

    def test_volume_is_a_metric_but_not_a_counted_one(self):
        self.assertIn("Volume", SC.BOX_METRICS)
        self.assertNotIn("Volume", SC.BOX_COUNTED)

    def test_sales_is_what_a_total_sums(self):
        self.assertEqual(SC.BOX_COUNTED, ("Sales",))


class TheHypeDoesNotEscalateForBoxYet(unittest.TestCase):
    """sale_hype.tier() reads "Int" and "NL" by NAME. Box has neither, so
    every Box sale comes out "regular" -- a rep closing six contracts gets the
    same mild line as one closing a single contract, and the escalation that
    makes the AT&T channel worth watching would be missing.

    Pinned so that switching Box alerts on without a tier rule is a failing
    test rather than a flat channel nobody can explain.
    """

    def test_a_big_box_day_still_reads_as_regular(self):
        from automations.shared import sale_hype as H
        big = {"Sales": 6, "Volume": 142950}
        self.assertEqual(H.tier(big), "regular",
                         "if this ever stops being true, Box tiering has "
                         "been thought about and this test should say how")

    def test_an_att_day_of_the_same_size_does_escalate(self):
        from automations.shared import sale_hype as H
        self.assertEqual(H.tier({"Int": 1, "NL": 5}), "super")
        self.assertEqual(H.tier({"Int": 1, "NL": 2}), "large")


class ALostSessionIsNotAQuietDay(unittest.TestCase):
    """Megan asked whether this works like SaraPlus -- sign in once and it
    never asks again. It does not: SaraPlus has no second factor, so the agent
    signs in fresh each sweep. This has an authenticator, so the SESSION has
    to survive, and how long it survives is unknown.

    What matters is not the lifetime. It is that losing it asks loudly rather
    than reporting an office that sold nothing.
    """

    def test_a_login_form_means_the_session_is_gone(self):
        page = mock.MagicMock()
        page.url = "https://myservicecloud.net/sign-in"
        page.query_selector.return_value = object()      # password box back
        self.assertTrue(SC.session_lost(page))

    def test_the_reset_page_also_counts_as_lost(self):
        page = mock.MagicMock()
        page.url = ("https://myservicecloud.net"
                    "/user/index/request-password-reset")
        page.query_selector.return_value = None
        self.assertTrue(SC.session_lost(page),
                        "a password-reset page would be read as a signed-in "
                        "office with no sales")

    def test_a_live_session_is_not_lost(self):
        page = mock.MagicMock()
        page.url = "https://myservicecloud.net/spa/contracts"
        page.query_selector.return_value = None
        self.assertFalse(SC.session_lost(page))

    def test_the_unknown_is_written_down_rather_than_assumed(self):
        self.assertTrue(SC.SESSION_LIFETIME_UNKNOWN)


class ALostSessionAsksTheOfficeNotUs(unittest.TestCase):
    """Ryan McSpadden, asked how often the authenticator is needed: "It saves
    typically, but it feels random when it logs me out" (2026-09-15).

    So this WILL happen, unpredictably, and the office will not know: their
    sales simply stop, which looks exactly like a slow week. It is also the
    only fault in this module the owner can fix -- posting it to
    #claudecorrections would tell the people who cannot.
    """

    def setUp(self):
        import tempfile, pathlib as _p
        from automations.icd_alerts import post as P
        self.P = P
        self._orig = P.SIGNIN_WARNED_PATH
        P.SIGNIN_WARNED_PATH = _p.Path(tempfile.mkdtemp()) / "asked.json"

    def tearDown(self):
        self.P.SIGNIN_WARNED_PATH = self._orig

    def test_the_message_tells_them_what_to_do(self):
        """The authenticator line lives on the page now, where it is actually
        needed -- repeating it in the DM made the message longer without
        making the one thing it must convey, WHICH COMPUTER, any clearer."""
        said = []
        self.P.ask_office_to_sign_in("ryan", "4:12 PM", send=False,
                                     log=said.append)
        text = " ".join(said)
        self.assertIn("LucyECO", text)
        self.assertIn("signin.html", text)
        self.assertIn("Nothing is lost", text,
                      "it reads as data loss rather than a blocked view")

    def test_it_is_asked_once_a_day_not_every_sweep(self):
        first = self.P.ask_office_to_sign_in("ryan", send=False,
                                             log=lambda *_: None)
        second = self.P.ask_office_to_sign_in("ryan", send=False,
                                              log=lambda *_: None)
        self.assertFalse(second,
                         "a session stays gone until somebody walks to the "
                         "computer, so this would fire every two minutes")

    def test_another_office_is_not_silenced_by_the_first(self):
        self.P.ask_office_to_sign_in("ryan", send=False, log=lambda *_: None)
        said = []
        self.P.ask_office_to_sign_in("carlos", send=False, log=said.append)
        self.assertTrue(said)


class SignInNeededIsItsOwnKindOfFault(unittest.TestCase):

    def test_it_is_distinguishable_from_any_other_problem(self):
        from automations.icd_alerts import box_read as B
        self.assertTrue(issubclass(B.SignInNeeded, B.AccountProblem))
        # A caller must be able to tell "ask the office" from "tell us".
        self.assertIsNot(B.SignInNeeded, B.AccountProblem)

    def test_a_missing_login_also_needs_a_person(self):
        from automations.icd_alerts import box_read as B
        import inspect
        src = inspect.getsource(B.read_day)
        self.assertIn("SignInNeeded", src)


class TheFixIsDifferentForEachSystem(unittest.TestCase):
    """Megan 2026-09-15: "we should build this alert message for sara+ and OV
    as well". The DETECTION generalises; the remedy does not.

    Service Cloud has an authenticator, so a person must sign in inside
    Lucy's own browser. SaraPlus and OwnerVille have no second factor -- Lucy
    signs in fresh each sweep -- so a failure means the password changed, and
    sending them to a browser would fix nothing.
    """

    def setUp(self):
        import tempfile, pathlib as _p
        from automations.icd_alerts import post as P
        self.P = P
        self._orig = P.SIGNIN_WARNED_PATH
        P.SIGNIN_WARNED_PATH = _p.Path(tempfile.mkdtemp()) / "asked.json"

    def tearDown(self):
        self.P.SIGNIN_WARNED_PATH = self._orig

    def _msg(self, system):
        said = []
        self.P.ask_office_to_sign_in("ryan", "4:12 PM", system=system,
                                     send=False, log=said.append)
        return " ".join(said)

    def test_service_cloud_sends_them_to_sign_in(self):
        m = self._msg("servicecloud")
        self.assertIn("signin.html", m)
        self.assertNotIn("new password", m,
                         "it tells them to change a password they cannot fix")

    def test_saraplus_sends_them_to_the_installer(self):
        m = self._msg("saraplus")
        self.assertIn("new password", m)
        self.assertNotIn("signin.html", m,
                         "a browser sign-in fixes nothing for SaraPlus")

    def test_ownerville_names_the_board_not_the_sales(self):
        m = self._msg("ownerville")
        self.assertIn("knocks board", m)

    def test_every_message_names_the_machine(self):
        for system in ("servicecloud", "saraplus", "ownerville"):
            self.assertIn("office computer running LucyECO", self._msg(system),
                          "%s does not say WHERE, so they would sign in "
                          "somewhere Lucy cannot see" % system)

    def test_every_message_says_nothing_is_lost(self):
        for system in ("servicecloud", "saraplus", "ownerville"):
            self.assertIn("Nothing is lost", self._msg(system))

    def test_two_systems_failing_are_two_separate_asks(self):
        # One telling the other to stay quiet would leave half an office's
        # numbers missing with nothing said.
        first = self._msg("saraplus")
        second = self._msg("servicecloud")
        self.assertTrue(first)
        self.assertTrue(second)

    def test_the_same_system_is_asked_once_a_day(self):
        self._msg("saraplus")
        again = self.P.ask_office_to_sign_in("ryan", system="saraplus",
                                             send=False, log=lambda *_: None)
        self.assertFalse(again)
