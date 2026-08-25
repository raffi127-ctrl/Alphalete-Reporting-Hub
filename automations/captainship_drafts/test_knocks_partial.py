"""Pins la decision de Eve del 2026-08-25: las secciones de knocks salen con
las oficinas que YA tenemos, y el correo no se retiene por las que faltan.

Contexto: de los 35 ICDs de las seis capitanias fiber, 16 no estaban en la
lista de Office Access de la cuenta del reporte (rhidalgo). Se pidieron los
accesos y entran de a poco, asi que el reporte tiene que funcionar con
cobertura parcial y crecer solo a medida que ownerville los otorga.

Lo que queda clavado:

  1. un ICD sin Office Access NO lleva PENDING_MARK — si lo llevara,
     run.py --send-reviewed retendria el correo del capitan entero, que es
     exactamente lo que dejo a cinco capitanes sin reporte el 24/8
  2. ese hueco IGUAL se ve en el correo (caja gris con el motivo), nunca
     desaparece en silencio
  3. una falla de verdad (Timeout, etc.) SI sigue siendo amarilla y sigue
     frenando: la distincion es el punto entero
  4. la fila de totales dice "(N of M ICDs)" cuando no estan todas
  5. un cero real (nadie golpeo) NO cuenta como oficina faltante — si no,
     todo domingo tranquilo se leeria como un problema de accesos
  6. el flavor fiber tiene las dos secciones y sus dos lineas de intro,
     index-alineadas

Run:  python -m automations.captainship_drafts.test_knocks_partial
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.captainship_drafts import config
from automations.captainship_drafts import email_build as EB
from automations.captainship_drafts import knock_dispo_images as KD


class AccessGapIsNotAFailure(unittest.TestCase):
    def test_access_gap_note_does_not_hold_the_send(self):
        note = KD._owner_error_note(
            RuntimeError("Wayne Rude not found in ownerville"))
        self.assertTrue(note.startswith(EB.NO_DATA_MARK))
        html = EB._pending("Daily Knocks — Wayne Rude", note)
        self.assertNotIn(EB.PENDING_MARK, html)

    def test_access_gap_still_says_why(self):
        note = KD._owner_error_note(
            RuntimeError("couldn't impersonate Coel Reif"))
        html = EB._pending("Daily Knocks — Coel Reif", note)
        self.assertIn("access", html.lower())
        self.assertIn("no data available", html)

    def test_a_real_failure_still_blocks(self):
        note = KD._owner_error_note(TimeoutError("Page.goto: Timeout 20000ms"))
        self.assertFalse(note.startswith(EB.NO_DATA_MARK))
        self.assertIn(EB.PENDING_MARK,
                      EB._pending("Daily Knocks — Jay Turnage", note))


class OfficesWeCannotPullStayOutOfTheEmail(unittest.TestCase):
    """Eve 2026-08-25: "esas 12 oficinas no las vamos a incluir por ahora
    aunque hayamos pedido los accesos". Twelve grey notes about offices the
    captain cannot do anything about is not information, it is noise."""

    def test_an_access_gap_is_recognised(self):
        for msg in ("Wayne Rude not found in ownerville",
                    "Couldn't impersonate 'Brian Tran' in ownerville: ov "
                    "access request pending (request sent in office access "
                    "table)"):
            self.assertTrue(KD.is_access_gap(RuntimeError(msg)), msg)

    def test_a_real_failure_is_not_an_access_gap(self):
        """Still shown, still yellow, still blocks — that is the point of the
        distinction."""
        self.assertFalse(KD.is_access_gap(
            TimeoutError("Page.goto: Timeout 20000ms exceeded")))

    def test_an_all_gapped_section_is_grey_not_yellow(self):
        """A captainship with nothing reachable must not fall into
        email_build's empty-list branch, which is a PENDING_MARK note and
        would hold that captain's entire email."""
        err = {"daily_knocks": EB.NO_DATA_MARK + "no office in this "
               "captainship is reachable yet — 6 still waiting on ownerville "
               "Office Access"}
        html = EB._pending("Daily Knocks boards", err["daily_knocks"])
        self.assertNotIn(EB.PENDING_MARK, html)
        self.assertIn("no data available", html)


