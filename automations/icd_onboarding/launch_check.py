"""Is this office actually set up? Run it BEFORE the office goes live.

    python -m automations.icd_onboarding.launch_check --office raf

Megan, 2026-11-15: *"we need to make sure that it's set up correctly for that
ICD when we launch."*

WHY THIS EXISTS AS ONE COMMAND. Every setting below already has a careful
check of its own at the moment it is needed -- Apex holds a person back when
the office has no Rate of Pay, the OwnerVille read skips an office with no
`ov_program` rather than guessing at Alphalete's, the seed needs an AppStream
id. Each of those is right, and each of them finds out TOO LATE: on the
morning somebody's first new start is sitting in the classroom, one step at a
time, as a line in a log nobody is reading. By then the fix takes a day it
does not have.

So this asks every one of those questions at once, on a day when the answer
is cheap, and it asks them the same way the real code will: by calling the
same readers, not by re-implementing them. A check that agrees with itself and
disagrees with the thing it is checking is worse than no check.

READ ONLY. It opens nothing, writes nothing, sends nothing and signs nothing
in. Everything here is a config read or a Sheets read.

WHAT IT DELIBERATELY DOES NOT DO: pass an office by filling anything in.
A blank Rate of Pay is a question for the ICD, and the one thing that must
never happen is this quietly writing Alphalete's $10.00 into somebody else's
payroll record because that made the check go green.
"""
from __future__ import annotations

import argparse
import sys
from typing import Callable, List, NamedTuple, Optional


class Check(NamedTuple):
    name: str
    ok: bool
    said: str          # what we found, in its own words
    fix: str           # what to do when it is not ok. "" when ok.
    blocks: str        # what stops working while it is missing


def _office(key: str):
    from automations.office_admin import config as OC
    return OC.office(key)


def check_ov_program(key: str) -> Check:
    o = _office(key)
    said = (getattr(o, "ov_program", "") or "").strip() if o else ""
    return Check(
        "OwnerVille programme", bool(said), said or "not set",
        "Open OwnerVille's campaign dropdown on this office's login and add "
        "the exact option text to OFFICES[%r].ov_program in "
        "automations/office_admin/config.py." % key,
        "the five OwnerVille columns and the Owner Submit press. A wrong or "
        "missing one reads an EMPTY table, which looks exactly like nobody "
        "having done anything.")


def check_appstream_id(key: str) -> Check:
    o = _office(key)
    said = (getattr(o, "appstream_id", "") or "").strip() if o else ""
    return Check(
        "ApplicantStream office id", bool(said), said or "not set",
        "Add it to OFFICES[%r].appstream_id." % key,
        "the weekly seed — nobody appears on the board at all.")


def check_rate_of_pay(key: str) -> Check:
    try:
        from automations.icd_onboarding import office_steps as OS
        said = OS.rate_of_pay(key)
    except Exception as e:                                  # noqa: BLE001
        return Check("Rate of Pay", False, "could not read Office Settings "
                     "(%s)" % type(e).__name__,
                     "Check the relay workbook is reachable.",
                     "Apex — every new start is held back.")
    return Check(
        "Rate of Pay", bool(said), ("$%s/hr" % said) if said else "nobody has "
        "been asked",
        "Ask the ICD what they pay per hour and put it in the 'Rate of Pay' "
        "column of the relay workbook's 'Office Settings' tab, on this "
        "office's row.",
        "Apex. Every new start is held back with 'this office has no Rate of "
        "Pay on its enrolment' — correctly, because typing Alphalete's $10.00 "
        "onto somebody else's payroll record is the one error nobody would "
        "see.")


def check_blueink(key: str) -> Check:
    """Whether this office does Blue Ink at all, and whether it could."""
    try:
        from automations.icd_onboarding import office_steps as OS
        skipped = set(OS.skipped_for(key) or ())
    except Exception:                                       # noqa: BLE001
        skipped = set()
    if "Blue Ink" in skipped:
        return Check("Blue Ink", True, "this office does not do Blue Ink "
                     "(set on Office Settings)", "",
                     "nothing — the board shows n/a rather than an open step.")
    from automations.blueink_docs import config as BC
    theirs = BC.ECO_CREDS_PATH.exists()
    # ALPHALETE'S OWN MACHINES READ THE REPO COPY and always have, so a repo
    # key is a pass for Alphalete and NOT for an ICD: an ICD whose machine
    # falls back to the repo copy is sending its new starts' documents out of
    # Alphalete's Blue Ink account, which is the whole reason each ICD got
    # their own on 2026-11-09.
    is_alphalete = str(key).strip().lower() in ("raf", "alphalete", "")
    repo = (BC.REPO_ROOT / "blueink-creds.json").exists()
    ok = theirs or (is_alphalete and repo)
    if theirs:
        said = "this office's own key is on this machine"
    elif is_alphalete and repo:
        said = "Alphalete's repo key (correct for Alphalete)"
    elif repo:
        said = "ONLY Alphalete's repo key — this office would send from "\
               "Alphalete's account"
    else:
        said = "no key at %s" % BC.ECO_CREDS_PATH
    return Check(
        "Blue Ink account", ok, said,
        "On the OFFICE'S OWN computer, put their Blue Ink API key and "
        "envelope template id in %s. Never in the repo: it is public, and a "
        "`git pull` destroys anything parked inside it."
        % BC.ECO_CREDS_PATH,
        "the Blue Ink send, and with it the Blue Ink column and the packet "
        "the Apex fill reads its data out of. Worse when a key exists but is "
        "the wrong office's: the send SUCCEEDS, from somebody else's "
        "account.")


