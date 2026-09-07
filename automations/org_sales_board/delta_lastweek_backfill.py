"""Backfill the per-day 'Last week' cells of a delta-box row that was added
AFTER last week's freeze — the daily breakdown a new person never got.

THE RULE THIS ENFORCES (Eve, 2026-08-31, on JAIRO CAPTAINSHIP):
"siempre que agregues a alguien a una capitania y a un delta chart, hay que
backfillear el desglose diario de la semana pasada de estas personas."

WHY THE CELLS ARE EMPTY. In a delta box every day is a THIS WEEK / LAST WEEK /
DELTA triplet. The 'This week' cells are =SUMIFs over the section's daily
table, so somebody added today is populated the same morning. The 'Last week'
cells are NOT formulas — they are last week's numbers FROZEN into place by
Tuesday's rollover (`rollover.plan_delta_rollover`). A row that did not exist
on that Tuesday was never frozen, so its seven per-day 'Last week' cells stay
BLANK and col D ('Total for week' -> Last week, an enumerated =G+J+M+P+S+V+Y)
sums to 0.

WHY THAT IS WORSE THAN IT LOOKS. Nothing errors. The row shows a real week
against 0, its Delta reads a flat 0.00%, and the box's totals row — whose
'Last week' cells are =SUM() over these very cells
([[project_org-board-delta-totals-lastweek-never-rolls]]) — comes out SHORT by
exactly the people who were added. Abdallah Ghousheh and Fernando Munoz had
sold 62 and 67 in the week Jairo's box was comparing against, and it said 0.

WHERE THE NUMBERS COME FROM: `backup_pre_rollover`, the board's own values-only
snapshot taken immediately BEFORE each Tuesday's rollover (rollover.BACKUP_TAB).
In that snapshot the person's delta row still shows last week as 'This week' —
which is, exactly, the cell the freeze would have copied. So this is not a
second opinion about somebody's week, it is the freeze being run late for one
row. No Tableau, no crosstab, no metric to choose: a Fiber box gets the Fiber
number and an NDS box the NDS one, because both come off the same board.

The snapshot only holds the week that just closed, so this has to run before
the next Tuesday overwrites it. It runs daily, inside the board fill.

IT CHECKS THE SNAPSHOT BEFORE IT TRUSTS IT. Every delta row that ALREADY has
its 'Last week' days filled is a known answer: it must equal that person's
'This week' in the snapshot. Those rows are compared first and a mismatch
refuses the whole run — that is what a stale or half-written backup tab looks
like, and it is not something to find out by writing 126 wrong cells.

BLANK IS THE SIGNAL, AND ONLY BLANK. A cell is filled only when it is empty:
empty means "nobody ever froze anything here", a literal 0 means "frozen, and
the answer was zero". So this is idempotent, it can never walk over a
rollover's work, and a row that is already complete costs nothing. A cell
holding a FORMULA is never touched either.

NOBODY IS LEFT BLANK — STAGE 2 (Eve, 2026-09-07: "cada vez que se agregue una
persona nueva ... aplicalo como regla general ... si no tienen ventas=0").

The snapshot only carries people who were already ON the board last Tuesday, so
it settles a MOVE between captainships and nothing else. A genuinely new ICD —
Nicolas Lujan, added to Carlos' captainship on 09/05 — is not in it, and used
to be left blank and merely named in the log. Blank is the failure this whole
module exists to remove, so the leftovers now go to a SECOND source:

  * the same three all-teams program crosstabs the captainship fill uses
    (`captainship.pull_programs`: fiber / b2b / nds), pinned to LAST week
    instead of this one. Same views, same product filters, same retry policy —
    imported, never re-listed, so the two can't drift.
  * a name the program pull DOES carry is filled with its real per-day numbers.
  * a name absent from every program is filled with a literal 0. That is not an
    invention: these views omit zero rows, which is exactly how the captainship
    fill reads absence when it writes NS for an ICD with no sales this week.

WHEN IT STILL REFUSES. Absence only means zero if the pull actually happened,
so stage 2 writes nothing at all when the program it needed FAILED to render,
when the pull cannot be calibrated against rows that are already frozen (>10%
of them disagreeing = the wrong week or the wrong view), or when there is no
Tableau session to pull with. In every one of those the cells stay blank and
the log says which — a blank row is visible, a wrong 0 is not.

Costs nothing on a normal day: stage 2 only opens a browser at all when stage 1
leaves something over, which is only the morning after somebody is added.

    python -m automations.org_sales_board.delta_lastweek_backfill          # dry-run
    python -m automations.org_sales_board.delta_lastweek_backfill --apply
    python -m automations.org_sales_board.delta_lastweek_backfill --offline # snapshot only
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automations.recruiting_report.fill import open_by_key, _retry     # noqa: E402
from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB      # noqa: E402
from automations.org_sales_board import rollover as ro                 # noqa: E402
from automations.org_sales_board import week as wk                     # noqa: E402
from automations.org_sales_board.delta_manual_fill import _cell        # noqa: E402
from automations.focus_office_att.aliases import load_aliases          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                                      # noqa: BLE001
    pass

# How many already-frozen rows have to agree with the snapshot before its
# numbers are used for the blank ones. Low enough that a small board still
# calibrates, high enough that it is not one lucky row.
MIN_CALIBRATION_ROWS = 5

# Same idea for stage 2, where the two sides are the board and a Tableau pull
# rather than the board and its own snapshot, so they are allowed to disagree a
# little: a frozen cell is the fill's answer from a week ago and a rep can be
# re-filed under another captain since. Above this share it is not drift, it is
# the wrong week or the wrong view, and nothing is written.
MIN_PROGRAM_CALIBRATION_ROWS = 5
MAX_PROGRAM_DISAGREE_SHARE = 0.10


def _key(name: str) -> str:
    """Accent- and case-insensitive name key.

    One board can type 'Fernando Munoz' where another types 'Fernando Muñoz'.
    A plain .lower() match misses that and the person is reported as absent —
    which reads exactly like a real 'was not here last week', so the backfill
    would quietly do nothing for the one row it exists for."""
    s = unicodedata.normalize("NFKD", (name or "").strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def _day_names(grid, table: dict) -> Dict[int, str]:
    """{this-week column -> weekday name}, read off the row ABOVE the header.

    The header row is 'This week / Last week / Delta' repeated seven times with
    nothing in it saying which day a triplet belongs to; the day names sit one
    row up. By label, never by column letter."""
    day_row = table["header_row"] - 1
    out: Dict[int, str] = {}
    for c in table["this_cols"]:
        name = _cell(grid, day_row, c)
        if name:
            out[c] = name
    return out


def box_kind(grid, table: dict) -> str:
    """What a delta box COUNTS, from the sub-label under its own title.

    A person is not enough to key on: Rafael and the five Fiber captains each
    have TWO boxes over the same roster — 'NEW INTERNET UNITS' and 'ALL UNITS'
    — so the same name carries two different (and both correct) sets of
    numbers. Keying on the person alone made 40 of them ambiguous.

    The sub-label sits one row under the box's title row and lives in col A on
    this board, col B on others, so read B then A — the same fallback
    `captainship_drafts.sales_board` uses on these very blocks."""
    hdr = table["header_row"]
    for r in (hdr, hdr - 1):
        txt = (_cell(grid, r, 2) or _cell(grid, r, 1)).upper()
        if "NEW INTERNET" in txt:
            return "NEW INTERNET"
        if "ALL UNITS" in txt or txt.endswith("UNITS"):
            return "ALL UNITS"
    return "ALL UNITS"          # the board's default box, and the NDS/B2B one


def snapshot_index(backup) -> Tuple[Dict[tuple, Dict[str, str]], List[str]]:
    """({(kind, name) -> {day: value}}, ambiguous keys) from the backup.

    Read off the snapshot's own delta boxes, 'This week' side: on that Tuesday
    morning 'This week' WAS the week the live board now calls 'Last week'.

    A key that still lands in two boxes with DIFFERENT numbers is dropped and
    reported rather than guessed at — a captainship box and a cross-cutting one
    (TRANG'S ORG, RAF SPECIAL TEAM) can legitimately count different products
    for the same person, and picking whichever came first would be a coin flip.
    Two boxes that agree are not ambiguous, just duplicated."""
    seen: Dict[tuple, List[Dict[str, str]]] = {}
    manual = {rep for _t, rep in ro.manual_fill_rows(backup)}
    for t in ro.find_delta_tables(backup):
        days = _day_names(backup, t)
        kind = box_kind(backup, t)
        for r in t["data_rows"]:
            name = _cell(backup, r, 2)
            if not name or name.strip().lower() in manual:
                continue        # hand-keyed rows: delta_manual_fill owns them
            got = {d: _cell(backup, r, c) for c, d in days.items()}
            seen.setdefault((kind, _key(name)), []).append(got)
    index: Dict[tuple, Dict[str, str]] = {}
    ambiguous: List[str] = []
    for k, rows in seen.items():
        if all(r == rows[0] for r in rows[1:]):
            index[k] = rows[0]
        else:
            ambiguous.append(f"{k[1]} ({k[0]})")
    return index, ambiguous


def calibrate(grid, index) -> Tuple[int, List[str]]:
    """(rows checked, disagreements) between the live 'Last week' cells that
    ARE filled and the snapshot. The snapshot is only trusted when this is
    clean — see the module docstring."""
    checked, bad = 0, []
    manual = {rep for _t, rep in ro.manual_fill_rows(grid)}
    for t in ro.find_delta_tables(grid):
        days = _day_names(grid, t)
        kind = box_kind(grid, t)
        for r in t["data_rows"]:
            name = _cell(grid, r, 2)
            if not name or name.strip().lower() in manual:
                continue
            src = index.get((kind, _key(name)))
            if not src:
                continue
            pairs = [(days[c], _cell(grid, r, c + 1)) for c in days]
            if any(v == "" for _d, v in pairs):
                continue                       # not fully frozen: nothing to check
            checked += 1
            diff = [f"{d} {v!r}≠{src.get(d, '')!r}" for d, v in pairs
                    if v != src.get(d, "")]
            if diff:
                bad.append(f"{name} (fila {r}): " + ", ".join(diff))
    return checked, bad


def blank_cells(grid, formulas) -> List[dict]:
    """Every delta-box cell that is an EMPTY per-day 'Last week'.

    [{row, name, last_col, day}] — the whole planning input, derived from the
    grid alone so the caller can skip the backup tab when it comes back
    empty."""
    out: List[dict] = []
    manual = {rep for _t, rep in ro.manual_fill_rows(grid)}
    for t in ro.find_delta_tables(grid):
        days = _day_names(grid, t)
        kind = box_kind(grid, t)
        for r in t["data_rows"]:
            name = _cell(grid, r, 2)
            if not name or name.strip().lower() in manual:
                continue
            for c, day in days.items():
                lc = c + 1                     # the triplet's 'Last week'
                if _cell(grid, r, lc) != "":
                    continue                   # frozen already (0 counts)
                if _cell(formulas, r, lc).startswith("="):
                    continue                   # a formula owns this cell
                out.append({"row": r, "name": name, "kind": kind,
                            "last_col": lc, "day": day})
    return out


# ------------------------------------------------------- stage 2: Tableau

def box_title(grid, table: dict) -> str:
    """The box's own banner — "CARLOS CAPTAINSHIP", "Chan's Captainship",
    "RAF SPECIAL TEAM". Read UPWARD from the header row in col A then col B,
    skipping the 'NEW INTERNET UNITS' / 'ALL UNITS' sub-label that `box_kind`
    reads, because a fiber captain's two boxes carry the banner one row higher
    than everybody else's. Returns "" when there is none (the caller then just
    searches every program, which is what the captainship fill does anyway)."""
    hdr = table["header_row"]
    for r in (hdr - 1, hdr - 2, hdr - 3):
        for c in (1, 2):
            v = (_cell(grid, r, c) or "").strip()
            if not v:
                continue
            up = v.upper()
            if "UNITS" in up and "CAPTAIN" not in up:
                continue            # the kind sub-label, not the banner
            return v
    return ""


def program_hint(title: str) -> str:
    """Which program's crosstab to look in FIRST for a box titled `title`.

    A HINT only, exactly as in `captainship.TYPE_HINTS`: the lookup falls back
    across every program, so a box the map has never heard of (RAF SPECIAL
    TEAM, TRANG'S ORG, a captainship added this morning) still resolves — it
    just pays for one wasted first lookup."""
    from automations.org_sales_board import captainship as cap
    key = re.sub(r"\b(CAPTAINSHIP|CAPTAIN|TEAM|ORG)\b", " ",
                 (title or "").upper())
    return cap.TYPE_HINTS.get(cap._cap_key(" ".join(key.split())),
                              cap.DEFAULT_TYPE)


def box_metric(kind: str) -> Optional[str]:
    """The pull metric a box of this `kind` reads. None = the program default
    (all units); a New Internet box reads the New-Internet-only sum of the very
    same crosstab, the way `captainship.run_captainships` routes its two fiber
    boxes."""
    return "NewInternet" if kind == "NEW INTERNET" else None


def program_days(prog: dict, hint: str, name: str, kind: str, aliases):
    """(per-day dict, program key) for `name` in the last-week program pull, or
    (None, None) when no program carries them at all.

    Deliberately the same search `captainship.per_for` does — hinted program
    first, then every other one — so a rep filed under an unexpected Tableau
    team is found here for the same reason they are found there."""
    from automations.org_sales_board import captainship as cap
    cands = cap._candidates_for_name(name, aliases)
    metric = box_metric(kind)
    for tk in [hint] + [k for k in prog if k != hint]:
        pdata = prog.get(tk) or {}
        k = next((x for x in pdata if x in cands), None)
        if k:
            return pdata[k].get(metric or cap.TYPES[tk]["metric"], {}), tk
    return None, None


def lastweek_programs(today: dt.date, page=None, out_dir=None, logfn=print):
    """({program: parsed}, [failed programs]) for the week the delta boxes are
    comparing AGAINST — one week before the live one.

    `today - 7` rather than a hand-built date, so the Monday lag (the board
    rolls Tuesday — `week.reporting_sunday`) applies identically to both weeks.
    The pull is written under its own name so it can never overwrite the
    current week's downloads sitting next to it."""
    from pathlib import Path as _Path
    from automations.org_sales_board import captainship as cap
    return cap.pull_programs(
        page, today - dt.timedelta(days=7),
        out_dir=_Path(out_dir) if out_dir else _Path("output") / "_lastweek",
        out_prefix="org_sales_board_lastweek_", logfn=logfn)


def calibrate_programs(grid, prog, day_dates, aliases) -> Tuple[int, List[str]]:
    """(rows checked, disagreements) between the delta rows that are ALREADY
    frozen and the last-week program pull.

    The twin of `calibrate`, and for the same reason: a pull that came back on
    the wrong week, or off a view somebody has since re-pointed, looks exactly
    like a good one. The rows whose answer is already on the board are the only
    way to tell, so they are checked before a single blank is written."""
    checked, bad = 0, []
    manual = {rep for _t, rep in ro.manual_fill_rows(grid)}
    for t in ro.find_delta_tables(grid):
        days = _day_names(grid, t)
        kind = box_kind(grid, t)
        hint = program_hint(box_title(grid, t))
        for r in t["data_rows"]:
            name = _cell(grid, r, 2)
            if not name or name.strip().lower() in manual:
                continue
            pairs = [(days[c], _cell(grid, r, c + 1)) for c in days]
            if any(v == "" for _d, v in pairs):
                continue                  # not frozen: nothing known to check
            src, _tk = program_days(prog, hint, name, kind, aliases)
            if src is None:
                continue                  # absent: that is what stage 2 tests
            checked += 1
            diff = []
            for d, v in pairs:
                want = str(int(src.get(day_dates.get(d), 0) or 0))
                if (v or "0").strip() != want:
                    diff.append(f"{d} {v!r}!={want}")
            if diff:
                bad.append(f"{name} (fila {r}): " + ", ".join(diff[:4]))
    return checked, bad


def plan_from_programs(grid, cells, prog, failed, day_dates, aliases
                       ) -> Tuple[List[dict], List[str]]:
    """[{range, values}] + notes for the cells stage 1 could not settle.

    A name the pull carries gets its real numbers; a name no program carries
    gets a literal 0 — these crosstabs omit zero rows, so absence IS zero, the
    same reading `captainship.run_captainships` makes when it writes NS. Unless
    a program FAILED to pull: then absence means nothing at all, and the row is
    left blank and named."""
    hints = {}
    for t in ro.find_delta_tables(grid):
        hint = program_hint(box_title(grid, t))
        for r in t["data_rows"]:
            hints[r] = hint
    updates: List[dict] = []
    notes: List[str] = []
    said: set = set()
    for c in cells:
        src, tk = program_days(prog, hints.get(c["row"], "fiber"),
                               c["name"], c["kind"], aliases)
        if src is None and failed:
            if c["name"] not in said:
                said.add(c["name"])
                notes.append(
                    f"{c['name']}: no esta en el pull de la semana pasada, "
                    f"pero {', '.join(failed)} no se pudo bajar — sin ese "
                    f"programa 'ausente' no quiere decir cero; se deja en "
                    f"blanco")
            continue
        if c["name"] not in said:
            said.add(c["name"])
            notes.append(
                f"{c['name']}: alta nueva, no un pase — "
                + (f"de la vista {tk!r} de la semana pasada"
                   if src is not None else
                   "ninguna vista lo trae la semana pasada: van 0"))
        updates.append({"range": f"{ro.a1col(c['last_col'])}{c['row']}",
                        "values": [[int((src or {}).get(
                            day_dates.get(c["day"]), 0) or 0)]]})
    return updates, notes


def plan(cells, index) -> Tuple[List[dict], List[dict], List[str]]:
    """(updates, leftover cells, notes) for `blank_cells` against the snapshot.

    Anybody the snapshot carries is settled here — that is a MOVE between
    captainships, and their frozen answer already exists. Anybody it does not
    is handed back as `leftover` for stage 2 to resolve off Tableau instead of
    being written off as a blank."""
    updates: List[dict] = []
    leftover: List[dict] = []
    notes: List[str] = []
    missing: set = set()
    for c in cells:
        src = index.get((c["kind"], _key(c["name"])))
        if src is None:
            leftover.append(c)
            if c["name"] not in missing:
                missing.add(c["name"])
                notes.append(
                    f"{c['name']}: no está en el snapshot pre-roleo — alta "
                    f"nueva, no un pase de capitanía; va a la vista de la "
                    f"semana pasada")
            continue
        updates.append({"range": f"{ro.a1col(c['last_col'])}{c['row']}",
                        "values": [[src.get(c["day"], 0) or 0]]})
    return updates, leftover, notes


def apply_backfill(ws, today: Optional[dt.date] = None,
                   dry_run: bool = False, logfn=print, page=None,
                   offline: bool = False) -> List[dict]:
    """Fill every blank per-day 'Last week' cell on `ws`.

    Two sources, in order: the pre-rollover snapshot (a move between
    captainships), then last week's program crosstabs (a brand-new person, and
    a literal 0 when no view carries them). Reads the grid first and returns
    before touching either one when nothing is blank, so the normal day costs
    one read and never opens a browser.

    `page` reuses a live patchright session if the caller already has one;
    `offline` skips stage 2 entirely."""
    today = today or dt.date.today()
    grid = _retry(ws.get_all_values)
    formulas = _retry(lambda: ws.get_all_values(value_render_option="FORMULA"))
    cells = blank_cells(grid, formulas)
    if not cells:
        logfn("  cajas delta: ningún 'Last week' por día en blanco — nada que "
              "backfillear")
        return []

    # ---- stage 1: the board's own snapshot of the week that just closed.
    # A backup tab that is missing or does not reconcile is NOT fatal any more:
    # it only means no move can be settled from it, and stage 2 is a wholly
    # independent source for the same cells.
    index: Dict[tuple, Dict[str, str]] = {}
    try:
        bws = ws.spreadsheet.worksheet(ro.BACKUP_TAB)
        backup = _retry(bws.get_all_values)
    except Exception as e:                                    # noqa: BLE001
        logfn(f"  [!] no hay pestaña {ro.BACKUP_TAB!r} ({e}) — sin snapshot "
              f"para los pases entre capitanías")
        backup = None
    if backup:
        index, ambiguous = snapshot_index(backup)
        for a in ambiguous:
            logfn(f"    [!] {a}: aparece en dos cajas del snapshot con números "
                  f"distintos — se deja en blanco")
        checked, disagree = calibrate(grid, index)
        if disagree:
            for d in disagree[:8]:
                logfn(f"    [!] {d}")
            logfn(f"  [!] {ro.BACKUP_TAB!r} NO coincide con las filas ya "
                  f"congeladas ({len(disagree)} de {checked}) — snapshot viejo "
                  f"o a medio escribir; no se usa")
            index = {}
        elif checked < MIN_CALIBRATION_ROWS:
            logfn(f"  [!] sólo {checked} fila(s) congeladas para verificar el "
                  f"snapshot (hacen falta {MIN_CALIBRATION_ROWS}) — no se usa")
            index = {}
        else:
            logfn(f"  snapshot {ro.BACKUP_TAB!r} verificado contra {checked} "
                  f"fila(s) ya congeladas")

    updates, leftover, notes = plan(cells, index)
    for n in notes:
        logfn(f"    [!] {n}")

    # ---- stage 2: last week's program crosstabs, for the people the snapshot
    # never carried. Only reached when stage 1 left something over, which is
    # only the morning after somebody was added to a captainship.
    if leftover and offline:
        logfn(f"  [!] {len(leftover)} celda(s) sin resolver y --offline — "
              f"quedan en blanco")
    elif leftover:
        try:
            names = ", ".join(dict.fromkeys(c["name"] for c in leftover))
            logfn(f"  bajando las vistas de la semana pasada para: {names}")
            aliases = load_aliases()
            day_dates = {d.strftime("%A"): d
                         for d in wk.reporting_week(today - dt.timedelta(days=7))}
            if page is not None:
                prog, failed = lastweek_programs(today, page=page, logfn=logfn)
            else:
                from automations.shared.tableau_patchright import tableau_session
                with tableau_session(verbose=False) as _pg:
                    prog, failed = lastweek_programs(today, page=_pg,
                                                     logfn=logfn)
            chk, bad = calibrate_programs(grid, prog, day_dates, aliases)
            share = (len(bad) / chk) if chk else 1.0
            if chk < MIN_PROGRAM_CALIBRATION_ROWS:
                logfn(f"  [!] sólo {chk} fila(s) congeladas para verificar el "
                      f"pull de la semana pasada (hacen falta "
                      f"{MIN_PROGRAM_CALIBRATION_ROWS}) — no se escribe nada "
                      f"de la etapa 2")
            elif share > MAX_PROGRAM_DISAGREE_SHARE:
                for d in bad[:8]:
                    logfn(f"    [!] {d}")
                logfn(f"  [!] el pull de la semana pasada NO coincide con las "
                      f"filas ya congeladas ({len(bad)} de {chk}) — semana o "
                      f"vista equivocada; no se escribe nada de la etapa 2")
            else:
                logfn(f"  pull de la semana pasada verificado contra {chk} "
                      f"fila(s) congeladas ({len(bad)} difieren)")
                u2, n2 = plan_from_programs(grid, leftover, prog, failed,
                                            day_dates, aliases)
                for n in n2:
                    logfn(f"    [!] {n}")
                updates += u2
        except Exception as e:                                # noqa: BLE001 —
            # a resolver that cannot reach Tableau must not take down the
            # backfill it rides on, let alone the board fill above THAT.
            logfn(f"  [!] etapa 2 (vistas de la semana pasada) salteada "
                  f"({type(e).__name__}: {str(e)[:90]}) — esas celdas quedan "
                  f"en blanco")

    for u in updates:
        logfn(f"    {u['range']} ← {u['values'][0][0]}")
    if updates and not dry_run:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    logfn(f"  'Last week' por día backfilleado: {len(updates)} celda(s)"
          + (" (dry-run)" if dry_run else " escritas" if updates else ""))
    return updates


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="completa el desglose diario de 'Last week' de las filas "
                    "que se agregaron a una caja delta después del roleo")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--tab", default=SANDBOX_TAB)
    ap.add_argument("--today", default=None, help="YYYY-MM-DD")
    ap.add_argument("--offline", action="store_true",
                    help="sólo el snapshot pre-roleo: no abre Tableau, así que "
                         "un alta nueva queda en blanco en vez de en 0")
    args = ap.parse_args(argv)
    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.date.today())
    print(f"=== backfill 'Last week' por día — {args.tab!r} — "
          f"{'APPLY' if args.apply else 'DRY-RUN'} ===")
    ws = _retry(lambda: open_by_key(SHEET_ID).worksheet(args.tab))
    apply_backfill(ws, today=today, dry_run=not args.apply,
                   offline=args.offline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
