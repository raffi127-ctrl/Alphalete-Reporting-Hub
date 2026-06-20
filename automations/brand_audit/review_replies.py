"""Google review → drafted reply → approve in Slack workflow.

Every review gets a reply. Lucy reads the reviews (Places API), drafts an
on-brand reply for each, and posts it to the brand-health Slack channel for
Megan/Raf to approve (✅) / refine (❌ + note) / skip (💀). Negative reviews are
flagged up top so they're handled fast.

POSTING TO GOOGLE IS STUBBED — replying to reviews needs the Google Business
Profile API (access pending). Approved replies are stored ready to push the
moment that lands; `post_reply_to_google()` is the single pluggable seam.

Reads at most ~5 reviews (Places API limit) until the Business Profile API
gives the full list.
"""
from __future__ import annotations

import json
from pathlib import Path

from automations.brand_audit import credentials
from automations.brand_audit.collectors import google_reviews
from automations.brand_audit.config import ALERT_SLACK_CHANNEL_ID, DEFAULT_COMPANY
from automations.brand_audit.social_inbox import (
    _client, _reacted, _thread_reactions, _human_reply_after,
)
from automations.brand_audit.config import (
    SOCIAL_APPROVE_EMOJI, SOCIAL_REJECT_EMOJI, SOCIAL_KILL_EMOJI,
)

MODEL = "claude-opus-4-8"
_STATE = Path.home() / ".config" / "brand-audit" / "review_replies.json"
NEGATIVE_BELOW = 4          # rating < 4 is flagged as needs-attention

_REPLY_SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}},
    "required": ["reply"], "additionalProperties": False,
}


def _load() -> dict:
    try:
        return json.loads(_STATE.read_text())
    except Exception:
        return {}


def _save(s: dict) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(s, indent=2))


def _key(rv: dict) -> str:
    """Stable-ish id for a review (Places API gives no review id)."""
    return f"{rv.get('author','')}|{rv.get('publish_time','') or (rv.get('text','') or '')[:50]}"


def get_reviews(company) -> list[dict]:
    """The review sample for a company (rating/text/author/when)."""
    res = google_reviews.collect(company)
    return ((res.as_dict().get("evidence") or {}).get("reviews")) or \
        (res.evidence.get("reviews") if hasattr(res, "evidence") else []) or []


def draft_reply(review: dict, company_name: str, feedback: str = "") -> str:
    """Draft the business's public reply to one review."""
    import anthropic
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    system = (
        f"You write {company_name}'s public reply to a Google review. "
        "Warm, genuine, professional, and CONCISE (1-3 sentences). Sound like a "
        "real person from the team, not corporate. Thank positive reviewers and "
        "use their first name if given. For criticism: acknowledge it sincerely, "
        "never be defensive or argue, take it offline (invite them to reach out "
        "to make it right). Never share private details, never use jargon or "
        "'we value your feedback' clichés. Keep the brand clean and classy.")
    stars = review.get("rating")
    user = (f"Review — {stars}★ from {review.get('author') or 'a customer'}:\n"
            f"\"{review.get('text') or '(no text, just a rating)'}\"\n\n"
            "Write the reply.")
    if feedback:
        user += f"\n\nThe approver rejected the last draft — apply this: \"{feedback}\"."
    resp = client.messages.create(
        model=MODEL, max_tokens=300, system=system,
        output_config={"format": {"type": "json_schema", "schema": _REPLY_SCHEMA}},
        messages=[{"role": "user", "content": user}])
    body = next((b.text for b in resp.content if b.type == "text"), "{}")
    return json.loads(body).get("reply", "")


def post_reply_to_google(review: dict, reply: str, company) -> dict:
    """Publish the reply to the Google review. PENDING the Business Profile API
    (access not yet granted). Approved replies wait for this seam."""
    raise NotImplementedError(
        "Google review replies need the Business Profile API "
        "(accounts.locations.reviews.updateReply) — access pending.")


