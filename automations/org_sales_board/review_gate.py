"""The approval gate between building the Org Sales Board email and mailing it.

The daily shape (Eve, 2026-07-29) — the same one the captainship drafts use, so
there is one review habit and not two:

    review_gate.py --post           build the preview -> PDF -> Drive -> Lucy
                                    posts the link in #revision-emails
    review_gate.py --check --send   a checkmark from an approver mails it

Nothing here can mail anything on its own: it shells out to
`screenshot_email --send-reviewed`, which mails the images ALREADY captured for
the day (from that run's manifest) and re-captures nothing. What was approved is
what goes out, even if the board moves between the post and the checkmark.

WHY A CHANNEL AND NOT A GROUP DM. The reaction IS the approval, so the gate has
to read reactions. They ride along on the messages conversations.history returns,
and the reporting token holds channels:history + groups:history but not
mpim:history — in a group DM it could post and never see the answer. Slack also
names who reacted, so approval is a person, not a string to interpret.

BOTH HALVES RUN ON THE MINI, unlike the captainship gate. --post has to: the
Slack user token there is Lucy's, and that is the only reason the message
arrives from Lucy (on Eve's box it is Evelyn's — one of the approvers, which
would read as her approving her own report). --check --send can, because this
email goes out over SMTP with alphaletereporting's app password, which the mini
already has; there is no Gmail-token half that only exists on Eve's box. The two
halves still never talk: --check finds the day's message by its marker.
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

# The private channel where the day's email is reviewed — THE SAME ONE THE
# CAPTAINSHIP DRAFTS USE (Eve, 2026-07-29). One channel, one review habit: the
# approvers are the same two people and they check one place, not two. The two
# gates can't confuse each other's posts — each searches for its own MARKER, and
# they differ.
#
# Hardcoded because the reporting token can neither create a channel (no
# groups:write) nor LIST them (no channels:read/groups:read), so this can't be
# resolved by name at runtime. Safe to hardcode: a renamed channel keeps its id.
REVIEW_CHANNEL = "C0BLLU9M0A2"      # #revision-emails

# Whose checkmark counts: EVELYN AND JOLIE, the same two as the captainship gate
# (Eve, 2026-07-30 — "mismos aprobadores en los dos"). Lucy is in the channel and
# is the one who POSTS the link, but she does not read the reports, so her
# checkmark must not release them. Slack reports the reacting user, so this is
# enforceable: a tick from anyone else leaves the gate closed.
#
# Jolie is U0ACBT3JVTP (joliecarc@gmail.com), verified against the channel's own
# members. NOT D0ACU8GQ7TK — that is the DM conversation with her, and a D-id
# here would never match a reacting user, so her approval would silently never
# count.
APPROVERS = {
    "U088E2KJEV8": "Evelyn",
    "U0ACBT3JVTP": "Jolie",
}
# Any of Slack's checkmarks — nobody should have to remember which one is "the"
# checkmark, and picking the wrong green tick must not silently mean "not yet".
APPROVE_EMOJI = {"white_check_mark", "heavy_check_mark",
                 "ballot_box_with_check", "check"}

# How --check finds the day's post from a run that never spoke to the one that
# posted it. It used to be a `ORG-BOARD-EMAIL-REVIEW 2026-07-29` line stamped
# into the message; Eve cut it 2026-07-29 — the reviewers read this message, and
# a machine code in it is noise to every one of them. The TITLE already carries
# the date and is already unique per day, so it does the same job with nothing
# extra on screen. Same for the thread replies: they're matched on their own
# opening word, and only ever our own messages live in that thread.
TITLE = "Org Sales Board — correo del"          # + " M/D"
REMIND_OPENER = "Recordatorio:"
SENT_OPENER = "Enviado"
FAILED_OPENER = "No se pudo enviar"
REMIND_AFTER_HOURS = 3.0

DRIVE_FOLDER_NAME = "Org Sales Board - correos para revisar"


# --------------------------------------------------------------------------
# 1. the preview + the PDF
# --------------------------------------------------------------------------
def build_preview(today: dt.date, verbose: bool = True) -> Path:
    """Build the day's email preview and return its self-contained HTML.

    Shells out to screenshot_email --dry-run rather than importing capture():
    that run is the one that writes the manifest --send-reviewed later mails,
    so the reviewed artifact and the sent artifact come from the same command.
    """
    from automations.org_sales_board import screenshot_email as se
    cmd = [sys.executable, "-u", "-m", "automations.org_sales_board.screenshot_email",
           "--dry-run", "--date", today.isoformat()]
    if verbose:
        print(f"→ {' '.join(cmd)}", flush=True)
    rc = subprocess.call(cmd)
    if rc != 0:
        raise RuntimeError(f"preview build failed (exit {rc}) — nothing to review")
    html = se.out_dir_for(today) / "preview.html"
    if not html.exists():
        raise RuntimeError(f"no preview.html at {html}")
    return html


def build_pdf(today: dt.date, html: Optional[Path] = None,
              verbose: bool = True) -> Path:
    """Render the preview to a PDF.

    A PDF and not the raw HTML: Drive shows a PDF inline in the browser, so a
    reviewer opens the link and reads it — an .html in Drive downloads instead.
    The preview carries its images as data URIs, so this prints with no network.
    """
    from patchright.sync_api import sync_playwright
    from automations.org_sales_board import screenshot_email as se

    html = html or (se.out_dir_for(today) / "preview.html")
    if not html.exists():
        raise RuntimeError(f"no preview at {html} — build it first (--post does)")
    out = se.out_dir_for(today) / f"org_sales_board_email_{today:%Y%m%d}.pdf"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(html.resolve().as_uri(), wait_until="load")
            page.wait_for_timeout(1500)      # let the inline images decode
            page.pdf(path=str(out), format="Letter", print_background=True,
                     margin={"top": "12mm", "bottom": "12mm",
                             "left": "10mm", "right": "10mm"})
        finally:
            browser.close()
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
    and the reviewers sign in as alphaletereporting, so the link already works
    for them. A sharing permission would only widen who can read a day of sales
    for the whole org — and an anyone-with-the-link file is one forward away
    from being public. Same reasoning as captainship_drafts.review_gate.
    """
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
            "REVIEW_CHANNEL is unset — create the review channel in Slack, add "
            "Lucy to it, then paste its id here. The reporting token can "
            "neither create the channel (no groups:write) nor find it by name "
            "(no channels:read/groups:read).")
    return ch


