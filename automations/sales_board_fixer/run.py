"""Lucy Salesboard Fixer -- audit a Sales Board tab (and its Line Up), fix
what is safe, write down what it did.

Raf's ask (Slack, 2026-10-06): once a day Lucy audits every sales board, fixes
it, tells the owner "this is what I noticed, I just fixed this", and Eve gets a
weekly list of everything Lucy touched. Eve, 2026-10-07: test it on OUR board
first (Alphalete SALES BOARD 2025), on a SANDBOX twin, then roll out.

LIVE since 2026-10-12 (Eve: "aplica en produccion y podes eliminar esas
sandbox"). Every morning it audits and fixes this week's 'Sales Board WE m.d',
'Line Up WE m.d' and 'Stations' -- so each new week's board is covered the day
the week roll creates it. Since 2026-10-19 also the 'Lanes' tab (Rafael's list
of main spreadsheets, #2) -- what gets fixed there is in lanes_check.py.
The SANDBOX twins (2026-10-07..10-11) are gone.

WHAT GETS FIXED vs ONLY REPORTED -- see checks.py for the why of each:
  fixed     formula put back in a formula column (X / number typed over it,
            formula deleted, a row added without formulas); font + size put
            back to the column's majority; Roll Call filled when Int carries
            X/T and the Roll Call is empty; conditional-format rules that can
            never fire (#REF!, pointing outside the tab, exact duplicates).
  reported  error values outside the rep block; conditional formats that stop
            short of the last rep row.

SAFETY. A backup of the tab's values, formulas and rules goes to the output
folder before any write. The board re-sorts itself during the day, so right
before writing the names in col C are read again and any row whose rep moved
is dropped from the batch, never written to the wrong person.

    python -m automations.sales_board_fixer.run                     # audit this week (read-only)
    python -m automations.sales_board_fixer.run --apply             # fix this week + Stations
    python -m automations.sales_board_fixer.run --date 2026-10-05 --apply   # a past week
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 -- Windows console, best effort
    pass

from automations.sales_board_fixer import checks as K
from automations.sales_board_fixer import lanes_check as LC
from automations.sales_board_fixer import tenure as T

SHEET_ID = "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc"   # Alphalete SALES BOARD 2025
STATIONS_TAB = "Stations"         # one tab, not per week
LANES_TAB = LC.TAB                # 'Lanes' -- see lanes_check.py
SANDBOX_PREFIX = "SANDBOX — "     # a test copy of a tab, checked like the real one
# Lanes tabs on owners' sheets: 'Exit Lanes' (Frank, Drew), 'Lanes' (Cyrus),
# 'Lanes JAIRO' (Miami) -- Eve 2026-10-19: "deben ser todos"
LANE_NAME = re.compile(r"\blanes?\b", re.I)
LINEUP_NAME = re.compile(r"\bline ?up\b", re.I)   # 'Line Up WE 10.25', 'Line Up NDS'
MAX_FIXES = 300                   # more than this on one tab = misread, don't write
REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "sales_board_fixer"
LANES_GOOD_FILE = OUT_DIR / "lanes_good.json"   # last healthy Lanes formulas + headers


def week_sunday(today: dt.date) -> dt.date:
    """The board names a week by its SUNDAY (Mon..Sun, 'WE 10.11')."""
    return today + dt.timedelta(days=(6 - today.weekday()))


def week_tabs(today: dt.date):
    s = week_sunday(today)
    tag = "%d.%d" % (s.month, s.day)
    return "Sales Board WE " + tag, "Line Up WE " + tag


def _book(sheet_id: str):
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(sheet_id)


def _tabs(sh) -> dict:
    """{title: sheetId} read fresh -- open_by_key memoises worksheets(), and a
    tab deleted or created a second ago must not be served from that memo."""
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId,title))"})
    return {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}


def load(sh, title: str, titles=()) -> dict:
    """titles: the whole run, so a Line Up knows its board in use (_home_board)."""
    ws = sh.worksheet(title)
    values = ws.get_all_values()
    formulas = ws.get_all_values(value_render_option="FORMULA")
    meta = sh.fetch_sheet_metadata({
        "fields": "sheets(properties(sheetId,title,gridProperties),conditionalFormats,basicFilter)"})
    sheet = next(s for s in meta["sheets"] if s["properties"]["title"] == title)
    ncols = sheet["properties"]["gridProperties"]["columnCount"]
    fonts, numfmts, notes = [], [], []
    if K.is_board(values):
        _, last = K.block_rows(values)
        rng = "'%s'!A1:%s%d" % (title, K.col_letter(ncols), last)
        grid = sh.fetch_sheet_metadata({
            "includeGridData": True, "ranges": [rng],
            "fields": "sheets(data(rowData(values(effectiveFormat("
                      "textFormat(fontFamily,fontSize),numberFormat),note))))"})
        rows = grid["sheets"][0]["data"][0].get("rowData", [])
        for rd in rows:
            vs = rd.get("values", [])
            fonts.append([_font(v) for v in vs])
            numfmts.append([_numfmt(v) for v in vs])
            notes.append([(v or {}).get("note", "") for v in vs])
    t = {"ws": ws, "title": title, "sheet_id": ws.id, "values": values,
         "formulas": formulas, "rules": sheet.get("conditionalFormats", []),
         "basic_filter": sheet.get("basicFilter"),
         "ncols": ncols, "fonts": fonts, "numfmts": numfmts, "notes": notes}
    if LANE_NAME.search(title):
        t.update(load_lanes(sh, t))
    elif LINEUP_NAME.search(title):
        t["home"], t["run_boards"] = _home_board(titles, title)
        t["boards"] = lineup_boards(sh, formulas, t["home"])
    return t


def lineup_boards(sh, formulas, home: str = None) -> dict:
    """{board tab: (name column, first rep row, last rep row)} for every sales
    board the Line Up's name lists read, plus `home` -- what
    check_lineup_names stretches to or moves to."""
    names = {K.ref_tab(m) for row in formulas for f in row for m in [K._name_list(f)] if m}
    if home:
        names.add(home)
    out = {}
    for name in sorted(names & set(_tabs(sh))):
        v = sh.worksheet(name).get_all_values()
        if K.is_board(v):
            out[name] = (K.layout(v).name_col,) + K.block_rows(v)
    return out


def _home_board(titles, title: str):
    """(home, run boards): the board a Line Up belongs to is the last board
    listed before it ('COLTEN', 'Line Up NDS', 'JAIRO', 'Line Up NDS JAIRO').
    A list already reading one of this run's boards keeps it (Jacob has two)."""
    titles = list(titles)
    boards = [x for x in titles
              if not (LINEUP_NAME.search(x) or LANE_NAME.search(x) or "station" in x.lower())]
    before = [x for x in titles[:titles.index(title)] if x in boards] if title in titles else []
    return (before[-1] if before else None), set(boards)


