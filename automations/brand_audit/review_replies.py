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
    _client, _reacted, _thread_reactions,
)
from automations.brand_audit.config import (
    SOCIAL_APPROVE_EMOJI, SOCIAL_REJECT_EMOJI, SOCIAL_KILL_EMOJI,
)

MODEL = "claude-opus-4-8"
_STATE = Path.home() / ".config" / "brand-audit" / "review_replies.json"
NEGATIVE_BELOW = 4          # rating < 4 is flagged as needs-attention
# An approver reacting one of these on the DAILY HEADER = batch done, stop
# re-checking it. Until then Lucy keeps picking up late reactions each scan.
HEADER_DONE_EMOJI = ("white_check_mark", "heavy_check_mark",
                     "ballot_box_with_check", "checkered_flag")

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


def draft_reply(review: dict, company_name: str, feedback: str = "",
                avoid: list[str] | None = None) -> str:
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
        "'we value your feedback' clichés. Keep the brand clean and classy.\n"
        "VARY every reply — do NOT reuse the same words or structure across "
        "replies. In particular don't lean on 'thrilled' (or any single word/"
        "phrase) repeatedly; each reply should read like it was written "
        "individually by a real person.\n"
        "DON'T SOUND AI: no balanced three-part phrases (tricolons), no filler "
        "('made our day', 'means the world', 'couldn't be happier', 'so glad'), "
        "no over-polished marketing tone. Write plainly, like a real teammate "
        "typing a quick, genuine thanks — short and human, not a press release.")
    stars = review.get("rating")
    user = (f"Review — {stars}★ from {review.get('author') or 'a customer'}:\n"
            f"\"{review.get('text') or '(no text, just a rating)'}\"\n\n"
            "Write the reply.")
    if feedback:
        user += f"\n\nThe approver rejected the last draft — apply this: \"{feedback}\"."
    if avoid:
        user += ("\n\nDo NOT reuse the wording or structure of these other "
                 "recent replies — make this one clearly different (and don't "
                 "repeat words like 'thrilled' that appear in them):\n"
                 + "\n".join(f"- {a}" for a in avoid if a))
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
    """One daily scan: post a 'Response Reviews MM/DD/YY' header thread, draft a
    reply for each new review as a REPLY in that thread, and pick up reactions on
    every still-open day's threads (approve / redo / skip). Keeps re-checking a
    day's header until an approver reacts a 'done' emoji on it. Posting to Google
    is stubbed (API pending) — approved replies are marked ready."""
    import datetime as dt
    from automations.brand_audit import intake
    company = intake.find_company(company_name)
    if not company:
        return [{"error": f"company {company_name!r} not found"}]
    channel = channel or ALERT_SLACK_CHANNEL_ID
    cl = _client()
    state = _load()
    state.setdefault("headers", {})
    state.setdefault("reviews", {})
    recent = list(state.get("_recent_replies", []))   # for cross-reply variety
    actions = []
    today = dt.date.today().strftime("%m/%d/%y")

    # 1) today's header thread (one per day)
    hdr = state["headers"].get(today)
    if not hdr and not dry_run:
        r = cl.chat_postMessage(channel=channel, text=f"*Response Reviews {today}*")
        hdr = state["headers"][today] = {"ts": r.get("ts"), "completed": False}
        actions.append({"action": "header_created", "date": today})

    # 2) draft + post any NEW reviews as replies under today's header
    new_count = 0
    for rv in get_reviews(company):
        k = _key(rv)
        if k in state["reviews"]:
            continue
        reply = draft_reply(rv, company_name, avoid=recent[:15])
        recent.insert(0, reply)
        new_count += 1
        actions.append({"action": "draft", "rating": rv.get("rating"), "reply": reply})
        if not dry_run and hdr:
            r = cl.chat_postMessage(channel=channel, thread_ts=hdr["ts"],
                                    text=_review_block(rv, reply))
            state["reviews"][k] = {"reply": reply, "reply_ts": r.get("ts"),
                                   "date": today, "review": rv}
    if not dry_run and hdr and new_count == 0 and not hdr.get("noted_empty"):
        cl.chat_postMessage(channel=channel, thread_ts=hdr["ts"],
                            text="No new reviews needing a response today. React "
                                 ":white_check_mark: on this header to close it out.")
        hdr["noted_empty"] = True

    # 3) handle reactions on every still-open review reply (any day)
    for k, st in state["reviews"].items():
        if st.get("posted") or st.get("skipped") or not st.get("reply_ts"):
            continue
        rv = st.get("review") or {}
        rx = _thread_reactions(cl, st["reply_ts"]).get(st["reply_ts"])
        if _reacted(rx, SOCIAL_KILL_EMOJI):
            st["skipped"] = True
            actions.append({"action": "skipped", "review": k})
            continue
        rejected = st.setdefault("rejected", [])
        cur = st.get("reply")
        if (not _reacted(rx, SOCIAL_APPROVE_EMOJI)
                and _reacted(rx, SOCIAL_REJECT_EMOJI)
                and cur and cur not in rejected):
            rejected.append(cur)
            new = draft_reply(rv, company_name, avoid=(rejected + recent)[:15])
            recent.insert(0, new)
            actions.append({"action": "redraft", "review": k, "reply": new})
            if not dry_run and hdr:
                r = cl.chat_postMessage(channel=channel, thread_ts=hdr["ts"],
                                        text=_review_block(rv, new))
                st["reply"] = new
                st["reply_ts"] = r.get("ts")
            continue
        if _reacted(rx, SOCIAL_APPROVE_EMOJI):
            actions.append({"action": "approved", "review": k, "reply": cur})
            if not dry_run:
                try:
                    post_reply_to_google(rv, cur, company)
                    st["posted"] = True
                except Exception:
                    st["approved_pending_api"] = True   # auto-posts once GBP API on
            continue
        actions.append({"action": "awaiting", "review": k})

    # 4) mark a day's header complete once an approver reacts a 'done' emoji
    for date, h in state["headers"].items():
        if h.get("completed") or not h.get("ts"):
            continue
        if _reacted(_thread_reactions(cl, h["ts"]).get(h["ts"]), HEADER_DONE_EMOJI):
            h["completed"] = True
            actions.append({"action": "header_completed", "date": date})

    if not dry_run:
        state["_recent_replies"] = recent[:40]
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
