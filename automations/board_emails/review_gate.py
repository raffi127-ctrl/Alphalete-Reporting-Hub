"""The approval gate for the board emails — the same one, for both boards.

    review_gate.py --board country   --post           build -> PDF -> Drive ->
                                                      Lucy posts the link
    review_gate.py --board country   --check --send   a checkmark mails it

Everything that decides WHO may approve and WHERE — the channel, the two
approvers, which emoji count — is imported from the Org Sales Board gate rather
than restated. There is one review habit in this company and it must not be
possible for the four gates to drift apart on who is allowed to release a
report. What differs per board is only its title, its Drive folder and the
command it shells out to, and that lives in boards.py.

Nothing here can mail anything on its own: it runs `email_send --send-reviewed`,
which mails the image already captured for the day and re-renders nothing.

WHICH MACHINE. --post has to run on the MINI: the Slack user token there is
Lucy's, and that is the only reason the message arrives from Lucy (on Eve's box
it is Evelyn's — one of the approvers, which would read as her approving her own
report). --check --send can run there too: these emails go out over SMTP with
alphaletereporting's app password, which the mini already has. The two halves
never talk — --check finds the day's post by its title.
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from automations.board_emails import boards as B
from automations.board_emails import email_send as es
# Single source of truth for the gate's policy. Importing it means a change to
# the approver list lands on every gate at once.
from automations.org_sales_board.review_gate import (
    REVIEW_CHANNEL, APPROVERS, APPROVE_EMOJI,
    _mentions, _client, _channel, _said, upload_pdf,
)
# Publishes the "approved" phase row the Hub card colours green.
from automations.shared import review_approval as RA

SENT_MARK = "Sent — approved by"
REMIND_MARK = "reminder: this board email"
FAILED_MARK = "Could not send"
# Said once when the day closes with nobody having approved. Without it such a
# day ends in silence — no approval, no send, no message — which reads exactly
# like a day that went fine; the only trace is a post with no checkmark,
# scrolling away under everything else. Same rule the Org board gate learned.
CLOSED_MARK = "Not sent — nobody approved"
REMIND_AFTER_HOURS = 3.0

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


# --------------------------------------------------------------------------
# 1. the preview + the PDF
# --------------------------------------------------------------------------
def build_preview(board: B.Board, run_day: dt.date, verbose: bool = True) -> Path:
    """Build the day's preview and return its self-contained HTML.

    Shells out to `email_send --dry-run` rather than importing capture(): that
    run is the one that writes the manifest --send-reviewed later mails, so the
    reviewed artifact and the sent artifact come from the same command."""
    cmd = [sys.executable, "-u", "-m", "automations.board_emails.email_send",
           "--board", board.key, "--dry-run", "--date", run_day.isoformat()]
    if verbose:
        print(f"→ {' '.join(cmd)}", flush=True)
    rc = subprocess.call(cmd)
    if rc != 0:
        raise RuntimeError(f"preview build failed (exit {rc}) — nothing to review")
    html = es.out_dir_for(board, run_day) / "preview.html"
    if not html.exists():
        raise RuntimeError(f"no preview.html at {html}")
    return html


def build_pdf(board: B.Board, run_day: dt.date, html: Optional[Path] = None,
              verbose: bool = True) -> Path:
    """Render the preview to a PDF — Drive shows a PDF inline in the browser, so
    a reviewer opens the link and reads it, where an .html would download. The
    preview carries its image as a data URI, so this prints with no network."""
    from patchright.sync_api import sync_playwright

    out_dir = es.out_dir_for(board, run_day)
    html = html or (out_dir / "preview.html")
    if not html.exists():
        raise RuntimeError(f"no preview at {html} — build it first (--post does)")
    out = out_dir / f"{board.key}_email_{run_day:%Y%m%d}.pdf"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(html.resolve().as_uri(), wait_until="load")
            page.wait_for_timeout(1500)      # let the inline image decode
            page.pdf(path=str(out), format="Letter", print_background=True,
                     margin={"top": "12mm", "bottom": "12mm",
                             "left": "10mm", "right": "10mm"})
        finally:
            browser.close()
    if verbose:
        print(f"✓ PDF: {out} ({out.stat().st_size // 1024} KB)", flush=True)
    return out


# --------------------------------------------------------------------------
# 2. Slack
# --------------------------------------------------------------------------
def _title(board: B.Board, run_day: dt.date) -> str:
    """The message's first line. Carries the REPORTED day (yesterday), which is
    what makes it unique per day — and what --check keys off.
    .month/.day, never %-m: that flag does not exist on Windows."""
    d = es.reported_day(run_day)
    return f"{board.review_title} — {d.month}/{d.day}"


def _all_posts(board: B.Board, run_day: dt.date,
               channel: Optional[str] = None) -> list:
    """Every review post for this board and day, newest first.

    Matched on the title as a PREFIX of the message, not anywhere inside it:
    four gates share this channel, and a title that is a substring of another's
    would let one board's checkmark release another's email."""
    want = _title(board, run_day)
    hist = _client().conversations_history(channel=_channel(channel), limit=100)
    return [m for m in hist.get("messages", [])
            if (m.get("text") or "").lstrip("*").startswith(want)]


def _find_post(board: B.Board, run_day: dt.date,
               channel: Optional[str] = None) -> Optional[dict]:
    posts = _all_posts(board, run_day, channel)
    return posts[0] if posts else None


def _approver_of(msg: dict) -> Optional[Tuple[str, str]]:
    for rx in msg.get("reactions", []):
        if rx.get("name") not in APPROVE_EMOJI:
            continue
        for uid in rx.get("users", []):
            if uid in APPROVERS:
                return uid, APPROVERS[uid]
    return None


def post_review(board: B.Board, link: str, run_day: dt.date,
                channel: Optional[str] = None, verbose: bool = True) -> str:
    """Post the day's link. Returns the message ts. RUN THIS ON THE MINI."""
    text = (f"*{_title(board, run_day)}*\n"
            f"{link}\n\n"
            f"{_mentions()} — please review and react with "
            f":white_check_mark: to send it. Nothing goes out until then.")
    cli = _client()
    olds = _all_posts(board, run_day, channel)

    # NEVER destroy an approval: if today's post already carries an authorised
    # checkmark the day is decided, and re-posting would delete a human's
    # decision and silently reset the gate to "waiting". Same rule (and same
    # 2026-07-29 lesson) as the Org board gate.
    for old in olds:
        who = _approver_of(old)
        if who:
            if verbose:
                print(f"— {_title(board, run_day)} is already approved by "
                      f"{who[1]}; leaving the post alone", flush=True)
            return old["ts"]

    # A second post for the same day is worse than none: the checker takes the
    # newest, so a checkmark on the older one would silently never send.
    for old in olds:
        try:
            cli.chat_delete(channel=_channel(channel), ts=old["ts"])
            if verbose:
                print(f"  (replaced the earlier post for "
                      f"{_title(board, run_day)})", flush=True)
        except Exception as e:  # noqa: BLE001 — a stale post must not block the new one
            print(f"  (could not remove the earlier post: {type(e).__name__})",
                  flush=True)
    r = cli.chat_postMessage(channel=_channel(channel), text=text,
                             unfurl_links=False)
    if verbose:
        print(f"✓ posted to {_channel(channel)} ts={r['ts']}", flush=True)
    return r["ts"]


