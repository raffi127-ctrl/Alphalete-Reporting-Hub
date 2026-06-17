"""Real Instagram + Facebook performance via the Meta Graph API.

Uses a stored Page token + IG business account id (see ~/.config/brand-audit/
keys.json). Pulls recent posts with likes/comments/dates, computes last-7-days
counts + engagement, flags a stalled channel, and asks Claude for short
performance feedback. FAILS SOFT if Meta isn't connected (most tenants won't be
at first) — the Social section just stays on its public-only view.

Scopes used: instagram_basic + pages_read_engagement (likes/comments/dates).
Reach/impressions would need instagram_manage_insights (not yet granted).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import requests

from automations.brand_audit import credentials
from automations.brand_audit.collectors.base import CollectorResult, WARN, INFO

SOURCE = "social_meta"
GRAPH = "https://graph.facebook.com/v23.0"


def _get(path: str, token: str, **params):
    params["access_token"] = token
    return requests.get(f"{GRAPH}/{path}", params=params, timeout=25).json()


def _age_days(iso: str) -> int | None:
    try:
        dt = datetime.fromisoformat(iso.replace("+0000", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return None


def _recent(items, ts_key, days=7):
    cut = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for m in items:
        try:
            if datetime.fromisoformat(m[ts_key].replace("+0000", "+00:00")) >= cut:
                out.append(m)
        except Exception:
            continue
    return out


def _instagram(token: str, ig_id: str) -> dict | None:
    r = _get(f"{ig_id}/media", token, limit=30,
             fields="caption,media_type,timestamp,like_count,comments_count,permalink")
    if "error" in r:
        return None
    media = r.get("data", [])
    prof = _get(ig_id, token, fields="followers_count,media_count")
    followers = prof.get("followers_count")
    recent = _recent(media, "timestamp")
    ages = [_age_days(m["timestamp"]) for m in media if m.get("timestamp")]
    last_age = min([a for a in ages if a is not None], default=None)
    # engagement over the most recent ~9 posts (stable sample)
    sample = media[:9]
    likes = [m.get("like_count") or 0 for m in sample]
    comments = [m.get("comments_count") or 0 for m in sample]
    avg_eng = (sum(likes) + sum(comments)) / len(sample) if sample else 0
    eng_rate = round(avg_eng / followers * 100, 2) if followers else None
    return {
        "followers": followers,
        "posts_last_7d": len(recent),
        "last_post_age_days": last_age,
        "avg_likes": round(sum(likes) / len(sample)) if sample else 0,
        "avg_comments": round(sum(comments) / len(sample)) if sample else 0,
        "engagement_rate_pct": eng_rate,
        "recent": [{"age_days": _age_days(m.get("timestamp", "")),
                    "type": m.get("media_type"),
                    "likes": m.get("like_count"), "comments": m.get("comments_count"),
                    "caption": (m.get("caption") or "")[:140]} for m in media[:10]],
    }


def _facebook(token: str, page_id: str) -> dict | None:
    r = _get(f"{page_id}/feed", token, limit=30,
             fields="created_time,message,reactions.summary(true),comments.summary(true)")
    if "error" in r:
        return None
    posts = r.get("data", [])
    recent = _recent(posts, "created_time")
    ages = [_age_days(p["created_time"]) for p in posts if p.get("created_time")]
    last_age = min([a for a in ages if a is not None], default=None)
    sample = posts[:9]
    reacts = [(p.get("reactions") or {}).get("summary", {}).get("total_count", 0) for p in sample]
    comments = [(p.get("comments") or {}).get("summary", {}).get("total_count", 0) for p in sample]
    return {
        "posts_last_7d": len(recent),
        "last_post_age_days": last_age,
        "avg_reactions": round(sum(reacts) / len(sample)) if sample else 0,
        "avg_comments": round(sum(comments) / len(sample)) if sample else 0,
    }


def _feedback(company, ig: dict | None, fb: dict | None) -> str:
    try:
        import anthropic, json
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
        data = {"instagram": ig, "facebook": fb}
        resp = client.messages.create(
            model="claude-opus-4-8", max_tokens=400,
            system=("You give a sales/marketing owner blunt, plain-language "
                    "feedback on their social performance. 2-4 sentences. No "
                    "fluff, no jargon. Focus on what the numbers mean and what to "
                    "do. Their IG target audience skews young (20-25)."),
            messages=[{"role": "user", "content":
                       f"{company.name} social performance (last posts):\n"
                       f"{json.dumps(data, indent=1)}\n\nGive the owner feedback."}])
        return next((b.text for b in resp.content if b.type == "text"), "")
    except Exception:
        return ""


def collect(company) -> CollectorResult:
    res = CollectorResult(source=SOURCE)
    token = credentials.optional("facebook_page_token")
    ig_id = credentials.optional("ig_business_account_id")
    page_id = credentials.optional("facebook_page_id")
    if not token:
        res.ok = False
        res.error = "Meta not connected (no facebook_page_token)"
        return res

    ig = _instagram(token, ig_id) if ig_id else None
    fb = _facebook(token, page_id) if page_id else None
    if ig is None and fb is None:
        return CollectorResult.failed(SOURCE, "Meta token present but no data "
                                              "(check token/permissions)")

    res.metrics = {"instagram": ig, "facebook": fb}
    res.evidence["feedback"] = _feedback(company, ig, fb)

    # flags: stalled channel + weak engagement
    if ig:
        if ig.get("last_post_age_days") is not None and ig["last_post_age_days"] > 14:
            res.flag(WARN, f"Instagram has gone quiet — last post "
                           f"{ig['last_post_age_days']} days ago.")
        er = ig.get("engagement_rate_pct")
        if er is not None and er < 0.5 and (ig.get("followers") or 0) > 5000:
            res.flag(INFO, f"Low IG engagement (~{er}% of {ig['followers']:,} "
                           "followers) — worth checking reach/audience quality.")
    return res
