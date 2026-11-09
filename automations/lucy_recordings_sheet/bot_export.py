"""Runs INSIDE the 2nd-round audit bot's own venv, with cwd = the bot's
.runtime folder (Lucy 1: ~/2nd-rd-audits/.runtime). Prints one JSON blob on
stdout and changes nothing.

Why a separate process: who uploaded each recording is only known through the
bot's own Slack app (scorecards._enrich_with_slack_uploaders), and its token
lives in the bot's .env. Reusing the bot's code keeps these numbers identical
to the scorecard Raf already sees.

Keep this file stdlib + bot modules only - it is NOT run with the Hub's venv.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

try:
    from dotenv import load_dotenv
    load_dotenv(Path.cwd() / ".env")
except Exception:  # noqa: BLE001
    pass

import scorecards  # noqa: E402
from rosters import load_owners, load_reps  # noqa: E402


def _score(rec):
    md = rec.get("report_md")
    if not md:
        return None
    p = Path(md)
    if not p.exists():
        alt = scorecards.REPORTS_DIR / p.name
        if not alt.exists():
            return None
        p = alt
    return scorecards._extract_overall_score(p)


def _slack_name(uid, cache):
    if uid in cache:
        return cache[uid]
    name = ""
    try:
        from slack_watcher import web
        prof = web.users_info(user=uid)["user"].get("profile", {})
        name = (prof.get("real_name") or prof.get("display_name") or "").strip()
    except Exception:  # noqa: BLE001
        pass
    cache[uid] = name
    return name


# ---- what run.py's guard needs (Raf 2026-11-07: a recording sent twice, or a
# fake 2-minute one, must not count). Read-only, like everything here.

PROCESSED = Path.cwd().parent / "processed"
_FFPROBE = shutil.which("ffprobe") or next(
    (p for p in ("/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe") if Path(p).exists()), None)
_HASH_BYTES = 1024 * 1024


def _audio_facts(audio):
    """(fingerprint, seconds) of the audio in processed/, None for what we can't
    read. Fingerprint = size + first and last MB: the same file re-sent matches,
    and hashing every full recording daily would take too long."""
    p = PROCESSED / audio
    if not p.is_file():
        return None, None
    size = p.stat().st_size
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        h.update(fh.read(_HASH_BYTES))
        if size > _HASH_BYTES:
            fh.seek(max(size - _HASH_BYTES, _HASH_BYTES))
            h.update(fh.read(_HASH_BYTES))
    seconds = None
    if _FFPROBE:
        try:
            r = subprocess.run(
                [_FFPROBE, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
                capture_output=True, text=True, timeout=30, check=True)
            seconds = float(r.stdout.strip())
        except Exception:  # noqa: BLE001
            pass
    return "%d-%s" % (size, h.hexdigest()[:24]), seconds


def _report_length(rec):
    """Seconds from the report's own 'Length' cell - only when the audio is gone."""
    md = rec.get("report_md")
    if not md:
        return None
    p = Path(md)
    if not p.exists():
        p = scorecards.REPORTS_DIR / p.name
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    for row in re.findall(r"^\|(.+)\|$", text, flags=re.MULTILINE):
        cells = [c.strip() for c in row.split("|") if c.strip()]
        m = re.match(r"(\d{1,2}):(\d{2}):(\d{2})", cells[-1]) if len(cells) == 4 else None
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    return None


def main():
    recs = scorecards._enrich_with_slack_uploaders(scorecards._load_all_completions())
    reps = load_reps()
    out_recs, names = [], {}
    for r in recs:
        if r.get("rejected"):
            continue
        audio = r.get("audio_filename", "") or ""
        if not audio.startswith("slack-"):
            continue
        uid = r.get("_uploader_user_id") or ""
        fp, seconds = _audio_facts(audio)
        if seconds is None:
            seconds = _report_length(r)
        out_recs.append({"ts": r.get("ts", ""), "uid": uid, "score": _score(r),
                         "file": audio, "fp": fp, "seconds": seconds})
        if uid and uid not in names:
            info = reps.get(uid) or {}
            nm = f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
            if len(nm.split()) < 2:
                nm = _slack_name(uid, {}) or nm
            names[uid] = nm
    print(json.dumps({
        "records": out_recs,
        "reps": reps,
        "names": names,
        "owners": load_owners(),
    }))


if __name__ == "__main__":
    main()
