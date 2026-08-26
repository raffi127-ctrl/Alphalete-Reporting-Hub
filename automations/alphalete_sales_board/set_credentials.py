"""Put the SaraPlus login on this machine, without it passing through anything.

    python -m automations.alphalete_sales_board.set_credentials

Asks for the email (Enter keeps the one already on file), then the password at
a hidden prompt, and writes ~/.config/recruiting-report/saraplus-creds.json at
mode 600. The password is never echoed, never an argument, and so never lands
in shell history, a log, or a chat.

IT ASKS TWO DIFFERENT WAYS, because the first version only knew how to ask a
terminal. Run from a Run button / a launchd job / anything without a TTY,
getpass had no keyboard to read and the whole thing died before writing
anything -- and from the button's side that looks exactly like "nothing
happened" (2026-08-26). So: a TTY gets the ordinary hidden prompt, and
everything else on macOS gets a native password DIALOG (osascript, hidden
answer). The dialog needs no terminal, and the answer comes back through the
process rather than through a command line, so it still never reaches history.

WHY A MODULE AND NOT A ONE-LINER: this is the second thing everyone reaches for
when a portal password rotates, and a 300-character one-liner is something you
have to paste from somewhere -- which is exactly how a credential ends up in
the place you were trying to keep it out of. `--push "Lucy 1"` hands it to a
runner afterwards through mini_control's redacted transit
(push_cred_file/set_cred_file), so the value never sits in the Mini Control
sheet either.

Prints NOTHING of the password, not even its length.
"""
from __future__ import annotations

import argparse
import getpass
import json
import platform
import stat
import subprocess
import sys

from automations.alphalete_sales_board import config as C


def _ask_dialog(prompt: str, *, hidden: bool, default: str = "") -> str:
    """One native macOS dialog. Returns "" if cancelled or unavailable."""
    script = (
        'set r to display dialog %s default answer %s%s '
        'with title "SaraPlus login" buttons {"Cancel","OK"} default button "OK"\n'
        'return text returned of r'
    ) % (json.dumps(prompt), json.dumps(default),
         " with hidden answer" if hidden else "")
    try:
        out = subprocess.run(["/usr/bin/osascript", "-e", script],
                             capture_output=True, text=True, timeout=300)
    except Exception:  # noqa: BLE001
        return ""
    if out.returncode != 0:      # Cancel, or no GUI session
        return ""
    return out.stdout.rstrip("\n")


def _interactive() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:  # noqa: BLE001
        return False


def ask(prompt: str, *, hidden: bool, default: str = "") -> str:
    """Terminal prompt when there is a terminal, a dialog when there isn't."""
    if _interactive():
        if hidden:
            return getpass.getpass(prompt + ": ")
        shown = "%s [%s]: " % (prompt, default) if default else prompt + ": "
        return input(shown).strip() or default
    if platform.system() == "Darwin":
        return _ask_dialog(prompt, hidden=hidden, default=default) or default
    raise RuntimeError(
        "no terminal to ask on and no macOS dialog available -- run this in a "
        "Terminal window, or pass --email and set the password there.")


def current_email() -> str:
    try:
        return json.loads(C.CREDS_PATH.read_text()).get("email", "")
    except Exception:  # noqa: BLE001 — no file, bad json, unreadable: all "none"
        return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--email", help="skip the email prompt (it is not a secret)")
    ap.add_argument("--push", metavar="MACHINE",
                    help='queue it onto a runner afterwards, e.g. --push "Lucy 1"')
    args = ap.parse_args(argv)

    existing = current_email()
    email = args.email or ask("SaraPlus email", hidden=False, default=existing)
    if not email:
        print("no email given — nothing written.")
        return 1

    password = ask("SaraPlus password for %s" % email, hidden=True)
    if not password:
        print("no password given (cancelled?) — nothing written.")
        return 1
    again = ask("Type it once more to be sure", hidden=True)
    if again != password:
        # Worth the second prompt: a typo here does not fail loudly, it fails
        # as a login bounce every five minutes until somebody reads a log.
        print("the two didn't match — nothing written.")
        return 1

    C.CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    C.CREDS_PATH.write_text(json.dumps({"email": email, "password": password}))
    C.CREDS_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)   # 0600, this user only
    print("wrote %s (mode 600) for %s" % (C.CREDS_PATH, email))

    if args.push:
        from automations.day_orchestrator import mini_control as mc
        ok, msg = mc._action_push_cred_file('saraplus-creds %s' % args.push)
        print(("pushed: " if ok else "push FAILED: ") + msg)
        return 0 if ok else 1

    print('Next: lucy push_cred_file saraplus-creds "Lucy 1"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
