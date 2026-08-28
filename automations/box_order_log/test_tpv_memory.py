"""Tests for THE TPV MEMORY — a sale stays a sale once we've seen it pass TPV.

The failure these lock down (2026-08-28, found chasing "El Meson Doña Tere"):
Tableau's export DROPS a deal's TPV transition row weeks after the fact, leaving
only `Draft` and `Cancelled by Broker`. The TPV gate reads history, so the deal
reads as "cancelled before it ever reached TPV" and is thrown out — it vanishes
from the Slack workbook and the payout tables while the sheet, which merges,
goes on showing a stale "TPV Passed" forever. 18 of Carlos's sales at once.

The rule itself is unchanged (Carlos, 2026-07-22: "TPV completed and forward is
a sale, but it could go to cancelled by broker at any point"). What changed is
that the gate will now accept the sheet's own record as evidence when today's
export has forgotten.

    PYTHONPATH=. python -m unittest \
        automations.box_order_log.test_tpv_memory -v
"""
from __future__ import annotations

import unittest

from automations.box_order_log import clean, sheet


def row(contract, account, status, sub, sale_date="8/13/2026", **extra):
    r = {"Contract ID": contract, "Account Id": account, "Status": status,
         "Contr. Sub-status": sub, "Sale Date": sale_date,
         "Rep Name": "Ashley Tapia", "Business Name": "El Meson Doña Tere",
         "Accepted Date": "", "Complete Sales": "0"}
    r.update(extra)
    return r


# The exact shape of the deal that started this: the TPV row is GONE.
EL_MESON = [
    row("278282", "275582", "Draft", "Awaiting Signature"),
    row("278285", "275582", "Cancelled by Broker", "Cancelled by Broker"),
]

KEY = ("278285", "275582")


class TpvMemory(unittest.TestCase):

    def test_without_memory_the_deal_is_dropped(self):
        """The old behaviour, kept explicit so a regression is loud."""
        sales, stats = clean.collapse(EL_MESON)
        self.assertEqual(sales, [])
        self.assertEqual(stats["dropped_never_reached_tpv"], 1)
        self.assertEqual(stats.get("rescued_by_tpv_memory", 0), 0)

    def test_memory_rescues_it(self):
        sales, stats = clean.collapse(EL_MESON, tpv_seen={KEY})
        self.assertEqual(len(sales), 1)
        self.assertEqual(stats["rescued_by_tpv_memory"], 1)
        self.assertEqual(stats["dropped_never_reached_tpv"], 0)

    def test_rescued_deal_shows_its_CURRENT_status(self):
        """It comes back as the cancel it is — not as a phantom TPV Passed.

        This is what lets the sheet self-heal: the merge finally has a fresh
        row to replace the stale one with.
        """
        (s,), _ = clean.collapse(EL_MESON, tpv_seen={KEY})
        self.assertEqual(s.status, "Cancelled by Broker")
        self.assertTrue(s.is_cancel)

    def test_memory_does_not_resurrect_a_pure_draft(self):
        """A Draft is dropped before the gate — memory must not reach it.

        Drafts are tablet-quote noise; if a stale key ever named one, letting
        it through would invent a sale that never existed.
        """
        sales, _ = clean.collapse(
            EL_MESON, tpv_seen={KEY, ("278282", "275582")})
        self.assertEqual([s.key[0] for s in sales], ["278285"])

    def test_memory_does_not_resurrect_a_dead_level(self):
        """TPV Failed stays dead — DEAD_LEVELS runs before the TPV gate."""
        failed = [row("999", "111", "Verification", "TPV Failed")]
        sales, _ = clean.collapse(failed, tpv_seen={("999", "111")})
        self.assertEqual(sales, [])

    def test_keys_match_across_sheets_number_formatting(self):
        """Sheets renders IDs as numbers: "278,285" must still match."""
        sales, _ = clean.collapse(EL_MESON, tpv_seen={("278,285", "275,582")})
        self.assertEqual(len(sales), 1)

    def test_empty_memory_is_exactly_the_old_behaviour(self):
        for empty in (set(), frozenset(), None, ()):
            sales, _ = clean.collapse(EL_MESON, tpv_seen=empty)
            self.assertEqual(sales, [], "empty memory changed the outcome")

    def test_a_real_tpv_row_still_wins_without_memory(self):
        """The export proving it is still the primary path."""
        rows = EL_MESON + [row("278285", "275582", "Verification", "TPV Passed")]
        sales, stats = clean.collapse(rows)
        self.assertEqual(len(sales), 1)
        self.assertEqual(stats.get("rescued_by_tpv_memory", 0), 0)


