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
from automations.icd_onboarding import board as BB          # the moved seed's name for it
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

# --- THE SEED, AND THE WALK THAT SAYS WHO DID NOT COME -----------------------
#
# Moved here from `icd_onboarding.run` on 2026-11-24. Both read
# ApplicantStream, both are the OFFICE's own sources -- their recruiting
# calendar, their Retention Report, their login -- and `run.py` cannot ship:
# its siblings reach OwnerVille's Hub session and gspread. `run.seed`,
# `run.seed_names` and `run.from_no_shows` are thin delegates now, so there is
# ONE of each body and not a Hub copy drifting from an office copy.
#
# THE SESSION IS `sessions.appstream_anywhere`, so the same body reads the warm
# console on a Lucy and the office's own Chrome on an office machine. The board
# writes already went through `fillers.seed_anywhere` / `apply_anywhere`, which
# is gspread on a Lucy and the relay on an office box -- so nothing in here
# knows or cares which machine it is.

def _appstream_id(office_key: str) -> str:
    from automations.office_admin import config as OC
    o = OC.office(office_key)
    return (o.appstream_id if o else "") or ""


def _appstream_ids(office_key: str) -> List[str]:
    """Every ApplicantStream account whose new starts onboard in this office.

    The office's own first, then any funnel that onboards here -- a new launch
    recruits on its own account and its people land in the host's OwnerVille
    (config.Office.extra_appstream_ids). ONLY THE SEED uses this; everything
    keyed to the office itself still uses `_appstream_id`.
    """
    from automations.office_admin import config as OC
    o = OC.office(office_key)
    if not o:
        return []
    ids = [str(o.appstream_id or "").strip()]
    for extra in (getattr(o, "extra_appstream_ids", ()) or ()):
        got = _id_and_label(extra)[0]
        if got and got not in ids:
            ids.append(got)
    return [i for i in ids if i]


def _id_and_label(entry) -> tuple:
    """An extra-funnel entry -> (id, label). Accepts a bare id or a pair."""
    if isinstance(entry, (tuple, list)):
        got = list(entry) + ["", ""]
        return str(got[0] or "").strip(), str(got[1] or "").strip()
    return str(entry or "").strip(), ""


def _funnel_labels(office_key: str) -> dict:
    """{account id: what to call it on the board}. The office's own account
    gets no label -- its people are the board's default, and a divider over
    everybody says nothing."""
    from automations.office_admin import config as OC
    o = OC.office(office_key)
    out = {}
    if not o:
        return out
    for extra in (getattr(o, "extra_appstream_ids", ()) or ()):
        got, label = _id_and_label(extra)
        if got:
            out[got] = label or got
    return out


def _person_key(person) -> str:
    """Who this row is, for de-duping across funnels: email if there is one,
    else the folded name. Email first because two funnels spell a name two
    ways far more often than they hold two addresses."""
    get = person.get if hasattr(person, "get") else (lambda k, d="": d)
    email = str(get("email", "") or "").strip().lower()
    if email:
        return email
    return _name_key(person)


def _name_key(person) -> str:
    """The folded name, as a SECOND way to recognise the same person.

    AN EMAIL CAN BE MISTYPED AND AN ADDRESS IS NOT AN IDENTITY. Carmen Lopez
    is on both of Raf's funnels as `Carmenlopezcr@icloud.co` and
    `carmenlopezcr@icloud.com` -- one letter apart -- so keying on the
    address alone made her two people and put her on the board twice, one
    row carrying eight finished steps and the other none (2026-11-20).

    Used as a fallback, never instead of the email: two different people
    genuinely sharing a name is rarer than a typo, but it is not impossible,
    so a name-only match is reported rather than taken quietly.
    """
    get = person.get if hasattr(person, "get") else (lambda k, d="": d)
    name = ("%s %s" % (get("first_name", "") or "",
                       get("last_name", "") or "")).strip()
    return B._fold(name) if name else ""


