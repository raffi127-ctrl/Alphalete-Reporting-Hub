"""The weekly card an office actually reads: four lines and a to-do list.

Megan 2026-11-09: "this card is way too busy ... make it super simple - 7
year old simple rule". So no grades, no scores, no tables, no jargon:

    🟢/🟡/🔴  ⭐ Google reviews        4.8 ★ · 820 reviews · 3 new this week
    🟢/🟡/🔴  🔎 When people Google you   Your website is #2 · no negative results on page 1
    🟢/🟡/🔴  📸 Posts this week        4 posts went out
    🟢/🟡/🔴  ✅ Your info online       Everything matches

    Do this week
      1. ...   (at most 3, plainest first)

Every number comes from a real source: Google's own review list (we're a
Manager on the listing), a logged-out Google search (SerpAPI), Lucy's own
record of what posted, and the sign-up-vs-internet check (consistency.py).
A source Lucy couldn't read says so -- it is never shown as a pass.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

GREEN, YELLOW, RED, GREY = "green", "yellow", "red", "grey"

# Platform badges for the posts line: the pages Lucy posts to for this office
# (Megan 2026-11-09). Drawn here (a colored tile + the platform's own letter
# mark), so the card never depends on an outside image loading.
BADGE = {"instagram": ("IG", "linear-gradient(45deg,#F58529,#DD2A7B,#8134AF)", "Instagram"),
         "facebook": ("f", "#1877F2", "Facebook"),
         "google": ("G", "#4285F4", "Google"),
         "linkedin": ("in", "#0A66C2", "LinkedIn"),
         "x": ("X", "#000000", "X")}
# Alphalete posts through its own Zoho; these are the pages connected there
# (confirmed 2026-11-09; LinkedIn isn't connected).
ALPHALETE_PAGES = ("instagram", "facebook", "google", "x")
DOT = {GREEN: "#22A35A", YELLOW: "#E8A317", RED: "#D93A3A", GREY: "#9AA0A6"}

# Plain-English fixes for the sign-up check's items.
FIX = {
    "address": "Fix the address on {site} so it matches yours",
    "phone": "Fix the phone number on {site}",
    "website": "Fix the website link on {site}",
    "website link is secure (https)": "Change your website link on Google to start with https://",
    "business name": "Make your business name on {site} match",
    "listing verified": "Finish verifying your Google listing",
    "site loads": "Your website isn't loading: call whoever runs it",
}


# THE REASON BEHIND EVERY PIECE OF ADVICE (Megan 2026-11-09: "we always want
# to have reasons behind advise"). Plain words, one or two sentences each.
WHY_FIX = {
    "website link is secure (https)":
        "Google and phones flag sites without https as \"Not secure\", and some people "
        "won't click a link that looks unsafe. It's free to change and takes a minute.",
    "address": "Google, Indeed and your website should all show the same address. When "
               "they don't match, Google trusts your listing less and shows it to fewer people.",
    "phone": "A wrong number on any site means a lost call: customers and applicants "
             "dial what Google shows them.",
    "website": "If Google links to the wrong site, the people who search you never "
               "reach your real page.",
    "business name": "Your name should be spelled the same everywhere so Google knows "
                     "it's all the same business.",
    "listing verified": "An unverified Google listing can't post replies or updates, "
                        "and shows up less in Maps.",
    "site loads": "When your website doesn't open, anyone who searches you sees an error "
                  "instead of you.",
    "_": "When your details differ between sites, Google trusts your listing less and "
         "people get confused about which is right.",
}
# HOW TO DO IT (Megan 2026-11-09: "a 'how to' section on the technical stuff").
# Short numbered steps a non-technical owner can follow on their phone.
HOW_FIX = {
    "website link is secure (https)": [
        "First check your site works with it: open https:// plus your website in your "
        "browser. If it opens with a 🔒 lock, you're good. If it shows an error, text "
        "your website person: \"Can you turn on SSL (https) for our site?\" It's free. "
        "Do the steps below once they say it's on.",
        "On your phone, search your business name on Google and tap \"Edit profile\" "
        "(or go to business.google.com).",
        "Tap \"Contact\", then \"Website\".",
        "Put https:// in front of the link, like https://yourcompany.com",
        "Tap \"Save\". Google takes a day or two to show it.",
    ],
    "listing verified": [
        "Go to business.google.com and sign in with the account that owns your listing.",
        "Tap \"Get verified\" and pick the option Google offers (video, call or postcard).",
        "Follow Google's steps. Lucy sees it the next Friday.",
    ],
    "_google": [
        "On your phone, search your business name on Google and tap \"Edit profile\" "
        "(or go to business.google.com).",
        "Find the wrong item (name, address, phone or website) and fix it so it matches "
        "your sign-up.",
        "Tap \"Save\". Google may take a few days to approve the change.",
    ],
    "_other": [
        "Sign in to that site as your business.",
        "Find your business details and fix the wrong item so it matches your sign-up.",
        "Save. Lucy re-checks it next Friday.",
    ],
}
HOW = {
    "bad_review": ["Tap your Slack channel above to open it.",
                   "Read Lucy's reply under the review.",
                   "React ✅ to post it, or ❌ and type what you'd change."],
    "photos": ["Tap your Slack channel above to open it.",
               "Tap the pinned 📸 New post button.",
               "Add your photo(s). Every photo you add goes in that ONE post. For "
               "another post, tap New post again.",
               "Say who's in it and what's happening, then tap Submit.",
               "Lucy edits every photo, writes the caption, and asks for your ✅ "
               "before anything posts."],
    "reviews": ["Tap your review link above and copy it.",
                "Text it to your new leaders and ask them to write about the team.",
                "Text it to this week's happy customers too. A mix of both reads best.",
                "Keep it short: \"Would you leave us a quick Google review? It helps a ton!\""],
}


# Megan 2026-11-09: "most icds have a person who will edit their websites".
# Anything ON their website is a job for that person: the card hands the ICD a
# ready message to forward instead of steps they'd never do themselves.
PAGE_NAME = {"instagram": "Instagram", "facebook": "Facebook", "tiktok": "TikTok", "x": "X",
             "linkedin": "LinkedIn", "youtube": "YouTube", "google": "Google"}


def _page(item: str) -> str:
    p = item[len("links to their "):]
    return PAGE_NAME.get(p.lower(), p)


def website_ask(r: Dict) -> str:
    item, want = r["item"], (r.get("expected") or "").strip()
    if item == "site loads":
        return "Our website isn't loading. Can you take a look today?"
    if item == "phone":
        return f"Can you update the phone number on our website to {want}?"
    if item == "address":
        return f"Can you update the address on our website to {want}?"
    if item.startswith("links to their "):
        page = _page(item)
        return (f"Can you add a link to our {page} page on the website" +
                (f": {want}" if want else "") + "?")
    return f"Can you fix the {item} on our website" + (f" (it should be {want})" if want else "") + "?"


def _how(r: Dict) -> List[str]:
    item, site = r["item"], (r.get("site") or "")
    if site.lower() == "website":
        return ["Text or email your website person (whoever edits your site) this message:",
                f"\u201c{website_ask(r)}\u201d",
                "That's it. Lucy re-checks your site next Friday."]
    if item in HOW_FIX:
        return HOW_FIX[item]
    return HOW_FIX["_google" if "google" in site.lower() else "_other"]


WHY = {
    "bad_review": "People read the bad reviews first. A calm, professional reply shows "
                  "every future customer and applicant that you care, even if you can't "
                  "change the review.",
    "photos": "Pages that post every week look active and real. Applicants check your "
              "pages before they show up, and an empty feed looks like nobody's there. "
              "Telling Lucy who's in it and what's happening lets her write a "
              "caption that's true to what happened.",
    "reviews": "New reviews push your rating up, show Google you're active, and help push "
               "negative search results further down. Happy customers rarely review unless you ask.",
}


# ---- the four lines ------------------------------------------------------------
def _answers(p) -> Dict[str, str]:
    """Lucy's drafted replies still waiting on an approver, by review id."""
    import json
    try:
        st = json.loads(p.path("review_replies.json").read_text())
    except Exception:
        return {}
    out = {}
    for v in (st.get("reviews") or {}).values():
        rv = v.get("review") or {}
        if not v.get("posted") and rv.get("review_id"):
            out[rv["review_id"]] = v.get("reply", "")
    return out


def google_line(p, now: dt.datetime, days: int = 7) -> Dict:
    from automations.brand_audit import gbp_api
    if not p.gbp_location:
        return {"color": GREY, "text": "Lucy can't see your Google reviews yet"}
    try:
        revs = gbp_api.list_reviews(p.gbp_location)
    except Exception:
        return {"color": GREY, "text": "Couldn't read Google this week"}
    stars = [r["rating"] for r in revs if isinstance(r.get("rating"), (int, float))]
    week = (now - dt.timedelta(days=days)).isoformat()
    new = [r for r in revs if (r.get("publish_time") or "") >= week]
    waiting = _answers(p)
    listing = []
    for r in sorted(new, key=lambda r: r.get("publish_time") or "", reverse=True):
        if r.get("has_reply"):
            status, reply = "replied", r.get("existing_reply", "")
        elif r.get("review_id") in waiting:
            status, reply = "waiting", waiting[r["review_id"]]
        else:
            status, reply = "none", ""
        listing.append({"stars": r.get("rating"), "author": r.get("author") or "Someone",
                        "text": (r.get("text") or "").strip(), "when": (r.get("publish_time") or "")[:10],
                        "status": status, "reply": reply})
    bad = [r for r in new if isinstance(r.get("rating"), (int, float)) and r["rating"] < 4]
    avg = sum(stars) / len(stars) if stars else 0
    # WHERE THEY STOOD LAST WEEK (Megan 2026-11-09): the same numbers counting
    # only reviews that already existed 7 days ago -- no saved history needed.
    cut = (now - dt.timedelta(days=7)).isoformat()
    before = [r["rating"] for r in revs if (r.get("publish_time") or "") < cut
              and isinstance(r.get("rating"), (int, float))]
    prev = {"avg": round(sum(before) / len(before), 1) if before else 0, "count": len(before)}
    span = "this week" if days == 7 else f"in the last {days} days"
    text = f"{avg:.1f} ★ · {len(revs)} reviews · {len(new)} new {span}"
    if bad:
        text += f" ({len(bad)} bad)"
    # Only an UNANSWERED bad review is red / a to-do; one already answered is done.
    open_bad = [r for r in listing if isinstance(r["stars"], (int, float)) and r["stars"] < 4
                and r["status"] != "replied"]
    color = RED if open_bad else (YELLOW if not new else GREEN)
    return {"color": color, "text": text, "new": len(new), "bad": len(open_bad),
            "reviews": listing, "avg": round(avg, 1), "count": len(revs), "prev": prev,
            "_revs": revs}


