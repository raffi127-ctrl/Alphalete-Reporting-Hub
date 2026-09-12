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
    ANCHOR, DAY_ROW, PROD_SHEET_ID, ROLL_CALL, SANDBOX_TAB, TRIO, WEEK_AVG_TK,
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


def week_of_tab(tab: str):
    """The seven dates of a 'Sales Board WE m.d' tab, Monday first."""
    import datetime as dt
    import re as _re
    m = _re.search(r"WE\s+(\d{1,2})\.(\d{1,2})", tab)
    if not m:
        raise SystemExit("no puedo leer la semana del nombre %r" % tab)
    today = dt.date.today()
    sunday = dt.date(today.year, int(m.group(1)), int(m.group(2)))
    return [sunday - dt.timedelta(days=6 - i) for i in range(7)]


def pull_week_talk_to(tab: str) -> dict:
    """{normalised rep name: the week's Talk-To's} straight from ownerville.

    Seven pulls in ONE session, because ownerville allows a single session per
    account and seven separate jobs would spend the day stepping aside for each
    other. A day that fails is reported and skipped, never guessed: a short week
    is visible, an invented number is not.
    """
    from automations.alphalete_production.tk_fill import _ov_norm
    from automations.total_knocks.pull import (
        COL_REP, COL_TOTAL_TALK_TO, KnocksPullFailed, pull_disposition_day)
    out = {}
    for day in week_of_tab(tab):
        try:
            got, records = pull_disposition_day(day, verbose=False)
        except KnocksPullFailed as e:
            print("  ! %s: ownerville falló (%s) -- día salteado" % (day, e))
            continue
        if got != day:
            print("  ! %s: ownerville contestó por %s -- día salteado" % (day, got))
            continue
        n = 0
        for rec in records:
            nm = str(rec.get(COL_REP, "")).strip()
            if not nm:
                continue
            try:
                v = int(float(str(rec.get(COL_TOTAL_TALK_TO, "")).replace(",", "") or 0))
            except ValueError:
                continue
            out[_ov_norm(nm)] = out.get(_ov_norm(nm), 0) + v
            n += 1
        print("  %s: %d rep(s)" % (day, n))
    return out


