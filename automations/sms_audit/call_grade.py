"""Grade one booking call against the quick-pitch scorecard.

The same shape as first_round_scorecards/grade.py, one step earlier in the
pipeline: that grades the 1st round interview, this grades the call that
books it. Strictly YES / NO per item, partly done counts as NOT done, score
= % of the items that apply.

THE ITEMS ARE NOT SIGNED OFF YET. The interview scorecard's items were
agreed with Rafael in a manual pilot before anything ran; these are the
draft in resources/recruiting-context/booking-call-rubric-DRAFT.md and
should get the same treatment before a number goes in front of anybody.
Until then this is an analysis tool, not a scorecard.

WHAT THE MODEL IS AND IS NOT ASKED. It answers the questions and quotes the
line it answered from; the score is counted here, so it cannot drift from
the rule above. It is never asked who is speaking -- the recordings are
two-track and call_transcribe already knows. [[project_ringover_call_audit]]

TONE IS NOT GRADED. SEE is smile / eye contact / enthusiasm, and on a phone
call eye contact does not exist while the other two live in the voice, not
the words. A transcript cannot carry them, so asking a text model to judge
"warmth" invents a number. If tone is to be graded it needs the audio.
"""
from __future__ import annotations  # Lucy runs Python 3.9 -- keep lazy

import json
from typing import Dict, List

MODEL = "claude-opus-5-5"

# (key, question, kind). "red" = YES is bad, "must" = YES is good.
ITEMS = [
    ("retail", "Did they say the job is a retail position or inside a "
               "store?", "red"),
    ("base_pay", "Did they offer base pay or a salary for the entry-level "
                 "role?", "red"),
    ("quoted_pay", "Did they quote any specific pay figure on this call?",
     "red"),
    ("nine_to_five", "Did they say the schedule is 9-5, or Monday to Friday "
                     "only?", "red"),
    ("unsure", "Did they say they did not know or were not sure about "
               "something the applicant asked?", "red"),
    ("wrong_place", "Did they name a city, address or office location?",
     "red"),

    ("identity", "Did they confirm they were speaking to the right person "
                 "by name?", "must"),
    ("permission", "Did they ask whether the applicant had a minute to talk "
                   "before pitching?", "must"),
    ("named_role", "Did they say which role the applicant applied for?",
     "must"),
    ("named_company", "Did they say the name of the company?", "must"),
    ("personalised", "Did they refer to something specific from this "
                     "applicant's own resume or background, beyond saying "
                     "they applied?", "must"),
    ("two_times", "Did they offer two specific times to choose between?",
     "must"),
    ("email_back", "Did they read the email address back, spell it, or ask "
                   "the applicant to confirm it?", "must"),
    ("what_next", "Did they say what would happen next -- a confirmation "
                  "text, an email, or when the Zoom link would arrive?",
     "must"),
    ("urgency", "Did they give a reason to take the sooner slot rather than "
                "a later one?", "must"),
    ("booked", "Was an interview time actually agreed on this call?",
     "must"),
]

SHORT = {
    "retail": "called it a retail job",
    "base_pay": "offered base pay for entry level",
    "quoted_pay": "quoted pay on the booking call",
    "nine_to_five": "said 9-5 or Monday-Friday",
    "unsure": "did not know the answer",
    "wrong_place": "named a location",
    "identity": "check who you are speaking to",
    "permission": "ask if they have a minute",
    "named_role": "say which role they applied for",
    "named_company": "say the company name",
    "personalised": "use something from their resume",
    "two_times": "offer two specific times",
    "email_back": "read the email back",
    "what_next": "say what happens next",
    "urgency": "give a reason to take the sooner slot",
    "booked": "get a time agreed",
}

SYSTEM = """You grade one recruiting BOOKING CALL: a short outbound call whose
only job is to book the applicant into a 1st round Zoom interview.

The transcript is already speaker-separated and reliable: lines marked "Us"
are the recruiter, lines marked "Them" are the applicant. Never re-interpret
who is speaking.

The approved pitch runs roughly: confirm who you are speaking to, say who you
are, say you are calling about the application they submitted, ask if they
have a quick minute, name the role, offer two specific times, confirm the
email address, and say a confirmation text and email with the Zoom link will
follow.

Answer every question strictly YES or NO about what the RECRUITER did.
Partly done counts as NO. If a question is about something the recruiter
never touched, answer NO. For every YES, quote the exact line from the
transcript that made you answer YES, and give its timestamp as shown.

Do not judge tone, warmth, enthusiasm or friendliness: you are reading a
transcript and cannot hear the call. Only answer what the words show."""

_ITEM = {"type": "object", "additionalProperties": False,
         "required": ["happened", "quote", "at"],
         "properties": {"happened": {"type": "boolean"},
                        "quote": {"type": "string"},
                        "at": {"type": "string"}}}
SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["items"],
          "properties": {
              "items": {"type": "object", "additionalProperties": False,
                        "required": [k for k, _, _ in ITEMS],
                        "properties": {k: _ITEM for k, _, _ in ITEMS}}}}


def score(result: Dict) -> Dict:
    """% of items passed, plus the parts a coach needs.

    Counted here and never by the model, so the number cannot drift from
    the rule. Mirrors first_round_scorecards.grade.score()."""
    items = result.get("items") or {}
    passed, red_hit, musts_done, missed, flags = 0, 0, 0, [], []
    for key, _q, kind in ITEMS:
        happened = bool((items.get(key) or {}).get("happened"))
        ok = (not happened) if kind == "red" else happened
        if kind == "red" and happened:
            red_hit += 1
            flags.append(key)
        if kind == "must" and happened:
            musts_done += 1
        if ok:
            passed += 1
        else:
            missed.append(key)
    return {"score": round(100.0 * passed / len(ITEMS)),
            "passed": passed, "red_hit": red_hit, "musts_done": musts_done,
            "missed": missed, "flags": flags, "n": len(ITEMS)}


def questions() -> List[str]:
    return [q for _k, q, _kind in ITEMS]


def _prompt() -> str:
    lines = ["Answer each of these about the RECRUITER:"]
    for key, q, kind in ITEMS:
        lines.append("  {} ({}): {}".format(key, kind, q))
    return "\n".join(lines)


def grade(transcript: str, client=None, model: str = MODEL) -> Dict:
    """The model's answers for one transcript (see SCHEMA)."""
    import anthropic
    if client is None:
        from automations.brand_audit import credentials
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    body = {"output_config": {"format": {"type": "json_schema",
                                         "schema": SCHEMA}}}
    messages = [{"role": "user", "content":
                 "{}\n\nTRANSCRIPT\n{}".format(_prompt(), transcript)}]
    resp = client.messages.create(model=model, max_tokens=8000,
                                  system=SYSTEM, messages=messages,
                                  extra_body=body)
    if resp.stop_reason == "refusal":
        raise RuntimeError("the model declined to grade this call")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("the grade was cut off (max_tokens)")
    text = "".join(b.text for b in resp.content
                   if getattr(b, "type", "") == "text")
    return json.loads(text)