GREEN_KINDS = ("owned", "profile")   # results that count as theirs


# Short "what is it" label for each top-5 result (Megan 2026-11-11: "-Your
# Indeed (Reviews)", "-Your Website", "-Reddit").
SITE_NAMES = {"indeed.com": "Indeed", "glassdoor.com": "Glassdoor", "ziprecruiter.com": "ZipRecruiter",
              "linkedin.com": "LinkedIn", "facebook.com": "Facebook", "instagram.com": "Instagram",
              "tiktok.com": "TikTok", "x.com": "X", "twitter.com": "X", "youtube.com": "YouTube",
              "reddit.com": "Reddit", "yelp.com": "Yelp", "bbb.org": "BBB", "smartrecruiters.com": "SmartRecruiters",
              "google.com": "Google", "mapquest.com": "MapQuest", "comparably.com": "Comparably",
              "trustpilot.com": "Trustpilot", "yellowpages.com": "Yellow Pages", "simplyhired.com": "SimplyHired"}
JOB_SITES = ("indeed.com", "glassdoor.com", "ziprecruiter.com", "linkedin.com", "smartrecruiters.com",
             "simplyhired.com", "comparably.com")


def result_label(r: Dict) -> str:
    dom = (r.get("domain") or "").lower()
    if r.get("kind") == "owned":
        return "Your website"
    base = next((d for d in SITE_NAMES if dom == d or dom.endswith("." + d)), None)
    name = SITE_NAMES[base] if base else (dom.split(".")[-2].title() if dom.count(".") else dom or "A website")
    what = ""
    if base in JOB_SITES:
        link, title = (r.get("link") or "").lower(), (r.get("title") or "").lower()
        if any(w in link for w in ("/reviews", "/salaries", "/benefits")) or "review" in title:
            what = " - Reviews"
        elif any(w in link for w in ("/jobs", "/job/", "/viewjob", "careers.")) or any(
                w in title for w in ("job", "hiring", "career", "representative")):
            what = " - Job listings"
    return (f"Your {name}" if r.get("kind") == "profile" else name) + what


def search_line(p) -> Dict:
    from automations.brand_audit.collectors import serp
    from automations.online_presence.weekly_card import company_for
    try:
        d = serp.collect(company_for(p)).as_dict()
        m = d.get("metrics") or {}
        page1 = (d.get("evidence") or {}).get("page1") or []
        profiles = (d.get("evidence") or {}).get("profiles") or []
    except Exception:
        m, page1, profiles = {}, [], []
    # The top 5 Google results for their name, as people see them (Megan
    # 2026-11-10: "this should say what the top 5 results are and if it's bad
    # be red").
    top = [{"pos": r.get("position"), "title": r.get("title") or r.get("domain") or "",
            "domain": r.get("domain") or "", "link": r.get("link") or "",
            "kind": r.get("category") or "neutral"} for r in page1[:5]]
    if not m:
        return {"color": GREY, "text": "Couldn't search Google this week"}
    own, neg = m.get("own_site_position"), m.get("top_negative_position")
    # The goal is all 5 green -- their own site or pages. Where the website
    # itself lands doesn't matter (Megan 2026-11-11).
    green = sum(1 for r in top if r["kind"] in GREEN_KINDS)
    neg_top = any(r["kind"] == "negative" for r in top)
    color = RED if neg_top else (GREEN if top and green == len(top) else YELLOW)
    text = f"{green} of the top {len(top) or 5} on Google are yours" + (
        f" · a negative result is #{neg}" if neg_top else "")
    return {"color": color, "text": text, "own": own, "neg": neg, "top": top, "green": green,
            "ratings": m.get("serp_ratings") or {},
            "live_links": [x["link"] for x in profiles] + [r.get("link") or "" for r in page1],
            "panel": profiles,
            "domains": sorted({r.get("domain") or "" for r in page1})}


# Posting goal (Megan 2026-11-11): 2-3 posts a week. 2 already earns the full
# posts score; the card asks for 2-3.
POST_GOAL = 2
POST_GOAL_TEXT = "2–3"


def posts_line(p, now: dt.datetime) -> Dict:
    from automations.brand_audit import social_inbox as S
    inbox = S._load_state(p.path("social_inbox.json"))
    since = (now - dt.timedelta(days=7)).timestamp()
    since2 = (now - dt.timedelta(days=14)).timestamp()
    n = n_prev = 0
    for ts, st in inbox.items():
        try:
            if not (isinstance(st, dict) and (st.get("published") or st.get("scheduled"))
                    and not st.get("killed")):
                continue
            t = float(ts)
        except ValueError:
            continue
        if t >= since:
            n += 1
        elif t >= since2:
            n_prev += 1
    color = GREEN if n >= POST_GOAL else (YELLOW if n else RED)
    pages = tuple(p.pages) or (ALPHALETE_PAGES if p.key == "alphalete" else ())
    pages = tuple(x for x in pages if x in BADGE)
    return {"color": color, "text": f"{n} post{'s' if n != 1 else ''} went out", "n": n,
            "pages": pages, "prev": {"n": n_prev}}


# What's WRONG, in plain words, for the "Your info online" card (Megan
# 2026-11-10: "this should just say what it is"). The to-do list says what
# to DO; this says what Lucy found.
PROBLEM = {
    "website link is secure (https)": "Your website link on {site} is missing the \"s\" in https://, so it may not open",
    "address": "The address on {site} doesn't match yours",
    "phone": "The phone number on {site} is different from yours",
    "website": "The website link on {site} is wrong",
    "business name": "Your business name on {site} doesn't match",
    "listing verified": "Your Google listing isn't verified",
    "site loads": "Your website isn't loading",
    "listing": "Lucy can't find your Google listing",
}


SEO_ONLY = {"name in page title"}

# ONE THING AT A TIME (Megan 2026-11-10: "we just need to prioritize the one
# thing until it's done and then move to the next"). Most damaging first: a
# site or listing people can't reach beats a detail that's slightly off.
PRIORITY = ["site loads", "listing", "listing is the one they gave us",
            "website link is secure (https)", "website", "phone", "address",
            "business name", "listing verified"]


def _prio(r: Dict) -> tuple:
    item, site = r["item"], (r.get("site") or "")
    rank = PRIORITY.index(item) if item in PRIORITY else len(PRIORITY)
    return (rank, 0 if site == "Google" else 1, item)


# The full checklist behind the card, worded as the thing that should be true.
CHECK_LABEL = {
    "site loads": "opens", "listing": "listing found",
    "listing is the one they gave us": "is the listing from your sign-up",
    "website link is secure (https)": "website link starts with https://",
    "website": "links to your correct website", "phone": "has your correct phone number",
    "address": "has your correct address", "business name": "has your exact business name",
    "listing verified": "listing is verified",
    "name in page title": "page title has your business name",
    "check by hand": "check by hand (it blocks Lucy)",
}


def check_label(r: Dict) -> str:
    site = r.get("site") or ""
    who = "Your website" if site.lower() == "website" else site
    item = r["item"]
    if item.startswith("links to their "):
        return f"{who} links to your {_page(item)} page"
    return f"{who}: {CHECK_LABEL.get(item, item)}"


def problem_text(r: Dict) -> str:
    item, site = r["item"], r.get("site") or ""
    if item.startswith("links to their "):
        return f"Your website doesn't link to your {_page(item)} page"
    return PROBLEM.get(item, f"Your {item} on {{site}} needs a look").format(
        site="your website" if site.lower() == "website" else site)


def info_line(p, aliases: Optional[Dict[str, set]] = None) -> Dict:
    from automations.online_presence import consistency
    try:
        rows = consistency.checks(p, aliases)
    except Exception:
        return {"color": GREY, "text": "Couldn't check this week", "fixes": [], "checks": {}}
    checks = {f'{r["site"]}|{r["item"]}': r["ok"] for r in rows}
    # The value that SHOULD be there is shown under each name/address/phone/
    # website line (Megan 2026-11-10: "should say has your correct address
    # and list the address, same for phone").
    show = ("address", "phone", "business name", "website")
    audit = sorted(({"label": check_label(r), "ok": r["ok"], "found": r.get("found") or "",
                     "value": (r.get("expected") or "") if r["item"] in show else "",
                     "page": r["item"][len("links to their "):] if r["item"].startswith("links to their ") else "",
                     "url": r.get("expected") or ""}
                    for r in rows), key=lambda x: {False: 0, None: 1, True: 2}[x["ok"]])
    rows = [r for r in rows if r["item"] not in SEO_ONLY]
    bad = sorted((r for r in rows if r["ok"] is False), key=_prio)
    def say(r):
        if (r.get("site") or "").lower() == "website":
            if r["item"] == "site loads":
                return "Your website isn't loading: tell your website person"
            if r["item"].startswith("links to their "):
                return f"Ask your website person to add your {_page(r['item'])} link"
            return f"Ask your website person to fix the {r['item']} on your site"
        return FIX.get(r["item"], f"Fix your {r['item']} on {{site}}").format(site=r["site"])
    fixes = [{"text": say(r),
              "why": WHY_FIX.get(r["item"], WHY_FIX["_"]),
              "how": _how(r)} for r in bad]
    checked = sorted({r["site"] for r in rows if r.get("ok") is not None})
    if not bad:
        return {"color": GREEN, "text": "Everything matches", "fixes": [], "problems": [],
                "checked": checked, "checks": checks, "audit": audit}
    return {"color": RED, "text": f"{len(bad)} thing{'s' if len(bad) != 1 else ''} to fix",
            "fixes": fixes, "problems": [problem_text(r) for r in bad], "checked": checked,
            "checks": checks, "audit": audit}


