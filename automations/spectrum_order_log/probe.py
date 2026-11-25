"""READ-ONLY: find the new Charter (Spectrum) workbook on Tableau and show what
its order-log-ish views carry, so the Spectrum Order Log can be built on it.

Maud 2026-11-24: "would you be able to create an order log for Spectrum
please? There is a Charter workbook on Tableau now!" Nobody here knows the
workbook's url segment, view names or columns yet — this answers all three.

What it does, on the sci site via the vizportal API (same calls as
recruiting_report.probe_b2b_views — page scraping misses virtualized lists):
  * every workbook whose name/repositoryUrl says charter or spectrum -> 'WB:'
  * every view of each -> 'VIEW:'
  * for each view, the first lines of its .csv export -> 'COLS:' (header),
    'ROW:' (first 3 data rows), 'ROWS:' (row count). Views that won't export
    print 'CSVERR:'.

Downloads only into memory, writes no Sheet, posts nothing. Prefixed lines so
`lucy logtail <log> COLS: 20` can page past the result cell.

Runs on a Lucy (Tableau SSO via ownerville). `lucy rerun spectrum_order_log_probe`

2026-11-25: default run reads the order table out of the page's
bootstrapSession reply (TS-* lines). `--export` = the EXPORT OPTIONS check
(it does nothing), `--all` = the 11/24 sweep.
"""
from __future__ import annotations

import csv
import io
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — py3.9 / non-tty
    pass

from automations.recruiting_report.probe_b2b_views import (
    BASE, _call, _seg, _views)

WORDS = ("charter", "spectrum")

CSV_JS = """async (url) => {
    const r = await fetch(url, {credentials: 'include'});
    const t = await r.text();
    const lines = t.split('\\n');
    return [r.status, lines.slice(0, 4).join('\\n'), lines.length];
}"""


