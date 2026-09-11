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

APP_DIR = Path.home() / ".config" / "lucy-reports"
CREDS_PATH = APP_DIR / "saraplus-creds.json"
OV_CREDS_PATH = APP_DIR / "ownerville-creds.json"
INSTALL_PATH = APP_DIR / "install.json"
STATE_PATH = APP_DIR / "state.json"
PROFILE_DIR = APP_DIR / "chrome-profile"
# A SEPARATE profile from SaraPlus's, so the two never fight over a locked
# profile directory. Note this is NOT a separate OwnerVille session -- that
# lives on the server, one per machine -- which is fine here precisely because
# this read never impersonates: an owner reading their own office cannot
# retarget anybody's session, including their own if they are signed in in
# their normal browser at the same time.
OV_PROFILE_DIR = APP_DIR / "chrome-profile-ov"
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


def ownerville_creds() -> Dict[str, str]:
    """{'username', 'password'} for this owner's OWN OwnerVille login.

    THEIR login, never ours. An owner's account sees their own office natively,
    so the knocks read needs no impersonation at all -- which deletes the
    single flakiest step in the knocks stack (the one that once returned
    Calvin's seven reps under Kash's heading, and the read-only probe that
    stranded a session and fed Raf an impersonated board twice in one
    afternoon). Two machines on one OwnerVille login do not evict each other;
    the one-session rule is per box, across processes.
    """
    env_user = os.environ.get("OWNERVILLE_USERNAME")
    env_pass = os.environ.get("OWNERVILLE_PASSWORD")
    if env_user and env_pass:
        return {"username": env_user, "password": env_pass}
    if not OV_CREDS_PATH.exists():
        raise RuntimeError(
            "No OwnerVille login saved yet on this computer. Open the alerts "
            "app and enter your OwnerVille username and password.")
    data = json.loads(OV_CREDS_PATH.read_text())
    missing = [k for k in ("username", "password") if not data.get(k)]
    if missing:
        raise RuntimeError(
            "The saved OwnerVille login is incomplete (missing %s). Open the "
            "alerts app and enter it again." % ", ".join(missing))
    return {"username": data["username"], "password": data["password"]}


def save_ownerville_creds(username: str, password: str) -> Path:
    """Saved beside the SaraPlus one, and just as local. Neither is relayed."""
    app_dir()
    OV_CREDS_PATH.write_text(json.dumps({"username": username,
                                         "password": password}))
    try:
        OV_CREDS_PATH.chmod(0o600)
    except OSError:
        pass
    return OV_CREDS_PATH


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


def save_requested_channels(channels) -> Path:
    """Remember where this office asked their alerts to go.

    A REQUEST, not a setting, and a LIST: nothing on this machine can put a
    message in a Slack channel, and an office can want the pings in more than
    one room. Stored here so re-running the installer is how an owner changes
    the answer.
    """
    app_dir()
    rec = dict(install())
    rec["requested_channels"] = [str(c).strip() for c in (channels or [])
                                 if str(c).strip()]
    INSTALL_PATH.write_text(json.dumps(rec, indent=2))
    return INSTALL_PATH


# --- when this office is worth reading ------------------------------------
# THE LAPTOP'S OWN CLOCK IS THE RIGHT ONE. An ICD's machine sits in their
# office, so local time IS office time -- unlike OwnerVille, whose timezone
# field describes the LOGIN and not the office. No timezone has to be
# configured, and nobody has to be asked which one they are in.
#
# SaraPlus is cumulative within a day, so a late start loses nothing: the first
# sweep of the day reads the whole day so far. That makes a narrow window cheap
# and a wide one wasteful -- the Alphalete sweep spent 36 logins before anyone
# knocked a door until its start moved to 10:00.
DAY_START_HHMM = (10, 0)
DAY_END_HHMM = (21, 30)
SATURDAY_END_HHMM = (17, 0)
SELLING_DAYS = (0, 1, 2, 3, 4, 5)      # Mon-Sat; Sunday is not a selling day


def in_selling_window(now: Optional[dt.datetime] = None) -> bool:
    now = now or dt.datetime.now()
    if now.weekday() not in SELLING_DAYS:
        return False
    start = now.replace(hour=DAY_START_HHMM[0], minute=DAY_START_HHMM[1],
                        second=0, microsecond=0)
    end_h, end_m = (SATURDAY_END_HHMM if now.weekday() == 5 else DAY_END_HHMM)
    end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    return start <= now <= end


def today() -> dt.date:
    """The ICD's LOCAL day. SaraPlus reports the day the office is selling, and
    that office is not necessarily in Central -- reading Megan's day here would
    ask for the wrong date in a different timezone with no error anywhere."""
    return dt.date.today()
