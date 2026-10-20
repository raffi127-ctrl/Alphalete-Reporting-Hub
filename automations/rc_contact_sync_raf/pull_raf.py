"""LUCY 1: pull Raf's FULL Sales Order History (all reps) and hand it to the
run box via the control sheet.

Why Lucy 1 and not wherever the run happens: Raf's SaraPlus dealer login
(alphalete_sales_board: saraplus-creds.json + the verified .saraplus_profile)
only exists on Lucy 1, and — unlike Carlos's B2B login — has NO emailed-passcode
step there, because the profile is already device-verified. A fresh profile
elsewhere would trip SaraPlus's new-browser verification and Raf's codes do NOT
land in an inbox this repo can read. So the pull stays on Lucy 1 and the raw
CSV crosses machines base64-chunked into a control-sheet tab, exactly like
sp_order_log/raf_guest.py.

This is raf_guest WITHOUT the roster filter: raf_guest.pull() already returns
the raw, all-reps export (its filter_csv runs AFTER), so this just uploads that
raw export under this report's own tab.

    python -m automations.rc_contact_sync_raf.pull_raf --pull     # Lucy 1
    python -m automations.rc_contact_sync_raf.pull_raf --show     # any box

Python 3.9-safe (Lucy runtime). Cross-platform.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                          # noqa: BLE001
    pass

from automations.rc_contact_sync_raf import config as C


def pull_and_upload(start: dt.date, end: dt.date, *, headless: bool = True,
                    no_upload: bool = False, log=print) -> int:
    """Raf's raw Sales Order History for [start, end] -> the handoff tab."""
    from automations.sp_order_log import raf_guest
    from automations.rc_contact_sync.status_probe import _upload_bytes

    log("Raf SaraPlus pull (ALL reps) %s..%s" % (start, end))
    data = raf_guest.pull(start, end, headless=headless, log=log)
    # rows = CSV data lines (minus the header)
    lines = data.decode("utf-8-sig", errors="replace").splitlines()
    rows = max(len(lines) - 1, 0)
    log("pulled %d order row(s)" % rows)
    if no_upload:
        log("(--no-upload: nothing written to the sheet)")
        return 0
    env = {"pulled": dt.datetime.now().isoformat(timespec="seconds"),
           "start": start.isoformat(), "end": end.isoformat(),
           "rows": rows,
           "csv": base64.b64encode(data).decode()}
    if not _upload_bytes(json.dumps(env).encode(), C.TAB, log=log):
        log("UPLOAD FAILED — the run box will not see this pull")
        return 1
    log("=== done ===")
    return 0


def show(log=print) -> int:
    """Read the handoff tab back and summarize it (any box)."""
    from automations.rc_contact_sync_raf import customers as cust
    env = cust._fetch(log=log)
    if not env:
        return 1
    age = cust._age_hours(env)
    log("pulled %s (%s old), window %s..%s, %s row(s)"
        % (env.get("pulled"), "?" if age is None else "%.1fh" % age,
           env.get("start"), env.get("end"), env.get("rows")))
    data = base64.b64decode(env.get("csv", "") or "")
    all_lines = data.decode("utf-8-sig", errors="replace").splitlines()
    for line in all_lines[:6]:
        log("  " + line[:160])
    if len(all_lines) > 6:
        log("  ... (%d line(s) total)" % len(all_lines))
    log("=== done ===")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="rc_contact_sync_raf.pull_raf",
        description="Pull Raf's full SaraPlus Sales Order History (all reps) "
                    "and hand it to the run box via the control sheet.")
    ap.add_argument("--pull", action="store_true",
                    help="log into Raf's SaraPlus and refresh the handoff tab "
                         "(Lucy 1)")
    ap.add_argument("--show", action="store_true",
                    help="read the handoff tab back and summarize it")
    ap.add_argument("--start", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--end", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--headed", action="store_true",
                    help="show the browser (debugging)")
    ap.add_argument("--no-upload", action="store_true",
                    help="with --pull: pull and report, write nothing")
    args = ap.parse_args(argv)

    if args.show:
        return show()

    today = dt.date.today()
    start = (dt.date.fromisoformat(args.start) if args.start
             else today - dt.timedelta(days=C.PULL_WINDOW_DAYS))
    end = dt.date.fromisoformat(args.end) if args.end else today

    if args.pull:
        return pull_and_upload(start, end, headless=not args.headed,
                               no_upload=args.no_upload)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
