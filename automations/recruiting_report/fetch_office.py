"""Switch the attached AppStream Chrome to one office + week, scrape the
Retention Report, and extract the 13 funnel metrics we need.

Assumes Chrome is launched with --remote-debugging-port=9222 and you've
already logged into AppStream once. Reuses that session.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, Optional

from patchright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

CDP_URL = "http://localhost:9222"
RETENTION_REPORT_PAGE = "p=701"

# Process-level flags. Once jQuery has been seen to never load (patchright
# stealth context appears to suppress it on AppStream), stop paying the
# wait timeout on every subsequent picker call.
_JQUERY_GIVE_UP = False
_FORM_DUMPED = False

# Map our canonical metric -> (AppStream row label, value type)
# Value types: 'count' (int), 'percent' (parsed from "44%" -> 44),
#              'derived' (computed from other metrics post-scrape)
METRICS: Dict[str, dict] = {
    "sent_to_call_list":          {"as_label": "Sent to Call List",                        "type": "count"},  # raw, used for derived only
    "first_booked":               {"as_label": "Total First Interviews",                   "type": "count"},
    "pct_apps_booked_first":      {"as_label": "Retention Call List",                      "type": "percent"},
    "first_showed":               {"as_label": "First Interviews Showed Up",               "type": "count"},
    "pct_first_retention":        {"as_label": "Retention First Interviews",               "type": "percent"},
    "second_booked":              {"as_label": "Total Second Interviews",                  "type": "count"},
    "second_showed":              {"as_label": "Second Interviews Showed Up",              "type": "count"},
    "pct_second_retention":       {"as_label": "Retention Second Interviews",              "type": "percent"},
    "job_offered":                {"as_label": "Offered Job From Second Round",            "type": "count"},
    "bob":                        {"as_label": "Total Daily Bob",                          "type": "count"},
    "new_starts_scheduled":       {"as_label": "Total New Starts Scheduled",               "type": "count"},
    "new_starts_showed":          {"as_label": "New Starts Showed Up",                     "type": "count"},
    "pct_new_start_retention":    {"as_label": "Retention New Starts Scheduled",           "type": "percent"},
    "removed_from_process_emails": {"as_label": "Removed From Process Emails",             "type": "count"},
    "emails_received":             {"as_label": "Emails Received",                          "type": "count"},
    "manual_apps_entry":           {"as_label": "Manual Apps Entry",                        "type": "count"},
    "pct_first_showed_booked_2nd": {"as_label": "Retention First Showed Up Booked Second",  "type": "percent"},
    # Derived (computed from above). Order matters — total_applies must
    # be computed before duplicate_pct since duplicate_pct depends on it.
    "pct_job_offered_retention":  {"derived": ("job_offered", "second_showed"),                       "type": "derived"},
    "pct_bob_conversion":         {"derived": ("bob", "job_offered"),                                 "type": "derived"},
    "pull":                       {"derived": "sum_sent_manual",                                       "type": "derived"},
    "total_applies":              {"derived": "sum_pull_removed",                                       "type": "derived"},
    "duplicate_pct":              {"derived": ("removed_from_process_emails", "pull"),                "type": "derived"},
}


def _attach() -> tuple:
    """Returns (browser, page) of the attached AppStream tab."""
    p = sync_playwright().start()
    browser = p.chromium.connect_over_cdp(CDP_URL)
    target = None
    for ctx in browser.contexts:
        for page in ctx.pages:
            if "applicantstream" in page.url:
                target = page
                break
        if target:
            break
    if not target:
        raise SystemExit("No applicantstream tab open in attached Chrome")
    return p, browser, target


def _dismiss_overlays(page: Page) -> None:
    """Close any open AppStream top-bar dropdowns (Settings, etc.) that would
    intercept clicks on #searchMC. Hovering the topBar opens menus that float
    over the office search input; Playwright then refuses the click.

    Press Escape, then click a neutral area near the page top-left, then
    move the mouse far away so no hover-menu is re-triggered."""
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        page.locator("body").click(position={"x": 5, "y": 5}, timeout=2000)
    except Exception:
        pass
    try:
        page.mouse.move(2000, 2000)
    except Exception:
        pass


def _switch_office(page: Page, office_id: str, owner_hint: str = "") -> bool:
    """Type into searchMC and select the matching office. Wait for page load."""
    _dismiss_overlays(page)
    try:
        page.locator("#searchMC").click(timeout=8000)
    except Exception:
        # Menu re-opened (hover-trigger) — force-click ignores intercept.
        page.locator("#searchMC").click(force=True)
    page.locator("#searchMC").fill("")
    # Type the office_id — most specific search term.
    page.locator("#searchMC").type(office_id, delay=30)
    page.wait_for_timeout(800)

    # Find the matching item in the autocomplete dropdown. Match strictly on
    # office_id — DO NOT fall back to the first item, because that would write
    # the wrong office's data to this tab.
    items = page.locator(".ui-autocomplete li, .ui-menu li").all()
    target_item = None
    for item in items:
        text = item.inner_text()
        if office_id in text:
            target_item = item
            break
    if not target_item:
        # Office isn't accessible in this AS account. Caller should skip.
        return False

    # Click the item — this triggers AppStream's office-switch (page reload)
    with page.expect_navigation(timeout=15000, wait_until="load"):
        target_item.click()
    return True


def _set_week_and_submit(page: Page, week_start: dt.date) -> None:
    """Set weekStart input to the target Sunday and submit the form.

    The input is a jQuery UI datepicker (readonly). To change its value we use
    the datepicker's setDate API rather than mutating the DOM, then submit."""
    global _JQUERY_GIVE_UP, _FORM_DUMPED
    formatted_dash = f"{week_start.month:02d}-{week_start.day:02d}-{week_start.year}"
    formatted_slash = f"{week_start.month:02d}/{week_start.day:02d}/{week_start.year}"
    current = page.locator("#weekStart").input_value()
    print(f"[picker] target={formatted_dash} BEFORE setDate: input_value={current!r}",
          flush=True)
    if current in (formatted_dash, formatted_slash):
        print("[picker] already on target week — skipping setDate", flush=True)
        return  # already on the right week

    # AppStream's datepicker is initialized by an async-loaded jQuery+UI bundle.
    # Under patchright stealth, the page reaches DOMContentLoaded before that
    # bundle finishes, so a setDate call here hits an undefined jQuery and
    # falls through to a no-op direct-value write — the form then submits
    # the server-rendered default week (Megan, 2026-05-26 diagnostic run).
    # Wait for jQuery+plugin once; if it genuinely never loads, give up on
    # the wait for the rest of the process so we don't eat 8s per call.
    if not _JQUERY_GIVE_UP:
        try:
            page.wait_for_function(
                "typeof jQuery !== 'undefined' && jQuery.fn && !!jQuery.fn.datepicker",
                timeout=8000,
            )
            print("[picker] jQuery+datepicker ready", flush=True)
        except PWTimeout:
            _JQUERY_GIVE_UP = True
            print("[picker] jQuery+datepicker never loaded after 8s — "
                  "giving up on wait for the rest of this process", flush=True)

    # Diagnostic: confirm jQuery + datepicker are actually present in this
    # context (patchright stealth has been suspected of stripping them).
    env = page.evaluate(
        """() => ({
          jq:      typeof jQuery !== 'undefined',
          dp:      typeof jQuery !== 'undefined' && !!jQuery.fn && !!jQuery.fn.datepicker,
          dpInstance: (typeof jQuery !== 'undefined' && jQuery('#weekStart').length)
                       ? !!jQuery('#weekStart').data('datepicker') : null,
        })"""
    )
    print(f"[picker] env: jQuery={env.get('jq')} datepicker={env.get('dp')} "
          f"#weekStart has datepicker instance={env.get('dpInstance')}", flush=True)

    # One-shot dump of the form's inputs when jQuery is genuinely missing.
    # If there's a hidden field the datepicker syncs to (separate from
    # #weekStart), we'll see it here and can set it directly.
    if not env.get("jq") and not _FORM_DUMPED:
        _FORM_DUMPED = True
        form_info = page.evaluate(
            """() => {
              const ws = document.getElementById('weekStart');
              const form = ws && ws.form;
              const inputs = form
                ? Array.from(form.querySelectorAll('input, select, textarea'))
                  .map(i => ({name: i.name, type: i.type, id: i.id,
                              value: (i.value || '').slice(0, 60)}))
                : [];
              return {
                action: form ? form.action : null,
                method: form ? form.method : null,
                inputs,
                scripts: Array.from(document.scripts)
                              .map(s => s.src || '<inline>')
                              .slice(0, 30),
              };
            }"""
        )
        print(f"[picker][form-dump] action={form_info.get('action')} "
              f"method={form_info.get('method')}", flush=True)
        for inp in form_info.get("inputs", []):
            print(f"[picker][form-dump]   input name={inp['name']!r} "
                  f"type={inp['type']!r} id={inp['id']!r} value={inp['value']!r}",
                  flush=True)
        for src in form_info.get("scripts", []):
            print(f"[picker][form-dump]   <script src={src!r}>", flush=True)

    # The server reads the HIDDEN #startDate2 input (slash format), NOT the
    # visible #weekStart text input. The jQuery UI datepicker normally syncs
    # both via setDate, but under patchright the plugin isn't always loaded
    # in time — so we set both inputs directly and skip the plugin entirely.
    # (Found via 2026-05-26 form-dump: both fields are part of the same
    # POST form to index.cfm; startDate2 is what the backend deserializes.)
    set_result = page.evaluate(
        """
        ({dash, slash}) => {
          const out = {tried: [], finalValues: {}};
          const visible = document.getElementById('weekStart');
          if (visible) {
            visible.removeAttribute('readonly');
            visible.value = dash;
            visible.dispatchEvent(new Event('change', {bubbles: true}));
            visible.dispatchEvent(new Event('blur',   {bubbles: true}));
            out.tried.push('#weekStart=' + dash);
            out.finalValues.weekStart = visible.value;
          }
          const hidden = document.getElementById('startDate2');
          if (hidden) {
            hidden.value = slash;
            hidden.dispatchEvent(new Event('change', {bubbles: true}));
            out.tried.push('#startDate2=' + slash);
            out.finalValues.startDate2 = hidden.value;
          } else {
            out.tried.push('NO #startDate2 hidden input on page');
          }
          return out;
        }
        """,
        {"dash": formatted_dash, "slash": formatted_slash},
    )
    print(f"[picker] setDate result: tried={set_result.get('tried')} "
          f"finalValues={set_result.get('finalValues')}",
          flush=True)
    after = page.locator("#weekStart").input_value()
    print(f"[picker] AFTER setDate, BEFORE submit: input_value={after!r}", flush=True)

    with page.expect_navigation(timeout=15000, wait_until="load"):
        page.locator('input[name="submit"][type="submit"]').first.click()
    post_nav = page.locator("#weekStart").input_value()
    print(f"[picker] AFTER submit/navigation: input_value={post_nav!r} url={page.url[:120]}",
          flush=True)


