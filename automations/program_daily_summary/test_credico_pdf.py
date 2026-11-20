"""python -m unittest automations.program_daily_summary.test_credico_pdf"""
import datetime as dt
import unittest

from automations.program_daily_summary.credico_pdf import parse_week_words

XS = [281, 310, 339, 368, 397, 426, 455]          # Sun..Sat column centers


def _row(y, cells):
    """cells: list of (x, text)."""
    return [(x - 4, y, x + 4, y + 6, t) for x, t in cells]


def _page(owner_rows, totals, market_rows=()):
    words = _row(36, [(20, "Week"), (40, "Ending")] +
                 [(x, f"11/{15 + i}") for i, x in enumerate(XS)])
    words += _row(54, [(20, "Owner"), (40, "Name"), (283, "Sun")])
    y = 62
    for name, vals in owner_rows:
        words += _row(y, [(20, name), (206, "CA")] +
                      [(x, v) for x, v in zip(XS, vals)])
        y += 8
    words += _row(y, [(x, v) for x, v in zip(XS, totals)] +
                  [(520, "2,322"), (680, "88.1%"), (820, "4.2")])
    y += 20
    for name, vals in market_rows:
        words += _row(y, [(230, name)] + [(x, v) for x, v in zip(XS, vals)])
        y += 8
    return words, "Week Ending November 21, 2026"


class ParseWeekWords(unittest.TestCase):
    def test_totals_row_by_date(self):
        words, text = _page([("Stacy", ["1", "37", "54", "41", "38", "0", "0"])],
                            ["30", "448", "512", "564", "425", "0", "0"])
        got = parse_week_words(words, text)
        self.assertEqual(got[dt.date(2026, 11, 16)], 448)
        self.assertEqual(got[dt.date(2026, 11, 19)], 425)
        self.assertEqual(len(got), 7)

    def test_market_table_below_is_not_totals(self):
        words, text = _page([("Ana", ["1", "2", "3", "4", "5", "0", "0"])],
                            ["54", "522", "522", "541", "533", "0", "0"],
                            market_rows=[("Massachusetts",
                                          ["14", "84", "82", "85", "79", "", ""])])
        self.assertEqual(parse_week_words(words, text)[dt.date(2026, 11, 15)], 54)

    def test_no_week_header_returns_empty(self):
        words, _ = _page([], ["1"] * 7)
        self.assertEqual(parse_week_words(words, "Month To Date"), {})


if __name__ == "__main__":
    unittest.main()
