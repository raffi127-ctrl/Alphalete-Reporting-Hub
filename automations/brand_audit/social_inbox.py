"""Slack photo → caption → approve → post workflow (#alphaletesocialmedia).

The flow (polled, not live):
  1. Someone drops a photo in the intake channel.
  2. No context? -> reply in-thread asking who / what / when / where.
  3. Has context -> Claude (vision) drafts a caption, posted as a thread reply.
  4. An authorized person approves by reacting (✅) — and may swap in an edited
     photo (re-upload in the thread; the latest image is the one used) or tweak
     the caption (reply with the new wording).
  5. Approved -> post to the chosen platform(s) [posting layer pluggable —
     decided later: IG-native vs aggregator].

State is tracked in ~/.config/brand-audit/social_inbox.json so each submission
is handled once. Posting is currently a stub (logs what it WOULD post) until
the posting destination is wired.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path

import requests

from automations.brand_audit import credentials, photo_edit, style
from automations.brand_audit.config import (
    SOCIAL_INBOX_CHANNEL_ID, SOCIAL_APPROVERS, SOCIAL_APPROVE_EMOJI,
    SOCIAL_REJECT_EMOJI, SOCIAL_KILL_EMOJI, SOCIAL_POSTED_EMOJI,
    DEFAULT_COMPANY, OUTPUT_DIR,
)

_STATE = Path.home() / ".config" / "brand-audit" / "social_inbox.json"
_LOCK = Path.home() / ".config" / "brand-audit" / "social_inbox.lock"
MODEL = "claude-opus-4-8"


# ---- singleton lock (already-running guard) ---------------------------------
# The state file is written once at the END of process_inbox, so two overlapping
# runs would both read the same state and both post the same photo. This
# pid-lockfile lets only ONE run touch the inbox at a time — so the noon launchd
# run and a manual Hub "Run Now" can never double-process a submission. Same
# idiom as automations.day_orchestrator.state (pid-based, reclaims stale locks).
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def acquire_lock(path: Path | None = None) -> bool:
    """True if we got the singleton lock. False if another LIVE run holds it.
    A stale lock (dead pid) is reclaimed. `path` = an office's own lock, so
    one office's pass never waits on (or races) another's."""
    lock = path or _LOCK
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        try:
            old = int(lock.read_text().strip() or "0")
        except ValueError:
            old = 0
        if old and old != os.getpid() and _pid_alive(old):
            return False
    lock.write_text(str(os.getpid()))
    return True


def release_lock(path: Path | None = None) -> None:
    lock = path or _LOCK
    try:
        if lock.exists() and lock.read_text().strip() == str(os.getpid()):
            lock.unlink()
    except OSError:
        pass

_CONTEXT_QUESTION = (
    "Thanks for the photo! To caption it right, can you reply here with:\n"
    "• *Who* is pictured (left to right)\n"
    "• *What* it is (promo, team night, event, atmosphere, pinning…)\n"
    "• *When / where* it happened\n"
    "• If a promotion: who was promoted, their new level, and their trainer"
)

_CAPTION_SCHEMA = {
    "type": "object",
    "properties": {"caption": {"type": "string"}},
    "required": ["caption"], "additionalProperties": False,
}


# ---- Slack helpers (reuse the shared user token) ----------------------------
def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def _token() -> str:
    from automations.shared import slack_metrics_post as smp
    return smp._load_token()


def _load_state(path: Path | None = None) -> dict:
    try:
        return json.loads((path or _STATE).read_text())
    except Exception:
        return {}


def _save_state(s: dict, path: Path | None = None) -> None:
    f = path or _STATE
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(s, indent=2))


def _image_files(msg: dict) -> list[dict]:
    return [f for f in (msg.get("files") or [])
            if str(f.get("mimetype", "")).startswith("image/")]


# SAME / NEAR-SAME PHOTO GUARD (Megan 2026-11-09: "we need to build a guard to
# not post 2 of the same photo/similar photo"). Every photo Lucy proposes is
# fingerprinted (photo_edit.dhash, on the edited version, so old photos can be
# fingerprinted from what's saved). A new one within SAME_PHOTO_BITS of any
# earlier one is held: Lucy says which one it matches, and an approver ✅ posts
# it anyway (a genuinely different shot) or ❌ drops it.
MAX_PHOTOS = 10              # one post holds up to 10 photos (Instagram's cap)
SAME_PHOTO_BITS = 10          # of 64; same shot re-sent ~0-4, a burst shot ~6-10
_HASHES = "_photo_hashes"
KEEP_HASHES = 500


def _seed_hashes(state: dict) -> list:
    """The fingerprint list, back-filled from photos proposed before the guard."""
    seen = state.setdefault(_HASHES, [])
    have = {x["ts"] for x in seen}
    for k, st in list(state.items()):
        if k.startswith("_") or not isinstance(st, dict):
            continue
        for i, p in enumerate(_paths(st)):
            key = k if i == 0 else f"{k}#{i}"
            if key in have or not Path(p).exists():
                continue
            try:
                seen.append({"ts": key, "h": f"{photo_edit.dhash(Path(p).read_bytes()):016x}"})
            except Exception:
                pass
    return seen


def _paths(st: dict) -> list:
    """Every edited photo of one post (a post made before albums has one)."""
    return list(st.get("photo_paths") or ([st["photo_path"]] if st.get("photo_path") else []))


def twin_of(seen: list, h: int, ts: str) -> dict | None:
    """The earlier photo this one matches, or None."""
    best = None
    for x in seen:
        if x["ts"] == ts:
            continue
        d = photo_edit.hash_distance(h, int(x["h"], 16))
        if d <= SAME_PHOTO_BITS and (best is None or d < best[0]):
            best = (d, x)
    return best[1] if best else None


def _dup_text(cl, chan: str, ts: str, twins: list, n: int) -> str:
    """The hold note: which photo matches which earlier one, with a link."""
    bits = []
    for i, twin in twins:
        link = ""
        if _post_ts(twin["ts"]) != ts:
            try:
                link = cl.chat_getPermalink(channel=chan,
                                            message_ts=_post_ts(twin["ts"])).get("permalink", "")
            except Exception:
                pass
        if _post_ts(twin["ts"]) == ts:
            j = int(twin["ts"].split("#")[1]) if "#" in twin["ts"] else 0
            where = f"photo {j + 1} in this same post"
        else:
            where = (f"<{link}|the one sent {_when(twin['ts'])}>" if link
                     else f"one sent {_when(twin['ts'])}")
        bits.append((f"photo {i + 1}" if n > 1 else "it") + f" looks like {where}")
    return (":repeat: *Holding this one*: " + "; ".join(bits) + ". We never post the "
            "same photo twice.\n*Approvers: react :white_check_mark: if they're really "
            "different photos, :x: to skip this post.*")


def _merge_quality(reports: list) -> dict | None:
    reports = [r or {} for r in reports]
    if len(reports) == 1:
        return reports[0]
    warns = [f"Photo {i + 1}: {w}" for i, r in enumerate(reports) for w in r.get("warnings") or []]
    return {"ok": all(r.get("ok", True) for r in reports), "warnings": warns}


def _save_edits(prefix: str, ts: str, edited: list) -> list:
    """Photo 1 keeps the old file name (so older posts still line up)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{prefix}{ts.replace('.', '')}_ig"
    out = []
    for i, im in enumerate(edited):
        p = OUTPUT_DIR / (f"{stem}.jpg" if i == 0 else f"{stem}_{i + 1}.jpg")
        p.write_bytes(im)
        out.append(p)
    return out


