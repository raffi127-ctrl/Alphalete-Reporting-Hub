"""The approval gate between building the captainship drafts and mailing them.

The daily shape (Eve, 2026-07-29):

    run.py --dry-run          build the 12 previews
    review_gate.py --post     one PDF -> Drive -> Lucy posts the link in Slack
    review_gate.py --check    a checkmark from Evelyn or Jolie fires the send

WHY A CHANNEL AND NOT A GROUP DM. The reaction is the approval, so the gate has
to be able to READ reactions. Reactions ride along on the messages that
conversations.history returns, and the reporting token holds channels:history +
groups:history — but not mpim:history, so in a group DM it can post and never
see the answer. In a private channel it works with the scopes already granted,
and Slack names the user who reacted, so approval is a person and not a string
someone has to interpret.

WHY TWO MACHINES. --post has to run on the MINI: the Slack user token there is
Lucy's, which is what makes the message arrive from Lucy. Every other machine
holds its own token and would post as that person instead (on Eve's Windows box
it is Evelyn's — one of the approvers, which would read as her approving her own
report). --check and the send have to run on EVE'S BOX, because that is where
the previews and the Gmail token live. The two halves never talk: --check finds
the day's message by searching the channel for its marker, so nothing has to be
handed between them.

Nothing here can mail anything on its own — it shells out to run.py
--send-reviewed, which sends the exact files that were reviewed and rebuilds
nothing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from automations.captainship_drafts import config

# The private channel with Evelyn, Jolie and Lucy. Set once (Slack blocks the
# reporting token from creating channels — it has no groups:write), then never
# again: a renamed channel keeps its id, so this survives a rename.
REVIEW_CHANNEL = "C0BLLU9M0A2"      # #revision-emails

# Whose checkmark counts: EVELYN AND JOLIE ONLY (Eve, 2026-07-30). Lucy posts
# the link but does not read the reports, so her tick must not release them.
# Slack reports the reacting user, so this is enforceable — a checkmark from
# anyone else leaves the gate closed.
#
# Jolie is U0ACBT3JVTP (joliecarc@gmail.com), verified against this channel's
# own members. NOT D0ACU8GQ7TK: that is the DM conversation with her, and a
# D-id here could never match a reacting user, so her approval would silently
# never count and the gate would sit closed with no error to explain it.
APPROVERS = {
    "U088E2KJEV8": "Evelyn",
    "U0ACBT3JVTP": "Jolie",
}
# Any of Slack's checkmarks — nobody should have to remember which one is "the"
# checkmark, and picking the wrong green tick must not silently mean "not yet".
APPROVE_EMOJI = {"white_check_mark", "heavy_check_mark",
                 "ballot_box_with_check", "check"}


def _mentions() -> str:
    """The approvers as real Slack mentions, e.g. "<@U08…> <@U0A…>".

    A plain "Approvers: Evelyn, Jolie" is only text — it lights nothing up, and
    this channel competes with every other one they are in, so the message just
    gets lost (Eve, 2026-07-30). "<@ID>" is what actually notifies them, and it
    renders as @Name so the sentence still reads normally.

    Built from APPROVERS and sorted by display name: the order is stable, and
    changing who approves changes who gets pinged with no second edit."""
    return " ".join(f"<@{uid}>" for uid, _ in
                    sorted(APPROVERS.items(), key=lambda kv: kv[1]))


# Stamped into the Slack message so --check can find the day's post from another
# machine without anything being passed between them.
MARKER = "CAPTAINSHIP-REVIEW"
REMIND_MARKER = "CAPTAINSHIP-REVIEW-REMINDER"
# Posted in the thread once the day's send has been attempted, and read before
# any send. THE APPROVAL IS NOT THE LOCK: a checkmark stays on the message all
# day, and the checker asks every 15 minutes from 9am to 8pm, so without this
# an approved day mails all 12 reports to their real recipients on EVERY tick.
# Found 2026-07-30 with the approval already in place — captainship_review.sh
# documented this lock, but nothing implemented it.
#
# It lives in the Slack thread and not in a state file on purpose: the send can
# be triggered from either machine and output/ gets wiped, so a local file would
# be a lock only one of them can see.
SENT_MARKER = "CAPTAINSHIP-SENT"
# Posted once when the day closes with no approval. Without it, a day nobody
# reacted to looks exactly like a day that went fine: the checker stops at
# END_HOUR, the captains get nothing, and the only trace is a post with no
# checkmark that scrolls away. Silence must not be the failure mode.
CLOSED_MARKER = "CAPTAINSHIP-NOT-SENT"
# Hours after the post, not a clock time — the build is triggered by hand once
# the Sales Board is complete, so it lands at a different hour every day.
REMIND_AFTER_HOURS = 2.0

_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"
DRIVE_FOLDER_NAME = "Captainship Reports - para revisar"


# --------------------------------------------------------------------------
# 1. the PDF
# --------------------------------------------------------------------------
def preview_htmls(today: dt.date) -> list[Tuple[str, Path]]:
    """[(captain display name, preview html)] for `today`, in roster order —
    the order the emails go out in, so the PDF reads like the send list."""
    out = []
    for cap in config.CAPTAINS:
        p = _OUTPUT_DIR / f"captainship_draft_{cap.key}_{today:%Y%m%d}.html"
        if p.exists():
            out.append((cap.display_name, p))
    return out


def build_pdf(today: dt.date, verbose: bool = True) -> Path:
    """Render the day's previews into ONE PDF.

    One file rather than twelve: Drive shows a PDF inline in the browser, so the
    reviewers scroll through the whole set behind a single link instead of
    downloading twelve attachments. The previews carry their images inline as
    data URIs, so this prints without touching the network."""
    from pypdf import PdfWriter
    from patchright.sync_api import sync_playwright

    pages = preview_htmls(today)
    if not pages:
        raise RuntimeError(
            f"no previews for {today:%Y-%m-%d} in {_OUTPUT_DIR} — run "
            f"`run.py --dry-run` first")
    if len(pages) != len(config.CAPTAINS):
        missing = {c.display_name for c in config.CAPTAINS} - {n for n, _ in pages}
        # Loud, not fatal: a captain whose draft failed to build must not be
        # quietly dropped from the thing people are approving.
        print(f"  ⚠ only {len(pages)}/{len(config.CAPTAINS)} previews — "
              f"missing: {sorted(missing)}", flush=True)

    out = _OUTPUT_DIR / f"captainship_reports_{today:%Y%m%d}.pdf"
    parts: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            for name, html in pages:
                part = _OUTPUT_DIR / f"_rg_{html.stem}.pdf"
                page.goto(html.resolve().as_uri(), wait_until="load")
                page.wait_for_timeout(1200)      # let the inline images decode
                page.pdf(path=str(part), format="Letter",
                         print_background=True,
                         margin={"top": "12mm", "bottom": "12mm",
                                 "left": "10mm", "right": "10mm"})
                parts.append(part)
                if verbose:
                    print(f"  ✓ {name}", flush=True)
        finally:
            browser.close()

    writer = PdfWriter()
    for part in parts:
        writer.append(str(part))
    with open(out, "wb") as fh:
        writer.write(fh)
    for part in parts:
        part.unlink(missing_ok=True)
    if verbose:
        print(f"✓ PDF: {out} ({out.stat().st_size // 1024} KB)", flush=True)
    return out


# --------------------------------------------------------------------------
# 2. Drive
# --------------------------------------------------------------------------
def upload_pdf(pdf: Path, verbose: bool = True) -> str:
    """Put the PDF in Drive and return a link the reviewers can open.

    Reuses the fiber_activations Drive token (alphaletereporting, drive.file
    scope — it can only touch files it created, which is all we need).

    NOTHING IS SHARED BY CODE. The file lands in alphaletereporting's own Drive
    and the reviewers all sign in as alphaletereporting (Eve, 2026-07-29), so
    the link already works for them. A sharing permission would only widen who
    can read a day of sales for ~145 reps — and an anyone-with-the-link file is
    one forward away from being public. Same reasoning as
    fiber_activations.drive_upload."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    from automations.fiber_activations import drive_auth

    svc = build("drive", "v3", credentials=drive_auth.load_credentials(),
                cache_discovery=False)
    folder_mime = "application/vnd.google-apps.folder"
    q = (f"name = '{DRIVE_FOLDER_NAME}' and mimeType = '{folder_mime}' "
         f"and trashed = false")
    found = svc.files().list(q=q, spaces="drive",
                             fields="files(id)").execute().get("files", [])
    fid = (found[0]["id"] if found else
           svc.files().create(body={"name": DRIVE_FOLDER_NAME,
                                    "mimeType": folder_mime},
                              fields="id").execute()["id"])

    media = MediaFileUpload(str(pdf), mimetype="application/pdf", resumable=False)
    q = f"name = '{pdf.name}' and '{fid}' in parents and trashed = false"
    existing = svc.files().list(q=q, spaces="drive",
                                fields="files(id)").execute().get("files", [])
    if existing:
        # Same name = same day. Update in place so a rebuild keeps the link the
        # reviewers may already be looking at.
        file_id = existing[0]["id"]
        svc.files().update(fileId=file_id, media_body=media).execute()
    else:
        file_id = svc.files().create(
            body={"name": pdf.name, "parents": [fid]},
            media_body=media, fields="id").execute()["id"]

    link = svc.files().get(fileId=file_id,
                           fields="webViewLink").execute()["webViewLink"]
    if verbose:
        print(f"✓ Drive: {link}", flush=True)
    return link