def team_avg_formula(src_col: int, knocks_col: int, row: int, days: int) -> str:
    """The per-day average of one team row, AS A FORMULA -- never as the number
    this run happens to read.

    WHY. A team's `Total Talk-To's` is a SUMIFS over the rep rows, so what it
    reads depends on WHEN you look. On 2026-09-11 the rep rows still held '-'
    when the backfill ran, the SUMIFS came back 0, and `float(cell or 0)` froze
    a `0.0` into six team rows -- each reading "0.0 talk-to's per day" next to
    its own 939. Numbers arriving later could not fix it: the cell was a value.

    Dividing in the sheet removes the ordering hazard. The guards mirror the
    block's own rules: no knocks that week -> the row stays clean (blank);
    knocks but nothing countable -> '-'.
    """
    src = "%s%d" % (_col_letter(src_col), row)
    knocks = "%s%d" % (_col_letter(knocks_col), row)
    return ('=IF(N(%s)=0,"",IF(NOT(ISNUMBER(%s)),"-",IFERROR(%s/%d,"-")))'
            % (knocks, src, src, days))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tab", default=SANDBOX_TAB, help="this week's tab")
    ap.add_argument("--from-tab", required=True, help="last week's tab")
    ap.add_argument("--sheet-id", default=PROD_SHEET_ID)
    ap.add_argument("--pull-talk-to", action="store_true",
                    help="take last week's Talk-To's from OWNERVILLE (7 pulls) "
                         "instead of from last week's tab -- for a week whose "
                         "tab never carried the column. Needs an ownerville "
                         "session, so it runs on Lucy 3.")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    from automations.energy_slack_fill.run import last_rep_row, name_col
    from automations.recruiting_report.fill import open_by_key
    ss = open_by_key(a.sheet_id)
    src = ss.worksheet(a.from_tab)
    ws = ss.worksheet(a.tab)
    prev = days_and_talk(src.get("A1:%s200" % _col_letter(src.col_count),
                                 value_render_option="FORMATTED_VALUE"))
    if a.pull_talk_to:
        # Ownerville carries the legal name and the board what people are
        # called, so the match falls back to FIRST + LAST word -- the same two
        # passes tk_fill uses, and for the same reason.
        from automations.alphalete_production.tk_fill import _ends
        pulled = pull_week_talk_to(a.from_tab)
        by_ends = {}
        for k, v in pulled.items():
            by_ends.setdefault(_ends(k), []).append(v)
        def _talk(key):
            if key in pulled:
                return pulled[key]
            hits = by_ends.get(_ends(key), [])
            return hits[0] if len(hits) == 1 else None
        prev = {k: (days, _talk(k)) for k, (days, _t) in prev.items()}
        print("  ownerville: %d rep(s) con talk-to's esa semana" % len(pulled))
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
        try:                       # sin knocks esa semana: la fila queda limpia
            has_knocks = float(_cell(grid, r, tk_c) or 0) > 0
        except ValueError:
            has_knocks = False
        if not has_knocks:
            continue
        got = prev.get(_norm(nm))
        if not got:
            # A rep who was not on LAST WEEK'S tab at all. Nothing to deduce,
            # so all three say so -- leaving the cells untouched would leave
            # blanks in the middle of the block, which reads as a broken report.
            miss.append(nm)
            for h in (WEEK_AVG_TK, WEEK_TT, WEEK_AVG_TT):
                data.append({"range": "%s%d" % (_col_letter(cols[h]), r),
                             "values": [["-"]]})
            continue
        days, talk = got
        hit += 1
        try:
            tk = float(_cell(grid, r, tk_c) or 0)
        except ValueError:
            tk = 0
        # '-' where nothing can be worked out, the number where it can, and 0
        # when the number is really 0 (Eve, 2026-09-09). A blank in a weekly
        # block reads as a broken report, so no cell of a real rep is left one.
        data.append({"range": "%s%d" % (_col_letter(cols[WEEK_AVG_TK]), r),
                     "values": [[round(tk / days, 1) if days else "-"]]})
        if talk is None:
            no_tt += 1
            for h in (WEEK_TT, WEEK_AVG_TT):
                data.append({"range": "%s%d" % (_col_letter(cols[h]), r),
                             "values": [["-"]]})
            continue
        data.append({"range": "%s%d" % (_col_letter(cols[WEEK_TT]), r),
                     "values": [[talk]]})
        data.append({"range": "%s%d" % (_col_letter(cols[WEEK_AVG_TT]), r),
                     "values": [[round(talk / days, 1) if days else "-"]]})

    # --- and the Teams block's two per-day cells --------------------------
    # They are the only cells in that block a formula cannot reach: a finished
    # week's day columns are gone, so there is no team day count to divide by.
    # The days ARE known here though -- one rep at a time, off last week's tab --
    # so they are summed per team and written as VALUES. That is what the block
    # holds anyway: from Monday on, Eve's roll carries the live numbers across
    # and nothing here has to run again.
    team_col = None
    for c in range(1, len(grid[0]) + 1):
        if _cell(grid, DAY_ROW, c).strip().lower() == "team":
            team_col = c
            break
    if team_col:
        days_by_team, all_days = {}, 0
        for r in range(4, last + 1):
            nm, team = _cell(grid, r, nc), _cell(grid, r, team_col)
            got = prev.get(_norm(nm))
            if not nm or not got:
                continue
            days_by_team[team] = days_by_team.get(team, 0) + got[0]
            all_days += got[0]
        int_c = sub_col(grid, b, "INT") or sub_col(grid, b, "Int")
        team_rows = [r for r in range(last + 2, len(grid) + 1)
                     if _cell(grid, r, int_c or 1)]
        tt_c = cols[WEEK_TT]
        for r in team_rows:
            label = _cell(grid, r, 3)
            d = all_days if "TOTALS" in label.upper() else days_by_team.get(label)
            if not d:
                continue
            # A FORMULA, not the number this run happens to see.
            #
            # WHY. A team's `Total Talk-To's` is itself a SUMIFS over the rep
            # rows, so what it reads depends on WHEN you look. On 2026-09-11 the
            # rep rows still held '-' when this ran, the SUMIFS came back 0, and
            # `float(cell or 0)` wrote a hard `0.0` -- so six teams read "0.0
            # talk-to's per day" next to their own 939. The numbers arriving
            # later could not fix it: the cell was a frozen value.
            #
            # Dividing in the sheet removes the ordering hazard entirely. The
            # guards mirror the block's own rules: no knocks that week -> the row
            # stays clean; knocks but no countable talk-to's -> '-'.
            for col, src_col in ((cols[WEEK_AVG_TK], tk_c),
                                 (cols[WEEK_AVG_TT], tt_c)):
                data.append({"range": "%s%d" % (_col_letter(col), r),
                             "values": [[team_avg_formula(src_col, tk_c, r, d)]]})
        # The roster's TOTALS row holds VALUES here, not formulas (`379`, not a
        # SUMIF), so its Talk-To's total has to be added up the same way.
        week_tt = sum(t for _d, t in prev.values() if isinstance(t, int))
        if week_tt:
            data.append({"range": "%s%d" % (_col_letter(cols[WEEK_TT]), last + 1),
                         "values": [[week_tt]]})
        # The roster's own TOTALS row, over the days EVERYBODY worked.
        #
        # The Talk-To's total comes from `week_tt`, NOT from re-reading the
        # cell: the grid was loaded before this run wrote anything, so that cell
        # still holds whatever was there -- and if `--past-weeks` had seeded it
        # with '-', float() choked and the average silently stayed a dash. That
        # is the cell Eve found in the totals on 2026-09-09.
        try:
            tk_total = float(_cell(grid, last + 1, tk_c) or 0)
        except ValueError:
            tk_total = 0
        for col, v in ((cols[WEEK_AVG_TK], tk_total), (cols[WEEK_AVG_TT], week_tt)):
            data.append({"range": "%s%d" % (_col_letter(col), last + 1),
                         "values": [[round(v / all_days, 1) if all_days and v
                                     else "-"]]})
        print("  equipos: %s" % ", ".join(
            "%s=%d dias" % (k or "(sin equipo)", v)
            for k, v in sorted(days_by_team.items()) if v))

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
