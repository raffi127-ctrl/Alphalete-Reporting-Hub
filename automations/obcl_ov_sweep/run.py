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


SUBMIT_FAILURES: list = []   # [(name, reason)] this pass — for the group text
LUCY_SUBMITTED: list = []    # names Lucy owner-submitted THIS pass
ALERTED: list = []           # [True] once the Megan/Eve alert really posted


def _picture(ws, args) -> None:
    """The hourly picture: drawn every live pass, texted only if it changed.
    Never lets a picture problem fail the sweep — the ticks already landed."""
    if not args.tick:
        return
    try:
        from automations.obcl_ov_sweep import snapshot
        _, values = _open_tab(args.tab or ws.title)
        print(snapshot.after_pass(ws, values, live=args.tick, text=args.text,
                                  failures=SUBMIT_FAILURES,
                                  lucy_new=LUCY_SUBMITTED,
                                  alerted=bool(ALERTED)), flush=True)
    except Exception as e:                                  # noqa: BLE001
        print(f"picture: FAILED ({type(e).__name__}: {str(e)[:200]})",
              flush=True)


def _submit(ready, writes, *, live: bool) -> None:
    """Owner-submit each READY person in OwnerVille (Megan 2026-09-22).

    GATED by config.OWNER_SUBMIT_LIVE: while it is False this is always a dry
    walk up to the confirm box — nobody is submitted and they stay blue. When
    live, only a submit OwnerVille CONFIRMS ("Review in Progress" on a fresh
    re-open) moves someone off blue and ticks the OBCL box."""
    from automations.obcl_ov_sweep import owner_submit
    from automations.shared.tableau_patchright import ownerville_session
    real = bool(live and config.OWNER_SUBMIT_LIVE)
    if live and not config.OWNER_SUBMIT_LIVE:
        print("  OWNER SUBMIT is GATED (config.OWNER_SUBMIT_LIVE = False) — "
              "dry walk only, nobody submitted", flush=True)
    with ownerville_session(headless=True, verbose=False,
                            profile_dir=PROFILE_DIR) as page:
        for p in list(ready):
            outcome, detail = owner_submit.submit_one(page, p.name,
                                                      dry_run=not real)
            print(f"  OWNER SUBMIT {outcome.upper()}: {detail}", flush=True)
            if real and outcome == "refused":
                # Megan 2026-09-22: a submit that didn't go through goes in the
                # group text. Detail reads "<Name>: <reason>" — keep the reason.
                SUBMIT_FAILURES.append((p.name, detail.split(": ", 1)[-1]))
            if outcome == "submitted":
                LUCY_SUBMITTED.append(p.name)
            if outcome in ("submitted", "already"):
                writes.append((p, "Owner Submit"))
                ready.remove(p)


ALERT_CHANNEL = "C0BK5PRG259"          # #claudecorrections-and-requests
ALERT_TAGS = ("<@U04G5HJBGFN>", "<@U088E2KJEV8>")   # Megan, Eve


def _alert_failures(live: bool) -> None:
    """Megan 2026-09-22: a submit Lucy couldn't do goes to the alerts channel,
    tagging Megan and Eve, so it gets corrected. One incident thread
    (failure-obcl_owner_submit): a same-day repeat updates it rather than
    posting again. The technical reason lives HERE, not in the group text."""
    if not (live and SUBMIT_FAILURES):
        return
    body = [" ".join(ALERT_TAGS) + " — owner submit needs doing by hand in "
            "OwnerVille (then Lucy ticks the OBCL on the next pass):"]
    body += [f"• {n} — {why}" for n, why in SUBMIT_FAILURES]
    title = (f"OBCL: couldn't owner submit {len(SUBMIT_FAILURES)} "
             f"new start{'s' if len(SUBMIT_FAILURES) != 1 else ''} in OwnerVille")
    try:
        from automations.shared import incident_thread as inc
        res = inc.open_or_followup(key="failure-obcl_owner_submit",
                                   title=title, body=body,
                                   channel=ALERT_CHANNEL,
                                   subjects=[n for n, _ in SUBMIT_FAILURES],
                                   label="OBCL owner submit")
        if res:
            ALERTED.append(True)
        print(f"  alert {'posted' if res else 'NOT confirmed'}: {title}",
              flush=True)
    except Exception as e:                                  # noqa: BLE001
        print(f"  ⚠ owner-submit alert FAILED to post ({type(e).__name__}: "
              f"{str(e)[:160]})", flush=True)


def _key(p) -> str:
    from automations.digi_docs import namematch
    return namematch.norm(p.name)


