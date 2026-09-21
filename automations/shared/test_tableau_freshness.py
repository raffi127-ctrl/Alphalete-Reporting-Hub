"""A WEEKLY source must not be judged by the daily bar.

Direct Deposit posted two false alerts in two days (8/18 ORG DD Detail, 8/19
ICD dd Detail) because the shared gate asked a weekly feed for yesterday's
data. These pin the rule that replaced it — and, just as important, that ONE
missed week is still loud, so the loosening didn't turn into blindness.
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

from automations.shared import tableau_freshness as tf

DD = "DirectDepositICDVIEWVersion2_0/DDDETAIL → ICD dd Detail"
DD_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
          "DirectDepositICDVIEWVersion2_0/DDDETAIL?:iid=1")
DAILY_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
             "B2BBOXEnergyTracker/BoxOrderLog?:iid=1")
# Carlos's cut of the BOX order log — the one that opened the Sunday thread.
BOX_CARLOS_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                  "B2BBOXEnergyTracker/BoxOrderLog/"
                  "8286c5bb-09f8-4bd8-a3cf-4842dd4d7f87/CarlosOrderLog?:iid=1")
LEADPEN_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "NDS-SNRES-ATT-OOFWorkbook/LeadPenetrationOverview/"
               "a15a85ac-e0c8-423d-ba85-6be048203b0b/THISWEEK?:iid=1")
# The custom view recruiting_report/opt_phase pulls, and the DEFAULT view of the
# same workbook that int_wow_penetration pulls on Tuesdays.
NICHURN_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "ATTTRACKER2_1-D2D/FiberLeadPerformance/"
               "a79fd021-3606-4aa2-bf55-bc3856cdac99/AUTOMATIONPULL-NICHURNVIEW")
FIBER_DEFAULT_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                     "ATTTRACKER2_1-D2D/FiberLeadPerformance?:iid=1")
FIBER_SHEET = "Office New Fiber Lead Penetration By Zip"
JE_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
          "JustEnergyRTL-SalesStaffingProductivityWorkbook/"
          "JEAllRetailersSalesSummarybyLocation?:iid=1")
JE_SHEET = "All RTL Sales Summary by Store"
JE_ICD_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
              "JustEnergyRTL-SalesStaffingProductivityWorkbook/"
              "WeeklyMetricsbyICD?:iid=1")


class _Cp1252Stdout:
    """A console that chokes on anything outside cp1252, like Windows'."""

    encoding = "cp1252"

    def write(self, s):
        s.encode("cp1252")          # raises UnicodeEncodeError on ⚠ / →
        return len(s)

    def flush(self):
        pass


def _export(tmp: Path, newest: str, name: str = "x.csv") -> Path:
    p = tmp / name
    p.write_text("Rep Name,cl.Sale Date,Total $ to ICD\n"
                 "A Rep,{},100\n".format(newest), encoding="utf-8")
    return p


class DecodingTheExport(unittest.TestCase):
    """A UTF-8 export with an EVEN byte count used to decode as UTF-16 without
    raising — mojibake headers, "no event-date column", and the source silently
    lost its staleness cover. Both encodings must survive, both lengths."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_utf8_csv_is_read_whatever_its_length(self):
        for n, name in ((0, "even.csv"), (1, "odd.csv")):
            p = self.tmp / name
            p.write_text("""Rep Name,cl.Sale Date,Total $ to ICD