def post_review(link: str, today: dt.date, channel: Optional[str] = None,
                verbose: bool = True) -> str:
    """Post the day's link. Returns the message ts.

    RUN THIS ON THE MINI — the token there is Lucy's, and that is the only
    reason the message arrives from Lucy."""
    # .month/.day, never %-m — that strftime flag does not exist on Windows and
    # this module runs on both machines.
    text = (f"*{_title(today)}*\n"
            f"{link}\n\n"
            f"Revisen y reaccionen con :white_check_mark: para que salga. "
            f"Nada se envía hasta entonces.")
    cli = _client()
    olds = _all_posts(today, channel)

    # NEVER destroy an approval. If today's post already carries an authorised
    # checkmark, the day is decided: re-posting would delete a human's decision
    # and silently reset the gate to "waiting". Learned the hard way 2026-07-29
    # — a rerun queued moments before Eve reacted wiped her checkmark, and the
    # email that was approved simply never went. --post is a no-op from then on.
    for old in olds:
        who = _approver_of(old)
        if who:
            if verbose:
                print(f"— {_title(today)} is already approved by {who[1]}; "
                      f"leaving the post (and the approval) alone", flush=True)
            return old["ts"]

    # A second review post for the same day is worse than none: the checker
    # takes the newest, so a checkmark left on the older one would silently
    # never send. A rerun replaces its own previous post — ours only, matched on
    # our own title for this day, and only while nobody has approved it.
    for old in olds:
        try:
            cli.chat_delete(channel=_channel(channel), ts=old["ts"])
            if verbose:
                print(f"  (replaced the earlier post for {_title(today)})", flush=True)
        except Exception as e:  # noqa: BLE001 — a stale post must not block the new one
            print(f"  (could not remove the earlier post: {type(e).__name__})", flush=True)
    r = cli.chat_postMessage(channel=_channel(channel), text=text,
                             unfurl_links=False)
    if verbose:
        print(f"✓ posted to {_channel(channel)} ts={r['ts']}", flush=True)
    return r["ts"]


