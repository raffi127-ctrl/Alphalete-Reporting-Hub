"""Lucy Salesboard Fixer -- audit a Sales Board tab (and its Line Up), fix
what is safe, write down what it did.

Raf's ask (Slack, 2026-10-06): once a day Lucy audits every sales board, fixes
it, tells the owner "this is what I noticed, I just fixed this", and Eve gets a
weekly list of everything Lucy touched. Eve, 2026-10-07: test it on OUR board
first (Alphalete SALES BOARD 2025), on a SANDBOX twin, then roll out.

LIVE since 2026-10-12 (Eve: "aplica en produccion y podes eliminar esas
sandbox"). Every morning it audits and fixes this week's 'Sales Board WE m.d',
'Line Up WE m.d' and 'Stations' -- so each new week's board is covered the day
the week roll creates it. The SANDBOX twins (2026-10-07..10-11) are gone.

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
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 -- Windows console, best effort
    pass

from automations.sales_board_fixer import checks as K
from automations.rep_sales_fill import board as B

SHEET_ID = "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc"   # Alphalete SALES BOARD 2025
STATIONS_TAB = "Stations"         # one tab, not per week
REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "sales_board_fixer"


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


def load(sh, title: str) -> dict:
    ws = sh.worksheet(title)
    values = ws.get_all_values()
    formulas = ws.get_all_values(value_render_option="FORMULA")
    meta = sh.fetch_sheet_metadata({
        "fields": "sheets(properties(sheetId,title,gridProperties),conditionalFormats)"})
    sheet = next(s for s in meta["sheets"] if s["properties"]["title"] == title)
    ncols = sheet["properties"]["gridProperties"]["columnCount"]
    fonts, numfmts, notes = [], [], []
    if title_kind(title) == "board":
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
    return {"ws": ws, "title": title, "sheet_id": ws.id, "values": values,
            "formulas": formulas, "rules": sheet.get("conditionalFormats", []),
            "ncols": ncols, "fonts": fonts, "numfmts": numfmts, "notes": notes}


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


def title_kind(title: str) -> str:
    if re.match(r"^Sales Board WE\s", title, re.I):
        return "board"
    return "lineup"


def audit(t: dict) -> list:
    title, v, f = t["title"], t["values"], t["formulas"]
    if title_kind(title) == "board":
        found = (K.check_formulas(title, v, f) + K.check_roll_call(title, v)
                 + K.check_fonts(title, t["sheet_id"], v, t["fonts"])
                 + K.check_number_formats(title, t["sheet_id"], v, t["numfmts"]))
        first, last = K.block_rows(v)
        fixed_cells = {x.where for x in found if x.value is not None}
        found += [e for e in K.check_errors(title, v, f) if e.where not in fixed_cells]
        found += K.check_conditional(title, t["sheet_id"], t["rules"], t["ncols"],
                                     block=(first, last))
    else:
        found = K.check_errors(title, v, f)
        found += K.check_conditional(title, t["sheet_id"], t["rules"], t["ncols"])
    return found


def backup(t: dict, stamp: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / ("backup_%s_%s.json" % (stamp, _slug(t["title"])))
    p.write_text(json.dumps({"title": t["title"], "values": t["values"],
                             "formulas": t["formulas"], "rules": t["rules"]},
                            ensure_ascii=False), encoding="utf-8")
    return p


def apply(sh, t: dict, found: list) -> list:
    """Write the fixable findings. Returns the ones actually written."""
    ws = t["ws"]
    # The board re-sorts during the day: re-read the names and drop any row
    # whose rep is no longer the one the finding was made for.
    names_now = ws.col_values(B.NAME_COL)
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tab", action="append",
                    help="tab a revisar (repetible). Default: Sales Board + Line Up de esta semana y Stations")
    ap.add_argument("--apply", action="store_true", help="arreglar (backup antes de escribir)")
    ap.add_argument("--sheet-id", default=SHEET_ID)
    ap.add_argument("--date", help="YYYY-MM-DD dentro de la semana (default: hoy)")
    a = ap.parse_args(argv)

    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    sh = _book(a.sheet_id)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    titles = a.tab or list(week_tabs(today)) + [STATIONS_TAB]
    # Monday 04:xx runs before the week roll makes this week's Sales Board:
    # skip it (tomorrow's run picks it up), don't crash
    have = _tabs(sh)
    for title in [t for t in titles if t not in have]:
        print("  no existe %r todavía -- salteada" % title)
    titles = [t for t in titles if t in have]

    results = {}
    for title in titles:
        t = load(sh, title)
        found = audit(t)
        print("%s: %d hallazgos (%d arreglables)" % (title, len(found),
                                                     sum(1 for x in found if x.fixable)))
        if a.apply:
            print("  backup:", backup(t, stamp))
            done = apply(sh, t, found)
            print("  escritos: %d" % len(done))
            left = audit(load(sh, title))
            print("  después de arreglar quedan: %d (%d arreglables)"
                  % (len(left), sum(1 for x in left if x.fixable)))
        results[title] = found
    print("reporte:", report(results, stamp, a.apply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
