"""Grade one 1st round transcript against the 11-item scorecard.

The scorecard is the one Rafael signed off on in the manual pilot (Sep 22-24):
5 red flags that should NOT happen + 6 must-dos that should. Every answer is
strictly YES / NO -- partly done counts as NOT done (Rafael, 2026-09-22).
Score = % of the 11 items passed, minus half an item for every script
portion said in the wrong words ("incorrect verbiage", Rafael 2026-09-30).
An office whose script leaves something for the 2nd round (pay, schedule,
commute) isn't counted on it: % of the items that apply (FORMATS).
90+ green, 70-89 yellow, under 70 red.

The model only answers the questions; the score is counted here, so it can
never drift from the rule above.
"""
from __future__ import annotations

import json
from typing import Dict, List

MODEL = "claude-opus-5-5"

# (key, question, kind). kind "red" = YES is bad; "must" = YES is good.
ITEMS = [
    ("retail", "Did she say the job is inside a retail store?", "red"),
    ("base_pay", "Did she offer base pay / salary for the ENTRY-LEVEL role?", "red"),
    ("nine_to_five", "Did she say the schedule is 9-5?", "red"),
    ("mon_fri", "Did she say Monday-Friday only?", "red"),
    ("off_script_pay", "Did she quote pay different from the script?", "red"),
    ("management", "Did she talk about the management training program?", "must"),
    ("commute", "Did she check the EVERYDAY commute?", "must"),
    ("schedule", "Did she cover the schedule (full time, in person, day shifts, 40 hrs, Saturdays)?", "must"),
    ("wrap_up", "Did she do the wrap-up script?", "must"),
    ("check_ins", "Did she ask the check-in questions?", "must"),
    ("pay", "Did she explain the pay?", "must"),
]
SHORT = {                      # how a missed item reads in the Slack post
    "retail": "said it's in a retail store",
    "base_pay": "offered base pay for entry level",
    "nine_to_five": "said 9-5",
    "mon_fri": "said Monday-Friday only",
    "off_script_pay": "pay different from the script",
    "management": "management training program",
    "commute": "everyday commute",
    "schedule": "schedule section",
    "wrap_up": "wrap-up script",
    "check_ins": "check-in questions",
    "pay": "explaining the pay",
}

# Each office has its own script (Camila, 2026-10-06: Slack folder "1st ROUNDS
# SCRIPT" in every office channel; PDFs + text in output/1st-round-scripts/).
# Intro, company, management, commute and wrap-up are word for word the same
# in all of them -- only the PAY numbers and the SCHEDULE line change. So an
# office is just those few lines; everything else is shared. An owner with
# no script of their own is graded on Rafael's (the one used since 9/22).
#   mon_fri_ok: the script itself says Monday-Friday with no Saturdays, so
#               saying it is NOT the "Monday-Friday only" red flag.
_STD_40 = ("All the positions we are looking to fill in are FULL TIME, IN PERSON, DAY "
           "SHIFTS. We are talking about a minimum of 40 hours a week, with the "
           "possibility of working on Saturdays to make more bonuses.")
_STD_PAY = {"entry": "$900 - $1200", "assistant": "65k - 75k",
            "executive": "between $110k - $150k plus bonuses and commission and the "
                         "profits from the team", "executive_short": "$110-150k"}
DEFAULT = {"entry": "$1000 - $1500", "assistant": "65k - 80k",
           "executive": "$250k plus bonuses and commission plus the profits from the revenue",
           "executive_short": "$250k", "schedule": _STD_40,
           "schedule_check": "Is that alright with you?", "mon_fri_ok": False}