def _title(today: dt.date) -> str:
    """The message's first line. Carries the REPORTED day (yesterday), which is
    what makes it unique per day — and what --check keys off.
    .month/.day, never %-m: that strftime flag does not exist on Windows."""
    reported = today - dt.timedelta(days=1)
    return f"{TITLE} {reported.month}/{reported.day}"


def _all_posts(today: dt.date, channel: Optional[str] = None) -> list:
    """Every review post for `today`, newest first. More than one means a rerun
    happened; the captainship gate's posts share this channel and are skipped by
    the title."""
    want = _title(today)
    hist = _client().conversations_history(channel=_channel(channel), limit=100)
    return [m for m in hist.get("messages", []) if want in (m.get("text") or "")]


def _find_post(today: dt.date, channel: Optional[str] = None) -> Optional[dict]:
    """The day's review message, found by its TITLE rather than by a ts handed
    over from the run that posted it — that is what lets --post and --check be
    separate runs. No hidden marker: the title already says which day it is."""
    posts = _all_posts(today, channel)
    return posts[0] if posts else None


def _approver_of(msg: dict) -> Optional[Tuple[str, str]]:
    for rx in msg.get("reactions", []):
        if rx.get("name") not in APPROVE_EMOJI:
            continue
        for uid in rx.get("users", []):
            if uid in APPROVERS:
                return uid, APPROVERS[uid]
    return None


def already_sent(today: dt.date, channel: Optional[str] = None) -> bool:
    """Has this day's email already gone out? The thread under the review post
    is the record: --check posts a confirmation there after a successful send.
    Checked from Slack and not from a local state file because the checker runs
    every 15 minutes and MUST NOT mail the board twice — a state file that a
    cleared output/ or a second machine can't see is not a lock."""
    msg = _find_post(today, channel)
    if msg is None:
        return False
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    return any((r.get("text") or "").startswith(SENT_OPENER) for r in replies[1:])


def report_failure(today: dt.date, rc: int, channel: Optional[str] = None) -> None:
    """Say in the thread that an APPROVED email did not go out. Once.

    The send now expands a live contact group, so it has a way to fail that the
    approval can't predict — a missing contacts token on the mini, a renamed
    group. Without this the checker would retry every 15 minutes and each
    failure would land in a log on a machine nobody is looking at, while the
    channel still showed a green checkmark and everyone assumed it went."""
    msg = _find_post(today, channel)
    if msg is None:
        return
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    if any((r.get("text") or "").startswith(FAILED_OPENER) for r in replies[1:]):
        return
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f"{FAILED_OPENER}: está aprobado, pero el envío falló "
              f"(exit {rc}). Sigo reintentando cada 15 min; si no cambia, "
              f"revisar el log `org-board-email-review` en la mini."))


def confirm_sent(today: dt.date, who: str, to_note: str = "",
                 channel: Optional[str] = None) -> None:
    """Reply in-thread that it went out. Doubles as the once-a-day lock, so it
    must keep starting with SENT_OPENER."""
    msg = _find_post(today, channel)
    if msg is None:
        return
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f"{SENT_OPENER} :white_check_mark: — aprobó {who}"
              f"{(' · ' + to_note) if to_note else ''}"))


