"""Pins the SECOND gate on short knock boards (Eve, 2026-09-09: "quiero que
este doble chequeo lo repitas cada mañana").

The first gate (total_knocks.pull) re-reads a short grid and refuses a drastic
one. What it deliberately lets through is this module's beat, so these tests are
mostly about the BAND BETWEEN the two: things the first gate is right to ignore
and the second is right to mention.

Run:  python -m automations.captainship_drafts.test_knocks_audit
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.captainship_drafts import knocks_audit as A
from automations.total_knocks import pull as P


def _rec(office, rows, tt, first=None, reread=False, date="2026-09-08"):
    return {"office": office, "date": date, "rows": rows, "tt_reps": tt,
            "first_rows": first if first is not None else rows,
            "reread": reread}


class TheBandTheFirstGateLetsThrough(unittest.TestCase):
    """Every case here passes total_knocks.pull's guard — that is the point."""

    def test_a_gap_under_the_refusal_threshold_is_still_reported(self):
        """4 short of 30 clears BOTH first-gate thresholds (gap < 5, and 26 is
        well over half of 30), so nothing upstream says a word."""
        self.assertIsNone(P.short_read_error(26, 30))
        f = A.short_read_findings([_rec("Esposito", 26, 30)])
        self.assertEqual([x["kind"] for x in f], ["short"])

    def test_a_grid_holding_just_over_half_is_still_reported(self):
        """15 of 28 survives the ratio test by one rep. A board missing 13 reps
        is not a quiet day, and the first gate is not allowed to be strict
        enough to catch it without holding real emails."""
        self.assertIsNone(P.short_read_error(15, 28))
        f = A.short_read_findings([_rec("Big Office", 15, 28)])
        self.assertEqual([x["kind"] for x in f], ["short"])

    def test_an_empty_grid_is_the_first_gates_blind_spot(self):
        """`bool(n_rows)` short-circuits BOTH halves of the first gate, so an
        empty Disposition with people on the Time Tracker is never re-read and
        never refused — it reaches the email as 'no knocks recorded
        yesterday'. Nothing but this check can catch it."""
        self.assertFalse(P.disposition_read_is_short(0, 9))
        self.assertIsNone(P.short_read_error(0, 9))
        f = A.short_read_findings([_rec("Empty", 0, 9)])
        self.assertEqual([x["kind"] for x in f], ["empty-grid"])

    def test_a_recovered_reread_is_still_worth_saying(self):
        """The re-read did its job, so the board is right — but the grid WAS
        read while it was still filling, which is the exact mechanism that
        mailed 2 reps of 22. Cheap to see now, expensive to find later."""
        f = A.short_read_findings([_rec("Recovered", 22, 22, first=2,
                                        reread=True)])
        self.assertEqual([x["kind"] for x in f], ["reread"])
        self.assertIn("re-read recovered", f[0]["detail"])


class QuietDaysMustStaySilent(unittest.TestCase):
    """A check that cries every morning is a check nobody reads — and the
    corrections channel is shared with every other report."""

    def test_a_full_board_is_not_a_finding(self):
        self.assertEqual(A.short_read_findings([_rec("Chan Park", 41, 41)]), [])

    def test_a_real_zero_day_is_not_a_finding(self):
        """Nobody clocked in, nobody knocked. Sunday exists."""
        self.assertEqual(A.short_read_findings([_rec("Quiet", 0, 0)]), [])

    def test_one_walk_on_rep_is_not_a_finding(self):
        """A rep can clock in and disposition nothing. One short, no re-read,
        nothing to say."""
        self.assertEqual(A.short_read_findings([_rec("Normal", 11, 12)]), [])

    def test_more_rows_than_the_tracker_is_not_a_finding(self):
        """A rep who knocked without a Time Tracker row makes rows > tt. That
        is not a short read in any direction."""
        self.assertEqual(A.short_read_findings([_rec("Extra", 14, 12)]), [])

    def test_a_clean_run_reports_clean(self):
        self.assertIn("CLEAN", A.verdict([]))


