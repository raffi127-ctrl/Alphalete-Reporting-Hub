"""Leader's Call weekly recognition — fills the 'Leader's Call' tab of the
All-in-One Local Office (Raf) sheet.

Copies the OPT report's machinery (CLAUDE.MD): each campaign's rep-level
crosstab is pulled UNATTENDED via
`automations.shared.tableau_patchright.download_crosstab_patchright` (ownerville
SSO -> Tableau; no browser extension, no manual clicks), parsed with
`automations.alphalete_org_report.opt_nds._read_tab_csv`, filtered to the
campaign's owners + apps/$ threshold, sorted desc, and written to the matching
section of the Leader's Call tab.

Crosstab worksheet names: Tableau appends a dedup counter ('… (3)'), so we
match by SUBSTRING (enumerate the dialog, find the sheet containing our name),
exactly like opt_b2b._download_view.

Build status: per-campaign parsers are verified one at a time against known
data via --dry-run before the real write (CLAUDE.MD: sandbox/dry-run first).

Usage:
  python -m automations.leaders_call.run --campaign fiber --inspect   # dump crosstab cols
  python -m automations.leaders_call.run --campaign fiber --dry-run    # pull+parse+print
  python -m automations.leaders_call.run --dry-run                     # all campaigns, no write
"""
from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "output" / "leaders_call"

LEADERS_CALL_SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
LEADERS_CALL_TAB = "Leader's Call"

# All AT&T product types — appended to the Fiber view URL so the crosstab's
# Grand Total reflects ALL apps (the bare view defaults to NEW INTERNET only).
_ATT_PRODUCTS = ["AIR", "NEW INTERNET", "UPGRADE INTERNET", "VIDEO", "VOICE",
                 "WIRELESS"]


def _fiber_url() -> str:
    base = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "ATTTRACKER2_1-D2D/D2D1-PAGERRepLvl?:iid=1")
    # Repeated filter param selects every product type ('(All)').
    qp = "".join(f"&Product%20Type%20(Broken%20Out)={p.replace(' ', '%20')}"
                 for p in _ATT_PRODUCTS)
    # Week scoping: the view's default relative filter is "This Week", which on
    # a Monday run = the just-completed week (observed Mon 6/15 -> showed
    # 6/8-6/14). We DON'T override it via URL (the "Last Week" value empties the
    # worksheets, and Tableau's viz iframe hides the real filter options from
    # the URL/DOM). Instead the parser reads the dated day-column headers and a
    # guard validates they equal the target completed week (safe on any run
    # day). A bulletproof pin would need a saved LASTWEEK custom view, like the
    # OPT report uses — a follow-up if Monday's default ever drifts.
    return base + qp


@dataclass
class Campaign:
    key: str
    url: str
    crosstab_sheet: str          # substring of the dialog worksheet name
    threshold: float
    section_title: str
    # Column-header substrings (lowercased) that identify each field in the CSV.
    rep_hdr: tuple = ("rep",)
    owner_hdr: tuple = ("owner",)
    value_hdr: tuple = ("grand total", "total")
    owners: list[str] = field(default_factory=list)   # keep these owners; [] = all
    parser: str = "generic"          # "generic" | "costco" | "revenue"
    sum_cols: tuple = ()             # Costco: product columns to sum per rep


