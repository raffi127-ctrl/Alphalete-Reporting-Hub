#!/usr/bin/env python3
"""
2nd Round Interview Auditor.

Usage:
    python audit.py path/to/recording.m4a   # one-shot
    python audit.py --watch                  # watch inbox/ forever

Drops a markdown report in ../reports/ and moves the audio to ../processed/.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from framework import FRAMEWORK
import grading_notes
from poster import write_poster, _parse_metadata

# ---------- paths ----------

RUNTIME_DIR = Path(__file__).parent.resolve()
ROOT = RUNTIME_DIR.parent
INBOX = ROOT / "inbox"
PROCESSED = ROOT / "processed"
REPORTS = ROOT / "reports"
REJECTED = RUNTIME_DIR / "rejected"

# A real 2nd round is 30–60 min. Anything under 5 min can't possibly contain
# the 11 frames — Gemini will hallucinate timestamps and quotes (see Gabe Perez
# 12-sec clip → fake 13-min audit, 2026-06-22). Reject before audit.
MIN_DURATION_SECONDS = 5 * 60
# After Gemini returns, sanity-check its reported length + timestamps against
# the real file duration. If Gemini claims much longer OR quotes timestamps
# beyond the real audio, the report is hallucinated.
MAX_LENGTH_INFLATION_RATIO = 1.5
MAX_TIMESTAMP_OVERSHOOT_RATIO = 1.1

AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".mp4", ".mov", ".aac", ".flac", ".ogg", ".webm", ".amr", ".3gp", ".3gpp"}

# Formats Gemini's File API doesn't accept directly — we convert these to MP3
# in a temp dir before uploading. The original audio stays untouched.
NEEDS_CONVERSION = {".mov", ".amr", ".3gp", ".3gpp"}

# ---------- config ----------

load_dotenv(RUNTIME_DIR / ".env")
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")

if not API_KEY:
    sys.exit("ERROR: GEMINI_API_KEY missing from .env")

client = genai.Client(api_key=API_KEY)

# Gemini 2.5 Pro pricing (paid tier; $0 on free tier). Update if model changes.
PRICE_INPUT_PER_MILLION = 1.25   # ≤200K tokens
PRICE_OUTPUT_PER_MILLION = 10.00  # ≤200K tokens
SPEND_LOG = RUNTIME_DIR / "spend.json"
COMPLETIONS_LOG = RUNTIME_DIR / "completions.jsonl"

# ---------- helpers ----------

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _find_executable(name: str, common_paths: list[str]) -> str | None:
    """Find an executable on PATH or in common Homebrew locations."""
    found = shutil.which(name)
    if found:
        return found
    for candidate in common_paths:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def mac_notify(title: str, message: str) -> None:
    """Fire a macOS notification (best-effort).

    Prefers terminal-notifier (more reliable, clearer sender label).
    Falls back to osascript if terminal-notifier isn't installed.
    Uses absolute paths because the watcher runs under nohup with a stripped PATH.
    """
    tn = _find_executable(
        "terminal-notifier",
        ["/opt/homebrew/bin/terminal-notifier", "/usr/local/bin/terminal-notifier"],
    )
    if tn:
        try:
            result = subprocess.run(
                [
                    tn,
                    "-title", "Interview Audit",
                    "-subtitle", title,
                    "-message", message,
                    "-sound", "Glass",
                    "-group", "interview-audit",
                ],
                check=False,
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                log(f"terminal-notifier exit {result.returncode}: {result.stderr.decode().strip()}")
            else:
                return
        except Exception as e:
            log(f"terminal-notifier raised, falling back to osascript: {e}")
    else:
        log("terminal-notifier not found, using osascript")

    # Fallback: osascript
    osa = _find_executable("osascript", ["/usr/bin/osascript"])
    if not osa:
        log("osascript not found either — no notification fired")
        return
    try:
        safe_title = title.replace('"', '\\"')
        safe_msg = message.replace('"', '\\"')
        script = f'display notification "{safe_msg}" with title "{safe_title}" sound name "Glass"'
        subprocess.run([osa, "-e", script], check=False, capture_output=True)
    except Exception as e:
        log(f"notify failed (non-fatal): {e}")


def safe_stem(path: Path) -> str:
    """Filesystem-safe stem for naming the report."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in path.stem)