def _ensure_on_retention_report(page: Page) -> None:
    """If we got bumped off the retention report after switch, navigate back."""
    if RETENTION_REPORT_PAGE in page.url:
        return
    # Find the rqst token in the current URL and reuse it
    m = re.search(r"rqst=([A-Z0-9-]+)", page.url, re.I)
    if not m:
        raise RuntimeError(f"Cannot find rqst token in URL: {page.url}")
    rqst = m.group(1)
    new_url = f"https://applicantstream.com/index.cfm?rqst={rqst}&p=701"
    page.goto(new_url, wait_until="load")


def _scrape_metrics(page: Page) -> Dict[str, Optional[float]]:
    """Read the Retention Report; return parsed values for every metric."""
    # The big retention table is index 1. The "View Details" tooltip data for
    # Removed-From-Process-Emails appears as separate small tables (1 row, 2
    # cells each) elsewhere on the page — we use them to compute Duplicate %.
    payload = page.evaluate(
        """
        () => {
          const tables = document.querySelectorAll('table');
          if (tables.length < 2) return null;

          // Main retention table: rows of [label, ..., weekly_total]
          const main = [];
          tables[1].querySelectorAll('tr').forEach(tr => {
            const cells = tr.querySelectorAll('th, td');
            if (cells.length < 2) return;
            const first = (cells[0].innerText || '').trim();
            const last  = (cells[cells.length - 1].innerText || '').trim();
            main.push([first, last]);
          });

          // Small 1-row reason-tooltip tables (skip the first 2 tables which
          // are header + main).
          const reasons = [];
          tables.forEach((t, i) => {
            if (i < 2) return;
            const trs = t.querySelectorAll('tr');
            if (trs.length !== 1) return;
            const cells = trs[0].querySelectorAll('td, th');
            if (cells.length !== 2) return;
            reasons.push([
              (cells[0].innerText || '').trim(),
              (cells[1].innerText || '').trim(),
            ]);
          });

          return {main, reasons};
        }
        """
    )
    if payload is None:
        return {}

    label_to_value = {label: value for label, value in payload["main"] if label and value}

    def _lookup(needle: str) -> Optional[str]:
        """Find a value by row label. Tries exact match, then a startswith
        match (the AS report appends 'View Details' link text to some rows)."""
        if needle in label_to_value:
            return label_to_value[needle]
        for label, value in label_to_value.items():
            if label.startswith(needle):
                return value
        return None

    parsed: Dict[str, Optional[float]] = {}
    for metric_key, meta in METRICS.items():
        if meta["type"] == "derived":
            continue
        raw = _lookup(meta["as_label"])
        parsed[metric_key] = _parse_value(raw, meta["type"]) if raw is not None else None

    # Compute derived metrics. Dict iteration order respects insertion order
    # (Python 3.7+), so deps must be defined before dependents in METRICS.
    for metric_key, meta in METRICS.items():
        if meta["type"] != "derived":
            continue
        derived = meta["derived"]
        if isinstance(derived, tuple):
            num_key, den_key = derived
            n, d = parsed.get(num_key), parsed.get(den_key)
            if n is None or d is None:
                parsed[metric_key] = None
            elif not d:  # divide-by-zero — show 0% rather than blank
                parsed[metric_key] = 0
            else:
                parsed[metric_key] = round((n / d) * 100)
        elif derived == "sum_sent_manual":
            n, m = parsed.get("sent_to_call_list"), parsed.get("manual_apps_entry")
            parsed[metric_key] = int((n or 0) + (m or 0)) if (n is not None or m is not None) else None
        elif derived == "sum_pull_removed":
            p, r = parsed.get("pull"), parsed.get("removed_from_process_emails")
            parsed[metric_key] = int((p or 0) + (r or 0)) if (p is not None or r is not None) else None
        else:
            parsed[metric_key] = None
    return parsed