def already_sent(board: B.Board, run_day: dt.date,
                 channel: Optional[str] = None) -> bool:
    """Has this day's email already gone out? The thread under the review post
    is the record. Read from Slack and not from a local file because the checker
    runs every 15 minutes and MUST NOT mail twice — a state file that a wiped
    output/ or a second machine can't see is not a lock."""
    msg = _find_post(board, run_day, channel)
    if msg is None:
        return False
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    return _said(replies, SENT_MARK)


def confirm_sent(board: B.Board, run_day: dt.date, who: str, to_note: str = "",
                 channel: Optional[str] = None) -> None:
    """Reply in-thread that it went out. Doubles as the once-a-day lock, so it
    must keep containing SENT_MARK."""
    msg = _find_post(board, run_day, channel)
    if msg is None:
        return
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f":white_check_mark: {SENT_MARK} {who}"
              f"{(' · ' + to_note) if to_note else ''}"))


def report_failure(board: B.Board, run_day: dt.date, rc: int,
                   channel: Optional[str] = None) -> None:
    """Say in the thread that an APPROVED email did not go out. Once — without
    it the checker retries every 15 minutes into a log nobody is reading while
    the channel still shows a green checkmark."""
    msg = _find_post(board, run_day, channel)
    if msg is None:
        return
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    if _said(replies, FAILED_MARK):
        return
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f"{_mentions()} — {FAILED_MARK}: this is approved, but the send "
              f"failed (exit {rc}). Still retrying every 15 min; if it doesn't "
              f"clear, check the `org-board-email-review` log on the mini "
              f"(the watcher that drives all three board emails)."))


