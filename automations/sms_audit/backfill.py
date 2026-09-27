"""Backfill — pull and file several past recruiting weeks for several
accounts, one week at a time.

Megan 2026-09-27: "I want the past full 6 weeks ran and filled for these 4
accounts."

WHY A DRIVER AND NOT SIX HAND RUNS. Both pulls write to ONE slot per office —
tab "SMS Log <office>" and output/sms_log_<office>.json — and the next week
overwrites it. So a week has to be pulled, brought down to a local file
STAMPED WITH ITS WEEK, and written into the sheet before the following week
is pulled. Six weeks times four accounts times two pulls is forty-eight
steps in a fixed order; doing that by hand is how a week ends up filed under
the wrong column.

  python -m automations.sms_audit.backfill --office 11280,23965,24065,11580 --weeks 6
  ... backfill.py --weeks 6 --skip-pull      # re-file from files already down
  ... backfill.py --weeks 2 --dry-run        # print the plan, touch nothing

Each week runs: queue the bookings walk on Lucy 2 → wait → download →
queue the message log → wait → download → write that week's column. The
download is stamped `w<N>` so `weekly_sheet --suffix w<N>` finds both halves
of the SAME week — mismatching them is what once gave a column its reply
speeds from a different week entirely.

Nothing here writes to Slack, and every AppStream read is read-only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO / "output"
CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
MACHINE = "Lucy 2"
POLL_SECONDS = 45
WAIT_MINUTES = 40


def _py():
    venv = REPO / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def _run(args, **kw):
    return subprocess.run([_py(), "-m"] + args, cwd=str(REPO),
                          capture_output=True, text=True,
                          env=dict(_env(), PYTHONPATH="."), **kw)


def _env():
    import os
    return os.environ.copy()


CONTROL_TAB = "Mini Control - {}".format(MACHINE)
TERMINAL = ("done", "failed")


def enqueue(action_args):
    out = _run(["automations.day_orchestrator.mini_control", "--by", "Megan",
                "--enqueue"] + action_args + ["--machine", MACHINE])
    print("   queued: {}".format(" ".join(action_args))[:200], flush=True)
    return out.returncode == 0


def _queue_rows():
    from automations.recruiting_report import fill as _fill
    try:
        ws = _fill._client().open_by_key(CONTROL_SHEET_ID).worksheet(CONTROL_TAB)
        return ws.get_all_records()
    except Exception as e:  # noqa: BLE001 — a transient read must not end the run
        # Said out loud: an empty read and a job still running look the same
        # to the caller, and this sheet does hit its 60-reads-a-minute cap
        # while a pull is writing thousands of rows into it.
        print("   (queue read failed: {} — retrying)".format(
            type(e).__name__), flush=True)
        return []


def wait_queue(args_text, minutes=WAIT_MINUTES):
    """Block until the newest queue row carrying `args_text` has FINISHED.

    The tab meta alone cannot tell a job that is still running from one that
    ran and wrote nothing: a pull that scrapes no rows leaves the tab alone
    on purpose, so its meta never advances and a meta-only wait burns the
    whole timeout on a job that ended minutes ago. That cost 40 minutes a
    week on 24065, which is a new account with no bookings that far back.

    So the queue answers "is it over" and the meta answers "which week is in
    the tab" — the second is still the only thing safe to download from."""
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        hits = [r for r in _queue_rows() if args_text in str(r.get("Args", ""))]
        if hits:
            status = str(hits[-1].get("Status", "")).strip().lower()
            if status in TERMINAL:
                print("   queue says {} ({})".format(status, args_text[:60]),
                      flush=True)
                return status
        time.sleep(POLL_SECONDS)
    print("   queue never finished after {} min".format(minutes), flush=True)
    return "timeout"


def fresh_tabs(tabs, want):
    """Of `tabs`, the ones whose meta now names the week we asked for.

    A tab that did not advance is NOT an error — an office with no bookings
    in that week leaves its tab untouched by design. It is skipped for the
    week and said out loud, rather than downloaded and filed under a column
    it did not come from."""
    ok, stale = [], []
    for t in tabs:
        (ok if want in _tab_meta(t) else stale).append(t)
    for t in stale:
        print("   {} did not advance — no data for this week, skipping"
              .format(t), flush=True)
    return ok


def _tab_meta(tab):
    """Row 1 of a pull's tab is its meta line — the range it covers."""
    from automations.recruiting_report import fill as _fill
    try:
        ws = _fill._client().open_by_key(CONTROL_SHEET_ID).worksheet(tab)
        return ws.acell("A1").value or ""
    except Exception:  # noqa: BLE001 — tab not created yet
        return ""