def _parse_value(raw: str, type_: str) -> Optional[float]:
    """Parse an AS cell. Empty / '-' / unparseable values are treated as 0
    rather than None, so the corresponding Sheet cell shows '0' / '0%' instead
    of staying blank. Use None only when truly unrecoverable (label missing)."""
    raw = raw.strip()
    if type_ == "percent":
        m = re.search(r"-?\d+(\.\d+)?", raw.replace(",", ""))
        return float(m.group()) if m else 0
    # count
    raw = raw.replace(",", "")
    if raw == "" or raw == "-":
        return 0
    try:
        return int(raw) if "." not in raw else float(raw)
    except ValueError:
        return 0


def fetch_one(page: Page, office_id: str, owner_hint: str, week_start: dt.date) -> Dict[str, Optional[float]]:
    """Switch to one office + week and return the 19 weekly-total metrics."""
    if not _switch_office(page, office_id, owner_hint):
        return {}
    _ensure_on_retention_report(page)
    _set_week_and_submit(page, week_start)
    page.wait_for_timeout(500)
    return _scrape_metrics(page)


# Day index in the AS retention table (0-indexed within row cells).
# Cell 0 = label, cells 1-7 = Sun..Sat, cell 8 = Weekly Total.
AS_DAY_CELL_INDEX = {
    "sunday": 1, "monday": 2, "tuesday": 3, "wednesday": 4,
    "thursday": 5, "friday": 6, "saturday": 7,
}


