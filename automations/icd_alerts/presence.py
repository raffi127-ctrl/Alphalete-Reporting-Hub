"""Is there a person at this Mac right now?

WHY THIS EXISTS. Megan, 2026-09-17: "We should make it where once someone is
at the mac if we need the PW it's auto popping up immediately on the screen
for them."

Today a lost session costs a DM, then somebody has to find the message, open
a link, copy a command and paste it into Terminal. Ryan lost 3.5 hours on
2026-09-16 that way and Carlos over 5. The machine knew within two minutes;
everything after that was people.

So the agent opens the sign-in window itself -- but ONLY when somebody is
there to use it. A Chrome window on an empty desk at 2am is worse than
useless: it holds the browser profile the sweep needs, so it would turn a
recoverable outage into a guaranteed one.

TWO THINGS HAVE TO BE TRUE:

  * somebody is logged in at the SCREEN, not over ssh -- /dev/console names
    that user and nobody else
  * the screen is not locked -- a locked Mac is an empty desk with someone's
    session still open on it

AND IT RUNS AS ROOT. The boot job is a LaunchDaemon (that is how it survives a
restart with nobody logged in), which has no GUI session of its own. Anything
it launches directly is invisible: the process starts, draws nothing, and
holds the profile anyway. `launchctl asuser` is what puts a window on the
screen the person is actually looking at.

EVERY ANSWER IS "NO" ON FAILURE. A machine we cannot read is one we must not
open windows on.
"""
from __future__ import annotations

import os
import platform
import subprocess
from typing import Optional

from automations.icd_alerts import config as C

CONSOLE = "/dev/console"


def console_user() -> str:
    """Who is logged in at the physical screen, '' if nobody.

    'root' and 'loginwindow' both mean the login screen -- nobody is there,
    whatever the file says.
    """
    if platform.system() != "Darwin":
        return ""
    try:
        out = subprocess.run(["stat", "-f%Su", CONSOLE],
                             capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        return ""
    who = (out.stdout or "").strip()
    return "" if who in ("", "root", "loginwindow", "_windowserver") else who


def screen_locked() -> bool:
    """True when the Mac is locked, and true when we cannot tell.

    UNKNOWN COUNTS AS LOCKED, deliberately. The cost of being wrong one way is
    a window nobody sees holding the profile the sweep needs; the other way it
    is one extra DM.
    """
    if platform.system() != "Darwin":
        return True
    try:
        out = subprocess.run(["ioreg", "-n", "Root", "-d1", "-a"],
                             capture_output=True, text=True, timeout=15)
    except Exception:  # noqa: BLE001
        return True
    text = out.stdout or ""
    if "CGSSessionScreenIsLocked" not in text:
        return False          # the key only appears while locked
    at = text.index("CGSSessionScreenIsLocked")
    return "true" in text[at:at + 120].lower()


def somebody_is_there() -> bool:
    return bool(console_user()) and not screen_locked()


def lucy_user() -> str:
    """The Mac account Lucy runs as -- the one whose folder holds her profiles.

    Read from who OWNS the app folder, not from who this process is: the boot
    job may run as root, and root's answer would be "root".
    """
    try:
        return C.APP_DIR.owner()
    except Exception:  # noqa: BLE001
        pass
    try:
        import getpass
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return ""


def owner_is_there() -> bool:
    """Somebody is at the screen AND it is Lucy's own account.

    THE GUEST ACCOUNT (Eve, 2026-10-29). Eveliz and Luke keep their own login
    and a second one for their reps, and the Mac goes back and forth between
    them. Lucy keeps running under the owner's account either way -- but a
    sign-in window opened while a rep is on the other account lands on a
    screen nobody is looking at, or in front of a rep who never gets the
    emailed code. Luke 2026-10-28: six windows in a row, every one "closed or
    not signed in". Their profile lives in the owner's folder, so only the
    owner's own session can use it.
    """
    who = console_user()
    if not who or screen_locked():
        return False
    mine = lucy_user()
    return not mine or who == mine


def user_id(user: Optional[str] = None) -> str:
    who = user or console_user()
    if not who:
        return ""
    try:
        out = subprocess.run(["id", "-u", who], capture_output=True,
                             text=True, timeout=10)
    except Exception:  # noqa: BLE001
        return ""
    return (out.stdout or "").strip()


def in_user_session(args) -> list:
    """`args`, wrapped so the window lands on the screen someone is using.

    A LaunchDaemon runs as root with no GUI session. Unwrapped, a browser it
    launches never appears -- which would look exactly like the office
    ignoring us, while the profile sits held open.
    """
    uid = user_id()
    if os.geteuid() != 0 or not uid:
        return list(args)     # already in a user session; nothing to do
    return ["launchctl", "asuser", uid] + list(args)
