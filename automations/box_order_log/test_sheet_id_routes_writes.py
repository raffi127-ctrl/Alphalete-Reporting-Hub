"""--sheet-id must route the --sheet WRITES, not just the TPV-memory reads
(2026-10-09: a per-office dry run wrote Ryan's sales into Carlos's board)."""
import unittest
from unittest import mock

from automations.box_order_log import run, sheet, flat_log


class SheetIdRoutesWritesTest(unittest.TestCase):
    def test_push_calls_carry_the_sheet_id(self):
        src = run.__file__
        with open(src) as fh:
            body = fh.read()
        # Both writers accept sheet_id; the run must hand it over.
        self.assertIn("sheet.push(window_sales, today=today, weeks_back=args.weeks,\n"
                      "                       sheet_id=args.sheet_id or None)", body)
        self.assertIn("flat_log.push(sales, today=today, sheet_id=args.sheet_id or None)", body)

    def test_writers_accept_sheet_id(self):
        import inspect
        self.assertIn("sheet_id", inspect.signature(sheet.push).parameters)
        self.assertIn("sheet_id", inspect.signature(flat_log.push).parameters)


if __name__ == "__main__":
    unittest.main()