def _csv_peek(page, repo: str, seg: str) -> None:
    url = "{}/t/sci/views/{}/{}.csv".format(BASE, repo, seg.split("/")[-1])
    try:
        st, head, n = page.evaluate(CSV_JS, url)
    except Exception as e:  # noqa: BLE001
        print(f"CSVERR: {seg}: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return
    if st != 200:
        print(f"CSVERR: {seg}: HTTP {st}", flush=True)
        return
    rows = list(csv.reader(io.StringIO(head.lstrip("﻿"))))
    if not rows:
        print(f"CSVERR: {seg}: empty export", flush=True)
        return
    print(f"COLS: {seg} | " + " | ".join(rows[0]), flush=True)
    for r in rows[1:4]:
        print(f"ROW: {seg} | " + " | ".join(r)[:400], flush=True)
    print(f"ROWS: {seg} ~{max(n - 2, 0)}", flush=True)


def main() -> int:
    from automations.shared.tableau_patchright import tableau_session

    with tableau_session(verbose=True) as page:
        page.goto(BASE + "/#/site/sci/workbooks", wait_until="domcontentloaded")
        page.wait_for_timeout(12_000)
        st, data = _call(page, "getWorkbooks", {
            "filter": {"operator": "and", "clauses": []},
            "order": [{"field": "name", "ascending": True}],
            "page": {"startIndex": 0, "maxItems": 1000}})
        wbs = (data.get("result") or {}).get("workbooks") or []
        print(f"site has {len(wbs)} workbook(s) (HTTP {st})", flush=True)
        if not wbs:
            print("!! getWorkbooks returned nothing — session not logged in?")
            return 1
        hits = [w for w in wbs if any(
            k in (str(w.get("name")) + " " + str(w.get("repositoryUrl"))).casefold()
            for k in WORDS)]
        if not hits:
            print("GONE: no workbook mentions charter/spectrum. All names:")
            for w in wbs:
                print(f"WB-ALL: {w.get('name')} repo={w.get('repositoryUrl')}",
                      flush=True)
            return 1
        for wb in hits:
            repo = wb.get("repositoryUrl") or ""
            print("\n" + "=" * 64, flush=True)
            print(f"WB: {wb.get('name')} repo={repo} id={wb.get('id')} "
                  f"project={wb.get('projectName')} "
                  f"updated={wb.get('updatedAt')}", flush=True)
            st, views = _views(page, wb["id"])
            print(f"{len(views)} view(s) (HTTP {st})", flush=True)
            for v in views:
                seg = _seg(v)
                print(f"VIEW: {v.get('name')} -> {repo}/{seg}", flush=True)
            for v in views:
                # The record's url segment comes back EMPTY on this site
                # (2026-11-24); the segment is the name with spaces and
                # punctuation dropped ('Order Log' -> 'OrderLog').
                seg = _seg(v) or "".join(
                    ch for ch in str(v.get("name") or "") if ch.isalnum())
                if seg:
                    _csv_peek(page, repo, seg)
        _viewdata_peek(page)
    return 0


def _viewdata_peek(page) -> None:
    """Crosstab offers ONLY 'Last Update' on this dashboard (2026-11-24), but
    the order table is there (Eve's screenshot: one row per line, Raf's rows,
    Sale Week 11/21/2026). So read it through Download -> Data -> View Data,
    clicking inside the table first so Data is enabled. 'VDCOLS:' header,
    'VDROW:' first rows, 'VDROWS:' count."""
    from automations.recruiting_report.opt_phase import scrape_view_data
    print("=" * 64, flush=True)
    for xy in ((0.55, 0.30), (0.40, 0.45)):
        try:
            fields, recs = scrape_view_data(ORDERLOG_URL, verbose=True,
                                            activate_xy=xy, page=page)
        except Exception as e:  # noqa: BLE001
            print(f"VDERR: {xy}: {type(e).__name__}: {str(e)[:200]}", flush=True)
            continue
        print(f"VDCOLS: {xy} | " + " | ".join(fields), flush=True)
        for r in recs[:3]:
            print(f"VDROW: " + " | ".join(str(c) for c in r)[:600], flush=True)
        print(f"VDROWS: {len(recs)}", flush=True)
        if len(fields) > 3:
            return


ORDERLOG_URL = BASE + "/#/site/sci/views/CharterD2DSalesMetrics/OrderLog"


def _crosstab_peek(page) -> None:
    """The OrderLog .csv only returns the dashboard's first sheet ('Last
    Update', 2026-11-24). The order table is another worksheet inside the
    dashboard: list the Crosstab dialog's sheets ('XSHEET:') and pull each
    one ('XCOLS:' header, 'XROW:' first rows, 'XROWS:' count)."""
    import tempfile
    from pathlib import Path
    from automations.recruiting_report.opt_phase import (
        drive_crosstab_dialog, list_crosstab_sheets)
    print("=" * 64, flush=True)
    try:
        sheets = list_crosstab_sheets(ORDERLOG_URL, page=page, verbose=True)
    except Exception as e:  # noqa: BLE001
        print(f"XERR: list sheets: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return
    for s in sheets:
        print(f"XSHEET: {s}", flush=True)
    tmp = Path(tempfile.mkdtemp(prefix="spectrum_probe_"))
    for i, s in enumerate(sheets):
        if s.strip().lower() == "last update":
            continue
        out = tmp / f"sheet{i}.csv"
        try:
            drive_crosstab_dialog(page, ORDERLOG_URL, s, out, verbose=True)
            raw = out.read_bytes()
        except Exception as e:  # noqa: BLE001
            print(f"XERR: {s}: {type(e).__name__}: {str(e)[:200]}", flush=True)
            continue
        # Tableau crosstab CSVs are UTF-16 with a BOM and tab-separated.
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            text = raw.decode("utf-16")
        else:
            text = raw.decode("utf-8-sig", errors="replace")
        first = text.splitlines()[0] if text else ""
        delim = "\t" if "\t" in first else ","
        rows = list(csv.reader(io.StringIO(text), delimiter=delim))
        if not rows:
            print(f"XERR: {s}: empty", flush=True)
            continue
        print(f"XCOLS: {s} | " + " | ".join(rows[0]), flush=True)
        for r in rows[1:4]:
            print(f"XROW: {s} | " + " | ".join(r)[:500], flush=True)
        print(f"XROWS: {s} {len(rows) - 1}", flush=True)


EXPORT_JS = """() => {
    const out = [];
    const seen = new Set();
    for (const el of document.querySelectorAll('body *')) {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) continue;
        const own = Array.from(el.childNodes)
            .filter(n => n.nodeType === 3).map(n => n.textContent.trim())
            .join(' ').trim();
        if (!own || own.length > 120 || seen.has(own)) continue;
        seen.add(own);
        out.push(own + ' @' + Math.round(r.x) + ',' + Math.round(r.y));
    }
    return out;
}"""


def _dump_text(page, tag: str) -> set:
    """Every visible text bit in every frame -> '<tag>: <text> @x,y'."""
    got = set()
    for f in page.frames:
        try:
            bits = f.evaluate(EXPORT_JS)
        except Exception:  # noqa: BLE001
            continue
        for b in bits:
            got.add(b.rsplit(" @", 1)[0])
            print(f"{tag}: {b}", flush=True)
    return got


def export_options_peek(page) -> None:
    """Order Log dashboard has an 'EXPORT OPTIONS' button under the blue left
    panel (Eve 2026-11-24). Crosstab/View Data can't reach the order table, so
    press it and log what it opens: 'EXP-URL:' url after, 'EXP-NEW:' text that
    appeared, 'EXP-POPUP:'/'EXP-DL:' new window or download. Then re-list the
    Crosstab sheets and peek the .csv of wherever we landed."""
    from automations.recruiting_report.opt_phase import _wait_viz_loaded
    print("=" * 64, flush=True)
    page.goto(ORDERLOG_URL, wait_until="domcontentloaded")
    viz = page.frame_locator('iframe[title="Data Visualization"]')
    viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]'
                ).wait_for(state="visible", timeout=120_000)
    _wait_viz_loaded(page)
    page.wait_for_timeout(10_000)
    before = _dump_text(page, "EXP-BEFORE")
    btn = viz.get_by_text("EXPORT OPTIONS", exact=False)
    n = btn.count()
    print(f"EXP-BTN: {n} match(es)", flush=True)
    if not n:
        btn = viz.get_by_text("Export", exact=False)
        n = btn.count()
        print(f"EXP-BTN: fallback 'Export' {n} match(es)", flush=True)
        if not n:
            return
    popups, downloads = [], []
    page.context.on("page", lambda p: popups.append(p))
    page.on("download", lambda d: downloads.append(d))
    try:
        btn.first.click(timeout=15_000)
    except Exception as e:  # noqa: BLE001
        print(f"EXP-ERR: click: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return
    page.wait_for_timeout(5_000)
    _wait_viz_loaded(page)
    page.wait_for_timeout(8_000)
    print(f"EXP-URL: {page.url}", flush=True)
    for p in popups:
        print(f"EXP-POPUP: {p.url}", flush=True)
    for d in downloads:
        print(f"EXP-DL: {d.suggested_filename}", flush=True)
    after = set()
    for f in page.frames:
        try:
            after.update(b.rsplit(" @", 1)[0] for b in f.evaluate(EXPORT_JS))
        except Exception:  # noqa: BLE001
            pass
    for t in sorted(after - before):
        print(f"EXP-NEW: {t}", flush=True)
    for t in sorted(before - after):
        print(f"EXP-GONE: {t}", flush=True)
    # Wherever we are now, what does Crosstab offer, and does .csv work?
    seg = page.url.split("/views/", 1)[-1].split("?")[0] if "/views/" in page.url else ""
    if seg and seg != "CharterD2DSalesMetrics/OrderLog":
        repo, _, view = seg.partition("/")
        _csv_peek(page, repo, view)
        try:
            from automations.recruiting_report.opt_phase import list_crosstab_sheets
            for s in list_crosstab_sheets(page.url, page=page, verbose=True):
                print(f"EXP-XSHEET: {s}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"EXP-ERR: crosstab: {type(e).__name__}: {str(e)[:200]}", flush=True)


def export_main() -> int:
    from automations.shared.tableau_patchright import tableau_session
    with tableau_session(verbose=True) as page:
        export_options_peek(page)
    return 0


# ---------------------------------------------------------------------------
# 2026-11-25: EXPORT OPTIONS does nothing (no menu, no download) and Tableau
# is SCI's — nobody here can turn downloads on. But the table is drawn by the
# browser, so its data arrives in the page's own bootstrapSession reply
# (dataDictionary + per-worksheet column indices). Read it from there: full
# values (the screen cuts long ones to '1000788415..') and every row, not just
# the ones on screen. 'TS-SHEET:' worksheets, 'TS-COLS:' header, 'TS-ROW:'
# rows, 'TS-ROWS:' count.

def _split_bootstrap(text: str):
    """'<len>;{json}<len>;{json}' -> list of parsed json objects."""
    import json
    out, i = [], 0
    while i < len(text):
        j = text.find(";", i)
        if j < 0:
            break
        try:
            n = int(text[i:j])
        except ValueError:
            break
        out.append(json.loads(text[j + 1:j + 1 + n]))
        i = j + 1 + n
    return out


def _tables_from_bootstrap(info: dict) -> dict:
    """{worksheet: (fields, rows)} out of a bootstrapSession secondaryInfo."""
    pmm = info["presModelMap"]
    segs = (pmm["dataDictionary"]["presModelHolder"]
            ["genDataDictionaryPresModel"]["dataSegments"])
    full: dict = {}
    for key in sorted(segs, key=lambda k: int(k)):
        for col in segs[key]["dataColumns"]:
            full.setdefault(col["dataType"], []).extend(col["dataValues"])
    sheets = (pmm["vizData"]["presModelHolder"]
              ["genPresModelMapPresModel"]["presModelMap"])
    out = {}
    for name, holder in sheets.items():
        try:
            cols = (holder["presModelHolder"]["genVizDataPresModel"]
                    ["paneColumnsData"])
        except (KeyError, TypeError):
            continue
        fields, columns = [], []
        for c in cols.get("vizDataColumns") or []:
            cap = c.get("fieldCaption")
            if not cap or not c.get("paneIndices"):
                continue
            pane = cols["paneColumnsList"][c["paneIndices"][0]]
            vp = pane["vizPaneColumns"][c["columnIndices"][0]]
            dt = c.get("dataType") or "cstring"
            idx = vp.get("aliasIndices") or vp.get("valueIndices") or []
            vals = []
            for k in idx:
                try:
                    vals.append(full[dt][k] if k >= 0 else full["cstring"][-k - 1])
                except (KeyError, IndexError):
                    vals.append("")
            fields.append(cap)
            columns.append(vals)
        if not fields:
            continue
        n = max(len(v) for v in columns)
        rows = [[(v[i] if i < len(v) else "") for v in columns] for i in range(n)]
        out[name] = (fields, rows)
    return out


def bootstrap_peek(page) -> int:
    bodies = []

    def _grab(resp):
        if "bootstrapSession" in resp.url:
            try:
                bodies.append(resp.text())
            except Exception as e:  # noqa: BLE001
                print(f"TS-ERR: body: {type(e).__name__}: {e}", flush=True)

    page.context.on("response", _grab)
    page.goto(ORDERLOG_URL, wait_until="domcontentloaded")
    viz = page.frame_locator('iframe[title="Data Visualization"]')
    viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]'
                ).wait_for(state="visible", timeout=120_000)
    page.wait_for_timeout(15_000)
    print(f"TS-BOOT: {len(bodies)} bootstrap reply(s), sizes "
          f"{[len(b) for b in bodies]}", flush=True)
    found = 0
    for b in bodies:
        try:
            parts = _split_bootstrap(b)
        except Exception as e:  # noqa: BLE001
            print(f"TS-ERR: split: {type(e).__name__}: {str(e)[:150]}", flush=True)
            continue
        for part in parts[1:]:
            try:
                tables = _tables_from_bootstrap(part["secondaryInfo"])
            except Exception as e:  # noqa: BLE001
                print(f"TS-ERR: parse: {type(e).__name__}: {str(e)[:150]} "
                      f"keys={list(part)[:8]}", flush=True)
                continue
            for name, (fields, rows) in tables.items():
                found += 1
                print(f"TS-SHEET: {name} ({len(fields)} cols, {len(rows)} rows)",
                      flush=True)
                if len(fields) < 5:
                    continue
                print(f"TS-COLS: {name} | " + " | ".join(fields), flush=True)
                for r in rows[:40]:
                    print("TS-ROW: " + " | ".join(str(c) for c in r)[:900],
                          flush=True)
                print(f"TS-ROWS: {name} {len(rows)}", flush=True)
    if not found:
        print("TS-NONE: no worksheet data in the bootstrap reply "
              "(server-rendered table?)", flush=True)
    return 0 if found else 1


def bootstrap_main() -> int:
    from automations.shared.tableau_patchright import tableau_session
    with tableau_session(verbose=True) as page:
        return bootstrap_peek(page)


if __name__ == "__main__":
    # Default = read the order table out of the page's bootstrap reply.
    # --export = 11/25 EXPORT OPTIONS check; --all = 11/24 sweep.
    if "--all" in sys.argv:
        sys.exit(main())
    sys.exit(export_main() if "--export" in sys.argv else bootstrap_main())
