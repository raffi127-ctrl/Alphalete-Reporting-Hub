"""Tests for Carlos's two 2026-08-25 asks on the Box thread.

    1. The payout board grew a "Submitted to Supplier" column. It is a SLICE of
       "Still Open", not a bucket beside it — a submitted deal is counted in
       both. The tests below pin that down, because the obvious "fix" the next
       time someone reads the board is to make the columns add up, and that
       would be wrong.
    2. The workbook's Pending Orders tab also ships as a standalone image. Both
       surfaces read pending.build(), so the tests assert the MODEL — the
       yellow split especially, which reads paint, not status names.

    python -m unittest automations.box_order_log.test_pending_and_submitted -v
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.box_order_log import clean, payout, pending, png


def sale(rep, status, *, sale_date=None, accepted=None, history=(),
         business="Some LLC", contract="1"):
    """One collapsed Sale, only the fields these two surfaces read."""
    return clean.Sale(
        key=(contract, contract),
        fields={"Rep Name": rep, "Business Name": business,
                "Contract ID": contract},
        status=status, sub_status="", level=status,
        sale_date=sale_date, accepted_date=accepted,
        week_ending=accepted or sale_date,
        history=tuple(history) or (status,), secondary="",
        is_cancel=status in payout.CANCEL_STATUSES,
    )


TODAY = dt.date(2026, 8, 25)          # a Tuesday: this week = 8.23 - 8.29


class SubmittedColumn(unittest.TestCase):

    def _rows(self, sales, which="this"):
        return payout.build_week_tables(sales, TODAY)[which]["rows"]

    def test_submitted_is_counted_inside_still_open(self):
        """Carlos: "as long as it's not cancelled by broker, it would go under
        pending" — so the same deal lands in both columns."""
        row = self._rows([sale("Ana", clean.SUBMITTED,
                               sale_date=dt.date(2026, 8, 24))])[0]
        self.assertEqual(row["submitted"], 1)
        self.assertEqual(row["pending"], 1)

    def test_only_the_submitted_label_counts(self):
        """A Verification deal is open but is NOT "labeled Submitted"."""
        rows = self._rows([
            sale("Ana", clean.SUBMITTED, sale_date=dt.date(2026, 8, 24),
                 contract="1"),
            sale("Ana", "Verification", sale_date=dt.date(2026, 8, 24),
                 contract="2"),
            sale("Ana", "Ready For Booking", sale_date=dt.date(2026, 8, 24),
                 contract="3"),
        ])
        self.assertEqual(rows[0]["submitted"], 1)
        self.assertEqual(rows[0]["pending"], 3)

    def test_accepted_and_cancelled_never_count_as_submitted(self):
        rows = self._rows([
            sale("Ana", "Accepted by Supplier", sale_date=dt.date(2026, 8, 24),
                 accepted=dt.date(2026, 8, 24), history=(clean.SUBMITTED,
                                                         "Accepted by Supplier")),
            sale("Ana", "Cancelled by Broker", sale_date=dt.date(2026, 8, 24),
                 contract="2", history=(clean.SUBMITTED, "Cancelled by Broker")),
        ])
        self.assertEqual(rows[0]["submitted"], 0)
        self.assertEqual(rows[0]["pending"], 0)

    def test_submitted_is_identical_in_both_week_tables(self):
        """Like Still Open it has no payout week — pinning it to one would
        invent information."""
        sales = [sale("Ana", clean.SUBMITTED, sale_date=dt.date(2026, 8, 10))]
        tables = payout.build_week_tables(sales, TODAY)
        self.assertEqual(tables["last"]["rows"][0]["submitted"],
                         tables["this"]["rows"][0]["submitted"])

    def test_board_draws_the_column(self):
        keys = [key for _label, key, _align in png.COLS]
        self.assertEqual(keys, ["rep", "posted", "submitted", "canceled",
                                "pending"])
        # Every column the board draws has to exist on every row, or the render
        # dies at 7am with a KeyError.
        row = payout.build_week_tables(
            [sale("Ana", clean.SUBMITTED, sale_date=dt.date(2026, 8, 24))],
            TODAY)["this"]["rows"][0]
        for key in keys:
            self.assertIn(key, row)


