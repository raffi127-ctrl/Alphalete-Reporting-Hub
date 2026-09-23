"""Put the sign-in window in front of whoever is at the Mac, by itself.

Megan, 2026-09-17: "We should make it where once someone is at the mac if we
need the PW it's auto popping up immediately on the screen for them."

WHAT IT REPLACES. A lost session sends a DM with a link; somebody has to find
the message, open the page, press Copy, open Terminal and paste. Every step is
a place it stops. Ryan lost 3.5 hours on 2026-09-16 and Carlos over 5, and
both machines knew within two minutes of the session dropping. The gap was
never detection.

RATE-LIMITED, HARD. The sweep runs every couple of minutes and a dead session
stays dead until a person acts, so without a cooldown this would open a window
every two minutes on top of whatever they are doing -- which is how somebody
force-quits the thing that is trying to help them, and then the sweep has no
browser at all.

IT NEVER FIGHTS THE SWEEP. Both sign-in helpers take the lock the readers
honour, so the window and the sweep cannot both hold one Chrome profile. This
only launches them; the locking is theirs.

DETACHED, ALWAYS. The helper waits up to ten minutes for a person to finish.
Waiting on that inside a sweep would blow through the next tick and every tick
after it.
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from typing import Optional

from automations.icd_alerts import config as C
from automations.icd_alerts import presence as PR

# Long enough that a person who walked away is not nagged, short enough that
# somebody arriving after lunch gets the window rather than a DM from 11am.
COOLDOWN_MINUTES = 20

SYSTEMS = {
    "servicecloud": {
        "module": "automations.icd_alerts.box_signin",
        "stamp": "box-autoprompt.txt",
        "name": "My Service Cloud",
    },
    "saraplus": {
        "module": "automations.icd_alerts.sara_signin",
        "stamp": "sara-autoprompt.txt",
        "name": "SaraPlus",
    },
    # THE PASSWORD BOX, not the browser. When SaraPlus says "invalid
    # email/password" the sign-in window cannot help: a person signs in
    # there by hand and the machine keeps its wrong saved copy (Khalil,
    # 2026-09-22/23: Francia signed in twice, the sweep stayed refused). This
    # one pops the native "Your NEW SaraPlus password" box, saves, and proves
    # it against SaraPlus before saying done (run --set-login).
    "saraplus_password": {
        "module": "automations.icd_alerts.run",
        "args": ["--set-login"],
        "stamp": "sara-password-autoprompt.txt",
        "name": "SaraPlus password",
    },
}


def _stamp_path(system: str):
    return C.APP_DIR / SYSTEMS[system]["stamp"]


def recently_offered(system: str, now: Optional[dt.datetime] = None) -> bool:
    now = now or dt.datetime.now()
    try:
        was = dt.datetime.fromisoformat(_stamp_path(system).read_text().strip())
    except (OSError, ValueError):
        return False
    return (now - was) < dt.timedelta(minutes=COOLDOWN_MINUTES)


def _remember(system: str) -> None:
    try:
        p = _stamp_path(system)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(dt.datetime.now().isoformat())
    except OSError:
        pass          # failing to remember must not stop the window opening


def offer(system: str, log=print) -> bool:
    """Open the sign-in window if -- and only if -- somebody can use it.

    Returns True when a window was launched. False is the ordinary answer and
    never an error: an empty office at 2am is exactly when this should do
    nothing at all.
    """
    spec = SYSTEMS.get(system)
    if not spec:
        return False
    if not PR.somebody_is_there():
        return False
    if recently_offered(system):
        return False

    from automations.icd_alerts import boot_schedule as B
    root = B.app_root()
    if not root:
        return False
    args = PR.in_user_session(
        [str(B.venv_python(root)), "-m", spec["module"]] + list(spec.get("args") or []))
    try:
        subprocess.Popen(args, cwd=str(root), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:  # noqa: BLE001 — a failed launch still leaves the DM
        log("could not open the %s sign-in window: %s"
            % (spec["name"], type(e).__name__))
        return False
    _remember(system)
    log("opened the %s sign-in window for %s"
        % (spec["name"], PR.console_user()))
    return True


def main(argv=None) -> int:
    system = (argv or sys.argv[1:] or ["servicecloud"])[0]
    return 0 if offer(system) else 1


if __name__ == "__main__":
    sys.exit(main())
