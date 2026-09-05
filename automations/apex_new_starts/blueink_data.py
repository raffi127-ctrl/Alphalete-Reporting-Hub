"""Pull one new start's onboarding answers out of their signed Blue Ink packet.

The packet is three documents -- I-9, W-4 and the direct-deposit form -- and
the same fact appears on more than one of them (the address is on both the I-9
and the W-4). So each field is taken from a PREFERRED document and only falls
back to another if the preferred one left it blank, and every value is
re-checked against the shape it is supposed to have before it is handed on.
That second check is the point: `field_map.json` was calibrated in the past, and
if somebody edits a template the keys shift. A shifted key almost always shows
up as a value of the wrong shape -- a phone number where a ZIP should be -- and
that comes back as a REFUSAL to fill rather than a wrong number typed into Apex.

Read-only. This module never creates, sends or cancels anything on Blue Ink;
the only calls it makes are GETs against bundles that are already complete.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dfield
from typing import Dict, List, Optional

from automations.blueink_docs import blueink as B
from automations.apex_new_starts import fieldmap as FM

# Which document to believe first, by the substring of its name. The I-9 is the
# federal form: its fields are the ones the person filled in most carefully and
# the ones an auditor would compare against.
DOC_PREFERENCE = ("i9", "i-9", "w4", "w-4", "dd", "direct deposit")

# What each mapped value has to look like before it is allowed through. A field
# with no rule here (city, address, names) is accepted as any non-blank text.
SHAPE = {
    "ssn": FM._SSN,
    "zip": FM._ZIP,
    "phone": FM._PHONE,
    "state": FM._STATE,
    "routing": FM._ROUTING,
    "account": FM._ACCOUNT,
    "email": re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    "dob": re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$|^\d{4}-\d{2}-\d{2}$"),
}

PAGE_SIZE = 50


@dataclass
class NewHire:
    """One person's onboarding answers, ready to be typed into Apex."""
    name: str                      # as the sales board spells it
    bundle_id: str = ""
    packet_name: str = ""          # as Blue Ink spells it
    values: Dict[str, str] = dfield(default_factory=dict)
    rejected: List[tuple] = dfield(default_factory=list)   # (name, why)
    missing_packet: bool = False
    has_ssn: bool = False          # their packet HAS one; its value is not kept
    matched_on: str = ""           # 'email' (proof) or 'name' (judgement)

    @property
    def have(self) -> List[str]:
        return [k for k in FM.PERSONAL if self.values.get(k)]

    # There is no `sensitive` property any more, and that is the point: since
    # 2026-09-05 the Social is not read out of Blue Ink at all. `extract` sees
    # it, records that one EXISTS, and drops the value on the floor. Nothing in
    # this report ever holds a Social Security number, so nothing can print it,
    # log it, write it to output/ or hand it to a browser. The operator types it
    # into a local prompt (see ssn_prompt.py) and it goes straight into Apex.

    def fillable(self) -> Dict[str, str]:
        return {k: v for k, v in self.values.items()
                if k in FM.PERSONAL and v}


def _norm(s) -> str:
    return " ".join(str(s if s is not None else "").split()).strip()


# Name-shaped noise that must come off before two spellings can be compared.
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_PUNCT = re.compile(r"[^\w\s]")


def _key(name: str) -> str:
    """Match key: last|first, folded hard.

    The board and Blue Ink spell the same person differently far more often
    than you would expect, and every difference seen so far is punctuation or
    decoration rather than a different person:

        board  "Ja'Vanna Nash"        Blue Ink  "Javanna Nash"
        board  "Jean Urbina Finol"    Blue Ink  "Jean Finol"
        board  "Orlando Marines (Wk 2)"

    So: parentheticals off (`base_name`), accents stripped, punctuation
    removed, suffixes dropped, then FIRST and LAST token only -- middle names
    appear on one side and not the other. Comparison only; nothing is ever
    written from this.
    """
    import unicodedata
    from automations.terminated_reps.board import base_name
    folded = unicodedata.normalize("NFKD", base_name(name))
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    parts = [p for p in _PUNCT.sub("", folded.replace("-", " ")).split()
             if p and p not in _SUFFIXES]
    if len(parts) < 2:
        return "|".join(parts)
    return f"{parts[-1]}|{parts[0]}"


