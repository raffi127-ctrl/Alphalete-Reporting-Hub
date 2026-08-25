"""Publish a completed orchestrator run to the Hub's shared "Hub Activity" tab.

The Hub marks a card "ran today" by reading SUCCESS rows from this tab
(dashboard._hub_recent_runs → _was_run_successfully_today). Runs the mini does
on its own never reached the Hub because they only updated the orchestrator's
local day_state — a different machine, a different store (Megan 2026-06-25:
"if reports were ran, even by the mini, they should be marked as ran on the
Hub"). So when a report finishes DONE, we append the same shape of row the Hub
writes for a click-run.

This is WRITE-ONLY and one-sided: the Hub already reads the tab, no Hub change
needed. Best-effort — never raises into the orchestrator loop.

NOTE: the Hub keys on its CARD id, which differs from our schedule_config
report_id (underscores vs hyphens, sometimes a different name). _HUB_CARD maps
ours → theirs. A report with no Hub card (weather_alert) is a no-op.
"""
from __future__ import annotations

import datetime as dt
import socket
import uuid

from automations.recruiting_report import fill as _fill

# The Hub Activity tab lives on the intake/backlog workbook (matches
# dashboard.HUB_ACTIVITY_SHEET_ID / HUB_ACTIVITY_TAB).
HUB_ACTIVITY_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
HUB_ACTIVITY_TAB = "Hub Activity"
# Column order must match dashboard.HUB_ACTIVITY_HEADERS exactly.
#   RunID, Started At, Report ID, Report Name, User, Machine, PID, Status, Ended At

