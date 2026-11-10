"""Write the text Lucy would send. Writes ONLY — there is no send here.

The model gets the office's facts (facts.block), the tail of the thread,
and why Lucy picked it up (triage). It returns a reply plus whether a
person has to act. The reply then goes through guard.check; the model is
never the last word on what is allowed.
"""
from __future__ import annotations

import json

from automations.applicant_replies import config as C

SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {
            "type": "string",
            "description": "The text to send the applicant, or an empty "
            "string to send nothing."},
        "hand_to_person": {
            "type": "boolean",
            "description": "True when a person on the team has to do "
            "something: place a call, book or move an interview, or answer a "
            "question the FACTS can't."},
        "note_for_team": {
            "type": "string",
            "description": "One line for the recruiter: what the applicant "
            "needs. Empty when hand_to_person is false."},
        "facts_used": {
            "type": "array", "items": {"type": "string"},
            "description": "Which FACTS lines the reply relies on, quoted "
            "briefly. Empty if none."},
    },
    "required": ["reply", "hand_to_person", "note_for_team", "facts_used"],
    "additionalProperties": False,
}

SYSTEM = """You answer job applicants by text message for a sales company's recruiting team. You are stepping into an SMS thread the team already started; the applicant has just written, and either nobody answered them or the answer they got didn't help.

FACTS are the only things you know. If the answer is not in FACTS, do not guess — leave reply empty or send the approved call line below, and set hand_to_person with a note. A wrong fact sent to an applicant (wrong suite, wrong pay) is worse than no text.

How the company wants questions answered — these are rulings, follow them exactly:
- Pay: use the Pay line in FACTS. Never say there is a "base" pay or salary.
- Where / remote: name the role they applied to first, then the office address. Do not jump straight to asking for their email.
- Group interview: the first interview is a small group interview. Say yes, then reassure them.
- Never push a job question (pay, hours, role, location, door-to-door) to "the hiring manager" or "the interview" when FACTS answers it. Answer it.
- A phone call request is passed to a person. Approved line: "Of course - I'll have someone from our team give you a call." Never give a time ("soon", "shortly", "today", "in a few minutes") and never ask them to pick a time.
- Never write the company name, an address or a job title in block capitals.

Style:
- Answer first, then one short question that keeps them moving toward the interview (the approved scripts end like "Is that something you're okay with?"). At most one question.
- Under 300 characters. Plain text. No emoji, no links except the office's own Zoom link when they need it.
- Do not introduce yourself and do not sign a name. If they ask who they are talking to, use the first name our side used earlier in the thread.
- If they ask whether this is a bot or a real person, be honest: you are the team's automated assistant, and a person can call them.
- If they wrote in Spanish, reply in Spanish with the same facts, under 130 characters (accented letters make every text segment shorter).
- Never mention age, gender or any other personal trait, and never describe who the company hires.
- Don't oversell: no promises about being hired, earnings beyond the Pay line, or how fast anyone gets promoted.
- You cannot see the calendar or book anything. Never offer, confirm or move an interview time, and do not ask whether a time still works - even one mentioned earlier in the thread, because it may have changed. If they want to book or reschedule, hand it to a person.
- Never claim you did something (noted it, booked it, removed them). You can only write this one text.

Special cases:
- They said stop or not interested: reply must be empty, hand_to_person false.
- They think it is a scam: apologize that our number probably isn't saved in their phone, and remind them of the role they applied for."""


def _thread_text(convo, upto):
    msgs = convo["msgs"][:upto + 1][-C.THREAD_TAIL:]
    lines = []
    for m in msgs:
        who = "APPLICANT" if m["dir"] == "In" else (
            "OUR AI" if "ai messaging" in (m.get("sent_by", "") + " " +
                                           m.get("source", "")).lower()
            else "OUR RECRUITER")
        lines.append("[{} {}] {}".format(m["when"].strftime("%a %m/%d %I:%M %p"),
                                         who, " ".join((m["body"] or "").split())))
    return "\n".join(lines)


def prompt(facts_text, convo, turn, reason, detail):
    return ("FACTS\n{}\n\nWHY YOU ARE ANSWERING: {} ({})\n\nTHREAD, oldest "
            "first, ending with the applicant's latest text\n{}"
            .format(facts_text, reason, detail, _thread_text(convo, turn["upto"])))


def _client():
    import anthropic
    from automations.brand_audit import credentials
    return anthropic.Anthropic(api_key=credentials.anthropic_api_key())


def write(facts_text, convo, turn, reason, detail, client=None):
    """The model's answer as a dict (SCHEMA), plus 'usage'."""
    import anthropic
    client = client or _client()
    body = {"output_config": {"effort": C.EFFORT,
                              "format": {"type": "json_schema", "schema": SCHEMA}}}
    messages = [{"role": "user",
                 "content": prompt(facts_text, convo, turn, reason, detail)}]
    # Same shape as first_round_scorecards.grade: extra_body so the older SDK
    # on a Lucy (Python 3.9) still sends it; on a refusal the API re-runs it
    # on a fallback model.
    try:
        resp = client.messages.create(
            model=C.MODEL, max_tokens=4000, system=SYSTEM, messages=messages,
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={**body, "fallbacks": "default"})
    except anthropic.BadRequestError:
        resp = client.messages.create(model=C.MODEL, max_tokens=4000,
                                      system=SYSTEM, messages=messages,
                                      extra_body=body)
    if resp.stop_reason == "refusal":
        raise RuntimeError("the model declined to draft this reply")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("the draft was cut off (max_tokens)")
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    out = json.loads(text)
    out["usage"] = {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens}
    return out
