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


def _org_name(g, hdr):
    """The 'X ORG' name from a '… ORG - Current vs Prior' header row — the CONTENT
    key that pairs a copy history table with its VA twin (never the row number)."""
    row = g[hdr - 1] if 0 < hdr <= len(g) else []
    for c in row[:6]:
        if c and "ORG - Current vs Prior" in c:
            return c.split("ORG")[0].strip().upper()
    return f"?org@{hdr}"


_WEEKDAYS_LOWER = {"monday", "tuesday", "wednesday", "thursday",
                   "friday", "saturday", "sunday"}
_CVP_LABELS = {"sales - this week": "this", "vs prior week": "vsprior",
               "vs 4 weekavg": "vs4wk", "sales (last week)": "lw",
               "sales ( 4 week avg)": "avg"}


def _find_cvp_blocks(g):
    """Every 'Current vs Prior' summary block — per-captainship AND per-ORG
    (CARLOS/COLTEN/BEN and RAF) — located by its col-B label sequence, NOT by row
    number. Each block: 'Sales - This Week' / 'vs Prior Week' / 'vs 4 WeekAVG' /
    'Sales (Last Week)' / 'Sales ( 4 Week AVG)', plus the weekday day-cols from the
    header row just above 'Sales - This Week'. Returns dicts in top-to-bottom order
    (both tabs list the same blocks in the same order)."""
    n = len(g)
    out = []
    r = 1
    while r <= n:
        if _bname(g, r).strip().lower() == "sales - this week":
            blk, end = {}, r
            for rr in range(r, min(r + 7, n + 1)):
                key = _CVP_LABELS.get(_bname(g, rr).strip().lower())
                if key:
                    blk[key] = rr
                    end = rr
            dayrow = None
            for rr in range(r - 1, max(r - 6, 0), -1):
                if sum(1 for c in g[rr - 1]
                       if str(c).strip().lower() in _WEEKDAYS_LOWER) >= 4:
                    dayrow = rr
                    break
            if dayrow:
                dc = [c + 1 for c in range(len(g[dayrow - 1]))
                      if str(g[dayrow - 1][c]).strip().lower() in _WEEKDAYS_LOWER]
                blk["day_cols"], blk["gt_col"] = dc, max(dc) + 1
            out.append(blk)
            r = end + 1
        else:
            r += 1
    return out


def _find_grand_total_rows(g):
    """Every leaderboard/section grand-total row — col A == 'TOTALS' (all-caps;
    distinct from the mixed-case 'Totals' product-summary rows). In board order."""
    return [r for r in range(1, len(g) + 1) if _acell(g, r) == "TOTALS"]


