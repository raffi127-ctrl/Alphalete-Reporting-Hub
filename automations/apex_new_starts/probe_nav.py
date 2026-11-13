"""Why can a run reach the employment tab and no other? READ ONLY.

Three attempts have failed differently, which means more than one thing is
wrong and guessing has run out (2026-11-12):

  * the page's own anchor click    -- the URL did not change at all
  * a driver click on that anchor  -- the URL did not change at all
  * window.location.assign(url)    -- landed on /Identity/.../ChangePassword

and yet in the very first run the profile tab WAS reached, right after a
person pressed Save. So this measures rather than theorises:

  1. is there an Angular/ui-router injector on a record, really
  2. what the user-profile anchor is, and what a REAL click does to the URL
  3. the whole redirect chain a direct navigation goes through, with statuses
  4. what the change-password page actually demands, and whether anything
     on it lets a session past

It types nothing, fills nothing, and presses no Save. It DOES navigate --
that is the thing being measured -- and navigation alone changes no data.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.probe_nav --person "First Last"
"""
from __future__ import annotations

import argparse

from automations.apex_new_starts import apex as AX
from automations.apex_new_starts import drive

ROUTER = r"""() => {
  const out = {angular: !!window.angular, injectors: [], uiRouter: false};
  if (window.angular) {
    for (const sel of ['html', 'body', '[ng-app]', '[ui-view]', 'div']) {
      const el = document.querySelector(sel);
      let got = false;
      try { got = !!(el && window.angular.element(el).injector()); } catch (e) {}
      if (got) out.injectors.push(sel);
    }
    try {
      const el = document.querySelector('[ui-view]') || document.body;
      const inj = window.angular.element(el).injector();
      out.uiRouter = !!(inj && inj.has && inj.has('$state'));
    } catch (e) {}
  }
  return out;
}"""

ANCHOR = r"""(w) => {
  const a = [...document.querySelectorAll('a[href]')]
    .find(x => (x.getAttribute('href') || '').indexOf(w) >= 0);
  if (!a) return null;
  a.setAttribute('data-ans-nav', '1');
  return {href: a.getAttribute('href'),
          sref: a.getAttribute('ui-sref') || '',
          target: a.getAttribute('target') || '',
          onclick: (a.getAttribute('ng-click') || a.getAttribute('onclick') || ''),
          cls: a.className || '',
          listeners: typeof window.getEventListeners === 'function' ? 'unknown' : 'n/a'};
}"""

PWPAGE = r"""() => {
  const t = (document.body.innerText || '').replace(/\s+/g, ' ').trim();
  return {
    words: t.slice(0, 400),
    inputs: [...document.querySelectorAll('input')]
      .filter(i => i.type !== 'hidden')
      .map(i => ({name: i.name || i.id || '', type: i.type,
                  required: !!i.required})),
    // anything that looks like a way past it
    outs: [...document.querySelectorAll('a,button')]
      .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim())
      .filter(x => x && x.length < 40),
  };
}"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure Apex navigation.")
    ap.add_argument("--person", required=True)
    a = ap.parse_args()
    who = [{"name": a.person, "find": a.person.split()[-1], "pages": {}}]
    seen = []

    with AX.ApexSession(log=print, login_timeout_s=10 * 60) as s:
        page = s.page
        # EVERY RESPONSE, so a redirect chain can be read off rather than
        # inferred from where it stopped.
        page.on("response", lambda r: seen.append((r.status, r.url))
                if "apex.herbjoyent.com" in r.url and "." not in
                r.url.rsplit("/", 1)[-1] else None)
        s.require_login()
        print("\n--- 4. the change-password page this session lands on ---")
        page.wait_for_timeout(1500)
        if "ChangePassword" in (page.url or ""):
            got = page.evaluate(PWPAGE)
            print("  says: %s" % got["words"][:300])
            print("  boxes: %s" % got["inputs"])
            print("  buttons/links: %s" % got["outs"][:14])
        else:
            print("  not on it — sitting on %s" % page.url)

        for _ in range(4):
            if drive.to_roster(page, log=print):
                break
            page.wait_for_timeout(2500)
        else:
            print("could not reach the roster")
            return 1
        drive.keep_loaded(page, who, log=lambda *x: None)
        pid = page.evaluate(
            "async (p) => { const id = await window.__ansOpen(p);"
            " return id ? String(id) : ''; }", who[0])
        if not pid:
            print("%s is not on the roster right now" % a.person)
            return 1
        page.wait_for_timeout(2500)
        print("\n  opened their record the way a person does: %s" % page.url)

        print("\n--- 1. is there a router on this record ---")
        print("  %s" % page.evaluate(ROUTER))

        want = "/employees/%s/edit/user-profile" % pid
        print("\n--- 2. the user-profile anchor, and a REAL click on it ---")
        info = page.evaluate(ANCHOR, want)
        print("  %s" % info)
        if info:
            before = page.url
            seen.clear()
            try:
                page.click("[data-ans-nav]", timeout=6000)
                page.wait_for_timeout(3000)
            except Exception as e:      # noqa: BLE001
                print("  click raised %s" % type(e).__name__)
            print("  url before: %s" % before)
            print("  url after:  %s" % page.url)
            print("  responses:  %s" % (seen[-6:] or "none"))

        print("\n--- 3. a direct navigation, with its redirect chain ---")
        seen.clear()
        try:
            page.evaluate("(u) => { window.location.assign(u); }", want)
            page.wait_for_load_state("domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)
        except Exception as e:          # noqa: BLE001
            print("  raised %s" % type(e).__name__)
        print("  url after: %s" % page.url)
        for st, u in seen[-8:]:
            print("    %s  %s" % (st, u))

        print("\nNothing was typed and nothing was saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
