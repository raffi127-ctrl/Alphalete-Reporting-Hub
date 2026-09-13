"""Alphalete Reporting by Lucy — join Lucy Eco (ICD self-serve sign-up).

Megan 2026-09-13: "they should be 'signing' up first and then I'm alerted."
Before this, enrolling an office started with US -- someone typed them into the
roster, minted a key and sent a link, then collected their hours and their
OwnerVille name over Slack afterwards. This asks the office once, up front, and
turns the request into a real office only when Megan approves it.

WHAT THIS FORM NEVER ASKS FOR: a password. The whole design rests on the
SaraPlus login staying on their own laptop, and a sign-up page that asked for
one would quietly undo that -- so the login is collected by the installer, on
their machine, and travels nowhere.

Their answers land on the 'ICD Signup' tab of the relay workbook as PENDING and
ping Megan in the corrections channel. NOTHING is created until she runs
`python -m automations.icd_signup.approve <office>` -- no key, no roster entry,
no push -- so an abandoned form leaves nothing behind.

Run locally:   .venv/bin/streamlit run icd_signup/app.py
On the web:    Streamlit Community Cloud.

Secrets: [gcp_service_account]/[gcp_oauth] for the relay workbook and
`slack_user_token` (TOP-LEVEL) for the ping. Without Sheets creds it saves a
local draft. ICD_SIGNUP_LOCAL_ONLY=1 forces that.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automations.icd_signup import schema as S, store          # noqa: E402
from automations.shared import onboarding_ui as ui             # noqa: E402

st.set_page_config(page_title="Join Lucy Eco", page_icon="🛰️")
ui.render_header(
    "Get your office's sales and credit checks in Slack",
    "Lucy watches your own SaraPlus and OwnerVille and posts to your team's "
    "channel. It runs on one computer in your office.")

ui.inject_slack_token()

st.markdown(
    "**What you are signing up for.** A small program runs on one Mac or PC in "
    "your office. It reads *your* SaraPlus and OwnerVille with *your* logins "
    "and sends us the numbers — credit checks, sales and knocks — so they can "
    "be posted in your team's Slack channel through the day.\n\n"
    "**Your passwords stay on your computer.** They are typed into the "
    "installer on that machine and never leave it. We never see them, and "
    "this form will never ask for one.")
st.divider()

with st.form("icd_signup"):
    st.subheader("Who you are")
    owner = st.text_input("Your full name",
                          placeholder="e.g. Cyrus Wade")
    contact = st.text_input(
        "Email or phone we can send your setup link to",
        help="The link is yours alone — it carries your office's code.")
    ov_name = st.text_input(
        "How your name is spelled in OwnerVille",
        placeholder="Leave blank if it is the same as above",
        help="OwnerVille often spells names differently, and we would rather "
             "ask than guess.")

    st.subheader("The computer it will run on")
    platform = st.radio("Is it a Mac or a Windows PC?",
                        options=["mac", "windows"],
                        format_func=lambda p: "Mac" if p == "mac" else "Windows PC",
                        horizontal=True)
    st.caption("It needs to stay on and plugged in during selling hours. "
               "A laptop that goes to sleep just means late numbers, not lost "
               "ones.")

    st.subheader("Your selling hours")
    st.caption("Nothing posts outside these — this is how Lucy knows your reps "
               "are actually out.")
    tz = st.selectbox("Your timezone", options=list(S.TIMEZONES),
                      format_func=lambda t: t.split("/")[-1].replace("_", " "))
    c1, c2 = st.columns(2)
    day_start = c1.text_input("Monday–Friday, start", value="13:30")
    day_end = c2.text_input("Monday–Friday, end", value="20:30")
    saturday = st.checkbox("We sell on Saturdays too", value=True)
    c3, c4 = st.columns(2)
    sat_start = c3.text_input("Saturday, start", value="10:45")
    sat_end = c4.text_input("Saturday, end", value="17:00")

    st.subheader("Your knocks and dispositions board")
    cadence = st.radio(
        "How often should the board post?",
        options=[c[0] for c in S.KNOCKS_CHOICES],
        format_func=lambda v: dict(S.KNOCKS_CHOICES)[v],
        index=1)

    st.subheader("Where it should post")
    wanted = st.text_input(
        "Which Slack channel(s)?",
        placeholder="e.g. #palace-sales",
        help="A name is fine. Nothing posts anywhere until someone on the "
             "reporting team approves it.")

    submitted = st.form_submit_button("Send my sign-up", type="primary")

if submitted:
    rec = S.IcdSignup(
        owner=owner, office_label="", platform=platform, timezone=tz,
        day_start=day_start.strip(), day_end=day_end.strip(),
        saturday=bool(saturday),
        sat_start=sat_start.strip(), sat_end=sat_end.strip(),
        ov_name=ov_name.strip(), knocks_cadence=int(cadence),
        wanted_channels=wanted.strip(), contact=contact.strip())
    problems = rec.problems()
    if problems:
        for p in problems:
            st.error(p)
    else:
        saved = store.submit(rec)
        try:
            from automations.icd_signup import request_notify
            request_notify.notify(saved, send=True, log=lambda *a, **k: None)
        except Exception:  # noqa: BLE001 — their sign-up is already saved
            pass
        st.success(
            "Thanks %s — that is in." % (owner.split()[0] if owner else "you"))
        st.markdown(
            "The reporting team has been told. They will send you a **setup "
            "link** for your office — one line you paste into your computer, "
            "and it asks you the rest.\n\n"
            "Nothing happens on your side until then, and nothing posts in "
            "any channel until someone approves it.")
