"""Rep Gap Alerts -- "Reps Over 15 Min Gap", texted every 10 minutes.

    python -m automations.gap_alerts.run                      # PREVIEW (renders,
                                                              # resolves, sends nothing)
    python -m automations.gap_alerts.run --send               # text the group
    python -m automations.gap_alerts.run --force --only rafael
    python -m automations.gap_alerts.run --probe              # dump the raw rows

WHAT IT IS. Carlos has had this card since July as the bottom panel of the
hourly B2B Dispositions post. Raf wants the same signal for his office, on its
own, faster: JUST the gap card, straight into the "Alphalete Partners" iMessage
group, every ten minutes of the selling day. No Today's Activity panel, no Slack
post, no thread. (It shipped at five minutes on 2026-08-26; Raf moved it to ten
the next day -- the cadence lives in config.TICK_MINUTES.)

WHY IT RUNS ON LUCY 1. Because that is where iMessage is set up (Megan). Lucy 1
is the busiest runner, but the group only exists in ITS Messages -- Megan added
alphaletereporting@ to the Partners chat on 8/26, which is what put the room on
that machine at all. Same reason alphalete_sales_board lives there.

THE LOAD IS FENCED, the same four ways the sales-board sweep is:
  1. its OWN browser profile (uploaded/.browser_profile_gap_alerts) so it can never
     collide with the .browser_profile the 4am batch holds;
  2. headless, and one page load per tick -- the card comes from a JSON
     endpoint, not a screenshot, so there is no rendering to wait on;
  3. it only runs inside the knocking window -- Mon-Fri 1:30pm-8:30pm,
     Saturday 10:00am-5:00pm, Sunday not at all;
  4. a pid lock, so a slow tick is SKIPPED rather than stacked. At ~48 runs a
     day an overlapping-run bug becomes 96.

NEVER TEXTS AN EMPTY CARD. If nobody is over the threshold that is good news,
not news -- and a "no reps over 15 min gap" picture arriving all afternoon is
how a room learns to mute the alert that matters.
[[feedback_never_post_blank]]

Python 3.9-safe (Lucy runtime). Cross-platform except the iMessage leg, which
only runs under --send.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.b2b_dispositions import capture as cap
from automations.gap_alerts import config as C

HUB_CARD_ID = "gap-alerts"
HUB_CARD_NAME = "Rep Gap Alerts (15-min gaps -> Partners chat)"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "gap_alerts"

# One alert after this many consecutive failed ticks, then a cooldown. A live
# outage would otherwise post an incident every tick all afternoon, and three
# ticks is ~30 minutes -- long enough to be a real outage and short enough that
# a dead ownerville session is caught the same hour.
FAIL_STREAK = 3
ALERT_COOLDOWN_HOURS = 2
FAIL_PATH = Path.home() / ".config" / "recruiting-report" / "gap_alerts_fails.json"
CORRECTIONS_CHANNEL = "C0BK5PRG259"  # #claudecorrections-and-requests


def _log(msg: str) -> None:
    print("[gap-alerts] %s" % msg, flush=True)


# --- singleton lock ----------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


class Lock:
    """Skip this tick if the last one is still going. Waiting would just queue
    behind the next tick; there is another one in ten minutes."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or C.LOCK_PATH
        self.held = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                pid = int(self.path.read_text().strip() or 0)
            except (ValueError, OSError):
                pid = 0
            if pid and _pid_alive(pid):
                return self
            try:
                self.path.unlink()
            except OSError:
                pass
        self.path.write_text(str(os.getpid()))
        self.held = True
        return self

    def __exit__(self, *exc):
        if self.held:
            try:
                self.path.unlink()
            except OSError:
                pass


