"""One office's onboarding board, brought up to date.

    python -m automations.icd_onboarding.run --office raf
    python -m automations.icd_onboarding.run --office raf --write

Seeds the week off the office's training calendar, then lets each source that
can answer tick what it has earned. Dry by default: it says what it would do
and writes nothing.

WHAT RUNS HERE AND WHAT DOES NOT. Two of the five sources tick themselves at
the moment they act — the contact sync as it adds somebody, the Apex run as it
saves a record — because they know then and nothing else has to work it out
afterwards. This runs the three that have to be gone and LOOKED for:

    seed        the training calendar   (ApplicantStream)
    ownerville  five columns, one read  (OwnerVille View Progress)
    blueink     Blue Ink                (the office's API key)
    sterling    BG Status               (the ICDs' forwarded results inbox)

AND ONE THAT ACTS rather than looks (2026-11-15) -- the only step here that
presses a button on somebody's behalf, which is why it lives apart in
presses.py and runs last, after `ownerville` has said what is true right now:

    owner_submit  attest and submit       -> Owner Submit

It is GATED, it is refused by OwnerVille's own section states rather than by
anything the board says, and it believes only what the page reads on a fresh
re-open. A board cell can never cause a press: people type in that sheet, and
a typed cell must not be able to attest for a rep.

THERE IS NO UID PRESS, though one was written and thrown away the same day.
OwnerVille's AT&T UID REQUEST section has no button in it: the rep submits the
ATTUID form themselves in the Candidate Roadmap Portal, and the request goes
to AT&T once they are activated for SaraPlus. It is the new start's own step,
like the quizzes and the headshot, so it belongs to the nudge. `uid_reasons`
is what is left of it -- a read of whose move each outstanding one is.

EVERY STEP IS INDEPENDENT. One source being down is not a reason to skip the
others: OwnerVille having a bad morning should not stop Blue Ink ticking, and
a step that fails says so and the run carries on. A step that cannot be read
leaves its column alone — unread is never "not done", the rule the whole board
is built on.

WHERE IT RUNS. The office's own machine, which holds its own logins. Reading
one office's calendar from another office's session is the thing this report
exists to avoid.

FOUR SOURCES, AND NO FIFTH. OwnerVille, ApplicantStream, Blue Ink, Apex (Megan,
2026-11-10: "we need to function off of OV / AS / Blueink / Apex ONLY moving
forward -- we generate the OBCL"). An ICD's ECO machine holds those four logins
and nothing else, so anything reading a fifth source works for Alphalete and
silently produces nothing for the other ~52 offices -- the sales board above
all, which is Alphalete's own. This board is an OUTPUT of the four, and where
they hold nothing (Classroom, Gender) it carries a column a person fills rather
than a read of somewhere else.
"""
from __future__ import annotations

import datetime as dt
import pathlib
from typing import Dict, List, Optional, Sequence

from automations.icd_onboarding import board as B
from automations.icd_onboarding import fillers as F


def _appstream_id(office_key: str) -> str:
    from automations.office_admin import config as OC
    o = OC.office(office_key)
    return (o.appstream_id if o else "") or ""


def _ov_program(office_key: str) -> str:
    from automations.office_admin import config as OC
    o = OC.office(office_key)
    return (getattr(o, "ov_program", "") if o else "") or ""


