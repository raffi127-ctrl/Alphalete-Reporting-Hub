"""What this watcher must never get wrong.

  python -m unittest automations.terminated_notice.test_notice
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.terminated_notice import run as R
from automations.terminated_notice import surfaces as S


ENTRY = {"name": "Eric Martinez", "date": "2026-09-10",
         "notes": "Office shut down (20721 Spartan Capital, Inc)"}


class ScanCode(unittest.TestCase):
    """The code scan reads the REAL repo files, so these double as a check that
    the paths in surfaces.py still exist."""

    def test_paths_in_the_table_are_real(self):
        missing = [s.path for s in S.code_surfaces()
                   if not (R.REPO_ROOT / s.path).exists()]
        self.assertEqual(missing, [], "surfaces.py points at files that are "
                                      "gone — the checklist would silently "
                                      "come back short")

    def test_finds_a_name_that_is_listed(self):
        # Kimberly Rodriguez is still on the DD roster (append-only by design),
        # so she is a stable fixture for "the scan finds a real hit".
        hits = R.scan_code(["Kimberly Rodriguez"])
        self.assertIn("automations/recruiting_report/dd_roster.json",
                      [h["path"] for h in hits])

    def test_finds_nothing_for_a_name_nobody_has(self):
        self.assertEqual(R.scan_code(["Zzz Nobody Here"]), [])

    def test_a_missing_file_never_raises(self):
        with mock.patch.object(S, "SURFACES",
                               [S.Code("gone", "automations/nope/nope.json")]):
            self.assertEqual(R.scan_code(["anyone"]), [])


class Render(unittest.TestCase):

    def test_lists_every_hit_and_the_leave_alone_note(self):
        txt = R.render(ENTRY,
                       [{"label": "DD roster", "path": "a/b.json",
                         "fix": "take their name out"}],
                       [{"label": "Focus Report", "where": "tab 'Eric Martinez'",
                         "fix": "hide the tab"}])
        self.assertIn("Eric Martinez is terminated", txt)
        self.assertIn("logged 2026-09-10", txt)
        self.assertIn("Focus Report", txt)
        self.assertIn("DD roster", txt)
        self.assertIn("Left alone on purpose", txt)
        self.assertIn("Canceled Orders", txt)

    def test_says_so_when_there_is_nothing_left(self):
        txt = R.render(ENTRY, [], [])
        self.assertIn("Nothing left to remove", txt)

    def test_carries_the_hiding_is_not_enough_warning(self):
        """A tab that a report fills regardless of the hidden flag has to say
        so — otherwise someone hides it, ticks the box, and the report keeps
        writing to it (what happened to Lizette Ruiz and Eveliz Wright)."""
        txt = R.render(ENTRY, [], [{"label": "Daily Rep Breakdown",
                                    "where": "tab 'Eric Martinez'",
                                    "fix": "hide it",
                                    "note": "hiding won't stop it"}])
        self.assertIn("hiding won't stop it", txt)

    def test_never_claims_it_removed_anything(self):
        txt = R.render(ENTRY, [], []).lower()
        self.assertNotIn("removed them", txt)
        self.assertIn("nothing here is deleted for you", txt)


class _StateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(R, "STATE_PATH",
                              Path(self.tmp.name) / "announced.json")
        p.start(); self.addCleanup(p.stop)
        p2 = mock.patch.object(R, "OUT_DIR", Path(self.tmp.name))
        p2.start(); self.addCleanup(p2.stop)


class FirstRun(_StateCase):

    def test_first_run_posts_nothing_and_records_everyone(self):
        """Standing the watcher up must not dump a checklist for every ICD
        terminated months ago."""
        logged = [{"name": "Jacob Morgan", "date": "", "notes": ""},
                  {"name": "Eric Martinez", "date": "", "notes": ""}]
        with mock.patch("automations.shared.terminated_icds.load_terminated",
                        return_value=logged), \
             mock.patch.object(R, "announce") as ann:
            rc = R.main(["--post"])
        self.assertEqual(rc, 0)
        ann.assert_not_called()
        saved = json.loads(R.STATE_PATH.read_text())
        self.assertEqual(set(saved), {"jacob morgan", "eric martinez"})
        self.assertFalse(saved["eric martinez"]["posted"])

    def test_the_next_new_name_does_post(self):
        R.save_state({"jacob morgan": {"name": "Jacob Morgan",
                                       "announced_at": "x", "posted": False}})
        logged = [{"name": "Jacob Morgan", "date": "", "notes": ""},
                  {"name": "Eric Martinez", "date": "", "notes": ""}]
        with mock.patch("automations.shared.terminated_icds.load_terminated",
                        return_value=logged), \
             mock.patch.object(R, "announce", return_value="posted") as ann:
            R.main(["--post"])
        self.assertEqual([c.args[0]["name"] for c in ann.call_args_list],
                         ["Eric Martinez"])


class PostsOnce(_StateCase):

    def test_a_name_never_posts_twice(self):
        logged = [{"name": "Eric Martinez", "date": "", "notes": ""}]
        with mock.patch("automations.shared.terminated_icds.load_terminated",
                        return_value=logged), \
             mock.patch.object(R, "announce", return_value="posted") as ann:
            R.save_state({"seed": {"name": "seed", "posted": True}})
            R.main(["--post"])          # posts
            R.main(["--post"])          # must not post again
        self.assertEqual(ann.call_count, 1)

    def test_a_refused_post_is_not_recorded_as_done(self):
        """If the machine wasn't Lucy, the name has to still be pending — the
        alternative is a termination nobody is ever told about."""
        logged = [{"name": "Eric Martinez", "date": "", "notes": ""}]
        with mock.patch("automations.shared.terminated_icds.load_terminated",
                        return_value=logged), \
             mock.patch.object(R, "announce", return_value=None) as ann:
            R.save_state({"seed": {"name": "seed", "posted": True}})
            R.main(["--post"])
            R.main(["--post"])
        self.assertEqual(ann.call_count, 2)

    def test_again_reposts_a_name_already_announced(self):
        logged = [{"name": "Eric Martinez", "date": "", "notes": ""}]
        R.save_state({"eric martinez": {"name": "Eric Martinez",
                                        "posted": True}})
        with mock.patch("automations.shared.terminated_icds.load_terminated",
                        return_value=logged), \
             mock.patch.object(R, "announce", return_value="posted") as ann:
            rc = R.main(["--post", "--again", "eric martinez"])
        self.assertEqual(rc, 0)
        self.assertEqual(ann.call_count, 1)

    def test_again_with_an_unknown_name_fails_loudly(self):
        with mock.patch("automations.shared.terminated_icds.load_terminated",
                        return_value=[{"name": "Eric Martinez", "date": "",
                                       "notes": ""}]), \
             mock.patch.object(R, "announce") as ann:
            rc = R.main(["--post", "--again", "Someone Else"])
        self.assertEqual(rc, 1)
        ann.assert_not_called()

    def test_dry_run_saves_no_state(self):
        logged = [{"name": "Eric Martinez", "date": "", "notes": ""}]
        R.save_state({"seed": {"name": "seed", "posted": True}})
        with mock.patch("automations.shared.terminated_icds.load_terminated",
                        return_value=logged), \
             mock.patch.object(R, "announce", return_value="x"):
            R.main(["--dry-run"])
        self.assertNotIn("eric martinez", R.load_state())


class Posting(unittest.TestCase):

    def test_refuses_when_the_token_is_a_person(self):
        """Megan's laptop holds Megan's token. A checklist signed by her reads
        as her asking someone else to do it."""
        client = mock.Mock()
        client.auth_test.return_value = {"user": "mhines"}
        with mock.patch("automations.shared.slack_metrics_post._client",
                        return_value=client), \
             mock.patch.object(R.platform, "system", return_value="Darwin"):
            ok = R.post("hello", dry_run=False, logfn=lambda *a: None)
        self.assertFalse(ok)
        client.chat_postMessage.assert_not_called()

    def test_posts_as_lucy(self):
        client = mock.Mock()
        client.auth_test.return_value = {"user": "lucy_reporting"}
        with mock.patch("automations.shared.slack_metrics_post._client",
                        return_value=client), \
             mock.patch.object(R.platform, "system", return_value="Darwin"):
            ok = R.post("hello", dry_run=False, logfn=lambda *a: None)
        self.assertTrue(ok)
        client.chat_postMessage.assert_called_once()
        self.assertEqual(client.chat_postMessage.call_args.kwargs["channel"],
                         R.CHANNEL)

    def test_windows_never_posts(self):
        with mock.patch.object(R.platform, "system", return_value="Windows"), \
             mock.patch("automations.shared.slack_metrics_post._client") as c:
            ok = R.post("hello", dry_run=False, logfn=lambda *a: None)
        self.assertFalse(ok)
        c.assert_not_called()


class Aliases(unittest.TestCase):

    def test_alias_failure_still_searches_the_one_name(self):
        with mock.patch("automations.focus_office_att.aliases.load_aliases",
                        side_effect=RuntimeError("sheet down")):
            self.assertEqual(R.name_candidates("Eric Martinez"),
                             ["Eric Martinez"])

    def test_aliases_widen_the_search(self):
        with mock.patch("automations.focus_office_att.aliases.load_aliases",
                        return_value={}), \
             mock.patch("automations.focus_office_att.aliases."
                        "get_search_candidates",
                        return_value=["Kim Rodriguez", "KIMBERLY RODRIGUEZ"]):
            got = R.name_candidates("Kimberly Rodriguez")
        self.assertEqual(got, ["Kimberly Rodriguez", "Kim Rodriguez",
                               "KIMBERLY RODRIGUEZ"])


if __name__ == "__main__":
    unittest.main()


class FalsePositives(unittest.TestCase):
    """Three ways the checklist cried wolf on its first live pass (2026-09-10).
    A to-do list that keeps listing finished work stops being read."""

    def test_a_removal_comment_is_not_a_listing(self):
        """Taking someone off a roster leaves a comment naming them. The
        comment is why nobody re-adds them — it stays, and must not read as
        'still listed'."""
        src = ('OWNERS = [\n'
               '    # Eric Martinez (ericdmartinez222@gmail.com) sacado el\n'
               '    # 2026-09-10: su oficina cerro.\n'
               '    "Someone Else",\n'
               ']\n')
        self.assertNotIn("eric martinez", R.strip_comments(src).lower())

    def test_a_name_still_in_the_list_is_still_found(self):
        src = 'OWNERS = [\n    "Eric Martinez",   # Spartan Capital\n]\n'
        self.assertIn("Eric Martinez", R.strip_comments(src))

    def test_a_hash_inside_a_string_does_not_truncate_the_line(self):
        src = 'CHANNEL = "#alphalete-sales"   # Raf\n'
        self.assertIn("#alphalete-sales", R.strip_comments(src))

    def test_office_mapping_in_skip_reads_as_done(self):
        data = json.dumps({"confirmed": [{"sheet_tab": "Someone Else"}],
                           "needs_review": [],
                           "skip": [{"sheet_tab": "Eric Martinez",
                                     "retired": "2026-09-10"}]})
        self.assertTrue(S._only_in_skip(data, ["Eric Martinez"]))

    def test_office_mapping_still_confirmed_reads_as_to_do(self):
        data = json.dumps({"confirmed": [{"sheet_tab": "Eric Martinez"}],
                           "needs_review": [], "skip": []})
        self.assertFalse(S._only_in_skip(data, ["Eric Martinez"]))

    def test_an_unparseable_mapping_reads_as_to_do(self):
        """'I couldn't tell' must never render as 'done'."""
        self.assertFalse(S._only_in_skip("{not json", ["Eric Martinez"]))

    def test_the_live_office_mapping_reads_as_done_for_eric(self):
        """He was moved to `skip` on 2026-09-10 — the checklist must not keep
        asking for it."""
        hits = R.scan_code(["Eric Martinez"])
        self.assertNotIn("automations/recruiting_report/office-mapping.json",
                         [h["path"] for h in hits])

    def test_a_hidden_tab_is_not_an_open_item(self):
        surf = S.SheetTab("Book", "id")
        ws_hidden = mock.Mock(); ws_hidden.title = "Eric Martinez"
        ws_hidden._properties = {"hidden": True}
        client = mock.Mock()
        client.open_by_key.return_value.worksheets.return_value = [ws_hidden]
        with mock.patch.object(S, "SURFACES", [surf]), \
             mock.patch("automations.recruiting_report.fill._client",
                        return_value=client):
            self.assertEqual(R.scan_sheets(["Eric Martinez"],
                                           logfn=lambda *a: None), [])

    def test_a_visible_tab_is_an_open_item(self):
        surf = S.SheetTab("Book", "id")
        ws = mock.Mock(); ws.title = "Eric Martinez"; ws._properties = {}
        client = mock.Mock()
        client.open_by_key.return_value.worksheets.return_value = [ws]
        with mock.patch.object(S, "SURFACES", [surf]), \
             mock.patch("automations.recruiting_report.fill._client",
                        return_value=client):
            got = R.scan_sheets(["Eric Martinez"], logfn=lambda *a: None)
        self.assertEqual(len(got), 1)
        self.assertIn("Eric Martinez", got[0]["where"])


