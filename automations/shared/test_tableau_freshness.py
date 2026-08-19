"""A WEEKLY source must not be judged by the daily bar.

Direct Deposit posted two false alerts in two days (8/18 ORG DD Detail, 8/19
ICD dd Detail) because the shared gate asked a weekly feed for yesterday's
data. These pin the rule that replaced it — and, just as important, that ONE
missed week is still loud, so the loosening didn't turn into blindness.
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.shared import tableau_freshness as tf

DD = "DirectDepositICDVIEWVersion2_0/DDDETAIL → ICD dd Detail"
DD_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
          "DirectDepositICDVIEWVersion2_0/DDDETAIL?:iid=1")
DAILY_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
             "B2BBOXEnergyTracker/BoxOrderLog?:iid=1")


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
        out = self._check(DAILY_URL, "8/16/2026", dt.date(2026, 8, 19), "d.csv")
        self.assertEqual(out["verdict"], "stale")
        self.assertEqual(len(self._alerts), 1)

    def test_an_explicit_needs_from_the_caller_still_wins(self):
        out = tf.check_export(_export(self.tmp, "8/16/2026", "e.csv"),
                              view_url=DD_URL, sheet="ICD dd Detail",
                              needs=dt.date(2026, 8, 18),
                              today=dt.date(2026, 8, 19))
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


if __name__ == "__main__":
    unittest.main()
