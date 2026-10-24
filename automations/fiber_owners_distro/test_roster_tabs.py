"""Roster tabs are found by label, whatever spelling Kelly's file ships.

`python -m unittest automations.fiber_owners_distro.test_roster_tabs`

10/10 the Fiber tab came as 'RES ATT'; 10/24 it came as 'RES-ATT' and the
exact-string lookup killed the whole weekly sync.
"""
import tempfile
import unittest
from pathlib import Path

from automations.fiber_owners_distro import roster


def _roster(tabs):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, email in tabs:
        ws = wb.create_sheet(name)
        ws.append([name])                      # title block, header lower down
        ws.append(["ICD OWNER NAME", "Email"])
        ws.append(["Owner " + name, email])
    path = Path(tempfile.mkdtemp()) / "roster.xlsx"
    wb.save(str(path))
    return path


class TabSpellings(unittest.TestCase):
    def test_hyphen_space_and_case_variants(self):
        for fiber, hybrid in [("RES-ATT", "HYBRID"), ("RES ATT", "Hybrid "),
                              ("Fiber", "hybrid"), ("res_att", "HYBRID")]:
            x = _roster([(fiber, "f@x.com"), ("RES-ATT-OOF", "nds@x.com"),
                         (hybrid, "h@x.com")])
            got = {o.email for o in roster.fiber_owners(x)}
            self.assertEqual(got, {"f@x.com", "h@x.com"}, fiber)

    def test_oof_tab_is_not_mistaken_for_fiber(self):
        x = _roster([("RES-ATT-OOF", "nds@x.com"), ("HYBRID", "h@x.com")])
        with self.assertRaises(RuntimeError):
            roster.fiber_owners(x)


if __name__ == "__main__":
    unittest.main()
