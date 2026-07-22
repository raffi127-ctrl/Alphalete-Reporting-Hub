"""Churn tab → PNG, posted alongside the Activations order-log message.

Carlos's ask (Loom 2026-07-19, 5:08): "if all of this right here could get
screenshotted and sent with where the activations order log thing is going
to get posted". That post is the Lucy thread in #alphalete-gp-sales
(automations.box_order_log.run.CHANNEL), so this renders the VISIBLE churn
block and uploads it there.

Rendering reuses the Org Sales Board technique: the Sheets PDF-export
endpoint on an explicit A1 range, rasterised and trimmed. That keeps the
exact-sheet look (conditional fills, borders, fonts) with no browser.

Posting is OFF unless --post is passed. Standing rule: nothing goes to
Slack without Megan saying so.
"""
from __future__ import annotations

import datetime as dt
import html
import io
from pathlib import Path

import requests
from google.auth.transport.requests import Request as _GARequest
from google.oauth2.credentials import Credentials

from automations.recruiting_report.fill import SCOPES, OAUTH_TOKEN_PATH
from automations.vantura_churn.fill import SHEET_ID

# The block Carlos means by "all of this right here": the control box, the
# activation-rate cells, the tiers chart and the rolloff list — i.e. every
# VISIBLE column, down to the end of the rolloff table. Bounds are resolved
# from the tab at render time, never hardcoded row/col indices.
FIRST_COL = "A"


def _access_token() -> str:
    creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN_PATH), SCOPES)
    creds.refresh(_GARequest())
    return creds.token


def visible_range(ws, helper_first_col: str = None) -> str:
    """A1 range covering the report block: columns A..(col before the helper
    block), rows 1..last populated.

    The helper column is DERIVED from the tab's own formulas by default — it
    moves when a column is inserted or removed, and a stale constant here
    silently reframes the shot. Bounded by the widest visible column, not
    column A: A holds a FILTER whose spill is one row (or #N/A) when there
    are no disconnects, which would crop the whole table out.
    """
    from automations.vantura_churn import fill
    if helper_first_col is None:
        helper_first_col = fill._colletter(fill.helper_bounds(ws)["f0"])
    scan_last = fill._col_idx(helper_first_col) - 1
    grid = ws.get(f"{FIRST_COL}1:{fill._colletter(scan_last)}{ws.row_count}")
    # Bound to the last row AND last column that actually hold content — the
    # block ends a column or two before the helper block, so stopping at
    # helper-1 leaves a blank strip of white on the right of the shot.
    last_row = last_col_i = 0
    for i, row in enumerate(grid, start=1):
        for j, c in enumerate(row):
            if str(c).strip():
                last_row = i
                last_col_i = max(last_col_i, j)
    return (f"{FIRST_COL}1:{fill._colletter(last_col_i)}"
            f"{max(last_row, 20)}")


def render(ws, out_path: Path, rng: str | None = None) -> Path:
    """Render `rng` of `ws` to a trimmed PNG."""
    import fitz  # PyMuPDF
    from PIL import Image, ImageChops
    import time

    rng = rng or visible_range(ws)
    token = _access_token()
    base = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?"
            f"format=pdf&gid={ws.id}&range={rng}&gridlines=false"
            f"&sheetnames=false&printtitle=false&pagenumbers=false&fzr=false"
            f"&top_margin=0.05&bottom_margin=0.05"
            f"&left_margin=0.05&right_margin=0.05")

    def _fetch(extra):
        for attempt in range(5):        # the export endpoint 429s when hammered
            r = requests.get(base + extra,
                             headers={"Authorization": f"Bearer {token}"},
                             timeout=90)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.content
        raise RuntimeError(f"export {rng}: throttled (429) after retries")

    dpi = 200
    doc = fitz.open(stream=_fetch("&portrait=false&fitw=true"), filetype="pdf")
    if doc.page_count > 1:              # tall list — refit so it stays one page
        doc = fitz.open(stream=_fetch("&portrait=true&scale=4"), filetype="pdf")
        dpi = 320

    def _trim(im):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bb = ImageChops.difference(im, bg).getbbox()
        if not bb:
            return im
        pad = 6
        return im.crop((max(0, bb[0] - pad), max(0, bb[1] - pad),
                        min(im.width, bb[2] + pad), min(im.height, bb[3] + pad)))

    pages = []
    for pg in doc:
        pm = pg.get_pixmap(dpi=dpi)
        pages.append(_trim(Image.open(io.BytesIO(pm.tobytes("png")))
                           .convert("RGB")))
    if len(pages) == 1:
        img = pages[0]
    else:
        w = max(p.width for p in pages)
        img = Image.new("RGB", (w, sum(p.height for p in pages)), (255, 255, 255))
        y = 0
        for p in pages:
            img.paste(p, (0, y))
            y += p.height
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def render_report(ws, out_path: Path, helper_first_col: str = None,
                  rep_col: str = None, log=print) -> Path:
    """The whole report as ONE image: churn block + the per-rep list.

    ONE range covers both: the PDF export omits columns hidden on the tab, so
    the helper block drops out of the middle by itself and the rep list lands
    right next to the churn block. That only holds while those columns are
    actually hidden — a freshly duplicated tab does NOT inherit the hidden
    state, so fill.hide_helper_columns() runs before this. Both the helper
    and rep-list columns are derived, never assumed.
    """
    reps_rng = _rep_range(ws, rep_col)
    main_rng = visible_range(ws, helper_first_col)
    if reps_rng is None:
        log("  ⚠ no per-rep list found — screenshot is the churn block only")
        return render(ws, out_path, main_rng)

    last_row = max(_range_rows(main_rng) or 0, _range_rows(reps_rng) or 0)
    last_col = reps_rng.split(":")[1].rstrip("0123456789")
    return render(ws, out_path, f"A1:{last_col}{last_row}")


