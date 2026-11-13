"""Run the audit-bot queue actions as a `rerun`, in a FRESH process.

WHY (2026-10-20). New mini_control actions only load when the poller reloads,
and on a backlogged day it never reaches the between-pass reload point — the
first `audit_bot_snapshot` came back "unknown action" with the code already on
disk. A rerun spawns its own python, so it always runs the code that's on disk.

    lucy rerun audit_bot_tool snapshot [colten]
    lucy rerun audit_bot_tool deploy [colten] audit.py [file…]
    lucy rerun audit_bot_tool ls [colten] inbox
    lucy rerun audit_bot_tool channels [colten]
    lucy rerun audit_bot_tool grep [colten] "<regex>"   (search saved reports)
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


def _action_grep(args: str) -> tuple[bool, str]:
    """READ-ONLY: search the bot's saved reports (reports/*.md) for a regex and
    dump every hit as `file :: line` into output/logs for `logtail`.

      audit_bot_tool grep "(?i)company name"
      audit_bot_tool grep colten "(?i)company name"
    """
    import re
    root, rest, label = mc._audit_bot_root(shlex.split(args or ""))
    if not rest:
        return False, "usage: audit_bot_tool grep [colten] <regex>"
    try:
        rx = re.compile(" ".join(rest))  # main() re-joins argv with spaces
    except re.error as e:
        return False, f"bad regex: {e}"
    reports = root / "reports"
    if not reports.is_dir():
        return False, f"no reports folder: {reports}"
    out, files = [], 0
    for p in sorted(reports.glob("*.md")):
        hits = [ln.strip() for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()
                if rx.search(ln)]
        if hits:
            files += 1
            out += [f"{p.name} :: {h[:500]}" for h in hits]
    stem = mc._audit_bot_dump(label, "grep", "\n".join(out) + "\n")
    return True, (f"[{label}] {files} report(s), {len(out)} line(s) match "
                  f"-> `lucy logtail {stem} . 40`")


def _action_regrade(args: str) -> tuple[bool, str]:
    """Start a SILENT regrade (automations/audit_bot/regrade.py) of the reports
    listed in automations/audit_bot/regrade_lists/<name>.txt, detached, in the
    bot's own venv. Returns at once; progress goes to output/logs/.

      audit_bot_tool regrade company_name
      audit_bot_tool regrade colten company_name
      audit_bot_tool regrade company_name --at 22:00   (sleeps until then)"""
    import os
    import subprocess
    root, rest, label = mc._audit_bot_root(shlex.split(args or ""))
    if not rest:
        return False, "usage: audit_bot_tool regrade [colten] <list name>"
    here = mc.REPO_ROOT / "automations" / "audit_bot"
    lst = here / "regrade_lists" / f"{rest[0]}.txt"
    if not lst.is_file():
        return False, f"no list {lst.name} (run `update` first?)"
    py = root / ".runtime" / "venv" / "bin" / "python"
    if not py.exists():
        return False, f"no bot venv at {py}"
    ps = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True,
                        timeout=15).stdout
    if any("regrade.py" in l and str(lst) in l for l in ps.splitlines()):
        return False, f"[{label}] a regrade of {lst.name} is already running"
    log = mc.REPO_ROOT / "output" / "logs" / f"regrade-{label}-{rest[0]}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["DYLD_FALLBACK_LIBRARY_PATH"] = "/opt/homebrew/lib:" + env.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    argv = ([str(py), str(here / "regrade.py"), str(lst)]
            + (["colten"] if label == "colten" else []) + rest[1:])  # e.g. --at 22:00
    with open(log, "a", encoding="utf-8") as fh:
        p = subprocess.Popen(argv, cwd=str(root / ".runtime"), stdout=fh,
                             stderr=subprocess.STDOUT, env=env, start_new_session=True)
    n = sum(1 for ln in lst.read_text(encoding="utf-8").splitlines() if ln.strip())
    return True, (f"[{label}] regrade of {n} report(s) started, pid {p.pid} — "
                  f"progress `lucy logtail regrade-{label}-{rest[0]} . 20`, "
                  f"results `logdump regrade-{label}-{rest[0]}.tsv`")


_ACTIONS = {
    "regrade": _action_regrade,
    "grep": _action_grep,
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
