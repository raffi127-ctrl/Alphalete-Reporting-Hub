"""The office push runs the Lucys' own One App at a time walk -- shipped
whole, not copied -- and the batch robot is gone (2026-10-20).

Indeed spots the Resume Helper extension pulling every resume in one burst
and blocks it, so the office machine now walks the queue one applicant at a
time, the way Lucy 2 and Lucy 4 do. These pin the four things that make that
safe to ship to a machine nobody can reach:

  * the walk's Hub-only extras are the NAMED ones, and each is either inside
    a try or in a function the office push never calls;
  * no office machine does anything until its office is listed, and
    none really sends until it is listed "live";
  * the rules every office machine walks by are stated, not inherited;
  * nothing asks for, or checks, Resume Helper any more.

Nothing here opens Chrome, signs in, or posts anywhere.
"""
from __future__ import annotations

import ast
import datetime as dt
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

    def test_a_live_office_has_no_lucy_pushing_it_too(self):
        # One office, one pusher: a live office machine's office must sit
        # ONLY under a relay entry in ROTATION_BY_MACHINE, never on a Lucy.
        from automations.applicant_push import offices
        for key, (office, mode) in RP.PUSH_OFFICES.items():
            if mode != "live":
                continue
            homes = [m for m, offs in offices.ROTATION_BY_MACHINE.items()
                     if office in offs]
            self.assertEqual(len(homes), 1, (key, homes))
            self.assertIn(homes[0], offices.RELAY_MACHINES, (key, homes))

    def test_a_relay_entry_is_never_a_lucy(self):
        from automations.applicant_push import offices
        for m in offices.RELAY_MACHINES:
            self.assertNotIn("lucy", m.lower().replace("lucy reports", ""))

    def test_the_test_run_offices_are_dry(self):
        # 10/25: nine offices switched on to TEST (Megan). Going live is a
        # deliberate per-office commit, never a side effect.
        for key in ("drew", "hasani", "jamis10", "jennifer-att", "rashad",
                    "steve", "trang", "tre", "valeria", "khalil-nds"):
            self.assertEqual(RP.PUSH_OFFICES[key][1], "dry", key)

    def test_every_listed_office_states_its_number_and_mode(self):
        for key, (office, mode) in RP.PUSH_OFFICES.items():
            self.assertTrue(office.isdigit(), key)
            self.assertIn(mode, ("dry", "live"), key)

    def test_an_unlisted_office_does_nothing(self):
        self.assertFalse(RP.armed({"office_key": "not-an-office"}))
        self.assertFalse(RP.armed({}))
        with mock.patch.object(RP, "push_record",
                               return_value={"office_key": "not-an-office"}), \
             mock.patch.object(RP.C, "appstream_creds",
                               return_value={"username": "u", "password": "p"}):
            self.assertFalse(RP.enabled())
            with mock.patch.object(RP, "_connect") as conn:
                self.assertEqual(RP.push(live=True), 0)
            conn.assert_not_called()

    def test_a_dry_office_is_never_armed(self):
        with mock.patch.dict(RP.PUSH_OFFICES, {"drew": ("24680", "dry")}):
            self.assertFalse(RP.armed({"office_key": "drew"}))

    def test_a_live_office_is_armed(self):
        with mock.patch.dict(RP.PUSH_OFFICES, {"drew": ("24680", "live")}):
            self.assertTrue(RP.armed({"office_key": "drew"}))

    def test_a_scheduled_live_tick_on_a_dry_office_walks_dry(self):
        seen = {}

        def fake_walk(page, live, record):
            seen["live"] = live
            return {"reached": True, "office": "11580", "rc": 0, "sent": 0}
        with mock.patch.object(RP.C, "appstream_creds",
                               return_value={"username": "u", "password": "p"}), \
             mock.patch.dict(RP.PUSH_OFFICES, {"drew": ("24680", "dry")}), \
             mock.patch.object(RP, "push_record",
                               return_value={"office_key": "drew"}), \
             mock.patch.object(RP, "quiet_now", return_value=False), \
             mock.patch.object(RP, "_connect",
                               return_value=(None, mock.MagicMock(), object())), \
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
    """The number is stated in PUSH_OFFICES, never learned off the page: a
    login that sees many offices would teach it the wrong one."""

    def test_the_stated_office_passes(self):
        self.assertEqual(RP._pin_office("11580", {"office_key": "carlos"}),
                         (True, ""))

    def test_another_office_is_refused(self):
        ok, why = RP._pin_office("23467", {"office_key": "carlos"})
        self.assertFalse(ok)
        self.assertIn("23467", why)

    def test_an_unreadable_banner_is_refused(self):
        self.assertFalse(RP._pin_office(None, {"office_key": "carlos"})[0])

    def test_an_unlisted_office_is_refused(self):
        self.assertFalse(RP._pin_office("24680", {"office_key": "drew"})[0])


