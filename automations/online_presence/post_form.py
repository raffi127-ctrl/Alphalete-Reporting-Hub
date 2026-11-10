"""The "📸 New post" button pinned in each office's LucyECO Social channel.

Megan 2026-11-09: "is there a way on slack where we can really regulate how a
photo is posted? ... they give us the image(s) for that post - then we ask
who/what/when/where/why ... and then they submit?" -- and NOT a slash command:
"I want it just in their LucyECOSocial channel".

    tap 📸 New post  ->  a form: photos (1-10, all ONE post), who's in it,
    what's happening, where, when, anything else  ->  Submit

On Submit the photos land in the channel as ONE message with the answers
written under them. From there it's the normal inbox (social_inbox): every
photo edited, screened, checked for repeats, caption from the answers, ✅.
Because who/what are required, Lucy rarely has to come back with questions.

Rides the always-on Jiraiya listener (due_diligence/bot.py) -- its button and
form route there, so the pinned message is posted by Jiraiya. Dropping photos
straight into the channel still works exactly as before.

    python -m automations.online_presence.post_form --pin <office_key>          # dry
    python -m automations.online_presence.post_form --pin <office_key> --live   # post + pin
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import tempfile
import threading
from pathlib import Path
from typing import Dict, List

JIRAIYA = "U0BL6DN0SN7"          # the bot that posts the form's photos (auth.test 2026-11-09)
NEW_POST_MARK = "New post from <@"
BUTTON = "lucyeco_new_post"
FORM = "lucyeco_post_form"
MAX_PHOTOS = 10
PIN_TEXT = ("*📸 Want something posted?* Tap the button, add your photo(s), and "
            "answer a few quick questions. Lucy edits every photo, writes the "
            "caption, and asks for your ✅ before anything goes up.")


# ---- what goes in Slack ------------------------------------------------------------
def from_form(msg: Dict) -> bool:
    """Did this channel message come from the New post form?"""
    return msg.get("user") == JIRAIYA and NEW_POST_MARK in (msg.get("text") or "")


def pin_blocks() -> List[Dict]:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": PIN_TEXT}},
            {"type": "actions", "elements": [{
                "type": "button", "action_id": BUTTON, "style": "primary",
                "text": {"type": "plain_text", "text": "📸 New post", "emoji": True}}]}]


def _text(block_id: str, label: str, hint: str = "", optional: bool = False,
          multiline: bool = False) -> Dict:
    el = {"type": "plain_text_input", "action_id": "v", "multiline": multiline}
    if hint:
        el["placeholder"] = {"type": "plain_text", "text": hint}
    return {"type": "input", "block_id": block_id, "optional": optional,
            "label": {"type": "plain_text", "text": label}, "element": el}


def form(channel: str, today: dt.date | None = None) -> Dict:
    """One question per box, 7-year-old simple. Photos, who and what are required."""
    today = today or dt.date.today()
    return {
        "type": "modal", "callback_id": FORM, "private_metadata": channel,
        "title": {"type": "plain_text", "text": "New post"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "input", "block_id": "photos",
             "label": {"type": "plain_text", "text": "Photos for this post"},
             "hint": {"type": "plain_text",
                      "text": f"Up to {MAX_PHOTOS}. They all go in ONE post. "
                              "For separate posts, tap New post again."},
             "element": {"type": "file_input", "action_id": "v", "max_files": MAX_PHOTOS,
                         "filetypes": ["jpg", "jpeg", "png", "heic", "webp"]}},
            _text("who", "Who's in it?", "Sarah, Mike and the whole Dallas team"),
            _text("what", "What's happening?", "Sarah's first sale!", multiline=True),
            _text("where", "Where?", "Dallas office, out in Frisco...", optional=True),
            {"type": "input", "block_id": "when", "optional": True,
             "label": {"type": "plain_text", "text": "When?"},
             "element": {"type": "datepicker", "action_id": "v",
                         "initial_date": today.isoformat()}},
            _text("extra", "Anything else to mention?", "optional", optional=True,
                  multiline=True),
        ]}


def answers(view: Dict) -> Dict:
    vals = (view.get("state") or {}).get("values") or {}

    def v(bid):
        a = (vals.get(bid) or {}).get("v") or {}
        return (a.get("value") or a.get("selected_date") or "").strip()
    files = ((vals.get("photos") or {}).get("v") or {}).get("files") or []
    return {"files": files, "who": v("who"), "what": v("what"), "where": v("where"),
            "when": v("when"), "extra": v("extra")}


def problems(a: Dict) -> Dict[str, str]:
    """Slack shows these under the box (the form stays open)."""
    errs = {}
    pics = [f for f in a["files"] if str(f.get("mimetype", "")).startswith("image/")]
    if not pics:
        errs["photos"] = "Add at least one photo."
    elif len(pics) < len(a["files"]):
        errs["photos"] = "Photos only, please (no videos or documents)."
    if not a["who"]:
        errs["who"] = "Tell Lucy who's in it."
    if not a["what"]:
        errs["what"] = "Tell Lucy what's happening."
    return errs


def _nice_date(iso: str) -> str:
    try:
        d = dt.date.fromisoformat(iso)
    except Exception:
        return iso
    return "today" if d == dt.date.today() else f"{d:%a %b} {d.day}"


def message(a: Dict, user: str) -> str:
    """The text under the photos -- what the inbox captions from."""
    n = len(a["files"])
    lines = [f"📸 *New post from <@{user}>*" + (f" · {n} photos, one post" if n > 1 else ""),
             f"*Who:* {a['who']}", f"*What:* {a['what']}"]
    if a["where"]:
        lines.append(f"*Where:* {a['where']}")
    if a["when"]:
        lines.append(f"*When:* {_nice_date(a['when'])}")
    if a["extra"]:
        lines.append(f"*Also:* {a['extra']}")
    return "\n".join(lines)


REDIRECT_TEXT = ("📸 To get this posted, tap *New post* below (it's also pinned at the "
                 "top of this channel), add the photo(s) and answer the quick questions. "
                 "Lucy doesn't post photos dropped straight in here.")


def point_to_button(chan: str, thread_ts: str, fallback_client) -> None:
    """Answer a photo dropped straight in: the button itself, right in the
    thread (posted by Jiraiya so the tap reaches the form). Plain words from
    Lucy if Jiraiya can't post there."""
    try:
        from automations.due_diligence.watch import _client as jiraiya
        blocks = pin_blocks()
        blocks[0]["text"]["text"] = REDIRECT_TEXT
        jiraiya().chat_postMessage(channel=chan, thread_ts=thread_ts,
                                   text=REDIRECT_TEXT, blocks=blocks)
    except Exception:
        fallback_client.chat_postMessage(channel=chan, thread_ts=thread_ts,
                                         text=REDIRECT_TEXT.replace(" below", ""))


