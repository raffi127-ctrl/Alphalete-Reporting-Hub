"""One typed text from Taylor's RingCentral line to ONE customer, by name.

Carlos 2026-11-15: "Text John saying, 'Hey John, do you need help activating
your line?'" -- a by-hand send for the follow-ups the review turns up.

    lucy rerun rc_send_text --customer "John Coward" --text "Hey John, ..."          # shows who and what, sends nothing
    lucy rerun rc_send_text --customer "John Coward" --text "Hey John, ..." --live   # sends

The number is the customer's MAIN contact in Taylor's book: the contact whose
name is exactly the customer's (the sync's "<Name> - Line N" contacts are the
lines, not the person). No contact, or more than one distinct person matching
the words, sends nothing and says so. --with-rep adds the rep's number (same
resolvers as the wrap-up) so it lands as the group thread. DRY RUN by default.
Python 3.9-safe.
"""
from __future__ import annotations

import argparse
from typing import Dict, List, Optional, Sequence

from automations.rc_contact_sync import config as C
from automations.rc_contact_sync import ringcentral as RC

REPORT_ID = "rc_send_text"


def main_contacts(book: Sequence[dict], words: Sequence[str]) -> Dict[str, List[str]]:
    """{contact name: [numbers]} for the people (not their "- Line N"
    contacts) whose name holds all the words."""
    from automations.rc_contact_sync import inbox
    out: Dict[str, List[str]] = {}
    for c in inbox.matching_contacts(list(book), list(words)):
        name = inbox._contact_name(c)
        if " - line" in name.lower():
            continue
        nums = inbox._contact_numbers(c)
        if nums:
            out.setdefault(" ".join(name.split()).title(), [])
            for n in nums:
                if n not in out[" ".join(name.split()).title()]:
                    out[" ".join(name.split()).title()].append(n)
    return out


def pick_number(found: Dict[str, List[str]]) -> Optional[str]:
    """The one number to text: exactly one person, their first number."""
    if len(found) != 1:
        return None
    nums = next(iter(found.values()))
    return nums[0] if nums else None


def run(customer: str, text: str, *, live: bool = False, rep: str = "", log=print) -> int:
    text = (text or "").strip()
    if not text:
        log("nothing to send: --text is empty")
        return 2
    creds = C.rc_creds()
    info = RC.token_info(creds)
    token = info["access_token"]
    RC.assert_identity(RC.identity(info), creds.get("expected_owner_id") or C.RC_OWNER_ID)
    book = RC.address_book(token, str(creds["contacts_extension_id"]))
    found = main_contacts(book, customer.split())
    for name, nums in found.items():
        log("contact: %s  %s" % (name, ", ".join(RC.e164(n) for n in nums)))
    number = pick_number(found)
    if not number:
        log("NOT SENT: %s" % ("no main contact matches %r in Taylor's book" % customer if not found
                              else "%d different people match %r -- name it more exactly" % (len(found), customer)))
        print("=== done ===", flush=True)
        return 1
    to = [number]
    if rep:
        from automations.rc_contact_sync import wrapup
        reps = wrapup.resolve_reps(book, [rep], log=log)
        if rep not in reps:
            log("NOT SENT: no number for rep %r" % rep)
            print("=== done ===", flush=True)
            return 1
        to.append(reps[rep])
    try:
        from_number = RC.sender_number(token)
    except RC.RCError:
        from automations.rc_contact_sync import wrapup
        from_number = wrapup.TAYLOR_SMS_NUMBER
    log("from %s (Taylor's line) to %s" % (from_number, ", ".join(RC.e164(n) for n in to)))
    log("text: %s" % text)
    if not live:
        log("DRY RUN -- nothing sent (pass --live)")
        print("=== done ===", flush=True)
        return 0
    res = RC.send_group_mms(token, from_number, to, text)
    log("SENT: message id %s, status %s" % (res.get("id"), res.get("messageStatus")))
    print("=== done ===", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rc_send_text",
                                 description="One typed text from Taylor's line to one customer (dry run by default).")
    ap.add_argument("--customer", required=True, help="the customer's name as in Taylor's contacts")
    ap.add_argument("--text", required=True, help="the message, exactly as it should read")
    ap.add_argument("--with-rep", default="", metavar="REP NAME", help="also include this rep (group thread)")
    ap.add_argument("--live", action="store_true", help="send it (default: show who and what only)")
    a = ap.parse_args(argv)
    return run(a.customer, a.text, live=a.live, rep=a.with_rep)


if __name__ == "__main__":
    import sys
    from automations.rc_contact_sync.unread_guard import guarded
    sys.exit(guarded(main))