# orchestrator report_id -> Hub CARD id. Reports absent here have no Hub card.
_HUB_CARD = {
    "att_focus_raf": "recruiting",
    "carlos_focus": "recruiting-carlos",
    "alphalete_org_focus": "recruiting-alphalete-org",
    "daily_focus": "daily-focus",
    "daily_rep_breakdown": "daily-rep-breakdown",
    # Raf's local office — folded onto the shared card with the other offices
    # (Megan 2026-07-16); it just still runs its own older module.
    "daily_metrics": "office-metrics",
    # Sunday Weekly Knock Dispositions board — NO card of its own (Megan
    # 2026-08-22): it posts into the same per-office Metrics threads, so its
    # runs land on the same shared card.
    "weekly_knock_dispositions": "office-metrics",
    "fiber_activations": "fiber-activations",
    "captainship_activations": "captainship-activations",
    "captainship_churn": "captainship-new-internet-wireless-churn",
    "captainship_cancel_rate": "captainship-cancel-rate",
    "captainship_raf_metrics": "captainship-raf-metrics",
    "owners_metrics_churn": "owners-metrics-churn",
    "recruiter_retention_daily": "daily-1st-round-recruiter-percent",
    "recruiter_retention_weekly": "ongoing-1st-round-recruiter-retention",
    "country_metrics": "country-metrics",
    "int_wow_penetration": "int-wow-penetration",
    "org_sales_board": "org-sales-board",
    "org_sales_board_email": "sales-board-screenshot-email",
    # LIVE, and its hyphenated card is gone (Megan 2026-08-25). It published to
    # `country-sales-board-email` through 2026-08-02; that card no longer exists
    # in either set, so since then the phantom guard has been auto-creating and
    # using the library card `country_sales_board_email` — which is where every
    # run since (incl. 2026-08-25 09:54 success) actually landed. Name the card it
    # really uses instead of a dead id the guard has to route around.
    "country_sales_board_email": "country_sales_board_email",
    # all_units_board_email: RETIRED 2026-07-31 — the All Units board stopped
    # being its own email and became the second section of the Org Sales Board
    # email (org_sales_board.screenshot_email, ALLUNITS_PREFIX). Its board entry
    # is gone from board_emails.boards, so the command now exits "unknown board
    # all-units". Last run 2026-08-01; its card is gone too. Mapping removed
    # rather than repointed — there is nothing left to publish.
    # The daily 'All Units' board FILL (all_campaigns_board, runs right after the
    # org board every day) was self-wiring to its own auto-registered
    # all_campaigns_board card, leaving the real hand-built "All Units Org Sales
    # Board" card (all-units-board) permanently white even though the fill
    # succeeds daily. Route the fill's pill to the real card (Megan 2026-08-02 —
    # the 7/31 repoint pointed the card at the board but never wired the publish).
    # The dupe all_campaigns_board library card is deleted alongside this.
    "all_campaigns_board": "all-units-board",
    # The daily Slack POST of the board (replaces the VA's manual post) — a
    # separate card from the board FILL above. Publishes only when it actually
    # posts, not on every 25-min pass.
    "org_board_slack": "org-sales-board-slack",
    # Added when this was a standalone launchd job outside the 4am batch, so a
    # blocked run wouldn't look exactly like a clean one — it ran unreported
    # until 2026-07-19, when a reconciliation failure went unnoticed for a day.
    # It joined Lucy 2's 4am flow 2026-07-23 and the 7:00 standalone
    # (com.alphalete.vantura-churn-daily) was retired 2026-08-14; the mapping
    # still matters, it's what puts the FLOW run on the card.
    "vantura_churn": "vantura-churn",
    # Vantura Weekly Payroll PREP (Carlos). Standalone Wed-11am LaunchAgent on
    # Lucy 2 (com.alphalete.vantura-payroll-wed) — LIVE since 2026-07-15 but it
    # never published, so its card was ALWAYS grey and a missed/failed weekly run
    # looked identical to a clean one. Wrapper now calls publish_done; this maps
    # it to the card (2026-07-22).
    "vantura_payroll": "vantura-payroll",
    # B2B Churn (Carlos) → Lucy Wireless / New INT / AIR Churn tabs. Standalone
    # LaunchAgent on Lucy 2 (com.alphalete.att-churn-daily, deploy/att_churn_daily.sh,
    # 7:15am), never in the 4am batch. Was a hand-run report until 2026-07-21, when
    # it went stale because nobody kicked it and it had no schedule. Same lesson as
    # vantura_churn: without this entry its card stays grey and a missed/failed run
    # looks identical to a clean one.
    "att_churn": "att-churn",
    # New-start onboarding: ONE CARD PER JOB, not one per family (Megan
    # 2026-08-25). These were briefly merged onto a single card, which was the
    # wrong read of the office-metrics precedent — that card merges twelve runs
    # of the SAME module on the SAME machine in the SAME batch. These three run
    # on three machines on three cadences, and a card is the Hub's unit of "did
    # THIS run on THIS box at THIS time": one pill cannot show Blue Ink failing
    # while Headshots succeeds, one schedule string cannot be three cadences,
    # and the card lands on all three profiles at once. Split back.
    "bg_check_sync": "bg-check-sync",
    "blueink_docs": "blueink-docs",
    "headshots": "headshot-bot",
    # The Monday thread post (weekly_thread.py) had self-registered a library
    # card of its own, so a manual `_now` run left the real card reading "no run
    # logged" all day. It belongs on the Headshot Bot card — same job, same
    # machine, same weekly cadence.
    "headshots_monday": "headshot-bot",
    # DD / Organization Bulletin: standalone LaunchAgent on the mini
    # (com.alphalete.dd-bulletin-thu, deploy/dd_bulletin_thu.sh, Thursday
    # 10:30-13:00) since 2026-07-30 — never in the 4am batch, so without this
    # entry its card stays grey and a week that never went out looks exactly like
    # a clean one. Its wrapper publishes ONLY on a pass that actually emailed:
    # the other six passes are quiet holds waiting for Eve to fill the tab.
    "dd_bulletin": "dd-bulletin",
    # Override Bulletin: standalone LaunchAgents on the mini (Lucy 1) — the Friday
    # FILL (override_bulletin_fri.sh) and SEND (override_bulletin_send_fri.sh),
    # never in the 4am batch. Missing here since it shipped, so a clean fill
    # published NOTHING and the card sat white even on a good run — a silent miss
    # looked identical to a clean one (same bug as vantura_churn / b2b_metrics).
    # The fill wrapper now calls publish_done on a real write; this line routes it
    # to the card. (2026-08-07)
    "override_bulletin": "override-bulletin",
    "recognition_tab": "recognition-tab",
    "pnl_office": "pnl-office",
    "sales_boards": "sales-boards",
    "vantura_slack_sales": "vantura-slack-sales",
    # Was mapped to "b2b-quality", a card that never existed — its daily pill
    # published into the void (Hub ORPHAN). Now maps to its real auto-registered
    # library card. The phantom-guard in hub_coverage.resolve_card also catches
    # this class of dangling mapping. (2026-07-27)
    "b2b_quality": "b2b_quality",
    # B2B Metrics: standalone LaunchAgent on Lucy 2 (com.alphalete.b2b-metrics,
    # deploy/b2b_metrics.sh, 7:45am) — never in the 4am batch. Missing here since
    # it shipped, so it posted its whole thread every morning while its card pill
    # stayed grey — a silent miss looked identical to a clean run (same bug as
    # vantura_churn / the captainship bonuses above). Its runner now calls
    # publish_done; this line is what makes that call land on the card.
    "b2b_metrics": "b2b-metrics",
    # Onboarded B2B offices (office_onboarding) run as their OWN scheduler entries
    # (jamis_metrics -> b2b_metrics.runner --office jamis) but belong on the ONE
    # consolidated B2B Metrics card, same as the D2D per-office feeds map to
    # office-metrics above. They're already in b2b_metrics.offices.ORDER (via
    # _merge_onboarded), so the card's re-run buttons already list them — this line
    # just routes their pill to that card and stops hub_coverage from
    # auto-registering a standalone library card (Megan 2026-08-02: "the 1 hub card
    # says who they are running for"). Add an onboarded office = one line here.
    "jamis_metrics": "b2b-metrics",
    # Weekly Promotion Check-In posts BOTH its passes (Mon 6pm + 7:15pm final)
    # under report_id "promo_checkin", and that card counts them via daily_runs:2
    # (the 2-phase pill). The Mon/Final install-agent plists got scanned into their
    # OWN auto-registered cards (promo_checkin_mon / promo_checkin_final) — dupes of
    # the one card. Route them to it so hub_coverage stops recreating them (Megan
    # 2026-08-02: "these 2 promo checkins should be 1 phase card").
    "promo_checkin_mon": "promo_checkin",
    "promo_checkin_final": "promo_checkin",
    # B2B Dispositions runs on Lucy 2 (deploy/b2b_dispositions.sh, hourly 12-6pm +
    # 6:30 final). Its two launchd plists got scanned into standalone auto cards
    # (b2b_dispositions_hourly / _final) that landed on the WRONG (Lucy 1) profile —
    # dupes of the one real card "b2b_dispositions". Fold them into it (Megan
    # 2026-08-02: "these 2 run on lucy 2 but are on the lucy 1 profile").
    "b2b_dispositions_hourly": "b2b_dispositions",
    "b2b_dispositions_final": "b2b_dispositions",
    # board_compare card RETIRED 2026-07-21 (Megan) — Eve hand-verifies the
    # automation instead; module kept for manual reruns but no Hub tile to publish to.
    "leaders_call": "leaders-call",
    # The 3 Monday reminder emails (11am/4pm/7:15pm) are their OWN card now —
    # "Promo Reminder Email" (promo-reminder-email, daily_runs {"0":3}) — split out
    # of the Leader's Call card 2026-08-02 (Megan). Each send publishes a success
    # here so that card's pill climbs 1/3 → 3/3 green. Leader's Call is now just
    # its deck (leaders_call above).
    "owners_call_reminder": "promo-reminder-email",
    # Fiber Owners email-distro sync: two orchestrator runs on Lucy 1 — Sat
    # 'post' (add owners + post departures for a 24h review) and Sun 'finalize'
    # (remove the approved departures). Neither report_id was mapped, so the
    # orchestrator ran them but never published — the card sat white forever.
    # Route both to the card so it greens on each run day (Megan 2026-08-02).
    "fiber_owners_distro_post": "fiber-owners-distro",
    "fiber_owners_distro_finalize": "fiber-owners-distro",
    # DD Thursday prep is one card now — "DD — Weekly Prep" (the dd_populate card,
    # daily_runs {"3":2}). dd_week_roll (rolls the week column) runs first, then
    # dd_populate (fills owners) — both publish here so the pill climbs 1/2 -> 2/2
    # green on Thursday (Megan 2026-08-02: "should these consolidate into 1 card").
    "dd_week_roll": "dd_populate",
    # New-Start Follow-Up's Saturday roll-call + nudges (and Sunday checklist)
    # run as their own launchd jobs, not the 4am batch. Each live pass publishes
    # here so the card's pill climbs as the passes land (Sat 4/4, Sun 1/1) —
    # without this line those runs post to Slack while the card stays white.
    "new_start_followup": "new-start-followup",
    "residential_rep_count": "residential_rep_count",
    # Sara+ issue escalation. This one runs every 5 min around the clock, so it
    # publishes ONLY when it actually escalates an issue (not on every tick) —
    # 288 heartbeat rows/day would bury the activity log. A quiet card here means
    # "no Sara+ issues reported", which is the normal, healthy state.
    "sara_down": "sara-plus-issues",
    # Every per-office metrics feed publishes to the ONE consolidated card
    # (dashboard._office_metrics_card) — same as the Tableau trackers. The card's
    # per-office ✅/❌ checklist carries which office missed; the pill is the
    # batch-level light. Adding an office = a row in office_metrics/offices.py
    # + its orchestrator entry + one line here.
    "rashad_metrics": "office-metrics",
    "aya_metrics": "office-metrics",
    "cyrus_metrics": "office-metrics",
    "hammad_metrics": "office-metrics",
    "kash_metrics": "office-metrics",
    "salik_metrics": "office-metrics",
    "cody_metrics": "office-metrics",
    # Rashad's other office-metrics variants (review post / order-log / churn pull)
    # — all consolidate under the single office-metrics card, not their own cards
    # (Megan 2026-07-27: "all metrics → 1 hub card like it was").
    "rashad_metrics_review": "office-metrics",
    "rashad_orderlog": "office-metrics",
    "rashad_churn": "office-metrics",
    # Churn variants that belong to an existing card, not their own.
    "vantura_churn_daily": "vantura-churn",
    "churn_eveliz_fix": "owners-metrics-churn",
    # frontier_opt: RETIRED 2026-08-23 (Megan: "we no longer use anything with
    # frontier"). Sunday agent uninstalled, on_scheduler false, and no frontier
    # card exists in either set. The module is kept for history / a one-off
    # `lucy rerun frontier_opt`; if that ever runs, the resolver registers it a
    # library card on the spot. Mapping removed — it named a card that is gone.
    "financial_report": "financial-pull",
    "brand_audit": "brand-health-audit",
    "social_inbox": "social-media-posting",
    "alphalete_production": "alphalete-production",
    "tableau_screenshots": "tableau-screenshots",
    # The ~7am Box catch-up is its own card: it runs hours after the morning
    # trackers, so folding it into that card would leave one pill standing for two
    # runs that succeed or fail independently.
    "tableau_screenshots_box": "tableau-screenshots-box",
    "weather_alert": "lucy-weather-forecast",
    # Library reports run on their own LaunchAgent/rerun (not the 4am batch) and
    # mark themselves via run_library_report / their wrapper. Their Hub card id IS
    # the library id, so map it to itself so _cal_status matches (card goes green).
    "june_texas_de_brazil_monthly_competition": "june_texas_de_brazil_monthly_competition",
    # Car-Rides Cleanup: library card, 9 launchd passes a morning on Lucy 2.
    # Card id IS the library id, so map it to itself. Its wrapper publishes
    # each pass so the pill can climb 1/9 -> 9/9 (amber -> green).
    "car_rides": "car_rides",
    # Weekly captainship reports: standalone LaunchAgents (Lucy 2 Mon/Tue, mini Tue)
    # that call publish_done from their wrapper. They ran fine for weeks but their
    # cards never went green — they were simply missing from this map, so Megan had
    # no way to tell a successful run from a silent miss (2026-07-14).
    "carlos_captainship_bonus": "carlos-captainship-bonus",
    "carlos_captainship_headcount": "carlos-captainship-headcount",
    "raf_captainship_bonus": "raf-captainship-bonus",
    # STF Field Check: standalone 11pm LaunchAgent on the mini that calls
    # publish_done from deploy/stf_field_check_11pm.sh — map so the card pill
    # reflects the real run (else it stays grey like the captainship bonuses did).
    "stf_field_check": "stf-field-check",
    # Resume Pushing: standalone Lucy 2 LaunchAgent firing every 10 min,
    # 8am-10pm Mon-Fri. It was missing here, so ~84 clean runs a day looked
    # identical to a silent miss (same bug as the captainship bonuses above).
    # Its wrapper publishes FAILURES every time but SUCCESS only once a day —
    # publishing all 84 would add ~2.5k rows/month to Hub Activity and slow
    # every dashboard/digest read for one report's heartbeat.
    # Still runnable (merged into applicant_push 2026-08-10, but the entry is kept
    # so `lucy rerun resume_pushing` works) and it still publishes — 2026-08-21
    # success. Its hyphenated card went away after 2026-08-04; every run since has
    # landed on the library card `resume_pushing` via the phantom guard, so that
    # is the card this should have named all along.
    "resume_pushing": "resume_pushing",
    # applicant_push: the unified batch + OAT-leftovers push (office 11580) that
    # supersedes resume_pushing + oat_processing on one warm CDP session.
    "applicant_push": "applicant-push",
    # applicant_sync_morning: the 4am phase of the SAME card as the 8pm evening
    # phase ("Applicant Tracker Sync", daily_runs 2 — orange after morning,
    # green after evening). Unmapped, resolve_card auto-created a SECOND library
    # card off its display_name, so the Hub carried two cards for one report:
    # the auto one going red on a failed 4am, and the real one staying white
    # because only the module's own log_completed feeds it (Megan 2026-08-18).
    # Pairs with run.py skipping its log_completed under the orchestrator —
    # without that the morning would write BOTH rows and turn a 2-run pill green
    # on its own, hiding a missed 8pm. [[reference_phase_pill_id_match]]
    "applicant_sync_morning": "applicant-tracker-sync",
    # Curated so runs land on the real Recruiting card instead of the bare
    # library card self-registration made on 2026-08-24 (report_id and card id
    # differ by an underscore vs a hyphen, which is exactly the mismatch that
    # leaves a pill stuck). [[reference_phase_pill_id_match]]
    # ONE CARD, TWO PASSES (Megan 2026-08-25). The 'Owner Chat Texts → iMessage
    # owner chats' card covers both morning passes — 7:30 trackers PDF, 7:45 WOW
    # board — but each pass runs under its OWN report_id, and neither slug-matches
    # the card id. So the resolver registered them as two separate library cards
    # and the real card never received a single row: it read "scheduled 7:30 AM,
    # no run logged" on the Hub's Needs-attention list EVERY morning, including
    # 8/25, when both passes had in fact delivered (trackers 07:35 success, board
    # 09:38 success after its data-gate hold cleared). A card that can only ever
    # say "no run logged" trains you to ignore that line, which is the one line
    # that has to mean something. Both ids point at the one card; the later pass
    # closes it, same as any other multi-pass card.
    "owner_chat_texts_trackers": "owner-chat-texts",
    "owner_chat_texts_board": "owner-chat-texts",
    "owner_chat_texts": "owner-chat-texts",
    # weather_alert: Slack-only, no Hub card → not published.
}