# ---- the Jiraiya listener hooks (asked BEFORE acking, like /aca) ---------------------
def wants(req) -> bool:
    p = req.payload or {}
    if req.type != "interactive":
        return False
    if p.get("type") == "block_actions":
        return any(a.get("action_id") == BUTTON for a in p.get("actions") or [])
    if p.get("type") == "view_submission":
        return (p.get("view") or {}).get("callback_id") == FORM
    return False


def ack(req) -> Dict | None:
    """The ack payload: field errors keep the form open; None closes it."""
    p = req.payload or {}
    if p.get("type") == "view_submission":
        errs = problems(answers(p["view"]))
        if errs:
            return {"response_action": "errors", "errors": errs}
    return None


def handle(client, req) -> None:
    p = req.payload or {}
    web = client.web_client
    if p.get("type") == "block_actions":
        chan = (p.get("channel") or {}).get("id") or (p.get("container") or {}).get("channel_id", "")
        web.views_open(trigger_id=p["trigger_id"], view=form(chan))
        return
    a = answers(p["view"])
    if problems(a):
        return                                    # the form stayed open with the errors
    chan, user = p["view"].get("private_metadata") or "", p["user"]["id"]
    threading.Thread(target=deliver, args=(web, chan, user, a), daemon=True).start()


def _download(web, f: Dict) -> bytes:
    import requests
    url = f.get("url_private_download") or f.get("url_private")
    if not url:
        url = web.files_info(file=f["id"])["file"]["url_private_download"]
    r = requests.get(url, headers={"Authorization": f"Bearer {web.token}"}, timeout=60)
    r.raise_for_status()
    return r.content


