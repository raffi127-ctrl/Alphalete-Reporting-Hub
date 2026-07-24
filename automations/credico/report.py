"""Credico Sales Management → Reports pull for the DD Bulletin. RUNS ON LUCY 1.

Credico is the second DD source: its direct deposits are ADDED to each owner's
weekly figure (override_bulletin/DD_SOURCES.md). Two things about it bite:

  * THE DATE RUNS ONE WEEK FORWARD. Week ending 3.22 is pulled as Saturday the
    28th. `dd_rows.credico_saturday()` owns that rule — never hand-pick a date.
  * IT REPORTS BY COMPANY, not by person (`Able Acquisitions` → Abel Draper).
    Those owners are often missing from the main DD list entirely and have to be
    ADDED, so an unmapped company is somebody's money going missing. Nothing is
    dropped silently — `dd_rows.to_owners()` returns what it couldn't place.

Row cleanup (LEDGER rows, blank-name continuation rows, +/- cancellation pairs)
is shared with the Tableau crosstab and lives in `override_bulletin/dd_rows.py`.

STATUS: the session + date + parse + merge path are done and tested. The page
extraction is NOT — nobody has looked at the Reports screen yet, and guessing
selectors for an SPA is how these break silently. Run discovery first, ON LUCY 1
(that is where the saved Credico session lives):

    python -m automations.credico.report --discover

`lucy rerun credico_check` already verifies the session. There is no
`credico_discover` lucy action yet — adding one is a copy of the `credico_check`
block in day_orchestrator/schedule_config.json with this module and `--discover`.

It dumps the screen's structure to stdout AND to the `_credico_discover` tab of
the override workbook, so the result is readable from any machine — the same
pattern override_bulletin/discover.py uses.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from automations.credico.session import BASE, credico_session
from automations.override_bulletin.dd_rows import (credico_saturday, normalize,
                                                   summarize, to_owners)

REPORTS_URL = f"{BASE}/#/dashboard/sales-management"
WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
DUMP_TAB = "_credico_discover"
OUT = Path(__file__).resolve().parents[2] / "output" / "credico"


def discover(page=None, verbose=True):
    """Dump what the Reports screen actually offers — controls, tables, frames.

    Read-only. This exists so the extraction below is written against the real
    page instead of a guess."""
    rows = [["WHAT", "DETAIL", "SELECTOR / VALUE"]]

    def grab(pg, tag):
        rows.append(["url", tag, pg.url])
        for sel, what in (("a", "link"), ("button", "button"),
                          ("input", "input"), ("select", "select")):
            for el in pg.query_selector_all(sel)[:60]:
                try:
                    txt = " ".join((el.inner_text() or "").split())[:60]
                    if not txt and sel in ("input", "select"):
                        txt = (el.get_attribute("placeholder")
                               or el.get_attribute("name")
                               or el.get_attribute("type") or "")
                    if not txt:
                        continue
                    rows.append([what, txt, (el.get_attribute("href")
                                             or el.get_attribute("id")
                                             or el.get_attribute("class") or "")[:80]])
                except Exception:  # noqa: BLE001
                    continue
        for t in pg.query_selector_all("table")[:4]:
            hdr = [" ".join((h.inner_text() or "").split())
                   for h in t.query_selector_all("th")[:12]]
            if hdr:
                rows.append(["table-headers", tag, " | ".join(hdr)[:200]])

    own = page is None
    ctx = credico_session(headless=True) if own else None
    page = ctx.__enter__() if own else page
    try:
        page.goto(REPORTS_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        grab(page, "sales-management")
        for fr in page.frames[1:4]:              # SPAs often park the grid in a frame
            try:
                grab(fr, f"frame:{(fr.url or '')[:50]}")
            except Exception:  # noqa: BLE001
                continue
    finally:
        if own:
            ctx.__exit__(None, None, None)

    if verbose:
        for r in rows:
            print("  ".join(str(c)[:70].ljust(24) for c in r))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "discover.tsv").write_text(
        "\n".join("\t".join(str(c) for c in r) for r in rows), encoding="utf-8")
    try:
        _dump_to_sheet(rows)
        print(f"\n✓ {len(rows)} row(s) → '{DUMP_TAB}' tab + output/credico/discover.tsv")
    except Exception as e:  # noqa: BLE001
        print(f"\n⚠ couldn't write the '{DUMP_TAB}' tab ({e}) — the TSV is still on disk")
    return rows


def discover_deep(week_label="7.19.26", page=None, verbose=True):
    """Drive the controls and dump the grid they produce. READ-ONLY.

    The plain `--discover` pass sees only the empty form: Select Office, Select
    Campaign, a `.calendar` text input and a Load button (AngularJS). The rows
    only exist AFTER a Load, so this picks each office/campaign in turn, sets the
    Saturday, clicks Load and dumps what comes back. Clicking Load is a read —
    nothing on Credico is modified."""
    saturday = credico_saturday(week_label)
    rows = [["WHAT", "DETAIL", "VALUE"]]
    own = page is None
    ctx = credico_session(headless=True) if own else None
    page = ctx.__enter__() if own else page
    try:
        page.goto(REPORTS_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        sels = page.query_selector_all("select")
        opts = []
        for i, s in enumerate(sels):
            vals = [(o.get_attribute("value"), " ".join((o.inner_text() or "").split()))
                    for o in s.query_selector_all("option")]
            opts.append(vals)
            for v, t in vals:
                rows.append([f"select{i}-option", t, str(v)])
        for i, inp in enumerate(page.query_selector_all("input")):
            rows.append([f"input{i}", (inp.get_attribute("type") or "") + " " +
                         (inp.get_attribute("class") or "")[:40],
                         f"value={inp.get_attribute('value')!r} "
                         f"placeholder={inp.get_attribute('placeholder')!r}"])
        rows.append(["target-date", "computed one week forward",
                     f"{saturday:%Y-%m-%d} ({saturday:%m/%d/%Y})"])

        # WHY a select may be unreachable: the native <select> is hidden behind a
        # styled widget, or its panel is collapsed. select_option() waits for
        # visibility and times out. Record the evidence before working around it.
        for i, s in enumerate(sels):
            try:
                box = s.bounding_box()
                st = s.evaluate("""el => {
                    const c = getComputedStyle(el);
                    return [c.display, c.visibility, c.opacity,
                            el.offsetParent === null ? 'no-offsetParent' : 'ok',
                            (el.className||'').slice(0,60),
                            (el.parentElement ? el.parentElement.className : '').slice(0,60)].join(' ~ ');
                }""")
                rows.append([f"select{i}-visibility", str(box), st])
            except Exception as e:  # noqa: BLE001
                rows.append([f"select{i}-visibility", "ERROR", str(e)[:200]])
        for sel, what in (("a", "nav-link"), ("[ng-click]", "ng-click"),
                          (".nav-link,.nav-item,[role=tab]", "tab")):
            for el in page.query_selector_all(sel)[:40]:
                t = " ".join((el.inner_text() or "").split())[:60]
                if t:
                    rows.append([what, t, (el.get_attribute("ng-click")
                                           or el.get_attribute("href") or "")[:80]])
        body = " ".join((page.inner_text("body") or "").split())
        for i in range(0, min(len(body), 1600), 400):
            rows.append(["body-text", f"chars {i}", body[i:i + 400]])

        # THE PANEL IS HIDDEN UNTIL A REPORT IS CHOSEN. The selects report
        # display:block/visible but have no offsetParent and no bounding box, so
        # an ancestor is display:none. The nav shows why: a Reports list —
        # Fee Reports / Personal / CDF Report, each `r.getReport(report)` — and
        # the office/campaign/date form only appears after one is picked.
        def _set(el, value):
            """Set a <select> and tell Angular. select_option() needs the element
            visible; ng-model listens for a native change event, which a
            dispatched event satisfies even from patchright's isolated world."""
            el.evaluate("""(el, v) => {
                el.value = v;
                el.dispatchEvent(new Event('change', {bubbles: true}));
                el.dispatchEvent(new Event('input', {bubbles: true}));
            }""", value)

        def _dump_tables(tag):
            tables = page.query_selector_all("table")
            if not tables:
                # Credico renders the week's figures WITHOUT <table> — record the
                # real container structure and the text, or the parser is a guess.
                body = page.inner_text("body") or ""
                after = body.split("Fee Reports", 1)[-1]
                for i in range(0, min(len(after), 2400), 400):
                    rows.append(["  text", tag, after[i:i + 400].replace("\n", " ⏎ ")])
                for sel in ("[ng-repeat]", ".row", "ul li", "div[class*=grid]",
                            "div[class*=report]", "div[class*=col]"):
                    els = page.query_selector_all(sel)
                    for el in els[:6]:
                        t = " ".join((el.inner_text() or "").split())
                        if t and len(t) > 8:
                            rows.append([f"  {sel}", tag,
                                         f"[{len(els)} el] "
                                         f"cls={(el.get_attribute('class') or '')[:40]} "
                                         f"rpt={(el.get_attribute('ng-repeat') or '')[:40]} "
                                         f"| {t[:280]}"])
                dl = [b for b in page.query_selector_all("a, button")
                      if re.search(r"download|export|csv|excel|xls|pdf|print",
                                   ((b.inner_text() or "") + " " +
                                    (b.get_attribute("href") or "") + " " +
                                    (b.get_attribute("class") or "")), re.I)]
                for b in dl[:8]:
                    rows.append(["  download?", tag,
                                 f"{' '.join((b.inner_text() or '').split())[:40]} "
                                 f"href={(b.get_attribute('href') or '')[:90]} "
                                 f"ng-click={(b.get_attribute('ng-click') or '')[:60]}"])
                return
            for t in tables[:3]:
                hdr = [" ".join((h.inner_text() or "").split())
                       for h in t.query_selector_all("th")[:16]]
                if hdr:
                    rows.append(["  headers", tag, " | ".join(hdr)[:450]])
                for tr in t.query_selector_all("tbody tr")[:10]:
                    cells = [" ".join((td.inner_text() or "").split())
                             for td in tr.query_selector_all("td")[:16]]
                    if any(cells):
                        rows.append(["  row", tag, " | ".join(cells)[:450]])

        for label in ("Fee Reports", "Personal", "CDF Report"):
            try:
                # Opening one report replaces the list, so the other links are
                # gone by the next pass. goto() alone does NOT reset a hash-router
                # SPA already sitting on that URL (no navigation event fires) —
                # reload() does.
                page.goto(REPORTS_URL, wait_until="domcontentloaded")
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(5000)
                link = next((el for el in page.query_selector_all("[ng-click='r.getReport(report)']")
                             if label.lower() in (el.inner_text() or "").lower()), None)
                if link is None:
                    link = page.query_selector(f"a:has-text('{label}')")
                if link is None:
                    rows.append(["REPORT", label, "no link found"])
                    continue
                link.click()
                page.wait_for_timeout(4500)
                rows.append(["REPORT", label, f"opened — url {page.url}"])

                # The opened report lists WEEK DATES (Saturdays) as links. Record
                # them, then open the one matching our computed Saturday — that
                # is where the actual figures live.
                want = f"{saturday:%Y-%m-%d}"
                # no %-m: Windows strftime rejects it (cross-platform rule)
                alts = {f"{saturday:%m/%d/%Y}",
                        f"{saturday.month}/{saturday.day}/{saturday.year}"}
                date_els = []
                for el in page.query_selector_all("a, [ng-click], li, td"):
                    t = " ".join((el.inner_text() or "").split())
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}", t or ""):
                        date_els.append((t, el))
                rows.append(["  week-dates", label,
                             ", ".join(t for t, _ in date_els[:14])[:400]])
                # FEE REPORTS IS A FILE BROWSER: date → office → file. The office
                # names under a date are links to the week's file, so capture what
                # they point AT (href / ng-click / download attr) before fetching
                # anything. Nothing is downloaded here.
                def _dump_office_links(tag):
                    lst = page.query_selector("div.report-list")
                    if lst is None:
                        return
                    for el in lst.query_selector_all("a, [ng-click], li, span"):
                        t = " ".join((el.inner_text() or "").split())
                        if not t or len(t) > 60:
                            continue
                        rows.append(["  office-link", tag,
                                     f"{t} | tag={el.evaluate('e => e.tagName')} "
                                     f"href={(el.get_attribute('href') or '')[:120]} "
                                     f"ng-click={(el.get_attribute('ng-click') or '')[:80]} "
                                     f"download={el.get_attribute('download')!r} "
                                     f"cls={(el.get_attribute('class') or '')[:40]}"])

                hit = next((el for t, el in date_els if t == want or t in alts), None)
                if hit is not None:
                    hit.click()
                    page.wait_for_timeout(6000)
                    rows.append(["  opened-week", label, f"{want} — url {page.url}"])
                    _dump_office_links(f"{label} @ {want}")
                    _dump_tables(f"{label} @ {want}")
                elif date_els:
                    t0, el0 = date_els[0]
                    el0.click()
                    page.wait_for_timeout(6000)
                    rows.append(["  opened-week", label,
                                 f"{want} NOT in the list — opened {t0} to show the shape"])
                    _dump_tables(f"{label} @ {t0}")

                vis = []
                for s in page.query_selector_all("select"):
                    if s.bounding_box():
                        o = [(x.get_attribute("value"),
                              " ".join((x.inner_text() or "").split()))
                             for x in s.query_selector_all("option")]
                        vis.append(s)
                        rows.append(["  select(visible)", label,
                                     "; ".join(f"{t}={v}" for v, t in o)[:400]])
                for i, inp in enumerate(page.query_selector_all("input")):
                    if inp.bounding_box():
                        rows.append([f"  input{i}(visible)", label,
                                     f"type={inp.get_attribute('type')} "
                                     f"class={(inp.get_attribute('class') or '')[:50]} "
                                     f"value={inp.get_attribute('value')!r}"])
                for b in page.query_selector_all("button"):
                    if b.bounding_box():
                        rows.append(["  button(visible)", label,
                                     " ".join((b.inner_text() or "").split())[:60]])

                # drive the first office x first campaign for this report
                if len(vis) >= 2:
                    ov = next((o.get_attribute("value")
                               for o in vis[0].query_selector_all("option")
                               if o.get_attribute("value")), None)
                    cv = next((o.get_attribute("value")
                               for o in vis[1].query_selector_all("option")
                               if o.get_attribute("value")), None)
                    if ov and cv:
                        _set(vis[0], ov)
                        page.wait_for_timeout(800)
                        _set(vis[1], cv)
                        page.wait_for_timeout(800)
                        cal = next((i for i in page.query_selector_all("input[type=text]")
                                    if i.bounding_box()), None)
                        if cal:
                            cal.fill(f"{saturday:%m/%d/%Y}")
                            page.keyboard.press("Escape")
                        btn = next((b for b in page.query_selector_all("button")
                                    if b.bounding_box()
                                    and "load" in (b.inner_text() or "").lower()), None)
                        if btn:
                            btn.click()
                            page.wait_for_timeout(7000)
                        rows.append(["  LOADED", label, f"office={ov} campaign={cv} "
                                     f"date={saturday:%m/%d/%Y}"])
                _dump_tables(label)
            except Exception as e:  # noqa: BLE001
                rows.append(["  ERROR", label, f"{type(e).__name__}: {e}"[:300]])
    finally:
        if own:
            ctx.__exit__(None, None, None)

    if verbose:
        for r in rows:
            print(" | ".join(str(c)[:120] for c in r))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "discover_deep.tsv").write_text(
        "\n".join("\t".join(str(c) for c in r) for r in rows), encoding="utf-8")
    try:
        _dump_to_sheet(rows)
        print(f"\n✓ {len(rows)} row(s) → '{DUMP_TAB}' tab")
    except Exception as e:  # noqa: BLE001
        print(f"\n⚠ couldn't write '{DUMP_TAB}' ({e}) — TSV is on disk")
    return rows


