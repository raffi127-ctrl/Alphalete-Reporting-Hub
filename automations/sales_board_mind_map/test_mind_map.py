"""Unit tests for the mind map's tree rules. No network, no Slack, no sheet.

    python -m unittest automations.sales_board_mind_map.test_mind_map
"""
from __future__ import annotations

import unittest

from automations.sales_board_mind_map import run as R


def rep(name, trainer="", *, week="5th wk+", team="Se7en Sins",
        level="level 1", apps=0.0, internet=0.0):
    return R.Rep(name=name, week=week, team=team, level=level, trainer=trainer,
                 apps=apps, internet=internet)


def quiet(*_a, **_k):
    pass


class TreeTests(unittest.TestCase):

    def test_trainer_becomes_the_parent(self):
        boss, kid = rep("Willie Henderson"), rep("Chloe Johnson", "Willie Henderson")
        roots = R.build_tree([boss, kid], logfn=quiet)
        self.assertEqual([r.name for r in roots], ["Willie Henderson"])
        self.assertEqual([c.name for c in boss.children], ["Chloe Johnson"])

    def test_office_trainer_and_blank_are_branch_roots(self):
        a, b = rep("Zoria Johnson", "Raf & JD"), rep("Ana Griffin", "")
        roots = R.build_tree([a, b], logfn=quiet)
        self.assertEqual({r.name for r in roots}, {"Zoria Johnson", "Ana Griffin"})

    def test_partial_and_decorated_trainer_names_resolve(self):
        # The board writes 'Willie' in one cell and 'Willie Henderson (NC)' in
        # another; both are the same person.
        boss = rep("Willie Henderson")
        short, decorated = rep("A", "Willie"), rep("B", "Willie Henderson (NC)")
        R.build_tree([boss, short, decorated], logfn=quiet)
        self.assertEqual(sorted(c.name for c in boss.children), ["A", "B"])

    def test_a_trainer_with_no_row_becomes_the_team_head(self):
        # Bas is above the board — no row of his own, but he is still the
        # upline, so the team hangs off HIM. [Megan 2026-09-20]
        a, b = rep("Elijah Rodriguez", "Bas"), rep("Andres Mejia", "BAS")
        roots = R.build_tree([a, b], logfn=quiet)
        # One head, not two — and shown with the full name Megan gave us, not
        # the "Bas" the Trainer cells type.
        self.assertEqual([x.display for x in roots], ["Basil Elhassan"])
        head = roots[0]
        self.assertTrue(head.offboard)
        self.assertEqual(sorted(c.name for c in head.children),
                         ["Andres Mejia", "Elijah Rodriguez"])
        self.assertIs(a.upline, head)

    def test_the_team_head_is_drawn_but_never_counted(self):
        r = rep("Elijah Rodriguez", "Bas", level="level 1")
        roots = R.build_tree([r], logfn=quiet)
        # 2 nodes in the branch, but the counts only know about the one rep.
        self.assertEqual(roots[0].size, 2)
        st = R.team_stats(list(roots[0].subtree()))
        self.assertEqual((st["total"], st["leaders"]), (1, 1))

    def test_a_trainer_loop_does_not_hang(self):
        a, b = rep("A", "B"), rep("B", "A")
        roots = R.build_tree([a, b], logfn=quiet)
        self.assertEqual(len(roots), 1)       # one of them keeps the other
        self.assertEqual(sum(r.size for r in roots), 2)

    def test_week_marker_comes_off_the_label(self):
        self.assertEqual(rep("Aundre Browder  (Wk 2)").display, "Aundre Browder")
        self.assertEqual(rep("Safiya Mahmoud (NC)").display, "Safiya Mahmoud")

    def test_an_internal_nickname_is_kept(self):
        self.assertEqual(rep("Noemi (Ivette) Ontiveros").display,
                         "Noemi (Ivette) Ontiveros")

    def test_dark_board_colours_get_white_text(self):
        self.assertEqual(R._ink("#B45F06"), "#ffffff")     # week 4 brown
        self.assertEqual(R._ink("#B6D7A8"), "#2f2b25")     # week 5+ green

    def test_the_cell_colour_wins_over_the_fallback_palette(self):
        r = rep("X", week="2nd wk")
        r.bg = "#123456"
        self.assertEqual(R._fill(r, {"2nd wk": "#FFE599"}), "#123456")
        self.assertEqual(R._fill(rep("Y", week="2nd wk"), {}), R.WEEK_FALLBACK["2nd wk"])


