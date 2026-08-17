"""What each CAMPAIGN is, and which metrics it can support.

This is the piece nobody had written down. The org board already knows which
ICDs run which campaign (every daily section IS a campaign, and an ICD's row in
that section is the board asserting the ICD runs it) — but "Isaiah is wireless
only, so he has no new-internet metrics" lived only in people's heads and in one
hand-maintained SECTION_OVERRIDES row. That is the fact this file makes
declarative.

Two registries:

  CAMPAIGNS — one row per org-board daily section. Carries the PRODUCT FAMILIES
    the campaign actually sells, plus the exact Tableau source (workbook / view /
    worksheet / filter) the board pulls it from.

  METRICS — one row per per-office daily metric, carrying the product family it
    NEEDS. A metric applies to an ICD only if some campaign that ICD runs sells
    that family.

So `applicable_metrics(["ATT NDS Team"])` returns the wireless-side metrics and
drops the internet ones, without anyone hand-listing them per office. That is
the whole point: an ICD's metric list is DERIVED from what they sell, so a
wireless-only office can never again be enrolled in eleven internet boards and
post a thread of blanks.

URLs here are transcribed from the pull specs that actually run
(org_sales_board/section_pull.py, sara_pull.py, je_pull.py,
office_metrics/offices.py) — NOT from sources.py's docstrings, which are stale
on two views (they name 'FiberTeamnovoice' and 'Wirelessthisweek'; the specs
pull 'AllproductsRafsteam' and 'WIRELESSONLY').
"""
from __future__ import annotations

from dataclasses import dataclass, field

_T = "https://us-east-1.online.tableau.com/#/site/sci/views/"

# Product families. A campaign SELLS families; a metric NEEDS one. The join of
# those two is what makes a metric apply to an ICD.
WIRELESS = "wireless"        # wireless lines / NDS wireless
INTERNET = "internet"        # new internet (fiber/AIR/broadband)
VIDEO = "video"
B2B = "b2b"                  # business — AT&T B2B
ENERGY = "energy"            # Just Energy / Box energy
FIBER_OTHER = "frontier"     # Frontier (Credico), not AT&T


@dataclass(frozen=True)
class Campaign:
    key: str
    section: str          # the org-board daily-section label = the join key
    label: str            # human name for the site
    families: tuple       # product families this campaign actually sells
    workbook: str = ""    # Tableau workbook slug
    view: str = ""        # Tableau view / custom-view slug
    worksheet: str = ""   # crosstab worksheet, when pulled as a crosstab
    url: str = ""         # full custom-view URL the pull actually navigates to
    owner_col: str = ""   # the column the ICD is identified by in the crosstab
    filters: str = ""     # saved-view filters that materially change the number
    notes: str = ""

    @property
    def is_tableau(self) -> bool:
        return bool(self.url)


