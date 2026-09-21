"""Tick OBCL boxes off OwnerVille — Digi Docs, Onboarding Quizzes, UID
Request, Owner Submit.

    python -m automations.obcl_ov_sweep.run            # dry run: say what it WOULD tick
    python -m automations.obcl_ov_sweep.run --tick     # write the ticks
    python -m automations.obcl_ov_sweep.run --only "Marqoun Holland"

Reads the newest `D2D OBCL <m.d>` tab (every chart on it, last week's carried
chart included), then ONE read of OwnerVille's View Progress table (RES-AT&T,
Show All). A box is ticked only when OwnerVille shows every step behind it
done with a date stamp. Ticks go ON only — never off: a hand tick stays.
Blue Ink and Headshot Photo have their own automations and are not touched.

Owner Submit also gets a colour: BLUE once every other OwnerVille step is
green (someone needs to go submit them), GREEN once it's ticked.
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


def _tint(ws, p, color) -> dict:
    """Background of the Owner Submit cell ONLY — the checkbox value is never
    touched by a tint."""
    col = p.cols["Owner Submit"]
    return {"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": p.row - 1,
                  "endRowIndex": p.row, "startColumnIndex": col - 1,
                  "endColumnIndex": col},
        "cell": {"userEnteredFormat": {"backgroundColor": color}},
        "fields": "userEnteredFormat.backgroundColor"}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tick", action="store_true",
                    help="write the ticks (default: dry run)")
    ap.add_argument("--tab", default="", help="OBCL tab (default: newest)")
    ap.add_argument("--only", default="", help="one person, 'First Last'")
    ap.add_argument("--show", action="store_true", help="visible browser")
    args = ap.parse_args(argv)

    ws, values = _open_tab(args.tab)
    everyone = sweep.people(values)
    todo = sweep.to_check(everyone)
    if args.only:
        todo = [p for p in todo if p.name.lower() == args.only.strip().lower()]
    print(f"{ws.title}: {len(everyone)} people, {len(todo)} with an open box "
          f"({', '.join(config.COLUMNS)})", flush=True)
    if not todo:
        return 0

    from automations.shared.tableau_patchright import ownerville_session
    with ownerville_session(headless=not args.show, verbose=False,
                            profile_dir=PROFILE_DIR) as page:
        heads, reps, complete = ov_table.read_table(page)

    matched, missing = match(todo, reps)
    writes, log, ready = [], [], []
    for p in todo:
        ov_name = matched.get(p.row)
        if not ov_name:
            continue
        cells = reps[ov_name]
        done = ov_table.done_columns(heads, cells)
        new = sweep.earned(p, done)
        for col in new:
            writes.append((p, col))
        is_ready = ov_table.ready_for_owner_submit(heads, cells)
        if (is_ready is True and "Owner Submit" in p.open_columns
                and "Owner Submit" not in new):
            ready.append(p)
        log.append({"row": p.row, "obcl": p.name, "ov": ov_name,
                    "done": done, "tick": new, "ready": is_ready,
                    "cells": {h.replace("\n", " "): c["text"].replace("\n", " ")
                              for h, c in zip(heads, cells)}})
        mark = ", ".join(new) if new else "nothing new"
        if ready and ready[-1] is p:
            mark += "  🔵 ready for Owner Submit"
        print(f"  row {p.row:>3}  {p.name:<28} → {mark}")

    for p in missing:
        print(f"  row {p.row:>3}  {p.name:<28} ⚠ not found in OwnerVille "
              f"({config.CAMPAIGN}) — left alone")
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
    submitted = [p for p, c in writes if c == "Owner Submit"]
    if args.tick and (ready or submitted):
        ws.spreadsheet.batch_update({"requests":
            [_tint(ws, p, config.READY_BLUE) for p in ready]
            + [_tint(ws, p, config.DONE_GREEN) for p in submitted]})

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
