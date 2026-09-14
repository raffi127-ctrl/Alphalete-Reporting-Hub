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

# (script path, url, label, icon, who it is for, LISTED).
#
# THE URL IS SET EXPLICITLY AND THAT IS NOT OPTIONAL. Streamlit derives a
# page's url from its FILENAME, and every tool in this repo is called app.py --
# so the second one added would silently collide with the first on /app. It is
# also the half of the address an owner sees, and "lucyeco.../join-lucy-eco"
# is a link somebody can be read down a phone.
#
# LISTED=False MEANS REACHABLE BUT NOT OFFERED. Daily Dispositions is the thing
# Lucy Eco replaces -- knocks and dispositions are moving onto the ICDs' own
# machines -- so putting the two side by side on the front page invites an
# office to pick the one we are retiring (Megan 2026-09-13: "this shouldn't
# offer 2 different things?"). It still has to EXIST: its ?confirm=<key> deep
# link is how a sign-up already in flight gets approved, and deleting the page
# would break that silently. So it keeps its url and loses its billing.
TOOLS = [
    ("icd_signup/app.py", "join-lucy-eco", "Join Lucy ECOsystem",
     ":material/rocket_launch:",
     "ICD owners — get your office's numbers posted in Slack", True),
    # LINK ONLY, and behind an access code (see icd_sales_board/gate.py). The
    # board carries every rep's name and daily production for every office, so
    # it is not something to offer from a front page an ICD can wander onto —
    # it is a link you send to an owner.
    ("automations/icd_sales_board/site.py", "sales-board", "Sales board",
     ":material/leaderboard:",
     "Owners — your office's board, by code", False),
    ("disposition_signup/app.py", "daily-dispositions", "Daily Dispositions",
     ":material/schedule:",
     "Being replaced by Lucy ECOsystem — reachable by link only", False),
]


def home():
    st.markdown("#### Alphalete Marketing")
    st.title("Reporting tools")
    st.write("Pick the one you were sent here for.")
    st.divider()
    for path, _url, label, _icon, who, listed in TOOLS:
        if not listed:
            continue
        st.markdown("### %s" % label)
        st.caption(who)
        st.page_link(path, label="Open %s" % label)
        st.write("")


pages = [st.Page(home, title="Home", icon=":material/home:", default=True)]
pages += [st.Page(p, title=t, icon=i, url_path=u)
          for p, u, t, i, _who, _listed in TOOLS]

# EVERY page is registered -- that is what keeps an unlisted tool's url alive --
# but the sidebar is hidden, because a sidebar is a list of offers and the
# unlisted ones are not on offer. Somebody who was sent a direct link lands
# exactly where they were sent; nobody browses into a tool they should not be
# picking.
st.navigation(pages, position="hidden").run()
