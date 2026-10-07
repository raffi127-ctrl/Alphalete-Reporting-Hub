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

from automations.captainship_drafts import email_build, tableau_shot


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


if __name__ == "__main__":
    unittest.main()
