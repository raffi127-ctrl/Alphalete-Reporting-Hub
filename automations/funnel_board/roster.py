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
    ("Cyrus Wade",        "22815", "Cyrus Wade"),
    ("Drew Tepper",       "22583", "Drew Tepper"),
    ("Haytham Nagi",      "22524", "Haytham Nagi"),
    ("Isaiah Revelle",    "19717", "Isaiah Revelle"),
    ("Jacob Dover",       "23607", "Jacob Dover"),
    ("Kash Rai",          "22177", "Akashdeep Rai"),
    ("Khalil Mansour",    "11901", "KHALIL MANSOUR"),
    ("Maxamad-Amin Aden", "23066", "Maxamad Aden"),
    ("Rafael Hidalgo",    "11280", "Rafael Hidalgo"),
    ("Rashad Reed",       "23411", "Rashad Reed"),
    ("Roshan Amin",       "19833", "Roshan Amin Ahmad"),
    ("Ryan McSpadden",    "22820", "Ryan McSpadden"),
    ("Salik Mallick",     "21328", "Muhammad UI Haque"),
]

ORG_NAMES = [n for n, _, _ in ORG]

CAPTAINSHIP = [
    # Carlos's own office leads it — he sits on the org board too, and asked for
    # his numbers here as well so the captainship total is the whole team
    # including him, not the team he manages minus himself.
    ("Carlos Hidalgo",   "11580", "CARLOS HIDALGO"),      # also on the org board
    ("Atef Choudhury",   "23467", "Atef Choudhury"),      # also on the org board
    ("Jamis Garay",      "19592", "Jamis Garay"),
    # 22358 is not in office-mapping-carlos.json (it has her as sales-only) —
    # it comes from her own Indeed tracker tab, whose Office ID column matches
    # the AppStream id exactly for all four of the others. If AppStream refuses
    # it, the run says so per office and she just stays at zero.
    ("Jackie LeRoy",     "22358", "Jackie LeRoy"),
    ("Noah Dubale",      "23356", "Noah Dubale"),
    ("Jeff Starr",       "15031", "Jeffrey Starr"),
    ("Kinsey Guenther",  "11906", "Kinsey Guenther"),
    ("Vincent Smith",    "23318", "Vincent Smith"),
    ("George Hipolito",  "11296", "George Hipolito"),
    ("Justin Wood",      "22192", "Justin Wood"),
    # Two offices answer to "Joshua Murphy" on this login — 21770 Leadsphere
    # Solutions and 10707 Zealous United. Carlos confirmed 21770 (2026-08-19),
    # which is also what office-mapping-carlos.json had. Discovery would have
    # resolved NEITHER here, by design.
    ("Joshua Murphy",    "21770", "Joshua Murphy"),
    ("Joey Ramirez",     "23206", "Joey Ramirez"),
    ("Dhyey Patel",      "22767", "Dhyey Patel"),
]

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
