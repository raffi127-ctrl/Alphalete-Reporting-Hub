"""Watch the jobs that deliberately publish NOTHING.

Most automations are watched by being seen: they write a Hub Activity row, the
Hub colours a card, and machine_digest's 10-minute watcher notices when a report
that normally runs today hasn't. A few jobs cannot join that scheme, and their
reasons are good ones:

  org_board_box_repull   `--no-manifest` is LOAD-BEARING. It re-pulls ONE section
                         of the Org Sales Board minutes before the 07:05 post, so
                         a SUCCESS here must not call mark_clean("org-sales-board")
                         (that would flip a genuinely INCOMPLETE 04:50 board green
                         and drop its retry button) and a FAILURE must not paint a
                         perfect board orange. Neither verdict is this run's to
                         give, so it gives none.

  blueink_completed_sweep  Fires seven times a day (08:15-20:15) to tick the
                         "Blue Ink" box for packets people have signed. Publishing
                         each fire would bury the run that actually matters —
                         Monday's send — under seven ticks a day.

Both therefore `exit 0` unconditionally and write no manifest and no Activity
row. That was always the intended trade for the FAILURE case: a late Box is a
normal morning, a missed tick costs a stale checkbox. What it also bought,
unintentionally, was silence for the case nobody accepted — the job not firing
AT ALL. On 2026-08-26 both showed on the Hub as "no run logged" (from phantom
cards, since deleted) while Slack said nothing, because the didn't-run watcher
builds its baseline from Activity rows and neither has ever written one. Megan:
"do something for this."

WHAT THIS IS. A heartbeat, and nothing more. Each job stamps one row — the same
row, overwritten — in a "Job Heartbeats" tab when it finishes. A checker asks one
question: has this job checked in when it should have? If not, it opens the
ordinary incident thread in #claudecorrections-and-requests, and closes it again
when the job checks back in.

WHAT THIS IS DELIBERATELY NOT. It gives no verdict on any report. It writes no
manifest, publishes no Activity row, colours no card and creates none. That
separation is the whole point: the reason these two are silent is that their
success and failure must not speak for their parent report, and a watchdog that
reintroduced that coupling would be the bug, not the fix.

WHY A SHARED SHEET AND NOT A LOCAL FILE. bg_check_sync/watchdog.py — the proven
version of this idea — keeps its heartbeat on disk and checks it from the same
machine. That cannot report the failure where the MACHINE is the thing that
stopped, and our two jobs live on different boxes (Blue Ink on Lucy 2, the BOX
top-off on the mini). One shared tab lets the single 10-minute watcher on the
mini cover both, and cover "Lucy 2 is dead" as well. Cost is nine one-row writes
a day; the tab never grows past one row per job.

TIMEZONE. Every machine in the fleet runs Central and the checker runs on the
mini, so beats and deadlines are compared in plain local time. If a runner ever
moves out of Central this needs revisiting — see the launchd TZ-drift note in
day_orchestrator.

  python -m automations.shared.silent_job_watch --beat <job_id> [--exit N]
  python -m automations.shared.silent_job_watch --check [--dry-run]
  python -m automations.shared.silent_job_watch --status
"""
from __future__ import annotations

import argparse
import datetime as dt
import socket
from typing import Dict, List, Optional

SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"   # same book as Hub Activity
TAB = "Job Heartbeats"
HEADERS = ["Job ID", "Last Seen", "Machine", "Status", "Note"]