def _scrape_metrics_per_day(page: Page) -> Dict[str, Dict[str, Optional[float]]]:
    """Scrape the AS Retention Report and return per-day values per metric.
    Returns {metric_key: {"monday": value, "tuesday": value, ...}}."""
    payload = page.evaluate(
        """
        () => {
          const tables = document.querySelectorAll('table');
          if (tables.length < 2) return null;
          const main = [];
          tables[1].querySelectorAll('tr').forEach(tr => {
            const cells = tr.querySelectorAll('th, td');
            if (cells.length < 2) return;
            main.push(Array.from(cells).map(c => (c.innerText || '').trim()));
          });
          return main;
        }
        """
    )
    if payload is None:
        return {}

    label_to_cells: Dict[str, list] = {}
    for row in payload:
        if not row:
            continue
        label = row[0]
        if label and label not in label_to_cells:
            label_to_cells[label] = row

    def _lookup(needle: str):
        if needle in label_to_cells:
            return label_to_cells[needle]
        for label, cells in label_to_cells.items():
            if label.startswith(needle):
                return cells
        return None

    result: Dict[str, Dict[str, Optional[float]]] = {}
    for metric_key, meta in METRICS.items():
        if meta["type"] == "derived":
            continue
        cells = _lookup(meta["as_label"])
        per_day: Dict[str, Optional[float]] = {}
        for day, idx in AS_DAY_CELL_INDEX.items():
            if cells and idx < len(cells):
                per_day[day] = _parse_value(cells[idx], meta["type"])
            else:
                per_day[day] = None
        result[metric_key] = per_day

    # Compute derived per-day from raw per-day values (same formulas as weekly)
    for metric_key, meta in METRICS.items():
        if meta["type"] != "derived":
            continue
        derived = meta["derived"]
        per_day = {}
        for day in AS_DAY_CELL_INDEX:
            if isinstance(derived, tuple):
                num_key, den_key = derived
                n = result.get(num_key, {}).get(day)
                d = result.get(den_key, {}).get(day)
                if n is None or d is None:
                    per_day[day] = None
                elif not d:
                    per_day[day] = 0
                else:
                    per_day[day] = round((n / d) * 100)
            elif derived == "sum_sent_manual":
                n = result.get("sent_to_call_list", {}).get(day)
                m = result.get("manual_apps_entry", {}).get(day)
                per_day[day] = int((n or 0) + (m or 0)) if (n is not None or m is not None) else None
            elif derived == "sum_pull_removed":
                p = result.get("pull", {}).get(day)
                r = result.get("removed_from_process_emails", {}).get(day)
                per_day[day] = int((p or 0) + (r or 0)) if (p is not None or r is not None) else None
            else:
                per_day[day] = None
        result[metric_key] = per_day
    return result


def fetch_one_daily(page: Page, office_id: str, owner_hint: str, week_start: dt.date):
    """Like fetch_one but returns per-day breakdown instead of weekly totals.
    Returns {} if office not accessible."""
    if not _switch_office(page, office_id, owner_hint):
        return {}
    _ensure_on_retention_report(page)
    _set_week_and_submit(page, week_start)
    page.wait_for_timeout(500)
    return _scrape_metrics_per_day(page)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--office-id", required=True)
    ap.add_argument("--owner", default="", help="for log messages")
    ap.add_argument("--week-start", required=True, help="Sunday at start of week, YYYY-MM-DD")
    args = ap.parse_args()
    week_start = dt.date.fromisoformat(args.week_start)

    p, browser, page = _attach()
    try:
        result = fetch_one(page, args.office_id, args.owner, week_start)
    finally:
        p.stop()
    print(json.dumps(result, indent=2, default=str))
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
