"""BG-check sync — daily run.

Reads First Advantage / Sterling emails, updates col K "BG Status" on both D2D
OBCL tabs for the current start-week (forward-only), and posts/updates the weekly
#rafs-office-recruiting thread as Lucy.

Safe by default: --dry-run makes NO sheet writes; Slack only posts with --post.
Both off = a pure preview. Nothing goes live until explicitly enabled.

    # full preview (reads real inbox, writes nothing, prints Slack message):
    python -m automations.bg_check_sync.run --dry-run
    # offline preview from a saved events file (no inbox needed):
    python -m automations.bg_check_sync.run --dry-run --events output/bg_events_sample_2026-07-20.json
    # go live:
    python -m automations.bg_check_sync.run --post
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys

from automations.recruiting_report import fill
from automations.bg_check_sync import parse, match, email_source, slack_post

SPREADSHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
ROLLING_TAB = "D2D OBCL"
_DATE_RE = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$")


def _fmt_week(d: dt.date) -> str:
    """Thread key / label. Explicit ints — %-m is not portable to Windows."""
    return f"{d.month}/{d.day}/{d.year}"


def _monday_of(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())   # Monday=0


def _active_monday(today: dt.date | None = None) -> dt.date:
    """The Monday whose new-start cohort we're onboarding RIGHT NOW — i.e. NEXT
    Monday, not this one.

    New starts are background-checked the week BEFORE they start, so during any
    given week the cohort worth tracking is the one starting the following
    Monday. That's `_monday_of(today) + 7`. The very first thread proved this:
    "week of 7/20" was posted Fri 7/17 (the week before), tracking those reps'
    checks in flight. Tracking the week that just STARTED instead would follow a
    cohort whose checks are already done.

    Guard: never go BACKWARDS to a week we've already threaded, so a re-run can't
    resurrect a past cohort's thread."""
    monday = _monday_of(today or dt.date.today()) + dt.timedelta(days=7)
    try:
        state = slack_post._load_state()
        seen = [match.parse_header_date(k) for k in state]
        latest = max([d for d in seen if d], default=None)
        if latest and latest > monday:
            monday = latest
    except Exception:  # noqa: BLE001 — state is a convenience, never fatal
        pass
    return monday


def _dated_tabs_in_window(sh, start: dt.date, end: dt.date):
    """Every 'D2D OBCL <M>.<D>' tab whose date falls in the week window.
    Returns (matched, all_dated) so the caller can SAY when dated tabs exist but
    none landed in the window — a naming/date drift that would otherwise silently
    drop a whole tab's worth of names."""
    matched, all_dated = [], []
    for ws in sh.worksheets():
        title = ws.title.strip()
        if not title.startswith(f"{ROLLING_TAB} "):
            continue
        all_dated.append(title)
        stamp = title[len(ROLLING_TAB):].strip().replace(".", "/")
        for year in (start.year, end.year):
            d = match.parse_header_date(f"{stamp}/{year}")
            if d and start <= d <= end:
                matched.append(title)
                break
    return matched, all_dated


def build_roster(sh, monday: dt.date):
    """Roster = every block (rolling tab) + every dated tab whose date falls in
    this Mon–Sun week, consolidated and deduped by name."""
    end = monday + dt.timedelta(days=6)
    rolling_vals = fill._retry(sh.worksheet(ROLLING_TAB).get_all_values)
    people = match.roster_blocks_in_window(rolling_vals, monday, end, ROLLING_TAB)
    dated, all_dated = _dated_tabs_in_window(sh, monday, end)
    for title in dated:
        vals = fill._retry(sh.worksheet(title).get_all_values)
        people += match.roster_from_dated_tab(vals, title)
    if dated:
        note = ", ".join(dated)
    elif all_dated:
        # Dated tabs exist but none fall in this week. Usually just "not built
        # yet" (the team builds it ~Thursday) — but naming which tabs DO exist
        # makes a name/date drift visible instead of silently dropping a tab.
        note = f"no dated tab for this week yet (existing: {', '.join(all_dated)})"
    else:
        note = "no dated tab yet"
    return match.consolidate(people), note


def apply_writes(sh, decisions, dry_run: bool) -> int:
    """Write col K for advancing decisions in every tab a person appears."""
    by_tab: dict[str, list[tuple[int, str]]] = {}
    for d in decisions:
        if not d.new_status:
            continue
        for tab, row in d.person.locations:
            by_tab.setdefault(tab, []).append((row, d.new_status))
    written = 0
    for tab, updates in by_tab.items():
        ws = sh.worksheet(tab)
        data = [{"range": f"K{row}", "values": [[val]]} for row, val in updates]
        written += len(data)
        if not dry_run:
            fill._retry(ws.batch_update, data, value_input_option="USER_ENTERED")
    print(f"[writes] {'(dry-run) would update' if dry_run else 'updated'} "
          f"{written} cell(s) across {len(by_tab)} tab(s)")
    return written


