"""Monthly cleanup of alphaletereception@gmail.com's Google Contacts.

JD asked (2026-11-13) because the reception phone had ~16k contacts and ran
slow. Two rules, both approved by JD + Eve (11/17 and 11/19). Everything else
is NEVER touched -- recruiters, managers, anyone we can't prove is one of
these two:

  A. APPLICANT: the contact's note has an interview date -- "Date and Time:
     MM/DD/YYYY" (1st round), "Date/Time: MM/DD/YYYY" (AppStream 2nd round
     card) or "2nd round ... MM/DD/YYYY" (second_round_contacts / LinkedIn
     test); with several, the LATEST one counts -- that date is more than 30 days ago, and the name is not on a
     Sales Board (= never hired).
  B. REP WHO LEFT WITHOUT SELLING: no note at all, phone or email matches an
     OwnerVille rep, EVERY matching OwnerVille record is retired, the OV start
     date is on/after 2024-07-01 (what the 2025 Sales Board covers), and the
     name is not on a Sales Board -- not even a look-alike (same last name +
     same first 3 letters of the first name).

Either rule is skipped for anyone in a real label (not "Imported on ...").

Safety:
  - a full backup of every contact is written before anything is deleted
  - more than MAX_DELETE candidates = something is off: nothing is deleted
    and Eve gets a DM instead
  - --dry-run builds the list + DMs Eve the counts, deletes nothing

    python -m automations.reception_contacts_cleanup.run --dry-run
    python -m automations.reception_contacts_cleanup.run
"""
from __future__ import annotations  # Lucy runs Python 3.9

import argparse
import csv
import datetime as dt
import json
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

ACCOUNT = "alphaletereception@gmail.com"
EVE = "U088E2KJEV8"
BOARDS = {"Alphalete SALES BOARD 2025": "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc",
          "ORG sales board": "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"}
APPLICANT_DAYS = 30
OV_START_FLOOR = dt.date(2024, 7, 1)
MAX_DELETE = 1500
SYSTEM_GROUPS = {"myContacts", "all", "starred", "friends", "family", "coworkers",
                 "chatBuddies", "blocked"}
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "reception-contacts"

# Eve 11/23: 2nd-round notes use other wordings -- without these they were
# never cleaned up (240 of them on the phone that day).
_INTERVIEW = re.compile(
    r"(?:Date(?: and |/)Time:\s*|2nd round\b[^/\n]{0,40}?\b)(\d{1,2})/(\d{1,2})/(\d{4})",
    re.IGNORECASE)
_SUFFIX = {"jr", "sr", "ii", "iii", "iv", "rt"}


# ---------- pure rules (tested) ----------

def norm(s) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", str(s or "").lower()).split())


def phone10(s) -> str:
    d = re.sub(r"\D", "", str(s or ""))
    return d[-10:] if len(d) >= 10 else ""


def ov_date(s) -> Optional[dt.date]:
    for fmt in ("%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(str(s or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def interview_date(bios: str) -> Optional[dt.date]:
    """Latest interview date in the note (None if there is none)."""
    found = []
    for m in _INTERVIEW.finditer(bios or ""):
        try:
            found.append(dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))))
        except ValueError:
            continue
    return max(found) if found else None


def on_board(name: str, board: Set[str]) -> bool:
    """Exact name, or a look-alike: same last name + same first 3 letters."""
    n = norm(name)
    if not n:
        return False
    if n in board:
        return True
    words = [w for w in n.split() if w not in _SUFFIX]
    if len(words) < 2:
        return False
    first, last = words[0], words[-1]
    return any(last in b.split() and any(w.startswith(first[:3]) for w in b.split())
               for b in board)


def decide(contact: dict, *, today: dt.date, labels: List[str], board: Set[str],
           ov_by_phone: Dict[str, list], ov_by_email: Dict[str, list]):
    """('delete' | 'keep', reason)."""
    name = (contact.get("names") or [{}])[0].get("displayName", "")
    bios = " ".join(b.get("value") or "" for b in contact.get("biographies", []))
    if labels:
        return "keep", "in a label"
    d = interview_date(bios)
    if d is not None:
        if (today - d).days <= APPLICANT_DAYS:
            return "keep", "interview under 30 days"
        if on_board(name, board):
            return "keep", "name on a Sales Board"
        return "delete", "A: applicant, interview %d days ago, never hired" % (today - d).days
    if bios.strip():
        return "keep", "has a note"
    hits = []
    for p in contact.get("phoneNumbers", []):
        hits += ov_by_phone.get(phone10(p.get("value")), [])
    for e in contact.get("emailAddresses", []):
        hits += ov_by_email.get((e.get("value") or "").strip().lower(), [])
    if not hits:
        return "keep", "not in OwnerVille"
    if any(h["roster"] != "inactive" for h in hits):
        return "keep", "still active in OwnerVille"
    starts = [ov_date(h["start"]) for h in hits]
    if any(s is None or s < OV_START_FLOOR for s in starts):
        return "keep", "started before the 2025 Sales Board"
    if on_board(name, board) or any(on_board("%s %s" % (h["first"], h["last"]), board)
                                    for h in hits):
        return "keep", "name on a Sales Board"
    return "delete", "B: retired in OwnerVille, never on a Sales Board"


def ov_index(reps: Iterable[dict]):
    by_phone: Dict[str, list] = {}
    by_email: Dict[str, list] = {}
    for r in reps:
        p = phone10(r.get("phone"))
        if p:
            by_phone.setdefault(p, []).append(r)
        e = (r.get("email") or "").strip().lower()
        if "@" in e:
            by_email.setdefault(e, []).append(r)
    return by_phone, by_email


