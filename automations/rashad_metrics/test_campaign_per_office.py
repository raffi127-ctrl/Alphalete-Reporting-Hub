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

    def test_wireless_office_gets_no_pin(self):
        # Isaiah knocks NDS/wireless — pinning the fiber campaign would put his
        # session on a campaign his office never uses.
        self.assertEqual(KP.campaign_for_office("Isaiah Revelle"), "")

    def test_wireless_lookup_is_case_and_spacing_tolerant(self):
        self.assertEqual(KP.campaign_for_office("  isaiah   revelle "), "")

    def test_fiber_offices_keep_the_default_pin(self):
        for name in ("Rafael Hidalgo", "Chan Park", "Haytham Nagi"):
            with self.subTest(name=name):
                self.assertEqual(KP.campaign_for_office(name),
                                 KP.KNOCKS_CAMPAIGN_ID)

    def test_unknown_name_falls_back_to_the_default(self):
        # The behaviour before this function existed: an office we can't
        # classify is pinned, not silently left on a stale campaign.
        self.assertEqual(KP.campaign_for_office("Nobody At All"),
                         KP.KNOCKS_CAMPAIGN_ID)
        self.assertEqual(KP.campaign_for_office(""), KP.KNOCKS_CAMPAIGN_ID)


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

    def test_a_wireless_office_end_to_end_skips_the_pin(self):
        page = _StubPage()
        KP._pin_campaign(page, "TOKEN", KP.campaign_for_office("Isaiah Revelle"),
                         verbose=False)
        self.assertEqual(page.gotos, [])


if __name__ == "__main__":
    unittest.main()
