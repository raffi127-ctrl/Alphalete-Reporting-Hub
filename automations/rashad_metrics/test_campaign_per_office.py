"""The TeleMapper campaign is a PER-OFFICE decision, not a process-wide one.

Before this, `_pin_campaign` read one module global, so every office got pinned
to RES AT&T — including the wireless offices that never knock it. It went
unnoticed because one run used to mean one office; an on-demand request pulls
the asked-for office AND the comparison office in the SAME session, so the two
have to be able to disagree.

Offline: no ownerville, no network. The page is a stub that records navigation.
"""
import unittest

from automations.rashad_metrics import knocks_pull as KP


class _StubPage:
    """Records goto() calls instead of driving a browser."""

    def __init__(self):
        self.gotos = []

    def goto(self, url, **kw):
        self.gotos.append(url)

    def wait_for_timeout(self, ms):
        pass


class CampaignForOffice(unittest.TestCase):

    def test_an_nds_office_still_knocks_the_default_campaign(self):
        # Isaiah IS NDS, and that is why his Disposition page is empty — his
        # reps don't disposition, so there are no knock counts to pull. It is
        # NOT why the campaign would differ: his picker offers BASE Energy /
        # RES AT&T / RES-ENERGYWELL and he knocks RES AT&T like everyone
        # (Megan checked ownerville 2026-08-25). Deriving the pin from NDS
        # left his session free to drift onto another campaign and go quiet.
        self.assertEqual(KP.campaign_for_office("Isaiah Revelle"),
                         KP.KNOCKS_CAMPAIGN_ID)

    def test_every_known_office_gets_the_default(self):
        for name in ("Rafael Hidalgo", "Chan Park", "Haytham Nagi",
                     "Rashad Reed", "Isaiah Revelle"):
            with self.subTest(name=name):
                self.assertEqual(KP.campaign_for_office(name),
                                 KP.KNOCKS_CAMPAIGN_ID)

    def test_unknown_name_falls_back_to_the_default(self):
        self.assertEqual(KP.campaign_for_office("Nobody At All"),
                         KP.KNOCKS_CAMPAIGN_ID)
        self.assertEqual(KP.campaign_for_office(""), KP.KNOCKS_CAMPAIGN_ID)

    def test_an_override_wins_when_one_is_written_down(self):
        # The escape hatch for an office PROVEN to knock something else.
        KP.CAMPAIGN_OVERRIDES["someone else"] = "16"
        try:
            self.assertEqual(KP.campaign_for_office("Someone Else"), "16")
            self.assertEqual(KP.campaign_for_office("  SOMEONE   ELSE "), "16")
        finally:
            KP.CAMPAIGN_OVERRIDES.pop("someone else", None)

    def test_overrides_are_observed_not_guessed(self):
        # The map was empty by design: a GUESSED override silently blanks an
        # office's whole board. Calvin is the first observed exception —
        # invD2DClientId=40 (RES-ENERGYWELL), read off his live URL on
        # 2026-08-29 — so the rule is now "only observed entries", not "none".
        self.assertEqual(set(KP.CAMPAIGN_OVERRIDES.values()), {"40", "2"},
                         "every override must be an observed campaign id")
        # The CANONICAL name only. "Calvin Rivera" is the alias sheet's job —
        # every caller resolves it before this map is consulted — and listing
        # it here too would be the per-report patch aliases exist to replace.
        self.assertEqual(KP.campaign_for_office("Calvin Ribera"), "40")

    def test_a_b2b_office_is_not_pinned_to_a_residential_campaign(self):
        # Carlos's office (11580) is B2B and never runs RES AT&T. The default
        # pin sent his session to 3 anyway, and the board came back looking
        # fine only because his office renders its own B2B AT&T grid unpinned.
        self.assertEqual(KP.campaign_for_office("Carlos Hidalgo"), "2")
        self.assertIn("2", KP.CAMPAIGN_EXPECTED_SHAPE,
                      "his pin must be one the shape guard can check — the "
                      "point of moving him off 3")

    def test_everyone_else_still_gets_the_default(self):
        # The override map must not leak onto offices that never asked.
        for name in ("Rafael Hidalgo", "Chan Park", "Isaiah Jones"):
            self.assertEqual(KP.campaign_for_office(name),
                             KP.KNOCKS_CAMPAIGN_ID)


