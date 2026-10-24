"""Put the NDS SaraPlus login on this machine -- and on Lucy 2 -- without it
passing through anything.

    python -m automations.vantura_nds_sara.set_credentials --push "Lucy 2"

That is the whole command Carlos runs on his laptop. It asks for the email
(Enter keeps the one already on file), then the password at a hidden prompt,
twice, and writes ~/.config/recruiting-report/saraplus-nds-creds.json
(vantura_nds_sara.config.creds_path) at mode 600. With --push it then hands
the file to Lucy 2 through mini_control's redacted transit (push_cred_file ->
set_cred_file, key `saraplus-nds-creds`): the Args cell is blanked on
landing, so the value never sits in the Mini Control sheet either. The
password is never echoed, never an argument, and so never lands in shell
history, a log, or a chat. Prints NOTHING of it, not even its length.

THIS IS THE NDS ACCOUNT'S FILE, not alphalete_sales_board's saraplus-creds.json
(alphaletemarketing) and not rc_contact_sync's saraplus-creds-b2b.json -- see
config.py for why each reader keeps its own. The login to type is the one
whose Order Dashboard shows the crew's NDS sales; `lucy rerun vantura_nds_sara
--probe --source sara` prints every rep's raw numbers from it before anything
is written.

LUCY 2 HAS TO KNOW THE KEY. set_cred_file on the receiving side checks the
same whitelist (mini_control._CRED_FILES), so the push lands only once Lucy 2
runs code that carries `saraplus-nds-creds`; pushed earlier, its row ends
"unknown file-key" and nothing is written there -- re-run the push after
`lucy update`.

IT ASKS TWO DIFFERENT WAYS (lifted from alphalete_sales_board.set_credentials,
2026-08-26): a TTY gets the ordinary hidden prompt, and anything without one
on macOS -- a Run button, a launchd job -- gets a native password DIALOG
(osascript, hidden answer), because getpass with no keyboard died before
writing anything and from the button's side that looked like "nothing
happened".
"""
from __future__ import annotations

import argparse
import getpass
import json
import platform
import stat
import subprocess
import sys

from automations.vantura_nds_sara import config as C


def _ask_dialog(prompt: str, *, hidden: bool, default: str = "") -> str:
    """One native macOS dialog. Returns "" if cancelled or unavailable."""
    script = (
        'set r to display dialog %s default answer %s%s '
        'with title "NDS SaraPlus login" buttons {"Cancel","OK"} default button "OK"\n'
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
        return json.loads(C.creds_path().read_text()).get("email", "")
    except Exception:  # noqa: BLE001 -- no file, bad json, unreadable: all "none"
        return ""


def write_creds(email: str, password: str) -> None:
    """The file, mode 600, this user only. Nothing printed."""
    path = C.creds_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"email": email, "password": password}))
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)   # 0600


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--email", help="skip the email prompt (it is not a secret)")
    ap.add_argument("--push", metavar="MACHINE",
                    help='queue it onto a runner afterwards: --push "Lucy 2"')
    args = ap.parse_args(argv)

    existing = current_email()
    email = args.email or ask("NDS SaraPlus email", hidden=False, default=existing)
    if not email:
        print("no email given -- nothing written.")
        return 1

    password = ask("NDS SaraPlus password for %s" % email, hidden=True)
    if not password:
        print("no password given (cancelled?) -- nothing written.")
        return 1
    again = ask("Type it once more to be sure", hidden=True)
    if again != password:
        # Worth the second prompt: a typo here does not fail loudly, it fails
        # as a login bounce on every pass until somebody reads a log.
        print("the two didn't match -- nothing written.")
        return 1

    write_creds(email, password)
    print("wrote %s (mode 600) for %s" % (C.creds_path(), email))

    if args.push:
        from automations.day_orchestrator import mini_control as mc
        ok, msg = mc._action_push_cred_file("%s %s" % (C.CRED_KEY, args.push))
        print(("pushed: " if ok else "push FAILED: ") + msg)
        if ok:
            print("Lucy 2 installs it on its next queue poll -- then: "
                  "lucy rerun vantura_nds_sara --preflight")
        return 0 if ok else 1

    print('Next: lucy push_cred_file %s "Lucy 2"' % C.CRED_KEY)
    return 0


if __name__ == "__main__":
    sys.exit(main())
