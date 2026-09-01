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
PREVIEW_DM = False   # set by --preview-dm
RATES_OVERRIDE = None  # set by --rates: force the rate columns on for ONE run

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


def gap_header(cfg: Dict) -> str:
    """"15 minutes of gaps — Jay — AT&T".

    THREE reports share the ENERGY WELLS DOMINATION chat — Calvin's Energy
    Wells, Jay's Energy Wells and Jay's AT&T — and a bare "15 minutes of gaps"
    gave no way to tell whose names were on it (Megan 2026-08-30: "since it's 2
    ICDs can it read ... so we know who is who"). Office then campaign, matching
    how she wrote it.

    Raf sets neither field: his chat carries only his office, so naming it there
    would be noise.
    """
    bits = [cfg.get("label"), cfg.get("campaign_label")]
    return C.GAP_TEXT_HEADER + "".join(" — %s" % b for b in bits if b)


def gap_text(gaps: List[Dict], previous: set, first_of_day: bool = False,
             header: str = ""):
    """The message Raf asked for, and the set of names on it.

    LONGEST GAP FIRST (Megan, 2026-08-28). Raf's Loom listed his mock-up
    alphabetically, but read back it is a to-text list and the person who has
    been dark 190 minutes belongs at the top, not under everyone whose name
    starts with A. The clock still marks who just appeared; the ordering says
    who is worst. Ties break alphabetically so the list is stable between
    ticks and does not shuffle for no reason.

    Returns (text, names); text is "" when nobody is over, so a quiet stretch
    sends no list at all rather than a header with nothing under it.
    """
    lines, names = [], []
    for r in sorted(gaps, key=lambda r: (-cap._int(r.get("minutesSinceLastKnock")),
                                         (r.get("name") or "").strip().lower())):
        name = (r.get("name") or "").strip()
        if not name:
            continue
        names.append(name)
        mins = cap._int(r.get("minutesSinceLastKnock"))
        new = not first_of_day and name not in previous
        mark = (" " + C.GAP_NEW_EMOJI) if new else ""
        # "min", not "minutes" (Megan 2026-08-31: "so it's shorter on the
        # text") — twenty of these stack up on a phone.
        lines.append("%s - %d min%s" % (name, mins, mark))
    if not lines:
        return "", []
    return (header or C.GAP_TEXT_HEADER) + "\n\n" + "\n".join(lines), names


def _slack_due(key: str, now: dt.datetime) -> bool:
    """Has this office's board gone to Slack yet THIS clock hour?

    Keyed on the hour itself rather than "minutes since the last post", so the
    post lands on the first tick of each hour and cannot drift later and later
    across the day the way an elapsed-time check would.
    """
    stamp = (_state().get("_slack_hour") or {}).get(key)
    return stamp != now.strftime("%Y-%m-%dT%H")


def _mark_slack_sent(key: str, now: dt.datetime) -> None:
    data = _state()
    data.setdefault("_slack_hour", {})[key] = now.strftime("%Y-%m-%dT%H")
    _save_state(data)


def post_slack(cfg: Dict, png: Path, slot: str, day: dt.date,
               dry_run: bool = True) -> Dict:
    """Put the board in #alphalete-lvl1-chat, once an hour (Raf 2026-08-29).

    The board only — not the gap list. The gap list is a to-text list for the
    handful of people who chase reps; a channel of reps reading a leaderboard
    has no use for who is 20 minutes dark, and posting it would put every rep's
    quiet stretch in front of everyone.
    """
    who = cfg.get("label") or cfg["name"].split()[0]
    comment = ("*%s — %s*  ·  ranked by total knocks"
               % (C.CARD_TITLE.title(), slot))
    if dry_run:
        return {"dry_run": True, "channel": C.SLACK_HOURLY_CHANNEL,
                "comment": comment, "file": png.name}
    from automations.shared import slack_metrics_post as smp
    smp._client().files_upload_v2(
        file_uploads=[{"file": str(png), "filename": png.name}],
        channel=C.SLACK_HOURLY_CHANNEL, initial_comment=comment)
    return {"channel": C.SLACK_HOURLY_CHANNEL, "file": png.name, "ok": True}


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