OFFICES = {
    "Rafael Hidalgo": {},
    "Atef Choudhury": dict(_STD_PAY),
    "Aya Al-Khafaji": dict(_STD_PAY),
    "Cyrus Wade": dict(_STD_PAY),
    "Jamis Garay": dict(_STD_PAY),
    "Kash Rai": dict(_STD_PAY),
    "Khalil Mansour": dict(_STD_PAY),
    "Max Aden": dict(_STD_PAY),
    "Isaiah Revelle": dict(_STD_PAY, schedule=(
        "All the positions we are looking to fill in are FULL TIME, IN PERSON, DAY "
        "SHIFTS. We are talking about an 11am to 8pm schedule with the possibility of "
        "working on Saturdays 9 to 4 to make more bonuses.")),
    "Haytham Nagi": dict(_STD_PAY, schedule_check="Would that schedule work for you?",
                         schedule="The schedule is Monday through Friday, from 10:30AM "
                                  "to 8:30PM, Saturdays 10:00AM to 7:00PM."),
    "Jacob Dover": dict(_STD_PAY, schedule_check="Would that schedule work for you?",
                        schedule="The schedule is Monday through Friday, from 9:00AM to "
                                 "8:00PM, Saturdays 9:00AM to 7:00PM."),
    "Rashad Reed": dict(_STD_PAY, schedule_check="Would that schedule work for you?",
                        schedule="The schedule is Monday through Friday, from 11:00 AM "
                                 "to 8:30 PM and Saturdays 9:00 AM to 4:00 PM."),
    "Nii Teiko": dict(_STD_PAY, schedule_check="Would that schedule work for you?",
                      mon_fri_ok=True,
                      schedule="The schedule is Monday through Friday, from 10:30 to 8pm. "
                               "All of the positions we're currently hiring for are FULL "
                               "TIME, IN PERSON, DAY SHIFTS, with a minimum of 40 hours "
                               "per week."),
    # 2026-10-07: the offices Eve wasn't in the channel of (Camila added her)
    "Blue Mendoza": dict(_STD_PAY),
    "Christopher Williams": dict(_STD_PAY),
    "Cody Cannon": dict(_STD_PAY),
    "JC Pascual": dict(_STD_PAY),
    "Joe Logan": dict(_STD_PAY),
    "Steve McElwee": dict(_STD_PAY),
    "David Robinson": dict(_STD_PAY, schedule="The schedule is Monday through Friday "
                                              "11:00AM to 8:00PM, Saturdays 9:00AM to "
                                              "6:00PM."),
    "Juan Botero": dict(_STD_PAY, schedule_check="Would that schedule work for you?",
                        schedule="The schedule is Monday through Friday, from 10:00AM to "
                                 "8:30PM, Saturdays 9:00AM to 6:00PM."),
    # 2026-10-09: Tre's new script (Eve) -- no pay, 40 hrs + Saturdays, North Houston
    "Tre Mitchell": {"format": "tre"},
    # Scripts shaped differently from Rafael's -- see FORMATS below.
    **{o: {"format": "profits"} for o in ("Eveliz Wright", "Colten Wright", "Jairo Ruiz",
                                         "Drew Tepper", "George Delgado", "Samuel Acay")},
    **{o: {"format": "highline"} for o in ("Roshan Ahmad", "Ryan McSpadden")},
    "Ellen Dent": {"format": "ellen", "schedule_check": "Is that alright with you?",
                   "schedule": "So regarding schedule, we work Mondays through Fridays "
                               "8:00 to 6:00, Saturdays 9:00 to 6:00."},
    "Carlos Hidalgo": {"format": "carlos", "entry": "$1200 - $2000", "assistant": "150k",
                       "executive": "$250k a year", "executive_short": "$250k"},
}
# ZOOMS INFO spells some owners differently from the script's file name
OWNER_ALIASES = {"raf hidalgo": "Rafael Hidalgo", "nii tagoe": "Nii Teiko",
                 "max amed": "Max Aden", "geoge delgado": "George Delgado",
                 "joseph logan": "Joe Logan", "lamar mitchell": "Tre Mitchell"}

