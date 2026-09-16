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
import re
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

    def test_signed_in_is_true_on_the_apps_own_routes(self):
        page = mock.MagicMock()
        page.url = "https://myservicecloud.net/spa/contracts"
        page.query_selector.return_value = None
        self.assertTrue(SC.signed_in(page))

    def test_a_page_with_no_password_box_is_not_enough(self):
        """THIS TEST USED TO ASSERT THE OPPOSITE, and that is how Ryan got
        told he was signed in while sitting on the authenticator enrolment
        screen (2026-09-16). "No password field" describes the enrolment
        page, the reset page and an error page just as well as it describes
        the app."""
        page = mock.MagicMock()
        page.url = "https://myservicecloud.net/user/register"
        page.query_selector.return_value = None
        self.assertFalse(SC.signed_in(page))

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


class ALostSessionAsksTheOfficeNotTheTeam(unittest.TestCase):
    """Ryan McSpadden, asked how often the authenticator is needed: "It saves
    typically, but it feels random when it logs me out" (2026-09-15).

    So this WILL happen, unpredictably, and the office will not know: their
    sales simply stop, which looks exactly like a slow week.

    It DMs the owner, Megan and Eve. A signed-out session is not the sales
    floor's business, and putting it in their channel is noise in the one room
    the boards are meant to own.
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


class MissingContractDataIsASale(unittest.TestCase):
    """Ryan's list said "Missing Documents". No such status exists -- the real
    one is "Missing Contract Data", and Megan confirmed they are the same
    thing (2026-09-15).

    It reads like a sale for the same reason "Submitted to supplier" does: the
    deal is done and the paperwork is outstanding.
    """

    def test_the_real_status_counts(self):
        self.assertTrue(SC.is_completed("Missing Contract Data"))

    def test_the_name_he_used_still_counts(self):
        # Kept so it survives Box renaming it back.
        self.assertTrue(SC.is_completed("Missing Documents"))

    def test_it_is_not_also_counted_as_dead(self):
        self.assertTrue(SC.is_logged("Missing Contract Data"))

    def test_nothing_is_left_unruled(self):
        live = ["Accepted by Supplier", "Submitted to Supplier", "TPV Passed",
                "Missing Contract Data", "Awaiting Signature", "PDF Generated",
                "TPV Sent", "Cancelled by Broker", "Rejected By Supplier",
                "Residential Rejection", "TPV Failed", "Credit Failed",
                "Document Error", "Drop Finalized", "Dropped-Other"]
        unruled = [s for s in live
                   if not SC.is_completed(s) and not SC.is_presale(s)
                   and s.lower() not in SC.KNOWN_NOT_COUNTED
                   and s.lower() not in SC.NOT_LOGGED]
        self.assertEqual(unruled, [],
                         "a status nobody has ruled on is still in play")


class TheSignInToolAsksForTheLoginItself(unittest.TestCase):
    """Megan 2026-09-15: "what they run should prompt them for the login to
    the service cloud account right?"

    Yes -- and only this can. An office enrolled before Box sales existed has
    no My Service Cloud login saved, and the only thing that asked for one
    was a full re-run of setup, which needs the original enrolment code. That
    is the one thing they no longer have to hand, so sending them to find it
    turns a five-minute job into next week.
    """

    def _signin(self):
        from automations.icd_alerts import box_signin
        return box_signin

    def test_it_asks_when_nothing_is_saved_and_saves_the_answer(self):
        B = self._signin()
        saved = {}
        fake = mock.MagicMock()
        fake.text.return_value = "ryan@boxenergy.com"
        fake.password.return_value = "hunter2"
        fake.Cancelled = RuntimeError
        with mock.patch.object(B.C, "sc_creds", lambda: {}), \
             mock.patch.object(B.C, "save_sc_creds",
                               lambda e, p: saved.update(email=e, password=p)), \
             mock.patch.dict("sys.modules",
                             {"automations.icd_alerts.dialogs": fake}):
            got = B._login(log=lambda *a: None)
        self.assertEqual(saved["email"], "ryan@boxenergy.com")
        self.assertEqual(got["email"], "ryan@boxenergy.com")

    def test_an_already_saved_login_is_not_asked_for_again(self):
        B = self._signin()
        fake = mock.MagicMock()
        with mock.patch.object(B.C, "sc_creds",
                               lambda: {"email": "a@b.c", "password": "x"}), \
             mock.patch.dict("sys.modules",
                             {"automations.icd_alerts.dialogs": fake}):
            got = B._login(log=lambda *a: None)
        self.assertEqual(got["email"], "a@b.c")
        fake.text.assert_not_called()

    def test_cancelling_still_opens_the_browser(self):
        """They may not have the password on them. Refusing to open the
        window would leave them with no way to sign in at all."""
        B = self._signin()
        fake = mock.MagicMock()
        fake.Cancelled = RuntimeError
        fake.text.side_effect = RuntimeError()
        with mock.patch.object(B.C, "sc_creds", lambda: {}), \
             mock.patch.dict("sys.modules",
                             {"automations.icd_alerts.dialogs": fake}):
            got = B._login(log=lambda *a: None)
        self.assertEqual(got, {}, "no login, but no crash either")


class ABoxOfficeIsChasedForItsChannel(unittest.TestCase):
    """Megan 2026-09-15: "then they also need to just tell us what channels
    they want them posted in right?"

    They do, and they already answered at install -- ask_for_channel() runs
    for every office. What was missing was the other half: the guard that
    builds Megan's pending-approval list dropped any office with no SaraPlus,
    because when it was written such an office had no sales at all. Box has
    sales now, so their answer would have sat unapproved forever with nobody
    ever shown it.
    """

    def _has_alerts(self, campaign):
        from automations.icd_alerts import post as P
        from automations.icd_signup import store as _st
        rec = mock.MagicMock()
        rec.campaign = campaign
        with mock.patch.object(_st, "get", lambda k: rec):
            return P._campaign_has_alerts("someoffice")

    def test_a_box_office_is_on_the_list(self):
        self.assertTrue(self._has_alerts("b2b_box"),
                        "their channel request would never be shown to anyone")

    def test_an_att_office_still_is(self):
        self.assertTrue(self._has_alerts("att"))

    def test_a_campaign_with_no_sales_anywhere_still_is_not(self):
        """Chasing an approval for something that can never post is how the
        real ones get skimmed past. Energy Wells is now the only one."""
        self.assertFalse(self._has_alerts("energy"))

    def test_an_nds_office_is_chased_because_nds_is_att(self):
        self.assertTrue(self._has_alerts("nds"))


class NdsIsAttAndSellsWirelessOnly(unittest.TestCase):
    """Megan 2026-09-15: "NDS is at&t so they should get the sara+ login
    prompt right?"

    Right. NDS sat on the no-SaraPlus list because it is not the FIBER
    campaign, and "not fiber" was read as "not AT&T" -- its own Tableau
    workbook is NDS-SNRES-ATT-OOFWorkbook and its board is "ATT NDS Team".
    An NDS office enrolling was never asked for a login and could never have
    had a credit check or a sale read, with nothing reporting a fault.
    """

    def test_an_nds_office_is_asked_for_saraplus(self):
        from automations.icd_signup.schema import uses_saraplus
        self.assertTrue(uses_saraplus("nds"))

    def test_the_sweep_finds_the_nds_enrollment(self):
        """config and run.py each had their own copy of the exclusion list,
        so moving NDS in one would have left the sweep still skipping it --
        the office asked for a login, saved it, and it was never used."""
        import inspect
        from automations.icd_alerts import run as R
        src = inspect.getsource(R.cmd_once)
        self.assertIn("C.NO_SARAPLUS", src)
        self.assertNotIn('("nds", "energy", "b2b_box")', src)

    def test_energy_wells_is_still_the_one_with_no_sales(self):
        from automations.icd_alerts import config as C
        from automations.icd_signup.schema import uses_saraplus
        stranded = [c for c in ("att", "b2b_att", "nds", "b2b_box", "energy")
                    if not uses_saraplus(c) and c not in C.SERVICECLOUD_CAMPAIGNS]
        self.assertEqual(stranded, ["energy"])


class ASaraPlusLayoutChangeMustNotReadAsAQuietDay(unittest.TestCase):
    """Every SaraPlus account has the SAME layout (Megan, 2026-09-15).

    That is what makes this worth pinning. The sales columns are fixed
    indices -- internet_sales is 9, wireless lines is 14 -- so if SaraPlus
    ever moves one, it is not one office's problem: parse_att skips every
    row shorter than column 14 and returns [], and EVERY office at once
    reads as a day when nobody sold anything.

    (Written worrying NDS might have its own narrower dashboard, since
    Khalil enrols 2026-09-16 as the first NDS office. It does not -- same
    layout as anyone's. The check earns its keep on the company-wide case.)
    """

    def test_a_narrow_grid_is_a_fault_not_a_quiet_day(self):
        from automations.shared import saraplus as S
        rows = [["", S.AGENT_ROW, "A Rep", "3", "1"]]
        self.assertEqual(S.parse_att(rows), [],
                         "the silent behaviour this exists to catch")
        said = S.att_shape_problem(rows)
        self.assertTrue(said)
        self.assertIn("no sales", said, "it must name the consequence")

    def test_a_differently_marked_grid_is_also_caught(self):
        """The AT&T Internet grid already proves a grid can mark its reps
        another way -- 6_Agent, not 5_Agent.

        WITH THE HIERARCHY PRESENT, which is what makes it evidence. A lone
        marker row and nothing above it is a half-read page, not a changed
        layout, and alarming on that is what fired at Carlos four times in
        fourteen minutes on a morning he simply had not sold yet.
        """
        from automations.shared import saraplus as S
        rows = [["", "1_Company", "ACME"] + ["0"] * 15,
                ["", "4_Campaign", "Internal"] + ["0"] * 15,
                ["", "6_Agent", "A Rep"] + ["0"] * 15]
        self.assertTrue(S.att_shape_problem(rows))

    def test_a_lone_marker_row_with_no_hierarchy_is_not(self):
        from automations.shared import saraplus as S
        self.assertEqual(S.att_shape_problem([["", "6_Agent", "A Rep"]]), "")

    def test_a_normal_grid_says_nothing(self):
        from automations.shared import saraplus as S
        rows = [["", S.AGENT_ROW, "A Rep"] + ["0"] * 15]
        self.assertEqual(S.att_shape_problem(rows), "")

    def test_an_empty_grid_is_not_a_fault(self):
        """Nobody has sold yet today. Crying wolf every morning is how a real
        alert stops being read."""
        from automations.shared import saraplus as S
        self.assertEqual(S.att_shape_problem([]), "")

    def test_a_normal_nds_account_parses_like_any_other(self):
        """Same layout means Khalil needs no special handling at all -- the
        only thing NDS genuinely needs is its own hype tier, because an NDS
        rep's Int is structurally zero."""
        from automations.shared import saraplus as S
        row = ["", S.AGENT_ROW, "Khalil Mansour"] + ["0"] * 6 + ["0", "0", "0"]
        row += ["0", "0", "4"]            # wireless lines at column 14
        got = S.parse_att([row])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["wireless_lines_sold"], 4)
        self.assertEqual(got[0]["internet_sales"], 0)

    def test_the_sweep_reports_a_broken_sales_half(self):
        """It used to write one line into a log file on a laptop in another
        state. An office whose sales half never worked looked exactly like an
        office having a slow week."""
        import inspect
        from automations.icd_alerts import sara_read as SR
        src = inspect.getsource(SR.read_day)
        self.assertIn("_report_sales_fault", src)
        self.assertIn("att_shape_problem", src)
        # And it must NOT take the credit checks down with it.
        self.assertIn("credit checks", src)


