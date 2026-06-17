"""Turn the audit data into a concrete, plain-English action list — what the ICD
actually DOES this week, not SEO strategy.

Each item: {priority, action (verb-first, jargon-free), who, result}. Generated
from THIS run's data so it stays specific and honest. No "H1 / schema /
backlink" jargon — anything technical is phrased as "ask your web person to…".
"""
from __future__ import annotations


def build_recommendations(serp: dict, reddit: dict, website: dict,
                          google: dict) -> list[dict]:
    recs: list[dict] = []
    name = google.get("_name") or "your company"

    own_pos = serp.get("own_site_position")
    top_neg = serp.get("top_negative_position")
    neg_on_page1 = serp.get("negative_results_on_page1") or 0
    has_panel = serp.get("has_knowledge_panel")
    neg_threads = reddit.get("negative_mentions") or 0
    has_blog = website.get("has_blog")

    negative_outranks_own = neg_on_page1 and (
        own_pos is None or (top_neg is not None and top_neg < own_pos))

    if negative_outranks_own:
        recs.append({
            "priority": "High",
            "action": f'Put one page on {name}\'s website titled like "Working '
                      f'at {name} — what to really expect" that honestly answers '
                      f'the questions people ask in that #%s Reddit thread.'
                      % (top_neg or 1),
            "who": "ICD writes the honest answers → web person posts the page",
            "result": "Gives Google a page of YOURS to show instead of the "
                      "Reddit thread.",
        })
        recs.append({
            "priority": "High",
            "action": "Post in your own subreddit once a week (even a short "
                      "update or a customer win).",
            "who": "ICD",
            "result": "Active subreddits climb in Google — yours can move above "
                      "the negative thread.",
        })

    recs.append({
        "priority": "High" if negative_outranks_own else "Medium",
        "action": "Ask 10 happy customers to leave a Google review this week "
                  "(text them the review link right after the sale).",
        "who": "ICD + reps",
        "result": "More fresh 5★ reviews keep your %s rating strong and front-"
                  "and-center." % (google.get("rating") or "high"),
    })

    if own_pos and own_pos > 1:
        recs.append({
            "priority": "Medium",
            "action": f'Ask whoever runs the website to make the homepage title '
                      f'and the big heading say exactly "{name}".',
            "who": "Web person (ICD forwards this)",
            "result": "Helps your own site beat the Reddit thread for the #1 "
                      "spot (you're #%s now)." % own_pos,
        })

    if not has_panel:
        recs.append({
            "priority": "Medium",
            "action": "Claim and fully fill out your Google Business Profile "
                      "(photos, hours, description).",
            "who": "ICD",
            "result": "Unlocks the info box on the right of Google — branded "
                      "space that's yours.",
        })

    if neg_threads:
        recs.append({
            "priority": "Low",
            "action": "Never argue inside the negative Reddit threads — answer "
                      "the concerns in your OWN content instead.",
            "who": "ICD",
            "result": "Arguing ranks the thread higher; owned answers outrank it.",
        })

    return recs
