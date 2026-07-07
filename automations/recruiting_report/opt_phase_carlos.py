"""Carlos OPT phase — pull rows 29, 33-37, 40, 41, 43, 44, 45-49, 50, 51
on the Carlos 1on1s - Focus Report sheet from 6 Tableau views.

Mirrors `opt_phase.py` (Raf's pipeline) but Carlos's metric set + Tableau
views are completely different, so this is a parallel module rather than
a refactor of opt_phase. Both reuse `fill._client()` + the captainship-
aware constants from fill.py.

Source of truth for what comes from where:
  resources/opt-section/carlos-tableau-source-map.md

Manual / formula / computed rows are NEVER touched:
  27, 28, 30, 31  — manual entry (humans only)
  32              — formula (would clobber the =formula expression)
  38, 39          — computed by this script from scraped values, written
                    as numeric values (not formulas)

Run:
    CAPTAINSHIP=Carlos .venv/bin/python -m automations.recruiting_report.opt_phase_carlos --test-view d2d1
    CAPTAINSHIP=Carlos .venv/bin/python -m automations.recruiting_report.opt_phase_carlos --dry-run

Prereq: debug Chrome at :9222 with Tableau logged in (SSO via ownerville).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import fill

WORKSPACE = Path(__file__).resolve().parent.parent.parent
DOWNLOAD_DIR = WORKSPACE / "output" / "carlos_opt_downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# View config — one entry per Tableau view we pull from
# ---------------------------------------------------------------------------
@dataclass
class ViewMetric:
    """One value to lift out of a view's crosstab."""
    sheet_row: int                # Carlos sheet row to write to
    tableau_column: str           # exact header text in the downloaded CSV
    is_global: bool = False       # True = single value broadcast to all 32 tabs
                                  # (e.g. national avg at bottom of view)
    transform: Optional[Callable] = None   # optional value-massage fn


def _strip_office_suffix(s: str) -> str:
    """For 'AARON CORSO\\n [cor consulting agency, inc.]' return 'AARON CORSO'.
    Cancel / Activation / Churn views key on 'Owner & Office' which packs
    the company in a newline-then-brackets suffix."""
    return (s or "").split("\n")[0].strip()


