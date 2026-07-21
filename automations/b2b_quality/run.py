"""B2B Quality & Bonus — daily Slack thread (VA-replacement Item 5).

The three ATTTRACKER-B2B Tableau views the VA posts each morning, moved into
their own dated thread in #alphalete-gp-sales (Megan 2026-07-17 — she picked the
title over "B2B Performance" / "Alphalete B2B Metrics" / "B2B Scorecard"):

    *B2B Quality & Bonus 07/18/2026*
    🎯 Tiered Bonus
    ⚡ Activation Rate
    📉 Churn Rate

…then each view's image as a threaded reply, titled with YESTERDAY's date to
match her convention ("Tiered Bonus 7.17.png").

The Sales Boards moved OUT of her old combined "Alphalete B2B" post into the
separate "Vantura Production" thread (automations/sales_boards), leaving these
three as the quality/payout half.

CAPTURE: rides the same machinery as the tracker screenshots — Tableau's own
Download → Image on a logged-in session (NOT a page screenshot, which drags in
browser chrome).

**RUNS ON LUCY 2 — correctness requirement, not a preference.** Lucy 2 is
signed in as CARLOS, Lucy 1 as Raf. These are Carlos's custom views
(CarlosLocalOffice*).

ACTIVATION'S SORT IS NOT SAVED IN ITS VIEW — we apply it (apply_sort clicks the
0-7 Days sort glyph). The click lands on Lucy 2's rendering and MISSES on
Lucy 1's, which is the whole reason this is pinned to Lucy 2. Churn needs no
click: its view really does carry its own sort (by 0-30 Day disconnect COUNT).

History, so nobody re-derives it wrong twice (I did): on 2026-07-18 a Lucy 2 run
came back correctly sorted and I concluded Carlos's login supplied the sort, so
I deleted the clicker. It hadn't — that run was on the PRE-deletion commit and
the click did the work. Removing it put an alphabetical Activation board in the
channel the next morning. If this looks unsorted again, the click missed; do NOT
conclude the login fixed it.

Two independent guards now stop a wrong image reaching Slack:
  * wait_for_custom_view — the viz must report "View: <custom view>" before we
    photograph it (capture.py lets this raise rather than shoot the default).
  * crop_to_last_data_row raises UnsortedViewError if rows above the crop are
    empty in the leading column — impossible when that column is sorted.
A blocked view is SKIPPED + FLAGGED; the later retry passes post it into the
same thread once it comes back right.

Also don't capture from the laptop: ownerville is single-session there and a
laptop scrape evicts the session holder out from under Lucy 1's other reports.

DRY-RUN by default — posting needs --post.

Usage:
  lucy rerun b2b_quality                     # capture only, no post
  (always with `--machine "Lucy 2"` — see above)
  lucy rerun b2b_quality --post              # capture + post the thread
  lucy rerun b2b_quality --post --dm U…      # post to a DM (test)
  lucy rerun b2b_quality --post --thread-ts 1784459700.561209   # into THAT thread

THREADING: a day's posts belong in ONE thread. The dedup guards that read Slack
(find_thread_ts / _already_replied) are unreliable here — Lucy's token cannot
read this channel's history at all, so they silently report "no thread yet" and
every retry pass opens its own (four identical threads, 2026-07-19). The
authority is output/b2b_quality/thread_state.json (day|channel -> thread_ts +
which views posted); it needs no Slack scope. That state is PER MACHINE, so if a
thread was opened elsewhere, pass --thread-ts rather than trusting the lookup.
ROOT FIX still open: give Lucy's token channels:history on #alphalete-gp-sales
and find_thread_ts becomes a real backstop.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import sys
import time
from pathlib import Path

_BASE = "https://us-east-1.online.tableau.com/#/site/sci/views/"
_IFRAME = 'iframe[title="Data Visualization"]'   # matches tableau_screenshots.capture
SORT_ICON_DX = 8        # px right of the header text where the sort glyph draws

# Saved views carry the filters the VA uses (Carlos's office). The GUID + saved
# view name in each URL is what pins those filters — don't trim them.
SPECS = [
    {
        "id": "tiered_bonus",
        "title": "Tiered Bonus",
        "emoji": "\U0001F3AF",                 # dart
        "url": _BASE + ("ATTTRACKER-B2B/OrderTieredBonus-RepRanking/"
                        "d8e25f41-e23b-4d82-bb9d-4c52dde38b9e/CarlosLocalOffice?:iid=1"),
        "crop": "canvas",
        "view_label": "Carlos Local Office",
    },
    {
        "id": "activation_rate",
        "title": "Activation Rate",
        "emoji": "\U000026A1",                 # zap
        "url": _BASE + ("ATTTRACKER-B2B/ACTIVATIONRATES/"
                        "4c53fb7e-5a1b-4e8f-990e-0b2c8cf42309/"
                        "CarlosLocalOfficeEXPANDED?:iid=2"),
        "crop": "canvas",
        "view_label": "Carlos Local Office EXPANDED",
        "sort_header": "0-7 Days",
        "data_cols": 4,          # 0-7 / 8-14 / 15-30 / 31-60
    },
    {
        "id": "churn_rate",
        "title": "Churn Rate",
        "emoji": "\U0001F4C9",                 # chart_with_downwards_trend
        "url": _BASE + ("ATTTRACKER-B2B/CHURNRATES/"
                        "7419b960-0fb1-41d5-a11e-76f0e81c0547/"
                        "CarlosLocalOfficeEXPANDEDCHURN?:iid=1"),
        "crop": "canvas",
        "view_label": "Carlos Local Office EXPANDED CHURN",
        # Sorted by the 0-30 Day DISCONNECT COUNT desc (3, 2, 1, 1, ..., 0, 0) —
        # NOT by the percentage. Reading the % column makes it look unsorted; it
        # isn't. The view carries this itself under Carlos's login, so there is
        # nothing to apply here. Matches Jolie's post row-for-row.
        "data_cols": 5,          # 0-30 / 30 / 60 / 90 / 120
    },
]

THREAD_TITLE = "B2B Quality & Bonus"
CHANNEL = ("#alphalete-gp-sales", "C07J46MQNUX")
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "b2b_quality"


def header_title(day) -> str:
    """Parent's first line — also the needle used to find today's thread."""
    return f"{THREAD_TITLE} {day.month:02d}/{day.day:02d}/{day.year}"


def header_text(day) -> str:
    """Parent message: title, then one line per view led by that view's emoji
    (Megan 2026-07-19 — the emoji REPLACES the bullet, it isn't added to it), so
    the header reads the same as the threaded replies underneath it."""
    return "\n".join([f"*{header_title(day)}*"]
                     + [f"{s['emoji']} {s['title']}" for s in SPECS])


def _channel():
    scratch = os.environ.get("B2B_QUALITY_CHANNEL_ID")
    return (f"scratch ({scratch})", scratch) if scratch else CHANNEL


class UnsortedViewError(RuntimeError):
    """The captured table is not sorted on its leading column, so the image would
    be wrong. Raised instead of posting — see crop_to_last_data_row."""


def crop_to_last_data_row(png: Path, data_cols: int, verbose: bool = False) -> bool:
    """Trim the image so it ENDS on the last row with a value in the FIRST data
    column (Megan 2026-07-18: "it needs to end with the last row that has data in
    the 0-30 day section"). Same rule she gave for Activation's 0-7 Days column.

    This is the crop the VA does by hand — it is NOT a filter. Reps below the cut
    still exist in the view; they just have nothing in the leading column, so the
    posted image stops before them. It also drops the second table further down
    the Churn dashboard (the Disconnect Reason breakdown), which she never posts.

    Works off the colour fills: every populated cell is a red/green/yellow block,
    every empty one is white. Order-independent — it finds the last row that has
    data, wherever that row sits. Best-effort: on any doubt the image is left at
    full length rather than cut wrong. Returns True if it trimmed.
    """
    try:
        from PIL import Image
    except ImportError:
        return False

    def saturated(p):
        return max(p) - min(p) > 45 and max(p) > 90

    try:
        im = Image.open(png).convert("RGB")
        W, H = im.size
        px = im.load()
        # Column geometry from a band safely inside the rep table: below the
        # National Average strip, above anything that follows the table.
        probe_lo, probe_hi = 400, min(H, 1200)
        if probe_hi - probe_lo < 100:
            return False
        counts = [sum(1 for y in range(probe_lo, probe_hi) if saturated(px[x, y]))
                  for x in range(W)]
        xs = [x for x in range(W) if counts[x] > 60]
        if not xs:
            return False
        # The data cells butt up against each other (no white gutter survives the
        # export), so the whole block reads as ONE run — split it evenly instead.
        left, right = xs[0], xs[-1]
        width = (right - left) // max(1, data_cols)
        if width < 10:
            return False
        c0, c1 = left, left + width

        def has_colour(y, a, b):
            return any(saturated(px[x, y]) for x in range(a, b))

        ys = [y for y in range(probe_lo, H) if has_colour(y, left, right)]
        if not ys:
            return False
        bands, start, prev = [], ys[0], ys[0]
        for y in ys[1:]:
            if y - prev > 3:
                bands.append((start, prev))
                start = y
            prev = y
        bands.append((start, prev))
        bands = [b for b in bands if b[1] - b[0] >= 8]        # drop specks
        with_data = [b for b in bands
                     if any(has_colour(y, c0, c1) for y in range(b[0], b[1] + 1))]
        if not with_data:
            return False
        cut = min(H, with_data[-1][1] + 4)                    # +4 keeps the border
        # SORT CHECK, independent of anything Tableau tells us. When the leading
        # column is sorted, every row above the cut has a value in it (blanks sort
        # last). If rows up there are EMPTY in that column, the table came back
        # unsorted — the 2026-07-19 failure — and the image must not be posted.
        above = [b for b in bands if b[1] <= cut]
        blanks = len(above) - len([b for b in above if b in with_data])
        if blanks > 0:
            raise UnsortedViewError(
                f"{blanks} of {len(above)} rows above the cut are empty in the "
                f"leading column — the view came back UNSORTED")
        if cut >= H - 4:
            return False                                      # nothing to trim
        im.crop((0, 0, W, cut)).save(png)
        if verbose:
            print(f"   ✂ cropped to last row with data ({H} -> {cut}px)", flush=True)
        return True
    except UnsortedViewError:
        raise                          # never swallowed — skip+flag beats posting wrong
    except Exception as e:  # noqa: BLE001 — a bad crop must not lose the image
        if verbose:
            print(f"   ⚠ crop failed ({type(e).__name__}) — full length kept",
                  flush=True)
        return False


def capture_all(out_dir: Path, only=None, headless: bool = True) -> dict:
    """{spec_id: png_path} via Tableau's Download → Image. A view that fails is
    SKIPPED and flagged rather than posted wrong — same rule as the trackers."""
    from automations.shared.tableau_patchright import tableau_session
    from automations.tableau_screenshots import capture as cap
    specs = [s for s in SPECS if not only or s["id"] in only]
    out, failed = {}, []
    out_dir.mkdir(parents=True, exist_ok=True)
    with tableau_session(headless=headless, allow_form_login=False, verbose=True) as page:
        for spec in specs:
            try:
                def hook(p, sp=spec):
                    if sp.get("view_label"):
                        wait_for_custom_view(p, sp["view_label"])
                    if sp.get("sort_header"):
                        apply_sort(p, sp["sort_header"],
                                   clicks=sp.get("sort_clicks", 1), verbose=True)
                png = cap.capture_page(page, spec, out_dir, after_load=hook, verbose=True)
                if spec.get("data_cols"):
                    crop_to_last_data_row(png, spec["data_cols"], verbose=True)
                out[spec["id"]] = png
                print(f"   ✓ {spec['title']} -> {png.name}", flush=True)
            except Exception as e:  # noqa: BLE001 — one bad view must not kill the rest
                failed.append(spec["id"])
                print(f"   ⚠ {spec['id']} FAILED: {type(e).__name__}: "
                      f"{str(e).splitlines()[0][:120]}", flush=True)
    if failed:
        print(f"captured {len(out)}/{len(specs)} — failed: {', '.join(failed)}", flush=True)
    return out


def _rep_table_header(fr, header: str):
    """Bounding box of the REP TABLE's `header` column label, or None.

    The label repeats per dashboard (Churn has four: the National Average band,
    the rep table, and another table far below), and neither DOM order nor
    "lowest on page" picks the right one on both dashboards. Anchor on the
    section title instead — the rep table's header is the first match below
    "<name> Owner (+/-) Rep".
    """
    # EXACT text — has_text= also matches every wrapper div up the tree, and
    # hovering one of those times out instead of surfacing the sort control.
    hdrs = fr.locator(f'div.tab-vizHeader >> text="{header}"')
    n = hdrs.count()
    if not n:
        return None
    tbox = fr.locator('text=/Owner \\(\\+/-\\) Rep/').first.bounding_box()
    if not tbox:
        return None
    below = [b for b in (hdrs.nth(i).bounding_box() for i in range(n))
             if b and b["y"] > tbox["y"]]
    return min(below, key=lambda b: b["y"]) if below else None


def apply_sort(page, header: str, clicks: int = 1, verbose: bool = False) -> bool:
    """Click a measure column's sort button, high→low — the manual step Jolie does
    before she downloads (Megan 2026-07-18: "you just hit the sorter button on
    tableau then take a screenshot and clip it").

    The custom views carry Carlos's FILTERS but not his SORT, so without this the
    image comes back in the table's default alphabetical-by-rep order. That's the
    bug behind both Activation Rate and Churn Rate posting wrong.

    Session-local: a header sort is not written back to the shared custom view, so
    Carlos's and Jolie's own Tableau are untouched. Returns False (and leaves the
    view alone) if the header or its control can't be found — the caller still
    captures, because an unsorted image beats no image.
    """
    fr = page.frame_locator(_IFRAME)
    try:
        # Drive the real mouse: locator.hover() times out here (the viz repaints
        # constantly so actionability never settles), and bounding_box() on a frame
        # locator is ALREADY page-relative — adding the iframe offset lands the
        # pointer on a data mark instead. The sort glyph itself is DRAWN, not a DOM
        # node, so no selector can reach it: hover the header text to arm it, then
        # click SORT_ICON_DX px to its right.
        for i in range(max(1, clicks)):
            # RE-RESOLVE from scratch each pass. Sorting re-renders the table, which
            # both shifts the header AND reshuffles the match order — so a cached
            # index or a cached box makes clicks 2+ land somewhere else entirely.
            box = _rep_table_header(fr, header)
            if not box:
                if verbose:
                    print(f"   ⚠ sort: {header!r} header not found "
                          f"(pass {i + 1})", flush=True)
                return i > 0
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.wait_for_timeout(1_500)
            page.mouse.move(box["x"] + box["width"] + SORT_ICON_DX,
                            box["y"] + box["height"] / 2)
            page.wait_for_timeout(1_200)
            page.mouse.down()
            page.wait_for_timeout(120)
            page.mouse.up()
            page.wait_for_timeout(6_000)
        if verbose:
            print(f"   ↕ sorted {header!r} ({clicks} click(s))", flush=True)
        return True

    except Exception as e:  # noqa: BLE001 — never lose the capture over the sort
        if verbose:
            print(f"   ⚠ sort on {header!r} failed: {type(e).__name__}", flush=True)
        return False



def wait_for_custom_view(page, label: str, timeout_ms: int = 90_000) -> None:
    """Block until Tableau reports the CUSTOM VIEW is the one on screen.

    The viewer renders the workbook's DEFAULT view first and swaps in the custom
    view a moment later. On a warm session that gap is invisible; on the first
    cold load of the morning it is not, and a fixed hydrate wait captures the
    default — which is unsorted, so Activation posts in alphabetical order.
    That is the 2026-07-19 5:30am failure: identical code posted correctly at
    21:55 the night before, when the session was warm.

    Tableau puts "View: <name>" in the viz toolbar; that string IS the proof the
    swap has happened. Poll for it instead of trusting a timer.

    RAISES on timeout — deliberately. capture_page lets this propagate so the
    view is SKIPPED AND FLAGGED rather than posted wrong, which is this module's
    standing rule.
    """
    import time as _t
    needle = f"View: {label}"
    fr = page.frame_locator(_IFRAME)
    deadline = _t.time() + timeout_ms / 1000
    last = ""
    while _t.time() < deadline:
        try:
            last = fr.locator("body").inner_text(timeout=10_000)
            if needle in last:
                return
        except Exception:  # noqa: BLE001 — viz still painting; keep polling
            pass
        page.wait_for_timeout(2_000)
    shown = next((ln.strip() for ln in last.splitlines() if ln.strip().startswith("View:")),
                 "(no View: line)")
    raise RuntimeError(
        f"custom view never applied: wanted {needle!r}, toolbar showed {shown!r}")


STATE_FILE = OUT_DIR / "thread_state.json"


def _load_state(day, channel: str) -> dict:
    """Today's {thread_ts, posted:[view_id]} for this channel, or empty.

    The Slack-read guards below (find_thread_ts / _already_replied) BOTH degrade
    to "no match" when the token can't read history — and on a retry schedule
    that means every pass starts a brand-new thread. That is exactly what
    happened on the first live morning (2026-07-19: four identical threads at
    5:32 / 5:40 / 5:48 / 5:56). This file is the authoritative guard because it
    needs no Slack scope at all; the API checks are now just a backstop.
    """
    try:
        import json
        blob = json.loads(STATE_FILE.read_text())
    except Exception:  # noqa: BLE001 — missing/corrupt state must not block a post
        return {}
    entry = blob.get(f"{day.isoformat()}|{channel}")
    return entry if isinstance(entry, dict) else {}


def _save_state(day, channel: str, thread_ts: str, posted: list) -> None:
    """Best-effort persist — never let a state write failure lose the post."""
    try:
        import json
        try:
            blob = json.loads(STATE_FILE.read_text())
        except Exception:  # noqa: BLE001
            blob = {}
        blob[f"{day.isoformat()}|{channel}"] = {"thread_ts": thread_ts,
                                                "posted": sorted(set(posted))}
        # keep only the last ~10 day|channel keys so this never grows unbounded
        for k in sorted(blob)[:-10]:
            blob.pop(k, None)
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(blob, indent=2))
    except Exception:  # noqa: BLE001
        pass


def find_thread_ts(client, channel: str, day):
    """ts of today's parent so a re-run never starts a second thread. Degrades to
    None (start fresh) if the history read fails — Lucy's token lacks im:history,
    which would otherwise crash a --dm test after the captures."""
    oldest = dt.datetime.combine(dt.date.today(), dt.time.min).timestamp()
    try:
        resp = client.conversations_history(channel=channel, oldest=str(oldest), limit=200)
    except Exception as e:  # noqa: BLE001
        print(f"    (thread lookup unavailable — {type(e).__name__}; new thread)")
        return None
    # Slack HTML-escapes message text on read, so the parent's "&" comes back
    # as "&amp;" ("B2B Quality &amp; Bonus …"). Matching the raw title with a
    # literal "&" therefore never hit and find_thread_ts always returned None —
    # masked only because the caller falls back to the state file. Unescape
    # both sides before comparing. (2026-07-20)
    needle = html.unescape(header_title(day))
    for m in resp.get("messages", []):
        if needle in html.unescape(m.get("text") or ""):
            return m.get("thread_ts") or m.get("ts")
    return None


def _already_replied(client, channel: str, thread_ts: str, plain: str) -> bool:
    """Two signals — caption text OR attached filename. files_upload_v2 doesn't
    guarantee initial_comment survives as the message text, and a false negative
    re-posts the image on the next pass."""
    try:
        rs = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
    except Exception:  # noqa: BLE001
        return False
    for m in rs.get("messages", []):
        text = html.unescape(m.get("text") or "")
        if plain in text:
            return True
        if any((f.get("name") or "").startswith(plain) for f in (m.get("files") or [])):
            return True
    return False


def post_thread(imgs: dict, day, yday, dry_run: bool, dm_user: str = "",
                thread_ts: str = "") -> list:
    name, cid = _channel()
    tag = f"{yday.month}.{yday.day}"
    if dry_run:
        return [{"dry_run": True, "channel": name, "id": cid, "header": header_text(day),
                 "replies": [f"{s['emoji']} *{s['title']} {tag}*"
                             for s in SPECS if s["id"] in imgs]}]
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    if dm_user:
        cid = client.conversations_open(users=dm_user)["channel"]["id"]
        name = f"DM to {dm_user}"
    # Local state FIRST — it is the only guard that works without a history read.
    state = _load_state(day, cid)
    posted = list(state.get("posted") or [])
    # --thread-ts wins: the state file is per-machine, so a thread opened by a
    # different runner (or one whose state was lost) is otherwise invisible and
    # we would open a SECOND thread. find_thread_ts can't be relied on to catch
    # that — Lucy's token can't read this channel's history at all.
    ts = thread_ts or state.get("thread_ts") or find_thread_ts(client, cid, day)
    if thread_ts:
        print(f"    (using --thread-ts {thread_ts})")
    created = False
    if not ts:
        ts = client.chat_postMessage(channel=cid, text=header_text(day)).get("ts")
        created = True
        _save_state(day, cid, ts, posted)
    out = [{"channel": name, "thread_ts": ts, "created_parent": created}]
    for spec in SPECS:
        png = imgs.get(spec["id"])
        if not png:
            continue
        plain = f"{spec['title']} {tag}"
        caption = f"{spec['emoji']} *{plain}*"
        if spec["id"] in posted or _already_replied(client, cid, ts, plain):
            out.append({"view": spec["id"], "skipped": "already in thread"})
            continue
        r = client.files_upload_v2(channel=cid, thread_ts=ts, file=str(png),
                                   filename=f"{plain}.png", initial_comment=caption)
        out.append({"view": spec["id"], "ok": r.get("ok")})
        posted.append(spec["id"])
        _save_state(day, cid, ts, posted)      # after EACH upload, so a crash
        time.sleep(1)                          # mid-thread can't re-post the rest
    return out


def _publish_hub(status: str) -> None:
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done("b2b_quality",
                                 "B2B Quality & Bonus → #alphalete-gp-sales", status)
    except Exception:  # noqa: BLE001
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated view ids")
    ap.add_argument("--post", action="store_true", help="ACTUALLY post (default dry-run)")
    ap.add_argument("--dm", metavar="USER_ID", help="post the thread to a DM (test)")
    ap.add_argument("--thread-ts", default="", metavar="TS",
                    help="post into THIS existing thread instead of finding/creating one")
    ap.add_argument("--show", action="store_true", help="run the browser headed")
    args = ap.parse_args(argv)

    today = dt.date.today()
    yday = today - dt.timedelta(days=1)
    only = {s.strip() for s in args.only.split(",")} if args.only else None

    imgs = capture_all(OUT_DIR, only=only, headless=not args.show)
    if not imgs:
        print("no views captured — nothing to post.")
        _publish_hub("failed")
        return 75           # EX_TEMPFAIL: let the scheduler retry

    # ORDER: within a pass we always post in SPECS order (🎯 → ⚡ → 📉), so a
    # complete capture reads exactly like the header. A view that IS missing does
    # NOT hold the others back — Megan 2026-07-19: "order isn't crazy important
    # here if it holds anything up". A straggler recovered by a later pass lands
    # at the bottom of the thread, and that is fine; getting the boards in front
    # of people on time is worth more than the reading order.
    wanted = [s["id"] for s in SPECS if not only or s["id"] in only]
    missing = [i for i in wanted if i not in imgs]
    if missing:
        print(f"posting {len(imgs)}/{len(wanted)} — missing: {', '.join(missing)} "
              f"(a later pass adds it at the end of the thread)")

    if not args.post:
        r = post_thread(imgs, today, yday, dry_run=True)[0]
        print(f"dry-run: {len(imgs)} image(s) in {OUT_DIR}. Not posting.")
        print(f"WOULD post to {r['channel']} ({r['id']}) as a thread:")
        for line in r["header"].split("\n"):
            print(f"    {line}")
        for rep in r["replies"]:
            print(f"    ↳ {rep}  (+ image)")
        return 0

    print("POSTING thread to Slack as Lucy:")
    try:
        results = post_thread(imgs, today, yday, dry_run=False, dm_user=args.dm or "",
                              thread_ts=args.thread_ts)
    except Exception:
        _publish_hub("failed")
        raise
    for r in results:
        print(f"    {r}")
    if not args.dm:
        _publish_hub("success")
    return 0


if __name__ == "__main__":
    sys.exit(main())