def _tint(ws, p, color, column: str = "Owner Submit") -> dict:
    """Background of ONE cell only — a tint never touches the checkbox value."""
    col = p.cols[column]
    return {"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": p.row - 1,
                  "endRowIndex": p.row, "startColumnIndex": col - 1,
                  "endColumnIndex": col},
        "cell": {"userEnteredFormat": {"backgroundColor": color}},
        "fields": "userEnteredFormat.backgroundColor"}}


def _statuses(ws, everyone, ticked_now, live: bool) -> None:
    """Final Status -> "Owner submitted" once Owner Submit + Blue Ink are both
    ticked. One batched write; the value only, never the cell's formatting."""
    ups = sweep.status_updates(everyone, ticked_now)
    print(f"{'Set' if live else 'Would set'} Final Status to "
          f"{sweep.OWNER_SUBMITTED!r}: {len(ups)}"
          + (f" — {', '.join(p.name for p in ups)}" if ups else ""))
    if live and ups:
        ws.batch_update(
            [{"range": gspread.utils.rowcol_to_a1(p.row, p.status_col),
              "values": [[sweep.OWNER_SUBMITTED]]} for p in ups],
            value_input_option="USER_ENTERED")


def _paint(ws, everyone, ticked_now, ready_rows, live: bool,
           bg_pending_rows=(), sheet_only: bool = False) -> None:
    """Green = ticked, blue = ready for Owner Submit, light red = not done —
    all four sweep columns, every active person, one batch_update."""
    plan = sweep.paint_plan(everyone, ticked_now, ready_rows, bg_pending_rows,
                            sheet_only=sheet_only)
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
    ap.add_argument("--text", action="store_true",
                    help="after a live pass, text the picture to ORIENTATION "
                         "CREW - Real IF it changed (the hourly wrapper sets it)")
    ap.add_argument("--submit", action="store_true",
                    help="owner-submit anyone READY in OwnerVille — gated by "
                         "config.OWNER_SUBMIT_LIVE (dry walk while False)")
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
        _statuses(ws, everyone, (), args.tick)
        _paint(ws, everyone, (), (), args.tick, sheet_only=True)
        return 0
    if not todo:
        # Nothing to look up — still colour every box by its tick.
        _statuses(ws, everyone, (), args.tick)
        _paint(ws, everyone, (), (), args.tick)
        _picture(ws, args)
        return 0

    import time
    t0 = time.monotonic()
    from automations.shared.tableau_patchright import ownerville_session
    with ownerville_session(headless=not args.show, verbose=False,
                            profile_dir=PROFILE_DIR) as page:
        heads, reps, complete = ov_table.read_table(page)
        matched, missing = match(todo, reps)
        if missing:
            # Page 1 is all the browser ever gets (server-side table); ask the
            # search about each person still missing, one at a time.
            t1 = time.monotonic()
            for p in list(missing):
                try:
                    ov_table.lookup_person(page, p.name, heads, reps)
                except Exception as e:                      # noqa: BLE001
                    print(f"  {p.name}: search failed ({type(e).__name__})")
            matched, missing = match(todo, reps)
            print(f"  searched one by one in {time.monotonic() - t1:.0f}s — "
                  f"{len(missing)} still not found", flush=True)
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

    if ready and args.submit:
        _submit(ready, writes, live=args.tick)
        _alert_failures(args.tick)
    # RE-READ BEFORE WRITING (2026-09-21, 7:22pm). The OwnerVille part takes
    # minutes; someone deleted last week's chart and inserted a Classroom
    # column meanwhile, and colours painted at the rows/columns read at the
    # START landed on Blue Ink, above the header and below the table. So the
    # tab is read again here and every tick + colour is placed by NAME on the
    # fresh read. A person who moved is found where they are now; one who
    # vanished is skipped.
    if args.tick:
        ws, values = _open_tab(args.tab or ws.title)
        fresh = sweep.people(values)
        where = {_key(p): p for p in fresh}
        writes = [(where[_key(p)], c) for p, c in writes
                  if _key(p) in where and c in where[_key(p)].cols]
        ready = [where[_key(p)] for p in ready if _key(p) in where]
        bg_wait = [where[_key(p)] for p in bg_wait if _key(p) in where]
        everyone = fresh
    if args.tick and writes:
        ws.batch_update(
            [{"range": gspread.utils.rowcol_to_a1(p.row, p.cols[c]),
              "values": [["TRUE"]]} for p, c in writes],
            value_input_option="USER_ENTERED")   # so the checkbox ticks
    _statuses(ws, everyone, [(p.row, c) for p, c in writes], args.tick)
    # Every box we tick also turns green (Megan 2026-09-21: "checkmark the box
    # and turn it green") — which is also what clears an Owner Submit blue.
    _paint(ws, everyone, [(p.row, c) for p, c in writes],
           [p.row for p in ready], args.tick, [p.row for p in bg_wait])

    _picture(ws, args)

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