def _resolve_card(report_id: str, report_name: str = "", *, create: bool = True):
    """Resolve a report_id to its Hub card id via the self-registering resolver
    (curated _HUB_CARD -> slug-match an existing card -> auto-create a library
    card). Falls back to the curated map alone if hub_coverage can't import, so a
    resolver hiccup can never stop a run from reporting itself. create=False makes
    it read-only (no card is invented)."""
    try:
        from automations.day_orchestrator import hub_coverage
        return hub_coverage.resolve_card(report_id, report_name, create=create)
    except Exception:
        return _HUB_CARD.get(report_id)


def hub_card_id(report_id: str):
    """The Hub card id for an orchestrator report_id, or None (read-only)."""
    return _resolve_card(report_id, create=False)


def _ws():
    return _fill._client().open_by_key(HUB_ACTIVITY_SHEET_ID).worksheet(HUB_ACTIVITY_TAB)


def publish_running(report_id: str, report_name: str, *, manual: bool = False):
    """Append a 'started' row so the Hub shows this mini run as RUNNING (yellow),
    live, from ANY machine's Hub — the dashboard already reads these rows
    (_hub_active_runs) with a 2h staleness guard. Returns the RunID to hand to
    publish_done (which flips this same row running->done in place), or None if the
    report has no Hub card / the write failed. Best-effort — never raises.

    `manual=True` means A PERSON started this run, and only then does the report's
    open alert thread get the :pending: mark (see _mark_working)."""
    card = _resolve_card(report_id, report_name)
    if not card:
        return None
    run_id = uuid.uuid4().hex[:12]
    try:
        _ws().append_row(
            [run_id, dt.datetime.now().isoformat(timespec="seconds"), card,
             report_name, "Mini (auto)", socket.gethostname(), "", "started", ""],
            value_input_option="RAW")     # column shape matches dashboard.HUB_ACTIVITY_HEADERS
        if manual:
            _mark_working(report_id)
        return run_id
    except Exception:
        return None


