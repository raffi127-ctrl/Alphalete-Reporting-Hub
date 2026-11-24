"""Open the one ApplicantStream page where the office ticks "Leader In Calendar".

WHY (Megan, 2026-11-23, with the page circled): "this is the page that we
should open for them to make sure that the setting is checked. So it's
Settings, then Office level settings, then check marking Leader in Calendar.
And that's it. It auto saves from there. There's no submit button or
anything." It is for Raf's trainer-calendar audit -- the audit answers WHO
ran each interview, and nothing can answer that until the office records a
leader against them.

NOT THE SAME AS THE CALENDAR QUESTION ON THE ENROLMENT FORM. That one asks
whether their ApplicantStream calendar is on List view with Show Notes
ticked, which is a thing they look at. This is a setting on an admin page
they would otherwise never open, so we open it.

A WINDOW, BECAUSE A PERSON TICKS IT. Lucy holds the office's AppStream
session and could tick the box herself -- but ticking it also turns on
"Leader Is Required in First Round" and "in Second Round" underneath, which
changes what their recruiters are made to fill in. Megan asked for the page
to be OPENED for them, so the owner sees what is being switched on and does
it. That is the counted exception in visible_windows.py: a person acts.

IT SKIPS ITSELF WHEN THE BOX IS ALREADY TICKED, with no window at all --
finish_setup is a link an office may run a dozen times, and a step that
opens a browser every time is a step people stop running.

NOT PROVED LIVE. p=345 and the label text come from Megan's screenshot of
Raf's account; nothing here has met the page. The first real run is the
installer pass on Raf's ECO machine.

    python -m automations.icd_alerts.leader_in_calendar
"""
from __future__ import annotations

import sys

# Settings -> Office Level Settings, from the URL in the screenshot
# (applicantstream.com/index.cfm?rqst=<token>&p=345).
OFFICE_LEVEL_SETTINGS_PAGE = 345

# The checkbox is found by the words beside it, not by an input name: this is
# a ColdFusion page whose field names nobody here has seen, and the label is
# what Megan pointed at.
LABEL = "Leader In Calendar"

WAIT_SECONDS = 300
POLL_SECONDS = 5


def _page_url(token: str) -> str:
    """Office Level Settings, for a live rqst token.

    `resume_push.AS_BASE` and not `tableau_patchright.APPSTREAM_BASE` -- the
    same URL, out of a module that SHIPS. That import is why this step has
    never once run on a real office machine: `tableau_patchright` pulls in
    `recruiting_report.opt_phase` and the Hub behind it, is not in
    agent_files.txt, and so every office saw this step answer
    "failed -- ModuleNotFoundError" (found by the shipped-closure test,
    2026-11-24).
    """
    from automations.icd_alerts import resume_push as RP
    return "%s?rqst=%s&p=%d" % (RP.AS_BASE, token,
                                OFFICE_LEVEL_SETTINGS_PAGE)


def is_ticked(page) -> bool:
    """Is the box ticked right now?

    Asked of the checkbox the label belongs to. A label whose input cannot
    be found answers False -- NOT True: claiming a setting is on when the
    page could not be read is how the audit would quietly have no leaders
    and nobody would look again.
    """
    try:
        box = page.locator(
            "xpath=//input[@type='checkbox']"
            "[following-sibling::text()[contains(., '%s')] or "
            " following::text()[1][contains(., '%s')]]" % (LABEL, LABEL)
        ).first
        return bool(box.is_checked(timeout=5_000))
    except Exception:                               # noqa: BLE001
        pass
    # Second road: the label element, then the input it is for.
    try:
        lab = page.get_by_text(LABEL, exact=False).first
        box = lab.locator("xpath=preceding::input[@type='checkbox'][1]")
        return bool(box.is_checked(timeout=5_000))
    except Exception:                               # noqa: BLE001
        return False


def run(log=print, dialogs=None) -> str:
    """One line for finish_setup's summary.

    THIS OFFICE'S OWN CHROME, the one the push already signs AppStream into
    (`eco_steps.appstream_here`, and `as_signin` says why a session proven in
    some other browser proves nothing about that one). It used to drive the
    Hub's warm console through `tableau_patchright`, which does not exist on
    an office machine.
    """
    from automations.icd_onboarding import eco_steps as ES

    # HIDDEN FIRST. The check costs nothing and opens nothing, so an office
    # that has already ticked it never sees a browser
    # ([[feedback_eco_runs_in_background]]).
    try:
        with ES.appstream_here(log=log) as app:
            token = app.token
            if not token:
                return "needs the ApplicantStream sign-in first"
            app.page.goto(_page_url(token), wait_until="domcontentloaded",
                          timeout=60_000)
            if not app.page.get_by_text(LABEL, exact=False).count():
                return "needs the ApplicantStream sign-in first"
            if is_ticked(app.page):
                log("  Leader In Calendar is already ticked.")
                return "already done"
    except Exception as e:                          # noqa: BLE001
        first = (str(e).strip().splitlines() or [""])[0]
        return "could not check it (%s: %s)" % (type(e).__name__, first[:120])

    # NOW the window, because now a person is needed -- which is the one
    # reason an ECO box may show one (icd_alerts.visible_windows: "person").
    if dialogs is None:
        from automations.icd_alerts import dialogs as dialogs
    dialogs.message(
        "One box to tick in ApplicantStream.\n\n"
        "A window is about to open on your Office Level Settings. "
        "Under Calendar, tick \"Leader In Calendar\".\n\n"
        "It saves itself -- there is no Save button for that box. "
        "Close the window when you have ticked it.")

    from automations.icd_alerts import resume_push as RP
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:
        from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # background=False: they have to see this one.
        browser, ctx, page = RP._connect(p, background=False,
                                         url=_page_url(token))
        if page is None:
            return "needs Lucy's Chrome to open"
        page.goto(_page_url(token), wait_until="domcontentloaded",
                  timeout=60_000)
        waited = 0
        while waited < WAIT_SECONDS:
            page.wait_for_timeout(POLL_SECONDS * 1000)
            waited += POLL_SECONDS
            try:
                if is_ticked(page):
                    log("  Leader In Calendar ticked.")
                    return "done"
            except Exception:                       # noqa: BLE001
                break                               # they closed the window
        return "needs Leader In Calendar ticked"


def main(argv=None) -> int:
    said = run()
    print(said)
    return 0 if said in ("done", "already done") else 1


if __name__ == "__main__":
    sys.exit(main())
