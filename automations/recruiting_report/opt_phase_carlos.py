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
    # When a view has MANY rows per owner (penetration is ZIP-level, ~37 rows
    # per ICD), `aggregator` collapses them into one {sheet_row: value} dict.
    # If set, the parser keeps ALL rows per owner instead of last-write-wins,
    # and `aggregator(rows)` computes the metric value(s). When None,
    # values_for_icd reads the configured columns from the single stored row.
    aggregator: Optional[Callable[[list], dict]] = None


# All 6 Carlos OPT-phase Tableau views, per
# resources/opt-section/carlos-tableau-source-map.md.
VIEWS: List[ViewConfig] = [
    ViewConfig(
        key="d2d1",
        url="https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/D2D1-PAGERV3",
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
        sheet_thumbnail_match="Cancel Rates Sheet",
        # Owner & Office cell looks like 'AARON CORSO\n [cor consulting agency, inc.]';
        # 3 rows per ICD (Cancel Rates / Canceled Orders / Unit Count) — pick the
        # 'Cancel Rates' one. Header for the subrow col is empty string in the CSV.
        key_column="Owner & Office",
        key_clean=_strip_office_suffix,
        subrow_column="",
        subrow_value="Cancel Rates",
        metrics=[
            ViewMetric(sheet_row=43, tableau_column="6 Week Average"),
        ],
    ),
    ViewConfig(
        key="activation",
        url="https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/ACTIVATIONRATES",
        sheet_thumbnail_match="Activation Office",
        # Owner & Office; multi-row per ICD ('Activation %' / 'Total Activations' /
        # 'Total Volume'); we want 'Activation %'.
        key_column="Owner & Office",
        key_clean=_strip_office_suffix,
        subrow_column="",
        subrow_value="Activation %",
        metrics=[
            ViewMetric(sheet_row=44, tableau_column="31-60 Days"),
        ],
    ),
    ViewConfig(
        key="churn",
        url="https://us-east-1.online.tableau.com/#/site/sci/views/ATTTRACKER-B2B/CHURNRATES",
        sheet_thumbnail_match="ICD Churn",
        # Owner & Office; multi-row per ICD ('Activated SPE/SP' / 'Calculation1 (1)'
        # / 'Churn Rate'); we want 'Churn Rate'. Columns DON'T have the 'Churn'
        # suffix in the CSV — just '0-30 Day', '30 Day', etc.
        key_column="Owner & Office",
        key_clean=_strip_office_suffix,
        subrow_column="",
        subrow_value="Churn Rate",
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
        key="dd",
        url="https://us-east-1.online.tableau.com/#/site/sci/views/DirectDepositICDVIEWVersion2_0/PROGRAMSUMMARY",
        # Sheet picker iteration log:
        # - "" (no match → first/Consultant ORG Title) → 64-byte empty file
        # - "Sheet 7 (3)" → Download button stayed disabled
        # Trying "Self Office Display" — "Self" sounds like the current
        # user's filtered view, which might contain the ICD breakdown.
        sheet_thumbnail_match="Self Office Display",
        metrics=[
            ViewMetric(sheet_row=51, tableau_column="Grand Total to ICD"),
        ],
        notes="Different workbook from the other 5. Sheet name TBD — may need "
              "iterating through 'Sheet 7 (2)', '(3)', 'Self Office Display'.",
    ),
]


# Rows we MUST NOT touch — manual entry or formula-bearing cells.
DO_NOT_TOUCH_ROWS = {27, 28, 30, 31, 32}

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
                continue
            raw = src.get(m.tableau_column)
            if raw is None or raw == "":
                continue
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
    """Return the WE Sunday for the in-progress week (today's week ending
    Sunday). For today=Wed 5/20 returns 5/24."""
    today = today or dt.date.today()
    days_to_sunday = (6 - today.weekday()) % 7
    return today + dt.timedelta(days=days_to_sunday)