class EverPassedTpvSurvivesDeath(unittest.TestCase):
    """Carlos, 2026-08-28: "If it ever said TPV passed, it should never get
    removed from the order log unless we're past the date range." So a later
    TPV Failed / Rejected QC no longer deletes the sale."""

    PASSED_THEN_FAILED = [
        row("300100", "200100", "Verification", "TPV Passed"),
        row("300100", "200100", "Verification", "TPV Failed"),
    ]

    def test_tpv_passed_then_failed_is_KEPT(self):
        """When BOTH rows survive in the export this already worked, because
        LEVEL_PRIORITY ranks TPV Passed above TPV Failed, so the sale surfaces
        as the pass and never reaches the dead-level filter. Pinned so a
        priority reshuffle can't quietly start deleting these."""
        sales, stats = clean.collapse(self.PASSED_THEN_FAILED)
        self.assertEqual(len(sales), 1)
        self.assertEqual(stats["dropped_dead"], 0)

    def test_tpv_passed_then_rejected_qc_is_KEPT(self):
        rows = [row("300101", "200101", "Verification", "TPV Passed"),
                row("300101", "200101", "Verification", "Rejected QC")]
        sales, _ = clean.collapse(rows)
        self.assertEqual(len(sales), 1)

    def test_requires_review_is_not_proof_of_passing(self):
        """Requires TPV Review is not "TPV passed" — the review is still owed,
        so it must not appear in the immunity set."""
        rows = [row("300102", "200102", "Verification", "Requires TPV Review")]
        (s,), _ = clean.collapse(rows)
        self.assertFalse(clean.ever_passed_tpv(s))

    def test_only_a_failure_left_in_the_export_dies_without_memory(self):
        """The shape that actually loses sales: the pass row is gone."""
        rows = [row("300102", "200102", "Verification", "TPV Failed")]
        sales, stats = clean.collapse(rows)
        self.assertEqual(sales, [])
        self.assertEqual(stats["dropped_dead"], 1)

    def test_bare_tpv_failed_still_dies(self):
        rows = [row("300103", "200103", "Verification", "TPV Failed")]
        self.assertEqual(clean.collapse(rows)[0], [])

    def test_memory_alone_can_grant_immunity(self):
        """The export erased the TPV row AND the deal has since failed."""
        rows = [row("300104", "200104", "Verification", "TPV Failed")]
        sales, stats = clean.collapse(
            rows, tpv_proven={("300104", "200104")})
        self.assertEqual(len(sales), 1)
        self.assertEqual(stats["kept_dead_after_tpv"], 1)

    def test_broad_memory_does_NOT_grant_immunity(self):
        """tpv_seen decides "was it a sale", not "does it survive a fail".

        A deal only ever seen at Requires TPV Review is in tpv_seen but must
        not be in tpv_proven, so a later TPV Failed still kills it.
        """
        rows = [row("300105", "200105", "Verification", "TPV Failed")]
        sales, _ = clean.collapse(rows, tpv_seen={("300105", "200105")})
        self.assertEqual(sales, [])

    def test_both_levels_survive_in_the_history(self):
        """Whatever surfaces, the full history is carried so Secondary Status
        can show the deal failed after passing."""
        (s,), _ = clean.collapse(self.PASSED_THEN_FAILED)
        for lvl in ("TPV Passed", "TPV Failed"):
            self.assertIn("Verification" + clean._LEVEL_SEP + lvl, s.history)


