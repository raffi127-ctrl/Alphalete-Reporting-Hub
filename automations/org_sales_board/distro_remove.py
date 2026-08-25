"""Take a rep OFF the Contacts groups that mail them a board they left.

The other half of the two-week zero rule ([[roster_remove]]): a rep removed from
the board must stop receiving the report that no longer lists them. There are
THREE places a name lives, and fixing one does nothing for the others:

  1. the board rows            → org_sales_board.roster_remove
  2. the code fallback lists   → captainship_drafts.config.RECIPIENTS,
                                 scheduled_6_days_out.email_send.RECIPIENTS,
                                 org_sales_board/distro_fallback.json
  3. the LIVE Contacts group   → this module

(2) is not cosmetic: `captainship_drafts.seed_groups` REBUILDS a group from
`RECIPIENTS`, so a name left in code walks back into the group the next time it
runs — the Jeremiah Minor / Ethan McKendree pattern.
[[project_seed-groups-undoes-manual-contact-removals]]

MEMBERSHIP IS PER PERSON, NOT PER ADDRESS. One contact card can carry two
addresses (Benjamin Burden holds a gmail AND a bgsu.edu), and the group holds the
PERSON. So a target is matched on person identity — any of the card's emails, or
its display name — and the whole membership goes. Display names drift from the
board's spelling ("Edgar Munoz II" in Contacts vs "Edgar Muniz II" on the board),
which is why an address is the safer key and the name is only a fallback.

REMOVES FROM THE GROUP, KEEPS THE CONTACT. `remove_members` unlinks membership;
nobody's contact card is deleted.

TWO TOKENS. The plan reads through the read-ONLY contacts token every machine
has; --apply needs the read-write one, which is a one-time interactive consent
per account and therefore cannot be granted from an unattended runner:

    python -m automations.fiber_owners_distro.contacts_write \
        --authorize --account alphaletereporting@gmail.com

    python -m automations.org_sales_board.distro_remove              # plan
    python -m automations.org_sales_board.distro_remove --apply      # write
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ACCOUNT = "alphaletereporting@gmail.com"

# Who comes off which group — the 2026-08-19 two-week-zero batch. Emails are the
# key; the name is what gets printed and the fallback match. Ronald Dawson and
# Jimmy Bonilla are on NO distro (checked live 2026-08-19), so they aren't here.
#
# ⚠ "Raf's Captain Team" and "Carlos' Captain Team" are SHARED with the Org Sales
# Board email (captainship_drafts.distro.GROUPS), so a removal there also stops
# the org board mail. Correct for this batch — none of them has a board row left.
REMOVALS: dict = {
    "Alphalete Org Owners": [
        ("Cinthya Reyes", "cinthyareyes093@gmail.com"),
        ("Benjamin Burden", "benjaminburden02@gmail.com"),   # also burdenb@bgsu.edu
        ("David Martinez", "martinez699341@gmail.com"),
        # 2026-08-19 (Eve): Paola Rodriguez comes off EVERY report, so both of
        # her distros go, not just the board's. Her second card
        # (rpaola17@icloud.com) is on no group, so it needs no entry.
        ("Paola Rodriguez", "rpaola205@gmail.com"),
    ],
    # Owners Call Reminder's distro — no code fallback, the live group is it.
    "Org. Call Invite": [
        ("Paola Rodriguez", "rpaola205@gmail.com"),          # 2026-08-19
    ],
    "Raf's Captain Team": [
        ("Edgar Muniz II", "edgarmuniz2020@icloud.com"),     # "Edgar Munoz II" in Contacts
        ("Benjamin Burden", "benjaminburden02@gmail.com"),
        # 2026-08-20 (Eve): Steve McElwee is not in Rafael's captainship at all
        # — a different reason from the two-week zero rule above, same removal.
        # His rows came off the board and off Rafael's six metrics tabs the
        # same day, and Tableau is pinned in shared/captainship_pins.
        # His card is on ONE other group, "ATT Fiber Owners", which STAYS: he
        # is still a real ATT fiber ICD, just not one of Raf's.
        ("Steve McElwee", "mcelwee.steve95@gmail.com"),
    ],
    "Wayne's Captain Team": [
        ("Mason Davis", "mason.d.management@gmail.com"),
    ],
    "Starr's Captainship": [
        ("Jason Strid", "jason.vyzahinc@gmail.com"),
        # 2026-08-25 (Eve): two-week zero rule — WE 08.23 and WE 08.16 at 0
        # in BOTH of Starr's fiber boxes. Kobe Cireus flagged the same day
        # stays: he is still selling Fiber - All Units.
        ("William Sassenberg", "William@optimabusinessmgmt.com"),
    ],
    "Tony's Captainship": [
        ("Melik El Jaiez", "melikeljaiez@yahoo.com"),        # no display name on the card
        ("Aden Berhane", "berhaneaden3@gmail.com"),
    ],
    "Carlos' Captain Team": [
        ("Ryan Kabbes", "ryankabbes@gmail.com"),
        ("Kevin Driggs", "kevdriggs25@gmail.com"),
    ],
    "Khalil's Captainship": [
        ("Ayleen Gonzalez", "agonzalezz25@outlook.com"),
    ],
    # 2026-08-24 (Eve): Jesus Hawthorne sale de TODAS las listas de distribución.
    # Su tarjeta está en UN solo grupo vivo ("ATT Fiber Owners") y en ninguna lista
    # de código (grep de nombre y de mail: 0 hits en distro_fallback.json,
    # captainship_drafts.config.RECIPIENTS, scheduled_6_days_out.email_send y
    # leaders_call). Para que el reset semanal no lo reponga va además en
    # fiber_owners_distro/excludes.json. Ojo: ese grupo existe en DOS cuentas
    # (raffi127 + alphaletereporting, ALL_TARGETS de fiber_owners_distro.run) y este
    # módulo sólo escribe en alphaletereporting.
    "ATT Fiber Owners": [
        ("Jesus Hawthorne", "jesus_hawthorne@yahoo.com"),
    ],
    # 2026-08-24 (Eve): Lizette Ruiz comes off Eveliz's captainship only — same
    # shape as Milan Godbolt below. Her address also left
    # captainship_drafts.config.RECIPIENTS["eveliz"] and Tableau is pinned in
    # shared/captainship_pins under "Eveliz". This group is NOT shared with the
    # org board mail, and her card stays on "Alphalete Org Owners": she is
    # still a B2B ICD of the org, just not one of Eveliz's.
    "Eveliz's Captainship": [
        ("Lizette Ruiz", "lizetteruiz0510@gmail.com"),
    ],
    "Colten's Captainship": [
        ("Javeon Lara", "javeonterrell@gmail.com"),
        ("Selena Powers", "selena.powersmiami@gmail.com"),   # listed twice on the card
        # 2026-08-21 (Eve): Milan Godbolt comes off Colten's captainship — a
        # different reason from the two-week zero rule above, same removal. His
        # three board rows went the same day and Tableau is pinned in
        # shared/captainship_pins under "Colten". This group is NOT shared with
        # the org board mail, so nothing else changes for him.
        ("Milan Godbolt", "arisesolutions.milan@gmail.com"),
    ],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _members(svc, group: dict) -> list:
    """[{resourceName, name, emails:[lower]}] for a group — same shape from
    either token, so plan and apply compare like for like."""
    full = svc.contactGroups().get(
        resourceName=group["resourceName"], maxMembers=1000).execute()
    rns = full.get("memberResourceNames", []) or []
    out = []
    for i in range(0, len(rns), 200):
        resp = svc.people().getBatchGet(
            resourceNames=rns[i:i + 200],
            personFields="names,emailAddresses").execute()
        for r in resp.get("responses", []):
            p = r.get("person", {})
            out.append({
                "resourceName": p.get("resourceName"),
                "name": (p.get("names") or [{}])[0].get("displayName", ""),
                "emails": [_norm(e.get("value")) for e in (p.get("emailAddresses") or [])
                           if e.get("value")],
            })
    return out


def _find_group(svc, name: str):
    tok = None
    while True:
        r = svc.contactGroups().list(pageSize=200, pageToken=tok).execute()
        for g in r.get("contactGroups", []):
            if _norm(g["name"]) == _norm(name):
                return g
        tok = r.get("nextPageToken")
        if not tok:
            return None


def _service(apply: bool, account: str = ACCOUNT):
    """Read-only service for the plan; read-write for the apply.

    `account` exists because ONE group name can live in two mailboxes: the
    reporting account and raffi127's personal contacts BOTH hold an "ATT Fiber
    Owners" group, and fiber_owners_distro.run syncs the two (its ALL_TARGETS).
    A removal run only here leaves the person on Raf's copy. The read-only plan
    always reads the reporting account (the one token every machine has), so
    --account only changes where --apply writes. (Eve 2026-08-24.)
    """
    from googleapiclient.discovery import build
    if apply:
        from automations.fiber_owners_distro import contacts_write as cw
        if not cw.token_path(account).exists():
            raise SystemExit(
                f"No hay token de ESCRITURA en {cw.token_path(account)}.\n"
                f"Corré una vez, con navegador:\n"
                f"  python -m automations.fiber_owners_distro.contacts_write "
                f"--authorize --account {account}")
        creds = cw.load_credentials(account)
    else:
        from automations.shared import contacts_auth as ca
        creds = ca.load_credentials()
    return build("people", "v1", credentials=creds, cache_discovery=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="org_sales_board.distro_remove")
    ap.add_argument("--apply", action="store_true", help="write (default: plan only)")
    ap.add_argument("--only", default=None, help="one group name, for a partial run")
    ap.add_argument("--account", default=ACCOUNT,
                    help="qué buzón de Contacts escribe --apply (default: la cuenta de reportes). 'ATT Fiber Owners' vive TAMBIÉN en raffi127@gmail.com, cuyo token rw está en la mini.")
    args = ap.parse_args(argv)

    svc = _service(args.apply, args.account)
    todo = {k: v for k, v in REMOVALS.items()
            if not args.only or _norm(k) == _norm(args.only)}
    total = missing = 0
    print(f"=== distro_remove ({'APPLY' if args.apply else 'plan'}) "
          f"— {args.account if args.apply else ACCOUNT}")
    for gname, targets in todo.items():
        g = _find_group(svc, gname)
        if not g:
            print(f"\n### {gname}: GRUPO NO ENCONTRADO — nada que hacer")
            continue
        members = _members(svc, g)
        hit = []
        for who, addr in targets:
            m = next((m for m in members
                      if _norm(addr) in m["emails"] or _norm(who) == _norm(m["name"])), None)
            if m:
                hit.append(m)
                print(f"  {gname:<24} - {who:<18} {addr:<32} "
                      f"(card: {m['name'] or '—'}, {len(m['emails'])} dir.)")
            else:
                missing += 1
                print(f"  {gname:<24} · {who:<18} {addr:<32} ya no estaba")
        total += len(hit)
        if hit and args.apply:
            from automations.fiber_owners_distro import contacts_write as cw
            cw.remove_members(svc, g, hit)
            left = {m["resourceName"] for m in _members(svc, g)}
            still = [m["name"] or m["emails"][0] for m in hit if m["resourceName"] in left]
            print(f"  {gname}: {len(hit)} baja(s)"
                  + (f" — ⚠ SIGUEN: {', '.join(still)}" if still else " ✓"))
    print(f"\n{total} baja(s){' aplicadas' if args.apply else ' a aplicar'}"
          f"{f', {missing} ya no estaban' if missing else ''}")
    if not args.apply:
        print("plan — nada escrito.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
