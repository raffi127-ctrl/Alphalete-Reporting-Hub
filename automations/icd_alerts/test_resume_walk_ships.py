"""The office push runs the Lucys' own One App at a time walk -- shipped
whole, not copied -- and the batch robot is gone (2026-10-20).

Indeed spots the Resume Helper extension pulling every resume in one burst
and blocks it, so the office machine now walks the queue one applicant at a
time, the way Lucy 2 and Lucy 4 do. These pin the four things that make that
safe to ship to a machine nobody can reach:

  * the walk's Hub-only extras are the NAMED ones, and each is either inside
    a try or in a function the office push never calls;
  * no office machine really sends until its office is switched on;
  * the rules every office machine walks by are stated, not inherited;
  * nothing asks for, or checks, Resume Helper any more.

Nothing here opens Chrome, signs in, or posts anywhere.
"""
from __future__ import annotations

import ast
import pathlib
import unittest
from unittest import mock

from automations.icd_alerts import package
from automations.icd_alerts import resume_push as RP

REPO = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent


def _imports_by_function(rel):
    """[(module, function, inside_try)] for every automations import."""
    tree = ast.parse((REPO / rel).read_text())
    out = []

    def walk(n, fn, in_try):
        for c in ast.iter_child_nodes(n):
            t = in_try or (isinstance(n, ast.Try) and c in n.body)
            f = c.name if isinstance(c, ast.FunctionDef) else fn
            if (isinstance(c, ast.ImportFrom) and c.module
                    and c.module.startswith("automations")):
                out.append((c.module, fn, t))
            walk(c, f, t)
    walk(tree, None, False)
    return out


class TheWalkShipsWhole(unittest.TestCase):

    def test_the_walk_is_in_the_package_and_the_batch_is_not(self):
        for rel in ("automations/oat_processing/run.py",
                    "automations/oat_processing/config.py",
                    "automations/oat_processing/classify.py",
                    "automations/oat_processing/resume_download.py",
                    "automations/applicant_push/window.py"):
            self.assertIn(rel, package.AGENT_FILES)
        self.assertNotIn("automations/icd_alerts/push_batch.py",
                         package.AGENT_FILES)

    def test_every_hub_only_import_is_guarded_or_unreachable(self):
        for rel, module, fn in sorted(package.HUB_ONLY_IMPORTS):
            found = [t for m, f, t in _imports_by_function(rel)
                     if m == module and f == fn]
            self.assertTrue(found, "%s no longer imports %s in %s -- drop "
                            "the entry" % (rel, module, fn))
            if fn in package.HUB_ONLY_ENTRY_POINTS:
                continue
            self.assertTrue(all(found), "%s: the %s import in %s() is no "
                            "longer inside a try -- on an office machine it "
                            "would crash the walk" % (rel, module, fn))

    def test_the_office_push_never_calls_a_lucy_only_entry_point(self):
        src = (HERE / "resume_push.py").read_text()
        for fn in package.HUB_ONLY_ENTRY_POINTS:
            self.assertNotIn("OAT.%s(" % fn, src)

    def test_the_walk_module_imports_without_the_hub_session_stack(self):
        tree = ast.parse(
            (REPO / "automations/oat_processing/run.py").read_text())
        top = [n.module for n in tree.body
               if isinstance(n, ast.ImportFrom) and n.module]
        self.assertFalse([m for m in top if m.startswith("automations")],
                         "module-level Hub imports stop the walk loading on "
                         "an office machine")


class NobodyIsSentUntilSwitchedOn(unittest.TestCase):

    def test_no_office_is_live_yet(self):
        # Rollout on hold (Megan, 10/7). Adding one is a deliberate commit.
        self.assertEqual(RP.LIVE_OFFICE_KEYS, frozenset())

    def test_an_unlisted_office_is_never_armed(self):
        self.assertFalse(RP.armed({"office_key": "drew"}))
        self.assertFalse(RP.armed({}))

    def test_a_listed_office_is_armed(self):
        with mock.patch.object(RP, "LIVE_OFFICE_KEYS", frozenset({"drew"})):
            self.assertTrue(RP.armed({"office_key": "drew"}))

    def test_a_scheduled_live_tick_walks_as_a_dry_run(self):
        seen = {}

        def fake_walk(page, live, record):
            seen["live"] = live
            return {"reached": True, "office": "12345", "rc": 0, "sent": 0}
        fake_ctx = mock.MagicMock()
        with mock.patch.object(RP.C, "appstream_creds",
                               return_value={"username": "u", "password": "p"}), \
             mock.patch.object(RP, "push_record",
                               return_value={"office_key": "drew"}), \
             mock.patch.object(RP, "quiet_now", return_value=False), \
             mock.patch.object(RP, "_connect",
                               return_value=(None, fake_ctx, object())), \
             mock.patch.object(RP, "sign_in", return_value=True), \
             mock.patch.object(RP, "_walk", side_effect=fake_walk), \
             mock.patch.object(RP, "_save_state"), \
             mock.patch.object(RP, "LOCK_PATH", mock.MagicMock()), \
             mock.patch("patchright.sync_api.sync_playwright"):
            self.assertEqual(RP.push(live=True), 0)
        self.assertIs(seen["live"], False)


class TheRulesAreStated(unittest.TestCase):

    def test_never_removes_for_contact_info_never_texts(self):
        from automations.oat_processing import config as OC
        keep = {k: getattr(OC, k) for k in (
            "OFFICE_ID", "OFFICE_HINT", "FILE_SUFFIX", "WALK_DIAG_TAB",
            "REMOVE_NO_PHONE", "ALLOW_RETEXT", "REMOVE_BLOCKED_READ",
            "MAX_WALK_SECONDS", "WALK_DEADLINE_EPOCH")}
        try:
            OC.REMOVE_NO_PHONE = OC.ALLOW_RETEXT = OC.REMOVE_BLOCKED_READ = True
            RP._point_walk_here("24680", {"owner": "Drew"})
            self.assertEqual(OC.OFFICE_ID, "24680")
            self.assertFalse(OC.REMOVE_NO_PHONE)
            self.assertFalse(OC.ALLOW_RETEXT)
            self.assertFalse(OC.REMOVE_BLOCKED_READ)
            self.assertEqual(OC.FILE_SUFFIX, "-24680")
        finally:
            for k, v in keep.items():
                setattr(OC, k, v)


class TheOfficeIsPinned(unittest.TestCase):

    def test_first_walk_learns_the_office(self):
        rec = {"office_key": "drew"}
        with mock.patch.object(RP.C, "add_enrollment") as add:
            self.assertEqual(RP._pin_office("24680", rec), (True, ""))
        self.assertEqual(rec["as_office_id"], "24680")
        add.assert_called_once()

    def test_a_different_office_is_refused(self):
        ok, why = RP._pin_office("11580", {"as_office_id": "24680"})
        self.assertFalse(ok)
        self.assertIn("11580", why)

    def test_an_unreadable_banner_is_refused(self):
        self.assertFalse(RP._pin_office(None, {"as_office_id": "24680"})[0])


class ResumeHelperIsGone(unittest.TestCase):

    def test_setup_does_not_ask_for_it(self):
        src = (HERE / "finish_setup.py").read_text()
        self.assertNotIn("extension_installed", src)
        self.assertNotIn("setup_extension", src)

    def test_the_old_setup_flag_still_answers(self):
        self.assertEqual(RP.main(["--setup"]), 0)


if __name__ == "__main__":
    unittest.main()
