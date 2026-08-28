"""What `unstick_profile` is allowed to kill.

This one gets a test because the failure mode is expensive in BOTH directions:
too timid and a browser report waits out the 30-minute profile lock and dies at
its timeout (2026-08-19 — four straight tableau_screenshots runs, Country
Trackers in no channel all morning); too eager and it kills the session holder
or a report that is legitimately mid-run, turning one late report into several
broken ones. The rules that keep it honest are the `--user-data-dir=` basename
match and the PPID-1 orphan filter, so those are what's pinned here.

    python -m unittest automations.day_orchestrator.test_chrome_guard
"""
from __future__ import annotations

import types
import unittest
from unittest import mock

from automations.day_orchestrator import chrome_guard

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
UPLOADED = "/Users/alphalete/recruiting-report/automations/uploaded"

# pid, ppid, command — one line each, exactly how `ps -Ao pid=,ppid=,command=`
# lays it out on the mini.
PS_LINES = [
    # the orphan we want: our profile, parent gone (reparented to launchd)
    f"  501     1 {CHROME} --user-data-dir={UPLOADED}/.browser_profile --remote-debugging-port=9246",
    # same profile but its Python/driver parent is alive — a live report
    f"  502  4711 {CHROME} --user-data-dir={UPLOADED}/.browser_profile --remote-debugging-port=9246",
    # the session holder: a DIFFERENT profile whose name merely starts the same
    f"  503     1 {CHROME} --user-data-dir={UPLOADED}/.browser_profile_holder",
    # AppStream's own profile
    f"  504     1 {CHROME} --user-data-dir={UPLOADED}/.appstream_profile",
    # a renderer child of the orphan — killing the browser takes it along
    f"  505   501 {CHROME} --type=renderer --user-data-dir={UPLOADED}/.browser_profile",
    # a person's Chrome
    "  506     1 " + CHROME,
]


def _fake_ps(lines):
    def run(cmd, **kw):
        return types.SimpleNamespace(stdout="\n".join(lines) + "\n", returncode=0)
    return run


class ProfileHolderPids(unittest.TestCase):
    def setUp(self):
        self.plat = mock.patch.object(chrome_guard.sys, "platform", "darwin")
        self.plat.start()
        self.addCleanup(self.plat.stop)
        self.ps = mock.patch.object(chrome_guard.subprocess, "run",
                                    _fake_ps(PS_LINES))
        self.ps.start()
        self.addCleanup(self.ps.stop)

    def test_orphan_only_is_the_default(self):
        """Only the parentless Chrome on OUR profile — not the live one."""
        self.assertEqual(chrome_guard.profile_holder_pids(), [501])

    def test_without_the_orphan_filter_both_holders_show(self):
        self.assertEqual(
            chrome_guard.profile_holder_pids(orphans_only=False), [501, 502])

    def test_holder_profile_is_not_a_substring_match(self):
        """'.browser_profile' must never sweep up '.browser_profile_holder' —
        killing the holder logs every report out of Tableau."""
        self.assertNotIn(503, chrome_guard.profile_holder_pids(orphans_only=False))
        self.assertEqual(
            chrome_guard.profile_holder_pids(".browser_profile_holder"), [503])

    def test_renderers_and_human_chrome_are_left_alone(self):
        pids = chrome_guard.profile_holder_pids(orphans_only=False)
        self.assertNotIn(505, pids)   # --type=renderer
        self.assertNotIn(506, pids)   # no --user-data-dir at all

    def test_not_macos_is_a_no_op(self):
        with mock.patch.object(chrome_guard.sys, "platform", "win32"):
            self.assertEqual(chrome_guard.profile_holder_pids(), [])


