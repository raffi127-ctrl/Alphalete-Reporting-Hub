"""READ-ONLY: el chequeo hacia atrás de los overrides que llegan TARDE.

    lucy rerun override_period_watch              # marcadores + ledger (LUCY 1)
    python -m automations.override_bulletin.period_watch --no-ledger

WHY THIS EXISTS
---------------
The Special Override and the Credico override are not weekly. Each belongs to a
retail PERIOD and lands on ONE week, weeks after that column was filled — and
sometimes the system posts it late. `backtrack.ledger_reconcile` already retries
every red marker on every Friday pass, so money that shows up gets placed. What
nothing did was look BACKWARD and say *"this one should have arrived by now"*:
a period that never lands just prints one quiet "still pending" line per run,
forever, and the money is missing from the bulletin the whole time (Eve,
2026-09-04: "que revises cada semana si el special override llegó").

Two failures this is meant to catch, both of which already cost real money:
  * P8-2026's special never reached the bot's copy of the tab, so WE 8.30.26
    published Carlos $371.45 and Colten $35,808.24 short.
  * P7-2026's credico has sat PENDING since 8.9.26 — its money IS in the ledger,
    but it reads 25-70x out of scale, so the placement guard holds it. Held
    forever with nobody told is the same as lost.

WHAT IT DOES NOT DO: place anything, or guess which week a period belongs in.
Placement stays marker-driven (markers.py: "a period with no marker is REPORTED,
never placed"). The expected week computed here is used ONLY to say something is
late — never to write it. The two jobs are deliberately separate, because the
cadence is an observation and the marker is the record.

THE CADENCE IS OBSERVED, NOT ASSUMED. Read off the tab's own marker history:

    special  24 markers back to P11-2024 — 22 of 23 gaps are exactly 4 weeks
    credico  19 markers back to P1-2025  — gaps wobble 4-6 weeks

So "late" means late against what this row has actually done, and a row that
changes its rhythm re-teaches it on the next run instead of crying wolf.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import Counter
from pathlib import Path

from automations.override_bulletin import fill as F
from automations.override_bulletin import markers as M
from automations.override_bulletin import pulls as P

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

OUT_DIR = Path("output/override_bulletin/period_watch")

# How many recent gaps to learn the cadence from. Long enough to be stable,
# short enough that a rhythm change is picked up within a couple of periods.
CADENCE_WINDOW = 8

# Grace before a missing period is called LATE. The ledger posts a few days
# after the week it belongs to, so the expected week arriving is not itself a
# problem — one week past it is.
GRACE_WEEKS = 1

_KIND_ES = {M.SPECIAL: "special override", M.CREDICO: "credico"}


def _week_date(label):
    """'8.16.26' -> date(2026, 8, 16)."""
    m, d, y = (int(x) for x in label.split("."))
    return dt.date(2000 + y, m, d)


def _week_label(d):
    """date(2026, 9, 13) -> '9.13.26' (the tab's header form)."""
    return f"{d.month}.{d.day}.{d.year % 100}"


def _next_period(period):
    """'P13-2025' -> 'P1-2026'. The retail year is 13 periods, so 13 wraps."""
    m = M._PERIOD.match(period)
    if not m:
        return None
    n, year = int(m.group(1)), int(m.group(2))
    return f"P1-{year + 1}" if n >= 13 else f"P{n + 1}-{year}"


def history(ws, kind, markers=None):
    """This kind's markers, oldest week first."""
    mks = [m for m in (markers if markers is not None else M.read_markers(ws))
           if m["kind"] == kind]
    return sorted(mks, key=lambda m: _week_date(m["week"]))


def cadence(marks):
    """(weeks, gaps_seen) — how many weeks apart this kind actually lands.

    The MODE of the recent gaps, not the mean: credico runs 4-5-5-4 and a mean of
    4.6 rounds to a week that never happens. `gaps_seen` is reported alongside so
    a wobbly row reads as wobbly instead of as a hard promise."""
    dates = [_week_date(m["week"]) for m in marks]
    gaps = [(b - a).days // 7 for a, b in zip(dates, dates[1:])]
    recent = gaps[-CADENCE_WINDOW:]
    if not recent:
        return None, []
    return Counter(recent).most_common(1)[0][0], sorted(set(recent))


def check(ws, *, ledger_rows=None, today=None, markers=None):
    """{kind: verdict} — what each late-arriving override is doing.

    `ledger_rows=None` runs the marker/cadence half alone (Sheets only, so it
    works off Lucy 1); with the rows it also answers "is the money actually
    there yet", which is what separates 'late because nobody placed it' from
    'late because the source has not posted it'."""
    today = today or dt.date.today()
    all_marks = markers if markers is not None else M.read_markers(ws)
    vals = ws.get_all_values() if ledger_rows else None
    out = {}
    for kind in (M.SPECIAL, M.CREDICO):
        marks = history(ws, kind, markers=all_marks)
        step, gaps = cadence(marks)
        last = marks[-1] if marks else None
        v = {"kind": kind, "markers": len(marks), "cadence": step,
             "gaps_seen": gaps, "last": last, "pending": [], "expected": None,
             "orphans": [], "late": []}

        # 1. every RED marker, oldest first — with how long it has been waiting
        #    and (when we have the ledger) whether its money is even there.
        for mk in marks:
            if not mk["pending"]:
                continue
            waited = (today - _week_date(mk["week"])).days // 7
            row = {"period": mk["period"], "week": mk["week"], "weeks": waited,
                   "in_ledger": None, "share": None}
            if ledger_rows:
                amts = M.amounts_for(
                    ledger_rows, kind, mk["period"],
                    owner_col=P.LEDGER_OWNER_COL, expl_col=P.LEDGER_EXPL_COL,
                    amt_col=P.LEDGER_AMT_COL)
                row["in_ledger"] = round(sum(amts.values()), 2) if amts else None
                # An amount coming back is NOT the same as the money being there.
                # Eve checked NetSuite by hand on 2026-09-04: P7-2026's credico
                # payments have not posted at all, yet this needle reads
                # $519,196.82 for it — 260% of what that week is worth. So the
                # size the placement guard already measures is carried here too,
                # and an out-of-scale read is reported as a BAD READ rather than
                # as money someone forgot to place. Saying "la plata ya está"
                # about that number sends Eve looking for a bug that isn't there.
                if row["in_ledger"] and vals is not None:
                    scale = M._week_scale(vals, mk["col"])
                    if scale:
                        row["share"] = row["in_ledger"] / scale
            v["pending"].append(row)

        # 2. the NEXT period: when it is due, and whether it is already overdue.
        #    Derived from the last marker of ANY colour — the record of where the
        #    row has been, never a guess about where money goes.
        if last and step:
            nxt = _next_period(last["period"])
            due = _week_date(last["week"]) + dt.timedelta(weeks=step)
            overdue = (today - due).days // 7
            v["expected"] = {"period": nxt, "week": _week_label(due),
                             "due": due, "overdue_weeks": overdue}
            if nxt and overdue > GRACE_WEEKS and not any(
                    m["period"] == nxt for m in marks):
                v["late"].append(v["expected"])

        # 3. money in the ledger for a period the tab never marked. Reported,
        #    never placed — only Eve knows which week it belongs to.
        if ledger_rows:
            known = {m["period"] for m in marks}
            v["orphans"] = sorted(
                p for p in M._periods_in_ledger(
                    ledger_rows, kind, expl_col=P.LEDGER_EXPL_COL)
                if p not in known)
        out[kind] = v
    return out


def _print(res, *, had_ledger):
    print("\nCHEQUEO HACIA ATRAS — overrides de PERIODO (llegan tarde)")
    if not had_ledger:
        print("  (sin ledger: sólo marcadores. Corré en Lucy 1 para saber si la "
              "plata ya está en Tableau.)")
    problems = 0
    for kind in (M.SPECIAL, M.CREDICO):
        v = res[kind]
        print(f"\n  {_KIND_ES[kind].upper()}")
        if not v["last"]:
            print("    (no hay marcadores en la pestaña)")
            continue
        gaps = "/".join(str(g) for g in v["gaps_seen"])
        print(f"    cae cada {v['cadence']} semana(s) (últimos saltos: {gaps}) · "
              f"{v['markers']} marcadores")
        print(f"    último: {v['last']['period']} en la semana "
              f"{v['last']['week']} — "
              f"{'PENDIENTE' if v['last']['pending'] else 'colocado'}")

        for p in v["pending"]:
            problems += 1
            share = p["share"]
            if p["in_ledger"] is None and had_ledger:
                estado = "todavía NO se pagó (el ledger no la trae)"
            elif p["in_ledger"] is None:
                estado = "sin chequear (falta el ledger)"
            elif share is not None and share > M.MAX_PLACEMENT_SHARE:
                estado = (f"el ledger devuelve ${p['in_ledger']:,.2f}, que es "
                          f"{share:.0%} de lo que vale esa semana — eso NO es "
                          f"plata atrasada, es una LECTURA MALA; el sistema la "
                          f"frena a propósito y hace bien")
            else:
                estado = (f"la plata YA está (${p['in_ledger']:,.2f}) — la "
                          f"próxima corrida la coloca sola")
            print(f"    ⚠ {p['period']} sigue PENDIENTE hace {p['weeks']} "
                  f"semana(s) (marcado en {p['week']}): {estado}")

        e = v["expected"]
        if e:
            if e in v["late"]:
                problems += 1
                print(f"    ⚠ {e['period']} tendría que haber caído en "
                      f"{e['week']} y no hay marcador — {e['overdue_weeks']} "
                      f"semana(s) tarde")
            elif e["overdue_weeks"] >= 0:
                print(f"    {e['period']} vencía en {e['week']} — dentro de la "
                      f"tolerancia de {GRACE_WEEKS} semana(s)")
            else:
                print(f"    próximo: {e['period']} cae en {e['week']} "
                      f"(faltan {-e['overdue_weeks']} semana(s))")
        for o in v["orphans"]:
            problems += 1
            print(f"    ⚠ {o} está en el ledger pero NO tiene marcador — nadie "
                  f"puede colocarlo hasta que digas en qué semana va")
    print(f"\n{'⚠ ' + str(problems) + ' cosa(s) para mirar' if problems else '✅ nada atrasado'}")
    return problems


def watch(*, tab=None, use_ledger=True, page=None, verbose=True, today=None):
    """Run the check and print it. Returns the verdict dict."""
    from automations.recruiting_report import fill as _fill
    ws = _fill._client().open_by_key(F.WORKBOOK_ID).worksheet(tab or F.SANDBOX_TAB)
    led = None
    if use_ledger:
        try:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            led = P.ledger_rows(OUT_DIR / "ledger.csv", page=page, verbose=verbose)
        except Exception as e:  # noqa: BLE001 — the marker half still stands
            print(f"⚠ no se pudo bajar el ledger ({type(e).__name__}: "
                  f"{str(e).splitlines()[0][:120]}) — sigo sólo con marcadores")
    res = check(ws, ledger_rows=led, today=today)
    if verbose:
        _print(res, had_ledger=bool(led))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Chequeo hacia atrás de los overrides de período (special y "
                    "credico): si el último ya cayó, y si el próximo se atrasó. "
                    "No escribe nada.")
    ap.add_argument("--no-ledger", action="store_true",
                    help="no bajar el ledger de Tableau — sólo los marcadores de "
                         "la pestaña (corre en cualquier máquina)")
    ap.add_argument("--tab", default=F.SANDBOX_TAB,
                    help="pestaña a revisar (default: la copia del bot)")
    a = ap.parse_args(argv)
    watch(tab=a.tab, use_ledger=not a.no_ledger)
    # Un atraso es INFORMACIÓN, no una corrida fallida: un exit distinto de 0
    # pintaría la tarjeta del Hub en rojo por un chequeo que hizo justo su
    # trabajo. Mismo criterio que compare.py.
    return 0


if __name__ == "__main__":
    sys.exit(main())
