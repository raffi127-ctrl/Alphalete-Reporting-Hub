"""Pull + parse Tableau's PENDING INSTALLS view for 'Activations Scheduled Today'.

Raf 2026-11-09 (#alphalete-sales thread "Activations Day Off"): reps should see
which customers are scheduled to INSTALL today so they can reach out to them
that day. Dylan's Loom shows the manual pull:

    ATT Tracker 2.1 - D2D -> PENDING INSTALLS ("Pending Installs (Internet/Video)")
    Owner Name = Rafael Hidalgo
    Sale Date Week Ending = the last 5 weeks
    Current Install Date Week Ending = this week
    -> Crosstab -> sort by Current Install Date

We pull the org-wide crosstab (no URL filters — some of these views hide the
worksheet on an empty URL-filter match, see disconnects/pull.py) and filter
client-side: Owner Name = owner AND Current Install Date = today (Central).
Filtering on the install DATE itself makes the sale-week window moot: an order
installing today is in the export whatever week it was sold, as long as the
view's default sale-week filter covers it. `--probe` checks exactly that.
"""
from __future__ import annotations

import csv
import datetime as dt
import tempfile
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")

VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "ATTTRACKER2_1-D2D/PENDINGINSTALLS")
# Worksheet name in the Crosstab dialog (confirmed by the Lucy 4 probe 2026-11-10;
# the dialog offers it + "zzz last refresh"):
# opt_phase's matcher is case-insensitive + rename-tolerant, and on a miss the
# error lists every sheet the dialog offered.
WORKSHEET = "Expected Installs"

# Header labels as they appear in the view (Dylan's Loom, 2026-11-09).
OWNER = "Owner Name"
REP = "Rep"
CUSTOMER = "Customer Name"
SALE_DATE = "sp.Order Date (copy)"
INSTALL_DATE = "Current Install Date"
INSTALL_STATUS = "Install Status"
PRODUCT = "Product Type (Broken Out)"
PACKAGE = "Package"
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


def fetch(out_path: Optional[Path] = None, verbose: bool = True,
          page=None, worksheet: str = WORKSHEET) -> Path:
    from automations.shared.tableau_patchright import download_crosstab_patchright
    out_path = out_path or (Path(tempfile.gettempdir())
                            / "activations_today_pending_installs.csv")
    download_crosstab_patchright(VIEW_URL, worksheet, out_path,
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


def scheduled_on(rows: List[Dict[str, str]], day: dt.date) -> List[Dict[str, str]]:
    """Rows whose Current Install Date is `day`, sorted Rep A-Z then customer."""
    hit = [r for r in rows if parse_date(r.get(INSTALL_DATE)) == day]
    hit.sort(key=lambda r: (r.get(REP, "").casefold(),
                            r.get(CUSTOMER, "").casefold()))
    return hit
