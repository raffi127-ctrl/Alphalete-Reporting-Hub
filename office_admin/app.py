"""Office Admin -- one login per office admin, two buttons.

  * Send background checks   today's 2nd interviews offered the position, on THIS
                             computer, sent from the office's ECO computer
                             (the one holding the Sterling login)
  * Add 2nd round contacts   this week's 2nd rounds -> the office's contacts
                             (done by Lucy 1)

Runs ON THE ADMIN'S COMPUTER (Megan 2026-11-03), which is somewhere else than
the office's ECO computer. See automations/office_admin/config.py.

    streamlit run office_admin/app.py

Setup on the admin's computer, once (Lucy's team does it):
  * ApplicantStream login saved on this computer
      python -m automations.shared.tableau_patchright --appstream-login
  * this computer connected to the office's relay
      python -m automations.office_admin.relay_client --setup <office>
  * the admin's login
      python -m automations.office_admin.accounts --add <username> --office <office> --generate
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automations.office_admin import accounts as A  # noqa: E402
from automations.office_admin import config as C  # noqa: E402
from automations.office_admin import sheets as S  # noqa: E402

st.set_page_config(page_title="Office Admin", page_icon="🗂️", layout="centered")

MAX_TRIES = 5
LOCK_SECONDS = 300


def _secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:  # noqa: BLE001 -- no secrets file locally
        return default


def _setup() -> None:
    sid = _secret("office_admin_sheet_id")
    if sid:
        os.environ[C.SHEET_ID_ENV] = str(sid).strip()
    try:
        import gspread
    except Exception:  # noqa: BLE001
        return
    sa = _secret("gcp_service_account")
    if sa:
        S.set_client(gspread.service_account_from_dict(dict(sa)))
        return
    o = _secret("gcp_oauth")
    if not o:
        tok = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"
        if tok.exists():
            o = json.loads(tok.read_text())
    if o:
        from google.oauth2.credentials import Credentials
        creds = Credentials(
            token=o.get("token"), refresh_token=o.get("refresh_token"),
            token_uri=o.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=o.get("client_id"), client_secret=o.get("client_secret"),
            scopes=list(o.get("scopes") or ["https://www.googleapis.com/auth/spreadsheets"]))
        S.set_client(gspread.authorize(creds))


# ------------------------------------------------------------------ login --

def _login() -> bool:
    if st.session_state.get("admin"):
        return True
    st.title("🗂️ Office Admin")
    locked_until = st.session_state.get("locked_until", 0)
    if time.time() < locked_until:
        st.error("Too many tries. Wait a few minutes and try again.")
        return False
    with st.form("login"):
        user = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        go = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if not go:
        return False
    ws = S.admins_tab()
    a = A.authenticate(S.read_admins(ws), user, pw)
    if not a:
        n = st.session_state.get("tries", 0) + 1
        st.session_state["tries"] = n
        if n >= MAX_TRIES:
            st.session_state["locked_until"] = time.time() + LOCK_SECONDS
            st.session_state["tries"] = 0
        st.error("That username and password don't match.")
        return False
    st.session_state["tries"] = 0
    st.session_state["admin"] = {"username": A.norm_username(a["Username"]),
                                 "office": a["Office Key"].strip().lower(),
                                 "name": a.get("Admin Name") or a["Username"]}
    try:
        S.set_admin_cells(ws, a["_row"], {"Last Login": S.now_str()})
    except Exception:  # noqa: BLE001 -- never block a login on the stamp
        pass
    st.rerun()
    return True


# ---------------------------------------------------------------- helpers --

def _mine(reqs, office_key, action):
    """This office's rows for one action, newest first."""
    rows = [r for r in reqs if r.get("Office Key", "").lower() == office_key
            and r.get("Action") == action]
    return sorted(rows, key=lambda r: r.get("Requested At", ""), reverse=True)


def _status_line(r) -> None:
    st_ = r.get("Status")
    when = r.get("Requested At", "")
    if st_ in C.OPEN_STATUSES:
        msg = {C.QUEUED: "Waiting for Lucy to pick it up…",
               C.WORKING: "Lucy is working on it…",
               C.AT_OFFICE: "Your office computer is sending them…"}.get(st_, st_)
        st.info("⏳ %s (pressed %s)" % (msg, when))
    elif st_ == C.DONE:
        st.success("✅ Done (pressed %s)" % when)
    elif st_ == C.FAILED:
        raw = r.get("Result") or ""
        res = S.loads(raw)
        st.error("⚠️ %s" % (res.get("error") if res else raw) or "Didn't go through.")


def _press(admin, action, details=None) -> None:
    S.add_request(S.requests_tab(), username=admin["username"],
                  office_key=admin["office"], action=action, details=details)
    st.rerun()


# ------------------------------------------------------------------ pages --

