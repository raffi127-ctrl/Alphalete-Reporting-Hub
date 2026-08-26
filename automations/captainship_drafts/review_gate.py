"""The approval gate between building the captainship drafts and mailing them.

The daily shape (Eve, 2026-07-29; split into blocks 2026-08-26):

    run.py --dry-run          build the previews, in BLOCK order
    review_gate.py --post     one PDF PER BLOCK -> Drive -> Lucy posts each
                              link inside the day's 'Captainship Reports' thread
    review_gate.py --check    a checkmark on a BLOCK's link fires THAT block

BLOCKS, AND WHY. Until 2026-08-26 this was one artefact: one PDF of thirteen
reports, one link, one checkmark. Nothing could be approved until the last
draft had finished building AND the whole set had finished printing, so one
slow captain held all thirteen. Eve split the work into blocks (config.BLOCKS
- Fiber 1: Rafael; Fiber 2: Wayne, Starr; Fiber 3: Tony, Chan, Sahil; then B2B;
then NDS): each block builds, prints and posts its own link as soon as it is
ready, and each link is approved and mailed on its own. A tanda goes out while
the next one is still being assembled.

THE THREAD IS THE DAY. One parent message names the day ('Captainship Reports
- 8/25'); every block's link is a REPLY in that thread, so the channel still
shows one conversation a day and not five posts to choose between. The
approval, the reminder, the weekend hold and the unapproved close all moved
onto the block replies, keyed by block.

BLOCKS ARE NOT THE PARTIAL SEND, and both still hold. A BLOCK is who gets
REVIEWED together - Eve's grouping, fixed in config. The partial send is who a
FAILURE touches on a given day - scope_today, computed from the day state. They
compose: a block's send skips the captains that day's failure holds back, and
the per-captain lock in the thread (PARTIAL_SENT_MARKER / sent_keys) stays the
one answer to "who already got their mail today", so the captain held back in
the morning is the only one mailed in the afternoon.

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
it is Evelyn's — the approver herself, which would read as her approving her own
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
from typing import List, Optional, Sequence, Set, Tuple

from automations.captainship_drafts import config
from automations.captainship_drafts import scope as _scope
# Publishes the "approved" phase row the Hub card colours green.
from automations.shared import review_approval as RA
# Sat/Sun: a clean day releases itself — nobody is in the channel to tick it.
from automations.shared import weekend_release as wr

# The private channel with Evelyn and Lucy. Set once (Slack blocks the
# reporting token from creating channels — it has no groups:write), then never
# again: a renamed channel keeps its id, so this survives a rename.
REVIEW_CHANNEL = "C0BLLU9M0A2"      # #revision-emails

# Whose checkmark counts: EVELYN ONLY (Eve, 2026-08-13 — Jolie left the company;
# she was the second approver here until today). Lucy posts the link but does not
# read the reports, so her tick must not release them. Slack reports the reacting
# user, so this is enforceable — a checkmark from anyone else, Jolie's old
# account included, leaves the gate closed.
#
# This dict is the ONLY list of approvers: _mentions() below builds the message's
# @-tags from it, so dropping someone here also stops the post from pinging them.
APPROVERS = {
    "U088E2KJEV8": "Evelyn",
}
# Any of Slack's checkmarks — nobody should have to remember which one is "the"
# checkmark, and picking the wrong green tick must not silently mean "not yet".
APPROVE_EMOJI = {"white_check_mark", "heavy_check_mark",
                 "ballot_box_with_check", "check"}

# The Hub card this gate releases. Used only to publish the "approved" phase row
# (shared/review_approval.py) that turns the card's tile green — the card lists
# "captainship-drafts-approved" as its last phase. Hyphenated: it is the CARD
# id, not the orchestrator's report_id (captainship_drafts_review).
HUB_CARD_ID = "captainship-drafts"
HUB_CARD_NAME = "Captainship Reports"


def _mentions() -> str:
    """The approvers as real Slack mentions, e.g. "<@U08…>".

    A plain "Approvers: Evelyn" is only text — it lights nothing up, and this
    channel competes with every other one she is in, so the message just gets
    lost (Eve, 2026-07-30). "<@ID>" is what actually notifies her, and it
    renders as @Name so the sentence still reads normally.

    Built from APPROVERS and sorted by display name: the order is stable, and
    changing who approves changes who gets pinged with no second edit — which is
    exactly how Jolie stopped being tagged (2026-08-13)."""
    return " ".join(f"<@{uid}>" for uid, _ in
                    sorted(APPROVERS.items(), key=lambda kv: kv[1]))


# Stamped into the Slack message so --check can find the day's post from another
# machine without anything being passed between them.
MARKER = "CAPTAINSHIP-REVIEW"
# Stamped into each BLOCK's threaded link, so a reply can be tied back to the
# block it releases without depending on the order Slack returns replies in.
# Format: "CAPTAINSHIP-REVIEW-BLOCK <date> <block key>".
BLOCK_MARKER = "CAPTAINSHIP-REVIEW-BLOCK"
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
# El mismo candado, pero cuando salio SOLO UNA PARTE (Eve 2026-08-22: «si falla
# uno... los que estan ok se envien»). Lleva las claves que YA salieron, porque
# el candado tiene que ser por capitan: sin eso, o se retiene a los doce hasta
# que se arregle el que fallo, o el tick de los 15 minutos les manda el reporte
# de nuevo a los que ya lo recibieron. Se lee con `sent_keys`.
PARTIAL_SENT_MARKER = "CAPTAINSHIP-SENT-ONLY"
# The scheduler id of the job that BUILDS these drafts' review post.
# weekend_release walks its dependency chain (the 8 metric modules included) to
# decide whether a Sat/Sun day is clean enough to release itself.
REPORT_ID = "captainship_drafts_review"
# Posted once when the day closes with no approval. Without it, a day nobody
# reacted to looks exactly like a day that went fine: the checker stops at
# END_HOUR, the captains get nothing, and the only trace is a post with no
# checkmark that scrolls away. Silence must not be the failure mode.
CLOSED_MARKER = "CAPTAINSHIP-NOT-SENT"
# The weekend-hold lock, per block. Its own marker rather than
# weekend_release.HELD_MARK, which is a PHRASE inside the note's prose: reusing
# it would make the hold note for one block read as a hold already said for
# every other block.
HELD_MARKER = "CAPTAINSHIP-WEEKEND-HELD"
# Hours after the post, not a clock time — the build is triggered by hand once
# the Sales Board is complete, so it lands at a different hour every day.
REMIND_AFTER_HOURS = 2.0

_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"
DRIVE_FOLDER_NAME = "Captainship Reports - para revisar"


# --------------------------------------------------------------------------
# 1. the PDF
# --------------------------------------------------------------------------
def _members(block: Optional["config.Block"]) -> list:
    """The captains a call covers: one block's, or everyone in block order."""
    return block.members if block is not None else config.captains_in_order()


def pdf_name(today: dt.date, block: Optional["config.Block"] = None) -> str:
    """The Drive/disk name of a block's review PDF. The name IS the identity:
    upload_pdf updates in place when a file of that name already exists, which
    is what keeps a link the approvers already have pointing at the rebuilt
    file."""
    stem = f"captainship_reports_{today:%Y%m%d}"
    return f"{stem}_{block.key}.pdf" if block is not None else f"{stem}.pdf"


def preview_htmls(today: dt.date,
                  block: Optional["config.Block"] = None
                  ) -> list[Tuple[str, Path]]:
    """[(captain display name, preview html)] for `today`, in BLOCK order —
    the order the emails go out in, so the PDF reads like the send list."""
    out = []
    for cap in _members(block):
        p = _OUTPUT_DIR / f"captainship_draft_{cap.key}_{today:%Y%m%d}.html"
        if p.exists():
            out.append((cap.display_name, p))
    return out


