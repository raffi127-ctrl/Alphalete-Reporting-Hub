"""Raf's computer relays three offices under ONE key (2026-11-03)."""
import json
import unittest

from automations.push_report import run as PR

HDR = ["Office", "Day", "Stage", "Summary", "Detail", "Count", "First At",
       "Last At"]


def row(key, summ, office, sent, at):
    return [key, "2026-11-03", "probe-push-stats", summ,
            json.dumps({"office": office, "sent_today": sent}), "1", "",
            "11/3/2026 %s" % at]


class Book:
    def __init__(self, rows):
        self.rows = rows

    def worksheet(self, _):
        return self

    def get_all_values(self):
        return [HDR] + self.rows


class RelayMulti(unittest.TestCase):
    def test_each_office_gets_its_own_row(self):
        b = Book([row("raf", "push stats 11280", "11280", 5, "18:00:00"),
                  row("raf", "push stats 23965", "23965", 2, "18:10:00"),
                  row("raf", "push stats 24065", "24065", 9, "18:20:00")])
        for oid, sent in (("11280", 5), ("23965", 2), ("24065", 9)):
            stats, _ = PR._relay_stats(b, "raf", "2026-11-03", oid)
            self.assertEqual(stats["sent_today"], sent, oid)

    def test_single_office_rows_still_read(self):
        b = Book([row("carlos", "push stats", "11580", 31, "15:00:00")])
        stats, _ = PR._relay_stats(b, "carlos", "2026-11-03", "11580")
        self.assertEqual(stats["sent_today"], 31)

    def test_raf_is_on_his_computer_not_lucy_4(self):
        tabs = {t: m for t, _l, m in PR.OFFICES}
        for oid in ("11280", "23965", "24065"):
            self.assertEqual(tabs.get("relay:raf:%s" % oid), "Raf's computer")
        self.assertNotIn("Lucy 4", tabs.values())


if __name__ == "__main__":
    unittest.main()
