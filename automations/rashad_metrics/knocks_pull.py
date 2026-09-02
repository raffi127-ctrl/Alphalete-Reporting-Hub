"""Pull a SPECIFIC office's daily 'knocks' data (Disposition by Rep + Time
Tracker gaps) from ownerville — the EXACT same scrape Raf's Total Knocks
report uses, but for an arbitrary office reached via IMPERSONATION first.

Raf's pull (automations.total_knocks.pull) scrapes whatever office the
ownerville session is currently on — Raf is the master/default office, so
it never switches. This module does the same scrape, but inside the single
ownerville_session it first IMPERSONATES the target office (default:
Rashad Reed), scrapes, then EXITS impersonation before the session closes.

EVERYTHING that does the actual scraping is IMPORTED from
total_knocks.pull (no copy-paste): _navigate / _header_index /
_scrape_rows / _scrape_time_tracker, the SHEET_COLUMNS/COL_* constants,
and the same badge-ID gap merge that pull_disposition_day does. The ONLY
thing added here is the impersonate-by-name wrapper, which is itself
imported from focus_office_att.run_all_owners so the office-switching
logic stays in one place.

Office is env-targetable (same pattern as the churn module's
CHURN_NI_VIEW_URL etc.):
    RASHAD_KNOCKS_OFFICE   default "Rashad Reed"
Name-spelling drift is resolved through the canonical ICD alias list.

Run standalone to preview a day's scrape WITHOUT touching any Sheet:
    python -m automations.rashad_metrics.knocks_pull            # yesterday
    python -m automations.rashad_metrics.knocks_pull 2026-06-27 # a date
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sys
from typing import Optional

from automations.shared.tableau_patchright import ownerville_session

# Impersonate-by-name machinery — imported, NOT duplicated. These are the
# same helpers run_all_owners uses to switch ownerville to one owner's
# office and back to master.
from automations.focus_office_att.aliases import (
    alias_to_canonical,
    load_aliases,
)
from automations.focus_office_att.run_all_owners import (
    _navigate_to_office_access,
    _find_owner_and_impersonate,
    _exit_impersonation,
)
from automations.focus_office_att.step5_fill_one_owner import page_rqst

# Scrape primitives + canonical columns — imported from Raf's pull so this
# report and Raf's stay byte-for-byte identical on the scrape itself.
from automations.total_knocks import pull as knocks
from automations.total_knocks.pull import (
    COL_ID,
    COL_GAPS,
    COL_TOTAL_GAPS,
    KnocksPullFailed,  # re-exported: callers catch it without importing both
    SHEET_COLUMNS,  # re-exported for callers (Sheet column order)
)

# The WIRELESS (NDS) Disposition by Rep table has a different shape from the
# house one: one "Not Interested" bucket (no Talk-To/Presentation split), no
# Sale column, plus wireless-only columns we don't board (battery, coverage,
# device, territory name, tm version, vl, total hours, total scheduled).
# Discovered live 2026-08-22 (Isaiah Revelle): the house scrape raised
# "missing expected column(s)" and the live-headers diagnostic showed this set.
_WIRELESS_COLUMNS = [
    knocks.COL_ID, knocks.COL_REP, knocks.COL_TOTAL_LEADS_KNOCKED,
    knocks.COL_TOTAL_KNOCKS, knocks.COL_FIRST_KNOCK, knocks.COL_LAST_KNOCK,
    knocks.COL_NO_ANSWER, knocks.COL_NOT_INTERESTED, knocks.COL_COME_BACK,
    knocks.COL_INACCESSIBLE, knocks.COL_DO_NOT_KNOCK,
]
_WIRELESS_COUNTS = {
    knocks.COL_TOTAL_LEADS_KNOCKED, knocks.COL_TOTAL_KNOCKS,
    knocks.COL_NO_ANSWER, knocks.COL_NOT_INTERESTED, knocks.COL_COME_BACK,
    knocks.COL_INACCESSIBLE, knocks.COL_DO_NOT_KNOCK,
}


# Energy Wells: the wireless columns plus Presentation and VL. Ordered so the
# board reads knocks -> outcomes, the same left-to-right as the others.
_ENERGYWELL_COLUMNS = [
    knocks.COL_ID, knocks.COL_REP, knocks.COL_TOTAL_LEADS_KNOCKED,
    knocks.COL_TOTAL_KNOCKS, knocks.COL_FIRST_KNOCK, knocks.COL_LAST_KNOCK,
    knocks.COL_NO_ANSWER, knocks.COL_NOT_INTERESTED, knocks.COL_PRESENTATION,
    knocks.COL_COME_BACK, knocks.COL_VL, knocks.COL_INACCESSIBLE,
    knocks.COL_DO_NOT_KNOCK,
]
_ENERGYWELL_COUNTS = {
    knocks.COL_TOTAL_LEADS_KNOCKED, knocks.COL_TOTAL_KNOCKS,
    knocks.COL_NO_ANSWER, knocks.COL_NOT_INTERESTED, knocks.COL_PRESENTATION,
    knocks.COL_COME_BACK, knocks.COL_VL, knocks.COL_INACCESSIBLE,
    knocks.COL_DO_NOT_KNOCK,
}
# Talk-to = everything except No answer and Inaccessible — nobody was spoken to
# in those. The SAME rule fiber uses (Do Not Knock counts), with VL added per
# Raf. Fiber's TALK_TO_PARTS is shared by every fiber board and must not gain
# VL, so Energy Wells carries its own list.
_ENERGYWELL_TALK_TO_PARTS = [
    knocks.COL_NOT_INTERESTED, knocks.COL_PRESENTATION, knocks.COL_COME_BACK,
    knocks.COL_VL, knocks.COL_DO_NOT_KNOCK,
]


def _is_energywell_dispo(idx: dict) -> bool:
    """Energy-Wells-shaped Disposition: the VL column is the signature — no
    other campaign's grid carries it. Checked BEFORE the wireless test, which
    this shape would otherwise satisfy (it has no Talk-To split either)."""
    # AND NOT the house Talk-To split. VL alone is not enough: a fiber grid
    # that also carries a VL column would be claimed here and then fail the
    # Energy Wells scrape on the columns it does not have — which is exactly
    # what killed Chan Park's comparison line on 2026-08-31 ("this one doesn't
    # have chans numbers?"). The campaign shapes are told apart by what they
    # LACK as much as by what they have, the same way the wireless test works.
    return (knocks._norm(knocks.COL_TOTAL_KNOCKS) in idx
            and knocks._norm(knocks.COL_VL) in idx
            and knocks._norm(knocks.COL_TALK_TO_NI) not in idx)


def _scrape_energywell_rows(page, idx: dict) -> list[dict]:
    """Energy Wells rows, keyed by _ENERGYWELL_COLUMNS, with Total Talk to
    computed over _ENERGYWELL_TALK_TO_PARTS. Same pagination walk as the
    wireless scrape."""
    rows = _scrape_shaped_rows(page, idx, _ENERGYWELL_COLUMNS,
                               _ENERGYWELL_COUNTS, "Energy Wells")
    for rec in rows:
        rec[knocks.COL_TOTAL_TALK_TO] = sum(
            int(rec.get(c) or 0) for c in _ENERGYWELL_TALK_TO_PARTS)
    return rows


# B2B. TWO campaigns, TWO grids, and they are not each other's — B2B AT&T SBS
# (invD2DClientId=2) and B2B-BOX-Energy (16) share only the spine (ID / Rep /
# Total Leads Knocked / Total Knocks / First / Last Knock) plus Come Back and
# Inaccurate Lead. Both column sets were read LIVE off p=89 on 2026-09-02 with
# the campaign pinned — an unpinned dump proves nothing, the campaign being a
# sticky session-global — and both header dumps are kept under output/probes/.
#
# WHY THEY NEEDED THEIR OWN SHAPES RATHER THAN THE TOLERANT WIRELESS SCRAPE.
# A B2B grid carries Total Knocks and no house Talk-To split, so
# _is_wireless_dispo claims it; the wireless scrape only REQUIRES ID/Rep/Total
# Knocks and zero-fills the rest. So B2B used to render a clean, plausible board
# with 0 under every disposition while the reps' real outcomes sat in buckets
# nobody read. The near-miss English is what makes it so easy: AT&T's grid says
# "Talked To - Not Interested" where fiber says "Talk To - Not Interested", and
# "Presentation - Not Interested" where fiber writes the en-dash version.
#
# NEITHER B2B GRID HAS A "No answer" BUCKET, and only Box has Inaccessible.
_B2B_ATT_COLUMNS = [
    knocks.COL_ID, knocks.COL_REP, knocks.COL_TOTAL_LEADS_KNOCKED,
    knocks.COL_TOTAL_KNOCKS, knocks.COL_FIRST_KNOCK, knocks.COL_LAST_KNOCK,
    knocks.COL_B2B_TALKED_TO_NI, knocks.COL_PRES_NI, knocks.COL_SALE,
    knocks.COL_COME_BACK, knocks.COL_B2B_CORP_LOCAL,
    knocks.COL_B2B_CORP_NO_OPP, knocks.COL_DO_NOT_KNOCK,
    knocks.COL_B2B_INACCURATE_LEAD, knocks.COL_B2B_NONE,
]
_B2B_ATT_COUNTS = set(_B2B_ATT_COLUMNS) - {
    knocks.COL_ID, knocks.COL_REP, knocks.COL_FIRST_KNOCK,
    knocks.COL_LAST_KNOCK}

_B2B_BOX_COLUMNS = [
    knocks.COL_ID, knocks.COL_REP, knocks.COL_TOTAL_LEADS_KNOCKED,
    knocks.COL_TOTAL_KNOCKS, knocks.COL_FIRST_KNOCK, knocks.COL_LAST_KNOCK,
    knocks.COL_BOX_TALKED_TO, knocks.COL_BOX_OWNER_TALKED_TO,
    knocks.COL_NOT_INTERESTED, knocks.COL_BOX_CONTRACT_SIGNED,
    knocks.COL_BOX_BILL_NO_SALE, knocks.COL_COME_BACK,
    knocks.COL_BOX_AM_COME_BACK, knocks.COL_BOX_CORP_NO_OPP,
    knocks.COL_BOX_DO_NOT_DISTURB, knocks.COL_INACCESSIBLE,
    knocks.COL_B2B_INACCURATE_LEAD,
]
_B2B_BOX_COUNTS = set(_B2B_BOX_COLUMNS) - {
    knocks.COL_ID, knocks.COL_REP, knocks.COL_FIRST_KNOCK,
    knocks.COL_LAST_KNOCK}

# TALK-TO = every bucket except the ones where nobody was spoken to. That is the
# house rule (fiber excludes No answer and Inaccessible, and counts Do Not
# Knock), applied to each B2B vocabulary:
#   AT&T  excludes None (knocked, no disposition) and Inaccurate Lead (the lead
#         was wrong, so there was nobody there). It has no No-answer bucket.
#   Box   excludes Inaccessible and Inaccurate Lead, and counts Do Not Disturb
#         the way fiber counts Do Not Knock.
#
# BOX'S THREE TALK-TO COLUMNS ARE THREE DISPOSITIONS, not one counted thrice.
# Asked and answered (Megan 2026-09-02): "they should be each their own column."
# So "Talked To", "Owner Talked To" and "Not Interested" are mutually exclusive
# the way every other grid's buckets are — a knock lands in exactly one, the
# board shows all three, and summing them into Total Talk to is a sum over
# distinct doors rather than the double-count it would be if a knock could hold
# two of them at once. Do not "simplify" this by collapsing them.
_B2B_ATT_TALK_TO_PARTS = [
    knocks.COL_B2B_TALKED_TO_NI, knocks.COL_PRES_NI, knocks.COL_SALE,
    knocks.COL_COME_BACK, knocks.COL_B2B_CORP_LOCAL,
    knocks.COL_B2B_CORP_NO_OPP, knocks.COL_DO_NOT_KNOCK,
]
_B2B_BOX_TALK_TO_PARTS = [
    knocks.COL_BOX_TALKED_TO, knocks.COL_BOX_OWNER_TALKED_TO,
    knocks.COL_NOT_INTERESTED, knocks.COL_BOX_CONTRACT_SIGNED,
    knocks.COL_BOX_BILL_NO_SALE, knocks.COL_COME_BACK,
    knocks.COL_BOX_AM_COME_BACK, knocks.COL_BOX_CORP_NO_OPP,
    knocks.COL_BOX_DO_NOT_DISTURB,
]


def _is_b2b_att_dispo(idx: dict) -> bool:
    """B2B AT&T SBS. "Corp Franchise No Opp" is the signature — no other grid
    carries a Corp column, and Box spells its own one "Corp - No Opp"."""
    return knocks._norm(knocks.COL_B2B_CORP_NO_OPP) in idx


def _is_b2b_box_dispo(idx: dict) -> bool:
    """B2B Box Energy. "Owner Talked To" is unique to it; the Corp column is
    checked too so a grid that renames one still lands here rather than being
    claimed by the tolerant wireless scrape."""
    return (knocks._norm(knocks.COL_BOX_OWNER_TALKED_TO) in idx
            or knocks._norm(knocks.COL_BOX_CORP_NO_OPP) in idx)


def is_b2b_dispo(idx: dict) -> bool:
    return _is_b2b_att_dispo(idx) or _is_b2b_box_dispo(idx)


# WHAT GRID EACH PINNED CAMPAIGN MUST PRODUCE. Only the campaigns whose grids
# are distinguishable on sight are listed — a pin we cannot verify is not
# checked, rather than guessed at.
#
# THIS EXISTS BECAUSE A PINNED CAMPAIGN DOES NOT ALWAYS PRODUCE ITS OWN GRID
# (observed 2026-09-02). Impersonating Carlos Hidalgo (11580) and pinning
# invD2DClientId=16 returned the 22-header B2B AT&T grid, not Box's 24-header
# one — in a fresh session, grid warmed first, and with the page genuinely on
# 16 (54 of its links carried it, and his picker lists B2B-BOX-Energy).
#
# IT IS THE OFFICE, NOT IMPERSONATION. Roshan Amin Ahmad (19833, Sapphire
# Marketing) is impersonated exactly the same way and his campaign-16 pull
# serves the full Box grid and real Box rows. Carlos's office simply does not
# render a Box-shaped disposition table, whatever its picker offers — so a
# campaign-16 pull against it comes back holding AT&T's reps and AT&T's numbers
# under a Box heading.
#
# Left unchecked that is the worst failure this repo has: a board titled "B2B
# Box" carrying AT&T's reps and AT&T's numbers, which — unlike a blank board —
# nobody reading it can tell is wrong. Same family as the impersonation
# fall-through that put Raf's 37 reps in Jay Turnage's chat.
CAMPAIGN_EXPECTED_SHAPE = {
    "2": ("B2B AT&T SBS", _is_b2b_att_dispo),
    "16": ("B2B-BOX-Energy", _is_b2b_box_dispo),
}


def assert_campaign_grid(idx: dict, campaign_id: "Optional[str]") -> None:
    """Raise unless the grid on screen is the one this campaign should serve.

    No-op when nothing was pinned, or when the campaign's grid has no signature
    we can recognise — this refuses what it can PROVE wrong, never what it
    merely cannot confirm.
    """
    want = CAMPAIGN_EXPECTED_SHAPE.get(str(campaign_id or "").strip())
    if not want:
        return
    name, matches = want
    if matches(idx):
        return
    got = ("B2B AT&T-shaped" if _is_b2b_att_dispo(idx)
           else "B2B Box-shaped" if _is_b2b_box_dispo(idx)
           else "not a B2B grid at all")
    raise KnocksPullFailed(
        "campaign %s (%s) was pinned, but the Disposition grid on screen is %s "
        "— the pin did not take and every number from it belongs to another "
        "campaign. Refusing to publish them. Headers seen: %s"
        % (campaign_id, name, got, ", ".join(sorted(idx)[:24])))


def _scrape_b2b_rows(page, idx: dict) -> list[dict]:
    """B2B rows for whichever of the two grids this is, with Total Talk to
    summed over that campaign's own parts."""
    att = _is_b2b_att_dispo(idx)
    cols, counts, parts, label = (
        (_B2B_ATT_COLUMNS, _B2B_ATT_COUNTS, _B2B_ATT_TALK_TO_PARTS, "B2B AT&T")
        if att else
        (_B2B_BOX_COLUMNS, _B2B_BOX_COUNTS, _B2B_BOX_TALK_TO_PARTS, "B2B Box"))
    rows = _scrape_shaped_rows(page, idx, cols, counts, label)
    for rec in rows:
        rec[knocks.COL_TOTAL_TALK_TO] = sum(
            int(rec.get(c) or 0) for c in parts)
    return rows