def remind(board: B.Board, run_day: dt.date,
           after_hours: float = REMIND_AFTER_HOURS,
           channel: Optional[str] = None, verbose: bool = True) -> bool:
    """Nudge the channel if the day's email is still waiting. True if posted.

    Hours SINCE THE POST, not a wall-clock time, and ONCE: a reminder that
    repeats becomes noise, and noise is how the real one gets ignored."""
    msg = _find_post(board, run_day, channel)
    if msg is None:
        if verbose:
            print(f"— nothing posted for {run_day:%Y-%m-%d}, nothing to chase",
                  flush=True)
        return False
    if _approver_of(msg):
        if verbose:
            print("— already approved", flush=True)
        return False
    import time
    age_h = (time.time() - float(msg["ts"])) / 3600
    if age_h < after_hours:
        if verbose:
            print(f"— posted {age_h:.1f}h ago, waiting until {after_hours}h",
                  flush=True)
        return False
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    if _said(replies, REMIND_MARK):
        if verbose:
            print("— already reminded once", flush=True)
        return False
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f"{_mentions()} — {REMIND_MARK} ({board.name}) is still "
              f"unapproved ({age_h:.0f}h). Nothing has been sent; it needs a "
              f":white_check_mark:."))
    if verbose:
        print(f"✓ reminder posted ({age_h:.1f}h unapproved)", flush=True)
    return True


def close_day(board: B.Board, run_day: dt.date,
              channel: Optional[str] = None, verbose: bool = True) -> bool:
    """Say in the thread that the day ended without an approval. True if posted.

    The checker stops at END_HOUR; without this, an unapproved day is the same
    silence as a day that went fine. Says nothing when the day is decided (an
    approved day is confirmed, or has its own failure notice) and says it ONCE,
    because the checker keeps ticking."""
    msg = _find_post(board, run_day, channel)
    if msg is None:
        if verbose:
            print(f"— nothing posted for {_title(board, run_day)}, "
                  f"nothing to close", flush=True)
        return False
    if _approver_of(msg):
        if verbose:
            print("— approved; the send path owns this day", flush=True)
        return False
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    if _said(replies, CLOSED_MARK):
        if verbose:
            print("— already closed once", flush=True)
        return False
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f"{_mentions()} — {CLOSED_MARK}: today's {board.name} email did "
              f"not go out. Approve here and it still will, or leave it and "
              f"tomorrow's post replaces it."))
    if verbose:
        print("✓ day closed unapproved — said so in the thread", flush=True)
    return True


