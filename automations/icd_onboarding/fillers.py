"""Letting the existing automations tick the ICD board.

Megan, 2026-11-09: "wire up the fillers so the steps tick themselves."

Nearly every step already has something that knows the answer. None of it is
rewritten here — this is the one place those answers become ticks, so there is
a single thing to read when asking what is allowed to mark somebody's step
done, and a single place the rules live.

    AppStream retention       ->  Showed Up
    OwnerVille View Progress  ->  Digi Docs · Onboarding Quizzes ·
                                  Headshot Photo · UID Request · Owner Submit
    Blue Ink                  ->  Blue Ink
    Sterling / fadv           ->  BG Status
    2nd-round contact sync    ->  Contact Added
    the Apex run              ->  Added to APEX

THE RULES, AND WHY EACH ONE IS HERE

  * ON ONLY. A source saying "not done" leaves the box alone; only True ticks.
    A tick is evidence something happened, and no source here is entitled to
    say it did not — `obcl_ov_sweep.earned` has worked that way from the start
    and this keeps it.
  * UNREAD IS NOT UNDONE. `done_columns` answers None when the header it needs
    is missing, which means the page could not be read, not that the step is
    outstanding. None never ticks and never counts as a no.
  * A SOURCE ONLY TICKS ITS OWN COLUMNS. Blue Ink has no business touching
    Owner Submit. Anything outside a source's list is refused rather than
    quietly ignored, so a wiring mistake shows up here instead of as a wrong
    tick on a real person.
  * NOBODY MARKED OFF IS TICKED. They left; ticking their steps would put them
    back on the chase list, and the printed sheet would carry a person who is
    not coming in.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from automations.icd_onboarding import board as B

# What each source is allowed to write. Read off the automations that already
# fill these, not invented: obcl_ov_sweep.config.COLUMNS is exactly its five.
SOURCES: Dict[str, Sequence[str]] = {
    "ownerville": ("Digi Docs", "Onboarding Quizzes", "Headshot Photo",
                   "UID Request", "OV BG Status", "Owner Submit",
                   # OwnerVille's own gates on Owner Submit, which it has
                   # always read and never had a column for (2026-11-24).
                   *B.OV_GATES),
    "blueink": ("Blue Ink",),
    "sterling": ("BG Status",),
    "contacts": ("Contact Added",),
    "apex": ("Added to APEX",),
    # The seed's second read: who of the scheduled actually turned up.
    "appstream": (B.SHOWED_UP,),
}


# WHAT AN ALERT LOOKS LIKE IN A STEP CELL. A step that cannot be done until a
# person decides something writes what it is waiting for into its own column,
# because that column is where the leader is already looking -- and it is the
# only surface they read. The prefix is what makes it an ASK rather than an
# answer: `plan` treats a cell starting with it as still outstanding, so the
# real date lands on top of it the moment the step actually runs. Without that
# the alert would wedge the step shut forever (2026-11-15).
# ONE definition, in board.py -- because `plan` here and `write_step` /
# `tick_plan` over there all have to agree on what an ask is, and when they
# did not the ask wedged the step shut (2026-11-22).
ALERT_PREFIX = B.ASK_PREFIX
is_alert = B.is_ask


def columns_for(source: str) -> Sequence[str]:
    if source not in SOURCES:
        raise ValueError(
            "%r is not a source. Known: %s" % (source, ", ".join(sorted(SOURCES))))
    return SOURCES[source]


def plan(rows: List[Dict], source: str,
         verdicts: Mapping[str, Mapping[str, object]]) -> Dict[str, Dict[str, str]]:
    """{column: {name: what to write}} for one source's answers.

    A verdict of True means "done" and the cell gets today's date. A verdict
    that is a STRING means "done, and this is what it says" and the cell gets
    the string — Megan, 2026-11-09: "We should just have Background Status:
    xStatus". A date proves something happened; for a background check the
    useful thing is WHICH answer came back, and the board has one cell to say
    it in.

    `verdicts` is {person: {column: True/False/None}} — the shape
    `ov_table.done_columns` already returns, so a source adapter is a dict and
    not a translation layer.

    Returns only what would CHANGE: somebody already ticked is not listed, so
    running this every hour writes nothing on the hours nothing happened.
    """
    allowed = set(columns_for(source))
    by_key = {}
    for r in rows:
        if str(r.get(B.TERMINATED_AT) or "").strip():
            continue                      # marked off — not ours to tick
        by_key[B._fold("%s%s" % (r.get("Name", ""), r.get("Last Name", "")))] = r

    import datetime as _dt
    stamp = _dt.date.today().strftime("%m/%d/%Y")

    out: Dict[str, Dict[str, str]] = {}
    for who, answers in (verdicts or {}).items():
        row = by_key.get(B._fold(who))
        if row is None:
            continue                      # not on this week's board
        for column, verdict in (answers or {}).items():
            if column not in allowed:
                raise ValueError(
                    "%r may not tick %r — it owns %s"
                    % (source, column, ", ".join(sorted(allowed))))
            if verdict is True:
                text = stamp
            elif isinstance(verdict, str) and verdict.strip():
                text = verdict.strip()
            else:
                continue                  # False = not done, None = unread
            answered = str(row.get(column) or "").strip()
            if answered and not is_alert(answered):
                # A TICK is written once. A STATUS may advance, and only
                # advance -- so a late "Sent" email cannot pull somebody back
                # from Passed, and a `Showed Up` date CAN replace an earlier
                # No Show, because somebody marked absent on Monday walking in
                # on the Tuesday is the case this board exists to survive.
                if column not in B.STATUS_STEPS:
                    continue
                if (B.status_rank(text, column)
                        <= B.status_rank(answered, column)):
                    continue
            if is_alert(text) and answered:
                continue                  # an ask does not replace an ask
            name = ("%s %s" % (row.get("Name", ""), row.get("Last Name", ""))).strip()
            out.setdefault(column, {})[name] = text
    return out


def describe(got: Dict[str, Dict[str, str]]) -> str:
    """What a dry run says. One line per column, names spelled out — a count
    on its own cannot be checked against anything. Where a column carries a
    value rather than a date, the value is shown with the name."""
    if not got:
        return "  nothing to tick"
    lines = []
    for col, people in sorted(got.items()):
        bits = []
        for name in sorted(people):
            text = people[name]
            dated = len(text) == 10 and text[2] == "/" and text[5] == "/"
            bits.append(name if dated else "%s (%s)" % (name, text))
        lines.append("  %-20s %d  %s" % (col, len(people), ", ".join(bits)))
    return "\n".join(lines)


def apply(workbook, week_start, source: str,
          verdicts: Mapping[str, Mapping[str, object]],
          *, dry_run: bool = True, log=print, office_key: str = "") -> int:
    """Tick what `source` has earned. DRY BY DEFAULT.

    Every filler goes through here rather than writing cells itself, so the
    on-only rule and the marked-off rule are kept in one place instead of
    being re-implemented five times.
    """
    from automations.icd_onboarding import sheet as S

    # Their own week tab where they have a book, the stacked tab otherwise.
    ws = S.board_for(office_key, week_start, create=False) if office_key \
        else S.stacked_tab(workbook)
    if ws is None:
        log("  no board to tick for %s" % (office_key or "this workbook"))
        return 0
    # A column this code knows about and the tab has not got would otherwise
    # never appear on a board that already existed.
    #
    # NOT ON A DRY RUN. A header is a write, and a dry run writes nothing --
    # this sat above the dry-run check and would quietly add columns to a live
    # board during a verification run (2026-11-15). It says what it would add
    # instead, which is the useful half anyway.
    if dry_run:
        head = [str(h).strip() for h in (S._values(ws)[S.HEADER_ROW - 1] or [])]
        would = [c for c in list(B.COLUMNS) + list(S.PAST_THE_CHART)
                 if c not in head]
        if would:
            log("  (dry run — would add the %s column(s))" % ", ".join(would))
    else:
        try:
            S.ensure_columns(ws, log=log)
        except Exception as e:   # noqa: BLE001 — never fail a tick over a header
            log("  (could not add missing columns: %s)" % type(e).__name__)
    rows = B.for_week(S.rows_of(ws.get_all_values()), week_start)
    got = plan(rows, source, verdicts)
    log("%s, week of %s:" % (source, B.week_label(week_start)))
    log(describe(got))
    if dry_run:
        log("  (dry run — nothing written)")
        return 0
    n = 0
    for column, people in got.items():
        # The tab this already opened, handed down: five columns were five
        # re-opens and five re-reads of the same board.
        n += S.write_step(workbook, week_start, column, people, ws=ws,
                          log=lambda *a: None)
    log("  ticked %d" % n)
    return n


# --------------------------------------------------- finding an office's board

def workbook_for(office_key: str):
    """The Google workbook holding that office's Onboarding tab.

    Their own metrics workbook — the one they already have. Resolved from
    `office_metrics.offices` so there is no second list of sheet ids to drift.
    Raises rather than returning None: a silent miss here is a tick that never
    lands and nobody notices.
    """
    from automations.recruiting_report.fill import open_by_key

    key = str(office_key or "").strip().lower()
    from automations.office_metrics import offices as OM
    rows = OM.OFFICES if isinstance(OM.OFFICES, list) else list(OM.OFFICES.values())
    for o in rows:
        if str(getattr(o, "key", "")).strip().lower() == key:
            sid = getattr(o, "sheet_id", "")
            if not sid:
                raise RuntimeError("office %r has no metrics workbook" % office_key)
            return open_by_key(sid)
    # Alphalete itself is not an ICD and has no metrics workbook; its board
    # lives on Raf's All in One.
    if key == "raf":
        from automations.shared.workbooks import ALL_IN_ONE_RAF
        return open_by_key(ALL_IN_ONE_RAF)
    raise RuntimeError(
        "no office %r in office_metrics.offices — its board cannot be found"
        % office_key)


# ------------------------------------- reaching the board from either machine

def on_office_machine(office_key: str = "") -> bool:
    """Is this the office's OWN computer, the one with no Google access?

    True only where a LucyEco enrolment for that office is installed, which is
    exactly the machine that cannot open a Sheet. A Lucy has an admin key and
    no office enrolment, so it answers False and keeps using gspread -- and so
    does a dev checkout, which is why nothing changes for a hand run.
    """
    from automations.icd_onboarding import relay_board as RB
    return RB.available(office_key)


def rows_anywhere(office_key: str, week_start, *, log=print) -> List[Dict]:
    """That office's rows for the week, read whichever way this machine can.

    Every step reads the board before it writes it -- to obey on-only, to skip
    anyone marked off, and to know who is even on the week. On a Lucy that is a
    gspread read; on the office's own computer there is no such thing, so it
    goes through the relay. An empty list means the week has nobody on it, and
    a board that could not be read raises rather than answering "nobody"
    ([[feedback_empty_means_proven_zero]]).
    """
    from automations.icd_onboarding import relay_board as RB
    from automations.icd_onboarding import sheet as S

    if on_office_machine(office_key):
        return B.for_week(RB.week(office_key, week_start), week_start)
    # `board_for`, NOT `open_board(workbook_for(...))`. The second reads the
    # old stacked `Onboarding` tab, and every office with a book of their own
    # -- a tab per week, Megan 2026-11-21 -- has their people somewhere else
    # entirely. It answered "nobody on the board for that week" about a week
    # with 32 people on it, and every step that reads before it writes then
    # did nothing at all: Blue Ink, Contact Added and Added to APEX all read
    # 0 of 32 on Raf's 11/22 board (found 2026-11-24).
    #
    # `apply` has always used `board_for`. So the writes were aimed at the
    # right tab while the reads were aimed at the old one, which is why this
    # failed as silence rather than as an error -- the steps had nobody to
    # write about. `test_fillers` now holds the two to the same sheet.
    ws = S.board_for(office_key, week_start, create=False)
    if ws is None:
        log("  no board for %s on the week of %s yet"
            % (office_key, B.week_label(week_start)))
        return []
    return B.for_week(S.rows_of(ws.get_all_values()), week_start)


def apply_anywhere(office_key: str, week_start, source: str,
                   verdicts, *, dry_run: bool = True, log=print) -> int:
    """`apply`, aimed at whichever way THIS machine can reach the board.

    On a Lucy that is gspread, unchanged. On the office's own computer it is
    the relay, which is the whole point: an ICD's onboarding should run on the
    ICD's machine, against the ICD's own logins (Megan, 2026-11-16).

    The on-only rule is applied twice on the relay path, on purpose. Here,
    because `plan` needs to know what a cell already says to handle an ask
    that must not replace an ask; and again at the relay, which refuses a
    rewrite whatever a caller sends. Two machines could be ticking the same
    week at once during a changeover, and the write is the only place that can
    settle it.
    """
    from automations.icd_onboarding import relay_board as RB

    if not on_office_machine(office_key):
        # PASS THE OFFICE ON. Without it `apply` falls to its own default of
        # "" and opens the old stacked tab instead of the office's own week
        # tab -- so a run reported "ticked 12" while the twelve cells landed
        # on the board nobody reads any more (2026-11-22: a new start's six
        # OwnerVille columns, counted and lost). Same shape as by_hand.write
        # on 2026-11-21: a green run and an unchanged board.
        return apply(workbook_for(office_key), week_start, source, verdicts,
                     dry_run=dry_run, log=log, office_key=office_key)

    rows = B.for_week(RB.week(office_key, week_start), week_start)
    got = plan(rows, source, verdicts)
    log("%s, week of %s (through the relay):" % (source, B.week_label(week_start)))
    log(describe(got))
    if dry_run:
        log("  (dry run — nothing written)")
        return 0
    n = 0
    for column, people in got.items():
        if column in B.STATUS_STEPS:
            out = RB.advance(office_key, week_start, column, people,
                             dry_run=False, log=log)
        else:
            out = RB.tick(office_key, week_start, column, list(people),
                          dry_run=False, log=log)
        n += int(out.get("changed") or 0)
    log("  ticked %d" % n)
    return n


def seed_anywhere(office_key: str, week_start, people, *,
                  dry_run: bool = True, log=print):
    """`sheet.seed`, aimed the same way. Returns whatever that path returns.

    Both sides are idempotent and both skip somebody already on the week, so
    an hourly seed behaves the same wherever it runs.
    """
    from automations.icd_onboarding import relay_board as RB
    from automations.icd_onboarding import sheet as S

    if not on_office_machine(office_key):
        return S.seed(workbook_for(office_key), week_start, people,
                      dry_run=dry_run, log=log,
                      ws=S.board_for(office_key, week_start,
                                     create=not dry_run))
    out = RB.seed(office_key, week_start, people, dry_run=dry_run, log=log)
    # Same shape sheet.seed answers with, so callers counting `add` do not
    # have to know which machine they are on.
    return {"add": list(out.get("names") or []),
            "keep": int(out.get("already") or 0), "left": []}


def alert(office_key: str, week_start, source: str,
          asks: Mapping[str, str], *, dry_run: bool = True, log=print) -> int:
    """Write what a step is WAITING ON A PERSON FOR into its own column.

    `asks` is {person: one sentence}. It goes in the source's column with
    `ALERT_PREFIX`, so the leader reading down that column sees what to do,
    and the step's real date overwrites it later with no tidying up.

    Used by the Apex run for a name its two sources spell differently (Megan,
    2026-11-15: "that 'alert' needs to go back to the admin to approve the
    correct name so that you can run it"). It does not tick anything and it
    never replaces an answer that is already there.
    """
    cols = columns_for(source)
    if len(cols) != 1:
        raise ValueError(
            "%r owns %d columns; say which with apply()" % (source, len(cols)))
    verdicts = {}
    for who, said in (asks or {}).items():
        said = " ".join(str(said or "").split())
        if not str(who or "").strip() or not said:
            continue
        verdicts[str(who)] = {cols[0]: ALERT_PREFIX + said}
    if not verdicts:
        return 0
    return apply(workbook_for(office_key), week_start, source, verdicts,
                 dry_run=dry_run, log=log)


def tick(office_key: str, week_start, source: str, names: Iterable[str],
         *, dry_run: bool = True, log=print) -> int:
    """Tick one source's single column for `names`, on an office's board.

    For the jobs that know the answer AT THE MOMENT THEY DO THE THING — the
    contact sync as it adds somebody, the Apex run as it saves a record. They
    write straight to the sheet because they run on a machine that already has
    Google access; the relay exists for the EXTENSION, which does not.

    Megan, 2026-11-09, choosing this over reading a state file afterwards: "the
    contact job ticks the board as it goes ... so the ICD can see that it's
    done."
    """
    cols = columns_for(source)
    if len(cols) != 1:
        raise ValueError(
            "%r owns %d columns; say which with apply()" % (source, len(cols)))
    verdicts = {str(n): {cols[0]: True} for n in names if str(n or "").strip()}
    if not verdicts:
        return 0
    try:
        book = workbook_for(office_key)
    except RuntimeError as e:
        log("  board: %s" % e)
        return 0
    return apply(book, week_start, source, verdicts, dry_run=dry_run, log=log)
