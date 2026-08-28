#!/usr/bin/env python3
"""Dump one office's OAT activity CSV (per-applicant walk outcomes) to a Sheet
tab, so the mini can read per-NAME results without shell access to Lucy 2.

Built 2026-08-27 for the removed-apps restore test (see
automations/oat_processing/restore_removed.py): the activity CSV is the only
per-name record of what each walk did (time, applicant, source, position,
action, outcome, reason), it lives on Lucy 2's disk, and logtail is path-locked
to output/logs — so the tally Carlos asked for ("of the 42 restored, how many
got sent vs. actually deserved the remove?") had no clean remote read. This is
that read: no browser, no session, reads one CSV and writes one tab.

  lucy rerun dump_activity --office 23467            # today's CSV
  lucy rerun dump_activity --office 23467 --date 2026-08-27
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

import argparse
import csv
import datetime as dt
import os
import sys


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Dump an office's oat-activity CSV "
                                            "to a Sheet tab")
    p.add_argument("--office", default="23467")
    p.add_argument("--date", default=dt.date.today().isoformat())
    p.add_argument("--tab", default="")
    a = p.parse_args(argv)

    suffix = "" if a.office == "11580" else f"-{a.office}"
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, "output", f"oat-activity-{a.date}{suffix}.csv")
    tab = a.tab or f"OAT Activity {a.office}"

    rows = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        print(f"[dump] {len(rows)} row(s) in {os.path.basename(path)}", flush=True)
    else:
        print(f"[dump] {os.path.basename(path)} does not exist (no live walk "
              f"has flushed yet today)", flush=True)

    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(
        "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
    try:
        ws = sh.worksheet(tab)
    except Exception:  # noqa: BLE001
        ws = sh.add_worksheet(title=tab, rows=1200, cols=10)
    ws.clear()
    meta = [f"office {a.office} · {a.date} · dumped "
            f"{dt.datetime.now().strftime('%H:%M:%S')} · {len(rows)} row(s) "
            f"(incl. header)"]
    body = [meta] + (rows or [["(no activity file yet)"]])
    width = max(len(r) for r in body)
    body = [list(r) + [""] * (width - len(r)) for r in body]
    ws.update(body, "A1", value_input_option="RAW")
    print(f"[dump] wrote {len(body)} row(s) to tab {tab!r}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