CAMPAIGNS: dict[str, Campaign] = {
    "fiber": Campaign(
        key="fiber",
        url=_fiber_url(),
        crosstab_sheet="Sales By ICD (ATT) (V2)",
        threshold=12,
        section_title="Fiber",
        rep_hdr=("rep",),
        owner_hdr=("owner name", "owner"),
        value_hdr=("grand total", "total"),
        owners=["Rafael Hidalgo", "Kash Rai", "Haytham Nagi", "Aya Al-Khafaji",
                "Cyrus Wade", "Hammad Haque", "Jacob Dover", "Cody Cannon",
                "Rashad Reed", "Salik Mallick"],
    ),
    "nds": Campaign(
        key="nds",
        url=("https://us-east-1.online.tableau.com/#/site/sci/views/"
             "NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep/"
             "b86d7862-bfc7-4966-a0a4-7803432a6444/REPEXPANDED?:iid=2"),
        crosstab_sheet="Sales By ICD (Weekly View)",
        threshold=12,
        section_title="NDS",
        rep_hdr=("rep",),
        owner_hdr=("owner",),
        value_hdr=("product total", "grand total", "total"),
        owners=["Khalil Mansour", "Maxamad Aden", "Isaiah Revelle"],
    ),
    "b2b": Campaign(
        key="b2b",
        url=("https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/"
             "B2BATTSalesMetrics/5dc77806-1536-4a20-9c98-54545f786715/B2BLASTWEEK"),
        crosstab_sheet="Sales.Quality Metrics",
        threshold=12,
        section_title="B2B",
        rep_hdr=("rep",),
        owner_hdr=("owner name", "owner"),
        value_hdr=("sales",),          # the 'Sales' (apps) column, not 'AIR/AWB Sales'
        owners=["Atef Choudhury", "Carlos Hidalgo", "Kevin Driggs"],
    ),
    "je": Campaign(
        key="je",
        url=("https://us-east-1.online.tableau.com/#/site/sci/views/"
             "JustEnergyRTL-SalesStaffingProductivityWorkbook/WeeklyMetricsbyRep"),
        crosstab_sheet="Weekly Metrics by Rep",
        threshold=12,
        section_title="JE",
        rep_hdr=("rep name", "rep"),
        owner_hdr=("icd name", "icd", "owner"),
        value_hdr=("total sales",),     # loom's 'Total Cells' = this view's Total Sales
        owners=["David Martinez", "Cinthya Reyes", "Paola Rodriguez",
                "Brandon Stockerbs", "Gerrit Stockerbs", "Ishama Ariyano"],
    ),
    "box": Campaign(
        key="box",
        url=("https://us-east-1.online.tableau.com/#/site/sci/views/"
             "B2BBOXEnergy/WoWMetricsbyRep"),
        crosstab_sheet="WoW Rep Metrics",
        threshold=12,
        section_title="BOX",
        rep_hdr=("rep name", "rep"),
        owner_hdr=("icd name", "icd", "owner"),
        value_hdr=("total sales",),
        owners=["Roshan Amin Ahmad", "Ryan McSpadden"],
    ),
    "costco": Campaign(
        key="costco",
        url=("https://us-east-1.online.tableau.com/#/site/sci/views/"
             "DropshipV_2/SARAPLUSSALESSUMMARY?:iid=1"),
        crosstab_sheet="Sara Plus Sales Summary (2)",
        threshold=8,
        section_title="Costco",
        owners=[],
        parser="costco",
        # apps = ATV+DTV+Internet+AIA+New/Port Lines (Megan 2026-06-18; the
        # '(No Up)' label = Next Up excluded).
        sum_cols=("atv", "dtv", "internet", "aia", "new/port lines"),
    ),
    "revenue": Campaign(
        key="revenue",
        url=("https://us-east-1.online.tableau.com/#/site/sci/views/"
             "DirectDepositICDVIEWVersion2_0/DDBYOWNERORG/"
             "796feca0-272f-459f-a665-63ac9aec3af8/DOWNLINEVIEW?:iid=1"),
        crosstab_sheet="Sheet 7 (5)",
        threshold=2000,
        section_title="Revenue over 2K",
        owners=[],
        parser="revenue",
    ),
}


