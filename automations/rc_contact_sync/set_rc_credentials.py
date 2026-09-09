"""Put the RingCentral app credentials on this machine, without them passing
through anything.

    python -m automations.rc_contact_sync.set_rc_credentials --push "Lucy 2"

Asks for the client id, the client secret and the JWT at hidden prompts (a
terminal prompt when there is a terminal, a native macOS dialog when there
isn't), writes ~/.config/recruiting-report/ringcentral-b2b-creds.json at mode
600, and --push hands it to a runner through mini_control's redacted transit.
Nothing is echoed, nothing becomes a command-line argument, so none of it
reaches shell history, a log, a chat or the Mini Control sheet.

IT VERIFIES BEFORE IT WRITES. The JWT is exchanged for a token and the
extension it belongs to is read back: if it is not TAYLOR, nothing is saved.
A token for the wrong user -- Carlos, or anyone in the other RingCentral
account -- authenticates perfectly well and would file every B2B customer in
the wrong address book while reading the wrong inbox, and the run would still
exit 0. Better to fail here, at a prompt, than at 4am into a phone system.

Prints NOTHING of the secrets, not even their length.
"""
from __future__ import annotations

import argparse
import json
import stat
import subprocess
import sys

from automations.alphalete_sales_board.set_credentials import _ask_dialog, _interactive
from automations.rc_contact_sync import config as C

CRED_KEY = "ringcentral-b2b-creds"


def ask(prompt: str, *, hidden: bool) -> str:
    """Terminal prompt when there is a terminal, a dialog when there isn't.

    NOT the sales board's ask(): that one titles every dialog "SaraPlus
    login", so asking for a RingCentral JWT popped a box labelled SaraPlus
    (2026-09-03). A prompt that misnames what it is asking for is a prompt
    somebody eventually types the wrong secret into."""
    import getpass
    import platform
    if _interactive():
        return (getpass.getpass(prompt + ": ") if hidden
                else input(prompt + ": ").strip())
    if platform.system() == "Darwin":
        script = (
            'set r to display dialog %s default answer ""%s '
            'with title "RingCentral credentials" '
            'buttons {"Cancel","OK"} default button "OK"\n'
            'return text returned of r'
        ) % (json.dumps(prompt), " with hidden answer" if hidden else "")
        out = subprocess.run(["/usr/bin/osascript", "-e", script],
                             capture_output=True, text=True, timeout=600)
        return "" if out.returncode != 0 else out.stdout.rstrip("\n")
    raise RuntimeError("no terminal to ask on and no macOS dialog available")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--push", metavar="MACHINE",
                    help='queue it onto a runner afterwards, e.g. --push "Lucy 2"')
    ap.add_argument("--client-id", dest="client_id", default=None,
                    help="the app's client id. It is an IDENTIFIER, not a "
                         "secret (the secret and the JWT are still prompted "
                         "for), so passing it here just removes one prompt.")
    ap.add_argument("--skip-check", action="store_true",
                    help="write without verifying who the token is (don't)")
    args = ap.parse_args(argv)

    # JWT FIRST. It is displayed exactly once in the console, so it is the
    # value most easily lost — asking for it last meant copying it, then
    # copying two more things over it (2026-09-03).
    # ONLY ASK FOR WHAT IS MISSING. Re-running to replace one rotated value
    # should not mean re-entering all three, and a prompt somebody has
    # already answered once is a prompt they end up cancelling (2026-09-03,
    # three times).
    have = {}
    if C.RC_CREDS_PATH.exists():
        try:
            have = json.loads(C.RC_CREDS_PATH.read_text())
        except (ValueError, OSError):
            have = {}
    if have:
        print("existing credentials found — only what is missing will be asked "
              "for (delete %s to start clean)" % C.RC_CREDS_PATH)

    jwt = have.get("jwt") or ask(
        "RingCentral JWT (from the credential page)", hidden=True)
    client_id = args.client_id or have.get("client_id") or ask(
        "RingCentral client id (app dashboard)", hidden=False)
    client_secret = have.get("client_secret") or ask(
        "RingCentral client secret — 'Click to see' on the app dashboard, "
        "then Cmd+V", hidden=True)
    if not jwt or not client_id or not client_secret:
        print("cancelled — nothing written.")
        return 1

    creds = {"client_id": client_id.strip(), "client_secret": client_secret.strip(),
             "jwt": jwt.strip()}

    if not args.skip_check:
        from automations.rc_contact_sync import ringcentral as RC
        try:
            me = RC.identity(RC.token_info(creds))
        except Exception as e:                             # noqa: BLE001
            print("✗ those credentials did not authenticate: %s"
                  % str(e).splitlines()[0][:200])
            print("  nothing written.")
            return 1
        print("authenticated: extension id %s, scope [%s]"
              % (me["owner_id"], me["scope"]))
        try:
            RC.assert_identity(me, C.RC_OWNER_ID)
        except RC.RCError as e:
            print("✗ %s" % e)
            print("  nothing written.")
            return 1
        print("✓ identity confirmed")

    C.RC_CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    C.RC_CREDS_PATH.write_text(json.dumps(creds))
    C.RC_CREDS_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)     # 0600, this user only
    print("wrote %s (mode 600)" % C.RC_CREDS_PATH)

    if args.push:
        from automations.day_orchestrator import mini_control as mc
        ok, msg = mc._action_push_cred_file("%s %s" % (CRED_KEY, args.push))
        print(("pushed: " if ok else "push FAILED: ") + msg)
        return 0 if ok else 1
    print('Next: lucy push_cred_file %s "Lucy 2"' % CRED_KEY)
    return 0


if __name__ == "__main__":
    sys.exit(main())
