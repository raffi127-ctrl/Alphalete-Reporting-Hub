"""After Lucy asks an office to sign back in, she says "Good to go" once it
worked (Megan 2026-10-20: "Right now they don't know if they got it corrected
or not")."""
import datetime as dt
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from automations.icd_alerts import post as P, offices as O

DAY = dt.date(2026, 10, 20)
NOW = dt.datetime(2026, 10, 20, 14, 0)
HEAD_F = ["Office", "Day", "Stage", "Summary", "Detail", "Count", "First At",
          "Last At", "Local Time", "Agent", "Platform", "Last Posted At"]


class GoodToGoTest(unittest.TestCase):
    def _book(self, stage="signin-saraplus", fault_last="10/20/2026 13:00:00",
              relay_at="10/20/2026 13:30:00", knocks_at=""):
        faults = [HEAD_F, ["cyrus", "2026-10-20", stage, "signed out", "", "3",
                           "10/20/2026 12:00:00", fault_last, "", "", "", "x"]]
        relay = [["Office", "Day", "Records JSON", "Received At"],
                 ["cyrus", "2026-10-20", "{}", relay_at]]
        knocks = [["Office", "Day", "a", "b", "c", "Received At"],
                  ["cyrus", "2026-10-20", "", "", "", knocks_at]]
        tabs = {P.FAULTS_TAB: faults, P.RELAY_TAB: relay, P.KNOCKS_TAB: knocks}
        book = mock.MagicMock()
        book.worksheet.side_effect = lambda n: mock.Mock(
            **{"get_all_values.return_value": tabs[n]})
        return book

    def _run(self, book, system="saraplus", fixed=None, send=True):
        d = pathlib.Path(tempfile.mkdtemp())
        asked, done = d / "asked.json", d / "fixed.json"
        asked.write_text(json.dumps(
            {"2026-10-20|signin|cyrus|%s" % system: "2026-10-20T12:05:00"}))
        if fixed:
            done.write_text(json.dumps(fixed))
        dms = []
        office = O.AlertOffice(key="cyrus", owner="Cyrus Wade",
                               label="Cyrus's Local Office", channels=(),
                               timezone="America/Chicago")
        with mock.patch.object(P, "SIGNIN_WARNED_PATH", asked), \
             mock.patch.object(P, "SIGNIN_FIXED_PATH", done), \
             mock.patch.object(P, "dm_office_people",
                               lambda k, t, **kw: dms.append((k, t))), \
             mock.patch.object(P.O, "get", lambda k: office):
            out = P.confirm_signins_fixed(DAY, send=send, book=book,
                                          log=lambda *a, **k: None, now=NOW)
        return out, dms

    def test_a_clean_read_after_the_ask_says_good_to_go(self):
        out, dms = self._run(self._book())
        self.assertEqual(out, ["cyrus"])
        self.assertEqual(dms[0][0], "cyrus")
        self.assertIn("Good to go", dms[0][1])
        self.assertIn("SaraPlus", dms[0][1])
        self.assertIn("1:30 PM", dms[0][1])

    def test_still_failing_says_nothing(self):
        out, dms = self._run(self._book(relay_at="10/20/2026 12:30:00"))
        self.assertEqual((out, dms), ([], []))

    def test_only_once(self):
        out, dms = self._run(self._book(), fixed={
            "2026-10-20|signin|cyrus|saraplus": "2026-10-20T13:40:00"})
        self.assertEqual(dms, [])

    def test_ownerville_needs_knocks_not_sales(self):
        book = self._book(stage="signin-ownerville", knocks_at="")
        self.assertEqual(self._run(book, system="ownerville")[1], [])
        book = self._book(stage="signin-ownerville",
                          knocks_at="10/20/2026 13:40:00")
        self.assertIn("OwnerVille", self._run(book, system="ownerville")[1][0][1])

    def _indeed_book(self, probe_at):
        book = self._book(stage="signin-indeed", relay_at="10/20/2026 13:30:00")
        faults = book.worksheet(P.FAULTS_TAB).get_all_values()
        if probe_at:
            faults.append(["cyrus", "2026-10-20", "probe-indeed-clear",
                           "a push got past Indeed's check again", "", "1",
                           probe_at, probe_at, "", "", "", "x"])
        tabs = {P.FAULTS_TAB: faults,
                P.RELAY_TAB: book.worksheet(P.RELAY_TAB).get_all_values(),
                P.KNOCKS_TAB: book.worksheet(P.KNOCKS_TAB).get_all_values()}
        book.worksheet.side_effect = lambda n: mock.Mock(
            **{"get_all_values.return_value": tabs[n]})
        return book

    def test_indeed_needs_its_own_cleared_probe_not_sales(self):
        # Sales relaying is no proof Indeed's box was ticked (Megan 10/21).
        self.assertEqual(self._run(self._indeed_book(None),
                                   system="indeed")[1], [])
        dms = self._run(self._indeed_book("10/20/2026 13:40:00"),
                        system="indeed")[1]
        self.assertEqual(dms[0][1], ":white_check_mark: *Cyrus's Local "
                                    "Office* — good to go on Indeed. Lucy is "
                                    "pushing applicants again.")

    def test_dry_run_sends_nothing(self):
        self.assertEqual(self._run(self._book(), send=False)[1], [])


if __name__ == "__main__":
    unittest.main()
