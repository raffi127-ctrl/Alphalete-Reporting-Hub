"""One ownerville session per machine — and a Chrome profile is not a session.

Every process here restores the SAME storage_state, so they are all the same
ownerville SERVER session however many Chrome profiles they launched, and
impersonation is a property of that session: whoever calls confirmImpersonate
last wins for everyone, and _exit_impersonation is just as loud, because it
drops the shared session back to MASTER.

Measured on Lucy 1 2026-09-02, four reads of Khalil's 09/01 inside ONE
impersonation while gap_alerts ran its own offices in its OWN profile:

    7 reps (KHALIL MANSOUR) -> 7 -> 39 (Chan Park) -> 39

Nothing raised, and the board went out titled KHALIL MANSOUR carrying Raf's 38
reps. The guard that should have caught it was `proc_guard` plus a hand-kept
list of module names in knocks_request, and it protected the shared PROFILE —
so gap_alerts was exempt for having its own profile, which is exactly backwards.

So the lock lives in ownerville_session() itself, where no caller can be
forgotten, and profile_dir buys no exemption from it.

Offline: the lock file is redirected to a temp path so a test run on a live
runner cannot take the session away from a real report.
"""
import inspect
import os
import tempfile
import unittest
from pathlib import Path

from automations.shared import tableau_patchright as tp

try:
    import fcntl as _fcntl
except ImportError:            # Windows — no flock, and the code says so
    _fcntl = None


class _TempLock(unittest.TestCase):
    """Point the lock at a throwaway file for the duration of one test."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self._saved = tp.OWNERVILLE_SESSION_LOCK
        tp.OWNERVILLE_SESSION_LOCK = Path(self._dir.name) / "ov.lock"
        tp._OV_LOCK_DEPTH, tp._OV_LOCK_FD = 0, None

    def tearDown(self):
        tp.OWNERVILLE_SESSION_LOCK = self._saved
        tp._OV_LOCK_DEPTH, tp._OV_LOCK_FD = 0, None
        self._dir.cleanup()


class TheLockExcludes(_TempLock):
    @unittest.skipIf(_fcntl is None, "no flock on this platform")
    def test_a_second_holder_is_refused_not_queued_forever(self):
        """Another process has it: this run refuses. Proceeding is the bug —
        two runs on one session read each other's offices and neither can
        tell, which is worse than no board because it looks like a board."""
        other = os.open(str(tp.OWNERVILLE_SESSION_LOCK),
                        os.O_CREAT | os.O_RDWR, 0o644)
        _fcntl.flock(other, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        try:
            with self.assertRaises(tp.OwnervilleBusy):
                tp._acquire_session_lock(wait_s=0, verbose=False, label="t")
        finally:
            _fcntl.flock(other, _fcntl.LOCK_UN)
            os.close(other)

    @unittest.skipIf(_fcntl is None, "no flock on this platform")
    def test_it_is_free_again_once_released(self):
        fd = tp._acquire_session_lock(wait_s=1, verbose=False, label="t")
        tp._release_session_lock(fd)
        again = tp._acquire_session_lock(wait_s=1, verbose=False, label="t")
        self.assertIsNotNone(again)
        tp._release_session_lock(again)

    @unittest.skipIf(_fcntl is None, "no flock on this platform")
    def test_the_holder_is_named_so_waiting_is_explicable(self):
        self.assertEqual(tp.ownerville_session_holder(), "")
        fd = tp._acquire_session_lock(wait_s=1, verbose=False, label="t")
        self.assertEqual(tp.ownerville_session_holder(), "this run")
        tp._release_session_lock(fd)


class TheLockIsReentrant(_TempLock):
    """flock is keyed to the open file DESCRIPTION, so a second os.open() of
    the same file in the SAME process blocks on the first — one run that nests
    two ownerville_session() calls would deadlock against itself, forever,
    logging that "another run" holds it. Nothing nests today; a deadlock is
    still not the thing to leave lying around for whoever does it next."""

    @unittest.skipIf(_fcntl is None, "no flock on this platform")
    def test_nesting_does_not_deadlock(self):
        outer = tp._acquire_session_lock(wait_s=1, verbose=False, label="a")
        inner = tp._acquire_session_lock(wait_s=1, verbose=False, label="b")
        self.assertEqual(outer, inner)
        self.assertEqual(tp._OV_LOCK_DEPTH, 2)

        tp._release_session_lock(inner)
        self.assertEqual(tp._OV_LOCK_DEPTH, 1, "the inner release let go of a "
                                               "lock the outer still needs")
        tp._release_session_lock(outer)
        self.assertEqual(tp._OV_LOCK_DEPTH, 0)


class EveryCallerIsCovered(unittest.TestCase):
    def test_ownerville_session_locks_by_default(self):
        """Opt-OUT, never opt-in. A list of who should be serialised is what
        failed; the default is what protects the caller nobody remembered."""
        sig = inspect.signature(tp.ownerville_session.__wrapped__
                                if hasattr(tp.ownerville_session, "__wrapped__")
                                else tp.ownerville_session)
        self.assertIs(sig.parameters["session_lock"].default, True)

    def test_a_private_profile_is_not_an_exemption(self):
        """profile_dir and session_lock are independent parameters. The moment
        one implies the other, gap_alerts is exempt again."""
        sig = inspect.signature(tp.ownerville_session.__wrapped__
                                if hasattr(tp.ownerville_session, "__wrapped__")
                                else tp.ownerville_session)
        self.assertIn("profile_dir", sig.parameters)
        self.assertIn("session_lock", sig.parameters)
        self.assertIsNone(sig.parameters["profile_dir"].default)


class ShortCadenceJobsSkipRatherThanQueue(unittest.TestCase):
    def test_gap_alerts_cannot_queue_past_its_own_cadence(self):
        """It runs every 5 minutes; the captainship build holds ownerville for
        ~2h. Queueing behind that stacks ticks that all fire at once against a
        clock that has moved on."""
        from automations.gap_alerts import config as C
        self.assertLessEqual(C.OWNERVILLE_SESSION_WAIT_S,
                             C.MIN_SEND_GAP_MINUTES * 60)


if __name__ == "__main__":
    unittest.main()
