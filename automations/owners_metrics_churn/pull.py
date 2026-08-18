"""Tableau pulls for the Owners Metrics Report churn tabs.

Each captainship gets ITS OWN pull (separate Tableau Crosstab download)
so the Grand Total row at the top of the Crosstab IS that
captainship's Captainship Avg. Pulling once with no captain filter and
splitting in Python would give a single combined Grand Total — not
useful.

All Fiber captainships share the same `ATTTRACKER2_1-D2D/CHURN`
workbook. B2B + NDS pull from different workbooks (TBD — Megan
sending URLs per phase).

Parser reuses the captainship_churn.pull.parse logic — data shape is
identical (per-ICD-owner rows + Grand Total office row).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from automations.shared.tableau_patchright import download_crosstab_patchright as _dcp


def _dl(view_url, crosstab_sheet, out_path, verbose=False, page=None, pre_export=None):
    """Harvest cutover (DEFAULT-OFF): read the dated cache when HARVEST_MODE=on,
    else scrape live. A cache miss/stale/error falls through to the live pull, so
    with no env var behaviour is identical to today."""
    if os.environ.get("HARVEST_MODE", "off").strip().lower() == "on":
        from automations.harvest import adapter
        cached = adapter.try_cache_view(view_url, crosstab_sheet, out_path)
        if cached is not None:
            return cached
    return _dcp(view_url, crosstab_sheet, out_path,
                verbose=verbose, page=page, pre_export=pre_export)
from automations.captainship_churn import pull as _shared
from automations.new_internet_churn import pull as _ni_shared  # for _to_num
from automations.focus_office_att.aliases import alias_to_canonical


def _apply_alias(name: str, aliases: Optional[dict]) -> str:
    """Map a parsed rep name to its canonical sheet-tab name via the
    shared ICD Aliases sheet, if an aliases dict was provided.
    Returns the input unchanged when no aliases or no match.

    Megan 2026-05-29: Tableau pulled 'Mohammad Altom' on Khalil's tab
    while the sheet had 'Mohammed Altom' (spelling variant). Without
    alias resolution, the parser treats them as two different reps
    and the runner inserts a duplicate. Reading the aliases sheet at
    parse time bridges the two automatically.
    """
    if not aliases:
        return name
    return alias_to_canonical(name, aliases)

# ----- Fiber (Phase 1) -----------------------------------------------
# Custom views Megan saves in Tableau with Churn View = New Internet
# Churn View + Product Type = NEW INTERNET + Captain's Bonus Teams =
# <captain's team> baked in. Replace these GUIDs when she sends them.
FIBER_WAYNE_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "2ad705af-af9a-4ae6-89e8-75dc9f3e4707/WAYNESTEAMCHURN?:iid=1"  # re-saved 2026-06-05 (old view corrupted)
)
FIBER_STARR_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "ed79d85b-5a5d-45c6-9610-e7a3c3b29086/STARSTEAMCHURN?:iid=1"  # re-saved 2026-06-05 (old view corrupted)
)
FIBER_ARON_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "a1726231-fd1a-434a-8172-ede2567df3c0/ARONSTEAMCHURN?:iid=1"  # re-saved 2026-06-05 (old view corrupted)
)
FIBER_CHAN_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "42938560-8c7b-43c5-a897-2a851dda252e/CHANSTEAMCHURN?:iid=1"
)
FIBER_TONY_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "5115611a-86e9-4a5c-bab1-ccb5b85c546c/TONY%E2%80%99S%20TEAM%20CHURN?:iid=1"
)
FIBER_SAHIL_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "e8557aee-2a5b-4c68-a6ad-a1da1394e198/SAHIL%E2%80%99S%20TEAM%20CHURN?:iid=1"
)
# All-teams (org-wide) Fiber churn view — the base CHURN dashboard, which already
# defaults to 'New Internet Churn View' + Captain's Bonus Teams = All (Megan
# confirmed 2026-07-23), so it lists every Fiber rep across all teams. Used to
# backfill a rep on a captain's tab who's absent from that captain's own SAVED
# view: Blue Mendoza is a new rep on Starr's team who never got added to the
# STARSTEAMCHURN custom-view filter, so Starr's own pull dropped him. Same
# 'ICD Churn' worksheet + parse() as the per-captain Fiber pulls.
FIBER_ALLTEAM_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN?:iid=1"
)

WORKSHEET = "ICD Churn"

PERIODS = _shared.PERIODS
fmt_units = _shared.fmt_units
parse = _shared.parse


# ----- Fiber WIRELESS (same captains, 'Wireless Churn - …' tabs) ------
# Eve 2026-07-28: the fiber captains wanted their WIRELESS churn filled the same
# way as their New Internet churn. There is NO per-captain wireless custom view
# in Tableau (Megan only ever saved per-captain NEW INTERNET views), so instead
# of asking her to build five more, we pull the ORG-WIDE wireless view ONCE and
# slice it per captainship in Python on the `Captain's Bonus Teams` column — the
# same SFDC team filter the per-captain NI views apply server-side.
#
# The view is AUTOMATION-WirelessChurn: the churn dashboard with
# `Churn View = Wireless Churn View` baked in (that parameter — not a
# Product Type override — is what drives the wireless formula; see
# wireless_churn/pull.py for the bug that taught us this). It is already proven
# in production by recruiting_report.opt_phase, which pulls it every week for
# the OPT wireless-churn rows, so we reuse its view id + worksheet rather than
# minting a sixth custom view.
#
# Its worksheet is "ICD Churn (Wireless)" — distinct from the "ICD Churn" sheet
# the New Internet views export — and it carries owner-level rows PLUS the
# `Captain's Bonus Teams` column we slice on.
FIBER_WIRELESS_ORG_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "67ab7e84-5a66-43c9-a6e5-df2edcaf95e6/AUTOMATION-WirelessChurn?:iid=1"
)
WIRELESS_WORKSHEET = "ICD Churn (Wireless)"

# Report slug -> the `Captain's Bonus Teams` cell value for that captainship.
# Sourced from the live crosstab (2026-07-28), NOT guessed: the column carries
# "Wayne's Team" etc. with a curly-free apostrophe. Aron is absent (his tab is
# retired to 'x - Churn - Aron Corral'), so only the five active fiber captains
# are here — matching the five fiber entries in run.REPORTS.
FIBER_WIRELESS_TEAM = {
    "wayne": "Wayne's Team",
    "starr": "Starr's Team",
    "chan":  "Chan's Team",
    "tony":  "Tony's Team",
    "sahil": "Sahil's Team",
}

# One download per PROCESS, shared by all five wireless reports. run.py calls
# fetch_fn once per selected report; without this cache the identical org view
# would be scraped five times (~1 min each) for byte-identical bytes.
_WIRELESS_ORG_CSV: Optional[Path] = None


def fetch_fiber_wireless_org(out_path: Optional[Path] = None,
                             verbose: bool = False, page=None) -> Path:
    """Download the ORG-WIDE wireless churn crosstab (all captainships).

    Cached per process — the second..fifth caller gets the first pull's file.
    """
    global _WIRELESS_ORG_CSV
    out_path = out_path or (Path(tempfile.gettempdir())
                            / "owners_fiber_wireless_org.csv")
    if _WIRELESS_ORG_CSV is not None and _WIRELESS_ORG_CSV.exists():
        return _WIRELESS_ORG_CSV
    _dl(FIBER_WIRELESS_ORG_URL, WIRELESS_WORKSHEET, out_path,
        verbose=verbose, page=page)
    _WIRELESS_ORG_CSV = out_path
    return out_path


def _fmt_pct(num: float, denom: float, decimals: int = 2) -> Optional[str]:
    """Format a churn % the way Tableau's crosstab does: percentage to
    `decimals` places, round-half-up, trailing '%'. None when denom is 0."""
    from decimal import Decimal, ROUND_HALF_UP
    if not denom:
        return None
    pct = (Decimal(str(num)) / Decimal(str(denom))) * Decimal(100)
    q = pct.quantize(Decimal("1." + "0" * decimals) if decimals else Decimal("1"),
                     rounding=ROUND_HALF_UP)
    return f"{q}%"


def _team_col(header) -> int:
    """Index of the `Captain's Bonus Teams` column. Matched by PREFIX because
    the header carries a 'v2' suffix on some views and none on others."""
    return next(i for i, h in enumerate(header)
                if h.startswith("Captain's Bonus Teams"))


def parse_wireless_team(csv_path: Path, team_value: Optional[str] = None) -> dict:
    """Pivot the ORG-WIDE wireless crosstab, keeping only `team_value`'s rows.

    Same output shape as parse() so the shared fill helpers consume it unchanged.

    Two differences from the per-captain New Internet pulls:
      * The rows are sliced HERE (on the `Captain's Bonus Teams` column) instead
        of server-side by a saved view.
      * Tableau's own 'Grand Total' row is ORG-WIDE, so it is dropped and the
        Captainship Avg is RECOMPUTED from the sliced owners:
        num/denom = column sums, pct = num/denom in Tableau's format. Keeping
        Tableau's Grand Total would print the whole company's wireless churn on
        every captain's tab.

    team_value=None keeps every team (used for the moved-owner backfill, which
    looks a rep up by name regardless of which captainship she sits on now).
    """
    import csv as _csv
    with open(csv_path, "r", encoding="utf-16-le") as f:
        rows = list(_csv.reader(f, delimiter="\t"))
    if not rows:
        return {"office_total": {}, "reps": {}}

    header = [h.lstrip("﻿").strip() for h in rows[0]]
    rep_i = header.index("ICD Owner Name (rep)")
    team_i = _team_col(header)
    color_col = next((c for c in header if c.startswith("30-60 Color Churn")), None)
    if color_col is None:
        raise ValueError(f"No '30-60 Color Churn ...' column found in {header}.")
    color_i = header.index(color_col)
    metric_i = header.index("0-30 Day Churn") - 1
    period_cols = {p: header.index(f"{p} Day Churn") for p in PERIODS}

    reps: dict = {}
    matched_rows = 0

    for r in rows[1:]:
        if len(r) <= max(period_cols.values()):
            continue
        raw_name = r[rep_i].strip()
        if raw_name == "Grand Total":
            continue                       # org-wide total — recomputed below
        team = r[team_i].strip() if len(r) > team_i else ""
        if team_value is not None and team != team_value:
            continue
        matched_rows += 1
        color = r[color_i].strip()
        metric = r[metric_i].strip()
        display_name = _shared._smart_title(raw_name)

        for period, col_i in period_cols.items():
            cell = r[col_i].strip()
            if not cell:
                continue
            slot = reps.setdefault(display_name, {}).setdefault(period, {})
            if color and color != "Total":
                slot.setdefault("color", color)
            # ACCUMULATE, never overwrite. One owner can appear under two
            # `Captain's Bonus Teams` values when his reps span captainships
            # (William Sassenberg sits on both Pat's and Starr's teams,
            # 2026-07-28). Within one team the color dimension also splits an
            # owner across rows, but each period lands in exactly one color row,
            # so a per-team slice never collides — only the all-teams parse
            # does, and overwriting there silently dropped his units.
            if metric == "Churn Rate (Unit vs Order)":
                if "pct" in slot:
                    slot["_multi"] = True   # two source rows → recompute below
                else:
                    slot["pct"] = cell
            elif metric == "Disconnect count (SPE/SP)":
                slot["num"] = (slot.get("num") or 0) + _ni_shared._to_num(cell)
            elif metric == "Activated SPE/SP":
                slot["denom"] = (slot.get("denom") or 0) + _ni_shared._to_num(cell)
            # Calculation1 (1) is a tableau normalizer — skip.

    # Any period fed by more than one source row needs its % recomputed from the
    # summed units; Tableau's per-row % only covers that row's slice.
    for periods_data in reps.values():
        for slot in periods_data.values():
            if slot.pop("_multi", False):
                recomputed = _fmt_pct(slot.get("num") or 0, slot.get("denom") or 0)
                if recomputed is not None:
                    slot["pct"] = recomputed

    if team_value is not None and not matched_rows:
        # A silent empty slice is the dangerous failure here: the fill would run
        # clean and write nothing. Almost always the team was renamed in SFDC
        # (e.g. "Wayne's Team" -> "Wayne's Team v2"), which FIBER_WIRELESS_TEAM
        # must then follow.
        raise ValueError(
            f"No rows for Captain's Bonus Teams == {team_value!r} in "
            f"{csv_path.name}. Teams present: "
            f"{sorted({(r[team_i] or '').strip() for r in rows[1:] if len(r) > team_i})}"
        )

    return {"office_total": _recompute_office_total(reps), "reps": reps}


def _recompute_office_total(reps: dict) -> dict:
    """Captainship Avg per period from the sliced owner rows: num/denom are
    column sums, pct is the Tableau-formatted ratio. Only emits a period some
    owner actually reports."""
    total: dict = {}
    for p in PERIODS:
        present = [d[p] for d in reps.values() if p in d]
        if not present:
            continue
        num = sum(c.get("num") or 0 for c in present)
        denom = sum(c.get("denom") or 0 for c in present)
        pct = _fmt_pct(num, denom)
        if pct is None:
            continue
        total[p] = {"num": num, "denom": denom, "pct": pct}
    return total


def make_wireless_parser(slug: str):
    """A parse_fn bound to one captainship's team value, for run.REPORTS."""
    team_value = FIBER_WIRELESS_TEAM[slug]

    def _parse(csv_path: Path) -> dict:
        return parse_wireless_team(csv_path, team_value)

    _parse.__name__ = f"parse_wireless_{slug}"
    _parse.is_wireless = True          # read by run._program_of
    return _parse