def _is_wireless_dispo(idx: dict) -> bool:
    """Wireless-shaped Disposition: has Total Knocks but not the house
    Talk-To split — the signature that separates the two table shapes."""
    return (knocks._norm(knocks.COL_TOTAL_KNOCKS) in idx
            and knocks._norm(knocks.COL_TALK_TO_NI) not in idx)


def _scrape_wireless_rows(page, idx: dict) -> list[dict]:
    """Walk the DataTables pages of a WIRELESS-shaped Disposition table and
    return one dict per rep keyed by _WIRELESS_COLUMNS. Same pagination walk
    as the house _scrape_rows, minus the Talk-To calculation."""
    return _scrape_shaped_rows(page, idx, _WIRELESS_COLUMNS, _WIRELESS_COUNTS,
                               "Wireless")


def _scrape_shaped_rows(page, idx: dict, columns: list, counts: set,
                        label: str) -> list[dict]:
    """The DataTables walk, for any campaign's column set.

    Was the wireless-only scrape; Energy Wells needed the identical walk over a
    different column list, and a second copy of a pagination loop is how the
    two drift. `label` only names the shape in errors.
    """
    # Same tolerance as the house walk: only ID / Rep / Total Knocks are
    # required, every other bucket is optional because the disposition
    # vocabulary is per-office (knocks._resolve_columns).
    want, absent = knocks._resolve_columns(idx, columns,
                                           label=f"{label} disposition")

    table = page.locator("#table-dispositions")
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#table-dispositions tbody tr')"
            ".length >= 1", timeout=10000)
    except Exception as e:  # noqa: BLE001 — turned into a typed failure below
        # An empty day still renders DataTables' 'No data available' row, so
        # zero rows means the grid never built — a failed scrape, not a quiet
        # day. Same rule as the house walk in total_knocks.pull._scrape_rows.
        raise KnocksPullFailed(
            f"{label} disposition grid rendered no rows at all — not even "
            "DataTables' 'No data available' placeholder — so the scrape "
            "failed rather than the day being empty.") from e

    out: list = []
    seen_ids: set = set()
    for _ in range(20):  # safety cap on pagination
        for tr in table.locator("tbody tr").all():
            cells = [c.inner_text().strip() for c in tr.locator("td").all()]
            if not cells or cells[0].lower().startswith("no data"):
                continue
            if max(want.values()) >= len(cells):
                continue
            rec = {}
            for col, i in want.items():
                raw = cells[i]
                rec[col] = knocks._to_int(raw) if col in counts else raw
            # A bucket this office's page doesn't carry: zero doors went into
            # it (blank for the text columns), so the board still renders.
            for col in absent:
                rec[col] = 0 if col in counts else ""
            rid = str(rec.get(knocks.COL_ID, "")).strip()
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            out.append(rec)
        nxt = page.locator("#table-dispositions_next").first
        if nxt.count() == 0 or "disabled" in (nxt.get_attribute("class") or ""):
            break
        nxt.click()
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001 — same tolerance as the house walk
            pass
    return out

