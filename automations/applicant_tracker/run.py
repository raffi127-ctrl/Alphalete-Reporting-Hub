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
import os
import sys
import threading
import time

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

# --- Time budgets ---------------------------------------------------------
# 2026-08-18: the morning run restored a LIVE console at 04:17 and was still
# inside the office loop when the orchestrator SIGKILLed the process group at
# 04:42 (25m, schedule_config timeout_minutes). Nothing synced, and the kill
# took the gap report, the Hub pill and the corrections post with it.
#
# So the run now polices its own clock instead of waiting to be killed:
#   OFFICE_BUDGET_S  one office's whole slice. Past it the office is abandoned
#                    and flagged — 16 good offices beat 1 stuck one.
#   RUN_BUDGET_S     stop STARTING offices here, leaving time to finish the one
#                    in flight and report. The rest are flagged as skipped.
#   HARD_BUDGET_S    watchdog. If something wedges below the checks anyway, say
#                    where and exit ourselves, under the orchestrator's cap, so
#                    the log names the stuck office + step instead of going dark.
# Typical office is well under a minute (the card budgets 12m for all 17), so
# 2m means "clearly stuck", not "a bit slow". Overridable for a manual catch-up
# run that wants a longer leash.
OFFICE_BUDGET_S = int(os.environ.get("APPLICANT_OFFICE_BUDGET_S", 120))
RUN_BUDGET_S = int(os.environ.get("APPLICANT_RUN_BUDGET_S", 20 * 60))
HARD_BUDGET_S = int(os.environ.get("APPLICANT_HARD_BUDGET_S", 23 * 60))

# What the run is doing right now, for the watchdog to name. Written by
# _Clock.check on every step; read from the watchdog thread.
_WHERE = {"office": "-", "step": "startup", "since": time.monotonic()}


class OfficeTimeout(Exception):
    """This office ran past OFFICE_BUDGET_S and was abandoned mid-way."""


class _Clock:
    """Wall clock the office steps check between page loads.

    Playwright's sync calls can't be interrupted from outside, so the cap is
    enforced BETWEEN steps rather than inside one. That's enough because every
    step is itself bounded (applicantstream sets a default timeout + navigation
    timeout on the page), so the worst case is one step's overshoot instead of
    the open-ended hang this is here to stop."""

    def __init__(self, budget_s: float, label: str):
        self.budget_s = budget_s
        self.label = label
        self.start = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.start

    def check(self, step: str) -> None:
        """Name the step about to run, and give up if the slice is spent."""
        _WHERE["office"] = self.label
        _WHERE["step"] = step
        _WHERE["since"] = time.monotonic()
        if self.elapsed > self.budget_s:
            raise OfficeTimeout(
                "over its {}s slice ({}s elapsed) — gave up before '{}'".format(
                    int(self.budget_s), int(self.elapsed), step))


def _start_watchdog(report) -> None:
    """Report and exit at HARD_BUDGET_S, before the orchestrator's SIGKILL.

    A SIGKILL is silent: it can't run the gap report and it discards whatever
    the process hadn't flushed. Ending the run ourselves means the log always
    names the office and step that hung."""
    def _tick():
        time.sleep(HARD_BUDGET_S)
        stuck = int(time.monotonic() - _WHERE["since"])
        print("\n!! WATCHDOG: {}s spent and still running — office {} has been "
              "in step '{}' for {}s. Ending the run here so this log says where "
              "it hung (the orchestrator's kill would not).".format(
                  HARD_BUDGET_S, _WHERE["office"], _WHERE["step"], stuck),
              flush=True)
        try:
            report(wedged="{} at '{}'".format(_WHERE["office"], _WHERE["step"]))
        except Exception as e:  # noqa: BLE001 — never trade the exit for a raise
            print("  (gap report failed: {})".format(e), flush=True)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)

    threading.Thread(target=_tick, daemon=True, name="applicant-watchdog").start()

# --- Retention detail-page row labels ---
L_CALL_LIST = "Sent to Call List"
L_2ND_ROSTER = "Total Second Interviews"
L_2ND_SHOWED = "Second Interviews Showed Up"
L_OFFERED = "Offered Job From Second Round"
L_BOB = "Total Daily Bob"
L_TRAINING = "Total Training"
L_TRAINING_SHOWED = "Training Showed Up"

# The "Sent to Call List" detail table has 8 data cols (First, Last, Email,
# Phone, Rating, Job Board, Date and Time, Ad) — the SAME off-by-one that hit 2R
# below. 7 stopped at Date and Time and dropped the Ad (sheet col I), so every
# Call List row imported with a blank Ad. It only became visible on 2026-07-28,
# when the morning phase moved into the 4am flow and the Call List started
# landing in full every day. Paste starts at B, so 8 fills B..I.
N_CALL_COLS = 8   # Call List tab -> B..I
# The "Total Second Interviews" detail table has 10 data cols (First, Last,
# Email, Phone, Rating, 1STR, 2ND, Job Board, Date and Time, Ad). 9 stopped at
# Date and Time and dropped the Ad (BD) — every 2R Retention row imported with a
# blank Ad. 10 captures through the Ad; paste starts at AU so this fills AU..BD.
N_2R_COLS = 10    # 2R tab -> AU..BD


