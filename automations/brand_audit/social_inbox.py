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
from pathlib import Path

import requests

from automations.brand_audit import credentials, photo_edit
from automations.brand_audit.config import (
    SOCIAL_INBOX_CHANNEL_ID, SOCIAL_APPROVERS, SOCIAL_APPROVE_EMOJI,
    SOCIAL_REJECT_EMOJI, DEFAULT_COMPANY, OUTPUT_DIR,
)

_STATE = Path.home() / ".config" / "brand-audit" / "social_inbox.json"
MODEL = "claude-opus-4-8"

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


def _load_state() -> dict:
    try:
        return json.loads(_STATE.read_text())
    except Exception:
        return {}


def _save_state(s: dict) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(s, indent=2))


def _image_files(msg: dict) -> list[dict]:
    return [f for f in (msg.get("files") or [])
            if str(f.get("mimetype", "")).startswith("image/")]


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


def _reacted(reactions: list[dict] | None, emoji: tuple) -> bool:
    """True if an authorized approver reacted with one of `emoji`."""
    for rx in (reactions or []):
        if rx.get("name") not in emoji:
            continue
        users = rx.get("users") or []
        if not SOCIAL_APPROVERS:          # no allow-list set yet → anyone counts
            return True
        if any(u in SOCIAL_APPROVERS for u in users):
            return True
    return False


def _get_reactions(cl, ts: str | None) -> list[dict] | None:
    """Reactions on a specific message (or None)."""
    if not ts:
        return None
    try:
        rr = cl.reactions_get(channel=SOCIAL_INBOX_CHANNEL_ID, timestamp=ts)
        return (rr.get("message") or {}).get("reactions")
    except Exception:
        return None


def _human_reply_after(cl, parent_ts: str, after_ts: str) -> dict | None:
    """Latest plain-text reply in the thread, posted after `after_ts`, that is a
    human answer (not one of our bot prompts — those start with an emoji
    shortcode). Used to read why a photo was rejected."""
    try:
        reps = cl.conversations_replies(channel=SOCIAL_INBOX_CHANNEL_ID,
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


_PHOTO_FEEDBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["skip", "fix"]},
        "aspect": {"type": "string",
                   "enum": ["keep", "4:5", "1:1", "1.91:1"]},
        "brightness": {"type": "number"},
        "contrast": {"type": "number"},
        "saturation": {"type": "number"},
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
            "out, bad crop, color/tint), return intent='fix' with multipliers "
            "(1.0 = no change; brightness/contrast 0.7-1.4, saturation 0.6-1.4) "
            "and an aspect ('keep' unless they mention the crop). Add a short, "
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
                "note": "Brightened it up a touch — take another look."}


def _newest_file_reply_ts(cl, parent_ts: str) -> str | None:
    """ts of the most recent thread reply that carries a file (the photo we
    just uploaded), so its reactions can be tracked separately."""
    try:
        reps = cl.conversations_replies(channel=SOCIAL_INBOX_CHANNEL_ID,
                                        ts=parent_ts).get("messages", [])
        files = [r for r in reps if r.get("files") and r.get("ts") != parent_ts]
        return files[-1]["ts"] if files else None
    except Exception:
        return None


# ---- caption generation -----------------------------------------------------
def caption_for(image_bytes: bytes, context: str, company_name: str,
                avoid: list[str] | None = None) -> str:
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
        "- Sound like a real teammate — specific, warm, human. NOT generic, NOT "
        "corporate, NOT obviously AI. Ban dead corporate phrases ('thrilled to "
        "announce', 'this is just the beginning').\n"
        "- Vary every caption — don't reuse the same hook or closer across posts; "
        "if a line feels like a template you've used, rewrite it.\n"
        "- Use the real names/context. Never invent specific numbers, dates, "
        "timelines, or perks that aren't in the context.\n"
        "- NEVER put a person's internal level in parentheses after their name "
        "(no 'Vincent (LVL 3)'). Naming the promotion itself ('Level 2') is fine."
    )
    user_text = f"Context from the submitter:\n{context}\n\nWrite the caption."
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


