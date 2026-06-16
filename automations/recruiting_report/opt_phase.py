"""OPT phase — Tableau "ICD Summary" crosstabs → Focus Report OPT section.

Pulls two AUTOMATION PULL crosstabs from Tableau and writes the OPT-section
metrics into each ICD tab. No manual CSV downloads — the run drives Tableau's
own Download → Crosstab.

Sources:
  - ATT view (D2D 1-PAGER V4): headcount, sale types, ranking, % wireless,
    1 GIG%, and the national sales-per-rep average.
  - INT view (D2D 1-PAGER V2, Internet Only): new-internet per-rep average
    (per ICD + national).

What it writes, per ICD tab:
  OPT section ("OPT" anchor in column B):
    - scraped: Active Headcount, New Internets, Upgrades, DTV, New Lines,
      % of Wireless Rep Count, Scorecard Ranking, AVG New INT Per Active
      Headcount
    - computed (by label lookup, never hardcoded rows): Total Apps =
      sum of the four sale types; AVG Apps Per Active Headcount =
      Total Apps / Active Headcount
    - national (same value every tab): National AVG Apps, National New INT AVG
  Office Metrics section ("Office Metrics" anchor): 1 GIG%

Safety: only WRITES the cells above — never clears or deletes anything.

Run:
  .venv/bin/python -m automations.recruiting_report.opt_phase --only "Marcellus Butler" --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import gspread
from patchright.sync_api import sync_playwright

from . import fetch_office, fill
from automations.shared import sheet_flags as _sheet_flags

WORKSPACE = Path(__file__).resolve().parent.parent.parent

# Raf's offices are in Texas — anchor "is it Monday?" to Central Time, not the
# machine clock (which may run in another tz).
CENTRAL = ZoneInfo("America/Chicago")

# ATT crosstab — D2D 1-PAGER V4. The "AUTOMATIONPULL" custom view was deleted
# 2026-06-01 (caught on Eve's run); the BASE dashboard still holds the same
# "ICD Summary - ATT (V2)" worksheet with current data, so we point at the base
# view. (Recreate an AUTOMATIONPULL saved view + restore the GUID URL if a
# non-default filter is ever needed.)
ATT_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/D2D1-PAGERV4"
)
ATT_SHEET = "ICD Summary - ATT (V2)"
# The (LW) "last week" worksheet — the most recent COMPLETED week. Charts were
# added to D2D1-PAGERV4 (2026-06-02) and the week-filter URL now renders only
# the (LW) sheets, hiding the current ATT_SHEET; we pull (LW) off the bare view
# instead (it's also never blank mid-week, unlike the in-progress sheet). See
# the _dl note in run_opt_phase. Megan-confirmed: the report fills last week.
ATT_SHEET_LW = "ICD Summary - ATT (V2) (LW) (2)"
ATT_PATH = WORKSPACE / "output" / "opt_icd_summary_att.csv"

# INT crosstab — D2D 1-PAGER V2 (Internet Only). AUTOMATIONPULL deleted
# 2026-06-01 → base dashboard (same "ICD Summary - ATT (V2) (2)" worksheet).
INT_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/D2D1-PAGERV2InternetOnly"
)
INT_SHEET = "ICD Summary - ATT (V2) (2)"
INT_SHEET_LW = "ICD Summary - ATT (V2) (LW) (3)"  # see ATT_SHEET_LW note
INT_PATH = WORKSPACE / "output" / "opt_icd_summary_int.csv"

# Product Sales crosstab — PRODUCT SALES SUMMARY 4WK. Per-REP per-product
# per-day for each ICD's Personal Production. The "AUTOMATIONPULL" view (deleted
# 2026-06-01) had the Rep dimension EXPANDED; the base dashboard collapses reps
# (ICD-level), which the parser can't use. Point instead at the existing
# 'DailyRepBDreportpull' rep-level view (same workbook + "Sales By ICD (Weekly
# View)" worksheet; already used by the daily-rep-breakdown report) — it yields
# Owner | Rep | Product | Mon-Sun, current week. Verified parses 1112 reps.
PRODUCT_SALES_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/"
    "f081e40f-dd21-4a09-8981-c7cce17b5381/DailyRepBDreportpull"
)
PRODUCT_SALES_SHEET = "Sales By ICD (Weekly View)"
PRODUCT_SALES_PATH = WORKSPACE / "output" / "opt_personal_production.csv"

# Metrics crosstab — the Metrics view (Office-Metrics-section rates).
# AUTOMATIONPULL-METRICS was deleted (caught 2026-06-01, Eve's run — 6+ days /
# cancel rate / 1 GIG% / activation% were blank). Base Metrics dashboard holds
# the same "Metrics Call Last week data (Internet)" worksheet with all fields.
METRICS_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/Metrics"
)
METRICS_SHEET = "Metrics Call Last week data (Internet)"
METRICS_PATH = WORKSPACE / "output" / "opt_metrics.csv"

# Churn crosstab — AUTOMATION-NIChurn custom view of CHURN (New Internet).
# Replaces AUTOMATIONPULL-NICHURNVIEW, which got stuck returning a SINGLE ICD
# (Nicholas Weldon) from a persisted filter — caught 2026-06-08; Eve rebuilt
# this view to return all ICDs (88). No date filter (churn is ongoing).
CHURN_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "2a8afd55-5eac-4217-94d1-17e62cd0feec/AUTOMATION-NIChurn?:iid=1"
)
CHURN_SHEET = "ICD Churn"
CHURN_PATH = WORKSPACE / "output" / "opt_churn.csv"

# Wireless Metrics crosstab — AP-WIRELESSMETRICS custom view of Metrics.
WIRELESS_METRICS_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/Metrics/"
    "23910d52-35aa-4b2d-95f5-8d96649a7b0d/AP-WIRELESSMETRICS"
)
WIRELESS_METRICS_SHEET = "Metrics Call Last week data (Wireless)"
WIRELESS_METRICS_PATH = WORKSPACE / "output" / "opt_wireless_metrics.csv"

# Wireless Churn crosstab — AUTOMATION-WirelessChurn custom view of CHURN.
# Replaces AP-WIRELESSCHURN (also stuck at 1 ICD); Eve rebuilt 2026-06-08 to
# return all ICDs (84). Its worksheet is "ICD Churn (Wireless)" — distinct from
# the NI-churn "ICD Churn" sheet. No date filter (churn is ongoing).
WIRELESS_CHURN_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "67ab7e84-5a66-43c9-a6e5-df2edcaf95e6/AUTOMATION-WirelessChurn?:iid=1"
)
WIRELESS_CHURN_SHEET = "ICD Churn (Wireless)"
WIRELESS_CHURN_PATH = WORKSPACE / "output" / "opt_wireless_churn.csv"

# Captain's Bonus crosstab — the DEFAULT view (no custom-view GUID). The
# AUTOMATIONPULL-CAPTAINS custom view stopped rendering its toolbar (the
# Download button never appears -> 120s timeout, observed 2026-06-15), so we
# pull the bare view: it renders fine AND exposes every captainship. The
# Crosstab dialog splits data into one "CB Appr + Churn (<captain>)" sheet per
# captainship team; those sheets are AUTO-DISCOVERED (discover_captains_sheets)
# so a captainship added/removed in Tableau is picked up without a code change,
# then merged into one ICD lookup.
CAPTAINS_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CaptainsBonus"
)
# FALLBACK ONLY — used when discover_captains_sheets can't reach the Crosstab
# dialog. Kept current (8 teams as of 2026-06-15: Aron's dissolved 2026-06-10;
# Chan/Jess/Sahil/Tony added) so even the fallback fills everyone.
CAPTAINS_SHEETS = ["CB Appr + Churn (Chan)", "CB Appr + Churn (Jess)",
                   "CB Appr + Churn (Pat)", "CB Appr + Churn (Raf)",
                   "CB Appr + Churn (Sahil)", "CB Appr + Churn (Starr)",
                   "CB Appr + Churn (Tony)", "CB Appr + Churn (Wayne)"]


def _captains_path(sheet: str) -> Path:
    """Per-team crosstab CSV path, e.g. .../opt_captains_raf.csv."""
    tag = sheet.split("(")[-1].rstrip(")").strip().lower()
    return WORKSPACE / "output" / f"opt_captains_{tag}.csv"


def discover_captains_sheets(page=None, logfn=print) -> List[str]:
    """Auto-detect the 'CB Appr + Churn (<team>)' sheets the Captain's Bonus
    view currently offers, so a captainship added/removed in Tableau is picked
    up without a code change. (Chan/Jess/Sahil/Tony appeared by 2026-06-15; the
    old hardcoded 4-team list silently dropped their ICDs — Marcellus Butler,
    Tony Chavez, Jennifer Figueroa.) Falls back to CAPTAINS_SHEETS when
    discovery can't reach the dialog or matches nothing."""
    try:
        offered = list_crosstab_sheets(CAPTAINS_VIEW_URL, page=page, verbose=False)
    except Exception as e:
        logfn(f"OPT: ⚠️ Captain's Bonus sheet discovery FAILED "
              f"({type(e).__name__}: {str(e)[:120]}) — using fallback "
              f"{len(CAPTAINS_SHEETS)} sheet(s)")
        return list(CAPTAINS_SHEETS)
    found = sorted(s for s in offered if re.search(r"cb\s*appr.*churn", s, re.I))
    if not found:
        logfn(f"OPT: ⚠️ Captain's Bonus discovery saw {len(offered)} sheet(s) but "
              f"none matched 'CB Appr + Churn' — using fallback "
              f"{len(CAPTAINS_SHEETS)} sheet(s)")
        return list(CAPTAINS_SHEETS)
    logfn(f"OPT: Captain's Bonus auto-discovered {len(found)} team sheet(s): "
          f"{[s.split('(')[-1].rstrip(')') for s in found]}")
    return found


# Program Summary (Direct Deposit) — PROGRAM SUMMARY view, CAPTAINVIEW custom
# view. Its per-ICD table won't crosstab-export, so it's scraped via the
# Download -> Data View Data window. Direct Deposit per ICD = the sum of that
# ICD's "Total $ to ICD" rows.
PROGRAM_SUMMARY_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "DirectDepositICDVIEWVersion2_0/PROGRAMSUMMARY/"
    "639b7ff1-d2ed-49ae-a85d-b96a0787a1e9/CAPTAINVIEW"
)
PROGRAM_SUMMARY_PATH = WORKSPACE / "output" / "opt_program_summary.csv"

# Direct Deposit roster — the set of ICD owners ever seen in the DD view
# (PROGRAM SUMMARY / CAPTAINVIEW). It lets the fill distinguish an owner who is
# KNOWN to the DD view but has no DD this week (-> "No DD") from one who never
# appears in it at all (-> "Not in Tableau"). Megan's rule, 2026-06-04. The
# roster self-maintains: every run adds the week's owners. Lives in the package
# dir (committed) so the classification is shared, not per-machine.
DD_ROSTER_PATH = Path(__file__).resolve().parent / "dd_roster.json"
DD_NO_DD = "No DD"            # in the DD view's roster, but no DD this week
DD_NOT_IN_TABLEAU = "Not in Tableau"  # never seen in the DD view