# --------------------------------------------------------------------------
# 3. Slack
# --------------------------------------------------------------------------
def _client():
    from automations.shared.slack_metrics_post import _client as c
    return c()


def _channel(channel: Optional[str] = None) -> str:
    ch = channel or REVIEW_CHANNEL
    if not ch:
        raise RuntimeError(
            "REVIEW_CHANNEL is unset — create the private channel in Slack "
            "(Evelyn + Jolie + Lucy), then paste its id here. The reporting "
            "token cannot create it: no groups:write.")
    return ch


def post_review(link: str, today: dt.date, channel: Optional[str] = None,
                verbose: bool = True) -> str:
    """Post the day's link. Returns the message ts.

    RUN THIS ON THE MINI — the token there is Lucy's, and that is the only
    reason the message arrives from Lucy."""
    # .month/.day, never %-m — that strftime flag does not exist on Windows and
    # this module runs on both machines.
    reported = today - dt.timedelta(days=1)
    # English, all of it (Eve, 2026-07-30) — the reminder in the thread below
    # matches, so the two halves of one conversation don't switch language.
    # The mentions come from APPROVERS, so changing who approves can't leave
    # the message pinging the old list.
    text = (f"*Captainship Reports — {reported.month}/{reported.day}*\n"
            f"{link}\n\n"
            f"{_mentions()} — please review and react with "
            f":white_check_mark: to send them. Nothing goes out until then.\n"
            f"`{MARKER} {today:%Y-%m-%d}`")
    # A SECOND post for the same day is worse than none: --check takes the
    # newest, so a checkmark left on the older one would silently never send —
    # the approvers would see a tick sitting there and the captains would get
    # nothing. Re-posting is the normal way to correct a draft, so this has to
    # be safe, not merely discouraged.
    cli = _client()
    for old in _all_posts(today, channel):
        if _approver_of(old):
            # Already approved. Replacing it would DISCARD an approval that has
            # already been given; keep it and let the send run off it. Use
            # --refresh to update the PDF behind the link it points at.
            if verbose:
                print(f"— {today:%Y-%m-%d} is already approved "
                      f"({_approver_of(old)[1]}); leaving that post alone",
                      flush=True)
            return old["ts"]
        try:
            cli.chat_delete(channel=_channel(channel), ts=old["ts"])
            if verbose:
                print("  (replaced the earlier post for this day)", flush=True)
        except Exception as e:  # noqa: BLE001 — a stale post must not block a new one
            print(f"  (could not remove the earlier post: {type(e).__name__}) "
                  f"— CHECK THE CHANNEL: two posts means a checkmark can land "
                  f"on the wrong one", flush=True)

    r = cli.chat_postMessage(channel=_channel(channel), text=text,
                             unfurl_links=False)
    if verbose:
        print(f"✓ posted to {_channel(channel)} ts={r['ts']}", flush=True)
    return r["ts"]