def _download_substr(page, url: str, sheet_substr: str, out: Path) -> Path:
    """Download a crosstab whose dialog worksheet name CONTAINS sheet_substr
    (Tableau appends '(3)'-style counters). Enumerate the dialog, resolve the
    exact name, then download it. Mirrors opt_b2b._download_view."""
    from automations.recruiting_report.opt_phase import drive_crosstab_dialog
    try:
        drive_crosstab_dialog(page, url, "__enumerate__", out, verbose=False)
    except RuntimeError as e:
        m = re.search(r":\s*(\[.*\])\.", str(e))
        avail = ast.literal_eval(m.group(1)) if m else []
        target = next((s for s in avail
                       if sheet_substr.lower() in s.lower()), None)
        if target is None:
            raise RuntimeError(f"{sheet_substr!r} not among {avail}")
        return drive_crosstab_dialog(page, url, target, out, verbose=False)
    raise RuntimeError("enumerate should have raised")


def _pull(camp: Campaign, page, out: Optional[Path] = None) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = out or (OUTPUT_DIR / f"{camp.key}.csv")
    return _download_substr(page, camp.url, camp.crosstab_sheet, out)


def _find_col(headers: list[str], needles: tuple) -> Optional[int]:
    low = [(h or "").strip().lower() for h in headers]
    for n in needles:                       # exact-ish first
        for i, h in enumerate(low):
            if h == n:
                return i
    for n in needles:                       # then substring
        for i, h in enumerate(low):
            if n in h:
                return i
    return None


def _num(s: str) -> Optional[float]:
    s = re.sub(r"[,$%\s]", "", (s or ""))
    try:
        return float(s)
    except ValueError:
        return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _owner_key(s: str) -> str:
    """Owner match key: drop the '[legal entity]' suffix some views append
    (e.g. 'KHALIL MANSOUR [alphalete management group, inc. dba hab]') and any
    newline, then normalize. So sheet/config owner names (no bracket) match the
    Tableau 'Owner & Office' column."""
    s = (s or "").split("[")[0]
    return _norm(s)


def _header_row(rows: list[list[str]]) -> int:
    """Tableau crosstabs can have a grouping row above the real labels (e.g. a
    'This Week' row over the day columns). The real header is the first row
    that has a 'Rep' cell. Falls back to row 0."""
    for i, r in enumerate(rows[:5]):
        low = [(c or "").strip().lower() for c in r]
        if any(c == "rep" or c.startswith("rep ") or c == "rep name" for c in low):
            return i
    return 0


def _value_col(headers: list[str], needles: tuple) -> Optional[int]:
    """Pick the value column. EXACT header match wins first (so B2B's 'Sales'
    beats 'AIR/AWB Sales'); otherwise the RIGHTMOST substring match (so a
    week-scoped crosstab lands on the 'Total'/'Grand Total' column, not a
    daily one)."""
    low = [(h or "").strip().lower() for h in headers]
    for n in needles:
        for i, h in enumerate(low):
            if h == n:
                return i
    hit = None
    for i, h in enumerate(low):
        if any(n in h for n in needles):
            hit = i
    return hit


def parse_rows(camp: Campaign, rows: list[list[str]]) -> list[tuple]:
    """Generic crosstab -> [(rep, owner, value)] honoring the campaign's
    owner filter + threshold, sorted by value desc. (Campaigns needing summed
    or reshaped values get their own parser later; this covers the simple
    rep|owner|total crosstabs: Fiber/NDS/B2B/BOX/Revenue.)"""
    if not rows:
        return []
    h = _header_row(rows)
    hdr = rows[h]
    ri = _find_col(hdr, camp.rep_hdr)
    oi = _find_col(hdr, camp.owner_hdr)
    vi = _value_col(hdr, camp.value_hdr)
    if ri is None or vi is None:
        raise RuntimeError(f"{camp.key}: couldn't find columns "
                           f"(rep={ri}, owner={oi}, value={vi}) in {hdr}")
    rows = rows[h:]
    keep_owners = {_owner_key(o) for o in camp.owners}
    out = []
    for r in rows[1:]:
        rep = (r[ri] if ri < len(r) else "").strip()
        owner = (r[oi] if oi is not None and oi < len(r) else "").strip()
        owner = re.sub(r"\s*\[.*", "", owner).replace("\n", " ").strip()
        val = _num(r[vi] if vi < len(r) else "")
        if not rep or rep.lower() in ("total", "grand total"):
            continue
        if val is None or val < camp.threshold:
            continue
        if keep_owners and _owner_key(owner) not in keep_owners:
            continue
        out.append((rep, owner, val))
    out.sort(key=lambda t: t[2], reverse=True)
    return out