def seed(office_key: str, week_start: dt.date, *, dry_run: bool = True,
         log=print, names_only: bool = False) -> int:
    """Everybody SCHEDULED to start in the office that week, onto the board.

    Megan, 2026-11-15: *"we would want this extension to live off of the
    applicant stream for that current week that are scheduled to start ... when
    they're brought on board, even though they're brought on board Monday, they
    could have a 2 week out start date. So we want to actually see the new
    starts on our onboarding list because those are the ones that are actually
    starting in the office that week that we're going to be onboarded."*

    So the WEEK A ROW LANDS ON IS THE WEEK THEY START, never the week they were
    brought on board, and the row is there before Monday rather than appearing
    the morning they walk in.

    TWO READS, ONE SESSION. The scheduled row makes the rows; the showed-up row
    then ticks `Showed Up` on them. Opening the session is the slow part, so the
    second read is two more page loads rather than another job.

    names_only=True IS THE 15-MINUTE PASS (`seed_names`, step 7). It does the
    first read and nothing else. Measured on Raf's two funnels 2026-11-22: the
    whole step took 7m01s, and the Showed Up half is where it goes -- the
    scheduled row is 2 page loads per account, the showed-up row 2 more, and
    the training calendar walk SEVEN, which this function's own comment below
    already prices. 22 page loads for two funnels, 18 of them about a column
    that changes when somebody ticks a radio once a day.

    So the two halves get the clocks they deserve. A NAME is urgent: until the
    row is there the office cannot see the person at all, which is why Megan
    asked for 15 minutes on 2026-11-22. Showed Up is not, and it stays on the
    hourly run, where nothing about it got slower.
    """
    from automations.icd_onboarding import sessions as SES
    from automations.office_admin import fdot

    from automations.office_admin import retention

    accounts = _appstream_ids(office_key)
    if not accounts:
        log("  seed: %s has no ApplicantStream id" % office_key)
        return 0
    if len(accounts) > 1:
        log("  seed: %d funnels onboard here -- %s"
            % (len(accounts), ", ".join(accounts)))
    people: List[dict] = []
    showed = None
    seen = set()
    by_name: Dict[str, str] = {}
    labels = _funnel_labels(office_key)
    # WHICHEVER APPLICANTSTREAM THIS MACHINE HAS (`sessions`). On a Lucy that
    # is the warm console everybody shares; on the office's own computer it is
    # the Chrome `resume_push` already signs in, with THEIR login -- which is
    # the whole point of the seed running there (Megan, 2026-11-23: "I want to
    # move it to the ECO machines once it's all built out").
    with SES.appstream_anywhere(office_key, log=log) as app:
        for account in accounts:
            app.select_office(account)
            # WHO IS DUE IN. The Retention Report answers this in TWO page
            # loads where the calendar walk takes seven (Megan, 2026-11-09:
            # "you should just look at the retention details report and not
            # walk the calendar as this would be faster").
            #
            # NO FALLBACK HERE, on purpose. The calendar walk answers who
            # SHOWED UP, which is a different question -- standing in for this
            # one it would quietly seed a different set of people, and a week
            # that could not be read must never be seeded from the nearest
            # thing to hand ([[feedback_empty_means_proven_zero]]).
            mine = retention.read_scheduled_week(app, account, week_start,
                                                 log=log)
            # ONE PERSON, ONE ROW. Two funnels can hold the same candidate --
            # a rep re-entered on the new launch's account is still one new
            # start -- and seeding them twice puts two rows on the board for
            # one human, which every later tick then has to choose between.
            label = labels.get(account, "")
            for person in (mine or []):
                key = _person_key(person)
                nkey = _name_key(person)
                # A name we already hold under a DIFFERENT address is the
                # typo case: same person, one row. Said out loud, because
                # the alternative reading -- two people of one name -- is
                # rare but real, and this is the line that would be wrong.
                if key and key not in seen and nkey and nkey in by_name:
                    log("    %s: already here as %s — treating the two "
                        "addresses as one person" % (nkey, by_name[nkey]))
                    key = by_name[nkey]
                if key and key in seen:
                    # ALREADY HELD FROM ANOTHER FUNNEL -- keep the LABELLED
                    # one. The office's own account is read first and carries
                    # no label, so first-wins quietly threw away the only copy
                    # that said where the person came from: Aalya Vasquez and
                    # Zachary Murphy are on 11280 AND 23965, landed as Raf's,
                    # and ended up on the board with a blank Funnel
                    # (2026-11-20). A funnel that names itself beats one that
                    # does not; two that both name themselves keep the first,
                    # because then it is a real ambiguity and not a default.
                    if label:
                        for held in people:
                            if _person_key(held) == key and not str(
                                    held.get(B.FUNNEL) or "").strip():
                                try:
                                    held[B.FUNNEL] = label
                                except TypeError:
                                    pass
                                break
                    continue
                if key:
                    seen.add(key)
                if nkey:
                    by_name.setdefault(nkey, key)
                # WHICH FUNNEL THIS ROW CAME FROM. The board draws a labelled
                # divider per funnel because they all land in ONE OwnerVille
                # and a leader reading the week has no other way to tell whose
                # new start is whose (Megan 2026-11-20). Blank for the
                # office's own account: its people are the default and a
                # divider over everybody says nothing.
                if label:
                    try:
                        person[B.FUNNEL] = label
                    except TypeError:       # not a dict -- leave it alone
                        pass
                people.append(person)
            if len(accounts) > 1:
                log("    %s: %d scheduled" % (account, len(mine or [])))

            # AND WHO TURNED UP, of those. Read in the same session; the walk
            # IS the fallback for this one, because it answers exactly this.
            #
            # Not on the 15-minute pass: see names_only in the docstring. The
            # rows still land; nothing here adds a row, it only ticks one.
            if names_only:
                continue
            try:
                got = retention.read_week(app, account, week_start, log=log)
            except Exception as e:  # noqa: BLE001 — fall back, never give up
                log("  showed-up row unavailable (%s: %s) — walking the "
                    "calendar" % (type(e).__name__, str(e)[:120]))
                try:
                    got = fdot.read_week(app, account, week_start, log=log)
                except Exception as e2:  # noqa: BLE001 — the seed still stands
                    log("  (nobody could be ticked as shown up on %s: %s — "
                        "the rows ARE on the board)"
                        % (account, type(e2).__name__))
                    got = None
            # None means "could not read", which is NOT the same as "nobody
            # showed" -- so it must never wipe what another funnel answered.
            if got is not None:
                showed = list(showed or []) + list(got)

            # AND THE TRAINING CALENDAR, as well as the Retention row rather
            # than instead of it (Megan 2026-11-21: "we can mark this yes if
            # they show up to day one on the applicant stream calendar").
            #
            # IT ALSO CARRIES THE ONE THING THE SCHEDULED ROW CANNOT: which
            # DAY each person starts. The Retention Report's date column is
            # the apply timestamp, so every seeded row fell back to the
            # week's Sunday -- all 31 on Raf's OBCL 11.23 read Start = 11/22
            # (2026-11-22). Blue Ink goes two days before each person's own
            # start and the welcome email names their day in words, so that
            # placeholder mails a real person the wrong date. `week_rows`
            # returns both answers off this same walk rather than a second
            # one.
            # The two disagree: on the week of 11/16 the calendar had Jaime
            # Molina and Carmen Lopez showing up and the board had their
            # Showed Up empty, so the extension said "not in yet" about two
            # people who were in. A union, because each only ever ADDS a name
            # and ticking is on-only anyway.
            #
            # It costs seven page loads per account against the Retention
            # row's two. Worth it for the one column somebody reads to decide
            # whether a person is actually here.
            try:
                turned_up, first_day = fdot.week_rows(app, account,
                                                      week_start, log=log)
                showed = list(showed or []) + list(turned_up)
                # The calendar's day beats the week's Sunday, and ONLY the
                # Sunday: a day the scheduled row did read is a real answer
                # off the page we asked, so it is left alone.
                fixed = 0
                for person in people:
                    if person.get("started"):
                        continue
                    name = ("%s %s" % (person.get("first_name", ""),
                                       person.get("last_name", ""))).strip()
                    day = first_day.get(" ".join(name.lower().split()))
                    if day:
                        person["started"] = day
                        fixed += 1
                if fixed:
                    log("    %d start day(s) off the training calendar"
                        % fixed)
            except Exception as e:                          # noqa: BLE001
                log("  calendar for %s unreadable (%s) -- the Retention row "
                    "stands alone for this funnel, so its people keep the "
                    "week's Sunday as their Start" % (account,
                                                      type(e).__name__))
    got = F.seed_anywhere(office_key, week_start, people,
                          dry_run=dry_run, log=log)
    if not names_only:
        _tick_showed_up(office_key, week_start, showed, dry_run=dry_run, log=log)
    # A step this office does not do is not an outstanding step. Marked at
    # seed time so the office never reads as behind on work that does not
    # exist (Megan, 2026-11-09: "if they don't then they can't enroll in apex
    # and so we would skip that part").
    from automations.icd_onboarding import office_steps as OS
    OS.mark_not_applicable(office_key, week_start, dry_run=dry_run, log=log)
    # NO GENDER SUGGESTION ANY MORE (Megan, 2026-11-24: "gender now is just
    # assumed based on name and does not belong on the OBCL. It'll only come
    # into play on the Apex fill"). The guess still happens -- at the moment it
    # is typed into Apex, where a person is sitting there and can correct it --
    # so `gender_suggest` is still the one guesser, just called from there
    # rather than written onto a column the office had to check.
    return len(got.get("add") or [])