def _mark_working(report_id: str) -> None:
    """A PERSON just re-ran a report with an OPEN alert thread → react :pending:
    on that thread's post (Eve 2026-08-17).

    Two people pull these tickets off the channel list, and without this both can
    start on the same one. `scan=False` keeps it free: local index only, so a
    report start never costs a Slack read.

    A MACHINE STARTING A REPORT IS NOT SOMEBODY WORKING IT (Megan 2026-08-20).
    This used to run on every publish_running, on the premise that "re-running a
    broken report IS someone working the ticket — usually the fix Claude was just
    asked for". True when a re-run meant a human clicking Run Now; not true of
    what actually calls publish_running now — the 4am loop (_attempt_report),
    every auto-retry, the standalone LaunchAgents on their own clocks, and worst
    of the four, _sync_hub_pills, which opens a pill for every non-terminal
    report on every pass INCLUDING ones merely waiting on data or a not_before
    clock with nothing executing at all. The channel filled with ⏳ on threads
    nobody had touched, which is worth no more than no mark at all: you can't
    tell what is really being worked.

    The callers that mean a person now say so with manual=True — a `lucy rerun`
    queued by a human (mini_control._action_rerun) is the live case. Anything a
    machine schedules leaves the thread unmarked, which is correct: it is still
    open and still nobody's."""
    try:
        from automations.shared import incident_thread as inc
        inc.mark_working(report_id, scan=False)
    except Exception:  # noqa: BLE001 — never raise into a starting run
        pass


