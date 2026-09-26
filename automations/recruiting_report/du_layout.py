"""Daily Update column resolver (Carlos 2026-09-26).

The 'Daily Update' tab is the VA's and its layout drifts: the Vantura master
gained a 'Week Ending' column at M on 2026-09-26 (right of the 2nd-round date),
while the 11 captainship owner boards still carry the classic layout, and the
owners' header wording differs from Carlos's ('2nd rounder' vs '2nd round ',
'job ad / source' vs 'Job Ad'). Every reader/writer of the tab must locate its
columns by HEADER, never by position — the bound script's addNewStartsToRollCall
already does. This is the one place that knows the header vocabulary.

    lay = resolve(header_row)        # {key: 0-based column index}
    row[lay["orient"]]               # instead of row[17]
    col_letter(lay["cr"])            # 'U' on the master, 'T' on an owner board

Keys: status, secondary, campaign, name, email, phone, date2 (2nd-round
interview DATE), first (1st-round interviewer), second (2nd rounder), show,
offered, bob, orient, ad, cr, week_ending (None when the tab has no such
column). Anything the headers do not carry falls back to the CLASSIC position,
so an owner board with a blank header cell still resolves the way it always did.
"""
import re

# The classic (pre-2026-09-26) layout every tab started from, 0-based.
CLASSIC = {
    "status": 0, "secondary": 1, "campaign": 5, "name": 8, "email": 9,
    "phone": 10, "date2": 11, "first": 12, "second": 13, "show": 14,
    "offered": 15, "bob": 16, "orient": 17, "ad": 18, "cr": 19,
}
# Columns nothing appends to; absent => None rather than a classic fallback.
OPTIONAL = {"week_ending"}


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _match(h: str):
    """The key a normalized header belongs to, or None."""
    if not h:
        return None
    if h == "status":
        return "status"
    if h.startswith("secondary status"):
        return "secondary"
    if h == "campaign":
        return "campaign"
    if h == "name":
        return "name"
    if h == "email":
        return "email"
    if h.startswith("phone"):
        return "phone"
    if h == "week ending":
        return "week_ending"
    if h.startswith("2nd round") and "date" in h:
        return "date2"
    if h.startswith("1st round"):
        return "first"
    if "show" in h:                      # '2nd show/no show', '2nd round show / no show'
        return "show"
    if h.startswith("2nd round"):        # '2nd round ', '2nd rounder' (the person)
        return "second"
    if h == "offered":
        return "offered"
    if h.startswith("bob"):
        return "bob"
    if "orientation" in h:
        return "orient"
    if h.startswith("job ad"):
        return "ad"
    if "classroom" in h or "retention" in h:
        return "cr"
    return None


def resolve(header_row) -> dict:
    """Map every layout key to its 0-based column on this tab."""
    lay = dict(CLASSIC)
    lay.update({k: None for k in OPTIONAL})
    found = set()
    for i, cell in enumerate(header_row or []):
        key = _match(_norm(cell))
        if key and key not in found:     # first header wins
            lay[key] = i
            found.add(key)
    return lay


def col_letter(idx: int) -> str:
    """0-based column index -> A1 letters."""
    s, n = "", idx + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s
