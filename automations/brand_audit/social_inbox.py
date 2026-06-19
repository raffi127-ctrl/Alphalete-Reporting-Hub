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

from automations.brand_audit import credentials
from automations.brand_audit.config import (
    SOCIAL_INBOX_CHANNEL_ID, SOCIAL_APPROVERS, SOCIAL_APPROVE_EMOJI,
    DEFAULT_COMPANY,
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


def _approved(msg: dict, caption_reactions: list[dict] | None) -> bool:
    """True if an authorized user reacted with an approval emoji on the photo
    (or the caption reply)."""
    def ok(reactions):
        for rx in (reactions or []):
            if rx.get("name") not in SOCIAL_APPROVE_EMOJI:
                continue
            users = rx.get("users") or []
            if not SOCIAL_APPROVERS:      # no allow-list set yet → any approver
                return True
            if any(u in SOCIAL_APPROVERS for u in users):
                return True
        return False
    return ok(msg.get("reactions")) or ok(caption_reactions)


# ---- caption generation -----------------------------------------------------
def caption_for(image_bytes: bytes, context: str, company_name: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    system = (
        f"You write Instagram captions for {company_name}, a door-to-door sales "
        "company. Brand voice = high-energy entrepreneurial hustle, in the spirit "
        "of Alex Hormozi, Gary Vaynerchuk, Grant Cardone, and accounts like "
        "@newbern.excel. Audience: ambitious 20-25 year-olds deciding whether to "
        "build a career here.\n"
        "VOICE: punchy, confident, direct. Short declarative lines that hit. "
        "Motivational but earned — tie it to the actual win in the photo. Speak to "
        "the reader's ambition (winning, leveling up, betting on yourself, "
        "outworking everyone).\n"
        "HARD RULES:\n"
        "- SHORT. 1-3 short lines max. Never a paragraph.\n"
        "- NO hashtag stacks. At most ONE hashtag, usually none.\n"
        "- Minimal emoji — one max, only if it truly lands. No emoji vomit.\n"
        "- No corporate-speak. Ban clichés: 'this is just the beginning', 'the "
        "grind', 'next man up', 'sky's the limit', 'leveled up'.\n"
        "- Sound like a sharp human who posts constantly — NOT a brand bot, NOT "
        "AI. Vary the structure; don't follow a template.\n"
        "- Use the real names/levels/context. Never invent facts."
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=400, system=system,
        output_config={"format": {"type": "json_schema", "schema": _CAPTION_SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
             "media_type": "image/jpeg",
             "data": base64.standard_b64encode(image_bytes).decode()}},
            {"type": "text", "text": f"Context from the submitter:\n{context}\n\n"
                                     "Write the caption."},
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

        # 2) caption (once) — use the latest image on the message
        if not st.get("caption"):
            try:
                img = _download(imgs[-1]["url_private"])
                cap = caption_for(img, text, company_name)
            except Exception as e:
                actions.append({"ts": ts, "action": "caption_error", "error": str(e)})
                continue
            actions.append({"ts": ts, "action": "propose_caption", "caption": cap})
            if not dry_run:
                r = cl.chat_postMessage(
                    channel=SOCIAL_INBOX_CHANNEL_ID, thread_ts=ts,
                    text=f":sparkles: *Proposed caption* — react :white_check_mark: "
                         f"to approve (or reply with edits / a new photo):\n\n{cap}")
                st["caption"] = cap
                st["caption_ts"] = r.get("ts")
            continue

        # 3) approved? -> post (stub)
        cap_reactions = None
        if st.get("caption_ts"):
            try:
                rr = cl.reactions_get(channel=SOCIAL_INBOX_CHANNEL_ID,
                                      timestamp=st["caption_ts"])
                cap_reactions = (rr.get("message") or {}).get("reactions")
            except Exception:
                pass
        if _approved(m, cap_reactions):
            actions.append({"ts": ts, "action": "post", "caption": st.get("caption")})
            if not dry_run:
                # TODO: wire real posting (IG-native or aggregator) here.
                cl.chat_postMessage(channel=SOCIAL_INBOX_CHANNEL_ID, thread_ts=ts,
                                    text=":rocket: Approved — posting queued. "
                                         "(Posting destination not wired yet.)")
                st["posted"] = True
        else:
            actions.append({"ts": ts, "action": "awaiting_approval",
                            "caption": st.get("caption")})

    if not dry_run:
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
