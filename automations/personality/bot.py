"""`/personality` on Jiraiya — a word-pick personality test, scored into the
four types (Popular / Powerful / Perfect / Peaceful), result DM'd back.

Megan 2026-10-24: "add to the Jiraiyah bot a /personality", modelled on the
Wired That Way test. The questions are NOT in this code — they live in
questions.json beside it. That file is the whole test: add a row there and
the test grows a row, no code change.

How it works (Megan 2026-10-24: "a row of questions and they select 1 and
then the next 4 pop up", with "1/40" on top):
  /personality   opens a popup showing ONE row: "1/40" and four word
                 buttons. Tapping a word swaps the popup to the next row —
                 no submit, no scrolling a 40-row form. A Back button
                 re-asks the previous row. The four are shuffled per row
                 (fixed per row) — the file lists them by type, and showing
                 them in that order would hand the taker the answer.
  last row       each pick is one point for its type. Highest = your type,
                 next = your second. A tie is said as a tie, never broken by
                 list order. The popup says "check your DMs", the result is
                 DM'd and logged to output/personality/results.jsonl.

The answers so far ride in the popup's private_metadata (one digit per row),
so nothing is kept in memory between taps and a listener restart mid-test
loses nothing but the open popup.

A branch in Jiraiya's _handler, per that module's rule: one listener, one
app, one token, no second process to keep alive.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import datetime as _dt
import json
import random
import threading
import traceback
from pathlib import Path

COMMANDS = ("personality",)
FORM = "personality_form"
START = "personality_start"
SHARE = "personality_share"            # the button under the result DM
SHARE_FORM = "personality_share_form"  # the "who should see it?" popup
PICK = "personality_pick"
BACK = "personality_back"
TYPES = ("popular", "powerful", "perfect", "peaceful")
QUESTIONS = Path(__file__).resolve().parent / "questions.json"
RESULTS = Path(__file__).resolve().parents[2] / "output" / "personality" \
    / "results.jsonl"
# Megan 2026-10-24: every result is also a row on the "Lucy Personality" tab
# of the AUTOMATION MASTER sheet (same id the onboarding stores hardcode).
MASTER_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
SHEET_TAB = "Lucy Personality"
SHEET_HEADER = ["Date", "Name", "ICD Owner", "Primary", "Secondary",
                "Popular", "Powerful", "Perfect", "Peaceful", "Slack ID"]


def load(path=QUESTIONS) -> dict:
    """The test, checked. A broken row fails HERE with its row number,
    not as a popup Slack silently refuses to open."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data.get("rows") or []
    if not rows:
        raise ValueError("questions.json has no rows yet.")
    for i, r in enumerate(rows, 1):
        missing = [t for t in TYPES if not str(r.get(t, "")).strip()]
        if missing:
            raise ValueError("Row {} is missing a word for: {}".format(
                i, ", ".join(missing)))
        if any(len(str(r[t])) > 75 for t in TYPES):
            raise ValueError("Row {} has a word over 75 characters "
                             "(Slack's limit for a button).".format(i))
    for t in TYPES:
        if t not in (data.get("types") or {}):
            raise ValueError("questions.json 'types' is missing '{}'.".format(t))
    return data


def is_sample(data) -> bool:
    return any(r.get("sample") for r in data["rows"])


def _order(i):
    """The four types in a fixed shuffle for row i (1-based)."""
    t = list(TYPES)
    random.Random(i).shuffle(t)
    return t


def _title(data):
    return {"type": "plain_text",
            "text": (data.get("title") or "Personality Test")[:24]}


def start_modal(data, name="") -> dict:
    """Screen 0 (Megan 2026-10-24: "ask name - ICD owner"): one box each,
    then Start. Both required -- the sheet row is useless without them."""
    def box(bid, label, initial, ph):
        el = {"type": "plain_text_input", "action_id": "v",
              "placeholder": {"type": "plain_text", "text": ph}}
        if initial:
            el["initial_value"] = initial
        return {"type": "input", "block_id": bid, "element": el,
                "label": {"type": "plain_text", "text": label}}
    return {"type": "modal", "callback_id": START, "title": _title(data),
            "submit": {"type": "plain_text", "text": "Start"},
            "close": {"type": "plain_text", "text": "Quit"},
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": (
                    ":crystal_ball: *What's your personality type?*\n"
                    "{} quick picks and Jiraiya will tell you -- plus your "
                    "superpowers in the field and with your team.\n\n"
                    "First, who are you?").format(len(data["rows"]))}},
                box("name", "Your name", name, "First and last name"),
                box("owner", "Your ICD owner", "",
                    "The owner of your office")]}