def date_header_for(target: dt.date) -> str:
    return target.strftime("%b %-d, %Y")  # e.g. "Jul 21, 2026"


def clean_owner_name(name: str) -> str:
    """'Rafael Hidalgo TX' -> 'Rafael Hidalgo' (strip a trailing 2-letter state)."""
    parts = name.strip().split()
    if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isupper():
        parts = parts[:-1]
    return " ".join(parts)


# ---- MORNING: Call List + 2R Status (reads YESTERDAY) --------------------
def _morning_office(app, ws_call, ws_2r, office_id: str, header: str,
                    ad_blank: list, clock: "_Clock") -> None:
    clock.check("select office")
    owner = app.select_office(office_id)  # raw owner (Call List keeps the state)

    # ONE report load -> collect every detail href this phase needs.
    clock.check("open retention report")
    app.open_retention_details()
    h_call = app.detail_href(L_CALL_LIST, header)
    h_roster = app.detail_href(L_2ND_ROSTER, header)
    h_showed = app.detail_href(L_2ND_SHOWED, header)
    h_offered = app.detail_href(L_OFFERED, header)
    h_bob = app.detail_href(L_BOB, header)

    # --- Export Call List ---
    clock.check("scrape Call List")
    call_rows = app.scrape_at(h_call, N_CALL_COLS)
    if call_rows:
        clock.check("write Call List")
        start = sheets.first_empty_row_in_column(ws_call, "A")
        sheets.paste_block(ws_call, start, "A", [[owner]] * len(call_rows))
        sheets.paste_block(ws_call, start, "B", call_rows)
        print(f"  [{office_id}] {owner}: Call List +{len(call_rows)} (row {start})",
              flush=True)
        # The Ad is the LAST data col. A whole office landing with a blank Ad is
        # how the 7-vs-8 column miss hid for days — nobody sees a silently
        # narrow paste. Flag it so the next column the site adds gets caught the
        # next morning instead of by Francia. [[feedback_flag_unfilled_cells]]
        if all(not (r[-1] or "").strip() for r in call_rows if r):
            ad_blank.append(str(office_id))
            print(f"  ⚠ [{office_id}] {owner}: every Call List row has a BLANK Ad "
                  f"— the detail table's columns probably moved (N_CALL_COLS)",
                  flush=True)
    else:
        print(f"  [{office_id}] {owner}: no Call List for {header}", flush=True)

    # --- Update 2R Status ---
    clock.check("read 2R roster")
    roster = app.names_at(h_roster)
    if not roster:
        print(f"  [{office_id}] no second interviews {header} -- 2R status skipped",
              flush=True)
        return
    clock.check("read 2R showed/offered/BOB")
    showed = app.names_at(h_showed)
    offered = app.names_at(h_offered)
    bob = app.names_at(h_bob)
    # Brought-on-board dates come from the calendar (only needed if anyone was
    # BOB). Best-effort: on the warm patchright session the jQuery calendar nav
    # is invisible, so bob_dates comes back empty and Notes(J) stays blank — the
    # rest of the status still writes. See applicantstream.open_calendar_for.
    bob_dates = {}
    if bob:
        clock.check("read BOB dates from the calendar")
        app.open_calendar_for(_header_to_date(header))
        bob_dates = app.scrape_calendar_bob_dates()  # {name_lower: "Jul 27"}

    clock.check("write 2R status")
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
    print(f"  [{office_id}] 2R status: {updated}/{len(roster)} matched", flush=True)


