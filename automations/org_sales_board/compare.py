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
CAPS = ["RAF", "WAYNE", "STARR", "CHAN", "TONY", "SAHIL", "CARLOS",
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


def check_formula_drift(cS, vS, aliases, logfn=print) -> list:
    """Flag cells the automation should keep as LIVE formulas but wrote as a
    static value — the 'clobbered formula' regression (e.g. a captainship
    leaderboard total written as a frozen number instead of =SUMIF, fixed
    2026-06-14).

    CONTENT-MATCHED (2026-07-04): pairs each copy row to its VA twin by content
    (name/label/finder-order via full_compare.content_row_map), then compares
    formula-PRESENCE at the twin — NEVER at the same row number. The two tabs
    carry different counts of history/spacer rows, so a same-row scan lined a
    static rep/history cell up against a VA formula row and cried 'drift' on
    ~99% false positives. Only content-matched structural rows are checked; a row
    with no twin is skipped (never flagged by position).

    Reports ONLY 'VA twin has a formula here, copy has a static non-blank value' —
    the real drift signal. Deliberately ignores:
      • col A (rank — intentionally static, re-ranked correctly every run)
      • copy == 'NS' (intended no-sales marker over a VA =SUM that would be 0)
      • blank copy cells (cleared today/future days, not a clobber)
      • 'both are formulas but differ' (those are equivalent: =SUM(C:I) vs VA's
        explicit list, and delta =SUMIFs that differ only by the sorted name)
    Read-only. Returns the flagged cell list."""
    from automations.org_sales_board.full_compare import content_row_map
    sh = open_by_key(SHEET_ID)
    cF = _retry(lambda: sh.worksheet(SANDBOX_TAB).get_all_values(
        value_render_option="FORMULA"))
    vF = _retry(lambda: sh.worksheet(PROD_TAB).get_all_values(
        value_render_option="FORMULA"))
    row_map = content_row_map(cS, vS, aliases)   # copy 1-based row -> VA 1-based row

    def isf(x):
        return isinstance(x, str) and x.startswith("=")

    def fcell(g, r, c):
        # FORMULA render returns ints/floats for numeric cells, not just str —
        # so don't assume .strip() exists; coerce to a string.
        return str(g[r][c]) if (0 <= r < len(g) and 0 <= c < len(g[r])) else ""

    flagged = []
    for cr, vr in sorted(row_map.items()):
        ci, vi = cr - 1, vr - 1                 # 1-based rows -> 0-based grid idx
        width = max(len(cF[ci]) if 0 <= ci < len(cF) else 0,
                    len(vF[vi]) if 0 <= vi < len(vF) else 0)
        for c in range(1, width):              # skip col A (index 0) = rank
            vv = fcell(vF, vi, c)
            cc = fcell(cF, ci, c)
            if isf(vv) and not isf(cc) and cc.strip() and cc.strip().upper() != "NS":
                flagged.append((cr, c + 1, fcell(vF, vi, 1) or fcell(vF, vi, 0),
                                cc, vv))
    if flagged:
        logfn(f"  ❌ FORMULA DRIFT — {len(flagged)} cell(s) the report wrote as a "
              f"static value where the VA tab keeps a live formula "
              f"(formula clobbered — it'll freeze/drift):")
        for r, c, lbl, cc, vv in flagged[:30]:
            from gspread.utils import rowcol_to_a1
            logfn(f"      {rowcol_to_a1(r, c)} [{lbl[:24]}] static={cc[:14]!r} "
                  f"expected formula={vv[:40]!r}")
        if len(flagged) > 30:
            logfn(f"      …and {len(flagged) - 30} more")
    else:
        logfn("  ✅ no formula drift — every VA formula cell is still a live "
              "formula on the copy.")
    return flagged


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
    # Formula-region integrity: catch any live VA formula the report clobbered
    # with a static value (separate from the value compare above).
    formula_drift = check_formula_drift(copy, va, aliases, logfn)
    # DERIVED / bottom auto-formula tables (leaderboards, delta tables, ORG +
    # campaign history rows, product summaries, section running totals). The value
    # compare above only reaches the raw daily cells; this reaches the totals a
    # wrong SUMIF would break (the old =F Monday-only 'Total this week'). Its own
    # SEPARATE bucket, current-week only, name-matched where sorted. Wrapped so a
    # bug in the new check can never crash the daily run's compare.
    try:
        from automations.org_sales_board import full_compare as _fc
        derived = _fc.run_derived_compare(sh, copy, va, aliases, logfn)
    except Exception as e:  # noqa: BLE001
        logfn(f"  ⚠ derived-table compare skipped ({type(e).__name__}: {str(e)[:60]})")
        derived = {"concerning": [], "benign_count": 0, "clean": True}
    clean = (not glitches and not copy_missing and not formula_drift
             and derived["clean"])
    if glitches:
        logfn(f"  ❌ {len(glitches)} REAL mismatch(es) (automation wrong/behind):")
        for g in glitches:
            logfn(f"      {g}")
    if copy_missing:
        logfn(f"  ❌ {len(copy_missing)} ICD(s) on the VA tab but MISSING a copy "
              f"row (add them): {copy_missing}")
    if clean:
        logfn("  ✅ copy matches the VA tab on every completed-day cell + every "
              "derived this-week total.")
    else:
        logfn("  ❌ COMPARISON FOUND DIFFERENCES — review the flagged items "
              "above before trusting the copy.")
    return {"tally": tally, "glitches": glitches, "copy_missing": copy_missing,
            "formula_drift": formula_drift, "derived": derived["concerning"],
            "clean": clean}


def _numeq(a: str, b: str) -> bool:
    try:  # strip thousands separators + a trailing % so '1,193'=='1193' etc.
        return (float(str(a).replace(",", "").rstrip("%"))
                == float(str(b).replace(",", "").rstrip("%")))
    except (ValueError, TypeError):
        return False


def every_cell_diff(band_at: int = 1000) -> dict:
    """RAW, exhaustive cell-by-cell diff of the whole copy tab vs the whole VA
    tab — EVERY cell, not just the report's completed-day/total regions. Compares
    DISPLAYED values (get_all_values), so a formula and a static value showing the
    same number match, and numerically-equal cells ('2' vs '2.0') are NOT flagged.

    Each real difference is bucketed by row band (< band_at vs >= band_at) and by
    KIND — the distinction that matters:
      copy-blank  : copy empty, VA has a value  (VA-only content / offset)
      va-blank    : copy has a value, VA empty  (copy-only content / offset)
      both-differ : BOTH populated but different (the only true data conflict)
    Only 'both-differ' cells are genuine disagreements; the blanks are structural
    (the two tabs aren't mirror layouts — different rows/summary blocks)."""
    from collections import Counter
    import gspread
    a1 = gspread.utils.rowcol_to_a1
    sh = open_by_key(SHEET_ID)
    copy = _retry(sh.worksheet(SANDBOX_TAB).get_all_values)
    va = _retry(sh.worksheet(PROD_TAB).get_all_values)
    counts: Counter = Counter()
    both_differ = []   # (a1, copy, va, row)
    for r in range(max(len(copy), len(va))):
        cr = copy[r] if r < len(copy) else []
        vr = va[r] if r < len(va) else []
        for c in range(max(len(cr), len(vr))):
            cv = (cr[c] if c < len(cr) else "").strip()
            vv = (vr[c] if c < len(vr) else "").strip()
            if cv == vv or _numeq(cv, vv):
                continue
            band = "below" if (r + 1) < band_at else "atplus"
            kind = "copy-blank" if not cv else "va-blank" if not vv else "both-differ"
            counts[(band, kind)] += 1
            if kind == "both-differ":
                both_differ.append((a1(r + 1, c + 1), cv, vv, r + 1))
    return {"copy_rows": len(copy), "va_rows": len(va), "band_at": band_at,
            "counts": dict(counts), "both_differ": both_differ}


def content_diff() -> dict:
    """CONTENT-keyed comparison (position-independent): match every labeled row
    between the two tabs by its A/B label signature — wherever it physically sits
    — then compare that row's values column-by-column. This answers 'does the
    CONTENT match?' rather than 'is every cell in the same place?'. Only rows with
    a unique, non-blank label on BOTH tabs are compared (blank/duplicate rows —
    spacers, repeated headers — can't be keyed unambiguously, so they're skipped
    and counted separately). Numerically-equal cells ('2' vs '2.0') are not
    flagged. Returns matched-row count, per-cell mismatches, and label-only sets."""
    from automations.org_sales_board import full_compare as _fc
    import gspread
    a1 = gspread.utils.rowcol_to_a1
    sh = open_by_key(SHEET_ID)
    copy = _retry(sh.worksheet(SANDBOX_TAB).get_all_values)
    va = _retry(sh.worksheet(PROD_TAB).get_all_values)

    def index(grid):
        m = {}
        for r in range(len(grid)):
            sig = _fc._row_sig(grid, r + 1)
            if sig[0] or sig[1]:
                m.setdefault(sig, []).append(r)
        return m

    ci, vi = index(copy), index(va)
    mismatches, matched, ambiguous = [], 0, 0
    only_copy, only_va = [], []
    for sig in set(ci) | set(vi):
        crows, vrows = ci.get(sig, []), vi.get(sig, [])
        label = f"{sig[0]}|{sig[1]}".strip("|")[:44]
        # Sections sit in a FIXED vertical order and the leaderboard sort only
        # reorders rows WITHIN a section, so the Kth top-to-bottom occurrence of
        # a name on the copy corresponds to the Kth on the VA — pair them in
        # order. This covers EVERY labeled row (no unkeyed dup-label gap) while
        # still ignoring within-section row-order/sort differences.
        if len(crows) != len(vrows):
            ambiguous += 1          # appears a different number of times each side
        for cr_i, vr_i in zip(crows, vrows):
            matched += 1
            cr, vr = copy[cr_i], va[vr_i]
            for c in range(max(len(cr), len(vr))):
                cv = (cr[c] if c < len(cr) else "").strip()
                vv = (vr[c] if c < len(vr) else "").strip()
                if cv == vv or _numeq(cv, vv):
                    continue
                if c == 0 and cv.isdigit() and vv.isdigit():
                    continue   # col-A rank = sort POSITION, not a data value
                if cv.lower() in ("", "0", "ns") and vv.lower() in ("", "0", "ns"):
                    continue   # blank / 0 / NS both mean "no sale"
                mismatches.append((label, a1(cr_i + 1, c + 1), cv, vv))
        # occurrences with no partner on the other side = row present on one only
        for extra in crows[len(vrows):]:
            only_copy.append(f"{label} @ row {extra + 1}")
        for extra in vrows[len(crows):]:
            only_va.append(f"{label} @ row {extra + 1}")
    return {"matched_rows": matched, "ambiguous_labels": ambiguous,
            "copy_labeled": len(ci), "va_labeled": len(vi),
            "only_copy": sorted(only_copy), "only_va": sorted(only_va),
            "mismatches": mismatches}


def format_va_check(d: dict, max_lines: int = 60) -> str:
    """Render the whole-sheet content_diff() as a compact block for the daily
    completion email: EVERY labeled cell (incl. below row 1000), matched by name
    so row-order/sort differences don't count — only real value differences,
    each with its cell + copy vs VA value. So Megan sees exactly what differs
    without having to ask. (2026-07-07.)"""
    mm = d.get("mismatches", [])
    ov, oc = d.get("only_va", []), d.get("only_copy", [])
    head = (f"VA whole-sheet check (every labeled cell incl. below row 1000; "
            f"matched by name so row-order/rank/no-sale differences are ignored): "
            f"{len(mm)} value diff(s)"
            + (f", {len(ov)} row(s) only on VA" if ov else "")
            + (f", {len(oc)} only on copy" if oc else "")
            + f" [matched {d.get('matched_rows', 0)} rows; "
              f"{d.get('ambiguous_labels', 0)} dup-label rows not keyed].")
    if not mm and not ov and not oc:
        return head + " ✅ all cells match."
    lines = [f"  {lbl} @ {a1}: copy={cv!r} VA={vv!r}"
             for lbl, a1, cv, vv in mm[:max_lines]]
    if len(mm) > max_lines:
        lines.append(f"  …and {len(mm) - max_lines} more value diff(s)")
    lines += [f"  ROW only on VA: {s}" for s in ov[:15]]
    lines += [f"  ROW only on copy: {s}" for s in oc[:15]]
    return head + "\n" + "\n".join(lines)


def main():
    """Standalone full comparison: copy tab vs the live VA tab, EVERY finding
    written to a pullable log. The mini's Mini-Control result cell truncates to
    ~480 chars, so the on-screen tail can't show a full glitch list — this writes
    output/logs/org_sales_board_compare-<stamp>.log, read via
    `lucy logtail org_sales_board_compare`. Read-only (sheet vs sheet); safe
    any time. Always exits 0 — a compare difference is a finding, not a crash."""
    import datetime as _dt
    import sys as _sys
    from pathlib import Path as _P
    logdir = _P(__file__).resolve().parents[2] / "output" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)

    # `--content`: position-independent content match — every labeled row keyed
    # by its A/B label and compared wherever it sits. Answers "does the CONTENT
    # match?" (Megan 2026-07-07: "I want the CONTENT to be matching, not the
    # locations.").
    if "--content" in _sys.argv:
        d = content_diff()
        stamp = _dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
        out = logdir / f"org_sales_board_content-{stamp}.log"
        mm = d["mismatches"]
        body = [f"ORG SALES BOARD — CONTENT (position-independent) DIFF {stamp}",
                f"labeled rows: copy={d['copy_labeled']} va={d['va_labeled']} | "
                f"matched 1:1={d['matched_rows']} | ambiguous(dup label)={d['ambiguous_labels']}",
                f"CONTENT MISMATCHES (same label, different value): {len(mm)}",
                f"labels only on copy: {len(d['only_copy'])} | "
                f"labels only on VA: {len(d['only_va'])}",
                "", "== CONTENT MISMATCHES (label @ cell: copy | VA) =="]
        body += [f"  {lbl} @ {a1}: {cv!r} | {vv!r}" for lbl, a1, cv, vv in mm]
        body += ["", "== LABELS ONLY ON COPY ==", *[f"  {s}" for s in d["only_copy"]],
                 "", "== LABELS ONLY ON VA ==", *[f"  {s}" for s in d["only_va"]]]
        out.write_text("\n".join(body), encoding="utf-8")
        print(f"content-diff -> {out.name} | matched {d['matched_rows']} rows | "
              f"CONTENT MISMATCHES={len(mm)} | only-copy={len(d['only_copy'])} "
              f"only-va={len(d['only_va'])} ambiguous={d['ambiguous_labels']} | "
              + ("CONTENT MATCHES ✓" if not mm else f"{len(mm)} content cell(s) differ"))
        print("=== done ===")
        return 0

    # `--every-cell`: exhaustive raw diff of the two whole tabs (answers "is
    # EVERY single cell identical?", not the region-scoped audit below).
    if "--every-cell" in _sys.argv:
        d = every_cell_diff()
        b = d["band_at"]
        cn = d["counts"]
        g = lambda band, kind: cn.get((band, kind), 0)
        stamp = _dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
        out = logdir / f"org_sales_board_everycell-{stamp}.log"
        bd = d["both_differ"]
        bd_below = [x for x in bd if x[3] < b]
        bd_at = [x for x in bd if x[3] >= b]
        body = [f"ORG SALES BOARD — EVERY-CELL RAW DIFF {stamp}",
                f"copy rows={d['copy_rows']} va rows={d['va_rows']}", "",
                f"ROWS BELOW {b}:  copy-blank={g('below','copy-blank')} "
                f"va-blank={g('below','va-blank')} "
                f"BOTH-DIFFER={g('below','both-differ')}",
                f"ROWS {b}+:      copy-blank={g('atplus','copy-blank')} "
                f"va-blank={g('atplus','va-blank')} "
                f"BOTH-DIFFER={g('atplus','both-differ')}", "",
                "Only BOTH-DIFFER = a real data conflict; blanks are structural "
                "(the tabs aren't mirror layouts).", "",
                f"== BOTH-DIFFER, rows below {b} ({len(bd_below)}) (cell: copy | VA) =="]
        body += [f"  {a1}: {cv!r} | {vv!r}" for a1, cv, vv, _r in bd_below]
        body += ["", f"== BOTH-DIFFER, rows {b}+ ({len(bd_at)}) =="]
        body += [f"  {a1}: {cv!r} | {vv!r}" for a1, cv, vv, _r in bd_at]
        out.write_text("\n".join(body), encoding="utf-8")
        nreal = len(bd)
        print(f"every-cell -> {out.name} | below {b}: "
              f"both-differ={g('below','both-differ')} "
              f"(copy-blank {g('below','copy-blank')}, va-blank {g('below','va-blank')}) "
              f"| {b}+: both-differ={g('atplus','both-differ')} "
              f"| TOTAL real conflicts={nreal}")
        print("=== done ===")
        return 0

    res = run_compare()
    try:
        stamp = _dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
        out = logdir / f"org_sales_board_compare-{stamp}.log"
        buckets = [
            ("GLITCHES (va_ahead / mismatch — automation behind or wrong)",
             res.get("glitches", [])),
            ("DERIVED total-table concerns (current week)",
             res.get("derived", [])),
            ("COPY MISSING (ICD on VA tab, no copy row)",
             res.get("copy_missing", [])),
            ("FORMULA DRIFT (a live VA formula got clobbered)",
             res.get("formula_drift", [])),
        ]
        body = [f"ORG SALES BOARD — FULL COMPARE {stamp} — clean={res['clean']}",
                f"tally={res.get('tally', {})}", ""]
        for title, items in buckets:
            body.append(f"== {title}: {len(items)} ==")
            body += [f"  {it}" for it in items]
            body.append("")
        out.write_text("\n".join(str(x) for x in body), encoding="utf-8")
        print(f"full compare -> {out.name} | "
              f"{len(res.get('glitches', []))} glitch, "
              f"{len(res.get('derived', []))} derived, "
              f"{len(res.get('copy_missing', []))} copy-missing, "
              f"{len(res.get('formula_drift', []))} formula-drift")
    except Exception as e:  # noqa: BLE001 — the log is best-effort
        print(f"(couldn't write full-compare log: {type(e).__name__}: {e})")
    print("=== done ===")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