# ---------- I/O ----------

def _fetch_all(svc, cw) -> list:
    out, tok = [], None
    while True:
        r = cw._retry(lambda: svc.people().connections().list(
            resourceName="people/me", pageSize=1000, pageToken=tok,
            personFields="names,emailAddresses,phoneNumbers,biographies,memberships").execute())
        out += r.get("connections", [])
        tok = r.get("nextPageToken")
        if not tok:
            return out


def _real_groups(svc) -> Dict[str, str]:
    gs, tok = [], None
    while True:
        r = svc.contactGroups().list(pageSize=1000, pageToken=tok).execute()
        gs += r.get("contactGroups", [])
        tok = r.get("nextPageToken")
        if not tok:
            break
    return {g["resourceName"].split("/")[-1]: g.get("formattedName", "") for g in gs
            if not g.get("formattedName", "").startswith("Imported on")
            and g["resourceName"].split("/")[-1] not in SYSTEM_GROUPS}


def _board_names() -> Set[str]:
    from automations.recruiting_report.fill import open_by_key
    names: Set[str] = set()
    for key in BOARDS.values():
        ss = open_by_key(key)
        ranges = ["'%s'" % w.title.replace("'", "''") for w in ss.worksheets()]
        for i in range(0, len(ranges), 10):
            for attempt in range(6):
                try:
                    res = ss.values_batch_get(ranges[i:i + 10])
                    break
                except Exception as e:  # noqa: BLE001 -- 429 shared quota
                    if "429" not in str(e) or attempt == 5:
                        raise
                    time.sleep(65)
            time.sleep(3)
            for vr in res.get("valueRanges", []):
                for row in vr.get("values", []):
                    for c in row:
                        n = norm(c)
                        if 2 <= len(n.split()) <= 5:
                            names.add(n)
    if len(names) < 200:
        raise RuntimeError("only %d names read off the Sales Boards -- refusing "
                           "to decide 'never hired' on a half-read board" % len(names))
    return names


def _dm_eve(text: str) -> None:
    try:
        from automations.shared import slack_metrics_post as sp
        sp._client().chat_postMessage(channel=EVE, text=text)
    except Exception as e:  # noqa: BLE001 -- the log still has the summary
        print("slack DM failed: %s" % e)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    from dataclasses import asdict
    from automations.fiber_owners_distro import contacts_write as cw
    from automations.mobrium_list import ownerville

    today = dt.date.today()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    svc = cw._service(ACCOUNT)
    contacts = _fetch_all(svc, cw)
    backup = OUT_DIR / ("monthly-backup-%s.json" % today.isoformat())
    backup.write_text(json.dumps(contacts, ensure_ascii=False), encoding="utf-8")
    print("contacts: %d (backup -> %s)" % (len(contacts), backup.name))
    groups = _real_groups(svc)
    board = _board_names()
    print("sales board names: %d" % len(board))
    reps = [asdict(r) for r in ownerville.load(include_inactive=True).reps]
    print("ownerville reps: %d" % len(reps))
    by_phone, by_email = ov_index(reps)

    rows, counts = [], {}
    for c in contacts:
        labels = [groups[m["contactGroupMembership"]["contactGroupId"]]
                  for m in c.get("memberships", [])
                  if m.get("contactGroupMembership", {}).get("contactGroupId") in groups]
        v, why = decide(c, today=today, labels=labels, board=board,
                        ov_by_phone=by_phone, ov_by_email=by_email)
        counts[why] = counts.get(why, 0) + 1
        rows.append({"action": v, "reason": why,
                     "name": (c.get("names") or [{}])[0].get("displayName", ""),
                     "phone": (c.get("phoneNumbers") or [{}])[0].get("value", ""),
                     "email": (c.get("emailAddresses") or [{}])[0].get("value", ""),
                     "resourceName": c["resourceName"]})
    dele = [r for r in rows if r["action"] == "delete"]
    nA = sum(1 for r in dele if r["reason"].startswith("A:"))
    nB = len(dele) - nA
    listing = OUT_DIR / ("monthly-%s.csv" % today.isoformat())
    with listing.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["action"])
        w.writeheader()
        w.writerows(dele)
    for k, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print("  %6d  %s" % (n, k))

    if args.dry_run:
        _dm_eve("Reception contacts cleanup (TEST, nothing deleted): would remove %d "
                "of %d (%d old applicants, %d reps who left without selling)."
                % (len(dele), len(contacts), nA, nB))
        print("DRY RUN -- nothing deleted")
        return 0
    if len(dele) > MAX_DELETE:
        _dm_eve(":warning: Reception contacts cleanup STOPPED: it wanted to remove %d "
                "contacts (limit %d). Nothing was deleted -- something looks off."
                % (len(dele), MAX_DELETE))
        print("STOPPED: %d > %d" % (len(dele), MAX_DELETE))
        return 1
    names = [r["resourceName"] for r in dele]
    for i in range(0, len(names), 500):
        chunk = names[i:i + 500]
        cw._retry(lambda: svc.people().batchDeleteContacts(
            body={"resourceNames": chunk}).execute())
        print("  deleted %d/%d" % (min(i + 500, len(names)), len(names)))
        time.sleep(2)
    left = len(contacts) - len(names)
    _dm_eve("Reception contacts cleanup: removed %d (%d old applicants, %d reps who "
            "left without selling). %d contacts left." % (len(names), nA, nB, left))
    print("done: removed %d, %d left" % (len(names), left))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
