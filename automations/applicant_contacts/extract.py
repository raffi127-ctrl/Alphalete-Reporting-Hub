"""Text and/or screenshot -> [{first_name, last_name, phone, email}].

Claude does the reading; the code decides what is usable. The model is told to
copy, never infer -- a phone it can't read stays blank -- and clean() throws
out anything that still doesn't look like a phone or an email.
"""
from __future__ import annotations  # Lucy runs Python 3.9

import base64
import json
import re
from typing import List, Optional, Tuple

MODEL = "claude-sonnet-5-5"

_SYSTEM = """You read job-applicant info that a recruiter pasted or \
screenshotted (an ApplicantStream / Indeed / text-message screen) and return \
each APPLICANT's contact details.

Rules:
- Copy only what is actually written. Never guess, complete, or invent a \
name, phone or email. If a field isn't there or can't be read, return "".
- One entry per applicant. Ignore the recruiter, the company, office staff, \
and anything that is plainly not the applicant.
- Phone: the applicant's own number, digits as written.
- If there is no applicant in it at all, return an empty list."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "applicants": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "phone": {"type": "string"},
                    "email": {"type": "string"},
                },
                "required": ["first_name", "last_name", "phone", "email"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["applicants"],
    "additionalProperties": False,
}

PHONE_RE = re.compile(r"(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")
EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")


def looks_like_applicant_text(text: str) -> bool:
    """A phone number or an email in the text. That is what separates an
    applicant message from the other things people DM Jiraiya (a DD rep name,
    'knocks …', 'thanks')."""
    t = re.sub(r"<mailto:([^|>]+)(?:\|[^>]*)?>", r"\1", text or "")
    return bool(PHONE_RE.search(t) or EMAIL_RE.search(t))


def phone10(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d if len(d) == 10 else ""


def e164(s: str) -> str:
    d = phone10(s)
    return "+1" + d if d else ""


def pretty_phone(s: str) -> str:
    d = phone10(s)
    return "(%s) %s-%s" % (d[:3], d[3:6], d[6:]) if d else ""


def _title(s: str) -> str:
    # "JUAN" / "juan" -> "Juan"; leave mixed case alone ("McKenzie", "DeShawn").
    s = " ".join((s or "").split())
    if s and (s.isupper() or s.islower()):
        return " ".join(w[:1].upper() + w[1:].lower() for w in s.split(" "))
    return s


def clean(raw: List[dict]) -> List[dict]:
    """Normalize the model's entries; drop a phone/email that doesn't parse."""
    out = []
    for a in raw or []:
        email = (a.get("email") or "").strip().strip(".,;").lower()
        if email and not EMAIL_RE.fullmatch(email):
            email = ""
        out.append({
            "first_name": _title(a.get("first_name", "")),
            "last_name": _title(a.get("last_name", "")),
            "phone": phone10(a.get("phone", "")),
            "email": email,
        })
    return [a for a in out if any(a.values())]


def extract(text: str = "", images: Optional[List[Tuple[bytes, str]]] = None,
            client=None) -> List[dict]:
    """images = [(bytes, media_type)]. Returns clean() entries."""
    import anthropic
    if client is None:
        from automations.brand_audit import credentials
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    content = []
    for data, media in images or []:
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": media,
            "data": base64.standard_b64encode(data).decode("ascii")}})
    content.append({"type": "text", "text":
                    "Message text (may be empty):\n" + (text or "").strip()})
    resp = client.messages.create(
        model=MODEL, max_tokens=4000, system=_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": content}])
    if resp.stop_reason != "end_turn":
        raise RuntimeError("model stopped: %s" % resp.stop_reason)
    body = next((b.text for b in resp.content if b.type == "text"), "{}")
    return clean(json.loads(body).get("applicants") or [])
