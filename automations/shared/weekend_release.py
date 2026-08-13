"""Sábado y domingo los gates de revisión se abren SOLOS — si el día está limpio.

Eve 2026-08-12: "sábados y domingos los reportes, armado de drafts y envíos
corran sin el gate de revisión, ya que no hay nada que los revise… a no ser que
algo lance una alerta o quede incompleto o falle".

El gate normal es: Lucy postea el link del borrador en #revision-emails y el ✅
de Evelyn es lo que dispara el envío. Los fines de semana no hay nadie
mirando el canal, así que el ✅ nunca llega y el correo simplemente no sale —
un reporte que se armó bien y se murió esperando a alguien. Este módulo es la
excepción: **el sábado y el domingo, un día limpio se aprueba solo.**

QUÉ CUENTA COMO "LIMPIO" — y por qué se lee del estado del día y no del gate.

El único lugar que sabe si el reporte de hoy salió bien es el estado del
orquestador (`output/day_state/<fecha>.json`), el mismo que alimenta las alertas
de falla. Un día limpio, para un correo dado, es:

  • el propio job del borrador y TODA su cadena de dependencias en `DONE`
    (transitiva: el correo de captainship depende de los drafts, que dependen de
    sus 8 módulos de métricas — si uno quedó a medias, el borrador salió con un
    hueco y nadie lo miró);
  • ninguno de esos ids en `failure_alerts_sent`, la lista de los que ya
    dispararon una alerta hoy;
  • y el archivo del día TIENE que existir y nombrarlos. Si no puedo probar que
    el día está limpio, no está limpio.

Esa última regla es el corazón del módulo: **falla cerrado**. Un readiness hold
no deja rastro ([[project_readiness-hold-leaves-no-trace]]) y un reporte que
nunca corrió no falla — los dos se leen igual que un día bueno si uno se fija
sólo en "¿hubo error?". Preguntando al revés ("¿está TODO en DONE?") los dos
casos caen del lado seguro: no se auto-envía, y el gate sigue esperando un ✅
como cualquier otro día.

Lo que NO bloquea: una falla en un reporte de otra rama (mobrium, un breakdown).
Si bloqueara cualquier falla del día, un solo módulo flojo dejaría sin correo
todos los fines de semana, que es justo lo que esto viene a arreglar.

EL SILENCIO TAMBIÉN AVISA. Cuando el día NO está limpio el gate no se queda
callado: deja UNA nota en el hilo diciendo qué lo frenó y etiqueta a los
aprobadores. Un sábado sin correo y sin mensaje se lee igual que un sábado que
salió bien, y eso se descubre el lunes.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Iterable, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")   # [[project_central-time-for-texas-reports]]
WEEKEND = {5, 6}                        # sábado, domingo (Python weekday())

# Perilla de apagado, para volver al gate manual los 7 días sin tocar los gates.
ENABLED = True

# Quién figura como "aprobador" cuando el día se libera solo. Va al mismo lugar
# donde iría el nombre de Evelyn, así el hilo dice quién lo soltó.
AUTO_ID = "auto-weekend"
AUTO_WHO = "envío automático de fin de semana (nadie revisa sáb/dom)"

# Marcador de la nota que se deja cuando el fin de semana NO se auto-envía.
# Igual que SENT_MARK / CLOSED_MARK: es lo que hace que se diga UNA sola vez,
# aunque el watcher pase cada 15 minutos.
HELD_MARK = "Weekend auto-send held"

DONE = "DONE"


def is_weekend(today: Optional[dt.date] = None) -> bool:
    today = today or dt.datetime.now(CENTRAL).date()
    return today.weekday() in WEEKEND


def _state(today: dt.date) -> Optional[dict]:
    """El estado del día, leído crudo. NUNCA `load_or_create`: eso escribiría un
    archivo de estado desde el watcher, que no es quien lleva ese registro."""
    from automations.day_orchestrator import state as st
    path = st.STATE_DIR / f"{today.isoformat()}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def dependency_closure(report_ids: Sequence[str]) -> List[str]:
    """Los ids dados MÁS todo lo que dependen, transitivamente.

    Se resuelve contra `schedule_config.json` en cada corrida, no con una lista
    acá: si mañana el correo del board depende de un módulo nuevo, esa
    dependencia entra sola en el chequeo. Lee `raw`, no `cfg.reports`, para que
    una dependencia fuera del scheduler igual aporte SUS dependencias."""
    from automations.day_orchestrator import registry as reg
    try:
        reports = reg.load_config().raw.get("reports", {})
    except Exception:  # noqa: BLE001 — sin config no hay cierre que hacer
        return list(report_ids)
    def resolve(rid: str) -> str:
        """Los gates conocen su reporte por el id de la TARJETA del Hub
        (`country-sales-board-email`) y el orquestador por el del schedule
        (`country_sales_board_email`). Son el mismo trabajo con distinto guión;
        sin esto la cadena quedaba vacía y ningún fin de semana se auto-enviaba."""
        if rid in reports:
            return rid
        twin = rid.replace("-", "_")
        return twin if twin in reports else rid

    seen: Set[str] = set()
    out: List[str] = []
    stack = [resolve(r) for r in report_ids]
    while stack:
        rid = resolve(stack.pop())
        if rid in seen:
            continue
        seen.add(rid)
        out.append(rid)
        entry = reports.get(rid) or {}
        stack.extend(entry.get("depends_on") or [])
        stack.extend(entry.get("after") or [])
    return out


def _scheduled_today(today: dt.date) -> Set[str]:
    """Ids que el orquestador TIENE que correr hoy, por cadencia."""
    from automations.day_orchestrator import registry as reg
    try:
        cfg = reg.load_config()
        return {r.report_id for r in reg.scheduled_today(cfg, today)}
    except Exception:  # noqa: BLE001
        return set()


def day_is_clean(report_ids: Sequence[str],
                 today: Optional[dt.date] = None) -> Tuple[bool, str]:
    """¿Puede este correo salir sin que nadie lo mire? (ok, motivo)."""
    today = today or dt.datetime.now(CENTRAL).date()
    ds = _state(today)
    if ds is None:
        return False, (f"no hay estado del día para {today.isoformat()} "
                       f"(output/day_state/) — no puedo probar que el día esté "
                       f"limpio, así que no se auto-envía")
    reports = ds.get("reports") or {}
    chain = dependency_closure(report_ids)

    # Una dependencia que HOY no corre no puede ensuciar el día. El correo del
    # Org board depende de all_campaigns_board, que no corre todos los días: sin
    # esto, su SKIPPED (o su ausencia del estado) bloquearía el auto-envío todos
    # los domingos, para siempre. Se exige registro sólo de lo que hoy tocaba.
    due = _scheduled_today(today)
    missing = sorted(r for r in chain if r not in reports and r in due)
    if missing:
        return False, (f"hoy tocaba {', '.join(missing)} y el estado del día no "
                       f"lo registra — sin rastro no hay limpieza que probar")
    checked = [r for r in chain if r in reports
               and reports[r].get("status") != "SKIPPED"]
    if not checked:
        return False, ("ninguno de los jobs de este reporte figura corrido hoy — "
                       "no se auto-envía")
    not_done = sorted(f"{r} ({reports[r].get('status')})"
                      for r in checked if reports[r].get("status") != DONE)
    if not_done:
        return False, f"no está todo en DONE: {', '.join(not_done)}"
    chain = checked
    alerted = sorted(set(chain) & set(ds.get("failure_alerts_sent") or []))
    if alerted:
        return False, (f"hoy ya salió una alerta de falla por "
                       f"{', '.join(alerted)}")
    return True, (f"día limpio: {len(chain)} job(s) en DONE, sin alertas "
                  f"({', '.join(sorted(chain))})")


def auto_release(report_ids: Sequence[str], today: Optional[dt.date] = None,
                 *, enabled: bool = True) -> Tuple[bool, str]:
    """¿Se libera solo? (ok, motivo). El motivo se imprime SIEMPRE — un día que
    no se auto-envía tiene que decir por qué, en el log y en el hilo."""
    today = today or dt.datetime.now(CENTRAL).date()
    if not (enabled and ENABLED):
        return False, "auto-envío de fin de semana desactivado (--no-auto)"
    if not is_weekend(today):
        return False, (f"{today.isoformat()} es "
                       f"{today.strftime('%A').lower()}: día hábil, el ✅ manda")
    ok, why = day_is_clean(report_ids, today)
    if not ok:
        return False, f"fin de semana, pero {why}"
    return True, f"fin de semana sin revisores y {why}"


def held_note(reason: str, what: str) -> str:
    """El texto de la nota que se deja cuando el fin de semana NO libera."""
    return (f"— {HELD_MARK}: hoy es fin de semana y {what} se habría enviado "
            f"solo, pero {reason}. Queda esperando un ✅ como cualquier otro "
            f"día; si está bien, aprobalo y sale.")
