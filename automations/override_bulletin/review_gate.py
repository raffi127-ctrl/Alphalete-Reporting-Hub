"""The approval gate between building the DD / Organization Bulletin and mailing it.

Same shape as the Org Sales Board and captainship gates, so there is ONE review
habit and not three:

    review_gate.py --post           build the pages -> PDF -> Drive -> Lucy posts
                                    the link in #revision-emails
    review_gate.py --refresh        the Sheet was corrected after the link went
                                    out: rebuild and overwrite the PDF in Drive,
                                    SAME link, NO second post
    review_gate.py --check --send   Evelyn's checkmark mails it

WHO APPROVES: **EVELYN ONLY** (Eve, 2026-08-06 — "que la unica aprobadora para
este bulletin sea Evelyn"). This gate got there first; since 2026-08-13 all four
gates in the channel are Evelyn-only, because Jolie left the company. A checkmark
from Lucy or from anyone else leaves the gate closed and sends nothing — Slack
reports who reacted, so that is enforceable rather than a convention. See
APPROVERS below.

WEEKLY, NOT DAILY. The other gates key their post off a date; this one keys off
the WEEK ENDING label ("8.2.26"), because that is what the bulletin carries and
what makes a post unique. Both halves derive it the same way — the Sunday that
just ended, Central — so --check finds --post's message without either run
telling the other anything.

THE REVIEWED PDF AND THE SENT EMAIL ARE BUILT TWICE. `send.py --dd` rebuilds the
pages from the live Sheet at send time; it does not mail the PDF that was
approved. That is how the sender works, and it is the right default for a report
whose numbers keep settling — but it means a Sheet edited between the checkmark
and the send changes what goes out. The thread confirmation therefore names the
week AND the headline that actually went, so a drift is visible after the fact.

BLOCKING PROBLEMS DO NOT STOP THE POST. `dd_data.load()` flags a figure it knows
is wrong. The post still goes up, WITH the list in the message — a bulletin that
cannot go out has to be visible, not silently absent. The refusal itself lives in
`send.py`, and note the two tiers: with `--notify` (how the Thursday send runs) a
`blocking` problem alerts #claudecorrections and mails ANYWAY; only `hard_block`
refuses outright. Both are listed in the post, hard ones first.
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from automations.override_bulletin import dd_build as DB
from automations.override_bulletin import dd_data as D

# The private channel the other three gates already use (#revision-emails).
# Hardcoded for the same reason they hardcode it: the reporting token can
# neither create a channel nor list channels by name. A rename keeps the id.
REVIEW_CHANNEL = "C0BLLU9M0A2"

# EVELYN ONLY — see the module docstring. This was the first gate to drop the
# Evelyn+Jolie pair; the other three followed on 2026-08-13 when Jolie left, so
# every gate in the channel now holds exactly this one id.
APPROVERS = {
    "U088E2KJEV8": "Evelyn",
}
# Any of Slack's checkmarks: nobody should have to remember which green tick is
# "the" one, and picking the wrong one must not silently mean "not yet".
APPROVE_EMOJI = {"white_check_mark", "heavy_check_mark",
                 "ballot_box_with_check", "check"}

# The first line of the post, and how --check finds it. PREFIX-matched, and four
# gates share this channel, so this string must not be a prefix of — nor start
# with — "Captainship Reports", "Org Sales Board Email" or "Country Sales Board
# Email". "Organization Bulletin" collides with none of them. Check that again
# before renaming it.
TITLE = "Organization Bulletin"          # + " — WE 8.2.26"
REMIND_MARK = "reminder: the Organization Bulletin"
SENT_MARK = "Sent — approved by"
FAILED_MARK = "Could not send"
CLOSED_MARK = "Not sent — nobody approved"
REMIND_AFTER_HOURS = 3.0

DRIVE_FOLDER_NAME = "Organization Bulletin - para revisar"
KEEP_LAST_PDFS = 30


def week_label(today: Optional[dt.date] = None) -> str:
    """The week ending the bulletin covers, as the tab spells it ('8.2.26').

    Derived, never passed between runs: --post and --check are separate
    processes and this is what lets them agree on which message is today's.
    Same helper the data layer uses, so a Thursday run and the tab's newest
    column name the same week — and when they disagree, `dd_data.load()` blocks
    the send rather than letting this quietly title the wrong week."""
    return D.fmt_week(D.week_just_ended(today))


def _title(today: Optional[dt.date] = None) -> str:
    return f"{TITLE} — WE {week_label(today)}"


def _mentions() -> str:
    """The approver as a real Slack mention. A plain "Evelyn" lights nothing up
    and the post is lost among every other channel she is in."""
    return " ".join(f"<@{uid}>" for uid, _ in
                    sorted(APPROVERS.items(), key=lambda kv: kv[1]))


# --------------------------------------------------------------------------
# 1. the pages + the PDF
# --------------------------------------------------------------------------
def build_preview(verbose: bool = True):
    """Build the review pages. Returns (html_paths, data).

    Calls the data layer ONCE and hands the result to the builder. Not a shell
    out to `send.py --dd`: that would read the whole workbook a second time, and
    Sheets' 60-reads-a-minute ceiling is a real failure mode in this repo. The
    returned data is what tells --post whether anything blocks the send.

    THREE pages since 2026-09-03 (Eve): the two bulletin pages plus the "Up and
    Coming RCs and NCs" companion, so the reviewer approves everything that goes
    out from ONE link instead of only seeing the companion after it was mailed.
    The companion is still MAILED separately by `send_companion` — this adds it
    to what gets reviewed, it does not change any recipient list."""
    d = D.load()
    paths = list(DB.build(data=d))
    if verbose:
        print(f"✓ pages built — week {d['weeks'][0]}, "
              f"headline {DB._fmt(d['headline'])}", flush=True)
    paths += _companion_page(d, verbose=verbose)
    return paths, d


def _companion_page(d, verbose: bool = True) -> list:
    """The 'Up and Coming RCs and NCs' page, as a 1-item list (empty on failure).

    BEST-EFFORT ON PURPOSE, exactly like `send_companion`: it reads a second tab
    (`Org Tree`) and the bulletin must still reach the reviewer if that read
    fails. A failure prints and is recorded in `problems` (so the Hub's "show
    the numbers" names it) but NEVER in `blocking` — the companion carries no
    money, its absence cannot make the bulletin wrong, and a two-page link is
    still a reviewable bulletin. Reuses the dd data already in hand, so this
    costs no second read of the DD tab."""
    try:
        from automations.override_bulletin import rcs_ncs_build as RB
        from automations.override_bulletin import rcs_ncs_data as RD
        p = RB.build(data=RD.load(dd=d))
        if verbose:
            print(f"✓ companion page built — {Path(p).name}", flush=True)
        return [Path(p)]
    except Exception as e:  # noqa: BLE001 — never lose the bulletin over the rider
        msg = ("the 'Up and Coming RCs and NCs' page could not be built "
               "({}: {}) — the link holds the two bulletin pages only".format(
                   type(e).__name__, e))
        print(f"  ({msg})", flush=True)
        try:
            d.setdefault("problems", []).append(msg)
        except Exception:  # noqa: BLE001
            pass
        return []


def build_pdf(html_paths=None, verbose: bool = True) -> Path:
    """Render the review pages into one PDF.

    A PDF and not the HTML: Drive shows a PDF inline, so a reviewer opens the
    link and reads it — an .html in Drive downloads instead.

    ONE TALL PAGE PER SHEET, not Letter. The bulletin's tables are a single
    column of 45 rows; paginating them to Letter splits a table across a page
    break and the reviewer loses the totals line. Printed from the HTML rather
    than from the PNGs so the text stays selectable and the file stays ~2.5 MB
    instead of ~60."""
    from patchright.sync_api import sync_playwright
    # ensure() and not a bare import — same missing-package break the
    # captainship gate hit on 2026-08-26 (see automations/shared/pkg.py).
    from automations.shared.pkg import ensure
    PdfWriter = ensure("pypdf").PdfWriter

    if html_paths:
        paths = [Path(p) for p in html_paths]
    else:
        # --pdf-only, off pages already on disk. The companion is OPTIONAL here:
        # an older build left only the two bulletin pages behind, and that has to
        # keep producing a PDF rather than raising.
        paths = [DB.OUT_DIR / "dd-bulletin-1.html", DB.OUT_DIR / "dd-bulletin-2.html"]
        companion = DB.OUT_DIR / "rcs-ncs.html"
        if companion.exists():
            paths.append(companion)
    for p in paths:
        if not p.exists():
            raise RuntimeError(f"no page at {p} — build it first (--post does)")
    out = DB.OUT_DIR / f"Organization-Bulletin-WE-{week_label()}.pdf"
    parts = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1180, "height": 1200})
        try:
            for i, html in enumerate(paths, 1):
                page.goto(html.resolve().as_uri(), wait_until="networkidle")
                page.wait_for_timeout(600)
                tall = page.evaluate("document.body.scrollHeight")
                # Sheet width comes from the PAGE, not a constant: the bulletin
                # pages are 1180px but the companion body is 1000px, and printing
                # a narrower page at 1180 leaves a white strip down the side (the
                # dark background is painted on <body>, not on <html>).
                wide = page.evaluate("Math.ceil(document.body.scrollWidth)") or 1180
                part = DB.OUT_DIR / f"_rg_page{i}.pdf"
                page.pdf(path=str(part), print_background=True,
                         width=f"{wide}px", height=f"{tall + 40}px",
                         margin={"top": "0", "bottom": "0",
                                 "left": "0", "right": "0"})
                parts.append(part)
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
def upload_pdf(pdf: Path, verbose: bool = True,
               folder_name: str = DRIVE_FOLDER_NAME,
               keep_last: int = KEEP_LAST_PDFS) -> str:
    """Put the PDF in Drive and return a link the reviewer can open.

    Reuses the fiber_activations Drive token (alphaletereporting, drive.file
    scope — it can only touch files it created, which is all this needs).

    NOTHING IS SHARED BY CODE. The file lands in alphaletereporting's own Drive
    and the reviewers sign in as alphaletereporting, so the link already works
    for them. An anyone-with-the-link permission on a file holding the whole
    org's weekly DD is one forward away from being public. Same reasoning as the
    other three gates."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    from automations.fiber_activations import drive_auth

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
        # Same name = same week. Update IN PLACE so --refresh keeps the link the
        # reviewer may already have open.
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
    try:
        from automations.shared.drive_prune import prune_folder
        prune_folder(svc, fid, keep_last, verbose=verbose)
    except ImportError:
        # drive_prune lives upstream; a checkout without it must still be able
        # to post. The folder just keeps growing until that machine updates.
        if verbose:
            print("  (drive_prune not available here — folder not pruned)",
                  flush=True)
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
            "REVIEW_CHANNEL is unset — paste the review channel's id here. The "
            "reporting token can neither create it nor find it by name.")
    return ch


