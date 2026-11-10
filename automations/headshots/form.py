"""The "📸 Add headshot" button in each week's headshot thread.

Megan 2026-11-09: regulate how headshots come in, the way the LucyECO Social
"📸 New post" form does (automations/online_presence/post_form.py). Free
replies went wrong in three ways: no name, two photos in one reply, and a
redo nobody knew how to ask for. The form makes each one impossible:

    tap 📸 Add headshot  ->  ONE photo, First name, Last name,
                             [ ] this replaces one that came out wrong
                          ->  Submit

On Submit, Jiraiya posts the photo in the week's thread with a fixed line
("📸 Headshot from @x: *First Last*", "· redo" when ticked). run.py reads that
line exactly -- no guessing names out of chatter -- and does what it always
does: white background, crop, post it back, upload to OwnerVille (replacing
the old photo on a redo).

Rides the always-on Jiraiya listener (due_diligence/bot.py), like New post:
a button only reaches the app that posted it, so Jiraiya posts the button.
Replying with a photo + name the old way still works.

    python -m automations.headshots.form --post-button --office omar          # dry
    python -m automations.headshots.form --post-button --office omar --live   # this week's thread
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

from automations.online_presence.post_form import JIRAIYA

BUTTON = "headshot_add"
FORM = "headshot_form"
MARK = "Headshot from <@"
BUTTON_TEXT = ("*📸 Adding a headshot?* Tap the button: ONE photo, their first "
               "and last name, Submit. Lucy cleans it up and puts it on their "
               "OwnerVille profile.")
# The fixed line Jiraiya posts. run.py reads THIS, never free text.
_LINE = re.compile(r"Headshot from <@[A-Z0-9]+>: \*(?P<name>[^*]+)\*(?P<redo> · redo)?")


# ---- reading a form post (run.py) ---------------------------------------------
def parse(msg: Dict) -> Optional[Tuple[str, bool]]:
    """(name, is_redo) for a post the form made; None for anything else."""
    if msg.get("user") != JIRAIYA:
        return None
    m = _LINE.search(msg.get("text") or "")
    if not m:
        return None
    return m.group("name").strip(), bool(m.group("redo"))


def line(first: str, last: str, user: str, redo: bool) -> str:
    from automations.shared.name_case import titlecase_name
    name = titlecase_name(f"{first.strip()} {last.strip()}")
    return f"📸 Headshot from <@{user}>: *{name}*" + (" · redo" if redo else "")


# ---- the button and the form ------------------------------------------------------
def button_blocks(text: str = BUTTON_TEXT):
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {"type": "actions", "elements": [{
                "type": "button", "action_id": BUTTON, "style": "primary",
                "text": {"type": "plain_text", "text": "📸 Add headshot",
                         "emoji": True}}]}]


def _text(block_id: str, label: str, hint: str) -> Dict:
    return {"type": "input", "block_id": block_id,
            "label": {"type": "plain_text", "text": label},
            "element": {"type": "plain_text_input", "action_id": "v",
                        "placeholder": {"type": "plain_text", "text": hint}}}


def form(channel: str, thread_ts: str) -> Dict:
    """One question per box. Photo, first and last name are required."""
    return {
        "type": "modal", "callback_id": FORM,
        "private_metadata": json.dumps({"c": channel, "t": thread_ts}),
        "title": {"type": "plain_text", "text": "Add headshot"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "input", "block_id": "photo",
             "label": {"type": "plain_text", "text": "Photo"},
             "hint": {"type": "plain_text",
                      "text": "ONE person, ONE photo. Clear, facing the camera, "
                              "chest up."},
             "element": {"type": "file_input", "action_id": "v", "max_files": 1,
                         "filetypes": ["jpg", "jpeg", "png", "heic", "webp"]}},
            _text("first", "First name", "Maria"),
            _text("last", "Last name", "Lopez"),
            {"type": "input", "block_id": "redo", "optional": True,
             "label": {"type": "plain_text", "text": "Redo?"},
             "element": {"type": "checkboxes", "action_id": "v", "options": [{
                 "text": {"type": "plain_text",
                          "text": "This replaces a headshot that came out wrong"},
                 "value": "redo"}]}},
        ]}


def answers(view: Dict) -> Dict:
    vals = (view.get("state") or {}).get("values") or {}

    def v(bid):
        return (((vals.get(bid) or {}).get("v") or {}).get("value") or "").strip()
    files = ((vals.get("photo") or {}).get("v") or {}).get("files") or []
    redo = bool(((vals.get("redo") or {}).get("v") or {}).get("selected_options"))
    return {"files": files, "first": v("first"), "last": v("last"), "redo": redo}


def problems(a: Dict) -> Dict[str, str]:
    """Slack shows these under the box and keeps the form open."""
    errs = {}
    pics = [f for f in a["files"] if str(f.get("mimetype", "")).startswith("image/")]
    if len(pics) != 1 or len(a["files"]) != 1:
        errs["photo"] = "Add ONE photo."
    for bid, label in (("first", "first"), ("last", "last")):
        val = a[bid]
        if not val:
            errs[bid] = f"Add their {label} name."
        elif not re.fullmatch(r"[A-Za-zÀ-ÿ'’. -]{1,40}", val):
            errs[bid] = "Just the name, please."
    return errs


# ---- the Jiraiya listener hooks (asked BEFORE acking, like New post) --------------
def wants(req) -> bool:
    p = req.payload or {}
    if req.type != "interactive":
        return False
    if p.get("type") == "block_actions":
        return any(a.get("action_id") == BUTTON for a in p.get("actions") or [])
    if p.get("type") == "view_submission":
        return (p.get("view") or {}).get("callback_id") == FORM
    return False


def ack(req) -> Optional[Dict]:
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
        chan = ((p.get("channel") or {}).get("id")
                or (p.get("container") or {}).get("channel_id", ""))
        msg = p.get("message") or {}
        # The button lives IN the week's thread: its parent is the thread.
        thread = msg.get("thread_ts") or (p.get("container") or {}).get("thread_ts") \
            or msg.get("ts", "")
        web.views_open(trigger_id=p["trigger_id"], view=form(chan, thread))
        return
    a = answers(p["view"])
    if problems(a):
        return
    meta = json.loads(p["view"].get("private_metadata") or "{}")
    threading.Thread(target=deliver, daemon=True,
                     args=(web, meta.get("c", ""), meta.get("t", ""),
                           p["user"]["id"], a)).start()


def deliver(web, chan: str, thread_ts: str, user: str, a: Dict) -> None:
    """The photo + the fixed line into the week's thread (run.py picks it up)."""
    from automations.online_presence.post_form import _download
    try:
        f = a["files"][0]
        with tempfile.TemporaryDirectory(prefix="lucy-headshot-") as tmp:
            path = Path(tmp) / f"photo.{(f.get('filetype') or 'jpg').lower()}"
            path.write_bytes(_download(web, f))
            web.files_upload_v2(channel=chan, thread_ts=thread_ts, file=str(path),
                                initial_comment=line(a["first"], a["last"], user,
                                                     a["redo"]))
    except Exception as e:                        # noqa: BLE001 -- tell them, never vanish
        print(f"[headshot form] FAILED {type(e).__name__}: {e}", flush=True)
        try:
            web.chat_postEphemeral(channel=chan, user=user,
                                   text=":x: That headshot didn't go through. Tap "
                                        "📸 Add headshot and try again.")
        except Exception:
            pass