class ProvenLevels(unittest.TestCase):

    def test_proven_is_sale_levels_minus_requires_review(self):
        self.assertTrue(all(l in clean.SALE_LEVELS
                            for l in clean.TPV_PROVEN_LEVELS))
        self.assertNotIn("Verification" + clean._LEVEL_SEP + "Requires TPV Review",
                         clean.TPV_PROVEN_LEVELS)

    def test_sheet_row_proved_tpv_reads_secondary(self):
        r = [""] * len(sheet.DATA_HEADERS)
        r[sheet._COL_STATUS] = "Verification"
        r[sheet._COL_STATUS + 1] = "TPV Failed"
        r[sheet._COL_STATUS + 2] = "Verification – TPV Passed"
        self.assertTrue(sheet.row_proved_tpv(r))

    def test_sheet_row_proved_tpv_rejects_requires_review(self):
        r = [""] * len(sheet.DATA_HEADERS)
        r[sheet._COL_STATUS] = "Verification"
        r[sheet._COL_STATUS + 1] = "TPV Failed"
        r[sheet._COL_STATUS + 2] = "Verification – Requires TPV Review"
        self.assertFalse(sheet.row_proved_tpv(r))


class MergeKeepsFailedAfterTpv(unittest.TestCase):
    """The sheet's own purge has to follow the same rule, or the deal is
    dropped on the way back out even though collapse kept it."""

    def _row(self, sub, secondary=""):
        r = [""] * len(sheet.DATA_HEADERS)
        r[sheet._COL_WEEK] = "08/15/2026"
        r[1] = "Ashley Tapia"
        r[sheet._COL_CONTRACT] = "300200"
        r[sheet._COL_ACCOUNT] = "200200"
        r[sheet._COL_STATUS] = "Verification"
        r[sheet._COL_STATUS + 1] = sub
        r[sheet._COL_STATUS + 2] = secondary
        return r

    def test_failed_row_with_tpv_history_is_kept(self):
        import datetime as dt
        out = sheet.merge_rows([self._row("TPV Failed", "Verification – TPV Passed")],
                               [], today=dt.date(2026, 8, 28))
        self.assertEqual(out["purged"], 0)
        self.assertEqual(len(out["rows"]), 1)

    def test_failed_row_without_tpv_history_is_purged(self):
        import datetime as dt
        out = sheet.merge_rows([self._row("TPV Failed")], [],
                               today=dt.date(2026, 8, 28))
        self.assertEqual(out["purged"], 1)
        self.assertEqual(out["rows"], [])


class SheetRowReadsAsTpv(unittest.TestCase):
    """What the sheet counts as evidence, read the way a human would."""

    def _row(self, status, sub, secondary=""):
        r = [""] * len(sheet.DATA_HEADERS)
        r[sheet._COL_STATUS] = status
        r[sheet._COL_STATUS + 1] = sub
        r[sheet._COL_STATUS + 2] = secondary
        return r

    def test_surfaced_status_counts(self):
        self.assertTrue(sheet.row_reached_tpv(
            self._row("Verification", "TPV Passed")))
        self.assertTrue(sheet.row_reached_tpv(
            self._row("Accepted by Supplier", "Accepted by Supplier")))

    def test_secondary_status_counts(self):
        """The cancel is surfaced; the TPV lives in Secondary."""
        self.assertTrue(sheet.row_reached_tpv(self._row(
            "Cancelled by Broker", "Cancelled by Broker",
            "Verification – TPV Passed, Submitted to Supplier")))

    def test_incomplete_is_exempt(self):
        self.assertTrue(sheet.row_reached_tpv(
            self._row("Incomplete", "Missing Contract Data")))

    def test_a_bare_cancel_is_not_evidence(self):
        self.assertFalse(sheet.row_reached_tpv(
            self._row("Cancelled by Broker", "Cancelled by Broker")))

    def test_a_draft_is_not_evidence(self):
        self.assertFalse(sheet.row_reached_tpv(
            self._row("Draft", "Awaiting Signature")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