def find_approval(board: B.Board, run_day: dt.date,
                  channel: Optional[str] = None,
                  verbose: bool = True) -> Optional[Tuple[str, str]]:
    msg = _find_post(board, run_day, channel)
    if msg is None:
        if verbose:
            print(f"— no review post found for {run_day:%Y-%m-%d}", flush=True)
        return None
    who = _approver_of(msg)
    if who:
        return who
    if verbose:
        got = [f":{r['name']}: x{r['count']}" for r in msg.get("reactions", [])]
        print(f"— not approved yet (reactions: {', '.join(got) or 'none'})",
              flush=True)
    return None


# --------------------------------------------------------------------------
# 3. the send
# --------------------------------------------------------------------------
def send_reviewed(board: B.Board, run_day: dt.date, verbose: bool = True) -> int:
    """Shell out to email_send --send-reviewed. A separate process on purpose:
    the sender stays the one command that has ever mailed this, and this module
    never grows its own path to a recipient list."""
    cmd = [sys.executable, "-u", "-m", "automations.board_emails.email_send",
           "--board", board.key, "--send-reviewed",
           "--date", run_day.isoformat()]
    if verbose:
        print(f"→ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board", required=True, choices=B.KEYS)
    ap.add_argument("--post", action="store_true",
                    help="build the preview + PDF, upload it, post the link. "
                         "RUN ON THE MINI so it comes from Lucy.")
    ap.add_argument("--check", action="store_true",
                    help="look for an authorised checkmark; with --send, mail "
                         "the reviewed image when it is there.")
    ap.add_argument("--send", action="store_true",
                    help="with --check: actually send.")
    ap.add_argument("--remind", action="store_true",
                    help="nudge the channel if still unapproved after "
                         "--after-hours. Nudges once.")
    ap.add_argument("--after-hours", type=float, default=REMIND_AFTER_HOURS)
    ap.add_argument("--close-day", action="store_true",
                    help="past the checking window: say once in the thread that "
                         "nobody approved, so an unapproved day isn't silence.")
    ap.add_argument("--pdf-only", action="store_true",
                    help="build the preview + PDF and stop (no Drive, no Slack).")
    ap.add_argument("--channel", default=None,
                    help="override the channel id (for a one-off test).")
    ap.add_argument("--date", default=None,
                    help="run date (default today, Central). The email reports "
                         "the day BEFORE it.")
    args = ap.parse_args(argv)

    board = B.get(args.board)
    run_day = (dt.date.fromisoformat(args.date) if args.date
               else es.today_central())

    if args.pdf_only:
        build_pdf(board, run_day, build_preview(board, run_day))
        return 0
    if args.post:
        pdf = build_pdf(board, run_day, build_preview(board, run_day))
        post_review(board, upload_pdf(pdf, folder_name=board.drive_folder),
                    run_day, args.channel)
        return 0
    if args.close_day:
        close_day(board, run_day, args.channel)
        return 0
    if args.remind:
        return 0 if remind(board, run_day, args.after_hours, args.channel) else 1
    if args.check:
        if already_sent(board, run_day, args.channel):
            print("— already sent today, nothing to do", flush=True)
            # Repair a missing approval row (the Hub pill) without costing a
            # Slack call on the other ~40 passes of the day: the lookup only
            # runs when today has nothing recorded yet.
            RA.ensure_recorded(board.report_id, board.hub_name,
                               lambda: find_approval(board, run_day,
                                                     args.channel, verbose=False),
                               day=run_day)
            return 0
        who = find_approval(board, run_day, args.channel)
        if not who:
            return 1
        print(f"✓ approved by {who[1]}", flush=True)
        # Tell the Hub the human said yes — this is what turns the card's phase
        # pill from purple (awaiting ✅) to green. Before the send, so an
        # approved day shows as approved even if the send then fails.
        RA.ensure_recorded(board.report_id, board.hub_name, who, day=run_day)
        if not args.send:
            return 0
        rc = send_reviewed(board, run_day)
        if rc == 0:
            confirm_sent(board, run_day, who[1],
                         to_note=", ".join(board.to), channel=args.channel)
        else:
            report_failure(board, run_day, rc, args.channel)
        return rc
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
