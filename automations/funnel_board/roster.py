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
    ("Joshua Murphy",    "21770", "Joshua Murphy"),
    ("Joey Ramirez",     "23206", "Joey Ramirez"),
    ("Dhyey Patel",      "22767", "Dhyey Patel"),
]

CAPTAINSHIP_NAMES = [n for n, _, _ in CAPTAINSHIP]

# Indeed ad tracker tabs that actually exist in the workbook today, for the
# Captain Ship Ad View dropdown. A name here must match a tab EXACTLY —
# INDIRECT does a literal string match, and a trailing space in a tab name
# breaks the view while looking perfectly fine in the tab bar.
AD_TABS = ["Atef Choudhury", "Jackie LeRoy", "Jamis Garay",
           "Justin Wood", "Noah Dubale"]

BOARD_TITLE = "Captainship Board"
TREND_TITLE = "Captainship Manager Trend"
AD_VIEW_TITLE = "Captain Ship Ad View"
