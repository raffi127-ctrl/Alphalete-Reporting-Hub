"""Team Stats en una semana anterior = nota gris, no falla (Eve 2026-10-06).

El martes 10/6 el reporte cubre el lunes 10/5, que abre una semana de
activaciones nueva. Jairo, Khalil y Colten todavía no tenían activaciones en
ella, así que el board cayó a la semana que termina el 10/4 (como debe) y la
revisión automática los frenó por "no 10/5 column". La nota hace explícito que
es a propósito, y no lleva PENDING_MARK, así que tampoco frena el envío.
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.captainship_drafts import config, email_build, tableau_shot


class TestWeekFallbackNote(unittest.TestCase):
    def setUp(self):
        self.png = Path(tempfile.mkdtemp()) / "team-stats.png"
        self.png.write_bytes(b"x")

    def test_no_sidecar_no_week(self):
        self.assertIsNone(tableau_shot.fallback_week(self.png))

    def test_sidecar_round_trip(self):
        tableau_shot.week_note_path(self.png).write_text("2026-10-04",
                                                         encoding="utf-8")
        self.assertEqual(tableau_shot.fallback_week(self.png),
                         dt.date(2026, 10, 4))

    def test_note_is_grey_and_never_pending(self):
        note = email_build._week_fallback_note(dt.date(2026, 10, 4))
        self.assertIn("week ending 10/4", note)
        self.assertIn("no activations yet", note)
        self.assertNotIn(email_build.PENDING_MARK, note)



class TestActivationLagNote(unittest.TestCase):
    """10/8 y 10/9: el board NDS sin la columna del día reportado (activaciones
    cargan un día tarde) frenó a Khalil, Colten y Jairo. Eve: sale igual, con
    la imagen como está y una nota gris (2026-10-09)."""

    def setUp(self):
        self.png = Path(tempfile.mkdtemp()) / "team-stats.png"
        self.png.write_bytes(b"x")
        self.imgs = email_build._Images()
        self.cap = config.BY_KEY["colten"]

    def _html(self, today):
        return email_build._section_html(
            self.cap, "Captain Team Stats Breakout", "teamstats_tableau", 1,
            {"teamstats_tableau": self.png}, self.imgs, today)

    def test_current_week_board_carries_the_lag_note(self):
        html = self._html(dt.date(2026, 10, 9))
        self.assertIn("activations a day late", html)
        self.assertIn("10/8 column", html)
        self.assertNotIn(email_build.PENDING_MARK, html)

    def test_week_fallback_keeps_its_own_note_only(self):
        tableau_shot.week_note_path(self.png).write_text("2026-10-04",
                                                         encoding="utf-8")
        html = self._html(dt.date(2026, 10, 6))
        self.assertIn("week ending 10/4", html)
        self.assertNotIn("activations a day late", html)

    def test_prompt_accepts_the_note(self):
        from automations.captainship_drafts import auto_send
        self.assertIn("loads activations a day late", auto_send._SYSTEM)


if __name__ == "__main__":
    unittest.main()
