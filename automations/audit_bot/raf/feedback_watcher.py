#!/usr/bin/env python3
"""
Feedback watcher — sister to audit.py.

Watches ~/Documents/2nd-rd-audits/feedback_inbox/ for audio/video files. When
one lands, transcribes it locally with whisper-cli (free, no API cost) and
saves the transcript as a markdown file in ~/Documents/2nd-rd-audits/feedback/.

Usage:
    python feedback_watcher.py --watch
    python feedback_watcher.py path/to/feedback.m4a
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ---------- paths ----------

RUNTIME_DIR = Path(__file__).parent.resolve()
ROOT = RUNTIME_DIR.parent
INBOX = ROOT / "feedback_inbox"
PROCESSED = ROOT / "feedback_inbox" / ".processed"
TRANSCRIPTS = ROOT / "feedback"

AUDIO_VIDEO_EXTS = {
    ".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".amr",
    ".mp4", ".mov", ".m4v", ".webm", ".3gp",
}

# Already-transcribed formats — we just wrap and save these, no Whisper needed.
TEXT_EXTS = {".srt", ".vtt", ".txt"}

PROCESSABLE_EXTS = AUDIO_VIDEO_EXTS | TEXT_EXTS

WHISPER_MODEL = Path.home() / ".whisper-models" / "ggml-small.en.bin"

# ---------- helpers ----------

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _find(name: str, common: list[str]) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for p in common:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def mac_notify(title: str, message: str) -> None:
    """Fire macOS notification."""
    tn = _find("terminal-notifier", ["/opt/homebrew/bin/terminal-notifier"])
    if tn:
        try:
            subprocess.run(
                [tn, "-title", "Interview Audit", "-subtitle", title,
                 "-message", message, "-sound", "Pop",
                 "-group", "interview-feedback"],
                check=False, capture_output=True, timeout=5,
            )
            return
        except Exception:
            pass
    osa = _find("osascript", ["/usr/bin/osascript"])
    if osa:
        try:
            script = f'display notification "{message}" with title "{title}" sound name "Pop"'
            subprocess.run([osa, "-e", script], check=False, capture_output=True)
        except Exception:
            pass


def safe_stem(path: Path) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in path.stem)


# ---------- transcription ----------

def _strip_srt_to_text(srt_content: str) -> str:
    """Strip SRT timing/numbering, leaving just spoken text."""
    import re
    lines = srt_content.splitlines()
    out = []
    for line in lines:
        stripped = line.strip()
        # Skip cue numbers
        if stripped.isdigit():
            continue
        # Skip timing lines (e.g., 00:00:01,000 --> 00:00:04,000)
        if "-->" in stripped:
            continue
        # Skip blank lines
        if not stripped:
            continue
        out.append(stripped)
    return " ".join(out)


def _handle_text_file(text_path: Path) -> Path | None:
    """Read a .srt/.vtt/.txt file and wrap as feedback markdown."""
    log(f"text feedback: {text_path.name}")
    try:
        raw = text_path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception as e:
        log(f"  read failed: {e}")
        return None

    ext = text_path.suffix.lower()
    if ext in (".srt", ".vtt"):
        body = _strip_srt_to_text(raw)
    else:
        body = raw

    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    stem = safe_stem(text_path)
    out_path = TRANSCRIPTS / f"{today}_{stem}.md"
    counter = 2
    while out_path.exists():
        out_path = TRANSCRIPTS / f"{today}_{stem}_{counter}.md"
        counter += 1

    md = f"""# Feedback — {text_path.name}