# Default office to impersonate. Env-targetable so the same module can be
# pointed at another office without a code change (mirrors the churn
# module's CHURN_*_VIEW_URL env overrides).
# KNOCKS_OFFICE is the office-agnostic override (Aya + future offices);
# RASHAD_KNOCKS_OFFICE stays as Rashad's back-compat name.
DEFAULT_OFFICE = (os.environ.get("KNOCKS_OFFICE")
                  or os.environ.get("RASHAD_KNOCKS_OFFICE", "Rashad Reed"))

# TeleMapper pages AND its JSON endpoints (Time Tracker included) are scoped
# to the session's STICKY current campaign — whatever was last selected, by
# anyone, survives into the next visit. Proven 2026-08-22: with Isaiah's
# session stuck on RES-ENERGYWELL the Time Tracker returned 0 rows for a day
# with 7 knocking reps; one navigation pinned to RES AT&T brought them back.
# So every scrape PINS the campaign first. 3 = "RES AT&T", the campaign all
# current knocks offices (fiber D2D and NDS wireless) knock under.
KNOCKS_CAMPAIGN_ID = os.environ.get("KNOCKS_CAMPAIGN_ID", "3")


# An office that knocks a campaign OTHER than the default goes here, keyed by
# ownerville name (already _norm_name'd — lowercase, trimmed). An entry has to
# be OBSERVED and written down, never inferred: a guess here silently blanks a
# whole office's board.
#
# calvin ribera -> 40 (RES-ENERGYWELL). Observed 2026-08-29: Megan read
# invD2DClientId=40 straight off the live URL with his grid on screen. He is
# Energy Wells ONLY (Raf: "Calvin is ENERGY WELL only"), and without this entry
# he was being pinned to 3 (RES AT&T) like everyone else and coming back with
# ZERO rows for days that plainly had four reps on them — the exact
# silently-blank-board failure this dict exists to prevent.
CAMPAIGN_OVERRIDES: "dict[str, str]" = {
    # ONE row, keyed by the CANONICAL name. "Calvin Rivera" is not listed and
    # does not need to be: the alias sheet already resolves it, and every
    # caller runs alias_to_canonical BEFORE asking this map (Megan 2026-09-01:
    # "we already have the alias added - both those calvins are the same").
    # A second spelling here would be the per-report patch the alias sheet
    # exists to replace, and two places to update the next time a name drifts.
    "calvin ribera": "40",
}


