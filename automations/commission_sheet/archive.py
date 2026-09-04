"""Filing for the commission-sheet archive (Raf's "Rafael" folder).

The archive already had a convention: one subfolder per year, 2016 through
2023, each holding that year's weekly workbooks. It stopped being maintained
after 2023, so 2024-2026 sat loose in the folder root while their (empty) year
folders already existed. This files them the way the older years are filed.

Which year a workbook belongs to is its CREATED date, not its name — the names
carry a month and day but no year ("RH 8.9", " RH 8.2", "RH 1.7.xlsx"). The
risk in that is the turn of the year: a workbook for the week ending 29 Dec is
created in January and would file one year late. Every file is checked for that
skew before anything moves, and any whose name-month and created-month disagree
is reported and left alone rather than filed on a guess.

Moves only — a Drive move is a re-parent, so nothing is copied and nothing is
deleted. Existing year folders are reused; a missing one is created.

    python -m automations.commission_sheet.archive              # dry run
    python -m automations.commission_sheet.archive --write
"""
from __future__ import annotations

import argparse
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from automations.commission_sheet import config as C
from automations.commission_sheet.drive_auth import service

_FOLDER_MIME = "application/vnd.google-apps.folder"
#: "RH 8.9", " RH 8.2", "RH 1.7.xlsx", "CR WE 3.15" -> (month, day)
_DATE_IN_NAME = re.compile(r"(\d{1,2})\.(\d{1,2})")


def _list(svc, folder_id: str) -> List[dict]:
    out: List[dict] = []
    token = None
    while True:
        res = svc.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken,files(id,name,mimeType,createdTime)",
            orderBy="createdTime", pageSize=1000, pageToken=token,
            supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        out += res.get("files", [])
        token = res.get("nextPageToken")
        if not token:
            return out


def _year_skew(name: str, created: str) -> Optional[str]:
    """Why this file can't be filed on its created year, or None if it can.

    A commission workbook is made within days of its week ending, so the month
    in the name and the month it was created agree (or sit one apart). December
    in the name against January in the created date means the created YEAR is
    one ahead of the week's year — the one case that would misfile."""
    match = _DATE_IN_NAME.search(name)
    if not match:
        return "no month.day in the name"
    name_month = int(match.group(1))
    created_month = int(created[5:7])
    if not 1 <= name_month <= 12:
        return f"month {name_month} in the name is not a month"
    if name_month == 12 and created_month == 1:
        return "week ends in December but the file was created in January"
    gap = abs(name_month - created_month)
    if min(gap, 12 - gap) > 1:
        return (f"name says month {name_month}, created in month {created_month}")
    return None


def plan(svc=None) -> Tuple[Dict[str, List[dict]], List[Tuple[dict, str]], Dict[str, str]]:
    """(files by year, skipped with reasons, existing year folders)."""
    svc = svc or service()
    items = _list(svc, C.ARCHIVE_FOLDER_ID)
    folders = {f["name"].strip(): f["id"]
               for f in items if f["mimeType"] == _FOLDER_MIME}
    loose = [f for f in items if f["mimeType"] != _FOLDER_MIME]

    by_year: Dict[str, List[dict]] = defaultdict(list)
    skipped: List[Tuple[dict, str]] = []
    for f in loose:
        reason = _year_skew(f["name"], f["createdTime"])
        if reason:
            skipped.append((f, reason))
        else:
            by_year[f["createdTime"][:4]].append(f)
    return dict(sorted(by_year.items())), skipped, folders


def report(by_year, skipped, folders) -> str:
    lines = [f"\nArchive folder holds {sum(len(v) for v in by_year.values())} "
             f"loose file(s) to file, {len(skipped)} to leave alone."]
    for year, files in by_year.items():
        state = "exists" if year in folders else "WILL BE CREATED"
        lines.append(f"\n  {year}  ({len(files)} file(s), folder {state})")
        for f in files[:4]:
            lines.append(f"      {f['createdTime'][:10]}  {f['name']}")
        if len(files) > 4:
            lines.append(f"      … {len(files) - 4} more")
    lines.append(f"\n  LEFT ALONE  ({len(skipped)})")
    if not skipped:
        lines.append("      —")
    for f, why in skipped:
        lines.append(f"      {f['createdTime'][:10]}  {f['name']!r} — {why}")
    return "\n".join(lines)


def apply(by_year, folders, svc=None) -> int:
    svc = svc or service()
    moved = 0
    for year, files in by_year.items():
        target = folders.get(year)
        if not target:
            target = svc.files().create(
                body={"name": year, "mimeType": _FOLDER_MIME,
                      "parents": [C.ARCHIVE_FOLDER_ID]},
                fields="id", supportsAllDrives=True).execute()["id"]
            folders[year] = target
        for f in files:
            # A Drive move is a re-parent: nothing is copied, nothing deleted.
            svc.files().update(fileId=f["id"], addParents=target,
                               removeParents=C.ARCHIVE_FOLDER_ID,
                               fields="id", supportsAllDrives=True).execute()
            moved += 1
        print(f"  {year}: filed {len(files)}")
    return moved


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="do the moves")
    args = ap.parse_args(argv)

    svc = service()
    by_year, skipped, folders = plan(svc)
    print(report(by_year, skipped, folders))
    if not args.write:
        print("\n(dry run — nothing moved; add --write to file them)")
        return 0
    print()
    moved = apply(by_year, folders, svc)
    print(f"\nFiled {moved} workbook(s) into year folders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