def remind(today: dt.date, after_hours: float = REMIND_AFTER_HOURS,
           channel: Optional[str] = None, verbose: bool = True) -> bool:
    """Nudge the channel if the day's email is still waiting. True if posted.

    Hours SINCE THE POST, not a wall-clock time. Nudges ONCE: a reminder that
    repeats becomes noise, and noise is how the real one gets ignored."""
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
    import time
    age_h = (time.time() - float(msg["ts"])) / 3600
    if age_h < after_hours:
        if verbose:
            print(f"— posted {age_h:.1f}h ago, waiting until {after_hours}h",
                  flush=True)
        return False
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    if any((r.get("text") or "").startswith(REMIND_OPENER) for r in replies[1:]):
        if verbose:
            print("— already reminded once", flush=True)
        return False
    names = " o ".join(sorted(APPROVERS.values()))
    # Must keep starting with REMIND_OPENER — that is what stops it repeating.
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f"{REMIND_OPENER} el correo del Org Sales Board sigue sin aprobar "
              f"({age_h:.0f}h). No se envió nada todavía — hace falta un "
              f":white_check_mark: de {names}."))
    if verbose:
        print(f"✓ reminder posted ({age_h:.1f}h unapproved)", flush=True)
    return True


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
def send_reviewed(today: dt.date, distro: bool = False,
                  verbose: bool = True) -> int:
    """Shell out to screenshot_email --send-reviewed. A separate process on
    purpose: the sender stays the one command that has ever mailed this, and
    this module never grows its own path to a recipient list."""
    cmd = [sys.executable, "-u", "-m",
           "automations.org_sales_board.screenshot_email",
           "--send-reviewed", "--date", today.isoformat()]
    if distro:
        cmd.append("--distro")
    if verbose:
        print(f"→ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--post", action="store_true",
                    help="build the preview + PDF, upload it, post the link. "
                         "RUN ON THE MINI so it comes from Lucy.")
    ap.add_argument("--check", action="store_true",
                    help="look for an authorised checkmark; with --send, mail "
                         "the reviewed images when it is there.")
    ap.add_argument("--send", action="store_true",
                    help="with --check: actually send. Without it, --check only "
                         "reports what it found.")
    ap.add_argument("--distro", action="store_true",
                    help="with --check --send: mail the real distro groups "
                         "instead of the proving list.")
    ap.add_argument("--remind", action="store_true",
                    help="nudge the channel if the day's email is still "
                         "unapproved after --after-hours. Nudges once.")
    ap.add_argument("--after-hours", type=float, default=REMIND_AFTER_HOURS,
                    help=f"hours since the post before --remind fires "
                         f"(default {REMIND_AFTER_HOURS}).")
    ap.add_argument("--pdf-only", action="store_true",
                    help="build the preview + PDF and stop (no Drive, no Slack).")
    ap.add_argument("--channel", default=None,
                    help="override the channel id (for a one-off test).")
    ap.add_argument("--date", default=None,
                    help="run date (default today). The email is for the day "
                         "BEFORE, same as screenshot_email.")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()

    if args.pdf_only:
        build_pdf(today, build_preview(today))
        return 0
    if args.post:
        post_review(upload_pdf(build_pdf(today, build_preview(today))),
                    today, args.channel)
        return 0
    if args.remind:
        return 0 if remind(today, args.after_hours, args.channel) else 1
    if args.check:
        if already_sent(today, args.channel):
            print("— already sent today, nothing to do", flush=True)
            return 0
        who = find_approval(today, args.channel)
        if not who:
            return 1
        print(f"✓ approved by {who[1]}", flush=True)
        if not args.send:
            return 0
        rc = send_reviewed(today, args.distro)
        if rc == 0:
            confirm_sent(today, who[1],
                         to_note="distro Alphalete Org Owners" if args.distro else "",
                         channel=args.channel)
        else:
            report_failure(today, rc, args.channel)
        return rc
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
