"""Step 1 — start a new week: copy last week's workbook, name it, archive old.

JD's Loom opens with this: take the most recent commission sheet, copy it,
rename the copy `RH <week ending>`, and move older ones into Raf's folder so
only the last couple stay live.

Identifying "the most recent commission sheet" is the whole difficulty, because
the live folder is shared. It holds, besides JD's weekly series:

  * `AC 8/30`, `AC 8/23`   — a different owner's parallel series
  * `CH WE 7.12.xlsx`      — Maud's
  * two commission templates, and several people's personal subfolders
  * `RH 8.30 Practice`, ` RH 7.19 PRACTICE` — demo copies, NOT the live sheet

and the live series itself is inconsistently named: ` RH 8.30-Alisson` carries a
leading space and a person's suffix, and IS the real workbook for that week
(Megan, 2026-09-04) even though it reads like a practice copy. So the rule is:
a name that starts with RH and carries a month.day, minus anything saying
PRACTICE. Everything else in the folder is left untouched.

The archived copies are filed straight into the year subfolder the archive
already uses (see archive.py), not dropped loose in its root.

    python -m automations.commission_sheet.newweek              # dry run
    python -m automations.commission_sheet.newweek --write
    python -m automations.commission_sheet.newweek --week 9.6 --write
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from typing import Dict, List, Optional, Tuple

from automations.commission_sheet import config as C
from automations.commission_sheet.archive import _FOLDER_MIME, _list
from automations.commission_sheet.drive_auth import service

_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
#: "RH 8.9", " RH 8.2", "RH 1.7.xlsx", " RH 8.30-Alisson"
_RH = re.compile(r"^\s*RH[\s.]+(\d{1,2})\.(\d{1,2})\b", re.I)
#: JD's demo copies. Never the live sheet for a week.
_PRACTICE = re.compile(r"practice", re.I)


def is_live_sheet(name: str) -> Optional[Tuple[int, int]]:
    """(month, day) if this name is a live weekly workbook, else None."""
    if _PRACTICE.search(name):
        return None
    m = _RH.match(name)
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return month, day


def _week_of(f: dict) -> Optional[dt.date]:
    """The week the workbook covers. The name has no year, so it is taken from
    the created date — then corrected when the two disagree across New Year
    (a workbook named 12.28 created in January belongs to the previous year)."""
    md = is_live_sheet(f["name"])
    if not md:
        return None
    month, day = md
    year = int(f["createdTime"][:4])
    created_month = int(f["createdTime"][5:7])
    if month == 12 and created_month == 1:
        year -= 1
    elif month == 1 and created_month == 12:
        year += 1
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def survey(svc=None) -> Tuple[List[Tuple[dt.date, dict]], List[dict]]:
    """(live workbooks newest-first, everything else in the folder)."""
    svc = svc or service()
    items = _list(svc, C.COMMISSION_FOLDER_ID)
    live, other = [], []
    for f in items:
        if f["mimeType"] == _FOLDER_MIME or f["mimeType"] != _SHEET_MIME:
            other.append(f)
            continue
        week = _week_of(f)
        (live.append((week, f)) if week else other.append(f))
    live.sort(key=lambda pair: pair[0], reverse=True)
    return live, other


def _name_for(week: dt.date) -> str:
    return f"RH {week.month}.{week.day}"


def plan(week: Optional[dt.date] = None, svc=None) -> Dict:
    svc = svc or service()
    live, other = survey(svc)
    if not live:
        raise RuntimeError(
            "No live RH workbook in the commission folder — nothing to copy from.")
    source_week, source = live[0]
    week = week or (source_week + dt.timedelta(days=7))
    new_name = _name_for(week)
    clash = [f for w, f in live if f["name"].strip() == new_name]
    # Only the newest KEEP_RECENT stay live; the rest go to Raf's folder.
    to_archive = [(w, f) for w, f in live[C.KEEP_RECENT:]]
    return {"week": week, "new_name": new_name, "source": source,
            "source_week": source_week, "clash": clash, "live": live,
            "other": other, "to_archive": to_archive}


def report(p: Dict) -> str:
    out = [f"\nNew week      : {p['week']:%a %d %b %Y}  ->  {p['new_name']!r}",
           f"Copy from     : {p['source']['name']!r} "
           f"(week of {p['source_week']:%d %b})"]
    if p["clash"]:
        out.append(f"  !! {p['new_name']!r} already exists — refusing to make a second one")
    out.append(f"\nSTAYS LIVE  (newest {C.KEEP_RECENT})")
    for w, f in p["live"][:C.KEEP_RECENT]:
        out.append(f"  {w:%Y-%m-%d}  {f['name']!r}")
    out.append(f"\nARCHIVE to Raf's folder  ({len(p['to_archive'])})")
    if not p["to_archive"]:
        out.append("  —")
    for w, f in p["to_archive"]:
        out.append(f"  {w:%Y-%m-%d}  {f['name']!r}   -> {w.year}/")
    out.append(f"\nLEFT ALONE — not the RH series  ({len(p['other'])})")
    for f in p["other"][:8]:
        out.append(f"  {f['name']!r}")
    if len(p["other"]) > 8:
        out.append(f"  … {len(p['other']) - 8} more")
    return "\n".join(out)


def _year_folder(svc, year: int) -> str:
    for f in _list(svc, C.ARCHIVE_FOLDER_ID):
        if f["mimeType"] == _FOLDER_MIME and f["name"].strip() == str(year):
            return f["id"]
    return svc.files().create(
        body={"name": str(year), "mimeType": _FOLDER_MIME,
              "parents": [C.ARCHIVE_FOLDER_ID]},
        fields="id", supportsAllDrives=True).execute()["id"]


def apply(p: Dict, svc=None) -> Dict:
    svc = svc or service()
    if p["clash"]:
        raise RuntimeError(
            f"{p['new_name']!r} already exists in the commission folder. "
            "Rename or remove it first — refusing to create a duplicate week.")

    made = svc.files().copy(
        fileId=p["source"]["id"],
        body={"name": p["new_name"], "parents": [C.COMMISSION_FOLDER_ID]},
        fields="id,name,webViewLink", supportsAllDrives=True).execute()

    moved = 0
    for week, f in p["to_archive"]:
        target = _year_folder(svc, week.year)
        svc.files().update(fileId=f["id"], addParents=target,
                           removeParents=C.COMMISSION_FOLDER_ID,
                           fields="id", supportsAllDrives=True).execute()
        moved += 1
    return {"id": made["id"], "name": made["name"],
            "link": made.get("webViewLink", ""), "archived": moved}


def _parse_week(text: str) -> dt.date:
    """--week 9.6 -> the 9/6 of the year that keeps it near today."""
    m = re.match(r"^\s*(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\s*$", text)
    if not m:
        raise argparse.ArgumentTypeError(f"Use M.D (e.g. 9.6), got {text!r}")
    month, day = int(m.group(1)), int(m.group(2))
    if m.group(3):
        year = int(m.group(3))
        year += 2000 if year < 100 else 0
    else:
        today = dt.date.today()
        year = today.year
        if month == 12 and today.month == 1:
            year -= 1
        elif month == 1 and today.month == 12:
            year += 1
    return dt.date(year, month, day)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--week", type=_parse_week,
                    help="week ending as M.D (default: one week after the "
                         "newest workbook)")
    ap.add_argument("--write", action="store_true", help="do it")
    args = ap.parse_args(argv)

    svc = service()
    p = plan(week=args.week, svc=svc)
    print(report(p))
    if not args.write:
        print("\n(dry run — nothing copied or moved; add --write to do it)")
        return 0
    done = apply(p, svc)
    print(f"\nCreated {done['name']!r}  {done['link']}")
    print(f"Archived {done['archived']} older workbook(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
