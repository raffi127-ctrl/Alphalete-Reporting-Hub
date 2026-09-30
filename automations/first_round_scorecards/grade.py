"""Grade one 1st round transcript against the 11-item scorecard.

The scorecard is the one Rafael signed off on in the manual pilot (Sep 22-24):
5 red flags that should NOT happen + 6 must-dos that should. Every answer is
strictly YES / NO -- partly done counts as NOT done (Rafael, 2026-09-22).
Score = % of the 11 items passed. 90+ green, 70-89 yellow, under 70 red.

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

# The script, cut into the portions an interviewer can skip (Rafael,
# 2026-09-30: "skipped portions: 5", each with the script line she skipped).
# Same granularity he counted by hand: the three check-ins are ONE portion,
# the whole wrap-up is ONE. A portion said only in part counts as skipped,
# like the must-dos. Not scored -- it's the list she re-reads before the next
# interview. The line shown is copied from here, never written by the model.
PORTIONS = [
    ("face_to_face", "All interactions with them are face to face, so we do not do "
                     "call center or inside of a retailer type of work."),
    ("management", "Ultimately we want to put someone into a Management role within "
                   "6-8 months to manage their own team and clients."),
    ("pay_entry", "For entry level team members we start with a weekly paycheck, this "
                  "is a performance based-role with an average paycheck from $1000 - "
                  "$1500 plus bonuses and commission."),
    ("pay_assistant", "As soon as someone gets into that assistant manager position "
                      "(within the first 4-6 months) we move to a salary role, "
                      "between 65k - 80k a year."),
    ("pay_executive", "At the Executive Manager position ... we are talking about $250k "
                      "plus bonuses and commission plus the profits from the revenue."),
    ("schedule", "All the positions we are looking to fill in are FULL TIME, IN PERSON, "
                 "DAY SHIFTS. We are talking about a minimum of 40 hours a week, with the "
                 "possibility of working on Saturdays to make more bonuses."),
    ("commute", "Remember that we are located in (CITY), is that a sustainable commute "
                "for you for an everyday job?"),
    ("check_ins", "Does this sound aligned with what you are looking for? / Overall, is "
                  "this a comfortable compensation rate for you? / Is that alright with you?"),
    ("wrap_up", "If you are selected you'll get a phone call before 5pm today from our "
                "recruitment team in order to schedule a 2nd interview. I would recommend "
                "dressing business professional attire for that and bringing a notebook "
                "and pen. If you don't get a phone call it just means we went a "
                "different direction."),
]

SCRIPT = """\
COMPANY BACKGROUND (key lines)
- "The positions we are looking to fill are in-person, full time ... All interactions with them are face to face, so we do not do call center or inside of a retailer type of work."
- "Ultimately we want to put someone into a Management role within 6-8 months to manage their own team and clients." -> then check-in: "Does this sound aligned with what you are looking for?"

PAY STRUCTURE
- "For entry level team members we start with a weekly paycheck, this is a performance based-role with an average paycheck from $1000 - $1500 plus bonuses and commission."
- "As soon as someone gets into that assistant manager position (within the first 4-6 months) we move to a salary role, between 65k - 80k a year."
- "At the Executive Manager position ... we are talking about $250k plus bonuses and commission plus the profits from the revenue."
- check-in: "Overall, is this a comfortable compensation rate for you?"

SCHEDULE
- "All the positions we are looking to fill in are FULL TIME, IN PERSON, DAY SHIFTS. We are talking about a minimum of 40 hours a week, with the possibility of working on Saturdays to make more bonuses. Is that alright with you?"
- "Remember that we are located in (CITY), is that a sustainable commute for you for an everyday job?"

