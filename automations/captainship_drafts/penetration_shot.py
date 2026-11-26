"""Penetration Report section of the fiber Captainship drafts (Raf's Loom, 11/26).

Raf asked (Loom "Penetration Rate per Fiber Owner"): once Tableau can split by
captain, add a section "Penetration Report" to the FIBER captainship emails
with a screenshot of Fiber Lead Performance → Penetration View "Market
Expectations" (one row per owner: active reps, target weekly sales, penetration,
weekly sales heat-map) — filtered to the captain's owners and WITHOUT the
captain's own office. Why without: captains get more leads (road trips, big
cities, lots unworkable), so their row looks off next to everybody else's.

SmartCircle (Gauraang Singhal, 2026-11-26) added "Account Captain Email" as a
filter + a column of the by-zip crosstab. How the shot is filtered:

  1. ONE crosstab per day (the by-zip sheet, the same pull fiber_zip_penetration
     makes) gives every owner with their Account Captain Email, spelled the way
     Tableau spells them. Cached in the render dir, so 8 captains = 1 download.
  2. The captain's group = the email whose local part names the captain
     (CAPTAIN_EMAIL pins it once known). Owners = that group minus the captain.
  3. The view is opened with URL params: Penetration View = Market
     Expectations, Account Captain Email = <email>, Owner Name = <owners>.
     Owner Name has to be set explicitly anyway: the base view opens on a saved
     "(Multiple values)" owner pick, which would silently drop owners.
  4. Before shooting, the filter boxes are read back: if the Account Captain
     Email box doesn't show the email, the params did not bind → RAISE (the
     section shows a pending note, never the unfiltered national board).

    python -m automations.captainship_drafts.penetration_shot rafael [out_dir]
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

BASE_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
             "ATTTRACKER2_1-D2D/FiberLeadPerformance")
CROSSTAB_SHEET = "Office New Fiber Lead Penetration By Zip"

# Tableau names (crosstab header / URL params). Matched by NAME, never index.
T_OWNER = "Account_Owner_Name__c"
T_CAPTAIN = "Account Captain Email"
P_VIEW = "Penetration View"
P_VIEW_VALUE = "Market Expectations"
P_OWNER = "Owner Name"

# captain key -> the captain's OWN office as Tableau spells it (left out of the
# shot). Checked against the 11/23 crosstab.
CAPTAIN_OWNER = {
    "rafael": "Rafael Hidalgo", "wayne": "Wayne Rude",
    "starr": "Starr Rodenhurst", "chan": "Chan Park", "tony": "Tony Chavez",
    "sahil": "Sahil Multani", "pat": "Pat Thompson", "jess": "Jess Lieberman",
}
# captain key -> exact Account Captain Email value, once seen in the data.
# Empty = auto-detect (see captain_email). Pin it here when confirmed.
CAPTAIN_EMAIL: Dict[str, str] = {}

MIN_OWNERS = 20       # fewer in the crosstab = a stuck Tableau filter


def _decode(raw: bytes) -> str:
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except Exception:  # noqa: BLE001
            continue
    return raw.decode("latin-1", "replace")


def owners_by_email(text: str) -> Dict[str, List[str]]:
    """{captain email (lower) -> sorted owner names} from the by-zip crosstab.
    Grand-total rows and blank emails are skipped."""
    first = text.splitlines()[0] if text else ""
    delim = "\t" if first.count("\t") >= first.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not rows:
        raise ValueError("empty crosstab")
    head = [(h or "").strip().lower() for h in rows[0]]
    try:
        i_o, i_c = head.index(T_OWNER.lower()), head.index(T_CAPTAIN.lower())
    except ValueError:
        raise KeyError(f"crosstab has no {T_OWNER!r} / {T_CAPTAIN!r} column: "
                       f"{rows[0]}") from None
    out: Dict[str, set] = {}
    for r in rows[1:]:
        if len(r) <= max(i_o, i_c):
            continue
        owner, email = r[i_o].strip(), r[i_c].strip().lower()
        if not owner or owner.lower() in ("total", "grand total") or "@" not in email:
            continue
        out.setdefault(email, set()).add(owner)
    return {e: sorted(o) for e, o in out.items()}


def all_owners(text: str) -> int:
    return len({o for g in owners_by_email(text).values() for o in g})


def captain_email(key: str, groups: Dict[str, List[str]]) -> str:
    """The Account Captain Email value for this captain. Pinned in
    CAPTAIN_EMAIL wins; else the ONE email whose local part matches the
    captain's name (first+last, first, initial+last, last — first unique hit),
    else the one group the captain's own office is in.
    Ambiguous or missing -> raise, never a guess."""
    if key in CAPTAIN_EMAIL:
        return CAPTAIN_EMAIL[key].lower()
    full = CAPTAIN_OWNER[key].lower().split()
    first, last = full[0], full[-1]
    local = {e: re.sub(r"[^a-z]", "", e.split("@")[0]) for e in groups}
    for test in (lambda l: first in l and last in l,
                 lambda l: first in l,
                 lambda l: l.startswith(first[0]) and last in l,
                 lambda l: last in l):
        hits = [e for e, l in local.items() if test(l)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ValueError(f"{key}: several captain emails match: {hits}")
    # No name in the address (Raf's is a nickname, 11/26 sample): the group his
    # OWN office sits in. One captain per owner, so this is unique or nothing.
    own = CAPTAIN_OWNER[key].lower()
    hits = [e for e, owners in groups.items()
            if own in {o.lower() for o in owners}]
    if len(hits) == 1:
        return hits[0]
    raise ValueError(f"{key}: no Account Captain Email matches "
                     f"{CAPTAIN_OWNER[key]!r} (emails: {sorted(groups)})")


def team_owners(key: str, groups: Dict[str, List[str]]) -> tuple:
    """(email, owners minus the captain's own office)."""
    email = captain_email(key, groups)
    own = CAPTAIN_OWNER[key].lower()
    return email, [o for o in groups[email] if o.lower() != own]


def view_url(email: str, owners: List[str]) -> str:
    names = ",".join(quote(o) for o in owners)
    return (f"{BASE_VIEW}?{quote(P_VIEW)}={quote(P_VIEW_VALUE)}"
            f"&{quote(T_CAPTAIN)}={quote(email)}"
            f"&{quote(P_OWNER)}={names}&:iid=1")


def _crosstab_text(render_dir: Path, today: dt.date, page) -> str:
    """Today's by-zip crosstab, downloaded once per day per machine."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    cache = Path(render_dir) / f"penetration_crosstab_{today.isoformat()}.csv"
    if cache.exists():
        text = _decode(cache.read_bytes())
        if all_owners(text) >= MIN_OWNERS:
            return text
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".part.csv")
    download_crosstab_patchright(f"{BASE_VIEW}?:iid=1", CROSSTAB_SHEET, tmp,
                                 verbose=False, page=page)
    text = _decode(tmp.read_bytes())
    n = all_owners(text)
    if n < MIN_OWNERS:
        raise RuntimeError(f"crosstab came back with {n} owner(s) "
                           f"(expected ~60) — a Tableau filter is stuck")
    tmp.replace(cache)
    return text


def _filter_texts(page) -> Dict[str, str]:
    """{filter title: shown value} for every categorical filter box."""
    from automations.captainship_drafts.tableau_shot import (
        _FILTER_BOX, _FILTER_CHROME, _VIZ_IFRAME)
    fr = page.frame_locator(_VIZ_IFRAME)
    boxes = fr.locator(_FILTER_BOX)
    out = {}
    for i in range(boxes.count()):
        lines = [ln.strip() for ln in (boxes.nth(i).inner_text() or "").splitlines()
                 if ln.strip() and ln.strip() not in _FILTER_CHROME]
        if len(lines) >= 2:
            out[lines[0]] = lines[-1]
    return out


def captain_penetration_shot(captain_key: str, today: dt.date, out_dir: Path,
                             *, logfn=print, verbose: bool = False) -> Path:
    """PNG of the Market Expectations board for this captain's owners. Raises on
    anything off (run.py turns it into the section's pending note)."""
    if captain_key not in CAPTAIN_OWNER:
        raise ValueError(f"{captain_key}: no Tableau owner name in CAPTAIN_OWNER")
    from automations.shared.tableau_patchright import tableau_session
    from automations.captainship_drafts import tableau_shot as ts
    out_dir = Path(out_dir)
    with tableau_session(headless=True, verbose=verbose) as page:
        groups = owners_by_email(_crosstab_text(out_dir, today, page))
        email, owners = team_owners(captain_key, groups)
        if not owners:
            raise RuntimeError(f"{captain_key}: {email} has no owners besides "
                               f"the captain")
        logfn(f"   · penetration {captain_key}: {email} → {len(owners)} owners "
              f"(minus {CAPTAIN_OWNER[captain_key]}): {', '.join(owners)}")
        spec = {"id": f"captainship_{captain_key}_penetration",
                "title": f"captainship_{captain_key}_penetration",
                "url": view_url(email, owners)}
        png = ts._shoot_rendered(page, spec, out_dir, verbose=verbose)
        shown = _filter_texts(page)
        logfn(f"   · penetration {captain_key}: filters {shown}")
        cap_box = next((v for k, v in shown.items()
                        if k.lower() == T_CAPTAIN.lower()), None)
        if cap_box is None or cap_box.lower() != email:
            png.unlink(missing_ok=True)
            raise RuntimeError(f"the {T_CAPTAIN} filter shows {cap_box!r}, not "
                               f"{email} — the URL filter did not bind")
    return png


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    key = sys.argv[1]
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("output")
    p = captain_penetration_shot(key, dt.date.today(), out, verbose=True)
    print(f"✓ {key}: {p}")