def _date_text(day: dt.date) -> str:
    """'8/28 (Friday)' — the weekday spelled out (Megan, 2026-08-28).

    Not knocks_intraday's version, which is '8/28' and is shared by the Slack
    boards; this one is ours. Built by hand rather than with %-m/%-d, which is
    glibc/BSD only and throws on Windows — every report here has to import on
    both.
    """
    return "%d/%d (%s)" % (day.month, day.day, day.strftime("%A"))


def pull_board(cfg: Dict, day: dt.date, out_dir: Path,
               slot: str = ""):
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
    from automations.knocks_intraday.run import first_name

    # Chan's TOTAL rides the board as the teal comparison line (Raf,
    # 2026-08-28: "can we have it compare to chans every 15 minutes"). It is
    # the same line his Slack boards already carry, and it is pulled in the
    # SAME session as Raf — a comparison is a nicety and must never cost its
    # own login, which at four ticks an hour would be a real bill.
    from automations.knocks_intraday.run import compare_office
    compare = compare_office() if C.compares(cfg) else ""
    # The office's campaign travels WITH the job. Without this the pull falls
    # back to CAMPAIGN_OVERRIDES, which is keyed by office NAME and so holds
    # one campaign per office — no good for Jay Turnage, who knocks AT&T AND
    # Energy Wells and gets a separate report for each.
    jobs = [(cfg["name"], [day], cfg.get("campaign_id") or None)]
    if compare and compare.strip().lower() != cfg["name"].strip().lower():
        # The comparison office keeps its OWN campaign (Chan is fiber), so no
        # third element — the map decides for him.
        jobs.append((compare, [day]))

    pulled = pull_offices_days(jobs, verbose=False,
                               profile_dir=str(C.PROFILE_DIR))
    by_name = {name: (days, err) for name, days, err in pulled}
    by_day, err = by_name.get(cfg["name"], ({}, None))
    if err is not None:
        raise err
    rows = by_day.get(day) or []
    if not rows:
        return [], []

    # NO SORT HERE. Ranking is the RENDERER's job (sort_by="knocks" below):
    # _combined_sub re-orders whatever rows it is handed, so sorting them here
    # was thrown away and the board kept coming out alphabetical while this
    # code looked like it had already fixed it (2026-08-28 -> 29). One place
    # decides the order.

    # A failed comparison costs ONE LINE, never the board.
    extra = []
    if compare:
        chan_days, chan_err = by_name.get(compare, ({}, None))
        chan_rows = (chan_days or {}).get(day) or []
        if chan_err is not None:
            # The MESSAGE, not just the type. This line said "(RuntimeError)"
            # and nothing else, and the pull runs verbose=False so its own
            # detail never reached the log either — which left "Chan's numbers
            # are gone" undiagnosable twice over. An error we chose to swallow
            # still has to say why.
            _log("  ⚠ %s comparison pull failed (%s: %s) — board goes out "
                 "without the line"
                 % (compare, type(chan_err).__name__, str(chan_err)[:300]))
        elif chan_rows:
            extra.append((compare, chan_rows))
        else:
            _log("  no %s rows for %s — board goes out without the line"
                 % (compare, day))

    # ONE header, not two. The board draws its own title band, and gap_alerts
    # used to draw a second one above it saying almost the same thing —
    # "KNOCKS & DISPOSITIONS — EnergyWell — Calvin — 11:32 AM" stacked on
    # "TOTAL KNOCKS — CALVIN — 8/29 (Saturday)" (Megan 2026-08-30: "this has 2
    # redundant headers"). The campaign and the clock now go INTO the board's
    # title and the wrapper is gone.
    _who = " — ".join(x for x in (cfg.get("campaign_label"),
                                  first_name(cfg.get("label") or cfg["name"]))
                      if x)
    _when = _date_text(day) + (" — %s" % slot if slot else "")
    pngs, shape = knocks_render.render_knocks_boards(
        day, rows=rows, out_dir=out_dir / cfg["key"],
        title_suffix=_who, date_text=_when, extra_totals=extra,
        rate_columns=(C.RATE_COLUMNS if RATES_OVERRIDE is None
                      else RATES_OVERRIDE),
        knocks_green_at=C.KNOCKS_GREEN_AT, sort_by="knocks")

    _log("  %s: %d rep(s) -> %s (%s)"
         % (cfg["key"], len(rows), ", ".join(p.name for p in pngs), shape))
    return list(pngs), rows