def meta_of(view) -> dict:
    """{"n": name, "o": owner, "p": picks} from a popup's private_metadata."""
    try:
        m = json.loads(view.get("private_metadata") or "{}")
    except ValueError:
        m = {}
    return {"n": m.get("n", ""), "o": m.get("o", ""), "p": m.get("p", "")}


def _cheer(n, total, section, prev_section):
    if section and prev_section and section != prev_section:
        return (":raised_hands: *Halfway there!* Now the {} -- be honest, "
                "nobody's perfect.".format(section.lower()))
    if n == total:
        return ":checkered_flag: *Last one!*"
    if n == total - 9 and total >= 20:
        return ":muscle: *Almost done!* 10 to go."
    if n == 11 and total >= 30:
        return ":fire: *You're on a roll!*"
    return ""


def modal(data, picks="", who=None) -> dict:
    """The popup for the NEXT unanswered row. `picks` = one digit per row
    answered so far (index into TYPES); `who` = {"n": name, "o": owner},
    carried along in private_metadata so the last tap can log it."""
    who = who or {}
    rows = data["rows"]
    n = len(picks) + 1                   # the row being asked, 1-based
    r = rows[n - 1]
    blocks = []
    if n == 1:
        blocks.append({"type": "section", "text": {
            "type": "mrkdwn", "text": data.get("intro") or
            "Pick the ONE word that sounds most like you."}})
    blocks.append({"type": "header", "text": {
        "type": "plain_text", "text": "{}/{}".format(n, len(rows))}})
    # Megan 2026-10-24: "look more fun" -- a progress bar, the section,
    # and a cheer at the milestones.
    done = round(10 * (n - 1) / len(rows))
    ctx = ":large_green_square:" * done + ":white_large_square:" * (10 - done)
    if r.get("section"):
        ctx += "   *{}*".format(r["section"])
    blocks.append({"type": "context", "elements": [{
        "type": "mrkdwn", "text": ctx}]})
    cheer = _cheer(n, len(rows), r.get("section"),
                   rows[n - 2].get("section") if n > 1 else None)
    if cheer:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
                                                   "text": cheer}})
    # Megan 2026-10-24: "our audience is super young" — each word keeps its
    # plain meaning from the row's "means", listed in the buttons' order.
    means = r.get("means") or {}
    if means:
        blocks.append({"type": "section", "text": {
            "type": "mrkdwn", "text": "\n".join(
                "*{}* — {}".format(str(r[t]).strip(), means[t]) if means.get(t)
                else "*{}*".format(str(r[t]).strip()) for t in _order(n))}})
    blocks.append({"type": "actions", "block_id": "row{}".format(n),
                   "elements": [
        {"type": "button", "action_id": "{}_{}".format(PICK, t),
         "text": {"type": "plain_text", "text": str(r[t]).strip()},
         "value": str(TYPES.index(t))} for t in _order(n)]})
    if picks:
        blocks.append({"type": "actions", "block_id": "nav", "elements": [
            {"type": "button", "action_id": BACK,
             "text": {"type": "plain_text", "text": "← Back"}}]})
    meta = json.dumps({"n": who.get("n", ""), "o": who.get("o", ""),
                       "p": picks})
    return {"type": "modal", "callback_id": FORM, "private_metadata": meta,
            "title": _title(data),
            "close": {"type": "plain_text", "text": "Quit"},
            "blocks": blocks}


