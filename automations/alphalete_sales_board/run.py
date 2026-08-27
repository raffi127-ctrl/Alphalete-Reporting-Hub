"""Alphalete Sales Board -- SaraPlus sweep, every 5 minutes of the selling day.

    python -m automations.alphalete_sales_board.run                # PREVIEW
    python -m automations.alphalete_sales_board.run --apply        # write board
    python -m automations.alphalete_sales_board.run --apply --send # + notify
    python -m automations.alphalete_sales_board.run --date 2026-08-25 --force

ONE SWEEP: log into SaraPlus, read the day's three ReportingHub grids, work out
each rep's Int / Int Up / DTV / NL, write TODAY's block on this week's Sales
Board tab, and announce whatever went up since the last sweep.

WHY IT RUNS ON LUCY 1 (Megan 2026-08-26). Lucy 1 is the busiest runner -- ~130
reports in the 4am batch -- and on load alone this belongs on Lucy 3, which is
nearly idle after 8:30am. It is here because of the TEXTS: the two chats live in
Lucy 1's Messages (alphaletereporting@, the account owner_chat_texts already
sends the owner trackers from) and Lucy 3's chat.db has no Alphalete groups at
all. Splitting the sweep -- scrape on Lucy 3, text from Lucy 1 -- would trade a
quiet box for a cross-machine handoff of state that is re-read every five
minutes, which is the shape of dependency this repo has been burned by before.

SO THE LOAD IS FENCED INSTEAD, four ways:
  1. its OWN Chrome profile (automations/uploaded/.saraplus_profile), so it can
     never collide with the Tableau/ownerville `.browser_profile` the 4am batch
     holds, and chrome_guard protects it like the others;
  2. HEADLESS, and SaraPlus is plain old ASP.NET -- no real-Chrome channel, no
     bot-detection dance, so a sweep is a short-lived process, not a session;
  3. it does not start until 07:00, after the batch's browser-heavy wave. This
     costs nothing: SaraPlus is CUMULATIVE within a day, so the first sweep
     reads the whole morning at once;
  4. a pid lock, so a slow sweep is skipped rather than stacked -- 150 runs a
     day is exactly where an overlapping-run bug turns into 300.

WHAT IT WILL NOT DO: write any day but today, blank a number, overwrite a
roll-call letter, or touch Apps / Roll Call. See fill.py.

THE HUB PILL IS PUBLISHED ONCE A DAY, on the first sweep that succeeds -- a
green pill 150 times over would say nothing. Failures are counted instead: one
alert after FAIL_STREAK consecutive failures, then a cooldown, because a
SaraPlus outage at 9am must not post 150 incidents by lunch.
[[feedback_launchd_reports_must_publish]]

Python 3.9-safe (Lucy runtime). Cross-platform: no Mac-only calls except the
iMessage leg, which is skipped when --send is off.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.alphalete_sales_board import aliases, calc, config as C, fill
from automations.alphalete_sales_board import notify as N
from automations.alphalete_sales_board import sara, state as S
from automations.rep_sales_fill import board as B
from automations.shared import name_case

HUB_CARD_ID = "alphalete-sales-board"
HUB_CARD_NAME = "Sales Text Updates"
FAIL_STREAK = 3                     # ~15 minutes of failures before we speak
ALERT_COOLDOWN_HOURS = 2
CORRECTIONS_CHANNEL = "C0BK5PRG259"  # #claudecorrections-and-requests
INCIDENT_KEY = "alphalete_sales_board"   # incident_thread key = the report id
FAIL_PATH = Path.home() / ".config" / "recruiting-report" / "alphalete_sales_board_fails.json"


def _log(msg: str = "") -> None:
    print(msg, flush=True)


# --- singleton lock ---------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


class Lock:
    """Skip this sweep if the last one is still going. A sweep that waited
    would just queue behind the next tick; there is another one in 5 minutes."""

    def __init__(self, path: Path = None):
        self.path = path or C.LOCK_PATH
        self.held = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                pid = int(self.path.read_text().strip() or 0)
            except (ValueError, OSError):
                pid = 0
            if pid and _pid_alive(pid):
                return self
            self.path.unlink(missing_ok=True)
        self.path.write_text(str(os.getpid()))
        self.held = True
        return self

    def __exit__(self, *exc):
        if self.held:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass


# --- failure streak ---------------------------------------------------------
def _fails() -> Dict:
    try:
        return json.loads(FAIL_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _record_failure(err: str, *, dry_run: bool) -> None:
    """Count it, and speak once the streak says this is not a blip."""
    data = _fails()
    data["streak"] = int(data.get("streak", 0)) + 1
    data["last_error"] = err[:400]
    data["last_at"] = dt.datetime.now().isoformat(timespec="seconds")
    streak = data["streak"]
    _log("failure #%d: %s" % (streak, err[:200]))

    should_alert = streak >= FAIL_STREAK
    last_alert = data.get("alerted_at")
    if should_alert and last_alert:
        try:
            age = (dt.datetime.now()
                   - dt.datetime.fromisoformat(last_alert)).total_seconds() / 3600.0
            if age < ALERT_COOLDOWN_HOURS:
                should_alert = False
        except ValueError:
            pass

    if should_alert and not dry_run:
        # Through incident_thread, NOT a bare chat_postMessage. The first
        # version posted the alert directly, which meant it could never be
        # closed: the ✅ is put on by the code when the report next runs clean,
        # and only a post the machinery OPENED can be found again. The 20:00
        # alert on the first night live sat open with its cause already fixed.
        # [[project_corrections_slack_channel]]
        try:
            from automations.shared import incident_thread
            incident_thread.open_or_followup(
                key=INCIDENT_KEY,
                title="%s has failed %d passes in a row" % (HUB_CARD_NAME, streak),
                body=["The board is not updating and the chats are getting "
                      "nothing."],
                details=["```", err[:1500], "```"],
                followup=["Re-run once the cause is clear: "
                          "`lucy rerun alphalete_sales_board --apply --send`"],
                label=HUB_CARD_NAME)
            data["alerted_at"] = dt.datetime.now().isoformat(timespec="seconds")
        except Exception as e:  # noqa: BLE001 — an alert must never crash the sweep
            _log("alert failed: %s: %s" % (type(e).__name__, str(e)[:120]))

    _write_fails(data)


def _write_fails(data: Dict) -> None:
    try:
        FAIL_PATH.parent.mkdir(parents=True, exist_ok=True)
        FAIL_PATH.write_text(json.dumps(data, indent=1))
    except OSError:
        pass


def _clear_failures() -> None:
    data = _fails()
    if data.get("streak"):
        _log("recovered after %d failed pass(es)" % data["streak"])
    # Free when nothing is open (a local index read, no Slack call), so it is
    # safe on every clean sweep -- which is what puts the ✅ on the alert
    # instead of leaving it open with the cause long fixed.
    try:
        from automations.shared import incident_thread
        incident_thread.resolve_if_open(
            INCIDENT_KEY, what="*%s*" % HUB_CARD_NAME,
            detail="The sweep ran clean: the board is filling and the chats "
                   "are getting the standings again.")
    except Exception as e:  # noqa: BLE001 — closing must never break the run
        _log("couldn't close the incident: %s: %s" % (type(e).__name__, str(e)[:120]))
    _write_fails({"streak": 0, "recovered_at": dt.datetime.now().isoformat(timespec="seconds")})


# --- week to date -----------------------------------------------------------
def week_to_date(grid, upto: dt.date) -> int:
    """Org total Mon..`upto` off the board itself -- Int + Int Up + DTV + NL,
    the board's own 'Total Units'. Read from the sheet rather than accumulated
    locally so a hand correction is reflected."""
    blocks = B.day_blocks(grid)
    last = B.last_rep_row(grid)
    days = [(upto - dt.timedelta(days=upto.weekday() - i)).strftime("%A")
            for i in range(upto.weekday() + 1)]
    total = 0
    for day_name in days:
        cols = blocks.get(day_name) or {}
        # Upgrades INCLUDED, because the board's own week rows count them:
        # 'WE 6/2 - 6/8' reads Total Units 213 against INT 128 + INT UP 42 +
        # DTV 8 + NL 36. Leaving them out made the goal line disagree with the
        # TOTALS line directly above it (2026-08-26).
        for metric in ("Int", "Int Up", "DTV", "NL"):
            col = cols.get(metric)
            if not col:
                continue
            for r in range(B.SUB_ROW + 1, last + 1):
                v = B.cell(grid, r, col).strip()
                if v.isdigit():
                    total += int(v)
    return total


# --- one sweep --------------------------------------------------------------
def sweep(day: dt.date, *, apply_writes: bool, send: bool, headless: bool = True) -> int:
    scraped = sara.scrape(day, headless=headless, log=_log)
    agents, records = scraped["agents"], scraped["records"]

    ws = fill.open_tab(day)
    grid = ws.get_all_values()
    names = fill.board_names(grid)
    _log("board tab %r: %d reps on the roster" % (ws.title, len(names)))

    alias_map = aliases.load()
    if alias_map:
        _log("%d alias(es) from the %r tab" % (len(alias_map), aliases.TAB))
    rows, notes, missing = calc.calculate(agents, names, alias_map)
    for n in notes:
        _log("  note: %s" % n)

    updates, plan_notes = fill.plan(grid, day, rows)
    for n in plan_notes:
        _log("  note: %s" % n)

    if apply_writes and updates:
        changed = fill.apply(ws, updates)
        _log("wrote %d cell(s) to %s" % (changed, ws.title))
    else:
        _log("%d cell(s) would change (preview)" % len(updates))
        for u in updates[:15]:
            _log("    %s -> %r" % (u["range"], u["values"][0][0]))

    # Who is on the board today that our pull can't explain? (See fill.
    # board_only_reps.) Logged every sweep so a pattern is visible in one grep.
    accounted = [r["board_name"] for r in rows] + [
        n for n in names if any(a.get("name") and
                                calc.match_name(a["name"], [n])[0] == n
                                for a in agents)]
    board_only = fill.board_only_reps(grid, day, accounted)
    if board_only:
        _log("COVERAGE: %d rep(s) have numbers on the board today that SaraPlus "
             "did not give us: %s" % (len(board_only), ", ".join(board_only)))
    else:
        _log("COVERAGE: every rep with numbers on today's board is one we pulled")

    # --- a rep who sold but has no row gets one, now -------------------------
    # Megan 2026-08-26: say in the text that they weren't on the board, that
    # they were added, and that their numbers land next sweep. Next sweep and
    # not this one because the row has to exist before plan() can find it, and
    # re-reading the whole tab to fill one rep would double every sweep's Sheets
    # work for a case that happens a few times a week.
    for item in missing:
        if not apply_writes:
            item["status"] = "would be added"
            continue
        clash = fill.near_matches(item["sara_name"], names)
        if clash:
            item["status"] = (
                "NOT added - could be %s already on the board. Same person? "
                "Add a row to the '%s' tab (SaraPlus Name | Board Name). "
                "Different person? Type their name into a blank roster row."
                % (" or ".join(clash[:2]), aliases.TAB))
            _log("  %s: %s" % (item["sara_name"], item["status"]))
            continue
        row, note = fill.add_rep(ws, grid, name_case.titlecase_name(item["sara_name"]))
        if row is None:
            item["status"] = note
        else:
            item["status"] = "wasn't on the board - added, numbers fill next sweep"
            _log("  added %s to row %d" % (item["sara_name"], row))

    # --- what is NEW since the last sweep -----------------------------------
    data = S.load()
    today = {r["board_name"]: r["metrics"] for r in rows}
    gained = S.deltas(data, day, today)
    rec_gained = S.record_deltas(data, day, records)

    # BASELINE PASS. With no state for today, EVERY sale reads as new -- so the
    # first sweep after a cutover, a state-file loss, or a mid-day start would
    # fire one hype line per rep and one credit-check line per rep. On the day
    # this shipped that was 11 + 31 = 42 Slack messages and a leaderboard with a
    # flame beside every name, announcing as "just now" sales that happened
    # hours ago. So the first sweep of a day SETTLES rather than celebrates: one
    # leaderboard with the true picture, no flames, no per-sale hype, no credit
    # -check pings. From the next sweep on, deltas mean what they say.
    baseline = not (data.get(day.isoformat()) or {})
    if baseline and (gained or rec_gained):
        _log("BASELINE pass (no state for %s yet): sending the standings once, "
             "with no per-sale hype for %d rep(s) and no credit-check pings for "
             "%d" % (day.isoformat(), len(gained), len(rec_gained)))
    _log("new this sweep: %d rep(s) with sales, %d with credit checks"
         % (len(gained), len(rec_gained)))

    if gained or rec_gained or missing:
        wtd = week_to_date(grid, day) if apply_writes else None
        body = N.leaderboard(today, [] if baseline else list(gained), wtd, missing,
                             goal=fill.board_goal(grid))
        if gained or (baseline and today):
            for group in C.LIVE_GROUPS:
                N.text_group(group, body, dry_run=not send, log=_log)
        if not baseline:
            for rep, delta in sorted(gained.items()):
                N.slack(N.hype(rep, delta, day), dry_run=not send, log=_log)
            for rep, up in sorted(rec_gained.items()):
                N.slack(N.records_line(rep, records.get(rep, up), up),
                        dry_run=not send, log=_log)

    if C.lvl1_due() and not S.lvl1_sent(data, day):
        # One resolve+send per room. A group that can't be resolved must not
        # cost the others their scoreboard, so each is attempted on its own.
        # flag_missing=False: the players see the sales, not the paperwork.
        body = N.leaderboard(today, [], week_to_date(grid, day), missing,
                             goal=fill.board_goal(grid), flag_missing=False)
        for group in C.END_OF_DAY_GROUPS:
            try:
                N.text_group(group, body, dry_run=not send, log=_log)
            except Exception as e:  # noqa: BLE001
                _log("  %s FAILED: %s: %s" % (group, type(e).__name__, str(e)[:160]))
        if send:
            data = S.mark_lvl1_sent(data, day)

    if apply_writes:
        data = S.remember(data, day, today, records)
        S.save(data)
    else:
        _log("(preview: state not updated, so the next preview says the same)")
    return len(updates)


def _publish_hub_once(day: dt.date) -> None:
    """First good sweep of the day paints the card; the other 149 stay quiet."""
    data = S.load()
    key = day.isoformat()
    if (data.get("_hub") or {}).get(key):
        return
    try:
        from automations.shared import hub_activity
        hub_activity.log_completed(HUB_CARD_ID, HUB_CARD_NAME, status="success")
        data.setdefault("_hub", {})[key] = True
        S.save(data)
    except Exception as e:  # noqa: BLE001 — the Hub row must never fail the sweep
        _log("hub publish skipped: %s: %s" % (type(e).__name__, str(e)[:120]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", help="YYYY-MM-DD (default today)")
    ap.add_argument("--apply", action="store_true",
                    help="write the board (default: preview only)")
    ap.add_argument("--send", action="store_true",
                    help="send the iMessages and Slack posts")
    ap.add_argument("--force", action="store_true",
                    help="run outside the selling-day window")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit preview (the default; here for the house flag)")
    ap.add_argument("--probe-grid", action="store_true",
                    help="READ-ONLY: dump a grid's headers + first rows with "
                         "column indexes, to check the COL_* mapping")
    ap.add_argument("--service", default="AT&T Internet",
                    help="which grid --probe-grid dumps")
    ap.add_argument("--probe", action="store_true",
                    help="READ-ONLY: log in and dump what the ReportingHub page "
                         "actually contains (for when a selector goes missing)")
    args = ap.parse_args(argv)

    if args.probe_grid:
        try:
            sara.probe_grid(args.service, headless=not args.headed, log=_log)
        except Exception as e:  # noqa: BLE001
            _log("PROBE FAILED: %s: %s" % (type(e).__name__, str(e)[:400]))
            return 1
        _log("=== done ===")
        return 0

    if args.probe:
        # Deliberately ahead of the window gate: you diagnose when you can, not
        # only between 7 and 9:30.
        try:
            sara.probe(headless=not args.headed, log=_log)
        except Exception as e:  # noqa: BLE001
            _log("PROBE FAILED: %s: %s" % (type(e).__name__, str(e)[:400]))
            return 1
        _log("=== done ===")
        return 0

    day = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
           if args.date else dt.date.today())
    apply_writes = args.apply and not args.dry_run
    send = args.send and not args.dry_run

    if not args.force and not C.in_selling_window():
        _log("outside the selling day (%s-%s, Mon-Sat) -- nothing to do"
             % ("%02d:%02d" % C.DAY_START_HHMM, "%02d:%02d" % C.DAY_END_HHMM))
        return 0

    with Lock() as lock:
        if not lock.held:
            _log("another sweep is still running -- skipping this tick")
            return 0
        try:
            sweep(day, apply_writes=apply_writes, send=send,
                  headless=not args.headed)
        except Exception as e:  # noqa: BLE001
            _record_failure("%s: %s" % (type(e).__name__, e), dry_run=not send)
            return 1

    _clear_failures()
    if apply_writes:
        _publish_hub_once(day)
    _log("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
