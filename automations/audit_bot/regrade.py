"""Silent regrade of past 2nd-round audits (Eve, 2026-11-13).

Raf's bot docked ~100 audits because the rep said their OWN office's company
name instead of "Alphalete". framework.py now says any company name is fine;
this re-runs those recordings through Gemini with the CURRENT framework and
writes the new grade NEXT TO the old one — nothing else:

  * does NOT touch reports/, processed/, completions.jsonl or the scorecard
  * does NOT post to Slack or DM anyone
  * new reports go to <bot>/regrade-<tag>/, and a summary TSV (old vs new
    scores) goes to output/logs/ so `logdump` can bring it to the laptop.

    lucy rerun audit_bot_tool regrade company_name     # starts it detached
    python -m automations.audit_bot.regrade <list.txt> [colten]   # the worker

The list is one saved report file name per line (reports/<name>.md).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCORE_ROW = re.compile(r"\|\s*(\d+)\s*/\s*5\s*\|\s*(\d+)\s*/\s*5\s*\|\s*(\d+)\s*/\s*7\s*\|\s*(\d+)\s*/\s*10\s*\|")


def scores(md: str) -> str:
    """'Posture/D2D/Pay/Overall' like '3/4/5/6', or '?' if the table is missing."""
    m = SCORE_ROW.search((md or "").replace("*", ""))  # Gemini sometimes bolds them
    return "/".join(m.groups()) if m else "?"


def overall(s: str) -> str:
    return s.split("/")[-1] if s != "?" else "?"


def _audio_for(report_name: str, completions: list, processed: Path) -> Path | None:
    """The recording behind a saved report: completions.jsonl maps report → audio
    name; the audio sits in processed/ (renamed name_2.ext on a collision, so
    take the candidate whose mtime is closest to the completion time)."""
    rec = next((r for r in reversed(completions)
                if Path(r.get("report_md") or "").name == report_name), None)
    if not rec:
        return None
    name = Path(rec.get("audio_filename") or "")
    if not name.name:
        return None
    cands = [p for p in processed.glob(f"{name.stem}*{name.suffix}")
             if p.stem == name.stem or re.fullmatch(re.escape(name.stem) + r"_\d+", p.stem)]
    if not cands:
        return None
    try:
        when = dt.datetime.fromisoformat(rec["ts"]).timestamp()
    except Exception:  # noqa: BLE001
        when = time.time()
    return min(cands, key=lambda p: abs(p.stat().st_mtime - when))


def grade(audit, audio: Path) -> str:
    """One Gemini pass with the bot's live framework. Returns the report markdown."""
    from google.genai import types
    upload = audio
    tmp = None
    if audio.suffix.lower() in audit.NEEDS_CONVERSION:
        import subprocess
        ffmpeg = audit._find_executable("ffmpeg", ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"])
        tmp = Path("/tmp") / f"regrade_{audio.stem}.mp3"
        subprocess.run([ffmpeg, "-y", "-i", str(audio), "-acodec", "libmp3lame",
                        "-ar", "16000", "-ac", "1", str(tmp)],
                       check=True, capture_output=True, timeout=180)
        upload = tmp
    try:
        str(upload).encode("ascii")
    except UnicodeEncodeError:
        import shutil
        safe = Path("/tmp") / ("regrade_" + "".join(c if ord(c) < 128 else "_" for c in upload.name))
        shutil.copy2(upload, safe)
        tmp, upload = safe, safe
    f = audit.client.files.upload(file=str(upload))
    try:
        deadline = time.time() + 300
        while f.state.name != "ACTIVE":
            if f.state.name == "FAILED" or time.time() > deadline:
                raise RuntimeError(f"Gemini file state {f.state.name}")
            time.sleep(3)
            f = audit.client.files.get(name=f.name)
        prompt = (f"Today's date: {dt.date.today():%Y-%m-%d}. The attached audio is a 2nd "
                  "round interview recording from one of Rafael Hidalgo's reps. Audit it "
                  "against the 11-frame framework in your system instructions and produce "
                  "the report in the exact format specified.")
        r = audit.client.models.generate_content(
            model=audit.MODEL, contents=[f, prompt],
            config=types.GenerateContentConfig(
                system_instruction=audit.FRAMEWORK + audit.grading_notes.as_prompt_addendum(),
                temperature=0.3, max_output_tokens=16384))
        return r.text or ""
    finally:
        try:
            audit.client.files.delete(name=f.name)
        except Exception:  # noqa: BLE001
            pass
        if tmp and tmp.exists():
            tmp.unlink()


def main(argv: list) -> int:
    if not argv:
        print("usage: python -m automations.audit_bot.regrade <list.txt> [colten]")
        return 2
    names = [ln.strip() for ln in Path(argv[0]).read_text(encoding="utf-8").splitlines()
             if ln.strip().endswith(".md")]
    label = "colten" if len(argv) > 1 and argv[1] == "colten" else "raf"
    root = Path.home() / ("2nd-rd-audits-colten" if label == "colten" else "2nd-rd-audits")
    rt = root / ".runtime"
    sys.path.insert(0, str(rt))
    import os
    os.chdir(rt)  # audit.py loads .env relative to its own folder; be safe
    import audit  # the bot's live module: same client, model, framework, notes

    tag = Path(argv[0]).stem
    out_dir = root / f"regrade-{tag}"
    out_dir.mkdir(exist_ok=True)
    summary = REPO_ROOT / "output" / "logs" / f"regrade-{label}-{tag}.tsv"
    summary.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if summary.exists():  # resumable: skip what's already in the summary
        done = {ln.split("\t")[0] for ln in summary.read_text(encoding="utf-8").splitlines()[1:]}
    else:
        summary.write_text("report\told P/D/Pay/Overall\tnew P/D/Pay/Overall\told overall\tnew overall\tnote\n",
                           encoding="utf-8")
    completions = []
    for ln in (rt / "completions.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            completions.append(json.loads(ln))
        except Exception:  # noqa: BLE001
            pass

    for i, name in enumerate(names, 1):
        if name in done:
            continue
        old_md = (root / "reports" / name)
        old = scores(old_md.read_text(encoding="utf-8", errors="replace")) if old_md.exists() else "?"
        audio = _audio_for(name, completions, root / "processed")
        new, note = "?", ""
        if audio is None:
            note = "recording not found"
        else:
            try:
                md = grade(audit, audio)
                (out_dir / name).write_text(md, encoding="utf-8")
                new = scores(md)
                note = audio.name
            except Exception as e:  # noqa: BLE001
                note = f"FAILED: {str(e)[:150]}"
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"{name}\t{old}\t{new}\t{overall(old)}\t{overall(new)}\t{note}\n")
        print(f"[{i}/{len(names)}] {name}: {old} -> {new} {note}", flush=True)
        time.sleep(2)
    print(f"DONE -> {summary.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
