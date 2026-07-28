"""Jiraiya — Socket Mode app: `/dd` opens a fill-in popup, hit Summon Jiraiya.

An always-on listener (Socket Mode, no inbound HTTP needed). On `/dd` it opens a
modal with ICD / Leader / Team fields; on submit it pulls the whole team from
Tableau and logs the 3-table block to that ICD's tab, then DMs the requester the
result. Uses the stdlib socket-mode backend — no extra dependency.

Tokens:
  * bot   (xoxb) — DD_BOT_TOKEN or ~/.config/recruiting-report/dd-bot-token
  * app   (xapp) — DD_APP_TOKEN or ~/.config/recruiting-report/dd-app-token
"""
from __future__ import annotations

import os
import ssl
import threading
from pathlib import Path

from . import config as C
from . import fill as dd_fill

CALLBACK = "dd_form"


def _app_token() -> str:
    tok = os.environ.get("DD_APP_TOKEN", "").strip()
    if not tok:
        f = Path.home() / ".config" / "recruiting-report" / "dd-app-token"
        if f.exists():
            tok = f.read_text(encoding="utf-8-sig").strip()
    if not tok:
        raise SystemExit("No app-level token — set DD_APP_TOKEN or save it to "
                         "~/.config/recruiting-report/dd-app-token (xapp-…).")
    return tok.lstrip("﻿")


def _web():
    from .watch import _client
    return _client()               # the Jiraiya bot (xoxb) web client


def _modal() -> dict:
    def _inp(bid, label, ph, multiline=False, optional=False):
        return {"type": "input", "block_id": bid, "optional": optional,
                "label": {"type": "plain_text", "text": label},
                "element": {"type": "plain_text_input", "action_id": "v",
                            "multiline": multiline,
                            "placeholder": {"type": "plain_text", "text": ph}}}
    return {
        "type": "modal", "callback_id": CALLBACK,
        "title": {"type": "plain_text", "text": "Jiraiya"},
        "submit": {"type": "plain_text", "text": "Summon Jiraiya"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": ":scroll: I'll pull the team's last 8 weeks of fiber, "
                     "wireless, cancel & churn and log it to the ICD's tab."}},
            _inp("icd", "ICD", "Tony Chavez"),
            _inp("leader", "Leader", "Baraquiel Fimbres", optional=True),
            _inp("team", "Team (one rep per line)",
                 "Isaac Torres\nDavid Becerra\nEmilio Fimbres", multiline=True),
        ],
    }


def _process(web, user_id: str, icd: str, leader: str, names: list) -> None:
    """Runs in a background thread (the pull takes minutes; the modal was already
    ack'd). DMs the requester progress + the result."""
    from .pull import gather_team
    link = f"https://docs.google.com/spreadsheets/d/{C.DD_SHEET_ID}/edit"
    try:
        n = len(names)
        est = max(2, round(1.5 + 0.6 * n))     # ~rough minutes, scales with team size
        web.chat_postMessage(channel=user_id, text=(
            f":frog: On it — pulling *{icd}* ({n} rep{'s' if n != 1 else ''}). "
            f"This takes about *{est} min*; I'll drop the numbers here and log them "
            f"to the <{link}|Due Diligence sheet>."))
        people, misses = gather_team(names, icd=icd)
        if not people:
            web.chat_postMessage(channel=user_id, text=(
                f":warning: Couldn't find any of those reps under *{icd}*: "
                f"{', '.join(names)}. Check the spelling and try `/dd` again."))
            return
        res = dd_fill.write_team_block(people, icd=icd, leader=leader, dry_run=False)
        lines = [f":scroll: *Due Diligence — {icd}*  ({len(people)} rep"
                 f"{'s' if len(people) != 1 else ''})"]
        for p in people:
            lines.append(f"• {p.matched_rep} — fiber 8wk *{p.new_int.avg_8wk}* · "
                         f"wireless 8wk *{p.wireless.avg_8wk}*")
        if res.get("wrote"):
            newtab = " (new tab)" if res.get("created_tab") else ""
            lines.append(f":pencil2: Logged to the *{res.get('tab')}* tab{newtab} — <{link}|open sheet>.")
        else:
            lines.append(f":warning: Not logged: {res.get('error')}.")
        if misses:
            lines.append(f":warning: Couldn't match (check spelling): {', '.join(misses)}")
        web.chat_postMessage(channel=user_id, text="\n".join(lines))
    except Exception as e:                       # noqa: BLE001 — never crash the listener
        try:
            web.chat_postMessage(channel=user_id,
                                 text=f":x: Jiraiya hit an error: {type(e).__name__}: {str(e)[:200]}")
        except Exception:
            pass


def _handler(client, req):
    from slack_sdk.socket_mode.response import SocketModeResponse
    print(f"[req] type={req.type} cmd={req.payload.get('command')} "
          f"ptype={req.payload.get('type')}", flush=True)
    if req.type == "slash_commands" and req.payload.get("command") == "/dd":
        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        try:
            r = client.web_client.views_open(trigger_id=req.payload["trigger_id"], view=_modal())
            print(f"[modal] opened ok={r.get('ok')}", flush=True)
        except Exception as e:                # noqa: BLE001
            print(f"[modal] FAILED {type(e).__name__}: {e}", flush=True)
        return
    if req.type == "interactive" and req.payload.get("type") == "view_submission" \
            and req.payload.get("view", {}).get("callback_id") == CALLBACK:
        vals = req.payload["view"]["state"]["values"]
        def g(bid):
            return (vals.get(bid, {}).get("v", {}).get("value") or "").strip()
        icd, leader, team_raw = g("icd"), g("leader"), g("team")
        names = ([leader] if leader else []) + [l.strip() for l in team_raw.splitlines() if l.strip()]
        names = list(dict.fromkeys(names))       # dedup, keep order
        user_id = req.payload["user"]["id"]
        # Close the modal immediately (must ack < 3s); process in the background.
        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        threading.Thread(target=_process, args=(client.web_client, user_id, icd, leader, names),
                         daemon=True).start()
        return
    # ack anything else so Slack doesn't retry
    client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))


def run() -> None:
    from slack_sdk.socket_mode.builtin import SocketModeClient
    web = _web()
    client = SocketModeClient(app_token=_app_token(), web_client=web)
    client.socket_mode_request_listeners.append(_handler)
    print("Jiraiya Socket Mode listener connecting…")
    client.connect()
    print("connected — /dd is live. Ctrl-C to stop.")
    threading.Event().wait()


if __name__ == "__main__":
    run()