def seed_names(office_key: str, week_start: dt.date, *, dry_run: bool = True,
               log=print) -> int:
    """STEP 7, on its own 15-minute clock: the names, and nothing else.

    "Their name appears on the OBCL extension" is the step the office actually
    waits on -- until the row is there the person does not exist to them --
    and Megan asked for it every 15 minutes rather than hourly (2026-11-22):
    somebody brought on board at 2:05 should be on the extension at 2:15.

    It is the same seed with the Showed Up half left off, NOT a second reader
    of the same thing. One function, one set of de-duplication rules, one
    place where a funnel label is decided; a copy of this that drifted would
    put a second row on the board for one person, which is the mistake the
    rules in `seed` exist to prevent.

    What it still does, because both are Sheets-only and belong with a row the
    moment it appears: marks the steps this office does not do, and suggests a
    gender on the new rows. What it does not do is read whether anybody turned
    up -- 18 of the 22 page loads, and an answer that changes when a recruiter
    ticks a radio, so it stays on the hourly run.

    Its LaunchAgent is com.alphalete.icd-onboarding-seed (:00, :15, :45).
    """
    return seed(office_key, week_start, dry_run=dry_run, log=log,
                names_only=True)


def from_no_shows(office_key: str, week_start: dt.date, *,
                  dry_run: bool = True, log=print) -> int:
    """Who ApplicantStream says did NOT turn up, onto `Showed Up`.

    Megan, 2026-11-16, asked what should stop a send off this board: *"1 would
    be if they are marked no show in app stream"*.

    AN EXPLICIT NO, NEVER AN ABSENCE. The training calendar's Show Up control
    is a radio; a recruiter checking No is a person stating they did not come.
    Nothing checked means nobody has said yet, and that is left alone -- the
    board has never marked anybody off for a blank and must not start.

    A YES ANYWHERE IN THE WEEK WINS. Somebody rescheduled is on the calendar
    twice, so a later Yes beats an earlier No: the Tuesday walk-in. The column
    advances (blank -> No Show -> a date) rather than ticking, so a date
    written later replaces a No Show and never the other way round.

    WHY IT IS ITS OWN STEP and not part of the seed: this is the SEVEN-page
    calendar walk, which the seed deliberately stopped doing when the two-page
    Retention Report turned out to answer the seed's question (Megan,
    2026-11-09). Running it hourly would put that cost back. Whether the
    Retention Report also carries a no-show row -- which would make this cheap
    enough for the hourly run -- is a question for somebody with an
    ApplicantStream session in front of them; the row labels this reads are
    the calendar's, which are known.
    """
    from automations.icd_onboarding import sessions as SES
    from automations.office_admin import fdot

    account = _appstream_id(office_key)
    if not account:
        log("  no_shows: %s has no ApplicantStream id" % office_key)
        return 0
    with SES.appstream_anywhere(office_key, log=log) as app:
        app.select_office(account)
        people = fdot.no_shows_week(app, account, week_start, log=log)
    if not people:
        log("  no_shows: nobody was marked No this week")
        return 0
    verdicts = {}
    for p in people:
        name = ("%s %s" % (p.get("first_name") or "",
                           p.get("last_name") or "")).strip()
        if name:
            verdicts[name] = {B.SHOWED_UP: B.NO_SHOW}
    wrote = F.apply_anywhere(office_key, week_start, "appstream", verdicts,
                             dry_run=dry_run, log=log)

    # AND INTO THE REMOVED SECTION, with the reason filled in for them (Megan,
    # 2026-11-24: "if they're checked no, it'll still appear on the OBCL, but
    # it'll be in the show removal section, and then it should just say no show
    # to first day").
    #
    # THE ROW STAYS ON THE BOARD. The removed section is part of it; this is
    # where the row goes, not something that happens to it. The office could
    # already click somebody in there and pick a reason by hand -- all that is
    # new is that a No they have already ticked in ApplicantStream does it, so
    # nobody enters the same fact twice.
    #
    # EVERY NAME, EVERY PASS, on purpose: both the relay and the gspread twin
    # leave a row that is already removed alone, so this writes nothing the
    # second night and cannot pile stamps up on one row.
    try:
        F.mark_removed_anywhere(office_key, week_start, list(verdicts),
                                reason=B.NO_SHOW_REASON, dry_run=dry_run,
                                log=log)
    except Exception as e:      # noqa: BLE001 -- the column still matters more
        # The Showed Up answer is the load-bearing half and it is already
        # written. A removal that could not be made is said out loud rather
        # than losing the pass that recorded who did not come.
        log("  (could not mark the no-shows removed: %s: %s)"
            % (type(e).__name__, str(e)[:140]))
    return wrote