# ---------------------------------------------------------------------------
# THE CAMPAIGN TABLE — keyed by the org board's daily-section label.
# ---------------------------------------------------------------------------
CAMPAIGNS: dict[str, Campaign] = {
    "retail_nl": Campaign(
        key="retail_nl", section="Retail NL", label="Retail — Wireless Lines",
        families=(WIRELESS,),
        workbook="DropshipV_2", view="RetailNLOrgSalesBoard",
        url=_T + ("DropshipV_2/SARAPLUSSALESSUMMARYBYDAY/"
                  "6e2f1ff9-4f18-4e99-bef9-0644c8328082/RetailNLOrgSalesBoard"),
        owner_col="ICD Owner Name",
        filters="Measure = 'Wireless Lines'. UPGRADES EXCLUDED by a saved filter "
                "on the view (Megan 2026-07-03).",
        notes="SARA-sourced, relative to this week. The upgrade exclusion lives "
              "ONLY as a saved filter — the scrape reads no sale-type column, so "
              "if that view resets, upgrades creep back in silently."),
    "retail_internet": Campaign(
        key="retail_internet", section="Retail Internet",
        label="Retail — Internet", families=(INTERNET,),
        workbook="DropshipV_2", view="RetailNLOrgSalesBoard",
        url=_T + ("DropshipV_2/SARAPLUSSALESSUMMARYBYDAY/"
                  "6e2f1ff9-4f18-4e99-bef9-0644c8328082/RetailNLOrgSalesBoard"),
        owner_col="ICD Owner Name",
        filters="Measure = 'Internet'.",
        notes="SAME pull as Retail NL — one SARA scrape feeds both sections; "
              "they differ only by which Measure Name is read."),
    "att_fiber": Campaign(
        key="att_fiber", section="ATT Fiber Team",
        label="AT&T D2D — Fiber Team", families=(WIRELESS, INTERNET, VIDEO),
        workbook="ATTTRACKER2_1-D2D", view="AllproductsRafsteam",
        worksheet="Sales By ICD (Weekly View)",
        url=_T + ("ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/"
                  "ab2eca72-395f-48d5-a254-9d99739b88d4/AllproductsRafsteam"),
        owner_col="Owner Name",
        filters="ALL product types EXCEPT Voice. Week-pinned to the reporting "
                "week (the view defaults to LAST week).",
        notes="The full-stack D2D campaign — these ICDs sell wireless AND "
              "internet AND video, so every metric applies to them. This is the "
              "profile the 11-metric daily thread was designed around."),
    "att_nds": Campaign(
        key="att_nds", section="ATT NDS Team",
        label="AT&T NDS — Wireless Only", families=(WIRELESS,),
        workbook="NDS-SNRES-ATT-OOFWorkbook", view="WIRELESSONLY",
        worksheet="Sales By ICD (Weekly View)",
        url=_T + ("NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep/"
                  "d9da84f9-9302-4249-96b5-f4d1df08774f/WIRELESSONLY"),
        owner_col="Owner & Office",
        filters="Wireless only. Week-pinned. Owner cell carries a '[company]' "
                "suffix that must be stripped.",
        notes="THE ONE THAT BITES. NDS owners sell NO new internet, so every "
              "internet-side metric (ABP, new-internet churn, ongoing cancel, "
              "disconnects) is N/A for them and renders blank. Their metrics "
              "come from the NDS-SN workbook, not the ATT-D2D one. This is why "
              "Isaiah and Drew are flagged nds=True in office_metrics.offices."),
    "b2b": Campaign(
        key="b2b", section="B2B", label="AT&T B2B", families=(B2B,),
        workbook="ATTTRACKER-B2B", view="LuissCaptainship",
        worksheet="Sales By ICD (ATT) (V2)",
        url=_T + ("ATTTRACKER-B2B/D2D1-PAGERV3/"
                  "e52b4954-dc0b-4f2a-a588-d218942f23a0/LuissCaptainship"),
        owner_col="ICD Owner Name",
        filters="Excludes Tablets / Wearables / Upgrades. Week-pinned.",
        notes="A DIFFERENT CAMPAIGN from D2D — the shared AT&T metric views do "
              "not describe a B2B office. Carlos is the standing example: he "
              "gets Tableau trackers but NO daily-metrics thread, and that is "
              "correct, not a coverage gap (Megan 2026-07-16)."),
    "box": Campaign(
        key="box", section="BOX", label="BOX / Energy", families=(ENERGY,),
        workbook="B2BBOXEnergyTracker", view="BoxDailyTracker",
        worksheet="Daily Tracker Sales",
        url=_T + "B2BBOXEnergyTracker/BoxDailyTracker",
        owner_col="Owner Name",
        filters="Week-pinned under this view's OWN caption 'Sale Date "
                "Weekending' — NOT the '(mon-sun)' caption every other view "
                "uses. A wrong caption is ignored SILENTLY (Eve 2026-08-10).",
        notes="Workbook renamed 2026-06-29 (B2BBOXEnergy → B2BBOXEnergyTracker); "
              "the old path 404s."),
    "retail_je": Campaign(
        key="retail_je", section="Retail JE", label="Just Energy — Retail",
        families=(ENERGY,),
        workbook="JustEnergyRTL-SalesStaffingProductivityWorkbook",
        view="ThisWeek", worksheet="Daily Sales by ICD",
        url=_T + ("JustEnergyRTL-SalesStaffingProductivityWorkbook/"
                  "WeeklyMetricsbyICD/41cac48e-7b4d-4b27-b595-8b01b1e80948/"
                  "ThisWeek?:iid=1"),
        owner_col="ICD Office Name",
        filters="The view's week is DRIVEN each run (the saved 'Sales Week "
                "Ending' filter was found pinned to a stale week — do not trust "
                "it to auto-roll).",
        notes="Runs a day behind (Sunday posts Monday). The board section is a "
              "CURATED subset of the fuller JE roster, deliberately."),
    "frontier": Campaign(
        key="frontier", section="Frontier", label="Frontier (Credico)",
        families=(FIBER_OTHER,),
        filters="", workbook="", view="",
        notes="NOT TABLEAU. Parsed from the emailed Credico 'Daily Sales - "
              "Frontier - Events by Store' PDF. Runs SUN–SAT, a day behind. "
              "Any site pulling 'from Tableau' will simply have no source for "
              "this ICD — it has to come off the PDF ingest."),
}

# section label -> campaign key, for joining the board read to this table
BY_SECTION: dict[str, str] = {c.section: c.key for c in CAMPAIGNS.values()}