# ---- EVENING: 2R Retention + First-Day (reads TODAY) --------------------
def _evening_office(app, ws_2r, office_id: str, header: str,
                    clock: "_Clock") -> None:
    clock.check("select office")
    owner = clean_owner_name(app.select_office(office_id))  # 2R Retention strips state

    clock.check("open retention report")
    app.open_retention_details()
    h_2nd = app.detail_href(L_2ND_ROSTER, header)
    h_train = app.detail_href(L_TRAINING, header)
    h_show = app.detail_href(L_TRAINING_SHOWED, header)

    # --- Export 2R Retention ---
    clock.check("scrape 2R Retention")
    ret_rows = app.scrape_at(h_2nd, N_2R_COLS)
    if ret_rows:
        clock.check("write 2R Retention")
        start = sheets.first_empty_row_in_column(ws_2r, "AT")
        sheets.paste_block(ws_2r, start, "AT", [[owner]] * len(ret_rows))
        sheets.paste_block(ws_2r, start, "AU", ret_rows)
        print(f"  [{office_id}] {owner}: 2R Retention +{len(ret_rows)} (row {start})",
              flush=True)
    else:
        print(f"  [{office_id}] {owner}: no Total Second Interviews for {header}",
              flush=True)

    # --- Confirm First-Day (col R) --- gated until verified
    clock.check("read first-day training lists")
    scheduled = app.names_at(h_train)
    if not scheduled:
        return
    showed = app.names_at(h_show)
    clock.check("mark first-day")
    for name in scheduled:
        row = sheets.find_row_by_name(ws_2r, name, 1)
        if not row:
            continue
        mark = "Y" if name in showed else "N"
        if FIRST_DAY_LIVE:
            sheets.set_cell(ws_2r, row, "R", mark)  # respects sheets.DRY_RUN
        else:
            print(f"    [first-day dry] R{row}={mark} for {name} "
                  "(not written — FIRST_DAY_LIVE off)", flush=True)


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
          f"{' [DRY-RUN]' if sheets.DRY_RUN else ''} ===", flush=True)

    ws_2r = sheets.open_tab(config.TAB_2R)
    ws_call = sheets.open_tab(config.TAB_CALL_LIST) if phase == "morning" else None

    total = len(config.OFFICE_IDS)
    failed: list[str] = []
    no_access: list[str] = []
    ad_blank: list[str] = []
    timed_out: list[str] = []
    skipped: list[str] = []
    reported = threading.Lock()   # the watchdog and the main path both report

    def _report(wedged: str = "") -> None:
        """Gap report + Hub pill + corrections post. Called once, by whichever
        of the main path and the watchdog gets there first."""
        if not reported.acquire(blocking=False):
            return
        _finish(phase, total, failed=failed, no_access=no_access,
                ad_blank=ad_blank, timed_out=timed_out, skipped=skipped,
                wedged=wedged)

    _start_watchdog(_report)
    run_clock = _Clock(RUN_BUDGET_S, "run")
    with session() as app:
        for i, office_id in enumerate(config.OFFICE_IDS):
            # Stop STARTING offices once the run budget is spent, so the report
            # below still runs. The remaining ids are named as skipped rather
            # than silently missing.
            if run_clock.elapsed > RUN_BUDGET_S:
                skipped = [str(o) for o in config.OFFICE_IDS[i:]]
                print(f"!! run budget ({RUN_BUDGET_S // 60}m) spent after "
                      f"{i} of {total} office(s) — not starting the remaining "
                      f"{len(skipped)}: {', '.join(skipped)}", flush=True)
                break
            print(f"[{office_id}] selecting office... "
                  f"({i + 1}/{total}, {int(run_clock.elapsed)}s in)", flush=True)
            clock = _Clock(OFFICE_BUDGET_S, str(office_id))
            try:
                if phase == "morning":
                    _morning_office(app, ws_call, ws_2r, office_id, header,
                                    ad_blank, clock)
                else:
                    _evening_office(app, ws_2r, office_id, header, clock)
                print(f"  [{office_id}] done in {int(clock.elapsed)}s", flush=True)
            except OfficeTimeout as e:
                # The whole point of the slice: this office is abandoned so the
                # rest still get their turn. Kept apart from `failed` because
                # the fix is different — a timeout means slow/stuck, not broken.
                timed_out.append(str(office_id))
                print(f"  ⏱ [{office_id}] TIMED OUT: {e} — skipped so the "
                      "remaining offices still run", flush=True)
            except OfficeNotAvailable as e:
                # Kept apart from `failed`: this one will fail identically every
                # night until somebody grants access or drops the id, so it must
                # not read as a flaky run you can just re-kick.
                no_access.append(str(office_id))
                print(f"  ⛔ [{office_id}] NO ACCESS: {e}", flush=True)
            except Exception as e:  # noqa: BLE001 -- one office must not sink the rest
                failed.append(str(office_id))
                print(f"  ! [{office_id}] error: {type(e).__name__}: {str(e)[:120]}",
                      flush=True)

    _report()
    print(f"=== {phase.upper()} phase done ===", flush=True)


