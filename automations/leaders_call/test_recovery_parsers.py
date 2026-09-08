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
    ["", "", "Total", "3", "3", "1", "2", "5", "0", "0", "14"],
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

    def test_ignores_the_per_rep_subtotal_row(self):
        """The crosstab carries a 'Total' Product Type row per rep; counting it
        would double everyone's apps and float people over the threshold."""
        camp = _camp(owners=["Rafael Hidalgo"], threshold=1)
        out = lc.parse_product_sales(camp, PRODUCT_SALES)
        self.assertEqual(out, [("Ana Griffin", "Rafael Hidalgo", 14.0)])  # not 28

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



# NDS 'This week and last': row 0 = week-ending date per column, row 1 = day
# name, data from row 2. The finished week (9/6) sits BESIDE the in-progress
# one (9/13), which only has the days it has so far.
NDS_MULTIWEEK = [
    ["", "", "", "9/6/2026", "9/6/2026", "9/6/2026", "9/6/2026", "9/6/2026",
     "9/6/2026", "9/6/2026", "9/6/2026", "9/13/2026", "9/13/2026", "9/13/2026"],
    ["Owner & Office", "Rep Name", "Product Type (Broken Out)", "Monday",
     "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
     "Total", "Monday", "Tuesday", "Total"],
    ["KHALIL MANSOUR\n[amg dba hab]", "Abdallah Ghousheh", "NEW INTERNET",
     "4", "3", "2", "1", "0", "0", "0", "10", "9", "9", "18"],
    ["", "", "WIRELESS", "1", "1", "1", "0", "0", "0", "0", "3", "0", "0", "0"],
    ["", "", "Total", "5", "4", "3", "1", "0", "0", "0", "13", "9", "9", "18"],
    ["MAXAMAD ADEN", "Slow Rep", "NEW INTERNET",
     "1", "0", "0", "0", "0", "0", "0", "1", "40", "40", "80"],
]


class NDSMultiweekTest(unittest.TestCase):
    def _camp(self):
        return _camp(key="nds", section_title="NDS",
                     owners=["Khalil Mansour", "Maxamad Aden"])

    def test_reads_the_finished_week_not_the_one_in_progress(self):
        camp = self._camp()
        out = lc.parse_product_sales_multiweek(camp, NDS_MULTIWEEK)
        # 10 NI + 3 WIRELESS across 8/31-9/6. The 9/13 columns (18 + 0) and the
        # 'Total' rows/columns are all excluded.
        self.assertEqual(out, [("Abdallah Ghousheh", "KHALIL MANSOUR", 13.0)])

    def test_a_rep_who_only_sold_this_week_does_not_qualify(self):
        """Slow Rep has 80 apps in the in-progress week and 1 in the finished
        one — reading the wrong block would put them on the deck."""
        camp = self._camp()
        names = [r[0] for r in lc.parse_product_sales_multiweek(camp,
                                                                NDS_MULTIWEEK)]
        self.assertNotIn("Slow Rep", names)

    def test_the_legal_suffix_on_its_own_line_is_stripped(self):
        out = lc.parse_product_sales_multiweek(self._camp(), NDS_MULTIWEEK)
        self.assertEqual(out[0][1], "KHALIL MANSOUR")

    def test_raises_when_the_finished_week_is_gone(self):
        """Once the view stops carrying the target week there is nothing to
        recover — it must say so, never quietly read the other block."""
        rolled = [r[:] for r in NDS_MULTIWEEK]
        rolled[0] = [c.replace("9/6/2026", "9/20/2026") for c in rolled[0]]
        with self.assertRaises(RuntimeError):
            lc.parse_product_sales_multiweek(self._camp(), rolled)



if __name__ == "__main__":
    unittest.main()