def deliver(web, chan: str, user: str, a: Dict) -> None:
    """Photos + answers into the channel as ONE message (the inbox picks it up)."""
    try:
        with tempfile.TemporaryDirectory(prefix="lucy-newpost-") as tmp:
            ups = []
            for i, f in enumerate(a["files"], 1):
                ext = (f.get("filetype") or "jpg").lower()
                path = Path(tmp) / f"photo{i:02d}.{ext}"
                path.write_bytes(_download(web, f))
                ups.append({"file": str(path), "title": f"Photo {i}"})
            web.files_upload_v2(channel=chan, file_uploads=ups,
                                initial_comment=message(a, user))
    except Exception as e:                        # noqa: BLE001 -- tell them, never vanish
        print(f"[newpost] FAILED {type(e).__name__}: {e}", flush=True)
        try:
            web.chat_postEphemeral(channel=chan, user=user,
                                   text=":x: Your post didn't go through. Please tap "
                                        "📸 New post and try again, or just drop the "
                                        "photos here with a line about them.")
        except Exception:
            pass


# ---- putting the button in an office's channel --------------------------------------
def pin(P, *, live: bool) -> Dict:
    """Jiraiya joins the office's channel (Lucy invites it), posts the button,
    pins it. Never twice: an existing pinned button is left alone."""
    from automations.brand_audit.social_inbox import _client as lucy
    from automations.due_diligence.watch import _client as jiraiya
    chan = P.slack_channel
    if not chan:
        return {"action": "no_channel"}
    bot = jiraiya()
    bot_user = bot.auth_test()["user_id"]
    if not live:
        return {"action": "would_pin", "channel": chan, "bot": bot_user}
    try:
        lucy().conversations_invite(channel=chan, users=bot_user)
    except Exception as e:                        # already_in_channel is fine
        if "already_in_channel" not in str(e):
            raise
    try:
        for it in lucy().pins_list(channel=chan).get("items") or []:
            if any(el.get("action_id") == BUTTON
                   for b in (it.get("message") or {}).get("blocks") or []
                   for el in b.get("elements") or []):
                return {"action": "already_pinned", "channel": chan}
    except Exception:
        pass
    r = bot.chat_postMessage(channel=chan, text="📸 New post", blocks=pin_blocks())
    # Jiraiya has no pins:write (checked 2026-11-09); Lucy's own login may.
    # If neither can, the button is still there -- pin it by hand once.
    for who in (bot, lucy()):
        try:
            who.pins_add(channel=chan, timestamp=r["ts"])
            return {"action": "pinned", "channel": chan, "ts": r["ts"]}
        except Exception as e:                    # missing_scope / not_allowed
            err = str(e)[:120]
    return {"action": "posted_pin_by_hand", "channel": chan, "ts": r["ts"], "error": err}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pin", required=True, metavar="OFFICE_KEY")
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args(argv)
    from automations.online_presence import offices
    rows = offices.load()
    P = offices.alphalete() if args.pin == "alphalete" else rows.get(args.pin)
    if P is None:
        print(f"no office '{args.pin}'. Known: {', '.join(sorted(rows))}")
        return 2
    print(json.dumps(pin(P, live=args.live)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
