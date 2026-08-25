"""Tests that data_gate's lagging exemption stays in step with section_pull.

WHY THIS FILE EXISTS. A section that publishes a day behind has a structurally
blank yesterday column every morning. Two modules have to agree about that and
they live far apart:

  * section_pull.ScrapeSpec.day_behind — "the PULL tolerates an empty week"
  * data_gate.LAGGING_SECTIONS         — "the GATE tolerates a blank column"

BOX got the first on 2026-08-12 and never got the second. For thirteen days the
gate read BOX's by-design blank cells as a real gap and HELD: on 2026-08-25 the
07:45 pass measured 165/172 rep cells with BOX row 153 at 4/4 blank and every
other section at 100%, which cost owner_chat_texts_board its morning send (it
signals a HOLD by exiting non-zero, so the corrections channel got a FAILED
incident) and pushed the org board email out to its 11:30 fail-open.

Nothing caught it because each half is individually correct. So the invariant
itself is the test: DAY-BEHIND IN THE PULL MUST MEAN EXEMPT IN THE GATE. The
next section that goes day-behind fails here instead of in the channel.

Run:  .venv/bin/python -m pytest automations/org_sales_board/test_data_gate_lagging.py
  or  .venv/bin/python -m unittest automations.org_sales_board.test_data_gate_lagging
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.org_sales_board import data_gate as dg
from automations.org_sales_board import section_pull as sp


YDAY = dt.date(2026, 8, 24)     # Monday — the day 8/25 held on
EARLY = dt.datetime(2026, 8, 25, 7, 45)     # the owner-chat board send
LATE = dt.datetime(2026, 8, 25, 11, 45)     # past SEND_ANYWAY_AFTER


def _section(name, missing, reps=4, row=153, col=3):
    """One coverage() row, shaped as gate() consumes it."""
    return {"row": row, "name": name, "lagging": dg._is_lagging(name),
            "col": col, "reps": reps, "expected": True,
            "filled": reps - len(missing), "missing": list(missing)}


class TheInvariant(unittest.TestCase):
    """The one rule this file is for."""

    def test_every_day_behind_spec_is_exempt_in_the_gate(self):
        for key, spec in sorted(sp.SPECS.items()):
            if not spec.day_behind:
                continue
            self.assertTrue(
                dg._is_lagging(spec.section_label),
                "section_pull.SPECS[%r] is day_behind=True but its board label "
                "%r is not matched by data_gate.LAGGING_SECTIONS %r. A "
                "day-behind section's yesterday column is blank every morning "
                "by design; leaving it out of the exemption holds the board all "
                "day and fails every report gated on it. Add it."
                % (key, spec.section_label, dg.LAGGING_SECTIONS))

    def test_box_is_the_spec_this_was_written_for(self):
        # Guards the invariant test above from passing vacuously if BOX ever
        # loses its flag without the gate being revisited.
        self.assertTrue(sp.SPECS["box"].day_behind)
        self.assertTrue(dg._is_lagging("BOX"))


class ExemptionIsNarrow(unittest.TestCase):
    """It must not turn into a blanket 'blank is fine'."""

    def test_sections_that_are_not_day_behind_are_not_exempt(self):
        for key, spec in sorted(sp.SPECS.items()):
            if spec.day_behind:
                continue
            self.assertFalse(
                dg._is_lagging(spec.section_label),
                "%r is not day_behind but the gate treats it as lagging — a "
                "real outage there would never hold the board." % key)

    def test_a_normal_section_going_blank_still_holds(self):
        secs = [_section("BOX", ["Roshan Amin Ahmad", "Carlos Hidalgo"]),
                _section("ATT NDS Team", ["Someone"], reps=10, row=120)]
        ok, why = dg._decide(secs, YDAY, now=EARLY)
        self.assertFalse(ok)
        self.assertIn("ATT NDS Team", why)
        self.assertNotIn("BOX row", why)

    def test_lagging_blank_is_named_but_does_not_hold(self):
        secs = [_section("BOX", ["Roshan Amin Ahmad", "Carlos Hidalgo",
                                 "Ryan Mcspadden", "Abel Draper"]),
                _section("Retail JE", ["Aiysha Mariano"], reps=3, row=108)]
        ok, why = dg._decide(secs, YDAY, now=EARLY)
        self.assertTrue(ok, why)
        self.assertIn("complete", why)
        # The gap is still SAID out loud, so a board that ships short says so.
        self.assertIn("BOX", why)
        self.assertIn("Retail JE", why)

    def test_a_missing_day_column_still_holds_even_for_a_lagging_section(self):
        # `col is None` = the week never rolled / headers moved. That is a
        # STRUCTURAL break, not a late publish, and the exemption must not
        # swallow it.
        s = _section("BOX", [], col=None)
        s["filled"] = 0
        ok, why = dg._decide([s], YDAY, now=EARLY)
        self.assertFalse(ok)
        self.assertIn("no 8/24 column", why)


class TheRegressionItself(unittest.TestCase):
    """2026-08-25, reproduced from the live coverage numbers in the log."""

    def _the_825_board(self):
        # Every other section was 100%; only these two were blank.
        secs = [_section("BOX", ["Roshan Amin Ahmad", "Carlos Hidalgo",
                                 "Ryan Mcspadden", "Abel Draper"]),
                _section("Retail JE", ["Aiysha Mariano", "Brandon Stallkamp",
                                       "Alex Nicholas"], reps=3, row=108)]
        secs.append(_section("ATT NDS Team", [], reps=10, row=120))
        return secs

    def test_the_745_send_now_passes(self):
        ok, why = dg._decide(self._the_825_board(), YDAY, now=EARLY)
        self.assertTrue(ok, "the 07:45 owner-chat board send must no longer "
                            "hold on BOX: %s" % why)

    def test_it_would_have_held_before_the_fix(self):
        # Same board, the old exemption list. Documents what was broken.
        old = dg.LAGGING_SECTIONS
        try:
            dg.LAGGING_SECTIONS = ("retail je",)
            secs = [_section(s["name"], s["missing"], s["reps"], s["row"])
                    for s in self._the_825_board()]
            ok, why = dg._decide(secs, YDAY, now=EARLY)
        finally:
            dg.LAGGING_SECTIONS = old
        self.assertFalse(ok)
        self.assertIn("BOX row 153: 4/4 blank", why)

    def test_the_1130_fail_open_is_untouched(self):
        old = dg.LAGGING_SECTIONS
        try:
            dg.LAGGING_SECTIONS = ("retail je",)
            secs = [_section(s["name"], s["missing"], s["reps"], s["row"])
                    for s in self._the_825_board()]
            ok, why = dg._decide(secs, YDAY, now=LATE)
        finally:
            dg.LAGGING_SECTIONS = old
        self.assertTrue(ok)
        self.assertIn("past 11:30", why)


if __name__ == "__main__":
    unittest.main()
