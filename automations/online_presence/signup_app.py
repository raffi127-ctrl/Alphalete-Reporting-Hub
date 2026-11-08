"""Join LucyECO Social — an office signs up for Lucy to run its online presence.

Lucy posts the team's photos to the office's OWN pages (from the office's own
Zoho, on its own computer) and replies to its Google reviews. Everything runs
through one Slack room for the office.

The answers land as PENDING on the 'LucyECO Social Signups' tab (signup.py).
Nothing switches on from this page; we finish on the install call.

Never asks for a password.

Run locally:   .venv/bin/streamlit run automations/online_presence/signup_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from automations.online_presence import signup                  # noqa: E402
from automations.shared import onboarding_ui as ui              # noqa: E402

st.set_page_config(page_title="Join LucyECO Social", page_icon="📸")
ui.render_header("Join LucyECO Social",
                 "Lucy posts your team's photos to your pages and answers your "
                 "Google reviews. You approve everything in Slack.")

_gc, _diag = ui.build_gs_client("LUCYECO_SOCIAL_LOCAL_ONLY")
if _gc is not None:
    signup.set_client(_gc)

st.divider()
st.subheader("About you")
owner = st.text_input("Your full name")
owner_email = st.text_input("Your email", help="We send your setup details here.")

st.subheader("Your business, exactly as customers see it")
st.caption("Lucy checks Google, your website, Indeed and Glassdoor against these "
           "and tells you when something doesn't match.")
business = st.text_input("Business name (exactly as it shows on Google)")
address = st.text_input("Office address", placeholder="100 Main St, Suite 200, Dallas, TX 75201")
phone = st.text_input("Company phone", placeholder="(214) 555-0100")
website = st.text_input("Company website", placeholder="yourcompany.com")
google_link = st.text_input(
    "Your Google listing link",
    help="Search your business on Google Maps → tap Share → Copy link, then paste it here.")
indeed = st.text_input("Your Indeed company page (if you have one)", placeholder="optional")
glassdoor = st.text_input("Your Glassdoor page (if you have one)", placeholder="optional")

st.subheader("Where should Lucy post?")
st.caption("Tick each page Lucy should post your photos to, and paste the link to "
           "that page. Lucy only posts to these, and only messages you if one of "
           "them gets disconnected.")
# ONE QUESTION PER PAGE (Megan 2026-11-08): tick it, and its link box opens
# right under it. Not st.form, so the box can appear the moment it's ticked.
pages, socials = [], {}
for page in signup.PAGES:
    if not st.checkbox(page, key=f"page_{page}"):
        continue
    pages.append(page)
    if page == "Google":
        st.caption("↳ Uses your Google listing link above.")
        continue
    field, hosts, _ = next(f for f in signup.SOCIAL_FIELDS if f[2] == page)
    host0 = hosts if isinstance(hosts, str) else hosts[0]
    socials[field] = st.text_input(f"Your {page} page link", key=f"link_{page}",
                                   placeholder=f"{host0}/yourpage")

st.subheader("Approvals")
approvers = st.text_input("Who can approve posts and review replies?",
                          placeholder="Names, separated by commas")
complaints = st.text_input(
    "Email for customer concerns",
    help="When someone leaves an unhappy Google review, Lucy's reply invites "
         "them to write here.")
tz = st.selectbox("Your timezone", ["America/Chicago", "America/New_York",
                                    "America/Denver", "America/Phoenix",
                                    "America/Los_Angeles"],
                  format_func=lambda z: {"America/Chicago": "Central",
                                         "America/New_York": "Eastern",
                                         "America/Denver": "Mountain",
                                         "America/Phoenix": "Arizona",
                                         "America/Los_Angeles": "Pacific"}[z])
notes = st.text_area("Anything we should know?", placeholder="optional")

answers = {"Owner": owner, "Owner Email": owner_email, "Business Name": business,
           "Address": address, "Phone": phone, "Website": website,
           "Google Listing Link": google_link, "Indeed Link": indeed,
           "Glassdoor Link": glassdoor, "Pages": list(pages), "Approvers": approvers,
           "Complaints Email": complaints, "Timezone": tz, "Notes": notes, **socials}

st.divider()
if st.button("Send my sign-up", type="primary"):
    probs = signup.problems(answers)
    if probs:
        for p in probs:
            st.error(p)
    else:
        saved = signup.submit(signup.tidy(answers))
        if saved:
            st.success("Got it! We'll reach out to set up a quick call. On the call we'll "
                       "make your Zoho Social account together, connect your pages, and "
                       "link your Google listing. Have your card and your social logins handy.")
        else:
            st.warning("We couldn't save that just now. Please try again in a minute, "
                       "or text us your answers.")
