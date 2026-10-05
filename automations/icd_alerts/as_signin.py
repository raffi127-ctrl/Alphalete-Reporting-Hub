"""Sign this office into AppStream with THEIR login, and prove it worked.

FOR RESUME PUSHING ON THE OFFICE'S OWN COMPUTER (Carlos 2026-10-05). The
installer runs this while somebody is sitting there.

IN THE SAME CHROME THE PUSH USES (resume_push.py), on purpose: the session
and the security check it passes here are exactly what the first scheduled
push reuses. A sign-in proven in some other browser would prove nothing
about that one.

THEIR LOGIN, NEVER OURS. An office's own AppStream account sees only that
office, and Send-to-AI reaches whatever the ACCOUNT can see -- so an account
that cannot see another office cannot push it (lucy-login-standard rule 3).

SAME FORM AS OWNERVILLE, SAME TRICK: username -> NEXT -> wait 30s -> password
-> wait 30s -> submit. Nobody has to tick the security box.

PROOF IS THE OFFICE CONSOLE (#searchMC), not a page that loaded. A wrong
username does not error -- the form submits and a page renders.

    python -m automations.icd_alerts.as_signin
"""
from __future__ import annotations

import sys


def run(log=print) -> int:
    """0 = signed in and on the office console. 1 = not. 2 = no login saved."""
    from automations.icd_alerts import resume_push
    return resume_push.check_login(log=log)


if __name__ == "__main__":
    sys.exit(run())
