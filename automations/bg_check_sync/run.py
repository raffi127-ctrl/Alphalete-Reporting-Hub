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
    """The Monday of the current Mon–Sun week. A new Monday => a new thread.

    Guard: never go BACKWARDS to a week we've already threaded. Without this, a
    run on Sat/Sun would resolve to the week that is technically current and
    spawn a thread for a cohort that already started."""
    monday = _monday_of(today or dt.date.today())
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="start-week date header (default: top block)")
    ap.add_argument("--events", help="JSON list of {sender,subject,body,date} (skip IMAP)")
    ap.add_argument("--since-days", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true", help="no sheet writes")
    ap.add_argument("--post", action="store_true", help="actually post/edit Slack")
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
    if args.week:
        monday = match.parse_header_date(args.week)
        if monday is None:
            raise SystemExit(f"--week {args.week!r} isn't a M/D/YYYY date")
    else:
        monday = _active_monday()
    week = _fmt_week(monday)

    roster, dated_note = build_roster(sh, monday)

    # --- events --------------------------------------------------------------
    if args.events:
        raw = json.load(open(args.events, encoding="utf-8"))
        events = [ev for e in raw
                  if (ev := parse.classify(e.get("sender", ""), e.get("subject", ""),
                                           e.get("body", ""), e.get("date", "")))]
        print(f"[events] {len(events)} parsed from {args.events}")
    else:
        events = email_source.fetch_events(since_days=args.since_days)

    fuzzy_log: list = []
    matched = match.match_events_to_people(roster, events, fuzzy_log=fuzzy_log)

    # --- decisions -----------------------------------------------------------
    decisions, slack_people, needs_confirm, flags = [], [], [], []
    for p in sorted(roster, key=lambda x: (x.last.lower(), x.first.lower())):
        d = match.decide(p, matched[p.key])
        decisions.append(d)
        effective = d.new_status or p.current
        slack_people.append((f"{p.first} {p.last}".strip(), effective))
        if d.needs_adjudication:
            needs_confirm.append(f"{p.first} {p.last}".strip())
        if d.flag:
            flags.append((f"{p.first} {p.last}".strip(), d.flag))

    changes = [d for d in decisions if d.new_status]
    print(f"\nWeek of {week} (Mon–Sun) | roster {len(roster)} "
          f"(rolling blocks + {dated_note}) | "
          f"{len(changes)} changes | {len(needs_confirm)} need confirmation | "
          f"{len(flags)} flags")
    for d in changes:
        print(f"  {d.person.last}, {d.person.first} : {d.person.current or '(blank)'} "
              f"-> {d.new_status}")

    # --- writes --------------------------------------------------------------
    apply_writes(sh, decisions, dry_run=args.dry_run)

    # --- terminated-ICD safety check ----------------------------------------
    try:
        from automations.shared import terminated_icds as ti
        names = [f"{p.first} {p.last}".strip() for p in roster]
        ti.alert_terminated(names, report_label="BG Check Sync")
    except Exception as e:
        print(f"[terminated-check] skipped: {e}")

    # --- Slack ---------------------------------------------------------------
    now = dt.datetime.now()
    hour12 = now.hour % 12 or 12
    updated_str = f"{now:%b} {now.day}, {hour12}:{now.minute:02d} {now:%p}"
    body = slack_post.render(week, slack_people, needs_confirm, updated_str)
    slack_post.post_or_update(week, body, dry_run=not args.post)

    if fuzzy_log:
        uniq = {(p.key, f"{p.first} {p.last}", f"{e.first} {e.last}") for e, p in fuzzy_log}
        print(f"\n[fuzzy-match] {len(uniq)} matched by compound-surname (eyeball these):")
        for _, sheet_name, email_name in sorted(uniq):
            print(f"  sheet '{sheet_name}' <- email '{email_name}'")

    if flags:
        print(f"\n[flags] {len(flags)} sheet-vs-email mismatches (no write):")
        for name, why in flags:
            print(f"  {name}: {why}")

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