def write_icd_values(ws, icd_values: dict[int, object],
                     target_col: int, dry_run: bool = False) -> list[str]:
    """Write `icd_values` ({sheet_row: value}) to one ICD tab's
    `target_col` column. Rows in DO_NOT_TOUCH_ROWS are skipped silently
    so the writer can be called with a dict that includes them.

    Values are written as a batch (single API call per tab) to keep the
    quota footprint small even when rolling out to 32 tabs.

    Returns a list of human-readable log lines."""
    import gspread.utils as _gu
    log = []
    to_write = {r: v for r, v in icd_values.items() if r not in DO_NOT_TOUCH_ROWS}
    if not to_write:
        log.append(f"  {ws.title}: nothing to write (all rows in DO_NOT_TOUCH)")
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
        ws.batch_update(body, value_input_option="USER_ENTERED")
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
                           verbose: bool = True) -> Path:
    """Open `view.url` in the debug-Chrome Tableau tab, click Download →
    Crosstab → pick the right sheet thumbnail → save CSV at `out_path`.

    Reuses the pattern from focus_office_att/step7_download_tableau.py:
    Tableau viz lives in an iframe `[title="Data Visualization"]`; toolbar
    buttons + the crosstab modal use `data-tb-test-id` attributes."""
    from playwright.sync_api import sync_playwright

    VIZ_RENDER_WAIT_MS = 10_000

    out_path.parent.mkdir(parents=True, exist_ok=True)
    debug_dir = out_path.parent / "_debug" / view.key
    debug_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        # Find an existing Tableau tab in the user's Chrome session
        page = None
        for ctx in browser.contexts:
            for pg in ctx.pages:
                if "online.tableau.com" in (pg.url or ""):
                    page = pg
                    break
            if page:
                break
        if not page:
            # Fall back to the first open page — caller may need to
            # bootstrap the Tableau SSO themselves first.
            page = browser.contexts[0].pages[0]

        if verbose:
            print(f"  → navigating Tableau tab to: {view.url}", flush=True)
        page.goto(view.url, wait_until="domcontentloaded")

        viz = page.frame_locator('iframe[title="Data Visualization"]')

        if verbose:
            print("  → waiting for viz Download button…", flush=True)
        viz.locator(
            '[data-tb-test-id="viz-viewer-toolbar-button-download"]'
        ).wait_for(state="visible", timeout=30_000)
        page.wait_for_timeout(VIZ_RENDER_WAIT_MS)

        if verbose:
            print("  → Download → Crosstab → (pick thumbnail) → CSV", flush=True)

        with page.expect_download(timeout=60_000) as dl_info:
            viz.locator(
                '[data-tb-test-id="viz-viewer-toolbar-button-download"]'
            ).click()
            page.wait_for_timeout(1500)
            page.screenshot(path=str(debug_dir / "01_download_menu.png"), full_page=True)

            viz.locator(
                '[data-tb-test-id="download-flyout-download-crosstab-MenuItem"]'
            ).click()
            page.wait_for_timeout(2000)
            page.screenshot(path=str(debug_dir / "02_crosstab_modal.png"), full_page=True)

            # Find any sheet thumbnails. If the view has only one sheet
            # Tableau may auto-select it (no picker shown); if many, we
            # match by `sheet_thumbnail_match` or fall back to first.
            thumbs = viz.locator('[data-tb-test-id^="sheet-thumbnail-"]')
            thumb_count = thumbs.count()
            if verbose:
                print(f"  → modal shows {thumb_count} sheet thumbnail(s)",
                      flush=True)
            # Enumerate names so we know which one to target. Tableau puts
            # the sheet title inside the thumbnail tile as visible text.
            for i in range(thumb_count):
                try:
                    text = thumbs.nth(i).inner_text(timeout=2000).strip()
                    tid = thumbs.nth(i).get_attribute("data-tb-test-id") or "?"
                except Exception as e:
                    text, tid = f"<error: {e}>", "?"
                if verbose:
                    print(f"    thumb #{i}: {tid}  text={text[:80]!r}",
                          flush=True)
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
                    thumb.click()
                    page.wait_for_timeout(800)
                page.screenshot(path=str(debug_dir / "03_after_thumb.png"), full_page=True)

            # CSV radio
            viz.locator(
                '[data-tb-test-id="crosstab-options-dialog-radio-csv-Label"]'
            ).click()
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
    args = ap.parse_args()

    if args.test_view:
        view = next(v for v in VIEWS if v.key == args.test_view)
        out = DOWNLOAD_DIR / f"{view.key}.csv"
        print(f"Test-downloading view '{view.key}'…")
        download_view_crosstab(view, out)
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
        if canary in by_owner:
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

        # Batch-read row 1 of every tab in ONE API call (vs 32 separate
        # reads which blow past the 60/min Sheets quota). Build a
        # per-tab target_col map so the loop below doesn't re-read.
        from automations.focus_office_att.daily import _q
        ranges = [f"{_q(t)}!1:1" for t in icd_tabs]
        resp = sh.values_batch_get(ranges)
        target_col_by_tab: dict[str, int] = {}
        for t, vr in zip(icd_tabs, resp.get("valueRanges", [])):
            vals = vr.get("values", [])
            if not vals:
                continue
            mapping = fill.find_sunday_columns([vals[0]], header_row_idx=0)
            col = mapping.get(we)
            if col:
                target_col_by_tab[t] = col

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
                                         dry_run=args.dry_run):
                print(line)
            wrote += 1
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
    sys.exit(main())