def done_modal(data) -> dict:
    return {"type": "modal", "callback_id": FORM + "_done",
            "title": _title(data),
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": [{"type": "section", "text": {
                "type": "mrkdwn",
                "text": ":tada: *All {} done!* :tada:\n\nCheck your DMs from "
                        "Jiraiya to see your type -- and share it with your "
                        "upline from there.".format(len(data["rows"]))}}]}


def step(picks, action) -> str:
    """The new answers string after a tap: a pick appends, Back drops one."""
    aid = action.get("action_id", "")
    if aid == BACK:
        return picks[:-1]
    if aid.startswith(PICK) and action.get("value", "") in "0123":
        return picks + action["value"]
    return picks


def answers_of(picks) -> dict:
    """{row number: type key} from the answers string."""
    return {i: TYPES[int(c)] for i, c in enumerate(picks, 1)}


def score(answers) -> dict:
    s = {t: 0 for t in TYPES}
    for t in answers.values():
        s[t] += 1
    return s


def ranked(scores):
    """[[types tied at the top], [types tied second]] — ties stay ties."""
    levels = sorted({v for v in scores.values() if v > 0}, reverse=True)
    return [[t for t in TYPES if scores[t] == lv] for lv in levels[:2]]


def result_parts(data, scores, name=None):
    """(big title, [paragraphs]) -- the result in pieces, so the DM can put
    the title in a header block and a divider between each piece.
    `name` set = a shared copy ("Jo is a ..."), else the taker's own."""
    types = data["types"]
    tiers = ranked(scores)
    if not tiers:
        return "No result", ["No answers came through, so there's no result."]
    top = tiers[0]

    def names(ts, emoji=True):
        return " + ".join("{}{}".format(types[t]["name"], " " +
                                        types[t]["emoji"] if emoji else "")
                          for t in ts)

    who = "{} is".format(name) if name else "You're"
    if len(top) == 1:
        t = top[0]
        title = "{e} {w} a {n}! {e}".format(e=types[t]["emoji"], w=who,
                                             n=types[t]["name"])
    else:
        title = ":sparkles: {} an even mix: {}! :sparkles:".format(
            who, names(top, emoji=False))
    paras = []
    if is_sample(data):
        paras.append("_SAMPLE questions -- this is not a real result yet._")
    # Megan 2026-10-24: "I also want this to look more fun" -- colored
    # emoji bars, one color per type, instead of grey boxes.
    total = sum(scores.values()) or 1
    bars = []
    if len(tiers) > 1:
        bars.append("Secondary: *{}*\n".format(names(tiers[1])))
    for t in sorted(TYPES, key=lambda k: -scores[k]):
        filled = round(10 * scores[t] / total)
        # score BEFORE the name (Megan 10/24: "Peaceful Phlegmatic 12"
        # wrapped and left the 12 alone on the next line)
        bars.append("{}{}  *{}*  {}".format(
            types[t].get("square", ":black_large_square:") * filled,
            ":white_large_square:" * (10 - filled), scores[t],
            types[t]["name"]))
    paras.append("\n".join(bars))
    for t in top:
        lines = ["*{} {}*".format(types[t]["emoji"], types[t]["name"])]
        # Megan 2026-10-24: "the result [should] have an overall
        # description for them" -- who you are, in plain words, first.
        if (types[t].get("overall") or "").strip():
            lines.append(types[t]["overall"].strip())
        # Megan 2026-10-24: "still have in some of the actual quiz
        # verbiage" -- the sheet's own description, then the field
        # write-up (written for B2B AND D2D). No "words you picked": cut.
        if (types[t].get("classic") or "").strip():
            lines.append(":scroll: _The classic description:_ {}".format(
                types[t]["classic"].strip()))
        about = (types[t].get("about") or "").strip()
        if about:
            lines.append(about.replace("*In the field:*",
                                       ":briefcase: *In the field:*")
                         .replace("*Level up:*", ":rocket: *Level up:*"))
        paras.append("\n\n".join(lines))
    # Megan 2026-10-24: "tailored strengths and weaknesses at the bottom".
    # A tie lists each type's under its own name, never a merged list.
    # Megan 2026-10-24: "we also build teams, that's how they grow" -- each
    # list has an in-the-field half and a team-building half.
    for label, key in ((":muscle: Your strengths", "strengths"),
                       (":warning: Watch out for", "weaknesses")):
        for t in top:
            parts = [(sub, types[t].get(k) or []) for sub, k in
                     ((":dart: In the field", key),
                      (":busts_in_silhouette: Building your team",
                       "team_" + key))]
            parts = [(sub, items) for sub, items in parts if items]
            if not parts:
                continue
            head = label if len(top) == 1 else "{} ({})".format(
                label, types[t]["name"])
            body = "\n\n".join("_{}_\n{}".format(
                sub, "\n".join("• " + x for x in items))
                for sub, items in parts)
            paras.append("*{}*\n{}".format(head, body))
    return title, paras


