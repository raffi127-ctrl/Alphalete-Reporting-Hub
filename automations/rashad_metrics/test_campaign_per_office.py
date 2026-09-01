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
        self.assertEqual(set(KP.CAMPAIGN_OVERRIDES.values()), {"40"},
                         "every override must be an observed campaign id")
        # The CANONICAL name only. "Calvin Rivera" is the alias sheet's job —
        # every caller resolves it before this map is consulted — and listing
        # it here too would be the per-report patch aliases exist to replace.
        self.assertEqual(KP.campaign_for_office("Calvin Ribera"), "40")

    def test_everyone_else_still_gets_the_default(self):
        # The override map must not leak onto offices that never asked.
        for name in ("Rafael Hidalgo", "Chan Park", "Isaiah Jones"):
            self.assertEqual(KP.campaign_for_office(name),
                             KP.KNOCKS_CAMPAIGN_ID)


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
