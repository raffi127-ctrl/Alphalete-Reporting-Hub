"""Weekly Google-review rep shout-out list (Maud, 2026-08-07 Loom).

Every week Jolie did this by hand every Monday 8am: open the Alphalete Google
listing → View all reviews → write down the name of every rep a review praises,
tally the duplicates, keep only reviews from the last 7 days (she eyeballs the
dates), then ask Boss for a shout-out and rock-paper-scissors the ties for a
$100 prize.

This automates the pull. Because the Business Profile API is live (gbp_api), we
read the FULL review list with exact timestamps — so the 7-day window is precise
instead of eyeballed — pull the reps each review names (Claude, same extraction
the positive-reply voice already does), tally one point per review per rep,
sort highest→lowest, and post the weekly list to Slack.

Runs Sundays (deploy/brand_audit_noon.sh gates it to weekday 7). When a week
has no new reviews it posts "Google Review WE x.x — No New Reviews for this
week" so the channel always hears back (Eve/Megan, 2026-08-07).

POSTING TARGET is a channel for now (see SHOUTOUT_CHANNEL). Maud asked for a
scheduled DM to "Boss and I"; who "Boss" is / DM-vs-channel is confirmed with
Megan before it goes live — until then it previews to the brand-health channel.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from automations.brand_audit import credentials, gbp_api
from automations.brand_audit.config import (
    ALERT_SLACK_CHANNEL_ID, DEFAULT_COMPANY, GBP_LOCATION_PATH,
    AUTO_POST_MIN_STARS,
)

MODEL = "claude-opus-4-8"

# Where the weekly list posts. Maud asked for a scheduled group DM to Boss + the
# team (Megan, 2026-08-07). When SHOUTOUT_DM_USERS is set the list goes to that
# group DM (opened idempotently each week); otherwise it falls back to
# SHOUTOUT_CHANNEL. Recipients: Bas + Raf + Megan, plus Alisson & Tiffani, whom
# Raf added to watch it / own the ATMO sheet and give feedback (Slack 2026-08-08).
#   U067WLPK92T = Bas               (basboosmahdi@gmail.com)
#   U045Z8N0ZQC = Rafael Hidalgo
#   U04G5HJBGFN = Megan Hidalgo
#   U0BBG374GE9 = Alisson Rodriguez
#   U0B9924FHCL = Tiffani Brown
SHOUTOUT_DM_USERS: tuple = ("U067WLPK92T", "U045Z8N0ZQC", "U04G5HJBGFN",
                            "U0BBG374GE9", "U0B9924FHCL")
# Fallback channel if the group DM is ever cleared (brand-health channel Megan
# and Raf already watch).
SHOUTOUT_CHANNEL = ALERT_SLACK_CHANNEL_ID

# Only reviews at/above this star count are shout-out candidates: a shout-out is
# for a rep a customer PRAISED, so a 1-3star ex-employee/complaint review naming
# someone must not turn into a "give them a shout-out". Same bar the auto-reply
# uses to tell positive from critical.
SHOUTOUT_MIN_STARS = AUTO_POST_MIN_STARS

WINDOW_DAYS = 7

# Don't post the same week twice (the scan is idempotent everywhere else too).
_STATE = Path.home() / ".config" / "brand-audit" / "rep_shoutouts.json"

_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "reps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["reps"], "additionalProperties": False,
}


def _load() -> dict:
    try:
        return json.loads(_STATE.read_text())
    except Exception:
        return {}


def _save(s: dict) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(s, indent=2))


def _parse_time(s: str) -> dt.datetime | None:
    """GBP createTime is RFC-3339 (e.g. '2026-08-05T14:03:11.123Z'). Return a
    tz-aware UTC datetime, or None if it won't parse."""
    if not s:
        return None
    t = s.strip().replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(t)
    except ValueError:
        # Trim fractional seconds to 6 digits if the API sent more/none oddly.
        try:
            head, _, tail = t.partition("+")
            base, _, frac = head.partition(".")
            frac = (frac[:6]) if frac else ""
            rebuilt = base + (("." + frac) if frac else "") + ("+" + tail if tail else "")
            d = dt.datetime.fromisoformat(rebuilt)
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d


