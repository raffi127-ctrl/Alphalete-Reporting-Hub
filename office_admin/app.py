"""Office Admin -- one login per office admin, one job: background checks.

  * Send background checks   today's 2nd interviews offered the position, on THIS
                             computer, sent from the office's ECO computer
                             (the one holding the Sterling login)

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

def _bob_section(admin) -> None:
    """"I've made today's BOB calls" -- the press that releases the update.

    Megan, 2026-11-24: "there should be some button that says, I've made the
    brought on board calls for today, after they've already marked them in
    applicant stream and scheduled them. And that will trigger the daily update
    being ran."

    IT IS A STATEMENT, NOT A SEND. Pressing it records the day; the office's
    own daily update run is what posts, and it may be minutes later. A button
    that posted directly would mean one mis-press sends the office its day's
    record with the answers still missing -- which is the thing the gate exists
    to stop, so the button must not be the way round it.
    """
    from automations.office_admin import bob_calls as BOB
    office = C.office(admin["office"])
    st.subheader("📞 Brought-on-board calls")
    try:
        already = BOB.done(office.key)
    except Exception as e:                      # noqa: BLE001
        st.warning("Could not check today's calls (%s). Try ↻ Check again."
                   % type(e).__name__)
        return
    if already:
        st.success("Today's calls are marked done. Your daily update can post.")
        return
    st.caption("Mark this once the calls are made AND everyone is marked and "
               "scheduled in ApplicantStream. Your daily update waits for it, "
               "so it is never posted with the answers missing.")
    if st.button("✅ I've made today's BOB calls", type="primary",
                 use_container_width=True):
        try:
            BOB.mark(office.key, by=admin.get("name") or admin["username"])
        except Exception as e:                  # noqa: BLE001
            st.error("That did not save (%s) — press it again." % type(e).__name__)
            return
        st.rerun()


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
    # Big and coloured (Megan 11/04: the grey caption was too easy to miss) --
    # every invite goes out with this location, so it must be seen.
    import html as _html
    loc_cols[0].markdown(
        '<div style="background:#E8F1FB;border-left:6px solid #1F6FB2;border-radius:6px;'
        'padding:10px 14px;margin-bottom:10px;font-size:1.25rem;font-weight:600;color:#123E66;">'
        '📍 Office location: %s, %s</div>'
        % (_html.escape(location["city"]), _html.escape(location["state"])),
        unsafe_allow_html=True)
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
            from automations.office_admin import already
            people = already.check(people, reqs, office.key)
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
                done = p.get("already") or ""
                label = ("%s — %s" % (name, done) if done else name) if has_email \
                    else "%s — no email in ApplicantStream" % name
                # Already done = shown, UNticked, still tickable (Megan 11/04).
                if st.checkbox(label, value=has_email and not done, disabled=not has_email,
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


def _drug_section(admin, reqs, ws) -> None:
    """The week-3 drug test.

    Rafael Hidalgo, 2026-11-24, asked whether it could ride along on the
    background-check press: "If we send the drug test with the background
    check, it'll cause confusion, it'll need resent because the applicant
    won't find it / if they're new and they take it, the owner gets charged
    more money. we like doing the drug test on WK3 of starting / so I think a
    button to send it would be great."

    So it is its own button, showing its own week. The shape is deliberately
    the background check's -- read, tick, send -- because it is the same job
    done to a different list, and an admin who can do one should not have to
    learn a second way.
    """
    from automations.office_admin import actions, relay_client, wk3
    office = C.office(admin["office"])
    st.subheader("🧪 Drug tests — week 3")
    if not relay_client.configured(office.key):
        st.warning("This computer isn't connected to your office's Lucy yet. "
                   "Ask Lucy's team to finish setting it up.")
        return

    # The week is DERIVED, never typed. Megan's rule is one input per concept
    # and the obvious default -- and "which Sunday was two weeks ago" is
    # exactly the arithmetic a person should not be asked to do at 8am.
    start = wk3.start_week_for(_dt.date.today())
    # "%b %-d" is Mac-only and this page runs on Windows too, so the day is
    # built from .day rather than a strftime directive.
    when = "%s %d" % (start.strftime("%b"), start.day)
    st.caption("Everyone who started training the week of %s — they're in "
               "their third week now." % when)

    sws = S.settings_tab()
    location = S.location_of(S.office_settings(sws, office.key))
    if not location:
        st.info("Set your office's city and state in Background checks first — "
                "Sterling needs it on every order.")
        return

    sends = _mine(reqs, office.key, C.SEND_DRUG)
    last_send = sends[0] if sends else None
    if last_send and last_send.get("Status") == C.AT_OFFICE:
        last_send = actions.refresh_send(ws, last_send)
    send_open = bool(last_send and last_send.get("Status") in C.OPEN_STATUSES)

    if st.button("🔎 Find week 3", use_container_width=True, disabled=send_open,
                 key="drug-find"):
        with st.spinner("Reading ApplicantStream…"):
            try:
                people = actions.find_drug(office)
            except Exception as e:  # noqa: BLE001
                st.error("Couldn't read ApplicantStream (%s). Is it logged in "
                         "on this computer?" % type(e).__name__)
                people = None
        if people is not None:
            st.session_state["wk3"] = {"people": people, "at": S.now_str()}
            try:
                actions.log_find_drug(ws, admin, people)
            except Exception:  # noqa: BLE001 -- the record is nice to have
                pass

    found = st.session_state.get("wk3")
    if found is not None:
        people = found["people"]
        if not people:
            st.write("Nobody started training that week.")
        else:
            # WHO IS STILL HERE IS PRE-ANSWERED. Megan, 2026-11-25: "it's
            # likely a lot that were onboarded won't still be active reps".
            # Anybody the board has taken off starts UNTICKED with the reason
            # beside them, so the admin confirms a short list instead of
            # remembering twenty-two names. An order for somebody who left is
            # billed to the owner exactly like a real one.
            err = next((q.get("board_error") for q in people if q.get("board_error")), "")
            if err:
                st.warning("Couldn't read the onboarding board (%s), so nobody "
                           "is ticked for you — check each name yourself "
                           "before sending." % err)
            left = sum(1 for q in people if q.get("gone"))
            if left:
                st.caption("%d of these %d are off the board already — "
                           "unticked below." % (left, len(people)))
            st.write("Tick who should get a drug test (read %s):" % found["at"])
            picked = []
            for i, p in enumerate(people):
                name = "%s %s" % (p.get("first_name"), p.get("last_name"))
                has_email = "@" in (p.get("email") or "")
                why = p.get("gone") or ""
                if not has_email:
                    label = "%s — no email in ApplicantStream" % name
                elif why:
                    label = "%s — %s" % (name, why)
                else:
                    label = name
                # A board we could not read pre-ticks NOBODY: ticking on a
                # failed read is how a whole cohort gets ordered by accident.
                on = has_email and not why and not err
                if st.checkbox(label, value=on, disabled=not has_email,
                               key="d-%s-%d" % (found["at"], i)):
                    picked.append(p)
            if st.button("🧪 Send drug tests (%d)" % len(picked), type="primary",
                         use_container_width=True,
                         disabled=send_open or not picked, key="drug-send"):
                try:
                    actions.send_drug(ws, admin, office, picked, location)
                    st.session_state.pop("wk3", None)
                except Exception as e:  # noqa: BLE001
                    st.error(str(e)[:300])
                st.rerun()

    if last_send:
        st.markdown("**Last send**")
        _status_line(last_send)
        res = S.loads(last_send.get("Result"))
        if res.get("would_send"):
            st.caption("Test run — nothing was sent. Would have sent: %s"
                       % ", ".join(res["would_send"]))
        if res.get("sent"):
            st.caption("Sent: %s" % ", ".join(res["sent"]))
        if res.get("failed"):
            st.warning("Not sent — please send by hand: %s" % ", ".join(res["failed"]))
        if res.get("unconfirmed"):
            st.warning("Not sure these went out — check Sterling before "
                       "sending again: %s" % ", ".join(res["unconfirmed"]))
        if res.get("error") and last_send.get("Status") == C.FAILED:
            st.caption(res["error"])


def _apex_section(admin, reqs, ws) -> None:
    """New starts -> Apex, in two presses: look up, then send.

    THE POP-UP IS THE WHOLE POINT. Megan, 2026-11-24: "when someone pushes
    the button to send to apex - we should pop up the names and gender we
    assume - then the admin/icd sending can change if they want before
    hitting send." Gender is guessed from the first name, and the guesser
    deliberately leaves a name it will not call BLANK rather than flip a
    coin onto a payroll record -- so the blanks are what this list is for.

    AND NOTHING IS TYPED IN APEX AFTERWARDS (Megan, same day: "no, I
    shouldn't have to fill anything on apex"). Whatever is confirmed here
    is typed with every other value when the job runs.
    """
    import datetime as _dt
    from automations.office_admin import actions, relay_client
    office = C.office(admin["office"])
    st.subheader("🧾 New starts → Apex")
    mode = (office.apex_mode or "off")
    if mode == "off":
        st.caption("Not switched on for your office yet.")
        return
    if not relay_client.configured(office.key):
        st.warning("This computer isn't connected to your office's Lucy yet. "
                   "Ask Lucy's team to finish setting it up.")
        return
    st.caption("Everyone who started training this week, onto payroll. "
               "You'll see the list before anything is sent.")

    # THE WEEK, AS THE BOARD COUNTS IT -- Sunday to Saturday, the same
    # week_start every other onboarding step uses, so "this week" means one
    # thing across the whole system.
    from automations.icd_onboarding import board as _B
    this_week = _B.week_start_of(_dt.date.today())
    week = st.date_input("Week starting", value=this_week, key="apex-week")

    looks = _mine(reqs, office.key, C.APEX_LOOK)
    last_look = looks[0] if looks else None
    if last_look and last_look.get("Status") == C.AT_OFFICE:
        last_look = actions.refresh_send(ws, last_look)
    sends = _mine(reqs, office.key, C.APEX_SEND)
    last_send = sends[0] if sends else None
    if last_send and last_send.get("Status") == C.AT_OFFICE:
        last_send = actions.refresh_send(ws, last_send)
    busy = bool(last_send and last_send.get("Status") in C.OPEN_STATUSES)
    looking = bool(last_look and last_look.get("Status") in C.OPEN_STATUSES)

    if st.button("🔎 Look up this week's new starts", use_container_width=True,
                 disabled=busy or looking):
        try:
            actions.apex_look(ws, admin, office, week)
        except Exception as e:  # noqa: BLE001
            st.error(str(e)[:300])
        st.rerun()

    if looking:
        st.info("Reading your office's calendar… press R to refresh.")
        return

    people = []
    if last_look:
        res = S.loads(last_look.get("Result"))
        people = list(res.get("people") or [])
        if res.get("error"):
            st.error(res["error"][:400])

    if not people:
        if last_look and last_look.get("Status") == C.DONE:
            st.write("Nobody started training that week.")
        return

    st.markdown("**Check the gender on each one, then send.**")
    st.caption("Guessed from the first name. A name we won't guess is blank "
               "— those are the ones to look at.")
    said = {}
    unknown = 0
    for i, p in enumerate(people):
        name = str(p.get("name") or "")
        was = str(p.get("gender") or "")
        where = str(p.get("from") or "")
        cols = st.columns([3, 2])
        label = name if where != "unknown" else "%s — needs a gender" % name
        cols[0].markdown(("**%s**" % label) if where == "unknown" else label)
        pick = cols[1].selectbox(
            "Gender for %s" % name, ["", "Male", "Female"],
            index=(["", "Male", "Female"].index(was) if was in ("Male", "Female") else 0),
            key="apex-g-%d" % i, label_visibility="collapsed")
        if pick:
            said[name] = pick
        else:
            unknown += 1

    if unknown:
        st.warning("%d still need a gender. Apex won't take a record without "
                   "one, so they'd be held back." % unknown)
    if st.button("📤 Send %d to Apex" % len(said), type="primary",
                 use_container_width=True,
                 disabled=busy or bool(unknown) or not said):
        try:
            actions.apex_send(ws, admin, office, week, said)
        except Exception as e:  # noqa: BLE001
            st.error(str(e)[:300])
        st.rerun()

    if last_send:
        st.markdown("**Last send**")
        _status_line(last_send)
        res = S.loads(last_send.get("Result"))
        if res.get("added"):
            st.caption("Added: %s" % ", ".join(res["added"]))
        for b in res.get("needs_hand") or []:
            st.warning("%s — %s" % (b.get("name", "?"), b.get("why", "")))
        if res.get("error"):
            st.caption(res["error"][:300])


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
    _bob_section(admin)
    _apex_section(admin, reqs, ws)
    st.divider()
    _drug_section(admin, reqs, ws)


main()
