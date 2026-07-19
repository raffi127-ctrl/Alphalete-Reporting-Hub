"""B2B Quality & Bonus — daily Slack thread (VA-replacement Item 5).

The three ATTTRACKER-B2B Tableau views the VA posts each morning, moved into
their own dated thread in #alphalete-gp-sales (Megan 2026-07-17 — she picked the
title over "B2B Performance" / "Alphalete B2B Metrics" / "B2B Scorecard"):

    *B2B Quality & Bonus 07/18/2026*
    • Tiered Bonus
    • Activation Rate
    • Churn Rate

…then each view's image as a threaded reply, titled with YESTERDAY's date to
match her convention ("Tiered Bonus 7.17.png").

The Sales Boards moved OUT of her old combined "Alphalete B2B" post into the
separate "Vantura Production" thread (automations/sales_boards), leaving these
three as the quality/payout half.

CAPTURE: rides the same machinery as the tracker screenshots — Tableau's own
Download → Image on a logged-in session (NOT a page screenshot, which drags in
browser chrome). So it MUST run on Lucy 1: ownerville is single-session and a
laptop scrape evicts the session holder.

DRY-RUN by default — posting needs --post.

Usage:
  lucy rerun b2b_quality                     # capture only, no post
  lucy rerun b2b_quality --post              # capture + post the thread
  lucy rerun b2b_quality --post --dm U…      # post to a DM (test)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path

_BASE = "https://us-east-1.online.tableau.com/#/site/sci/views/"
_IFRAME = 'iframe[title="Data Visualization"]'      # matches tableau_screenshots.capture
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
    },
    {
        "id": "activation_rate",
        "title": "Activation Rate",
        "emoji": "\U000026A1",                 # zap
        "url": _BASE + ("ATTTRACKER-B2B/ACTIVATIONRATES/"
                        "4c53fb7e-5a1b-4e8f-990e-0b2c8cf42309/"
                        "CarlosLocalOfficeEXPANDED?:iid=2"),
        "crop": "canvas",
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
        # NO sort_header on purpose. Megan wants this sorted 0-30 Day high->low,
        # but Tableau's glyph on THIS view only cycles ascending <-> cleared —
        # descending is not reachable by clicking, so a sort here would post
        # blanks-first, which is worse than the default. The unsorted default is
        # byte-for-byte what Jolie posts today (verified against her 7/17 image),
        # so we match her until the sort is saved into the custom view itself.
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
    return "\n".join([f"*{header_title(day)}*"] + [f"• {s['title']}" for s in SPECS])


def _channel():
    scratch = os.environ.get("B2B_QUALITY_CHANNEL_ID")
    return (f"scratch ({scratch})", scratch) if scratch else CHANNEL


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
        if cut >= H - 4:
            return False                                      # nothing to trim
        im.crop((0, 0, W, cut)).save(png)
        if verbose:
            print(f"   ✂ cropped to last row with data ({H} -> {cut}px)", flush=True)
        return True
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
                # The sort must run INSIDE capture_page: it navigates to the URL
                # itself, so sorting beforehand is silently undone.
                hook = None
                if spec.get("sort_header"):
                    hook = (lambda p, h=spec["sort_header"],
                            c=spec.get("sort_clicks", 1):
                            apply_sort(p, h, clicks=c, verbose=True))
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
    needle = header_title(day)
    for m in resp.get("messages", []):
        if needle in (m.get("text") or ""):
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
        text = (m.get("text") or "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        if plain in text:
            return True
        if any((f.get("name") or "").startswith(plain) for f in (m.get("files") or [])):
            return True
    return False


def post_thread(imgs: dict, day, yday, dry_run: bool, dm_user: str = "") -> list:
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
    ts = find_thread_ts(client, cid, day)
    created = False
    if not ts:
        ts = client.chat_postMessage(channel=cid, text=header_text(day)).get("ts")
        created = True
    out = [{"channel": name, "thread_ts": ts, "created_parent": created}]
    for spec in SPECS:
        png = imgs.get(spec["id"])
        if not png:
            continue
        plain = f"{spec['title']} {tag}"
        caption = f"{spec['emoji']} *{plain}*"
        if _already_replied(client, cid, ts, plain):
            out.append({"view": spec["id"], "skipped": "already in thread"})
            continue
        r = client.files_upload_v2(channel=cid, thread_ts=ts, file=str(png),
                                   filename=f"{plain}.png", initial_comment=caption)
        out.append({"view": spec["id"], "ok": r.get("ok")})
        time.sleep(1)
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
        results = post_thread(imgs, today, yday, dry_run=False, dm_user=args.dm or "")
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