def result_text(data, scores, name=None) -> str:
    """The plain-text version (notification preview, logs, tests)."""
    title, paras = result_parts(data, scores, name)
    return "*{}*\n\n{}".format(title, "\n\n".join(paras))


def result_blocks(data, scores, who, share=True, name=None) -> list:
    """The result as Slack blocks: a big header, then each piece with a
    divider between (a section caps at 3000 chars). The taker's own copy
    ends with the share button, which carries the scores, not the text, so
    a shared copy is always rebuilt from today's write-ups."""
    title, paras = result_parts(data, scores, name)
    blocks = [{"type": "header", "text": {"type": "plain_text",
                                          "text": title[:150], "emoji": True}}]
    for i, p in enumerate(paras):
        if i:
            blocks.append({"type": "divider"})
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": p[:3000]}})
    if share:
        blocks.append({"type": "divider"})
        blocks.append({"type": "actions", "block_id": "share", "elements": [{
            "type": "button", "action_id": SHARE, "style": "primary",
            "text": {"type": "plain_text", "text": ":outbox_tray: Share with your upline",
                     "emoji": True},
            "value": json.dumps({"s": [scores[t] for t in TYPES],
                                 "n": who.get("n", ""), "o": who.get("o", "")})
        }]})
    return blocks


def share_modal(value) -> dict:
    """Megan 2026-10-24: a plain "share" -- send it to anyone in the Slack
    workspace. One box: pick the people (as many as they like)."""
    return {"type": "modal", "callback_id": SHARE_FORM,
            "private_metadata": value,
            "title": {"type": "plain_text", "text": "Share my result"},
            "submit": {"type": "plain_text", "text": "Send"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [{"type": "input", "block_id": "to",
                        "label": {"type": "plain_text",
                                  "text": "Send it to"},
                        "element": {"type": "multi_users_select",
                                    "action_id": "v",
                                    "placeholder": {"type": "plain_text",
                                                    "text": "Anyone in Slack"}}}]}


def _share(web, from_id, value, to_ids):
    """Megan 2026-10-24: a share landed in Raf's Jiraiya app chat, where
    nobody looks. So each person picked gets a GROUP DM -- the sharer, that
    person, and Jiraiya -- which shows up as a new conversation with the
    sharer's name on it. One group per person, so two uplines never see
    each other's thread. Needs the bot scope mpim:write; without it (or any
    other open failure) that person gets the app DM instead, so a share
    never silently goes nowhere."""
    v = json.loads(value)
    scores = dict(zip(TYPES, v["s"]))
    data = load()
    name = v.get("n") or "<@{}>".format(from_id)
    owner = " (ICD owner: {})".format(v["o"]) if v.get("o") else ""
    text = result_text(data, scores, name)
    grouped, direct = [], []
    for uid in to_ids:
        if uid == from_id:
            continue
        try:
            ch = web.conversations_open(
                users="{},{}".format(from_id, uid))["channel"]["id"]
            head = ":outbox_tray: <@{}> shared their personality result " \
                   "with <@{}>{}".format(from_id, uid, owner)
            out = grouped
        except Exception as e:  # noqa: BLE001 — fall back, don't drop it
            print("[personality] group DM failed for {}: {}".format(uid, e),
                  flush=True)
            ch = uid
            head = ":outbox_tray: <@{}> shared their personality result " \
                   "with you{}".format(from_id, owner)
            out = direct
        web.chat_postMessage(
            channel=ch, text=head + "\n\n" + text,
            blocks=[{"type": "section", "text": {"type": "mrkdwn",
                                                 "text": head}}]
            + result_blocks(data, scores, {}, share=False, name=name))
        out.append("<@{}>".format(uid))
    msg = []
    if grouped:
        msg.append("Sent your result to {} -- it's in a group chat with "
                   "you both :white_check_mark:".format(", ".join(grouped)))
    if direct:
        msg.append("Sent your result to {} -- they'll find it under Apps → "
                   "Jiraiya in Slack :white_check_mark:".format(
                       ", ".join(direct)))
    if grouped or direct:
        # the group chat already shows the sharer the result; only say
        # where it went when some of it went somewhere they can't see
        if direct:
            web.chat_postMessage(channel=from_id, text="\n".join(msg))
        return
    web.chat_postMessage(channel=from_id,
                         text="Nobody to send to -- pick someone other than "
                              "you.")


def log(user_id, who, answers, scores, path=RESULTS):
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"at": _dt.datetime.now().isoformat(timespec="seconds"),
           "user_id": user_id, "name": who.get("n", ""),
           "icd_owner": who.get("o", ""),
           "scores": scores, "answers": {str(k): v for k, v in
                                         sorted(answers.items())}}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def sheet_row(data, user_id, who, scores, when=None) -> list:
    """One "Lucy Personality" row. A tie keeps both names ("A + B") so the
    sheet never claims a primary the test didn't give."""
    types = data["types"]
    tiers = ranked(scores)

    def names(i):
        return " + ".join(types[t]["name"] for t in tiers[i]) \
            if len(tiers) > i else ""

    when = when or _dt.datetime.now()
    return [when.strftime("%Y-%m-%d %H:%M"), who.get("n", ""),
            who.get("o", ""), names(0), names(1)] \
        + [scores[t] for t in TYPES] + [user_id]