def completed_bundles(limit: int = 200, pages: int = 6) -> List[dict]:
    """Recent bundles whose signer has FINISHED, newest first.

    Only 'co' (complete) counts. A packet still out for signature has no
    answers in it, and half a record in Apex is worse than none.
    """
    out: List[dict] = []
    for page in range(1, pages + 1):
        rows = B._results(B._request(
            "GET", "/bundles/", params={"page": page, "per_page": PAGE_SIZE}))
        if not rows:
            break
        for b in rows:
            if str(b.get("status")) == "co":
                out.append(b)
                if len(out) >= limit:
                    return out
    return out


def bundle_data(bundle_id: str) -> List[dict]:
    """Every filled field of one bundle."""
    return B._request("GET", f"/bundles/{bundle_id}/data/") or []


def index_by_person(bundles: List[dict]) -> tuple:
    """(by_email, by_name) -- newest wins, since `bundles` is newest-first.

    Two indexes because the packet's EMAIL is the stronger key: it is the
    address the packet was actually delivered to, so a match on it is proof,
    where a name match is a judgement about spelling. A rehire can have two
    signed packets; the one they signed most recently is the one that
    describes them now.
    """
    by_email: Dict[str, dict] = {}
    by_name: Dict[str, dict] = {}
    for b in bundles:
        for p in b.get("packets") or []:
            if str(p.get("status")) != "co":
                continue
            em = _norm(p.get("email")).lower()
            if em and em not in by_email:
                by_email[em] = b
            k = _key(p.get("name") or "")
            if k and k not in by_name:
                by_name[k] = b
    return by_email, by_name


def _doc_rank(doc_name: str) -> int:
    low = (doc_name or "").lower()
    for i, tag in enumerate(DOC_PREFERENCE):
        if tag in low:
            return i
    return len(DOC_PREFERENCE)


def extract(bundle: dict, mapping: Dict[str, Dict[str, str]],
            name: str) -> NewHire:
    """Map one bundle's fields into a NewHire, rejecting wrong-shaped values."""
    hire = NewHire(name=name, bundle_id=str(bundle.get("id", "")),
                   packet_name=_norm((bundle.get("packets") or [{}])[0].get("name")))
    docs = {d["key"]: _norm(d.get("name")) for d in bundle.get("documents") or []}
    # (semantic name) -> (doc rank, value), best-ranked document wins.
    best: Dict[str, tuple] = {}
    for f in bundle_data(hire.bundle_id):
        doc = docs.get(f.get("doc_key")) or ""
        sem = (mapping.get(doc) or {}).get(f.get("field_key"))
        val = _norm(f.get("value"))
        if not sem or not val or val == "[signature]":
            continue
        if sem in FM.SENSITIVE:
            # Seen and deliberately discarded -- see the note on NewHire.
            hire.has_ssn = True
            continue
        rule = SHAPE.get(sem)
        if rule and not rule.match(val):
            hire.rejected.append(
                (sem, f"{doc} field {f.get('field_key')} doesn't look like a "
                      f"{sem} — field_map.json may be stale, recalibrate"))
            continue
        rank = _doc_rank(doc)
        if sem not in best or rank < best[sem][0]:
            best[sem] = (rank, val)
    hire.values = {k: v for k, (_, v) in best.items()}
    return hire


def for_people(people, mapping: Optional[dict] = None,
               limit: int = 200) -> Dict[str, NewHire]:
    """{board name: NewHire} for everyone we can find a signed packet for.

    `people` is anything with `.name` and `.email` (the board's Candidates), or
    plain name strings.

    ONE sweep of the bundle list for the whole cohort, then one data call per
    person we actually matched -- a per-person search would be ~50 API calls
    for a 13-person week and rate-limit the account.
    """
    mapping = mapping or FM.load()
    by_email, by_name = index_by_person(completed_bundles(limit=limit))
    out: Dict[str, NewHire] = {}
    for person in people:
        name = getattr(person, "name", person)
        email = _norm(getattr(person, "email", "")).lower()
        b = (by_email.get(email) if email else None) or by_name.get(_key(name))
        if not b:
            out[name] = NewHire(name=name, missing_packet=True)
            continue
        hire = extract(b, mapping, name)
        hire.matched_on = "email" if email and email in by_email else "name"
        out[name] = hire
    return out


def signed_pdf_url(bundle_id: str) -> str:
    """A short-lived link to the signed I-9 PDF, for the operator to read the
    SSN off. Blue Ink's own expiring S3 link -- nothing is downloaded here and
    the number never enters this report's output."""
    try:
        files = B._request("GET", f"/bundles/{bundle_id}/files/") or []
    except Exception:  # noqa: BLE001
        return ""
    best = ""
    for f in files:
        url = f.get("file_url") or ""
        if "i9" in url.lower().replace("-", "") or "i_9" in url.lower():
            return url
        best = best or url
    return best