class UnstickProfile(unittest.TestCase):
    def setUp(self):
        self.plat = mock.patch.object(chrome_guard.sys, "platform", "darwin")
        self.plat.start()
        self.addCleanup(self.plat.stop)
        self.sleep = mock.patch.object(chrome_guard.time, "sleep", lambda *_: None)
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def test_nothing_to_do_kills_nothing(self):
        with mock.patch.object(chrome_guard.subprocess, "run", _fake_ps([])), \
                mock.patch.object(chrome_guard.os, "kill") as kill:
            self.assertEqual(chrome_guard.unstick_profile(verbose=False), [])
            kill.assert_not_called()

    def test_term_then_kill_only_what_survived(self):
        """SIGTERM the orphan; SIGKILL only if it's still there afterwards."""
        with mock.patch.object(chrome_guard.subprocess, "run", _fake_ps(PS_LINES)), \
                mock.patch.object(chrome_guard.os, "kill") as kill:
            freed = chrome_guard.unstick_profile(verbose=False)
        self.assertEqual(freed, [501])
        sent = [c.args for c in kill.call_args_list]
        self.assertEqual(sent[0], (501, chrome_guard.signal.SIGTERM))
        # Nothing but the orphan is ever signalled, whichever signal it is.
        self.assertTrue(all(pid == 501 for pid, _ in sent))
        # ps still reports it (the fake never changes), so a SIGKILL follows —
        # only assertable where SIGKILL exists (this test also runs on Windows,
        # where the second os.kill raises AttributeError and is swallowed).
        sigkill = getattr(chrome_guard.signal, "SIGKILL", None)
        if sigkill is not None:
            self.assertEqual(sent[1], (501, sigkill))

    def test_a_dead_pid_does_not_raise(self):
        with mock.patch.object(chrome_guard.subprocess, "run", _fake_ps(PS_LINES)), \
                mock.patch.object(chrome_guard.os, "kill",
                                  side_effect=ProcessLookupError):
            self.assertEqual(chrome_guard.unstick_profile(verbose=False), [501])


class OurOwnChromeIsNeverStray(unittest.TestCase):
    """2026-08-28: `close_stray_chrome` only knew ONE family of our browsers.

    The CDP downloaders (vantura_churn / att_order_log / b2b_metrics on port
    9246, resume_pushing on 9245, apex_payroll) run the real Google Chrome out
    of /tmp/*_cdp_profile with no `--type=` — indistinguishable from a person's
    Chrome under the old `automations/uploaded` test, so this guard killed them
    mid-pull. They serialise among themselves on cdp_pull._cdp_lock, but the
    guard is not one of them and never takes it: a `lucy rerun` of any Tableau
    report ran this pre-flight and took out whatever was capturing, which
    surfaced as `TargetClosedError` and read like a broken Tableau view.
    """

    CDP_LINES = [
        # port 9246 — vantura_churn / att_order_log / b2b_metrics
        f"  601     1 {CHROME} --user-data-dir=/tmp/vantura_cdp_profile "
        f"--remote-debugging-port=9246",
        # port 9245 — resume_pushing
        f"  602     1 {CHROME} --user-data-dir=/tmp/rp_cdp_profile "
        f"--remote-debugging-port=9245",
        # apex_payroll
        f"  603     1 {CHROME} --user-data-dir=/tmp/apex_cdp_profile",
        # a person's Chrome — still stray, still closed
        "  604     1 " + CHROME,
    ]

    def setUp(self):
        self.plat = mock.patch.object(chrome_guard.sys, "platform", "darwin")
        self.plat.start()
        self.addCleanup(self.plat.stop)
        self.ps = mock.patch.object(chrome_guard.subprocess, "run",
                                    _fake_ps(self.CDP_LINES))
        self.ps.start()
        self.addCleanup(self.ps.stop)

    def test_cdp_downloaders_are_not_stray_human_chrome(self):
        self.assertEqual(chrome_guard._stray_human_chrome_pids(), [604])

    def test_a_real_human_chrome_is_still_closed(self):
        """The guard must not go blind — the 2026-07-01 failure it exists for
        (a person's Chrome adopting our launches) has to stay covered."""
        with mock.patch.object(chrome_guard.os, "kill") as k:
            with mock.patch.object(chrome_guard.time, "sleep"):
                acted = chrome_guard.close_stray_chrome(verbose=False)
        self.assertEqual(acted, [604])
        self.assertTrue(k.called)

    def test_uploaded_profiles_stay_protected(self):
        self.assertFalse(chrome_guard._is_ours(CHROME))
        self.assertTrue(chrome_guard._is_ours(
            f"{CHROME} --user-data-dir={UPLOADED}/.browser_profile"))

    def test_remote_debugging_port_alone_is_enough(self):
        """The backstop: a CDP profile path nobody anticipated is still ours,
        because a person's Chrome never carries this flag."""
        self.assertTrue(chrome_guard._is_ours(
            f"{CHROME} --user-data-dir=/tmp/some_new_puller "
            f"--remote-debugging-port=9299"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
