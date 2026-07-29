"""The approval gate between building the captainship drafts and mailing them.

The daily shape (Eve, 2026-07-29):

    run.py --dry-run          build the 12 previews
    review_gate.py --post     one PDF -> Drive -> Lucy posts the link in Slack
    review_gate.py --check    a checkmark from Lucy or Evelyn fires the send

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
REVIEW_CHANNEL = "C0BLLU9M0A2"      # #revision-informes-capitanes

# Whose checkmark counts. Jolie is in the channel to review, NOT to authorise
# (Eve, 2026-07-29). Slack reports the reacting user, so this is enforceable.
APPROVERS = {
    "U0BCFGCR5PV": "Lucy",
    "U088E2KJEV8": "Evelyn",
}
# Any of Slack's checkmarks — nobody should have to remember which one is "the"
# checkmark, and picking the wrong green tick must not silently mean "not yet".
APPROVE_EMOJI = {"white_check_mark", "heavy_check_mark",
                 "ballot_box_with_check", "check"}

# Stamped into the Slack message so --check can find the day's post from another
# machine without anything being passed between them.
MARKER = "CAPTAINSHIP-REVIEW"
REMIND_MARKER = "CAPTAINSHIP-REVIEW-REMINDER"
# Hours after the post, not a clock time — the build is triggered by hand once
# the Sales Board is complete, so it lands at a different hour every day.
REMIND_AFTER_HOURS = 3.0

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
    text = (f"*Informes de capitanes — {reported.month}/{reported.day}*\n"
            f"{link}\n\n"
            f"Revisen y reaccionen con :white_check_mark: para que salgan. "
            f"Autorizan Lucy o Evelyn. Nada se envía hasta entonces.\n"
            f"`{MARKER} {today:%Y-%m-%d}`")
    r = _client().chat_postMessage(channel=_channel(channel), text=text,
                                   unfurl_links=False)
    if verbose:
        print(f"✓ posted to {_channel(channel)} ts={r['ts']}", flush=True)
    return r["ts"]


def _find_post(today: dt.date, channel: Optional[str] = None) -> Optional[dict]:
    """The day's review message, found by its marker rather than by a ts handed
    over from the machine that posted it — that is what lets --post run on the
    mini and everything else run on Eve's box."""
    want = f"{MARKER} {today:%Y-%m-%d}"
    hist = _client().conversations_history(channel=_channel(channel), limit=100)
    return next((m for m in hist.get("messages", [])
                 if want in (m.get("text") or "")), None)


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
    names = " o ".join(sorted(APPROVERS.values()))
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f"Recordatorio: los informes de capitanes siguen sin aprobar "
              f"({age_h:.0f}h). No se envió nada todavía — hace falta un "
              f":white_check_mark: de {names}.\n`{REMIND_MARKER}`"))
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
    if args.post:
        post_review(upload_pdf(build_pdf(today)), today, args.channel)
        return 0
    if args.remind:
        return 0 if remind(today, args.after_hours, args.channel) else 1
    if args.check:
        who = find_approval(today, args.channel)
        if not who:
            return 1
        print(f"✓ approved by {who[1]}", flush=True)
        return send_reviewed(today) if args.send else 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
