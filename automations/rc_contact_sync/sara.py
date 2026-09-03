"""Read yesterday's B2B orders off SaraPlus Detail Reports.

SOURCE, spelled out:
  ui.saraplus.com (CARLOS's login) -> Analytics -> Reports/ReportingHub.aspx
  -> tab 'Detail Reports' -> sub-tab 'Sales Order History'
  -> Date Range start = end = the ONE day, Customer Type = 'Both', Submit
  -> the grid whose header row carries 'Order ID' + 'Business Name'
  -> columns 'User Name' (the rep) and 'Business Name'
  -> that row's 'View Customer' link -> 'Primary Phone' + the customer's name.

NOTHING IS ADDRESSED BY INDEX. Telerik renders these tabs as anonymous divs
and this grid's column order is not the Order Dashboard's, so tabs are clicked
by visible text and every column is looked up in the header row that same run.
A header we don't recognise raises -- it never falls through to whatever
column happens to sit where 'Business Name' used to be.
[[feedback_no_hardcoded_columns]]

THE DATE PICKERS ARE TELERIK RadDatePicker and fill() does not work on them;
see alphalete_sales_board.sara._set_telerik_date, which is reused here. Their
element ids on THIS tab are discovered at run time rather than hardcoded,
because the two tabs use different control names.

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional

from automations.alphalete_sales_board.sara import (SaraError, _login,
                                                    _set_telerik_date)
from automations.rc_contact_sync import config as C


# --- small helpers ------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def page_state(page) -> str:
    """One line saying where we ACTUALLY are. Every 'selector not found' is
    really 'not on the page you think', and this is what tells them apart."""
    try:
        title = page.title()
    except Exception:                                      # noqa: BLE001
        title = "?"
    marks = []
    for name, needle in (("detail reports tab", C.TAB_DETAIL_REPORTS),
                         ("sales order history tab", C.TAB_SALES_ORDER_HISTORY),
                         ("login form", None)):
        try:
            if needle is None:
                if page.locator("#ctl00_MainContent_txtUserName").count():
                    marks.append(name)
            elif page.locator("text=%s" % needle).count():
                marks.append(name)
        except Exception:                                  # noqa: BLE001
            pass
    return "url=%s | title=%r | found: %s" % (
        page.url, title, ", ".join(marks) or "NONE of the expected landmarks")


def _click_tab(page, label: str) -> None:
    """Click a RadTabStrip tab by its visible text.

    The strip renders each tab as several nested divs with the same text and
    no id (confirmed on the live hub 2026-09-02), so we click the innermost
    one that actually carries the handler -- the .rtsLink anchor when there is
    one, else the deepest element whose whole text equals the label."""
    clicked = page.evaluate(
        """(want) => {
             const hit = [];
             document.querySelectorAll('a,span,div').forEach(e => {
               if ((e.innerText || '').trim() === want) hit.push(e);
             });
             if (!hit.length) return false;
             // deepest match = the clickable leaf; the outer wrappers repeat
             // the same text and swallow the click on some skins.
             const link = hit.find(e => (e.className || '').includes('rtsLink'));
             (link || hit[hit.length - 1]).click();
             return true;
           }""", label)
    if not clicked:
        raise SaraError("no %r tab on this page. %s" % (label, page_state(page)))
    page.wait_for_load_state("networkidle", timeout=C.NAV_TIMEOUT_MS)
    page.wait_for_timeout(800)


def _date_picker_ids(page) -> List[str]:
    """The RadDatePicker base ids visible on the current panel, in DOM order.

    A RadDatePicker is a hidden input `<id>` beside a visible `<id>_dateInput`,
    so the visible ones are exactly the ids that have a _dateInput sibling and
    are not inside a hidden panel. Discovered per run: the Detail Reports date
    fields are not the Order Dashboard's rdpOrderDash* ids."""
    return page.evaluate(
        """() => {
             const out = [];
             document.querySelectorAll('input[id$="_dateInput"]').forEach(e => {
               const base = e.id.replace(/_dateInput$/, '');
               const r = e.getBoundingClientRect();
               if (r.width > 0 && r.height > 0) out.push(base);
             });
             return out;
           }""")