# An office that knocks MORE THAN ONE campaign, keyed by canonical name:
# [(label, invD2DClientId, keyword), ...]. CAMPAIGN_OVERRIDES holds one value
# per office and cannot describe these at all.
#
# This is what lets a request ASK instead of guessing (Megan 2026-09-01: "maybe
# it's a response to that request instead of everyone having to pick on each
# request"). A picker on every /knocks would tax the many for the few; a
# follow-up only when the name is genuinely ambiguous costs nothing to anyone
# else.
#
# Jay Turnage knocks both and gets a separate report for each, so a /knocks
# that silently picked one would hand back half his day as if it were all of
# it. Ids read off the live picker: 3 = RES AT&T, 40 = RES-ENERGYWELL.
MULTI_CAMPAIGN: "dict[str, list]" = {
    "jay turnage": [("AT&T", "3", "att"),
                    ("Energy Wells", "40", "energywell")],
}


def campaigns_for(name: str) -> list:
    """[(label, id, keyword)] when this office runs more than one campaign,
    else []. Canonical name, same as campaign_for_office."""
    from automations.focus_office_att.aliases import _norm_name
    return list(MULTI_CAMPAIGN.get(_norm_name(name or ""), []))


def campaign_by_keyword(name: str, word: str) -> "str | None":
    """The invD2DClientId for a spoken campaign word ("att", "energywell"),
    or None when it names none of this office's campaigns."""
    w = (word or "").strip().lower().replace("-", "").replace(" ", "")
    for _label, cid, key in campaigns_for(name):
        if w == key:
            return cid
    return None


def campaign_for_office(name: str) -> str:
    """The TeleMapper campaign to pin for `name`. "" would mean DON'T pin.

    PASS THE CANONICAL NAME. This map is keyed by it, and resolving aliases
    here would mean a Sheet read on every call; the callers already canonicalise
    (pull_offices_days and pull_office_days_on_page both run
    alias_to_canonical first), so an alias never reaches this lookup.

    Everyone gets the default unless CAMPAIGN_OVERRIDES says otherwise.

    This USED to return "" for any office flagged NDS, on the reasoning that a
    wireless office has no fiber campaign. That was wrong, and Isaiah is why
    (Megan checked his ownerville on 2026-08-25): his campaign picker offers
    BASE Energy / RES AT&T / RES-ENERGYWELL, and his reps knock RES AT&T like
    everyone else. His Disposition page is empty because his reps don't
    disposition at all — they clock in and knock, and Time Tracker is the only
    record. NDS describes the BUSINESS, not the campaign; conflating the two
    left his session free to drift onto BASE Energy or RES-ENERGYWELL and
    quietly return nothing.

    So the pin is not derived from anything about the office any more — an
    exception has to be observed and written down, not inferred.
    """
    from automations.focus_office_att.aliases import _norm_name
    return CAMPAIGN_OVERRIDES.get(_norm_name(name or ""), KNOCKS_CAMPAIGN_ID)