def publish_heartbeat(run_id: str) -> bool:
    """Re-stamp an open 'started' row's Started At (col 2) to now so its yellow
    pill stays LIVE past the Hub's 2h staleness window (dashboard.HUB_STALE_AFTER)
    — for a report the orchestrator is still working hours later (e.g. a board
    waiting on its not_before, or a Tableau report retrying while data lands).
    Only touches a row we opened (matched by RunID) and never its Status/Ended At.
    Best-effort — never raises. Returns True if a row was re-stamped."""
    if not run_id:
        return False
    now = dt.datetime.now().isoformat(timespec="seconds")
    try:
        ws = _ws()
        cell = ws.find(str(run_id))
        if not cell:
            return False
        ws.update([[now]], f"B{cell.row}", value_input_option="RAW")   # Started At
        return True
    except Exception:
        return False


def final_status(report_id: str, ok: bool) -> str:
    """The status to close a run's pill with: 'success' | 'partial' | 'failed'.

    A report that fans out to many parts (the Tableau trackers post to 5 Slack
    channels) can land MOST of them and miss one. Closing that red is wrong — a
    red pill on a report that mostly worked teaches people to ignore red. If the
    report wrote a manifest saying some parts succeeded and some failed, this
    returns 'partial' (the Hub colours it orange). Reports that don't record
    `succeeded` are unaffected: they still resolve to plain success/failed."""
    if ok:
        return "success"
    try:
        from automations.shared import run_manifest
        return run_manifest.outcome(report_id) or "failed"
    except Exception:      # noqa: BLE001 — status must never break the run
        return "failed"


