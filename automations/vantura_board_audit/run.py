"""Vantura Master Sales Board — daily data-quality audit (mini, 4am batch).

Grew out of the 2026-07-19 deep audit (see memory/vantura-board-data-quality
notes and automations/vantura_payroll/PAYROLL_RUNBOOK.md for the board map).
Two invariants, both broken silently in the past:

1. OFF-MENU ADDS: every Sales Board rep must have a New Starts & Roll Call
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
    roll = sh.worksheet("New Starts & Roll Call").get_all_values()

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

    # 2. stats-range drift: summary formulas whose rep-block range ends off
    for i, row in enumerate(board_form, start=1):
        for c in row:
            c = str(c)
            if not c.startswith("="):
                continue
            for m in RANGE_TOK.finditer(c):
                a, b = int(m.group(1)), int(m.group(2))
                if a in (5, 6) and 40 <= b <= 100 and b != last_rep:
                    findings.append(
                        f"STATS-RANGE DRIFT: formula on board r{i} covers rows "
                        f"{a}:{b} but the rep block ends at r{last_rep} — "
                        "summary counts are excluding reps again.")
                    break
            else:
                continue
            break
        else:
            continue
        break  # one drift finding is enough — it's systemic

    if not findings:
        log(f"audit clean: {len(reps)} reps checked, block ends r{last_rep}")
        return 0

    ri = sh.worksheet("Report an Issue")
    existing = " ".join(" ".join(r) for r in ri.get_all_values()[-40:])
    new = [f for f in findings if f[:60] not in existing]
    for f in findings:
        log(("NEW: " if f in new else "already reported: ") + f)
    if not write:
        log("(dry-run: nothing appended)")
        return 1
    today = dt.date.today().strftime("%-m/%-d/%Y")
    if new:
        ri.append_rows([[today, "board-audit (mini 4am)", "Sales Board", f, ""]
                        for f in new], value_input_option="RAW")
        log(f"appended {len(new)} finding(s) to Report an Issue")
    return 1


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