def _hm(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


# The jobs that publish nothing, and what silence from each one MEANS. Adding a
# job here is the whole registration: the checker reads this table and nothing
# else.
#
#   first_by        local HH:MM by which a beat dated TODAY must exist. This is
#                   what catches a stall on the same morning instead of a day
#                   later — it is the job's first pass plus a real grace, not a
#                   guess derived from history.
#   max_gap_min     for a job that fires repeatedly: the longest quiet stretch
#                   allowed between beats, checked until `active_until`. Set it
#                   above the normal interval so ONE skipped pass is tolerated
#                   (the wrappers skip a pass on purpose when the previous one is
#                   still running) and two in a row is not.
#   weekdays        Python weekday(); None means every day.
#   watch_from      deployment grace. Before this date the job is not watched at
#                   all, so shipping the heartbeat does not immediately alert
#                   about the passes that ran before it existed.
JOBS: Dict[str, dict] = {
    "org_board_box_repull": {
        "name": "Org Sales Board — BOX top-off",
        "machine": "the mini",
        "first_by": "07:15",       # passes at 06:52 + 06:58, ~2-5 min each
        "max_gap_min": None,       # one opportunity a day; first_by covers it
        "active_until": None,
        "weekdays": None,          # every day, incl. weekends
        "watch_from": "2026-08-28",
        "means": ("the 07:05 board post and the emailed picture will carry "
                  "YESTERDAY's Box numbers, which is the exact thing this job "
                  "was written to stop. Nothing else breaks and nothing waits "
                  "on it."),
        "fix": "lucy rerun install_org_board_box_repull_agent",
    },
    "blueink_completed_sweep": {
        "name": "Blue Ink completed-sweep",
        "machine": "Lucy 2",
        "first_by": "09:15",       # first pass 08:15 + 60 min grace
        "max_gap_min": 300,        # 2h cadence → 5h tolerates one skipped pass
        "active_until": "21:15",   # last pass 20:15 + grace
        "weekdays": None,
        "watch_from": "2026-08-28",
        "means": ("the \"Blue Ink\" checkboxes stop tracking who has signed, so "
                  "the OBCL will read stale until someone notices by hand. "
                  "Nothing is sent or lost — only the ticks go cold."),
        "fix": "lucy rerun install_blueink_sweep_agent --machine \"Lucy 2\"",
    },
}


# ------------------------------------------------------------------ the sheet
def _ws(create: bool = False):
    """The heartbeat tab. `create=False` for every READ path: a checker that
    creates the thing it is checking would turn "this tab was never set up" into
    a silent pass, which is the failure mode this whole module exists to end.
    Only beat() — a job proving it ran — is allowed to bring the tab into being."""
    from automations.recruiting_report.fill import open_by_key
    import gspread as _gs
    sh = open_by_key(SHEET_ID)
    try:
        return sh.worksheet(TAB)
    except _gs.WorksheetNotFound:
        if not create:
            raise
        ws = sh.add_worksheet(title=TAB, rows=50, cols=len(HEADERS))
        ws.update([HEADERS], "A1:E1")
        return ws


def beat(job_id: str, *, ok: bool = True, note: str = "") -> bool:
    """Record that `job_id` just finished. Upserts ONE row, so the tab stays the
    size of JOBS however many times a day the job fires.

    Best-effort and silent by contract: a job must never fail, and must never
    change its exit code, because it could not reach the heartbeat sheet. The
    caller is a wrapper that already `exit 0`s unconditionally."""
    try:
        from automations.recruiting_report.fill import _retry
        ws = _ws(create=True)
        row = [job_id, dt.datetime.now().isoformat(timespec="seconds"),
               socket.gethostname(), "ok" if ok else "failed", note]
        try:
            found = ws.find(job_id, in_column=1)
        except Exception:
            found = None
        if found:
            _retry(lambda: ws.update([row], "A%d:E%d" % (found.row, found.row),
                                     value_input_option="RAW"))
        else:
            _retry(lambda: ws.append_row(row, value_input_option="RAW"))
        return True
    except Exception:  # noqa: BLE001 — never let a heartbeat sink its job
        return False


def read_beats() -> Dict[str, dict]:
    """{job_id: {'last_seen': datetime|None, 'machine': str, 'status': str}}."""
    out: Dict[str, dict] = {}
    try:
        recs = _ws().get_all_records()
    except Exception:  # noqa: BLE001
        # No tab yet, or the sheet is unreachable. Returning {} means every job
        # reads as "never checked in", which `overdue()` reports as overdue past
        # its deadline — loud, and correct: we genuinely cannot tell whether
        # these ran. `watch_from` is what keeps that from firing on day one.
        return out
    for r in recs:
        jid = str(r.get("Job ID") or "").strip()
        if not jid:
            continue
        try:
            seen = dt.datetime.fromisoformat(str(r.get("Last Seen") or "").strip())
        except Exception:
            seen = None
        out[jid] = {"last_seen": seen,
                    "machine": str(r.get("Machine") or ""),
                    "status": str(r.get("Status") or "").strip().lower()}
    return out


# ----------------------------------------------------------------- the check
def overdue(now: Optional[dt.datetime] = None,
            beats: Optional[Dict[str, dict]] = None) -> List[dict]:
    """Jobs that should have checked in by now and haven't.

    Two independent ways to be late, because the two jobs fail differently:
    a once-a-morning job is late when TODAY has produced no beat by its
    deadline, and a repeating job is late when it has gone quiet for longer
    than its cadence allows. Either one alone would miss the other's stall."""
    now = now or dt.datetime.now()
    beats = read_beats() if beats is None else beats
    today = now.date()
    late: List[dict] = []
    for jid, spec in JOBS.items():
        wd = spec.get("weekdays")
        if wd is not None and now.weekday() not in wd:
            continue
        try:
            if today < dt.date.fromisoformat(spec["watch_from"]):
                continue                      # not armed yet — deployment grace
        except Exception:
            pass
        seen = (beats.get(jid) or {}).get("last_seen")

        # 1) Nothing today by the deadline.
        if now.time() >= _hm(spec["first_by"]):
            if seen is None or seen.date() < today:
                late.append({**spec, "job_id": jid, "last_seen": seen,
                             "why": "no run today by %s" % spec["first_by"]})
                continue

        # 2) Repeating job that has gone quiet mid-day.
        gap = spec.get("max_gap_min")
        until = spec.get("active_until")
        if gap and seen is not None and (not until or now.time() <= _hm(until)):
            quiet = (now - seen).total_seconds() / 60.0
            if quiet > gap and now.time() >= _hm(spec["first_by"]):
                late.append({**spec, "job_id": jid, "last_seen": seen,
                             "why": "no run for %d min (allowed %d)"
                                    % (int(quiet), gap)})
    return late


def healthy(now: Optional[dt.datetime] = None,
            beats: Optional[Dict[str, dict]] = None) -> List[str]:
    """Job ids that are currently checking in as they should — the set whose
    incident threads should be closed."""
    now = now or dt.datetime.now()
    beats = read_beats() if beats is None else beats
    bad = {j["job_id"] for j in overdue(now, beats)}
    return [j for j in JOBS if j not in bad and (beats.get(j) or {}).get("last_seen")]


# ------------------------------------------------------------------- runners
def _fmt_seen(seen: Optional[dt.datetime]) -> str:
    return "never" if seen is None else seen.strftime("%a %-d %b %H:%M")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="silent_job_watch")
    ap.add_argument("--beat", metavar="JOB_ID",
                    help="record that this job just finished")
    ap.add_argument("--exit", type=int, default=0,
                    help="the job's exit code (non-zero records a failed beat)")
    ap.add_argument("--note", default="")
    ap.add_argument("--check", action="store_true",
                    help="print which jobs are overdue (read-only)")
    ap.add_argument("--status", action="store_true",
                    help="print every job's last check-in")
    args = ap.parse_args(argv)

    if args.beat:
        if args.beat not in JOBS:
            print("unknown job %r — known: %s" % (args.beat, ", ".join(sorted(JOBS))))
            return 1
        ok = beat(args.beat, ok=(args.exit == 0), note=args.note)
        print("heartbeat %s for %s" % ("recorded" if ok else "FAILED", args.beat))
        return 0                      # never non-zero: the caller must not care

    if args.status or args.check:
        beats = read_beats()
        now = dt.datetime.now()
        late = {j["job_id"]: j for j in overdue(now, beats)}
        for jid, spec in sorted(JOBS.items()):
            seen = (beats.get(jid) or {}).get("last_seen")
            flag = ("OVERDUE — %s" % late[jid]["why"]) if jid in late else "ok"
            print("  %-24s last %-18s %s" % (jid, _fmt_seen(seen), flag))
        if args.status:
            # A clock time here past the job's first_by is NOT by itself late, and
            # reading it that way costs a morning (Megan 2026-08-27: this column
            # said 07:20 against a 07:15 deadline while the job was in fact fine).
            # beat() keeps ONE row per job, so a job that fires more than once a
            # day overwrites its own row and this shows the LAST pass — today's
            # box re-pull met 07:15 on its 06:52 pass at 06:55, then a slow 06:58
            # pass stamped 07:20 over it. Use the `ok` / `OVERDUE` flag, which is
            # what overdue() actually computes: a same-DAY beat clears first_by.
            print("\n  'last' = most recent beat. A job with several passes a day"
                  "\n  overwrites its own row, so this can be a later pass than the"
                  "\n  one that made the deadline — trust the flag, not the clock.")
        if args.check and late:
            print("\n%d job(s) overdue." % len(late))
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
