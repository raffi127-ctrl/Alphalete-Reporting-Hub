"""The Hub's two morning signals must not cry wolf.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.test_hub_status_signals

Both fixes here are the same shape: a state that is FINE was being reported as a
problem, and the reported remedy did not work — so the line stopped meaning
anything and got ignored, which is the real cost.

1. THE GIT BADGE (_git_health). "not on latest main" was the fall-through for
   `local != remote` with nothing to pull — i.e. the repo is AHEAD. That is what
   this repo looks like between a local commit and its push, and several Claude
   sessions commit here every morning. Its printed remedy is "fully quit +
   relaunch to update", and a relaunch PULLS, so it could never clear a state with
   nothing to pull. Megan sat in that loop on 2026-08-25 while the repo was
   exactly level with origin/main.

2. NEEDS-ATTENTION vs an AUDIT. vantura_board_audit exits 0 and records findings
   as ok=False on purpose, so the orchestrator marks a SOFT INCOMPLETE "instead of
   a hard exit-1 FAILED that fires the immediate 'needs attention' page". That
   soft incomplete arrives as `partial`, and Needs-attention flagged every
   `partial` — reproducing the exact page the audit was written to avoid.

These tests drive the real functions with git stubbed; no repo state, no network.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations import dashboard

HEAD = "52b5e9e"
SHA_A = "a" * 40
SHA_B = "b" * 40


def _health(*, local, remote, behind, ahead, supervised=False):
    """Run _git_health with its `git` calls stubbed to the given repo state."""
    def fake_git(*args, **kw):
        a = list(args)
        if a[:2] == ["rev-parse", "--short"]:
            return HEAD
        if a[:1] == ["fetch"]:
            return ""
        if a[:2] == ["rev-parse", "--abbrev-ref"]:
            return "main"
        if a == ["rev-parse", "HEAD"]:
            return local
        if a == ["rev-parse", "origin/main"]:
            return remote
        if a[:2] == ["rev-list", "--count"]:
            return behind if a[2] == "HEAD..origin/main" else ahead
        if a[:1] == ["log"]:
            return "2 minutes ago"
        return ""

    env = {"HUB_SUPERVISED": "1"} if supervised else {}
    # _git_health is @st.cache_data-wrapped; __wrapped__ is the plain function.
    fn = getattr(dashboard._git_health, "__wrapped__", dashboard._git_health)
    with mock.patch("subprocess.run") as sp, \
            mock.patch.dict("os.environ", env, clear=False):
        sp.side_effect = lambda cmd, **kw: mock.Mock(
            stdout=fake_git(*cmd[1:]))
        return fn()


class AheadIsNotStale(unittest.TestCase):
    """THE LOOP. Local commits that haven't been pushed are not stale code."""

    def test_ahead_only_reads_as_on_latest(self):
        h = _health(local=SHA_A, remote=SHA_B, behind="0", ahead="2")
        self.assertTrue(h["ok"])
        self.assertEqual(h["label"], "On latest")

    def test_ahead_only_says_how_many_are_unpushed(self):
        h = _health(local=SHA_A, remote=SHA_B, behind="0", ahead="2")
        self.assertIn("2 local commit(s) not pushed", h["detail"])

    def test_ahead_only_never_tells_you_to_relaunch(self):
        """A relaunch pulls, and there is nothing to pull — that instruction is
        what made this unclearable."""
        h = _health(local=SHA_A, remote=SHA_B, behind="0", ahead="2")
        self.assertNotIn("relaunch", h["detail"].lower())
        self.assertNotIn("update", h["label"].lower())


class BehindStillWarns(unittest.TestCase):
    """The signal that must keep working: real stale code."""

    def test_behind_is_flagged_with_a_count(self):
        h = _health(local=SHA_A, remote=SHA_B, behind="4", ahead="0")
        self.assertFalse(h["ok"])
        self.assertIn("4 update(s) behind", h["label"])

    def test_behind_tells_you_to_relaunch_when_unsupervised(self):
        h = _health(local=SHA_A, remote=SHA_B, behind="4", ahead="0")
        self.assertIn("relaunch", h["detail"].lower())

    def test_behind_offers_the_button_when_supervised(self):
        h = _health(local=SHA_A, remote=SHA_B, behind="4", ahead="0",
                    supervised=True)
        self.assertIn("Update & restart", h["detail"])

    def test_diverged_leads_with_behind_and_still_mentions_unpushed(self):
        """Both at once: there IS something to pull, so that half leads."""
        h = _health(local=SHA_A, remote=SHA_B, behind="3", ahead="1")
        self.assertFalse(h["ok"])
        self.assertIn("3 update(s) behind", h["label"])
        self.assertIn("1 local commit(s) not pushed", h["detail"])


