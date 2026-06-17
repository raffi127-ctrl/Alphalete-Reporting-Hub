"""Render the Brand Health Card — a standalone HTML report (BIS-style layout,
but graded on metrics that matter) plus a short research narrative.

Saved to output/ (per the "one-off outputs go to output/" rule). Self-contained
inline CSS so it opens/prints anywhere. Returns the file path.
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from automations.brand_audit.config import OUTPUT_DIR

# grade letter -> color (first matching prefix wins)
_GRADE_COLORS = [
    ("A", "#2E9E5B"), ("B", "#2D6CDF"), ("C", "#E0A100"),
    ("D", "#E2711D"), ("F", "#D64545"), ("N", "#8A8F98"),  # N/A
]


def _grade_color(grade: str) -> str:
    for prefix, color in _GRADE_COLORS:
        if (grade or "N").startswith(prefix):
            return color
    return "#8A8F98"


def _slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")


def _esc(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def _metric_chip(label: str, value) -> str:
    if value is None or value == "":
        value = "—"
    return (f'<div class="chip"><div class="chip-v">{_esc(value)}</div>'
            f'<div class="chip-l">{_esc(label)}</div></div>')


def _reviews_table_html(rows: list[dict]) -> str:
    head = ("<tr><th>Site</th><th>Rating</th><th>Reviews</th>"
            "<th>New since last audit</th><th>Below 5★</th></tr>")
    trs = []
    for r in rows:
        if not r.get("readable"):
            trs.append(f'<tr><td>{_esc(r["site"])}</td>'
                       f'<td colspan="4" class="muted">couldn\'t read today</td></tr>')
            continue
        rating = f'{r["rating"]}/5' if r.get("rating") is not None else "—"
        total = r["total"] if r.get("total") is not None else "—"
        nsa = r.get("new_since_audit")
        new7 = ('<span class="muted">baseline set</span>' if nsa is None
                else (f'+{nsa}' if nsa else '0'))
        if r.get("below5") is None:
            b5 = '<span class="muted">needs API</span>'
        else:
            b5 = str(r["below5"]) + ('<span class="muted">+ (sample)</span>'
                                     if r.get("below5_partial") else "")
        trs.append(f'<tr><td>{_esc(r["site"])}</td><td>{_esc(rating)}</td>'
                   f'<td>{_esc(total)}</td><td>{new7}</td><td>{b5}</td></tr>')
    return f'<table class="rev">{head}{"".join(trs)}</table>'


def _social_posts_html(posts: list[dict]) -> str:
    if not posts:
        return ""
    rows = []
    for p in posts:
        n = p.get("posts_last_7d")
        val = '<span class="muted">needs API</span>' if n is None else str(n)
        rows.append(f'<tr><td>{_esc(p["platform"])}</td><td>{val}</td></tr>')
    return ('<div class="serp-title">Posts in the last 7 days</div>'
            f'<table class="rev"><tr><th>Platform</th>'
            f'<th>Posts</th></tr>{"".join(rows)}</table>')


def _note_html(note: str) -> str:
    if not note:
        return ""
    paras = "".join(f"<p>{_esc(p.strip())}</p>" for p in note.split("\n\n") if p.strip())
    return ('<div class="note-title">Performance feedback</div>'
            f'<div class="note-box">{paras}</div>')


def _respond_html(respond: list[dict]) -> str:
    if not respond:
        return ('<div class="respond-empty">No below-5★ reviews visible right '
                'now. Once the Business Profile API is approved, every sub-5★ '
                'review lists here with a drafted reply for your approval.</div>')
    items = []
    for r in respond:
        items.append(
            f'<div class="respond-item"><div class="r-head">'
            f'{_esc(r["stars"])}★ · {_esc(r.get("author") or "anonymous")} '
            f'· {_esc(r.get("when") or "")}</div>'
            f'<div class="r-text">“{_esc(r.get("snippet"))}”</div>'
            f'<div class="r-draft"><b>Suggested reply:</b> {_esc(r["draft"])}</div>'
            f'</div>')
    return "".join(items)


_CAT_LABEL = {"owned": "you", "profile": "brand profile",
              "negative": "negative", "neutral": "3rd-party"}
_CAT_CLASS = {"owned": "cat-own", "profile": "cat-prof",
              "negative": "cat-neg", "neutral": "cat-neu"}


def _page1_html(page1: list[dict], limit: int = 6) -> str:
    rows = []
    for e in page1[:limit]:
        cat = e.get("category", "neutral")
        tag = (f'<span class="cat {_CAT_CLASS.get(cat,"cat-neu")}">'
               f'{_CAT_LABEL.get(cat, cat)}</span>')
        title = _esc(e.get("title") or e.get("domain"))
        link = e.get("link") or ""
        title_html = f'<a href="{_esc(link)}">{title}</a>' if link else title
        rows.append(f'<div class="serp-row"><span class="pos">'
                    f'{_esc(e.get("position"))}</span>{tag}'
                    f'<span class="serp-t">{title_html}</span></div>')
    return ('<div class="serp-title">What people see when they Google you</div>'
            + "".join(rows))


def _advice_html(advice: list[dict]) -> str:
    if not advice:
        return ""
    items = []
    for a in advice:
        steps = "".join(f"<li>{_esc(s)}</li>" for s in a.get("steps", []))
        paste = ""
        if a.get("paste"):
            paste = ('<div class="paste-label">Copy &amp; paste this:</div>'
                     f'<div class="paste-box">{_esc(a["paste"])}</div>')
        items.append(
            f'<div class="act"><div class="act-h">'
            f'<span class="act-prio">{_esc(a.get("priority",""))}</span>'
            f'<b>{_esc(a.get("title",""))}</b></div>'
            f'<div class="act-who">Who: {_esc(a.get("who",""))}</div>'
            f'<ol class="steps">{steps}</ol>{paste}</div>')
    return ('<div class="advice-title">What to do — copy-paste steps for the ICD'
            '</div>' + "".join(items))


def _design_review_html(rv: dict) -> str:
    if not rv or not rv.get("vibe"):
        return ""
    rows = []
    for label, key in (("Vibe", "vibe"), ("Photos", "photos"),
                        ("Fit for a 20-25yo", "audience_fit")):
        if rv.get(key):
            rows.append(f'<div class="dr-row"><b>{label}:</b> {_esc(rv[key])}</div>')
    acts = "".join(f"<li>{_esc(a)}</li>" for a in (rv.get("actions") or []))
    actions = (f'<div class="dr-actions-title">Design ideas</div>'
               f'<ul class="dr-actions">{acts}</ul>') if acts else ""
    return ('<div class="dr-title">How the site looks — design review</div>'
            + "".join(rows) + actions)


def _section_html(s: dict) -> str:
    grade = s["grade"]
    color = _grade_color(grade)
    reasons = "".join(f"<li>{_esc(r)}</li>" for r in s["reasons"])
    score_txt = "" if s["score"] is None else f'<span class="score">{s["score"]}/100</span>'
    if s.get("rows") and s["key"] == "reviews":   # reviews table render
        body = _reviews_table_html(s["rows"])
        n_resp = len(s.get("respond") or [])
        body += (f'<div class="respond-title">Reviews needing a response: '
                 f'{n_resp}</div>' + _respond_html(s.get("respond") or []))
    else:               # default chip render
        body = ('<div class="chips">'
                + "".join(_metric_chip(_pretty(k), v) for k, v in s["display"].items())
                + "</div>")
    if s.get("review"):
        body += _design_review_html(s["review"])
    if s.get("posts"):
        body += _social_posts_html(s["posts"])
    if s.get("note"):
        body += _note_html(s["note"])
    if s.get("page1"):
        body += _page1_html(s["page1"])
    if s.get("advice"):
        body += _advice_html(s["advice"])
    return f"""
    <div class="section">
      <div class="grade-box" style="background:{color}">
        <div class="grade">{_esc(grade)}</div>{score_txt}
      </div>
      <div class="section-body">
        <div class="section-title">{_esc(s['label'])}</div>
        {body}
        <ul class="reasons">{reasons}</ul>
      </div>
    </div>"""


_PRETTY = {
    "google_rating": "Google ★", "google_review_count": "Google reviews",
    "google_newest_age_days": "Newest review (days)",
    "indeed_rating": "Indeed ★", "indeed_review_count": "Indeed reviews",
    "glassdoor_rating": "Glassdoor ★", "glassdoor_review_count": "Glassdoor reviews",
    "own_site_position": "Your rank for your name", "has_knowledge_panel": "Knowledge panel",
    "negative_results_on_page1": "Negative page-1 results",
    "negative_reddit_threads": "Negative Reddit threads", "reddit_mentions": "Reddit mentions",
    "reachable": "Site up", "has_blog": "Blog", "newest_content_age_days": "Newest page (days)",
    "sitemap_url_count": "Pages indexed", "channels_connected": "Channels connected",
    "secure_https": "Secure (HTTPS)", "blog_post_count": "Blog posts",
    "pages_updated_90d": "Updated (90d)", "postable_channels": "Postable channels",
    "followers_total": "Followers", "avg_engagement_rate": "Engagement rate",
    "ig_followers": "IG followers", "ig_posts_7d": "IG posts (7d)",
    "ig_last_post_days": "IG last post (days)", "ig_avg_likes": "IG avg likes",
    "ig_engagement_pct": "IG engagement %",
}


def _pretty(key: str) -> str:
    return _PRETTY.get(key, key.replace("_", " ").title())


def _attention_html(flags: list[dict]) -> str:
    negatives = [f for f in flags if f.get("level") == "negative"]
    warns = [f for f in flags if f.get("level") == "warn"]
    if not negatives and not warns:
        return '<div class="ok">✓ No negative findings this run.</div>'
    rows = []
    for f in negatives + warns:
        tag = "🚩" if f["level"] == "negative" else "⚠️"
        link = (f'<a href="{_esc(f["url"])}">{_esc(f.get("detail") or "open")}</a>'
                if f.get("url") else _esc(f.get("detail") or ""))
        rows.append(f'<li>{tag} <b>{_esc(f["message"])}</b><br>'
                    f'<span class="det">{link}</span></li>')
    return f'<ul class="attention">{"".join(rows)}</ul>'


def render_html(company, scorecard: dict, narrative: str,
                as_of: datetime) -> str:
    sections = "".join(_section_html(s) for s in scorecard["sections"])
    overall_color = _grade_color(scorecard["overall_grade"])
    attention = _attention_html(scorecard["flags"])
    month = as_of.strftime("%B %Y")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Brand Health — {_esc(company.name)}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         color:#1a1d24; background:#f4f5f7; margin:0; padding:24px; }}
  .card {{ max-width:820px; margin:0 auto; background:#fff; border-radius:12px;
          overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,.12); }}
  .head {{ background:#2b2f63; color:#fff; padding:22px 28px; display:flex;
          align-items:center; justify-content:space-between; }}
  .head h1 {{ font-size:22px; margin:0; }}
  .head .sub {{ opacity:.8; font-size:13px; margin-top:4px; }}
  .overall {{ text-align:center; }}
  .overall .g {{ font-size:46px; font-weight:800; line-height:1;
                color:{overall_color}; background:#fff; border-radius:10px;
                padding:8px 16px; }}
  .overall .l {{ font-size:11px; letter-spacing:.08em; opacity:.85; margin-top:6px;
                text-transform:uppercase; }}
  .section {{ display:flex; border-top:1px solid #eceef1; }}
  .grade-box {{ width:120px; color:#fff; display:flex; flex-direction:column;
               align-items:center; justify-content:center; padding:18px 8px; }}
  .grade-box .grade {{ font-size:34px; font-weight:800; }}
  .grade-box .score {{ font-size:12px; opacity:.9; }}
  .section-body {{ flex:1; padding:16px 20px; }}
  .section-title {{ font-size:17px; font-weight:700; margin-bottom:10px; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:10px; margin-bottom:10px; }}
  .chip {{ background:#f4f5f7; border-radius:8px; padding:8px 12px; min-width:84px; }}
  .chip-v {{ font-size:20px; font-weight:700; }}
  .chip-l {{ font-size:11px; color:#6b7280; margin-top:2px; }}
  .reasons {{ margin:8px 0 0; padding-left:18px; color:#3a3f48; font-size:12px; }}
  .reasons li {{ margin:2px 0; }}
  table.rev {{ width:100%; border-collapse:collapse; font-size:13px; }}
  table.rev th {{ text-align:left; color:#6b7280; font-weight:600; font-size:11px;
                 padding:4px 8px; border-bottom:1px solid #eceef1; }}
  table.rev td {{ padding:6px 8px; border-bottom:1px solid #f3f4f6; }}
  .muted {{ color:#9aa0a8; font-size:11px; margin-left:3px; }}
  .respond-title {{ margin:12px 0 6px; font-size:13px; font-weight:700; }}
  .respond-empty {{ font-size:12px; color:#6b7280; background:#f4f5f7;
                   border-radius:8px; padding:10px 12px; }}
  .respond-item {{ border-left:3px solid #E2711D; padding:6px 10px; margin:6px 0;
                  background:#fff8f2; border-radius:0 8px 8px 0; }}
  .r-head {{ font-size:12px; font-weight:700; color:#b45309; }}
  .r-text {{ font-size:12px; color:#3a3f48; margin:3px 0; font-style:italic; }}
  .r-draft {{ font-size:12px; color:#1a1d24; }}
  .serp-title, .advice-title {{ margin:12px 0 6px; font-size:13px; font-weight:700; }}
  .dr-title {{ margin:12px 0 6px; font-size:13px; font-weight:700; }}
  .dr-row {{ font-size:12px; color:#3a3f48; margin:3px 0; }}
  .dr-actions-title {{ font-size:12px; font-weight:700; margin:8px 0 3px; }}
  .dr-actions {{ margin:0; padding-left:18px; font-size:12px; color:#2a2e35; }}
  .dr-actions li {{ margin:2px 0; }}
  .note-title {{ margin:12px 0 4px; font-size:13px; font-weight:700; }}
  .note-box {{ background:#f4f7fb; border-left:3px solid #2D6CDF; border-radius:0 8px 8px 0;
              padding:8px 12px; font-size:12px; color:#2a2e35; }}
  .note-box p {{ margin:5px 0; line-height:1.5; }}
  .serp-row {{ display:flex; align-items:center; gap:8px; padding:5px 0;
              border-top:1px solid #f3f4f6; font-size:12px; }}
  .serp-row .pos {{ color:#9aa0a8; width:16px; }}
  .serp-t a {{ color:#2D6CDF; text-decoration:none; }}
  .cat {{ font-size:10px; padding:1px 7px; border-radius:10px; white-space:nowrap; }}
  .cat-own {{ background:#e6f4ec; color:#1f7a44; }}
  .cat-prof {{ background:#eaf1fb; color:#1c5fa6; }}
  .cat-neg {{ background:#fae6e6; color:#b42318; }}
  .cat-neu {{ background:#f1f2f4; color:#6b7280; }}
  .act {{ background:#f7f8fa; border:1px solid #eceef1; border-radius:8px;
         padding:10px 12px; margin:8px 0; }}
  .act-h {{ font-size:13px; }}
  .act-prio {{ font-size:10px; font-weight:700; background:#e6f0fb; color:#1c5fa6;
              padding:1px 7px; border-radius:10px; margin-right:6px; }}
  .act-who {{ font-size:11px; color:#6b7280; margin:2px 0 4px; }}
  ol.steps {{ margin:4px 0; padding-left:20px; font-size:12.5px; color:#2a2e35; }}
  ol.steps li {{ margin:2px 0; }}
  .paste-label {{ font-size:11px; font-weight:700; color:#3a3f48; margin:6px 0 2px; }}
  .paste-box {{ font-family:ui-monospace, Menlo, Consolas, monospace; font-size:12px;
               background:#fff; border:1px dashed #b4c7e0; border-radius:6px;
               padding:8px 10px; color:#1a1d24; white-space:pre-wrap;
               user-select:all; }}
  .attn-wrap {{ padding:18px 28px; background:#fff6f6; border-top:1px solid #f0d4d4; }}
  .attn-wrap h2 {{ font-size:15px; margin:0 0 10px; color:#b42318; }}
  .attention {{ list-style:none; margin:0; padding:0; }}
  .attention li {{ padding:8px 0; border-bottom:1px solid #f3e0e0; font-size:13px; }}
  .attention .det a {{ color:#2D6CDF; text-decoration:none; }}
  .ok {{ color:#2E9E5B; font-weight:600; }}
  .narr {{ padding:18px 28px; font-size:14px; line-height:1.5; color:#2a2e35;
          border-top:1px solid #eceef1; }}
  .foot {{ padding:14px 28px; font-size:11px; color:#8a8f98; border-top:1px solid #eceef1; }}
</style></head><body>
<div class="card">
  <div class="head">
    <div>
      <h1>Brand Health Audit</h1>
      <div class="sub">{_esc(company.name)} · {_esc(company.location)} · {month}</div>
    </div>
    <div class="overall"><div class="g">{_esc(scorecard['overall_grade'])}</div>
      <div class="l">Overall · {scorecard['overall_score']}/100</div></div>
  </div>
  {sections}
  <div class="attn-wrap"><h2>Needs attention</h2>{attention}</div>
  <div class="narr">{narrative}</div>
  <div class="foot">Sources: Google Places API · SerpAPI (Google SERP) ·
    Reddit via Google index · site sitemap · Indeed/Glassdoor scrape.
    Generated {as_of.strftime('%Y-%m-%d %H:%M')}. Social engagement metrics
    pending a platform API. Review-reply + response-rate pending Google Business
    Profile API.</div>
</div></body></html>"""


