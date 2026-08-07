"""Who sold in the ATT (Internet Only) program LAST WEEK, straight from Tableau.

SOURCE — spelled out because the whole report hangs off it:
  workbook  ATT Tracker 2.1 - D2D
  view      D2D 1-PAGERV2 (Internet Only)
  page      D2D PAGE 2 LAST WEEK (Internet Only)
  worksheet 'Sales By ICD (ATT) (V2) (LW2) (2)'   ← the crosstab we export
  columns   ICD Owner Name | Office | ST, City | Captain's Bonus Teams v2 |
            Mon (MM-DD) … Sun (MM-DD) | Total

'D2D PAGE 2 LAST WEEK (Internet Only)' is a DASHBOARD PAGE, not a worksheet, so
it never appears in the Crosstab dialog — asking for it by that name fails with
"Couldn't find the sheet … saw 11 thumb(s)". The two worksheets that page is
built from are the ones offered:

    ICD Summary - ATT (V2) (LW) (3)        68 owners — the ranked metrics table
    Sales By ICD (ATT) (V2) (LW2) (2)      70 owners — per-owner per-day sales

We take the SECOND. Probed 2026-08-07 for WE 08.02, it is a strict superset
(the two it adds, Kobe Cireus and Melik El Jaiez, sold last week but are absent
from the ranked summary), and its semantics are exactly the question this report
asks — "who sold last week" — rather than "who ranked". It also carries the
office / city / captain team that make the Slack note readable.

The worksheet is pinned to a RELATIVE week ("last week"); there is no week
filter to set (same finding as country_sales_board's pull — a pinned URL renders
the sheet empty and Tableau then hides it entirely). So we read the week back
OUT of the day headers and let the caller check it against the calendar, rather
than assuming the view is where we think it is.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "ATTTRACKER2_1-D2D/D2D1-PAGERV2InternetOnly")
CROSSTAB_SHEET = "Sales By ICD (ATT) (V2) (LW2) (2)"
DASHBOARD_PAGE = "D2D PAGE 2 LAST WEEK (Internet Only)"   # for logs/humans

OWNER_COL = "ICD Owner Name"
OFFICE_COL = "Office Name (Consolidated)"
CITY_COL = "ST, City (consolidated"          # sic — Tableau truncates the ')'
TEAM_COL = "Captain's Bonus Teams v2"

# Crosstab roll-up rows, dropped on sight.
SKIP_OWNERS = {"grand total", "sales total", "total", ""}

_DAY_RE = re.compile(r"^(mon|tue|wed|thu|fri|sat|sun)[a-z]*\s*\((\d{1,2})-(\d{1,2})\)$")


class NoDataYet(RuntimeError):
    """Tableau hides an empty worksheet, so a missing sheet means 'that window
    has no sales', not 'the view is broken'."""


@dataclass
class Owner:
    name: str                       # exactly as Tableau spells it
    office: str = ""
    city: str = ""
    team: str = ""
    days: Dict[dt.date, int] = field(default_factory=dict)
    total: int = 0


@dataclass
class Pull:
    owners: List[Owner]
    days: List[dt.date]             # the seven dates the crosstab covers

    @property
    def week_ending(self) -> Optional[dt.date]:
        return max(self.days) if self.days else None

    @property
    def names(self) -> List[str]:
        return [o.name for o in self.owners]


def _read_rows(path: Path) -> List[List[str]]:
    """Tableau crosstabs come out UTF-16 tab-delimited; test fixtures may be
    UTF-8 comma. Sniff both rather than guess."""
    data = Path(path).read_bytes()
    for enc in ("utf-16", "utf-8-sig", "utf-8", "iso-8859-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", errors="replace")
    first = text.splitlines()[0] if text.splitlines() else ""
    delim = "\t" if "\t" in first else ","
    return list(csv.reader(io.StringIO(text), delimiter=delim))