**Recorded:** {datetime.fromtimestamp(text_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}
**Transcribed:** {datetime.now().strftime("%Y-%m-%d %H:%M")}
**Source:** `{text_path}` (pre-transcribed {ext})

---

{body}
"""
    out_path.write_text(md, encoding="utf-8")
    log(f"  saved: {out_path}")

    # Archive original
    PROCESSED.mkdir(parents=True, exist_ok=True)
    archive = PROCESSED / text_path.name
    counter = 2
    while archive.exists():
        archive = PROCESSED / f"{text_path.stem}_{counter}{text_path.suffix}"
        counter += 1
    try:
        text_path.rename(archive)
    except Exception as e:
        log(f"  archive failed: {e}")

    mac_notify("Feedback ready", f"{text_path.name} → feedback/{out_path.name}")
    return out_path


def transcribe(media_path: Path) -> Path | None:
    """Transcribe media to a markdown file. Dispatches:
    - .srt/.vtt/.txt → wrap as-is (no Whisper needed)
    - audio/video → Whisper local
    Returns the path to the transcript or None on failure."""

    if not media_path.exists():
        log(f"file not found: {media_path}")
        return None

    ext = media_path.suffix.lower()
    if ext in TEXT_EXTS:
        return _handle_text_file(media_path)

    if ext not in AUDIO_VIDEO_EXTS:
        log(f"skipping non-media file: {media_path.name}")
        return None

    log(f"transcribing: {media_path.name} ({media_path.stat().st_size / 1024 / 1024:.1f} MB)")

    whisper = _find("whisper-cli", ["/opt/homebrew/bin/whisper-cli"])
    ffmpeg = _find("ffmpeg", ["/opt/homebrew/bin/ffmpeg"])

    if not whisper:
        log("whisper-cli not found")
        mac_notify("Feedback FAILED", f"{media_path.name} — whisper-cli missing")
        return None

    if not WHISPER_MODEL.exists():
        log(f"whisper model not found at {WHISPER_MODEL}")
        mac_notify("Feedback FAILED", f"{media_path.name} — whisper model missing")
        return None

    # Step 1: convert to 16kHz mono wav (Whisper's required input format)
    if not ffmpeg:
        log("ffmpeg not found — can't prep audio for whisper")
        mac_notify("Feedback FAILED", f"{media_path.name} — ffmpeg missing")
        return None

    temp_wav = Path("/tmp") / f"{safe_stem(media_path)}_feedback.wav"
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", str(media_path),
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
             str(temp_wav)],
            check=True, capture_output=True, timeout=300,
        )
    except Exception as e:
        log(f"  ffmpeg failed: {e}")
        mac_notify("Feedback FAILED", f"{media_path.name} — ffmpeg conversion")
        return None

    log(f"  converted to wav, running whisper...")

    # Step 2: whisper-cli transcribe to plain text
    temp_txt_base = Path("/tmp") / f"{safe_stem(media_path)}_feedback"
    try:
        result = subprocess.run(
            [whisper, "-m", str(WHISPER_MODEL),
             "-f", str(temp_wav),
             "-otxt", "-of", str(temp_txt_base),
             "-l", "en"],
            check=True, capture_output=True, timeout=600,
        )
    except subprocess.CalledProcessError as e:
        log(f"  whisper failed: {e.stderr.decode()[:500]}")
        mac_notify("Feedback FAILED", f"{media_path.name} — whisper")
        return None
    except Exception as e:
        log(f"  whisper failed: {e}")
        mac_notify("Feedback FAILED", f"{media_path.name} — whisper")
        return None

    txt_path = Path(str(temp_txt_base) + ".txt")
    if not txt_path.exists():
        log(f"  whisper didn't produce a transcript at {txt_path}")
        mac_notify("Feedback FAILED", f"{media_path.name} — no transcript")
        return None

    transcript_text = txt_path.read_text(encoding="utf-8").strip()
    log(f"  transcribed: {len(transcript_text)} chars")

    # Step 3: save as markdown
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    stem = safe_stem(media_path)
    out_path = TRANSCRIPTS / f"{today}_{stem}.md"
    counter = 2
    while out_path.exists():
        out_path = TRANSCRIPTS / f"{today}_{stem}_{counter}.md"
        counter += 1

    md = f"""# Feedback — {media_path.name}
**Recorded:** {datetime.fromtimestamp(media_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}
**Transcribed:** {datetime.now().strftime("%Y-%m-%d %H:%M")}
**Source:** `{media_path}`

---

{transcript_text}
"""
    out_path.write_text(md, encoding="utf-8")
    log(f"  saved: {out_path}")

    # Step 4: archive original (don't delete in case user wants the raw audio)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    archive = PROCESSED / media_path.name
    counter = 2
    while archive.exists():
        archive = PROCESSED / f"{media_path.stem}_{counter}{media_path.suffix}"
        counter += 1
    try:
        media_path.rename(archive)
    except Exception as e:
        log(f"  archive failed: {e}")

    # Cleanup temp files
    for p in [temp_wav, txt_path]:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass

    mac_notify("Feedback ready", f"{media_path.name} → feedback/{out_path.name}")
    return out_path


# ---------- watch mode ----------

class FeedbackHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self.seen: set[str] = set()

    def _handle(self, path_str: str) -> None:
        path = Path(path_str)
        if path.suffix.lower() not in PROCESSABLE_EXTS:
            return
        if path.name in self.seen:
            return
        if not path.exists():
            return
        # Wait for write to settle
        log(f"detected new file: {path.name} — waiting for write to settle")
        last_size = -1
        stable = 0
        for _ in range(60):
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                return
            if size == last_size and size > 0:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
            last_size = size
            time.sleep(1)
        self.seen.add(path.name)
        try:
            transcribe(path)
        except Exception as e:
            log(f"transcribe threw: {e}")

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(event.dest_path)


def watch_inbox() -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    log(f"watching {INBOX} for new feedback recordings...")
    log("drop audio/video files in there → transcript appears in ../feedback/")

    # Process anything sitting in there on startup
    for f in sorted(INBOX.iterdir()):
        if f.is_file() and f.suffix.lower() in PROCESSABLE_EXTS:
            log(f"found existing file in feedback_inbox: {f.name}")
            try:
                transcribe(f)
            except Exception as e:
                log(f"existing-file transcribe threw: {e}")

    handler = FeedbackHandler()
    observer = Observer()
    observer.schedule(handler, str(INBOX), recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        log("shutting down feedback watcher")
        observer.stop()
    observer.join()


# ---------- entry ----------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", nargs="?")
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()

    if args.watch:
        watch_inbox()
    elif args.file:
        path = Path(args.file).expanduser().resolve()
        out = transcribe(path)
        if out:
            print(f"Done: {out}")
        else:
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