def _set_customer_type(page, label: str) -> None:
    """Pick the Customer Type value by visible text.

    Carlos's Loom: 'for the customer type, we would click on both'. 'Both' is
    also the page default, so a failure here is logged rather than fatal --
    but it IS logged, because a silently un-set filter is the kind of thing
    that shows up weeks later as 'why are we missing half the customers'."""
    picked = page.evaluate(
        """(want) => {
             // Telerik combo: click the input, then the list item.
             const inputs = [...document.querySelectorAll('input[id*="CustomerType"], select[id*="CustomerType"]')];
             for (const el of inputs) {
               if (el.tagName === 'SELECT') {
                 const opt = [...el.options].find(o => o.text.trim() === want);
                 if (opt) { el.value = opt.value;
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                            return 'select'; }
               }
             }
             return '';
           }""", label)
    if picked:
        page.wait_for_timeout(400)
        return
    # RadComboBox path: open it, then click the item with that text.
    try:
        combo = page.locator('input[id*="CustomerType"][id$="_Input"]').first
        if combo.count():
            combo.click()
            page.wait_for_timeout(600)
            page.evaluate(
                """(want) => {
                     const items = document.querySelectorAll('.rcbList li, [class*="rcbItem"]');
                     for (const el of items) {
                       if ((el.textContent || '').trim() === want) { el.click(); return true; }
                     }
                     return false;
                   }""", label)
            page.wait_for_timeout(400)
    except Exception:                                      # noqa: BLE001
        pass


def _submit(page) -> None:
    page.evaluate(
        """() => {
             const btns = [...document.querySelectorAll(
               'input[type=submit],input[type=button],button,a')];
             const b = btns.find(e => ((e.value || e.innerText || '').trim()
                                       .toLowerCase() === 'submit'));
             if (b) b.click();
           }""")
    page.wait_for_load_state("networkidle", timeout=C.GRID_TIMEOUT_MS)
    page.wait_for_timeout(1200)


# --- the grid -----------------------------------------------------------------

def read_grid(page) -> List[Dict[str, str]]:
    """Every data row of the Sales Order History grid, keyed BY HEADER LABEL.

    Returns dicts like {'Order ID': 'DSI269931154', 'User Name': 'FERNANDO
    SALAZAR', 'Business Name': '...', '_row': 3} -- '_row' being the row's
    0-based position, which is how the View Customer link for that row is
    found again after the page reloads."""
    tables = page.evaluate(
        """() => {
             const out = [];
             document.querySelectorAll('table').forEach((t, ti) => {
               const head = t.querySelector('tr');
               if (!head) return;
               const hs = [...head.querySelectorAll('th,td')]
                            .map(c => (c.innerText || '').replace(/\\s+/g,' ').trim());
               if (!hs.length) return;
               const rows = [...t.querySelectorAll('tr')].slice(1).map(
                 r => [...r.querySelectorAll('td')].map(
                   c => (c.innerText || '').replace(/\\s+/g,' ').trim()));
               out.push({index: ti, headers: hs, rows: rows});
             });
             return out;
           }""")
    try:
        return parse_tables(tables)
    except SaraError as e:
        raise SaraError("%s %s" % (e, page_state(page)))


def parse_tables(tables: List[Dict]) -> List[Dict[str, str]]:
    """The pure half of read_grid: pick the right table and map its columns.

    Split out from the browser so the column logic can be tested without a
    login -- this is the part that decides which text is a rep and which is a
    business, and it should not need SaraPlus to be up to be checked."""
    want = set(C.REQUIRED_COLUMNS)
    grid = None
    for t in tables:
        if want.issubset({_norm(h) for h in t["headers"]}):
            grid = t
            break
    if grid is None:
        seen = " | ".join(
            ", ".join(t["headers"][:8]) for t in tables[:6]) or "no tables at all"
        raise SaraError(
            "no grid on this page carries all of %s. Headers seen: %s."
            % (", ".join(C.REQUIRED_COLUMNS), seen))

    idx = {}
    for want_col in C.REQUIRED_COLUMNS:
        for i, h in enumerate(grid["headers"]):
            if _norm(h) == want_col:
                idx[want_col] = i
                break
    out: List[Dict[str, str]] = []
    for n, cells in enumerate(grid["rows"]):
        if not cells:
            continue                       # spacer / pager row
        row = {c: (cells[i] if i < len(cells) else "")
               for c, i in idx.items()}
        if not row.get(C.COL_ORDER_ID):
            continue                       # grouping or footer row
        row["_row"] = n
        out.append(row)
    return out


