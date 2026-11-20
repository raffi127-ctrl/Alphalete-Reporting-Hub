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

    def test_install_type_colors(self):
        self.assertEqual(run.status_color("Tech Install"), run._YELLOW)
        self.assertEqual(run.status_color("Self Install"), run._BLUE)
        self.assertEqual(run.status_color(""), "")

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

    def test_wireless_one_row_per_line(self):
        """Raf 11/16: every line itemized with its own status; activated
        lines of a still-open order show greyed; all-active orders drop."""
        def line(cust, spm, status, act=""):
            return {"Owner Name": "Rafael Hidalgo", "Rep": "Zed Rep",
                    "Customer Name": cust, "sp.SPM Number": spm,
                    "sp.Order Date (copy)": "11/02/2026",
                    "Product Type (Broken Out)": "WIRELESS",
                    "Package": "AT&T Value 2.0", "spe.Status": status,
                    "Status Date": "11/14/2026",
                    "Activatoin Date (order log)": act}
        rows = [line("MIX M", "SPM9", "Shipped"),
                line("MIX M", "SPM9", "Active", "11/12/2026"),
                line("MIX M", "SPM9", "Delivered"),
                line("MIX M", "SPM9", "Cancelled"),
                line("DONE D", "SPM8", "Active", "11/10/2026")]
        wl = pull.wireless_pending(rows)
        self.assertEqual([r["spe.Status"] for r in wl],
                         ["Shipped", "Delivered", "Active"])
        self.assertEqual(pull.wireless_orders(wl), 1)
        work = run.build(wl, "Rafael Hidalgo", self.day)
        cells = [r.cells for r in work["sections"][0]["rows"]]
        self.assertEqual(cells[0][0], "MIX M")
        self.assertEqual(cells[1][0], "")
        self.assertEqual(cells[0][3], "Shipped 11/14")
        self.assertEqual(cells[2][3], "Activated 11/12")
        self.assertEqual(cells[1][5], "Line 2 of 3 · AT&T Value 2.0")
        self.assertEqual(work["sections"][0]["rows"][2].status, "Activated")
        self.assertEqual(run.count_text(wl), "0 installs + 1 wireless pending")
        self.assertTrue(run.render(work, self.tmp / "w.png")[0].exists())



class NameGroupsCase(unittest.TestCase):
    def test_lowercase_rep_sorts_with_its_letter(self):
        reps = [(n, []) for n in ["Ana A", "Kim K", "Zoe Z", "ortensia m"]]
        groups = run.name_groups(reps, max_names=2, stretch=2)
        self.assertEqual([l for l, _ in groups], ["A–K", "O–Z"])
        self.assertEqual([r for r, _ in groups[1][1]], ["ortensia m", "Zoe Z"])


if __name__ == "__main__":
    unittest.main()
