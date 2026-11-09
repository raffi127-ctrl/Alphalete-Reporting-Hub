"""Verizon daily production for the Org Sales Board — the Verizon section, one
ICD: Nicolas Murrugarra (High Value Acquisitions, Inc., Grand Prairie TX; Carlos
org). Maud confirmed the section 2026-10-27; it sits where Frontier used to.

Source: Credico's emailed 'Verizon Wireless - Daily Sales Scorecard (SCI) -
Wireless Only' PDF — the same file the Country Trackers post
(tableau_screenshots.email_tracker, board `vzw_wireless`). Credico does not mail
us; Carlos's Gmail filter forwards it ~9:31am CT, so it is matched by subject and
filename, never by sender. NOT Tableau. Mirrors frontier_pull: fetch -> parse ->
to_board_pull, consumed by orchestrate's _adapter_verizon.

What the PDF holds: lines sold per OWNER per day, pages 1-3 = the current
Credico week and the two before it (Sun-Sat, 'Week Ending <Saturday>'), page 4 =
month to date by weekday (not used). No per-rep numbers.

The board section is Mon-Sun like every other section — NOT Sun-Sat the way
Frontier was. Every PDF day carries its real date, and the fill places a value
by its date, so Credico's Sunday lands in the board's Sunday of the right week.

TWO DAYS BEHIND at the morning fill: the newest PDF on hand at ~6am is
yesterday's, which runs through the day before. Future days in the PDF print as
0, so everything after 'sales through' (= the filename's date - 1) is dropped
rather than written as a zero nobody earned yet.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, Optional

ICD = "Nicolas Murrugarra"
METRIC = "Lines"
_DAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def fetch(dest_dir: Optional[Path] = None, page=None) -> Optional[Path]:
    """Newest Wireless Only scorecard PDF from the reporting inbox, or None.
    `page` is accepted + ignored (adapter parity — this comes from email)."""
    from automations.tableau_screenshots import email_tracker as et
    dest = Path(dest_dir) if dest_dir else Path("output")
    return et.fetch_vzw_pdf(dest / "verizon_scorecard", verbose=False)


def report_date(pdf_path: Path) -> Optional[dt.date]:
    """The edition's date, from the filename ('... - Wireless Only - 20261027.pdf')."""
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", Path(pdf_path).name)
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _row_values(page, owner: str) -> Optional[list]:
    """The owner's 7 day numbers (Sun..Sat) on one weekly page, read by
    position: each value is the number sitting under that day's header."""
    words = page.get_text("words")          # x0, y0, x1, y1, text, ...
    last = owner.split()[-1].lower()
    hit = next((w for w in words if w[4].lower() == last), None)
    if hit is None:
        return None
    y = (hit[1] + hit[3]) / 2
    row = [w for w in words if abs((w[1] + w[3]) / 2 - y) < 3]
    # The day header line: the 'Sun' word and its six siblings on that line.
    sun = next((w for w in words if w[4] == "Sun"), None)
    if sun is None:
        return None
    hy = (sun[1] + sun[3]) / 2
    hdr = {w[4]: (w[0] + w[2]) / 2 for w in words
           if w[4] in _DAYS and abs((w[1] + w[3]) / 2 - hy) < 3}
    if len(hdr) != 7:
        return None
    out = []
    for d in _DAYS:
        x = hdr[d]
        near = [w for w in row if re.fullmatch(r"\d+", w[4])
                and abs((w[0] + w[2]) / 2 - x) < 12]
        out.append(int(min(near, key=lambda w: abs((w[0] + w[2]) / 2 - x))[4])
                   if near else 0)
    return out


