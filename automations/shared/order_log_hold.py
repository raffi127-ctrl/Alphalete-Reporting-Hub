"""Hold an Order Log section when Tableau's Order Log hasn't caught up.

WHY (Raf, 2026-09-29): that morning the ATT TRACKER 2.1 - D2D ORDER LOG
(ALLREPS) was two days behind -- newest data 9/27, most of 9/24-9/26 missing --
and every office's Order Log posted a fraction of its real rows (Rashad: 0,
where the day before was 531). tableau_freshness saw it and said so
("STALE PULL ... newest data 2026-09-27, needs 2026-09-28"), but that guard only
WARNS, by design, for ~120 reports. The metrics posted anyway, understated,
with nothing in the channel to say so.

WHAT THIS DOES. The four office-metrics sections built on that one view --
Order Log, Canceled Orders, Disconnects, Sales Scheduled 6+ Days Out -- call
hold_if_stale() on the export they are about to post from (fresh download or
cache, it judges the FILE). When its newest ORDER or STATUS date is older than
yesterday (the STALE PULL warning's bar, on the columns that mean a sale), the
section posts ONE short notice into today's Metrics thread instead of its
numbers and exits HELD_EXIT (75, EX_TEMPFAIL -- the house "held, not crashed"
code). Every other section posts as normal: only the section that read the
lagging data is held.

SELF-HEALING. Nothing is remembered except "the notice went out today", so
the orchestrator's part-retry of an INCOMPLETE run -- and every later normal
run -- pulls again and posts the real numbers the moment the export is fresh.
The notice is posted at most once per section, per channel, per day, so those
retries can never stack notices in a room.

OPT-IN, per process: METRICS_HOLD_STALE_ORDER_LOG=1, which the office-metrics
runner sets. Every other caller of these modules behaves exactly as before.
Never raises: if the check itself breaks, the section posts as it always did.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV = "METRICS_HOLD_STALE_ORDER_LOG"
OFFICE_ENV = "METRICS_OFFICE_KEY"   # set by office_metrics.runner
HELD_EXIT = 75

# The one view all four sections read (canceled_orders/disconnects/
# scheduled_6_days_out/uploaded.order_log pull it with their own date ranges).
ORDER_LOG_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                  "ATTTRACKER2_1-D2D/ORDERLOG/117748c0-9487-45e8-a5d4-c447093718d5/ALLREPS")
ORDER_LOG_SHEET = "A.Order Log"

NOTICE = ("⏳ {label}: Order Log data is behind (Tableau not caught up{detail}) "
          "— this section is held and will post once the data lands.")

MARK_DIR = REPO_ROOT / "output" / "order_log_hold"


def enabled() -> bool:
    return (os.environ.get(ENV) or "").strip().lower() in ("1", "true", "yes")


# JUDGED ON THE ORDER LOG'S OWN EVENT DATES ONLY. tableau_freshness takes the
# newest date in ANY date column, and this export carries install-appointment
# columns ('spe.dtr First Available Date') that routinely hold TODAY: at 8:54 on
# 2026-09-29 one such row made an export with zero orders after 9/26 read as
# "fresh". An order or a status change is what a day of selling leaves behind.
EVENT_COLUMNS = ("sp.Order Date (copy)", "Status Date")
MAX_DAYS_BEHIND = 1       # same bar as the STALE PULL warning: yesterday must be in


def verdict(csv_path, today: Optional[dt.date] = None) -> dict:
    """{'verdict': 'fresh'|'stale'|'unknown', 'newest', 'needs'} for this
    export, from its Order Date / Status Date columns alone."""
    from automations.shared import tableau_freshness as tf
    today = today or dt.date.today()
    needs = today - dt.timedelta(days=MAX_DAYS_BEHIND)
    header, rows = tf._rows(csv_path)
    cols = [i for i, h in enumerate(header or [])
            if (h or "").strip().lstrip("\ufeff") in EVENT_COLUMNS]
    if not cols:
        return {"verdict": "unknown", "newest": None, "needs": needs}
    newest = None
    for r in rows:
        for i in cols:
            if i < len(r):
                d = tf.parse_date(r[i], today=today)
                if d is not None and d <= today and (newest is None or d > newest):
                    newest = d
    if newest is None:
        return {"verdict": "unknown", "newest": None, "needs": needs}
    return {"verdict": "fresh" if newest >= needs else "stale",
            "newest": newest, "needs": needs}


def notice_text(label: str, newest=None, needs=None) -> str:
    detail = ""
    if newest and needs:
        detail = " — newest {}, needs {}".format(_md(newest), _md(needs))
    return NOTICE.format(label=label, detail=detail)


def _md(d) -> str:
    try:
        return "%d/%d" % (d.month, d.day)
    except AttributeError:
        return str(d)


def _mark_path(label: str, today: dt.date) -> Path:
    """One notice per OFFICE + channel + section a day. The office is in the
    key because email-only offices have no channel: on 2026-09-29 joseph's and
    christian's runs both keyed as "default", and the second office's held
    notices were never sent."""
    report = os.environ.get(OFFICE_ENV) or "office"
    channel = os.environ.get("METRICS_CHANNEL_ID") or "default"
    slug = "".join(ch if ch.isalnum() else "-" for ch in label.lower()).strip("-")[:40]
    return MARK_DIR / today.isoformat() / ("%s--%s--%s.json" % (report, channel, slug))


def hold(label: str, newest=None, needs=None, *, post: bool,
         today: Optional[dt.date] = None, poster=None) -> int:
    """Post the held notice (once per section/channel/day) and return HELD_EXIT."""
    today = today or dt.date.today()
    text = notice_text(label, newest, needs)
    print("⏳ HELD: %s — Order Log data is behind (newest %s, needs %s). Not "
          "posting understated numbers." % (label, newest, needs), flush=True)
    mark = _mark_path(label, today)
    if not post:
        print("  --dry-run — would post: %r" % text, flush=True)
        return HELD_EXIT
    if mark.exists():
        print("  (held notice already in the channel today — not repeating it)", flush=True)
        return HELD_EXIT
    try:
        if poster is None:
            from automations.shared import slack_metrics_post as smp
            poster = smp.post_reply_text_only
        res = poster(text, react_emoji="hourglass_flowing_sand", today=today)
        if res and res.get("ok", True):
            mark.parent.mkdir(parents=True, exist_ok=True)
            mark.write_text(json.dumps({"label": label, "text": text,
                                        "at": dt.datetime.now().isoformat(timespec="seconds")}))
            print("  ✓ posted the held notice", flush=True)
    except Exception as e:  # noqa: BLE001 -- the hold stands even if the notice fails
        print("  ⚠ held notice failed to post (%s: %s) — section still held"
              % (type(e).__name__, str(e)[:160]), flush=True)
    return HELD_EXIT


def hold_if_stale(csv_path, label: str, *, post: bool,
                  today: Optional[dt.date] = None, poster=None) -> Optional[int]:
    """HELD_EXIT (after the notice) when enabled and this export is stale; None
    to carry on and post normally."""
    if not enabled():
        return None
    try:
        v = verdict(csv_path, today=today)
    except Exception as e:  # noqa: BLE001 -- a broken check never costs a post
        print("  [order-log hold] check failed (%s) — posting as normal" % type(e).__name__)
        return None
    if v.get("verdict") != "stale":
        return None
    return hold(label, v.get("newest"), v.get("needs"), post=post, today=today, poster=poster)


def empty_day_error(exc: BaseException) -> bool:
    """The ALLREPS view HIDES its worksheet when the URL date filter matches no
    rows, so a one-day pull for a day the extract hasn't loaded fails with the
    Crosstab dialog offering only 'Last Refresh'. That is missing data, not a
    changed view."""
    msg = str(exc)
    return "Couldn't find the 'A.Order Log' sheet" in msg and "Last Refresh" in msg