class NdsTiersOnLinesBecauseThatIsAllTheySell(unittest.TestCase):
    """AT&T's thresholds, minus the part NDS structurally cannot meet.

    Both AT&T loud tiers gate on Int > 0. An NDS rep sells wireless and
    phones, so against Khalil Mansour's real 2026-09-15 grid six of his seven
    reps came out "regular" while putting up 2 to 5 lines each -- a rep's
    best day sounding exactly like their quietest, which is the flat channel
    Box had.

    The BAR is unchanged from every other office: 5 super, 2 large. Only the
    Internet requirement is dropped, and only for the campaign that cannot
    have one.
    """

    def _say(self, lines, campaign="nds"):
        from automations.shared import sale_hype as H
        return H.tier({"Int": 0, "Int Up": 0, "DTV": 0, "NL": lines}, campaign)

    def test_the_bar_is_the_same_two_and_five(self):
        self.assertEqual(self._say(5), "super")
        self.assertEqual(self._say(2), "large")
        self.assertEqual(self._say(1), "regular")

    def test_the_att_rule_is_untouched(self):
        from automations.shared import sale_hype as H
        self.assertEqual(H.tier({"Int": 1, "NL": 5}, "att"), "super")
        self.assertEqual(H.tier({"Int": 1, "NL": 2}, "att"), "large")
        self.assertEqual(H.tier({"Int": 0, "NL": 8}, "att"), "regular",
                         "an AT&T office with no Int is a data problem, not "
                         "a wireless office -- do not quietly relabel it")

    def test_khalils_real_day_is_not_flat(self):
        """His seven reps, read off his own account. Under AT&T's rule six
        were ordinary; the point of this shape is that they are not."""
        from automations.shared import sale_hype as H
        real = [(0, 0, 0, 4), (2, 0, 0, 7), (1, 0, 1, 3), (1, 0, 1, 3),
                (0, 0, 0, 5), (0, 0, 0, 4), (1, 0, 1, 2)]
        tiers = [H.tier(H.metrics_for(
            {"internet_sales": i, "internet_upgrades": u, "aia_sales": a,
             "wireless_lines_sold": nl, "dtv_streaming": 0}), "nds")
            for i, u, a, nl in real]
        self.assertEqual(tiers.count("regular"), 0)
        self.assertEqual(tiers.count("super"), 2)

    def test_a_real_agent_row_parses_at_the_hardcoded_indices(self):
        """Jevon Wiley's actual row off Khalil's account, cell for cell --
        every SaraPlus account really does have the same layout, so NDS needs
        no reader of its own."""
        from automations.shared import saraplus as S
        row = ["", S.AGENT_ROW, "Jevon Wiley", "2", "", "2", "0", "0", "0",
               "0", "0", "0", "0", "2", "4", "0", "4", "0", "0"]
        self.assertEqual(S.att_shape_problem([row]), "")
        got = S.parse_att([row])[0]
        self.assertEqual(got["name"], "Jevon Wiley")
        self.assertEqual(got["wireless_lines_sold"], 4)
        self.assertEqual(got["internet_sales"], 0)


class ASignedInMachineIsNotBlockedByAMissingPassword(unittest.TestCase):
    """Ryan McSpadden, 2026-09-16. He ran the sign-in and his machine still
    reported "No My Service Cloud login is saved on this computer, so this
    office's sales cannot be read" -- and the remedy it printed told him to
    do the thing he had just done.

    THE PASSWORD CANNOT LOG ANYONE IN. My Service Cloud has two-factor, so
    nothing ever submits it: the browser profile IS the session. The saved
    password does exactly one job, telling the office which account to sign
    in as. Gating the read on it blocked a working machine on the absence of
    a string it never needed.
    """

    def test_read_day_does_not_demand_saved_credentials(self):
        import inspect
        from automations.icd_alerts import box_read as B
        src = inspect.getsource(B.read_day)
        self.assertNotIn('cr.get("email")', src,
                         "a signed-in machine is refused over a saved string")

    def test_the_session_is_what_is_actually_checked(self):
        import inspect
        from automations.icd_alerts import box_read as B
        src = inspect.getsource(B.read_day)
        self.assertIn("session_lost", src)
        # And a lost session must still raise the alert that asks a human to
        # go and sign in -- that is the whole point of the module.
        self.assertIn("SignInNeeded", src)

    def test_nothing_else_ever_used_the_password(self):
        """If some future code signs in with it, this test should fail and be
        thought about rather than deleted.

        The BODY, not the docstring -- which talks about passwords at length
        and would have made this pass for the wrong reason.
        """
        import inspect
        from automations.icd_alerts import box_read as B
        body = inspect.getsource(B._context).split('"""')[-1]
        self.assertNotIn("password", body)
        self.assertNotIn("sc_creds", body)


