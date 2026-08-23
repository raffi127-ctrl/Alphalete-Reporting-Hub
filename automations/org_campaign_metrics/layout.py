"""Campaign-block layouts for the org Focus Report — the single source of truth.

The Focus Report tab renders a generic "campaign zone" (N_SLOTS rows of
INDEX/MATCH formulas, built by funnel_board/build.py) below the recruiting
funnel. WHAT those rows say — band headers, labels, which rows are manual or
graded — is *data*, defined here and written to the hidden 'Campaign Log' tab
by sheet.py. Changing a campaign's metric list is an edit HERE plus one stamper
run; build.py never needs to know.

Slot kinds (column G on Campaign Log; build.py's CF rules key on these):
    hdr     campaign super-band (ink background)
    band0-4 section band, colored with the funnel's stage palette
            (TEAM / PRODUCTION / PRODUCT MIX / QUALITY / NATIONAL)
    m       automated metric row
    mm      manual metric row (typed in the sheet, synced back by Apps Script)
    mg      manual + has a goal in column B + graded against it (Head Count)
    g       automated + has a goal + graded (weekly units, Sales per Rep)

Values are stored and rendered as TEXT exactly as they should display ("288",
"6.4", "79%", "+12%") — one campaign's slot is a count where another's is a
rate, and a Sheets cell can hold only one number format. Grading CF compares
VALUE() of the text, so chips still work.

Owner spellings per source system live with each puller; the names HERE must
match the Focus Report picker (funnel_board/roster.py) exactly.
"""

# How many rows build.py reserves for the zone. Must be >= the longest layout;
# headroom is free (unused rows render blank and invisible).
N_SLOTS = 44

# First zone row on the Focus Report tab (1-based). build.py derives its own
# CAMP_Z0 from the funnel geometry and ASSERTS it equals this — goal_sync.gs
# hardcodes the same number, so a funnel-length change must fail loudly here
# instead of silently de-syncing the Apps Script.
ZONE_START = 30

# picker name -> campaign key. Only Carlos's Tuesday 1:1 people for now —
# an unmapped manager renders an empty zone, which is the correct default for
# everyone else. Adding a manager (e.g. Drew/Isaiah -> nds) is a config change.
MANAGER_CAMPAIGN = {
    "Carlos Hidalgo":    "b2b_att",
    "Atef Choudhury":    "b2b_att",
    "Ryan McSpadden":    "box",
    "Roshan Amin":       "box",
    "Khalil Mansour":    "nds",
    "Maxamad-Amin Aden": "nds",
    "MJ Malhas":         "limbo",
    "Akib Chowdhury":    "limbo",
}

# Campaigns whose manual rows (mm/mg) the stamper is allowed to overwrite —
# b2b_att's manual TEAM numbers live on the Captainship Dashboard MT tabs
# (Carlos types them there), so for b2b the stamper copy WINS. Everyone else's
# manual rows are typed on this dashboard and must never be stomped.
STAMPER_OWNS_MANUAL = {"b2b_att"}