def _said(replies, *marks) -> bool:
    """Has one of our own thread replies already said `marks`? Substring, not
    startswith — the replies open with the mention. Safe, because only our own
    messages live in this thread."""
    return any(any(m in (r.get("text") or "") for m in marks)
               for r in replies[1:])


def _all_posts(today: Optional[dt.date] = None,
               channel: Optional[str] = None) -> list:
    """Every review post for this week, newest first.

    PREFIX match, never "anywhere in the text": four gates share this channel
    and every post opens with its own title, so a plain `in` would let a title
    that merely CONTAINS this one be picked up here — and a checkmark meant for
    another report would release the bulletin."""
    want = _title(today)
    hist = _client().conversations_history(channel=_channel(channel), limit=100)
    return [m for m in hist.get("messages", [])
            if (m.get("text") or "").lstrip("*").startswith(want)]


def _find_post(today: Optional[dt.date] = None,
               channel: Optional[str] = None) -> Optional[dict]:
    posts = _all_posts(today, channel)
    return posts[0] if posts else None


def _approver_of(msg: dict) -> Optional[Tuple[str, str]]:
    """(id, name) of the first AUTHORISED checkmark, else None.

    A tick from anyone who is not in APPROVERS simply falls through and the gate
    stays closed. That is the whole enforcement."""
    for rx in msg.get("reactions", []):
        if rx.get("name") not in APPROVE_EMOJI:
            continue
        for uid in rx.get("users", []):
            if uid in APPROVERS:
                return uid, APPROVERS[uid]
    return None


