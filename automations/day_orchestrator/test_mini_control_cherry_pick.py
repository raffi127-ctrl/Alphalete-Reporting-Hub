"""cherry_pick takes one upstream commit, and never strands the runner.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.day_orchestrator.test_mini_control_cherry_pick

WHY (2026-08-31). The 3am AppStream false-alarm was fixed in 72d266b at 08:09,
but Lucy 1 and Lucy 3 sat 20 commits behind on other sessions' in-flight work.
`update` would have shipped all of it mid-day to get the one fix, and SSH — the
usual escape hatch — is refused by Lucy 3, which has Remote Login off. So there
was no route to put one commit on one runner.

The danger the action has to survive is not the pick, it is the DAY AFTER: a
cherry-pick leaves the branch ahead of origin/main, `pull --ff-only` cannot
fast-forward across divergence, and a runner that silently stops taking deploys
is the 2026-07-15 Lucy 2 stranding wearing a different hat. These tests pin both
halves — the guard that only upstream commits may be picked, and the `update`
reconciliation that clears the divergence without eating anyone's work.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from automations.day_orchestrator import mini_control as mc


def _git(cwd, *a):
    p = subprocess.run(["git", "-C", str(cwd), *a],
                       capture_output=True, text=True)
    return p.returncode == 0, (p.stdout or p.stderr).strip()


class CherryPickTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)

        self.origin = root / "origin.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.origin)],
                       capture_output=True, check=True)

        # The "laptop" — where commits are authored and pushed.
        self.work = root / "work"
        subprocess.run(["git", "clone", str(self.origin), str(self.work)],
                       capture_output=True, check=True)
        for k, v in (("user.email", "t@t.t"), ("user.name", "t")):
            _git(self.work, "config", k, v)
        self.base = self._commit(self.work, "base.txt", "base", "base commit")
        _git(self.work, "push", "-u", "origin", "main")

        # The "runner" — clones at base, i.e. behind.
        self.runner = root / "runner"
        subprocess.run(["git", "clone", str(self.origin), str(self.runner)],
                       capture_output=True, check=True)
        for k, v in (("user.email", "r@r.r"), ("user.name", "r")):
            _git(self.runner, "config", k, v)

        # Two more commits land upstream: the fix we want, and unrelated churn
        # we do NOT want — the whole point of picking instead of pulling.
        self.fix = self._commit(self.work, "watch.py", "fixed", "the fix")
        self.churn = self._commit(self.work, "other.py", "churn", "unrelated churn")
        _git(self.work, "push", "origin", "main")

        real_root = mc.REPO_ROOT
        mc.REPO_ROOT = self.runner
        self.addCleanup(setattr, mc, "REPO_ROOT", real_root)

    def _commit(self, repo, name, body, msg):
        (Path(repo) / name).write_text(body)
        _git(repo, "add", name)
        _git(repo, "commit", "-m", msg)
        return _git(repo, "rev-parse", "HEAD")[1]

    def _head_subject(self):
        return _git(self.runner, "log", "-1", "--format=%s")[1]

    def _has(self, sha):
        return _git(self.runner, "merge-base", "--is-ancestor", sha, "HEAD")[0]

    # --- the pick ------------------------------------------------------------

    def test_picks_the_fix_and_leaves_the_churn_behind(self):
        ok, msg = mc._action_cherry_pick(self.fix)
        self.assertTrue(ok, msg)
        self.assertTrue(self._has(self.fix) is False)  # not the ORIGINAL sha…
        self.assertEqual((self.runner / "watch.py").read_text(), "fixed")
        self.assertFalse((self.runner / "other.py").exists(),
                         "picking must not drag in unrelated upstream churn")
        self.assertIn("watch.py", msg)

    def test_refuses_a_commit_not_yet_on_origin_main(self):
        local = self._commit(self.work, "wip.py", "wip", "unpushed work")
        _git(self.runner, "fetch", str(self.work), local)
        ok, msg = mc._action_cherry_pick(local)
        self.assertFalse(ok)
        self.assertIn("not on origin/main", msg)
        self.assertFalse((self.runner / "wip.py").exists())

    def test_already_present_is_a_no_op_not_an_error(self):
        ok, msg = mc._action_cherry_pick(self.base)
        self.assertTrue(ok, msg)
        self.assertIn("nothing to do", msg)

    def test_refuses_when_tracked_edits_would_be_swept_in(self):
        (self.runner / "base.txt").write_text("someone was editing this")
        ok, msg = mc._action_cherry_pick(self.fix)
        self.assertFalse(ok)
        self.assertIn("git_stash", msg)
        self.assertEqual((self.runner / "base.txt").read_text(),
                         "someone was editing this", "must not touch their edit")

    def test_a_conflicting_pick_aborts_and_leaves_a_clean_tree(self):
        # Same file, different content, committed locally first → conflict.
        self._commit(self.runner, "watch.py", "local version", "local edit")
        ok, msg = mc._action_cherry_pick(self.fix)
        self.assertFalse(ok)
        self.assertIn("aborted", msg.lower())
        unmerged = _git(self.runner, "diff", "--name-only", "--diff-filter=U")[1]
        self.assertEqual(unmerged, "", "an unmerged tree kills the 4am batch")
        self.assertEqual((self.runner / "watch.py").read_text(), "local version")

    # --- the day after: update must still work -------------------------------

    def test_update_reconciles_the_cherry_picked_runner(self):
        """The real trap: after a pick, `pull --ff-only` cannot fast-forward."""
        ok, msg = mc._action_cherry_pick(self.fix)
        self.assertTrue(ok, msg)
        ahead = _git(self.runner, "rev-list", "--count", "origin/main..HEAD")[1]
        self.assertEqual(ahead, "1", "the pick should leave the runner diverged")

        ok, msg = mc._action_update("")
        self.assertTrue(ok, f"update must survive a cherry-picked runner: {msg}")
        self.assertIn("reconciled", msg)
        # Now on real origin/main: both upstream commits, no leftover duplicate.
        self.assertTrue(self._has(self.fix))
        self.assertTrue(self._has(self.churn))
        self.assertEqual(
            _git(self.runner, "rev-list", "--count", "origin/main..HEAD")[1], "0")

    def test_update_refuses_to_discard_real_local_work(self):
        """A local-only commit that is NOT a cherry-pick is somebody's work."""
        self._commit(self.runner, "theirs.py", "mine", "real local work")
        ok, msg = mc._action_update("")
        self.assertFalse(ok)
        self.assertIn("REFUSING", msg)
        self.assertIn("real local work", msg)
        self.assertTrue((self.runner / "theirs.py").exists())

    def test_clean_runner_is_untouched_by_the_new_check(self):
        """No local-only commits → the normal deploy path, unchanged."""
        ok, msg = mc._action_update("")
        self.assertTrue(ok, msg)
        self.assertNotIn("reconciled", msg)
        self.assertTrue(self._has(self.churn))