def _lanes_key(sh, title: str) -> str:
    return "%s|%s" % (sh.id, title[len(SANDBOX_PREFIX):] if title.startswith(SANDBOX_PREFIX)
                      else title)


def _lanes_good() -> dict:
    """{sheet|tab: healthy copy}. The first version (10/19) held only ours."""
    try:
        d = json.loads(LANES_GOOD_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {"%s|%s" % (SHEET_ID, LANES_TAB): d} if "formulas" in d else d


def load_lanes(sh, t: dict) -> dict:
    """What lanes_check needs beyond the tab itself: which cells a person
    typed (vs spilled), the board tabs the lanes read, and -- ours only --
    where lanes.py says each week should point."""
    from automations.alphalete_sales_board import lanes as L
    from automations.alphalete_sales_board import fill
    v = t["values"]
    grid = sh.fetch_sheet_metadata({
        "includeGridData": True, "ranges": ["'%s'!A1:%s%d" % (t["title"], K.col_letter(t["ncols"]),
                                                             max(len(v), 1))],
        "fields": "sheets(data(rowData(values(userEnteredValue,note))))"})
    rows = grid["sheets"][0]["data"][0].get("rowData", [])
    entered = [[bool((c or {}).get("userEnteredValue")) for c in rd.get("values", [])]
               for rd in rows]
    notes = [[(c or {}).get("note", "") for c in rd.get("values", [])] for rd in rows]
    have = _tabs(sh)
    ours = sh.id == SHEET_ID
    boards, targets = {}, ({} if ours else None)
    anchor = L.lanes_week(dt.date.today())
    for key, back in ((("current", 0), ("last", 7)) if ours else ()):
        title = fill.tab_title(anchor - dt.timedelta(days=back))
        if title not in have:
            continue
        g = sh.worksheet(title).get_all_values()
        end = L.totals_row([r[2] if len(r) > 2 else "" for r in g])
        if end:
            boards[title], targets[key] = g, (title, end - 1)
    # the tabs the lanes point at today count too (Monday: last week's pair)
    for f in (t["formulas"][r][c] for r in range(min(len(t["formulas"]), 6))
              for c in range(len(t["formulas"][r]))):
        for tab, *_ in LC.ranges(f):
            if tab not in boards and tab in have:
                boards[tab] = sh.worksheet(tab).get_all_values()
    return {"lanes": {"entered": entered, "boards": boards, "targets": targets,
                      "good": _lanes_good().get(_lanes_key(sh, t["title"]))},
            "notes": notes}


def lanes_findings(t: dict) -> list:
    """lanes_check on a loaded tab; [] when it is not a lanes tab after all
    (no 'Current Week' / 'Last week' banner) or our week tab isn't built yet."""
    x = t["lanes"]
    if x["targets"] is not None and len(x["targets"]) < 2:
        return []                      # a week tab missing: lanes.py waits too
    try:
        return LC.check(t["formulas"], t["values"], x["entered"], x["boards"], x["good"],
                        x["targets"], tab=t["title"])
    except RuntimeError:
        return []


def _font(v: dict):
    tf = ((v or {}).get("effectiveFormat") or {}).get("textFormat") or {}
    if not tf.get("fontFamily"):
        return None
    return (tf["fontFamily"], tf.get("fontSize"))


def _numfmt(v: dict):
    nf = ((v or {}).get("effectiveFormat") or {}).get("numberFormat") or {}
    kind, pat = nf.get("type", ""), nf.get("pattern", "")
    # 'm/d/yyyy' and 'M/d/yyyy' print the same date -- not a difference
    return (kind, pat.lower() if kind.startswith("DATE") else pat)


def audit(t: dict, tenure=None, owner: bool = False) -> list:
    """tenure = (history, earliest sunday) from tenure_history(), or None.
    owner: an owner's board -- the Roll Call word is learned off the board."""
    title, v, f = t["title"], t["values"], t["formulas"]
    if "lanes" in t:
        found = lanes_findings(t)
        found += K.check_conditional(title, t["sheet_id"], t["rules"], t["ncols"])
    elif K.is_board(v):
        found = (K.check_formulas(title, v, f) + K.check_roll_call(title, v, learn=owner)
                 + K.check_fonts(title, t["sheet_id"], v, t["fonts"])
                 + K.check_number_formats(title, t["sheet_id"], v, t["numfmts"]))
        first, last = K.block_rows(v)
        fixed_cells = {x.where for x in found if x.value is not None}
        found += [e for e in K.check_errors(title, v, f) if e.where not in fixed_cells]
        found += K.check_conditional(title, t["sheet_id"], t["rules"], t["ncols"],
                                     block=(first, last))
        if tenure and T.has_tenure(v):
            found += T.audit(title, t["sheet_id"], v, f, t.get("basic_filter"), *tenure)
    else:
        found = K.check_errors(title, v, f)
        found += K.check_conditional(title, t["sheet_id"], t["rules"], t["ncols"])
        if t.get("boards"):
            found += K.check_lineup_names(title, f, t["boards"], t.get("home"),
                                          keep=t.get("run_boards", ()))
    return found


def tenure_history(sh, today: dt.date):
    """(history, earliest sunday) off every 'Sales Board WE m.d' tab up to this
    week -- one read. Unformatted, so dates come back as serials."""
    from automations.terminated_reps.board import week_tabs as all_weeks
    weeks = [(d, t) for d, t in all_weeks(sh, today) if d <= week_sunday(today)]
    if not weeks:
        return None
    res = sh.values_batch_get(["'%s'" % t for _, t in weeks],
                              params={"valueRenderOption": "UNFORMATTED_VALUE"})
    grids = [(d, vr.get("values", [])) for (d, _), vr in zip(weeks, res["valueRanges"])]
    return T.history(grids), weeks[0][0]


def backup(t: dict, stamp: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / ("backup_%s_%s.json" % (stamp, _slug(t["title"])))
    p.write_text(json.dumps({"title": t["title"], "values": t["values"],
                             "formulas": t["formulas"], "rules": t["rules"],
                             "basic_filter": t.get("basic_filter")},
                            ensure_ascii=False), encoding="utf-8")
    return p


def apply(sh, t: dict, found: list, notes: bool = True) -> list:
    """Write the fixable findings. Returns the ones actually written.
    notes=False: no hover notes (owners' boards had none 10/12-10/20)."""
    ws = t["ws"]
    # The board re-sorts during the day: re-read the names and drop any row
    # whose rep is no longer the one the finding was made for.
    names_now = (ws.col_values(K.layout(t["values"]).name_col)
                 if any(x.row and x.name for x in found) else [])
    def still_there(x):
        if x.row is None or not x.name:
            return True
        now = names_now[x.row - 1].strip() if x.row - 1 < len(names_now) else ""
        return now == x.name
    todo = [x for x in found if x.fixable and still_there(x)]
    skipped = [x for x in found if x.fixable and not still_there(x)]
    for x in skipped:
        print("  SALTEADA (la fila %d ya no es %s): %s" % (x.row, x.name, x.where))

    cells = [x for x in todo if x.value is not None]
    if cells:
        ws.batch_update([{"range": x.where, "values": [[x.value]]} for x in cells],
                        value_input_option="USER_ENTERED")
    fmt = [x.request for x in todo if x.request and "updateCells" in x.request]
    # a note on every touched cell, so a person can hover and see what changed
    if notes:
        fmt += K.note_requests(todo, t["sheet_id"], t.get("notes") or [],
                               dt.date.today().strftime("%m/%d"))
    # rule deletes last, highest index first (checks.py already sorted them)
    dels = [x.request for x in todo if x.request and "deleteConditionalFormatRule" in x.request]
    if fmt or dels:
        sh.batch_update({"requests": fmt + dels})
    return todo


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "-", s).strip("-")


def report(results: dict, stamp: str, applied: bool) -> Path:
    """One plain-Spanish page for Eve: what was found, grouped by kind."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# Lucy Salesboard Fixer — %s" % stamp, "",
             "Modo: **%s**" % ("ARREGLÓ" if applied else "solo mirar"), ""]
    data = {}
    for title, found in results.items():
        data[title] = [x.as_dict() for x in found]
        lines += ["## %s — %d hallazgos" % (title, len(found)), ""]
        by = {}
        for x in found:
            by.setdefault(x.kind, []).append(x)
        for kind, xs in sorted(by.items(), key=lambda kv: -len(kv[1])):
            fx = sum(1 for x in xs if x.fixable)
            lines.append("### %s — %d (%s)" % (K.KIND_LABEL.get(kind, kind), len(xs),
                                               "se arregla sola" if fx == len(xs)
                                               else "%d se arreglan, %d a mano" % (fx, len(xs) - fx)))
            for x in xs[:40]:
                who = (" · %s" % x.name) if x.name else ""
                lines.append("- `%s`%s — %s → %s" % (x.where, who, x.before, x.after or "—"))
            if len(xs) > 40:
                lines.append("- … y %d más (ver JSON)" % (len(xs) - 40))
            lines.append("")
    md = OUT_DIR / ("%s_report.md" % stamp)
    md.write_text("\n".join(lines), encoding="utf-8")
    (OUT_DIR / ("%s_report.json" % stamp)).write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return md


# Hub: steps on the Sales Board card ('alphalete-sales-board' phases)
HUB_PHASE = "sales-board-fixer"
HUB_PHASE_OWNERS = "sales-board-fixer-owners"


def hub_phase(phase_id: str, name: str, ok: bool) -> None:
    """Colour this fixer's step on the card of the report it fixes (Eve
    2026-10-19: a fixer is a gate behind its report, not a card of its own).
    register_card=False: a PHASE row, never a library card. Best-effort."""
    try:
        from automations.shared import hub_activity
        hub_activity.log_completed(phase_id, name, status="success" if ok else "failed",
                                   register_card=False)
    except Exception as e:  # noqa: BLE001 -- a Hub hiccup never fails the fix
        print("  hub: %s" % e)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tab", action="append",
                    help="tab a revisar (repetible). Default: Sales Board + Line Up de esta semana y Stations")
    ap.add_argument("--apply", action="store_true", help="arreglar (backup antes de escribir)")
    ap.add_argument("--sheet-id", default=SHEET_ID)
    ap.add_argument("--date", help="YYYY-MM-DD dentro de la semana (default: hoy)")
    ap.add_argument("--owners", nargs="?", const="", default=None, metavar="NOMBRE",
                    help="revisar los All-in-One de los dueños (owners.json); "
                         "sólo escribe en los que tienen \"apply\": true")
    a = ap.parse_args(argv)
    # only the full scheduled pass colours the card; a --tab / one owner / a
    # read-only look doesn't
    if a.owners is not None:
        phase = HUB_PHASE_OWNERS if a.apply and a.owners == "" else None
        name = "Lucy Salesboard Fixer (owners)"
    else:
        phase = HUB_PHASE if a.apply and not a.tab and a.sheet_id == SHEET_ID else None
        name = "Lucy Salesboard Fixer"
    try:
        rc = _main(a)
    except Exception:
        if phase:
            hub_phase(phase, name, False)
        raise
    if phase:
        hub_phase(phase, name, rc == 0)
    return rc


def _main(a) -> int:
    if a.owners is not None:
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M") + "_owners"
        results = run_owners(a.owners, a.apply, stamp)
        print("reporte:", report(results, stamp, a.apply))
        return 0

    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    sh = _book(a.sheet_id)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    titles = a.tab or list(week_tabs(today)) + [STATIONS_TAB, LANES_TAB]
    # Monday 04:xx runs before the week roll makes this week's Sales Board:
    # skip it (tomorrow's run picks it up), don't crash
    have = _tabs(sh)
    for title in [t for t in titles if t not in have]:
        print("  no existe %r todavía -- salteada" % title)
    titles = [t for t in titles if t in have]
    results = run_tabs(sh, titles, stamp, a.apply, tenure=tenure_history(sh, today))
    print("reporte:", report(results, stamp, a.apply))
    return 0


def _drop_past(found: list, values, stop: str) -> list:
    """Font / number-format findings at or right of the `stop` header go.
    Jairo's board (2026-10-21) keeps a rep-info section after SUN (Campaign,
    Start Date, Termination Date, checklist): dates and $ there on purpose, and
    with no banner after SUN its columns read as part of Sunday."""
    if not stop or not K.is_board(values):
        return found
    row = values[K.layout(values).day_row - 1]
    col = next((c for c, x in enumerate(row, start=1)
                if " ".join(str(x).split()).lower() == stop.lower()), 0)
    if not col:
        return found
    return [x for x in found if x.kind not in ("font", "number_format")
            or _col_of(x.where) < col]


def _col_of(a1: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", a1).group():
        n = n * 26 + ord(ch) - 64
    return n


def run_tabs(sh, titles, stamp: str, do_apply: bool, label: str = "",
             tenure=None, kinds=None, max_fixes: int = MAX_FIXES,
             format_stop: str = "") -> dict:
    """kinds: only these finding kinds get written, the rest is just reported
    (owners' boards: OWNER_KINDS, no notes).
    max_fixes: per-owner cap (owners.json 'max_fixes').
    format_stop: header (day-banner row) where the board's own section ends --
    font / number-format checks skip that column and everything right of it
    (owners.json 'format_stop')."""
    results = {}
    owner = kinds is not None
    for title in titles:
        t = load(sh, title, titles)
        widened = []
        if do_apply and tenure:
            # Widening the filter re-sorts the rows, so it goes first, alone,
            # and everything else is read again after it.
            widened = [x for x in audit(t, tenure, owner) if x.kind == "filter_short"]
            if widened:
                print("  backup:", backup(t, stamp + "_prefilter"))
                sh.batch_update({"requests": [x.request for x in widened]})
                print("  filtro ampliado: %s -> %s" % (widened[0].before, widened[0].after))
                t = load(sh, title, titles)
        if do_apply:
            # last week's 'Lucy fixed this' notes come along when a week tab
            # is copied: take Lucy's old ones off first, so today's go on clean
            clear, t["notes"] = K.old_note_requests(t["sheet_id"], t.get("notes"), dt.date.today())
            if clear:
                sh.batch_update({"requests": clear})
                print("  notas viejas de Lucy borradas: %d" % len(clear))
        found = _drop_past(audit(t, tenure, owner), t["values"], format_stop)
        if owner:
            name_col = K.layout(t["values"]).name_col if K.is_board(t["values"]) else 0
            for x in found:
                if (x.kind not in kinds or _owners_rank_cell(x, name_col)
                        or (x.kind == "x_over_formula" and not _x_kept(x, t["values"], found))):
                    x.value = x.request = None                      # report only
        n_fix = sum(1 for x in found if x.fixable)
        print("%s%s: %d hallazgos (%d arreglables)" % (label, title, len(found), n_fix))
        if do_apply and n_fix > max_fixes:
            # thousands of "fixes" means the tab was read wrong, not that it
            # is that broken -- never write on a misread
            print("  NO se escribe: %d arreglos es demasiado (tope %d), revisar a mano"
                  % (n_fix, max_fixes))
        elif do_apply:
            print("  backup:", backup(t, stamp))
            done = apply(sh, t, found)
            print("  escritos: %d" % len(done))
            t2 = load(sh, title, titles)
            left = [x for x in _drop_past(audit(t2, tenure, owner), t2["values"], format_stop)
                    if kinds is None or x.kind in kinds]
            print("  después de arreglar quedan: %d (%d arreglables)"
                  % (len(left), sum(1 for x in left if x.fixable)))
        if LANE_NAME.search(title) and not title.startswith(SANDBOX_PREFIX):
            remember_lanes(sh, title)       # never learn from a sandbox copy
        results[label + title] = widened + found
    return results


def remember_lanes(sh, title: str) -> None:
    """Save the Lanes formulas + the headers they read as the healthy copy --
    only when the tab, read again now, has nothing to fix or report on its
    formulas. That copy is what a deleted lane is rebuilt from."""
    t = load(sh, title)
    x = t["lanes"]
    if x["targets"] is not None and len(x["targets"]) < 2:
        return
    try:
        left = [f for f in LC.check(t["formulas"], t["values"], x["entered"], x["boards"],
                                    x["good"], x["targets"], tab=title)
                if f.kind in LC.REPAIRS]
        good = LC.remember(t["formulas"], t["values"], x["boards"])
    except RuntimeError:               # not a lanes tab
        return
    if left or not good["formulas"]:
        return
    allgood = _lanes_good()
    allgood[_lanes_key(sh, title)] = good
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LANES_GOOD_FILE.write_text(json.dumps(allgood, ensure_ascii=False, indent=1), encoding="utf-8")


# --- owners' All-in-One workbooks (2026-10-12) -------------------------------

OWNERS_FILE = Path(__file__).with_name("owners.json")
# a bare week date ('10.12', '10/12') is a board too: Cyrus keeps one set of
# tabs per week, '10.12' + '10.12 Linep' + '10.12 Stations' (2026-10-13);
# Salik/Hammad one tab per Monday, '10/12', '10/5'... (2026-10-14)
BOARD_NAME = re.compile(r"sales\s*board|^\s*w\.?\s*e\b|^\s*\d{1,2}[./]\d{1,2}\s*$", re.I)
SIDE_NAME = re.compile(r"line\s*u?p|stations", re.I)
WEEK_PREFIX = re.compile(r"^\s*(\d{1,2}[./]\d{1,2})\b")
DATED_TAB = re.compile(r"^\s*(\d{1,2})[./](\d{1,2})\s*$")


def this_weeks_tab(visible, today: dt.date, week_end: bool = False):
    """The bare-date tab ('10/12') dated in the last 7 days, newest wins.
    Salik/Hammad keep a dead 'Fiber Sales Board' (WE 8/24) leftmost, so
    leftmost-with-reps alone would pick the wrong board.
    week_end: the tab is named by the week's Sunday, not its Monday (Kash's
    Palace board, '10.18' = 10/12-10/18).
    Owners add each new week on the LEFT, so a tab dated later than one left
    of it is last year's (Palace keeps a year of '10.19'-style tabs, 2026-10-19)."""
    best, left = None, None
    for t in visible:
        m = DATED_TAB.match(t)
        if not m:
            continue
        try:
            d = dt.date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
        if week_end:
            d -= dt.timedelta(days=6)
        if d > today + dt.timedelta(days=6):  # a December tab read in January
            d = d.replace(year=today.year - 1)
        if left is not None and d > left:
            continue
        left = d
        # tabs are named by Monday: next week's tab can exist by Sunday
        if 0 <= (today - d).days <= 6 and (best is None or d > best[0]):
            best = (d, t)
    return best[1] if best else None


