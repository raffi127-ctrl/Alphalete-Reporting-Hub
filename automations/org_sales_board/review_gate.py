"""The approval gate between building the Org Sales Board email and mailing it.

The daily shape (Eve, 2026-07-29) — the same one the captainship drafts use, so
there is one review habit and not two:

    review_gate.py --post           build the preview -> PDF -> Drive -> Lucy
                                    posts the link in #revision-emails
    review_gate.py --refresh        the board was corrected after the link went
                                    out: rebuild and overwrite the PDF in Drive,
                                    same link, NO second post
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

# Publishes the "approved" phase row the Hub card colours green.
from automations.shared import review_approval as RA
# Sat/Sun policy: a clean day releases itself, because nobody is in the channel
# to tick it. One module for all four gates, so the weekend rule can't drift.
from automations.shared import weekend_release as wr

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

# The Hub card this gate releases. Used only to publish the "approved" phase row
# (shared/review_approval.py) that turns the card's tile green — the card lists
# "<this>-approved" as its last phase. Hyphenated: it is the CARD id, not the
# orchestrator's report_id.
HUB_CARD_ID = "sales-board-screenshot-email"
HUB_CARD_NAME = "Org. Sales Board Email"


def _mentions() -> str:
    """The approvers as real Slack mentions, e.g. "<@U08…> <@U0A…>".

    A plain "Evelyn, Jolie" is only text — it lights nothing up, and this
    channel competes with every other one they are in, so the message just gets
    lost (Eve, 2026-07-30). "<@ID>" is what actually notifies them, and it
    renders as @Name so the sentence still reads normally.

    Built from APPROVERS and sorted by display name: the order is stable, and
    changing who approves changes who gets pinged with no second edit. Same
    helper, same wording as the captainship gate — one habit, not two."""
    return " ".join(f"<@{uid}>" for uid, _ in
                    sorted(APPROVERS.items(), key=lambda kv: kv[1]))


# How --check finds the day's post from a run that never spoke to the one that
# posted it. It used to be a `ORG-BOARD-EMAIL-REVIEW 2026-07-29` line stamped
# into the message; Eve cut it 2026-07-29 — the reviewers read this message, and
# a machine code in it is noise to every one of them. The TITLE already carries
# the date and is already unique per day, so it does the same job with nothing
# extra on screen. Same for the thread replies: they're matched on a distinctive
# phrase of their own, and only ever our own messages live in that thread.
#
# ENGLISH since 2026-07-30 (Eve), to match the captainship gate that shares this
# channel. The _LEGACY twins are the Spanish strings this used to write: --check
# still RECOGNISES them so a post made before the switch stays approvable. They
# are read-only — nothing writes them any more — and can be deleted once no
# unapproved Spanish post is left in the channel.
# The scheduler id of the job that BUILDS this day's draft. weekend_release
# walks its dependency chain to decide whether a Sat/Sun day is clean enough to
# mail itself — so it must stay the id in schedule_config.json, not a label.
REPORT_ID = "org_sales_board_email"

TITLE = "Org Sales Board Email"                 # + " — M/D"
TITLE_LEGACY = "Org Sales Board — correo del"   # + " M/D"
REMIND_MARK = "reminder: the Org Sales Board email"
REMIND_MARK_LEGACY = "Recordatorio:"
SENT_MARK = "Sent — approved by"
# "Enviado" is what this wrote before 2026-07-30. "Sent to the distro" was the
# English wording for a few minutes on 2026-07-30 and said "distro" even when the
# mail had gone to the proving list — recognised here so a thread that got one
# is still locked, never written.
SENT_MARK_LEGACY = ("Enviado", "Sent to the distro")
FAILED_MARK = "Could not send"
# Said once when the day closes with nobody having approved. Until this existed,
# such a day ended in silence — no approval, no send, no message — which reads
# exactly like a day that went fine. The only trace was a post with no checkmark,
# scrolling away under everything else.
CLOSED_MARK = "Not sent — nobody approved"
FAILED_MARK_LEGACY = "No se pudo enviar"
REMIND_AFTER_HOURS = 3.0


def _said(replies, *marks) -> bool:
    """Has one of our own thread replies already said `marks`?

    Substring, not startswith: the replies now OPEN with the approver mentions,
    so the phrase that identifies them is no longer the first thing in the text.
    Safe as a substring because only our own messages live in this thread.

    Each mark is a string OR an iterable of them, so a wording that changed more
    than once can carry every retired spelling without the call sites growing a
    star-arg each time."""
    flat = []
    for m in marks:
        flat.extend([m] if isinstance(m, str) else list(m))
    return any(any(m in (r.get("text") or "") for m in flat)
               for r in replies[1:])

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
# How many dated review PDFs a folder keeps. One per report per day, so this is
# "the last N days". 30 is well past the point where anyone re-opens one.
KEEP_LAST_PDFS = 30


def upload_pdf(pdf: Path, verbose: bool = True,
               folder_name: str = None,
               keep_last: int = KEEP_LAST_PDFS) -> str:
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

    # `folder_name` defaults to this board's folder; board_emails passes its
    # own so each report's reviewers open a folder holding only that report.
    folder_name = folder_name or DRIVE_FOLDER_NAME
    svc = build("drive", "v3", credentials=drive_auth.load_credentials(),
                cache_discovery=False)
    folder_mime = "application/vnd.google-apps.folder"
    q = (f"name = '{folder_name}' and mimeType = '{folder_mime}' "
         f"and trashed = false")
    found = svc.files().list(q=q, spaces="drive",
                             fields="files(id)").execute().get("files", [])
    fid = (found[0]["id"] if found else
           svc.files().create(body={"name": folder_name,
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
    # One dated PDF a day would fill this folder forever. Keep the recent ones
    # and trash the rest — the record of what was approved lives in the Slack
    # thread, not in a review PDF from three months ago.
    from automations.shared.drive_prune import prune_folder
    prune_folder(svc, fid, keep_last, verbose=verbose)
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
    # English, all of it (Eve, 2026-07-30) — the thread replies below match, so
    # the two halves of one conversation don't switch language, and it reads the
    # same as the captainship post that shares this channel.
    # The mentions come from APPROVERS, so changing who approves can't leave the
    # message pinging the old list.
    text = (f"*{_title(today)}*\n"
            f"{link}\n\n"
            f"{_mentions()} — please review and react with "
            f":white_check_mark: to send it. Nothing goes out until then.")
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
    return f"{TITLE} — {reported.month}/{reported.day}"


def _title_legacy(today: dt.date) -> str:
    """The Spanish title this used to write. Read-only — see TITLE_LEGACY."""
    reported = today - dt.timedelta(days=1)
    return f"{TITLE_LEGACY} {reported.month}/{reported.day}"


def _all_posts(today: dt.date, channel: Optional[str] = None) -> list:
    """Every review post for `today`, newest first. More than one means a rerun
    happened; the captainship gate's posts share this channel and are skipped by
    the title.

    Matches the legacy Spanish title too, so the switch to English on 2026-07-30
    could not strand a post that was already up and waiting for its checkmark —
    the checker would simply have stopped finding it and that day's email would
    never have gone out."""
    wants = (_title(today), _title_legacy(today))
    hist = _client().conversations_history(channel=_channel(channel), limit=100)
    # PREFIX, not "anywhere in the text" (2026-07-30). Four gates now share this
    # channel, and every post opens with *its own title*. A plain `in` matched
    # any title that merely CONTAINED this one, so a board named
    # "… Org Sales Board Email" would have been picked up here — and a checkmark
    # meant for it would have released the Org board's email instead.
    return [m for m in hist.get("messages", [])
            if any((m.get("text") or "").lstrip("*").startswith(w)
                   for w in wants)]


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
    return _said(replies, SENT_MARK, SENT_MARK_LEGACY)


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
    if _said(replies, FAILED_MARK, FAILED_MARK_LEGACY):
        return
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f"{_mentions()} — {FAILED_MARK}: this is approved, but the send "
              f"failed (exit {rc}). Still retrying every 15 min; if it doesn't "
              f"clear, check the `org-board-email-review` log on the mini."))


def close_day(today: dt.date, channel: Optional[str] = None,
              verbose: bool = True) -> bool:
    """Say in the thread that the day ended without an approval. True if posted.

    The checker stops at END_HOUR, and until now that was the whole ending: the
    board email simply never went and nobody was told. Says nothing when the day
    is decided — an approved day is confirmed or has its own failure notice —
    and says it ONCE, because the checker keeps ticking until midnight."""
    msg = _find_post(today, channel)
    if msg is None:
        if verbose:
            print(f"— nothing posted for {_title(today)}, nothing to close",
                  flush=True)
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
        text=(f"{_mentions()} — {CLOSED_MARK}: today's Org Sales Board email "
              f"did not go out. Approve here and it still will, or leave it and "
              f"tomorrow's post replaces it."))
    if verbose:
        print("✓ day closed unapproved — said so in the thread", flush=True)
    return True


def hold_weekend(today: dt.date, reason: str,
                 channel: Optional[str] = None, verbose: bool = True) -> bool:
    """Say in the thread that the weekend auto-send did NOT release this day.

    Sat/Sun a clean day mails itself (weekend_release). A day that DOESN'T is
    the one nobody is watching: no approver in the channel, no email, and — with
    nothing said — no difference from a weekend that went fine. Says it once,
    names what blocked it, and tags the approvers so the checkmark path is still
    open to whoever reads it."""
    msg = _find_post(today, channel)
    if msg is None:
        return False
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    if _said(replies, wr.HELD_MARK):
        return False
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=f"{_mentions()} {wr.held_note(reason, 'the Org Sales Board email')}")
    if verbose:
        print(f"✓ weekend hold said once in the thread — {reason}", flush=True)
    return True


def confirm_sent(today: dt.date, who: str, to_note: str = "",
                 channel: Optional[str] = None) -> None:
    """Reply in-thread that it went out. Doubles as the once-a-day lock, so it
    must keep containing SENT_MARK."""
    msg = _find_post(today, channel)
    if msg is None:
        return
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f":white_check_mark: {SENT_MARK} {who}"
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
    if _said(replies, REMIND_MARK, REMIND_MARK_LEGACY):
        if verbose:
            print("— already reminded once", flush=True)
        return False
    # Must keep containing REMIND_MARK — that is what stops it repeating.
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f"{_mentions()} — {REMIND_MARK} is still unapproved "
              f"({age_h:.0f}h). Nothing has been sent; it needs a "
              f":white_check_mark:."))
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
    ap.add_argument("--refresh", action="store_true",
                    help="rebuild the preview + PDF and update the one already "
                         "in Drive, WITHOUT posting again. For when the board "
                         "is corrected after the link went out. Wins over "
                         "--post.")
    ap.add_argument("--check", action="store_true",
                    help="look for an authorised checkmark; with --send, mail "
                         "the reviewed images when it is there.")
    ap.add_argument("--send", action="store_true",
                    help="with --check: actually send. Without it, --check only "
                         "reports what it found.")
    ap.add_argument("--no-auto", action="store_true",
                    help="never release without a checkmark, not even on the "
                         "weekend (weekend_release).")
    ap.add_argument("--distro", action="store_true",
                    help="with --check --send: mail the real distro groups "
                         "instead of the proving list.")
    ap.add_argument("--remind", action="store_true",
                    help="nudge the channel if the day's email is still "
                         "unapproved after --after-hours. Nudges once.")
    ap.add_argument("--close-day", action="store_true",
                    help="say in the thread that the day ended unapproved, so "
                         "a day nobody reacted to isn't silent. Says it once, "
                         "and nothing at all if the day was approved.")
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
    # Checked BEFORE --post on purpose. The scheduler entry's base_args are
    # ["--post"], so `lucy rerun org_sales_board_email --refresh` arrives here
    # as "--post --refresh" and has to mean refresh — otherwise the one case
    # this exists for could not be triggered the one way it is triggered.
    # Same flag, same order, same reason as captainship_drafts.review_gate.
    if args.refresh:
        # Rebuilding the preview also rewrites the day's manifest, so the images
        # --check --send mails are the corrected ones too: what is reviewed and
        # what is sent stay the same artifact.
        link = upload_pdf(build_pdf(today, build_preview(today)))
        # Same name = same day, so upload_pdf updated the file IN PLACE and the
        # link already posted in Slack now shows the rebuilt PDF. Nothing is
        # posted: a correction must not ping the approvers a second time with a
        # second message for them to choose between.
        print(f"✓ refreshed in place, existing link still valid: {link}",
              flush=True)
        return 0
    if args.post:
        post_review(upload_pdf(build_pdf(today, build_preview(today))),
                    today, args.channel)
        return 0
    if args.remind:
        return 0 if remind(today, args.after_hours, args.channel) else 1
    if args.close_day:
        close_day(today, args.channel)
        return 0
    if args.check:
        if already_sent(today, args.channel):
            print("— already sent today, nothing to do", flush=True)
            # Repair a missing approval row (the Hub pill) without costing a
            # Slack call on the other ~40 passes of the day: the lookup only
            # runs when today has nothing recorded yet.
            RA.ensure_recorded(HUB_CARD_ID, HUB_CARD_NAME,
                               lambda: find_approval(today, args.channel,
                                                     verbose=False),
                               day=today)
            return 0
        who = find_approval(today, args.channel)
        if not who:
            # Sat/Sun there is nobody in the channel to tick it, and a report
            # that built cleanly should not die waiting for a reader who isn't
            # there (Eve 2026-08-12). A clean weekend day releases itself; a
            # dirty one still waits for a checkmark, and says so in the thread.
            ok, why = wr.auto_release([REPORT_ID], today,
                                      enabled=not args.no_auto)
            print(f"  weekend auto-send: {why}", flush=True)
            if not ok:
                if args.send and wr.is_weekend(today) and not args.no_auto:
                    hold_weekend(today, why, args.channel)
                return 1
            who = (wr.AUTO_ID, wr.AUTO_WHO)
        print(f"✓ approved by {who[1]}", flush=True)
        # Tell the Hub the human said yes — this is what turns the card's phase
        # pill from purple (awaiting ✅) to green. Before the send, so an
        # approved day shows as approved even if the send then fails.
        RA.ensure_recorded(HUB_CARD_ID, HUB_CARD_NAME, who, day=today)
        if not args.send:
            return 0
        rc = send_reviewed(today, args.distro)
        if rc == 0:
            # Name the real destination in BOTH cases (Eve, 2026-07-30). The
            # confirmation used to say nothing at all without --distro, so a
            # mail that went only to Rafael + Megan read in the channel exactly
            # like one that went to the whole org.
            confirm_sent(today, who[1],
                         to_note=("Alphalete Org Owners distro" if args.distro
                                  else "proving list (Rafael + Megan)"),
                         channel=args.channel)
        else:
            report_failure(today, rc, args.channel)
        return rc
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
