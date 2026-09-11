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

    def test_splits_what_is_done_from_what_a_person_must_do(self):
        """Megan 2026-09-10: "state where you removed/hid them and then what
        absolutely needs done by a human". A hidden tab is a FACT, not a task,
        and it must never appear under the heading Megan and Eve work from."""
        txt = R.render(ENTRY,
                       [{"label": "DD roster", "path": "a/b.json",
                         "fix": "take their name out"}],
                       [{"label": "Focus Report", "where": "tab 'Eric Martinez'",
                         "fix": "hidden (rows untouched)", "done": True},
                        {"label": "ORG Sales Board", "where": "'KTS' A41",
                         "fix": "their rows come off"}])
        self.assertIn("Eric Martinez — terminated", txt)
        self.assertIn("2026-09-10", txt)
        done, need = txt.split("*To do*")
        self.assertIn("Focus Report", done)      # finished -> Done
        self.assertIn("DD roster", done)         # code rosters are not their job
        self.assertIn("ORG Sales Board", need)   # genuinely human -> Needs
        self.assertNotIn("ORG Sales Board", done)
        self.assertNotIn("Focus Report", need)

    def test_the_shortest_post_is_just_the_one_thing_we_cannot_check(self):
        txt = R.render(ENTRY, [], [])
        self.assertNotIn("*Done", txt)
        self.assertIn("Google Contacts", txt)
        body = txt.split("*To do*")[1].split("_Left on purpose")[0]
        self.assertEqual(len([l for l in body.splitlines() if l.startswith(":black_square_button:")]), 1)

    def test_the_leave_alone_rule_survives_without_naming_examples(self):
        """The rule has to stay — it stops someone "finishing the job" and
        quietly changing a captain's totals. The example names were dropped
        because a post about Melik cited Melik as the example."""
        txt = R.render(ENTRY, [], [])
        self.assertIn("Leave alone", txt)
        self.assertIn("Canceled Orders", txt)
        self.assertNotIn("Melik El Jaiez", txt)

    def test_carries_the_hiding_is_not_enough_warning(self):
        """A tab that a report fills regardless of the hidden flag has to say
        so — otherwise someone hides it, ticks the box, and the report keeps
        writing to it (what happened to Lizette Ruiz and Eveliz Wright)."""
        txt = R.render(ENTRY, [], [{"label": "Daily Rep Breakdown",
                                    "where": "tab 'Eric Martinez'",
                                    "fix": "hide it",
                                    "note": "hiding won't stop it"}])
        self.assertIn("hiding won't stop it", txt)

    def test_never_claims_a_removal_it_did_not_make(self):
        """The contract CHANGED on 2026-09-10: it now hides tabs itself, so
        "it never touches anything" is no longer true and pretending otherwise
        would be the lie. What must still hold: nothing is DELETED, and a
        surface only reads as done when the run actually finished it."""
        txt = R.render(ENTRY, [],
                       [{"label": "ORG Sales Board", "where": "'KTS' A41",
                         "fix": "their rows come off"}])
        self.assertNotIn("*Done", txt)           # nothing finished -> no claim
        self.assertIn("*To do*", txt)

    def test_a_failed_hide_is_reported_as_work_not_as_done(self):
        """If the API call fails the tab is still open, and the checklist has
        to say so — a silent failure here is how a tab keeps filling while
        everyone believes it was handled."""
        txt = R.render(ENTRY, [],
                       [{"label": "Focus Report", "where": "tab 'X'",
                         "fix": "hide the tab; the automatic hide failed here"}])
        _done, need = txt.split("*To do*")
        self.assertIn("Focus Report", need)


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


