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
         verdicts: Mapping[str, Mapping[str, object]]) -> Dict[str, List[str]]:
    """{column: [names to tick]} for one source's answers.

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

    out: Dict[str, List[str]] = {}
    for who, answers in (verdicts or {}).items():
        row = by_key.get(B._fold(who))
        if row is None:
            continue                      # not on this week's board
        for column, verdict in (answers or {}).items():
            if column not in allowed:
                raise ValueError(
                    "%r may not tick %r — it owns %s"
                    % (source, column, ", ".join(sorted(allowed))))
            if verdict is not True:
                continue                  # False = not done, None = unread
            if str(row.get(column) or "").strip():
                continue                  # already ticked; nothing to do
            name = ("%s %s" % (row.get("Name", ""), row.get("Last Name", ""))).strip()
            out.setdefault(column, []).append(name)
    return out


def describe(got: Dict[str, List[str]]) -> str:
    """What a dry run says. One line per column, names spelled out — a count
    on its own cannot be checked against anything."""
    if not got:
        return "  nothing to tick"
    return "\n".join(
        "  %-20s %d  %s" % (col, len(names), ", ".join(sorted(names)))
        for col, names in sorted(got.items()))


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
    for column, names in got.items():
        n += S.tick(workbook, week_start, column, names, log=lambda *a: None)
    log("  ticked %d" % n)
    return n
