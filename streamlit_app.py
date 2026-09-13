"""Alphalete Reporting by Lucy — every self-serve tool, one site.

Megan 2026-09-13: "I really don't want to keep creating all these apps. Can we
combine them? I think this is all going to live on 1 website eventually."

Eight separate Community Cloud deploys had grown up one at a time, each with
its own subdomain, its own copy of the same secrets and its own thing to keep
alive. This is the one door.

HOW IT AVOIDS A REWRITE. st.navigation takes a PATH to a script, so each tool
stays exactly where it is and is listed here -- `icd_signup/app.py` is the same
file it always was. Adding a tool is one line in TOOLS; nothing is copied,
nothing is refactored, and a tool can be pulled back out just as cheaply.

set_page_config IS DELIBERATELY NOT CALLED HERE. Each tool script calls its own
as its first Streamlit command, and a second call in the same run raises. The
page owns its own title and icon, which is also what keeps each tool looking
like itself.

MIGRATING THE OLD DEPLOYS IS A SEPARATE DECISION, one tool at a time. Owners
and ICDs are holding links to the existing subdomains -- a dispositions confirm
link, a pay-structure link -- and those keep working until somebody decides to
retire them. Listing a tool here does not switch the old one off.
"""
from __future__ import annotations

import streamlit as st

# (script path, url, label, icon, who it is for). Sidebar order = this order.
#
# THE URL IS SET EXPLICITLY AND THAT IS NOT OPTIONAL. Streamlit derives a
# page's url from its FILENAME, and every tool in this repo is called app.py --
# so the second one added would silently collide with the first on /app. It is
# also the half of the address an owner sees, and "alphalete.../join-lucy-eco"
# is a link somebody can be read down a phone.
TOOLS = [
    ("icd_signup/app.py", "join-lucy-eco", "Join Lucy Eco",
     ":material/rocket_launch:",
     "ICD owners — get your office's numbers posted in Slack"),
    # FOLDED IN because this site took over its subdomain (2026-09-13). Its
    # confirm view is a deep link Megan holds -- ?confirm=<key> -- so it has
    # to stay reachable, now at /daily-dispositions?confirm=<key>. Dropping
    # the tool instead would have broken that quietly.
    ("disposition_signup/app.py", "daily-dispositions", "Daily Dispositions",
     ":material/schedule:",
     "Office owners — get your knocks and dispositions board on a schedule"),
]


def home():
    st.markdown("#### Alphalete Marketing")
    st.title("Reporting tools")
    st.write("Pick the one you were sent here for.")
    st.divider()
    for path, _url, label, _icon, who in TOOLS:
        st.markdown("### %s" % label)
        st.caption(who)
        st.page_link(path, label="Open %s" % label)
        st.write("")


pages = [st.Page(home, title="Home", icon=":material/home:", default=True)]
pages += [st.Page(p, title=t, icon=i, url_path=u)
          for p, u, t, i, _who in TOOLS]

st.navigation(pages).run()
