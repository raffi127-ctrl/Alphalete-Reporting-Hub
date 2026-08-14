"""The approval gate between building the Override Bulletin and posting it.

Same shape as the DD / Organization Bulletin gate (`review_gate.py`) so there is
ONE review habit, not two:

    override_gate.py --post           build the page -> PDF -> Drive -> Lucy posts
                                      the link in #revision-emails
    override_gate.py --refresh        the Sheet was corrected after the link went
                                      out: rebuild and overwrite the PDF in Drive,
                                      SAME link, NO second post
    override_gate.py --check --send   Eve's checkmark mails + Slacks it

WHO APPROVES: **EVE (Evelyn) ONLY** — the same sole approver as the DD bulletin
(Eve, 2026-08-07: "it should mirror the DD one for eve's approval"). A checkmark
from anyone else leaves the gate closed and sends nothing; Slack reports who
reacted, so that is enforceable rather than a convention. The approver list, the
review channel and the Drive token are all REUSED from `review_gate` so the two
bulletins never drift apart on who-can-approve or where the post lands.

WEEKLY, NOT DAILY, and the week is POSITIONAL — the leftmost week header on the
override tab, exactly as `send.py` reads it. Both --post and --check derive it
the same way (one read of the same tab, which does not change during the Friday
gate window), so they agree on which message is this week's without either run
telling the other anything. No calendar math, so there is no way for a
calendar-vs-tab format drift to make --check miss --post's message.

WHAT GOES OUT is `send.py` (the regular Override Bulletin, NOT --dd): full-org is
`--send` (every Slack channel + both contact groups); the soft-launch fallback is
`--test --send` (the 4-person group, no Slack). The gate changes WHO decides it
goes out — Eve's checkmark instead of the clock — never WHERE it goes.

NOTHING SENDS ON ITS OWN. `send.py` refuses a week that is not filled and records
the week it sent so the q25m retry passes never double-mail; this gate only
releases the send once Eve has reacted. Gaps (a captain/program row not yet
sourced) do NOT block — the sender mails with whatever is in, matching the VA,
and flags the gap to #claudecorrections — so they are shown in the review post as
a heads-up, not as a blocker.
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from automations.override_bulletin import build as B
from automations.override_bulletin import fill as F
# Reuse the DD gate's generic leaf helpers so the two bulletins share ONE set of
# approvers, ONE review channel and ONE Drive token — a change to who-can-approve
# happens in one place, never in two that quietly diverge.
from automations.override_bulletin import review_gate as RG

# The first line of the post, and how --check finds it. PREFIX-matched, and the
# gates share #revision-emails, so this must not be a prefix of — nor start with —
# any other gate's title. "Override Bulletin" collides with none of them
# ("Organization Bulletin", "Captainship Reports", "Org Sales Board Email",
# "Country Sales Board Email"). Check that again before renaming it.
TITLE = "Override Bulletin"
REMIND_MARK = "reminder: the Override Bulletin"
SENT_MARK = "Sent — approved by"
FAILED_MARK = "Could not send"
CLOSED_MARK = "Not sent — nobody approved"

DRIVE_FOLDER_NAME = "Override Bulletin - para revisar"


# --------------------------------------------------------------------------
# week label — POSITIONAL, from the tab, same as send.py
# --------------------------------------------------------------------------
def _read(tab: str = None):
    """One read of the override tab → (week_labels, combined, regular,
    captainship, program). Central to the gate: --post and --check both call it
    and both take week_labels[0] as THE week, so they agree without state."""
    return B.read_data(tab or F.SANDBOX_TAB)


def week_label(data=None, tab: str = None) -> str:
    """The week the bulletin covers, as the tab spells it (e.g. '8.2.26') — the
    leftmost week header. Pass `data` (a prior _read result) to avoid a second
    Sheet read."""
    wl = (data[0] if data is not None else _read(tab)[0])
    return (wl[0] if wl else "").strip()


def _title(wk: str) -> str:
    return f"{TITLE} — WE {wk}"


# --------------------------------------------------------------------------
# 1. the page + the PDF
# --------------------------------------------------------------------------
def build_preview(tab: str = None, verbose: bool = True):
    """Build the bulletin page from OUR fill (the sandbox copy tab by default).

    Returns (html_path, week, gaps): `week` is the leftmost tab header, `gaps`
    are the captain/program rows whose weekly figure has not been sourced yet —
    shown in the review post as a heads-up, never as a blocker (see the module
    docstring).

    A BLANK IS NOT AUTOMATICALLY A GAP. Carlos' and Colten's Special Override is
    a retail-PERIOD item — it posts at period end and shows on the first week of
    the next period, so it is legitimately blank ~3 weeks out of 4. Listing it
    put the same two names in front of Eve nearly every Friday under the heading
    "not sourced yet", which is exactly the warning-that-cries-wolf that trains
    people to skim past the real one (Eve 2026-08-14). `send.py` already made
    this distinction for its #claudecorrections alert; the review post now uses
    the SAME two rules, imported rather than re-implemented so the two can never
    disagree about what counts as a gap:

      * routine  — the row's own recent history says it is blank most weeks
                   (`send._blank_is_routine`); no name list, so a new
                   period-based row needs no code change and a weekly row that
                   goes quiet still shouts.
      * override — a RED P#-YYYY marker sitting on THIS week is the sheet saying
                   "money is expected here and has not landed"
                   (`send._week_has_pending_marker`); then every blank counts.
    """
    tab = tab or F.SANDBOX_TAB
    week_labels, combined, regular, captainship, program = _read(tab)
    B.OUT_DIR.mkdir(parents=True, exist_ok=True)
    html_path = B.OUT_DIR / "override-bulletin.html"
    html_path.write_text(
        B.build_html(week_labels, combined, regular, captainship, program),
        encoding="utf-8")
    wk = (week_labels[0] if week_labels else "").strip()
    blank_rows = [r for r in (captainship + program) if r.get("week") is None]
    gaps, routine = [], []
    if blank_rows:
        from automations.override_bulletin import send as S
        from automations.recruiting_report import fill as _fill
        ws = _fill._client().open_by_key(F.WORKBOOK_ID).worksheet(tab)
        marker_pending = S._week_has_pending_marker(ws, wk)
        for r in blank_rows:
            (gaps if (marker_pending or not S._blank_is_routine(r))
             else routine).append(r["name"])
    if verbose:
        print(f"✓ page built — week {wk!r}, {len(combined)} org rows"
              f"{f', {len(gaps)} gap(s)' if gaps else ''}", flush=True)
        if routine:
            print(f"  routine blank(s), NOT shown in the post (period-based, "
                  f"blank most weeks): {', '.join(routine)}", flush=True)
    return html_path, wk, gaps


def build_pdf(html_path: Path, wk: str, verbose: bool = True) -> Path:
    """Render the one bulletin page into a single tall PDF (Drive shows a PDF
    inline; an .html downloads). ONE tall page, not Letter, so the single column
    of rows never splits across a page break and the totals line stays with the
    table. Printed from the HTML so the text stays selectable."""
    from patchright.sync_api import sync_playwright

    safe = wk or "unknown"
    out = B.OUT_DIR / f"Override-Bulletin-WE-{safe}.pdf"
    if not html_path.exists():
        raise RuntimeError(f"no page at {html_path} — build it first (--post does)")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1180, "height": 1200})
        try:
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            page.wait_for_timeout(600)
            tall = page.evaluate("document.body.scrollHeight")
            page.pdf(path=str(out), print_background=True,
                     width="1180px", height=f"{tall + 40}px",
                     margin={"top": "0", "bottom": "0",
                             "left": "0", "right": "0"})
        finally:
            browser.close()
    if verbose:
        print(f"✓ PDF: {out} ({out.stat().st_size // 1024} KB)", flush=True)
    return out


# --------------------------------------------------------------------------
# 2. Slack — title-specific; the leaf helpers come from review_gate
# --------------------------------------------------------------------------
def _all_posts(wk: str, channel: Optional[str] = None) -> list:
    """Every review post for this week, newest first. PREFIX match on the title,
    never 'anywhere in the text' — the gates share this channel and a plain `in`
    would let another report's checkmark release this one."""
    want = _title(wk)
    hist = RG._client().conversations_history(
        channel=RG._channel(channel), limit=100)
    return [m for m in hist.get("messages", [])
            if (m.get("text") or "").lstrip("*").startswith(want)]


