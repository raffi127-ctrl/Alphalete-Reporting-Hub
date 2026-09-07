"""Reports that are deliberately switched OFF — the one list, read by everyone.

It used to live in dashboard.py, which meant only the Hub could see it: the Hub
greyed Texas de Brazil's pill on 2026-09-05 and machine_digest's watcher, which
imports nothing from Streamlit, went on expecting it and opened
`standalone-june_texas_de_brazil_monthly_competition` — "didn't run today on the
mini" — two days later. A stand-down that only one surface knows about is not a
stand-down. Moved here (2026-09-07) so the Hub AND the watchers read the same
declaration; importable with no Streamlit.

PAUSED is not RETIRED. `hub_coverage._RETIRED` means the report is dead and
`is_internal()` hides it everywhere; a paused report keeps its card, its ⏸ pill
and its reason on hover, and is expected back. Retire something permanently dead;
pause something coming back.
"""

# STOOD-DOWN reports: card id -> why, in one line. These are switched off on
# purpose, so the Hub must stop counting them as due, stop advertising their
# schedule, and never put them on the morning triage list (Megan 2026-08-25).
#
# It lives here rather than as a card field because a self-registered LIBRARY
# card is a row in a Sheet, not a dict in hub_cards.py — tracker_mirror is one,
# so there is nowhere on the card to put the flag. A hand-written card can
# instead just set `"paused": "reason"` on itself; _paused_reason reads both.
#
# The stand-down that prompted this: tracker_mirror. Carlos switched it off on
# 2026-08-24 (5d4042b) because the manager tabs went back on live IMPORTRANGE, so
# a ferry pass would overwrite those formulas with frozen values. It is enforced
# by a DISABLED file on Lucy 1 that makes both run.py and deploy/tracker_mirror.sh
# refuse to run — but that file is on the RUNNER, invisible to a Hub on anyone's
# laptop, so the card went on showing "07:30 CST" and reading as overdue for a job
# that must not run. Running it would have been the wrong thing to do.
PAUSED_REPORTS = {
    # Both spellings on purpose: the library card is hyphenated, schedule_config
    # uses the underscored id, and _paused_reason() looks the card id up as-is.
    "energy-crossref": ("Retired 2026-09-01 (Rafael) — the Base Power Energy "
                        "program ended, so there are no sales to cross-check "
                        "and nobody to tag. energy_crossref/DISABLED stands the "
                        "module down; the Sales Board EN fill still runs."),
    "energy_crossref": ("Retired 2026-09-01 (Rafael) — the Base Power Energy "
                        "program ended, so there are no sales to cross-check "
                        "and nobody to tag. energy_crossref/DISABLED stands the "
                        "module down; the Sales Board EN fill still runs."),
    "energy-slack-fill": ("Retired 2026-09-01 (Eve) — the Energy program ended "
                          "and the board's per-day 'EN' column became 'TK' "
                          "(knocks) on 8/31, so this had nowhere left to write. "
                          "energy_slack_fill/DISABLED stands the module down."),
    "energy_slack_fill": ("Retired 2026-09-01 (Eve) — the Energy program ended "
                          "and the board's per-day 'EN' column became 'TK' "
                          "(knocks) on 8/31, so this had nowhere left to write. "
                          "energy_slack_fill/DISABLED stands the module down."),
    "tracker_mirror": ("Stood down 2026-08-24 (Carlos, 5d4042b) — the manager "
                       "tabs are on live IMPORTRANGE again, so a ferry pass "
                       "would overwrite those formulas with frozen values."),
    # Both spellings again: the library card id is the one the Hub renders,
    # `texas_de_brazil` is the schedule_config / `lucy rerun` key.
    "june_texas_de_brazil_monthly_competition": (
        "Paused 2026-09-05 (Rafael, #l10-alphalete) — the Texas de Brazil "
        "competition is ending for now; it may come back after R&R. The "
        "daily 7:45am post is stood down by "
        "deploy/texas_de_brazil_745.DISABLED — the wrapper and "
        "run_library_report both refuse to send while that file exists. "
        "Delete that file + this entry to restart it."),
    "texas_de_brazil": (
        "Paused 2026-09-05 (Rafael, #l10-alphalete) — the Texas de Brazil "
        "competition is ending for now; it may come back after R&R. The "
        "daily 7:45am post is stood down by "
        "deploy/texas_de_brazil_745.DISABLED — the wrapper and "
        "run_library_report both refuse to send while that file exists. "
        "Delete that file + this entry to restart it."),
}


def reason(report_id: str) -> str:
    """Why `report_id` is stood down, or '' if it is live."""
    return PAUSED_REPORTS.get(report_id or "", "")


def paused_ids() -> set:
    """Every id declared stood down, for the watchers' skip lists."""
    return set(PAUSED_REPORTS)