# Where an owner edits their Google listing: Google's Business Profile
# manager lists every listing their account manages, with Edit profile.
GBP_EDIT = "https://business.google.com/locations"


def todo(lines: Dict, review_link: str = "") -> List[Dict]:
    """At most 3 plain steps, most important first -- each with its WHY."""
    out: List[Dict] = []
    g, s, po, inf = lines["google"], lines["search"], lines["posts"], lines["info"]
    if g.get("bad"):
        out.append({"text": "Approve Lucy's reply to the bad review (it's in your Slack channel)",
                    "why": WHY["bad_review"], "how": HOW["bad_review"]})
    out += inf.get("fixes", [])[:1]          # one thing at a time, most important first
    if po["color"] != GREEN:
        out.append({"text": "Tap 📸 New post in your Slack channel and send 2–3 team posts (they go to Google too)", "why": WHY["photos"], "how": HOW["photos"]})
    if g["color"] == YELLOW or s["color"] in (RED, YELLOW):
        out.append({"text": "Send your review link to your new leaders and this week's happy "
                            "customers (you want a mix of both)", "why": WHY["reviews"],
                    "how": HOW["reviews"]})
    gd = inf.get("description") or {}
    if gd.get("needs_change") and gd.get("suggested"):
        # editing the listing is a quick action, with the link (Megan 11/11)
        out.append({"text": "Paste the new description into your Google listing",
                    "why": SEO["description"]["why"], "how": SEO["description"]["how"],
                    "now": gd.get("now") or "", "suggested": gd["suggested"],
                    "what_changed": gd.get("what_changed") or ""})
    return out[:4]


# ---- last week, for the lines Lucy can't rebuild from dates ------------------------
# ONE SCORE OUT OF 100 (Megan 2026-11-10: "this should be some type of score
# with a WOW then line graph of their score"). Four parts, 25 points each, so
# every card on the page shows where its points went:
#   Google reviews  15 for the rating (3.0★ = 0 ... 5.0★ = 15) + 10 for new
#                   reviews this week (3 or more = all 10)
#   Google search   5 for each of the top 5 results that's theirs (their
#                   website or one of their pages) -- the goal is all 5 green
#   Posts           2 or more posts this week = all 25 (goal 2-3)
#   Your info       25, minus 8 for each thing that doesn't match
# A part Lucy couldn't check scores 0 and says so -- never a free pass.
def raise_tips(lines: Dict, parts: Dict[str, int]) -> Dict[str, str]:
    """For each card, the one thing that raises that part of the score, with
    the points it's worth (Megan 2026-11-11: "we need to be able to tell them
    what they can do to improve their score"). A full part says so."""
    g, s, po, inf = lines["google"], lines["search"], lines["posts"], lines["info"]
    out = {}
    new = g.get("new") or 0
    if new < 3:
        k = 3 - new
        gain = 10 - round(min(new, 3) / 3 * 10)
        out["google"] = (f"Get {k} more new review{'s' if k != 1 else ''} this week "
                         f"(+{gain} points). Send your review link to new leaders and happy customers.")
    elif (g.get("avg") or 0) < 4.8:
        out["google"] = "Keep 3 new reviews a week coming: every 5★ review lifts your rating."
    n = po.get("n") or 0
    if n < POST_GOAL:
        k = POST_GOAL - n
        out["posts"] = (f"Send {k} more post{'s' if k != 1 else ''} with 📸 New post "
                        f"(+{25 - parts.get('posts', 0)} points).")
    if s.get("color") != GREY:
        top = s.get("top") or []
        bad = [r for r in top if r["kind"] not in GREEN_KINDS]
        if bad:
            first = bad[0]
            what = ("Push the negative result down" if first["kind"] == "negative"
                    else f"Get one of your own pages above #{first['pos']}")
            out["search"] = (f"{what} (+5 points for each top-5 spot that's yours). "
                             f"See \"Rank higher on Google\" below.")
    probs = inf.get("problems") or []
    if probs:
        out["info"] = f"Fix the first thing above (+8 points each, {len(probs)} to go)."
    return out


def score(lines: Dict) -> Tuple[int, Dict[str, int]]:
    g, s, po, inf = lines["google"], lines["search"], lines["posts"], lines["info"]
    parts = {}
    avg = g.get("avg")
    parts["google"] = round((max(0.0, min(1.0, (avg - 3) / 2)) * 15 if avg else 0)
                            + min(g.get("new") or 0, 3) / 3 * 10)
    if s.get("color") == GREY:
        parts["search"] = 0
    else:
        parts["search"] = 5 * min(s.get("green") or 0, 5)      # 5 per green result in the top 5
    parts["posts"] = round(min(po.get("n") or 0, POST_GOAL) / POST_GOAL * 25)
    parts["info"] = 0 if inf.get("color") == GREY else max(0, 25 - 8 * len(inf.get("problems") or []))
    return sum(parts.values()), parts


def _history(p) -> Dict:
    import json
    try:
        return json.loads(p.path("weekly_card_history.json").read_text())
    except Exception:
        return {}


def record(p, card: Dict, now: Optional[dt.datetime] = None) -> None:
    """Save this Friday's numbers so next Friday can say 'was #3'. Only the
    live Friday run calls this (a preview must never become 'last week')."""
    import json
    now = now or dt.datetime.now()
    h = _history(p)
    L = card["lines"]
    h[now.date().isoformat()] = {"green": L["search"].get("green"), "own": L["search"].get("own"), "neg": L["search"].get("neg"),
                                 "fixes": len(L["info"].get("fixes", [])),
                                 "score": card.get("score")}
    f = p.path("weekly_card_history.json")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(dict(sorted(h.items())[-12:]), indent=2))


def last_week(p, now: dt.datetime) -> Optional[Dict]:
    h = _history(p)
    cut = (now - dt.timedelta(days=5)).date().isoformat()
    older = [k for k in sorted(h) if k <= cut]
    return h[older[-1]] if older else None


def compare(lines: Dict, prev: Optional[Dict]) -> Dict[str, Dict]:
    """{line: {"text": "Last week: ...", "dir": up|down|same|new}}; up = better."""
    def d(now_v, then_v, higher_better=True):
        if now_v == then_v:
            return "same"
        if now_v is None or then_v is None:
            return "new"
        return "up" if ((now_v > then_v) if higher_better else (now_v < then_v)) else "down"
    g, po, out = lines["google"], lines["posts"], {}
    if (g.get("prev") or {}).get("count"):
        gp, diff = g["prev"], g["count"] - g["prev"]["count"]
        out["google"] = {"text": f"Last week: {gp['avg']:.1f} ★ · {gp['count']} reviews"
                                 + (f" (+{diff} since)" if diff > 0 else ""),
                         "dir": d((g["avg"], g["count"]), (gp["avg"], gp["count"]))}
    if "prev" in po:
        k = po["prev"]["n"]
        out["posts"] = {"text": f"Last week: {k} post{'s' if k != 1 else ''}", "dir": d(po["n"], k)}
    if prev is None:
        for k in ("search", "info"):
            out[k] = {"text": "Last week: first week, nothing to compare yet", "dir": "new"}
    else:
        if prev.get("green") is None:
            out["search"] = {"text": "Last week: first week, nothing to compare yet", "dir": "new"}
        else:
            out["search"] = {"text": f"Last week: {prev['green']} of 5 green",
                             "dir": d(lines["search"].get("green") or 0, prev["green"])}
        n_now, n_then = len(lines["info"].get("fixes", [])), prev.get("fixes", 0)
        out["info"] = {"text": f"Last week: {n_then} thing{'s' if n_then != 1 else ''} to fix",
                       "dir": d(n_now, n_then, higher_better=False)}
    return out


# ---- week-by-week progress (the charts at the bottom) ---------------------------
WEEKS = 8


def progress(p, lines: Dict, now: dt.datetime, weeks: int = WEEKS) -> List[Dict]:
    """[{title, unit, points:[(label, value)], lower_better}] -- one small chart
    each, oldest week first. Google + posts are rebuilt from dates, so they
    show 8 weeks from the first card; search rank needs saved Fridays."""
    from automations.brand_audit import social_inbox as S
    ends = [now - dt.timedelta(days=7 * i) for i in range(weeks - 1, -1, -1)]
    label = lambda d: f"{d:%b} {d.day}"
    charts = []
    revs = lines["google"].get("_revs") or []
    if revs:
        rating, newc = [], []
        for end in ends:
            iso, start = end.isoformat(), (end - dt.timedelta(days=7)).isoformat()
            stars = [r["rating"] for r in revs if (r.get("publish_time") or "") < iso
                     and isinstance(r.get("rating"), (int, float))]
            rating.append((label(end), round(sum(stars) / len(stars), 2) if stars else None))
            newc.append((label(end), sum(1 for r in revs if start <= (r.get("publish_time") or "") < iso)))
        charts.append({"title": "⭐ Google rating", "points": rating, "fmt": "{:.2f}"})
        charts.append({"title": "💬 New reviews each week", "points": newc, "fmt": "{:.0f}"})
    inbox = S._load_state(p.path("social_inbox.json"))
    stamps = []
    for ts, st in inbox.items():
        try:
            if isinstance(st, dict) and (st.get("published") or st.get("scheduled")) \
                    and not st.get("killed"):
                stamps.append(float(ts))
        except ValueError:
            pass
    posts = [(label(e), sum(1 for t in stamps if (e - dt.timedelta(days=7)).timestamp() <= t
                            < e.timestamp())) for e in ends]
    charts.append({"title": "📸 Posts each week", "points": posts, "fmt": "{:.0f}"})
    h = _history(p)
    if len(h) >= 2:
        pts = [(dt.date.fromisoformat(k).strftime("%b ") + str(dt.date.fromisoformat(k).day),
                v.get("own")) for k, v in sorted(h.items())[-weeks:]]
        charts.append({"title": "🔎 Your spot on Google (#1 is best)", "points": pts,
                       "fmt": "#{:.0f}", "lower_better": True})
    return charts


