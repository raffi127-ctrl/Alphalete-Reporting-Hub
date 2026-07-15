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

from automations.brand_audit import credentials, gbp_api
from automations.brand_audit.collectors import google_reviews
from automations.brand_audit.config import (
    ALERT_SLACK_CHANNEL_ID, DEFAULT_COMPANY, GBP_LOCATION_PATH,
    AUTO_POST_MIN_STARS, AUTO_POST_DAILY_CAP,
)
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


def gbp_ready() -> bool:
    """True once we can both READ the full review list and POST replies:
    a location is configured AND a Business Profile token exists. Until then
    the workflow reads the Places 5-review sample and only drafts (no posting)."""
    return bool(GBP_LOCATION_PATH) and gbp_api.has_token()


def get_reviews(company) -> list[dict]:
    """Reviews for a company (rating/text/author/when/name/has_reply).

    Prefers the Business Profile API (FULL history + a review 'name' we can
    reply to). Falls back to the Places API 5-review sample if GBP isn't set up
    yet, access isn't granted (403), or anything errors — so the drafting side
    keeps working while access is pending. Already-answered reviews are dropped."""
    if gbp_ready():
        try:
            revs = gbp_api.list_reviews(GBP_LOCATION_PATH)
            # Don't re-reply to reviews that already have a business reply.
            return [r for r in revs if not r.get("has_reply")]
        except gbp_api.GBPAccessError:
            pass  # allowlist not granted yet — fall back to the sample
        except Exception:
            pass
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
        "typing a quick, genuine thanks, short and human, not a press release.\n"
        "Avoid the em-dash-heavy rhythm that reads as AI (don't string clauses "
        "with ' — '); use plain periods/commas and vary how sentences open. "
        "Contractions are good. It should read like a busy human typed it fast.")
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
    """Publish the reply to the Google review via the Business Profile API.

    Needs the review's full v4 resource name (present on GBP-sourced reviews,
    absent on the Places-API sample) AND granted API access. Raises
    gbp_api.GBPAccessError if access isn't live yet — callers treat that as
    'not ready, keep the draft'."""
    name = review.get("name")
    if not name:
        raise NotImplementedError(
            "This review came from the Places sample (no reply target). Posting "
            "needs the Business Profile API review list — set GBP_LOCATION_PATH "
            "and authorize (python -m automations.brand_audit.gbp_api --setup).")
    return gbp_api.reply_to_review(name, reply)


def _auto_block(review: dict, reply: str, entry: dict) -> str:
    """FYI posted to Slack when a 4-5★ review was auto-replied (no approval
    step) — so there's always a visible trail of what went public."""
    stars = review.get("rating")
    star_str = ("⭐" * int(stars)) if isinstance(stars, (int, float)) else "?"
    if entry.get("posted"):
        head = ":white_check_mark: *Auto-replied — posted to Google*"
    elif entry.get("approved_pending_api"):
        head = ":hourglass_flowing_sand: *Auto-reply held* (API access not live)"
    else:
        head = (":warning: *Auto-reply failed to post* — "
                + (entry.get("post_error") or "unknown error"))
    return (f"{head}  {star_str} — *{review.get('author') or 'Anonymous'}*\n"
            f"> {(review.get('text') or '(rating only, no text)')}\n\n"
            f":pencil2: _Reply:_ {reply}")


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

    # 2) draft a reply for each NEW review. HYBRID model (Megan 2026-07-15):
    #    rating >= AUTO_POST_MIN_STARS  -> auto-post to Google now + FYI to Slack.
    #    below that / no reply target   -> queue in Slack for approve/redo/skip.
    new_count = 0
    auto_ok = gbp_ready()
    counts = state.setdefault("auto_post_counts", {})
    posted_today = counts.get(today, 0)          # throttle across runs in a day
    deferred = 0
    for rv in get_reviews(company):
        k = _key(rv)
        if k in state["reviews"]:
            continue
        stars = rv.get("rating")
        auto = (auto_ok and isinstance(stars, (int, float))
                and stars >= AUTO_POST_MIN_STARS and rv.get("name"))
        # Throttle: once today's auto-post cap is hit, leave the rest UNTOUCHED
        # (don't draft, don't record) so the next daily run picks them up.
        if auto and posted_today >= AUTO_POST_DAILY_CAP:
            deferred += 1
            continue
        reply = draft_reply(rv, company_name, avoid=recent[:15])
        recent.insert(0, reply)
        new_count += 1
        if auto:
            posted_today += 1
            counts[today] = posted_today
            actions.append({"action": "auto_post", "rating": stars, "reply": reply})
            if not dry_run:
                entry = {"reply": reply, "date": today, "review": rv, "auto": True}
                try:
                    post_reply_to_google(rv, reply, company)
                    entry["posted"] = True
                except gbp_api.GBPAccessError:
                    entry["approved_pending_api"] = True   # access dropped; hold
                except Exception as e:
                    entry["post_error"] = str(e)[:200]
                if hdr:
                    cl.chat_postMessage(channel=channel, thread_ts=hdr["ts"],
                                        text=_auto_block(rv, reply, entry))
                state["reviews"][k] = entry
            continue
        # queue for approval (negatives + anything we can't/won't auto-post)
        actions.append({"action": "draft", "rating": stars, "reply": reply})
        if not dry_run and hdr:
            r = cl.chat_postMessage(channel=channel, thread_ts=hdr["ts"],
                                    text=_review_block(rv, reply))
            state["reviews"][k] = {"reply": reply, "reply_ts": r.get("ts"),
                                   "date": today, "review": rv}
    if deferred:
        actions.append({"action": "deferred", "count": deferred,
                        "note": f"{deferred} more held for later daily runs "
                                f"(cap {AUTO_POST_DAILY_CAP} auto-posts/day)"})
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