def parse_wireless_allteams(csv_path: Path) -> dict:
    """Every team's wireless rows — the moved-owner backfill source."""
    return parse_wireless_team(csv_path, None)


def fetch_fiber_wayne(out_path: Optional[Path] = None,
                     verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_fiber_wayne.csv"
    _dl(FIBER_WAYNE_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_fiber_starr(out_path: Optional[Path] = None,
                     verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_fiber_starr.csv"
    _dl(FIBER_STARR_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_fiber_aron(out_path: Optional[Path] = None,
                    verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_fiber_aron.csv"
    _dl(FIBER_ARON_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_fiber_chan(out_path: Optional[Path] = None,
                    verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_fiber_chan.csv"
    _dl(FIBER_CHAN_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_fiber_tony(out_path: Optional[Path] = None,
                    verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_fiber_tony.csv"
    _dl(FIBER_TONY_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_fiber_sahil(out_path: Optional[Path] = None,
                     verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_fiber_sahil.csv"
    _dl(FIBER_SAHIL_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


# ----- B2B (Phase 2) -------------------------------------------------
# Different Tableau workbook (ATTTRACKER-B2B/CHURNRATES) — 5-bucket
# (0-30 / 30 / 60 / 90 / 120 day) per-ICD churn shape. Total row
# labeled "Grand Total" in the Crosstab (megan called it "Total
# General" in the live view; the export label is "Grand Total").
B2B_CARLOS_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER-B2B/CHURNRATES/"
    "77b888d4-dec2-45c9-bdce-5511f6055084/CarlosCaptainship?:iid=1"
)
# Eveliz's view excludes Van (custom view "EvelizWOVan"). FRAGILITY:
# if the filter is a fixed include-list of names, any ICD added to
# Eveliz's captainship in Tableau will NOT show up here until megan
# updates the view. If it's an exclude-list ("exclude Van"), new ICDs
# auto-flow through. Megan flagged this 2026-05-29 — verify the
# filter type and re-save as exclude if needed.
B2B_EVELIZ_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER-B2B/CHURNRATES/"
    "867f88d3-4026-4c70-b275-330208a4053c/EvelizWOVan?:iid=1"
)

# Luis Salazar — same B2B workbook, view filtered to his captainship team
# (added 2026-05-30 at Eve's request).
B2B_LUIS_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER-B2B/CHURNRATES/"
    "2d2a9ec0-8088-4e4e-8ada-ed370f4b9d8f/LuissCaptainship?:iid=1"
)

# All-teams B2B churn view (team filter = All) — every B2B owner regardless of
# captainship. Same CHURNRATES dashboard + "ICD Churn" crosstab as the per-captain
# B2B views above, so parse_b2b reads it unchanged. Used to BACKFILL an owner who
# moved captainships: reps change teams routinely (Megan 2026-07-09), and once a
# rep leaves a captain's SFDC team the per-captain pull no longer returns her even
# though her row is still on that captain's sheet tab — she'd silently go dark.
# Pulling her from here keeps the tab filling instead. (Proven view id — also used
# by recruiting_report.opt_phase_carlos.)
B2B_ALLTEAM_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER-B2B/CHURNRATES/"
    "429cb06d-a32e-4d0e-bf06-9acb77587afd/ALLTEAMCHURN?:iid=1"
)


def fetch_b2b_allteams(out_path: Optional[Path] = None,
                       verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_b2b_allteams.csv"
    _dl(B2B_ALLTEAM_URL, WORKSHEET, out_path,
                                 verbose=verbose, page=page)
    return out_path


B2B_PERIODS = ("0-30", "30", "60", "90", "120")


def fetch_b2b_luis(out_path: Optional[Path] = None,
                   verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_b2b_luis.csv"
    _dl(B2B_LUIS_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_b2b_carlos(out_path: Optional[Path] = None,
                     verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_b2b_carlos.csv"
    _dl(B2B_CARLOS_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_b2b_eveliz(out_path: Optional[Path] = None,
                     verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_b2b_eveliz.csv"
    _dl(B2B_EVELIZ_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def parse_b2b(csv_path: Path) -> dict:
    """Pivot the B2B Crosstab into office_total + per-ICD data.

    Differences from the Fiber/Captainship parse:
      * Owner column is 'Owner & Office'; the cell value is multi-line
        ('CAPTAIN NAME\\n [office]'). We split at the newline and
        title-case the name.
      * No 'Captain's Bonus Teams' column.
      * Five period columns: '0-30 Day' through '120 Day' (NO 'Churn'
        suffix).
      * Churn-rate metric row is labeled 'Churn Rate', not 'Churn
        Rate (Unit vs Order)'.
    """
    import csv as _csv
    with open(csv_path, "r", encoding="utf-16-le") as f:
        rows = list(_csv.reader(f, delimiter="\t"))
    if not rows:
        return {"office_total": {}, "reps": {}}

    header = [h.lstrip("﻿").strip() for h in rows[0]]
    rep_i = header.index("Owner & Office")
    color_col = next(
        (c for c in header if c.startswith("30-60 Color Churn")),
        None,
    )
    if color_col is None:
        raise ValueError(
            f"No '30-60 Color Churn ...' column found in {header}."
        )
    color_i = header.index(color_col)
    metric_i = header.index("0-30 Day") - 1
    period_cols = {p: header.index(f"{p} Day") for p in B2B_PERIODS}

    office_total: dict = {}
    reps: dict = {}

    for r in rows[1:]:
        if len(r) <= max(period_cols.values()):
            continue
        raw_name = (r[rep_i] or "").strip()
        # 'CAPTAIN NAME\n [office]' → 'CAPTAIN NAME'
        bare_name = raw_name.split("\n")[0].strip()
        color = (r[color_i] or "").strip()
        metric = (r[metric_i] or "").strip()
        is_total = bare_name == "Grand Total"

        display_name = bare_name if is_total else _shared._smart_title(bare_name)

        for period, col_i in period_cols.items():
            cell = (r[col_i] or "").strip()
            if not cell:
                continue
            target = office_total if is_total else reps.setdefault(display_name, {})
            slot = target.setdefault(period, {})
            if not is_total and color and color != "Total":
                slot.setdefault("color", color)
            if metric == "Churn Rate":
                slot["pct"] = cell
            elif metric == "Disconnect count (SPE/SP)":
                slot["num"] = _ni_shared._to_num(cell)
            elif metric == "Activated SPE/SP":
                slot["denom"] = _ni_shared._to_num(cell)

    return {"office_total": office_total, "reps": reps}


def make_b2b_captainship_parser(roster):
    """parse_b2b narrowed to ONE captainship's roster, off the all-teams view.

    Why this exists (2026-08-18, Eve): Atef Choudhury got his own captainship,
    but he is not in the Tableau captain dropdown yet, so `CHURNRATES` has no
    `AtefCaptainship` custom view to point a per-captain pull at. His reps are
    "sueltos" — spread through the org-wide view. ALLTEAMCHURN already lists
    every B2B owner (it is the proven moved-rep backfill source), so read that
    and keep only his three.

    'Grand Total' from that file is the whole B2B org, which would print as his
    "Captainship Avg" — the one number on the tab nobody would catch as wrong.
    So office_total is RECOMPUTED from the roster's own disconnects over their
    own activations, which is what a captainship average is.

    Swap this for a plain per-captain fetch the day his view exists; the tab and
    everything downstream stay as they are.
    """
    want = {_ni_shared._norm_name(n) if hasattr(_ni_shared, "_norm_name")
            else " ".join(str(n).lower().split()) for n in roster}

    def _key(n):
        return " ".join(str(n or "").lower().split())

    def _parse(csv_path: Path) -> dict:
        parsed = parse_b2b(csv_path)
        reps = {n: d for n, d in parsed["reps"].items() if _key(n) in want}
        office: dict = {}
        for period in B2B_PERIODS:
            num = denom = 0
            seen = False
            for d in reps.values():
                slot = d.get(period) or {}
                if slot.get("num") is None and slot.get("denom") is None:
                    continue
                seen = True
                num += slot.get("num") or 0
                denom += slot.get("denom") or 0
            if not seen:
                continue
            office[period] = {
                "num": num, "denom": denom,
                "pct": ("%.2f%%" % (100.0 * num / denom)) if denom else "0.00%",
            }
        return {"office_total": office, "reps": reps}

    _parse.__name__ = "parse_b2b_captainship"
    return _parse


# ----- NDS (Phase 3) -------------------------------------------------
# Different Tableau workbook (NDS-SNRES-ATT-OOFWorkbook/CHURNRATES)
# AND a different worksheet name in the Crosstab dialog
# ('Churn Rates (ICD)' instead of 'ICD Churn'). Back to 4-bucket
# (0-30 / 30 / 60 / 90) shape like Fiber. Office row labeled
# 'Office/Organization Average' (not 'Grand Total'). Disconnect /
# activation metric labels also differ: 'Activated Wireless Lines'
# instead of 'Activated SPE/SP', plain 'Disconnect count' instead of
# 'Disconnect count (SPE/SP)'.
NDS_KHALIL_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "NDS-SNRES-ATT-OOFWorkbook/CHURNRATES/"
    "5c5501aa-98b3-48c5-b260-a8b405a16412/KhalilsCaptainship?:iid=1"
)
NDS_COLTEN_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "NDS-SNRES-ATT-OOFWorkbook/CHURNRATES/"
    "32daf35c-78ac-480e-b7b7-e9c24bdacba8/ColtensCaptainshipChurn?:iid=1"  # re-saved 2026-06-17 (old view 28f34b4b… returned Jairo's data)
)
NDS_JAIRO_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "NDS-SNRES-ATT-OOFWorkbook/CHURNRATES/"
    "e20c59fb-dd0e-4c0e-af0b-ae803ccd1fc4/JairosCaptainship?:iid=1"
)
# All-teams (org-wide) NDS churn view — the UNFILTERED base CHURNRATES view (no
# per-captain custom-view suffix), so it lists every NDS rep across all teams.
# Used to backfill a rep who MOVED captainships (still on a captain's sheet tab
# but no longer in that captain's own pull): Jimmy Bonilla moved off Khalil's
# team to 'obsidian opulence, inc.' but stayed on Khalil's tab (Megan 2026-07-23).
# parse_nds strips the '[office]' suffix, so 'JIMMY BONILLA [obsidian opulence,
# inc.]' matches his sheet row 'Jimmy Bonilla'.
NDS_ALLTEAM_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "NDS-SNRES-ATT-OOFWorkbook/CHURNRATES?:iid=1"
)
NDS_WORKSHEET = "Churn Rates (ICD)"
NDS_PERIODS = ("0-30", "30", "60", "90")


def fetch_nds_khalil(out_path: Optional[Path] = None,
                     verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_nds_khalil.csv"
    _dl(NDS_KHALIL_URL, NDS_WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_nds_colten(out_path: Optional[Path] = None,
                     verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_nds_colten.csv"
    _dl(NDS_COLTEN_URL, NDS_WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def fetch_nds_jairo(out_path: Optional[Path] = None,
                    verbose: bool = False, page=None) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "owners_nds_jairo.csv"
    _dl(NDS_JAIRO_URL, NDS_WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def parse_nds(csv_path: Path) -> dict:
    """Pivot the NDS Crosstab into office_total + per-ICD data.

    Differences from B2B parse:
      * No named header columns for owner/color/metric — they're
        positional (cols 0/1/2). The first labeled column is
        '0-30 Day Churn' at index 3.
      * Office row labeled 'Office/Organization Average' (NDS) vs
        'Grand Total' (Fiber/B2B).
      * Metric labels: 'Activated Wireless Lines' (denom) +
        'Disconnect count' (num), no '(SPE/SP)' suffix.
      * Owner cell is multi-line: 'NAME\\n[office]' (square brackets,
        no leading space) — split at newline.
    """
    import csv as _csv
    with open(csv_path, "r", encoding="utf-16-le") as f:
        rows = list(_csv.reader(f, delimiter="\t"))
    if not rows:
        return {"office_total": {}, "reps": {}}

    header = [h.lstrip("﻿").strip() for h in rows[0]]
    period_cols = {p: header.index(f"{p} Day Churn") for p in NDS_PERIODS}

    office_total: dict = {}
    reps: dict = {}

    for r in rows[1:]:
        if len(r) <= max(period_cols.values()):
            continue
        raw_name = (r[0] or "").strip()
        bare_name = raw_name.split("\n")[0].strip()
        color = (r[1] or "").strip()
        metric = (r[2] or "").strip()
        is_total = bare_name == "Office/Organization Average"

        display_name = bare_name if is_total else _shared._smart_title(bare_name)

        for period, col_i in period_cols.items():
            cell = (r[col_i] or "").strip()
            if not cell:
                continue
            target = office_total if is_total else reps.setdefault(display_name, {})
            slot = target.setdefault(period, {})
            if not is_total and color and color != "Total":
                slot.setdefault("color", color)
            if metric == "Churn Rate":
                slot["pct"] = cell
            elif metric == "Disconnect count":
                slot["num"] = _ni_shared._to_num(cell)
            elif metric == "Activated Wireless Lines":
                slot["denom"] = _ni_shared._to_num(cell)

    return {"office_total": office_total, "reps": reps}


# ----- All-teams churn sources (for backfilling reps who moved captainships) --
# program -> (all_teams_view_url, crosstab_worksheet, parse_fn). When an owner on
# a captain's churn tab is absent from that captain's own pull (she moved SFDC
# teams), the runner pulls the program's all-teams view here and re-fills her row
# from it. Only B2B has a proven all-teams churn view today; a moved Fiber/NDS
# owner still flags went-dark (unchanged) until their all-teams CHURN view id is
# added here.
ALLTEAMS_CHURN_SOURCE = {
    "b2b": (B2B_ALLTEAM_URL, WORKSHEET, parse_b2b),
    "fiber": (FIBER_ALLTEAM_URL, WORKSHEET, parse),      # wired 2026-07-23 (Blue Mendoza absent from Starr's saved view)
    "nds": (NDS_ALLTEAM_URL, NDS_WORKSHEET, parse_nds),   # wired 2026-07-23 (Jimmy Bonilla moved teams)
    # Fiber wireless already pulls org-wide and slices per team, so a rep who
    # moved captainships IS in the file — just under a different team value.
    # Re-reading it with no team filter finds her by name (2026-07-28).
    "fiber_wireless": (FIBER_WIRELESS_ORG_URL, WIRELESS_WORKSHEET,
                       parse_wireless_allteams),
}