def render(cfg: Dict, pngs, out_dir: Path, slot: str):
    """The boards, as they come. -> [paths]

    Nothing to add any more: the campaign, the office, the date and the clock
    are all in the board's own title band now, so the second header this used
    to draw was pure duplication.

    Images, not a PDF: a PDF arrives as a grey document tile you have to tap
    to see (Raf, 2026-08-27). The tall roster that once needed one is gone.
    """
    return [Path(p) for p in pngs]


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

    if send and not getattr(C, "SEND_ENABLED", True):
        _log("SENDING IS PAUSED (config.SEND_ENABLED=False) — building and "
             "reporting only. Flip it to True to resume.")
        send = False

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
            pngs, rows = pull_board(cfg, day, out_dir, slot)
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
        # A BACKDATED RUN GETS NO GAP LIST. "minutesSinceLastKnock" is measured
        # from RIGHT NOW, so for any past day every rep reads as inactive for a
        # thousand-plus minutes — a wall of red that says nothing except that
        # yesterday ended. The board is history and travels fine; the gap list
        # is a live signal and does not.
        if day != dt.date.today():
            gaps = []
            _log("  gap list SKIPPED — %s is not today, and 'minutes since "
                 "last knock' is only meaningful live" % day)
        else:
            try:
                gaps = gap_rows(cfg, day)
            except Exception as e:  # noqa: BLE001
                gaps = []
                _log("  gap list SKIPPED (%s: %s)"
                     % (type(e).__name__, str(e)[:160]))
        previous, first_of_day = _previous_gap_names(cfg["key"], day)
        body, gap_names = gap_text(gaps, previous, first_of_day,
                                   header=gap_header(cfg))
        newly = ([] if first_of_day
                 else [n for n in gap_names if n not in previous])
        _log("  %d rep(s) over %d min, %d new%s"
             % (len(gap_names), C.GAP_THRESHOLD_MIN, len(newly),
                (" (" + ", ".join(newly) + ")") if newly else ""))
        boards = render(cfg, pngs, out_dir, slot)
        if PREVIEW_DM:
            try:
                _log("  preview DM -> Megan: %s"
                     % preview_dm(boards[0], slot)["file"])
            except Exception as e:  # noqa: BLE001
                _log("  preview DM failed: %s: %s"
                     % (type(e).__name__, str(e)[:160]))
        try:
            # Resolution runs on a dry run too — it is read-only and it is the
            # half most likely to be wrong (Lucy removed from the chat, the
            # room renamed). A preview that skipped it would prove nothing.
            # ONE send: the gap list as the message text, the board as its
            # attachment. send_to_group posts the text first, so the names
            # arrive above the flyer.
            res = tp.send_to_group(cfg["group"], body, boards, dry_run=not send)
            _log("  %s -> %r (%s participants)%s"
                 % ("TEXT" if send else "PREVIEW", res.get("resolved_name"),
                    res.get("participants"), "" if send else " — nothing sent"))
            # The hourly Slack post rides the SAME board that was just
            # built — never its own pull. It is also independent of the text:
            # a Messages failure must not cost the channel its leaderboard,
            # and vice versa, so it sits in its own try.
            if cfg.get("slack_hourly") and boards:
                now = dt.datetime.now()
                if _slack_due(cfg["key"], now):
                    try:
                        res = post_slack(cfg, boards[0], slot, day,
                                         dry_run=not send)
                        _log("  %s -> %s (%s)"
                             % ("SLACK" if send else "SLACK (preview)",
                                res.get("channel"), res.get("file")))
                        if send:
                            _mark_slack_sent(cfg["key"], now)
                    except Exception as e:  # noqa: BLE001
                        _log("  SLACK FAILED: %s: %s"
                             % (type(e).__name__, str(e)[:200]))

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