class AnOwnerWhoVanished(unittest.TestCase):
    """The one outcome nobody would notice by reading the email: not a board,
    not a note, just gone."""

    def test_an_unaccounted_roster_owner_is_reported(self):
        f = A.coverage_findings(["Ada Lovelace", "Grace Hopper"],
                                ["Ada Lovelace"], [], captain="rafael")
        self.assertEqual([x["office"] for x in f], ["Grace Hopper"])
        self.assertEqual(f[0]["kind"], "missing")

    def test_an_owner_with_an_error_note_is_accounted_for(self):
        """An access gap is a KNOWN, visible hole — the email says so. It is
        not a vanished owner and must not be reported as one, or the 16 offices
        still waiting on ownerville Office Access would alert every morning."""
        self.assertEqual(
            A.coverage_findings(["Wayne Rude"], [],
                                ["daily_knocks:Wayne Rude"]), [])

    def test_the_incomplete_suffix_still_matches_the_roster_name(self):
        """Board labels wear ' — ⚠ INCOMPLETE: apps unavailable'; the roster
        does not. A cosmetic suffix must not read as a missing owner."""
        self.assertEqual(
            A.coverage_findings(
                ["Cody Cannon"],
                ["Cody Cannon — ⚠ INCOMPLETE: apps unavailable"], []), [])


class TheTablePrintsEveryMorning(unittest.TestCase):
    """A check whose output only exists on bad days cannot be trusted on good
    ones — the ICD-by-ICD table is the artefact, not the alert."""

    def test_a_clean_run_still_prints_every_office(self):
        lines = A.summary_lines([_rec("A Office", 12, 12),
                                 _rec("B Office", 8, 8)])
        self.assertTrue(any("A Office" in l for l in lines))
        self.assertTrue(any("B Office" in l for l in lines))

    def test_the_short_office_is_flagged_in_the_table(self):
        lines = A.summary_lines([_rec("Short One", 4, 20)])
        self.assertTrue(any("short" in l for l in lines))

    def test_no_records_says_so_rather_than_printing_nothing(self):
        self.assertIn("no pull records", A.summary_lines([])[0])


class TheAuditNeverCostsTheCapture(unittest.TestCase):
    """It runs after every board is drawn. A bug here must not be what holds
    twelve captains' reports."""

    def test_run_does_not_post_when_asked_not_to(self):
        got = A.run([_rec("Short", 2, 22)], {}, {}, logfn=lambda *_: None,
                    post=False)
        self.assertEqual([x["kind"] for x in got], ["short"])

    def test_a_reused_capture_does_not_close_an_open_incident(self):
        """A same-day re-run short-circuits on the manifest: no ownerville
        session, no records, nothing checked. It must not tick an open
        short-board thread closed — 'found nothing' there means 'looked at
        nothing'."""
        called = []
        orig = A._resolve
        try:
            A._resolve = lambda **k: called.append(k)
            A.run([], {}, {}, logfn=lambda *_: None)          # reused capture
            self.assertEqual(called, [], "closed an incident without checking")
            A.run([_rec("Fine", 9, 9)], {}, {}, logfn=lambda *_: None)
            self.assertEqual(len(called), 1, "a real clean run must close it")
        finally:
            A._resolve = orig

    def test_a_broken_roster_entry_does_not_raise(self):
        A.run([], {"rafael": None}, {"rafael": {}}, logfn=lambda *_: None,
              post=False)

    def test_capture_swallows_an_audit_that_blows_up(self):
        from automations.captainship_drafts import knocks_capture as KC
        import automations.captainship_drafts.knocks_audit as KA
        orig, printed = KA.run, []
        try:
            KA.run = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
            KC._audit({}, {})          # must not raise
        finally:
            KA.run = orig


class TheRecordsComeFromTheRealPull(unittest.TestCase):
    """The audit is only as good as its inputs, and its inputs are written by
    the two pull paths the guard already lives in."""

    def test_record_pull_round_trips(self):
        P.take_records()               # start clean
        P.audit_label("Some Office")
        P.record_pull(dt.date(2026, 9, 8), 2, 22, 22, reread=True)
        got = P.take_records()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["office"], "Some Office")
        self.assertEqual((got[0]["first_rows"], got[0]["tt_reps"],
                          got[0]["rows"]), (2, 22, 22))
        self.assertTrue(got[0]["reread"])

    def test_take_records_resets_so_a_second_capture_starts_clean(self):
        P.take_records()
        P.record_pull(dt.date(2026, 9, 8), 1, 1, 1)
        self.assertEqual(len(P.take_records()), 1)
        self.assertEqual(P.take_records(), [])

    def test_recording_never_raises_on_junk(self):
        P.take_records()
        P.record_pull(None, "x", None, 3)      # must not raise
        P.take_records()

    def test_both_pull_paths_record(self):
        """A fix that lived in only one of them would leave the other's boards
        unaudited — the same trap the first gate had to avoid."""
        import inspect
        from automations.rashad_metrics import knocks_pull as KP
        self.assertIn("record_pull",
                      inspect.getsource(KP._scrape_day_on_page))
        self.assertIn("record_pull",
                      inspect.getsource(P.pull_disposition_day))


if __name__ == "__main__":
    unittest.main(verbosity=2)
