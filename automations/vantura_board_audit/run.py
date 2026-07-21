"""Vantura Master Sales Board — daily data-quality audit (mini, 4am batch).

Grew out of the 2026-07-19 deep audit (see memory/vantura-board-data-quality
notes and automations/vantura_payroll/PAYROLL_RUNBOOK.md for the board map).
Two invariants, both broken silently in the past:

1. OFF-MENU ADDS: every Sales Board rep must have a Roll Call
   row (the roll cohort week is the tenure anchor; a rep without one gets a
   FROZEN week tag and dodges the stats). People are supposed to add reps
   ONLY via the Alphalete menu — name columns are hard-protected since
   2026-07-19, but protection-list editors can still bypass.
2. STATS-RANGE DRIFT: the summary boxes' fixed ranges (rows 5:<last rep>)
   silently exclude reps when rows are added/removed (menu adds insert at
   row 5, pushing range starts down).

Findings are appended to the board's "Report an Issue" tab, deduped against
rows already there. Read-only against the board except that tab.

  python -m automations.vantura_board_audit.run            # audit + report
  python -m automations.vantura_board_audit.run --dry-run  # print only
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

REPORT_ID = "vantura-board-audit"
SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
WK_TAG = re.compile(r"^\d+(st|nd|rd|th) Wk$")
RANGE_TOK = re.compile(r"\$?[A-Z]{1,2}\$?(\d+):\$?[A-Z]{1,2}\$?(\d+)\b")


def _log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}",
          flush=True)


def _norm(n: str) -> str:
    return " ".join(str(n).lower().split())


def audit(write: bool, log=_log) -> int:
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(SHEET_ID)
    board = sh.worksheet("Sales Board").get("A1:AQ110")
    board_form = sh.worksheet("Sales Board").get(
        "A1:AQ110", value_render_option="FORMULA")
    roll = sh.worksheet("Roll Call").get_all_values()

    # rep block = rows >=5 with a name and a week tag, or (for tag-less manual
    # strays like the old 'Nico M' row) a campaign — but never the campaign
    # TOTAL rows, which carry a SUMIFS in col C.
    def _is_rep(i, r):
        if i < 5 or len(r) < 14 or not str(r[1]).strip():
            return False
        cf = str(board_form[i - 1][2]) if len(board_form[i - 1]) > 2 else ""
        if "SUMIFS" in cf.upper():
            return False
        return bool(WK_TAG.match(str(r[13]).strip())
                    or str(r[11]).strip() in ("B2B", "BOX", "JE", "Base"))

    reps = [(i, str(r[1]).strip()) for i, r in enumerate(board, start=1)
            if _is_rep(i, r)]
    if not reps:
        log("no rep rows found — layout changed? aborting without report")
        return 2
    last_rep = max(i for i, _ in reps)

    findings = []

    # 1. off-menu adds: board rep with no roll-call row (script's prefix rule)
    roll_names = {_norm(r[3]) for r in roll if len(r) > 3 and str(r[3]).strip()}
    for i, name in reps:
        n = _norm(name)
        hit = n in roll_names or any(
            k.startswith(n + " ") or n.startswith(k + " ") for k in roll_names)
        if not hit:
            findings.append(
                f"OFF-MENU ADD? '{name}' (board r{i}) has no Roll Call row — "
                "tenure tag is frozen and stats may miss them. Re-add via "
                "Alphalete menu > Add (or add their Roll Call row).")

    # 1b. reverse direction (added 2026-07-20 after Edgar's board row vanished
    #     mid-morning with no alert): every roll person whose status shows
    #     "Active" must have a board row. "New Start" status is exempt (they
    #     join the board at the week roll); Terminated/blank are irrelevant.
    board_names = {_norm(n) for _, n in reps}
    # managers sell occasionally but aren't board reps (Carlos, 2026-07-20)
    EXEMPT = {"carlos hidalgo", "nico murrugarra"}
    def _on_board(n):
        return n in board_names or any(
            k.startswith(n + " ") or n.startswith(k + " ") for k in board_names)
    for ri, r in enumerate(roll, start=1):
        if len(r) < 4 or not str(r[3]).strip():
            continue
        if str(r[1]).strip() != "Active":
            continue
        n = _norm(r[3])
        if n in EXEMPT:
            continue
        if not _on_board(n):
            findings.append(
                f"MISSING FROM BOARD: '{str(r[3]).strip()}' (roll r{ri}) is "
                "Active on Roll Call but has no Sales Board row — deleted by "
                "accident? Re-add via Alphalete menu (their WeekData history "
                "re-links by name).")

    # 2. stats-range drift: summary formulas whose rep-block range ends off
    for i, row in enumerate(board_form, start=1):
        for c in row:
            c = str(c)
            if not c.startswith("="):
                continue
            for m in RANGE_TOK.finditer(c):
                a, b = int(m.group(1)), int(m.group(2))
                # start-drift (top-inserted rows push 5 -> 6/7/...) is just as
                # real as end-drift — 2026-07-20 the whole % box read 7:68
                if 5 <= a <= 20 and 40 <= b <= 100 and (a != 5
                                                        or b != last_rep):
                    findings.append(
                        f"STATS-RANGE DRIFT: formula on board r{i} covers rows "
                        f"{a}:{b} but the rep block is 5:{last_rep} — "
                        "summary counts are excluding reps again. Run "
                        "Alphalete > Realign / Health Check.")
                    break
            else:
                continue
            break
        else:
            continue
        break  # one drift finding is enough — it's systemic

    findings += audit_stations(sh, last_rep, reps, roll, log=log)

    from automations.shared import run_manifest

    if not findings:
        log(f"audit clean: {len(reps)} reps checked, block ends r{last_rep}, "
            "stations OK")
        if write:
            run_manifest.mark_clean(REPORT_ID, kind="finding")
        return 0

    ri = sh.worksheet("Report an Issue")
    existing = " ".join(" ".join(r) for r in ri.get_all_values()[-40:])
    new = [f for f in findings if f[:60] not in existing]
    for f in findings:
        log(("NEW: " if f in new else "already reported: ") + f)
    if not write:
        log("(dry-run: nothing appended, no manifest written)")
        return 0
    today = dt.date.today().strftime("%-m/%-d/%Y")
    if new:
        ri.append_rows([[today, "board-audit (mini 4am)", "Sales Board", f, ""]
                        for f in new], value_input_option="RAW")
        log(f"appended {len(new)} finding(s) to Report an Issue")

    # FINDINGS ARE THE JOB, NOT A FAILURE. Exit 0 and record the findings in a
    # run-manifest as ok=False so the orchestrator marks this a SOFT INCOMPLETE
    # (with the finding text as its note) instead of a hard exit-1 FAILED that
    # fires the immediate "needs attention" page (Megan/Carlos 2026-07-21, same
    # class as the tableau_screenshots false-fail). No retry_args: a human fixes
    # the board — there is nothing to auto-re-run. A GENUINE crash (scrape/auth/
    # IO) still exits non-zero from main(); a layout break still returns 2 above.
    note = (f"{len(findings)} board data-quality finding(s) logged to the "
            "board's 'Report an Issue' tab: " + " | ".join(f[:140] for f in findings))
    run_manifest.write_manifest(REPORT_ID, ok=False, kind="finding",
                                failed=findings, note=note, retry_args=[])
    return 0


def audit_stations(sh, last_rep: int, reps, roll, log=_log) -> list[str]:
    """Stations-tab invariants (added 2026-07-19 after the audit that found
    all of these broken at once):
      1. no formula-error cells (#REF!/#N/A/... — e.g. the deleted week-label
         ref that silently emptied the new-start lists for months)
      2. checklist formulas V5/X5/Z5 filter the board from $B$5 (they had
         drifted to B10/B15, hiding the top reps) and W5/Y5/AA5 read roll
         $D$3 and compare $R$2 (not a stale range / literal #REF!)
      3. Rep List FILTERs (F col, all sections + Mon-Fri lineup blocks) start
         at $B$5 — top-inserted board rows push these ranges down over time
      4. Stations week label R2 == Sales Board B2
      5. name hygiene: every human name in the car-ride / skill / lineup /
         OFF-list cells must match a board rep or a roll-call person (catches
         'aracely'-style typos and stale identities that break matching)
    """
    out = []
    stn = sh.worksheet("Stations")
    vals = stn.get("A1:CL135")
    form = stn.get("A1:CL135", value_render_option="FORMULA")

    for i, row in enumerate(vals, start=1):
        for j, c in enumerate(row):
            if any(e in str(c) for e in ("#REF!", "#N/A", "#VALUE!", "#NAME?")):
                out.append(f"STATIONS: error value {c!r} at r{i}c{j+1} — a "
                           "formula reference broke (deleted row/col?).")

    def fml(a1):
        m = re.match(r"([A-Z]+)(\d+)", a1)
        col = 0
        for ch in m.group(1):
            col = col * 26 + ord(ch) - 64
        r = int(m.group(2))
        row = form[r-1] if len(form) >= r else []
        return str(row[col-1]) if len(row) >= col else ""

    for cell in ("V5", "X5", "Z5"):
        f = fml(cell)
        if f and "'Sales Board'!$B$5:" not in f:
            out.append(f"STATIONS: checklist {cell} no longer filters the "
                       "board from $B$5 — top reps are being dropped again.")
    for cell in ("W5", "Y5", "AA5"):
        f = fml(cell)
        if f and ("$D$3:" not in f or "$R$2" not in f or "#REF" in f):
            out.append(f"STATIONS: new-start list {cell} formula drifted "
                       "(needs roll $D$3 range + $R$2 week; no #REF).")
    for cell in ("F6", "F29", "F42", "F55", "F68", "F81", "F94", "F107", "F120"):
        f = fml(cell)
        if f and "$B$5:" not in f:
            out.append(f"STATIONS: Rep List formula {cell} no longer starts "
                       "at board $B$5 (top-insert drift).")

    week_stn = str(vals[1][17]).strip() if len(vals) > 1 and len(vals[1]) > 17 else ""
    week_board = str(sh.worksheet("Sales Board").acell("B2").value or "").strip()
    if week_stn and week_board and week_stn != week_board:
        out.append(f"STATIONS: week label R2={week_stn!r} != Sales Board "
                   f"B2={week_board!r}.")

    known = {_n(n) for _, n in reps} | {
        _n(r[3]) for r in roll if len(r) > 3 and str(r[3]).strip()}
    def matches(name):
        n = _n(name)
        return (n in known or any(k.startswith(n + " ") or n.startswith(k + " ")
                                  for k in known))
    LABELS = re.compile(r"^(\d|rep #|rep list|store|territory|car rides|"
                        r"stations|legend|off|terminated|new starts|monday|"
                        r"tuesday|wednesday|thursday|friday|in a |in both|"
                        r"roadtrip|pitch|closing|transition|running|day 0|"
                        r"pk$|qq|intro |saturday|sunday)", re.I)
    name_cols = list(range(0, 7)) + list(range(8, 14)) + [89]
    unknown = set()
    for i, row in enumerate(vals, start=1):
        if i < 4:
            continue
        for j in name_cols:
            c = str(row[j]).strip() if len(row) > j else ""
            if c and " " in c and not LABELS.match(c) and not matches(c):
                unknown.add(f"{c!r} (r{i})")
    if unknown:
        out.append("STATIONS: name(s) matching nobody on the board/roll — "
                   "typo or stale identity: " + ", ".join(sorted(unknown)[:8]))
    return out


def _n(s) -> str:
    return " ".join(str(s).lower().split())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Vantura board daily audit.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print findings; don't write to Report an Issue")
    args = ap.parse_args(argv)
    try:
        return audit(write=not args.dry_run)
    except Exception as e:  # noqa: BLE001 — audit must fail loud in the log
        _log(f"AUDIT ERROR: {type(e).__name__}: {e}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
