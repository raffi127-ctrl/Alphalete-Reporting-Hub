"""Fetch the CURRENT Slack invite link, the way reception does it by hand.

Slack invite links cannot be made permanent -- 30 days maximum, 400 uses, and
no API for generating or reading one (checked against Slack's own docs
2026-08-26). So the only way this report is ever hands-off is to do what the
person did: open the workspace's invite screen every Monday and copy whatever
link is there. Megan's call, 2026-08-26: "there's no point in doing it if it's
not forever."

NOTHING HERE TYPES A PASSWORD. `--login` opens a real browser and waits for a
human to sign in once (SSO and 2FA included); every later run replays the saved
cookies. When the session dies a human re-seeds. That is a ONE-TIME step, not a
weekly one -- the weekly part is what's automated.

    # once per machine, at the keyboard (Lucy 1, as Raf -- needs to be someone
    # who can see the workspace's invite screen)
    python -m automations.slack_skool_email.slack_invite --login

    # is the session still good, and what link would Monday send?
    python -m automations.slack_skool_email.slack_invite --check

    # first run on a new machine: watch it work, and dump what it saw
    python -m automations.slack_skool_email.slack_invite --probe --headed

WHY IT DUMPS RATHER THAN JUST FAILING: a selector timeout tells you a click
path broke but not what the page actually was, and guessing from timeouts cost
Digi Docs three wrong diagnoses before its probe was made to dump the page
instead (see reference_mini_logtail_paging). So every failure here writes the
page's text, its links and a screenshot to output/logs/.

It COPIES the current link; it never resets one. Resetting mints a new link and
kills the old one, which would strand anyone midway through joining -- that is
a decision for a person, not for an 8am timer.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

# From the workspace URL: ao-pbns.slack.com ("AO").
WORKSPACE = "ao-pbns"

STORAGE_STATE = Path(__file__).resolve().parent / ".slack_storage_state.json"
PROFILE_DIR = Path(__file__).resolve().parent / ".slack_profile"
DUMP_DIR = Path(__file__).resolve().parents[2] / "output" / "logs"

# The only shape we will ever accept as an invite link. Anything else -- a
# login page, a help-centre URL, a truncated string -- is refused rather than
# mailed to fifty new starts.
INVITE_RE = re.compile(
    r"https://join\.slack\.com/t/[A-Za-z0-9._-]+/shared_invite/[A-Za-z0-9._~+/-]+")

CLIENT_URL = "https://app.slack.com/client"

# The workspace admin page WAS tried first, on the theory that a
# server-rendered page beats a React modal. It is a dead end for this session
# and the 2026-08-26 discovery run proved why: it answers "Only AO Workspace
# Admins can view this page". The saved session belongs to **Lucy**, who is a
# member and not a workspace admin. The client modal works for her anyway --
# inviting people is not admin-gated on this workspace, only the admin console
# is -- so the modal is the only route, and keeping the admin attempt would
# just spend ten seconds and write a misleading dump every Monday.
#
# Kept as a constant because `--discover` still loads it: the day the fetch
# breaks, "can Lucy see the admin page now?" is worth one line of evidence.
ADMIN_INVITES_URL = "https://{}.slack.com/admin/invites".format(WORKSPACE)


class InviteError(RuntimeError):
    pass


def _sync_api():
    """patchright if present (stealth), else plain playwright."""
    try:
        from patchright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        from playwright.sync_api import sync_playwright
        return sync_playwright


def have_session() -> bool:
    return STORAGE_STATE.exists() and STORAGE_STATE.stat().st_size > 0


def _require_session() -> None:
    if not have_session():
        raise InviteError(
            "No Slack session on this machine. At the keyboard here, run:\n"
            "    python -m automations.slack_skool_email.slack_invite --login\n"
            "and sign in to the AO workspace as someone who can invite people.")


def login() -> int:
    sync_playwright = _sync_api()
    print("Opening Slack. Sign in to the AO workspace -- SSO and 2FA are\n"
          "fine, take as long as you need. This waits until it sees the\n"
          "client, then saves the session.\n")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=False, no_viewport=True,
            args=["--window-size=1440,1000", "--window-position=0,0",
                  "--disable-sync"])       # never sync into a human's Chrome
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(CLIENT_URL, wait_until="domcontentloaded")
        print("waiting for sign-in...", flush=True)
        try:
            page.wait_for_url("**/client/**", timeout=600_000)
        except Exception:
            print("\nDidn't reach the Slack client. Nothing saved -- rerun "
                  "when you're ready.", file=sys.stderr)
            ctx.close()
            return 1
        ctx.storage_state(path=str(STORAGE_STATE))
        STORAGE_STATE.chmod(0o600)
        ctx.close()
    print("\nSaved the Slack session (owner-only). This machine can now read "
          "the invite link without anyone signing in again.")
    return 0


def _dump(page, why: str, tag: str = "") -> str:
    """Write what we actually saw. The whole point of the probe.

    Tagged per ATTEMPT, because one dump for the whole run is a dump of
    whichever page happened to be loaded last: the 2026-08-26 probe reported
    "no invite link on the admin page" and then handed back a screenshot of
    the CLIENT, so the admin page was never actually seen.
    """
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    base = DUMP_DIR / "slack-invite-{}{}".format(
        stamp, ("-" + tag) if tag else "")
    try:
        text = page.inner_text("body")[:20000]
    except Exception as exc:
        text = "<could not read body: {}>".format(exc)
    try:
        hrefs = page.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.href).slice(0, 300)")
    except Exception:
        hrefs = []
    base.with_suffix(".txt").write_text(
        "WHY: {}\nURL: {}\n\n--- LINKS ---\n{}\n\n--- TEXT ---\n{}".format(
            why, page.url, "\n".join(hrefs), text), encoding="utf-8")
    try:
        page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
    except Exception:
        pass
    return str(base)


def _inventory(page) -> str:
    """Every data-qa on the page, plus anything that looks clickable and names
    itself. This is what replaces guessing at selectors: Slack renames these,
    and a timeout only ever says "not this one", never "try that one".
    """
    try:
        qa = page.eval_on_selector_all(
            "[data-qa]",
            "els => Array.from(new Set(els.map(e => e.getAttribute('data-qa'))))"
            ".sort()")
    except Exception as exc:
        qa = ["<could not read data-qa: {}>".format(exc)]
    try:
        clickable = page.eval_on_selector_all(
            "button,[role=button],a[href]",
            "els => els.map(e => ({"
            "  qa: e.getAttribute('data-qa') || '',"
            "  label: (e.getAttribute('aria-label') || e.title || "
            "          (e.innerText||'').trim().slice(0,60))"
            "})).filter(x => x.label).slice(0, 400)")
    except Exception as exc:
        clickable = [{"qa": "", "label": "<could not read: {}>".format(exc)}]

    lines = ["--- data-qa values on this page ({}) ---".format(len(qa))]
    lines += ["  {}".format(v) for v in qa]
    lines.append("")
    lines.append("--- clickable things, by name ({}) ---".format(len(clickable)))
    for c in clickable:
        lines.append("  {:50} data-qa={}".format(
            (c.get("label") or "").replace("\n", " / ")[:50], c.get("qa") or "-"))
    return "\n".join(lines)


def discover(*, headless: bool = False, logfn=print) -> int:
    """Load each route and write down exactly what is on it.

    Run this ONCE when a click path breaks. It changes nothing and clicks
    nothing; it just produces the two files that say which selector to use.
    """
    _require_session()
    sync_playwright = _sync_api()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless, args=["--window-size=1440,1000", "--disable-sync"])
        ctx = browser.new_context(
            storage_state=str(STORAGE_STATE),
            viewport={"width": 1440, "height": 1000},
            permissions=["clipboard-read", "clipboard-write"])
        page = ctx.new_page()
        try:
            for tag, url, wait in (("admin", ADMIN_INVITES_URL, 4000),
                                   ("client", CLIENT_URL, 8000)):
                logfn("loading {} -> {}".format(tag, url))
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                    page.wait_for_timeout(wait)
                except Exception as exc:
                    logfn("  couldn't load: {}".format(exc))
                logfn("  landed on: {}".format(page.url))
                link = _scan(page)
                logfn("  invite link visible here: {}".format(link or "no"))
                where = _dump(page, "discover: {}".format(tag), tag)
                Path(where + ".inventory.txt").write_text(
                    "URL: {}\n\n{}".format(page.url, _inventory(page)),
                    encoding="utf-8")
                logfn("  wrote {}.txt / .png / .inventory.txt".format(where))
        finally:
            browser.close()
    logfn("\nSend me the two .inventory.txt files and I'll wire the real "
          "selector.")
    return 0


def _scan(page):
    """Any invite link visible on this page, in its HTML or its inputs."""
    try:
        html = page.content()
    except Exception:
        html = ""
    m = INVITE_RE.search(html or "")
    if m:
        return m.group(0)
    # React often holds it in an input's VALUE, which isn't in the HTML.
    try:
        vals = page.eval_on_selector_all(
            "input,textarea", "els => els.map(e => e.value || '')")
    except Exception:
        vals = []
    for v in vals:
        m = INVITE_RE.search(v or "")
        if m:
            return m.group(0)
    return ""


def _from_clipboard(page):
    """What 'Copy Invite Link' actually put on the clipboard."""
    try:
        return page.evaluate("navigator.clipboard.readText()") or ""
    except Exception:
        return ""


def _try_admin_page(page, log) -> str:
    log("trying the admin invites page: {}".format(ADMIN_INVITES_URL))
    page.goto(ADMIN_INVITES_URL, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(3000)
    log("  landed on {}".format(page.url))
    if "/signin" in page.url or "/workspace-signin" in page.url:
        raise InviteError(
            "Slack asked this machine to sign in again -- the saved session "
            "has expired. A human re-seeds it at the keyboard with --login.")
    return _scan(page)


#: An open Slack pop-up. Its overlay sits over the whole client and swallows
#: every click underneath it.
POPUP_OVERLAY = ".ReactModal__Overlay--after-open"
#: Ways to close one, all of them "dismiss" answers: none accepts, enables or
#: changes anything.
POPUP_CLOSE = (
    "[data-qa='sk_close_modal_button']",
    POPUP_OVERLAY + " button[aria-label='Close']",
    POPUP_OVERLAY + " button:has-text('Not now')",
    POPUP_OVERLAY + " button:has-text('Maybe later')",
    POPUP_OVERLAY + " button:has-text('Skip')",
    POPUP_OVERLAY + " button:has-text('Got it')",
)


def _dismiss_popups(page, log, tries: int = 3) -> None:
    """Close whatever Slack pop-up is covering the client.

    WHY (2026-11-21): the 8am send to Monday's new starts died on
    `couldn't open the workspace menu`. The button was right where it always is
    (`workspace_actions_button`, "AO Actions", visible and enabled). Playwright's
    own log said a ReactModal__Overlay "intercepts pointer events": Slack had
    opened a pop-up (an announcement, a prompt) over the page, and 15 seconds
    of retries all hit the pop-up instead. Close it, then click."""
    for _ in range(tries):
        try:
            if not page.query_selector(POPUP_OVERLAY):
                return
        except Exception:                                   # noqa: BLE001
            return
        try:
            title = (page.inner_text(POPUP_OVERLAY) or "").strip().split("\n")[0]
        except Exception:                                   # noqa: BLE001
            title = ""
        log("  a Slack pop-up is covering the page ({}) -- closing it".format(
            title[:60] or "untitled"))
        for sel in POPUP_CLOSE:
            try:
                page.click(sel, timeout=1500)
                break
            except Exception:                               # noqa: BLE001
                continue
        else:
            page.keyboard.press("Escape")
        page.wait_for_timeout(1000)


def _try_client_modal(page, log) -> str:
    """The path the Loom shows: workspace menu -> Invite people -> Copy."""
    log("trying the client invite modal")
    page.goto(CLIENT_URL, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(6000)          # the client boots slowly
    log("  landed on {}".format(page.url))
    # An expired session lands on a sign-in page, where the menu click below
    # can only time out. Say which it is (2026-11-21: a bare 15s timeout left
    # nobody able to tell a dead session from a moved button).
    if any(s in page.url for s in ("/signin", "/workspace-signin",
                                   "slack.com/get-started", "/ssb/")):
        raise InviteError(
            "Slack asked this machine to sign in again -- the saved session "
            "has expired. A human re-seeds it at the keyboard with --login.")

    # The workspace menu. `workspace_actions_button` ("AO Actions") is what the
    # 2026-08-26 discovery run actually found on the page; the guessed
    # `team-menu-trigger` / `team_menu` did not exist. Keyed on data-qa rather
    # than button text so a copy change doesn't break it. The client can take
    # longer than 6s to draw the sidebar, so wait for it once, then try the
    # known name and the aria-label it carries ("AO Actions").
    menu = "[data-qa='workspace_actions_button'], button[aria-label='AO Actions']"
    try:
        page.wait_for_selector(menu, state="visible", timeout=45_000)
        _dismiss_popups(page, log)
        page.click(menu, timeout=15_000)
        page.wait_for_timeout(1500)
    except Exception as exc:
        raise InviteError("couldn't open the workspace menu (on {}): {}".format(
            page.url, str(exc).split("\n")[0]))

    # What the menu offers THIS account. Whether "Invite people" is here at all
    # depends on who the session belongs to and on the workspace's invitation
    # permissions -- so when it's missing, say what WAS on the menu rather than
    # reporting a bare timeout.
    try:
        items = page.eval_on_selector_all(
            "[role=menuitem],[role=menu] button,[role=menu] a",
            "els => els.map(e => (e.innerText||'').trim()).filter(Boolean)")
    except Exception:
        items = []

    try:
        page.click("text=/Invite people to/i", timeout=8000)
    except Exception as exc:
        raise InviteError(
            "the workspace menu has no 'Invite people' for this account. "
            "It offered: {}. ({})".format(
                "; ".join(items) or "nothing readable", str(exc).split("\n")[0]))

    page.wait_for_timeout(2500)
    found = _scan(page)
    if found:
        return found
    return _link_from_modal(page, log)


#: The dialog opens on its Email tab since about 2026-11-02; the link lives on
#: the 'Invite link' tab next to it.
LINK_TAB_SELECTORS = (
    "[role=tab]:has-text('Invite link')",
    "button:has-text('Invite link')",
    "text=/^\s*Invite link\s*$/i",
)
COPY_SELECTORS = (
    "[data-qa='copy-invite-link']",
    "button:has-text('Copy Invite Link')",
    "button:has-text('Copy invite link')",
    "button:has-text('Copy link')",
    "button:has-text('Copy')",
)


def _link_from_modal(page, log) -> str:
    """The invite link off the open dialog: its link tab, then Copy."""
    for sel in LINK_TAB_SELECTORS:
        try:
            page.click(sel, timeout=4000)
            page.wait_for_timeout(1500)
            log("  opened the invite link tab")
            break
        except Exception:
            continue
    found = _scan(page)
    if found:
        return found
    # Not in the DOM -- click Copy and read the clipboard instead.
    for sel in COPY_SELECTORS:
        try:
            page.click(sel, timeout=3000)
            page.wait_for_timeout(1200)
        except Exception:
            continue
        m = INVITE_RE.search(_from_clipboard(page))
        if m:
            return m.group(0)
    return ""


def fetch(*, headless: bool = True, logfn=print, dump_always: bool = False) -> str:
    """This week's invite link, or raise. Never returns something unvalidated."""
    _require_session()
    sync_playwright = _sync_api()
    problems = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless, args=["--window-size=1440,1000", "--disable-sync"])
        ctx = browser.new_context(
            storage_state=str(STORAGE_STATE),
            viewport={"width": 1440, "height": 1000},
            permissions=["clipboard-read", "clipboard-write"])
        page = ctx.new_page()
        try:
            for attempt in (_try_client_modal,):
                try:
                    link = attempt(page, logfn)
                except Exception as exc:
                    problems.append(str(exc) if isinstance(exc, InviteError)
                                    else "{}: {}".format(attempt.__name__, exc))
                    # The page as it was when the click path broke. The
                    # docstring always promised this, but only the SUCCESS
                    # path dumped, so the 2026-11-21 failure left no evidence.
                    try:
                        logfn("dumped: {}".format(_dump(
                            page, "FAILED {}".format(attempt.__name__),
                            attempt.__name__.strip("_") + "-failed")))
                    except Exception:                       # noqa: BLE001
                        pass
                    continue
                else:
                    # Evidence for THIS attempt, before the next one navigates
                    # away and takes the scene of the crime with it.
                    _dump(page, "after {}".format(attempt.__name__),
                          attempt.__name__.strip("_"))
                if link:
                    if dump_always:
                        logfn("dumped: {}".format(
                            _dump(page, "probe, found a link", "found")))
                    logfn("found: {}".format(link))
                    return link
                problems.append("{}: no invite link on the page"
                                .format(attempt.__name__))
            raise InviteError(
                "Couldn't read the Slack invite link.\n  " +
                "\n  ".join(problems) +
                "\nEach attempt dumped what it saw to output/logs/"
                "slack-invite-*.txt (and .png).\nIf a selector has moved, run "
                "`--discover` -- it lists every data-qa on each page instead "
                "of guessing.")
        finally:
            browser.close()


def check(headless: bool = True) -> int:
    try:
        link = fetch(headless=headless)
    except InviteError as exc:
        print(exc)
        return 1
    print("session is GOOD -- Monday would send this link:\n  {}".format(link))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--login", action="store_true",
                    help="open a browser so a human can sign in once")
    ap.add_argument("--check", action="store_true",
                    help="fetch the link now and print it; sends nothing")
    ap.add_argument("--probe", action="store_true",
                    help="like --check but always dumps what it saw")
    ap.add_argument("--discover", action="store_true",
                    help="click nothing; just write down what is on each page "
                         "(run this when a selector has moved)")
    ap.add_argument("--headed", action="store_true",
                    help="show the browser")
    args = ap.parse_args(argv)

    if args.login:
        return login()
    if args.discover:
        return discover(headless=not args.headed)
    if args.probe:
        try:
            link = fetch(headless=not args.headed, dump_always=True)
        except InviteError as exc:
            print(exc)
            return 1
        print(link)
        return 0
    if args.check:
        return check(headless=not args.headed)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
