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
    """This week's showed-up people onto the board."""
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
        # The Retention Report first: it answers this in TWO page loads where
        # the calendar walk takes seven (Megan, 2026-11-09: "you should just
        # look at the retention details report and not walk the calendar as
        # this would be faster"). Checked against the walk on Raf's week of
        # 11/01 -- the same 29 people, the same 29 emails.
        #
        # The walk stays as the fallback, not as dead code: the report is one
        # page that an office might not carry the row on, and a week that
        # could not be read must never seed as an empty one
        # ([[feedback_empty_means_proven_zero]]).
        try:
            people = retention.read_week(app, account, week_start, log=log)
        except Exception as e:      # noqa: BLE001 — fall back, never give up
            log("  retention report unavailable (%s: %s) — walking the calendar"
                % (type(e).__name__, str(e)[:120]))
            people = fdot.read_week(app, account, week_start, log=log)
    book = F.workbook_for(office_key)
    got = S.seed(book, week_start, people, dry_run=dry_run, log=log)
    # A step this office does not do is not an outstanding step. Marked at
    # seed time so the office never reads as behind on work that does not
    # exist (Megan, 2026-11-09: "if they don't then they can't enroll in apex
    # and so we would skip that part").
    from automations.icd_onboarding import office_steps as OS
    OS.mark_not_applicable(office_key, week_start, dry_run=dry_run, log=log)
    return len(got.get("add") or [])


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

    ws = S.open_board(F.workbook_for(office_key), create=False)
    if ws is None:
        return []
    out = []
    for r in B.for_week(S.rows_of(ws.get_all_values()), week_start):
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

    verdicts = {name: ov_table.done_columns(heads, cells)
                for name, cells in reps.items()}
    return F.apply(F.workbook_for(office_key), week_start, "ownerville",
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

    book = F.workbook_for(office_key)
    ws = S.open_board(book, create=False)
    if ws is None:
        log("  blueink: no board yet")
        return 0
    rows = B.for_week(S.rows_of(ws.get_all_values()), week_start)
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
    return F.apply(book, week_start, "blueink", verdicts,
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


def from_contacts(office_key: str, week_start: dt.date, *,
                  dry_run: bool = True, log=print) -> int:
    """Contact Added, off Eve's second-round contact sync.

    Megan, 2026-11-09: "we need to connect to Eve's already built automation
    that's adding 2nd round contacts."

    IT READS HER RECORD RATHER THAN REDOING HER WORK. `second_round_contacts`
    writes every contact it creates to its own state file -- name, phone,
    email, office, status -- so the question "has this person been added?" is
    already answered there. Reading it needs no change to her job, no second
    Google Contacts call, and no second idea of who counts as added.

    IT ALSO COVERS THE PEOPLE ADDED BEFORE THE BOARD EXISTED, which an
    as-it-happens tick cannot: somebody contacted at their second round three
    weeks ago is never re-added, so a tick that only fires on creation would
    leave them blank for ever. On the real OBCL Contact Added is true for
    nearly everybody, and that is why.

    MATCHED THE WAY SHE MATCHES: phone first, then email -- `state.key_for`'s
    rule, not a new one. A name is only the last resort, and it is a weak one:
    an applicant types their own name into ApplicantStream, so the board and
    the sync disagree over "Mike"/"Michael", a middle name, a married name or
    an accent, and a name-only match answered 0 of 21 on Raf's week of 11/08
    while 98 contacts sat on record. The phone is the same digits in both.

    WHERE IT RUNS. Wherever the state file is, which is the machine her job
    runs on (Lucy 1). On any other machine the file is simply absent and this
    says so and ticks nothing -- an unread source is never a "no"
    ([[feedback_empty_means_proven_zero]]). The tick itself goes to the Sheet,
    so it reaches the office's board from wherever it is made.
    """
    from automations.icd_onboarding import sheet as S
    from automations.second_round_contacts import config as SC
    from automations.second_round_contacts import state as SS

    if not SC.STATE_PATH.exists():
        log("  contacts: no state file at %s — this runs where the contact "
            "sync runs. Nothing ticked." % SC.STATE_PATH)
        return 0

    from automations.applicant_contacts.extract import phone10

    by_phone, by_email, by_name = {}, {}, {}
    per_account: Dict[str, int] = {}
    n = 0
    for _account, people in (SS.load() or {}).items():
        for entry in (people or {}).values():
            if str(entry.get("status") or "") == SS.REMOVED:
                continue      # taken out again; not an added contact
            n += 1
            per_account[str(_account)] = per_account.get(str(_account), 0) + 1
            ph = phone10(str(entry.get("phone") or ""))
            if ph:
                by_phone[ph] = entry
            em = str(entry.get("email") or "").strip().lower()
            if em:
                by_email[em] = entry
            name = ("%s %s" % (entry.get("first_name", ""),
                               entry.get("last_name", ""))).strip()
            if name:
                by_name[B._fold(name)] = entry
    log("  contacts: %d on record from the second-round sync "
        "(%d with a phone, %d with an email)"
        % (n, len(by_phone), len(by_email)))
    # WHOSE contacts they are. The sync keys its state by ApplicantStream
    # account, and a state full of somebody else's offices looks exactly like
    # a state full of nobody -- both tick zero. 98 contacts matched 0 of
    # Raf's 21 on 2026-11-10 and the counts alone could not say which it was.
    if per_account:
        log("    by account: %s"
            % ", ".join("%s=%d" % kv for kv in sorted(per_account.items())))

    ws = S.open_board(F.workbook_for(office_key), create=False)
    if ws is None:
        log("  contacts: no board yet")
        return 0
    rows = B.for_week(S.rows_of(ws.get_all_values()), week_start)
    verdicts = {}
    how = {"phone": 0, "email": 0, "name": 0}
    for r in rows:
        name = ("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip()
        ph = phone10(str(r.get("Phone") or ""))
        em = str(r.get("Email") or "").strip().lower()
        if ph and ph in by_phone:
            hit = "phone"
        elif em and em in by_email:
            hit = "email"
        elif B._fold(name) in by_name:
            hit = "name"
        else:
            continue
        how[hit] += 1
        verdicts[name] = {"Contact Added": True}
    if verdicts:
        log("    matched %d: %s"
            % (len(verdicts), ", ".join("%d by %s" % (v, k)
                                        for k, v in how.items() if v)))
    else:
        askable = sum(1 for r in rows
                      if str(r.get("Phone") or "").strip()
                      or str(r.get("Email") or "").strip())
        log("    matched 0 of %d on the board (%d of them had a phone or an "
            "email to match on)" % (len(rows), askable))
    return F.apply(F.workbook_for(office_key), week_start, "contacts",
                   verdicts, dry_run=dry_run, log=log)


STEPS = (("seed", seed), ("ownerville", from_ownerville),
         ("blueink", from_blueink), ("sterling", from_sterling),
         ("contacts", from_contacts))


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
STEPS_BY_MACHINE = {
    "Lucy 1": ("contacts", "sterling"),
    "Lucy 2": ("blueink",),
    "Lucy 3": ("seed", "ownerville"),
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

    bad = 0
    for office in offices:
        got = for_office(office, week, dry_run=not a.write, only=only)
        bad += sum(1 for v in got.values() if isinstance(v, str))
        print()
    if not a.write:
        print("(dry run — nothing was written. --write to do it for real.)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