def load_dd_roster() -> Dict[str, dict]:
    """Read dd_roster.json -> {normalized owner: {"owner": display}} so it
    plugs straight into _match_owner. Missing/corrupt file -> {}."""
    try:
        names = json.loads(DD_ROSTER_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {_norm(n): {"owner": n} for n in names if str(n).strip()}


def update_dd_roster(roster: Dict[str, dict], program_summary: Dict[str, dict]
                     ) -> Dict[str, dict]:
    """Fold this run's DD-view owners into the roster and persist it. Append-
    only — an owner is never dropped, so a one-week absence doesn't demote a
    known ICD to 'Not in Tableau'. No-op write when nothing new appeared."""
    merged = dict(roster)
    added = False
    for k, v in (program_summary or {}).items():
        if k not in merged:
            merged[k] = {"owner": v.get("owner", k)}
            added = True
    if added:
        try:
            names = sorted(v["owner"] for v in merged.values())
            DD_ROSTER_PATH.write_text(json.dumps(names, indent=2) + "\n",
                                      encoding="utf-8")
        except Exception:
            pass   # persistence is best-effort; classification still works
    return merged


def _dd_value(tab_name: str, program_summary: Dict[str, dict],
              dd_roster: Optional[Dict[str, dict]], aliases_map: dict):
    """The Direct Deposit cell value for a tab, or None to leave the cell as-is.

      - owner has a DD row this week        -> the dollar amount
      - owner in the DD roster, none this wk -> "No DD"
      - owner never in the DD view          -> "Not in Tableau"
      - no DD data loaded this run / roster  -> None (don't touch the cell)

    Only ever drives the CURRENT week's column, so prior weeks' (possibly hand-
    entered) DD is never disturbed."""
    ps_row = _match_owner(tab_name, program_summary, aliases_map)
    if ps_row:
        return round(ps_row["total"], 2)
    # No DD this week. Only label if we actually pulled DD data this run AND we
    # have a roster to classify against — otherwise leave the cell untouched
    # (a failed/empty DD pull must never blanket-label every tab).
    if not program_summary or dd_roster is None:
        return None
    known = _match_owner(tab_name, dd_roster, aliases_map)
    return DD_NO_DD if known else DD_NOT_IN_TABLEAU

# Fiber Lead Performance — per-ICD pull. The report filters the view to ONE ICD
# at a time (Owner Name filter) and scrapes that ICD's "Program Overview" box —
# a clean 4-row Measure Names/Values worksheet (activate_xy below). The by-zip
# table can't be scraped reliably (Measure-Names pivot garbles the grid), but
# Program Overview has every number we need as a single per-owner total:
#   Lead Count                       -> Total Leads
#   Total Sales                      -> Penetration Rate = Total Sales / Lead Count
#   Assigned Fiber Lead Penetration  -> goal (e.g. 0.02); Expected Fiber Sales
#                                       (120 days, 17wks) = round(Lead Count * goal)
#   Expected Fiber Sales Weekly      = round(Expected / 17)
# The Program Overview box sits near the top-center of the dashboard.
FIBER_OVERVIEW_XY = (0.45, 0.45)
FIBER_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/FiberLeadPerformance"
)
# Bulk-pull custom view: AUTOMATIONPULL-NICHURNVIEW exposes the same
# Penetration By Zip data BUT its Crosstab export is a clean wide CSV
# with per-owner "Fixed" aggregates already computed by Tableau —
# Office Lead Penetration (Fixed) / ICD Workable Fiber Lead Count (copy)
# / Fiber Sales (Fixed) (copy). One ~10s Crosstab download replaces the
# 25-min per-ICD loop. Megan/data-team added this view 2026-05-22;
# verified working against Hasani Lynch (2.6%/80,404/2,062 — matches
# the per-ICD scrape's prior values within day-to-day drift).
FIBER_BULK_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/FiberLeadPerformance/"
    "a79fd021-3606-4aa2-bf55-bc3856cdac99/AUTOMATIONPULL-NICHURNVIEW"
)
FIBER_BULK_CROSSTAB_SHEET = "Office New Fiber Lead Penetration By Zip"
FIBER_PATH = WORKSPACE / "output" / "opt_fiber.csv"
# Sentinel value written when an ICD has no row in Tableau's Fiber data
# (e.g. Khalil Mansour 2026-05-26 — neither the AUTOMATIONPULL-NICHURNVIEW
# crosstab nor the bare workbook's owner-filtered scrape returned any
# rows for him). Megan asked for a clearly visible "missing from source"
# signal to distinguish this from a real-zero case (e.g. Rashad Reed,
# who genuinely has 0.0% activity but IS in the data). The fill code
# detects this string and writes it across all four Fiber cells.
FIBER_NOT_ON_TABLEAU = "Not On Tableau"


# Tableau product type -> short label, in the order they appear in the cell.
PRODUCT_LABELS = [
    ("NEW INTERNET", "NI"),
    ("VIDEO", "DTV"),
    ("WIRELESS", "NL"),
    ("UPGRADE INTERNET", "UG"),
]

# --- metric mapping (Sheet row label -> Tableau crosstab column header) ---
# OPT section — scraped straight from the ATT crosstab.
OPT_SCRAPED: Dict[str, str] = {
    "Active Headcount on Tableau": "Rep Count",
    "New Internets":               "New Internet",
    "Upgrades":                    "Upgrd Internet",
    "DTV":                         "Video Sales",
    "New Lines":                   "Wrlss Lines New/Port",
    "% of Wireless Rep Count":     "% Wireless rep count",
    "Scorecard Ranking":           "Ranking",
}
# OPT section — computed. Total Apps = sum of these four sale-type rows.
TOTAL_APPS_COMPONENTS = ["New Internets", "Upgrades", "DTV", "New Lines"]
# OPT section — national totals (Grand Total row), same value on every tab.
OPT_NATIONAL: Dict[str, str] = {"National AVG Apps": "Sales Per Rep Avg"}
# OPT section — scraped from the INT crosstab.
INT_SCRAPED: Dict[str, str] = {
    "AVG New INT Per Active Headcount": "New Int Sales Per Rep Avg",
}
INT_NATIONAL: Dict[str, str] = {
    "National New INT AVG": "New Int Sales Per Rep Avg",
}
# Office Metrics section — scraped from the ATT crosstab.
METRIC_GOALS_SCRAPED: Dict[str, str] = {"1 GIG%": "New Internet 1Gig+ Mix%"}
# Office Metrics section — scraped from the Metrics crosstab.
METRICS_SCRAPED: Dict[str, str] = {
    "6+ days out scheduled":   "% of sales scheduled 6+ days out (4 wks)",
    # "Intall" is the literal (mis)spelling of the Tableau header — do NOT
    # "fix" it; the typo is what the Metrics-Install crosstab actually emits.
    "6+ days Orders Scheduled": "Intall Scheduled 6+ Days New Internet Count (4 wk)",
    "Jep Orders":              "Jep New Internet Count (4 wk)",
    "0-30 Day Cancel Rate":    "0-30 day New Internet cancel rate",
    "30-60 activation rate %": "30-60 day New Internet activation rate",
}
# Office Metrics section — scraped from the CHURN crosstab (% values).
CHURN_SCRAPED: Dict[str, str] = {
    "0-30 Day Churn": "0-30 Day Churn",
    "30 Day Churn":   "30 Day Churn",
    "60 day Churn":   "60 Day Churn",
    "90 day Churn":   "90 Day Churn",
}
# Wireless Metrics section — scraped from the Wireless Metrics crosstab.
WIRELESS_SCRAPED: Dict[str, str] = {
    "BYOD Lines":                     "BYOD Lines (Metrics)",
    "BYOD %":                         "BYOD Line % (Metrics)",
    "New Lines":                      "New Lines (Metrics)",
    "New Lines %":                    "New Line % (Metrics)",
    "Approval % (Rolling 4 weeks)":   "Approval % (Rolling 4 Weeks)",
    "30-60 Activation Rate":          "30-60 Activation Rate",
    "0-30 day cancel Rate":           "0-30 day wireless cancel rate",
    "0-30 day Wireless Cancels":      "0-30 day wireless cancels",
    "Extra / Preimum Plan % Metrics": "Extra/Premium Plan % (Metrics)",
    "Next up %":                      "Next Up % (Metrics)",
}
# Wireless Metrics section — churn rows, scraped from the Wireless Churn crosstab.
WIRELESS_CHURN_SCRAPED: Dict[str, str] = {
    "0-30 Day Churn": "0-30 Day Churn",
    "30 Day Churn":   "30 Day Churn",
    "60 Day Churn":   "60 Day Churn",
    "90 Day Churn":   "90 Day Churn",
}
# Office Metrics section — scraped from the Captain's Bonus crosstab. The
# 30-60 Day Cancel Rate is computed (100% − Activation/Approval %).
CAPTAINS_SCRAPED: Dict[str, str] = {
    "Activation /Approval %": "Rolling 4 Weeks",
}

def _norm(s) -> str:
    """Normalize a label / header / name for matching: lowercase, trim, drop
    apostrophes + periods, collapse whitespace, drop spaces around / - %."""
    s = str(s or "").strip().lower()
    s = s.replace("'", "").replace("’", "").replace(".", "")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*([/\-%])\s*", r"\1", s)
    return s


# Some ICD tabs label an OPT row slightly differently — try these alternates.
ALT_LABELS: Dict[str, List[str]] = {
    "% of Wireless Rep Count": ["% of Wireless Attachment", "% Wireless Rep Count",
                                "% Wireless Attachment"],
    "National AVG Apps": ["National AVG for sales"],
    "New Internets": ["New Internet"],
    "DTV": ["DTVs"],
    "0-30 Day Churn": ["0-30 Churn"],
}

# Rows legitimately absent on specific tabs — never flagged as data gaps.
# Keyed by normalized tab name -> set of normalized labels. Raf Hidalgo is no
# longer in the field, so his tab has no Personal Production row by design.
_EXPECTED_MISSING: Dict[str, set] = {
    "raf hidalgo": {"personal production"},
}


def _to_num(s) -> Optional[float]:
    """Parse a crosstab cell to a number. Strips %, commas. None if blank."""
    t = str(s or "").strip().replace(",", "").replace("%", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _parse_money(s) -> Optional[float]:
    """Parse a currency cell like '$2,440.00' or '($866.67)' (parens = neg)."""
    t = str(s or "").strip()
    if not t:
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace("$", "").replace(",", "").strip()
    if not t:
        return None
    try:
        v = float(t)
        return -v if neg else v
    except ValueError:
        return None


# ---------------------------------------------------------------- download

def _find_tableau_page(browser):
    """Return an SSO'd Tableau tab in the connected Chrome, or None."""
    for ctx in browser.contexts:
        for pg in ctx.pages:
            u = (pg.url or "").lower()
            if "online.tableau.com" in u and "/login" not in u and "/idp/" not in u:
                return pg
    return None


# A Tableau crosstab pull can time out mid-click when the viz is slow to
# render or a transient error toast intercepts the Download button (Eve scrape
# glitches: rows 18-64). drive_crosstab_dialog re-navigates to the view on
# entry, so re-driving it from scratch is a clean recovery. INERT on a healthy
# pull — download_crosstab returns on the first attempt and never loops.
_CROSSTAB_RETRIES = 3


def _is_scrape_timeout(exc: Exception) -> bool:
    return "timeout" in str(exc).lower()


def _is_target_closed(exc: Exception) -> bool:
    s = str(exc).lower()
    return ("target page" in s or "target closed" in s
            or "has been closed" in s)


def download_crosstab(view_url: str, crosstab_sheet: str, out_path: Path,
                      verbose: bool = True, page=None) -> Path:
    """Drive Tableau's Download → Crosstab on `view_url` and save the
    `crosstab_sheet` sheet as a CSV. Returns out_path.

    Runs through the patchright stealth session (self-logs into ownerville →
    Tableau via the persistent profile), NOT the CDP/Report-Chrome path. The
    CDP path depended on a human keeping ownerville + a live Tableau tab in
    Report Chrome and silently failed twice on 2026-05-25 (Eve's ATT/Carlos
    OPT didn't fill). patchright is the same proven path the Alphalete Org OPT
    uses and needs no human-launched Chrome.

    `run_opt_phase` passes a shared `page` so all ~8 crosstab pulls in a run
    reuse ONE login. If `page` is None, opens its own one-shot session.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    last: Optional[Exception] = None
    for attempt in range(_CROSSTAB_RETRIES):
        try:
            if page is not None:
                return drive_crosstab_dialog(page, view_url, crosstab_sheet,
                                             out_path, verbose=verbose)
            # Lazy import — tableau_patchright imports drive_crosstab_dialog
            # from this module, so a top-level import would be circular.
            from automations.shared.tableau_patchright import tableau_session
            with tableau_session(verbose=verbose) as pg:
                return drive_crosstab_dialog(pg, view_url, crosstab_sheet,
                                             out_path, verbose=verbose)
        except Exception as e:
            last = e
            shared = page is not None
            # Retry a transient scrape timeout — drive_crosstab_dialog
            # re-navigates to view_url on entry, so the next attempt starts
            # clean. For a fresh one-shot session we can also retry a closed
            # target; on a SHARED page (run_opt_phase owns the session) a
            # closed target can't be recovered here, so don't mask it.
            retryable = (_is_scrape_timeout(e)
                         or (not shared and _is_target_closed(e)))
            if retryable and attempt < _CROSSTAB_RETRIES - 1:
                if verbose:
                    print(f"  ⚠ crosstab {crosstab_sheet!r} attempt "
                          f"{attempt + 1}/{_CROSSTAB_RETRIES} failed "
                          f"({type(e).__name__}) — re-navigating and retrying",
                          flush=True)
                continue
            raise
    assert last is not None
    raise last


def _norm_crosstab_sheet(s: str) -> str:
    """Normalize a Crosstab sheet name for rename-tolerant matching: drop a
    trailing parenthetical (Tableau adds/removes these — e.g. 'ICD Churn
    (Wireless)' vs 'ICD Churn'), collapse whitespace, lowercase."""
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s or "")
    return re.sub(r"\s+", " ", s).strip().lower()


def _match_crosstab_sheet(available: List[str], wanted: str,
                          verbose: bool = True) -> Optional[int]:
    """Find `wanted` among the `available` Crosstab thumbnails, with fallbacks
    so a Tableau-side rename degrades gracefully instead of aborting the whole
    OPT phase (the 2026-05-25 'ICD Churn (Wireless)' incident):
      1) exact match
      2) case-insensitive exact
      3) rename-tolerant (trailing parentheticals stripped) — but ONLY when
         it's unambiguous (exactly one candidate); never guess between two.
    Returns the matched index, or None."""
    for i, a in enumerate(available):                 # 1) exact
        if a == wanted:
            return i
    wl = (wanted or "").strip().lower()
    for i, a in enumerate(available):                 # 2) case-insensitive
        if a.strip().lower() == wl:
            if verbose:
                print(f"  (matched {wanted!r} -> {a!r}, case-insensitive)", flush=True)
            return i
    nw = _norm_crosstab_sheet(wanted)                 # 3) rename-tolerant, unambiguous
    hits = [i for i, a in enumerate(available) if _norm_crosstab_sheet(a) == nw]
    if len(hits) == 1:
        print(f"  WARNING: Crosstab sheet {wanted!r} not found exactly; matched "
              f"{available[hits[0]]!r} (rename-tolerant). Update the sheet-name "
              f"constant in opt_phase.py to silence this.", flush=True)
        return hits[0]
    return None


def list_crosstab_sheets(view_url: str, page=None, verbose: bool = False,
                         settle_s: int = 6, max_s: int = 60) -> List[str]:
    """Open `view_url`'s Download → Crosstab dialog and RETURN the worksheet
    thumbnail names (no download). Lets callers AUTO-DETECT which sheets a
    dashboard currently offers — e.g. the Fiber report's per-captainship
    'CB Activations (<team>)' sheets — so a hardcoded team list can't go stale
    when a captainship is added or removed in Tableau (Aron's captainship
    dissolved 2026-06-10).

    Heavy dashboards hydrate thumbnails progressively, so we poll until the
    count holds steady for `settle_s` seconds (capped at `max_s`) rather than
    reading once. Opens its own tableau_session when `page` is None."""
    import contextlib
    from automations.shared.tableau_patchright import tableau_session

    @contextlib.contextmanager
    def _sess():
        if page is not None:
            yield page
        else:
            with tableau_session(verbose=verbose) as pg:
                yield pg

    with _sess() as pg:
        try:
            pg.goto("about:blank", wait_until="domcontentloaded", timeout=10_000)
        except Exception:
            pass
        pg.goto(view_url, wait_until="domcontentloaded")
        viz = pg.frame_locator('iframe[title="Data Visualization"]')
        dl_btn = viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]')
        dl_btn.wait_for(state="visible", timeout=120_000)
        pg.wait_for_timeout(25_000)
        # Dismiss any error toast overlaying the toolbar (same as drive_crosstab_dialog).
        try:
            toast = viz.locator('[data-tb-test-id^="banner-error-toast"]')
            if toast.count():
                toast.first.evaluate(
                    "el => { (el.closest('.tab-shared-widget-toaster') || el).remove(); }")
                pg.wait_for_timeout(500)
        except Exception:
            pass
        dl_btn.click()
        pg.wait_for_timeout(1800)
        viz.locator(
            '[data-tb-test-id="download-flyout-download-crosstab-MenuItem"]').click()
        thumbs = viz.locator('[data-tb-test-id^="sheet-thumbnail-"]')
        last, stable = -1, 0
        for _ in range(max_s):
            pg.wait_for_timeout(1000)
            n = thumbs.count()
            if n and n == last:
                stable += 1
                if stable >= settle_s:
                    break
            else:
                stable = 0
            last = n
        n = thumbs.count()
        names = [thumbs.nth(i).inner_text().strip() for i in range(n)]
        if verbose:
            print(f"  crosstab dialog offers {n} sheet(s): {names}", flush=True)
        try:
            pg.keyboard.press("Escape")
        except Exception:
            pass
        return names