def _record_spend(input_tokens: int, output_tokens: int) -> dict:
    """Calculate cost for this audit and append to the running daily spend log.
    Returns a dict with today's cumulative totals so we can log them."""
    cost = (
        input_tokens * PRICE_INPUT_PER_MILLION / 1_000_000
        + output_tokens * PRICE_OUTPUT_PER_MILLION / 1_000_000
    )

    today = datetime.now().strftime("%Y-%m-%d")
    try:
        data = json.loads(SPEND_LOG.read_text()) if SPEND_LOG.exists() else {}
    except Exception:
        data = {}

    day = data.setdefault(today, {"audits": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    day["audits"] += 1
    day["input_tokens"] += int(input_tokens)
    day["output_tokens"] += int(output_tokens)
    day["cost_usd"] = round(day["cost_usd"] + cost, 4)

    try:
        SPEND_LOG.write_text(json.dumps(data, indent=2, sort_keys=True))
    except Exception as e:
        log(f"  spend log write failed (non-fatal): {e}")

    return {
        "this_audit_cost": round(cost, 4),
        "today_audits": day["audits"],
        "today_cost": round(day["cost_usd"], 4),
    }


def already_processed(audio_path: Path) -> bool:
    """Has this exact file (same name AND same size) already been moved into
    processed/? Size-aware so the iPhone's repeated default names ('New
    Recording 3.m4a') don't trip the dupe check on different recordings."""
    target = PROCESSED / audio_path.name
    if not target.exists():
        return False
    try:
        return target.stat().st_size == audio_path.stat().st_size
    except OSError:
        return False


# ---------- audit ----------

def _ffprobe_duration(audio_path: Path) -> float | None:
    """Return audio duration in seconds via ffprobe, or None if unparseable."""
    ffprobe = _find_executable("ffprobe", ["/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe"])
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, OSError):
        return None


def _parse_length_cell_seconds(report_md: str) -> float | None:
    """Find the 'Length' value in the report's metadata table (HH:MM:SS)."""
    import re as _re
    for row in _re.findall(r"^\|(.+)\|$", report_md, flags=_re.MULTILINE):
        cells = [c.strip() for c in row.split("|") if c.strip()]
        if len(cells) == 4 and _re.match(r"\d{1,2}:\d{2}:\d{2}", cells[-1]):
            parts = cells[-1].split(":")
            try:
                h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                return h * 3600 + m * 60 + s
            except ValueError:
                continue
    return None


def _max_timestamp_seconds(report_md: str) -> float:
    """Find the largest `@ MM:SS` (or `@ HH:MM:SS`) timestamp referenced in the report."""
    import re as _re
    max_sec = 0.0
    for m in _re.finditer(r"@\s*(\d{1,2}:\d{2}(?::\d{2})?)", report_md):
        parts = m.group(1).split(":")
        try:
            if len(parts) == 2:
                sec = int(parts[0]) * 60 + int(parts[1])
            else:
                sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            max_sec = max(max_sec, sec)
        except ValueError:
            continue
    return max_sec


def _write_rejection(audio_path: Path, reason: str, **extras) -> None:
    """Write a rejection record to completions.jsonl + move audio to rejected/."""
    REJECTED.mkdir(parents=True, exist_ok=True)
    target = REJECTED / audio_path.name
    counter = 2
    while target.exists():
        target = REJECTED / f"{audio_path.stem}_{counter}{audio_path.suffix}"
        counter += 1
    try:
        audio_path.rename(target)
    except OSError as e:
        log(f"  failed to move rejected file: {e}")
    record = {
        "ts": datetime.now().isoformat(),
        "audio_filename": audio_path.name,
        "rejected": True,
        "reason": reason,
        "report_md": None,
        "report_pdf": None,
        **extras,
    }
    try:
        with open(COMPLETIONS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as e:
        log(f"  rejection log write failed: {e}")


# ---------- unreadable recordings ----------
#
# 2026-10-19: a WhatsApp export Gemini couldn't open sat in inbox/ all night.
# audit_file() returned None and left it there, the watcher went quiet, and the
# heartbeat killed + restarted it every ~10 min — each restart re-tried the same
# file. Now an unreadable file is moved to rejected/ (never deleted) and the rep
# gets ONE plain reply telling them what to send instead (wording approved by
# Megan, 2026-10-20). Deliberately NOT written to completions.jsonl, so
# slack_watcher's own rejection replies can't double-post.

UNREADABLE_REPLY = (
    ":studio_microphone: *I couldn't open this recording, so there's no audit yet.*\n\n"
    "Please send it again as one of these:\n"
    ":white_check_mark: A *Voice Memo* from your iPhone\n"
    ":white_check_mark: An *.m4a*, *.mp3* or *.wav* file\n\n"
    ":x: WhatsApp audio doesn't work.\n\n"
    "Just upload the new file here and I'll start the audit."
)
UNREADABLE_LOG = RUNTIME_DIR / "unreadable.jsonl"


def _slack_key(audio_path: Path) -> str | None:
    """'slack-1790092430_000400_WhatsApp_….mp4' -> 'slack-1790092430_000400'
    (the slack_pending.json key slack_watcher writes on download)."""
    parts = audio_path.name.split("_")
    if not audio_path.name.startswith("slack-") or len(parts) < 2:
        return None
    return f"{parts[0]}_{parts[1]}"


def _reply_unreadable(audio_path: Path) -> str:
    """Post UNREADABLE_REPLY in the thread the recording came from. Best-effort:
    returns what happened, never raises."""
    key = _slack_key(audio_path)
    if not key:
        return "not a Slack upload — no reply"
    try:
        pending = json.loads((RUNTIME_DIR / "slack_pending.json").read_text())
        dest = pending[key]
    except Exception as e:  # noqa: BLE001
        return f"no Slack thread on file for {key} ({type(e).__name__})"
    try:
        sys.path.insert(0, str(RUNTIME_DIR))
        from slack_watcher import web  # same client heartbeat.py uses
        web.chat_postMessage(channel=dest["channel"], thread_ts=dest.get("thread_ts"),
                             text=UNREADABLE_REPLY)
        return f"replied in {dest['channel']}"
    except Exception as e:  # noqa: BLE001
        return f"reply failed: {type(e).__name__}: {e}"


def _reject_unreadable(audio_path: Path, why: str) -> None:
    """Move an unreadable recording out of inbox/ into rejected/ and tell the rep."""
    REJECTED.mkdir(parents=True, exist_ok=True)
    target = REJECTED / audio_path.name
    counter = 2
    while target.exists():
        target = REJECTED / f"{audio_path.stem}_{counter}{audio_path.suffix}"
        counter += 1
    try:
        audio_path.rename(target)
        moved = f"moved to rejected/{target.name}"
    except OSError as e:
        moved = f"move FAILED: {e}"
    replied = _reply_unreadable(audio_path)
    log(f"  UNREADABLE ({why}): {moved}; {replied}")
    try:
        with open(UNREADABLE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now().isoformat(),
                                "audio_filename": audio_path.name, "why": why,
                                "moved": moved, "replied": replied}) + "\n")
    except OSError:
        pass


