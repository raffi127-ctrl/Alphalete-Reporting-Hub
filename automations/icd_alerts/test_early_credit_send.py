"""Credit checks go to the relay the moment their SaraPlus pass is done, not
after the three sales grids behind it (Megan, 2026-11-13: "how can we get
these sara alerts to go quicker for everyone?").

What these pin:
  * the early send carries the sales EXACTLY as last sent -- the relay
    overwrites the whole row, so an early send without them would blank an
    office's sales until the full send landed;
  * it only happens when there is something safe to carry: sent today, by this
    office, within EARLY_SALES_MAX_AGE_MIN -- a sales half that has been
    failing longer must still let the row go stale;
  * it never raises, and never runs on a dry run, outside the alert hours, or
    on a catch-up.
"""
import datetime as dt
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import relay as R
from automations.icd_alerts import run as RUN
from automations.icd_alerts import sara_read as SR

REC = {"office_key": "test-office", "relay_url": "https://example.invalid/x",
       "relay_key": "k"}
DAY = dt.date(2026, 11, 13)
NOW = dt.datetime(2026, 11, 13, 15, 0, 0)
SALES = {"PAT EXAMPLE": {"Int": 2, "Int Up": 0, "DTV": 0, "NL": 1}}


class EarlySend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.note = Path(self.tmp.name) / "last_sales_sent.json"
        self.sent = []
        ps = [mock.patch.object(R, "_last_sales_path", return_value=self.note),
              mock.patch.object(R.C, "app_dir", return_value=None),
              mock.patch.object(R, "_endpoint", return_value=dict(REC)),
              mock.patch.object(R, "_post", side_effect=self._post)]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def _post(self, url, data):
        self.sent.append(json.loads(data))
        return '{"ok": true}'

    def _early(self, records, **kw):
        return R.send_records_early(records, DAY, office_key="test-office",
                                    log=lambda *_: None,
                                    now=kw.get("now", NOW))

    def test_nothing_goes_early_before_a_full_send_today(self):
        self.assertFalse(self._early({"PAT EXAMPLE": 3}))
        self.assertEqual(self.sent, [])

    def test_a_full_send_is_remembered_and_rides_the_next_early_send(self):
        R.send({"PAT EXAMPLE": 3}, DAY, sales=SALES, office_key="test-office",
               log=lambda *_: None)
        full = self.sent[-1]
        note = json.loads(self.note.read_text())
        note["at"] = (NOW - dt.timedelta(minutes=2)).isoformat(timespec="seconds")
        self.note.write_text(json.dumps(note))

        self.assertTrue(self._early({"PAT EXAMPLE": 4, "SAM SAMPLE": 1}))
        early = self.sent[-1]
        self.assertEqual(early["records"], {"PAT EXAMPLE": 4, "SAM SAMPLE": 1})
        self.assertEqual(early["sales"], full["sales"])       # verbatim
        self.assertTrue(early["sales"])                       # never blanked
        self.assertEqual(early["day"], "2026-11-13")
        self.assertEqual(early["office_key"], "test-office")

    def _note(self, **over):
        got = {"office_key": "test-office", "day": "2026-11-13",
               "at": (NOW - dt.timedelta(minutes=2)).isoformat(timespec="seconds"),
               "sales": SALES}
        got.update(over)
        self.note.write_text(json.dumps(got))

    def test_stale_sales_stop_the_early_send(self):
        old = NOW - dt.timedelta(minutes=R.EARLY_SALES_MAX_AGE_MIN + 1)
        self._note(at=old.isoformat(timespec="seconds"))
        self.assertFalse(self._early({"PAT EXAMPLE": 4}))
        self.assertEqual(self.sent, [])

    def test_yesterdays_or_another_offices_sales_are_never_reused(self):
        self._note(day="2026-11-12")
        self.assertFalse(self._early({"PAT EXAMPLE": 4}))
        self._note(office_key="someone-else")
        self.assertFalse(self._early({"PAT EXAMPLE": 4}))
        self._note(at="not a time")
        self.assertFalse(self._early({"PAT EXAMPLE": 4}))
        self.assertEqual(self.sent, [])

    def test_a_failed_post_is_false_not_an_error(self):
        self._note()
        with mock.patch.object(R, "_post", side_effect=OSError("no route")):
            self.assertFalse(self._early({"PAT EXAMPLE": 4}))
        with mock.patch.object(R, "_post", return_value="<html>nope</html>"):
            self.assertFalse(self._early({"PAT EXAMPLE": 4}))
        with mock.patch.object(R, "_post", return_value='{"ok": false}'):
            self.assertFalse(self._early({"PAT EXAMPLE": 4}))

    def test_a_dry_run_remembers_nothing(self):
        R.send({"PAT EXAMPLE": 3}, DAY, sales=SALES, office_key="test-office",
               log=lambda *_: None, dry_run=True)
        self.assertFalse(self.note.exists())


class Wiring(unittest.TestCase):
    def test_the_read_hands_over_after_credit_checks_and_before_sales(self):
        src = inspect.getsource(SR.read_day)
        credit = src.index("C.SERVICE_INTERNET")
        hand = src.index("on_records(dict(records))")
        sales = src.index('S._run_report(page, base, day, "AT&T"')
        self.assertLess(credit, hand)
        self.assertLess(hand, sales)

    def test_only_an_ordinary_live_sweep_of_today_sends_early(self):
        src = inspect.getsource(RUN.cmd_once)
        self.assertIn("if not (dry_run or sales_only or resume_only) "
                      "and day == C.today():", src)
        self.assertIn("on_records=early", src)

    def test_the_early_send_never_holds_up_the_sales_grids(self):
        # its own thread, and always waited for before the full send
        src = inspect.getsource(RUN.cmd_once)
        self.assertIn("threading.Thread(", src)
        self.assertIn("target=R.send_records_early", src)
        fin = src.index("finally:")
        self.assertIn("t.join(EARLY_SEND_WAIT_S)", src[fin:fin + 400])
        self.assertLess(fin, src.index("data = St.load()"))
        self.assertLessEqual(RUN.EARLY_SEND_WAIT_S, 60)

    def test_the_stale_cap_sits_inside_the_posters_stale_window(self):
        # An office whose sales half is dead must still go stale: the cap has
        # to be shorter than the 25 minutes after which boards are withheld.
        self.assertLess(R.EARLY_SALES_MAX_AGE_MIN, 25)


if __name__ == "__main__":
    unittest.main()