def drive_crosstab_dialog(page, view_url: str, crosstab_sheet: str,
                          out_path: Path, verbose: bool = True,
                          skip_nav: bool = False) -> Path:
    """The Page-level Crosstab driver: navigates to `view_url`, opens the
    Download → Crosstab dialog, picks `crosstab_sheet`, exports CSV.

    Reusable across browser-launch strategies (CDP-attached or patchright).
    Caller is responsible for browser lifecycle + Tableau auth state.

    skip_nav: when True, do NOT navigate — assume the caller already loaded
    the view AND set up any interactive state (e.g. a week selection) that a
    fresh navigation would reset. Used by views whose week can't be driven by
    a URL param (JE 'Sales Week Ending')."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Navigate to about:blank first to force a clean DOM (avoids
    # leftover modal state from a previous crashed download). Then
    # navigate to the actual view. page.reload triggers an asyncio
    # race on Python 3.9 / Playwright's sync API; this is the
    # workaround.
    if not skip_nav:
        try:
            page.goto("about:blank", wait_until="domcontentloaded", timeout=10_000)
        except Exception:
            pass
        page.goto(view_url, wait_until="domcontentloaded")

    viz = page.frame_locator('iframe[title="Data Visualization"]')
    dl_btn = viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]')
    # Heavy views render their toolbar LATE: the all-reps ORDER LOG / CHURN
    # views (canceled_orders, disconnects, churn) sit on an "Opening workbook
    # → Computing models" overlay for ~50s before the toolbar — and thus the
    # Download button — even exists in the DOM (Eve measured ~50s, 2026-06-02).
    # The old 35s timeout fired first, so the pull died with
    # "viz-viewer-toolbar-button-download not visible" though the button was
    # fine. wait_for returns the instant it appears, so the generous ceiling
    # doesn't slow the light single-owner views (≈15s, e.g. order_log).
    dl_btn.wait_for(state="visible", timeout=120_000)
    # Let Tableau hydrate the data behind the viz before exporting.
    # Complex per-rep views (NDS Weekly Metrics, Activation Rates) take
    # longer to load; their crosstab Download button stays disabled
    # until the underlying data is in. Bumped from 10s to 25s.
    page.wait_for_timeout(25_000)

    def _clear_error_toast() -> None:
        """Tableau intermittently raises a viz error toast that overlays the
        toolbar and intercepts clicks on the Download button, so dl_btn.click()
        times out (then the page can close) even though the button is visible +
        enabled. Tableau renders the toast with more than one test-id —
        'banner-error-toast-widget' (Fiber PSS-country view) and
        'banner-error-toast-message' (scheduled-6-days-out Order Log) — so match
        any 'banner-error-toast*' (both live in the same .tab-shared-widget-
        toaster container, which is what actually intercepts the pointer). When
        a toast is present: log its text (so the real Tableau error shows up in
        the run log instead of an opaque click timeout) and dismiss it so the
        click can land. No-op when there's no toast — the normal download path
        is byte-for-byte unchanged. (2026-06-02)"""
        toast = viz.locator('[data-tb-test-id^="banner-error-toast"]')
        try:
            if toast.count() == 0:
                return
        except Exception:
            return
        try:
            msg = toast.first.inner_text(timeout=2_000).strip()
        except Exception:
            msg = "(toast text unreadable)"
        if verbose:
            print(f"  ⚠ Tableau error toast over Download: {msg!r} — dismissing",
                  flush=True)
        for sel in ('button[aria-label*="lose" i]',
                    'button[aria-label*="ismiss" i]',
                    '[data-tb-test-id*="dismiss" i]',
                    '[data-tb-test-id*="close" i]'):
            try:
                btn = toast.locator(sel)
                if btn.count() > 0:
                    btn.first.click(timeout=3_000)
                    page.wait_for_timeout(500)
                    return
            except Exception:
                continue
        # No close control found — remove the toaster container from the DOM so
        # it stops intercepting pointer events. Cosmetic only; doesn't touch the
        # viz or its data.
        try:
            toast.first.evaluate(
                "el => { (el.closest('.tab-shared-widget-toaster') || el)"
                ".remove(); }")
        except Exception:
            pass
        page.wait_for_timeout(500)

    if verbose:
        print(f"Download → Crosstab → {crosstab_sheet!r} → CSV…", flush=True)
    _clear_error_toast()
    dl_btn.click()
    page.wait_for_timeout(1800)
    viz.locator('[data-tb-test-id="download-flyout-download-crosstab-MenuItem"]').click()

    # Find the requested worksheet in the Crosstab dialog. Heavy views hydrate
    # their thumbnails PROGRESSIVELY and with gaps — the ATT 1-PAGER loads its
    # 11 chart thumbnails, pauses several seconds, THEN the summary sheets — so
    # any "wait until the count stops changing" heuristic settles too early and
    # misses later-loading sheets like 'ICD Summary - ATT (V2)'. Poll for the
    # TARGET sheet name directly instead; immune to hydration gaps (2026-06-02).
    thumbs = viz.locator('[data-tb-test-id^="sheet-thumbnail-"]')

    def _poll_for_target(max_s: int = 45):
        """Poll the dialog up to max_s seconds until the requested worksheet
        thumbnail appears. Returns (idx, available, count); idx is None if it
        never showed."""
        avail = []
        for _ in range(max_s):
            page.wait_for_timeout(1000)
            n = thumbs.count()
            if n == 0:
                continue
            avail = [thumbs.nth(i).inner_text().strip() for i in range(n)]
            hit = _match_crosstab_sheet(avail, crosstab_sheet, verbose=False)
            if hit is not None:
                return hit, avail, n
        return None, avail, thumbs.count()

    idx, available, count = _poll_for_target()

    # If the dialog opened completely empty, the viz hadn't hydrated when
    # Tableau snapshotted worksheet state at open-time — sheets won't appear no
    # matter how long we wait. Close, give the viz 20s more, reopen once, poll
    # again. (Slow machines — Eve's Windows, 2026-05-28 — self-heal here.)
    if idx is None and count == 0:
        if verbose:
            print("  ⚠ Crosstab dialog opened empty — reopening once after extra hydration…", flush=True)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(20_000)
        _clear_error_toast()
        dl_btn.click()
        page.wait_for_timeout(1800)
        viz.locator('[data-tb-test-id="download-flyout-download-crosstab-MenuItem"]').click()
        idx, available, count = _poll_for_target()

    if idx is None:
        raise RuntimeError(
            f"Couldn't find the {crosstab_sheet!r} sheet in the Crosstab "
            f"dialog — saw {len(available)} thumb(s): {available!r}. "
            "The view may have changed."
        )
    # Select the sheet, then export. The hard-won lesson (2026-05-24):
    # the thumbnail click strategies must be tried ONE AT A TIME and we
    # must STOP as soon as the sheet is selected — because clicking an
    # ALREADY-selected thumbnail toggles it back OFF. Firing every
    # strategy unconditionally (the old behavior) selected then
    # deselected on dialogs where the first strategy already worked,
    # which is why the same code worked on some worksheets and silently
    # failed on others.
    #
    # The signal that a sheet is selected: the Export button enables
    # (a format radio is selected by default). So: pick a format, then
    # walk the click strategies, polling Export after each, and break
    # the instant it enables.
    target_thumb = thumbs.nth(idx)
    export_btn = viz.locator('[data-tb-test-id="export-crosstab-export-Button"]')

    def _select_format(format_id: str) -> None:
        """Click the format radio. Tableau's radio has two test-IDs:
        `-Label` (the <label>, visually on top) and `-RadioButton` (the
        <input>, behind it). The label is the right click target —
        labels forward clicks to their input natively; clicking the
        input directly fails because the label intercepts pointer
        events. (Verified 2026-05-21.)"""
        label = viz.locator(
            f'[data-tb-test-id="crosstab-options-dialog-radio-{format_id}-Label"]')
        if label.count() > 0:
            try:
                label.first.click(timeout=5_000)
            except Exception:
                radio = viz.locator(
                    f'[data-tb-test-id="crosstab-options-dialog-radio-{format_id}-RadioButton"]')
                try:
                    radio.first.click(force=True, timeout=5_000)
                except Exception:
                    pass
        page.wait_for_timeout(800)

    def _export_enabled_within(secs: int) -> bool:
        for _ in range(secs):
            try:
                if export_btn.is_enabled(timeout=2_000):
                    return True
            except Exception:
                pass
            page.wait_for_timeout(1000)
        return False

    # Click strategies in order: locator-based first (clean single
    # selection on dialogs that accept them), then the synthetic /
    # coordinate / force clicks that crack the silent-no-op dialogs.
    def _click_css(sel):
        btn = viz.locator(sel)
        if btn.count() == 0:
            raise RuntimeError("no match")
        btn.first.click(timeout=5_000)

    def _click_xpath(xp):
        anc = target_thumb.locator(xp)
        if anc.count() == 0:
            raise RuntimeError("no match")
        anc.first.click(timeout=5_000)

    def _click_mouse_center():
        bbox = target_thumb.bounding_box()
        if not bbox:
            raise RuntimeError("no bbox")
        page.mouse.click(bbox["x"] + bbox["width"] / 2,
                         bbox["y"] + bbox["height"] / 2)

    click_attempts = [
        ("css role=button",   lambda: _click_css(f'[role="button"]:has-text("{crosstab_sheet}")')),
        ("css button",        lambda: _click_css(f'button:has-text("{crosstab_sheet}")')),
        ("css role=checkbox", lambda: _click_css(f'[role="checkbox"]:has-text("{crosstab_sheet}")')),
        ("css label",         lambda: _click_css(f'label:has-text("{crosstab_sheet}")')),
        ("xpath button",      lambda: _click_xpath('xpath=ancestor::*[@role="button"][1]')),
        ("xpath checkbox",    lambda: _click_xpath('xpath=ancestor::*[@role="checkbox"][1]')),
        ("dispatch_event",    lambda: target_thumb.dispatch_event("click")),
        ("mouse center",      _click_mouse_center),
        ("force click",       lambda: target_thumb.click(force=True)),
    ]

    # Try each format; within a format, walk click strategies one at a
    # time, stopping at the first that enables Export. CSV first so the
    # downstream parsers keep getting tab-CSV; Excel fallback for views
    # that only export as xlsx.
    chosen_format = None
    for fmt in ("csv", "excel"):
        _select_format(fmt)
        for name, action in click_attempts:
            try:
                action()
            except Exception:
                continue
            page.wait_for_timeout(1200)
            if _export_enabled_within(6):
                chosen_format = fmt
                if verbose:
                    print(f"  selected via {name} ({fmt})", flush=True)
                break
        if chosen_format:
            break

    if chosen_format == "excel" and str(out_path).lower().endswith(".csv"):
        # Caller passed .csv; the file is really xlsx. _read_tab_csv
        # sniffs the PK magic bytes so the extension can stay .csv.
        pass

    if chosen_format is None:
        # Diagnostic screenshot at the moment Export refused to enable —
        # captures dialog DOM state for later inspection.
        try:
            from automations.alphalete_org_report.opt_nds import OUTPUT_DIR as _OD
            shot_path = _OD / f"crosstab_disabled_{crosstab_sheet.replace(' ', '_').replace('(', '').replace(')', '')}.png"
            page.screenshot(path=str(shot_path), full_page=True)
            shot_note = f" Screenshot saved: {shot_path}"
        except Exception:
            shot_note = ""
        raise RuntimeError(
            f"Crosstab Download button stayed disabled for {crosstab_sheet!r} "
            "in both CSV and Excel formats — Tableau may have no data to "
            "export for this view's current filter state." + shot_note
        )
    if verbose:
        print(f"  format: {chosen_format}", flush=True)

    # 300s ceiling lets a wide Order-Date window (Canceled Orders /
    # Disconnects pull 30 days) finish; fast pulls return as soon as the
    # download event fires so they don't pay for the bigger budget.
    with page.expect_download(timeout=300_000) as dl_info:
        export_btn.click()
    dl_info.value.save_as(str(out_path))
    if verbose:
        print(f"saved crosstab: {out_path} ({out_path.stat().st_size:,} bytes)", flush=True)
    return out_path


# ----------------------------------------------------- View Data scraping
# Some views (Fiber Lead, Program Summary) have per-ICD tables Tableau won't
# export as a crosstab (the Download button stays disabled) and that render
# on a canvas. Their "Download -> Data" View Data window DOES render the rows
# as DOM text — so we drive that and scrape it.

_OWNERVILLE = "https://v2.ownerville.com/index.cfm"


def _reauth_tableau(ctx):
    """Refresh the Tableau session via ownerville's 'Login to Tableau' SSO
    link, in a dedicated tab so the user's own tabs are left alone. Returns
    the working page (now on a Tableau view, authenticated)."""
    work = ctx.new_page()
    work.goto(_OWNERVILLE, wait_until="domcontentloaded")
    work.wait_for_timeout(6000)
    m = re.search(r"rqst=([A-Za-z0-9_]+)", work.url or "")
    if not m:
        href = work.evaluate(
            "() => { const a=[...document.querySelectorAll('a')]"
            ".find(x=>/p=81/.test(x.getAttribute('href')||'')); "
            "return a?a.getAttribute('href'):''; }")
        m = re.search(r"rqst=([A-Za-z0-9_]+)", href or "")
    if not m:
        work.close()
        raise RuntimeError(
            "Couldn't re-auth Tableau — ownerville isn't logged in in Report "
            "Chrome. Open v2.ownerville.com, log in, then run again."
        )
    work.goto(f"{_OWNERVILLE}?p=81&rqst={m.group(1)}&ssook=1",
              wait_until="domcontentloaded")
    work.wait_for_timeout(15_000)
    return work


def _wait_viz_loaded(page, timeout_s: int = 90) -> None:
    """Wait for the Tableau viz to finish initializing (loading glass gone)."""
    for _ in range(timeout_s):
        glassed = False
        for f in page.frames:
            try:
                loc = f.locator('#loadingGlassPane')
                if loc.count() and loc.first.is_visible():
                    glassed = True
                    break
            except Exception:
                pass
        if not glassed:
            break
        page.wait_for_timeout(1000)
    page.wait_for_timeout(5000)


def _parse_view_data_text(txt: str) -> Tuple[List[str], List[List[str]]]:
    """Parse a View Data window innerText snapshot into (field_names, records).
    Header layout: '<N> rows <M> fields', then 'Download', then K pairs of
    (datasource, field-name), then the data as groups of K cells.

    Note on K vs M: Tableau's "<M> fields" header counts every conceptual
    field including ones not present as a (datasource, field-name) pair in
    the text (e.g. Fiber Penetration by Zip reports "14 fields" but emits
    only 10 visible pairs; the row width is 10, not 14). So we count the
    ACTUAL header pairs by walking forward from "Download" while the
    datasource line repeats, then stop. Records are sliced at K cells,
    not M."""
    lines = [l.strip() for l in (txt or "").splitlines() if l.strip()]
    if not re.search(r"\d+\s+rows?\s+\d+\s+fields?",
                     " ".join(lines[:14])):
        return [], []
    try:
        di = lines.index("Download")
    except ValueError:
        return [], []
    # The first non-Download line is the datasource marker — it repeats
    # before every field-name pair. Walk forward until that marker stops
    # matching: that's the start of the data section.
    if di + 1 >= len(lines):
        return [], []
    ds_marker = lines[di + 1]
    fields: List[str] = []
    i = di + 1
    while i + 1 < len(lines) and lines[i] == ds_marker:
        fields.append(lines[i + 1])
        i += 2
    if not fields:
        return [], []
    nfields = len(fields)
    data = lines[i:]
    records = [data[j:j + nfields]
               for j in range(0, len(data) - nfields + 1, nfields)]
    return fields, records


def _scrape_view_data_grid(win, verbose: bool = True,
                           max_iter: int = 250,
                           stale_max: int = 10,
                           scroll_step: float = 0.75,
                           scroll_wait_ms: int = 900,
                           jump_every: Optional[int] = 4,
                           ) -> Tuple[List[str], List[List[str]]]:
    """Scroll-scrape the View Data window's virtualized grid. Returns
    (field_names, records).

    Scrolls the **top-3** scrollable containers (not just the tallest) and
    alternates incremental scrolls with a hard jump to scrollHeight — needed
    for multi-group grids (e.g. Fiber's by-state by-zip view) where a single
    container's incremental scroll plateaus after the first group is loaded.
    Stale threshold is generous so a slow Tableau redraw doesn't stop us
    short of the row count we know is coming.

    Tuning params for sparse single-group grids (SARA Plus office) where
    jump-to-bottom skips middle rows:
      jump_every=None disables jumps (pure linear scroll)
      scroll_step=0.35 (smaller) sweeps without skipping rows
      scroll_wait_ms=1800 (longer) gives Tableau time to redraw
      stale_max=30 (more patience) survives slow re-renders mid-grid
    """
    win.wait_for_timeout(4500)
    fields: List[str] = []
    seen: Dict[tuple, List[str]] = {}
    expect = None
    last = -1
    stale = 0
    for i in range(max_iter):
        txt = win.evaluate("() => document.body ? document.body.innerText : ''")
        if expect is None:
            mm = re.search(r"(\d+)\s+rows?\s+\d+\s+fields?", txt or "")
            expect = int(mm.group(1)) if mm else None
        f, recs = _parse_view_data_text(txt)
        if f and not fields:
            fields = f
        for r in recs:
            seen[tuple(r)] = r
        if expect and len(seen) >= expect:
            break
        stale = stale + 1 if len(seen) == last else 0
        if stale >= stale_max:
            break
        last = len(seen)
        jump = (jump_every is not None and i % jump_every == jump_every - 1)
        win.evaluate(f"""() => {{
          const cands = [];
          document.querySelectorAll('*').forEach(e => {{
            const d = e.scrollHeight - e.clientHeight;
            if (d > 0 && e.clientHeight > 120) cands.push([d, e]);
          }});
          cands.sort((a, b) => b[0] - a[0]);
          cands.slice(0, 3).forEach(([d, e]) => {{
            if ({str(jump).lower()}) {{
              e.scrollTop = e.scrollHeight;
            }} else {{
              e.scrollTop += Math.round(e.clientHeight * {scroll_step});
            }}
          }});
        }}""")
        win.wait_for_timeout(scroll_wait_ms)
    if verbose:
        print(f"  scraped {len(seen)}/{expect or '?'} View Data rows", flush=True)
    return fields, list(seen.values())


def _scrape_one_view_data(page, ctx, view_url: str, verbose: bool = True,
                          activate_xy: Optional[Tuple[float, float]] = None,
                          scrape_kwargs: Optional[Dict] = None,
                          ) -> Tuple[List[str], List[List[str]]]:
    """Navigate an already-authenticated `page` to `view_url`, drive
    Download -> Data, scrape + close the View Data window. Returns
    (fields, records). Reusable in a loop with one shared page."""
    for pg in list(ctx.pages):
        if "hybrid-window" in (pg.url or "") or "/assets/vizql/" in (pg.url or ""):
            try:
                pg.close()
            except Exception:
                pass
    page.goto(view_url, wait_until="domcontentloaded")
    viz = page.frame_locator('iframe[title="Data Visualization"]')
    dl = viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]')
    dl.wait_for(state="visible", timeout=40_000)
    _wait_viz_loaded(page)
    for _ in range(3):
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    data_item = viz.locator(
        '[data-tb-test-id="download-flyout-download-data-MenuItem"]')

    def _open_flyout():
        for _ in range(8):
            try:
                dl.click(timeout=8000)
                return True
            except Exception:
                page.wait_for_timeout(2000)
        return False

    before = set(ctx.pages)
    if activate_xy:
        # 'Download -> Data' is disabled until a worksheet is active. Click a
        # column header (activates the sheet, selects no data mark — a mark
        # would scope the View Data to one zip). The header's y drifts per
        # ICD, so try a few within the header band and keep whichever one
        # leaves the 'Data' menu item enabled.
        box = page.query_selector(
            'iframe[title="Data Visualization"]').bounding_box()
        x0, y0 = activate_xy
        activated = False
        for dy in (0.0, -0.02, 0.02, -0.03, 0.01, -0.01):
            cx = box["x"] + box["width"] * x0
            cy = box["y"] + box["height"] * (y0 + dy)
            page.mouse.click(cx, cy)
            page.wait_for_timeout(1100)
            page.mouse.click(cx, cy)
            page.wait_for_timeout(1100)
            if not _open_flyout():
                continue
            page.wait_for_timeout(1400)
            if data_item.get_attribute("aria-disabled") != "true":
                activated = True
                break
            page.keyboard.press("Escape")
            page.wait_for_timeout(600)
        if not activated:
            raise RuntimeError("couldn't activate the worksheet for Download->Data")
    else:
        if not _open_flyout():
            raise RuntimeError("Download button stayed blocked — viz didn't load")
        page.wait_for_timeout(1400)
    if verbose:
        print("Download -> Data -> View Data window…", flush=True)
    data_item.click()
    page.wait_for_timeout(7000)
    win = next((pg for pg in ctx.pages if pg not in before), None)
    if win is None:
        raise RuntimeError("Download -> Data didn't open a View Data window")
    try:
        return _scrape_view_data_grid(win, verbose, **(scrape_kwargs or {}))
    finally:
        try:
            win.close()
        except Exception:
            pass


def scrape_view_data(view_url: str, verbose: bool = True,
                     activate_xy: Optional[Tuple[float, float]] = None,
                     page=None) -> Tuple[List[str], List[List[str]]]:
    """Drive Tableau's Download -> Data on `view_url` and scrape the View Data
    window. Returns (field_names, records). Used for views whose per-ICD table
    won't crosstab-export.

    Runs through the patchright session (self-logs in) like download_crosstab.
    A caller can pass a shared `page` to reuse one login; otherwise opens a
    one-shot session.

    On a multi-sheet dashboard, 'Download -> Data' is disabled until a
    worksheet is selected — pass `activate_xy` (fractional x, y of the viz)
    to click inside the target worksheet first."""
    if page is not None:
        return _scrape_one_view_data(page, page.context, view_url, verbose, activate_xy)
    from automations.shared.tableau_patchright import tableau_session
    with tableau_session(verbose=verbose) as pg:
        return _scrape_one_view_data(pg, pg.context, view_url, verbose, activate_xy)


def _program_summary_url(we_sunday: Optional[dt.date] = None) -> str:
    """PROGRAM SUMMARY view URL, pinned to a week via its 'Processed Week'
    filter. The filter value is the week's MONDAY in ISO (YYYY-MM-DD) — ISO
    works, MM/DD/YYYY is silently ignored (same as the Carlos DD view, verified
    2026-06-01). Without a pin the view returns whatever week it was last
    hand-advanced to, which silently wrote one week's DD into another week's
    column (the 5/24/5/31 duplication, fixed 2026-06-04)."""
    if we_sunday is None:
        return PROGRAM_SUMMARY_VIEW_URL
    from urllib.parse import quote
    monday = we_sunday - dt.timedelta(days=6)
    sep = "&" if "?" in PROGRAM_SUMMARY_VIEW_URL else "?"
    return (f"{PROGRAM_SUMMARY_VIEW_URL}{sep}"
            f"{quote('Processed Week')}={quote(monday.isoformat())}")


def download_program_summary(out_path: Path = PROGRAM_SUMMARY_PATH,
                             verbose: bool = True, page=None,
                             we_sunday: Optional[dt.date] = None) -> Path:
    """Scrape the Program Summary View Data and save it tab-delimited so the
    parse step (and --skip-download) can reuse it. Pinned to `we_sunday`'s week
    via the view's 'Processed Week' filter when given."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields, records = scrape_view_data(_program_summary_url(we_sunday),
                                       verbose=verbose, page=page)
    lines = ["\t".join(fields)] + ["\t".join(r) for r in records]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    if verbose:
        print(f"saved Program Summary view-data: {out_path} "
              f"({len(records)} rows)", flush=True)
    return out_path


