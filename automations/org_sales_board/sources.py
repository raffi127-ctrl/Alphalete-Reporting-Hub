"""Source registry for every Alphalete ORG Sales Board daily section.

Single source of truth for WHERE each section's numbers come from and HOW
to pull them. The fill side (fill_section.py) is source-agnostic — it just
needs a {owner: {metric: {date: value}}} dict — so onboarding a section =
one entry here + a small pull adapter that returns that shape.

Pull cost drives the run order ([[feedback_report_runtime]]):
  • HTTP  — Tableau's .csv endpoint, ~1-2s/pull, honors date URL params.
  • XTAB  — Crosstab/View-Data UI via patchright, ~60-90s/pull, needs a
            live browser session (reused across pulls).
  • MANUAL — hand-keyed (screenshot) or emailed PDF; no Tableau pull.

⚠ Column shapes for the XTAB/purpose-built views still need a one-time
live confirm (only SARA/Retail NL is column-verified so far — it's the
template). View URLs + filters below are authoritative from the recipe.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

# Pull methods. The purpose-built Org-board views are Tableau CUSTOM (saved)
# views — the .csv endpoint can't address them by name (404), so they're
# pulled by navigating patchright to the full custom-view URL and scraping
# Download → Data (View Data). Confirmed for Retail NL 2026-05-31.
SCRAPE = "scrape"    # scrape_view_data_patchright(full custom-view URL)
XTAB = "crosstab"    # download_crosstab_patchright (named worksheet)
MANUAL = "manual"    # hand-keyed screenshot / emailed PDF

# Date modes
RELATIVE = "relative_this_week"    # view is pinned to This Week; nothing to set
WEEK_ENDING = "week_ending_param"  # view exposes a Week Ending dropdown
MANUAL_DATE = "manual"


@dataclass(frozen=True)
class Source:
    label: str            # col-A header of the daily section (fill anchor)
    metric: str           # the per-day metric key the parser emits
    method: str           # HTTP | XTAB | MANUAL
    date_mode: str
    workbook: str = ""    # Tableau workbook slug
    view: str = ""        # Tableau view slug (named view)
    worksheet: str = ""   # crosstab worksheet name (XTAB only)
    shared_key: str = ""  # sections sharing ONE pull have the same key
    column_verified: bool = False   # per-day CSV columns confirmed live?
    notes: str = ""

    @property
    def is_manual(self) -> bool:
        return self.method == MANUAL


# One SARA pull feeds Retail NL + Retail Internet (shared_key 'sara_retail').
DAILY_SOURCES: List[Source] = [
    Source(
        label="Retail NL", metric="Wireless Lines",
        method=SCRAPE, date_mode=RELATIVE,
        workbook="DropshipV_2", view="RetailNLOrgSalesBoard",
        shared_key="sara_retail", column_verified=True,
        notes="VERIFIED live 2026-05-31. Scrape View Data; cols ICD Owner "
              "Name|Measure Names|Order Date|Measure Values. Wireless Lines "
              "metric. View is relative to this week."),
    Source(
        label="Retail Internet", metric="Internet",
        method=SCRAPE, date_mode=RELATIVE,
        workbook="DropshipV_2", view="RetailNLOrgSalesBoard",
        shared_key="sara_retail", column_verified=True,
        notes="Same SARA scrape as Retail NL; read the Internet measure."),
    Source(
        label="ATT Fiber Team", metric="Total",
        method=SCRAPE, date_mode=WEEK_ENDING,
        workbook="ATTTRACKER2_1-D2D", view="FiberTeamnovoice",
        shared_key="fiber",
        notes="Per-ICD Total/day = AIR+New Internet+Upgrade Internet+Video+"
              "Wireless (Voice excluded). Custom view — scrape View Data; "
              "confirm per-day columns live."),
    Source(
        label="ATT NDS Team", metric="Wireless",
        method=SCRAPE, date_mode=RELATIVE,
        workbook="NDS-SNRES-ATT-OOFWorkbook", view="Wirelessthisweek",
        shared_key="nds",
        notes="Per-ICD Wireless Total/weekday. Custom view — scrape View "
              "Data; confirm per-day columns live."),
    Source(
        label="B2B", metric="count",
        method=SCRAPE, date_mode=RELATIVE,
        workbook="ATTTRACKER-B2B", view="LuissCaptainship",
        shared_key="b2b",
        notes="Per-ICD count/weekday. Excludes Wireless Tablets/Wearables/"
              "Upgrades. Custom view — scrape; confirm columns live."),
    Source(
        label="BOX", metric="count",
        method=SCRAPE, date_mode=RELATIVE,
        workbook="B2BBOXEnergy", view="B2BBOXEnergyDailyTracker",
        shared_key="box",
        notes="Per-ICD count/weekday (ICD Owner & Office x day -> Total "
              "general). Owner names carry '|company, Inc.|' suffix -> strip+"
              "alias. Custom view — scrape; confirm columns live."),
    Source(
        label="Retail JE", metric="Closed Won",
        method=MANUAL, date_mode=MANUAL_DATE, column_verified=True,
        notes="Hand-keyed from screenshot ('Closed Won' per Regional Office). "
              "Not pullable. Rollover must still freeze its weekly total."),
    Source(
        label="Frontier", metric="sales",
        method=MANUAL, date_mode=MANUAL_DATE, column_verified=True,
        notes="Emailed Verizon PDF, 1 ICD (Abel Draper), Sun-Sat. Hand-keyed "
              "for now. Rollover must still freeze its weekly total."),
]


def by_label(label: str) -> Optional[Source]:
    return next((s for s in DAILY_SOURCES if s.label == label), None)


def shared_groups() -> dict[str, List[Source]]:
    """{shared_key: [sources]} — sections that come from ONE pull."""
    out: dict[str, List[Source]] = {}
    for s in DAILY_SOURCES:
        if s.shared_key:
            out.setdefault(s.shared_key, []).append(s)
    return out


def run_order() -> List[List[Source]]:
    """Fastest pull order, grouped into stages ([[feedback_report_runtime]]):

      Stage 1 — Tableau SCRAPE pulls (custom views via View Data), all
                back-to-back in ONE reused patchright session — login once,
                no re-auth between pulls.
      Stage 2 — MANUAL fills (no network) from hand-keyed input.

    Within each stage, sections sharing a pull (shared_key) are pulled once
    (Retail NL + Retail Internet = one SARA scrape). The wins are (a) ONE
    auth/session reused for every pull, (b) one pull feeding multiple
    sections. (Future optimization: any view whose base worksheet + filter
    URL-params reproduce the custom view could move to the ~1s HTTP .csv
    endpoint — but the scrape is what's verified to respect the saved
    filters today.)
    """
    def dedup(sources: List[Source]) -> List[Source]:
        seen, out = set(), []
        for s in sources:
            key = s.shared_key or s.label
            if key not in seen:
                seen.add(key)
                out.append(s)
        return out

    scrape = dedup([s for s in DAILY_SOURCES if s.method == SCRAPE])
    manual = [s for s in DAILY_SOURCES if s.method == MANUAL]
    return [scrape, manual]