class AManyOfficeLoginSwitchesFirst(unittest.TestCase):
    """Carlos's computer holds the six-office Lucy Resume Pushing login, which
    lands on whatever office it was on last. The walk switches to the stated
    office before reading anyone -- and stops if it cannot."""

    def _page(self, has_switcher):
        page = mock.MagicMock()
        page.locator.return_value.count.return_value = 1 if has_switcher else 0
        page.title.return_value = "Somebody Else (23467) -"
        return page

    def test_switches_to_the_stated_office(self):
        from automations.recruiting_report import fetch_office as FO
        from automations.oat_processing import run as OAT
        with mock.patch.object(FO, "_switch_office", return_value=True) as sw, \
             mock.patch.object(OAT, "open_oat", return_value=False):
            RP._walk(self._page(True), False, {"office_key": "carlos"})
        self.assertEqual(sw.call_args.args[1], "11580")

    def test_a_failed_switch_is_not_fatal_the_banner_decides(self):
        # 10/21: the switch crashed five runs on Carlos's computer. Now a
        # failed or raising switch goes on to the banner check -- which
        # refuses unless the queue really is 11580.
        from automations.recruiting_report import fetch_office as FO
        from automations.oat_processing import run as OAT
        for outcome in (dict(return_value=False),
                        dict(side_effect=TimeoutError("row never showed"))):
            with mock.patch.object(FO, "_switch_office", **outcome), \
                 mock.patch.object(OAT, "open_oat", return_value=True), \
                 mock.patch.object(OAT, "office_on_page", return_value="23467"), \
                 mock.patch.object(OAT, "run_walk") as rw:
                out = RP._walk(self._page(True), True, {"office_key": "carlos"})
            rw.assert_not_called()          # wrong office: nobody touched
            self.assertEqual(out["rc"], 2)

    def test_already_on_the_office_skips_the_switch(self):
        from automations.recruiting_report import fetch_office as FO
        from automations.oat_processing import run as OAT
        page = self._page(True)
        page.title.return_value = "Carlos Hidalgo Office (11580) -"
        with mock.patch.object(FO, "_switch_office") as sw, \
             mock.patch.object(OAT, "open_oat", return_value=False):
            RP._walk(page, False, {"office_key": "carlos"})
        sw.assert_not_called()

    def test_an_office_only_login_does_not_switch(self):
        from automations.recruiting_report import fetch_office as FO
        from automations.oat_processing import run as OAT
        with mock.patch.object(FO, "_switch_office") as sw, \
             mock.patch.object(OAT, "open_oat", return_value=False):
            RP._walk(self._page(False), False, {"office_key": "carlos"})
        sw.assert_not_called()

    def test_the_switch_ships(self):
        self.assertIn("automations/recruiting_report/fetch_office.py",
                      package.AGENT_FILES)


