"""Sync current Vantura reps into alphaletegp@gmail.com's Google Contacts
'Vantura Reps' group, with their campaign in parentheses after the name
(Carlos 2026-09-05).

Who: every person whose Daily Update (Vantura Master Sales Board) Status is
"Active" or "Orientation Scheduled" — the same two statuses vantura_du_status
treats as live. Orientation-Scheduled people usually aren't on the Roll Call
yet, so they are included from the Daily Update alone.

Name: "<Daily Update Name> (<CAMPAIGN>)". The campaign is read from the Roll
Call (the authoritative current-campaign source Carlos pointed at), matched by
name through the master's Name Aliases both ways, newest week wins. When a
person isn't on the Roll Call yet (typically Orientation Scheduled), the Daily
Update's own Campaign column is the fallback. Campaigns are canonicalized to
the Roll Call vocabulary — B2B / BOX / BASE / JE — so "B2B ATT" and "Box"
don't produce a second spelling.

Matching an existing contact: by phone (last 10 digits) first, then by
normalized base name (its own parenthetical stripped). An existing contact is
only ever RENAMED to append/fix the parenthetical — its base name is kept, so
this never overwrites a hand-curated fuller name. New people are created with
name + phone + email and added to the group.

DRY-RUN by default; --write applies. Read + write Contacts scope comes from
the alphaletegp token authorized on the mini and pushed to Lucy 2
(contacts-rw-token-alphaletegp).

  python -m automations.vantura_contacts_sync.run            # dry preview
  python -m automations.vantura_contacts_sync.run --write    # apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import unicodedata
from typing import Dict, List, Optional, Tuple

from automations.fiber_owners_distro import contacts_write as cw

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"   # Vantura Master
ACCOUNT = "alphaletegp@gmail.com"
GROUP = "Vantura Reps"
ADD_STATUSES = {"active", "orientation scheduled"}

DU_TAB, ROLL_TAB, ALIAS_TAB = "Daily Update", "Roll Call", "Name Aliases"
# Daily Update columns (0-based): Status A, Campaign F, Name I, Email J, Phone K,
# "2nd round" (the interviewer who ran it) N, Orientation Date R.
DU_STATUS, DU_CAMP, DU_NAME, DU_EMAIL, DU_PHONE = 0, 5, 8, 9, 10
DU_2ND, DU_ORIENT = 13, 17

# Managed block written into the contact's Notes (biographies). Anything a human
# typed ABOVE this marker is preserved; the block below is regenerated each run,
# so the sync stays idempotent and never duplicates or clobbers manual notes.
NOTE_MARKER = "— Vantura sync —"
# Roll Call columns: Week Ending A, Status B, Campaign C, Roll Call (name) D.
R_WEEK, R_STATUS, R_CAMP, R_NAME = 0, 1, 2, 3


def _log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}",
          flush=True)


def _norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _strip_parens(s: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", str(s or "")).strip()


def _phone10(s) -> str:
    d = re.sub(r"\D", "", str(s or ""))
    return d[-10:] if len(d) >= 10 else ""


def _canon_campaign(raw: str) -> str:
    """Fold every spelling onto the Roll Call vocabulary: B2B / BOX / BASE / JE.
    Unknown values pass through upper-cased rather than being dropped."""
    u = str(raw or "").strip().upper()
    if not u:
        return ""
    if "B2B" in u:
        return "B2B"
    if "BOX" in u:
        return "BOX"
    if "BASE" in u:
        return "BASE"
    if u == "JE" or "JE " in u or u.endswith(" JE"):
        return "JE"
    return u


def _we_date(we) -> dt.date:
    """'m.d' week label -> date, nearest-year rule (matches vantura_du_status)."""
    p = str(we or "").split(".")
    if len(p) != 2:
        return dt.date.min
    try:
        mo, da = int(p[0]), int(p[1])
    except ValueError:
        return dt.date.min
    now = dt.date.today()
    best = None
    for y in (now.year - 1, now.year, now.year + 1):
        try:
            d = dt.date(y, mo, da)
        except ValueError:
            continue
        if (d - now).days <= 31 and (
                best is None or abs((d - now).days) < abs((best - now).days)):
            best = d
    return best or dt.date.min


def load_aliases(sh) -> Dict[str, set]:
    """Normalized name -> set of alias names, both directions."""
    aliases: Dict[str, set] = {}
    try:
        rows = sh.worksheet(ALIAS_TAB).get_all_values()
    except Exception:  # noqa: BLE001 — no alias tab is not fatal
        return aliases
    for r in rows[1:]:
        cells = [_norm(c) for c in r if str(c).strip()]
        for a in cells:
            for b in cells:
                if a != b:
                    aliases.setdefault(a, set()).add(b)
    return aliases


def rollcall_campaign(roll_vals, aliases) -> Dict[str, Tuple[dt.date, str]]:
    """Normalized name -> (newest week, canonical campaign) from the Roll Call."""
    out: Dict[str, Tuple[dt.date, str]] = {}
    for r in roll_vals[2:]:
        if len(r) <= R_NAME:
            continue
        nm = _norm(r[R_NAME])
        if not nm:
            continue
        wed = _we_date(r[R_WEEK])
        camp = _canon_campaign(r[R_CAMP] if len(r) > R_CAMP else "")
        for key in {nm} | aliases.get(nm, set()):
            cur = out.get(key)
            if cur is None or wed > cur[0]:
                out[key] = (wed, camp)
    return out


def build_targets(sh) -> List[dict]:
    """The people to ensure in the group: name, campaign, phone, email."""
    du = sh.worksheet(DU_TAB).get_all_values()
    roll = sh.worksheet(ROLL_TAB).get_all_values()
    aliases = load_aliases(sh)
    rc = rollcall_campaign(roll, aliases)

    targets: List[dict] = []
    seen_phone: set = set()
    for r in du[2:]:
        if len(r) <= DU_PHONE:
            continue
        if _norm(r[DU_STATUS]) not in ADD_STATUSES:
            continue
        name = _strip_parens(r[DU_NAME])
        if not name:
            continue
        nkey = _norm(name)
        hit = rc.get(nkey)
        if hit is None:
            for al in aliases.get(nkey, set()):
                if al in rc:
                    hit = rc[al]
                    break
        campaign = (hit[1] if hit else "") or _canon_campaign(r[DU_CAMP])
        phone = _phone10(r[DU_PHONE])
        if phone and phone in seen_phone:
            continue                      # one Daily Update row per rep already
        if phone:
            seen_phone.add(phone)
        targets.append({
            "name": name,
            "campaign": campaign,
            "phone": phone,
            "email": str(r[DU_EMAIL]).strip(),
            "status": str(r[DU_STATUS]).strip(),
            "orientation": str(r[DU_ORIENT]).strip() if len(r) > DU_ORIENT else "",
            "second_round": str(r[DU_2ND]).strip() if len(r) > DU_2ND else "",
        })
    return targets


def build_notes(t: dict) -> str:
    """The managed Notes block for a rep — only lines whose value is present."""
    lines = []
    if t.get("orientation"):
        lines.append(f"Orientation scheduled: {t['orientation']}")
    if t.get("second_round"):
        lines.append(f"Second round conducted by: {t['second_round']}")
    return "\n".join(lines)


def merge_notes(existing: str, generated: str) -> str:
    """Keep any human text above NOTE_MARKER; replace the managed block below it."""
    base = str(existing or "")
    idx = base.find(NOTE_MARKER)
    if idx != -1:
        base = base[:idx].rstrip()
    if not generated:
        return base.strip()
    block = f"{NOTE_MARKER}\n{generated}"
    return f"{base}\n\n{block}".strip() if base.strip() else block


def load_group_members(svc, grp) -> List[dict]:
    """Members with resourceName, etag, displayName, phones(last10)."""
    full = svc.contactGroups().get(
        resourceName=grp["resourceName"], maxMembers=1000).execute()
    rns = full.get("memberResourceNames", []) or []
    out: List[dict] = []
    for i in range(0, len(rns), 200):
        batch = cw._retry(lambda c=rns[i:i + 200]: svc.people().getBatchGet(
            resourceNames=c,
            personFields="names,phoneNumbers,biographies").execute())
        for r in batch.get("responses", []) or []:
            p = r.get("person", {})
            out.append({
                "resourceName": p.get("resourceName"),
                "etag": p.get("etag"),
                "display": (p.get("names") or [{}])[0].get("displayName", ""),
                "phones": {_phone10(ph.get("value"))
                           for ph in (p.get("phoneNumbers") or [])
                           if _phone10(ph.get("value"))},
                "bio": (p.get("biographies") or [{}])[0].get("value", ""),
            })
    return out


def plan(targets: List[dict], members: List[dict]) -> Tuple[list, list, list]:
    """-> (to_create, to_rename, already_ok). to_create: target dicts.
    to_rename: (member, new_display). already_ok: display strings.

    Member-centric so DUPLICATE contacts of the same rep all get tagged: every
    group member that matches a current target (by phone or base name) is
    evaluated on its own. A target with no matching member at all is created."""
    tgt_by_phone = {t["phone"]: t for t in targets if t["phone"]}
    tgt_by_base = {_norm(t["name"]): t for t in targets}

    create, update, ok = [], [], []
    matched_keys = set()      # phones + base-names of targets that found a member
    for m in members:
        t = None
        for ph in m["phones"]:
            if ph in tgt_by_phone:
                t = tgt_by_phone[ph]
                break
        if t is None:
            t = tgt_by_base.get(_norm(_strip_parens(m["display"])))
        if t is None:
            continue          # member isn't a current-active rep — leave alone
        if t["phone"]:
            matched_keys.add(("p", t["phone"]))
        matched_keys.add(("n", _norm(t["name"])))
        # keep this contact's own base name; only fix the parenthetical
        kept_base = _strip_parens(m["display"]) or t["name"]
        new_display = f"{kept_base} ({t['campaign']})" if t["campaign"] else kept_base
        new_notes = merge_notes(m.get("bio", ""), build_notes(t))
        name_changed = _norm(m["display"]) != _norm(new_display)
        notes_changed = (m.get("bio", "") or "").strip() != new_notes.strip()
        if name_changed or notes_changed:
            update.append((m, new_display, new_notes))
        else:
            ok.append(new_display)

    for t in targets:
        keyed = ("p", t["phone"]) in matched_keys or ("n", _norm(t["name"])) in matched_keys
        if not keyed:
            create.append(t)
    return create, update, ok


def apply(svc, grp, create: List[dict], update: list) -> None:
    # create contacts (name + phone + email + notes), 200/batch, then add to group
    new_rns: List[str] = []
    for i in range(0, len(create), 200):
        chunk = create[i:i + 200]
        contacts = []
        for t in chunk:
            disp = f"{t['name']} ({t['campaign']})" if t["campaign"] else t["name"]
            person = {"names": [{"unstructuredName": disp, "givenName": disp}]}
            if t["phone"]:
                person["phoneNumbers"] = [{"value": t["phone"]}]
            if t["email"]:
                person["emailAddresses"] = [{"value": t["email"]}]
            notes = merge_notes("", build_notes(t))
            if notes:
                person["biographies"] = [{"value": notes,
                                          "contentType": "TEXT_PLAIN"}]
            contacts.append({"contactPerson": person})
        body = {"contacts": contacts, "readMask": "names"}
        resp = cw._retry(lambda b=body: svc.people()
                         .batchCreateContacts(body=b).execute())
        for r in resp.get("createdPeople", []) or []:
            rn = (r.get("person") or {}).get("resourceName")
            if rn:
                new_rns.append(rn)
    for i in range(0, len(new_rns), 500):
        cw._retry(lambda c=new_rns[i:i + 500]: svc.contactGroups().members()
                  .modify(resourceName=grp["resourceName"],
                          body={"resourceNamesToAdd": c}).execute())

    # update existing: name parenthetical and/or Notes block, one call each
    for m, new_display, new_notes in update:
        body = {"etag": m["etag"],
                "names": [{"unstructuredName": new_display, "givenName": new_display}],
                "biographies": [{"value": new_notes, "contentType": "TEXT_PLAIN"}]}
        cw._retry(lambda mm=m, b=body: svc.people().updateContact(
            resourceName=mm["resourceName"],
            updatePersonFields="names,biographies", body=b).execute())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true", help="apply (default: dry run)")
    a = ap.parse_args(argv)

    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(SHEET_ID)
    targets = build_targets(sh)
    _log(f"{len(targets)} Active/Orientation-Scheduled rep(s) on the Daily Update")

    no_phone = [t["name"] for t in targets if not t["phone"]]
    no_camp = [t["name"] for t in targets if not t["campaign"]]
    if no_phone:
        _log(f"  {len(no_phone)} with NO phone: " + ", ".join(no_phone))
    if no_camp:
        _log(f"  {len(no_camp)} with NO campaign: " + ", ".join(no_camp))

    svc = cw._service(ACCOUNT)
    grp = cw.find_group(svc, GROUP)
    if grp is None:
        _log(f"group {GROUP!r} not found in {ACCOUNT} — aborting")
        return 1
    members = load_group_members(svc, grp)
    create, update, ok = plan(targets, members)

    _log(f"CREATE {len(create)} · UPDATE {len(update)} · already-correct {len(ok)}")
    for t in sorted(create, key=lambda x: x["name"]):
        disp = f"{t['name']} ({t['campaign']})" if t["campaign"] else t["name"]
        note = build_notes(t).replace("\n", " · ")
        _log(f"  + {disp}   [{t['status']}]" + (f"   notes: {note}" if note else ""))
    for m, new_display, new_notes in sorted(update, key=lambda x: x[1]):
        what = []
        if _norm(m["display"]) != _norm(new_display):
            what.append(f"name {m['display']!r}->{new_display!r}")
        if (m.get("bio", "") or "").strip() != new_notes.strip():
            what.append("notes:" + new_notes.replace("\n", " · ").replace(NOTE_MARKER, "").strip())
        _log(f"  ~ {new_display}: " + "; ".join(what))

    if not a.write:
        _log("DRY RUN — re-run with --write to apply")
        return 0
    apply(svc, grp, create, update)
    _log(f"wrote: created {len(create)}, updated {len(update)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
