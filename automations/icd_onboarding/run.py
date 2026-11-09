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


def from_ownerville(office_key: str, week_start: dt.date, *,
                    dry_run: bool = True, log=print) -> int:
    """Five columns off one View Progress read."""
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
    with ownerville_session(headless=True, verbose=False,
                            profile_dir=PROFILE_DIR) as page:
        heads, reps, complete = ov_table.read_table(page, verbose=False,
                                                    campaign=programme)
    if not complete:
        # Not a reason to stop: the people it DID read are answered, and the
        # ones it did not get no verdict at all, so nothing is wrongly ticked.
        log("  ownerville: read %d rows, the table says there are more — the "
            "rest are 'not read', not 'not done'" % len(reps))
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


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Bring an onboarding board up to date.")
    ap.add_argument("--office", action="append", default=[], required=True,
                    help="office key; repeatable")
    ap.add_argument("--week", default=None, help="YYYY-MM-DD in the week")
    ap.add_argument("--only", action="append", default=[],
                    choices=[n for n, _ in STEPS],
                    help="just these steps; repeatable")
    ap.add_argument("--write", action="store_true",
                    help="actually write (default is a dry run)")
    a = ap.parse_args(argv)
    week = dt.date.fromisoformat(a.week) if a.week else dt.date.today()
    bad = 0
    for office in a.office:
        got = for_office(office, week, dry_run=not a.write, only=a.only)
        bad += sum(1 for v in got.values() if isinstance(v, str))
        print()
    if not a.write:
        print("(dry run — nothing was written. --write to do it for real.)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