def _finish(phase: str, total: int, *, failed: list, no_access: list,
            ad_blank: list, timed_out: list, skipped: list,
            wedged: str = "") -> None:
    """Gap report — name the offices that did NOT sync, at the end where the log
    tail actually shows it. Per-office errors are swallowed above so one bad
    office can't sink the other 16; without this the isolation also hides them.

    Split out of run() so the watchdog can call it too: a run that gets wedged
    should still say which offices it got through before it gave up."""
    if wedged:
        print(f"!! run WEDGED on {wedged} — the offices below are what "
              "finished before that", flush=True)
    if timed_out:
        print(f"!! {len(timed_out)} of {total} office(s) ran past the "
              f"{OFFICE_BUDGET_S}s per-office budget and were skipped: "
              f"{', '.join(timed_out)}", flush=True)
    if skipped:
        print(f"!! {len(skipped)} of {total} office(s) were never started — the "
              f"run hit its {RUN_BUDGET_S // 60}m budget first: "
              f"{', '.join(skipped)}", flush=True)
    if failed:
        print(f"!! {len(failed)} of {total} office(s) did NOT sync: "
              f"{', '.join(failed)}", flush=True)
    if no_access:
        print(f"!! {len(no_access)} of {total} office(s) are NOT VISIBLE to this "
              f"login ({config.__name__} OFFICE_IDS): {', '.join(no_access)} — "
              "this repeats nightly until access is granted or the id is removed",
              flush=True)
    if ad_blank:
        print(f"!! {len(ad_blank)} of {total} office(s) imported the Call List "
              f"with a BLANK Ad: {', '.join(ad_blank)} — check whether the "
              "'Sent to Call List' detail table gained/moved a column "
              f"(N_CALL_COLS is {N_CALL_COLS})", flush=True)

    # Report completion for the Hub pill. Only real (non-dry) runs count.
    #
    # The card follows the SAME rules as every other report: a completed run is
    # SUCCESS (green). A missed office no longer holds the pill amber — instead
    # the gap is posted to the corrections channel so it's still visible (Megan
    # 2026-07-25, revised: green + Slack the gap, not an amber pill). A WEDGED
    # run is the exception: it didn't complete, so it isn't a green run.
    if sheets.DRY_RUN:
        return
    try:
        from automations.shared import hub_activity
        hub_activity.log_completed(CARD_ID, CARD_NAME,
                                   status="failed" if wedged else "success")
    except Exception:
        pass
    # Any office that did NOT sync (a genuine error OR a no-access gap) goes
    # to #claudecorrections-and-requests so the miss is seen even though the
    # pill is green. Best-effort — a Slack hiccup never fails the run.
    if not (failed or no_access or ad_blank or timed_out or skipped or wedged):
        # A clean sweep closes the office-gap thread — the fix for a
        # no-access office is granting access, which happens outside any
        # run, so nothing else would ever say "it's over" (Eve 2026-08-17).
        try:
            from automations.shared import incident_thread as _inc
            _inc.resolve_if_open(
                "applicant-tracker-gaps",
                what="*Applicant Tracker*",
                detail="All {} offices synced on the {} run.".format(
                    total, phase))
        except Exception:  # noqa: BLE001 — never sink a good run
            pass
        return
    try:
        from automations.day_orchestrator import notify
        missed = len(failed) + len(no_access) + len(timed_out) + len(skipped)
        lines = ["🗂️ *Applicant Tracker — {} run: {} of {} office(s) "
                 "did not sync*".format(phase, missed, total)
                 if missed else
                 "🗂️ *Applicant Tracker — {} run: all {} office(s) "
                 "synced, but something looks off*".format(phase, total)]
        if wedged:
            lines.append("• Run WEDGED on {} — it was ended at {}m so this "
                         "report could run at all".format(
                             wedged, HARD_BUDGET_S // 60))
        if no_access:
            lines.append("• No access ({}): {}".format(
                len(no_access), ", ".join(no_access)))
        if timed_out:
            lines.append("• Ran past the {}s per-office budget ({}): {}".format(
                OFFICE_BUDGET_S, len(timed_out), ", ".join(timed_out)))
        if skipped:
            lines.append("• Never started, run hit its {}m budget ({}): "
                         "{}".format(RUN_BUDGET_S // 60, len(skipped),
                                     ", ".join(skipped)))
        if failed:
            lines.append("• Errored ({}): {}".format(
                len(failed), ", ".join(failed)))
        if ad_blank:
            lines.append(
                "• Call List imported with a BLANK Ad ({}): {} — the "
                "'Sent to Call List' detail table may have gained or "
                "moved a column".format(len(ad_blank),
                                        ", ".join(ad_blank)))
        # ONE thread for the office gaps, not a post per run. This fired
        # twice a day, every day, with the same office in it — six
        # near-identical posts sat in the channel between 8/13 and 8/17.
        # The run that still has gaps replies inside; a clean sweep
        # closes it above (Eve 2026-08-17).
        notify.post_alert(lines[0], lines[1:], dry_run=False,
                          tag="applicant-tracker-gaps",
                          incident="applicant-tracker-gaps",
                          label="*Applicant Tracker* ({} run)".format(phase))
    except Exception as e:  # noqa: BLE001 — Slack must not fail the run
        print("  (corrections post skipped: {})".format(e), flush=True)


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
