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
        another way -- 6_Agent, not 5_Agent."""
        from automations.shared import saraplus as S
        rows = [["", "6_Agent", "A Rep"] + ["0"] * 15]
        self.assertTrue(S.att_shape_problem(rows))

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

    def test_a_history_only_grid_is_what_triggered_it(self):
        from automations.shared import saraplus as S
        rows = [["", "6_History", "an order"] + ["0"] * 15 for _ in range(9)]
        said = S.att_shape_problem(rows)
        self.assertTrue(said, "this is still worth noticing")
        self.assertIn("6_History", said, "it must say what it actually saw")


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

    def test_the_config_directory_is_the_installers_one(self):
        # The stamp deletion has to hit the real file or the update is not
        # forced and the whole command is pointless.
        self.assertIn('CONFIG_DIR = HOME / ".config" / "lucy-reports"',
                      self.setup)
        self.assertIn("~/.config/lucy-reports/last-selfupdate.txt", self.page)