def side_tabs(visible, picked) -> list:
    """Line Up / Stations tabs to check. One that starts with a week date
    belongs to that week: only the picked board's week counts, not every old
    week the owner left visible."""
    weeks = {m.group(1) for m in map(WEEK_PREFIX.match, picked) if m}
    out = []
    for t in visible:
        if not SIDE_NAME.search(t) or t.lower().startswith("copy of"):
            continue
        m = WEEK_PREFIX.match(t)
        if m and m.group(1) not in weeks:
            continue
        out.append(t)
    return out


def owner_tabs(sh, boards: int = 1, week_end: bool = False) -> list:
    """The tabs to check in an owner's All-in-One: the leftmost visible sales
    board(s) with reps on it -- owners keep the current week first, and name
    it anything ('Sales Board', 'NEW Sales Board', 'Sales Board W.E 10.11') --
    plus the visible Line Up / Stations tabs (side_tabs). A tab named with
    this week's date ('10/12') goes ahead of the leftmost one."""
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(title,hidden))"})
    visible = [s["properties"]["title"] for s in meta["sheets"]
               if not s["properties"].get("hidden")]
    picked = []
    dated = this_weeks_tab(visible, dt.date.today(), week_end)
    for title in ([dated] if dated else []) + [t for t in visible if t != dated]:
        if len(picked) >= boards:
            break
        if BOARD_NAME.search(title) and not title.lower().startswith("copy of"):
            v = sh.worksheet(title).get_all_values()
            first, last = K.block_rows(v)
            if K.is_board(v) and any(K.name_at(v, r) for r in range(first, last + 1)):
                picked.append(title)
    return picked + side_tabs(visible, picked)


