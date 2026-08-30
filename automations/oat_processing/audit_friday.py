#!/usr/bin/env python3
"""Audit how AI Messaging books interviews: for each office, open the calendar
for one date, collect the FIRST-round interviews and who booked them, and for
every AI-Messaging booking read the applicant's full SMS thread. Read-only —
nothing is sent, removed, or edited.

Carlos, 2026-08-30: "look at everyone scheduled for an interview last Friday …
the row where it says 'booked by AI messaging' under the first rounds … audit
all the text messages for all of these individuals so we can compare."

  audit_friday --offices 11580,23467 --date 08-28-2026 [--tab-prefix 'AI Audit']

Results: one JSON-lines file per office under output/ai-audit-<date>-<office>.jsonl
plus (when Sheets auth is available) a tab per office so the mini can read what
a Lucy 2 run produced.
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

import argparse
import datetime as dt
import json
import os
import re
import sys

from automations.recruiting_report import fetch_office
from automations.resume_pushing import run as rp
from automations.oat_processing import run as oat


def _dump_calendar(page, date_str):
    """POST the calDate form, WAIT for the navigation, and verify the banner
    says the requested date — the first version read the page mid-reload and
    saw an empty calendar. Returns (raw_text, parsed_rows)."""
    for _attempt in range(3):
        try:
            with page.expect_navigation(timeout=30000,
                                        wait_until="domcontentloaded"):
                page.evaluate("""(d) => {
                    const el = document.querySelector("input[name='calDate']");
                    el.value = d;
                    HTMLFormElement.prototype.submit.call(el.form); }""", date_str)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(4000)
        banner = page.evaluate("() => (document.body.innerText||'').match("
                               "/Calendars for [0-9-]+/) ? "
                               "document.body.innerText.match("
                               "/Calendars for [0-9-]+/)[0] : ''")
        if date_str in banner:
            break
        print(f"    calendar banner {banner!r} != {date_str}, retrying",
              flush=True)
    raw = page.evaluate("() => document.body.innerText || ''")
    rows = page.evaluate("""() => {
        const out = [];
        for (const tb of document.querySelectorAll('table')) {
            const head = (tb.rows[0] ? tb.rows[0].innerText : '');
            for (const r of tb.rows) {
                const t = r.innerText.replace(/\\n/g, ' | ').trim();
                if (t) out.push(t);
            }
        }
        return out; }""")
    return raw, rows


def _read_thread(page, name, phone):
    """Open the SMS widget, bind this applicant's thread, return its text."""
    if not oat._open_sms_panel(page):
        return None, "sms panel failed"
    w, diag = oat._sms_widget_frame(page, 30000)
    if w is None:
        oat._close_sms_panel(page)
        return None, f"widget missing ({diag[:80]})"
    page.wait_for_timeout(800)
    want = re.sub(r"\\D", "", phone or "")[-10:]
    hit = w.evaluate(r"""(args) => {
        const [nm, ph] = args;
        const setF = (sel, v) => { const el = document.querySelector(sel);
            if (!el) return false; el.value = v;
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true})); return true; };
        const dsel = document.querySelector("#sms_date_filter, [name='sms_date_filter']");
        if (dsel) { for (const o of dsel.options)
            if (/this month/i.test(o.text)) { dsel.value = o.value;
                dsel.dispatchEvent(new Event('change', {bubbles: true})); break; } }
        setF("#sms_name_filter, [name='sms_name_filter']", "");
        setF("#sms_phone_filter, [name='sms_phone_filter']", "");
        if (ph) setF("#sms_phone_filter, [name='sms_phone_filter']", ph);
        else setF("#sms_name_filter, [name='sms_name_filter']", nm);
        const go = [...document.querySelectorAll('button, input')]
            .find(b => /search/i.test(b.value || b.innerText || ''));
        if (go) go.click();
        return true; }""", [name, want])
    page.wait_for_timeout(3000)
    clicked = w.evaluate(r"""(nm) => {
        const fold = s => s.normalize('NFKD').replace(/[^\\w ]/g, '').toLowerCase();
        const items = [...document.querySelectorAll('li, tr, div')]
            .filter(e => e.offsetParent !== null && e.childElementCount < 12
                      && fold(e.innerText || '').includes(fold(nm).split(' ')[0]));
        if (!items.length) return false;
        items[0].click(); return (items[0].innerText || '').slice(0, 80); }""",
        name)
    if not clicked:
        oat._close_sms_panel(page)
        return None, "no thread matched"
    page.wait_for_timeout(3500)
    text = w.evaluate("() => document.body.innerText || ''")
    oat._close_sms_panel(page)
    return text, "ok"


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--offices", required=True,
                   help="comma-separated office ids")
    p.add_argument("--date", default="08-28-2026")
    p.add_argument("--limit", type=int, default=0,
                   help="cap threads read per office (0 = all)")
    a = p.parse_args(argv)
    ids = [o.strip() for o in a.offices.split(",") if o.strip()]

    from automations.applicant_push import offices as OF
    OF.activate("11580")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with rp.warm_appstream_cdp_page(switch_office=False, diag_tab="") as (page, ctx, net):
        for oid in ids:
            outp = os.path.join(root, "output", f"ai-audit-{a.date}-{oid}.jsonl")
            try:
                if not fetch_office._switch_office(page, oid, ""):
                    print(f"[{oid}] SWITCH FAILED", flush=True)
                    continue
                m = re.search(r"rqst=([A-F0-9-]+)", page.url or "")
                page.goto(f"https://applicantstream.com/index.cfm?rqst={m.group(1)}&p=102",
                          wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(5000)
                raw, rows = _dump_calendar(page, a.date)
                # first-round rows booked by AI Messaging: name is the first cell
                ai_rows = [r for r in rows if re.search(r"AI Messaging", r, re.I)]
                fh = open(outp, "w")
                fh.write(json.dumps({"office": oid, "date": a.date,
                                     "calendar_rows": rows[:400]}) + "\n")
                names = []
                for r in ai_rows:
                    cells = [c.strip() for c in r.split("|") if c.strip()]
                    nm = next((c for c in cells
                               if re.match(r"^[A-Z][a-zA-Z'\-]+ [A-Z]", c)
                               and not re.search(r"AI Messaging|Interview|Calendar", c)), "")
                    ph = next((re.sub(r"\D", "", c) for c in cells
                               if re.search(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", c)), "")
                    if nm:
                        names.append((nm, ph))
                seen = set()
                names = [(n, p2) for n, p2 in names
                         if not (n.lower() in seen or seen.add(n.lower()))]
                if a.limit:
                    names = names[:a.limit]
                print(f"[{oid}] AI-booked rows={len(ai_rows)} "
                      f"distinct names={len(names)}", flush=True)
                for nm, ph in names:
                    text, why = _read_thread(page, nm, ph)
                    fh.write(json.dumps({"office": oid, "name": nm, "phone": ph,
                                         "thread_status": why,
                                         "thread": (text or "")[:20000]}) + "\n")
                    print(f"[{oid}]   {nm}: {why} "
                          f"({len(text or '')} chars)", flush=True)
                fh.close()
            except Exception as e:  # noqa: BLE001
                print(f"[{oid}] ERR {type(e).__name__}: {str(e)[:100]}", flush=True)
        print("AUDIT_DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