def parse(pdf_path: Path, owner: str = ICD) -> Dict[dt.date, int]:
    """{date: lines} for `owner` across every weekly page, through the edition's
    'sales through' day (report date - 1). {} if the owner isn't in it."""
    import fitz
    through = report_date(pdf_path)
    through = through - dt.timedelta(days=1) if through else None
    days: Dict[dt.date, int] = {}
    doc = fitz.open(str(pdf_path))
    try:
        for page in doc:
            m = re.search(r"Week Ending (\w+ \d{1,2}, \d{4})", page.get_text())
            if not m:
                continue                        # page 4 = month to date
            we_sat = dt.datetime.strptime(m.group(1), "%B %d, %Y").date()
            vals = _row_values(page, owner)
            if vals is None:
                # A weekly page with its day header but no row for the owner
                # = no lines sold that week so far (the scorecard lists only
                # owners who sold; same 'not in the tracker = 0' rule as
                # scoring_hc). Monday's edition opens the new Sun-Sat week
                # with an EMPTY page, and skipping it left Sunday blank, which
                # held the NEW A Players board all day (2026-11-09).
                if all(re.search(r"\b%s\b" % d, page.get_text()) for d in _DAYS):
                    vals = [0] * 7
                else:
                    continue
            sun = we_sat - dt.timedelta(days=6)
            for i, v in enumerate(vals):
                d = sun + dt.timedelta(days=i)
                if through is None or d <= through:
                    days[d] = v
    finally:
        doc.close()
    return days


def to_board_pull(days: Dict[dt.date, int]) -> dict:
    """parse() output -> the engine shape {owner_norm: {metric: {date: value}}}.
    Every date is passed; the fill keeps only the board week's own days."""
    if not days:
        return {}
    from automations.alphalete_org_report.tableau_http import _norm_owner
    return {_norm_owner(ICD): {METRIC: dict(days)}}


def week_totals(days: Dict[dt.date, int]) -> Dict[dt.date, Dict[dt.date, int]]:
    """Group days into the BOARD's Mon-Sun weeks: {week-ending Sunday: {date: v}}.
    Used by the one-off backfill to rebuild past weeks."""
    out: Dict[dt.date, Dict[dt.date, int]] = {}
    for d, v in days.items():
        we_sun = d + dt.timedelta(days=(6 - d.weekday()))
        out.setdefault(we_sun, {})[d] = v
    return out


def edition(report_date: dt.date, dest_dir: Optional[Path] = None) -> Optional[Path]:
    """The edition mailed ON `report_date` (sales through the day before), or
    None if it never reached the inbox."""
    from automations.shared import email_ingest
    from automations.tableau_screenshots import email_tracker as et
    dest = (Path(dest_dir) if dest_dir else Path("output")) / "verizon_scorecard"
    glob = f"Daily Sales - Verizon Wireless*Wireless Only*{report_date:%Y%m%d}.pdf"
    got = email_ingest.fetch_by_globs("", [glob], dest, subject=et.VZW_SUBJECT,
                                      since_days=max(3, (dt.date.today() - report_date).days + 3),
                                      verbose=False)
    return got.get(glob)


def _page_week_ending(page) -> Optional[dt.date]:
    """The Saturday in a weekly page's 'Week Ending <date>' line; None on page 4."""
    m = re.search(r"Week Ending (\w+ \d{1,2}, \d{4})", page.get_text())
    return dt.datetime.strptime(m.group(1), "%B %d, %Y").date() if m else None


def scoring_hc(pdf_path: Path, owner: str = ICD,
               week_ending: Optional[dt.date] = None) -> Optional[int]:
    """The owner's 'Scoring HC' for one Credico week (Sun-Sat, to date) -- reps
    who scored at least one line. 0 when the owner is not on that week's page
    (the same 'not in the tracker = 0' rule the headcount tab uses), None when
    the page or the column can't be found.

    `week_ending` = that week's Saturday; None = page 1, the edition's current
    week. Sat 10/31 and Sun 11/1 read 0 for Nicolas Murrugarra (the real count
    was 15) because the edition mailed on Sunday already opens on the NEW week,
    empty, and the week that just closed moved to page 2."""
    import fitz
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[0]
        if week_ending is not None:
            page = next((pg for pg in doc if _page_week_ending(pg) == week_ending), None)
            if page is None:
                return None
        words = page.get_text("words")
        hc = next((w for w in words if w[4] == "HC"), None)
        if hc is None:
            return None
        x = (hc[0] + hc[2]) / 2
        last = owner.split()[-1].lower()
        hit = next((w for w in words if w[4].lower() == last), None)
        if hit is None:
            return 0
        y = (hit[1] + hit[3]) / 2
        near = [w for w in words if abs((w[1] + w[3]) / 2 - y) < 3
                and re.fullmatch(r"\d+", w[4]) and abs((w[0] + w[2]) / 2 - x) < 12]
        return int(min(near, key=lambda w: abs((w[0] + w[2]) / 2 - x))[4]) if near else None
    finally:
        doc.close()