def _pin_campaign(page, rqst: str, campaign_id: Optional[str] = None,
                  verbose: bool = True) -> None:
    """Force the impersonated session's TeleMapper campaign so a stale sticky
    selection can't silently blank the whole pull. Best-effort: a failure here
    leaves us exactly where we were before this guard existed.

    `campaign_id` None means "use the module default" (what every caller did
    before per-office campaigns existed). An EMPTY campaign skips the pin —
    the session keeps whatever campaign it already had. That's what
    weekly_knock_dispositions does for an NDS office, and it's how
    `lucy probe_knocks … campaign=none` asks whether the pin is what's
    blanking an office."""
    campaign_id = (KNOCKS_CAMPAIGN_ID if campaign_id is None else campaign_id)
    if not campaign_id:
        if verbose:
            print("  · TeleMapper campaign pin SKIPPED "
                  "(no campaign for this office)", flush=True)
        return
    try:
        page.goto(f"https://v2.ownerville.com/index.cfm?p=88&rqst={rqst}"
                  f"&invD2DClientId={campaign_id}",
                  wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(1000)
        if verbose:
            print(f"  ✓ Pinned TeleMapper campaign (invD2DClientId="
                  f"{campaign_id})", flush=True)
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"  ⚠ Campaign pin failed ({type(e).__name__}) — "
                  "continuing with the session's current campaign", flush=True)


_BE_OFFICE_SEL = "select[name=beOffice], #beOffice"


def impersonated_office_label(page, rqst: str, *, attempts: int = 3) -> str:
    """The office the session is ACTUALLY on, read off p=88's `beOffice` select
    — e.g. "Calvin Ribera (22162 - Vernon, Inc.)".

    This is the only readout that tracks impersonation. The rqst token does NOT:
    ownerville hands an impersonated session the SAME token as master, so a
    confirmImpersonate that silently fails leaves every later fetch answering
    for the wrong office with nothing raising (verified 2026-09-01).

    RETRIED, because "" is no longer a free pass. A single flaky read is what
    put Raf's 38 reps on a board titled KHALIL MANSOUR (2026-09-02, /knocks):
    the read came back empty once, assert_impersonating took that as "not a
    mismatch", and the pull scraped whatever office the session was on. The
    same read, re-run against the same office minutes later, took 1-4s and
    answered "KHALIL MANSOUR (11901 - ALPHALETE MANAGEMENT GROUP, INC.)" every
    time — so it is transient, and a retry costs a few seconds against a board
    of someone else's numbers.

    Waits for the SELECT, not for networkidle: the element is in the initial
    HTML, while the grid behind it keeps loading — on the biggest offices
    (11280, 11901) that is the difference between a 1s read and a timeout.
    """
    last = ""
    for i in range(max(1, attempts)):
        try:
            page.goto("https://v2.ownerville.com/index.cfm?p=88&rqst=%s" % rqst,
                      wait_until="domcontentloaded", timeout=45000)
            page.wait_for_selector(_BE_OFFICE_SEL, timeout=20000)
            last = page.eval_on_selector(
                _BE_OFFICE_SEL,
                "e => (e.options[e.selectedIndex] || {}).text || ''") or ""
            if last.strip():
                return last
        except Exception:  # noqa: BLE001 — a check must never be the failure
            pass
        if i + 1 < max(1, attempts):
            try:
                page.wait_for_timeout(1500)
            except Exception:  # noqa: BLE001
                pass
    return last


def assert_impersonating(page, rqst: str, canonical: str, aliases_raw,
                         *, verbose: bool = True) -> None:
    """Raise unless the session is really on `canonical`'s office.

    WHY THIS IS NOT OPTIONAL. On 2026-09-01 `/knocks Kash Rai` came back with
    Calvin Ribera's seven Energy Wells reps under the heading "TOTAL KNOCKS —
    KASH RAI", and the same fall-through put Raf's 37 reps in Jay Turnage's
    chat. Nothing errored in either case. A board with the right title and
    another office's numbers is worse than no board: unlike a blank one, the
    person reading it cannot tell.

    AND WHY IT NOW RAISES ON AN UNREADABLE OFFICE. The first cut let an
    unreadable label through — "only a positive mismatch counts" — which is a
    guard that stands down the moment it is inconvenienced. 2026-09-02:
    `/knocks Khalil Mansour` drew Raf's 38 reps under KHALIL MANSOUR, and the
    log for that one office is missing its "✓ Confirmed" line while Chan,
    Kash, Cyrus and Isaiah all carry theirs from the same session. The guard
    never decided anything; the read came back empty once and it stepped
    aside. So: retry, then take a second opinion off the page header, then
    refuse. A request that errors can be re-asked.
    """
    label = impersonated_office_label(page, rqst)
    if not label:
        # UNREADABLE IS NOT A PASS. It used to be — "only a positive mismatch
        # counts" — and that is the hole Khalil Mansour fell through on
        # 2026-09-02: one empty read, no "✓ Confirmed" line, and /knocks handed
        # back Raf's 38 reps under the title KHALIL MANSOUR. Every other office
        # in the same session confirmed normally, so the guard was not wrong
        # about the office; it simply never got to ask.
        #
        # Second opinion before giving up: while impersonating, p=901 renders
        # the office-access LIST and the header carries no office id, so an id
        # here at all means the session is still on master and the switch
        # plainly did not take. Named separately because it is the failure that
        # actually happens, and "still on Raf" is worth saying out loud.
        head, office_id = logged_in_office(page)
        if office_id == MASTER_OFFICE_ID:
            raise RuntimeError(
                "impersonation of %r did not take — the session is still on "
                "the master office %s, and every number from it would be "
                "Raf's. Header: %r"
                % (canonical, MASTER_OFFICE_ID, head[:120]))
        raise RuntimeError(
            "couldn't read which office the session is on after impersonating "
            "%r (p=88 gave no beOffice value in any of its tries) — "
            "refusing to publish numbers nobody can attribute. Ask again; "
            "this read is transient." % (canonical,))
    # load_aliases() returns {canonical_sheet_tab: [aliases]} — NOT
    # {alias: canonical}. Reading it the other way round built an alias set
    # that never contained the alias, so this refused the RIGHT office: on
    # 2026-09-01 it told Raf "impersonation landed on 'Akashdeep Rai (22177 -
    # Palace Acquisitions, Inc.)', not 'Kash Rai'" — which is the same office,
    # under the spelling ownerville uses.
    want = {_norm_office(canonical)}
    for canon, alias_list in (aliases_raw or {}).items():
        if _norm_office(canon) != _norm_office(canonical):
            continue
        for alias in (alias_list or []):
            want.add(_norm_office(alias))
    got = _norm_office(label)
    if any(w and w in got for w in want):
        if verbose:
            print("  ✓ Confirmed on %s" % label.strip(), flush=True)
        return
    raise RuntimeError(
        "impersonation landed on %r, not %r — ownerville did not switch office "
        "and every number from this session would belong to someone else."
        % (label.strip()[:80], canonical))


