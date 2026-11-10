"""Marketplace Watch settings — edit these, not run.py.

Goal: cheap/free office furniture near the office, alerted as soon as it's
listed. Center = 5217 Tennyson Pkwy, Plano TX 75024.
"""

# The office (5217 Tennyson Pkwy, Plano TX 75024).
OFFICE_LAT, OFFICE_LNG = 33.0779, -96.8226

# "About 20 minutes" ≈ 13 straight-line miles in DFW traffic. Every listing
# card only says a city ("Frisco, TX"), so distance = office → city center.
MAX_MILES = 13

# Free counts (price 0). Anything above this is skipped.
MAX_PRICE = 100

# One Marketplace search per line, newest first. Dallas is the only metro
# slug FB accepts in the URL; the 65 km radius around Dallas covers all of
# Collin/Denton, then MAX_MILES trims it to our side of town.
SEARCHES = [
    "office chair",
    "desk chair",
    "desk",
    "office desk",
    "standing desk",
    "office furniture",
    "filing cabinet",
    "conference table",
    # guest + lobby seating (Megan, 2026-11-10)
    "guest chairs",
    "reception chairs",
    "waiting room chairs",
    "lobby furniture",
    "leather sofa",
    "loveseat",
    # large decor for the offices
    "large wall art",
    "floor mirror",
    "artificial tree",
]

# A title must hit one of these to count as office furniture...
KEEP_WORDS = [
    "chair", "desk", "office", "conference table", "work table",
    "folding table", "cabinet", "file", "filing",
    "bookcase", "bookshelf", "shelf", "shelving", "credenza", "workstation",
    "cubicle", "stool", "escritorio", "silla",
    # guest / lobby seating
    "guest", "lobby", "reception", "waiting", "sofa", "couch", "loveseat",
    "settee", "sectional", "bench", "accent chair", "armchair",
    # large decor
    "wall art", "canvas", "painting", "artwork", "mirror", "artificial",
    "faux", "tree", "sculpture", "decor", "rug",
]
# ...and none of these.
SKIP_WORDS = [
    "lamp", "baby", "toddler", "kid", "kids", "child", "high chair",
    "highchair", "car seat", "booster", "stroller", "rocking", "massage",
    "wheelchair", "shower", "potty", "camping", "beach", "lawn", "patio",
    "wanted", "iso", "looking for", "mat", "pad", "organizer", "monitor",
    "keyboard", "mouse", "printer", "dollhouse", "toy", "plant stand",
    "console", "dining", "kitchen", "bar table", "coffee table", "end table",
    "nightstand", "entry table",
]

# City center coordinates for every town within ~20 miles. A city that
# isn't here is skipped and logged as "unknown city" so it can be added.
CITY_COORDS = {
    "plano": (33.0198, -96.6989),
    "frisco": (33.1507, -96.8236),
    "the colony": (33.0890, -96.8864),
    "carrollton": (32.9756, -96.8900),
    "addison": (32.9612, -96.8292),
    "richardson": (32.9483, -96.7299),
    "allen": (33.1032, -96.6706),
    "lewisville": (33.0462, -96.9942),
    "farmers branch": (32.9265, -96.8961),
    "little elm": (33.1626, -96.9375),
    "hackberry": (33.1518, -96.9172),
    "oak point": (33.1801, -96.9911),
    "lake dallas": (33.1193, -97.0256),
    "hickory creek": (33.1232, -97.0436),
    "highland village": (33.0918, -97.0466),
    "prosper": (33.2362, -96.8011),
    "parker": (33.0568, -96.6214),
    "fairview": (33.1579, -96.6317),
    "murphy": (33.0151, -96.6131),
    "mckinney": (33.1972, -96.6398),
    "lucas": (33.0843, -96.5764),
    "coppell": (32.9546, -97.0150),
    "corinth": (33.1540, -97.0647),
    "flower mound": (33.0146, -97.0970),
    "garland": (32.9126, -96.6389),
    "sachse": (32.9762, -96.5953),
    "university park": (32.8501, -96.8000),
    "highland park": (32.8335, -96.7920),
    "celina": (33.3246, -96.7845),
    "wylie": (33.0151, -96.5389),
    "rowlett": (32.9029, -96.5639),
    "irving": (32.8140, -96.9489),
    "denton": (33.2148, -97.1331),
    "dallas": (32.7767, -96.7970),
    "mesquite": (32.7668, -96.5992),
    "grand prairie": (32.7460, -96.9978),
    "arlington": (32.7357, -97.1081),
    "southlake": (32.9412, -97.1342),
    "grapevine": (32.9343, -97.0781),
}

# Who gets the alert email: Megan's own pick (2026-11-10). Email, not Slack:
# the only Slack login on her laptop is her own, and Slack never pings you for
# your own message. The address lives OFF the repo, on this Mac only:
#   ~/.config/recruiting-report/marketplace-alert-email
from pathlib import Path as _P
try:
    ALERT_EMAIL = (_P.home() / ".config/recruiting-report/marketplace-alert-email"
                   ).read_text().strip()
except OSError:
    ALERT_EMAIL = ""

# Never more than this many alert emails a day (Megan, 2026-11-10). The schedule runs
# twice (9am + 3pm); this is the backstop if someone reruns it by hand.
MAX_ALERTS_PER_DAY = 2
