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
from collections import defaultdict
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


def _pdf(rec):
    """The audit's own PDF on disk, or "" (paths can be stale after the folder
    move -> fall back to reports/ by name, like daily_owner_digest)."""
    for key in ("report_pdf", "report_md"):
        v = rec.get(key)
        if not v:
            continue
        p = Path(v)
        if key == "report_pdf" and p.exists():
            return str(p)
        alt = scorecards.REPORTS_DIR / (p.stem + ".pdf")
        if alt.exists():
            return str(alt)
    return ""


# ---- who sent it (Raf 2026-11-21). The bot finds the sender by FILE NAME, last
# one wins. iPhone voice memos are named after where they were recorded
# ("5217 Tennyson Pkwy 6"), so two reps in the same office send files with the
# same name and one gets the other's recording: Algemar's interview showed up
# under Samajai ("Sosa sent two"), and Algemar wasn't on the list at all.
# The audio name carries the Slack message time (slack-<ts>_<micro>_<name>):
# among the files with that name, take the one uploaded at that moment.

SENT_WINDOW_SECONDS = 10 * 60


def _slack_files():
    """[{name, uid, created, share_ts}] from the bot's files.list, newest 2000."""
    try:
        from slack_watcher import web, _BOT_USER_ID
    except Exception:  # noqa: BLE001
        return None
    out, page = [], 1
    try:
        while page <= 10:
            res = web.files_list(count=200, page=page, types="all")
            files = res.get("files", []) or []
            if not files:
                break
            for f in files:
                uid = f.get("user")
                if not uid or uid == _BOT_USER_ID:
                    continue
                share_ts = set()
                for by_chan in (f.get("shares") or {}).values():
                    for posts in (by_chan or {}).values():
                        share_ts.update(str(p.get("ts")) for p in posts or [] if p.get("ts"))
                out.append({"name": f.get("name", "") or "", "uid": uid,
                            "created": f.get("created") or f.get("timestamp"),
                            "share_ts": share_ts})
            if page >= (res.get("paging") or {}).get("pages", 1):
                break
            page += 1
    except Exception:  # noqa: BLE001
        return None
    return out


def match_sender(audio, files):
    """(uid, how) for one slack-* audio name, or ("", why-not)."""
    m = re.match(r"^slack-(\d+)_(\d+)_(.+)$", audio or "")
    if not m:
        return "", "no slack time in the name"
    msg_ts = "%s.%s" % (m.group(1), m.group(2))
    sent = float(msg_ts)
    raw = m.group(3)
    stem = raw.rsplit(".", 1)[0] if "." in raw else raw
    names = {raw, raw.replace("_", " "), stem, stem.replace("_", " ")}
    by_share = {f["uid"] for f in files if msg_ts in f["share_ts"]}
    if len(by_share) == 1:
        return by_share.pop(), "message"
    def norm(n):
        n = n.rsplit(".", 1)[0] if "." in n else n
        return re.sub(r"[^a-z0-9]+", " ", n.lower()).strip()
    wanted = {norm(n) for n in names}
    same = [f for f in files if norm(f["name"]) in wanted]
    timed = [(abs(float(f["created"]) - sent), f["uid"]) for f in same if f.get("created")]
    timed = [t for t in timed if t[0] <= SENT_WINDOW_SECONDS]
    if timed:
        return min(timed)[1], "name + time"
    if len({f["uid"] for f in same}) == 1:
        return same[0]["uid"], "name"
    return "", ("%d senders share that name" % len({f["uid"] for f in same})) if same else "not in slack's list"


def fix_senders(recs, files):
    """Overwrite the bot's name-only guess with match_sender's. Returns the
    changes [(file, old uid, new uid, how)] so the run log shows them."""
    changes = []
    if files is None:
        return changes
    for r in recs:
        audio = r.get("audio_filename", "") or ""
        if not audio.startswith("slack-"):
            continue
        old = r.get("_uploader_user_id") or ""
        uid, how = match_sender(audio, files)
        if uid and uid != old:
            r["_uploader_user_id"] = uid
            changes.append((audio, old, uid, how))
        elif not uid and old and "share that name" in how:
            # several reps sent a file with this name and none was sent at this
            # time: the bot's guess is a coin flip - say "no name" instead
            r["_uploader_user_id"] = ""
            changes.append((audio, old, "", how))
    return changes


def _md(rec):
    """The audit's markdown on disk, or "" - bot_pdfs re-draws the scorecard
    from it with the sender's name."""
    v = rec.get("report_md")
    if not v:
        return ""
    p = Path(v)
    if p.exists():
        return str(p)
    alt = scorecards.REPORTS_DIR / p.name
    return str(alt) if alt.exists() else ""


def main():
    recs = scorecards._enrich_with_slack_uploaders(scorecards._load_all_completions())
    sender_changes = fix_senders(recs, _slack_files())
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
                         "file": audio, "fp": fp, "seconds": seconds, "pdf": _pdf(r),
                         "md": _md(r)})
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
        "sender_changes": sender_changes,
    }))


if __name__ == "__main__":
    main()