def preview_dm(pdf: Path, slot: str, user: str = "U04G5HJBGFN") -> Dict:
    """DM the built PDF to Megan for review — the room gets nothing.

    Exists because there is no way to read a file off the runner from the
    laptop: ssh is refused and the control queue has no fetch action, so
    "let me see it before it posts" had no answer that did not involve
    posting it. Same files_upload_v2 path the b2b preview uses.
    """
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    uid = smp._resolve_user_id(client, user)
    channel = client.conversations_open(users=uid)["channel"]["id"]
    client.files_upload_v2(
        file_uploads=[{"file": str(pdf), "filename": pdf.name}],
        channel=channel,
        initial_comment="*[gap alerts preview]* %s — not sent to the room" % slot)
    return {"ok": True, "to": user, "file": pdf.name}


def probe_campaigns(headless: bool = True, office: str = "",
                    campaign: str = "") -> int:
    """READ-ONLY: list the campaigns this login can see, and dump the
    Disposition-by-Rep table's LIVE column headers for each.

    Both halves are needed before Energy Wells can be built, and neither can be
    guessed:

    * the campaign's `invD2DClientId` — the id is what pins a TeleMapper page;
    * its disposition COLUMNS. total_knocks scrapes a FIXED list
      (SHEET_COLUMNS) and RAISES if one is missing, so a campaign whose grid is
      shaped differently does not degrade, it fails. Raf says Energy Wells adds
      "VL" and counts it as a talk-to, which means at minimum a column the
      current scraper neither reads nor sums.

    `office` (optional): impersonate this owner first, for a campaign the
    master login cannot see on its own.
    """
    from automations.shared.tableau_patchright import ownerville_session
    from automations.total_knocks import pull as knocks

    with ownerville_session(headless=headless, verbose=False,
                            profile_dir=C.PROFILE_DIR) as page:
        rqst = cap.capture_rqst(page)
        if office:
            from automations.focus_office_att.aliases import load_aliases
            from automations.focus_office_att.run_all_owners import (
                _exit_impersonation, _find_owner_and_impersonate,
                _navigate_to_office_access)
            _exit_impersonation(page)
            _navigate_to_office_access(page)
            rqst, reason = _find_owner_and_impersonate(page, office,
                                                       load_aliases())
            if not rqst:
                # ANSWERED, not failed. A probe that cannot reach an owner has
                # told you the thing you asked it — and exiting non-zero makes
                # the run watcher open an incident against the LIVE 15-minute
                # report, which is posting perfectly (it did, 2026-08-28).
                # A read-only diagnostic must never page the corrections
                # channel about a report it did not touch.
                _log("ANSWER: %r is not reachable from this login — %s. "
                     "Either the name needs an ICD alias or the owner needs "
                     "Office Access provisioned." % (office, reason))
                return 0
            _log("impersonated %r" % office)

        # THE CAMPAIGN IS A STICKY SESSION-GLOBAL AND IMPERSONATION DOES NOT
        # RESET IT. This probe previously loaded p=89 with no campaign param
        # and reported "missing: nothing" — it was reading RES AT&T's grid
        # while impersonated as an Energy Wells owner, because that is what the
        # session happened to be pinned to. The headers it printed (close,
        # credit check, already has at&t, bill payer not home) are AT&T
        # dispositions; Energy Wells has Not Interested, Presentation and VL.
        # Always pass --campaign and read the campaign name off the page.
        try:
            _extra = ("&invD2DClientId=%s" % campaign) if campaign else ""
            cap._goto(page, "https://v2.ownerville.com/index.cfm?p=%d&rqst=%s%s"
                      % (C.PAGE_DISPOSITION, rqst, _extra))
            page.wait_for_timeout(3000)
            idx = knocks._header_index(page)
            # WHICH campaign is this actually? The page prints its name; the
            # probe must say it, or a header dump proves nothing about which
            # campaign produced it.
            try:
                onscreen = page.evaluate(
                    "() => { const t = (document.body.innerText || '');"
                    " const m = t.match(/RES-?[A-Z& ]{3,20}/); "
                    " return m ? m[0].trim() : ''; }")
            except Exception:  # noqa: BLE001
                onscreen = ""
            _log("campaign=%s onscreen=%r headers (%d): %s"
                 % (campaign or "(session default)", onscreen, len(idx),
                    ", ".join(sorted(idx))))
            missing = [c for c in knocks.SHEET_COLUMNS
                       if c not in {knocks.COL_TOTAL_TALK_TO,
                                    *knocks.TIME_TRACKER_COLUMNS}
                       and knocks._norm(c) not in idx]
            _log("scraper would %s — missing: %s"
                 % ("RAISE" if missing else "WORK AS-IS",
                    ", ".join(missing) if missing else "nothing"))
            # The columns this campaign HAS that the fiber scraper ignores.
            # Short list, and the one that matters: Raf says Energy Wells
            # counts "VL" as a talk-to, so if it is here it has to be added to
            # that campaign's talk-to sum — TALK_TO_PARTS is shared with every
            # fiber board and cannot simply be appended to.
            known = {knocks._norm(c) for c in knocks.SHEET_COLUMNS}
            extra = sorted(h for h in idx if h not in known)
            _log("EXTRA headers this campaign has (%d): %s"
                 % (len(extra), ", ".join(extra)))
        except Exception as e:  # noqa: BLE001
            _log("default headers unavailable (%s: %s)"
                 % (type(e).__name__, str(e)[:160]))

        # WHICH CAMPAIGN ID AM I ON? Calvin is Energy-Wells-only, so whatever
        # this session resolves to after impersonating him IS the Energy Wells
        # id — and that id is what JAY's Energy Wells report will have to pin,
        # because he runs two campaigns and has no safe default.
        #
        # Read off the page's own links rather than a dropdown: the campaign
        # picker is not a <select> here (the earlier dump found only territory,
        # table-length and feedbackModules), and every campaign-scoped link the
        # page builds carries the id.
        try:
            found = page.evaluate(
                "() => { const out = {};"
                " for (const a of document.querySelectorAll('a[href]')) {"
                "   const m = a.href.match(/invD2DClientId=(\\d+)/);"
                "   if (m) { out[m[1]] = (out[m[1]] || 0) + 1; } }"
                " return { ids: out, url: location.href }; }")
            _log("current url: %s" % str(found.get("url"))[:160])
            ids = found.get("ids") or {}
            _log("invD2DClientId seen in page links: %s"
                 % (", ".join("%s (x%s)" % (k, v) for k, v in ids.items())
                    or "none"))
        except Exception as e:  # noqa: BLE001
            _log("campaign-id scan failed (%s)" % type(e).__name__)

        # FIND THE CAMPAIGN PICKER BY ITS OWN TEXT, then click THAT.
        #
        # b2b's _open_campaign_dropdown grabs the first [data-toggle=dropdown]
        # on the page. On Raf's layout that is the NOTIFICATIONS BELL — proved
        # by dumping the menu's raw text and getting "You have 2 inventory
        # alerts | 10 devices are expiring this week". Every "the campaign list
        # is only RES AT&T and BASE Energy" reading came from the wrong menu.
        #
        # The picker is the top-right control whose label IS the current
        # campaign ("RES-ENERGYWELL" on Calvin's screen), so locate it by that
        # text, click it, and read what opens.
        try:
            found = page.evaluate(
                r"""() => {
                  const rx = /^\s*[★*]?\s*(RES[-\w &]*|BASE [-\w &]*|B2B[-\w &]*)\s*$/i;
                  const cands = [...document.querySelectorAll('a,button,span,div')]
                    .filter(e => rx.test((e.innerText || '').trim())
                                 && (e.innerText || '').trim().length < 30
                                 && e.offsetParent !== null);
                  if (!cands.length) return {clicked: false, label: ''};
                  // The SMALLEST match is the label itself, not a wrapper.
                  cands.sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);
                  const el = cands[0];
                  const label = (el.innerText || '').trim();
                  (el.closest('[data-toggle="dropdown"],a,button') || el).click();
                  const dd = el.closest('.dropdown,.btn-group,li,div');
                  if (dd) { dd.classList.add('open','show');
                            const m = dd.querySelector('.dropdown-menu');
                            if (m) { m.classList.add('show'); m.style.display='block'; } }
                  return {clicked: true, label};
                }""")
            _log("PICKER control: %s" % found)
            page.wait_for_timeout(2500)
            items = page.evaluate(
                r"""() => [...document.querySelectorAll('a,li,span,button')]
                     .filter(e => e.offsetParent !== null)
                     .map(e => {
                       const t = (e.innerText || '').replace(/\s+/g,' ').trim();
                       const blob = [e.getAttribute('href'), e.getAttribute('onclick'),
                                     e.getAttribute('data-id')].filter(Boolean).join(' ');
                       const m = blob.match(/invD2DClientId\D{0,3}(\d{1,6})/i);
                       return (t && t.length < 40 && m) ? (m[1] + ' = ' + t) : null;
                     }).filter(Boolean).slice(0, 30)""")
            for it in dict.fromkeys(items):
                _log("CAMPAIGN %s" % it)
            if not items:
                _log("CAMPAIGN: picker opened but no invD2DClientId items visible")
        except Exception as e:  # noqa: BLE001
            _log("picker click failed (%s: %s)" % (type(e).__name__, str(e)[:140]))

        # THE CAMPAIGN PICKER IS NOT A <select> AND NOT A PLAIN LINK. Calvin's
        # screen shows "RES-ENERGYWELL" in a custom dropdown top-right, so the
        # id exists — the earlier a[href] scan simply never saw it (it found 3
        # and 39, which turned out to be RES AT&T and a third campaign with
        # "bill pull"/"inaccessible no soliciting").
        #
        # So scan the WHOLE document for invD2DClientId — every attribute and
        # every inline script — and pair each id with the nearest readable
        # text. That is what turns an id into a NAME, which is the only way to
        # know we pinned Energy Wells and not something that merely returns
        # rows.
        try:
            pairs = page.evaluate(
                "() => { const out = [];"
                " for (const el of document.querySelectorAll('*')) {"
                "   for (const a of el.attributes || []) {"
                "     const m = String(a.value).match(/invD2DClientId=?[\"']?(\\d+)/);"
                "     if (m) { out.push([m[1], (el.innerText || el.textContent || '')"
                "        .replace(/\\s+/g,' ').trim().slice(0,40)]); } } }"
                " for (const sc of document.querySelectorAll('script')) {"
                "   const txt = sc.textContent || '';"
                "   const re = /invD2DClientId[=:\\s\"']+(\\d+)/g; let m;"
                "   while ((m = re.exec(txt))) { out.push([m[1], '(script)']); } }"
                " return out.slice(0, 60); }")
            seen = {}
            for cid, label in pairs:
                if cid not in seen or (label and label != "(script)"
                                       and seen[cid] == "(script)"):
                    seen[cid] = label
            for cid, label in sorted(seen.items(), key=lambda kv: int(kv[0])):
                _log("PICKER id=%-4s %s" % (cid, label or "(no text)"))
            if not seen:
                _log("PICKER: no invD2DClientId anywhere in the DOM")
        except Exception as e:  # noqa: BLE001
            _log("picker scan failed (%s: %s)" % (type(e).__name__, str(e)[:120]))

        # NAME each candidate id. Two ids in Calvin's links (3 and 39) is not
        # an answer: 3 is RES AT&T, so 39 is PROBABLY Energy Wells — and
        # "probably" is exactly what would hand Jay's Energy Wells report the
        # wrong campaign's numbers while looking perfectly normal. Load each id
        # and read the campaign the page says it is on.
        for cid in sorted((found.get("ids") or {})):
            try:
                cap._goto(page, "https://v2.ownerville.com/index.cfm?p=%d"
                                "&rqst=%s&invD2DClientId=%s"
                          % (C.PAGE_TODAYS_ACTIVITY, rqst, cid))
                page.wait_for_timeout(1800)
                head = page.evaluate(
                    "() => (document.body.innerText || '')"
                    "   .split('\\n').map(s => s.trim())"
                    "   .filter(s => s && s.length < 60).slice(0, 12)")
                _log("id=%s top-of-page: %s" % (cid, " | ".join(head)))
            except Exception as e:  # noqa: BLE001
                _log("id=%s label unavailable (%s)" % (cid, type(e).__name__))

        # Every <select> on the page, so the campaign picker (and its ids) can
        # be found without guessing at the B2B dropdown's shape — that reader
        # returned nothing on this login, which is why the first scan was blind.
        try:
            sels = page.evaluate(
                "() => [...document.querySelectorAll('select')].map(s => ({"
                " name: s.name || s.id || '', n: s.options.length,"
                " opts: [...s.options].slice(0, 12).map(o => "
                "   (o.value || '') + '=' + (o.textContent || '')"
                "     .replace(/\\s+/g, ' ').trim().slice(0, 40)) }))")
            for s in sels:
                if s["n"] and s["n"] < 40:
                    _log("select %r (%d): %s"
                         % (s["name"], s["n"], " | ".join(s["opts"])))
        except Exception as e:  # noqa: BLE001
            _log("select dump failed (%s)" % type(e).__name__)

        for cid in range(1, 0):   # id scan disabled — the dumps above answer it
            url = ("https://v2.ownerville.com/index.cfm?p=%d&rqst=%s"
                   "&invD2DClientId=%d" % (C.PAGE_TIME_TRACKER, rqst, cid))
            try:
                cap._goto(page, url)
                label, _cur = cap.current_campaign(page)
            except Exception as e:  # noqa: BLE001
                label = "(err %s)" % type(e).__name__
            if not label or label.startswith("(err"):
                continue
            _log("campaign id=%-3d %s" % (cid, label))
            # The grid's real headers for this campaign.
            try:
                cap._goto(page, "https://v2.ownerville.com/index.cfm?p=%d"
                                "&rqst=%s&invD2DClientId=%d"
                          % (C.PAGE_DISPOSITION, rqst, cid))
                page.wait_for_timeout(2500)
                idx = knocks._header_index(page)
                heads = sorted(idx)
                _log("    headers(%d): %s" % (len(heads), ", ".join(heads)))
                missing = [c for c in knocks.SHEET_COLUMNS
                           if c not in {knocks.COL_TOTAL_TALK_TO,
                                        *knocks.TIME_TRACKER_COLUMNS}
                           and knocks._norm(c) not in idx]
                if missing:
                    _log("    ⚠ the current scraper would RAISE here — missing: %s"
                         % ", ".join(missing))
            except Exception as e:  # noqa: BLE001
                _log("    headers unavailable (%s: %s)"
                     % (type(e).__name__, str(e)[:120]))
        if office:
            from automations.focus_office_att.run_all_owners import (
                _exit_impersonation)
            _exit_impersonation(page)
    return 0