def _find_post(wk: str, channel: Optional[str] = None) -> Optional[dict]:
    posts = _all_posts(wk, channel)
    return posts[0] if posts else None


def post_review(link: str, wk: str, gaps=None, channel: Optional[str] = None,
                repost: bool = False, verbose: bool = True) -> str:
    """Post this week's link with Eve's mention. Returns the message ts.

    RUN THIS ON THE MINI — the Slack user token there is Lucy's, and that is the
    only reason the message arrives from Lucy. On Eve's box it is Evelyn's, and
    the post would read as the approver approving her own report.

    Idempotent by default (like the DD gate): the Friday agent makes several
    passes and each calls --post; a gate that re-posted every pass would ping Eve
    repeatedly and hand her several links to choose between. One post per week; a
    correction goes out with --refresh (same link, no second message). Never
    re-posts over an existing approval — that would delete a human's decision."""
    gaps = list(gaps or [])
    heads = ""
    if gaps:
        bullets = "\n".join(f"• {g}" for g in gaps[:6])
        more = (f"\n• …and {len(gaps) - 6} more" if len(gaps) > 6 else "")
        # A HEADS-UP, not a blocker: the sender mails with whatever is in (it
        # matches the VA and flags the gap to #claudecorrections). Eve's
        # checkmark still releases it — she just knows these numbers may fill in.
        heads = (f"\n\n:information_source: *{len(gaps)} captain/program "
                 f"number(s) not sourced yet* — it will still send (matching the "
                 f"VA); they fill in over the following days:\n{bullets}{more}")
    text = (f"*{_title(wk)}*\n"
            f"{link}\n\n"
            f"{RG._mentions()} — please review and react with "
            f":white_check_mark: to send it. Nothing goes out until then."
            f"{heads}")

    cli = RG._client()
    olds = _all_posts(wk, channel)
    if olds and not repost:
        who = RG._approver_of(olds[0])
        if verbose:
            print(f"— {_title(wk)} is already posted"
                  f"{f' and approved by {who[1]}' if who else ''}; leaving it "
                  f"alone (use --refresh to update the PDF, --repost to replace "
                  f"the message)", flush=True)
        return olds[0]["ts"]
    for old in olds:
        if RG._approver_of(old):
            if verbose:
                print("— refusing to --repost over an approval", flush=True)
            return old["ts"]
        try:
            cli.chat_delete(channel=RG._channel(channel), ts=old["ts"])
            if verbose:
                print(f"  (replaced the earlier post for {_title(wk)})",
                      flush=True)
        except Exception as e:  # noqa: BLE001 — a stale post must not block this
            print(f"  (could not remove the earlier post: {type(e).__name__})",
                  flush=True)
    r = cli.chat_postMessage(channel=RG._channel(channel), text=text,
                             unfurl_links=False)
    if verbose:
        print(f"✓ posted to {RG._channel(channel)} ts={r['ts']}", flush=True)
    return r["ts"]


