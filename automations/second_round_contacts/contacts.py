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
    from automations.fiber_owners_distro import contacts_write as cw
    try:
        cw._retry(lambda: svc.people().get(resourceName=resource_name,
                                           personFields="names").execute())
        return True
    except Exception:  # noqa: BLE001 -- 404 = deleted by hand; that is an answer
        return False
