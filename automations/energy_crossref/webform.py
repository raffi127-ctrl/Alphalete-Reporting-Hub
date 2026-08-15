"""The Base Power Energy webform ('Form Responses 1') -> one row per SALE.

Every Energy rep is supposed to fill this Google Form once per sale. The tab is
the form's own response sheet, so it is append-only and NEVER sorted: a row's
Timestamp is when the rep filled the form, which is regularly a different day
from the sale. So the day is read off **col J 'Date of Sale'**, never off the
timestamp — on 8/13 alone reps submitted sales dated 7/29, 8/7, 8/10 and 8/11.

DUPLICATES ARE THE WHOLE POINT OF THIS FILE. The cross-reference asks "did this
rep file as many forms as they have sales", so a rep who submitted the SAME sale
twice reads as fully covered when they are actually one form short. Two rows are
the same sale when they carry the same rep AND either the same customer name or
the same phone number. Address is deliberately NOT a dedupe key — a referral in
the same building is a real second sale — it only earns a warning.

Column letters are never hardcoded: every column is found by its header text in
row 1, because this sheet grows a column whenever the form gains a question.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

SHEET_ID = "1wwvSEQAYqeGfgguvUeBR5ebtmez0JSik4BCHKOswa50"
TAB = "Form Responses 1"

# Header text -> the field we need. Matched as a case-insensitive PREFIX on the
# squeezed header, so the trailing-space / punctuation drift the form questions
# carry ("Customers first, last name? ") doesn't break the lookup.
HEADERS = {
    "timestamp": "timestamp",
    "rep": "your first and last name",
    "manager": "your managers name",
    "customer": "customers first, last name",
    "phone": "customers phone number",
    "address": "customers address",
    "sale_date": "date of sale",
}


@dataclass
class Submission:
    """One webform row."""
    row: int                       # 1-based row on the tab
    rep: str
    manager: str
    customer: str
    phone: str
    address: str
    sale_date: dt.date | None
    timestamp: str

    @property
    def phone_digits(self) -> str:
        d = re.sub(r"\D", "", self.phone)
        return d[-10:] if len(d) >= 10 else ""


@dataclass
class RepForms:
    """Every submission one rep filed for the day, after dedupe."""
    rep: str                       # as typed on the form
    kept: list[Submission] = field(default_factory=list)
    dupes: list[tuple[Submission, Submission]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.kept)


def _squeeze(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def header_cols(header_row: list[str]) -> dict[str, int]:
    """{field: 0-based column} found by header text. Raises on a missing one —
    a renamed question is a real break, not something to guess around."""
    squeezed = [_squeeze(h) for h in header_row]
    out: dict[str, int] = {}
    for field_name, needle in HEADERS.items():
        c = next((i for i, h in enumerate(squeezed) if h.startswith(needle)), None)
        if c is None:
            raise RuntimeError(
                f"the webform tab has no {field_name!r} column (looked for a "
                f"header starting {needle!r}); the form question was renamed — "
                f"update HEADERS in webform.py. Headers seen: {squeezed}")
        out[field_name] = c
    return out


def parse_date(raw: str) -> dt.date | None:
    """'8/13/2026', '08/13/26', '2026-08-13' -> a date. None when unreadable."""
    s = str(raw).strip()
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
    else:
        m = re.match(r"^(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{2,4})", s)
        if not m:
            return None
        mo, d, y = (int(x) for x in m.groups())
        if y < 100:
            y += 2000
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def read_rows(grid: list[list[str]]) -> list[Submission]:
    """The whole tab -> Submissions (blank rep rows dropped)."""
    cols = header_cols(grid[0])

    def cell(r: list[str], key: str) -> str:
        c = cols[key]
        return str(r[c]).strip() if c < len(r) else ""

    out = []
    for i, r in enumerate(grid[1:], start=2):
        rep = cell(r, "rep")
        if not rep:
            continue
        out.append(Submission(
            row=i, rep=rep, manager=cell(r, "manager"),
            customer=cell(r, "customer"), phone=cell(r, "phone"),
            address=cell(r, "address"),
            sale_date=parse_date(cell(r, "sale_date")),
            timestamp=cell(r, "timestamp")))
    return out


def _norm(s: str) -> str:
    """Lowercase, punctuation-free, suffix-free — for comparing free-typed names.
    Reps type their own name differently every night ('Ivan soto', 'Miguel
    vargas'), and customer names arrive in every case ('SATYA BALAGAM')."""
    n = re.sub(r"\([^)]*\)", " ", str(s).lower())
    n = re.sub(r"[^a-z ]", " ", n)
    n = re.sub(r"\b(sr|jr|iii|ii)\b", " ", n)
    return " ".join(n.split())


def _norm_address(s: str) -> str:
    """Like _norm but KEEPS THE DIGITS. Stripping them turned '7732 LA HAYE DR'
    and '7747 la haye dr' — two real sales, neighbours on one street, referred by
    each other on 8/13 — into the same string and flagged Pranish for a duplicate
    he never filed. A street number is most of what tells two addresses apart."""
    n = re.sub(r"[^a-z0-9 ]", " ", str(s).lower())
    return " ".join(n.split())


def _same_sale(a: Submission, b: Submission) -> str:
    """Why these two rows are the same sale, or '' if they aren't.

    Address is NOT here on purpose: two of the 8/13 sales were neighbours on one
    street referred by each other, and a duplex/apartment pair would read as a
    dupe and quietly shrink a rep's credit."""
    if a.phone_digits and a.phone_digits == b.phone_digits:
        return f"same phone {a.phone}"
    ca, cb = _norm(a.customer), _norm(b.customer)
    if ca and ca == cb:
        return f"same customer {a.customer!r}"
    return ""


def for_day(rows: list[Submission], day: dt.date) -> tuple[dict[str, RepForms], list[str]]:
    """({normalised rep -> RepForms}, address-collision warnings) for one sale day.

    Duplicates are dropped from the count and kept on the RepForms so the run can
    name them: a rep whose second form is a re-file is still one form short.
    """
    today = [s for s in rows if s.sale_date == day]
    by_rep: dict[str, RepForms] = {}
    for s in sorted(today, key=lambda s: s.row):
        key = _norm(s.rep)
        rf = by_rep.setdefault(key, RepForms(rep=s.rep))
        hit = next(((k, why) for k in rf.kept if (why := _same_sale(k, s))), None)
        if hit:
            rf.dupes.append((hit[0], s))
        else:
            rf.kept.append(s)

    warnings = []
    for rf in by_rep.values():
        seen: dict[str, Submission] = {}
        for s in rf.kept:
            a = _norm_address(s.address)
            if not a:
                continue
            if a in seen:
                warnings.append(
                    f"{rf.rep}: rows {seen[a].row} and {s.row} share an address "
                    f"({s.address!r}) but different customers "
                    f"({seen[a].customer!r} / {s.customer!r}) — counted as TWO "
                    "sales; check that it isn't one sale filed twice")
            seen[a] = s
    return by_rep, warnings


def load(sheet_id: str = SHEET_ID, tab: str = TAB) -> list[Submission]:
    from automations.recruiting_report.fill import open_by_key
    ss = open_by_key(sheet_id)
    return read_rows(ss.worksheet(tab).get_all_values())
