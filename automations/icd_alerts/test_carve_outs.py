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


class EitherOfThemCanFinishTheSetUp(unittest.TestCase):
    """Megan or Eve, not Megan only (Megan 2026-09-13).

    Nothing ever BLOCKED Eve from approving an office -- but the room check
    was hardcoded to Megan's id, so when Eve ran it she was told whether MEGAN
    was in the channel, which is the one thing she did not ask and the one
    thing she could not act on.
    """

    def test_the_runner_is_reported_on_even_if_unlisted(self):
        from automations.icd_alerts import approve as A
        # Somebody approving who is not in APPROVERS yet -- Eve today -- must
        # still be told when SHE is the one missing from the room.
        self.assertIn("you", A._missing_people(["U04G5HJBGFN"], "UEVE"))

    def test_everyone_present_reports_nothing(self):
        from automations.icd_alerts import approve as A
        self.assertEqual(A._missing_people(["U04G5HJBGFN", "UEVE"], "UEVE"), [])

    def test_a_missing_approver_is_named(self):
        from automations.icd_alerts import approve as A
        self.assertEqual(A._missing_people(["UEVE"], "UEVE"), ["Megan"])

    def test_a_missing_person_never_blocks_an_approval(self):
        """Lucy missing is fatal; a person missing is a ten-second fix in Slack.

        Blocking on it would leave an office waiting on a click that has
        nothing to do with them.
        """
        from automations.icd_alerts import approve as A
        src = pathlib.Path(A.__file__).read_text()
        # the fatal one appends to `problems` and continues; the people one
        # only decorates the printed line
        self.assertIn('problems.append("%s — Lucy Reporting is not in it"', src)
        self.assertNotIn("problems.append(\"%s — Megan", src)

    def test_lucy_is_still_checked_by_id_not_by_whoever_is_running_it(self):
        """The token is per MACHINE. Asking auth_test "is Lucy here" from
        Megan's laptop answers about Megan, says yes, and approves a room the
        poster cannot reach."""
        from automations.icd_alerts import approve as A
        self.assertEqual(A.LUCY_REPORTING, "U0BCG8F9B5Z")
        src = pathlib.Path(A.__file__).read_text()
        self.assertIn("if LUCY_REPORTING not in members", src)
