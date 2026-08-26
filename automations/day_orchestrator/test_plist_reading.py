"""Reading a LaunchAgent plist must agree with launchd, or the Hub invents cards.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.day_orchestrator.test_plist_reading

THE BUG (Megan 2026-08-26). Our plists are heavily commented, and the comments
quote CLI flags: "SENDS NOTHING -- --sync-completed only reads ...". A double
hyphen inside an XML comment is illegal XML. launchd (CFPropertyList) does not
care and `plutil -lint` says OK, so every one of these agents was loaded and
running fine. Python's plistlib runs on expat, which refuses outright — so
`plistlib.loads()` raised on SIX of our plists and hub_coverage silently
concluded it knew nothing about those agents.

That is the whole mechanism behind the phantom Hub cards:

  _wrapper_for_plist -> None            (can't read ProgramArguments)
  _agent_report_id   -> (None, 'no-wrapper')
  sync_launchd_system -> falls through to its GENERIC branch and cards the
                         agent as a standalone report in its own right...
  _plist_schedule    -> ...with a real clock time, because THAT reader already
                         had the comment-stripping fallback and worked.

So the Hub grew a card called "Blueink Completed Sweep — scheduled 08:15" for a
job that deliberately publishes nothing (deploy/blueink_completed_sweep.sh: "not
published to the Hub ... fires seven times a day"). It can never log a run, so
Needs-attention said "scheduled 08:15, no run logged" every single day — while
Slack stayed silent, because the didn't-run watcher's baseline is built from
Activity rows and this report has never written one. A card that looked watched
and was structurally invisible.

Five more had the same shape and were only quiet because they fire on one
weekday: blueink_docs_monday, leaders_call_mon, new_start_followup_sat,
dd_bulletin_thu, and (by a different route) org_board_box_repull.

No network, no Sheets — these read the committed plists off disk.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from automations.day_orchestrator import hub_coverage as hc

PLISTS = sorted(hc.DEPLOY_DIR.glob("com.alphalete.*.plist"))


class EveryCommittedPlistIsReadable(unittest.TestCase):
    """If launchd can load it, we must be able to read it."""

    def test_there_are_plists_to_check(self):
        self.assertTrue(PLISTS, "no deploy/com.alphalete.*.plist found")

    def test_none_of_them_defeat_the_loader(self):
        unreadable = [p.name for p in PLISTS if hc._load_plist(p) is None]
        self.assertEqual(unreadable, [],
                         "hub_coverage cannot read these, so every agent in "
                         "them resolves to 'no-wrapper' and gets a phantom "
                         "card: %s" % unreadable)

    def test_a_double_hyphen_comment_is_tolerated(self):
        """The exact shape that broke it — reduced to one file."""
        import tempfile
        raw = (b'<?xml version="1.0" encoding="UTF-8"?>\n'
               b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
               b'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
               b'<plist version="1.0"><dict>\n'
               b'  <!-- pass --dry-run to rehearse it -->\n'
               b'  <key>Label</key><string>com.alphalete.example</string>\n'
               b'</dict></plist>\n')
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "com.alphalete.example.plist"
            p.write_bytes(raw)
            import plistlib
            with self.assertRaises(Exception):      # plain plistlib still can't
                plistlib.loads(raw)
            self.assertEqual((hc._load_plist(p) or {}).get("Label"),
                             "com.alphalete.example")

    def test_the_loader_agrees_with_plutil(self):
        """plutil IS launchd's parser. Anything it lints clean, we must read —
        otherwise the two disagree and the Hub decides based on the wrong one."""
        if not Path("/usr/bin/plutil").exists():
            self.skipTest("plutil is macOS-only")
        for p in PLISTS:
            with self.subTest(plist=p.name):
                lint = subprocess.run(["/usr/bin/plutil", "-lint", str(p)],
                                      capture_output=True, text=True)
                if lint.returncode != 0:
                    continue          # genuinely malformed — not our problem here
                self.assertIsNotNone(
                    hc._load_plist(p),
                    "plutil lints %s clean but _load_plist returned None" % p.name)


class AnAgentResolvesToItsRealReport(unittest.TestCase):
    """'no-wrapper' is the failure that manufactures a phantom card."""

    def test_no_agent_is_stranded_on_no_wrapper(self):
        stranded = []
        for p in PLISTS:
            name = p.name[len("com.alphalete."):-len(".plist")]
            _rid, why = hc._agent_report_id(name)
            if why == "no-wrapper":
                stranded.append(name)
        self.assertEqual(stranded, [],
                         "these name a wrapper we can't see: %s" % stranded)

    def test_the_blue_ink_sweep_lands_on_the_blue_ink_docs_card(self):
        """It is a sub-step of that report, not a report. Its 2-hourly fires
        belong to no card of their own."""
        rid, why = hc._agent_report_id("blueink-completed-sweep")
        self.assertEqual((rid, why), ("blueink_docs", "module-match"))


class NotAReportMeansTheRowDeleteSticks(unittest.TestCase):
    """_NOT_A_REPORT's docstring promises a plain row-delete STICKS."""

    def test_the_declared_substeps_are_internal(self):
        """The four listed by hand. blueink_docs_monday and dd_bulletin_thu are
        NOT here on purpose — the plist now resolves them to their real report
        (blueink_docs / dd_bulletin), which is the better mechanism: it wires
        the pill to the right card instead of only suppressing a wrong one."""
        for rid in ("org_board_box_repull", "blueink_completed_sweep",
                    "leaders_call_mon", "new_start_followup_sat"):
            with self.subTest(report=rid):
                self.assertTrue(hc.is_internal(rid))

    def test_sync_launchd_system_would_not_recreate_a_deleted_substep(self):
        """The regression that made the promise false: this branch keyed only on
        _INFRA_AGENTS (the plist label), never on is_internal — so a job listed
        in _NOT_A_REPORT was carded straight back on the next sync."""
        PHANTOM = {"blueink_completed_sweep", "org_board_box_repull",
                   "blueink_docs_monday", "leaders_call_mon",
                   "new_start_followup_sat", "dd_bulletin_thu"}
        real = hc.existing_card_ids
        hc.existing_card_ids = lambda: real() - PHANTOM   # pretend they're gone
        try:
            msgs = hc.sync_launchd_system(dry_run=True)
        finally:
            hc.existing_card_ids = real
        offenders = [m for m in msgs
                     if any(c in m for c in PHANTOM)]
        self.assertEqual(offenders, [],
                         "deleting these rows would not stick: %s" % offenders)