def _find_post(today: dt.date, channel: Optional[str] = None) -> Optional[dict]:
    """The day's review message, found by its marker rather than by a ts handed
    over from the machine that posted it — that is what lets --post run on the
    mini and everything else run on Eve's box."""
    posts = _all_posts(today, channel)
    return posts[0] if posts else None


def _all_posts(today: dt.date, channel: Optional[str] = None) -> list:
    """Every review post for `today`, newest first. There should only ever be
    one — see post_review, which is what keeps it that way."""
    want = f"{MARKER} {today:%Y-%m-%d}"
    hist = _client().conversations_history(channel=_channel(channel), limit=100)
    return [m for m in hist.get("messages", [])
            if want in (m.get("text") or "")]


def _approver_of(msg: dict) -> Optional[Tuple[str, str]]:
    for rx in msg.get("reactions", []):
        if rx.get("name") not in APPROVE_EMOJI:
            continue
        for uid in rx.get("users", []):
            if uid in APPROVERS:
                return uid, APPROVERS[uid]
    return None


def remind(today: dt.date, after_hours: float = REMIND_AFTER_HOURS,
           channel: Optional[str] = None, verbose: bool = True) -> bool:
    """Nudge the channel if the day's reports are still waiting. True if posted.

    Hours SINCE THE POST, not a wall-clock time: the build is triggered by hand
    once the Sales Board is complete, so it lands at a different hour every day
    and a fixed 3pm reminder would fire before the link existed as often as
    after it.

    Silence was the alternative and it fails exactly when it matters — the day
    everyone is busy and nobody notices the captains got nothing (Eve,
    2026-07-29). Nudges ONCE: a reminder that repeats becomes noise, and noise
    is how the real one gets ignored."""
    msg = _find_post(today, channel)
    if msg is None:
        if verbose:
            print(f"— nothing posted for {today:%Y-%m-%d}, nothing to chase",
                  flush=True)
        return False
    who = _approver_of(msg)
    if who:
        if verbose:
            print(f"— already approved by {who[1]}", flush=True)
        return False
    # Epoch maths, so no timezone can make this fire early on one machine.
    import time
    age_h = (time.time() - float(msg["ts"])) / 3600
    if age_h < after_hours:
        if verbose:
            print(f"— posted {age_h:.1f}h ago, waiting until {after_hours}h",
                  flush=True)
        return False
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    if any(REMIND_MARKER in (r.get("text") or "") for r in replies[1:]):
        if verbose:
            print("— already reminded once", flush=True)
        return False
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f"{_mentions()} — reminder: the captainship reports are still "
              f"unapproved ({age_h:.0f}h). Nothing has been sent; they need a "
              f":white_check_mark:.\n`{REMIND_MARKER}`"))
    if verbose:
        print(f"✓ reminder posted ({age_h:.1f}h unapproved)", flush=True)
    return True


