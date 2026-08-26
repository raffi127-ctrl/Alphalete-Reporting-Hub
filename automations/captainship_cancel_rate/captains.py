"""The 5 ATT Fiber captains + their tabs in the Cancel Rate workbook.

Adding / removing a captain = edit CAPTAINS only; run.py iterates it.

Tabs are resolved by TITLE, never by gid — a sandbox copy of the workbook
re-assigns every gid, so the gid here is reference-only (for logging and for
building the deep-link the Hub card shows).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# "Captainship Metrics Report - Cancel Rate" — the live workbook.
REAL_SHEET_ID = "1P95BxzlmLKkuvcL0gqjD9EfEHPLniGN-m4eE9UsPe_E"

# Sandbox = a duplicate of the real workbook, for practice runs only. The
# report writes to the LIVE workbook by default (Eve 2026-07-28: these tabs
# were created from scratch for this report, so there's nothing to protect) —
# --sandbox is the opt-in, not the other way round.
# Set CANCEL_RATE_SANDBOX_SHEET_ID to point at a different duplicate.
SANDBOX_SHEET_ID = os.environ.get(
    "CANCEL_RATE_SANDBOX_SHEET_ID",
    "1Je8W3Pv5sQ1GurNQeExBQBimzgDjN5gAxJq2o7P17-M")


def sheet_id(sandbox: bool = False) -> str:
    """Destination workbook — the live one unless `sandbox`. Env override wins
    (lets the Hub / scheduler retarget without a code change)."""
    override = os.environ.get("CANCEL_RATE_SHEET_ID", "").strip()
    if override:
        return override
    return SANDBOX_SHEET_ID if sandbox else REAL_SHEET_ID


@dataclass(frozen=True)
class Captain:
    slug: str    # --only value
    tab: str     # worksheet title in the Cancel Rate workbook
    gid: int     # worksheet id in the REAL workbook (deep-links / logging)
    team: str    # the Tableau "Captain's Bonus Teams" filter value


CAPTAINS: list[Captain] = [
    Captain("wayne", "Cancel Rate - Wayne (ATT Fiber)", 2129685820, "Wayne's Team"),
    Captain("starr", "Cancel Rate - Starr (ATT Fiber)", 957243792,  "Starr's Team"),
    Captain("chan",  "Cancel Rate - Chan (ATT Fiber)",  2086894353, "Chan's Team"),
    Captain("tony",  "Cancel Rate - Tony (ATT Fiber)",  797904270,  "Tony's Team"),
    Captain("sahil", "Cancel Rate - Sahil (ATT Fiber)", 367210987,  "Sahil's Team"),
]

BY_SLUG = {c.slug: c for c in CAPTAINS}
SLUGS = [c.slug for c in CAPTAINS]

# ICDs who are WINDING DOWN — their row stays on the tab (the history is worth
# keeping) but they no longer come back from the Metrics view, so the run's
# "went dark" guard must not fail the report on them. Without this the report
# exits 1 every single morning for a permanent, correct blank — the trap
# country_sales_board documents at run.py:208 for this same set of people, and
# the one org_sales_board's daily compare already fell into.
#
# This list is DELIBERATELY per-name, never a blanket rule: an ICD who WAS
# producing and suddenly goes dark is exactly the signal the guard exists for
# (a dropped Captain's Bonus Teams filter, or a rename past the alias). Only
# add someone once you know they're on the way out.
#
# Remove a name here the day they come back and the guard covers them again.
INACTIVE_ICDS: dict[str, str] = {
    # Wayne's Team. Dropped out of the Metrics view 2026-08-10 (blank on BOTH
    # Cancel Rate and Activation Rate that morning, after 5 days flat at 0.00%
    # cancel / 100.00% activation). Already listed as an inactive rep absent
    # from the view in country_sales_board. Eve 2026-08-10: on the way out.
    "mason davis": "winding down — off the Metrics view since 2026-08-10 (Eve)",
    # Starr's Team. Same shape as Mason Davis: 0-30 sat flat at 0.00% for five
    # days (8/14-8/18), then 2026-08-19 both sections went blank at once — he
    # dropped out of the Metrics pull entirely, not a filter that broke. Backed
    # by the two-week zero rule the same morning: WE 08.09 and WE 08.16 both
    # closed at 0 on Starr's Fiber boxes (output/org_board_zero_two_weeks_
    # 2026-08-19.csv), so he came off the boards and is pinned in
    # new_owners/captain_gate.EXCLUDE["Starr"]. Row stays for the history.
    "jason strid": "winding down — off the Metrics view since 2026-08-19, "
                   "two-week zero rule (Eve)",
    # Sahil's Team. Third time this exact shape: 0-30 flat at 0.00% for five
    # days (8/15-8/19), then 2026-08-20 BOTH sections went blank at once — on
    # the Activation Rate tabs too (66.70% / 75.00% on 8/19, nothing since), so
    # he left the Metrics view itself, not one report's filter. He is on no
    # other captain's tab either, so it is not a move to another captainship.
    # Three closed weeks at 0 on the board (WE 08.02, 08.09, 08.16) and Eve had
    # already taken him out of the "Sahil's Captainship" group on 2026-07-30.
    # He was held out of the 2026-08-19 two-week-zero batch because his WE
    # 07.26 / 07.19 columns were BLANK, not 0 (new owner, no history yet) —
    # that is no longer true. This entry only stops the daily false ping; the
    # four-place removal (roster_remove x2 + captain_gate.EXCLUDE["Sahil"] +
    # distro_remove) is still pending Eve's call.
    "jeremiah minor": "winding down — off the Metrics view since 2026-08-20 "
                      "(pending Eve's call on the full two-week-zero removal)",
    # Tony's Team. Pinned out of the captainship 2026-08-19 (two-week zero
    # rule, new_owners/captain_gate.EXCLUDE["Tony"]). His 0-30 had already been
    # reading "No Data" every day since ~8/16 — present in the view, 0 cancels
    # of 0 sales — and on 2026-08-26 the 30-60 went with it: he is off the
    # Captain's Bonus Teams filter entirely now. Confirmed the same morning on
    # the sibling Activation Rate - Tony tab (same pull, same view): both boxes
    # blank for him too, while every other owner on the tab filled. Rows stay
    # for the history.
    "melik el jaiez": "off the captainship 2026-08-19 (two-week zero rule); "
                      "out of the Metrics view since 2026-08-26 (Eve)",
    # Starr's Team. Same thing one week later: OUT 2026-08-25 under the
    # two-week zero rule — 0 in both of Starr's boxes for WE 08.16 and
    # WE 08.23, taken off Starr's captainship distro
    # (captainship_drafts/config.py) and pinned in
    # captain_gate.EXCLUDE["Starr"]. Unlike the wind-downs above there was no
    # run of 0.00% first: he filled real numbers in all four boxes through
    # 8/25 (22.20% / 25.80%) and vanished on 8/26, which is what the removal
    # looks like from this report's side — the roster change IS the cause, so
    # there is no filter or alias to chase.
    "william sassenberg": "off the captainship 2026-08-25 (two-week zero "
                          "rule); out of the Metrics view since 2026-08-26 "
                          "(Eve)",
}


def is_inactive(name: str) -> bool:
    """Is this ICD a known wind-down, i.e. is a blank today EXPECTED?"""
    return " ".join((name or "").split()).strip().lower() in INACTIVE_ICDS
