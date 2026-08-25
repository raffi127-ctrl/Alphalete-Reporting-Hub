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

    def test_overrides_start_empty(self):
        # A guessed override silently blanks an office's whole board, so the
        # map stays empty until an exception is actually observed.
        self.assertEqual(KP.CAMPAIGN_OVERRIDES, {})


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