class PendingWorklist(unittest.TestCase):

    def test_accepted_and_dead_deals_are_not_pending(self):
        sales = [
            sale("Ana", "Accepted by Supplier", accepted=dt.date(2026, 8, 24)),
            sale("Ana", "Cancelled by Broker", contract="2"),
            sale("Ana", "Rejected", contract="3"),
            sale("Ana", "Dropped", contract="4"),
            sale("Ana", "Verification", contract="5"),
        ]
        work = pending.build(sales, today=TODAY)
        self.assertEqual(work["count"], 1)

    def test_yellow_split_reads_the_paint_not_the_status(self):
        """Ready For Booking is yellow since 2026-08-20, and a Verification
        deal is yellow only if its HISTORY shows it was already submitted."""
        submitted = sale("Ana", clean.SUBMITTED, contract="1")
        booking = sale("Ana", "Ready For Booking", contract="2")
        waiting = sale("Ana", "Verification", contract="3",
                       history=(clean.SUBMITTED, "Verification"))
        ours = sale("Ana", "Verification", contract="4")
        incomplete = sale("Ana", "Incomplete", contract="5")

        work = pending.build([submitted, booking, waiting, ours, incomplete],
                             today=TODAY)
        not_yellow, yellow = work["sections"]
        self.assertEqual({s.key[0] for s in yellow["rows"]}, {"1", "2", "3"})
        self.assertEqual({s.key[0] for s in not_yellow["rows"]}, {"4", "5"})

    def test_both_sections_survive_when_one_is_empty(self):
        """An empty half is information, not something to drop — otherwise the
        image just looks truncated."""
        work = pending.build([sale("Ana", "Verification")], today=TODAY)
        self.assertEqual(len(work["sections"]), 2)
        self.assertEqual(work["sections"][1]["rows"], [])
        self.assertTrue(work["sections"][1]["empty_note"])

    def test_reps_a_to_z_and_stalest_deal_first(self):
        sales = [
            sale("Zoe", "Verification", sale_date=dt.date(2026, 8, 20),
                 contract="1"),
            sale("Ana", "Verification", sale_date=dt.date(2026, 8, 20),
                 contract="2"),
            sale("Ana", "Verification", sale_date=dt.date(2026, 7, 1),
                 contract="3"),
        ]
        reps = pending.build(sales, today=TODAY)["sections"][0]["reps"]
        self.assertEqual([rep for rep, _ in reps], ["Ana", "Zoe"])
        self.assertEqual([s.key[0] for s in reps[0][1]], ["3", "2"])

    def test_days_waiting_counts_from_the_sale_date(self):
        s = sale("Ana", "Verification", sale_date=dt.date(2026, 8, 18))
        self.assertEqual(pending.days_waiting(s, TODAY), 7)

    def test_a_dateless_deal_still_lists(self):
        """No sale date means no age — it must not knock the row out."""
        s = sale("Ana", "Verification", sale_date=None)
        self.assertEqual(pending.days_waiting(s, TODAY), "")
        self.assertEqual(pending.build([s], today=TODAY)["count"], 1)

    def test_row_values_match_the_column_order(self):
        s = sale("Ana", clean.SUBMITTED, sale_date=dt.date(2026, 8, 18),
                 business="KBE auto sale", contract="281682")
        vals = pending.row_values(s, TODAY)
        self.assertEqual(len(vals), len(pending.COLUMNS))
        self.assertEqual(vals[0], "Ana")
        self.assertEqual(vals[3], "KBE auto sale")
        self.assertEqual(vals[4], "281682")
        self.assertEqual(vals[5], clean.SUBMITTED)
        self.assertIn("supplier", vals[6].lower())


if __name__ == "__main__":
    unittest.main()