def seed(office_key: str, week_start: dt.date, *, dry_run: bool = True,
         log=print) -> int:
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
    """
    from automations.applicant_tracker.applicantstream import session
    from automations.icd_onboarding import sheet as S
    from automations.office_admin import fdot

    from automations.office_admin import retention

    account = _appstream_id(office_key)
    if not account:
        log("  seed: %s has no ApplicantStream id" % office_key)
        return 0
    with session() as app:
        app.select_office(account)
        # WHO IS DUE IN. The Retention Report answers this in TWO page loads
        # where the calendar walk takes seven (Megan, 2026-11-09: "you should
        # just look at the retention details report and not walk the calendar
        # as this would be faster").
        #
        # NO FALLBACK HERE, on purpose. The calendar walk answers who SHOWED
        # UP, which is a different question -- standing in for this one it
        # would quietly seed a different set of people, and a week that could
        # not be read must never be seeded from the nearest thing to hand
        # ([[feedback_empty_means_proven_zero]]).
        people = retention.read_scheduled_week(app, account, week_start,
                                               log=log)
        # AND WHO TURNED UP, of those. Read in the same session; the walk IS
        # the fallback for this one, because it answers exactly this.
        try:
            showed = retention.read_week(app, account, week_start, log=log)
        except Exception as e:      # noqa: BLE001 — fall back, never give up
            log("  showed-up row unavailable (%s: %s) — walking the calendar"
                % (type(e).__name__, str(e)[:120]))
            try:
                showed = fdot.read_week(app, account, week_start, log=log)
            except Exception as e2:     # noqa: BLE001 — the seed still stands
                log("  (nobody could be ticked as shown up: %s — the rows ARE "
                    "on the board)" % type(e2).__name__)
                showed = None
    got = F.seed_anywhere(office_key, week_start, people,
                          dry_run=dry_run, log=log)
    _tick_showed_up(office_key, week_start, showed, dry_run=dry_run, log=log)
    # A step this office does not do is not an outstanding step. Marked at
    # seed time so the office never reads as behind on work that does not
    # exist (Megan, 2026-11-09: "if they don't then they can't enroll in apex
    # and so we would skip that part").
    from automations.icd_onboarding import office_steps as OS
    OS.mark_not_applicable(office_key, week_start, dry_run=dry_run, log=log)
    # A GENDER SUGGESTION ON THE NEW ROWS, where the first name makes it clear
    # (Megan, 2026-11-18). At seed time and not on a clock of its own: the
    # admin should find the column already part-filled when the row appears,
    # rather than meeting a blank column and then having it change under them.
    #
    # Guarded, because this is a convenience and the seed is not. A board that
    # was seeded with no suggestions is a week somebody types by hand; a seed
    # that died trying to suggest is a week with no rows at all.
    try:
        from automations.icd_onboarding import gender_suggest as GS
        GS.fill(office_key, week_start, dry_run=dry_run, log=log)
    except Exception as exc:                                # noqa: BLE001
        log("  (no gender suggestions this time: %s: %s)"
            % (type(exc).__name__, str(exc)[:120]))
    return len(got.get("add") or [])


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
    from automations.applicant_tracker.applicantstream import session
    from automations.office_admin import fdot

    account = _appstream_id(office_key)
    if not account:
        log("  no_shows: %s has no ApplicantStream id" % office_key)
        return 0
    with session() as app:
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
    return F.apply_anywhere(office_key, week_start, "appstream", verdicts,
                            dry_run=dry_run, log=log)


def _tick_showed_up(office_key: str, week_start: dt.date, showed,
                    *, dry_run: bool, log=print) -> int:
    """Tick `Showed Up` for the scheduled people who turned up.

    ON ONLY, like every other tick: an absence is not a tick off and is never
    a removal -- somebody missing on Monday may walk in on the Tuesday, and
    marking them off is a person's call ("No Show" is one of the reasons the
    panel offers). An unread showed-up row ticks nobody rather than emptying
    the column.

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
        return F.apply_anywhere(office_key, week_start, "appstream",
                                verdicts, dry_run=dry_run, log=log)
    except Exception as e:      # noqa: BLE001
        log("  (Showed Up was not ticked: %s: %s)"
            % (type(e).__name__, str(e)[:120]))
        return 0


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
    from automations.icd_onboarding import sheet as S

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
    """Five columns off one View Progress read, plus a search for the rest.

    THE PAGE ONLY EVER GIVES PAGE ONE. The table is served a page at a time,
    so one read returns a couple of dozen rows out of a hundred-odd and the
    people on the later pages come back unread — on Raf's office that was 24
    of 127, and only 3 of the week's 29 got their five columns.

    Unread is never "not done", so nothing was wrongly ticked; they simply
    never got an answer. The sweep solved this long ago by asking the server's
    own search about each missing person one at a time, and this does the same
    — but only for the people on THIS WEEK'S BOARD, which is a couple of dozen
    rather than the whole roster.
    """
    import time

    from automations.obcl_ov_sweep import config as OVC
    from automations.obcl_ov_sweep import ov_table
    from automations.obcl_ov_sweep.run import PROFILE_DIR
    from automations.shared.tableau_patchright import ownerville_session

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

    with ownerville_session(headless=True, verbose=False,
                            profile_dir=PROFILE_DIR) as page:
        heads, reps, complete = ov_table.read_table(page, verbose=False,
                                                    campaign=programme)
        found = {B._fold(n) for n in reps}
        missing = [n for n in wanted if B._fold(n) not in found]
        if missing:
            log("  ownerville: %d of this week's %d were not on page one — "
                "asking the search for them" % (len(missing), len(wanted)))
            t0 = time.monotonic()
            got = 0
            for name in missing:
                if time.monotonic() - t0 >= budget:
                    log("    time budget reached; %d not searched this run"
                        % (len(missing) - got))
                    break
                try:
                    ov_table.lookup_person(page, name, heads, reps)
                except Exception as e:      # noqa: BLE001 — one name, not the run
                    log("    %s: search failed (%s)" % (name, type(e).__name__))
                got += 1
            still = [n for n in wanted if B._fold(n) not in {B._fold(x) for x in reps}]
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