def post_review(link: str, blocking=None, today: Optional[dt.date] = None,
                channel: Optional[str] = None, repost: bool = False,
                verbose: bool = True) -> str:
    """Post this week's link. Returns the message ts.

    RUN THIS ON THE MINI — the Slack user token there is Lucy's, and that is the
    only reason the message arrives from Lucy. On Eve's box it is Evelyn's, and
    the post would read as the approver approving her own report."""
    blocking = list(blocking or [])
    warn = ""
    if blocking:
        # Named in the post, not just in a log on a machine nobody reads. An
        # approver has to know the checkmark will not release this until the
        # figures are fixed, or she reacts and assumes it went.
        bullets = "\n".join(f"• {b}" for b in blocking[:6])
        more = (f"\n• …and {len(blocking) - 6} more" if len(blocking) > 6 else "")
        warn = (f"\n\n:warning: *{len(blocking)} problem(s) BLOCK the send* — "
                f"a checkmark will not release it until these are fixed:\n"
                f"{bullets}{more}")
    # The reviewer approves the PDF, but what goes out is the PDF *plus* the
    # email body — so a week carrying a one-off note has to show that note here.
    # Approving a correction email without seeing the apology line in it is
    # approving something you were not shown.
    from automations.override_bulletin.send import dd_one_off_note
    note = dd_one_off_note(week_label(today))
    note_line = (f"\n\n:memo: *This week the email carries a note above the "
                 f"bulletin:*\n>{note}" if note else "")
    text = (f"*{_title(today)}*\n"
            f"{link}\n\n"
            f"{_mentions()} — please review and react with "
            f":white_check_mark: to send it. Nothing goes out until then."
            f"{note_line}{warn}")

    cli = _client()
    olds = _all_posts(today, channel)
    # IDEMPOTENT BY DEFAULT, unlike the daily gates. The Thursday agent makes
    # SEVEN passes between 10:30 and 13:00, and each one calls --post; a gate
    # that deleted and re-posted every pass would ping Evelyn seven times and
    # hand her seven links to choose between. One post per week, and a
    # correction goes out with --refresh (same link, no second message) — the
    # standing rule for every gated report in this repo.
    #
    # NEVER destroy an approval either: re-posting over a checkmark would delete
    # a human's decision and silently reset the gate to "waiting".
    if olds and not repost:
        who = _approver_of(olds[0])
        if verbose:
            print(f"— {_title(today)} is already posted"
                  f"{f' and approved by {who[1]}' if who else ''}; leaving it "
                  f"alone (use --refresh to update the PDF, --repost to "
                  f"replace the message)", flush=True)
        return olds[0]["ts"]
    for old in olds:
        if _approver_of(old):
            if verbose:
                print("— refusing to --repost over an approval", flush=True)
            return old["ts"]
        try:
            cli.chat_delete(channel=_channel(channel), ts=old["ts"])
            if verbose:
                print(f"  (replaced the earlier post for {_title(today)})",
                      flush=True)
        except Exception as e:  # noqa: BLE001 — a stale post must not block this
            print(f"  (could not remove the earlier post: {type(e).__name__})",
                  flush=True)
    r = cli.chat_postMessage(channel=_channel(channel), text=text,
                             unfurl_links=False)
    if verbose:
        print(f"✓ posted to {_channel(channel)} ts={r['ts']}", flush=True)
    # PHASE 1 of the card's 2-phase pill (daily_runs:2): the review link is up,
    # waiting on the checkmark. Published HERE, not by the Thursday wrapper
    # grepping its own pass log, so a post made outside a wrapper pass
    # (`lucy rerun dd_bulletin_gate`) counts too — 2026-08-20 the link was
    # posted by hand at 9:29 and the card sat white all morning. Only the
    # week's FIRST post counts: a --repost replacement (olds non-empty) would
    # otherwise add a second row and green the card without any approval.
    if not olds:
        _publish_phase()
    return r["ts"]