class MultiCampaignOffices(unittest.TestCase):
    """An office that knocks two campaigns must be ASKED about, not guessed at.

    Megan, 2026-09-09: "I asked for Carlos' knocks and it didn't ask me which
    campaign, even though he runs 2." He was missing from MULTI_CAMPAIGN, so
    `/knocks` skipped the picker and handed back one campaign as if it were
    the office.
    """

    def test_carlos_runs_two_and_both_are_offered(self):
        opts = KP.campaigns_for("Carlos Hidalgo")
        self.assertEqual([cid for _l, cid, _k in opts], ["2", "16"])

    def test_an_offices_default_campaign_is_one_it_actually_runs(self):
        # The pin an unpicked path uses has to be one of the office's own
        # campaigns. Carlos was pinned to 3, which his B2B office never runs.
        for name in KP.MULTI_CAMPAIGN:
            with self.subTest(office=name):
                ids = [c for _l, c, _k in KP.campaigns_for(name)]
                self.assertIn(KP.campaign_for_office(name), ids)

    def test_a_single_campaign_office_is_never_asked(self):
        for name in ("Rafael Hidalgo", "Chan Park", "Isaiah Revelle"):
            self.assertEqual(KP.campaigns_for(name), [],
                             "a picker on every request taxes the many for "
                             "the few")

    def test_no_offered_campaign_is_unverifiable_by_accident(self):
        # A pick we cannot verify is a board we cannot trust: pinning 16 on
        # Carlos's office once returned the AT&T grid (2026-09-02), and the
        # same class of miss put Box's numbers under an ENERGYWELL heading.
        #
        # This does NOT ban an unsignatured campaign — assert_campaign_grid
        # refuses only what it can prove wrong, and the strict rule would mean
        # Christian's Quantum Fiber board could not be asked for at all. It
        # bans an unsignatured campaign nobody WROTE DOWN, so the gap stays a
        # known debt instead of becoming a silent hole.
        for name, opts in KP.MULTI_CAMPAIGN.items():
            for label, cid, _key in opts:
                if cid == KP.KNOCKS_CAMPAIGN_ID:
                    continue    # 3 is deliberately unchecked — see the map
                with self.subTest(office=name, campaign=label):
                    self.assertTrue(
                        cid in KP.CAMPAIGN_EXPECTED_SHAPE
                        or cid in KP.UNVERIFIED_GRID,
                        f"{label} ({cid}) has no grid signature — add one, or "
                        "record it in UNVERIFIED_GRID with why")

    def test_the_unverified_list_does_not_hide_a_signature_we_have(self):
        # An id in both places would mean a real check being ignored.
        self.assertEqual(KP.UNVERIFIED_GRID & set(KP.CAMPAIGN_EXPECTED_SHAPE),
                         set())

    def test_a_spoken_word_picks_the_campaign(self):
        self.assertEqual(KP.campaign_by_keyword("Carlos Hidalgo", "box"), "16")
        self.assertEqual(KP.campaign_by_keyword("Carlos Hidalgo", "att"), "2")
        self.assertIsNone(KP.campaign_by_keyword("Carlos Hidalgo", "energywell"))

    def test_the_label_says_which_campaign_a_board_is(self):
        self.assertEqual(KP.campaign_label("Carlos Hidalgo", "16"), "B2B Box")
        self.assertEqual(KP.campaign_label("Jay Turnage", "40"), "Energy Wells")
        # One-campaign office, no campaign, and a foreign id all say nothing —
        # the label is for disambiguating, and there is nothing to disambiguate.
        self.assertEqual(KP.campaign_label("Chan Park", "3"), "")
        self.assertEqual(KP.campaign_label("Carlos Hidalgo", None), "")
        self.assertEqual(KP.campaign_label("Carlos Hidalgo", "40"), "")


