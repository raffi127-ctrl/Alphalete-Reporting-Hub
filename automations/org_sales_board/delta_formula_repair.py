"""Rebuild the LIVE formulas on the DELTA boxes: the per-day 'This week'
=SUMIFs and the Delta % beside them.

WHAT BREAKS
-----------
Every delta box ('Total this week / Last week / Delta') carries, per rep row,
seven per-day 'This week' cells (F/I/L/O/R/U/X). Each is a =SUMIF over that
captainship's own DAILY table, keyed on the rep's name as a literal string:

    F1684 = =SUMIF($B$214:$B$226,"Rafael Hidalgo",$C$214:$C$226)

Everything above them is derived from those seven: the row's 'Total this week'
(col C, `=F+I`, sized to the elapsed days by `elapsed_totals.plan_delta_lastweek`)
and the box's totals row (`=SUM` down the column). So a literal pasted over one
of these cells does not look broken — it shows a number, and the number is even
right for the day it was frozen on. It just stops moving.

On 2026-08-26 all twelve FIBER boxes (Raf/Wayne/Starr/Chan/Tony/Sahil, two boxes
each) had all 602 of these cells as literals, frozen at the Tuesday-morning
state: Monday's real number in the first day column and 0 in the other six.
Monday looked perfect, Tuesday never arrived, and 'Total this week' ran short all
week. No other box was touched and every totals row was fine — which is exactly
why nobody saw it for a week. `rollover.check_delta_live_formulas` is the
tripwire; this is the repair it points at.

THE REPAIR
----------
Rebuild the formula from the board's own structure. Each delta box is matched to
its captainship's daily table — `captainship.find_captainship_boxes` for the
boxes (a fiber captain has TWO, stacked New Internet then All Units; everyone
else has one), `cap_insert._delta_captain` for whose box a delta table is. Boxes
and delta tables pair up in tab order, and a pair is REFUSED unless the rep
counts match, so a roster change mid-repair cannot shear a name onto the wrong
row. A rep in the delta box whose name is absent from the daily table is skipped
and reported: that SUMIF would be valid and silently return 0.

ACCEPTANCE TEST (why the ranges can be trusted): the rebuilt Monday cell must
recompute to the literal that was already sitting in it. Monday is a completed
day, so the formula and the frozen value describe the same thing — if a range
were off by a row the two would not agree. `--verify` asserts it after writing.

A box no captainship claims (RAF SPECIAL TEAM, TRANG'S ORG — cross-cutting
rosters that read another captain's daily table) has no daily table of its own to
derive from and is SKIPPED, not guessed at. Same rule `cap_insert` follows.

Everything is located by label — captain title, 'Total this week', 'Monday',
col-B rep name — never by row/column index ([[feedback_no_hardcoded_columns]]).

    python -m automations.org_sales_board.delta_formula_repair            # dry-run
    python -m automations.org_sales_board.delta_formula_repair --apply --verify

Applied 2026-08-26: 602 cells across the 12 fiber boxes. Monday agreed with the
frozen literal on all 86 rep rows and Tuesday came back from 0 to 1,202 units.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automations.recruiting_report.fill import open_by_key, _retry     # noqa: E402
from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB      # noqa: E402
from automations.org_sales_board import captainship as cap             # noqa: E402
from automations.org_sales_board import rollover as ro                 # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                                      # noqa: BLE001
    pass


def _cell(grid, r1: int, c1: int) -> str:
    """1-based row/col, always a str — the grid may be values or formulas."""
    row = grid[r1 - 1] if 0 < r1 <= len(grid) else []
    return str(row[c1 - 1]).strip() if 0 < c1 <= len(row) else ""


def pair_boxes(grid: List[List[str]]) -> Tuple[List[dict], List[str]]:
    """[{box, delta}] pairs, plus a line per box it refused to pair.

    A fiber captain owns two daily boxes AND two delta tables; both lists come
    off the tab top to bottom, so zipping them keeps New Internet with New
    Internet. The rep counts are asserted rather than assumed — an unequal pair
    is reported and dropped, never written to.
    """
    from automations.new_owners import cap_insert as ci

    by_cap: Dict[str, List[dict]] = {}
    for title, _prog in cap.discover_captainships(grid):
        for variant, anchor in cap.find_captainship_boxes(grid, title):
            rows = [r for r, _ in anchor.daily]
            if not rows or not anchor.day_cols:
                continue
            by_cap.setdefault(cap._cap_key(title), []).append(
                {"captain": title, "variant": variant,
                 "d0": min(rows), "d1": max(rows),
                 "day_cols": sorted(anchor.day_cols),
                 "names": [n for _, n in anchor.daily]})

    deltas: Dict[str, List[dict]] = {}
    problems: List[str] = []
    for t in ro.find_delta_tables(grid):
        title = ci._delta_captain(grid, t["header_row"])
        if not title:
            problems.append(f"la caja delta de la fila {t['header_row']} no la "
                            f"reclama ninguna capitania — se saltea")
            continue
        deltas.setdefault(cap._cap_key(title), []).append(
            {"t": t, "title": title})

    pairs: List[dict] = []
    for key, boxes in by_cap.items():
        ds = deltas.get(key, [])
        if len(ds) != len(boxes):
            problems.append(f"{key}: {len(boxes)} caja(s) diaria(s) pero "
                            f"{len(ds)} tabla(s) delta — se saltea")
            continue
        for box, d in zip(boxes, ds):
            n_daily, n_delta = len(box["names"]), len(d["t"]["data_rows"])
            if n_daily != n_delta:
                problems.append(
                    f"{key}/{box['variant']}: la diaria tiene {n_daily} reps y "
                    f"la delta {n_delta} filas — se saltea")
                continue
            pairs.append({"box": box, "delta": d})
    return pairs, problems


DELTA_PCT_COL = 5                 # col E — the row's Delta %


def plan_delta_pct(grid: List[List[str]], formulas: List[List[str]]
                   ) -> List[dict]:
    """[{range, values}] for every Delta % cell that is a frozen value.

    Row-local arithmetic ('=Iferror((C-D)/D,0)'), so unlike the per-day SUMIFs
    it needs no daily table and applies to EVERY delta box — the cross-cutting
    ones (RAF SPECIAL TEAM, TRANG'S ORG) included, and to a hand-filled rep's
    row too: their C and D are typed in, but the percentage between them is
    still computed. A cell that is already a formula is never rewritten."""
    updates: List[dict] = []
    for t in ro.find_delta_tables(grid):
        rows = list(t["data_rows"])
        tail = rows[-1] + 1
        if _cell(grid, tail, 3):                  # label-less totals row
            rows.append(tail)
        for r in rows:
            if _cell(formulas, r, DELTA_PCT_COL).startswith("="):
                continue
            updates.append({"range": f"{ro.a1col(DELTA_PCT_COL)}{r}",
                            "values": [[f"=Iferror((C{r}-D{r})/D{r},0)"]]})
    return updates


def plan(grid: List[List[str]], formulas: List[List[str]],
         pairs: List[dict]) -> Tuple[List[dict], List[str], int]:
    """[{range, values}] for every per-day 'This week' cell that is not already
    the right =SUMIF, plus warnings and the count already correct."""
    updates: List[dict] = []
    warn: List[str] = []
    already = 0
    for p in pairs:
        box, t = p["box"], p["delta"]["t"]
        title = p["delta"]["title"]
        day_cols = box["day_cols"]                    # C..I on the daily table
        tw_cols = sorted(t["this_cols"])              # F/I/L/O/R/U/X on the delta
        if len(day_cols) != len(tw_cols):
            warn.append(f"{title}: {len(day_cols)} dia(s) en la diaria vs "
                        f"{len(tw_cols)} triplete(s) en la delta — se saltea")
            continue
        daily_names = {n.strip().lower() for n in box["names"]}
        for r in t["data_rows"]:
            name = _cell(grid, r, 2)
            if name.strip().lower() not in daily_names:
                warn.append(f"{title} fila {r}: '{name}' no esta en la diaria "
                            f"{box['d0']}-{box['d1']} — se saltea (daria 0)")
                continue
            esc = name.replace('"', '""')
            for dc, tc in zip(day_cols, tw_cols):
                col = ro.a1col(dc)
                want = (f'=SUMIF($B${box["d0"]}:$B${box["d1"]},"{esc}",'
                        f'${col}${box["d0"]}:${col}${box["d1"]})')
                # Case-insensitive: SUMIF's criterion is, and some rows were
                # hand-keyed lowercase ("jackie leroy"). Those compute correctly
                # — rewriting them would be churn that never converges.
                if _cell(formulas, r, tc).casefold() == want.casefold():
                    already += 1
                    continue
                updates.append({"range": f"{ro.a1col(tc)}{r}",
                                "values": [[want]]})
    return updates, warn, already


def _num(v) -> Optional[float]:
    try:
        return float(str(v).replace(",", "").replace("$", "").strip() or 0)
    except (TypeError, ValueError):
        return None


def verify_monday(ws, before: List[List[str]],
                  pairs: List[dict]) -> Tuple[int, List[str]]:
    """Re-read the tab and assert the rebuilt Monday cell equals the literal the
    repair overwrote. Returns (rows that agree, disagreements)."""
    after = _retry(ws.get_all_values)
    ok, bad = 0, []
    for p in pairs:
        t = p["delta"]["t"]
        first = sorted(t["this_cols"])[0]
        for r in t["data_rows"]:
            was, now = _num(_cell(before, r, first)), _num(_cell(after, r, first))
            if was is None or now is None:
                continue
            if was == now:
                ok += 1
            else:
                bad.append(f"{ro.a1col(first)}{r} ({_cell(before, r, 2)}): "
                           f"era {was:g}, ahora {now:g}")
    return ok, bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="rehace los =SUMIF por dia de las cajas delta")
    ap.add_argument("--apply", action="store_true",
                    help="escribe en el Sheet (por defecto: dry-run)")
    ap.add_argument("--tab", default=SANDBOX_TAB)
    ap.add_argument("--verify", action="store_true",
                    help="tras escribir, confirma que el lunes recalculado "
                         "coincide con el literal que habia")
    args = ap.parse_args(argv)

    print(f"=== delta 'This week' repair — {args.tab!r} — "
          f"{'APPLY' if args.apply else 'DRY-RUN'} ===")
    ws = _retry(lambda: open_by_key(SHEET_ID).worksheet(args.tab))
    grid = _retry(ws.get_all_values)
    formulas = _retry(lambda: ws.get_all_values(value_render_option="FORMULA"))

    pairs, problems = pair_boxes(grid)
    for p in problems:
        print(f"  · {p}")
    print(f"  {len(pairs)} caja(s) pareada(s) con su tabla diaria")
    for p in pairs:
        b, d = p["box"], p["delta"]
        print(f"    {b['captain']:<14} {str(b['variant']):<13} "
              f"delta fila {d['t']['header_row']:>5} "
              f"({len(d['t']['data_rows'])} reps) -> diaria {b['d0']}-{b['d1']}")

    updates, warn, already = plan(grid, formulas, pairs)
    pct = plan_delta_pct(grid, formulas)
    if pct:
        print(f"  columna Delta: {len(pct)} celda(s) congelada(s) -> formula")
    updates += pct
    for w in warn:
        print(f"  [!] {w}")
    print(f"  ya correctas: {already} · a reescribir: {len(updates)}")
    for u in updates[:5]:
        print(f"    {u['range']} = {u['values'][0][0]}")
    if len(updates) > 5:
        print(f"    ...y {len(updates) - 5} mas")

    if not args.apply:
        print("  (dry-run — no se escribio nada)")
        return 0
    if not updates:
        print("  nada que escribir")
        return 0
    ws.batch_update(updates, value_input_option="USER_ENTERED")
    print(f"  [OK] {len(updates)} formula(s) escrita(s)")

    if args.verify:
        ok, bad = verify_monday(ws, grid, pairs)
        if bad:
            print(f"  [FALLO] el lunes NO coincide en {len(bad)} celda(s) — "
                  f"los rangos pueden estar mal:")
            for b in bad[:10]:
                print(f"      {b}")
            return 1
        print(f"  [OK] el lunes recalculado coincide con el literal previo "
              f"en {ok} fila(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
