"""Visual website review — screenshots the homepage and asks Claude (vision) for
a real design opinion: the vibe, how the photos look, whether it lands with the
company's young (20-25) target audience, and concrete improvement ideas.

This is the qualitative half of the Website section (the website collector
handles the mechanical half: up / HTTPS / blog / freshness). Heavier than the
others (a browser render + one vision call), and it FAILS SOFT — a blocked
render or API hiccup just leaves the visual review out, it never breaks the run.
"""
from __future__ import annotations

import base64

from automations.brand_audit import credentials
from automations.brand_audit.collectors.base import CollectorResult, WARN
from automations.brand_audit.config import OUTPUT_DIR

SOURCE = "website_review"
MODEL = "claude-opus-4-8"

_SCHEMA = {
    "type": "object",
    "properties": {
        "vibe": {"type": "string"},
        "photos": {"type": "string"},
        "audience_fit": {"type": "string"},
        "actions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["vibe", "photos", "audience_fit", "actions"],
    "additionalProperties": False,
}


def _screenshot(url: str) -> bytes | None:
    """First-impression homepage screenshot (above-the-fold). Returns PNG bytes
    or None on any failure."""
    try:
        from patchright.sync_api import sync_playwright
    except Exception:
        return None
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            pg = b.new_page(viewport={"width": 1280, "height": 900})
            try:
                pg.goto(url, wait_until="networkidle", timeout=45000)
            except Exception:
                pg.goto(url, wait_until="load", timeout=45000)
            pg.wait_for_timeout(1500)
            png = pg.screenshot()  # viewport = the first thing a visitor sees
            b.close()
            return png
    except Exception:
        return None


def collect(company) -> CollectorResult:
    res = CollectorResult(source=SOURCE)
    url = company.website
    if not url:
        return CollectorResult.failed(SOURCE, "no website URL")

    png = _screenshot(url)
    if not png:
        res.ok = False
        res.error = "couldn't render the homepage for a visual review"
        res.flag(WARN, "Couldn't screenshot the site for a design review "
                       "(render blocked/failed).", url=url)
        return res

    # save the shot next to the report (gitignored output/)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = "".join(c.lower() if c.isalnum() else "_" for c in company.name).strip("_")
    shot_path = OUTPUT_DIR / f"home_{slug}.png"
    shot_path.write_bytes(png)
    res.evidence["screenshot_path"] = str(shot_path)

    prompt = (
        f"This is the homepage (first screen) of {company.name}, a door-to-door "
        f"sales & marketing company. Its target audience skews YOUNG (roughly "
        f"20-25) — both potential hires and customers. Give a candid, specific "
        f"design critique of this first impression, in plain language:\n"
        f"- vibe: the overall feel/aesthetic in 1-2 sentences\n"
        f"- photos: how the imagery looks (quality, authenticity, are they stock?)\n"
        f"- audience_fit: does this land with a 20-25-year-old? why or why not\n"
        f"- actions: 2-4 concrete, doable improvement ideas (specific, not vague)\n"
        f"Be honest — if it looks dated or corporate, say so."
    )
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.standard_b64encode(png).decode()}},
                {"type": "text", "text": prompt},
            ]}],
        )
        import json
        text = next((b.text for b in resp.content if b.type == "text"), "{}")
        data = json.loads(text)
    except Exception as e:
        return CollectorResult.failed(SOURCE, f"vision review failed: {e}")

    res.metrics = {"reviewed": True, "action_count": len(data.get("actions") or [])}
    res.evidence.update({
        "vibe": data.get("vibe", ""),
        "photos": data.get("photos", ""),
        "audience_fit": data.get("audience_fit", ""),
        "actions": data.get("actions", []),
    })
    return res