def reviews_in_window(company, *, days: int = WINDOW_DAYS,
                      now: dt.datetime | None = None) -> list[dict]:
    """Positive reviews created in the last `days` days, newest first.

    Reads the full Business Profile review list (not the Places 5-review sample)
    so the window is exact. Filters to >= SHOUTOUT_MIN_STARS — only praise counts
    as a shout-out."""
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=days)
    revs = gbp_api.list_reviews(GBP_LOCATION_PATH)
    out = []
    for rv in revs:
        when = _parse_time(rv.get("publish_time", ""))
        if not when or when < cutoff:
            continue
        stars = rv.get("rating")
        if not isinstance(stars, (int, float)) or stars < SHOUTOUT_MIN_STARS:
            continue
        rv = dict(rv)
        rv["_when"] = when
        out.append(rv)
    out.sort(key=lambda r: r["_when"], reverse=True)
    return out


def _titlecase(name: str) -> str:
    """Title-case a rep's name, preserving intra-name capitals like McClain / II
    (house rule). Only touches all-lower or all-upper tokens."""
    parts = []
    for tok in name.split():
        if tok.islower() or tok.isupper():
            parts.append(tok[:1].upper() + tok[1:].lower())
        else:
            parts.append(tok)             # already mixed (McClain, DeShawn) — keep
    return " ".join(parts)


def extract_reps(review: dict) -> list[str]:
    """The Alphalete rep first-name(s) a single review praises (distinct, first
    name only). [] when the review names no rep. Excludes the reviewer's own
    name so a customer signing their review isn't counted as a rep."""
    text = (review.get("text") or "").strip()
    if not text:
        return []
    import anthropic
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    author = (review.get("author") or "").strip()
    system = (
        "You read a positive Google review of Alphalete Marketing, a direct "
        "sales company. Extract the FIRST names of the Alphalete reps / "
        "employees the reviewer is thanking or praising for the service they "
        "received — the company's people, not the reviewer.\n\n"
        "RULES:\n"
        "- First name only, properly capitalized (e.g. 'Dylan', 'Marquise').\n"
        "- Each distinct rep once, even if named several times.\n"
        "- Do NOT include the reviewer's own name, the company name, or generic "
        "words ('the team', 'everyone', 'the guys').\n"
        "- If the review praises no specific person by name, return an empty "
        "list. A rating with only generic praise names no rep.\n"
        + (f"- The reviewer is '{author}' — never return that name as a rep.\n"
           if author else ""))
    user = f"Review:\n\"{text}\"\n\nList the rep first names praised."
    resp = client.messages.create(
        model=MODEL, max_tokens=200, system=system,
        output_config={"format": {"type": "json_schema", "schema": _EXTRACT_SCHEMA}},
        messages=[{"role": "user", "content": user}])
    body = next((b.text for b in resp.content if b.type == "text"), "{}")
    names = json.loads(body).get("reps", []) or []
    # Normalize + dedupe within this one review (case-insensitive).
    seen, clean = set(), []
    for n in names:
        n = _titlecase((n or "").strip())
        key = n.lower()
        if n and key not in seen and key != author.lower():
            seen.add(key)
            clean.append(n)
    return clean


def tally(reviews: list[dict]) -> list[tuple[str, int]]:
    """One point per review per distinct rep named, summed across the week and
    sorted highest→lowest (ties broken alphabetically). Mirrors what Maud does
    by hand: a rep praised in two separate reviews scores 2."""
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for rv in reviews:
        for name in extract_reps(rv):
            key = name.lower()
            counts[key] = counts.get(key, 0) + 1
            display.setdefault(key, name)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(display[k], c) for k, c in ranked]