# Offices whose script isn't Rafael's shape (Camila's PDFs, 2026-10-07). Each
# one says which scorecard items its script doesn't have ("na": not counted,
# so an interviewer isn't marked down for a part her script leaves to the 2nd
# round), which script portions it drops, the lines that read differently, and
# the rules that change. Score = % of the items that DO apply.
#   profits  -- Profits Management (Eveliz, Colten, Jairo, Drew, George, Samuel):
#               no pay in the 1st round, the 2nd round is booked on the call.
#   highline -- Highline Management (Roshan, Ryan): pay, hours and commute all
#               wait for the 2nd round.
#   ellen    -- Ellen's: pay only if they ask ($1,000-2,500/wk), own hours.
#   tre      -- Tre's (2026-10-09): pay waits for the 2nd round, standard 40 hrs
#               + Saturdays, North Houston, wrap-up without attire/notebook.
#   carlos   -- Carlos': own pay numbers, no schedule or commute in the 1st round,
#               2nd round tomorrow in person in Grand Prairie.
_PROFITS_WRAP = ("The second interview will be in person, so you can come to the office, "
                 "meet the manager... Would you like to move forward with a second "
                 "interview? Are you available tomorrow or the day after? ... Which time "
                 "works best for you? ... You will receive all the important information, "
                 "including the office address and interview details, by email and text "
                 "message.")
_NO_PAY_RULE = ("YES if she quoted any pay number at all -- this script leaves the pay "
                "for the 2nd round. NO if she quoted none.")
