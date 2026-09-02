"""Find an enrolling office in OwnerVille BY ITS ACCOUNT NUMBER, and settle the
name so impersonation can find it afterwards.

WHY THIS EXISTS. Impersonation matches on an EXACT name string: the search in
`focus_office_att.run_all_owners._find_owner_and_impersonate` filters the Office
Access table and accepts a row only when `row[2] == candidate`, with the ICD
alias sheet supplying the candidates. So every spelling drift is a dead
enrollment — "Calvin Rivera" for OwnerVille's "Calvin RIBERA", "Kash Rai" for
"Akashdeep Rai" — and the only cure is a human noticing and adding an alias row.
That is the step this form exists to delete.

Meanwhile the form REQUIRES the owner's OwnerVille account number and nothing
has ever read it. The Office Access table's first column IS that number
(`knocks_access_watch.audit.classify` reads `row[0]` as the office number for
exactly this reason — an owner can hold two offices and have access to only one,
Wayne Rude's 19910 vs 21570). A number is unambiguous where a name is not.

So: match on the number, read OwnerVille's own spelling off the row it lands on,
and if that differs from what the owner typed, write it to the ICD Aliases sheet
([[feedback_alias_list]] — name-spelling mismatches go there, never into a
per-report patch). Every other report inherits the fix.

The row also carries its ACTION cell, which is how "we have no access yet" stops
looking like "we cannot find you": a listed office whose action still reads
"Request Sent" is waiting on the owner to accept, which is a retry, not a
failure.

Pure functions here take rows; only `resolve()` touches a browser.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

# What the Office Access row says about this office.
GRANTED = "granted"    # impersonation should work right now
PENDING = "pending"    # listed, but the owner has not accepted the request yet
MISSING = "missing"    # not on the list at all under number or any spelling

# Column positions in an Office Access row, named once. Same reading
# knocks_access_watch.audit.classify does — it treats row[0] as the office
# number, row[1] as the company and row[2] as the owner, and the two must not
# drift apart or the audit and the enrollment would disagree about the table.
COL_ACCOUNT = 0
COL_COMPANY = 1
COL_OWNER = 2


def normalize_account(value) -> str:
    """'#22162' / ' 22162 ' / 'acct 22162' / '22162.0' -> '22162'.

    The FIRST run of digits, not every digit in the string. Stripping all
    non-digits turns the float a spreadsheet hands back — `22162.0` — into
    `221620`, which matches no office at all and would have read as "you are
    not on the access list". Owners type this field by hand and it travels
    through a Sheet on the way here, so both are ordinary.
    """
    m = re.search(r"\d+", str(value or ""))
    return m.group(0) if m else ""


def _norm(value) -> str:
    return " ".join(str(value or "").split()).lower()


def account_of(row: Sequence) -> str:
    return normalize_account(row[COL_ACCOUNT] if len(row) > COL_ACCOUNT else "")


def owner_of(row: Sequence) -> str:
    return str(row[COL_OWNER] if len(row) > COL_OWNER else "").strip()


def company_of(row: Sequence) -> str:
    return str(row[COL_COMPANY] if len(row) > COL_COMPANY else "").strip()


def access_state(row: Sequence) -> str:
    """GRANTED or PENDING, off the row's own action cell.

    A blank action means granted — that is how the audit reads it, and how the
    2026-08-25 hint line spells it ("granted" when the last cell is empty).
    """
    action = str(row[-1] if len(row) else "").strip()
    return PENDING if re.search(r"request", action, re.I) else GRANTED


def match_row(rows: "List[Sequence]", *, account: str = "",
              names: "Sequence[str]" = ()) -> "Tuple[Optional[Sequence], str]":
    """The office's row, and HOW it was found. -> (row|None, "account"|"name"|"")

    ACCOUNT FIRST, on purpose. It is the field that cannot be spelled two ways,
    and it is the one the form makes required. Names are the fallback so an
    office whose number was mistyped still resolves the way it always did —
    this can only find more offices than before, never fewer.
    """
    want = normalize_account(account)
    if want:
        for row in rows:
            if account_of(row) == want:
                return row, "account"
    wanted_names = {_norm(n) for n in names if _norm(n)}
    if wanted_names:
        for row in rows:
            if _norm(owner_of(row)) in wanted_names:
                return row, "name"
    return None, ""


def near_rows(rows: "List[Sequence]", name: str,
              limit: int = 4) -> "List[str]":
    """Rows whose owner text carries this surname — the actionable half of a
    miss. Same hint shape the access audit posts, including the office number,
    because an owner can hold two offices and only one of them be granted."""
    surname = (str(name or "").split() or [""])[-1].lower()
    if len(surname) < 3:
        return []
    out = []
    for row in rows:
        if surname not in _norm(owner_of(row)):
            continue
        out.append("%s (#%s, %s)" % (owner_of(row), account_of(row) or "?",
                                     access_state(row)))
    return out[:limit]


def name_candidates(rec, aliases: "Optional[Dict]" = None) -> "List[str]":
    """Every spelling we would search OwnerVille for: the office name the record
    resolves through, the owner's own name, and each of their known aliases."""
    out: List[str] = []
    for base in (rec.office_name(), rec.owner, rec.knocks_office):
        base = (base or "").strip()
        if base and base not in out:
            out.append(base)
    if aliases is None:
        try:
            from automations.focus_office_att.aliases import load_aliases
            aliases = load_aliases()
        except Exception:                            # noqa: BLE001
            aliases = {}
    try:
        from automations.focus_office_att.aliases import get_search_candidates
        for base in list(out):
            for cand in get_search_candidates(base, aliases or {}):
                if cand and cand not in out:
                    out.append(cand)
    except Exception:                                # noqa: BLE001
        pass
    return out


