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


def ensure_local_oauth(log=None):
    """Write the Google credentials to disk if missing. -> (usable, hosted).

    `hosted` is True when a credential had to be taken from the host's secret
    store, which is the honest signal that this is running somewhere public
    rather than on one of our Macs. A page can use it to decide it needs an
    access code — the machines in the office do not.

    Returns rather than raises: a page that cannot authenticate should say so
    in its own words, not crash with a traceback a reader cannot act on."""
    ok, hosted = True, False
    for fname, secret in _WANT:
        path = _DIR / fname
        if path.exists():
            continue
        raw = _from_host(secret)
        if not raw.strip():
            ok = False
            if log:
                log(f"missing credential: {secret}")
            continue
        _DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(raw)
        # The token is a live credential; keep it off other users of the host.
        path.chmod(0o600)
        hosted = True
    return ok, hosted
