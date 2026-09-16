"""Tier Bonus $ comes from Tableau's "Bonus Eligible $" field (Raf 2026-09-16).

  python -m unittest automations.uploaded.test_order_log_tier_bonus
"""
import tempfile
import unittest
from pathlib import Path

from automations.uploaded import order_log as ol


def _crosstab(path: Path, bonus_header: str, bonus_values) -> None:
    cols = [c for c in ol.COLUMNS_TO_KEEP if c != "Rep Tier Bonus Amount"]
    header = cols + ([bonus_header] if bonus_header else [])
    lines = ["\t".join(header)]
    for i, bonus in enumerate(bonus_values):
        row = {c: "x" for c in cols}
        row.update({"Rep": "Aaron Corona", "sp.Order Date (copy)": "9/1/2026",
                    "spe.Install Date": "9/2/2026",
                    "Activatoin Date (order log)": "9/3/2026",
                    "spe.Status": "Active", "sp.SPM Number": f"SPM{i}"})
        vals = [row[c] for c in cols] + ([bonus] if bonus_header else [])
        lines.append("\t".join(vals))
    path.write_text("\n".join(lines), encoding="utf-16")


class TierBonusColumn(unittest.TestCase):
    def _load(self, header, values):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ol.csv"
            _crosstab(p, header, values)
            return ol._load_and_clean(p)

    def test_bonus_eligible_fills_tier_bonus(self):
        df = self._load("Bonus Eligible $", ["$20", "$35", "Null"])
        self.assertEqual(sorted(df["Tier Bonus $"].tolist()), ["", "$20", "$35"])

    def test_missing_column_stays_blank(self):
        df = self._load("", ["", ""])
        self.assertEqual(df["Tier Bonus $"].tolist(), ["", ""])


if __name__ == "__main__":
    unittest.main()
