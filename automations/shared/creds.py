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


# --- Sara Plus (saraplus.com) login — B2B WE sales board pull -----------------
# Direct email+password form at /e/servicepages/login.aspx (no 2FA). Same
# gitignored-file → env source order; never hardcoded (the repo was public).
def saraplus_username() -> str:
    return _resolve("saraplus_username", "SARAPLUS_USERNAME")


def saraplus_password() -> str:
    return _resolve("saraplus_password", "SARAPLUS_PASSWORD")