FORMATS = {
    "profits": {
        "na": {"pay"},
        "drop": {"pay_entry", "pay_assistant", "pay_executive"},
        "lines": {
            "face_to_face": "All interactions with them are face to face, so we do not do "
                            "call center work or anything like that.",
            "management": "Ultimately we want to put someone into that management role "
                          "within 6 months to oversee one of our big clients.",
            "commute": "Remember that we are located in CITY (send the address via zoom "
                       "chat), is that a sustainable commute for you for an everyday job?",
            "check_ins": "Does this sound aligned with what you are looking for? / Is that "
                         "alright with you?",
            "wrap_up": _PROFITS_WRAP,
        },
        "keys": {
            "face_to_face": "face to face with clients / not a call center",
            "check_ins": "both questions",
            "wrap_up": "offering the 2nd interview, booking a day and time for it, and "
                       "that the address and details come by email and text",
        },
        "rules": {
            "off_script_pay": _NO_PAY_RULE,
            "management": "YES if she said the goal is a management role within about 6 "
                          "months.",
            "wrap_up": "YES only if she offered the 2nd interview, booked a day and time "
                       "for it on the call, and said the details come by email and text. "
                       "Missing any = NO.",
            "check_ins": "YES only if she asked both check-in questions (aligned with what "
                         "you're looking for? / schedule alright?). Missing any = NO.",
        },
    },
    "highline": {
        "na": {"pay", "schedule", "commute"},
        "drop": {"pay_entry", "pay_assistant", "pay_executive", "schedule", "commute"},
        "lines": {
            "face_to_face": "We don't do any cold calls, blast emails, or snail mail. "
                            "Everything we do is person to person, face to face.",
            "management": "We are definitely looking for someone who wants to grow into "
                          "higher level roles... in order to get to that management "
                          "position, we only promote from within.",
            "check_ins": "Is the face to face side of customer service, sales, and "
                         "marketing, something you would be comfortable doing? / Is "
                         "management something that aligns with your goals?",
            "wrap_up": "If we are moving forward with your profile, we will be reaching out "
                       "today before 5 p.m. in order to book this second interview with "
                       "you... have your phone on you... If you don't receive a call/text "
                       "back it does mean we decided to move in a different direction.",
        },
        "keys": {
            "face_to_face": "everything is person to person, face to face (no cold calls)",
            "management": "growing into management, promoting from within",
            "check_ins": "both questions",
            "wrap_up": "the call or text before 5pm today to book the 2nd interview, and "
                       "'if you don't hear back we went a different direction'",
        },
        "rules": {
            "off_script_pay": _NO_PAY_RULE,
            "management": "YES if she said they promote from within and the goal is to grow "
                          "into management.",
            "wrap_up": "YES only if she said they reach out before 5pm today to book the 2nd "
                       "interview and that no call/text means a different direction. "
                       "Missing any = NO.",
            "check_ins": "YES only if she asked both (comfortable with the face to face "
                         "side? / does management align with your goals?). Missing any = NO.",
        },
    },
    "ellen": {
        "na": {"pay"},
        "drop": {"face_to_face", "pay_entry", "pay_assistant", "pay_executive"},
        "lines": {
            "management": "We're looking for someone that can start off entry-level and be "
                          "trained into a management role within the first six months of "
                          "being with us.",
            "check_ins": "Does this sound aligned with what you are looking for? / Is that "
                         "alright with you?",
        },
        "keys": {"check_ins": "both questions"},
        "rules": {
            "off_script_pay": "YES if any pay number she quoted differs from the script (paid "
                              "training, then performance-based, averaging $1,000-2,500 a "
                              "week, uncapped -- said only if they ask). NO if she quoted no "
                              "numbers at all.",
            "management": "YES if she said the goal is a management role within about 6 "
                          "months.",
            "check_ins": "YES only if she asked both check-in questions (aligned with what "
                         "you're looking for? / schedule alright?). Missing any = NO.",
        },
    },
    "tre": {
        "na": {"pay"},
        "drop": {"pay_entry", "pay_assistant", "pay_executive"},
        "lines": {
            "face_to_face": "All interactions with them are face to face.",
            "commute": "Remember that we are located in North Houston, is that a "
                       "sustainable commute for you for an everyday job?",
            "check_ins": "Does this sound aligned with what you are looking for? / Is that "
                         "alright with you?",
            "wrap_up": "If you are selected you'll get a phone call before 5pm today from our "
                       "recruitment team in order to schedule a 2nd interview. If you don't "
                       "get a phone call it just means we went a different direction.",
        },
        "keys": {
            "face_to_face": "all interactions with clients are face to face",
            "check_ins": "both questions",
            "wrap_up": "the call before 5pm today to schedule the 2nd interview, and 'if you "
                       "don't get a call we went a different direction'",
        },
        "rules": {
            "off_script_pay": _NO_PAY_RULE,
            "wrap_up": "YES only if she said the call comes before 5pm today to schedule the "
                       "2nd interview and \"if you don't get a call we went a different "
                       "direction\". Missing any = NO.",
            "check_ins": "YES only if she asked both check-in questions (aligned with what "
                         "you're looking for? / schedule alright?). Missing any = NO.",
        },
    },
    "carlos": {
        "na": {"schedule", "commute"},
        "drop": {"face_to_face", "schedule", "commute"},
        "lines": {
            "management": "Ultimately we want to put someone into that management role "
                          "within 6 months to oversee one of our big clients.",
            "pay_entry": "For entry level team members and account managers on average they "
                         "make about $1200 to $2000 a week and people get paid weekly. Which "
                         "translates into $57k - $96k a year just starting off.",
            "pay_assistant": "As soon as someone gets into that assistant manager position "
                             "they make about 150k a year.",
            "pay_executive": "At the management position it is $250k a year.",
            "check_ins": "Overall, is that a comfortable compensation rate for you? / "
                         "Overall is this an industry that aligns with what you're looking "
                         "for?",
            "wrap_up": "We are conducting these interviews tomorrow in person at our Grand "
                       "Prairie office. If you were to be selected would you be able to make "
                       "it? ... I would recommend dressing business professional for that and "
                       "bringing a notebook and pen. If you are selected you'll get a phone "
                       "call before 5pm. If you don't get a phone call it just means we went "
                       "a different direction.",
        },
        "keys": {
            "pay_entry": "the $1,200-2,000 weekly average",
            "pay_assistant": "the $150k for assistant manager",
            "check_ins": "both questions",
            "wrap_up": "the 2nd interview tomorrow in person in Grand Prairie, business "
                       "professional attire, notebook and pen, the call before 5pm, and "
                       "'if you don't get a call we went a different direction'",
        },
        "rules": {
            "base_pay": "YES if she promised a fixed base pay, hourly pay or salary for the "
                        "ENTRY-LEVEL role. The script's answer when asked -- \"there is "
                        "potential for a base salary based on background and experience, "
                        "plus bonuses and commission\" -- is NOT a flag.",
            "off_script_pay": "YES if any pay number she quoted differs from the script "
                              "(entry $1,200-2,000 a week = $57-96k a year, Assistant Manager "
                              "$150k, management $250k). NO if she quoted no numbers at all.",
            "management": "YES if she said the goal is a management role within about 6 "
                          "months.",
            "wrap_up": "YES only if she said the 2nd interview is tomorrow in person in Grand "
                       "Prairie, business professional attire, notebook and pen, the call "
                       "before 5pm, and no call = different direction. Missing any = NO.",
            "check_ins": "YES only if she asked both (comfortable compensation? / does the "
                         "industry align with what you're looking for?). Missing any = NO.",
            "pay": "YES if she explained the pay for the entry-level role (the $1,200-2,000 "
                   "weekly average, paid weekly). NO if pay was never explained.",
        },
    },
}


