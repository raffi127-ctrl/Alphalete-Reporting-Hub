"""Lucy PNL Fixer -- audit the 'PNL <year>' tab of every owner's All-in-One,
fix what is safe, write down what it did. What is checked: checks.py.

Rafael's list of main spreadsheets (Slack 2026-10-10), #7 "PNL"; Eve
2026-10-20: "avanza con PNL".

A book is written only with "apply": true in books.json (all of them since
Eve's OK, 2026-10-20, after the Aya / Cyrus / Kash previews), or when named
with --owner together with --apply. Mondays 4am, Lucy 4.

SAFETY. A backup of the tab's values + formulas goes to output/pnl_fixer/
before it is written; one batch per tab; a hover note on every touched cell.
More than MAX_FIXES on one tab means it was read wrong -- nothing is written.

    python -m automations.pnl_fixer.run                     # audit every book (read-only)
    python -m automations.pnl_fixer.run --owner Aya --apply
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

from automations.pnl_fixer import checks as P

BOOKS_FILE = Path(__file__).with_name("books.json")
MAX_FIXES = 150
REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "pnl_fixer"


def _book(sheet_id: str):
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(sheet_id)


def tab_name(today: dt.date) -> re.Pattern:
    return re.compile(r"^\s*pnl\s*%d\s*$" % today.year, re.I)


def load(sh, today: dt.date) -> dict:
    """This year's visible PNL tab: formulas, what it shows, notes."""
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId,title,hidden))"})
    want = tab_name(today)
    tab = next((s["properties"] for s in meta["sheets"]
                if want.match(s["properties"]["title"]) and not s["properties"].get("hidden")), None)
    if not tab:
        return {}
    title = tab["title"]
    rng = "'%s'" % title

    def get(render):
        return sh.values_batch_get([rng], params={"valueRenderOption": render}
                                   )["valueRanges"][0].get("values", [])
    formulas, values = get("FORMULA"), get("FORMATTED_VALUE")
    grid = sh.fetch_sheet_metadata({"includeGridData": True, "ranges": [rng],
                                    "fields": "sheets(data(rowData(values(note))))"})
    rows = grid["sheets"][0]["data"][0].get("rowData", [])
    notes = [[(v or {}).get("note", "") for v in rd.get("values", [])] for rd in rows]
    return {"title": title, "sheet_id": tab["sheetId"], "ws": sh.worksheet(title),
            "formulas": formulas, "values": values, "notes": notes}


def _load_retry(name, sid, today):
    for attempt in (1, 2):
        try:
            return load(_book(sid), today)
        except Exception as e:  # noqa: BLE001 -- one book never stops the rest
            if attempt == 1 and "429" in str(e):
                print("  cuota de lectura de Google -- espero 70s y repito")
                time.sleep(70)
                continue
            print("== %s: NO se pudo leer (%s)" % (name, type(e).__name__))
    return {}


def backup(name: str, t: dict, stamp: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / ("backup_%s_%s.json" % (stamp, re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")))
    p.write_text(json.dumps({"title": t["title"], "values": t["values"], "formulas": t["formulas"]},
                            ensure_ascii=False), encoding="utf-8")
    return p


def apply(t: dict, found: list) -> list:
    todo = [x for x in found if x.fixable]
    if todo:
        t["ws"].batch_update([{"range": x.where, "values": [[x.value]]} for x in todo],
                             value_input_option="USER_ENTERED")
        notes = P.note_requests(todo, t["sheet_id"], t["notes"], dt.date.today().strftime("%m/%d"))
        if notes:
            t["ws"].spreadsheet.batch_update({"requests": notes})
    return todo


def report(results: dict, stamp: str, applied: bool) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# Lucy PNL Fixer — %s" % stamp, "",
             "Modo: **%s**" % ("ARREGLÓ" if applied else "solo mirar"), ""]
    for name, found in results.items():
        lines += ["## %s — %d hallazgos (%d se arreglan)"
                  % (name, len(found), sum(1 for x in found if x.fixable)), ""]
        for x in found[:80]:
            lines.append("- `%s` %s — %s → %s%s" % (x.where, x.detail, x.before, x.after or "—",
                                                   "" if x.fixable else " *(solo aviso)*"))
        if len(found) > 80:
            lines.append("- … y %d más (ver JSON)" % (len(found) - 80))
        lines.append("")
    md = OUT_DIR / ("%s_report.md" % stamp)
    md.write_text("\n".join(lines), encoding="utf-8")
    (OUT_DIR / ("%s_report.json" % stamp)).write_text(json.dumps(
        {n: [x.as_dict() for x in f] for n, f in results.items()}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return md


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--owner", help="sólo este dueño (parte del nombre en books.json)")
    ap.add_argument("--apply", action="store_true",
                    help="arreglar (backup antes); sin --owner sólo los \"apply\": true")
    a = ap.parse_args(argv)
    cfg = json.loads(BOOKS_FILE.read_text(encoding="utf-8"))
    today = dt.date.today()
    tpl = _load_retry("TEMPLATE", cfg["template"], today)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    results, failed = {}, []
    for b in cfg["books"]:
        name = b["name"]
        if a.owner and a.owner.lower() not in name.lower():
            continue
        t = _load_retry(name, b["sheet_id"], today)
        if not t:
            print("== %s: sin tab PNL %d" % (name, today.year))
            results[name] = [P.Finding("row_missing", "—", "no tiene tab 'PNL %d' a la vista" % today.year)]
            continue
        found = P.audit(t["values"], t["formulas"], tpl.get("values"))
        n_fix = sum(1 for x in found if x.fixable)
        print("== %s · %s: %d hallazgos (%d arreglables)" % (name, t["title"], len(found), n_fix))
        on = a.apply and (bool(a.owner) or b.get("apply", False))
        if on and n_fix > MAX_FIXES:
            print("  NO se escribe: %d arreglos es demasiado (tope %d)" % (n_fix, MAX_FIXES))
        elif on and n_fix:
            print("  backup:", backup(name, t, stamp))
            try:
                print("  escritos: %d" % len(apply(t, found)))
            except Exception as e:  # noqa: BLE001 -- e.g. no edit access: the rest still run
                print("  NO se pudo escribir (%s: %s)" % (type(e).__name__, str(e)[:120]))
                failed.append(name)
        results[name] = found
    print("reporte:", report(results, stamp, a.apply))
    if failed:
        print("sin poder escribir en: %s" % ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