class Agent(unittest.TestCase):
    """The 10-minute LaunchAgent that makes a termination reach the channel the
    same hour instead of the next morning (Megan, 2026-09-10)."""

    PLIST = "deploy/com.alphalete.terminated-notice.plist"
    SH = "deploy/terminated_notice_10min.sh"

    def test_the_pair_is_committed(self):
        for rel in (self.PLIST, self.SH):
            self.assertTrue((R.REPO_ROOT / rel).exists(), f"{rel} is missing")

    def test_the_plist_points_at_the_wrapper_that_exists(self):
        import plistlib
        data = plistlib.loads((R.REPO_ROOT / self.PLIST).read_bytes())
        shs = [a for a in data["ProgramArguments"] if a.endswith(".sh")]
        self.assertEqual(len(shs), 1)
        self.assertTrue(shs[0].endswith("terminated_notice_10min.sh"))
        # install_agent rewrites the committed laptop path to the machine's own
        # repo root, so the tail is what has to match — not the whole path.
        self.assertTrue((R.REPO_ROOT / self.SH).exists())

    def test_the_wrapper_runs_this_module(self):
        body = (R.REPO_ROOT / self.SH).read_text(encoding="utf-8")
        self.assertIn("automations.terminated_notice.run", body)
        self.assertIn("--post", body)

    def test_the_wrapper_has_no_hardcoded_venv(self):
        """Every report has to run on macOS AND Windows, and a mini without
        .venv must not silently do nothing."""
        body = (R.REPO_ROOT / self.SH).read_text(encoding="utf-8")
        self.assertIn("python3", body, "no fallback interpreter")

    def test_schedule_config_can_install_and_disable_it(self):
        import json
        cfg = json.loads((R.REPO_ROOT / "automations" / "day_orchestrator"
                          / "schedule_config.json").read_text(encoding="utf-8"))
        for key, mod in (("install_terminated_notice_agent",
                          "automations.day_orchestrator.install_agent"),
                         ("disable_terminated_notice_agent",
                          "automations.day_orchestrator.disable_agent")):
            e = cfg["reports"][key]
            self.assertEqual(e["command"], [mod])
            # Its OWN base_args: extra args land AFTER base_args, so borrowing
            # another install_* entry would install the wrong agent.
            self.assertEqual(e["base_args"], ["terminated-notice"])
            self.assertEqual(e["cadence"]["weekdays"], [])

    def test_the_batch_backstop_is_still_scheduled(self):
        """The agent is the fast path, not a replacement — if it is ever
        unloaded the checklist must still arrive, just slower."""
        import json
        cfg = json.loads((R.REPO_ROOT / "automations" / "day_orchestrator"
                          / "schedule_config.json").read_text(encoding="utf-8"))
        e = cfg["reports"]["terminated_notice"]
        self.assertTrue(e["on_scheduler"])
        self.assertEqual(e["cadence"]["weekdays"], [0, 1, 2, 3, 4, 5, 6])