def close_day(today: dt.date, channel: Optional[str] = None,
              verbose: bool = True) -> bool:
    """Say in the thread that the day ended without an approval. True if posted.

    The checker stops at END_HOUR. Until now that was the whole ending: no
    approval, no send, no message — a day where 12 captains got nothing looked
    identical to a day that went fine, because the only trace was a post with no
    checkmark, scrolling away under everything else. Silence is the worst
    failure mode a review gate can have.

    Says nothing when the day is decided: an approved-and-sent day is already
    confirmed in the thread, and an approved-but-failed one has its own notice.
    Posts ONCE — the checker keeps ticking until midnight."""
    msg = _find_post(today, channel)
    if msg is None:
        if verbose:
            print(f"— nothing posted for {today:%Y-%m-%d}, nothing to close",
                  flush=True)
        return False
    if _approver_of(msg):
        if verbose:
            print("— approved; the send path owns this day", flush=True)
        return False
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    if any(CLOSED_MARKER in (r.get("text") or "") for r in replies[1:]):
        if verbose:
            print("— already closed once", flush=True)
        return False
    n = len(config.CAPTAINS)
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f"{_mentions()} — nobody approved this today, so the {n} "
              f"captainship reports were NOT sent. The previews are still on "
              f"the mini: approve here and they go out, or leave it and "
              f"tomorrow's run replaces them.\n`{CLOSED_MARKER}`"))
    if verbose:
        print("✓ day closed unapproved — said so in the thread", flush=True)
    return True


def already_sent(msg: dict, channel: Optional[str] = None) -> bool:
    """Has today's send already been attempted? Reads the thread for the lock."""
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    return any(SENT_MARKER in (r.get("text") or "") for r in replies[1:])


