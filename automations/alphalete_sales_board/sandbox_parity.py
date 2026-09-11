"""The walk-through that answers one question: are the two tabs the same?

WHY IT EXISTS. While the Talk-To columns are being judged, the week carries two
tabs -- 'Sales Board WE m.d' and its 'SANDBOX — ' twin -- and the whole point of
the sandbox is that the only difference between them is the three new columns.
The sweep already mirrors the day's SALES onto the twin (run._mirror_to_sandbox).
What it can NOT mirror is everything a person types: the roll-call letters, and
above all the 'T' that marks a rep TERMINATED.

Eve, 2026-09-11: *"levanta los reps que fueron Terminated en la sandbox, esos se
cargan a mano, no lo haces vos, por eso te pido que lo pongas como paso a
chequear, para que queden iguales las dos tabs"*. So the terminations are not
written here and never will be -- they are LISTED, side by side, as a step she
ticks off. A report that quietly "fixed" a termination would be writing a
personnel record nobody asked it to write.

WHAT IT COMPARES, by label on both tabs and never by row (the two tabs are
sorted differently, so the same rep sits on different rows):

  * the ROSTER -- who is on one tab and not the other;
  * every day block, sub-header by sub-header, for the reps on both. Split into
    what the sweep writes (Int / Int Up / DTV / NL / TK) and what a person
    writes (Roll Call, and any status letter -- X, T, RT, CR...);
  * the TERMINATIONS, read with the tracker's own reader
    (`terminated_reps.board.scan_grid`), so 'T' anywhere in a day block counts
    exactly like it does for the Terminated Reps report.

'Apps' is skipped: it is an ARRAYFORMULA over the cells already compared, so a
difference there is the same finding twice. Columns that exist on only one tab
(the trio, while it is still being evaluated) are reported as INFO, not as a
difference -- that asymmetry is the experiment, not a fault.

READ-ONLY. Nothing here writes a cell.

    python -m automations.alphalete_sales_board.sandbox_parity
    python -m automations.alphalete_sales_board.sandbox_parity --all
    python -m automations.alphalete_sales_board.sandbox_parity --tab "SANDBOX — Sales Board WE 9.20"
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 -- Windows console, best effort
    pass

from automations.alphalete_sales_board.fill import SANDBOX_PREFIX
from automations.alphalete_sales_board.talk_to_columns import (
    PROD_SHEET_ID, SANDBOX_TAB, TRIO, _cell, day_blocks)
from automations.energy_slack_fill.run import SUB_ROW, last_rep_row, name_col
from automations.rep_sales_fill.board import STATUS_WORDS, _norm_name
from automations.terminated_reps import board as BD

# What the machine fills. A gap here is OUR bug: the mirror runs on the same
# scrape as the live write, so these have no honest reason to disagree.
AUTO_HEADERS = ("Int", "Int Up", "DTV", "NL", "TK", "EN")

# What a person fills. A gap here is a TO-DO for Eve, not a defect.
HAND_HEADERS = ("Roll Call",)

# Derived on the tab itself; compared, but reported apart so a formula that
# reads a cell we already flagged doesn't look like a second problem.
SKIP_HEADERS = ("Apps",)

AUTO, MANO, DERIVADA = "AUTOMATICA", "A MANO", "DERIVADA"

_TERM_MARKS = BD.TERM_MARKS          # {'t', 'terminated'}
_WE_RE = re.compile(r"we\s+(\d{1,2})\.(\d{1,2})\s*$", re.I)


# --------------------------------------------------------------- tab names
def live_title(sandbox_tab: str) -> str:
    """'SANDBOX — Sales Board WE 9.13' -> 'Sales Board WE 9.13'.

    The prefix is the only difference by construction (fill.SANDBOX_PREFIX), so
    stripping it is how the twin names its own original -- no second constant to
    keep in step."""
    t = (sandbox_tab or "").strip()
    pref = SANDBOX_PREFIX.strip()
    if t.lower().startswith(pref.lower()):
        return t[len(pref):].strip()
    return t


def week_monday(tab: str, today: Optional[dt.date] = None) -> Optional[dt.date]:
    """The Monday of the week a 'WE m.d' tab covers, or None if unnamed.

    It dates every 'T' mark, so it is worth being explicit: the tab is named for
    its SUNDAY and the week runs Mon->Sun, so Monday is that Sunday minus six.
    The year comes from `terminated_reps.board`, which picks the candidate
    closest to today rather than assuming this one."""
    m = _WE_RE.search(tab or "")
    if not m:
        return None
    sunday = BD._resolve_tab_date(int(m.group(1)), int(m.group(2)),
                                  today or dt.date.today())
    return None if sunday is None else sunday - dt.timedelta(days=6)


# ------------------------------------------------------------------ roster
def roster(grid) -> Dict[str, Tuple[int, str]]:
    """{normalised name: (row, name as the tab spells it)} for the roster block.

    Normalised because the same rep is 'Jaylen Walker' on one tab and
    'Jaylen Walker (Wk 2)' on the other the week they cross a tenure line, and
    that is not a difference anyone wants reported."""
    nc, last = name_col(grid), last_rep_row(grid)
    out = {}
    for r in range(SUB_ROW + 1, last + 1):
        name = _cell(grid, r, nc).strip()
        if name:
            out[_norm_name(name)] = (r, name)
    return out


def headers(grid, block) -> Dict[str, int]:
    """{sub-header: column} for one day block, row 3, as spelled."""
    lo, hi = block
    out = {}
    for c in range(lo, hi + 1):
        h = " ".join(_cell(grid, SUB_ROW, c).split())
        if h and h not in out:
            out[h] = c
    return out


def _kind(header: str, a: str, b: str) -> str:
    """Which of the three buckets a differing cell belongs in."""
    if header in HAND_HEADERS:
        return MANO
    for v in (a, b):
        f = v.strip().upper()
        if f in STATUS_WORDS or f.lower() in _TERM_MARKS:
            return MANO             # somebody typed a roll-call letter in here
    return AUTO if header in AUTO_HEADERS else DERIVADA


# ------------------------------------------------------------------- diffs
def cell_diffs(live, sbx) -> Tuple[List[tuple], List[str]]:
    """([(kind, day, header, name, live_value, sbx_value)], [info lines]).

    Walks the days both tabs have, the headers both blocks have and the reps
    both rosters have -- anything one-sided is INFO, because during the
    evaluation the sandbox is SUPPOSED to be wider."""
    lr, sr = roster(live), roster(sbx)
    shared_names = sorted(set(lr) & set(sr), key=lambda n: lr[n][0])
    lb, sb = day_blocks(live), day_blocks(sbx)
    diffs, info = [], []

    for day in sorted(set(lb) & set(sb), key=lambda d: lb[d][0]):
        lh, sh = headers(live, lb[day]), headers(sbx, sb[day])
        only_l, only_s = sorted(set(lh) - set(sh)), sorted(set(sh) - set(lh))
        if only_l:
            info.append("%s: columna(s) solo en la live: %s"
                        % (day, ", ".join(only_l)))
        if only_s:
            extra = [h for h in only_s if h not in TRIO]
            tag = "" if extra else " (el trio, esperado)"
            info.append("%s: columna(s) solo en la sandbox: %s%s"
                        % (day, ", ".join(only_s), tag))
        for h in sorted(set(lh) & set(sh), key=lambda x: lh[x]):
            if h in SKIP_HEADERS:
                continue
            for n in shared_names:
                a = _cell(live, lr[n][0], lh[h]).strip()
                b = _cell(sbx, sr[n][0], sh[h]).strip()
                if a != b:
                    diffs.append((_kind(h, a, b), day, h, lr[n][1], a, b))
    return diffs, info


def patched(grid, updates):
    """A copy of `grid` with a batch of `fill.plan` updates already applied.

    The sweep reads both grids BEFORE it writes, so comparing them raw would
    report every cell the sweep is in the middle of fixing as a difference --
    a false alarm 150 times a day. Applying the same updates in memory costs no
    API call and compares the tabs as they will be a second from now.
    """
    out = [list(r) for r in grid]
    for u in updates or []:
        ref = str(u.get("range", "")).split("!")[-1]
        m = re.match(r"^\$?([A-Za-z]+)\$?(\d+)$", ref)
        if not m:
            continue                    # a multi-cell range: not what plan emits
        col = 0
        for ch in m.group(1).upper():
            col = col * 26 + (ord(ch) - 64)
        row = int(m.group(2))
        while len(out) < row:
            out.append([])
        line = out[row - 1]
        while len(line) < col:
            line.append("")
        line[col - 1] = str(u["values"][0][0])
    return out


def terminations(grid, tab: str, monday: dt.date) -> Tuple[Dict[str, object], List[str]]:
    """({normalised name: Termination}, [notes]) for one tab.

    Straight through `terminated_reps.board.scan_grid` -- the same reader the
    Terminated Reps report files from -- so 'terminated here' means exactly what
    it means there: a filled Termination Date, a 'T' anywhere in a day block, or
    'Terminated' in the New Starts box. A layout it cannot read comes back as a
    note instead of an exception: the recorrida still has a roster and cells to
    report on."""
    try:
        rows, checks = BD.scan_grid(grid, tab, monday)
        lay = BD.find_layout(grid)
    except BD.BoardLayoutError as e:
        return {}, ["%s: no se pudo leer las bajas (%s)" % (tab, e)]
    notes = []
    for c in checks:
        # A 'T' on a day that also carries knocks is NOT a contradiction by
        # itself: the rep can be let go in the afternoon after knocking all
        # morning. What decides it is the days AFTER (Eve, 2026-09-11: *"la
        # clave es revisar los siguientes dias, pudo haber tenido knocks ese
        # dia porque fue terminated por la tarde"*). Ivan Munoz, WE 9.13: T on
        # Monday with TK=22, then T and nothing else Tue..Sun -- a termination.
        if c.proposed is not None and c.marked_date is not None:
            later = _works_after(grid, c.row, lay,
                                 (c.marked_date - monday).days)
            if not later:
                rows.append(c.proposed)
                continue
            notes.append("%s fila %d: T el %s pero sigue trabajando despues "
                         "(%s)" % (c.name, c.row, _DAYS[c.marked_date.weekday()],
                                   ", ".join(later[:4])))
            continue
        notes.append("%s fila %d: %s" % (c.name, c.row, c.reason))
    return {BD.norm_name(t.name): t for t in BD.dedupe(rows)}, notes


_DAYS = ("lun", "mar", "mie", "jue", "vie", "sab", "dom")

# Roll-call words that say the rep was NOT in the field. After a 'T' they are
# no evidence of still working (the 'T' letters themselves and the blanks, 'x',
# '0' are already neutral in terminated_reps.board).
_NOT_WORKING = {"off", "o-na", "ffp"}


def _is_work(value) -> bool:
    """Does this cell say the rep worked that day? A non-zero number, or a
    roll-call status that means they showed up ('Here', 'H+DC', 'Late'...)."""
    v = BD._mark(value)
    if v in BD.TERM_MARKS or v in BD.NEUTRAL_MARKS or v in _NOT_WORKING:
        return False
    try:
        return float(v.rstrip("%").replace(",", "")) != 0
    except ValueError:
        return True


def _works_after(grid, row: int, lay, first_off: int) -> List[str]:
    """['mar Int=2', ...] -- every cell AFTER the first 'T' day that says the
    rep was still working. Empty = the termination stands, whatever the 'T' day
    itself shows."""
    out = []
    for off, c0, c1 in lay.day_blocks:
        if off <= first_off:
            continue
        for c in range(c0, c1 + 1):
            v = BD._cell(grid, row, c)
            if _is_work(v):
                h = str(BD._cell(grid, lay.header_row, c) or "col %d" % c).strip()
                out.append("%s %s=%s" % (_DAYS[off], h, str(v).strip()))
    return out


def term_diffs(live, live_tab, sbx, sbx_tab, monday):
    """(solo_live, solo_sandbox, distinta_fecha, [notes]) -- the manual step.

    Nothing here is ever written. The three lists ARE the checklist: a name in
    `solo_live` has to be marked on the sandbox by hand, one in `solo_sandbox`
    on the live tab, and `distinta_fecha` means both tabs agree the rep is gone
    and disagree about the day."""
    lt, ln = terminations(live, live_tab, monday)
    st, sn = terminations(sbx, sbx_tab, monday)
    only_l = [lt[k] for k in sorted(set(lt) - set(st))]
    only_s = [st[k] for k in sorted(set(st) - set(lt))]
    both = [(lt[k], st[k]) for k in sorted(set(lt) & set(st))
            if lt[k].term_date != st[k].term_date]
    # Say which tab a note came from: the same contradiction usually sits on
    # BOTH (the sandbox was copied from the live tab), at different rows.
    return (only_l, only_s, both,
            ["live: " + n for n in ln] + ["sandbox: " + n for n in sn])


# ------------------------------------------------------------------ report
def _d(t) -> str:
    return "%s %d/%d" % (t.term_date.strftime("%a"), t.term_date.month,
                         t.term_date.day)


def summary_lines(live, live_tab, sbx, sbx_tab, monday) -> List[str]:
    """The lines the 5-minute sweep logs: one summary, plus a line per
    termination the two tabs disagree about. Short on purpose -- this runs ~150
    times a day, and a checklist that long is a checklist nobody reads."""
    lr, sr = roster(live), roster(sbx)
    only_l, only_s, both, _notes = term_diffs(live, live_tab, sbx, sbx_tab, monday)
    diffs, _info = cell_diffs(live, sbx)
    auto = [d for d in diffs if d[0] == AUTO]
    mano = [d for d in diffs if d[0] == MANO]
    out = ["recorrida sandbox: roster %d/%d, celdas auto %d distinta(s), "
           "a mano %d, bajas live %d / sandbox %d"
           % (len(lr), len(sr), len(auto), len(mano),
              len(only_l) + len(both), len(only_s) + len(both))]
    for t in only_l:
        out.append("  PASO MANUAL - baja %r (%s) esta en la live y NO en la "
                   "sandbox" % (t.name, _d(t)))
    for t in only_s:
        out.append("  PASO MANUAL - baja %r (%s) esta en la sandbox y NO en la "
                   "live" % (t.name, _d(t)))
    for a, b in both:
        out.append("  PASO MANUAL - baja %r: live %s / sandbox %s"
                   % (a.name, _d(a), _d(b)))
    return out


def report(live, live_tab, sbx, sbx_tab, monday,
           *, show_all: bool = False) -> Tuple[List[str], int]:
    """([lines], how many things to look at). The full walk-through."""
    lines = ["recorrida %r  vs  %r" % (sbx_tab, live_tab), ""]
    lr, sr = roster(live), roster(sbx)
    faltan_s = [lr[k][1] for k in sorted(set(lr) - set(sr), key=lambda n: lr[n][0])]
    faltan_l = [sr[k][1] for k in sorted(set(sr) - set(lr), key=lambda n: sr[n][0])]
    diffs, info = cell_diffs(live, sbx)
    only_l, only_s, both, notes = term_diffs(live, live_tab, sbx, sbx_tab, monday)

    lines.append("ROSTER: %d en la live, %d en la sandbox, %d en las dos"
                 % (len(lr), len(sr), len(set(lr) & set(sr))))
    for n in faltan_s:
        lines.append("   falta en la SANDBOX : %s" % n)
    for n in faltan_l:
        lines.append("   falta en la LIVE    : %s" % n)

    lines.append("")
    lines.append("PASO MANUAL - BAJAS (Terminated). Esto lo cargas vos; el "
                 "script solo las lista:")
    if not (only_l or only_s or both):
        lines.append("   ok: las dos tabs marcan las mismas %d baja(s)"
                     % len(terminations(live, live_tab, monday)[0]))
    for t in only_l:
        lines.append("   cargar en la SANDBOX: %-28s %s  (live fila %d, %s)"
                     % (t.name, _d(t), t.row, t.source))
    for t in only_s:
        lines.append("   cargar en la LIVE   : %-28s %s  (sandbox fila %d, %s)"
                     % (t.name, _d(t), t.row, t.source))
    for a, b in both:
        lines.append("   fecha distinta      : %-28s live %s / sandbox %s"
                     % (a.name, _d(a), _d(b)))
    for n in notes:
        lines.append("   revisar             : %s" % n)

    for kind, title in (
            (AUTO, "CELDAS QUE ESCRIBE EL SWEEP (Int/Int Up/DTV/NL/TK)"),
            (MANO, "CELDAS A MANO (Roll Call y letras de estado)"),
            (DERIVADA, "COLUMNAS DERIVADAS (formulas del trio)")):
        rows = [d for d in diffs if d[0] == kind]
        lines.append("")
        lines.append("%s: %d diferencia(s)" % (title, len(rows)))
        for _k, day, h, name, a, b in (rows if show_all else rows[:15]):
            lines.append("   %-4s %-18s %-26s live %-8r sandbox %r"
                         % (day, h[:18], name[:26], a, b))
        if not show_all and len(rows) > 15:
            lines.append("   ... %d mas (--all)" % (len(rows) - 15))

    if info:
        lines.append("")
        lines.append("INFO (asimetrias esperadas mientras se evalua el trio):")
        for i in info:
            lines.append("   %s" % i)

    pend = (len(faltan_s) + len(faltan_l) + len(only_l) + len(only_s)
            + len(both) + len(notes) + len(diffs))
    return lines, pend


# --------------------------------------------------------------------- cli
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tab", default=SANDBOX_TAB, help="la tab sandbox")
    ap.add_argument("--live", default=None,
                    help="la tab real (default: la sandbox sin el prefijo)")
    ap.add_argument("--sheet-id", default=PROD_SHEET_ID)
    ap.add_argument("--all", action="store_true", help="listar cada celda")
    a = ap.parse_args(argv)

    from automations.recruiting_report.fill import open_by_key
    ss = open_by_key(a.sheet_id)
    sbx_tab = a.tab
    lv_tab = a.live or live_title(sbx_tab)
    monday = week_monday(lv_tab)
    if monday is None:
        print("no puedo sacar la semana de %r (esperaba '... WE m.d')" % lv_tab)
        return 2
    sbx = ss.worksheet(sbx_tab).get_all_values()
    live = ss.worksheet(lv_tab).get_all_values()

    lines, pend = report(live, lv_tab, sbx, sbx_tab, monday, show_all=a.all)
    for ln in lines:
        print(ln)
    print("")
    print("%d cosa(s) para mirar" % pend)
    return 1 if pend else 0


if __name__ == "__main__":
    raise SystemExit(main())
