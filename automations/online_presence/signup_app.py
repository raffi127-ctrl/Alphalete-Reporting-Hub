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

# Megan's "where's the Channel ID" screenshot, shared with the other forms.
SLACK_ID_IMG = (Path(__file__).resolve().parents[2] / "tracker_onboarding"
                / "slack_id_help.png")

st.set_page_config(page_title="Join LucyECO Social", page_icon="📸")
ui.render_header("Join LucyECO Social",
                 "Lucy posts your team's photos to your pages and answers your "
                 "Google reviews. You approve everything in Slack.")

_gc, _diag = ui.build_gs_client("LUCYECO_SOCIAL_LOCAL_ONLY")
if _gc is not None:
    signup.set_client(_gc)

st.divider()
# Every launch starts with the company name: Lucy makes the logo options from
# it, and the site + socials are built from the logo they pick (Megan 2026-11-12).
st.subheader("Your company name")
business = st.text_input("Business name (exactly as it shows on Google)",
                         help="Lucy makes your logo options from this, then builds your "
                              "website and social pages from the logo you pick.")
st.subheader("About you")
owner = st.text_input("Your full name")
owner_email = st.text_input("Your email", help="We send your setup details here.")

st.subheader("Your business, exactly as customers see it")
st.caption("Lucy checks Google, your website, Indeed and Glassdoor against these "
           "and tells you when something doesn't match.")
address = st.text_input("Office address", placeholder="100 Main St, Suite 200, Dallas, TX 75201")
phone = st.text_input("Company phone", placeholder="(214) 555-0100")
need_site = st.radio("Do you have a website?",
                     ["Yes, I have one", "No, build one for me"], index=None, key="need_site")
website = ""
if need_site == "Yes, I have one":
    website = st.text_input("Company website", placeholder="yourcompany.com")
elif need_site:
    st.caption("We'll build your recruiting website, set up your company email "
               "(like careers@yourcompany.com) and keep both running. A few questions "
               "below make your site sound like YOUR team.")
google_link = st.text_input(
    "Your Google listing link",
    help="Search your business on Google Maps → tap Share → Copy link, then paste it here.")
indeed = st.text_input("Your Indeed company page (if you have one)", placeholder="optional")
glassdoor = st.text_input("Your Glassdoor page (if you have one)", placeholder="optional")

site = {}
if need_site == "No, build one for me":
    st.subheader("Your website")
    site["Website Name Ideas"] = st.text_input(
        "What should your website be called?",
        placeholder="e.g. palaceacquisitions.com, palacesales.com",
        help="Give one or two ideas. We check which are free and register it for you.")
    site["Campaign"] = st.selectbox("What does your team sell?", list(signup.CAMPAIGNS), index=None,
                                    placeholder="Pick one")
    site["Areas Served"] = st.text_input("Which cities do you work in?",
                                         placeholder="Dallas, Irving, Arlington")
    st.markdown("**In your own words** (a sentence or two each, this becomes your site)")
    site["Story Started"] = st.text_area("How did your office start?")
    site["Story Different"] = st.text_area("What makes your team different?")
    site["Story Culture"] = st.text_area("What's the culture like? (team nights, wins, trips…)",
                                         placeholder="optional")
    site["Site Look"] = st.radio("Pick a look for your site", list(signup.LOOKS), index=4,
                                 key="site_look")
    if st.checkbox("I have a brand color", key="has_color"):
        site["Brand Color"] = st.color_picker("Your brand color", "#C8A24B")
    site["Apply Link"] = st.text_input(
        "Your job application link (if you have one)", placeholder="optional",
        help="Your ApplicantStream or Indeed apply link. Without one, the Apply button "
             "goes to your company email.")
    st.info("📸 After you sign up, we'll ask for **10–15 photos** in your Slack channel: "
            "team shots, the office, wins, team nights. They launch your website AND your "
            "social pages.")

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

st.subheader("Your Slack channel")
st.caption("Lucy puts your photos, captions and review replies for approval in one "
           "Slack channel.")
has_room = st.radio(
    "Do you already have a Slack channel for your social media / branding?",
    ["Yes, I have one", "No, please create one for me"], index=None, key="has_room")
slack_channel = ""
if has_room == "Yes, I have one":
    slack_channel = ui.channel_id_input("Paste that channel's Channel ID", key="slack_channel")
    ui.channel_id_help_expander(SLACK_ID_IMG)
    st.caption("Add **Lucy Reporting** to that channel so she can post there.")
elif has_room:
    st.caption("No problem: once you send this, Lucy makes a private channel for you "
               "(your company name + \"-lucyeco-social\", like #palace-acquisitions-lucyeco-social) and adds you to it.")

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
           "Complaints Email": complaints, "Timezone": tz, "Notes": notes,
           "Slack Room": {"Yes, I have one": "existing",
                          "No, please create one for me": "create us one"}.get(has_room or "", ""),
           "Slack Channel": slack_channel, **socials,
           "Need Website": need_site or "", **site}

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