class OfferedIsNotKnocked(unittest.TestCase):
    """The scan reads what ownerville OFFERS; only the owner knows what they
    knock, and the gap is wide enough to matter."""

    def test_carlos_is_offered_three_and_knocks_two(self):
        # His page links carry BASE Energy (39). Megan, 2026-09-09: "carlos
        # runs 2 campaigns." So /knocks offers two buttons, not three.
        self.assertEqual(KP.not_knocked("Carlos Hidalgo"), {"39"})
        self.assertEqual(len(KP.campaigns_for("Carlos Hidalgo")), 2)

    def test_a_dead_campaign_is_never_offered_as_a_button(self):
        # A button that returns an empty board for a day the office plainly
        # worked reads as a broken report, not as a campaign nobody knocks.
        for name, opts in KP.MULTI_CAMPAIGN.items():
            dead = KP.NOT_KNOCKED.get(name, set())
            for _label, cid, _key in opts:
                with self.subTest(office=name, campaign=cid):
                    self.assertNotIn(cid, dead)

    def test_the_canonical_name_only(self):
        # Same rule as CAMPAIGN_OVERRIDES: callers canonicalise first, so an
        # alias spelling here would be the per-report patch aliases replace.
        self.assertEqual(KP.not_knocked("  CARLOS   HIDALGO "), {"39"})
        self.assertEqual(KP.not_knocked("Nobody At All"), set())

    def test_calvin_is_not_listed_dead_on_a_campaign_he_knocks(self):
        # He was, for one commit, on the strength of "Calvin is ENERGY WELL
        # only" quoted in CAMPAIGN_OVERRIDES to explain why 40 and not 3. That
        # line was never a survey of what he knocks (Megan 2026-09-09: "calvin
        # also runs 2 campaigns"). Dropping a real campaign is the worse of the
        # two mistakes — a missing button is invisible.
        self.assertEqual(KP.not_knocked("Calvin Ribera"), set())
        self.assertEqual([c for _l, c, _k in KP.campaigns_for("Calvin Ribera")],
                         ["16", "40"])

    def test_it_is_a_copy_so_a_caller_cannot_edit_the_map(self):
        got = KP.not_knocked("Carlos Hidalgo")
        got.add("999")
        self.assertEqual(KP.not_knocked("Carlos Hidalgo"), {"39"})


class PinCampaign(unittest.TestCase):

    def test_empty_campaign_does_not_navigate(self):
        page = _StubPage()
        KP._pin_campaign(page, "TOKEN", "", verbose=False)
        self.assertEqual(page.gotos, [], "an empty campaign must skip the pin")

    def test_campaign_id_lands_in_the_url(self):
        page = _StubPage()
        KP._pin_campaign(page, "TOKEN", "3", verbose=False)
        self.assertEqual(len(page.gotos), 1)
        self.assertIn("invD2DClientId=3", page.gotos[0])
        self.assertIn("rqst=TOKEN", page.gotos[0])

    def test_none_means_the_module_default(self):
        # Back-compat: callers that never passed a campaign keep their old
        # behaviour rather than silently losing the pin.
        page = _StubPage()
        KP._pin_campaign(page, "TOKEN", None, verbose=False)
        self.assertIn(f"invD2DClientId={KP.KNOCKS_CAMPAIGN_ID}", page.gotos[0])

    def test_an_nds_office_end_to_end_gets_pinned(self):
        page = _StubPage()
        KP._pin_campaign(page, "TOKEN", KP.campaign_for_office("Isaiah Revelle"),
                         verbose=False)
        self.assertEqual(len(page.gotos), 1)
        self.assertIn(f"invD2DClientId={KP.KNOCKS_CAMPAIGN_ID}", page.gotos[0])


if __name__ == "__main__":
    unittest.main()