def _fiber_overview(fields: List[str], records: List[List[str]]
                    ) -> Tuple[str, Optional[int], Optional[int]]:
    """Parse one ICD's 'Program Overview' View Data (a clean Measure
    Names/Values table) into (penetration %, Total Leads, Expected Fiber Sales).
      Lead Count  -> Total Leads
      Total Sales -> Penetration Rate = Total Sales / Lead Count
      Assigned Fiber Lead Penetration -> goal; Expected = round(Lead Count*goal)
    Returns ("", None, None) if the worksheet didn't yield the measures."""
    mn_i = next((i for i, f in enumerate(fields)
                 if "measure names" in f.lower()), None)
    mv_i = next((i for i, f in enumerate(fields)
                 if "measure values" in f.lower()), None)
    if mn_i is None or mv_i is None:
        return "", None, None
    by: Dict[str, str] = {}
    for r in records:
        if len(r) > max(mn_i, mv_i):
            by[r[mn_i].strip().lower()] = r[mv_i].strip()
    lead = _to_num(by.get("lead count", ""))
    sales = _to_num(by.get("total sales", ""))
    goal = _to_num(by.get("assigned fiber lead penetration", ""))
    # Fill what the data IS — never blank a weird value (Megan 2026-05-25:
    # "fill in what it is/has, turn the font red on anything that looks weird").
    # A brand-new ICD whose Fiber isn't set up can report nonsense (Eric Zech:
    # 967 sales vs 256 leads -> 377%, goal 3.777); we write it anyway and the
    # fill red-flags it (looks_weird_pct) so a human eyeballs it.
    penetration = ""
    if lead:
        penetration = f"{(sales or 0) / lead * 100:.2f}%"
    elif lead == 0:
        penetration = "0%"
    expected = (int(round(lead * goal))
                if (lead is not None and goal is not None) else None)
    lead_i = int(round(lead)) if lead is not None else None
    return penetration, lead_i, expected


