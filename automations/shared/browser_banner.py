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

DEFAULT_TITLE = "DON'T CLOSE OR CLICK THIS WINDOW"

# WHY THE SECOND LINE EXISTS. The first version only said "do not close", and
# the helpful thing for an owner to do with a half-finished login is finish it
# -- type their password, tick the security box. That BREAKS it: the check
# clears itself only if it is left alone (Megan 2026-09-11: "the lucy bot has
# to be able to clear the pass"), and a human touching the box or the fields
# mid-sign-in is how the login fails in a way that looks like a wrong
# password. So the bar asks for the one thing that is actually needed:
# nothing.
DEFAULT_DETAIL = ("Lucy Reports is signing itself in — please don't type "
                  "your password or tick the security box. It clears on its "
                  "own and this window closes by itself.")

DEFAULT_MESSAGE = DEFAULT_TITLE

_SCRIPT = """
(parts) => {
  const ID = '__alphalete_alerts_banner';
  const paint = () => {
    if (!document.body || document.getElementById(ID)) return;
    const bar = document.createElement('div');
    bar.id = ID;
    bar.style.cssText = [
      'position:fixed', 'top:0', 'left:0', 'right:0',
      'z-index:2147483647',
      'background:#b30000', 'color:#ffffff',
      'font:15px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif',
      'padding:12px 16px', 'text-align:center',
      'letter-spacing:.2px', 'box-shadow:0 2px 6px rgba(0,0,0,.35)',
      'pointer-events:none'
    ].join(';');
    const head = document.createElement('div');
    head.textContent = parts.title;
    head.style.cssText = 'font-weight:800;font-size:16px;letter-spacing:.6px';
    const sub = document.createElement('div');
    sub.textContent = parts.detail;
    sub.style.cssText = 'font-weight:500;font-size:13.5px;opacity:.95;margin-top:3px';
    bar.appendChild(head);
    if (parts.detail) bar.appendChild(sub);
    document.body.appendChild(bar);
  };
  // Three ways in, because the page may be at any stage when this runs and a
  // postback can replace the body under us without a navigation event.
  if (document.readyState !== 'loading') paint();
  document.addEventListener('DOMContentLoaded', paint);
  setInterval(paint, 1000);
}
"""


def attach(context, message: str = DEFAULT_TITLE,
           detail: str = DEFAULT_DETAIL) -> None:
    """Put the bar on every page this context opens, now and later.

    Never raises: a missing banner must not be the reason a report fails. The
    window being unexplained is bad; the run dying because we could not explain
    it is worse.
    """
    parts = {"title": message, "detail": detail}
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
