"""Where one ICD install keeps its credential, its state and its browser.

EVERYTHING IS UNDER THE USER'S HOME, never under the repo. The ICD app may be
installed somewhere the user cannot write, and the repo copy gets replaced on
every update -- a Chrome profile parked inside it would be destroyed by a
`git pull`, and losing the profile is what re-triggers SaraPlus's "new location
or browser" passcode challenge. The profile surviving updates is the whole
reason the challenge fires once instead of every week.

ITS OWN CHROME PROFILE, not the user's. Pointing a launch at the ICD's real
Chrome profile would fight their own browsing, and a profile already held by a
running Chrome blocks the launch outright.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Dict, Optional

APP_DIR = Path.home() / ".config" / "alphalete-alerts"
CREDS_PATH = APP_DIR / "saraplus-creds.json"
INSTALL_PATH = APP_DIR / "install.json"
STATE_PATH = APP_DIR / "state.json"
PROFILE_DIR = APP_DIR / "chrome-profile"
LOG_PATH = APP_DIR / "agent.log"

# The service filter and grid that carry credit checks. Imported rather than
# retyped so a SaraPlus change is fixed in ONE place for every report here.
from automations.shared.saraplus import (  # noqa: E402
    AGENT_ROW_INTERNET, COL_INTERNET, GRID_INTERNET,
)

SERVICE_INTERNET = "AT&T Internet"
LOGIN_URL = "https://ui.saraplus.com"


def app_dir() -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DIR


def creds() -> Dict[str, str]:
    """{'email', 'password'} typed in by the ICD on this machine.

    Raises with the fix in plain English -- a non-technical owner reads this
    error, not us.
    """
    env_user = os.environ.get("SARA_PLUS_EMAIL")
    env_pass = os.environ.get("SARA_PLUS_PASSWORD")
    if env_user and env_pass:
        return {"email": env_user, "password": env_pass}
    if not CREDS_PATH.exists():
        raise RuntimeError(
            "No SaraPlus login saved yet on this computer. Open the alerts app "
            "and enter your SaraPlus email and password.")
    data = json.loads(CREDS_PATH.read_text())
    missing = [k for k in ("email", "password") if not data.get(k)]
    if missing:
        raise RuntimeError(
            "The saved SaraPlus login is incomplete (missing %s). Open the "
            "alerts app and enter it again." % ", ".join(missing))
    return {"email": data["email"], "password": data["password"]}


def save_creds(email: str, password: str) -> Path:
    """Write the login this machine will use. 0600 where the OS supports it.

    The password stays on this machine and is never relayed: the whole reason
    the read happens here is so it never has to travel.
    """
    app_dir()
    CREDS_PATH.write_text(json.dumps({"email": email, "password": password}))
    try:
        CREDS_PATH.chmod(0o600)      # no-op on Windows, and that is fine
    except OSError:
        pass
    return CREDS_PATH


def install() -> Dict:
    """Who this install is. Written once at setup, read on every run."""
    if not INSTALL_PATH.exists():
        return {}
    try:
        return json.loads(INSTALL_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_install(office_key: str, owner: str) -> Path:
    app_dir()
    rec = dict(install())
    rec.update({"office_key": office_key, "owner": owner})
    INSTALL_PATH.write_text(json.dumps(rec, indent=2))
    return INSTALL_PATH


def today() -> dt.date:
    """The ICD's LOCAL day. SaraPlus reports the day the office is selling, and
    that office is not necessarily in Central -- reading Megan's day here would
    ask for the wrong date in a different timezone with no error anywhere."""
    return dt.date.today()
