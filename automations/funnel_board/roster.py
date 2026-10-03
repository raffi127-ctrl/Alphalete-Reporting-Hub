"""Carlos's captainship — one list, read by both run.py and build.py.

The Funnel Board proper covers the 17 offices of the Alphalete org. This is a
different cut of the same data: Carlos's own office plus the twelve people who
report to him as a captain. They overlap (Carlos and Atef are on both) and
neither is a subset of the other — most of the captainship sits outside the org
board entirely.

Three fields, and each one is load-bearing:

    name   The label on the Captainship Board, the key written into Daily Log's
           Manager column, AND the tab name the ad-budget box reaches with
           INDIRECT. All three have to agree, so this is the AppStream/tab
           spelling rather than however the name gets said out loud (Carlos says
           "James Garay", "George Hippolito", "Kenzie Gutner", "Dhey Patel";
           AppStream and the workbook tabs say Jamis / Hipolito / Kinsey
           Guenther / Dhyey Patel).
    oid    AppStream office id, or None for someone who has no office yet.
    owner  What AppStream's own office switcher calls them — the switcher lists
           people under their legal name often enough that matching on `name`
           alone would miss them.

PENDING OFFICES (oid None). Nobody is pending as of 2026-08-19: Jeff Starr
(15031), Vincent Smith (23318) and Dhyey Patel (22767) were sales-only when this
list was first written and their offices appeared the next morning — read
straight off the switcher and typed in here. The machinery stays, because the
next person added will be in the same position: run.py re-checks the office
switcher by owner name on every hourly pass, resolves a name only when exactly
ONE office matches it, and starts pulling the moment one appears. Ids found that
way are remembered in state/resolved_offices.json.

FIRST PULL. Anyone with no rows in the Daily Log yet — freshly discovered OR
freshly typed into this list — gets a deep pull the first time, so their Trend
opens with a shape instead of a single column.
"""

# The Alphalete org's own 17 — the Manager Board / Trend / Matrix roster, and
# the list run.py pulls first. It lives here rather than in run.py so build.py
# can read it too WITHOUT importing run (which drags in the browser stack): the
# org board has to be the 17, not "whoever happens to be in the Daily Log", or
# the captainship people appear on it the moment they are first pulled. That is
# exactly what happened on 2026-08-19.
ORG = [
    ("Atef Choudhury",    "23467", "Atef Choudhury"),
    ("Aya Al-Khafaji",    "22992", "Aya Al-Khafaji"),
    ("Carlos Hidalgo",    "11580", "CARLOS HIDALGO"),
    ("Cody Cannon",       "21151", "Cody Cannon"),
    ("Colten Wright",    "",      "Colten Wright"),          # South Shore (Carlos 2026-09-14)
    ("Cyrus Wade",        "22815", "Cyrus Wade"),
    ("Drew Tepper",       "22583", "Drew Tepper"),
    ("Eveliz Wright",    "",      "Eveliz Wright"),          # South Shore
    ("Frank Matos",      "",      "Frank Matos"),            # South Shore
    ("George Delgado",   "",      "George Delgado"),         # South Shore
    ("Haytham Nagi",      "22524", "Haytham Nagi"),
    ("Isaiah Revelle",    "19717", "Isaiah Revelle"),
    ("Jacob Dover",       "23607", "Jacob Dover"),
    ("Jairo Ruiz",       "",      "Jairo Ruiz"),             # South Shore
    ("Jose Velasquez",   "",      "Jose Velasquez"),         # South Shore
    ("Joseph Delgado",   "",      "Joseph Delgado"),         # South Shore
    ("Justin Fermin",    "",      "Justin Fermin"),          # South Shore
    ("Karrington Moody", "",      "Karrington Moody"),       # South Shore
    ("Kash Rai",          "22177", "Akashdeep Rai"),
    ("Khalil Mansour",    "11901", "KHALIL MANSOUR"),
    ("Lizette Ruiz",     "",      "Lizette Ruiz-Conejo"),    # South Shore — legal name has the -Conejo
    ("Marcos Barbosa",   "",      "Marcos Barbosa"),         # South Shore
    ("Maxamad-Amin Aden", "23066", "Maxamad Aden"),
    ("Rafael Hidalgo",    "11280", "Rafael Hidalgo"),
    ("Rashad Reed",       "23411", "Rashad Reed"),
    ("Roshan Amin",       "19833", "Roshan Amin Ahmad"),
    ("Ryan McSpadden",    "22820", "Ryan McSpadden"),
    ("Salik Mallick",     "21328", "Muhammad UI Haque"),
    ("Valeria Tristan",  "",      "Valeria Tristan"),        # South Shore
]

ORG_NAMES = [n for n, _, _ in ORG]

# Colten Wright's org — the "South Shore" GROUP on the Recruiting Dashboard
# (Carlos 2026-09-14). Every one of these is ALSO in ORG above (org views,
# Goals, Focus, Source Report, Ad Sales Board, Manager Matrix all treat them
# as org people); the dashboard's group picker is the only place this list
# shows as its own roster. Drew Tepper is the one exception in the other
# direction: he stays in ORG for data, but the DASHBOARD shows him under
# South Shore instead of Org (see build.py _BOARD_ORG).
SOUTH_SHORE_NAMES = [
    "Colten Wright",
    "Jairo Ruiz",
    "Frank Matos",
    "Joseph Delgado",
    "Drew Tepper",
    "Eveliz Wright",
    "Karrington Moody",
    "Justin Fermin",
    "Jose Velasquez",
    "George Delgado",
    "Lizette Ruiz",
    "Valeria Tristan",
    "Marcos Barbosa",
]

