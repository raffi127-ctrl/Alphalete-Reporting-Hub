"""The VA compare must never decide whether the Org Sales Board posted.

WHY THIS FILE EXISTS — 2026-09-08. The tab the compare diffs against,
`tabs.ARCHIVED_VA_TAB`, has been out of circulation since 2026-07-21 and was
renamed + hidden on 08-19; `board_compare`, the 9am job that used to run it,
was retired the same day. Nobody has keyed it in seven weeks.

So a compare against it no longer measures agreement, it measures drift. That
morning it reported 28 "ICDs on the VA tab with no copy row" — every one of
them somebody we retired in August: Steve McElwee (8/20), Milan Godbolt
(8/21), Marcos Barbosa (8/27), Fernando Munoz (8/31), plus the two-week-zero
batches — and 12,995 value diffs, and marked the board INCOMPLETE.

THE PATH THAT COST THE MORNING. The 4am run passes --skip-compare, so it was
fine. But the granular "Retry failed only" button that run.py itself writes
into the failure manifest does NOT pass it. An unrelated 4am drop (that day: a
week nobody sold retail) put the button in the channel, the retry compared
against July, and a board that had just filled correctly did not post. The
retry button took the board down.

The invariants, then:
  * a retry built from THIS file's own manifest must not turn the compare on
  * a not-clean compare must never reach the failure manifest or the
    INCOMPLETE verdict

Fixing it by pointing the compare at a tab somebody actually keys is welcome;
these tests fail loudly if gating comes back without that.

Run:  .venv/bin/python -m unittest \
          automations.org_sales_board.test_compare_never_gates
"""
from __future__ import annotations

import inspect
import unittest

from automations.org_sales_board import run as board_run
from automations.org_sales_board import tabs


class TheReferenceIsAnArchive(unittest.TestCase):

    def test_prod_tab_is_the_archived_tab(self):
        # If PROD_TAB is ever repointed at a live tab, revisit every test here.
        self.assertEqual(board_run.PROD_TAB, tabs.ARCHIVED_VA_TAB)

    def test_the_archive_name_says_so(self):
        self.assertIn("ARCHIVE", tabs.ARCHIVED_VA_TAB)


class CompareIsOptInAndReportOnly(unittest.TestCase):

    @staticmethod
    def _parser_flags():
        src = inspect.getsource(board_run.main)
        return src

    def test_compare_is_off_by_default(self):
        # store_true => default False => the fill does not compare unless asked.
        parser_src = self._parser_flags()
        self.assertIn('ap.add_argument("--compare", action="store_true"',
                      parser_src)

    def test_skip_compare_is_still_accepted(self):
        # Every scheduled caller and several saved retry_args still pass it
        # (deploy/board_catchup.sh, org_board_box_repull.sh, je_sunday_catchup,
        # retail_catchup, hub_cards, schedule_config). It must not error.
        self.assertIn('"--skip-compare"', self._parser_flags())

    def test_the_gate_reads_compare_not_skip_compare(self):
        src = self._parser_flags()
        self.assertIn("and args.compare:", src)
        self.assertNotIn("not args.skip_compare", src)

    def test_compare_result_is_not_in_the_failure_manifest(self):
        # `_failed_all` is what becomes the alert's "N part(s) missing" list.
        # No compare bucket may contribute to it.
        src = self._parser_flags()
        head, _, tail = src.partition("_failed_all = (")
        body = tail.split("_rm.write_manifest")[0]
        self.assertNotIn("_compare_clean", body)
        self.assertNotIn("compare:", body)

    def test_compare_does_not_decide_the_incomplete_verdict(self):
        # The two `if (...)` guards — the manifest one and the INCOMPLETE one —
        # must not consult the compare at all.
        src = self._parser_flags()
        for guard in ("if (_skipped or _failed_prog or _failed_caps\n"
                      "                            or _missing_reps "
                      "or _dropped):",
                      "if (_skipped or _failed_prog or _failed_caps\n"
                      "                    or _missing_reps or _dropped):"):
            self.assertIn(guard, src)
        self.assertNotIn("or not _compare_clean", src)

    def test_the_dead_gating_counter_is_gone(self):
        # _compare_ndiff counted glitches+derived only, so a board held by
        # copy-missing rows announced itself as "compare: 0 cell(s) disagree
        # with the VA tab" — a headline that said nothing was wrong.
        self.assertNotIn("_compare_ndiff", inspect.getsource(board_run))


class ARetryDoesNotTurnCompareBackOn(unittest.TestCase):
    """The manifest's own retry_args are the thing that bit us."""

    @staticmethod
    def _retry_arg_shapes():
        src = inspect.getsource(board_run.main)
        block = src.split("# GRANULAR retry:")[1].split("_rm.write_manifest")[0]
        return block

    def test_no_retry_shape_passes_compare(self):
        self.assertNotIn('"--compare"', self._retry_arg_shapes())

    def test_retry_shapes_are_still_built(self):
        # Guard against the block being refactored away and the test passing
        # vacuously.
        block = self._retry_arg_shapes()
        self.assertIn('"--step", "daily"', block)
        self.assertIn('"--sections"', block)


if __name__ == "__main__":
    unittest.main()
