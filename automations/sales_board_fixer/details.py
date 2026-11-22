"""The rep's detail columns on the right of the board: none of them blank.

Eve 2026-11-22: *"agregá chequeo en lucy fixer que siempre todos los campos de
las columnas a la derecha estén completos"*. Until now the fixer audited only
Campaign (checks.check_campaign). This adds, on Raf's own board:

  Trainer            blank -> last week's Trainer on the same rep; else the
                     New Starts box (full name, same lookup as first_weeks).
                     Only flagged for a rep who HAD one (last week or box) or
                     is in their 1st-4th week ("5th wk+" = veteran): leaders have no trainer
                     (Basil Elhassan), and a blank there is not an error.
  Team               blank -> last week's Team; else their trainer's team.
  Field Status       blank -> listed for a person (week_roll advances it on
  Leadership Status         Mondays; a blank one is a hand mistake, and which
                            week they are in is not something to guess).

Only EMPTY cells are ever written. Columns are found by their ROW-1 label.
Drug Test / Direct Deposit / A-Play / Email / Location are NOT here: Location
and Email come from Blue Ink (city_check), the rest has no source yet (Eve has
the list, 11/22).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from automations.alphalete_sales_board import config as SBC
from automations.rep_sales_fill import board as B
from automations.sales_board_fixer import checks as K

KIND = "detail_blank"
K.KIND_LABEL.setdefault(KIND, "columna de datos del rep vacía (Trainer / Team / "
                              "Field Status / Leadership)")
K.NOTE_LABEL.setdefault(KIND, "this was blank")

FILL = ("Trainer", "Team")
REPORT = ("Field Status", "Leadership Status")
_NEW = re.compile(r"^\s*[1-4](st|nd|rd|th)\s*wk", re.I)   # '5th wk+' = veteran, no trainer owed


def _cols(values) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for c, x in enumerate(values[0] if values else [], 1):
        label = " ".join(str(x).split())
        if label in FILL + REPORT and label not in out:
            out[label] = c
    return out


def _by_name(values) -> Dict[str, int]:
    if not values or not K.is_board(values):
        return {}
    first, last = K.block_rows(values)
    out = {}
    for r in range(first, last + 1):
        n = B._norm_name(K.name_at(values, r))
        if n:
            out.setdefault(n, r)
    return out


def _box_trainer(values, tab: str, name: str) -> str:
    """Full trainer name for `name` from this tab's New Starts box, or ''."""
    try:
        from automations.apex_new_starts import board as AB
        from automations.alphalete_sales_board import first_weeks as FW
        want = B._norm_name(name)
        for p in AB.read_box(values, tab):
            if want in FW._variants(p.name):
                full, _team, _camp, _note = FW.trainer_details(
                    values, p.trainer, FW._label_cols(values))
                return full
    except Exception:  # noqa: BLE001 -- no box / odd layout = no box answer
        return ""
    return ""


def check(tab: str, values, last_week: Optional[list]) -> List[K.Finding]:
    """last_week: last week's tab values (or None)."""
    if not values or not K.is_board(values):
        return []
    cols = _cols(values)
    if not cols:
        return []
    old = last_week or []
    ocols = _cols(old) if old else {}
    orow = _by_name(old)
    skip = {B._norm_name(n) for n in SBC.EXCLUDE_REPS}
    first, last = K.block_rows(values)
    out: List[K.Finding] = []
    for r in range(first, last + 1):
        name = K.name_at(values, r)
        key = B._norm_name(name)
        if not key or K._SPARE_NAME.match(name.strip()) or key in skip:
            continue
        o = orow.get(key)

        def prev(label):
            if o and label in ocols:
                return K._g(old, o, ocols[label]).strip()
            return ""

        status = K._g(values, r, cols["Field Status"]).strip() if "Field Status" in cols else ""
        got: Dict[str, str] = {}
        if "Trainer" in cols and not K._g(values, r, cols["Trainer"]).strip():
            want = prev("Trainer") or _box_trainer(values, tab, name)
            if want:
                got["Trainer"] = want
            elif _NEW.match(status):
                out.append(K.Finding(KIND, tab, K.a1(r, cols["Trainer"]),
                                     "Trainer vacío y no está en la semana pasada "
                                     "ni en el cuadro New Starts", row=r, name=name,
                                     before="vacía"))
        if "Team" in cols and not K._g(values, r, cols["Team"]).strip():
            want = prev("Team")
            trainer = got.get("Trainer") or (
                K._g(values, r, cols["Trainer"]).strip() if "Trainer" in cols else "")
            if not want and trainer:
                tr = _by_name(values).get(B._norm_name(trainer))
                if tr:
                    want = K._g(values, tr, cols["Team"]).strip()
            if want:
                got["Team"] = want
            else:
                out.append(K.Finding(KIND, tab, K.a1(r, cols["Team"]),
                                     "Team vacío: ni la semana pasada ni el trainer lo dicen",
                                     row=r, name=name, before="vacía"))
        for label, v in got.items():
            out.append(K.Finding(KIND, tab, K.a1(r, cols[label]),
                                 "%s vacío: puesto %s" % (label, "de la semana pasada"
                                                          if prev(label) == v else
                                                          "del cuadro New Starts / trainer"),
                                 row=r, name=name, before="vacía", after=v, value=v))
        for label in REPORT:
            if label in cols and not K._g(values, r, cols[label]).strip():
                out.append(K.Finding(KIND, tab, K.a1(r, cols[label]),
                                     "%s vacío (semana pasada: %s)" % (label, prev(label) or "-"),
                                     row=r, name=name, before="vacía"))
    return out
