#!/usr/bin/env python3
"""Removed Apps at Processing — read the removals for a date range, and restore them.

WHY THIS EXISTS (Carlos, 2026-08-27): applicants that a human "removes" from the
processing queue land on the classic ApplicantStream page **Applicants -> Removed
Apps at Processing**. Carlos's suspicion is that some of those removals are
lazy — the person clicked Remove instead of working the applicant — so the
applicant never reached the AI call list even though nothing about them was
actually un-sendable. This module makes that testable: pull the removals for a
day, RESTORE them, and let the normal Applicant Push (`applicant_push --office
<id> --live`) walk them. Whatever the push then does to each one -- send_ai /
override_send_ai / remove_duplicate / flag_no_phone -- is the ground truth for
whether the original removal was justified.

SAFETY. A restore is a real mutation, so:
  * DRY-RUN IS THE DEFAULT. Plain run reads the table, writes it to a Sheet tab
    and clicks nothing.
  * ``--live`` is required to click Restore, and ``--limit N`` bounds it.
  * A restore is the SAFE direction of this pair: it puts an applicant BACK in
    the queue, where the push re-decides them. It never deletes anything.

Runs on Lucy 2, on the same warm real-Chrome/CDP AppStream session the push uses
(``resume_pushing.warm_appstream_cdp_page``) — so no separate login, and the
office switch is the one ``applicant_push.offices`` already declares.

  lucy rerun restore_removed --office 23467 --start 08/24/2026 --debug
  lucy rerun restore_removed --office 23467 --start 08/24/2026          # dry-run
  lucy rerun restore_removed --office 23467 --start 08/24/2026 --live
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

import argparse
import datetime as dt
import re
import sys

from automations.resume_pushing import run as rp
from automations.applicant_push import offices
from automations.oat_processing.run import attach_dialog_accept

BASE = "https://applicantstream.com/index.cfm"
# Confirmed on Lucy 2, office 23467, 2026-08-27: Applicants -> "Removed Apps at
# Processing" is index.cfm?p=605 (the menu link carries it). Kept as the fallback
# for the direct nav; the menu label is still what we look for first.
PAGE_ID = "605"

# The nav label, as it reads in the Applicants menu.
PAGE_LABEL_RE = re.compile(r"removed\s+apps?\s+at\s+processing", re.I)
# Looser, for the submit button / any link that mentions removed apps.
REMOVED_RE = re.compile(r"removed\s+apps?", re.I)


def _log(msg: str) -> None:
    rp._log(msg)


def _token(page) -> str:
    """The session's rqst token. Hyphens are PART of the token — a
    [A-Za-z0-9]+ regex truncates it and every later page answers 'Your login is
    timed out', which reads like an auth failure but is a bad URL."""
    m = re.search(r"rqst=([A-Za-z0-9\-]+)", page.url or "")
    if m:
        return m.group(1)
    href = page.evaluate(
        "() => (Array.from(document.querySelectorAll('a[href*=rqst]'))[0]||{})"
        ".href || ''")
    m = re.search(r"rqst=([A-Za-z0-9\-]+)", href or "")
    return m.group(1) if m else ""


# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #
def find_removed_page(page):
    """Locate 'Removed Apps at Processing' under the Applicants menu.

    Returns the page id (e.g. '618') if we can read it off the link, else "".
    Label-first (same approach as oat.open_oat) because we have the LABEL from
    Carlos, not the p= number."""
    for how in ("hover", "click"):
        try:
            loc = page.locator(
                "xpath=//a[normalize-space(.)='Applicants'] "
                "| //*[self::button or @role='button']"
                "[normalize-space(.)='Applicants']").first
            if loc.count() == 0:
                break
            getattr(loc, how)(timeout=5000)
            page.wait_for_timeout(800)
        except Exception:  # noqa: BLE001
            pass

    links = page.evaluate(
        "() => Array.from(document.querySelectorAll('a')).map(a => ["
        "  (a.innerText||a.textContent||'').trim(),"
        "  a.getAttribute('href')||'',"
        "  a.getAttribute('onclick')||'' ])")
    for text, href, onclick in links:
        if PAGE_LABEL_RE.search(text or ""):
            m = re.search(r"[?&]p=(\d+)", (href or "") + " " + (onclick or ""))
            _log(f"[rm] menu link '{text[:50]}' -> href={href[:90]!r} "
                 f"onclick={onclick[:60]!r}")
            return m.group(1) if m else ""
    _log("[rm] no 'Removed Apps at Processing' link found in the nav")
    return ""


