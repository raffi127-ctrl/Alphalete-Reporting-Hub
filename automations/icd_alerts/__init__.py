"""Credit-check alerts for an ICD's own office, read on the ICD's own machine.

WHY THIS IS NOT JUST ANOTHER OFFICE IN THE ALPHALETE SWEEP.

A SaraPlus account sees exactly ONE owner's information (Megan 2026-09-10), so
reading office N means holding office N's login. We cannot get most of those
logins, and Megan is not going to ask 50 ICDs for their password. So the read
moves to the machine where that login already lives -- the ICD's laptop -- and
the credential never travels.

THE LAPTOP IS A READ-AND-RELAY, NOTHING MORE. It logs into SaraPlus, reads the
one grid, and hands the numbers to us. It does NOT post to Slack. That split is
the whole design:

    their laptop                             our side
    ------------                             --------
    SaraPlus login (their creds, local)  ->  relayed rows  ->  Lucy posts to AO

  * no Slack token ever sits on a machine we don't control. The posting
    identity is per-machine -- whatever token is in slack-user-token -- and a
    post from the wrong box once landed in #a-players-b2b as Megan instead of
    Lucy. Fifty contractor laptops holding that token is not a thing to build.
  * revoking an office is us ignoring its rows. They cannot post into AO
    without us, by construction rather than by policy.
  * the alert wording lives in ONE place. Changing it does not mean reaching
    52 machines.

EVERY SARAPLUS IS THE SAME (Megan 2026-09-10), which is why this module holds
no per-office selectors, column indices or grid names: it imports them from
`automations/shared/saraplus.py`, where they are pinned once and already proven
against the live site. That module knows nothing about any office -- which is
what lets this one ship to a laptop we do not own. The `alphaletemarketing@` login that 404s on
ReportingHub.aspx was a MARKETING account, not an owner account -- a different
account type, not a different SaraPlus.

WHAT THIS MODULE DELIBERATELY DOES NOT NEED: the board workbook, the rep
roster, NAME_MAP, EXCLUDE_REPS, week-ending tabs, iMessage. A credit-check ping
is "NAME just ran N credit checks (M today)" and the names come straight off
the grid. None of the board machinery applies.

Python 3.9-safe and cross-platform: this runs on an ICD's laptop, which may be
Windows and is certainly not a machine we set up.
"""