def build_narrative(company, scorecard: dict) -> str:
    secs = {s["key"]: s for s in scorecard["sections"]}
    rep = secs.get("reputation", {})
    rev = secs.get("reviews", {})
    bits = [f"<b>{_esc(company.name)}</b> earns an overall "
            f"<b>{scorecard['overall_grade']}</b>."]
    if rev.get("grade", "").startswith("A"):
        bits.append("Customer reviews are a genuine strength.")
    if rep.get("score") is not None and rep["score"] < 50:
        bits.append("The drag is <b>reputation in search</b>: negative results "
                    "rank for the brand name, so the strong star rating isn't "
                    "what a prospect sees first. This is the highest-leverage "
                    "fix — outranking those results (fresh owned content, the "
                    "company subreddit, review velocity) moves the overall grade "
                    "more than anything else.")
    return " ".join(bits)


def save_report(company, scorecard: dict, results: dict,
                as_of: datetime | None = None) -> Path:
    as_of = as_of or datetime.now()
    narrative = build_narrative(company, scorecard)
    htmltext = render_html(company, scorecard, narrative, as_of)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slug(company.name)
    stamp = as_of.strftime("%Y%m%d")
    html_path = OUTPUT_DIR / f"brand_health_{slug}_{stamp}.html"
    html_path.write_text(htmltext, encoding="utf-8")
    # also drop the raw data next to it for debugging / future Sheet writes
    (OUTPUT_DIR / f"brand_health_{slug}_{stamp}.json").write_text(
        json.dumps({"company": company.as_dict(), "scorecard": scorecard,
                    "results": results}, indent=2), encoding="utf-8")
    return html_path
