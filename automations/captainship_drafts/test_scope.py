"""Pins la regla de Eve del 2026-08-22 sobre los envios parciales.

Verbatim: "si fallan todos, espera para un nuevo link de revision; si falla uno,
mientras reviso link te aviso para que corrijas y mientras los que estan ok se
envien, porque se retrasa todo sin sentido".

Lo que tiene que quedar clavado:

  1. una falla acotada a UN capitan retiene a ese y a nadie mas
  2. una falla que no se puede atribuir (sin manifest, sin `failed`, o una
     seccion que no nombra a un capitan) frena a los trece — la duda va del
     lado seguro
  3. una falla que toca a TODOS frena a los trece: eso es "esperar un link nuevo"
  4. un id que ya se recupero (su manifest de HOY dice ok) no retiene a nadie,
     aunque el day_state siga diciendo INCOMPLETE — `lucy rerun` no lo limpia
  5. el candado del hilo es POR CAPITAN, para que la segunda tanda no le mande
     una copia a quien ya la recibio

Run:  python -m automations.captainship_drafts.test_scope
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.captainship_drafts import config, scope
from automations.captainship_drafts import review_gate as rg
from automations.shared import run_manifest

TODAY = dt.date(2026, 8, 22)        # el sabado del caso real
ALL = {c.key for c in config.CAPTAINS}


def manifest(*, ok: bool, failed=(), day: dt.date = TODAY) -> dict:
    return {"ok": ok, "failed": list(failed),
            "run_ts": f"{day.isoformat()}T07:14:00"}


class Base(unittest.TestCase):
    def setUp(self):
        self._read = run_manifest.read_manifest
        self.manifests: dict = {}
        run_manifest.read_manifest = lambda rid: self.manifests.get(rid)

    def tearDown(self):
        run_manifest.read_manifest = self._read


class MapsSectionToCaptain(Base):
    def test_the_real_saturday_section(self):
        self.assertEqual(scope.captain_of("Tony Chavez (ATT Fiber)"), "tony")

    def test_the_wireless_tab_name(self):
        self.assertEqual(
            scope.captain_of("Wireless Churn - Sahil Multani (ATT Fiber)"),
            "sahil")

    def test_a_tableau_view_with_the_possessive(self):
        self.assertEqual(scope.captain_of("TonysCaptainshipCancel"), "tony")

    def test_a_longer_name_is_not_a_captain(self):
        # "Chandler" no es Chan. Sin el limite de palabra, retendriamos a un
        # capitan por el nombre de otra persona.
        self.assertIsNone(scope.captain_of("Chandler Reyes"))

    def test_a_section_naming_nobody(self):
        self.assertIsNone(scope.captain_of("ATT Fiber (org)"))


class HeldCaptains(Base):
    # OJO CON LAS CLAVES de self.manifests: van bajo el id del MANIFEST
    # (verify.report_id, con guiones), no el del schedule. Los modulos escriben
    # con otro nombre — `owners_metrics_churn` escribe `owners-metrics-churn` —
    # y la version original de estos tests los mockeaba bajo el id del
    # schedule, con lo cual pasaban mientras produccion no encontraba NINGUN
    # manifest y frenaba todo (el sabado 2026-08-22, otra vez).
    def test_one_captain_holds_only_that_captain(self):
        self.manifests["owners-metrics-churn"] = manifest(
            ok=False, failed=["Tony Chavez (ATT Fiber)"])
        held, why = scope.held_captains(["owners_metrics_churn"], TODAY)
        self.assertEqual(held, {"tony"})
        self.assertIn("tony", why)
        self.assertEqual(len(scope.other_keys(held)), len(ALL) - 1)
        self.assertNotIn("tony", scope.other_keys(held))

    def test_two_modules_two_captains(self):
        self.manifests["owners-metrics-churn"] = manifest(
            ok=False, failed=["Tony Chavez (ATT Fiber)"])
        self.manifests["captainship-cancel-rate"] = manifest(
            ok=False, failed=["Cancel Rate - Starr Rodenhurst (ATT Fiber)"])
        held, _ = scope.held_captains(
            ["owners_metrics_churn", "captainship_cancel_rate"], TODAY)
        self.assertEqual(held, {"tony", "starr"})

    def test_schedule_id_reads_the_modules_own_manifest_name(self):
        # El caso real completo: el gate frena por el id del SCHEDULE y el
        # modulo escribio su manifest bajo verify.report_id. Un manifest bajo
        # el id del schedule NO debe encontrarse (ese archivo no existe en
        # produccion).
        self.assertEqual(scope._manifest_id("owners_metrics_churn"),
                         "owners-metrics-churn")
        self.assertEqual(scope._manifest_id("captainship_churn"),
                         "captainship-new-internet-wireless-churn")
        self.assertEqual(scope._manifest_id("un-id-que-no-existe"),
                         "un-id-que-no-existe")
        self.manifests["owners_metrics_churn"] = manifest(
            ok=False, failed=["Tony Chavez (ATT Fiber)"])
        held, why = scope.held_captains(["owners_metrics_churn"], TODAY)
        self.assertIsNone(held)
        self.assertIn("manifest", why)

    def test_no_manifest_holds_everything(self):
        held, why = scope.held_captains(["captainship_activations"], TODAY)
        self.assertIsNone(held)
        self.assertIn("manifest", why)

    def test_yesterdays_manifest_does_not_count(self):
        self.manifests["owners_metrics_churn"] = manifest(
            ok=False, failed=["Tony Chavez (ATT Fiber)"],
            day=TODAY - dt.timedelta(days=1))
        held, _ = scope.held_captains(["owners_metrics_churn"], TODAY)
        self.assertIsNone(held)

    def test_failure_without_parts_holds_everything(self):
        self.manifests["captainship_drafts"] = manifest(ok=False, failed=[])
        held, why = scope.held_captains(["captainship_drafts"], TODAY)
        self.assertIsNone(held)
        self.assertIn("que parte", why)

    def test_unmappable_part_holds_everything(self):
        self.manifests["org-sales-board"] = manifest(
            ok=False, failed=["Retail JE"])
        held, _ = scope.held_captains(["org_sales_board"], TODAY)
        self.assertIsNone(held)

    def test_everybody_broken_waits_for_a_new_link(self):
        self.manifests["captainship-activations"] = manifest(
            ok=False, failed=[c.display_name for c in config.CAPTAINS])
        held, why = scope.held_captains(["captainship_activations"], TODAY)
        self.assertIsNone(held)
        self.assertIn("no es un caso parcial", why)

    def test_a_rerun_that_fixed_it_holds_nobody(self):
        # El day_state seguira diciendo INCOMPLETE toda la vida; el manifest es
        # el unico que sabe como esta el reporte AHORA.
        self.manifests["owners-metrics-churn"] = manifest(ok=True)
        held, why = scope.held_captains(["owners_metrics_churn"], TODAY)
        self.assertEqual(held, set())
        self.assertIn("recuperaron", why)

    def test_nothing_blocking(self):
        held, _ = scope.held_captains([], TODAY)
        self.assertEqual(held, set())


class ThreadLockIsPerCaptain(unittest.TestCase):
    def test_partial_marker_lists_who_went(self):
        keys = rg._keys_in_marker(
            f"`{rg.PARTIAL_SENT_MARKER} rafael,wayne,starr`")
        self.assertEqual(keys, {"rafael", "wayne", "starr"})

    def test_a_line_without_the_marker_says_nothing(self):
        self.assertEqual(rg._keys_in_marker("✅ Sent — on their way"), set())

    def test_full_marker_closes_the_day(self):
        msg = {"ts": "1.0"}
        replies = [{"text": "post"},
                   {"text": f"✅ Sent\n`{rg.SENT_MARKER}`"}]
        rg._client = lambda: _FakeSlack(replies)
        self.assertEqual(rg.sent_keys(msg), ALL)

    def test_two_tranches_add_up_and_nobody_repeats(self):
        msg = {"ts": "1.0"}
        going = sorted(ALL - {"tony"})
        replies = [{"text": "post"},
                   {"text": f"Sent 12 of 13\n`{rg.PARTIAL_SENT_MARKER} "
                            f"{','.join(going)}`"}]
        rg._client = lambda: _FakeSlack(replies)
        done = rg.sent_keys(msg)
        self.assertEqual(done, set(going))
        # La segunda tanda: solo el que faltaba.
        self.assertEqual([k for k in scope.other_keys(set()) if k not in done],
                         ["tony"])


class _FakeSlack:
    def __init__(self, replies):
        self._replies = replies

    def conversations_replies(self, **_kw):
        return {"messages": self._replies}


if __name__ == "__main__":
    unittest.main(verbosity=2)
