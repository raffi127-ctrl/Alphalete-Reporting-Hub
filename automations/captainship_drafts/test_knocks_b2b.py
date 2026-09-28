"""B2B captainships get the daily knocks + the weekly knock dispositions
(Carlos asked for the weekly, Eve added the daily — 2026-09-28).

Pins: the preview gate (nothing ships until PREVIEW_KINDS lets go), the B2B
talk-to rule in the weekly pull, the no-apps boards, and the daily summary's
B2B shape.

    python -m unittest automations.captainship_drafts.test_knocks_b2b
"""
import datetime as dt
import os
import unittest
from unittest import mock

from automations.captainship_drafts import config

SUN = dt.date(2026, 10, 4)
TUE = dt.date(2026, 10, 6)


def _b2b():
    return next(c for c in config.CAPTAINS if c.flavor == "b2b")


class PreviewGate(unittest.TestCase):
    def test_b2b_declares_both_knock_sections(self):
        kinds = config.SECTION_KINDS["b2b"]
        self.assertIn("knock_dispo", kinds)
        self.assertIn("daily_knocks", kinds)
        self.assertEqual(len(config._INTRO["b2b"][1]), len(kinds))

    def test_held_back_without_the_flag(self):
        with mock.patch.dict(os.environ, {config.PREVIEW_ENV: ""}):
            kinds = {k for _h, k in _b2b().sections_on(SUN)}
        self.assertFalse({"knock_dispo", "daily_knocks"} & kinds)

    def test_daily_runs_every_day_with_the_flag(self):
        with mock.patch.dict(os.environ, {config.PREVIEW_ENV: "1"}):
            self.assertIn("daily_knocks",
                          {k for _h, k in _b2b().sections_on(TUE)})

    def test_night_mail_never_takes_b2b(self):
        from automations.captainship_night_knocks.run import default_captains
        b2b_keys = {c.key for c in config.CAPTAINS if c.flavor == "b2b"}
        for flag in ("", "1"):
            with mock.patch.dict(os.environ, {config.PREVIEW_ENV: flag}):
                self.assertFalse(b2b_keys & set(default_captains()))

    def test_runs_with_the_flag_on_sun_mon_only(self):
        with mock.patch.dict(os.environ, {config.PREVIEW_ENV: "1"}):
            self.assertIn("knock_dispo",
                          {k for _h, k in _b2b().sections_on(SUN)})
            self.assertNotIn("knock_dispo",
                             {k for _h, k in _b2b().sections_on(TUE)})

    def test_other_flavors_untouched(self):
        with mock.patch.dict(os.environ, {config.PREVIEW_ENV: ""}):
            raf = config.BY_KEY["rafael"]
            self.assertIn("knock_dispo",
                          {k for _h, k in raf.sections_on(SUN)})

    def test_weekly_pdf_hook_sees_no_b2b_section_in_preview(self):
        # run.py / reply_attachment / weekly_pdf_slack decide the weekly PDF
        # off Captain.sections: a preview capture must not reach a real mail.
        with mock.patch.dict(os.environ, {config.PREVIEW_ENV: ""}):
            self.assertNotIn("knock_dispo",
                             {k for _h, k in _b2b().sections})

    def test_attachment_only_in_the_body(self):
        with mock.patch.dict(os.environ, {config.PREVIEW_ENV: "1"}):
            body = {k for _h, k in _b2b().body_sections_on(SUN)}
        self.assertNotIn("knock_dispo", body)

    def test_scheduled_capture_skips_b2b(self):
        from automations.captainship_drafts.knocks_capture import captains_for
        with mock.patch.dict(os.environ, {config.PREVIEW_ENV: ""}):
            flavors = {c.flavor for c, _w in captains_for(SUN)}
        self.assertNotIn("b2b", flavors)

    def test_access_watch_skips_preview_kinds(self):
        from automations.knocks_access_watch import audit
        b2b_keys = {c.key for c in config.CAPTAINS if c.flavor == "b2b"}
        self.assertFalse(b2b_keys & set(audit._captains_with_knocks()))


