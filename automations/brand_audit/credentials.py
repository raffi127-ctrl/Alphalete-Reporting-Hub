"""API-key loader for the Brand Health audit — keeps keys OUT of source.

Source order (first hit wins), mirroring automations/shared/creds.py:
  1. ~/.config/brand-audit/keys.json   (per-machine, outside the repo)
  2. brand-audit-keys.json at repo root (gitignored)
  3. environment variables

keys.json shape:
  {
    "google_places_api_key": "...",
    "serpapi_api_key": "..."
  }

Nothing is hardcoded: if a key is missing we raise a clear error telling you
exactly where to put it. Reddit needs no key (keyless public data); the Google
Business Profile + posting keys arrive in later phases.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from automations.brand_audit.config import REPO_ROOT

_HOME_PATH = Path.home() / ".config" / "brand-audit" / "keys.json"
_REPO_PATH = REPO_ROOT / "brand-audit-keys.json"


@lru_cache(maxsize=1)
def _file() -> dict:
    for path in (_HOME_PATH, _REPO_PATH):
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return {}


def _resolve(key: str, env: str) -> str:
    val = str(_file().get(key) or os.environ.get(env, "")).strip()
    if not val:
        raise RuntimeError(
            f"Missing API key {key!r}. Add it to '{_HOME_PATH}' (preferred) or "
            f"'{_REPO_PATH.name}' at the repo root as {{\"{key}\": \"...\"}}, or "
            f"set the {env} environment variable. Those files are gitignored / "
            "outside the repo — never commit a key."
        )
    return val


def google_places_api_key() -> str:
    return _resolve("google_places_api_key", "GOOGLE_PLACES_API_KEY")


def serpapi_api_key() -> str:
    return _resolve("serpapi_api_key", "SERPAPI_API_KEY")


def anthropic_api_key() -> str:
    return _resolve("anthropic_api_key", "ANTHROPIC_API_KEY")


def optional(key: str, env: str | None = None):
    """Return a key if present (file or env), else None — for credentials that
    only some companies have wired up (e.g. Meta token). Never raises."""
    val = str(_file().get(key) or os.environ.get(env or key.upper(), "")).strip()
    return val or None


def has(key: str) -> bool:
    """True if a key is available without raising — lets collectors skip soft."""
    try:
        return bool(str(_file().get(key) or os.environ.get(key.upper(), "")).strip())
    except Exception:
        return False