def _norm_office(name) -> str:
    return " ".join(str(name or "").split()).strip().lower()


def pull_office_knocks(office_name: Optional[str] = None,
                       target: Optional[dt.date] = None,
                       verbose: bool = True) -> tuple[dt.date, list[dict]]:
    """Scrape Disposition by Rep + Time Tracker gaps for `office_name`'s
    office for `target` (default: yesterday, Central Time), merged by badge
    ID — exactly like total_knocks.pull.pull_disposition_day, but inside the
    session it impersonates `office_name` first and exits impersonation
    after.

    Returns (date, [rep_record, ...]) with each record keyed by
    SHEET_COLUMNS. Reps with no Time Tracker row keep Gaps / Total Gaps
    blank (per Eve), identical to Raf's pull.

    `office_name` defaults to RASHAD_KNOCKS_OFFICE ("Rashad Reed"). The name
    is resolved through the canonical ICD alias list, and the per-row search
    in _find_owner_and_impersonate also tries every known alias.
    """
    office_name = office_name or DEFAULT_OFFICE
    target = target or knocks._yesterday()

    # Resolve any spelling drift to the canonical name up front, so logs +
    # the office-row search start from the canonical spelling. The search
    # itself (get_search_candidates inside the helper) still tries aliases.
    aliases_raw = load_aliases()
    canonical = alias_to_canonical(office_name, aliases_raw)
    if verbose and canonical != office_name:
        print(f"-> Office '{office_name}' resolves to canonical '{canonical}'",
              flush=True)

    with ownerville_session(verbose=verbose) as page:
        return pull_office_on_page(page, canonical, aliases_raw, target,
                                   verbose=verbose)


def pull_office_days_on_page(page, canonical: str, aliases_raw,
                             targets: "list[dt.date]", *,
                             verbose: bool = True,
                             campaign: "str | None" = None) -> "dict":
    """SEVERAL days for one office on an ALREADY-OPEN page: impersonate
    `canonical` ONCE, scrape each day in `targets`, exit impersonation once.
    Returns {date: rows}.

    Why days loop INSIDE the impersonation: switching offices is the expensive
    step (Office Access page, row search, token handoff) and the sticky-campaign
    pin goes with it. A day is just a re-navigation of p=89 plus one JSON fetch,
    so a week costs one impersonation, not seven.

    NOT a date-range request to ownerville, deliberately: p=510 (Time Tracker)
    has no range parameter, and 'Avg. Hrs Knocking' is single-day clock
    arithmetic that a server-side aggregate would silently break. The days are
    folded afterwards by total_knocks.aggregate, where the arithmetic is right
    and each day stays individually cacheable.
    """
    out: dict = {}
    # Bound every op so a stuck page can't hang the run (same guard
    # run_all_owners uses).
    page.set_default_timeout(60_000)
    page.set_default_navigation_timeout(60_000)

    # Clear any lingering impersonation from a prior interrupted run so
    # the ?p=901 navigation below isn't bounced back to ?p=2. Always
    # safe — returns False if not currently impersonating.
    if _exit_impersonation(page) and verbose:
        print("  ✓ Cleared lingering impersonation from prior session",
              flush=True)

    # --- IMPERSONATE the target office --------------------------------
    if not _navigate_to_office_access(page):
        raise RuntimeError(
            "Couldn't reach the ownerville Office Access page (?p=901) to "
            f"impersonate {canonical!r}.")
    # _find_owner_and_impersonate returns the FRESH rqst for the
    # impersonated session (the server hands back a new token), so we
    # don't need to re-capture it separately.
    rqst, reason = _find_owner_and_impersonate(page, canonical, aliases_raw)
    if not rqst:
        raise RuntimeError(
            f"Couldn't impersonate {canonical!r} in ownerville: {reason}")
    if verbose:
        print(f"  ✓ Impersonated {canonical!r}; rqst={rqst[:8]}…",
              flush=True)
    # PROVE IT. "Impersonated" above only means confirmImpersonate was called,
    # not that ownerville switched — and the token cannot tell us, so this asks
    # the page which office it is actually on.
    assert_impersonating(page, rqst, canonical, aliases_raw, verbose=verbose)

    try:
        # Defensive: prefer the live page's rqst if the post-impersonate
        # navigation landed on a URL with a newer token. page_rqst falls
        # back to the value we already have.
        rqst = page_rqst(page) or rqst

        # Sticky-campaign guard — see KNOCKS_CAMPAIGN_ID above. Pinned once
        # for the impersonated session, not once per day: the campaign is a
        # property of the session, and re-pinning would cost a navigation a day.
        # `campaign` overrides the per-office map for THIS pull. Needed the
        # moment one office runs TWO campaigns: Jay Turnage knocks AT&T and
        # Energy Wells and gets a separate report for each (Raf: "not
        # combined, 2 separate reports"), which a map keyed by office NAME
        # cannot express — it holds one value per office.
        # WARM THE GRID BEFORE PINNING. The pin is a no-op on a session that
        # has not loaded the Disposition grid yet — measured on Lucy 1
        # 2026-09-01, impersonating Calvin (Energy Wells, campaign 40):
        #
        #   impersonate -> pin -> p=89   ->  ID, Rep, ..., Corp - No Opp, ...
        #                                    (the UNPINNED B2B grid, no VL)
        #   impersonate -> p=89 -> pin -> p=89  ->  ..., VL, Presentation, ...
        #
        # Same call, same campaign id; only the order differs. So the office's
        # column set — and therefore its BOARD SHAPE — was decided by whatever
        # had happened to load the grid before it, which is why Calvin rendered
        # `energywell` in the afternoon and `wireless` after the session was
        # re-minted, silently losing Chan's comparison line and the average
        # columns (the wireless renderer accepts neither).
        #
        # One extra navigation per office pull, once — not once per day.
        if targets:
            try:
                knocks._navigate(page, rqst, targets[0].strftime("%m/%d/%Y"))
            except Exception:  # noqa: BLE001 — the pin below is the point;
                pass           # a warm-up that fails must not kill the pull
        _pin_campaign(page, rqst,
                      campaign if campaign is not None
                      else campaign_for_office(canonical),
                      verbose=verbose)

        for target in targets:
            out[target] = _scrape_day_on_page(page, rqst, target,
                                              verbose=verbose,
                                              expect_campaign=campaign)
    finally:
        # ALWAYS exit impersonation before the session closes so the
        # next run / other reports start from master, not a stuck
        # impersonated state.
        if _exit_impersonation(page):
            if verbose:
                print("  ✓ Exited impersonation", flush=True)
        elif verbose:
            print("  ⚠ Exit-impersonation call didn't succeed", flush=True)

    return out