def office_for(owner: str) -> str:
    """The OFFICES key for an owner as ZOOMS INFO writes it ('Raf Hidalgo\\n2nd
    funnel', 'Nii Tagoe'), or '' when that office has no script of its own."""
    lines = (owner or "").strip().splitlines()
    first = " ".join(lines[0].lower().split()) if lines else ""
    if first in OWNER_ALIASES:
        return OWNER_ALIASES[first]
    return next((k for k in OFFICES if k.lower() == first), "")


def _money(x: str) -> str:
    """'$900 - $1200' -> '$900-1,200', '65k - 75k' -> '$65-75k' (for the rules)."""
    if "-" not in x:                                    # one number ('150k')
        return "$" + x.strip().lstrip("$")
    a, b = [p.strip().lstrip("$") for p in x.split("-")]
    if a.endswith("k") and b.endswith("k"):
        return f"${a[:-1]}-{b}"
    return f"${int(a):,}-{int(b):,}"


VERBIAGE_COST = 0.5                 # items lost per portion in the wrong words


def build(office: str = "") -> Dict:
    """The script portions, prompt pieces and system prompt for one office
    ('' or an office with no script of its own = Rafael's)."""
    office = office if office in OFFICES else ""
    o = {**DEFAULT, **OFFICES.get(office, {})}
    sched_bits = ("day shifts, 40 hours a week and Saturdays" if o["schedule"] == _STD_40
                  else "the days and hours of this schedule")
    # The script, cut into the portions an interviewer can skip (Rafael,
    # 2026-09-30: "skipped portions: 5", each with the script line she skipped).
    # Same granularity he counted by hand: the three check-ins are ONE portion,
    # the whole wrap-up is ONE. A portion said only in part counts as skipped,
    # like the must-dos. Not scored -- it's the list she re-reads before the
    # next interview. The line shown is copied from here, never written by the model.
    portions = [
        ("face_to_face", "All interactions with them are face to face, so we do not do "
                         "call center or inside of a retailer type of work."),
        ("management", "Ultimately we want to put someone into a Management role within "
                       "6-8 months to manage their own team and clients."),
        ("pay_entry", "For entry level team members we start with a weekly paycheck, this "
                      "is a performance based-role with an average paycheck from "
                      f"{o['entry']} plus bonuses and commission."),
        ("pay_assistant", "As soon as someone gets into that assistant manager position "
                          "(within the first 4-6 months) we move to a salary role, "
                          f"between {o['assistant']} a year."),
        ("pay_executive", "At the Executive Manager position ... we are talking about "
                          f"{o['executive']}."),
        ("schedule", o["schedule"]),
        ("commute", "Remember that we are located in (CITY), is that a sustainable commute "
                    "for you for an everyday job?"),
        ("check_ins", "Does this sound aligned with what you are looking for? / Overall, is "
                      f"this a comfortable compensation rate for you? / {o['schedule_check']}"),
        ("wrap_up", "If you are selected you'll get a phone call before 5pm today from our "
                    "recruitment team in order to schedule a 2nd interview. I would recommend "
                    "dressing business professional attire for that and bringing a notebook "
                    "and pen. If you don't get a phone call it just means we went a "
                    "different direction."),
    ]
    fmt = FORMATS.get(o.get("format", ""), {})
    if fmt:
        portions = [(k, fmt.get("lines", {}).get(k, text)) for k, text in portions
                    if k not in fmt.get("drop", ())]
    line = dict(portions)
    if not fmt:
        script = f"""\
COMPANY BACKGROUND (key lines)
- "The positions we are looking to fill are in-person, full time ... {line['face_to_face']}"
- "{line['management']}" -> then check-in: "Does this sound aligned with what you are looking for?"

PAY STRUCTURE
- "{line['pay_entry']}"
- "{line['pay_assistant']}"
- "{line['pay_executive']}"
- check-in: "Overall, is this a comfortable compensation rate for you?"

SCHEDULE
- "{o['schedule']} {o['schedule_check']}"
- "{line['commute']}"

WRAP UP
- "If you are selected you'll get a phone call before 5pm today from our recruitment team in order to schedule a 2nd interview. I would recommend dressing business professional attire for that and bringing a notebook and pen."
- "If you don't get a phone call it just means we went a different direction."
"""
    else:
        # a differently shaped script: its key lines in order, and what it
        # leaves for the 2nd round (those items aren't counted)
        later = [SHORT[k] for k, _, _ in ITEMS if k in fmt["na"]]
        script = ("KEY LINES (in order)\n"
                  + "".join(f'- "{text}"\n' for _, text in portions)
                  + f"This script does NOT cover these in the 1st round: {', '.join(later)}.\n")
    mon_fri = ("NO -- this office's script itself says Monday to Friday, so "
               "saying it is following the script." if o["mon_fri_ok"] else
               "YES if she said Monday to Friday only.")
    sched_rule = ("YES only if she covered full time, in person / day shifts and the 40 "
                  "hours (Saturdays for bonuses)" if o["schedule"] == _STD_40 else
                  "YES only if she covered the schedule as the script says it (the days "
                  "and the hours)")
    rule = {
        "retail": "YES only if she said the job is inside a retail store.",
        "base_pay": "YES if she offered a base pay, hourly pay or salary for the "
                    "ENTRY-LEVEL role. \"Salary\" for the Assistant Manager role is the "
                    "script wording -- that is NOT a flag.",
        "nine_to_five": "YES if she said the hours are 9 to 5.",
        "mon_fri": mon_fri,
        "off_script_pay": "YES if any pay number she quoted differs from the script (entry "
                          f"{_money(o['entry'])} average weekly paycheck, Assistant Manager "
                          f"{_money(o['assistant'])} a year, Executive Manager "
                          f"{o['executive_short']}+). NO if she quoted no numbers at all.",
        "management": "YES if she said the goal is a management role within about 6-8 "
                      "months (\"six months\" is close enough).",
        "commute": "YES only if she asked whether the commute works for an EVERYDAY job. "
                   "Asking only about getting to the 2nd interview = NO.",
        "schedule": f"{sched_rule}. Skipped or partial = NO.",
        "wrap_up": "YES only if she said the call comes before 5pm today, business "
                   "professional attire, notebook and pen, and \"if you don't get a call we "
                   "went a different direction\". Missing any = NO.",
        "check_ins": "YES only if she asked the 3 check-in questions (aligned with what "
                     "you're looking for? / comfortable compensation? / schedule alright?). "
                     "Missing any = NO.",
        "pay": "YES if she explained the pay for the entry-level role (performance-based "
               "weekly paycheck, bonuses and commission). NO if pay was never explained.",
    }
    rule.update(fmt.get("rules", {}))
    na = set(fmt.get("na", ()))
    for k in na:
        rule[k] = ("NO -- this office's script leaves it for the 2nd round, so it isn't "
                   "counted. Note: \"Not in this office's 1st round script.\"")
    rules = ("How to answer each item (strictly YES or NO; partly done = NO):\n"
             + "".join(f"- {k}: {rule[k]}\n" for k, _, _ in ITEMS)
             + "Applicants asking indirect questions still count (e.g. \"are we going to "
               "be on the field?\" = asking if it's door to door).\n")
    # What makes a portion "said" at all. Missing one of these = skipped; all of
    # them there but the rest dropped or worded differently = incorrect verbiage.
    # (9/30 first run: the right $65-80k without "within 4-6 months" came back
    # as a skip -- Rafael counts that as said, just not word for word.)
    key_pieces = {
        "face_to_face": "face to face with clients / not a call center or retail job",
        "management": "a management role, with a time frame",
        "pay_entry": f"a weekly, performance-based paycheck with the {_money(o['entry'])} average",
        "pay_assistant": f"the {_money(o['assistant'])} salary for assistant manager",
        "pay_executive": f"the {o['executive_short']} for the top position",
        "schedule": sched_bits,
        "commute": "asking if the commute works for an EVERYDAY job",
        "check_ins": "each of the three questions",
        "wrap_up": "the call before 5pm today, business professional attire, notebook and "
                   "pen, and 'if you don't get a call we went a different direction'",
    }
    key_pieces.update(fmt.get("keys", {}))
    key_pieces = {k: key_pieces[k] for k, _ in portions}
    portion_keys = "\n".join(f"- {k}: {key_pieces[k]}" for k, _ in portions)
    whose = (f"This interview is for {office}'s office: grade it against THEIR script "
             "below (the pay numbers and the schedule are that office's own).\n\n"
             if office else "")
    system = f"""You audit 1st round group job interviews (Zoom, recorded by Fathom) for a door-to-door sales company. The interviewer follows a script; you check the transcript against it for the hiring manager, who uses it to coach the interviewer.

The interviewer is the speaker named in the request (the Zoom account name, e.g. "ARS ZOOM 12"). Everyone else is an applicant. Several interviewers can share one Zoom account, so put the interviewer's first name in interviewer_name as she introduces herself ("My name is ___, I'm one of the hiring managers"); leave it empty if she never says it -- never guess. The transcript is machine-made: names and numbers can be misheard, so judge by meaning, not exact words.

{whose}THE SCRIPT
{script}
{rules}
For every item write a note of 1-3 sentences in plain English: what she actually said, as a quote with its timestamp (like @12:29), and -- when it falls short -- what the script says instead. If the item never came up, say so. Then 2 or 3 short coaching points for the interviewer: most important first, what to fix and what to keep doing.

Then list in skipped_portions every script portion she did not say the way the script says it, by its key, with a kind. Each portion's KEY pieces:
{portion_keys}
Kinds:
- skipped: she never said it, or left out one of its KEY pieces.
- incorrect_verbiage: every KEY piece is there, but something else in the portion is wrong or left out -- a different number, time frame or title, or a detail of the script line dropped (e.g. "six months" for "6-8 months", "management role" for "Executive Manager", the assistant manager salary without "within the first 4-6 months"). Ordinary rephrasing that keeps every fact of the line is NOT incorrect verbiage: leave it off the list.
note = one short sentence: for skipped, what she said instead or that it never came up; for incorrect_verbiage, her exact words as a quote. Always with the timestamp. Empty list if she said every portion right.

Also list the applicants' questions on these topics, each with the interviewer's answer as said (quote + timestamp): door to door / field work, benefits, flexible schedule, is this a scam, hourly pay, working in a specific city. Leave the list empty if none came up.

Plain, simple words -- the readers are not technical.

If the recording is not a 1st round interview (empty, a test, a different kind of meeting, or it stops before the interview really starts), set is_interview to false and explain in not_interview_reason."""
    return {"portions": portions, "script": script, "rules": rules,
            "key_pieces": key_pieces, "system": system, "na": na}


