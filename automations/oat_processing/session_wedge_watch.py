"""Office-11580 session-wedge alarm (Lucy 2).

WHY: when office 11580's Cloudflare clearance goes stale, BOTH the primary sender
(resume_pushing extractor) AND the OAT leftovers processing freeze at once — new
Indeed applications pile into the "Process Emails" queue and nobody is told, so it
silently climbs (Megan watched it reach 90). The automated browser can't clear
that Cloudflare itself; it needs a one-time headed clear on the mini. The whole
point of this watcher is to catch the wedge the moment it happens so it gets
cleared in minutes instead of stacking for a day.

HOW: runs cheaply (piggybacked on the OAT 5-min wrapper) — it only READS logs and
posts Slack, so it works even while the AppStream session is wedged. It scans the
newest resume_pushing + oat_processing logs for the wedge signature and, on a
fresh wedge, posts ONE alert to the corrections channel. Debounced: one alert per
episode, re-pinged at most every RE_ALERT_HOURS; the alert self-clears (posts an
"all clear") when a healthy run is seen again.

Run on the mini:  PYTHONPATH=. .venv/bin/python -m automations.oat_processing.session_wedge_watch
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
LOG_DIR = REPO_ROOT / "output" / "logs"
STATE = REPO_ROOT / "output" / ".oat_session_wedge_state"
CHANNEL_CACHE = REPO_ROOT / "output" / ".corrections_channel_id"

# Only consider logs touched in the last window — an old stalled run isn't a live
# wedge. Long enough to span the 5-min OAT cadence + a resume_pushing cycle.
LOOKBACK_MIN = 90
# Don't re-ping more than this often while a wedge stays open.
RE_ALERT_HOURS = 3

# The exact signatures both reports already log when the office-11580 session is
# wedged on Cloudflare (see resume_pushing.run.ExtractionStalled + oat open_oat).
WEDGE_SIGS = [
    "stale cloudflare clearance on office",
    "extractor stalled",
    "menu click miss",              # oat open_oat menu-click timeout
    "no rqst token in url",         # oat direct-nav fallback failed
    "no next-pager control found",  # walk landed on a pager-less page
]
# Signs a recent run processed cleanly (used to CLOSE an open wedge episode).
HEALTHY_SIGS = [
    "✅ sent to ai",
    "sent via overwrite",
    "ready for extraction at start: 0",
    re.compile(r"fill-nophone-from-tab: sent [1-9]"),
    re.compile(r"extract.*cycle.*→.*drop"),
]

# Which logs to scan (bare-name substrings under output/logs). Includes the merged
# applicant-push log (Resume Pushing + OAT combined) so the wedge signature is
# caught whether the office-11580 push runs as the two old agents or the unified one.
LOG_PATTERNS = ("oat-processing-", "oat_processing", "resume-pushing-",
                "resume_pushing", "applicant-push-", "applicant_push")


def _recent_logs() -> list[pathlib.Path]:
    if not LOG_DIR.exists():
        return []
    cutoff = dt.datetime.now().timestamp() - LOOKBACK_MIN * 60
    out = []
    for p in LOG_DIR.iterdir():
        if not p.is_file():
            continue
        if not any(pat in p.name for pat in LOG_PATTERNS):
            continue
        try:
            if p.stat().st_mtime >= cutoff:
                out.append(p)
        except OSError:
            continue
    return out


def _tail(p: pathlib.Path, n: int = 400) -> str:
    try:
        return "\n".join(p.read_text(errors="ignore").splitlines()[-n:]).lower()
    except OSError:
        return ""


def _match(text: str, sigs) -> str | None:
    for s in sigs:
        if isinstance(s, str):
            if s in text:
                return s
        else:  # compiled regex
            m = s.search(text)
            if m:
                return m.group(0)
    return None


def assess() -> tuple[str, str, str]:
    """Return (state, evidence, source_log). state ∈ {'wedged','healthy','quiet'}."""
    logs = _recent_logs()
    if not logs:
        return "quiet", "", ""
    wedge_hit = ("", "")
    healthy_hit = ("", "")
    for p in sorted(logs, key=lambda x: x.stat().st_mtime, reverse=True):
        text = _tail(p)
        w = _match(text, WEDGE_SIGS)
        if w and not wedge_hit[0]:
            wedge_hit = (w, p.name)
        h = _match(text, HEALTHY_SIGS)
        if h and not healthy_hit[0]:
            healthy_hit = (h, p.name)
    # A healthy signal from the NEWEST activity closes the episode even if an
    # older tail line still shows a past wedge.
    if healthy_hit[0] and not wedge_hit[0]:
        return "healthy", healthy_hit[0], healthy_hit[1]
    if wedge_hit[0]:
        return "wedged", wedge_hit[0], wedge_hit[1]
    if healthy_hit[0]:
        return "healthy", healthy_hit[0], healthy_hit[1]
    return "quiet", "", ""


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _save_state(d: dict) -> None:
    try:
        STATE.write_text(json.dumps(d))
    except OSError:
        pass


def _post(title: str, body_lines: list[str], dry_run: bool) -> bool:
    ch = ""
    try:
        ch = CHANNEL_CACHE.read_text().strip()
    except OSError:
        pass
    text = "\n".join([title] + body_lines)
    if dry_run or not ch:
        print(f"[wedge-watch] {'DRY-RUN' if dry_run else 'NO CHANNEL'} — would post:\n{text}\n")
        return bool(dry_run)
    try:
        from automations.shared.slack_metrics_post import _client
        _client().chat_postMessage(channel=ch, text=text,
                                   unfurl_links=False, unfurl_media=False)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[wedge-watch] post failed: {type(e).__name__}: {e}")
        return False


def run(dry_run: bool = False, now: dt.datetime | None = None) -> int:
    now = now or dt.datetime.now()
    state, evidence, source = assess()
    print(f"[wedge-watch] state={state} evidence={evidence!r} source={source}")
    st = _load_state()

    if state == "wedged":
        last = st.get("alerted_at")
        recent = False
        if last:
            try:
                recent = (now - dt.datetime.fromisoformat(last)).total_seconds() < RE_ALERT_HOURS * 3600
            except ValueError:
                recent = False
        if recent:
            print("[wedge-watch] wedge still open, alerted recently — no re-ping")
            return 0
        title = ":rotating_light: *Office 11580 session wedged — Lucy 2*"
        body = [
            "Cloudflare clearance went stale, so the automated browser is frozen "
            "on office 11580 — *both* pipelines are stalled:",
            "• *Resume Pushing* extractor — applications not getting auto-sent",
            "• *OAT 'One App at a time'* leftovers — not draining",
            "New Indeed apps keep arriving, so the Process Emails queue is climbing.",
            f"_signature:_ `{evidence}`  ({source})",
            "",
            "*Fix (~1 min, one-time):* on the mini, open AppStream for office 11580 "
            "in a headed window and clear the 'verify you are human' box once. "
            "Both reports resume and drain on their own.",
            "_This alarm auto-clears once a healthy run is seen._",
        ]
        if _post(title, body, dry_run):
            st["alerted_at"] = now.isoformat()
            st["episode_evidence"] = evidence
            _save_state(st)
            print("[wedge-watch] ALERT posted")
        return 0

    if state == "healthy":
        if st.get("alerted_at"):
            _post(":white_check_mark: *Office 11580 session recovered — Lucy 2*",
                  ["A healthy run just processed cleanly — the wedge is cleared and "
                   "the queue is draining again."], dry_run)
            print("[wedge-watch] episode closed (all-clear posted)")
        _save_state({})
        return 0

    # quiet: no recent activity to judge — leave any open episode as-is.
    print("[wedge-watch] no recent office-11580 activity — nothing to assess")
    return 0


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Office-11580 session-wedge alarm")
    ap.add_argument("--dry-run", action="store_true",
                    help="assess + print the alert, post nothing")
    args = ap.parse_args(argv)
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    import sys
    sys.exit(main())