def _post_ts(key: str) -> str:
    return key.split("#")[0]


def _when(ts: str) -> str:
    import datetime as _dt
    try:
        d = _dt.datetime.fromtimestamp(float(_post_ts(ts)))
        return f"{d:%b} {d.day}"            # no %-d: it breaks on Windows
    except Exception:
        return "earlier"


def _download(url: str) -> bytes:
    # File downloads need files:read — use the bot token (it has it) and fall
    # back to the user token. The bot must be a member of the channel.
    tok = credentials.optional("slack_bot_token") or _token()
    r = requests.get(url, headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    r.raise_for_status()
    return r.content


def _has_context(text: str) -> bool:
    """Is there enough text to caption from? (a bare photo or a one-word note
    isn't enough)."""
    t = (text or "").strip()
    if not t or "has joined the channel" in t:
        return False
    return len(t) >= 8


def _reacted(reactions: list[dict] | None, emoji: tuple,
             approvers: tuple | None = None) -> bool:
    """True if an authorized approver reacted with one of `emoji`.
    `approvers` = an office's own list; None = Alphalete's SOCIAL_APPROVERS."""
    allowed = SOCIAL_APPROVERS if approvers is None else approvers
    for rx in (reactions or []):
        if rx.get("name") not in emoji:
            continue
        users = rx.get("users") or []
        if not allowed:                   # no allow-list set yet → anyone counts
            return True
        if any(u in allowed for u in users):
            return True
    return False


def _thread_reactions(cl, parent_ts: str, channel: str | None = None) -> dict:
    """{message_ts: reactions} for a thread, read via conversations_replies
    (history scope; includes reactor user IDs — reactions.get needs a scope our
    token lacks).

    `channel` defaults to the social inbox (what this module's own flows use),
    but MUST be passed by callers whose threads live elsewhere — review_replies
    posts to the brand-health alert channel, and reading it against the social
    inbox silently returned {} (so every reaction was invisible and no draft
    ever got approved or redrafted). Fixed 2026-07-16."""
    out = {}
    try:
        for m in cl.conversations_replies(channel=channel or SOCIAL_INBOX_CHANNEL_ID,
                                          ts=parent_ts).get("messages", []):
            out[m["ts"]] = m.get("reactions")
    except Exception:
        pass
    return out


def _human_reply_after(cl, parent_ts: str, after_ts: str,
                       channel: str | None = None) -> dict | None:
    """Latest plain-text reply in the thread, posted after `after_ts`, that is a
    human answer (not one of our bot prompts — those start with an emoji
    shortcode). Used to read why a photo was rejected."""
    try:
        reps = cl.conversations_replies(channel=channel or SOCIAL_INBOX_CHANNEL_ID,
                                        ts=parent_ts).get("messages", [])
    except Exception:
        return None
    out = None
    for r in reps:
        if r.get("ts", "") <= (after_ts or ""):
            continue
        if r.get("files"):
            continue
        t = (r.get("text") or "").strip()
        if not t or t.startswith(":"):   # skip blanks + our emoji-led prompts
            continue
        out = r
    return out


_SCREEN_SCHEMA = {
    "type": "object",
    "properties": {
        "safe": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["safe"], "additionalProperties": False,
}


def screen_photo(image_bytes: bytes, company_name: str) -> list[str]:
    """Brand-safety screen. Returns a list of issues (empty = safe to post).
    HARD RULE: never post alcohol, profanity, gang signs, or anything that
    reads ghetto/thuggish/unprofessional."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
        system = (
            f"You screen photos before they post on {company_name}'s social "
            "accounts. The brand must look POLISHED and PROFESSIONAL — it "
            "recruits young professionals and must NEVER look ghetto, thuggish, "
            "or unprofessional. Set safe=false and name the issue if the photo "
            "shows ANY of: alcohol or drinking (bottles, cans, cups of beer/"
            "liquor), visible profanity or offensive text/symbols, gang signs / "
            "throwing up sets, middle fingers, flashing cash, weapons, drugs/"
            "vaping/smoking, or clothing/poses/anything that looks thuggish or "
            "unprofessional. IMPORTANT: normal friendly gestures are FINE — "
            "thumbs up, pointing, peace sign, shaka, clapping, arms crossed; do "
            "NOT flag those as gang signs. If the photo is clean and "
            "professional, safe=true.")
        resp = client.messages.create(
            model=MODEL, max_tokens=200, system=system,
            output_config={"format": {"type": "json_schema",
                                       "schema": _SCREEN_SCHEMA}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": "image/jpeg",
                 "data": base64.standard_b64encode(image_bytes).decode()}},
                {"type": "text", "text": "Screen this photo."},
            ]}])
        body = next((b.text for b in resp.content if b.type == "text"), "{}")
        data = json.loads(body)
        return [] if data.get("safe") else (data.get("issues") or ["flagged"])
    except Exception:
        return []   # screening failure shouldn't hard-block; logged elsewhere


def _clean_reply(text: str) -> str:
    """Reply text with @mentions stripped (so a bare tag/ping reads as empty)."""
    return re.sub(r"<@[^>]+>", "", text or "").strip()


def _rep_context(cl, parent_ts: str, channel: str | None = None,
                 approvers: tuple | None = None) -> str:
    """Substantive replies from a REP (a non-approver) — the real answers to
    Lucy's questions. Approver messages (Megan/Raf uploading photos or tagging
    the rep to respond) and bare @-pings do NOT count as the answer."""
    out = []
    allowed = SOCIAL_APPROVERS if approvers is None else approvers
    try:
        for r in cl.conversations_replies(channel=channel or SOCIAL_INBOX_CHANNEL_ID,
                                          ts=parent_ts).get("messages", []):
            if r.get("ts") == parent_ts or r.get("files"):
                continue
            if r.get("user") in allowed:   # not the rep's answer
                continue
            t = _clean_reply(r.get("text"))
            if t and not t.startswith(":") and len(t) >= 3:
                out.append(t)
    except Exception:
        pass
    return " | ".join(out)


def _rep_answered_after(cl, parent_ts: str, after_ts: str,
                        channel: str | None = None,
                        approvers: tuple | None = None) -> bool:
    """True if a rep (non-approver) posted a substantive reply after `after_ts`."""
    allowed = SOCIAL_APPROVERS if approvers is None else approvers
    try:
        for r in cl.conversations_replies(channel=channel or SOCIAL_INBOX_CHANNEL_ID,
                                          ts=parent_ts).get("messages", []):
            if r.get("ts", "") <= (after_ts or "") or r.get("files"):
                continue
            if r.get("user") in allowed:
                continue
            t = _clean_reply(r.get("text"))
            if t and not t.startswith(":") and len(t) >= 3:
                return True
    except Exception:
        pass
    return False


_CONTEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "enough": {"type": "boolean"},
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["enough"], "additionalProperties": False,
}


def needs_more_context(image_bytes: bytes, context: str,
                       company_name: str) -> list[str]:
    """Decide if there's enough to caption well; return clarifying questions if
    not (empty list = good to go). Lucy asks rather than guesses."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
        system = (
            f"You are Lucy, writing a social caption for {company_name} (a "
            "door-to-door sales company) from a submitted photo + context. "
            "Decide if you have ENOUGH to write a SPECIFIC, accurate caption: "
            "who is featured (first names), what the moment is (a promotion + "
            "which level, an event, a win, team culture), and any key detail. If "
            "something important is missing or ambiguous, set enough=false and "
            "give 1-3 short, friendly questions to ask the submitter in Slack. "
            "If you can already write a good, accurate caption, enough=true with "
            "no questions. Don't ask for trivia — only what materially improves "
            "the caption. Never guess at names or what's happening.")
        resp = client.messages.create(
            model=MODEL, max_tokens=300, system=system,
            output_config={"format": {"type": "json_schema",
                                       "schema": _CONTEXT_SCHEMA}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": "image/jpeg",
                 "data": base64.standard_b64encode(image_bytes).decode()}},
                {"type": "text", "text": f"Context so far: {context or '(none)'}"},
            ]}])
        body = next((b.text for b in resp.content if b.type == "text"), "{}")
        data = json.loads(body)
        return [] if data.get("enough") else (data.get("questions") or [])
    except Exception:
        return []   # on any error, don't block — caption with what we have