def mark_sent(msg: dict, failures: int, channel: Optional[str] = None) -> None:
    """Close the day in the thread, cleanly or not.

    Posted after ANY completed attempt, including one with failures, and that is
    deliberate. Leaving it unlocked so a partial failure can retry means the
    captains who DID get their report get it again every 15 minutes; a send that
    needs a human is the lesser problem, and this message is how they find out.
    """
    note = ("✅ Sent — the reports are on their way to the captains."
            if not failures else
            f"⚠️ Sent with {failures} failure(s) — see the run log. Nothing will "
            f"retry on its own; trigger the rest by hand once it's fixed.")
    _client().chat_postMessage(channel=_channel(channel), thread_ts=msg["ts"],
                               text=f"{note}\n`{SENT_MARKER}`")


def find_approval(today: dt.date, channel: Optional[str] = None,
                  verbose: bool = True) -> Optional[Tuple[str, str]]:
    """(user_id, name) of the first authorised checkmark on today's post, else
    None."""
    msg = _find_post(today, channel)
    if msg is None:
        if verbose:
            print(f"— no review post found for {today:%Y-%m-%d}", flush=True)
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
# 4. the send
# --------------------------------------------------------------------------
def send_reviewed(today: dt.date, verbose: bool = True) -> int:
    """Shell out to run.py --send-reviewed for `today`. A separate process on
    purpose: the sender stays the one command that has ever mailed these, and
    this module never grows its own path to a recipient list."""
    cmd = [sys.executable, "-m", "automations.captainship_drafts.run",
           "--send-reviewed", "--date", today.isoformat()]
    if verbose:
        print(f"→ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--post", action="store_true",
                    help="build the PDF, upload it, post the link. RUN ON THE "
                         "MINI so it comes from Lucy.")
    ap.add_argument("--refresh", action="store_true",
                    help="rebuild the PDF and update the one already in Drive, "
                         "WITHOUT posting again. For when a draft is rebuilt "
                         "after the link went out. Wins over --post.")
    ap.add_argument("--check", action="store_true",
                    help="look for an authorised checkmark; with --send, mail "
                         "the reviewed files when it is there. Run on Eve's box.")
    ap.add_argument("--send", action="store_true",
                    help="with --check: actually send. Without it, --check only "
                         "reports what it found.")
    ap.add_argument("--remind", action="store_true",
                    help="nudge the channel if the day's reports are still "
                         "unapproved after --after-hours. Nudges once.")
    ap.add_argument("--after-hours", type=float, default=REMIND_AFTER_HOURS,
                    help=f"hours since the post before --remind fires "
                         f"(default {REMIND_AFTER_HOURS}).")
    ap.add_argument("--close-day", action="store_true",
                    help="say in the thread that the day ended unapproved, so "
                         "a day nobody reacted to isn't silent. Says it once, "
                         "and nothing at all if the day was approved.")
    ap.add_argument("--pdf-only", action="store_true",
                    help="build the PDF and stop (no Drive, no Slack).")
    ap.add_argument("--channel", default=None,
                    help="override the channel id (for a one-off test).")
    ap.add_argument("--date", default=None,
                    help="run date (default today). The reports are for the "
                         "day BEFORE, same as run.py.")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()

    if args.pdf_only:
        build_pdf(today)
        return 0
    # Checked BEFORE --post on purpose. The scheduler entry's base_args are
    # ["--post"], so `lucy rerun captainship_drafts_review --refresh` arrives
    # here as "--post --refresh" and has to mean refresh — otherwise the one
    # case this exists for could not be triggered the one way it is triggered.
    if args.refresh:
        link = upload_pdf(build_pdf(today))
        # Same name = same day, so upload_pdf updated the file IN PLACE and the
        # link already posted in Slack now shows the rebuilt PDF. Nothing is
        # posted: a correction must not ping the approvers a second time with a
        # second message for them to choose between.
        print(f"✓ refreshed in place, existing link still valid: {link}",
              flush=True)
        return 0
    if args.post:
        post_review(upload_pdf(build_pdf(today)), today, args.channel)
        return 0
    if args.remind:
        return 0 if remind(today, args.after_hours, args.channel) else 1
    if args.close_day:
        close_day(today, args.channel)
        return 0
    if args.check:
        who = find_approval(today, args.channel)
        if not who:
            return 1
        print(f"✓ approved by {who[1]}", flush=True)
        if not args.send:
            return 0
        msg = _find_post(today, args.channel)
        if msg is not None and already_sent(msg, args.channel):
            print("— already sent today (the thread carries the lock); "
                  "nothing to do", flush=True)
            return 0
        failures = send_reviewed(today)
        if msg is not None:
            mark_sent(msg, failures, args.channel)
        return failures
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