def from_blueink(office_key: str, week_start: dt.date, *,
                 dry_run: bool = True, log=print) -> int:
    """Who has a signed packet."""
    from automations.apex_new_starts import blueink_data as BID
    from automations.apex_new_starts import eco_run as ECO
    from automations.icd_onboarding import sheet as S

    from automations.icd_onboarding import office_steps as OS
    if OS.uses_blueink(office_key) is False:
        log("  blueink: %s has no Blue Ink account — nothing to read"
            % office_key)
        return 0

    rows = F.rows_anywhere(office_key, week_start, log=log)
    if not rows:
        log("  blueink: nobody on the board for that week")
        return 0
    people = [ECO.Starter(name=("%s %s" % (r.get("Name", ""),
                                           r.get("Last Name", ""))).strip(),
                          email=r.get("Email", ""))
              for r in rows if r.get("Name") or r.get("Last Name")]
    if not people:
        log("  blueink: nobody on the board for that week")
        return 0
    # THE API ONLY IF THIS MACHINE HAS A KEY. API Access is an Enterprise-only
    # feature on this Blue Ink plan, which is why no machine in the fleet had a
    # key on 2026-08-24 and recent_ui exists at all. An ICD on a normal plan
    # may not be able to create one even if asked, so the web session -- the
    # same screen a person reads -- is the route that always works.
    from automations.blueink_docs import config as BC
    verdicts = {}
    if str(BC._creds().get("blueink_api_key") or "").strip():
        hires = BID.for_people(people, keep_ssn=False)
        for p in people:
            h = hires.get(p.name)
            if h is not None and not h.missing_packet:
                verdicts[p.name] = {"Blue Ink": True}
    else:
        from automations.blueink_docs import recent_ui as RU
        log("  blueink: no API key on this machine — reading the web app")
        done = RU.signed(people, headless=True)
        for p in people:
            if (p.email or "").strip().lower() in done:
                verdicts[p.name] = {"Blue Ink": True}
    return F.apply_anywhere(office_key, week_start, "blueink", verdicts,
                            dry_run=dry_run, log=log)


