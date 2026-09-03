"""Program Sales Boards — daily Slack thread (VA-replacement Items 5-8).

RESTRUCTURED 2026-08-30 (Carlos): the standalone "Vantura Production" thread
is RETIRED. Each board's TWO images — (a) the weekly ranking and (b) the
Highrollers cut for yesterday, titled with YESTERDAY's date — now reply into
the thread where their audience already reads:

    :briefcase: B2B Sales Board  -> the day's B2B METRICS thread (this run
        creates it at 5:10 if the metrics runner hasn't yet — which is what
        makes the board the thread's FIRST screenshot), followed at 5:20 by
        the :moneybag: Revenue Board (vantura_revenue_board).
    :package: BOX Sales Board    -> the day's BOX ORDER LOG thread (7:00) —
        posted by vantura_revenue_board's 7:25 pass (--program BOX here),
        after the 7:15 order-log confirm has corrected the cells.

Both in #alphalete-gp-sales AND #a-players-b2b; Zero Streaks ride the
A-Players B2B Metrics thread.

Rendering lives in render.py — see its header for why we duplicate the tab and
hide rows per campaign instead of cropping ranges (campaigns are NOT contiguous).

Reads the PROD sheet as of go-live (2026-07-18); set SALES_BOARD_SHEET_ID to the
sandbox id to build against a copy. DRY-RUN by default — posting needs --post.

Usage:
  python -m automations.sales_boards.run                  # dry-run, all 4
  python -m automations.sales_boards.run --program JE     # one program
  python -m automations.sales_boards.run --post           # post to the channel
  python -m automations.sales_boards.run --post --dm U…   # post to a DM (test)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path

from automations.recruiting_report.fill import open_by_key, _retry
from automations.pnl_office.run import _token
from automations.sales_boards import render as R
from automations.sales_boards import zeros as Z

SANDBOX_SHEET_ID = "15QzcyFqTzX9RYNJ2SvT_HOiyQsMU1v90wHjSUHA_cNc"   # re-copied 7/18
PROD_SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
# PROD by default as of go-live (Megan 2026-07-18). Set SALES_BOARD_SHEET_ID to
# the sandbox id to build against a copy again.
SHEET_ID = os.environ.get("SALES_BOARD_SHEET_ID", PROD_SHEET_ID)
TAB = "Sales Board"
TEMP_TAB = "_sb_render_tmp"          # ephemeral copy we create + delete

# Boards that post to the thread. Sourced from render.PROGRAMS but with JE and
# Base dropped — JE: Megan 2026-07-22; Base: Carlos 2026-08-06 (no longer runs
# the base campaign, so ⚡ Base Sales Board should stop posting on both channels).
# (render.PROGRAMS stays full: it also drives rep-row detection in render.py.)
PROGRAMS = [p for p in R.PROGRAMS if p not in ("JE", "Base")]
# The VA's per-program emoji, kept so the thread reads the way the channel is
# used to: ":briefcase: *B2B Sales Board 7.17*".
PROGRAM_EMOJI = {"B2B": ":briefcase:", "Base": ":zap:",
                 "JE": ":bulb:", "BOX": ":package:"}
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "sales_boards"
CHANNEL = ("#alphalete-gp-sales", "C07J46MQNUX")

# Carlos 7/23: the same Vantura Production thread also lands in his A-Players
# channel, and THAT copy carries the extra Zero Streak screenshots (they're a
# callout for his A-Players room, not for the main sales channel).
#   (name, channel_id, include_zeros?)
TARGETS = [
    ("#alphalete-gp-sales", "C07J46MQNUX", False),
    ("#a-players-b2b", "C0AJQA8P716", True),
]

# The second daily thread in the same channel — the three ATTTRACKER-B2B Tableau
# views. Those captures aren't built yet; the header lives here so both threads
# stay consistent when they land.
QUALITY_THREAD_TITLE = "B2B Quality & Bonus"
QUALITY_THREAD_ITEMS = ["Tiered Bonus", "Activation Rate", "Churn Rate"]


WE_CELL = (2, 2)        # B2 — the gold week-ending selector


def expected_we(yday):
    """(sunday_date, "M.D") the board's WE selector MUST show: the SUNDAY of
    YESTERDAY's week.

    Matters most on Monday — yesterday is Sunday, so we need the week that just
    COMPLETED, not the new one. Verified against her Monday 7/6 post, whose gold
    cell reads 7.5 (the completed week)."""
    sunday = yday + dt.timedelta(days=(6 - yday.weekday()) % 7)
    return sunday, f"{sunday.month}.{sunday.day}"


def we_matches(shown: str, want: str) -> bool:
    """Is the gold cell showing `want`, allowing for a LOST TRAILING ZERO?

    Picking a week from B2's dropdown stores it as a NUMBER, and a number cannot
    keep a trailing zero: week `8.30` comes back from the API as `8.3`. That is
    exactly how 2026-08-24 went wrong — the board had been rolled correctly, but
    the gate read '8.3', held, and the whole thing looked like a board nobody
    touched. (It also made the board's own date header render Jul 28–Aug 3: the
    AS3 anchor parsed "8.3" as month 8, day 3. AS3 now reads the real Sunday off
    WeekData!J:K instead, and B2 is kept as TEXT so the day-cell keys stay
    `<REP>|8.30` — the spelling `zeros.we_label` builds.)

    Comparing numerically as well as textually is safe because a WE is always a
    SUNDAY: within one year `x.3` and `x.30` are 27 days apart, never a multiple
    of 7, so they can never both be Sundays. Same for x.1/x.10 and x.2/x.20.
    """
    if shown == want:
        return True
    try:
        return float(shown) == float(want)
    except ValueError:
        return False


def check_we(grid, yday):
    """(ok, shown, want). We deliberately do NOT rewrite B2 ourselves: only some
    day cells are formulas keyed on it (=INDEX(WeekData…MATCH(REP|$B$2))) — the
    rest are hand-typed, so flipping the selector would repopulate a few cells
    and leave stale typed numbers behind, producing a mixed-week board. If the
    selector is on the wrong week we HOLD and say so."""
    r, c = WE_CELL
    shown = (grid[r - 1][c - 1] if len(grid) >= r and len(grid[r - 1]) >= c else "").strip()
    _, want = expected_we(yday)
    return we_matches(shown, want), shown, want


def header_title(day) -> str:
    """Parent's first line — also the needle used to find today's thread."""
    return f"Vantura Production {day.month:02d}/{day.day:02d}/{day.year}"


def header_text(day, zeros=None, tag: str = "") -> str:
    """Parent message. `zeros` (the render_zeros result) adds the Zero Streak line
    — only the A-Players copy gets it, so the two channels' parents differ by that
    one line while sharing the same title needle."""
    lines = [f"*{header_title(day)}*"]
    lines += [f"{PROGRAM_EMOJI.get(p, '')} {p} Sales Board".strip() for p in PROGRAMS]
    if zeros:
        lines.append(f"{Z.EMOJI} Zero Streak {tag}  "
                     f"({', '.join(Z.level_label(n) for n in sorted(zeros))})")
    return "\n".join(lines)


def quality_header_text(day) -> str:
    title = f"{QUALITY_THREAD_TITLE} {day.month:02d}/{day.day:02d}/{day.year}"
    return "\n".join([f"*{title}*"] + [f"• {i}" for i in QUALITY_THREAD_ITEMS])


def find_thread_ts(client, channel: str, day):
    """ts of today's parent, so a re-run never starts a second thread.

    Degrades to None (= start a fresh thread) if the history read fails. Lucy's
    token has channels:history + groups:history — enough for the real channel —
    but NOT im:history, so this raises in a --dm test run. A test shouldn't be
    able to crash the post path."""
    oldest = dt.datetime.combine(dt.date.today(), dt.time.min).timestamp()
    try:
        resp = client.conversations_history(channel=channel, oldest=str(oldest), limit=200)
    except Exception as e:  # noqa: BLE001
        print(f"    (thread lookup unavailable — {type(e).__name__}; starting a new thread)")
        return None
    needle = header_title(day)
    for msg in resp.get("messages", []):
        if needle in (msg.get("text") or ""):
            return msg.get("thread_ts") or msg.get("ts")
    return None


def _already_replied(client, channel: str, thread_ts: str, plain: str) -> bool:
    """Is this board's reply already in the thread?

    TWO signals, because either alone can miss:
      * the caption text — but Slack does NOT guarantee `initial_comment`
        survives as the file-share message's `text` in every upload path, and a
        false negative here re-posts duplicate images on the next pass;
      * the attached FILENAME — which we control ("<plain> (a).png").
    Both derive from `plain` (no emoji), since Slack may store the shortcode or
    the rendered character and a verbatim caption match would be unreliable.
    Also unescapes &/</> — Slack stores message text HTML-escaped.
    """
    try:
        rs = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
    except Exception:  # noqa: BLE001 — a lookup failure must not block posting
        return False
    for m in rs.get("messages", []):
        text = (m.get("text") or "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        if plain in text:
            return True
        if any((f.get("name") or "").startswith(plain) for f in (m.get("files") or [])):
            return True
    return False


def _publish_hub(status: str) -> None:
    """Flip the Hub card's pill. Best-effort — never fails the run. Called only
    on a real post (this fires 8x/day; publishing every pass would bury the
    activity log)."""
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done("sales_boards",
                                 "Sales Boards → #alphalete-gp-sales", status)
    except Exception:  # noqa: BLE001 — Hub publish must never break the post
        pass


def _replies(imgs: dict, zeros: dict, tag: str, want_zeros: bool,
             corrected: bool = False) -> list:
    """The thread's replies in post order: the boards, then (A-Players only) one
    reply per Zero Streak level. Each entry is
    (plain_needle, caption, [(local_path, slack_filename), …])."""
    out = []
    for p in PROGRAMS:
        parts = imgs.get(p) or {}
        if not parts:
            continue
        plain = f"{p} Sales Board {tag}"
        if corrected:
            # A re-post AFTER the order log corrected the board (the 5:10
            # thread already carries the original reply, and _already_replied
            # keys on the plain text — this suffix is what lets the corrected
            # images through, exactly once).
            plain += " (corrected)"
        out.append((plain, f"{PROGRAM_EMOJI.get(p, '')} *{plain}*".strip(),
                    [(parts[k], f"{plain} ({k}).png") for k in ("a", "b") if k in parts]))
    if want_zeros:
        for n in sorted(zeros or {}):
            info = zeros[n]
            plain = Z.plain_caption(n, tag)
            caption = f"{Z.EMOJI} *{plain}*  —  {info['reps']} reps"
            out.append((plain, caption, [(info["path"], f"{plain}.png")]))
    return out


# ------------------------------------------------------------ thread routing
# RESTRUCTURE (Carlos 2026-08-30): the standalone "Vantura Production" thread
# is RETIRED. The B2B Sales Board images open (or join) the day's B2B METRICS
# thread — same parent b2b_metrics uses, coordinated through b2b_quality's
# thread_state.json so whoever posts first creates it and the metrics runner
# appends its sections after — and the BOX images go into the day's BOX ORDER
# LOG thread (box_order_log's 7:00 post; we reply by title). Both in the same
# two rooms as before: #alphalete-gp-sales + #a-players-b2b.

def metrics_thread_ts(client, chan: str, today) -> str:
    """ts of the day's 'B2B Metrics' thread in `chan`, creating the parent if
    nobody has yet (5:10 normally beats the metrics runner, which is exactly
    what puts the Sales Board FIRST in the thread — Carlos 2026-08-30)."""
    import automations.b2b_quality.run as bq
    state = bq._load_state(today, chan)
    ts = state.get("thread_ts")
    if ts:
        return ts
    from automations.b2b_metrics import offices as MO
    from automations.b2b_metrics import runner as MR
    o = MO.OFFICES["carlos"]
    header = MR.header_text(o, today)
    lines = header.split("\n")
    # The board + revenue ride ahead of the metrics sections in the thread, so
    # the parent's contents list says so too.
    lines[1:1] = [":briefcase: B2B Sales Board", ":moneybag: Revenue Board"]
    ts = client.chat_postMessage(channel=chan, text="\n".join(lines)).get("ts")
    bq._save_state(today, chan, ts, list(state.get("posted") or []))
    print(f"    opened B2B Metrics thread in {chan} ts={ts}")
    return ts


def box_thread_ts(client, chan: str, today):
    """ts of the day's 'BOX Order Log — <Month D, YYYY>' thread in `chan`, or
    None — box_order_log posts it at 7:00 (8:30 fallback); we never create it."""
    needle = "BOX Order Log — {}".format(today.strftime("%B %d, %Y"))
    alt = "BOX Order Log — {}".format(
        today.strftime("%B %d, %Y").replace(" 0", " "))
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    try:
        resp = client.conversations_history(channel=chan, oldest=str(oldest),
                                            limit=200)
    except Exception as e:  # noqa: BLE001
        print(f"    (box-thread lookup unavailable in {chan} — "
              f"{type(e).__name__})")
        return None
    import html as _html
    for m in resp.get("messages", []):
        text = _html.unescape(m.get("text") or "")
        if needle in text or alt in text:
            return m.get("thread_ts") or m.get("ts")
    return None


def post_thread(imgs: dict, zeros: dict, day, yday, dry_run: bool,
                dm_user: str = "", corrected: bool = False) -> list:
    """Route each program's images into ITS thread (Carlos 2026-08-30):
    B2B -> the day's B2B Metrics thread (created here if absent, so the board
    is the thread's first screenshot); BOX -> the day's BOX Order Log thread
    (never created here — box_order_log owns it; missing = hold). Zero Streaks
    ride the A-Players B2B Metrics thread, where their audience already is.
    dm_user still routes everything into one DM for a test."""
    tag = f"{yday.month}.{yday.day}"
    scratch = os.environ.get("SALES_BOARD_CHANNEL_ID")
    targets = ([(f"scratch ({scratch})", scratch, True)] if scratch
               else [t for t in TARGETS if t[1]])

    if dry_run:
        return [{"dry_run": True, "channel": name, "id": cid,
                 "header": "(joins B2B Metrics / BOX Order Log threads)",
                 "replies": [(cap, [f for _, f in ups])
                             for _, cap, ups in _replies(imgs, zeros, tag, wz,
                                                         corrected)]}
                for name, cid, wz in targets]

    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    if dm_user:      # a DM test gets the full set, zeros included
        targets = [(f"DM to {dm_user}",
                    client.conversations_open(users=dm_user)["channel"]["id"],
                    True)]

    out = []
    held = False
    for name, cid, wz in targets:
        ts_cache = {}

        def _ts_for(plain: str):
            if dm_user:
                return "dm"
            kind = "box" if plain.startswith("BOX ") else "b2b"
            if kind not in ts_cache:
                if kind == "box":
                    ts_cache[kind] = box_thread_ts(client, cid, day)
                else:
                    ts_cache[kind] = metrics_thread_ts(client, cid, day)
            return ts_cache[kind]

        for plain, caption, ups in _replies(imgs, zeros, tag,
                                            wz and not corrected, corrected):
            ts = _ts_for(plain)
            if ts is None:
                out.append({"channel": name, "reply": plain,
                            "held": "no BOX Order Log thread yet"})
                held = True
                continue
            if ts != "dm" and _already_replied(client, cid, ts, plain):
                out.append({"channel": name, "reply": plain,
                            "skipped": "already in thread"})
                continue
            r = client.files_upload_v2(
                channel=cid, thread_ts=None if ts == "dm" else ts,
                file_uploads=[{"file": str(p), "filename": f} for p, f in ups],
                initial_comment=caption)
            out.append({"channel": name, "reply": plain,
                        "images": len(ups), "ok": r.get("ok")})
            time.sleep(1)
    if held:
        out.append({"held": True})
    return out


def shown_sunday(shown: str, want_sunday):
    """The SUNDAY the gold cell is pointing at, or None if it can't be read.

    Only used to say WHICH WAY the board is off — forward (rolled early for
    today's fill) or backward (someone parked it on an old week). Handles the
    lost trailing zero the same way we_matches does: a WE is always a Sunday, so
    of `8.3` and `8.30` at most one can be, and that one is the answer.
    """
    try:
        m, d = (int(x) for x in str(shown).strip().split("."))
    except (ValueError, TypeError):
        return None
    for day in (d, d * 10):
        try:
            cand = dt.date(want_sunday.year, m, day)
        except ValueError:
            continue
        if cand.weekday() == 6:
            return cand
    return None


def _day_already_posted(day, yday) -> bool:
    """Did an EARLIER pass already ship today's thread in full?

    The week gate runs before anything is rendered, so a pass that fires AFTER a
    human rolls the board forward sees the "wrong" week and holds — even though
    the thread went out hours earlier on the right week. That is the normal
    Monday shape: the 5:00am fill closes out Sunday on week 8.23, we post, and
    then someone has to roll B2 to 8.30 before the 4:00pm fill (the roll-due
    reminder in #claudecorrections asks for it by name). On 2026-08-24 the 8:05
    pass held on that rolled board and opened an incident saying "today's thread
    was not posted" — three hours after it had been — whose fix line told the
    reader to set B2 back to 8.23, which would have broken the 4:00pm fill.

    A hold is only real if the day's boards are actually missing. True only when
    EVERY program's board reply is in the thread in EVERY target channel; any
    lookup failure returns False, since alerting twice beats swallowing a day
    that never posted.
    """
    targets = [t for t in TARGETS if t[1]]
    if os.environ.get("SALES_BOARD_CHANNEL_ID") or not targets:
        return False                      # a scratch-channel run proves nothing
    tag = f"{yday.month}.{yday.day}"
    try:
        from automations.shared import slack_metrics_post as smp
        import automations.b2b_quality.run as bq
        client = smp._client()
        for name, cid, _wz in targets:
            # Post-restructure the boards live in TWO threads: B2B in the B2B
            # Metrics thread (ts from the shared state file — never create it
            # from a checker), BOX in the BOX Order Log thread.
            for prog in [p for p in PROGRAMS if p != "BOX"]:
                ts = bq._load_state(day, cid).get("thread_ts")
                if not ts:
                    print(f"    ({name}: no B2B Metrics thread today)")
                    return False
                plain = f"{prog} Sales Board {tag}"
                if not _already_replied(client, cid, ts, plain):
                    print(f"    ({name}: {plain!r} is not in today's thread)")
                    return False
            if "BOX" in PROGRAMS:
                ts = box_thread_ts(client, cid, day)
                plain = f"BOX Sales Board {tag}"
                if not ts or not _already_replied(client, cid, ts, plain):
                    print(f"    ({name}: {plain!r} not posted yet)")
                    return False
    except Exception as e:  # noqa: BLE001 — unknown means "still might be missing"
        print(f"    (posted-check unavailable — {type(e).__name__}: {str(e)[:80]})")
        return False
    return True


def _alert_wrong_week(shown: str, want: str, yday, *, post: bool) -> None:
    """Say in #claudecorrections that we HELD, and name the cell that caused it.

    The hold below returns 75, and here that reaches nobody. Exit 75 only turns
    into an alert when the run came through `lucy rerun` or a Hub card; this
    report is driven by its OWN LaunchAgent (com.alphalete.sales-boards, 5:10am
    daily), so a hold is completely silent. On 2026-08-19 someone left the gold
    WE cell on an old week (8.9 while the board lived 8.23), this held at 5:10,
    and the missing production thread was only noticed three hours later — off a
    vantura-board-audit finding that happens to check the same cell. The board
    fix takes a minute once you know; the whole cost was not knowing.

    Best-effort and DRY-RUN AWARE: a human running `lucy rerun sales_boards`
    (no --post) to see where the board stands must not open a channel incident.

    Filed under the report's `standalone-` key so the one-thread-per-problem
    family rules apply, and so the next clean post closes it on its own
    (_publish_hub -> hub_publish -> resolve_report).
    """
    if not post:
        return
    # Which way is it off? A board sitting on a LATER week was rolled early for
    # the 4:00pm fill (the roll-due reminder asks for exactly that), so "set it
    # to 8.23" alone would leave the reader undoing the roll — and the fill
    # holding all afternoon. Say the whole round trip, or say nothing.
    sunday, _ = expected_we(yday)
    on = shown_sunday(shown, sunday)
    ahead = []
    if on and on > sunday:
        ahead = [f"Heads up: the board was rolled FORWARD to {shown} for "
                 f"today's fill — that roll is correct and has to stay. Set it "
                 f"to {want} only long enough for the next pass to post "
                 f"(≤25 min), then put it back on {shown} before the 4:00pm "
                 f"fill, or the fill holds all afternoon."]
    try:
        from automations.shared import incident_thread
        incident_thread.open_or_followup(
            key="standalone-sales_boards",
            title=f"Sales Boards held — the board is showing week {shown!r}, "
                  f"not {want!r}",
            channel_line=f"*Sales Boards* — gold WE cell reads {shown!r}, "
                         f"needs {want!r}; today's thread was not posted",
            body=[
                f"The Sales Board gold WE cell (tab 'Sales Board', row 2, right "
                f"of the 'WE' label) reads {shown!r}. {yday:%a %m/%d}'s numbers "
                f"live in week {want!r}, so posting now would ship the wrong "
                f"week — the run held instead and NOTHING was posted.",
                f"Fix: set that cell to {want}. Nothing else to re-run by hand; "
                "the next pass renders and posts, and closes this thread.",
                "Only some day cells are formulas keyed on that cell, so it is "
                "never rolled automatically — a human moves it to read an old "
                "week and forgets to move it back.",
                *ahead,
            ],
            label="Sales Boards → #alphalete-gp-sales",
        )
    except Exception:  # noqa: BLE001 — an alert must never change the hold
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--program", choices=PROGRAMS, help="just one program")
    ap.add_argument("--post", action="store_true",
                    help="ACTUALLY post to Slack (default dry-run)")
    ap.add_argument("--dm", metavar="USER_ID",
                    help="post the thread to a DM instead of the channel (test run)")
    ap.add_argument("--only-zeros", action="store_true",
                    help="render just the Zero Streak images (skip the boards)")
    ap.add_argument("--corrected", action="store_true",
                    help="re-post pass after an order-log correction: captions "
                         "carry '(corrected)' (so the morning reply doesn't "
                         "dedupe them away) and Zero Streaks are skipped")
    args = ap.parse_args(argv)

    today = dt.date.today()
    yday = today - dt.timedelta(days=1)
    # The 5:10 run posts B2B only: the BOX images move to the BOX Order Log
    # thread, which doesn't exist until box_order_log's 7:00 post — the
    # vantura_revenue_board 7:25 pass posts them (with corrected data, since
    # the 7:15 order-log confirm has run by then). --program BOX still works
    # for that pass and for the corrected re-post.
    programs = [args.program] if args.program else \
        [p for p in PROGRAMS if p != "BOX"]

    sh = open_by_key(SHEET_ID)
    src = _retry(lambda: sh.worksheet(TAB))
    print(f"sheet: {SHEET_ID[:12]}… "
          f"({'SANDBOX' if SHEET_ID == SANDBOX_SHEET_ID else 'PROD'})  tab={TAB}")

    # GATE: the board must be showing the week that contains YESTERDAY before we
    # render anything (on Monday that's last week's completed week).
    ok, shown, want = check_we(_retry(src.get_all_values), yday)
    sunday, _ = expected_we(yday)
    print(f"week check: board WE={shown!r}, need {want!r} "
          f"(week ending {sunday:%a %m/%d} — covers {yday:%a %m/%d})")
    if not ok:
        # A rolled-forward board is only a problem while the day is unposted —
        # see _day_already_posted. Checked before the hold so a late pass neither
        # alerts nor returns 75 (which the LaunchAgent ladder would keep retrying).
        if args.post and not args.dm and _day_already_posted(today, yday):
            print(f"WRONG WEEK for a re-run (board reads {shown!r}, "
                  f"{yday:%a %m/%d} lives in {want!r}) — but today's thread is "
                  "already posted in full, so there is nothing left to render. "
                  "The board has moved on to the week the 4:00pm fill needs; "
                  "that is correct, not a failure.")
            return 0
        print(f"WRONG WEEK — holding. The gold WE cell reads {shown!r} but "
              f"{yday:%a %m/%d}'s data lives in week {want!r}. Set B2 to {want} "
              "(or wait for the roll) and re-run; posting now would ship the "
              "wrong week.")
        _alert_wrong_week(shown, want, yday, post=args.post and not args.dm)
        return 75          # EX_TEMPFAIL — the scheduler retries

    # Open a live 'running' pill so the card PULSES while the boards render/post;
    # _publish_hub below closes this same row into green/red. Gate MUST match the
    # close (`not args.dm`) — a --post --dm DM-test never calls _publish_hub, so
    # opening a row there would leave a stale pill that never closes (Megan 2026-07-29).
    if args.post and not args.dm:
        try:
            from automations.day_orchestrator import hub_publish
            hub_publish.publish_running("sales_boards",
                                        "Sales Boards → #alphalete-gp-sales")
        except Exception:  # noqa: BLE001 — Hub publish must never break the post
            pass

    for w in sh.worksheets():                 # clear any orphan from a crashed run
        if w.title == TEMP_TAB:
            sh.del_worksheet(w)
    # Zeros render on their OWN throwaway tab — they overwrite the day columns with
    # a cross-week window, which would corrupt the boards if the two shared a copy.
    zrs = {} if args.corrected else \
        Z.render_zeros(sh, src, SHEET_ID, _token(), yday, OUT_DIR)

    imgs = {p: {} for p in programs}
    if not args.only_zeros:
        tmp = sh.duplicate_sheet(src.id, new_sheet_name=TEMP_TAB)
        try:
            sh.batch_update({"requests": [{"clearBasicFilter": {"sheetId": tmp.id}}]})
            imgs = R.render_all(sh, tmp, SHEET_ID, _token(), yday, OUT_DIR, programs)
        finally:
            sh.del_worksheet(tmp)
            print("temp tab removed")

    made = sum(len(v) for v in imgs.values()) + len(zrs)
    if not args.post:
        print(f"dry-run: {made} image(s) in {OUT_DIR}. Not posting.")
        for r in post_thread(imgs, zrs, today, yday, dry_run=True):
            print(f"WOULD post to {r['channel']} ({r['id']}) as a thread:")
            for line in r["header"].split("\n"):
                print(f"    {line}")
            for cap, names in r["replies"]:
                print(f"    ↳ {cap}  ({len(names)} image(s): {', '.join(names)})")
        return 0
    print("POSTING thread to Slack as Lucy:")
    try:
        results = post_thread(imgs, zrs, today, yday, dry_run=False,
                              dm_user=args.dm or "", corrected=args.corrected)
    except Exception:
        if not args.dm:              # a DM test shouldn't touch the Hub card either
            _publish_hub("failed")   # way — a failed test used to mark the card red
        raise
    for r in results:
        print(f"    {r}")
    held = any(r.get("held") for r in results if isinstance(r, dict))
    if not args.dm:                  # a DM test shouldn't touch the Hub card
        _publish_hub("partial" if held else "success")
    return 75 if held else 0


if __name__ == "__main__":
    sys.exit(main())
