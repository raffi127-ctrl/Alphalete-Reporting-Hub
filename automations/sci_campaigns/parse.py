"""Turn the two tracker PDFs into {sheet row label -> weekly units}.

WHERE EACH OF THE TAB'S 13 ROWS COMES FROM
------------------------------------------
Neither PDF alone fills the tab. Reverse-engineered 2026-07-27 from every week
the VAs filled by hand (2025-08 .. 2026-03) — the split below reproduces all 13
rows exactly on every week where both PDFs parse:

  "… - Campaign Totals By Day.pdf"  (the 'LW Week Ending' total column)
      AT&T           -> AT&T Fiber
      Frontier       -> Frontier Fiber
      DTV            -> DTV
      Lumen          -> Lumen Fiber           (renamed 'Quantum Fiber' 2026-06)
      Verizon FiOS   -> Verizon FiOS Fiber
      Verizon 5G     -> Verizon 5G Fiber      (dropped from the PDF 2025-11)
      Rogers         -> Rogers                (new WE 8.15.2026)
      Rogers Wireless-> Rogers Wireless       (new WE 8.15.2026)
      Kinetic        -> Kinetic                (row added 2026-08-28)
      AT&T B2B       -> B2B

  the RANKED PDF's FOOTER  (the 'LW Week Ending' column)
      AT&T NDS Total                          -> AT&T NDS
      AT&T Selling … Wireless Total           -> AT&T selling Wireless
      Frontier Selling … Wireless Total       -> Frontier Selling Wireless
      Verizon FiOS Selling … Wireless Total   -> Verizion FiOS Selling Wireless
      Verizon 5G Selling … Wireless Total     -> Verizon 5G selling VZ Wireless

The by-day PDF ALSO carries 'AT&T NDS', 'AT&T Wireless' and 'VZ Wireless', but
those are NOT what the tab wants: 'VZ Wireless' is one lump the tab splits three
ways, and the footer is the authoritative breakout. We cross-check the two AT&T
NDS figures against each other instead (check_consistency).

'T-mobile Fiber' appears in neither PDF and has been 0 for over a year — it, and
any other row the PDFs stop reporting, fills 0 (see fill.py, which warns when a
row that was PRODUCING last week goes missing rather than silently zeroing it).
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

import pdfplumber

# --- by-day PDF: exact campaign name -> tab row label -----------------------
BYDAY_MAP = {
    "at&t": "AT&T Fiber",
    "frontier": "Frontier Fiber",
    "dtv": "DTV",
    "lumen": "Lumen Fiber",
    "quantum fiber": "Lumen Fiber",
    "verizon fios": "Verizon FiOS Fiber",
    "verizon 5g": "Verizon 5G Fiber",
    "at&t b2b": "B2B",
    # New campaigns Adriana started reporting WE 8.15.2026, given their own rows
    # on the tab 2026-08-28 (Eve's call) — before that they landed in `unknown`
    # and the identity check was off by their combined 4,115.
    "rogers": "Rogers",
    "rogers wireless": "Rogers Wireless",
    # Kinetic (Windstream) reported since WE 7.25.2026 but deliberately kept off
    # the tab until 2026-08-28, when Eve gave it a row alongside Rogers.
    "kinetic": "Kinetic",
}
# by-day rows we deliberately ignore (the footer supplies these, better split)
BYDAY_IGNORED = {"at&t nds", "at&t wireless", "vz wireless"}

# --- RANKED footer: matched by PREFIX, because the middle qualifier drifts
# ("Frontier Selling VZ Wireless" vs "Frontier Selling AT&T Wireless" — both
# seen). Order matters: 'at&t nds' before the generic 'at&t selling'.
FOOTER_RULES: List[tuple] = [
    ("at&t nds", "AT&T NDS"),
    ("at&t selling", "AT&T selling Wireless"),
    ("frontier selling", "Frontier Selling Wireless"),
    ("verizon fios selling", "Verizion FiOS Selling Wireless"),
    ("verizon 5g selling", "Verizon 5G selling VZ Wireless"),
]

# A campaign-totals row: rank, name, 7 day columns, LW total, and — only since
# 2025-08-23 — a 'Previous Week Ending' total. The second total is OPTIONAL so
# the original single-column layout still parses; we only ever read the LW one.
_BYDAY_ROW = re.compile(
    r"^\s*\d+\s+(.+?)\s+(?:[\d,]+\s+){7}([\d,]+)(?:\s+([\d,]+))?\s*$")
# A footer total, found ANYWHERE in a line rather than anchored to it. The
# RANKED PDF is three trackers side by side, so pdfplumber flattens two (even
# three) different trackers' footers onto ONE line, separated by a '#' gutter:
#   "Verizon FiOS Total 2681 2522 # Frontier Selling AT&T Wireless Total 34 39"
# An anchored regex sees only the last block and silently drops the wireless
# rows — which then fill 0 and read as a real collapse. finditer over each
# '#'-delimited segment picks up every block on the line.
_FOOTER_ANY = re.compile(
    r"([A-Za-z][A-Za-z0-9&.'/\- ]*?)\s+Total\s+([\d,]+)\s+([\d,]+)")
_HDR_DATE = re.compile(r"(\d{1,2}\.\d{1,2}\.\d{2,4})")


def header_date(label: str) -> Optional["dt.date"]:
    """'8.8.26' / '8.8.2026' -> date. None for anything else.

    The by-day PDF prints the two week-endings it covers ('8.15.26', '8.8.26'),
    which is the only way to CONFIRM that its 'Previous Week Ending' column is
    the week we think it is — see run.resolve_week. Adriana skipped WE 8.8.2026
    entirely, and the RANKED PDF that followed restated 8.1 in that column."""
    m = re.fullmatch(r"\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*", label or "")
    if not m:
        return None
    y = int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return dt.date(y, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


class ParseError(RuntimeError):
    pass


class Parsed(NamedTuple):
    values: Dict[str, int]        # tab row label -> weekly units
    byday_grand: Optional[int]    # the by-day PDF's Grand Total (LW column)
    byday_extra: Dict[str, int]   # the ignored by-day rows, for the audit
    header_weeks: List[str]       # ['7.18.26', '7.11.26'] as printed
    unknown: Dict[str, int]       # campaign -> units we didn't recognise


def _int(s: str) -> int:
    return int(s.replace(",", "").strip())


def _text(pdf_path: Path) -> str:
    with pdfplumber.open(str(pdf_path)) as pdf:
        return "\n".join(pg.extract_text() or "" for pg in pdf.pages)


def parse_byday(pdf_path: Path, *, prev: bool = False) -> tuple:
    """-> ({row label: units}, grand_total, {ignored name: units}, header_weeks,
    {unknown name: units}).

    Reads the 'LW Week Ending' total, or with prev=True the 'Previous Week
    Ending' one — see parse_week's `prev` for why that column matters.
    """
    text = _text(pdf_path)
    vals: Dict[str, int] = {}
    extra: Dict[str, int] = {}
    unknown: Dict[str, int] = {}
    for line in text.splitlines():
        m = _BYDAY_ROW.match(line)
        if not m:
            continue
        raw = m.group(3) if prev else m.group(2)
        if raw is None:
            raise ParseError(
                f"{pdf_path.name} has no 'Previous Week Ending' column (the "
                f"original single-total layout) — can't recover a prior week "
                f"from it.")
        name = " ".join(m.group(1).split())
        key = name.casefold()
        if key in BYDAY_MAP:
            vals[BYDAY_MAP[key]] = _int(raw)
        elif key in BYDAY_IGNORED:
            extra[name] = _int(raw)
        else:
            unknown[name] = _int(raw)
    if not vals:
        raise ParseError(
            f"{pdf_path.name}: no campaign rows parsed — the 'Campaign Totals "
            f"By Day' layout changed. First lines:\n"
            + "\n".join(text.splitlines()[:8]))
    g = re.search(r"Grand Total\s+([\d,]+)(?:\s+([\d,]+))?", text)
    grand = None
    if g:
        raw = g.group(2) if prev else g.group(1)
        grand = _int(raw) if raw else None
    return (vals, grand, extra, _HDR_DATE.findall(text)[:2], unknown)


def parse_footer(pdf_path: Path, *, prev: bool = False) -> Dict[str, int]:
    """The RANKED PDF's footer totals -> {tab row label: units}, from the LW
    column or (prev=True) the 'Previous Week Ending' one."""
    text = _text(pdf_path)
    out: Dict[str, int] = {}
    for line in text.splitlines():
        for seg in line.split("#"):
            for m in _FOOTER_ANY.finditer(seg):
                name = " ".join(m.group(1).split()).casefold()
                if name.endswith("grand"):
                    continue
                for prefix, label in FOOTER_RULES:
                    if name.startswith(prefix):
                        # First occurrence wins: the tracker footers are printed
                        # once each, and a later page repeat would be the same
                        # block. setdefault also keeps the LEFT-most (correct)
                        # segment when a line carries two trackers.
                        out.setdefault(label, _int(m.group(3 if prev else 2)))
                        break
    if not out:
        raise ParseError(
            f"{pdf_path.name}: no '… Total' footer rows parsed — the RANKED "
            f"PDF layout changed. Last lines:\n"
            + "\n".join(text.splitlines()[-8:]))
    return out


def parse_week(byday_pdf: Optional[Path], main_pdf: Optional[Path],
               *, prev: bool = False) -> Parsed:
    """Both PDFs -> one {tab row label: units} map. Both are REQUIRED: with only
    the by-day PDF every wireless row would fill 0, which reads as a real
    collapse rather than a missing attachment.

    prev=True reads the 'Previous Week Ending' column instead, i.e. these PDFs
    describe week W and we want W-7. Both PDFs restate the prior week in full,
    which is how run.py recovers a week whose OWN email is unusable — Adriana
    has sent a week as JPGs only (WE 6.20.2026), dropped the RANKED PDF (WE
    6.6.2026), and skipped the inbox entirely (WE 5.30.2026, which arrived only
    as Rafael's forward). All three were recovered from the FOLLOWING week's
    attachments, and each reconciled exactly against check_consistency.
    """
    if byday_pdf is None:
        raise ParseError("missing the 'Campaign Totals By Day' PDF")
    if main_pdf is None:
        raise ParseError("missing the RANKED tracker PDF (carries the "
                         "AT&T NDS + 'Selling … Wireless' footer totals)")
    vals, grand, extra, weeks, unknown = parse_byday(byday_pdf, prev=prev)
    vals.update(parse_footer(main_pdf, prev=prev))
    return Parsed(vals, grand, extra, weeks, unknown)


def check_consistency(p: Parsed) -> List[str]:
    """Cross-checks that hold on every hand-filled week. Returns warning lines
    (empty = clean). These catch a layout drift that still parses.

    1. AT&T NDS is printed in BOTH PDFs — they must agree.
    2. The by-day Grand Total is an identity once the wireless lump is swapped
       for the footer's four-way split:
         grand - (AT&T Wireless + VZ Wireless) + (the 4 footer wireless rows)
       must equal the sum of the tab's 13 rows.
    """
    warn: List[str] = []
    nds_byday = p.byday_extra.get("AT&T NDS")
    nds_foot = p.values.get("AT&T NDS")
    if nds_byday is not None and nds_foot is not None and nds_byday != nds_foot:
        warn.append(f"AT&T NDS disagrees between the PDFs: by-day={nds_byday} "
                    f"vs RANKED footer={nds_foot} — using the footer.")
    if p.byday_grand is not None:
        lump = sum(v for k, v in p.byday_extra.items() if k != "AT&T NDS")
        wireless = sum(p.values.get(k, 0) for k in (
            "AT&T selling Wireless", "Frontier Selling Wireless",
            "Verizion FiOS Selling Wireless", "Verizon 5G selling VZ Wireless"))
        expect = p.byday_grand - lump + wireless
        got = sum(p.values.values())
        if expect != got:
            warn.append(f"total identity off by {got - expect}: rows sum to "
                        f"{got}, but the by-day Grand Total implies {expect}.")
    if p.unknown:
        # With the units, not just the names: the identity warning above is
        # off by exactly this much, and it's how you tell one new campaign the
        # tab may want a row for from noise.
        warn.append("unmapped campaign(s) in the by-day PDF — they are NOT "
                    "being written anywhere: "
                    + ", ".join(f"{k} {v}" for k, v in sorted(p.unknown.items())))
    return warn