def _fiber_name_candidates(tab: str, as_owner_map: dict, aliases_map: dict
                           ) -> List[str]:
    """Owner-Name values to try for a tab — the Fiber view may spell a name
    differently than the Sheet tab. Tries the tab name, its parenthetical
    parts, the AppStream owner, and any alias-group members."""
    cands = [tab]
    m = re.match(r"^(.*?)\s*\((.+?)\)\s*$", tab or "")
    if m:
        cands += [m.group(2).strip(), m.group(1).strip()]
    if as_owner_map.get(tab):
        cands.append(as_owner_map[tab])
    for canon, al in (aliases_map or {}).items():
        grp = [canon] + list(al)
        if _norm(tab) in {_norm(g) for g in grp}:
            cands += grp
    # Dedup by literal lowercase — NOT by _norm — because Tableau's Owner
    # Name filter does exact-text matching, so "DMari Longmire" and
    # "D'Mari Longmire" (same _norm) must both make it into the list.
    seen, out = set(), []
    for c in cands:
        c = (c or "").strip()
        key = c.lower()
        if c and key not in seen:
            seen.add(key)
            out.append(c)
    return out


def download_fiber(icd_names: List[str], out_path: Path = FIBER_PATH,
                   logfn=print) -> Path:
    """Fiber pull dispatch — tries the fast bulk path first, falls back to
    the legacy per-ICD loop if anything goes wrong. Both produce the same
    tab\\tpenetration\\tlead_count\\texpected CSV at `out_path`.

    Bulk path (~10s total): one Crosstab download of the
    AUTOMATIONPULL-NICHURNVIEW custom view, which exposes per-owner Fixed
    aggregates (Office Lead Penetration / ICD Workable Fiber Lead Count /
    Fiber Sales). We parse the CSV, match each Sheet tab to an owner row
    by candidate name (same alias logic the legacy path used), and emit
    the same CSV.

    Legacy path (~25 min): one page.goto per ICD, scrape the Program
    Overview box, compute penetration from sales/leads. The reliable but
    slow fallback. Used to be the only path. Eve 2026-05-26 also hit a
    `new_page() Failed` crash at ICD 10 in this path — the bulk path
    eliminates the per-ICD loop entirely and dodges that failure mode."""
    try:
        return _download_fiber_bulk(icd_names, out_path, logfn=logfn)
    except Exception as e:
        logfn(f"OPT: Fiber bulk path failed ({type(e).__name__}: "
              f"{str(e)[:120]}) — falling back to per-ICD loop")
        return _download_fiber_legacy(icd_names, out_path, logfn=logfn)


def _download_fiber_bulk(icd_names: List[str], out_path: Path,
                         logfn=print) -> Path:
    """One Crosstab download → 1,800-ish per-(owner, zip) rows → group by
    owner → match Sheet tabs to owner rows by candidate name → emit the
    same CSV format as the legacy per-ICD path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        as_owner_map = {c["sheet_tab"]: c.get("as_owner", "")
                        for c in fill.load_mapping()["confirmed"]}
    except Exception:
        as_owner_map = {}
    try:
        from automations.focus_office_att import aliases as _al
        aliases_map = _al.load_aliases()
    except Exception:
        aliases_map = {}

    # Download the Crosstab to a tmp file. UTF-16-LE encoded, tab-delimited.
    tmp_path = out_path.parent / "opt_fiber_crosstab_raw.csv"
    from automations.shared.tableau_patchright import download_crosstab_patchright
    download_crosstab_patchright(FIBER_BULK_VIEW_URL, FIBER_BULK_CROSSTAB_SHEET,
                                 tmp_path, verbose=False)
    raw = tmp_path.read_bytes().decode("utf-16").replace("\r\n", "\n")
    lines = raw.split("\n")
    if len(lines) < 3:
        raise RuntimeError(f"crosstab too short ({len(lines)} lines)")
    header = lines[0].split("\t")
    # Locate columns by name — Tableau can reorder them when the workbook
    # is edited, so match by header rather than hardcoded index.
    def _col(needle: str) -> int:
        nl = needle.lower()
        for i, h in enumerate(header):
            if nl in h.lower():
                return i
        raise RuntimeError(f"crosstab missing column matching {needle!r}; "
                           f"have {header}")
    pen_i   = _col("office lead penetration")
    owner_i = _col("account_owner_name")
    leads_i = _col("icd workable fiber lead count")
    exp_i   = _col("fiber sales (fixed)")

    # First-row-per-owner is enough because columns pen/leads/exp are
    # "Fixed" calc — same value on every one of that owner's zip rows.
    by_owner: Dict[str, Tuple[str, str, str]] = {}
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) <= max(pen_i, owner_i, leads_i, exp_i):
            continue
        owner = cols[owner_i].strip()
        if not owner or owner.lower() in ("grand total", "total"):
            continue
        if owner in by_owner:
            continue
        by_owner[owner] = (
            cols[pen_i].strip(),
            cols[leads_i].strip().replace(",", ""),
            cols[exp_i].strip().replace(",", ""),
        )
    # Reindex by normalized name for matching.
    by_owner_norm: Dict[str, Tuple[str, str, str]] = {
        _norm(o): v for o, v in by_owner.items()
    }
    logfn(f"OPT: Fiber bulk — crosstab has {len(by_owner)} owners")

    # For each Sheet tab, walk candidate names to find a matching owner row.
    rows: List[Tuple[str, str, str, str]] = []
    matched = unmatched = 0
    for tab in icd_names:
        hit = None
        for cand in _fiber_name_candidates(tab, as_owner_map, aliases_map):
            hit = by_owner_norm.get(_norm(cand))
            if hit:
                break
        if hit:
            pen, leads, expected = hit
            rows.append((tab, pen, leads, expected))
            matched += 1
            logfn(f"OPT: Fiber {tab}: penetration={pen}, leads={leads}, "
                  f"expected={expected}")
        else:
            # The ICD has no row in Tableau's Fiber data — verified empty
            # for Khalil Mansour 2026-05-26 in both the crosstab and the
            # bare workbook scrape. Write "Not On Tableau" as the sentinel
            # so the user sees a clear "missing from source" signal across
            # all four Fiber cells (Megan 2026-05-26 — "0%" was confusing
            # because it conflicted with the real-zero case like Rashad
            # Reed who genuinely has 0.0% activity).
            rows.append((tab, FIBER_NOT_ON_TABLEAU, FIBER_NOT_ON_TABLEAU,
                         FIBER_NOT_ON_TABLEAU))
            unmatched += 1
            logfn(f"OPT: Fiber {tab}: no matching owner in crosstab "
                  f"({FIBER_NOT_ON_TABLEAU})")
    out_lines = (["tab\tpenetration\tlead_count\texpected"]
                 + ["\t".join(r) for r in rows])
    out_path.write_text("\n".join(out_lines), encoding="utf-8")
    logfn(f"OPT: Fiber bulk — matched {matched}/{len(rows)} tabs, "
          f"{unmatched} skipped → {out_path}")
    return out_path


def _download_fiber_legacy(icd_names: List[str], out_path: Path = FIBER_PATH,
                           logfn=print) -> Path:
    """Per-ICD Fiber pull: filter the Fiber view to each ICD's Owner Name,
    scrape that ICD's 'Program Overview' box (FIBER_OVERVIEW_XY), and record
    Penetration % + Total Leads + Expected Fiber Sales. One Tableau session,
    looped over the ICDs. Rows are keyed by the Sheet tab name."""
    from urllib.parse import quote
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        as_owner_map = {c["sheet_tab"]: c.get("as_owner", "")
                        for c in fill.load_mapping()["confirmed"]}
    except Exception:
        as_owner_map = {}
    try:
        from automations.focus_office_att import aliases as _al
        aliases_map = _al.load_aliases()
    except Exception:
        aliases_map = {}
    rows: List[Tuple[str, str, str, str]] = []
    # patchright session (self-logs in) instead of CDP/Report-Chrome. The heavy
    # Fiber viz still leaks tabs over many loads, so we open a fresh page from
    # the SAME authed context every 10 ICDs (ctx.new_page() — cookies carry the
    # login, no re-SSO needed).
    from automations.shared.tableau_patchright import tableau_session
    with tableau_session(verbose=False) as page:
        ctx = page.context
        try:
            n = len(icd_names)
            for i, tab in enumerate(icd_names, 1):
                if i > 1 and i % 10 == 1:
                    try:
                        page.close()
                    except Exception:
                        pass
                    # The Fiber viz leaks helper "hybrid-window" / vizql tabs
                    # that accumulate across page.goto's. Closing JUST our
                    # working page isn't enough — over time the context fills
                    # up and ctx.new_page() fails with "Failed to open a new
                    # tab" (Eve 2026-05-26, crashed at ICD #10/52). Close
                    # every leftover page in the context before requesting a
                    # new one so Chrome's per-context tab cap doesn't trip.
                    for _stale in list(ctx.pages):
                        try:
                            _stale.close()
                        except Exception:
                            pass
                    page = ctx.new_page()
                pen, leads, expected, ok, err, empty = "", None, None, False, "", False
                for cand in _fiber_name_candidates(tab, as_owner_map, aliases_map):
                    if ok:
                        break
                    url = f"{FIBER_VIEW_URL}?{quote('Owner Name')}={quote(cand)}"
                    for _ in range(3):   # retry transient Tableau flakes
                        try:
                            if page.is_closed():
                                page = ctx.new_page()
                            fields, recs = _scrape_one_view_data(
                                page, ctx, url, verbose=False,
                                activate_xy=FIBER_OVERVIEW_XY)
                        except Exception as e:
                            err = type(e).__name__
                            # "couldn't activate the worksheet" = the Fiber
                            # view rendered with no marks (i.e. this owner
                            # has no row in Tableau's Fiber data). Write
                            # the FIBER_NOT_ON_TABLEAU sentinel (Megan
                            # 2026-05-26) so the user sees "missing from
                            # source" across all four Fiber cells instead
                            # of zeros that look indistinguishable from a
                            # real-zero owner like Rashad Reed.
                            if "couldn't activate" in str(e):
                                pen = leads = expected = FIBER_NOT_ON_TABLEAU
                                ok = empty = True
                                break
                            if page.is_closed():
                                try:
                                    page = ctx.new_page()
                                except Exception:
                                    pass
                            continue
                        pen, leads, expected = _fiber_overview(fields, recs)
                        if pen or leads is not None:
                            ok = True
                        break
                rows.append((tab, pen,
                             "" if leads is None else str(leads),
                             "" if expected is None else str(expected)))
                if empty:
                    logfn(f"OPT: Fiber [{i}/{n}] {tab}: empty view -> "
                          f"penetration=0%, leads=0, expected=0")
                elif ok:
                    logfn(f"OPT: Fiber [{i}/{n}] {tab}: penetration={pen}, "
                          f"leads={leads}, expected={expected}")
                else:
                    logfn(f"OPT: Fiber [{i}/{n}] {tab}: FAILED "
                          f"({err or 'no data for this ICD'})")
        finally:
            try:
                page.close()
            except Exception:
                pass
    lines = (["tab\tpenetration\tlead_count\texpected"]
             + ["\t".join(r) for r in rows])
    out_path.write_text("\n".join(lines), encoding="utf-8")
    ok = sum(1 for _, pn, lc, _ex in rows if pn or lc)
    logfn(f"OPT: Fiber — pulled {ok}/{len(rows)} ICDs → {out_path}")
    return out_path


# ------------------------------------------------------------------- parse

def parse_icd_summary(path: Path) -> Tuple[Dict[str, dict], dict]:
    """Parse the UTF-16, tab-delimited crosstab.

    Returns (by_owner, national):
      by_owner  — {normalized owner name: {"owner": raw, "values": {norm header: cell}}}
      national  — {norm header: cell} from the 'Grand Total' row
    """
    raw = Path(path).read_text(encoding="utf-16")
    rows = [ln.split("\t") for ln in raw.splitlines() if ln.strip()]
    if not rows:
        raise RuntimeError("crosstab file is empty")
    headers = [_norm(h) for h in rows[0]]
    # The ICD-name column is usually col 0, but some views (Metrics) put it
    # later — find it by header instead of assuming.
    owner_col = next((i for i, h in enumerate(headers)
                      if "icd owner name" in h), 0)

    by_owner: Dict[str, dict] = {}
    national: dict = {}
    for r in rows[1:]:
        owner = (r[owner_col] if len(r) > owner_col else "").strip()
        if not owner:
            continue
        rec = {headers[i]: r[i].strip() for i in range(min(len(headers), len(r)))}
        if owner.lower() in ("grand total", "total"):
            national = rec
        else:
            by_owner[_norm(owner)] = {"owner": owner, "values": rec}
    return by_owner, national


def parse_personal_production(path: Path) -> Dict[str, dict]:
    """Parse the per-rep PRODUCT SALES crosstab into each rep's own weekly
    sales. Columns: Owner Name, Rep, Product Type, the 7 weekday columns,
    then a trailing 'Product Total' column.

    Returns {normalized rep name: {"owner": raw rep, "values": {PRODUCT TYPE:
    week total}}} — same shape as parse_icd_summary so _match_owner works."""
    raw = Path(path).read_text(encoding="utf-16")
    rows = [ln.split("\t") for ln in raw.splitlines() if ln.strip()]
    if not rows:
        return {}
    headers = [str(h).strip().lower() for h in rows[0]]
    # Sum the weekday columns ONLY — the crosstab ends with a 'Product Total'
    # column that already equals the week's sum, so including it would double
    # every count. Found by header so it survives a column-order change.
    day_cols = [i for i in range(3, len(headers)) if "total" not in headers[i]]
    out: Dict[str, dict] = {}
    for r in rows[1:]:
        if len(r) < 4:
            continue
        rep = (r[1] or "").strip()
        ptype = (r[2] or "").strip().upper()
        if not rep or rep.lower() == "total" or ptype.lower() in ("total", ""):
            continue
        week_total = 0
        for i in day_cols:
            n = _to_num(r[i]) if i < len(r) else None
            if n:
                week_total += int(n)
        if week_total:
            entry = out.setdefault(_norm(rep), {"owner": rep, "values": {}})
            entry["values"][ptype] = entry["values"].get(ptype, 0) + week_total
    return out


def _format_personal_production(products: Dict[str, int]) -> str:
    """Render a rep's product counts as e.g. '2 NI / 1 DTV / 3 NL'."""
    parts = [f"{products[ptype]} {label}"
             for ptype, label in PRODUCT_LABELS if products.get(ptype)]
    return " / ".join(parts)


