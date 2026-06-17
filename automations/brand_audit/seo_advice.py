"""Dead-simple, copy-paste SEO/reputation actions for the ICD.

The ICD is a sales owner, not a marketer — every action is written like you're
explaining it to a 7-year-old: a plain title, numbered tap-by-tap steps, and
(where it helps) the EXACT words to copy and paste. No jargon, no "do this and
maybe that" — one clear thing to do.

Each item: {priority, title, who, steps: [str, ...], paste: str|""}.
"""
from __future__ import annotations


# Reviews this strong don't need a "go get more" nudge — surface that action
# only when the rating or volume is actually weak (named, tunable).
REVIEWS_STRONG_RATING = 4.3
REVIEWS_STRONG_COUNT = 100


def build_recommendations(serp: dict, reddit: dict, website: dict, google: dict,
                          *, subreddit: str = "", website_url: str = "",
                          review_link: str = "") -> list[dict]:
    name = google.get("_name") or "your company"
    sub = subreddit or "yoursubreddit"
    site = website_url or "your website"
    review_link = review_link or "(your Google review link)"

    own_pos = serp.get("own_site_position")
    top_neg = serp.get("top_negative_position")
    neg_on_page1 = serp.get("negative_results_on_page1") or 0
    negative_outranks_own = neg_on_page1 and (
        own_pos is None or (top_neg is not None and top_neg < own_pos))

    rating = google.get("rating")
    count = google.get("review_count") or 0
    reviews_strong = (rating is not None and rating >= REVIEWS_STRONG_RATING
                      and count >= REVIEWS_STRONG_COUNT)

    recs: list[dict] = []

    # 1) Get more Google reviews — ONLY when reviews are actually weak. A brand
    # that already pulls strong reviews routinely doesn't need this nudge.
    if not reviews_strong:
        recs.append({
            "priority": "Do this first",
            "title": "Text 10 happy customers and ask for a Google review",
            "who": "You (and your reps)",
            "steps": [
                "Open the text messages on your phone.",
                "Pick 10 customers who were happy.",
                "Copy the message below.",
                "Send it to each one — change [first name] to their name.",
                "Send the link too (it opens straight to leaving a review).",
            ],
            "paste": (f"Hi [first name]! Thanks again for choosing {name}. If you "
                      f"have 30 seconds, leaving us a quick Google review would "
                      f"mean a lot: {review_link}"),
        })

    # 2) Post in the company's own subreddit (uses the weekly draft we send).
    recs.append({
        "priority": "Do this weekly",
        "title": "Post once a week in your Reddit group",
        "who": "You",
        "steps": [
            f"Open Reddit and go to: reddit.com/r/{sub}",
            "Log in.",
            "Tap the button that says \"Create Post\".",
            "Open your Slack channel #alphaletemarketingbrandhealth — copy the "
            "post we wrote for you there.",
            "Paste it in, then tap \"Post\".",
        ],
        "paste": "",
    })

    # 3) Only if a negative result sits above the owned site: get a page up.
    if negative_outranks_own:
        recs.append({
            "priority": "Important",
            "title": "Ask your website person to add one new page",
            "who": "Forward this to whoever runs the website",
            "steps": [
                "Open your email or text to your website person.",
                "Copy the message below and send it to them.",
                "That's it — they do the rest.",
            ],
            "paste": (
                f"Hey — can you add a new page to {site} titled \"Working at "
                f"{name} — what it's really like\"? Please make the page's title "
                f"and big heading say \"{name}\" exactly. I'll send you the words "
                f"to put on it. Goal: it should show up on Google when people "
                f"search our company name. Thanks!"),
        })

    return recs
