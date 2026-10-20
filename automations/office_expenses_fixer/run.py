"""Lucy Office Expenses Fixer -- audit the 'Office Expenses' tab of every
owner's All-in-One, fix what is safe, write down what it did. What is
checked: checks.py.

Rafael's list of main spreadsheets (Slack 2026-10-10), #6 "Office Expenses";
Eve 2026-10-20: "luego seguí con office expenses" -- each office its own way:
the rows under TOTAL are compared with the OTHER offices (and the template)
that have the same row, never with one fixed layout.

PREVIEW FIRST (CLAUDE.md): a book is written only with "apply": true in
books.json, or when named with --owner together with --apply.

SAFETY. A backup of the tab's values + formulas goes to
output/office_expenses_fixer/ before it is written; one batch per tab; a
hover note on every touched cell. More than MAX_FIXES on one tab means it was
read wrong -- nothing is written there.

    python -m automations.office_expenses_fixer.run                    # audit every book (read-only)
    python -m automations.office_expenses_fixer.run --owner Cody --apply
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

from automations.office_expenses_fixer import checks as C

BOOKS_FILE = Path(__file__).with_name("books.json")
TAB = re.compile(r"^\s*offices?\s+expenses\s*$", re.I)     # Isaiah: 'Offices Expenses'
MAX_FIXES = 40
REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "office_expenses_fixer"


def _book(sheet_id: str):
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(sheet_id)


def load(sh) -> dict:
    """The visible Office Expenses tab, three ways: formulas, what it shows,
    and raw (numbers as numbers, so an amount typed as text stands out)."""
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId,title,hidden))"})
    tab = next((s["properties"] for s in meta["sheets"]
                if TAB.match(s["properties"]["title"]) and not s["properties"].get("hidden")), None)
    if not tab:
        return {}
    title = tab["title"]
    rng = "'%s'" % title
    def get(render):
        return sh.values_batch_get([rng], params={"valueRenderOption": render}
                                   )["valueRanges"][0].get("values", [])
    formulas, values, raw = get("FORMULA"), get("FORMATTED_VALUE"), get("UNFORMATTED_VALUE")
    grid = sh.fetch_sheet_metadata({"includeGridData": True, "ranges": [rng],
                                    "fields": "sheets(data(rowData(values(note))))"})
    rows = grid["sheets"][0]["data"][0].get("rowData", [])
    notes = [[(v or {}).get("note", "") for v in rd.get("values", [])] for rd in rows]
    return {"title": title, "sheet_id": tab["sheetId"], "ws": sh.worksheet(title),
            "formulas": formulas, "values": values, "raw": raw, "notes": notes}


def _read_all(books, template):
    """{name: loaded tab} -- the template too, as one more office to compare."""
    out = {}
    for name, sid in [("TEMPLATE", template)] + [(b["name"], b["sheet_id"]) for b in books]:
        for attempt in (1, 2):
            try:
                out[name] = load(_book(sid))
                break
            except Exception as e:  # noqa: BLE001 -- one book never stops the rest
                if attempt == 1 and "429" in str(e):
                    print("  cuota de lectura de Google -- espero 70s y repito")
                    time.sleep(70)
                    continue
                print("== %s: NO se pudo leer (%s)" % (name, type(e).__name__))
    return out


def audit(name: str, t: dict, peers: dict, totals: dict, inherited=frozenset()) -> list:
    f, v, raw = t["formulas"], t["values"], t["raw"]
    found = (C.check_sums(f, raw) + C.check_derived(f, v, peers)
             + C.check_total_typed_over(f, list(peers)))
    fixed = {x.where for x in found if x.fixable}
    found += [e for e in C.check_errors(v, f, inherited) if e.where not in fixed]
    mine = totals.get(name)
    if mine and any(mine):
        twins = [n for n, tt in totals.items() if n != name and tt == mine]
        if "TEMPLATE" in twins:
            found.append(C.Finding("template_amounts", "TOTAL", C.KIND_LABEL["template_amounts"],
                                   before=str(mine)))
        elif twins:
            found.append(C.Finding("same_as_other", "TOTAL", "%s: %s" % (
                C.KIND_LABEL["same_as_other"], ", ".join(twins)), before=str(mine)))
    return found


def backup(name: str, t: dict, stamp: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / ("backup_%s_%s.json" % (stamp, re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")))
    p.write_text(json.dumps({"title": t["title"], "values": t["values"], "formulas": t["formulas"],
                             "raw": t["raw"]}, ensure_ascii=False), encoding="utf-8")
    return p


def apply(t: dict, found: list) -> list:
    todo = [x for x in found if x.fixable]
    if todo:
        t["ws"].batch_update([{"range": x.where, "values": [[x.value]]} for x in todo],
                             value_input_option="USER_ENTERED")
        notes = C.note_requests(todo, t["sheet_id"], t["notes"], dt.date.today().strftime("%m/%d"))
        if notes:
            t["ws"].spreadsheet.batch_update({"requests": notes})
    return todo


def report(results: dict, stamp: str, applied: bool) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# Lucy Office Expenses Fixer — %s" % stamp, "",
             "Modo: **%s**" % ("ARREGLÓ" if applied else "solo mirar"), ""]
    for name, found in results.items():
        lines += ["## %s — %d hallazgos (%d se arreglan)"
                  % (name, len(found), sum(1 for x in found if x.fixable)), ""]
        for x in found:
            lines.append("- `%s` %s — %s → %s%s" % (x.where, x.detail, x.before, x.after or "—",
                                                   "" if x.fixable else " *(solo aviso)*"))
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
    books = cfg["books"]
    # every book is read even with --owner: the others are what it is compared with
    tabs = _read_all(books, cfg["template"])
    tabs = {n: t for n, t in tabs.items() if t}
    peers = C.peer_formulas([C.shape(t["formulas"]) for t in tabs.values()])
    totals = {n: C.totals(t["formulas"], t["raw"]) for n, t in tabs.items()}
    tpl = tabs.get("TEMPLATE")
    inherited = C.template_errors(tpl["values"], tpl["formulas"]) if tpl else frozenset()
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    results = {}
    for b in books:
        name = b["name"]
        if a.owner and a.owner.lower() not in name.lower():
            continue
        t = tabs.get(name)
        if not t:
            print("== %s: sin tab Office Expenses" % name)
            continue
        found = audit(name, t, peers, totals, inherited)
        n_fix = sum(1 for x in found if x.fixable)
        print("== %s · %s: %d hallazgos (%d arreglables)" % (name, t["title"], len(found), n_fix))
        on = a.apply and (bool(a.owner) or b.get("apply", False))
        if on and n_fix > MAX_FIXES:
            print("  NO se escribe: %d arreglos es demasiado (tope %d)" % (n_fix, MAX_FIXES))
        elif on and n_fix:
            print("  backup:", backup(name, t, stamp))
            print("  escritos: %d" % len(apply(t, found)))
        results[name] = found
    print("reporte:", report(results, stamp, a.apply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
