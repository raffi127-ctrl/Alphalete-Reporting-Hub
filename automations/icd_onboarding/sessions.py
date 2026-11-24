"""The logins a step needs, opened whichever way THIS machine can.

Named for the job rather than for one site: it started as OwnerVille only
(`ov_anywhere`, 2026-11-24) and ApplicantStream arrived the same day with the
same shape, so a module called after one of the two would have been a small
lie that cost somebody a search later.

The board already has this shape for the sheet: `fillers.rows_anywhere` reads
with gspread on a Lucy and through the relay on an office's own computer, and
the step bodies know no difference. This is the same idea for the OwnerVille
SESSION, and the reason is Megan's, 2026-11-24, when the contention on Lucy 3
came up: *"the OV sweep would happen on the ECO machine."*

THAT IS WHY THE CONTENTION DISSOLVES RATHER THAN BEING MANAGED. One Lucy holds
ONE OwnerVille session, deliberately -- two runs on one session read each
other's offices -- so every office's read queues behind every other, and on
2026-11-24 the 8am sweep waited its whole 30 minutes behind three other jobs
and refused rather than guess whose rows it had. Forty offices reading their
own OwnerVille on forty machines, each with its own login, never queue at all.

WHICH BRANCH IS NOT A GUESS. `fillers.on_office_machine` answers it the one way
that is true: a LucyEco enrolment for that office is installed, which is
exactly the machine that has the office's own login and no Google access. A
Lucy and a dev checkout both answer False and keep the Hub session.

EACH IMPORT LIVES INSIDE ITS OWN BRANCH. `shared.tableau_patchright` cannot
ship -- it pulls in `recruiting_report.opt_phase` and the Hub behind it -- so an
office machine must never reach the line that imports it.
"""
from __future__ import annotations

import contextlib
from typing import Optional


@contextlib.contextmanager
def session_anywhere(office_key: str = "", *, campaign: str = "",
                     profile_dir=None, headless: bool = True, log=print):
    """Yield an OwnerVille page, from whichever session this machine has.

    `campaign` is only read on the office-machine branch, where the office's
    own config decides it; on a Lucy the campaign is pinned by the caller the
    way it always was, because one machine serves many offices and the pin is
    the only thing that says which.

    THE REASON A CALLER CANNOT TELL THE TWO APART is the point: a step that
    behaved differently depending on where it ran would be two steps, and the
    one nobody watches is the one that breaks.
    """
    from automations.icd_onboarding import fillers as F

    if F.on_office_machine(office_key):
        # `headless` IS IGNORED HERE, on purpose. On an office's own computer
        # whether a window opens is never a caller's or a flag's call: the
        # session opens one only when a sign-in genuinely needs it, and hides
        # it ([[feedback_eco_runs_in_background]]). A debugging flag must not
        # be able to put a browser on an owner's screen.
        from automations.icd_alerts.ov_session import ownerville_here
        with ownerville_here(headless=True, campaign=campaign, log=log) as page:
            yield page
        return

    from automations.shared.tableau_patchright import ownerville_session
    with ownerville_session(headless=headless, verbose=False,
                            profile_dir=profile_dir) as page:
        yield page


def unavailable():
    """The exception classes that mean NOTHING WAS LOOKED AT, for a caller that
    has to tell that from a read which went wrong half way.

    A tuple rather than one class because the two branches raise their own:
    `OwnervilleUnavailable` on an office machine (a held sign-in, a campaign
    that would not select) and `OwnervilleBusy` on a Lucy (another run held the
    one session for the whole wait). Either way the answer is the same -- no
    rows were seen, so no step may record an answer
    ([[feedback_empty_means_proven_zero]]).
    """
    out = []
    try:
        from automations.icd_alerts.ov_session import OwnervilleUnavailable
        out.append(OwnervilleUnavailable)
    except Exception:       # noqa: BLE001 -- not shipped here
        pass
    try:
        from automations.shared.tableau_patchright import OwnervilleBusy
        out.append(OwnervilleBusy)
    except Exception:       # noqa: BLE001 -- not on an office machine
        pass
    return tuple(out) or (RuntimeError,)


@contextlib.contextmanager
def appstream_anywhere(office_key: str = "", *, log=print):
    """Yield an `ApplicantStream` driver, from whichever session this machine
    has.

    THE SEED AND THE NO-SHOWS WALK both read ApplicantStream, and both are
    steps whose source is the OFFICE's -- their recruiting calendar, their
    Retention Report, their login. On a Lucy that is the warm console
    `tableau_patchright` keeps for everybody; on an office's own computer it is
    the Chrome `resume_push` already signs in (`eco_steps.appstream_here`), and
    `as_signin` says why that matters: a sign-in proven in some other browser
    proves nothing about the one the scheduled reads use.

    Same branch and same reason as `session_anywhere` above, and the Hub import
    sits inside its own branch because `shared.tableau_patchright` cannot ship.
    """
    from automations.icd_onboarding import fillers as F

    if F.on_office_machine(office_key):
        from automations.icd_onboarding.eco_steps import appstream_here
        with appstream_here(log=log) as app:
            yield app
        return

    from automations.applicant_tracker.applicantstream import session
    with session() as app:
        yield app
