"""The OwnerVille half: add a rep, then generate their document bundle.

⚠️ SELECTORS ARE UNVERIFIED. Every step below is transcribed from Megan's Loom
and screenshots (workflows/digi-docs-onboarding-quizzes.md) and from the paths
headshots/ov_upload.py already proved. Not one of them has been run against a
live page yet — that needs a Lucy 3 run. The STRUCTURE is the settled part: the
step order, what reveals what, and the refusals.

The rule this file exists to encode: **nothing here submits until a control
literally says "Generate Document".** Three buttons on the way look like the
submit and are not. `Generate Bundle` reveals the bundle dropdown; choosing the
bundle reveals the commission boxes; `Get Documents for Selected Bundle` opens
the per-document form. Each step therefore WAITS for its own control to exist
rather than assuming a static form — a form that reveals itself one control at
a time is exactly the shape that produces an automation clicking a button that
is not there and reporting success.
"""
from __future__ import annotations

from automations.digi_docs import config


class Refused(RuntimeError):
    """We stopped on purpose. Never a crash — a refusal names its reason so the
    Slack summary can say who was skipped and why."""


# --- phase 2: add the reps ------------------------------------------------

def add_sales_rep(page, name: str, *, dry_run: bool = True) -> bool:
    """Onboard → View Progress → `+ Add Sales Rep`.

    Employee, then Add. **No team is selected** (Megan 2026-08-25) — that
    dropdown sits between the employee picker and the Activate Now box, both of
    which we do touch, so it reads like a required field and is precisely the
    one an automation would helpfully fill in. Activate Now is checked by
    default; leave it.
    """
    raise NotImplementedError("selectors need a Lucy 3 run")


# --- phase 3: generate the bundle ----------------------------------------

def open_set_status(page, name: str):
    """Search the rep, `Edit`, and return the "<Name> - Set Status" modal.

    Same modal headshots/ov_upload.py already opens for photo uploads, so the
    finding logic is proven: try each campaign, search by LAST name (full names
    filter to zero), and flip "Filter by Activation Date" to Show All when a
    just-added rep isn't in the default 3-week window.
    """
    raise NotImplementedError("selectors need a Lucy 3 run")


def docs_still_owed(modal) -> bool:
    """Is ONBOARDING DOCUMENTS still `REQUIRED ACTION`?

    OwnerVille refuses a second generate for the same rep, so this is NOT what
    prevents a double-send — the platform is. It keeps a re-run QUIET (a batch
    re-run would otherwise walk every already-done rep through nine steps to
    collect a refusal) and keeps that refusal MEANINGFUL: if we only ever
    generate for reps we believe still need it, a "won't allow" means our
    picture is wrong and is worth saying out loud.
    """
    raise NotImplementedError("selectors need a Lucy 3 run")


def open_docs_portal(page, modal):
    """Expand ONBOARDING DOCUMENTS → gray `Access Digital Doc Portal`.

    Opens a NEW TAB. Catch it with `context.expect_page()` — the click returns
    before the page exists, and patchright's evaluate runs in an isolated world,
    so any "just read the current page" shortcut quietly reads the OLD tab.
    """
    raise NotImplementedError("selectors need a Lucy 3 run")


def generate_bundle(tab, name: str, *, dry_run: bool = True) -> None:
    """The reveal chain, in order. Each step waits for the next control.

    1. campaign, then Bundle Type = config.BUNDLE_TYPE
    2. `Generate Bundle`            → reveals the bundle dropdown
    3. Select Bundle = config.BUNDLE → reveals the commission checkboxes
    4. tick config.COMMISSION_BUNDLES_TICK, leave ..._LEAVE alone
    5. `Get Documents for Selected Bundle` → opens the per-document form
    6. verify, scroll, `Generate Document`  ← the only irreversible step

    Two refusals, both cheap, both guarding an expensive mistake:

    * The bundle dropdown must hold exactly ONE real option
      (config.BUNDLE_EXPECT_SINGLE_OPTION). More means the campaign or the plan
      changed — refuse rather than take row one. It is a typeahead select, not a
      <select>, so it needs click-then-type-then-pick, not select_option.
    * Every required field on the per-document form must be non-empty before
      the submit. They pre-fill (Megan: "I don't think anything is hand typed"),
      but that is a belief about a form nobody has watched populate itself, and
      being wrong means a contract mailed with a blank employee name on it. One
      read turns a bet into a refusal.
    """
    raise NotImplementedError("selectors need a Lucy 3 run")


def confirm_generated(tab, name: str) -> bool:
    """Banner reads "Successfully Added Document(s) for <Name>" and lists the
    nine documents. OwnerVille emails them from here — generating IS the send,
    there is no separate mail step."""
    raise NotImplementedError("selectors need a Lucy 3 run")


def tick_attestations(page, modal, *, dry_run: bool = True) -> None:
    """Back on Set Status: BACKGROUND CHECK (1 box), DRUG TEST (2), SERVICE →
    RES-ATT, then Save Changes bottom right.

    The second drug-test box states the company HAS REVIEWED the drug screen and
    confirmed it passes — an assertion to AT&T, not a status flag. Raised with
    Megan 2026-08-25; her call was to tick it, so we do what the hand process
    does. The one thing carried over from raising it: log per rep that we ticked
    these, so the attestation is auditable rather than invisible.
    """
    raise NotImplementedError("selectors need a Lucy 3 run")
