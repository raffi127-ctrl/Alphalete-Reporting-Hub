"""Let a CLOUD-hosted page use the same Google credentials the Macs use.

Every report reads Sheets through `fill._client()`, which loads an OAuth
client + token from ~/.config/recruiting-report/. That is right for the Lucys
and for Megan's laptop, and impossible on Streamlit Community Cloud: there is
no home directory to put them in, and nothing in the repo should ever hold
them.

So the Cloud host keeps them in its own secrets store and this writes them
back out to the paths the rest of the codebase already expects — one shim,
rather than teaching every reader a second way to authenticate.

NOTHING HERE PUTS A CREDENTIAL IN THE REPO. It moves what the host was given
into a file at runtime. On a machine that already has the files it does
nothing at all, so importing it locally is a no-op.
"""
from __future__ import annotations

import json
import os
import pathlib

_DIR = pathlib.Path.home() / ".config" / "recruiting-report"
# (file, secret/env name) — the two halves fill._client() looks for.
_WANT = (("oauth-client.json", "GOOGLE_OAUTH_CLIENT"),
         ("oauth-token.json", "GOOGLE_OAUTH_TOKEN"))


def _from_host(name: str) -> str:
    """The secret's value, from st.secrets or the environment."""
    try:
        import streamlit as st

        if name in st.secrets:
            v = st.secrets[name]
            return v if isinstance(v, str) else json.dumps(dict(v))
    except Exception:   # noqa: BLE001 — not every caller is a Streamlit run
        pass
    return os.environ.get(name, "")


def host_key_names() -> list:
    """The NAMES of the secrets the host has set. Never their values.

    A missing credential is otherwise indistinguishable from a misspelt one,
    and the person who can fix it cannot see inside the process. Names are not
    secret; values never leave this module."""
    try:
        import streamlit as st

        return sorted(str(k) for k in st.secrets.keys())
    except Exception:   # noqa: BLE001
        return []


def ensure_local_oauth(log=None):
    """Write the Google credentials to disk if missing. -> (usable, hosted).

    PREFERS THE SECRET THIS ORG ALREADY USES. `[gcp_oauth]` is described in
    onboarding_ui.build_gs_client as "the one true secrets→Sheets wiring", and
    every tool already deployed authenticates with it — so a board that
    demanded its own pair of secrets was asking somebody to paste credentials
    that were already sitting there. It holds the authorized-user JSON, which
    is exactly what fill._client() loads.

    fill._client() reads only oauth-token.json; it merely CHECKS that
    oauth-client.json exists. That second file is written from the same
    client_id / client_secret rather than stubbed, so it says something true.

    `hosted` is True when a credential had to come from the host's secret
    store, which is the honest signal that this is running somewhere public
    rather than on one of our Macs. A page uses it to decide it needs an
    access code — the machines in the office do not.

    Returns rather than raises: a page that cannot authenticate should say so
    in its own words, not crash with a traceback a reader cannot act on."""
    # HOSTED IS A FACT ABOUT THE HOST, NOT ABOUT THE DISK. Deciding it from
    # "did we have to write the files" was wrong and briefly left the board
    # ungated on a public URL: the first run writes them into the container,
    # every rerun after that sees them on disk and concludes it is a Mac in
    # the office. Ask the host instead — a machine in the office has no
    # secrets store with our Google credential in it.
    secret_tok = _gcp_oauth() or _json_secret("GOOGLE_OAUTH_TOKEN")
    hosted = bool(secret_tok)

    token_p, client_p = _DIR / "oauth-token.json", _DIR / "oauth-client.json"
    if token_p.exists() and client_p.exists():
        ensure_local_oauth.missing = []
        return True, hosted

    tok = secret_tok
    if not tok:
        ensure_local_oauth.missing = ["gcp_oauth"]
        if log:
            log("missing credential: gcp_oauth")
        return False, True
    _DIR.mkdir(parents=True, exist_ok=True)
    token_p.write_text(json.dumps(tok))
    token_p.chmod(0o600)
    if not client_p.exists():
        client_p.write_text(json.dumps({"installed": {
            "client_id": tok.get("client_id", ""),
            "client_secret": tok.get("client_secret", ""),
            "token_uri": tok.get("token_uri",
                                 "https://oauth2.googleapis.com/token"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth"}}))
        client_p.chmod(0o600)
    ensure_local_oauth.missing = []
    return True, hosted


def _gcp_oauth():
    """The org's existing [gcp_oauth] secret, as a plain dict."""
    try:
        import streamlit as st

        o = st.secrets.get("gcp_oauth")
        return dict(o) if o else None
    except Exception:   # noqa: BLE001 — not every caller is a Streamlit run
        return None


def _json_secret(name: str):
    """A secret holding raw JSON text, for a host that has it that way."""
    raw = _from_host(name)
    try:
        return json.loads(raw) if raw.strip() else None
    except ValueError:
        return None
