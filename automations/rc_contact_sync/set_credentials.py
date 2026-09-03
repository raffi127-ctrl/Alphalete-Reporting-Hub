"""Put CARLOS's SaraPlus login on this machine, without it passing through
anything.

    python -m automations.rc_contact_sync.set_credentials --push "Lucy 2"

Asks for the email (Enter keeps carhi1816@gmail.com), then the password at a
hidden prompt -- a terminal prompt when there is a terminal, a native macOS
dialog when there isn't -- and writes
~/.config/recruiting-report/saraplus-creds-b2b.json at mode 600. The password
is never echoed, never an argument, and so never lands in shell history, a
log, or a chat. `--push` hands it to a runner through mini_control's redacted
transit, so it never sits in the Mini Control sheet either.

A SEPARATE FILE FROM THE SALES BOARD'S, and that is the whole point. That one
is alphaletemarketing@gmail.com -- a different dealer, whose Detail Reports
return rows, just not these rows. Megan 2026-09-02: "make sure you're ONLY
using Carlos' sara plus login to access". Two files means a password change on
one account can never quietly hand this report the other's orders.

The prompting itself is the sales board's, reused rather than re-typed: it
already learned that a Run button has no TTY for getpass to read, and finding
that out again here would look exactly like "nothing happened".

Prints NOTHING of the password, not even its length.
"""
from __future__ import annotations

import argparse
import json
import stat
import sys

from automations.alphalete_sales_board.set_credentials import ask
from automations.rc_contact_sync import config as C

# Carlos's SaraPlus account (not a secret -- he posted it in the channel).
# Offered as the default so the usual answer to the email prompt is Enter.
DEFAULT_EMAIL = "carhi1816@gmail.com"
CRED_KEY = "saraplus-creds-b2b"


def current_email() -> str:
    try:
        return json.loads(C.CREDS_PATH.read_text()).get("email", "")
    except Exception:                     # no file, bad json, unreadable
        return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--email", help="skip the email prompt (it is not a secret)")
    ap.add_argument("--push", metavar="MACHINE",
                    help='queue it onto a runner afterwards, e.g. --push "Lucy 2"')
    args = ap.parse_args(argv)

    default = current_email() or DEFAULT_EMAIL
    email = args.email or ask("Carlos's SaraPlus email", hidden=False,
                              default=default)
    if not email:
        print("no email given — nothing written.")
        return 1

    password = ask("SaraPlus password for %s" % email, hidden=True)
    if not password:
        print("no password given (cancelled?) — nothing written.")
        return 1
    again = ask("Type it once more to be sure", hidden=True)
    if again != password:
        # Worth the second prompt: a typo here doesn't fail loudly, it fails
        # as a login bounce every morning until somebody reads a log.
        print("the two didn't match — nothing written.")
        return 1

    C.CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    C.CREDS_PATH.write_text(json.dumps({"email": email, "password": password}))
    C.CREDS_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)       # 0600, this user only
    print("wrote %s (mode 600) for %s" % (C.CREDS_PATH, email))

    if args.push:
        from automations.day_orchestrator import mini_control as mc
        ok, msg = mc._action_push_cred_file("%s %s" % (CRED_KEY, args.push))
        print(("pushed: " if ok else "push FAILED: ") + msg)
        return 0 if ok else 1

    print('Next: lucy push_cred_file %s "Lucy 2"' % CRED_KEY)
    return 0


if __name__ == "__main__":
    sys.exit(main())