def build_pdf(today: dt.date, block: Optional["config.Block"] = None,
              verbose: bool = True) -> Path:
    """Render one BLOCK's previews into ONE PDF (or the whole day's, if no
    block is given).

    One file rather than one per captain: Drive shows a PDF inline in the
    browser, so the reviewers scroll through the block behind a single link
    instead of downloading three attachments. The previews carry their images
    inline as data URIs, so this prints without touching the network.

    Per block since 2026-08-26 — printing thirteen reports was minutes of work
    that had to finish before ANY of them could be looked at."""
    # ensure() and not a bare import: this is the leg that broke on
    # 2026-08-26 — the mini's venv had no pypdf, so the previews built and
    # the review post never happened. A missing package is the one failure a
    # 15-minute retry agent can never ride out on its own.
    from automations.shared.pkg import ensure
    PdfWriter = ensure("pypdf").PdfWriter
    from patchright.sync_api import sync_playwright

    want = _members(block)
    label = block.key if block is not None else "all"
    pages = preview_htmls(today, block)
    if not pages:
        raise RuntimeError(
            f"no previews for {label} on {today:%Y-%m-%d} in {_OUTPUT_DIR} — "
            f"run `run.py --dry-run"
            f"{f' --block {block.key}' if block is not None else ''}` first")
    if len(pages) != len(want):
        missing = {c.display_name for c in want} - {n for n, _ in pages}
        # Loud, not fatal: a captain whose draft failed to build must not be
        # quietly dropped from the thing people are approving.
        print(f"  ⚠ {label}: only {len(pages)}/{len(want)} previews — "
              f"missing: {sorted(missing)}", flush=True)

    out = _OUTPUT_DIR / pdf_name(today, block)
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
def preview_emls(today: dt.date, block: Optional["config.Block"] = None
                 ) -> list[Tuple[str, Path]]:
    """[(captain key, preview .eml)] for `today` — the files --send-reviewed
    actually mails, as opposed to the .html the PDF is printed from."""
    return [(cap.key, _OUTPUT_DIR / f"captainship_draft_{cap.key}_{today:%Y%m%d}.eml")
            for cap in _members(block)]


def previews_complete(today: dt.date,
                      keys: Optional[Sequence[str]] = None) -> Tuple[bool, str]:
    """Are the twelve reports actually READY TO MAIL? (ok, motivo).

    This is what the weekend auto-send asks instead of "did the orchestrator
    mark the job DONE" (Eve 2026-08-21: "se tienen que enviar solos, a no ser
    que presenten una falla en la corrida directamente -- por ej que algun
    reporte de los captainship drafts no se haya completado o no se vea en el
    correo"). The orchestrator's bookkeeping is not the deliverable: on Sat
    2026-08-15 `captainship_drafts` read MISSED_NOT_READY with all twelve
    previews sitting on disk, because the 07:15 post agent builds them when the
    morning chain has not. Asking the .eml files is asking the thing Eve is
    actually describing.

    Checked, per captain, on the .eml the send would mail (not the .html the PDF
    is printed from):

      * it exists and is not empty          -> "no se completo"
      * it has an HTML body                 -> there is a mail to look at
      * it carries inline images and every  -> "no se ve en el correo": this is
        cid: the HTML points at resolves       the exact shape that made Gmail
                                               render broken boxes before.

    What this does NOT prove is that every SECTION made it in - a captain whose
    section 2 was skipped still produces a valid, smaller email. That case is
    caught one step earlier, by the metric module's own FAILED/INCOMPLETE status
    in the day state, which weekend_release treats as a hard stop.
    """
    import re as _re
    from email import policy as _policy
    from email.parser import BytesParser as _BytesParser

    # `keys` = mirar SOLO esos capitanes. Lo usa el envio parcial: si hoy sale
    # una tanda de doce, lo que tiene que estar completo son esos doce — el
    # borrador del que quedo retenido puede estar a medias, es justamente por lo
    # que se lo retiene.
    wanted = set(keys) if keys is not None else None
    pairs = [(k, p) for k, p in preview_emls(today)
             if wanted is None or k in wanted]
    want = len(pairs)
    missing, broken = [], []
    for key, path in pairs:
        if not path.exists() or path.stat().st_size == 0:
            missing.append(key)
            continue
        try:
            msg = _BytesParser(policy=_policy.default).parsebytes(path.read_bytes())
            html, cids = None, []
            for part in msg.walk():
                if part.get_content_type() == "text/html" and html is None:
                    html = part.get_content()
                if part.get_content_type().startswith("image/"):
                    cids.append((part.get("Content-ID") or "").strip()[1:-1])
            if not html:
                broken.append(f"{key} (sin cuerpo HTML)")
                continue
            refs = _re.findall(r'src="cid:([^"]+)"', html)
            if not cids:
                broken.append(f"{key} (sin imagenes)")
            elif [r for r in refs if r not in cids]:
                broken.append(f"{key} (imagenes rotas: "
                              f"{len([r for r in refs if r not in cids])} cid sin parte)")
        except Exception as e:  # noqa: BLE001 - un .eml ilegible ES el problema
            broken.append(f"{key} ({type(e).__name__})")

    if missing:
        return False, (f"faltan {len(missing)} de {want} borradores: "
                       f"{', '.join(missing)}")
    if broken:
        return False, f"borradores con problemas: {', '.join(broken)}"
    return True, f"los {want} borradores estan completos y con las imagenes bien"


def eml_digest(today: dt.date, block: Optional["config.Block"] = None) -> str:
    """Fingerprint of the day's .eml SET — what was reviewed, file for file.

    Why this exists (2026-07-31, and it cost a real send): the artefact people
    approve is the PDF, which lives in Drive and is therefore SHARED. The
    artefact that gets mailed is output/*.eml, which is per-machine. Nothing
    tied the two together. The mini built the drafts and posted the link; the
    same drafts were rebuilt on Eve's box after a fix and the Drive PDF was
    updated in place — so the reviewers approved corrected reports while the
    mini still held the broken .eml, and the send mailed those. The gate had no
    way to notice, because the only thing it checked was that SOMEONE had
    ticked SOME message.

    A missing preview hashes as "missing" rather than being skipped: a set of
    eleven is not the set of twelve that was approved.

    SCOPED TO THE BLOCK since 2026-08-26, because the block is now what gets
    approved. A whole-day digest would mean rebuilding Fiber 2 invalidated the
    NDS checkmark that was given off a PDF nothing had touched."""
    import hashlib
    h = hashlib.sha256()
    for key, path in preview_emls(today, block):
        h.update(key.encode())
        h.update(hashlib.sha256(path.read_bytes()).digest()
                 if path.exists() else b"missing")
    return h.hexdigest()[:16]


def reviewed_digest(today: dt.date, block: Optional["config.Block"] = None,
                    verbose: bool = False) -> Optional[str]:
    """The digest stamped on the Drive PDF when it was uploaded, or None.

    Read from Drive rather than from the Slack message on purpose: Drive is the
    one store BOTH machines can write, so a --refresh from either of them keeps
    the stamp true. Editing the Slack post would only work from the machine
    that posted it."""
    from googleapiclient.discovery import build
    from automations.fiber_activations import drive_auth
    svc = build("drive", "v3", credentials=drive_auth.load_credentials(),
                cache_discovery=False)
    name = pdf_name(today, block)
    q = f"name = '{name}' and trashed = false"
    files = svc.files().list(q=q, spaces="drive",
                             fields="files(id,description)").execute().get("files", [])
    if not files:
        if verbose:
            print(f"— no {name} in Drive", flush=True)
        return None
    return files[0].get("description") or None