def incomplete_status(report_id: str) -> str:
    """Pill status for a run the orchestrator marked INCOMPLETE (it RAN, but did
    not deliver everything). NEVER 'success'.

    WHY (Megan 2026-08-20): this used to return 'success' unless the report's
    manifest explicitly recorded a partial outcome. daily_metrics posted 8 of 9
    metrics, its manifest recorded nothing, so an INCOMPLETE run published GREEN
    — and because publish_done auto-resolves an open incident on 'success', Lucy
    also posted "RESOLVED. It just ran clean." while New Internet ABP % was
    still missing. A card cannot read done while a section is missing, and a
    missing section cannot close its own ticket.

    'partial' (orange) is the floor now. The manifest is still consulted so a
    report that records something finer can override, but the default for
    INCOMPLETE is partial, not green — and 'partial' is not 'success', so
    publish_done leaves the incident thread OPEN."""
    try:
        from automations.shared import run_manifest
        outcome = run_manifest.outcome(report_id)
        if outcome in ("partial", "failed"):
            return outcome
    except Exception:      # noqa: BLE001 — status must never break the run
        pass
    return "partial"


def _find_open_row_for_card(ws, card: str, report_name: str = ""):
    """Row index (1-based) of the most-recent OPEN 'started' row for `card` — one a
    publish_running opened and never closed (Status col 8 == 'started', Ended At
    col 9 empty). Lets a standalone wrapper pair its start/end WITHOUT threading a
    RunID through shell: it publish_running's at the top, then its existing
    publish_done (no run_id) finds and closes that same row here. Returns None if
    no open row (→ publish_done appends a fresh finished row, the old behaviour).

    Matched on `report_name` too, because a card can now carry SEVERAL reports
    (Megan 2026-08-25: the three new-start steps share new-start-onboarding).
    Blue Ink's wrapper publish_running's at 7:30 Monday and stays open for the
    best part of an hour, straddling the Headshot Bot's 8:30 Monday post and its
    5-minute tick — on card alone, whichever finished first would close Blue
    Ink's row and stamp it with the wrong step's status. Callers that pass no
    name keep the old card-only behaviour."""
    try:
        vals = ws.get_all_values()
    except Exception:
        return None
    hit = None
    for i, row in enumerate(vals[1:], start=2):     # skip header row
        row = (row + [""] * 9)[:9]
        # cols: 0 RunID,1 Started,2 Report ID(card),3 Name,4 User,5 Machine,6 PID,7 Status,8 Ended
        if (row[2] == card and str(row[7]).lower() == "started"
                and not str(row[8]).strip()
                and (not report_name or row[3] == report_name)):
            hit = i                                 # keep the LAST match = most recent
    return hit


