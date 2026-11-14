"""The board's leaders label follows the board name (NDS since 2026-11-14)."""
import datetime as dt
import unittest
from unittest import mock

from automations.vantura_revenue_board import run as V


class Kicker(unittest.TestCase):
    def _html_for(self, board_name):
        captured = {}

        def fake_write(self_path, text, encoding="utf-8"):
            captured["html"] = text
        with mock.patch("pathlib.Path.write_text", fake_write), \
             mock.patch("pathlib.Path.mkdir", lambda *a, **k: None), \
             mock.patch.dict("sys.modules", {"patchright": None, "patchright.sync_api": None}):
            try:
                V._render_html([], {"days": {}}, dt.date(2026, 11, 9), dt.date(2026, 11, 14),
                               V.Path("/tmp/x.png"), board_name, tiered=False)
            except Exception:  # noqa: BLE001 -- the browser step is not the point
                pass
        return captured.get("html", "")

    def test_names(self):
        self.assertIn("NDS LEADERS", self._html_for("NDS Revenue Board"))
        self.assertNotIn("B2B LEADERS", self._html_for("NDS Revenue Board"))
        self.assertIn("AT&T B2B LEADERS", self._html_for("Vantura B2B Revenue"))
        self.assertIn("BOX LEADERS", self._html_for("Vantura BOX Revenue"))
        self.assertIn("VERIZON LEADERS", self._html_for("Verizon Revenue Board"))


if __name__ == "__main__":
    unittest.main()
