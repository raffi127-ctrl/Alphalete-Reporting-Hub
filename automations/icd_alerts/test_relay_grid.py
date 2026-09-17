"""The relay script and the columns we read must agree, and must fit.

WHAT WENT WRONG (2026-09-17). 'ICD Knocks' was created with eight columns,
before the agent/machine columns existed. The branch of _upsertKnocks that
writes the wider header only runs when the tab is ABSENT, so an existing tab
never gained them -- and getRange(row, 9) on an eight-column sheet does not
grow it, it THROWS. Every such write sits inside doPost's try, so the failure
would not have been "no machine recorded", it would have been "the relay
rejected the knocks" for every office at once, the moment the script was
redeployed.

It stayed hidden because nothing exercised it: the DEPLOYED script predated
the change, so the write that would have thrown was never reached. The cost
was Khalil -- the only knocks-only office, and so the only machine we had no
heartbeat for at all.

These tests read the two sides together, which is the only way this class of
drift is visible: one side is Python constants, the other is JavaScript in a
file nobody imports.
"""
from __future__ import annotations

import pathlib
import re
import unittest

from automations.icd_alerts import post as P

GS = (pathlib.Path(__file__).resolve().parents[2]
      / "resources" / "icd-alerts-relay.gs")


def _header_after(marker: str) -> list:
    """The appendRow([...]) header list that follows `marker` in the script."""
    src = GS.read_text()
    at = src.index(marker)
    start = src.index("appendRow([", at) + len("appendRow([")
    return re.findall(r"'([^']*)'", src[start:src.index("]", start)])


class HeadersMatchTheIndexesWeReadTest(unittest.TestCase):
    def test_knocks_header_covers_agent_and_machines(self):
        head = _header_after("function _upsertKnocks")
        self.assertGreater(len(head), P.KN_MACHINES,
                           "the script creates a knocks tab too narrow for "
                           "the columns post.py reads")
        self.assertEqual(head[P.KN_AGENT], "Agent")
        self.assertEqual(head[P.KN_MACHINES], "Machines")

    def test_relay_header_covers_the_machines_column(self):
        head = _header_after("function _upsert(")
        self.assertGreater(len(head), P.COL_MACHINES,
                           "a freshly created relay tab would be narrower "
                           "than the very next write to it")
        self.assertEqual(head[P.COL_MACHINES], "Machines")


class NothingWritesPastTheGridUnguardedTest(unittest.TestCase):
    """Both merge helpers widen before they write, so a narrow tab is slow to
    fix rather than fatal to every office's POST."""

    def _body(self, name: str) -> str:
        src = GS.read_text()
        at = src.index("function %s(" % name)
        return src[at:src.index("\n}", at)]

    def test_the_helper_exists_and_grows_the_sheet(self):
        body = self._body("_ensureCols")
        self.assertIn("getMaxColumns", body)
        self.assertIn("insertColumnsAfter", body)

    def test_both_machine_merges_widen_first(self):
        for fn in ("_mergeKnockMachine", "_mergeMachine"):
            body = self._body(fn)
            self.assertIn("_ensureCols", body,
                          "%s writes past the created header without "
                          "widening -- one narrow tab fails every POST" % fn)
            self.assertLess(body.index("_ensureCols"), body.index("getRange"),
                            "%s widens AFTER its first getRange, which is "
                            "the throw it is meant to prevent" % fn)

    def test_the_knocks_merge_backfills_the_header_names(self):
        """A tab that predates the columns never gets their names otherwise --
        the wide header is only written when the tab is created."""
        body = self._body("_mergeKnockMachine")
        self.assertIn("'Agent'", body)
        self.assertIn("'Machines'", body)


if __name__ == "__main__":
    unittest.main()