LAYOUTS = {
    "b2b_att": [
        ("hdr",   "AT&T B2B — CAMPAIGN"),
        ("band0", "TEAM"),
        ("mg",    "Head Count  ✎"),
        ("mm",    "Leaders  ✎"),
        ("mm",    "People in Training  ✎"),
        ("m",     "Active Headcount on Tableau"),
        ("band1", "PRODUCTION"),
        ("g",     "Total Apps"),
        ("g",     "Sales per Rep"),
        ("m",     "Rank on the Tracker"),
        ("band2", "PRODUCT MIX"),
        ("m",     "New Internet Sales"),
        ("m",     "CRU Internet Sales"),
        ("m",     "Wireless Sales (excl. BYOD)"),
        ("m",     "BYOD Sales"),
        ("m",     "CRU BYOD Sales"),
        ("m",     "IRU BYOD Sales"),
        ("m",     "AIR/AWB Sales"),
        ("m",     "VoIP Line Count"),
        ("band3", "QUALITY"),
        ("m",     "CRU %"),
        ("m",     "ABP %"),
        ("m",     "BYOD %"),
        ("m",     "Activation Rate (31–60 Day)"),
        ("m",     "0–30 Day Churn Rate"),
        ("band4", "NATIONAL BENCHMARK"),
        ("m",     "National AVG Headcount"),
        ("m",     "National Sales per Rep"),
        ("hdr",   "B2B AT&T METRICS — SCREENSHOT"),
        ("m",     "(screenshot lands here — wiring in progress)"),
        ("hdr",   "FOUR-WEEK AVERAGE — SCREENSHOT"),
        ("m",     "(screenshot lands here — wiring in progress)"),
    ],
    "box": [
        ("hdr",   "BOX · B2B BOX ENERGY — CAMPAIGN"),
        ("band0", "TEAM"),
        ("mg",    "Head Count  ✎"),
        ("mm",    "Leaders  ✎"),
        ("mm",    "People in Training  ✎"),
        ("m",     "Total Rep Count on Tableau"),
        ("m",     "Selling Rep Count"),
        ("band1", "PRODUCTION"),
        ("g",     "Complete Sales"),
        ("g",     "Sales per Rep"),
        ("m",     "Rank on the Tracker"),
        ("m",     "vs Prior Week"),
        ("band2", "PRODUCT MIX"),
        ("m",     "ELE Sales"),
        ("m",     "Gas Sales"),
        ("m",     "Avg kWh per Sale"),
        ("band3", "QUALITY / PIPELINE"),
        ("m",     "Acceptance Rate (30–60 Day)"),
        ("m",     "Drop Rate (0–45 Day)"),
        ("m",     "Accepted by Supplier (wk)"),
        ("m",     "Still Open / Pending"),
        ("m",     "Drops This Week"),
        ("band4", "NATIONAL BENCHMARK"),
        ("m",     "National Sales per Rep"),
        ("m",     "National Avg kWh per Sale"),
    ],
    "nds": [
        ("hdr",   "NDS · AT&T OUT OF FOOTPRINT — CAMPAIGN"),
        ("band0", "TEAM"),
        ("mg",    "Head Count  ✎"),
        ("mm",    "Leaders  ✎"),
        ("mm",    "People in Training  ✎"),
        ("m",     "Active Selling Reps"),
        ("band1", "PRODUCTION"),
        ("g",     "New/Ports Sold"),
        ("g",     "Sales per Rep"),
        ("m",     "Rank on the Tracker"),
        ("m",     "AIR Sold"),
        ("m",     "Air %"),
        ("band3", "QUALITY"),
        ("m",     "Metric Flag Count"),
        ("m",     "Trailing Activation Rate (30–60 Day)"),
        ("m",     "0–30 Day Churn"),
        ("m",     "90 Day Churn"),
        ("m",     "ABP %"),
        ("m",     "High/Med Credit Risk %"),
        ("m",     "AT&T Lead Usage Rate"),
        ("m",     "Next Up %"),
        ("m",     "Extra / Premium %"),
        ("m",     "DNQ Rep Count"),
        ("band4", "NATIONAL BENCHMARK"),
        ("m",     "National Sales per Rep"),
        ("m",     "National 0–30 Churn"),
    ],
    "limbo": [
        ("hdr",   "CAMPAIGN — RETAIL / IN TRANSITION"),
        ("band0", "TEAM"),
        ("mg",    "Head Count  ✎"),
        ("mm",    "Leaders  ✎"),
        ("mm",    "People in Training  ✎"),
    ],
}

for _c, _rows in LAYOUTS.items():
    if len(_rows) > N_SLOTS:
        raise ValueError("layout %r has %d rows > N_SLOTS %d"
                         % (_c, len(_rows), N_SLOTS))


def slot_kinds(campaign):
    """{slot number (1-based): kind} for one campaign."""
    return {i + 1: k for i, (k, _lab) in enumerate(LAYOUTS.get(campaign, []))}


def slots_by_label(campaign):
    """{label: slot number} — pullers key on labels so layout edits don't
    silently re-aim a metric at the wrong row."""
    return {lab: i + 1 for i, (_k, lab) in enumerate(LAYOUTS.get(campaign, []))}


def manual_slots(campaign):
    return [s for s, k in slot_kinds(campaign).items() if k in ("mm", "mg")]


def goal_slots(campaign):
    return [s for s, k in slot_kinds(campaign).items() if k in ("mg", "g")]
