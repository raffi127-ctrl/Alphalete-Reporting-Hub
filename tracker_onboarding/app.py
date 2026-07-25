"""Tracker Onboarding — add an office to the daily Tableau tracker screenshots.

For Megan/Eve. The trackers are universal boards (the same images post to every
channel), so onboarding an office is just: its Slack channel + which trackers it
wants, in what order. On submit this writes the config to the 'Tracker Onboarding'
tab of the AUTOMATION MASTER sheet; `apply` then adds it to the tracker run's
channel list, and the existing daily run + Hub card pick it up (no schedule entry,
no machine choice).

Run locally:   .venv/bin/streamlit run tracker_onboarding/app.py
On the web:    deploy this repo to Streamlit Community Cloud with
               tracker_onboarding/app.py as the entry point.

No access-code gate — internal Megan/Eve tool.
Secrets: [gcp_service_account] / [gcp_oauth] for the master sheet. Without creds
it saves to a local draft (sandbox). TRACKER_ONBOARDING_LOCAL_ONLY=1 forces that.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automations.tracker_onboarding import schema as S, store  # noqa: E402

st.set_page_config(page_title="Tracker Onboarding", page_icon="📊",
                   layout="centered")


def _inject_gs_client() -> None:
    if os.environ.get("TRACKER_ONBOARDING_LOCAL_ONLY") == "1":
        return
    try:
        import gspread
    except Exception:
        return
    try:
        sa = st.secrets.get("gcp_service_account")
    except Exception:
        sa = None
    if sa:
        store.set_client(gspread.service_account_from_dict(dict(sa)))
        return
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
        store.set_client(gspread.authorize(creds))


def form_view() -> None:
    st.markdown("## 📊 Tracker Onboarding")
    st.caption("Add an office to the daily Tableau tracker screenshots. The "
               "trackers are the same boards everyone gets — just pick this "
               "office's Slack channel and which trackers to post, in what order. "
               "On submit it saves the config; the daily run + Hub card pick it up "
               "once applied.")

    # ---- 1. Office & channel ---------------------------------------------
    st.divider()
    st.markdown("### 1. Office & channel")
    owner = st.text_input(
        "Office / owner name *",
        help="Just for identity + the office key (e.g. 'Aeon' or 'Cody Cannon').")
    c1, c2 = st.columns(2)
    with c1:
        channel_id = st.text_input("Channel ID *", placeholder="C0…",
                                   help="Right-click the channel → View channel "
                                        "details → the ID at the bottom.")
    with c2:
        channel_name = st.text_input("Channel name *", placeholder="#aeon-sales")

    key_default = S.slug_from(owner)
    if st.checkbox("Set a custom internal id (rarely needed)", value=False,
                   help="Auto-made from the office name; only change it if another "
                        "office already uses that id."):
        key = st.text_input("Internal id", value=key_default).strip()
    else:
        key = key_default
        if owner.strip():
            st.caption(f"Internal id: `{key}` — auto-set from the office name.")

    # ---- 2. Trackers to post ---------------------------------------------
    st.divider()
    st.markdown("### 2. Trackers to post")
    catalog = S.tracker_catalog()
    if not catalog:
        st.error("Couldn't load the tracker list (tableau_screenshots.pages "
                 "import failed). The form can't build the checklist.")
        catalog = []
    st.caption("Check the trackers this office should get. The number sets the "
               "order they appear in the post (lower = earlier). Opt-in trackers "
               "are unchecked by default.")
    default_on = set(S.default_selection())
    picked: list = []            # (tracker_id, order)
    for i, t in enumerate(catalog):
        oc1, oc2 = st.columns([6, 1])
        with oc1:
            lbl = f"{t['emoji']} {t['title']}" + ("  · opt-in" if t["opt_in"] else "")
            on = st.checkbox(lbl, value=(t["id"] in default_on), key=f"trk_{t['id']}")
        with oc2:
            order = st.number_input("order", 1, 99, i + 1, key=f"ord_{t['id']}",
                                    label_visibility="collapsed", disabled=not on)
        if on:
            picked.append((t["id"], int(order)))
    trackers = [tid for tid, _ in sorted(picked, key=lambda x: x[1])]

    # ---- build + submit --------------------------------------------------
    st.divider()
    rec = S.TrackerRecord(
        key=(key or "").strip(), owner=owner.strip(),
        channel_id=channel_id.strip(), channel_name=channel_name.strip(),
        trackers=trackers)

    if st.button("💾 Submit office", type="primary"):
        reg = store.existing_registry(exclude_key=rec.key)
        problems = S.validate(rec, existing_keys=reg["keys"],
                              existing_channels=reg["channels"])
        if problems:
            st.error("Fix these before submitting:")
            for p in problems:
                st.markdown(f"- {p}")
            return
        rec.submitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        rec.submitted_by = "Megan"
        try:
            where = store.save(rec)
        except Exception as e:                       # noqa: BLE001
            st.error(f"Couldn't save: {e}")
            return
        st.session_state["_last_submit"] = {"rec": rec.to_json(), "where": where}
        st.rerun()

    _show_result(catalog)


def _show_result(catalog) -> None:
    res = st.session_state.get("_last_submit")
    if not res:
        return
    d = res["rec"]
    st.divider()
    dest = ("the **Tracker Onboarding** tab" if res["where"] == "sheet"
            else "a **local draft** (`output/tracker_onboarding_submissions.json`) "
                 "— no Google creds, so nothing hit the live master sheet")
    st.success(f"Saved {d['key']} to {dest}.")
    titles = {t["id"]: f"{t['emoji']} {t['title']}" for t in catalog}
    order_lines = "\n".join(f"{i+1}. {titles.get(tid, tid)}"
                            for i, tid in enumerate(d.get("trackers", [])))
    st.markdown(f"**{d['channel_name']}** will post these trackers, in order:")
    st.markdown(order_lines)
    st.markdown("#### Apply it")
    st.caption("Run it, review `git diff`, then commit + push. The next daily "
               "tracker run posts to this channel; the Hub card lists it too. "
               "Nothing is auto-pushed.")
    st.code(f"python -m automations.tracker_onboarding.apply --only {d['key']}\n"
            f"python -m automations.tracker_onboarding.apply --only {d['key']} --write",
            language="bash")
    if st.button("Onboard another office"):
        del st.session_state["_last_submit"]
        st.rerun()


# --------------------------------------------------------------------------
_inject_gs_client()
form_view()
