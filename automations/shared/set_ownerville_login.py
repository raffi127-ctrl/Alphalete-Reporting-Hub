"""Point THIS machine's ownerville login at a different account.

WHY THIS EXISTS. The ownerville login is one machine-wide credential file, and
everything downstream trusts it silently: the session holder re-logs in from it
on a timer and overwrites the saved cookie blob, and every report injects that
blob over its browser profile. So logging in by hand as the right owner does
not stick — the next renewal puts the file's account back, minutes later, with
nothing reporting a problem.

That cost a full afternoon on 2026-09-01. Lucy 1's file said `chidalgo` (it had
been `rhidalgo` through Aug 25), so Raf's gap boards, Calvin's and Jay's all ran
against Carlos's office 11580. Megan re-logged in as Raf three times and each
one was wiped. The account is the fix; the browser login never was.

Run it ON the machine whose login is wrong:

    PYTHONPATH=. .venv/bin/python -m automations.shared.set_ownerville_login rhidalgo

The password is asked for at the prompt and never echoed, never logged, never
passed as an argument (an argument would land in shell history and in `ps`).
Only the two ownerville_* keys are touched — the AppStream and Double Entry
logins in the same file are left exactly as they are.

Then it clears the stale cookie blob, because that blob is still the OLD
account and would be injected over the new login on the very next run.
"""
from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import sys
import datetime as dt

from automations.shared import creds
from automations.shared.tableau_patchright import OWNERVILLE_STORAGE_STATE

SESSION_HOLDER_LABEL = "com.alphalete.session-holder"


def _backup(path) -> None:
    if path.exists():
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, str(path) + ".bak." + stamp)


def set_login(username: str, password: str) -> str:
    path = creds._CREDS_PATH
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = {}
    was = str(data.get("ownerville_username") or "(none)")
    _backup(path)
    data["ownerville_username"] = username
    data["ownerville_password"] = password
    path.write_text(json.dumps(data, indent=2))
    os.chmod(path, 0o600)
    creds.reload()
    return was


def clear_saved_session() -> bool:
    """Drop the saved cookie blob. It belongs to the OLD account, and every run
    injects it over the profile — leaving it in place would re-establish the
    account we just replaced."""
    if not OWNERVILLE_STORAGE_STATE.exists():
        return False
    _backup(OWNERVILLE_STORAGE_STATE)
    OWNERVILLE_STORAGE_STATE.unlink()
    return True


def restart_holder() -> bool:
    try:
        subprocess.run(["launchctl", "kickstart", "-k",
                        "gui/%d/%s" % (os.getuid(), SESSION_HOLDER_LABEL)],
                       check=True, capture_output=True, timeout=30)
        return True
    except Exception:  # noqa: BLE001 — the login is set either way
        return False


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m automations.shared.set_ownerville_login "
              "<username>   (e.g. rhidalgo)")
        return 2
    username = sys.argv[1].strip()
    if not username or username.startswith("-"):
        print("✗ pass the ownerville username, e.g. rhidalgo")
        return 2
    password = getpass.getpass("ownerville password for %s (not shown): "
                               % username)
    if not password.strip():
        print("✗ no password entered — nothing changed")
        return 2
    was = set_login(username, password)
    print("✓ ownerville login: %s → %s" % (was, username))
    print("✓ cleared the saved session blob"
          if clear_saved_session() else "· no saved session blob to clear")
    print("✓ session holder restarted — it will log in as %s" % username
          if restart_holder() else
          "⚠ couldn't restart the session holder; run Session Check on this box")
    print("\nVerify with:  PYTHONPATH=. .venv/bin/python -m "
          "automations.shared.session_check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
