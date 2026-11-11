"""Customer e-mail addresses for the NDS Order Log tab, off NDS SaraPlus.

Carlos 2026-11-11: "looks like on the nds order log we need to add the
customers email so we can check the shipping status". AT&T's guest order
lookup (att.com/orders/checkmyorder) wants the order number, the ZIP and
the e-mail address that was put on the order before it shows a thing, and
nothing we pull carries that e-mail: not the wireless per-line feed (the
Reporting Hub's Wireless Dashboard), not its Excel export, not the Tableau
NDS-SN order-log export. SaraPlus only shows it on the customer card
(Sales Order History -> a row's View Customer -> "E-mail Address"), which
is where the 2026-09 status probe photographed it.

So this harvests it: NDS SaraPlus login (the wireless pull's creds and
profile), Detail Reports -> Sales Order History for the order dates the
tab carries (7-day windows, the panel is one grid page per window), and
per order either the grid's own e-mail column when the grid has one (every
column is in the DOM whatever the Report View says -- sara.read_grid) or
the View Customer card's E-mail Address input. Found addresses land in
output/nds_metrics/customer_emails.json keyed by DSI #, which
order_log_tab.EmailIndex reads into the tab's "Email" column (after Zip).
An order the card cannot place keeps whatever the tab already has.

    python -m automations.nds_metrics.customer_email              # harvest + refresh the tab
    python -m automations.nds_metrics.customer_email --dry-run    # harvest, say what it found, tab untouched
    python -m automations.nds_metrics.customer_email --limit 5    # the first 5 wanted orders only
    python -m automations.nds_metrics.customer_email --dsi DSI280405775 --dsi DSI280428165

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from automations.nds_metrics.run import NDS_SARA_CREDS, NDS_SARA_PROFILE, OUT_DIR

CACHE = OUT_DIR / "customer_emails.json"
WINDOW_DAYS = 7
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# a page of the Sales Order History grid; a window that fills it is split
GRID_PAGE_ROWS = 100


# --- the cache ---------------------------------------------------------------

def load_cache(path: Path = CACHE) -> Dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- a half-written file must not stop the morning
        return {}
    return {str(k): v for k, v in data.items()} if isinstance(data, dict) else {}


def save_cache(data: Dict[str, dict], path: Path = CACHE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def _norm_dsi(v) -> str:
    return "".join(ch for ch in str(v or "").upper() if ch.isalnum())


def _norm(s) -> str:
    return " ".join(str(s or "").split()).strip()


# --- what to look for ----------------------------------------------------------

def _parse_date(v) -> Optional[dt.date]:
    s = str(v or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def wanted_orders(today: dt.date, cache: Dict[str, dict], *, only: Sequence[str] = (),
                  log=print) -> Dict[str, dict]:
    """{dsi: {customer, order_date}} for every order on today's cached
    wireless feed plus every order on the tab whose Email is blank, minus
    the ones the cache already has (unless named with --dsi)."""
    from automations.nds_metrics import wireless_pull as WP
    want: Dict[str, dict] = {}
    f = WP.cached(today)
    if f is not None:
        orders, _lines = WP.parse(f.read_bytes(), log=lambda *a, **k: None)
        for o in orders:
            d = _norm_dsi(o.get("dsi"))
            if d:
                want[d] = {"customer": _norm(o.get("customer")),
                           "order_date": _norm(o.get("order_date"))}
        log("[email] feed: %d order(s)" % len(want))
    else:
        log("[email] no wireless feed cached for %s -- tab orders only" % today)
    try:
        for d, info in tab_orders_without_email(log=log).items():
            want.setdefault(d, info)
    except Exception as e:  # noqa: BLE001
        log("[email] (tab read failed: %s: %s -- feed orders only)" % (type(e).__name__, str(e)[:160]))
    if only:
        keep = {_norm_dsi(x) for x in only}
        want = {d: v for d, v in want.items() if d in keep}
        for d in keep - set(want):
            want[d] = {"customer": "", "order_date": ""}
        return want
    # an order the grid showed WITHOUT an e-mail is not asked for again every
    # morning (it is in the cache with email ""), only ones never seen
    return {d: v for d, v in want.items() if d not in cache}


def tab_orders_without_email(log=print) -> Dict[str, dict]:
    """Orders on the live NDS Order Log tab with a blank Email, by DSI."""
    from automations.nds_metrics import order_log_tab as T
    from automations.recruiting_report.fill import open_by_key, _retry
    sh = open_by_key(T.VANTURA_SHEET_ID)
    ws = sh.worksheet(T.TAB)
    rows = _retry(lambda: ws.get_all_values())
    if not rows:
        return {}
    hdr = [" ".join(str(h).split()).lower() for h in rows[0]]
    need = {}
    for name in ("dsi #", "customer", "order date"):
        if name not in hdr:
            raise RuntimeError("NDS Order Log tab has no %r column -- header: %r" % (name, rows[0]))
        need[name] = hdr.index(name)
    i_email = hdr.index("email") if "email" in hdr else None
    out: Dict[str, dict] = {}
    for r in rows[1:]:
        cell = lambda i: r[i] if i is not None and i < len(r) else ""  # noqa: E731
        if i_email is not None and _norm(cell(i_email)):
            continue
        d = _norm_dsi(cell(need["dsi #"]))
        if d and d not in out:
            out[d] = {"customer": _norm(cell(need["customer"])),
                      "order_date": _norm(cell(need["order date"]))}
    log("[email] tab: %d order(s) without an e-mail" % len(out))
    return out


def windows(dates: Iterable[Optional[dt.date]], today: dt.date,
            days: int = WINDOW_DAYS) -> List[Tuple[dt.date, dt.date]]:
    """7-day [start, end] windows covering every order date (unknown dates
    -> the last 31 days), newest first."""
    known = [d for d in dates if d]
    lo = min(known) if known else today - dt.timedelta(days=31)
    if not known or any(d is None for d in dates):
        lo = min(lo, today - dt.timedelta(days=31))
    out = []
    end = today
    while end >= lo:
        start = max(lo, end - dt.timedelta(days=days - 1))
        out.append((start, end))
        end = start - dt.timedelta(days=1)
    return out


# --- the grid and the card -------------------------------------------------------

_GRID_JS = """
(ids) => {
  const hdr = document.getElementById(ids.header);
  const data = document.getElementById(ids.data);
  if (!hdr || !data) return {headers: [], rows: [], missing: (!hdr ? 'header ' : '') + (!data ? 'data' : '')};
  const headRow = hdr.querySelector('tr');
  const headers = headRow ? [...headRow.querySelectorAll('th,td')]
      .map(c => (c.innerText || '').replace(/[ \\t\\n\\r]+/g, ' ').trim()) : [];
  const rows = [...data.querySelectorAll('tbody > tr')].map((r, i) => {
    const cells = [...r.querySelectorAll('td')].map(c => (c.innerText || '').replace(/[ \\t\\n\\r]+/g, ' ').trim());
    const a = [...r.querySelectorAll('a,input[type=button],input[type=submit],button')]
      .find(x => /view/i.test(((x.innerText || x.value || '') + ' ' + (x.id || '')).trim()));
    return {i: i, cells: cells,
            view: a ? {id: a.id || '', onclick: a.getAttribute('onclick') || '', text: (a.innerText || a.value || '').trim()} : null};
  });
  return {headers: headers, rows: rows, missing: ''};
}
"""

_CLICK_ROW_VIEW_JS = """
(cfg) => {
  const data = document.getElementById(cfg.gid);
  if (!data) return 'no grid';
  const rows = [...data.querySelectorAll('tbody > tr')];
  const row = rows[cfg.i];
  if (!row) return 'row gone';
  const e = [...row.querySelectorAll('a,input[type=button],input[type=submit],button')]
    .find(x => /view/i.test(((x.innerText || x.value || '') + ' ' + (x.id || '')).trim()));
  if (!e) return 'no View link on the row';
  e.click();
  return 'clicked';
}
"""

_EMAILS_JS = """
() => {
  const out = [];
  const re = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}/;
  const labelOf = (el) => {
    // the card lays each field out as a blue label above a grey box: the
    // nearest label-ish text before the input, within its block
    let n = el, hops = 0;
    while (n && hops < 6) {
      let p = n.previousElementSibling;
      while (p) {
        const t = (p.innerText || p.textContent || '').trim();
        if (t && t.length < 40) return t;
        p = p.previousElementSibling;
      }
      n = n.parentElement; hops += 1;
    }
    return '';
  };
  for (const el of document.querySelectorAll('input,textarea')) {
    const v = (el.value || '').trim();
    const tag = ((el.id || '') + ' ' + (el.name || '') + ' ' + (el.placeholder || '')).toLowerCase();
    if (re.test(v)) out.push({where: 'input', id: el.id || el.name || '', value: v,
                              label: labelOf(el), mail: /mail/.test(tag)});
  }
  const m = (document.body ? (document.body.innerText || '') : '').match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}/g) || [];
  for (const v of m) out.push({where: 'text', id: '', value: v, mail: false});
  return out;
}
"""

_CLOSE_CARD_JS = """
() => {
  const els = [...document.querySelectorAll('a,span,button,input')];
  const b = els.find(e => /rwCloseButton|CloseButton/i.test(e.className || ''))
         || els.find(e => /^close$/i.test((e.textContent || e.value || '').trim()));
  if (b) { b.click(); return true; }
  return false;
}
"""


def pick_email(found: List[dict], login_email: str = "") -> str:
    """The customer's address out of what the card shows: the input under
    the card's "E-mail Address" label first, then an input whose id says
    mail, then any input holding an address, then page text -- never our
    own login."""
    own = (login_email or "").strip().lower()
    cands = [f for f in found if f.get("value") and f["value"].strip().lower() != own
             and not f["value"].lower().endswith("saraplus.com")]
    for pred in (lambda f: f["where"] == "input" and re.search(r"e-?mail", f.get("label") or "", re.I),
                 lambda f: f["where"] == "input" and f.get("mail"),
                 lambda f: f["where"] == "input",
                 lambda f: True):
        for f in cands:
            if pred(f):
                return f["value"].strip()
    return ""


def _email_column(headers: Sequence[str]) -> Optional[int]:
    """The CUSTOMER's e-mail column. The grid carries "User Email" (the rep
    who placed the order) eighteen columns before "Email" (the customer);
    the first harvest on 11/11 took the first match and put every rep's
    address on their customers (Carlos: "thats the sales reps email")."""
    norm = [_norm(h).lower() for h in headers]
    for want in ("email", "e-mail", "customer email", "customer e-mail", "e-mail address", "email address"):
        if want in norm:
            return norm.index(want)
    for i, h in enumerate(norm):
        if re.search(r"e-?mail", h) and not re.search(r"user|rep|sales|dealer|agent|entered", h):
            return i
    return None


def _id_columns(headers: Sequence[str]) -> List[int]:
    """Columns whose text could carry the DSI (Order ID / SP Order ID /
    Order Number / DSI). The row is also searched whole as a fallback."""
    out = []
    for i, h in enumerate(headers):
        if re.search(r"order ?id|sp order|order number|dsi", h or "", re.I):
            out.append(i)
    return out


def _row_dsi(cells: Sequence[str], id_cols: Sequence[int], wanted: Set[str]) -> str:
    for i in id_cols:
        if i < len(cells):
            d = _norm_dsi(cells[i])
            if d in wanted:
                return d
    for c in cells:
        for m in re.findall(r"(?:DSI|SPM)\s*\d{6,}", c or "", re.I):
            d = _norm_dsi(m)
            if d in wanted:
                return d
    return ""


def harvest(want: Dict[str, dict], today: dt.date, *, headless: bool = True,
            limit: Optional[int] = None, log=print, save=None) -> Dict[str, dict]:
    """Open NDS SaraPlus and read the e-mail for each wanted order. Returns
    {dsi: {email, customer, source, seen}} for the ones found. `save(found)`
    is called after every window, so a run that dies keeps what it read
    (the 11/11 refresh lost 66 addresses to a panel that would not re-open)."""
    from patchright.sync_api import sync_playwright
    from automations.rc_contact_sync import config as C
    from automations.rc_contact_sync import sara

    cr = json.loads(NDS_SARA_CREDS.read_text())
    NDS_SARA_PROFILE.mkdir(parents=True, exist_ok=True)
    remaining: Set[str] = set(want)
    if limit:
        remaining = set(list(sorted(remaining))[:limit])
    found: Dict[str, dict] = {}
    dates = [_parse_date(want[d].get("order_date")) for d in remaining]
    wins = windows(dates, today)
    log("[email] %d order(s) to look up across %d window(s)" % (len(remaining), len(wins)))

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(NDS_SARA_PROFILE), headless=headless, args=["--disable-sync"],
            viewport={"width": 1600, "height": 1000})
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            base = sara.login(page, cr["email"], cr["password"], log=log)
            log("[email] logged in as %s" % cr["email"])
            page.goto(base + C.HUB_PATH, wait_until="networkidle", timeout=C.NAV_TIMEOUT_MS)
            sara.open_order_history_panel(page, log=log)
            headers_logged = False
            combo_settable = None
            windows_run = 0
            ecol_logged = False
            for start, end in wins:
                if not remaining:
                    break
                # a window holding none of the wanted order dates is skipped
                # (unknown dates look everywhere)
                in_win = [d for d in remaining
                          if (_parse_date(want[d].get("order_date")) is None
                              or start <= _parse_date(want[d].get("order_date")) <= end)]
                if not in_win:
                    continue
                if windows_run:
                    # The full run on 11/11 read the same 41 rows for every
                    # window: once the grid is up, new dates + Submit leave it
                    # as it was. The panel is re-opened fresh per window --
                    # twice if need be, and a window whose panel will not come
                    # back is skipped, not the run.
                    opened = False
                    for attempt in (1, 2):
                        try:
                            page.goto(base + C.HUB_PATH, wait_until="networkidle", timeout=C.NAV_TIMEOUT_MS)
                            page.wait_for_timeout(1500 * attempt)
                            sara.open_order_history_panel(page, log=lambda *a, **k: None)
                            opened = True
                            break
                        except Exception as e:  # noqa: BLE001
                            log("[email] %s..%s: panel did not re-open (try %d: %s: %s)"
                                % (start, end, attempt, type(e).__name__, str(e)[:120]))
                    if not opened:
                        continue
                windows_run += 1
                sara._set_telerik_date(page, C.FIELD_START, start)
                sara._set_telerik_date(page, C.FIELD_END, end)
                # The NDS dealer's Customer Type box is locked ("Residential",
                # disabled -- first run 2026-11-11 timed out clicking it); on a
                # login where it can be set, Both is what sara.open_report uses.
                if combo_settable is None:
                    combo_settable = _combo_enabled(page)
                    if not combo_settable:
                        log("[email] customer type box is fixed on this login -- left as is")
                if combo_settable:
                    try:
                        sara._set_customer_type(page, C.CUSTOMER_TYPE_BOTH, log=lambda *a, **k: None)
                    except Exception as e:  # noqa: BLE001
                        combo_settable = False
                        log("[email] customer type not settable (%s) -- left as is" % type(e).__name__)
                    sara._set_telerik_date(page, C.FIELD_START, start)
                    sara._set_telerik_date(page, C.FIELD_END, end)
                try:
                    sara._submit(page, log=log)
                except Exception as e:  # noqa: BLE001
                    log("[email] %s..%s: submit failed (%s: %s) -- %s"
                        % (start, end, type(e).__name__, str(e)[:120], sara.page_state(page)))
                    continue
                grid = page.evaluate(_GRID_JS, {"header": C.GRID_HEADER, "data": C.GRID_DATA})
                if grid.get("missing"):
                    log("[email] %s..%s: grid missing (%s) -- %s"
                        % (start, end, grid["missing"].strip(), sara.page_state(page)))
                    continue
                headers = grid["headers"]
                rows = [r for r in grid["rows"] if r["cells"]]
                if not headers_logged:
                    log("[email] grid columns (%d): %s"
                        % (len(headers), " | ".join(h for h in headers if h)[:1500]))
                    headers_logged = True
                # the dates the grid actually shows, so a window that did not
                # take (same rows as the last one) is visible in the log
                i_od = next((i for i, h in enumerate(headers) if _norm(h).lower() == "order date"), None)
                shown = sorted({_parse_date(r["cells"][i_od]) for r in rows
                                if i_od is not None and i_od < len(r["cells"])} - {None})
                log("[email] %s..%s: %d row(s), order dates %s..%s" % (
                    start, end, len(rows), shown[0] if shown else "?", shown[-1] if shown else "?"))
                if shown and (shown[-1] < start or shown[0] > end):
                    log("[email]   the grid ignored the window -- rows are outside it")
                if len(rows) >= GRID_PAGE_ROWS:
                    log("[email]   (a full grid page -- orders past it are not read; "
                        "shrink WINDOW_DAYS if this keeps happening)")
                ecol = _email_column(headers)
                id_cols = _id_columns(headers)
                if not ecol_logged:
                    log("[email] customer e-mail column: %s" % (
                        ("%r (#%d)" % (headers[ecol], ecol + 1)) if ecol is not None else "none -- reading the card"))
                    ecol_logged = True
                hit_rows: List[Tuple[str, dict]] = []
                for r in rows:
                    d = _row_dsi(r["cells"], id_cols, remaining)
                    if d:
                        hit_rows.append((d, r))
                log("[email]   %d wanted order(s) on this page" % len(hit_rows))
                if not hit_rows and rows:
                    log("[email]   first row: %s" % " | ".join(c for c in rows[0]["cells"] if c)[:400])
                for d, r in hit_rows:
                    email = ""
                    source = ""
                    if ecol is not None and ecol < len(r["cells"]):
                        m = EMAIL_RE.search(r["cells"][ecol] or "")
                        if m:
                            email, source = m.group(0), "grid"
                    if not email:
                        email = card_email(ctx, page, r, cr.get("email", ""), log=log)
                        source = "card" if email else ""
                    cust = want.get(d, {}).get("customer", "")
                    found[d] = {"email": email, "customer": cust, "source": source,
                                "seen": today.isoformat()}
                    remaining.discard(d)
                    if email:
                        log("  %-14s %-26s %s  (%s)" % (d, cust[:26], email, source))
                    else:
                        log("  %-14s %-26s NO E-MAIL on the order" % (d, cust[:26]))
                if save and hit_rows:
                    save(found)
        finally:
            ctx.close()
            if save:
                save(found)
    if remaining:
        log("[email] %d order(s) not found on any Sales Order History page: %s"
            % (len(remaining), ", ".join(sorted(remaining))[:600]))
    return found


def _combo_enabled(page) -> bool:
    """Can the Customer Type combo be set on this login? (disabled on the
    NDS dealer's Sales Order History)"""
    from automations.rc_contact_sync import config as C
    try:
        return bool(page.evaluate(
            """(id) => { const e = document.getElementById(id);
                         return !!e && !e.disabled && !e.readOnly; }""",
            C.COMBO_CUSTOMER_TYPE + "_Input"))
    except Exception:  # noqa: BLE001
        return False


def card_email(ctx, page, row: dict, login_email: str, log=print) -> str:
    """Open the row's View Customer card, read its e-mail, close it."""
    from automations.rc_contact_sync import config as C
    pages_before = len(ctx.pages)
    try:
        res = page.evaluate(_CLICK_ROW_VIEW_JS, {"gid": C.GRID_DATA, "i": row["i"]})
    except Exception as e:  # noqa: BLE001
        res = "click failed: %s" % str(e)[:120]
    if res != "clicked":
        log("    (%s)" % res)
        return ""
    try:
        page.wait_for_load_state("networkidle", timeout=C.NAV_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(2500)
    found: List[dict] = []
    views = list(ctx.pages[pages_before:]) + [page]
    for v in views:
        for fr in v.frames:
            try:
                found.extend(fr.evaluate(_EMAILS_JS) or [])
            except Exception:  # noqa: BLE001
                continue
    email = pick_email(found, login_email)
    # every address the card showed, with where it sat -- Carlos 11/11 on the
    # first harvest: "thats the sales reps email", so the log has to show
    # which field each address came from
    for f in found:
        log("    candidate %-6s %-28s label=%r id=%r" % (f.get("where"), f.get("value"),
                                                       (f.get("label") or "")[:30], (f.get("id") or "")[:40]))
    # tidy up: a popped tab is closed, a RadWindow card gets its X
    for v in ctx.pages[pages_before:]:
        try:
            v.close()
        except Exception:  # noqa: BLE001
            pass
    try:
        page.evaluate(_CLOSE_CARD_JS)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(1200)
    return email


# --- entry ----------------------------------------------------------------------

def run(today: Optional[dt.date] = None, *, dry_run: bool = False, limit: Optional[int] = None,
        only: Sequence[str] = (), headless: bool = True, refresh: bool = False, log=print) -> int:
    today = today or dt.date.today()
    cache = {} if refresh else load_cache()
    if refresh:
        log("[email] --refresh: the cache is rebuilt from scratch and every order is read again")
    want = wanted_orders(today, cache, only=only, log=log)
    if not want:
        log("[email] every order already has an e-mail in %s (%d)" % (CACHE.name, len(cache)))
    else:
        def _save(found):
            cache.update(found)
            save_cache(cache)
        found = harvest(want, today, headless=headless, limit=limit, log=log, save=_save)
        _save(found)
        log("[email] %d order(s) read this run, %d in %s (%d with an address)"
            % (len(found), len(cache), CACHE.name, sum(1 for v in cache.values() if (v or {}).get("email"))))
    if dry_run:
        log("[email] --dry-run: the tab is not refreshed")
        return 0
    from automations.nds_metrics import order_log_tab as T
    T.refresh(today, log=log)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nds_customer_email",
                                 description="customer e-mails off NDS SaraPlus -> NDS Order Log 'Email'")
    ap.add_argument("--dry-run", action="store_true", help="harvest and report; leave the tab alone")
    ap.add_argument("--limit", type=int, default=None, help="only the first N wanted orders")
    ap.add_argument("--dsi", action="append", default=[], help="only this order (repeatable)")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--refresh", action="store_true",
                    help="forget the cache and read every order again (a wrong column was read on 11/11)")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD (default: today)")
    a = ap.parse_args(argv)
    today = dt.datetime.strptime(a.today, "%Y-%m-%d").date() if a.today else dt.date.today()
    rc = run(today, dry_run=a.dry_run, limit=a.limit, only=a.dsi, headless=not a.headed,
             refresh=a.refresh)
    print("=== done ===", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
