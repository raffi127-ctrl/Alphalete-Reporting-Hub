"""READ-ONLY probe: OwnerVille's CRU/IRU Engagement page (p=164) for one office.

Jamis (Midspire, 2026-11-14) wants CONSUMER tallies on his B2B knocks board.
They are not on Disposition by Rep (p=89) — they live on Reports → CRU/IRU
Engagement ("TM-Leads · Reporting"), behind an "Include consumer tallies"
switch and a "Consumer Tally" tab. Nothing in the repo reads that page yet, so
this probe finds out WHAT it serves and HOW before a reader is built:

  1. impersonate the office (same helpers knocks_pull uses; always exits),
  2. pin the campaign (B2B AT&T SBS = 2 by default),
  3. open p=164 on the session's own host, then on v2.ownerville.com,
  4. record every data call the page makes (URL with the session token masked,
     status, first bytes of the body),
  5. dump the switches, tabs, table headers and first rows — before and after
     turning "Show disposition breakdown" + "Include consumer tallies" on, and
     on the "Consumer Tally" tab.

Changes NOTHING in OwnerVille (the switches are page-view filters; no Save).
Writes output/consumer_tally_probe/<office>-<date>.json + PNG screenshots and
prints a summary that `lucy logtail` can read.

    python -m automations.b2b_metrics.consumer_tally_probe --office "Jamis Garay"
    python -m automations.b2b_metrics.consumer_tally_probe --office "Jamis Garay" --date 2026-11-13
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

OUT_DIR = Path("output") / "consumer_tally_probe"
PAGE = "index.cfm?p=164"
V2_HOST = "https://v2.ownerville.com"


def _mask(url: str) -> str:
    """Never print the session token."""
    s = re.sub(r"(rqst=)[^&\s]+", r"\1…", url or "")
    # multipart bodies carry it as its own form field, not rqst=…
    return re.sub(r'(name="rqst"\s+)\S+', r"\1…", s)


def _snapshot(page, label: str, shots: Path) -> dict:
    """What the page shows right now: switches, tabs, tables (headers + 3 rows)."""
    try:
        page.wait_for_timeout(2500)
    except Exception:  # noqa: BLE001
        pass
    data = page.evaluate(r"""() => {
      const txt = el => (el.innerText || el.textContent || '').trim().replace(/\s+/g,' ');
      const checks = [...document.querySelectorAll('input[type=checkbox]')].map(c => {
        const lab = c.closest('label') || document.querySelector(`label[for="${c.id}"]`);
        return {label: lab ? txt(lab) : (c.name || c.id || ''), checked: c.checked, id: c.id, name: c.name};
      });
      const tabs = [...document.querySelectorAll('button, a, [role=tab]')]
        .map(txt).filter(t => /tally|disposition by rep|territory stats|today.s activity/i.test(t));
      const tables = [...document.querySelectorAll('table')].map(t => {
        const heads = [...t.querySelectorAll('thead tr')].map(tr => [...tr.children].map(txt));
        const rows = [...t.querySelectorAll('tbody tr')].slice(0, 3).map(tr => [...tr.children].map(txt));
        return {id: t.id, cls: t.className, heads, rows,
                n_rows: t.querySelectorAll('tbody tr').length};
      });
      const iframes = [...document.querySelectorAll('iframe')].map(f => f.src);
      return {url: location.href, title: document.title, checks, tabs: [...new Set(tabs)],
              tables, iframes, body_head: txt(document.body).slice(0, 600)};
    }""")
    data["url"] = _mask(data.get("url", ""))
    try:
        page.screenshot(path=str(shots / f"{label}.png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass
    print(f"\n=== {label} ===  {data['url']}  ({data.get('title','')})", flush=True)
    print("  switches:", [(c["label"][:40], c["checked"]) for c in data["checks"]], flush=True)
    print("  tabs:", data["tabs"], flush=True)
    for t in data["tables"]:
        print(f"  table id={t['id']!r} rows={t['n_rows']}", flush=True)
        for h in t["heads"]:
            print("    head:", h, flush=True)
        for r in t["rows"]:
            print("    row :", r, flush=True)
    if not data["tables"]:
        print("  (no <table>) body:", data["body_head"][:300], flush=True)
    return data


def _turn_on(page, words: str) -> bool:
    """Tick the switch whose label contains `words` (case-insensitive)."""
    return bool(page.evaluate(r"""(words) => {
      const want = words.toLowerCase();
      for (const c of document.querySelectorAll('input[type=checkbox]')) {
        const lab = c.closest('label') || document.querySelector(`label[for="${c.id}"]`);
        const t = ((lab && lab.innerText) || '').toLowerCase();
        if (t.includes(want)) { if (!c.checked) { (lab || c).click(); } return true; }
      }
      return false;
    }""", words))


def _click_text(page, words: str) -> bool:
    return bool(page.evaluate(r"""(words) => {
      const want = words.toLowerCase();
      for (const el of document.querySelectorAll('button, a, [role=tab], li, div')) {
        const t = (el.innerText || '').trim().toLowerCase();
        if (t === want) { el.click(); return true; }
      }
      return false;
    }""", words))


def _set_day(page, day: dt.date) -> None:
    """Best effort: type the day into the page's DAY box if it has one."""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        ok = page.evaluate(r"""(v) => {
          const inp = [...document.querySelectorAll('input')].find(i =>
              /date|day/i.test((i.type||'') + (i.name||'') + (i.id||'') + (i.placeholder||'')));
          if (!inp) return false;
          inp.value = v; inp.dispatchEvent(new Event('input', {bubbles:true}));
          inp.dispatchEvent(new Event('change', {bubbles:true})); return true;
        }""", day.strftime(fmt))
        if ok:
            print(f"  day set -> {day.strftime(fmt)}", flush=True)
            return


def probe(office: str, day: dt.date, campaign: str = "2") -> dict:
    from automations.shared.tableau_patchright import ownerville_session
    from automations.focus_office_att.aliases import alias_to_canonical, load_aliases
    from automations.focus_office_att.run_all_owners import (
        _navigate_to_office_access, _find_owner_and_impersonate, _exit_impersonation)
    from automations.focus_office_att.step5_fill_one_owner import page_rqst
    from automations.rashad_metrics.knocks_pull import assert_impersonating, _pin_campaign

    aliases = load_aliases()
    canonical = alias_to_canonical(office, aliases)
    stamp = "%s-%s" % (re.sub(r"\W+", "_", canonical.lower()).strip("_"), day.isoformat())
    shots = OUT_DIR / stamp
    shots.mkdir(parents=True, exist_ok=True)
    report = {"office": canonical, "day": day.isoformat(), "campaign": campaign,
              "calls": [], "views": {}}

    with ownerville_session(verbose=True) as page:
        page.set_default_timeout(60_000)
        page.set_default_navigation_timeout(60_000)

        def _on_response(resp):
            try:
                rt = resp.request.resource_type
                if rt not in ("xhr", "fetch", "document"):
                    return
                body = ""
                ctype = resp.headers.get("content-type", "")
                if "json" in ctype or "text" in ctype or "javascript" in ctype:
                    try:
                        body = resp.text()[:1500]
                    except Exception:  # noqa: BLE001
                        body = ""
                report["calls"].append({"type": rt, "method": resp.request.method,
                                        "url": _mask(resp.url), "status": resp.status,
                                        "ctype": ctype,
                                        "post": _mask(resp.request.post_data or "")[:600],
                                        "body": body})
            except Exception:  # noqa: BLE001
                pass

        page.on("response", _on_response)
        _exit_impersonation(page)
        if not _navigate_to_office_access(page):
            raise RuntimeError("Office Access (?p=901) did not load")
        try:
            rqst, reason = _find_owner_and_impersonate(page, canonical, aliases)
            if not rqst:
                raise RuntimeError(f"Couldn't impersonate {canonical!r}: {reason}")
            assert_impersonating(page, rqst, canonical, aliases, verbose=True)
            rqst = page_rqst(page) or rqst
            _pin_campaign(page, rqst, campaign, verbose=True)

            here = re.match(r"https?://[^/]+", page.url).group(0)
            hosts = [here] + ([V2_HOST] if here.rstrip("/") != V2_HOST else [])
            for host in hosts:
                tag = "v2" if "v2." in host else "v1"
                page.goto(f"{host}/{PAGE}&rqst={rqst}", wait_until="domcontentloaded")
                page.wait_for_timeout(4000)
                report["views"][f"{tag}-open"] = _snapshot(page, f"{tag}-1-open", shots)
                _set_day(page, day)
                page.wait_for_timeout(2500)
                _click_text(page, "Disposition by Rep")
                on1 = _turn_on(page, "disposition breakdown")
                on2 = _turn_on(page, "consumer tallies")
                print(f"  switched on: breakdown={on1} consumer={on2}", flush=True)
                page.wait_for_timeout(4000)
                report["views"][f"{tag}-breakdown"] = _snapshot(
                    page, f"{tag}-2-breakdown+consumer", shots)
                if _click_text(page, "Consumer Tally"):
                    page.wait_for_timeout(4000)
                    report["views"][f"{tag}-consumer-tab"] = _snapshot(
                        page, f"{tag}-3-consumer-tally-tab", shots)
                if any(v.get("tables") for k, v in report["views"].items()
                       if k.startswith(tag)):
                    break       # this host served the page; no need for the other
        finally:
            try:
                _exit_impersonation(page)
            except Exception:  # noqa: BLE001
                pass

    print("\n=== data calls (xhr/fetch) ===", flush=True)
    for c in report["calls"]:
        if c["type"] in ("xhr", "fetch"):
            print(f"  {c['method']} {c['status']} {c['url'][:160]}", flush=True)
            if c["post"]:
                print(f"      post: {c['post'][:200]}", flush=True)
            if c["body"]:
                print(f"      body: {c['body'][:300]!r}", flush=True)
    out = OUT_DIR / f"{stamp}.json"
    out.write_text(json.dumps(report, indent=1))
    print(f"\nwrote {out} + screenshots in {shots}", flush=True)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="b2b_metrics.consumer_tally_probe")
    ap.add_argument("--office", default="Jamis Garay")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--campaign", default="2", help="client id to pin (2 = B2B AT&T SBS)")
    a = ap.parse_args(argv)
    day = (dt.date.fromisoformat(a.date) if a.date
           else dt.date.today() - dt.timedelta(days=1))
    probe(a.office, day, a.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
