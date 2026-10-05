"""Sign this office into AppStream with THEIR login, and prove it worked.

FOR RESUME PUSHING ON THE OFFICE'S OWN COMPUTER (Carlos 2026-10-05: Lucy
"takes up the screen while pushing" on Lucy 2, and one machine is slow across
that many offices). The push moves onto the office's relay machine, so the
machine needs an AppStream login of its own.

THEIR LOGIN, NEVER OURS. An office's own AppStream account sees only that
office, and Send-to-AI reaches whatever the ACCOUNT can see -- so an account
that cannot see another office cannot push it (lucy-login-standard rule 3).

SAME FORM AS OWNERVILLE, SAME TRICK: username -> NEXT -> wait 30s -> password
-> wait 30s -> submit. The security box clears itself if left alone; nobody has
to be at the machine. The window is visible only because the box does not
clear for a headless browser (proven for OwnerVille, 2026-09-11).

PROOF IS THE OFFICE CONSOLE (#searchMC), not a page that loaded. A wrong
username does not error -- the form submits and a page renders -- so anything
short of the console is a failure.

    python -m automations.icd_alerts.as_signin
"""
from __future__ import annotations

import sys

from automations.icd_alerts import config as C
from automations.shared import ownerville_knocks as K

AS_HOME = "https://applicantstream.com/"
AS_BASE = "https://applicantstream.com/index.cfm"
CONSOLE = "#searchMC"


def _rqst_tokens(ctx):
    return [c["name"][len("rqst_"):] for c in ctx.cookies()
            if c.get("name", "").startswith("rqst_")]


def _on_console(page, ctx) -> bool:
    """Already on the console, or one token hop away from it."""
    if page.locator(CONSOLE).count() > 0:
        return True
    for tok in _rqst_tokens(ctx):
        try:
            page.goto("%s?rqst=%s&p=701" % (AS_BASE, tok),
                      wait_until="domcontentloaded", timeout=25_000)
            page.wait_for_selector(CONSOLE, timeout=10_000)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def run(log=print) -> int:
    """0 = signed in and on the office console. 1 = not. 2 = no login saved."""
    cr = C.appstream_creds()
    if not cr:
        log("no AppStream login saved on this computer")
        return 2

    from patchright.sync_api import sync_playwright

    C.AS_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    marker = C.AS_PROFILE_DIR / ".appstream_account"
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(C.AS_PROFILE_DIR), headless=False, args=["--disable-sync"])
        try:
            from automations.shared import browser_banner
            browser_banner.attach(ctx)
        except Exception:  # noqa: BLE001 — a missing banner never blocks this
            pass
        try:
            # A SESSION LEFT BY A DIFFERENT USERNAME IS NOT THIS ONE. Reusing
            # it would "pass" as whoever signed in last (Lucy 2, 2026-08-20).
            try:
                last = marker.read_text().strip() if marker.exists() else ""
            except OSError:
                last = ""
            if last != cr["username"]:
                ctx.clear_cookies()

            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            if last == cr["username"] and _on_console(page, ctx):
                log("AppStream session still good")
                return 0

            log("signing in to AppStream as %s" % cr["username"])
            try:
                K.login(page, cr["username"], cr["password"], log=log,
                        url=AS_HOME)
            except Exception as e:  # noqa: BLE001
                log("the AppStream sign-in page did not behave (%s)"
                    % type(e).__name__)
                return 1
            if not _on_console(page, ctx):
                log("signed in, but the AppStream office page never opened -- "
                    "usually a mistyped username or password")
                return 1
            try:
                marker.write_text(cr["username"])
            except OSError:
                pass
            log("AppStream is signed in")
            return 0
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    sys.exit(run())
