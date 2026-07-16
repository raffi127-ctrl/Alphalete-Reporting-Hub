"""Email the owner when new commits land on the repo — i.e. code pushed to the
Hub directly from a Claude session (or any machine), bypassing the Hub's own
upload flow. Hub uploads go to a Google Sheet, not git, so they're covered
separately (shared/hub_upload_notify.py); THIS covers everything that arrives as
a git push.

How it works (poll, not webhook — runs on the always-on mini via launchd every
~10 min):
  1. `git fetch` the remote.
  2. Compare origin/<branch> to a stored marker (the last SHA we've reported).
  3. If it advanced, email the new commits — each with author, subject, and the
     files it touched — plus a truncated combined diff so you can see WHAT changed.
  4. Advance the marker only after a successful send, so a failed send just
     retries on the next poll (no missed pushes, no dupes).

First run with no marker initializes silently to the current HEAD (no backfill
blast). `--init` re-initializes to HEAD without emailing. `--dry-run` builds the
email to output/logs and neither sends nor moves the marker.

Usage:
  python -m automations.hub_push_watch.run [--dry-run] [--init] [--branch main]
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import subprocess
import sys
from pathlib import Path

from automations.shared import hub_notify_email, hub_identity

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BRANCH = "main"
REMOTE = "origin"

# Marker lives beside the other machine-local config (creds, oauth token), NOT
# in the repo — it's per-machine state and must never be committed.
MARKER = Path.home() / ".config" / "recruiting-report" / "hub-push-watch-last-sha"

_MAX_DIFF_LINES = 500


def _git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def _read_marker() -> str | None:
    try:
        s = MARKER.read_text().strip()
        return s or None
    except FileNotFoundError:
        return None


def _write_marker(sha: str) -> None:
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(sha + "\n")


def _commits(rng: str) -> list[dict]:
    """Parse `git log rng` into dicts. Uses a unit-separator format so subjects
    with any punctuation survive."""
    fmt = "%H%x1f%h%x1f%an%x1f%ae%x1f%ad%x1f%s"
    out = _git("log", "--date=format:%b %d %-I:%M %p", f"--pretty={fmt}", rng)
    # NB: %-I above runs on the mini/macOS (Unix) only — this watcher is a mini
    # LaunchAgent, never Windows, so it's safe here (unlike Hub-side code).
    commits = []
    for line in out.splitlines():
        if not line.strip():
            continue
        full, short, an, ae, date, subject = line.split("\x1f")
        files = _git("show", "--pretty=format:", "--name-only", full).strip()
        # Map the git identity to a team name (raffi127-ctrl → Megan).
        commits.append({"full": full, "short": short,
                        "author": hub_identity.git_author(an, ae),
                        "date": date, "subject": subject,
                        "files": [f for f in files.splitlines() if f]})
    return commits


def _render(commits: list[dict], diff: str, elided: int,
            branch: str, diverged: bool) -> tuple[str, str, str]:
    n = len(commits)
    authors = sorted({c["author"] for c in commits})
    subject = (f"⬆️ {n} new commit{'s' if n != 1 else ''} pushed to the Hub "
               f"({', '.join(authors)})")

    h = ['<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;'
         'color:#111;max-width:820px">',
         f'<h2 style="margin:0 0 4px">⬆️ {n} new commit{"s" if n != 1 else ""} '
         f'on <code>{html.escape(branch)}</code></h2>',
         '<p style="margin:0 0 14px;color:#666">Code pushed to the repo '
         'directly (outside the Hub upload flow).</p>']
    t = [f"{n} new commit(s) on {branch}", ""]

    if diverged:
        warn = ("⚠️ History diverged (a force-push or reset) — showing the "
                "latest commits instead of an exact range.")
        h.append(f'<p style="color:#b31d28;margin:0 0 12px">{warn}</p>')
        t += [warn, ""]

    for c in commits:
        files = c["files"]
        flist = "".join(f'<li>{html.escape(f)}</li>' for f in files[:40])
        if len(files) > 40:
            flist += f'<li style="color:#666">… {len(files) - 40} more</li>'
        h.append(
            f'<div style="margin:0 0 14px;padding:10px;border:1px solid #e1e4e8;'
            f'border-radius:6px">'
            f'<div style="font-weight:600">{html.escape(c["subject"])}</div>'
            f'<div style="color:#666;font-size:13px;margin:2px 0 6px">'
            f'{html.escape(c["short"])} · {html.escape(c["author"])} · '
            f'{html.escape(c["date"])} · {len(files)} file(s)</div>'
            f'<ul style="margin:0;padding-left:18px;font-size:13px">{flist}</ul>'
            f'</div>')
        t += [f"* {c['subject']}",
              f"    {c['short']} · {c['author']} · {c['date']} · "
              f"{len(files)} file(s)"]
        t += [f"      {f}" for f in files[:40]]
        if len(files) > 40:
            t.append(f"      … {len(files) - 40} more")
        t.append("")

    if diff.strip():
        h.append('<h3 style="margin:18px 0 6px">Combined diff</h3>')
        rows = []
        for ln in diff.splitlines():
            if ln.startswith("+") and not ln.startswith("+++"):
                bg, col = "#e6ffed", "#22863a"
            elif ln.startswith("-") and not ln.startswith("---"):
                bg, col = "#ffeef0", "#b31d28"
            elif ln.startswith("@@"):
                bg, col = "#f1f8ff", "#005cc5"
            else:
                bg, col = "transparent", "#444"
            rows.append(f'<div style="background:{bg};color:{col}">'
                        f'{html.escape(ln) or "&nbsp;"}</div>')
        h.append('<div style="background:#f6f8fa;border:1px solid #e1e4e8;'
                 'border-radius:6px;padding:10px;overflow-x:auto;font-size:12px;'
                 'line-height:1.45;font-family:ui-monospace,Menlo,Consolas,'
                 'monospace;white-space:pre">' + "".join(rows) + '</div>')
        t += ["", "Combined diff:", diff]
        if elided:
            note = f"… {elided} more diff line(s) not shown."
            h.append(f'<p style="color:#666;margin:6px 0">{note}</p>')
            t += [note]

    h.append('</div>')
    return subject, "".join(h), "\n".join(t)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="build the email to output/logs; don't send or move the marker")
    ap.add_argument("--init", action="store_true",
                    help="set the marker to current HEAD without emailing")
    ap.add_argument("--branch", default=DEFAULT_BRANCH)
    args = ap.parse_args(argv)

    ts = dt.datetime.now().isoformat(timespec="seconds")

    try:
        _git("fetch", "--quiet", REMOTE, args.branch)
    except Exception as e:
        print(f"[{ts}] hub-push-watch: fetch failed: {e}", flush=True)
        return 1  # transient — next poll retries; marker untouched

    head = _git("rev-parse", f"{REMOTE}/{args.branch}").strip()
    marker = _read_marker()

    if args.init or marker is None:
        _write_marker(head)
        why = "re-init" if args.init else "first run — initialized"
        print(f"[{ts}] hub-push-watch: {why}, marker = {head[:12]} "
              "(no email)", flush=True)
        return 0

    if marker == head:
        print(f"[{ts}] hub-push-watch: no new commits (at {head[:12]})",
              flush=True)
        return 0

    # Did history stay linear from the marker? A force-push/reset makes the
    # marker no longer an ancestor — then a range diff is meaningless.
    is_ancestor = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "merge-base", "--is-ancestor",
         marker, head]).returncode == 0
    diverged = not is_ancestor

    if diverged:
        commits = _commits(f"{head}~5..{head}") if _has_depth(head, 5) \
            else _commits(head)
        diff = _git("show", "--format=", head)
    else:
        rng = f"{marker}..{head}"
        commits = _commits(rng)
        diff = _git("diff", rng)

    diff_lines = diff.splitlines()
    elided = max(0, len(diff_lines) - _MAX_DIFF_LINES)
    diff = "\n".join(diff_lines[:_MAX_DIFF_LINES])

    if not commits:
        print(f"[{ts}] hub-push-watch: advanced to {head[:12]} but no commits "
              "parsed; advancing marker.", flush=True)
        if not args.dry_run:
            _write_marker(head)
        return 0

    subject, html_body, text_body = _render(
        commits, diff, elided, args.branch, diverged)

    try:
        hub_notify_email.send_html(subject, html_body, text_body,
                                   dry_run=args.dry_run, tag="hub-push")
    except Exception as e:
        print(f"[{ts}] hub-push-watch: send failed, marker NOT moved "
              f"(retry next poll): {type(e).__name__}: {e}", flush=True)
        return 1

    if not args.dry_run:
        _write_marker(head)
    print(f"[{ts}] hub-push-watch: reported {len(commits)} commit(s), "
          f"marker → {head[:12]}{' (dry-run: marker unchanged)' if args.dry_run else ''}",
          flush=True)
    return 0


def _has_depth(sha: str, n: int) -> bool:
    """True if `sha` has at least n ancestors (so sha~n resolves)."""
    r = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", f"{sha}~{n}"],
                       capture_output=True, text=True)
    return r.returncode == 0


if __name__ == "__main__":
    sys.exit(main())
