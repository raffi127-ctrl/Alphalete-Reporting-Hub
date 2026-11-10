"""The onboarding-documents question, asked once on the office's own computer.

Megan, 2026-11-09: *"Digi docs + Owner Submit - when an icd enrolls we should
ask them this question to make sure we send it right for them specifically."*

WHY IT IS ASKED HERE AND NOT ON A FORM. The answers are not facts an owner
knows; they are the exact labels on their own OwnerVille's Generate Document
screen. Typed from memory, "Door to Door General" instead of "Door to Door-
General 1" selects nothing, and the run either refuses or -- worse, before
`BUNDLE_EXPECT_SINGLE_OPTION` -- takes whatever was first. So this opens their
OwnerVille, READS the real options, and offers them as a list to pick from.
Nothing here is typed ([[feedback_simple_ux]]: no clever syntax inputs; one
input per concept).

ASKED ONCE. An office with its answers saved is skipped, so this is safe in
`finish_setup`'s "run it whenever you like" list.

WHAT IT ASKS -- TWO QUESTIONS, not four:

  * the **campaign**, read off the View Progress dropdown. It also decides
    which bundles exist, because the bundle list is per campaign.
  * the **bundle type**, read off the Generate Document radios.

The BUNDLE itself is never asked: under a bundle type the dropdown holds
exactly one real option, and digi_docs already refuses rather than guessing
when it holds more. The COMMISSION bundle is a question, but it only appears
after a bundle is chosen for a REAL REP -- so it is asked at the office's
first send, not here, and `office_config` refuses to send until it has been.

NOTHING IS SENT BY THIS. It reads two screens and writes a row.
"""
from __future__ import annotations

from typing import List, Optional

# The office picks from its own page; these are only the fall-backs used when
# a screen cannot be read at all, so the question can still be answered rather
# than the whole setup stopping.
KNOWN_BUNDLE_TYPES = (
    "Base (Door to Door/Business to Business)",
    "Base (Retail)",
    "Base (Events)",
)

SKIP = "Not sure — ask me later"


def _campaigns(page) -> List[str]:
    """Every programme this office's OwnerVille offers, off the real dropdown."""
    from automations.headshots.ov_upload import _campaign_select
    sel = _campaign_select(page)
    return [o.strip() for o in sel.evaluate(
        "s => [...s.options].map(o => o.textContent)") if o and o.strip()]


def _bundle_types(page) -> List[str]:
    """The Generate Document bundle-type radios, by their labels.

    Read off the page rather than listed in code, because the whole point of
    asking is that this office's list may not be Alphalete's.
    """
    got = page.evaluate(
        """() => [...document.querySelectorAll("input[type='radio']")]
            .map(el => {
                const lab = el.closest('label')
                    || document.querySelector('label[for="' + el.id + '"]');
                return (lab ? lab.innerText : (el.parentElement || {}).innerText || '')
                    .replace(/\\s+/g, ' ').trim();
            })
            .filter(t => /^Base\\b/i.test(t))""")
    seen, out = set(), []
    for t in got or ():
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def ask_office(office_key: str, *, ask=None, page=None, log=print) -> str:
    """Ask, and save. Returns a word for finish_setup's summary.

    Never raises: a setup step that explodes costs every step after it.
    """
    from automations.digi_docs import office_config as OC

    if ask is None:
        from automations.icd_alerts import dialogs as ask  # type: ignore

    key = str(office_key or "").strip().lower()
    if not key:
        return "no office key on this machine"
    if OC.answered(key):
        return "nothing to do"

    # What we can read without a browser first, so a page that will not open
    # does not cost the answer we already have.
    campaign = ""
    try:
        from automations.office_admin import config as AC
        o = AC.office(key)
        campaign = (getattr(o, "ov_program", "") if o else "") or ""
    except Exception:          # noqa: BLE001
        campaign = ""

    opened_here = page is None
    ctx = None
    try:
        if page is None:
            from automations.icd_alerts import config as IC
            from automations.shared.tableau_patchright import ownerville_session
            ctx = ownerville_session(headless=False, verbose=False,
                                     profile_dir=str(IC.OV_PROFILE_DIR))
            page = ctx.__enter__()

        from automations.b2b_dispositions.capture import capture_rqst
        from automations.headshots.ov_upload import VIEW_PROGRESS_P
        page.set_default_navigation_timeout(90000)
        rqst = capture_rqst(page)
        page.goto("https://v2.ownerville.com/index.cfm?p=%d&rqst=%s"
                  % (VIEW_PROGRESS_P, rqst), wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        if not campaign:
            options = _campaigns(page)
            if len(options) == 1:
                campaign = options[0]
                log("  only one programme on this OwnerVille: %s" % campaign)
            elif options:
                campaign = ask.choose(
                    "Which programme are your new starts added under?\n\n"
                    "This is read from your own OwnerVille — pick the one your "
                    "reps appear in.", options + [SKIP])
                if campaign == SKIP:
                    return "left for later"

        types = _bundle_types(page) or list(KNOWN_BUNDLE_TYPES)
        bundle_type = ask.choose(
            "Which onboarding document bundle do your new starts sign?\n\n"
            "Pick the one your office uses — this is what Lucy will send.",
            types + [SKIP])
        if bundle_type == SKIP:
            return "left for later"
    except ask.Cancelled:
        return "left for later"
    except Exception as e:     # noqa: BLE001 — never cost the other steps
        log("  could not read OwnerVille's choices: %s" % type(e).__name__)
        return "could not read OwnerVille — run this again"
    finally:
        if opened_here and ctx is not None:
            try:
                ctx.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass

    OC.save(key, campaign=campaign, bundle_type=bundle_type, log=log)
    # The commission bundle only exists on screen once a real rep has a bundle
    # chosen, so it is asked at the first send rather than guessed at now.
    return "answered — the commission bundle is asked at your first send"


def main(argv=None) -> int:
    """    python -m automations.icd_alerts.digi_docs_setup --office <key>"""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--office", default="", help="office key; this machine's by default")
    a = ap.parse_args(argv)
    key = a.office
    if not key:
        from automations.icd_alerts import config as IC
        rows = IC.enrollments()
        key = (rows[0].get("office_key") if rows else "") or ""
    print(ask_office(key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