def download(prefix, tab_prefix, office, tag):
    """Bring a pull's tab down to output/<prefix>_<office>_<tag>.json."""
    from automations.recruiting_report import fill as _fill
    ws = _fill._client().open_by_key(CONTROL_SHEET_ID).worksheet(
        "{} {}".format(tab_prefix, office))
    vals = ws.get_all_values()
    if len(vals) < 3:
        return 0
    hdr = vals[1]
    if prefix == "sms_thread_dump":
        recs = []
        for row in vals[2:]:
            d = dict(zip(hdr, row))
            try:
                d["thread"] = json.loads(d.pop("thread_json") or "[]")
            except ValueError:
                d["thread"] = []
            d["office"] = office
            recs.append(d)
    else:
        recs = [dict(zip(hdr, r)) for r in vals[2:] if any(r)]
    path = OUTPUT_DIR / "{}_{}_{}.json".format(prefix, office, tag)
    path.write_text(json.dumps(recs, ensure_ascii=False))
    return len(recs)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="11280,23965,24065,11580")
    ap.add_argument("--weeks", type=int, default=6,
                    help="how many complete recruiting weeks back to fill")
    ap.add_argument("--from-week", type=int, default=1,
                    help="1 = the week just finished")
    ap.add_argument("--skip-pull", action="store_true",
                    help="file from files already downloaded")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    from automations.sms_thread_dump.run import _recruiting_week
    offices = [o.strip() for o in a.office.split(",") if o.strip()]
    plan = []
    for back in range(a.from_week, a.from_week + a.weeks):
        lo, hi = _recruiting_week(back=back)
        plan.append((back, lo, hi, "w{:%m%d}".format(hi)))

    print("[backfill] {} offices x {} weeks".format(len(offices), len(plan)),
          flush=True)
    for back, lo, hi, tag in plan:
        print("   week -{}: {} → {}  tag {}".format(back, lo, hi, tag), flush=True)
    if a.dry_run:
        return 0

    olist = ",".join(offices)
    for back, lo, hi, tag in plan:
        started = dt.datetime.now()
        print("\n[backfill] === week ending {} (tag {}) ===".format(hi, tag),
              flush=True)
        filed = list(offices)
        if not a.skip_pull:
            dump_args = ("sms_thread_dump --office {} --bookings-only --week {}"
                         .format(olist, back))
            enqueue(["rerun", "sms_thread_dump", "--office", olist,
                     "--bookings-only", "--week", str(back)])
            wait_queue(dump_args)
            ready = fresh_tabs(["SMS Dump {}".format(o) for o in offices],
                               hi.strftime("%m-%d-%Y"))
            got = {t.rsplit(" ", 1)[1] for t in ready}
            for o in offices:
                if o not in got:
                    continue
                n = download("sms_thread_dump", "SMS Dump", o, tag)
                print("   {} bookings → {}".format(n, o), flush=True)

            log_args = "sms_log --office {} --week {}".format(olist, back)
            enqueue(["rerun", "sms_log", "--office", olist, "--week", str(back)])
            wait_queue(log_args)
            ready = fresh_tabs(["SMS Log {}".format(o) for o in offices],
                               "{}..{}".format(lo.strftime("%m-%d-%Y"),
                                               hi.strftime("%m-%d-%Y")))
            got_log = {t.rsplit(" ", 1)[1] for t in ready}
            for o in offices:
                if o not in got_log:
                    continue
                n = download("sms_log", "SMS Log", o, tag)
                print("   {} messages → {}".format(n, o), flush=True)
            # an office needs BOTH halves of the week to be filed at all
            filed = [o for o in offices if o in got and o in got_log]
            for o in offices:
                if o not in filed:
                    print("   {}: no data for this week — column left alone"
                          .format(o), flush=True)

        for o in filed:
            r = _run(["automations.sms_audit.weekly_sheet", "--office", o,
                      "--week", str(back), "--suffix", tag])
            line = [x for x in (r.stdout or "").splitlines()
                    if "cells" in x or "REFUSED" in x or "nothing to read" in x]
            print("   {}".format(line[0] if line else (r.stderr or "")[-160:]),
                  flush=True)
        print("[backfill] week {} done in {}".format(
            hi, dt.datetime.now() - started), flush=True)
    print("\n[backfill] finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
