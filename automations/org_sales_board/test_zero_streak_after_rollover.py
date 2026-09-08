"""The zero rule now rides each board's Tuesday rollover instead of its own card.

WHY (Eve, 2026-09-01): "incluilo en el proceso de roleo de los martes, no le
crees tarjeta aparte". The standalone card only ever read CLOSED literals
because its `order` (26) happened to sit after org_sales_board's (15) — an
ordering invisible from either entry, and one that did not exist at all for the
Country board (order 40). Hung off the roll, the precondition IS the trigger.

What these lock down, because all three are silent failures:
  * it must never raise into the board fill it is called from;
  * it must post NOTHING when the board did not actually roll;
  * it must propose, never remove.
"""
import datetime as dt
import unittest

from automations.org_sales_board import zero_streak as zs


def sheet(rows):
    """A worksheet stub whose .get() returns `rows` whatever is asked for."""
    class WS:
        def get(self, *a, **k):
            return rows
    class SH:
        def worksheet(self, _t):
            return WS()
    return SH()


# A minimal board: header row of WE labels, one section, three reps.
#   col A / col B / col C.. = WE columns, newest first
def board(live_label, cold_name="Cold Rep"):
    return [
        ["AT&T FIBER TEAM", "", live_label, "WE 08.30", "WE 08.23", "WE 08.16"],
        ["Fiber - All Units", "", "", "", "", ""],
        ["1", "Hot Rep", "10", "12", "9", "11"],
        ["2", cold_name, "0", "0", "0", "7"],
        ["3", "New Hire", "0", "", "", ""],
        ["TOTALS", "", "10", "12", "9", "18"],
    ]


def two_box_board(live_label, second_box):
    """Same banner, TWO campaigns — the shape the banner rule turns on.

    `second_box` is what 'Split Rep' did in the second campaign, newest closed
    week first. The rep is stone cold in the first one either way.
    """
    return [
        ["ALPHALETE ORG", "", live_label, "WE 08.30", "WE 08.23", "WE 08.16"],
        ["Retail Internet", "", "", "", "", ""],
        ["1", "Hot Rep", "10", "12", "9", "11"],
        ["2", "Split Rep", "0", "0", "0", "7"],
        ["TOTALS", "", "10", "12", "9", "18"],
        [],
        ["ALPHALETE ORG", "", live_label, "WE 08.30", "WE 08.23", "WE 08.16"],
        ["Retail NL", "", "", "", "", ""],
        ["1", "Split Rep", "0"] + second_box,
        ["TOTALS", "", "0"] + second_box,
    ]


class AfterRollover(unittest.TestCase):
    today = dt.date(2026, 9, 1)          # Tuesday; live week = WE 09.06

    def setUp(self):
        self.posted = []
        self._real_open, self._real_post = zs.open_by_key, zs.post_slack
        zs.post_slack = (lambda f, n, w, t, logfn=print, kept=(), tab="":
                         self.posted.append((f, n, kept, tab)))
        self.addCleanup(self._restore)

    def _restore(self):
        zs.open_by_key, zs.post_slack = self._real_open, self._real_post

    def test_rolled_board_proposes_the_cold_rep(self):
        zs.open_by_key = lambda _id: sheet(board("WE 09.06"))
        n = zs.after_rollover("sid", "tab", today=self.today, logfn=lambda m: None)
        self.assertEqual(n, 1)
        flags, _newbies, _kept, _tab = self.posted[0]
        self.assertEqual([f["name"] for f in flags], ["Cold Rep"])

    def test_a_board_that_did_not_roll_posts_nothing(self):
        """The roll failing is exactly when the newest CLOSED week is still col
        C's live formula. Scoring it would judge people on a week that has not
        been frozen — so say so and stay silent."""
        zs.open_by_key = lambda _id: sheet(board("WE 08.30"))
        said = []
        n = zs.after_rollover("sid", "tab", today=self.today, logfn=said.append)
        self.assertEqual(n, 0)
        self.assertEqual(self.posted, [])
        self.assertIn("did not land", " ".join(said))

    def test_dry_run_scores_but_does_not_post(self):
        zs.open_by_key = lambda _id: sheet(board("WE 09.06"))
        n = zs.after_rollover("sid", "tab", today=self.today, dry_run=True,
                              logfn=lambda m: None)
        self.assertEqual(n, 1)
        self.assertEqual(self.posted, [])

    def test_a_broken_read_never_raises_into_the_board_fill(self):
        """The caller has already rolled and filled a live board. A detector
        blowing up there would turn a good run into a FAILED one."""
        def boom(_id):
            raise RuntimeError("quota exceeded")
        zs.open_by_key = boom
        said = []
        self.assertEqual(
            zs.after_rollover("sid", "tab", today=self.today, logfn=said.append), 0)
        self.assertIn("SALTEADO", " ".join(said))

    def test_no_leaderboard_is_a_skip_not_a_crash(self):
        zs.open_by_key = lambda _id: sheet([["something", "else"]])
        self.assertEqual(
            zs.after_rollover("sid", "tab", today=self.today,
                              logfn=lambda m: None), 0)
        self.assertEqual(self.posted, [])

    def test_a_blank_history_is_never_a_streak(self):
        """'New Hire' has blanks, not zeros. Blank is missing data; counting it
        would propose every new rep for removal on their first Tuesday."""
        zs.open_by_key = lambda _id: sheet(board("WE 09.06"))
        zs.after_rollover("sid", "tab", today=self.today, logfn=lambda m: None)
        flags, newbies, _kept, _tab = self.posted[0]
        self.assertNotIn("New Hire", [f["name"] for f in flags])
        self.assertNotIn("New Hire", [f["name"] for f in newbies])