def _scrape_day_on_page(page, rqst: str, target: dt.date, *,
                        verbose: bool = True,
                        expect_campaign: "Optional[str]" = None) -> list:
    """ONE day's rows on a page that is already impersonating the right office
    with its campaign pinned — Disposition by Rep merged with Time Tracker
    gaps, exactly as pull_office_on_page always did inline. Extracted so the
    multi-day loop and the single-day wrapper can't drift apart."""
    mdy = target.strftime("%m/%d/%Y")

    # --- SCRAPE (identical to pull_disposition_day) ---------------
    if verbose:
        print(f"-> Disposition by Rep for {mdy} (rqst {rqst[:12]}…)",
              flush=True)
    knocks._navigate(page, rqst, mdy)
    idx = knocks._header_index(page)
    # PROVE THE PIN TOOK, before a single number is read off this grid. Under
    # impersonation the campaign can silently stay where it was, and a board
    # with the right title and another campaign's numbers is worse than no
    # board — nobody reading it can tell.
    assert_campaign_grid(idx, expect_campaign)
    # A WIRELESS (NDS) office's Disposition table has its own shape —
    # scrape it with the wireless column set instead of letting the house
    # scrape raise "missing expected column(s)". The wireless rows keep
    # COL_TOTAL_KNOCKS, so knocks_run renders a real Total Knocks board.
    if is_b2b_dispo(idx):
        # BEFORE every other test: both B2B grids satisfy the wireless one (they
        # carry Total Knocks and no house Talk-To split), and the wireless
        # scrape zero-fills what it cannot find — so B2B would come back as a
        # plausible board with every disposition at 0.
        rows = _scrape_b2b_rows(page, idx)
        if verbose:
            print(f"-> B2B-shaped disposition: {len(rows)} rep(s)", flush=True)
    elif _is_energywell_dispo(idx):
        # BEFORE the wireless test: Energy Wells has no Talk-To split either,
        # so the wireless check would claim it and drop VL and Presentation.
        rows = _scrape_energywell_rows(page, idx)
        if verbose:
            print(f"-> Energy-Wells-shaped disposition: {len(rows)} rep(s)",
                  flush=True)
    elif _is_wireless_dispo(idx):
        rows = _scrape_wireless_rows(page, idx)
        if verbose:
            print(f"-> Wireless-shaped disposition: {len(rows)} rep(s)",
                  flush=True)
    else:
        rows = knocks._scrape_rows(page, idx)
    # Supplementary while we have disposition rows, the last source
    # standing when we don't — only then is a failed fetch fatal.
    tt = knocks._scrape_time_tracker(page, rqst, mdy, verbose=verbose,
                                     required=not rows)
    if verbose:
        print(f"-> Time Tracker: gap data for {len(tt)} rep(s)", flush=True)

    # A wireless/NDS owner has NO Disposition campaign, so p=89 returns 0
    # rows and there's nothing to hang the gaps on. Build Time-Gaps rows
    # straight from the Time Tracker (name + knock times live in its JSON)
    # while the session is still open. Only the Time Gaps board renders;
    # knocks_run skips Total Knocks when there's no knock data.
    if not rows:
        gap_rows = knocks._scrape_time_tracker_rows(page, rqst, mdy,
                                                    verbose=verbose)
        if gap_rows:
            if verbose:
                print(f"-> Disposition empty; {len(gap_rows)} Time-Tracker gap "
                      f"row(s) (gaps-only office).", flush=True)
            return gap_rows
        return []

    # --- Merge gaps onto disposition rows by badge ID (same as Raf's) -----
    matched = 0
    for rec in rows:
        rid = str(rec.get(COL_ID, "")).strip()
        if rid in tt:
            rec.update(tt[rid])
            matched += 1
    if verbose:
        print(f"-> Merged gaps onto {matched}/{len(rows)} disposition rep(s)",
              flush=True)
    return rows


def pull_office_on_page(page, canonical: str, aliases_raw, target: dt.date,
                        *, verbose: bool = True) -> tuple[dt.date, list[dict]]:
    """ONE day for one office on an already-open page — the original
    single-date entry point, now a thin wrapper over the multi-day loop so both
    paths impersonate, pin and scrape through identical code."""
    days = pull_office_days_on_page(page, canonical, aliases_raw, [target],
                                    verbose=verbose)
    return target, days.get(target, [])


def is_master_office(name: str) -> bool:
    """Is `name` the MASTER ownerville office — the login itself?

    The rhidalgo login IS office 11280, so Raf is not in his own Office Access
    list and `_find_owner_and_impersonate` can never find him. Asking for him
    by impersonation fails with "name not found in ownerville", which reads
    exactly like a permissions gap and is not one (Megan 2026-08-24: `/knocks
    Rafael Hidalgo` answered "16 offices are in this position").
    """
    from automations.focus_office_att.aliases import _norm_name
    from automations.weekly_knock_dispositions.offices import RAF
    return _norm_name(name or "") == _norm_name(RAF["name"])


# The ownerville page header names the signed-in account and its office id,
# e.g. "RAFAEL HIDALGO - Owner • ALPHALETE SPECIALIZED MARKETING, INC.-TX
# (11280)". Reading it is the ONLY way a run can tell which owner's data it is
# about to publish: the login is a machine-wide credential file, so a session
# can be a different owner than the report thinks without anything erroring.
MASTER_OFFICE_ID = "11280"          # rhidalgo — the login IS Raf's office
_OFFICE_ID_RE = re.compile(r"\((\d{4,6})\)")


def logged_in_office(page) -> tuple:
    """(header_text, office_id) for the account this ownerville session is
    signed in as. office_id is "" when the header can't be read — an unreadable
    header must not be treated as a mismatch, only a mismatch is."""
    try:
        head = " ".join((page.inner_text("body") or "")[:200].split())
    except Exception:  # noqa: BLE001 — identity is a check, never the failure
        return ("", "")
    m = _OFFICE_ID_RE.search(head)
    return (head, m.group(1) if m else "")


