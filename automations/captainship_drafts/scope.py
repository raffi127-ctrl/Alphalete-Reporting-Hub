"""A quien le duele la falla de hoy: acotar el freno a los capitanes tocados.

REGLA DE EVE (2026-08-22), para el envio diario Y el de fin de semana:

    «si fallan todos, espera para un nuevo link de revision; si falla uno,
    mientras reviso el link te aviso para que corrijas y mientras los que estan
    ok se envien, porque se retrasa todo sin sentido»

El gate era todo-o-nada: un modulo de metricas INCOMPLETE frenaba los TRECE
reportes. El sabado 2026-08-22 `owners_metrics_churn` dejo caer UNA seccion
(«Tony Chavez (ATT Fiber)» — dos reps sin llenar) y con eso se quedaron sin
correo los otros doce capitanes, que no tenian nada malo. Este modulo contesta
la pregunta que faltaba: **de los que frenan el dia, ¿a que capitanes tocan?**

CONTRATO (`held_captains`) — tres respuestas, y las tres importan:

  * `(None, motivo)`  → NO se puede acotar. Frenar todo, como antes. Es la
    respuesta conservadora y es la que sale ante cualquier duda: un id que no
    dejo manifest, un manifest sin `failed`, una seccion que no mapea a un
    capitan (o que mapea a dos).
  * `(set(), motivo)` → nadie tocado: los ids que frenaban ya se recuperaron
    (su manifest de HOY dice `ok`). Sale todo.
  * `({claves}, motivo)` → sale el resto y esos esperan el arreglo.

POR QUE EL MANIFEST Y NO EL day_state. `output/day_state/<fecha>.json` es el
registro de la corrida PROGRAMADA de las 4am y un `lucy rerun` exitoso NO lo
toca ([[project_daystate-does-not-clear-on-manual-rerun]]): si mirara solo eso,
el capitan tocado quedaria retenido para siempre aunque el rerun ya hubiera
llenado su tab. El manifest (`output/manifests/<id>.json`) SI lo reescribe cada
corrida, asi que es lo unico que sabe como esta el reporte AHORA. Se exige que
sea de HOY — uno de ayer no habla de esta corrida.

EL MAPEO ES POR NOMBRE, no por una tabla que haya que mantener. Las secciones
que los modulos por-capitan registran en `failed` llevan el nombre del capitan
(«Tony Chavez (ATT Fiber)», «Wireless Churn - Sahil Multani (ATT Fiber)»), y los
trece `display_name` de config.py son distintos entre si, asi que alcanza. Un
capitan nuevo entra solo. Si una seccion no matchea a exactamente UNO, no se
adivina: se frena todo.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from automations.captainship_drafts import config
from automations.shared import run_manifest


def _names(display_name: str, section: str) -> bool:
    """¿`section` nombra a ESTE capitan?

    El nombre tiene que empezar palabra («Chandler Reyes» NO es Chan: sin esto
    retendriamos a un capitan por el nombre de otra persona) y puede llevar el
    posesivo pegado, con apostrofe o sin el — asi se llaman las vistas de
    Tableau («TonysCaptainshipCancel») y varias secciones. Lo unico que descarta
    un match es que despues siga MINUSCULA: eso es otra palabra mas larga.
    """
    low, name = (section or "").lower(), display_name.lower()
    for m in re.finditer(re.escape(name), low):
        start, end = m.span()
        if start and low[start - 1].isalpha():
            continue
        rest = (section or "")[end:]
        if rest[:2].lower() == "'s":
            rest = rest[2:]
        elif rest[:1].lower() == "s":
            rest = rest[1:]
        if rest[:1].isalpha() and rest[:1].islower():
            continue
        return True
    return False


def captain_of(section: str) -> Optional[str]:
    """La clave del capitan nombrado en `section`, o None si no es exactamente
    uno (ninguno, o dos — las dos cosas son 'no se': el que llama frena todo)."""
    hits = [c.key for c in config.CAPTAINS if _names(c.display_name, section)]
    return hits[0] if len(hits) == 1 else None


def _manifest_id(rid: str) -> str:
    """El id bajo el que ESTE reporte escribe su manifest.

    Casi nunca es el id del schedule: `owners_metrics_churn` escribe
    `owners-metrics-churn`, `captainship_churn` escribe
    `captainship-new-internet-wireless-churn` — hoy los 23 reportes con verify
    de manifest usan otro nombre. El orquestador ya conoce ese mapeo
    (`verify.report_id` en schedule_config.json), asi que se lee de ahi y no de
    una tabla nueva que haya que mantener. Sin esto, el mismo sabado que motivo
    este modulo el manifest de la falla EXISTIA pero con otro nombre,
    `held_captains` contestaba «no dejo manifest» y el freno volvia a ser
    todo-o-nada.
    """
    try:
        from automations.day_orchestrator import registry as reg
        entry = reg.load_config().raw.get("reports", {}).get(rid) or {}
        v = entry.get("verify") or {}
        if v.get("type") == "manifest" and v.get("report_id"):
            return str(v["report_id"])
    except Exception:  # noqa: BLE001 — sin config, el id del schedule tal cual
        pass
    return rid


def _manifest_of_today(report_id: str, today: dt.date) -> Optional[dict]:
    """El manifest de `report_id` SOLO si lo escribio una corrida de hoy."""
    m = run_manifest.read_manifest(_manifest_id(report_id))
    if not m:
        return None
    if (m.get("run_ts") or "")[:10] != today.isoformat():
        return None
    return m


def held_captains(blocking_ids: Sequence[str],
                  today: Optional[dt.date] = None
                  ) -> Tuple[Optional[Set[str]], str]:
    """(capitanes a retener | None, motivo). Ver el contrato arriba."""
    today = today or dt.date.today()
    if not blocking_ids:
        return set(), "no hay nada frenando el dia"

    held: Set[str] = set()
    recovered: List[str] = []
    for rid in blocking_ids:
        m = _manifest_of_today(rid, today)
        if m is None:
            return None, (f"{rid} no dejo manifest de hoy: no puedo saber a que "
                          f"capitan afecta, asi que frena a todos")
        if m.get("ok"):
            # Se cayo en la corrida de las 4am y un rerun lo arreglo. El
            # day_state sigue diciendo INCOMPLETE y no va a cambiar solo.
            recovered.append(rid)
            continue
        parts = [str(p) for p in (m.get("failed") or []) if str(p).strip()]
        if not parts:
            return None, (f"{rid} fallo sin decir que parte "
                          f"(manifest sin `failed`): frena a todos")
        for part in parts:
            key = captain_of(part)
            if key is None:
                return None, (f"{rid}: la parte caida «{part}» no cae en un "
                              f"capitan solo, asi que frena a todos")
            held.add(key)

    if not held:
        return set(), ("los ids que frenaban ya se recuperaron: "
                       + ", ".join(sorted(recovered)))
    if len(held) >= len(config.CAPTAINS):
        return None, (f"la falla toca a los {len(held)} capitanes: no es un "
                      f"caso parcial, frena todo")
    why = "falla acotada a " + ", ".join(sorted(held))
    if recovered:
        why += " (ya recuperados: " + ", ".join(sorted(recovered)) + ")"
    return held, why


def other_keys(held: Iterable[str]) -> List[str]:
    """Las claves que SI salen, en el orden de config (el de siempre)."""
    held = set(held or ())
    return [c.key for c in config.CAPTAINS if c.key not in held]