_PHOTO_FEEDBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["skip", "fix"]},
        "aspect": {"type": "string",
                   "enum": ["keep", "4:5", "1:1", "1.91:1"]},
        "brightness": {"type": "number"},
        "contrast": {"type": "number"},
        "saturation": {"type": "number"},
        "zoom": {"type": "number"},
        "note": {"type": "string"},
    },
    "required": ["intent"], "additionalProperties": False,
}


def _interpret_photo_feedback(text: str) -> dict:
    """Decide why an approver ❌'d the photo. intent='skip' if they don't want
    THIS photo posted at all (content/privacy/'not this one'); intent='fix' if
    it's about how the image LOOKS, with modest adjustment multipliers + a short
    human-facing note. Falls back to a gentle brighten on any API hiccup."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
        system = (
            "An approver rejected an auto-edited social photo and gave a reason. "
            "If they simply don't want THIS photo posted (privacy, wrong moment, "
            "'not this one', 'skip it'), return intent='skip'. If the complaint "
            "is about how the image LOOKS (too dark/bright, dull/flat, washed "
            "out, bad crop, color/tint, too zoomed out / cropped too loose), "
            "return intent='fix' with multipliers (1.0 = no change; "
            "brightness/contrast 0.7-1.4, saturation 0.6-1.4), an aspect ('keep' "
            "unless they want a different shape), and zoom — be generous: 1.5-1.8 "
            "if they want it cropped tighter / more zoomed in on the subjects "
            "(1.7+ if they say 'more' / it's still too loose); 1.0 only if crop "
            "is fine. "
            "Add a short, "
            "friendly `note` saying what you changed (or, if it's something we "
            "can't fix like blur/low-res, say so plainly).")
        resp = client.messages.create(
            model=MODEL, max_tokens=300, system=system,
            output_config={"format": {"type": "json_schema",
                                       "schema": _PHOTO_FEEDBACK_SCHEMA}},
            messages=[{"role": "user", "content":
                       f"Approver's reason: {text!r}"}])
        body = next((b.text for b in resp.content if b.type == "text"), "{}")
        return json.loads(body)
    except Exception:
        return {"intent": "fix", "aspect": "keep", "brightness": 1.12,
                "zoom": 1.0, "note": "Brightened it up a touch — take another look."}


def _newest_file_reply_ts(cl, parent_ts: str,
                          channel: str | None = None) -> str | None:
    """ts of the most recent thread reply carrying a file (the photo we just
    uploaded). Retries — the file message can lag a beat after upload."""
    for _ in range(5):
        try:
            reps = cl.conversations_replies(channel=channel or SOCIAL_INBOX_CHANNEL_ID,
                                            ts=parent_ts).get("messages", [])
            files = [r for r in reps if r.get("files") and r.get("ts") != parent_ts]
            if files:
                return files[-1]["ts"]
        except Exception:
            pass
        time.sleep(1.5)
    return None


# ---- caption generation -----------------------------------------------------
def caption_for(image_bytes: bytes, context: str, company_name: str,
                avoid: list[str] | None = None, feedback: str = "",
                style_path: Path | None = None) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    system = (
        f"You write Instagram captions for {company_name}, a door-to-door sales "
        "company. Aim for a SIMILAR VIBE to accounts like @newbern.excel and the "
        "energy of Hormozi / Gary Vee / Grant Cardone — but this is our OWN "
        "voice, NOT a copy of anyone. Audience: ambitious 20-25 year-olds "
        "deciding whether to build a career here, plus our clients and community.\n"
        "#1 PRINCIPLE — DOCUMENT, DON'T CREATE. You are capturing real moments "
        "from inside the company, not manufacturing ads. Caption what's actually "
        "happening — the people, the team energy, the day — like a teammate "
        "sharing it, not a marketer selling it.\n"
        "#2 PRIORITY — CULTURE OVER EVERYTHING. Above wins, money, or "
        "promotions, these posts show the CULTURE: the people, the team energy, "
        "the brotherhood/family feel, the fun, the sense of belonging. Even a "
        "results or promotion post is really about the person and the team around "
        "them.\n"
        "TONE: warm, celebratory, genuinely happy FOR the people in the photo — "
        "like a teammate hyping them up, not a brand account. High-energy and "
        "confident, but human and kind. Celebrate the PERSON first, the result "
        "second.\n"
        "MATCH THE PHOTO TO A POST TYPE — we post a WIDE RANGE, not just wins:\n"
        "- Promotion / pin: warmly congratulate the person by name, name the "
        "growth, hype their future.\n"
        "- Results / income: name the person + the real number from the context, "
        "one punchy line on their mindset, celebrate the win.\n"
        "- Client / customer appreciation: genuine gratitude to the people we "
        "serve — thank them, show we value their trust, highlight a happy "
        "customer or a job well done. Warm and sincere, not salesy.\n"
        "- Culture / lifestyle (team hanging out, morning vibe, office, events): "
        "light, fun, relatable — NOT every post is a win. It's great to ask the "
        "audience a question.\n"
        "- Milestone / event / behind-the-scenes: conferences, team trips, a "
        "normal day in the field, recognition nights — document the moment.\n"
        "- Values / why: the deeper reason — growth, becoming someone, building a "
        "life worth wanting.\n"
        "Let the photo + context decide the type. Keep the overall feed varied.\n"
        "CALL TO ACTION — USE SPARINGLY. Do NOT turn every post into a "
        "recruiting pitch. Most posts are just documenting the moment and need NO "
        "CTA. Only add a low-key invite ('DM INFO to learn more') now and then, "
        "when it genuinely fits — never forced, never salesy.\n"
        "STYLE:\n"
        "- SHORT. 2-4 short lines.\n"
        f"- Hashtags are GOOD here — end with 3-5 tags: a brand tag built from "
        f"the company name (e.g. #{company_name.replace(' ', '')}) plus a few "
        "relevant ones. Don't exceed ~5.\n"
        "- 1-3 relevant emoji are on-brand (🔥💰👏🚀). Don't go wall-to-wall.\n"
        "- FEATURE THE PERSON BEING PROMOTED/FEATURED — center their win. The "
        "trainer/mentor is secondary: mention them in passing at most, often not "
        "at all. Don't make the post about the trainer.\n"
        "- AUDIENCE = APPLICANTS. Write so a 20-25yo thinking about joining feels "
        "it could be them — naturally, no tacked-on salesy CTA.\n"
        "- DON'T SOUND AI. The #1 tell is the balanced three-part phrase / "
        "tricolon ('suited up, locked in, ready to work', 'two suits, big smiles, "
        "well earned') — NEVER write those. Also ban filler hype: 'well earned', "
        "'just getting started', 'the work shows', 'locked in', 'put in the "
        "work'. Write like a real teammate typing fast on their phone: short, "
        "plain, ONE specific real detail beats three generic ones.\n"
        "- Vary every caption — don't reuse the same hook or closer across posts; "
        "if a line feels like a template you've used, rewrite it.\n"
        "- FIRST NAMES ONLY — never use anyone's last name.\n"
        "- Never use profanity or anything that reads unprofessional/thuggish — "
        "the brand stays clean and polished.\n"
        "- Use the real names/context. Never invent specific numbers, dates, "
        "timelines, or perks that aren't in the context.\n"
        "- NEVER put a person's internal level in parentheses after their name "
        "(no 'Vincent (LVL 3)'). Naming the promotion itself ('Level 2') is fine."
    )
    from automations.brand_audit import style
    learned = style.caption_rules(style_path)
    if learned:
        system += ("\n\nSTANDING TEAM FEEDBACK — ALWAYS FOLLOW (learned from past "
                   "corrections; these override anything above if they conflict):\n"
                   + "\n".join(f"- {r}" for r in learned))
    user_text = f"Context from the submitter:\n{context}\n\nWrite the caption."
    if feedback:
        user_text += (
            f"\n\nThe approver REJECTED the previous caption with this feedback — "
            f"apply it directly: \"{feedback}\". If they said it sounds too AI / "
            "generic, make it sound like a real teammate typed it fast: plainer "
            "words, a specific human detail, drop polished marketing phrasing and "
            "any line that feels templated.")
    if avoid:
        recent = "\n".join(f"- {c}" for c in avoid if c)
        user_text += (
            "\n\nCRITICAL — DO NOT SOUND AUTOMATED. Here are our RECENT captions. "
            "Even if THIS photo is the same kind of moment (e.g. another "
            "promotion), the caption must feel written fresh by a different "
            "person. Do NOT reuse — not even reworded — any of these from the "
            "list below: a line or phrase; an opener or closer (e.g. 'Proud of "
            "you, NAME'); a sentence shape or rhythm; a recurring framing (e.g. "
            "'two women...', 'got to be the one to call it', 'just getting "
            "started', 'the climb'); or the same topical hashtags (the brand tag "
            "is the only one allowed to repeat). Find a different angle, "
            "structure, and word choice every time:\n"
            f"{recent}"
        )
    resp = client.messages.create(
        model=MODEL, max_tokens=400, system=system,
        output_config={"format": {"type": "json_schema", "schema": _CAPTION_SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
             "media_type": "image/jpeg",
             "data": base64.standard_b64encode(image_bytes).decode()}},
            {"type": "text", "text": user_text},
        ]}])
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    return json.loads(text).get("caption", "")


# ---- an ICD office's publish step ------------------------------------------
def _office_publish(P, cl, ts: str, st: dict, caption: str, dry_run: bool,
                    sched_file: Path, zoho_prof: Path) -> list[dict]:
    """Both halves approved -> out it goes, on the OFFICE's own Zoho.

    One post a day, never after 6pm, on the office's own clock. A Zoho plan
    that can schedule gets a time; the free plan may not, so Lucy publishes
    it herself ("Post Now") on the first pass inside the window -- and if
    today already had its post, it waits for tomorrow's pass.

    Errors stay in the action list (our log), never in the office's room."""
    import datetime as dt
    from zoneinfo import ZoneInfo
    from automations.brand_audit import zoho_draft
    if st.get("scheduled") or st.get("published") or st.get("eco_job"):
        return []
    photo = _paths(st)
    now = dt.datetime.now(ZoneInfo(P.timezone)).replace(tzinfo=None)
    if P.post_via == "eco":
        return _office_queue(P, ts, st, caption, dry_run, sched_file, now)
    if P.zoho_schedules:
        slot = zoho_draft.next_daily_slot(list(P.post_hours), sched_state=sched_file)
        act = {"ts": ts, "action": "both_approved", "caption": caption,
               "photo": photo, "scheduled_for": slot.isoformat()}
        if dry_run:
            return [act]
        try:
            res = zoho_draft.schedule_post(
                caption, photo, P.business_name, when=slot, media_type="photo",
                dry_run=False, profile_dir=zoho_prof, sched_state=sched_file)
        except Exception as e:
            res = {"ok": False, "error": str(e)}
        if not res.get("ok"):
            return [act, {"ts": ts, "action": "schedule_error",
                          "error": res.get("error")}]
        h12 = slot.hour % 12 or 12
        said = (f":rocket: *Lucy has scheduled this to post* on {slot:%a %b} "
                f"{slot.day} at {h12}:{slot.minute:02d} "
                f"{'AM' if slot.hour < 12 else 'PM'}.")
        st["scheduled"] = True
    else:
        last = {}
        try:
            last = json.loads(sched_file.read_text())
        except Exception:
            pass
        if last.get("last_scheduled_date") == now.date().isoformat():
            return [{"ts": ts, "action": "waiting_for_tomorrow",
                     "note": "today's one post already went out"}]
        if not (min(P.post_hours) <= now.hour <= max(P.post_hours)):
            return [{"ts": ts, "action": "waiting_for_window",
                     "note": f"{now:%H:%M} office time is outside "
                             f"{min(P.post_hours)}:00-{max(P.post_hours)}:59"}]
        act = {"ts": ts, "action": "post_now", "caption": caption, "photo": photo}
        if dry_run:
            return [act]
        try:
            res = zoho_draft.post_now(caption, photo, P.business_name,
                                      media_type="photo", profile_dir=zoho_prof)
        except Exception as e:
            res = {"ok": False, "error": str(e)}
        if not res.get("ok"):
            return [act, {"ts": ts, "action": "schedule_error",
                          "error": res.get("error")}]
        zoho_draft._record_slot(now, sched_file)
        said = ":rocket: *Lucy posted this* to your connected pages."
        st["published"] = True
    cl.chat_postMessage(channel=P.slack_channel, thread_ts=ts, text=said)
    try:
        cl.reactions_add(channel=P.slack_channel, name=SOCIAL_POSTED_EMOJI,
                         timestamp=ts)
    except Exception:
        pass
    st["posted"] = True
    return [act]


