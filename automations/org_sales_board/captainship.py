"""Locate + fill a captainship block on the Org Sales Board.

Each captain has a block titled "<NAME> CAPTAINSHIP" in col B, containing:
  • a weekly LEADERBOARD ("CAPTAIN TEAM" header; col C = this-week total,
    cols D+ = 12 weeks of history), ranked high→low.
  • a DAILY table ("<type> - All Units" + a Monday…Sunday header; cols C-I =
    Mon-Sun, J = running total, K = last week, L = previous).

Fill matches ICDs BY NAME (with aliases) — never by position — and is
WORKSHEET-SCOPED. We fill the daily Mon-Sun + running total and the
leaderboard's this-week total IN PLACE (no re-sort, per Megan 2026-05-31;
the go-live version will sort high→low). [[reference_org_board_sandbox_scoping]]
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from automations.focus_office_att.aliases import load_aliases

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday")


@dataclass
class CaptainAnchor:
    captain: str
    leaderboard: List[Tuple[int, str]] = field(default_factory=list)  # (row, name)
    week_total_col: int = 3          # col C (1-based)
    daily: List[Tuple[int, str]] = field(default_factory=list)         # (row, name)
    day_cols: List[int] = field(default_factory=list)  # 1-based cols for Mon..Sun
    running_col: int = 10            # col J


def _cell(grid, r, c):  # 0-based
    return (grid[r][c] if r < len(grid) and c < len(grid[r]) else "").strip()


def find_captainship(grid: List[List[str]], captain_title: str) -> CaptainAnchor:
    title_l = captain_title.strip().lower()
    n = len(grid)
    t = next((i for i in range(n)
              if title_l in _cell(grid, i, 1).lower()
              and "captainship" in _cell(grid, i, 1).lower()), None)
    if t is None:
        raise ValueError(f"captainship title for {captain_title!r} not found")
    a = CaptainAnchor(captain=captain_title)
    # Leaderboard: first 'CAPTAIN TEAM' (col A) below the title.
    cap = next(i for i in range(t, n) if _cell(grid, i, 0).upper() == "CAPTAIN TEAM")
    r = cap + 2  # skip the sub-label row ("Fiber - All Units")
    while r < n:
        if _cell(grid, r, 0).upper() == "TOTALS":
            break
        name = _cell(grid, r, 1)
        if name:
            a.leaderboard.append((r + 1, name))
        r += 1
    lb_end = r
    # Daily table: first row whose col C == 'Monday' below the leaderboard.
    dh = next(i for i in range(lb_end, n) if _cell(grid, i, 2).lower() == "monday")
    # That header row's weekday columns → day_cols (Mon..Sun, expect C..I).
    a.day_cols = [c + 1 for c in range(len(grid[dh]))
                  if _cell(grid, dh, c).lower() in WEEKDAYS]
    r = dh + 2  # skip the day-number row beneath the weekday header
    while r < n:
        if _cell(grid, r, 0).upper() in ("TOTALS", "TOTAL"):
            break
        name = _cell(grid, r, 1)
        if name:
            a.daily.append((r + 1, name))
        r += 1
    return a


def _a1col(c: int) -> str:  # 1-based col -> letter(s)
    s = ""
    while c > 0:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def fill_captainship(ws, anchor: CaptainAnchor, today, per_for,
                     dry_run: bool = False) -> list:
    """Fill a captainship's daily Mon-Sun + running total and the
    leaderboard's this-week total. `per_for(name)` returns that ICD's
    {date: value} dict (team view first, org-wide fallback) or {} if nowhere.
    Every no-sale day is written as 0 (Megan: insert 0, never blank).
    WORKSHEET-SCOPED. Returns ICDs found in NO pull (filled 0)."""
    assert ws.title == "Copy of Alphalete ORG Sales Board", ws.title
    from automations.org_sales_board import week as _wk
    monday = _wk.reporting_monday(today)  # rolls Tuesday — Monday = last week
    days = [monday + dt.timedelta(days=i) for i in range(len(anchor.day_cols))]
    L0, L1 = _a1col(anchor.day_cols[0]), _a1col(anchor.day_cols[-1])
    runL, wkL = _a1col(anchor.running_col), _a1col(anchor.week_total_col)
    updates, missing = [], []
    for row, name in anchor.daily:
        per = per_for(name)
        if not per:
            # No sales found in any view this week — write "NS" (No Sales)
            # across the row instead of 0 (Megan 2026-06-03), so a zero-
            # production rep reads clearly rather than looking like missing data.
            missing.append(name)
            # NS only on completed days (< today); today + future blank out —
            # they haven't happened yet (Megan 2026-06-03).
            updates.append({"range": f"{L0}{row}:{L1}{row}",
                            "values": [["" if d >= today else "NS"
                                        for d in days]]})
            updates.append({"range": f"{runL}{row}", "values": [["NS"]]})
            continue
        updates.append({"range": f"{L0}{row}:{L1}{row}",
                        "values": [["" if d >= today else int(per.get(d, 0))
                                    for d in days]]})
        updates.append({"range": f"{runL}{row}",
                        "values": [[f"=SUM({L0}{row}:{L1}{row})"]]})
    for row, name in anchor.leaderboard:
        per = per_for(name) or {}
        updates.append({"range": f"{wkL}{row}",
                        "values": [[sum(int(per.get(d, 0)) for d in days)]]})
    if not dry_run:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    return missing


# --------------------------------------------------------------- registry

# Per-type parse config + org-wide all-products fallback view (for ICDs on a
# captain's SHEET roster that aren't in their TEAM view — pulled, never copied
# from the VAs). [[feedback_captainship_roster_truth]]
_V = "https://us-east-1.online.tableau.com/#/site/sci/views/"
TYPES = {
    "fiber": {
        "metric": "Total",
        "parse": dict(owner_col="Owner Name",
                      crosstab_sheet="Sales By ICD (Weekly View)",
                      total_label="Total", exclude_products=("VOICE",)),
        "org": None,   # Fiber team views covered every roster ICD
    },
    "b2b": {
        "metric": "count",
        "parse": dict(owner_col="ICD Owner Name",
                      crosstab_sheet="Sales By ICD (ATT) (V2)"),
        "org": _V + ("ATTTRACKER-B2B/D2D1-PAGERV3/"
                     "e52b4954-dc0b-4f2a-a588-d218942f23a0/LuissCaptainship"),
    },
    "nds": {
        "metric": "Total",
        "parse": dict(owner_col="Owner & Office",
                      crosstab_sheet="Sales By ICD (Weekly View)",
                      total_label="Total", strip_office=True),
        "org": _V + ("NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep/"
                     "c6d0a461-f8ac-49ed-bb38-27a807328a70/"
                     "ALLPRODUCTS-EXPANDEDREPS"),
    },
}

# (sheet-title token, type, team-view URL). Title token feeds find_captainship.
CAPTAINS = [
    ("RAF", "fiber", _V + "ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/ab2eca72-395f-48d5-a254-9d99739b88d4/AllproductsRafsteam"),
    ("WAYNE", "fiber", _V + "ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/70f6a2a1-af9e-409b-9e9c-ac3ac20a85ab/AllproductsWaynesteam"),
    ("STARR", "fiber", _V + "ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/c29a4154-c77c-4416-8e06-379e7b431b60/AllproductsStarsteam"),
    # New fiber captainships (Aron's captainship dissolved 2026-06; its sheet
    # block is already gone). The per-captain team-view URL is VESTIGIAL —
    # _team_url is unused below; every captainship's sales come from the fiber
    # PROGRAMS all-teams pull. Placeholder until/if a real team view is wired.
    ("CHAN", "fiber", "VESTIGIAL-UNUSED-team-view-url"),
    ("TONY", "fiber", "VESTIGIAL-UNUSED-team-view-url"),
    ("SAHIL", "fiber", "VESTIGIAL-UNUSED-team-view-url"),
    ("CARLOS", "b2b", _V + "ATTTRACKER-B2B/D2D1-PAGERV3/32440800-0a5a-4f21-be33-f807ba5930a7/CarlosTeam"),
    ("EVELIZ", "b2b", _V + "ATTTRACKER-B2B/D2D1-PAGERV3/48735d6e-cf6a-48fa-8d24-6f790d2ba3b7/EvelizsTeam"),
    ("LUIS", "b2b", _V + "ATTTRACKER-B2B/D2D1-PAGERV3/8f51c40d-46c3-4ddc-bf64-ec769777f3eb/LuissTeam"),
    ("KHALIL", "nds", _V + "NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep/7f7d9a86-425b-438a-8838-ffb1d16cde63/KHALILSTEAM"),
    ("COLTEN", "nds", _V + "NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep/f6e61d86-e503-4c7d-9230-56b85048f402/COLTENSTEAM"),
    ("JAIRO", "nds", _V + "NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep/99c40989-62fd-4ffd-bc6e-c6e7fe78c0d7/JAIROSTEAM"),
]

# All-teams, all-products per-PROGRAM views (Megan 2026-06-03). Pull every ICD
# once per program, then assign each to its captainship via the SHEET roster —
# faster (3 pulls vs 10 team pulls) AND catches an ICD no matter which Tableau
# team it's filed under, closing the silent-miss gap the per-team pulls had.
# An ICD absent here genuinely has 0 sales this week (the crosstab omits zero
# rows) → filled NS, which matches the VAs' 0.
# [[feedback_captainship_roster_truth]] [[feedback_flag_nonmatched_icds]]
PROGRAMS = {
    "fiber": _V + ("ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/"
                   "c287b023-03c1-489b-9d44-978200018569/AllproductsALLTEAMS"),
    "b2b":   _V + ("ATTTRACKER-B2B/D2D1-PAGERV3/"
                   "49e48afc-de23-4d5d-98ad-e8b1b246d640/ALLTEAMS"),
    "nds":   _V + ("NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep/"
                   "c6d0a461-f8ac-49ed-bb38-27a807328a70/ALLPRODUCTS-EXPANDEDREPS"),
}


def _spec(label, view_url, parse, metric):
    from automations.org_sales_board import section_pull as sp
    return sp.ScrapeSpec(
        section_label=label, metric=metric, view_url=view_url,
        owner_col=parse["owner_col"], value_col="", day_col="",
        method=sp.CROSSTAB, crosstab_sheet=parse["crosstab_sheet"],
        total_label=parse.get("total_label", ""),
        exclude_products=parse.get("exclude_products", ()),
        strip_office=parse.get("strip_office", False),
        skip_owners=("Grand Total", "Sales Total"),
        week_pin=True,   # team/org views default to LAST week — pin to current
        out_name=f"org_sales_board_cap_{label}.csv")


def run_captainships(ws, page, *, today=None, dry_run=False,
                     resolve_csv=None, logfn=print) -> dict:
    """Pull + fill all 10 captainships under ONE patchright session.

    For each captain: pull the TEAM view crosstab, then look each SHEET-roster
    ICD up there first and in the org-wide all-products view as fallback. Fills
    worksheet-scoped. `resolve_csv(key, spec)` overrides the live download with
    a saved CSV path (offline tests); default pulls live via `page`.
    """
    import datetime as dt
    from pathlib import Path
    from automations.org_sales_board import section_pull as sp
    today = today or dt.date.today()
    aliases = load_aliases()
    grid = ws.get_all_values()

    def _pull(label, view_url, parse, metric):
        spec = _spec(label, view_url, parse, metric)
        if resolve_csv:
            csv = resolve_csv(label, spec)
        else:
            csv = sp.pull_section_byday(spec, Path("output"), page, logfn=lambda m: None, today=today)
        return sp.parse_byday(spec, csv, today)

    # Pull each PROGRAM's all-teams view ONCE (fiber, b2b, nds) — every ICD in
    # that program, no team filter. RESILIENT: a single program view that
    # fails to render (Tableau load/render flake → "0 thumbs", or a stale
    # custom view) must NOT crash the whole board run. Skip + flag it; its
    # captainship numbers stay blank this run and the rest still fills.
    # (Megan 2026-06-08: a PROG pull "0 thumbs" killed the entire run.)
    prog = {}
    failed_programs = []
    for tkey, view_url in PROGRAMS.items():
        t = TYPES[tkey]
        logfn(f"  program pull: {tkey}")
        try:
            prog[tkey] = _pull(f"PROG_{tkey}", view_url, t["parse"], t["metric"])
        except Exception as e:
            logfn(f"  ⚠ program pull {tkey} FAILED ({type(e).__name__}: "
                  f"{str(e)[:90]}) — skipping; {tkey} stays blank for all "
                  f"captainships this run. Re-run to retry.")
            prog[tkey] = {}
            failed_programs.append(tkey)

    summary = {"filled": [], "missing": {}, "failed_programs": failed_programs}
    for title, tkey, _team_url in CAPTAINS:
        t = TYPES[tkey]
        metric = t["metric"]
        pull = prog.get(tkey, {})
        logfn(f"  captainship {title} ({tkey})…")
        # A captainship in CAPTAINS with no matching block on the board must NOT
        # crash the whole run — skip it with a flag (mirrors rollover.py's
        # find_captainship guard). Happens when a captainship is dissolved (its
        # block removed) but still listed, or added to CAPTAINS before its sheet
        # block exists. Re-add the block (or remove it from CAPTAINS) to clear.
        try:
            anchor = find_captainship(grid, title)
        except Exception as e:
            logfn(f"    ⚠ no '{title} CAPTAINSHIP' block on the board "
                  f"({type(e).__name__}: {str(e)[:80]}) — skipping {title}.")
            continue

        # Roster-driven: each ICD on this captainship's sheet rows is matched
        # by name (+ aliases). Match the captainship's OWN program first; if
        # the ICD isn't there, fall back to ANY other program and pull its
        # numbers anyway — some reps sit on a captainship whose Tableau team
        # doesn't include them (e.g. Preppie Olison is on ARON/fiber but his
        # sales are in NDS — pull them regardless, Megan 2026-06-08). Absent
        # from EVERY program = 0 sales this week → NS.
        def per_for(name, prog=prog, tkey=tkey):
            cands = _candidates_for_name(name, aliases)
            for tk in [tkey] + [k for k in prog if k != tkey]:
                pdata = prog.get(tk, {})
                k = next((x for x in pdata if x in cands), None)
                if k:
                    return pdata[k].get(TYPES[tk]["metric"], {})
            return {}

        missing = fill_captainship(ws, anchor, today, per_for, dry_run=dry_run)
        summary["filled"].append(title)
        if missing:
            summary["missing"][title] = missing
        logfn(f"    {title}: {len(anchor.daily)} ICDs"
              + (f", 0-sales/not in program view (NS): {missing}" if missing else ""))
    logfn(f"=== captainships filled: {summary['filled']} "
          f"| 0-sales (NS): {summary['missing']} ===")
    if failed_programs:
        logfn(f"  ⚠ PROGRAM PULL(S) FAILED this run: {failed_programs} — those "
              f"programs are blank for all captainships; re-run to retry.")
    return summary


def _candidates_for_name(name, aliases):
    """ICD name → candidate normalized forms (board label + aliases). Thin
    wrapper over the fill engine's matcher so captainship matching stays in
    lockstep with the daily sections."""
    from automations.org_sales_board import fill_section as fs
    return fs._candidates_for(name, aliases)
