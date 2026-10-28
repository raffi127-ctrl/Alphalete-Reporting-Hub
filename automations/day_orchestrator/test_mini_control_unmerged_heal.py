"""`update` heals an autostash clash instead of stranding the runner, and
git_status names a half-merged file (2026-10-28: the mini and Lucy 3 each sat
with `UU office-mapping*.json`, every later update died at `checkout main`, and
git_status said "nothing blocking a pull"). Local temp repos only — no network."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from automations.day_orchestrator import mini_control as mc


def _git(cwd, *a):
    p = subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True)
    return p.returncode == 0, (p.stdout or p.stderr).strip()


class UnmergedHeal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        origin = root / "origin.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)],
                       capture_output=True, check=True)
        self.work = root / "work"
        subprocess.run(["git", "clone", str(origin), str(self.work)],
                       capture_output=True, check=True)
        for k, v in (("user.email", "t@t.t"), ("user.name", "t")):
            _git(self.work, "config", k, v)
        self._commit("office-mapping.json", '{"a": 1}\n', "base")
        _git(self.work, "push", "-u", "origin", "main")
        self.runner = root / "runner"
        subprocess.run(["git", "clone", str(origin), str(self.runner)],
                       capture_output=True, check=True)
        for k, v in (("user.email", "r@r.r"), ("user.name", "r")):
            _git(self.runner, "config", k, v)
        # Upstream changes the mapping; the runner has its own uncommitted edit.
        self._commit("office-mapping.json", '{"a": 2}\n', "upstream mapping")
        _git(self.work, "push", "origin", "main")
        (self.runner / "office-mapping.json").write_text('{"a": 3}\n')
        real = mc.REPO_ROOT
        mc.REPO_ROOT = self.runner
        self.addCleanup(setattr, mc, "REPO_ROOT", real)

    def _commit(self, name, body, msg):
        (self.work / name).write_text(body)
        _git(self.work, "add", name)
        _git(self.work, "commit", "-m", msg)

    def _unmerged(self):
        return _git(self.runner, "diff", "--name-only", "--diff-filter=U")[1]

    def test_update_heals_and_keeps_the_edit_in_the_stash(self):
        ok, msg = mc._action_update("")
        self.assertTrue(ok, msg)
        self.assertEqual(self._unmerged(), "")
        self.assertEqual((self.runner / "office-mapping.json").read_text(),
                         '{"a": 2}\n')
        self.assertIn("parked", msg)
        self.assertTrue(_git(self.runner, "stash", "list")[1])

    def test_the_next_update_is_not_blocked(self):
        mc._action_update("")
        ok, msg = mc._action_update("")
        self.assertTrue(ok, msg)
        self.assertNotIn("resolve your current index", msg)

    def test_git_status_names_a_half_merged_file(self):
        # Reproduce the stuck state the old update left behind.
        _git(self.runner, "pull", "--ff-only", "--autostash")
        self.assertIn("office-mapping.json", self._unmerged())
        ok, msg = mc._action_git_status("")
        self.assertIn("HALF-MERGED", msg)
        self.assertIn("office-mapping.json", msg)
        self.assertNotIn("nothing blocking a pull", msg)


if __name__ == "__main__":
    unittest.main()
