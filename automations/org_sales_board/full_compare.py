"""Full-cell value check of the DERIVED / bottom auto-formula tables — the cells
compare.py's data pass never reaches: captainship + ALPHALETE-ORG leaderboards,
the per-rep DELTA tables, the ORG/campaign 'this week' history rows, the
captainship product summaries, and the section running totals.

Two independent checks, CURRENT-WEEK cells ONLY (the frozen prior-week history is
maintained separately on each tab, so comparing it is pure noise — a copy that's
rolled at a different moment than the VA will differ on 2 years of static weeks):

copy-vs-VA — every derived this-week cell, name-matched where the region is sorted
(leaderboards, delta rows — the two tabs sort differently), positional where it's
label-anchored (history/summary rows sit in identical rows). Buckets:
    • copy_ahead (copy > VA)  — automation more current than the hand-entry.
      BENIGN mid-week (the VAs always lag); counted, not listed. A systematic raw
      over-count (e.g. the Retail-NL 'counting upgrades' bug, 2026-07-03) is caught
      by compare.py's RAW pass, not here.
    • va_ahead / mismatch     — automation total SHORT of / disagreeing with the VA.
      CONCERNING — this is where a wrong SUMIF (the old =F Monday-only 'Total this
      week') surfaces as a short total.

NOTE: a VA-independent internal-consistency check (Total == sum of its own day
cells) was tried and REMOVED — the finders' rightmost value column includes
non-day columns (running / prior-week totals), so a generic grand-total-vs-daysum
check false-positives. Re-add only with exact per-table column maps.

Read-only — reads both tabs, writes nothing. [[project_org_sales_board]]
[[feedback_read_actual_content]] [[feedback_flag_nonmatched_icds]]
"""
from __future__ import annotations

from typing import List

from gspread.utils import rowcol_to_a1

from automations.org_sales_board import rollover, fill_section as fs, captainship as cap
from automations.alphalete_org_report.tableau_http import _norm_owner

SECTIONS = ["Retail NL", "Retail Internet", "ATT Fiber Team",
            "ATT NDS Team", "B2B", "BOX"]
_ZERO = (None, "", 0, 0.0, "0", "0.0", "0%", "0.00%")


def _u(g, r1, c1):
    return g[r1 - 1][c1 - 1] if r1 - 1 < len(g) and c1 - 1 < len(g[r1 - 1]) else ""


def _bname(g, r1):
    return (g[r1 - 1][1] if r1 - 1 < len(g) and 1 < len(g[r1 - 1]) else "").strip()


def _acell(g, r1):
    return (g[r1 - 1][0] if r1 - 1 < len(g) and len(g[r1 - 1]) else "").strip()


def _num(x):
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip().replace(",", "").replace("%", "").replace("$", "")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _classify(c, v):
    """copy computed `c` vs VA computed `v` -> bucket."""
    cs = str(c).strip() if c is not None else ""
    vs = str(v).strip() if v is not None else ""
    if cs == vs:
        return "exact"
    if cs.upper() == "NS" and v in _ZERO:
        return "ns0"
    if c in _ZERO and v in _ZERO:
        return "blank"
    cn, vn = _num(c), _num(v)
    if cn is not None and vn is not None:
        if cn == vn:
            return "exact"
        return "copy_ahead" if cn > vn else "va_ahead"
    return "mismatch"


