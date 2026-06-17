"""Weekly Reddit post drafting — Claude writes a fresh, human-sounding post for
the company's OWN subreddit, rotating across content types so it never reads
"automated". Drafts are held for approval (posted to Slack); actual posting to
Reddit happens after approval (needs the authenticated Reddit write API).

Uses the Anthropic API (official SDK). Model: claude-opus-4-8 for the most
natural prose — a weekly short post is a fraction of a cent. Structured JSON
output ({title, body}) so parsing never breaks.
"""
from __future__ import annotations

import json
from datetime import date

from automations.brand_audit import credentials

MODEL = "claude-opus-4-8"

# Rotated weekly so consecutive posts differ in kind. "custom" expects a
# one-line topic from the ICD; the others self-generate from real data.
CONTENT_TYPES = ["customer_win", "hiring", "update", "custom"]

_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["title", "body"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You write short posts for a company's OWN subreddit. The goal is content "
    "that reads like a real person on the team wrote it — NOT marketing, NOT a "
    "press release, NOT obviously AI. Rules: first person, conversational, "
    "specific; no hashtags; no emoji walls; no corporate buzzwords (\"thrilled "
    "to announce\", \"leverage\", \"synergy\"); vary sentence length; sound like "
    "a human posting an update, not an ad. Keep it brief (a tight title + a few "
    "sentences). Never fabricate facts — use only what you're given."
)


def _recent_positive_review(results: dict) -> dict | None:
    reviews = ((results.get("google_reviews") or {}).get("evidence") or {}).get("reviews") or []
    for r in reviews:
        if isinstance(r.get("rating"), (int, float)) and r["rating"] >= 5 and (r.get("text") or "").strip():
            return r
    return None


def pick_content_type(results: dict, week: int | None = None,
                      custom_topic: str = "") -> str:
    if custom_topic:
        return "custom"
    week = week if week is not None else date.today().isocalendar()[1]
    ctype = CONTENT_TYPES[week % len(CONTENT_TYPES)]
    # customer_win needs a real review to ground it; fall back to hiring
    if ctype == "customer_win" and not _recent_positive_review(results):
        ctype = "hiring"
    # custom needs a topic; without one, fall back to update
    if ctype == "custom" and not custom_topic:
        ctype = "update"
    return ctype


def _prompt(company, results: dict, ctype: str, custom_topic: str) -> str:
    name = company.name
    if ctype == "customer_win":
        rv = _recent_positive_review(results) or {}
        return (
            f"Write a post for r/{_subreddit(company)} about a recent happy "
            f"customer at {name} (a door-to-door sales company). Ground it in "
            f"this real review — paraphrase, don't quote verbatim, and don't use "
            f"the reviewer's name:\n\n\"{(rv.get('text') or '')[:400]}\"\n\n"
            f"Make it feel like someone on the team sharing a small win."
        )
    if ctype == "hiring":
        return (
            f"Write a post for r/{_subreddit(company)} that honestly describes "
            f"what working at {name} (a door-to-door sales company) is actually "
            f"like day to day — the kind of straight-talk post that answers what "
            f"a curious applicant would want to know. Honest, not a recruiting ad."
        )
    if ctype == "custom":
        return (
            f"Write a post for r/{_subreddit(company)} ({name}, a door-to-door "
            f"sales company) about this: {custom_topic}"
        )
    return (  # update
        f"Write a short, genuine update post for r/{_subreddit(company)} from "
        f"the team at {name} (a door-to-door sales company) — a milestone, a "
        f"team highlight, or what's been going on lately. Keep it real and human."
    )


def _subreddit(company) -> str:
    from urllib.parse import urlparse
    parts = [p for p in urlparse(company.reddit or "").path.split("/") if p]
    return parts[1] if len(parts) >= 2 and parts[0].lower() == "r" else "yoursubreddit"


def generate_draft(company, results: dict, *, custom_topic: str = "") -> dict:
    """Return {type, title, body}. Raises on API failure (caller decides)."""
    import anthropic
    ctype = pick_content_type(results, custom_topic=custom_topic)
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user",
                   "content": _prompt(company, results, ctype, custom_topic)}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    data = json.loads(text)
    return {"type": ctype, "title": data.get("title", ""),
            "body": data.get("body", ""), "subreddit": _subreddit(company)}


def _slack_message(company, draft: dict) -> str:
    sub = draft.get("subreddit", "")
    return "\n".join([
        f":memo: *Weekly Reddit draft — r/{sub}*  _(type: {draft.get('type')})_",
        "Review it, tweak if needed, then paste into Reddit. React :white_check_mark: "
        "once you've posted it (just for your own tracking).",
        "",
        f"*Title:* {draft.get('title','')}",
        "",
        draft.get("body", ""),
    ])


def post_draft_to_slack(company, draft: dict, *, dry_run: bool = False,
                        channel_id: str | None = None) -> dict:
    from automations.brand_audit.config import ALERT_SLACK_CHANNEL_ID
    channel_id = channel_id or ALERT_SLACK_CHANNEL_ID
    message = _slack_message(company, draft)
    if dry_run:
        return {"dry_run": True, "channel": channel_id, "message": message}
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    resp = client.chat_postMessage(channel=channel_id, text=message)
    return {"posted": bool(resp.get("ok")), "channel": channel_id,
            "ts": resp.get("ts")}


def main(argv=None) -> int:
    import argparse
    import sys
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    from automations.brand_audit import intake
    from automations.brand_audit.config import DEFAULT_COMPANY
    from automations.brand_audit.collectors import google_reviews

    p = argparse.ArgumentParser(prog="brand_audit.reddit_drafts")
    p.add_argument("--company", default=DEFAULT_COMPANY)
    p.add_argument("--topic", default="", help="optional one-line topic for the post")
    p.add_argument("--dry-run", action="store_true",
                   help="print the draft instead of posting to Slack")
    args = p.parse_args(argv)

    company = intake.find_company(args.company)
    if not company:
        print(f"!! company {args.company!r} not found", file=sys.stderr)
        return 1

    # Only Google reviews are needed to ground a customer-win post.
    results = {"google_reviews": google_reviews.collect(company).as_dict()}
    draft = generate_draft(company, results, custom_topic=args.topic)
    out = post_draft_to_slack(company, draft, dry_run=args.dry_run)
    if out.get("dry_run"):
        print("--- would post to Slack ---")
        print(out["message"])
    elif out.get("posted"):
        print(f"posted weekly draft to Slack ({draft['type']}) for review")
    else:
        print("!! Slack post failed", file=sys.stderr)
        return 1
    print("=== done ===")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
