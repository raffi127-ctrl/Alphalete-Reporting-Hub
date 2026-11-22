"""Google Contacts side, per reception account."""
from __future__ import annotations

import datetime as dt
from typing import Dict, Optional, Tuple

from automations.second_round_contacts import config as C


def has_token(account: str) -> bool:
    from automations.fiber_owners_distro import contacts_write as cw
    return cw.token_path(account).exists()


def token_file(account: str) -> str:
    from automations.fiber_owners_distro import contacts_write as cw
    return cw.token_path(account).name


def service(account: str):
    from automations.fiber_owners_distro import contacts_write as cw
    return cw._service(account)


def ensure_group(svc, name: str) -> dict:
    """The contact group, created when missing."""
    from automations.fiber_owners_distro import contacts_write as cw
    g = cw.find_group(svc, name)
    if g:
        return g
    return cw._retry(lambda: svc.contactGroups().create(
        body={"contactGroup": {"name": name}}).execute())


def existing_index(svc) -> Tuple[Dict[str, str], Dict[str, str]]:
    """({phone10: name}, {email: name}) over the whole account."""
    from automations.applicant_contacts import contacts as K
    return K.existing_index(svc)


#: What `note_for` writes at the end of every card this job creates. It is
#: the signature that makes a card ours rather than one the owner typed.
SIGNATURE = "second_round_contacts"


def ours(svc) -> list:
    """Every card in this account that THIS JOB created.

    Read off the account rather than off a file, because the file lives on
    whichever machine happened to run the job, and the cards live with the
    owner. Matched on the note's signature, not on the group: an owner who
    renames or deletes a contact group has not un-created the contacts, and
    a card dragged out of "2nd Rounds" is still one of ours to audit.

    Returns the raw people, with the fields `state.rebuild` reads.
    """
    from automations.fiber_owners_distro import contacts_write as cw
    out, token = [], None
    while True:
        resp = cw._retry(lambda: svc.people().connections().list(
            resourceName="people/me", pageSize=1000,
            personFields="names,phoneNumbers,emailAddresses,biographies,"
                         "memberships",
            pageToken=token).execute())
        for p in resp.get("connections", []) or []:
            for b in p.get("biographies") or []:
                if SIGNATURE in (b.get("value") or ""):
                    out.append(p)
                    break
        token = resp.get("nextPageToken")
        if not token:
            return out


def display_name(a: dict, day: dt.date) -> str:
    from automations.applicant_contacts.contacts import full_name
    return "%s (%s %d/%d)" % (full_name(a), C.NAME_TAG, day.month, day.day)


def note_for(owner: str, office: str, day: dt.date) -> str:
    return ("2nd round %s - %s (AppStream %s) - second_round_contacts"
            % (day.strftime("%m/%d/%Y"), owner, office))


def create(svc, group: dict, a: dict, *, display: str, note: str) -> str:
    """Create the card (name, mobile, email, note), add it to the group,
    return its resourceName."""
    from automations.applicant_contacts.extract import e164
    from automations.fiber_owners_distro import contacts_write as cw
    body = {"names": [{"unstructuredName": display, "givenName": display}],
            "biographies": [{"value": note, "contentType": "TEXT_PLAIN"}]}
    if a.get("phone"):
        body["phoneNumbers"] = [{"value": e164(a["phone"]), "type": "mobile"}]
    if a.get("email"):
        body["emailAddresses"] = [{"value": a["email"]}]
    person = cw._retry(lambda: svc.people().createContact(
        body=body, personFields="names").execute())
    rn = person.get("resourceName", "")
    if rn:
        cw._retry(lambda: svc.contactGroups().members().modify(
            resourceName=group["resourceName"],
            body={"resourceNamesToAdd": [rn]}).execute())
    return rn


def delete(svc, resource_name: str) -> None:
    from automations.fiber_owners_distro import contacts_write as cw
    cw._retry(lambda: svc.people().deleteContact(resourceName=resource_name).execute())


def still_exists(svc, resource_name: str) -> bool:
    """Is that card still on the account? True / False -- or it RAISES.

    "I COULD NOT TELL" IS NOT "IT IS GONE". This swallowed every exception
    and answered False, and the caller reads False as "already deleted by
    hand" and marks the person REMOVED without deleting anything. A 404 is
    the only error that means gone. A 429 does not, and `_retry` gives up
    and raises after six of them -- the read quota is 90/min/user, so a big
    account is exactly where that happens.

    Measured 2026-11-22: 22 people on Raf's reception account are marked
    `removed` on file and are still on the phone. None on Cyrus's 20 or
    Hasan's 24; all of them on the 143-card account. Once the file says
    removed, nothing looks at that person again -- the audit only gathers
    facts for the tracked -- so they stay on the owner's phone for ever.
    That is the complaint this audit exists to prevent.

    Raising is what the caller already wants: its `except` logs FAILED,
    leaves the status alone, and the next pass tries again.
    """
    from googleapiclient.errors import HttpError

    from automations.fiber_owners_distro import contacts_write as cw
    try:
        cw._retry(lambda: svc.people().get(resourceName=resource_name,
                                           personFields="names").execute())
        return True
    except HttpError as e:
        if getattr(getattr(e, "resp", None), "status", None) == 404:
            return False          # deleted by hand; that IS an answer
        raise


def find_ours(svc, key: str):
    """The resourceName of the card for `key`, looked up on the account.

    A stored resourceName that 404s does not prove the person is off the
    phone: a card re-created since is a different id, and the old one is
    all the file has. Looking them up among the cards this job created
    answers the question the stored id cannot.

    `key` is `state.key_for`'s -- phone first, then email -- so this matches
    the identity everything else dedupes on.
    """
    from automations.second_round_contacts import state as S

    for person in ours(svc):
        e = S.from_card(person)
        if e and S.key_for(e) == key:
            return e.get("resourceName") or ""
    return ""