def run_derived_compare(sh, cS, vS, aliases, logfn=print) -> dict:
    """cS/vS = FORMATTED grids of copy (SANDBOX) + VA (PROD) tabs, already read by
    the caller. Fetches the UNFORMATTED (computed) grids itself. Returns
    {concerning, benign_count, inconsistent, clean}."""
    from automations.org_sales_board.run import SANDBOX_TAB, PROD_TAB
    from automations.recruiting_report.fill import _retry
    cU = _retry(lambda: sh.worksheet(SANDBOX_TAB).get_all_values(
        value_render_option="UNFORMATTED_VALUE"))
    vU = _retry(lambda: sh.worksheet(PROD_TAB).get_all_values(
        value_render_option="UNFORMATTED_VALUE"))

    concerning: List[tuple] = []     # (region, label, a1, copy, va, bucket)
    benign = 0

    def candidates(name):
        return set(fs._candidates_for(name, aliases))

    def match_row(name, pool):
        for k in candidates(name):
            if k in pool:
                return pool[k]
        return None

    def cmp_cell(region, label, cr, c1, vr=None):
        nonlocal benign
        vr = vr if vr is not None else cr
        cc, vv = _u(cU, cr, c1), _u(vU, vr, c1)
        b = _classify(cc, vv)
        if b in ("exact", "ns0", "blank"):
            return
        if b == "copy_ahead":
            benign += 1
            return
        concerning.append((region, label, rowcol_to_a1(cr, c1), cc, vv, b))

    # ---------- NAME-ANCHORED regions (current-week column only) ----------
    # Section running totals
    for lbl in SECTIONS:
        try:
            ca = fs.find_daily_section(cS, lbl)
            va = fs.find_daily_section(vS, lbl)
        except Exception:
            continue
        vpool = {_norm_owner(n): r for n, r in va.icd_rows.items()}
        for name, r in ca.icd_rows.items():
            vr = match_row(name, vpool)
            if vr is None:
                continue
            cmp_cell(f"section {lbl!r} running-total", name, r,
                     ca.running_total_col, vr)

    # Captainship leaderboards (col C this-week total)
    try:
        caps = [t for t, _hint in cap.discover_captainships(cS)]
    except Exception:
        caps = []
    for t in caps:
        try:
            ca = cap.find_captainship(cS, t)
            va = cap.find_captainship(vS, t)
        except Exception:
            continue
        vpool = {_norm_owner(n): r for r, n in va.leaderboard}
        for r, name in ca.leaderboard:
            vr = match_row(name, vpool)
            if vr is None:
                continue
            cmp_cell(f"{t} leaderboard total", name, r, ca.week_total_col, vr)

    # ALPHALETE ORG leaderboard (col C this-week)
    try:
        ob_c = rollover.find_org_block(cS)
        ob_v = rollover.find_org_block(vS)
        vpool = {_norm_owner(_bname(vS, r)): r for r in ob_v.data_rows}
        for r in ob_c.data_rows:
            name = _bname(cS, r)
            vr = match_row(name, vpool)
            if vr is None:
                continue
            cmp_cell("ORG leaderboard this-week", name, r, ob_c.first_col, vr)
    except Exception as e:  # noqa: BLE001
        logfn(f"  ⚠ ORG leaderboard skipped ({str(e)[:50]})")

    # DELTA tables — 'Total this week' (col C) + this-week per-day cols; and the
    # internal-consistency check (col C == sum of the per-day This-week cols).
    v_deltas = {d["header_row"]: d for d in rollover.find_delta_tables(vS)}
    for t in rollover.find_delta_tables(cS):
        vt = v_deltas.get(t["header_row"])
        vpool = ({_norm_owner(_bname(vS, r)): r for r in vt["data_rows"]}
                 if vt else {})
        for r in t["data_rows"]:
            name = _bname(cS, r)
            if not name:
                continue
            vr = match_row(name, vpool) if vt else None
            if vr is None:
                continue
            for c1 in [3] + t["this_cols"]:
                cmp_cell(f"delta@{t['header_row']}", name, r, c1, vr)

    # ---------- POSITIONAL regions (label-anchored, current-week row only) ----------
    def pos_row(region, r, day_cols, gt_col):
        label = _acell(cS, r) or _bname(cS, r)
        for c1 in day_cols + [gt_col]:
            cmp_cell(region, label, r, c1)

    for h in rollover.find_org_history_tables(cS):
        pos_row("ORG history this-week", h["this"],
                list(range(h["c0"], h["cN"])), h["cN"])
    for h in rollover.find_campaign_history_tables(cS):
        pos_row("campaign this-week", h["this"],
                list(range(h["c0"], h["cN"])), h["cN"])
    for s in rollover.find_captainship_product_summaries(cS):
        pos_row("product-summary this-week", s["totals_row"],
                s["day_cols"], s["gt_col"])

    clean = not concerning
    _report(logfn, concerning, benign, clean)
    return {"concerning": concerning, "benign_count": benign, "clean": clean}


def _report(logfn, concerning, benign, clean):
    logfn(f"  --- DERIVED / BOTTOM AUTO-FORMULA TABLES (current-week) ---")
    if concerning:
        logfn(f"  ❌ {len(concerning)} derived cell(s) where the automation total is "
              f"SHORT of / disagrees with the VA (va_ahead/mismatch):")
        for region, label, a1, c, v, b in concerning[:40]:
            logfn(f"      [{region}] {label} {a1}: copy={c!r} VA={v!r}  ({b})")
        if len(concerning) > 40:
            logfn(f"      …and {len(concerning) - 40} more")
    if benign:
        logfn(f"  ℹ {benign} derived cell(s) where the copy is AHEAD of the VA "
              f"(automation more current — benign mid-week lag, not gated).")
    if clean:
        logfn("  ✅ every derived this-week total matches the VA "
              "(or the copy is ahead — benign).")