class TheDailyBoardSaysDaily(unittest.TestCase):
    """Eve 2026-08-25 asked for "DAILY" in front of the per-owner board's
    title. It has to be a PARAMETER: the same renderer draws the metrics
    threads, the intraday slots and the /knocks replies, and none of those
    are the captainship email's daily board."""

    def test_the_prefix_is_opt_in(self):
        import inspect
        from automations.total_knocks import render as R
        sig = inspect.signature(R.render_total_knocks)
        self.assertIn("title_prefix", sig.parameters)
        self.assertEqual(sig.parameters["title_prefix"].default, "",
                         "default must leave every other board unchanged")

    def test_every_owner_board_carries_chans_comparison_line(self):
        """Eve 2026-08-25, with Megan's Cody Cannon board as the reference:
        the teal CHAN PARK TOTAL line sits above each office's own TOTAL, on
        EVERY owner's board — not just on the captainship summary."""
        rows = [{"Rep": "x"}]
        got = KD.compare_totals_for("Cody Cannon", rows)
        self.assertEqual(got, [("Chan Park", rows)])

    def test_chans_own_board_has_no_comparison_line(self):
        """A comparison line identical to the TOTAL underneath it reads like
        the office was counted twice."""
        self.assertEqual(KD.compare_totals_for("Chan Park", [{"Rep": "x"}]), [])

    def test_no_comparison_data_means_no_line(self):
        """Rather than a line built from nothing."""
        self.assertEqual(KD.compare_totals_for("Cody Cannon", None), [])
        self.assertEqual(KD.compare_totals_for("Cody Cannon", []), [])

    def test_the_per_rep_column_stays_on_the_board(self):
        """It is blank on rep rows BY DESIGN — a rep row is one rep, so per-rep
        there would repeat Total Talk to — and carries the real number on both
        totals rows (Chan's 65.0 and the office's 77.5 in Megan's reference
        board). Eve 2026-08-25: "no la tenes que sacar"."""
        from automations.total_knocks import render as R
        self.assertIn(R.COL_TALK_TO_PER_REP, R.COMBINED_KNOCKS_HEADERS)
        self.assertIn(R.COL_TALK_TO_PER_REP, R.DERIVED_COLUMNS)

    def test_the_captainship_board_passes_it(self):
        import inspect
        src = inspect.getsource(KD.capture_sections)
        self.assertIn('title_prefix="DAILY "', src)


class TotalsLabelTellsTheTruth(unittest.TestCase):
    def test_partial_says_how_many(self):
        self.assertEqual(KD.totals_label(4, 8),
                         "CAPTAINSHIP TOTALS (4 of 8 ICDs)")

    def test_complete_stays_bare(self):
        self.assertEqual(KD.totals_label(13, 13), "CAPTAINSHIP TOTALS")

    def test_no_roster_count_stays_bare(self):
        self.assertEqual(KD.totals_label(3, None), "CAPTAINSHIP TOTALS")

    def test_a_real_zero_is_covered_not_missing(self):
        """Two owners on the roster, one with rows and one that answered with
        a zero: `captured` holds only the first, but the totals speak for
        both, so the label must stay bare."""
        captured = [("Chan Park", {"name": "Chan Park"}, [])]
        table, _bgs = KD.daily_summary_table(captured, chan_rows=None,
                                             roster_n=2, n_covered=2)
        self.assertEqual(table[-1][0], "CAPTAINSHIP TOTALS")
        table, _bgs = KD.daily_summary_table(captured, chan_rows=None,
                                             roster_n=2, n_covered=1)
        self.assertEqual(table[-1][0], "CAPTAINSHIP TOTALS (1 of 2 ICDs)")


class FiberCarriesBothSections(unittest.TestCase):
    def test_kinds_and_intro_stay_index_aligned(self):
        for flavor in ("fiber", "rafael"):
            _greeting, items = config._INTRO[flavor]
            self.assertEqual(len(items), len(config.SECTION_KINDS[flavor]),
                             f"{flavor}: intro/kinds drifted")
            self.assertEqual(config.SECTION_KINDS[flavor][-2:],
                             ["daily_knocks", "knock_dispo"], flavor)

    def test_weekly_is_sunday_and_monday_only(self):
        sunday, monday, tuesday = (dt.date(2026, 8, 23), dt.date(2026, 8, 24),
                                   dt.date(2026, 8, 25))
        self.assertTrue(config.kind_runs_on("knock_dispo", sunday))
        self.assertTrue(config.kind_runs_on("knock_dispo", monday))
        self.assertFalse(config.kind_runs_on("knock_dispo", tuesday))
        self.assertTrue(config.kind_runs_on("daily_knocks", tuesday))


if __name__ == "__main__":
    unittest.main(verbosity=2)
