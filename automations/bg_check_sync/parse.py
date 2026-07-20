"""Classify a First Advantage / Sterling ("fadv.co") email into a background-check
status event.

Every result email lands from ``noreply@us.fadv.co`` (a couple use
``NoReply@us.fadv.co``). We only care about a handful of subject/body shapes;
everything else (bulk-invite confirmations, one-time auth codes) is ignored.

The candidate is identified by Sterling's "Last, First Middle" convention, which
we split into (first, last) for matching against the sheet's separate first/last
columns. Matching itself lives in ``match.py`` -- this module only extracts.

Status vocabulary matches column K of the D2D OBCL tabs exactly:
    Sent | Taken - Pending | Review | Passed | Failed | Unperformable | Complete
"""
from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

# ---- status constants (must match the sheet's column-K vocabulary) ----------
SENT = "Sent"
TAKEN_PENDING = "Taken - Pending"
REVIEW = "Review"
PASSED = "Passed"
FAILED = "Failed"
UNPERFORMABLE = "Unperformable"
COMPLETE = "Complete"  # plain "is complete" with no score email; see PLAIN_COMPLETE_STATUS

# COMPLIANCE RULE (Raf, hard): we NEVER mark someone "Passed" unless an explicit
# "Score PASS" email says so -- calling an unadjudicated report a pass could get
# us in serious trouble. So a plain "Background Check for X is complete" (only a
# "click to view" link, no Score PASS, not moved to Review) does NOT become
# Passed. We keep it at Taken - Pending and surface it on a "report is back,
# needs your PASS/FAIL confirmation" list so a human adjudicates it.
PLAIN_COMPLETE_STATUS = TAKEN_PENDING

# Rank = how "advanced"/authoritative a status is. When a candidate has several
# emails, the highest (rank, date) wins -- a later ETA "still pending" ping must
# never clobber an earlier "Passed", and a "Score FAIL" must win over an earlier
# "Review". Terminal outcomes share the top rank; ties break on email date.
RANK = {
    SENT: 1,
    TAKEN_PENDING: 2,
    REVIEW: 3,
    COMPLETE: 4,
    PASSED: 5,
    FAILED: 5,
    UNPERFORMABLE: 5,
}

FADV_SENDER = "fadv.co"


@dataclass
class BGEvent:
    """One parsed status signal for one candidate from one email."""
    last: str
    first: str
    status: str
    date: str          # ISO-ish string from the email header, for tie-breaking
    subject: str
    source_id: str = ""  # gmail/imap message id, for auditing
    needs_adjudication: bool = False  # report is back but not officially PASS/FAIL

    @property
    def rank(self) -> int:
        return RANK.get(self.status, 0)


def _clean(text: str) -> str:
    """Un-escape HTML entities and collapse whitespace."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_name(last_comma_first: str) -> Optional[tuple[str, str]]:
    """'Woods, Cedric Charles' -> ('Woods', 'Cedric'). First token after the
    comma is the given name; anything before the comma is the surname."""
    s = _clean(last_comma_first)
    if "," not in s:
        return None
    last, rest = s.split(",", 1)
    last = last.strip()
    rest = rest.strip()
    if not last or not rest:
        return None
    first = rest.split()[0]
    return last, first


def is_fadv(sender: str) -> bool:
    return FADV_SENDER in (sender or "").lower()


# Name embedded in the "view the background check of Last, First" link -- used by
# emails whose subject has no name (Unperformable) or as a body fallback.
_VIEW_RE = re.compile(r"background check of\s+([^<\n]+?)\s*(?:<|$)", re.IGNORECASE)
# "Applicant: Last, First" line in Score PASS/FAIL bodies.
_APPLICANT_RE = re.compile(r"Applicant:\s*([^\n<]+?)\s*(?:Score|<|$)", re.IGNORECASE)


def _name_from_subject_between(subject: str, before: str, after: str) -> Optional[str]:
    s = _clean(subject)
    m = re.search(re.escape(before) + r"\s*(.+?)\s*" + re.escape(after), s, re.IGNORECASE)
    return m.group(1) if m else None


def classify(sender: str, subject: str, body: str, date: str = "",
             source_id: str = "") -> Optional[BGEvent]:
    """Return a BGEvent for a fadv result email, or None if the email isn't a
    per-candidate status signal (bulk invites, auth codes, etc.)."""
    if not is_fadv(sender):
        return None

    subj = _clean(subject)
    body_c = _clean(body)
    low_subj = subj.lower()
    low_body = body_c.lower()

    raw_name: Optional[str] = None
    status: Optional[str] = None
    needs_adjudication = False

    # --- Score PASS / FAIL ---------------------------------------------------
    if "background check complete - score pass" in low_subj:
        status = PASSED
        m = _APPLICANT_RE.search(body_c)
        raw_name = m.group(1) if m else None
    elif "background check complete - score fail" in low_subj:
        # "Score FAIL" is NOT a terminal failure. Every one of these emails
        # (178/179 verified) carries body "Score: Review/Adverse Action" and
        # "report status: REVIEW" -- Sterling has flagged the check for
        # adverse-action REVIEW, which a rep can still be cleared through. So we
        # record REVIEW (pending), never terminal FAILED, and mark it for human
        # adjudication. Marking a rep "Failed" off this email is the exact
        # false-fail Raf ruled out (2026-07-20).
        status = REVIEW
        needs_adjudication = True
        m = _APPLICANT_RE.search(body_c)
        raw_name = m.group(1) if m else None

    # --- SSN Trace Unperformable (name only in the body link) ----------------
    elif "unperformable" in low_subj:
        status = UNPERFORMABLE
        m = _VIEW_RE.search(body_c)
        raw_name = m.group(1) if m else None

    # --- E-invite completed = candidate took the check -----------------------
    elif "e-invite for" in low_subj and "is complete" in low_subj:
        status = TAKEN_PENDING
        raw_name = _name_from_subject_between(subj, "E-Invite for", "is Complete")

    # --- ETA update = completion date slipped; still pending -----------------
    elif "background check eta update for" in low_subj:
        status = TAKEN_PENDING
        # subject ends with the name, so grab everything after the phrase
        idx = low_subj.find("eta update for")
        raw_name = subj[idx + len("eta update for"):].strip() if idx >= 0 else None

    # --- "Background Check for X is complete" (Review vs plain) ---------------
    elif low_subj.startswith("background check for") and low_subj.endswith("is complete"):
        raw_name = _name_from_subject_between(subj, "Background Check for", "is complete")
        if "moved to review status" in low_body or "review status" in low_body:
            status = REVIEW
        else:
            status = PLAIN_COMPLETE_STATUS
            needs_adjudication = True  # report back, no Score PASS -> human confirms

    # --- "Background Check for X is Consider" = needs review ------------------
    elif low_subj.startswith("background check for") and low_subj.endswith("is consider"):
        status = REVIEW
        raw_name = _name_from_subject_between(subj, "Background Check for", "is Consider")

    if status is None or not raw_name:
        return None

    split = _split_name(raw_name)
    if not split:
        return None
    last, first = split
    return BGEvent(last=last, first=first, status=status, date=date or "",
                   subject=subj, source_id=source_id,
                   needs_adjudication=needs_adjudication)


# ---- name normalization (shared with match.py) ------------------------------
def norm(name: str) -> str:
    """Fold case, strip accents and punctuation for tolerant name matching.
    'Durañona' -> 'duranona', 'Dawkins - Jones' -> 'dawkins jones'."""
    s = unicodedata.normalize("NFKD", _clean(name))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()