def _review_block(review: dict, reply: str) -> str:
    stars = review.get("rating")
    star_str = ("⭐" * int(stars)) if isinstance(stars, (int, float)) else "?"
    neg = isinstance(stars, (int, float)) and stars < NEGATIVE_BELOW
    head = (":rotating_light: *Negative review — needs attention*" if neg
            else ":speech_balloon: *New review*")
    return (f"{head}  {star_str} — *{review.get('author') or 'Anonymous'}* "
            f"({review.get('when') or ''})\n"
            f"> {(review.get('text') or '(rating only, no text)')}\n\n"
            f":pencil2: *Drafted reply* — react :white_check_mark: to approve, "
            f":x: + a note to redo, :skull: to skip:\n{reply}")


def process_reviews(company_name: str = DEFAULT_COMPANY, *, dry_run: bool = True,
                    channel: str | None = None) -> list[dict]:
    """Draft + post replies for every review; track approvals. Posting to Google
    is stubbed (API pending) — approved replies are marked ready."""
    from automations.brand_audit import intake
    company = intake.find_company(company_name)
    if not company:
        return [{"error": f"company {company_name!r} not found"}]
    channel = channel or ALERT_SLACK_CHANNEL_ID
    cl = _client()
    state = _load()
    actions = []

    for rv in get_reviews(company):
        k = _key(rv)
        st = state.setdefault(k, {})
        if st.get("posted") or st.get("skipped"):
            continue

        # 💀 skip
        if st.get("reply_ts"):
            rx = _thread_reactions(cl, st["reply_ts"]).get(st["reply_ts"])
            if _reacted(rx, SOCIAL_KILL_EMOJI):
                actions.append({"review": k, "action": "skipped"})
                st["skipped"] = True
                continue
            # ❌ + note -> redraft
            rejected = st.setdefault("rejected", [])
            cur = st.get("reply")
            if (not _reacted(rx, SOCIAL_APPROVE_EMOJI)
                    and _reacted(rx, SOCIAL_REJECT_EMOJI)
                    and cur and cur not in rejected):
                rejected.append(cur)
                fb = _human_reply_after(cl, st["reply_ts"], st["reply_ts"])
                new = draft_reply(rv, company_name,
                                  feedback=(fb.get("text") if fb else ""))
                actions.append({"review": k, "action": "redraft", "reply": new})
                if not dry_run:
                    r = cl.chat_postMessage(channel=channel, text=_review_block(rv, new))
                    st["reply"] = new
                    st["reply_ts"] = r.get("ts")
                continue
            # ✅ approved -> ready to post (stub until API)
            if _reacted(rx, SOCIAL_APPROVE_EMOJI):
                actions.append({"review": k, "action": "approved", "reply": cur})
                if not dry_run:
                    try:
                        post_reply_to_google(rv, cur, company)
                        st["posted"] = True
                    except Exception:
                        st["approved_pending_api"] = True   # wait for GBP API
                        if not st.get("approved_acked"):
                            cl.chat_postMessage(
                                channel=channel,
                                text=":white_check_mark: Approved — will post to "
                                     "Google automatically once API access is on.")
                            st["approved_acked"] = True
                continue
            actions.append({"review": k, "action": "awaiting_approval"})
            continue

        # first pass: draft + post for approval
        reply = draft_reply(rv, company_name)
        actions.append({"review": k, "action": "draft", "rating": rv.get("rating"),
                        "reply": reply})
        if not dry_run:
            r = cl.chat_postMessage(channel=channel, text=_review_block(rv, reply))
            st["reply"] = reply
            st["reply_ts"] = r.get("ts")

    if not dry_run:
        _save(state)
    return actions


def main(argv=None) -> int:
    import argparse
    import sys
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="brand_audit.review_replies")
    p.add_argument("--company", default=DEFAULT_COMPANY)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    for a in process_reviews(args.company, dry_run=args.dry_run):
        print(a.get("action"), "·", (a.get("reply") or a.get("error") or "")[:80])
    print("=== done ===")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
