"""Run the audit-bot queue actions as a `rerun`, in a FRESH process.

WHY (2026-10-20). New mini_control actions only load when the poller reloads,
and on a backlogged day it never reaches the between-pass reload point — the
first `audit_bot_snapshot` came back "unknown action" with the code already on
disk. A rerun spawns its own python, so it always runs the code that's on disk.

    lucy rerun audit_bot_tool snapshot [colten]
    lucy rerun audit_bot_tool deploy [colten] audit.py [file…]
    lucy rerun audit_bot_tool ls [colten] inbox
"""
import sys

from automations.day_orchestrator import mini_control as mc

_ACTIONS = {
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