# The default (Rafael's script) -- what an office with no script is graded on
_DEFAULT = build()
PORTIONS = _DEFAULT["portions"]
SCRIPT = _DEFAULT["script"]
RULES = _DEFAULT["rules"]
KEY_PIECES = _DEFAULT["key_pieces"]
SYSTEM = _DEFAULT["system"]

_ITEM_SCHEMA = {"type": "object", "additionalProperties": False,
                "required": ["happened", "note"],
                "properties": {"happened": {"type": "boolean"}, "note": {"type": "string"}}}
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["is_interview", "not_interview_reason", "interviewer_name", "applicants",
                 "items", "skipped_portions", "coaching", "applicant_questions"],
    "properties": {
        "is_interview": {"type": "boolean"},
        "interviewer_name": {"type": "string"},
        "not_interview_reason": {"type": "string"},
        "applicants": {"type": "array", "items": {"type": "string"}},
        "items": {"type": "object", "additionalProperties": False,
                  "required": [k for k, _, _ in ITEMS],
                  "properties": {k: _ITEM_SCHEMA for k, _, _ in ITEMS}},
        # a list of keys, not one yes/no object per portion: nine more nested
        # objects made the API reject the schema ("compiled grammar is too
        # large", 2026-09-30)
        "skipped_portions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["portion", "kind", "note"],
            "properties": {"portion": {"type": "string", "enum": [k for k, _ in PORTIONS]},
                           "kind": {"type": "string",
                                    "enum": ["skipped", "incorrect_verbiage"]},
                           "note": {"type": "string"}}}},
        "coaching": {"type": "array", "items": {"type": "string"}},
        "applicant_questions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["topic", "question", "answer"],
            "properties": {"topic": {"type": "string"}, "question": {"type": "string"},
                           "answer": {"type": "string"}}}},
    },
}


