"""A credit-check read that parses to nobody carries what the grid showed."""
import datetime as dt
import unittest
from unittest import mock

from automations.icd_alerts import sara_read


class EmptyReadEvidenceTest(unittest.TestCase):
    def test_evidence_names_rows_page_and_text(self):
        page = mock.Mock(url="https://www.saraplus.com/e/(S(x))/ReportingHub.aspx")
        page.title.return_value = "Reporting Hub"
        page.inner_text.return_value = "Start Date 10/21/2026  End Date 10/21/2026  Service AT&T Internet  No records to display."
        raw = [["", "", "Agent", "Records"], ["", "", "Company Total", "0"]]
        ev = sara_read._empty_read_evidence(page, dt.date(2026, 10, 21), raw)
        self.assertIn("raw grid rows: 2", ev)
        self.assertIn("row 0:", ev)
        self.assertIn("ReportingHub.aspx", ev)
        self.assertIn("No records to display", ev)

    def test_evidence_carries_the_whole_grid_not_a_sample(self):
        page = mock.Mock(url="u"); page.title.return_value = "t"
        page.inner_text.return_value = "x"
        page.evaluate.return_value = "rgOrderDash_ATT_Internet_ctl00:11"
        raw = [["", "7_History", "10/%02d/26" % d] for d in range(1, 12)]
        ev = sara_read._empty_read_evidence(page, dt.date(2026, 10, 21), raw)
        self.assertIn("row 10:", ev)
        self.assertIn("tables on page: rgOrderDash_ATT_Internet_ctl00:11", ev)
        self.assertIn("filters:", ev)

    def test_evidence_never_raises(self):
        page = mock.Mock(); page.title.side_effect = RuntimeError("gone"); type(page).url = mock.PropertyMock(side_effect=RuntimeError("gone"))
        ev = sara_read._empty_read_evidence(page, dt.date(2026, 10, 21), None)
        self.assertIn("parsed to 0 reps", ev)


if __name__ == "__main__":
    unittest.main()
