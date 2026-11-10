"""The weekly card an office actually reads: four lines and a to-do list.

Megan 2026-11-09: "this card is way too busy ... make it super simple - 7
year old simple rule". So no grades, no scores, no tables, no jargon:

    🟢/🟡/🔴  ⭐ Google reviews        4.8 ★ · 820 reviews · 3 new this week
    🟢/🟡/🔴  🔎 When people Google you   Your website is #2 · nothing bad on page 1
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
from pathlib import Path
from typing import Dict, List, Optional

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
    "bad_review": ["Open your Slack channel (link at the top of this card).",
                   "Read Lucy's reply under the review.",
                   "React ✅ to post it, or ❌ and type what you'd change."],
    "photos": ["Open your Slack channel (link at the top of this card).",
               "Tap the pinned 📸 New post button.",
               "Add your photo(s). Every photo you add goes in that ONE post. For "
               "another post, tap New post again.",
               "Say who's in it and what's happening, then tap Submit.",
               "Lucy edits every photo, writes the caption, and asks for your ✅ "
               "before anything posts."],
    "reviews": ["Copy your review link (top of this card).",
                "Text it to 5 customers who were happy with their service.",
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
               "bad search results further down. Happy customers rarely review unless you ask.",
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


def search_line(p) -> Dict:
    from automations.brand_audit.collectors import serp
    from automations.online_presence.weekly_card import company_for
    try:
        m = serp.collect(company_for(p)).as_dict().get("metrics") or {}
    except Exception:
        m = {}
    if not m:
        return {"color": GREY, "text": "Couldn't search Google this week"}
    own, neg = m.get("own_site_position"), m.get("top_negative_position")
    site = f"Your website is #{own}" if own else "Your website isn't on page 1"
    if neg:
        bad = f"something bad is #{neg}"
        color = RED if (own is None or neg < own) else YELLOW
    else:
        bad, color = "nothing bad on page 1", (GREEN if own and own <= 3 else YELLOW)
    return {"color": color, "text": f"{site} · {bad}", "own": own, "neg": neg}


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
    color = GREEN if n >= 3 else (YELLOW if n else RED)
    pages = tuple(p.pages) or (ALPHALETE_PAGES if p.key == "alphalete" else ())
    pages = tuple(x for x in pages if x in BADGE)
    return {"color": color, "text": f"{n} post{'s' if n != 1 else ''} went out", "n": n,
            "pages": pages, "prev": {"n": n_prev}}


def info_line(p) -> Dict:
    from automations.online_presence import consistency
    try:
        rows = consistency.checks(p)
    except Exception:
        return {"color": GREY, "text": "Couldn't check this week", "fixes": []}
    bad = [r for r in rows if r["ok"] is False]
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
    if not bad:
        return {"color": GREEN, "text": "Everything matches", "fixes": []}
    return {"color": RED, "text": f"{len(bad)} thing{'s' if len(bad) != 1 else ''} to fix",
            "fixes": fixes}


def todo(lines: Dict, review_link: str = "") -> List[Dict]:
    """At most 3 plain steps, most important first -- each with its WHY."""
    out: List[Dict] = []
    g, s, po, inf = lines["google"], lines["search"], lines["posts"], lines["info"]
    if g.get("bad"):
        out.append({"text": "Approve Lucy's reply to the bad review (it's in your Slack channel)",
                    "why": WHY["bad_review"], "how": HOW["bad_review"]})
    out += inf.get("fixes", [])
    if po["color"] != GREEN:
        out.append({"text": "Tap 📸 New post in your Slack channel and send 3 team posts", "why": WHY["photos"], "how": HOW["photos"]})
    if g["color"] == YELLOW or s["color"] in (RED, YELLOW):
        out.append({"text": "Text 5 happy customers your review link", "why": WHY["reviews"],
                    "how": HOW["reviews"]})
    return out[:3]


# ---- last week, for the lines Lucy can't rebuild from dates ------------------------
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
    h[now.date().isoformat()] = {"own": L["search"].get("own"), "neg": L["search"].get("neg"),
                                 "fixes": len(L["info"].get("fixes", []))}
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
        own = lines["search"].get("own")
        was = f"#{prev['own']}" if prev.get("own") else "not on page 1"
        out["search"] = {"text": f"Last week: your website was {was}",
                         "dir": d(own or 99, prev.get("own") or 99, higher_better=False)}
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
    if hi == lo:
        pad = 1 if lo >= 1 else 0.1
        lo, hi = lo - pad, hi + pad
    if c.get("fmt", "").startswith("{:.0f}") and lo > 0:
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
    dots = "".join(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="#2F6FDE" stroke="#fff" '
                   f'stroke-width="2"><title>{e(lab)}: {e(c["fmt"].format(v))}</title></circle>'
                   for px, py, lab, v in xy)
    lx, ly, _, lv = xy[-1]
    first, last = pts[0][0], pts[-1][0]
    return (f'<div class="chart"><div class="ct">{e(c["title"])}</div>'
            f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="{e(c["title"])}">'
            f'<line x1="{L}" y1="{T + ph}" x2="{L + pw}" y2="{T + ph}" stroke="#E2E2E2" stroke-width="1"/>'
            f'<path d="{path}" fill="none" stroke="#2F6FDE" stroke-width="2" stroke-linejoin="round"/>'
            f'{dots}<text x="{lx + 9:.1f}" y="{ly + 5:.1f}" font-size="15" font-weight="700" '
            f'fill="#1E1E1E">{e(c["fmt"].format(lv))}</text>'
            f'<text x="{L}" y="{h - 8}" font-size="13" fill="#888">{e(first)}</text>'
            f'<text x="{L + pw}" y="{h - 8}" font-size="13" fill="#888" text-anchor="end">{e(last)}</text>'
            f'</svg></div>')


def _md(d) -> str:
    return f"{d:%b} {d.day}"                # "Nov 9" -- %-d breaks on Windows


def slack_link(channel_id: str) -> str:
    """Opens the office's channel in Slack (app or browser) -- no workspace id needed."""
    return f"https://slack.com/app_redirect?channel={channel_id}" if channel_id else ""


