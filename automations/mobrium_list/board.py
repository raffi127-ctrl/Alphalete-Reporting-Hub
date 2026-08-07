"""The week's new starts, off the SALES BOARD's 'New Starts/Raf' box.

Same workbook and same box terminated_reps reads, so the tab is picked and the
box is located with that module's helpers rather than a second copy of the
label-hunting logic. A new 'Sales Board WE <m>.<d>' tab is created by hand every
MONDAY; `board.pick_tab` handles both that and the week where it hasn't been
made yet, so a Friday run always lands on the current week.

WHAT THE BOX ACTUALLY LOOKS LIKE (checked across WE 7.26 → 8.9, 2026-08-07):

  C Classroom (the name) · D Trainers · E Email · F Ran Orientation · K Location

but about a third of the rows on any given week are SHIFTED one column right —
E holds a checkbox, F the email, G the phone. That is not corruption, it's how
the box gets filled: the shifted rows are the only ones that carry a PHONE at
all. So we don't read column E; we sweep the box's columns and take the first
email-shaped cell and the first phone-shaped cell on the row. That recovers the
phone for the shifted rows and reads the plain rows exactly the same way.

AND THE EMAIL COLUMN GOES OUT OF STEP WITH THE NAMES. On WE 8.9, row 'David
Redmon' carries carloferrino744@gmail.com, 'Jesus Galvan' carries Brian Bivens's
address, 'Carlo Ferrino' carries Ashley Diaz's — every one of them belongs to
someone else in the same box, shifted by a few rows. WE 8.2 and 7.26 line up
fine, so it is this week's data entry, not the layout. It is also invisible: an
address that looks perfectly valid is simply the wrong person's.

That is why OwnerVille is the primary source for BOTH email and phone, and what
we scrape here is a fallback used only for people OwnerVille has never heard of
— and then only when the address plausibly belongs to them (see `belongs_to`).
An unclaimable address is dropped and reported, never written: a Mobrium review
request sent to the wrong person is worse than a blank cell somebody fills in.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import List, Optional

from automations.recruiting_report.fill import open_by_key
from automations.terminated_reps import board as tboard
from automations.mobrium_list.ownerville import name_tokens

SHEET_ID = tboard.SHEET_ID

# How far right of the name column the box's own fields can sit. K (Location) is
# the last labelled one; the shifted rows push email/phone to F/G. 12 covers
# both with room to spare and stops well short of the roster's day blocks.
BOX_SCAN_COLS = 12

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# 10 digits, optionally with a leading US country code, in any punctuation.
_PHONE_DIGITS = re.compile(r"\d")

# A name token has to be this long before it may vouch for an email address.
# 'ann' would match half the alphabet; 'diaz' is specific enough to mean it.
MIN_TOKEN = 4


class BoardError(RuntimeError):
    pass


@dataclass(frozen=True)
class NewStart:
    """One row of the 'New Starts/Raf' box."""
    name: str
    email: str          # as scraped — NOT yet checked against the name
    phone: str          # as scraped
    tab: str
    row: int


def belongs_to(email: str, name: str) -> bool:
    """Does this address plausibly belong to this person?

    The box's email column drifts out of step with its names, so a scraped
    address is only accepted when its local part contains one of the person's
    own name tokens. Measured against the WE 8.9 box:

        businessbivens@gmail.com  + Brian Bivens        -> True  ('bivens')
        timothy54188@gmail.com    + Qilu(Timothy) Zhao  -> True  ('timothy',
                                   which only exists because name_tokens keeps
                                   what's inside the parentheses)
        Ashdiaz670@gmail.com      + Carlo Ferrino       -> False
        chevin321@gmail.com       + Alexa Loredo        -> False

    It is deliberately one-directional: a False never means the address is
    wrong, only that we can't prove it's right, and the cell is left blank.
    """
    if not email or not name:
        return False
    local = re.sub(r"[^a-z]", "", email.split("@", 1)[0].lower())
    return any(len(t) >= MIN_TOKEN and t in local for t in name_tokens(name))


def pretty_phone(raw) -> str:
    """Anything phone-shaped -> '(972) 903-5202', the Mobrium List's own style.

    The board stores an unformatted read as a NUMBER (19729035202), so the
    leading US country code is dropped before formatting. Returns '' for
    anything that isn't a plain 10-digit US number, rather than writing a
    half-formatted string into the sheet.
    """
    digits = "".join(_PHONE_DIGITS.findall(str(raw or "")))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return ""
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def _looks_like_phone(value) -> bool:
    return bool(pretty_phone(value))


def scan_grid(grid: list, tab: str) -> List[NewStart]:
    """The box's rows, in board order."""
    lay = tboard.find_layout(grid)
    out: List[NewStart] = []
    for r in range(lay.box_first_row, len(grid) + 1):
        name = str(tboard._cell(grid, r, lay.box_name_col) or "").strip()
        if not name:
            continue
        email = phone = ""
        for c in range(lay.box_name_col + 1, lay.box_name_col + 1 + BOX_SCAN_COLS):
            cell = tboard._cell(grid, r, c)
            if cell in ("", None) or cell is True or cell is False:
                continue
            text = str(cell).strip()
            if not email:
                m = _EMAIL.search(text)
                if m:
                    email = m.group(0)
                    continue
            # A cell holding an email must not also be read as a phone, hence
            # the continue above. Dates and counts are filtered by pretty_phone
            # insisting on exactly 10 digits.
            if not phone and _looks_like_phone(text):
                phone = pretty_phone(text)
        out.append(NewStart(name=name, email=email, phone=phone, tab=tab, row=r))
    return out


def scan(today: dt.date, *, tab: Optional[str] = None,
         logfn=print) -> tuple[List[NewStart], str]:
    """Read the 'New Starts/Raf' box of the week covering `today`."""
    sh = open_by_key(SHEET_ID)
    title = tboard.pick_tab(sh, today, tab)
    grid = sh.worksheet(title).get_values(value_render_option="UNFORMATTED_VALUE")
    rows = scan_grid(grid, title)
    if not rows:
        raise BoardError(
            f"the 'New Starts/Raf' box on {title!r} is empty — that has never "
            "happened on a real week, so this is far more likely a layout "
            "change than a week with no new starts. Nothing added.")
    logfn(f"  {title!r}: {len(rows)} new start(s) in the box "
          f"({sum(1 for n in rows if n.email)} with an email on the board, "
          f"{sum(1 for n in rows if n.phone)} with a phone)")
    return rows, title
