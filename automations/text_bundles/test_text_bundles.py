"""Text bundles (Carlos 2026-11-27): reports drop into a bundle, the bundle
goes out as one PDF per chat. No Messages, no Sheets."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from automations.b2b_dispositions import config as B
from automations.b2b_dispositions import text_post as tp
from automations.text_bundles import config as C
from automations.text_bundles import run as R
from automations.text_bundles import store as ST


def _png(path: Path, color=(200, 0, 0), size=(300, 120)) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(C, "ROOT", self.tmp / "bundles")
        p.start()
        self.addCleanup(p.stop)
        self.day = dt.date(2026, 11, 30)          # a Monday
        self.now = dt.datetime(2026, 11, 30, 7, 5)


class Store(_Tmp):
    def test_bad_tokens_fail(self):
        with self.assertRaises(ValueError):
            ST.parse_token("BUNDLE:nope:tracker")
        with self.assertRaises(ValueError):
            ST.parse_token("BUNDLE:morning:nope")

    def test_drop_then_read_and_a_rerun_replaces(self):
        a = _png(self.tmp / "a.png")
        ST.drop("BUNDLE:morning:tracker", "NDS — Nov 30", [a], now=self.now)
        ST.drop("BUNDLE:morning:tracker", "NDS — Nov 30 (2)", [a, a], now=self.now)
        got = ST.parts("morning", self.day)
        self.assertEqual(list(got), ["tracker"])
        self.assertEqual(got["tracker"]["text"], "NDS — Nov 30 (2)")
        self.assertEqual(len(got["tracker"]["images"]), 2)

    def test_after_sent_a_part_is_texted_alone(self):
        ST.mark_sent("morning", self.day)
        with mock.patch.object(ST, "late_send", return_value={"late": True}) as late:
            ST.drop("BUNDLE:morning:tracker", "NDS", [_png(self.tmp / "a.png")], now=self.now)
        late.assert_called_once()
        self.assertEqual(ST.parts("morning", self.day), {})


class Due(unittest.TestCase):
    def test_ticks(self):
        mon = dt.datetime(2026, 11, 30, 7, 31)
        self.assertEqual(R.due(mon), [("morning", False)])
        self.assertEqual(R.due(mon.replace(hour=8, minute=30)), [("morning", True)])
        self.assertEqual(R.due(mon.replace(hour=11, minute=35)), [("weeks", False)])
        self.assertEqual(R.due(mon.replace(hour=12, minute=1)), [("weeks", True)])
        self.assertEqual(R.due(mon.replace(hour=10, minute=0)), [])
        sat = dt.datetime(2026, 12, 5, 11, 35)
        self.assertEqual(R.due(sat), [])                  # weeks: Mon-Fri only


class Send(_Tmp):
    def _fill_morning(self, skip=()):
        for pid, label, _d in C.BUNDLES["morning"]["parts"]:
            if pid in skip:
                continue
            text = ("Good Morning Team\n1st rounds: 3" if pid == "schedule" else label)
            ST.drop("BUNDLE:morning:" + pid, text, [_png(self.tmp / (pid + ".png"))], now=self.now)

    def test_waits_for_missing_parts_until_the_final_tick(self):
        self._fill_morning(skip=("second_rounds",))
        with mock.patch("automations.day_orchestrator.text_outbox.drop") as drop:
            R.send_bundle("morning", self.day, final=False, send=True)
            drop.assert_not_called()
            self.assertFalse(ST.is_sent("morning", self.day))
            R.send_bundle("morning", self.day, final=True, send=True)
            drop.assert_called_once()
        self.assertTrue(ST.is_sent("morning", self.day))

    def test_complete_bundle_goes_as_one_pdf_to_both_chains(self):
        self._fill_morning()
        with mock.patch("automations.day_orchestrator.text_outbox.drop") as drop, \
             mock.patch("automations.b2b_dispositions.run.OUTPUT_DIR", self.tmp / "out"):
            R.send_bundle("morning", self.day, final=False, send=True)
        mp = Path(drop.call_args[0][0])
        man = json.loads(mp.read_text())
        self.assertEqual(man["kind"], "bundle_morning")
        (pdf,) = man["by_campaign"][C.TEXT_CAMPAIGN]
        self.assertTrue(pdf.endswith(".pdf") and Path(pdf).exists())
        self.assertEqual(B.TEXT_ROUTES[(C.TEXT_CAMPAIGN, "bundle_morning")],
                         [B.TEXT_GROUP_ALL, B.TEXT_GROUP_ATT])
        # once a day
        with mock.patch("automations.day_orchestrator.text_outbox.drop") as again:
            R.send_bundle("morning", self.day, final=True, send=True)
        again.assert_not_called()

    def test_page_order_follows_config(self):
        self._fill_morning()
        pages, _ = R.assemble("morning", self.day)
        self.assertEqual([p[0] for p in pages][0], "NDS Tracker")
        self.assertEqual(pages[1][0], "Today's 1st/2nd-round schedule")   # multi-line text keeps its body
        self.assertIn("1st rounds", pages[1][1])

    def test_weeks_get_the_teams_box_after_the_week_ones(self):
        for pid in ("nds_week1", "vz_week1", "nds_weeks", "vz_weeks"):
            ST.drop("BUNDLE:weeks:" + pid, pid, [_png(self.tmp / (pid + ".png"))], now=self.now)
        teams = {"text": "", "images": [str(_png(self.tmp / "teams.png"))]}
        with mock.patch.object(R, "_teams_part", return_value=teams):
            pages, _ = R.assemble("weeks", self.day)
        self.assertEqual([p[0] for p in pages],
                         ["nds_week1", "vz_week1", "AT&T teams, week so far", "nds_weeks", "vz_weeks"])


class Routes(_Tmp):
    def test_text_post_drops_instead_of_texting(self):
        a = _png(self.tmp / "a.png")
        with mock.patch.object(tp, "resolve_group") as resolve, \
             mock.patch.object(tp, "_osascript") as osa, \
             mock.patch.object(ST, "drop", return_value={"late": False}) as drop:
            r = tp.send_to_group("BUNDLE:morning:tracker", "NDS", [a], dry_run=False)
            tp.send_text_to_group("BUNDLE:morning:schedule", "Good morning", dry_run=False)
        self.assertTrue(r["ok"] and r["bundle"])
        self.assertEqual(drop.call_count, 2)
        resolve.assert_not_called()
        osa.assert_not_called()

    def test_dry_run_drops_nothing(self):
        with mock.patch.object(ST, "drop") as drop:
            tp.send_to_group("BUNDLE:morning:tracker", "NDS", [], dry_run=True)
        drop.assert_not_called()

    def test_every_bundle_token_in_the_routes_is_valid(self):
        from automations.tracker_texts import config as TT
        toks = [g for gs in list(B.TEXT_ROUTES.values()) + list(TT.ROUTES.values())
                for g in gs if g.startswith(C.PREFIX)]
        self.assertGreaterEqual(len(toks), 8)
        for t in toks:
            ST.parse_token(t)

    def test_carlos_asked_for(self):
        r = B.TEXT_ROUTES
        self.assertEqual(r[("NDS METRICS", "nds_churn_by_rep")], [])
        self.assertNotIn(("NDS METRICS", "nds_churn_rates"), {k for k, v in r.items() if v})
        self.assertEqual(r[("2ND ROUNDS", "second_rounds_leaders_att")], [])
        from automations.recruiting_day_texts import run as RD
        self.assertEqual(RD.sender_for("carlos", "morning"), "Lucy 2")
        self.assertEqual(RD.sender_for("carlos", "showed"), "Lucy 1")
        self.assertEqual(RD.sender_for("raf", "morning"), "Lucy 1")


if __name__ == "__main__":
    unittest.main()