def parse_churn(path: Path) -> Dict[str, dict]:
    """Parse the CHURN 'ICD Churn' crosstab. Each ICD spans several measure
    rows AND several colour blocks (Green/Red/Yellow) — each block fills only
    some of the 0-30 / 30 / 60 / 90 day columns. Keep only the 'Churn Rate
    (Unit vs Order)' rows and MERGE their non-empty cells, so an ICD ends up
    with all four churn values.

    Returns {normalized ICD name: {"owner": raw, "values": {norm header: cell}}}."""
    raw = Path(path).read_text(encoding="utf-16")
    rows = [ln.split("\t") for ln in raw.splitlines() if ln.strip()]
    if not rows:
        raise RuntimeError("churn crosstab file is empty")
    headers = [_norm(h) for h in rows[0]]
    owner_col = next((i for i, h in enumerate(headers)
                      if "icd owner name" in h), 0)
    out: Dict[str, dict] = {}
    for r in rows[1:]:
        if len(r) <= owner_col:
            continue
        owner = r[owner_col].strip()
        if not owner or owner.lower() in ("grand total", "total"):
            continue
        # Keep only churn-rate rows; merge their non-empty cells per ICD.
        if not any("churn rate" in _norm(c) for c in r):
            continue
        entry = out.setdefault(_norm(owner), {"owner": owner, "values": {}})
        for i in range(min(len(headers), len(r))):
            cell = r[i].strip()
            if cell:
                entry["values"][headers[i]] = cell
    return out


def parse_captains(paths: List[Path]) -> Dict[str, dict]:
    """Merge the per-team 'CB Appr + Churn' crosstabs into one ICD lookup —
    every team's ICDs in a single {norm name: {...}} dict."""
    merged: Dict[str, dict] = {}
    for p in paths:
        if not Path(p).exists():
            continue
        by_owner, _ = parse_icd_summary(p)
        merged.update(by_owner)
    return merged


