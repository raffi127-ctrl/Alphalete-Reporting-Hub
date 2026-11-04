"""Send Sterling background-check e-invites from this office's own computer.

Called by office_jobs for a 'bgc_send' job. The people come from the office
admin's ticks on the office admin page (read off ApplicantStream on the
admin's own computer).

WHY HERE (Megan 2026-11-03): the office admin is somewhere else; THIS is the
computer that holds the office's Sterling login. The admin's page queues the
job (office_admin/relay_client.py); office_jobs.py hands it to us.

THE SIGN-IN: Sterling emails a code on every login (noreply@us.fadv.co,
"Authentication Request", "Your authentication code is 966828."). Same road
as SaraPlus codes: the office's Gmail filter forwards ONLY those code mails
to the reporting inbox, the office's address goes on the relay workbook's
'Sterling Code Mail' tab, and at the code screen this calls code() below --
Lucy 1 (code_answer, service "sterling") finds the code and hands it back.

NOT WIRED YET: the Sterling portal's own click path (login page, code screen,
the "send e-invite" form and which package to pick) has never been automated
here -- bg_check_sync only ever read Sterling's EMAILS. Until it is mapped
from a real signed-in session:
  * dry  -> answers who it WOULD invite (nothing is sent, nothing signed in)
  * live -> refuses, so no admin ever believes invites went out that didn't.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

WIRED = False


def code(since: dt.datetime, office_key: str = "", log=print) -> str:
    """The Sterling code mailed after `since`, via Lucy 1. Raises
    sara_code.NoCode when none comes (no forward set up, or too slow)."""
    from automations.icd_alerts import sara_code
    return sara_code.code_from_relay(since, office_key=office_key, log=log,
                                     service="sterling")


def _name(p: Dict) -> str:
    return ("%s %s" % (p.get("first_name") or "", p.get("last_name") or "")).strip()


def send_invites(people: List[Dict], *, live: bool, office_key: str = "",
                 log=print) -> Dict:
    """-> {'status': 'sent'|'dry_run'|'error', 'sent': [...], 'failed': [...],
    'would_send': [...], 'error': str}."""
    people = [p for p in people or [] if _name(p) and "@" in str(p.get("email") or "")]
    if not people:
        return {"status": "error", "error": "nobody to invite"}
    if not live:
        return {"status": "dry_run", "would_send": [_name(p) for p in people],
                "signed_in": False,
                "note": "test run -- Sterling sign-in not wired yet, nothing sent"}
    if not WIRED:
        return {"status": "error",
                "error": "sending from this computer isn't switched on yet -- send these in Sterling by hand",
                "failed": [_name(p) for p in people]}
    raise NotImplementedError  # pragma: no cover -- replaced when wired
