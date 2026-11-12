"""The words on an office's website, written for THAT office (Megan
2026-11-11: "EVERY site needs to be different").

Same-text sites hurt every office on Google (duplicate content), and read like
a template. So each site's copy is written from the office's own facts and the
owner's own answers (site.json -> "answers": how they started, what makes the
office different, the culture), in plain words.

Rules: only facts given (never invented numbers, awards, years, clients); no
age / gender / "who we hire" (feedback_recruiting_copy_compliance); no fluff.
Cached per office until the inputs change, so a rebuild never rewrites a site
the owner already approved.
"""
from __future__ import annotations

import hashlib
import json
from typing import Dict

MODEL = "claude-opus-5-5"

FIELDS = {
    "hero_h1": "2 short lines, max 9 words total, punchy, about the opportunity. Use \\n between the lines.",
    "hero_sub": "1-2 sentences: what they sell, where, and that no experience is needed.",
    "what_title": "3-6 words",
    "what_body": "2-3 sentences about the work itself.",
    "why_title": "3-6 words",
    "why_body": "2-3 sentences about the team and culture, from the owner's answers.",
    "about_title": "3-6 words",
    "about_story": "3-5 sentences: the office's own story from the owner's answers. If no story was given, describe the team plainly without inventing history.",
    "value_1_title": "1-2 words", "value_1_body": "1 sentence",
    "value_2_title": "1-2 words", "value_2_body": "1 sentence",
    "value_3_title": "1-2 words", "value_3_body": "1 sentence",
    "apply_title": "3-7 words",
    "apply_sub": "1-2 sentences inviting people to apply.",
    "meta_description": "under 155 characters, includes the business name, city and what they sell.",
}

_SCHEMA = {"type": "object", "properties": {k: {"type": "string"} for k in FIELDS},
           "required": list(FIELDS), "additionalProperties": False}

_SYSTEM = """You write the website for one small door-to-door sales office. The site is recruiting-first: it turns visitors into job applicants, and also tells customers who the office is.

Voice: confident, plain, like the owner talking. Short sentences. No buzzwords ("leading", "premier", "passionate", "elevate", "unparalleled", "solutions", "journey", "world-class"), no exclamation marks, no emojis, no em dashes.

Hard rules:
- Use ONLY the facts and answers given. Never invent numbers, pay, awards, years, clients, office counts or history.
- The story and culture come from the owner's answers, reworded, never added to: no motives, feelings, events or details the answers don't say ("they built the office they wished they'd had" is invented unless the owner said it). Shorter is better than padded.
- Never mention age, gender or who they want to hire ("young", "guys", "20-somethings", "recent grads"). "No experience needed", "we train you", "promoted on performance" are fine.
- Say they SELL a brand's products; never write as if they are that brand.
- Make it sound like THIS office: use their city, their story and their words from the answers. Two offices with the same facts must still read differently, so lean on the owner's answers.

Field guide:
""" + "\n".join(f"- {k}: {v}" for k, v in FIELDS.items())


def _ask(facts: Dict, answers: Dict) -> Dict:
    import anthropic
    from automations.brand_audit import credentials
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    user = json.dumps({"business_name": facts["name"], "city": facts["city"], "state": facts["state"],
                       "areas_served": facts["areas"], "what_they_sell": facts["sells"],
                       "brand": facts["brand"], "sells_to_businesses": facts["b2b"],
                       "owner_answers": answers or {}}, indent=1)
    resp = client.messages.create(
        model=MODEL, max_tokens=1500, system=_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": user}])
    text = next(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return json.loads(text)


def copy_for(p, facts: Dict, answers: Dict) -> Dict:
    key = hashlib.sha1(json.dumps([facts["name"], facts["city"], facts["sells"], facts["areas"],
                                   answers], sort_keys=True).encode()).hexdigest()
    cache = p.path("site_copy.json")
    try:
        saved = json.loads(cache.read_text())
        if saved.get("key") == key:
            return saved["copy"]
    except Exception:
        pass
    got = _ask(facts, answers)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"key": key, "copy": got}, indent=1))
    return got
