"""The campaign dropdown is not just "the first visible select".

2026-11-23: OwnerVille put an owner switcher (97 options shaped like
"Maxamad Aden (23066 - Maximal Management, Inc.)") above the campaign
dropdown. `_campaign_select` took `.first`, so digi_docs refused 12 new starts
with "campaign 'RES-AT&T' matched 0 of 97 options".
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.headshots import ov_upload as U

OWNERS = ["Maxamad Aden (23066 - Maximal Management, Inc.)",
          "Roshan Amin Ahmad (19833 - Sapphire Marketing, Inc)",
          "Zaid Arabyat (19018 - Aces Acquisitions, Inc)"]
CAMPAIGNS = ["RES-AT&T", "ATT Fiber", "B2B"]
LENGTH = ["10", "25", "50", "100", "All"]


class _Opts:
    def __init__(self, texts):
        self.texts = texts

    def all_inner_texts(self):
        return list(self.texts)


class _Sel:
    def __init__(self, texts):
        self.texts = texts

    def locator(self, _q):
        return _Opts(self.texts)

    def wait_for(self, **_kw):
        pass


class _Many:
    def __init__(self, sels):
        self.sels = sels
        self.first = sels[0]

    def count(self):
        return len(self.sels)

    def nth(self, i):
        return self.sels[i]


class _Page:
    def __init__(self, *lists):
        self.sels = [_Sel(t) for t in lists]

    def locator(self, _q):
        return _Many(self.sels)


def pick(*lists):
    page = _Page(*lists)
    with mock.patch.object(U, "_wait_loaded"):
        return U._campaign_select(page).texts


class CampaignSelect(unittest.TestCase):

    def test_skips_the_owner_switcher_above_it(self):
        self.assertEqual(pick(OWNERS, CAMPAIGNS), CAMPAIGNS)

    def test_skips_the_page_length_box(self):
        self.assertEqual(pick(LENGTH, CAMPAIGNS), CAMPAIGNS)

    def test_single_campaign_select_still_works(self):
        self.assertEqual(pick(CAMPAIGNS), CAMPAIGNS)

    def test_nothing_recognisable_falls_back_to_first(self):
        """_select_campaign then refuses on the bad match, as before."""
        self.assertEqual(pick(OWNERS), OWNERS)


if __name__ == "__main__":
    unittest.main()
