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
    lucy rerun audit_bot_tool reassign [colten] <owner> = <rep>, <rep> [--apply]
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


def _norm_name(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (s or "").lower())).strip()


def _action_reassign(args: str) -> tuple[bool, str]:
    """Move reps to another owner in the bot's reps.json (a rep who answered the
    owner question wrong — Colten 2026-11-18: three of Samuel Acay's reps sent
    Colten's / Raf's name). The scorecards read each rep's CURRENT owner, so
    their past audits move too. Dry run unless --apply; reps.json is backed up
    to .runtime/backup-<stamp>/ first. The full roster goes to the log.

      audit_bot_tool reassign colten Samuel Acay = Oswaldo, Katherine Gomez, Valentina
      audit_bot_tool reassign colten Samuel Acay = Oswaldo, Katherine Gomez, Valentina --apply

    A rep is a Slack ID (U0…; most reps have no name saved), a full name, or a
    first name only ONE rep has. The owner matches its exact name/alias, or a
    longer saved name ("Samuel Acay" -> "Samuel Acay Escobar") when only one
    fits; an owner not on the bot's list yet is added (with --apply)."""
    import json
    import re
    import shutil
    from datetime import datetime
    parts = (args or "").split()
    apply = "--apply" in parts
    parts = [p for p in parts if p != "--apply"]
    root, rest, label = mc._audit_bot_root(parts)
    text = " ".join(rest)
    if "=" not in text:
        return False, "usage: audit_bot_tool reassign [colten] <owner> = <rep>, <rep> [--apply]"
    owner_q, reps_q = (s.strip() for s in text.split("=", 1))
    rep_qs = [r.strip() for r in reps_q.split(",") if r.strip()]
    rt = root / ".runtime"
    of, rf = rt / "owners.json", rt / "reps.json"
    if not of.is_file() or not rf.is_file():
        return False, f"[{label}] no owners.json / reps.json in {rt}"
    owners_doc = json.loads(of.read_text(encoding="utf-8"))
    reps_doc = json.loads(rf.read_text(encoding="utf-8"))
    owners, reps = owners_doc.get("owners", []), reps_doc.get("reps", {})
    oname = {o.get("id"): o.get("name", o.get("id")) for o in owners}

    # Owner: exact name or alias only — no fuzzy guess on who gets the reps.
    want = _norm_name(owner_q)
    owner = next((o for o in owners if _norm_name(o.get("name", "")) == want
                  or want in [_norm_name(a) for a in o.get("aliases") or []]), None)
    if not owner:  # "Samuel Acay" when the rep confirmed "Samuel Acay Escobar"
        longer = [o for o in owners if _norm_name(o.get("name", "")).startswith(want + " ")]
        owner = longer[0] if len(longer) == 1 else None
    log = [f"owner wanted: {owner_q} -> "
           + (f"{owner['name']} ({owner['id']})" if owner else "NOT on the bot's list")]

    picks, problems = [], []
    for q in rep_qs:
        if re.fullmatch(r"U[A-Z0-9]{6,}", q):  # Slack ID — most reps have no name saved
            if q in reps:
                picks.append((q, q, reps[q]))
            else:
                problems.append(f"{q}: no rep with that Slack ID")
            continue
        nq = _norm_name(q)
        full =[(u, r) for u, r in reps.items()
                if _norm_name(f"{r.get('first_name', '')} {r.get('last_name', '')}") == nq]
        first = [(u, r) for u, r in reps.items() if _norm_name(r.get("first_name", "")) == nq]
        hits = full or first
        if len(hits) == 1:
            picks.append((q, *hits[0]))
        else:
            problems.append(f"{q}: {'no rep by that name' if not hits else f'{len(hits)} reps match'}")

    roster = sorted(f"{r.get('first_name', '')} {r.get('last_name', '')}".strip() + f" [{u}]"
                    f" -> {oname.get(r.get('owner_id'), r.get('owner_id') or '-')}"
                    for u, r in reps.items())
    for q, u, r in picks:
        log.append(f"{q}: {r.get('first_name', '')} {r.get('last_name', '')} [{u}] "
                   f"now under {oname.get(r.get('owner_id'), r.get('owner_id') or '-')}")
    log += problems + ["", "ALL REPS:"] + roster
    stem = mc._audit_bot_dump(label, "reassign", "\n".join(log) + "\n")
    summary = "; ".join(log[1:1 + len(picks)] + problems)
    if problems or not picks:
        return False, f"[{label}] nothing changed — {summary} (roster: `lucy logtail {stem} . 80`)"
    if not apply:
        return True, (f"[{label}] DRY RUN -> {owner['name'] if owner else owner_q + ' (would be added)'}: "
                      f"{summary}. Add --apply to save. (`lucy logtail {stem} . 80`)")

    backup = rt / f"backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    backup.mkdir()
    shutil.copy2(of, backup / of.name)
    shutil.copy2(rf, backup / rf.name)
    if not owner:
        oid = base = re.sub(r"[^a-z0-9]+", "_", owner_q.lower()).strip("_")
        i = 2
        while oid in oname:
            oid, i = f"{base}_{i}", i + 1
        owner = {"id": oid, "name": owner_q.strip(), "aliases": [owner_q.split()[0].lower()],
                 "added_at": datetime.now().isoformat(), "source": "reassign"}
        owners.append(owner)
        owners_doc["owners"] = owners
        of.write_text(json.dumps(owners_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    now = datetime.now().isoformat()
    for _q, u, r in picks:
        r["reassigned_from"] = r.get("owner_id")
        r["owner_id"] = owner["id"]
        r["set_at"] = now
        r["source"] = "reassign"
    rf.write_text(json.dumps(reps_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return True, (f"[{label}] moved {len(picks)} rep(s) to {owner['name']}: {summary} "
                  f"(old files in {backup.name}/)")


def _action_fixname(args: str) -> tuple[bool, str]:
    """Put the Slack sender's real name on ONE audit that went out with a
    misheard interviewer name, re-render its PDF and DM it to the rep. Dry run
    unless --apply. Scores untouched. (Tiffani Brown → "Sydney", 2026-11-23.)

      audit_bot_tool fixname Sydney_2026-11-23.md U0B9924FHCL [--apply]"""
    import os
    import subprocess
    root, rest, label = mc._audit_bot_root(shlex.split(args or ""))
    if len([a for a in rest if a != "--apply"]) != 2:
        return False, "usage: audit_bot_tool fixname [colten] <report.md> <SlackUserID> [--apply]"
    py = root / ".runtime" / "venv" / "bin" / "python"
    if not py.exists():
        return False, f"no bot venv at {py}"
    env = dict(os.environ)
    env["DYLD_FALLBACK_LIBRARY_PATH"] = "/opt/homebrew/lib:" + env.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    script = mc.REPO_ROOT / "automations" / "audit_bot" / "fix_name.py"
    r = subprocess.run([str(py), str(script), *rest], cwd=str(root / ".runtime"),
                       capture_output=True, text=True, timeout=300, env=env)
    out = (r.stdout + r.stderr).strip()
    return r.returncode == 0, f"[{label}] {out[-1500:]}"


def _action_ovreps(args: str) -> tuple[bool, str]:
    """READ-ONLY: an office's ACTIVE reps straight from OwnerVille (name +
    email), to work out which Slack account a rep is before `reassign`.
    Uses owner_rep_audit's roster reader; nothing is sent to anyone.

      audit_bot_tool ovreps 23751"""
    from automations.owner_rep_audit import roster
    offices = [a for a in (args or "").split() if a.isdigit()]
    if not offices:
        return False, "usage: audit_bot_tool ovreps <office number> [...]"
    lines = []
    for ro in roster.read_all(only=offices):
        lines.append(f"{ro.office} {ro.owner} ({ro.company}) — {ro.access}"
                     + (f": {ro.note}" if ro.note else ""))
        lines += [f"  {r.get('name', '')} | {r.get('email', '')}" for r in ro.reps]
    stem = mc._audit_bot_dump("ov", "reps-" + "-".join(offices), "\n".join(lines) + "\n")
    return bool(lines), f"{len(lines)} line(s) -> `logdump {stem}.log`"


_ACTIONS = {
    "ovreps": _action_ovreps,
    "reassign": _action_reassign,
    "regrade": _action_regrade,
    "fixname": _action_fixname,
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
