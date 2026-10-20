"""Lucy Focus Report Fixer -- audit the office tabs of the four Focus Report
books, fix what is safe, write down what it did. What is checked: checks.py.

Rafael's list of main spreadsheets (Slack 2026-10-10), #5 "Focus report
(Huge)"; Eve 2026-10-19: "avanzá con el focus report fixer", then "tiene que
correr en ATT Program, Alphalete Org 1on1s, NDS Program, Carlos 1on1s, con las
particularidades de cada campaña". Each tab is compared with the template
tab of its own book that shares the most row labels with it (B2B, NDS, JE,
BOX, Retail, Frontier, Fiber).

PREVIEW FIRST (CLAUDE.md): --apply writes ONLY the tabs named with --tab
until Eve says roll out; the default preview tab is Marcellus Butler.
--all-tabs is the rollout switch.

SAFETY. A backup of every tab's values + formulas + color rules goes to
output/focus_report_fixer/ before it is written. Only cells the checks
marked fixable are written; one batch per tab. More than MAX_FIXES on one
tab means it was read wrong -- nothing is written there.

    python -m automations.focus_report_fixer.run                       # audit every book (read-only)
    python -m automations.focus_report_fixer.run --book nds            # one book
    python -m automations.focus_report_fixer.run --tab "Marcellus Butler" --apply
    python -m automations.focus_report_fixer.run --all-tabs --apply   # rollout
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

from automations.focus_report_fixer import checks as FC
from automations.sales_board_fixer import checks as K

SHEET_ID = "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE"   # ATT Program - Focus Report
# same ids as financial_report/fill.py
BOOKS = {
    "att": ("ATT Program - Focus Report", SHEET_ID),
    "org": ("Alphalete Org 1on1s - Focus Reports", "1C6BLttOSZhs_dREySac19XkxnMl-Ab_sYacNSl2l6AQ"),
    "nds": ("NDS Program - Focus Report", "1Vu_J7bcSpreIBcsYuAVEQMusL9-RaOSgB65DiKxrYtI"),
    "carlos": ("Carlos 1on1s - Focus Report", "1KLF8diMJ8pwIQWW9IqN7CL288t1l9VGUKxzBcMl8Of4"),
}
TEMPLATE = re.compile(r"template", re.I)
PREVIEW_TAB = "Marcellus Butler"
# copies, test tabs and retired ones ('x - Mario Marroquin - 5G') are not offices
SKIP = re.compile(r"template|^(copy of|sandbox|x\s*-)|test", re.I)
# Raf's own master tab (Saturday weeks, PNL links, 300 rows): read, never written
REPORT_ONLY = {"Raf Hidalgo"}
MAX_FIXES = 400
CF_FIXES = {"cf_broken", "cf_duplicate", "cf_foreign"}
# the other books' old tabs keep rules reaching past their last column: not
# proven dead there (Sheets may clip the range), so only reported
CF_FIXES_OTHER = {"cf_broken", "cf_duplicate"}
REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "focus_report_fixer"


def _book(sheet_id: str = SHEET_ID):
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(sheet_id)


def load_all(sh) -> dict:
    """{title: {...}} for every tab -- two value reads + one metadata read for
    the whole book (88 tabs one by one would run out the read quota)."""
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId,title,hidden,"
                                              "gridProperties),conditionalFormats)"})
    titles = [s["properties"]["title"] for s in meta["sheets"]]
    rng = ["'%s'" % t for t in titles]
    vals = sh.values_batch_get(rng)["valueRanges"]
    forms = sh.values_batch_get(rng, params={"valueRenderOption": "FORMULA"})["valueRanges"]
    out = {}
    for s, v, f in zip(meta["sheets"], vals, forms):
        p = s["properties"]
        out[p["title"]] = {"title": p["title"], "sheet_id": p["sheetId"],
                           "ncols": p["gridProperties"]["columnCount"],
                           "rules": s.get("conditionalFormats", []),
                           "values": v.get("values", []), "formulas": f.get("values", [])}
    return out


def office_tabs(book: dict) -> list:
    return [t for t, x in book.items() if FC.is_focus_tab(x["values"]) and not SKIP.search(t)]


def templates(book: dict) -> list:
    return [x for t, x in book.items() if TEMPLATE.search(t) and FC.is_focus_tab(x["values"])
            and not t.lower().startswith("copy of")]


def pick_template(t: dict, tpls: list) -> dict:
    """The template of the tab's campaign: named by the tab ('Colten Wright -
    NDS' -> 'NDS Template'), else the one sharing the most row labels
    (Carlos' tabs carry no campaign in the name)."""
    camp = re.search(r"-\s*([A-Za-z0-9]+)\s*$", t["title"])
    named = [x for x in tpls if camp
             and camp.group(1).lower() in re.findall(r"[a-z0-9]+", x["title"].lower())]
    have = set(FC.row_keys(t["values"]))
    return max(named or tpls, key=lambda x: len(have & set(FC.row_keys(x["values"]))))


def audit(t: dict, tpl: dict, today: dt.date, filled, cf_fixes=CF_FIXES) -> list:
    found = FC.check_tab(t["title"], t["values"], t["formulas"], tpl["values"],
                         tpl["formulas"], today, filled)
    cf = K.check_conditional(t["title"], t["sheet_id"], t["rules"], t["ncols"])
    for x in cf:
        if x.kind not in cf_fixes:
            x.request = x.value = None          # 'short' / 'fragmented': report only
    return found + cf


def backup(t: dict, stamp: str, key: str = "att") -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    name = t["title"] if key == "att" else "%s_%s" % (key, t["title"])
    p = OUT_DIR / ("backup_%s_%s.json" % (stamp, re.sub(r"[^A-Za-z0-9.]+", "-", name)))
    p.write_text(json.dumps({k: t[k] for k in ("title", "values", "formulas", "rules")},
                            ensure_ascii=False), encoding="utf-8")
    return p


def apply(sh, t: dict, found: list) -> int:
    cells = [x for x in found if x.value is not None]
    if cells:
        sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": [
            {"range": "'%s'!%s" % (t["title"], x.where), "values": [[x.value]]} for x in cells]})
    dels = [x.request for x in found if x.request and "deleteConditionalFormatRule" in x.request]
    if dels:                                   # highest index first (checks.py sorts them)
        sh.batch_update({"requests": dels})
    return len(cells) + len(dels)


