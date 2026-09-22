"""Does SaraPlus accept a HIDDEN login from this machine, and in which browser?

    python -m automations.shared.saraplus_probe            # playwright's headless shell
    python -m automations.shared.saraplus_probe --chromium # full Chromium, new headless

WHY (2026-09-22). Khalil's ICD machine: the person's visible window signs in
fine; the hidden read, on the same profile, gets the login page handed back
with NO error and no redirect, 130+ times. The hidden read had just moved
from the headless shell to full Chromium (channel="chromium"). This runs the
SAME shared login on a Lucy with the sales board's own account, in each
browser, on a THROWAWAY profile, and prints where it landed -- so the
difference (if it is the browser) shows up on a machine we can see, not
the office's. Read-only: nothing on SaraPlus is changed; the throwaway
profile is deleted after.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chromium", action="store_true",
                    help="full Chromium (channel='chromium'), hidden")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args(argv)
    from patchright.sync_api import sync_playwright
    from automations.shared import saraplus as S
    from automations.alphalete_sales_board import config as C
    cr = C.creds()
    prof = Path(tempfile.mkdtemp(prefix="sara-probe-"))
    kw = {"headless": not args.headed, "args": ["--disable-sync"]}
    if args.chromium:
        kw["channel"] = "chromium"
    print("browser: %s%s" % ("full chromium" if args.chromium else "headless shell",
                             "" if kw["headless"] else " (headed)"))
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(str(prof), **kw)
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                print("ua: %s" % page.evaluate("() => navigator.userAgent"))
                try:
                    base = S._login(page, cr["email"], cr["password"],
                                    creds_hint="the sales board login", log=print)
                    print("RESULT: logged in -> %s" % base)
                except S.SaraError as e:
                    print("RESULT: %s: %s" % (type(e).__name__, str(e)[:700]))
                print("final url: %s" % page.url)
            finally:
                ctx.close()
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
