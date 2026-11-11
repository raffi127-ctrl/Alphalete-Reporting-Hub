"""An owner's Slack id from the email they sign in to Slack with.

The sign-up form asks for that email (Megan 2026-11-10); Lucy turns it into
the id when she announces the sign-up, and writes it on their row. That id is
what puts the owner in the group DM when their computer goes quiet.

    python -m automations.icd_signup.slack_lookup someone@example.com
"""
from __future__ import annotations

import sys
from typing import Callable, Iterable, Optional


def _default_clients() -> Iterable[Callable]:
    """Lucy's own token first, then the workspace-admin one. Either may lack
    the email scope on a given machine, so both are tried."""
    def lucy():
        from automations.shared import slack_metrics_post as smp
        return smp._client()

    def admin():
        from automations.ao_cleanup import slack_read
        return slack_read.client()
    return (lucy, admin)


def id_for_email(email: str, clients: Optional[Iterable[Callable]] = None,
                 log=print) -> str:
    """The Slack user id for this email, or '' when none is found.

    '' ALSO WHEN SLACK CANNOT BE ASKED -- a missing scope, no token, the
    network. The caller says "no account found" either way and a person fills
    it in; that is one line in a notice, where a raised error here would cost
    the whole sign-up announcement. A deactivated account does not count.
    """
    email = (email or "").strip().lower()
    if "@" not in email:
        return ""
    if clients is None:
        from automations.shared import live_effects
        if live_effects.driven_by_a_test():
            return ""
        clients = _default_clients()
    for make in clients:
        try:
            user = (make().users_lookupByEmail(email=email) or {}).get("user") or {}
        except Exception as e:  # noqa: BLE001 — try the next token
            log("slack lookup for %s: %s: %s"
                % (email, type(e).__name__, str(e)[:80].replace("\n", " ")))
            continue
        if user.get("id") and not user.get("deleted") and not user.get("is_bot"):
            return user["id"]
    return ""


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m automations.icd_signup.slack_lookup <email>")
        return 1
    found = id_for_email(args[0])
    print(found or "no Slack account found for %s" % args[0])
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