def chart_svg(c: Dict, w: int = 330, h: int = 150) -> str:
    """One small line chart: thin line, dots, only the latest value labeled,
    first + last dates under it. Each dot carries a hover tooltip (web)."""
    e = html.escape
    pts = [(lab, v) for lab, v in c["points"]]
    vals = [v for _, v in pts if v is not None]
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    if c.get("range"):
        lo, hi = c["range"]                            # e.g. the score: always 0-100
    elif hi == lo:
        pad = 1 if lo >= 1 else 0.1
        lo, hi = lo - pad, hi + pad
    if not c.get("range") and c.get("fmt", "").startswith("{:.0f}") and lo > 0:
        lo = 0                                         # counts sit on zero
    L, R, T, B = 14, 54, 26, 30
    pw, ph = w - L - R, h - T - B
    n = len(pts)
    x = lambda i: L + (pw * i / (n - 1) if n > 1 else pw / 2)
    def y(v):
        f = (v - lo) / (hi - lo)
        if c.get("lower_better"):
            f = 1 - f                                  # #1 at the top
        return T + ph * (1 - f)
    xy = [(x(i), y(v), lab, v) for i, (lab, v) in enumerate(pts) if v is not None]
    path = " ".join(f"{'M' if k == 0 else 'L'}{px:.1f},{py:.1f}" for k, (px, py, _, _) in enumerate(xy))
    dots = "".join(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="#B8862B" stroke="#fff" '
                   f'stroke-width="2"><title>{e(lab)}: {e(c["fmt"].format(v))}</title></circle>'
                   for px, py, lab, v in xy)
    lx, ly, _, lv = xy[-1]
    first, last = pts[0][0], pts[-1][0]
    return (f'<div class="chart"><div class="ct">{e(c["title"])}</div>'
            f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="{e(c["title"])}">'
            f'<line x1="{L}" y1="{T + ph}" x2="{L + pw}" y2="{T + ph}" stroke="#E6DAC2" stroke-width="1"/>'
            f'<path d="{path}" fill="none" stroke="#B8862B" stroke-width="2.5" stroke-linejoin="round"/>'
            f'{dots}<text x="{lx + 9:.1f}" y="{ly + 5:.1f}" font-size="15" font-weight="700" '
            f'fill="#2A2318">{e(c["fmt"].format(lv))}</text>'
            f'<text x="{L}" y="{h - 8}" font-size="13" fill="#6E6253">{e(first)}</text>'
            f'<text x="{L + pw}" y="{h - 8}" font-size="13" fill="#6E6253" text-anchor="end">{e(last)}</text>'
            f'</svg></div>')


def _md(d) -> str:
    return f"{d:%b} {d.day}"                # "Nov 9" -- %-d breaks on Windows



# ---- ranking higher on Google (Megan 2026-11-10: "we need to have ideas of
# how to get their SEO better"). Picked from THIS office's numbers, never a
# generic list: each idea fires only when its own reason is true this week.
# Ordered by how much it moves a local listing. Ideas already in "Do this
# week" are skipped, so the card never says the same thing twice.
SEO = {
    "reviews": {
        "text": "Get 3+ new Google reviews every week",
        "why": "How many reviews you get, and how recently, is one of the biggest things "
               "Google uses to rank local businesses. A steady trickle beats a big burst.",
        "how": [("Each week, ask your new leaders and a few happy customers. A mix of both reads best.", "weekly_reviews"),
                "Send them your review link (it's in Quick actions and the Slack message).",
                "Lucy answers every review, which Google also likes."]},
    "google_posts": {
        "text": "Post on your Google listing every week",
        "why": "Listings that post often look active to Google and show up more in Maps. "
               "Lucy already sends your approved photos to Google, so this is one tap.",
        "how": ["Tap 📸 New post in your Slack channel.",
                ("Keep Google ticked on your pages (it is by default).", "google_ticked"),
                ("One post a week is plenty.", "weekly_posts")]},
    "push_down": {
        "text": "Push the negative result down",
        "why": "The more of your own pages show up when people Google you, the further down "
               "the negative one goes. Page 2 is where almost nobody looks.",
        "how": [("Use your business name on your Facebook, Instagram and LinkedIn pages.", "page_names"),
                ("Post 2–3 times a week with 📸 New post. Lucy puts it on all your pages.", "weekly_posts"),
                ("Put your Facebook, Instagram and LinkedIn links on your website.", "site_links_socials")]},
    "own_site": {
        "text": "Fill more of the top 5 with your own pages",
        "why": "Every top-5 spot that's yours is one less spot for someone else's page about "
               "you. Google ranks your pages higher when they all point to each other.",
        "how": [("Use the exact same business name on your website, Google listing and social pages.", "name_match"),
                ("Link your website from your Google listing and every social page.", "site_on_google"),
                ("Put your business name in your website's page title (your website person can do this in 5 minutes).", "title_name")]},
    "photos": {
        "text": "Add 5 new photos to your Google listing each month",
        "why": "Listings with fresh photos get more clicks and calls, and Google shows them more.",
        "how": ["Use 📸 New post: the photos you approve also land on your Google listing.",
                "Team photos, the office and happy customers all work."]},
    "description": {
        "text": "Say what you do and where, in your Google description",
        "why": "Google matches searches like \"AT&T internet Dallas\" to the words in your listing.",
        "how": ["Tap your Google listing. Don't see your business? Check the email in the top "
                "right corner and switch to the Google account that manages your listing.",
                "Tap Edit profile, then Description.",
                "Paste in the new version below (or change it to how you'd say it), then Save."]},
}


def _norm(x: str) -> str:
    x = re.sub(r"[^a-z0-9]", "", (x or "").lower())
    return re.sub(r"(llc|inc|co|corp)$", "", x)


def names_check(business: str, names: Dict[str, str]) -> Optional[Tuple[bool, str]]:
    """Do their Facebook / Instagram / LinkedIn / X / TikTok pages carry their
    business name? (Megan 2026-11-10: "we should check their platform
    names".) A page NAME must contain it; a HANDLE (@name) must too, written
    without spaces -- 'alphaletemarketing' passes for Alphalete Marketing,
    'AlphaleteMrktg' does not. (ok, detail) or None when Lucy has no names."""
    if not names:
        return None
    biz = _norm(business)
    # The business's main word: "Alphalete" for Alphalete Marketing (skip
    # filler like "The"; generic trade words can't be the identifying one).
    generic = {"the", "marketing", "management", "mgmt", "group", "sales", "solutions",
               "services", "llc", "inc", "co", "company", "enterprises", "consulting"}
    words = [w for w in re.findall(r"[a-z0-9]+", (business or "").lower()) if w not in generic]
    key = next((w for w in words if len(w) >= 4), words[0] if words else biz)
    label = {"facebook": "Facebook", "instagram": "Instagram", "linkedin": "LinkedIn",
             "x": "X", "tiktok": "TikTok"}
    # Facebook / LinkedIn show a page NAME: the full business name is required.
    # X / Instagram / TikTok show a USERNAME with a length cap (X: 15), so a
    # short form carrying the main word passes (decided 2026-11-10).
    def ok(page, v):
        n = _norm(v)
        if page in ("facebook", "linkedin"):
            return bool(biz) and biz in n
        return bool(biz) and (biz in n or (key and key in n))
    off = [f"{label.get(k, k)}: {v}" for k, v in sorted(names.items()) if not ok(k, v)]
    return (not off, "; ".join(off))


def zoho_pages(p) -> Dict:
    """What Zoho knows about their connected pages: {"names": {page: name},
    "pages": {page: {id, name, connected}}}. From the office computer's daily
    check (watch.json), or Alphalete's own Zoho when this machine has it."""
    try:
        st = json.loads(p.path("watch.json").read_text())
        res = (st.get("last_check") or {}).get("result") or {}
        if res.get("names") or res.get("pages"):
            return {"names": res.get("names") or {}, "pages": res.get("pages") or {}}
    except Exception:
        pass
    if p.key == "alphalete":
        from automations.brand_audit import zoho_draft
        cache = p.path("zoho_pages.json")
        try:
            if zoho_draft.ZOHO_PROFILE_DIR.exists():
                r = zoho_draft.channel_check(headless=False)
                got = {"names": r.get("names") or {}, "pages": r.get("pages") or {}}
                if got["names"] or got["pages"]:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps(got))
                    return got
        except Exception:
            pass                     # a failed live read falls back to the last good one
        try:
            return json.loads(cache.read_text())
        except Exception:
            return {"names": {}, "pages": {}}
    return {"names": {}, "pages": {}}


def page_names(p) -> Dict[str, str]:
    return zoho_pages(p).get("names") or {}


def page_aliases(search: Dict, zp: Dict) -> Dict[str, set]:
    """Every way each of their accounts is written: its number and username
    from Zoho, plus the address Google's business panel shows for it."""
    from automations.online_presence.consistency import account_key
    al: Dict[str, set] = {}
    for page, x in (zp.get("pages") or {}).items():
        keys = {str(x.get("id") or "").lower()}
        if page in ("instagram", "x", "tiktok"):            # their 'name' is the username
            keys.add(re.sub(r"[^a-z0-9._]", "", (x.get("name") or "").lower()))
        al.setdefault(page, set()).update(k for k in keys if k)
    for x in search.get("panel") or []:
        n = (x.get("name") or "").lower()
        page = ("facebook" if "facebook" in n else "instagram" if "instagram" in n else
                "linkedin" if "linkedin" in n else "x" if ("twitter" in n or n.strip() == "x") else
                "tiktok" if "tiktok" in n else "")
        if page and page in al:            # Google's panel = that same connected account
            al[page].add(account_key(x["link"]))
    return al


def step_done(key: str, lines: Dict):
    """Is this how-step already done? True / False, or None when Lucy can't
    tell (Megan 2026-11-10: "we should tell them if they ✅ on these")."""
    g, po, inf = lines["google"], lines["posts"], lines["info"]
    ck = inf.get("checks") or {}
    if key == "weekly_reviews":
        return (g.get("new") or 0) >= 3
    if key == "weekly_posts":
        return (po.get("n") or 0) >= 1
    if key == "google_ticked":
        return "google" in (po.get("pages") or [])
    if key == "page_names":
        return inf.get("names")
    if key == "name_match":
        g_ok, pn = ck.get("Google|business name"), inf.get("names")
        if g_ok is None and pn is None:
            return None
        bad = [] if g_ok is not False else ["your Google listing"]
        if pn and not pn[0]:
            bad.append(pn[1])
        return (not bad, "; ".join(bad))
    if key == "site_on_google":
        return ck.get("Google|website")
    if key == "title_name":
        return ck.get("Website|name in page title")
    if key == "site_links_socials":
        got = [v for k, v in ck.items() if k.startswith("Website|links to their ") and v is not None]
        return all(got) if got else None
    return None


