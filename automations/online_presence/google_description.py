"""The office's Google listing description: what it says now, and a plain
rewrite Lucy recommends (Megan 2026-11-11: "this should have what their
listing says now and what we'd recommend - it should edit it in a very non
AI way - not a lot of fluff and try to incorporate what is already there").

Read through the central GBP API (alphaletemarketing@gmail.com is Manager
on every office's listing). Nothing here writes to Google: the owner pastes
the suggestion in themselves.

The suggestion is cached per office and only redone when the description on
Google changes, so the same advice shows week to week and the AI is called
at most once per change.
"""
from __future__ import annotations

import hashlib
import json
from typing import Dict, Optional

MAX_CHARS = 750          # Google's limit for a business description
MODEL = "claude-opus-5-5"

# What each campaign sells, in the words a customer would Google. Naming the
# product + city in the description is what lets Google match searches like
# "AT&T Fiber Plano" to the listing. Worded as "we sell X", never as if they
# ARE the brand. Energy Wells is a test campaign: nothing added.
SELLS = {
    "att": "AT&T Fiber internet for homes",
    "nds": "AT&T wireless and internet for homes",
    "b2b_att": "AT&T Business internet and phone service for local businesses",
    "b2b_box": "business energy plans for local businesses",
    "verizon": "Verizon home internet and wireless",
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "needs_change": {"type": "boolean"},
        "suggested": {"type": "string"},
        "what_changed": {"type": "string"},
    },
    "required": ["needs_change", "suggested", "what_changed"],
    "additionalProperties": False,
}

_SYSTEM = f"""You edit Google Business Profile descriptions for small door-to-door sales offices.

Goal: a description that tells Google and a person reading it WHAT the business does and WHERE, in plain words.

Rules:
- Start from their current description. Keep their own sentences and facts wherever they work; cut, don't rewrite for the sake of it.
- Plain, everyday wording, like the owner would say it out loud. No fluff, no buzzwords ("leading", "premier", "dedicated", "passionate", "elevate", "unparalleled", "cutting-edge", "solutions", "journey"), no exclamation marks, no emojis, no em dashes.
- Use ONLY facts in the current description, the business name, category, city and "What they sell" given. Never invent products, numbers, awards, years or clients.
- If "What they sell" is given and the current text doesn't say it, work it in once, plainly (e.g. "We sell AT&T Fiber internet door to door in Plano and across DFW."). Say they SELL it; never write as if they are that brand or an official part of it.
- Name the city and the area they cover if the current text or address gives it.
- Never mention age, gender, or who they hire ("young", "guys", "20-somethings"). Hiring can be mentioned only as "we're hiring" / "no experience needed" style appeal.
- 2 to 4 short sentences, under {MAX_CHARS} characters.
- If the current description already says what they sell and where, plainly, set needs_change false and return it unchanged.
- what_changed: one short plain sentence for the owner, e.g. "Cut the long middle part and added that you cover Dallas and Fort Worth."
"""


def current(p, sess=None) -> Optional[Dict]:
    """{"description", "category", "city"} from their Google listing, or
    None when the listing isn't linked or Google can't be read."""
    if not p.gbp_location:
        return None
    try:
        from automations.brand_audit import gbp_api
        sess = sess or gbp_api._session()
        lid = p.gbp_location.split("/locations/")[-1]
        d = gbp_api._get(sess, f"{gbp_api._INFO_API}/locations/{lid}",
                         {"readMask": "title,profile,categories,storefrontAddress"})
    except Exception:
        return None
    addr = d.get("storefrontAddress") or {}
    return {"description": ((d.get("profile") or {}).get("description") or "").strip(),
            "category": ((d.get("categories") or {}).get("primaryCategory") or {}).get("displayName") or "",
            "city": ", ".join(x for x in (addr.get("locality"), addr.get("administrativeArea")) if x)}


def _suggest(business: str, now: Dict) -> Dict:
    sells = now.get("sells") or ""
    import anthropic
    from automations.brand_audit import credentials
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    user = (f"Business name: {business}\nCategory on Google: {now['category'] or 'unknown'}\n"
            f"City: {now['city'] or 'unknown'}\nWhat they sell: {sells or 'not given'}\n\n"
            f"Current description:\n"
            f"\"{now['description'] or '(empty)'}\"")
    resp = client.messages.create(
        model=MODEL, max_tokens=600, system=_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": user}])
    text = next(b.text for b in resp.content if getattr(b, "type", "") == "text")
    out = json.loads(text)
    out["suggested"] = out["suggested"].strip()[:MAX_CHARS]
    return out


def check(p, sess=None) -> Optional[Dict]:
    """{"now", "suggested", "needs_change", "what_changed"} or None."""
    now = current(p, sess)
    if now is None:
        return None
    now["sells"] = SELLS.get((getattr(p, "campaign", "") or "").lower(), "")
    key = hashlib.sha1(json.dumps(now, sort_keys=True).encode()).hexdigest()
    cache = p.path("google_description.json")
    try:
        saved = json.loads(cache.read_text())
        if saved.get("key") == key:
            return saved["result"]
    except Exception:
        pass
    try:
        got = _suggest(p.business_name, now)
    except Exception:
        return {"now": now["description"], "suggested": "", "needs_change": None, "what_changed": ""}
    result = {"now": now["description"], **got}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"key": key, "result": result}))
    except Exception:
        pass
    return result
