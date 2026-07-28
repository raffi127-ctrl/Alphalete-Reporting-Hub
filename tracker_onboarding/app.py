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


def _inject_gs_client() -> dict:
    """Wire the Sheets client from secrets. Returns a KEYS-ONLY diagnostic (never
    secret values) so `?debug=1` can show WHY it fell back to a local draft."""
    diag = {"local_only": os.environ.get("TRACKER_ONBOARDING_LOCAL_ONLY"),
            "gspread_import": False, "secret_keys": None, "has_gcp_oauth": False,
            "has_gcp_service_account": False, "oauth_field_keys": None,
            "client_set": False, "error": ""}
    if os.environ.get("TRACKER_ONBOARDING_LOCAL_ONLY") == "1":
        diag["error"] = "TRACKER_ONBOARDING_LOCAL_ONLY=1 forces local draft"
        return diag
    try:
        import gspread
        diag["gspread_import"] = True
    except Exception as e:                       # noqa: BLE001
        diag["error"] = f"gspread import failed: {type(e).__name__}: {e}"
        return diag
    try:
        diag["secret_keys"] = sorted(list(st.secrets.keys()))
    except Exception as e:                       # noqa: BLE001
        diag["error"] = f"st.secrets unreadable: {type(e).__name__}: {e}"
    try:
        sa = st.secrets.get("gcp_service_account")
    except Exception:
        sa = None
    diag["has_gcp_service_account"] = bool(sa)
    if sa:
        try:
            store.set_client(gspread.service_account_from_dict(dict(sa)))
            diag["client_set"] = True
        except Exception as e:                   # noqa: BLE001
            diag["error"] = f"service_account client failed: {type(e).__name__}: {e}"
        return diag
    try:
        o = st.secrets.get("gcp_oauth")
    except Exception:
        o = None
    diag["has_gcp_oauth"] = bool(o)
    if o:
        try:
            diag["oauth_field_keys"] = sorted(list(dict(o).keys()))
        except Exception:
            pass
    if not o:
        tok = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"
        if tok.exists():
            import json
            o = json.loads(tok.read_text())
    if o:
        try:
            from google.oauth2.credentials import Credentials
            creds = Credentials(
                token=o.get("token"), refresh_token=o.get("refresh_token"),
                token_uri=o.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=o.get("client_id"), client_secret=o.get("client_secret"),
                scopes=list(o.get("scopes") or
                            ["https://www.googleapis.com/auth/spreadsheets"]))
            store.set_client(gspread.authorize(creds))
            diag["client_set"] = True
        except Exception as e:                   # noqa: BLE001 — report, don't crash
            diag["error"] = f"oauth client build failed: {type(e).__name__}: {e}"
    return diag


def _enqueue_onboard(key: str, *, post: bool) -> "tuple":
    """Drop a mini_control `onboard_apply tracker <key>` job so the mini wires the
    office (apply --write into its working tree → joins the daily tracker run) and,
    with --post, runs the tracker post now. Trackers run on the default machine
    (Lucy 1). Reuses the form's own Sheets client (the queue is a tab on this same
    master sheet). Best-effort; returns (ok, note)."""
    gc = store.get_client()
    if gc is None:
        return False, "no Sheets client (local-draft mode)"
    try:
        from automations.day_orchestrator import queue_enqueue as qenq
        args = f"tracker {key}" + (" --post" if post else "")
        tab = qenq.enqueue(gc, "onboard_apply", args, by="Megan")
        return True, tab
    except Exception as e:                           # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


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
        # Auto-wire: hand the mini an apply job so this office joins the daily
        # tracker run with no manual apply/commit. Only when it hit the Sheet.
        wired = _enqueue_onboard(rec.key, post=False) if where == "sheet" else (False, "local")
        st.session_state["_last_submit"] = {"rec": rec.to_json(), "where": where,
                                            "wired": wired}
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

    if res["where"] == "sheet":
        wired_ok, wired_note = res.get("wired", (False, ""))
        if wired_ok:
            st.success("✅ Auto-wiring into the daily tracker run — the mini is "
                       "applying it now (live in the next run, ~1–2 min). "
                       "No commands to run.")
        else:
            st.warning(f"Saved to the Sheet, but couldn't auto-wire ({wired_note}). "
                       "Use the fallback commands below.")
        st.markdown("#### Post it to the channel now")
        st.caption(f"Runs the trackers for {d['channel_name']} and posts them "
                   "immediately (otherwise they first appear in tomorrow's run).")
        if st.button(f"▶️ Post to {d['channel_name']} now", type="primary"):
            ok, note = _enqueue_onboard(d["key"], post=True)
            if ok:
                st.success(f"Queued — the mini will post to {d['channel_name']} in "
                           "~1–2 min. Watch the channel.")
            else:
                st.error(f"Couldn't queue the post: {note}")
        with st.expander("Prefer to run it by hand? (fallback commands)"):
            st.code(f"python -m automations.tracker_onboarding.apply --only {d['key']} --write",
                    language="bash")
    else:
        st.markdown("#### Apply it")
        st.caption("No Google creds here, so it saved locally. Run this where the "
                   "repo lives, review `git diff`, then commit + push.")
        st.code(f"python -m automations.tracker_onboarding.apply --only {d['key']} --write",
                language="bash")

    if st.button("Onboard another office"):
        del st.session_state["_last_submit"]
        st.rerun()


# --------------------------------------------------------------------------
_diag = _inject_gs_client()
# ?debug=1 shows a KEYS-ONLY readout of what the app can see in its secrets
# (never any secret value) — so a "why is it still a local draft?" is answerable
# without guessing. Safe to leave in; invisible unless the query param is set.
try:
    _dbg = str(st.query_params.get("debug", "")).lower() in ("1", "true", "yes")
except Exception:
    _dbg = False
if _dbg:
    st.warning("🔧 secrets diagnostic (keys only, no values):")
    st.json(_diag)
form_view()