def _parse_csv_num(s) -> float:
    """Tableau CSV cells may have '%', commas, or be blank. Coerce to a
    float; return 0.0 for unparseable / empty."""
    s = (str(s) if s is not None else "").strip().rstrip("%").replace(",", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _aggregate_penetration(rows: list) -> dict:
    """Penetration is ZIP-level — each owner has many rows. Tableau rolls
    'Actual Pen %' up at the owner level as
        sum(Actual Sales) / ICD Workable Lead Count
    (verified against Adrian Sarabia 2026-05-20: 875 / 41,780 = 2.09%
    matches what Megan sees in Tableau)."""
    if not rows:
        return {}
    total_actual = sum(_parse_csv_num(r.get("Actual Sales")) for r in rows)
    # 'ICD Workable Lead Count' is owner-constant — same on every row.
    icd_wlc = _parse_csv_num(rows[0].get("ICD Workable Lead Count"))
    if not icd_wlc:
        return {}
    return {50: total_actual / icd_wlc}


@dataclass
class ViewConfig:
    """One Tableau view we visit + which metrics we pull from it."""
    key: str                      # short id for CLI --test-view
    url: str                      # full Tableau URL
    sheet_thumbnail_match: str    # substring used to find the right
                                  # Download → Crosstab thumbnail
    metrics: List[ViewMetric] = field(default_factory=list)
    notes: str = ""
    # Per-view CSV parsing config — defaults work for the simple d2d1
    # layout; other views override.
    key_column: str = "ICD Owner Name"        # CSV col that has the owner name
    key_clean: Optional[Callable[[str], str]] = None  # optional cleaner fn
    subrow_column: str = ""                   # if non-empty, filter rows by
    subrow_value: str = ""                    # this col's value matching this
    # Some views (DD) have crosstab that's heavily user-filtered. Setting
    # `download_mode = "data"` clicks Download → Data → Full Data instead
    # of Download → Crosstab. The "data" path exports underlying records
    # (often per-row) and bypasses some view-level filtering.
    download_mode: str = "crosstab"           # "crosstab" or "data"
    # When a view has MANY rows per owner (penetration is ZIP-level, ~37 rows
    # per ICD), `aggregator` collapses them into one {sheet_row: value} dict.
    # If set, the parser keeps ALL rows per owner instead of last-write-wins,
    # and `aggregator(rows)` computes the metric value(s). When None,
    # values_for_icd reads the configured columns from the single stored row.
    aggregator: Optional[Callable[[list], dict]] = None
    # When set, empty/missing column values get this placeholder written
    # instead of being skipped. Used by churn (some buckets have no data
    # yet for new offices) — Megan wants the cells filled with a clear
    # text marker rather than left blank.
    empty_placeholder: Optional[str] = None
    # Tableau filter field that pins the view to a specific week. WITHOUT
    # this the crosstab exports whatever week Tableau shows at download time
    # — on a Monday that's the brand-new in-progress week, so churn comes
    # back empty ('No Data In Tableau') and sales bleed in from the prior
    # week (Eve 2026-06-01). Default matches the ATT workbooks' shared
    # 'Sale Date Week Ending (mon-sun)' filter (same one opt_phase._week_url
    # and focus_office_att use). Set to None for views with no week filter
    # (e.g. cumulative Direct Deposit).
    week_filter_field: Optional[str] = "Sale Date Week Ending (mon-sun)"
    # Extra render wait (ms) before opening Download → Crosstab. HEAVY sheets
    # (the base B2BATTSalesMetrics dashboard's 'Sales.Quality Metrics') render a
    # few seconds AFTER the toolbar appears; opening the dialog too early lists
    # only the light sheets and the target thumbnail is missing. None = use the
    # global VIZ_RENDER_WAIT_MS. (Belt-and-suspenders with the reopen-retry.)
    render_wait_ms: Optional[int] = None
    # numberFormat pattern to STAMP on this view's metric cells after writing,
    # so percents render consistently regardless of the cell's prior format
    # (some tabs were '0.00%', some '0%', some unformatted -> raw 0.04). Values
    # are stored as plain decimals; the format controls display. Megan
    # 2026-06-01: churn keeps 2 decimals ('0.00%'), the rest are whole ('0%').
    percent_format: Optional[str] = None


# All 6 Carlos OPT-phase Tableau views, per
# resources/opt-section/carlos-tableau-source-map.md.
VIEWS: List[ViewConfig] = [
    ViewConfig(
        key="d2d1",
        # ALLTEAMS custom view (team filter = All) saved 2026-06-01. The base
        # view kept auto-restoring a broken 'Luis's Team' custom view that
        # filtered OUT every Carlos ICD not on Luis's team (→ wrong/duplicated
        # numbers). This view pins the team filter to All; the parser still
        # narrows to Carlos's tab list. No week filter — the dashboard is
        # hardwired to "B2B - Current Week" (week_filter_field=None).
        url="https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/D2D1-PAGERV3/49e48afc-de23-4d5d-98ad-e8b1b246d640/ALLTEAMS",
        week_filter_field=None,
        # The workbook holds 14 worksheets; the one with our per-ICD
        # metrics (Rep Count / voice / wireless / AIR/AWB / totals / rank)
        # is "ICD Summary - ATT (V2) (TW) (3)" — TW = This Week. The
        # "(3)" suffix is Tableau's dedup counter; substring-matching
        # without it survives sheet re-saves that bump the counter.
        sheet_thumbnail_match="ICD Summary - ATT (V2) (TW)",
        metrics=[
            # Exact case-sensitive header text from the downloaded CSV
            # (verified 2026-05-20 via --test-view d2d1). Don't simplify
            # to lowercase — column matching uses these strings verbatim.
            ViewMetric(sheet_row=29, tableau_column="Rep Count"),
            ViewMetric(sheet_row=33, tableau_column="New Intrnt Sales"),
            ViewMetric(sheet_row=34, tableau_column="Voice Count"),
            ViewMetric(sheet_row=35, tableau_column="Wrls Sales"),
            ViewMetric(sheet_row=36, tableau_column="AIR/AWB Sales"),
            # Row 37 (Total Apps) is NOT a column in this view — it's the
            # sum of rows 33+34+35+36. We compute it in Python.
            ViewMetric(sheet_row=40, tableau_column="Sales / Rep", is_global=True),
            ViewMetric(sheet_row=41, tableau_column="Ranking"),
        ],
        notes="7 columns + 1 computed sum (row 37). The view includes ALL "
              "B2B ICDs (~78), not just Carlos's 32 — parser filters by tab list.",
    ),
    ViewConfig(
        key="cancel",
        url="https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/B2BCancelRates",
        percent_format="0%",   # whole-number percent
        sheet_thumbnail_match="Cancel Rates Sheet",
        # Owner & Office cell looks like 'AARON CORSO\n [cor consulting agency, inc.]';
        # 3 rows per ICD (Cancel Rates / Canceled Orders / Unit Count) — pick the
        # 'Cancel Rates' one. Header for the subrow col is empty string in the CSV.
        key_column="Owner & Office",
        key_clean=_strip_office_suffix,
        subrow_column="",
        subrow_value="Cancel Rates",
        # ICDs too new to have 6-week-avg data get a visible marker
        # instead of a blank cell.
        empty_placeholder="No Data In Tableau",
        metrics=[
            ViewMetric(sheet_row=43, tableau_column="6 Week Average"),
        ],
    ),
    ViewConfig(
        key="activation",
        url="https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/ACTIVATIONRATES",
        # NO week pin: activation is a rolling day-bucket view (0-7 / 8-14 /
        # ... / 31-60 Days since sale). Pinning it to one week (the blanket
        # default) collapsed it to only the recent buckets, dropping the
        # '31-60 Days' column the report reads → 'No Data In Tableau' for
        # everyone (Megan 2026-06-01). It reads a rolling window, not a week.
        week_filter_field=None,
        sheet_thumbnail_match="Activation Office",
        # Owner & Office; multi-row per ICD ('Activation %' / 'Total Activations' /
        # 'Total Volume'); we want 'Activation %'.
        key_column="Owner & Office",
        key_clean=_strip_office_suffix,
        subrow_column="",
        subrow_value="Activation %",
        percent_format="0%",   # whole-number percent (78%)
        # ICDs whose offices are too new for the 31-60 day window to have
        # closed get the visible 'No Data In Tableau' marker.
        empty_placeholder="No Data In Tableau",
        metrics=[
            ViewMetric(sheet_row=44, tableau_column="31-60 Days"),
        ],
    ),
    ViewConfig(
        key="churn",
        # ALLTEAMCHURN custom view (team filter = All) saved 2026-06-01 — same
        # fix as d2d1: the base view auto-restored a broken 'Luis's Team'
        # custom view that excluded every Carlos ICD not on Luis's team, so
        # their churn came back empty ('No Data In Tableau'). Office-age churn
        # cohorts, not weekly → no week filter (week_filter_field=None).
        url="https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/CHURNRATES/429cb06d-a32e-4d0e-bf06-9acb77587afd/ALLTEAMCHURN",
        week_filter_field=None,
        percent_format="0.00%",   # churn keeps 2 decimals (4.00%)
        sheet_thumbnail_match="ICD Churn",
        # Owner & Office; multi-row per ICD ('Activated SPE/SP' / 'Calculation1 (1)'
        # / 'Churn Rate'); we want 'Churn Rate'. Columns DON'T have the 'Churn'
        # suffix in the CSV — just '0-30 Day', '30 Day', etc.
        key_column="Owner & Office",
        key_clean=_strip_office_suffix,
        subrow_column="",
        subrow_value="Churn Rate",
        # Many ICDs have data in only some buckets (e.g. a 35-day-old office
        # has no '60/90/120 Day' churn yet). Fill empty cells with a clear
        # text marker so the viewer knows the bucket isn't applicable, vs
        # mistaking blank for 0%.
        empty_placeholder="No Data In Tableau",
        metrics=[
            ViewMetric(sheet_row=45, tableau_column="0-30 Day"),
            ViewMetric(sheet_row=46, tableau_column="30 Day"),
            ViewMetric(sheet_row=47, tableau_column="60 Day"),
            ViewMetric(sheet_row=48, tableau_column="90 Day"),
            ViewMetric(sheet_row=49, tableau_column="120 Day"),
        ],
    ),
    ViewConfig(
        key="penetration",
        url="https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/MARKETPERFORMANCEZIPLEVEL",
        percent_format="0%",   # whole-number percent
        sheet_thumbnail_match="Office/Zip Lead Penetration",
        # ZIP-level data — 9608 rows, MANY per owner (~37 rows per ICD,
        # one per ZIP). Per-ZIP 'Actual Pen %' varies; Tableau's owner-
        # level rollup of 'Actual Pen %' is sum(Actual Sales) / ICD
        # Workable Lead Count (verified vs Adrian 2026-05-20: 2.09%).
        # `aggregator` collapses all of an owner's rows into the single
        # owner-level value before we write it.
        key_column="Owner Name",
        aggregator=_aggregate_penetration,
        metrics=[
            # Listed for documentation only; the aggregator is what
            # produces the value at row 50. _to_number doesn't run on
            # aggregator output.
            ViewMetric(sheet_row=50, tableau_column="Actual Pen %"),
        ],
    ),
    ViewConfig(
        key="personal_production",
        # BASE view 'B2BATTSalesMetrics' (was the saved custom view
        # /REPEXPANDED, which BROKE in Tableau — "An error occurred while
        # loading the custom view REP EXPANDED. Re-create the custom view" —
        # so its viz rendered blank and every download/scrape failed, leaving
        # PP stuck at a May-20 cache: identical every week, Megan 2026-06-08).
        # The base 'Sales.Quality Metrics' worksheet is ALREADY rep-level
        # (dimensions Owner Name + Rep — verified live 2026-06-08), and a
        # CROSSTAB export returns the worksheet's full level of detail
        # regardless of visual collapse, so it gives the same per-rep rows the
        # custom view used to. The base view's Download→Crosstab flyout opens
        # cleanly (the custom view's didn't). Week is pinned via the URL
        # 'Sale Date Week Ending (mon-sun)' filter below.
        url="https://us-east-1.online.tableau.com/#/site/sci/views/"
            "ATTTRACKER-B2B/B2BATTSalesMetrics",
        sheet_thumbnail_match="Sales.Quality Metrics",
        render_wait_ms=22_000,  # heavy base dashboard — let the rep table render
        # NO URL week filter. The base dashboard's week control is its canvas
        # "Time Frame" quick filter (defaults to "Last Week" = the just-finished
        # reporting week, which is exactly what the weekly run needs). Appending
        # the ATT workbooks' 'Sale Date Week Ending (mon-sun)' param BLANKS the
        # Sales.Quality Metrics sheet (it isn't a real filter on this dashboard;
        # verified 2026-06-08 — the sheet never renders, so the crosstab can't
        # find it). week_filter_field=None keeps the URL clean.
        week_filter_field=None,
        metrics=[
            ViewMetric(sheet_row=42, tableau_column="Total"),  # placeholder
        ],
        notes="Personal Production — text format. Filters per-ICD where "
              "REP = ICD's name. Pulls only the ICD's own sales, not "
              "the office total. Special-cased in --apply-view loop.",
    ),
    ViewConfig(
        key="dd",
        # Same workbook as Raf's pipeline (Direct Deposit ICD VIEW v2.0,
        # PROGRAM SUMMARY view) but with the "downline or captain" filter
        # flipped from "Captain" to "downline" — Megan saved this state
        # as the DOWNLINEVIEW custom view so Carlos's ICDs appear too.
        # Pure URL filter params didn't work (the user-scope filter
        # applies before URL params); the saved custom view does.
        url="https://us-east-1.online.tableau.com/#/site/sci/views/"
            "DirectDepositICDVIEWVersion2_0/PROGRAMSUMMARY/"
            "15c897de-6162-469b-9ef7-1735d235f2a8/DOWNLINEVIEW",
        sheet_thumbnail_match="",
        metrics=[
            ViewMetric(sheet_row=51, tableau_column="Total $ to ICD"),
        ],
        notes="dd uses View Data scrape (not crosstab). URL filter param "
              "switches from captain-view to downline-view so Carlos's "
              "ICDs appear too. Special-cased in the --apply-view loop.",
    ),
]

# NOTE (2026-07-01): Personal Production is scraped via the CROSSTAB of the
# 'Sales.Quality Metrics' rep worksheet (download_view_crosstab) — the flyout
# opens on the base view and yields the full wide table. A prior View-Data
# scrape approach (activation-click sweep of the multi-sheet dashboard) was
# abandoned: Tableau's View Data Summary is scoped to the ONE measure selected
# in the saved view, so it returned only 'AIR/AWB Sales'. See git history for
# _pp_scrape_autotune if that path is ever needed again.


# Canonical column-B label(s) for each sheet row in our OPT block. The
# writer looks up the actual row by matching ANY listed label in each
# tab's column B (so tabs whose rows have shifted up/down still get data
# in the right cell). A few rows have multiple accepted labels because
# some Carlos tabs (Justin Wood / Luis Salazar / Alex Badawi) use
# abbreviated metric names.
#
# A value can be a single str OR a tuple of acceptable str variants —
# the lookup tries each in order, first match wins.
ROW_TO_LABEL = {
    29: "Active Headcount on Tableau",
    33: "New Internets",
    34: ("Voice Sales", "Voice Count"),
    35: ("Wireless", "Wireless Sales"),
    36: ("New Lines", "AIR / AWB"),
    37: "Total Apps",
    38: "AVG Apps Per Active Headcount",
    39: "AVG New INT Sales",
    40: "National AVG Apps",
    41: "Scorecard Ranking",
    43: "0-30 Day Cancel Rate",
    44: "Activation /Approval %",
    45: "0-30 Day Churn",
    46: "30 Day Churn",
    47: "60 Day Churn",
    48: "90 Day Churn",
    49: "120 Day churn",
    50: "Penetration Rate",
    51: "Direct Deposit",
}

# Rows we MUST NOT touch — manual entry or formula-bearing cells.
DO_NOT_TOUCH_ROWS = {27, 28, 30, 31, 32}


# Personal Production column → label map. Listed in the order Raf's
# pipeline emits ('N NI / N VOIP / N NL / N AIR'); only non-zero
# products appear in the rendered string. Megan: 'Internet Sales > NI,
# VOIP Line Count > VOIP, Wireless Lines > NL, AIR/AWB Sales > AIR'.
PP_PRODUCT_LABELS = [
    ("Internet Sales.", "NI"),
    ("VOIP Line Count", "VOIP"),
    ("Wireless Lines",  "NL"),
    ("AIR/AWB Sales",   "AIR"),
]


def _format_carlos_pp(products: dict) -> str:
    """Render Carlos PP as e.g. '3 NI / 2 NL'. Skips 0 / blank products.
    Returns '-' when nothing to show — matches the existing manual-entry
    convention on Carlos's sheet."""
    parts = []
    for col, label in PP_PRODUCT_LABELS:
        v = products.get(col)
        try:
            n = int(float(str(v).replace(",", ""))) if v not in (None, "", "0") else 0
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            parts.append(f"{n} {label}")
    return " / ".join(parts) if parts else "-"


def _norm_label(s: str) -> str:
    """Normalize a column-B label for matching — lower-cased, collapsed
    whitespace, no leading/trailing spaces, slashes normalized."""
    s = (s or "").strip().lower().replace("/", " / ")
    return " ".join(s.split())


def metric_row_for_tab(col_b: list, label) -> Optional[int]:
    """Return the 1-indexed row in `col_b` where the value matches `label`
    (case + whitespace insensitive). `label` can be a single str or a
    tuple of acceptable variants — first matching label wins. None if
    nothing matches."""
    labels = (label,) if isinstance(label, str) else tuple(label)
    targets = {_norm_label(l) for l in labels}
    for i, v in enumerate(col_b, start=1):
        if _norm_label(v) in targets:
            return i
    return None

# Rows we COMPUTE in Python from other rows (don't read from Tableau).
# Each entry: target_row -> (numerator_row, denominator_row) for division
# OR target_row -> ('sum', [source_rows...]) for sums.
COMPUTED_ROWS = {
    37: ("sum", [33, 34, 35, 36]),    # Total Apps = New INT + Voice + Wireless + AIR/AWB
    38: ("div", 37, 29),              # AVG Apps Per Active Headcount = total apps / headcount
    39: ("div", 33, 29),              # AVG New INT Sales = new internets / headcount
}


# ---------------------------------------------------------------------------
# CSV parsing — Tableau crosstab exports are UTF-16 LE, tab-separated
# ---------------------------------------------------------------------------
def _parse_view_csv(csv_path: Path, key_column: str = "ICD Owner Name",
                    key_clean: Optional[Callable[[str], str]] = None,
                    subrow_column: str = "", subrow_value: str = "",
                    keep_all_rows: bool = False
                    ) -> tuple[list[str], dict, dict]:
    """Read a Tableau crosstab CSV. Returns (headers, by_owner, grand_total).

    Tableau crosstabs export as UTF-16 LE with tabs. The first data row is
    a "Grand Total" aggregate that we keep separate for the global-value
    metrics (e.g. National AVG Apps comes from the grand total's column).

    `key_column` is the CSV column with the owner name. Some views (cancel
    / activation / churn) use "Owner & Office" with the company suffixed
    after a newline — `key_clean` (e.g. `_strip_office_suffix`) extracts
    just the owner name.

    Multi-row-per-owner views (cancel, activation, churn) have several
    rows per ICD, one per metric subtype ("Cancel Rates", "Activation %",
    "Churn Rate"). `subrow_column` + `subrow_value` filter to just the
    right subrow.
    """
    import csv as _csv
    with open(csv_path, encoding="utf-16") as f:
        rows = list(_csv.reader(f, delimiter="\t"))
    if not rows:
        return [], {}, {}
    headers = [h.strip() for h in rows[0]]
    by_owner: dict[str, dict] = {}
    grand_total: dict = {}
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        rec = {h: (v.strip() if v else "") for h, v in zip(headers, r)}
        # Apply the subrow filter — skip rows that aren't the metric subtype
        # we want. For multi-row views this is how we pick ONE row per ICD.
        if subrow_column or subrow_value:
            actual = rec.get(subrow_column, "").strip().lower()
            wanted = subrow_value.strip().lower()
            if actual != wanted:
                continue
        raw_key = rec.get(key_column, "")
        clean = key_clean(raw_key) if key_clean else raw_key
        key = clean.strip().lower()
        if key == "grand total":
            grand_total = rec
        elif key:
            if keep_all_rows:
                by_owner.setdefault(key, []).append(rec)
            elif subrow_column or subrow_value:
                # Subrow-filtered views can have MULTIPLE matching rows
                # per owner (e.g. churn: Carlos has two 'Churn Rate'
                # subrows — one with 0-30/90/120 day data, one with
                # 30/60 day data). Merge them column-by-column so a
                # non-empty value in either survives. Without this we'd
                # silently lose half the data.
                existing = by_owner.get(key, {})
                merged = dict(existing)
                for col, val in rec.items():
                    if val and str(val).strip():
                        merged[col] = val
                by_owner[key] = merged
            else:
                by_owner[key] = rec
    return headers, by_owner, grand_total


def _to_number(s: str):
    """Convert a Tableau cell string to int/float/percent — or pass through
    untouched if it's not a recognized number format."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    # Percent: "31%" → 0.31 (sheet cells with % format display 0.31 as 31%)
    if s.endswith("%"):
        try:
            return float(s.rstrip("%").replace(",", "")) / 100.0
        except ValueError:
            return s
    # Plain number with optional comma thousands
    try:
        if "." in s:
            return float(s.replace(",", ""))
        return int(s.replace(",", ""))
    except ValueError:
        return s


# ---------------------------------------------------------------------------
# Sheet writer — writes a per-ICD column-A:?? batch for the OPT-block rows
# ---------------------------------------------------------------------------
def _carlos_icd_tabs() -> list[str]:
    """Return Carlos's confirmed ICD tab names from office-mapping-carlos.json."""
    mapping = fill.load_mapping()
    return [c["sheet_tab"] for c in mapping["confirmed"]]


def values_for_icd(icd_name: str, by_owner: dict, grand_total: dict,
                   view: ViewConfig,
                   fallback_names: Optional[list[str]] = None) -> dict:
    """Extract this view's metrics for one ICD. Returns {sheet_row: value}.

    Tries `icd_name` first; if not in `by_owner`, walks `fallback_names`
    in order (typically the `as_owner` field from office-mapping-carlos.json
    — Tableau sometimes uses the legal name 'Alexander Badawi' for a tab
    called 'Alex Badawi'). Returns empty dict only when no name matches
    AND the view has no global-row metrics.

    If `view.aggregator` is set, the value at `by_owner[key]` is a LIST
    of records (one per ZIP/whatever) and the aggregator collapses them
    into {sheet_row: value}. Used by views like penetration where the
    per-ICD value has to be computed across many rows."""
    candidates = [icd_name] + list(fallback_names or [])
    found = None
    for cand in candidates:
        key = (cand or "").strip().lower()
        if key and key in by_owner:
            found = by_owner[key]
            break
    if not found and not any(m.is_global for m in view.metrics):
        # ICD isn't in this view's CSV at all. If the view has an
        # empty_placeholder, fill all non-global metric rows with it so
        # the cell is visibly "no data" instead of left blank.
        if view.empty_placeholder is not None:
            return {m.sheet_row: view.empty_placeholder for m in view.metrics
                    if not m.is_global}
        return {}
    out: dict[int, object] = {}
    if view.aggregator and found is not None:
        try:
            agg_input = found if isinstance(found, list) else [found]
            agg_out = view.aggregator(agg_input)
            for row, val in (agg_out or {}).items():
                if val is not None:
                    out[row] = val
        except Exception as e:
            # Don't blow up the whole rollout on one bad ICD's aggregation
            print(f"  ⚠ aggregator failed for {icd_name}: {e}", flush=True)
    else:
        rec = found if not isinstance(found, list) else (found[0] if found else None)
        for m in view.metrics:
            src = grand_total if m.is_global else rec
            if not src:
                # If we have an empty_placeholder, fill the cell anyway
                # so it's visibly "no data" instead of silently blank.
                if view.empty_placeholder is not None:
                    out[m.sheet_row] = view.empty_placeholder
                continue
            raw = src.get(m.tableau_column)
            if raw is None or raw == "":
                if view.empty_placeholder is not None:
                    out[m.sheet_row] = view.empty_placeholder
                continue
            # Always store the decimal (0.04). Percent VIEWS get a '0%'
            # number format set on their cells after the write (percent_format
            # views), so the decimal renders as a whole-number percent ('4%')
            # — consistent across all tabs regardless of the cell's prior
            # format (Megan 2026-06-01: show '78%', not '78.00%' or raw 0.78).
            out[m.sheet_row] = _to_number(raw)
    return out


def apply_computed(values: dict[int, object]) -> dict[int, object]:
    """Apply COMPUTED_ROWS on top of the per-ICD scraped values."""
    out = dict(values)
    for target, spec in COMPUTED_ROWS.items():
        if spec[0] == "sum":
            srcs = spec[1]
            present = [out.get(r) for r in srcs
                       if isinstance(out.get(r), (int, float))]
            if present:
                out[target] = sum(present)
        elif spec[0] == "div":
            _, num_r, den_r = spec
            num, den = out.get(num_r), out.get(den_r)
            if isinstance(num, (int, float)) and isinstance(den, (int, float)) and den:
                out[target] = num / den
    return out


# ---------------------------------------------------------------------------
# Sheet writer
# ---------------------------------------------------------------------------
def _current_we_sunday(today: Optional["dt.date"] = None) -> "dt.date":
    """Return the WE Sunday for the most-recently-completed week.

    Eve runs this report on Mondays AFTER the week ends — she wants the
    just-ended week's column filled, NOT the new in-progress week's
    upcoming-Sunday column.

    For Mon 5/25 returns 5/24 (yesterday Sun = just-ended week's WE).
    For Wed 5/20 returns 5/17 (last Sun before today = last completed
    week). For Sun 5/24 returns 5/17 (today's week isn't fully complete
    until 23:59, so target last Sun's week).

    Caller can override via a CLI flag if they specifically want to
    target a different week (e.g. backfill)."""
    today = today or dt.date.today()
    # Most recent Sunday STRICTLY BEFORE today (or today minus 7 if Sunday)
    days_back = (today.weekday() + 1) % 7 or 7
    return today - dt.timedelta(days=days_back)


def select_time_frame_week(target: "dt.date", verbose: bool = True):
    """Build a pre_download_hook that drives the base B2BATTSalesMetrics
    dashboard's on-canvas 'Time Frame' quick filter to a single week-ending
    Sunday (`target`), for Personal Production back-fills.

    WHY a hook, not a URL param: this dashboard ignores '?Time Frame=…' and
    blanks on '?Sale Date Week Ending (mon-sun)=…' (verified 2026-06-08), so the
    only way to pick a historical week is to click the quick filter:
      open the dropdown → check the target date → UNCHECK 'Last Week' → Apply.
    Clicks target the CHECKBOX (~14px left of the date label) because clicking
    the label text alone doesn't toggle it. The date options render as text
    'YYYY-MM-DD' (Sundays). Never press Escape afterwards — Escape clears the
    applied filter and silently widens the export to every week.
    """
    iso = target.isoformat()

    def _click_checkbox(page, viz, label):
        loc = viz.locator(f'text="{label}"')
        boxes = sorted([b for i in range(loc.count())
                        if (b := loc.nth(i).bounding_box())], key=lambda b: b["y"])
        if not boxes:
            raise RuntimeError(f"Time Frame option '{label}' not found")
        b = boxes[-1]                              # in-list option = lowest on screen
        page.mouse.click(b["x"] - 14, b["y"] + b["height"] / 2)
        page.wait_for_timeout(900)

    def hook(page, viz):
        if verbose:
            print(f"  → Time Frame: selecting week-ending {iso}", flush=True)
        # The hook runs as soon as the Download toolbar button is visible, which
        # can be BEFORE the canvas 'Time Frame' quick filter has rendered. Wait
        # for the filter's 'Last Week' label to appear first (else the open-box
        # lookup finds nothing → "filter box not found").
        try:
            viz.locator('text="Last Week"').first.wait_for(
                state="visible", timeout=25_000)
        except Exception:
            page.wait_for_timeout(4000)   # last resort — give it a beat
        page.wait_for_timeout(1500)
        # Open the collapsed value box (top-most 'Last Week').
        lw = viz.locator('text="Last Week"')
        boxes = sorted([b for i in range(lw.count())
                        if (b := lw.nth(i).bounding_box())], key=lambda b: b["y"])
        if not boxes:
            raise RuntimeError("Time Frame filter box not found")
        top = boxes[0]
        page.mouse.click(top["x"] + top["width"] / 2, top["y"] + top["height"] / 2)
        page.wait_for_timeout(2500)
        _click_checkbox(page, viz, iso)            # check the target week
        _click_checkbox(page, viz, "Last Week")    # uncheck the default
        apply = viz.locator('text="Apply"').first
        if not apply.is_enabled(timeout=3000):
            raise RuntimeError(
                f"Time Frame 'Apply' never enabled selecting {iso} — the "
                f"checkbox clicks didn't register a change.")
        apply.click(timeout=6000)
        page.wait_for_timeout(9000)                # let the heavy sheet re-render
        if verbose:
            print(f"  → Time Frame applied: {iso}", flush=True)

    return hook


def _dd_week_url(url: str, we_sunday: "dt.date") -> str:
    """Pin the Direct Deposit view to a week via its 'Processed Week' filter.
    The filter value is the week's MONDAY in ISO (YYYY-MM-DD) — verified
    2026-06-01: ISO works, MM/DD/YYYY is silently ignored. Works on both the
    base view and the DOWNLINEVIEW custom view, so DD no longer depends on the
    view being hand-advanced each week."""
    from urllib.parse import quote
    monday = we_sunday - dt.timedelta(days=6)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{quote('Processed Week')}={quote(monday.isoformat())}"


def write_icd_values(ws, icd_values: dict[int, object],
                     target_col: int, dry_run: bool = False,
                     row_remap: Optional[dict] = None) -> list[str]:
    """Write `icd_values` ({sheet_row: value}) to one ICD tab's
    `target_col` column. Rows in DO_NOT_TOUCH_ROWS are skipped silently
    so the writer can be called with a dict that includes them.

    `row_remap` translates the canonical sheet_row (from the view config)
    to the actual row on this specific tab — needed because many Carlos
    tabs have rows shifted by ±1 from the master layout. When None, no
    translation happens (the canonical row is used as-is).

    Values are written as a batch (single API call per tab) to keep the
    quota footprint small even when rolling out to 32 tabs.

    Returns a list of human-readable log lines."""
    import gspread.utils as _gu
    log = []
    to_write_canonical = {r: v for r, v in icd_values.items()
                          if r not in DO_NOT_TOUCH_ROWS}
    # Translate canonical rows → actual rows for this tab. If we have a
    # remap but a canonical row isn't in it, the metric is missing from
    # this tab (e.g. the tab's column B has no matching label) — skip it
    # with a warning. Without a remap, fall back to canonical row.
    to_write: dict[int, object] = {}
    missing: list[str] = []
    for canonical_row, val in to_write_canonical.items():
        if row_remap is not None:
            actual_row = row_remap.get(canonical_row)
            if actual_row is None:
                label_or_tuple = ROW_TO_LABEL.get(canonical_row, f"row {canonical_row}")
                # Show the canonical (first) label for the warning, not the full tuple
                label = label_or_tuple[0] if isinstance(label_or_tuple, tuple) else label_or_tuple
                missing.append(label)
                continue
        else:
            actual_row = canonical_row
        to_write[actual_row] = val
    if not to_write and not missing:
        log.append(f"  {ws.title}: nothing to write (all rows in DO_NOT_TOUCH)")
        return log
    if missing:
        log.append(f"  ⚠ {ws.title}: skipped {len(missing)} metric(s) — no "
                   f"matching column-B label: {missing}")
    if not to_write:
        return log
    # gspread batch_update wants A1 ranges. Convert (row, col) → letter.
    col_a1 = _gu.rowcol_to_a1(1, target_col).rstrip("1")
    cells_summary = []
    body = []
    for row, val in sorted(to_write.items()):
        a1 = f"{col_a1}{row}"
        cells_summary.append(f"{a1}={val!r}")
        body.append({"range": a1, "values": [[val]]})
    if dry_run:
        log.append(f"  [DRY-RUN] {ws.title}: would write {len(body)} cell(s) "
                   f"to col {col_a1}")
        for c in cells_summary:
            log.append(f"    {c}")
    else:
        # Go through fill._retry so a Sheets 429 (per-minute write quota)
        # waits out the 60s window and retries instead of crashing the whole
        # apply. This is the ONE write in the OPT apply path that used to
        # bypass the shared retry — DD (the last of 7 views) reliably hit the
        # quota once the 2026-07-01 PP fix added a write burst 45s ahead of it,
        # so DD's batch_update was 429ing with no backoff.
        try:
            fill._retry(ws.batch_update, body, value_input_option="USER_ENTERED")
        except Exception as _e:
            # TEMP DIAGNOSTIC: the mini keeps only 3 lines of stdout, so a write
            # failure's traceback is otherwise unreachable. Persist tab + the
            # exact body + full traceback to a top-level log logtail can read.
            import traceback as _tb
            _dbg = Path("output/logs/carlos-write-debug.log")
            _dbg.parent.mkdir(parents=True, exist_ok=True)
            with _dbg.open("a") as _f:
                _f.write(f"\n=== {ws.title} col {col_a1} FAILED: "
                         f"{type(_e).__name__}: {str(_e)[:300]}\n")
                _f.write(f"body={body!r}\n")
                _f.write(_tb.format_exc())
            raise
        log.append(f"  [OK] {ws.title}: wrote {len(body)} cell(s) "
                   f"to col {col_a1}")
        for c in cells_summary:
            log.append(f"    {c}")
    return log


def _as_owner_by_tab() -> dict[str, str]:
    """Reverse-index of {sheet_tab: as_owner} from the captainship's
    confirmed mapping. Lets the Tableau lookup fall back to the AppStream
    owner name when the sheet tab uses a nickname/short form."""
    mapping = fill.load_mapping()
    return {c["sheet_tab"]: c.get("as_owner", "")
            for c in mapping["confirmed"]}


def apply_view_to_icd(view: ViewConfig, csv_path: Path, ws,
                      target_col: int, dry_run: bool = False,
                      as_owner_by_tab: Optional[dict] = None) -> list[str]:
    """Parse `csv_path`, compute values for one ICD tab, apply
    COMPUTED_ROWS, write to `target_col`. Returns log lines.

    `as_owner_by_tab` is the cached {tab: as_owner} map; if not passed,
    looked up per call (slower for bulk runs). Used as a fallback name
    when the tab title doesn't appear in the Tableau CSV verbatim."""
    log = []
    try:
        headers, by_owner, grand_total = _parse_view_csv(
            csv_path,
            key_column=view.key_column,
            key_clean=view.key_clean,
            subrow_column=view.subrow_column,
            subrow_value=view.subrow_value,
            keep_all_rows=view.aggregator is not None,
        )
    except Exception as e:
        log.append(f"  ⚠ couldn't parse {csv_path.name}: {e}")
        return log
    if as_owner_by_tab is None:
        as_owner_by_tab = _as_owner_by_tab()
    fallback = as_owner_by_tab.get(ws.title, "")
    fallbacks = [fallback] if fallback and fallback.lower() != ws.title.lower() else []
    raw = values_for_icd(ws.title, by_owner, grand_total, view,
                         fallback_names=fallbacks)
    if not raw:
        log.append(f"  ⚠ {ws.title}: no values from {view.key} "
                   f"({len(by_owner)} ICDs in CSV; tried "
                   f"{[ws.title] + fallbacks})")
        return log
    full = apply_computed(raw)
    log.extend(write_icd_values(ws, full, target_col, dry_run))
    return log


# ---------------------------------------------------------------------------
# Download helper — connects to debug Chrome, navigates view, downloads CSV
# ---------------------------------------------------------------------------
def download_view_crosstab(view: ViewConfig, out_path: Path,
                           verbose: bool = True, week=None, page=None,
                           pre_download_hook=None) -> Path:
    """Open `view.url` in the debug-Chrome Tableau tab, click Download →
    Crosstab → pick the right sheet thumbnail → save CSV at `out_path`.

    `week` (a date) pins the view to that WE Sunday via the view's
    `week_filter_field` URL param, so the export is the completed week's
    data — not whatever in-progress week Tableau happens to show at
    download time.

    Reuses the pattern from focus_office_att/step7_download_tableau.py:
    Tableau viz lives in an iframe `[title="Data Visualization"]`; toolbar
    buttons + the crosstab modal use `data-tb-test-id` attributes."""
    # Unattended Tableau login via patchright (ownerville SSO) — replaces the
    # debug-Chrome CDP attach (broken on Chrome 148). Megan 2026-05-25.
    # When a caller passes a shared `page` (one login for the whole Carlos OPT
    # run), reuse it and don't close it; otherwise open a one-shot session.
    # Repeated per-view logins were tripping ownerville's Cloudflare — the
    # login click timed out behind a CF challenge overlay (Eve 2026-06-01).
    import contextlib
    from automations.shared.tableau_patchright import tableau_session

    @contextlib.contextmanager
    def _session_or_shared():
        if page is not None:
            yield page
        else:
            with tableau_session(verbose=verbose) as pg:
                yield pg

    VIZ_RENDER_WAIT_MS = 10_000

    out_path.parent.mkdir(parents=True, exist_ok=True)
    debug_dir = out_path.parent / "_debug" / view.key
    debug_dir.mkdir(parents=True, exist_ok=True)
    with _session_or_shared() as page:

        # The viz toolbar (Download button) sometimes never renders: a heavy
        # rep-expanded workbook can need >30s, OR a saved custom view in the
        # URL (GUID) was deleted — a recurring Tableau problem — and the page
        # shows "view not found" with no toolbar at all. Retry once with a
        # longer timeout to absorb a slow render; on every miss, screenshot
        # the page so a real deletion is diagnosable (the bare timeout used to
        # leave no evidence, which is how this glitch reached the Bug tab).
        download_btn = '[data-tb-test-id="viz-viewer-toolbar-button-download"]'
        viz = page.frame_locator('iframe[title="Data Visualization"]')
        # Pin the view to the target week via its URL filter. Without this the
        # export is whatever week Tableau shows at download time (the broken
        # default). Skipped when the view has no week filter (week_filter_field
        # is None) or no week was passed.
        nav_url = view.url
        if week is not None and view.week_filter_field:
            from urllib.parse import quote
            sep = "&" if "?" in nav_url else "?"
            nav_url = (f"{nav_url}{sep}{quote(view.week_filter_field)}"
                       f"={quote(str(week))}")
            if verbose:
                print(f"  → week-pinned to {week} via "
                      f"'{view.week_filter_field}'", flush=True)
        last_err = None
        for attempt, timeout_ms in enumerate((30_000, 60_000), start=1):
            if verbose:
                tag = f"  (attempt {attempt})" if attempt > 1 else ""
                print(f"  → navigating Tableau tab to: {nav_url}{tag}",
                      flush=True)
            page.goto(nav_url, wait_until="domcontentloaded")
            viz = page.frame_locator('iframe[title="Data Visualization"]')
            if verbose:
                print(f"  → waiting for viz Download button… "
                      f"(timeout {timeout_ms // 1000}s)", flush=True)
            try:
                viz.locator(download_btn).wait_for(
                    state="visible", timeout=timeout_ms)
                last_err = None
                break
            except Exception as e:   # patchright TimeoutError + friends
                last_err = e
                shot = debug_dir / f"00_no_toolbar_attempt{attempt}.png"
                try:
                    page.screenshot(path=str(shot), full_page=True)
                    if verbose:
                        print(f"  ⚠ Download button not visible after "
                              f"{timeout_ms // 1000}s — saved {shot}",
                              flush=True)
                except Exception:
                    pass
        if last_err is not None:
            raise RuntimeError(
                f"Viz toolbar never rendered for view '{view.key}' at "
                f"{view.url} — the viz failed to load. If the URL ends in a "
                f"custom-view name (e.g. /REPEXPANDED), that saved view was "
                f"likely deleted in Tableau; re-save it (or repoint to a base "
                f"view). Screenshots: {debug_dir}"
            ) from last_err
        # Optional hook to manipulate on-canvas filters (e.g. drive the base
        # dashboard's 'Time Frame' quick filter to a specific week-ending date
        # for the backfill) AFTER the viz loads but BEFORE the crosstab dialog
        # opens. The hook should leave the target week applied; the render wait
        # below then lets the heavy sheet re-render before we read it.
        if pre_download_hook is not None:
            pre_download_hook(page, viz)
        page.wait_for_timeout(view.render_wait_ms or VIZ_RENDER_WAIT_MS)

        if verbose:
            print("  → Download → Crosstab → (pick thumbnail) → CSV", flush=True)

        with page.expect_download(timeout=180_000) as dl_info:
            # Open Download → Crosstab, then make sure the TARGET worksheet is
            # actually listed before proceeding. On the base B2BATTSalesMetrics
            # dashboard 'Sales.Quality Metrics' is heavy and renders a few
            # seconds after the toolbar — opening the dialog too early lists only
            # the light sheets ('zzz Last Refresh') and the target thumbnail is
            # missing (Megan 2026-06-08). So we CLOSE + wait + REOPEN (escalating
            # wait) until it appears. force=True punches through Tableau's
            # tab-glass overlay (the click-intercept that left PP stale before).
            dl_btn = viz.locator(
                '[data-tb-test-id="viz-viewer-toolbar-button-download"]')
            xtab_item = viz.locator(
                '[data-tb-test-id="download-flyout-download-crosstab-MenuItem"]')
            thumbs = viz.locator('[data-tb-test-id^="sheet-thumbnail-"]')
            target = view.sheet_thumbnail_match
            thumb_count = 0
            # NEVER press Escape in these retries: on this canvas dashboard Escape
            # CLEARS the applied 'Time Frame' quick filter, which silently widened
            # the crosstab export from one week to every week (137 owners / ~7k
            # rep rows, Megan 2026-06-08). Recover the flyout by re-clicking the
            # toolbar Download button instead — but only when it isn't already
            # open (a blind re-click would TOGGLE an open flyout shut).
            for open_attempt in range(1, 8):
                # Open the Download flyout → Crosstab. On this heavy view the
                # toolbar's download button click intermittently doesn't open the
                # flyout (a tab-glass overlay swallows it). Short timeout + retry
                # the open rather than blocking on a flyout that won't show.
                try:
                    if not xtab_item.is_visible(timeout=1500):
                        dl_btn.click(force=True, timeout=30_000)
                        page.wait_for_timeout(1800)
                    page.screenshot(path=str(debug_dir / "01_download_menu.png"), full_page=True)
                    xtab_item.click(force=True, timeout=10_000)
                    page.wait_for_timeout(2000)
                except Exception as e:
                    if verbose:
                        print(f"  ↻ download flyout didn't open "
                              f"(attempt {open_attempt}/7): {type(e).__name__}; "
                              f"retrying…", flush=True)
                    page.wait_for_timeout(3500 * open_attempt)
                    continue
                page.screenshot(path=str(debug_dir / "02_crosstab_modal.png"), full_page=True)
                thumb_count = thumbs.count()
                names = []
                for i in range(thumb_count):
                    try:
                        names.append(thumbs.nth(i).inner_text(timeout=2000).strip())
                    except Exception as e:
                        names.append(f"<error: {e}>")
                if verbose:
                    print(f"  → modal shows {thumb_count} sheet thumbnail(s): "
                          f"{names}", flush=True)
                present = (not target) or any(target in n for n in names)
                if present:
                    break
                if verbose:
                    print(f"  ↻ target sheet '{target}' not rendered yet "
                          f"(attempt {open_attempt}/7); waiting to reopen…",
                          flush=True)
                # Close the crosstab modal via its Cancel button (filter-safe;
                # NOT Escape) so the next attempt can reopen it after the sheet
                # finishes rendering.
                try:
                    viz.locator('[data-tb-test-id="export-crosstab-cancel-Button"]'
                                ).click(force=True, timeout=4000)
                except Exception:
                    pass
                page.wait_for_timeout(6000 * open_attempt)
            if thumb_count > 0:
                # Tableau auto-selects the first thumbnail by default. If
                # the user's target IS the first thumbnail, our "click to
                # select" would toggle it OFF — leaving nothing selected
                # and the Download button disabled. So: only click the
                # target thumb if the modal's Download button is currently
                # disabled OR our target name doesn't appear to be the
                # currently-active selection.
                #
                # The simplest reliable proxy: check the Download button
                # state. If already enabled, the auto-selection covers
                # what we want — skip the click. If disabled, our target
                # isn't selected, so click it.
                final_btn_probe = viz.locator(
                    '[data-tb-test-id="export-crosstab-export-Button"]'
                )
                try:
                    already_enabled = final_btn_probe.is_enabled(timeout=1500)
                except Exception:
                    already_enabled = False

                need_thumb_click = True
                if already_enabled and not view.sheet_thumbnail_match:
                    # No specific match requested + button already enabled =
                    # auto-selection is fine; don't disturb it.
                    need_thumb_click = False
                elif already_enabled and view.sheet_thumbnail_match:
                    # Specific match requested. If our match is the FIRST
                    # thumbnail (which would be auto-selected), skip the
                    # click; otherwise click it to switch selection.
                    first_text = thumbs.nth(0).inner_text(timeout=2000).strip()
                    if view.sheet_thumbnail_match in first_text:
                        if verbose:
                            print(f"  → target is the auto-selected first "
                                  f"thumbnail; skipping click", flush=True)
                        need_thumb_click = False

                if need_thumb_click:
                    if view.sheet_thumbnail_match:
                        thumb = viz.locator(
                            f'[data-tb-test-id^="sheet-thumbnail-"]'
                            f':has-text("{view.sheet_thumbnail_match}")'
                        ).first
                    else:
                        thumb = thumbs.first
                    thumb.wait_for(state="visible", timeout=15_000)
                    thumb.click(force=True)
                    page.wait_for_timeout(1200)
                    # Verify the Download button enabled within ~3s — if
                    # not, the click didn't register a selection. Retry
                    # with a more specific click on the thumbnail's
                    # internal checkbox / image.
                    try:
                        ok = final_btn_probe.is_enabled(timeout=3000)
                    except Exception:
                        ok = False
                    if not ok:
                        if verbose:
                            print("  ↻ first click didn't enable Download; "
                                  "trying thumb's inner checkbox/image",
                                  flush=True)
                        # Click any clickable child (button, input, img)
                        for inner_sel in ("input", "button", "img", "div"):
                            try:
                                thumb.locator(inner_sel).first.click(force=True, timeout=2000)
                                page.wait_for_timeout(700)
                                if final_btn_probe.is_enabled(timeout=2000):
                                    if verbose:
                                        print(f"  ↺ Download enabled after "
                                              f"clicking inner {inner_sel}",
                                              flush=True)
                                    break
                            except Exception:
                                continue
                page.screenshot(path=str(debug_dir / "03_after_thumb.png"), full_page=True)

            # CSV radio
            viz.locator(
                '[data-tb-test-id="crosstab-options-dialog-radio-csv-Label"]'
            ).click(force=True, timeout=60_000)
            page.wait_for_timeout(500)
            page.screenshot(path=str(debug_dir / "04_after_csv.png"), full_page=True)

            # Final Download — log whether it's enabled before clicking
            final_btn = viz.locator(
                '[data-tb-test-id="export-crosstab-export-Button"]'
            )
            try:
                is_enabled = final_btn.is_enabled(timeout=2000)
            except Exception:
                is_enabled = "?"
            if verbose:
                print(f"  → final Download button enabled? {is_enabled}",
                      flush=True)
            final_btn.click(timeout=20_000)

        dl = dl_info.value
        if verbose:
            print(f"  → download fired: {dl.suggested_filename}", flush=True)
        dl.save_as(str(out_path))
        if verbose:
            print(f"  ✓ saved {out_path} "
                  f"({out_path.stat().st_size:,} bytes)", flush=True)

    return out_path


# ---------------------------------------------------------------------------
# CLI — test mode (one view) + full run
# ---------------------------------------------------------------------------
def main() -> int:
    if fill.CAPTAINSHIP != "Carlos":
        print("This module is Carlos-only. Set CAPTAINSHIP=Carlos before running.",
              file=sys.stderr)
        return 2

    ap = argparse.ArgumentParser()
    ap.add_argument("--test-view", choices=[v.key for v in VIEWS],
                    help="Download a single view's crosstab to inspect "
                         "the CSV format (no Sheet writes). Use this first "
                         "while wiring up each view's parser.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Run the full pipeline but don't write to the Sheet.")
    ap.add_argument("--preview-icd",
                    help="Preview-write one ICD's d2d1-view values to its "
                         "tab. Uses the cached CSV at "
                         "output/carlos_opt_downloads/d2d1.csv (re-download "
                         "via --test-view d2d1 first if stale). Skips the "
                         "no-fly rows automatically.")
    ap.add_argument("--apply-view", choices=[v.key for v in VIEWS],
                    help="Apply one view's cached CSV to ALL Carlos ICD tabs "
                         "(rolls out across the confirmed mapping). Pair with "
                         "--dry-run to preview without writing.")
    ap.add_argument("--cleanup-drift", action="store_true",
                    help="One-time cleanup: scan every tab, find rows where "
                         "our previous row-drift bug wrote data to the wrong "
                         "row (canonical position holds a value matching what "
                         "now lives at the correct position), and clear the "
                         "wrong-row cell. Safe to re-run (idempotent).")
    ap.add_argument("--download-all", action="store_true",
                    help="Download EVERY OPT view (crosstabs + dd View Data) "
                         "to the cache under ONE ownerville login. Run this "
                         "once, then --apply-view <key> --no-download per view "
                         "(no further logins). Avoids the per-view logins that "
                         "trip Cloudflare.")
    ap.add_argument("--no-download", action="store_true",
                    help="On --apply-view, never hit Tableau live — use the "
                         "cached CSV (paired with a prior --download-all). "
                         "Currently only dd does a live scrape; this makes it "
                         "read the cache instead.")
    ap.add_argument("--week",
                    help="WE Sunday (YYYY-MM-DD) to target instead of the "
                         "current completed week. Use to BACKFILL a prior "
                         "column, e.g. `--apply-view dd --week 2026-05-24` "
                         "pins DD's Processed Week to that week's Monday and "
                         "writes the 5/24 column. (dd is the only view that "
                         "can pin an arbitrary week — d2d1/etc. are "
                         "current-week-only, so don't backfill those.)")
    args = ap.parse_args()
    week_override = dt.date.fromisoformat(args.week) if args.week else None

    if args.download_all:
        # ONE ownerville login for the whole Carlos OPT phase. Per-view logins
        # (a fresh browser per view) were tripping Cloudflare's challenge so
        # the login click never completed (Eve 2026-06-01). Download every
        # crosstab + scrape dd through a single shared page.
        from automations.shared.tableau_patchright import tableau_session
        from automations.recruiting_report.opt_phase import scrape_view_data
        we = _current_we_sunday()
        crosstab_views = [v for v in VIEWS
                          if v.key not in ("dd", "personal_production")]
        ok, fails = [], []
        print(f"Downloading ALL Carlos OPT views in ONE login "
              f"(week ending {we})…", flush=True)
        with tableau_session(verbose=True) as page:
            for v in crosstab_views:
                out = DOWNLOAD_DIR / f"{v.key}.csv"
                try:
                    download_view_crosstab(v, out, week=we, page=page)
                    ok.append(v.key)
                except Exception as e:
                    print(f"  ✗ {v.key}: {type(e).__name__}: {str(e)[:160]}",
                          flush=True)
                    fails.append(v.key)
            dd_view = next(v for v in VIEWS if v.key == "dd")
            try:
                fields, records = scrape_view_data(
                    _dd_week_url(dd_view.url, we), verbose=True, page=page)
                dd_path = DOWNLOAD_DIR / "dd_view_data.csv"
                dd_path.parent.mkdir(parents=True, exist_ok=True)
                dd_path.write_text(
                    "\n".join(["\t".join(fields)]
                              + ["\t".join(r) for r in records]),
                    encoding="utf-8")
                print(f"  → dd: scraped {len(records)} View Data row(s)",
                      flush=True)
                ok.append("dd")
            except Exception as e:
                print(f"  ✗ dd: {type(e).__name__}: {str(e)[:160]}", flush=True)
                fails.append("dd")
            # Personal Production — Crosstab of the 'Sales.Quality Metrics'
            # rep worksheet (full wide table; flyout opens on the base view).
            pp_view = next(v for v in VIEWS if v.key == "personal_production")
            try:
                pp_path = DOWNLOAD_DIR / "personal_production_crosstab.csv"
                download_view_crosstab(pp_view, pp_path, week=we, page=page)
                print(f"  → personal_production: crosstab saved "
                      f"{pp_path.name}", flush=True)
                ok.append("personal_production")
            except Exception as e:
                print(f"  ✗ personal_production: {type(e).__name__}: "
                      f"{str(e)[:160]}", flush=True)
                fails.append("personal_production")
        print(f"\nDownloaded {len(ok)}/{len(VIEWS)}: {ok}"
              + (f"  | FAILED: {fails}" if fails else ""), flush=True)
        return 1 if fails else 0

    if args.test_view:
        view = next(v for v in VIEWS if v.key == args.test_view)
        # Pin the download to the SAME completed week the apply step targets
        # (_current_we_sunday), so churn isn't empty and sales don't bleed in
        # from the prior week. On a Monday this is the just-ended Sunday.
        we = _current_we_sunday()
        if view.key == "personal_production":
            # Crosstab of the 'Sales.Quality Metrics' rep worksheet — the
            # flyout opens on the base view and gives the full wide table
            # (every product column). The old View-Data scrape was scoped to
            # the one measure selected in the saved view (all 'AIR/AWB Sales'),
            # so it couldn't yield NI/VOIP/NL/AIR together (2026-07-01).
            out = DOWNLOAD_DIR / "personal_production_crosstab.csv"
            print(f"Test-CROSSTAB PP (sheet {view.sheet_thumbnail_match!r}, "
                  f"week ending {we})…")
            download_view_crosstab(view, out, week=we)
            # Tableau crosstabs are UTF-16 / tab-delimited (see _parse_view_csv).
            import csv as _csv
            with open(out, encoding="utf-16") as fh:
                rows = list(_csv.reader(fh, delimiter="\t"))
            print(f"\nDone. CSV: {out}  ({len(rows)-1} data rows, "
                  f"{len(rows[0]) if rows else 0} cols)")
            print("COLUMNS:", rows[0] if rows else [])
            for r in rows[1:6]:
                print("  ", r)
            return 0
        out = DOWNLOAD_DIR / f"{view.key}.csv"
        print(f"Test-downloading view '{view.key}' (week ending {we})…")
        download_view_crosstab(view, out, week=we)
        print(f"\nDone. CSV: {out}")
        # Parse + show Adrian Sarabia's resolved values for this view as
        # a canary. If columns don't match, this is where we find out.
        headers, by_owner, grand_total = _parse_view_csv(
            out,
            key_column=view.key_column,
            key_clean=view.key_clean,
            subrow_column=view.subrow_column,
            subrow_value=view.subrow_value,
            keep_all_rows=view.aggregator is not None,
        )
        print(f"  Headers: {headers}")
        print(f"  Rows: {len(by_owner)} ICDs + "
              f"{'grand total ✓' if grand_total else 'no grand total'}")
        canary = "adrian sarabia"
        if view.key == "personal_production":
            # Personal Production is a per-REP view (REPEXPANDED), so the
            # owner-grouped `by_owner` is legitimately empty — the apply path
            # parses by REP instead. Run the canary against the rep rows so
            # the diagnostic reflects what we actually fill (and never prints
            # a scary 'Canary not found / 0 ICDs / []' on a healthy view).
            import csv as _csv
            rep_idx = next((i for i, h in enumerate(headers)
                            if h.strip().lower() == "rep"), 1)
            with open(out, encoding="utf-16") as f:
                rrows = list(_csv.reader(f, delimiter="\t"))
            reps = {(r[rep_idx] or "").strip().lower()
                    for r in rrows[1:] if len(r) > rep_idx and r[rep_idx].strip()}
            print(f"  Per-rep view: {len(reps)} rep row(s)")
            if canary in reps:
                print(f"  Canary '{canary}' present as a rep ✓")
            else:
                print(f"  note: canary '{canary}' not among reps (may not have "
                      f"sold this week) — first 5 reps: {sorted(reps)[:5]}")
        elif canary in by_owner:
            values = values_for_icd(canary, by_owner, grand_total, view)
            print(f"\nAdrian Sarabia raw values from this view:")
            for row, val in sorted(values.items()):
                print(f"  row {row}: {val!r}")
            full = apply_computed(values)
            new = {r: v for r, v in full.items() if r not in values}
            if new:
                print(f"\nComputed (this view's data plus COMPUTED_ROWS):")
                for row, val in sorted(new.items()):
                    print(f"  row {row}: {val!r}")
        else:
            print(f"\n⚠ Canary '{canary}' not found in by_owner keys; "
                  f"first 5 keys: {list(by_owner)[:5]}")
        return 0

    if args.cleanup_drift:
        # Cleanup pass — for each drifted tab, find canonical rows where
        # we previously wrote (wrong row) and the actual row also has the
        # same value (correct row, just-written). Clear the wrong-row
        # cell. Safe + idempotent: if the canonical value doesn't match
        # the actual-row value, it's left alone (manual entry).
        from automations.focus_office_att.daily import _q
        sh = fill.open_sheet()
        icd_tabs = _carlos_icd_tabs()
        we = _current_we_sunday()
        print(f"Cleanup-drift pass on {len(icd_tabs)} ICD tab(s); "
              f"target WE {we.isoformat()}; dry_run={args.dry_run}")

        # Batch-read row 1 + col B once per tab.
        ranges = []
        for t in icd_tabs:
            ranges.append(f"{_q(t)}!1:1")
            ranges.append(f"{_q(t)}!B:B")
        resp = sh.values_batch_get(ranges)
        target_col_by_tab: dict[str, int] = {}
        row_remap_by_tab: dict[str, dict] = {}
        vrs = resp.get("valueRanges", [])
        for idx, t in enumerate(icd_tabs):
            row1 = vrs[idx * 2].get("values", [])
            col_b = [r[0] if r else "" for r in vrs[idx * 2 + 1].get("values", [])]
            if row1:
                mapping = fill.find_sunday_columns([row1[0]], header_row_idx=0)
                col = mapping.get(we)
                if col:
                    target_col_by_tab[t] = col
            remap: dict[int, int] = {}
            for canonical_row, label in ROW_TO_LABEL.items():
                actual = metric_row_for_tab(col_b, label)
                if actual:
                    remap[canonical_row] = actual
            row_remap_by_tab[t] = remap

        # For each tab where any canonical_row != actual_row, batch-read
        # BOTH cells (canonical + actual) at current-week col and compare.
        import gspread.utils as _gu
        total_cleared = 0
        for tab in icd_tabs:
            target_col = target_col_by_tab.get(tab)
            remap = row_remap_by_tab.get(tab) or {}
            if not target_col:
                continue
            drifted = [(c, a) for c, a in remap.items() if c != a]
            if not drifted:
                continue
            col_a1 = _gu.rowcol_to_a1(1, target_col).rstrip("1")
            # Batch-fetch all (canonical, actual) pairs for this tab
            cell_ranges = []
            for c, a in drifted:
                cell_ranges.append(f"{_q(tab)}!{col_a1}{c}")
                cell_ranges.append(f"{_q(tab)}!{col_a1}{a}")
            r = sh.values_batch_get(cell_ranges,
                                    params={"valueRenderOption": "UNFORMATTED_VALUE"})
            vals = r.get("valueRanges", [])
            stale = []  # canonical rows on this tab whose value matches actual
            for i, (c, a) in enumerate(drifted):
                v_canon = vals[i * 2].get("values", [[None]])
                v_actual = vals[i * 2 + 1].get("values", [[None]])
                v_canon = v_canon[0][0] if v_canon and v_canon[0] else None
                v_actual = v_actual[0][0] if v_actual and v_actual[0] else None
                if v_canon in (None, "") or v_actual in (None, ""):
                    continue
                # Compare loosely — values close enough? (handles float
                # precision). Strings exact.
                same = False
                try:
                    if abs(float(v_canon) - float(v_actual)) < 1e-9:
                        same = True
                except (TypeError, ValueError):
                    same = (str(v_canon) == str(v_actual))
                if same:
                    stale.append(c)
            if not stale:
                continue
            if args.dry_run:
                print(f"  [DRY-RUN] {tab}: would clear stale {col_a1}"
                      f"{{{','.join(str(r) for r in stale)}}}")
            else:
                # Batch-clear those cells
                clear_body = [{"range": f"{col_a1}{r}", "values": [[""]]}
                              for r in stale]
                try:
                    ws = sh.worksheet(tab)
                except Exception as e:
                    print(f"  ⚠ couldn't open {tab!r}: {e}")
                    continue
                ws.batch_update(clear_body, value_input_option="USER_ENTERED")
                print(f"  [OK] {tab}: cleared {len(stale)} stale cell(s) "
                      f"({col_a1}{stale})")
            total_cleared += len(stale)
        print(f"\nSummary: cleared {total_cleared} stale cell(s)"
              f"{' (dry-run)' if args.dry_run else ''}")
        return 0

    if args.apply_view == "personal_production":
        # Special path — the view is per-rep (REPEXPANDED custom view),
        # so per-ICD we look up rows where REP == ICD's name (with
        # as_owner fallback) and sum the 4 product columns. Renders as
        # '3 NI / 2 NL' (or '-' if nothing).
        import csv as _csv
        pp_view = next(v for v in VIEWS if v.key == "personal_production")
        # Crosstab of the 'Sales.Quality Metrics' rep worksheet (UTF-16). The
        # flyout DOES open on the base view (2026-07-01) and gives the full
        # wide table — every product column at once. The View-Data scrape was
        # abandoned: its Summary is scoped to the one measure selected in the
        # saved view (came back all 'AIR/AWB Sales'), so it can't yield NI/VOIP/
        # NL/AIR together.
        csv_path = DOWNLOAD_DIR / "personal_production_crosstab.csv"
        if not csv_path.exists():
            print(f"No cached CSV at {csv_path}. Run --test-view personal_production first.")
            return 1
        # STALENESS GATE — the PP CSV has NO date column, so a failed scrape
        # leaves an OLD cache that we'd otherwise fill silently, making PP
        # identical every week (Megan 2026-06-08: "same every week → incorrect";
        # cache was stuck at May 20). The scrape runs in the SAME run as the
        # apply, so a cache not refreshed TODAY means this week's scrape failed.
        # Refuse to write stale numbers — skip + flag, leave the cell as-is
        # (blank/last good) rather than presenting wrong data as complete.
        import datetime as _dt
        cache_day = _dt.date.fromtimestamp(csv_path.stat().st_mtime)
        if not args.dry_run and cache_day < _dt.date.today():
            print(f"❌ Personal Production cache is STALE (scraped "
                  f"{cache_day.isoformat()}, not today) — the PP View-Data "
                  f"scrape failed this run. SKIPPING the PP fill so stale "
                  f"numbers aren't written. Fix the scrape, then re-run "
                  f"`--download-all` + `--apply-view personal_production`.")
            return 1
        with open(csv_path, encoding="utf-16") as f:
            rows = list(_csv.reader(f, delimiter="\t"))
        headers = [h.strip() for h in rows[0]]
        # The 'Rep' header has a trailing space in the CSV ('Rep ').
        rep_idx = next((i for i, h in enumerate(headers)
                        if h.strip().lower() == "rep"), 1)

        # Build {rep-name lowered: product values} from per-rep rows.
        by_rep: dict[str, dict] = {}
        for r in rows[1:]:
            if len(r) <= rep_idx:
                continue
            rep = (r[rep_idx] or "").strip()
            if not rep or rep.lower() == "total":
                continue
            rec = {h: (r[i].strip() if i < len(r) and r[i] else "")
                   for i, h in enumerate(headers)}
            by_rep[rep.lower()] = rec
        print(f"  → parsed {len(by_rep)} per-rep rows from {csv_path.name}")

        sh = fill.open_sheet()
        icd_tabs = _carlos_icd_tabs()
        as_owner_map = _as_owner_by_tab()
        we = _current_we_sunday()
        print(f"Applying view 'personal_production' to {len(icd_tabs)} ICD tab(s); "
              f"target WE {we.isoformat()}; dry_run={args.dry_run}")

        # Batch-read row 1 + col B for date column + row-drift remap.
        from automations.focus_office_att.daily import _q
        ranges = []
        for t in icd_tabs:
            ranges.append(f"{_q(t)}!1:1")
            ranges.append(f"{_q(t)}!B:B")
        resp = sh.values_batch_get(ranges)
        target_col_by_tab: dict[str, int] = {}
        row_remap_by_tab: dict[str, dict] = {}
        vrs = resp.get("valueRanges", [])
        for idx, t in enumerate(icd_tabs):
            row1 = vrs[idx * 2].get("values", [])
            col_b = [r[0] if r else "" for r in vrs[idx * 2 + 1].get("values", [])]
            if row1:
                mapping = fill.find_sunday_columns([row1[0]], header_row_idx=0)
                col = mapping.get(we)
                if col:
                    target_col_by_tab[t] = col
            remap: dict[int, int] = {}
            for canonical_row, label in ROW_TO_LABEL.items():
                actual = metric_row_for_tab(col_b, label)
                if actual:
                    remap[canonical_row] = actual
            # Personal Production row 42 isn't in ROW_TO_LABEL (it's
            # captainship-specific). Look up its label directly.
            pp_row = metric_row_for_tab(col_b, "Personal Production")
            if pp_row:
                remap[42] = pp_row
            row_remap_by_tab[t] = remap

        wrote = skipped = errored = 0
        for tab in icd_tabs:
            target_col = target_col_by_tab.get(tab)
            remap = row_remap_by_tab.get(tab) or {}
            pp_actual_row = remap.get(42)
            if not target_col or not pp_actual_row:
                print(f"  ⚠ {tab}: no col for WE {we.isoformat()} or no PP row")
                skipped += 1
                continue
            try:
                ws = sh.worksheet(tab)
            except Exception as e:
                print(f"  ⚠ couldn't open {tab!r}: {e}")
                errored += 1
                continue
            # Try tab name + as_owner fallback as the rep name. Plus a
            # FIRST+LAST fallback to catch middle-name variants (Atef
            # Choudhury → 'Atef Ahmed Choudhury' in this view).
            fb = as_owner_map.get(tab, "")
            candidates = [tab, fb] if fb and fb.lower() != tab.lower() else [tab]
            rec = None
            for cand in candidates:
                if cand.lower() in by_rep:
                    rec = by_rep[cand.lower()]
                    break
            if rec is None:
                # First-and-last fallback: 'Atef Choudhury' matches any rep
                # that starts with 'atef ' AND ends with ' choudhury'.
                for cand in candidates:
                    parts = cand.strip().split()
                    if len(parts) < 2:
                        continue
                    first, last = parts[0].lower(), parts[-1].lower()
                    for rep_key, rep_rec in by_rep.items():
                        rep_parts = rep_key.split()
                        if (len(rep_parts) >= 2
                                and rep_parts[0] == first
                                and rep_parts[-1] == last):
                            rec = rep_rec
                            break
                    if rec:
                        break
            value = _format_carlos_pp(rec or {})
            # Use write_icd_values without row_remap (we already resolved)
            for line in write_icd_values(ws, {pp_actual_row: value},
                                         target_col, dry_run=args.dry_run):
                print(line)
            wrote += 1
        print(f"\nSummary: {wrote} written/previewed, "
              f"{skipped} skipped, {errored} errored")
        return 0

    if args.apply_view == "dd":
        # Special path — Program Summary uses View Data scrape (not
        # crosstab) and a DIFFERENT view URL than Raf's pipeline: with
        # the "downline or captain" filter set to "downline" so Carlos's
        # ICDs appear alongside Raf's (Raf's CAPTAINVIEW filters out
        # everyone but the logged-in user's downline).
        from automations.recruiting_report.opt_phase import (
            scrape_view_data, parse_program_summary, _norm,
        )
        dd_view = next(v for v in VIEWS if v.key == "dd")
        # Use a distinct filename so the old UTF-16 crosstab attempts at
        # dd.csv don't get mis-parsed as UTF-8 View Data.
        carlos_dd_path = DOWNLOAD_DIR / "dd_view_data.csv"
        sh = fill.open_sheet()
        icd_tabs = _carlos_icd_tabs()
        as_owner_map = _as_owner_by_tab()
        we = week_override or _current_we_sunday()
        print(f"Applying view 'dd' to {len(icd_tabs)} ICD tab(s); "
              f"target WE {we.isoformat()}; dry_run={args.dry_run}")

        # Refresh the View Data CSV from Carlos's URL (downline filter) —
        # unless --no-download says a prior --download-all already cached it
        # (so the apply needs no ownerville login of its own). The scrape is
        # week-pinned via 'Processed Week' so it targets THIS week, not the
        # frozen one — and --week backfills a prior column.
        if args.no_download and carlos_dd_path.exists():
            print(f"  → using cached dd View Data ({carlos_dd_path.name})")
        elif not args.dry_run or not carlos_dd_path.exists():
            dd_url = _dd_week_url(dd_view.url, we)
            print(f"  → scraping View Data from {dd_url}")
            fields, records = scrape_view_data(dd_url, verbose=True)
            carlos_dd_path.parent.mkdir(parents=True, exist_ok=True)
            lines = ["\t".join(fields)] + ["\t".join(r) for r in records]
            carlos_dd_path.write_text("\n".join(lines), encoding="utf-8")
            print(f"  → saved {len(records)} View Data row(s) to {carlos_dd_path.name}")
        by_owner = parse_program_summary(carlos_dd_path)
        print(f"  → parsed {len(by_owner)} ICDs from Program Summary")

        # Batch-read row 1 + col B for date column AND row-drift remap.
        from automations.focus_office_att.daily import _q
        ranges = []
        for t in icd_tabs:
            ranges.append(f"{_q(t)}!1:1")
            ranges.append(f"{_q(t)}!B:B")
        resp = sh.values_batch_get(ranges)
        target_col_by_tab: dict[str, int] = {}
        row_remap_by_tab: dict[str, dict] = {}
        vrs = resp.get("valueRanges", [])
        for idx, t in enumerate(icd_tabs):
            row1 = vrs[idx * 2].get("values", [])
            col_b = [r[0] if r else "" for r in vrs[idx * 2 + 1].get("values", [])]
            if row1:
                mapping = fill.find_sunday_columns([row1[0]], header_row_idx=0)
                col = mapping.get(we)
                if col:
                    target_col_by_tab[t] = col
            remap: dict[int, int] = {}
            for canonical_row, label in ROW_TO_LABEL.items():
                actual = metric_row_for_tab(col_b, label)
                if actual:
                    remap[canonical_row] = actual
            row_remap_by_tab[t] = remap

        wrote = skipped = errored = 0
        for tab in icd_tabs:
            target_col = target_col_by_tab.get(tab)
            if not target_col:
                print(f"  ⚠ {tab}: no col for WE {we.isoformat()}")
                skipped += 1
                continue
            try:
                ws = sh.worksheet(tab)
            except Exception as e:
                print(f"  ⚠ couldn't open {tab!r}: {e}")
                errored += 1
                continue
            fb = as_owner_map.get(tab, "")
            candidates = [tab, fb] if fb and fb.lower() != tab.lower() else [tab]
            record = None
            for cand in candidates:
                key = _norm(cand)
                if key in by_owner:
                    record = by_owner[key]
                    break
            # Carlos's Tableau session can only see ~3 of his 32 ICDs in this
            # view (permission-scoped to his direct downline). Per Megan: the
            # ones we CAN'T see should get "No Access" stamped in row 51 so
            # the viewer knows the data exists but is gated by Tableau access,
            # vs being mistaken for $0 or a stale cell.
            total: object
            if record:
                total = record.get("total")
                if total is None:
                    print(f"  ⚠ {tab}: matched {record.get('owner')!r} but no total")
                    skipped += 1
                    continue
            else:
                total = "No Access"
            for line in write_icd_values(ws, {51: total}, target_col,
                                         dry_run=args.dry_run,
                                         row_remap=row_remap_by_tab.get(tab)):
                print(line)
            wrote += 1
        print(f"\nSummary: {wrote} written/previewed, "
              f"{skipped} skipped, {errored} errored")
        return 0

    if args.apply_view:
        view = next(v for v in VIEWS if v.key == args.apply_view)
        csv_path = DOWNLOAD_DIR / f"{view.key}.csv"
        if not csv_path.exists():
            print(f"No cached CSV at {csv_path}. Run --test-view {view.key} first.")
            return 1
        sh = fill.open_sheet()
        icd_tabs = _carlos_icd_tabs()
        as_owner_map = _as_owner_by_tab()
        we = _current_we_sunday()
        print(f"Applying view '{view.key}' to {len(icd_tabs)} ICD tab(s); "
              f"target WE {we.isoformat()}; dry_run={args.dry_run}")

        # Batch-read row 1 AND column B of every tab in ONE API call (vs
        # 64 separate reads which blow past the 60/min Sheets quota).
        # Row 1 gives us the date column; column B gives us the metric
        # label per row, used to translate canonical rows → actual rows
        # (many tabs have rows shifted ±1 from the master layout).
        from automations.focus_office_att.daily import _q
        ranges = []
        for t in icd_tabs:
            ranges.append(f"{_q(t)}!1:1")        # row 1 = dates
            ranges.append(f"{_q(t)}!B:B")        # col B = metric labels
        resp = sh.values_batch_get(ranges)
        target_col_by_tab: dict[str, int] = {}
        row_remap_by_tab: dict[str, dict] = {}
        vrs = resp.get("valueRanges", [])
        for idx, t in enumerate(icd_tabs):
            row1 = vrs[idx * 2].get("values", [])
            col_b = [r[0] if r else "" for r in vrs[idx * 2 + 1].get("values", [])]
            if row1:
                mapping = fill.find_sunday_columns([row1[0]], header_row_idx=0)
                col = mapping.get(we)
                if col:
                    target_col_by_tab[t] = col
            # Build canonical → actual row map by matching each metric's
            # label in column B. Missing labels are silently absent from
            # the map (writer skips them with a warning).
            remap: dict[int, int] = {}
            for canonical_row, label in ROW_TO_LABEL.items():
                actual = metric_row_for_tab(col_b, label)
                if actual:
                    remap[canonical_row] = actual
            row_remap_by_tab[t] = remap

        # Parse CSV ONCE (same data drives all per-ICD writes).
        try:
            headers, by_owner, grand_total = _parse_view_csv(
                csv_path,
                key_column=view.key_column,
                key_clean=view.key_clean,
                subrow_column=view.subrow_column,
                subrow_value=view.subrow_value,
                keep_all_rows=view.aggregator is not None,
            )
        except Exception as e:
            print(f"⚠ couldn't parse {csv_path.name}: {e}")
            return 1

        wrote = skipped = errored = 0
        for tab in icd_tabs:
            target_col = target_col_by_tab.get(tab)
            if not target_col:
                print(f"  ⚠ {tab}: no col for WE {we.isoformat()}")
                skipped += 1
                continue
            try:
                ws = sh.worksheet(tab)
            except Exception as e:
                print(f"  ⚠ couldn't open {tab!r}: {e}")
                errored += 1
                continue
            fb = as_owner_map.get(tab, "")
            fbs = [fb] if fb and fb.lower() != tab.lower() else []
            raw = values_for_icd(tab, by_owner, grand_total, view,
                                 fallback_names=fbs)
            if not raw:
                print(f"  ⚠ {tab}: no values from {view.key} "
                      f"(tried {[tab] + fbs})")
                skipped += 1
                continue
            full = apply_computed(raw)
            for line in write_icd_values(ws, full, target_col,
                                         dry_run=args.dry_run,
                                         row_remap=row_remap_by_tab.get(tab)):
                print(line)
            wrote += 1

        # Stamp the percent number format on this view's metric cells so they
        # render consistently (whole '0%' or churn's '0.00%') no matter the
        # cell's prior format. ONE batched call (avoids per-tab 429).
        if view.percent_format and not args.dry_run:
            fmt = {"numberFormat": {"type": "PERCENT",
                                    "pattern": view.percent_format}}
            sheet_ids = {w.title: w.id for w in sh.worksheets()}
            reqs = []
            for tab in icd_tabs:
                col = target_col_by_tab.get(tab)
                sid = sheet_ids.get(tab)
                remap = row_remap_by_tab.get(tab) or {}
                if not col or sid is None:
                    continue
                for m in view.metrics:
                    r = remap.get(m.sheet_row, m.sheet_row)
                    reqs.append({"repeatCell": {
                        "range": {"sheetId": sid, "startRowIndex": r - 1,
                                  "endRowIndex": r, "startColumnIndex": col - 1,
                                  "endColumnIndex": col},
                        "cell": {"userEnteredFormat": fmt},
                        "fields": "userEnteredFormat.numberFormat"}})
            if reqs:
                sh.batch_update({"requests": reqs})
                print(f"  → stamped {view.percent_format!r} on {len(reqs)} "
                      f"percent cell(s)")

        print(f"\nSummary: {wrote} written/previewed, "
              f"{skipped} skipped (no data), {errored} errored")
        return 0

    if args.preview_icd:
        view = next(v for v in VIEWS if v.key == "d2d1")
        csv_path = DOWNLOAD_DIR / f"{view.key}.csv"
        if not csv_path.exists():
            print(f"No cached CSV at {csv_path}. Run --test-view d2d1 first.")
            return 1
        sh = fill.open_sheet()
        try:
            ws = sh.worksheet(args.preview_icd)
        except Exception as e:
            print(f"Couldn't open tab {args.preview_icd!r}: {e}")
            return 1
        # Find col for current WE Sunday
        we = _current_we_sunday()
        sunday_to_col = fill.find_sunday_columns(ws.get_all_values(),
                                                 header_row_idx=0)
        target_col = sunday_to_col.get(we)
        if not target_col:
            print(f"Couldn't find WE {we.isoformat()} column in {ws.title!r}; "
                  f"available: {sorted(sunday_to_col)[:5]}…")
            return 1
        print(f"Target: {ws.title}, WE {we.isoformat()} → col {target_col}, "
              f"dry_run={args.dry_run}")
        log = apply_view_to_icd(view, csv_path, ws, target_col,
                                dry_run=args.dry_run)
        for line in log:
            print(line)
        return 0

    print("Full-run mode is not implemented yet — wire view parsers first.")
    print("Test each view individually with --test-view <key>:")
    for v in VIEWS:
        print(f"  --test-view {v.key:<12}  →  {len(v.metrics)} metric(s) "
              f"({', '.join(m.tableau_column for m in v.metrics)[:60]})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as _e:   # TEMP DIAGNOSTIC — capture the real traceback
        import traceback as _tb
        _dbg = Path("output/logs/carlos-main-debug.log")
        _dbg.parent.mkdir(parents=True, exist_ok=True)
        with _dbg.open("a") as _f:
            _f.write(f"\n=== main() raised: {type(_e).__name__}: "
                     f"{str(_e)[:300]}\n")
            _f.write(_tb.format_exc())
        raise
