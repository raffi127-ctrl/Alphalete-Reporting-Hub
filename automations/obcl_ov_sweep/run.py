"""Tick OBCL boxes off OwnerVille — Digi Docs, Onboarding Quizzes, UID
Request, Owner Submit.

    python -m automations.obcl_ov_sweep.run            # dry run: say what it WOULD tick
    python -m automations.obcl_ov_sweep.run --tick     # write the ticks
    python -m automations.obcl_ov_sweep.run --only "Marqoun Holland"

Reads the newest `D2D OBCL <m.d>` tab (every chart on it, last week's carried
chart included), then ONE read of OwnerVille's View Progress table (RES-AT&T,
Show All). A box is ticked only when OwnerVille shows every step behind it
done with a date stamp. Ticks go ON only — never off: a hand tick stays.
Blue Ink has its own automation and is not touched. Headshot Photo is shared
with the Headshot Bot (both tick ON only); this catches hand uploads.

Colours: every box it owns is GREEN (done) or LIGHT RED (not done); Owner
Submit is BLUE when it's the only step left, YELLOW when only a pending
background check stands in the way. Owner Submit additionally turns BLUE
once every other OwnerVille step is green (someone needs to go submit them).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import gspread

from automations.obcl_ov_sweep import config, ov_table, sweep

ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = ROOT / "automations" / "uploaded" / config.BROWSER_PROFILE_DIRNAME
LOG_DIR = ROOT / "output" / "obcl_ov_sweep"


def _open_tab(tab_name: str = ""):
    from automations.blueink_docs import roster as bir
    from automations.recruiting_report.fill import open_by_key
    ws = bir.current_tab(open_by_key(config.SHEET_ID), tab_name)
    return ws, ws.get_all_values()


def match(people, reps: dict):
    """{person: ov name} for everyone we can pin to exactly one OV row.
    Ambiguous or absent -> left out (and reported), never guessed."""
    from automations.digi_docs import namematch
    options = list(reps)
    by_norm = {namematch.norm(o): o for o in options}
    out, missing = {}, []
    for p in people:
        exact = by_norm.get(namematch.norm(p.name))
        hit = exact or namematch.resolve(p.name, options)[0]
        if hit:
            out[p.row] = hit
        else:
            missing.append(p)
    return out, missing


def _tint(ws, p, color, column: str = "Owner Submit") -> dict:
    """Background of ONE cell only — a tint never touches the checkbox value."""
    col = p.cols[column]
    return {"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": p.row - 1,
                  "endRowIndex": p.row, "startColumnIndex": col - 1,
                  "endColumnIndex": col},
        "cell": {"userEnteredFormat": {"backgroundColor": color}},
        "fields": "userEnteredFormat.backgroundColor"}}


def _paint(ws, everyone, ticked_now, ready_rows, live: bool,
           bg_pending_rows=()) -> None:
    """Green = ticked, blue = ready for Owner Submit, light red = not done —
    all four sweep columns, every active person, one batch_update."""
    plan = sweep.paint_plan(everyone, ticked_now, ready_rows, bg_pending_rows)
    n = {k: sum(1 for *_, col in plan if col is v) for k, v in
         (("green", config.DONE_GREEN), ("blue", config.READY_BLUE),
          ("yellow", config.BG_PENDING_YELLOW), ("red", config.NOT_FOUND_RED))}
    print(f"{'Painted' if live else 'Would paint'}: green {n['green']}, "
          f"blue {n['blue']}, yellow {n['yellow']}, light red {n['red']}")
    if live and plan:
        ws.spreadsheet.batch_update({"requests":
            [_tint(ws, p, color, c) for p, c, color in plan]})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tick", action="store_true",
                    help="write the ticks (default: dry run)")
    ap.add_argument("--tab", default="", help="OBCL tab (default: newest)")
    ap.add_argument("--only", default="", help="one person, 'First Last'")
    ap.add_argument("--show", action="store_true", help="visible browser")
    ap.add_argument("--paint-only", action="store_true",
                    help="colour the boxes off the sheet alone — no OwnerVille")
    args = ap.parse_args(argv)

    ws, values = _open_tab(args.tab)
    everyone = sweep.people(values)
    todo = sweep.to_check(everyone)
    if args.only:
        todo = [p for p in todo if p.name.lower() == args.only.strip().lower()]
    print(f"{ws.title}: {len(everyone)} people, {len(todo)} with an open box "
          f"({', '.join(config.COLUMNS)})", flush=True)
    if args.paint_only:
        _paint(ws, everyone, (), (), args.tick)
        return 0
    if not todo:
        # Nothing to look up — still colour every box by its tick.
        _paint(ws, everyone, (), (), args.tick)
        return 0

    import time
    t0 = time.monotonic()
    from automations.shared.tableau_patchright import ownerville_session
    with ownerville_session(headless=not args.show, verbose=False,
                            profile_dir=PROFILE_DIR) as page:
        heads, reps, complete = ov_table.read_table(page)
        matched, missing = match(todo, reps)
        if missing:
            # The one-page read is not trusted to be whole; search the rest.
            surnames = sorted({(p.last or p.first).split()[-1]
                               for p in missing if (p.last or p.first)})
            ov_table.search_fill(page, heads, reps, surnames)
            matched, missing = match(todo, reps)
        if missing:
            # Second probe for a surname that searches differently in OV
            # ("Quiroz - Lebron" on the OBCL): the first name.
            firsts = sorted({p.first.split()[0] for p in missing if p.first})
            ov_table.search_fill(page, heads, reps, firsts)
            matched, missing = match(todo, reps)
        # Everyone not on page 1 was searched for directly, so the page-1
        # shortfall no longer leaves anyone unread.
        complete = True
    writes, log, ready, bg_wait = [], [], [], []
    for p in todo:
        ov_name = matched.get(p.row)
        if not ov_name:
            continue
        cells = reps[ov_name]
        done = ov_table.done_columns(heads, cells)
        new = sweep.earned(p, done)
        for col in new:
            writes.append((p, col))
        state = ov_table.owner_submit_state(heads, cells)
        is_ready = state == "ready"
        if "Owner Submit" in p.open_columns and "Owner Submit" not in new:
            if state == "ready":
                ready.append(p)
            elif state == "bg_pending":
                bg_wait.append(p)
        log.append({"row": p.row, "obcl": p.name, "ov": ov_name,
                    "done": done, "tick": new, "ready": is_ready,
                    "cells": {h.replace("\n", " "): c["text"].replace("\n", " ")
                              for h, c in zip(heads, cells)}})
        mark = ", ".join(new) if new else "nothing new"
        if ready and ready[-1] is p:
            mark += "  🔵 ready for Owner Submit"
        elif bg_wait and bg_wait[-1] is p:
            mark += "  🟡 only the background check is pending"
        print(f"  row {p.row:>3}  {p.name:<28} → {mark}")

    for p in missing:
        print(f"  row {p.row:>3}  {p.name:<28} ⚠ not found in OwnerVille "
              f"({config.CAMPAIGN}) — left alone")
    if missing:
        print(f"NOT FOUND ({len(missing)}): "
              + "; ".join(f"{p.name} (row {p.row})" for p in missing))
    if not complete:
        print("  ⛔ View Progress read was INCOMPLETE — anyone not found above "
              "may simply not have been read.")

    by_col = {c: sum(1 for _, x in writes if x == c) for c in config.COLUMNS}
    print(f"\n{'Ticked' if args.tick else 'Would tick'}: "
          + ", ".join(f"{c} {n}" for c, n in by_col.items())
          + f"  ({len(writes)} boxes, {len(missing)} not found)")
    print(f"{'Painted' if args.tick else 'Would paint'} Owner Submit blue "
          f"(ready to submit): {len(ready)}"
          + (f" — {', '.join(p.name for p in ready)}" if ready else ""))

    if args.tick and writes:
        ws.batch_update(
            [{"range": gspread.utils.rowcol_to_a1(p.row, p.cols[c]),
              "values": [["TRUE"]]} for p, c in writes],
            value_input_option="USER_ENTERED")   # so the checkbox ticks
    # Every box we tick also turns green (Megan 2026-09-21: "checkmark the box
    # and turn it green") — which is also what clears an Owner Submit blue.
    _paint(ws, everyone, [(p.row, c) for p, c in writes],
           [p.row for p in ready], args.tick, [p.row for p in bg_wait])

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    (LOG_DIR / f"{stamp}{'' if args.tick else '_dry'}.json").write_text(
        json.dumps({"tab": ws.title, "tick": args.tick, "complete": complete,
                    "headers": heads, "people": log,
                    "missing": [p.name for p in missing],
                    "ready_for_owner_submit": [p.name for p in ready]}, indent=1))
    return 0 if complete else 2


if __name__ == "__main__":
    sys.exit(main())