class AlreadyDone(unittest.TestCase):
    """Melik El Jaiez, 2026-09-11: the post asked for three things and two were
    finished weeks earlier — his Captainship Bonuses row was already hidden and
    his card had already left Tony's group. A to-do that lists done work is
    read as 'this list exaggerates', and then the real item gets skipped."""

    def _cells_scan(self, hidden_rows, title="Captainship Bonuses",
                    meta_error=False):
        surf = S.SheetCells("ORG Sales Board", "id", tabs=(title,),
                            hidden_row_is_done=("Captainship Bonuses",))
        cell = mock.Mock(); cell.row = 49; cell.address = "A49"
        ws = mock.Mock(); ws.title = title
        ws.findall.return_value = [cell]
        sh = mock.Mock()
        sh.worksheets.return_value = [ws]
        if meta_error:
            sh.fetch_sheet_metadata.side_effect = RuntimeError("quota")
        else:
            sh.fetch_sheet_metadata.return_value = {"sheets": [{
                "properties": {"title": title},
                "data": [{"startRow": 48, "rowMetadata": [
                    {"hiddenByUser": 49 in hidden_rows}]}]}]}
        client = mock.Mock(); client.open_by_key.return_value = sh
        with mock.patch.object(S, "SURFACES", [surf]), \
             mock.patch("automations.recruiting_report.fill._client",
                        return_value=client):
            return R.scan_sheets(["Melik El Jaiez"], logfn=lambda *a: None)

    def test_a_hidden_row_on_captainship_bonuses_is_done(self):
        self.assertEqual(self._cells_scan({49}), [])

    def test_a_visible_row_on_captainship_bonuses_is_still_to_do(self):
        got = self._cells_scan(set())
        self.assertEqual(len(got), 1)
        self.assertIn("A49", got[0]["where"])

    def test_a_hidden_row_elsewhere_is_still_to_do(self):
        """On Overrides Math a hidden row still counts in the SUM."""
        got = self._cells_scan({49}, title="Overrides Math")
        self.assertEqual(len(got), 1)

    def test_unreadable_row_state_is_still_to_do(self):
        self.assertEqual(len(self._cells_scan(set(), meta_error=True)), 1)

    # --- Google Contacts -------------------------------------------------

    def _contacts(self, people):
        svc = mock.Mock()
        svc.contactGroups().list().execute.return_value = {"contactGroups": [
            {"resourceName": "contactGroups/tony", "name": "Tony's Captainship",
             "groupType": "USER_CONTACT_GROUP"},
            {"resourceName": "contactGroups/myContacts", "name": "myContacts",
             "groupType": "SYSTEM_CONTACT_GROUP"}]}
        svc.people().connections().list().execute.return_value = {
            "connections": people}
        with mock.patch("automations.shared.contacts_auth.load_credentials"), \
             mock.patch("googleapiclient.discovery.build", return_value=svc):
            return R.scan_contacts(["Melik El Jaiez"], logfn=lambda *a: None)

    @staticmethod
    def _card(groups, name="", email="melikeljaiez@yahoo.com"):
        return {"names": [{"displayName": name}] if name else [],
                "emailAddresses": [{"value": email}],
                "memberships": [{"contactGroupMembership": {
                    "contactGroupResourceName": f"contactGroups/{g}"}}
                    for g in groups]}

    def test_card_in_no_group_is_done(self):
        hit = self._contacts([self._card(["myContacts"])])
        self.assertTrue(hit["done"])

    def test_nameless_card_still_matches_on_its_address(self):
        hit = self._contacts([self._card(["tony"])])
        self.assertFalse(hit.get("done"))
        self.assertIn("Tony's Captainship", hit["where"])

    def test_card_found_by_display_name(self):
        hit = self._contacts([self._card(["tony"], name="Melik El Jaiez",
                                         email="m@x.com")])
        self.assertIn("Tony's Captainship", hit["where"])

    def test_no_card_means_cannot_tell(self):
        self.assertIsNone(self._contacts([self._card(["tony"], name="Someone",
                                                     email="a@b.com")]))

    def test_no_token_means_cannot_tell(self):
        with mock.patch("automations.shared.contacts_auth.load_credentials",
                        side_effect=RuntimeError("no token")):
            self.assertIsNone(R.scan_contacts(["Melik El Jaiez"],
                                              logfn=lambda *a: None))

    def test_a_checked_contacts_line_replaces_the_generic_one(self):
        txt = R.render(ENTRY, [], [{"label": "Google Contacts", "done": True,
                                    "where": "their card",
                                    "fix": "is in no contact group"}])
        done, need = txt.split("*To do*")
        self.assertIn("Google Contacts", done)
        self.assertNotIn("Google Contacts", need)


class OverridesMathStaysWhilePaid(unittest.TestCase):
    """Eve, 2026-09-11, on Melik's Overrides Math row ($1,175): "cuando deje de
    proveer revenue y esté en $0 se puede sacar". Asking for the row to come
    off while it still carries money is asking for the opposite of the rule."""

    def _scan(self, row_values=None, read_error=False):
        surf = S.SheetCells("ORG Sales Board", "id", tabs=("Overrides Math",),
                            keep_while_paid=("Overrides Math",))
        cell = mock.Mock(); cell.row = 110; cell.address = "A110"
        ws = mock.Mock(); ws.title = "Overrides Math"
        ws.findall.return_value = [cell]
        sh = mock.Mock(); sh.worksheets.return_value = [ws]
        if read_error:
            sh.values_batch_get.side_effect = RuntimeError("quota")
        else:
            sh.values_batch_get.return_value = {
                "valueRanges": [{"values": [row_values]}]}
        client = mock.Mock(); client.open_by_key.return_value = sh
        with mock.patch.object(S, "SURFACES", [surf]), \
             mock.patch("automations.recruiting_report.fill._client",
                        return_value=client):
            return R.scan_sheets(["Melik El Jaiez"], logfn=lambda *a: None)

    def test_a_row_still_in_money_is_left_alone(self):
        got = self._scan(["Melik El Jaiez", "35", "100", "81", "$1,175"])
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0]["kept"])
        self.assertIn("$1,175", got[0]["where"])
        txt = R.render(ENTRY, [], got)
        after = txt.split("*To do*")[1]
        self.assertNotIn(":black_square_button: *ORG Sales Board*", after)
        self.assertIn("_Leave alone: ORG Sales Board", after)

    def test_a_row_at_zero_is_to_do(self):
        got = self._scan(["Olin Salter", "0", "0", "0", "$0"])
        self.assertEqual(len(got), 1)
        self.assertFalse(got[0].get("kept"))
        self.assertIn("A110", got[0]["where"])

    def test_unreadable_amount_is_to_do_with_the_rule_spelled_out(self):
        got = self._scan(read_error=True)
        self.assertFalse(got[0].get("kept"))
        self.assertIn("$0", got[0]["where"])

    def test_money_parsing(self):
        self.assertEqual(R._money("$1,175"), 1175.0)
        self.assertEqual(R._money("-$20"), -20.0)
        self.assertEqual(R._money("$0"), 0.0)
        self.assertIsNone(R._money("81"))
        self.assertIsNone(R._money("Melik El Jaiez"))