def parse_program_summary(path: Path) -> Dict[str, dict]:
    """Sum the View Data window's 'Total $ to ICD' per ICD owner. A trailing
    ' LEDGER' on an owner name is a ledger / record-change line for that same
    ICD — it's folded into the ICD's total (and the suffix stripped so the
    name matches the tab). Returns {normalized owner: {"owner", "total"}}."""
    if not Path(path).exists():
        return {}
    rows = [ln.split("\t") for ln in
            Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not rows:
        return {}
    fields = [f.strip().lower() for f in rows[0]]
    owner_i = next((i for i, f in enumerate(fields) if "icd owner name" in f), 1)
    total_i = next((i for i, f in enumerate(fields) if "total $" in f),
                   len(fields) - 1)
    out: Dict[str, dict] = {}
    for r in rows[1:]:
        if len(r) <= max(owner_i, total_i):
            continue
        owner = re.sub(r"\s+LEDGER\s*$", "", r[owner_i].strip(), flags=re.I).strip()
        amt = _parse_money(r[total_i])
        if not owner or amt is None:
            continue
        e = out.setdefault(_norm(owner), {"owner": owner, "total": 0.0})
        e["total"] += amt
    return out


def parse_fiber(path: Path) -> Dict[str, dict]:
    """Read the per-ICD Fiber pull (tab-keyed). Returns {normalized tab name:
    {"owner", "penetration", "lead_count", "expected"}}. The 'expected' column
    is optional so older cached files (3 columns) still parse."""
    if not Path(path).exists():
        return {}
    rows = [ln.split("\t") for ln in
            Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    out: Dict[str, dict] = {}
    for r in rows[1:]:
        if len(r) < 3 or not r[0].strip():
            continue
        out[_norm(r[0])] = {"owner": r[0].strip(),
                            "penetration": r[1].strip(),
                            "lead_count": r[2].strip(),
                            "expected": r[3].strip() if len(r) > 3 else ""}
    return out


def _match_owner(tab_name: str, by_owner: dict, aliases_map: dict) -> Optional[dict]:
    """Find the crosstab row for a Sheet tab. Tries, in order: the tab name,
    its parenthetical (a tab named 'X (Y)' also tries Y and X), every alias
    for it, then a subset match (one name has an extra middle name, same
    surname). All comparisons ignore case, apostrophes, and extra spacing."""
    candidates = [tab_name]
    m = re.match(r"^(.*?)\s*\((.+?)\)\s*$", tab_name or "")
    if m:
        candidates += [m.group(1).strip(), m.group(2).strip()]
    norm_tab = _norm(tab_name)
    for canonical, aliases in (aliases_map or {}).items():
        group = [canonical] + list(aliases)
        if norm_tab in {_norm(g) for g in group}:
            candidates.extend(group)
    for cand in candidates:
        hit = by_owner.get(_norm(cand))
        if hit:
            return hit
    # Subset fallback: same surname (last word) AND one name's word set is a
    # subset of the other — catches a middle name present on only one side.
    tw = norm_tab.split()
    if len(tw) >= 2:
        for key, hit in by_owner.items():
            kw = key.split()
            if kw and kw[-1] == tw[-1] and (set(tw) <= set(kw) or set(kw) <= set(tw)):
                return hit
    return None


# -------------------------------------------------------------------- fill

def _is_opt_anchor(nv: str) -> bool:
    return nv == "opt" or "office performance tracker" in nv


# Column-B anchors that END the OPT block. Everything from the OPT header to
# one of these is one block — OPT + Office Metrics combined — because some
# tabs (Raf's) merge them under a single OPT header instead of two sections.
_OPT_BLOCK_END = {"we sunday", "wireless metrics", "extra data"}


def _opt_block_rows(col_b: List[str]) -> Dict[str, int]:
    """{normalized label: 1-indexed row} for the OPT block — the OPT section
    AND the Office Metrics section as one span. Found from the OPT anchor in
    column B to the next major section; never a hardcoded row number."""
    start = None
    for j, v in enumerate(col_b):
        if _is_opt_anchor(_norm(v)):
            start = j
            break
    if start is None:
        return {}
    out: Dict[str, int] = {}
    for j in range(start + 1, len(col_b)):
        nv = _norm(col_b[j])
        if not nv:
            continue
        if nv in _OPT_BLOCK_END or "office performance tracker" in nv:
            break
        out.setdefault(nv, j + 1)
    return out


# Column-B anchors that END the Wireless Metrics block.
_WIRELESS_BLOCK_END = {"we sunday", "extra data", "opt", "office metrics"}


def _wireless_block_rows(col_b: List[str]) -> Dict[str, int]:
    """{normalized label: 1-indexed row} for the Wireless Metrics section.
    Found from the 'Wireless Metrics' anchor in column B to the next major
    section; never a hardcoded row number. Separate from the OPT block — its
    churn labels (0-30 Day Churn ...) collide with the Office-Metrics ones."""
    start = None
    for j, v in enumerate(col_b):
        if _norm(v) == "wireless metrics":
            start = j
            break
    if start is None:
        return {}
    out: Dict[str, int] = {}
    for j in range(start + 1, len(col_b)):
        nv = _norm(col_b[j])
        if not nv:
            continue
        if nv in _WIRELESS_BLOCK_END or "office performance tracker" in nv:
            break
        out.setdefault(nv, j + 1)
    return out


def fill_opt_for_tab(
    sh: gspread.Spreadsheet, tab_name: str,
    att_by_owner: dict, att_national: dict,
    int_by_owner: dict, int_national: dict,
    metrics_by_owner: dict, churn_by_owner: dict, personal_prod: dict,
    wireless_metrics_by_owner: dict, wireless_churn_by_owner: dict,
    captains_by_owner: dict, program_summary: dict, fiber_by_owner: dict,
    aliases_map: dict, week_sunday: dt.date, dry_run: bool,
    fill_empty_only: bool = False, dd_roster: Optional[dict] = None,
) -> List[str]:
    """Write the OPT + Office-Metrics values for one ICD tab from the ATT and
    INT crosstabs. Returns log lines. Only writes mapped cells — never clears.
    fill_empty_only=True skips any cell that already has a value (used to fill
    gaps from a previously-failed source without overwriting entered data)."""
    try:
        ws = fill._retry(sh.worksheet, tab_name)
    except Exception as e:
        return [f"[SKIP] {tab_name}: tab not found ({e})"]

    att_row = _match_owner(tab_name, att_by_owner, aliases_map)
    int_row = _match_owner(tab_name, int_by_owner, aliases_map)
    metrics_row = _match_owner(tab_name, metrics_by_owner, aliases_map)
    if not att_row and not int_row and not metrics_row:
        return [f"[SKIP] {tab_name}: no crosstab row (ATT / INT / Metrics)"]

    grid = fill._retry(ws.get_all_values)
    sunday_to_col = fill.find_sunday_columns(grid, header_row_idx=0)
    col = sunday_to_col.get(week_sunday)
    if not col:
        return [f"[SKIP] {tab_name}: no column for week {week_sunday.isoformat()}"]

    col_b = [r[1] if len(r) > 1 else "" for r in grid]
    # OPT + Office Metrics as one label map — some tabs (Raf's) merge them
    # under a single OPT header instead of two separate sections.
    opt_rows = om_rows = _opt_block_rows(col_b)
    if not opt_rows:
        return [f"[SKIP] {tab_name}: no OPT section anchor found in column B"]

    updates: List[Tuple[str, object]] = []
    missing: List[str] = []
    red_cells: List[str] = []   # cells whose value looks weird -> red font (fill-but-flag)

    def _queue(label_rows: Dict[str, int], sheet_label: str, value) -> bool:
        for lbl in [sheet_label] + ALT_LABELS.get(sheet_label, []):
            r = label_rows.get(_norm(lbl))
            if r:
                a1 = gspread.utils.rowcol_to_a1(r, col)
                if fill_empty_only:
                    cur = (grid[r - 1][col - 1]
                           if r - 1 < len(grid) and col - 1 < len(grid[r - 1])
                           else "")
                    if str(cur).strip() != "":
                        return True   # already filled — don't overwrite
                updates.append((a1, value))
                # Universal fill-but-flag: any percentage that lands outside
                # 0–100% (e.g. a churn or penetration >100%) is written but
                # red-flagged so a human eyeballs it (Megan 2026-05-25).
                if _sheet_flags.looks_weird_pct(value):
                    red_cells.append(a1)
                return True
        missing.append(sheet_label)
        return False

    # --- ATT crosstab ---
    if att_row:
        av = att_row["values"]
        for sheet_label, csv_col in OPT_SCRAPED.items():
            cell = av.get(_norm(csv_col), "")
            if str(cell).strip() != "":
                _queue(opt_rows, sheet_label, cell)
            elif sheet_label == "% of Wireless Rep Count":
                # Blank in the crosstab = 0% — write it rather than leave the
                # cell empty (Megan 2026-05-25: "enter a 0% if it's 0").
                _queue(opt_rows, sheet_label, "0%")
        # computed: Total Apps + AVG Apps (component rows found by label)
        parts = [_to_num(av.get(_norm(OPT_SCRAPED[c]), ""))
                 for c in TOTAL_APPS_COMPONENTS]
        total_apps = None
        if all(p is not None for p in parts):
            total_apps = int(sum(parts))
            _queue(opt_rows, "Total Apps", total_apps)
        headcount = _to_num(av.get(_norm(OPT_SCRAPED["Active Headcount on Tableau"]), ""))
        if total_apps is not None and headcount:
            _queue(opt_rows, "AVG Apps Per Active Headcount",
                   round(total_apps / headcount, 1))
        # Office Metrics — 1 GIG%
        for sheet_label, csv_col in METRIC_GOALS_SCRAPED.items():
            cell = av.get(_norm(csv_col), "")
            if str(cell).strip() != "":
                _queue(om_rows, sheet_label, cell)
    # ATT national (same value on every tab)
    for sheet_label, csv_col in OPT_NATIONAL.items():
        cell = att_national.get(_norm(csv_col), "")
        if str(cell).strip() != "":
            _queue(opt_rows, sheet_label, cell)

    # --- INT crosstab ---
    if int_row:
        iv = int_row["values"]
        for sheet_label, csv_col in INT_SCRAPED.items():
            cell = iv.get(_norm(csv_col), "")
            if str(cell).strip() != "":
                _queue(opt_rows, sheet_label, cell)
    for sheet_label, csv_col in INT_NATIONAL.items():
        cell = int_national.get(_norm(csv_col), "")
        if str(cell).strip() != "":
            _queue(opt_rows, sheet_label, cell)

    # --- Metrics view (Office Metrics section) ---
    if metrics_row:
        mv = metrics_row["values"]
        for sheet_label, csv_col in METRICS_SCRAPED.items():
            cell = mv.get(_norm(csv_col), "")
            if str(cell).strip() != "":
                _queue(om_rows, sheet_label, cell)

    # --- CHURN view (Office Metrics section) ---
    churn_row = _match_owner(tab_name, churn_by_owner, aliases_map)
    # Fill -% (USER_ENTERED -> literal text) for any churn metric the owner has
    # no value for — whether the owner didn't match the Churn crosstab at all
    # (cv = {}) or matched but that cell came back blank. Mirrors int_wow's '-%'
    # no-data marker so a gap reads as "reported, no data", not "untouched".
    cv = churn_row["values"] if churn_row else {}
    for sheet_label, csv_col in CHURN_SCRAPED.items():
        cell = cv.get(_norm(csv_col), "")
        if str(cell).strip() != "":
            _queue(om_rows, sheet_label, cell)
        elif churn_by_owner:
            # -% only when the Churn source actually loaded (dict non-empty).
            # A failed download leaves churn_by_owner={} -> write nothing, so
            # the cell stays as-is instead of being stamped over with -%.
            _queue(om_rows, sheet_label, "-%")

    # --- Captain's Bonus (Office Metrics section) ---
    cap_row = _match_owner(tab_name, captains_by_owner, aliases_map)
    if cap_row:
        cvv = cap_row["values"]
        for sheet_label, csv_col in CAPTAINS_SCRAPED.items():
            cell = cvv.get(_norm(csv_col), "")
            if str(cell).strip() != "":
                _queue(om_rows, sheet_label, cell)
        # 30-60 Day Cancel Rate = 100% − Activation/Approval %.
        appr = _to_num(cvv.get(_norm("Rolling 4 Weeks"), ""))
        if appr is not None:
            _queue(om_rows, "30-60 Day Cancel Rate", f"{round(100 - appr, 1)}%")

    # --- Program Summary (Direct Deposit) ---
    # Amount if the ICD has DD this week; else "No DD" (known to the DD view but
    # none this week) or "Not in Tableau" (never in it). Current-week cell only;
    # None = leave the cell untouched (e.g. DD source didn't load). Megan's rule
    # 2026-06-04.
    dd_val = _dd_value(tab_name, program_summary, dd_roster, aliases_map)
    if dd_val is not None:
        _queue(om_rows, "Direct Deposit", dd_val)

    # --- Fiber Lead (Office Metrics section) — keyed by tab name ---
    # All from the Fiber view's Program Overview box: Penetration Rate, Total
    # Leads, Expected Fiber Sales (120 days/17wks), and Weekly = Expected / 17.
    fiber_row = fiber_by_owner.get(_norm(tab_name))
    if fiber_row:
        pen = fiber_row.get("penetration") or ""
        # "Not On Tableau" sentinel: write the message into all four Fiber
        # cells so the user sees a clear "missing from data source" signal
        # everywhere (instead of mixed updated/stale, or zeros that look
        # like real-zero activity). Megan 2026-05-26 — distinguishes
        # genuinely-missing owners (Khalil Mansour) from real-zero ones
        # (Rashad Reed: 0.0% / 52,889 / 0 — has data, just no sales).
        if pen == FIBER_NOT_ON_TABLEAU:
            for lbl in ("Penetration Rate", "Total Leads",
                        "Expected Fiber Sales (120 days, 17wks)",
                        "Expected Fiber Sales Weekly"):
                _queue(om_rows, lbl, FIBER_NOT_ON_TABLEAU)
        else:
            if pen:
                _queue(om_rows, "Penetration Rate", pen)
            lead_n = _to_num(fiber_row.get("lead_count", ""))
            if lead_n is not None:
                _queue(om_rows, "Total Leads", int(lead_n))
            exp_n = _to_num(fiber_row.get("expected", ""))
            if exp_n is not None:
                _queue(om_rows, "Expected Fiber Sales (120 days, 17wks)", int(exp_n))
                _queue(om_rows, "Expected Fiber Sales Weekly", round(exp_n / 17))
            # Fill-but-flag (Megan 2026-05-25): an impossible penetration
            # (>100% = more sales than leads, e.g. a brand-new ICD whose
            # Fiber isn't set up) is still written, but the whole Fiber
            # block goes RED so a human checks.
            if _sheet_flags.looks_weird_pct(pen):
                for lbl in ("Penetration Rate",
                            "Expected Fiber Sales (120 days, 17wks)",
                            "Expected Fiber Sales Weekly"):
                    r = om_rows.get(_norm(lbl))
                    if r:
                        red_cells.append(gspread.utils.rowcol_to_a1(r, col))

    # --- Personal Production (the ICD's own sales as a rep) ---
    # Always written — an ICD with no personal sales gets a literal 0.
    pp_row = _match_owner(tab_name, personal_prod, aliases_map)
    text = _format_personal_production(pp_row["values"]) if pp_row else ""
    _queue(opt_rows, "Personal Production", text or "0")

    # --- Wireless Metrics section (its own anchor; not all tabs have it) ---
    wireless_rows = _wireless_block_rows(col_b)
    wm_row = wc_row = None
    if wireless_rows:
        wm_row = _match_owner(tab_name, wireless_metrics_by_owner, aliases_map)
        if wm_row:
            wv = wm_row["values"]
            for sheet_label, csv_col in WIRELESS_SCRAPED.items():
                cell = wv.get(_norm(csv_col), "")
                if str(cell).strip() != "":
                    _queue(wireless_rows, sheet_label, cell)
        wc_row = _match_owner(tab_name, wireless_churn_by_owner, aliases_map)
        # Same -% no-data fill as the Office-Metrics churn block above.
        wcv = wc_row["values"] if wc_row else {}
        for sheet_label, csv_col in WIRELESS_CHURN_SCRAPED.items():
            cell = wcv.get(_norm(csv_col), "")
            if str(cell).strip() != "":
                _queue(wireless_rows, sheet_label, cell)
            elif wireless_churn_by_owner:
                # -% only when the Wireless Churn source loaded (dict non-empty).
                _queue(wireless_rows, sheet_label, "-%")

    # Drop rows that are legitimately absent on this tab — not real gaps.
    expected_gone = _EXPECTED_MISSING.get(_norm(tab_name), set())
    if expected_gone:
        missing = [m for m in missing if _norm(m) not in expected_gone]

    if not updates:
        return [f"[SKIP] {tab_name}: nothing to write"]

    if dry_run:
        log = [f"[DRY-RUN] {tab_name} (col {col}, week {week_sunday}): "
               f"would write {len(updates)} cells"]
        for a1, v in updates:
            log.append(f"    {a1} <- {v}")
    else:
        fill._retry(ws.batch_update, [
            {"range": a1, "values": [[v]]} for a1, v in updates
        ], value_input_option="USER_ENTERED")
        log = [f"[OK] {tab_name}: wrote {len(updates)} cells (col {col})"]
        # Fill-but-flag: red-font any value that looked weird (e.g. >100%
        # penetration). Done after the value write so the data lands regardless.
        if red_cells:
            _sheet_flags.apply_red_font(ws, red_cells, retry=fill._retry)
            log.append(f"    [flag] {len(red_cells)} weird cell(s) marked red")
    if missing:
        log.append(f"    [note] labels not found on tab: {', '.join(missing)}")
    # Data-gap line — which Tableau views this ICD wasn't found in, and which
    # rows aren't on the tab. Collected into the end-of-run rundown.
    gap_views = [v for row, v in [(att_row, "ATT"), (int_row, "INT"),
                 (metrics_row, "Metrics"), (churn_row, "Churn"),
                 (cap_row, "Captain's Bonus")] if not row]
    if wireless_rows:
        if not wm_row:
            gap_views.append("Wireless Metrics")
        if not wc_row:
            gap_views.append("Wireless Churn")
    if gap_views or missing:
        bits = []
        if gap_views:
            bits.append("not in Tableau view(s): " + ", ".join(gap_views))
        if missing:
            bits.append("row(s) not on tab: " + ", ".join(missing))
        log.append(f"[gap] {tab_name} — " + "; ".join(bits))
    return log


def _week_url(base_url: str, we_sunday: dt.date) -> str:
    """Append Tableau's 'Sale Date Week Ending (mon-sun)' filter param so the
    view loads the target week."""
    from urllib.parse import quote
    return (f"{base_url}?{quote('Sale Date Week Ending (mon-sun)')}"
            f"={quote(str(we_sunday))}")


def _crosstab_grand_total(path: Path) -> str:
    """Best-effort 'Sales Total' (last column) from a Product Sales crosstab,
    for an at-a-glance audit log. Returns '' if not parseable."""
    try:
        txt = path.read_text(encoding="utf-16")
    except Exception:
        try:
            txt = path.read_text(encoding="utf-8", errors="replace").replace("\x00", "")
        except Exception:
            return ""
    for ln in txt.splitlines():
        cells = ln.split("\t")
        if cells and cells[0].strip().lower() == "sales total":
            return cells[-1].strip()
    return ""


def _most_recent_sunday(today: Optional[dt.date] = None) -> dt.date:
    """The most recent Sunday on or before today — the week that just ended."""
    today = today or dt.date.today()
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


def run_opt_phase(we_sunday: Optional[dt.date] = None, only: Optional[str] = None,
                  dry_run: bool = False, skip_download: bool = False,
                  fill_empty_only: bool = False, skip_breakdowns: bool = False,
                  logfn=print) -> dict:
    """Download the ATT + INT ICD Summary crosstabs from Tableau and fill the
    OPT section on the target ICD tabs. Entry point the weekly report's run.py
    calls. Returns {"filled": [...], "skipped": [...]}."""
    if we_sunday is None:
        we_sunday = _most_recent_sunday()
    # Per-source download success, so one bad Tableau sheet (renamed/missing)
    # skips ONLY its metric instead of aborting the whole OPT phase. Empty for
    # --skip-download (the files were already verified present below).
    dl_ok: Dict[str, bool] = {}
    dl_gaps: List[str] = []
    # Captain's Bonus team sheets — auto-discovered inside the download session
    # below; defaults to the static fallback so --skip-download (which never
    # opens a session) still parses whatever per-team CSVs are on disk.
    captains_sheets = list(CAPTAINS_SHEETS)
    if skip_download:
        for pth, lbl in [(ATT_PATH, "ATT"), (INT_PATH, "INT"),
                         (PRODUCT_SALES_PATH, "Product Sales"),
                         (METRICS_PATH, "Metrics"), (CHURN_PATH, "Churn"),
                         (WIRELESS_METRICS_PATH, "Wireless Metrics"),
                         (WIRELESS_CHURN_PATH, "Wireless Churn"),
                         (PROGRAM_SUMMARY_PATH, "Program Summary")]:
            if not pth.exists():
                raise RuntimeError(f"--skip-download but no {lbl} crosstab at {pth}")
        logfn("OPT: reusing previously-downloaded crosstabs")
    else:
        # ONE patchright login powers every crosstab + the Program Summary
        # view-data scrape (instead of 8 separate logins). It self-authenticates
        # via the persistent profile — no Report Chrome / manual Tableau tab, the
        # same proven path the Alphalete Org OPT uses. Each source is ISOLATED:
        # if one fails (e.g. a renamed sheet), only that metric is skipped (its
        # cells left as-is) + flagged; the rest still fill. (Before 2026-05-25 a
        # single bad sheet aborted the entire OPT phase.)
        from automations.shared.tableau_patchright import tableau_session

        def _dl(key: str, label: str, fn) -> None:
            try:
                fn()
                dl_ok[key] = True
            except Exception as e:
                dl_ok[key] = False
                dl_gaps.append(label)
                logfn(f"OPT: ⚠️ {label} download FAILED — skipping that metric "
                      f"(cells left as-is); the rest continue. "
                      f"({type(e).__name__}: {str(e)[:140]})")

        with tableau_session(verbose=False) as _pg:
            # On MONDAYS Tableau hasn't rolled the just-closed week into its
            # "last week" / week-ending sources yet, so the normal (LW)/pinned
            # path silently serves the PRIOR week -> the 5/31->6/7 duplication
            # (Eve 2026-06-08). The bare-view CURRENT-week sheets DO carry the
            # live week (verified reachable 2026-06-08; the 2026-06-02 chart
            # clutter only blocked the *week-filtered* URL, not the bare view).
            # So on Mondays pull This Week (may be partial); Tue-Sun keep the
            # finished-week behavior. Anchored to Central (Raf's TX offices).
            _is_monday = dt.datetime.now(CENTRAL).weekday() == 0

            # ATT / INT: bare dashboard, CURRENT sheet on Mondays else the (LW)
            # "last week" sheet. (LW) IS the most recent COMPLETED week and is
            # never blank mid-week; it can't serve a backfill of an OLDER week,
            # so a backfill still skips ATT/INT rather than write the wrong week.
            if we_sunday == _most_recent_sunday():
                _att_sheet = ATT_SHEET if _is_monday else ATT_SHEET_LW
                _int_sheet = INT_SHEET if _is_monday else INT_SHEET_LW
                logfn("OPT: ATT/INT source -- "
                      + ("THIS WEEK (bare current sheet, Monday)" if _is_monday
                         else "(LW) last completed week"))
                _dl("att", "ATT", lambda: download_crosstab(
                    ATT_VIEW_URL, _att_sheet, ATT_PATH, verbose=False, page=_pg))
                _dl("int", "INT", lambda: download_crosstab(
                    INT_VIEW_URL, _int_sheet, INT_PATH, verbose=False, page=_pg))
            else:
                logfn(f"OPT: ⚠️ ATT/INT skipped — the bare-view (LW) sheet only "
                      f"serves the most recent completed week; {we_sunday} is a "
                      f"backfill, so those cells are left as-is.")
                dl_ok["att"] = dl_ok["int"] = False
                dl_gaps.extend(["ATT", "INT"])
            # Product Sales: ALWAYS pin to the target week-ending. The per-rep
            # box + breakdowns want the latest COMPLETED week (WE 6/7 -> Cody
            # Cannon = 99, verified 2026-06-08); the bare "This Week" view returns
            # a different (wrong) week. Unlike ATT/INT ((LW) sheets) and Metrics,
            # this source is week-pinned, so a stale Monday-AM pull self-corrects
            # once Tableau has loaded the week -- just re-run later that day.
            logfn(f"OPT: Product Sales source -- pinned week-ending {we_sunday.isoformat()}")
            _dl("product", "Product Sales", lambda: download_crosstab(
                _week_url(PRODUCT_SALES_VIEW_URL, we_sunday),
                PRODUCT_SALES_SHEET, PRODUCT_SALES_PATH, verbose=False, page=_pg))
            _ptot = _crosstab_grand_total(PRODUCT_SALES_PATH)
            if _ptot:
                logfn(f"OPT: Product Sales grand total = {_ptot}")
            _metrics_url = (METRICS_VIEW_URL if _is_monday
                            else _week_url(METRICS_VIEW_URL, we_sunday))
            logfn("OPT: Metrics source -- "
                  + ("THIS WEEK (bare view, Monday)" if _is_monday
                     else f"pinned week-ending {we_sunday.isoformat()}"))
            _dl("metrics", "Metrics", lambda: download_crosstab(
                _metrics_url, METRICS_SHEET, METRICS_PATH, verbose=False, page=_pg))
            _dl("churn", "Churn", lambda: download_crosstab(
                CHURN_VIEW_URL, CHURN_SHEET, CHURN_PATH, verbose=False, page=_pg))
            _dl("wmetrics", "Wireless Metrics", lambda: download_crosstab(
                WIRELESS_METRICS_VIEW_URL, WIRELESS_METRICS_SHEET,
                WIRELESS_METRICS_PATH, verbose=False, page=_pg))
            _dl("wchurn", "Wireless Churn", lambda: download_crosstab(
                WIRELESS_CHURN_VIEW_URL, WIRELESS_CHURN_SHEET,
                WIRELESS_CHURN_PATH, verbose=False, page=_pg))
            # Discover the live team sheets first so a captainship added/removed
            # in Tableau is picked up without a code change (falls back to the
            # static list if the dialog can't be read).
            captains_sheets = discover_captains_sheets(_pg, logfn)
            _dl("captains", "Captain's Bonus", lambda: [download_crosstab(
                CAPTAINS_VIEW_URL, sheet, _captains_path(sheet),
                verbose=False, page=_pg) for sheet in captains_sheets])
            _dl("program", "Program Summary",
                lambda: download_program_summary(verbose=False, page=_pg,
                                                 we_sunday=we_sunday))
        _n_ok = sum(1 for v in dl_ok.values() if v)
        logfn(f"OPT: downloaded {_n_ok}/{len(dl_ok)} source(s)"
              + (f" — FAILED: {dl_gaps}" if dl_gaps else ""))

    # Parse each source only if it downloaded OK this run (or on --skip-download,
    # where dl_ok is empty so .get(..., True) lets every parse proceed). A failed
    # source stays empty → its cells are left untouched, never overwritten with
    # stale data.
    att_by_owner, att_national = (parse_icd_summary(ATT_PATH)
                                  if dl_ok.get("att", True) else ({}, {}))
    int_by_owner, int_national = (parse_icd_summary(INT_PATH)
                                  if dl_ok.get("int", True) else ({}, {}))
    personal_prod = (parse_personal_production(PRODUCT_SALES_PATH)
                     if dl_ok.get("product", True) else {})
    metrics_by_owner = (parse_icd_summary(METRICS_PATH)[0]
                        if dl_ok.get("metrics", True) else {})
    churn_by_owner = (parse_churn(CHURN_PATH)
                      if dl_ok.get("churn", True) else {})
    wireless_metrics_by_owner = (parse_icd_summary(WIRELESS_METRICS_PATH)[0]
                                 if dl_ok.get("wmetrics", True) else {})
    wireless_churn_by_owner = (parse_churn(WIRELESS_CHURN_PATH)
                               if dl_ok.get("wchurn", True) else {})
    captains_by_owner = (parse_captains([_captains_path(s) for s in captains_sheets])
                         if dl_ok.get("captains", True) else {})
    program_summary = (parse_program_summary(PROGRAM_SUMMARY_PATH)
                       if dl_ok.get("program", True) else {})
    # DD roster: load, fold in this week's DD-view owners (persisted), and pass
    # to the fill so non-matched tabs get "No DD" (known to the view) vs "Not in
    # Tableau" (never in it). Only when DD actually loaded this run.
    dd_roster = load_dd_roster()
    if program_summary:
        dd_roster = update_dd_roster(dd_roster, program_summary)
        logfn(f"OPT: DD roster now {len(dd_roster)} owner(s)")
    logfn(f"OPT: parsed {len(att_by_owner)} ATT, {len(int_by_owner)} INT, "
          f"{len(metrics_by_owner)} Metrics, {len(churn_by_owner)} Churn, "
          f"{len(wireless_metrics_by_owner)} Wireless Metrics, "
          f"{len(wireless_churn_by_owner)} Wireless Churn, "
          f"{len(captains_by_owner)} Captain's Bonus, "
          f"{len(program_summary)} Program Summary, "
          f"{len(personal_prod)} reps for Personal Production"
          + ("" if att_national and int_national
             else " — WARNING: a national total row is missing"))

    try:
        from automations.focus_office_att import aliases as _al
        aliases_map = _al.load_aliases()
    except Exception:
        aliases_map = {}

    sh = fill.open_sheet()
    mapping = fill.load_mapping()
    for tab in fill.prune_deleted_tabs(sh, mapping, dry_run=dry_run):
        logfn(f"OPT: pruned deleted tab '{tab}' — no longer in the Sheet")
    targets = [only] if only else [c["sheet_tab"]
                                   for c in mapping["confirmed"]]
    # Fiber Lead — per-ICD pull (slow, one View Data scrape per ICD); skipped
    # on --skip-download, which reuses the last opt_fiber.csv. parse_fiber
    # returns {} when there's no file, so Fiber just doesn't fill.
    if not skip_download:
        # Non-fatal: the per-ICD Fiber pull is the slowest/flakiest step. If it
        # fails, keep going — the main OPT metrics are already downloaded above,
        # and parse_fiber just falls back to the prior Fiber file (or no fill).
        try:
            download_fiber(targets, logfn=logfn)
        except Exception as e:
            logfn(f"OPT: Fiber pull failed (non-fatal, prior Fiber data kept): "
                  f"{type(e).__name__}: {str(e)[:160]}")
    fiber_by_owner = parse_fiber(FIBER_PATH)
    if fiber_by_owner:
        logfn(f"OPT: parsed {len(fiber_by_owner)} Fiber Lead")
    filled: List[str] = []
    skipped: List[str] = []
    all_gaps: List[str] = []
    if dl_gaps:
        # Surface download failures at the top of the gap report — these affect
        # the metric on EVERY tab, not one tab's data.
        all_gaps.append("[download] Tableau source(s) that failed to download "
                        "(that metric left as-is on all tabs): " + ", ".join(dl_gaps))
    for tab_name in targets:
        lines = fill_opt_for_tab(sh, tab_name, att_by_owner, att_national,
                                 int_by_owner, int_national, metrics_by_owner,
                                 churn_by_owner, personal_prod,
                                 wireless_metrics_by_owner,
                                 wireless_churn_by_owner, captains_by_owner,
                                 program_summary, fiber_by_owner,
                                 aliases_map, we_sunday, dry_run,
                                 fill_empty_only=fill_empty_only,
                                 dd_roster=dd_roster)
        for ln in lines:
            logfn("OPT: " + ln)
            if ln.startswith("[SKIP]") or ln.startswith("[gap]"):
                all_gaps.append(ln)
        if any(ln.startswith("[OK]") or ln.startswith("[DRY-RUN]") for ln in lines):
            filled.append(tab_name)
        else:
            skipped.append(tab_name)
    if all_gaps:
        logfn("")
        logfn("===== DATA GAPS — what couldn't be filled (chase access / fix the tab) =====")
        for g in all_gaps:
            logfn("  " + g)

    # ----- Production Breakdown by Rep (combined NI+WIRELESS chart) -----
    # Uses the PRODUCT SALES SUMMARY crosstab we already downloaded.
    if not dry_run and not skip_breakdowns:
        try:
            from automations.production_breakdown.run import run_production_breakdown
            logfn("")
            logfn("===== Production Breakdown =====")
            run_production_breakdown(PRODUCT_SALES_PATH, logfn=logfn)
        except Exception as e:
            logfn(f"OPT: Production Breakdown failed: {type(e).__name__}: {e}")

    # ----- Team Breakdowns ('Next Promotion' sections) ------------------
    if not dry_run and not skip_breakdowns:
        try:
            from automations.team_breakdowns.run import run_team_breakdowns
            logfn("")
            logfn("===== Team Breakdowns (Next Promotion) =====")
            run_team_breakdowns(PRODUCT_SALES_PATH, logfn=logfn)
        except Exception as e:
            logfn(f"OPT: Team Breakdowns failed: {type(e).__name__}: {e}")

    return {"filled": filled, "skipped": skipped, "gaps": all_gaps}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Only this ICD tab (by tab name).")
    ap.add_argument("--week", help="WE Sunday YYYY-MM-DD. Default: most recent Sunday.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't write to the Sheet — just print what would change.")
    ap.add_argument("--skip-download", action="store_true",
                    help="Reuse the last downloaded crosstabs instead of re-pulling.")
    ap.add_argument("--fill-empty-only", action="store_true",
                    help="Only fill cells that are currently EMPTY — never "
                         "overwrite a value already in the Sheet. Use to fill "
                         "gaps from a previously-failed source.")
    ap.add_argument("--skip-breakdowns", action="store_true",
                    help="Skip the Production + Team breakdown steps (when "
                         "they already ran fine and only metrics need filling).")
    args = ap.parse_args()

    week = dt.date.fromisoformat(args.week) if args.week else _most_recent_sunday()
    print(f"OPT phase — target week (WE Sunday): {week.isoformat()}  dry_run={args.dry_run}")
    try:
        result = run_opt_phase(week, only=args.only, dry_run=args.dry_run,
                               skip_download=args.skip_download,
                               fill_empty_only=args.fill_empty_only,
                               skip_breakdowns=args.skip_breakdowns)
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        return 1
    print(f"done — {len(result['filled'])} filled, {len(result['skipped'])} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
