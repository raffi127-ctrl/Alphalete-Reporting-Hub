"""Pure logic for the Captainship Penetration box (no network; test_core).

Source: Tableau ATT Tracker 2.1 - D2D -> Fiber Lead Performance -> crosstab
'Office New Fiber Lead Penetration By Zip' (Penetration Type = Office Level,
the view's default). One row per zip; per-OWNER columns repeat on every row:

  Account_Owner_Name__c                 owner (Tableau spelling)
  Account Captain Email                 the owner's captain (SmartCircle 11/26)
  ICD Workable Fiber Lead Count (copy)  owner's workable leads
  Fiber Sales (Fixed) (copy)            owner's fiber sales since assignment
  Office Lead Penetration (Fixed)       owner's penetration, 1 decimal

The number is ONGOING (cumulative since the zips were assigned) and Tableau
recalculates it every day — so each day's column is that day's snapshot of the
running rate, exactly like the churn / activation boxes.

Penetration = sales / workable leads, computed here to 2 decimals (Tableau
prints 1). Captainship Avg = the WEIGHTED rate of the owners shown: sum of
sales / sum of leads. The captain's own office is left out (Raf's Loom 11/26:
captains get more leads - road trips, big cities - and look off next to the
rest).
"""
from __future__ import annotations

import csv
import io
import re
from typing import Dict, List, Optional

T_OWNER = "Account_Owner_Name__c"
T_CAPTAIN = "Account Captain Email"
T_LEADS = "ICD Workable Fiber Lead Count (copy)"
T_SALES = "Fiber Sales (Fixed) (copy)"
T_PCT = "Office Lead Penetration (Fixed)"

MIN_OWNERS = 20       # fewer in the crosstab = a stuck Tableau filter

# captain key -> the captain's OWN office as Tableau spells it (left out).
CAPTAIN_OWNER = {
    "rafael": "Rafael Hidalgo", "wayne": "Wayne Rude",
    "starr": "Starr Rodenhurst", "chan": "Chan Park", "tony": "Tony Chavez",
    "sahil": "Sahil Multani", "pat": "Pat Thompson", "jess": "Jess Lieberman",
}
# captain key -> Account Captain Email, pinned once seen. Empty = detect.
CAPTAIN_EMAIL: Dict[str, str] = {}


def decode(raw: bytes) -> str:
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except Exception:  # noqa: BLE001
            continue
    return raw.decode("latin-1", "replace")


def _int(s: str) -> Optional[int]:
    s = (s or "").replace(",", "").strip()
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_owners(text: str) -> Dict[str, dict]:
    """{owner: {"email", "leads", "sales", "tableau_pct"}} — one per owner."""
    first = text.splitlines()[0] if text else ""
    delim = "\t" if first.count("\t") >= first.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not rows:
        raise ValueError("empty crosstab")
    head = [(h or "").strip().lower() for h in rows[0]]

    def col(name):
        try:
            return head.index(name.lower())
        except ValueError:
            raise KeyError(f"crosstab has no {name!r} column: {rows[0]}") from None

    i_o, i_c, i_l, i_s, i_p = (col(T_OWNER), col(T_CAPTAIN), col(T_LEADS),
                               col(T_SALES), col(T_PCT))
    out: Dict[str, dict] = {}
    for r in rows[1:]:
        if len(r) <= max(i_o, i_c, i_l, i_s, i_p):
            continue
        owner = r[i_o].strip()
        if not owner or owner.lower() in ("total", "grand total") or owner in out:
            continue
        out[owner] = {"email": r[i_c].strip(), "leads": _int(r[i_l]),
                      "sales": _int(r[i_s]), "tableau_pct": r[i_p].strip()}
    return out


def groups(owners: Dict[str, dict]) -> Dict[str, List[str]]:
    """{captain email -> sorted owners}; case variants fold together."""
    spelled: Dict[str, str] = {}
    out: Dict[str, set] = {}
    for o, d in owners.items():
        e = d["email"]
        if "@" not in e:
            continue
        e = spelled.setdefault(e.lower(), e)
        out.setdefault(e, set()).add(o)
    return {e: sorted(v) for e, v in out.items()}


def captain_email(key: str, grp: Dict[str, List[str]]) -> str:
    """Pinned CAPTAIN_EMAIL wins; else the one address whose local part names
    the captain; else the one group the captain's own office sits in (Raf's
    address is a nickname). Ambiguous / none -> raise, never a guess."""
    if key in CAPTAIN_EMAIL:
        want = CAPTAIN_EMAIL[key].lower()
        for e in grp:
            if e.lower() == want:
                return e
        raise ValueError(f"{key}: pinned {CAPTAIN_EMAIL[key]} not in the crosstab")
    full = CAPTAIN_OWNER[key].lower().split()
    first, last = full[0], full[-1]
    local = {e: re.sub(r"[^a-z]", "", e.split("@")[0].lower()) for e in grp}
    for test in (lambda l: first in l and last in l, lambda l: first in l,
                 lambda l: l.startswith(first[0]) and last in l,
                 lambda l: last in l):
        hits = [e for e, l in local.items() if test(l)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ValueError(f"{key}: several captain emails match: {hits}")
    own = CAPTAIN_OWNER[key].lower()
    hits = [e for e, os_ in grp.items() if own in {o.lower() for o in os_}]
    if len(hits) == 1:
        return hits[0]
    raise ValueError(f"{key}: no Account Captain Email matches "
                     f"{CAPTAIN_OWNER[key]!r} (emails: {sorted(grp)})")


def pct(sales: Optional[int], leads: Optional[int]) -> str:
    """'2.28%', or '' when there are no leads to divide by."""
    if sales is None or not leads:
        return ""
    return f"{sales / leads * 100:.2f}%"


def captainship(key: str, owners: Dict[str, dict]) -> dict:
    """{"email", "owners": {name: 'x.xx%'}, "avg": 'x.xx%'} for one captain,
    the captain's own office left out."""
    grp = groups(owners)
    email = captain_email(key, grp)
    own = CAPTAIN_OWNER[key].lower()
    shown = [o for o in grp[email] if o.lower() != own]
    vals = {o: pct(owners[o]["sales"], owners[o]["leads"]) for o in shown}
    s = sum(owners[o]["sales"] or 0 for o in shown if owners[o]["leads"])
    l = sum(owners[o]["leads"] or 0 for o in shown)
    return {"email": email, "owners": vals, "avg": pct(s, l)}