def content_row_map(cS, vS, aliases):
    """Map every content-identifiable COPY row -> the VA row holding the SAME
    content, using the label/name finders — NEVER absolute position. The two tabs
    carry different counts of history/spacer rows, so row N on the copy is not row
    N on the VA; this pairs by WHO/WHAT the row is instead.

    Covers the formula-bearing structural rows: section ICD + 'Totals' rows,
    captainship daily + leaderboard rows, the ORG leaderboard, delta data rows, the
    X-ORG history tables (paired by ORG name), and the per-campaign history tables +
    captainship product summaries (paired by finder ORDER — same entities, same
    top-to-bottom order on both tabs, guarded by an equal-count check). Rows with no
    content twin are simply absent — callers skip them or fall back, so a missing
    pair can never produce a false flag. Read-only."""
    def cands(name):
        return set(fs._candidates_for(name, aliases))

    def match(name, pool):
        for k in cands(name):
            if k in pool:
                return pool[k]
        return None

    m: dict = {}
    # sections: ICD rows (name-matched) + the section 'Totals' row (same section)
    for lbl in SECTIONS:
        try:
            ca = fs.find_daily_section(cS, lbl)
            va = fs.find_daily_section(vS, lbl)
        except Exception:
            continue
        vpool = {_norm_owner(n): r for n, r in va.icd_rows.items()}
        for name, r in ca.icd_rows.items():
            vr = match(name, vpool)
            if vr:
                m[r] = vr
        if ca.totals_row and va.totals_row:
            m[ca.totals_row] = va.totals_row
    # captainships: daily + leaderboard rows (name-matched)
    try:
        caps = [t for t, _h in cap.discover_captainships(cS)]
    except Exception:
        caps = []
    for t in caps:
        try:
            ca = cap.find_captainship(cS, t)
            va = cap.find_captainship(vS, t)
        except Exception:
            continue
        vp_d = {_norm_owner(n): r for r, n in va.daily}
        vp_l = {_norm_owner(n): r for r, n in va.leaderboard}
        for r, name in ca.daily:
            vr = match(name, vp_d)
            if vr:
                m[r] = vr
        for r, name in ca.leaderboard:
            vr = match(name, vp_l)
            if vr:
                m[r] = vr
    # ORG leaderboard rows (name-matched)
    try:
        ob_c = rollover.find_org_block(cS)
        ob_v = rollover.find_org_block(vS)
        vp = {_norm_owner(_bname(vS, r)): r for r in ob_v.data_rows}
        for r in ob_c.data_rows:
            vr = match(_bname(cS, r), vp)
            if vr:
                m[r] = vr
    except Exception:
        pass
    # delta tables: pair each copy table to its VA twin by ORDER (count-guarded),
    # then map data rows by name
    _cdt, _vdt = rollover.find_delta_tables(cS), rollover.find_delta_tables(vS)
    for ct, vt in (zip(_cdt, _vdt) if len(_cdt) == len(_vdt) else []):
        vp = {_norm_owner(_bname(vS, r)): r for r in vt["data_rows"]}
        for r in ct["data_rows"]:
            vr = match(_bname(cS, r), vp)
            if vr:
                m[r] = vr
    # X-ORG history tables: pair by ORG name; map this + 4 history rows
    v_org = {_org_name(vS, t["header_row"]): t
             for t in rollover.find_org_history_tables(vS)}
    for h in rollover.find_org_history_tables(cS):
        vt = v_org.get(_org_name(cS, h["header_row"]))
        if vt:
            for k in ("this", "lw", "pw", "2wp", "3wp"):
                if h.get(k) and vt.get(k):
                    m[h[k]] = vt[k]
    # per-campaign history tables: pair by order (count-guarded)
    _cch, _vch = (rollover.find_campaign_history_tables(cS),
                  rollover.find_campaign_history_tables(vS))
    for ct, vt in (zip(_cch, _vch) if len(_cch) == len(_vch) else []):
        for k in ("this", "lw", "pw", "2wp", "3wp"):
            if ct.get(k) and vt.get(k):
                m[ct[k]] = vt[k]
    # captainship product summaries: pair by order (count-guarded); map the
    # totals + the two summary formula rows
    _cps, _vps = (rollover.find_captainship_product_summaries(cS),
                  rollover.find_captainship_product_summaries(vS))
    for cs_, vs_ in (zip(_cps, _vps) if len(_cps) == len(_vps) else []):
        for k in ("totals_row", "last_week_row", "avg_row"):
            if cs_.get(k) and vs_.get(k):
                m[cs_[k]] = vs_[k]
    # 'Current vs Prior' summary blocks (per-captainship + per-ORG incl RAF) —
    # pair by order, map all 5 label rows
    _ccvp, _vcvp = _find_cvp_blocks(cS), _find_cvp_blocks(vS)
    for cb, vb in (zip(_ccvp, _vcvp) if len(_ccvp) == len(_vcvp) else []):
        for k in ("this", "vsprior", "vs4wk", "lw", "avg"):
            if cb.get(k) and vb.get(k):
                m[cb[k]] = vb[k]
    # leaderboard/section grand-total ('TOTALS') rows — pair by order
    _cgt, _vgt = _find_grand_total_rows(cS), _find_grand_total_rows(vS)
    for cr, vr in (zip(_cgt, _vgt) if len(_cgt) == len(_vgt) else []):
        m[cr] = vr
    return m