def _range_rows(rng: str):
    """Row count spanned by an A1 range like 'A1:Q24' → 24."""
    import re
    m = re.match(r"^[A-Z]+(\d+):[A-Z]+(\d+)$", str(rng or ""))
    return (int(m.group(2)) - int(m.group(1)) + 1) if m else None


def _rep_range(ws, rep_col: str = None):
    """A1 range of the per-rep list, or None when it hasn't been written.

    Column derived from the helper block by default — a constant goes stale
    the moment a column is inserted or removed.
    """
    from automations.vantura_churn import fill
    if rep_col is None:
        rep_col = fill._colletter(fill.rep_list_col(ws))
    c0 = fill._col_idx(rep_col)
    # Bound to the actual content, not a fixed width — the list dropped from
    # 3 columns to 2 (0-30 only) on 2026-07-20, so scan a small window and
    # stop at the last column/row that holds anything.
    vals = ws.get(f"{rep_col}1:{fill._colletter(c0 + 3)}{ws.row_count}")
    first_row = last_row = last_col_i = 0
    for i, row in enumerate(vals, start=1):
        for j, c in enumerate(row):
            if str(c).strip():
                if not first_row:
                    first_row = i
                last_row = i
                last_col_i = max(last_col_i, c0 + j)
    # Start at the first populated row, not row 1 — the list is anchored well
    # below the top of the sheet, and starting at 1 would frame ~14 blank rows.
    if not first_row or last_row <= first_row:
        return None
    return (f"{rep_col}{first_row}:"
            f"{fill._colletter(last_col_i)}{last_row}")


# The two images, in post order. `title` is both the Slack file title and the
# uploaded filename (Slack HTML-escapes the caption on read, so the caption
# carries the emoji + bold; the filename stays plain ASCII-friendly).
# Distinct emojis from the B2B Quality report's own 'Churn Rate' / 'Activation
# Rate' lines (Megan 2026-07-20), so each thread item reads uniquely. `code`
# is the Slack shortcode — Slack returns emoji as shortcodes on read, so the
# header sync writes/compares that form to stay idempotent.
POST_IMAGES = [
    {"key": "churn", "emoji": "🐺", "code": "wolf",
     "title": "Churn & Activations Board",
     "range": lambda ws: visible_range(ws)},
    {"key": "reps", "emoji": "📈", "code": "chart_with_upwards_trend",
     "title": "Activation Rate by Rep",
     "range": lambda ws: _rep_range(ws)},
]