def from_sterling(office_key: str, week_start: dt.date, *,
                  dry_run: bool = True, log=print) -> int:
    """BG Status, off the ICDs' shared Sterling inbox.

    SKIPPED, NOT FAILED, where that inbox's app password is not installed.
    This reads ONE inbox shared by every office and writes through Sheets, so
    it does not have to run on the office's own machine -- it has to run
    wherever the password is, once. A box without it is not broken; it simply
    is not the one that does this job, and failing the whole hourly run over a
    credential it was never given makes every other step's result look like an
    outage (Lucy 2, 2026-11-10).

    Nothing is ticked on the way past, so a skipped pass can never be mistaken
    for "nobody has a result" ([[feedback_empty_means_proven_zero]]).
    """
    from automations.icd_onboarding import bg_status

    from automations.icd_alerts import code_answer as CA
    path = bg_status.APP_PW_PATH or str(CA.RESULTS_APP_PW)
    if not pathlib.Path(path).exists():
        log("  sterling: this machine has no %s password — skipped. BG Status "
            "fills from whichever box holds it." % bg_status.INBOX)
        return 0
    return bg_status.run(week_start, offices=[office_key],
                         dry_run=dry_run, log=log)


def reception_account(office_key: str) -> str:
    """The office's OWN reception Gmail, off the second-round roster.

    Megan, 2026-11-11: "each ICD will have their own reception email" -- so
    this is a per-office login like OwnerVille or Blue Ink, not one account
    every office would have to be given a key to.
    """
    from automations.second_round_contacts import roster as SR
    want = str(_appstream_id(office_key) or "").strip()
    if not want:
        return ""
    for o in SR.read():
        if want in [str(x).strip() for x in (o.offices or [o.office])]:
            return str(o.account or "").strip()
    return ""