def _publish_phase(status: str = "success") -> None:
    """One Hub Activity row under the DD card's id. The post pass and the send
    pass each add one; the card's daily_runs:2 counts them (1 = awaiting the
    checkmark, 2 = sent). Best-effort — a publish failure must never break the
    post/send it is reporting on."""
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done("dd_bulletin", "DD / Organization Bulletin",
                                 status)
    except Exception as e:  # noqa: BLE001
        print(f"  (hub publish failed: {type(e).__name__} — the card pill "
              f"will lag reality)", flush=True)


def already_sent(today: Optional[dt.date] = None,
                 channel: Optional[str] = None) -> bool:
    """Has this week's bulletin already gone out?

    Read from the SLACK THREAD, not a local state file: the checker runs
    repeatedly and must not mail the org twice, and a state file that a cleared
    output/ or a second machine cannot see is not a lock. (The captainship gate
    learned this on 2026-07-30, when 12 reports went out twice.)"""
    msg = _find_post(today, channel)
    if msg is None:
        return False
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    return _said(replies, SENT_MARK)


def find_approval(today: Optional[dt.date] = None,
                  channel: Optional[str] = None,
                  verbose: bool = True) -> Optional[Tuple[str, str]]:
    msg = _find_post(today, channel)
    if msg is None:
        if verbose:
            print(f"— no review post found for {_title(today)}", flush=True)
        return None
    who = _approver_of(msg)
    if who:
        return who
    if verbose:
        got = [f":{r['name']}: x{r['count']}" for r in msg.get("reactions", [])]
        # Name the reactions we DID see. A tick from someone who is not an
        # approver is the likeliest way for this to sit unsent, and "not
        # approved yet" alone would send somebody hunting for a post that
        # visibly has a checkmark on it.
        print(f"— not approved yet (reactions: {', '.join(got) or 'none'}; "
              f"only {', '.join(APPROVERS.values())} can release this one)",
              flush=True)
    return None