def lane_tabs(sh, only_for=None) -> list:
    """Visible Lanes tabs of an owner's sheet. A book shared by several owners
    (Miami) names them by owner -- 'Lanes JAIRO' -- so with `only_for` (that
    owner's tabs from owners.json) only the ones naming one of them count."""
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(title,hidden))"})
    out = []
    for s in meta["sheets"]:
        t = s["properties"]["title"]
        if s["properties"].get("hidden") or not LANE_NAME.search(t) \
                or t.lower().startswith("copy of"):
            continue
        if only_for is not None and not any(o.strip().lower() in t.lower() for o in only_for):
            continue
        out.append(t)
    return out


# What Lucy writes on an OWNER's board. Eve 2026-10-12: broken formulas and
# color rules only. Eve 2026-10-20: everything ours gets -- fonts, number
# formats, Roll Call, hover notes -- each judged by THAT board's own way: the
# column majority of that board, the Roll Call word that board writes
# (checks.roll_call_words). An X typed over a formula is put back only when the
# Roll Call carries the same status, so the formula shows the X again (_x_kept).
OWNER_KINDS = {"typed_over_formula", "missing_formula", "different_formula",
               "row_added_wrong", "cf_broken", "cf_foreign", "cf_duplicate",
               "lineup_short", "lineup_old_week",
               "font", "number_format", "roll_call_blank", "x_over_formula",
               *LC.REPAIRS}


