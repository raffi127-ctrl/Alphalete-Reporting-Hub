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


# WHAT KIND OF POST, THEN QUESTIONS THAT FIT IT (Megan 2026-11-10: "we don't
# need a when/date on this - we need to ask more / prompt more so they know
# what to put - things like 'Is this a team night, what team is this, is this
# a promotion? if so, what level?'"). Picking a kind redraws the form with
# that kind's questions; what's already typed or uploaded stays.
#   (block_id, label, example shown in the box, required, big box)
# Built from what actually gets posted (scanned 2026-11-10): 400 @alphaletemarketing
# Instagram captions (Apr 2023-now), 100 @southshoreflorida (May-Nov 2026), and
# a year of #alphaletesocialmedia -- incl. what Lucy kept coming back to ask
# ("which one is Hank, left or right?", "who did the promoting?", "celebrating
# a win?"). Kinds in order of how often they're posted. No quote/motivation
# kind: those aren't photo posts (Megan 2026-11-10: "remove the quote"). The details each kind
# asks for are the ones its captions used most (a promotion caption names the
# level 96/110 times, the trainer 61, the team 60, time with the company 49).
KINDS = {
    "promotion": ("🎉 A promotion", [
        ("promoted", "Who got promoted?", "Sarah Lopez (or several names)", True, False),
        ("level", "What level did they get promoted to?",
         "Level 1, Level 2, Level 3, Mastermind, AL Partner...", True, False),
        ("trainer", "Who's their trainer / who promoted them?", "Rashad", False, False),
        ("spots", "Who's where in the photo?", "Sarah on the left, Rashad on the right", False, False),
        ("team", "What team are they on?", "Team Elite", False, False),
        ("tenure", "How long have they been with the company?", "6 months, just hit 1 year...", False, False),
        ("earned", "What did they do to earn it? Anything about their story?",
         "Broke the office record, built a team of 5, started with zero sales experience...",
         False, True),
        ("shoutouts", "Anyone else to shout out?", "Their team, their trainer's trainer...", False, False)]),
    "celebration": ("🎂 A birthday, work anniversary or holiday", [
        ("occasion", "What are we celebrating?",
         "Al's birthday, Kiyah's 1 year with us, the Christmas party, Halloween...", True, False),
        ("role", "Their level or role (if it's about one person)", "Level 2 leader", False, False),
        ("fun", "Anything fun happen, or anything to say about them?",
         "Cake + singing, costume contest, one of our top leaders...", False, True)]),
    "day": ("☀️ A day with the team", [
        ("moment", "What's going on?", "Monday kickoff, the early crew, heading out to knock...", True, True),
        ("team", "What team or office?", "Team Elite, the Dallas office", False, False),
        ("people", "Anyone to name?", "Names, or leave blank", False, False)]),
    "spotlight": ("⭐ A spotlight on someone", [
        ("person", "Who are we spotlighting?", "Pranish", True, False),
        ("role", "Their level or role", "Owner, Level 3 leader, top recruiter...", False, False),
        ("story", "What should people know about them?",
         "Started 2 years ago, now runs his own office; always first one in...", True, True)]),
    "win": ("🏆 A big win, contest or award", [
        ("winner", "Who won?", "Mike Chen, 1st Jacie / 2nd Oscar / 3rd Maliha, the whole team...", True, True),
        ("feat", "What did they win or do?",
         "Mentor of the Year, top of the board, a sales contest, 10 sales in a day...", True, True),
        ("prize", "Any prize?", "Trophy, cash, a trip...", False, False),
        ("team", "What team are they on?", "Team Elite", False, False)]),
    # Megan 2026-11-10: "team night should ask where it was or what the
    # activity was" -- both asked, at least ONE of them needed (ONE_OF).
    "teamnight": ("🍻 A team night, outing or reward trip", [
        ("team", "What team is this?", "Team Elite, the managers, the whole Dallas office...", True, False),
        ("where", "Where did you go?", "Dee Lincoln, Topgolf, DFW Adventure Park...", False, False),
        ("activity", "What did you do?", "Laser tag, volleyball, team dinner, Lambo ride...", False, True),
        ("why", "Celebrating anything, or a reward for something?",
         "A record week, top 3 in sales for October, or just for fun", False, True),
        ("thanks", "Anyone to thank for it?", "Raf, Carlos and Colten for treating everyone", False, False)]),
    "training": ("📚 A training or meeting", [
        ("topic", "What was it about?", "Leadership meeting, door approach training...", True, True),
        ("leader", "Who led it?", "Randy", False, False),
        ("people", "Who's in the photos?", "Names, or 'the whole team'", False, False)]),
    "event": ("🎤 A conference, trip or new market", [
        ("event", "What was it?",
         "Regionals, Captain's Retreat, opening our Chicago market, visiting Starr's office...", True, True),
        ("city", "What city?", "Las Vegas, Chicago...", False, False),
        ("people", "Who went?", "Names, or 'the Hashiras team'", False, False),
        ("standout", "Did anyone speak, get recognized, or do it for the first time?",
         "Raf was a featured speaker; Indesia's first regionals", False, True)]),
    # Hiring posts stay about the job, never who we hire (recruiting copy rules).
    "hiring": ("📣 We're hiring / join us", [
        ("pitch", "What should people know about the job?",
         "Paid training, room to grow into management, what a day looks like...", True, True),
        ("office", "What office or city?", "Dallas", False, False),
        ("apply", "How do they apply?", "DM us, link in bio, a link...", False, False)]),
    "community": ("❤️ A community event", [
        ("event", "What's the event?", "Toy drive, school supply giveaway...", True, True),
        ("people", "Who's in the photos?", "Names, or 'the whole team'", False, False)]),
    "other": ("✨ Something else", [
        ("who", "Who's in it?", "Names, or 'the whole team'", True, False),
        ("what", "What's happening?", "Tell Lucy what's going on in the photos", True, True)]),
}
# a kind that needs at least one of these filled (the error goes on the first)
ONE_OF = {"teamnight": ("where", "activity")}
ALWAYS = [("where", "Where was this?", "Dallas office, out in Frisco...", False, False),
          ("extra", "Anything else Lucy should know or mention?",
           "Shout-outs, a hashtag, something funny that happened...", False, True)]


