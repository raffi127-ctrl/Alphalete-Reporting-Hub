"""Read the company intake sheet — one row per company.

Columns are matched by HEADER LABEL, never by position, so the sheet can be
reordered or extended without breaking this (per the no-hardcoded-columns rule).
Each row becomes a Company. The same structure serves Alphalete today and other
SCI companies later — they just add a row.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from automations.brand_audit import sheets
from automations.brand_audit.config import DEFAULT_INTAKE_SHEET_ID

# header keyword (lowercased, checked with `in`) -> Company field name.
# Order matters: first match wins, so put more specific keys first.
_HEADER_MAP = [
    ("icd", "icd_name"),
    ("company", "name"),
    ("owner", "owner"),
    ("location", "location"),
    ("fb", "facebook"),
    ("facebook", "facebook"),
    ("ig", "instagram"),
    ("instagram", "instagram"),
    ("google", "google_profile"),
    ("reddit", "reddit"),
    ("twitter", "twitter"),
    ("website", "website"),
    ("indeed", "indeed"),
    ("glassdoor", "glassdoor"),
    ("linkedin", "linkedin"),
    ("li link", "linkedin"),
    ("li ", "linkedin"),
]


@dataclass
class Company:
    name: str = ""
    icd_name: str = ""   # the ICD/owner this company maps to; names the log tab
    owner: str = ""
    location: str = ""
    facebook: str = ""
    instagram: str = ""
    google_profile: str = ""
    linkedin: str = ""
    reddit: str = ""
    twitter: str = ""
    website: str = ""
    indeed: str = ""
    glassdoor: str = ""
    raw: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        return d


def _field_for(header: str) -> Optional[str]:
    h = (header or "").strip().lower()
    if not h:
        return None
    # exact "x" header -> twitter/X
    if h == "x" or h == "x link":
        return "twitter"
    for key, fieldname in _HEADER_MAP:
        if key in h:
            return fieldname
    return None


def parse_rows(header: list[str], rows: list[list[str]]) -> list[Company]:
    """Pure parser (no network) — easy to unit-test with a fixed grid."""
    col_field = {i: _field_for(h) for i, h in enumerate(header)}
    companies: list[Company] = []
    for row in rows:
        values = {}
        raw = {}
        for i, cell in enumerate(row):
            cell = (cell or "").strip()
            hdr = header[i] if i < len(header) else f"col{i}"
            raw[hdr] = cell
            fn = col_field.get(i)
            if fn and cell:
                values.setdefault(fn, cell)
        if not values.get("name"):
            continue  # skip blank / spacer rows
        companies.append(Company(raw=raw, **values))
    return companies


def read_companies(sheet_id: str = DEFAULT_INTAKE_SHEET_ID,
                   worksheet: Optional[str] = None) -> list[Company]:
    """Open the intake sheet and return all companies."""
    sh = sheets.open_by_key(sheet_id)
    ws = sh.worksheet(worksheet) if worksheet else sh.sheet1
    grid = ws.get_all_values()
    if not grid:
        return []
    return parse_rows(grid[0], grid[1:])


def find_company(name: str, sheet_id: str = DEFAULT_INTAKE_SHEET_ID,
                 worksheet: Optional[str] = None) -> Optional[Company]:
    """Case-insensitive lookup by company name (substring tolerant)."""
    want = (name or "").strip().lower()
    companies = read_companies(sheet_id, worksheet)
    for c in companies:
        if c.name.strip().lower() == want:
            return c
    for c in companies:  # fall back to substring
        if want and want in c.name.strip().lower():
            return c
    return None
