"""Raf and AO stay on OUR machines. Confirmed by Megan, 2026-09-13.

THE DIRECTION THIS PROTECTS AGAINST ITS OWN MOMENTUM. Megan the same day:
"going forward, all knocks and sara+ postings will be done from the ICD
personal machines." That is right for ICD offices, and it will be tempting to
finish the job by moving the last two holdouts as well. She said not to:

  * RAF'S REPORTS SHOULD NOT CHANGE (2026-09-12, said twice, the second time
    while correcting a change that had touched his board). gap_alerts is his.
  * THE AO OFFICE IS ALPHALETE'S OWN, not an ICD's. alphalete_sales_board
    reads SaraPlus on a machine we own, with a login we control, and nobody
    asked for that to move.

These are cheap import-level assertions rather than behaviour tests on
purpose: the failure mode they guard is a whole module being rewired to the
relay, which shows up here long before any of its own tests notice.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _imports(path: pathlib.Path):
    """Every module this file imports, however it spells it."""
    tree = ast.parse(path.read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update("%s.%s" % (node.module, a.name) for a in node.names)
    return out


class RafStaysOnOurMachines(unittest.TestCase):

    PATHS = ("automations/gap_alerts/run.py",
             "automations/gap_alerts/config.py")

    def test_gap_alerts_does_not_read_the_icd_relay(self):
        for rel in self.PATHS:
            mods = _imports(ROOT / rel)
            leaked = [m for m in mods if "icd_alerts" in m or "icd_signup" in m]
            self.assertEqual(leaked, [], "%s now reads the ICD relay. Raf's "
                                         "reports are not supposed to change "
                                         "(Megan 2026-09-12)." % rel)


class AOStaysOnOurMachines(unittest.TestCase):

    PATHS = ("automations/alphalete_sales_board/run.py",
             "automations/alphalete_sales_board/sara.py")

    def test_the_ao_sweep_does_not_read_the_icd_relay(self):
        for rel in self.PATHS:
            mods = _imports(ROOT / rel)
            leaked = [m for m in mods if "icd_alerts" in m or "icd_signup" in m]
            self.assertEqual(leaked, [], "%s now reads the ICD relay. AO is "
                                         "Alphalete's own office, not an ICD's "
                                         "(Megan 2026-09-13)." % rel)

    def test_the_ao_sweep_still_reads_saraplus_directly(self):
        # The other direction: if this ever stops being true, AO has been
        # migrated and nobody said to.
        mods = _imports(ROOT / "automations/alphalete_sales_board/sara.py")
        self.assertTrue(any("saraplus" in m for m in mods),
                        "AO no longer reads SaraPlus directly")


if __name__ == "__main__":
    unittest.main()