A Rep{},8/16/2026,100
""".format("x" * n), encoding="utf-8")
            self.assertEqual(tf._rows(p)[0][1], "cl.Sale Date",
                             "{} bytes: header came back mangled".format(
                                 p.stat().st_size))

    def test_utf16_tab_crosstab_still_wins(self):
        tab, nl = chr(9), chr(10)
        p = self.tmp / "crosstab.csv"
        p.write_bytes((tab.join(["Rep Name", "cl.Sale Date"]) + nl +
                       tab.join(["A Rep", "8/16/2026"]) + nl).encode("utf-16"))
        header, rows = tf._rows(p)
        self.assertEqual(header[1], "cl.Sale Date")
        self.assertEqual(rows[0][1], "8/16/2026")


class WeeklyBar(unittest.TestCase):
    def test_label_is_recognised_whatever_the_sheet(self):
        self.assertTrue(tf.is_weekly_source(DD))
        self.assertTrue(tf.is_weekly_source(
            "DirectDepositICDVIEWVersion2_0/DDDETAILORG → ORG DD Detail"))
        self.assertFalse(tf.is_weekly_source(
            "B2BBOXEnergyTracker/BoxOrderLog → Order Log"))
        self.assertTrue(tf.is_weekly_source(
            "NDS-SNRES-ATT-OOFWorkbook/LeadPenetrationOverview.csv "
            "→ LeadPenetrationOverview"))
        # A different workbook that merely talks about lead penetration is NOT
        # this view — int_wow_penetration pulls its by-zip sheet daily.
        self.assertFalse(tf.is_weekly_source(
            "ATTTRACKER2_1-D2D/FiberLeadPerformance "
            "→ Office New Fiber Lead Penetration By Zip"))

    def test_needs_is_the_sunday_before_the_one_that_just_ended(self):
        # Wed 2026-08-19: week just ended 8/16, so one week of lag = 8/09.
        self.assertEqual(tf.weekly_needs(dt.date(2026, 8, 19)),
                         dt.date(2026, 8, 9))
        # Tue 8/18 — the day the ORG thread fired at "9 days behind".
        self.assertEqual(tf.weekly_needs(dt.date(2026, 8, 18)),
                         dt.date(2026, 8, 9))
        # On a Sunday the week that just ended is today.
        self.assertEqual(tf.weekly_needs(dt.date(2026, 8, 16)),
                         dt.date(2026, 8, 9))


class TheTwoFalseAlarms(unittest.TestCase):
    """Both real threads, replayed."""

    def setUp(self):
        self._alerts = []
        self._real = tf.alert_stale
        tf.alert_stale = lambda **kw: (self._alerts.append(kw), True)[1]
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        tf.alert_stale = self._real

    def _check(self, url, newest, today, name):
        return tf.check_export(_export(self.tmp, newest, name), view_url=url,
                               sheet="ICD dd Detail", today=today)

    def test_icd_dd_detail_on_8_19_is_fresh(self):
        out = self._check(DD_URL, "8/16/2026", dt.date(2026, 8, 19), "a.csv")
        self.assertEqual(out["verdict"], "fresh")
        self.assertEqual(self._alerts, [])

    def test_org_dd_detail_on_8_18_is_fresh(self):
        out = self._check(DD_URL, "8/9/2026", dt.date(2026, 8, 18), "b.csv")
        self.assertEqual(out["verdict"], "fresh")
        self.assertEqual(self._alerts, [])

    def test_a_missed_week_is_still_loud(self):
        # Nothing newer than 8/02 on 8/19 = the 8/09 week never posted.
        out = self._check(DD_URL, "8/2/2026", dt.date(2026, 8, 19), "c.csv")
        self.assertEqual(out["verdict"], "stale")
        self.assertEqual(len(self._alerts), 1)

    def test_a_daily_source_keeps_the_daily_bar(self):
        # A Wednesday. BOX is Sunday-quiet, which moves nothing but Monday's
        # bar, so this still has to ask for Tuesday and still has to be loud.
        out = self._check(DAILY_URL, "8/16/2026", dt.date(2026, 8, 19), "d.csv")
        self.assertEqual(out["verdict"], "stale")
        self.assertEqual(len(self._alerts), 1)

    def test_an_explicit_needs_from_the_caller_still_wins(self):
        out = tf.check_export(_export(self.tmp, "8/16/2026", "e.csv"),
                              view_url=DD_URL, sheet="ICD dd Detail",
                              needs=dt.date(2026, 8, 18),
                              today=dt.date(2026, 8, 19))
        self.assertEqual(out["verdict"], "stale")


class TheMondayOnlySource(unittest.TestCase):
    """LeadPenetrationOverview, 2026-08-24 — the thread that found the second
    weekly source. `alphalete_org_focus` runs Mondays only (cadence.weekdays
    [0]) against the view's THISWEEK cut, so the newest row is the Saturday that
    closed the week: two days back on the only day it is ever pulled. Replayed
    from the exports themselves, two Mondays eight weeks apart."""

    def setUp(self):
        self._alerts = []
        self._real = tf.alert_stale
        tf.alert_stale = lambda **kw: (self._alerts.append(kw), True)[1]
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        tf.alert_stale = self._real

    def _check(self, newest, today, name):
        return tf.check_export(_export(self.tmp, newest, name),
                               view_url=LEADPEN_URL,
                               sheet="LeadPenetrationOverview", today=today)

    def test_monday_8_24_saturday_data_is_fresh(self):
        out = self._check("8/22/2026", dt.date(2026, 8, 24), "a.csv")
        self.assertEqual(out["verdict"], "fresh")
        self.assertEqual(self._alerts, [])

    def test_monday_6_29_saturday_data_is_fresh(self):
        out = self._check("6/27/2026", dt.date(2026, 6, 29), "b.csv")
        self.assertEqual(out["verdict"], "fresh")
        self.assertEqual(self._alerts, [])

    def test_a_missed_week_is_still_loud(self):
        # Mon 8/24 with nothing newer than Sat 8/15 = the 8/16 week never landed.
        out = self._check("8/15/2026", dt.date(2026, 8, 24), "c.csv")
        self.assertEqual(out["verdict"], "stale")
        self.assertEqual(len(self._alerts), 1)


class TheMondayMorningLag(unittest.TestCase):
    """AUTOMATIONPULL-NICHURNVIEW, 2026-08-24 — a DAILY feed the Monday Focus
    run reads before Sunday has loaded. Not weekly: the same worksheet through
    the workbook's default view carries yesterday when int_wow_penetration pulls
    it on Tuesday afternoons, so only the custom view gets the extra day.
    Replayed from the exports on disk."""

    def setUp(self):
        self._alerts = []
        self._real = tf.alert_stale
        tf.alert_stale = lambda **kw: (self._alerts.append(kw), True)[1]
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        tf.alert_stale = self._real

    def _check(self, newest, today, name, url=NICHURN_URL, **kw):
        return tf.check_export(_export(self.tmp, newest, name), view_url=url,
                               sheet=FIBER_SHEET, today=today, **kw)

    def test_monday_8_24_saturday_data_is_fresh(self):
        out = self._check("8/22/2026", dt.date(2026, 8, 24), "a.csv")
        self.assertEqual(out["verdict"], "fresh")
        self.assertEqual(self._alerts, [])

    def test_monday_8_17_saturday_data_is_fresh(self):
        out = self._check("8/15/2026", dt.date(2026, 8, 17), "b.csv")
        self.assertEqual(out["verdict"], "fresh")
        self.assertEqual(self._alerts, [])

    def test_it_is_not_judged_by_the_weekly_bar(self):
        # Three days back is still loud — this buys ONE day, not a whole week.
        out = self._check("8/21/2026", dt.date(2026, 8, 24), "c.csv")
        self.assertEqual(out["verdict"], "stale")
        self.assertEqual(out["needs"], dt.date(2026, 8, 22))
        self.assertEqual(len(self._alerts), 1)

    def test_the_default_view_keeps_the_daily_bar(self):
        # int_wow_penetration's Tuesday pull carries yesterday, so it still owes
        # the daily bar. The looser one is scoped to the custom view alone.
        out = self._check("5/23/2026", dt.date(2026, 5, 26), "d.csv",
                          url=FIBER_DEFAULT_URL)
        self.assertEqual(out["verdict"], "stale")
        self.assertEqual(len(self._alerts), 1)

    def test_a_caller_that_named_its_own_bar_keeps_it(self):
        out = self._check("8/22/2026", dt.date(2026, 8, 24), "e.csv",
                          max_days_behind=0)
        self.assertEqual(out["verdict"], "stale")


class JustEnergySalesByStoreIsOneIcdsSlice(unittest.TestCase):
    """opt_je pulls this sheet filtered to ONE ICD, so its newest date is that
    ICD's last sale, not the feed's. 2026-09-21: Brandon Stallkamp's 4 sales
    (last Fri 9/18) opened a stale thread while the org-wide JE feed had
    Saturday 9/19 loaded. It was under LAGGY_SOURCE_DAYS before; now it is
    never date-judged (ONE_OWNER_MARKERS)."""

    def setUp(self):
        self._alerts = []
        self._real = tf.alert_stale
        tf.alert_stale = lambda **kw: (self._alerts.append(kw), True)[1]
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        tf.alert_stale = self._real

    def _check(self, newest, today, name, url=JE_URL, **kw):
        return tf.check_export(_export(self.tmp, newest, name), view_url=url,
                               sheet=JE_SHEET, today=today, **kw)

    def test_monday_9_21_a_quiet_icds_friday_does_not_alert(self):
        # The thread itself: Brandon's last sale Fri 9/18, judged Mon 9/21.
        out = self._check("9/18/2026", dt.date(2026, 9, 21), "a.csv",
                          url=JE_URL + "&ICD%20Name=Brandon%20Stallkamp")
        self.assertEqual(out["verdict"], "unknown")
        self.assertEqual(self._alerts, [])

    def test_even_a_week_old_slice_is_not_called_stale(self):
        # An ICD that sold nothing all week has an old newest date too.
        out = self._check("9/7/2026", dt.date(2026, 9, 21), "b.csv")
        self.assertEqual(out["verdict"], "unknown")
        self.assertEqual(self._alerts, [])

    def test_the_other_je_view_keeps_the_daily_bar(self):
        # WeeklyMetricsbyICD feeds the DAILY sales board and has its own guard;
        # the marker names the sheet that alerted, not the workbook.
        out = self._check("8/22/2026", dt.date(2026, 8, 24), "e.csv",
                          url=JE_ICD_URL)
        self.assertEqual(out["verdict"], "stale")
        self.assertEqual(len(self._alerts), 1)


class ACp1252ConsoleCannotSilenceTheAlert(unittest.TestCase):
    """Windows, 2026-08-24: the "⚠ STALE PULL" line raised UnicodeEncodeError on
    a cp1252 console, check_export's blanket except swallowed it, and the
    alert_stale() call that came after it never ran. Verdict stale, alerted
    False, no thread. The console must never decide whether we get heard."""

    def setUp(self):
        self._alerts = []
        self._real = tf.alert_stale
        tf.alert_stale = lambda **kw: (self._alerts.append(kw), True)[1]
        self._stdout = sys.stdout
        sys.stdout = _Cp1252Stdout()
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        sys.stdout = self._stdout
        tf.alert_stale = self._real

    def test_the_alert_still_fires(self):
        out = tf.check_export(_export(self.tmp, "8/13/2026", "a.csv"),
                              view_url=DAILY_URL, sheet="Order Log",
                              today=dt.date(2026, 8, 17))
        self.assertEqual(out["verdict"], "stale")
        self.assertTrue(out["alerted"])
        self.assertEqual(len(self._alerts), 1)


class TheSundayQuietSource(unittest.TestCase):
    """The BOX energy order log, 2026-08-24 — the Monday thread that found the
    rule. B2B energy sells to businesses, which are shut on Sunday, so Monday's
    newest row is Saturday's. Off three BOX offices' merged high-water tabs,
    Carlos's Sundays run 0/0/0/0/1/0 over six weeks while his Saturdays run
    3/3/6/6/7, and all three offices ran full volume into Sat 8/22 — a closed
    weekend, not the capped pull that leaves a cliff."""

    def setUp(self):
        self._alerts = []
        self._real = tf.alert_stale
        tf.alert_stale = lambda **kw: (self._alerts.append(kw), True)[1]
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        tf.alert_stale = self._real

    def _check(self, newest, today, name, url=BOX_CARLOS_URL):
        return tf.check_export(_export(self.tmp, newest, name), view_url=url,
                               sheet="Order Log", today=today)

    def test_label_is_recognised_across_the_whole_workbook(self):
        for cut in ("B2BBOXEnergyTracker/BoxOrderLog/CarlosOrderLog → Order Log",
                    "B2BBOXEnergyTracker/BoxOrderLog → Order Log",
                    "B2BBOXEnergyTracker/BoxOrderLog/ALLEXPORDERLOG → Order Log"):
            self.assertTrue(tf.is_sunday_quiet_source(cut), cut)
        self.assertFalse(tf.is_sunday_quiet_source(DD))

    def test_monday_8_24_saturday_data_is_fresh(self):
        # The thread itself: newest 8/22 (Sat) on Mon 8/24, "needs 8/23".
        out = self._check("8/22/2026", dt.date(2026, 8, 24), "a.csv")
        self.assertEqual(out["verdict"], "fresh")
        self.assertEqual(out["needs"], dt.date(2026, 8, 22))
        self.assertEqual(self._alerts, [])

    def test_the_base_view_the_owner_emails_pull_is_covered_too(self):
        out = self._check("8/22/2026", dt.date(2026, 8, 24), "b.csv",
                          url=DAILY_URL)
        self.assertEqual(out["verdict"], "fresh")
        self.assertEqual(self._alerts, [])

    def test_a_missing_saturday_is_still_loud_on_monday(self):
        # Monday asks for Saturday, not Sunday — Friday-newest still shouts.
        out = self._check("8/21/2026", dt.date(2026, 8, 24), "c.csv")
        self.assertEqual(out["verdict"], "stale")
        self.assertEqual(len(self._alerts), 1)

    def test_tuesday_hears_the_freeze_monday_could_not_prove(self):
        out = self._check("8/22/2026", dt.date(2026, 8, 25), "d.csv")
        self.assertEqual(out["verdict"], "stale")
        self.assertEqual(len(self._alerts), 1)

    def test_sunday_still_asks_for_saturday(self):
        # Sun 8/23: yesterday IS Saturday, so nothing is loosened here.
        self.assertEqual(tf.business_needs(dt.date(2026, 8, 23)),
                         dt.date(2026, 8, 22))

    def test_the_midweek_bar_is_untouched(self):
        for today, wants in ((dt.date(2026, 8, 25), dt.date(2026, 8, 24)),
                             (dt.date(2026, 8, 26), dt.date(2026, 8, 25)),
                             (dt.date(2026, 8, 29), dt.date(2026, 8, 28))):
            self.assertEqual(tf.business_needs(today), wants, today)

    def test_an_explicit_needs_from_the_caller_still_wins(self):
        out = tf.check_export(_export(self.tmp, "8/22/2026", "e.csv"),
                              view_url=BOX_CARLOS_URL, sheet="Order Log",
                              needs=dt.date(2026, 8, 23),
                              today=dt.date(2026, 8, 24))
        self.assertEqual(out["verdict"], "stale")


class TheAlertSaysWhatActuallyHappened(unittest.TestCase):
    """A stale SOURCE is not a suppressed report. The wording it borrowed from
    'capped' claimed three things that were false on 8/19 — pin all three."""

    def _text(self):
        from automations.shared import section_drop_alert as sda
        return sda._compose(
            "tableau-stale-directdepositicdviewversion2-0-dddetail-icd-dd-detail",
            ["DirectDepositICDVIEWVersion2_0/DDDETAIL - ICD dd Detail - newest "
             "data is 2026-08-16"],
            None, "", "stale_source")

    def test_it_does_not_claim_the_report_was_suppressed(self):
        text = self._text().lower()
        self.assertNotIn("nothing was sent", text)
        self.assertNotIn("no email/post went out", text)
        self.assertIn("ran and sent normally", text)

    def test_it_does_not_send_anyone_to_the_box_filters(self):
        text = self._text().lower()
        for wrong in ("contract id", "account id", "probe-filters",
                      "box_order_log_roshan"):
            self.assertNotIn(wrong, text)

    # --- and the other half of the same alert (Megan 2026-09-15) -------------
    # "nothing to re-run" is right until a report has pulled off the stale feed.
    # After that the report SENT, and what it sent is as old as the data. On
    # 2026-09-15 box_order_log posted `THIS 9.14-9.20 paid=0` off a feed stuck
    # at 9/12 while this alert said nothing to re-run; Carlos caught it at 9:04.

    SRC = "tableau-stale-b2bboxenergytracker-boxorderlog-order-log"
    LINE = ("B2BBOXEnergyTracker/BoxOrderLog - Order Log - newest data is "
            "2026-09-12 - 3 day(s) behind 2026-09-15")

    def _text_with(self, reports):
        from automations.shared import section_drop_alert as sda
        from automations.shared import tableau_freshness as tf
        rem = tf._already_sent_remediation(reports, self.SRC)
        return sda._compose(self.SRC, [self.LINE], rem, "", "stale_source")

    def test_nothing_pulled_yet_keeps_the_calm_wording(self):
        """The 2026-08-26 case, untouched: no consumer, so nothing to re-send."""
        from automations.shared import tableau_freshness as tf
        self.assertIsNone(tf._already_sent_remediation([], self.SRC))
        text = self._text_with([]).lower()
        self.assertIn("ran and sent normally", text)

    def test_once_a_report_pulled_it_stops_saying_nothing_to_rerun(self):
        text = self._text_with(["box_order_log"])
        self.assertNotIn("nothing to re-run", text.lower())
        self.assertNotIn("ran and sent normally", text.lower())
        self.assertIn("box_order_log", text)

    def test_it_says_catching_up_will_not_repair_what_went_out(self):
        text = self._text_with(["box_order_log"])
        self.assertIn("does NOT repair what already went out", text)
        self.assertIn("RE-SEND", text)

    def test_it_still_refuses_to_send_you_to_rerun_the_source_id(self):
        """The 2026-08-19 lesson survives the re-wording: the id is a SOURCE."""
        text = self._text_with(["box_order_log"])
        self.assertIn("that id is the SOURCE, not a report", text)

    def test_every_report_that_pulled_is_named(self):
        text = self._text_with(["tableau_screenshots_box", "box_order_log"])
        for r in ("box_order_log", "tableau_screenshots_box"):
            self.assertIn(r, text)

    def test_one_report_reads_singular(self):
        self.assertIn("the report that pulled it already ran",
                      self._text_with(["box_order_log"]))
        self.assertIn("the reports that pulled it already ran",
                      self._text_with(["box_order_log", "tableau_screenshots_box"]))

    def test_it_does_not_tell_you_to_re_run_a_source(self):
        text = self._text()
        self.assertIn("that id is the SOURCE, not a report", text)

    def test_the_kind_exists_so_it_cannot_fall_back_to_section(self):
        from automations.shared import section_drop_alert as sda
        self.assertIn("stale_source", sda._KINDS)
        self.assertNotIn("did NOT post", self._text())

    def test_capped_still_says_all_of_that_where_it_belongs(self):
        from automations.shared import section_drop_alert as sda
        capped = sda._compose("box_order_log_roshan", ["W/V - Order Log"],
                              None, "", "capped")
        self.assertIn("nothing was sent", capped.lower())
        self.assertIn("Contract ID", capped)


class ARecoveredSourceClosesItsOwnThread(unittest.TestCase):
    """Nothing used to close a stale-source incident. Ever.

    WHAT THAT LOOKED LIKE (2026-08-26). `alert_stale` writes a PER-DAY state
    file, so a source still behind tomorrow re-alerts — correct. But a source
    that CATCHES UP has no path back: its thread stays open forever, and the
    channel accumulates alerts nobody can tell apart from live ones.
    drop-tableau-stale-atttracker2-1-d2d-fiberleadperformance-office-new-fiber-lead
    sat open from 08-25 07:30 for exactly this reason, and closing it by hand was
    the only option available.
    """

    def setUp(self):
        from automations.shared import tableau_freshness as tf
        from automations.shared import incident_thread as inc
        self.tf = tf
        self.resolved = []
        real = inc.resolve_report
        inc.resolve_report = lambda rid, **kw: (
            self.resolved.append((rid, kw.get("note", ""))), True)[1]
        self.addCleanup(setattr, inc, "resolve_report", real)

    def test_a_source_that_caught_up_resolves_its_alert(self):
        ok = self.tf.clear_stale("Workbook/View → Sheet", "Workbook/View → Sheet",
                                 dt.date(2026, 8, 26), dt.date(2026, 8, 26))
        self.assertTrue(ok)
        self.assertEqual(1, len(self.resolved))
        self.assertIn("2026-08-26", self.resolved[0][1])

    def test_it_closes_under_the_same_id_the_alert_opened(self):
        """alert_stale and alert_frozen both file under tableau-stale-<slug>;
        closing under anything else leaves the thread open and posts an
        all-clear into a thread nobody is reading."""
        self.tf.clear_stale("ATTTRACKER2_1-D2D/FiberLeadPerformance",
                            "label", None, dt.date(2026, 8, 26))
        self.assertEqual(
            "tableau-stale-" + self.tf._slug("ATTTRACKER2_1-D2D/FiberLeadPerformance"),
            self.resolved[0][0])

    def test_a_frozen_feed_that_moved_says_so_instead_of_naming_a_date(self):
        self.tf.clear_stale("k", "label", None, dt.date(2026, 8, 26))
        self.assertIn("Moving again", self.resolved[0][1])

    def test_a_failure_to_close_never_reaches_the_caller(self):
        """The run that earned the all-clear had GOOD data — it must not fail
        because Slack was down."""
        from automations.shared import incident_thread as inc

        def boom(rid, **kw):
            raise RuntimeError("slack down")
        inc.resolve_report = boom
        self.assertFalse(self.tf.clear_stale("k", "l", None, dt.date(2026, 8, 26)))

    def test_check_export_clears_on_the_fresh_path(self):
        """The wiring, not just the helper — this is what actually runs daily."""
        import inspect
        src = inspect.getsource(self.tf.check_export)
        fresh = src.split('out["verdict"] = "fresh"')[1].split("return out")[0]
        self.assertIn("clear_stale", fresh)


if __name__ == "__main__":
    unittest.main()