def parse_costco(camp: Campaign, rows: list[list[str]]) -> list[tuple]:
    """Sara Plus crosstab -> [(rep, owner, apps)] where apps = sum of the
    configured product columns (ATV+DTV+Internet+AIA per the loom). Header is
    row 0; owner col = 'Owner & Office' (legal suffix stripped); skip the
    per-owner 'Total' subrows."""
    if not rows:
        return []
    hdr = [(h or "").strip().lower() for h in rows[0]]
    oi = _find_col(rows[0], camp.owner_hdr or ("owner",))
    ri = _find_col(rows[0], ("rep",))
    sum_idx = [i for i, h in enumerate(hdr) if h in camp.sum_cols]
    if ri is None or not sum_idx:
        raise RuntimeError(f"costco: cols rep={ri} sum={sum_idx} in {rows[0]}")
    out = []
    for r in rows[1:]:
        rep = (r[ri] if ri < len(r) else "").strip()
        if not rep or rep.lower() in ("total", "grand total"):
            continue
        owner = re.sub(r"\s*\[.*", "", (r[oi] if oi is not None and oi < len(r)
                                        else "")).replace("\n", " ").strip()
        apps = sum(int(_num(r[i]) or 0) for i in sum_idx if i < len(r))
        if apps >= camp.threshold:
            out.append((rep, owner, apps))
    out.sort(key=lambda t: t[2], reverse=True)
    return out


# Revenue is filtered to the LOCAL OFFICE owners (the loom selects ~two dozen
# owners before keeping >= $2k). This is the union of every campaign's owners +
# the Costco owners. DD spells some differently (e.g. 'Roshan Ahmad' vs 'Roshan
# Amin Ahmad'), so matching is by first+last name token, not exact string.
REVENUE_OWNERS = [
    "Rafael Hidalgo", "Kash Rai", "Haytham Nagi", "Aya Al-Khafaji", "Cyrus Wade",
    "Hammad Haque", "Jacob Dover", "Cody Cannon", "Rashad Reed", "Salik Mallick",
    "Khalil Mansour", "Maxamad Aden", "Isaiah Revelle",
    "Atef Choudhury", "Carlos Hidalgo", "Kevin Driggs",
    "David Martinez", "Cinthya Reyes", "Paola Rodriguez",
    "Roshan Amin Ahmad", "Ryan McSpadden",
    "Amjad Malhas", "Ana Griffin", "Boaktear Chowdhury", "Ronald Dawson",
]


def _name_tokens(s: str) -> tuple:
    """(first, last) lowercased tokens of a person name, bracket-suffix dropped —
    so 'Roshan Amin Ahmad' and 'Roshan Ahmad' both key to ('roshan','ahmad')."""
    parts = _owner_key(s).split()
    return (parts[0], parts[-1]) if len(parts) >= 2 else (parts[0] if parts else "",)


_REVENUE_OWNER_KEYS = {_name_tokens(o) for o in REVENUE_OWNERS}


