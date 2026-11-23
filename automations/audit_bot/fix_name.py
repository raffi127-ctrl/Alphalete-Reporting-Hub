"""Fix the interviewer name on ONE saved 2nd-round audit and re-send the PDF
(Eve, 2026-11-23).

Gemini used to take the interviewer's name from the audio and sometimes
misheard it (Tiffani Brown's audit came out "Sydney"). audit.py now uses the
Slack sender; this fixes a report that already went out wrong:

  * puts the sender's real name in the Interviewer cell / title of the .md
  * re-renders the PDF from it (same file names on disk, so completions.jsonl
    and the scorecards keep pointing at it — they go by Slack ID anyway)
  * DMs the corrected PDF to the rep, named <Real_Name>_<date>.pdf
  * old .md/.pdf are copied to .runtime/backup-<stamp>/ first

Scores are NOT touched — no re-grade, no Gemini call.

    lucy rerun audit_bot_tool fixname Sydney_2026-11-23.md U0B9924FHCL           # dry run
    lucy rerun audit_bot_tool fixname Sydney_2026-11-23.md U0B9924FHCL --apply

Worker: runs in the bot's venv with cwd = .runtime (so slack_watcher / poster
import), started by tool.py's `fixname` action.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


def real_name(rt: Path, uid: str, web) -> str:
    """Roster full name → Slack profile real_name → roster first name."""
    info = {}
    try:
        info = json.loads((rt / "reps.json").read_text(encoding="utf-8")).get("reps", {}).get(uid) or {}
    except Exception:  # noqa: BLE001
        pass
    roster = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
    if len(roster.split()) >= 2:
        return roster
    try:
        real = (web.users_info(user=uid)["user"].get("profile", {}).get("real_name") or "").strip()
        if real:
            return real
    except Exception as e:  # noqa: BLE001
        print(f"Slack profile lookup failed: {type(e).__name__}: {e}")
    return roster


def force_interviewer(md: str, guessed: str, real: str) -> str:
    g = re.escape(guessed)
    md = re.sub(rf"^\|\s*{g}\s*\|", f"| {real} |", md, count=1, flags=re.MULTILINE)
    md = re.sub(rf"^(#\s+Audit\s+[—–-]\s+){g}(\s+[×x]\s+)", rf"\g<1>{real}\g<2>", md,
                count=1, flags=re.MULTILINE)
    return md


def main(argv: list) -> int:
    apply = "--apply" in argv
    args = [a for a in argv if a != "--apply"]
    if len(args) != 2 or "/" in args[0] or ".." in args[0]:
        print("usage: fix_name.py <report.md> <SlackUserID> [--apply]")
        return 2
    report, uid = args
    rt = Path.cwd()
    sys.path.insert(0, str(rt))
    from dotenv import load_dotenv
    load_dotenv(rt / ".env")
    from slack_watcher import web
    from poster import _parse_metadata, write_poster

    md_path = rt.parent / "reports" / report
    if not md_path.is_file():
        print(f"no such report: {md_path}")
        return 1
    md = md_path.read_text(encoding="utf-8")
    meta = _parse_metadata(md)
    guessed = (meta.get("interviewer") or "").strip()
    name = real_name(rt, uid, web)
    if not name:
        print(f"no name on file for {uid}")
        return 1
    new_md = force_interviewer(md, guessed, name)
    print(f"report: {report} | interviewer now '{guessed}' -> '{name}' | "
          f"applicant '{meta.get('applicant')}' | overall {meta.get('overall')}")
    if new_md == md:
        print("nothing to replace in the report — stopping")
        return 1
    if not apply:
        print("DRY RUN — add --apply to fix the report and DM the PDF")
        return 0

    backup = rt / f"backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    backup.mkdir()
    for p in (md_path, md_path.with_suffix(".pdf")):
        if p.exists():
            shutil.copy2(p, backup / p.name)
    md_path.write_text(new_md, encoding="utf-8")
    pdf = write_poster(md_path)
    if pdf.suffix != ".pdf":
        print(f"PDF render failed (got {pdf.name}) — report text fixed, nothing sent; old files in {backup.name}/")
        return 1
    date = re.search(r"\d{4}-\d{2}-\d{2}", report)
    nice = "_".join(name.split()) + (f"_{date.group(0)}" if date else "") + ".pdf"
    dm = web.conversations_open(users=uid)["channel"]["id"]
    web.files_upload_v2(
        channel=dm, file=str(pdf), filename=nice, title=nice,
        initial_comment=(f"Corrected audit — the name on your earlier PDF was wrong "
                         f"(it said {guessed}). Same scores, right name this time."),
    )
    print(f"fixed + sent {nice} to {uid} in {dm}; old files in {backup.name}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