def _tick_showed_up(office_key: str, week_start: dt.date, showed,
                    *, dry_run: bool, log=print) -> int:
    """Tick `Showed Up` for the scheduled people who turned up.

    ON ONLY, like every other tick: an absence is not a tick off and is never
    a removal -- somebody missing on Monday may walk in on the Tuesday. An
    unread showed-up row ticks nobody rather than emptying the column.

    AND THE TUESDAY WALK-IN IS PUT BACK. Since 2026-11-24 a No ticked in
    ApplicantStream also lands the row in the board's removed section, so this
    is the pass that has to undo it: somebody who turns up after being marked
    absent is exactly the case the board exists to survive, and a removal left
    standing would keep them out of every step below it. The date already
    outranks No Show in the column (`showed_up_rank`); this makes the removed
    section agree with the column instead of contradicting it.

    ONLY A REMOVAL THE MACHINE MADE IS LIFTED. A person who clicked somebody
    off and typed their own reason has decided something this does not know
    about, and a walk-in does not undo it ([[feedback_dont_touch_user_data]]).

    Never fails the seed: the rows are already on the board, and a column that
    did not tick is a visible gap in the right place.
    """
    if showed is None:
        return 0
    from automations.icd_onboarding import board as BB
    verdicts = {}
    for p in showed:
        name = ("%s %s" % (p.get("first_name") or "",
                           p.get("last_name") or "")).strip()
        if name:
            verdicts[name] = {BB.SHOWED_UP: True}
    if not verdicts:
        log("  showed up: nobody yet this week")
        return 0
    try:
        wrote = F.apply_anywhere(office_key, week_start, "appstream",
                                 verdicts, dry_run=dry_run, log=log)
    except Exception as e:      # noqa: BLE001
        log("  (Showed Up was not ticked: %s: %s)"
            % (type(e).__name__, str(e)[:120]))
        return 0
    try:
        back = _walked_in_after_a_no_show(office_key, week_start,
                                          list(verdicts), log=log)
        if back:
            log("  %d turned up after being marked a no show -- putting them "
                "back on the board" % len(back))
            F.mark_removed_anywhere(office_key, week_start, back, restore=True,
                                    dry_run=dry_run, log=log)
    except Exception as e:      # noqa: BLE001 -- the tick is the load-bearing half
        log("  (could not put a walk-in back: %s: %s)"
            % (type(e).__name__, str(e)[:140]))
    return wrote


