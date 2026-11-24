"""Wednesday: this week's %-payout workbook into Raf's Commission Sheets folder.

Maud 2026-11-24. Every Wednesday morning:

  1  download Tableau "ORG DD Detail" (the newest DD week)
  2  build the %-payout workbook from it (pct_payout.py — Edited, payout tab,
     one tab per rep, Raw)
  3  upload it as a Google Sheet into "Commission Sheets", named
     `RH M.D.YY` — the week-ending SUNDAY (DD week is the Saturday, +1 day)
  4  keep only the 2 newest RH workbooks in that folder; MOVE the older ones
     into "Rafael/<year>". Moved, never deleted or trashed.

Guards:
  * the DD's week must be last week (Sunday on or before today, within 7 days).
    If Tableau hasn't published the new week yet, stop — never upload last
    week's numbers under this week's name.
  * if an RH workbook for this week already exists, don't make a second one
    (the archive step still runs, so a re-run is safe).
  * a file that can't be moved is reported and skipped; the rest still move.

Drive access is commission_sheet.drive_auth (full-Drive token for the account
that owns Raf's folders). One-time setup on the machine that runs this:
`python -m automations.commission_sheet.drive_auth`.

    python -m automations.commission_sheet.weekly_drop                 # dry run
    python -m automations.commission_sheet.weekly_drop --write
    python -m automations.commission_sheet.weekly_drop --write --suffix " - Maudy"
    python -m automations.commission_sheet.weekly_drop --dd-file dd.csv --write
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from automations.commission_sheet import config as C

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"


def _log(msg: str = "") -> None:
    print(msg, flush=True)


def dd_week_sunday(dd_path: Path) -> dt.date:
    """Week-ending Sunday of the DD in this file (DD week is a Saturday)."""
    from automations.commission_sheet.sources import (dominant_dd_week,
                                                      read_crosstab)
    rows = read_crosstab(dd_path)
    week, n, total = dominant_dd_week(rows, 0)
    if not week:
        raise RuntimeError("no cl.DD Week dates in the DD download")
    return week + dt.timedelta(days=(6 - week.weekday()) % 7)


def check_fresh(sunday: dt.date, today: Optional[dt.date] = None) -> None:
    today = today or dt.date.today()
    age = (today - sunday).days
    if not 0 <= age < 7:
        raise RuntimeError(
            f"DD week ends {sunday:%m/%d/%Y}, which is not last week "
            f"(today {today:%m/%d/%Y}) — Tableau may not have published the "
            "new week yet. Nothing uploaded.")


def name_for(sunday: dt.date, suffix: str = "") -> str:
    from automations.commission_sheet.newweek import _name_for
    return _name_for(sunday) + suffix


def existing_for_week(live, sunday: dt.date) -> List[dict]:
    return [f for w, f in live if w == sunday]


def upload(svc, xlsx: Path, name: str) -> dict:
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(str(xlsx), mimetype=XLSX_MIME, resumable=True)
    return svc.files().create(
        body={"name": name, "mimeType": SHEET_MIME,
              "parents": [C.COMMISSION_FOLDER_ID]},
        media_body=media, fields="id,name,webViewLink",
        supportsAllDrives=True).execute()


def archive_old(svc, write: bool) -> dict:
    """Move every RH workbook past the newest KEEP_RECENT into Rafael/<year>."""
    from automations.commission_sheet.newweek import _year_folder, survey
    live, _ = survey(svc)
    keep, old = live[:C.KEEP_RECENT], live[C.KEEP_RECENT:]
    for w, f in keep:
        _log(f"  stays     {f['name'].strip()!r}")
    moved, failed = [], []
    for w, f in old:
        label = f"{f['name'].strip()!r} -> Rafael/{w.year}"
        if not write:
            _log(f"  would move {label}")
            continue
        try:
            target = _year_folder(svc, w.year)
            svc.files().update(fileId=f["id"], addParents=target,
                               removeParents=C.COMMISSION_FOLDER_ID,
                               fields="id", supportsAllDrives=True).execute()
            moved.append(f["name"].strip())
            _log(f"  moved     {label}")
        except Exception as e:                      # noqa: BLE001
            failed.append(f["name"].strip())
            _log(f"  ✗ could not move {label}: {type(e).__name__}: {e}")
    return {"moved": moved, "failed": failed, "to_move": len(old)}


def run(write: bool, dd_file: Optional[Path], suffix: str) -> int:
    from automations.commission_sheet import pct_payout
    from automations.commission_sheet.drive_auth import service
    from automations.commission_sheet.newweek import survey

    work = Path(tempfile.mkdtemp(prefix="commission_drop_"))
    if dd_file:
        dd = dd_file
    else:
        from automations.commission_sheet.sources import fetch_dd
        _log("1  downloading ORG DD Detail from Tableau…")
        dd = fetch_dd(work / "dd.csv")
    sunday = dd_week_sunday(dd)
    check_fresh(sunday)
    name = name_for(sunday, suffix)
    _log(f"   DD week ending Sunday {sunday:%m/%d/%Y} -> {name!r}")

    svc = service()
    live, _ = survey(svc)
    already = existing_for_week(live, sunday)

    if already:
        _log(f"3  already in Commission Sheets for this week: "
             f"{[f['name'].strip() for f in already]} — not making another")
    else:
        xlsx = work / f"{name}.xlsx"
        _log("2  building the workbook…")
        pct_payout.main(dd, xlsx)
        if write:
            made = upload(svc, xlsx, name)
            _log(f"3  uploaded {made['name']!r}  {made.get('webViewLink', '')}")
        else:
            _log(f"3  would upload {name!r} to Commission Sheets")

    _log(f"4  keep the newest {C.KEEP_RECENT}, archive the rest:")
    res = archive_old(svc, write)
    if not write:
        _log("\n(dry run — nothing uploaded or moved; add --write)")
        return 0
    if res["failed"]:
        _log(f"\n{len(res['failed'])} workbook(s) could not be moved — "
             "the account needs permission to move them, or move them by hand.")
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="actually upload + move")
    ap.add_argument("--dd-file", type=Path, help="use this DD crosstab")
    ap.add_argument("--suffix", default="", help='added to the name, e.g. " - Maudy"')
    a = ap.parse_args(argv)
    try:
        return run(a.write, a.dd_file, a.suffix)
    except RuntimeError as e:
        _log(f"STOPPED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