# How many review PDFs the Drive folder keeps. A DAY is now one PDF PER BLOCK,
# so this is "the last ~30 days" and not "the last 30 files" — leaving it at 30
# would have pruned the folder down to six days without anybody asking.
KEEP_PDFS = 30 * max(1, len(config.BLOCKS))


def upload_pdf(pdf: Path, verbose: bool = True,
               keep_last: int = KEEP_PDFS, description: str = "") -> str:
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
    # The digest of the .eml set this PDF was printed from, stamped on the file
    # so the SENDING machine can prove it holds the same set — see eml_digest.
    body = {"description": description} if description else {}
    if existing:
        # Same name = same day. Update in place so a rebuild keeps the link the
        # reviewers may already be looking at.
        file_id = existing[0]["id"]
        svc.files().update(fileId=file_id, media_body=media,
                           body=body or None).execute()
    else:
        file_id = svc.files().create(
            body={"name": pdf.name, "parents": [fid], **body},
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
            "REVIEW_CHANNEL is unset — create the private channel in Slack "
            "(Evelyn + Lucy), then paste its id here. The reporting "
            "token cannot create it: no groups:write.")
    return ch


def replies(parent: dict, channel: Optional[str] = None) -> list:
    """The day's thread, parent excluded. ONE call — every per-block question
    (approved? sent? reminded? closed?) is answered off this list rather than
    asking Slack once per block, which at five blocks and a 15-minute watcher
    would be hundreds of calls a day for the same answer."""
    return _client().conversations_replies(
        channel=_channel(channel), ts=parent["ts"], limit=200
    ).get("messages", [])[1:]


def ensure_parent(today: dt.date, channel: Optional[str] = None,
                  verbose: bool = True) -> dict:
    """The day's parent message — found, or posted if it isn't there yet.

    It carries NO link: the links are the block replies underneath it. What it
    carries is the day, so the channel reads as one conversation and a
    checkmark can only ever land on a block, never on "everything".

    RUN THE POSTING SIDE ON THE MINI — the token there is Lucy's, and that is
    the only reason the message arrives from Lucy."""
    msg = _find_post(today, channel)
    if msg is not None:
        return msg
    # .month/.day, never %-m — that strftime flag does not exist on Windows and
    # this module runs on both machines.
    reported = today - dt.timedelta(days=1)
    blocks_line = " · ".join(f"{b.label} ({b.who})" for b in config.BLOCKS)
    # English, all of it (Eve, 2026-07-30) — the replies in the thread below
    # match, so the two halves of one conversation don't switch language.
    # The mentions come from APPROVERS, so changing who approves can't leave
    # the message pinging the old list.
    text = (f"*Captainship Reports — {reported.month}/{reported.day}*\n"
            f"{_mentions()} — the reports go up in this thread in blocks: "
            f"{blocks_line}.\n"
            f"Each block gets its own link below. React :white_check_mark: on "
            f"a block's message to send THAT block — you don't have to wait "
            f"for the rest. Nothing goes out until then.\n"
            f"`{MARKER} {today:%Y-%m-%d}`")
    r = _client().chat_postMessage(channel=_channel(channel), text=text,
                                   unfurl_links=False)
    if verbose:
        print(f"✓ opened the day's thread in {_channel(channel)} "
              f"ts={r['ts']}", flush=True)
    return {"ts": r["ts"], "text": text}


def _block_of_reply(msg: dict, today: dt.date) -> Optional[str]:
    """The block key a threaded reply belongs to, or None if it isn't a block
    link. Read off the marker rather than off position — Slack's reply order is
    chronological, and a re-post would silently shift a positional read."""
    want = f"{BLOCK_MARKER} {today:%Y-%m-%d} "
    text = msg.get("text") or ""
    i = text.find(want)
    if i < 0:
        return None
    key = text[i + len(want):].split("`")[0].split()[0].strip()
    return key if key in config.BLOCK_BY_KEY else None


def block_posts(today: dt.date, parent: dict,
                channel: Optional[str] = None,
                thread: Optional[list] = None) -> dict:
    """{block key: its link message} for today's thread. Newest wins, so a
    re-posted block link is the one a checkmark is read from."""
    out: dict = {}
    for m in (thread if thread is not None else replies(parent, channel)):
        key = _block_of_reply(m, today)
        if key:
            out[key] = m
    return out


def post_block(link: str, today: dt.date, block: "config.Block", parent: dict,
               channel: Optional[str] = None, verbose: bool = True) -> str:
    """Put ONE block's review link in the day's thread. Returns its ts.

    A SECOND link for the same block is worse than none: --check reads the
    newest, so a checkmark left on the older one would silently never send —
    the approvers would see a tick sitting there and the captains would get
    nothing. Re-posting is the normal way to correct a draft, so the old rule
    holds per block: an already-approved block is left alone (use --refresh to
    update the PDF behind the link people are already looking at), any other
    older copy is deleted first."""
    cli = _client()
    existing = block_posts(today, parent, channel).get(block.key)
    if existing is not None:
        if _approver_of(existing):
            if verbose:
                print(f"— {block.key} is already approved "
                      f"({_approver_of(existing)[1]}); leaving that post alone",
                      flush=True)
            return existing["ts"]
        try:
            cli.chat_delete(channel=_channel(channel), ts=existing["ts"])
            if verbose:
                print(f"  ({block.key}: replaced the earlier link)", flush=True)
        except Exception as e:  # noqa: BLE001 — a stale post must not block a new one
            print(f"  ({block.key}: could not remove the earlier link: "
                  f"{type(e).__name__}) — CHECK THE THREAD: two links means a "
                  f"checkmark can land on the wrong one", flush=True)

    n = len(block.members)
    text = (f"*{block.label} — {block.who}* "
            f"({n} report{'s' if n != 1 else ''})\n"
            f"{link}\n"
            f"{_mentions()} — :white_check_mark: here sends these {n}. "
            f"The other blocks are separate.\n"
            f"`{BLOCK_MARKER} {today:%Y-%m-%d} {block.key}`")
    r = cli.chat_postMessage(channel=_channel(channel), thread_ts=parent["ts"],
                             text=text, unfurl_links=False)
    if verbose:
        print(f"✓ {block.key} posted in the thread ts={r['ts']}", flush=True)
    return r["ts"]


def _find_post(today: dt.date, channel: Optional[str] = None) -> Optional[dict]:
    """The day's PARENT message, found by its marker rather than by a ts handed
    over from the machine that posted it — that is what lets --post run on the
    mini and everything else run on Eve's box."""
    posts = _all_posts(today, channel)
    return posts[0] if posts else None