def _num(raw: str) -> int:
    s = (raw or "").strip().replace(",", "")
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _day_date(header: str, near: dt.date) -> Optional[dt.date]:
    """'Mon (07-27)' → 2026-07-27. The crosstab carries MM-DD with no year, so
    the year is the one that puts the date NEAREST `near` — which is how a
    late-December run reads a January column (and vice versa) without a special
    case."""
    m = _DAY_RE.match(" ".join((header or "").strip().lower().split()))
    if not m:
        return None
    mm, dd = int(m.group(2)), int(m.group(3))
    best = None
    for yr in (near.year - 1, near.year, near.year + 1):
        try:
            cand = dt.date(yr, mm, dd)
        except ValueError:                      # 02-29 on a non-leap year
            continue
        if best is None or abs((cand - near).days) < abs((best - near).days):
            best = cand
    return best


def parse(path: Path, near: Optional[dt.date] = None) -> Pull:
    """Parse the crosstab into Owners + the week it covers. Pure — no network.

    Header discovery is by CONTENT (the row carrying 'ICD Owner Name'), not by
    position: the export has a 'Last Week' band row above the real header, and
    a view that gains or loses a band row must not silently shift every column
    by one."""
    near = near or dt.date.today()
    rows = _read_rows(path)
    if not rows:
        raise NoDataYet(f"{Path(path).name} is empty — nothing was exported")

    hdr_idx = next((i for i, r in enumerate(rows[:6])
                    if any((c or "").strip() == OWNER_COL for c in r)), None)
    if hdr_idx is None:
        raise ValueError(
            f"crosstab has no {OWNER_COL!r} column. First rows: {rows[:3]}")
    header = [(c or "").strip() for c in rows[hdr_idx]]

    def col(label: str) -> Optional[int]:
        want = " ".join(label.lower().split())
        for i, h in enumerate(header):
            if " ".join(h.lower().split()) == want:
                return i
        return None

    oi = col(OWNER_COL)
    day_cols = {i: d for i, h in enumerate(header) if (d := _day_date(h, near))}
    if not day_cols:
        raise ValueError(f"no 'Mon (MM-DD)' day columns in header {header}")

    idx_office, idx_city, idx_team = col(OFFICE_COL), col(CITY_COL), col(TEAM_COL)
    seen: Dict[str, Owner] = {}
    for r in rows[hdr_idx + 1:]:
        if len(r) <= oi:
            continue
        name = (r[oi] or "").strip()
        if name.lower() in SKIP_OWNERS:
            continue
        o = seen.get(name)
        if o is None:
            o = seen[name] = Owner(
                name=name,
                office=(r[idx_office].strip() if idx_office is not None
                        and len(r) > idx_office else ""),
                city=(r[idx_city].strip() if idx_city is not None
                      and len(r) > idx_city else ""),
                team=(r[idx_team].strip() if idx_team is not None
                      and len(r) > idx_team else ""))
        for i, day in day_cols.items():
            if len(r) > i:
                o.days[day] = o.days.get(day, 0) + _num(r[i])
        o.total = sum(o.days.values())
    return Pull(owners=sorted(seen.values(), key=lambda o: o.name.upper()),
                days=sorted(set(day_cols.values())))


def pull_last_week(page, out_dir: Path, *, near: Optional[dt.date] = None,
                   logfn=print) -> Pull:
    """Download + parse. `page` is a live patchright tableau_session() Page —
    the caller owns the browser."""
    from automations.shared.tableau_patchright import download_crosstab_patchright

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "att_owners_last_week.csv"
    logfn(f"  downloading {CROSSTAB_SHEET!r} "
          f"(the '{DASHBOARD_PAGE}' page)…")
    url = f"{VIEW_URL}?:refresh=yes"        # read what the VAs read, not a cache
    try:
        download_crosstab_patchright(url, CROSSTAB_SHEET, out_path, page=page,
                                     verbose=False)
    except RuntimeError as e:
        if "Couldn't find" in str(e) and CROSSTAB_SHEET in str(e):
            raise NoDataYet(
                f"{CROSSTAB_SHEET!r} isn't in the Crosstab dialog — Tableau "
                f"hides an empty worksheet, so last week has no sales yet "
                f"(or the worksheet was renamed)") from e
        raise
    pull = parse(out_path, near=near)
    logfn(f"  parsed {len(pull.owners)} owner(s), "
          f"{pull.days[0].isoformat()}..{pull.days[-1].isoformat()} "
          f"({sum(o.total for o in pull.owners)} units)")
    return pull