def score(result: Dict) -> Dict:
    """Count the score from the model's answers -> {score, passed, red_hit,
    musts_done, verbiage, missed: [keys that lost points]}."""
    items = result.get("items") or {}
    na = build(result.get("script_office") or "")["na"]
    counted = [(k, q, kind) for k, q, kind in ITEMS if k not in na]
    passed, red_hit, musts_done, missed = 0, 0, 0, []
    for key, _, kind in counted:
        happened = bool((items.get(key) or {}).get("happened"))
        ok = (not happened) if kind == "red" else happened
        if kind == "red" and happened:
            red_hit += 1
        if kind == "must" and happened:
            musts_done += 1
        if ok:
            passed += 1
        else:
            missed.append(key)
    wrong_words = len(verbiage(result))
    pts = max(0.0, passed - VERBIAGE_COST * wrong_words)
    # items the office's script leaves for the 2nd round aren't counted either way
    return {"score": round(100 * pts / len(counted)), "passed": passed,
            "red_hit": red_hit, "musts_done": musts_done, "verbiage": wrong_words,
            "missed": missed, "na": sorted(na),
            "n_red": sum(kind == "red" for _, _, kind in counted),
            "n_must": sum(kind == "must" for _, _, kind in counted)}


def _gaps(result: Dict, kind: str) -> List[tuple]:
    """[(key, script line, note)] for the portions of that kind, in script
    order (a portion named twice counts once, skipped wins). A result graded
    before portions existed has none; one graded before verbiage existed has
    only skips."""
    got: Dict[str, tuple] = {}
    for g in result.get("skipped_portions") or []:
        k, gk = g.get("portion"), g.get("kind") or "skipped"
        if k not in got or gk == "skipped":
            got[k] = (gk, g.get("note") or "")
    portions = build(result.get("script_office") or "")["portions"]
    return [(k, line, got[k][1]) for k, line in portions
            if k in got and got[k][0] == kind]


