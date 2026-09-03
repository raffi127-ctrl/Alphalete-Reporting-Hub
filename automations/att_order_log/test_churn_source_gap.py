"""Which story the att_churn SOURCE-GAP alert tells.

2026-09-03: all 12 feeds gapped at once and #claudecorrections said "12 feed(s)
had nothing to slice", with a remediation asking SmartCircle for an all-team
version of the views. But ALLTEAMSEXP *is* the all-team view — the log showed
every product carrying exactly ONE owner, CODY LOWERY, i.e. the source view had
been narrowed. Nobody's captaincy had changed, and the suggested fix would have
fixed nothing. So the all-gapped case now tells its own story, and the partial
case keeps the captaincy one it was written for.
"""
import unittest

from automations.att_order_log import churn_run as cr


def _all_gaps():
    return {"{}_{}".format(o, p): cr.OFFICES[o]["owner"]
            for o in cr.OFFICES for p in cr.PRODUCTS}


class AllFeedsGapped(unittest.TestCase):
    def test_every_office_times_every_product_is_the_narrowed_case(self):
        self.assertTrue(cr._all_feeds_gapped(_all_gaps()))

    def test_one_office_leaving_a_captaincy_is_not(self):
        """Atef's split (2026-08-18) gapped his three feeds and no others — the
        case the original manifest was written for."""
        gaps = {"atef_{}".format(p): "ATEF CHOUDHURY" for p in cr.PRODUCTS}
        self.assertFalse(cr._all_feeds_gapped(gaps))

    def test_a_clean_run_is_neither(self):
        self.assertFalse(cr._all_feeds_gapped({}))

    def test_the_count_follows_the_live_tables(self):
        """Read off OFFICES x PRODUCTS, not a hard-coded 12 — onboarding a fifth
        B2B office must not quietly turn the all-gapped case back into partial."""
        self.assertEqual(len(_all_gaps()), len(cr.OFFICES) * len(cr.PRODUCTS))


class ViewOwnerSummary(unittest.TestCase):
    """The owners the view DID carry are the whole diagnosis, so they have to
    survive into the alert text."""

    def test_the_one_owner_that_broke_9_3_is_named(self):
        self.assertEqual(
            cr._view_owner_summary({"wireless": ["CODY LOWERY"],
                                    "new_int": ["CODY LOWERY"],
                                    "air": ["CODY LOWERY"]}),
            "CODY LOWERY")

    def test_owners_are_deduped_across_products(self):
        got = cr._view_owner_summary({"wireless": ["B OWNER", "A OWNER"],
                                      "air": ["A OWNER"]})
        self.assertEqual(got, "A OWNER, B OWNER")

    def test_a_long_list_is_capped_but_still_counted(self):
        names = ["OWNER {}".format(i) for i in range(12)]
        got = cr._view_owner_summary({"wireless": names})
        self.assertTrue(got.startswith("12 owners incl. "))

    def test_unreadable_owners_say_so_rather_than_reading_as_empty(self):
        """_distinct_owners can itself raise; the alert must not then claim the
        view carried nobody, which is a different fault."""
        self.assertEqual(cr._view_owner_summary({}), "none we could read")


if __name__ == "__main__":
    unittest.main()
