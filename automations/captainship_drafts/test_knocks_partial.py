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
from pathlib import Path

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


class TotalAppsColumn(unittest.TestCase):
    """Pedido de Rafael (2026-08-26): la columna Total Apps en los boards
    DIARIOS de knocks — la misma cuenta de apps que ya lleva el board semanal
    (PRODUCT SALES SUMMARY, todos los productos), pero del dia."""

    def _rows(self):
        from automations.total_knocks import pull as K
        def rec(rep, knocks, talk):
            r = {c: "" for c in K.SHEET_COLUMNS}
            r.update({K.COL_REP: rep, K.COL_TOTAL_KNOCKS: knocks,
                      K.COL_TOTAL_TALK_TO: talk,
                      K.COL_FIRST_KNOCK: "10:00 AM",
                      K.COL_LAST_KNOCK: "7:00 PM"})
            return r
        return [rec("Alan Diaz", 38, 9), rec("bree kim", 51, 14)]

    def test_a_rep_who_sold_without_knocking_still_appears(self):
        """Si no, la columna no suma al total de la oficina y el numero deja
        de ser creible — misma regla que el board semanal."""
        rows, apps, total = KD.daily_apps_for_board(
            self._rows(), {"Alan Diaz": 3, "BREE KIM": 5, "Zed Moore": 2})
        self.assertEqual(total, 10)
        self.assertEqual(len(rows), 3)
        self.assertEqual(apps["Zed Moore"], 2)
        self.assertEqual(apps["bree kim"], 5)      # match por nombre normalizado

    def test_no_crosstab_means_no_column_not_a_zero(self):
        rows, apps, total = KD.daily_apps_for_board(self._rows(), None)
        self.assertEqual(len(rows), 2)
        self.assertIsNone(apps)
        self.assertIsNone(total)

    def test_the_sales_only_rep_does_not_dilute_talk_tos_per_rep(self):
        """El board de la oficina y el resumen violeta dividen por los que
        golpearon; una fila que solo vendio no es alguien que trabajo la
        puerta, y los dos numeros tienen que coincidir."""
        from automations.total_knocks import render as R
        rows, apps, _t = KD.daily_apps_for_board(
            self._rows(), {"Alan Diaz": 3, "Zed Moore": 2})
        header, table = R._table_from_rows(rows)
        sub = R._combined_sub(header, table)
        totals = R._combined_totals("TOTAL", sub)
        per_rep = totals[R.COMBINED_KNOCKS_HEADERS.index(
            R.COL_TALK_TO_PER_REP)]
        self.assertEqual(per_rep, "11.5")          # 23 / 2, no 23 / 3
        summary = KD.daily_summary_row("ICD", self._rows(), 5)
        self.assertEqual(summary[KD.DAILY_SUMMARY_HEADERS.index(
            "Talk To's per Rep")], "11.5")
        self.assertEqual(summary[KD.DAILY_SUMMARY_HEADERS.index(
            "Total Apps")], "5")

    def test_the_column_is_off_unless_the_caller_asks(self):
        """El mismo renderer dibuja los hilos de metricas, los slots
        intraday y /knocks: ninguno pidio la columna."""
        import inspect
        from automations.total_knocks import render as R
        self.assertIsNone(
            inspect.signature(R.render_total_knocks).parameters["apps"].default)
        self.assertNotIn(R.COL_TOTAL_APPS, R.COMBINED_KNOCKS_HEADERS)

    def test_totals_row_sums_the_icd_rows_above_it(self):
        table, _bgs = KD.daily_summary_table(
            [("A", {"name": "A"}, self._rows(), 4),
             ("B", {"name": "B"}, self._rows(), 6)], chan_rows=None)
        at = KD.DAILY_SUMMARY_HEADERS.index("Total Apps")
        self.assertEqual([r[at] for r in table], ["4", "6", "10"])

    def test_an_icd_with_no_apps_pulled_is_blank_never_zero(self):
        table, _bgs = KD.daily_summary_table(
            [("A", {"name": "A"}, self._rows(), None)], chan_rows=None)
        at = KD.DAILY_SUMMARY_HEADERS.index("Total Apps")
        self.assertEqual([r[at] for r in table], ["", ""])

    def test_an_old_capture_reused_from_disk_keeps_working(self):
        """Un sidecar escrito antes de esta columna es una LISTA de filas."""
        table, _bgs = KD.daily_summary_table(
            [("A", {"name": "A"}, self._rows())], chan_rows=None)
        self.assertEqual(table[0][KD.DAILY_SUMMARY_HEADERS.index("Total Apps")],
                         "")

    def test_average_app_per_rep_divides_by_the_reps_who_knocked(self):
        """Pedido de Eve (2026-08-27). Mismo divisor que Talk To's per Rep:
        los reps que trabajaron ese dia, no el roster entero."""
        summary = KD.daily_summary_row("ICD", self._rows(), 5)
        self.assertEqual(summary[KD.DAILY_SUMMARY_HEADERS.index(
            "Average App per Rep")], "2.5")        # 5 / 2 reps

    def test_average_app_per_rep_is_blank_when_total_apps_is(self):
        """Un ICD sin crosstab no puede mostrar un promedio de 0: leeria como
        una oficina que no vendio."""
        at = KD.DAILY_SUMMARY_HEADERS.index("Average App per Rep")
        self.assertEqual(KD.daily_summary_row("ICD", self._rows(), None)[at],
                         "")
        self.assertEqual(KD.daily_summary_row("ICD", [], 4)[at], "")

    def test_average_app_per_rep_on_totals_divides_by_every_rep(self):
        """La fila TOTALS promedia sobre los reps de TODA la capitania, no el
        promedio de los promedios."""
        table, _bgs = KD.daily_summary_table(
            [("A", {"name": "A"}, self._rows(), 4),
             ("B", {"name": "B"}, self._rows(), 6)], chan_rows=None)
        at = KD.DAILY_SUMMARY_HEADERS.index("Average App per Rep")
        self.assertEqual([r[at] for r in table], ["2.0", "3.0", "2.5"])

    def _drawn(self, monkey, **kw):
        """Renderiza el board por-owner capturando lo que llega a _draw, sin
        escribir un PNG: devuelve (headers, filas)."""
        from automations.total_knocks import render as R
        seen = {}
        def fake_draw(cols, table, title, theme, out, **k):
            seen["cols"], seen["table"] = list(cols), [list(r) for r in table]
            return out
        monkey(R, "_draw", fake_draw)
        R.render_total_knocks(dt.date(2026, 8, 27), rows=kw.pop("rows"),
                              out_dir=Path("."), **kw)
        return seen["cols"], seen["table"]

    def test_average_app_per_rep_rides_the_per_owner_daily_board(self):
        """Pedido de Eve (2026-08-28): la columna que el board resumen ya
        tenia le faltaba al board DIARIO de cada persona."""
        from automations.total_knocks import render as R
        old = R._draw
        try:
            rows, apps, _t = KD.daily_apps_for_board(
                self._rows(), {"Alan Diaz": 3, "bree kim": 5})
            cols, table = self._drawn(setattr, rows=rows, apps=apps)
            at = cols.index(R.COL_AVG_APP_PER_REP)
            self.assertEqual(cols[at - 1], R.COL_TOTAL_APPS)
            # fila 0 = TOTAL de la oficina (8 apps / 2 reps), luego los reps.
            self.assertEqual(table[0][at], "4.0")
            self.assertEqual([r[at] for r in table[1:]], ["", ""])
        finally:
            R._draw = old

    def test_average_app_per_rep_never_reaches_a_board_without_apps(self):
        """Los hilos de metricas, los slots intraday y /knocks no la pidieron:
        sin `apps` no aparece ninguna de las dos columnas."""
        from automations.total_knocks import render as R
        old = R._draw
        try:
            cols, _t = self._drawn(setattr, rows=self._rows())
            self.assertNotIn(R.COL_AVG_APP_PER_REP, cols)
            self.assertNotIn(R.COL_TOTAL_APPS, cols)
            self.assertNotIn(R.COL_AVG_APP_PER_REP, R.COMBINED_KNOCKS_HEADERS)
        finally:
            R._draw = old

    def test_the_comparison_office_divides_by_its_own_reps(self):
        """La fila teal de Chan promedia sobre SUS reps, no sobre los nuestros
        — y queda en blanco si sus apps no bajaron, nunca en 0."""
        from automations.total_knocks import render as R
        old = R._draw
        try:
            rows, apps, _t = KD.daily_apps_for_board(
                self._rows(), {"Alan Diaz": 3, "bree kim": 5})
            chan = self._rows()[:1]                    # un solo rep
            cols, table = self._drawn(
                setattr, rows=rows, apps=apps,
                extra_totals=[("Chan Park", chan, {"Alan Diaz": 7})])
            at = cols.index(R.COL_AVG_APP_PER_REP)
            self.assertEqual(table[0][at], "7.0")      # 7 / 1 rep de Chan
            cols, table = self._drawn(
                setattr, rows=rows, apps=apps,
                extra_totals=[("Chan Park", chan)])    # sin sus apps
            self.assertEqual(table[0][cols.index(R.COL_AVG_APP_PER_REP)], "")
        finally:
            R._draw = old

    def test_the_daily_pull_reads_one_weekday_of_the_weekly_crosstab(self):
        from automations.weekly_knock_dispositions import apps as A
        self.assertEqual(A.day_name(dt.date(2026, 8, 25)), "Tuesday")
        # el dia del board siempre cae en la semana que el build ya baja
        for d in range(1, 15):
            today = dt.date(2026, 8, 12) + dt.timedelta(days=d)
            _mon, _sat, we_sunday = KD.week_window(today)
            from automations.shared.report_week import week_ending
            self.assertEqual(week_ending(KD.daily_target(today)), we_sunday)


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