class TheGridCanaryConfirmsBeforeItCriesWolf(unittest.TestCase):
    """The first thing it ever caught was Carlos's grid coming back as nine
    rows all marked History, with no Company, Location or Agent rows at all
    (2026-09-16) -- posted as "carlos's Local Office - something broke
    sales".

    That is not a layout that exists. It is a page that had not finished
    rendering, and SaraPlus is slow enough that _run_report already retries
    its own timeouts for exactly that reason. A half-rendered grid and a
    moved column look identical from here, and only one is worth waking
    somebody for.
    """

    def test_it_re_reads_before_reporting(self):
        import inspect
        from automations.icd_alerts import sara_read as SR
        src = inspect.getsource(SR.read_day)
        body = src[src.index("att_shape_problem"):]
        self.assertEqual(body.count("att_shape_problem"), 2,
                         "it must ask a second time before reporting")
        self.assertLess(body.index("reading it again"),
                        body.index("_report_sales_fault"),
                        "it reported before re-reading")

    def test_a_history_only_grid_is_a_quiet_morning_not_a_fault(self):
        """What actually fired on Carlos: nine history rows, no hierarchy
        above them, four times in fourteen minutes -- while the honest answer
        was that nobody had sold yet. An alarm that lands every quiet morning
        is one people learn to scroll past."""
        from automations.shared import saraplus as S
        rows = [["", "6_History", "an order"] + ["0"] * 15 for _ in range(9)]
        self.assertEqual(S.att_shape_problem(rows), "")

    def test_a_drawn_grid_missing_its_agent_marker_still_is_one(self):
        """The grid is a hierarchy. If the OUTER levels rendered and the
        agent level did not, the marker moved -- and every sale is read from
        agent rows."""
        from automations.shared import saraplus as S
        rows = [["", "1_Company", "ACME"] + ["0"] * 15,
                ["", "2_Location", "TX"] + ["0"] * 15,
                ["", "7_Rep", "A Rep"] + ["0"] * 15]
        said = S.att_shape_problem(rows)
        self.assertTrue(said)
        self.assertIn("5_Agent", said)

    def test_an_ordinary_grid_says_nothing(self):
        from automations.shared import saraplus as S
        rows = [["", "1_Company", "ACME"] + ["0"] * 15,
                ["", S.AGENT_ROW, "A Rep"] + ["0"] * 15]
        self.assertEqual(S.att_shape_problem(rows), "")


class AFaultNamesTheOfficeItBelongsTo(unittest.TestCase):
    """Carlos's machine runs two campaigns. _endpoint() with no key returns
    the FIRST enrollment, so his SaraPlus failure was filed against his BOX
    office and posted as "carlos's Local Office - something broke sales" --
    wrong office, wrong product, and the one person who could act on it
    reading about a campaign that has no SaraPlus at all.
    """

    def test_report_fault_accepts_an_office_key(self):
        import inspect
        from automations.icd_alerts import relay as R
        self.assertIn("office_key",
                      inspect.signature(R.report_fault).parameters)

    def test_the_saraplus_sweep_names_its_att_enrollment(self):
        import inspect
        from automations.icd_alerts import run as RUN
        src = inspect.getsource(RUN.cmd_once)
        self.assertNotIn('_report("sweep", e)\n', src,
                         "an unattributed sweep fault lands on the wrong office")
        self.assertIn("office_key=att_key", src)

    def test_the_box_sweep_names_its_own(self):
        import inspect
        from automations.icd_alerts import run as RUN
        self.assertIn("_box_key", inspect.getsource(RUN.cmd_box))


