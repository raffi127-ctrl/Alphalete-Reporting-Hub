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

# THE SEED'S OWN HELPERS, re-exported. They moved to `eco_steps` on 2026-11-24
# so the seed can run on an office's computer; these names are what the Hub
# side and the tests reach for, and one definition is the whole point of the
# move -- the same thing `book` does for `tab_name`.
from automations.icd_onboarding.eco_steps import (    # noqa: E402,F401
    _appstream_id, _appstream_ids, _board_names, _funnel_labels,
    _id_and_label, _name_key, _ov_program, _person_key, _tick_showed_up,
    _walked_in_after_a_no_show)
















def seed(office_key: str, week_start: dt.date, *, dry_run: bool = True,
         log=print, names_only: bool = False):
    """Moved to `eco_steps` on 2026-11-24 so it can run on the office's own
    computer. This name is what the Hub and the tests reach for; the body
    lives where it ships, and there is one of it."""
    from automations.icd_onboarding import eco_steps as ES
    return ES.seed(office_key, week_start, dry_run=dry_run, log=log,
                   names_only=names_only)


def seed_names(office_key: str, week_start: dt.date, *, dry_run: bool = True,
               log=print):
    """Moved to `eco_steps` on 2026-11-24 so it can run on the office's own
    computer. This name is what the Hub and the tests reach for; the body
    lives where it ships, and there is one of it."""
    from automations.icd_onboarding import eco_steps as ES
    return ES.seed_names(office_key, week_start, dry_run=dry_run, log=log)


def from_no_shows(office_key: str, week_start: dt.date, *, dry_run: bool = True,
                  log=print):
    """Moved to `eco_steps` on 2026-11-24 so it can run on the office's own
    computer. This name is what the Hub and the tests reach for; the body
    lives where it ships, and there is one of it."""
    from automations.icd_onboarding import eco_steps as ES
    return ES.from_no_shows(office_key, week_start, dry_run=dry_run, log=log)








def from_ownerville(office_key: str, week_start: dt.date, *,
                    dry_run: bool = True, log=print,
                    budget_s=None) -> int:
    """Moved to `eco_steps` on 2026-11-24 so the five OwnerVille columns can be
    read on the office's own computer, with the office's own login. This name
    is what the Hub and the tests reach for; there is one body."""
    from automations.icd_onboarding import eco_steps as ES
    return ES.from_ownerville(office_key, week_start, dry_run=dry_run,
                              log=log, budget_s=budget_s)




def from_blueink(office_key: str, week_start: dt.date, *,
                 dry_run: bool = True, log=print) -> int:
    """Moved to `eco_steps` on 2026-11-24 so a signed packet can be read on the
    office's own computer, from their own Blue Ink. One body."""
    from automations.icd_onboarding import eco_steps as ES
    return ES.from_blueink(office_key, week_start, dry_run=dry_run, log=log)


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


def mark_not_completed(office_key: str, week_start: dt.date, *,
                       dry_run: bool = True, log=print) -> int:
    """Week-3 people never owner submitted -> off the board, "Onboarding Not
    Completed" (Megan, 2026-11-25). The body is `not_completed`; this name is
    what STEPS and the tests reach for.

    IT IGNORES `week_start` ON PURPOSE. Every other step works on the week it
    is handed; this one always judges the WEEK-3 week, because that is the
    cohort the rule is about. `wk3.start_week_for` owns that, so the mark and
    the drug send cannot disagree about which week they mean.
    """
    from automations.icd_onboarding import not_completed as NC
    return NC.run(office_key, dry_run=dry_run, log=log)


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
         ("no_shows", from_no_shows),
         # WEEKLY, and on its own clock. Marks the week-3 cohort's
         # never-owner-submitted people off the board.
         ("not_completed", mark_not_completed))

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
#   seed_names   com.alphalete.icd-onboarding-seed-names, :05/:20/:50 from
#                6am to 8:50pm on the box holding this office's
#                ApplicantStream session. It is `seed` with the Showed Up
#                half left off, so the names land within 15 minutes of a BOB
#                (Megan, 2026-11-22).
#                OFF THE BOARD'S MINUTES, which are :00/:15/:30/:45. It ran
#                :00/:15/:45 until 2026-11-25, avoiding only :30 because the
#                board then fired at half past; the board moved to the hour
#                and that avoidance stopped avoiding anything, so the two
#                collided at nearly every fire and the overlap guard was
#                skipping one of them. Nobody saw it because both plists
#                carried an illegal "--" in an XML comment and the collision
#                test's parser gave up before reading a single time.
#   not_completed  com.alphalete.icd-onboarding-not-completed, Mondays at
#                07:40 -- weekly, because the cohort it judges does not change
#                inside the week, and :40 because it is not a minute the board
#                (:00/:15/:30/:45) or the names run (:05/:20/:50) uses. Early
#                Monday so the board is right before anybody is nudged to send
#                that week's drug tests. SHEETS ONLY: it reads the Owner
#                Submit column the hourly `ownerville` step already wrote, so
#                it opens no OwnerVille and holds no session.
OWN_CLOCK = ("no_shows", "seed_names", "not_completed")

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