WRAP UP
- "If you are selected you'll get a phone call before 5pm today from our recruitment team in order to schedule a 2nd interview. I would recommend dressing business professional attire for that and bringing a notebook and pen."
- "If you don't get a phone call it just means we went a different direction."
"""

RULES = """\
How to answer each item (strictly YES or NO; partly done = NO):
- retail: YES only if she said the job is inside a retail store.
- base_pay: YES if she offered a base pay, hourly pay or salary for the ENTRY-LEVEL role. "Salary" for the Assistant Manager role is the script wording -- that is NOT a flag.
- nine_to_five: YES if she said the hours are 9 to 5.
- mon_fri: YES if she said Monday to Friday only.
- off_script_pay: YES if any pay number she quoted differs from the script (entry $1,000-1,500 average weekly paycheck, Assistant Manager $65-80k a year, Executive Manager $250k+). NO if she quoted no numbers at all.
- management: YES if she said the goal is a management role within about 6-8 months ("six months" is close enough).
- commute: YES only if she asked whether the commute works for an EVERYDAY job. Asking only about getting to the 2nd interview = NO.
- schedule: YES only if she covered full time, in person / day shifts and the 40 hours (Saturdays for bonuses). Skipped or partial = NO.
- wrap_up: YES only if she said the call comes before 5pm today, business professional attire, notebook and pen, and "if you don't get a call we went a different direction". Missing any = NO.
- check_ins: YES only if she asked the 3 check-in questions (aligned with what you're looking for? / comfortable compensation? / schedule alright?). Missing any = NO.
- pay: YES if she explained the pay for the entry-level role (performance-based weekly paycheck, bonuses and commission). NO if pay was never explained.
Applicants asking indirect questions still count (e.g. "are we going to be on the field?" = asking if it's door to door).
"""

PORTION_KEYS = ", ".join(k for k, _ in PORTIONS)

SYSTEM = f"""You audit 1st round group job interviews (Zoom, recorded by Fathom) for a door-to-door sales company. The interviewer follows a script; you check the transcript against it for the hiring manager, who uses it to coach the interviewer.

The interviewer is the speaker named in the request (the Zoom account name, e.g. "ARS ZOOM 12"). Everyone else is an applicant. Several interviewers can share one Zoom account, so put the interviewer's first name in interviewer_name as she introduces herself ("My name is ___, I'm one of the hiring managers"); leave it empty if she never says it -- never guess. The transcript is machine-made: names and numbers can be misheard, so judge by meaning, not exact words.

THE SCRIPT
{SCRIPT}
{RULES}
For every item write a note of 1-3 sentences in plain English: what she actually said, as a quote with its timestamp (like @12:29), and -- when it falls short -- what the script says instead. If the item never came up, say so. Then 2 or 3 short coaching points for the interviewer: most important first, what to fix and what to keep doing.

Then, for every script portion under "portions" ({PORTION_KEYS}), say whether she said it. said=true only if she covered ALL of it (by meaning, not exact words); partly said or skipped = false. check_ins = all three check-in questions; wrap_up = every piece of the wrap-up. note = one short sentence: what she said instead, with its timestamp, or that it never came up.

Also list the applicants' questions on these topics, each with the interviewer's answer as said (quote + timestamp): door to door / field work, benefits, flexible schedule, is this a scam, hourly pay, working in a specific city. Leave the list empty if none came up.

Plain, simple words -- the readers are not technical.

If the recording is not a 1st round interview (empty, a test, a different kind of meeting, or it stops before the interview really starts), set is_interview to false and explain in not_interview_reason."""

_PORTION_SCHEMA = {"type": "object", "additionalProperties": False,
                   "required": ["said", "note"],
                   "properties": {"said": {"type": "boolean"}, "note": {"type": "string"}}}
_ITEM_SCHEMA = {"type": "object", "additionalProperties": False,
                "required": ["happened", "note"],
                "properties": {"happened": {"type": "boolean"}, "note": {"type": "string"}}}
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["is_interview", "not_interview_reason", "interviewer_name", "applicants",
                 "items", "portions", "coaching", "applicant_questions"],
    "properties": {
        "is_interview": {"type": "boolean"},
        "interviewer_name": {"type": "string"},
        "not_interview_reason": {"type": "string"},
        "applicants": {"type": "array", "items": {"type": "string"}},
        "items": {"type": "object", "additionalProperties": False,
                  "required": [k for k, _, _ in ITEMS],
                  "properties": {k: _ITEM_SCHEMA for k, _, _ in ITEMS}},
        "portions": {"type": "object", "additionalProperties": False,
                     "required": [k for k, _ in PORTIONS],
                     "properties": {k: _PORTION_SCHEMA for k, _ in PORTIONS}},
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
    musts_done, missed: [keys that lost points]}."""
    items = result.get("items") or {}
    passed, red_hit, musts_done, missed = 0, 0, 0, []
    for key, _, kind in ITEMS:
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
    return {"score": round(100 * passed / len(ITEMS)), "passed": passed,
            "red_hit": red_hit, "musts_done": musts_done, "missed": missed}


def skipped(result: Dict) -> List[tuple]:
    """[(key, script line, note)] for each portion she didn't fully say, in
    script order. A result graded before portions existed has none."""
    got = result.get("portions") or {}
    return [(k, line, got[k].get("note") or "") for k, line in PORTIONS
            if k in got and not got[k].get("said")]


def grade(transcript: str, *, interviewer_speaker: str, client=None) -> Dict:
    """Ask the model; returns the parsed JSON answer (see SCHEMA)."""
    import anthropic
    if client is None:
        from automations.brand_audit import credentials
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    body = {"output_config": {"effort": "high",
                              "format": {"type": "json_schema", "schema": SCHEMA}}}
    messages = [{"role": "user", "content":
                 f"Interviewer's speaker name: {interviewer_speaker}\n\nTRANSCRIPT\n{transcript}"}]
    # Passed as extra_body so an older SDK on the runner (Python 3.9) still
    # sends them. On a refusal the API re-runs it on a fallback model.
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=16000, system=SYSTEM, messages=messages,
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={**body, "fallbacks": "default"})
    except anthropic.BadRequestError:
        # the fallback option is the only optional piece -- try once without it
        resp = client.messages.create(model=MODEL, max_tokens=16000, system=SYSTEM,
                                      messages=messages, extra_body=body)
    if resp.stop_reason == "refusal":
        raise RuntimeError("the model declined to grade this transcript")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("the grade was cut off (max_tokens)")
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return json.loads(text)


def questions() -> List[str]:
    return [q for _, q, _ in ITEMS]
