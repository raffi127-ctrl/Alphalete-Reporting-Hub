"""The Org / Country board emails' auto-send (Eve 2026-10-07).

Pins the decisions, not the Slack wording:
  * a clean weekday goes out with nothing posted;
  * a NEW OWNER holds a weekday for the ✅ and names who; on a weekend it goes
    out anyway with a heads-up;
  * a visual blocker is rebuilt once, then held; a visual check that can't run
    holds (fail closed);
  * a dirty chain holds, and once it clears the email is rebuilt once before
    it goes;
  * not built yet = wait quietly; already sent = do nothing.

    python -m unittest automations.board_emails.test_auto_send
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from automations.board_emails import auto_send as A

THU = dt.date(2026, 10, 8)
SAT = dt.date(2026, 10, 10)

GRID = [["", "Owner"], ["1", "Chan Park"], ["2", "Wayne Rude"],
        ["TOTALS", ""], ["WE 10.4", "Sahil Multani"]]


class Fake:
    """A board, its hooks, and every call they got."""

    def __init__(self, tmp: Path, day: dt.date, built: bool = True):
        self.calls = []
        self.dir = tmp / "imgs"
        self.dir.mkdir(exist_ok=True)
        self.built = built
        self.day = day
        if built:
            self.write_images()
        self.post = False
        self.target = A.Target("t", "Test Board", "test_report",
                               self.images, lambda: GRID)

    def write_images(self, payload: bytes = b"x" * 500):
        for n in ("board", "daily"):
            p = self.dir / f"{n}.png"
            p.write_bytes(payload)
            noon = time.mktime(dt.datetime.combine(
                self.day, dt.time(12)).timetuple())
            os.utime(p, (noon, noon))

    def images(self, day):
        if not self.built:
            raise RuntimeError("no manifest")
        return [(n, self.dir / f"{n}.png") for n in ("board", "daily")]

    def hooks(self, rc: int = 0) -> A.Hooks:
        def post_link(fyi):
            self.post = True
            self.calls.append(("post", fyi))

        def reply(text, mark):
            self.calls.append(("reply", text))
            return True

        def rebuild():
            self.calls.append(("rebuild",))
            self.write_images(b"y" * 500)        # new images, new hash

        return A.Hooks(
            has_post=lambda: self.post, post_link=post_link, reply=reply,
            rebuild=rebuild,
            send=lambda: self.calls.append(("send",)) or rc,
            confirm=lambda who: self.calls.append(("confirm", who)),
            record=lambda who: self.calls.append(("record", who)),
            mentions="<@EVE>")

    def kinds(self):
        return [c[0] for c in self.calls]


def ok_visual(new, prior):
    return {"ok": True, "issues": []}


def bad_visual(new, prior):
    return {"ok": False, "issues": [{"image": 1, "section": "Daily Sales",
                                     "problem": "10/7 column empty",
                                     "severity": "blocker"}]}


class AutoSendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(A, "STATE_DIR", self.tmp / "state")
        p.start()
        self.addCleanup(p.stop)
        a = mock.patch.object(A, "_alert")
        self.alert = a.start()
        self.addCleanup(a.stop)
        c = mock.patch.object(A, "_close")
        c.start()
        self.addCleanup(c.stop)

    def run_once(self, fake, day, *, names=None, visual=ok_visual,
                 clean=(True, "clean"), tableau=()):
        return A.run(fake.target, day, fake.hooks(),
                     clean=lambda: clean, tableau=lambda: list(tableau),
                     names=names or (lambda: {"Chan Park", "Wayne Rude"}),
                     visual=visual, verbose=False)

    def seed_roster(self, fake, names=("Chan Park", "Wayne Rude")):
        A.new_owners(fake.target, THU - dt.timedelta(days=3), set(names))

    # ---- the clean day ----------------------------------------------------
    def test_clean_weekday_sends_without_posting(self):
        f = Fake(self.tmp, THU)
        self.seed_roster(f)
        self.assertEqual(self.run_once(f, THU), 0)
        self.assertEqual(f.kinds(), ["record", "send"])
        self.assertTrue(A.local_sent(f.target, THU))
        # the next pass does nothing at all
        f.calls.clear()
        self.assertEqual(self.run_once(f, THU), 0)
        self.assertEqual(f.calls, [])

    def test_first_day_is_the_baseline_nobody_is_new(self):
        f = Fake(self.tmp, THU)
        self.assertEqual(self.run_once(f, THU), 0)
        self.assertNotIn("post", f.kinds())

    # ---- new owners --------------------------------------------------------
    def test_new_owner_holds_a_weekday_and_names_them(self):
        f = Fake(self.tmp, THU)
        self.seed_roster(f)
        rc = self.run_once(f, THU, names=lambda: {"Chan Park", "Wayne Rude",
                                                  "Samuel Acay"})
        self.assertEqual(rc, 1)
        self.assertNotIn("send", f.kinds())
        self.assertIn(("post", False), f.calls)
        text = [c[1] for c in f.calls if c[0] == "reply"][0]
        self.assertIn("Samuel Acay", text)
        self.assertIn(A.NEW_OWNER_MARK, text)

    def test_new_owner_stays_new_all_day(self):
        f = Fake(self.tmp, THU)
        self.seed_roster(f)
        names = lambda: {"Chan Park", "Wayne Rude", "Samuel Acay"}  # noqa: E731
        self.run_once(f, THU, names=names)
        f.calls.clear()
        self.assertEqual(self.run_once(f, THU, names=names), 1)
        self.assertNotIn("send", f.kinds())

    def test_new_owner_on_a_weekend_goes_out_with_a_heads_up(self):
        f = Fake(self.tmp, SAT)
        self.seed_roster(f)
        rc = self.run_once(f, SAT, names=lambda: {"Chan Park", "Wayne Rude",
                                                  "Samuel Acay"})
        self.assertEqual(rc, 0)
        self.assertIn("send", f.kinds())
        self.assertIn(("post", True), f.calls)          # FYI, not "approve"
        self.assertTrue(any("Samuel Acay" in c[1] for c in f.calls
                            if c[0] == "reply"))

    def test_the_visual_check_is_told_who_is_new(self):
        f = Fake(self.tmp, SAT)
        self.seed_roster(f)
        seen = []
        self.run_once(f, SAT, names=lambda: {"Chan Park", "Wayne Rude",
                                             "Samuel Acay"},
                      visual=lambda new, prior: seen.append(new) or
                      {"ok": True, "issues": []})
        self.assertEqual(seen, [["Samuel Acay"]])

    # ---- the visual check ---------------------------------------------------
    def test_visual_blocker_rebuilds_once_then_holds(self):
        f = Fake(self.tmp, THU)
        self.seed_roster(f)
        self.assertEqual(self.run_once(f, THU, visual=bad_visual), 1)
        self.assertEqual(f.kinds(), ["rebuild"])
        f.calls.clear()
        self.assertEqual(self.run_once(f, THU, visual=bad_visual), 1)
        self.assertNotIn("send", f.kinds())
        self.assertNotIn("rebuild", f.kinds())
        self.assertIn(("post", False), f.calls)
        self.assertTrue(self.alert.called)

    def test_rebuild_that_fixes_it_sends_with_the_link(self):
        f = Fake(self.tmp, THU)
        self.seed_roster(f)
        self.run_once(f, THU, visual=bad_visual)
        f.calls.clear()
        self.assertEqual(self.run_once(f, THU), 0)
        self.assertIn("send", f.kinds())
        self.assertIn(("post", True), f.calls)
        self.assertTrue(any(A.REBUILT_MARK in c[1] for c in f.calls
                            if c[0] == "reply"))

    def test_visual_check_that_cannot_run_holds(self):
        f = Fake(self.tmp, THU)
        self.seed_roster(f)

        def boom(new, prior):
            raise RuntimeError("no API key")
        self.assertEqual(self.run_once(f, THU, visual=boom), 1)
        self.assertNotIn("send", f.kinds())
        self.assertNotIn("rebuild", f.kinds())

    def test_minor_issues_do_not_hold(self):
        f = Fake(self.tmp, THU)
        self.seed_roster(f)
        minor = lambda new, prior: {"ok": True, "issues": [  # noqa: E731
            {"image": 1, "section": "x", "problem": "y", "severity": "minor"}]}
        self.assertEqual(self.run_once(f, THU, visual=minor), 0)

    # ---- the chain and Tableau ---------------------------------------------
    def test_dirty_chain_holds_then_rebuilds_once_when_it_clears(self):
        f = Fake(self.tmp, THU)
        self.seed_roster(f)
        rc = self.run_once(f, THU, clean=(False, "org_sales_board (FAILED)"))
        self.assertEqual(rc, 1)
        self.assertNotIn("send", f.kinds())
        self.assertIn(("post", False), f.calls)
        f.calls.clear()
        self.assertEqual(self.run_once(f, THU), 1)
        self.assertEqual(f.kinds(), ["rebuild"])
        f.calls.clear()
        self.assertEqual(self.run_once(f, THU), 0)
        self.assertIn("send", f.kinds())

    def test_stale_tableau_holds(self):
        f = Fake(self.tmp, SAT)
        self.seed_roster(f)
        rc = self.run_once(f, SAT, tableau=["D2D1-PAGERV4 (data only through "
                                            "2026-10-08)"])
        self.assertEqual(rc, 1)
        self.assertNotIn("send", f.kinds())

    # ---- waiting / errors ---------------------------------------------------
    def test_not_built_yet_waits_quietly(self):
        f = Fake(self.tmp, THU, built=False)
        self.assertEqual(self.run_once(f, THU), 1)
        self.assertEqual(f.calls, [])

    def test_failed_send_is_not_recorded_as_sent(self):
        f = Fake(self.tmp, THU)
        self.seed_roster(f)
        rc = A.run(f.target, THU, f.hooks(rc=3), clean=lambda: (True, ""),
                   tableau=lambda: [], names=lambda: {"Chan Park", "Wayne Rude"},
                   visual=ok_visual, verbose=False)
        self.assertEqual(rc, 3)
        self.assertFalse(A.local_sent(f.target, THU))

    def test_totals_that_disagree_rebuild_once_then_hold(self):
        # 2026-10-08: Org 1886 beside All Units 1841 went out unnoticed.
        f = Fake(self.tmp, THU)
        self.seed_roster(f)
        f.target.totals = lambda day: ["All Units total (1841) doesn't match"]
        self.assertEqual(self.run_once(f, THU), 1)
        self.assertEqual(f.kinds(), ["rebuild"])
        f.calls.clear()
        self.assertEqual(self.run_once(f, THU), 1)
        self.assertNotIn("send", f.kinds())
        self.assertTrue(self.alert.called)

    def test_totals_that_agree_after_the_rebuild_send(self):
        f = Fake(self.tmp, THU)
        self.seed_roster(f)
        state = {"bad": True}
        f.target.totals = lambda day: (["mismatch"] if state["bad"] else [])
        self.run_once(f, THU)
        state["bad"] = False
        f.calls.clear()
        self.assertEqual(self.run_once(f, THU), 0)
        self.assertIn("send", f.kinds())

    def test_image_from_yesterday_is_a_problem(self):
        f = Fake(self.tmp, THU)
        old = time.mktime(dt.datetime(2026, 10, 7, 9).timetuple())
        os.utime(f.dir / "board.png", (old, old))
        self.assertIn("image(s) not built today: board",
                      A.structural_issues(f.target, THU))


class PureTest(unittest.TestCase):
    def test_owner_names_only_ranked_rows(self):
        self.assertEqual(A.owner_names(GRID), {"Chan Park", "Wayne Rude"})

    def test_grand_total_found_by_header_and_label(self):
        from automations.org_sales_board import screenshot_email as se
        org = [["", "Product Summary"],
               ["", "Product Type", "Monday", "Grand Total"],
               ["", "BOX", "31", "114"], ["", "Grand Total", "631", "1,886"]]
        acb = [["", "Product Type", "Monday", "Grand\nTotal"],
               ["", "All Units", "631", "1841"]]
        self.assertEqual(se.grand_total(org, "Grand Total"), 1886)
        self.assertEqual(se.grand_total(acb, "All Units"), 1841)
        self.assertIsNone(se.grand_total(acb, "Nope"))

    def test_org_totals_unreadable_or_missing_holds(self):
        from automations.org_sales_board import screenshot_email as se
        for got, want in ((None, "not recorded"),
                          ({"org": 1886, "all_units": None}, "All Units"),
                          ({"org": 1886, "all_units": 1841}, "1841"),
                          ({"org": 1886, "all_units": 1886}, None)):
            with mock.patch.object(se, "captured_totals", return_value=got):
                out = A._org_totals(THU)
            if want is None:
                self.assertEqual(out, [])
            else:
                self.assertTrue(out and want in out[0], (got, out))

    def test_off_before_the_start_date(self):
        self.assertFalse(A.is_on(dt.date(2026, 10, 7)))
        self.assertTrue(A.is_on(THU))
        self.assertFalse(A.is_on(THU, enabled=False))


if __name__ == "__main__":
    unittest.main()