def _x_kept(x, values, found) -> bool:
    """An X/T typed over an owner's Int formula: putting the formula back is
    safe only if it reads that day's Roll Call and the Roll Call says the same
    status (already, or by today's roll_call_blank fix) -- otherwise the X,
    the attendance record, would vanish."""
    m = re.match(r"([A-Z]+)(\d+)$", x.where or "")
    if not m:
        return False
    c, r = K.col_index(m.group(1)), int(m.group(2))
    status = str(x.before).strip().upper()
    for ic, rc in K.roll_call_cols(values).values():
        if ic != c:
            continue
        rc_cell = K.a1(r, rc)
        if not re.search(r"(?<![A-Z$])\$?%s\$?%d(?!\d)" % (K.col_letter(rc), r), x.value or ""):
            return False
        now = K._g(values, r, rc).strip()
        if not now:
            return any(y.kind == "roll_call_blank" and y.where == rc_cell and y.value
                       for y in found)
        word = K.roll_call_words(values).get(status)
        return now.upper() == status or (word is not None and now == word)
    return False


def _owners_rank_cell(x, name_col: int) -> bool:
    """The '#' column left of the names. Owners write it their own way --
    Rashad switched to =IF(B5<>"",ROW()-3,"") on purpose (2026-10-13) and a
    column majority would put the old =A4+1 chain back. Only a #REF! gets fixed."""
    m = re.match(r"([A-Z]+)\d+$", x.where or "")
    if not m or not name_col or "#REF!" in (x.before or ""):
        return False
    col = 0
    for ch in m.group(1):
        col = col * 26 + ord(ch) - 64
    return col < name_col