# ---- the polled processor ---------------------------------------------------
def process_inbox(company_name: str = DEFAULT_COMPANY, *, dry_run: bool = True,
                  limit: int = 20) -> list[dict]:
    """Walk recent submissions; return the actions taken/proposed. In dry_run
    nothing is written to Slack or posted — it just reports what it would do."""
    cl = _client()
    msgs = cl.conversations_history(channel=SOCIAL_INBOX_CHANNEL_ID,
                                    limit=limit).get("messages", [])
    state = _load_state()
    # Captions we've already used (persisted across runs so we never repeat a
    # line even days apart). Newest first; we feed the recent slice as a
    # "do-not-reuse" list to every new caption.
    recent_captions = list(state.get("_recent_captions", []))
    actions = []

    for m in msgs:
        if m.get("subtype") == "channel_join":
            continue
        imgs = _image_files(m)
        if not imgs:
            continue
        ts = m["ts"]
        st = state.setdefault(ts, {})
        if st.get("posted"):
            continue
        text = m.get("text", "")

        # 1) no context -> ask for it (once)
        if not _has_context(text):
            if not st.get("asked_context"):
                actions.append({"ts": ts, "action": "ask_context",
                                "message": _CONTEXT_QUESTION})
                if not dry_run:
                    cl.chat_postMessage(channel=SOCIAL_INBOX_CHANNEL_ID,
                                        thread_ts=ts, text=_CONTEXT_QUESTION)
                    st["asked_context"] = True
            continue

        # 2) first pass: post the edited PHOTO and the CAPTION as TWO separate
        #    messages so each can be approved on its own (✅) or rejected (❌).
        if not st.get("caption"):
            try:
                raw = _download(imgs[-1]["url_private"])
                quality = photo_edit.quality_report(raw)   # flag bad sources
                img = photo_edit.process_bytes(raw)        # auto-enhance + IG crop
                cap = caption_for(img, text, company_name,
                                  avoid=recent_captions[:25])
            except Exception as e:
                actions.append({"ts": ts, "action": "caption_error", "error": str(e)})
                continue
            recent_captions.insert(0, cap)   # avoid repeats within this run too
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            photo_path = OUTPUT_DIR / f"social_{ts.replace('.', '')}_ig.jpg"
            photo_path.write_bytes(img)
            actions.append({"ts": ts, "action": "propose", "caption": cap,
                            "photo": str(photo_path), "quality": quality})
            if not dry_run:
                warn = ""
                if quality and quality.get("warnings"):
                    warn = (":warning: *Photo quality* — "
                            + " ".join(quality["warnings"]) + "\n\n")
                # the edited PHOTO — approved on its own
                cl.files_upload_v2(
                    channel=SOCIAL_INBOX_CHANNEL_ID, thread_ts=ts,
                    file=str(photo_path), title="Edited photo — IG ready",
                    initial_comment=f"{warn}:frame_with_picture: *Edited photo* "
                    "(auto-enhanced + cropped) — react :white_check_mark: to "
                    "approve the PHOTO, :x: to ask for a different edit / upload "
                    "your own.")
                st["photo_ts"] = _newest_file_reply_ts(cl, ts)
                st["photo_path"] = str(photo_path)
                # the CAPTION — approved on its own
                r = cl.chat_postMessage(
                    channel=SOCIAL_INBOX_CHANNEL_ID, thread_ts=ts,
                    text=":sparkles: *Proposed caption* — react "
                         ":white_check_mark: to approve the CAPTION, :x: for a "
                         f"different one:\n\n{cap}")
                st["caption"] = cap
                st["caption_ts"] = r.get("ts")
            continue

        # 3) collect reactions on the caption and the photo (judged separately)
        cap_reactions = _get_reactions(cl, st.get("caption_ts"))
        photo_reactions = _get_reactions(cl, st.get("photo_ts"))
        caption_ok = _reacted(cap_reactions, SOCIAL_APPROVE_EMOJI)
        photo_ok = _reacted(photo_reactions, SOCIAL_APPROVE_EMOJI)
        cur = st.get("caption")

        # caption ❌ -> regenerate a fresh caption (approval wins over reject)
        rejected = st.setdefault("rejected", [])
        if (not caption_ok and _reacted(cap_reactions, SOCIAL_REJECT_EMOJI)
                and cur and cur not in rejected):
            rejected.append(cur)
            try:
                raw = _download(imgs[-1]["url_private"])
                newcap = caption_for(photo_edit.process_bytes(raw), text,
                                     company_name,
                                     avoid=(rejected + recent_captions)[:25])
            except Exception as e:
                actions.append({"ts": ts, "action": "caption_error", "error": str(e)})
                continue
            recent_captions.insert(0, newcap)
            actions.append({"ts": ts, "action": "repropose_caption",
                            "caption": newcap, "rejected": cur})
            if not dry_run:
                r = cl.chat_postMessage(
                    channel=SOCIAL_INBOX_CHANNEL_ID, thread_ts=ts,
                    text=":arrows_counterclockwise: Got it — a different take. "
                         "React :white_check_mark: to approve the CAPTION, :x: "
                         f"for another:\n\n{newcap}")
                st["caption"] = newcap
                st["caption_ts"] = r.get("ts")
            continue

        # photo ❌ -> ask WHY, then skip (don't want it) or fix (how it looks)
        photo_rejected = (not photo_ok
                          and _reacted(photo_reactions, SOCIAL_REJECT_EMOJI))
        if photo_rejected and not st.get("photo_dismissed"):
            # A) ask why (once per reject cycle)
            if not st.get("photo_why_ts"):
                actions.append({"ts": ts, "action": "ask_photo_reason"})
                if not dry_run:
                    q = cl.chat_postMessage(
                        channel=SOCIAL_INBOX_CHANNEL_ID, thread_ts=ts,
                        text=":frame_with_picture: Got a :x: on the photo — "
                             "what's off? If you just don't want *this photo* "
                             "posted, tell me and I'll skip it. If it's *how it "
                             "looks* (too dark/bright, dull, crop, color), say so "
                             "and I'll fix it and re-post.")
                    st["photo_why_ts"] = q.get("ts")
                continue
            # B) read their answer
            reply = _human_reply_after(cl, ts, st.get("photo_why_ts"))
            if not reply:
                actions.append({"ts": ts, "action": "awaiting_photo_reason"})
                continue
            interp = _interpret_photo_feedback(reply.get("text", ""))
            if interp.get("intent") == "skip":
                actions.append({"ts": ts, "action": "photo_skipped"})
                if not dry_run:
                    cl.chat_postMessage(
                        channel=SOCIAL_INBOX_CHANNEL_ID, thread_ts=ts,
                        text=":ok_hand: Got it — skipping this one. Send the next "
                             "photo whenever.")
                    st["photo_dismissed"] = True
                    st["posted"] = True
                continue
            # fix: re-edit per their feedback and re-post for approval
            try:
                raw = _download(imgs[-1]["url_private"])
                asp = interp.get("aspect") or "keep"
                opts = {"brightness": interp.get("brightness", 1.0),
                        "contrast": interp.get("contrast", 1.0),
                        "color": interp.get("saturation", 1.0)}
                newimg = photo_edit.process_bytes(
                    raw, aspect=("auto" if asp == "keep" else asp),
                    adjust_opts=opts)
            except Exception as e:
                actions.append({"ts": ts, "action": "caption_error", "error": str(e)})
                continue
            new_path = OUTPUT_DIR / f"social_{ts.replace('.', '')}_ig.jpg"
            new_path.write_bytes(newimg)
            actions.append({"ts": ts, "action": "photo_reedited",
                            "photo": str(new_path)})
            if not dry_run:
                note = interp.get("note") or "Updated the edit."
                cl.files_upload_v2(
                    channel=SOCIAL_INBOX_CHANNEL_ID, thread_ts=ts,
                    file=str(new_path), title="Edited photo (v2)",
                    initial_comment=f":frame_with_picture: {note} React "
                    ":white_check_mark: to approve the PHOTO, :x: if it still "
                    "needs work.")
                st["photo_ts"] = _newest_file_reply_ts(cl, ts)
                st["photo_path"] = str(new_path)
                st["photo_why_ts"] = None   # next ❌ asks why again
            continue

        # BOTH approved -> draft in Zoho
        if caption_ok and photo_ok:
            actions.append({"ts": ts, "action": "both_approved",
                            "caption": cur, "photo": st.get("photo_path")})
            if not dry_run and not st.get("drafted"):
                try:
                    from automations.brand_audit import zoho_draft
                    zoho_draft.create_draft(cur, st.get("photo_path"),
                                            company_name)
                    cl.chat_postMessage(
                        channel=SOCIAL_INBOX_CHANNEL_ID, thread_ts=ts,
                        text=":rocket: Photo + caption approved — saved as a "
                             "*draft in Zoho* for you to publish.\n"
                             ":warning: Before publishing, check the channels — "
                             "leave *Rafael Hidalgo's personal LinkedIn* "
                             "unchecked (never post there).")
                    st["drafted"] = True
                    st["posted"] = True
                except Exception as e:
                    if not st.get("zoho_pending_notified"):
                        cl.chat_postMessage(
                            channel=SOCIAL_INBOX_CHANNEL_ID, thread_ts=ts,
                            text=":white_check_mark: Photo + caption both "
                                 "approved. The Zoho draft step is being wired — "
                                 "it'll draft automatically once ready.")
                        st["zoho_pending_notified"] = True
                    actions.append({"ts": ts, "action": "zoho_pending",
                                    "error": str(e)})
        else:
            actions.append({"ts": ts, "action": "awaiting_approval",
                            "caption_ok": caption_ok, "photo_ok": photo_ok})

    if not dry_run:
        state["_recent_captions"] = recent_captions[:50]   # cap history
        _save_state(state)
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
    args = p.parse_args(argv)
    for a in process_inbox(args.company, dry_run=args.dry_run):
        print(a.get("action"), "·", a.get("caption") or a.get("message") or a.get("error") or "")
    print("=== done ===")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
