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

LEADERS_CALL_SHEET_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
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


def _target_week() -> tuple:
    """(Monday, Sunday) of the just-completed week — the same target every
    campaign fills. On a Monday run this is the week that just ended."""
    import datetime as dt
    from automations.alphalete_org_report.opt_nds import _current_target_week_end
    sun = _current_target_week_end(None)
    return sun - dt.timedelta(days=6), sun


def _je_url() -> str:
    """JE 'Weekly Metrics by Rep' with Sales Week Ending PINNED to the target
    week's Sunday. The view's saved default was stale (stuck at 6/7/2026 on the
    2026-06-29 run). Unlike the ATT 'Time Frame' filter, JE's 'Sales Week Ending'
    IS URL-drivable — but ONLY in ISO format (2026-06-28); the M/D/YYYY form is
    silently ignored (verified 2026-06-29). Same param opt_je.py uses."""
    from urllib.parse import quote
    _, sun = _target_week()
    base = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "JustEnergyRTL-SalesStaffingProductivityWorkbook/WeeklyMetricsbyRep")
    return f"{base}?{quote('Sales Week Ending')}={sun.isoformat()}"


def _box_url() -> str:
    """BOX 'Box Sales Metrics' with 'Sale Date Weekending' PINNED to the target
    week's Sunday. The view's filter defaults to a LAGGING week — on the 2026-07-06
    run it sat on 6/28 (the prior week) instead of the target 7/5, so BOX showed
    last week's numbers. Pin it like JE: the 'Sale Date Weekending' filter IS
    URL-drivable in ISO format (verified 2026-07-07 — set 7/5/2026, data changed)."""
    from urllib.parse import quote
    _, sun = _target_week()
    base = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "B2BBOXEnergyTracker/BoxSalesMetrics?:iid=1")
    return f"{base}&{quote('Sale Date Weekending')}={sun.isoformat()}"


