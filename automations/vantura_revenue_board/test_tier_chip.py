# -*- coding: utf-8 -*-
"""extra['tier_chip'] on a base-comp board + extra['reps_extra'] after the rep
count (NDS, Carlos 2026-11-15); boards without them render as before."""
import datetime as dt
import unittest
from unittest import mock

from automations.vantura_revenue_board import run as V

ROWS = [{"rep": "Ana Lopez", "tier": "T2", "total": 1000.0, "next": "", "ntotal": 1000.0,
         "Mon": 1000.0, "rep_badge": "5 orders · 9 port lines", "rep_lines": ["Ana", "Lopez"],
         "rep_tags": "4 new phones · 5 BYOD · 0 Air<br>0 Next Up",
         "extra": [{"text": "3 ($639)", "cls": "ct"}]}]


def _html(extra):
    captured = {}

    def fake_write(self_path, text, encoding="utf-8"):
        captured["html"] = text
    with mock.patch("pathlib.Path.write_text", fake_write), \
         mock.patch("pathlib.Path.mkdir", lambda *a, **k: None), \
         mock.patch.dict("sys.modules", {"patchright": None, "patchright.sync_api": None}):
        try:
            V._render_html(ROWS, {"days": {"Mon": 1000.0}}, dt.date(2026, 11, 9), dt.date(2026, 11, 15),
                           V.Path("/tmp/x.png"), "NDS Revenue Board", tiered=False, extra=extra)
        except Exception:  # noqa: BLE001 -- the browser step is not the point
            pass
    return captured.get("html", "")


class TierChip(unittest.TestCase):
    def test_chip_and_reps_extra_on(self):
        html = _html({"headers": ["LINES ACTIVATED"], "tier_chip": True,
                      "reps_extra": " <span>· 5.0 sales per rep</span>"})
        self.assertIn(">TIER</th>", html)
        self.assertIn('class="chip"', html)
        self.assertIn(">T2</span>", html)
        self.assertIn('<div class="cval">1 <span>· 5.0 sales per rep</span></div>', html)
        self.assertNotIn("NEXT TIER", html)                       # no bonus math on a base-comp board
        self.assertIn("5 orders · 9 port lines", html)
        self.assertIn('<div class="rn">ANA</div><div class="rn">LOPEZ</div>', html)      # stacked name cell
        self.assertIn('<div class="rtag">4 new phones', html)
        self.assertIn("3 ($639)", html)
        # the totals row keeps its columns aligned: a blank cell under TIER
        self.assertIn('<td class="rep">OFFICE TOTAL</td><td class="tot">$1,000</td><td></td>', html)

    def test_office_total_badge_and_tags(self):
        captured = {}

        def fake_write(self_path, text, encoding="utf-8"):
            captured["html"] = text
        with mock.patch("pathlib.Path.write_text", fake_write), \
             mock.patch("pathlib.Path.mkdir", lambda *a, **k: None), \
             mock.patch.dict("sys.modules", {"patchright": None, "patchright.sync_api": None}):
            try:
                V._render_html(ROWS, {"days": {"Mon": 1000.0}, "rep_badge": "43 orders \u00b7 134 apps",
                                      "rep_tags": "92 new phones \u00b7 39 BYOD \u00b7 3 Air<br>1 Next Up"},
                               dt.date(2026, 11, 9), dt.date(2026, 11, 15), V.Path("/tmp/x.png"),
                               "NDS Revenue Board", tiered=False, extra={"tier_chip": True})
            except Exception:  # noqa: BLE001
                pass
        html = captured.get("html", "")
        self.assertIn('OFFICE TOTAL <span class="rb">43 orders \u00b7 134 apps</span><div class="rtag">92 new phones', html)

    def test_plain_base_comp_board_unchanged(self):
        html = _html(None)
        self.assertNotIn(">TIER</th>", html)
        self.assertNotIn('class="chip"', html)
        self.assertIn('<div class="cval">1</div>', html)          # the plain rep count
        self.assertIn('<td class="rep">OFFICE TOTAL</td><td class="tot">$1,000</td><td class="day ttl">', html)


if __name__ == "__main__":
    unittest.main()
