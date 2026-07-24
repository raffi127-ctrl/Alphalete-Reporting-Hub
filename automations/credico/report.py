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

        # office x campaign, skipping each dropdown's placeholder first option
        offices = [o for o in (opts[0] if opts else []) if o[0] and "select" not in (o[1] or "").lower()]
        camps = [o for o in (opts[1] if len(opts) > 1 else []) if o[0] and "select" not in (o[1] or "").lower()]
        for oi, (ov, ot) in enumerate(offices):
            for ci, (cv, ct) in enumerate(camps):
                try:
                    sels[0].select_option(ov)
                    page.wait_for_timeout(700)
                    page.query_selector_all("select")[1].select_option(cv)
                    page.wait_for_timeout(700)
                    cal = page.query_selector("input.calendar") or page.query_selector("input[type=text]")
                    if cal:
                        cal.fill(f"{saturday:%m/%d/%Y}")
                        page.keyboard.press("Escape")
                    btn = page.query_selector("button:has-text('Load')")
                    if btn:
                        btn.click()
                        page.wait_for_timeout(6000)
                    rows.append(["LOADED", f"{ot} / {ct}", page.url])
                    for t in page.query_selector_all("table")[:3]:
                        hdr = [" ".join((h.inner_text() or "").split())
                               for h in t.query_selector_all("th")[:14]]
                        if hdr:
                            rows.append(["  headers", f"{ot} / {ct}", " | ".join(hdr)[:400]])
                        for tr in t.query_selector_all("tbody tr")[:8]:
                            cells = [" ".join((td.inner_text() or "").split())
                                     for td in tr.query_selector_all("td")[:14]]
                            if any(cells):
                                rows.append(["  row", f"{ot} / {ct}", " | ".join(cells)[:400]])
                    if not page.query_selector_all("table"):
                        body = " ".join((page.inner_text("body") or "").split())
                        rows.append(["  NO TABLE", f"{ot} / {ct}", body[-400:]])
                except Exception as e:  # noqa: BLE001
                    rows.append(["  ERROR", f"{ot} / {ct}", f"{type(e).__name__}: {e}"[:300]])
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