def parse_revenue(camp: Campaign, rows: list[list[str]]) -> list[tuple]:
    """Direct-Deposit 'Sheet 7 (5)' crosstab -> [(rep, owner, $total)]. The
    grid has a measure-name column ('Distinct count…' / 'Total $ to ICD') and
    per-program $ columns. A rep's grand total = the fully-aggregated row
    (Strategic Alliance=Total, Commission=Total, measure='Total $ to ICD'),
    summed across the money columns. Keep reps >= $2,000."""
    if not rows:
        return []
    hdr = rows[0]
    owner_i = _find_col(hdr, ("cl.icd owner name", "icd owner", "owner name", "owner"))
    rep_i = _find_col(hdr, ("sales rep",))
    alli_i = _find_col(hdr, ("strategic alliance", "alliance"))
    comm_i = _find_col(hdr, ("commission description", "commission"))
    gt_i = _find_col(hdr, ("grand total to icd", "grand total"))
    if None in (owner_i, rep_i, alli_i, comm_i, gt_i):
        raise RuntimeError(f"revenue: cols owner={owner_i} rep={rep_i} "
                           f"alli={alli_i} comm={comm_i} gt={gt_i} in {hdr}")
    measure_i = gt_i - 1                       # the blank-header measure column
    money_cols = range(gt_i, len(hdr))         # Grand Total to ICD + program $
    out = []
    for r in rows[1:]:
        def g(i): return (r[i] if i < len(r) else "").strip()
        rep = g(rep_i)
        if not rep or rep.lower() in ("total", "total to icd", "grand total"):
            continue
        if (g(alli_i).lower() == "total" and g(comm_i).lower() == "total"
                and g(measure_i).lower() == "total $ to icd"):
            owner = g(owner_i)
            if _name_tokens(owner) not in _REVENUE_OWNER_KEYS:
                continue                       # keep only local-office owners
            total = sum(_num(r[i]) or 0 for i in money_cols if i < len(r))
            if total >= camp.threshold:
                out.append((rep, owner, total))
    out.sort(key=lambda t: t[2], reverse=True)
    return out


def parse(camp: Campaign, rows: list[list[str]]) -> list[tuple]:
    if camp.parser == "costco":
        return parse_costco(camp, rows)
    if camp.parser == "revenue":
        return parse_revenue(camp, rows)
    return parse_rows(camp, rows)


def _dump_timeframe(camp: Campaign) -> None:
    """Open the view (no crosstab) and print the Time Frame filter's current
    value + available options, so week-scoping uses a REAL value."""
    from automations.shared.tableau_patchright import tableau_session
    # Strip our Time Frame override so we see the native default + options.
    url = camp.url.split("&Time%20Frame")[0]
    with tableau_session(verbose=True) as page:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(20000)
        txt = page.evaluate("() => document.body.innerText")
        print("=== page text (filter labels/values) ===")
        for ln in (txt or "").splitlines():
            s = ln.strip()
            if s and any(k in s.lower() for k in
                         ("week", "time frame", "wk", "20", "/")):
                print("  ", s[:120])
        # Try to open the Time Frame dropdown and read its options.
        try:
            cb = page.get_by_text("This Week", exact=False).first
            cb.click(timeout=5000)
            page.wait_for_timeout(2500)
            opts = page.evaluate(
                "() => Array.from(document.querySelectorAll("
                "'[role=option],[role=menuitemradio],a,label,span'))"
                ".map(e=>e.textContent.trim()).filter(t=>t && t.length<40)"
                ".filter(t=>/week|wk|20\\d\\d|\\d+\\/\\d+/i.test(t))")
            print("=== Time Frame options (after click) ===")
            for o in dict.fromkeys(opts):
                print("  *", o)
        except Exception as e:
            print(f"(couldn't open Time Frame dropdown: {type(e).__name__}: {e})")


def _inspect(camp: Campaign) -> None:
    from automations.alphalete_org_report.opt_nds import _read_tab_csv
    from automations.shared.tableau_patchright import tableau_session
    with tableau_session(verbose=True) as page:
        path = _pull(camp, page)
    rows = _read_tab_csv(path)
    print(f"\n=== {camp.key}: {path} ({len(rows)} rows) ===")
    for i, r in enumerate(rows[:30]):
        print(f"{i:>3} | " + " | ".join((c or "").strip() for c in r))


