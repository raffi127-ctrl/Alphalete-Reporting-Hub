"""New starts -> Apex, on the office's OWN computer.

Megan, 2026-11-06: "what if the ICDs relay machine also just logs into apex and
blueink -- the admin is just saying the task should run and who to run it for?"

The admin holds neither login. This machine holds both: that office's Blue Ink
key and an Apex session its owner signed into by hand (`icd_alerts.apex_signin`,
the same rule as box_signin -- no password is ever typed by Lucy). So the admin
presses a button, the relay carries one fact -- WHICH WEEK -- and everything
else happens here.

    admin    -> relay   "apex_week, week of 2026-11-02"      (admin session)
    here     <- relay   that job, handed out once            (office key)
    here     -> relay   who went in, who needs a hand        (office key)

WHO IS IN THE WEEK IS DECIDED HERE, NOT BY THE ADMIN. The job carries a date
and nothing else. This machine reads its own training calendar
(`office_admin.fdot` -- Show Up = Yes, Monday to Saturday, pooled) so a stale
or edited list cannot be posted in from outside. The same reasoning as the
account-number guard on background checks.

THE SOCIAL. From 2026-11-06 this machine may hold one, which Megan decided
after noting that the operator already previews the signed tax document and
copies the number out by hand. It is asked for only when this is actually going
to type it (`live`), it arrives wrapped as a `Secret`, it is never written down
and it cannot reach the result: `json.dumps` refuses a Secret, so a mistake
here fails loudly rather than posting a Social to a Google Sheet. A dry run
never asks for one at all.

WHAT THIS DOES AND DOES NOT DO YET. The whole pipeline up to the typing is
here and testable: roster -> Blue Ink -> per-person values -> what is ready and
what is missing. The typing itself calls the existing Apex path, which has only
ever been driven with somebody watching, so `live=True` is deliberately gated
and the default is a dry run that reports exactly what it would do.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from automations.apex_new_starts import apex
from automations.apex_new_starts import blueink_data as BID

KIND = "apex_week"


@dataclass
class Starter:
    """One person off the training calendar, shaped the way `apex_values`
    expects a board Candidate. Separate from board.Candidate on purpose: this
    one comes from a calendar and has no sales-board row, no trainer and no
    roll -- inventing those to satisfy a constructor would be inventing data.
    """
    name: str
    email: str = ""
    phone: str = ""
    gender: str = ""
    hire_date: Optional[dt.date] = None
    source: str = "training calendar"


def starters(rows: List[Dict], day: Optional[dt.date] = None) -> List[Starter]:
    """fdot rows -> Starters. The training date IS the start date."""
    out = []
    for r in rows:
        name = ("%s %s" % (r.get("first_name", ""), r.get("last_name", ""))).strip()
        if not name:
            continue
        out.append(Starter(name=name, email=r.get("email", ""),
                           phone=r.get("phone", ""),
                           hire_date=r.get("started") or day))
    return out


def _name_disagreement(person, hire) -> str:
    """"" when the packet and AppStream agree about this person's name.

    Compared on the letters only: "McCrobie" vs "Mccrobie" is the same name
    written two ways, while "Davis" vs "Dav" is not. A packet that is simply
    missing a name is somebody else's problem (plan already holds them for a
    missing packet).
    """
    import re as _re

    def fold(t):
        return _re.sub(r"[^a-z]", "", str(t or "").lower())

    want = str(getattr(person, "name", "") or "").split()
    if not want or hire is None:
        return ""
    theirs_last, theirs_first = fold(hire.values.get("last")), \
        fold(hire.values.get("first"))
    ours_last, ours_first = fold(want[-1]), fold(want[0])
    bad = []
    if theirs_last and ours_last and theirs_last != ours_last:
        bad.append("last name: the signed packet says %r, AppStream says %r"
                   % (hire.values.get("last"), want[-1]))
    if theirs_first and ours_first and theirs_first != ours_first:
        bad.append("first name: the signed packet says %r, AppStream says %r"
                   % (hire.values.get("first"), want[0]))
    if not bad:
        return ""
    return ("their name does not match AppStream, so an admin has to say "
            "which is right before this goes on a payroll record — "
            + "; ".join(bad))


def plan(people: List[Starter], hires: Dict[str, BID.NewHire],
         log=print, office_key: str = "", watched: bool = False) -> Dict:
    """Who can go in, and why anybody cannot -- without touching Apex.

    Returns {ready: [(Starter, values)], blocked: [{name, why}]}. Nothing is
    invented: a gap is reported and the person is held back, never filled with
    a placeholder that lands on a payroll record.
    """
    # values, not run: run.py imports the sales board and so Google Sheets,
    # and an office Mac reads a calendar, not a board.
    from automations.apex_new_starts import values as V

    ready, blocked = [], []
    for p in people:
        hire = hires.get(p.name)
        if hire is None or hire.missing_packet:
            blocked.append({"name": p.name,
                            "why": "no signed Blue Ink packet — type this one by hand"})
            continue
        # THE NAME ON THE PACKET MUST MATCH APPSTREAM. Chrisjen Davis wrote
        # "Dav" in the Last Name box of his own I-9, so the packet said
        # Chrisjen Dav while AppStream -- which is what seeded the board --
        # said Chrisjen Davis. Creating him would have put "Chrisjen Dav" on
        # a payroll record, and nothing downstream would ever have matched
        # him again (Megan, 2026-11-15: "we would look at app stream and
        # flag it for the admin to approve what is correct and then you run
        # it").
        #
        # Nothing guesses which spelling is right -- a nickname, a married
        # name and a typo all look the same from here. It holds, and says
        # what each source claims.
        said = _name_disagreement(p, hire)

        values = V.apex_values(p, hire, office_key)
        if said:
            # NOT A BLOCK ON ITS OWN (Megan, 2026-11-15: "UNLESS you find it
            # in the pending where it matches app stream and you can just
            # know it's correct"). Being on Apex's Pending list under the
            # AppStream spelling IS the confirmation -- somebody already put
            # them there under that name. The triage is what establishes
            # that, so this travels with them and is settled there.
            values["_name_dispute"] = said
        # Rate of Pay is in here because Apex REFUSES THE SAVE without one,
        # and because it is the office's own number -- an office nobody has
        # asked has none, and that must hold the person back rather than
        # quietly paying them Alphalete's rate (Megan, 2026-11-12).
        # GENDER IS IN HERE NOW (Megan, 2026-11-13: "we need to only run on
        # the ones I gave you genders for"). Apex refuses the profile tab
        # without one, so starting somebody who has none does not fail
        # early -- it saves the employment tab and then stops, leaving a
        # part-filled record and a person who looks half done. Nothing
        # guesses a gender, so a blank one holds them here, before anything
        # is typed.
        # THE TWO STATE FIELDS HOLD TOO (2026-11-22). `values.apex_values`
        # already DROPS pay_state and tax_state for an office that has not
        # answered them, and says why: "so the person is held back and named
        # rather than filed under another company's state". The drop worked;
        # the hold did not, because this list never named them. Measured that
        # day: 0 of 41 offices have answered either, so all 26 of Raf's week
        # came back "ready" with no State Working In and no State to be taxed
        # in -- which a live run either gets refused for mid-save, leaving the
        # part-filled record described just above, or lands as a blank state
        # on a tax record.
        #
        # Raf's own Apex work does not come through here: the Hub card's
        # button calls apex_values with NO office_key, so nothing is dropped
        # and his records keep Texas and his rate. This path is the ECO build.
        PACKET = ("dob", "address1", "city", "zip")
        FROM_THE_OFFICE = ("rate", "pay_state", "tax_state")
        gaps = [lbl for lbl in PACKET + FROM_THE_OFFICE + ("gender",)
                if not values.get(lbl)]
        # A BLANK GENDER HOLDS, WATCHED OR NOT. Gender is assumed from the
        # first name (Megan, 2026-11-24: "remember that we're assuming gender
        # based on name"), and `gender_suggest` deliberately returns blank
        # rather than flip a coin on a name like Kimble.
        #
        # An earlier cut let a watched run through on a blank and left the
        # Gender dropdown for the person to set on the form. Megan,
        # 2026-11-24: "no, I shouldn't have to fill anything on apex" -- that
        # is the one thing this is supposed to spare them. So gender is
        # confirmed BEFORE the fill now, in the pop-up the Send button raises
        # or with --gender on a one-person sitting, and then it is TYPED like
        # every other value. A blank still holds, because the alternative is
        # guessing onto a payroll record with no undo.
        #
        # `watched` therefore no longer relaxes anything here. It is still
        # accepted because supervised.py passes it; it is a candidate for
        # removal, not a switch that does something subtle.
        if gaps:
            # Named by WHERE THE ANSWER LIVES, because each sends somebody
            # somewhere different: the packet means Blue Ink, the enrolment
            # means ask the ICD, the gender means the board. One message that
            # says "missing pay_state" sends them to read a packet that was
            # never going to have it.
            ours = [g for g in gaps if g in FROM_THE_OFFICE]
            theirs = [g for g in gaps if g in PACKET]
            says = []
            if theirs:
                says.append("their packet is missing " + ", ".join(theirs))
            if ours:
                nice = {"rate": "Rate of Pay", "pay_state": "State Working In",
                        "tax_state": "State to be taxed in"}
                says.append("this office's enrolment has no %s — ask the ICD "
                            "and add it" % ", ".join(nice[g] for g in ours))
            if "gender" in gaps:
                says.append("no gender — %r is not a first name the guesser "
                            "will call, so it has to be confirmed before the "
                            "send (the pop-up, or --gender on a sitting). "
                            "Nothing here guesses it onto a payroll record"
                            % (p.name.split()[0] if p.name.split() else p.name))
            why = "; ".join(says)
            blocked.append({"name": p.name, "why": why})
            continue
        ready.append((p, values))
    log("  %d ready, %d held back" % (len(ready), len(blocked)))
    return {"ready": ready, "blocked": blocked}


def _result(week_start: dt.date, *, status: str, added=(), blocked=(),
            error: str = "", counted: int = 0, live: bool = False,
            apex=None, people=None) -> Dict:
    """The job's answer. Plain JSON -- names and reasons, never a number.

    Built in one place so there is one thing to read when asking "could a
    Social end up on the relay?". It cannot: nothing here comes from `ssn`,
    and a Secret would make json.dumps raise on the way out.
    """
    out = {"status": status, "week_start": week_start.isoformat(),
           "counted": counted, "added": list(added),
           "needs_hand": [dict(b) for b in blocked],
           "mode": "live" if live else "dry"}
    if error:
        out["error"] = error
    if people is not None:
        # THE PREVIEW'S LIST: name and the gender that would be used, so the
        # person sending can change one before they press Send. Names and
        # one word each -- nothing from the packet, same rule as the rest.
        out["people"] = [dict(p) for p in people]
    if apex is not None:
        # WHAT APEX ALREADY HOLDS, beside what the data says is ready. Names
        # only -- the same rule as everything else in here.
        out["apex"] = {k: list(v) for k, v in apex.items()}
    return out


def run_week(week_start: dt.date, *, office_appstream: str, office_key: str = "",
             live: bool = False, log=print, genders: Dict = None,
             preview: bool = False) -> Dict:
    """The whole job. Returns a result dict; raises nothing the caller must
    catch for correctness (office_jobs also guards, belt and braces)."""
    from automations.office_admin import fdot

    monday = week_start - dt.timedelta(days=week_start.weekday())
    try:
        # WHICHEVER APPLICANTSTREAM THIS MACHINE HAS. This job runs on the
        # OFFICE's computer (Megan, 2026-11-11: "apex has to run on the ECO
        # machine since it's that ICDs independent login"), and the warm
        # console `applicantstream.session` binds to lives only on a Lucy --
        # so that import was the one line here that could not resolve where
        # the job actually runs. `sessions.appstream_anywhere` reads the
        # office's own Chrome there and the warm console on a Lucy.
        from automations.icd_onboarding import sessions as SES
        with SES.appstream_anywhere(office_key, log=log) as app:
            rows = fdot.read_week(app, office_appstream, monday, log=log)
    except Exception as e:  # noqa: BLE001
        # A calendar that cannot be read is NOT an empty week. Saying "0 new
        # starts" here would quietly leave real people off payroll.
        return _result(monday, status="error", live=live,
                       error="could not read the training calendar: %s: %s"
                             % (type(e).__name__, str(e)[:200]))

    people = starters(rows, day=monday)
    if not people:
        return _result(monday, status="none", live=live, counted=0)

    # ONLY PEOPLE STILL ON THE OBCL (Megan, 2026-11-11: "you should only add
    # those then NOT removed from the OBCL"). The calendar says who showed up
    # for training; the board says who is still going through onboarding, and
    # between the two somebody quits, no-shows or fails a check. An Apex record
    # is a payroll record with no undo, so the board's removals win.
    try:
        gone = _removed_on_the_board(office_key, monday, log=log)
    except Exception as e:  # noqa: BLE001
        # A board that cannot be read is NOT a board with nobody removed.
        # Carrying on here would put somebody the ICD removed onto payroll.
        return _result(monday, status="error", live=live, counted=len(people),
                       error="could not read the onboarding board, so who was "
                             "removed is unknown: %s: %s"
                             % (type(e).__name__, str(e)[:200]))
    if gone:
        from automations.icd_onboarding import board as _B
        kept = [p for p in people if _B._fold(p.name) not in gone]
        log("  %d removed on the board -- not going to Apex (%d left)"
            % (len(people) - len(kept), len(kept)))
        people = kept
        if not people:
            return _result(monday, status="none", live=live, counted=0)

    # The Social is asked for ONLY when this run is going to type it.
    try:
        hires = BID.for_people(people, keep_ssn=live)
    except Exception as e:  # noqa: BLE001
        return _result(monday, status="error", live=live, counted=len(people),
                       error="Blue Ink: %s: %s" % (type(e).__name__, str(e)[:200]))

    # GENDER, BEFORE THE PLAN. `starters()` builds people from the training
    # calendar, which has no such column, so without this every single person
    # would be held for "no gender". It is guessed from the first name here
    # rather than read off the board (Megan, 2026-11-24) -- `plan` still holds
    # anybody it would not call, which is the point (Megan, 2026-11-13), and a
    # value somebody has already typed is never overwritten.
    # WHAT THE ADMIN CONFIRMED WINS OVER WHAT WAS GUESSED. Megan,
    # 2026-11-24: "when someone pushes the button to send to apex - we should
    # pop up the names and gender we assume - then the admin/icd sending can
    # change if they want before hitting send." So the guess is a DRAFT shown
    # before the send, and whatever comes back in the payload is an answer a
    # person gave. An answer is never re-guessed and never overwritten.
    said = {}
    if genders:
        from automations.icd_onboarding import board as _B
        said = {_B._fold(k): v for k, v in (genders or {}).items() if v}
    guessed = _genders_for(people, log=log)
    from automations.icd_onboarding import board as _B
    byk = {_B._fold(k): v for k, v in (guessed or {}).items()}
    for _p in people:
        if _p.gender:
            continue
        key = _B._fold(_p.name)
        _p.gender = said.get(key) or byk.get(key, "")
    if said:
        log("  %d gender(s) confirmed by the person sending" % len(said))

    # THE POP-UP'S DATA. A preview opens nothing and saves nothing: it is the
    # list the admin is shown before they press Send -- every name in the
    # week, the gender we would use, and whether that came from a person or
    # from the guesser. Built from the SAME people list the send will use, so
    # what is confirmed is what goes in.
    if preview:
        return _result(
            monday, status="preview", live=False, counted=len(people),
            added=[], blocked=[],
            people=[{"name": _p.name,
                     "gender": _p.gender,
                     "from": ("confirmed" if _B._fold(_p.name) in said
                              else ("guessed" if _p.gender else "unknown"))}
                    for _p in people])

    got = plan(people, hires, log=log, office_key=office_key)
    if not live:
        # AND ASK APEX WHO ACTUALLY NEEDS ANYTHING (2026-11-23). "26 ready"
        # only ever meant "26 have complete data" -- it says nothing about
        # whether Apex already holds them. Alexis Justice and Brandon
        # Aceituno were both ACTIVE and both still sat on the Pending list,
        # so the plan named them as work and the only way to find out
        # otherwise was a supervised run, one person at a time.
        #
        # Read-only: triage opens no record and types nothing. If Apex cannot
        # be reached the dry run still answers with the data half it always
        # had and says the Apex half is unknown -- a plan that quietly
        # dropped back to the old meaning is what made this invisible.
        state = _apex_state([p for p, _ in got["ready"]], log=log)
        return _result(monday, status="dry_run", live=False,
                       counted=len(people),
                       added=[p.name for p, _ in got["ready"]],
                       blocked=got["blocked"], apex=state)

    # THE GATE IS CLEARED (Megan, 2026-11-24: "clear the gate"). It asked
    # for one thing -- somebody watches a record go in -- and that happened:
    # Luis Frias was filled by this code and saved on screen.
    #
    # EVERYTHING BELOW STILL SAVES TO A REAL PAYROLL RECORD, so the checks
    # that matter are the ones further in, not this flag: `plan` holds back
    # anybody with a gap, `fill_one` refuses a box that did not take its
    # value, and `save_tab` refuses a tab that is wrong or incomplete. The
    # flag only ever said "nobody has watched one yet", and now somebody
    # has.

    # NOBODY IS WATCHING THIS ONE -- no window on the owner's screen.
    with apex.ApexSession(log=log, visible=False) as s:
        s.require_login()
        out = fill_week(s.page, got["ready"], hires, monday,
                        genders=genders, log=log)
    added = out["added"]
    blocked = list(got["blocked"]) + out["blocked"]
    _tell_the_board(office_key, monday, added, log=log)
    _ask_the_board(office_key, monday,
                   {b["name"]: b["why"] for b in out.get("blocked", ())
                    if b.get("ask")}, log=log)
    return _result(monday, status="filled", live=True, counted=len(people),
                   added=added, blocked=blocked)


def _apex_state(ready, log=print) -> Dict:
    """{verdict: [name, ...]} for the people the data says are ready.

    READS ONLY. It opens Apex, triages, and closes -- no record is opened and
    nothing is typed. The point is to answer "who is actually left" without
    somebody sitting through one supervised run per name.
    """
    names = [p.name for p in (ready or [])]
    if not names:
        return {}
    try:
        with apex.ApexSession(log=log, visible=False) as s:
            s.require_login()
            from automations.apex_new_starts import drive
            if not drive.to_roster(s.page, log=log):
                return {"unknown": names}
            need = drive.triage(s.page, [{"name": n} for n in names], log=log)
    except Exception as e:          # noqa: BLE001
        # NOT A FAILED DRY RUN. The data half is still worth having, and an
        # unreachable Apex is reported as unknown rather than as nobody
        # needing anything.
        log("  could not ask Apex who is left (%s: %s)"
            % (type(e).__name__, str(e)[:120]))
        return {"unknown": names}
    out: Dict[str, List[str]] = {}
    for name in names:
        what = (need.get(name) or {}).get("need") or "unknown"
        out.setdefault(what, []).append(name)
    for what, who in sorted(out.items()):
        log("  Apex says %d %s: %s"
            % (len(who), what,
               ", ".join(who[:6]) + (" ..." if len(who) > 6 else "")))
    return out


def _genders_for(people, log=print) -> Dict:
    """{name: Gender}, guessed from each FIRST NAME.

    NOT OFF THE BOARD ANY MORE (Megan, 2026-11-24: "gender now is just assumed
    based on name and does not belong on the OBCL. It'll only come into play on
    the Apex fill"). It was a column somebody had to check on a board where
    nothing waited on it; the only reader was ever this record.

    HERE IS THE RIGHT PLACE FOR A GUESS, and that is the point. Apex is typed
    with a person sitting at it, so a wrong guess is in front of the one human
    who can fix it before the record saves. On the board it was a quiet
    pre-filled cell on a payroll answer that nobody was prompted to look at.

    A NAME IT CANNOT CALL IS LEFT OUT, exactly as a blank column was: the
    engine then leaves that box alone and SAYS it missed it, rather than
    picking one. `gender_suggest` is the same guesser that used to pre-fill the
    column, so the answers do not change -- only where they are produced.
    """
    try:
        from automations.icd_onboarding import gender_suggest as GS
    except Exception as e:      # noqa: BLE001
        # Not fatal: the engine fills everything else and names the box it
        # could not set, which is visible on the record.
        log("  (no genders guessed: %s)" % type(e).__name__)
        return {}
    out, unsure = {}, []
    for p in people or []:
        # A Starter CARRIES ONE `name`. It has no first_name/last_name, and
        # reading those through getattr defaults meant every person fell
        # through the `continue` below -- so the guesser answered "nobody",
        # in silence, for everybody. Found 2026-11-25 on the first real
        # preview of Raf's week: 12 names in, 0 guessed and 0 unsure, which
        # is the giveaway. An empty unsure list next to an empty answer
        # cannot both be true unless nothing was looked at. The test that
        # covered this built its own person with those two attributes, so it
        # passed on a shape production never had.
        whole = str(getattr(p, "name", "") or "").strip()
        first = str(getattr(p, "first_name", "") or "").strip()
        last = str(getattr(p, "last_name", "") or "").strip()
        if whole and not (first or last):
            bits = whole.split()
            first, last = bits[0], " ".join(bits[1:])
        name = ("%s %s" % (first, last)).strip() or whole
        if not name:
            continue
        said = GS.suggest(first) if first else ""
        if said:
            out[name] = said
        else:
            unsure.append(name)
    log("  %d gender(s) from the first name" % len(out))
    if unsure:
        # THE UNSURE LIST IS THE LOAD-BEARING HALF, same as it was on the
        # board: a guess here lands on a payroll record, so "no idea" has to
        # look different from an answer.
        log("  %d name(s) it would not call: %s"
            % (len(unsure), ", ".join(sorted(unsure))))
    return out


def _removed_on_the_board(office_key: str, monday: dt.date,
                          log=print) -> set:
    """Folded names the office's board says are OFF for this week.

    An office with no board yet has nobody removed -- that is a real answer,
    not a missing one, so it returns empty rather than raising. Anything that
    goes WRONG while reading a board that does exist raises, because "I could
    not look" must never be mistaken for "nobody was removed".

    NO OFFICE KEY IS NOT AN OFFICE WITH NO BOARD. This used to return empty
    for a blank key, which is the exact mistake the paragraph above refuses:
    the caller is told nobody was removed when nothing was read. The CLI had
    no way to pass a key at all until 2026-11-22, so every run of it had this
    gate quietly off -- harmless on a dry run, and on a live one it is how
    somebody the ICD removed gets a payroll record.

    THROUGH `rows_anywhere` SINCE 2026-11-24, which is what lets this whole job
    ship to the office's own computer: on a Lucy it is a gspread read and on an
    office Mac it is the relay, and that machine has no Google access at all.
    It was the last Sheets call on the Apex path, and `package.py` has named it
    as the blocker since 11/11 -- "the removals have to reach the office another
    way (in the job, through the relay)". The relay IS that way.

    It also keeps the rule this function is built on: `rows_anywhere` RAISES
    when a board cannot be read rather than answering "nobody"
    ([[feedback_empty_means_proven_zero]]).
    """
    from automations.icd_onboarding import board as B
    from automations.icd_onboarding import fillers as F
    if not office_key:
        raise RuntimeError("no office key, so no board to read removals from")
    rows = F.rows_anywhere(office_key, monday, log=log)
    gone = set()
    for r in rows:
        if str(r.get(B.TERMINATED_AT) or "").strip():
            why = str(r.get(B.REMOVED_WHY) or "").strip() or "removed"
            name = ("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip()
            log("    off the board: %s (%s)" % (name, why))
            gone.add(B._fold(name))
    return gone


def _ask_the_board(office_key: str, monday: dt.date, asks, log=print) -> None:
    """Put what a person has to decide into the board's own Apex column.

    Megan, 2026-11-15, on a name the packet and AppStream spell differently:
    "that 'alert' needs to go back to the admin to approve the correct name so
    that you can run it". A refusal that only reaches a log reaches nobody.

    NEVER fails the run, the same reason the tick does not: the people who
    went in are already in.
    """
    if not office_key or not asks:
        return
    try:
        from automations.icd_onboarding import fillers as F
        F.alert(office_key, monday, "apex", asks, dry_run=False, log=log)
    except Exception as e:  # noqa: BLE001
        log("  (the board was not asked: %s: %s)"
            % (type(e).__name__, str(e)[:120]))


def _tell_the_board(office_key: str, monday: dt.date, added, log=print) -> None:
    """Tick 'Added to APEX' for everyone this run actually saved.

    The run knows who it saved at the moment it saves them, so it says so
    rather than something else working it out afterwards — the same shape as
    the contact sync ticking 'Contact Added' (Megan, 2026-11-09).

    NEVER fails the run. The payroll records are already saved by this point;
    raising here would report a failure for work that succeeded, and send
    somebody looking for people who are in fact in Apex. A board that did not
    get ticked is a visible gap on the board, which is the right place for it.
    """
    if not office_key or not added:
        return
    try:
        from automations.icd_onboarding import fillers as F
        F.tick(office_key, monday, "apex", added, dry_run=False, log=log)
    except Exception as e:  # noqa: BLE001
        log("  (the board was not ticked: %s: %s — the records ARE saved)"
            % (type(e).__name__, str(e)[:120]))


# The create form, by ng-model rather than by label. Read off the live page
# 2026-11-08 -- see resources/apex-form-controls.md, which is the only reason
# any of this is not guesswork.
#
# A plain text box takes the value. A "dropdown" is TWO HALVES: a widget the
# person clicks and a separate input carrying the chosen id, which is what the
# form submits -- so its model name ends in ID and typing a LABEL into it puts
# a word where an id belongs. Those are driven through the widget.
BY_MODEL = {
    "first":         "$ctrl.user.FirstName",
    "middle":        "$ctrl.user.MiddleName",
    "last":          "$ctrl.user.LastName",
    "username":      "$ctrl.userName",
    "account_email": "$ctrl.user.EmailAddress",
}

# label -> the id-carrying input beside the widget. Set through the widget.
BY_WIDGET_ID = {
    "position":      "$ctrl.employmentRecord.JobTitleID",
    "pay_frequency": "$ctrl.employmentRecord.PayFrequencyID",
    "pay_basis":     "$ctrl.employmentRecord.BasisOfPayID",
    "pay_state":     "$ctrl.stateWorkingIn",
    "department":    "$ctrl.employmentRecord.CompensationProfileID",
}

# Kendo widgets, driven through their own API.
KENDO = {"hire_date": "k-datepicker", "rate": "k-numerictextbox"}

# Sales Rep is a radio on $ctrl.roleID, value 11 (read off the live form).
ROLE_MODEL, ROLE_VALUE = "$ctrl.roleID", "11"

# NOTHING may write these. The first emails a real person; the second sits
# directly under Rate of Pay and is the wrong box for $10/hr.
NEVER = ("$ctrl.sendUserPassword", "$ctrl.employmentRecord.Salary")


FILL_JS = r"""(spec) => {
  /* THE CREATE FORM, AS IT IS NOW. Apex was rewritten: /employees/new has no
     jQuery, no Kendo and no Angular -- window.jQuery, window.$, window.kendo
     and window.angular are all undefined on it (probe_create, 2026-11-24).
     The `ng-model` attributes are STILL IN THE MARKUP as dead text, which is
     what made the old version look like it worked: every lookup found its
     element, nothing reported a miss, and Apex then refused to save because
     no binding had heard a thing.

     So nothing here goes through a framework. Each control is set on the DOM
     and told about it with the events a plain page listens for.

     THE PAIRED BOXES ARE THE WHOLE BUG. User Name, Account Email, Rate of
     Pay, Salary and Commission Threshold are each TWO inputs in one group: a
     visible one with no id, over the real one that carries the id and the
     value the form posts. Setting one and not the other is what produced a
     form that looked filled and still said "User Name is required"
     (Luis Frias, 2026-11-24). Everything here sets BOTH.

     THE DROPDOWNS ARE A <select> OVER A HIDDEN INPUT. The <select> has no
     name, so it does not post; the hidden input beside it does. Picking an
     option without mirroring its value into that hidden input leaves the
     page showing "Sales Rep" and posting nothing. */
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const done = [], missed = [];

  const group = el => el && el.closest('.form-group, .mb-3, .col, td, .row');

  /* The visible box sitting over a real one, if there is one. Same group, a
     typable input, not hidden, not the element itself, and with no id of its
     own -- the id is what marks the real one. */
  const twin = el => {
    const g = group(el);
    if (!g) return null;
    return [...g.querySelectorAll('input')].find(
      o => o !== el && !o.id && o.type !== 'hidden' && o.type !== 'checkbox'
           && o.type !== 'radio' && o.offsetParent) || null;
  };

  const tell = el => {
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    el.dispatchEvent(new Event('blur', {bubbles: true}));
  };

  const put = (el, val) => { el.value = val; tell(el); };

  /* Find a control by the ng-model attribute the spec names. The attribute is
     inert now, but it is still the most stable handle on the page: the ids
     carry a record-number suffix (PayRate_368) that changes per form. */
  const byModel = model =>
    document.querySelector('[ng-model="' + model + '"]');

  const setText = (model, val) => {
    const el = byModel(model);
    if (!el) { missed.push(model + ' (no control)'); return; }
    put(el, val);
    const t = twin(el);
    if (t) put(t, val);
    done.push(model.split('.').pop());
  };

  const setDrop = (idSuffix, wantText) => {
    /* The hidden input the spec names, then the <select> in its group. */
    const idEl = [...document.querySelectorAll('input[ng-model]')]
        .find(e => (e.getAttribute('ng-model') || '').endsWith(idSuffix));
    if (!idEl) { missed.push(idSuffix + ' (no control)'); return; }
    const g = group(idEl);
    const sel = g && g.querySelector('select');
    if (!sel) { missed.push(idSuffix + ' (no select)'); return; }
    const opts = [...sel.options];
    const want = norm(wantText).toLowerCase();
    let o = opts.find(x => norm(x.text).toLowerCase() === want);
    if (!o) o = opts.find(x => norm(x.text).toLowerCase().indexOf(want) === 0);
    if (!o) {
      /* Name every option. A dropdown handed something it does not have stays
         on 'Select' with no error anywhere -- the silent failure this whole
         report keeps meeting. */
      missed.push(idSuffix + ' has no "' + wantText + '" -- it offers: ' +
                  opts.map(x => norm(x.text)).filter(Boolean).join(' | '));
      return;
    }
    sel.value = o.value;
    tell(sel);
    /* THE HIDDEN ONE IS WHAT POSTS. */
    put(idEl, o.value);
    done.push(idSuffix + '=' + norm(o.text));
  };

  for (const [m, v] of Object.entries(spec.text || {})) setText(m, v);
  for (const [k, v] of Object.entries(spec.drops || {})) setDrop(k, v);

  if (spec.hire_date) {
    /* Two boxes again: a type=date that holds yyyy-mm-dd and a visible text
       picker that shows MM/dd/yyyy. */
    const real = byModel('$ctrl.employmentRecord.HireDate');
    if (!real) missed.push('Hire Date (no control)');
    else {
      const [y, m, d] = spec.hire_date.split('-');
      put(real, spec.hire_date);
      const t = twin(real);
      if (t) put(t, m + '/' + d + '/' + y);
      done.push('Hire Date');
    }
  }
  if (spec.rate) {
    const real = byModel('$ctrl.employmentRecord.PayRate');
    if (!real) missed.push('Rate of Pay (no control)');
    else {
      put(real, spec.rate);
      const t = twin(real);
      if (t) put(t, spec.rate);
      done.push('Rate of Pay');
    }
  }
  if (spec.role_value) {
    const r = [...document.querySelectorAll('input[type=radio][ng-model="$ctrl.roleID"]')]
        .find(x => x.value === String(spec.role_value));
    if (r) { r.click(); done.push('Role'); }
    else missed.push('Role (no radio with value ' + spec.role_value + ')');
  }

  /* The password-reset box DEFAULTS TO TICKED on a fresh form: saving would
     email the person. Always set deliberately, never left as found. */
  const pw = document.querySelector('[ng-model="$ctrl.sendUserPassword"]');
  if (pw && pw.checked !== !!spec.email_password_reset) {
    pw.click();
    done.push('password reset ' + (spec.email_password_reset ? 'ON' : 'OFF'));
  }

  /* What the page itself still objects to, read AFTER everything is set.
     These messages are the only honest check: the hidden inputs read back ''
     in some states even when they carry a value. */
  const errors = [...new Set([...document.querySelectorAll('.text-danger, ng-message')]
      .filter(e => e.offsetParent).map(e => norm(e.innerText)).filter(Boolean))];
  const salary = byModel('$ctrl.employmentRecord.Salary');
  /* WHAT IS ACTUALLY IN THE BOXES NOW. The error messages on this page are
     not a reliable verdict -- nothing re-renders them without a framework --
     so the fill reports what it can read back, and the caller can tell a
     value that did not stick from a message that did not clear
     (Luis Frias, 2026-11-24). */
  const readback = {};
  for (const el of document.querySelectorAll('[ng-model]')) {
    const m = el.getAttribute('ng-model');
    if (!m) continue;
    readback[m] = (el.type === 'checkbox' || el.type === 'radio')
      ? (el.checked ? 'checked' : '') : (el.value || '');
  }
  for (const sel of document.querySelectorAll('select')) {
    const g = group(sel);
    const h = g && g.querySelector('input[type=hidden][id]');
    if (h) readback['select:' + h.id] =
      (sel.selectedOptions[0] ? norm(sel.selectedOptions[0].text) : '');
  }
  return {done, missed, errors, readback,
          salaryTouched: !!(salary && salary.value),
          passwordResetTicked: pw ? pw.checked : null};
}"""


def fill_spec(person: Starter, values: Dict) -> Dict:
    """What FILL_JS should put where, for one person. Pure -- no browser."""
    text = {model: values[key] for key, model in BY_MODEL.items() if values.get(key)}
    drops = {BY_WIDGET_ID[k].split(".")[-1]: values[k]
             for k in BY_WIDGET_ID if values.get(k)}
    return {
        "text": text,
        "drops": drops,
        "hire_date": person.hire_date.isoformat() if person.hire_date else "",
        "rate": values.get("rate", ""),
        "role_value": ROLE_VALUE,
        # Deliberate, because the box defaults to ticked. These people are
        # created FOR payroll, not to be invited to sign in, and an unexpected
        # "reset your password" email to a brand new rep is a support call.
        "email_password_reset": False,
    }


def payload_for(ready, hires, week_start: dt.date) -> List[Dict]:
    """The week, in the shape the engine's own `D` array expects.

    Built with filler.rows_for -- the SAME function the bookmarklet uses to
    turn a values dict into per-page labels. Writing a second one here is how
    the two copies of this would start disagreeing about which Apex box a
    value belongs in.
    """
    from automations.apex_new_starts import filler as FL
    out = []
    for person, values in ready:
        hire = hires.get(person.name)
        out.append({
            "name": person.name,
            "pages": FL.rows_for(values),
            "hire": (person.hire_date or week_start).strftime("%m/%d/%Y"),
            # The surname is what the Blue Ink dashboard is searched by, and
            # the only thing about a person that ends up in a URL.
            "find": (person.name.split()[-1] if person.name else ""),
            "doc": (BID.signed_pdf_url(hire.bundle_id, prefer="w4")
                    if hire is not None and getattr(hire, "bundle_id", "") else ""),
        })
    return out


def fill_week(page, ready, hires, week_start: dt.date, *, genders=None,
              log=print) -> Dict:
    """Drive the ENGINE over a whole week, the way the panel's own run does.

    Megan, 2026-11-10: "look at pending and complete if existing or create if
    not on there yet." That is `addMissing` then `runPerson`, which is exactly
    the order the panel's Run button uses -- so this starts them rather than
    re-implementing the loop around them.

    SAVING IS WHAT THIS DOES. `runPerson` saves each of the three tabs and
    `addMissing` saves a new record, which is why the caller holds the gate.

    Returns {"added": [names], "blocked": [{name, why}]} from the engine's own
    REPORT, never from a guess about what happened.
    """
    from automations.apex_new_starts import drive

    people = payload_for(ready, hires, week_start)
    if not drive.load(page, people, week_start.strftime("%m/%d/%Y"), log=log):
        raise RuntimeError("the Apex engine did not load — nothing was touched")
    if not drive.ready(page):
        raise RuntimeError("the Apex engine loaded only partly — nothing was "
                           "touched")

    # The two things a person used to type into the panel.
    socials = {}
    for person, _values in ready:
        hire = hires.get(person.name)
        sec = getattr(hire, "ssn", None) if hire is not None else None
        if sec is not None:
            socials[person.name] = sec
    drive.hand_over(page, genders=genders or {}, socials=socials, log=log)

    # WHICH OF THE TWO EACH PERSON NEEDS, decided before anything is typed
    # (Megan, 2026-11-11). Completing is the common case: an ICD's people
    # arrive on Pending by themselves once they are in OwnerVille.
    if not drive.to_roster(page, log=log):
        raise RuntimeError("could not reach Roster -> Employees — nothing was "
                           "touched")
    # The nav link is a full page load; the engine does not survive it.
    if not drive.keep_loaded(page, people, week_start.strftime("%m/%d/%Y"),
                             log=log):
        raise RuntimeError("the Apex engine did not survive the move to the "
                           "roster — nothing was touched")
    need = drive.triage(page, people, log=log)

    by_name = {pp.name: vv for pp, vv in ready}
    by_hand = [{"name": n, "why": v["why"]}
               for n, v in need.items() if v["need"] == drive.BY_HAND]
    for b in by_hand:
        log("  %s: %s" % (b["name"], b["why"]))

    # Create only the ones Apex has never heard of. The engine checks All
    # Employees for each one again on its way past, so this cannot make a
    # second payroll record even if the triage were wrong.
    #
    # A DISPUTED NAME IS SETTLED HERE, by where the triage found them
    # (Megan, 2026-11-15: "UNLESS you find it in the pending where it matches
    # app stream and you can just knwo it's correct"). On Pending under
    # AppStream's spelling, somebody already put them there under that name,
    # so it is right and it is what gets typed. Not on Pending, and nothing
    # here can tell which spelling is the real one -- so they are NOT created
    # and it goes back as an alert for an admin to approve a name.
    disputed = {pp.name: vv["_name_dispute"] for pp, vv in ready
                if (vv or {}).get("_name_dispute")}
    name_alerts = []
    for who, said in sorted(disputed.items()):
        what = (need.get(who) or {}).get("need")
        if what == drive.ADD:
            name_alerts.append(
                {"name": who, "ask": True,
                 "why": "%s Not on Apex's Pending list either, so an admin "
                        "has to approve which spelling is right before a "
                        "payroll record is made under it." % said})
            log("  %s: not created — %s" % (who, said))
        elif what == drive.COMPLETE:
            parts = who.split()
            vv = by_name.get(who)
            if parts and vv is not None:
                vv["first"] = parts[0]
                vv["last"] = " ".join(parts[1:]) or parts[0]
            log("  %s: on Pending under this spelling, so it is the right "
                "one" % who)

    to_add = [p for p in people
              if need.get(p["name"], {}).get("need") == drive.ADD
              and p["name"] not in disputed]
    if to_add:
        made = page.evaluate(
            "async (d) => { const said = [];"
            " const n = await window.__ansAddMissing(d, m => said.push(String(m)));"
            " return {made: n, said: said}; }", to_add)
        log("  created %s of %d in Apex" % ((made or {}).get("made", 0), len(to_add)))

    # Then complete everybody on Pending -- the ones who were already there,
    # plus the ones just created, which is where a create leaves them. One at
    # a time, carrying on past anybody that could not be finished.
    #
    # NOT `__ansRunPerson`. It walks the three tabs and saves each -- the
    # right shape -- but it fills every dropdown with an in-page click, and
    # the Beta rewrite ignores those, so every starred dropdown would stay
    # empty and Apex would refuse each save (2026-11-12).
    #
    # `drive.complete_person` is the walk that was watched working, and it is
    # the SAME walk the supervised rehearsal runs. The only difference is who
    # presses Save: there a person does, here `drive.save_tab` does -- which
    # is required, not a convenience, because Apex will not let a filled tab
    # be left unsaved and the way past that prompt discards the fill.
    working = [p for p in people
               if need.get(p["name"], {}).get("need") in (drive.COMPLETE, drive.ADD)
               and not (need.get(p["name"], {}).get("need") == drive.ADD
                        and p["name"] in disputed)]
    added, stuck = [], []
    for person in working:
        name = person["name"]
        apex_id = (need.get(name) or {}).get("id") or ""
        if not apex_id:
            # A create leaves them on Pending but the triage ran BEFORE it,
            # so it has no id for them. Re-reading the roster per person is
            # the next piece; until then they are reported, never guessed at.
            stuck.append({"name": name,
                          "why": "no Apex id yet — created this run, so it "
                                 "needs a fresh look at the roster"})
            continue
        hire = hires.get(name)
        try:
            walked = drive.complete_person(
                page, person, apex_id, values=by_name.get(name, {}),
                social=(getattr(hire, "ssn", None) if hire is not None else None),
                save=(lambda _tab, got, _id=apex_id: drive.save_tab(page, _id, got, log=log)),
                log=log)
        except Exception as e:      # noqa: BLE001 -- carry on past one person
            log("  %s: %s" % (name, type(e).__name__))
            stuck.append({"name": name, "why": "%s while filling" % type(e).__name__})
            continue
        short = [t for t, _p, _v in drive.TABS if t not in walked]
        if short:
            # SILENCE IS NOT A SAVE, and neither is a partial walk.
            stuck.append({"name": name,
                          "why": "stopped before " + ", ".join(short)})
        else:
            added.append(name)
    out = {"added": added, "blocked": stuck}
    out["blocked"] = list(out["blocked"]) + by_hand + name_alerts
    return out


def _from_report(report, names: Sequence[str], log=print) -> Dict:
    """The engine's REPORT -> {added, blocked}. A person the report says
    nothing about is BLOCKED, never added: silence is not a save."""
    rows = []
    if isinstance(report, dict):
        rows = report.get("rows") or report.get("report") or []
    elif isinstance(report, list):
        rows = report
    said = {}
    for r in rows or []:
        if isinstance(r, dict) and r.get("name"):
            said[str(r["name"])] = r
    added, blocked = [], []
    for n in names:
        r = said.get(n)
        if r and r.get("ok"):
            added.append(n)
        else:
            why = (r or {}).get("why") or "the run said nothing about them"
            blocked.append({"name": n, "why": str(why)[:160]})
    if blocked:
        log("  %d not finished: %s"
            % (len(blocked), ", ".join(b["name"] for b in blocked)))
    return {"added": added, "blocked": blocked}


READBACK_JS = r"""() => {
  /* What is in the boxes NOW. Separate from FILL_JS so it can be run again
     after the dropdowns are clicked from Python. */
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const out = {};
  for (const el of document.querySelectorAll('[ng-model]')) {
    const m = el.getAttribute('ng-model');
    if (!m) continue;
    out[m] = (el.type === 'checkbox' || el.type === 'radio')
      ? (el.checked ? 'checked' : '') : (el.value || '');
  }
  /* The Kendo boxes show their choice in a span, not a value. */
  for (const w of document.querySelectorAll('.k-dropdown, .k-widget')) {
    const g = w.closest('.form-group, .mb-3, .col, td, .row');
    const h = g && g.querySelector('input[type=hidden][id]');
    const inp = w.querySelector('.k-input');
    if (h && inp) out['shows:' + h.id] = norm(inp.innerText);
  }
  return out;
}"""


def unfilled(spec: Dict, readback: Dict) -> List[str]:
    """What the spec asked for that is NOT in the box afterwards.

    THIS IS THE VERDICT NOW, not the page's red messages. On the rewritten
    create form nothing re-renders validation, so "User Name is required" sat
    over a User Name box holding the right address, and four correct fills in
    a row were refused for it (Luis Frias, 2026-11-24). A message that did not
    clear and a value that did not stick are different problems, and only one
    of them is ours.

    Pure: it compares two dicts and opens nothing.
    """
    out = []
    for model, want in (spec.get("text") or {}).items():
        if want and not str(readback.get(model) or "").strip():
            out.append(model.split(".")[-1])
    for suffix in (spec.get("drops") or {}):
        key = next((k for k in readback if k.endswith(suffix)), "")
        if not key or not str(readback.get(key) or "").strip():
            out.append(suffix)
    if spec.get("hire_date") and not str(
            readback.get("$ctrl.employmentRecord.HireDate") or "").strip():
        out.append("HireDate")
    if spec.get("rate") and not str(
            readback.get("$ctrl.employmentRecord.PayRate") or "").strip():
        out.append("PayRate")
    return out


def fill_one(person: Starter, values: Dict, hire, log=print, *, page=None,
             save: bool = False) -> Dict:
    """Fill one person into the Apex form that is already on screen.

    The only function here that touches Apex, so there is one place to read
    when asking what this machine does to a payroll record.

    FILLING is proven (2026-11-08, filled live; re-proved 2026-11-24 against
    the rewritten create form, which needed driving a different way
    entirely). SAVING was proved on 2026-11-24 -- Luis Frias went in with
    Megan watching -- so `save=True` now presses it, through `save_tab`,
    which refuses a tab that is incomplete, wrong, or still invalid.

    `save` is False by default and the supervised run never passes it.
    """
    import os
    if page is None:
        raise RuntimeError("fill_one needs the Apex page to fill.")
    spec = fill_spec(person, values)
    # THE DROPDOWNS ARE CLICKED, NOT SET. Kendo paints a span over a hidden
    # <select> and Angular holds the model; neither is addressable from a
    # page with no globals, so writing the value left the box reading
    # "Select" (Megan, 2026-11-24: "this isn't filled"). A real click runs
    # Kendo's own handler, which is the only thing that tells Angular.
    drops = dict(spec.get("drops") or {})
    got = page.evaluate(FILL_JS, dict(spec, drops={}))
    for m in got.get("missed") or []:
        log("    missed: %s" % m)
    from automations.apex_new_starts import drive as DR
    stuck = []
    for suffix, want in drops.items():
        if DR.pick_dropdown(page, suffix, want, log=log):
            (got.setdefault("done", [])).append("%s=%s" % (suffix, want))
        else:
            stuck.append("%s (%s)" % (suffix, want))
    if got.get("salaryTouched"):
        raise RuntimeError("Salary was written -- that is the wrong box for an "
                           "hourly rate. Nothing saved.")
    # READ THE PAGE AGAIN. The first readback was taken before the dropdowns
    # were clicked, so it showed every one of them empty in the log even
    # after all five had been chosen -- a report that contradicts itself is
    # worse than none (2026-11-24).
    if drops:
        try:
            got["readback"] = page.evaluate(READBACK_JS)
        except Exception:      # noqa: BLE001
            pass
    short = unfilled(dict(spec, drops={}),
                     got.get("readback") or {}) + stuck
    if short:
        for k in sorted(got.get("readback") or {}):
            log("      %-46s %r" % (k, got["readback"][k]))
        raise RuntimeError("these boxes did not take their value: %s"
                           % ", ".join(short))
    if got.get("errors"):
        # NOT A REFUSAL ANY MORE, because every box the spec asked for has
        # its value -- checked just above. The rewritten form leaves its red
        # messages on screen whatever you type into it.
        log("    the page still shows (every value IS in — these do not "
            "clear on this form): %s" % "; ".join(got["errors"][:6]))
    if not save:
        log("    filled, NOT saved (%d fields)" % len(got.get("done") or []))
        return got
    # THE GATE IS CLEARED (Megan, 2026-11-24: "clear the gate"). What it
    # asked for happened: Luis Frias's create form was filled by this code,
    # read on screen, and saved by a person watching -- the record went in
    # clean. So the Save step is no longer the one thing nobody has seen.
    #
    # WHAT STILL GUARDS IT. Clearing the gate did not make this press Save
    # on anything it is unsure of. `save_tab` refuses outright on a required
    # box with no value, on a box holding something other than what was
    # asked for, and on a form Angular still calls invalid -- and it proves
    # the save by watching for the POST rather than trusting the click. The
    # readback above has already shown every value is in by the time this
    # line runs. And `save` is still False everywhere by default: the
    # supervised run passes nothing and cannot be made to.
    from automations.apex_new_starts import drive as DR
    if not DR.save_tab(page, "", {"missed": [], "absent": []}, log=log):
        raise RuntimeError(
            "the create form was filled correctly but would not save. "
            "Nothing was created.")
    got["saved"] = True
    log("    SAVED.")
    return got


def main(argv=None) -> int:
    """Read-only by default.

        python -m automations.apex_new_starts.eco_run --office 11280
        python -m automations.apex_new_starts.eco_run --office 11280 --week 2026-11-02
    """
    import argparse
    import json
    ap = argparse.ArgumentParser(description="New starts -> Apex, on this office's computer.")
    ap.add_argument("--office", required=True, help="ApplicantStream office id")
    ap.add_argument("--week", default=None, help="YYYY-MM-DD in the week to run")
    ap.add_argument("--office-key", default="raf",
                    help="whose onboarding board to read and tick (default raf)")
    args = ap.parse_args(argv)
    start = dt.date.fromisoformat(args.week) if args.week else dt.date.today()
    res = run_week(start, office_appstream=args.office,
                   office_key=args.office_key, live=False)
    print(json.dumps(res, indent=2))
    return 0 if res.get("status") in ("dry_run", "none") else 1


if __name__ == "__main__":
    raise SystemExit(main())