def _sheet_ws():
    from automations.recruiting_report.fill import open_by_key, _retry
    sh = open_by_key(MASTER_SHEET_ID)
    try:
        return sh.worksheet(SHEET_TAB), _retry
    except Exception:  # noqa: BLE001 — first run: build the tab
        ws = _retry(sh.add_worksheet, title=SHEET_TAB, rows=500,
                    cols=len(SHEET_HEADER))
        _retry(ws.update, values=[SHEET_HEADER], range_name="A1")
        _retry(ws.format, "1:1", {"textFormat": {"bold": True}})
        _retry(ws.freeze, rows=1)
        return ws, _retry


def save_to_sheet(row) -> None:
    """Append, never overwrite. A header that isn't ours means someone
    changed the tab by hand -- say so instead of writing into the wrong
    columns."""
    ws, _retry = _sheet_ws()
    head = _retry(ws.row_values, 1)
    if head and head[:len(SHEET_HEADER)] != SHEET_HEADER:
        raise RuntimeError("the '{}' tab's header changed -- not writing "
                           "into the wrong columns".format(SHEET_TAB))
    if not head:
        _retry(ws.update, values=[SHEET_HEADER], range_name="A1")
    _retry(ws.append_row, row, value_input_option="USER_ENTERED")


def wants(req):
    """Is this request ours? Asked BEFORE acking, so Jiraiya only swallows
    the envelopes that belong to /personality."""
    p = req.payload or {}
    if req.type == "slash_commands":
        return p.get("command", "").lstrip("/").lower() in COMMANDS
    if req.type == "interactive" and p.get("type") == "block_actions":
        if p.get("view", {}).get("callback_id") == FORM:
            return True
        return any(a.get("action_id") == SHARE for a in p.get("actions", []))
    if req.type == "interactive" and p.get("type") == "view_submission":
        return p.get("view", {}).get("callback_id") in (START, SHARE_FORM)
    return False


