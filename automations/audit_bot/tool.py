"""Run the audit-bot queue actions as a `rerun`, in a FRESH process.

WHY (2026-10-20). New mini_control actions only load when the poller reloads,
and on a backlogged day it never reaches the between-pass reload point — the
first `audit_bot_snapshot` came back "unknown action" with the code already on
disk. A rerun spawns its own python, so it always runs the code that's on disk.

    lucy rerun audit_bot_tool snapshot [colten]
    lucy rerun audit_bot_tool deploy [colten] audit.py [file…]
    lucy rerun audit_bot_tool ls [colten] inbox
    lucy rerun audit_bot_tool channels [colten]
"""
import shlex
import sys

from automations.day_orchestrator import mini_control as mc


def _action_channels(args: str) -> tuple[bool, str]:
    """Every channel the bot is a member of (needs channels:read + groups:read,
    added 2026-10-21). The bot token is read from the bot's own .env and never
    printed — only channel names go to the log."""
    root, _rest, label = mc._audit_bot_root(shlex.split(args or ""))
    env = root / ".runtime" / ".env"
    tok = next((ln.split("=", 1)[1].strip().strip("'\"")
                for ln in env.read_text(encoding="utf-8").splitlines()
                if "=" in ln and ln.split("=", 1)[1].strip().strip("'\"").startswith("xoxb-")),
               None) if env.is_file() else None
    if not tok:
        return False, f"no xoxb- bot token in {env}"
    import ssl
    import certifi
    from slack_sdk import WebClient
    web = WebClient(token=tok, ssl=ssl.create_default_context(cafile=certifi.where()))
    chans, cur = [], None
    while True:
        r = web.users_conversations(types="public_channel,private_channel",
                                    exclude_archived=True, limit=200, cursor=cur)
        chans += r["channels"]
        cur = (r.get("response_metadata") or {}).get("next_cursor")
        if not cur:
            break
    lines = sorted(f"{'private' if c.get('is_private') else 'public '}  "
                   f"#{c.get('name') or c['id']}" for c in chans)
    stem = mc._audit_bot_dump(label, "channels", "\n".join(lines) + "\n")
    return True, f"[{label}] in {len(lines)} channel(s): " + ", ".join(
        l.split()[-1] for l in lines) + f" (log: {stem})"


_ACTIONS = {
    "channels": _action_channels,
    "snapshot": mc._action_audit_bot_snapshot,
    "deploy": mc._action_audit_bot_deploy,
    "ls": mc._action_audit_bot_ls,
    "peek": mc._action_audit_bot_peek,
    "quarantine": mc._action_audit_bot_quarantine,
}


def main(argv: list) -> int:
    if not argv or argv[0] not in _ACTIONS:
        print(f"usage: audit_bot_tool {{{'|'.join(_ACTIONS)}}} [args…]")
        return 2
    ok, msg = _ACTIONS[argv[0]](" ".join(argv[1:]))
    print(("OK " if ok else "FAILED ") + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
