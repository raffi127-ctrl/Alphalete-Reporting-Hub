"""Rep contact details out of OwnerVille — the only place the PHONE numbers live.

The sales board carries a new start's email (sometimes) and never their phone,
so the Mobrium List's Phone column can only come from here.

WHERE IT COMES FROM: OwnerVille 'Sales Reps' (index.cfm?p=20), the DataTable
`#table-rep-user-list` — columns ID | First | Last | Full Name | Module Access |
Email | Phone | Start Date | Retired Date | Status. Its four toggle buttons
(Active / Inactive / Admin / Lead) are four `repType` values against ONE
server-side endpoint:

    POST https://v2.ownerville.com/components/users.cfc
    extraParams=<DataTables JSON>&method=getRepList&rqst=<TOKEN>&repType=<TYPE>

WE CALL THAT ENDPOINT DIRECTLY instead of driving the table, for two reasons.
It is server-side paginated, so the rendered <tbody> only ever holds the current
25 rows — scraping the DOM would have silently returned 25 of 420 active reps.
And patchright evaluates in an isolated world, so `window.$('#table-rep-user-list')
.DataTable()` is invisible to us (the same limitation car_rides and
applicant_tracker document); the DataTables API route isn't available at all.
One POST with length=2000 returns every active rep in a single response.

`repType=inactiveReps` is 10k+ rows of everyone ever retired, so it is paged and
only fetched when a caller asks for it.

The JSON's cells are HTML fragments (`<span class="center">08-03-2026</span>`),
so every value is tag-stripped on the way in. Email and Phone come through
clean, and the phone already arrives formatted `(817) 600-2840` — which is the
dominant style on the Mobrium List, so nothing has to be re-formatted.

A NAME MISS HERE IS NOT EVIDENCE OF ANYTHING. Several people who are plainly
working (Andrew Sanborn, Deavion Allen) are in none of the four rosters, and
someone the tracker says was terminated (Mustafa Alzaidy) is in none of them
either — the office's OwnerVille records don't line up 1:1 with the board. So
this module is a CONTACT LOOKUP only: presence in `activeReps` is allowed to
VETO a removal (it proves a rehire), absence is never allowed to cause one.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlencode

V2_URL = "https://v2.ownerville.com/index.cfm"
ENDPOINT = "https://v2.ownerville.com/components/users.cfc"

# The column list the page itself posts, in order. Sent verbatim: the endpoint
# echoes DataTables' contract and sorts by `sortColumnName`, so a short or
# reordered list changes what comes back.
COLUMNS = ["personchecked", "personpk", "fname", "lname", "repnamelink",
           "moduleAccess", "email", "phone", "fechabob", "retireddate",
           "status", "profile", "action"]

# The four toggle buttons on p=20. 'active' is the working roster; 'lead' and
# 'admin' are small and hold owners/leaders who never appear under 'active'.
ROSTERS = {"active": "activeReps", "lead": "leadReps", "admin": "adminReps"}
INACTIVE = "inactiveReps"

PAGE_SIZE = 2000                 # the endpoint caps a response near 2000 rows
_TAG = re.compile(r"<[^>]+>")
_RQST = re.compile(r"rqst=([A-Za-z0-9_-]+)")


class OwnervilleError(RuntimeError):
    """The session is gone or the endpoint stopped answering. Raised rather than
    returning an empty directory — an empty directory would look exactly like
    'nobody has a phone number' and quietly write 12 blank rows."""


@dataclass(frozen=True)
class Rep:
    first: str
    last: str
    email: str
    phone: str
    start: str
    retired: str
    roster: str          # 'active' | 'lead' | 'admin' | 'inactive'

    @property
    def full(self) -> str:
        return f"{self.first} {self.last}".strip()

    @property
    def working(self) -> bool:
        return self.roster in ROSTERS


# Parenthetical tags the board and OwnerVille both sprinkle on names — week
# markers, '(NC)' for a new captain, and so on. They are noise for matching AND
# for writing, so they come off in both places.
_PAREN = re.compile(r"\([^)]*\)")


def norm_name(s) -> str:
    """Fold a name to compare it. Drops parentheticals, punctuation, digits and
    the non-breaking spaces pasted names carry."""
    s = _PAREN.sub(" ", str(s or "").replace("\xa0", " ").replace("\t", " ").lower())
    return " ".join(re.sub(r"[^a-z ]+", " ", s).split())


def name_tokens(s) -> List[str]:
    """Every word a name answers to, INCLUDING what's in parentheses.

    'Qilu(Timothy) Zhao' -> ['qilu', 'timothy', 'zhao']. The parenthetical is
    dropped from the written name but kept here, because it is often the name
    the person's own email is built from (timothy54188@gmail.com).
    """
    s = str(s or "").replace("\xa0", " ").lower()
    return [t for t in re.sub(r"[^a-z ]+", " ", s).split() if t]


def _clean(value) -> str:
    """A JSON cell -> plain text. The endpoint wraps most values in markup."""
    return " ".join(_TAG.sub(" ", str(value or "")).split())


def _payload(rqst: str, rep_type: str, start: int, length: int) -> str:
    extra = {
        "draw": 1, "length": length, "start": start, "search": "",
        "sortDirection": "asc", "sortColumnNumber": 3, "sortColumnName": "lname",
        "columns": [{"data": c, "name": "", "searchable": True, "orderable": True,
                     "search": {"value": "", "regex": False}} for c in COLUMNS],
    }
    return urlencode({"extraParams": json.dumps(extra), "method": "getRepList",
                      "rqst": rqst, "repType": rep_type})


def _post(page, rqst: str, rep_type: str, start: int, length: int) -> dict:
    resp = page.request.post(
        ENDPOINT, data=_payload(rqst, rep_type, start, length),
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "X-Requested-With": "XMLHttpRequest"})
    if resp.status != 200:
        raise OwnervilleError(
            f"getRepList({rep_type}) answered HTTP {resp.status} — the "
            "OwnerVille session is probably stale on this machine.")
    body = resp.text()
    try:
        return json.loads(body)
    except ValueError:
        # An expired session serves the login page with a 200.
        raise OwnervilleError(
            f"getRepList({rep_type}) didn't answer JSON — session likely "
            f"expired. First 200 chars: {body[:200]!r}") from None


def _rows(page, rqst: str, rep_type: str, roster: str, *, paged: bool,
          logfn) -> List[Rep]:
    out: List[Rep] = []
    start = 0
    while True:
        data = _post(page, rqst, rep_type, start, PAGE_SIZE)
        chunk = data.get("data") or []
        total = int(data.get("recordsTotal") or 0)
        for d in chunk:
            out.append(Rep(
                first=_clean(d.get("fname")), last=_clean(d.get("lname")),
                email=_clean(d.get("email")), phone=_clean(d.get("phone")),
                start=_clean(d.get("fechabob")), retired=_clean(d.get("retireddate")),
                roster=roster))
        start += len(chunk)
        if not paged or not chunk or start >= total:
            logfn(f"  ownerville {rep_type}: {len(out)} of {total}")
            if start < total:
                # Never silently short a roster — a partial 'active' list would
                # turn working reps into removal candidates.
                raise OwnervilleError(
                    f"only got {start} of {total} {rep_type} rows")
            return out


class Directory:
    """Everyone OwnerVille knows, indexed by folded name.

    A name can legitimately map to more than one record (a rehire has an old
    inactive row and a new active one), so lookups keep the WORKING record when
    there is one — that is the row whose email and phone are current.
    """

    def __init__(self, reps: Iterable[Rep]):
        self.reps: List[Rep] = list(reps)
        self._by_name: Dict[str, List[Rep]] = {}
        for r in self.reps:
            self._by_name.setdefault(norm_name(r.full), []).append(r)

    def find(self, name: str) -> Optional[Rep]:
        hits = self._by_name.get(norm_name(name))
        if not hits:
            return None
        working = [r for r in hits if r.working]
        pool = working or hits
        # Prefer a record that actually carries contact details.
        with_contact = [r for r in pool if r.phone or r.email]
        return (with_contact or pool)[0]

    def is_working(self, name: str) -> bool:
        """True when OwnerVille still lists this person on a live roster.

        This is the ONLY thing absence-vs-presence is trusted for, and only in
        one direction: True vetoes a removal, False proves nothing.
        """
        return any(r.working for r in self._by_name.get(norm_name(name), ()))

    def __len__(self) -> int:
        return len(self.reps)


def load(*, include_inactive: bool = False, headless: bool = True,
         verbose: bool = False, logfn=print) -> Directory:
    """Open an OwnerVille session and read the rep rosters.

    `include_inactive` pages through the 10k-row retired list. Off by default:
    it costs five extra round-trips and this module never needs it (a removal is
    decided by the tracker tab, not by OwnerVille). It's there for `--audit`.
    """
    from automations.shared import tableau_patchright as tp

    reps: List[Rep] = []
    with tp.ownerville_session(headless=headless, verbose=verbose) as page:
        page.goto(V2_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(6_000)
        # v2 mints the request token off the login cookie; every call needs it.
        m = _RQST.search(page.url or "")
        if not m:
            href = page.evaluate(
                "() => { const a=[...document.querySelectorAll('a')]"
                ".find(x=>/rqst=/.test(x.getAttribute('href')||'')); "
                "return a ? a.getAttribute('href') : ''; }")
            m = _RQST.search(href or "")
        if not m:
            raise OwnervilleError(
                "no rqst token on v2.ownerville.com — the saved session isn't "
                "live on this machine. Re-export it (see the session runbook); "
                "an unattended re-login can't clear Cloudflare.")
        rqst = m.group(1)

        for roster, rep_type in ROSTERS.items():
            reps += _rows(page, rqst, rep_type, roster, paged=False, logfn=logfn)
        if include_inactive:
            reps += _rows(page, rqst, INACTIVE, "inactive", paged=True, logfn=logfn)

    return Directory(reps)