class ItStaysInTheBackground(unittest.TestCase):
    """Megan 2026-10-21: "we want it running in the background". The walk
    brings tabs to the front on every resume read; Lucy's Chrome must not
    follow them onto the screen -- unless Indeed needs a person."""

    def test_a_held_guard_is_active_the_whole_time(self):
        g = RP._FocusGuard()
        self.assertFalse(g._active())
        g.hold()
        self.assertTrue(g._active())

    def test_it_stands_down_when_indeed_walls_the_walk(self):
        g = RP._FocusGuard()
        walled = {"now": False}
        g.hold(stand_down=lambda: walled["now"])
        self.assertTrue(g._active())
        walled["now"] = True
        self.assertFalse(g._active())
        self.assertTrue(g.stood_down)

    def test_windows_reminimizes_after_bring_to_front(self):
        from patchright.sync_api._generated import Page
        original = Page.bring_to_front
        calls = []
        with mock.patch.object(Page, "bring_to_front",
                               lambda self, *a, **k: calls.append("front")), \
             mock.patch.object(RP, "minimize",
                               side_effect=lambda c, p: calls.append("min")), \
             mock.patch.object(RP, "_walled", return_value=False):
            undo = RP._keep_minimized(object())
            Page.bring_to_front(object())
            undo()
        self.assertEqual(calls, ["front", "min"])
        self.assertIsNot(Page.bring_to_front, None)
        self.assertIs(Page.bring_to_front, original)

    def test_a_scheduled_push_holds_the_guard_for_the_walk(self):
        held = {}

        class G:
            hidden = 0
            def start(self): return self
            def stop(self): pass
            def hold(self, stand_down=None): held["yes"] = stand_down
        with mock.patch.object(RP.C, "appstream_creds",
                               return_value={"username": "u", "password": "p"}), \
             mock.patch.dict(RP.PUSH_OFFICES, {"drew": ("24680", "dry")}), \
             mock.patch.object(RP, "push_record",
                               return_value={"office_key": "drew"}), \
             mock.patch.object(RP, "_FocusGuard", G), \
             mock.patch.object(RP, "_connect",
                               return_value=(None, mock.MagicMock(), object())), \
             mock.patch.object(RP, "sign_in", return_value=True), \
             mock.patch.object(RP, "_walk", return_value={
                 "reached": True, "office": "24680", "rc": 0, "sent": 0}), \
             mock.patch.object(RP, "_save_state"), \
             mock.patch.object(RP, "LOCK_PATH", mock.MagicMock()), \
             mock.patch("patchright.sync_api.sync_playwright"):
            RP.push(live=False, scheduled=True)
        self.assertIs(held.get("yes"), RP._walled)


class IndeedsCheckReachesThePeopleWhoCanTickIt(unittest.TestCase):
    """Megan 2026-10-21: DM the owner, Eve and Megan when the human check
    needs doing -- but not for a wall that clears on the next run."""

    def setUp(self):
        self.state = {}
        self.filed = []
        ps = [mock.patch.object(RP, "_state", side_effect=lambda: dict(self.state)),
              mock.patch.object(RP, "_save_state",
                                side_effect=lambda st: self.state.update(st)),
              mock.patch.object(RP, "push_record",
                                return_value={"office_key": "carlos"}),
              mock.patch("automations.icd_alerts.relay.report_fault",
                         side_effect=lambda stage, *a, **k:
                         self.filed.append((stage, k.get("office_key"))))]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)

    def test_one_walled_run_files_nothing(self):
        RP._note_wall(True)
        self.assertEqual(self.filed, [])

    def test_three_in_a_row_files_one_signin_fault(self):
        for _ in range(RP.WALL_RUNS + 2):
            RP._note_wall(True)
        self.assertEqual(self.filed, [("signin-indeed", "carlos")])

    def test_clearing_after_an_alert_files_the_proof(self):
        for _ in range(RP.WALL_RUNS):
            RP._note_wall(True)
        RP._note_wall(False)
        self.assertEqual(self.filed, [("signin-indeed", "carlos"),
                                      ("probe-indeed-clear", "carlos")])

    def test_clearing_without_an_alert_files_nothing(self):
        RP._note_wall(True)
        RP._note_wall(False)
        self.assertEqual(self.filed, [])

    def test_the_good_to_go_is_super_simple(self):
        from automations.icd_alerts import post as P
        spec = P.SYSTEMS["indeed"]
        text = spec["good"] % ("Carlos's Local Office", spec["name"], "1:43 PM")
        self.assertEqual(text, ":white_check_mark: *Carlos's Local Office* "
                               "— good to go. Lucy is pushing again.")
        self.assertEqual(P._SIGNIN_PROOF["indeed"], "probe-indeed-clear")

    def test_a_clean_run_resets_the_count(self):
        RP._note_wall(True)
        RP._note_wall(True)
        RP._note_wall(False)
        RP._note_wall(True)
        self.assertEqual(self.filed, [])

    def test_the_poster_dms_it_and_keeps_it_out_of_the_channel(self):
        from automations.icd_alerts import post as P
        self.assertEqual(P._signin_system({"stage": "signin-indeed"}),
                         "indeed")
        spec = P.SYSTEMS["indeed"]
        text = spec["ask"] % ("Carlos's Local Office", spec["name"],
                              spec["what"], "1:07 PM", spec["why"],
                              spec["how"])
        self.assertEqual(text, (
            ":raising_hand: *Carlos's Local Office* — Lucy needs a human.\n"
            "On the LucyECO computer: click Lucy's Chrome and tick "
            "\u201cVerify you are human.\u201d"))
        self.assertLessEqual(len(text.splitlines()), 2)   # SUPER SIMPLE


