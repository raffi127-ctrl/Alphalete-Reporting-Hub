"""The Orientation Manual content, as tokenized page specs.

Text is stored with `{token}` placeholders so any company can be swapped in.
Tokens (see build.py Context):
    {company}       full company name          e.g. "Alphalete Marketing"
    {company_short} short/first word           e.g. "Alphalete"
    {owner}         owner / upline leadership   e.g. "Raf & JD"
    {owner_short}   single owner first name     e.g. "Raf"
    {location}      city, ST                    e.g. "Irving, TX"

Each page is a dict with a "type" that maps to a renderer in build.py. Only
branding tokens change per company; the training content is the shared system
every office adopts.

STATUS: 20 content pages captured from the Canva source. The three internal
new-starts / follow-up tracker pages were dropped — they held applicant PII and
aren't part of the rep-facing orientation content.
"""

# Original-source values, used when no branding overrides are passed (renders
# the Alphalete baseline) and as the reference for what each token replaces.
ORIGINAL = {
    "company": "Alphalete Marketing",
    "company_short": "Alphalete",
    "owner": "Raf & JD",
    "owner_short": "Raf",
    "location": "Irving, TX",
    "upline": "Raf & JD",
}

PAGES = [
    # ---- p1: cover / welcome letter -------------------------------------
    {
        "type": "cover",
        "title": "WELCOME TO THE TEAM!",
        "letter": [
            "Welcome to the {company} team! We are excited to have you begin "
            "your new career with us! You possess the attributes necessary to "
            "be successful with us, and we aim to provide you the opportunity "
            "to grow personally and professionally through our training "
            "program.",
            "At our {location} location, you will be encouraged to expand your "
            "horizons and face new challenges daily. With the right student "
            "mentality, you will accomplish the tasks required for promotions "
            "at your own pace. We will help you develop your communication "
            "skills and self-management right from the start. Your career "
            "growth will be based solely on learning the fundamentals of our "
            "proven system. You will receive adequate coaching, and our doors "
            "are open to discussing your progress at any time.",
            "We look forward to many promising conversations about your "
            "future. We are pleased to congratulate you on the opportunity to "
            "capitalize on this position as {company} continues to grow. The "
            "search for high-caliber individuals is our top priority to keep "
            "pace with our forecasted expansion!",
            "The following pages outline our expectations, client "
            "representation, and the steps to achieve success within the "
            "company.",
        ],
        "signoff": "Sincerely,",
        "signoff_team": "THE {company_upper} MANAGEMENT TEAM",
    },

    # ---- p2: "most don't make it" stat splash ---------------------------
    {
        "type": "splash",
        "kicker": "THE 30 DAYS THAT LAUNCH YOUR CAREER",
        "headline": "THE 30-DAY {company_short} BOOT CAMP",
        "pin_image": "resources/10x-pin.png",
        "stats": [
            {"big": "85%",
             "label": "Of reps who complete the 30-day boot camp go on to earn "
                      "$150K+ a year."},
            {"big": "10X",
             "label": "Earn your 10X pin the moment you finish your first "
                      "30 days."},
        ],
        "closer": "Give these 30 days everything you've got — it's the "
                  "foundation the rest of your career is built on.",
    },

    # ---- p3: scheduling / time off / commissions ------------------------
    {
        "type": "schedule",
        "sidebar": "SCHEDULING",
        "blocks": [
            {
                "heading": "REQUESTING TIME OFF",
                "body_bullets": True,
                "body": [
                    "A 1 week notice is required",
                    "Send a Slack message to upline",
                    "Include:",
                ],
                "bullets": [
                    "Dates you're requesting off",
                    "Reason for absence",
                ],
            },
            {
                "heading": "COMMISSIONS",
                "body": [
                    "In order to ensure that you receive full commission "
                    "payments, it is crucial to dedicate yourself to a complete "
                    "workweek of 6 days.",
                    "It is important to note that full commission should not be "
                    "expected without fulfilling the full 40-hour workweek "
                    "requirement.",
                ],
                "bullets": [],
            },
        ],
        # Office/Field split, exact times from the packet (pending Megan's
        # confirmation of the hours).
        "week_table": {
            "days": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
            "rows": [
                ["OFFICE", "11:00–12:30 PM", "11:00–12:30 PM", "11:00–12:30 PM",
                 "11:00–12:30 PM", "11:00–12:30 PM", "9:00–10:00 AM", "OFF"],
                ["FIELD", "1:30–8:30 PM", "1:30–8:30 PM", "1:30–8:30 PM",
                 "1:30–8:30 PM", "1:30–8:30 PM", "9:45 AM–5:00 PM", "OFF"],
            ],
        },
    },

    # ---- p4: communication / Slack --------------------------------------
    {
        "type": "concept",
        "sidebar": "COMMUNICATION",
        "title": "COMMUNICATION",
        "intro": "We run on Slack. Here's what everything means:",
        "image": "resources/slack-example.png",
        "terms": [
            ("WORKSPACE",
             "Our company's Slack home — every channel and person lives here."),
            ("CHANNELS",
             "Topic-based group chats (like #sales) — post your sales, wins, "
             "and updates."),
            ("DIRECT MESSAGES",
             "Private 1-on-1 or small-group chats."),
            ("THREAD",
             "Replies attached to a specific message — keeps conversations "
             "organized."),
            ("HUDDLE",
             "A quick live audio call right inside Slack."),
        ],
        "notes": [
            "{upline_line}",
            "Have a question about punctuality, territory, or anything else? "
            "Send your upline a Slack message.",
            "We live on Slack — you'll get a faster response here than by "
            "text. :)",
        ],
    },

    # ---- p5: promotional checklist / the opportunity --------------------
    {
        "type": "promotion",
        "sidebar": "ADVANCEMENT",
        "title": "THE OPPORTUNITY!",
        "subtitle": "PROMOTIONAL CHECK LIST",
        # Items may be a plain string, or {"head":..., "sub":[...]} for a
        # parent line with indented sub-items. Matches the Canva page exactly.
        "levels": [
            {
                "name": "LEVEL 1 PROMOTION",
                "items": [
                    {"head": "Honoring the partnership",
                     "sub": ["Accountable", "Professional dress",
                             "Atmo / Slack engagement",
                             "Reading / listening habits"]},
                    "Marketing systems + honoring the partnership memorized",
                    "Leadership contract signed with upline",
                    "14 units over 2 weeks",
                ],
            },
            {
                "name": "LEVEL 2 PROMOTION",
                "items": [
                    {"head": "Be partner honoring",
                     "sub": ["Maintain 7 units weekly"]},
                    "Team structure: 1/2",
                    "Read one book on the approval booklist or one book "
                    "specifically recommended by upline",
                ],
            },
            {
                "name": "LEVEL 3 PROMOTION",
                "items": [
                    {"head": "Be partner honoring",
                     "sub": ["Maintain 7 units weekly"]},
                    "Money (goal decided by upline)",
                    "Team structure: 2/4",
                    "Read one book on the approval booklist or one book "
                    "specifically recommended by upline",
                ],
            },
            {
                "name": "MASTERMIND PROMOTION",
                "items": [
                    {"head": "Be partner honoring",
                     "sub": ["Maintain 7 units weekly"]},
                    "Money saved goal (decided by upline)",
                    "Team structure: 4/6",
                    "Read one book on the approval booklist or one book "
                    "specifically recommended by upline",
                ],
            },
            {
                "name": "PARTNER PROMOTION",
                "items": [
                    {"head": "Be partner honoring",
                     "sub": ["Maintain 7 units weekly"]},
                    "Positive PNL for 8 weeks in a row",
                    "Team structure: 6/10",
                    "Read one book on the approval booklist or one book "
                    "specifically recommended by upline",
                ],
            },
        ],
    },

    # ---- p6: management training book list ------------------------------
    {
        "type": "booklist",
        "sidebar": "SELF DEVELOPMENT",
        "kicker": "MANAGEMENT TRAINING PROGRAM",
        "title": "BOOK LIST",
        "intro": "Leaders never stop reading. Work the list — read them, apply "
                 "them, and level up.",
        # (title, author) — alphabetical.
        "books": [
            ("The 5 Dysfunctions of a Team", "Patrick Lencioni"),
            ("The 5 Levels of Leadership", "John Maxwell"),
            ("10X", "Grant Cardone"),
            ("21 Irrefutable Laws of Leadership", "John Maxwell"),
            ("Above the Line", "Urban Meyer"),
            ("Atomic Habits", "James Clear"),
            ("Be Obsessed or Be Average", "Grant Cardone"),
            ("Big Money Energy", "Ryan Serhant"),
            ("Bringing Out the Best in People", "Alan Loy McGinnis"),
            ("Can't Hurt Me", "David Goggins"),
            ("Crucial Accountability", "Joseph Grenny & Ron McMillan"),
            ("Crucial Conversations", "Joseph Grenny & Ron McMillan"),
            ("The Dream Giver", "Bruce Wilkinson"),
            ("Dynamic People Skills", "Dexter Yager"),
            ("An Enemy Called Average", "John Mason"),
            ("The Energy Bus", "Jon Gordon"),
            ("Extreme Ownership", "Jocko Willink & Leif Babin"),
            ("The Gap & the Gain", "Dan Sullivan"),
            ("The Go-Getter", "Peter Kyne"),
            ("How I Raised Myself From Failure to Success in Selling",
             "Frank Bettger"),
            ("How to Win Friends & Influence People", "Dale Carnegie"),
            ("Hung by the Tongue", "Francis P. Martin"),
            ("Influence: The Psychology of Persuasion", "Robert Cialdini"),
            ("Leadershift", "John Maxwell"),
            ("The Magic of Thinking Big", "David Schwartz"),
            ("Managing Oneself", "Peter Drucker"),
            ("The Master Key to Riches", "Napoleon Hill"),
            ("Millionaire Booklet", "Grant Cardone"),
            ("The Motive", "Patrick Lencioni"),
            ("Psychology of Selling", "Brian Tracy"),
            ("Rich Dad Poor Dad", "Robert Kiyosaki"),
            ("The School of Greatness", "Lewis Howes"),
            ("Sell It Like Serhant", "Ryan Serhant"),
            ("Sell or Be Sold", "Grant Cardone"),
            ("Skills With People", "Les Giblin"),
            ("Slight Edge", "Jeff Olson"),
            ("Speed of Unity", "Rob Ketterling"),
            ("Think & Grow Rich", "Napoleon Hill"),
            ("Way of the Wolf", "Jordan Belfort"),
            ("What to Say When You Talk to Yourself", "Shad Helmstetter"),
            ("Wired That Way", "Marita Littauer"),
        ],
    },

    # ---- p7: podcasts ---------------------------------------------------
    {
        "type": "media",
        "sidebar": "LISTEN NOW",
        "title": "PODCASTS",
        "footnote": "SCAN & FOLLOW",
        # Each item: (title, url). A url renders a real scannable QR code;
        # None renders a "link coming" placeholder until we have the link.
        # (title, url, cover_image)
        "sections": [
            {
                "group": "HONOR THE PARTNERSHIP",
                "items": [
                    ("Unlocked — Richard Anderson",
                     "https://www.youtube.com/playlist?"
                     "list=PLnEHS0Vz2ri-00GOXyp9F1tn8hs2NcPkE",
                     "resources/podcasts/unlocked.png"),
                    ("The Process — Carlos Hidalgo & Colten Wright",
                     "https://podcasts.apple.com/ca/podcast/"
                     "the-process/id1685765704",
                     "resources/podcasts/the-process.png"),
                ],
            },
            {
                "group": "THE PARTNERSHIP",
                "items": [
                    ("Maxwell Leadership Podcast — John Maxwell",
                     "https://www.youtube.com/playlist?"
                     "list=PLlWx1lni_ne0JdyS77beZjnUQX9bAYecC",
                     "resources/podcasts/maxwell.png"),
                    ("Jocko Podcast — Jocko Willink",
                     "https://podcasts.apple.com/us/podcast/"
                     "jocko-podcast/id1070322219",
                     "resources/podcasts/jocko.png"),
                    ("The Game — Alex Hormozi",
                     "https://podcasts.apple.com/us/podcast/"
                     "the-game-with-alex-hormozi/id1254720112",
                     "resources/podcasts/the-game.png"),
                    ("Build with Leila Hormozi",
                     "https://podcasts.apple.com/us/podcast/"
                     "build-with-leila-hormozi/id1663834553",
                     "resources/podcasts/build.png"),
                ],
            },
        ],
    },

    # ---- p8: 9 core steps framework -------------------------------------
    {
        "type": "framework",
        "sidebar": "9 CORE STEPS",
        "title": "9 CORE STEPS",
        "steps": [
            ("1. Professional Networking", [
                {"b": "2-5 1-on-1's a week (with upline or referral)",
                 "sub": ["2-5 hrs/week"]},
                "Reaching out",
                "Making friends / connections outside the office",
                "Calendar planning",
            ]),
            ("2. Personal Sales", [
                "Proactively trying to improve this # by reaching up "
                "constantly",
                "Lead by example",
                "1 new INT daily minimum (6 min per week)",
            ]),
            ("3. Reading", [
                "15 mins daily",
                "Success & Principle book",
                "Leadership books",
                "People skills books",
                "Sales books",
                "Self-image books",
            ]),
            ("4. Listening", [
                "1 podcast daily (30 mins)",
                "Richard Anderson / Carlos Hidalgo / Alex Hormozi / "
                "Leila Hormozi / Jocko Willink",
                "In the AM getting ready / driving in your car",
            ]),
            ("5. Association / Networking", [
                {"b": "Office presence — adding energy & positivity",
                 "sub": ["Atmo: no cell phone or leaving the room",
                         "Atmo = where we make our money"]},
                "Slack engagement — responding to all posts and sales",
                "Team nights",
                "Team meeting fun night",
                "Quarterly conferences",
                "Education vs. Education",
                "Prioritizing future success",
            ]),
            ("6. Accountability", [
                "100% attendance",
                "Submitting territory webform by EOD",
                "Weekly breakdowns & game plans",
                "90 day Core Run — Habit Tracker",
            ]),
            ("7. Earn Mentorship / Coachability", [
                "Honoring the partnership",
            ]),
            ("8. Communication", [
                "Over-communicate with your upline",
                "Ask questions early — raise your hand",
                "Give clear, consistent updates",
            ]),
            ("9. Dress Professional", [
                "Dress like you run the place, because you will :)",
            ]),
        ],
        "footer": (
            "EARN MENTORSHIP — partner up with your mentor to earn your "
            "position in ownership. Perform the 9 Core Steps for 180 days / "
            "26 weeks and you'll be offered a business ownership position."
        ),
    },

    # ---- p9: commission structure — training pay ------------------------
    {
        "type": "paytable",
        "sidebar": "COMMISSION",
        "title": "COMMISSION STRUCTURE",
        "subtitle": "1st Two Weeks · Training Pay",
        "banner": "$600 TRAINING BONUS FOR YOUR FIRST 2 CHECKS",
        "row_h": 26,
        "blocks": [
            {
                "kind": "checks",
                "heading": "WEEK 1 — QUALIFYING FOR TRAINING PAY",
                "items": [
                    "5 closing frames",
                    "Reshare story",
                    "Explain early + late objection",
                    "5 rebuttals memorized & said correctly",
                    "Attendance every day",
                ],
            },
            {
                "kind": "checks",
                "heading": "WEEK 2 — QUALIFYING FOR TRAINING PAY",
                "items": [
                    "Honoring the Partnership teachback",
                    "Internet quiz completed & gone over with upline",
                    "3 new INTs, or 2 INTs + lines, in your own code by "
                    "yourself",
                    "Use QuickQuote — show 4 quotes to upline",
                    "Teachback the main promotions on the whiteboard (5 main "
                    "phones we sell, ported-line promotions, converged bundle "
                    "offer, appreciation offer)",
                    "Show how to find TIV & what it means",
                    "Explain Next Up",
                    "Explain first 3 months' bills",
                ],
            },
            {
                "kind": "tables",
                "heading": "WEEK 3+ — FULL BONUSES + COMMISSIONS",
                "side_by_side": True,
                "space_before": 30,
                "tables": [
                    {
                        "label": "INT ONLY",
                        "headers": ["Examples", "Per Sale", "Payout"],
                        "size": 9,
                        "rows": [
                            ["11 Activations", "$200", "$2,200"],
                            ["8 Activations", "$185", "$1,480"],
                            ["5 Activations", "$170", "$850"],
                            ["1 GIG + Auto Bill Pay", "$150"],
                        ],
                    },
                    {
                        "label": "INT + 5 NEW LINES",
                        "headers": ["Examples", "Breakdown", "Payout"],
                        "size": 9,
                        "rows": [
                            ["11 new INT + 11 new lines", "$2,200 + $1,375",
                             "$3,575"],
                            ["8 new INT + 8 new lines", "$1,480 + $1,000",
                             "$2,480"],
                            ["5 new INT + 5 new lines", "$850 + $625",
                             "$1,475"],
                            ["1 new line + 5 new INT", "$40 bonus per line"],
                            ["1 new line", "$85"],
                        ],
                    },
                ],
            },
        ],
    },

    # ---- p10: commission structure — rate card --------------------------
    {
        "type": "paytable",
        "sidebar": "COMMISSION",
        "title": "COMMISSION STRUCTURE",
        "subtitle": "Rate Card",
        "row_h": 30,
        "blocks": [
            {
                "kind": "tables",
                "heading": "AT&T INT FIBER",
                "tables": [{
                    "headers": ["ATT INT Fiber", "With ABP", "No ABP",
                                "Owner Pay"],
                    "size": 11, "first_left": False, "all_bold": True,
                    "rows": [
                        ["AT&T INT Fiber 1GIG +", "$150", "$0", "$263.50"],
                        ["5–7 INT · $20 bonus per sale", "$170", "$0",
                         "$283.50"],
                        ["8–10 INT · $35 bonus per sale", "$185", "$0",
                         "$298.50"],
                        ["11+ INT · $50 bonus per sale", "$200", "$0",
                         "$313.50"],
                        ["ATT INT upgrade to 300–500 MBPS", "$25", "$0", "—"],
                        ["ATT INT upgrade to 1GIG+", "$60", "$0", "—"],
                    ],
                }],
            },
            {
                "kind": "tables",
                "heading": "DTV STREAM",
                "tables": [{
                    "headers": ["DTV Stream", "Commission"],
                    "size": 11, "first_left": False, "all_bold": True,
                    "rows": [
                        ["Entertainment", "$85"],
                        ["Choice & above", "$100"],
                    ],
                }],
            },
            {
                "kind": "tables",
                "heading": "NEW LINES",
                "tables": [{
                    "headers": ["New Lines", "With Next Up", "No Next Up",
                                "Bonus · 5 new INTs same week"],
                    "size": 11, "first_left": False, "all_bold": True,
                    "rows": [
                        ["New line upgrade", "$15", "N/A", "N/A"],
                        ["New lines", "$85", "N/A", "$40"],
                        ["Elite / Extra", "$10", "N/A", "N/A"],
                        ["BYOD", "$40", "N/A", "N/A"],
                    ],
                }],
            },
        ],
    },

    # ---- p11: breakeven / finances worksheet ----------------------------
    {
        "type": "worksheet",
        "sidebar": "FINANCES",
        "title": "BREAKEVEN",
        "subtitle": "WHO'S GOT MY MONEY?!",
        "summary_title": "Weekly / Monthly Expenses",
        "summary": ["Monthly Expenses", "Weekly Expenses",
                    "Gross Paycheck Needed"],
        "table_headers": ["Fixed Monthly Bills", "Debt"],
        "rows_list": [
            "Mortgage / Rent", "Renters Insurance", "Utilities", "Car Payment",
            "Car Insurance", "Cell Phone", "Gas", "Groceries", "Toiletry",
            "Meals & Entertainment", "Subscription:", "Subscription:",
            "Subscription:", "Subscription:", "Student Loan Payments",
            "Debt Payments", "Credit Card Payments", "Medical Payments",
        ],
    },

    # ---- p15: suggestions box QR ----------------------------------------
    {
        "type": "qrpage",
        "sidebar": "YOUR VOICE",
        "title": "Suggestions",
        "title2": "BOX",
        "subtitle": "Anonymous. Read by leadership. Your ideas move the "
                    "office forward.",
        # TEMPLATE DEFAULT — swap for the office's own suggestions form.
        "url": "https://forms.gle/your-suggestions-box",
        "caption": "SCAN TO DROP A SUGGESTION",
    },

    # ---- p16: 8 steps to success ----------------------------------------
    {
        "type": "steps",
        "sidebar": "FUNDAMENTALS",
        "title": "8 STEPS TO SUCCESS",
        "steps": [
            "Have a great attitude",
            "Be on time",
            "Be prepared",
            "Work the full day",
            "Work the full territory",
            "Maintain your attitude",
            "Know why you're here",
            "Take control",
        ],
    },

    # ---- p17: 5 steps to a conversation ---------------------------------
    {
        "type": "numbered",
        "sidebar": "THE PITCH",
        "title": "5 STEPS TO A CONVERSATION",
        "subtitle": "A System to BUILD Impulse",
        "steps": [
            {"n": "1", "name": "INTRODUCTION",
             "left": [
                "Ice breaker",
                {"b": "SEE Factors:", "sub": [
                    "S — Smile (builds comfort + contagious)",
                    "E — Eye Contact (creates confidence and trust)",
                    "E — Enthusiasm (builds curiosity)"]},
             ],
             "right": [
                "Wave/Head nod",
                "Confident body language\n(chest out / shoulders back / "
                "chin up)",
                "Broomstick Theory (give them room to come outside)",
             ]},
            {"n": "2", "name": "SHORT STORY", "bullets": [
                "Who, What, Why",
                "KISS it (Keep It Short & Simple)",
                {"b": "Example:", "sub": [
                    "\"Hi! My name is Tommy with AT&T. They sent us here "
                    "because everyone is switching their internet.\""]},
            ]},
            {"n": "3", "name": "PRESENTATION",
             "left": [
                "Build Impulse and Value in the product",
                "Ask Questions to create problems",
                "Active listening",
                "Make it make sense (MIMS)",
             ],
             "right": [
                {"b": "CPR with the customer", "sub": [
                    "Create a Personal Relationship"]},
                {"b": "Use FORDs to connect", "sub": [
                    "Family · Occupation · Recreation",
                    "Dogs · Sports"]},
             ]},
            {"n": "4", "name": "CLOSE",
             "left": [
                "When? At the HEIGHT of impulse.",
                "Ask for business. If you don't make it a big deal, it "
                "won't be one.",
                "Assume the sale",
             ],
             "right": [
                "Avoid silence",
                "Ask Yes-Yes questions — Example: \"What card do you want "
                "on file for autopay, debit or credit?\"",
                "Close with ACTION, not HESITATION",
             ]},
            {"n": "5", "name": "REHASH",
             "left": [
                "Remember everyone has another sale hidden",
                "Review the order with them",
             ],
             "right": [
                "Confirm the person's phone number",
                "Go over installation or delivery process",
                "Pre-empt drop work (AT&T)",
             ]},
        ],
    },

    # ---- p18: garden theory ---------------------------------------------
    {
        "type": "garden",
        "sidebar": "PACE",
        "title": "GARDEN THEORY",
        "laps": [
            {"tag": "LAP 1 · 1:45–5:45 PM",
             "title": "WEEDING OUT & PLANTING SEEDS",
             "note": "Hit 40–60 houses before 5 PM",
             "list_head": "TYPES OF PEOPLE",
             "bullets": ["Stay-at-home parents", "Babysitters", "Elderly",
                         "Shift workers", "Kids", "Teachers", "Unemployed",
                         "Construction workers", "Some decision makers (DMs)"]},
            {"tag": "LAP 2 · 5:45–8:00 PM",
             "title": "HARVEST & MONEY LAP",
             "note": "Go back to houses that didn't answer, comebacks, "
                     "referrals",
             "list_head": "TYPES OF PEOPLE",
             "bullets": ["Doctors", "Lawyers", "Business owners", "9–5'ers",
                         "Decision makers (DMs)", "Single parents"]},
        ],
        "boxes": [
            {"title": "3 TYPES OF DAYS", "lines": [
                {"lead": "A Day —", "x": "starts fast, finishes slow. More "
                 "yes's in the first lap, more no's in the 2nd."},
                {"lead": "B Day —", "x": "more no's in the first lap, more "
                 "yes's in the 2nd."},
                {"lead": "C Day —", "x": "consistent all day — yes's come "
                 "throughout the day."},
            ]},
            {"title": "LAW OF AVERAGES \"LOA's\"", "lines": [
                {"x": "Laps: 2"}, {"x": "Houses: 60–80+"},
                {"x": "Talk-to's: 15–20"}, {"x": "Presentations: 10–15+"},
                {"x": "Closes: 5–10"}, {"x": "Sales: 1–2"},
            ]},
            {"title": "5 TYPES OF PEOPLE", "lines": [
                {"x": "1.  No"}, {"x": "2.  Shopper"}, {"x": "3.  Looker"},
                {"x": "4.  M + R (Mean + Rude)"}, {"x": "5.  Buyer"},
            ]},
        ],
    },

    # ---- p19: impulse & fugi factor -------------------------------------
    {
        "type": "fugi",
        "sidebar": "IMPULSE",
        "title": "IMPULSE & FUGI FACTOR",
        "subtitle": "A System to Create More Impulse",
        "intro": "You spend 80% of your time with maybes and 20% with a solid "
                 "yes or no. This gets people to a solid yes or no faster.",
        "cols": 2,
        "cards": [
            {"heading": "FEAR OF LOSS", "lines": [
                {"t": "bullet", "x": "Specific: using specific names & "
                 "testimonials"},
                {"t": "bullet", "x": "Generic: phrases like \"everyone is "
                 "getting it\""},
                {"t": "label", "lead": "Verbal:", "x": "\"We're all booked "
                 "today, but we can squeeze you in tomorrow — morning or "
                 "afternoon?\""},
                {"t": "label", "lead": "Non-Verbal:", "x": "taking the flyer "
                 "/ item out of hand"},
            ]},
            {"heading": "URGENCY", "sub": "We are always in a rush!", "lines": [
                {"t": "labelhead", "x": "Verbal:"},
                {"t": "bullet", "x": "\"Right now, super fast, really quick, "
                 "takes no time, I only have a few minutes\""},
                {"t": "labelhead", "x": "Non-Verbal:"},
                {"t": "bullet", "x": "Look at your watch, walk fast, run"},
                {"t": "note", "x": "Use these phrases at least 5 times each "
                 "pitch."},
            ]},
            {"heading": "GREED FACTOR", "sub": "\"Jones Effect\"", "lines": [
                {"t": "bullet", "x": "Point around the neighborhood"},
                {"t": "bullet", "x": "Use past testimonials (stories with "
                 "specific names)"},
                {"t": "bullet", "x": "Keeping up with the Joneses — "
                 "\"everyone is upgrading their internet\""},
                {"t": "label", "lead": "Verbal:", "x": "\"Everyone is getting "
                 "installed\""},
                {"t": "label", "lead": "Non-Verbal:", "x": "pointing to other "
                 "parts of the neighborhood"},
            ]},
            {"heading": "INDIFFERENCE",
             "sub": "Don't be pushy — get a solid yes or no.", "lines": [
                {"t": "labelhead", "x": "Verbal:"},
                {"t": "bullet", "x": "\"It's up to you\""},
                {"t": "bullet", "x": "\"It doesn't matter either way!\""},
                {"t": "labelhead", "x": "Non-Verbal:"},
                {"t": "bullet", "x": "Panda paws, take a step back, shrug "
                 "your shoulders"},
            ]},
        ],
    },

    # ---- p20: stop signs ------------------------------------------------
    {
        "type": "cards",
        "sidebar": "READ THE BUYER",
        "title": "STOP SIGNS",
        "subtitle": "Shut Up, Take Out Tablet",
        "decor": "stop",
        "cols": 1,
        "cards": [
            {"heading": "BUYING SIGNS", "lines": [
                {"t": "bullet", "x": "Future talk"},
                {"t": "bullet", "x": "Talking about current services "
                 "(issues / problems)"},
                {"t": "bullet", "x": "Positive body language / engaged in "
                 "conversation"},
                {"t": "bullet", "x": "Already tried to get our service / "
                 "looked into it"},
                {"t": "bullet", "x": "Repeating / agreeing with the issues"},
                {"t": "bullet", "x": "Asking questions"},
                {"t": "bullet", "x": "\"Yes\" man / agreeing with what you're "
                 "saying"},
                {"t": "bullet", "x": "\"Wow\" — surprised with the service / "
                 "savings"},
            ]},
            {"heading": "NON-BUYING SIGNS", "lines": [
                {"t": "bullet", "x": "Happy with what they have"},
                {"t": "bullet", "x": "Not having any issues with their "
                 "service"},
                {"t": "bullet", "x": "Talking through screen door / not "
                 "engaged"},
                {"t": "bullet", "x": "Never looked into new services"},
                {"t": "bullet", "x": "Not agreeing with any of the issues"},
                {"t": "bullet", "x": "No questions / one-word answers"},
                {"t": "bullet", "x": "Answering \"no\""},
                {"t": "bullet", "x": "Not surprised about the service"},
            ]},
        ],
    },

    # ---- p21: early objections & rebuttals ------------------------------
    {
        "type": "objections",
        "sidebar": "REBUTTALS",
        "title": "EARLY OBJECTIONS & REBUTTALS",
        "terms": [
            ("OBJECTION", "a verbal barrier between you and the buyer"),
            ("REBUTTAL", "a response to a prospect's objection"),
            ("AIR", "Acknowledge, Ignore, Resume"),
            ("ABC", "Agree, Bullet, Close"),
            ("KISS", "Keep it Short & Simple"),
        ],
        "objections": [
            {"name": "NOT INTERESTED",
             "agree": "\"Yeah, no worries\"",
             "bullet": "\"We're just out here for Customer Service\"",
             "close": "(Go right back into the pitch)"},
            {"name": "DON'T LIKE AT&T",
             "agree": "\"I know, it wasn't the best before — that's why I'm "
                      "here\"",
             "bullet": "\"We've made a lot of updates since then\"",
             "close": "(Go right back into the pitch)"},
            {"name": "NO TIME / BUSY",
             "agree": "\"Yeah, no worries\"",
             "bullet": "\"This'll be quick, I actually have to go too\"",
             "close": "(Go right back into the pitch)"},
            {"name": "YOU WERE JUST HERE",
             "agree": "\"Yeah, I know!\"",
             "bullet": "\"We had a really good response and they sent us back "
                       "out\"",
             "close": "(Go right back into the pitch)"},
            {"name": "GOOD WITH CURRENT SERVICE",
             "agree": "\"Yeah, that's fine, I totally understand\"",
             "bullet": "\"Most neighbors said their bill's been going up / "
                       "internet is slow\"",
             "close": "(Go right back into the pitch)"},
            {"name": "BUSINESS CARD?",
             "agree": "\"For sure!\"",
             "bullet": "\"Unfortunately these are just promotions while we're "
                       "in the area\"",
             "close": "(Go right back into the pitch)"},
        ],
    },

    # ---- p22: closing & late objections ---------------------------------
    {
        "type": "objections",
        "sidebar": "CLOSING",
        "title": "CLOSING & LATE OBJECTIONS",
        "terms": [
            ("ATS", "Assume the Sale"),
            ("MIMS", "Make it Make Sense"),
            ("\"Yes, Yes\" Question", "a close where the customer has a choice "
             "but the only answer is yes (\"morning or afternoon appointment?\")"),
            ("Yes Train", "asking 2–3 questions in a row a customer would "
             "answer yes to"),
            ("Hotspots", "points a customer really cares about (faster speed, "
             "better deal, reaches the whole house)"),
        ],
        "panels": [
            {"title": "LATE OBJECTIONS", "items": [
                "\"Do you have a business card?\"",
                "\"Not right now\"",
                "\"Too expensive\"",
                "\"I don't want to put my card on it right now\"",
                "\"Let me think about it\"",
                "\"Let me talk to my husband / wife before we sign up\"",
            ]},
            {"title": "PROBLEM: THEY ARE NOT CLOSED — SOLUTION",
             "numbered": True, "items": [
                "Agree — \"Yes, I totally understand\" / \"Yes sir, I got "
                "you…\"",
                "Address the issue or concern",
                "Throw in incentives (free equipment, no activation fee, gift "
                "card)",
                "Rehash what the customer is getting",
                "Go right back into the sales process",
            ]},
        ],
    },

    # ---- p23: PPA = APP -------------------------------------------------
    {
        "type": "bands",
        "sidebar": "MINDSET",
        "title": "PPA = APP",
        "subtitle": "Pitch, Pace, Attitude = Applications",
        "intro": "There are only 3 things you can control in the field that "
                 "determine your outcome.",
        "bands": [
            {"name": "PITCH", "sub": "The Ability to Communicate",
             "color": "dark", "bullets": [
                "Memorize script",
                "Project your voice",
                "Pregnant pauses (know when to stop talking and let the "
                "customer engage)"]},
            {"name": "PACE", "sub": "Work Ethic", "color": "accent",
             "bullets": [
                "Hitting 80 houses",
                "Completing 2 laps",
                "Garden Theory"]},
            {"name": "ATTITUDE", "sub": "Results", "color": "primary",
             "bullets": [
                "Let your ATTITUDE determine your RESULTS — never let your "
                "RESULTS determine your ATTITUDE!",
                "Poker face! Smile, eye contact, enthusiasm!",
                "\"1% better everyday\" mentality"]},
        ],
    },

    # ---- p24: dress code — office uniform -------------------------------
    {
        "type": "dresscode",
        "sidebar": "DRESS CODE",
        "title": "DRESS CODE",
        "subtitle": "OFFICE UNIFORM",
        "appearance": "Employees must always present a clean, professional "
                      "appearance. Everyone is expected to be well-groomed and "
                      "wear clean clothing free of holes, tears, see-through "
                      "areas, or other signs of wear.",
        "cards": [
            {"heading": "MEN", "sub": "Business Professional", "lines": [
                {"t": "bullet", "x": "Suit & tie"},
                {"t": "bullet", "x": "Solid-colored dress shirts"},
                {"t": "bullet", "x": "Dress shoes"},
                {"t": "bullet", "x": "Matching belts"},
            ]},
            {"heading": "WOMEN", "sub": "Business Professional", "lines": [
                {"t": "bullet", "x": "Pant suits with blazers"},
                {"t": "bullet", "x": "Modest dress with a blazer"},
                {"t": "bullet", "x": "Closed-toe professional shoes"},
            ]},
        ],
        "images": [
            "resources/dresscode/Office 1.png",
            "resources/dresscode/Office 2.png",
            "resources/dresscode/Office 3.png",
            "resources/dresscode/Office 4.png",
        ],
        "banner": "DRESS LIKE YOU RUN THE PLACE — BECAUSE YOU WILL",
    },

    # ---- p25: dress code — field uniform -------------------------------
    {
        "type": "dresscode",
        "sidebar": "DRESS CODE",
        "title": "DRESS CODE",
        "subtitle": "FIELD UNIFORM",
        "appearance": "Employees must always present a clean, professional "
                      "appearance. Everyone is expected to be well-groomed and "
                      "wear clean clothing free of holes, tears, see-through "
                      "areas, or other signs of wear.",
        "cards": [
            {"heading": "THE FIELD UNIFORM", "lines": [
                {"t": "bullet", "lead": "Tops —",
                 "x": "client shirt / sweatshirt / polo, in client colors"},
                {"t": "bullet", "lead": "Bottoms —",
                 "x": "black or khaki pants"},
                {"t": "bullet", "lead": "Shoes —", "x": "comfortable sneakers"},
            ]},
        ],
        "images": [
            "resources/dresscode/Field 1.png",
            "resources/dresscode/Field 2.png",
            "resources/dresscode/Field 3.png",
            "resources/dresscode/Field 4.png",
        ],
        "not_allowed": [
            {"head": "Tops", "items": ["Random t-shirt / sweatshirt",
                                       "Torn shirts"]},
            {"head": "Bottoms", "items": ["Jeans", "Jeggings", "Skirts",
                                          "Dresses", "Spandex", "Sweats"]},
            {"head": "Shoes", "items": ["Open-toe shoes", "Sandals",
                                        "Flip-flops"]},
        ],
        "banner": "BADGES ALWAYS ON WHILE WORKING",
    },

    # ---- p26: seasonal recommendations --------------------------------
    {
        "type": "seasonal",
        "sidebar": "COME PREPARED",
        "title": "SEASONAL RECOMMENDATIONS",
        "subtitle": "Dress for the day — stay comfortable, stay out longer",
        # always-bring field essentials (full-width band up top)
        "always": {
            "heading": "ALWAYS BRING IN THE FIELD",
            "items": [
                "Water bottle / canteen",
                "Jacket and/or umbrella (just in case)",
                "Snacks",
                "Clipboard",
                "Backpack",
                "30 Day Bootcamp Packet",
                "Pens / notebook",
                "Battery pack charger",
            ],
        },
        "cards": [
            {"heading": "SUMMER", "sub": "Beat the heat and keep pushing",
             "lines": [
                {"t": "bullet", "x": "Sunscreen"},
                {"t": "bullet", "x": "Bug spray"},
                {"t": "bullet", "x": "Water — stay hydrated all day"},
                {"t": "bullet", "x": "Hat"},
                {"t": "bullet", "x": "Sunglasses"},
                {"t": "bullet", "x": "Light, breathable clothing"},
                {"t": "bullet", "x": "Cooling towel / bandana"},
                {"t": "bullet", "x": "Electrolytes"},
            ]},
            {"heading": "WINTER", "sub": "Layer up and stay warm & dry",
             "lines": [
                {"t": "bullet", "x": "Thermals — legs & body"},
                {"t": "bullet", "x": "Double / triple layers on legs & body"},
                {"t": "bullet", "x": "Boots"},
                {"t": "bullet", "x": "Wool socks (double / triple layer)"},
                {"t": "bullet", "x": "Thick gloves"},
                {"t": "bullet", "x": "Pocket warmers"},
                {"t": "bullet", "x": "Earmuffs"},
                {"t": "bullet", "x": "Ski mask"},
            ]},
        ],
    },
]

# Page order: the dress-code pages (office, field) and the field/seasonal
# recommendations move up to sit right after the Suggestions Box page — so
# they land on pages 13, 14 and 15. Everything else keeps its relative order.
_PREP_PAGES = PAGES[-3:]                 # office dress, field dress, seasonal
PAGES = PAGES[:12] + _PREP_PAGES + PAGES[12:-3]