def _dump_to_sheet(rows):
    """Mirror discovery into a throwaway tab so it is readable from any machine."""
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(WORKBOOK_ID)
    try:
        ws = sh.worksheet(DUMP_TAB)
        ws.clear()
    except Exception:  # noqa: BLE001
        ws = sh.add_worksheet(title=DUMP_TAB, rows=max(200, len(rows) + 20), cols=4)
    if len(rows) > ws.row_count:
        ws.add_rows(len(rows) - ws.row_count + 10)
    ws.update(values=[[str(c) for c in r] for r in rows],
              range_name=f"A1:C{len(rows)}", value_input_option="RAW")


def pull(week_label, page=None, aliases=None, verbose=True):
    """{owner_key: credico_dd} for a sheet week, plus the lines a human must see.

    Returns (owners, notes). Raises rather than returning an empty dict — a
    silent {} would zero every Credico owner's week and look like a real result.
    """
    saturday = credico_saturday(week_label)
    if verbose:
        print(f"-> credico: week {week_label} → report date {saturday:%Y-%m-%d} "
              f"(one week forward — the FOLLOWING Saturday)", flush=True)
    raw = _extract(saturday, page=page, verbose=verbose)
    if not raw:
        raise RuntimeError(
            f"no Credico rows for {saturday:%Y-%m-%d}. Not treating that as $0 — "
            f"run `python -m automations.credico.report --discover` on Lucy 1 and "
            f"wire _extract() to what the page actually shows.")
    entries, report = normalize(raw)
    owners, unmapped = to_owners(entries, aliases=aliases)
    notes = summarize(entries, report, unmapped)
    if verbose:
        print(f"-> credico: {len(raw)} raw row(s) → {len(entries)} owner(s), "
              f"${sum(owners.values()):,.2f}")
        for n in notes:
            print(f"   · {n}")
    return owners, notes