def open_removed_page(page, page_id: str = "") -> bool:
    """Land on the Removed-Apps page: click the menu link, else direct-nav to its
    p= id carrying the session token."""
    try:
        loc = page.locator(
            "xpath=//a[contains(translate(normalize-space(.),"
            "'REMOVEDAPSTPOCING','removedapstpocing'),'removed apps')]").first
        if loc.count() > 0:
            loc.click(timeout=12000)
            page.wait_for_timeout(2500)
            if page_id and f"p={page_id}" in (page.url or ""):
                return True
            if REMOVED_RE.search(page.inner_text("body")[:4000]):
                return True
    except Exception as e:  # noqa: BLE001
        _log(f"[rm] menu click miss ({type(e).__name__})")

    if not page_id:
        return False
    tok = _token(page)
    if not tok:
        _log("[rm] no rqst token — cannot direct-nav")
        return False
    for _ in range(2):
        try:
            page.goto(f"{BASE}?p={page_id}&rqst={tok}",
                      wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            if f"p={page_id}" in (page.url or ""):
                return True
        except Exception:  # noqa: BLE001
            page.wait_for_timeout(1500)
    return False


# --------------------------------------------------------------------------- #
# Discovery (--debug)
# --------------------------------------------------------------------------- #
def dump_page(page, tag: str = "") -> None:
    """Print every control + table header on the current page, so the selectors
    below can be confirmed (or fixed) from one remote pass. The Result cell
    truncates hard, so this goes to the log + the diag tab, not the cell."""
    _log(f"[dump]{tag} url: {(page.url or '')[:140]}")
    try:
        ctrls = page.evaluate(
            "() => Array.from(document.querySelectorAll("
            "'input,select,textarea,button')).map(e => ["
            "  e.tagName, e.type||'', e.name||'', e.id||'',"
            "  (e.value||'').slice(0,40),"
            "  (e.innerText||'').trim().slice(0,40),"
            "  e.offsetParent === null ? 'hidden' : 'vis' ])")
        _log(f"[dump]{tag} {len(ctrls)} control(s):")
        for c in ctrls:
            _log("[dump]   " + " | ".join(str(x) for x in c))
    except Exception as e:  # noqa: BLE001
        _log(f"[dump]{tag} controls err: {e}")
    try:
        tables = page.evaluate(
            "() => Array.from(document.querySelectorAll('table')).map((t,i) => ({"
            "  i, id: t.id||'', rows: t.rows.length,"
            "  head: Array.from((t.rows[0]||{cells:[]}).cells)"
            "          .map(c => (c.innerText||'').trim().slice(0,26)),"
            "  first: Array.from((t.rows[1]||{cells:[]}).cells)"
            "          .map(c => (c.innerText||'').trim().slice(0,26)) }))")
        _log(f"[dump]{tag} {len(tables)} table(s):")
        for t in tables:
            if t["rows"] < 2:
                continue
            _log(f"[dump]   table#{t['i']} id={t['id']!r} rows={t['rows']}")
            _log(f"[dump]     head : {t['head']}")
            _log(f"[dump]     row1 : {t['first']}")
    except Exception as e:  # noqa: BLE001
        _log(f"[dump]{tag} tables err: {e}")


# --------------------------------------------------------------------------- #
# The date filter
# --------------------------------------------------------------------------- #
def _fill_date_inputs(page, start: str, end: str) -> int:
    """Fill the start/end date filter.

    AppStream's report forms pair a VISIBLE mm-dd-yyyy field with a HIDDEN
    mm/dd/yyyy twin (``startDate`` + ``startDate2`` on the Source Report, p=702)
    and the server reads the hidden one — so filling only what you can see
    silently returns the default range. Fill BOTH, matching on name/id rather
    than position, and fire change/blur so any datepicker syncs."""
    filled = 0
    ctrls = page.evaluate(
        "() => Array.from(document.querySelectorAll('input')).map(e => ["
        "  e.name||'', e.id||'', e.type||'' ])")
    for name, eid, typ in ctrls:
        key = (name + " " + eid).lower()
        if typ in ("checkbox", "radio", "submit", "button"):
            continue
        if not re.search(r"date", key):
            continue
        if re.search(r"start|from|begin", key):
            val = start
        elif re.search(r"end|thru|through|to\b|stop", key):
            val = end
        else:
            continue
        # The "2" twin takes slashes, the visible one dashes (p=702 convention).
        use = val.replace("-", "/") if key.rstrip().endswith("2") else val
        sel = f"#{eid}" if eid else f"input[name='{name}']"
        try:
            page.evaluate(
                "([s, v]) => { const e = document.querySelector(s); if (!e) return;"
                "  e.value = v;"
                "  e.dispatchEvent(new Event('input',  {bubbles:true}));"
                "  e.dispatchEvent(new Event('change', {bubbles:true}));"
                "  e.dispatchEvent(new Event('blur',   {bubbles:true})); }",
                [sel, use])
            _log(f"[rm] date field {sel} = {use}")
            filled += 1
        except Exception as e:  # noqa: BLE001
            _log(f"[rm] could not set {sel}: {type(e).__name__}")
    return filled


def _click_removed_apps_button(page) -> bool:
    """Click the 'Removed Apps' submit that loads the filtered list."""
    for sel in ("xpath=//input[@type='submit' or @type='button']"
                "[contains(translate(@value,'REMOVEDAPS','removedaps'),"
                "'removed apps')]",
                "xpath=//button[contains(translate(normalize-space(.),"
                "'REMOVEDAPS','removedaps'),'removed apps')]",
                "xpath=//a[contains(translate(normalize-space(.),"
                "'REMOVEDAPS','removedaps'),'removed apps')]"):
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.click(timeout=12000)
                page.wait_for_timeout(4000)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(1500)
                _log(f"[rm] clicked the Removed-Apps submit ({sel[:40]}…)")
                return True
        except Exception as e:  # noqa: BLE001
            _log(f"[rm] submit click miss: {type(e).__name__}")
    _log("[rm] no 'Removed Apps' submit control found")
    return False


# --------------------------------------------------------------------------- #
# Restore-mechanism probe (--debug)
# --------------------------------------------------------------------------- #
def probe_restore_mechanism(page) -> None:
    """Print EXACTLY how a restore works on this page: every control whose
    value/text/title mentions 'restore' (with name/id/type/form/row), every form's
    action, and every inline-script snippet around the word 'restore' — the
    ColdFusion pages do their work in a page-local JS function, and calling THAT
    is far more robust than clicking at its UI."""
    try:
        ctrls = page.evaluate(
            """() => Array.from(document.querySelectorAll('a, input, button'))
              .filter(e => /restore/i.test(
                  (e.innerText || e.value || e.title || '').trim()))
              .map(e => ({ tag: e.tagName, type: e.type || '',
                  name: e.name || '', id: e.id || '',
                  value: (e.value || '').slice(0, 30),
                  cls: (e.className || '').slice(0, 40),
                  onclick: (e.getAttribute('onclick') || '').slice(0, 200),
                  form: e.form ? (e.form.name || e.form.id ||
                                  (e.form.action || '').slice(-60)) : '',
                  row: (e.closest('tr') || {}).rowIndex }))""")
        _log(f"[probe] {len(ctrls)} restore control(s)")
        for c in ctrls[:6]:
            _log("[probe] ctrl " + " | ".join(
                f"{k}={c[k]!r}" for k in
                ("tag", "type", "name", "id", "value", "cls", "onclick",
                 "form", "row")))
    except Exception as e:  # noqa: BLE001
        _log(f"[probe] ctrl read err: {e}")
    try:
        forms = page.evaluate(
            """() => Array.from(document.forms).map(f => ({
                name: f.name || '', id: f.id || '',
                action: (f.action || '').slice(-80), method: f.method }))""")
        for f in forms:
            _log(f"[probe] form {f}")
    except Exception as e:  # noqa: BLE001
        _log(f"[probe] forms err: {e}")
    try:
        hits = page.evaluate(
            """() => { const txt = Array.from(document.scripts)
                  .map(s => s.textContent || '').join('\n');
               return (txt.match(/.{0,80}restore.{0,220}/gi) || [])
                  .slice(0, 12); }""")
        _log(f"[probe] {len(hits)} script mention(s) of 'restore'")
        for h in hits:
            _log("[probe] js: " + " ".join(h.split())[:300])
    except Exception as e:  # noqa: BLE001
        _log(f"[probe] scripts err: {e}")


# --------------------------------------------------------------------------- #
# The results table
# --------------------------------------------------------------------------- #
# The columns Carlos asked to capture. Matched against the real header text by
# substring so a wording difference ("Remove Date" vs "Removed Date") still maps.
WANT = ["applicant", "email", "phone", "remove date", "job board", "job posting",
        "removed by", "removed reason", "resume"]


def _results_table(page):
    """The table holding the removals: the one whose header mentions BOTH an
    applicant/name column and a remove-date column. Picking by content, not by
    index, because the classic pages carry layout tables too."""
    tables = page.evaluate(
        "() => Array.from(document.querySelectorAll('table')).map((t,i) => ({"
        "  i, rows: t.rows.length,"
        "  head: Array.from((t.rows[0]||{cells:[]}).cells)"
        "          .map(c => (c.innerText||'').trim()) }))")
    best, best_score = None, 0
    for t in tables:
        head = " | ".join(t["head"]).lower()
        score = sum(1 for w in WANT if w in head)
        if t["rows"] >= 2 and score > best_score:
            best, best_score = t, score
    if best:
        _log(f"[rm] results table = #{best['i']} ({best['rows']} rows, "
             f"{best_score}/{len(WANT)} wanted columns matched)")
        _log(f"[rm] header: {best['head']}")
    return best


def scrape_rows(page):
    """Return (header, rows) for the removals table — every cell as text, plus a
    trailing 'resume' link href when the cell holds one."""
    t = _results_table(page)
    if not t:
        _log("[rm] no results table on the page")
        return [], []
    data = page.evaluate(
        "(i) => { const t = document.querySelectorAll('table')[i];"
        "  return Array.from(t.rows).map(r => Array.from(r.cells).map(c => {"
        "    const a = c.querySelector('a[href]');"
        "    const txt = (c.innerText||'').trim();"
        "    return (a && /resume|view|\\.pdf|\\.doc/i.test(txt + a.href))"
        "      ? (txt + ' <' + a.href + '>') : txt; })); }", t["i"])
    if not data:
        return [], []
    header, rows = data[0], [r for r in data[1:] if any(c.strip() for c in r)]
    # Drop a trailing "no records" pseudo-row and any repeated header.
    rows = [r for r in rows
            if not re.match(r"^\s*(no records|total)", " ".join(r), re.I)]
    _log(f"[rm] scraped {len(rows)} removal row(s)")
    return header, rows


def write_sheet(tab: str, header, rows, meta: str) -> None:
    """Publish the scrape to a Sheet tab — the poller Result cell truncates, and
    this table is the deliverable, so it must land somewhere readable."""
    try:
        from automations.recruiting_report import fill as _fill
        sh = _fill._client().open_by_key(
            "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
        try:
            ws = sh.worksheet(tab)
        except Exception:  # noqa: BLE001
            ws = sh.add_worksheet(title=tab, rows=400,
                                  cols=max(12, len(header) + 2))
        ws.clear()
        body = [[meta]] + [list(header)] + [list(r) for r in rows]
        width = max(len(r) for r in body)
        body = [r + [""] * (width - len(r)) for r in body]
        ws.update(body, "A1", value_input_option="RAW")
        _log(f"[rm] wrote {len(rows)} row(s) + header to the '{tab}' tab")
    except Exception as e:  # noqa: BLE001
        _log(f"[rm] sheet write failed: {type(e).__name__}: {e}")


# --------------------------------------------------------------------------- #
# Restore
# --------------------------------------------------------------------------- #
# The Restore control lives in the last cell of each row. It is NOT reliably
# click-actionable through Playwright: the first live attempt (2026-08-27) found
# the anchors but timed out at 12s on .click(), which is the classic
# ColdFusion-table signature — the cell is zero-height / off-viewport / covered,
# so Playwright waits forever for a stable box that never arrives. We therefore
# read each control's href+onclick in JS and DRIVE IT IN JS, which runs the same
# handler the page would and skips the actionability wait entirely.
# CRACKED 2026-08-27 (probe + live run on the mini): each row's Restore is an
# <a class="restore-applicant"> anchor — jQuery-bound, NO href/onclick — inside
# form frmRmvAppPE. One JS click per anchor restores that row (anchors 42 -> 0,
# verified by an empty re-filter). THE TRAP that burned the first two passes:
# matching /restore/i on TEXT grabs the hidden #reportDataXL input first (its
# report-export blob contains the word "restore"), so the click hit a hidden
# input and nothing happened. Match the class, never the text.
_RESTORE_JS = """
() => Array.from(document.querySelectorAll('a.restore-applicant'))
  .map(e => ({
      tag: e.tagName,
      href: e.getAttribute('href') || '',
      onclick: (e.getAttribute('onclick') || '').slice(0, 160),
      text: (e.innerText || '').trim().slice(0, 20),
      row: (e.closest('tr') || {}).rowIndex,
      name: (((e.closest('tr') || {cells: []}).cells[0] || {}).innerText
             || '').trim().slice(0, 40) }))
"""


def _restore_controls(page):
    """Describe every Restore control on the page (tag / href / onclick / the row's
    applicant name), in document order."""
    try:
        return page.evaluate(_RESTORE_JS) or []
    except Exception as e:  # noqa: BLE001
        _log(f"[rm] could not read restore controls: {type(e).__name__}: {e}")
        return []


def _click_restore_js(page) -> bool:
    """Click the FIRST Restore control via JS. Returns False when there is none
    left — which is how the loop knows it is finished."""
    try:
        return bool(page.evaluate(
            """() => { const el = document.querySelector('a.restore-applicant');
               if (!el) return false;
               el.scrollIntoView({block: 'center'});
               el.click();
               return true; }"""))
    except Exception as e:  # noqa: BLE001
        _log(f"[rm] JS restore click err: {type(e).__name__}: {str(e)[:120]}")
        return False


def restore_all(page, expected: int, limit: int = 0) -> int:
    """Click Restore on every row.

    Re-reads the control list after EACH click: a restore takes that row off the
    list, so a cached list of handles goes stale immediately and index-based
    iteration would skip every other row. Loops until no Restore control is left
    (or the safety bound), which is also the completion proof."""
    ctrls = _restore_controls(page)
    _log(f"[rm] {len(ctrls)} Restore control(s) on the page")
    if ctrls:
        c = ctrls[0]
        _log(f"[rm] control shape: tag={c['tag']} href={c['href'][:80]!r} "
             f"onclick={c['onclick'][:80]!r} row={c['row']} "
             f"name={(c['name'] or '').strip()[:30]!r}")

    done = 0
    bound = (limit or expected or 0) + 5      # +5 for pagination/re-render slack
    for _ in range(max(bound, 1)):
        if limit and done >= limit:
            _log(f"[rm] --limit {limit} reached — stopping")
            break
        before = len(_restore_controls(page))
        if before == 0:
            _log("[rm] no Restore controls left on the page")
            break
        if not _click_restore_js(page):
            _log("[rm] restore click found no control — stopping")
            break
        page.wait_for_timeout(1200)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=20000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1200)
        after = len(_restore_controls(page))
        done += 1
        _log(f"[rm] restore {done}: controls {before} -> {after}")
        if after >= before:
            # The click ran but nothing left the list. Either the restore did not
            # take, or this page re-renders the full list every time — either way,
            # grinding the same first row `expected` times would be a lie in the
            # log, so stop and say so.
            _log("[rm] WARNING: the list did not shrink after a restore — "
                 "stopping rather than re-clicking the same row")
            break
    return done


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def run(office: str, start: str, end: str = "", live: bool = False,
        limit: int = 0, debug: bool = False, tab: str = "") -> int:
    o = offices.activate(office)
    # A DEDICATED Chrome profile + port, NOT the office's own. The scheduled
    # applicant-push fires every 5 min and each office's run pkills `-f` its own
    # profile marker on start and again on teardown — so sharing the office's
    # profile would mean this utility and a live walk killing each other's Chrome
    # mid-action. Port 9248 is past the office table's 9245/9247 and past the
    # 9246 that resume_pushing's one-off --office override claims.
    rp.CDP_PROFILE = "/tmp/rp_cdp_restore"
    rp.CDP_PORT = "9248"
    rp._CDP_KILL_PAT = "rp_cdp_restore"
    rp._CDP_SEED_MARKER = rp.CDP_PROFILE + "/.rp_seeded"
    end = end or start
    tab = tab or f"Removed Apps {office}"
    mode = "LIVE (will click Restore)" if live else "DRY-RUN (read only)"
    rp._LOG_BUFFER.clear()
    _log(f"[rm] Removed Apps at Processing — {o['label']} — {start} to {end} — "
         f"{mode}")

    rc = {"code": 1}

    def _work(page, ctx, net):
        attach_dialog_accept(page)            # AppStream confirms Restore
        pid = find_removed_page(page) or PAGE_ID
        if not open_removed_page(page, pid):
            _log("[rm][STOP] could not open the Removed-Apps page")
            if debug:
                dump_page(page, " nav-fail")
            return 2
        _log(f"[rm] on the removed-apps page: {(page.url or '')[:120]}")
        if debug:
            dump_page(page, " before-filter")

        _fill_date_inputs(page, start, end)
        if not _click_removed_apps_button(page):
            if debug:
                dump_page(page, " no-submit")
            return 3
        if debug:
            dump_page(page, " after-filter")

        if debug:
            probe_restore_mechanism(page)
        header, rows = scrape_rows(page)
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        write_sheet(tab, header, rows,
                    f"{o['label']} · removed {start}–{end} · scraped {stamp} · "
                    f"{len(rows)} row(s) · {'LIVE' if live else 'DRY-RUN'}")
        for r in rows:                        # also into the log, for logtail
            _log("[row] " + " | ".join(c[:40] for c in r))

        if not live:
            _log(f"[rm] DRY-RUN — would restore {len(rows)} applicant(s); "
                 "nothing clicked")
            return 0
        n = restore_all(page, expected=len(rows), limit=limit)
        _log(f"[rm] ===== RESTORED {n} of {len(rows)} =====")
        # Re-read the filtered list as the proof: a real restore takes the row
        # OFF this page, so a non-empty list here means some did not take.
        if _click_removed_apps_button(page):
            _, after = scrape_rows(page)
            _log(f"[rm] still showing as removed for {start}: {len(after)} "
                 f"(expected 0 if every restore took)")
            for r in after:
                _log("[left] " + " | ".join(c[:40] for c in r))
        return 0

    try:
        with rp.warm_appstream_cdp_page(diag_tab=o["push_diag_tab"]) as (
                page, ctx, net):
            rc["code"] = _work(page, ctx, net)
    except rp.AppStreamLoginFailed as e:
        _log(f"[rm][STOP] no AppStream session: {e}")
        return 2
    return rc["code"] or 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Read / restore 'Removed Apps at Processing' for one office")
    p.add_argument("--office", default="23467", choices=sorted(offices.OFFICES),
                   help="ApplicantStream office (default %(default)s = Atef)")
    p.add_argument("--start", required=True, help="start date, mm-dd-yyyy")
    p.add_argument("--end", default="", help="end date (default: same as --start)")
    p.add_argument("--live", action="store_true",
                   help="actually click Restore (default: read + report only)")
    p.add_argument("--dry-run", action="store_true", help="explicit dry-run")
    p.add_argument("--limit", type=int, default=0,
                   help="restore at most N (0 = all)")
    p.add_argument("--debug", action="store_true",
                   help="dump the page's controls + tables (selector discovery)")
    p.add_argument("--tab", default="", help="Sheet tab for the scrape")
    a = p.parse_args(argv)
    return run(office=a.office, start=a.start, end=a.end,
               live=a.live and not a.dry_run, limit=a.limit, debug=a.debug,
               tab=a.tab)


if __name__ == "__main__":
    sys.exit(main())