def confirm_sent(who: str, to_note: str = "", headline=None,
                 today: Optional[dt.date] = None,
                 channel: Optional[str] = None) -> None:
    """Reply in-thread that it went out. Doubles as the once-a-week lock, so it
    must keep containing SENT_MARK.

    Names the WEEK and the HEADLINE actually sent: `send.py --dd` rebuilds from
    the live Sheet, so this is the only place a difference between what was
    approved and what was mailed becomes visible."""
    msg = _find_post(today, channel)
    if msg is None:
        return
    figure = f" · {DB._fmt(headline)}" if headline is not None else ""
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f":white_check_mark: {SENT_MARK} {who} · WE {week_label(today)}"
              f"{figure}{(' · ' + to_note) if to_note else ''}"))


def report_failure(rc: int, today: Optional[dt.date] = None,
                   channel: Optional[str] = None) -> None:
    """Say in the thread that an APPROVED bulletin did not go out. Once.

    Without this, a failing send retries in a log nobody reads while the channel
    still shows a green checkmark and everyone assumes it went."""
    msg = _find_post(today, channel)
    if msg is None:
        return
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    if _said(replies, FAILED_MARK):
        return
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f"{_mentions()} — {FAILED_MARK}: this is approved, but the send "
              f"failed (exit {rc}). Most often that is a figure the data layer "
              f"refuses to publish — see the `dd-bulletin` log on the mini."))


