"""Omar's Daily Update from ApplicantStream (Raf, Slack 2026-10-26).

    "Can we automate the pulling of the applicants from applicant stream to
     the daily update every day at 12:00PM?"

Same pull as Raf's Daily Update (raf_daily_update.harvest: Retention Details
→ the day's 2nd-round pages + the calendar's BOB-call result), for office
24153 (Kalkan Marketing, Dearborn MI), written to the 'Daily Update' tab of
"All In One - Omar". One row per 2nd-round candidate; anyone already on the
tab for that day is skipped, so re-runs and hand entries are safe. No Slack
post. The '2nd Rds' tab (second_rds.py) reads these rows by formula.

The noon run covers YESTERDAY: by then the BOB calls are on the calendar.

    python -m automations.omar_daily_update.run                    # dry: yesterday
    python -m automations.omar_daily_update.run --date 2026-10-24
    python -m automations.omar_daily_update.run --write --sandbox  # test copy
    python -m automations.omar_daily_update.run --write            # real sheet
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import List
from zoneinfo import ZoneInfo

from automations.omar_daily_update import layout as OL
from automations.raf_daily_update import layout as RL

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

EASTERN = ZoneInfo("America/Detroit")
OFFICE_ID = "24153"                                        # Omar Mohammad
REAL_SHEET = "1eYIs-FV0-J_TGTQtunFxdeII6uwLpvHYbj7C3t_eRTY"   # All In One - Omar
# "SANDBOX - All In One - Omar (2nd rds test)", Eve's copy (2026-10-26).
SANDBOX_SHEET = "1nbXYO2WrGbrCbOnrIrvDyv1L0kZMmsgE_JnrwG3n6zk"
TAB = "Daily Update"


def log(msg: str) -> None:
    print("[%s] %s" % (dt.datetime.now().replace(microsecond=0).isoformat(), msg),
          flush=True)


def write_sheet(rows: List[dict], day: dt.date, write: bool, sheet_id: str) -> int:
    """Append the day's rows nobody has typed yet, below the tab's last row.
    Only the mapped cells -- the MONTHLY TOTALS blocks right of the table and
    every existing row are never touched."""
    from automations.recruiting_report.fill import _retry, open_by_key
    sh = _retry(lambda: open_by_key(sheet_id))
    ws = sh.worksheet(TAB)
    grid = ws.get_values("A1:J")
    lay = OL.resolve(grid[0] if grid else [])
    cols = sorted(lay.values())
    have, last = [], 1
    for i, raw in enumerate(grid[1:], 2):
        raw = list(raw) + [""] * 20
        if any(str(raw[c]).strip() for c in cols):
            last = i
        d = RL.parse_sheet_date(raw[lay["date"]], day.year)
        if d:
            have.append(RL.person_key(d, raw[lay["first"]], raw[lay["last"]]))
    add = RL.new_rows(rows, have)
    log("  %s %r: %d for %s, %d already there, appending %d at row %d%s"
        % (sh.title, TAB, len(rows), day, len(rows) - len(add), len(add),
           last + 1, "" if write else "  (dry-run)"))
    if not (write and add):
        return len(add)
    need = last + len(add)
    if need > ws.row_count:
        ws.add_rows(need - ws.row_count + 10)
    data = []
    for n, r in enumerate(add, last + 1):
        for key in OL.WRITE_KEYS:
            if key in lay and r.get(key):
                data.append({"range": "'%s'!%s%d" % (TAB, RL.col_letter(lay[key]), n),
                             "values": [[r[key]]]})
    sh.values_batch_update(body={"valueInputOption": "USER_ENTERED", "data": data})
    return len(add)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default yesterday)")
    ap.add_argument("--write", action="store_true", help="append to the Daily Update tab")
    ap.add_argument("--sandbox", action="store_true", help="write Eve's test copy")
    ap.add_argument("--dry-run", action="store_true", help="write nothing (the default)")
    args = ap.parse_args(argv)
    if args.dry_run:
        args.write = False

    day = (dt.date.fromisoformat(args.date) if args.date
           else dt.datetime.now(EASTERN).date() - dt.timedelta(days=1))
    sheet = SANDBOX_SHEET if args.sandbox else REAL_SHEET
    log("=== omar daily update | %s | office %s | %s%s ===" % (
        day, OFFICE_ID, "WRITE" if args.write else "DRY-RUN",
        " (sandbox)" if args.sandbox else ""))
    if day.weekday() == 6 and not args.date:
        log("  Sunday -- no 2nd rounds, nothing to do")
        return 0

    from automations.raf_daily_update.run import harvest
    rows = RL.build_rows(harvest(day, OFFICE_ID))
    log("  %s" % RL.summary_line(rows))
    for r in rows:
        log("    %-16s %s %-22s 2nd: %-22s %s" % (r["status"] or "to call", r["first"],
                                                   r["last"], r["int2"], r["bob_date"]))
    if not rows:
        log("  no 2nd rounds for this day -- nothing to write")
        return 0
    write_sheet(rows, day, args.write, sheet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
