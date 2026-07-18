"""Program Sales Boards — daily Slack thread (VA-replacement Items 5-8).

Replaces the VA's per-program Sales Board posts in #alphalete-gp-sales with ONE
dated thread (Megan 2026-07-17):

    *Vantura Production 07/18/2026*
    :briefcase: B2B Sales Board
    :zap: Base Sales Board
    :bulb: JE Sales Board
    :package: BOX Sales Board

…then each board's TWO images as a threaded reply — (a) the weekly ranking and
(b) the Highrollers cut for yesterday. Titled with YESTERDAY's date, matching the
VA (posted Sat 7/18 -> "BOX Sales Board 7.17").

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

SANDBOX_SHEET_ID = "15QzcyFqTzX9RYNJ2SvT_HOiyQsMU1v90wHjSUHA_cNc"   # re-copied 7/18
PROD_SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
# PROD by default as of go-live (Megan 2026-07-18). Set SALES_BOARD_SHEET_ID to
# the sandbox id to build against a copy again.
SHEET_ID = os.environ.get("SALES_BOARD_SHEET_ID", PROD_SHEET_ID)
TAB = "Sales Board"
TEMP_TAB = "_sb_render_tmp"          # ephemeral copy we create + delete

PROGRAMS = R.PROGRAMS
# The VA's per-program emoji, kept so the thread reads the way the channel is
# used to: ":briefcase: *B2B Sales Board 7.17*".
PROGRAM_EMOJI = {"B2B": ":briefcase:", "Base": ":zap:",
                 "JE": ":bulb:", "BOX": ":package:"}
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "sales_boards"
CHANNEL = ("#alphalete-gp-sales", "C07J46MQNUX")

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


def check_we(grid, yday):
    """(ok, shown, want). We deliberately do NOT rewrite B2 ourselves: only some
    day cells are formulas keyed on it (=INDEX(WeekData…MATCH(REP|$B$2))) — the
    rest are hand-typed, so flipping the selector would repopulate a few cells
    and leave stale typed numbers behind, producing a mixed-week board. If the
    selector is on the wrong week we HOLD and say so."""
    r, c = WE_CELL
    shown = (grid[r - 1][c - 1] if len(grid) >= r and len(grid[r - 1]) >= c else "").strip()
    _, want = expected_we(yday)
    return shown == want, shown, want


def header_title(day) -> str:
    """Parent's first line — also the needle used to find today's thread."""
    return f"Vantura Production {day.month:02d}/{day.day:02d}/{day.year}"


def header_text(day) -> str:
    return "\n".join([f"*{header_title(day)}*"]
                     + [f"{PROGRAM_EMOJI.get(p, '')} {p} Sales Board".strip()
                        for p in PROGRAMS])


def quality_header_text(day) -> str:
    title = f"{QUALITY_THREAD_TITLE} {day.month:02d}/{day.day:02d}/{day.year}"
    return "\n".join([f"*{title}*"] + [f"• {i}" for i in QUALITY_THREAD_ITEMS])


def _channel():
    scratch = os.environ.get("SALES_BOARD_CHANNEL_ID")
    return (f"scratch ({scratch})", scratch) if scratch else CHANNEL


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


def post_thread(imgs: dict, day, yday, dry_run: bool, dm_user: str = "") -> list:
    """Find-or-create today's parent, then post each board's images as a reply.
    dm_user routes the whole thread into a DM instead — same code path, used to
    prove the multi-image threaded upload before pointing it at the channel."""
    name, cid = _channel()
    tag = f"{yday.month}.{yday.day}"
    if dry_run:
        return [{"dry_run": True, "channel": name, "id": cid,
                 "header": header_text(day),
                 "replies": [(f"{PROGRAM_EMOJI.get(p, '')} *{p} Sales Board {tag}*".strip(),
                              sorted(v)) for p, v in imgs.items() if v]}]
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    if dm_user:
        cid = client.conversations_open(users=dm_user)["channel"]["id"]
        name = f"DM to {dm_user}"
    ts = find_thread_ts(client, cid, day)
    created = False
    if not ts:
        ts = client.chat_postMessage(channel=cid, text=header_text(day)).get("ts")
        created = True
    out = [{"channel": name, "thread_ts": ts, "created_parent": created}]
    for p in PROGRAMS:
        parts = imgs.get(p) or {}
        if not parts:
            continue
        plain = f"{p} Sales Board {tag}"
        caption = f"{PROGRAM_EMOJI.get(p, '')} *{plain}*".strip()
        # dedupe on the PLAIN text — Slack may store the emoji as a shortcode or
        # the rendered character, so matching the caption verbatim is unreliable
        if _already_replied(client, cid, ts, plain):
            out.append({"board": p, "skipped": "already in thread"})
            continue
        uploads = [{"file": str(parts[k]), "filename": f"{plain} ({k}).png"}
                   for k in ("a", "b") if k in parts]
        r = client.files_upload_v2(channel=cid, thread_ts=ts,
                                   file_uploads=uploads, initial_comment=caption)
        out.append({"board": p, "images": len(uploads), "ok": r.get("ok")})
        time.sleep(1)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--program", choices=PROGRAMS, help="just one program")
    ap.add_argument("--post", action="store_true",
                    help="ACTUALLY post to Slack (default dry-run)")
    ap.add_argument("--dm", metavar="USER_ID",
                    help="post the thread to a DM instead of the channel (test run)")
    args = ap.parse_args(argv)

    today = dt.date.today()
    yday = today - dt.timedelta(days=1)
    programs = [args.program] if args.program else PROGRAMS

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
        print(f"WRONG WEEK — holding. The gold WE cell reads {shown!r} but "
              f"{yday:%a %m/%d}'s data lives in week {want!r}. Set B2 to {want} "
              "(or wait for the roll) and re-run; posting now would ship the "
              "wrong week.")
        return 75          # EX_TEMPFAIL — the scheduler retries

    for w in sh.worksheets():                 # clear any orphan from a crashed run
        if w.title == TEMP_TAB:
            sh.del_worksheet(w)
    tmp = sh.duplicate_sheet(src.id, new_sheet_name=TEMP_TAB)
    try:
        sh.batch_update({"requests": [{"clearBasicFilter": {"sheetId": tmp.id}}]})
        imgs = R.render_all(sh, tmp, SHEET_ID, _token(), yday, OUT_DIR, programs)
    finally:
        sh.del_worksheet(tmp)
        print("temp tab removed")

    made = sum(len(v) for v in imgs.values())
    if not args.post:
        print(f"dry-run: {made} image(s) in {OUT_DIR}. Not posting.")
        r = post_thread(imgs, today, yday, dry_run=True)[0]
        print(f"WOULD post to {r['channel']} ({r['id']}) as a thread:")
        for line in r["header"].split("\n"):
            print(f"    {line}")
        for cap, keys in r["replies"]:
            print(f"    ↳ {cap}  ({len(keys)} image(s): {', '.join(keys)})")
        return 0
    print("POSTING thread to Slack as Lucy:")
    for r in post_thread(imgs, today, yday, dry_run=False, dm_user=args.dm or ""):
        print(f"    {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