class StatsTests(unittest.TestCase):
    """Raf's vocabulary (2026-09-21): total active = week two and up, i.e.
    entry levels + leaders; a week one is a "Week 1 new start", never "in
    training"."""

    def _team(self):
        sub = [rep("a", level="mastermind", apps=10, internet=6),
               rep("b", level="level 1", apps=4, internet=2),
               rep("c", level="entry level", apps=2, internet=2),
               rep("d", level="in training", apps=0, internet=0)]
        ns = R.Rep(name="e", week="1st wk", team="", level="in training",
                   trainer="", new_start=True)
        return sub + [ns]

    def test_the_head_counts_are_raf_s_five_lines(self):
        st = R.team_stats(self._team(), terminated=3)
        self.assertEqual((st["total"], st["active"], st["leaders"],
                          st["entry"], st["week1"], st["terminated"]),
                         (5, 3, 2, 1, 2, 3))

    def test_averages_divide_team_production_by_who_should_sell(self):
        st = R.team_stats(self._team())
        # 16 apps / 2 leaders, and / 3 entry+leaders
        self.assertEqual(st["apps_per_leader"], "8.0")
        self.assertEqual(st["apps_per_active"], "5.3")
        self.assertEqual(st["int_per_leader"], "5.0")

    def test_no_leaders_reads_as_a_dash_not_a_zero(self):
        st = R.team_stats([rep("solo", level="entry level", apps=3)])
        self.assertEqual(st["apps_per_leader"], "—")
        self.assertEqual(st["apps_per_active"], "3.0")

    def test_the_bubble_carries_the_leadership_status(self):
        # Raf's shorthand, not the board's wording (Megan 2026-09-21).
        self.assertEqual(rep("x", level="level 2").rank, "Lvl 2")
        self.assertEqual(rep("y", level="in training").rank, "WK1 New Start")
        self.assertIn("Lvl 2", R._node(rep("x", level="level 2"), {}))


class TeamTests(unittest.TestCase):
    """The main teams, and which branch belongs to which (Megan 2026-09-20:
    Ceaseless = Willie, Se7en Sins = Al Kennel, Hashiras = Bas, Alphaletes has
    no main leader)."""

    def _office(self):
        board = [
            rep("Willie Henderson", "Raf & JD", team="Ceaseless"),
            rep("Chloe Johnson", "Willie Henderson", team="Ceaseless"),
            rep("Jordan Ruiz", "Willie Henderson", team="Ceaseless"),
            rep("Anthony Marchetti", "Algemar Kennel", team="Se7en Sins"),
            rep("Nima Aweida", "Algemar Kennel", team="Se7en Sins"),
            rep("Benjamin Kushpit", "Bas", team="Hashiras"),
            rep("Safiya Mahmoud", "Raf & JD", team="Alphaletes"),
            rep("Zoria Johnson", "Raf & JD", team="Alphaletes"),
        ]
        return board, R.build_tree(board, logfn=quiet)

    def test_sections_are_the_main_teams(self):
        _, roots = self._office()
        self.assertEqual([t for t, _ in R.group_by_team(roots)],
                         ["Ceaseless", "Se7en Sins", "Alphaletes", "Hashiras"])

    def test_an_offboard_head_inherits_the_team_of_its_people(self):
        _, roots = self._office()
        heads = {b.display: R.branch_team(b) for b in roots}
        self.assertEqual(heads["Algemar Kennel"], "Se7en Sins")
        self.assertEqual(heads["Basil Elhassan"], "Hashiras")

    def test_the_main_leader_is_named_only_when_one_head_carries_the_team(self):
        _, roots = self._office()
        leads = {t: R.team_lead(b) for t, b in R.group_by_team(roots)}
        self.assertEqual(leads["Ceaseless"].display, "Willie Henderson")
        self.assertEqual(leads["Se7en Sins"].display, "Algemar Kennel")
        self.assertIsNone(leads["Alphaletes"])   # two equal heads, no main lead

    def test_bubble_structure_counts_first_gens_and_whole_team(self):
        board, _ = self._office()
        willie = next(r for r in board if r.name == "Willie Henderson")
        self.assertEqual(R.structure(willie), (2, 2))
        self.assertIn("2/2", R._node(willie, {}))