def _marked(how: List, lines: Dict) -> List:
    out = []
    for step in how:
        if isinstance(step, (tuple, list)):
            text, key = step
            d = step_done(key, lines)
            done, detail = (d if isinstance(d, tuple) else (d, ""))
            out.append({"text": text, "done": done, "detail": detail if done is False else ""})
        else:
            out.append({"text": step, "done": None, "detail": ""})
    return out


def seo_ideas(lines: Dict, todo_items: List[Dict], n: int = 3) -> List[Dict]:
    g, s, po = lines["google"], lines["search"], lines["posts"]
    picks = []
    if (g.get("new") or 0) < 3:
        picks.append("reviews")
    if s.get("neg"):
        picks.append("push_down")
    if (s.get("green") or 0) < 5:
        picks.append("own_site")
    # Posting to Google + Google photos aren't separate ideas any more: the
    # 📸 New post step in "Do this week" already sends to Google (Megan
    # 2026-11-11: "these are pretty redundant").
    picks += ["description"]
    done = " ".join(t["text"].lower() for t in todo_items)
    out = []
    for k in dict.fromkeys(picks):
        if k == "reviews" and "review link" in done:
            continue
        if k == "description":
            if "google description" in done or "your google listing" in done:
                continue                     # already a quick action up top
            gd = (lines.get("info") or {}).get("description")
            if gd and gd.get("needs_change") is False:
                continue                     # theirs already says what + where
            if gd and gd.get("suggested"):
                out.append(dict(SEO[k], key=k, how=_marked(SEO[k]["how"], lines),
                                now=gd.get("now") or "", suggested=gd["suggested"],
                                what_changed=gd.get("what_changed") or ""))
                if len(out) == n:
                    break
                continue
        how = _marked(SEO[k]["how"], lines)
        # every step already done -> nothing to tell them; show the next idea
        if how and all(h["done"] is True for h in how):
            continue
        out.append(dict(SEO[k], key=k, how=how))
        if len(out) == n:
            break
    return out


def confirm_links(audit: List[Dict], lines: Dict, p=None) -> List[Dict]:
    """Do the website's social links really open to the right page? (Megan
    2026-11-10: "are you making sure all these social links actually open to
    the correct pages and aren't broken?") Lucy can't open Facebook /
    LinkedIn / Instagram herself (they block or ask for a sign-in), so the
    proof is Google: a page Google shows for their name is live. The link
    must also be the account from their sign-up (consistency.py checks that
    part). Megan: "the important thing is making sure their website links are
    correct" -- so this grades the WEBSITE's links only."""
    from automations.online_presence.consistency import social_handle
    s = lines["search"]
    if s.get("color") == GREY:
        return audit
    from automations.online_presence.consistency import account_key
    live = {(_host_of(u), social_handle(u)) for u in s.get("live_links") or [] if u}
    known = (lines.get("info") or {}).get("aliases") or {}
    out = []
    for a in audit:
        if a.get("page") and a["ok"] is True:
            key = (_host_of(a["url"]), social_handle(a["url"]))
            if key in live:
                a = dict(a, label=a["label"] + " (Google shows it's live)")
            elif _google_has_page(a["page"], a["url"], p, known):
                a = dict(a, label=a["label"] + " (Google shows it's live)")
            else:
                a = dict(a, ok=False, label=a["label"] + " (Google can't find this page)",
                         found="Google can't find it: open the link and check it isn't broken")
        out.append(a)
    return out


LINK_HOSTS = {"linkedin": "linkedin.com/company", "facebook": "facebook.com", "instagram": "instagram.com",
              "x": "x.com", "tiktok": "tiktok.com"}


def _google_has_page(page: str, url: str, p, known: Dict) -> bool:
    """The audit can't leave a link unchecked (Megan 2026-11-11: "we need to
    make sure we can check everything as this is our audit"). LinkedIn and
    friends block Lucy from opening their pages, so ask Google directly:
    search that site for the business name. A hit that IS this account (same
    handle, or Zoho says it's their connected page by that name) = live.
    Numeric LinkedIn links (/company/15255695) never show on Google as the
    number, so a page under their name tied to that number in Zoho counts."""
    from automations.online_presence.consistency import social_handle, account_key
    if p is None or page not in LINK_HOSTS:
        return False
    try:
        from automations.brand_audit.collectors import serp
        data = serp._search(f'site:{LINK_HOSTS[page]} "{p.business_name}"', "")
    except Exception:
        return False
    want = social_handle(url)
    mine = set(known.get(page) or []) | {account_key(url)}
    name = re.sub(r"[^a-z0-9]", "", p.business_name.lower())
    for res in data.get("organic_results") or []:
        link = res.get("link") or ""
        if _host_of(link) != _host_of(url):
            continue
        if social_handle(link) == want or account_key(link) in mine:
            return True
        # numeric LinkedIn id: Zoho ties it to them, Google shows it by name
        if (page == "linkedin" and account_key(url).isdigit() and account_key(url) in set(known.get(page) or [])
                and name in re.sub(r"[^a-z0-9]", "", (res.get("title") or "").lower())):
            return True
    return False


def _host_of(u: str) -> str:
    h = re.sub(r"^https?://", "", (u or "").lower()).split("/")[0]
    h = re.sub(r"^(www|m|[a-z]{2})\.", "", h)
    return {"twitter.com": "x.com"}.get(h, h)


def review_site_rows(lines: Dict) -> List[Dict]:
    """Indeed + Glassdoor on the checklist, from what Lucy CAN see: the Google
    search for their name (Megan 2026-11-10: "we should have them on there if
    it's lucy"). Both sites block Lucy, so their pages are never opened."""
    s = lines["search"]
    if s.get("color") == GREY:
        return []
    out = []
    for key, name, dom in (("indeed", "Indeed", "indeed.com"), ("glassdoor", "Glassdoor", "glassdoor.com")):
        shows = any(d.endswith(dom) for d in s.get("domains") or [])
        rt = (s.get("ratings") or {}).get(key) or {}
        found = (f'{rt["rating"]}★' + (f' · {rt["reviews"]} reviews' if rt.get("reviews") else "")
                 if rt.get("rating") is not None else "")
        label = f"{name}: your page shows on Google for your name" + (f" ({found})" if found else "")
        out.append({"label": label, "ok": shows,
                    "found": "not on page 1 of Google" if not shows else ""})
    return out


def _score_block(p, lines: Dict, now: dt.datetime, prog: List[Dict]) -> Dict:
    """This week's score, last week's, and the line of weeks for the graph.

    Saved Fridays win. Until there are enough of them, the earlier weeks are
    worked out from what has dates -- the Google rating then, the new reviews
    and posts that week -- with this week's search + info standing in for the
    parts that can't be rebuilt (the card says so)."""
    total, parts = score(lines)
    hist = {k: v.get("score") for k, v in _history(p).items()
            if v.get("score") is not None and k < now.date().isoformat()}
    prev = hist[max(hist)] if hist else None
    by = {c["title"]: c["points"] for c in prog}
    rating = by.get("⭐ Google rating") or []
    newc = by.get("💬 New reviews each week") or []
    posts = by.get("📸 Posts each week") or []
    pts, estimated = [], False
    for i, (lab, _) in enumerate(posts[:-1]):            # the weeks before this one
        end = now - dt.timedelta(days=7 * (len(posts) - 1 - i))
        saved = next((v for k, v in hist.items() if abs((dt.date.fromisoformat(k) - end.date()).days) <= 3), None)
        if saved is not None:
            pts.append((lab, saved))
            continue
        r = rating[i][1] if i < len(rating) else None
        n = newc[i][1] if i < len(newc) else 0
        g = round((max(0.0, min(1.0, (r - 3) / 2)) * 15 if r else 0) + min(n or 0, 3) / 3 * 10)
        pp = round(min(posts[i][1] or 0, POST_GOAL) / POST_GOAL * 25)
        pts.append((lab, g + parts["search"] + pp + parts["info"]))
        estimated = True
    pts.append((_md(now), total))
    if prev is None and len(pts) >= 2:
        prev = pts[-2][1]                  # last week, worked out the same way
    return {"score": total, "score_parts": parts, "score_prev": prev,
            "score_line": {"title": "Your score", "points": pts, "fmt": "{:.0f}", "range": (0, 100),
                           "estimated": estimated}}


def slack_link(channel_id: str) -> str:
    """Opens the office's channel in Slack (app or browser) -- no workspace id needed."""
    return f"https://slack.com/app_redirect?channel={channel_id}" if channel_id else ""


def build(p, now: Optional[dt.datetime] = None, review_days: int = 7) -> Dict:
    now = now or dt.datetime.now()
    search = search_line(p)
    zp = zoho_pages(p)
    aliases = page_aliases(search, zp)
    lines = {"google": google_line(p, now, review_days), "search": search,
             "posts": posts_line(p, now), "info": info_line(p, aliases)}
    lines["info"]["names"] = names_check(p.business_name, zp.get("names") or {})
    lines["info"]["aliases"] = {k: sorted(v) for k, v in aliases.items()}
    try:
        from automations.online_presence import google_description
        lines["info"]["description"] = google_description.check(p)
    except Exception:
        lines["info"]["description"] = None
    link = ""
    try:
        from automations.brand_audit import gbp_api
        link = next((l.get("review_link", "") for l in gbp_api.all_locations()
                     if l["path"] == p.gbp_location), "")
    except Exception:
        pass
    prog = progress(p, lines, now)
    inf = lines["info"]
    inf["audit"] = sorted(confirm_links([a for a in inf.get("audit") or [] if "check by hand" not in a["label"]],
                                        lines, p)
                          + review_site_rows(lines),
                          key=lambda x: {False: 0, None: 1, True: 2}[x["ok"]])
    colors = [v["color"] for v in lines.values()]
    trend = compare(lines, last_week(p, now))
    verdict = ("Great week 🎉" if all(c == GREEN for c in colors) else
               "A few things need you" if RED in colors else
               "Pretty good week 👍")
    return {"business": p.business_name, "week_of": _md(now - dt.timedelta(days=6))
            if hasattr(now, "strftime") else "", "until": _md(now),
            "lines": lines, "todo": todo(lines, link), "verdict": verdict, "trend": trend,
            "review_link": link, "slack_link": slack_link(p.slack_channel),
            "progress": prog,
            "seo": seo_ideas(lines, todo(lines, link)),
            **_score_block(p, lines, now, prog)}


