"""SaraPlus status probe — WHERE do activation/order statuses live? READ-ONLY.

Carlos (2026-09-10) wants the Activation Report Overview rebuilt on SaraPlus
data because Tableau lags days behind while SaraPlus updates almost live. The
open question is whether SaraPlus exposes an activation/posted status at all:
on the Sales Order History grid, on the row's 'View Customer' page, or on a
sibling Detail Reports tab (Pending Orders?). This probe goes and looks.

It changes NOTHING: SaraPlus is only read, and the current activation report
is not touched. The only writes are diagnostic tabs on the control sheet:

    'SP Status Diag'  — every grid header, candidate status columns and their
                        value per order, pager state, the first row's links,
                        and the View Customer page's text.
    'SP Grid Shot' / 'SP Cust Shot' — full-page screenshots, base64-chunked
                        (decode on the mini, house pattern).

Login rides rc_contact_sync's machinery unchanged: CARLOS's SaraPlus creds +
the already-verified .saraplus_b2b_profile on Lucy 2, emailed-passcode flow
included. Default day is 7 days back so Tableau's order log (which HAS caught
up by then) can be compared against what SaraPlus shows for the same orders.

    lucy rerun sp_status_probe                    # 7 days ago, 6 sample rows
    lucy rerun sp_status_probe -- 2026-09-03      # a specific day
    lucy rerun sp_status_probe -- --rows 10
    lucy rerun sp_status_probe -- --tab-arg 3:1   # open ANOTHER Detail
        # Reports child tab (e.g. Pending Orders) generically and dump
        # whatever grids it renders — no new deploy needed to explore.

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.rc_contact_sync import config as C
from automations.rc_contact_sync import sara

CONTROL_SHEET = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
DIAG_TAB = "SP Status Diag"
SHOT_GRID = "SP Grid Shot"
SHOT_CUST = "SP Cust Shot"

# A header is a status CANDIDATE when it smells like one. Deliberately broad —
# the whole point is to see what SaraPlus calls it, not to guess right first.
STATUS_RE = re.compile(
    r"status|activ|instal|disposition|complet|post|cancel|disconnect|dtr|"
    r"stage|state|pend", re.I)

# Row-identity columns repeated beside every candidate value so the mini can
# join against the Tableau order log (which has Customer Name + Phone but no
# SaraPlus Order ID).
ID_COLS = ("Order ID", "Order Date", "User Name", "Business Name",
           "Customer Name", "Phone")


def _upload_lines(lines: List[str]) -> None:
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(CONTROL_SHEET)
    try:
        t = sh.worksheet(DIAG_TAB)
    except Exception:  # noqa: BLE001
        t = sh.add_worksheet(title=DIAG_TAB, rows=1000, cols=1)
    t.clear()
    t.update([[ln[:4900]] for ln in lines][:950], "A1")


def _upload_shot(png_bytes: bytes, tab: str, log=print) -> None:
    try:
        from automations.vantura_churn.cdp_pull import _upload_png
        _upload_png(png_bytes, tab=tab)
        log("  screenshot -> %r (%s bytes)" % (tab, "{:,}".format(len(png_bytes))))
    except Exception as e:  # noqa: BLE001 — a lost shot must not sink the probe
        log("  (screenshot upload to %r failed: %s: %s)"
            % (tab, type(e).__name__, str(e)[:120]))


def _raw_grid(page) -> Dict:
    """Headers + every cell of every row, UNfiltered (sara.read_grid keeps
    only the six known columns; this probe wants all ~146)."""
    return page.evaluate(
        """(ids) => {
             const hdr = document.getElementById(ids.header);
             const data = document.getElementById(ids.data);
             if (!hdr || !data) return {headers: [], rows: [],
                 missing: (!hdr ? 'header ' : '') + (!data ? 'data' : '')};
             const headRow = hdr.querySelector('tr');
             const headers = headRow
               ? [...headRow.querySelectorAll('th,td')]
                   .map(c => (c.innerText || '').replace(/[ \\t\\n\\r]+/g, ' ').trim())
               : [];
             const rows = [...data.querySelectorAll('tbody > tr')]
               .map(r => [...r.querySelectorAll('td')]
                 .map(c => (c.innerText || '').replace(/[ \\t\\n\\r]+/g, ' ').trim()));
             return {headers: headers, rows: rows, missing: ''};
           }""", {"header": C.GRID_HEADER, "data": C.GRID_DATA})


def _dump_tab_strip(page, log) -> None:
    """Every tab label in the Reporting Hub's RadTabStrip, with nesting, so we
    learn what sits beside Sales Order History (Pending Orders, WSC, ...)."""
    tabs = page.evaluate(
        """() => {
             const strip = document.getElementById('ctl00_MainContent_rtsReportOptions');
             if (!strip) return null;
             const out = [];
             strip.querySelectorAll('ul').forEach(ul => {
               let depth = 0, e = ul;
               while (e && e !== strip) { if (e.tagName === 'UL') depth++; e = e.parentElement; }
               [...ul.children].forEach((li, i) => {
                 const t = (li.innerText || '').split('\\n')[0].trim();
                 if (t) out.push({depth: depth, index: i, text: t});
               });
             });
             return out;
           }""")
    if not tabs:
        log("tab strip: NOT FOUND (ctl00_MainContent_rtsReportOptions)")
        return
    log("-- Reporting Hub tab strip (depth:index text) --")
    for t in tabs:
        log("   %s%d: %s" % ("  " * (t["depth"] - 1), t["index"], t["text"]))


def _generic_tab_dump(page, arg_index: str, log) -> None:
    """Open an arbitrary Detail Reports child by hierarchical index (e.g.
    '3:1') via the same postback trick, then dump whatever grids rendered."""
    posted = page.evaluate(
        """(cfg) => {
             const t = document.getElementsByName('__EVENTTARGET')[0];
             const a = document.getElementsByName('__EVENTARGUMENT')[0];
             if (!t || !a) return 'no __EVENTTARGET/__EVENTARGUMENT';
             t.value = cfg.target;
             a.value = JSON.stringify({type: 0, index: cfg.index});
             const f = document.getElementById(cfg.form) || document.forms[0];
             if (!f) return 'no form';
             f.submit();
             return 'posted';
           }""",
        {"target": C.TAB_POSTBACK_TARGET, "index": arg_index, "form": C.FORM_ID})
    log("postback index %s: %s" % (arg_index, posted))
    try:
        page.wait_for_load_state("networkidle", timeout=C.NAV_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(2500)
    log(sara.page_state(page))
    panels = page.evaluate(
        """() => {
             const out = {grids: [], controls: []};
             document.querySelectorAll('table[id$="_Header"]').forEach(t => {
               const row = t.querySelector('tr');
               out.grids.push({id: t.id, headers: row
                 ? [...row.querySelectorAll('th,td')]
                     .map(c => (c.innerText || '').replace(/\\s+/g, ' ').trim())
                 : []});
             });
             document.querySelectorAll('input[id],select[id]').forEach(e => {
               if (e.type === 'hidden') return;
               if (e.offsetParent === null) return;
               out.controls.push(e.tagName + ':' + e.type + ' #' + e.id);
             });
             return out;
           }""")
    for g in panels["grids"]:
        log("grid %s:" % g["id"])
        for i, h in enumerate(g["headers"]):
            if h:
                log("   [%d] %s" % (i, h))
    log("-- visible controls --")
    for ctl in panels["controls"][:60]:
        log("   " + ctl)


def _dump_first_row_links(page, log) -> List[Dict]:
    """Every anchor/button in the FIRST data row — which one is View Customer?"""
    links = page.evaluate(
        """(gid) => {
             const data = document.getElementById(gid);
             if (!data) return [];
             const row = data.querySelector('tbody > tr');
             if (!row) return [];
             return [...row.querySelectorAll('a,input[type=button],input[type=submit],button')]
               .map(e => ({tag: e.tagName, id: e.id || '',
                           text: (e.innerText || e.value || '').trim().slice(0, 40),
                           href: (e.getAttribute('href') || '').slice(0, 120),
                           onclick: (e.getAttribute('onclick') || '').slice(0, 120)}));
           }""", C.GRID_DATA)
    log("-- first data row's clickables --")
    for l in links:
        log("   %s id=%r text=%r href=%r onclick=%r"
            % (l["tag"], l["id"], l["text"], l["href"], l["onclick"]))
    return links


def _dump_customer_view(ctx, page, links: List[Dict], log) -> Optional[bytes]:
    """Click the first row's View-ish link and dump whatever appears — a new
    tab, an in-page RadWindow iframe, or a full navigation. Returns a PNG of
    it, or None if there was nothing to click."""
    target = next((l for l in links
                   if re.search(r"view", (l["text"] or "") + " " + (l["id"] or ""),
                                re.I)), None)
    if target is None and links:
        target = links[0]
        log("no link matches /view/i — clicking the first one instead")
    if target is None:
        log("the first row has nothing clickable — no customer view to open")
        return None

    pages_before = len(ctx.pages)
    log("clicking %r (id=%r) ..." % (target["text"], target["id"]))
    try:
        if target["id"]:
            page.click("#%s" % target["id"], timeout=20_000)
        else:
            page.evaluate(
                """(gid) => {
                     const row = document.getElementById(gid).querySelector('tbody > tr');
                     const e = [...row.querySelectorAll('a,input,button')]
                       .find(x => /view/i.test((x.innerText || x.value || '') + x.id));
                     (e || row.querySelector('a,input,button')).click();
                   }""", C.GRID_DATA)
    except Exception as e:  # noqa: BLE001
        log("click failed: %s: %s" % (type(e).__name__, str(e)[:160]))
        return None
    try:
        page.wait_for_load_state("networkidle", timeout=C.NAV_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(2500)

    view = page
    if len(ctx.pages) > pages_before:            # it opened a new tab
        view = ctx.pages[-1]
        log("a NEW TAB opened: %s" % view.url)
        try:
            view.wait_for_load_state("networkidle", timeout=C.NAV_TIMEOUT_MS)
        except Exception:  # noqa: BLE001
            pass
    else:
        log("after click: %s" % sara.page_state(page))

    for fr in view.frames:
        if fr == view.main_frame:
            continue
        try:
            txt = fr.evaluate("() => (document.body.innerText || '')") or ""
        except Exception:  # noqa: BLE001
            continue
        if txt.strip():
            log("-- iframe %s --" % (fr.url or "(no url)")[:160])
            for ln in txt.splitlines():
                if ln.strip():
                    log("   | " + ln.strip()[:180])

    log("-- customer view text (main frame) --")
    try:
        txt = view.evaluate("() => (document.body.innerText || '')") or ""
    except Exception:  # noqa: BLE001
        txt = ""
    kept = 0
    for ln in txt.splitlines():
        if ln.strip():
            log("   | " + ln.strip()[:180])
            kept += 1
            if kept >= 220:
                log("   | ... (text truncated at 220 lines)")
                break
    try:
        return view.screenshot(full_page=True)
    except Exception as e:  # noqa: BLE001
        log("(screenshot of the view failed: %s)" % type(e).__name__)
        return None


def run(day: dt.date, rows_n: int, tab_arg: str, headless: bool) -> int:
    from patchright.sync_api import sync_playwright

    lines: List[str] = []

    def log(msg):
        print(msg, flush=True)
        lines.append(str(msg))

    log("SaraPlus status probe — day %s, %d sample row(s)%s"
        % (day, rows_n, ("  [tab-arg %s]" % tab_arg) if tab_arg else ""))
    cr = C.creds()
    C.PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    grid_png = cust_png = None
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(C.PROFILE_DIR), headless=headless, args=["--disable-sync"],
            viewport={"width": 1600, "height": 1000})
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            base = sara.login(page, cr["email"], cr["password"], log=log)
            log("logged in as %s: %s" % (cr["email"], base))

            page.goto(base + C.HUB_PATH, wait_until="networkidle",
                      timeout=C.NAV_TIMEOUT_MS)
            _dump_tab_strip(page, log)

            if tab_arg:
                _generic_tab_dump(page, tab_arg, log)
                grid_png = page.screenshot(full_page=True)
            else:
                sara.open_order_history_panel(page, log=log)
                sara._set_telerik_date(page, C.FIELD_START, day)
                sara._set_telerik_date(page, C.FIELD_END, day)
                sara._set_customer_type(page, C.CUSTOMER_TYPE_BOTH, log=log)
                sara._set_telerik_date(page, C.FIELD_START, day)
                sara._set_telerik_date(page, C.FIELD_END, day)
                sara._submit(page, log=log)

                raw = _raw_grid(page)
                if raw.get("missing"):
                    log("GRID MISSING (%s). %s"
                        % (raw["missing"], sara.page_state(page)))
                else:
                    heads = raw["headers"]
                    data_rows = [r for r in raw["rows"] if any(r)]
                    log("grid: %d column(s), %d row(s) on %s"
                        % (len(heads), len(data_rows), day))

                    log("-- ALL column headers --")
                    for i, h in enumerate(heads):
                        mark = "  <== status candidate" if STATUS_RE.search(h or "") else ""
                        log("   [%3d] %s%s" % (i, h or "(blank)", mark))

                    cand = [(i, h) for i, h in enumerate(heads)
                            if STATUS_RE.search(h or "")]
                    idx = {h: i for i, h in enumerate(heads)}

                    log("-- first %d row(s), every non-empty column --" % rows_n)
                    for n, r in enumerate(data_rows[:rows_n]):
                        log("ROW %d:" % (n + 1))
                        for i, h in enumerate(heads):
                            v = r[i] if i < len(r) else ""
                            if v:
                                log("   %s = %s" % (h or ("[col %d]" % i), v))

                    log("-- candidate status values, EVERY row --")
                    for n, r in enumerate(data_rows):
                        ident = " | ".join(
                            "%s" % (r[idx[c]] if c in idx and idx[c] < len(r) else "")
                            for c in ID_COLS if c in idx)
                        vals = "; ".join(
                            "%s=%s" % (h, r[i] if i < len(r) else "")
                            for i, h in cand if (r[i] if i < len(r) else ""))
                        log("   #%02d %s || %s" % (n + 1, ident, vals or "(all blank)"))

                    pager = page.evaluate(
                        """(gid) => {
                             const g = document.getElementById(gid);
                             const p = g && g.parentElement
                               ? g.parentElement.querySelector('[class*="rgPager"],[id*="Pager"]')
                               : null;
                             return p ? (p.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 200) : '';
                           }""", C.GRID_DATA)
                    log("pager: %s" % (pager or "(none — single page)"))

                grid_png = page.screenshot(full_page=True)
                links = _dump_first_row_links(page, log)
                cust_png = _dump_customer_view(ctx, page, links, log)
        except sara.SaraError as e:
            log("SARA ERROR: %s" % e)
        except Exception as e:  # noqa: BLE001
            log("ERROR: %s: %s" % (type(e).__name__, str(e)[:300]))
        finally:
            ctx.close()

    if grid_png:
        _upload_shot(grid_png, SHOT_GRID, log=log)
    if cust_png:
        _upload_shot(cust_png, SHOT_CUST, log=log)
    _upload_lines(lines)
    print("probe output -> sheet tab %r (%d line(s))" % (DIAG_TAB, len(lines)),
          flush=True)
    print("=== done ===", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="sp_status_probe",
        description="READ-ONLY: where do activation statuses live on SaraPlus?")
    ap.add_argument("date", nargs="?", default=None,
                    help="YYYY-MM-DD (default: 7 days ago)")
    ap.add_argument("--rows", type=int, default=6,
                    help="how many rows to dump in full (default 6)")
    ap.add_argument("--tab-arg", default="",
                    help="open THIS Detail Reports tab index instead (e.g. "
                         "'3:1' for the tab after Sales Order History) and "
                         "dump its grids generically")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args(argv)
    day = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
           if args.date else dt.date.today() - dt.timedelta(days=7))
    return run(day, args.rows, args.tab_arg, headless=not args.headed)


if __name__ == "__main__":
    sys.exit(main())