def _bgc_section(admin, reqs, ws) -> None:
    from automations.office_admin import actions, relay_client
    office = C.office(admin["office"])
    st.subheader("🛡️ Background checks")
    st.caption("Everyone marked Yes for Offer Position in today's second interviews.")
    if not relay_client.configured(office.key):
        st.warning("This computer isn't connected to your office's Lucy yet. "
                   "Ask Lucy's team to finish setting it up.")
        return

    # The office's city + state: Sterling's form needs it on every invite.
    sws = S.settings_tab()
    location = S.location_of(S.office_settings(sws, office.key))
    editing = st.session_state.get("edit_location") or not location
    if editing:
        st.markdown("**Where is your office?** (asked once)")
        with st.form("location"):
            states = list(C.US_STATES)
            pick = st.selectbox("State", ["Pick your state"] + states,
                                index=(states.index(location["state"]) + 1) if location else 0)
            city = st.text_input("City", value=location.get("city", "") if location else "")
            if st.form_submit_button("Save", type="primary"):
                try:
                    S.save_office_location(sws, office.key, pick, city, admin["username"])
                    st.session_state.pop("edit_location", None)
                    st.rerun()
                except ValueError as e:
                    st.error(str(e).capitalize() + ".")
        return
    loc_cols = st.columns([4, 1])
    loc_cols[0].caption("Office location: %s, %s" % (location["city"], location["state"]))
    if loc_cols[1].button("Change", key="chg-loc"):
        st.session_state["edit_location"] = True
        st.rerun()

    sends = _mine(reqs, office.key, C.SEND_BGC)
    last_send = sends[0] if sends else None
    if last_send and last_send.get("Status") == C.AT_OFFICE:
        last_send = actions.refresh_send(ws, last_send)
    send_open = bool(last_send and last_send.get("Status") in C.OPEN_STATUSES)

    if st.button("🔎 Find today's offers", use_container_width=True, disabled=send_open):
        with st.spinner("Reading ApplicantStream…"):
            try:
                people = actions.find_bob(office)
            except Exception as e:  # noqa: BLE001
                st.error("Couldn't read ApplicantStream (%s). Is it logged in on this computer?"
                         % type(e).__name__)
                people = None
        if people is not None:
            st.session_state["bob"] = {"people": people, "at": S.now_str()}
            try:
                actions.log_find(ws, admin, people)
            except Exception:  # noqa: BLE001 -- the record is nice to have
                pass

    found = st.session_state.get("bob")
    if found is not None:
        people = found["people"]
        if not people:
            st.write("Nobody marked Yes for Offer Position today yet.")
        else:
            st.write("Tick who should get one (read %s):" % found["at"])
            picked = []
            for i, p in enumerate(people):
                name = "%s %s" % (p.get("first_name"), p.get("last_name"))
                has_email = "@" in (p.get("email") or "")
                label = name if has_email else "%s — no email in ApplicantStream" % name
                if st.checkbox(label, value=has_email, disabled=not has_email,
                               key="p-%s-%d" % (found["at"], i)):
                    picked.append(p)
            if st.button("📨 Send background checks (%d)" % len(picked), type="primary",
                         use_container_width=True, disabled=send_open or not picked):
                try:
                    actions.send_bgc(ws, admin, office, picked, location)
                    st.session_state.pop("bob", None)
                except Exception as e:  # noqa: BLE001
                    st.error(str(e)[:300])
                st.rerun()

    if last_send:
        st.markdown("**Last send**")
        _status_line(last_send)
        res = S.loads(last_send.get("Result"))
        if res.get("would_send"):
            st.caption("Test run — nothing was sent. Would have sent: %s" % ", ".join(res["would_send"]))
        if res.get("sent"):
            st.caption("Sent: %s" % ", ".join(res["sent"]))
        if res.get("failed"):
            st.warning("Not sent — please send by hand: %s" % ", ".join(res["failed"]))
        if res.get("unconfirmed"):
            st.warning("Not sure these went out — check Sterling before sending again: %s"
                       % ", ".join(res["unconfirmed"]))
        if res.get("error") and last_send.get("Status") == C.FAILED:
            st.caption(res["error"])


def _contacts_section(admin, reqs) -> None:
    st.subheader("📇 2nd round contacts")
    st.caption("Puts this week's 2nd rounds into your office's contacts.")
    rows = _mine(reqs, admin["office"], C.ADD_CONTACTS)
    last = rows[0] if rows else None
    busy = bool(last and last.get("Status") in C.OPEN_STATUSES)
    if st.button("➕ Add 2nd round contacts", use_container_width=True, disabled=busy):
        _press(admin, C.ADD_CONTACTS)
    if last:
        _status_line(last)
        if last.get("Status") == C.DONE and last.get("Result"):
            st.caption(last["Result"])


def main() -> None:
    _setup()
    if not _login():
        return
    admin = st.session_state["admin"]
    office = C.office(admin["office"])
    top = st.columns([4, 1])
    top[0].title("🗂️ %s" % office.owner)
    if top[1].button("Sign out"):
        st.session_state.clear()
        st.rerun()
    st.caption("Signed in as %s" % admin["name"])
    if office.bgc_mode != "live":
        st.info("Test mode: background checks are checked, not sent.")
    ws = S.requests_tab()
    reqs = S.read_requests(ws)
    st.button("↻ Check again", on_click=lambda: None)
    st.divider()
    _bgc_section(admin, reqs, ws)
    st.divider()
    _contacts_section(admin, reqs)


main()