REPEATS_FILE = OUT_DIR / "owner_repeats.json"
REPEAT_DAYS = 3                   # same fix N days in a row -> tell Eve
EVE_USER_ID = "U088E2KJEV8"       # Evelyn Sobrino


def repeats(history: dict, written, today: dt.date) -> list:
    """Record today's fixes in `history` ({key: [iso dates]}) and return the
    keys fixed exactly REPEAT_DAYS days in a row ending today -- somebody keeps
    putting it back by hand. Exactly, so Eve hears once, not every day after."""
    days = [(today - dt.timedelta(days=i)).isoformat() for i in range(REPEAT_DAYS + 1)]
    for key in written:
        seen = history.setdefault(key, [])
        if days[0] not in seen:
            seen.append(days[0])
    for key in list(history):                     # keep two weeks
        history[key] = [d for d in history[key]
                        if d >= (today - dt.timedelta(days=14)).isoformat()]
        if not history[key]:
            del history[key]
    return [k for k in written
            if all(d in history[k] for d in days[:REPEAT_DAYS])
            and days[REPEAT_DAYS] not in history[k]]


def _tell_eve(lines) -> None:
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    try:
        who = client.auth_test().get("user", "")
    except Exception:  # noqa: BLE001
        who = ""
    if who and "lucy" not in who.lower():
        print("! esta máquina postea como %s, no Lucy -- no mando el DM" % who)
        return
    text = ("Salesboard Fixer: Lucy fixed these %d days in a row -- someone keeps "
            "changing them back by hand. Ask the owner if they want it that way:\n"
            % REPEAT_DAYS) + "\n".join("• " + l for l in lines)
    ch = client.conversations_open(users=EVE_USER_ID)["channel"]["id"]
    client.chat_postMessage(channel=ch, text=text)
    print("  DM a Eve: %d repetidos" % len(lines))


