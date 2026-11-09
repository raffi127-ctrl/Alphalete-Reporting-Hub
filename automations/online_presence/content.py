"""Monthly blog + quarterly press release drafts, approved in the office's room.

The BIS package sells a monthly blog and quarterly press releases (Megan
2026-11-09). Lucy drafts both from what actually happened -- the captions of
photos that went out and the office's recent good Google reviews -- and
posts them in the office's room:

    header ("This month's blog draft") -> thread: the draft as a file + a
    preview, and the ✅ / ❌ / 💀 line on the DRAFT message:
      ✅  approved -> "Final, ready to publish" file in the thread
      ❌ + a note -> a new draft with the note applied (a fresh message)
      💀  skip this one

NOT PUBLISHED FOR THEM (yet): posting to their website needs each office's
site login, and wire distribution for a press release is a paid service.
The approved file is ready to paste.

WHEN: the blog on the first weekday of each month from 10am office time; the
press release on the first weekday of Jan / Apr / Jul / Oct. Live offices
only, one of each per period (the period is the key in content.json).

HOUSE RULES baked into the prompt (Megan's standing recruiting-copy rules):
never an age, gender or "who we hire" preference; "team members", not
"reps"; no MLM / "ground floor" language; nothing too-good-to-be-true; real
numbers only if they're in the source material; first names only.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

HOUR = 10
QUARTER_MONTHS = (1, 4, 7, 10)

RULES = (
    "HOUSE RULES (never break): never state or hint at an age, gender or any "
    "'who we hire' preference (no 'young', 'guys', '20-somethings'); say "
    "'team members', never 'reps'; no MLM or 'ground floor' language ('get in, "
    "get paid, move up'); don't sound too good to be true -- put the work on "
    "the reader; use real numbers ONLY if they appear in the material below; "
    "first names only, never last names; no profanity; warm and professional.")


def _load(path: Path) -> Dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save(path: Path, d: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, indent=2))


def first_weekday(year: int, month: int) -> dt.date:
    d = dt.date(year, month, 1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def due(kind: str, now: dt.datetime) -> Optional[str]:
    """The period key this draft is due for right now, else None."""
    if now.hour < HOUR or now.date() < first_weekday(now.year, now.month):
        return None
    if kind == "blog":
        return f"blog-{now:%Y-%m}"
    if kind == "press" and now.month in QUARTER_MONTHS:
        return f"press-{now.year}-Q{(now.month - 1) // 3 + 1}"
    return None


def material(P, now: dt.datetime, days: int) -> str:
    """What happened: captions of photos that went out + recent good reviews."""
    from automations.brand_audit import social_inbox as S
    inbox = S._load_state(P.path("social_inbox.json"))
    since = now.timestamp() - days * 86400
    caps = []
    for ts, st in inbox.items():
        try:
            if isinstance(st, dict) and st.get("published") and float(ts) >= since:
                caps.append(st.get("caption", ""))
        except ValueError:
            continue
    revs = []
    if P.gbp_location:
        try:
            from automations.brand_audit import gbp_api
            for r in gbp_api.list_reviews(P.gbp_location, limit=30):
                if (r.get("rating") or 0) >= 4 and r.get("text"):
                    revs.append(r["text"][:400])
        except Exception:
            pass
    out = [f"Business: {P.business_name} ({P.address}). Website: {P.website}."]
    if caps:
        out += ["Social posts that went out:"] + [f"- {c}" for c in caps[:20]]
    if revs:
        out += ["Recent 4-5 star Google reviews:"] + [f"- {r}" for r in revs[:8]]
    return "\n".join(out)


_SCHEMA = {"type": "object",
           "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
           "required": ["title", "body"], "additionalProperties": False}


def draft(P, kind: str, source: str, feedback: str = "") -> Dict:
    import anthropic
    from automations.brand_audit import credentials
    from automations.brand_audit.social_inbox import MODEL
    if kind == "blog":
        task = ("Write a 500-700 word blog post for the business's website. Pick ONE "
                "angle the material supports (a team win, what training looks like, "
                "a customer story, culture). Helpful and specific, written for people "
                f"near {P.address.split(',')[-2].strip() if ',' in P.address else 'the area'} "
                "who might work with or for the business. A clear title with the city "
                "in it where natural (local SEO). Short paragraphs, 2-3 subheadings "
                "(markdown ##), end with one low-key line inviting readers to learn "
                "more on the website.")
    else:
        task = ("Write a press release (350-500 words) in standard format: headline, "
                "dateline (city, date), lead paragraph, 2-3 body paragraphs, one "
                "quote attributed to 'the team at <business>' (never invent a named "
                "person), and an '### About <business>' boilerplate. Newsworthy only "
                "from the material: growth, promotions, community, milestones.")
    user = f"{task}\n\n{RULES}\n\nMATERIAL (use only this, invent nothing):\n{source}"
    if feedback:
        user += f"\n\nThe approver rejected the last draft. Apply this: \"{feedback}\""
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    resp = client.messages.create(
        model=MODEL, max_tokens=2000,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": user}])
    body = next((b.text for b in resp.content if b.type == "text"), "{}")
    return json.loads(body)


_LABEL = {"blog": "blog post", "press": "press release"}


def _post_draft(P, cl, ts: str, kind: str, d: Dict, key: str, n: int, final=False) -> str:
    """Upload the draft as a .md file in the thread; returns the message ts
    that carries the ✅/❌/💀 line (the reaction target)."""
    f = P.path(f"{key}{'-final' if final else f'-v{n}'}.md")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f"# {d['title']}\n\n{d['body']}\n", encoding="utf-8")
    cl.files_upload_v2(channel=P.slack_channel, thread_ts=ts, file=str(f),
                       title=("FINAL — " if final else "") + d["title"])
    if final:
        cl.chat_postMessage(channel=P.slack_channel, thread_ts=ts,
                            text=":white_check_mark: *Final, ready to publish* — the file "
                                 "above. Paste it into your website's blog"
                                 + (" or send it to your press contacts." if kind == "press" else "."))
        return ""
    preview = d["body"][:600] + ("…" if len(d["body"]) > 600 else "")
    r = cl.chat_postMessage(
        channel=P.slack_channel, thread_ts=ts,
        text=(f":memo: *Draft {n}: {d['title']}*\n\n{preview}\n\n"
              ":white_check_mark: approve · :x: + reply with what to change · "
              ":skull: skip this one"))
    return r.get("ts", "")


def step(P, cl, *, live: bool, now: dt.datetime | None = None) -> List[Dict]:
    """One pass for one office: start any due draft, then handle reactions."""
    from automations.brand_audit import social_inbox as S
    from automations.brand_audit.config import (SOCIAL_APPROVE_EMOJI, SOCIAL_KILL_EMOJI,
                                                SOCIAL_REJECT_EMOJI)
    if not P.social:
        return []
    now = now or dt.datetime.now(ZoneInfo(P.timezone))
    state_file = P.path("content.json")
    state = _load(state_file)
    who, acts = P.counted_approvers, []
    for kind, days in (("blog", 31), ("press", 92)):
        key = due(kind, now)
        if key and key not in state:
            src = material(P, now, days)
            d = draft(P, kind, src)
            acts.append({"action": f"propose_{kind}" if live else f"would_propose_{kind}",
                         "note": d["title"]})
            if live:
                r = cl.chat_postMessage(channel=P.slack_channel,
                                        text=f":memo: *This {'month' if kind == 'blog' else 'quarter'}'s "
                                             f"{_LABEL[kind]} draft for {P.business_name}* — "
                                             "draft in the thread.")
                ts = r.get("ts")
                dts = _post_draft(P, cl, ts, kind, d, key, 1)
                state[key] = {"kind": kind, "status": "proposed", "ts": ts,
                              "draft_ts": dts, "n": 1, "draft": d, "source": src}
    for key, cur in state.items():
        if cur.get("status") != "proposed":
            continue
        allrx = S._thread_reactions(cl, cur["ts"], P.slack_channel)
        rx = allrx.get(cur.get("draft_ts"))
        if any(S._reacted(v, SOCIAL_KILL_EMOJI, who) for v in allrx.values()):
            acts.append({"action": f"{cur['kind']}_skipped", "note": key})
            if live:
                cur["status"] = "skipped"
        elif S._reacted(rx, SOCIAL_APPROVE_EMOJI, who):
            acts.append({"action": f"{cur['kind']}_approved", "note": cur["draft"]["title"]})
            if live:
                _post_draft(P, cl, cur["ts"], cur["kind"], cur["draft"], key, cur["n"], final=True)
                cur["status"] = "approved"
        elif S._reacted(rx, SOCIAL_REJECT_EMOJI, who):
            fb = S._human_reply_after(cl, cur["ts"], cur.get("draft_ts") or cur["ts"],
                                      P.slack_channel)
            d = draft(P, cur["kind"], cur["source"], feedback=(fb or {}).get("text", ""))
            acts.append({"action": f"{cur['kind']}_redraft", "note": d["title"]})
            if live:
                cur["n"] += 1
                cur["draft"] = d
                cur["draft_ts"] = _post_draft(P, cl, cur["ts"], cur["kind"], d, key, cur["n"])
    if live:
        _save(state_file, state)
    return acts
