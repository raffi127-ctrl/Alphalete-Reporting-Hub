"""The board steps an office's OWN computer does, for itself.

Megan, 2026-11-24: *"we need it to work like lucy eco does"* -- so these are
not jobs handed out by a Lucy. They are features of the office's own agent, the
same shape as every other thing on that machine: `sara_read`, `box_read`,
`optix_read`, `resume_push`. Each reads the office's own source with the
office's own login, on the agent's tick, with nothing on screen.

    python -m automations.icd_onboarding.eco_steps          # one pass, dry
    python -m automations.icd_onboarding.eco_steps --write

WHY THIS FILE AND NOT `icd_onboarding.run`. That module is the HUB's runner and
cannot go on an office Mac: measured 2026-11-24, its import closure is one file
but its RUN closure reaches 90 Hub modules -- `presses` to OwnerVille's Hub
session, `sheet` to gspread. An office computer has no Google access at all.
This file holds only the steps that reach their source the ECO way, and it
grows one step at a time as each one's ECO reader lands; `run.py` delegates to
it, so there is ONE implementation of a step and not a Hub copy and an office
copy drifting apart.

THE BOARD IS REACHED THROUGH THE RELAY, always. `fillers.rows_anywhere` and
`fillers.apply_anywhere` already choose: gspread on a Lucy, the relay on an
office machine (`relay_board`). Nothing here knows the difference, which is
why the same step body is correct on both.

A STEP THAT CANNOT READ ITS SOURCE TICKS NOTHING AND SAYS SO. It never answers
"nobody" on a read that did not happen ([[feedback_empty_means_proven_zero]]):
a machine without the token for this office's reception account is not broken,
it is simply not the one that does that job, and a skipped pass must never be
mistaken for an office where nobody has been contacted.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import sys
from typing import Dict, List, Sequence, Tuple

from automations.icd_onboarding import board as B
from automations.icd_onboarding import fillers as F


def reception_account(office_key: str) -> str:
    """The office's OWN reception Gmail, off the second-round roster.

    Megan, 2026-11-11: "each ICD will have their own reception email" -- so
    this is a per-office login like OwnerVille or Blue Ink, not one account
    every office would have to be given a key to.

    ON THIS OFFICE'S OWN COMPUTER the roster is unreachable -- it is a Google
    Sheet -- so the address the ICD gave the installer
    (`icd_alerts.onboarding_setup.reception_email`) is the answer there. Asked
    of the machine FIRST, because a machine that has been told is never wrong
    about its own office, and the roster read costs a Sheets call.
    """
    try:
        from automations.icd_alerts import onboarding_setup as OS
        said = OS.reception_email()
        if said:
            return said
    except Exception:      # noqa: BLE001 -- not an ECO machine
        pass
    # THE ROSTER IS OURS, not theirs: it is a Google Sheet, so this half
    # runs on a Lucy and simply is not available on an office Mac. A
    # machine that has been told its own address never reaches it.
    try:
        from automations.icd_onboarding import run as R
        from automations.second_round_contacts import roster as SR
        want = str(R._appstream_id(office_key) or "").strip()
        if not want:
            return ""
        for o in SR.read():
            if want in [str(x).strip() for x in (o.offices or [o.office])]:
                return str(o.account or "").strip()
    except Exception:          # noqa: BLE001 -- no roster here
        return ""
    return ""


def contacts(office_key: str, week_start: dt.date, *,
             dry_run: bool = True, log=print) -> int:
    """Contact Added, read off the office's reception Google Contacts.

    Megan, 2026-11-09: "we need to connect to Eve's already built automation
    that's adding 2nd round contacts." Her job puts every second-round
    applicant into that owner's reception account; this asks the account
    whether the contact is there.

    IT ASKS THE ACCOUNT, NOT THE JOB'S NOTES. This used to read
    `second_round_contacts`'s state file, which records what the sync BELIEVES
    it did -- a different thing from what is in the account, and where they
    disagree the account is right. That file held 98 contacts and matched 0 of
    Raf's 21 for the week of 11/08, with no way to tell a sync that had not
    run from one whose notes were about other offices. A contact either exists
    or it does not.

    IT ALSO COVERS THE PEOPLE ADDED BEFORE THE BOARD EXISTED, which an
    as-it-happens tick cannot: somebody contacted at their second round three
    weeks ago is never re-added, so a tick that only fired on creation would
    leave them blank for ever. On the real OBCL Contact Added is true for
    nearly everybody, and that is why this is a LOOKUP.

    PHONE, THEN EMAIL. NEVER THE NAME. An applicant types their own name into
    ApplicantStream, so the two sides disagree over Mike/Michael, a middle
    name, a married name or an accent -- and a name match that is wrong ticks
    a step for somebody nobody ever rang. The ten digits of the phone are the
    same in both.

    SKIPPED, NOT FAILED, where this machine holds no token for that account --
    the Sterling inbox's rule. A box without the token is not broken; it is
    simply not the one that does this job. Nothing is ticked on the way past,
    so a skipped pass can never be mistaken for "nobody has been contacted"
    ([[feedback_empty_means_proven_zero]]).
    """
    from automations.second_round_contacts import contacts as K
    from automations.applicant_contacts.extract import phone10

    account = reception_account(office_key)
    if not account:
        log("  contacts: %s has no reception account on the second-round "
            "roster -- nothing to read" % office_key)
        return 0
    if not K.has_token(account):
        log("  contacts: no Contacts token for %s on this machine (%s) -- "
            "this runs where that token is. Nothing ticked."
            % (account, K.token_file(account)))
        return 0

    # THE BOARD FIRST, AND OFTEN NOTHING AFTER IT. Reading this account means
    # paging the WHOLE of it -- Alphalete's reception Gmail holds 16,000-odd
    # contacts (Megan, 2026-11-11: "ours will be much larger than anyone
    # else's"), which is 17 pages, 29 times a day on the half-hourly run. A
    # tick never comes off, so once everybody on the week is ticked the answer
    # cannot change and the whole read is wasted work.
    rows = F.rows_anywhere(office_key, week_start, log=log)
    live = [r for r in rows if not str(r.get(B.TERMINATED_AT) or "").strip()]
    want = [r for r in live if not str(r.get("Contact Added") or "").strip()]
    if not want:
        log("  contacts: all %d on the board are already ticked -- not reading "
            "%s" % (len(live), account))
        return 0

    try:
        svc = K.service(account)
        by_phone, by_email = K.existing_index(svc)
    except Exception as e:      # noqa: BLE001
        # An account that could not be READ is not an account with nobody in
        # it. Say so and tick nothing.
        log("  contacts: could not read %s: %s: %s -- nothing ticked"
            % (account, type(e).__name__, str(e)[:160]))
        return 0
    log("  contacts: %s holds %d contact(s) with a phone, %d with an email "
        "(looking for %d of %d)"
        % (account, len(by_phone), len(by_email), len(want), len(live)))

    verdicts = {}
    how = {"phone": 0, "email": 0}
    # only the ones still missing the tick -- the rest cannot change.
    for r in want:
        name = ("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip()
        ph = phone10(str(r.get("Phone") or ""))
        em = str(r.get("Email") or "").strip().lower()
        if ph and ph in by_phone:
            hit = "phone"
        elif em and em in by_email:
            hit = "email"
        else:
            continue
        how[hit] += 1
        verdicts[name] = {"Contact Added": True}
    if verdicts:
        log("    matched %d: %s"
            % (len(verdicts), ", ".join("%d by %s" % (v, k)
                                        for k, v in how.items() if v)))
    else:
        askable = sum(1 for r in want
                      if str(r.get("Phone") or "").strip()
                      or str(r.get("Email") or "").strip())
        log("    matched 0 of the %d still missing a tick (%d of them had a "
            "phone or an email to match on)" % (len(want), askable))
    return F.apply_anywhere(office_key, week_start, "contacts",
                            verdicts, dry_run=dry_run, log=log)


# --- ApplicantStream, on this office's own computer ---------------------------
@contextlib.contextmanager
def appstream_here(log=print):
    """An `ApplicantStream` driver bound to THIS office's own Chrome.

    WHY THIS EXISTS. `applicant_tracker.applicantstream.session` binds to the
    warm console `shared.tableau_patchright` keeps alive on OUR machines, and
    that module cannot ship -- it imports `recruiting_report.opt_phase` and
    the Hub behind it. The DRIVER can: measured 2026-11-24, the only
    `automations` import in applicantstream.py is inside `session()`, and the
    class itself needs nothing but a Playwright page.

    THE SAME CHROME THE PUSH USES (`resume_push`), on purpose and for the same
    reason `as_signin` gives: the session and the security check it passed are
    exactly what this reuses. A read proven in some other browser would prove
    nothing about that one -- and this office's AppStream login already lives
    there, which is the whole point of the step running here.

    BACKGROUND, ALWAYS. A scheduled read on somebody's office computer opens
    nothing they can see ([[feedback_eco_runs_in_background]]). `_connect`
    hides the window and keeps focus where it was; this is not in
    `icd_alerts.visible_windows` and must never be.

    It does NOT close the browser. Lucy's Chrome is shared with the push and
    the walk, and closing it from under them is how a run that worked takes
    the next one down.
    """
    from automations.applicant_tracker.applicantstream import (
        ApplicantStream, DEFAULT_TIMEOUT_MS, NAV_TIMEOUT_MS)
    from automations.icd_alerts import resume_push as RP
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:                 # noqa: F401 -- a box without patchright
        from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, ctx, page = RP._connect(p, background=True, url=RP.AS_BASE)
        if page is None:
            raise RuntimeError(
                "Lucy's Chrome would not open, so ApplicantStream was never "
                "read. Nothing was seeded.")
        app = ApplicantStream(headless=True)
        app.page = page
        try:
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            page.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        except Exception:               # noqa: BLE001 -- still runs without them
            pass
        # THE OFFICE SWITCHER IS THE PROOF, not a page that loaded. A logged-out
        # console answers every office select with a timeout, which reads as a
        # broken office instead of an expired login (applicantstream.session
        # checks the same thing, for the same reason).
        if page.locator("#searchMC").count() == 0:
            raise RuntimeError(
                "this computer's ApplicantStream session has gone -- the "
                "console came back without the office switcher, so no office "
                "could be selected. Sign in again with "
                "`python -m automations.icd_alerts.as_signin`.")
        app._capture_token()
        yield app

# THE STEPS THIS MACHINE CAN DO ITSELF, in the order a pass runs them.
#
# ONE ENTRY, ON PURPOSE. Contact Added is here first because both its halves
# already ship: the account is read with the office's OWN reception token
# (second_round_contacts.contacts) and the board is written through the relay.
# The rest -- the seed, the five OwnerVille columns, Blue Ink, Sterling, the
# Owner Submit press, the no-shows walk -- each need their Hub reader rebuilt
# the ECO way before they can join this list, and a step in this tuple that
# cannot run on an office Mac would be a pass that fails every hour.
STEPS: Sequence[Tuple[str, object]] = (("contacts", contacts),)


def run_once(office_key: str, week_start: dt.date, *, dry_run: bool = True,
             log=print) -> int:
    """Every step this machine can do, for one office and one week.

    ONE STEP NEVER COSTS THE OTHERS. An office needing two things done and
    getting one would look done, and the second would be found the slow way --
    the same rule `finish_setup` keeps for its own steps.
    """
    total = 0
    for name, fn in STEPS:
        try:
            total += int(fn(office_key, week_start, dry_run=dry_run, log=log) or 0)
        except Exception as e:      # noqa: BLE001 -- said in full, never swallowed
            log("  %s stopped: %s" % (name, str(e).strip() or type(e).__name__))
    return total


def offices() -> List[str]:
    """The offices this machine works, off its own ECO enrolment.

    `config.base_office_key` is the ONE definition of which office a campaign
    key belongs to: an office running AT&T and Box has one board, and a new
    start is on it whichever campaign hired them.
    """
    try:
        from automations.icd_alerts import config as C
        out = []
        for rec in C.enrollments():
            key = C.base_office_key(rec.get("office_key") or "")
            if key and key not in out:
                out.append(key)
        return out
    except Exception:               # noqa: BLE001 -- not an enrolled machine
        return []


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--office", action="append", default=[],
                    help="office key; default is this machine's own")
    ap.add_argument("--week", default=None, help="any date in the week (YYYY-MM-DD)")
    ap.add_argument("--only", action="append", default=[],
                    help="run only these steps")
    ap.add_argument("--write", action="store_true",
                    help="really tick the board (default is a dry run)")
    a = ap.parse_args(argv)

    day = dt.date.fromisoformat(a.week) if a.week else dt.date.today()
    week = B.week_start_of(day)
    keys = [str(k).strip().lower() for k in a.office] or offices()
    if not keys:
        print("this computer is not enrolled for an office.")
        return 1

    steps = [(n, f) for n, f in STEPS if not a.only or n in a.only]
    if a.only and not steps:
        print("no such step: %s (have: %s)"
              % (", ".join(a.only), ", ".join(n for n, _ in STEPS)))
        return 2

    total = 0
    for key in keys:
        print("%s · week of %s%s"
              % (key, B.week_label(week), "" if a.write else "  (DRY RUN)"))
        for name, fn in steps:
            try:
                total += int(fn(key, week, dry_run=not a.write, log=print) or 0)
            except Exception as e:  # noqa: BLE001
                print("  %s stopped: %s" % (name, str(e).strip() or type(e).__name__))
    print("%d cell(s)%s" % (total, "" if a.write else " would be written"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
