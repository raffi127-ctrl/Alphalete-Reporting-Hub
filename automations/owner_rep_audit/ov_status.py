"""READ-ONLY: where a list of Slack people stands in OwnerVille.

Eve 2026-11-03: the people in recruiting channels the audit can't see, are they
still active, terminated, reps or admins? Reads the four Sales Reps rosters
(active / lead / admin / inactive) in every office we have access to, matches
review_people.json by email and then by exact name, and prints one tab-separated
OVSTATUS line per person. It changes nothing in OwnerVille or Slack.

A person NOT found is not evidence they were never there: their office may be
one we can't read, or their name may be spelled differently (OVOFFICE lines say
which offices were read).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List

PEOPLE_FILE = Path(__file__).with_name("review_people.json")


def _rows(page, rqst: str, office: str) -> List[dict]:
    from automations.mobrium_list import ownerville as OV
    out: List[dict] = []
    for roster, rep_type in list(OV.ROSTERS.items()) + [("inactive", OV.INACTIVE)]:
        start = 0
        while True:
            data = OV._post(page, rqst, rep_type, start, OV.PAGE_SIZE)
            chunk = data.get("data") or []
            total = int(data.get("recordsTotal") or 0)
            for d in chunk:
                out.append({
                    "office": office, "roster": roster,
                    "name": f"{OV._clean(d.get('fname'))} {OV._clean(d.get('lname'))}".strip(),
                    "email": OV._clean(d.get("email")).lower(),
                    "access": OV._clean(d.get("moduleAccess")),
                    "start": OV._clean(d.get("fechabob")),
                    "retired": OV._clean(d.get("retireddate")),
                    "status": OV._clean(d.get("status"))})
            start += len(chunk)
            if not chunk or start >= total:
                if start < total:
                    raise OV.OwnervilleError(f"only {start} of {total} {rep_type}")
                break
    return out


def match(person: Dict, records: Iterable[dict]) -> List[dict]:
    """Every OwnerVille row for this person. A real email wins over the name;
    the name only counts when the email found nothing."""
    from automations.mobrium_list.ownerville import norm_name
    records = list(records)
    email = (person.get("email") or "").strip().lower()
    hits = [r for r in records if email and r["email"] == email]
    if hits:
        return [dict(r, how="email") for r in hits]
    name = norm_name(person.get("name"))
    if len(name.split()) < 2:     # "Agustina" alone would match strangers
        return []
    return [dict(r, how="name") for r in records if norm_name(r["name"]) == name]


def verdict(hits: List[dict]) -> str:
    """One word for a person's rows: any working row beats an old retired one."""
    rosters = {h["roster"] for h in hits}
    if not hits:
        return "not found"
    for roster in ("admin", "lead", "active"):
        if roster in rosters:
            return roster
    return "terminated"


def line(person: Dict, hits: List[dict]) -> str:
    shown = [h for h in hits if h["roster"] != "inactive"] or hits
    where = "; ".join(sorted({f"{h['office']}/{h['roster']}" for h in shown}))
    first = shown[0] if shown else {}
    return "\t".join(["OVSTATUS", person.get("slack_id", ""), person.get("name", ""),
                      verdict(hits), first.get("how", ""), where,
                      first.get("access", ""), first.get("start", ""),
                      first.get("retired", ""), first.get("status", ""),
                      str(len(hits))])


def add_emails(people: List[Dict], cli=None) -> int:
    """Look each email up in Slack at run time. On purpose they are never saved
    in the repo or printed. A failed lookup leaves the name to match on."""
    from automations.ao_cleanup.slack_read import client
    cli = cli or client()
    found = 0
    for p in people:
        try:
            u = cli.users_info(user=p["slack_id"])["user"]
            p["email"] = ((u.get("profile") or {}).get("email") or "").lower()
        except Exception:  # noqa: BLE001
            p["email"] = ""
        found += bool(p["email"])
    return found


def main() -> int:
    from automations.focus_office_att import run_all_owners as R
    from automations.knocks_access_watch import audit as A
    from automations.owner_rep_audit.roster import PROFILE_DIR, _impersonate, granted
    from automations.shared.tableau_patchright import ownerville_session

    people = json.loads(PEOPLE_FILE.read_text(encoding="utf-8"))
    print(f"OVEMAILS\t{add_emails(people)} of {len(people)} found in Slack", flush=True)
    records: List[dict] = []
    with ownerville_session(verbose=True, profile_dir=PROFILE_DIR) as page:
        table = A.read_office_access(page)
        own = R.page_rqst(page)
        if own:
            try:
                got = _rows(page, own, "own login")
                records += got
                print(f"OVOFFICE\town login\tread\t{len(got)}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"OVOFFICE\town login\terror\t{type(e).__name__}", flush=True)
        for r in table:
            office, _company, owner = (r + ["", "", ""])[:3]
            label = f"{office.strip()} {owner.strip()}"
            if not granted(r[-1]):
                print(f"OVOFFICE\t{label}\tno access\t0", flush=True)
                continue
            try:
                if not R._navigate_to_office_access(page):
                    raise RuntimeError("couldn't reach Office Access")
                rqst = _impersonate(page, office.strip())
                if not rqst:
                    raise RuntimeError("impersonation didn't take")
                got = _rows(page, rqst, label)
                records += got
                print(f"OVOFFICE\t{label}\tread\t{len(got)}", flush=True)
            except Exception as e:  # noqa: BLE001 -- one office never kills the rest
                print(f"OVOFFICE\t{label}\terror\t{type(e).__name__}: {str(e)[:120]}", flush=True)
            finally:
                R._exit_impersonation(page)
    for p in people:
        print(line(p, match(p, records)), flush=True)
    print(f"OVDONE\t{len(people)} people\t{len(records)} rows read", flush=True)
    return 0