# ---------------------------------------------------------------------------
# THE METRIC TABLE — what the daily thread can show, and what it needs to exist.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Metric:
    slug: str             # office_metrics runner slug
    label: str            # the board title as it posts
    needs: tuple          # product families; metric applies if ANY is sold
    source: str = ""      # where the number comes from
    url: str = ""
    scope: str = "org_sliced"   # org_sliced | ownerville | screenshot
    # Some metrics can only be read out of ONE workbook. An NDS owner sells
    # wireless, same as a D2D fiber owner, so product family alone does NOT
    # separate them — but their orders live in the NDS-SN workbook, so a metric
    # built on an ATTTRACKER2_1-D2D view genuinely cannot reach them. When set,
    # the ICD must run at least one campaign sourced from this workbook.
    needs_workbook: str = ""
    # Metrics that DO exist for NDS owners but come from a different place.
    # Applicability is by product family; the SOURCE is by campaign.
    nds_source: str = ""
    notes: str = ""


METRICS: list[Metric] = [
    Metric("order_log", "📋 Order Log", (WIRELESS, INTERNET),
           source="org-wide 'A.Order Log' crosstab, filtered to the owner",
           notes="One shared crosstab feeds order_log + cancels + disconnects."),
    Metric("rep_activations", "🆕 Rep Activations", (WIRELESS, INTERNET),
           source="same 'A.Order Log' crosstab",
           notes="Posts as its own board, separate from Order Log "
                 "(Megan 2026-08-07)."),
    Metric("sales_6plus", "📅 Sales Scheduled 6+ Days Out", (INTERNET,),
           source="org-wide order crosstab, filtered to the owner",
           notes="Install-scheduling metric — internet only."),
    Metric("cancels", "🚫 Canceled Orders", (WIRELESS, INTERNET),
           source="org-wide 'A.Order Log' crosstab"),
    Metric("disconnects", "❎ Disconnected New Internets", (INTERNET,),
           source="org-wide 'A.Order Log' crosstab",
           notes="New-internet only by definition."),
    Metric("ongoing_cancel", "🔁 Ongoing Cancel", (INTERNET,),
           source="CancelRatesRunningSumRaf / InternetCancelRatesDoD / AllExpanded",
           url=_T + ("CancelRatesRunningSumRaf/InternetCancelRatesDoD/"
                     "878f4f05-e565-4e93-9c78-be4a8f96b73c/AllExpanded?:iid=1"),
           notes="Rate can't be averaged — the slice recomputes it as "
                 "sum(cancels)/sum(sales) from the summable count measures."),
    Metric("churn_ni", "🌐 New Internet Churn", (INTERNET,),
           source="ATTTRACKER2_1-D2D / CHURN / INTAllTeams",
           url=_T + ("ATTTRACKER2_1-D2D/CHURN/"
                     "907184c5-3782-4c32-92ff-919b63d5d402/INTAllTeams?:iid=1")),
    Metric("churn_wl", "📊 Wireless Churn", (WIRELESS,),
           source="ATTTRACKER2_1-D2D / CHURN / WirelessAllTeams",
           url=_T + ("ATTTRACKER2_1-D2D/CHURN/"
                     "66b10d0a-1bb2-441a-85b1-982977a9514e/WirelessAllTeams?:iid=1"),
           nds_source="NDS-SN ChurnALlExp, sliced per rep (office_metrics."
                      "nds_churn)",
           notes="Wireless churn is the ONE churn half an NDS office has. The "
                 "runner bundles both halves into a single 'churn' metric, so "
                 "the internet half can't be dropped independently today."),
    Metric("abp", "💳 New Internet ABP %", (INTERNET,),
           source="ATTTRACKER2_1-D2D / Metrics / ALLEXP",
           url=_T + ("ATTTRACKER2_1-D2D/Metrics/"
                     "0d5c97aa-d39e-4541-bf88-a8e599ab5e69/ALLEXP?:iid=1"),
           notes="Must use an EXPANDED view — the collapsed default drops the "
                 "'Rep Name' column and ABP crashes for every office."),
    Metric("knocks_gaps", "🚪 Total Knocks + 🕐 Time Gaps", (WIRELESS, INTERNET, B2B),
           source="ownerville (impersonate → Disposition + Time Tracker)",
           scope="ownerville",
           notes="NOT Tableau — the only metric that isn't. Needs the office's "
                 "ownerville name, which often differs from the Tableau name."),
    Metric("tableau_shot", "📸 Tableau Metrics", (WIRELESS, INTERNET),
           source="ATT TRACKER 2.1 Metrics view, screenshotted, owner-filtered",
           scope="screenshot", needs_workbook="ATTTRACKER2_1-D2D",
           notes="D2D-ONLY. An NDS owner sells wireless too, so family alone "
                 "would wrongly include them — but this shot is of the D2D "
                 "tracker, which has none of their orders. Both NDS overrides "
                 "(isaiah, drew) exclude it, which is why it's workbook-gated."),
]

