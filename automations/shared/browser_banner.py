"""A red "do not close this window" bar, for any browser an ICD can see.

WHY IT EXISTS. These agents run HEADLESS, so on a normal day nothing appears
on the owner's screen at all. But headless is not a promise: a `--headful` run
while somebody is helping them, or a SaraPlus passcode challenge that has to be
watched, puts a real Chrome window in front of a person who did not open it.
Left unexplained, the reasonable thing for them to do is close it -- and they
would be closing their own alerts, with no idea that is what happened.

INJECTED, NOT DRAWN BY US. `add_init_script` re-runs on every navigation, which
matters because the SaraPlus hub reloads itself constantly through postbacks
and a banner added once would vanish on the first one. Patchright evaluates in
an ISOLATED WORLD, but the DOM is shared -- only page globals are hidden -- so
appending an element works and touching the page's own scripts would not.

NEVER on a headless run: there is no one to read it, and it would sit on top of
the controls the report is about to click.
"""
from __future__ import annotations

DEFAULT_TITLE = "DO NOT MANUALLY LOG IN OR CLEAR CLOUDFLARE"

# THE HEADLINE IS THE INSTRUCTION, and it is deliberately enormous (Megan
# 2026-09-12: "really really big").
#
# The first version only said "do not close", and the helpful thing for an
# owner to do with a half-finished login is FINISH it -- type their password,
# tick the security box. That breaks it: the check clears itself only if it is
# left alone (Megan 2026-09-11: "the lucy bot has to be able to clear the
# pass"), and a human touching the box or the fields mid-sign-in fails the
# login in a way that looks exactly like a wrong password -- which then sends
# somebody off re-entering a password that was never wrong.
#
# So the bar names the two specific things not to do, rather than a polite
# general request nobody reads.
DEFAULT_DETAIL = ("Lucy is signing herself in. This window closes by itself — "
                  "usually within a minute. Just leave it alone.")

DEFAULT_MESSAGE = DEFAULT_TITLE

RED = "#b30000"      # wait -- Lucy is working, do not touch
GREEN = "#1b7f3b"    # your turn -- do the one thing the bar says

# The bar can CHANGE mid-run (show() below): red while Lucy works, green when
# it is the person's turn (Eve 2026-11-23, Apex setup with Jairo: "que Lucy
# avise las esperas"). The current words live in sessionStorage -- shared with
# the page's world, per tab, and it survives the navigations of a sign-in --
# so the bar a new page paints is the one last shown, not the first one.
_KEY = "__alphalete_alerts_banner_now"

_SCRIPT = """
(parts) => {
  const ID = '__alphalete_alerts_banner';
  const KEY = '%s';
  const now = () => {
    try {
      const v = JSON.parse(sessionStorage.getItem(KEY) || 'null');
      if (v && v.title) return v;
    } catch (e) {}
    return parts;
  };
  const paint = () => {
    if (!document.body) return;
    const want = now();
    let bar = document.getElementById(ID);
    if (bar && bar.dataset.title === want.title
        && bar.dataset.detail === (want.detail || '')
        && bar.dataset.color === (want.color || '')) return;
    if (bar) bar.remove();
    bar = document.createElement('div');
    bar.id = ID;
    bar.dataset.title = want.title;
    bar.dataset.detail = want.detail || '';
    bar.dataset.color = want.color || '';
    bar.style.cssText = [
      'position:fixed', 'top:0', 'left:0', 'right:0',
      'z-index:2147483647',
      'background:' + (want.color || '%s'), 'color:#ffffff',
      'font:15px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif',
      'padding:22px 18px', 'text-align:center',
      'letter-spacing:.2px', 'box-shadow:0 2px 6px rgba(0,0,0,.35)',
      'pointer-events:none'
    ].join(';');
    const head = document.createElement('div');
    head.textContent = want.title;
    head.style.cssText = [
      'font-weight:900',
      // Scales with the window and never smaller than 26px: this is the one
      // sentence the whole bar exists to deliver.
      'font-size:clamp(26px,3.4vw,44px)',
      'line-height:1.12',
      'letter-spacing:.5px',
      'text-transform:uppercase'
    ].join(';');
    const sub = document.createElement('div');
    sub.textContent = want.detail || '';
    sub.style.cssText = 'font-weight:600;font-size:16px;opacity:.95;margin-top:8px';
    bar.appendChild(head);
    if (want.detail) bar.appendChild(sub);
    document.body.appendChild(bar);
  };
  // Three ways in, because the page may be at any stage when this runs and a
  // postback can replace the body under us without a navigation event. The
  // timer also picks up a show() within a second.
  if (document.readyState !== 'loading') paint();
  document.addEventListener('DOMContentLoaded', paint);
  setInterval(paint, 1000);
}
""" % (_KEY, RED)


def attach(context, message: str = DEFAULT_TITLE,
           detail: str = DEFAULT_DETAIL, color: str = RED) -> None:
    """Put the bar on every page this context opens, now and later.

    Never raises: a missing banner must not be the reason a report fails. The
    window being unexplained is bad; the run dying because we could not explain
    it is worse.
    """
    parts = {"title": message, "detail": detail, "color": color}
    try:
        context.add_init_script(_SCRIPT.strip(), parts)
    except TypeError:
        # Older bindings take no argument for add_init_script.
        try:
            import json as _json
            context.add_init_script(
                "(%s)(%s)" % (_SCRIPT.strip(), _json.dumps(parts)))
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass


def show(page, message: str, detail: str = "", color: str = RED) -> None:
    """Change the bar on this tab NOW, and on every page it loads after.

    Same never-raises rule as attach(): a page mid-navigation just picks the
    words up from sessionStorage on its next paint.
    """
    import json as _json
    want = _json.dumps({"title": message, "detail": detail, "color": color})
    try:
        page.evaluate("(v) => { try { sessionStorage.setItem('%s', v); } "
                      "catch (e) {} }" % _KEY, want)
    except Exception:  # noqa: BLE001
        pass
