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
    """Set the calendar date the way a human does — click the datepicker input,
    type the date, press Enter. Raw value+submit and the jQuery API are both
    ignored on this page (no global jQuery; the picker's own handler navigates).
    Then parse every table whose header carries a 'Booked By' column."""
    banner = ""
    for _attempt in range(3):
        try:
            loc = page.locator("input[name='calDate']").first
            loc.click(timeout=8000)
            page.wait_for_timeout(1000)
            loc.press("Meta+a")
            loc.press_sequentially(date_str, delay=60)
            page.wait_for_timeout(500)
            try:
                with page.expect_navigation(timeout=20000,
                                            wait_until="domcontentloaded"):
                    loc.press("Enter")
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(4000)
        except Exception:  # noqa: BLE001
            page.wait_for_timeout(2000)
        banner = page.evaluate(
            "() => { const m=(document.body.innerText||'').match("
            "/Calendars for [0-9-]+/); return m ? m[0] : ''; }")
        if date_str in banner:
            break
        print(f"    calendar banner {banner!r} != {date_str}, retrying",
              flush=True)
    raw = page.evaluate("() => document.body.innerText || ''")
    tables = page.evaluate("""() => {
        const out = [];
        for (const tb of document.querySelectorAll('table')) {
            const hdr = tb.rows[0] ? [...tb.rows[0].cells]
                .map(c => c.innerText.trim()) : [];
            const bi = hdr.findIndex(h => /booked by/i.test(h));
            if (bi < 0) continue;
            // nearest earlier text that names the section
            let section = '';
            for (let el = tb.previousElementSibling; el && !section;
                 el = el.previousElementSibling) {
                const t = (el.innerText || '').trim();
                if (/INTERVIEW|FIRST DAY/i.test(t)) section = t.slice(0, 60);
            }
            const rows = [];
            for (const r of [...tb.rows].slice(1)) {
                const c = [...r.cells].map(x => x.innerText.trim());
                if (c.length >= bi + 1 && (c[1] || c[2])) rows.push(c);
            }
            out.push({section, header: hdr, rows});
        }
        return out; }""")
    return raw, tables


_SET_JS = r"""(args) => {
    const nm=args[0], phone=args[1], win=args[2];
    const out={date:'', term:false, by:'', opts:[]};
    const tf=document.querySelector("#sms_type_filter,[name='sms_type_filter']");
    if(tf){ const all=[...tf.options].find(o=>/^all$/i.test(o.text.trim()));
        if(all && tf.value!==all.value){ tf.value=all.value;
            tf.dispatchEvent(new Event('change',{bubbles:true})); } }
    const d=document.querySelector("#sms_date_filter, [name='sms_date_filter']");
    if(d){ out.opts=[...d.options].map(o=>o.text.trim());
        const o=[...d.options].find(o=>o.text.trim().toLowerCase()===win.toLowerCase())
              ||[...d.options].find(o=>new RegExp(win,'i').test(o.text));
        if(o){ d.value=o.value; d.dispatchEvent(new Event('change',{bubbles:true})); out.date=o.text.trim(); } }
    const setF=(sel,val)=>{const e=document.querySelector(sel); if(!e)return false;
        e.value=val; e.dispatchEvent(new Event('input',{bubbles:true}));
        e.dispatchEvent(new Event('change',{bubbles:true})); return true;};
    setF("#sms_name_filter, [name='sms_name_filter']","");
    setF("#sms_phone_filter, [name='sms_phone_filter']","");
    if(phone && setF("#sms_phone_filter, [name='sms_phone_filter']",phone)){out.term=true;out.by='phone';}
    else if(setF("#sms_name_filter, [name='sms_name_filter']",nm)){out.term=true;out.by='name';}
    return out;
}"""

_PICK_JS = r"""(args) => {
    const want = args[0], name = (args[1]||'').toLowerCase();
    const norm = s => (s||'').replace(/\D/g,'');
    const all = [...document.querySelectorAll('div,li,a,tr')];
    const rows = all.filter(e => { const t=e.innerText||'';
        return t.length<200 && norm(t).length>=10 && /\+?1?\d{10}/.test(norm(t))
               && e.querySelectorAll('*').length<25; });
    const cand = rows.filter(e => !rows.some(o => o!==e && e.contains(o)));
    window.__aud_rows = cand;
    const scored = cand.map((e,i)=>{ const t=e.innerText||'', d=norm(t);
        return {i, hasPhone:!!(want && d.includes(want)),
                hasName:!!(name && t.toLowerCase().includes(name)),
                text:t.replace(/\s+/g,' ').slice(0,60)}; });
    const byPhone = scored.find(s=>s.hasPhone);
    const named = scored.filter(s=>s.hasName);
    const choice = byPhone || (named.length===1 ? named[0] : (cand.length===1 ? scored[0] : null));
    return {count:cand.length, choice};
}"""