# --- the customer card --------------------------------------------------------

def _text_after_label(page, label: str) -> str:
    """The value that sits beside a label on the customer card.

    Read by LABEL, both layouts: a two-cell table row ('Primary Phone' | the
    number) and a stacked div ('Primary Phone' then the number). Returns '' if
    the label isn't on the page -- the caller decides whether that is fatal."""
    return page.evaluate(
        """(want) => {
             const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
             const wants = norm(want).toLowerCase();
             const els = [...document.querySelectorAll('td,th,div,span,label,b,strong')];
             for (const e of els) {
               const t = norm(e.innerText).toLowerCase().replace(/[:*]+$/, '');
               if (t !== wants) continue;
               // same row, next cell
               const cell = e.closest('td,th');
               if (cell && cell.nextElementSibling) {
                 const v = norm(cell.nextElementSibling.innerText);
                 if (v) return v;
               }
               // next sibling / next text block
               let sib = e.nextElementSibling;
               while (sib) {
                 const v = norm(sib.innerText);
                 if (v) return v;
                 sib = sib.nextElementSibling;
               }
               // a wrapping node that holds 'Label value'
               const p = e.parentElement;
               if (p) {
                 const v = norm(p.innerText);
                 if (v.toLowerCase().startsWith(wants))
                   return norm(v.slice(want.length).replace(/^[:\\s]+/, ''));
               }
             }
             return '';
           }""", label)


def open_customer(page, row_index: int) -> Dict[str, str]:
    """Click row `row_index`'s 'View Customer' and read the card.

    Returns {'phone', 'customer_name', 'url'}. The card opens either in place
    or in a popup depending on the skin, so both are handled; either way we
    come back to the grid before returning."""
    ctx = page.context
    before = len(ctx.pages)
    opened = page.evaluate(
        """(n) => {
             const links = [...document.querySelectorAll('a')]
               .filter(a => (a.innerText || '').replace(/\\s+/g,' ').trim()
                              .toLowerCase() === 'view customer');
             if (n >= links.length) return false;
             links[n].click();
             return true;
           }""", row_index)
    if not opened:
        raise SaraError("row %d has no 'View Customer' link" % row_index)

    page.wait_for_timeout(1500)
    card = page
    popup = None
    if len(ctx.pages) > before:
        popup = ctx.pages[-1]
        card = popup
    card.wait_for_load_state("networkidle", timeout=C.NAV_TIMEOUT_MS)

    phone = _text_after_label(card, C.PRIMARY_PHONE_LABEL)
    name = ""
    for label in ("Customer Name", "Contact Name", "Full Name", "Name"):
        name = _text_after_label(card, label)
        if name:
            break
    if not name:
        first = _text_after_label(card, "First Name")
        last = _text_after_label(card, "Last Name")
        name = _norm("%s %s" % (first, last))
    url = card.url

    if popup is not None:
        popup.close()
    else:
        page.go_back(wait_until="networkidle", timeout=C.NAV_TIMEOUT_MS)
        page.wait_for_timeout(800)
    return {"phone": _norm(phone), "customer_name": _norm(name), "url": url}


# --- the whole pass -----------------------------------------------------------

def open_report(page, base_url: str, day: dt.date, log=print) -> None:
    """Navigate to Sales Order History for ONE day and submit it."""
    page.goto(base_url + C.HUB_PATH, wait_until="networkidle",
              timeout=C.NAV_TIMEOUT_MS)
    if "404" in (page.title() or "") or "404.aspx" in page.url:
        raise SaraError(
            "%s is a 404 for this dealer (landed on %s). The Reporting Hub "
            "sits BESIDE DealerPages/, not inside it."
            % (base_url + C.HUB_PATH, page.url))
    _click_tab(page, C.TAB_DETAIL_REPORTS)
    _click_tab(page, C.TAB_SALES_ORDER_HISTORY)

    ids = _date_picker_ids(page)
    if len(ids) < 2:
        raise SaraError(
            "expected two date fields on Sales Order History, found %d (%s). %s"
            % (len(ids), ", ".join(ids) or "none", page_state(page)))
    # Carlos's Loom: the range is set to the one day, start AND end.
    _set_telerik_date(page, ids[0], day)
    _set_telerik_date(page, ids[1], day)
    log("  date range %s -> %s (%s, %s)" % (day, day, ids[0], ids[1]))

    _set_customer_type(page, C.CUSTOMER_TYPE_BOTH)
    _submit(page)