class ThePastedCommandUsesPathsThatExist(unittest.TestCase):
    """Ryan McSpadden pasted the sign-in command twice on 2026-09-16 and got
    "zsh: no such file or directory: ./venv/bin/python" both times -- on the
    one instruction we had given him to fix his own office.

    The installer puts `app` and `venv` SIDE BY SIDE under ~/.lucy-reports,
    so from inside app/ there is no ./venv. It went unnoticed because nothing
    else types this path: the LaunchAgent that runs every sweep is written
    from venv_python(), so scheduled runs were always fine and only the line
    a human pastes was broken.

    This test reads the page and the installer together so they cannot drift
    apart again.
    """

    def setUp(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        self.page = (root / "docs" / "signin.html").read_text()
        self.startup = (root / "docs" / "startup.html").read_text()
        self.setup = (root / "automations" / "icd_alerts" / "dist"
                      / "setup.py").read_text()

    def test_app_and_venv_really_are_siblings(self):
        """If the installer ever nests them, this test should fail and the
        page should be changed WITH it."""
        self.assertIn('APP_DIR = BASE / "app"', self.setup)
        self.assertIn('VENV_DIR = BASE / "venv"', self.setup)
        self.assertIn('BASE = HOME / ".lucy-reports"', self.setup)

    def _code(self):
        """The page's JS with // comments stripped -- the comments EXPLAIN
        the old broken path, and matching those instead of the real command
        is how this test passes while the page is still wrong."""
        out = []
        for line in self.page.splitlines():
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            out.append(line)
        return "\n".join(out)

    def test_the_page_does_not_look_for_a_venv_inside_app(self):
        self.assertNotIn("./venv/bin/python", self._code())

    def test_the_page_points_at_the_installers_actual_venv(self):
        self.assertIn("~/.lucy-reports/venv/bin/python", self._code())

    def test_the_startup_page_uses_the_same_real_paths(self):
        """A second page typing the same paths is a second chance to type
        them wrong."""
        code = "\n".join(l for l in self.startup.splitlines()
                         if not l.strip().startswith("//"))
        self.assertNotIn("./venv/bin/python", code)
        self.assertIn("~/.lucy-reports/venv/bin/python", code)
        self.assertIn("~/.config/lucy-reports/last-selfupdate.txt", code)
        self.assertIn("automations.icd_alerts.boot_schedule", code)

    def test_the_config_directory_is_the_installers_one(self):
        # The stamp deletion has to hit the real file or the update is not
        # forced and the whole command is pointless.
        self.assertIn('CONFIG_DIR = HOME / ".config" / "lucy-reports"',
                      self.setup)
        self.assertIn("~/.config/lucy-reports/last-selfupdate.txt", self.page)


class BeingPastTheLoginFormIsNotBeingSignedIn(unittest.TestCase):
    """Ryan McSpadden, 2026-09-16, 10:50. He signed in, My Service Cloud
    showed him its AUTHENTICATOR ENROLMENT screen -- a QR code, a manual key
    and a box for six digits -- and the tool told him "Signed in. Lucy can
    see your sales again."

    He stopped there, reasonably. The sweep went on reporting his account
    signed out, correctly, forty-seven times.

    The check was `page.query_selector(password) is None` -- an ABSENCE. The
    enrolment page has no password field either. A false success is worse
    than a false failure here: it ends with the office believing they are
    done and nobody looking again.
    """

    class _Page:
        def __init__(self, url, pw=None, text=""):
            self.url, self._pw, self._t = url, pw, text

        def query_selector(self, _sel):
            return self._pw

        def inner_text(self, _sel):
            return self._t

    def test_the_mfa_page_is_not_signed_in(self):
        from automations.shared import servicecloud as SC
        page = self._Page("https://myservicecloud.net/user/register",
                          text="Register My Service Cloud — Google "
                               "Authenticator — enter a code")
        self.assertFalse(SC.signed_in(page), "this is the exact false 'done'")

    def test_the_mfa_page_is_named_so_the_message_can_help(self):
        from automations.shared import servicecloud as SC
        page = self._Page("https://myservicecloud.net/user/register",
                          text="Register My Service Cloud / google authenticator")
        self.assertTrue(SC.on_mfa_setup(page))

    def test_the_app_itself_is_signed_in(self):
        from automations.shared import servicecloud as SC
        self.assertTrue(SC.signed_in(
            self._Page("https://myservicecloud.net/spa/contracts")))

    def test_the_login_form_and_reset_page_are_not(self):
        from automations.shared import servicecloud as SC
        self.assertFalse(SC.signed_in(
            self._Page("https://myservicecloud.net/sign-in", pw=object())))
        self.assertFalse(SC.signed_in(
            self._Page("https://myservicecloud.net"
                       "/user/index/request-password-reset")))

    def test_signin_confirms_against_the_contracts_page(self):
        """Being past the login form is not the same as being able to read
        contracts, and contracts are the only thing this exists for.

        Read off the MODULE, not one function: the window moved into a helper
        when the sign-in lock was added, and a test pinned to run() went green
        while checking nothing.
        """
        import inspect
        from automations.icd_alerts import box_signin as B
        src = inspect.getsource(B)
        self.assertIn("CONTRACTS_PATH", src)
        self.assertIn("on_mfa_setup", src)


class TheMachineComesBackWithoutAnybodyTouchingIt(unittest.TestCase):
    """Kash's iMac restarted overnight on 2026-09-16, came back to the login
    screen, and sat there powered on running nothing until noon. No error,
    because there is nothing to error: a LaunchAgent lives in the user's own
    folder and only starts once somebody logs in.

    Megan: "we need to make it where they don't need to keep doing something
    for this to work."

    A LaunchDaemon loads at BOOT and its UserName key runs it as the office's
    own account -- so no auto-login, no macOS password written to
    /etc/kcpassword where it can be read back, and FileVault can stay on.
    """

    def setUp(self):
        from pathlib import Path
        from automations.icd_alerts import boot_schedule
        self.B = boot_schedule
        root = Path(__file__).resolve().parents[2]
        self.setup_src = (root / "automations" / "icd_alerts" / "dist"
                          / "setup.py").read_text()

    def test_the_boot_job_runs_as_the_office_user_not_root(self):
        """Running as root would put every path -- install.json, both browser
        profiles, the logs -- under /var/root, and the daemon would behave
        like a machine that had never been set up."""
        import getpass
        text = self.B.plist_text(120)
        self.assertIn("<key>UserName</key>", text)
        self.assertIn("<string>%s</string>" % getpass.getuser(), text)

    def test_it_sets_home_explicitly(self):
        """launchd does not reliably hand a UserName job the user's HOME."""
        from pathlib import Path
        text = self.B.plist_text(120)
        self.assertIn("<key>HOME</key>", text)
        self.assertIn("<string>%s</string>" % Path.home(), text)

    def test_it_keeps_the_cadence_the_machine_already_had(self):
        """Offices do not all sweep at the same interval -- Cyrus is slower
        on purpose -- and a migration that silently reset everyone would
        change how often two offices post without anybody asking."""
        self.assertIn("<key>StartInterval</key><integer>900</integer>",
                      self.B.plist_text(900))

    def test_the_interpreter_is_not_a_hand_written_path(self):
        """"./venv/bin/python" is what stopped Ryan twice on 2026-09-16."""
        import sys
        self.assertIn("<string>%s</string>" % sys.executable,
                      self.B.plist_text(120))

    def test_loaded_is_asked_of_launchctl_not_assumed(self):
        """A plist copied into /Library/LaunchDaemons that launchd never
        accepted is the worst outcome: the machine reports success, the
        per-login job is removed, and the office is quieter than before."""
        import inspect
        self.assertIn("launchctl", inspect.getsource(self.B.loaded))
        self.assertIn("print", inspect.getsource(self.B.loaded))

    def test_install_returns_what_launchd_actually_did(self):
        import inspect
        src = inspect.getsource(self.B.install)
        self.assertTrue(src.rstrip().endswith("return loaded()"),
                        "install must report the verified state, not the "
                        "exit code of an osascript the user may have "
                        "cancelled")

    def test_the_login_job_is_installed_first(self):
        """It needs no password and cannot be declined, so the machine has a
        working schedule before anything a person can say no to."""
        step = self.setup_src[self.setup_src.index("step(9, total,"):]
        self.assertLess(step.index("schedule_mac()"),
                        step.index("boot_schedule.install("))

    def test_the_login_job_is_only_dropped_after_the_daemon_is_verified(self):
        """Removing it and then failing to install the daemon would leave the
        office with no schedule at all."""
        step = self.setup_src[self.setup_src.index("step(9, total,"):]
        self.assertLess(step.index("boot_schedule.install("),
                        step.index("unload_login_agent()"))

    def test_the_installer_does_not_keep_its_own_copy(self):
        """Two definitions is how the installer and the agent end up
        disagreeing about a plist nobody can see."""
        self.assertNotIn("<key>UserName</key>", self.setup_src)

    def test_it_ships_to_the_machines(self):
        """setup.py does NOT ship. Without this in the bundle an enrolled
        office would need a full re-install, which needs the enrolment code
        they no longer have -- the Service Cloud trap again."""
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        listing = (root / "automations" / "icd_alerts"
                   / "agent_files.txt").read_text()
        self.assertIn("automations/icd_alerts/boot_schedule.py", listing)


class OneLinkThatDoesWhateverIsMissing(unittest.TestCase):
    """Megan 2026-09-16: "I can't keep going back to all the owners and
    having them run a million things."

    CODE reaches the machines by itself -- selfupdate pulls it daily and
    nobody is asked anything. Anything the INSTALLER does cannot, because
    setup.py is not shipped and half of it needs an administrator password or
    somebody holding an authenticator. So each such change had meant a new
    page, a new paste, and another round of messages.

    finish_setup is the one link. A new requirement becomes a step inside it,
    carried to every machine by the next daily update, and the link never
    changes.
    """

    def setUp(self):
        from automations.icd_alerts import finish_setup
        self.F = finish_setup

    def test_it_is_safe_to_run_when_nothing_is_missing(self):
        """It is sent to people who may already have run it -- that is the
        point of having one link. Every step must skip itself."""
        said = []
        with mock.patch.object(self.F, "_update", lambda log: "up to date"), \
             mock.patch.object(self.F, "_boot_job", lambda log: "already done"), \
             mock.patch.object(self.F, "_saraplus", lambda log: "already working"), \
             mock.patch.object(self.F, "_service_cloud",
                               lambda log: "not needed for this office"):
            rc = self.F.run(log=said.append)
        self.assertEqual(rc, 0)
        self.assertTrue(any("All set" in s for s in said))

    def test_one_failing_step_does_not_cost_the_others(self):
        """A machine needing two things fixed that gets one would look
        fixed, and the second would be found the slow way."""
        reached = []

        def boom(log):
            raise RuntimeError("nope")

        with mock.patch.object(self.F, "_update", lambda log: "up to date"), \
             mock.patch.object(self.F, "_boot_job", boom), \
             mock.patch.object(self.F, "_saraplus", lambda log: "already working"), \
             mock.patch.object(self.F, "_service_cloud",
                               lambda log: reached.append(1) or "done"):
            rc = self.F.run(log=lambda *_a: None)
        self.assertEqual(reached, [1], "it stopped at the failure")
        self.assertEqual(rc, 1, "an unfinished machine must not report success")

    def test_it_says_so_when_something_still_needs_doing(self):
        said = []
        with mock.patch.object(self.F, "_update", lambda log: "up to date"), \
             mock.patch.object(self.F, "_boot_job", lambda log: "skipped"), \
             mock.patch.object(self.F, "_saraplus", lambda log: "already working"), \
             mock.patch.object(self.F, "_service_cloud", lambda log: "done"):
            rc = self.F.run(log=said.append)
        self.assertEqual(rc, 1)
        self.assertFalse(any("All set" in s for s in said))

    def test_the_update_runs_before_anything_decides_what_is_missing(self):
        """The steps are only as current as the files on the machine."""
        import inspect
        src = inspect.getsource(self.F.run)
        self.assertLess(src.index("_update"), src.index("_boot_job"))

    def test_service_cloud_is_skipped_for_offices_that_do_not_use_it(self):
        from automations.icd_alerts import config as C
        with mock.patch.object(C, "uses_servicecloud", lambda: False):
            self.assertIn("not needed", self.F._service_cloud(lambda *_a: None))

    def test_it_ships(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        listing = (root / "automations" / "icd_alerts"
                   / "agent_files.txt").read_text()
        self.assertIn("automations/icd_alerts/finish_setup.py", listing)


class AFixReachesTheOfficesWhenWePublishIt(unittest.TestCase):
    """Megan 2026-09-16: "we need it where we can push the updates we make to
    their machines."

    Code already reached them on its own, but once a day -- so this morning's
    correction to the sign-in command sat in main while Ryan pasted the
    broken one twice.

    The agent now reads ONE small file each sweep and pulls nothing unless
    its release number moved. That keeps main free for work in progress: a
    commit reaches nobody until the number is raised deliberately.
    """

    def setUp(self):
        import datetime
        from automations.icd_alerts import selfupdate
        self.S = selfupdate
        self.DAY = datetime.date(2026, 9, 16)

    def test_a_new_release_is_due_immediately_not_tomorrow(self):
        with mock.patch.object(self.S, "published_release", lambda: "9.9.9"), \
             mock.patch.object(self.S, "applied_release", lambda: "9.9.8"):
            self.assertTrue(self.S.due(self.DAY))

    def test_an_unchanged_release_does_not_pull(self):
        """Otherwise every office re-downloads the bundle every two minutes
        for a tree that changes a few times a week."""
        stamp = mock.MagicMock()
        stamp.read_text.return_value = "2026-09-16"
        with mock.patch.object(self.S, "published_release", lambda: "9.9.9"), \
             mock.patch.object(self.S, "applied_release", lambda: "9.9.9"), \
             mock.patch.object(self.S, "STAMP", stamp):
            self.assertFalse(self.S.due(self.DAY))

    def test_being_unable_to_ask_falls_back_to_the_daily_rule(self):
        """A flaky connection must not either update on nothing or decide the
        machine is current -- both end with a fleet that quietly stops
        tracking main."""
        stamp = mock.MagicMock()
        stamp.read_text.return_value = "2026-09-15"      # yesterday
        with mock.patch.object(self.S, "published_release", lambda: None), \
             mock.patch.object(self.S, "STAMP", stamp):
            self.assertTrue(self.S.due(self.DAY))
        stamp.read_text.return_value = "2026-09-16"      # already done today
        with mock.patch.object(self.S, "published_release", lambda: None), \
             mock.patch.object(self.S, "STAMP", stamp):
            self.assertFalse(self.S.due(self.DAY))

    def test_an_error_page_is_not_a_version(self):
        with mock.patch.object(self.S, "_fetch",
                               lambda *_a: b"<html>404 not found</html>\n<b>x"):
            self.assertIsNone(self.S.published_release())

    def test_a_bad_push_is_not_retried_every_two_minutes(self):
        """A rollback records the release too. Otherwise a machine nobody can
        reach would loop on download, failed import and rollback all day."""
        import inspect
        src = inspect.getsource(self.S.run)
        self.assertNotIn("_stamp(today)\n", src,
                         "an exit path forgets the release and will re-pull")
        self.assertIn("_stamp(today, release)", src)

    def test_the_release_is_read_once_before_the_files_land(self):
        """Asking again afterwards could record a release we did not install
        -- and the machine would then believe it was current."""
        import inspect
        src = inspect.getsource(self.S.run)
        self.assertLess(src.index("release = published_release()"),
                        src.index("_stamp(today, release)"))

    def test_the_published_file_exists_and_is_a_short_token(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        text = (root / "automations" / "icd_alerts"
                / "agent_release.txt").read_text().strip()
        self.assertTrue(text)
        self.assertLessEqual(len(text), 40)
        self.assertNotIn("\n", text)


class ThePasswordBoxSaysWhoIsAsking(unittest.TestCase):
    """Kash's office, 2026-09-16: "It's asking for osascript password. Idk
    what that is."

    Without `with prompt`, macOS labels the dialog with the name of the tool
    that raised it -- osascript -- which nobody outside this trade has heard
    of. Being asked for your password by something you do not recognise is a
    thing people are RIGHT to refuse, and our explanation was in the Terminal
    window BEHIND the dialog, where it does no good.
    """

    def _prompts(self):
        from automations.icd_alerts import boot_schedule, stay_awake
        return {"boot": boot_schedule.PROMPT, "sleep": stay_awake.PROMPT}

    def test_both_dialogs_name_us_rather_than_osascript(self):
        for where, text in self._prompts().items():
            self.assertIn("Lucy Reports", text, where)

    def test_both_say_which_password(self):
        """"Your password" is ambiguous on a Mac -- there is the login one,
        the Apple ID, and whatever they use for SaraPlus."""
        for where, text in self._prompts().items():
            self.assertIn("log in to this computer", text, where)

    def test_both_say_what_it_is_for(self):
        """A reason is what turns "some program wants my password" into a
        decision somebody can actually make."""
        self.assertIn("after this Mac restarts", self._prompts()["boot"])
        self.assertIn("going to sleep", self._prompts()["sleep"])

    def test_the_prompt_actually_reaches_the_dialog(self):
        import inspect
        from automations.icd_alerts import boot_schedule, stay_awake
        for fn in (boot_schedule.install, stay_awake.apply_pmset):
            src = inspect.getsource(fn)
            self.assertIn("with prompt", src, fn.__name__)
            self.assertIn("PROMPT", src, fn.__name__)


class EnrollCannotSilentlyMakeAnOfficeAttAnyMore(unittest.TestCase):
    """enroll.py was written when every office was AT&T fiber and defaulted to
    it with no way to say otherwise. Running it for the first NDS office
    (Khalil, 2026-09-16) would have pinned OwnerVille to campaign id 3 instead
    of 1, read the wrong grid for their knocks board, and handed them the AT&T
    hype tier -- on which an NDS rep's Int is structurally zero, so EVERY sale
    they ever make reads "regular".

    None of those three raise. They are silent wrongnesses on a machine nobody
    can reach.
    """

    def setUp(self):
        from automations.icd_alerts import enroll
        self.E = enroll

    def test_the_row_it_writes_carries_the_campaign(self):
        row = self.E.entry_text(
            "khalil", "Khalil Mansour", "Khalil's Local Office",
            "America/Chicago", "U045F9JCPJT", ("13:30", "20:30"),
            ("10:45", "17:00"), True, "mac", False, "nds")
        self.assertIn('campaign="nds"', row)

    def test_att_is_written_out_rather_than_left_to_the_default(self):
        """So the next person reading the file does not have to know what the
        default is to know what the office sells."""
        row = self.E.entry_text(
            "someone", "Some One", "Some One's Local Office",
            "America/Chicago", "", ("13:30", "20:30"), ("10:45", "17:00"),
            True)
        self.assertIn('campaign="att"', row)

    def test_the_row_it_writes_is_valid_python(self):
        """It is spliced into offices.py, and a roster that will not import
        takes down every office rather than one."""
        import ast
        row = self.E.entry_text(
            "khalil", "Khalil Mansour", "Khalil's Local Office",
            "America/Chicago", "U045F9JCPJT", ("13:30", "20:30"),
            ("10:45", "17:00"), True, "mac", False, "nds")
        ast.parse("D = {\n%s}\n" % row)

    def test_an_unknown_campaign_stops_the_enrolment(self):
        """A typo must not become a default. Checked against the sign-up
        form's own list so the two cannot drift."""
        with self.assertRaises(SystemExit) as e:
            self.E.enroll("Nobody Real", campaign="ndss", do_push=False,
                          log=lambda *_a: None)
        self.assertIn("do not know the campaign", str(e.exception))

    def test_every_campaign_the_form_offers_is_accepted(self):
        from automations.icd_signup.schema import CAMPAIGNS
        for key, _label, _sara in CAMPAIGNS:
            row = self.E.entry_text(
                "x", "X Y", "X's Local Office", "America/Chicago", "",
                ("13:30", "20:30"), ("10:45", "17:00"), True, "mac", False,
                key)
            self.assertIn('campaign="%s"' % key, row)


class TheAuthIsBorrowedWhereTheBrowserActuallySendsIt(unittest.TestCase):
    """Ryan's machine, 2026-09-16 13:54 -- minutes after his sign-in finally
    worked: "Page.evaluate: TypeError: Failed to fetch".

    The old code monkey-patched window.fetch from inside the page to borrow
    the app's Authorization header. patchright runs page.evaluate in an
    ISOLATED WORLD, so the patch landed on a different `window` than the
    app's: the real request went past unseen, the header was never captured,
    and the forged cross-origin POST went out unauthorised and died at the
    network layer.

    It looked right when written because it was tried in a browser console --
    which IS the main world. That difference does not show up until the code
    is on somebody else's computer.
    """

    class _Req:
        def __init__(self, url, method="POST", headers=None):
            self.url, self.method = url, method
            self.headers = headers or {}

    def _borrowed(self):
        from automations.icd_alerts import box_read as B
        return B._Borrowed()

    def test_it_takes_the_headers_off_the_real_request(self):
        b = self._borrowed()
        b._seen(self._Req("https://api.myservicecloud.net/gql/secured/v2",
                          headers={"Authorization": "Bearer abc",
                                   "Content-Type": "application/json"}))
        self.assertEqual(b.headers.get("authorization"), "Bearer abc")
        self.assertTrue(b.ready())

    def test_hop_by_hop_headers_are_dropped(self):
        """Replaying a captured content-length against a different body is a
        request the server is right to reject."""
        b = self._borrowed()
        b._seen(self._Req("https://api.myservicecloud.net/gql",
                          headers={"Authorization": "x", "Content-Length": "99",
                                   "Host": "api.myservicecloud.net"}))
        self.assertNotIn("content-length", b.headers)
        self.assertNotIn("host", b.headers)

    def test_unrelated_requests_are_ignored(self):
        b = self._borrowed()
        b._seen(self._Req("https://myservicecloud.net/spa/contracts",
                          method="GET", headers={"Authorization": "nope"}))
        self.assertFalse(b.ready())

    def test_content_type_alone_is_not_ready(self):
        """That is what we would have invented ourselves -- it proves nothing
        was borrowed, which is the state the old sniffer was silently in."""
        b = self._borrowed()
        b._seen(self._Req("https://api.myservicecloud.net/gql",
                          headers={"Content-Type": "application/json"}))
        self.assertFalse(b.ready())

    def test_a_listener_that_throws_never_breaks_the_read(self):
        b = self._borrowed()
        b._seen(object())          # nothing like a request at all
        self.assertEqual(b.headers, {})

    def test_the_in_page_fetch_is_gone(self):
        from automations.icd_alerts import box_read as B
        self.assertFalse(hasattr(B, "_FETCH_JS"),
                         "a fetch from inside the page is cross-origin, "
                         "unauthorised, and in the wrong world")
        self.assertFalse(hasattr(B, "_SNIFF_JS"))

    def test_the_query_still_asks_for_term(self):
        """Carlos's tiers are read off it; losing it in the rewrite would
        quietly flatten every Box sale line."""
        from automations.icd_alerts import box_read as B
        self.assertIn("term", B.GRAPHQL_QUERY)
        self.assertIn("adjusted_annual_volume", B.GRAPHQL_QUERY)
        self.assertIn("contract_substatus", B.GRAPHQL_QUERY)


class BoxDoesNotAnnounceTheStepBeforeASale(unittest.TestCase):
    """Ryan McSpadden, 2026-09-16, after seeing his first day of real Box
    data: "Can we hold off on the before sale posts? Box has a glitch where
    it makes us generate multiple contracts so the posts would be way off."

    So the pre-sale count counts nothing real on Box -- one deal can leave
    several draft contracts behind it. An alert whose number is wrong is
    worse than no alert, because it costs the ones that are right their
    credibility.
    """

    def test_box_suppresses_the_presale_ping(self):
        from automations.shared import sale_hype as H
        self.assertFalse(H.shape("b2b_box").presale_ping)

    def test_att_and_nds_still_have_theirs(self):
        """A credit check is one customer and one event -- it is the fast
        ping those offices actually watch."""
        from automations.shared import sale_hype as H
        self.assertTrue(H.shape("att").presale_ping)
        self.assertTrue(H.shape("nds").presale_ping)

    def test_the_poster_honours_it(self):
        import inspect
        from automations.icd_alerts import post as P
        src = inspect.getsource(P.run)
        self.assertIn("presale_ping", src)

    def test_the_state_is_still_recorded_while_it_is_off(self):
        """`merged` must reach the sheet either way, or turning it back on
        would replay the whole day as though it had just happened."""
        import inspect
        from automations.icd_alerts import post as P
        src = inspect.getsource(P.run)
        cut = src[src.index("presale_ping"):]
        self.assertNotIn("merged = {}", cut[:200],
                         "clearing the state is what causes a replay")

    def test_the_sale_line_speaks_box_not_board(self):
        """'just have it say "Omar just finished a contract!"' -- Box sells
        contracts; "on the board" is AT&T's word."""
        from automations.shared import sale_hype as H
        import datetime as _dt
        seen = set()
        for n in range(1, 40):
            seen.add(H.hype("Omar Sanchez",
                            {"Sales": 1, "Volume": 900, "Big": 0, "Huge": 0},
                            _dt.date(2026, 9, n % 28 + 1), "b2b_box"))
        joined = " ".join(seen).lower()
        self.assertIn("contract", joined)
        self.assertNotIn("on the board", joined)

    def test_att_wording_is_untouched(self):
        from automations.shared import sale_hype as H
        import datetime as _dt
        seen = " ".join(
            H.hype("Max Allen", {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 0},
                   _dt.date(2026, 9, n % 28 + 1), "att") for n in range(1, 40))
        self.assertIn("board", seen.lower())

    def test_the_loud_tiers_still_fire_for_box(self):
        """Carlos's escalation is a separate ask from Ryan's wording one, and
        rewording must not quietly drop it.

        THE TIER, NOT THE WORDS. This used to assert the literal "TELL US",
        which broke the moment that tier gained a second wording -- pinning
        the copy is how a test blocks the next copy change (2026-09-16).
        """
        from automations.shared import sale_hype as H
        import datetime as _dt
        big = {"Sales": 2, "Volume": 138240, "Big": 2, "Huge": 2}
        small = {"Sales": 1, "Volume": 900, "Big": 0, "Huge": 0}
        self.assertEqual(H.tier(big, "b2b_box"), "super")
        loud = H.hype("Omar Sanchez", big, _dt.date(2026, 9, 16), "b2b_box")
        quiet = H.hype("Omar Sanchez", small, _dt.date(2026, 9, 16), "b2b_box")
        self.assertNotEqual(loud, quiet)
        self.assertIn("OMAR", loud, "the top tier shouts the name")


class BoxSaleCountsAreNotDeduplicated(unittest.TestCase):
    """Box's duplicate-contract glitch was the reason the pre-sale ping went
    off. The natural next worry is whether duplicates also reach the SOLD
    statuses and double a rep's count.

    Asked rather than assumed -- Ryan McSpadden, 2026-09-16: "No only one
    will go TPV passed thankfully". So the counts stand, and nothing should
    start collapsing them: two contracts in a day for one rep are two sales,
    and de-duplicating on a resemblance would cost somebody a real one.
    """

    DAY = __import__("datetime").date(2026, 9, 15)

    def _row(self, agent, status, volume):
        from automations.shared import servicecloud as _SC
        return {_SC.COL_AGENT: agent, _SC.COL_SUBSTATUS: status,
                _SC.COL_INITIATED: "09/15/2026 06:13 PM",
                "Adjusted Annual Volume": volume, _SC.COL_TERM: 36,
                _SC.COL_BUSINESS: "Somewhere LLC"}

    def test_two_sold_contracts_for_one_rep_count_twice(self):
        from automations.icd_alerts import box_read as B
        rows = [self._row("Tiffany Palmer", "TPV Passed", "69,120"),
                self._row("Tiffany Palmer", "Accepted by Supplier", "69,120")]
        got = B.tally(rows, self.DAY)["sales"]["Tiffany Palmer"]
        self.assertEqual(got["Sales"], 2)
        self.assertEqual(got["Volume"], 138240)

    def test_identical_looking_contracts_are_still_two(self):
        """Same rep, same volume, same status, same day -- which is exactly
        what a de-duplicating reader would throw away."""
        from automations.icd_alerts import box_read as B
        rows = [self._row("Omar Sanchez", "TPV Passed", "20,000"),
                self._row("Omar Sanchez", "TPV Passed", "20,000")]
        got = B.tally(rows, self.DAY)["sales"]["Omar Sanchez"]
        self.assertEqual(got["Sales"], 2)


class TheSweepYieldsWhileSomebodyIsSigningIn(unittest.TestCase):
    """Chromium will not open one profile twice, and the sweep opens the SAME
    Service Cloud profile every two minutes. So a sign-in window sitting open
    while its owner finds their phone and types six digits is racing a
    background job for that directory -- and whichever loses, the office is
    told nothing useful.

    Carlos ran the link on 2026-09-16 and his session still came back signed
    out. Ryan took three goes.
    """

    def setUp(self):
        import tempfile, pathlib
        from automations.icd_alerts import config as C
        self.lock = pathlib.Path(tempfile.mkdtemp()) / "sc-signin.lock"
        self.p = mock.patch.object(C, "SC_SIGNIN_LOCK", self.lock)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_no_lock_means_carry_on(self):
        from automations.icd_alerts import box_read as B
        self.assertFalse(B.signin_in_progress())

    def test_a_fresh_lock_holds_the_sweep_off(self):
        import datetime as _dt
        from automations.icd_alerts import box_read as B
        self.lock.write_text(_dt.datetime.now().isoformat())
        self.assertTrue(B.signin_in_progress())

    def test_a_stale_lock_is_ignored(self):
        """A crashed sign-in must not mute an office's sales for the rest of
        the afternoon. The failure mode of a forgotten lock has to be noise,
        never silence."""
        import datetime as _dt
        from automations.icd_alerts import box_read as B
        self.lock.write_text(
            (_dt.datetime.now() - _dt.timedelta(hours=3)).isoformat())
        self.assertFalse(B.signin_in_progress())

    def test_a_corrupt_lock_is_ignored(self):
        from automations.icd_alerts import box_read as B
        self.lock.write_text("not a date at all")
        self.assertFalse(B.signin_in_progress())

    def test_yielding_is_not_a_fault(self):
        """Reporting it would alert on the exact minute the office is doing
        what we asked them to."""
        from automations.icd_alerts import box_read as B
        self.assertFalse(issubclass(B.SignInInProgress, B.AccountProblem))

    def test_the_sweep_returns_clean_rather_than_reporting(self):
        import inspect
        from automations.icd_alerts import run as RUN
        src = inspect.getsource(RUN.cmd_box)
        cut = src[src.index("SignInInProgress"):]
        self.assertLess(cut.index("return 0"), cut.index("_report"),
                        "a sign-in in progress must not file a fault")

    def test_the_sign_in_always_releases_it(self):
        """Held through a crash, it would silence the office it was meant to
        help."""
        import inspect
        from automations.icd_alerts import box_signin as B
        src = inspect.getsource(B.run)
        self.assertIn("finally", src)
        self.assertIn("unlink", src)


class NotTriedIsNotTheSameAsFailed(unittest.TestCase):
    """Khalil Mansour's install, 2026-09-16. His SaraPlus password had
    genuinely expired, so the installer never got as far as testing
    OwnerVille -- and recorded that as a FAILURE.

    The closing dialog told him "the OwnerVille login did not work, so the
    knocks board will not post yet" while his knocks were relaying: 13 reps,
    read and sent, four minutes later.

    Claiming a failure that did not happen sends somebody to fix a working
    thing, and it costs every other message in that dialog its weight.
    """

    def setUp(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        self.src = (root / "automations" / "icd_alerts" / "dist"
                    / "setup.py").read_text()

    def test_untested_ownerville_is_none_not_false(self):
        self.assertIn("ov_ok = ownerville_until_it_works() if ok else None",
                      self.src)

    def test_the_warning_only_fires_on_a_real_failure(self):
        """`not ov_ok` is true for None as well, which is exactly the bug."""
        self.assertNotIn("if not ov_ok and", self.src)
        self.assertIn("if ov_ok is False and", self.src)

    def test_the_upstream_fault_is_gated_the_same_way(self):
        """A fault filed for an untested login is a ticket about nothing."""
        self.assertIn("elif ov_ok is False and", self.src)
        self.assertNotIn("elif not ov_ok and", self.src)


class TheTextApprovalCanActuallyBeRun(unittest.TestCase):
    """cmd_texts existed with no way to run it. Khalil asked to be texted on
    the sign-up form on 2026-09-16, his request sat in his record as
    ('Reporting', 15), and no flag would approve it -- so the one thing he
    was waiting for could not be done at all.

    Written, tested, shipped, unreachable: the same shape as
    ask_office_to_sign_in and the laptop detectors before them.
    """

    def setUp(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        self.src = (root / "automations" / "icd_alerts"
                    / "approve.py").read_text()

    def test_there_is_a_texts_flag(self):
        self.assertIn('"--texts"', self.src)

    def test_the_flag_reaches_cmd_texts(self):
        """A flag that parses and routes nowhere is the same bug wearing a
        command-line argument."""
        self.assertIn("cmd_texts(args.office)", self.src)

    def test_every_approval_path_is_reachable(self):
        """If a fourth kind of destination is added, it belongs here too."""
        import inspect
        from automations.icd_alerts import approve as A
        main_src = inspect.getsource(A.main)
        for fn in ("cmd_texts", "cmd_knocks", "cmd_approve"):
            self.assertIn(fn + "(", main_src, fn + " cannot be run")


class TheBootJobRunsTheVenvPython(unittest.TestCase):
    """Khalil Mansour was the first office to install with a boot job, on
    2026-09-16. Twelve sweeps died on `ModuleNotFoundError: No module named
    'patchright'` before anybody looked.

    install.sh finds whatever system Python the Mac has and runs setup.py
    under it -- so during an install `sys.executable` is NOT the venv, it is
    a Python with none of this agent's packages. The boot job launched the
    agent with that.

    The docstring previously asserted sys.executable "is the venv python
    whenever this is run the way it is meant to be", which was wrong about
    the single most common way it runs.
    """

    def _tree(self):
        import pathlib, tempfile
        base = pathlib.Path(tempfile.mkdtemp())
        (base / "app" / "automations" / "icd_alerts").mkdir(parents=True)
        (base / "app" / "automations" / "icd_alerts" / "run.py").touch()
        (base / "venv" / "bin").mkdir(parents=True)
        (base / "venv" / "bin" / "python").touch()
        return base

    def test_it_finds_the_sibling_venv_not_the_running_interpreter(self):
        from automations.icd_alerts import boot_schedule as B
        base = self._tree()
        self.assertEqual(B.venv_python(base / "app"),
                         base / "venv" / "bin" / "python")

    def test_it_does_not_simply_take_sys_executable(self):
        import sys
        from automations.icd_alerts import boot_schedule as B
        base = self._tree()
        self.assertNotEqual(str(B.venv_python(base / "app")), sys.executable)

    def test_a_tree_with_no_venv_falls_back_rather_than_breaking(self):
        """A checkout being tested by hand has no sibling venv, and this must
        still produce something runnable."""
        import pathlib, tempfile, sys
        from automations.icd_alerts import boot_schedule as B
        bare = pathlib.Path(tempfile.mkdtemp()) / "app"
        bare.mkdir()
        self.assertEqual(str(B.venv_python(bare)), sys.executable)

    def test_the_plist_names_the_venv_python_for_a_real_install(self):
        """BEHAVIOUR, NOT SOURCE TEXT. Three attempts at this today matched
        my own prose instead of the code -- once passing a check it had not
        performed. What matters is the interpreter the plist actually names.
        """
        import sys
        from automations.icd_alerts import boot_schedule as B
        base = self._tree()
        with mock.patch.object(B, "app_root", lambda: base / "app"):
            plist = B.plist_text(120)
        want = str(base / "venv" / "bin" / "python")
        self.assertIn("<string>%s</string>" % want, plist)
        self.assertNotIn("<string>%s</string>" % sys.executable, plist,
                         "the boot job would run whatever launched setup.py")


class ALoadedBootJobIsNotNecessarilyAWorkingOne(unittest.TestCase):
    """Khalil's was installed, accepted by launchd, running every two minutes
    -- and dying every time on ModuleNotFoundError, because it named the
    system Python that ran the installer instead of the venv.

    finish_setup asked only `loaded()`, so re-running the link would have
    reported "already done" and skipped the very repair he ran it for.
    """

    def _plist(self, interpreter):
        import plistlib, pathlib, tempfile
        path = pathlib.Path(tempfile.mkdtemp()) / "boot.plist"
        with path.open("wb") as fh:
            plistlib.dump({"Label": "x",
                           "ProgramArguments": [interpreter, "-m", "x"]}, fh)
        return path

    def test_a_job_naming_the_wrong_python_is_not_right(self):
        from automations.icd_alerts import boot_schedule as B
        path = self._plist("/usr/bin/python3")
        with mock.patch.object(B, "DAEMON_PATH", str(path)), \
             mock.patch.object(B, "venv_python",
                               lambda *_a: "/home/.lucy-reports/venv/bin/python"):
            self.assertFalse(B.runs_the_right_python())

    def test_a_job_naming_the_venv_is_right(self):
        from automations.icd_alerts import boot_schedule as B
        want = "/home/.lucy-reports/venv/bin/python"
        path = self._plist(want)
        with mock.patch.object(B, "DAEMON_PATH", str(path)), \
             mock.patch.object(B, "venv_python", lambda *_a: want):
            self.assertTrue(B.runs_the_right_python())

    def test_a_missing_plist_is_not_right(self):
        from automations.icd_alerts import boot_schedule as B
        with mock.patch.object(B, "DAEMON_PATH", "/nowhere/at/all.plist"):
            self.assertFalse(B.runs_the_right_python())

    def test_finish_setup_repairs_rather_than_skipping(self):
        import inspect
        from automations.icd_alerts import finish_setup as F
        src = inspect.getsource(F._boot_job)
        self.assertIn("runs_the_right_python", src,
                      '"loaded" alone would report already done')


class TheOneLinkAlsoFixesASaraPlusPassword(unittest.TestCase):
    """Khalil hit a rotated SaraPlus password on his first afternoon
    (2026-09-16) and needed a SECOND command pasted after the link -- which
    is exactly the "one more thing" finish_setup exists to stop.

    SaraPlus rotates every few weeks, so this is not a setup-time question:
    it is what an office hits months later when their alerts go quiet.
    """

    def setUp(self):
        from automations.icd_alerts import finish_setup
        self.F = finish_setup

    def test_saraplus_is_one_of_the_steps(self):
        import inspect
        self.assertIn("_saraplus", inspect.getsource(self.F.run))

    def test_it_is_skipped_for_an_office_with_no_saraplus(self):
        from automations.icd_alerts import config as C
        with mock.patch.object(C, "uses_saraplus", lambda: False):
            self.assertIn("not needed",
                          self.F._saraplus(lambda *_a: None))

    def test_a_working_login_is_never_asked_to_change(self):
        """Prompting a working office for a password is how somebody changes
        one that was fine -- our notes record two unnecessary changes from
        exactly that."""
        from automations.icd_alerts import config as C, sara_read
        with mock.patch.object(C, "uses_saraplus", lambda: True), \
             mock.patch.object(sara_read, "check_account",
                               lambda **k: {"ok": True}):
            self.assertEqual(self.F._saraplus(lambda *_a: None),
                             "already working")

    def test_a_broken_login_is_asked_for(self):
        from automations.icd_alerts import config as C, sara_read, run as R
        with mock.patch.object(C, "uses_saraplus", lambda: True), \
             mock.patch.object(sara_read, "check_account",
                               lambda **k: {"ok": False}), \
             mock.patch.object(R, "cmd_set_login", lambda **k: 0):
            self.assertEqual(self.F._saraplus(lambda *_a: None), "done")

    def test_the_update_still_runs_before_every_other_step(self):
        import inspect
        src = inspect.getsource(self.F.run)
        self.assertLess(src.index("_update"), src.index("_saraplus"))


class NoTestMayRaiseARealDialog(unittest.TestCase):
    """A test of finish_setup.run() that leaves one step unpatched RUNS that
    step -- and on 2026-09-16 that put a real SaraPlus password box on
    Megan's screen, mid-conversation, three times.

    [[feedback_no_blind_test_sweeps]] says some test_*.py do things for real.
    This is the shape of that: not a send, but a prompt.
    """

    def test_every_step_in_run_is_named_here(self):
        """If a step is added to run() it must be added to the patch lists in
        OneLinkThatDoesWhateverIsMissing too. This fails loudly when it is
        not, instead of the step quietly executing against the machine
        running the tests."""
        import inspect
        from automations.icd_alerts import finish_setup as F
        steps = set(re.findall(r'\("[^"]+", (_\w+)\)',
                               inspect.getsource(F.run)))
        guarded = inspect.getsource(OneLinkThatDoesWhateverIsMissing)
        missing = [s for s in steps if s not in guarded]
        self.assertEqual(missing, [],
                         "unpatched in the run() tests, so it executes for "
                         "real: %s" % missing)


class TheSaleLinesSoundLikeTheCompany(unittest.TestCase):
    """Megan 2026-09-16, on what the channels already say: "Heck Yeah",
    "x Found the Money!", "Snicklepop,!! x is on the board!".

    An alert that does not sound like the room it posts in reads as a system
    narrating over people, which is the fastest way to be scrolled past.
    """

    def _pools(self, campaign):
        from automations.shared import sale_hype as H
        sh = H.shape(campaign)
        return sh.regular_lines, sh.large_lines, sh.super_lines

    def test_every_tier_has_more_than_one_wording(self):
        """The loud two used to be ONE line each -- and they are the ones
        people see most: on Box roughly two sales in three land there."""
        for campaign in ("att", "nds", "b2b_box"):
            for pool in self._pools(campaign):
                self.assertGreater(len(pool), 1, campaign)

    def test_the_popular_emoji_are_in_there(self):
        """Megan 2026-09-16: fries and paw prints are what the channels are
        using at the moment. Sprinkled, not on every line -- an emoji on
        everything stops being a signal."""
        for campaign in ("att", "b2b_box"):
            joined = " ".join(sum(self._pools(campaign), ()))
            for emoji in (":fries:", ":paw_prints:"):
                self.assertIn(emoji, joined, "%s / %s" % (campaign, emoji))

    def test_no_emoji_is_on_every_single_line(self):
        for campaign in ("att", "b2b_box"):
            for pool in self._pools(campaign):
                for emoji in (":fries:", ":paw_prints:"):
                    hits = sum(1 for l in pool if emoji in l)
                    self.assertLess(hits, len(pool), "%s everywhere" % emoji)

    def test_the_ribbing_lands_on_ordinary_days_only(self):
        """Megan 2026-09-16: "joke about not getting complacent".

        It is funny after one sale and sour after somebody's best day of the
        month -- so the top tier stays pure celebration and the joke sits
        where the day is ordinary.
        """
        for campaign in ("att", "b2b_box"):
            regular, _large, super_ = self._pools(campaign)
            ribbed = [l for l in regular if "complacen" in l.lower()]
            self.assertTrue(ribbed, campaign)
            for line in super_:
                self.assertNotIn("complacen", line.lower())

    def test_the_word_is_complacent_not_a_synonym(self):
        """Megan was specific (2026-09-16). It is the word the offices
        actually use, and a near-synonym in a line meant to sound like them
        is the whole difference between borrowed and invented."""
        for campaign in ("att", "b2b_box"):
            joined = " ".join(sum(self._pools(campaign), ())).lower()
            self.assertIn("complacen", joined)
            for near in ("comfortable", "comfy", "coasting"):
                self.assertNotIn(near, joined, near)

    def test_the_house_phrases_are_in_there(self):
        for campaign in ("att", "b2b_box"):
            joined = " ".join(sum(self._pools(campaign), ())).lower()
            for phrase in ("heck yeah", "found the money", "snicklepop",
                           "closers", "winner"):
                self.assertIn(phrase, joined, "%s / %s" % (campaign, phrase))

    def test_the_top_tier_shouts_the_name(self):
        """A rep's name in caps reads differently in a channel, and it is the
        one part of the old wording doing real work."""
        from automations.shared import sale_hype as H
        import datetime as _dt
        seen = {H.hype("Max Allen", {"Int": 1, "NL": 5},
                       _dt.date(2026, 9, n % 28 + 1), "att")
                for n in range(1, 60)}
        self.assertTrue(all("MAX" in line for line in seen), seen)

    def test_box_still_says_contract_not_board_at_the_regular_tier(self):
        regular, _l, _s = self._pools("b2b_box")
        joined = " ".join(regular).lower()
        self.assertIn("contract", joined)
        self.assertNotIn("on the board", joined)

    def test_the_same_sale_always_gets_the_same_words(self):
        """Hashed, never random: a sweep that has to be re-run repeats itself
        instead of announcing one sale twice in two different voices."""
        from automations.shared import sale_hype as H
        import datetime as _dt
        m = {"Int": 1, "NL": 3}
        first = H.hype("Max Allen", m, _dt.date(2026, 9, 16), "att")
        for _ in range(20):
            self.assertEqual(
                H.hype("Max Allen", m, _dt.date(2026, 9, 16), "att"), first)

    def test_every_line_renders_without_a_stray_placeholder(self):
        """A line with the wrong field name posts the braces verbatim."""
        for campaign in ("att", "nds", "b2b_box"):
            for pool in self._pools(campaign):
                for line in pool:
                    got = line.format(first="Max")
                    self.assertNotIn("{", got, line)
