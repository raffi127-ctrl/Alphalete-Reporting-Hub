"""Edit Your Office Metrics — the owner-scoped Thread Builder.

An office owner enters their code (the same one from their welcome email / Pay
Structure) and gets a section editor LOCKED to their office only: turn each metric
on or off and reorder them. Saves to the shared 'Thread Plans' sheet; the change
goes live the next morning — no re-wiring, no deploy.

This reuses the exact editor the admin uses (thread_builder.editor), just scoped to
one office via the code gate, so owners self-serve the common "add/remove a metric"
change without touching the onboarding form.

Run locally:   .venv/bin/streamlit run metric_edit/app.py
On the web:    deploy to Streamlit Community Cloud with metric_edit/app.py as the
               entry point (suggested subdomain alphaletemetricsedit).

Secrets (Streamlit Cloud, or .streamlit/secrets.toml locally):
  [gcp_service_account] / [gcp_oauth]   # Google creds for the master sheet
Set METRIC_EDIT_LOCAL_ONLY=1 to force a no-creds local sandbox.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automations.office_onboarding import store as _oo_store  # noqa: E402

st.set_page_config(page_title="Edit Your Office Metrics", page_icon="✏️",
                   layout="centered")


# --------------------------------------------------------------------------
def _build_gs_client():
    if os.environ.get("METRIC_EDIT_LOCAL_ONLY") == "1":
        return None
    try:
        import gspread
    except Exception:
        return None
    try:
        sa = st.secrets.get("gcp_service_account")
    except Exception:
        sa = None
    if sa:
        return gspread.service_account_from_dict(dict(sa))
    try:
        o = st.secrets.get("gcp_oauth")
    except Exception:
        o = None
    if not o:
        tok = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"
        if tok.exists():
            import json
            o = json.loads(tok.read_text())
    if o:
        from google.oauth2.credentials import Credentials
        creds = Credentials(
            token=o.get("token"), refresh_token=o.get("refresh_token"),
            token_uri=o.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=o.get("client_id"), client_secret=o.get("client_secret"),
            scopes=list(o.get("scopes") or
                        ["https://www.googleapis.com/auth/spreadsheets"]))
        return gspread.authorize(creds)
    return None


def _inject_clients() -> None:
    """Share one client with the two stores this app reads/writes: pay_structure
    (to resolve the owner's code → office) and thread_builder (to save the plan)."""
    gc = _build_gs_client()
    if gc is None:
        return
    try:
        from automations.pay_structure import store as _ps
        os.environ.setdefault("PAY_STRUCTURE_SHEET_ID", _oo_store.MASTER_SHEET_ID)
        _ps.set_client(gc)
    except Exception:                                # noqa: BLE001
        pass
    try:
        from automations.thread_builder import store as _tbs
        _tbs.set_client(gc)
    except Exception:                                # noqa: BLE001
        pass


def _resolve_office(code: str) -> "dict | None":
    """Map an owner's code → {key, campaign, label} using the Pay Structure codes
    (the same code from their welcome email). None when it doesn't match a live
    office. Best-effort: a read error just fails the match."""
    code = (code or "").strip().lower()
    if not code:
        return None
    try:
        from automations.pay_structure import store as _ps
        codes = _ps.load_codes() or {}
    except Exception:                                # noqa: BLE001
        codes = {}
    key = next((k for k, c in codes.items()
                if str(c).strip().lower() == code), None)
    if not key:
        return None
    from automations.thread_builder import catalog as C
    for campaign in C.CAMPAIGNS:
        for k, label in C.offices(campaign):
            if k == key:
                return {"key": key, "campaign": campaign, "label": label}
    return None


# --------------------------------------------------------------------------
def _gate() -> None:
    st.markdown("## ✏️ Edit your office metrics")
    st.caption("Turn each metric on or off for your daily Slack thread, or reorder "
               "them. Changes go live the next morning — no waiting on setup.")
    st.divider()
    code = st.text_input(
        "Your office code",
        help="The code from your welcome email (the same one you use on the Pay "
             "Structure site).")
    if st.button("Continue →", type="primary"):
        info = _resolve_office(code)
        if not info:
            st.error("That code didn't match an office. Double-check it — or "
                     "message Megan and she'll sort it out.")
            return
        st.session_state["_edit_office"] = info
        st.rerun()


def _editor() -> None:
    info = st.session_state["_edit_office"]
    st.markdown("## ✏️ {}".format(info["label"]))
    st.caption("Check a metric to include it in your morning thread, uncheck to "
               "drop it, and set the order. Saved changes post starting the next "
               "morning.")
    st.info("Heads-up: churn and ABP metrics need a one-time setup on our end. If "
            "you enable one and it isn't posting the next day, message Megan to "
            "finish wiring it.")
    st.divider()
    from automations.thread_builder.editor import SheetBackend, render_owner_editor
    render_owner_editor(SheetBackend(), info["campaign"], info["key"],
                        info["label"], by="owner:{}".format(info["key"]))
    st.divider()
    if st.button("← Done / switch office"):
        del st.session_state["_edit_office"]
        st.rerun()


# --------------------------------------------------------------------------
_inject_clients()
if st.session_state.get("_edit_office"):
    _editor()
else:
    _gate()