def check_blueink_wording(key: str) -> Check:
    """WHICH OFFICE'S NAME a new start would see on the email.

    Always 'ok' -- it is never missing, only possibly wrong -- but printed,
    because the one way this goes bad is silently: a new start opening an
    email that names a different company has, as far as they can tell, been
    sent somebody else's paperwork, on the first thing we ever send them.
    """
    from automations.blueink_docs import config as BC
    name = BC.office_name(key)
    generic = name == BC.DEFAULT_OFFICE_NAME and key.lower() not in (
        "raf", "alphalete", "")
    return Check(
        "Blue Ink email wording", not generic,
        "subject reads %r" % BC.email_subject(key),
        "This office has no `office_label` on its ECO sign-up, so the email "
        "falls back to Alphalete's name. Set their label on the sign-up tab.",
        "nothing technical — but their new start is welcomed by the wrong "
        "company.")


def check_board(key: str) -> Check:
    """This week's tab, reached the one way that knows about a per-week book.

    `open_board(workbook_for(...))` is the OLD stacked tab, and an office with
    a book of their own has a tab per week -- so this reported "workbook
    found, no tab yet" about a board with 32 people on it, and a launch check
    that cannot see the board is worse than no check (2026-11-24).
    """
    import datetime as dt
    try:
        from automations.icd_onboarding import sheet as S
        from automations.shared.onboarding_week import week_start_of
        week = week_start_of(dt.date.today())
        ws = S.board_for(key, week, create=False)
    except Exception as e:                                  # noqa: BLE001
        return Check("Onboarding board", False,
                     "%s: %s" % (type(e).__name__, str(e)[:120]),
                     "The office needs a metrics workbook in "
                     "automations/office_metrics/offices.py.",
                     "everything. There is nowhere to write.")
    if ws is None:
        return Check("Onboarding board", False, "workbook found, no tab yet",
                     "The first seed creates it; nothing to do by hand.",
                     "nothing yet.")
    try:
        head = [str(h).strip() for h in (S._values(ws)[S.HEADER_ROW - 1] or [])]
    except Exception:                                       # noqa: BLE001
        head = []
    from automations.icd_onboarding import board as B
    missing = [c for c in list(B.COLUMNS) + list(S.PAST_THE_CHART)
               if c not in head]
    return Check(
        "Onboarding board", not missing,
        "tab present, %d columns" % len(head) if not missing
        else "missing: %s" % ", ".join(missing),
        "A live run of any step calls ensure_columns and appends them.",
        "whichever columns are missing — a removal with no 'Removed Because' "
        "column records the date and loses the reason.")


def check_alert_channel(key: str) -> Check:
    o = _office(key)
    said = (getattr(o, "channel", "") or "").strip() if o else ""
    return Check(
        "Office Slack channel", bool(said), said or "not set",
        "Add the channel id to OFFICES[%r].channel." % key,
        "the 6pm 'not sent yet' alert. Everything else still runs.")


CHECKS: List[Callable] = [check_appstream_id, check_ov_program,
                          check_rate_of_pay, check_blueink,
                          check_blueink_wording, check_board,
                          check_alert_channel]


def run(office_key: str, log=print) -> List[Check]:
    out = []
    for fn in CHECKS:
        try:
            got = fn(office_key)
        except Exception as e:      # noqa: BLE001 — one check, not the run
            got = Check(fn.__name__, False, "check itself failed (%s)"
                        % type(e).__name__, "Look at %s." % fn.__name__,
                        "unknown — this check could not answer.")
        out.append(got)
        log("  %s %-26s %s" % ("✓" if got.ok else "✗", got.name, got.said))
    bad = [c for c in out if not c.ok]
    if not bad:
        log("\n%s is ready to launch." % office_key)
        return out
    log("\n%d thing%s to sort before %s launches:"
        % (len(bad), "" if len(bad) == 1 else "s", office_key))
    for c in bad:
        log("\n  %s" % c.name)
        log("    found : %s" % c.said)
        log("    breaks: %s" % c.blocks)
        log("    fix   : %s" % c.fix)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--office", required=True, help="office key, e.g. raf")
    a = ap.parse_args(argv)
    print("launch check — %s\n" % a.office)
    got = run(a.office)
    # 0 only when everything passed, so a scheduled caller can trust it.
    return 0 if all(c.ok for c in got) else 1


if __name__ == "__main__":
    sys.exit(main())