class EveryRunSaysWhatItDid(unittest.TestCase):
    """Megan 2026-10-21: "We need to know it's working!" Each run relays its
    queue numbers; the push report reads them (push_report.run)."""

    def test_a_run_files_its_numbers(self):
        import json
        filed = []
        with mock.patch("automations.icd_alerts.relay.report_fault",
                        side_effect=lambda stage, summary, detail="", **k:
                        filed.append((stage, summary, json.loads(detail),
                                      k.get("office_key")))), \
             mock.patch.object(RP, "push_record",
                               return_value={"office_key": "carlos"}):
            RP._file_stats({"office": "11580", "queue_start": 54,
                            "queue_end": 50, "sent": 4, "walled": False},
                           True, 19, "ok")
        stage, summary, d, key = filed[0]
        self.assertEqual((stage, summary, key),
                         ("probe-push-stats", "push stats", "carlos"))
        self.assertEqual((d["start"], d["end"], d["sent_run"],
                          d["sent_today"], d["live"]), (54, 50, 4, 19, True))

    def test_the_stage_is_one_the_report_reads(self):
        from automations.push_report import run as PR
        self.assertEqual(RP.STATS_STAGE, PR.RELAY_STATS_STAGE)

    def test_the_walk_hands_back_its_queue(self):
        from automations.oat_processing import run as OAT
        self.assertIsInstance(OAT.LAST_WALK, dict)


class TheAgentReportsThePushsHealth(unittest.TestCase):
    """10/21 evening: no stats row, and nothing to tell a hung push from one
    that never started. The agent's own tick now says which."""

    def test_heartbeat_files_release_lock_and_log(self):
        import json
        filed, state = [], {"last_start": "2026-10-21T19:50:00",
                            "last_result": "ok"}
        with mock.patch.object(RP, "push_record",
                               return_value={"office_key": "carlos"}), \
             mock.patch.object(RP, "_state", side_effect=lambda: dict(state)), \
             mock.patch.object(RP, "_save_state",
                               side_effect=lambda st: state.update(st)), \
             mock.patch.object(RP, "_log_tail", return_value=["x LIVE: office 11580"]), \
             mock.patch.object(RP.C, "appstream_creds", return_value={"u": 1}), \
             mock.patch("automations.icd_alerts.relay.report_fault",
                        side_effect=lambda st_, su, d="", **k:
                        filed.append((st_, json.loads(d))) or True):
            now = dt.datetime(2026, 10, 21, 20, 0)
            self.assertTrue(RP._heartbeat(now=now))
            self.assertFalse(RP._heartbeat(now=now + dt.timedelta(minutes=5)))
            self.assertTrue(RP._heartbeat(now=now + dt.timedelta(minutes=16)))
        stage, body = filed[0]
        self.assertEqual(stage, "probe-push-health")
        for k in ("release", "listed", "lock_min", "last_start",
                  "last_result", "log_tail"):
            self.assertIn(k, body)
        self.assertEqual(body["log_tail"], ["x LIVE: office 11580"])

    def test_no_push_here_no_heartbeat(self):
        with mock.patch.object(RP, "push_record", return_value={}):
            self.assertFalse(RP._heartbeat())