class LevelAndUnknown(unittest.TestCase):

    def test_identical_shas_are_on_latest(self):
        h = _health(local=SHA_A, remote=SHA_A, behind="0", ahead="0")
        self.assertTrue(h["ok"])
        self.assertEqual(h["label"], "On latest")

    def test_neither_ahead_nor_behind_but_different_is_reported_as_unknown(self):
        """origin/main unreadable, detached HEAD — real, but we don't know the
        fix, so we must not prescribe one."""
        h = _health(local=SHA_A, remote=SHA_B, behind="", ahead="")
        self.assertFalse(h["ok"])
        self.assertIn("can't compare", h["label"])
        self.assertNotIn("relaunch", h["detail"].lower())


class AnAuditsFindingsAreNotAFailure(unittest.TestCase):
    """Needs-attention must not reproduce the page the audit avoided."""

    def test_the_audit_card_is_listed_under_both_spellings(self):
        """It self-registers as a library card, so its id keeps underscores; a
        later rename to hyphens must not quietly re-break this."""
        self.assertIn("vantura_board_audit", dashboard.FINDINGS_REPORTS)
        self.assertIn("vantura-board-audit", dashboard.FINDINGS_REPORTS)

    def test_the_rule_is_partial_only_never_failed(self):
        """A genuine crash exits non-zero and lands as FAILED — that still has
        to reach the triage list, or the audit could break in silence."""
        import inspect
        src = inspect.getsource(dashboard)
        self.assertIn('if _stt == "partial" and r["id"] in FINDINGS_REPORTS:', src,
                      "the skip must be gated on partial alone")

    def test_the_set_does_not_swallow_ordinary_reports(self):
        """Scoped narrowly on purpose — every other report's partial still
        pages."""
        for rid in ("org-sales-board", "owner-chat-texts", "daily-focus",
                    "b2b-metrics"):
            with self.subTest(report=rid):
                self.assertNotIn(rid, dashboard.FINDINGS_REPORTS)

    def test_the_cancel_rate_is_listed_under_both_spellings(self):
        """captainship_cancel_rate writes kind='unfilled_icd' — "ran fine, N ICDs
        didn't fill". Slack has treated that as a finding since 2026-08-15 and
        resolves it; the Hub kept it on triage with a red ❌ all day."""
        self.assertIn("captainship-cancel-rate", dashboard.FINDINGS_REPORTS)
        self.assertIn("captainship_cancel_rate", dashboard.FINDINGS_REPORTS)

    def test_every_report_that_writes_a_finding_kind_is_mirrored(self):
        """THE DRIFT GUARD. Slack derives "this partial is a finding" from the
        manifest `kind` the run just wrote; the Hub cannot (manifests are local
        files on the runner) so FINDINGS_REPORTS is a hand-kept mirror — and a
        hand-kept mirror silently rots. captainship_cancel_rate started writing
        'unfilled_icd' and nobody added it here, so it sat on the triage list
        every morning it did its job.

        This greps the writers instead of trusting the list: any module calling
        write_manifest(kind=<one of notify._FINDING_KINDS>) must appear in
        FINDINGS_REPORTS. org_sales_board is exempt — it routes its 'finding'
        through section_drop_alert as a report-only side check that never gates
        the fill, so the board's own run status is not the finding."""
        import re
        from pathlib import Path
        from automations.day_orchestrator.notify import _FINDING_KINDS

        repo = Path(dashboard.__file__).resolve().parents[1]
        pat = re.compile(r"""kind\s*=\s*["'](%s)["']"""
                         % "|".join(map(re.escape, _FINDING_KINDS)))
        EXEMPT = {"org_sales_board"}     # side-channel alert, not the run verdict

        offenders = []
        for py in sorted((repo / "automations").rglob("*/run.py")):
            if not pat.search(py.read_text(encoding="utf-8", errors="replace")):
                continue
            pkg = py.parent.name
            if pkg in EXEMPT:
                continue
            if not ({pkg, pkg.replace("_", "-")} & dashboard.FINDINGS_REPORTS):
                offenders.append(pkg)
        self.assertEqual(offenders, [],
                         "these write a finding-kind manifest but are missing "
                         "from dashboard.FINDINGS_REPORTS, so their partial "
                         "still pages Megan every morning: %s" % offenders)


if __name__ == "__main__":
    unittest.main()
