"""Every curated _HUB_CARD target has to be a card that actually exists.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.day_orchestrator.test_hub_card_ids

WHY (Megan 2026-08-25). The Hub keys on its CARD id; the orchestrator keys on a
report_id, and the two differ (underscores vs hyphens, sometimes a different
name). When a report's id neither appears in _HUB_CARD nor slug-matches a card,
the resolver registers it as its OWN library card — so the real card never
receives a row and sits on the Needs-attention list saying "scheduled …, no run
logged" forever.

That is exactly what 'Owner Chat Texts → iMessage owner chats' did. It covers two
morning passes (7:30 trackers PDF, 7:45 WOW board) that run under
`owner_chat_texts_trackers` and `owner_chat_texts_board`. Neither slug-matches
`owner-chat-texts`, so on 8/25 the card read "no run logged" while the Hub
Activity tab plainly showed both passes had run from Lucy 1 — trackers success at
07:35, board success at 09:38 once its data-gate hold cleared. A card that can
only ever say "no run logged" trains you to ignore that line, and that line is
the one that has to mean something.

SCOPE. This checks only what is knowable OFFLINE. A curated target is valid if
it is a hardcoded card OR a card in the shared library (hub_coverage.resolve_card
accepts both), and the library lives in a Sheet — so "is every target real?"
cannot be answered without a network read, and a unit test must not take one. The
assertions below therefore cover the hardcoded set, which is where this card
lives and which is the path that needs no network at all.
"""
from __future__ import annotations

import unittest

from automations.day_orchestrator import hub_publish
from automations.hub_cards import AUTOMATED_REPORTS


def _card_ids() -> set:
    return {c["id"] for c in AUTOMATED_REPORTS if c.get("id")}


# Library cards keep the UNDERSCORE report_id as their id (hub_coverage:
# "The created library card's id is the underscore report_id"), and hand-written
# cards in hub_cards.py are hyphenated. So a HYPHENATED target that is not a
# hardcoded card cannot be a library card either — it can only be a card that
# never existed or has since been deleted, which is the whole bug class below.
# One documented exception exists in the other direction (a hyphenated LIBRARY
# card), so it is listed rather than silently widening the rule.
_HYPHENATED_LIBRARY_CARDS = {"indeed-source-report"}


class NoTargetNamesADeletedCard(unittest.TestCase):
    """The dangling-target bug class, made offline-checkable.

    Four targets named cards that no longer exist anywhere (2026-08-25):
    `country-sales-board-email` and `resume-pushing` (both cards deleted while
    their reports kept running), `all-units-board-email` (report retired
    2026-07-31) and `frontier-opt-data-pull` (report retired 2026-08-23).

    Nothing was lost — hub_coverage's PHANTOM GUARD falls through to
    slug-match/auto-create precisely so a live report always lands somewhere
    real. But the map was then describing cards that didn't exist, every run
    paid for the guard, and if anyone ever recreated a card under the old
    hyphenated name the runs would silently move back onto it.
    """

    def test_no_hyphenated_target_is_missing_from_the_hardcoded_cards(self):
        from automations.day_orchestrator import hub_coverage

        hard = hub_coverage._hardcoded_card_ids()
        dangling = {rid: card for rid, card in hub_publish._HUB_CARD.items()
                    if "-" in card
                    and card not in hard
                    and card not in _HYPHENATED_LIBRARY_CARDS}
        self.assertEqual(dangling, {},
                         "hyphenated _HUB_CARD targets that are not hardcoded "
                         "cards cannot exist as library cards either: "
                         + repr(dangling))

    def test_the_four_retired_or_deleted_targets_are_gone(self):
        targets = set(hub_publish._HUB_CARD.values())
        for dead in ("country-sales-board-email", "all-units-board-email",
                     "frontier-opt-data-pull", "resume-pushing"):
            with self.subTest(card=dead):
                self.assertNotIn(dead, targets)

    def test_the_two_live_reports_now_name_the_card_they_actually_use(self):
        """Both publish to a library card, whose id is the report_id itself."""
        for rid in ("country_sales_board_email", "resume_pushing"):
            with self.subTest(report_id=rid):
                self.assertEqual(hub_publish._HUB_CARD.get(rid), rid)

    def test_the_two_retired_reports_are_no_longer_mapped(self):
        for rid in ("all_units_board_email", "frontier_opt"):
            with self.subTest(report_id=rid):
                self.assertNotIn(rid, hub_publish._HUB_CARD)

    def test_sharing_one_card_between_passes_is_still_allowed(self):
        """The rule must not outlaw the several-report_ids-one-card pattern —
        promo_checkin, b2b_dispositions and owner-chat-texts all rely on it."""
        for rid, card in (("promo_checkin_mon", "promo_checkin"),
                          ("promo_checkin_final", "promo_checkin"),
                          ("b2b_dispositions_hourly", "b2b_dispositions"),
                          ("b2b_dispositions_final", "b2b_dispositions")):
            with self.subTest(report_id=rid):
                self.assertEqual(hub_publish._HUB_CARD.get(rid), card)


class OwnerChatTextsReachesItsCard(unittest.TestCase):
    """The specific card this test module was written for."""

    CARD = "owner-chat-texts"

    def test_the_card_exists(self):
        self.assertIn(self.CARD, _card_ids())

    def test_both_morning_passes_map_to_it(self):
        """7:30 trackers and 7:45 WOW board are two report_ids, one card."""
        for rid in ("owner_chat_texts_trackers", "owner_chat_texts_board"):
            with self.subTest(report_id=rid):
                self.assertEqual(hub_publish._HUB_CARD.get(rid), self.CARD)

    def test_the_umbrella_id_maps_too(self):
        """`owner_chat_texts` runs both halves in one go — same card."""
        self.assertEqual(hub_publish._HUB_CARD.get("owner_chat_texts"), self.CARD)

    def test_the_target_is_a_hardcoded_card_so_resolution_needs_no_network(self):
        """resolve_card trusts a curated target that is a HARDCODED card id
        without reading the library Sheet (its fast path). That matters at 4am:
        a library read that fails would otherwise send these runs down the
        slug-match/auto-create path and back onto their own stray cards."""
        from automations.day_orchestrator import hub_coverage
        self.assertIn(self.CARD, hub_coverage._hardcoded_card_ids())


if __name__ == "__main__":
    unittest.main()