# How long this producer stays quiet after alerting about one report. It used to
# be "the rest of the day", which made a re-run's failure INVISIBLE: you fixed
# something, ran it again, it failed again, and the channel said nothing until
# tomorrow — the one thing Eve needs to see in the thread (2026-08-17). The reply
# is threaded, so it costs the channel nothing; the cooldown only stops a
# 5-minute job from calling in every tick (the thread itself already folds a
# same-day repeat into one edited status line).
_REALERT_AFTER_S = 45 * 60


def _alert_failure(report_id: str, report_name: str) -> None:
    """Post a failure alert to #claudecorrections-and-requests when a report
    closes 'failed' — so a silently-failing standalone agent (whose wrapper
    doesn't alert on its own) gets seen, not just a red pill nobody's watching.
    A repeat lands as a reply in the SAME thread (incident_thread), throttled by
    _REALERT_AFTER_S. Best-effort — never raises into the run.
    The orchestrator opts out (alert_on_fail=False) — it sends its own richer
    failure summary with a paste-to-Claude block. (Megan 2026-08-02)

    Goes through incident_thread (Eve 2026-08-17): this is the THINNEST witness of
    a broken report — three lines and "open its Hub card" — and it fires first, so
    as a bare post it put a 4th near-identical BOX Order Log message in the channel
    ahead of the mini's full standalone alert 4 minutes later. As an incident it
    opens the thread only if nobody else has, and otherwise replies inside the one
    that's already there. failure- and standalone- share a subject, so which of
    them spoke first stops mattering."""
    try:
        import time
        marker = _fail_marker(report_id)
        if (marker.exists()
                and (time.time() - marker.stat().st_mtime) < _REALERT_AFTER_S):
            return
        from automations.day_orchestrator import notify
        notify.post_alert(
            f"❌ {report_name} failed",
            [f"`{report_id}` closed a run with status **FAILED** on "
             f"{socket.gethostname()}.",
             "Open its Hub card for the log, then re-run it."],
            tag=f"failalert-{report_id}",
            incident=f"failure-{report_id}", label=report_name)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("")
    except Exception:
        pass


def _fail_marker(report_id: str):
    """The "already alerted for this report" stamp. No date in the name any more
    — it is read as a COOLDOWN (see _alert_failure)."""
    from pathlib import Path as _P
    return (_P(__file__).resolve().parents[2] / "output" / "logs"
            / f".failalert-{report_id}")


def _clear_failure(report_id: str, report_name: str) -> None:
    """A run finished CLEAN → close the alert thread it left open and say so
    there, then clear the re-alert cooldown.

    WHY (Eve 2026-08-17): nothing closed an incident except the 4am orchestrator
    (for reports inside its loop) and the machine_digest watcher (standalone ones,
    hours later). Someone who read the alert, fixed the cause and re-ran the
    report from the Hub closed NOTHING — so the second person working the channel
    kept re-diagnosing problems that were already fixed, which is the exact cost
    Eve described. publish_done is the one place EVERY report's success lands, on
    every machine, so it is where the ✅ belongs.

    Clearing the cooldown matters too: after a fix, the NEXT break has to be able
    to speak immediately rather than waiting out a timer earned by the old
    problem — and since its thread was just closed, it correctly opens a fresh
    post. Best-effort: never raises into a good run."""
    try:
        marker = _fail_marker(report_id)
        from automations.shared import incident_thread as inc
        inc.resolve_report(report_id, what=f"*{report_name or report_id}*")
        if marker.exists():
            marker.unlink()
    except Exception:
        pass


