"""Read the Alphalete office's SaraPlus day.

THE SARAPLUS MECHANICS MOVED to `automations/shared/saraplus.py` on 2026-09-10
— every selector, column index, row marker and parser, comments and all. They
are shared now because every SaraPlus is the same, and because
`automations/icd_alerts` runs the same reads on an ICD's own laptop and must
not import this package's config (the workbook id, the Slack channel, the
iMessage groups).

WHAT IS LEFT HERE is the part that is Alphalete's: which credential, which
Chrome profile, and the three-pass day this office needs.

  1. 'AT&T'          -> Internet Sales / Internet Upgrades / AIA / Wireless Lines
  2. 'All'           -> DTV Streaming   (the AT&T-filtered grid always says 0)
  3. 'AT&T Internet' -> Records, i.e. credit checks -- one step BEFORE a
                        confirmed sale. Never written to the board; it only
                        feeds the Slack heads-up.

SOURCE, spelled out: ui.saraplus.com -> DealerPages/Reports/ReportingHub.aspx
-> Order Dashboard, date range set to the ONE day, Service = the filter above,
-> the RadGrid named in shared.saraplus.GRID_* -> the columns in COL_*.

Everything the old module exported is still importable from here, so
`rc_contact_sync` (which borrows `_set_telerik_date`) and `run.py` are
unchanged.

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from automations.alphalete_sales_board import config as C
from automations.shared.saraplus import (  # noqa: F401  (re-exported API)
    AGENT_ROW, AGENT_ROW_INTERNET, COL_ALL, COL_ATT, COL_INTERNET, COL_ROWTYPE,
    COMBO_INPUT, FIELD_END, FIELD_START, GRID_ALL, GRID_ATT, GRID_INTERNET,
    GRID_TIMEOUT_MS, HUB_PATH, NAV_TIMEOUT_MS, SUBMIT, SaraError, _assert_on_hub,
    _int, _run_report, _run_report_once, _select_service, _set_telerik_date,
    agent_rows, merge_dtv, page_state, parse_att, parse_dtv, parse_records,
    strip_office,
)
from automations.shared import saraplus as _sp


def _open_and_login(playwright, *, headless: bool, log=print):
    """(ctx, page, base_url) with a stuck Chrome profile healed automatically.

    A Change Password page from SaraPlus is nearly always THIS PROFILE, not the
    account; login_healing proves which by retrying once on an empty one. Only
    a wall that survives that raises SaraPasswordChangeRequired, and run.py
    turns that one into a Slack ping (2026-09-12)."""
    cr = C.creds()
    return _sp.login_healing(playwright, C.PROFILE_DIR, cr["email"],
                             cr["password"], headless=headless,
                             creds_hint=str(C.CREDS_PATH), log=log)


# --- the one public entry point ---------------------------------------------
def scrape(day: Optional[dt.date] = None, *, headless: bool = True,
           log=print) -> Dict:
    """{'agents': [...], 'records': {...}} for ONE day."""
    from patchright.sync_api import sync_playwright

    day = day or dt.date.today()

    with sync_playwright() as p:
        ctx, page, base = _open_and_login(p, headless=headless, log=log)
        try:
            log("logged in: %s" % base)

            att = parse_att(_run_report(page, base, day, "AT&T", GRID_ATT, log=log))
            log("AT&T pass: %d reps" % len(att))

            dtv = parse_dtv(_run_report(page, base, day, "All", GRID_ALL, log=log))
            log("All pass: DTV for %d reps" % len(dtv))

            records = parse_records(
                _run_report(page, base, day, "AT&T Internet", GRID_INTERNET, log=log))
            log("AT&T Internet pass: records for %d reps" % len(records))
        finally:
            ctx.close()

    return {"agents": merge_dtv(att, dtv), "records": records, "day": day}


def probe(*, headless: bool = True, log=print) -> Dict:
    """READ-ONLY: log in, open the ReportingHub, and report what is ACTUALLY
    there -- the landing url, the page title, which expected landmarks exist,
    and every id/name that looks like a Telerik combo or grid.

    Exists because a bare 'waiting for locator(...)' says only that something
    is missing, never what is present instead, and the answer is usually that
    login landed somewhere else entirely (a dealer picker, a T&C page, a
    session bounce). Clicks nothing, submits nothing, writes nothing.
    """
    from patchright.sync_api import sync_playwright

    out = {}
    with sync_playwright() as p:
        ctx, page, base = _open_and_login(p, headless=headless, log=log)
        try:
            out["base_url"] = base
            log("LOGIN OK -> %s" % base)
            log("after login: %s" % page_state(page))

            # What can this login actually REACH? Dumped from the landing page,
            # because "the hub 404s" and "this account has no reporting module"
            # look identical from the hub's side and need opposite fixes.
            # EVERY link, unfiltered. The first version of this kept only
            # hrefs containing ".aspx" and then grepped them for "report" --
            # and reported "NONE", which I read as "this login has no
            # reporting". It has: the menu is called ANALYTICS (Megan's
            # screenshot, 2026-08-26). A keyword search only ever finds the
            # word you guessed. Dump the nav and read it.
            links = page.evaluate(
                r"""() => Array.from(document.querySelectorAll('a'))
                       .map(a => ({
                              text: (a.textContent || '').trim().replace(/\s+/g, ' '),
                              href: a.getAttribute('href') || '',
                              onclick: (a.getAttribute('onclick') || '').slice(0, 120)}))
                       .filter(o => o.text || o.href)""")
            out["links"] = links
            log("--- %d links on the landing page (ALL of them) ---" % len(links))
            for o in links[:60]:
                log("   %-28s -> %s%s" % (o["text"][:28], o["href"][:90],
                                          ("  onclick=" + o["onclick"]) if o["onclick"] else ""))

            page.goto(base + HUB_PATH, wait_until="domcontentloaded",
                      timeout=NAV_TIMEOUT_MS)
            page.wait_for_timeout(3000)
            out["hub_state"] = page_state(page)
            log("ReportingHub: %s" % out["hub_state"])

            controls = page.evaluate(
                """() => {
                     const out = {combos: [], grids: [], dates: [], buttons: []};
                     for (const el of document.querySelectorAll('[id]')) {
                       const id = el.id;
                       if (/rcb.*Input$/i.test(id)) out.combos.push(id);
                       else if (/^ctl00.*rg[A-Za-z_]*_ctl00$/.test(id)) out.grids.push(id);
                       else if (/rdp.*Date$/i.test(id)) out.dates.push(id);
                       else if (/btn|Submit/i.test(id) && el.tagName !== 'DIV') out.buttons.push(id);
                     }
                     out.title = document.title;
                     out.frames = document.querySelectorAll('iframe').length;
                     return out;
                   }""")
            out["controls"] = controls
            for key in ("combos", "dates", "grids", "buttons"):
                vals = controls.get(key) or []
                log("%-8s %d: %s" % (key, len(vals), ", ".join(vals[:8]) or "(none)"))
            log("iframes on page: %s" % controls.get("frames"))
            if controls.get("frames"):
                log("NOTE: the dashboard may live inside an IFRAME -- our "
                    "selectors run against the top document only.")
        finally:
            ctx.close()
    return out


def probe_grid(service: str = "AT&T Internet", *, headless: bool = True,
               log=print) -> Dict:
    """READ-ONLY: dump one grid's HEADER ROW and first data rows, with column
    INDEXES, so a column mapping can be checked against the live page instead
    of against a doc.

    COL_* here were "confirmed on 2026-07-09" by the porting brief -- the same
    brief that had the ReportingHub path wrong and invented a weekly goal. A
    number that comes from the wrong column looks perfectly plausible, which is
    the kind of wrong nobody catches from the output alone.

        python -m automations.alphalete_sales_board.run --probe-grid
        python -m automations.alphalete_sales_board.run --probe-grid --service "AT&T"
    """
    from patchright.sync_api import sync_playwright
    import datetime as _dt

    grid_for = {"AT&T": GRID_ATT, "All": GRID_ALL, "AT&T Internet": GRID_INTERNET}
    grid = grid_for.get(service)
    if not grid:
        raise SaraError("unknown service %r -- try one of %s"
                        % (service, ", ".join(grid_for)))
    out = {}
    with sync_playwright() as p:
        ctx, page, base = _open_and_login(p, headless=headless, log=log)
        try:
            rows = _run_report(page, base, _dt.date.today(), service, grid, log=log)
            headers = page.evaluate(
                """(sel) => {
                     const g = document.querySelector(sel);
                     if (!g) return [];
                     const head = g.closest('table') || g;
                     const hr = head.querySelectorAll('thead tr');
                     const last = hr[hr.length - 1];
                     return last ? Array.from(last.querySelectorAll('th'))
                                        .map(th => (th.innerText || '').trim()) : [];
                   }""", grid)
            out["headers"] = headers
            out["rows"] = rows[:4]
            log("--- %s grid: %d header cell(s) ---" % (service, len(headers)))
            for i, h in enumerate(headers):
                log("   [%2d] %s" % (i, h[:40]))
            log("--- first data rows (index: value) ---")
            for r in rows[:3]:
                log("   " + " | ".join("[%d]%s" % (i, (v or "")[:14])
                                       for i, v in enumerate(r) if (v or "").strip()))
        finally:
            ctx.close()
    return out
