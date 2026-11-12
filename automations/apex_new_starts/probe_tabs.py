"""How do you actually get from one tab of a record to another? READ ONLY.

`goSpa` clicks the anchor whose href holds the path. That works from the
roster and does nothing from ON a record, and a driver click on the same
anchor did not navigate either (2026-11-12) -- so the tab strip is not what
this assumed. This dumps every link and every clickable thing near the top of
an employment record so the real control can be named.

Types nothing, clicks nothing, saves nothing.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_tabs --person "First Last"
"""
from __future__ import annotations

import argparse
import json

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive

DUMP = r"""() => {
  const out = {url: location.href, links: [], tabby: []};
  for (const a of document.querySelectorAll('a')) {
    const h = a.getAttribute('href') || '';
    const t = (a.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 40);
    if (!t && !h) continue;
    out.links.push({text: t, href: h.slice(0, 90),
                    cls: (a.className || '').slice(0, 60),
                    shown: !!a.offsetParent});
  }
  // anything that LOOKS like a tab strip, however it is built
  const words = /employment record|user profile|tax *& *bank|bank info/i;
  for (const e of document.querySelectorAll(
        'li,button,span,div[role=tab],[role=tab],[ui-sref],[ng-click],[data-url]')) {
    const t = (e.innerText || '').replace(/\s+/g, ' ').trim();
    if (!words.test(t) || t.length > 60) continue;
    out.tabby.push({tag: e.tagName.toLowerCase(), text: t.slice(0, 40),
                    cls: (e.className || '').slice(0, 70),
                    sref: e.getAttribute('ui-sref') || '',
                    click: (e.getAttribute('ng-click') || '').slice(0, 70),
                    dataUrl: (e.getAttribute('data-url') || '').slice(0, 70),
                    shown: !!e.offsetParent});
  }
  return out;
}"""


def main() -> int:
    ap = argparse.ArgumentParser(description="What the tab strip really is.")
    ap.add_argument("--person", required=True)
    a = ap.parse_args()
    who = [{"name": a.person, "find": a.person.split()[-1], "pages": {}}]

    with AX.ApexSession(log=print, login_timeout_s=10 * 60) as s:
        page = s.page
        s.require_login()
        page.wait_for_timeout(1500)
        for _ in range(4):
            if drive.to_roster(page, log=print):
                break
            page.wait_for_timeout(2500)
        else:
            print("could not reach the roster")
            return 1
        drive.keep_loaded(page, who, log=print)
        pid = page.evaluate(
            "async (p) => { const id = await window.__ansOpen(p);"
            " return id ? String(id) : ''; }", who[0])
        if not pid:
            print("%s is not on the roster right now" % a.person)
            return 1
        path = "/employees/%s/edit/employment-record" % pid
        if path not in (page.url or ""):
            drive.keep_loaded(page, who, log=lambda *x: None)
            page.evaluate("async (p) => await window.__ansGoSpa(p)", path)
            page.wait_for_timeout(2500)
        got = page.evaluate(DUMP)
        print("\non %s\n" % got["url"])
        print("TAB-SHAPED THINGS:")
        for t in got["tabby"]:
            print("  %-7s %-24s shown=%-5s cls=%s sref=%r click=%r url=%r"
                  % (t["tag"], t["text"], t["shown"], t["cls"],
                     t["sref"], t["click"], t["dataUrl"]))
        print("\nLINKS mentioning a tab path:")
        for l in got["links"]:
            if any(k in l["href"] for k in ("user-profile", "bank-info",
                                            "employment-record")):
                print("  %-28s shown=%-5s href=%s" % (l["text"], l["shown"],
                                                      l["href"]))
        print("\n(%d links in all; nothing was typed or clicked)"
              % len(got["links"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
