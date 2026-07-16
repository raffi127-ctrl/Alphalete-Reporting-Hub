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
    AUTO_POST_MIN_STARS, AUTO_POST_DAILY_CAP, REVIEW_REPLY_CONTACT,
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


def _positive_system(company_name: str) -> str:
    """Voice for 4-5★ replies: warm, human, off-the-cuff. These auto-post."""
    return (
        f"You write {company_name}'s public reply to a POSITIVE Google review. "
        "Warm, genuine, professional, and CONCISE (1-3 sentences). Sound like a "
        "real person from the team, not corporate. Thank them and use their "
        "first name if given. Never share private details, never use jargon or "
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


def _negative_system(company_name: str) -> str:
    """Voice for 1-3★ replies — DELIBERATELY different from the positive voice.

    Modeled on the replies Alphalete actually posts (Luke 7/16, Mladen 6/23,
    Hisham 1/5, Ashley 12/15). These reviews are mostly ex-employees/applicants
    making serious public allegations (unpaid wages, being misled, scam/MLM/cult
    claims), so the reply is a legal + reputational document, not a friendly
    note. The cardinal rule is NEVER concede the allegation — an earlier warm
    voice ("being unpaid for days of real work is not okay") publicly admitted
    fault and was rejected across the board (Megan, 2026-07-16)."""
    return (
        f"You write {company_name}'s PUBLIC reply to a CRITICAL Google review "
        "(1-3 stars). This is a legal and reputational statement on a permanent "
        "public record that future applicants and customers will read. It is NOT "
        "a casual or friendly note. Match the house style exactly.\n\n"
        "VOICE: the company speaking as 'we'/'our'. NEVER 'I' or 'me'. "
        "Professional, measured, calm, respectful. No slang, no jokes, no "
        "casual phrasing, no emotional or effusive language.\n\n"
        "**NEVER ADMIT FAULT OR TREAT AN ALLEGATION AS FACT — the most important "
        "rule.** Do NOT agree that the reviewer was unpaid or underpaid, scammed, "
        "lied to, misled, discriminated against, overcharged, or mistreated. NEVER "
        "write anything like 'that's not okay', 'that should never have happened', "
        "'you're right', 'we failed you', 'that isn't how our reps should behave', "
        "or 'the numbers you describe aren't right'. Instead acknowledge only that "
        "they RAISED a concern, without conceding it happened: 'We understand your "
        "concerns regarding scheduling and the recruitment process.' You may say "
        "you regret their experience did not meet their expectations, but never "
        "accept the factual claim.\n\n"
        "CORRECT DAMAGING FALSE CLAIMS calmly and factually — never defensively, "
        "never argue. If the review calls the company a cult, MLM, pyramid or "
        "scam, or alleges illegal practices, state plainly what the company is: a "
        "direct marketing company focused on customer acquisition, professional "
        "development and merit-based advancement; a performance-based agency "
        "serving clients in the telecom and energy sectors; a model based on "
        "client services and performance rather than recruitment.\n\n"
        "REINFORCE THE STANDARD: that the company strives for transparency about "
        "role responsibilities, compensation, scheduling expectations and career "
        "opportunities, and emphasizes structured training and coaching.\n\n"
        "TAKE IT OFFLINE: direct them to contact "
        f"{REVIEW_REPLY_CONTACT or 'the company directly'} so the concern can be "
        "reviewed through the appropriate internal process. Phrase this plainly "
        "and professionally, e.g. 'We would appreciate the opportunity to review "
        f"your concerns directly. Please contact {REVIEW_REPLY_CONTACT}.' "
        "NEVER use tentative, pleading or casual phrasing for this. Banned "
        "outright: \"If you're willing, email me at\", \"if you're open to it\", "
        "\"feel free to\", \"shoot us an email\", \"if you'd like\", \"we'd love "
        "to hear\". It is never 'me' or 'I' — the company is asking, so it is "
        "always 'us'/'we'.\n\n"
        "LENGTH: a detailed or serious review gets 2-3 short paragraphs. A brief "
        "review, or a rating with no text, gets ONE short paragraph. Open with "
        "the reviewer's first name. Never name employees, never share private "
        "details, never be sarcastic.\n\n"
        "END EVERY REPLY EXACTLY WITH:\n\nWarm Regards,\nAlphalete Marketing")


def draft_reply(review: dict, company_name: str, feedback: str = "",
                avoid: list[str] | None = None) -> str:
    """Draft the business's public reply to one review. Positive and critical
    reviews get DIFFERENT voices (see _positive_system / _negative_system)."""
    import anthropic
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    stars = review.get("rating")
    negative = isinstance(stars, (int, float)) and stars < AUTO_POST_MIN_STARS
    system = (_negative_system(company_name) if negative
              else _positive_system(company_name))
    user = (f"Review — {stars}★ from {review.get('author') or 'a customer'}:\n"
            f"\"{review.get('text') or '(no text, just a rating)'}\"\n\n"
            "Write the reply.")
    if feedback:
        user += f"\n\nThe approver rejected the last draft — apply this: \"{feedback}\"."
    # Variety matters for POSITIVE replies (each should read individually
    # written). Critical replies are the opposite: the house style is
    # deliberately consistent (same measured framing, identical sign-off), so
    # don't push them to differ — only the specifics of the concern change.
    if avoid and not negative:
        user += ("\n\nDo NOT reuse the wording or structure of these other "
                 "recent replies — make this one clearly different (and don't "
                 "repeat words like 'thrilled' that appear in them):\n"
                 + "\n".join(f"- {a}" for a in avoid if a))
    resp = client.messages.create(
        model=MODEL, max_tokens=700 if negative else 300, system=system,
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
            f":x: + a note to redo, :skull: to scrap it and bring it back "
            f"fresh:\n{reply}")


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
    resurface = []   # 💀'd reviews: forget them so they come back for a fresh reply
    for k, st in state["reviews"].items():
        if st.get("posted") or st.get("skipped") or not st.get("reply_ts"):
            continue
        rv = st.get("review") or {}
        rx = _thread_reactions(cl, st["reply_ts"]).get(st["reply_ts"])
        if _reacted(rx, SOCIAL_KILL_EMOJI):
            # UNLIKE the social-post workflow, 💀 does NOT kill a review — every
            # review still needs a response. Drop its handled-state so the next
            # scan re-drafts it fresh and it comes back up on the list.
            resurface.append(k)
            actions.append({"action": "resurface", "review": k})
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

    # drop 💀'd reviews from state AFTER the loop (can't mutate mid-iteration) so
    # the next scan sees them as new and drafts a fresh reply.
    for k in resurface:
        state["reviews"].pop(k, None)

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