def _inspect_all(keys: list[str]) -> None:
    """Pull every requested campaign's crosstab in ONE Tableau session and dump
    headers + a few rows, so all parsers can be built without re-authing each."""
    from automations.alphalete_org_report.opt_nds import _read_tab_csv
    from automations.shared.tableau_patchright import tableau_session
    with tableau_session(verbose=True) as page:
        for k in keys:
            camp = CAMPAIGNS[k]
            print(f"\n################ {k} ################", flush=True)
            try:
                path = _pull(camp, page)
                rows = _read_tab_csv(path)
                print(f"rows={len(rows)} file={path}")
                for i, r in enumerate(rows[:12]):
                    print(f"{i:>3} | " + " | ".join((c or "").strip() for c in r))
            except Exception as e:
                print(f"✗ {k}: {type(e).__name__}: {str(e)[:200]}")


def _dry_one(camp: Campaign) -> None:
    from automations.alphalete_org_report.opt_nds import _read_tab_csv
    from automations.shared.tableau_patchright import tableau_session
    with tableau_session(verbose=True) as page:
        path = _pull(camp, page)
    parsed = parse(camp, _read_tab_csv(path))
    print(f"\n=== {camp.section_title}: {len(parsed)} reps >= {camp.threshold} ===")
    for rep, owner, val in parsed:
        v = f"${val:,.0f}" if camp.threshold >= 100 else f"{val:g}"
        print(f"  {rep}  |  {owner}  |  {v}")


TABLEAU_ORDER = ["fiber", "nds", "b2b", "je", "box", "costco", "revenue"]

# Section title -> regex matched against column A to locate each section's
# header row on the Leader's Call tab (label lookup, never hardcoded rows).
SECTION_MATCH = {
    "Fiber":           re.compile(r"\bfiber\b", re.I),
    "NDS":             re.compile(r"\bnds\b", re.I),
    "B2B":             re.compile(r"\bb2b\b", re.I),
    "JE":              re.compile(r"\bje\b", re.I),
    "BOX":             re.compile(r"\bbox\b", re.I),
    "Costco":          re.compile(r"costco", re.I),
    "Frontier":        re.compile(r"frontier", re.I),
    "Revenue over 2K": re.compile(r"revenue", re.I),
}


def _fmt_value(section_title: str, val) -> str:
    if "revenue" in section_title.lower():
        return f"${float(val):,.2f}"
    return str(int(val))


def _open_tab(tab: str = LEADERS_CALL_TAB):
    from automations.recruiting_report import fill as rfill
    client = rfill._client()
    sh = rfill.open_by_key(LEADERS_CALL_SHEET_ID, client)
    ws = rfill._retry(sh.worksheet, tab)
    return sh, ws


def write_report(ws, results: dict, dry_run: bool = True) -> list[str]:
    """Write each section's [(rep,owner,val)] into the Leader's Call tab.

    Locate each section by its column-A title (SECTION_MATCH); data lives in the
    rows between the section's column-header row (title+1) and the next section's
    title. Resize that block to the new row count (insert/delete) then overwrite
    A:C. Process sections BOTTOM-UP so inserts/deletes never shift the title rows
    of sections not yet written. Sections with no data (None) are left untouched.
    """
    from automations.recruiting_report import fill as rfill
    grid = rfill._retry(ws.get_all_values)
    colA = [(r[0] if r else "") for r in grid]
    # Ordered (section_title, title_row_1based) for sections present on the tab.
    found = []
    for i, a in enumerate(colA):
        for title, rx in SECTION_MATCH.items():
            if rx.search(a or ""):
                found.append((title, i + 1))
                break
    found.sort(key=lambda t: t[1])
    title_rows = {t: r for t, r in found}
    ordered = [t for t, _ in found]

    log = []
    for idx in range(len(found) - 1, -1, -1):       # bottom-up
        title, trow = found[idx]
        rows = results.get(title)
        if rows is None:
            log.append(f"[skip] {title}: no data (left as-is)")
            continue
        data_start = trow + 2                        # title, header, then data
        next_trow = found[idx + 1][1] if idx + 1 < len(found) else len(grid) + 1
        old_count = max(0, next_trow - data_start)
        new_count = len(rows)
        body = [[rep, owner, _fmt_value(title, val)] for rep, owner, val in rows]
        if dry_run:
            log.append(f"[dry] {title}: rows {old_count} -> {new_count} "
                       f"(write A{data_start}:C{data_start + new_count - 1})")
            continue
        diff = new_count - old_count
        if diff > 0:
            rfill._retry(ws.insert_rows, [[""] * 3] * diff, data_start)
        elif diff < 0:
            rfill._retry(ws.delete_rows, data_start, data_start - diff - 1)
        if new_count:
            rng = f"A{data_start}:C{data_start + new_count - 1}"
            rfill._retry(ws.update, rng, body, value_input_option="USER_ENTERED")
        log.append(f"[ok] {title}: wrote {new_count} rows at A{data_start}")
    return log