def publish_done(report_id: str, report_name: str, status: str = "success",
                 run_id: str | None = None, *, alert_on_fail: bool = True,
                 user: str = "Mini (auto)") -> bool:
    """Mark a run finished on the Hub. If `run_id` (from publish_running) is given,
    UPDATE that 'started' row in place (Status col 8 + Ended At col 9) so the card
    flips running->done and doesn't leave a dangling yellow pill. With no run_id,
    close the most-recent OPEN started row for this card if one exists (a standalone
    wrapper that publish_running'd at its start), so it too shows a running->done
    pulse; only if there's no open row do we append a fresh finished row (the
    reverify / no-prior-start path). Returns True if the Hub was touched, False if
    the report has no Hub card. Best-effort — never raises.

    `user` fills the User column on an appended row. It defaults to the mini so
    every existing caller reads exactly as before; the hand-run hook
    (shared/hub_autopublish.py) passes the real person, because "Mini (auto)" on
    a row someone typed on their laptop sends you to the wrong machine."""
    card = _resolve_card(report_id, report_name)
    if not card:
        return False
    # Tell the hand-run hook this run already reported itself, so it cannot add
    # a SECOND row and fill a daily_runs>1 pill off a single pass.
    try:
        from automations.shared import hub_autopublish
        hub_autopublish.mark_reported()
    except Exception:   # noqa: BLE001
        pass
    now = dt.datetime.now().isoformat(timespec="seconds")
    try:
        ws = _ws()
        row = None
        if run_id:
            cell = ws.find(str(run_id))
            row = cell.row if cell else None
        else:
            row = _find_open_row_for_card(ws, card, report_name)  # pair a wrapper's start/end
        if row:
            ws.update_cell(row, 8, status)                        # Status
            ws.update([[now]], f"I{row}", value_input_option="RAW")   # Ended At
        else:
            ws.append_row(
                [uuid.uuid4().hex[:12], now, card, report_name, user,
                 socket.gethostname(), "", status, now],
                value_input_option="RAW")
        # A hard failure alerts Slack (deduped) so it can't fail silently. Only
        # 'failed' — NOT 'partial' (mostly worked) or 'skipped'/'scanned' (healthy
        # no-op). The orchestrator passes alert_on_fail=False (its own summary).
        if alert_on_fail and str(status).lower() == "failed":
            _alert_failure(report_id, report_name)
        elif str(status).lower() == "success":
            # …and a clean run CLOSES whatever thread the last failure opened —
            # including a re-run someone kicked off by hand from the Hub, which
            # is how most of these actually get fixed. Runs for the orchestrator
            # too: it closes its own carry-overs at the end of the batch, and
            # closing an already-closed incident is a free local no-op.
            _clear_failure(report_id, report_name)
        return True
    except Exception:
        return False

def main(argv=None) -> int:
    """Mark a report DONE on the Hub from anywhere — including a run that never
    touched a Lucy.

        python -m automations.day_orchestrator.hub_publish --done <report_id> [...]
        python -m automations.day_orchestrator.hub_publish --done fiber_activations --status success

    WHY (Megan 2026-08-19): a report run BY HAND from her laptop really ran, but
    its Hub card stayed white — only the orchestrator (and the handful of modules
    that self-publish) ever calls publish_done, so a hand-run report looks like it
    never happened. On 2026-08-19 owner_showdown, daily_rep_breakdown and the d2d
    metrics all ran on her laptop and every one of those cards read as missing.

    This ONLY records that a run finished; it does not run anything. Use it after
    you have actually confirmed the report's output, never to silence a card.
    Display names resolve from schedule_config so the Hub row matches what the
    orchestrator would have written."""
    import argparse
    ap = argparse.ArgumentParser(prog="hub_publish")
    ap.add_argument("--done", nargs="+", metavar="REPORT_ID", required=True,
                    help="report_id(s) to mark finished on the Hub")
    ap.add_argument("--status", default="success",
                    help="success (default) or a failure status")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be published, touch nothing")
    a = ap.parse_args(argv)

    try:
        from automations.day_orchestrator import registry
        cfg = registry.load_config()
    except Exception:  # noqa: BLE001 — names are a nicety, not a requirement
        cfg = None

    rc = 0
    for rid in a.done:
        name = rid
        if cfg is not None:
            try:
                r = registry.resolve_report(cfg, rid)
                if r is not None and getattr(r, "display_name", None):
                    name = r.display_name
            except Exception:  # noqa: BLE001
                pass
        if a.dry_run:
            print(f"[dry-run] would publish DONE: {rid} ({name}) status={a.status}")
            continue
        try:
            ok = publish_done(rid, name, status=a.status)
            print(f"{'✓' if ok else '·'} {rid} ({name}) -> {a.status}"
                  f"{'' if ok else '  [Hub not touched]'}")
            if not ok:
                rc = 1
        except Exception as e:  # noqa: BLE001
            print(f"✗ {rid}: {type(e).__name__}: {e}")
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
