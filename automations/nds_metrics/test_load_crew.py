"""load_crew(): the crew filter still shapes the per-rep boards, but every
line on Carlos's owner is kept on cols.owner_lines for the Revenue Board
(Carlos 2026-11-03: a sale from someone off the list still counts there)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.nds_metrics import run as R

CSV = (
    "Rep,Owner & Office,Order Date,Unit Count\n"
    "NICHOLAS SMEDRA,CARLOS HIDALGO,11/2/2026,1\n"
    "SOMEBODY NEW,CARLOS HIDALGO,11/2/2026,1\n"
    "OTHER OFFICE,RAFAEL HIDALGO,11/2/2026,1\n"
)


class LoadCrew(unittest.TestCase):
    def test_owner_lines_keep_the_off_roster_rep(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ol.csv"
            p.write_text(CSV, encoding="utf-8")
            with mock.patch.object(R, "crew_names", return_value=["Nicholas Smedra"]):
                said = []
                cols, crew = R.load_crew(p, log=said.append)
        reps = lambda rows: sorted(r[0] for r in rows)  # noqa: E731
        self.assertEqual(reps(crew), ["NICHOLAS SMEDRA"])
        self.assertEqual(reps(cols.owner_lines), ["NICHOLAS SMEDRA", "SOMEBODY NEW"])
        self.assertTrue(any("SOMEBODY NEW=1" in s for s in said))   # dropped name is said

    def test_nobody_on_the_roster_falls_back_to_every_owner_line(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ol.csv"
            p.write_text(CSV, encoding="utf-8")
            with mock.patch.object(R, "crew_names", return_value=["Nobody Here"]):
                cols, crew = R.load_crew(p, log=lambda *a: None)
        self.assertEqual(sorted(r[0] for r in crew), ["NICHOLAS SMEDRA", "SOMEBODY NEW"])


if __name__ == "__main__":
    unittest.main()
