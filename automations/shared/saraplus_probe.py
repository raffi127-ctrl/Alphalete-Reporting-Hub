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
    ap.add_argument("--reuse", action="store_true",
                    help="after a real login, CLOSE the browser, reopen the same "
                         "profile and see whether SaraPlus still treats it as signed "
                         "in -- the question behind Kash's 'Only one login at a time' "
                         "(2026-09-30): the ICD reader signs in with the password on "
                         "every 2-minute sweep. Read-only.")
    ap.add_argument("--columns", metavar="YYYY-MM-DD",
                    help="after the login, run the Order Dashboard for that ONE "
                         "day under each Service and print every grid's HEADER "
                         "labels, plus the Service options. Read-only. Built "
                         "2026-10-22 for Carlos: the credit-check alert counts "
                         "Records (got on the tablet), and NL counts upgrades, "
                         "tablets and wearables -- this shows which columns "
                         "SaraPlus really has to split them.")
    ap.add_argument("--rows", metavar="SERVICE",
                    help="with --columns: only the Services whose name contains "
                         "this (case-insensitive, e.g. 'internet' or 'AT&T'), and "
                         "print each rep row's NON-ZERO cells by header label.")
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
                base = None
                try:
                    base = S._login(page, cr["email"], cr["password"],
                                    creds_hint="the sales board login", log=print)
                    print("RESULT: logged in -> %s" % base)
                except S.SaraError as e:
                    print("RESULT: %s: %s" % (type(e).__name__, str(e)[:700]))
                print("final url: %s" % page.url)
                landed = page.url
                # _login's return value, NOT page.url: by the time it returns
                # the page can sit on .../e/(S(..)) with no DealerPages/ in it
                # (all four --columns runs on 2026-10-22 skipped the dump that
                # way), and the Reporting Hub is a SIBLING of DealerPages/.
                if args.columns and base:
                    _dump_columns(page, base if base.endswith("/") else base + "/",
                                  args.columns, args.rows)
            finally:
                ctx.close()
            if args.reuse:
                # SAME PROFILE, NEW BROWSER: what does SaraPlus do with the
                # cookies it left behind? Three landings are tried, and each
                # is reported as the url it ended on plus whether the login
                # form is on it.
                ctx = p.chromium.launch_persistent_context(str(prof), **kw)
                try:
                    page = ctx.new_page()
                    for label, url in (("dealer home", landed.split("DealerPages/")[0] + "DealerPages/" if "DealerPages/" in landed else landed),
                                       ("login page", S.LOGIN_URL)):
                        try:
                            page.goto(url, wait_until="networkidle", timeout=60000)
                            page.wait_for_timeout(2500)
                            form = page.locator("#ctl00_MainContent_txtUserName").count()
                            print("REUSE %-11s -> %s  | login form on page: %s"
                                  % (label, page.url, "YES" if form else "no"))
                        except Exception as e:  # noqa: BLE001
                            print("REUSE %-11s -> %s: %s" % (label, type(e).__name__, str(e)[:160]))
                finally:
                    ctx.close()
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    return 0


# Every RadGrid master table on the page, with its header labels and body rows.
# BY LABEL, not by the fixed COL_* indices: the point is to see what is there.
_GRIDS_JS = """() => Array.from(document.querySelectorAll('table.rgMasterTable')).map(t => ({
    id: t.id || '',
    headers: Array.from(t.querySelectorAll('thead th')).map(th => (th.innerText || '').trim()),
    rows: Array.from(t.querySelectorAll('tbody tr')).map(tr =>
        Array.from(tr.querySelectorAll('td')).map(td => (td.innerText || '').trim())),
}))"""

_SERVICES_JS = """() => Array.from(document.querySelectorAll('.rcbList li, [class*="rcbItem"]'))
    .map(el => (el.textContent || '').trim()).filter(Boolean)"""


def _dump_columns(page, base: str, day_s: str, only: str = None) -> None:
    """Print, per Service, each grid's header labels (and, with `only`, each
    rep row's non-zero cells). Output is kept short: the mini queue keeps
    only the tail of what a probe prints."""
    import datetime as dt
    from automations.shared import saraplus as S
    day = dt.date.fromisoformat(day_s)
    page.goto(base + S.HUB_PATH, wait_until="domcontentloaded", timeout=S.NAV_TIMEOUT_MS)
    page.wait_for_timeout(2500)
    page.click(S.COMBO_INPUT)
    page.wait_for_timeout(800)
    services = list(dict.fromkeys(page.evaluate(_SERVICES_JS)))
    page.keyboard.press("Escape")
    print("SERVICES: %s" % " | ".join(services))
    # A PIECE OF THE NAME, not the exact label: the mini queue splits a
    # sara_probe row on spaces, so "AT&T Internet" can't arrive whole.
    # `--rows internet` finds it; `--rows AT&T` takes every AT&T service.
    want = (only or "").lower()
    for svc in ([s for s in services if want in s.lower()] if only else services):
        try:
            page.goto(base + S.HUB_PATH, wait_until="domcontentloaded",
                      timeout=S.NAV_TIMEOUT_MS)
            page.wait_for_timeout(2000)
            S._set_telerik_date(page, S.FIELD_START, day)
            S._set_telerik_date(page, S.FIELD_END, day)
            S._select_service(page, svc)
            page.click(S.SUBMIT)
            page.wait_for_timeout(8000)
            grids = page.evaluate(_GRIDS_JS)
        except Exception as e:  # noqa: BLE001
            print("[%s] %s: %s" % (svc, type(e).__name__, str(e)[:120]))
            continue
        for g in grids:
            if not g["rows"]:
                continue
            print("[%s] %s (%d rows): %s" % (svc, g["id"].split("rgOrderDash")[-1],
                                             len(g["rows"]), " | ".join(g["headers"])))
            if not only:
                continue
            # Body rows carry one more leading cell than headers on some grids;
            # align from the RIGHT, where the measure columns are.
            hs = g["headers"]
            for r in g["rows"]:
                if len(r) <= 2 or not r[1].strip().endswith("_Agent"):
                    continue
                off = len(r) - len(hs)
                vals = ["%s=%s" % (hs[i], r[i + off]) for i in range(len(hs))
                        if 0 <= i + off < len(r) and r[i + off] not in ("", "0", "0.00", "$0.00")
                        and i + off > 2]
                print("  %s: %s" % (r[2], ", ".join(vals)))


if __name__ == "__main__":
    sys.exit(main())