def _read_thread(page, name, phone):
    """Open the SMS widget and read ONE applicant's conversation, using the SAME
    filter/search/bind choreography the production re-text uses (its _SET_JS /
    _PICK_JS verbatim; window sweep; #sms_filter_search). Text is read from
    #chatContainer only — the widget lives in the MAIN page DOM."""
    if not oat._open_sms_panel(page):
        return None, "sms panel failed"
    w, diag = oat._sms_widget_frame(page, 30000)
    if w is None:
        oat._close_sms_panel(page)
        return None, f"widget missing ({diag[:80]})"
    page.wait_for_timeout(800)
    want = re.sub(r"\D", "", phone or "")[-10:]
    last = (name or "").split()[-1]
    picked = None
    for win in ("This Month", "Last Month", "This Week", "Today"):
        st = w.evaluate(_SET_JS, [last or name, want, win])
        if not st.get("term"):
            oat._close_sms_panel(page)
            return None, "filters not found"
        if not st.get("date"):
            continue
        try:
            w.locator("#sms_filter_search").first.click(timeout=4000,
                                                        no_wait_after=True)
        except Exception:  # noqa: BLE001
            w.evaluate("() => { const b=document.querySelector('#sms_filter_search');"
                       " if (b) b.click(); }")
        page.wait_for_timeout(2600)
        pk = w.evaluate(_PICK_JS, [want, name])
        if pk.get("choice"):
            picked = pk
            break
    choice = picked.get("choice") if picked else None
    if not choice:
        oat._close_sms_panel(page)
        return None, "no thread matched"
    try:
        w.evaluate("(i) => window.__aud_rows[i].click()", choice["i"])
        page.wait_for_timeout(3000)
    except Exception as e:  # noqa: BLE001
        oat._close_sms_panel(page)
        return None, f"thread click: {type(e).__name__}"
    text = w.evaluate("""() => { const r = document.querySelector('#chatContainer');
        return r ? (r.innerText || '') : ''; }""")
    oat._close_sms_panel(page)
    return text, f"ok (bound: {choice.get('text','')[:50]})"


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
                raw, tables = _dump_calendar(page, a.date)
                fh = open(outp, "w")
                fh.write(json.dumps({"office": oid, "date": a.date,
                                     "tables": tables}) + "\n")
                names = []
                n_ai = 0
                for t in tables:
                    hdr = [h.lower() for h in t["header"]]
                    def col(label, hdr=hdr):
                        return next((i for i, h in enumerate(hdr)
                                     if label in h), None)
                    bi, fi, li = col("booked by"), col("first name"), col("last name")
                    pi, ci = col("phone"), col("cell")
                    first_round = "second" not in (t["section"] or "").lower()
                    for r in t["rows"]:
                        booked = r[bi] if bi is not None and bi < len(r) else ""
                        if not re.search(r"AI Messaging", booked, re.I):
                            continue
                        n_ai += 1
                        if not first_round:
                            continue          # Carlos asked for FIRST rounds
                        nm = f"{r[fi] if fi is not None else ''} " \
                             f"{r[li] if li is not None else ''}".strip()
                        ph = ""
                        for j in (pi, ci):
                            if j is not None and j < len(r) and r[j].strip():
                                ph = r[j]; break
                        if nm:
                            names.append((nm, ph, booked[:60]))
                seen = set()
                names = [t3 for t3 in names
                         if not (t3[0].lower() in seen or seen.add(t3[0].lower()))]
                if a.limit:
                    names = names[:a.limit]
                print(f"[{oid}] AI-booked rows={n_ai} "
                      f"first-round names={len(names)}", flush=True)
                for nm, ph, booked in names:
                    text, why = _read_thread(page, nm, ph)
                    fh.write(json.dumps({"office": oid, "name": nm, "phone": ph,
                                         "booked": booked, "thread_status": why,
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
