"""BG-check sync — daily run.

Reads First Advantage / Sterling emails, updates col K "BG Status" on both D2D
OBCL tabs for the current start-week (forward-only), and posts/updates the weekly
#11280-alphalete-marketing-inc-rafael-hidalgo thread as Lucy.

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
from automations.bg_check_sync import (parse, match, email_source,
                                       name_gate, ov_name_sync, slack_post)
from automations.shared import name_case

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


def _future_week_mondays(sh, this_monday: dt.date, rolling_vals) -> list:
    """Every week-Monday from this week onward that has people in EITHER tab
    (all future new-start cohorts). Skips already-past blocks so a stale old row
    can't collide with a new applicant of the same name. Always includes this
    week + next week so their threads post even before a block/tab exists."""
    mondays = {this_monday, this_monday + dt.timedelta(days=7)}
    for row in rolling_vals:
        d = match.parse_header_date(row[0] if row else "")
        if d and _monday_of(d) >= this_monday:
            mondays.add(_monday_of(d))
    for ws in sh.worksheets():
        title = ws.title.strip()
        if not title.startswith(f"{ROLLING_TAB} "):
            continue
        stamp = title[len(ROLLING_TAB):].strip().replace(".", "/")
        for year in (this_monday.year, this_monday.year + 1):
            d = match.parse_header_date(f"{stamp}/{year}")
            if d and _monday_of(d) >= this_monday:
                mondays.add(_monday_of(d))
                break
    return sorted(mondays)


def build_roster(sh, monday: dt.date, rolling_vals=None):
    """Roster = every block (rolling tab) + every dated tab whose date falls in
    this Mon–Sun week, consolidated and deduped by name."""
    end = monday + dt.timedelta(days=6)
    if rolling_vals is None:
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


def settle_name_gate(sh, *, dry_run: bool, do_post: bool) -> int:
    """Phase A of the legal-name gate: act on the ✅/❌ that came in since the
    last pass, BEFORE anything reads the sheet.

    Runs first on purpose. An approved rename rewrites the OBCL name, so doing
    it up front means this same run reads the corrected name, matches the
    Sterling email that was orphaned by the nickname, and fills col K — instead
    of the fix landing today and the status waiting for tomorrow.

    Never fatal: no token, no network, a deleted thread — the BG sync's actual
    job is col K, and none of it depends on this.
    """
    try:
        state = name_gate.load_state()
        approved, rejected = name_gate.collect_decisions(state)
        if not (approved or rejected):
            return 0
        applied = name_gate.apply_renames(sh, approved, state, dry_run=dry_run)
        name_gate.record_rejections(rejected, state, dry_run=dry_run)
        name_gate.confirm(applied, rejected, dry_run=not do_post)
        if not dry_run:
            name_gate.save_state(state)
        for entry in rejected:
            print(f"[name-gate] REJECTED: {entry['sheet_first']} {entry['sheet_last']} "
                  f"is NOT {entry['legal_first']} {entry['legal_last']} — that "
                  f"Sterling check belongs to someone else")
        return len(applied)
    except Exception as e:  # noqa: BLE001
        print(f"[name-gate] settle skipped: {e}")
        return 0


def ask_name_gate(roster, events, matched, monday, week, *, dry_run: bool,
                  do_post: bool, claimed_ids=None, collect=None,
                  refresh: bool = False) -> int:
    """Phase B: anyone left unmatched who looks like a nickname.

    With `collect`, the proposals are set aside instead of posted — the OV pass
    gets a chance to PROVE them first, and a question OwnerVille can answer is
    one nobody should be asked. Without it, they go straight to the channel.
    Never fatal either way.
    """
    try:
        state = name_gate.load_state()
        proposals = name_gate.propose(roster, events, matched, monday, week,
                                      claimed_ids=claimed_ids)
        # --refresh-asks: keep the ones already posted, so their wording can be
        # corrected in place instead of asked again.
        fresh = (proposals if refresh
                 else name_gate.unanswered(proposals, state))
        if not fresh:
            return 0
        for p in fresh:
            print(f"[name-gate] mismatch: sheet '{p.sheet_name}' vs Sterling "
                  f"'{p.legal_name}' ({p.evidence})")
        if collect is not None:
            collect.extend((p, roster) for p in fresh)
            return len(fresh)
        posted = name_gate.post_proposals(fresh, state, dry_run=not do_post)
        if posted:
            name_gate.save_state(state)
        return len(fresh)
    except Exception as e:  # noqa: BLE001
        print(f"[name-gate] ask skipped: {e}")
        return 0


def settle_by_ownerville(sh, pending: list, *, dry_run: bool, do_post: bool,
                         headless: bool, allow_login: bool) -> None:
    """Ask OwnerVille before asking people.

    For each mismatch the gate would have posted: if an OV profile shares this
    row's phone or email AND already carries the name Sterling ran, that is the
    identity proof the gate exists to get — apply the rename and say nothing.
    Everything left over is posted as usual.
    """
    if not pending:
        return
    checks = []
    for proposal, roster in pending:
        person = next((p for p in roster if p.key == proposal.key), None)
        checks.append(ov_name_sync.OVCheck(
            sheet_name=proposal.sheet_name,
            legal_first=proposal.legal_first, legal_last=proposal.legal_last,
            email=getattr(person, "email", "") or proposal.email,
            phone=getattr(person, "phone", "")))
    print(f"[name-gate] asking OwnerVille about {len(checks)} mismatch(es) "
          f"before asking anybody")
    verdicts = ov_name_sync.prove(checks, headless=headless, allow_login=allow_login)

    state = name_gate.load_state()
    proven, unproven = [], []
    for proposal, _roster in pending:
        ok, why = verdicts.get(proposal.sheet_name, (False, "not checked"))
        (proven if ok else unproven).append((proposal, why))
    for proposal, why in proven:
        print(f"[name-gate] PROVEN {proposal.sheet_name} = {proposal.legal_name} "
              f"— {why}")
    for proposal, why in unproven:
        print(f"[name-gate] still asking about {proposal.sheet_name}: {why}")

    if proven:
        entries = [p.as_entry() for p, _ in proven]
        name_gate.apply_renames(sh, entries, state, dry_run=dry_run)
        if not dry_run:
            for proposal, why in proven:
                state[proposal.pid] = {**state.get(proposal.pid, {}), **{
                    "status": "applied", "decided_by": "ownerville",
                    "reason": why,
                    "applied_at": dt.datetime.now().isoformat(timespec="seconds")}}
    if unproven:
        name_gate.post_proposals([p for p, _ in unproven], state,
                                 dry_run=not do_post)
    if not dry_run:
        name_gate.save_state(state)


OV_CHECKED_KEY = "_ov_checked"


def ov_targets_for(roster, matched, state, out: list) -> None:
    """Collect the people worth showing OwnerVille: everyone whose Sterling
    result we hold and whose OV profile we have not already confirmed.

    Skipping the confirmed ones matters — find_rep walks every campaign and
    types into a DataTables search box for each rep, so re-checking a settled
    profile three times a day would spend minutes to learn nothing.
    """
    done = state.get(OV_CHECKED_KEY, {})
    seen = {c.sheet_name for c in out}
    for p in roster:
        ev = match.best_event(matched.get(p.key) or [])
        if ev is None:
            continue
        name = f"{p.first} {p.last}".strip()
        if name in seen or name in done:
            continue
        seen.add(name)
        # Title-case here, not at the write: Sterling shouts some names
        # ("LEON URDAPILLETA BERNAL") and the report line should show what we
        # would actually put in the box.
        out.append(ov_name_sync.OVCheck(
            sheet_name=name,
            legal_first=name_case.titlecase_name(ev.first),
            legal_last=name_case.titlecase_name(ev.last),
            email=getattr(p, "email", ""), phone=getattr(p, "phone", "")))


def process_week(sh, monday, events, *, dry_run, do_post, repost, now,
                 do_slack=True, rolling_vals=None, claimed_ids=None,
                 ov_targets=None, pending_asks=None, names_from=None,
                 refresh_asks=False):
    """Update col K on both tabs for ONE week, and (if do_slack) post/edit its
    Slack thread. Returns a short summary dict. Empty weeks are skipped."""
    week = _fmt_week(monday)
    roster, dated_note = build_roster(sh, monday, rolling_vals)
    if not roster:
        print(f"\nWeek of {week} (Mon–Sun): no roster yet — skipped")
        return {"week": week, "roster": 0, "changes": 0}

    fuzzy_log: list = []
    matched = match.match_events_to_people(roster, events, fuzzy_log=fuzzy_log)

    # NAME WORK STARTS FROM A CUTOFF WEEK (Megan 2026-08-26: "we're not doing any
    # of this week's, they've already been hand done"). The cohort in flight was
    # reconciled by hand while this was being built, so re-deciding it now would
    # either re-ask settled questions or write over somebody's correction. The
    # cutoff is the NEXT start week, and everything before it is left exactly as
    # the humans left it. Statuses (col K) are unaffected — those run every week
    # as they always have.
    do_names = names_from is None or monday >= names_from
    if not do_names:
        print(f"  (name corrections skipped for {week} — handled by hand)")

    # The legal-name gate asks about this week's nickname/Sterling mismatches.
    # EVERY week we update, not just the two that get a Slack thread: the check
    # is taken the day somebody is hired and a start can be a month out, so the
    # result email is freshest — and the sheet read is cheapest — long before
    # their week comes around. Waiting would mean asking about an email that has
    # already fallen out of the 30-day scan. Each question is asked once and
    # remembered, so asking early costs nothing.
    if do_names:
        ask_name_gate(roster, events, matched, monday, week,
                      dry_run=dry_run, do_post=do_post, claimed_ids=claimed_ids,
                      collect=pending_asks, refresh=refresh_asks)

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

    # Sterling is the truth: anyone we have already MATCHED gets their checklist
    # spelling brought up to the name their check ran under. No gate — the match
    # is the proof of identity, which is the only thing the gate is for.
    try:
        fixes = name_gate.spelling_fixes(roster, matched, week) if do_names else []
        if fixes:
            print(f"[name-gate] {len(fixes)} matched name(s) spelled differently "
                  f"from Sterling:")
            applied = name_gate.apply_renames(sh, fixes, {}, dry_run=dry_run)
            # Carry the new spelling back into the roster we're holding, so the
            # green tint below lands in THIS run rather than the next one — the
            # row is correct the moment we write it, and a row that is correct
            # but still uncoloured for four hours is the tint saying the wrong
            # thing. Only people whose cells actually changed: apply_renames
            # skips any row that no longer holds the name we expected.
            if not dry_run:
                changed = {e["key"]: e for e in applied if e.get("rows_written")}
                if changed:
                    for person in roster:
                        e = changed.get(person.key)
                        if e:
                            person.first = e["legal_first"]
                            person.last = e["legal_last"]
                            person.key = match._norm_key(person.first, person.last)
                    matched = match.match_events_to_people(roster, events)
    except Exception as e:  # noqa: BLE001
        print(f"[name-gate] spelling fixes skipped: {e}")

    apply_writes(sh, decisions, dry_run=dry_run)

    if ov_targets is not None and do_names:
        try:
            ov_targets_for(roster, matched, name_gate.load_state(), ov_targets)
        except Exception as e:  # noqa: BLE001
            print(f"[ov-names] target collection skipped: {e}")

    # Green = this row's name is the one Sterling ran the check under.
    try:
        state = name_gate.load_state()
        if name_gate.tint_confirmed(
                sh, name_gate.confirmed_locations(roster, matched), state,
                dry_run=dry_run) and not dry_run:
            name_gate.save_state(state)
    except Exception as e:  # noqa: BLE001
        print(f"[name-gate] tint skipped: {e}")

    try:
        from automations.shared import terminated_icds as ti
        ti.alert_terminated([f"{p.first} {p.last}".strip() for p in roster],
                            report_label="BG Check Sync")
    except Exception as e:  # noqa: BLE001
        print(f"[terminated-check] skipped: {e}")

    if do_slack:
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


def _publish(hub_run_id, status: str) -> None:
    """Close this run's Hub Activity row. Best-effort — a Hub hiccup must never
    be what breaks (or masks) the report."""
    if hub_run_id is None:
        return
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done("bg_check_sync", "BG Check Sync",
                                 status=status, run_id=hub_run_id)
    except Exception as e:  # noqa: BLE001
        print(f"[hub] publish_done skipped: {e}")


def _run(args) -> None:
    """The actual sync. Split out of main() so main() can own the Hub row's
    open/close on BOTH the success and the crash path."""
    sh = fill.open_by_key(SPREADSHEET_ID)
    now = dt.datetime.now()

    # Settle yesterday's name questions FIRST, so the sheet read below already
    # carries any approved legal name and its col K can advance this same run.
    settle_name_gate(sh, dry_run=args.dry_run, do_post=args.post)

    rolling_vals = fill._retry(sh.worksheet(ROLLING_TAB).get_all_values)

    # SHEET updates cover EVERY current-and-future week on the OBCL — it's all
    # future new starts, so update all of it as results come in (Raf 2026-07-22).
    # SLACK threads stay focused on the near term: the current week + next week.
    # --week overrides to a single week (manual backfill).
    if args.week:
        m = match.parse_header_date(args.week)
        if m is None:
            raise SystemExit(f"--week {args.week!r} isn't a M/D/YYYY date")
        weeks = [m]
        slack_weeks = {m}
    else:
        this_mon = _monday_of(now.date())
        weeks = _future_week_mondays(sh, this_mon, rolling_vals)
        slack_weeks = {this_mon, this_mon + dt.timedelta(days=7)}

    # --- events (fetched once, reused for every week) ------------------------
    if args.events:
        raw = json.load(open(args.events, encoding="utf-8"))
        events = [ev for e in raw
                  if (ev := parse.classify(e.get("sender", ""), e.get("subject", ""),
                                           e.get("body", ""), e.get("date", "")))]
        print(f"[events] {len(events)} parsed from {args.events}")
    else:
        events = email_source.fetch_events(since_days=args.since_days)

    # Who on the WHOLE checklist owns which result — the week-blind pairing the
    # name gate would otherwise make is the one bug this prevents.
    try:
        claimed_ids = name_gate.claimed_anywhere(rolling_vals, events)
    except Exception as e:  # noqa: BLE001
        print(f"[name-gate] global claim check skipped: {e}")
        claimed_ids = None

    upcoming = max(slack_weeks)  # the next-Monday cohort — the one worth a Friday bump
    print(f"[weeks] updating {len(weeks)} week(s) on the OBCL: "
          f"{', '.join(_fmt_week(w) for w in weeks)}")
    if args.names_from:
        names_from = match.parse_header_date(args.names_from)
        if names_from is None:
            raise SystemExit(f"--names-from {args.names_from!r} isn't a M/D/YYYY date")
        names_from = _monday_of(names_from)
    else:
        names_from = _monday_of(now.date()) + dt.timedelta(days=7)
    print(f"[name-gate] name corrections apply from the week of "
          f"{_fmt_week(names_from)} onward")

    ov_targets: list = [] if args.ov else None
    # With OwnerVille in play, hold the questions back until it has had a chance
    # to answer them itself.
    pending_asks: list = [] if args.ov else None
    for monday in weeks:
        do_slack = monday in slack_weeks
        # Friday-afternoon repost applies only to the UPCOMING week's thread.
        repost = (args.repost or
                  (monday == upcoming and now.weekday() == 4 and now.hour >= 12))
        process_week(sh, monday, events, dry_run=args.dry_run, do_post=args.post,
                     repost=repost, now=now, do_slack=do_slack,
                     rolling_vals=rolling_vals, claimed_ids=claimed_ids,
                     ov_targets=ov_targets, pending_asks=pending_asks,
                     names_from=names_from, refresh_asks=args.refresh_asks)

    if args.ov:
        try:
            settle_by_ownerville(sh, pending_asks or [], dry_run=args.dry_run,
                                 do_post=args.post, headless=not args.ov_headed,
                                 allow_login=args.ov_login)
        except Exception as e:  # noqa: BLE001
            print(f"[name-gate] OwnerVille proof pass skipped: "
                  f"{type(e).__name__}: {str(e).splitlines()[0][:160]}")
        # The OwnerVille pass is an extra; col K is the report. A browser that
        # won't open must never be what turns this run red.
        try:
            run_ov_pass(ov_targets or [], apply=args.ov_apply,
                        headless=not args.ov_headed,
                        allow_login=args.ov_login, only=args.ov_only or "")
        except Exception as e:  # noqa: BLE001
            print(f"[ov-names] pass skipped: "
                  f"{type(e).__name__}: {str(e).splitlines()[0][:160]}")


def run_ov_pass(targets: list, *, apply: bool, headless: bool,
                allow_login: bool = False, only: str = "") -> None:
    """The OwnerVille half: make each profile say what Sterling ran.

    Opt-in (`--ov`) and never part of the plain 3x/day pass — it drives a real
    browser through every campaign on View Progress, which is minutes of work
    and a profile lock the headless status sync has no reason to hold.
    """
    if only:
        # Scope a real OwnerVille edit to ONE person. The first time this writes
        # to anybody's profile it should write to exactly the profile somebody
        # is standing by to look at — the same reason report fills preview on
        # one tab before they touch fifty-two.
        want = only.strip().lower()
        targets = [t for t in targets if want in t.sheet_name.lower()]
        if not targets:
            print(f"[ov-names] --ov-only {only!r} matched nobody this run")
            return
        if len(targets) > 1:
            print(f"[ov-names] --ov-only {only!r} matched "
                  f"{', '.join(t.sheet_name for t in targets)} — be more specific")
            return
    if not targets:
        print("[ov-names] nothing to check")
        return
    print(f"[ov-names] checking {len(targets)} profile(s) in OwnerVille"
          f"{'' if apply else ' (dry run — no edits)'}")
    results = ov_name_sync.sync_names(targets, apply=apply, headless=headless,
                                      allow_login=allow_login)
    print(f"[ov-names] {ov_name_sync.summarise(results)}")
    for r in results:
        if r.action in ("would-edit", "edited", "refused"):
            print(f"  {r.action}: {r.sheet_name} — {r.reason}")
    if apply:
        try:
            state = name_gate.load_state()
            done = state.setdefault(OV_CHECKED_KEY, {})
            for r in results:
                if r.action in ("match", "edited"):
                    done[r.sheet_name] = r.legal_name
            name_gate.save_state(state)
        except Exception as e:  # noqa: BLE001
            print(f"[ov-names] state save skipped: {e}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="start-week date header (default: top block)")
    ap.add_argument("--events", help="JSON list of {sender,subject,body,date} (skip IMAP)")
    ap.add_argument("--since-days", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true", help="no sheet writes")
    ap.add_argument("--post", action="store_true", help="actually post/edit Slack")
    ap.add_argument("--refresh-asks", action="store_true",
                    help="rewrite questions already posted in Slack (same "
                         "messages, same reactions) instead of asking again")
    ap.add_argument("--names-from",
                    help="first start-week (M/D/YYYY) to correct names for; "
                         "earlier weeks are left alone (default: next Monday)")
    ap.add_argument("--ov", action="store_true",
                    help="also check OwnerVille profiles against Sterling "
                         "(browser; reports only unless --ov-apply)")
    ap.add_argument("--ov-only",
                    help="with --ov: check/edit ONE person's OwnerVille profile "
                         "(match on their checklist name) — the preview switch")
    ap.add_argument("--ov-apply", action="store_true",
                    help="with --ov: actually edit the OwnerVille profile names")
    ap.add_argument("--ov-login", action="store_true",
                    help="with --ov: open the OwnerVille login so you can sign "
                         "in (headed; you clear the 'verify you are human' box)")
    ap.add_argument("--ov-headed", action="store_true",
                    help="with --ov: watch the browser instead of running headless")
    ap.add_argument("--repost", action="store_true",
                    help="force a fresh repost of the thread (the Friday bump)")
    args = ap.parse_args(argv)
    if args.ov_apply or args.ov_headed or args.ov_login or args.ov_only:
        args.ov = True
    if args.ov_login:
        args.ov_headed = True      # somebody has to see the box to tick it

    # Tell the Hub we're running (yellow pill -> green on success). Never let a
    # Hub-publish hiccup break the actual report.
    hub_run_id = None
    if not args.dry_run:
        try:
            from automations.day_orchestrator import hub_publish
            hub_run_id = hub_publish.publish_running("bg_check_sync", "BG Check Sync")
        except Exception as e:  # noqa: BLE001
            print(f"[hub] publish_running skipped: {e}")

    # A CRASH has to close the Hub row too. Without this the run dies mid-way,
    # publish_done never fires, and the row sits at 'started' forever — the card
    # stays amber at 1/2 and NOTHING alerts, because a stuck row is
    # indistinguishable from a still-running one. That's how the 2026-08-17 4pm
    # pass (killed by a transient `imaplib.abort: FETCH => System Error`) went
    # unnoticed until Megan asked why the tile wasn't green. status="failed"
    # also opens the incident in #claudecorrections-and-requests via
    # hub_publish._alert_failure, and the next clean run closes it.
    try:
        _run(args)
    except Exception as e:  # noqa: BLE001 — report to the Hub, then re-raise
        _publish(hub_run_id, "failed")
        print(f"[hub] marked FAILED on the Hub: {type(e).__name__}: {e}")
        raise

    _publish(hub_run_id, "success")

    # Heartbeat for the watchdog — a real run only (not --dry-run). If this
    # stops updating, watchdog.py DMs Raf that the scheduler stalled.
    if not args.dry_run:
        try:
            from automations.bg_check_sync.watchdog import HEARTBEAT
            HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
            HEARTBEAT.write_text(dt.datetime.now().isoformat())
        except Exception as e:  # noqa: BLE001
            print(f"[heartbeat] skipped: {e}")

    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