def from_contacts(office_key: str, week_start: dt.date, *,
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
    from automations.icd_onboarding import sheet as S
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



# THE TWO THAT ACT, kept LAST and in this order (Megan, 2026-11-15: "do 1
# and 2"). Both live in presses.py; see there for why the re-point was the
# campaign and not the press.
#
# ORDER MATTERS AND IS THE WHOLE REASON THEY SIT HERE. `ownerville` reads
# first, so both presses work off what OwnerVille says this minute rather than
# off a board that is up to an hour old. `uid` runs before `owner_submit`
# because a requested UID is one of Owner Submit's own prerequisites: pressed
# the other way round, every person whose only gap was the UID would be
# refused, and then requested, and would wait a whole pass to be submitted.
from automations.icd_onboarding.presses import (press_owner_submit,
                                                uid_reasons)

STEPS = (("seed", seed), ("ownerville", from_ownerville),
         ("blueink", from_blueink), ("sterling", from_sterling),
         ("contacts", from_contacts),
         ("owner_submit", press_owner_submit),
         # Read-only, hand-run, and in no machine's list. There is no UID
         # press: OwnerVille's own section says the rep submits the ATTUID
         # form in the Candidate Roadmap Portal and the send to AT&T fires off
         # SaraPlus activation. This reads WHOSE MOVE each outstanding one is.
         ("uid_reasons", uid_reasons),
         # WHO WAS MARKED NO in ApplicantStream -- the signal that somebody is
         # not starting, which this board had no way to carry until now
         # (Megan, 2026-11-16). Hand-run: it is the seven-page calendar walk.
         ("no_shows", from_no_shows))

# STEPS THAT NO MACHINE RUNS ON A SCHEDULE, each one listed with its reason.
# Every other step must be routed to exactly one box, and the test that pins
# that reads this list -- so a new hand-run step fails until it is named here
# rather than quietly joining the ones nobody runs.
#
#   uid_reasons  read-only. It opens OwnerVille to say whose move each
#                outstanding AT&T UID is. Useful before a nudge, not hourly --
#                and it holds the one OwnerVille session while it runs.
HAND_RUN_ONLY = ("uid_reasons",)

# STEPS THAT RUN ON A CLOCK OF THEIR OWN rather than on the hourly board run.
# Unrouted here for the same reason HAND_RUN_ONLY is -- so the coverage test
# still fails for a NEW step nobody runs -- but these are scheduled, just not
# hourly, and each one's LaunchAgent is named beside it.
#
#   no_shows     com.alphalete.icd-onboarding-no-shows, daily 19:30 on the box
#                holding this office's ApplicantStream session. It is the
#                SEVEN-page calendar walk; the hourly run stopped walking the
#                calendar when the two-page Retention Report turned out to
#                answer the seed's question (Megan, 2026-11-09), and putting
#                the walk on an hourly clock would undo that. The answer only
#                changes when a recruiter marks a radio, so daily is enough
#                (Megan, 2026-11-16: "run it daily"). The evening matters: the
#                training day has to have happened, and it lands before the
#                next morning's 7:30am Blue Ink send, which is what this
#                column stops for somebody who did not come.
OWN_CLOCK = ("no_shows",)

# Every step must be accounted for: routed to a machine, hand-run, or on its
# own clock. The coverage test reads this, so a new step fails until it is
# named somewhere.
UNROUTED = HAND_RUN_ONLY + OWN_CLOCK


def for_office(office_key: str, week_start: dt.date, *, dry_run: bool = True,
               only: Sequence[str] = (), log=print) -> Dict[str, object]:
    """Every step for one office. Never stops on one failing."""
    out: Dict[str, object] = {}
    for name, fn in STEPS:
        if only and name not in only:
            continue
        log("%s · %s" % (office_key, name))
        try:
            out[name] = fn(office_key, week_start, dry_run=dry_run, log=log)
        except Exception as e:  # noqa: BLE001
            # One source being down is not a reason to skip the others.
            out[name] = "%s: %s" % (type(e).__name__, str(e)[:160])
            log("  ✗ %s" % out[name])
    return out


# WHICH BOARD A FLEET RUNNER WORKS. An ICD's own computer needs no entry --
# its enrolment names its office. A Lucy is not enrolled for anybody, so the
# board it works is routed here, the way applicant_push routes its offices.
#
# THE BOARD RUNS WHERE THAT OFFICE'S OWNERVILLE IS. That is the constraint
# that decides this, and it is not negotiable: five of the nine columns are
# read off View Progress, and a machine signed in as somebody else sees none
# of this office's reps. Lucy 2 was tried for a morning on 2026-11-10 and
# found 0 of 10 -- its OwnerVille account is `chidalgo`, Carlos's. Nothing was
# wrongly ticked, because unread never ticks, but those columns could never
# have filled. Lucy 3 is `rhidalgo`, Raf's, which is why the OBCL sweep for
# the same people already lives there.
#
# It also holds a warm AppStream session (Lucy 1/2/3 do; Lucy 4's
# holds_appstream is off on purpose, and fleet.py calls turning it on "the one
# Lucy 4 change that can cost the LIVE fleet"), and seed cannot work without
# one -- Megan's Mac could not keep a session alive for an hour.
#
# NOT MEGAN'S MAC, which ran this for one evening and could not keep an
# AppStream session alive: saved at 22:00, working at 22:02, rejected by 22:53.
# No session holder there, and the credential is deliberately not on her
# laptop, so every expiry needed her at the keyboard.
#
# NOT LUCY 4, whose `holds_appstream` is off on purpose -- fleet.py calls
# turning it on "the one Lucy 4 change that can cost the LIVE fleet", because
# a second session competes for the token the 4am batches share.
OFFICES_BY_MACHINE = {
    "Lucy 3": ("raf",),
    # These two run SOME of this office's steps -- see STEPS_BY_MACHINE.
    "Lucy 1": ("raf",),
    "Lucy 2": ("raf",),
}

# WHICH STEPS A MACHINE IS RESPONSIBLE FOR. Absent from here means all of them,
# which is what an ICD's own computer does: its office's logins are all on it.
#
# Alphalete's are not. Each source sits where its credential or its data is,
# and a step run anywhere else does not fail -- it quietly finds nothing, which
# is the worst way for this to be wrong. So the split is written down:
#
#   Lucy 3  OwnerVille and AppStream: its OwnerVille account is Raf's
#           (`rhidalgo`) and it holds a warm AppStream session.
#   Lucy 2  Blue Ink, because the signed-in Blue Ink session is there -- it is
#           the box the Blue Ink completed-sweep already runs on. Lucy 3 was
#           tried on 2026-11-10 and answered "No Blue Ink session".
#   Lucy 1  contacts, because `second_round_contacts` runs there and its state
#           file -- the record of every contact it has created -- is a local
#           file on that box. Read from anywhere else it is simply absent.
#           Sterling too: it reads the one inbox every office forwards to, and
#           Lucy 1 is the machine that already reads that inbox to confirm the
#           forwards. Where the password is not installed the step says so and
#           ticks nothing.
#
# The tick itself goes through Sheets, so a step reaches any office's board
# from whichever machine runs it.
# The two presses go where the OwnerVille session already is -- Lucy 3 holds
# it, and a second machine driving OwnerVille is the profile collision this
# fleet has paid for before ([[reference_browser_profile_collisions]]). They
# are also the only steps here that ACT, so keeping them on one box keeps
# "who pressed this" answerable.
STEPS_BY_MACHINE = {
    "Lucy 1": ("contacts", "sterling"),
    "Lucy 2": ("blueink",),
    "Lucy 3": ("seed", "ownerville", "owner_submit"),
}

# A machine that is neither a Lucy nor an ECO box can still name its offices,
# one key per line. A FILE, not the committed plist: the same plist is
# installed on every box, so an office key written into it would have every
# ECO machine working somebody else's board.
OFFICES_FILE = (pathlib.Path.home() / ".config" / "recruiting-report"
                / "icd-onboarding-offices")


def this_machine() -> str:
    """Which box this is, for the routing tables above. "" when unknown.

    `hub_identity.machine_name()` reads the gitignored `.machine-profile`
    marker and otherwise falls back to the HOSTNAME -- so on a Lucy whose
    marker is missing it answers "Lucys-Mac-mini.local", that misses both
    tables, and the box silently runs EVERY step instead of its own two. The
    failure is invisible: a step on the wrong box reads nothing and ticks
    nothing, which looks exactly like a quiet day.

    So an unrecognised answer is tried against `fleet.HOSTNAMES`, the curated
    hostname list (four nearly-identical names -- `Lucys-Mac-mini.local` is
    Lucy 3 and `Lucys-MacBook-Neo` is Lucy 2, so nothing here guesses from the
    word "lucy").

    UNKNOWN STAYS UNKNOWN. An ICD's own computer is deliberately in neither
    table and must run every step, so this never falls back to a Lucy's name
    the way `mini_control._machine_profile()` does -- that would have an
    office's machine running Alphalete's split.
    """
    try:
        from automations.shared import hub_identity as HI
        said = (HI.machine_name() or "").strip()
    except Exception:          # noqa: BLE001 — identity is never fatal here
        return ""
    if said in STEPS_BY_MACHINE or said in OFFICES_BY_MACHINE:
        return said
    try:
        from automations.shared import fleet
    except Exception:          # noqa: BLE001
        return said
    low = said.lower().removesuffix(".local")
    for name, hosts in fleet.HOSTNAMES.items():
        for h in hosts:
            if low == h.lower().removesuffix(".local"):
                return name
    return said


def offices_here() -> List[str]:
    """The offices THIS machine should work.

    In order: the env var, this runner's routed board, this machine's file,
    then its ECO enrollment. So the
    hourly run takes no arguments on an ECO box -- the machine already knows
    whose logins it holds, and a key typed into a plist is a key that goes
    stale the day an office is re-enrolled. An office running two campaigns has
    one board, so the keys are de-duplicated by office.
    """
    import os
    named = os.environ.get("ICD_ONBOARDING_OFFICES", "")
    if not named:
        routed = OFFICES_BY_MACHINE.get(this_machine())
        if routed:
            return list(routed)
    if not named and OFFICES_FILE.exists():
        try:
            named = OFFICES_FILE.read_text(encoding="utf-8")
        except Exception:      # noqa: BLE001
            named = ""
    if named:
        out = []
        for line in named.replace(",", "\n").splitlines():
            key = line.strip().lower()
            if key and not key.startswith("#") and key not in out:
                out.append(key)
        if out:
            return out
    try:
        from automations.icd_alerts import config as AC
        rows = AC.enrollments()
    except Exception:          # noqa: BLE001 — not an ECO machine
        return []
    out = []
    for r in rows:
        key = str(r.get("office_key") or "").strip().lower()
        # A second campaign's key hangs off the same office (jamis / jamis10);
        # the board is the office's, so the first one wins.
        base = key.split("-")[0]
        if key and base not in out:
            out.append(base)
    return out


def steps_here() -> Sequence[str]:
    """The step names this machine runs. () means "all of them".

    An explicit --only always wins; this is only the default for a scheduled
    run that was given no arguments.
    """
    import os
    named = os.environ.get("ICD_ONBOARDING_STEPS", "")
    if named:
        return tuple(x.strip() for x in named.replace(",", " ").split() if x.strip())
    return tuple(STEPS_BY_MACHINE.get(this_machine()) or ())


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Bring an onboarding board up to date.")
    ap.add_argument("--office", action="append", default=[],
                    help="office key; repeatable. Left out, this machine's own.")
    ap.add_argument("--week", default=None,
                    help="YYYY-MM-DD in the week (default: this week)")
    ap.add_argument("--only", action="append", default=[],
                    choices=[n for n, _ in STEPS],
                    help="just these steps; repeatable")
    ap.add_argument("--write", action="store_true",
                    help="actually write (default is a dry run)")
    a = ap.parse_args(argv)
    # THE CURRENT WEEK, always (Megan, 2026-11-09: "OBCL should just always be
    # active for that current week"). Monday-normalised by week_label, so an
    # hourly run on a Thursday works the same board it worked on Monday.
    week = dt.date.fromisoformat(a.week) if a.week else dt.date.today()
    offices = a.office or offices_here()
    only = list(a.only) or list(steps_here())
    if not offices:
        print("no office to run: pass --office, or run this on a machine that "
              "is enrolled for one.")
        return 1
    # SAY WHICH BOX THIS IS AND WHAT IT IS RESPONSIBLE FOR. Each step runs on
    # the machine holding its data, and a step on the wrong box reads nothing
    # rather than failing -- so a log that does not name the split cannot be
    # told apart from a quiet day.
    _me = this_machine() or "this machine"
    print("%s · %s · steps: %s"
          % (_me, ", ".join(offices), ", ".join(only) if only else "all"))
    if not a.write:
        # A DRY RUN TELLS THE HUB NOTHING. It writes no cell, so there is
        # nothing to report as done -- and a probe whose source could not be
        # reached must not turn this card red for everybody (2026-11-15).
        try:
            from automations.shared import hub_autopublish
            hub_autopublish.nothing_to_report()
        except Exception:      # noqa: BLE001 — never fail a run over the pill
            pass

    bad = 0
    for office in offices:
        got = for_office(office, week, dry_run=not a.write, only=only)
        bad += sum(1 for v in got.values() if isinstance(v, str))
        print()
    if not a.write:
        print("(dry run — nothing was written. --write to do it for real.)")
    elif not bad:
        _record_delivery(offices)
    return 1 if bad else 0


def _record_delivery(offices: Sequence[str]) -> None:
    """Today's manifest = the proof shared/delivery_check looks for.

    2026-11-09 to 11-11 every failure-icd_onboarding ticket stayed open after
    a clean re-run — "ran clean, but nothing can confirm it DELIVERED" —
    because this board wrote no manifest. Only a clean --write pass records
    one, so a dry run or a pass with a failed step never fakes the proof.
    Never raises."""
    try:
        from automations.shared import run_manifest
        run_manifest.write_manifest(
            "icd_onboarding", succeeded=list(offices),
            note="board up to date for %s" % ", ".join(offices))
    except Exception as e:  # noqa: BLE001 — the proof must never fail the run
        print("manifest skipped: %s: %s — the board is written, but a failure "
              "ticket won't close itself" % (type(e).__name__, str(e)[:120]))


if __name__ == "__main__":
    raise SystemExit(main())
