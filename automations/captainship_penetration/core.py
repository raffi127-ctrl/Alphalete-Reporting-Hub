"""Pure logic for the Captainship Penetration box (no network; test_core).

Source: Tableau ATT Tracker 2.1 - D2D -> Fiber Lead Performance -> crosstab
'Office New Fiber Lead Penetration By Zip' (Penetration Type = Office Level,
the view's default). One row per zip; per-OWNER columns repeat on every row:

  Account_Owner_Name__c                 owner (Tableau spelling)
  Account Captain Email                 the owner's captain (SmartCircle 11/26)
  Office Lead Penetration (Fixed)       owner's penetration, 1 decimal (USED AS IS)
  Total Sales / Lead Count              per ZIP row (summed for the avg)

The number is ONGOING (cumulative since the zips were assigned) and Tableau
recalculates it every day — so each day's column is that day's snapshot of the
running rate, exactly like the churn / activation boxes.

Owner % = Tableau's own number. Captainship Avg = sum of the owners' zip
sales / sum of their zip leads (2 decimals) — the weighted rate, the way
Tableau's Program Overview totals it. The captain's own office is left out (Raf's Loom 11/26:
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
T_PCT = "Office Lead Penetration (Fixed)"
T_ZIP_SALES = "Total Sales"           # per zip row
T_ZIP_LEADS = "Lead Count"            # per zip row

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
    """{owner: {"email", "pct", "zip_sales", "zip_leads"}} — one per owner.

    pct = Tableau's own 'Office Lead Penetration (Fixed)' for the owner, as
    Tableau prints it (1 decimal) — the number Raf and the captains see. Our
    first fill (11/26) divided the '(copy)' sales/leads columns instead and
    got 30 owners wrong (Kash Rai 11600%, Jarred Hill 0.16% vs Tableau 0.3%):
    those columns are not the inputs of Tableau's %. zip_sales / zip_leads are
    the owner's summed 'Total Sales' / 'Lead Count' over his zip rows — what
    Tableau's own Program Overview adds up — and feed the Captainship Avg."""
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

    i_o, i_c, i_p, i_zs, i_zl = (col(T_OWNER), col(T_CAPTAIN), col(T_PCT),
                                 col(T_ZIP_SALES), col(T_ZIP_LEADS))
    out: Dict[str, dict] = {}
    for r in rows[1:]:
        if len(r) <= max(i_o, i_c, i_p, i_zs, i_zl):
            continue
        owner = r[i_o].strip()
        if not owner or owner.lower() in ("total", "grand total"):
            continue
        d = out.get(owner)
        if d is None:
            v = _pct_num(r[i_p])
            d = out[owner] = {"email": r[i_c].strip(),
                              "pct": "" if v is None else f"{v:.1f}%",
                              "zip_sales": 0, "zip_leads": 0}
        d["zip_sales"] += _int(r[i_zs]) or 0
        d["zip_leads"] += _int(r[i_zl]) or 0
    return out


def _pct_num(s: str) -> Optional[float]:
    s = (s or "").replace(",", "").strip().rstrip("%").strip()
    try:
        return float(s)
    except ValueError:
        return None


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
    vals = {o: owners[o]["pct"] for o in shown}
    s_ = sum(owners[o]["zip_sales"] for o in shown)
    l_ = sum(owners[o]["zip_leads"] for o in shown)
    return {"email": email, "owners": vals, "avg": pct(s_, l_)}