class TheBannerIsTheUnit(unittest.TestCase):
    """Cold in ONE campaign is not a removal when the same banner has another
    the rep still sells (Eve, 2026-09-08: "es que ana no debe salir mientras
    venda una retail"). Ana Griffin went out as a proposal, and half her rows
    were deleted, because the old `elsewhere` warning only looked at the live
    week and the last closed one — her last Retail NL sale was one week older
    than that.
    """
    today = dt.date(2026, 9, 1)          # live week = WE 09.06

    def setUp(self):
        self.posted = []
        self._real_open, self._real_post = zs.open_by_key, zs.post_slack
        zs.post_slack = (lambda f, n, w, t, logfn=print, kept=(), tab="":
                         self.posted.append((f, n, kept, tab)))
        self.addCleanup(self._restore)

    def _restore(self):
        zs.open_by_key, zs.post_slack = self._real_open, self._real_post

    def _run(self, second_box):
        zs.open_by_key = lambda _id: sheet(two_box_board("WE 09.06", second_box))
        n = zs.after_rollover("sid", "tab", today=self.today, logfn=lambda m: None)
        return n, self.posted[0]

    def test_a_sale_too_old_to_be_active_still_vetoes_the_removal(self):
        """WE 08.23 is two closed weeks back — outside the `elsewhere` window,
        inside the streak. That gap is the whole Ana Griffin case."""
        n, (flags, _newbies, kept, _tab) = self._run(["0", "6", "4"])
        self.assertEqual(n, 0, "nothing to remove")
        self.assertEqual([f["name"] for f in flags], [])
        self.assertEqual([f["name"] for f in kept], ["Split Rep"])
        self.assertEqual(kept[0]["kept_for"], ["ALPHALETE ORG/Retail NL"])

    def test_cold_in_every_box_of_the_banner_is_still_a_removal(self):
        """The veto is a warm sibling, not the mere existence of one."""
        n, (flags, _newbies, kept, _tab) = self._run(["0", "0", "9"])
        self.assertEqual(n, 2, "both boxes propose")
        self.assertEqual({f["name"] for f in flags}, {"Split Rep"})
        self.assertEqual(kept, [])


class ThePostNamesItsBoard(unittest.TestCase):
    """Two boards ride this detector into the SAME channel off their own rolls.
    On 2026-09-08 the ORG board proposed four people at 07:00 and the Country
    board posted "nadie llegó al umbral" at 09:50 — same title, no board name,
    so the second read like the first being retracted."""
    today = dt.date(2026, 9, 1)
    weeks = [dt.date(2026, 8, 30), dt.date(2026, 8, 23)]

    def test_the_empty_post_says_which_board(self):
        text = zs.build_post([], [], self.weeks, self.today,
                             tab="Country Sales Board")
        self.assertIn("Country Sales Board", text)

    def test_the_listing_post_says_which_board(self):
        flags = [{"name": "Cold Rep", "owner": "ALPHALETE ORG",
                  "section": "Retail NL", "streak": 2, "last_sale": "WE 08.16",
                  "elsewhere": [], "kept_for": []}]
        text = zs.build_post(flags, [], self.weeks, self.today,
                             tab="Alphalete ORG Sales Board")
        self.assertIn("Alphalete ORG Sales Board", text)
        self.assertIn("Cold Rep", text)

    def test_no_tab_still_builds(self):
        """after_rollover always passes one, but the default must not crash a
        hand-built post."""
        self.assertIn("Two-week zero rule",
                      zs.build_post([], [], self.weeks, self.today))


class NoStandaloneCard(unittest.TestCase):
    def test_the_card_is_off_the_scheduler(self):
        """Eve asked for no separate card. registry.load_config drops
        on_scheduler:false, so this is what "no card" actually means here — it
        never enters the morning batch. An explicit `lucy rerun` still resolves
        it through resolve_report(), which reads the raw config on purpose, and
        that hand-run handle is fine to keep."""
        from automations.day_orchestrator import registry
        cfg = registry.load_config()
        self.assertNotIn("org_board_zero_streak", cfg.reports)
        self.assertIsNotNone(
            registry.resolve_report(cfg, "org_board_zero_streak"),
            "a hand `lucy rerun` should still find it")


if __name__ == "__main__":
    unittest.main()