class PictureResumesAreReadOnTheMac(unittest.TestCase):
    """10/22: Jorge Banos's number was on his resume in plain sight and the
    office push called him "no phone" -- Indeed drew it as a picture, and the
    Claude vision fallback needs a key no office computer has."""

    def test_the_reader_ships(self):
        self.assertIn("automations/oat_processing/bin/ocr_screen.js",
                      package.AGENT_FILES)

    def test_vision_failing_falls_back_to_the_mac(self):
        from automations.oat_processing import run as OAT
        with mock.patch.object(OAT, "_local_screen_text", return_value=(
                "Jorge Banos's Resume\nView candidate\nJORGE\nBANOS\n"
                "Dallas, TX\njbanos400@gmail.com\n9454023077\n"
                "2504 Bentley Ave 75211")):
            phone, email = OAT._ocr_phone(mock.MagicMock())
        self.assertEqual((phone, email), ("9454023077", "jbanos400@gmail.com"))

    def test_no_text_is_no_phone(self):
        from automations.oat_processing import run as OAT
        with mock.patch.object(OAT, "_local_screen_text", return_value=""):
            self.assertEqual(OAT._ocr_phone(mock.MagicMock()), (None, ""))

    def test_the_written_off_are_reread_once_per_fix(self):
        state, resets = {}, []
        oat = mock.Mock(reset_nophone_cache=lambda: resets.append(1) or 2)
        with mock.patch.object(RP, "_state", side_effect=lambda: dict(state)), \
             mock.patch.object(RP, "_save_state",
                               side_effect=lambda st: state.update(st)):
            RP._recheck_once_per_fix(oat)
            RP._recheck_once_per_fix(oat)
        self.assertEqual(resets, [1])
        self.assertEqual(state["recheck_for"], RP.READ_FIX)


class TheMacReaderReallyReads(unittest.TestCase):
    """The real thing, on a real image: macOS only, skipped elsewhere."""

    def test_reads_a_number_off_an_image(self):
        import platform
        import subprocess
        import tempfile
        if platform.system() != "Darwin":
            self.skipTest("macOS only")
        js = REPO / "automations/oat_processing/bin/ocr_screen.js"
        png = tempfile.mktemp(suffix=".png")
        html = ("<html><body style='font:40px Arial;padding:40px'>"
                "Jorge Banos<br>9454023077</body></html>")
        try:
            from patchright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True)
                pg = b.new_page()
                pg.set_content(html)
                pg.screenshot(path=png)
                b.close()
        except Exception as e:  # noqa: BLE001
            self.skipTest("no browser: %s" % e)
        out = subprocess.run(["osascript", "-l", "JavaScript", str(js), png],
                             capture_output=True, timeout=60).stdout.decode()
        self.assertIn("9454023077", out.replace(" ", ""))


class TheHealthRowNamesPeople(unittest.TestCase):

    def test_only_the_lines_about_people_and_short(self):
        import tempfile, pathlib
        log = pathlib.Path(tempfile.mktemp())
        log.write_text("\n".join([
            "    [attachment] no attachment on the panel (waited 4.0s)",
            "    [cf] first resume read of this session -- waiting 150s",
            "[2] FLAG_NO_PHONE -- Jorge Banos: no phone or cell on file",
            "    [ocr] read by the Mac itself: 9454023077",
            "    \u2705 SENT to AI: Jorge Banos " + "x" * 200,
        ]))
        with mock.patch.object(RP, "LOG_PATH", log):
            tail = RP._log_tail()
        self.assertEqual(len(tail), 3)
        self.assertIn("Jorge Banos", tail[0])
        self.assertIn("Mac itself", tail[1])
        self.assertTrue(tail[2].startswith("\u2705 SENT to AI: Jorge Banos"))
        self.assertTrue(all(len(l) <= 110 for l in tail))


class DownloadedPdfsAreReadOnTheMac(unittest.TestCase):
    """10/22 evening: Jorge Banos STILL not sent. Indeed hands his resume over
    as a PDF, and an office computer has no PDF library."""

    def test_the_reader_ships(self):
        self.assertIn("automations/oat_processing/bin/read_file.js",
                      package.AGENT_FILES)

    def _real(self):
        import platform
        if platform.system() != "Darwin":
            self.skipTest("macOS only")

    def _pdf(self, html):
        import tempfile
        path = tempfile.mktemp(suffix=".pdf")
        try:
            from patchright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True)
                pg = b.new_page()
                pg.set_content(html)
                pg.pdf(path=path)
                b.close()
        except Exception as e:  # noqa: BLE001
            self.skipTest("no browser: %s" % e)
        return path

    def test_a_text_pdf_without_any_pdf_library(self):
        self._real()
        from automations.oat_processing import resume_download as RD
        path = self._pdf("<h1>Jorge Banos</h1><p>jbanos400@gmail.com</p>"
                         "<p>9454023077</p>")
        import builtins
        real_import = builtins.__import__

        def no_pdf_libs(name, *a, **k):
            if name in ("fitz", "pdfminer.high_level"):
                raise ImportError(name)
            return real_import(name, *a, **k)
        with mock.patch("builtins.__import__", no_pdf_libs):
            self.assertEqual(RD.phone_from_file(path), "9454023077")
        self.assertEqual(RD.LAST_EMAIL, "jbanos400@gmail.com")

    def test_a_picture_pdf_without_swift(self):
        self._real()
        import subprocess
        import tempfile
        from automations.oat_processing import resume_download as RD
        text_pdf = self._pdf("<div style='font:40px Arial'>Jorge Banos"
                             "<br>9454023077</div>")
        # Flatten it to a picture-only PDF: no text layer at all.
        png = tempfile.mktemp(suffix=".png")
        flat = tempfile.mktemp(suffix=".pdf")
        subprocess.run(["sips", "-s", "format", "png", text_pdf, "--out",
                        png], capture_output=True)
        subprocess.run(["sips", "-s", "format", "pdf", png, "--out", flat],
                       capture_output=True)
        with mock.patch.object(RD, "_swift_usable", return_value=False), \
             mock.patch.object(RD, "_text_from_pdf", return_value=""):
            self.assertEqual(RD.phone_from_file(flat), "9454023077")

    def test_the_written_off_are_reread_for_this_fix(self):
        self.assertEqual(RP.READ_FIX, "2026-10-22-mac-pdf")


