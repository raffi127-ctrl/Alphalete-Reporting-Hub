"""The off-day recovery parsers, on synthetic crosstabs of the real shapes.

--recover stands in for Fiber / NDS / B2B when their relative "This Week" views
have already rolled past the target week (see test_week_roll_hold). It has to
produce EXACTLY what the live section would have: the campaign's own owner
filter, its own threshold, sorted desc.
"""
import unittest

from automations.leaders_call import run as lc


def _camp(**kw):
    base = dict(key="fiber", url="", crosstab_sheet="", threshold=12,
                section_title="Fiber", owners=[])
    base.update(kw)
    return lc.Campaign(**base)


# Owner Name | Rep | Product Type | Mon..Sun | Product Total
PRODUCT_SALES = [
    ["Owner Name", "Rep", "Product Type", "Mon", "Tue", "Wed", "Thu", "Fri",
     "Sat", "Sun", "Product Total"],
    ["Rafael Hidalgo", "Ana Griffin", "NEW INTERNET", "2", "3", "1", "0", "4",
     "0", "0", "10"],
    ["", "", "WIRELESS", "1", "0", "0", "2", "1", "0", "0", "4"],
    ["Kash Rai", "Hank Tran", "NEW INTERNET", "5", "5", "3", "0", "0", "0",
     "0", "13"],
    ["Cyrus Wade", "Micah Mcghee", "NEW INTERNET", "1", "1", "0", "0", "0",
     "0", "0", "2"],
    ["Someone Else", "Outsider Rep", "NEW INTERNET", "9", "9", "9", "0", "0",
     "0", "0", "27"],
    ["", "Total", "", "", "", "", "", "", "", "", "56"],
]


class ProductSalesRecoveryTest(unittest.TestCase):
    def test_sums_every_product_and_carries_owner_forward(self):
        camp = _camp(owners=["Rafael Hidalgo", "Kash Rai", "Cyrus Wade"])
        out = lc.parse_product_sales(camp, PRODUCT_SALES)
        # Ana: 10 NI + 4 WIRELESS = 14 (her second row inherits her owner/name).
        self.assertEqual(out, [("Ana Griffin", "Rafael Hidalgo", 14.0),
                               ("Hank Tran", "Kash Rai", 13.0)])

    def test_never_double_counts_the_product_total_column(self):
        camp = _camp(owners=["Kash Rai"], threshold=1)
        out = lc.parse_product_sales(camp, PRODUCT_SALES)
        self.assertEqual(out[0][2], 13.0)      # not 26

    def test_owner_filter_and_threshold_match_the_live_section(self):
        camp = _camp(owners=["Rafael Hidalgo", "Kash Rai", "Cyrus Wade"])
        names = [r[0] for r in lc.parse_product_sales(camp, PRODUCT_SALES)]
        self.assertNotIn("Outsider Rep", names)   # owner not in the campaign
        self.assertNotIn("Micah Mcghee", names)   # 2 apps, under 12

    def test_a_collapsed_export_raises_instead_of_writing_owners_as_reps(self):
        collapsed = [["Owner Name", "Product Type", "Mon", "Product Total"],
                     ["Rafael Hidalgo", "NEW INTERNET", "40", "40"]]
        with self.assertRaises(RuntimeError):
            lc.parse_product_sales(_camp(), collapsed)


# Owner & Office | Rep | <measure, header BLANK> | product columns…
B2B_SUMMARY = [
    ["Owner & Office", "Rep", "", "CRU NEW INTERNET", "IRU NEW INTERNET",
     "CRU VOICE", "CRU WIRELESS", "IRU WIRELESS", "CRU AIR/AWB", "IRU AIR/AWB"],
    ["Carlos Hidalgo [alphalete]", "Cinthya reyes", "Total Volume",
     "6", "2", "1", "4", "0", "1", "0"],
    ["", "", "Total Activations", "5", "2", "1", "3", "0", "1", "0"],
    ["", "", "Activation %", "83%", "100%", "100%", "75%", "", "100%", ""],
    ["Atef Choudhury", "Ingrid Castillo", "Total Volume",
     "2", "0", "0", "1", "0", "0", "0"],
    ["Nobody Important", "Other Rep", "Total Volume",
     "40", "0", "0", "0", "0", "0", "0"],
]


class B2BRecoveryTest(unittest.TestCase):
    def test_reads_total_volume_and_strips_the_legal_suffix(self):
        camp = _camp(key="b2b", section_title="B2B",
                     owner_hdr=("owner name", "owner"),
                     owners=["Carlos Hidalgo", "Atef Choudhury"])
        out = lc.parse_b2b_summary(camp, B2B_SUMMARY)
        # 6+2 NI + 1 VOICE + 4 WIRELESS + 1 AIR = 14; the Activations and
        # Activation % rows of the same rep are ignored.
        self.assertEqual(out, [("Cinthya reyes", "Carlos Hidalgo", 14.0)])

    def test_owner_level_export_raises(self):
        """The hierarchy failing to expand is the known ~40% failure of this
        source — it must never be read as rep data."""
        owner_level = [["Owner & Office", "", "CRU NEW INTERNET"],
                       ["Carlos Hidalgo", "Total Volume", "120"]]
        with self.assertRaises(RuntimeError):
            lc.parse_b2b_summary(_camp(key="b2b"), owner_level)


if __name__ == "__main__":
    unittest.main()
