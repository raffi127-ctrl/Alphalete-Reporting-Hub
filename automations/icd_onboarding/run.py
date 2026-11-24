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
import time
from typing import Dict, List, Optional, Sequence

from automations.icd_onboarding import board as B
from automations.icd_onboarding import fillers as F


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


def _ov_program(office_key: str) -> str:
    from automations.office_admin import config as OC
    o = OC.office(office_key)
    return (getattr(o, "ov_program", "") if o else "") or ""


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
    from automations.obcl_ov_sweep.run import PROFILE_DIR

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
    """The office's own reception Gmail. Lives in `eco_steps`, which SHIPS.

    Kept here as a name because this module is what every Hub caller and the
    tests reach for; the body moved so an office's own computer can run the
    step itself (Megan, 2026-11-24: "we need it to work like lucy eco does").
    One implementation, not a Hub copy and an office copy drifting apart.
    """
    from automations.icd_onboarding import eco_steps as ES
    return ES.reception_account(office_key)


def from_contacts(office_key: str, week_start: dt.date, *,
                  dry_run: bool = True, log=print) -> int:
    """Contact Added. The step itself is `eco_steps.contacts`, which SHIPS to
    the office's own computer; this is the Hub's name for it."""
    from automations.icd_onboarding import eco_steps as ES
    return ES.contacts(office_key, week_start, dry_run=dry_run, log=log)



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

STEPS = (("seed", seed), ("seed_names", seed_names),
         ("ownerville", from_ownerville),
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
#   no_shows     com.alphalete.icd-onboarding-no-shows, daily 21:15 on the box
#                holding this office's ApplicantStream session. 21:15 and not
#                the 19:30 it shipped with: :30 is the hourly board run's
#                minute, the walk's wrapper skips itself when it sees that
#                module running, so it met the board run on its first fire and
#                every fire after -- correct in every part and never once
#                doing its job (ff1f506, 2026-11-20). It is the
#                SEVEN-page calendar walk; the hourly run stopped walking the
#                calendar when the two-page Retention Report turned out to
#                answer the seed's question (Megan, 2026-11-09), and putting
#                the walk on an hourly clock would undo that. The answer only
#                changes when a recruiter marks a radio, so daily is enough
#                (Megan, 2026-11-16: "run it daily"). The evening matters: the
#                training day has to have happened, and it lands before the
#                next morning's 7:30am Blue Ink send, which is what this
#                column stops for somebody who did not come.
#   seed_names   com.alphalete.icd-onboarding-seed, :00/:15/:45 from 6am to
#                8:45pm on the box holding this office's ApplicantStream
#                session. It is `seed` with the Showed Up half left off, so
#                the names land within 15 minutes of a BOB (Megan,
#                2026-11-22). NOT at :30: the hourly board run fires at half
#                past and seeds as its first step, so a :30 pass would be the
#                same work twice, racing itself for the one AppStream session.
OWN_CLOCK = ("no_shows", "seed_names")

# Every step must be accounted for: routed to a machine, hand-run, or on its
# own clock. The coverage test reads this, so a new step fails until it is
# named somewhere.
UNROUTED = HAND_RUN_ONLY + OWN_CLOCK


def _mmss(seconds: float) -> str:
    """'3m07s' / '47s'. Minutes only once there are minutes, so a quick step
    does not read as a slow one."""
    whole = int(round(seconds))
    return ("%dm%02ds" % (whole // 60, whole % 60)) if whole >= 60 else "%ds" % whole


def for_office(office_key: str, week_start: dt.date, *, dry_run: bool = True,
               only: Sequence[str] = (), log=print) -> Dict[str, object]:
    """Every step for one office. Never stops on one failing."""
    out: Dict[str, object] = {}
    # HOW LONG EACH STEP TOOK. Measured 2026-11-19: one office on Lucy 3 took
    # 19m19s (12:30:03 to 12:49:22) and ticked NOTHING, so the time is spent
    # waiting on pages rather than doing work. That matters because the board
    # is meant to move to each ICD's own machine and scan every 15 minutes
    # (Megan): a run longer than the gap means the `pgrep` guard drops ticks
    # and the real cadence quietly becomes the runtime. A total alone cannot
    # say WHICH step to fix, so each one is timed and they are printed slowest
    # first -- costs one clock read per step.
    spent: List[tuple] = []
    for name, fn in STEPS:
        if only and name not in only:
            continue
        log("%s · %s" % (office_key, name))
        started = time.monotonic()
        try:
            out[name] = fn(office_key, week_start, dry_run=dry_run, log=log)
        except Exception as e:  # noqa: BLE001
            # One source being down is not a reason to skip the others.
            out[name] = "%s: %s" % (type(e).__name__, str(e)[:160])
            log("  ✗ %s" % out[name])
        finally:
            # In `finally` on purpose: a step that THREW is the one most worth
            # timing, and it is also the one a plain line after the call would
            # never reach.
            took = time.monotonic() - started
            spent.append((took, name))
            log("  · %s took %s" % (name, _mmss(took)))
    if spent:
        total = sum(t for t, _ in spent)
        log("%s · %s in all: %s" % (office_key, _mmss(total), ", ".join(
            "%s %s" % (n, _mmss(t)) for t, n in sorted(spent, reverse=True))))
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
        # A second campaign's key hangs off the same office and the board is
        # the OFFICE's, so every campaign reduces to one key. ONE DEFINITION,
        # in config: the suffix is spelt two ways (carlos-b2batt, jamis10) and
        # the rule here handled only the dash -- so `jamis10` asked for a
        # board nothing owns and read as empty (2026-11-24).
        base = AC.base_office_key(key)
        if key and base and base not in out:
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
    ap.add_argument("--if-due", action="store_true",
                    help="do nothing unless this hour's band says a pass is "
                         "due (icd_onboarding.cadence) -- for the agent")
    a = ap.parse_args(argv)
    # FOR THE SCHEDULED CALLER ONLY. The agent fires on the band's own minutes
    # -- 39 times a day since 2026-11-24 -- because launchd cannot say "every
    # 15 minutes between 8 and noon"; the band is decided here instead. A HAND
    # RUN never passes this and always runs, which is the whole point of the
    # flag being opt-in: "it did nothing and said nothing" is a terrible answer
    # to somebody who typed the command themselves.
    if a.if_due:
        from automations.icd_onboarding import cadence as CAD
        if not CAD.due():
            print("not due yet (every %d min this hour; last ran %s)"
                  % (CAD.every_minutes(), CAD.last_run() or "never"))
            return 0
        CAD.mark_run()
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
