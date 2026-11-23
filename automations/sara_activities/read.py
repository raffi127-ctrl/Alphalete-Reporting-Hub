"""Read SaraPlus Analytics -> Detail Reports -> Activities for a date range.

Path, as Raf showed it (Loom 2026-11-23): ReportingHub -> 'Detail Reports'
(top row, green) -> 'Activities' (second row) -> Activity Report panel:
Date Range (two RadDatePickers), Report View Quick, Disposition ALL,
Customer Type Residential, Submit, Export Options CSV / Excel.

The Activity panel's control ids were never seen from code (built off the
Loom), so nothing below names an id: tabs and buttons are found by their
VISIBLE TEXT, date pickers as the visible RadDatePickers on the page (the
Order Dashboard's pair is on a hidden tab once Activities is open). Every
step logs what it found, and `--probe` dumps the panel, so the first live
run says exactly what to fix if a guess is wrong.

The rows come from the CSV export (all rows, no paging). If the download
never arrives, the visible grid is read instead and the log says so.

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Dict, List, Tuple

from automations.shared import saraplus as _sp

_PICK = "data-claude-pick"

# Mark the first VISIBLE element whose own text (or value) is exactly `want`.
# Innermost match wins (a tab's <span> rather than the whole strip), then the
# nearest clickable ancestor is what gets marked.
_MARK_JS = r"""([want, attr]) => {
  document.querySelectorAll('[' + attr + ']').forEach(e => e.removeAttribute(attr));
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                    && getComputedStyle(el).visibility !== 'hidden';
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const w = norm(want);
  const all = Array.from(document.querySelectorAll(
      'a, button, input[type=submit], input[type=button], span, li, div, td'));
  const hits = all.filter(el => {
    const t = el.tagName === 'INPUT' ? norm(el.value) : norm(el.innerText);
    return t === w && vis(el);
  });
  if (!hits.length) return null;
  // innermost: no other hit inside it
  const inner = hits.filter(h => !hits.some(o => o !== h && h.contains(o)));
  let el = inner[0];
  const click = el.closest('a, button, input, li') || el;
  click.setAttribute(attr, '1');
  return {tag: click.tagName, id: click.id || '', n: hits.length};
}"""

_VISIBLE_DATES_JS = r"""() => {
  const vis = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
  const out = [];
  for (const el of document.querySelectorAll('input[id$="_dateInput"]')) {
    if (vis(el)) out.push(el.id.replace(/_dateInput$/, ''));
  }
  return out;
}"""

_DUMP_JS = r"""() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const out = {ids: [], buttons: [], tables: []};
  for (const el of document.querySelectorAll('[id]')) {
    if (!vis(el)) continue;
    if (/rdp|rcb|rg|btn|Submit|Export|Csv|Excel|Activ/i.test(el.id)) out.ids.push(el.tagName + '#' + el.id);
  }
  for (const el of document.querySelectorAll('a, button, input[type=submit], input[type=button]')) {
    if (!vis(el)) continue;
    const t = (el.tagName === 'INPUT' ? el.value : el.innerText || '').replace(/\s+/g, ' ').trim();
    if (t && t.length < 40) out.buttons.push(t + (el.id ? ' (#' + el.id + ')' : ''));
  }
  for (const t of document.querySelectorAll('table')) {
    if (!vis(t)) continue;
    const ths = Array.from(t.querySelectorAll('th')).map(th => (th.innerText || '').trim()).filter(Boolean);
    if (ths.length > 3) out.tables.push({id: t.id || '', n: t.querySelectorAll('tbody tr').length, th: ths.slice(0, 16)});
  }
  return out;
}"""

# The visible table whose header has both 'Order ID' and 'Agent Name'.
_GRID_JS = r"""() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  for (const t of document.querySelectorAll('table')) {
    if (!vis(t)) continue;
    const hr = t.querySelectorAll('thead tr');
    if (!hr.length) continue;
    const th = Array.from(hr[hr.length - 1].querySelectorAll('th')).map(x => norm(x.innerText));
    if (!th.includes('Order ID') || !th.includes('Agent Name')) continue;
    const rows = Array.from(t.querySelectorAll('tbody > tr'))
      .map(tr => Array.from(tr.querySelectorAll(':scope > td')).map(td => norm(td.innerText)));
    return {headers: th, rows: rows};
  }
  return null;
}"""


class ActivitiesError(_sp.SaraError):
    pass


def _click_text(page, text: str, log, *, required: bool = True) -> bool:
    got = page.evaluate(_MARK_JS, [text, _PICK])
    if not got:
        if required:
            raise ActivitiesError("no visible %r on the page -- %s"
                                  % (text, _sp.page_state(page)))
        return False
    log("  click %r -> %s%s (%d match%s)" % (
        text, got["tag"], ("#" + got["id"]) if got["id"] else "",
        got["n"], "" if got["n"] == 1 else "es"))
    page.click("[%s='1']" % _PICK, timeout=30_000)
    return True


def dump(page, log, label: str) -> Dict:
    d = page.evaluate(_DUMP_JS)
    log("--- %s ---" % label)
    log("  ids     : %s" % (", ".join(d["ids"][:40]) or "(none)"))
    log("  buttons : %s" % (" | ".join(d["buttons"][:50]) or "(none)"))
    for t in d["tables"][:6]:
        log("  table #%s rows=%s th=%s" % (t["id"], t["n"], t["th"]))
    return d


def open_activities(page, base: str, log=print, probe: bool = False) -> None:
    page.goto(base + _sp.HUB_PATH, wait_until="domcontentloaded",
              timeout=_sp.NAV_TIMEOUT_MS)
    page.wait_for_timeout(2500)
    _sp._assert_on_hub(page, base)
    if probe:
        dump(page, log, "hub as it loads")
    _click_text(page, "Detail Reports", log)
    page.wait_for_timeout(2500)
    _click_text(page, "Activities", log)
    page.wait_for_timeout(3500)
    if probe:
        dump(page, log, "after Detail Reports -> Activities")


def _set_range(page, start: dt.date, end: dt.date, log) -> None:
    ids = page.evaluate(_VISIBLE_DATES_JS)
    ids = [i for i in ids if i not in (_sp.FIELD_START, _sp.FIELD_END)] or ids
    if len(ids) < 2:
        raise ActivitiesError("expected the Activity Report's 2 date boxes, "
                              "found %d visible: %s" % (len(ids), ids))
    log("  date boxes: %s .. %s" % (ids[0], ids[1]))
    _sp._set_telerik_date(page, ids[0], start)
    _sp._set_telerik_date(page, ids[1], end)


def _csv_rows(page, log) -> Tuple[List[str], List[List[str]]]:
    with page.expect_download(timeout=90_000) as dl_info:
        _click_text(page, "CSV", log)
    dl = dl_info.value
    path = dl.path()
    raw = open(path, "rb").read()
    text = raw.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        return [], []
    log("  CSV: %d data row(s), headers %s" % (len(rows) - 1, rows[0]))
    return [h.strip() for h in rows[0]], rows[1:]


def read_range(page, base: str, start: dt.date, end: dt.date, log=print,
               probe: bool = False) -> Tuple[List[str], List[List[str]], str]:
    """(headers, rows, how) -- how = 'csv' or 'grid'."""
    open_activities(page, base, log=log, probe=probe)
    _set_range(page, start, end, log)
    _sp._pick_company_if_asked(page)
    _click_text(page, "Submit", log)
    # Wait for the grid with Order ID / Agent Name to be there.
    grid = None
    for _ in range(60):
        page.wait_for_timeout(1500)
        grid = page.evaluate(_GRID_JS)
        if grid is not None:
            break
    if probe:
        dump(page, log, "after Submit")
    if grid is None:
        raise ActivitiesError("the Activity grid (Order ID + Agent Name) never "
                              "showed after Submit -- %s" % _sp.page_state(page))
    log("  grid on screen: %d row(s)" % len(grid["rows"]))
    try:
        headers, rows = _csv_rows(page, log)
        if headers:
            return headers, rows, "csv"
        log("  CSV came back empty -- reading the grid instead")
    except Exception as e:  # noqa: BLE001 -- the grid is the fallback
        log("  CSV export failed (%s: %s) -- reading the grid instead"
            % (type(e).__name__, str(e)[:200]))
    return grid["headers"], grid["rows"], "grid"