class LeaverTests(unittest.TestCase):
    """A trainer who is gone hands their people to their OWN upline
    (Megan 2026-09-20: "his team goes to his upline")."""

    def test_a_departed_trainer_does_not_come_back_as_a_head(self):
        chloe = rep("Chloe Johnson", "Willie Henderson", team="Ceaseless")
        willie = rep("Willie Henderson", "Raf & JD", team="Ceaseless")
        lemsy = rep("Lemsy Vazquez", "Deavion", team="Ceaseless")
        roots = R.build_tree([willie, chloe, lemsy],
                             departed={"deavion allen": ("Chloe Johnson",
                                                         "Ceaseless")},
                             logfn=quiet)
        self.assertEqual([r.name for r in roots], ["Willie Henderson"])
        self.assertIn("Lemsy Vazquez", [c.name for c in chloe.children])
        self.assertFalse(any(r.offboard for r in willie.subtree()))

    def test_it_walks_more_than_one_leaver(self):
        boss = rep("Willie Henderson", "Raf & JD")
        orphan = rep("Someone", "Gone One")
        R.build_tree([boss, orphan],
                     departed={"gone one": ("Gone Two", ""),
                               "gone two": ("Willie Henderson", "")},
                     logfn=quiet)
        self.assertEqual([c.name for c in boss.children], ["Someone"])

    def test_a_leaver_who_reported_to_the_office_leaves_a_branch_head(self):
        orphan = rep("Someone", "Gone One")
        orphan.team = ""
        roots = R.build_tree([orphan],
                             departed={"gone one": ("Raf & JD", "Ceaseless")},
                             logfn=quiet)
        self.assertEqual([r.name for r in roots], ["Someone"])
        self.assertFalse(roots[0].offboard)
        # and they keep the leaver's team rather than landing on "No team"
        self.assertEqual(roots[0].team, "Ceaseless")

    def test_a_trainer_who_was_never_on_the_board_still_heads_the_team(self):
        r = rep("Elijah Rodriguez", "Bas")
        roots = R.build_tree([r], departed={}, logfn=quiet)
        self.assertTrue(roots[0].offboard)
        self.assertEqual(roots[0].display, "Basil Elhassan")


class PlanTests(unittest.TestCase):
    """The team leader is drawn once, on the roof, and planning twice gives the
    same answer — plan_teams used to re-parent the tree it was reading."""

    def _office(self):
        willie = rep("Willie Henderson", "Raf & JD", team="Ceaseless")
        chloe = rep("Chloe Johnson", "Willie Henderson", team="Ceaseless")
        jordan = rep("Jordan Ruiz", "Willie Henderson", team="Ceaseless")
        kid = rep("Yani Young", "Jordan Ruiz", team="Ceaseless")
        reps = [willie, chloe, jordan, kid]
        return reps, R.build_tree(reps, logfn=quiet)

    def test_the_leader_moves_to_the_roof_and_their_1st_gens_become_branches(self):
        reps, roots = self._office()
        (team, branches, lead, name, first, members), = R.plan_teams(roots, reps)
        self.assertEqual((team, name, first), ("Ceaseless", "Willie Henderson", 2))
        self.assertEqual(sorted(b.display for b in branches),
                         ["Chloe Johnson", "Jordan Ruiz"])
        self.assertEqual(lead.display, "Willie Henderson")
        self.assertNotIn(lead, branches)      # named on the roof, not drawn
        self.assertEqual(len(members), 4)     # the leader still counts as a body

    def test_planning_twice_gives_the_same_office(self):
        reps, roots = self._office()
        first = R.plan_teams(roots, reps)
        second = R.plan_teams(roots, reps)
        self.assertEqual([(t, len(b), n, f, len(m))
                          for t, b, _l, n, f, m in first],
                         [(t, len(b), n, f, len(m))
                          for t, b, _l, n, f, m in second])