def skipped(result: Dict) -> List[tuple]:
    return _gaps(result, "skipped")


def verbiage(result: Dict) -> List[tuple]:
    """Portions said in full but in the wrong words -- each costs half an item."""
    return _gaps(result, "incorrect_verbiage")


def grade(transcript: str, *, interviewer_speaker: str, owner: str = "",
          client=None) -> Dict:
    """Ask the model; returns the parsed JSON answer (see SCHEMA) plus
    script_office = whose script it was graded on ('' = the default one)."""
    import anthropic
    if client is None:
        from automations.brand_audit import credentials
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    office = office_for(owner)
    system = build(office)["system"]
    body = {"output_config": {"effort": "high",
                              "format": {"type": "json_schema", "schema": SCHEMA}}}
    messages = [{"role": "user", "content":
                 f"Interviewer's speaker name: {interviewer_speaker}\n\nTRANSCRIPT\n{transcript}"}]
    # Passed as extra_body so an older SDK on the runner (Python 3.9) still
    # sends them. On a refusal the API re-runs it on a fallback model.
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=16000, system=system, messages=messages,
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={**body, "fallbacks": "default"})
    except anthropic.BadRequestError:
        # the fallback option is the only optional piece -- try once without it
        resp = client.messages.create(model=MODEL, max_tokens=16000, system=system,
                                      messages=messages, extra_body=body)
    if resp.stop_reason == "refusal":
        raise RuntimeError("the model declined to grade this transcript")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("the grade was cut off (max_tokens)")
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    result = json.loads(text)
    result["script_office"] = office
    return result


def questions() -> List[str]:
    return [q for _, q, _ in ITEMS]
