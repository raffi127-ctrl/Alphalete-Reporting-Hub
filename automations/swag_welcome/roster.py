"""Pure roster logic: phone normalization + quoted-name handling.

No I/O, no network — everything here is deterministic and unit-testable so
the fragile bits (Claude vision, iMessage, image compositing) stay thin.

The screenshot has three columns: Name (first name), Last Name, Phone. We
only ever text using the FIRST name + phone. A name cell can carry a quoted
alternate that means one of two different things, and there's no reliable way
to tell them apart automatically:

    Auryn "RN"        → pronunciation guide   → use the real name (Auryn)
    Jonathan "Jon"    → preferred nickname    → use the nickname (Jon)

So we never auto-decide: we surface BOTH and the preflight screen makes a
human pick. `default_name` leans to the real name; `needs_quote_decision`
tells the UI to force a choice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict


# --------------------------------------------------------------------------
# Phone normalization
# --------------------------------------------------------------------------

def normalize_phone(raw: str) -> tuple[str | None, str | None]:
    """Return (e164, warning). e164 is like '+12147321780' or None if we
    couldn't make a valid US 10-digit number out of it.

    Handles the messy inputs seen in real rosters: a leading country-code 1
    (12147321780), a bare 10-digit (2147322212), and dash/paren/space
    formatting (214-535-9794). Anything that doesn't resolve to 10 national
    digits comes back with a warning so preflight can flag it instead of
    silently texting a wrong number.
    """
    if raw is None:
        return None, "no phone"
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None, "no phone"
    # Drop a leading US country code if present.
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return "+1" + digits, None
    # 11+ digits not starting with 1, or too short — surface, don't guess.
    return None, f"unexpected phone ({len(digits)} digits): {raw!r}"


def pretty_phone(e164: str | None) -> str:
    """'+12147321780' → '(214) 732-1780' for display. Falls back to the raw
    string if it isn't a +1 10-digit number."""
    if not e164:
        return ""
    m = re.fullmatch(r"\+1(\d{3})(\d{3})(\d{4})", e164)
    if not m:
        return e164
    return f"({m.group(1)}) {m.group(2)}-{m.group(3)}"


# --------------------------------------------------------------------------
# Quoted-name handling
# --------------------------------------------------------------------------

_QUOTE_RE = re.compile(r"""["“”']([^"“”']+)["“”']""")


def split_quoted_name(name_cell: str) -> tuple[str, str | None]:
    """('Davone "Day VEON"') → ('Davone', 'Day VEON').

    The base name is everything outside the quotes (collapsed whitespace);
    the quoted alternate is whatever was inside. Returns (base, None) when
    there's no quoted part. Note the base can be multi-word ('Jose Angel') —
    that's a legit two-part first name, not a nickname.
    """
    if not name_cell:
        return "", None
    text = str(name_cell).strip()
    m = _QUOTE_RE.search(text)
    if not m:
        return re.sub(r"\s+", " ", text), None
    quoted = m.group(1).strip()
    base = _QUOTE_RE.sub("", text)
    base = re.sub(r"\s+", " ", base).strip()
    return base, (quoted or None)


# --------------------------------------------------------------------------
# Recipient model
# --------------------------------------------------------------------------

@dataclass
class Recipient:
    """One row of the preflight table. `chosen_name` is what actually gets
    written on the card + used in the message; it defaults to the real name
    and the preflight UI can flip it to the quoted alternate."""

    raw_name: str            # exact Name-cell text from the screenshot
    base_name: str           # name with any quoted part removed
    quoted_alt: str | None   # text inside quotes, if any
    phone_e164: str | None
    phone_raw: str = ""
    chosen_name: str = ""    # what to print/text; defaults to base_name
    include: bool = True     # preflight can toggle a row out of the batch
    warnings: list[str] = field(default_factory=list)

    @property
    def needs_quote_decision(self) -> bool:
        return self.quoted_alt is not None

    @classmethod
    def from_cells(cls, name_cell: str, phone_cell: str) -> "Recipient":
        base, quoted = split_quoted_name(name_cell)
        e164, warn = normalize_phone(phone_cell)
        warnings = [warn] if warn else []
        if not base:
            warnings.append("no name")
        return cls(
            raw_name=str(name_cell or "").strip(),
            base_name=base,
            quoted_alt=quoted,
            phone_e164=e164,
            phone_raw=str(phone_cell or "").strip(),
            chosen_name=base,
            warnings=warnings,
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["needs_quote_decision"] = self.needs_quote_decision
        d["phone_pretty"] = pretty_phone(self.phone_e164)
        return d


def build_roster(rows: list[dict]) -> list[Recipient]:
    """rows: [{'name': 'Davone "Day VEON"', 'phone': '12147321780'}, ...]
    (the 'last_name' column is ignored — we only text first name + phone)."""
    out = []
    for r in rows:
        out.append(Recipient.from_cells(r.get("name", ""), r.get("phone", "")))
    return out