def _all_posts(today: dt.date, channel: Optional[str] = None) -> list:
    """Every PARENT review post for `today`, newest first. There should only
    ever be one — see ensure_parent, which is what keeps it that way."""
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
    2026-07-29). Nudges ONCE PER BLOCK: a reminder that repeats becomes noise,
    and noise is how the real one gets ignored.

    Hours since THAT BLOCK'S link, not the parent's age: the blocks go up
    minutes apart on a good day and hours apart on a bad one, so each is chased
    on its own clock."""
    import time
    parent = _find_post(today, channel)
    if parent is None:
        if verbose:
            print(f"— nothing posted for {today:%Y-%m-%d}, nothing to chase",
                  flush=True)
        return False
    thread = replies(parent, channel)
    posts = block_posts(today, parent, channel, thread=thread)
    # ALREADY GONE OUT is not "still waiting", even with no checkmark on it: the
    # weekend auto-release mails a clean Sat/Sun day with nobody having ticked
    # anything (weekend_release), so reading the reaction alone would nudge
    # Evelyn about reports the captains already have. `sent_keys` is the honest
    # answer and it covers both routes.
    done = _sent_keys_from(thread)
    waiting = []
    for block in config.BLOCKS:
        msg = posts.get(block.key)
        if msg is None or _approver_of(msg):
            continue
        if set(block.captains) <= done:
            continue
        if _has_mark(thread, REMIND_MARKER, block.key):
            continue
        # Epoch maths, so no timezone can make this fire early on one machine.
        age_h = (time.time() - float(msg["ts"])) / 3600
        if age_h >= after_hours:
            waiting.append((block, age_h))
    if not waiting:
        if verbose:
            print("— nothing to chase (approved, sent, already reminded, or "
                  "too recent)", flush=True)
        return False
    for block, age_h in waiting:
        n = len(block.members)
        _client().chat_postMessage(
            channel=_channel(channel), thread_ts=parent["ts"],
            text=(f"{_mentions()} — reminder: *{block.label}* ({block.who}) is "
                  f"still unapproved ({age_h:.0f}h). Those {n} reports have "
                  f"not been sent; they need a :white_check_mark: on that "
                  f"block's message above.\n"
                  f"`{_tagged(REMIND_MARKER, block.key)}`"))
        if verbose:
            print(f"✓ reminder posted for {block.key} ({age_h:.1f}h "
                  f"unapproved)", flush=True)
    return True


def close_day(today: dt.date, channel: Optional[str] = None,
              verbose: bool = True) -> bool:
    """Say in the thread that the day ended without an approval. True if posted.

    The checker stops at END_HOUR. Until now that was the whole ending: no
    approval, no send, no message — a day where 12 captains got nothing looked
    identical to a day that went fine, because the only trace was a post with no
    checkmark, scrolling away under everything else. Silence is the worst
    failure mode a review gate can have.

    Says nothing about a block that is decided: an approved-and-sent block is
    already confirmed in the thread, and an approved-but-failed one has its own
    notice. Posts ONCE per block — the checker keeps ticking until midnight.

    PER BLOCK since 2026-08-26, and it says WHICH: a day where Fiber went out
    and NDS did not is a real outcome now, and "nobody approved this today"
    would be a lie about two thirds of it."""
    parent = _find_post(today, channel)
    if parent is None:
        if verbose:
            print(f"— nothing posted for {today:%Y-%m-%d}, nothing to close",
                  flush=True)
        return False
    thread = replies(parent, channel)
    posts = block_posts(today, parent, channel, thread=thread)
    # A WEEKEND AUTO-SEND LEAVES NO REACTION. `_approver_of` only sees a human
    # tick, so on Sun 2026-08-16 this posted "were NOT sent" at 20:12 on a
    # thread that had said "Sent" at 09:10 — the reports HAD gone out, released
    # by weekend_release. Read on Monday, that reads as a weekend that failed.
    # `sent_keys` is the honest answer to "was this decided" and it covers both
    # routes; the reaction only covers one.
    done = _sent_keys_from(thread)
    names = {c.key: c.display_name for c in config.CAPTAINS}
    stuck = []
    for block in config.BLOCKS:
        members = set(block.captains)
        if members <= done:
            continue                       # everyone in it already has theirs
        msg = posts.get(block.key)
        if msg is not None and _approver_of(msg):
            continue                       # approved; the send path owns it
        if _has_mark(thread, CLOSED_MARKER, block.key):
            continue
        stuck.append((block, sorted(members - done)))
    if not stuck:
        if verbose:
            print("— every block is decided or already closed", flush=True)
        return False
    for block, owed in stuck:
        who = ", ".join(names.get(k, k) for k in owed)
        if block.key not in posts:
            body = (f"never made it up for review today, so *{who}* got "
                    f"nothing.")
        elif len(owed) < len(block.captains):
            # Partial: part of the block went out earlier (a held captain, or a
            # tanda). Saying "NOT sent" about the whole block would be wrong.
            body = (f"went out except *{who}*. The preview is still on the "
                    f"mini: fix the source, rebuild, `--refresh --block "
                    f"{block.key}`, and the next check mails only those.")
        else:
            body = (f"nobody approved this today, so those "
                    f"{len(owed)} reports were NOT sent. The previews are "
                    f"still on the mini: approve above and they go out, or "
                    f"leave it and tomorrow's run replaces them.")
        _client().chat_postMessage(
            channel=_channel(channel), thread_ts=parent["ts"],
            text=(f"{_mentions()} — *{block.label}* ({block.who}): {body}\n"
                  f"`{_tagged(CLOSED_MARKER, block.key)}`"))
        if verbose:
            print(f"✓ closed {block.key} — said so in the thread", flush=True)
    return True


def already_sent(msg: dict, channel: Optional[str] = None) -> bool:
    """Has today's WHOLE send already been attempted? The all-or-nothing lock.

    Un envio parcial no cierra el dia: los capitanes retenidos siguen debiendo
    su correo, asi que esto es False y quien decide es `sent_keys`."""
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    return any(SENT_MARKER in (r.get("text") or "") for r in replies[1:])


def _tagged(marker: str, key: str) -> str:
    """The per-block form of a thread marker: "CAPTAINSHIP-NOT-SENT nds"."""
    return f"{marker} {key}"


def _has_mark(thread: list, marker: str, key: str) -> bool:
    """Is this block's marker already in the thread? A BARE marker (nothing
    after it) counts for every block: that is the pre-2026-08-26 whole-day
    form, so a day already reminded/closed under the old shape is not
    re-announced five times by the new code."""
    tag = _tagged(marker, key)
    for m in thread:
        text = m.get("text") or ""
        if tag in text:
            return True
        i = text.find(marker)
        if i < 0:
            continue
        if not text[i + len(marker):].split("`")[0].strip():
            return True
    return False


def _sent_keys_from(thread: list) -> Set[str]:
    """`sent_keys`, off a thread already in hand. Same rules — a bare
    SENT_MARKER means the whole roster, each PARTIAL adds its own keys — but no
    second Slack call, which matters now that five blocks ask the same
    question on every tick."""
    out: Set[str] = set()
    for r in thread:
        text = r.get("text") or ""
        if SENT_MARKER in text and PARTIAL_SENT_MARKER not in text:
            return {c.key for c in config.CAPTAINS}
        out |= _keys_in_marker(text)
    return out


def _keys_in_marker(text: str) -> Set[str]:
    """Las claves anotadas en una linea `CAPTAINSHIP-SENT-ONLY a,b,c`."""
    for line in (text or "").splitlines():
        if PARTIAL_SENT_MARKER in line:
            tail = line.split(PARTIAL_SENT_MARKER, 1)[1]
            return {k.strip(" `,") for k in tail.replace("`", "").split(",")
                    if k.strip(" `,")}
    return set()


def sent_keys(msg: dict, channel: Optional[str] = None) -> Set[str]:
    """Que capitanes YA recibieron su reporte hoy, segun el hilo.

    El candado por capitan. `SENT_MARKER` (envio completo) devuelve a los trece;
    cada `PARTIAL_SENT_MARKER` suma los suyos, asi que un dia que salio en dos
    tandas (doce ahora, el que fallo despues del arreglo) queda bien contado y
    nadie recibe el correo dos veces."""
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    return _sent_keys_from(replies[1:])


def mark_block_sent(parent: dict, block: "config.Block", failures: int,
                    channel: Optional[str] = None, *,
                    sent: Sequence[str] = (),
                    held: Sequence[str] = (), reason: str = "") -> None:
    """Close ONE BLOCK in the thread, cleanly or not.

    Posted after ANY completed attempt, including one with failures, and that is
    deliberate. Leaving it unlocked so a partial failure can retry means the
    captains who DID get their report get it again every 15 minutes; a send that
    needs a human is the lesser problem, and this message is how they find out.

    ALWAYS the per-captain marker, never the bare whole-day one: `sent_keys`
    reads a bare `CAPTAINSHIP-SENT` as "the entire roster is done", which is
    exactly what one block's send must not claim. The blocks add up instead —
    once the last one posts, the union of the markers IS the whole roster."""
    names = {c.key: c.display_name for c in config.CAPTAINS}
    went = ", ".join(names.get(k, k) for k in sorted(sent))
    n_all = len(block.captains)
    if failures:
        head = (f"⚠️ *{block.label}* — sent {len(sent)} of {n_all} with "
                f"{failures} failure(s); see the run log. Nothing will retry on "
                f"its own.")
    elif len(sent) == n_all:
        head = (f"✅ *{block.label}* sent — {went}'s reports are on their way "
                f"to the captains.")
    else:
        head = f"✅ *{block.label}* — sent {len(sent)} of {n_all}: {went}."
    tail = ""
    if held:
        waiting = ", ".join(names.get(k, k) for k in sorted(held))
        tail = (f"\n{_mentions()} — *{waiting}* held back: {reason}. Fix it, "
                f"rebuild and run `review_gate.py --refresh --block "
                f"{block.key}` (same link); the next check mails only the held "
                f"one — nobody gets a second copy.")
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=parent["ts"],
        text=(f"{head}{tail}\n"
              f"`{PARTIAL_SENT_MARKER} {','.join(sorted(sent))}`"))


def mark_sent(msg: dict, failures: int, channel: Optional[str] = None,
              *, sent: Optional[Sequence[str]] = None,
              held: Optional[Sequence[str]] = None,
              reason: str = "") -> None:
    """Close the day in the thread, cleanly or not.

    Posted after ANY completed attempt, including one with failures, and that is
    deliberate. Leaving it unlocked so a partial failure can retry means the
    captains who DID get their report get it again every 15 minutes; a send that
    needs a human is the lesser problem, and this message is how they find out.

    `sent` + `held` = envio PARCIAL: se anota el candado por capitan y se dice
    quien falta y por que, etiquetando a los aprobadores — un capitan retenido
    en silencio es exactamente el agujero que esto viene a tapar.
    """
    if held:
        names = {c.key: c.display_name for c in config.CAPTAINS}
        went = ", ".join(names.get(k, k) for k in sorted(sent or ()))
        waiting = ", ".join(names.get(k, k) for k in sorted(held))
        head = (f"✅ Sent {len(sent or ())} of {len(config.CAPTAINS)} — {went}."
                if not failures else
                f"⚠️ Sent {len(sent or ())} of {len(config.CAPTAINS)} with "
                f"{failures} failure(s) — see the run log.")
        _client().chat_postMessage(
            channel=_channel(channel), thread_ts=msg["ts"],
            text=(f"{head}\n{_mentions()} — *{waiting}* held back: {reason}. "
                  f"Fix it, rebuild the drafts and run `review_gate.py "
                  f"--refresh` (same link); the next check mails only the "
                  f"held one — nobody gets a second copy.\n"
                  f"`{PARTIAL_SENT_MARKER} {','.join(sorted(sent or ()))}`"))
        return
    if sent is not None and len(sent) < len(config.CAPTAINS):
        # LA SEGUNDA TANDA: el que quedo retenido a la mañana, ya arreglado.
        # Cierra el dia con el marcador entero (ahora si estan los trece), pero
        # diciendo que salio solo lo que faltaba — un "Sent" a secas se leeria
        # como que se remandaron los trece.
        names = {c.key: c.display_name for c in config.CAPTAINS}
        who_now = ", ".join(names.get(k, k) for k in sorted(sent))
        note = (f"✅ Sent the remaining {len(sent)} of {len(config.CAPTAINS)} — "
                f"{who_now}. Everyone has today's report now."
                if not failures else
                f"⚠️ Sent the remaining {len(sent)} with {failures} failure(s) — "
                f"see the run log.")
    else:
        note = ("✅ Sent — the reports are on their way to the captains."
                if not failures else
                f"⚠️ Sent with {failures} failure(s) — see the run log. Nothing "
                f"will retry on its own; trigger the rest by hand once it's "
                f"fixed.")
    _client().chat_postMessage(channel=_channel(channel), thread_ts=msg["ts"],
                               text=f"{note}\n`{SENT_MARKER}`")


def hold_weekend(parent: dict, block: "config.Block", reason: str,
                 channel: Optional[str] = None,
                 thread: Optional[list] = None, verbose: bool = True) -> bool:
    """Say ONCE per block that the weekend auto-send did not release it.

    Sat/Sun a clean day mails itself (weekend_release). A day that doesn't has
    nobody watching the channel either, so without this it is silence — the same
    silence as reports that went out fine."""
    if thread is None:
        thread = replies(parent, channel)
    if _has_mark(thread, HELD_MARKER, block.key):
        return False
    what = f"{block.who}'s reports"
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=parent["ts"],
        text=(f"{_mentions()} *{block.label}* — {wr.held_note(reason, what)}\n"
              f"`{_tagged(HELD_MARKER, block.key)}`"))
    if verbose:
        print(f"✓ weekend hold said once for {block.key} — {reason}",
              flush=True)
    return True


def find_approval(today: dt.date, channel: Optional[str] = None,
                  verbose: bool = True) -> dict:
    """{block key: (user_id, name)} for every block carrying an authorised
    checkmark today. Empty dict = nothing approved yet."""
    parent = _find_post(today, channel)
    if parent is None:
        if verbose:
            print(f"— no review post found for {today:%Y-%m-%d}", flush=True)
        return {}
    posts = block_posts(today, parent, channel)
    out = {}
    for block in config.BLOCKS:
        msg = posts.get(block.key)
        if msg is None:
            if verbose:
                print(f"— {block.key}: not up for review yet", flush=True)
            continue
        who = _approver_of(msg)
        if who:
            out[block.key] = who
        elif verbose:
            got = [f":{r['name']}: x{r['count']}"
                   for r in msg.get("reactions", [])]
            print(f"— {block.key}: not approved yet "
                  f"(reactions: {', '.join(got) or 'none'})", flush=True)
    return out


# --------------------------------------------------------------------------
# 4. the send
# --------------------------------------------------------------------------
def scope_today(today: dt.date, *, enabled: bool = True
                ) -> Tuple[Optional[Set[str]], str]:
    """A que capitanes toca lo que hoy frena el dia. (claves | None, motivo).

    None = no se puede acotar, asi que frena todo (ver `scope.held_captains`).
    Un set vacio = nada frena, o lo que frenaba ya se recupero.
    """
    if not enabled:
        return None, "--no-partial: el dia se juzga entero, como antes"
    ids = wr.blocking_reports([REPORT_ID], today,
                              own_ids=[REPORT_ID, "captainship_drafts"])
    if ids is None:
        return None, "no hay estado del dia: no se puede acotar la falla"
    return _scope.held_captains(ids, today)


def send_reviewed(today: dt.date, verbose: bool = True,
                  only: Optional[Sequence[str]] = None) -> int:  # noqa: D401
    """Shell out to run.py --send-reviewed for `today`. A separate process on
    purpose: the sender stays the one command that has ever mailed these, and
    this module never grows its own path to a recipient list.

    `only` = las claves que salen en esta tanda (envio parcial). Es el `--only`
    que run.py ya tenia; el guardian del digest sigue mirando el SET completo de
    .eml del dia, asi que mandar a doce no lo afloja."""
    cmd = [sys.executable, "-m", "automations.captainship_drafts.run",
           "--send-reviewed", "--date", today.isoformat()]
    if only:
        cmd += ["--only", ",".join(only)]
    if verbose:
        print(f"→ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd)


# --------------------------------------------------------------------------
# 5. the deadline
# --------------------------------------------------------------------------
def _alert_deadline_failure(day: dt.date, what: str, detail: str = "") -> None:
    """Tell #claudecorrections-and-requests that the DEADLINE path failed.

    WHY THIS EXISTS (2026-08-15). The 4am orchestrator alerts on its own failed
    reports, but the 10:00 deadline runs from deploy/captainship_review.sh — a
    standalone 15-minute agent the orchestrator knows nothing about. On
    2026-08-15 its build failed at 12:01 and its review post at 12:03; the Hub
    card went red, the reports never went up for review, and the channel was
    never told. Megan's standing rule is that every fail reaches that channel in
    real time, so this path needs its own voice.

    ONE THREAD PER DAY (incident key carries the date): the agent ticks every 15
    minutes, and a still-broken day must not repost — it replies under the first
    message instead. Best-effort: an alert must never sink the tick.
    """
    try:
        from automations.day_orchestrator import notify
        lines = [
            f"Reports for {day.month}/{day.day} are NOT up for review — {what}.",
            "",
            "*What this means:* that block's link was not posted to "
            "#revision-emails, so there is nothing for Evelyn to ✅ and those "
            "captain reports have not gone out. Any OTHER block that did post "
            "is unaffected — the blocks are approved and sent separately.",
        ]
        if detail:
            lines += ["", detail]
        lines += [
            "",
            "*To fix it now:* `lucy rerun captainship_drafts` (rebuilds the "
            "previews), then `lucy rerun captainship_drafts_review` (posts a "
            "PDF per block for approval; a block already up for review is left "
            "alone). The agent also retries on its own every 15 min until 8pm.",
        ]
        notify.post_alert("✉️ *Captainship Reports — deadline path failed*",
                          lines, tag="captainship-deadline",
                          incident=f"captainship-deadline-{day.isoformat()}")
    except Exception as e:  # noqa: BLE001 — an alert must never break the tick
        print(f"  (corrections alert skipped: {e})", flush=True)


def ensure_posted(today: dt.date, channel: Optional[str] = None,
                  verbose: bool = True, blocks=None) -> int:
    """THE 11:00 DEADLINE (Eve, 2026-08-04: "necesito que estos drafts se armen
    como tarde a las 11 am central time"). If the day's reports are already up
    for review, do nothing at all. If they are not, build them with whatever the
    boxes have and post them.

    WHY A DEADLINE AND NOT AN EARLIER SLOT. The normal path is not slow: on a
    good day the link is up between 07:20 and 09:03. What breaks the promise is a
    dependency that FAILS and comes back hours later, dragging the rest of the
    chain with it — captainship_churn died at 06:24 on 2026-07-31 and retried at
    10:28, so the reports posted at 11:20; abp_6days failed at 11:49 on
    2026-07-30 and the day's post landed at 12:00; on 2026-07-29 the drafts never
    ran at all and nobody was told. Moving the chain earlier in the morning would
    not have saved a single one of those days. A deadline does, and it costs no
    other report its slot.

    HELD TO THE SAME STANDARD AS THE 4am BUILD: `run.py --dry-run` only writes
    previews to output/ — it mails nobody — and the twelve reports still go out
    only on a checkmark from Evelyn. This makes them ASKABLE by 11:00;
    it does not make them sent.

    Reuses previews already on disk. On 2026-07-30 the build succeeded and only
    the review post failed; re-rendering twelve reports to fix a failed upload
    would spend 20 minutes re-deciding something already decided.

    IDEMPOTENT PER BLOCK, and that is what makes it safe to call from a
    15-minute agent: a block already up for review — approved or not — is left
    alone, so the later slots cannot re-post a link under the approvers. Only a
    block with NO link at all builds anything.

    BLOCK BY BLOCK since 2026-08-26, and this is where the split earns its keep:
    each block prints, uploads and posts before the next one starts, so Fiber 1
    is askable while NDS is still being assembled. A block that fails to build
    costs only itself — the rest still go up, and --close-day names the one that
    never made it.
    """
    todo = list(blocks) if blocks else list(config.BLOCKS)
    parent = None
    existing: dict = {}
    try:
        parent = _find_post(today, channel)
        if parent is not None:
            existing = block_posts(today, parent, channel)
    except Exception as e:  # noqa: BLE001 — a Slack read must not lose the day
        print(f"✗ could not read the review thread: {type(e).__name__}: {e}",
              flush=True)
        _alert_deadline_failure(
            today, f"the review thread could not be read ({type(e).__name__})",
            f"Error: {str(e)[:300]}")
        return 1

    pending = [b for b in todo if b.key not in existing]
    if not pending:
        if verbose:
            print(f"— every block for {today:%Y-%m-%d} is already up for "
                  f"review; nothing to do", flush=True)
        return 0

    failures = 0
    for block in pending:
        have = preview_htmls(today, block)
        if not have:
            if verbose:
                print(f"— {block.key}: no previews and nothing posted, "
                      f"building it now (deadline)", flush=True)
            cmd = [sys.executable, "-u", "-m",
                   "automations.captainship_drafts.run",
                   "--dry-run", "--block", block.key,
                   "--date", today.isoformat()]
            print(f"→ {' '.join(cmd)}", flush=True)
            rc = subprocess.call(cmd)
            have = preview_htmls(today, block)
            if not have:
                failures += 1
                print(f"✗ {block.key}: the deadline build produced no previews "
                      f"(exit {rc}) — nothing posted for it. The next tick "
                      f"tries again.", flush=True)
                _alert_deadline_failure(
                    today,
                    f"the deadline build for {block.label} ({block.who}) "
                    f"exited {rc} and wrote no previews — that block was not "
                    f"posted",
                    "This ran from the review agent "
                    "(deploy/captainship_review.sh), NOT the 4am orchestrator, "
                    "so the orchestrator's own failure alert never covers it. "
                    "Check output/ for captainship_draft_*_{}.html.".format(
                        today.strftime("%Y%m%d")))
                continue
            if rc != 0:
                # Partial: run.py exits 1 when a captain fails, but the ones
                # that did build are real reports and must still be reviewable.
                print(f"  ⚠ {block.key}: the build exited {rc} but wrote "
                      f"{len(have)} preview(s) — posting those", flush=True)
        elif verbose:
            print(f"— {block.key}: {len(have)} preview(s) already on disk, "
                  f"never posted: posting them", flush=True)

        # The previews exist; only the print → Drive → Slack leg is left. It is
        # also the leg that fails on a flaky network (2026-08-15: SSL handshake
        # timeouts to Slack) and on a missing package (2026-08-26: no pypdf on
        # the mini), and a traceback here used to be the whole story — the agent
        # exited, the next tick tried again, and nobody was told on the day it
        # never recovered. Alert, then keep going: one block's failed upload
        # must not cost the other four their link.
        try:
            if parent is None:
                parent = ensure_parent(today, channel, verbose=verbose)
            post_block(
                upload_pdf(build_pdf(today, block),
                           description=eml_digest(today, block)),
                today, block, parent, channel, verbose=verbose)
        except Exception as e:  # noqa: BLE001 — report it, don't swallow it
            failures += 1
            print(f"✗ {block.key}: the deadline post failed: "
                  f"{type(e).__name__}: {e}", flush=True)
            _alert_deadline_failure(
                today,
                f"{block.label}'s previews are built but posting them failed "
                f"({type(e).__name__})",
                f"Error: {str(e)[:300]}\nThe previews are already on disk, so "
                f"the fix is just the post: `lucy rerun "
                f"captainship_drafts_review`.")
    return 1 if failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--post", action="store_true",
                    help="build ONE PDF PER BLOCK, upload each, and post its "
                         "link in the day's thread. RUN ON THE MINI so it "
                         "comes from Lucy. Scope with --block.")
    ap.add_argument("--refresh", action="store_true",
                    help="rebuild each block's PDF and update the one already "
                         "in Drive, WITHOUT posting again. For when a draft is "
                         "rebuilt after the link went out. Wins over --post. "
                         "Scope with --block to touch only what you rebuilt.")
    ap.add_argument("--check", action="store_true",
                    help="look for an authorised checkmark ON EACH BLOCK; with "
                         "--send, mail every block that has one. Blocks are "
                         "independent — approving Fiber 1 sends Fiber 1. Run "
                         "on Eve's box.")
    ap.add_argument("--send", action="store_true",
                    help="with --check: actually send. Without it, --check only "
                         "reports what it found.")
    ap.add_argument("--mark-sent-only", default=None, metavar="KEYS",
                    help="anotar en el hilo que estos capitanes YA recibieron "
                         "su reporte, SIN mandar nada. Para cuando la tanda "
                         "salio por fuera del gate (run.py --send-reviewed "
                         "--only a mano): sin esa marca, un ✅ posterior les "
                         "manda una segunda copia.")
    ap.add_argument("--no-partial", action="store_true",
                    help="con --check: no acotar. Si algo fallo, frena a los "
                         "trece como antes en vez de mandar a los que no "
                         "estan tocados.")
    ap.add_argument("--no-auto", action="store_true",
                    help="never release without a checkmark, not even on the "
                         "weekend (weekend_release).")
    ap.add_argument("--remind", action="store_true",
                    help="nudge the channel about any BLOCK still unapproved "
                         "--after-hours since ITS link went up. Nudges once "
                         "per block.")
    ap.add_argument("--after-hours", type=float, default=REMIND_AFTER_HOURS,
                    help=f"hours since the post before --remind fires "
                         f"(default {REMIND_AFTER_HOURS}).")
    ap.add_argument("--close-day", action="store_true",
                    help="say in the thread which BLOCKS ended the day "
                         "unapproved, so a block nobody reacted to isn't "
                         "silent. Says it once per block, and nothing at all "
                         "about a block that already went out.")
    ap.add_argument("--ensure-posted", action="store_true",
                    help="THE DEADLINE. Per block: one already up for review "
                         "is skipped; one that isn't gets built with whatever "
                         "the boxes have and posted, before the next block "
                         "starts. Mails nobody — the checkmark still does "
                         "that. Driven by deploy/captainship_review.sh at "
                         "10:00 CT.")
    ap.add_argument("--pdf-only", action="store_true",
                    help="build the PDF and stop (no Drive, no Slack).")
    ap.add_argument("--preview", action="store_true",
                    help="build the PDF, upload it under a PREVIEW- name and "
                         "print the link. Posts NOTHING and never touches the "
                         "day's reviewed PDF — for looking at a change before "
                         "it goes out.")
    ap.add_argument("--channel", default=None,
                    help="override the channel id (for a one-off test).")
    ap.add_argument("--date", default=None,
                    help="run date (default today). The reports are for the "
                         "day BEFORE, same as run.py.")
    ap.add_argument("--block", default=None,
                    help="limit every action to these BLOCK keys "
                         f"({', '.join(b.key for b in config.BLOCKS)}). "
                         "Default: all of them, in order.")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()

    if args.block:
        bkeys = [b.strip() for b in args.block.split(",") if b.strip()]
        unknown_b = [b for b in bkeys if b not in config.BLOCK_BY_KEY]
        if unknown_b:
            print(f"Unknown block key(s): {unknown_b}. "
                  f"Valid: {[b.key for b in config.BLOCKS]}")
            return 1
        blocks = [config.BLOCK_BY_KEY[b] for b in bkeys]
    else:
        blocks = list(config.BLOCKS)

    if args.pdf_only:
        for block in blocks:
            build_pdf(today, block)
        return 0

    if args.preview:
        # A LOOK, not a review. Two rules make it safe to run on a day whose
        # real link is already out and already approved:
        #   * its own Drive name (PREVIEW-…-HHMM), so the reviewed PDF behind
        #     the link people already have is untouched — replacing that file
        #     is what `--refresh` is for, and doing it by accident would swap
        #     the document under an approval that already fired;
        #   * it posts nothing, so no second link competes with the real one
        #     (the standing rule: never two messages to choose between).
        import shutil
        stamp = dt.datetime.now().strftime("%H%M")
        for block in blocks:
            pdf = build_pdf(today, block)
            shot = pdf.with_name(f"PREVIEW-{pdf.stem}-{stamp}.pdf")
            shutil.copyfile(pdf, shot)
            link = upload_pdf(shot, description="preview — not for approval")
            print(f"\n  {block.key} preview PDF: {link}")
        print("  (nothing was posted; the day's reviewed PDFs are untouched)")
        return 0
    # Before --post: the deadline agent passes only this flag, but keeping it
    # ahead of --post means a queued `--post --ensure-posted` can never turn
    # into a second post for a day that is already asked.
    # ANTES de --post: el scheduler pasa --post como base_args, asi que
    # `lucy rerun captainship_drafts_review --mark-sent-only a,b` llega aca
    # como "--post --mark-sent-only a,b" y tiene que significar la marca.
    if args.mark_sent_only:
        # Solo bookkeeping: pone el candado por capitan en el hilo. Corre en la
        # MINI para que la linea salga como Lucy, igual que el resto del hilo.
        keys = [k.strip() for k in args.mark_sent_only.split(",") if k.strip()]
        unknown = sorted(set(keys) - {c.key for c in config.CAPTAINS})
        if unknown:
            print(f"Unknown captain key(s): {unknown}", flush=True)
            return 1
        msg = _find_post(today, args.channel)
        if msg is None:
            print("— no review post for today; nothing to mark", flush=True)
            return 1
        mark_sent(msg, 0, args.channel, sent=keys,
                  held=sorted({c.key for c in config.CAPTAINS} - set(keys)),
                  reason="sent by hand outside the gate")
        print(f"✓ marked {len(keys)} captain(s) as already sent", flush=True)
        return 0
    if args.ensure_posted:
        return ensure_posted(today, args.channel, blocks=blocks)
    # Checked BEFORE --post on purpose. The scheduler entry's base_args are
    # ["--post"], so `lucy rerun captainship_drafts_review --refresh` arrives
    # here as "--post --refresh" and has to mean refresh — otherwise the one
    # case this exists for could not be triggered the one way it is triggered.
    if args.refresh:
        # Every block by default — the rebuild that prompts a --refresh is
        # usually `run.py --dry-run` over all of them. Scope it with --block
        # when only one tanda was rebuilt: refreshing a block nobody touched
        # rewrites a PDF for no reason, and each block's Drive file carries its
        # own fingerprint now.
        for block in blocks:
            link = upload_pdf(build_pdf(today, block),
                              description=eml_digest(today, block))
            # Same name = same day + same block, so upload_pdf updated the file
            # IN PLACE and the link already in the thread now shows the rebuilt
            # PDF. Nothing is posted: a correction must not ping the approvers a
            # second time with a second message for them to choose between.
            print(f"✓ {block.key} refreshed in place, existing link still "
                  f"valid: {link}", flush=True)
        return 0
    if args.post:
        parent = ensure_parent(today, args.channel)
        for block in blocks:
            post_block(upload_pdf(build_pdf(today, block),
                                  description=eml_digest(today, block)),
                       today, block, parent, args.channel)
        return 0
    if args.remind:
        return 0 if remind(today, args.after_hours, args.channel) else 1
    if args.close_day:
        close_day(today, args.channel)
        return 0
    if args.check:
        # NO POST, NO SEND (2026-08-19). The SENT lock lives in the thread
        # (mark_block_sent), so sending before the thread exists mails reports
        # with nothing to write the lock into — and the next tick, 15 minutes
        # later, mails them again. Only the weekend auto-release can reach here
        # without a post (a human ✅ implies one), and it is easy to hit: the
        # checker's window opens at 07:00 and the previews are built by ~06:15,
        # so on a clean Saturday the 07:00 tick finds the chain DONE a quarter
        # of an hour before the 07:15 agent puts the links up. Wait for it — the
        # very next tick sends, with a thread to lock.
        parent = _find_post(today, args.channel)
        if parent is None:
            print(f"— no review thread for {today:%Y-%m-%d} yet; nothing to "
                  f"check (the send lock lives in it)", flush=True)
            return 1
        thread = replies(parent, args.channel)
        posts = block_posts(today, parent, args.channel, thread=thread)
        approved = {k: _approver_of(m) for k, m in posts.items()
                    if _approver_of(m)}
        # El candado es POR CAPITAN: `sent_keys` cuenta lo que ya salio hoy
        # (todo, o la tanda parcial de un rato antes), asi que el que quedo
        # retenido puede salir mas tarde sin que nadie reciba dos copias. Vale
        # entre bloques igual que dentro de uno.
        done = _sent_keys_from(thread)

        # EL DIA SE JUZGA UNA VEZ, LOS BLOQUES SE MANDAN POR SEPARADO. Both the
        # weekend auto-release and the partial-send scope read the DAY's state,
        # not a block's, so they are asked once here and then applied to each
        # block in turn — asking per block would be five identical answers and
        # five reads of the same file.
        auto = None
        held_keys: Set[str] = set()
        held_why = ""
        unticked = [b for b in blocks if b.key in posts and b.key not in approved
                    and not set(b.captains) <= done]
        if unticked:
            # Sat/Sun nobody is in the channel to tick it. A day whose whole
            # chain is DONE releases itself; anything short of that keeps
            # waiting for a human (Eve 2026-08-12).
            # own_ids = LA PIERNA PROPIA de este reporte. Su estado ya no
            # decide: lo decide `previews_complete`, que mira los .eml. El
            # sabado 8/15 estos dos figuraban MISSED_NOT_READY con los
            # borradores armados, y eso freno un dia que no tenia nada malo.
            # Todo lo que esta AGUAS ARRIBA (los 8 modulos de metricas) sigue
            # necesitando DONE, porque es contenido del correo.
            ok, why = wr.auto_release(
                [REPORT_ID], today, enabled=not args.no_auto,
                own_ids=[REPORT_ID, "captainship_drafts"],
                verify=lambda: previews_complete(
                    today, [k for b in unticked for k in b.captains]))
            print(f"  weekend auto-send: {why}", flush=True)
            if ok:
                auto = (wr.AUTO_ID, wr.AUTO_WHO)
            else:
                # UNA FALLA QUE TOCA A UN CAPITAN NO FRENA A LOS OTROS DOCE
                # (Eve 2026-08-22). Se pregunta a quien afecta lo que freno el
                # dia; si cae en un subconjunto, sale el resto y ese espera.
                # `None` = no se puede acotar -> el hold de siempre.
                held, scope_why = scope_today(today,
                                              enabled=not args.no_partial)
                weekend_auto = wr.is_weekend(today) and not args.no_auto
                going = [k for b in unticked for k in b.captains
                         if k not in (held or ())]
                ready, ready_why = (previews_complete(today, going)
                                    if held is not None and weekend_auto and going
                                    else (False, "sin envio parcial"))
                if held is None or not weekend_auto or not ready:
                    if args.send and wr.is_weekend(today) and not args.no_auto:
                        detail = why if held is None else f"{why} ({ready_why})"
                        for block in unticked:
                            hold_weekend(parent, block, detail, args.channel,
                                         thread=thread)
                else:
                    auto = (wr.AUTO_ID, wr.AUTO_WHO)
                    held_keys, held_why = set(held), f"{why} — {scope_why}"
                    print(f"  envio parcial: {scope_why}; salen {len(going)} "
                          f"({ready_why})", flush=True)
        if not args.no_partial and not held_keys:
            # Dia habil, con ✅ (o un bloque ya aprobado). La misma regla: el
            # capitan cuyo contenido se cayo espera el arreglo y los demas salen
            # ahora. Si no se puede acotar (`None`), manda la aprobacion humana
            # y sale todo, como siempre — un ✅ no se reinterpreta.
            hit, scope_why = scope_today(today, enabled=True)
            if hit:
                held_keys, held_why = set(hit), scope_why
                print(f"  envio parcial: {scope_why}", flush=True)

        # Tell the Hub the humans said yes — this is what turns the card's phase
        # pill from purple (awaiting ✅) to green. Only once EVERY block is
        # released: a tile that greened on the first of five checkmarks would
        # say the day was done with eight reports still unapproved. Idempotent,
        # so the 15-minute checker writes one row a day, not one per pass.
        released = {}
        for b in config.BLOCKS:
            who = approved.get(b.key) or (auto if b.key in posts else None)
            if who is None and set(b.captains) <= done:
                who = (wr.AUTO_ID, "already sent earlier today")
            if who is not None:
                released[b.key] = who
        if len(released) == len(config.BLOCKS):
            RA.ensure_recorded(HUB_CARD_ID, HUB_CARD_NAME,
                               released[config.BLOCKS[0].key], day=today)

        pending = 0
        failures = 0
        for block in blocks:
            who = released.get(block.key)
            if who is None:
                pending += 1
                continue
            print(f"✓ {block.key} ({block.who}) approved by {who[1]}",
                  flush=True)
            if not args.send:
                continue
            going = [k for k in block.captains
                     if k not in held_keys and k not in done]
            if not going:
                held_here = [k for k in block.captains if k in held_keys]
                if held_here:
                    pending += 1      # its captains are waiting on a fix
                print(f"— {block.key}: nothing left to send "
                      f"({len([k for k in block.captains if k in done])} "
                      f"already out, {len(held_here)} held)", flush=True)
                continue
            n = send_reviewed(today, only=going)
            failures += n
            mark_block_sent(parent, block, n, args.channel, sent=going,
                            held=[k for k in block.captains if k in held_keys],
                            reason=held_why)
            if [k for k in block.captains if k in held_keys]:
                pending += 1          # the held ones still owe a mail
            # Re-read once per send so the NEXT block in this same pass sees the
            # lock we just wrote — cheap, and it is the only thing standing
            # between a crash mid-loop and a double send.
            thread = replies(parent, args.channel)
            done = _sent_keys_from(thread)
        if failures:
            return failures
        # exit 1 while anything is still waiting: that is what makes
        # deploy/captainship_review.sh fire the reminder and keep ticking.
        return 1 if pending else 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