def _costco_url() -> str:
    """The saved "Costco Rep All" custom view (Maud 2026-06-29) — rep-level SARA
    summary with Owner & Office=(All) (the base view was stuck on a single owner
    via the shared profile's RetailNLOrgSalesBoard default). Min/Max Date are
    PINNED to the just-completed week via URL: SARA's real date control is
    Min/Max Date (ignores 'week ending'), and WITHOUT pinning the view defaults
    to the CURRENT in-progress week — empty on a Monday run, so the rep worksheet
    never renders and the Crosstab dialog shows only 'Z_Last Refresh' (the exact
    Monday failure we hit). Rep worksheet = 'Sara Plus Sales Summary (2)'."""
    from urllib.parse import quote
    mon, sun = _target_week()
    base = ("https://us-east-1.online.tableau.com/#/site/sci/views/DropshipV_2/"
            "SARAPLUSSALESSUMMARY/513cb7f6-fba5-4e38-896d-419bcb8010b4/"
            "CostcoRepAll?:iid=1")
    return (f"{base}&{quote('Min Date')}={mon.isoformat()}"
            f"&{quote('Max Date')}={sun.isoformat()}")


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
    exclude_reps: tuple = ()         # rep names ALWAYS dropped (first+last match)
    flag_if_empty: bool = False      # relative-"This Week" view: 0 rows => likely
                                     # the week rolled; FLAG instead of writing 0


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
        flag_if_empty=True,           # relative This Week — guards the week roll
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
        flag_if_empty=True,           # relative This Week — guards the week roll
    ),
    "b2b": Campaign(
        key="b2b",
        # The saved "B2B Leader Recognition" custom view pins Time Frame=This Week
        # (the recognition week), addressed via the :customView= URL param — the
        # B2BLASTWEEK custom view + Time Frame filter can't be driven any other way
        # (URL filter params and interactive clicks both fail; see memory). The
        # relative "This Week" auto-rolls each week, so no weekly re-save (Maud
        # created it 2026-06-29).
        url=("https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/"
             "B2BATTSalesMetrics?:customView=B2B%20Leader%20Recognition"),
        crosstab_sheet="Sales.Quality Metrics",
        threshold=12,
        section_title="B2B",
        rep_hdr=("rep",),
        owner_hdr=("owner name", "owner"),
        value_hdr=("sales",),          # the 'Sales' (apps) column, not 'AIR/AWB Sales'
        owners=["Atef Choudhury", "Carlos Hidalgo", "Kevin Driggs"],
        flag_if_empty=True,           # relative This Week (no date cols to check)
    ),
    "box": Campaign(
        key="box",
        # Maud 2026-06-29: B2BBOXEnergyTracker workbook, 'Box Sales Metrics' tab.
        # url pins 'Sale Date Weekending' to the target week (2026-07-07 fix — its
        # filter defaulted to a LAGGING/prior week, so BOX showed last week's #s).
        url=_box_url(),
        crosstab_sheet="Sales Metrics",
        threshold=8,                  # Maud 2026-06-29: 8+ Complete Sales (was 12)
        section_title="BOX",
        rep_hdr=("rep name", "rep"),
        owner_hdr=("owner name", "owner"),
        value_hdr=("complete sales",),   # exact-match column, not Sales/Rep etc.
        owners=[],                        # all reps with 8+ Complete Sales
        flag_if_empty=True,           # pinned week may lag data — flag, don't stale
    ),
    "costco": Campaign(
        key="costco",
        url=_costco_url(),
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
        # Always drop Khalil Mansour from Revenue recognition (Maud 2026-06-29).
        exclude_reps=("Khalil Mansour",),
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
    # The "Costco Rep All" view is Owner & Office=(All) — company-wide (125 reps
    # across every office). Scope to the LOCAL office owners (first+last match),
    # like every other section, so recognition isn't polluted by other offices.
    keep = {_name_tokens(o) for o in camp.owners} if camp.owners else None
    out = []
    for r in rows[1:]:
        rep = (r[ri] if ri < len(r) else "").strip()
        if not rep or rep.lower() in ("total", "grand total"):
            continue
        owner = re.sub(r"\s*\[.*", "", (r[oi] if oi is not None and oi < len(r)
                                        else "")).replace("\n", " ").strip()
        if keep is not None and _name_tokens(owner) not in keep:
            continue
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

# Only these four ICDs run Costco (Maud 2026-06-29). The "Costco Rep All" view is
# company-wide (Owner & Office=All), so scope to exactly these owners.
COSTCO_OWNERS = ["Amjad Malhas", "Ana Griffin", "Ronald Dawson",
                 "Boaktear Chowdhury"]
CAMPAIGNS["costco"].owners = COSTCO_OWNERS


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


def _is_excluded(camp: Campaign, rep: str) -> bool:
    """True if `rep` is on the campaign's always-drop list (first+last match, so
    'Khalil Mansour' drops regardless of middle name / spacing)."""
    if not camp.exclude_reps:
        return False
    keys = {_name_tokens(x) for x in camp.exclude_reps}
    return _name_tokens(rep) in keys


def parse(camp: Campaign, rows: list[list[str]]) -> list[tuple]:
    out = _parse_inner(camp, rows)
    if camp.exclude_reps:
        out = [t for t in out if not _is_excluded(camp, t[0])]
    return out


def _parse_inner(camp: Campaign, rows: list[list[str]]) -> list[tuple]:
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


TABLEAU_ORDER = ["fiber", "nds", "b2b", "box", "costco", "revenue"]   # JE dropped (Carlos)

# Heavy Tableau vizzes (notably Costco's SARA view and BOX) intermittently fail
# to render in time — the Crosstab dialog shows only the 'Z_Last Refresh' thumb,
# or the download toolbar 120s-timeouts. Every other report in this repo retries
# these exact flakes (see download_crosstab_patchright); the Leader's Call pull
# historically did NOT, so a single flake dropped the section. Retry on a fresh
# navigation before giving up.
PULL_ATTEMPTS = 3
_PULL_SETTLE_MS = 6000


class PullFailure:
    """Sentinel: a Tableau pull/parse that failed after every retry. DISTINCT
    from None (a section legitimately left as-is, e.g. Frontier with no upload),
    so write_report flags it loudly and NEVER leaves stale numbers in its place."""
    def __init__(self, key: str, msg: str):
        self.key = key
        self.msg = msg


_DATE_PAREN_RE = re.compile(r"\((\d{1,2})-(\d{1,2})\)")        # Fiber 'Mon (06-22)'
_DATE_SLASH_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/\d{4}\b")  # NDS '6/28/2026'


def _extract_week_dates(rows: list[list[str]]) -> list[tuple]:
    """(month, day) pairs found in the crosstab's header rows — Fiber's
    'Mon (06-22)' day columns and NDS's '6/28/2026' week-ending cells. Empty when
    the worksheet carries no dates (B2B/JE/Costco rep sheets)."""
    out = []
    for r in rows[:4]:
        for c in r:
            c = c or ""
            for mth, day in _DATE_PAREN_RE.findall(c):
                out.append((int(mth), int(day)))
            for mth, day in _DATE_SLASH_RE.findall(c):
                out.append((int(mth), int(day)))
    return out


def _week_ok(rows: list[list[str]]) -> Optional[bool]:
    """True if EVERY date in the crosstab header falls inside the target
    completed week; False if any date is outside (the view's 'This Week' rolled
    to a different week); None if the worksheet has no dates to check."""
    import datetime as dt
    mon, sun = _target_week()
    target = {((mon + dt.timedelta(days=i)).month,
               (mon + dt.timedelta(days=i)).day) for i in range(7)}
    dates = _extract_week_dates(rows)
    if not dates:
        return None
    return all(md in target for md in dates)


def _pull_parse(camp: Campaign, page):
    """Pull + parse one campaign's crosstab, retrying transient Tableau render
    flakes on a fresh navigation. Returns the parsed [(rep,owner,val)] rows, or a
    PullFailure sentinel if every attempt fails — callers must treat that as a
    hard error and must never fall back to stale data.

    WEEK GUARD: every pull is checked against the target completed week. If the
    crosstab's dated columns are for a DIFFERENT week (the relative 'This Week'
    filter rolled — e.g. an off-hours run after the new week's data loaded), it's
    flagged, never written. For relative-week views with no date columns to read
    (flag_if_empty, e.g. B2B), a 0-row result is treated the same way."""
    from automations.alphalete_org_report.opt_nds import _read_tab_csv
    import datetime as dt
    mon, sun = _target_week()
    wk = f"{mon.isoformat()}..{sun.isoformat()}"
    last = ""
    for attempt in range(1, PULL_ATTEMPTS + 1):
        try:
            path = _pull(camp, page)
            rows = _read_tab_csv(path)
            res = parse(camp, rows)
            # Hard week mismatch (dated columns say a different week): definitive,
            # don't retry — the week won't change on a re-pull.
            if _week_ok(rows) is False:
                got = sorted({f"{m:02d}-{d:02d}" for m, d in _extract_week_dates(rows)})
                return PullFailure(camp.key,
                                   f"WRONG WEEK: data is for {got}, expected {wk}")
            # Relative-week view with no dates (B2B): 0 rows usually means the
            # week rolled to the new empty week. Retry (could be a flake), then flag.
            if camp.flag_if_empty and not res:
                last = f"0 rows (possible rolled/empty week, expected {wk})"
                print(f"  ⚠ {camp.key}: empty result — attempt {attempt}/"
                      f"{PULL_ATTEMPTS}", flush=True)
                if attempt < PULL_ATTEMPTS:
                    page.wait_for_timeout(_PULL_SETTLE_MS)
                    continue
                return PullFailure(camp.key, f"0 rows after {PULL_ATTEMPTS} tries — "
                                   f"likely the week hasn't rolled to {wk} yet; "
                                   "verify run timing")
            return res
        except Exception as e:
            last = str(e).splitlines()[0][:160]
            print(f"  ⚠ {camp.key}: pull attempt {attempt}/{PULL_ATTEMPTS} "
                  f"failed ({last})", flush=True)
            if attempt < PULL_ATTEMPTS:
                try:
                    page.wait_for_timeout(_PULL_SETTLE_MS)  # let render settle
                except Exception:
                    pass
    return PullFailure(camp.key, last)

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
        if isinstance(rows, PullFailure):
            # NEVER leave stale numbers for a failed pull: overwrite the section
            # with one visible failure marker so it's obvious it didn't update.
            body = [[f"⚠ PULL FAILED — not updated this week; re-run the report "
                     f"({rows.msg[:50]})", "", ""]]
            label = "FAIL"
        else:
            body = [[rep, owner, _fmt_value(title, val)] for rep, owner, val in rows]
            label = "ok"
        new_count = len(body)
        if dry_run:
            tag = " [FAILURE marker]" if label == "FAIL" else ""
            log.append(f"[dry/{label}] {title}: rows {old_count} -> {new_count} "
                       f"(write A{data_start}:C{data_start + new_count - 1}){tag}")
            continue
        diff = new_count - old_count
        if diff > 0:
            rfill._retry(ws.insert_rows, [[""] * 3] * diff, data_start)
        elif diff < 0:
            rfill._retry(ws.delete_rows, data_start, data_start - diff - 1)
        if new_count:
            rng = f"A{data_start}:C{data_start + new_count - 1}"
            rfill._retry(ws.update, rng, body, value_input_option="USER_ENTERED")
        log.append(f"[{label}] {title}: wrote {new_count} rows at A{data_start}")
    return log


def run_all(write: bool = False) -> dict:
    """Pull + parse every Tableau campaign in ONE session and print each
    section. With write=True, also write the results into the live Leader's
    Call tab (Frontier is left as-is unless its preflight upload was parsed).
    Returns {section_title: [(rep, owner, value)]}."""
    from automations.shared.tableau_patchright import tableau_session
    results: dict = {}
    with tableau_session(verbose=True) as page:
        for k in TABLEAU_ORDER:
            camp = CAMPAIGNS[k]
            res = _pull_parse(camp, page)         # retries flakes internally
            results[camp.section_title] = res
            if isinstance(res, PullFailure):
                print(f"\n✗ {camp.section_title}: FAILED after {PULL_ATTEMPTS} "
                      f"attempts ({res.msg}) — will be flagged, not left stale",
                      flush=True)
                continue
            print(f"\n=== {camp.section_title}: {len(res)} >= {camp.threshold} ===",
                  flush=True)
            for rep, owner, val in res:
                v = f"${val:,.0f}" if camp.threshold >= 100 else f"{val:g}"
                print(f"   {rep} | {owner} | {v}", flush=True)
    # Frontier removed from the recognition (Maud 2026-06-29). The section is no
    # longer pulled or written; the frontier.py / frontier_email.py modules and
    # the read-only Gmail token are now dormant.

    if write:
        sh, ws = _open_tab()
        print("\n--- writing Leader's Call tab ---", flush=True)
        for ln in write_report(ws, results, dry_run=False):
            print("  " + ln, flush=True)
    return results


def _failed_sections(results: dict) -> list:
    """Section titles whose Tableau pull failed (PullFailure sentinel) — used to
    set a non-zero exit so the Hub flags the run instead of reporting success."""
    return [t for t, v in results.items() if isinstance(v, PullFailure)]


# Who the finished PDF goes to on Slack (as Lucy) after a clean run — the
# Leader's Call group: Maud + Carlos + Rafael (ids avoid needing users:read on
# Lucy's token). Override with LEADERS_CALL_PDF_SLACK_USERS (comma-separated
# ids/emails/names). Sent as ONE group DM if Lucy has mpim:write, else as
# individual DMs (slack_metrics_post.dm_users_with_file falls back automatically).
import os as _os
PDF_SLACK_RECIPIENTS = [
    u.strip() for u in _os.environ.get(
        "LEADERS_CALL_PDF_SLACK_USERS",
        "U045USN7NCD,U046G04P5LG,U045Z8N0ZQC,U04G5HJBGFN").split(",") if u.strip()
]  # Maud Miller, Carlos Hidalgo, Rafael Hidalgo, Megan Hidalgo (added 2026-07-21)


_NOTE_SYS = (
    "You tidy short recognition notes for a sales team's weekly slide. Rewrite the note "
    "so it is clear, concise, and grammatically correct: fix spelling, grammar, and "
    "spacing, and drop shouting punctuation. Do NOT add any fact that isn't in the "
    "original. Use gender-neutral phrasing (they/their) — never guess someone's gender. "
    "Keep it to one short sentence. Reply with ONLY the cleaned note, no quotes.")
_NOTE_MODEL = "claude-haiku-4-5-20251001"


def _light_clean(raw: str) -> str:
    s = re.sub(r"\s+", " ", (raw or "").strip())
    s = re.sub(r"([!?.])\1{1,}", r"\1", s)
    if s:
        s = s[0].upper() + s[1:]
        if s[-1] not in ".!?":
            s += "."
    return s


def _polish_note(raw: str) -> str:
    """AI-tidy an ICD's extra-recognition note (grammar/wording only — never invents).
    Falls back to a light rule-based clean if the key/SDK is unavailable."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        from automations.brand_audit import credentials
        import anthropic
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
        resp = client.messages.create(model=_NOTE_MODEL, max_tokens=120, system=_NOTE_SYS,
                                       messages=[{"role": "user", "content": raw}])
        out = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "").strip()
        return out or _light_clean(raw)
    except Exception as e:  # noqa: BLE001 — never fail the deck over note polish
        print(f"[promotions] note polish fell back ({type(e).__name__}) for {raw[:40]!r}",
              flush=True)
        return _light_clean(raw)


def _fetch_promotions() -> list:
    """This week's promotions from Maud's recognition sheet tab: (rep, trainer, owner,
    level, cleaned note). Best-effort — returns [] on any error so the deck still builds."""
    try:
        from automations.leaders_call.recognition_tab import (RECOGNITION_SHEET_ID,
                                                              week_tab_name)
        from automations.recruiting_report import fill as rfill
        client = rfill._client()
        sh = rfill.open_by_key(RECOGNITION_SHEET_ID, client)
        name = week_tab_name()
        titles = [w.title for w in rfill._retry(sh.worksheets)]
        if name not in titles:
            print(f"[promotions] tab {name!r} not found — no promotions this run", flush=True)
            return []
        ws = rfill._retry(sh.worksheet, name)
        vals = rfill._retry(ws.get_values, "A3:E300")
        promos = []
        for r in vals[1:]:                              # skip the header row (row 3)
            rep = (r[0] if len(r) > 0 else "").strip()
            level = (r[3] if len(r) > 3 else "").strip()
            if not rep or not level:
                continue
            trainer = (r[1] if len(r) > 1 else "").strip()
            owner = (r[2] if len(r) > 2 else "").strip()
            note = (r[4] if len(r) > 4 else "").strip()
            promos.append((rep, trainer, owner, level, _polish_note(note)))
        print(f"[promotions] {len(promos)} promotion(s) from {name!r}", flush=True)
        return promos
    except Exception as e:  # noqa: BLE001
        print(f"[promotions] fetch failed ({type(e).__name__}: {str(e)[:120]}) — skipping",
              flush=True)
        return []


def _build_recognition_pdf(results: dict) -> None:
    """Generate the Alphalete Leader's Call PDF from a CLEAN run's results and
    DM it to the PDF_SLACK_RECIPIENTS group on Slack (as Lucy). Only called when
    no section failed (see main). PDF or Slack errors are logged but do NOT fail
    the run — the sheet is already correctly written."""
    _, sun = _target_week()
    try:
        from automations.leaders_call import build_pdf as pdf
        out = OUTPUT_DIR / f"alphalete_leaders_call_{sun.isoformat()}.pdf"
        promos = _fetch_promotions()
        pdf.build_pdf(results, out, pdf.qualifiers_from_campaigns(), promotions=promos)
        print(f"📄 Leader's Call PDF generated: {out}", flush=True)
    except Exception as e:
        print(f"⚠ PDF generation failed ({type(e).__name__}: {str(e)[:140]}) — "
              "the sheet is written; PDF can be re-built separately.", flush=True)
        return
    try:
        from automations.shared import slack_metrics_post as slack
        res = slack.dm_users_with_file(
            out, users=PDF_SLACK_RECIPIENTS, file_name=out.name,
            # Use the provisioned 'Lucy Reporting' USER token (slack-user-token,
            # the same one the metrics posts use) — the separate bot-app token
            # (SLACK_BOT_TOKEN) was never created, so as_bot=True fails on the mini.
            as_bot=False,
            comment=f"📣 Alphalete Leader's Call — recognition for the week ending "
                    f"{sun.month}/{sun.day}.")
        print(f"📨 PDF delivered to {len(PDF_SLACK_RECIPIENTS)} recipient(s) on Slack "
              f"(mode={res.get('mode')}, ok={res.get('ok')})", flush=True)
        # Mark the "Leader's Call - Weekly Recognition" Hub card GREEN once the PDF
        # actually went out (Megan 2026-07-21). This runs on its own Mon 2pm launchd
        # job, not the 4am batch, so nothing else marks the card — gate on the send
        # succeeding so a failed DM never shows green. Best-effort: never fail the
        # run over a Hub write.
        if res.get("ok"):
            try:
                from automations.day_orchestrator import hub_publish
                hub_publish.publish_done("leaders_call",
                                         "Leader's Call - Weekly Recognition",
                                         status="success")
            except Exception:
                pass
    except Exception as e:
        print(f"⚠ Slack delivery to the Leader's Call group failed "
              f"({type(e).__name__}: {str(e)[:140]}) — the PDF is saved at {out}.",
              flush=True)


# The 7:30pm final pass posts the finished deck to these Slack channels AS Lucy
# (Megan 2026-07-21: top-leaders + gp-sales, replacing the old group DM). Lucy must
# be a MEMBER of each channel to upload the file.
FINAL_CHANNELS = [
    ("top-leaders-alphalete-org", "C067TTGFEFR"),
    ("alphalete-gp-sales",        "C07J46MQNUX"),
]
# The message posted above the deck (the "flyer") — call-to-join (Megan 2026-07-21).
CALL_TIME = "8:45"
ZOOM_URL = "https://us02web.zoom.us/j/7567334591"


def _post_pdf_to_channels(pdf_path, week_end, dry_run: bool = False) -> list:
    from pathlib import Path as _P
    name = _P(pdf_path).name
    comment = (f"🐺 Alphalete Leader's Call — Weekly Recognition\n"
               f"Join the Leader's Call at {CALL_TIME} tonight!  {ZOOM_URL}")
    out = []
    for chan, cid in FINAL_CHANNELS:
        if dry_run:
            print(f"  [dry-run] WOULD post {name} to #{chan} ({cid}) as Lucy", flush=True)
            out.append({"channel": chan, "dry_run": True})
            continue
        try:
            from automations.shared import slack_metrics_post as smp
            resp = smp._client().files_upload_v2(channel=cid, file=str(pdf_path),
                                                 filename=name, initial_comment=comment)
            ok = bool(resp.get("ok"))
            print(f"  #{chan}: {'posted ✓' if ok else 'ok=false'}", flush=True)
            out.append({"channel": chan, "ok": ok})
        except Exception as e:  # noqa: BLE001
            print(f"  #{chan}: FAILED — {type(e).__name__}: {str(e)[:140]}", flush=True)
            out.append({"channel": chan, "ok": False, "error": str(e)})
    return out


def _finalize(dry_run: bool = False) -> int:
    """The 7:30pm final pass: rebuild the deck from the tab (2pm campaign data) + the
    now-complete promotions, then post the PDF to the leadership Slack channels. No
    Tableau pull — the 2pm --write run already filled the tab."""
    from automations.leaders_call import build_pdf as pdf
    results = _results_from_tab()
    n = sum(len(v) for v in results.values())
    sun = _target_week()[1]
    out = OUTPUT_DIR / f"alphalete_leaders_call_{sun.isoformat()}.pdf"
    promos = _fetch_promotions()
    pdf.build_pdf(results, out, pdf.qualifiers_from_campaigns(), promotions=promos)
    print(f"📄 Final deck built ({n} rows, {len(promos)} promotions): {out}", flush=True)
    posts = _post_pdf_to_channels(out, sun, dry_run=dry_run)
    if not dry_run and any(p.get("ok") for p in posts):
        try:
            from automations.day_orchestrator import hub_publish
            hub_publish.publish_done("leaders_call", "Leader's Call - Weekly Recognition",
                                     status="success")
        except Exception:
            pass
    failed = [p["channel"] for p in posts if not p.get("ok") and not p.get("dry_run")]
    if failed:
        print(f"❌ Channel post failed: {', '.join(failed)} — is Lucy a member?", flush=True)
        return 1
    return 0


def _results_from_tab() -> dict:
    """Read the live Leader's Call tab into {section_title: [(rep, owner, value)]} —
    the inverse of write_report. Lets --pdf-only rebuild the deck from already-written
    data (no Tableau pull, no DM), e.g. to self-test the PDF build on the mini."""
    from automations.recruiting_report import fill as rfill
    _, ws = _open_tab()
    grid = rfill._retry(ws.get_all_values)
    colA = [(r[0] if r else "") for r in grid]
    found = []
    for i, a in enumerate(colA):
        for title, rx in SECTION_MATCH.items():
            if rx.search(a or ""):
                found.append((title, i))
                break
    found.sort(key=lambda t: t[1])
    results = {}
    for k, (title, r) in enumerate(found):
        nxt = found[k + 1][1] if k + 1 < len(found) else len(grid)
        rows = []
        for row in grid[r + 2:nxt]:
            rep = (row[0] if row else "").strip()
            if not rep:
                continue
            owner = (row[1] if len(row) > 1 else "").strip()
            raw = (row[2] if len(row) > 2 else "").replace("$", "").replace(",", "").strip()
            try:
                val = float(raw)
            except ValueError:
                continue
            rows.append((rep, owner, val))
        results[title] = rows
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
    ap.add_argument("--pdf-only", action="store_true",
                    help="rebuild the recognition PDF from the current tab data "
                         "(no Tableau pull, no DM) — a self-test / offline rebuild.")
    ap.add_argument("--no-pdf", action="store_true",
                    help="with --write: pull + write the tab only (no PDF/send); the "
                         "PDF + channel post is deferred to the 7:30pm --finalize pass.")
    ap.add_argument("--finalize", action="store_true",
                    help="the 7:30pm pass — rebuild the deck from the tab + final "
                         "promotions and POST it to the leadership Slack channels. "
                         "Add --dry-run to build + preview without posting.")
    args = ap.parse_args()

    if args.finalize:
        return _finalize(dry_run=args.dry_run)
    if args.pdf_only:
        from automations.leaders_call import build_pdf as pdf
        results = _results_from_tab()
        n = sum(len(v) for v in results.values())
        sun = _target_week()[1]
        out = OUTPUT_DIR / f"alphalete_leaders_call_{sun.isoformat()}.pdf"
        promos = _fetch_promotions()
        pdf.build_pdf(results, out, pdf.qualifiers_from_campaigns(), promotions=promos)
        print(f"📄 PDF rebuilt from the tab ({n} rows across {len(results)} sections, "
              f"{len(promos)} promotions) — no Tableau pull, no DM: {out}", flush=True)
        return 0

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
        results = run_all(write=False)
        return 1 if _failed_sections(results) else 0
    if args.write:
        results = run_all(write=True)
        failed = _failed_sections(results)
        if failed:
            print(f"\n❌ {len(failed)} section(s) failed to pull and were FLAGGED "
                  f"in the sheet (not left stale): {', '.join(failed)}. Re-run the "
                  "report to refresh them.", flush=True)
            print("   ⏸ Recognition PDF NOT generated — it only builds when every "
                  "section pulled cleanly.", flush=True)
            return 1
        print("\n✅ All sections pulled and written for this week.", flush=True)
        if args.no_pdf:
            print("   (--no-pdf: tab written; the PDF + channel post runs in the "
                  "7:30pm finalize pass.)", flush=True)
            return 0
        # GATE: only build the Leader's Call PDF on a fully-clean pull (Maud
        # 2026-06-29). Nothing failed here, so generate it from the same results.
        _build_recognition_pdf(results)
        return 0

    print("Use --dry-run to preview, or --write to fill the live Leader's Call "
          "tab. (Run on a Monday so the views' 'This Week' = the completed week.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
