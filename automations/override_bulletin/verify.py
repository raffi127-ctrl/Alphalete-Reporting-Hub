"""Cell-for-cell verification of the override pulls against a week the VA
ALREADY filled by hand — read-only, writes nothing anywhere.

Why this exists. Every earlier check was a COVERAGE check ("16 of 21 actives
matched"), which proves we found a row for someone, not that we found the RIGHT
number. The CAPTAIN/SPECIAL block especially (Carlos / Colten / Khalil / Jairo /
Eveliz, from the DD pull) had never been compared against a filled week — and a
captain's weekly figure is a SUM of several Captain's-Bonus lines, so a parse
that picks one line instead of the sum looks perfectly healthy until you compare
the dollars.

So: pull week W exactly as the Friday fill would, assemble the same section-1 /
section-2 write plan, then diff it against what the VA actually typed in the LIVE
tab's W column. Anything that disagrees is printed as a MISMATCH line.

    python -m automations.override_bulletin.verify                 # newest filled week
    python -m automations.override_bulletin.verify --week 7.12.26

RUN ON LUCY 1 (Raf's org login) — the pulls need Raf's Tableau session. Nothing
is written to any sheet, so it is safe to run against the LIVE tab (and it must
be: the VA's numbers are the answer key).
"""
from __future__ import annotations

import argparse
import sys

from automations.override_bulletin import fill as F
from automations.override_bulletin import pulls as P
from automations.override_bulletin import run as R

# A cent of drift is rounding, not a parse error. The VA types whole dollars for
# captain rows and 2dp for regular overrides.
TOLERANCE = 0.01


def newest_filled_week(ws):
    """The newest week label on the tab that actually carries numbers — the most
    recent week the VA has finished, i.e. the one worth checking against."""
    for label in R.sheet_weeks(ws):
        if F.week_is_filled(ws, label):
            return label
    return None


def _cell_value(vals, row_1based, col_0based):
    """Displayed value of a cell as a float, or None if blank/unparseable."""
    if row_1based - 1 >= len(vals):
        return None
    row = vals[row_1based - 1]
    if col_0based >= len(row):
        return None
    return P._num_locale(row[col_0based])


def compare(ws, week_mdy, section1, section2, roster, captains):
    """[(kind, row, label, ours, theirs, delta)] for every cell we would write.

    `ours` is what the pull produced; `theirs` is what the VA typed. A row the VA
    left blank is reported as theirs=None (not 0) — blank and zero are different
    claims and collapsing them would hide a whole missing source."""
    vals = ws.get_all_values()
    col = F.week_col(ws, week_mdy, header=vals[0] if vals else [])
    if col is None:
        raise ValueError(f"no column headed {week_mdy!r} on {ws.title!r}")
    row_label = {}
    for _key, (r, _active, disp) in roster.items():
        row_label[r] = ("ALL ORG", disp)
    for _key, rows in captains.items():
        leader = (vals[rows["total"] - 1][0] or "").strip()
        if rows.get("captain"):
            row_label[rows["captain"]] = ("CAPTAIN", f"{leader} · Captain Override")
        if rows.get("special"):
            row_label[rows["special"]] = ("SPECIAL", f"{leader} · Special Override")

    out = []
    for r, ours in sorted(list(section1.items()) + list(section2.items())):
        kind, label = row_label.get(r, ("?", f"row {r}"))
        theirs = _cell_value(vals, r, col)
        delta = None if theirs is None else round(ours - theirs, 2)
        out.append((kind, r, label, ours, theirs, delta))
    return col, out


def verify(week_mdy=None, *, tab=F.LIVE_TAB, verbose=True):
    from automations.recruiting_report import fill as _fill
    from automations.shared.tableau_patchright import tableau_session

    wb = _fill._client().open_by_key(F.WORKBOOK_ID)
    ws = wb.worksheet(tab)
    aliases = F.load_alias_map()
    roster = F.read_roster(ws, aliases)
    captains = F.read_captains(ws, aliases)

    week_mdy = week_mdy or newest_filled_week(ws)
    if not week_mdy:
        print("VERIFY: no filled week on the tab — nothing to check against")
        return 1
    m, d, y = week_mdy.split(".")
    week_header = "{}/{}/20{}".format(int(m), int(d), y[-2:])
    print("VERIFY week {} on {!r} (answer key = the VA's own column)".format(
        week_mdy, tab))

    # strict=False: this is a diagnostic, so a source that fails to export is
    # RECORDED and the other four are still compared. Its rows then surface as
    # mismatches below rather than as a crash with nothing to show.
    failures = []
    with tableau_session(headless=True, verbose=verbose) as page:
        regular, captain, special = R.pull_all(
            week_mdy, week_header, period_num=int(m), period_year="20" + y[-2:],
            page=page, verbose=verbose, aliases=aliases,
            strict=False, failures=failures)
    print("pulls: regular={} captain={} special={}".format(
        len(regular), len(captain), len(special)))

    section1, section2, unmatched = F.assemble(
        week_mdy, roster, captains, regular=regular, captain=captain,
        special=special, ws=ws, aliases=aliases)
    col, rows = compare(ws, week_mdy, section1, section2, roster, captains)

    bad = [r for r in rows if r[5] is None or abs(r[5]) > TOLERANCE]
    print("\ncompared {} cell(s) against column {}: {} match, {} MISMATCH".format(
        len(rows), F._col_letter(col), len(rows) - len(bad), len(bad)))
    for kind, r, label, ours, theirs, delta in bad:
        print("MISMATCH [{}] row {} {}: ours={} theirs={} delta={}".format(
            kind, r, label, ours, theirs, delta))
    if verbose:
        print("\nfull comparison:")
        for kind, r, label, ours, theirs, delta in rows:
            flag = "  " if (delta is not None and abs(delta) <= TOLERANCE) else "!!"
            print("{} [{:<8}] row {:>3} {:<42} ours={:>12} theirs={:>12}".format(
                flag, kind, r, label[:42], ours, theirs))
    if unmatched:
        print("\nno source row ({}) — these are $0 by fill-but-flag, "
              "check each: {}".format(len(unmatched), ", ".join(unmatched)))
    for msg in failures:
        print("\nSOURCE FAILED — its rows below are NOT a real disagreement: {}".format(msg))
    print("\nVERIFY RESULT: {}{}".format(
        "ALL {} CELLS MATCH".format(len(rows)) if not bad
        else "{} of {} cells disagree".format(len(bad), len(rows)),
        " ({} source(s) failed to export)".format(len(failures)) if failures else ""))
    return 0 if not bad else 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="sheet week label e.g. 7.12.26 "
                                   "(default: the newest FILLED week on the tab)")
    ap.add_argument("--tab", default=F.LIVE_TAB,
                    help="tab to check against (default: the live tab — it holds "
                         "the VA's hand-typed answer key). Read-only either way.")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    # Always exit 0: a mismatch is a REPORT, not a crashed run, and a non-zero
    # would make `lucy rerun` / the Hub card cry failure on a diagnostic.
    verify(a.week, tab=a.tab, verbose=not a.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
