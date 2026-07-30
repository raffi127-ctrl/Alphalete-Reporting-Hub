"""Where each captainship report's recipients come from.

WHY THIS EXISTS. The 12 lists were copied into `config.RECIPIENTS` on
2026-07-27 (commit c755a716) — not by design, but as a side effect of the CID
fix: until then Eve opened each draft in Gmail and picked the addresses by
hand, and once a human could no longer touch the draft (opening it in compose
strips the inline images out of what actually goes out), the addresses had to
live somewhere the code could read. They were pasted verbatim from what she
used to type. The cost showed up 2026-07-30: Khalil's address carried a
one-letter typo for days, bouncing every scheduled send, invisible to anyone
editing Gmail.

So the list moves to a Gmail CONTACT GROUP per captain, expanded at SEND time —
exactly what the Org Sales Board email and the Override Bulletin already do
(`shared.contacts_auth.expand_groups`, account alphaletereporting@gmail.com).
Eve edits the group in Contacts; the next send picks it up with no code change.

FALLBACK. A captain whose group is missing, empty, or unreadable falls back to
`config.RECIPIENTS[key]` and says so LOUDLY in the log. Rationale: a report
that goes to the last known-good list beats a report that goes nowhere, and the
review gate still holds every send until a human approves it. The warning is
the thing to watch — a silent fallback is how the Khalil typo survived.

    from automations.captainship_drafts import distro
    addrs, source = distro.recipients_for("sahil")   # source: 'group' | 'code'
"""
from __future__ import annotations

from typing import List, Tuple

# captain slug -> the EXACT contact-group name in alphaletereporting's Contacts.
# Eve already keeps group labels there, so this maps to HER names rather than
# inventing new ones. Anything not listed falls back to the derived
# 'Captainship - <Display>' form.
#
# To fill / correct this, list what actually exists:
#     python -m automations.shared.contacts_auth --list-groups
# then check the wiring end-to-end without sending anything:
#     python -m automations.captainship_drafts.run --distro-check
#
# Matching is case- and spacing-insensitive (contacts_auth._norm), but the
# WORDS have to match — 'Sahil Team' will not find 'Sahil's Team'.
GROUPS: dict = {
    # Verified against --list-groups on 2026-07-30. Note the three that do NOT
    # follow the "<Name>'s Captainship" pattern, and the apostrophe in "Luis'".
    #
    # ⚠ "Raf's Captain Team" and "Carlos' Captain Team" are SHARED with the Org
    # Sales Board email (org_sales_board.screenshot_email.DISTRO_GROUPS) — a
    # person added there lands on BOTH that captain's report and the org board.
    # That is how they're already set up; keep it in mind before editing them.
    "rafael": "Raf's Captain Team",
    "wayne":  "Wayne's Captain Team",
    "starr":  "Starr's Captainship",
    "chan":   "Chan's Captainship",
    "tony":   "Tony's Captainship",
    "sahil":  "Sahil's Captainship",
    "carlos": "Carlos' Captain Team",
    "eveliz": "Eveliz's Captainship",
    "luis":   "Luis' Captainship",
    "khalil": "Khalil's Captainship",
    "colten": "Colten's Captainship",
    "jairo":  "Jairo's Captainship",
}

GROUP_PREFIX = "Captainship - "


def group_name(key: str) -> str:
    """Contacts group for a captain slug — the mapped name, else
    'Captainship - <Display>'."""
    from automations.captainship_drafts import config
    if key in GROUPS:
        return GROUPS[key]
    cap = config.BY_KEY.get(key)
    return f"{GROUP_PREFIX}{cap.display_name if cap else key.title()}"


def code_list(key: str) -> List[str]:
    """The hardcoded fallback list for a captain."""
    from automations.captainship_drafts import config
    return list(config.RECIPIENTS.get(key, []))


def _norm(addrs) -> List[str]:
    """Lowercase + de-dupe, preserving order. Gmail addresses are
    case-insensitive, and a group can hold the same person twice."""
    seen, out = set(), []
    for a in addrs:
        a = (a or "").strip()
        if not a:
            continue
        if a.lower() in seen:
            continue
        seen.add(a.lower())
        out.append(a)
    return out


def recipients_for(key: str, *, logfn=print) -> Tuple[List[str], str]:
    """(addresses, source) for one captain. source is 'group' or 'code'.

    Never raises: an auth failure here would take down a send that has already
    been reviewed and approved, so it degrades to the code list instead.
    """
    name = group_name(key)
    try:
        from automations.shared.contacts_auth import expand_groups
        emails, missing = expand_groups([name])
    except Exception as e:                       # noqa: BLE001 — see docstring
        logfn(f"  ⚠ {key}: couldn't read Contacts ({type(e).__name__}: {e}) — "
              f"falling back to config.RECIPIENTS[{key!r}]")
        return _norm(code_list(key)), "code"

    if missing or not emails:
        why = "not found" if missing else "is empty"
        logfn(f"  ⚠ {key}: contacts group {name!r} {why} — falling back to "
              f"config.RECIPIENTS[{key!r}]. Create/fill it in Contacts "
              f"(alphaletereporting@gmail.com) to manage this list from Gmail.")
        return _norm(code_list(key)), "code"

    return _norm(emails), "group"


def to_header(key: str, *, logfn=print) -> str:
    """The comma-joined To header for a captain."""
    addrs, _ = recipients_for(key, logfn=logfn)
    return ", ".join(addrs)


def diff_report(keys=None, *, logfn=print) -> int:
    """Print group-vs-code for each captain. Returns the number of captains
    whose live group differs from the hardcoded list (0 = in sync).

    This is the check to run after editing a group in Contacts — it answers
    "will tomorrow's send actually go where I think it does?" without sending.
    """
    from automations.captainship_drafts import config
    keys = list(keys or [c.key for c in config.CAPTAINS])
    drifted = 0
    for key in keys:
        addrs, source = recipients_for(key, logfn=lambda *_: None)
        code = _norm(code_list(key))
        if source == "code":
            logfn(f"  {key:<8} group {group_name(key)!r}: MISSING — using the "
                  f"{len(code)} address(es) in config.py")
            continue
        only_group = [a for a in addrs if a.lower() not in {c.lower() for c in code}]
        only_code = [c for c in code if c.lower() not in {a.lower() for a in addrs}]
        if not only_group and not only_code:
            logfn(f"  {key:<8} group: {len(addrs)} address(es), matches config.py")
            continue
        drifted += 1
        logfn(f"  {key:<8} group: {len(addrs)} address(es) — DIFFERS from config.py")
        for a in only_group:
            logfn(f"             + only in the group: {a}")
        for c in only_code:
            logfn(f"             - only in config.py: {c}")
    return drifted