def probe(day: dt.date, cfg: Dict, headless: bool = True) -> int:
    """READ-ONLY: the rows the board is built from, and their columns.

    Points at the SAME pull the post uses, deliberately. A probe that reads a
    different source can agree with itself while the board is wrong.
    """
    from automations.rashad_metrics.knocks_pull import pull_offices_days
    # The campaign goes with the job, exactly as pull_board sends it. Without
    # it this probe silently reads whatever campaign the office defaults to —
    # which is how Jay's Energy Wells probe came back full of AT&T columns and
    # briefly looked like the pin was broken when only the probe was.
    pulled = pull_offices_days(
        [(cfg["name"], [day], cfg.get("campaign_id") or None)],
        verbose=True, profile_dir=str(C.PROFILE_DIR))
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
    ap.add_argument("--rates", action="store_true",
                    help="force the Avg Knocks/Hr + Avg Doors/Rep columns on "
                         "for THIS run, without arming them for the schedule")
    ap.add_argument("--preview-dm", action="store_true",
                    help="build, then DM the PDF to Megan for review "
                         "(the group gets nothing)")
    ap.add_argument("--probe-campaigns", action="store_true",
                    help="READ-ONLY: list campaign ids and dump each "
                         "Disposition table's live column headers")
    ap.add_argument("--office", default="",
                    help="impersonate this owner for --probe-campaigns")
    ap.add_argument("--campaign", default="",
                    help="pin this invD2DClientId before dumping headers — "
                         "REQUIRED to trust the dump, since the campaign is a "
                         "sticky session-global that impersonation does not "
                         "reset")
    ap.add_argument("--probe", action="store_true",
                    help="READ-ONLY: dump the raw Time Tracker rows")
    args = ap.parse_args(argv)

    day = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
           if args.date else dt.date.today())
    send = args.send and not args.dry_run
    global PREVIEW_DM, RATES_OVERRIDE
    PREVIEW_DM = bool(getattr(args, "preview_dm", False))
    if getattr(args, "rates", False):
        RATES_OVERRIDE = True

    if getattr(args, "probe_campaigns", False):
        return probe_campaigns(headless=not args.headed, office=args.office,
                               campaign=args.campaign)

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
