"""A control tab that exists but nobody drains must not swallow a queued row.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.day_orchestrator.test_control_tab_liveness

WHY (Megan 2026-08-25). `--machine <name>` writes into "Mini Control - <name>",
and a name no runner polls means the row sits 'queued' forever with no error —
the failure that once stranded ten incident hand-offs for three weeks.

1839245 (8/20) added a guard, but it only refuses a tab that is NOT THERE. That
stopped NEW orphans and nothing else: an orphan created before it landed still
matches, still passes, still swallows the row. 'Mini Control - Mini' is exactly
that — `--machine "Mini"` when Lucy 1's tab is plain "Mini Control" — and Eve
lost a push_cred_file into it on 8/24, FOUR DAYS after the guard shipped. Five
days later it was still 'queued'.

THE SUBTLETY, and why the obvious test is wrong. That orphan reads
{'canceled': 10, 'queued': 4} — a human clearing rows that were never going to
run. So "any row not queued" calls it LIVE and strands the next one too. Only
`done`/`failed` are written by a poller finishing work, so only those count.

Verified against the live sheet when this was written: the three real machine
tabs answer live=True, both orphans ('Mini Control - Mini', 'Mini Control -
lucy2') answer live=False.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.day_orchestrator import mini_control as mc

HDR = ["Queued At", "Action", "Args", "By", "Status", "Result", "Finished At"]


def _sheet(rows_by_tab: dict):
    """A stand-in Sheet whose worksheet(title) yields the given rows."""
    sh = mock.Mock()

    def _ws(title):
        if title not in rows_by_tab:
            raise KeyError(title)
        w = mock.Mock()
        w.get_all_values.return_value = [HDR] + rows_by_tab[title]
        return w

    sh.worksheet.side_effect = _ws
    return sh


def _row(status):
    return ["2026-08-25T09:00:00", "ping", "", "Megan", status, "", ""]


class ProofOfLifeIsARunnerStatus(unittest.TestCase):

    def test_a_done_row_means_live(self):
        sh = _sheet({"T": [_row("queued"), _row("done")]})
        self.assertTrue(mc._tab_is_live(sh, "T"))

    def test_a_failed_row_also_means_live(self):
        """A poller that ran something and errored still proves it reads here."""
        sh = _sheet({"T": [_row("failed")]})
        self.assertTrue(mc._tab_is_live(sh, "T"))

    def test_status_matching_ignores_case_and_padding(self):
        sh = _sheet({"T": [_row("  Done ")]})
        self.assertTrue(mc._tab_is_live(sh, "T"))


class CanceledIsNotProofOfLife(unittest.TestCase):
    """THE BUG THIS TURNS ON. 'canceled' is a human tidying up, not a runner."""

    def test_the_real_orphan_shape_is_not_live(self):
        """'Mini Control - Mini' as it actually stood: 10 canceled, 4 queued."""
        sh = _sheet({"T": [_row("canceled")] * 10 + [_row("queued")] * 4})
        self.assertFalse(mc._tab_is_live(sh, "T"))

    def test_all_queued_is_not_live(self):
        sh = _sheet({"T": [_row("queued"), _row("queued")]})
        self.assertFalse(mc._tab_is_live(sh, "T"))

    def test_an_empty_tab_is_not_live(self):
        sh = _sheet({"T": []})
        self.assertFalse(mc._tab_is_live(sh, "T"))

    def test_canceled_alongside_done_is_still_live(self):
        """Cancelling rows on a REAL machine must not retire it."""
        sh = _sheet({"T": [_row("canceled"), _row("done")]})
        self.assertTrue(mc._tab_is_live(sh, "T"))


class ItFailsSafe(unittest.TestCase):
    """A false 'no' costs a clear error message. A false 'yes' costs five days
    of silence — so an unreadable tab reads as an orphan."""

    def test_an_unreadable_tab_is_not_live(self):
        sh = mock.Mock()
        sh.worksheet.side_effect = RuntimeError("network")
        self.assertFalse(mc._tab_is_live(sh, "T"))

    def test_a_short_row_does_not_crash_the_probe(self):
        """Rows written before the column set settled can be short."""
        sh = _sheet({"T": [["2026-08-25", "ping"], _row("done")]})
        self.assertTrue(mc._tab_is_live(sh, "T"))


class TheGuardChecksALoneCandidateToo(unittest.TestCase):
    """The gap 1839245 left: with exactly one matching tab it took it without
    ever asking whether anything reads it."""

    def test_the_lone_candidate_path_consults_liveness(self):
        import inspect
        src = inspect.getsource(mc)
        self.assertIn("proven = [t for t in cands if _tab_is_live(sh, t)]", src,
                      "liveness must be computed before the single-candidate branch")
        self.assertIn("if len(cands) == 1:\n            if not proven:", src,
                      "a lone candidate must be rejected when nothing drains it")

    def test_canceled_is_not_in_the_runner_statuses(self):
        self.assertNotIn("canceled", mc._RUNNER_STATUSES)
        self.assertEqual(set(mc._RUNNER_STATUSES), {"done", "failed"})


if __name__ == "__main__":
    unittest.main()