class LocalOnlyDuplicatesTest(unittest.TestCase):
    """The predicate `update` leans on, driven directly."""

    def _fake_git(self, local, bodies, upstream):
        def g(*a, **kw):
            if a[0] == "rev-list":
                return True, "\n".join(local)
            if a[0] == "log":
                return True, bodies.get(a[-1], "")
            if a[0] == "merge-base":
                return a[2] in upstream, ""
            return True, ""
        return g

    def test_no_local_commits_is_the_quiet_yes(self):
        dupes, local, detail = mc._local_only_upstream_duplicates(
            self._fake_git([], {}, set()))
        self.assertTrue(dupes)
        self.assertEqual(local, [])

    def test_a_verified_cherry_pick_is_a_duplicate(self):
        g = self._fake_git(
            ["aaa"], {"aaa": "the fix\n\n(cherry picked from commit beef123)"},
            {"beef123"})
        dupes, local, _ = mc._local_only_upstream_duplicates(g)
        self.assertTrue(dupes)
        self.assertEqual(local, ["aaa"])

    def test_a_trailer_naming_a_commit_not_upstream_is_not_trusted(self):
        """The trailer is a claim; only origin/main settles it."""
        g = self._fake_git(
            ["aaa"], {"aaa": "x\n\n(cherry picked from commit deadbee)"}, set())
        dupes, _, detail = mc._local_only_upstream_duplicates(g)
        self.assertFalse(dupes)
        self.assertIn("not on main", detail)

    def test_a_plain_local_commit_is_real_work(self):
        g = self._fake_git(["aaa"], {"aaa": "somebody's hotfix"}, set())
        dupes, _, detail = mc._local_only_upstream_duplicates(g)
        self.assertFalse(dupes)


if __name__ == "__main__":
    unittest.main()
