"""The two steps on an ICD's board that ACT in OwnerVille, not just read it.

Megan, 2026-11-15: "do 1 and 2" — point the Owner Submit press at the office
boards, and request the UID.

Everything else in this package LOOKS and ticks. These two press a button on
somebody's behalf, which is why they are here on their own and read with the
rest of the module in mind:

    uid           AT&T UID REQUEST   ->  UID Request
    owner_submit  OWNER SUBMIT       ->  Owner Submit

THE PRESSES THEMSELVES ARE NOT WRITTEN HERE. `obcl_ov_sweep.owner_submit` has
been pressing Owner Submit for Alphalete since 22 September, attestation, gate
and confirming re-open and all; `obcl_ov_sweep.uid_request` is the same shape
for the UID. This module is the RE-POINT Megan asked for: which office, which
campaign, which board, and whose session.

WHAT MADE IT ALPHALETE-ONLY, since that is the whole of gap #1. Not the press.
`ownerville.open_set_status` pinned the campaign to RES-AT&T, so the lookup
always ran against Alphalete's roster — an ICD's new start simply was not
there, and that reads identically to "not in OwnerVille". The campaign is now
the caller's to name and comes from the office's own `ov_program`, the same
value `from_ownerville` already reads the table with.

WHO GETS LOOKED UP. The board decides that, cheaply: anybody not marked off
whose column is still blank. OWNERVILLE DECIDES WHETHER TO PRESS — its own
section states are the gate, exactly as they are for Alphalete. The board is
never allowed to be the reason something is pressed: it is a sheet, people
type in it, and a hand-typed cell must not be able to cause an attestation.

A REFUSAL IS NOT A FAILURE. Somebody whose sections are not all COMPLETED is
not ready, which is the normal case on most days; the run says so and carries
on. A refusal only becomes an alert when the press was LIVE and OwnerVille
still would not take it — then it goes to the corrections channel as one
incident thread per office, so a person finishes it by hand and the next pass
ticks the board off OwnerVille.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Dict, List, Optional, Sequence

from automations.icd_onboarding import board as B
from automations.icd_onboarding import fillers as F

# Who to tag when a live press is refused, and where. Same channel and the
# same two people as Alphalete's (Megan, Eve) — a refusal here needs the same
# pair of eyes, and one channel is the one surface they read.
ALERT_CHANNEL = "C0BK5PRG259"          # #claudecorrections-and-requests
ALERT_TAGS = ("<@U04G5HJBGFN>", "<@U088E2KJEV8>")   # Megan, Eve


def _ov_program(office_key: str) -> str:
    from automations.office_admin import config as OC
    o = OC.office(office_key)
    return (getattr(o, "ov_program", "") if o else "") or ""


# NOT READY IS NOT A FAILURE (Eve 2026-11-16). The board hands the press
# everybody with a blank column -- it does not know who is ready -- so most
# refusals on any day just mean "not yet": sections still open, background
# check still running, or not on the campaign yet (the board is seeded by who
# is SCHEDULED to start; Digi Docs adds them nearer their start). On 11/15 the
# first live pass for raf posted 10 of those to the corrections channel as if
# they needed doing by hand, and it would repeat daily. Only a refusal from
# somebody OwnerVille showed as READY -- the confirm box, the save, the
# confirming re-open -- is something a person has to finish.
NOT_READY = ("not every section is done",
             "background check is not COMPLETED",
             "not found in OwnerVille")


def is_not_ready(detail: str) -> bool:
    return any(m in str(detail) for m in NOT_READY)


# The two board columns that hold a STATE rather than a tick, and the answers
# that mean the state is finished (bg_status.DONE_STATUSES). "Pending" in a BG
# cell is a cell somebody filled in and not a step somebody completed, so
# `_step_done` will not count it towards being ready.
_STATE_COLUMNS = ("BG Status", "OV BG Status")


def _step_done(column: str, said: str) -> bool:
    """Does this board cell say the step is FINISHED?"""
    from automations.icd_onboarding import bg_status as BG

    said = str(said or "").strip()
    if not said or F.is_alert(said):
        return False
    if column in _STATE_COLUMNS:
        return any(d.lower() in said.lower() for d in BG.DONE_STATUSES)
    return True


def readiness(row: Dict, column: str) -> int:
    """How many of the steps BEFORE `column` this row already shows finished.

    A guess, and only ever used to decide who is asked about FIRST. It reads
    our own board, which is a sheet people type in -- so it must never be able
    to cause a press, and it cannot: OwnerVille's own section states remain the
    only gate.
    """
    steps = list(B.STEPS)
    before = steps[:steps.index(column)] if column in steps else []
    return sum(1 for c in before if _step_done(c, row.get(c)))


def candidates(office_key: str, week_start: dt.date, column: str) -> List[str]:
    """Who on this week's board has `column` still blank and is not marked off,
    READIEST FIRST.

    The same filter `_board_names` uses, for the same reason: a lookup is one
    request against a slow server (~23s measured), so asking about people who
    can gain nothing is how a run spends its budget and still leaves somebody
    out. An `ALERT_PREFIX` cell counts as blank — it is an ask, not an answer.

    THE ORDER IS THE DIFFERENCE BETWEEN REACHING SOMEBODY AND NOT. Measured on
    raf, 2026-11-20: owner_submit spent its whole 9m39s budget on the first
    eight names in BOARD order -- four not in OwnerVille at all, four with
    every section PENDING -- and stopped with "20 not reached this run". Jaime
    Molina, who was ready, whose sections all read COMPLETED and whose Submit
    box was sitting there unticked, was one of the twenty. Every lookup in that
    run worked perfectly and the run submitted nobody.

    So the readiest go first (`readiness`), and board order breaks ties. This
    changes who is ASKED first and nothing else.
    """
    from automations.icd_onboarding import sheet as S

    # `board_for`, not `open_board(workbook_for(...))`: an office with a
    # book of their own has a tab PER WEEK, and the old stacked tab is
    # empty for them -- so this offered NOBODY to submit (2026-11-24).
    ws = S.board_for(office_key, week_start, create=False)
    if ws is None:
        return []
    scored = []
    for seen, r in enumerate(B.for_week(S.rows_of(ws.get_all_values()),
                                        week_start)):
        if not (r.get("Name") or r.get("Last Name")):
            continue
        if str(r.get(B.TERMINATED_AT) or "").strip():
            continue
        said = str(r.get(column) or "").strip()
        if said and not F.is_alert(said):
            continue
        name = ("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip()
        scored.append((-readiness(r, column), seen, name))
    scored.sort()
    return [name for _, _, name in scored]


def _alert(office_key: str, what: str, failures: Sequence, log=print) -> None:
    """A live press OwnerVille would not take goes to the corrections channel.

    One incident thread PER OFFICE and per press, so Alphalete's refusals and
    an ICD's never land in each other's thread and a same-day repeat updates
    the post instead of making a second one somebody has to choose between.
    Never fails the run: the ticks and the rest of the board already landed.
    """
    if not failures:
        return
    body = [" ".join(ALERT_TAGS) + " — %s needs doing by hand in OwnerVille "
            "for %s (then Lucy ticks the board on the next pass):"
            % (what, office_key)]
    body += ["• %s — %s" % (n, why) for n, why in failures]
    title = ("%s: couldn't %s %d new start%s in OwnerVille"
             % (office_key, what, len(failures),
                "s" if len(failures) != 1 else ""))
    try:
        from automations.shared import incident_thread as inc
        res = inc.open_or_followup(
            key="failure-icd_%s-%s" % (what.replace(" ", "_"), office_key),
            title=title, body=body, channel=ALERT_CHANNEL,
            subjects=[n for n, _ in failures],
            label="%s %s" % (office_key, what))
        log("  alert %s: %s" % ("posted" if res else "NOT confirmed", title))
    except Exception as e:                                  # noqa: BLE001
        log("  ⚠ %s alert FAILED to post (%s: %s)"
            % (what, type(e).__name__, str(e)[:160]))


def _press(office_key: str, week_start: dt.date, *, column: str, what: str,
           press, live_gate: bool, dry_run: bool, log,
           budget_s: Optional[float]) -> int:
    """The shared half of both presses: open the office's own OwnerVille once,
    walk its candidates, tick what OwnerVille confirms, alert what it refused.

    `live_gate` is the module-level switch for this press. A press is REAL only
    when the run is writing AND its gate is on — so `--write` alone cannot fire
    something Megan has not switched on, and a gate being on cannot make a dry
    run press anything. Both have to agree.
    """
    from automations.icd_onboarding import ov_misses as OVM
    from automations.obcl_ov_sweep import config as OVC
    from automations.obcl_ov_sweep.run import PROFILE_DIR
    from automations.shared.tableau_patchright import ownerville_session

    programme = _ov_program(office_key)
    if not programme:
        # The campaign IS the roster. Falling back to Alphalete's would look
        # up an ICD's new start on somebody else's campaign, find nobody, and
        # report "not in OwnerVille" — which is exactly the wrong answer to
        # act on ([[reference_campaign_picks_the_workbook]]).
        log("  %s: %s has no ov_program set — skipped rather than guessing "
            "at Alphalete's" % (what, office_key))
        return 0

    wanted = candidates(office_key, week_start, column)
    if not wanted:
        log("  %s: nobody on this week's board with %s still open"
            % (what, column))
        return 0

    real = bool(not dry_run and live_gate)
    if not dry_run and not live_gate:
        log("  %s is GATED — dry walk only, nothing pressed" % what)
    # DON'T PAY TWICE FOR THE SAME ABSENCE. Half of the eight names this step
    # reached on raf (2026-11-20) cost a full ~27s lookup only to answer "not
    # found in OwnerVille" -- for people nobody has added there yet, which the
    # previous run had already discovered. `ov_misses` is the same cooldown the
    # `ownerville` step uses; the budget it frees goes to names worth asking
    # about. A remembered miss NEVER means "not in OwnerVille", only "don't
    # spend the search on them again yet".
    askable = OVM.fresh(office_key, week_start, wanted)
    held = len(wanted) - len(askable)
    if held:
        log("  %s: %d name(s) held back — OwnerVille said it didn't have them "
            "in the last %d minutes" % (what, held, OVM.COOLDOWN_MIN))
    if not askable:
        log("  %s: every name is on that cooldown — nothing to search for "
            "this pass" % what)
        return F.apply(F.workbook_for(office_key), week_start, "ownerville",
                       {}, dry_run=dry_run, log=log,
                       office_key=office_key)
    budget = OVC.SEARCH_BUDGET_S if budget_s is None else budget_s
    verdicts: Dict[str, Dict[str, object]] = {}
    failures: List = []
    missing: List[str] = []
    found: List[str] = []
    t0 = time.monotonic()
    done = 0
    with ownerville_session(headless=True, verbose=False,
                            profile_dir=PROFILE_DIR) as page:
        for name in askable:
            if time.monotonic() - t0 >= budget:
                log("    time budget reached; %d not reached this run"
                    % (len(askable) - done))
                break
            done += 1
            try:
                outcome, detail = press(page, name, dry_run=not real,
                                        campaign=programme)
            except Exception as e:      # noqa: BLE001 — one name, not the run
                outcome, detail = "refused", "%s: %s" % (type(e).__name__, e)
            log("  %s %s: %s" % (what.upper(), outcome.upper(), detail))
            # A LOOKUP THAT REACHED THE PERSON IS A HIT, whatever it then said
            # about them: "not every section is done" is OwnerVille describing
            # somebody it has. Only the not-found answer is an absence.
            if "not found in OwnerVille" in str(detail):
                missing.append(name)
            else:
                found.append(name)
            if outcome in ("submitted", "requested", "already"):
                verdicts[name] = {column: True}
            elif real and outcome == "refused" and not is_not_ready(detail):
                failures.append((name, detail.split(": ", 1)[-1]))
    OVM.remember(office_key, week_start, missing)
    OVM.forget(office_key, week_start, found)

    if real:
        _alert(office_key, what, failures, log=log)
    # Ticked off what OWNERVILLE says, through the one place a tick is decided.
    return F.apply(F.workbook_for(office_key), week_start, "ownerville",
                   verdicts, dry_run=dry_run, log=log,
                   office_key=office_key)


def press_owner_submit(office_key: str, week_start: dt.date, *,
                       dry_run: bool = True, log=print,
                       budget_s: Optional[float] = None) -> int:
    """Owner-submit anyone on this week's board OwnerVille says is ready.

    THE GATE IS THE ONE MEGAN ALREADY DECIDED. She reviewed the dry walk in
    September and switched `config.OWNER_SUBMIT_LIVE` on on the 22nd; this
    inherits that switch rather than adding a second one, because it is the
    same attestation on the same form with the same refusal alert. There is
    nothing new to approve — only a different office's campaign.
    """
    from automations.obcl_ov_sweep import config as OVC
    from automations.obcl_ov_sweep import owner_submit

    return _press(office_key, week_start, column="Owner Submit",
                  what="owner submit", press=owner_submit.submit_one,
                  live_gate=OVC.OWNER_SUBMIT_LIVE, dry_run=dry_run, log=log,
                  budget_s=budget_s)


def uid_reasons(office_key: str, week_start: dt.date, *, dry_run: bool = True,
                log=print, budget_s: Optional[float] = None) -> int:
    """READ ONLY: why each outstanding AT&T UID is outstanding, and whose move.

    THERE IS NO UID PRESS, and this is what replaced the one that was written
    on 2026-11-15 before Megan's screenshots showed the section has no button
    in it -- see uid_request's docstring. The rep submits the ATTUID form
    themselves in the Candidate Roadmap Portal, and the send to AT&T fires off
    SaraPlus activation.

    So the useful thing is not a click, it is the DIFFERENCE between three
    blanks that look identical on the board: waiting on the rep, waiting on
    SaraPlus activation, waiting on AT&T. Only the first is anybody's to chase,
    and it is the input a UID nudge needs.

    Presses nothing and writes nothing, whatever --write says. Hand-run only.
    """
    from automations.obcl_ov_sweep import config as OVC
    from automations.obcl_ov_sweep import uid_request
    from automations.obcl_ov_sweep.run import PROFILE_DIR
    from automations.shared.tableau_patchright import ownerville_session

    programme = _ov_program(office_key)
    if not programme:
        log("  uid reasons: %s has no ov_program set" % office_key)
        return 0
    wanted = candidates(office_key, week_start, "UID Request")
    if not wanted:
        log("  uid reasons: nobody on this week's board with UID Request open")
        return 0
    budget = OVC.SEARCH_BUDGET_S if budget_s is None else budget_s
    t0, seen, tally = time.monotonic(), 0, {}
    with ownerville_session(headless=True, verbose=False,
                            profile_dir=PROFILE_DIR) as page:
        for name in wanted:
            if time.monotonic() - t0 >= budget:
                log("    time budget reached; %d not read this run"
                    % (len(wanted) - seen))
                break
            seen += 1
            try:
                state, said, whose = uid_request.reason_one(
                    page, name, campaign=programme)
            except Exception as e:      # noqa: BLE001 — one name, not the run
                state, said, whose = "", "%s: %s" % (type(e).__name__, e), ""
            log("  UID [%s] %s" % (state or "?", said))
            log("    whose move: %s" % (whose or "could not tell"))
            tally[whose or "could not tell"] = tally.get(whose or "could not tell", 0) + 1
    for whose, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        log("  %d waiting on %s" % (n, whose))
    return 0