def _walked_in_after_a_no_show(office_key: str, week_start: dt.date,
                               turned_up: Sequence[str], log=print) -> List[str]:
    """Of the people who turned up, which are sitting in the removed section
    for OUR no-show reason?

    Read off the board rather than assumed, because the answer has to be both
    halves: they are removed AND the reason is the one the machine writes. A
    person's own reason is left exactly where it is.
    """
    want = {B._fold(n) for n in turned_up}
    out = []
    for r in F.rows_anywhere(office_key, week_start, log=log):
        who = "%s %s" % (r.get("Name", ""), r.get("Last Name", ""))
        if B._fold(who) not in want:
            continue
        if not str(r.get(B.TERMINATED_AT) or "").strip():
            continue
        if str(r.get(B.REMOVED_WHY) or "").strip() != B.NO_SHOW_REASON:
            continue
        out.append(who.strip())
    return out


# --- THE FIVE OWNERVILLE COLUMNS ---------------------------------------------
#
# Moved here from `icd_onboarding.run` on 2026-11-24. One read of OwnerVille's
# View Progress answers five boxes at once, and it is the office's OWN
# OwnerVille -- their login, their campaign, their roster. The session comes
# from `sessions.session_anywhere`, so this same body reads the Hub's
# one-per-box session on a Lucy and the office's own on an office machine,
# where nothing queues behind another office.
#
# `run.from_ownerville` is a delegate now. One body, as with the seed.