# THE CAPTAINSHIP LEFT THIS BOOK (Carlos 2026-10-02). The 15 captainship-only
# owners now report in their own workbook, the SCI Recruiting Dashboard
# (1aWWdtMtv1ivZa8fv10cbEzJJUNrO7h9YA8fVvfiRqlg) — their roster lives in
# deploy/sci-roster.json as that book's ORG, fed to the same three modules via
# the RECRUITING_ROSTER_JSON override below (each deploy wrapper runs an SCI
# pass after the Alphalete one). Carlos and Atef were in both rosters and stay
# org-only here, per the split rule: in both -> org wins. This list is EMPTY on
# purpose so every Alphalete-default run drops the Captainship group everywhere
# (pickers, Goals box, Source Report, Ad Sales) with no env needed.
#
# Hard-won office-id notes preserved from the old list (now in sci-roster.json):
#   Jackie LeRoy 22358 — NOT in office-mapping-carlos.json (has her sales-only);
#     id came from her own Indeed tracker tab's Office ID column.
#   Joshua Murphy 21770 — TWO offices answer to his name (21770 Leadsphere,
#     10707 Zealous United); Carlos confirmed 21770 (2026-08-19). Discovery
#     would have resolved neither, by design.
#   Sabrina Alicea 21291 — from switcher discovery 2026-08-26; Tableau owner
#     string "SABRINA ALICEA [alisei, inc.]".
#   Nicolas Lujan "" — office still unknown; blank oid = run.py discovery pins
#     it from the AppStream picker on an SCI funnel run and backfills history.
CAPTAINSHIP = []

CAPTAINSHIP_NAMES = [n for n, _, _ in CAPTAINSHIP]

# Campaign-only people: on the Focus Report picker (their campaign block from
# the Campaign Log renders below the funnel) but NOT in the org — they have no
# AppStream office being pulled, no Goals row, no Recruiting Dashboard /
# Matrix presence. Their funnel rows legitimately read zero. Carlos's Tuesday
# 1:1 crew in limbo (2026-08-23): MJ and Akib, parked on Retail.
CAMPAIGN_ONLY = ["MJ Malhas", "Akib Chowdhury"]

# Indeed ad tracker tabs that actually exist in the workbook today, for the
# Captain Ship Ad View dropdown. A name here must match a tab EXACTLY —
# INDIRECT does a literal string match, and a trailing space in a tab name
# breaks the view while looking perfectly fine in the tab bar.
AD_TABS = ["Atef Choudhury", "Jackie LeRoy", "Jamis Garay",
           "Justin Wood", "Noah Dubale"]

BOARD_TITLE = "Captainship Recruiting Dashboard"
TREND_TITLE = "Captainship Focus Report"
AD_VIEW_TITLE = "Captain Ship Ad View"

# What the FIRST (everyone) group is called in the pickers. "Org" here;
# the SCI book overrides it to "Owners" (Carlos 2026-10-03). Formulas only
# ever compare against the OTHER labels ("Captainship", a captain's name),
# so the first group's label is pure display and safe to rename per book.
ORG_LABEL = "Org"

# The Recruiting Dashboard GROUP picker, generalized (Carlos 2026-10-03:
# "see all of the owners at once... then add captains; view just their
# captainship"). Ordered (label, members) pairs; the FIRST entry is the
# default view and the coercion fallback. Drew Tepper's dashboard-only move
# to South Shore (2026-09-14) lives here now: he stays in ORG for data and
# every other view.
BOARD_GROUPS = [(ORG_LABEL, [n for n in ORG_NAMES if n != "Drew Tepper"])]
if CAPTAINSHIP_NAMES:
    BOARD_GROUPS.append(("Captainship", CAPTAINSHIP_NAMES))
if SOUTH_SHORE_NAMES:
    BOARD_GROUPS.append(("South Shore", SOUTH_SHORE_NAMES))


# ---------------------------------------------------------------------------
# STANDALONE / MANAGER-KIT OVERRIDE (2026-09-21). When RECRUITING_ROSTER_JSON
# names a JSON file ({"org": [[display name, office id or "", appstream owner
# spelling], ...], "captainship": [...], "south_shore": [...]}), every roster
# above is REPLACED by it — that is how a new manager runs this reporting on
# their own machine against their own copy of the workbook, with no tie to
# Alphalete's production roster or runner. Unset (production, Lucy 2): the
# hardcoded lists above are used untouched.
import json as _json
import os as _os

_OVR = _os.environ.get("RECRUITING_ROSTER_JSON", "").strip()
if _OVR:
    with open(_OVR, encoding="utf-8") as _f:
        _cfg = _json.load(_f)
    ORG = [tuple(x) for x in _cfg.get("org", [])]
    CAPTAINSHIP = [tuple(x) for x in _cfg.get("captainship", [])]
    ORG_NAMES = [n for n, _, _ in ORG]
    CAPTAINSHIP_NAMES = [n for n, _, _ in CAPTAINSHIP]
    SOUTH_SHORE_NAMES = list(_cfg.get("south_shore_names",
                             [n for n, _, _ in _cfg.get("south_shore", [])]))
    CAMPAIGN_ONLY = list(_cfg.get("campaign_only", []))
    ORG_LABEL = _cfg.get("org_label", "Org")
    if _cfg.get("board_groups"):
        BOARD_GROUPS = [(g["label"], list(g["members"]))
                        for g in _cfg["board_groups"]]
    else:
        BOARD_GROUPS = [(ORG_LABEL,
                         [n for n in ORG_NAMES if n != "Drew Tepper"])]
        if CAPTAINSHIP_NAMES:
            BOARD_GROUPS.append(("Captainship", CAPTAINSHIP_NAMES))
        if SOUTH_SHORE_NAMES:
            BOARD_GROUPS.append(("South Shore", SOUTH_SHORE_NAMES))
