"""SaraPlus's spelling of a rep -> the spelling their office actually uses.

Megan 2026-09-14: Callista Flythe went out as "Callisa Flythe" and "CALLISA"
because that is the name SaraPlus holds, and **the ICD cannot edit it there**.
We never type a rep's name, so without this there is no spelling of hers we can
correct -- the alerts would keep misspelling a rep in front of her own office.

OURS, NOT THEIRS. It lives in the relay workbook on OUR side and is read by the
poster, so a fix reaches every office's Slack line without anything going out
to fifty-two laptops -- the same reason the wording lives centrally. A laptop
cannot write this tab and does not know it exists.

DISPLAY ONLY, and that is load-bearing. The relay's 'Last Posted' state is
keyed by the SaraPlus name; renaming a rep anywhere upstream would read as a
brand-new rep with a count of zero and re-announce her whole day. So the
substitution happens at the moment a sentence is built and nowhere else --
exactly where the casing happens, for exactly the same reason.

    Rep Name Fixes
      Office | SaraPlus Name   | Show As          | Added By | Note
      kash   | CALLISA FLYTHE  | Callista Flythe  | Megan    | SaraPlus typo

PER OFFICE, because two offices can have two different reps whose SaraPlus
spellings collide, and a global map would rename the wrong woman in the wrong
room. Matching ignores case and outside spacing on both the office and the
name, since a person types these.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

TAB = "Rep Name Fixes"
HEADERS = ["Office", "SaraPlus Name", "Show As", "Added By", "Note"]


def _key(office: str, sara: str) -> Tuple[str, str]:
    return (str(office or "").strip().lower(),
            " ".join(str(sara or "").upper().split()))


def load(book=None) -> Dict[Tuple[str, str], str]:
    """{(office, SARAPLUS NAME): shown name}.

    EMPTY ON ANY FAILURE, including no tab at all. A missing or unreadable
    spelling tab must never cost an office its alerts; the worst case is the
    rep's name goes out the way it has been going out all along.
    """
    if book is None:
        from automations.recruiting_report.fill import open_by_key
        from automations.icd_alerts.post import RELAY_SPREADSHEET_ID
        book = open_by_key(RELAY_SPREADSHEET_ID)
    try:
        rows = book.worksheet(TAB).get_all_values()
    except Exception:  # noqa: BLE001 — no tab yet is not a failure
        return {}

    out: Dict[Tuple[str, str], str] = {}
    for row in rows[1:]:
        if len(row) < 3:
            continue
        office, sara, shown = row[0], row[1], (row[2] or "").strip()
        if not shown or not str(sara or "").strip():
            continue
        # A row with no office is ignored rather than applied everywhere: a
        # half-filled row is the likeliest thing on this tab, and renaming a
        # rep in an office nobody meant is worse than not renaming her.
        if not str(office or "").strip():
            continue
        out[_key(office, sara)] = shown
    return out


def resolver(fixes: Dict[Tuple[str, str], str],
             office: str) -> Optional[Callable[[str], str]]:
    """One office's `name -> name`, or None when it has no fixes.

    None rather than an identity function so the caller can keep its own
    default (which title-cases) instead of being handed a no-op that silently
    replaces it.
    """
    mine = {sara: shown for (o, sara), shown in fixes.items()
            if o == str(office or "").strip().lower()}
    if not mine:
        return None

    def show(name: str) -> str:
        return mine.get(" ".join(str(name or "").upper().split()), name)

    return show


def ensure_tab(book=None) -> str:
    """Create the tab with its headers if it isn't there. Returns its title."""
    if book is None:
        from automations.recruiting_report.fill import open_by_key
        from automations.icd_alerts.post import RELAY_SPREADSHEET_ID
        book = open_by_key(RELAY_SPREADSHEET_ID)
    for ws in book.worksheets():
        if ws.title.strip().lower() == TAB.lower():
            return ws.title
    ws = book.add_worksheet(title=TAB, rows=200, cols=len(HEADERS))
    ws.update("A1:E1", [HEADERS])
    ws.format("A1:E1", {"textFormat": {"bold": True}})
    return ws.title
