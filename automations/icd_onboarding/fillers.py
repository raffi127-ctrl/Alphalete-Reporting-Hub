"""Letting the existing automations tick the ICD board.

Megan, 2026-11-09: "wire up the fillers so the steps tick themselves."

Nearly every step already has something that knows the answer. None of it is
rewritten here — this is the one place those answers become ticks, so there is
a single thing to read when asking what is allowed to mark somebody's step
done, and a single place the rules live.

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
                   "UID Request", "Owner Submit"),
    "blueink": ("Blue Ink",),
    "sterling": ("BG Status",),
    "contacts": ("Contact Added",),
    "apex": ("Added to APEX",),
}


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
            if str(row.get(column) or "").strip():
                continue                  # already answered; nothing to do
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
          *, dry_run: bool = True, log=print) -> int:
    """Tick what `source` has earned. DRY BY DEFAULT.

    Every filler goes through here rather than writing cells itself, so the
    on-only rule and the marked-off rule are kept in one place instead of
    being re-implemented five times.
    """
    from automations.icd_onboarding import sheet as S

    ws = S.open_board(workbook, create=False)
    if ws is None:
        log("  no %s tab on this workbook" % B.TAB)
        return 0
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
