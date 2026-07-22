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


def check_formula_drift(cS, vS, aliases, logfn=print, live_cells=None) -> list:
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

    `live_cells` (optional): the set of (copy_row, 1-based_col) the derived
    compare GATES as current-week — full_compare's `gated` set. When given, only
    drift on THOSE cells gates; drift on frozen prior-week / history cells (where
    the copy legitimately froze a past =SUM/=SUMIF to a static value the VA still
    keeps live, and the two tabs roll at different moments) is logged REPORT-ONLY
    and NOT returned. Without it, every drift cell is returned (old behavior).
    Read-only. Returns the GATING flagged cell list."""
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
    # Split into GATING (current-week live cells) vs report-only (frozen/history).
    if live_cells is not None:
        frozen = [f for f in flagged if (f[0], f[1]) not in live_cells]
        flagged = [f for f in flagged if (f[0], f[1]) in live_cells]
        if frozen:
            logfn(f"  ℹ {len(frozen)} formula-vs-static diff(s) on FROZEN prior-week/"
                  f"history cells (report-only, not gated — the two tabs roll them "
                  f"at different moments).")
    if flagged:
        logfn(f"  ❌ FORMULA DRIFT — {len(flagged)} current-week cell(s) the report "
              f"wrote as a static value where the VA tab keeps a live formula "
              f"(formula clobbered — it'll freeze/drift):")
        for r, c, lbl, cc, vv in flagged[:30]:
            from gspread.utils import rowcol_to_a1
            logfn(f"      {rowcol_to_a1(r, c)} [{lbl[:24]}] static={cc[:14]!r} "
                  f"expected formula={vv[:40]!r}")
        if len(flagged) > 30:
            logfn(f"      …and {len(flagged) - 30} more")
    else:
        logfn("  ✅ no formula drift — every current-week VA formula cell is still "
              "a live formula on the copy.")
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
    # DERIVED / bottom auto-formula tables (leaderboards, delta tables, ORG +
    # campaign history rows, product summaries, section running totals). The value
    # compare above only reaches the raw daily cells; this reaches the totals a
    # wrong SUMIF would break (the old =F Monday-only 'Total this week'). Its own
    # SEPARATE bucket, current-week only, name-matched where sorted. Wrapped so a
    # bug in the new check can never crash the daily run's compare. Runs BEFORE the
    # formula-drift check so its `gated` set (the current-week cells the gate
    # covers) can scope the drift check to live cells only.
    try:
        from automations.org_sales_board import full_compare as _fc
        derived = _fc.run_derived_compare(sh, copy, va, aliases, logfn)
    except Exception as e:  # noqa: BLE001
        logfn(f"  ⚠ derived-table compare skipped ({type(e).__name__}: {str(e)[:60]})")
        derived = {"concerning": [], "benign_count": 0, "clean": True, "gated": None}
    # Formula-region integrity: catch any live VA formula the report clobbered
    # with a static value (separate from the value compare above). Scoped to the
    # derived compare's current-week `gated` cells so frozen prior-week history
    # (static-on-copy where the VA kept a live =SUM) doesn't false-flag.
    formula_drift = check_formula_drift(copy, va, aliases, logfn,
                                        live_cells=derived.get("gated"))
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
                if c == 0 and _rankish(cv) and _rankish(vv):
                    continue   # col-A = rank/marker (digit, blank, '*'), not data
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


def exhaustive_diff() -> dict:
    """THE GO-LIVE GATE: every single cell of the copy tab vs the VA tab, rows 1..end
    — INCLUDING rows past 1000 (Megan has asked for this repeatedly) — with a FULL
    coverage accounting so nothing can hide.

    Every non-empty row is either paired to its VA twin BY CONTENT (col-A label +
    col-B name, occurrence by occurrence — the leaderboards sort differently, so row
    N on the copy is NOT row N on the VA) or reported as UNPAIRED. Label-less rows
    (spacers/strips with no name to key on) are compared POSITIONALLY so they are
    not left unchecked either.

    HARD GUARD: two rows are never compared unless their label+name are identical.
    Without it a positional fallback lined 'Kash Rai' up against 'Cyrus Wade' and
    invented ~200 differences that did not exist (2026-07-14).

    Values compare NUMERICALLY: 2 == 2.0 == '2', and blank == 0 == 'NS' (all three
    mean 'no sale'). Col A is skipped — it's the rank, re-ranked every run by design.

    Returns {compared, diffs, only_copy, only_va, labelless_rows, labelless_diffs,
    total} — total == 0 means EVERY cell matches."""
    import collections
    from gspread.utils import rowcol_to_a1
    from automations.org_sales_board import full_compare as _fc

    sh = open_by_key(SHEET_ID)
    cS = _retry(sh.worksheet(SANDBOX_TAB).get_all_values)
    vS = _retry(sh.worksheet(PROD_TAB).get_all_values)
    cU = _retry(lambda: sh.worksheet(SANDBOX_TAB).get_all_values(
        value_render_option="UNFORMATTED_VALUE"))
    vU = _retry(lambda: sh.worksheet(PROD_TAB).get_all_values(
        value_render_option="UNFORMATTED_VALUE"))

    def nonempty(g, r):
        return any(str(x).strip() for x in (g[r - 1] if r - 1 < len(g) else []))

    def norm(x):
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s.upper() in ("", "NS"):
            return 0.0            # blank / 0 / NS all mean "no sale"
        try:
            f = float(s.replace(",", "").replace("$", "").rstrip("%"))
            return f / 100.0 if s.endswith("%") else f
        except ValueError:
            return s.lower()

    def cell(U, r, c):
        return U[r - 1][c - 1] if r - 1 < len(U) and c - 1 < len(U[r - 1]) else ""

    ci, vi = collections.defaultdict(list), collections.defaultdict(list)
    for r in range(1, len(cS) + 1):
        if nonempty(cS, r):
            ci[_fc._row_sig(cS, r)].append(r)
    for r in range(1, len(vS) + 1):
        if nonempty(vS, r):
            vi[_fc._row_sig(vS, r)].append(r)

    pairs, only_copy, only_va, labelless = [], [], [], []
    for s, crows in ci.items():
        if s == ("", ""):                       # no label -> can't key by content
            labelless.extend(crows)
            continue
        vrows = vi.get(s, [])
        pairs += list(zip(crows, vrows))
        only_copy += crows[len(vrows):]
    for s, vrows in vi.items():
        if s != ("", ""):
            only_va += vrows[len(ci.get(s, [])):]

    for cr, vr in pairs:                        # the guard
        if _fc._row_sig(cS, cr) != _fc._row_sig(vS, vr):
            raise AssertionError(f"pairing guard: copy r{cr} vs VA r{vr}")

    compared, diffs = 0, []
    for cr, vr in pairs:
        w = max(len(cU[cr - 1]) if cr - 1 < len(cU) else 0,
                len(vU[vr - 1]) if vr - 1 < len(vU) else 0)
        for c in range(2, w + 1):               # skip col A (rank)
            cv, vv = cell(cU, cr, c), cell(vU, vr, c)
            compared += 1
            if norm(cv) != norm(vv):
                nm = (cS[cr - 1][1] if len(cS[cr - 1]) > 1 else "") or \
                     (cS[cr - 1][0] if cS[cr - 1] else "")
                diffs.append((rowcol_to_a1(cr, c), cr, vr, nm, cv, vv))

    ll_diffs = []
    for r in labelless:                          # positional (tabs are same shape)
        w = max(len(cU[r - 1]) if r - 1 < len(cU) else 0,
                len(vU[r - 1]) if r - 1 < len(vU) else 0)
        for c in range(2, w + 1):
            cv, vv = cell(cU, r, c), cell(vU, r, c)
            compared += 1
            if norm(cv) != norm(vv):
                ll_diffs.append((rowcol_to_a1(r, c), r, r, "(no label)", cv, vv))

    total = len(diffs) + len(ll_diffs) + len(only_copy) + len(only_va)
    return {"compared": compared, "diffs": diffs, "only_copy": only_copy,
            "only_va": only_va, "labelless_rows": len(labelless),
            "labelless_diffs": ll_diffs, "pairs": len(pairs),
            "copy_rows": len(cS), "va_rows": len(vS), "total": total}


def _fnum(s: str):
    try:
        return float(str(s).replace(",", "").rstrip("%"))
    except (ValueError, TypeError):
        return None


def _rankish(s: str) -> bool:
    """col-A content that is a rank/marker, never real data: blank, a bare
    integer, an '=A+1' rank formula, or a pure-symbol marker like '*'."""
    import re
    s = (s or "").strip()
    return (s == "" or s.isdigit() or s.startswith("=")
            or bool(re.fullmatch(r"[\W_]+", s)))


_ACRONYMS = {"Je": "JE", "Nl": "NL", "B2B": "B2B", "Nds": "NDS", "Box": "BOX",
             "Att": "ATT", "Org": "ORG", "Pp": "PP", "Dd": "DD", "Opt": "OPT"}
# col-B row labels that are auto-recomputed rollups, not rep data — collapsed in
# the detail so the email leads with the actual per-rep differences.
_ROLLUP = {"totals", "grand total", "all totals", "sales - this week",
           "vs prior week", "vs 4 weekavg", "sales (last week)",
           "sales ( 4 week avg)"}


def _pretty(name: str) -> str:
    """Title-case a row label but keep report acronyms upper (Retail JE, B2B…)."""
    out = " ".join(_ACRONYMS.get(w, w) for w in name.title().split())
    return out


_TABLEAU_BASE = "https://us-east-1.online.tableau.com/#/site/sci/views/"


def _source_view_url(s) -> str:
    if s.label == "Retail JE":
        from automations.org_sales_board import je_pull
        return je_pull.CV_URL                    # the pinned custom-view URL
    if s.workbook and s.view:
        return f"{_TABLEAU_BASE}{s.workbook}/{s.view}"
    return ""                                    # Frontier = emailed PDF, no view


def _section_url(grid, r0):
    """The Tableau source-view URL for the daily section a row sits in — found
    by walking UP to the nearest section-title cell that matches a registered
    Source label. Each daily section names itself in col A (e.g. 'Retail JE' on
    the day-header row); the top product-summary block names them in col B — so
    check BOTH. '' when none is found. NOTE: callers pass '' for org-level
    rollup rows so they don't wrongly inherit the section title sitting above
    them in the summary block."""
    from automations.org_sales_board import sources as _src
    labels = {s.label.lower(): s for s in _src.DAILY_SOURCES}
    for rr in range(r0, max(-1, r0 - 45), -1):
        row = grid[rr] if rr < len(grid) else []
        for ci in (0, 1):                        # col A (section header) then col B
            s = labels.get((row[ci] if len(row) > ci else "").strip().lower())
            if s:
                return _source_view_url(s)
    return ""


def _col_header(grid, r0, c):
    """Human label for a cell's COLUMN — the nearest header text above it in the
    same column (a weekday name, 'Running Week Totals', 'Grand Total',
    'WE 07.12', …). '' when none within reach (e.g. leaderboard total columns)."""
    import re
    for rr in range(r0 - 1, max(-1, r0 - 16), -1):
        v = (grid[rr][c] if rr < len(grid) and c < len(grid[rr]) else "").strip()
        if v and re.search(r"[A-Za-z]", v):
            return " ".join(v.split())
    return ""


# Row labels / column headers that mark a cell as DERIVED-from-frozen-history —
# a %-change or a prior-week baseline the two tabs maintain and roll INDEPENDENTLY,
# so a copy-vs-VA difference there is expected (different roll moments), not a data
# error. full_compare.py already treats these as report-only for the GATE; the
# email must too, or a week-rollover day flags hundreds of benign delta cells as
# "needs a look" (Megan 2026-07-15: the rollover deltas are the real glitch — a
# week-boundary artifact, not bad numbers).
_REPORT_ONLY_MARKERS = ("delta", "vs prior", "vs 4", "weekavg", "4 week avg",
                        "4 weekavg", "last week", "prior week", "weeks prior")


def _we_md(col: str):
    """(month, day) parsed from a 'WE 07.19' / 'WE 7.5' column header, else None."""
    import re
    m = re.match(r"\s*we\s+(\d{1,2})[./](\d{1,2})", (col or "").lower())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _is_report_only(label: str, col: str, cv: str, vv: str,
                    current_we=None) -> bool:
    """True for a %-change / frozen prior-week cell whose divergence is a rollover
    artifact, not a data glitch — surfaced informationally, never counted toward
    'needs a look'. A RAW current-week integer in a weekday/total column is NOT
    report-only and still counts — and, crucially, neither is the CURRENT week's
    'WE mm.dd' column (only PAST 'WE' columns are frozen history; matching the
    live week here would hide a real current-week undercount from the email)."""
    lab, c = (label or "").lower(), (col or "").lower()
    if any(k in lab for k in _REPORT_ONLY_MARKERS):
        return True
    if (c.startswith("vs ") or "delta" in c or "%" in c
            or "last week" in c or "4 week" in c or "prior" in c):
        return True
    we = _we_md(c)                           # a 'WE mm.dd' column?
    if we is not None and we != current_we:  # a PAST week's frozen history only
        return True
    if "%" in (cv or "") or "%" in (vv or ""):
        return True
    for x in (cv, vv):                       # a fractional ratio = a %-change raw
        try:
            f = float(str(x).replace(",", ""))
            if f != int(f):
                return True
        except (ValueError, TypeError):
            pass
    return False


def breakdown(cd: dict | None = None) -> dict:
    """Categorized copy-vs-VA comparison for the daily summary email — built on
    top of the proven content_diff() (name-matched within sections, frozen
    prior-week history excluded, no-sale/rank differences already filtered).

    Each surviving mismatch is bucketed by severity AND enriched with a plain
    COLUMN LABEL (day name / 'Grand Total' / etc.) and a flag for whether the row
    is an auto-recomputed rollup, so the renderer can group by rep and read
    clearly instead of listing raw cell coordinates. Buckets:
      copy_missing — VA has a value, copy blank  (ATTENTION)
      behind       — both numeric, copy < VA     (ATTENTION)
      conflict     — both populated, non-numeric differ (ATTENTION)
      ahead        — copy > VA, or copy has a value the VA hasn't keyed (benign)
      report_only  — %-change / frozen prior-week baseline (rollover artifact —
                     informational, NOT counted toward attention)

    `cd` lets a caller pass a content_diff() it already computed."""
    from gspread.utils import a1_to_rowcol
    from automations.org_sales_board import week as _wk
    d = cd if cd is not None else content_diff()
    grid = _retry(open_by_key(SHEET_ID).worksheet(SANDBOX_TAB).get_all_values)
    _sun = _wk.reporting_sunday(dt.date.today())      # the LIVE week-ending
    current_we = (_sun.month, _sun.day)               # never treat this WE as frozen
    b = {k: [] for k in ("ahead", "behind", "conflict", "copy_missing",
                         "report_only")}
    for label, cell, cv, vv in d.get("mismatches", []):
        raw = label.split("|")[-1].strip()
        name = _pretty(raw[:40] or label[:40])
        rollup = raw.lower() in _ROLLUP
        r, c = a1_to_rowcol(cell)
        col = _col_header(grid, r - 1, c - 1)
        # org-level rollups aggregate every section — don't inherit the section
        # title that happens to sit above them in the summary block.
        url = "" if rollup else _section_url(grid, r - 1)
        rec = (name, cell, cv, vv, col, rollup, url)
        # A %-change / frozen prior-week cell rolls independently on each tab —
        # report it, never gate on it (mirrors full_compare's report-only split).
        if _is_report_only(label, col, cv, vv, current_we):
            b["report_only"].append(rec)
            continue
        cempty = cv.lower() in ("", "0", "ns")
        vempty = vv.lower() in ("", "0", "ns")
        if cempty and not vempty:
            b["copy_missing"].append(rec)          # VA has it, copy blank
        elif vempty and not cempty:
            b["ahead"].append(rec)                 # copy ahead of the VA
        else:
            nc, nv = _fnum(cv), _fnum(vv)
            if nc is not None and nv is not None:
                b["ahead" if nc > nv else "behind"].append(rec)
            else:
                b["conflict"].append(rec)
    only_va, only_copy = d.get("only_va", []), d.get("only_copy", [])
    attention = (len(b["behind"]) + len(b["conflict"]) + len(b["copy_missing"])
                 + len(only_va) + len(only_copy))
    return {"matched": d.get("matched_rows", 0), "only_va": only_va,
            "only_copy": only_copy, "attention": attention, **b}


_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday")


def _guess_reason(bucket: str, col: str, cv: str, vv: str) -> str:
    """A best-effort GUESS at why a cell differs, for the email's reason column.
    Heuristic only (never authoritative) — phrased so a reader knows it's a
    guess."""
    c = (col or "").strip().lower()
    is_day = any(wd in c for wd in _WEEKDAYS)
    is_total = "total" in c or c.startswith("we ")
    is_pct = "%" in (cv or "") or "%" in (vv or "") or c.startswith("vs ")
    va_blank = vv.strip().lower() in ("", "0", "ns")
    if bucket == "copy_missing":
        return "Likely a missed pull — the VA has this sale, the automation doesn't. Check the source view."
    if bucket == "behind":
        return "Automation is lower than the VA — possible undercount. Check the source view."
    if bucket == "conflict":
        return "The two tabs disagree — check the source view."
    # ahead (benign)
    if is_pct:
        return "A percentage that recalculated off the more-current numbers."
    if va_blank and is_day:
        return f"VA hasn't hand-entered {col} yet — the automation already pulled it."
    if is_total:
        return "Automation is more current — includes a day the VA hasn't added yet."
    return "Automation pulled a more recent number than the hand-entry."


def format_breakdown_html(d: dict, max_rows: int = 40) -> str:
    """Render breakdown() as a simple Excel-style table for the emails:
    4 columns — Category | VA tab | Automation tab | Likely reason — one row
    per real difference (rep-level cells; the auto-recomputed section/org totals
    are collapsed to a single footnote). Rows are colored by type: red = needs a
    look (VA has something the copy misses, or the copy is behind), plain = the
    copy is just more current than the hand-entry. Green banner when in sync."""
    def eb(x):
        return _esc(x) if x else "(blank)"

    # Flatten to table rows: (category, va, copy, attention?, reason). Group per
    # row NAME and dedupe by value so a rep's 'week total' shows ONCE. Rep-data
    # rows and the auto-recomputed rollup rows are returned SEPARATELY so the
    # table can lead with the real per-rep differences and list the derived
    # totals/percentages under their own separator.
    def rows_for(items, attention, bucket):
        reps, rolls = [], []
        r_order, r_per, k_order, k_per = [], {}, [], {}
        for nm, cell, cv, vv, col, rollup, url in items:
            order, per = (k_order, k_per) if rollup else (r_order, r_per)
            if nm not in per:
                per[nm] = {}
                order.append(nm)
            k = (cv, vv)
            if k not in per[nm]:
                per[nm][k] = (col or "Week total", cv, vv, url)
            else:                                # merge dup: keep best label + a url
                plbl, pcv, pvv, purl = per[nm][k]
                per[nm][k] = (col or plbl or "Week total", pcv, pvv, purl or url)
        for order, per, is_roll in ((r_order, r_per, False), (k_order, k_per, True)):
            bucket_rows = rolls if is_roll else reps
            for nm in order:
                for lbl, cv, vv, url in per[nm].values():
                    cat = f"{nm} — {lbl}" if lbl else nm
                    reason = ("Auto-recalculated total/percentage — reflects the "
                              "rep rows above." if is_roll
                              else _guess_reason(bucket, lbl, cv, vv))
                    bucket_rows.append((cat, vv, cv, attention, reason, url))
        return reps, rolls

    table_rows, rollup_rows = [], []
    for key, attn in (("copy_missing", True), ("behind", True),
                      ("conflict", True), ("ahead", False)):
        reps, rolls = rows_for(d.get(key, []), attn, key)
        table_rows += reps
        rollup_rows += rolls
    for s in d.get("only_va", []):
        table_rows.append((f"Row only on VA — {s}", "(row present)", "(missing)",
                           True, "Row on the VA only — likely a name/marker mismatch, not missing data.", ""))
    for s in d.get("only_copy", []):
        table_rows.append((f"Row only on copy — {s}", "(missing)", "(row present)",
                           True, "Row on the copy only — likely a name/marker mismatch, not missing data.", ""))
    # %-change / prior-week baseline cells — informational only (rollover artifact)
    rr_reps, rr_rolls = rows_for(d.get("report_only", []), False, "report_only")
    report_rows = rr_reps + rr_rolls

    att = d.get("attention", 0)
    # A HUGE count isn't thousands of real errors — it's a STRUCTURAL misalignment:
    # almost always the VA tab rolled to the new week on Monday while the automation
    # still holds last week (it rolls Tuesday), so EVERY cell reads one column off and
    # the compare flags all of them. Suppress the scary wall (Megan 2026-07-13) — the
    # underlying numbers are fine; a real glitch day is dozens, not thousands.
    if att > 1000:
        return (
            "<h3 style='margin:10px 0 4px'>📊 Copy vs VA — comparison</h3>"
            "<div style='background:#fef9e7;border-left:4px solid #f39c12;"
            "padding:8px 10px;margin:6px 0;font-size:13px'>ℹ️ Cell-by-cell compare "
            f"suppressed: {att:,} differences across the whole sheet means the two "
            "tabs are <b>structurally misaligned</b>, not that thousands of numbers "
            "are wrong. This is almost always the <b>VA board rolling to the new week "
            "on Monday</b> while the automation still holds last week (it rolls "
            "Tuesday) — a one-column offset, so the numbers actually match. It "
            "realigns once both tabs are on the same week. (If it's still flagging "
            "thousands past Tuesday, the tabs genuinely need a look.)</div>")
    banner = ("<div style='background:#eafaf1;border-left:4px solid #27ae60;"
              "padding:8px 10px;margin:6px 0;font-size:13px'>✅ In sync — the "
              "automation tab matches the VA tab. The only differences are the "
              "automation being more current (VA not hand-entered yet).</div>"
              if att == 0 else
              f"<div style='background:#fdedec;border-left:4px solid #c0392b;"
              f"padding:8px 10px;margin:6px 0;font-size:13px'>⚠ {att} difference(s) "
              f"need a look (highlighted below).</div>")

    html = ["<h3 style='margin:10px 0 4px'>📊 Copy vs VA — comparison</h3>", banner]
    th = ("padding:5px 10px;border:1px solid #ccc;text-align:left;"
          "background:#f0f0f0;font-size:13px")
    td = "padding:4px 10px;border:1px solid #ddd;font-size:13px;vertical-align:top"
    tdr = td + ";color:#555"
    html.append("<table style='border-collapse:collapse;max-width:760px;width:100%'>"
                f"<tr><th style='{th}'>Category</th>"
                f"<th style='{th}'>VA tab</th>"
                f"<th style='{th}'>Automation tab</th>"
                f"<th style='{th}'>Likely reason (best guess)</th></tr>")
    def emit(rows):
        for cat, va, copy, attn, reason, url in rows:
            bg = "background:#fdecea" if attn else ""
            cat_html = _esc(cat)
            if url:
                cat_html += (f" <a href='{_esc(url)}' style='font-size:11px;"
                             f"color:#1a6fc4;text-decoration:none;white-space:nowrap'>"
                             f"(Tableau ↗)</a>")
            html.append(f"<tr style='{bg}'><td style='{td}'>{cat_html}</td>"
                        f"<td style='{td}'>{eb(va)}</td>"
                        f"<td style='{td}'>{eb(copy)}</td>"
                        f"<td style='{tdr}'>{_esc(reason)}</td></tr>")

    emit(table_rows[:max_rows])
    shown = min(len(table_rows), max_rows)
    if rollup_rows and shown < max_rows:
        html.append(f"<tr><td colspan='4' style='padding:5px 10px;border:1px solid "
                    f"#ccc;background:#f7f7f7;font-size:12px;color:#666'>"
                    f"Totals &amp; percentages — recomputed automatically from the "
                    f"rows above (shown for completeness):</td></tr>")
        emit(rollup_rows[:max_rows - shown])
    if report_rows:
        _rr_cap = 12
        html.append(f"<tr><td colspan='4' style='padding:5px 10px;border:1px solid "
                    f"#ccc;background:#eef4fb;font-size:12px;color:#557'>"
                    f"↺ Week-over-week %s &amp; prior-week baselines "
                    f"({len(report_rows)}) — the two tabs roll their frozen history "
                    f"independently, so these differ by design on a rollover day. "
                    f"Informational, <b>not</b> a data problem:</td></tr>")
        emit(report_rows[:_rr_cap])
    html.append("</table>")
    dropped = (len(table_rows) - shown) + max(0, len(rollup_rows) - max(0, max_rows - shown))
    if dropped > 0:
        html.append(f"<div style='font-size:12px;color:#888;margin:4px 0'>"
                    f"…and {dropped} more difference(s)</div>")
    if len(report_rows) > 12:
        html.append(f"<div style='font-size:12px;color:#889;margin:4px 0'>"
                    f"…and {len(report_rows) - 12} more informational "
                    f"%-change/baseline row(s)</div>")
    return "".join(html)


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


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

    # `--all`: THE GO-LIVE GATE. Every single cell, rows 1..end incl. past 1000,
    # content-matched, with a full coverage accounting (Megan 2026-07-14: "I want to
    # just make sure EVERY SINGLE cell is matching — that includes rows past 1000").
    # total == 0 means the copy tab matches the VA everywhere.
    if "--all" in _sys.argv:
        d = exhaustive_diff()
        stamp = _dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
        out = logdir / f"org_sales_board_everycell_all-{stamp}.log"
        alld = d["diffs"] + d["labelless_diffs"]
        over = [x for x in alld if x[1] >= 1000]
        body = [f"ORG SALES BOARD — EVERY SINGLE CELL (copy vs VA) {stamp}",
                f"copy rows={d['copy_rows']}  VA rows={d['va_rows']}",
                f"rows paired by content : {d['pairs']}",
                f"label-less rows        : {d['labelless_rows']} (compared positionally)",
                f"CELLS COMPARED         : {d['compared']}",
                f"CELLS DIFFERING        : {len(alld)}  "
                f"(rows<1000: {len(alld) - len(over)} | rows>=1000: {len(over)})",
                f"copy rows w/ no VA twin: {len(d['only_copy'])}",
                f"VA rows w/ no copy twin: {len(d['only_va'])}",
                "", "== EVERY DIFFERING CELL (cell | copyRow | vaRow | name | copy | VA) =="]
        body += [f"  {a1} | r{cr} | r{vr} | {nm[:24]} | {cv!r} | {vv!r}"
                 for a1, cr, vr, nm, cv, vv in alld]
        body += ["", "== COPY ROWS WITH NO VA TWIN ==",
                 *[f"  row {r}" for r in d["only_copy"]],
                 "", "== VA ROWS WITH NO COPY TWIN ==",
                 *[f"  row {r}" for r in d["only_va"]]]
        out.write_text("\n".join(body), encoding="utf-8")
        print(f"EVERY-CELL -> {out.name}")
        print(f"  cells compared = {d['compared']:,}  (rows paired {d['pairs']}, "
              f"label-less {d['labelless_rows']}, uncovered rows "
              f"{len(d['only_copy']) + len(d['only_va'])})")
        print(f"  CELLS DIFFERING = {len(alld)}  "
              f"(rows<1000: {len(alld) - len(over)} | rows>=1000: {len(over)})")
        for a1, cr, _vr, nm, cv, vv in alld[:40]:
            print(f"      {a1:<8} {nm[:22]:<22} copy={cv!r} VA={vv!r}")
        if len(alld) > 40:
            print(f"      …and {len(alld) - 40} more (full list in the log)")
        print("  ✅ EVERY SINGLE CELL MATCHES (incl. rows past 1000)"
              if d["total"] == 0 else
              f"  ❌ {d['total']} difference(s) — NOT yet 100% in line with the VA")
        print("=== done ===")
        return 0

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
    # This used to ALWAYS exit 0 ("a compare difference is a finding, not a crash")
    # — fine while it was a hand-run diagnostic. It is now a SCHEDULED 9am gate, and
    # an exit-0 with the done sentinel would let a REAL disagreement pass silently:
    # the orchestrator would mark it done and nobody would ever hear about it. So a
    # NOT-clean compare now fails the run, which surfaces it in the failure email
    # with the paste-to-Claude block. (Megan 2026-07-14.)
    #
    # This only fires on genuine problems. `clean` is False only for va_ahead /
    # mismatch / copy-missing / formula-drift — the automation being AHEAD of the VA
    # (copy_ahead) is explicitly NOT counted, so the ordinary mid-week state where
    # the VAs haven't finished keying stays green.
    if not res["clean"]:
        print("=== VA COMPARE FOUND REAL DIFFERENCES — the board disagrees with "
              "the VA tab (see the buckets above / the log). ===")
        return 1
    print("=== done ===")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