class BothKnocksReportsAgree(unittest.TestCase):
    """The weekly report used to decide the campaign itself ("" if nds else
    "3"), so the two knocks reports could disagree about the same office —
    which is how Isaiah ended up pinned by one and unpinned by the other."""

    def test_weekly_rows_take_their_campaign_from_knocks_pull(self):
        from automations.weekly_knock_dispositions import offices as W
        rows = W.enrolled_offices()
        self.assertTrue(rows, "no enrolled offices to check")
        for r in rows:
            with self.subTest(office=r["name"]):
                self.assertEqual(r["campaign_id"],
                                 KP.campaign_for_office(r["name"]))

    def test_no_enrolled_office_skips_the_pin(self):
        # An empty campaign means "don't pin", which leaves the session on
        # whatever was last selected. Nothing should be in that state today.
        from automations.weekly_knock_dispositions import offices as W
        blank = [r["name"] for r in W.enrolled_offices()
                 if not r["campaign_id"]]
        self.assertEqual(blank, [])

    def test_an_override_reaches_the_weekly_report_too(self):
        from automations.weekly_knock_dispositions import offices as W
        rows = W.enrolled_offices()
        target = rows[0]["name"]
        from automations.focus_office_att.aliases import _norm_name
        KP.CAMPAIGN_OVERRIDES[_norm_name(target)] = "16"
        try:
            got = next(r["campaign_id"] for r in W.enrolled_offices()
                       if r["name"] == target)
            self.assertEqual(got, "16")
        finally:
            KP.CAMPAIGN_OVERRIDES.pop(_norm_name(target), None)


class NoDataDayPostsOnce(unittest.TestCase):
    """A verified-empty day used to announce TWO metrics — Total Knocks and
    Time Gaps — left over from when every office posted two images. Nobody
    posts two on a data day now, so two no-data lines promised a board that
    was never coming."""

    def _run_no_data(self, monkey_rows):
        """Run knocks_run.run() with the pull stubbed to return no rows and
        Slack stubbed out, capturing what it would post."""
        import io, contextlib
        from automations.rashad_metrics import knocks_run as KR
        posted = []

        def _fake_pull(office_name, extras, target):
            import datetime as dt
            return monkey_rows, [], target or dt.date(2026, 8, 23)

        def _fake_post(text, react_emoji=None, today=None):
            posted.append(text)
            return {"ok": True}

        import automations.shared.slack_metrics_post as SMP
        orig_pull, orig_post = KR._pull, SMP.post_reply_text_only
        KR._pull, SMP.post_reply_text_only = _fake_pull, _fake_post
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = KR.run(dry_run=False)
            return rc, posted, buf.getvalue()
        finally:
            KR._pull, SMP.post_reply_text_only = orig_pull, orig_post

    def test_exactly_one_no_data_line(self):
        rc, posted, _out = self._run_no_data([])
        self.assertEqual(rc, 0)
        self.assertEqual(len(posted), 1,
                         f"expected ONE no-data line, got {posted}")
        self.assertIn("No data available", posted[0])

    def test_the_line_is_the_knocks_slot_not_time_gaps(self):
        _rc, posted, _out = self._run_no_data([])
        from automations.rashad_metrics.knocks_run import (
            POST_TOTAL_KNOCKS, POST_TIME_GAPS,
        )
        self.assertIn(POST_TOTAL_KNOCKS[0], posted[0])
        self.assertNotIn(POST_TIME_GAPS[0], posted[0])


class EnergyWellsShapeDetection(unittest.TestCase):
    """A fiber grid that happens to carry VL must NOT be read as Energy Wells.

    On 2026-08-31 it was, and the Energy Wells scrape then raised on the
    columns fiber does not have — which silently cost Chan Park's comparison
    line on Raf's board ("this one doesn't have chans numbers?"). The shapes
    are told apart by what they LACK as much as by what they carry.
    """

    @staticmethod
    def _idx(*cols):
        from automations.total_knocks import pull as k
        return {k._norm(c): i for i, c in enumerate(cols)}

    def test_energy_wells_grid_is_detected(self):
        from automations.total_knocks import pull as k
        idx = self._idx(k.COL_TOTAL_KNOCKS, k.COL_VL, k.COL_NOT_INTERESTED)
        self.assertTrue(KP._is_energywell_dispo(idx))

    def test_fiber_grid_with_a_vl_column_is_not(self):
        from automations.total_knocks import pull as k
        idx = self._idx(k.COL_TOTAL_KNOCKS, k.COL_VL, k.COL_TALK_TO_NI)
        self.assertFalse(KP._is_energywell_dispo(idx),
                         "a fiber grid carrying VL must still scrape as fiber")

    def test_plain_fiber_grid_is_not(self):
        from automations.total_knocks import pull as k
        idx = self._idx(k.COL_TOTAL_KNOCKS, k.COL_TALK_TO_NI)
        self.assertFalse(KP._is_energywell_dispo(idx))
