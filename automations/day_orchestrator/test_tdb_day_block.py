"""Texas de Brazil scores a day block found by header, at any block width.

`day_block_cols` used to scan a FIXED window: seven columns back from Roll
Call. That held while the block was `Apps Int Int Up DTV NL TK Cx Roll Call`.
The Talk-To trio made it eleven wide, and the window stopped reaching Apps /
Int / Int Up -- so 'int' fell out of the map entirely and every rep scored ZERO
for interior sales, with no error anywhere. This is the same reader that already
paid knocks as energy points when EN was renamed TK (2026-09-01), so the
regression is pinned twice: the right columns at both widths, and TK still
unmapped.
"""
import unittest

from automations.day_orchestrator import tdb_data as T


OLD = ["Apps", "Int", "Int Up", "DTV", "NL", "TK", "Cx", "Roll Call"]
NEW = ["Apps", "Int", "Int Up", "DTV", "NL", "TK",
       "Total Talk-To's", "% of TT's per knock", "AVG app per TT",
       "Cx", "Roll Call"]
LEAD = ["#", "", "Rep", "APPS", "INT", "INT UP", "DTV", "NL"]   # running block


def header_row(block):
    return LEAD + list(block)


class DayBlockWindow(unittest.TestCase):
    def cols(self, block):
        hdr = header_row(block)
        start = len(LEAD)
        rc = hdr.index("Roll Call")
        return hdr, T.day_block_cols(hdr, rc, start)

    def test_old_layout_unchanged(self):
        hdr, m = self.cols(OLD)
        self.assertEqual(hdr[m["int"]], "Int")
        self.assertEqual(hdr[m["dtv"]], "DTV")
        self.assertEqual(hdr[m["nl"]], "NL")

    def test_int_survives_the_wider_block(self):
        """The bug: 'int' used to be missing here, and missing means 0 points."""
        hdr, m = self.cols(NEW)
        self.assertIn("int", m)
        self.assertEqual(hdr[m["int"]], "Int")
        self.assertEqual(hdr[m["dtv"]], "DTV")
        self.assertEqual(hdr[m["nl"]], "NL")

    def test_tk_stays_unmapped_at_both_widths(self):
        """An unmapped header scores nothing -- never ~200 knocks as energy."""
        for block in (OLD, NEW):
            _, m = self.cols(block)
            self.assertNotIn("energy", m)

    def test_running_block_is_never_scanned(self):
        """Without a start the window could reach back into RUNNING WEEK and
        score its INT as the day's."""
        hdr, m = self.cols(NEW)
        self.assertGreaterEqual(m["int"], len(LEAD))

    def test_energy_era_block_still_scores(self):
        hdr = header_row(["Apps", "Int", "Int Up", "DTV", "NL", "EN", "Cx", "Roll Call"])
        m = T.day_block_cols(hdr, hdr.index("Roll Call"), len(LEAD))
        self.assertEqual(hdr[m["energy"]], "EN")

    def test_no_recognisable_header_falls_back_to_offsets(self):
        hdr = ["", "", "", "", "", "", "", "Roll Call"]
        m = T.day_block_cols(hdr, 7, 0)
        self.assertEqual(m["int"], 7 - T.INT_OFF)

    def test_start_is_optional_for_old_callers(self):
        hdr = header_row(OLD)
        self.assertEqual(T.day_block_cols(hdr, hdr.index("Roll Call")),
                         T.day_block_cols(hdr, hdr.index("Roll Call"), len(LEAD)))


if __name__ == "__main__":
    unittest.main()
