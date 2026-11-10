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
"""
from __future__ import annotations

import datetime as dt
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

    account = _appstream_id(office_key)
    if not account:
        log("  seed: %s has no ApplicantStream id" % office_key)
        return 0
    with session() as app:
        people = fdot.read_week(app, account, week_start, log=log)
    book = F.workbook_for(office_key)
    got = S.seed(book, week_start, people, dry_run=dry_run, log=log)
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
    hires = BID.for_people(people, keep_ssn=False)
    verdicts = {}
    for p in people:
        h = hires.get(p.name)
        if h is not None and not h.missing_packet:
            verdicts[p.name] = {"Blue Ink": True}
    return F.apply(book, week_start, "blueink", verdicts,
                   dry_run=dry_run, log=log)


def from_sterling(office_key: str, week_start: dt.date, *,
                  dry_run: bool = True, log=print) -> int:
    from automations.icd_onboarding import bg_status
    return bg_status.run(week_start, offices=[office_key],
                         dry_run=dry_run, log=log)


STEPS = (("seed", seed), ("ownerville", from_ownerville),
         ("blueink", from_blueink), ("sterling", from_sterling))


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


def offices_here() -> List[str]:
    """The offices THIS machine is enrolled for.

    So the hourly run takes no arguments on an ECO box: the machine already
    knows whose logins it holds, and a key typed into a plist is a key that
    goes stale the day an office is re-enrolled. An office running two
    campaigns has one board, so the keys are de-duplicated by office.
    """
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
    if not offices:
        print("no office to run: pass --office, or run this on a machine that "
              "is enrolled for one.")
        return 1
    bad = 0
    for office in offices:
        got = for_office(office, week, dry_run=not a.write, only=a.only)
        bad += sum(1 for v in got.values() if isinstance(v, str))
        print()
    if not a.write:
        print("(dry run — nothing was written. --write to do it for real.)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
