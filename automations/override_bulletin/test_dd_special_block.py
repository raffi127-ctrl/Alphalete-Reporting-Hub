"""Tests for the 'ICD (Special Cases)' EMPTY-COLUMN guard in `dd_data.load()`.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.override_bulletin.test_dd_special_block

WHAT THESE GUARD (2026-09-10). `dd_week_roll` opens the new week column and
BLANKS it; only `dd_special_accumulate` ever fills the four adoption rows. That
Thursday the accumulate never ran — Credico's token had expired, dd_populate sat
"waiting on credico_fetch", somebody re-ran it by hand (which day_state never
sees), and the noon backstop retired the accumulate MISSED. The rows stayed
blank.

Every existing note about that block lives inside `if special_week:`, so a block
of zeros says NOTHING: no problem line, no blocking line, no hard block. The
11:20 send was correct only because somebody had typed the four figures in by
hand first. Without that, Colten's and Jairo's orgs would have gone to the whole
org $30,690.00 short and Rafael's "outside of Carlos & Colten" line that much
long, with nothing anywhere saying so.

A COPIED column was already caught. These pin the twin: a BLANK one, hard-blocked
so it cannot mail, and gated on the prior week so a genuinely quiet week is not
jammed for ever.
"""
from __future__ import annotations

import unittest

from automations.override_bulletin import dd_data as D


class _WS:
    def __init__(self, rows):
        self._rows = rows

    def get_all_values(self):
        return self._rows


def _this_week():
    return D.fmt_week(D.week_just_ended())


def _dd_tab(special_this, special_prior):
    """A minimally plausible DD tab: a header, enough paid owners and a big
    enough 'Total - Raf' to clear the CURRENT-WEEK-LOOKS-EMPTY floor, then the
    'ICD (Special Cases)' block with the two shown adoptions.

    special_this / special_prior are the strings that sit in the current and
    prior week cells of BOTH special rows ("" = the blank the roll leaves).
    """
    wk, prior = _this_week(), "8.30.26"
    hdr = ["ICD", "Active ICD", "Campaign", "ORG", "Total DD", wk, prior]
    rows = [hdr]
    for i in range(20):
        rows.append([f"Owner {i}", "YES", "ATT", "Raf", "$120,000.00",
                     "$6,000.00", "$5,900.00"])
    rows.append(["Total - Raf", "", "", "", "$2,400,000.00",
                 "$120,000.00", "$118,000.00"])
    rows.append(["", "", "", "", "", "", ""])
    rows.append(["ICD (Special Cases)", "", "", "", "", "", ""])
    rows.append(["Karrington Moody", "", "ATT", "Colten", "",
                 special_this, special_prior])
    rows.append(["Justin Fermin", "", "ATT", "Jairo", "",
                 special_this, special_prior])
    return _WS(rows)


def _load(special_this, special_prior):
    return D.load(ws=_dd_tab(special_this, special_prior),
                  tree_ws=_WS([["PODIUM LEADERS"], ["Leader", "Loc"]]),
                  aliases={}, credico=False)


class SpecialCasesBlankBlockTest(unittest.TestCase):

    def _hard(self, d):
        return " ".join(d.get("hard_block") or [])

    # ---- the 2026-09-10 incident ----

    def test_blank_special_column_hard_blocks_the_send(self):
        d = _load("", "$21,379.00")
        self.assertIn("BLANK", self._hard(d))
        self.assertIn("dd_special_accumulate", self._hard(d))

    def test_zeroed_special_column_hard_blocks_too(self):
        """The roll leaves blanks, but a half-written column reads as $0.00 —
        same wrong page."""
        d = _load("$0.00", "$21,379.00")
        self.assertIn("BLANK", self._hard(d))

    def test_the_block_names_the_week_and_the_rows(self):
        d = _load("", "$21,379.00")
        msg = self._hard(d)
        self.assertIn(_this_week(), msg)
        self.assertIn("Karrington Moody", msg)
        self.assertIn("Justin Fermin", msg)

    # ---- it must not fire on a good week, or jam a quiet one ----

    def test_a_filled_special_column_does_not_block(self):
        d = _load("$21,379.00", "$18,000.00")
        self.assertNotIn("BLANK", self._hard(d))
        self.assertEqual(d.get("hard_block"), [])

    def test_a_quiet_week_behind_a_quiet_week_lifts_the_block(self):
        """Both weeks zero = the adoptions really have stopped. Blocking that for
        ever would strand the bulletin with no override (hard_block ignores
        --force), so the prior week is the escape hatch."""
        d = _load("", "")
        self.assertNotIn("BLANK", self._hard(d))

    def test_a_copied_column_is_still_the_copied_column_message(self):
        """The pre-existing guard must keep its own wording — the blank branch is
        an elif, not a replacement."""
        d = _load("$21,379.00", "$21,379.00")
        self.assertIn("copied column", self._hard(d))


if __name__ == "__main__":
    unittest.main()