def audit_file(audio_path: Path) -> Path | None:
    """Run one audit. Returns path to the report, or None on failure."""

    if not audio_path.exists():
        log(f"file not found: {audio_path}")
        return None

    if audio_path.suffix.lower() not in AUDIO_EXTS:
        log(f"skipping non-audio file: {audio_path.name}")
        return None

    log(f"auditing: {audio_path.name} ({audio_path.stat().st_size / 1024 / 1024:.1f} MB)")

    # GATE 1: minimum duration. Gemini hallucinates timestamps/quotes when given
    # a clip too short to actually contain a 2nd round.
    duration = _ffprobe_duration(audio_path)
    if duration is None:
        log(f"  WARN: couldn't read audio duration with ffprobe — proceeding anyway")
    elif duration < MIN_DURATION_SECONDS:
        log(f"  REJECTED: audio is only {duration:.0f}s "
            f"(< {MIN_DURATION_SECONDS}s min). Won't audit — Gemini would hallucinate.")
        _write_rejection(
            audio_path,
            reason="too_short",
            actual_duration_sec=round(duration, 1),
            min_required_sec=MIN_DURATION_SECONDS,
        )
        return None

    # 1a. Convert format if Gemini doesn't accept it natively
    upload_path = audio_path
    temp_converted = None
    if audio_path.suffix.lower() in NEEDS_CONVERSION:
        log(f"  converting {audio_path.suffix} → .mp3 for Gemini compatibility")
        temp_converted = Path("/tmp") / f"{audio_path.stem}_converted.mp3"
        ffmpeg = _find_executable("ffmpeg", ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"])
        if not ffmpeg:
            log("  ffmpeg not found — cannot convert")
            mac_notify("Audit FAILED", f"{audio_path.name} — ffmpeg missing, can't convert")
            return None
        try:
            subprocess.run(
                [ffmpeg, "-y", "-i", str(audio_path),
                 "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1",
                 str(temp_converted)],
                check=True,
                capture_output=True,
                timeout=120,
            )
            upload_path = temp_converted
            log(f"  converted: {temp_converted} ({temp_converted.stat().st_size / 1024 / 1024:.1f} MB)")
        except Exception as e:
            log(f"  conversion failed: {e}")
            mac_notify("Audit FAILED", f"{audio_path.name} — format conversion error")
            _reject_unreadable(audio_path, "conversion failed")
            return None

    # 1b. Sanitize filename if it has non-ASCII (Gemini SDK breaks on those)
    upload_via_temp = None
    try:
        str(upload_path).encode("ascii")
    except UnicodeEncodeError:
        # Re-encode the filename to ASCII-safe, copy to /tmp, upload from there
        safe_name = "".join(c if ord(c) < 128 else "_" for c in upload_path.name)
        upload_via_temp = Path("/tmp") / f"upload_{safe_name}"
        try:
            import shutil as _sh
            _sh.copy2(str(upload_path), str(upload_via_temp))
            log(f"  filename had non-ASCII chars — uploading via {upload_via_temp.name}")
            upload_path = upload_via_temp
        except Exception as e:
            log(f"  sanitization copy failed: {e}")

    # 1c. Upload audio
    log("uploading to Gemini File API...")
    try:
        uploaded = client.files.upload(file=str(upload_path))
    except Exception as e:
        log(f"upload failed: {e}")
        mac_notify("Audit FAILED", f"{audio_path.name} — upload error")
        if temp_converted and temp_converted.exists():
            temp_converted.unlink(missing_ok=True)
        if upload_via_temp and upload_via_temp.exists():
            upload_via_temp.unlink(missing_ok=True)
        return None

    # 2. Wait for file to become ACTIVE
    log(f"  uploaded as {uploaded.name}, waiting for ACTIVE state...")
    deadline = time.time() + 300  # 5 min
    while uploaded.state.name != "ACTIVE":
        if time.time() > deadline:
            log("file never reached ACTIVE state — bailing")
            mac_notify("Audit FAILED", f"{audio_path.name} — file processing timeout")
            return None
        if uploaded.state.name == "FAILED":
            log("Gemini reports file FAILED to process")
            mac_notify("Audit FAILED", f"{audio_path.name} — Gemini couldn't process audio")
            if temp_converted and temp_converted.exists():
                temp_converted.unlink(missing_ok=True)
            if upload_via_temp and upload_via_temp.exists():
                upload_via_temp.unlink(missing_ok=True)
            _reject_unreadable(audio_path, "Gemini could not process it")
            return None
        time.sleep(3)
        uploaded = client.files.get(name=uploaded.name)

    log(f"  file ACTIVE — running audit")

    # 3. Generate content
    today = datetime.now().strftime("%Y-%m-%d")
    user_prompt = (
        f"Today's date: {today}. The attached audio is a 2nd round interview "
        f"recording from one of Rafael Hidalgo's reps. Audit it against the "
        f"11-frame framework in your system instructions and produce the report "
        f"in the exact format specified."
    )

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=[uploaded, user_prompt],
            config=types.GenerateContentConfig(
                system_instruction=FRAMEWORK + grading_notes.as_prompt_addendum(),
                temperature=0.3,
                max_output_tokens=16384,
            ),
        )
    except Exception as e:
        log(f"generation failed: {e}")
        mac_notify("Audit FAILED", f"{audio_path.name} — Gemini API error")
        # Clean up uploaded file
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass
        return None

    report_md = response.text or ""
    if not report_md.strip():
        log("Gemini returned empty response")
        mac_notify("Audit FAILED", f"{audio_path.name} — empty response")
        return None

    # GATE 2: hallucination check. If Gemini claims a much longer interview than
    # the actual file, or quotes timestamps past the end, the report is fake.
    if duration is not None:
        claimed = _parse_length_cell_seconds(report_md)
        max_ts = _max_timestamp_seconds(report_md)
        hallucinated_reason = None
        if claimed and claimed > duration * MAX_LENGTH_INFLATION_RATIO:
            hallucinated_reason = (
                f"claimed_length_{int(claimed)}s_vs_actual_{int(duration)}s"
            )
        elif max_ts > duration * MAX_TIMESTAMP_OVERSHOOT_RATIO and max_ts > duration + 30:
            hallucinated_reason = (
                f"max_timestamp_{int(max_ts)}s_past_actual_{int(duration)}s"
            )
        if hallucinated_reason:
            log(f"  REJECTED: hallucinated report — {hallucinated_reason}")
            _write_rejection(
                audio_path,
                reason="hallucinated",
                actual_duration_sec=round(duration, 1),
                claimed_duration_sec=claimed,
                max_referenced_timestamp_sec=max_ts,
                detail=hallucinated_reason,
            )
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass
            return None

    # Record spend (uses real token counts from Gemini's usage_metadata)
    try:
        usage = getattr(response, "usage_metadata", None)
        if usage:
            in_tok = getattr(usage, "prompt_token_count", 0) or 0
            out_tok = getattr(usage, "candidates_token_count", 0) or 0
            spend = _record_spend(in_tok, out_tok)
            log(
                f"  cost: ${spend['this_audit_cost']:.4f} "
                f"(in: {in_tok:,} tok, out: {out_tok:,} tok)  "
                f"|  today: {spend['today_audits']} audit(s), ${spend['today_cost']:.4f}"
            )
    except Exception as e:
        log(f"  spend log failed (non-fatal): {e}")

    # 4. Save report — name it after the interviewer + date.
    #    If Gemini couldn't ID the interviewer, fall back to the audio filename
    #    so we don't end up with "Rep_Name_*" or "Unknown_*" reports.
    REPORTS.mkdir(parents=True, exist_ok=True)
    meta = _parse_metadata(report_md)
    interviewer = (meta.get("interviewer") or "").strip()

    # Treat these as "unidentified" — fall back to the audio filename stem.
    placeholder_names = {
        "", "unknown", "unknown rep", "rep", "rep name", "the rep",
        "interviewer", "name", "[name]", "[rep name]",
    }
    if interviewer.lower() in placeholder_names:
        base_stub = safe_stem(audio_path)
        log(f"  interviewer not identified — using audio filename: {base_stub}")
    else:
        base_stub = "".join(c if c.isalnum() else "_" for c in interviewer).strip("_")
        if not base_stub:
            base_stub = safe_stem(audio_path)

    base_name = f"{base_stub}_{today}"
    report_path = REPORTS / f"{base_name}.md"
    counter = 2
    while report_path.exists():
        report_path = REPORTS / f"{base_name}_{counter}.md"
        counter += 1

    report_path.write_text(report_md, encoding="utf-8")
    log(f"  report saved: {report_path}")

    # 4b. Generate the styled HTML poster alongside
    try:
        html_path = write_poster(report_path)
        log(f"  poster saved: {html_path}")
    except Exception as e:
        log(f"  poster generation failed (non-fatal): {e}")

    # 5. Move audio to processed/
    PROCESSED.mkdir(parents=True, exist_ok=True)
    target = PROCESSED / audio_path.name
    counter = 2
    while target.exists():
        target = PROCESSED / f"{audio_path.stem}_{counter}{audio_path.suffix}"
        counter += 1
    audio_path.rename(target)
    log(f"  audio moved to: {target}")

    # 6. Clean up uploaded file from Gemini (48hr TTL anyway, but tidy)
    try:
        client.files.delete(name=uploaded.name)
    except Exception:
        pass

    # 6b. Clean up local temp-converted MP3 (if we made one)
    if temp_converted and temp_converted.exists():
        try:
            temp_converted.unlink()
        except Exception:
            pass

    # 6c. Clean up ASCII-sanitized upload copy (if we made one)
    if upload_via_temp and upload_via_temp.exists():
        try:
            upload_via_temp.unlink()
        except Exception:
            pass

    # 7. Append completion record for downstream watchers (e.g., Slack bot)
    try:
        pdf_candidate = report_path.with_suffix(".pdf")
        record = {
            "ts": datetime.now().isoformat(),
            "audio_filename": audio_path.name,
            "report_md": str(report_path),
            "report_pdf": str(pdf_candidate) if pdf_candidate.exists() else None,
        }
        with open(COMPLETIONS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        log(f"completion log write failed (non-fatal): {e}")

    # 8. Notify
    mac_notify("Audit complete", f"{audio_path.name} → reports/{report_path.name}")

    return report_path


# ---------- watch mode ----------

class InboxHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        # Files we're currently processing (or just processed) to avoid double-fires
        self.seen: set[str] = set()

    def _handle(self, path_str: str) -> None:
        path = Path(path_str)
        if path.suffix.lower() not in AUDIO_EXTS:
            return
        if path.name in self.seen:
            return
        if not path.exists():
            return
        if already_processed(path):
            log(f"skipping (already in processed/): {path.name}")
            self.seen.add(path.name)
            return

        # Wait for the file to finish writing (size stable for 2 sec)
        log(f"detected new file: {path.name} — waiting for write to settle")
        last_size = -1
        stable_checks = 0
        for _ in range(60):  # max 60 seconds wait
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                return
            if size == last_size and size > 0:
                stable_checks += 1
                if stable_checks >= 2:
                    break
            else:
                stable_checks = 0
            last_size = size
            time.sleep(1)

        self.seen.add(path.name)
        try:
            audit_file(path)
        except Exception as e:
            log(f"audit threw unexpectedly: {e}")
            mac_notify("Audit CRASHED", f"{path.name} — {e}")

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(event.dest_path)


def watch_inbox() -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    log(f"watching {INBOX} for new audio files...")
    log("drop .m4a / .mp3 / .wav files in there and reports will appear in ../reports/")

    # Process anything already sitting in inbox/ on startup
    for existing in sorted(INBOX.iterdir()):
        if existing.is_file() and existing.suffix.lower() in AUDIO_EXTS:
            log(f"found existing file in inbox: {existing.name}")
            try:
                audit_file(existing)
            except Exception as e:
                log(f"existing-file audit threw: {e}")

    handler = InboxHandler()
    observer = Observer()
    observer.schedule(handler, str(INBOX), recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        log("shutting down watcher")
        observer.stop()
    observer.join()


# ---------- entry point ----------

def main() -> None:
    parser = argparse.ArgumentParser(description="Audit 2nd round interview recordings.")
    parser.add_argument("file", nargs="?", help="Audio file to audit (one-shot mode)")
    parser.add_argument("--watch", action="store_true", help="Watch inbox/ forever")
    args = parser.parse_args()

    if args.watch:
        import socket as _socket, zlib as _zlib  # SOCKET SINGLETON
        _singleton_sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        try:
            _singleton_sock.bind(("127.0.0.1", 41000 + (_zlib.crc32(str(RUNTIME_DIR).encode()) % 5000)))
        except OSError:
            print("[audit] another audit --watch already running -- exiting", flush=True)
            raise SystemExit(0)
        watch_inbox()
    elif args.file:
        path = Path(args.file).expanduser().resolve()
        report = audit_file(path)
        if report:
            print(f"\nDone: {report}")
        else:
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
