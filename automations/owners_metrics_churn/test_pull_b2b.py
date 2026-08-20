"""parse_b2b must SUM the rep rows when the crosstab is broken out by Rep.

2026-08-20: the four B2B captainship tabs went WIRELESS on 08-19, and Atef's
pull moved from ALLTEAMCHURN to the ALLTEAMWireless custom view. That view
carries an extra `Rep` dimension — one row per owner x rep x metric — so plain
assignment left the LAST rep's numbers standing as the whole ICD's. Atef's tab
read 32.3% (10/31, a single rep) instead of 4.2% (37/871, his ICD), and his
Captainship Avg followed. Rate is recomputed from the sums, not read off a row.

The per-captain views (CarlosCaptainship / EvelizWOVan / LuissCaptainship) have
NO Rep column and must keep parsing exactly as before — pinned here too.

Run:  python -m automations.owners_metrics_churn.test_pull_b2b   (or pytest)
"""
from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

if "patchright.sync_api" not in sys.modules:
    _pw = types.ModuleType("patchright")
    _api = types.ModuleType("patchright.sync_api")
    for _n in ("sync_playwright", "Page", "Browser", "BrowserContext",
               "Error", "TimeoutError", "Locator"):
        setattr(_api, _n, type(_n, (), {}))
    _pw.sync_api = _api
    sys.modules["patchright"] = _pw
    sys.modules["patchright.sync_api"] = _api

from automations.owners_metrics_churn import pull  # noqa: E402

_HDR_REP = ["Owner & Office", "Rep", "30-60 Color Churn (copy)", "",
            "0-30 Day", "30 Day", "60 Day", "90 Day", "120 Day"]
_HDR_PLAIN = ["Owner & Office", "30-60 Color Churn (copy)", "",
              "0-30 Day", "30 Day", "60 Day", "90 Day", "120 Day"]


def _write(rows):
    fd = tempfile.NamedTemporaryFile("w", encoding="utf-16-le", suffix=".csv",
                                     delete=False, newline="")
    import csv as _csv
    with fd as f:
        _csv.writer(f, delimiter="\t", lineterminator="\r\n",
                    quoting=_csv.QUOTE_ALL).writerows(rows)
    return Path(fd.name)


def _rep_rows(owner, rep, num, denom, pct):
    return [
        [owner, rep, "Green", "Activated SPE/SP", denom, denom, denom, denom, denom],
        [owner, rep, "Green", "Churn Rate", pct, pct, pct, pct, pct],
        [owner, rep, "Green", "Disconnect count (SPE/SP)", num, num, num, num, num],
    ]


class RepBrokenOutCrosstab(unittest.TestCase):
    def setUp(self):
        rows = [_HDR_REP]
        rows += _rep_rows("ATEF CHOUDHURY\n [alphalete]", "Ana Ruiz",
                          "27", "840", "3.2%")
        rows += _rep_rows("ATEF CHOUDHURY\n [alphalete]", "Kristhel Basilio",
                          "10", "31", "32.3%")
        rows += _rep_rows("Grand Total", "Total", "37", "871", "4.2%")
        self.path = _write(rows)

    def test_owner_row_sums_its_reps(self):
        got = pull.parse_b2b(self.path)["reps"]["Atef Choudhury"]["0-30"]
        self.assertEqual(got["num"], 37.0)
        self.assertEqual(got["denom"], 871.0)

    def test_rate_is_recomputed_not_last_rep(self):
        got = pull.parse_b2b(self.path)["reps"]["Atef Choudhury"]["0-30"]
        self.assertEqual(got["pct"], "4.2%")   # NOT 32.3%, the last rep's

    def test_grand_total_unaffected(self):
        got = pull.parse_b2b(self.path)["office_total"]["0-30"]
        self.assertEqual((got["num"], got["denom"], got["pct"]),
                         (37.0, 871.0, "4.2%"))


class PlainCrosstabUnchanged(unittest.TestCase):
    def setUp(self):
        pct = "5.0%"
        self.path = _write([
            _HDR_PLAIN,
            ["CARLOS HIDALGO\n [alphalete]", "Red", "Activated SPE/SP",
             "278", "289", "300", "310", "320"],
            ["CARLOS HIDALGO\n [alphalete]", "Red", "Churn Rate",
             pct, pct, pct, pct, pct],
            ["CARLOS HIDALGO\n [alphalete]", "Red", "Disconnect count (SPE/SP)",
             "14", "18", "20", "22", "24"],
        ])

    def test_reads_the_row_as_is(self):
        got = pull.parse_b2b(self.path)["reps"]["Carlos Hidalgo"]["0-30"]
        self.assertEqual((got["num"], got["denom"], got["pct"], got["color"]),
                         (14.0, 278.0, "5.0%", "Red"))


if __name__ == "__main__":
    unittest.main()