def _extract(saturday, page=None, verbose=True):
    """Rows off the Reports screen for that Saturday, as [{'name','amount'}].

    NOT WRITTEN YET — deliberately. The Reports screen has never been looked at,
    and inventing selectors for a hash-router SPA produces a scraper that returns
    [] on a layout change and looks like a quiet zero week. Run `--discover`
    on Lucy 1, then write this against the real markup."""
    raise NotImplementedError(
        "Credico report extraction is not wired yet.\n"
        "  0. Check the session first:  lucy rerun credico_check\n"
        "  1. On Lucy 1:  python -m automations.credico.report --discover\n"
        "  2. Read the '_credico_discover' tab (readable from any machine)\n"
        "  3. Implement _extract() against the real controls, using\n"
        "     dd_rows.normalize()/to_owners() for the cleanup — already tested.")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Credico DD pull (Lucy 1)")
    ap.add_argument("--discover", action="store_true",
                    help="dump the Reports screen structure (read-only)")
    ap.add_argument("--deep", action="store_true",
                    help="drive office/campaign/date + Load and dump the grid "
                         "(read-only)")
    ap.add_argument("--week", help="sheet week label, e.g. 7.19.26")
    a = ap.parse_args(argv)
    if a.deep:
        discover_deep(a.week or "7.19.26")
        return 0
    if a.discover:
        discover()
        return 0
    if a.week:
        try:
            owners, _ = pull(a.week)
        except NotImplementedError as e:
            print(f"✗ {e}")
            return 1
        for k, v in sorted(owners.items(), key=lambda kv: -kv[1]):
            print(f"  {k:28} ${v:>12,.2f}")
        return 0
    print(f"credico report date for 7.19.26 = {credico_saturday('7.19.26'):%Y-%m-%d}")
    print("pass --discover (on Lucy 1) or --week 7.19.26")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