def post_report(ws, day: dt.date | None = None, dry_run: bool = True,
                thread_ts: str | None = None, log=print) -> dict:
    """Render the churn overview + rep breakdown and reply them into that
    day's 'B2B Quality & Bonus' thread — the same thread the B2B Quality
    report posts to (#alphalete-gp-sales), as Lucy.

    Runs on Lucy 2, so the post carries the Lucy identity (this machine's
    Slack token decides who it's from — a manual run from a laptop posts as
    that laptop's user). dry_run=True resolves + renders + reports the target
    without sending. Skips any image already in the thread, so a re-run
    doesn't duplicate. Does NOT create the parent — if the B2B Quality thread
    doesn't exist yet, it logs and skips rather than opening a rival thread.

    Finds the thread via B2B Quality's shared thread-state file (no Slack scope
    needed), falling back to the history read; that read fails on Lucy's token,
    so relying on it alone would make this skip on a cold morning.
    """
    from automations.b2b_quality import run as bq
    from automations.shared import slack_metrics_post as smp

    day = day or dt.date.today()
    tag = f"{day.month}.{day.day}"
    out_dir = Path("output/vantura_churn")

    # Render both to clean, dated filenames.
    imgs = []
    for spec in POST_IMAGES:
        rng = spec["range"](ws)
        if rng is None:
            log(f"  ⚠ {spec['key']}: nothing to render — skipping")
            continue
        fname = f"{spec['title']} {tag}.png"
        path = render(ws, out_dir / fname, rng)
        imgs.append((spec, path))

    client = smp._client()
    cid = bq.CHANNEL[1]
    # Resolve the thread the SAME way B2B Quality does: the shared thread-state
    # file first, the Slack history read only as a backstop. find_thread_ts()
    # alone is unreliable here — Lucy's token can't read this channel's history,
    # so on a cold morning it returns None even though the thread exists, and we
    # would silently skip posting. B2B Quality writes thread_state.json when it
    # opens the parent, so that ts is authoritative and needs no Slack scope.
    ts = (thread_ts
          or bq._load_state(day, cid).get("thread_ts")
          or bq.find_thread_ts(client, cid, day))
    if not ts:
        log(f"  ⚠ no '{bq.THREAD_TITLE}' thread for {day} yet — churn "
            "screenshots not posted (the B2B Quality report opens that "
            "thread; this only replies into it).")
        return {"posted": [], "thread_ts": None, "reason": "no thread"}

    if dry_run:
        log(f"[dry-run] would reply {len(imgs)} image(s) into "
            f"{bq.CHANNEL[0]} thread {ts}:")
        for spec, path in imgs:
            log(f"           {spec['emoji']} {spec['title']} {tag}  "
                f"({path.name}, {path.stat().st_size:,} bytes)")
        _update_parent_header(client, cid, ts, imgs, dry_run=True, log=log)
        return {"dry_run": True, "thread_ts": ts,
                "images": [p.name for _s, p in imgs]}

    posted = []
    for spec, path in imgs:
        plain = f"{spec['title']} {tag}"
        if bq._already_replied(client, cid, ts, plain):
            log(f"  · {plain} already in thread — skipping")
            continue
        client.files_upload_v2(
            channel=cid, thread_ts=ts, file=str(path),
            filename=f"{plain}.png", title=plain,
            initial_comment=f"{spec['emoji']} *{plain}*")
        posted.append(plain)
        log(f"  ✓ posted '{plain}' to {bq.CHANNEL[0]} thread")
    _update_parent_header(client, cid, ts, imgs, dry_run=False, log=log)
    return {"posted": posted, "thread_ts": ts}


def _update_parent_header(client, cid, ts, imgs, dry_run, log) -> None:
    """Make the thread's parent header list the churn screenshots too.

    The B2B Quality report writes the parent (Tiered Bonus / Activation Rate
    / Churn Rate); these two images are added by a different report, so the
    header doesn't mention them unless we append. Idempotent — only adds a
    line that isn't already there. Only the message's author (Lucy, on Lucy
    2) can edit it, so this is best-effort and a no-op from a laptop.
    """
    try:
        msgs = client.conversations_replies(
            channel=cid, ts=ts, limit=1).get("messages", [])
    except Exception as e:  # noqa: BLE001
        log(f"  ⚠ header not updated (couldn't read parent): {e}")
        return
    if not msgs:
        return
    lines = html.unescape(msgs[0].get("text") or "").split("\n")
    changed = []
    for spec, _p in imgs:
        # Write the shortcode form — Slack returns emoji as shortcodes on
        # read, so this is what a later run sees, keeping the check stable.
        want = f":{spec['code']}: {spec['title']}"
        ok = {want, f"{spec['emoji']} {spec['title']}"}
        idx = next((i for i, ln in enumerate(lines)
                    if spec["title"] in ln), None)
        if idx is None:                       # not listed yet → append
            lines.append(want)
            changed.append(f"+{spec['title']}")
        elif lines[idx] not in ok:            # listed with a different emoji
            lines[idx] = want
            changed.append(f"~{spec['title']}")
    if not changed:
        log("  · header already current")
        return
    if dry_run:
        log(f"[dry-run] would update header ({', '.join(changed)})")
        return
    try:
        client.chat_update(channel=cid, ts=ts, text="\n".join(lines))
        log(f"  ✓ header updated ({', '.join(changed)})")
    except Exception as e:  # noqa: BLE001 — laptop token can't edit Lucy's msg
        log(f"  ⚠ header not updated ({type(e).__name__}: "
            f"{str(e)[:60]}) — only Lucy 2 can edit its own message")
