"""Consolidated Applicant Tracker sync — the four ApplicantStream reports merged
into ONE module with two phases, so the whole thing is one Hub card + one login.

WHY TWO PHASES (not one run): it's about what each part READS, not the sheet.
  * MORNING  reads YESTERDAY  -> runs in the 4am orchestrator, ready by morning:
        - Export Call List      (Call List tab: owner A, data B-H)
        - Update 2R Status      (2R tab: Offered H / Follow-up I / Notes J)
  * EVENING  reads TODAY       -> must run end-of-day (~8pm), after the data exists:
        - Export 2R Retention   (2R tab: owner AT, 9 cols AU-BC)
        - Confirm First-Day     (2R tab: col R = Y/N)  [DRY until verified]

EFFICIENCY: one ApplicantStream login for the whole phase; each office is
selected ONCE and its Retention report loaded ONCE — all the detail links that
phase needs are collected from that single load (detail_href doesn't navigate),
then each is visited. That replaces the old 4-separate-logins,
reload-report-before-every-metric approach.
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import argparse
import datetime as dt

from . import config
from . import sheets
from .applicantstream import OfficeNotAvailable, session

# --- Hub card identity (the pill counts successful runs by this id) ---
CARD_ID = "applicant-tracker-sync"
CARD_NAME = "Applicant Tracker Sync"

ESTIMATED_MINUTES = 12
REPORT_BREAKDOWN = """
WHAT IT DOES: One login syncs all of ApplicantStream into the Applicant Tracker.
MORNING phase (reads YESTERDAY): appends the Call List (owner A, B-H) and updates
second-round status on the 2R tab (Offered H, Follow-up I, BOB/Notes J).
EVENING phase (reads TODAY): appends Total Second Interviews to 2R (owner AT,
AU-BC) and marks first-day-training show-up in 2R col R.
SOURCE: ApplicantStream Retention Details detail pages, per office (17 offices).
PRE-FLIGHT: (1) service-account key present + sheet shared with it;
(2) one-time headed browser login saved; (3) ApplicantStream login current in
the sheet's README tab (B1/B2). First-Day is DRY until verified on a real
first-day-of-training day (FIRST_DAY_LIVE).
""".strip()

# First-Day (col R) stays computed-but-not-written until it's verified on a day
# with real first-day-of-training people (build day had zero) — it still prints
# the marks it WOULD write, so a real day can be checked without risk.
#
# HOW TO VERIFY (Francia, 2026-07-24): nobody runs orientation on Fridays, so the
# first checkable day is a MONDAY. Compare the [first-day dry] Y/N counts against
# the "CR Show" column = column AG on the "Accounts" tab of the tracker sheet
# (that tab's HEADER IS ROW 2, not row 1; AG is near-empty on non-orientation
# days — expected). If they agree, flip this True. If they don't, the mapping is
# probably wrong: swap L_TRAINING to "Total New Starts Scheduled".
FIRST_DAY_LIVE = False

# --- Retention detail-page row labels ---
L_CALL_LIST = "Sent to Call List"
L_2ND_ROSTER = "Total Second Interviews"
L_2ND_SHOWED = "Second Interviews Showed Up"
L_OFFERED = "Offered Job From Second Round"
L_BOB = "Total Daily Bob"
L_TRAINING = "Total Training"
L_TRAINING_SHOWED = "Training Showed Up"

N_CALL_COLS = 7   # Call List tab -> B..H
N_2R_COLS = 9     # 2R tab -> AU..BC


def date_header_for(target: dt.date) -> str:
    return target.strftime("%b %-d, %Y")  # e.g. "Jul 21, 2026"


def clean_owner_name(name: str) -> str:
    """'Rafael Hidalgo TX' -> 'Rafael Hidalgo' (strip a trailing 2-letter state)."""
    parts = name.strip().split()
    if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isupper():
        parts = parts[:-1]
    return " ".join(parts)


# ---- MORNING: Call List + 2R Status (reads YESTERDAY) --------------------
def _morning_office(app, ws_call, ws_2r, office_id: str, header: str) -> None:
    owner = app.select_office(office_id)  # raw owner (Call List keeps the state)

    # ONE report load -> collect every detail href this phase needs.
    app.open_retention_details()
    h_call = app.detail_href(L_CALL_LIST, header)
    h_roster = app.detail_href(L_2ND_ROSTER, header)
    h_showed = app.detail_href(L_2ND_SHOWED, header)
    h_offered = app.detail_href(L_OFFERED, header)
    h_bob = app.detail_href(L_BOB, header)

    # --- Export Call List ---
    call_rows = app.scrape_at(h_call, N_CALL_COLS)
    if call_rows:
        start = sheets.first_empty_row_in_column(ws_call, "A")
        sheets.paste_block(ws_call, start, "A", [[owner]] * len(call_rows))
        sheets.paste_block(ws_call, start, "B", call_rows)
        print(f"  [{office_id}] {owner}: Call List +{len(call_rows)} (row {start})")
    else:
        print(f"  [{office_id}] {owner}: no Call List for {header}")

    # --- Update 2R Status ---
    roster = app.names_at(h_roster)
    if not roster:
        print(f"  [{office_id}] no second interviews {header} -- 2R status skipped")
        return
    showed = app.names_at(h_showed)
    offered = app.names_at(h_offered)
    bob = app.names_at(h_bob)
    # Brought-on-board dates come from the calendar (only needed if anyone was
    # BOB). Best-effort: on the warm patchright session the jQuery calendar nav
    # is invisible, so bob_dates comes back empty and Notes(J) stays blank — the
    # rest of the status still writes. See applicantstream.open_calendar_for.
    bob_dates = {}
    if bob:
        app.open_calendar_for(_header_to_date(header))
        bob_dates = app.scrape_calendar_bob_dates()  # {name_lower: "Jul 27"}

    updated = 0
    for name in roster:
        row = sheets.find_row_by_name(ws_2r, name, 1)  # col A = Full Name
        if not row:
            continue
        if name in offered:
            sheets.set_cell(ws_2r, row, "H", "yes")
        if name not in showed:
            sheets.set_cell(ws_2r, row, "I", "no show")
        elif name in bob:
            sheets.set_cell(ws_2r, row, "I", "BOB")
            d = bob_dates.get(name.strip().lower())
            if d:
                sheets.set_cell(ws_2r, row, "J", d)
        updated += 1
    print(f"  [{office_id}] 2R status: {updated}/{len(roster)} matched")


# ---- EVENING: 2R Retention + First-Day (reads TODAY) --------------------
def _evening_office(app, ws_2r, office_id: str, header: str) -> None:
    owner = clean_owner_name(app.select_office(office_id))  # 2R Retention strips state

    app.open_retention_details()
    h_2nd = app.detail_href(L_2ND_ROSTER, header)
    h_train = app.detail_href(L_TRAINING, header)
    h_show = app.detail_href(L_TRAINING_SHOWED, header)

    # --- Export 2R Retention ---
    ret_rows = app.scrape_at(h_2nd, N_2R_COLS)
    if ret_rows:
        start = sheets.first_empty_row_in_column(ws_2r, "AT")
        sheets.paste_block(ws_2r, start, "AT", [[owner]] * len(ret_rows))
        sheets.paste_block(ws_2r, start, "AU", ret_rows)
        print(f"  [{office_id}] {owner}: 2R Retention +{len(ret_rows)} (row {start})")
    else:
        print(f"  [{office_id}] {owner}: no Total Second Interviews for {header}")

    # --- Confirm First-Day (col R) --- gated until verified
    scheduled = app.names_at(h_train)
    if not scheduled:
        return
    showed = app.names_at(h_show)
    for name in scheduled:
        row = sheets.find_row_by_name(ws_2r, name, 1)
        if not row:
            continue
        mark = "Y" if name in showed else "N"
        if FIRST_DAY_LIVE:
            sheets.set_cell(ws_2r, row, "R", mark)  # respects sheets.DRY_RUN
        else:
            print(f"    [first-day dry] R{row}={mark} for {name} "
                  "(not written — FIRST_DAY_LIVE off)")


def _header_to_date(header: str) -> dt.date:
    return dt.datetime.strptime(header, "%b %d, %Y").date()


def run(phase: str, target: dt.date | None = None) -> None:
    phase = phase.lower()
    if phase not in ("morning", "evening"):
        raise ValueError(f"phase must be 'morning' or 'evening', got {phase!r}")

    if phase == "morning":
        target = target or (dt.date.today() - dt.timedelta(days=1))  # yesterday
    else:
        target = target or dt.date.today()                            # today
    header = date_header_for(target)
    print(f"=== Applicant Tracker: {phase.upper()} phase for {header} "
          f"({len(config.OFFICE_IDS)} offices)"
          f"{' [DRY-RUN]' if sheets.DRY_RUN else ''} ===")

    ws_2r = sheets.open_tab(config.TAB_2R)
    ws_call = sheets.open_tab(config.TAB_CALL_LIST) if phase == "morning" else None

    failed: list[str] = []
    no_access: list[str] = []
    with session() as app:
        for office_id in config.OFFICE_IDS:
            print(f"[{office_id}] selecting office...")
            try:
                if phase == "morning":
                    _morning_office(app, ws_call, ws_2r, office_id, header)
                else:
                    _evening_office(app, ws_2r, office_id, header)
            except OfficeNotAvailable as e:
                # Kept apart from `failed`: this one will fail identically every
                # night until somebody grants access or drops the id, so it must
                # not read as a flaky run you can just re-kick.
                no_access.append(str(office_id))
                print(f"  ⛔ [{office_id}] NO ACCESS: {e}")
            except Exception as e:  # noqa: BLE001 -- one office must not sink the rest
                failed.append(str(office_id))
                print(f"  ! [{office_id}] error: {type(e).__name__}: {str(e)[:120]}")

    # Gap report — name the offices that did NOT sync, at the end where the log
    # tail actually shows it. Per-office errors are swallowed above so one bad
    # office can't sink the other 16; without this line that isolation also
    # hides them.
    total = len(config.OFFICE_IDS)
    if failed:
        print(f"!! {len(failed)} of {total} office(s) did NOT sync: "
              f"{', '.join(failed)}")
    if no_access:
        print(f"!! {len(no_access)} of {total} office(s) are NOT VISIBLE to this "
              f"login ({config.__name__} OFFICE_IDS): {', '.join(no_access)} — "
              "this repeats nightly until access is granted or the id is removed")

    # Report completion for the Hub pill. Only real (non-dry) runs count.
    #
    # The card follows the SAME rules as every other report: a completed run is
    # SUCCESS (green). A missed office no longer holds the pill amber — instead
    # the gap is posted to the corrections channel so it's still visible (Megan
    # 2026-07-25, revised: green + Slack the gap, not an amber pill).
    if not sheets.DRY_RUN:
        try:
            from automations.shared import hub_activity
            hub_activity.log_completed(CARD_ID, CARD_NAME, status="success")
        except Exception:
            pass
        # Any office that did NOT sync (a genuine error OR a no-access gap) goes
        # to #claudecorrections-and-requests so the miss is seen even though the
        # pill is green. Best-effort — a Slack hiccup never fails the run.
        if failed or no_access:
            try:
                from automations.day_orchestrator import notify
                from automations.day_orchestrator.registry import load_config
                lines = ["🗂️ *Applicant Tracker — {} run: {} of {} office(s) "
                         "did not sync*".format(
                             phase, len(failed) + len(no_access), total)]
                if no_access:
                    lines.append("• No access ({}): {}".format(
                        len(no_access), ", ".join(no_access)))
                if failed:
                    lines.append("• Errored ({}): {}".format(
                        len(failed), ", ".join(failed)))
                notify._post_corrections(load_config(), None, lines,
                                         dry_run=False,
                                         tag="applicant-tracker-gaps")
            except Exception as e:  # noqa: BLE001 — Slack must not fail the run
                print("  (corrections post skipped: {})".format(e))
    print(f"=== {phase.upper()} phase done ===")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Applicant Tracker consolidated sync")
    p.add_argument("phase", choices=["morning", "evening"],
                   help="morning = Call List + 2R Status (yesterday); "
                        "evening = 2R Retention + First-Day (today)")
    p.add_argument("--dry-run", action="store_true",
                   help="run end to end but write NOTHING to the Sheet")
    p.add_argument("--office", action="append", metavar="ID",
                   help="limit to office id(s); repeatable")
    p.add_argument("--date", metavar="YYYY-MM-DD", help="override the target date")
    a = p.parse_args()
    if a.dry_run:
        sheets.DRY_RUN = True
    if a.office:
        keep = {str(o).strip() for o in a.office}
        config.OFFICE_IDS = [o for o in config.OFFICE_IDS if o in keep]
    run(a.phase, dt.date.fromisoformat(a.date) if a.date else None)
