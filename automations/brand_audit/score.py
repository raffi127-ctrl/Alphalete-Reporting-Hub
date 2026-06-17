"""Scoring engine — turn collected metrics into the metrics-that-matter and a
letter grade per section, plus an overall grade.

Design principles:
  * Every threshold/weight is a NAMED constant up top — no magic numbers buried
    in logic, so grades are explainable and tunable.
  * Each section records the human-readable reasons behind its score, so the
    report can show WHY a grade landed where it did (not just the letter).
  * A section with no real data is graded "N/A" — never faked. (Social, until a
    platform API is connected.)

Sections:
  Reviews          — Google rating + volume (+ response rate once Phase 3 lands)
  Reputation/Search— the differentiator: negative results/threads ranking for
                     the brand name. This is where a "4.8 stars" company can
                     still be in trouble.
  Website          — reachable + blog + content freshness.
  Social           — N/A in v1 (needs platform API).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---- grade bands (score 0-100 -> letter) -----------------------------------
_GRADE_BANDS = [
    (90, "A"), (85, "A-"), (80, "B+"), (75, "B"), (70, "B-"),
    (65, "C+"), (60, "C"), (55, "C-"), (50, "D+"), (45, "D"), (40, "D-"),
    (0, "F"),
]

# ---- Reviews weights --------------------------------------------------------
REV_RATING_FLOOR = 3.0          # rating at/below this earns 0 rating points
REV_RATING_TARGET = 4.8         # rating at/above this earns full rating points
REV_RATING_POINTS = 70          # (response-rate component deferred to Phase 3,
REV_VOLUME_POINTS = 30          #  so rating+volume are rescaled to 100)
REV_VOLUME_TIERS = [(500, 30), (200, 24), (50, 16), (10, 8), (1, 3)]
REV_NEG_PENALTY = 12            # per negative review in the sample

# ---- Reputation / Search weights -------------------------------------------
# Tuned so "page 1 is mostly yours + one negative" is a fixable C, not an F.
# A single old negative thread shouldn't tank a brand that otherwise owns the
# results and has strong reviews (Megan's call, 2026-06-17).
REP_NEG_ABOVE_OWN = 22          # a negative result ranking above the own site
REP_NEG_ON_PAGE1 = 12           # a negative result on page 1 but below own site
REP_REDDIT_NEG_EACH = 2         # per negative Reddit thread (often old / niche)
REP_REDDIT_NEG_CAP = 12
REP_OWN_NOT_FIRST = 6
REP_OWN_OFF_PAGE1 = 20

# ---- Website weights --------------------------------------------------------
WEB_NO_BLOG = 25
WEB_STALE_90 = 18
WEB_STALE_180 = 35
WEB_NOT_SECURE = 20   # no HTTPS — a trust + SEO problem

# ---- overall section weights (must cover the graded sections) ---------------
SECTION_WEIGHTS = {"reviews": 0.30, "reputation": 0.45, "website": 0.25}


def grade_from_score(score: float) -> str:
    for floor, letter in _GRADE_BANDS:
        if score >= floor:
            return letter
    return "F"


@dataclass
class SectionScore:
    key: str
    label: str
    score: float | None          # None => N/A (not graded)
    grade: str
    reasons: list[str] = field(default_factory=list)
    display: dict = field(default_factory=dict)   # chip metrics (fallback render)
    rows: list = field(default_factory=list)      # per-site table rows (reviews)
    respond: list = field(default_factory=list)   # below-5★ reviews + draft reply
    page1: list = field(default_factory=list)     # SERP page-1 w/ category (reputation)
    advice: list = field(default_factory=list)    # SEO/reputation action plan
    posts: list = field(default_factory=list)     # per-platform posts since audit (social)

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "score": self.score,
                "grade": self.grade, "reasons": self.reasons,
                "display": self.display, "rows": self.rows,
                "respond": self.respond, "page1": self.page1,
                "advice": self.advice, "posts": self.posts}


@dataclass
class Scorecard:
    overall_score: float
    overall_grade: str
    sections: list[SectionScore]
    flags: list[dict] = field(default_factory=list)   # all negative/warn flags

    def as_dict(self) -> dict:
        return {"overall_score": self.overall_score,
                "overall_grade": self.overall_grade,
                "sections": [s.as_dict() for s in self.sections],
                "flags": self.flags}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _volume_points(count):
    if not count:
        return 0
    for tier, pts in REV_VOLUME_TIERS:
        if count >= tier:
            return pts
    return 0


def _review_site_row(company_name, site, rating, total, *, readable,
                     below5=None, below5_partial=False):
    """One per-site row for the Reviews table. new_since_audit comes from the
    snapshot history; None until a prior audit exists."""
    from automations.brand_audit import review_history
    new_since = review_history.new_since_last_audit(company_name, site, total) \
        if readable else None
    return {"site": site, "rating": rating, "total": total,
            "new_since_audit": new_since, "below5": below5,
            "below5_partial": below5_partial, "readable": readable}


def _score_reviews(results: dict, company_name: str) -> SectionScore:
    google = (results.get("google_reviews") or {}).get("metrics") or {}
    gev = (results.get("google_reviews") or {}).get("evidence") or {}
    rep = (results.get("reputation") or {}).get("metrics") or {}
    serp_ratings = ((results.get("serp") or {}).get("metrics") or {}).get("serp_ratings") or {}

    def _site(name, rep_rating_key, rep_count_key, serp_key):
        # prefer the direct scrape; fall back to the Google rich-snippet rating
        rating = rep.get(rep_rating_key)
        count = rep.get(rep_count_key)
        if rating is None and serp_ratings.get(serp_key):
            rating = serp_ratings[serp_key].get("rating")
            count = count if count is not None else serp_ratings[serp_key].get("reviews")
        return rating, count

    rating = google.get("rating")
    count = google.get("review_count")
    neg = google.get("negative_in_sample") or 0
    reasons = []

    # --- per-site table rows -------------------------------------------------
    rows = [
        _review_site_row(company_name, "Google", rating, count, readable=True,
                         below5=google.get("below5_in_sample"),
                         below5_partial=True),  # only the 5-review sample
    ]
    gd_rating, gd_count = _site("Glassdoor", "glassdoor_rating",
                                "glassdoor_review_count", "glassdoor")
    in_rating, in_count = _site("Indeed", "indeed_rating",
                                "indeed_review_count", "indeed")
    rows.append(_review_site_row(company_name, "Glassdoor", gd_rating, gd_count,
                                 readable=gd_rating is not None))
    rows.append(_review_site_row(company_name, "Indeed", in_rating, in_count,
                                 readable=in_rating is not None))

    # --- below-5★ reviews to respond to (what we can currently see) ----------
    from automations.brand_audit.respond_draft import draft_reply
    respond = []
    for rv in (gev.get("reviews") or []):
        if isinstance(rv.get("rating"), (int, float)) and rv["rating"] < 5:
            respond.append({
                "site": "Google", "stars": rv["rating"],
                "author": rv.get("author", ""), "when": rv.get("when", ""),
                "snippet": (rv.get("text") or "")[:240],
                "draft": draft_reply(rv, company_name),
            })

    if rating is None:
        return SectionScore("reviews", "Reviews", None, "N/A",
                            ["No Google rating could be read."],
                            rows=rows, respond=respond)

    # --- grade (rating + volume; response-rate component deferred) -----------
    span = max(0.001, REV_RATING_TARGET - REV_RATING_FLOOR)
    rating_pts = _clamp((rating - REV_RATING_FLOOR) / span, 0, 1) * REV_RATING_POINTS
    vol_pts = _volume_points(count)
    penalty = neg * REV_NEG_PENALTY
    score = _clamp(rating_pts + vol_pts - penalty, 0, 100)

    reasons.append(f"Google {rating}★ across {count or 0} reviews.")
    if neg:
        reasons.append(f"{neg} negative review(s) in the recent sample (-{penalty}).")
    reasons.append("Below-5★ list + drafted replies fill in fully once the "
                   "Business Profile API is approved (Google's public API only "
                   "returns a 5-review sample).")
    return SectionScore("reviews", "Reviews", round(score),
                        grade_from_score(score), reasons, rows=rows,
                        respond=respond)


def _score_reputation(results: dict, company_name: str) -> SectionScore:
    serp = (results.get("serp") or {}).get("metrics") or {}
    sev = (results.get("serp") or {}).get("evidence") or {}
    reddit = (results.get("reddit") or {}).get("metrics") or {}
    website = (results.get("website") or {}).get("metrics") or {}
    google = dict((results.get("google_reviews") or {}).get("metrics") or {})
    google["_name"] = company_name   # so advice can use the brand name
    reasons = []
    score = 100.0

    own_pos = serp.get("own_site_position")
    on_page1 = serp.get("own_site_on_page1")
    neg_on_page1 = serp.get("negative_results_on_page1") or 0
    top_neg = serp.get("top_negative_position")

    if neg_on_page1:
        above_own = (own_pos is None) or (top_neg is not None and top_neg < own_pos)
        if above_own:
            score -= REP_NEG_ABOVE_OWN
            reasons.append(f"A negative result ranks #{top_neg} for your name — "
                           f"ABOVE your own site (-{REP_NEG_ABOVE_OWN}).")
        else:
            score -= REP_NEG_ON_PAGE1
            reasons.append(f"{neg_on_page1} negative result(s) on page 1 "
                           f"(-{REP_NEG_ON_PAGE1}).")

    neg_threads = reddit.get("negative_mentions") or 0
    if neg_threads:
        pen = min(neg_threads * REP_REDDIT_NEG_EACH, REP_REDDIT_NEG_CAP)
        score -= pen
        reasons.append(f"{neg_threads} negative Reddit thread(s) (-{pen}).")

    if not on_page1:
        score -= REP_OWN_OFF_PAGE1
        reasons.append(f"Your own site is not on page 1 (-{REP_OWN_OFF_PAGE1}).")
    elif own_pos and own_pos > 1:
        score -= REP_OWN_NOT_FIRST
        reasons.append(f"Your site ranks #{own_pos}, not #1 (-{REP_OWN_NOT_FIRST}).")

    if not reasons:
        reasons.append("Clean page 1, own site on top, no negative threads.")

    score = _clamp(score, 0, 100)
    display = {
        "own_site_position": own_pos,
        "brand_controlled_on_page1": serp.get("brand_controlled_count"),
        "negative_results_on_page1": neg_on_page1,
        "negative_reddit_threads": neg_threads,
        "has_knowledge_panel": serp.get("has_knowledge_panel"),
    }
    # top page-1 results with category (owned / profile / negative / neutral)
    page1 = [
        {"position": e.get("position"), "title": e.get("title"),
         "domain": e.get("domain"), "link": e.get("link"),
         "category": e.get("category")}
        for e in (sev.get("page1") or [])
    ]
    from automations.brand_audit.seo_advice import build_recommendations
    advice = build_recommendations(serp, reddit, website, google)
    return SectionScore("reputation", "Reputation / Search", round(score),
                        grade_from_score(score), reasons, display,
                        page1=page1, advice=advice)


def _score_website(web: dict) -> SectionScore:
    reasons = []
    if not web.get("reachable"):
        return SectionScore("website", "Website", 0, "F",
                            [f"Website not reachable (status "
                             f"{web.get('http_status')})."],
                            {"reachable": False})
    score = 100.0
    if web.get("secure_https") is False:
        score -= WEB_NOT_SECURE
        reasons.append(f"Not served over HTTPS (-{WEB_NOT_SECURE}).")
    if not web.get("has_blog"):
        score -= WEB_NO_BLOG
        reasons.append(f"No blog detected (-{WEB_NO_BLOG}).")
    age = web.get("newest_content_age_days")
    if age is not None:
        if age > 180:
            score -= WEB_STALE_180
            reasons.append(f"Newest content ~{age} days old (-{WEB_STALE_180}).")
        elif age > 90:
            score -= WEB_STALE_90
            reasons.append(f"Newest content ~{age} days old (-{WEB_STALE_90}).")
        else:
            reasons.append(f"Fresh — newest content ~{age} days old.")
    recent = web.get("pages_updated_90d")
    if recent:
        reasons.append(f"{recent} page(s) updated in the last 90 days — actively maintained.")
    if web.get("has_blog") and web.get("secure_https") and (age is None or age <= 90):
        reasons.insert(0, "Up, secure, has a blog, content is fresh.")
    score = _clamp(score, 0, 100)
    display = {"reachable": True, "secure_https": web.get("secure_https"),
               "has_blog": web.get("has_blog"),
               "blog_post_count": web.get("blog_post_count"),
               "newest_content_age_days": age,
               "pages_updated_90d": recent,
               "sitemap_url_count": web.get("sitemap_url_count")}
    return SectionScore("website", "Website", round(score),
                        grade_from_score(score), reasons, display)


def _score_social(results: dict) -> SectionScore:
    social = (results.get("social_public") or {}).get("metrics") or {}
    ev = (results.get("social_public") or {}).get("evidence") or {}
    channels = ev.get("channels") or {}

    connected = [c["label"] for c in channels.values() if c.get("connected")]
    postable = [c["label"] for c in channels.values() if c.get("postable")]
    blocked = [c["label"] for c in channels.values()
               if c.get("connected") and not c.get("postable")]

    # Per-platform "posts since last audit" — structure now, fills in once a
    # platform API / aggregator is connected (post counts aren't on public pages).
    posts_rows = [
        {"platform": c["label"],
         "posts_since_audit": c.get("posts_since_audit")}   # None until API
        for c in channels.values() if c.get("connected")
    ]

    reasons = [f"Present on {len(connected)} platform(s): "
               + (", ".join(connected) or "none") + "."]
    if blocked:
        reasons.append("Excluded from posting (by rule): "
                       + ", ".join(blocked) + ".")
    reasons.append("Posts-since-last-audit, engagement, and followers need a "
                   "platform API (Meta) or aggregator — not on public pages, so "
                   "this stays N/A until one is connected.")
    display = {
        "channels_connected": len(connected),
        "postable_channels": len(postable),
        "followers_total": social.get("followers_total"),     # None until API
        "avg_engagement_rate": social.get("avg_engagement_rate"),
    }
    return SectionScore("social", "Social", None, "N/A", reasons, display,
                        posts=posts_rows)


def build_scorecard(results: dict, company_name: str = "") -> Scorecard:
    """results: {source_name: CollectorResult.as_dict()}."""
    def m(src):
        return (results.get(src) or {}).get("metrics") or {}

    sections = [
        _score_reviews(results, company_name),
        _score_reputation(results, company_name),
        _score_website(m("website")),
        _score_social(results),
    ]

    # overall = weighted mean of graded sections (skip N/A), reweighted to the
    # sections we actually have.
    graded = [s for s in sections if s.score is not None and s.key in SECTION_WEIGHTS]
    wsum = sum(SECTION_WEIGHTS[s.key] for s in graded) or 1.0
    overall = sum(s.score * SECTION_WEIGHTS[s.key] for s in graded) / wsum

    # collect every negative/warn flag for the alerts + "needs attention" list
    flags = []
    for src, r in results.items():
        for f in (r or {}).get("flags", []):
            if f.get("level") in ("negative", "warn"):
                flags.append({**f, "source": src})

    return Scorecard(round(overall), grade_from_score(overall), sections, flags)