def process_week(sh, monday, events, *, dry_run, do_post, repost, now):
    """Update col K on both tabs + post/edit the Slack thread for ONE week.
    Returns a short summary dict. Empty-roster weeks are skipped (no empty post)."""
    week = _fmt_week(monday)
    roster, dated_note = build_roster(sh, monday)
    if not roster:
        print(f"\nWeek of {week} (Mon–Sun): no roster yet — skipped")
        return {"week": week, "roster": 0, "changes": 0}

    fuzzy_log: list = []
    matched = match.match_events_to_people(roster, events, fuzzy_log=fuzzy_log)

    decisions, slack_people, needs_confirm, flags = [], [], [], []
    for p in sorted(roster, key=lambda x: (x.last.lower(), x.first.lower())):
        d = match.decide(p, matched[p.key])
        decisions.append(d)
        slack_people.append((f"{p.first} {p.last}".strip(), d.new_status or p.current))
        if d.needs_adjudication:
            needs_confirm.append(f"{p.first} {p.last}".strip())
        if d.flag:
            flags.append((f"{p.first} {p.last}".strip(), d.flag))

    changes = [d for d in decisions if d.new_status]
    print(f"\nWeek of {week} (Mon–Sun) | roster {len(roster)} "
          f"(rolling blocks + {dated_note}) | {len(changes)} changes | "
          f"{len(needs_confirm)} need confirmation | {len(flags)} flags")
    for d in changes:
        print(f"  {d.person.last}, {d.person.first} : "
              f"{d.person.current or '(blank)'} -> {d.new_status}")

    apply_writes(sh, decisions, dry_run=dry_run)

    try:
        from automations.shared import terminated_icds as ti
        ti.alert_terminated([f"{p.first} {p.last}".strip() for p in roster],
                            report_label="BG Check Sync")
    except Exception as e:  # noqa: BLE001
        print(f"[terminated-check] skipped: {e}")

    hour12 = now.hour % 12 or 12
    updated_str = f"{now:%b} {now.day}, {hour12}:{now.minute:02d} {now:%p}"
    body = slack_post.render(week, slack_people, needs_confirm, updated_str)
    slack_post.post_or_update(week, body, dry_run=not do_post,
                              repost=repost, today=now.date().isoformat())

    if fuzzy_log:
        uniq = {(p.key, f"{p.first} {p.last}", f"{e.first} {e.last}") for e, p in fuzzy_log}
        print(f"[fuzzy-match] {len(uniq)} matched by compound-surname:")
        for _, sheet_name, email_name in sorted(uniq):
            print(f"  sheet '{sheet_name}' <- email '{email_name}'")
    if flags:
        print(f"[flags] {len(flags)} sheet-vs-email mismatches (no write):")
        for name, why in flags:
            print(f"  {name}: {why}")
    try:
        conflicts = [(f"{p.first} {p.last}".strip(), s)
                     for p in roster if (s := match.status_conflict(p))]
        if conflicts:
            print(f"[bg-conflict] {len(conflicts)} person(s) whose BG status DIFFERS "
                  f"between tabs (human should reconcile):")
            for name, split in sorted(conflicts):
                print(f"  {name}: {split}")
    except Exception as e:  # noqa: BLE001
        print(f"[bg-conflict] check skipped: {e}")

    return {"week": week, "roster": len(roster), "changes": len(changes)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="start-week date header (default: top block)")
    ap.add_argument("--events", help="JSON list of {sender,subject,body,date} (skip IMAP)")
    ap.add_argument("--since-days", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true", help="no sheet writes")
    ap.add_argument("--post", action="store_true", help="actually post/edit Slack")
    ap.add_argument("--repost", action="store_true",
                    help="force a fresh repost of the thread (the Friday bump)")
    args = ap.parse_args(argv)

    # Tell the Hub we're running (yellow pill -> green on success). Never let a
    # Hub-publish hiccup break the actual report.
    hub_run_id = None
    if not args.dry_run:
        try:
            from automations.day_orchestrator import hub_publish
            hub_run_id = hub_publish.publish_running("bg_check_sync", "BG Check Sync")
        except Exception as e:  # noqa: BLE001
            print(f"[hub] publish_running skipped: {e}")

    sh = fill.open_by_key(SPREADSHEET_ID)
    now = dt.datetime.now()

    # Which weeks to process. Default = CURRENT week AND NEXT week, so the OBCL
    # (rolling tab) keeps updating daily for everyone actively onboarding — not
    # just next week's cohort (Raf 2026-07-22). --week overrides to a single week.
    if args.week:
        m = match.parse_header_date(args.week)
        if m is None:
            raise SystemExit(f"--week {args.week!r} isn't a M/D/YYYY date")
        weeks = [m]
    else:
        this_mon = _monday_of(now.date())
        weeks = [this_mon, this_mon + dt.timedelta(days=7)]

    # --- events (fetched once, reused for every week) ------------------------
    if args.events:
        raw = json.load(open(args.events, encoding="utf-8"))
        events = [ev for e in raw
                  if (ev := parse.classify(e.get("sender", ""), e.get("subject", ""),
                                           e.get("body", ""), e.get("date", "")))]
        print(f"[events] {len(events)} parsed from {args.events}")
    else:
        events = email_source.fetch_events(since_days=args.since_days)

    upcoming = weeks[-1]  # the next-Monday cohort — the one worth a Friday bump
    for monday in weeks:
        # Friday-afternoon repost applies only to the UPCOMING week's thread (it's
        # the one about to start); the current week's thread just edits in place.
        repost = (args.repost or
                  (monday == upcoming and now.weekday() == 4 and now.hour >= 12))
        process_week(sh, monday, events, dry_run=args.dry_run,
                     do_post=args.post, repost=repost, now=now)

    if hub_run_id is not None:
        try:
            from automations.day_orchestrator import hub_publish
            hub_publish.publish_done("bg_check_sync", "BG Check Sync",
                                     status="success", run_id=hub_run_id)
        except Exception as e:  # noqa: BLE001
            print(f"[hub] publish_done skipped: {e}")

    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