def _office_queue(P, ts: str, st: dict, caption: str, dry_run: bool,
                  sched_file: Path, now) -> list[dict]:
    """Hand the approved post to the office's OWN computer (relay job).

    Same one-a-day, inside-the-window rule as everywhere else, judged on the
    office's clock. The 🚀 / "posted" note comes later, when the computer
    answers (online_presence.watch) -- queued is not posted."""
    last = {}
    try:
        last = json.loads(sched_file.read_text())
    except Exception:
        pass
    if last.get("last_scheduled_date") == now.date().isoformat():
        return [{"ts": ts, "action": "waiting_for_tomorrow",
                 "note": "today's one post already went out"}]
    if not (min(P.post_hours) <= now.hour <= max(P.post_hours)):
        return [{"ts": ts, "action": "waiting_for_window",
                 "note": f"{now:%H:%M} office time is outside "
                         f"{min(P.post_hours)}:00-{max(P.post_hours)}:59"}]
    act = {"ts": ts, "action": "queue_to_office", "caption": caption,
           "photo": st.get("photo_path"), "photos": _paths(st), "pages": list(P.pages)}
    if dry_run:
        return [act]
    from automations.brand_audit import zoho_draft
    from automations.online_presence import relay
    try:
        st["eco_job"] = relay.enqueue_post(P.key, caption,
                                           [Path(p) for p in _paths(st)],
                                           P.pages, live=True, thread_ts=ts)
    except Exception as e:
        return [act, {"ts": ts, "action": "schedule_error", "error": str(e)[:200]}]
    zoho_draft._record_slot(now, sched_file)     # today's one post is spoken for
    act["job_id"] = st["eco_job"]
    return [act]