def remind(after_hours: float = REMIND_AFTER_HOURS,
           today: Optional[dt.date] = None, channel: Optional[str] = None,
           verbose: bool = True) -> bool:
    """Nudge if the week's bulletin is still waiting. Once — a reminder that
    repeats becomes noise, and noise is how the real one gets ignored."""
    msg = _find_post(today, channel)
    if msg is None:
        if verbose:
            print(f"— nothing posted for {_title(today)}, nothing to chase",
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
        text=(f"{_mentions()} — {REMIND_MARK} for WE {week_label(today)} is "
              f"still unapproved ({age_h:.0f}h). Nothing has been sent; it "
              f"needs a :white_check_mark:."))
    if verbose:
        print(f"✓ reminder posted ({age_h:.1f}h unapproved)", flush=True)
    return True


def close_day(today: Optional[dt.date] = None, channel: Optional[str] = None,
              verbose: bool = True) -> bool:
    """Say in the thread that the day ended without an approval. True if posted.

    A week that ends unapproved used to end in silence — no approval, no send,
    no message — which reads exactly like a week that went fine. The only trace
    was a post with no checkmark, scrolling away under everything else."""
    msg = _find_post(today, channel)
    if msg is None:
        if verbose:
            print(f"— nothing posted for {_title(today)}, nothing to close",
                  flush=True)
        return False
    if _approver_of(msg):
        if verbose:
            print("— approved; the send path owns this week", flush=True)
        return False
    replies = _client().conversations_replies(
        channel=_channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    if _said(replies, CLOSED_MARK):
        if verbose:
            print("— already closed once", flush=True)
        return False
    _client().chat_postMessage(
        channel=_channel(channel), thread_ts=msg["ts"],
        text=(f"{_mentions()} — {CLOSED_MARK}: the Organization Bulletin for "
              f"WE {week_label(today)} did not go out. Approve here and it "
              f"still will."))
    if verbose:
        print("✓ closed unapproved — said so in the thread", flush=True)
    return True


# --------------------------------------------------------------------------
# 4. the send
# --------------------------------------------------------------------------
def send_reviewed(distro: bool = False, force: bool = False,
                  verbose: bool = True) -> int:
    """Shell out to send.py. A separate process on purpose: the sender stays the
    one command that has ever mailed this, and this module never grows its own
    path to a recipient list.

    `--distro` reproduces the 2026-07-31 full-org go-live EXACTLY —
    `--dd --send --notify`: both contact groups ("Alphalete Org Owners" +
    "Bulletins"), the 3 Slack channels, and an alert to #claudecorrections on a
    data gap instead of a refusal. Without it, the 4-person soft-launch group.
    The gate changes WHO decides the bulletin goes out, never WHERE it goes —
    dropping --notify here would have silently narrowed the distro.

    `force` is for a CORRECTED RE-SEND of a week that already went out: the
    sender records the week it published and refuses a second send, which is
    right for a retrying agent and wrong for "the figures moved, send it again".
    It does NOT reach `hard_block` — a wrong week still never mails."""
    cmd = [sys.executable, "-u", "-m", "automations.override_bulletin.send",
           "--dd", "--send"] + (["--notify"] if distro else ["--test"]) \
        + (["--force"] if force else [])
    if verbose:
        print(f"→ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd)


def send_companion(distro: bool = False, verbose: bool = True) -> None:
    """Fire the 'Up and Coming RCs and NCs' email right after the DD send that
    actually went out — HERE, not in the Thursday wrapper, so the companion
    rides on EVERY path a send can take (a wrapper pass, `lucy rerun
    dd_bulletin_gate` after the pass window). The wrapper's old lock-step block
    only saw its own passes; a send released by rerun left the companion unsent
    (2026-08-20). Mode mirrors the DD send: --distro → both contact groups,
    otherwise the 4-person test group — same rule as send_reviewed.

    Best-effort ON PURPOSE: the bulletin is already out when this runs, so a
    companion failure must never flip the gate's exit code into "the send
    failed". It publishes its own Hub pill ('rcs_ncs') instead — success only
    when the sender actually printed an 'emailed' line; exit 0 with no email is
    a correct hold (hard-block or already sent this week) and leaves the pill
    quiet. send.py alerts #claudecorrections itself on a hard-block."""
    cmd = [sys.executable, "-u", "-m", "automations.override_bulletin.send",
           "--rcs-ncs", "--send"] + (["--notify"] if distro else ["--test"])
    if verbose:
        print(f"→ {' '.join(cmd)}", flush=True)
    status = None
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        print((proc.stdout or "") + (proc.stderr or ""), end="", flush=True)
        if proc.returncode != 0:
            status = "failed"
        elif any(line.startswith("emailed ")
                 for line in (proc.stdout or "").splitlines()):
            status = "success"
    except Exception as e:  # noqa: BLE001 — never fail the gate for the rider
        print(f"  (companion send crashed: {type(e).__name__}: {e})", flush=True)
        status = "failed"
    if status:
        try:
            from automations.day_orchestrator import hub_publish
            hub_publish.publish_done("rcs_ncs", "Up and Coming RCs and NCs",
                                     status)
        except Exception as e:  # noqa: BLE001
            print(f"  (hub publish failed: {type(e).__name__} — the rcs_ncs "
                  f"pill will lag, the email did what it did)", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--post", action="store_true",
                    help="build the pages + PDF, upload it, post the link. "
                         "RUN ON THE MINI so it comes from Lucy.")
    ap.add_argument("--refresh", action="store_true",
                    help="rebuild and overwrite the PDF already in Drive, "
                         "WITHOUT posting again. For when the Sheet is "
                         "corrected after the link went out. Wins over --post.")
    ap.add_argument("--repost", action="store_true",
                    help="with --post: replace this week's message instead of "
                         "leaving it alone. Refuses over an approval.")
    ap.add_argument("--check", action="store_true",
                    help="look for Evelyn's checkmark; with --send, mail it.")
    ap.add_argument("--send", action="store_true",
                    help="with --check: actually send.")
    ap.add_argument("--distro", action="store_true",
                    help="with --check --send: mail the real distro instead of "
                         "the 4-person soft-launch group.")
    ap.add_argument("--force", action="store_true",
                    help="with --check --send: send even though this week "
                         "already went out — a CORRECTED re-send. Never "
                         "overrides a hard block.")
    ap.add_argument("--remind", action="store_true",
                    help="nudge if still unapproved after --after-hours. Once.")
    ap.add_argument("--close-day", action="store_true",
                    help="say in the thread that the day ended unapproved.")
    ap.add_argument("--after-hours", type=float, default=REMIND_AFTER_HOURS,
                    help=f"hours before --remind fires (default "
                         f"{REMIND_AFTER_HOURS}).")
    ap.add_argument("--pdf-only", action="store_true",
                    help="build the pages + PDF and stop (no Drive, no Slack).")
    ap.add_argument("--channel", default=None,
                    help="override the channel id (for a one-off test).")
    ap.add_argument("--date", default=None,
                    help="run date (default today). The week is the Sunday "
                         "that just ended, Central.")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.date) if args.date else None

    if args.pdf_only:
        paths, _ = build_preview()
        build_pdf(paths)
        return 0
    # --refresh is checked BEFORE --post on purpose: the scheduler entry's base
    # args are ["--post"], so `lucy rerun dd_bulletin --refresh` arrives here as
    # "--post --refresh" and has to mean refresh. Same order, same reason as the
    # other two gates.
    if args.refresh:
        paths, _ = build_preview()
        link = upload_pdf(build_pdf(paths))
        print(f"✓ refreshed in place, existing link still valid: {link}",
              flush=True)
        return 0
    # --check is checked BEFORE --post for the same reason --refresh is: the
    # `dd_bulletin_gate` scheduler entry carries ["--post"] as its base args, so
    # `lucy rerun dd_bulletin_gate --check --send --distro` arrives here as
    # "--post --check --send --distro" and has to mean CHECK. Handled the other
    # way round it would silently re-post (idempotently, so: do nothing) and
    # never look for the checkmark — an approved bulletin that sits unsent while
    # the command that was supposed to send it exits 0. The Thursday agent is
    # unaffected: dd_bulletin_thu.sh runs --post and --check as separate passes.
    if args.post and not args.check:
        # ALREADY POSTED -> stop here, and in particular do NOT touch Drive.
        # post_review is idempotent, but it only learns the week is already up
        # AFTER upload_pdf has rebuilt and re-uploaded the PDF, so every pass
        # after the one real post was re-uploading a bulletin that had already
        # gone out. On Thu 2026-08-27 the 19:00 pass died mid-upload with a
        # BrokenPipeError (upload_pdf, line ~217) on a week that was posted,
        # approved by Evelyn and MAILED hours earlier: a pointless re-upload
        # exited 1, painted the Hub card red and opened a failure incident for a
        # report that had done its job. One Slack read up front removes the
        # whole surface -- 15 of the 16 Thursday passes now touch nothing.
        # --repost still rebuilds, on purpose: that flag exists to replace the
        # message, so it has to produce a fresh PDF to point at.
        if not args.repost and _all_posts(today, args.channel):
            print(f"- {_title(today)} is already posted; nothing to do "
                  f"(--refresh to update the PDF, --repost to replace the "
                  f"message)", flush=True)
            return 0
        # HOLD instead of posting when Eve has not opened the week's column yet.
        # The week the bulletin carries is POSITIONAL — the leftmost week header
        # on the tab — and nothing here rolls it, so an unfilled tab leaves LAST
        # week's column in front. Posting that would put a link to a bulletin
        # for the wrong week in front of the approver, and a checkmark on it
        # would republish a week that already went out (7.19.26 went out twice
        # that way). Six of the seven Thursday passes normally hold; the pass
        # after her fill picks it up. Exits 0 — a correct hold, not a failure.
        paths, d = build_preview()
        have = (d["weeks"] or [""])[0]
        if have != week_label(today):
            print(f"— HOLDING: the tab's newest week is {have or '(none)'} but "
                  f"the week that just ended is {week_label(today)}. Nothing "
                  f"posted — Eve has not filled the column yet.", flush=True)
            return 0
        # hard_block FIRST: those are the ones that refuse even with --notify,
        # so they are what actually decides whether a checkmark can release this.
        post_review(upload_pdf(build_pdf(paths)),
                    blocking=(d.get("hard_block") or []) + (d.get("blocking") or []),
                    today=today, channel=args.channel, repost=args.repost)
        return 0
    if args.remind:
        return 0 if remind(args.after_hours, today, args.channel) else 1
    if args.close_day:
        close_day(today, args.channel)
        return 0
    if args.check:
        if already_sent(today, args.channel):
            print("— already sent this week, nothing to do", flush=True)
            return 0
        who = find_approval(today, args.channel)
        if not who:
            return 1
        print(f"✓ approved by {who[1]}", flush=True)
        if not args.send:
            return 0
        rc = send_reviewed(args.distro, force=args.force)
        if rc == 0:
            # PHASE 2 of the pill: the approved send actually went out this
            # invocation (already_sent returned above, so this is not a re-run
            # of a sent week). Greens the card from any path, wrapper or rerun.
            _publish_phase()
            # Read the headline back so the confirmation names what was mailed,
            # not what was approved — see the module docstring.
            try:
                headline = D.load(credico=False)["headline"]
            except Exception:  # noqa: BLE001 — never fail a successful send
                headline = None
            confirm_sent(who[1], headline=headline,
                         to_note=("full distro" if args.distro
                                  else "soft-launch group (4 people)"),
                         today=today, channel=args.channel)
            # The 'Up and Coming RCs and NCs' companion rides on the send that
            # went out, whatever released it and whenever Evelyn ticked it.
            send_companion(args.distro)
        else:
            report_failure(rc, today, args.channel)
        return rc
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
