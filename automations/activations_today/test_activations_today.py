"""python -m unittest automations.activations_today.test_activations_today"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.activations_today import pull, run

HEADER = ["Owner Name", "Rep", "Customer Name", "sp.SPM Number",
          "sp.Order Date (copy)", "Current Install Date",
          "Days to Current Install", "Current Install Date Week Ending",
          "Install Status", "DTR Status", "Product Type (Broken Out)", "Package"]

ROWS = [
    ["Rafael Hidalgo", "Alyssa Moreno", "ARIANA H", "SPM1", "11/06/2026",
     "11/10/2026", "0", "11/14/2026", "On Track", "Confirmed", "NEW INTERNET",
     "Internet 1000 (Fiber 1 GIG)"],
    ["", "", "HARDIK P", "SPM2", "11/08/2026", "11/14/2026", "4",
     "11/14/2026", "On Track", "Null", "NEW INTERNET", "Internet 1000"],
    ["", "Bill Hirwa", "ADILENE C", "SPM3", "11/05/2026", "11/10/2026", "0",
     "11/14/2026", "Self Install On Track", "Confirmed", "NEW INTERNET",
     "Internet 1000"],
    ["", "Brenden Mendez", "JAVIER N", "SPM4", "10/24/2026", "11/10/2026",
     "0", "11/14/2026", "Past Due", "Confirmed", "VIDEO",
     "DIRECTV Streaming App"],
    ["Someone Else", "Other Rep", "X Y", "SPM5", "11/05/2026", "11/10/2026",
     "0", "11/14/2026", "On Track", "Confirmed", "NEW INTERNET", "Internet"],
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

    def test_fill_down_owner_and_rep(self):
        self.assertEqual(self.rows[1]["Owner Name"], "Rafael Hidalgo")
        self.assertEqual(self.rows[1]["Rep"], "Alyssa Moreno")

    def test_only_owner_and_today(self):
        mine = pull.owner_rows(self.rows, "rafael hidalgo")
        self.assertEqual(len(mine), 4)
        today = pull.scheduled_on(mine, dt.date(2026, 11, 10))
        self.assertEqual([r["Customer Name"] for r in today],
                         ["ARIANA H", "ADILENE C", "JAVIER N"])

    def test_status_colors(self):
        self.assertEqual(run.status_color("On Track"), run._GREEN)
        self.assertEqual(run.status_color("Rescheduled Install Past Due"), run._RED)
        self.assertEqual(run.status_color("JEP Order"), run._RED)
        self.assertEqual(run.status_color("Self Install"), run._YELLOW)

    def test_render(self):
        day = dt.date(2026, 11, 10)
        today = pull.scheduled_on(pull.owner_rows(self.rows, "Rafael Hidalgo"), day)
        work = run.build(today, "Rafael Hidalgo", day)
        self.assertEqual(work["count"], 3)
        self.assertEqual([r for r, _ in work["sections"][0]["reps"]],
                         ["Alyssa Moreno", "Bill Hirwa", "Brenden Mendez"])
        outs = run.render(work, self.tmp / "a.png")
        self.assertTrue(outs[0].exists())


if __name__ == "__main__":
    unittest.main()