def already_sent(wk: str, channel: Optional[str] = None) -> bool:
    """Has this week's bulletin already gone out? Read from the SLACK THREAD, not
    a local state file: the checker runs repeatedly and must not mail twice, and a
    state file a cleared output/ or a second machine cannot see is not a lock."""
    msg = _find_post(wk, channel)
    if msg is None:
        return False
    replies = RG._client().conversations_replies(
        channel=RG._channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    return RG._said(replies, SENT_MARK)


def find_approval(wk: str, channel: Optional[str] = None,
                  verbose: bool = True) -> Optional[Tuple[str, str]]:
    msg = _find_post(wk, channel)
    if msg is None:
        if verbose:
            print(f"— no review post found for {_title(wk)}", flush=True)
        return None
    who = RG._approver_of(msg)
    if who:
        return who
    if verbose:
        got = [f":{r['name']}: x{r['count']}" for r in msg.get("reactions", [])]
        print(f"— not approved yet (reactions: {', '.join(got) or 'none'}; "
              f"only {', '.join(RG.APPROVERS.values())} can release this one)",
              flush=True)
    return None


def confirm_sent(who: str, wk: str, to_note: str = "",
                 channel: Optional[str] = None) -> None:
    """Reply in-thread that it went out. Doubles as the once-a-week lock, so it
    must keep containing SENT_MARK. Names the WEEK actually sent — send.py
    rebuilds from the Sheet at send time, so this is where a difference between
    what was approved and what was mailed becomes visible."""
    msg = _find_post(wk, channel)
    if msg is None:
        return
    RG._client().chat_postMessage(
        channel=RG._channel(channel), thread_ts=msg["ts"],
        text=(f":white_check_mark: {SENT_MARK} {who} · WE {wk}"
              f"{(' · ' + to_note) if to_note else ''}"))


def report_failure(rc: int, wk: str, channel: Optional[str] = None) -> None:
    """Say in the thread that an APPROVED bulletin did not go out. Once. Without
    this, a failing send retries in a log nobody reads while the channel still
    shows a green checkmark and everyone assumes it went."""
    msg = _find_post(wk, channel)
    if msg is None:
        return
    replies = RG._client().conversations_replies(
        channel=RG._channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    if RG._said(replies, FAILED_MARK):
        return
    RG._client().chat_postMessage(
        channel=RG._channel(channel), thread_ts=msg["ts"],
        text=(f"{RG._mentions()} — {FAILED_MARK}: this is approved, but the send "
              f"failed (exit {rc}). Most often that is a week the sender refuses "
              f"to publish — see the `override-bulletin` log on the mini."))


def remind(wk: str, after_hours: float = RG.REMIND_AFTER_HOURS,
           channel: Optional[str] = None, verbose: bool = True) -> bool:
    """Nudge if the week's bulletin is still waiting. Once — a reminder that
    repeats becomes noise, and noise is how the real one gets ignored."""
    msg = _find_post(wk, channel)
    if msg is None:
        if verbose:
            print(f"— nothing posted for {_title(wk)}, nothing to chase",
                  flush=True)
        return False
    if RG._approver_of(msg):
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
    replies = RG._client().conversations_replies(
        channel=RG._channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    if RG._said(replies, REMIND_MARK):
        if verbose:
            print("— already reminded once", flush=True)
        return False
    RG._client().chat_postMessage(
        channel=RG._channel(channel), thread_ts=msg["ts"],
        text=(f"{RG._mentions()} — {REMIND_MARK} for WE {wk} is still unapproved "
              f"({age_h:.0f}h). Nothing has been sent; it needs a "
              f":white_check_mark:."))
    if verbose:
        print(f"✓ reminder posted ({age_h:.1f}h unapproved)", flush=True)
    return True


def close_day(wk: str, channel: Optional[str] = None,
              verbose: bool = True) -> bool:
    """Say in the thread that the day ended without an approval. True if posted.
    A week that ends unapproved otherwise ends in silence — which reads exactly
    like a week that went fine."""
    msg = _find_post(wk, channel)
    if msg is None:
        if verbose:
            print(f"— nothing posted for {_title(wk)}, nothing to close",
                  flush=True)
        return False
    if RG._approver_of(msg):
        if verbose:
            print("— approved; the send path owns this week", flush=True)
        return False
    replies = RG._client().conversations_replies(
        channel=RG._channel(channel), ts=msg["ts"], limit=50).get("messages", [])
    if RG._said(replies, CLOSED_MARK):
        if verbose:
            print("— already closed once", flush=True)
        return False
    RG._client().chat_postMessage(
        channel=RG._channel(channel), thread_ts=msg["ts"],
        text=(f"{RG._mentions()} — {CLOSED_MARK}: the Override Bulletin for WE "
              f"{wk} did not go out. Approve here and it still will."))
    if verbose:
        print("✓ closed unapproved — said so in the thread", flush=True)
    return True


# --------------------------------------------------------------------------
# 3. Drive + the send
# --------------------------------------------------------------------------
def upload_pdf(pdf: Path, verbose: bool = True) -> str:
    """Put the PDF in the Override review folder and return a link. Reuses the DD
    gate's uploader (same alphaletereporting drive.file token, same prune,
    same no-code-sharing reasoning) — only the folder differs."""
    return RG.upload_pdf(pdf, verbose=verbose, folder_name=DRIVE_FOLDER_NAME)


def send_reviewed(distro: bool = False, force: bool = False,
                  verbose: bool = True) -> int:
    """Shell out to send.py — a separate process on purpose, so the sender stays
    the one command that has ever mailed this and this module never grows its own
    path to a recipient list.

    Full-org (`distro=True`) is `--send`: every Slack channel + both contact
    groups. Without it, `--test --send`: the 4-person soft-launch group, no Slack.
    `force` is a CORRECTED re-send of a week already sent — the sender records the
    week it published and refuses a second send otherwise. It never makes the
    sender publish an UNFILLED week."""
    cmd = [sys.executable, "-u", "-m", "automations.override_bulletin.send"]
    cmd += ["--send"] if distro else ["--test", "--send"]
    if force:
        cmd += ["--force"]
    if verbose:
        print(f"→ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--post", action="store_true",
                    help="build the page + PDF, upload it, post the link. "
                         "RUN ON THE MINI so it comes from Lucy.")
    ap.add_argument("--refresh", action="store_true",
                    help="rebuild and overwrite the PDF already in Drive, WITHOUT "
                         "posting again. For when the Sheet is corrected after the "
                         "link went out. Wins over --post.")
    ap.add_argument("--repost", action="store_true",
                    help="with --post: replace this week's message instead of "
                         "leaving it alone. Refuses over an approval.")
    ap.add_argument("--check", action="store_true",
                    help="look for Eve's checkmark; with --send, mail it.")
    ap.add_argument("--send", action="store_true",
                    help="with --check: actually send.")
    ap.add_argument("--distro", action="store_true",
                    help="with --check --send: mail the real distro (Slack + both "
                         "contact groups) instead of the 4-person soft-launch "
                         "group.")
    ap.add_argument("--force", action="store_true",
                    help="with --check --send: send even though this week already "
                         "went out — a CORRECTED re-send.")
    ap.add_argument("--remind", action="store_true",
                    help="nudge if still unapproved after --after-hours. Once.")
    ap.add_argument("--close-day", action="store_true",
                    help="say in the thread that the day ended unapproved.")
    ap.add_argument("--after-hours", type=float, default=RG.REMIND_AFTER_HOURS,
                    help=f"hours before --remind fires (default "
                         f"{RG.REMIND_AFTER_HOURS}).")
    ap.add_argument("--pdf-only", action="store_true",
                    help="build the page + PDF and stop (no Drive, no Slack).")
    ap.add_argument("--tab", default=F.SANDBOX_TAB,
                    help="tab to build from (default the sandbox copy tab — OUR "
                         "fill from the real sources).")
    ap.add_argument("--channel", default=None,
                    help="override the channel id (for a one-off test).")
    args = ap.parse_args(argv)

    if args.pdf_only:
        html_path, wk, _ = build_preview(args.tab)
        build_pdf(html_path, wk)
        return 0
    # --refresh / --check are checked BEFORE --post because the scheduler entry's
    # base args are ["--post"]: `lucy rerun override_bulletin_gate --check --send
    # --distro` arrives here as "--post --check --send --distro" and has to mean
    # CHECK, and `... --refresh` has to mean refresh. Same order, same reason as
    # the DD gate. The Friday wrapper runs --post and --check as separate passes,
    # so it is unaffected either way.
    if args.refresh:
        html_path, wk, _ = build_preview(args.tab)
        link = upload_pdf(build_pdf(html_path, wk))
        print(f"✓ refreshed in place, existing link still valid: {link}",
              flush=True)
        return 0
    if args.check:
        html_path_wk = week_label(tab=args.tab)   # one read; the leftmost week
        if already_sent(html_path_wk, args.channel):
            print("— already sent this week, nothing to do", flush=True)
            return 0
        who = find_approval(html_path_wk, args.channel)
        if not who:
            return 1
        print(f"✓ approved by {who[1]}", flush=True)
        if not args.send:
            return 0
        rc = send_reviewed(args.distro, force=args.force)
        if rc == 0:
            confirm_sent(who[1], html_path_wk,
                         to_note=("full distro" if args.distro
                                  else "soft-launch group (4 people)"),
                         channel=args.channel)
            print("✓ SENT", flush=True)
        else:
            report_failure(rc, html_path_wk, args.channel)
        return rc
    if args.post:
        # HOLD instead of posting when the week is not filled yet. The week is
        # POSITIONAL — the leftmost header — and nothing here rolls it, so an
        # unfilled tab would put a link to a blank/last-week bulletin in front of
        # the approver, and a checkmark on it would publish the wrong week. The
        # fill agent (override_bulletin_fri.sh) rolls + fills earlier in the
        # morning; the pass after it picks this up. Exits 0 — a correct hold.
        html_path, wk, gaps = build_preview(args.tab)
        from automations.recruiting_report import fill as _fill
        ws = _fill._client().open_by_key(F.WORKBOOK_ID).worksheet(args.tab)
        if not wk or not F.week_is_filled(ws, wk):
            print(f"— HOLDING: {wk or '(no week)'} is not filled on {args.tab!r} "
                  f"yet — nothing posted. The fill agent has not populated the "
                  f"column.", flush=True)
            return 0
        post_review(upload_pdf(build_pdf(html_path, wk)), wk, gaps=gaps,
                    channel=args.channel, repost=args.repost)
        return 0
    if args.remind:
        return 0 if remind(week_label(tab=args.tab), args.after_hours,
                           args.channel) else 1
    if args.close_day:
        close_day(week_label(tab=args.tab), args.channel)
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
