"""collect._read_tab header matching (11/23: Jairo's "full name" lowercase)."""
import sys
import types
import unittest
from unittest import mock

from automations.ad_photo_threads import collect


class _Sh:
    def __init__(self, rows):
        self._rows = rows

    def worksheet(self, _tab):
        return types.SimpleNamespace(get_all_values=lambda: self._rows)


def _read(rows):
    fake_fill = types.SimpleNamespace(_retry=lambda fn: fn())
    with mock.patch.dict(sys.modules,
                         {"automations.recruiting_report.fill": fake_fill}):
        return collect._read_tab(_Sh(rows), "Jairo Ruiz")


class ReadTabHeaders(unittest.TestCase):
    def test_lowercase_full_name_header_is_read(self):
        rows = [["Client Name", "Date 1st Rd", "1st Round Interviewer",
                 "full name", "Ad Title"],
                ["Jairo Ruiz", "11/23/2026", "Milena", "Eloy Dalama", "Sales"]]
        out = _read(rows)
        self.assertEqual(out[0]["Full Name"], "Eloy Dalama")
        self.assertEqual(out[0]["Ad Title"], "Sales")

    def test_blank_header_after_interviewer_still_means_full_name(self):
        rows = [["Date 1st Rd", "1st Round Interviewer", "", "Ad Title"],
                ["11/23/2026", "Milena", "Rehan Roy", "Sales"]]
        self.assertEqual(_read(rows)[0]["Full Name"], "Rehan Roy")

    def test_missing_header_still_raises(self):
        rows = [["Date 1st Rd", "Name", "Ad Title"], ["11/23/2026", "X", "Y"]]
        with self.assertRaises(RuntimeError):
            _read(rows)


if __name__ == "__main__":
    unittest.main()