# ---- the page --------------------------------------------------------------------
ROWS = (("google", "⭐", "Google reviews"), ("search", "🔎", "When people Google you"),
        ("posts", "📸", "Posts this week"), ("info", "✅", "Your info online"))


STATUS = {"replied": ("✅", "Answered"), "waiting": ("⏳", "Lucy's reply is waiting for your ✅"),
          "none": ("•", "Not answered yet")}


def review_list_html(reviews: List[Dict]) -> str:
    e = html.escape
    out = []
    for r in reviews:
        icon, label = STATUS[r["status"]]
        stars = "★" * int(r["stars"] or 0)
        out.append(
            f'<div class="rv"><div class="rvh"><span class="stars">{stars}</span> '
            f'<b>{e(r["author"])}</b> <span class="when">{e(r["when"])}</span></div>'
            f'<div class="rvt">{e(r["text"]) or "<i>(stars only, no words)</i>"}</div>'
            f'<div class="ans"><b>{icon} {label}</b>'
            + (f'<div class="reply">{e(r["reply"])}</div>' if r["reply"] else "")
            + "</div></div>")
    return "".join(out)


def thread_text(card: Dict) -> str:
    """The Slack thread under the card: every new review + how it was answered."""
    g = card["lines"]["google"]
    revs = g.get("reviews") or []
    lines = []
    if card.get("review_link"):
        lines.append(f"⭐ <{card['review_link']}|Your review link> (send it to happy customers)")
    if card.get("slack_link"):
        lines.append(f"💬 <{card['slack_link']}|Your Slack channel>")
    if not revs:
        return "\n".join(lines)
    lines.append(f"\n*⭐ New Google reviews ({len(revs)})*")
    for r in revs:
        icon, label = STATUS[r["status"]]
        lines.append(f"\n{'★' * int(r['stars'] or 0)} *{r['author']}* · {r['when']}\n"
                     f"> {r['text'] or '(stars only)'}\n{icon} {label}"
                     + (f"\n_{r['reply']}_" if r["reply"] else ""))
    return "\n".join(lines)


def badges(pages) -> str:
    return "".join(f'<span class="bdg" title="{BADGE[x][2]}" style="background:{BADGE[x][1]}">'
                   f'{BADGE[x][0]}</span>' for x in pages)


