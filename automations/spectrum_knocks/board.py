"""Spectrum Knocks board — a picture of every rep's day, posted every hour.

Raf 2026-11-19: "can we get it to come out at the same frequency that the other
knocking report is coming out at?" -> the OwnerVille GPS threads in the same
channel (rep_knock_threads) go every hour, 10 AM-9 PM CT. So Slack now gets the
board at the top of every hour, 10 AM-9 PM CT, Mon-Sat. An hour with no doors
yet today posts nothing (no empty boards at 10 AM). The iMessage text stays at
three a day (2 PM, 5 PM, 9 PM) so the A-Players group chat isn't hit hourly.

History:

Raf 2026-11-18 ("can we have it send to knocking reports?") + Eve ("igual que
el de OwnerVille"): the OwnerVille intraday knock boards post at 2:00 PM
(First Knocks), 5:15 PM (Money Lap) and 9:00 PM (End of Day), Mon-Sat. Same
three moments here, Central time, into #alphalete-sales-knocking-data.
(The OwnerVille GPS threads in that channel have no Spectrum twin: Spectrum
has no GPS check.)

Raf 2026-11-18, right after: "can we get it posted on the knocking imessage
chat?" -> `--text` sends the same picture to the iMessage room "Knocking Chat
A-Players" (the room his GPS alerts and Line Up picture already text). Slack
and the text are tracked apart, so one failing never re-posts the other.

Who's on it: every rep who knocked today, most doors first, plus reps who have
assigned houses but no doors yet (greyed, at the bottom — at 2 PM that's the
"who isn't out yet" list). Same numbers as the "Spectrum Knocks" tab.

    # preview: draws the PNG to output/spectrum_knocks/board/, posts nothing
    python -m automations.spectrum_knocks.board --slot h14 --force
    # test post to Eve's own DM
    python -m automations.spectrum_knocks.board --slot h21 --force --send --to D087ZGE2B0F
    # live (the LaunchAgent, every 5 min; posts each slot once, when it's due)
    python -m automations.spectrum_knocks.board --tick --send --text
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from automations.spectrum_knocks import pull

CHANNEL_ID = "C0C8KBT065D"            # #alphalete-sales-knocking-data (private, Raf's)
CHANNEL_NAME = "#alphalete-sales-knocking-data"
TEXT_GROUP = "Knocking Chat A-Players"   # Raf's iMessage room
SHEET_URL = ("https://docs.google.com/spreadsheets/d/"
             "1qUiljtWXhcy3OGhQ_81LnNPIsUXjad3MJi-VzjEIDV8/edit#gid=24854023")
TZ = "America/Chicago"
# A slot posts only within this many minutes after its time; a box that was
# asleep at 2 PM must not drop the 2 PM board at 3:30.
LATE_LIMIT_MIN = 60

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "spectrum_knocks" / "board"
STATE_PATH = OUT_DIR / "posted.json"


@dataclass(frozen=True)
class Slot:
    key: str
    hour: int
    minute: int
    label: str
    text: bool = False                 # also goes to the iMessage group


FIRST_HOUR, LAST_HOUR = 10, 21         # same hours as rep_knock_threads
_NAMED = {14: "First Knocks", 17: "Money Lap", 21: "End of Day"}
SLOTS = tuple(
    Slot("h%02d" % h, h, 0, _NAMED.get(h, "Hourly"), text=h in _NAMED)
    for h in range(FIRST_HOUR, LAST_HOUR + 1))
POST_DAYS = {0, 1, 2, 3, 4, 5}        # Mon-Sat


def _now() -> dt.datetime:
    from zoneinfo import ZoneInfo
    return dt.datetime.now(ZoneInfo(TZ)).replace(tzinfo=None)


def due(now: dt.datetime, done: set) -> Optional[Slot]:
    """The slot to post at `now` (naive Central), or None. Latest due wins;
    earlier missed slots are skipped, never posted late."""
    if now.weekday() not in POST_DAYS:
        return None
    for s in reversed(SLOTS):
        at = now.replace(hour=s.hour, minute=s.minute, second=0, microsecond=0)
        if at <= now < at + dt.timedelta(minutes=LATE_LIMIT_MIN):
            key = "%s|%s" % (now.date().isoformat(), s.key)
            return None if key in done else s
    return None


def _state() -> Dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(state: Dict, today: dt.date) -> None:
    cutoff = (today - dt.timedelta(days=14)).isoformat()
    state["posted"] = {k: v for k, v in (state.get("posted") or {}).items()
                       if k.split("|", 1)[0] >= cutoff}
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1), encoding="utf-8")


def _md(d: dt.date) -> str:
    return "%d/%d" % (d.month, d.day)


def _clock(t: dt.datetime) -> str:
    return "%d:%02d %s" % (t.hour % 12 or 12, t.minute, "AM" if t.hour < 12 else "PM")


def board_rows(summary: List[dict]) -> List[dict]:
    """Knocked reps (most doors first), then reps with houses but no doors."""
    knocked = [l for l in summary if l["Doors"]]
    idle = [l for l in summary if not l["Doors"] and (l.get("Assigned Houses") or 0) > 0]
    knocked.sort(key=lambda l: (-l["Doors"], l["Rep"]))
    idle.sort(key=lambda l: l["Rep"])
    return knocked + idle


# --- picture ------------------------------------------------------------------
W = 1340
PAD = 24
ROW_H = 40
HEAD_H = 92
TILES_H = 96
INK = (33, 37, 41)
MUTED = (140, 146, 153)
GRID = (226, 229, 233)
BAND = (0, 69, 135)                   # same navy as the sheet header
ZEBRA = (246, 248, 251)
GREEN = (25, 135, 84)
GREEN_BG = (209, 235, 214)
RED = (200, 35, 51)
RED_BG = (250, 210, 205)

_FONTS = {
    True: ("C:/Windows/Fonts/arialbd.ttf",
           "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
           "/Library/Fonts/Arial Bold.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    False: ("C:/Windows/Fonts/arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
}
_cache: Dict = {}


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    key = (size, bold)
    if key not in _cache:
        for p in _FONTS[bold]:
            try:
                _cache[key] = ImageFont.truetype(p, size)
                break
            except Exception:  # noqa: BLE001
                continue
        else:
            _cache[key] = ImageFont.load_default()
    return _cache[key]


BREAK_COL = "Longest Break (min)"
# (header, summary key, width)
COLS = [
    ("Rep", "Rep", 290), ("Doors", "Doors", 80), ("Assigned", "Assigned Houses", 100),
    ("Not Home", "Not Home", 100), ("Not Int.", "Not Interested", 90),
    ("Pres.", "Presentation (No Sale)", 75), ("Follow Up", "Follow Up", 100),
    ("Sold", "Sold", 70), ("First", "First Door", 100), ("Last", "Last Door", 100),
    ("Hours", "Hours Knocking", 75), ("Long. Break", BREAK_COL, 110),
]


def render(rows: List[dict], title_sub: str, out: Path) -> Path:
    from PIL import Image, ImageDraw
    knocked = [r for r in rows if r["Doors"]]
    tot_doors = sum(r["Doors"] for r in knocked)
    tot_sold = sum(r["Sold"] + r.get("Mobile Sold", 0) for r in knocked)
    tot_pres = sum(r["Presentation (No Sale)"] for r in knocked)
    firsts = [r["First Door"] for r in knocked if r["First Door"]]

    def mins(c):
        t = dt.datetime.strptime(c, "%I:%M %p")
        return t.hour * 60 + t.minute
    first = min(firsts, key=mins) if firsts else "—"

    h = HEAD_H + TILES_H + ROW_H * (len(rows) + 1) + PAD + (ROW_H if not rows else 0)
    im = Image.new("RGB", (W, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, HEAD_H], fill=BAND)
    d.text((PAD, 14), "Spectrum Knocks", font=_font(30, True), fill=(255, 255, 255))
    d.text((PAD, 56), title_sub, font=_font(18), fill=(205, 220, 238))
    y = HEAD_H
    tiles = [("Reps knocking", str(len(knocked))), ("Doors", str(tot_doors)),
             ("Presentations", str(tot_pres)), ("Sold", str(tot_sold)),
             ("First door", first)]
    tw = (W - 2 * PAD) // len(tiles)
    for i, (label, val) in enumerate(tiles):
        x = PAD + i * tw
        d.text((x, y + 16), label.upper(), font=_font(13, True), fill=MUTED)
        col = GREEN if label == "Sold" and tot_sold else INK
        d.text((x, y + 38), val, font=_font(26, True), fill=col)
    y += TILES_H

    d.rectangle([0, y, W, y + ROW_H], fill=(232, 237, 243))
    x = PAD
    for name, _, cw in COLS:
        d.text((x, y + 11), name, font=_font(15, True), fill=INK)
        x += cw
    y += ROW_H
    if not rows:
        d.text((PAD, y + 10), "No doors yet today.", font=_font(16), fill=MUTED)
    for ri, r in enumerate(rows):
        idle = not r["Doors"]
        d.rectangle([0, y, W, y + ROW_H], fill=ZEBRA if ri % 2 else (255, 255, 255))
        d.line([0, y + ROW_H, W, y + ROW_H], fill=GRID)
        x = PAD
        for name, key, cw in COLS:
            val = r.get(key, "")
            if idle and key not in ("Rep", "Assigned Houses"):
                val = "—" if key == "Doors" else ""
            txt = str(val)
            f = _font(16, key in ("Rep", "Doors"))
            col = MUTED if idle else INK
            if key == "Sold" and not idle and (r["Sold"] or r.get("Mobile Sold")):
                d.rectangle([x - 8, y + 4, x + cw - 16, y + ROW_H - 4], fill=GREEN_BG)
                txt, col, f = str(r["Sold"] + r.get("Mobile Sold", 0)), GREEN, _font(16, True)
            if key == BREAK_COL and not idle and (r.get(BREAK_COL) or 0) >= 60:
                d.rectangle([x - 8, y + 4, x + cw - 16, y + ROW_H - 4], fill=RED_BG)
                col, f = RED, _font(16, True)
            if key == "Rep" and idle:
                txt += "  (not out yet)"
            while txt and d.textlength(txt, font=f) > cw - 12:
                txt = txt[:-1]
            d.text((x, y + 11), txt, font=f, fill=col)
            x += cw
        y += ROW_H
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


# --- Slack --------------------------------------------------------------------
def post(png: Path, caption: str, channel: str) -> None:
    from automations.shared import slack_metrics_post as smp
    smp._client().files_upload_v2(
        channel=channel, initial_comment=caption,
        file_uploads=[{"file": str(png), "filename": png.name}])


# --- iMessage -----------------------------------------------------------------
def text_caption(slot: Slot, day: dt.date, rows: List[dict]) -> str:
    """Plain words (no Slack markup, no sheet link -- not everyone in the chat
    can open the sheet)."""
    knocked = [r for r in rows if r["Doors"]]
    return ("Spectrum Knocks · %s · %s %s — %d reps, %d doors, %d sold"
            % (slot.label, day.strftime("%a"), _md(day), len(knocked),
               sum(r["Doors"] for r in knocked),
               sum(r["Sold"] + r.get("Mobile Sold", 0) for r in knocked)))


def send_text(png: Path, caption: str, live: bool) -> Dict:
    """Picture + one line to TEXT_GROUP. live=False only checks this Lucy can
    see the group (read-only) and sends nothing."""
    from automations.b2b_dispositions import text_post as tp
    from automations.gap_alerts import config as GA
    if live and not GA.can_text():
        raise RuntimeError("this machine can't text (not in TEXTING_MACHINES)")
    return tp.send_to_group(TEXT_GROUP, caption, [png], dry_run=not live)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tick", action="store_true", help="post whichever slot is due now")
    ap.add_argument("--slot", choices=[s.key for s in SLOTS], help="this slot, now")
    ap.add_argument("--force", action="store_true", help="--slot even off-schedule")
    ap.add_argument("--send", action="store_true", help="post to Slack (default: preview)")
    ap.add_argument("--text", action="store_true",
                    help="also text the picture to %s" % TEXT_GROUP)
    ap.add_argument("--check-text", action="store_true",
                    help="only check this Lucy is in %s; sends nothing" % TEXT_GROUP)
    ap.add_argument("--to", default=CHANNEL_ID, help="channel/DM id (tests: Eve's DM)")
    ap.add_argument("--day", help="YYYY-MM-DD (default today, Central)")
    a = ap.parse_args(argv)

    now = _now()
    state = _state()
    done = set((state.get("posted") or {}).keys())
    if a.check_text:
        r = send_text(Path(), "", live=False)
        print("[spectrum_board] %s OK on this Lucy: %s (%s people)"
              % (TEXT_GROUP, r["resolved_name"], r["participants"]))
        return 0
    if a.tick:
        slot = due(now, set())
        if slot is None:
            print("[spectrum_board] %s CT — nothing due" % _clock(now))
            return 0
        key = "%s|%s" % (now.date().isoformat(), slot.key)
        want_slack = a.send and key not in done
        want_text = a.text and slot.text and (key + "|text") not in done
        if not (want_slack or want_text):
            print("[spectrum_board] %s CT — %s already posted" % (_clock(now), slot.label))
            return 0
    elif a.slot:
        slot = next(s for s in SLOTS if s.key == a.slot)
        if not a.force and due(now, set()) != slot:
            print("[spectrum_board] %s isn't due now (use --force)" % slot.label)
            return 0
        want_slack, want_text = a.send, a.text
    else:
        ap.error("give --tick or --slot (or --check-text)")
    day = dt.date.fromisoformat(a.day) if a.day else now.date()

    summary = pull.run(day)
    rows = board_rows(summary)
    asof = _clock(now) if day == now.date() else "end of day"
    sub = "%s  ·  %s %s  ·  as of %s CT" % (slot.label, day.strftime("%a"), _md(day), asof)
    png = render(rows, sub, OUT_DIR / day.isoformat() / ("%s.png" % slot.key))
    knocked = [r for r in rows if r["Doors"]]
    if a.tick and not knocked and day == now.date():
        # Nobody's out yet: no empty board. Mark the hour so the next 5-min
        # tick doesn't pull again; the next hour tries fresh.
        print("[spectrum_board] %s CT — no doors yet, %s skipped"
              % (_clock(now), slot.label))
        if a.send or a.text:
            k = "%s|%s" % (day.isoformat(), slot.key)
            state.setdefault("posted", {})[k] = "skipped"
            state["posted"][k + "|text"] = "skipped"
            _save(state, day)
        return 0
    caption = ("*Spectrum Knocks · %s · %s %s* — %d reps, %d doors, %d sold\n"
               "Full sheet: <%s|Spectrum Knocks tab>"
               % (slot.label, day.strftime("%a"), _md(day), len(knocked),
                  sum(r["Doors"] for r in knocked),
                  sum(r["Sold"] + r.get("Mobile Sold", 0) for r in knocked), SHEET_URL))
    print("[spectrum_board] %s -> %s" % (caption.splitlines()[0], png))
    if not (a.send or a.text):
        print("[spectrum_board] PREVIEW — nothing posted")
        return 0
    key = "%s|%s" % (day.isoformat(), slot.key)
    if a.send and want_slack:
        post(png, caption, a.to)
        print("[spectrum_board] posted to %s" % a.to)
        if a.tick and a.to == CHANNEL_ID:
            state.setdefault("posted", {})[key] = now.isoformat()
            _save(state, day)
    if want_text:
        # Raises on failure (logged, ticket); Slack above is already saved, so
        # the next tick retries only the text, inside the same late limit.
        send_text(png, text_caption(slot, day, rows), live=True)
        print("[spectrum_board] texted %s" % TEXT_GROUP)
        if a.tick:
            state.setdefault("posted", {})[key + "|text"] = now.isoformat()
            _save(state, day)
    return 0


if __name__ == "__main__":
    sys.exit(main())
