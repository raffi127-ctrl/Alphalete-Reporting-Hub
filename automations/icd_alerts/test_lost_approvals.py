"""'Could not read' must never be announced as 'every office is switched off'.

2026-09-18, 10:02. The ops room got:

    An office was switched ON and is now switched OFF.
    aya - lost: board ... ryan - lost: board      (all nine)
    This is not an office waiting for approval - it had one and it is gone.
    Nothing posts for them until it is put back.

Every approval was intact. Nothing had stopped; Ryan's boards posted normally
an hour later. What happened is that each approved_* reader answers a failed
Sheets read with {} -- correct for a poster, where "I could not check" must
never post to a room nobody approved -- and the lost-approval detector
compared that {} against the stored snapshot.

It then WROTE the empty state back, so the next run would have believed it.

Two guards, because the first one can only cover the failure it can see:
  * a read that did not return says so, and the detector stays quiet
  * every office losing everything at once is one thing wrong on our side,
    not nine independent regressions -- so it is never announced either way
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from automations.icd_alerts import post as P


class _Sheet:
    def __init__(self, rows, boom=False):
        self._rows, self._boom = rows, boom

    def get_all_values(self):
        if self._boom:
            raise RuntimeError("429 rate limited")
        return self._rows


class _Book:
    def __init__(self, sheet):
        self._s = sheet

    def worksheet(self, _name):
        return self._s


def _row(key, board=True, alerts=True):
    r = [""] * 17
    r[P.CH_OFFICE] = key
    if board:
        r[P.CH_KN_APPROVED] = "TRUE"
        r[P.CH_KN_APPROVED_JSON] = json.dumps([{"channel_id": "C1"}])
    if alerts:
        r[P.CH_APPROVED] = "TRUE"
        r[P.CH_APPROVED_JSON] = json.dumps(["C1"])
    return r


HEAD = [["Office"] + [""] * 16]


class AFailedReadIsNotAnEmptyRosterTest(unittest.TestCase):
    def test_read_failure_reports_not_ok(self):
        ok, now = P._approvals_now(_Book(_Sheet([], boom=True)))
        self.assertFalse(ok)
        self.assertEqual(now, {})

    def test_a_good_read_reports_ok(self):
        ok, now = P._approvals_now(_Book(_Sheet(HEAD + [_row("kash")])))
        self.assertTrue(ok)
        self.assertEqual(now["kash"], {"board", "alerts"})

    def test_a_flag_without_json_is_not_an_approval(self):
        r = [""] * 17
        r[P.CH_OFFICE] = "kash"
        r[P.CH_KN_APPROVED] = "TRUE"      # but no JSON beside it
        ok, now = P._approvals_now(_Book(_Sheet(HEAD + [r])))
        self.assertTrue(ok)
        self.assertNotIn("kash", now)


class NothingIsAnnouncedOnAFailedReadTest(unittest.TestCase):
    def test_silent_when_the_read_failed(self):
        with mock.patch.object(P, "_approvals_now", return_value=(False, {})):
            said = P.warn_lost_approvals(send=False, log=lambda *_a: None)
        self.assertEqual(said, [])

    def test_the_snapshot_is_not_overwritten_on_a_failed_read(self):
        """Writing the empty state is what would make the NEXT run believe
        it -- the false alarm teaching itself."""
        import tempfile, pathlib as _pl
        with tempfile.TemporaryDirectory() as tmp:
            snap = _pl.Path(tmp) / "approvals.json"
            snap.write_text(json.dumps({"kash": ["board"]}))
            with mock.patch.object(P, "APPROVALS_PATH", snap), \
                 mock.patch.object(P, "_approvals_now", return_value=(False, {})):
                P.warn_lost_approvals(send=False, log=lambda *_a: None)
            self.assertEqual(json.loads(snap.read_text()), {"kash": ["board"]},
                             "the snapshot was overwritten with the empty read")

    def test_everything_vanishing_at_once_is_not_announced(self):
        """Nine offices do not lose every approval in the same tick."""
        before = {"a": ["board"], "b": ["board"], "c": ["board"]}
        import tempfile, pathlib as _pl
        with tempfile.TemporaryDirectory() as tmp:
            snap = _pl.Path(tmp) / "approvals.json"
            snap.write_text(json.dumps(before))
            with mock.patch.object(P, "APPROVALS_PATH", snap), \
                 mock.patch.object(P, "_approvals_now", return_value=(True, {})):
                said = P.warn_lost_approvals(send=False, log=lambda *_a: None)
        self.assertEqual(said, [])

    def test_two_offices_losing_everything_is_still_reported(self):
        """The wholesale guard needs THREE. With one or two offices, "all of
        them" and "the only one" are the same sentence, and suppressing that
        would hide the single-office regression this was written for."""
        import tempfile, pathlib as _pl
        before = {"a": ["board"], "b": ["board"]}
        with tempfile.TemporaryDirectory() as tmp:
            snap = _pl.Path(tmp) / "approvals.json"
            snap.write_text(json.dumps(before))
            with mock.patch.object(P, "APPROVALS_PATH", snap), \
                 mock.patch.object(P, "_approvals_now", return_value=(True, {})):
                said = P.warn_lost_approvals(send=False, log=lambda *_a: None)
        self.assertEqual(len(said), 2)

    def test_ONE_office_losing_its_board_is_still_reported(self):
        """The real regression this exists to catch must survive the guards."""
        before = {"a": ["board"], "b": ["board"]}
        now = {"b": {"board"}}
        import tempfile, pathlib as _pl
        with tempfile.TemporaryDirectory() as tmp:
            snap = _pl.Path(tmp) / "approvals.json"
            snap.write_text(json.dumps(before))
            with mock.patch.object(P, "APPROVALS_PATH", snap), \
                 mock.patch.object(P, "_approvals_now", return_value=(True, now)):
                said = P.warn_lost_approvals(send=False, log=lambda *_a: None)
        self.assertEqual(len(said), 1)
        self.assertIn("a", said[0])


if __name__ == "__main__":
    unittest.main()
