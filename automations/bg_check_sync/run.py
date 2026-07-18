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


def _dated_tab_name(week_date: str) -> str:
    m, d, *_ = week_date.strip().split("/")
    return f"D2D OBCL {int(m)}.{int(d)}"


def _week_headers(rolling_vals) -> list[str]:
    return [(r[0] or "").strip() for r in rolling_vals
            if r and _DATE_RE.match((r[0] or "").strip())]


def _default_week(rolling_vals) -> str:
    """Active cohort = the top-most date-header block (team keeps the current
    start-week at the top). Overridable via --week."""
    headers = _week_headers(rolling_vals)
    if not headers:
        raise SystemExit("No date-header blocks found in rolling tab.")
    return headers[0]


def build_roster(sh, week: str):
    rolling_vals = fill._retry(sh.worksheet(ROLLING_TAB).get_all_values)
    people = match.roster_block_from_rolling(rolling_vals, week, ROLLING_TAB)
    dated_name = _dated_tab_name(week)
    try:
        dated_vals = fill._retry(sh.worksheet(dated_name).get_all_values)
        people += match.roster_from_dated_tab(dated_vals, dated_name)
        dated_note = f"{dated_name} (found)"
    except Exception:
        dated_note = f"{dated_name} (not built yet)"
    return match.consolidate(people), dated_note


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

    sh = fill.open_by_key(SPREADSHEET_ID)
    rolling_vals = fill._retry(sh.worksheet(ROLLING_TAB).get_all_values)
    week = args.week or _default_week(rolling_vals)

    roster, dated_note = build_roster(sh, week)

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
    print(f"\nWeek {week} | roster {len(roster)} (rolling block + {dated_note}) | "
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

    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
