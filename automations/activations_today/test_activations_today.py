"""python -m unittest automations.activations_today.test_activations_today"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.activations_today import pull, run

HEADER = ["Owner Name", "Rep", "Customer Name", "sp.Customer Phone",
          "sp.SPM Number", "sp.Order Date (copy)", "Product Type (Broken Out)",
          "Package", "spe.Status", "spe.Install Date",
          "Activatoin Date (order log)", "Tech Install"]

ROWS = [
    ["Rafael Hidalgo", "Alyssa Moreno", "ARIANA H", "(210) 555-0101", "SPM1",
     "11/06/2026", "NEW INTERNET", "Internet 1000 (Fiber 1 GIG)", "Pending",
     "11/10/2026", "", "Tech"],
    ["", "", "HARDIK P", "(210) 555-0102", "SPM2", "11/08/2026",
     "NEW INTERNET", "Internet 1000", "Pending", "11/14/2026", "", "Tech"],
    ["", "Bill Hirwa", "ADILENE C", "(210) 555-0103", "SPM3", "11/05/2026",
     "NEW INTERNET", "Internet 1000", "Shipped", "11/10/2026", "", "Self"],
    ["", "Brenden Mendez", "JAVIER N", "(210) 555-0104", "SPM4", "10/24/2026",
     "VIDEO", "DIRECTV Streaming App", "Past Due", "11/10/2026", "", "Tech"],
    # already activated -> out
    ["", "Brenden Mendez", "DONE D", "(210) 555-0105", "SPM6", "11/01/2026",
     "NEW INTERNET", "Internet 300", "Activated", "11/10/2026", "11/10/2026", "Tech"],
    # canceled -> out
    ["", "Brenden Mendez", "GONE G", "(210) 555-0106", "SPM7", "11/01/2026",
     "NEW INTERNET", "Internet 300", "Canceled", "11/10/2026", "", "Tech"],
    ["Someone Else", "Other Rep", "X Y", "(210) 555-0107", "SPM5",
     "11/05/2026", "NEW INTERNET", "Internet", "Pending", "11/10/2026", "", "Tech"],
]


def _csv(tmp: Path) -> Path:
    p = tmp / "x.csv"
    text = "\n".join("\t".join(r) for r in [HEADER] + ROWS)
    p.write_bytes(text.encode("utf-16"))
    return p


class ActivationsTodayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rows = pull.read_rows(_csv(self.tmp))
        self.day = dt.date(2026, 11, 10)

    def test_fill_down_owner_and_rep(self):
        self.assertEqual(self.rows[1]["Owner Name"], "Rafael Hidalgo")
        self.assertEqual(self.rows[1]["Rep"], "Alyssa Moreno")

    def test_only_owner_today_open(self):
        mine = pull.owner_rows(self.rows, "rafael hidalgo")
        self.assertEqual(len(mine), 6)
        today = pull.scheduled_on(mine, self.day)
        self.assertEqual([r["Customer Name"] for r in today],
                         ["ARIANA H", "ADILENE C", "JAVIER N"])

    def test_url_is_sale_window(self):
        url = pull.build_url(self.day)
        self.assertIn("SalesBoardOriginal", url)
        self.assertIn("Start%20Date=2026-09-29&End%20Date=2026-11-10", url)

    def test_status_colors(self):
        self.assertEqual(run.status_color("Past Due"), run._RED)
        self.assertEqual(run.status_color("JEP Order"), run._RED)
        self.assertEqual(run.status_color("Pending"), "")

    def test_render(self):
        today = pull.scheduled_on(pull.owner_rows(self.rows, "Rafael Hidalgo"),
                                  self.day)
        work = run.build(today, "Rafael Hidalgo", self.day)
        self.assertEqual(work["count"], 3)
        self.assertEqual([r for r, _ in work["sections"][0]["reps"]],
                         ["Alyssa Moreno", "Bill Hirwa", "Brenden Mendez"])
        self.assertEqual(work["sections"][0]["rows"][0].cells[1], "(210) 555-0101")
        outs = run.render(work, self.tmp / "a.png")
        self.assertTrue(outs[0].exists())


if __name__ == "__main__":
    unittest.main()