def pull_master_days_on_page(page, targets: "list[dt.date]", *,
                             verbose: bool = True) -> "dict":
    """The master office's rows for SEVERAL days on an ALREADY-OPEN page — no
    impersonation, because the session is already on that office. Returns
    {date: rows}.

    Same steps as the impersonated path minus the office switch: capture rqst,
    pin the campaign (the sticky-campaign guard applies to the master session
    too), then Disposition + Time Tracker merged by badge id per day. Lived
    inline in captainship_drafts.knock_dispo_images._daily_rows_for_owner until
    on-demand `/knocks` needed the same routing; extracted here so the two
    callers share ONE master scrape instead of keeping two copies in step.
    """
    # WHO ARE WE? The master path does not impersonate — it publishes whatever
    # office the session happens to be signed into, under Raf's name. On
    # 2026-09-01 Lucy 1's ownerville credential file said `chidalgo`, so the
    # session was Carlos's office 11580 and this function scraped it as Raf's
    # board with no error anywhere. Wrong numbers under the right title are
    # worse than no board, so a mismatch stops the pull.
    head, office_id = logged_in_office(page)
    if office_id and office_id != MASTER_OFFICE_ID:
        raise RuntimeError(
            "ownerville is signed in as office %s, not the master office %s — "
            "refusing to publish that office's reps as Raf's. Fix the login on "
            "this machine (ownerville-creds.json must be the rhidalgo account) "
            "and re-run. Header: %r"
            % (office_id, MASTER_OFFICE_ID, head[:120]))
    rqst = knocks._capture_rqst(page)
    if not rqst:
        raise RuntimeError("Couldn't capture ownerville rqst token from "
                           f"{page.url!r} for the master office.")
    from automations.weekly_knock_dispositions.offices import RAF as _RAF
    _pin_campaign(page, rqst, campaign_for_office(_RAF["name"]),
                  verbose=verbose)
    out: dict = {}
    for target in targets:
        rows = _scrape_day_on_page(page, rqst, target, verbose=verbose)
        if verbose:
            print(f"-> master office {target}: {len(rows)} rep(s)", flush=True)
        out[target] = rows
    return out


def pull_master_on_page(page, target: dt.date, *, verbose: bool = True) -> list:
    """ONE day for the master office — the original entry point, wrapping the
    multi-day loop so both paths run identical code."""
    return pull_master_days_on_page(page, [target], verbose=verbose).get(
        target, [])


def pull_offices_days(jobs, verbose: bool = True, profile_dir=None):
    """Scrape SEVERAL offices, each for its OWN list of days, in ONE session.

    `jobs`: [(office_name, [date, ...]), ...]. Per-office date lists rather
    than one shared list because the caller's two offices rarely need the same
    days — the board's office may be missing Thursday while the comparison
    office is missing all week, and pulling days we already have on disk is
    pure waste.

    Returns [(office_name, {date: rows}, error_or_None), ...] in the order
    given. One office raising does NOT abort the rest — its error rides in the
    tuple so the caller can report it per office. A partial failure mid-office
    loses that office's whole dict: the days share one impersonation, so there
    is no half-office state worth handing back.
    """
    aliases_raw = load_aliases()
    out: list = []
    with ownerville_session(verbose=verbose, profile_dir=profile_dir) as page:
        for job in jobs:
            # (name, days) or (name, days, campaign) — the third element pins
            # THIS pull's campaign, for an office that runs more than one.
            name, targets = job[0], job[1]
            campaign = job[2] if len(job) > 2 else None
            targets = sorted(set(targets))
            canonical = alias_to_canonical(name, aliases_raw)
            if verbose and canonical != name:
                print(f"-> Office '{name}' resolves to canonical '{canonical}'",
                      flush=True)
            if verbose and len(targets) > 1:
                print(f"-> {canonical}: {len(targets)} day(s), "
                      f"{targets[0]} → {targets[-1]}", flush=True)
            try:
                if is_master_office(canonical):
                    # The login IS this office — impersonating it would fail.
                    days = pull_master_days_on_page(page, targets,
                                                    verbose=verbose)
                else:
                    days = pull_office_days_on_page(page, canonical,
                                                    aliases_raw, targets,
                                                    verbose=verbose,
                                                    campaign=campaign)
                out.append((name, days, None))
            except Exception as e:  # noqa: BLE001 — one office must not kill the rest
                if verbose:
                    print(f"  ✗ {name}: {type(e).__name__}: {str(e)[:120]}",
                          flush=True)
                out.append((name, {}, e))
    return out


def pull_offices_knocks(office_names, target: Optional[dt.date] = None,
                        verbose: bool = True, profile_dir=None):
    """Scrape SEVERAL offices inside ONE ownerville session, one day each.

    Why one session: each `ownerville_session` launches real Chrome on a shared
    user-data-dir, and the next launch can be adopted by the one before it if
    that Chrome hasn't fully exited ("Opening in existing browser session" —
    the profile race that cost other_office_knocks its second office on
    2026-08-18, even with the built-in 4x8s retry). One login, one browser,
    offices in turn — and it's faster, because the login is paid once.
    Impersonation is exited between offices exactly as the single-office path
    does, so each office starts from master.

    `profile_dir`: run on a Chrome profile of your own instead of the shared
    one, so a run that overlaps another browser report doesn't lose the launch
    race (the shared profile is first-come, first-served).

    Returns (target, [(office_name, rows, error_or_None), ...]) in the order
    given. One office raising does NOT abort the rest — its error rides in the
    tuple so the caller can report it per office.

    A thin wrapper over `pull_offices_days` since on-demand ranges arrived;
    every existing caller keeps this exact signature and return shape.
    """
    target = target or knocks._yesterday()
    out = [(name, days.get(target, []), err)
           for name, days, err in pull_offices_days(
               [(n, [target]) for n in office_names],
               verbose=verbose, profile_dir=profile_dir)]
    return target, out


def _print_preview(office_name: str, target: dt.date, rows: list[dict]) -> None:
    print(f"\n=== {office_name} — Disposition by Rep — {target.isoformat()} "
          f"({len(rows)} rep(s)) ===")
    show = [COL_ID, "Rep", "Total Knocks", "Total Talk to",
            "First Knock", "Last Knock", "Sale", COL_GAPS, COL_TOTAL_GAPS]
    print("  " + " | ".join(f"{c}" for c in show))
    for r in rows[:25]:
        print("  " + " | ".join(str(r.get(c, "")) for c in show))
    if len(rows) > 25:
        print(f"  … +{len(rows) - 25} more")


def main() -> int:
    target = None
    if len(sys.argv) > 1:
        target = dt.datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    office_name = DEFAULT_OFFICE
    target, rows = pull_office_knocks(office_name, target)
    _print_preview(office_name, target, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
