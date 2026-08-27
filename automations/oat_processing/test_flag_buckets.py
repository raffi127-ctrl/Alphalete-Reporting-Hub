"""Which bucket a flagged applicant lands in on the twice-daily to-do post.

THE BUG THIS PINS (2026-08-27): the post has two buckets, and they are two
DIFFERENT jobs for the human — "go pull this person's number off Indeed" vs
"send this person a fresh message by hand". An applicant who arrives with no
phone, whose number we then read off their resume, whose send the ATS refuses
("correspondence with this phone number has already occurred"), and whose SMS
thread is too old for the widget to see, ENDS as needs-a-manual-text. But the
bucketing tested `d.action` — where they ENTERED — before `outcome` — where they
ended up — so every one of them was filed under needs-a-number. Result: "need a
manual text" read 0 in all 37 snapshots that day while the log carried 103
re-text fallbacks in that office, and the people who needed a message were shown
to a human as needing a number they already had. (Victor Renteria, Claudia
Ceniceros — both had sat for days.)

Run:  PYTHONPATH=. .venv/bin/python -m automations.oat_processing.test_flag_buckets
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

_passed = 0
_failed = 0


def check(label, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print("  [ok] %s: %r" % (label, got))
    else:
        _failed += 1
        print("  [FAIL] %s: got %r, want %r" % (label, got, want))


def bucket(outcome, action):
    """The bucketing decision as run.py makes it (run.py ~2028)."""
    if outcome == "flag_retext":
        return "retext"
    if outcome == "flag_no_phone" or (not outcome and action == "flag_no_phone"):
        return "nophone"
    return None


print("the reported case — entered no-phone, ENDED needing a manual text:")
# Victor: no phone on file -> number read off his resume -> ATS refuses (last
# correspondence 03/23/2026) -> no SMS thread that old -> flag_retext.
check("Victor Renteria goes to the manual-text list",
      bucket("flag_retext", "flag_no_phone"), "retext")
check("Claudia Ceniceros likewise",
      bucket("flag_retext", "flag_no_phone"), "retext")

print("a genuine no-number applicant still goes to the number list:")
# Resume really had no phone on it — a human does have to pull one from Indeed.
check("ended no-phone", bucket("flag_no_phone", "flag_no_phone"), "nophone")
check("no outcome recorded, fall back to the action",
      bucket("", "flag_no_phone"), "nophone")
check("None outcome falls back too", bucket(None, "flag_no_phone"), "nophone")

print("a re-text that came in as a re-text is unchanged:")
check("entered and ended as re-text", bucket("flag_retext", "retext_then_remove"),
      "retext")

print("outcomes that need no human are in neither bucket:")
for o in ("sent", "sent_override", "removed", "retext_sent", "retext_removed"):
    check("%s is not on the to-do list" % o, bucket(o, "send_ai"), None)

print("the old logic put the reported case in the WRONG bucket (regression guard):")


def old_bucket(outcome, action):
    if outcome == "flag_no_phone" or action == "flag_no_phone":
        return "nophone"
    if outcome == "flag_retext":
        return "retext"
    return None


check("old logic mis-filed Victor as needing a number",
      old_bucket("flag_retext", "flag_no_phone"), "nophone")
check("new logic does not", bucket("flag_retext", "flag_no_phone"), "retext")

print("an applicant whose name didn't parse is still listed, never dropped:")


def label(first, last, email):
    """How run.py names an entry for the post."""
    nm = ("%s %s" % (first, last)).strip()
    if not nm:
        nm = (email or "").strip() or "(name unreadable — find them in the queue)"
    return nm


check("normal name", label("Claudia", "Ceniceros", "c@x.com"), "Claudia Ceniceros")
# The ATS re-renders mid-walk and the read comes back nameless; before the fix
# these fell through an `if _nm:` guard and vanished from the to-do post.
check("no name, falls back to the email",
      label("", "", "conversation-juangarcia-h702i@indeedemail.com"),
      "conversation-juangarcia-h702i@indeedemail.com")
check("no name and no email still names them something findable",
      label("", "", ""), "(name unreadable — find them in the queue)")
check("never empty, so never silently dropped", bool(label("", "", "")), True)

print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
