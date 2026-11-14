# -*- coding: utf-8 -*-
"""Every AppStream pull the Applicant Stream Grade Card needs, then the card.

Megan 2026-11-13:
  * "we should pull 6 weeks always of data for this to start and then
    ongoing the last 2 completed weeks so that we get anything changed"
  * "when we pull the previous week for that week to catch changes, we only
    need to pull the trend page numbers. We don't have to pull the text
    email setup audit. And then we should run this on Sunday. That way they
    have a full Monday to Saturday completed week."

So:
  --initial   6 finished Mon-Sat weeks of bookings + texts, the setup
              audit (AI Settings, templates), the Trend numbers, the card.
  (weekly)    run on SUNDAY: the Mon-Sat week that just finished, in full
              (bookings, texts, setup audit), plus the Trend numbers — which
              re-pull every recent week, so the week before is refreshed
              there and only there.

The bookings dump (sms_thread_dump) and the SMS log (pull_log) each
OVERWRITE their file on every run. This keeps a merged copy: a week that is
pulled again replaces that week's rows, older weeks are kept, and anything
older than KEEP_WEEKS is dropped. The card reads the merged files.

    python -m automations.applicant_stream_card.pull_all --office 11280 --initial
    python -m automations.applicant_stream_card.pull_all --office 11280

Read-only in AppStream. Writes the usual output/ files and control-sheet
tabs, then output/applicant-stream-card-<id>.html. Posts and sends nothing.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output"
KEEP_WEEKS = 6


def mon_sat_weeks(n, today=None):
    """[(monday, saturday)] for the last `n` FINISHED Mon-Sat weeks, oldest
    first. On a Sunday the week that ended yesterday is the newest."""
    today = today or dt.date.today()
    # The most recent Saturday strictly before today.
    sat = today - dt.timedelta(days=(today.weekday() - 5) % 7 or 7)
    return [(sat - dt.timedelta(days=5 + 7 * i), sat - dt.timedelta(days=7 * i))
            for i in range(n - 1, -1, -1)]


def _day(s):
    """'10-19-2026 12:47 AM' / '10-19-2026' -> date, or None."""
    try:
        return dt.datetime.strptime((s or "").strip()[:10], "%m-%d-%Y").date()
    except ValueError:
        return None


def _rec_day(r):
    return _day(r.get("date"))


def _log_day(r):
    return _day(r.get("sent_at")) or _day(r.get("queued_at"))


def merge(store, fresh, first, last, day_of):
    """`store` with every row dated first..last replaced by `fresh`."""
    kept = [r for r in store
            if not (day_of(r) and first <= day_of(r) <= last)]
    return kept + list(fresh)


def trim(rows, since, day_of):
    return [r for r in rows if day_of(r) and day_of(r) >= since]


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(path, rows):
    path.write_text(json.dumps(rows, indent=1, ensure_ascii=False),
                    encoding="utf-8")


def _run(name, *args):
    """One puller as its own process (each opens and closes its own
    AppStream session). Returns True on exit 0."""
    log = OUTPUT / "audit-logs"
    log.mkdir(parents=True, exist_ok=True)
    out = log / "{}.log".format(name)
    t0 = dt.datetime.now()
    print("[pull_all] {} ...".format(name), flush=True)
    with out.open("w", encoding="utf-8") as fh:
        rc = subprocess.call([sys.executable, "-m"] + list(args),
                             cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT)
    print("[pull_all] {} {} in {:.0f} min (log: {})".format(
        name, "ok" if rc == 0 else "FAILED rc={}".format(rc),
        (dt.datetime.now() - t0).total_seconds() / 60, out), flush=True)
    return rc == 0


def _fmt(d):
    return d.strftime("%m-%d-%Y")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--office", default="11280")
    ap.add_argument("--initial", action="store_true",
                    help="first run: 6 weeks of bookings + texts")
    ap.add_argument("--weeks", type=int, default=0,
                    help="pull the last N finished weeks and merge them in "
                         "(e.g. 2 to redo weeks a run missed)")
    ap.add_argument("--skip-setup", action="store_true",
                    help="leave AI Settings + templates as they are")
    a = ap.parse_args(argv)
    oid = a.office.strip()
    dump_p = OUTPUT / "sms_thread_dump_{}.json".format(oid)
    log_p = OUTPUT / "sms_log_{}.json".format(oid)
    # A machine that has never pulled this office (a Lucy on its first
    # Sunday) has no saved weeks to add one to: do the 6-week first pull.
    if not a.initial and not (_load(dump_p) and _load(log_p)):
        print("[pull_all] {}: no saved weeks here yet — doing the 6-week "
              "first pull".format(oid), flush=True)
        a.initial = True
    weeks = mon_sat_weeks(KEEP_WEEKS if a.initial else (a.weeks or 1))
    since = mon_sat_weeks(KEEP_WEEKS)[0][0]
    print("[pull_all] {}: {} week(s), {} to {}".format(
        oid, len(weeks), weeks[0][0], weeks[-1][1]), flush=True)
    ok = {}

    if not a.skip_setup:
        ok["ai_settings"] = _run("ai-settings-" + oid,
                                 "automations.sms_audit.pull_ai_settings",
                                 "--office", oid)
        ok["templates"] = _run("templates-" + oid,
                               "automations.as_templates_probe.run",
                               "--office", oid, "--all")
    # Re-pulls every recent week, so last week's late changes land here.
    ok["vitals"] = _run("vitals-" + oid, "automations.applicant_stream_card.vitals",
                        "--office", oid)

    # The pullers overwrite these files, so hold the merged copy in memory.
    dump = [] if a.initial else _load(dump_p)
    log = [] if a.initial else _load(log_p)
    for first, last in weeks:
        label = "{}_{}".format(_fmt(first), oid)
        got = _run("sms-log-" + label, "automations.sms_audit.pull_log",
                   "--office", oid, "--dates",
                   "{},{}".format(_fmt(first), _fmt(last)))
        if got:
            log = merge(log, _load(log_p), first, last, _log_day)
        ok["texts " + _fmt(first)] = got
        days = [first + dt.timedelta(days=i) for i in range(6)]
        if _run("bookings-" + label, "automations.sms_thread_dump.run",
                "--office", oid, "--actions", "--dates",
                ",".join(_fmt(d) for d in days)):
            dump = merge(dump, _load(dump_p), first, last, _rec_day)
            ok["bookings " + _fmt(first)] = True
        else:
            ok["bookings " + _fmt(first)] = False
        # Write the merged copy after every week, so a failure later keeps it.
        _save(dump_p, trim(dump, since, _rec_day))
        _save(log_p, trim(log, since, _log_day))

    ok["card"] = _run("card-" + oid, "automations.applicant_stream_card.run",
                      "--office", oid)
    bad = [k for k, v in ok.items() if not v]
    print("[pull_all] {} done: {} of {} parts ok{}".format(
        oid, len(ok) - len(bad), len(ok),
        "" if not bad else " — FAILED: " + ", ".join(bad)), flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
