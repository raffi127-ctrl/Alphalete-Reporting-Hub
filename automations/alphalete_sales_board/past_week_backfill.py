"""Fill LAST WEEK'S TOTALS on this week's tab from the week that just ended.

WHY IT IS NOT A FORMULA. On a REP row those columns hold values -- Eve's Monday
roll drops last week's numbers in, which is why `APPS` there is `8` and not a
formula. So the Talk-To columns beside them have to be filled the same way, and
the numbers have to come from somewhere: this reads the PREVIOUS week's own tab.

WHAT IT CAN WORK OUT AND WHAT IT CANNOT.

  * `AVG Total Knocks per day` = the LAST WEEK `TK` already on this tab, over
    the days that rep actually worked -- and THOSE are on last week's tab, in
    its day blocks. Same rule the live columns use (`day_worked_expr`): not `X`,
    not `T`, not Sunday, and the day has to have left a trace.
  * `Total Talk-To's` and `AVG TT's per day` need last week's per-day Talk-To's.
    Those live nowhere but the tab that carried them, so this fills them only
    when last week's tab HAS the column. It never invents them.

    (For WE 9.6 that tab was the sandbox Eve had deleted, so those two stayed
    empty and the Talk-To history had to come back another way. From WE 9.13 on
    the live tabs carry the column and this needs no help.)

    python -m automations.alphalete_sales_board.past_week_backfill            # preview
    python -m automations.alphalete_sales_board.past_week_backfill --apply
"""
from __future__ import annotations

import argparse
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 -- Windows console, best effort
    pass

from automations.alphalete_sales_board.talk_to_columns import (
    ANCHOR, PROD_SHEET_ID, ROLL_CALL, SANDBOX_TAB, TRIO, WEEK_AVG_TK,
    WEEK_AVG_TT, WEEK_TT, _cell, _col_letter, _labelled_block, day_blocks,
    sub_col)

LAST_WEEK = "LAST WEEK'S TOTALS"


def _norm(name: str) -> str:
    from automations.energy_slack_fill.run import _norm as n
    return n(name)


def days_and_talk(grid) -> dict:
    """{normalised rep name: (days worked, weekly Talk-To's or None)} from a
    finished week's tab."""
    from automations.energy_slack_fill.run import last_rep_row, name_col
    nc, last = name_col(grid), last_rep_row(grid)
    blocks = [(lab, b) for lab, b in day_blocks(grid).items()
              if lab.upper() != "SUN"]
    out = {}
    for r in range(4, last + 1):
        nm = _cell(grid, r, nc)
        if not nm:
            continue
        days, talk, seen_tt = 0, 0, False
        for _lab, b in blocks:
            apps = _cell(grid, r, b[0])
            tk = _cell(grid, r, sub_col(grid, b, ANCHOR) or b[0])
            rc_col = sub_col(grid, b, ROLL_CALL)
            rc = _cell(grid, r, rc_col) if rc_col else ""
            if apps in ("X", "T", ""):
                continue
            if rc or tk or apps not in ("0", "0.00"):
                days += 1
            tt_col = sub_col(grid, b, TRIO[0])
            if tt_col:
                seen_tt = True
                try:
                    talk += int(float(_cell(grid, r, tt_col) or 0))
                except ValueError:
                    pass
        out[_norm(nm)] = (days, talk if seen_tt else None)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tab", default=SANDBOX_TAB, help="this week's tab")
    ap.add_argument("--from-tab", required=True, help="last week's tab")
    ap.add_argument("--sheet-id", default=PROD_SHEET_ID)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    from automations.energy_slack_fill.run import last_rep_row, name_col
    from automations.recruiting_report.fill import open_by_key
    ss = open_by_key(a.sheet_id)
    src = ss.worksheet(a.from_tab)
    ws = ss.worksheet(a.tab)
    prev = days_and_talk(src.get("A1:%s200" % _col_letter(src.col_count),
                                 value_render_option="FORMATTED_VALUE"))
    grid = ws.get("A1:%s200" % _col_letter(ws.col_count),
                  value_render_option="FORMATTED_VALUE")
    b = _labelled_block(grid, LAST_WEEK)
    if not b[0]:
        print("no hay bloque %r en %r" % (LAST_WEEK, a.tab))
        return 1
    tk_c = sub_col(grid, b, ANCHOR)
    cols = {h: sub_col(grid, b, h) for h in (WEEK_AVG_TK, WEEK_TT, WEEK_AVG_TT)}
    if not tk_c or not all(cols.values()):
        print("%s incompleto en %r -- correr --past-weeks primero"
              % (LAST_WEEK, a.tab))
        return 1

    nc, last = name_col(grid), last_rep_row(grid)
    data, hit, miss, no_tt = [], 0, [], 0
    for r in range(4, last + 1):
        nm = _cell(grid, r, nc)
        if not nm:
            continue
        got = prev.get(_norm(nm))
        if not got:
            miss.append(nm)
            continue
        days, talk = got
        hit += 1
        try:
            tk = float(_cell(grid, r, tk_c) or 0)
        except ValueError:
            tk = 0
        data.append({"range": "%s%d" % (_col_letter(cols[WEEK_AVG_TK]), r),
                     "values": [[round(tk / days, 1) if days else "-"]]})
        if talk is None:
            no_tt += 1
            continue
        data.append({"range": "%s%d" % (_col_letter(cols[WEEK_TT]), r),
                     "values": [[talk]]})
        data.append({"range": "%s%d" % (_col_letter(cols[WEEK_AVG_TT]), r),
                     "values": [[round(talk / days, 1) if days else "-"]]})

    print("%r <- %r" % (a.tab, a.from_tab))
    print("  %d rep(s) emparejados, %d sin par en la semana pasada" % (hit, len(miss)))
    if miss:
        print("     " + ", ".join(miss[:8]) + (" …" if len(miss) > 8 else ""))
    if no_tt:
        print("  %d sin Talk-To's: la pestaña de la semana pasada no tiene la "
              "columna, esas dos quedan vacías" % no_tt)
    print("  %d celda(s) a escribir" % len(data))
    for d in data[:6]:
        print("     %s -> %r" % (d["range"], d["values"][0][0]))
    if not a.apply:
        print("\npreview only -- re-run with --apply to write.")
        return 0
    ws.batch_update(data, value_input_option="USER_ENTERED")
    print("\nescritas %d celda(s) en %s." % (len(data), LAST_WEEK))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
