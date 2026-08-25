"""The per-office SARA Plus parse in opt_nds / opt_retail.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.alphalete_org_report.test_sara_office_parser

WHAT THIS GUARDS (Megan 2026-08-24). The same SARA Plus table has TWO export
shapes, and opt_retail carries a parser for each:

  - Crosstab export  → WIDE: one column per measure
                       → parse_sara_plus_office_totals
  - View Data scrape → LONG: Owner & Office | Rep | rep.Rep Number |
                       Measure Names | Measure Values, one row per
                       (rep, measure) → parse_sara_view_data

opt_nds downloads this file with scrape_view_data_patchright, so it is ALWAYS
long — but it imported the wide parser. That parser finds 'Owner & Office' and
'Rep', finds no metric columns (they are row values under Measure Names), and
returns {} without raising. Result on 2026-08-24: Next Up % and Extra/Premium %
blank on every NDS tab of the Alphalete Org focus report, while Retail — same
dashboard, same scrape, correct parser — filled fine. The run still exited 0.

Nothing here talks to Tableau; the fixture is the real column layout as logged
off Lucy 3 that morning.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from automations.alphalete_org_report import opt_nds
from automations.alphalete_org_report.opt_retail import (
    parse_sara_plus_office_totals, parse_sara_view_data)

# Exact header logged on Lucy 3 2026-08-24 for opt_nds_sara_plus_office.csv.
LONG_HEADER = ["Owner & Office", "Rep", "rep.Rep Number",
               "Measure Names", "Measure Values"]
LONG_ROWS = [
    ("RAFAEL HIDALGO[alphalete, inc.]", "Ana Rep", "111", "New/Port Lines", "10.0000"),
    ("RAFAEL HIDALGO[alphalete, inc.]", "Ana Rep", "111", "Next Up", "4.0000"),
    ("RAFAEL HIDALGO[alphalete, inc.]", "Ana Rep", "111", "Premium/Elite", "3.0000"),
    ("RAFAEL HIDALGO[alphalete, inc.]", "Ana Rep", "111", "Extra", "1.0000"),
    ("RAFAEL HIDALGO[alphalete, inc.]", "Bo Rep", "222", "New/Port Lines", "6.0000"),
    ("RAFAEL HIDALGO[alphalete, inc.]", "Bo Rep", "222", "Next Up", "2.0000"),
    ("RAFAEL HIDALGO[alphalete, inc.]", "Bo Rep", "222", "Premium/Elite", "1.0000"),
    ("RAFAEL HIDALGO[alphalete, inc.]", "Bo Rep", "222", "Extra", "0.0000"),
]


def _write_long_csv() -> Path:
    """UTF-16 tab-delimited, the shape _read_tab_csv expects."""
    fh = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                     encoding="utf-16")
    lines = ["\t".join(LONG_HEADER)]
    lines += ["\t".join(r) for r in LONG_ROWS]
    fh.write("\n".join(lines))
    fh.close()
    return Path(fh.name)


class SaraOfficeParserTest(unittest.TestCase):

    def setUp(self):
        self.path = _write_long_csv()

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def test_view_data_parser_reads_the_long_export(self):
        got = parse_sara_view_data(self.path)
        self.assertIn("rafael hidalgo", got)
        row = got["rafael hidalgo"]
        # Summed across both reps.
        self.assertEqual(row["New/Port Lines"], 16)
        self.assertEqual(row["Next Up"], 6)
        self.assertEqual(row["Premium/Elite"], 4)
        self.assertEqual(row["Extra"], 1)
        self.assertEqual(row["_active_reps"], 2)

    def test_wide_parser_returns_empty_on_the_long_export(self):
        """The trap itself: silent {}, no exception. If this ever starts
        passing, the wide parser grew long-format support and the guard
        below matters less — but it must never be the NDS default."""
        self.assertEqual(parse_sara_plus_office_totals(self.path), {})

    def test_opt_nds_is_wired_to_the_view_data_parser(self):
        """opt_nds imports the parser lazily inside run(), so assert on the
        source rather than importing a name that only exists at call time."""
        src = Path(opt_nds.__file__).with_suffix(".py").read_text(
            encoding="utf-8")
        self.assertIn("parse_sara_view_data as _parse_sara_office", src)
        self.assertNotIn("parse_sara_plus_office_totals as _parse_sara_office",
                         src)

    def test_metrics_nds_actually_reads_are_all_present(self):
        """opt_nds computes Next Up % and Extra/Premium % from exactly these
        four keys — a parser swap that dropped any of them would blank the
        same two columns all over again."""
        row = parse_sara_view_data(self.path)["rafael hidalgo"]
        for key in ("Next Up", "New/Port Lines", "Premium/Elite", "Extra"):
            self.assertIn(key, row)


if __name__ == "__main__":
    unittest.main()