class OwnerCfgs(unittest.TestCase):
    def test_b2b_has_no_apps_source(self):
        from automations.captainship_drafts import knock_dispo_images as K
        with mock.patch("automations.focus_office_att.aliases."
                        "alias_to_canonical", side_effect=lambda n, _a: n):
            pairs = K.owner_cfgs(["Jeff Starr"], {}, b2b=True)
        self.assertEqual(pairs[0][1]["apps_source"], "none")


class B2BTalkTo(unittest.TestCase):
    ATT = ["Talked To - Not Interested", "Presentation - Not Interested",
           "Sale", "Come Back", "Corp Franchise Local",
           "Corp Franchise No Opp", "Do Not Knock", "Inaccurate Lead", "None"]

    def _idx(self, names):
        from automations.total_knocks.pull import _norm
        return {_norm(h): i for i, h in enumerate(names)}

    def test_att_grid_uses_the_daily_parts(self):
        from automations.weekly_knock_dispositions.pull import (
            _b2b_talk_to_cols)
        got = _b2b_talk_to_cols(self._idx(self.ATT), "2", self.ATT)
        self.assertNotIn("None", got)
        self.assertNotIn("Inaccurate Lead", got)
        self.assertIn("Corp Franchise No Opp", got)
        self.assertEqual(len(got), 7)

    def test_house_grid_is_left_alone(self):
        from automations.weekly_knock_dispositions.pull import (
            _b2b_talk_to_cols)
        house = ["No answer", "Talk To - Not Interested", "Come Back"]
        self.assertIsNone(_b2b_talk_to_cols(self._idx(house), "3", house))

    def test_b2b_pin_that_did_not_take_raises(self):
        from automations.weekly_knock_dispositions.pull import (
            _b2b_talk_to_cols)
        house = ["No answer", "Talk To - Not Interested", "Come Back"]
        with self.assertRaises(Exception):
            _b2b_talk_to_cols(self._idx(house), "2", house)


class DailySummary(unittest.TestCase):
    def _captured(self):
        from automations.total_knocks import pull as knocks
        rec = {knocks.COL_REP: "Rep A", knocks.COL_TOTAL_KNOCKS: 40,
               knocks.COL_TOTAL_LEADS_KNOCKED: 30,
               knocks.COL_TOTAL_TALK_TO: 12,
               knocks.COL_B2B_CORP_NO_OPP: 3,
               knocks.COL_FIRST_KNOCK: "10:00 AM",
               knocks.COL_LAST_KNOCK: "5:00 PM"}
        return [("Jeff Starr", {"name": "Jeff Starr"}, [rec], None)]

    def test_b2b_rows_get_no_house_breakdown(self):
        from automations.captainship_drafts import knock_dispo_images as K
        self.assertEqual(K.summary_dispo(self._captured()), [])

    def test_house_rows_unchanged(self):
        from automations.captainship_drafts import knock_dispo_images as K
        from automations.total_knocks import pull as knocks
        cap = [("X", {"name": "X"}, [{knocks.COL_TOTAL_KNOCKS: 5,
                                      knocks.COL_TALK_TO_NI: 1}], None)]
        self.assertEqual(K.summary_dispo(cap), list(K.DAILY_SUMMARY_DISPO))

    def test_summary_renders_without_apps(self):
        import tempfile
        from automations.captainship_drafts import knock_dispo_images as K
        with tempfile.TemporaryDirectory() as d:
            png = K.render_daily_summary(self._captured(), SUN, d,
                                         roster_n=1, n_covered=1,
                                         captain="carlos", no_apps=True)
            self.assertTrue(png.exists())

    def test_apps_headers_exist_to_be_dropped(self):
        from automations.captainship_drafts import knock_dispo_images as K
        self.assertTrue(K.SUMMARY_APPS_HEADERS
                        <= set(K.summary_headers([])))


class NoAppsBoard(unittest.TestCase):
    def test_drop_columns(self):
        from automations.weekly_knock_dispositions import board as B
        hdr = B.headers_for(None)
        rows = [[str(i) for i in range(len(hdr))]]
        h2, r2 = B.drop_columns(hdr, rows, B.APPS_COLUMNS)
        self.assertEqual(len(h2), len(hdr) - 2)
        self.assertFalse(B.APPS_COLUMNS & set(h2))
        self.assertEqual(len(r2[0]), len(h2))
        self.assertTrue(B.APPS_COLUMNS <= set(hdr))


if __name__ == "__main__":
    unittest.main()