def _ov_program(office_key: str) -> str:
    from automations.office_admin import config as OC
    o = OC.office(office_key)
    return (getattr(o, "ov_program", "") if o else "") or ""


def _board_names(office_key: str, week_start: dt.date,
                 columns: Sequence[str] = ()) -> List[str]:
    """Who on this week's board is still worth looking up.

    Not everybody: the search is one request per person against a slow server
    (~23s each, measured), so asking about people who cannot gain anything is
    how a run spends its whole budget and still leaves somebody out.

    Left out:
      * anybody MARKED OFF — they are never ticked, so an answer about them is
        thrown away;
      * anybody who already has every column this source fills — there is
        nothing left to learn, and each run then has fewer to ask about than
        the last.
    """
    out = []
    for r in F.rows_anywhere(office_key, week_start):
        if not (r.get("Name") or r.get("Last Name")):
            continue
        if str(r.get(B.TERMINATED_AT) or "").strip():
            continue
        if columns and all(str(r.get(c) or "").strip() for c in columns):
            continue
        out.append(("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip())
    return out


def from_ownerville(office_key: str, week_start: dt.date, *,
                    dry_run: bool = True, log=print,
                    budget_s: Optional[float] = None) -> int:
    """Five columns off one View Progress read.

    IT USED TO ONLY GIVE PAGE ONE. The table was read as rendered, which
    served a couple of dozen rows out of a hundred-odd, so the people on the
    later pages came back unread — on Raf's office that was 24 of 127, and
    only 3 of the week's 29 got their five columns. Unread is never "not
    done", so nothing was wrongly ticked; they simply never got an answer.
    The answer then was to ask the server's own search about each missing
    person, one at a time.

    Since 2026-11-21 read_table reads the request that fills the table, so one
    call returns the WHOLE roster and `complete` says so. The per-person
    search is kept only for the case where that read falls short, because
    against a complete roster it cannot find anybody the read missed: the
    search box fires the same request and filters the answer in the browser.
    Measured here on the week of 11/15 — 22 of 39 missing, 7 searched over
    203s, 22 still missing afterwards. Those 22 are not unread; they are not
    enrolled in this programme yet, and no amount of searching changes that.
    """
    import time

    from automations.icd_onboarding import sessions as OVA
    from automations.icd_onboarding import ov_misses as OVM
    from automations.obcl_ov_sweep import config as OVC
    from automations.obcl_ov_sweep import ov_table
    # `config`, NOT `run`: the path moved there on 2026-11-24 precisely so
    # that wanting it does not import the sweep and gspread with it -- which
    # an office machine has neither of. The shipped-closure test caught this
    # line on the first pass.
    from automations.obcl_ov_sweep.config import PROFILE_DIR

    programme = _ov_program(office_key)
    if not programme:
        # A guess here reads an empty table, which looks exactly like nobody
        # having done anything ([[reference_campaign_picks_the_workbook]]).
        log("  ownerville: %s has no ov_program set — skipped rather than "
            "guessing at Alphalete's" % office_key)
        return 0

    wanted = _board_names(office_key, week_start,
                          columns=F.columns_for("ownerville"))
    budget = OVC.SEARCH_BUDGET_S if budget_s is None else budget_s

    # WHICHEVER SESSION THIS MACHINE HAS (`sessions`). On a Lucy that is the
    # Hub's one-per-box OwnerVille, which every office's read queues behind --
    # the 8am sweep waited its whole 30 minutes behind three other jobs on
    # 2026-11-24 and refused rather than guess whose rows it had. On the
    # office's own computer it is THEIR OwnerVille, with their login, and
    # nothing queues at all (Megan, same day: "the OV sweep would happen on
    # the ECO machine").
    with OVA.session_anywhere(office_key, campaign=programme,
                              profile_dir=PROFILE_DIR, log=log) as page:
        heads, reps, complete = ov_table.read_table(page, verbose=False,
                                                    campaign=programme)
        found = {B._fold(n) for n in reps}
        missing = [n for n in wanted if B._fold(n) not in found]
        if missing and complete:
            # STILL SAID OUT LOUD, just not searched for. These people have
            # been looked for in the whole roster and are not in it, which is
            # a real answer and the one somebody acts on -- they have not been
            # added to this programme yet. Their columns stay untouched.
            log("  ownerville: %d of this week's %d are not in the %s roster "
                "(read was complete, so the search cannot find them): %s"
                % (len(missing), len(wanted), programme,
                   ", ".join(missing[:8])
                   + (" ..." if len(missing) > 8 else "")))
        if missing and not complete:
            # DON'T ASK AGAIN ABOUT SOMEBODY OWNERVILLE ALREADY SAID IT HAS
            # NOT GOT. Measured 2026-11-19: 21 of 29 were not there, each
            # search costs ~27s, and the budget then ran out with 10 names
            # never asked about -- so the wasted time was also crowding out
            # the searches that would have found somebody. A miss goes stale
            # after ov_misses.COOLDOWN_MIN, so anyone added during the day is
            # still picked up; until then the budget goes to new names.
            ask = OVM.fresh(office_key, week_start, missing)
            skipped = len(missing) - len(ask)
            log("  ownerville: the read fell short — %d of this week's %d "
                "unanswered, asking the search for them"
                % (len(missing), len(wanted)))
            if skipped:
                log("    skipping %d OwnerVille said it has not got in the "
                    "last %d min — they are re-asked after that, not ticked"
                    % (skipped, OVM.COOLDOWN_MIN))
            t0 = time.monotonic()
            got = 0
            for name in ask:
                if time.monotonic() - t0 >= budget:
                    log("    time budget reached; %d not searched this run"
                        % (len(ask) - got))
                    break
                try:
                    ov_table.lookup_person(page, name, heads, reps)
                except Exception as e:      # noqa: BLE001 — one name, not the run
                    log("    %s: search failed (%s)" % (name, type(e).__name__))
                got += 1
            seen = {B._fold(x) for x in reps}
            still = [n for n in wanted if B._fold(n) not in seen]
            # Remember only the ones we ACTUALLY asked about and did not find;
            # a name the budget never reached has not been answered, and
            # recording it would stop it being asked next time either.
            asked = ask[:got]
            OVM.remember(office_key, week_start,
                         [n for n in asked if B._fold(n) not in seen])
            # And a name that DID turn up stops being treated as absent the
            # moment it appears, however it appeared.
            OVM.forget(office_key, week_start,
                       [n for n in wanted if B._fold(n) in seen])
            log("    searched %d in %.0fs — %d still not found in OwnerVille"
                % (got, time.monotonic() - t0, len(still)))

    verdicts = {}
    for name, cells in reps.items():
        v = ov_table.done_columns(heads, cells)
        # WHAT OWNERVILLE SAYS ABOUT THE BACKGROUND CHECK, beside what
        # Sterling says (Megan, 2026-11-11: "the BGstatus is the BG check
        # column and what it says"). A STATE, not a tick: it advances, and a
        # blank means the cell could not be read -- never "nothing happened".
        said = ov_table.bg_status_text(heads, cells)
        if said:
            v["OV BG Status"] = said
        verdicts[name] = v
    return F.apply_anywhere(office_key, week_start, "ownerville",
                            verdicts, dry_run=dry_run, log=log)


# THE STEPS THIS MACHINE CAN DO ITSELF, in the order a pass runs them.
#
# A STEP EARNS ITS PLACE HERE by being able to run on an office Mac at all --
# its source read with the office's own login, its board write through the
# relay. One in this tuple that cannot is a pass that fails every hour.
#
#   seed       first, because nothing below it has anybody to be about. It
#              reads ApplicantStream's Retention Report for who is SCHEDULED
#              to start this week, through `sessions.appstream_anywhere` --
#              the office's own Chrome here, the warm console on a Lucy.
#   ownerville five boxes from ONE read of OwnerVille's View Progress -- Digi
#              Docs, the quizzes, the headshot, the UID and the BG status,
#              plus the three gates that hold Owner Submit. The office's own
#              OwnerVille, their login and their campaign, through
#              `sessions.session_anywhere`.
#   contacts   Contact Added, off the office's OWN reception Google Contacts
#              (Megan, 2026-11-11: "each ICD will have their own reception
#              email"). The first step that ever ran here.
#   no_shows   who was marked No in ApplicantStream. Its own slot at 21:15,
#              not this list's order -- `eco_job` runs it alone, because it is
#              the seven-page calendar walk and it must land before the next
#              morning's Blue Ink send.
#
# STILL TO COME: the Owner Submit press (its body is in `presses`, which does
# not ship), Blue Ink, Sterling and Apex. The press is the one that ACTS rather
# than reads, so it moves last and deliberately.
#
# NOTHING HERE IS SWITCHED ON BY BEING LISTED. `eco_job` runs nothing until a
# machine is armed (`eco_job.switch_on`), and no machine is
# ([[feedback_onboarding_nothing_live_till_built]]).
STEPS: Sequence[Tuple[str, object]] = (
    ("seed", seed),
    ("ownerville", from_ownerville),
    ("contacts", contacts),
    ("no_shows", from_no_shows),
)


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