def ack(req):
    """The payload Jiraiya acks with. The name/owner screen is a real form
    submit, and Slack takes the next screen (or the box errors) IN the ack
    -- a plain ack would just close the popup."""
    p = req.payload or {}
    if not (req.type == "interactive" and p.get("type") == "view_submission"
            and p.get("view", {}).get("callback_id") == START):
        return None
    vals = p["view"].get("state", {}).get("values", {})

    def g(bid):
        return " ".join(((vals.get(bid, {}).get("v", {}) or {})
                         .get("value") or "").split())
    who = {"n": g("name"), "o": g("owner")}
    errors = {}
    if not who["n"]:
        errors["name"] = "Type your name."
    if not who["o"]:
        errors["owner"] = "Type your ICD owner's name."
    if errors:
        return {"response_action": "errors", "errors": errors}
    try:
        return {"response_action": "update", "view": modal(load(), "", who)}
    except Exception as e:  # noqa: BLE001 — never leave Slack un-acked
        return {"response_action": "errors",
                "errors": {"name": "The test isn't set up yet: {}".format(e)}}


def _real_name(web, user_id):
    try:
        u = web.users_info(user=user_id).get("user") or {}
        return (u.get("real_name") or u.get("profile", {}).get("real_name")
                or "").strip()
    except Exception:  # noqa: BLE001 — a blank box is fine, they type it
        return ""


def handle(client, req):
    p = req.payload or {}
    web = client.web_client
    if req.type == "slash_commands":
        user_id = p.get("user_id", "")
        try:
            view = start_modal(load(), _real_name(web, user_id))
        except Exception as e:  # noqa: BLE001 — say it, don't go silent
            web.chat_postMessage(channel=user_id, text=(
                "The personality test isn't set up yet: {}".format(e)))
            return
        web.views_open(trigger_id=p["trigger_id"], view=view)
        return
    if p.get("type") == "view_submission":
        if p["view"].get("callback_id") == SHARE_FORM:
            to = (p["view"].get("state", {}).get("values", {}).get("to", {})
                  .get("v", {}).get("selected_users") or [])
            threading.Thread(target=_share, args=(
                web, p.get("user", {}).get("id", ""),
                p["view"].get("private_metadata", "{}"), to),
                daemon=True).start()
        return                     # the start screen: ack() already moved on
    if any(a.get("action_id") == SHARE for a in p.get("actions", [])):
        a = [a for a in p["actions"] if a.get("action_id") == SHARE][0]
        web.views_open(trigger_id=p["trigger_id"],
                       view=share_modal(a.get("value", "{}")))
        return
    # a word (or Back) was tapped
    view = p["view"]
    data = load()
    meta = meta_of(view)
    who = {"n": meta["n"], "o": meta["o"]}
    picks = step(meta["p"], (p.get("actions") or [{}])[0])
    picks = picks[:len(data["rows"])]
    try:
        # `hash` makes Slack refuse an update built from a stale popup, so a
        # double-tap can't answer the same row twice.
        if len(picks) < len(data["rows"]):
            web.views_update(view_id=view["id"], hash=view.get("hash"),
                             view=modal(data, picks, who))
            return
        web.views_update(view_id=view["id"], hash=view.get("hash"),
                         view=done_modal(data))
    except Exception as e:  # noqa: BLE001
        print("[personality] update skipped: {}".format(e), flush=True)
        return
    threading.Thread(target=_background,
                     args=(web, p.get("user", {}).get("id", ""), who,
                           answers_of(picks)),
                     daemon=True).start()


def _background(web, user_id, who, answers):
    data = load()
    scores = score(answers)
    try:
        log(user_id, who, answers, scores)
        web.chat_postMessage(channel=user_id, text=result_text(data, scores),
                             blocks=result_blocks(data, scores, who))
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        try:
            web.chat_postMessage(channel=user_id, text=(
                "Your test went in but the result didn't finish: {}".format(e)))
        except Exception:  # noqa: BLE001
            pass
    try:
        save_to_sheet(sheet_row(data, user_id, who, scores))
        print("[personality] logged {} ({}) to {}".format(
            who.get("n"), who.get("o"), SHEET_TAB), flush=True)
    except Exception as e:  # noqa: BLE001 — the DM already went; the local
        traceback.print_exc()  # results.jsonl still has the row to replay
        print("[personality] SHEET WRITE FAILED for {}: {}".format(
            who.get("n"), e), flush=True)