def report(results: dict, stamp: str, applied: list) -> Path:
    """One plain-Spanish page for Eve."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# Lucy Focus Report Fixer — %s" % stamp, "",
             "Escribió en: **%s**" % (", ".join(applied) or "nada (solo mirar)"), ""]
    for title, found in results.items():
        if not found:
            continue
        lines += ["## %s — %d hallazgos" % (title, len(found)), ""]
        by = {}
        for x in found:
            by.setdefault(x.kind, []).append(x)
        for kind, xs in sorted(by.items(), key=lambda kv: -len(kv[1])):
            fx = sum(1 for x in xs if x.fixable)
            label = FC.KIND_LABEL.get(kind) or K.KIND_LABEL.get(kind, kind)
            lines.append("### %s — %d (%s)" % (label, len(xs), "se arregla sola" if fx == len(xs)
                                               else "%d se arreglan, %d a mano" % (fx, len(xs) - fx)))
            for x in xs[:15]:
                lines.append("- `%s` — %s — %s → %s" % (x.where, x.detail, x.before[:80] or "(vacía)",
                                                         (x.after or "—")[:80]))
            if len(xs) > 15:
                lines.append("- … y %d más (ver JSON)" % (len(xs) - 15))
            lines.append("")
    md = OUT_DIR / ("%s_report.md" % stamp)
    md.write_text("\n".join(lines), encoding="utf-8")
    (OUT_DIR / ("%s_report.json" % stamp)).write_text(json.dumps(
        {t: [x.as_dict() for x in f] for t, f in results.items()}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return md


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--book", action="append", choices=sorted(BOOKS),
                    help="only this book (repeatable; default all four)")
    ap.add_argument("--tab", action="append", help="tab to check / write (repeatable)")
    ap.add_argument("--all-tabs", action="store_true",
                    help="with --apply: write every office tab (ROLLOUT -- only after Eve's OK)")
    ap.add_argument("--apply", action="store_true", help="write the fixes (backup first)")
    a = ap.parse_args(argv)
    if a.apply and not (a.tab or a.all_tabs):
        print("--apply necesita --tab (preview, default %r) o --all-tabs (rollout)" % PREVIEW_TAB)
        return 2

    today = dt.date.today()
    filled = FC.rows_filled_by_reports()
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    results, applied, seen = {}, [], set()
    for key in a.book or list(BOOKS):
        bname, sid = BOOKS[key]
        sh = _book(sid)
        book = load_all(sh)
        tpls = templates(book)
        titles = [t for t in a.tab if t in book] if a.tab else office_tabs(book)
        seen.update(titles)
        print("== %s: %d tabs, templates %s" % (bname, len(titles), [x["title"] for x in tpls]))
        for title in titles:
            t = book[title]
            tpl = pick_template(t, tpls)
            found = audit(t, tpl, today, filled, CF_FIXES if key == "att" else CF_FIXES_OTHER)
            n_fix = sum(1 for x in found if x.fixable)
            print("%s [%s]: %d hallazgos (%d arreglables)" % (title, tpl["title"], len(found), n_fix))
            label = title if key == "att" else "%s · %s" % (key.upper(), title)
            if a.apply and n_fix and title in REPORT_ONLY:
                print("  solo reporte (%s): no se escribe" % title)
            elif a.apply and n_fix:
                if n_fix > MAX_FIXES:
                    print("  NO se escribe: %d arreglos es demasiado (tope %d)" % (n_fix, MAX_FIXES))
                else:
                    print("  backup:", backup(t, stamp, key))
                    print("  escritos: %d" % apply(sh, t, found))
                    applied.append(label)
            results[label] = found
    missing = [t for t in (a.tab or []) if t not in seen]
    if missing:
        print("no existen: %s" % missing)
    print("reporte:", report(results, stamp, applied))
    return 2 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
