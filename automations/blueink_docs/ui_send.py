"""Send a Blue Ink packet by driving the web app, the way a person does.

WHY NOT THE API: on "Blueink Unlimited Annual", every bundle the API creates is
billed as a **Bulk Envelope** and that allowance is 50 PER YEAR (spent; resets
12/20/26). Both API paths were tested and both 403 -- see config.py. Sends made
in the web app draw on the **Envelopes** bucket, which is unlimited on this plan
and is where the team's own ~50-90/week already go. API Access is an Enterprise-
only feature here, so this is the route that works on the plan Alphalete has.

THE FLOW (mapped against the live app 2026-08-24). Every step is keyed on Blue
Ink's own `data-tid` attributes rather than button text, so a copy change
doesn't break the run:

  /dashboard/templates
    -> row containing the template name -> "Use this Template"
    -> /dashboard/edit/<bundle>/signers        <- draft bundle exists from here
    -> [data-tid=nub-signerSearch] input       type the email
    -> button[data-tid=nub-addSigner]          "Add New Signer"
    -> input[name=given_name] / [name=family_name], then
       button[data-tid=nub-pktPerson-saveName]
    -> button[data-tid=nub-create-prepare]     -> /prepare  (template fields
                                                  are already placed)
    -> button[data-tid=nub-create-review]      -> /review
    -> button[data-tid=nub-create-send]        SENDS. No undo.

The signer form is TRANSIENT -- reloading the draft URL drops back to the search
box -- so one person is one uninterrupted pass. The browser is reused across the
batch (relaunching per person would roughly double an already ~hour-long run).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from automations.blueink_docs import session as S

TEMPLATES_URL = "https://secure.blueink.com/dashboard/templates"

# The app long-polls, so `networkidle` never settles -- every wait here is for a
# specific element or URL instead.
NAV_TIMEOUT = 90_000
STEP_TIMEOUT = 60_000

_BUNDLE_RE = re.compile(r"/dashboard/edit/([A-Za-z0-9]+)/")


class UISendError(RuntimeError):
    pass


@dataclass
class UIResult:
    bundle_id: str
    status: str


def _bundle_id(url: str) -> str:
    m = _BUNDLE_RE.search(url or "")
    return m.group(1) if m else ""


def open_browser(p, *, headless: bool = True):
    """A logged-in browser for the whole batch. Caller closes it."""
    return S.open_context(p, headless=headless)


def send_one(page, *, first: str, last: str, email: str,
             template_name: str, really_send: bool = False) -> UIResult:
    """Drive one packet end to end.

    really_send=False walks every step INCLUDING loading the review screen, and
    stops with the Send button in front of it -- so a dry run exercises the real
    flow (and catches a UI change) without mailing anyone. The draft it leaves
    behind is harmless; Blue Ink drafts send nothing.
    """
    page.goto(TEMPLATES_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    page.wait_for_selector("xpath=//button[contains(., 'Use this Template')]",
                           timeout=STEP_TIMEOUT)

    row = page.query_selector(f"xpath=//tr[contains(., {_xpath_literal(template_name)})]")
    if not row:
        raise UISendError(
            f"No template row named {template_name!r} on the Envelope Templates "
            "page. Has it been renamed?")
    use = row.query_selector("xpath=.//button[contains(., 'Use this Template')]")
    if not use:
        raise UISendError(f"Template {template_name!r} has no 'Use this Template' button.")
    use.click()

    page.wait_for_url("**/signers", timeout=NAV_TIMEOUT)
    page.wait_for_selector("[data-tid='nub-signerSearch'] input", timeout=STEP_TIMEOUT)
    bundle = _bundle_id(page.url)

    # --- signer ---------------------------------------------------------
    box = page.query_selector("[data-tid='nub-signerSearch'] input")
    box.click()
    box.type(email, delay=40)
    # The "Add New Signer" button only appears once the search has come back
    # empty -- waiting for the BUTTON is what makes this deterministic.
    page.wait_for_selector("button[data-tid='nub-addSigner']", timeout=STEP_TIMEOUT)
    page.click("button[data-tid='nub-addSigner']")

    page.wait_for_selector("input[name='given_name']", timeout=STEP_TIMEOUT)
    page.fill("input[name='given_name']", first)
    page.fill("input[name='family_name']", last)
    page.click("button[data-tid='nub-pktPerson-saveName']")

    # --- prepare --------------------------------------------------------
    page.wait_for_selector("button[data-tid='nub-create-prepare']", timeout=STEP_TIMEOUT)
    page.click("button[data-tid='nub-create-prepare']")
    page.wait_for_url("**/prepare", timeout=NAV_TIMEOUT)
    page.wait_for_selector("button[data-tid='nub-create-review']", timeout=STEP_TIMEOUT)

    # --- review ---------------------------------------------------------
    page.click("button[data-tid='nub-create-review']")
    page.wait_for_url("**/review", timeout=NAV_TIMEOUT)
    page.wait_for_selector("button[data-tid='nub-create-send']", timeout=STEP_TIMEOUT)

    # Confirm the review screen really is addressed to this person before we
    # commit -- a mis-wired step would otherwise mail the wrong human.
    body = " ".join((page.inner_text("body") or "").split())
    if email.lower() not in body.lower():
        raise UISendError(
            f"Review screen for bundle {bundle} doesn't mention {email} -- "
            "refusing to send. The wizard may have changed.")

    if not really_send:
        return UIResult(bundle_id=bundle, status="draft (dry run, not sent)")

    page.click("button[data-tid='nub-create-send']")
    # Sending navigates off /review. If it doesn't, treat it as a failure rather
    # than reporting a send we can't see evidence of.
    try:
        page.wait_for_url(lambda u: "/review" not in u, timeout=NAV_TIMEOUT)
    except Exception:
        raise UISendError(
            f"Clicked Send on bundle {bundle} but the page stayed on /review. "
            "Check the Blue Ink dashboard before rerunning -- it may or may not "
            "have gone out.")
    return UIResult(bundle_id=bundle, status="sent")


def _xpath_literal(s: str) -> str:
    """Quote a string for XPath, including one containing a quote character."""
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = s.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"
