"""AI Settings pull — Office Info, AI Preferences and the Escalations table,
off `index.cfm?p=1504`.

Megan found this page on 2026-10-01 and then found that several offices had
it set wrong. Nothing was reading it, so every check was a screenshot.
Audited by ai_settings.py and escalations.py.

THE PAGE IS p=1504. AI tab -> AI Settings. `&pane=escalations` opens the
Escalations tab directly; Office Info and AI Preferences are on the
Settings pane. Both panes are scraped in one visit.

WHAT MATTERS ON IT (eStream's own walkthrough, transcribed in
resources/recruiting-context/appstream-ai-settings.md):

  * the right-hand Office Info column is READ ONLY for the office. It is
    scraped anyway, because what the AI sends comes from there — 11280's
    suite had been typed into the State field and the AI dropped it.
  * the two timeslot buffers are both counted backwards from the
    appointment, so the window an applicant actually gets is
    offered - accepted. 11280 was on 15 and 10: five minutes.
  * routing lives in four radio columns (Clarify / Escalate / Silent /
    Don't Escalate). Some rows are locked to "Silent Only" and show text
    there instead of radios, which is why `routing` can come back as that
    string rather than a choice.

  lucy rerun sms_ai_settings --office 11280 --machine "Lucy 2"
  ... pull_ai_settings.py --office 11280 --dry-run

RUNS ON THE 'Lucy Reports' LOGIN (Megan 2026-10-01). The name has a space
in it, and it is one of only two AppStream accounts left — the other is
'Lucy Resume Pushing'. That is a property of the machine's configured
profile, not something this module selects: appstream_direct_session's
`account=` argument picks a separate CAPTURE profile used for seeding a
session, not for running one. So if a box is signed in as the wrong
account, re-seed the box; do not pass `account` here.

READ-ONLY. Writes output/ai_settings_<office>.json and
output/escalations_<office>.json. It changes nothing in AppStream.
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9 — keep lazy

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fetch_office as fo
from automations.shared.tableau_patchright import appstream_direct_session

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"

# Label on the page -> the key ai_settings.py expects. Matched on the
# label's text with punctuation and case thrown away, because the page
# words them slightly differently between panes.
FIELDS = {
    "name your ai assitant": "ai_assistant_name",      # their typo, kept
    "name your ai assistant": "ai_assistant_name",
    "escalation contact title": "escalation_contact_title",
    "escalation contact person name": "escalation_contact_name",
    "how long are your interviews": "interview_length",
    "office name": "office_name",
    "ai recruiting company name": "ai_company_name",
    "office address": "office_address1",
    "office city": "office_city",
    "office state": "office_state",
    "office zip": "office_zip",
    "office phone": "office_phone",
    "timeslot buffer for times offered by ai in minutes": "offered_buffer",
    "timeslot buffer for times accepted by candidates in minutes":
        "accepted_buffer",
    "ghosting threshold in minutes": "ghosting_threshold",
}


def _rqst(page):
    m = re.search(r"rqst=([A-Za-z0-9_-]+)", page.url or "")
    if m:
        return m.group(1)
    m = re.search(r"rqst=([A-Za-z0-9_-]+)",
                  page.evaluate("() => document.documentElement.innerHTML") or "")
    return m.group(1) if m else None


def _open(page, tok, pane=""):
    url = "https://www.applicantstream.com/index.cfm?rqst={}&p=1504".format(tok)
    if pane:
        url += "&pane=" + pane
    # No networkidle: this is a React page that keeps polling, so idle never
    # arrives and the wait just burns 30s before failing the run.
    page.goto(url, wait_until="domcontentloaded", timeout=40000)
    page.wait_for_timeout(4000)


def scrape_settings(page):
    """Every labelled input on the Settings pane, by its visible label.

    Read off the label rather than an id: the ids are generated and the
    labels are what eStream's own walkthrough names, so a renamed id does
    not silently empty the audit."""
    return page.evaluate("""() => {
      const norm = s => (s||'').replace(/[^A-Za-z0-9 ]/g,' ')
                               .replace(/\\s+/g,' ').trim().toLowerCase();
      const out = {}, radios = {};
      document.querySelectorAll('input,select,textarea').forEach(el => {
        if (el.type === 'hidden') return;
        let label = '';
        if (el.id) {
          const l = document.querySelector('label[for="' + el.id + '"]');
          if (l) label = l.textContent;
        }
        if (!label) {
          let n = el.closest('div,td,li');
          for (let i = 0; i < 3 && n && !label; i++) {
            const l = n.querySelector('label');
            if (l) label = l.textContent;
            n = n.parentElement;
          }
        }
        const key = norm(label);
        if (!key) return;
        if (el.type === 'checkbox') { radios[key] = el.checked; return; }
        if (el.type === 'radio') { if (el.checked) out[key] = norm(el.value); return; }
        const v = (el.value || '').trim();
        if (v && !(key in out)) out[key] = v;
      });
      // the Interview Type radios carry their choice in a sibling label
      const t = [...document.querySelectorAll('input[type=radio]')]
        .filter(r => r.checked)
        .map(r => {
          const l = r.closest('label') ||
                    document.querySelector('label[for="' + r.id + '"]');
          return l ? l.textContent.trim() : (r.value || '').trim();
        })
        .filter(Boolean);
      return {fields: out, flags: radios, checked_radios: t};
    }""")


def scrape_escalations(page):
    """One row per escalation: name, category, description, custom message
    and which of the four routing columns is selected.

    A row locked by the platform has the words "Silent Only" in the routing
    cells instead of radios; that string is returned as the routing so the
    audit can tell "nobody set this" from "nobody CAN set this"."""
    return page.evaluate("""() => {
      const txt = el => (el ? el.textContent : '').replace(/\\s+/g,' ').trim();
      const tables = [...document.querySelectorAll('table')];
      const tbl = tables.find(t => /escalat|clarify/i.test(txt(t))) || tables[0];
      if (!tbl) return [];
      const heads = [...tbl.querySelectorAll('thead th,tr:first-child th')]
        .map(h => txt(h).toLowerCase());
      const cols = ['clarify','escalate','silent',"don't escalate"]
        .map(n => heads.findIndex(h => h.replace(/[^a-z' ]/g,'').trim() === n));
      const rows = [];
      [...tbl.querySelectorAll('tbody tr')].forEach(tr => {
        const tds = [...tr.children];
        if (tds.length < 4) return;
        const name = txt(tds[0]);
        if (!name) return;
        const cell = txt(tds[2]);
        let msg = '';
        const m = cell.match(/Custom Message:\\s*(.*?)(?:\\s*Edit Custom Message|$)/);
        if (m) msg = m[1].replace(/\\s*Message disabled for Silent escalation\\s*$/,'').trim();
        let routing = '';
        const names = ['Clarify','Escalate','Silent',"Don't Escalate"];
        cols.forEach((ci, i) => {
          if (ci < 0 || !tds[ci]) return;
          const r = tds[ci].querySelector('input[type=radio]');
          if (r && r.checked) routing = names[i];
          else if (!r && /silent only/i.test(txt(tds[ci]))) routing = 'Silent Only';
        });
        rows.push({name: name, category: txt(tds[1]),
                   description: cell.split('Custom Message:')[0].trim(),
                   message: msg, routing: routing});
      });
      return rows;
    }""")


# The panes p=1504 is known to carry. Probed in order; the first that
# yields the buffers is the one the puller should be reading.
PANES = ("", "settings", "preferences", "office", "escalations")


def _probe(page, tok, office):
    """Print what each pane actually exposes. Writes nothing.

    Added 2026-10-06: the pull came back "0 settings, 0 preferences, 50
    escalation rows", which says the page loaded and the FIELDS mapping
    matched nothing. Only the page can say whether the labels were renamed
    or the fields live on another pane, so ask it rather than guess."""
    for pane in PANES:
        try:
            _open(page, tok, pane)
            raw = scrape_settings(page) or {}
        except Exception as e:  # noqa: BLE001
            print("[probe] {} pane {!r}: FAILED {}".format(office, pane, e),
                  flush=True)
            continue
        fields = raw.get("fields") or {}
        mapped = {FIELDS[k]: v for k, v in fields.items() if k in FIELDS}
        print("[probe] {} pane {!r}: {} labelled fields, {} of them mapped"
              .format(office, pane or "(default)", len(fields), len(mapped)),
              flush=True)
        for label in sorted(fields):
            print("    {:<58} = {:<22} {}".format(
                label[:58], str(fields[label])[:22],
                "-> " + FIELDS[label] if label in FIELDS else "UNMAPPED"),
                flush=True)
        tabs = page.evaluate(
            "() => Array.from(document.querySelectorAll("
            "'a,button,[role=tab]')).map(e => (e.textContent||'').trim())"
            ".filter(t => t && t.length < 32).slice(0, 40)") or []
        print("    tabs/buttons: {}".format(", ".join(tabs[:20])), flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="11280", help="one id or a comma list")
    ap.add_argument("--probe", action="store_true",
                    help="print every label the page exposes, per pane, and "
                         "write nothing — for when the mapping comes back "
                         "empty and guessing at label names is the "
                         "alternative")
    ap.add_argument("--dry-run", action="store_true",
                    help="scrape and print, write nothing")
    a = ap.parse_args(argv)

    offices = [o.strip() for o in str(a.office).split(",") if o.strip()]
    OUTPUT_DIR.mkdir(exist_ok=True)
    rc = 0
    # Step aside rather than queue behind a report. An audit is never
    # worth making a live pull wait for the one AppStream session.
    with appstream_direct_session(verbose=True, yield_if_busy=True) as page:
        page.wait_for_timeout(3000)
        tok = _rqst(page)
        if not tok:
            raise RuntimeError("no rqst token on the console page")
        for office in offices:
            fo._switch_office(page, office, "")
            page.wait_for_timeout(1500)
            tok = _rqst(page) or tok

            if a.probe:
                _probe(page, tok, office)
                continue
            _open(page, tok)
            raw = scrape_settings(page) or {}
            fields = raw.get("fields") or {}
            info, prefs = {}, {}
            for label, value in fields.items():
                key = FIELDS.get(label)
                if not key:
                    continue
                (prefs if key.endswith(("_buffer", "_threshold")) else info)[key] = value
            itype = [t for t in (raw.get("checked_radios") or [])
                     if re.search(r"in.?person|phone|zoom|google meet", t, re.I)]
            if itype:
                info["interview_type"] = itype[0]

            _open(page, tok, "escalations")
            time.sleep(1.0)
            rows = scrape_escalations(page) or []

            if not info and not rows:
                print("[ai_settings] {}: nothing scraped — the page shape "
                      "changed, or the office never loaded".format(office),
                      flush=True)
                rc = 1
                continue

            print("[ai_settings] {}: {} settings, {} preferences, {} "
                  "escalation rows ({} with a message, {} locked silent)"
                  .format(office, len(info), len(prefs), len(rows),
                          sum(1 for r in rows if r.get("message")),
                          sum(1 for r in rows
                              if r.get("routing") == "Silent Only")),
                  flush=True)
            if not prefs:
                print("   no timeslot buffers found — the window check will "
                      "be skipped, not passed", flush=True)

            if a.dry_run:
                print(json.dumps({"office_info": info, "preferences": prefs},
                                 indent=2, ensure_ascii=False), flush=True)
                for r in rows[:5]:
                    print("   {:<34} {:<14} {}".format(
                        r["name"][:34], r["routing"], r["message"][:50]),
                        flush=True)
                continue

            (OUTPUT_DIR / "ai_settings_{}.json".format(office)).write_text(
                json.dumps({"office": office,
                            "pulled": dt.datetime.now().isoformat(timespec="seconds"),
                            "office_info": info, "preferences": prefs},
                           ensure_ascii=False, indent=2), encoding="utf-8")
            (OUTPUT_DIR / "escalations_{}.json".format(office)).write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            # The JSON above only ever exists on the machine that pulled, and
            # that is always Lucy 2. The tab is what every other machine
            # reads, so a clean run is visible everywhere.
            try:
                from automations.sms_audit import ai_settings_tab as TAB
                tab, n = TAB.write(office, info, prefs, rows)
                print("[ai_settings]   -> {} ({} rows)".format(tab, n),
                      flush=True)
            except Exception as e:  # noqa: BLE001
                print("[ai_settings]   tab write failed, local JSON is "
                      "written: {}".format(e), flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