def render(card: Dict, mode: str = "image") -> str:
    """mode "image": the picture posted to Slack (points at the PDF/thread).
    "web": the preview (reviews + Why/How open in place).
    "pdf": the PDF in the thread -- everything spelled out, links clickable.

    THE LOOK (Megan 2026-11-10, "redo the card all together"): the house board
    look she picked (feedback_sales_board_look) -- warm cream + gold, a header
    band with the office initial in a gold circle, four number cards that each
    say how they moved vs last week, and status words in pills."""
    e = html.escape
    web, pdf, img = mode == "web", mode == "pdf", mode == "image"
    L = card["lines"]
    g, s, po, inf = L["google"], L["search"], L["posts"], L["info"]
    trend = card.get("trend") or {}
    n_new = len(g.get("reviews") or [])

    PILL = {GREEN: ("good", "Good"), YELLOW: ("watch", "Keep an eye on it"),
            RED: ("bad", "Needs you"), GREY: ("na", "Couldn't check")}
    ARROW = {"up": ("▲", "up"), "down": ("▼", "down"), "same": ("●", "same"), "new": ("", "new")}

    def pill(color):
        cls, word = PILL.get(color, PILL[GREY])
        return f'<span class="pill {cls}">{word}</span>'

    def delta(k):
        t = trend.get(k)
        if not t:
            return '<div class="vs na">First week: nothing to compare yet</div>'
        a, cls = ARROW[t["dir"]]
        txt = t["text"].replace("Last week: ", "")
        if t["dir"] == "new":
            return '<div class="vs na">First week: nothing to compare yet</div>'
        return f'<div class="vs {cls}"><b>{a}</b> vs last week · {e(txt)}</div>'

    parts = card.get("score_parts") or {}
    tips = raise_tips(L, parts) if parts else {}

    def tip(k):
        if k not in parts:
            return ""
        if k in tips:
            return f'<div class="up"><b>How to raise your score:</b> {e(tips[k])}</div>'
        return '<div class="up full">✓ Full points here. Keep doing what you\'re doing.</div>' if parts[k] >= 25 else ""

    def pts(k):
        # every card shows its score out of 25, then HOW to raise it (Megan
        # 2026-11-11: "this is meant to give them DIRECTION")
        if k not in parts:
            return pill(L[k]["color"])
        v = parts[k]
        cls = "good" if v >= 20 else "watch" if v >= 12 else "bad"
        return f'<span class="pill {cls}">{v}/25</span>'

    def kpi(k, label, big, sub, extra=""):
        return (f'<div class="kpi"><div class="kh"><span class="kl">{label}</span>'
                f'{pts(k)}</div>' + (f'<div class="big">{big}</div>' if big else "")
                + f'<div class="sub">{sub}</div>{extra}{tip(k)}{delta(k)}</div>')

    avg = g.get("avg")
    # Indeed + Glassdoor next to Google, from the Google search (Megan 11/11).
    # Shown only; the score stays Google's.
    other = []
    for key, nm in (("indeed", "Indeed"), ("glassdoor", "Glassdoor")):
        x = (s.get("ratings") or {}).get(key) or {}
        if x.get("rating"):
            cnt = f' · {x["reviews"]:,} reviews' if x.get("reviews") else ""
            other.append(f'<div class="orow"><span>{nm}</span><b>{x["rating"]:.1f}★</b>'
                         f'<small>{cnt.lstrip(" ·")}</small></div>')
    k_rating = kpi("google", "Google rating",
                   f'{avg:.1f}<span class="star">★</span>' if avg else "—",
                   f'{g.get("count") or 0:,} reviews · <b>{n_new}</b> new this week',
                   f'<div class="others">{"".join(other)}</div>' if other else "")
    own, neg = s.get("own"), s.get("neg")
    TAG = {"owned": ("own", "Your website"), "profile": ("prof", "Your page"),
           "negative": ("neg", "Negative"), "neutral": ("", "")}

    def result(r):
        cls, tag = TAG.get(r["kind"], TAG["neutral"])
        tag = result_label(r) + (" · Negative" if r["kind"] == "negative" else "")
        title = e(r["title"][:80] + ("…" if len(r["title"]) > 80 else ""))
        name = (f'<a href="{e(r["link"])}">{title}</a>' if (r["link"] and not img) else title)
        return (f'<li class="res {cls}"><span class="rp">{r["pos"]}</span><span class="rt">'
                f'{name}<span class="rd">{e(r["domain"])}</span></span>'
                + (f'<span class="rtag {cls}">{tag}</span>' if tag else "") + "</li>")
    top = s.get("top") or []
    top_html = (f'<div class="toph">Top 5 on Google for your name</div>'
                f'<ol class="top5">{"".join(result(r) for r in top)}</ol>') if top else ""
    n_top, n_green = len(top) or 5, s.get("green") or 0
    neg_top = any(r["kind"] == "negative" for r in top)
    k_search = kpi("search", "When people Google you",
                   f"{n_green}/{n_top}" if top else "—",
                   f"of the top {n_top} are yours (goal: all 5)" + (f' · <span class="warn">a negative result is #{neg}</span>'
                                                       if neg_top else ""),
                   top_html)
    pages = po.get("pages") or []
    k_posts = kpi("posts", "Posts this week", f'{po.get("n") or 0}',
                  "posts went out (goal: 2–3 a week)",
                  f'<div class="pages">{badges(pages)}</div>' if pages else "")
    probs = inf.get("problems") or []
    checked = " and ".join(("your website" if c.lower() == "website" else c)
                           for c in inf.get("checked") or []) or "Google and your website"
    audit = inf.get("audit") or []
    n_ok = sum(1 for a in audit if a["ok"] is True)
    n_known = sum(1 for a in audit if a["ok"] is not None)
    def audit_list():
        mark = {True: ("ok", "✅"), False: ("no", "❌"), None: ("na", "—")}
        return '<ul class="audit">' + "".join(
            f'<li class="{mark[a["ok"]][0]}"><span class="am">{mark[a["ok"]][1]}</span><span class="at">'
            f'{e(a["label"])}'
            + (f'<small class="val">{e(a["value"])}</small>' if a.get("value") and a["ok"] is not False else "")
            + (f'<small>Should be: {e(a["value"])}</small>' if a.get("value") and a["ok"] is False else "")
            + (f'<small>Lucy sees: {e(a["found"])}</small>' if a["ok"] is False and a["found"] else "")
            + "</span></li>" for a in audit) + "</ul>"
    all_pass = bool(audit) and not probs and inf["color"] == GREEN
    count = "" if all_pass else f"{n_ok} of {n_known} checks pass · "
    if audit and web:
        listing = (f'<details class="aud"><summary>{count}'
                   f'<span class="tap">See the full checklist ▾</span></summary>{audit_list()}</details>')
    elif audit and pdf:
        listing = (f'<div class="aud"><b>{"The full checklist" if all_pass else count.rstrip(" ·")}'
                   f'</b>{audit_list()}</div>')
    elif audit:
        listing = f'<div class="aud">{count}full checklist in the PDF</div>'
    else:
        listing = ""
    if probs:
        more = (f'<div class="more">Then {len(probs) - 1} more, one at a time</div>'
                if len(probs) > 1 else "")
        k_info = kpi("info", "Your info online", "",
                     f'<div class="probs"><div class="prob">{e(probs[0])}</div></div>{more}', listing)
    elif inf["color"] == GREEN:
        okline = (f"✓ {n_ok}/{n_known} passed in your online brand audit" if all_pass
                  else f"✓ Your name, address, phone and website match on {checked}")
        k_info = kpi("info", "Your info online", "", f'<div class="okline">{e(okline)}</div>', listing)
    else:
        k_info = kpi("info", "Your info online", "", f'<div class="okline na">{e(inf["text"])}</div>')
    kpis = k_rating + k_posts + k_info + k_search.replace('class="kpi"', 'class="kpi wide"', 1)

    # new reviews: open in place (web), listed (pdf), pointed at (image)
    revs = ""
    if n_new:
        body = review_list_html(g["reviews"])
        if web:
            revs = (f'<details class="box rv-box"><summary><b>💬 {n_new} new Google '
                    f'review{"s" if n_new != 1 else ""}</b> <span class="tap">See them and how '
                    f'they were answered ▾</span></summary>{body}</details>')
        elif pdf:
            revs = f'<div class="box rv-box"><h3>💬 New Google reviews ({n_new})</h3>{body}</div>'
        else:
            revs = (f'<div class="box rv-box"><b>💬 {n_new} new Google review'
                    f'{"s" if n_new != 1 else ""}</b> <span class="tap">· read them in the PDF below</span></div>')

    rl, sl = card.get("review_link"), card.get("slack_link")

    def linkify(t):
        # The Slack channel and review link are one tap away INSIDE the to-do
        # (Megan 2026-11-10: "the slack link should be here"), not just up top.
        import re as _re
        out = _re.sub(r"(https?://\S+)", r'<a href="\1">link</a>', e(t))
        if not img:
            if sl:
                out = out.replace("your Slack channel",
                                  f'<a class="inl" href="{e(sl)}">your Slack channel</a>', 1)
            if rl:
                out = out.replace("your review link",
                                  f'<a class="inl" href="{e(rl)}">your review link</a>', 1)
            out = out.replace("your Google listing",
                              f'<a class="inl" href="{GBP_EDIT}">your Google listing</a>', 1)
        return out

    def step_li(x):
        if isinstance(x, dict):
            mark = {True: '<span class="ck yes">✅ done</span>', False: '<span class="ck no">❌ not yet</span>'
                    }.get(x.get("done"), "")
            det = f'<div class="ckd">Lucy sees: {e(x["detail"])}</div>' if x.get("detail") else ""
            return f'<li>{e(x["text"])} {mark}{det}</li>'
        return f"<li>{e(x)}</li>"

    def steps(t):
        how = t.get("how") or []
        if not how:
            return ""
        known = any(isinstance(x, dict) and x.get("done") is not None for x in how)
        note = ('<div class="cknote">✅ / ❌ = what Lucy could see this week</div>' if known else "")
        return '<ol class="how">' + "".join(step_li(x) for x in how) + "</ol>" + note

    def desc_boxes(t):
        if not t.get("suggested"):
            return ""
        now = e(t.get("now") or "") or "<i>Empty: your listing has no description yet.</i>"
        changed = (f'<div class="dchg">{e(t["what_changed"])}</div>' if t.get("what_changed") else "")
        return (f'<div class="dbox now"><div class="dh">What it says now</div>{now}</div>'
                f'<div class="dbox new"><div class="dh">What we\'d change it to</div>{e(t["suggested"])}'
                f'{changed}</div>')

    def task(i, t, tag="Why + how"):
        head = f'<span class="num">{i}</span><span class="tt">{linkify(t["text"])}</span>'
        if img:
            return f'<div class="task flat">{head}</div>'
        inner = (f'<div class="why"><b>Why:</b> {e(t["why"])}</div>'
                 f'<div class="howh">How:</div>{steps(t)}' + desc_boxes(t))
        if pdf:
            return f'<div class="task open"><div class="th">{head}</div>{inner}</div>'
        return (f'<details class="task"><summary>{head}<span class="wq">{tag} ▾</span></summary>'
                f'{inner}</details>')

    todo_html = ("".join(task(i, t) for i, t in enumerate(card["todo"], 1))
                 or '<div class="task done"><span class="num">✓</span><span class="tt">'
                    'Nothing this week. Keep sending Lucy your photos!</span></div>')
    seo_html = "".join(task(i, t) for i, t in enumerate(card.get("seo") or [], 1))
    seo_sec = (f'<section><h2>Rank Higher On Google / Improve Your SEO</h2><p class="lede">Picked from this '
               f'week\'s numbers. Each one helps you show up first when people search you.</p>'
               f'{seo_html}</section>') if seo_html else ""

    if img:
        links = ('<div class="links"><span class="btn gold">⭐ Your review link</span>'
                 '<span class="btn line">💬 Your Slack channel</span>'
                 '<span class="lk2">Tap them in the message below</span></div>') if (rl or sl) else ""
    else:
        bits = ([f'<a class="btn gold" href="{e(rl)}">⭐ Your review link</a>'] if rl else []) + \
               ([f'<a class="btn line" href="{e(sl)}">💬 Your Slack channel</a>'] if sl else [])
        links = (f'<div class="links">{"".join(bits)}<span class="lk2">Send the review link to '
                 f'happy customers: one tap takes them straight to the stars.</span></div>'
                 ) if bits else ""

    ch = "".join(chart_svg(c) for c in card.get("progress") or [])
    charts = (f'<section><h2>Week by week</h2><div class="charts">{ch}</div></section>'
              if ch else "")
    why_note = ('<p class="lede">Open the PDF below for why each one matters and how to do it.</p>'
                if img else "")
    sc_now, sc_prev = card.get("score"), card.get("score_prev")
    band = ("good" if (sc_now or 0) >= 80 else "watch" if (sc_now or 0) >= 60 else "bad")
    if sc_now is None:
        wow = ""
    elif sc_prev is None:
        wow = '<div class="wow na">First week: next Friday shows the change</div>'
    else:
        d = sc_now - sc_prev
        wow = (f'<div class="wow {"up" if d > 0 else "down" if d < 0 else "same"}">'
               f'{"▲" if d > 0 else "▼" if d < 0 else "●"} {abs(d) if d else "same as"}'
               f'{" vs" if d else ""} last week ({sc_prev})</div>')
    score_html = (f'<div class="score {band}"><div class="sl">Your score</div>'
                  f'<div class="sn">{sc_now}<span>/100</span></div>{wow}</div>'
                  if sc_now is not None else "")
    line = card.get("score_line") or {}
    if len(line.get("points") or []) >= 2:
        est = ('<div class="cknote">Earlier weeks are worked out from your reviews and posts '
               'by date; search and info use this week\'s numbers until Lucy has saved those weeks.</div>'
               if line.get("estimated") else "")
        score_graph = (f'<section class="sg"><h2>Your score, week by week</h2>'
                       f'{chart_svg(dict(line, title=""), w=700, h=170)}{est}</section>')
    else:
        score_graph = ('<div class="sg0">📈 Your score graph starts next Friday: one dot '
                       'each week, so you can see it climb.</div>')
    initial = e((card["business"] or "?").strip()[:1].upper())

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{e(card['business'])} — your week online</title>
<style>
 :root{{--ground:#F3EBDA;--paper:#FFFCF5;--band:#EADBB8;--gold:#B8862B;--gold-d:#8C6418;
       --ink:#2A2318;--soft:#6E6253;--line:#E6DAC2;--good:#2E7D4F;--good-bg:#E2F1E6;
       --watch:#9A6A00;--watch-bg:#FBEFD2;--bad:#B3261E;--bad-bg:#F9E1DE;--na:#7A7468;--na-bg:#EEEAE2}}
 *{{box-sizing:border-box}}
 body{{margin:0;background:var(--ground);color:var(--ink);
      font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif}}
 .card{{width:780px;margin:24px auto;background:var(--paper);border-radius:22px;overflow:hidden;
       box-shadow:0 2px 18px rgba(80,60,20,.10)}}
 .head{{background:var(--band);padding:26px 34px;display:flex;align-items:center;gap:18px}}
 .mono{{width:58px;height:58px;border-radius:50%;background:var(--gold);color:#fff;font:700 28px Georgia,serif;
       display:flex;align-items:center;justify-content:center;flex:none}}
 .hn{{flex:1;min-width:0}} .biz{{font:700 30px Georgia,"Times New Roman",serif;margin:0}}
 .kick{{font-size:13px;letter-spacing:.14em;color:var(--gold-d);font-weight:700;margin-top:3px}}
 .wk{{font-size:15px;color:var(--soft);margin-top:4px}}
 .score{{text-align:right;flex:none}} .sl{{font-size:13px;letter-spacing:.12em;font-weight:700;color:var(--gold-d);text-transform:uppercase}}
 .sn{{font:700 56px Georgia,serif;line-height:1}} .sn span{{font-size:22px;color:var(--soft);margin-left:2px}}
 .score.good .sn{{color:var(--good)}} .score.watch .sn{{color:var(--watch)}} .score.bad .sn{{color:var(--bad)}}
 .wow{{font-size:14px;font-weight:700;margin-top:4px}} .wow.up{{color:var(--good)}} .wow.down{{color:var(--bad)}}
 .wow.same,.wow.na{{color:var(--soft);font-weight:600}}
 .sg{{margin:0 0 18px}} .sg svg{{width:100%;height:auto}}
 .sg0{{font-size:15px;color:var(--soft);background:var(--ground);border-radius:12px;padding:10px 14px;margin-bottom:18px}}
 .verdict{{font-size:16px;font-weight:700;border-radius:999px;padding:8px 16px;white-space:nowrap}}
 .verdict.good{{background:var(--good-bg);color:var(--good)}} .verdict.watch{{background:var(--watch-bg);color:var(--watch)}}
 .verdict.bad{{background:var(--bad-bg);color:var(--bad)}}
 .wrap{{padding:24px 34px 30px}}
 .links{{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-top:24px}}
 .btn{{display:inline-block;border-radius:12px;padding:10px 16px;font-weight:700;font-size:16px;text-decoration:none}}
 .btn.gold{{background:var(--gold);color:#fff}} .btn.line{{border:2px solid var(--gold);color:var(--gold-d)}}
 .lk2{{font-size:14px;color:var(--soft)}}
 .kpis{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}} .kpi.wide{{grid-column:1/-1}}
 .probs{{margin-top:10px}} .more{{font-size:13px;color:var(--soft);margin-top:6px}}
 .aud{{font-size:14px;margin-top:10px;color:var(--soft)}} .aud summary{{cursor:pointer;list-style:none}}
 ul.audit{{list-style:none;padding:0;margin:8px 0 0;display:grid;gap:4px;font-size:14px;color:var(--ink)}}
 ul.audit li{{display:flex;gap:8px;align-items:flex-start}} ul.audit li.no{{color:var(--bad);font-weight:600}}
 ul.audit li.na{{color:var(--soft)}} .am{{flex:none;width:20px}} .at{{flex:1;min-width:0}}
 ul.audit small{{display:block;font-size:12px;font-weight:400}} ul.audit small.val{{color:var(--soft);font-size:13px}}
 .prob{{background:var(--bad-bg);color:var(--bad);border-radius:10px;padding:8px 10px;font-weight:600;font-size:15px}}
 .okline{{margin-top:10px;font-size:15px;color:var(--good);font-weight:600}} .okline.na{{color:var(--na)}}
 .toph{{font-size:14px;font-weight:700;color:var(--soft);margin-top:14px}}
 ol.top5{{list-style:none;margin:6px 0 0;padding:0;display:grid;gap:6px}}
 .res{{display:flex;align-items:center;gap:10px;border:1px solid var(--line);border-radius:10px;padding:8px 10px;font-size:15px}}
 .res.neg{{background:var(--bad-bg);border-color:#EBB8B2;color:var(--bad)}} .res.neg a,.res.neg .rd{{color:var(--bad)}}
 .res.own,.res.prof{{background:var(--good-bg);border-color:#BFDEC9}}
 .rp{{font:700 18px Georgia,serif;width:22px;text-align:center;flex:none}}
 .rt{{flex:1;min-width:0;display:flex;flex-direction:column}} .rt a{{color:inherit;text-decoration:none;font-weight:600}}
 .rd{{font-size:13px;color:var(--soft)}}
 .rtag{{font-size:12px;font-weight:700;border-radius:999px;padding:2px 9px;white-space:nowrap}}
 .rtag.own,.rtag.prof{{background:#fff;color:var(--good)}}
 .rtag.neg{{background:var(--bad);color:#fff}}
 .kpi{{border:1.5px solid var(--line);border-radius:16px;padding:16px 18px;background:#fff}}
 .kh{{display:flex;justify-content:space-between;align-items:center;gap:8px}}
 .kl{{font-size:15px;color:var(--soft);font-weight:600}}
 .big{{font:700 40px Georgia,serif;margin:6px 0 2px;line-height:1}} .star{{color:var(--gold);font-size:34px;margin-left:4px}}
 .sub{{font-size:15px;color:var(--ink)}} .warn{{color:var(--bad);font-weight:700}}
 .up{{margin-top:10px;padding:8px 10px;border-radius:8px;background:#F6EEDC;color:#6B4E12;font-size:14px;line-height:1.35}}
 .up.full{{background:#E6F1E8;color:var(--good)}}
 .vs{{font-size:14px;margin-top:10px;padding-top:8px;border-top:1px dashed var(--line);color:var(--soft)}}
 .vs b{{margin-right:4px}} .vs.up b{{color:var(--good)}} .vs.down b{{color:var(--bad)}} .vs.same b{{color:var(--na)}}
 .pill{{font-size:12px;font-weight:700;border-radius:999px;padding:3px 10px;white-space:nowrap}}
 .pill.good{{background:var(--good-bg);color:var(--good)}} .pill.watch{{background:var(--watch-bg);color:var(--watch)}}
 .pill.bad{{background:var(--bad-bg);color:var(--bad)}} .pill.na{{background:var(--na-bg);color:var(--na)}}
 .pages{{display:flex;gap:6px;margin-top:8px}}
 .bdg{{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:8px;
      color:#fff;font-weight:800;font-size:13px}}
 .box{{border:1.5px solid var(--line);border-radius:16px;padding:14px 18px;margin-top:14px;background:#fff;font-size:16px}}
 details summary{{cursor:pointer;list-style:none}} details summary::-webkit-details-marker{{display:none}}
 .tap{{color:var(--gold-d);font-weight:600;font-size:15px}}
 section{{margin-top:28px}}
 h2{{font:700 22px Georgia,serif;margin:0 0 4px}} h3{{font:700 18px Georgia,serif;margin:0 0 8px}}
 .lede{{font-size:15px;color:var(--soft);margin:0 0 10px}}
 .others{{margin-top:10px;border-top:1px dashed var(--line);padding-top:8px}}
 .orow{{display:flex;gap:8px;align-items:baseline;font-size:15px;margin-top:2px}} .orow span{{min-width:72px;color:var(--soft)}}
 .orow small{{color:var(--soft)}}
 .dbox{{border-radius:10px;padding:10px 12px;margin-top:10px;font-size:15px;line-height:1.45}}
 .dbox.now{{background:#F4F1EA;color:var(--soft)}} .dbox.new{{background:var(--good-bg);border:1.5px solid #BFDCC6}}
 .dh{{font-weight:800;font-size:13px;letter-spacing:.03em;text-transform:uppercase;margin-bottom:4px;color:var(--ink)}}
 .dchg{{font-size:13px;color:var(--soft);margin-top:6px;font-style:italic}}
 .dothis{{margin-top:24px;padding:18px 18px 20px;border:3px solid var(--gold);border-radius:18px;background:#FBF3E2}}
 .dothis h2{{font-size:26px}} .dothis .tt{{font-weight:800;font-size:19px}} .dothis .task{{border-color:#E2CFA4}}
 .task{{border:1.5px solid var(--line);border-radius:14px;padding:12px 14px;margin-top:10px;background:#fff}}
 .task summary,.task .th,.task.done,.task.flat{{display:flex;align-items:center;gap:12px}}
 .num{{width:30px;height:30px;border-radius:50%;background:var(--gold);color:#fff;font-weight:800;
      display:flex;align-items:center;justify-content:center;flex:none;font-size:15px}}
 .tt{{flex:1;font-size:18px;font-weight:600;min-width:0}}
 .wq{{font-size:13px;font-weight:700;color:var(--gold-d);border:1.5px solid var(--gold);border-radius:999px;
     padding:2px 10px;white-space:nowrap}}
 .why{{font-size:15px;color:var(--ink);background:var(--ground);border-radius:10px;padding:10px 12px;margin:10px 0 4px}}
 .ck{{font-size:13px;font-weight:700;border-radius:999px;padding:1px 8px;margin-left:4px;white-space:nowrap}}
 .ck.yes{{background:var(--good-bg);color:var(--good)}} .ck.no{{background:var(--bad-bg);color:var(--bad)}}
 .ckd{{font-size:13px;color:var(--bad);margin-top:2px}}
 .cknote{{font-size:13px;color:var(--soft);margin-top:4px}}
 .howh{{font-weight:700;font-size:15px;margin-top:8px}} ol.how{{font-size:15px;line-height:1.45;padding-left:22px;margin:4px 0 2px}}
 .charts{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
 .chart{{border:1.5px solid var(--line);border-radius:14px;padding:10px 10px 2px;background:#fff}}
 .chart svg{{width:100%;height:auto}} .ct{{font-size:14px;font-weight:700;margin-bottom:2px}}
 .rv{{border-left:4px solid var(--line);padding:8px 14px;margin:12px 0}} .rvh{{font-size:16px}}
 .stars{{color:var(--gold)}} .when{{color:var(--soft);font-size:14px}} .rvt{{font-size:16px;margin:6px 0}}
 .ans{{font-size:15px}} .reply{{background:var(--ground);border-radius:10px;padding:8px 12px;margin-top:6px}}
 .foot{{font-size:13px;color:var(--soft);margin-top:28px;border-top:1px solid var(--line);padding-top:12px}}
 a{{color:var(--gold-d)}} a.inl{{display:inline-block;background:var(--gold);color:#fff;text-decoration:none;border-radius:9px;
        padding:1px 10px;margin:0 2px;font-size:.95em}} .btn.gold{{color:#fff}}
 @media print{{body{{background:#fff}} .card{{box-shadow:none;margin:0 auto}} .task,.chart,.kpi{{break-inside:avoid}}}}
</style></head><body><div class="card">
 <div class="head"><div class="mono">{initial}</div>
  <div class="hn"><h1 class="biz">{e(card['business'])}</h1>
   <div class="kick">LUCYECO SOCIAL · WEEKLY CARD</div>
   <div class="wk">Week of {e(card['week_of'])} – {e(card['until'])}</div></div>
  {score_html}</div>
 <div class="wrap">
  {score_graph}
  <div class="kpis">{kpis}</div>
  {revs}
  {seo_sec}
  {charts}
  <section class="dothis"><h2>⚡ Quick actions you can take this week</h2>{why_note}{todo_html}</section>
  <div class="foot">Lucy checks this every Friday at noon. Your score is 4 parts of 25: Google
   reviews (rating + new reviews), Google search (5 per top-5 result that's yours), posts (2–3 a week)
   and your info (25, minus 8 per thing that doesn't match).</div>
 </div></div></body></html>"""


def save(card: Dict, out: Path, mode: str = "image") -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(card, mode), encoding="utf-8")
    return out


def _browser_render(html_path: Path, out: Path, kind: str) -> Path:
    from patchright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            pg = b.new_page(viewport={"width": 860, "height": 1000}, device_scale_factor=2)
            pg.goto(html_path.resolve().as_uri(), wait_until="load", timeout=30000)
            if kind == "png":
                pg.screenshot(path=str(out), full_page=True)
            else:
                pg.pdf(path=str(out), format="Letter", print_background=True,
                       margin={"top": "0.4in", "bottom": "0.4in", "left": "0.3in", "right": "0.3in"})
        finally:
            b.close()
    return out


def files(card: Dict, folder: Path, stem: str) -> Dict[str, Path]:
    """The two things that go to Slack: the card picture + the PDF."""
    img_html = save(card, folder / f"{stem}.html", "image")
    pdf_html = save(card, folder / f"{stem}_pdf.html", "pdf")
    return {"png": _browser_render(img_html, folder / f"{stem}.png", "png"),
            "pdf": _browser_render(pdf_html, folder / f"{stem}.pdf", "pdf")}