class AnOfficeOnlyLoginCountsAsSignedIn(unittest.TestCase):
    """10/25 test run: Jennifer's and Rashad's computers reached their own
    office page and were called "sign-in failed" -- an office-only login has
    no office switcher."""

    def _page(self, switcher, title):
        page = mock.MagicMock()
        page.locator.return_value.count.return_value = 1 if switcher else 0
        page.title.return_value = title
        return page

    def _ctx(self, token):
        ctx = mock.MagicMock()
        ctx.cookies.return_value = ([{"name": "rqst_ABC"}] if token else [])
        return ctx

    def test_the_office_page_with_a_session_is_signed_in(self):
        self.assertTrue(RP._signed_in_here(
            self._page(False, "Figspire Management, Inc. (23132) -"),
            self._ctx(True)))

    def test_the_switcher_still_counts(self):
        self.assertTrue(RP._signed_in_here(self._page(True, "x"),
                                           self._ctx(False)))

    def test_the_login_page_does_not(self):
        self.assertFalse(RP._signed_in_here(self._page(False, "Login"),
                                            self._ctx(True)))

    def test_no_session_token_does_not(self):
        self.assertFalse(RP._signed_in_here(
            self._page(False, "Figspire Management, Inc. (23132) -"),
            self._ctx(False)))


class TheAwaitTextIsRetunedOnLivePushesOnly(unittest.TestCase):
    """Megan 2026-10-28: every office's Await text carries the right times --
    on the office computer too, where 11580 actually pushes. Test runs edit
    nothing."""

    def _walk(self, live):
        from automations.oat_processing import run as OAT
        from automations.oat_processing import await_template as AT
        page = mock.MagicMock()
        page.locator.return_value.count.return_value = 0
        with mock.patch.object(OAT, "attach_dialog_accept"), \
             mock.patch.object(OAT, "open_oat", return_value=True), \
             mock.patch.object(OAT, "office_on_page", return_value="11580"), \
             mock.patch.object(OAT, "run_walk", return_value=0), \
             mock.patch.object(RP, "_recheck_once_per_fix"), \
             mock.patch.object(AT, "ensure_await_template") as ens:
            RP._walk(page, live, {"office_key": "carlos"})
        return ens

    def test_live_retunes_for_the_pinned_office(self):
        ens = self._walk(True)
        ens.assert_called_once()
        self.assertEqual(ens.call_args.args[1], "11580")

    def test_a_test_run_edits_nothing(self):
        self._walk(False).assert_not_called()

    def test_the_two_files_ship(self):
        for rel in ("automations/oat_processing/await_window.py",
                    "automations/oat_processing/await_template.py"):
            self.assertIn(rel, package.AGENT_FILES)


class ResumeHelperIsGone(unittest.TestCase):

    def test_setup_does_not_ask_for_it(self):
        src = (HERE / "finish_setup.py").read_text()
        self.assertNotIn("extension_installed", src)
        self.assertNotIn("setup_extension", src)

    def test_the_old_setup_flag_still_answers(self):
        self.assertEqual(RP.main(["--setup"]), 0)


if __name__ == "__main__":
    unittest.main()
