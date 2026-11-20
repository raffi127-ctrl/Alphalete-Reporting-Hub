"""Daily COUNTRY totals out of Credico's daily scorecard PDFs (Fios, Frontier).

Both mails ("Verizon Fios - Daily Sales Scorecard (SCI)" and "Frontier by
Verizon // Daily Sales Scorecard // SCI") carry a 4-page PDF: pages 1-3 = this
week and the two before (Sun..Sat), page 4 = month to date. Each week page has a
date header ('11/15 11/16 … 11/21' over 'Sun Mon … Sat'), one row per owner,
then a RED TOTALS ROW with no name in it — that row is the whole of SCI for the
program, which is the 'country' number Raf asked for. Days not reported yet are
blank in the PDF (an invisible 0 in its text) and are cut at the edition date
in the filename, so they come back as missing here, never as 0.

Verified 2026-11-20 on the 11/20 editions:
  Fios     WE 11/21: Sun 54, Mon 522, Tue 522, Wed 541, Thu 533  (Total 2,756)
  Frontier WE 11/21: Sun 30, Mon 448, Tue 512, Wed 564, Thu 425  (Total 2,322)

Columns are located by the date header's x position each run, never by index.
The Fios page has a second table under the owners (by Sales Market); it has a
market name in the left columns, so it can never be mistaken for the totals row.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.shared import email_ingest

SOURCES = {
    # program -> (mail subject, attachment glob)
    "Fios": ("Verizon Fios - Daily Sales Scorecard",
             "Daily Sales - Verizon Fios - SCI*.pdf"),
    "Frontier": ("Frontier by Verizon // Daily Sales Scorecard",
                 "Daily Sales - Frontier by Verizon - SCI*.pdf"),
}

_MD = re.compile(r"^(\d{1,2})/(\d{1,2})$")
_WE = re.compile(r"Week Ending\s+([A-Za-z]+ \d{1,2}, \d{4})")
_NUM = re.compile(r"^-?[\d,]+$")
_DEC = re.compile(r"^-?[\d,]*\.\d+%?$|^-?[\d,]+%$")   # 4.2, 88.1%, 100%

Word = Tuple[float, float, float, float, str]


def _lines(words: List[Word], tol: float = 2.5) -> List[List[Word]]:
    """Group words into visual lines (same baseline within `tol` pt), top-down,
    each line sorted left to right."""
    out: List[List[Word]] = []
    for w in sorted(words, key=lambda w: (w[1], w[0])):
        if out and abs(out[-1][0][1] - w[1]) <= tol:
            out[-1].append(w)
        else:
            out.append([w])
    return [sorted(l, key=lambda w: w[0]) for l in out]


def _xc(w: Word) -> float:
    return (w[0] + w[2]) / 2


def parse_week_words(words: List[Word], page_text: str
                     ) -> Dict[dt.date, int]:
    """{date: country units} for one week page, from its words.

    `words` are (x0, y0, x1, y1, text) like PyMuPDF's get_text('words')."""
    m = _WE.search(page_text)
    if not m:
        return {}
    we = dt.datetime.strptime(m.group(1), "%B %d, %Y").date()
    lines = _lines([tuple(w[:5]) for w in words])

    # 1. the date header: the line with 7 consecutive m/d stamps
    hdr_i, cols = None, []
    for i, ln in enumerate(lines):
        stamps = [w for w in ln if _MD.match(w[4])]
        if len(stamps) == 7:
            hdr_i, cols = i, stamps
            break
    if hdr_i is None:
        return {}
    dates = []
    for w in cols:
        mo, d = map(int, _MD.match(w[4]).groups())
        yr = we.year - (1 if mo > we.month else 0)     # a Dec/Jan week
        dates.append(dt.date(yr, mo, d))
    xs = [_xc(w) for w in cols]
    half = min(b - a for a, b in zip(xs, xs[1:])) / 2
    left_edge = xs[0] - half

    # 2. the 'Owner Name' header, then the first all-numeric line whose first
    #    word starts at the Sun column (no name/office/territory text) = totals
    start = next((i for i, ln in enumerate(lines)
                  if i > hdr_i and any(w[4] == "Owner" for w in ln)), hdr_i)
    for ln in lines[start + 1:]:
        if not ln or ln[0][0] < left_edge - 1:
            continue
        if not all(_NUM.match(w[4]) or _DEC.match(w[4]) or w[4] == "-"
                   for w in ln):
            continue
        out: Dict[dt.date, int] = {}
        for w in ln:
            if not _NUM.match(w[4]):
                continue
            for x, d in zip(xs, dates):
                if abs(_xc(w) - x) <= half:
                    out[d] = int(w[4].replace(",", ""))
        return out
    return {}


def parse_pdf(path: str | Path) -> Dict[dt.date, int]:
    """{date: country units} across every WEEK page of one scorecard PDF
    (the month-to-date page has no dates and is skipped on its own)."""
    import fitz
    out: Dict[dt.date, int] = {}
    # Days not reported yet print as an invisible 0, not a blank, so cut at the
    # edition date in the filename ('… - SCI - 20261120.pdf' = sales through
    # 11/19). No date in the name -> keep everything.
    m = re.search(r"(\d{8})\.pdf$", Path(path).name)
    edition = dt.datetime.strptime(m.group(1), "%Y%m%d").date() if m else None
    doc = fitz.open(str(path))
    try:
        for page in doc:
            got = parse_week_words(page.get_text("words"), page.get_text())
            for d, v in got.items():
                if edition is None or d < edition:
                    out.setdefault(d, v)      # page 1 (newest) wins
    finally:
        doc.close()
    return out


def fetch_pdf(program: str, dest: str | Path, *, since_days: int = 4,
              verbose: bool = False) -> Optional[Path]:
    """Newest scorecard PDF for `program` ('Fios' | 'Frontier'), or None."""
    subject, glob = SOURCES[program]
    found = email_ingest.fetch_by_globs("", [glob], dest, subject=subject,
                                        since_days=since_days, verbose=verbose)
    return next(iter(found.values()), None)


def edition(path: str | Path) -> Optional[dt.date]:
    """The edition date in a scorecard filename ('… - SCI - 20261120.pdf')."""
    m = re.search(r"(\d{8})\.pdf$", Path(path).name)
    return dt.datetime.strptime(m.group(1), "%Y%m%d").date() if m else None


def editions(dest: str | Path) -> Dict[str, Optional[dt.date]]:
    """{program: edition date of the newest PDF in the inbox, or None}. Used
    by the orchestrator's readiness gate: today's edition = yesterday's sales."""
    out = {}
    for prog in SOURCES:
        p = fetch_pdf(prog, dest)
        out[prog] = edition(p) if p else None
    return out


def country_days(dest: str | Path, *, verbose: bool = False
                 ) -> Dict[str, Dict[dt.date, int]]:
    """{'Fios': {date: n}, 'Frontier': {date: n}} from the newest PDFs.
    A program whose PDF hasn't landed comes back as {} (the image says so)."""
    out = {}
    for prog in SOURCES:
        p = fetch_pdf(prog, dest, verbose=verbose)
        out[prog] = parse_pdf(p) if p else {}
    return out


if __name__ == "__main__":
    import sys
    for f in sys.argv[1:]:
        got = parse_pdf(f)
        print(Path(f).name)
        for d in sorted(got):
            print(f"  {d:%a %m/%d}: {got[d]}")