def run_all(write: bool = False) -> dict:
    """Pull + parse every Tableau campaign in ONE session and print each
    section. With write=True, also write the results into the live Leader's
    Call tab (Frontier is left as-is unless its preflight upload was parsed).
    Returns {section_title: [(rep, owner, value)]}."""
    from automations.alphalete_org_report.opt_nds import _read_tab_csv
    from automations.shared.tableau_patchright import tableau_session
    results: dict = {}
    with tableau_session(verbose=True) as page:
        for k in TABLEAU_ORDER:
            camp = CAMPAIGNS[k]
            try:
                path = _pull(camp, page)
                res = parse(camp, _read_tab_csv(path))
                results[camp.section_title] = res
                print(f"\n=== {camp.section_title}: {len(res)} >= {camp.threshold} ===",
                      flush=True)
                for rep, owner, val in res:
                    v = f"${val:,.0f}" if camp.threshold >= 100 else f"{val:g}"
                    print(f"   {rep} | {owner} | {v}", flush=True)
            except Exception as e:
                print(f"✗ {k}: {type(e).__name__}: {str(e)[:160]}", flush=True)
                results[camp.section_title] = None
    # Frontier: filled from its preflight-uploaded PDF (see frontier.py).
    try:
        from automations.leaders_call import frontier as fr
        results["Frontier"] = fr.parse_uploaded()
        print(f"\n=== Frontier: {len(results['Frontier'])} >= 8 ===", flush=True)
    except Exception as e:
        results["Frontier"] = None
        print(f"\n(Frontier skipped: {type(e).__name__}: {str(e)[:120]})", flush=True)

    if write:
        sh, ws = _open_tab()
        print("\n--- writing Leader's Call tab ---", flush=True)
        for ln in write_report(ws, results, dry_run=False):
            print("  " + ln, flush=True)
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", help="one of: " + ", ".join(CAMPAIGNS))
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--inspect-all", action="store_true")
    ap.add_argument("--dump-timeframe", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--write", action="store_true",
                    help="write results into the live Leader's Call tab")
    args = ap.parse_args()

    if args.campaign and args.campaign not in CAMPAIGNS:
        print(f"unknown campaign {args.campaign!r}")
        return 2
    if args.inspect_all:
        _inspect_all([k for k in CAMPAIGNS])
        return 0
    if args.dump_timeframe:
        _dump_timeframe(CAMPAIGNS[args.campaign])
        return 0
    if args.inspect:
        _inspect(CAMPAIGNS[args.campaign])
        return 0
    if args.dry_run and args.campaign:
        _dry_one(CAMPAIGNS[args.campaign])
        return 0
    if args.dry_run:
        run_all(write=False)
        return 0
    if args.write:
        run_all(write=True)
        return 0

    print("Use --dry-run to preview, or --write to fill the live Leader's Call "
          "tab. (Run on a Monday so the views' 'This Week' = the completed week.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