# ---- the polled processor ---------------------------------------------------
def process_inbox(company_name: str = DEFAULT_COMPANY, *, dry_run: bool = True,
                  limit: int = 20, profile=None) -> list[dict]:
    """Walk recent submissions; return the actions taken/proposed. In dry_run
    nothing is written to Slack or posted — it just reports what it would do.

    `profile` = an ICD office (automations.online_presence.offices): its own
    room, approvers, learned style, Zoho login and one-a-day slot. None =
    Alphalete, exactly as before."""
    if profile is None:
        from automations.online_presence.offices import alphalete
        profile = alphalete()
    P = profile
    alpha = P.key == "alphalete"
    if not alpha:
        company_name = P.business_name
    chan, who = P.slack_channel, P.counted_approvers
    state_file, style_file = P.path("social_inbox.json"), P.style_file
    sched_file = P.path("zoho_schedule.json") if not alpha else None
    zoho_prof = None if alpha else P.zoho_profile
    photo_prefix = "social_" if alpha else f"social_{P.key}_"
    cl = _client()
    msgs = cl.conversations_history(channel=chan,
                                    limit=limit).get("messages", [])
    state = _load_state(state_file)
    # Captions we've already used (persisted across runs so we never repeat a
    # line even days apart). Newest first; we feed the recent slice as a
    # "do-not-reuse" list to every new caption.
    recent_captions = list(state.get("_recent_captions", []))
    seen_photos = _seed_hashes(state)
    # FORM ONLY from here on (online_presence.post_form): a photo dropped
    # straight into the channel gets one pointer to the 📸 New post button and
    # is never posted. Anything already under way finishes as before.
    from automations.online_presence import post_form
    since = state.setdefault("_form_only_since", f"{time.time():.6f}")
    actions = []

    for m in msgs:
        if m.get("subtype") == "channel_join":
            continue
        imgs = _image_files(m)
        if not imgs:
            continue
        # Lucy's / an app's own pictures (the Friday card, logo sheets) are not
        # a dropped photo: never answer them with the New post button (Megan
        # 2026-11-13: Jiraiya replied "tap New post" under the weekly card).
        if (m.get("bot_id") or m.get("app_id") or m.get("subtype") == "bot_message") \
                and not post_form.from_form(m):
            continue
        ts = m["ts"]
        if ts not in state and not post_form.from_form(m):
            if float(ts) > float(since):
                actions.append({"ts": ts, "action": "use_the_button"})
                if not dry_run:
                    post_form.point_to_button(chan, ts, cl)
                    state[ts] = {"posted": True, "redirected": True}
            continue
        st = state.setdefault(ts, {})
        if st.get("killed"):
            continue
        text = m.get("text", "")

        # 💀 from an approver TRUMPS everything — even an approval (✅+💀 = no),
        # even if it was already scheduled. Checked first, on active + scheduled
        # items, so one person's skull overrides the other's approval.
        if (not st.get("posted")) or st.get("scheduled"):
            krx = _thread_reactions(cl, ts, chan)
            if any(_reacted(krx.get(t), SOCIAL_KILL_EMOJI, who)
                   for t in (ts, st.get("photo_ts"), st.get("caption_ts")) if t):
                actions.append({"ts": ts, "action": "killed",
                                "was_scheduled": bool(st.get("scheduled"))})
                if not dry_run:
                    if st.get("scheduled"):
                        cl.chat_postMessage(
                            channel=chan, thread_ts=ts,
                            text=":skull: Got it — but heads up, this was already "
                                 "*scheduled in Zoho*. Please remove it from the "
                                 "scheduled queue (I can't auto-unschedule yet).")
                    else:
                        cl.chat_postMessage(
                            channel=chan, thread_ts=ts,
                            text=":skull: Got it — we won't post this one.")
                st["killed"] = True
                st["posted"] = True
                continue

        if st.get("posted"):
            continue

        # ONE MESSAGE = ONE POST, ALL ITS PHOTOS (Megan 2026-11-09: "we want to
        # be able to have multi photos on a post - but that means each photo
        # needs edited"). Every photo is edited, screened and checked for
        # repeats on its own; they're approved and posted together. Past
        # MAX_PHOTOS, say once that only the first ones go in.
        if len(imgs) > MAX_PHOTOS and not st.get("over_cap_told"):
            actions.append({"ts": ts, "action": "over_photo_cap", "photos": len(imgs)})
            if not dry_run:
                cl.chat_postMessage(
                    channel=chan, thread_ts=ts,
                    text=f":information_source: One post holds up to {MAX_PHOTOS} photos, "
                         f"so I'll use the first {MAX_PHOTOS} of these {len(imgs)}. Send "
                         "the rest as their own post, with a line about them.")
                st["over_cap_told"] = True
        imgs = imgs[:MAX_PHOTOS]

        # SAME PHOTO TWICE: an approver already answered the hold?
        if st.get("dup_ts") and not st.get("dup_ok"):
            drx = _thread_reactions(cl, ts, chan).get(st["dup_ts"])
            if _reacted(drx, SOCIAL_APPROVE_EMOJI, who):
                st["dup_ok"] = True
            elif _reacted(drx, SOCIAL_REJECT_EMOJI, who):
                actions.append({"ts": ts, "action": "duplicate_dropped"})
                if not dry_run:
                    cl.chat_postMessage(channel=chan, thread_ts=ts,
                                        text=":ok_hand: Skipped, it won't post twice.")
                    st["posted"] = True
                continue
            else:
                actions.append({"ts": ts, "action": "awaiting_duplicate_review"})
                continue

        # PROPOSE: post the edited PHOTO right away (no context needed); the
        # CAPTION follows once we have enough context. Approved separately.
        if not (st.get("photo_ts") and st.get("caption")):
            # the edited image — process fresh if the photo isn't posted yet,
            # else reuse the version already saved (caption-only passes)
            quality = None
            if st.get("photo_ts") and _paths(st) and \
                    all(Path(p).exists() for p in _paths(st)):
                edited = [Path(p).read_bytes() for p in _paths(st)]
                raws = None
            else:
                try:
                    raws = [_download(f["url_private"]) for f in imgs]
                    zoom = style.photo_default_zoom(style_file)
                    edited = [photo_edit.process_bytes(r, zoom=zoom) for r in raws]
                    quality = _merge_quality([photo_edit.quality_report(r) for r in raws])
                except Exception as e:
                    actions.append({"ts": ts, "action": "caption_error",
                                    "error": str(e)})
                    continue
                if not st.get("dup_ok"):
                    twins = []
                    for i, im in enumerate(edited):
                        key = ts if i == 0 else f"{ts}#{i}"
                        h = photo_edit.dhash(im)
                        twin = twin_of(seen_photos, h, key)
                        if twin:
                            twins.append((i, twin))
                        if not any(x["ts"] == key for x in seen_photos):
                            seen_photos.append({"ts": key, "h": f"{h:016x}"})
                    if twins:
                        actions.append({"ts": ts, "action": "duplicate_held",
                                        "matches": [t["ts"] for _, t in twins]})
                        if not dry_run:
                            r0 = cl.chat_postMessage(
                                channel=chan, thread_ts=ts,
                                text=_dup_text(cl, chan, ts, twins, len(edited)))
                            st["dup_ts"] = r0.get("ts")
                        continue
                    st["dup_ok"] = True
            img = edited[0]          # the caption reads the first photo

            # 1) BRAND-SAFETY SCREEN — gate everything. Flag (don't auto-block)
            #    alcohol/smoking/drugs/profanity/gang signs/weapons/cash/blur or
            #    anything thuggish-unprofessional → approvers ✅ post / ❌ deny.
            if not st.get("screen_ok"):
                if st.get("flagged_ts"):
                    frx = _thread_reactions(cl, ts, chan).get(st["flagged_ts"])
                    if _reacted(frx, SOCIAL_APPROVE_EMOJI, who):
                        st["screen_ok"] = True
                    elif _reacted(frx, SOCIAL_REJECT_EMOJI, who):
                        actions.append({"ts": ts, "action": "photo_denied"})
                        if not dry_run:
                            cl.chat_postMessage(
                                channel=chan, thread_ts=ts,
                                text=":no_entry: Denied — we won't post this one. "
                                     "Thanks for sending though!")
                            st["posted"] = True
                        continue
                    else:
                        actions.append({"ts": ts, "action": "awaiting_screen_review"})
                        continue
                else:
                    issues = []
                    for i, im in enumerate(edited):
                        mine = list(screen_photo(im, company_name))
                        if raws is not None and photo_edit.is_too_blurry(raws[i]):
                            mine.append("too blurry to meet our posting standards "
                                        "(couldn't sharpen it enough)")
                        tag = f"photo {i + 1}: " if len(edited) > 1 else ""
                        issues += [tag + x for x in mine]
                    if issues:
                        actions.append({"ts": ts, "action": "photo_flagged",
                                        "issues": issues})
                        if not dry_run:
                            r0 = cl.chat_postMessage(
                                channel=chan, thread_ts=ts,
                                text=":warning: *Flagging for review* — heads up, "
                                     "this looks like it has: " + "; ".join(issues)
                                     + ".\n*Approvers: react :white_check_mark: to "
                                     "post it anyway, :x: to deny.*")
                            st["flagged_ts"] = r0.get("ts")
                        continue
                    st["screen_ok"] = True

            # 2) post the EDITED PHOTO for approval — NO context needed
            if not st.get("photo_ts"):
                paths = _save_edits(photo_prefix, ts, edited)
                many = len(paths) > 1
                actions.append({"ts": ts, "action": "propose_photo",
                                "photo": str(paths[0]), "photos": [str(p) for p in paths],
                                "quality": quality})
                if not dry_run:
                    warn = ""
                    if quality and quality.get("warnings"):
                        warn = (":warning: *Photo quality* — "
                                + " ".join(quality["warnings"]) + "\n\n")
                    what = (f"*{len(paths)} edited photos, one post*" if many
                            else "*Edited photo*")
                    cl.files_upload_v2(
                        channel=chan, thread_ts=ts,
                        file_uploads=[{"file": str(p), "title": f"Edited photo {i + 1}"
                                       if many else "Edited photo — IG ready"}
                                      for i, p in enumerate(paths)],
                        initial_comment=f"{warn}:frame_with_picture: {what} "
                        "(auto-enhanced + cropped) — react "
                        f":white_check_mark: to approve the {'PHOTOS' if many else 'PHOTO'}, "
                        ":x: to ask for a different edit / upload your own.")
                    st["photo_ts"] = _newest_file_reply_ts(cl, ts, chan)
                    st["photo_paths"] = [str(p) for p in paths]
                    st["photo_path"] = str(paths[0])

            # 3) CAPTION — needs context; ask the rep / wait, then post
            if not st.get("caption"):
                rep_ctx = _rep_context(cl, ts, chan, who)
                full_context = (text + ("\n" + rep_ctx if rep_ctx else "")).strip()
                if not st.get("context_resolved"):
                    if st.get("asked_context_ts"):
                        if not _rep_answered_after(cl, ts, st["asked_context_ts"],
                                                   chan, who):
                            actions.append({"ts": ts, "action": "awaiting_context"})
                            continue
                        st["context_resolved"] = True
                    else:
                        questions = needs_more_context(img, full_context,
                                                       company_name)
                        if questions:
                            msg = (":wave: A couple quick Qs so I caption this "
                                   "right:\n" + "\n".join(f"• {q}" for q in questions))
                            actions.append({"ts": ts, "action": "ask_context",
                                            "message": msg})
                            if not dry_run:
                                r0 = cl.chat_postMessage(
                                    channel=chan,
                                    thread_ts=ts, text=msg)
                                st["asked_context_ts"] = r0.get("ts")
                            continue
                        st["context_resolved"] = True
                try:
                    cap = caption_for(img, full_context, company_name,
                                      avoid=recent_captions[:25],
                                      style_path=style_file)
                except Exception as e:
                    actions.append({"ts": ts, "action": "caption_error",
                                    "error": str(e)})
                    continue
                recent_captions.insert(0, cap)
                actions.append({"ts": ts, "action": "propose_caption",
                                "caption": cap})
                if not dry_run:
                    r = cl.chat_postMessage(
                        channel=chan, thread_ts=ts,
                        text=":sparkles: *Proposed caption* — react "
                             ":white_check_mark: to approve the CAPTION, :x: for "
                             f"a different one:\n\n{cap}")
                    st["caption"] = cap
                    st["caption_ts"] = r.get("ts")
            continue

        # 3) collect reactions on the caption and the photo (judged separately)
        thread_rx = _thread_reactions(cl, ts, chan)
        cap_reactions = thread_rx.get(st.get("caption_ts"))
        photo_reactions = thread_rx.get(st.get("photo_ts"))
        caption_ok = _reacted(cap_reactions, SOCIAL_APPROVE_EMOJI, who)
        photo_ok = _reacted(photo_reactions, SOCIAL_APPROVE_EMOJI, who)
        cur = st.get("caption")

        # caption ❌ -> regenerate a fresh caption (approval wins over reject)
        rejected = st.setdefault("rejected", [])
        if (not caption_ok and _reacted(cap_reactions, SOCIAL_REJECT_EMOJI, who)
                and cur and cur not in rejected):
            rejected.append(cur)
            fb = _human_reply_after(cl, ts, st.get("caption_ts") or ts, chan)
            if fb and fb.get("text"):
                style.add_caption_feedback(fb["text"], style_file)   # Lucy learns from it
            try:
                raw = _download(imgs[0]["url_private"])
                newcap = caption_for(photo_edit.process_bytes(raw), text,
                                     company_name,
                                     avoid=(rejected + recent_captions)[:25],
                                     feedback=(fb.get("text") if fb else ""),
                                     style_path=style_file)
            except Exception as e:
                actions.append({"ts": ts, "action": "caption_error", "error": str(e)})
                continue
            recent_captions.insert(0, newcap)
            actions.append({"ts": ts, "action": "repropose_caption",
                            "caption": newcap, "rejected": cur})
            if not dry_run:
                r = cl.chat_postMessage(
                    channel=chan, thread_ts=ts,
                    text=":arrows_counterclockwise: Got it — a different take. "
                         "React :white_check_mark: to approve the CAPTION, :x: "
                         f"for another:\n\n{newcap}")
                st["caption"] = newcap
                st["caption_ts"] = r.get("ts")
            continue

        # photo ❌ -> ask WHY, then skip (don't want it) or fix (how it looks)
        photo_rejected = (not photo_ok
                          and _reacted(photo_reactions, SOCIAL_REJECT_EMOJI, who))
        if photo_rejected and not st.get("photo_dismissed"):
            # use feedback already in the thread (after the photo was proposed);
            # only ask "what's off?" if they haven't said anything yet
            reply = _human_reply_after(cl, ts, st.get("photo_ts") or ts, chan)
            if not reply:
                if not st.get("photo_why_ts"):
                    actions.append({"ts": ts, "action": "ask_photo_reason"})
                    if not dry_run:
                        q = cl.chat_postMessage(
                            channel=chan, thread_ts=ts,
                            text=":frame_with_picture: Got a :x: on the photo — "
                                 "what's off? If you just don't want *this photo* "
                                 "posted, tell me and I'll skip it. If it's *how "
                                 "it looks* (too dark/bright, dull, crop, zoom, "
                                 "color), say so and I'll fix it and re-post.")
                        st["photo_why_ts"] = q.get("ts")
                else:
                    actions.append({"ts": ts, "action": "awaiting_photo_reason"})
                continue
            interp = _interpret_photo_feedback(reply.get("text", ""))
            if interp.get("intent") == "fix":   # Lucy learns the photo preference
                style.add_photo_feedback(reply.get("text", ""),
                                         zoom=float(interp.get("zoom") or 1.0),
                                         path=style_file)
            if interp.get("intent") == "skip":
                actions.append({"ts": ts, "action": "photo_skipped"})
                if not dry_run:
                    cl.chat_postMessage(
                        channel=chan, thread_ts=ts,
                        text=":ok_hand: Got it — skipping this one. Send the next "
                             "photo whenever.")
                    st["photo_dismissed"] = True
                    st["posted"] = True
                continue
            # fix: re-edit per their feedback (every photo the same way) and
            # re-post for approval
            try:
                asp = interp.get("aspect") or "keep"
                opts = {"brightness": interp.get("brightness", 1.0),
                        "contrast": interp.get("contrast", 1.0),
                        "color": interp.get("saturation", 1.0)}
                newimgs = [photo_edit.process_bytes(
                    _download(f["url_private"]), aspect=("auto" if asp == "keep" else asp),
                    adjust_opts=opts, zoom=float(interp.get("zoom") or 1.0)) for f in imgs]
            except Exception as e:
                actions.append({"ts": ts, "action": "caption_error", "error": str(e)})
                continue
            new_paths = _save_edits(photo_prefix, ts, newimgs)
            actions.append({"ts": ts, "action": "photo_reedited",
                            "photo": str(new_paths[0]),
                            "photos": [str(p) for p in new_paths]})
            if not dry_run:
                note = interp.get("note") or "Updated the edit."
                many = len(new_paths) > 1
                cl.files_upload_v2(
                    channel=chan, thread_ts=ts,
                    file_uploads=[{"file": str(p), "title": f"Edited photo {i + 1} (v2)"
                                   if many else "Edited photo (v2)"}
                                  for i, p in enumerate(new_paths)],
                    initial_comment=f":frame_with_picture: {note} React "
                    f":white_check_mark: to approve the {'PHOTOS' if many else 'PHOTO'}, "
                    ":x: if it still needs work.")
                st["photo_ts"] = _newest_file_reply_ts(cl, ts, chan)
                st["photo_paths"] = [str(p) for p in new_paths]
                st["photo_path"] = str(new_paths[0])
                st["photo_why_ts"] = None   # next ❌ asks why again
            continue

        # BOTH approved -> SCHEDULE into the next daily slot (one post/day).
        # Zoho is only touched on a live (non-dry-run) pass; channel exclusion
        # (Raf's personal LinkedIn) is enforced inside schedule_post.
        if caption_ok and photo_ok and not alpha:
            actions.extend(_office_publish(P, cl, ts, st, cur, dry_run,
                                           sched_file, zoho_prof))
        elif caption_ok and photo_ok:
            from automations.brand_audit import zoho_draft, best_time
            hours, _src = best_time.best_good_hours(company_name)
            slot = zoho_draft.next_daily_slot(hours)
            actions.append({"ts": ts, "action": "both_approved",
                            "caption": cur, "photo": st.get("photo_path"),
                            "scheduled_for": slot.isoformat()})
            if not dry_run and not st.get("scheduled"):
                try:
                    res = zoho_draft.schedule_post(
                        cur, _paths(st), company_name,
                        when=slot, media_type="photo", dry_run=False)
                except Exception as e:
                    res = {"ok": False, "error": str(e)}
                if res.get("ok"):
                    h12 = slot.hour % 12 or 12
                    when_txt = (f"{slot:%a %b} {slot.day} at {h12}:"
                                f"{slot.minute:02d} {'AM' if slot.hour < 12 else 'PM'}")
                    cl.chat_postMessage(
                        channel=chan, thread_ts=ts,
                        text=f":rocket: *Lucy has scheduled this to post* on "
                             f"{when_txt} (Facebook, X, LinkedIn company page, "
                             "Instagram, Google).")
                    # mark the ORIGINAL submitted photo as handled/posted
                    try:
                        cl.reactions_add(channel=chan,
                                         name=SOCIAL_POSTED_EMOJI, timestamp=ts)
                    except Exception:
                        pass
                    st["scheduled"] = True
                    st["posted"] = True
                else:
                    # INTERNAL ONLY — never post technical errors to the team's
                    # thread. Logged in the action list for us; retried next run.
                    actions.append({"ts": ts, "action": "schedule_error",
                                    "error": res.get("error")})
        else:
            actions.append({"ts": ts, "action": "awaiting_approval",
                            "caption_ok": caption_ok, "photo_ok": photo_ok})

    if not dry_run:
        state["_recent_captions"] = recent_captions[:50]   # cap history
        state[_HASHES] = seen_photos[-KEEP_HASHES:]
        _save_state(state, state_file)
    return actions


def main(argv=None) -> int:
    import argparse, sys
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="brand_audit.social_inbox")
    p.add_argument("--company", default=DEFAULT_COMPANY)
    p.add_argument("--dry-run", action="store_true",
                   help="report actions without writing to Slack or posting")
    p.add_argument("--force", action="store_true",
                   help="bypass the already-running lock (only if a stale lock "
                        "is wrongly blocking a run)")
    args = p.parse_args(argv)
    if not args.force and not acquire_lock():
        print("another social_inbox run is already in progress — skipping "
              "(pass --force to override)")
        print("=== done ===")
        return 0
    try:
        for a in process_inbox(args.company, dry_run=args.dry_run):
            print(a.get("action"), "·", a.get("caption") or a.get("message") or a.get("error") or "")
    finally:
        if not args.force:
            release_lock()
    print("=== done ===")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