class ARetiredReportLosesItsCardForGood(unittest.TestCase):
    """Switching a report off never removed its card, and the card came back.

    knocks_access_watch was switched off 2026-08-25 — agent unloaded, cadence
    weekdays [] — but on_scheduler stayed true, so hub_coverage kept it in
    _scheduler_reports() and its Report Library row kept advertising "4 AM flow ·
    DUE TODAY" for a job that had not run in a week. Deleting the row alone would
    not have held: sync() re-cards from schedule_config and sync_launchd_system()
    re-cards from deploy/*.plist, so a retirement has to shut BOTH doors."""

    def test_it_is_internal(self):
        from automations.day_orchestrator.hub_coverage import _RETIRED
        for rid in _RETIRED:
            with self.subTest(report=rid):
                self.assertTrue(hc.is_internal(rid))

    def test_it_is_off_the_scheduler_too(self):
        """_RETIRED stops the CARD; on_scheduler:false stops the RUN. A report
        listed here that is still on_scheduler would keep running invisibly —
        the exact shape of the never-run blind spot, upside down."""
        import json
        from automations.day_orchestrator.hub_coverage import _RETIRED, CONFIG_PATH
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["reports"]
        still_on = [rid for rid in _RETIRED
                    if cfg.get(rid, {}).get("on_scheduler")]
        self.assertEqual(still_on, [],
                         "retired but still on_scheduler: %s" % still_on)

    def test_neither_door_recreates_the_card(self):
        from automations.day_orchestrator.hub_coverage import _RETIRED
        real = hc.existing_card_ids
        hc.existing_card_ids = lambda: real() - set(_RETIRED)
        try:
            back = ([m for m in hc.sync(dry_run=True)
                     if any(r in m for r in _RETIRED)]
                    + [m for m in hc.sync_launchd_system(dry_run=True)
                       if any(r in m for r in _RETIRED)])
        finally:
            hc.existing_card_ids = real
        self.assertEqual(back, [], "a retired card would be recreated: %s" % back)


if __name__ == "__main__":
    unittest.main()
