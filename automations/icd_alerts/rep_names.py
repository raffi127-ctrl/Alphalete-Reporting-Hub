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


# --- one rep ringing sales under another rep's SaraPlus login, for a day -----
# Carlos 2026-11-19: "jacob is selling under esmeralda today" -- the text said
# Esmeralda had the sale and Jacob's four were "missing". SaraPlus cannot be
# told who really sold, so, like every fix in this file, it is DISPLAY ONLY:
# the relay state stays keyed by the SaraPlus name (nothing is re-announced),
# and the standings, the shout-outs and the team line all say the real seller.
# DATED, so it ends by itself at midnight. The pattern is every word that must
# appear in the SaraPlus name (so "ESMERALDA" matches whatever surnames
# SaraPlus holds for her). The board and payroll are NOT touched by this.
#   {(office key, "YYYY-MM-DD"): {"WORDS IN THE SARAPLUS NAME": "Real Seller"}}
SOLD_UNDER = {
    # Carlos 2026-11-19: "All of Esmeralda's sales this week are Jacob's" --
    # the whole week of WE 11.22, Mon 11/16 .. Sun 11/22.
    **{("carlos-b2batt", "2026-11-%02d" % d): {"ESMERALDA": "Jacob Ortega"}
       for d in range(16, 23)},
}
# STANDING swaps, from a start day with no end (same display-only rule).
# Carlos 2026-11-25: "remember esmeralda is jacob so list as jacob" / "jacob
# is using esmeraldas login" -- every sale under Esmeralda's login is Jacob's.
#   {office key: [("YYYY-MM-DD" first day, "WORDS IN THE SARAPLUS NAME", "Real Seller")]}
SOLD_UNDER_FROM = {
    "carlos-b2batt": [("2026-11-16", "ESMERALDA", "Jacob Ortega")],
}


def _swaps(office: str, iso: str) -> dict:
    """Every swap in force for this office on this day: the dated ones plus
    the standing ones that have started."""
    key = str(office or "").strip().lower()
    out = {}
    for start, pat, real in SOLD_UNDER_FROM.get(key, ()):
        if iso >= start:
            out[pat] = real
    out.update(SOLD_UNDER.get((key, iso)) or {})
    return out


def sold_under_for(office: str, day, name: str) -> str:
    """The real seller when `name` (any spelling) rang under someone else's
    login on `day` for this office, else ''."""
    iso = day.isoformat() if hasattr(day, "isoformat") else str(day)
    swaps = _swaps(office, iso)
    words = set(str(name or "").upper().split())
    for pat, real in swaps.items():
        need = set(str(pat).upper().split())
        if need and need <= words:
            return real
    return ""


def day_resolver(show: Optional[Callable[[str], str]], office: str,
                 day) -> Optional[Callable[[str], str]]:
    """`show` with today's SOLD_UNDER entries for this office laid over it;
    `show` itself (None included) when there are none."""
    iso = day.isoformat() if hasattr(day, "isoformat") else str(day)
    swaps = _swaps(office, iso)
    if not swaps:
        return show
    pats = [(set(str(k).upper().split()), v) for k, v in swaps.items()]

    def shown(name: str) -> str:
        words = set(str(name or "").upper().split())
        for need, real in pats:
            if need and need <= words:
                return real
        return show(name) if show else name
    return shown
