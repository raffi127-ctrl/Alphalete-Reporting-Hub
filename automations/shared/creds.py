"""Local credential loader — keeps the ownerville login OUT of source.

The repo was public with the ownerville password hardcoded (Megan 2026-05-25,
chose not to rotate). This reads the login from a GITIGNORED file at the repo
root (or env vars) instead, so the password never lives in the code — public or
private. NOTHING is hardcoded here: if the login isn't found, it raises a clear
error telling you to create the file.

  ownerville-creds.json  (repo root, gitignored, NEVER commit):
    {
      "ownerville_username": "rhidalgo",
      "ownerville_password": "..."
    }
  or env vars: OWNERVILLE_USERNAME / OWNERVILLE_PASSWORD

Each machine that runs login-based reports needs this file — distributed
out-of-band (not through the repo). Upload-only reports (Financial, Frontier,
First/Last Sale) don't touch it.
"""
from __future__ import annotations

import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path

_CREDS_PATH = Path(__file__).resolve().parents[2] / "ownerville-creds.json"


@lru_cache(maxsize=1)
def _file() -> dict:
    try:
        return json.loads(_CREDS_PATH.read_text())
    except Exception:
        return {}


def reload() -> None:
    """Forget the cached credential files — call this after WRITING one from
    inside a long-lived process.

    `_file()` is read once per process, which is right for a report run and
    wrong for the mini's poller: it reads the file at startup and then lives for
    days. So an installer that writes a credential and immediately verifies it
    was checking the cached copy, not what it had just written. On 2026-08-27
    `set_doubleentry_creds` wrote the missing Double Entry login onto Lucy 1 and
    then reported "SIGN-IN FAILED: Missing Double Entry credential" — the
    credential was on disk the whole time. Wrong twice over: the row goes red on
    a good install, and a genuinely bad password would look identical."""
    _file.cache_clear()
    _alt_file.cache_clear()


def _resolve(key: str, env: str) -> str:
    val = str(_file().get(key) or os.environ.get(env, "")).strip()
    if not val:
        raise RuntimeError(
            f"Missing credential {key!r}. Create '{_CREDS_PATH.name}' at the repo "
            f"root containing {{\"ownerville_username\": ..., \"ownerville_password\": "
            f"...}} (ask Megan for the login), or set the {env} environment "
            "variable. That file is gitignored — never commit it."
        )
    return val


def ownerville_username() -> str:
    return _resolve("ownerville_username", "OWNERVILLE_USERNAME")


def ownerville_password() -> str:
    return _resolve("ownerville_password", "OWNERVILLE_PASSWORD")


# --- AppStream (ApplicantStream) recruiting login (account: rcaptain) ---------
# Source order: gitignored creds file → env → macOS keychain (where it already
# lives via `security add-generic-password -a applicantstream -s applicantstream-
# <field>`). Never hardcoded — the repo was public.
def _keychain(service: str) -> str:
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-a", "applicantstream",
             "-s", service, "-w"],
            capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _resolve_as(key: str, env: str, keychain_service: str) -> str:
    val = (str(_file().get(key) or "").strip()
           or os.environ.get(env, "").strip()
           or _keychain(keychain_service))
    if not val:
        raise RuntimeError(
            f"Missing AppStream credential {key!r}. Add it to "
            f"'{_CREDS_PATH.name}', set {env}, or store it in the keychain: "
            f"security add-generic-password -a applicantstream -s "
            f"{keychain_service} -w. Never commit it."
        )
    return val


def appstream_username() -> str:
    return _resolve_as("appstream_username", "APPLICANTSTREAM_USERNAME",
                       "applicantstream-username")


def appstream_password() -> str:
    return _resolve_as("appstream_password", "APPLICANTSTREAM_PASSWORD",
                       "applicantstream-password")


# --- Double Entry (doubleentry.com) financial login ---------------------------
# The weekly financials used to arrive as emailed .xlsx workbooks; they now come
# off the Double Entry org summary report, which needs a login. Same rule as
# every other credential here: it lives in the gitignored creds file or an env
# var, NEVER in the code. Add to 'ownerville-creds.json' at the repo root:
#   {"doubleentry_username": "...@gmail.com", "doubleentry_password": "..."}
# or set DOUBLEENTRY_USERNAME / DOUBLEENTRY_PASSWORD.
def _resolve_de(key: str, env: str) -> str:
    val = str(_file().get(key) or os.environ.get(env, "")).strip()
    if not val:
        raise RuntimeError(
            f"Missing Double Entry credential {key!r}. Add it to "
            f"'{_CREDS_PATH.name}' at the repo root "
            f"({{\"doubleentry_username\": ..., \"doubleentry_password\": ...}}) "
            f"or set the {env} environment variable. That file is gitignored — "
            "never commit it."
        )
    return val


def doubleentry_username() -> str:
    return _resolve_de("doubleentry_username", "DOUBLEENTRY_USERNAME")


def doubleentry_password() -> str:
    return _resolve_de("doubleentry_password", "DOUBLEENTRY_PASSWORD")


# --- Alternate AppStream account -------------------------------------------
# A machine may need a SECOND AppStream login: Lucy 2 runs as CarlosNLR, which
# cannot see six of the 28 offices, while rcaptain can. Rather than overwrite the
# primary (other reports on that machine depend on it), the alternate lives
# beside it and each job picks the account it needs.
_ALT_PATH = Path.home() / ".config" / "recruiting-report" / "appstream-alt.json"


@lru_cache(maxsize=1)
def _alt_file() -> dict:
    # Outside the repo on purpose: the repo is public, and this is a live login.
    try:
        return json.loads(_ALT_PATH.read_text())
    except Exception:
        return {}


def appstream_alt_username() -> str:
    return (str(_alt_file().get("appstream_alt_username") or "").strip()
            or _resolve_as("appstream_alt_username", "APPLICANTSTREAM_ALT_USERNAME",
                           "applicantstream-alt-username"))


def appstream_alt_password() -> str:
    return (str(_alt_file().get("appstream_alt_password") or "").strip()
            or _resolve_as("appstream_alt_password", "APPLICANTSTREAM_ALT_PASSWORD",
                           "applicantstream-alt-password"))


def has_appstream_alt() -> bool:
    """True if this machine has a second AppStream account configured."""
    try:
        return bool(appstream_alt_username() and appstream_alt_password())
    except Exception:  # noqa: BLE001 — missing is a normal state, not an error
        return False