def alias_needed(rec, row: Sequence,
                 aliases: "Optional[Dict]" = None) -> "Optional[Tuple[str, str]]":
    """(canonical, alias) to write, or None when the search already finds it.

    Direction matches the rest of the repo: CANONICAL is the name this office is
    filed under here (what the owner typed, which becomes the office row's
    `name`), and the ALIAS is OwnerVille's own spelling — the same way
    `_find_owner_and_impersonate` saves one when a human answers its prompt.
    That is the direction impersonation reads: candidates are the canonical plus
    its aliases, and it is the ALIAS that has to match the OwnerVille row.
    """
    ov = owner_of(row)
    if not ov:
        return None
    if _norm(ov) in {_norm(c) for c in name_candidates(rec, aliases)}:
        return None
    return (rec.office_name(), ov)


def describe(row: Sequence, how: str) -> str:
    return "%s (#%s%s) — %s, found by %s" % (
        owner_of(row) or "?", account_of(row) or "?",
        ", " + company_of(row) if company_of(row) else "",
        access_state(row), how or "?")


def resolve(page, rec, *, save: bool = True) -> Dict:
    """Look this office up on an ALREADY-OPEN OwnerVille page and settle its
    name. -> a preflight-shaped {name, ok, note, state, row}.

    THE CALLER OWNS THE SESSION, and owns not being mid-impersonation: reading
    the Office Access table navigates to the site root to mint an `rqst`, which
    re-establishes the account's single session in MASTER mode. Doing that under
    a live capture silently drops it back onto the master office
    ([[reference_ownerville_session_killers]]). Preflight takes gap_alerts' pid
    lock for exactly this reason.
    """
    name = "OwnerVille office"
    try:
        from automations.knocks_access_watch.audit import read_office_access
        rows = read_office_access(page)
    except Exception as e:                           # noqa: BLE001
        return {"name": name, "ok": False, "state": "",
                "note": "couldn't read the Office Access table (%s: %s)"
                        % (type(e).__name__, str(e)[:180])}

    row, how = match_row(rows, account=rec.ov_account,
                         names=name_candidates(rec))
    if row is None:
        near = near_rows(rows, rec.owner)
        return {"name": name, "ok": False, "state": MISSING,
                "note": ("account #%s is not in Rafael's Office Access list "
                         "under any spelling we search for%s"
                         % (normalize_account(rec.ov_account) or "?",
                            (" — near matches: " + "; ".join(near))
                            if near else ""))}

    state = access_state(row)
    note = describe(row, how)

    # The alias is worth writing whether or not access is granted yet: it is
    # what makes the RETRY find them, and every other report benefits.
    pair = alias_needed(rec, row)
    if pair and save:
        try:
            from automations.focus_office_att.aliases import save_alias
            save_alias(pair[0], pair[1])
            note += "; filed alias %r -> %r" % (pair[1], pair[0])
        except Exception as e:                       # noqa: BLE001
            note += ("; couldn't file the alias %r -> %r (%s) — impersonation "
                     "will keep missing them until it is added by hand"
                     % (pair[1], pair[0], type(e).__name__))
    elif pair:
        note += "; would file alias %r -> %r" % (pair[1], pair[0])

    if state == PENDING:
        note += (" — the owner has NOT accepted the access request yet, so "
                 "nothing can be pulled. This retries on its own")
    return {"name": name, "ok": state == GRANTED, "state": state, "note": note}