def build(p, now: Optional[dt.datetime] = None, review_days: int = 7) -> Dict:
    now = now or dt.datetime.now()
    lines = {"google": google_line(p, now, review_days), "search": search_line(p),
             "posts": posts_line(p, now), "info": info_line(p)}
    link = ""
    try:
        from automations.brand_audit import gbp_api
        link = next((l.get("review_link", "") for l in gbp_api.all_locations()
                     if l["path"] == p.gbp_location), "")
    except Exception:
        pass
    colors = [v["color"] for v in lines.values()]
    trend = compare(lines, last_week(p, now))
    verdict = ("Great week 🎉" if all(c == GREEN for c in colors) else
               "A few things need you" if RED in colors else
               "Pretty good week 👍")
    return {"business": p.business_name, "week_of": _md(now - dt.timedelta(days=6))
            if hasattr(now, "strftime") else "", "until": _md(now),
            "lines": lines, "todo": todo(lines, link), "verdict": verdict, "trend": trend,
            "review_link": link, "slack_link": slack_link(p.slack_channel),
            "progress": progress(p, lines, now)}


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
    "web": the preview (the reviews line opens the list).
    "pdf": the PDF in the thread -- everything spelled out, links clickable."""
    e = html.escape
    interactive = mode == "web"
    g = card["lines"]["google"]
    n = len(g.get("reviews") or [])

    ARROW = {"up": ("▲", "#22A35A"), "down": ("▼", "#D93A3A"), "same": ("=", "#9AA0A6"),
             "new": ("", "#9AA0A6")}

    def row(k, icon, label):
        val = e(card["lines"][k]["text"])
        body = (f'<div class="label">{icon} {label}</div><div class="val">{val}</div>')
        t = (card.get("trend") or {}).get(k)
        if t:
            a, col = ARROW[t["dir"]]
            body += f'<div class="was">{e(t["text"])} <b style="color:{col}">{a}</b></div>' 
        if k == "posts" and card["lines"]["posts"].get("pages"):
            body += (f'<div class="pages">Posting to {badges(card["lines"]["posts"]["pages"])}</div>')
        if k == "google" and n and mode == "pdf":
            body += '<div class="tap">They\'re listed at the end, with how each was answered.</div>'
        elif k == "google" and n:
            if interactive:
                return (f'<details class="row rowd"><summary><span class="dot" style="background:'
                        f'{DOT[g["color"]]}"></span><div>{body}<div class="tap">Tap to see them and '
                        f'how they were answered ▾</div></div></summary>'
                        f'<div class="rvs">{review_list_html(g["reviews"])}</div></details>')
            body += '<div class="tap">Open the PDF below to read them 👇</div>'
        return (f'<div class="row"><span class="dot" style="background:{DOT[card["lines"][k]["color"]]}">'
                f'</span><div>{body}</div></div>')
    rows = "".join(row(k, icon, label) for k, icon, label in ROWS)
    def linkify(t):
        t = e(t)
        import re as _re
        return _re.sub(r"(https?://\S+)", r'<a href="\1">leave-a-review link</a>', t)
    def steps(t):
        return ("<ol class=\"how\">" + "".join(f"<li>{e(x)}</li>" for x in t.get("how") or [])
                + "</ol>") if t.get("how") else ""
    def item(t):
        if mode == "image":
            return f"<li>{linkify(t['text'])}</li>"
        if mode == "pdf":
            return f'<li>{linkify(t["text"])}<div class="why"><b>Why:</b> {e(t["why"])}</div></li>'
        return (f'<li><details class="whyd"><summary>{linkify(t["text"])} '
                f'<span class="whyq">Why + how?</span></summary><div class="why"><b>Why:</b> '
                f'{e(t["why"])}<div class="howh">How:</div>{steps(t)}</div></details></li>')
    todo = ("".join(item(t) for t in card["todo"])
            or "<li>Nothing. Keep sending Lucy your photos!</li>")
    ch = "".join(chart_svg(c) for c in card.get("progress") or [])
    charts = (f'<h2>How you\'re doing week by week</h2><div class="charts">{ch}</div>'
              if ch else "")
    why_note = ('<div class="tap">Open the PDF below for why each one matters, and how to do it 👇</div>'
                if mode == "image" and card["todo"] else "")
    howto = ("<h2>How to do it</h2>" + "".join(
        f'<div class="hw"><div class="hwt">{i}. {e(t["text"])}</div>{steps(t)}</div>'
        for i, t in enumerate(card["todo"], 1) if t.get("how"))
        if mode == "pdf" and card["todo"] else "")
    # Megan 2026-11-09: least friction -- their review link and their Slack
    # channel are one tap away on the card itself.
    rl, sl = card.get("review_link"), card.get("slack_link")
    if mode == "image":
        links = ('<div class="links">⭐ Your review link · 💬 Your Slack channel '
                 '<span class="lk2">(tap them in the message below)</span></div>'
                 if rl or sl else "")
    else:
        bits = ([f'<a class="btn" href="{e(rl)}">⭐ Your review link</a>'] if rl else []) + \
               ([f'<a class="btn" href="{e(sl)}">💬 Your Slack channel</a>'] if sl else [])
        links = (f'<div class="links">{"".join(bits)}'
                 + ('<div class="lk2">Send the review link to happy customers: one tap '
                    'takes them straight to the stars.</div>' if rl else "")
                 + "</div>") if bits else ""
    pdf_reviews = (f'<h2>New Google reviews ({n})</h2><div class="rvs0">{review_list_html(g["reviews"])}</div>'
                   if mode == "pdf" and n else "")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{e(card['business'])} — your week online</title>
<style>
 body{{margin:0;background:#F4F1EA;font-family:-apple-system,Helvetica,Arial,sans-serif;color:#1E1E1E}}
 .card{{width:760px;margin:24px auto;background:#fff;border-radius:22px;padding:40px 44px;
        box-shadow:0 2px 14px rgba(0,0,0,.08)}}
 h1{{font-size:34px;margin:0}} .sub{{font-size:20px;color:#666;margin:6px 0 4px}}
 .verdict{{font-size:26px;font-weight:700;margin:18px 0 26px}}
 .row{{display:flex;gap:20px;align-items:center;padding:20px 0;border-top:1px solid #EEE}}
 .dot{{width:30px;height:30px;border-radius:50%;flex:none}}
 .label{{font-size:19px;color:#666}} .val{{font-size:28px;font-weight:700;margin-top:3px}}
 h2{{font-size:26px;margin:30px 0 10px;border-top:2px solid #1E1E1E;padding-top:24px}}
 ol{{font-size:23px;line-height:1.5;margin:0;padding-left:30px}} li{{margin:8px 0}}
 .foot{{font-size:15px;color:#999;margin-top:28px}}
 .tap{{font-size:17px;color:#2F6FDE;margin-top:6px;font-weight:600}}
 .was{{font-size:17px;color:#888;margin-top:4px}}
 .charts{{display:grid;grid-template-columns:1fr 1fr;gap:18px 26px}}
 .chart{{background:#FAFAF7;border-radius:14px;padding:12px 14px 4px}} .ct{{font-size:18px;font-weight:700;margin-bottom:2px}}
 @media print{{.chart{{break-inside:avoid}}}}
 details.whyd summary{{cursor:pointer;list-style:none}} details.whyd summary::-webkit-details-marker{{display:none}}
 .whyq{{font-size:15px;color:#2F6FDE;font-weight:700;margin-left:6px;border:1.5px solid #2F6FDE;
        border-radius:12px;padding:1px 9px}}
 .why{{font-size:18px;color:#444;background:#F4F1EA;border-radius:10px;padding:10px 14px;margin:8px 0 4px}}
 .pages{{font-size:17px;color:#666;margin-top:8px;display:flex;align-items:center;gap:6px}}
 .bdg{{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;
       border-radius:8px;color:#fff;font-weight:800;font-size:14px;font-family:Helvetica,Arial,sans-serif}}
 a{{color:#2F6FDE}} .rvs0 .rv{{margin:14px 0}}
 @media print{{body{{background:#fff}} .card{{box-shadow:none;margin:0 auto}} details{{display:block}}}}
 details.rowd{{display:block}} details.rowd summary{{display:flex;gap:20px;align-items:center;cursor:pointer;list-style:none}}
 details.rowd summary::-webkit-details-marker{{display:none}}
 .rvs{{margin:16px 0 0 50px}} .rv{{border-left:4px solid #EEE;padding:10px 16px;margin:12px 0}}
 .rvh{{font-size:18px}} .stars{{color:#E8A317}} .when{{color:#999;font-size:15px}}
 .rvt{{font-size:18px;margin:6px 0}} .ans{{font-size:16px;color:#333}}
 .links{{background:#F4F1EA;border-radius:16px;padding:14px 18px;margin:-8px 0 18px;font-size:19px;font-weight:700}}
 .btn{{display:inline-block;background:#2F6FDE;color:#fff;text-decoration:none;border-radius:12px;
       padding:10px 16px;margin:0 10px 6px 0;font-size:19px}}
 .lk2{{font-size:16px;color:#666;font-weight:400;margin-top:4px}}
 .howh{{font-weight:700;margin-top:8px}} ol.how{{font-size:17px;line-height:1.45;padding-left:24px;margin:4px 0}}
 ol.how li{{margin:4px 0}} .hw{{margin:12px 0 18px}} .hwt{{font-size:21px;font-weight:700}}
 .reply{{background:#F4F1EA;border-radius:10px;padding:10px 14px;margin-top:6px;font-size:16px}}
</style></head><body><div class="card">
 <h1>{e(card['business'])}</h1>
 <div class="sub">Your week online · {e(card['week_of'])} – {e(card['until'])}</div>
 <div class="verdict">{e(card['verdict'])}</div>
 {links}
 {rows}
 <h2>Do this week</h2><ol>{todo}</ol>{why_note}
 {charts}
 {howto}
 {pdf_reviews}
 <div class="foot">Lucy checks this every Friday at noon.</div>
</div></body></html>"""


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