def scrape(day: Optional[dt.date] = None, *, headless: bool = True,
           limit: Optional[int] = None, log=print) -> List[Dict[str, str]]:
    """Yesterday's B2B orders with the rep, the business and the phone.

    [{'order_id', 'day', 'rep', 'business', 'customer_name', 'phone'}]
    One browser session for the whole pass -- the customer card is opened and
    closed inside it, so the grid is submitted once, not once per row."""
    from patchright.sync_api import sync_playwright

    day = day or C.yesterday()
    cr = C.creds()
    C.PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    out: List[Dict[str, str]] = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(C.PROFILE_DIR), headless=headless, args=["--disable-sync"])
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                base = _login(page, cr["email"], cr["password"])
            except SaraError as e:
                raise SaraError(
                    "%s (credentials read from %s -- this report uses CARLOS's "
                    "SaraPlus login, not the sales board's)"
                    % (e, C.CREDS_PATH))
            log("logged in as %s: %s" % (cr["email"], base))

            open_report(page, base, day, log=log)
            rows = read_grid(page)
            log("Sales Order History %s: %d order(s)" % (day, len(rows)))
            if limit:
                rows = rows[:limit]
                log("  --limit %d: only the first %d" % (limit, len(rows)))

            for r in rows:
                card = open_customer(page, r["_row"])
                out.append({
                    "order_id": r[C.COL_ORDER_ID],
                    "day": day.isoformat(),
                    "order_date": r.get(C.COL_ORDER_DATE, ""),
                    "rep": _norm(r[C.COL_REP]),
                    "business": _norm(r[C.COL_BUSINESS]),
                    "customer_name": card["customer_name"],
                    "phone": card["phone"],
                })
                log("  %-14s %-28s %-22s %s"
                    % (r[C.COL_ORDER_ID], r[C.COL_BUSINESS][:28],
                       card["customer_name"][:22], card["phone"] or "NO PHONE"))
        finally:
            ctx.close()
    return out


def probe(day: Optional[dt.date] = None, *, headless: bool = True,
          log=print) -> Dict:
    """READ-ONLY: log in, open the report, and say what is actually there --
    the landing url, the tabs found, the date-picker ids, every grid header,
    and the FIRST customer card's labels. This is the thing to run on Lucy 2
    the first time, before trusting a single contact write."""
    from patchright.sync_api import sync_playwright

    day = day or C.yesterday()
    cr = C.creds()
    C.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    info: Dict = {"day": day.isoformat(), "login": cr["email"]}

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(C.PROFILE_DIR), headless=headless, args=["--disable-sync"])
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            base = _login(page, cr["email"], cr["password"])
            info["base"] = base
            page.goto(base + C.HUB_PATH, wait_until="networkidle",
                      timeout=C.NAV_TIMEOUT_MS)
            info["hub_state"] = page_state(page)
            _click_tab(page, C.TAB_DETAIL_REPORTS)
            _click_tab(page, C.TAB_SALES_ORDER_HISTORY)
            info["date_pickers"] = _date_picker_ids(page)
            _set_customer_type(page, C.CUSTOMER_TYPE_BOTH)
            ids = info["date_pickers"]
            if len(ids) >= 2:
                _set_telerik_date(page, ids[0], day)
                _set_telerik_date(page, ids[1], day)
            _submit(page)
            info["headers"] = page.evaluate(
                """() => [...document.querySelectorAll('table')]
                     .map(t => [...(t.querySelector('tr') || {querySelectorAll: () => []})
                       .querySelectorAll('th,td')]
                       .map(c => (c.innerText||'').replace(/\\s+/g,' ').trim()))
                     .filter(h => h.length > 2).slice(0, 8)""")
            try:
                rows = read_grid(page)
                info["rows"] = len(rows)
                info["first_row"] = rows[0] if rows else None
                if rows:
                    info["first_card"] = open_customer(page, rows[0]["_row"])
            except SaraError as e:
                info["grid_error"] = str(e)
        finally:
            ctx.close()
    for k, v in info.items():
        log("%s: %s" % (k, v))
    return info
