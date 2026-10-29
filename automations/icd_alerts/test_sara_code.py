"""The office Mac clears SaraPlus's code screen with Lucy 1's code (sara_code).

What must hold: it waits for the answer and no longer; "none" and an old relay
stop it at once; any failure files the SAME signin-saraplus fault the sweep
used to file, so nobody loses the DM; and it is not retried every sweep.
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import relay as R
from automations.icd_alerts import sara_code as SC

SINCE = dt.datetime(2026, 10, 29, 10, 2, 11).astimezone()


class Clock:
    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


def answers(*statuses):
    seq = list(statuses)

    def poll(since, office_key=""):
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return poll


class FromTheRelay(unittest.TestCase):
    def _get(self, poll, request_ok=True, wait_s=120):
        clock = Clock()
        with mock.patch.object(R, "request_code", return_value=request_ok), \
             mock.patch.object(R, "poll_code", side_effect=poll):
            return SC.code_from_relay(SINCE, wait_s=wait_s, poll_s=15,
                                      sleep=clock.sleep, clock=clock.time,
                                      log=lambda *_: None)

    def test_waits_until_the_code_is_ready(self):
        poll = answers({"status": "waiting"}, {"status": "waiting"},
                       {"status": "ready", "code": "482913"})
        self.assertEqual(self._get(poll), "482913")

    def test_none_stops_at_once(self):
        with self.assertRaises(SC.NoCode):
            self._get(answers({"status": "none"}))

    def test_an_old_relay_stops_at_once(self):
        with self.assertRaises(SC.NoCode):
            self._get(answers({"status": "unsupported", "error": "bad day"}))

    def test_gives_up_at_the_deadline(self):
        with self.assertRaises(SC.NoCode):
            self._get(answers({"status": "waiting"}), wait_s=60)

    def test_a_request_the_relay_did_not_take_is_not_waited_on(self):
        with self.assertRaises(SC.NoCode):
            self._get(answers({"status": "ready", "code": "1"}), request_ok=False)


class FallsBackToTheOldPath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        for target, path in ((SC, "STAMP_PATH"),):
            p = mock.patch.object(target, path, d / "stamp.txt")
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(SC.C, "SARA_SIGNIN_LOCK", d / "lock")
        p.start()
        self.addCleanup(p.stop)
        self.filed = []
        p = mock.patch.object(R, "report_fault",
                              side_effect=lambda stage, *a, **k: self.filed.append(stage) or True)
        p.start()
        self.addCleanup(p.stop)
        from automations.icd_alerts import sara_read as SR
        for name in ("signin_in_progress",):
            p = mock.patch.object(SR, name, return_value=False)
            p.start()
            self.addCleanup(p.stop)
        self.SR = SR

    def test_a_failure_files_the_same_signin_fault(self):
        def attempt(office_key="", log=print):
            raise SC.NoCode("no SaraPlus code forward is set up for this office")
        with mock.patch("automations.icd_alerts.autoprompt.offer") as offer:
            rc = SC.run("luke", log=lambda *_: None, attempt=attempt)
        self.assertEqual(rc, 1)
        self.assertIn("signin-saraplus", self.filed)
        offer.assert_called_once()
        self.assertFalse(SC.C.SARA_SIGNIN_LOCK.exists(), "lock released")

    def test_success_hands_the_session_over_and_lifts_the_hold(self):
        with mock.patch.object(self.SR, "_remember_session") as rem, \
             mock.patch.object(self.SR, "clear_sara_hold") as clear:
            rc = SC.run("luke", log=lambda *_: None,
                        attempt=lambda office_key="", log=print: "https://x/e/(S(a))/")
        self.assertEqual(rc, 0)
        rem.assert_called_once_with("https://x/e/(S(a))/")
        clear.assert_called_once()
        self.assertNotIn("signin-saraplus", self.filed)

    def test_not_tried_again_every_sweep(self):
        SC._stamp()
        self.assertTrue(SC.recently_tried())
        later = dt.datetime.now() + dt.timedelta(minutes=SC.RETRY_AFTER_MINUTES + 1)
        self.assertFalse(SC.recently_tried(later))


class PollWording(unittest.TestCase):
    def test_an_old_relay_reads_as_unsupported(self):
        with mock.patch.object(R, "_endpoint", return_value={
                "office_key": "luke", "relay_key": "k", "relay_url": "u"}), \
             mock.patch.object(R, "_post", return_value='{"ok": false, "error": "bad day"}'):
            self.assertEqual(R.poll_code(SINCE)["status"], R.CODE_UNSUPPORTED)

    def test_a_network_blip_is_waiting(self):
        with mock.patch.object(R, "_endpoint", side_effect=OSError("down")):
            self.assertEqual(R.poll_code(SINCE)["status"], R.CODE_WAITING)

    def test_ready_carries_the_code(self):
        with mock.patch.object(R, "_endpoint", return_value={
                "office_key": "luke", "relay_key": "k", "relay_url": "u"}), \
             mock.patch.object(R, "_post",
                               return_value='{"ok": true, "status": "ready", "code": "482913"}'):
            self.assertEqual(R.poll_code(SINCE), {"status": "ready", "code": "482913"})


if __name__ == "__main__":
    unittest.main()