def _week_ending(now: dt.datetime | None = None) -> dt.date:
    """The Sunday on/most-recently-before today — the 'week ending' date used
    in the 'WE x.x' title (the report pulls on Sundays)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    d = now.date()
    # weekday(): Mon=0 .. Sat=5, Sun=6. Days since the last Sunday.
    back = (d.weekday() - 6) % 7
    return d - dt.timedelta(days=back)


def _we_label(d: dt.date) -> str:
    # "8.9" — no leading zeros, cross-platform (no %-d).
    return f"{d.month}.{d.day}"


def build_message(ranked: list[tuple[str, int]], week_ending: dt.date) -> str:
    """The Slack text: the ranked shout-out list, or the no-new-reviews line."""
    we = _we_label(week_ending)
    if not ranked:
        return f"*Google Review WE {we} — No New Reviews for this week*"
    top = ranked[0][1]
    lines = [f"*Google Review WE {we} — Reps to Shout Out* :tada:",
             "_Reps named in Google reviews this week (last 7 days), most first._",
             ""]
    medals = {1: ":first_place_medal: ", 2: ":second_place_medal: ",
              3: ":third_place_medal: "}
    rank = 0
    last_count = None
    for name, count in ranked:
        if count != last_count:
            rank += 1
            last_count = count
        badge = medals.get(rank, "")
        star = " ⭐" if count == top else ""
        lines.append(f"{badge}*{name}* — {count}{star}")
    tied = [n for n, c in ranked if c == top]
    lines.append("")
    if len(tied) > 1:
        lines.append(f":rock: Tie for most ({top}): "
                     + ", ".join(tied)
                     + " — rock-paper-scissors for the prize.")
    lines.append("Can we give these reps a shout-out? :clap:")
    return "\n".join(lines)


def weekly_shoutouts(company_name: str = DEFAULT_COMPANY, *, dry_run: bool = True,
                     channel: str | None = None, force: bool = False) -> dict:
    """Pull the last 7 days of Google reviews, tally the reps praised, and post
    the weekly shout-out list to Slack. Idempotent per week-ending date unless
    `force`. Returns a summary dict (message + ranking) for logging/preview."""
    from automations.brand_audit import intake
    company = intake.find_company(company_name)
    if not company:
        return {"error": f"company {company_name!r} not found"}
    channel = channel or SHOUTOUT_CHANNEL
    week_ending = _week_ending()
    we_key = week_ending.isoformat()

    state = _load()
    already = state.get("posted", {}).get(we_key)
    if already and not dry_run and not force:
        return {"skipped": "already posted this week", "week_ending": we_key,
                "message": already.get("message", "")}

    reviews = reviews_in_window(company)
    ranked = tally(reviews)
    message = build_message(ranked, week_ending)
    summary = {"week_ending": we_key, "reviews_in_window": len(reviews),
               "ranking": ranked, "message": message, "dry_run": dry_run}

    # Write the names onto the Monday ATMO print (Google Doc), replacing last
    # week's. Best-effort + isolated: inert until the Docs token exists and the
    # write is enabled (atmo_doc rollout guard), and a doc failure must never
    # block the Slack DM.
    from automations.brand_audit import atmo_doc
    if atmo_doc.has_token():
        try:
            summary["doc"] = atmo_doc.write_shoutouts(ranked, dry_run=dry_run)
        except Exception as e:
            summary["doc_error"] = str(e)[:300]

    if dry_run:
        return summary

    from automations.brand_audit.social_inbox import _client
    cl = _client()
    # Prefer the confirmed group DM (Bas + Raf + Megan). conversations_open is
    # idempotent — same members return the same mpim channel every week — and
    # falls back to the channel if opening the DM fails (e.g. a user left).
    if channel is SHOUTOUT_CHANNEL and SHOUTOUT_DM_USERS:
        try:
            opened = cl.conversations_open(users=",".join(SHOUTOUT_DM_USERS))
            channel = (opened.get("channel") or {}).get("id") or channel
        except Exception as e:
            summary["dm_open_error"] = str(e)[:200]
    r = cl.chat_postMessage(channel=channel, text=message)
    state.setdefault("posted", {})[we_key] = {"ts": r.get("ts"),
                                              "message": message}
    _save(state)
    summary["posted_ts"] = r.get("ts")
    return summary


def main(argv=None) -> int:
    import argparse
    import sys
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="brand_audit.rep_shoutouts")
    p.add_argument("--company", default=DEFAULT_COMPANY)
    p.add_argument("--dry-run", action="store_true",
                   help="build + print the list, post nothing")
    p.add_argument("--channel", default=None, help="override the Slack channel")
    p.add_argument("--force", action="store_true",
                   help="post even if this week was already posted")
    args = p.parse_args(argv)
    out = weekly_shoutouts(args.company, dry_run=args.dry_run,
                           channel=args.channel, force=args.force)
    if out.get("error"):
        print("ERROR:", out["error"])
        return 1
    if out.get("skipped"):
        print("skipped:", out["skipped"], "(", out.get("week_ending"), ")")
        return 0
    print(f"=== week ending {out['week_ending']} · "
          f"{out.get('reviews_in_window', 0)} positive reviews in window ===")
    for name, count in out.get("ranking", []):
        print(f"  {name}: {count}")
    print("--- message ---")
    print(out["message"])
    if out.get("posted_ts"):
        print(f"--- posted to Slack (ts {out['posted_ts']}) ---")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