def run_owners(only, do_apply: bool, stamp: str) -> dict:
    owners = json.loads(OWNERS_FILE.read_text(encoding="utf-8"))["owners"]
    results, written = {}, {}
    for o in owners:
        if only and only.lower() not in o["name"].lower():
            continue
        try:
            sh = _book(o["sheet_id"])
            # one book shared by several owners names its tabs by owner
            # ('COLTEN', 'JAIRO'): list them in owners.json (2026-10-14)
            tabs = ([t for t in o["tabs"] if t in _tabs(sh)] if o.get("tabs")
                    else owner_tabs(sh, o.get("boards", 1), o.get("week_end", False)))
            tabs += [t for t in lane_tabs(sh, o.get("tabs")) if t not in tabs]
        except Exception as e:  # noqa: BLE001 -- one owner's sheet never stops the rest
            print("== %s: NO se pudo abrir (%s)" % (o["name"], type(e).__name__))
            continue
        print("== %s: %s" % (o["name"], tabs or "sin board en uso"))
        # writing on an owner's sheet is switched on owner by owner, in owners.json
        on = do_apply and o.get("apply", False)
        # Miami's big book (2026-10-14) ran the read quota out mid-owner: wait
        # out the minute and redo that owner (a fix already written re-audits
        # clean). Anything else skips the owner, never the rest of the run.
        res = {}
        for attempt in (1, 2):
            try:
                res = run_tabs(sh, tabs, stamp, on, label=o["name"] + " · ", kinds=OWNER_KINDS,
                               max_fixes=o.get("max_fixes", MAX_FIXES),
                               format_stop=o.get("format_stop", ""))
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 1 and "429" in str(e):
                    print("  cuota de lectura de Google -- espero 70s y repito")
                    time.sleep(70)
                    continue
                print("== %s: se cortó (%s)" % (o["name"], type(e).__name__))
        results.update(res)
        if on:
            for tab, found in res.items():
                for x in found:
                    if x.fixable:
                        written["%s | %s | %s" % (tab, x.where, x.kind)] = (
                            "%s %s: %s" % (tab, x.where, K.KIND_LABEL.get(x.kind, x.kind)))
    if written:
        try:
            history = json.loads(REPEATS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            history = {}
        again = repeats(history, list(written), dt.date.today())
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        REPEATS_FILE.write_text(json.dumps(history, indent=1), encoding="utf-8")
        if again:
            _tell_eve([written[k] for k in again])
    return results


if __name__ == "__main__":
    raise SystemExit(main())
