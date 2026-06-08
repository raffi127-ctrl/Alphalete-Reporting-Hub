"""Daily match-check: the COPY tab (automation output) vs the live VA tab.

Reads BOTH existing tabs (never creates anything), matches ICDs by name
(+ aliases) across the 6 daily sections + 10 captainships, and compares the
COMPLETED days (everything before today). It distinguishes real glitches from
expected, harmless differences so the daily run only cries wolf when the
automation is actually wrong:

  • exact              — same value (fine)
  • NS-vs-0            — copy "NS" vs VA 0/blank (intentional, formula-safe)
  • automation-ahead   — copy has a value, VA still 0/blank (the live pull is
                         simply more current than the hand-entry; NOT a glitch)
  • VA-ahead   ❌ GLITCH — VA has a value the copy is missing (NS/0/blank): the
                         automation failed to pull a real sale
  • mismatch   ❌ GLITCH — both have values and they differ
  • copy-missing ❌ GLITCH — an ICD on the VA tab has no row on the copy (the
                         copy roster is behind; add the row)

Prints `=== done ===` ONLY when clean. If any ❌ glitch is found it prints the
flagged list and omits the sentinel, so the Hub surfaces the run for review.
Read-only — writes nothing. ICDs only, not reps. [[feedback_flag_nonmatched_icds]]
[[feedback_read_actual_content]]
"""
from __future__ import annotations

import datetime as dt

from automations.recruiting_report.fill import open_by_key, _retry
from automations.org_sales_board import fill_section as fs, captainship as cap
from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB, PROD_TAB
from automations.focus_office_att.aliases import load_aliases
from automations.alphalete_org_report.tableau_http import _norm_owner

SECTIONS = ["Retail NL", "Retail Internet", "ATT Fiber Team",
            "ATT NDS Team", "B2B", "BOX"]
CAPS = ["RAF", "WAYNE", "STARR", "ARON", "CARLOS",
        "EVELIZ", "LUIS", "KHALIL", "COLTEN", "JAIRO"]
_ZERO = {"", "0", "0.0", "0%", "0.00%"}


def _cell(grid, r, c):
    return (grid[r][c].strip() if 0 <= r < len(grid)
            and 0 <= c < len(grid[r]) else "")


def _classify(c, v):
    """copy cell `c` vs VA cell `v` -> bucket."""
    if c == v:
        return "exact" if c else "blank"
    if c == "NS" and v in _ZERO:
        return "ns0"
    if c in _ZERO and v in _ZERO:
        return "blank"
    if c not in _ZERO and c != "NS" and v in _ZERO:
        return "auto_ahead"            # copy ahead of VA — not a glitch
    if (c in _ZERO or c == "NS") and v not in _ZERO:
        return "va_ahead"              # GLITCH: automation missing a real sale
    return "mismatch"                  # GLITCH: both have values, differ


def run_compare(logfn=print) -> dict:
    today = dt.date.today()
    aliases = load_aliases()
    sh = open_by_key(SHEET_ID)
    copy = _retry(sh.worksheet(SANDBOX_TAB).get_all_values)
    va = _retry(sh.worksheet(PROD_TAB).get_all_values)
    from automations.org_sales_board import week as _wk
    monday = _wk.reporting_monday(today)
    completed = _wk.completed_days(today)
    logfn(f"=== ORG board compare — copy vs VA — completed days "
          f"{[d.isoformat() for d in completed] or '(none yet)'} ===")

    tally = {k: 0 for k in
             ("exact", "ns0", "auto_ahead", "va_ahead", "mismatch")}
    glitches, copy_missing = [], []

    def amatch(name, pool_norm):
        return next((k for k in fs._candidates_for(name, aliases)
                     if k in pool_norm), None)

    # --- daily sections ---
    for lbl in SECTIONS:
        try:
            ca = fs.find_daily_section(copy, lbl)
            vca = fs.find_daily_section(va, lbl)
        except Exception as e:
            logfn(f"  ⚠ section {lbl!r} not found ({str(e)[:50]})")
            continue
        vrows = {_norm_owner(n): r for n, r in vca.icd_rows.items()}
        cnorm = {_norm_owner(n) for n in ca.icd_rows}
        for name, crow in ca.icd_rows.items():
            vr = vrows.get(amatch(name, set(vrows)))
            if vr is None:
                continue
            for d in completed:
                cc = ca.day_col_by_daynum.get(d.day)
                vc = vca.day_col_by_daynum.get(d.day)
                if not cc or not vc:
                    continue
                b = _classify(_cell(copy, crow - 1, cc - 1),
                              _cell(va, vr - 1, vc - 1))
                tally[b] = tally.get(b, 0) + 1
                if b in ("va_ahead", "mismatch"):
                    glitches.append(f"[{lbl}] {name} {d:%a}: "
                                    f"copy={_cell(copy, crow-1, cc-1)!r} "
                                    f"VA={_cell(va, vr-1, vc-1)!r}")
        copy_missing += [f"[{lbl}] {n}" for n in vca.icd_rows
                         if amatch(n, cnorm) is None]

    # --- captainships ---
    for t in CAPS:
        try:
            ca = cap.find_captainship(copy, t)
            vca = cap.find_captainship(va, t)
        except Exception as e:
            logfn(f"  ⚠ captainship {t!r} not found ({str(e)[:50]})")
            continue
        vrows = {_norm_owner(n): r for r, n in vca.daily}
        cnorm = {_norm_owner(n) for r, n in ca.daily}
        for crow, name in ca.daily:
            vr = vrows.get(amatch(name, set(vrows)))
            if vr is None:
                continue
            for i in range(min(len(completed), len(ca.day_cols), len(vca.day_cols))):
                b = _classify(_cell(copy, crow - 1, ca.day_cols[i] - 1),
                              _cell(va, vr - 1, vca.day_cols[i] - 1))
                tally[b] = tally.get(b, 0) + 1
                if b in ("va_ahead", "mismatch"):
                    glitches.append(
                        f"[{t} cap] {name} d{i}: "
                        f"copy={_cell(copy, crow-1, ca.day_cols[i]-1)!r} "
                        f"VA={_cell(va, vr-1, vca.day_cols[i]-1)!r}")
        copy_missing += [f"[{t} cap] {n}" for r, n in vca.daily
                         if amatch(n, cnorm) is None]

    logfn(f"  exact={tally['exact']}  NS-vs-0={tally['ns0']}  "
          f"automation-ahead={tally['auto_ahead']}")
    clean = not glitches and not copy_missing
    if glitches:
        logfn(f"  ❌ {len(glitches)} REAL mismatch(es) (automation wrong/behind):")
        for g in glitches:
            logfn(f"      {g}")
    if copy_missing:
        logfn(f"  ❌ {len(copy_missing)} ICD(s) on the VA tab but MISSING a copy "
              f"row (add them): {copy_missing}")
    if clean:
        logfn("  ✅ copy matches the VA tab on every completed-day cell.")
    else:
        logfn("  ❌ COMPARISON FOUND DIFFERENCES — review the flagged items "
              "above before trusting the copy.")
    return {"tally": tally, "glitches": glitches, "copy_missing": copy_missing,
            "clean": clean}


def main():
    res = run_compare()
    if res["clean"]:
        print("=== done ===")
        return 0
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