# ---- putting the button in a thread -------------------------------------------------
def post_button(channel: str, thread_ts: str, *, text: str = BUTTON_TEXT,
                live: bool = True) -> Dict:
    """Jiraiya posts the button as a reply in the week's thread (Lucy invites
    Jiraiya into the channel first). Never raises: the thread still works
    without it."""
    if not live:
        return {"action": "would_post", "channel": channel, "thread": thread_ts}
    try:
        from automations.due_diligence.watch import _client as jiraiya
        bot = jiraiya()
        try:
            from automations.shared import slack_metrics_post as smp
            smp._client().conversations_invite(channel=channel,
                                               users=bot.auth_test()["user_id"])
        except Exception as e:                    # already_in_channel is fine
            if "already_in_channel" not in str(e):
                print(f"  (couldn't invite Jiraiya: {str(e)[:100]})")
        r = bot.chat_postMessage(channel=channel, thread_ts=thread_ts,
                                 text="📸 Add headshot", blocks=button_blocks(text))
        return {"action": "posted", "channel": channel, "ts": r.get("ts")}
    except Exception as e:                        # noqa: BLE001
        print(f"  (headshot button not posted: {type(e).__name__}: {str(e)[:120]})")
        return {"action": "failed", "error": str(e)[:200]}


def main(argv=None) -> int:
    from automations.headshots import config
    from automations.headshots import weekly_thread as wt
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--post-button", action="store_true", required=True)
    ap.add_argument("--office", required=True, help="a key in headshots config.OFFICES")
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args(argv)
    off = config.OFFICES.get(args.office.lower())
    if off is None:
        print(f"no office {args.office!r}; known: {', '.join(config.OFFICES)}")
        return 2
    anchor = wt.find_week_anchor(channel=off.channel)
    if not anchor:
        print(f"no headshot thread this week in {off.key}'s channel")
        return 1
    print(json.dumps(post_button(off.channel, anchor["ts"], live=args.live)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