# --- state (hub pill only; the card itself is stateless) ---------------------
def _state() -> Dict:
    try:
        return json.loads(C.STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(data: Dict) -> None:
    C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = C.STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    tmp.replace(C.STATE_PATH)


def _sent_too_recently(key: str):
    """Minutes since this office's last SENT card, or None if that was long
    enough ago (or never). See config.MIN_SEND_GAP_MINUTES for why."""
    stamp = (_state().get("_last_sent") or {}).get(key)
    if not stamp:
        return None
    try:
        age = (dt.datetime.now()
               - dt.datetime.fromisoformat(stamp)).total_seconds() / 60.0
    except ValueError:
        return None
    # A clock that went backwards (DST, an NTP correction) must not wedge the
    # alert shut for an hour — treat a negative age as "long enough ago".
    if age < 0 or age >= C.MIN_SEND_GAP_MINUTES:
        return None
    return age


def _mark_sent(key: str) -> None:
    data = _state()
    data.setdefault("_last_sent", {})[key] = dt.datetime.now().isoformat(
        timespec="seconds")
    _save_state(data)


def _previous_gap_names(key: str, day: dt.date):
    """(names, is_first_list_of_the_day).

    DAY-SCOPED on purpose. Two different bugs live here otherwise:
      * carrying yesterday's names into today would suppress the clock on
        someone who is dark again this morning — exactly the person to text;
      * treating the day's FIRST list as all-new marks all twenty at once,
        which is not a signal. The first list is the baseline; from then on the
        clock means what Raf asked it to mean, "this one just appeared".
    """
    rec = (_state().get("_gap_names") or {}).get(key) or {}
    if rec.get("day") != day.isoformat():
        return set(), True
    return set(rec.get("names") or []), False


def _remember_gap_names(key: str, day: dt.date, names) -> None:
    """Recorded only on a SEND. If a skipped tick updated this, the people who
    joined the list while we were quiet would never be marked."""
    data = _state()
    data.setdefault("_gap_names", {})[key] = {"day": day.isoformat(),
                                              "names": sorted(names)}
    _save_state(data)


def gap_text(gaps: List[Dict], previous: set, first_of_day: bool = False):
    """The message Raf asked for, and the set of names on it.

    ALPHABETICAL by name — his example listing is alphabetical, and the point
    is no longer "who is worst" (the ordering) but "who just appeared" (the
    emoji). Returns (text, names); text is "" when nobody is over, so a quiet
    stretch sends no list at all rather than a header with nothing under it.
    """
    lines, names = [], []
    for r in sorted(gaps, key=lambda r: (r.get("name") or "").strip().lower()):
        name = (r.get("name") or "").strip()
        if not name:
            continue
        names.append(name)
        mins = cap._int(r.get("minutesSinceLastKnock"))
        new = not first_of_day and name not in previous
        mark = (" " + C.GAP_NEW_EMOJI) if new else ""
        lines.append("%s - %d minutes%s" % (name, mins, mark))
    if not lines:
        return "", []
    return C.GAP_TEXT_HEADER + "\n\n" + "\n".join(lines), names


def _publish_hub_once(day: dt.date) -> None:
    """The first good tick of the day paints the card; every later tick stays
    quiet. A green pill repainted all afternoon would say nothing.
    [[feedback_launchd_reports_must_publish]]"""
    data = _state()
    key = day.isoformat()
    if (data.get("_hub") or {}).get(key):
        return
    try:
        from automations.shared import hub_activity
        hub_activity.log_completed(HUB_CARD_ID, HUB_CARD_NAME, status="success")
        data.setdefault("_hub", {})[key] = True
        _save_state(data)
    except Exception as e:  # noqa: BLE001 — the Hub row must never fail a tick
        _log("hub publish skipped: %s: %s" % (type(e).__name__, str(e)[:120]))


# --- failure streak ----------------------------------------------------------
def _fails() -> Dict:
    try:
        return json.loads(FAIL_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _write_fails(data: Dict) -> None:
    try:
        FAIL_PATH.parent.mkdir(parents=True, exist_ok=True)
        FAIL_PATH.write_text(json.dumps(data, indent=1))
    except OSError:
        pass


def _record_failure(err: str, *, dry_run: bool) -> None:
    """Count it, and speak once the streak says this is not a blip.

    A five-minute job that dies quietly is the worst kind: the room simply
    stops getting cards and reads that as "nobody has a gap".
    """
    data = _fails()
    data["streak"] = int(data.get("streak", 0)) + 1
    data["last_error"] = err[:400]
    data["last_at"] = dt.datetime.now().isoformat(timespec="seconds")
    streak = data["streak"]
    _log("failure #%d: %s" % (streak, err[:200]))

    should_alert = streak >= FAIL_STREAK
    last_alert = data.get("alerted_at")
    if should_alert and last_alert:
        try:
            age = (dt.datetime.now()
                   - dt.datetime.fromisoformat(last_alert)).total_seconds() / 3600.0
            if age < ALERT_COOLDOWN_HOURS:
                should_alert = False
        except ValueError:
            pass

    if should_alert and not dry_run:
        try:
            # One emoji-free line in the channel, the detail in the thread —
            # the house format for #claudecorrections.
            from automations.shared import slack_metrics_post as smp
            client = smp._client()
            resp = client.chat_postMessage(
                channel=CORRECTIONS_CHANNEL,
                text=("Rep Gap Alerts has failed %d ticks in a row — the "
                      "Partners chat is not getting gap cards." % streak))
            client.chat_postMessage(
                channel=CORRECTIONS_CHANNEL, thread_ts=resp["ts"],
                text=("```\n%s\n```\nRe-run once the cause is clear:\n"
                      "`lucy rerun gap_alerts`" % err[:1500]))
            data["alerted_at"] = dt.datetime.now().isoformat(timespec="seconds")
        except Exception as e:  # noqa: BLE001 — an alert must never crash a tick
            _log("alert failed: %s: %s" % (type(e).__name__, str(e)[:120]))

    _write_fails(data)


def _clear_failures() -> None:
    data = _fails()
    if data.get("streak"):
        _log("recovered after %d failed tick(s)" % data["streak"])
        _write_fails({"streak": 0,
                      "recovered_at": dt.datetime.now().isoformat(timespec="seconds")})


# --- the pull ----------------------------------------------------------------
def _pin_campaign(page, rqst: str, campaign_id: str) -> None:
    """Sticky-campaign guard. TeleMapper pages are scoped to whatever campaign
    the session last had selected -- by ANY job on this box -- so every tick
    re-pins it. Best-effort, same as the knocks and WKD pulls."""
    if not campaign_id:
        return
    try:
        page.goto("https://v2.ownerville.com/index.cfm?p=%d&rqst=%s"
                  "&invD2DClientId=%s" % (C.PAGE_TIME_TRACKER, rqst, campaign_id),
                  wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(800)
    except Exception as e:  # noqa: BLE001
        _log("  campaign pin failed (%s) — continuing on the session's current "
             "campaign" % type(e).__name__)


def titled(src: Path, title: str, out: Path) -> Path:
    """Prepend a title bar whose text actually FITS the image.

    cap.add_title_header draws at a fixed 30px and never measures, so on a
    narrow panel the title runs off the right edge — Raf's PDF showed
    "TODAY'S ACTIVITY — 6" with the time sliced off (Megan, 2026-08-27). Here
    the font steps down until the text fits, and the bar grows or shrinks with
    it, so the header scales to the panel instead of the panel having to be
    wide enough for the header.
    """
    from PIL import Image, ImageDraw
    im = Image.open(src).convert("RGB")
    W = im.width
    pad = max(12, W // 60)
    size = max(11, min(34, W // 22))
    f = cap._stitch_font(size)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    while size > 11:
        f = cap._stitch_font(size)
        if probe.textlength(title, font=f) <= W - pad * 2:
            break
        size -= 1
    bar = int(size * 1.9)
    canvas = Image.new("RGB", (W, bar + 8 + im.height), (255, 255, 255))
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, 0, W, bar], fill=(32, 41, 57))
    d.text((pad, (bar - size) // 2 - 2), title, font=f, fill=(255, 255, 255))
    canvas.paste(im, (0, bar + 8))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out


def _blank_rows(im, margin: int = 6):
    """y -> True where a horizontal scanline is entirely background.

    Both panels draw their rows as light boxes separated by a band of near-white
    page. Those bands are the only safe place to cut, so find them by asking a
    much simpler question than "where are the rows": is this whole scanline
    light? Ignores a few pixels at each edge, where a panel border runs the full
    height and would otherwise make every line look non-blank.
    """
    g = im.convert("L")
    w, h = g.size
    px = g.load()
    x0, x1 = margin, max(margin + 1, w - margin)
    step = max(1, (x1 - x0) // 160)          # sample, don't read every pixel
    xs = list(range(x0, x1, step))
    # A FRACTION, not "every pixel is light". The real OwnerVille panel has a
    # container border and a scrollbar track running its full height, so an
    # all-or-nothing test finds NO blank row anywhere and every cut falls back
    # to a hard slice — which is exactly the severed-and-repeated row Raf saw.
    # Allowing a couple of dark samples ignores those verticals while still
    # rejecting any line that touches a name, a time or a count pill.
    allow = max(1, len(xs) // 50)            # ~2% of the width may be dark
    out = bytearray(h)
    for y in range(h):
        dark = 0
        for x in xs:
            if px[x, y] < 232:               # text, border, avatar or pill
                dark += 1
                if dark > allow:
                    break
        out[y] = 1 if dark <= allow else 0
    return out


def _bands(blank, lo: int, hi: int):
    """[(top, bottom, thickness)] for every run of blank scanlines in [lo, hi)."""
    out, y = [], max(0, lo)
    hi = min(hi, len(blank))
    while y < hi:
        if blank[y]:
            top = y
            while y + 1 < hi and blank[y + 1]:
                y += 1
            out.append((top, y, y - top + 1))
        y += 1
    return out


def _cut_at_row_boundary(blank, target: int, reach: int):
    """Cut through the THICKEST blank band at or above `target`.

    Thickest, not nearest, and that distinction is the whole fix. A row is not
    solid: there is white space above and below the text INSIDE each row too,
    so "nearest blank line" happily cuts through the middle of a rep and leaves
    a half-drawn row — which is what Raf saw. The gap BETWEEN two rows is the
    thickest blank run in any neighbourhood, so picking by thickness lands
    between reps instead of inside one.

    Returns (y, thickness); thickness 0 means nothing usable was found and the
    caller should fall back to a hard cut.
    """
    bands = _bands(blank, target - reach, target + 1)
    if not bands:
        return target, 0
    top, bottom, thick = max(bands, key=lambda b: (b[2], b[0]))
    return (top + bottom) // 2, thick


def _pages_for(im, max_aspect: float, overlap: int = 0):
    """Slice one tall panel into page-sized pieces, cutting BETWEEN rows.

    The first version cut at a fixed height and overlapped the pieces so a
    severed row still appeared whole on the next page. It worked, and it looked
    broken: Raf's PDF showed a half-drawn "Rep 13" dangling off one page and
    the same rep repeated at the top of the next (Megan, 2026-08-27).

    So the cut now snaps UP to the gap between two rows, and there is no
    overlap at all — nothing is severed, so nothing needs repeating.
    """
    if im.height <= im.width * max_aspect:
        return [im]
    page_h = int(im.width * max_aspect)
    blank = _blank_rows(im)
    reach = max(40, page_h // 3)     # how far up we will hunt for a clean gap
    out, top, cuts = [], 0, []
    while top < im.height:
        if top + page_h >= im.height:
            out.append(im.crop((0, top, im.width, im.height)))
            break
        cut, thick = _cut_at_row_boundary(blank, top + page_h, reach)
        if cut <= top + 20:          # nothing usable — hard cut, ugly but safe
            cut, thick = top + page_h, 0
        cuts.append(thick)
        out.append(im.crop((0, top, im.width, cut)))
        top = cut
    if cuts:
        # Visible in the run log so a bad split can be diagnosed without
        # fetching the PNG off the runner. A 0 means that page break had to be
        # cut blind, which is the only way a row gets severed now.
        _log("  sliced into %d page(s); gap found at each break: %s px"
             % (len(out), ", ".join(str(c) for c in cuts)))
    return out


def to_pdf(panel_paths, out_pdf: Path) -> Path:
    """Turn the panels into a multi-page PDF, one panel after another.

    WHY A PDF AT ALL: Messages renders a tall narrow image inline as a sliver
    you cannot read (Raf, 2026-08-27). A PDF opens full-screen and zooms.

    WHY SLICED: a single 700x2900 page would open zoomed-to-fit and be just as
    unreadable — it would only move the squinting from Messages into Preview.

    TWO THINGS COPIED FROM owner_chat_texts.pdf_build, which has been sending
    Raf a tracker PDF every morning since 2026-08-23 — both learned the hard
    way there, and both would bite exactly the same way here:

    * **PyMuPDF, not PIL.** PIL's PDF writer re-encodes every page through its
      JPEG codec — lossy, on an image whose entire value is small text and
      colour-coded count badges — and not every Pillow build even carries that
      codec (Megan's laptop does not). fitz embeds the PNGs losslessly.
    * **EVERY page gets the SAME width.** PDF viewers pick one zoom for the
      whole document and fit the WIDEST page, so mixing the roster screenshot's
      width with the narrower gap card would shrink the gap card to a fraction
      of the screen. Raf's exact complaint about the other PDF was "pretty
      zoomed out"; this is what caused it.
    """
    import fitz
    from PIL import Image

    PAGE_W = 800.0
    tmp_dir = out_pdf.parent / "_pdf_pages"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    slices = []
    for i, p in enumerate(panel_paths):
        p = Path(p)
        if not p.exists():
            continue
        im = Image.open(p).convert("RGB")
        for j, piece in enumerate(_pages_for(im, C.PDF_MAX_ASPECT)):
            sp = tmp_dir / ("page_%02d_%02d.png" % (i, j))
            piece.save(sp)          # PNG all the way to fitz — never re-encoded
            slices.append(sp)
    if not slices:
        raise RuntimeError("no panels to put in the PDF")

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for sp in slices:
        pix = fitz.Pixmap(str(sp))
        page = doc.new_page(width=PAGE_W,
                            height=PAGE_W * pix.height / pix.width)
        page.insert_image(page.rect, pixmap=pix)
        pix = None
    doc.save(str(out_pdf), deflate=True)
    doc.close()
    return out_pdf


def gap_rows(cfg: Dict, day: dt.date) -> List[Dict]:
    """Reps over the gap threshold right now, longest-dark first.

    KEPT AS ITS OWN SECTION (Raf via Megan, 2026-08-28: the knocks board
    replaces the Today's Activity panel, "the bottom over 15 min gap" stays
    separate). It is not redundant with the board's Gaps columns: those are
    the day's CUMULATIVE gap totals, this is who is dark at this minute. One is
    a scorecard, the other is the alert, and merging them would lose the alert.

    Its own short ownerville session, because pull_board's session belongs to
    pull_offices_days and is already closed by the time we get here.
    """
    from automations.shared.tableau_patchright import ownerville_session
    with ownerville_session(headless=True, verbose=False,
                            profile_dir=C.PROFILE_DIR) as page:
        rqst = cap.capture_rqst(page)
        impersonated = False
        if cfg.get("ov") == "impersonate":
            # Dead for Raf (his login IS office 11280) and live the day a
            # second office is added. ALWAYS exited in the finally, or the next
            # office reads the previous one's numbers.
            from automations.focus_office_att.aliases import load_aliases
            from automations.focus_office_att.run_all_owners import (
                _exit_impersonation, _find_owner_and_impersonate,
                _navigate_to_office_access)
            _exit_impersonation(page)
            _navigate_to_office_access(page)
            rqst, reason = _find_owner_and_impersonate(page, cfg["name"],
                                                       load_aliases())
            if not rqst:
                raise RuntimeError("Couldn't impersonate %r: %s"
                                   % (cfg["name"], reason))
            impersonated = True
        try:
            _pin_campaign(page, rqst, cfg.get("campaign_id", ""))
            rows = cap.fetch_time_tracking(page, rqst,
                                           day.strftime("%m/%d/%Y"))
        finally:
            if impersonated:
                from automations.focus_office_att.run_all_owners import (
                    _exit_impersonation)
                _exit_impersonation(page)
    over = [r for r in rows
            if cap._int(r.get("minutesSinceLastKnock")) > C.GAP_THRESHOLD_MIN]
    over.sort(key=lambda r: -cap._int(r.get("minutesSinceLastKnock")))
    return over


def pull_board(cfg: Dict, day: dt.date, out_dir: Path):
    """Pull Raf's office for TODAY and render the knock board. -> (pngs, rows).

    This is the board Raf pointed at in his Loom (2026-08-28): the columns off
    OwnerVille's **Disposition by Rep** export — Total Knocks, Total Talk To's,
    First/Last Knock, Total Gaps, Avg Hrs Knocking, then the disposition
    breakdown — in the same colours as the daily board he already gets in
    Slack. No Rep ID column; he dropped it.

    NOTHING NEW IS SCRAPED OR DRAWN HERE. knocks_intraday already builds this
    exact board for the CURRENT day, so this calls the same pull and the same
    renderer. What is different is only the trigger (every 15 minutes) and the
    destination (the Alphalete Partners chat).

    The office is pulled through `pull_offices_days`, which checks
    `is_master_office` first: on Lucy 1 the login IS Raf's office, and
    impersonating yourself fails — that check is why this works for him and why
    the WKD probe never could.
    """
    from automations.rashad_metrics.knocks_pull import pull_offices_days
    from automations.total_knocks import render as knocks_render
    from automations.knocks_intraday.run import _date_text, first_name

    pulled = pull_offices_days([(cfg["name"], [day])], verbose=False,
                               profile_dir=str(C.PROFILE_DIR))
    _name, by_day, err = pulled[0]
    if err is not None:
        raise err
    rows = by_day.get(day) or []
    if not rows:
        return [], []

    pngs, shape = knocks_render.render_knocks_boards(
        day, rows=rows, out_dir=out_dir / cfg["key"],
        title_suffix=first_name(cfg.get("label") or cfg["name"]),
        date_text=_date_text(day))
    _log("  %s: %d rep(s) -> %s (%s)"
         % (cfg["key"], len(rows), ", ".join(p.name for p in pngs), shape))
    return list(pngs), rows


def render(cfg: Dict, pngs, out_dir: Path, slot: str) -> Path:
    """The board(s) as ONE PDF — the "flyer" half of the post.

    No gap card here any more: Raf replaced that picture with a plain text
    list (see gap_text). What is left is the knocks/disposition board, and it
    stays a PDF because it is WIDE — a dozen-plus columns, which Messages
    renders inline as an unreadable strip. A PDF opens full-screen and zooms.

    render_knocks_boards decides how many boards the row shape deserves: it
    folds Time Gaps into the main board when the columns already carry Gaps +
    Total Gaps, which Raf's TeleMapper shape does.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    who = (" — %s" % cfg["label"]) if cfg.get("label") else ""
    pages = []
    for i, p in enumerate(pngs):
        # Only the first board carries the clock — this is one post, and a time
        # stamped on every page reads like several separate sends.
        if i == 0:
            pages.append(titled(Path(p), "%s%s — %s" % (C.CARD_TITLE, who, slot),
                                out_dir / ("board_%s_0.png" % cfg["key"])))
        else:
            pages.append(Path(p))
    return to_pdf(pages, out_dir / ("gaps_%s.pdf" % cfg["key"]))


def tick(day: dt.date, *, send: bool, only: str = "",
         headless: bool = True) -> List[str]:
    """One pass. Returns the list of failures (empty = clean).

    No browser session is opened here any more: pull_board calls
    pull_offices_days, which owns its own ownerville session (and its own
    impersonation exit). Two sessions on one profile is the launch race that
    has cost other reports an office.
    """
    offices = [o for o in C.enabled()
               if not only or o["key"] in {k.strip().lower()
                                           for k in only.split(",")}]
    if not offices:
        return ["no office matched --only %r" % only]
    slot = C.slot_label()
    out_dir = OUTPUT_DIR / day.strftime("%Y-%m-%d")

    from automations.b2b_dispositions import text_post as tp

    failures = []
    seen_names = []
    for cfg in offices:
        # The guard runs BEFORE the pull. A skipped tick should cost nothing,
        # and this pull is the expensive half of the run.
        recent = _sent_too_recently(cfg["key"])
        if recent is not None and send:
            _log("%s: last board went out %.1f min ago — skipping this tick "
                 "(min gap %d min). The room already has this."
                 % (cfg["key"], recent, C.MIN_SEND_GAP_MINUTES))
            continue

        try:
            pngs, rows = pull_board(cfg, day, out_dir)
        except Exception as e:  # noqa: BLE001
            failures.append("%s: %s: %s" % (cfg["key"], type(e).__name__,
                                            str(e)[:200]))
            _log("%s PULL FAILED: %s: %s"
                 % (cfg["key"], type(e).__name__, str(e)[:200]))
            continue

        if not pngs:
            # Visible absence, never a blank board — the standing rule. Before
            # the field is out there are simply no rows, and that is not news.
            _log("%s: no rows yet at %s — nothing sent" % (cfg["key"], slot))
            continue

        seen_names += [str(r.get("Rep") or r.get("rep") or "").strip()
                       for r in rows]
        # A failed gap pull costs the section, never the board — the board is
        # the thing Raf asked for and it is already in hand.
        try:
            gaps = gap_rows(cfg, day)
        except Exception as e:  # noqa: BLE001
            gaps = []
            _log("  gap list SKIPPED (%s: %s)"
                 % (type(e).__name__, str(e)[:160]))
        previous, first_of_day = _previous_gap_names(cfg["key"], day)
        body, gap_names = gap_text(gaps, previous, first_of_day)
        newly = ([] if first_of_day
                 else [n for n in gap_names if n not in previous])
        _log("  %d rep(s) over %d min, %d new%s"
             % (len(gap_names), C.GAP_THRESHOLD_MIN, len(newly),
                (" (" + ", ".join(newly) + ")") if newly else ""))
        pdf = render(cfg, pngs, out_dir, slot)
        try:
            # Resolution runs on a dry run too — it is read-only and it is the
            # half most likely to be wrong (Lucy removed from the chat, the
            # room renamed). A preview that skipped it would prove nothing.
            # ONE send: the gap list as the message text, the board as its
            # attachment. send_to_group posts the text first, so the names
            # arrive above the flyer.
            res = tp.send_to_group(cfg["group"], body, [pdf], dry_run=not send)
            _log("  %s -> %r (%s participants)%s"
                 % ("TEXT" if send else "PREVIEW", res.get("resolved_name"),
                    res.get("participants"), "" if send else " — nothing sent"))
            if send:
                # Both stamped only after Messages actually took it: a failed
                # send must not block the next retry, and must not consume the
                # "new" marks — those people would then never be flagged.
                _mark_sent(cfg["key"])
                _remember_gap_names(cfg["key"], day, gap_names)
        except Exception as e:  # noqa: BLE001
            failures.append("%s text: %s: %s" % (cfg["key"], type(e).__name__,
                                                 str(e)[:200]))
            _log("  TEXT FAILED: %s: %s" % (type(e).__name__, str(e)[:200]))
    _terminated_check_once(day, seen_names)
    return failures


def _terminated_check_once(day: dt.date, names: List[str]) -> None:
    """Flag anyone on the card who is on the 'Terminated ICDs' tab — ONCE a day,
    not on every tick. Advisory only: it never fails a tick, and it never
    changes what the card says.
    [[feedback_terminated_icd_check]]"""
    names = [n for n in dict.fromkeys(names) if n]
    if not names:
        return
    data = _state()
    key = day.isoformat()
    if (data.get("_terminated") or {}).get(key):
        return
    try:
        from automations.shared import terminated_icds as ti
        ti.alert_terminated(names, report_label="Rep Gap Alerts")
        data.setdefault("_terminated", {})[key] = True
        _save_state(data)
    except Exception as e:  # noqa: BLE001 — advisory, never fatal
        _log("terminated check skipped: %s: %s" % (type(e).__name__, str(e)[:120]))


def probe(day: dt.date, cfg: Dict, headless: bool = True) -> int:
    """READ-ONLY: the rows the board is built from, and their columns.

    Points at the SAME pull the post uses, deliberately. A probe that reads a
    different source can agree with itself while the board is wrong.
    """
    from automations.rashad_metrics.knocks_pull import pull_offices_days
    pulled = pull_offices_days([(cfg["name"], [day])], verbose=True,
                               profile_dir=str(C.PROFILE_DIR))
    _name, by_day, err = pulled[0]
    if err is not None:
        _log("PULL FAILED: %s: %s" % (type(err).__name__, str(err)[:300]))
        return 1
    rows = by_day.get(day) or []
    _log("office=%s day=%s rows=%d" % (cfg["key"], day, len(rows)))
    if rows:
        _log("columns=%s" % sorted(rows[0].keys()))
    for r in rows[:25]:
        _log("  %s" % {k: v for k, v in list(r.items())[:8]})
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--send", action="store_true",
                    help="text the group (default: render + resolve only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit preview (the default; here for the house flag)")
    ap.add_argument("--only", default="",
                    help="comma-separated office keys (default: all enabled)")
    ap.add_argument("--date", help="YYYY-MM-DD (default today)")
    ap.add_argument("--force", action="store_true",
                    help="run outside the selling-day window")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument("--probe", action="store_true",
                    help="READ-ONLY: dump the raw Time Tracker rows")
    args = ap.parse_args(argv)

    day = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
           if args.date else dt.date.today())
    send = args.send and not args.dry_run

    if args.probe:
        # Ahead of the window gate on purpose: you diagnose when you can, not
        # only between noon and 8.
        cfg = C.office(args.only) if args.only else C.enabled()[0]
        if not cfg:
            _log("no office %r" % args.only)
            return 1
        return probe(day, cfg, headless=not args.headed)

    if not args.force and not C.in_selling_window():
        _log("outside today's window (%s) — nothing to do" % C.window_label())
        return 0

    with Lock() as lock:
        if not lock.held:
            _log("another tick is still running — skipping this one")
            return 0
        failures = tick(day, send=send, only=args.only,
                        headless=not args.headed)

    if failures:
        _record_failure("; ".join(failures), dry_run=not send)
        _log("=== done (%d failure(s)) ===" % len(failures))
        return 1

    _clear_failures()
    if send:
        _publish_hub_once(day)
    _log("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