if __name__ == "__main__":
    unittest.main()


class WeekTabTests(unittest.TestCase):
    """Monday draws the week that just closed (Megan 2026-09-21)."""

    class _Sheet:
        pass

    def setUp(self):
        import datetime as dt
        from automations.terminated_reps import board as BD
        self.dt, self.BD = dt, BD
        self.tabs = [(dt.date(2026, 9, 13), "Sales Board WE 9.13"),
                     (dt.date(2026, 9, 20), "Sales Board WE 9.20"),
                     (dt.date(2026, 9, 27), "Sales Board WE 9.27")]
        self._week_tabs, self._pick = BD.week_tabs, BD.pick_tab
        BD.week_tabs = lambda sh, today: list(self.tabs)
        BD.pick_tab = lambda sh, today, want=None: "Sales Board WE 9.27"

    def tearDown(self):
        self.BD.week_tabs, self.BD.pick_tab = self._week_tabs, self._pick

    def test_monday_reads_last_week_even_when_the_new_tab_exists(self):
        monday = self.dt.date(2026, 9, 21)
        self.assertEqual(R.week_tab_for(self._Sheet(), monday, logfn=quiet),
                         "Sales Board WE 9.20")

    def test_every_other_day_reads_its_own_week(self):
        for day in (22, 23, 26, 27):        # Tue, Wed, Sat, Sun
            d = self.dt.date(2026, 9, day)
            self.assertEqual(R.week_tab_for(self._Sheet(), d, logfn=quiet),
                             "Sales Board WE 9.27")


class TerminatedTests(unittest.TestCase):
    """Raf 2026-09-21: terminated this week stays on the map, struck through,
    and counts only as a termination."""

    def _team(self):
        boss = rep("Willie Henderson", "Raf & JD", team="Ceaseless", level="level 2")
        kid = rep("Chloe Johnson", "Willie Henderson", team="Ceaseless")
        gone = rep("Gregory Beamon", "Willie Henderson", team="Ceaseless",
                   level="in training")
        gone.terminated = True
        # somebody the terminated rep trained
        orphan = rep("Paris Carroll", "Gregory Beamon", team="Ceaseless",
                     level="in training")
        reps = [boss, kid, gone, orphan]
        R.build_tree(reps, departed={"gregory beamon":
                                     ("Willie Henderson", "Ceaseless")},
                     logfn=quiet)
        return boss, kid, gone, orphan

    def test_the_terminated_stay_on_the_map_under_their_trainer(self):
        boss, _kid, gone, _o = self._team()
        self.assertIn(gone, boss.children)
        html = R._node(gone, {})
        self.assertIn(" gone", html)
        self.assertIn("Terminated", html)

    def test_nobody_hangs_off_a_struck_through_name(self):
        boss, _kid, gone, orphan = self._team()
        self.assertEqual(gone.children, [])
        self.assertIs(orphan.upline, boss)    # rolled up past them

    def test_they_count_as_terminations_and_nothing_else(self):
        boss, *_ = self._team()
        st = R.team_stats(list(boss.subtree()))
        self.assertEqual((st["total"], st["terminated"]), (3, 1))
        self.assertEqual(R.structure(boss), (2, 2))   # Chloe + Paris, not Gregory