METRIC_BY_SLUG: dict[str, Metric] = {m.slug: m for m in METRICS}


# ---------------------------------------------------------------------------
# HEADLINE VITALS — the office-level numbers that sit ABOVE the campaign
# boards (Megan 2026-08-17). These are not per-campaign: every ICD gets them
# regardless of what they sell, because they describe the OFFICE, not the
# product. They are the "are we healthy" line, where the boards are "what did
# we sell".
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Vital:
    slug: str
    label: str
    definition: str        # say the arithmetic out loud — these get misread
    source: str = ""       # "" = not wired yet
    notes: str = ""

    @property
    def is_wired(self) -> bool:
        return bool(self.source)


VITALS: list[Vital] = [
    Vital("active_reps", "Active Reps",
          definition="reps on the office roster",
          source="",
          notes="DEFINITION TRAP — pin this before building. On the Tableau "
                "trackers, 'Rep Count' means reps who PRODUCED that week, NOT "
                "the roster ([[reference_showdown_rep_count_is_weekly]]). So "
                "'active reps' can mean two different numbers, and the % below "
                "is meaningless until we say which. Recommend: roster = "
                "ownerville headcount, producers = the sales pull, and never "
                "reuse the word 'active' for both."),
    Vital("reps_selling_pct", "% of Reps Selling",
          definition="reps with at least one sale this week / active reps",
          source="",
          notes="Numerator is already available — every campaign's expanded "
                "crosstab carries per-rep rows, so counting reps with a nonzero "
                "week is a slice of a pull we ALREADY do. The denominator is "
                "the missing half (see above). This is the metric that shows "
                "an office carried by three people."),
    Vital("apps_in", "Applications Coming In",
          definition="applications received this week",
          source="appstream",
          notes="Same number as stage 1 of the recruiting funnel — pull it "
                "ONCE and show it in both places rather than sourcing it twice "
                "([[feedback_no_cross_report_data_reuse]] is about not reusing "
                "another REPORT's output; this is one report showing one "
                "number in two views, which is fine)."),
    Vital("apps_removed", "Applications Removed",
          definition="applications removed from the funnel this week",
          source="",
          notes="The counterweight to apps coming in — volume alone reads "
                "healthy right up until you see how much of it was thrown "
                "away. Confirm with Eve WHICH removals count (disqualified, "
                "withdrawn, duplicate, aged-out); ApplicantStream almost "
                "certainly distinguishes them and they mean different things."),
]

# HOW THIS RENDERS (Megan 2026-08-17): "needs to be stupid simple to look at."
# The owner-facing page is not an analyst tool. Same standard as the Hub itself
# ([[feedback_simple_ux]]): one number per concept, the obvious default, no
# syntax and no configuration. Concretely, for this build:
#   • the vitals above are the ONLY things above the fold — four numbers;
#   • a metric that does not apply is ABSENT, not shown empty or greyed;
#   • say the plain word, not the system's word ("reps selling", not
#     "producer ratio"); and
#   • one glance answers "are we up or down" — the detail is below, not beside.
SIMPLE_UX_NOTE = __doc__

VITAL_BY_SLUG: dict[str, Vital] = {v.slug: v for v in VITALS}


def families_for(sections: list) -> set:
    """The product families an ICD sells, from the board sections they appear in."""
    fams: set = set()
    for s in sections:
        key = BY_SECTION.get(s)
        if key:
            fams.update(CAMPAIGNS[key].families)
    return fams


def workbooks_for(sections: list) -> set:
    """The Tableau workbooks an ICD's campaigns actually live in."""
    books: set = set()
    for s in sections:
        key = BY_SECTION.get(s)
        if key and CAMPAIGNS[key].workbook:
            books.add(CAMPAIGNS[key].workbook)
    return books


def applicable_metrics(sections: list) -> list:
    """Metric slugs that are MEANINGFUL for an ICD running these campaigns.

    A metric applies when the ICD sells at least one family the metric needs
    AND — for metrics that can only be read out of one workbook — the ICD has a
    campaign in that workbook. Everything else is N/A: not 'missing', not
    'broken'. An all-blank board is worse than no board (Megan 2026-08-04), so
    the site should render only these and say nothing about the rest."""
    fams = families_for(sections)
    books = workbooks_for(sections)
    return [m.slug for m in METRICS
            if (fams & set(m.needs))
            and (not m.needs_workbook or m.needs_workbook in books)]


def na_metrics(sections: list) -> list:
    """The inverse — slugs that do NOT apply, so a display can explain the gap
    instead of showing an empty board."""
    ok = set(applicable_metrics(sections))
    return [m.slug for m in METRICS if m.slug not in ok]