def _questions(kind: str) -> list:
    """The kind's own questions, then the always-asked ones it doesn't already ask."""
    own = KINDS[kind][1] if kind in KINDS else []
    have = {q[0] for q in own}
    return own + [q for q in ALWAYS if q[0] not in have]


def _kind_block(kind: str = "") -> Dict:
    el = {"type": "radio_buttons", "action_id": "kind",
          "options": [{"text": {"type": "plain_text", "text": t, "emoji": True}, "value": k}
                      for k, (t, _) in KINDS.items()]}
    if kind in KINDS:
        el["initial_option"] = next(o for o in el["options"] if o["value"] == kind)
    return {"type": "input", "block_id": "kind", "dispatch_action": True,
            "label": {"type": "plain_text", "text": "What kind of post is this?"},
            "element": el}


def form(channel: str, kind: str = "") -> Dict:
    """Photos + what kind of post. Once a kind is picked, its questions show."""
    blocks = [
        {"type": "input", "block_id": "photos",
         "label": {"type": "plain_text", "text": "Photos for this post"},
         "hint": {"type": "plain_text",
                  "text": f"Up to {MAX_PHOTOS}. They all go in ONE post. "
                          "For separate posts, tap New post again."},
         "element": {"type": "file_input", "action_id": "v", "max_files": MAX_PHOTOS,
                     "filetypes": ["jpg", "jpeg", "png", "heic", "webp"]}},
        _kind_block(kind)]
    if kind in KINDS:
        for bid, label, eg, req, big in _questions(kind):
            blocks.append(_text(bid, label, eg, optional=not req, multiline=big))
    else:
        blocks.append({"type": "context", "elements": [{
            "type": "mrkdwn", "text": "Pick one and Lucy will ask a few quick questions."}]})
    return {"type": "modal", "callback_id": FORM,
            "private_metadata": json.dumps({"channel": channel, "kind": kind}),
            "title": {"type": "plain_text", "text": "New post"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"}, "blocks": blocks}


def _meta(view: Dict) -> Dict:
    raw = view.get("private_metadata") or ""
    try:
        m = json.loads(raw)
        return m if isinstance(m, dict) else {"channel": raw}
    except Exception:
        return {"channel": raw}


def answers(view: Dict) -> Dict:
    vals = (view.get("state") or {}).get("values") or {}

    def v(bid):
        a = (vals.get(bid) or {}).get("v") or {}
        return (a.get("value") or "").strip()
    kind = (((vals.get("kind") or {}).get("kind") or {}).get("selected_option") or {}).get("value") \
        or _meta(view).get("kind") or ""
    files = ((vals.get("photos") or {}).get("v") or {}).get("files") or []
    qs = _questions(kind)
    return {"files": files, "kind": kind,
            "fields": [(bid, label, v(bid)) for bid, label, *_ in qs],
            "required": [bid for bid, _l, _e, req, _b in qs if req]}


def problems(a: Dict) -> Dict[str, str]:
    """Slack shows these under the box (the form stays open)."""
    errs = {}
    pics = [f for f in a["files"] if str(f.get("mimetype", "")).startswith("image/")]
    if not pics:
        errs["photos"] = "Add at least one photo."
    elif len(pics) < len(a["files"]):
        errs["photos"] = "Photos only, please (no videos or documents)."
    if a["kind"] not in KINDS:
        errs["kind"] = "Pick what kind of post this is."
    got = {bid: val for bid, _label, val in a["fields"]}
    for bid in a["required"]:
        if not got.get(bid):
            errs[bid] = "Lucy needs this one to write the caption."
    either = ONE_OF.get(a["kind"])
    if either and not any(got.get(b) for b in either):
        errs[either[0]] = "Tell Lucy where you went or what you did (one is enough)."
    return errs


def message(a: Dict, user: str) -> str:
    """The text under the photos -- what the inbox captions from."""
    n = len(a["files"])
    kind = KINDS.get(a["kind"], ("", []))[0]
    lines = [f"📸 *New post from <@{user}>*" + (f" · {kind}" if kind else "")
             + (f" · {n} photos, one post" if n > 1 else "")]
    lines += [f"*{label}* {val}" for _bid, label, val in a["fields"] if val]
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
        return (any(a.get("action_id") == BUTTON for a in p.get("actions") or [])
                or (p.get("view") or {}).get("callback_id") == FORM)
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
    if p.get("type") == "block_actions" and p.get("view"):
        # a kind was picked: redraw with its questions (same block ids keep
        # whatever was already typed / uploaded)
        view = p["view"]
        kind = next((a.get("selected_option", {}).get("value") for a in p.get("actions") or []
                     if a.get("action_id") == "kind"), "")
        web.views_update(view_id=view["id"], hash=view.get("hash"),
                         view=form(_meta(view).get("channel", ""), kind))
        return
    if p.get("type") == "block_actions":
        chan = (p.get("channel") or {}).get("id") or (p.get("container") or {}).get("channel_id", "")
        web.views_open(trigger_id=p["trigger_id"], view=form(chan))
        return
    a = answers(p["view"])
    if problems(a):
        return                                    # the form stayed open with the errors
    chan, user = _meta(p["view"]).get("channel", ""), p["user"]["id"]
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
                                        "📸 New post and try again.")
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
        for it in bot.pins_list(channel=chan).get("items") or []:
            if any(el.get("action_id") == BUTTON
                   for b in (it.get("message") or {}).get("blocks") or []
                   for el in b.get("elements") or []):
                return {"action": "already_pinned", "channel": chan}
    except Exception:
        pass
    r = bot.chat_postMessage(channel=chan, text="📸 New post", blocks=pin_blocks())
    # Jiraiya has pins:write + pins:read since 2026-11-10; Lucy's login is
    # the fallback. If neither can, the button is still there -- pin it by hand.
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
