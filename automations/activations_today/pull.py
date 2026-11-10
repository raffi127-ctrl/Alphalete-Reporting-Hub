"""Pull + parse the ORDER LOG for 'Activations Scheduled Today'.

Raf 2026-11-09 (#alphalete-sales thread "Activations Day Off"): reps should see
which customers are scheduled to INSTALL today so they can reach out to them
that day. Dylan's Loom used ATT Tracker 2.1 - D2D -> PENDING INSTALLS, but that
view can't be driven by URL (Lucy 4 probes 2026-11-10): its saved filters are
stuck on April-May sales, M/D/YYYY and long dates are ignored, and every ISO
date filter, alone or combined, hides the 'Expected Installs' sheet.

So the source is the Order Log instead (Dylan: "I thought this was already
pulled in the reps' individual order logs"):

    ATT TRACKER 2.1 - D2D -> ORDER LOG -> 'Sales Board Original' custom view
    -> worksheet 'A.Order Log', Start/End Date = SALE date (honored by URL)

Window = the last WINDOW_DAYS of sales (Loom: "the last five weeks"), then
client-side: Owner Name = owner, spe.Install Date = today (Central), no
activation date yet, not canceled. Bonus over Pending Installs: the customer's
phone number, which is what a rep needs to reach out.
"""
from __future__ import annotations

import csv
import datetime as dt
import tempfile
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")

# Same org-wide view scheduled_6_days_out uses for single-owner cuts. NOT the
# ALLREPS view: that one's Start/End is ACTIVATION date, and an install that's
# still scheduled has none.
VIEW_URL_TMPL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/ORDERLOG/"
    "78466c86-905b-4553-9d55-5206170c7e56/SalesBoardOriginal?:iid=1"
    "&Start%20Date={start}&End%20Date={end}"
)
WORKSHEET = "A.Order Log"
WINDOW_DAYS = 42

OWNER = "Owner Name"
REP = "Rep"
CUSTOMER = "Customer Name"
PHONE = "sp.Customer Phone"
SALE_DATE = "sp.Order Date (copy)"
INSTALL_DATE = "spe.Install Date"
ACTIVATION = "Activatoin Date (order log)"   # typo matches the source
STATUS = "spe.Status"
PRODUCT = "Product Type (Broken Out)"
PACKAGE = "Package"
TECH = "Tech Install"
SPM = "sp.SPM Number"

# Crosstab exports sometimes leave a merged dimension blank on the rows under
# its first one; carry the last value down for these.
_FILL_DOWN = (OWNER, REP)


def central_today() -> dt.date:
    return dt.datetime.now(CENTRAL).date()


def parse_date(v) -> Optional[dt.date]:
    s = str(v or "").strip()
    if not s:
        return None
    s = s.split(" ")[0]
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def build_url(day: dt.date) -> str:
    start = day - dt.timedelta(days=WINDOW_DAYS)
    return VIEW_URL_TMPL.format(start=start.isoformat(), end=day.isoformat())


def fetch(day: dt.date, out_path: Optional[Path] = None,
          verbose: bool = True, page=None) -> Path:
    from automations.shared.tableau_patchright import download_crosstab_patchright
    out_path = out_path or (Path(tempfile.gettempdir())
                            / "activations_today_orderlog.csv")
    url = build_url(day)
    if verbose:
        print("  view: {}".format(url), flush=True)
    download_crosstab_patchright(url, WORKSHEET, out_path,
                                 verbose=verbose, page=page)
    return out_path


def read_rows(csv_path: Path) -> List[Dict[str, str]]:
    """Every row of the crosstab as {header: value}, merged cells filled down."""
    raw = Path(csv_path).read_bytes()
    text = None
    for enc in ("utf-16", "utf-8-sig"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    lines = list(csv.reader(text.splitlines(),
                            delimiter="\t" if "\t" in text[:2000] else ","))
    if not lines:
        return []
    header = [h.lstrip("﻿").strip() for h in lines[0]]
    out: List[Dict[str, str]] = []
    last: Dict[str, str] = {}
    for r in lines[1:]:
        if not any((c or "").strip() for c in r):
            continue
        row = {h: (r[i].strip() if i < len(r) else "") for i, h in enumerate(header)}
        for k in _FILL_DOWN:
            if k in row:
                if row[k]:
                    last[k] = row[k]
                else:
                    row[k] = last.get(k, "")
        out.append(row)
    return out


def owner_rows(rows: List[Dict[str, str]], owner: str) -> List[Dict[str, str]]:
    want = owner.strip().casefold()
    return [r for r in rows if r.get(OWNER, "").strip().casefold() == want]


def is_open(r: Dict[str, str]) -> bool:
    """Still to install: no activation date and not canceled."""
    if parse_date(r.get(ACTIVATION)):
        return False
    # Lucy 4 probe 11/10: an 'Active' line can still have no activation date.
    s = r.get(STATUS, "").strip().lower()
    return not ("cancel" in s or s in ("active", "disconnected"))


def scheduled_on(rows: List[Dict[str, str]], day: dt.date) -> List[Dict[str, str]]:
    """Open orders whose install date is `day`, Rep A-Z then customer."""
    hit = [r for r in rows
           if parse_date(r.get(INSTALL_DATE)) == day and is_open(r)]
    hit.sort(key=lambda r: (r.get(REP, "").casefold(),
                            r.get(CUSTOMER, "").casefold()))
    return hit
