"""Camila's list of the recruiters on our team, read live from her Excel.

She keeps it up to date in the `mails` tab of "Tracking ARS Services.xlsx" and
people join every week (Eve 2026-11-04), so the audit reads it every time it
needs the protected list. Nobody has to send it or copy it anywhere, and no
email ends up in the repo.

READ ONLY (Eve 2026-11-04: Lucy must never change or delete anything in that
Excel). The Excel is Maud's, so the Hub's usual `drive.file` token can't see it
and this uses alphaletereporting's full-drive login. Google won't narrow that
login to read-only (`invalid_scope`), so the guard is here: this module makes
one plain HTTP GET and holds no Drive client that could do anything else. A
test fails if a write call ever shows up in this file.

Anything wrong with the Excel raises: protected_ids() turns that into nobody
being deactivated.
"""
from __future__ import annotations  # Lucy runners are Python 3.9

import io
import re
import unicodedata
from typing import Dict, List, Set, Tuple

FILE_ID = "1rHyZbE2SBwB2K0buqgb_lv4oBvx4sh1Z"   # Tracking ARS Services.xlsx
TAB = "mails"
NAME_HEADER = "owner"
SLACK_HEADER = "slack id"       # holds their Slack display name, despite the header
EMAIL_HEADER = "email"
DOWNLOAD_URL = "https://www.googleapis.com/drive/v3/files/{id}"
SLACK_ID = re.compile(r"^U[A-Z0-9]{8,}$")


class StaffSheetError(RuntimeError):
    pass


def _key(text) -> str:
    """Lowercase, no accents, no extra spaces: Belén == Belen."""
    plain = unicodedata.normalize("NFKD", str(text or ""))
    plain = plain.encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z ]+", " ", plain).split())


def parse(workbook_bytes: bytes) -> List[Dict[str, str]]:
    """Every person in the tab. Columns are found by header, never by position."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(workbook_bytes), read_only=True,
                                data_only=True)
    try:
        tab = next((n for n in wb.sheetnames if n.strip().lower() == TAB), None)
        if tab is None:
            raise StaffSheetError(f"no '{TAB}' tab in the staff Excel")
        rows = list(wb[tab].iter_rows(values_only=True))
    finally:
        wb.close()
    wanted = (NAME_HEADER, SLACK_HEADER, EMAIL_HEADER)
    for i, row in enumerate(rows[:10]):
        heads = [_key(c) for c in row]
        if all(h in heads for h in wanted):
            cols = {h: heads.index(h) for h in wanted}
            break
    else:
        raise StaffSheetError(f"headers not found in the '{TAB}' tab")
    people = []
    for row in rows[i + 1:]:
        name, slack, email = (str(row[cols[h]] or "").strip() for h in wanted)
        if name or slack or email:
            people.append({"name": name, "slack": slack, "email": email.lower()})
    if not people:
        raise StaffSheetError(f"the '{TAB}' tab has nobody in it")
    return people


def read_people() -> List[Dict[str, str]]:
    """Downloads a copy into memory. Nothing is saved, nothing is sent back."""
    import requests
    from automations.first_round_scorecards.drive_auth import load_credentials
    resp = requests.get(
        DOWNLOAD_URL.format(id=FILE_ID), params={"alt": "media"}, timeout=120,
        headers={"Authorization": f"Bearer {load_credentials().token}"})
    if resp.status_code != 200:
        raise StaffSheetError(f"can't read the staff Excel: HTTP {resp.status_code}")
    return parse(resp.content)


def match(people: List[Dict[str, str]],
          users: List[Dict]) -> Tuple[Set[str], List[str]]:
    """(Slack ids, names of whoever has no account). Email first, then name.
    A shared name protects everyone who has it: keeping one account too many
    is harmless, deactivating a recruiter is what this is here to stop."""
    by_email, by_name = {}, {}
    for u in users:
        if u.get("bot"):
            continue
        if u.get("email"):
            by_email[u["email"].lower()] = u["id"]
        if not (u.get("deleted") or u.get("external")):
            by_name.setdefault(_key(u.get("name")), []).append(u["id"])
    ids, missing = set(), []
    for p in people:
        if SLACK_ID.match(p["slack"]):
            ids.add(p["slack"])
        elif p["email"] and p["email"] in by_email:
            ids.add(by_email[p["email"]])
        else:
            hits = by_name.get(_key(p["slack"])) or by_name.get(_key(p["name"]))
            if hits:
                ids.update(hits)
            else:
                missing.append(p["name"] or p["slack"] or p["email"])
    return ids, missing