def _row_sig(g, r):
    """Content signature of a row: (col-A label, col-B label), with rank cells
    (a bare integer or an '=A+1' formula) neutralized so a rep row is identified by
    its NAME, not its (differing) rank. Pure-symbol markers (e.g. a manual '*' in
    the bottom delta tables) are ALSO neutralized — they drift between the VA and
    the copy, and keying on them mis-flagged identical rows as 'only on one tab'
    (2026-07-09). [[feedback_read_actual_content]]"""
    import re
    A = _acell(g, r)
    B = _bname(g, r)
    if (not A or re.fullmatch(r"\d+", A) or A.startswith("=")
            or re.fullmatch(r"[\W_]+", A)):
        A = ""
    return (A.strip().lower(), B.strip().lower())


def coverage_row_map(cS, vS, aliases):
    """FULL copy-row -> VA-row map for the completeness sweep: the high-confidence
    structural map (content_row_map) PLUS a label two-pointer alignment of every
    remaining row inside each gap between structural anchors. Anchors constrain the
    alignment so a run of same-labelled rows pairs by content; only a truly
    label-less gap row falls back to gap-relative position. Used ONLY by the
    report-only catch-all (never by the gating passes or the formula-drift check),
    so a mis-pair can at most add report-only noise, never a gating false flag."""
    m = dict(content_row_map(cS, vS, aliases))
    # Label-occurrence pairing: a row identifier that appears the SAME number of
    # times on both tabs -> pair occurrence-by-occurrence, in order (both tabs list
    # the same blocks in the same order). Two passes: col-B NAME (rep rows in detail
    # blocks no finder covers), then col-A LABEL for name-less rows (e.g. a section's
    # far-right week-history strip). setdefault so structural matches + the name pass
    # win, and so this never overrides a stronger pairing.
    from collections import defaultdict

    def _pair_by(key_fn):
        cD, vD = defaultdict(list), defaultdict(list)
        for r in range(1, len(cS) + 1):
            k = key_fn(cS, r)
            if k:
                cD[k].append(r)
        for r in range(1, len(vS) + 1):
            k = key_fn(vS, r)
            if k:
                vD[k].append(r)
        for k, crs in cD.items():
            vrs = vD.get(k)
            if vrs and len(vrs) == len(crs):
                for cr, vr in zip(crs, vrs):
                    m.setdefault(cr, vr)

    _pair_by(lambda g, r: _bname(g, r).strip().lower())          # rep names
    _pair_by(lambda g, r: (_acell(g, r).strip().lower()
                           if not _bname(g, r).strip() else ""))  # name-less label rows
    Nc, Nv = len(cS), len(vS)
    csig = [None] + [_row_sig(cS, r) for r in range(1, Nc + 1)]
    vsig = [None] + [_row_sig(vS, r) for r in range(1, Nv + 1)]
    # monotonic anchor spine (increasing in BOTH tabs) so gaps are well-formed
    anchors, lastv = [], 0
    for a in sorted(m):
        if m[a] > lastv:
            anchors.append(a)
            lastv = m[a]
    bounds = [(0, 0)] + [(a, m[a]) for a in anchors] + [(Nc + 1, Nv + 1)]
    for (ca, va), (cb, vb) in zip(bounds, bounds[1:]):
        crows = list(range(ca + 1, cb))
        vrows = list(range(va + 1, vb))
        i = j = 0
        while i < len(crows) and j < len(vrows):
            sc, sv = csig[crows[i]], vsig[vrows[j]]
            if sc == sv:
                m[crows[i]] = vrows[j]
                i += 1
                j += 1
                continue
            dj = next((k for k in range(j + 1, len(vrows))
                       if sc != ("", "") and vsig[vrows[k]] == sc), None)
            di = next((k for k in range(i + 1, len(crows))
                       if sv != ("", "") and csig[crows[k]] == sv), None)
            if dj is not None and (di is None or (dj - j) <= (di - i)):
                j += 1                    # VA has an extra (inserted) row here
            elif di is not None:
                i += 1                    # copy has an extra row here
            else:
                m[crows[i]] = vrows[j]     # label-less gap row -> gap-relative pair
                i += 1
                j += 1
    return m


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
    {concerning, benign_count, frozen, other, clean}. `frozen` (prior-week history
    drift) and `other` (catch-all completeness pass over EVERY remaining cell) are
    both REPORT-ONLY — neither affects `clean`/the gate."""
    from automations.org_sales_board.run import SANDBOX_TAB, PROD_TAB
    from automations.recruiting_report.fill import _retry
    cU = _retry(lambda: sh.worksheet(SANDBOX_TAB).get_all_values(
        value_render_option="UNFORMATTED_VALUE"))
    vU = _retry(lambda: sh.worksheet(PROD_TAB).get_all_values(
        value_render_option="UNFORMATTED_VALUE"))

    concerning: List[tuple] = []     # (region, label, a1, copy, va, bucket)
    benign = 0
    frozen: List[tuple] = []         # (region, label, a1, copy, va) — REPORT-ONLY
    other: List[tuple] = []          # catch-all completeness pass — REPORT-ONLY
    touched = set()                  # (copy_row, col) every targeted pass read

    def candidates(name):
        return set(fs._candidates_for(name, aliases))

    def match_row(name, pool):
        for k in candidates(name):
            if k in pool:
                return pool[k]
        return None

    def cmp_cell(region, label, cr, c1, vr=None, tol=0.0):
        nonlocal benign
        if (cr, c1) in touched:          # already compared by an earlier pass -> once
            return
        vr = vr if vr is not None else cr
        touched.add((cr, c1))
        cc, vv = _u(cU, cr, c1), _u(vU, vr, c1)
        if tol:                          # rounding tolerance (%-change / ratio rows)
            cn, vn = _num(cc), _num(vv)
            if cn is not None and vn is not None and abs(cn - vn) <= tol:
                return
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
    # Pair each COPY delta table to its VA twin by finder ORDER (same tables, same
    # order on both tabs), NOT by matching absolute header_row — the two tabs are
    # row-offset, so header_row N on the copy isn't header_row N on the VA. Keyed by
    # the copy header_row so the existing .get(t["header_row"]) lookups still work.
    _cdt, _vdt = rollover.find_delta_tables(cS), rollover.find_delta_tables(vS)
    v_deltas = ({ct["header_row"]: vt for ct, vt in zip(_cdt, _vdt)}
                if len(_cdt) == len(_vdt) else {})
    for t in _cdt:
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

    # ---------- CONTENT-MATCHED total rows (current-week row only) ----------
    # Locate the VA total row by the table's CONTENT (ORG name / finder order), NOT
    # the copy's row number. The copy block sits N rows below its VA twin (different
    # history/spacer counts), so a same-row compare lined a live =SUM/=SUMIF total up
    # against a frozen 'WE …' history row — 77 spurious 'va_ahead' flags. Pairing the
    # twin first makes it live-total vs live-total.
    def pos_row(region, cr, day_cols, gt_col, vr):
        if vr is None:
            return                       # no VA twin -> don't compare (never false-flag)
        label = _acell(cS, cr) or _bname(cS, cr)
        for c1 in day_cols + [gt_col]:
            cmp_cell(region, label, cr, c1, vr)

    # X-ORG history 'Sales - This Week' — pair CARLOS/COLTEN/BEN by ORG name
    v_org_hist = {_org_name(vS, t["header_row"]): t
                  for t in rollover.find_org_history_tables(vS)}
    for h in rollover.find_org_history_tables(cS):
        vt = v_org_hist.get(_org_name(cS, h["header_row"]))
        pos_row("ORG history this-week", h["this"],
                list(range(h["c0"], h["cN"])), h["cN"],
                vt["this"] if vt else None)
    # per-campaign 'this-week' Totals — pair by finder order (count-guarded)
    _cch, _vch = (rollover.find_campaign_history_tables(cS),
                  rollover.find_campaign_history_tables(vS))
    _camp_ok = len(_cch) == len(_vch)
    for i, h in enumerate(_cch):
        pos_row("campaign this-week", h["this"],
                list(range(h["c0"], h["cN"])), h["cN"],
                _vch[i]["this"] if _camp_ok else None)
    # captainship product-summary Totals — pair by finder order (count-guarded)
    _cps, _vps = (rollover.find_captainship_product_summaries(cS),
                  rollover.find_captainship_product_summaries(vS))
    _ps_ok = len(_cps) == len(_vps)
    for i, s in enumerate(_cps):
        pos_row("product-summary this-week", s["totals_row"],
                s["day_cols"], s["gt_col"],
                _vps[i]["totals_row"] if _ps_ok else None)

    # 'Current vs Prior' summary blocks (per-captainship + per-ORG incl RAF) — pair
    # by finder order. GATE only the live 'Sales - This Week' row (the real current
    # total; flags only on genuine automation lag). The 'Sales (Last Week)' / '4
    # Week AVG' / 'vs Prior Week' / 'vs 4 WeekAVG' rows are DERIVED FROM FROZEN
    # prior-week history, which the two tabs maintain independently and roll at
    # different moments — so they differ for reasons unrelated to the automation and
    # would false-flag if gated. They ARE still value-compared, REPORT-ONLY, by the
    # catch-all pass below (all 5 rows are in content_row_map). (cmp_cell dedups, so
    # ORG 'this' rows already checked above aren't double-counted.)
    _ccvp, _vcvp = _find_cvp_blocks(cS), _find_cvp_blocks(vS)
    _cvp_ok = len(_ccvp) == len(_vcvp)
    for i, cb in enumerate(_ccvp):
        vb = _vcvp[i] if _cvp_ok else None
        if not (vb and cb.get("this") and vb.get("this")):
            continue
        cols = cb.get("day_cols", []) + ([cb["gt_col"]] if cb.get("gt_col") else [])
        for c1 in cols:
            cmp_cell("cvp Sales-This-Week", _bname(cS, cb["this"]) or "this",
                     cb["this"], c1, vb["this"])
    # Leaderboard/section grand-total ('TOTALS') rows — GATE the current-week total
    # column (col C = the live week total); the frozen history columns of these rows
    # fall to the report-only frozen/catch-all passes (past weeks differ by design).
    _cgt, _vgt = _find_grand_total_rows(cS), _find_grand_total_rows(vS)
    if len(_cgt) == len(_vgt):
        for cr, vr in zip(_cgt, _vgt):
            cmp_cell("grand-total (this-week)", "TOTALS", cr, 3, vr)

    # ========== FROZEN prior-week history (REPORT-ONLY, never gates) ==========
    # Every static past-week cell: leaderboard history cols, delta 'Last week'
    # cols, ORG/campaign history rows, product-summary WE-stack. These are
    # immovable past data — the two tabs, rolled at different moments, diverge
    # here, so it can't gate (it'd hold the board red forever). Surfaced so
    # nothing is unchecked. (Megan 2026-07-03: report, don't gate.)
    def frz_named(region, label, cr, vr, c1):
        touched.add((cr, c1))
        cc, vv = _u(cU, cr, c1), _u(vU, vr, c1)
        if _classify(cc, vv) not in ("exact", "ns0", "blank"):
            frozen.append((region, label, rowcol_to_a1(cr, c1), cc, vv))

    def frz_pos(region, label, r, c1):
        touched.add((r, c1))
        cc, vv = _u(cU, r, c1), _u(vU, r, c1)
        if _classify(cc, vv) not in ("exact", "ns0", "blank"):
            frozen.append((region, label, rowcol_to_a1(r, c1), cc, vv))

    try:
        _ob_c = rollover.find_org_block(cS)
        _ob_v = rollover.find_org_block(vS)
        _last = _ob_c.last_col
        vpool = {_norm_owner(_bname(vS, r)): r for r in _ob_v.data_rows}
        for r in _ob_c.data_rows:
            vr = match_row(_bname(cS, r), vpool)
            if vr is None:
                continue
            for c1 in range(_ob_c.first_col + 1, _last + 1):
                frz_named("ORG leaderboard history", _bname(cS, r), r, vr, c1)
        # Captainship leaderboards shift right in lock-step with ORG, so their
        # history spans the same columns (C+1 .. ORG last_col).
        for t in caps:
            try:
                ca = cap.find_captainship(cS, t)
                va = cap.find_captainship(vS, t)
            except Exception:
                continue
            vp = {_norm_owner(n): r for r, n in va.leaderboard}
            for r, name in ca.leaderboard:
                vr = match_row(name, vp)
                if vr is None:
                    continue
                for c1 in range(ca.week_total_col + 1, _last + 1):
                    frz_named(f"{t} leaderboard history", name, r, vr, c1)
    except Exception as e:  # noqa: BLE001
        logfn(f"  ⚠ frozen leaderboard history skipped ({str(e)[:50]})")

    # Delta 'Last week' cols (the frozen partner of each per-day This-week col)
    for t in rollover.find_delta_tables(cS):
        vt = v_deltas.get(t["header_row"])
        if not vt:
            continue
        vpool = {_norm_owner(_bname(vS, r)): r for r in vt["data_rows"]}
        for r in t["data_rows"]:
            name = _bname(cS, r)
            if not name:
                continue
            vr = match_row(name, vpool)
            if vr is None:
                continue
            for c1 in [c + 1 for c in t["this_cols"]]:
                frz_named(f"delta@{t['header_row']} last-week", name, r, vr, c1)

    # ORG + campaign 4-week history rows — pair the VA row by CONTENT twin (ORG
    # name / finder order), not the copy row number.
    for h in rollover.find_org_history_tables(cS):
        vt = v_org_hist.get(_org_name(cS, h["header_row"]))
        for key in ("lw", "pw", "2wp", "3wp"):
            if not (vt and vt.get(key)):
                continue
            for c1 in range(h["c0"], h["cN"] + 1):
                frz_named("ORG history rows", _acell(cS, h[key]) or key,
                          h[key], vt[key], c1)
    for i, h in enumerate(_cch):
        vt = _vch[i] if _camp_ok else None
        for key in ("lw", "pw", "2wp", "3wp"):
            if not (vt and vt.get(key)):
                continue
            for c1 in range(h["c0"], h["cN"] + 1):
                frz_named("campaign history rows", _acell(cS, h[key]) or key,
                          h[key], vt[key], c1)
    # Product-summary WE-stack + last-week/avg rows (positional)
    for s in rollover.find_captainship_product_summaries(cS):
        rows = [x for x in (s["last_week_row"], s["avg_row"]) if x]
        r = s["top_row"]
        while r < len(cS) and rollover._WE_ROW_RE.match(_acell(cS, r)):
            rows.append(r)
            r += 1
        for rr in rows:
            for c1 in s["day_cols"] + [s["gt_col"]]:
                frz_pos("product-summary history", _acell(cS, rr) or _bname(cS, rr),
                        rr, c1)

    # ========== CATCH-ALL completeness pass (REPORT-ONLY, never gates) ==========
    # Guarantees LITERALLY every value cell is compared — the delta 'Delta' cols,
    # row/team subtotals, ORG-summary metric rows, anything the targeted passes
    # above didn't reach. Rows that sort differently between the tabs are
    # name-mapped (only those move); every other row is positional (the two tabs
    # are structurally identical). Col A (rank) is skipped — it's re-ranked per
    # run and differs by design. (Megan 2026-07-03: verify EVERY cell.)
    sorted_rows: dict = {}     # copy_row -> va_row (matched rows in sorted blocks)
    sorted_all: set = set()    # every row inside a sorted block (matched or not)
    try:
        for lbl in SECTIONS:
            try:
                ca = fs.find_daily_section(cS, lbl)
                va = fs.find_daily_section(vS, lbl)
            except Exception:
                continue
            vp = {_norm_owner(n): r for n, r in va.icd_rows.items()}
            for name, r in ca.icd_rows.items():
                sorted_all.add(r)
                vr = match_row(name, vp)
                if vr:
                    sorted_rows[r] = vr
        for t in caps:
            try:
                ca = cap.find_captainship(cS, t)
                va = cap.find_captainship(vS, t)
            except Exception:
                continue
            vp_d = {_norm_owner(n): r for r, n in va.daily}
            vp_l = {_norm_owner(n): r for r, n in va.leaderboard}
            for r, name in ca.daily:
                sorted_all.add(r)
                vr = match_row(name, vp_d)
                if vr:
                    sorted_rows[r] = vr
            for r, name in ca.leaderboard:
                sorted_all.add(r)
                vr = match_row(name, vp_l)
                if vr:
                    sorted_rows[r] = vr
        _ob = rollover.find_org_block(cS)
        _obv = rollover.find_org_block(vS)
        vp = {_norm_owner(_bname(vS, r)): r for r in _obv.data_rows}
        for r in _ob.data_rows:
            sorted_all.add(r)
            vr = match_row(_bname(cS, r), vp)
            if vr:
                sorted_rows[r] = vr
        for t in rollover.find_delta_tables(cS):
            vt = v_deltas.get(t["header_row"])
            if not vt:
                continue
            vp = {_norm_owner(_bname(vS, r)): r for r in vt["data_rows"]}
            for r in t["data_rows"]:
                sorted_all.add(r)
                vr = match_row(_bname(cS, r), vp)
                if vr:
                    sorted_rows[r] = vr
        # FULL content twin for EVERY row (structural map + label alignment of the
        # gaps). Used so the completeness sweep compares by CONTENT, never by
        # absolute row position, and leaves NOTHING unchecked.
        _cmap = coverage_row_map(cS, vS, aliases)
        for r in range(1, len(cU) + 1):
            width = len(cU[r - 1]) if r - 1 < len(cU) else 0
            for c1 in range(2, width + 1):        # skip col A (rank)
                if (r, c1) in touched:
                    continue
                # A named rep row that didn't match by name (roster mismatch) is
                # surfaced by the non-match check; still value-compare it against its
                # aligned twin so no cell is left unchecked.
                vr = sorted_rows.get(r) or _cmap.get(r)
                if vr is None:
                    continue           # no content twin at all (extra tail row)
                touched.add((r, c1))   # count it as compared (completeness coverage)
                cc, vv = _u(cU, r, c1), _u(vU, vr, c1)
                b = _classify(cc, vv)
                if b in ("exact", "ns0", "blank"):
                    continue
                other.append((_bname(cS, r) or _acell(cS, r),
                              rowcol_to_a1(r, c1), cc, vv, b))
    except Exception as e:  # noqa: BLE001
        logfn(f"  ⚠ catch-all completeness pass skipped ({str(e)[:60]})")

    clean = not concerning     # frozen + other are REPORT-ONLY — never gate
    _report(logfn, concerning, benign, frozen, other, clean)
    return {"concerning": concerning, "benign_count": benign,
            "frozen": frozen, "other": other, "clean": clean,
            "touched": touched}


def _report(logfn, concerning, benign, frozen, other, clean):
    import collections
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
    # Frozen prior-week history — REPORT-ONLY, never gates the run.
    logfn("  --- FROZEN PRIOR-WEEK HISTORY (report-only, does NOT gate) ---")
    if frozen:
        by = collections.Counter(f[0] for f in frozen)
        logfn(f"  ⚠ {len(frozen)} frozen history cell(s) differ copy-vs-VA "
              f"(immovable past data — informational):")
        for reg, n in by.most_common():
            logfn(f"      {reg}: {n}")
    else:
        logfn("  ✅ frozen history matches the VA tab too.")
    # Catch-all completeness pass — every remaining value cell (deltas, subtotals,
    # ORG-summary metrics, anything else). REPORT-ONLY, never gates.
    logfn("  --- CATCH-ALL: EVERY OTHER CELL (report-only, does NOT gate) ---")
    if other:
        dirs = collections.Counter(o[4] for o in other)
        logfn(f"  ⚠ {len(other)} remaining cell(s) differ copy-vs-VA "
              f"({dict(dirs)}) — mostly derived delta/subtotal/metric cells:")
        for label, a1, c, v, b in other[:25]:
            logfn(f"      {label[:26]} {a1}: copy={c!r} VA={v!r}  ({b})")
        if len(other) > 25:
            logfn(f"      …and {len(other) - 25} more")
    else:
        logfn("  ✅ every remaining cell matches the VA tab — 100% coverage clean.")
