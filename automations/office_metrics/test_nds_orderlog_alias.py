"""The NDS order log matches an owner through the ICD alias sheet, so Tableau's
full-legal-name spelling ('JUAN IGNACIO LUCIO [lucio marketing, inc.]') finds
the office we call Juan Lucio (2026-11-09)."""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.office_metrics import nds_orderlog as N


class AliasMatch(unittest.TestCase):
    def _csv(self):
        d = Path(tempfile.mkdtemp()); p = d / "ol.csv"
        with open(p, "w", newline="", encoding="utf-16") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["Owner & Office", "Customer Zip Simple", "Order Status"])
            w.writerow(["JUAN IGNACIO LUCIO\r [lucio marketing, inc.]", "78414", "Active"])
            w.writerow(["ZAID ARABYAT\r [aces acquisitions, inc.]", "02124", "Active"])
            w.writerow(["JAIRO RUIZ\r [profits management, inc.]", "33101", "Active"])
        return p

    def test_alias_spelling_matches(self):
        raw = {"Juan Lucio": ["Juan Ignacio Lucio"], "Zaid Arabiyat": ["Zaid Arabyat"]}
        with mock.patch("automations.focus_office_att.aliases.load_aliases", return_value=raw):
            _, juan = N.load(self._csv(), "Juan Lucio")
            _, zaid = N.load(self._csv(), "Zaid Arabiyat")
            _, jairo = N.load(self._csv(), "Jairo Ruiz")
        self.assertEqual(len(juan), 1); self.assertEqual(len(zaid), 1); self.assertEqual(len(jairo), 1)

    def test_churn_slice_accepts_the_alias_spelling(self):
        from automations.office_metrics.owner_match import accepted_spellings, is_owner
        raw = {"Zaid Arabiyat": ["Zaid Arabyat"]}
        with mock.patch("automations.focus_office_att.aliases.load_aliases", return_value=raw):
            acc = accepted_spellings("Zaid Arabiyat")
        self.assertTrue(is_owner("ZAID ARABYAT", acc))
        self.assertTrue(is_owner("Zaid Arabiyat\n[aces acquisitions, inc.]", acc))
        self.assertFalse(is_owner("JAIRO RUIZ", acc))

    def test_literal_match_still_works_without_the_sheet(self):
        with mock.patch("automations.focus_office_att.aliases.load_aliases", side_effect=RuntimeError("offline")):
            _, jairo = N.load(self._csv(), "Jairo Ruiz")
        self.assertEqual(len(jairo), 1)


if __name__ == "__main__":
    unittest.main()
