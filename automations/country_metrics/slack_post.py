"""Post a weekly 'week completed' note to a per-month Country Metrics thread.

Channel #level10-alphalete. Unlike the Penetration report (one permanent
thread all year), Country Metrics opens a NEW thread each month, titled
'🌎 *Country Metrics (June 2026)*' — bold, with the globe icon — where the
month is the one the report is PUBLISHED in (the run date), not the
weekending's month.

  - The monthly parent (title) carries the globe icon, once per month — the
    weekly replies stay icon-light so the thread doesn't get cluttered.
  - The FIRST weekly reply of the month (posted when the thread is created)
    tags Rafael Hidalgo + Maud Miller. Later weeks that month reply untagged.
  - Each weekly reply is just 'WE 6.14 completed ✅' — the just-completed week,
    the same week the sheet column was filled. The thread title supplies the
    'Country Metrics' context.

Posts as the same Slack user the other reports use (reuses slack_metrics_post's
token + client). Best-effort: a Slack failure is logged but NEVER fails the
run — the sheet fill is what matters (mirrors int_wow_penetration, Eve
2026-06-02).
"""
from __future__ import annotations

import calendar
import datetime as dt

from automations.shared import slack_metrics_post as _smp

CHANNEL_ID = "C075PCEL92M"  # #level10-alphalete (private)

# Tagged in the FIRST weekly reply of each month's thread only.
TAG_USER_IDS = ("U045Z8N0ZQC", "U045USN7NCD")  # Rafael Hidalgo, Maud Miller


def month_key(today: dt.date) -> str:
    """'Country Metrics (June 2026)' — stable, un-decorated; used to find this
    month's existing thread regardless of the title's bold/bullet/icon."""
    return f"Country Metrics ({calendar.month_name[today.month]} {today.year})"


def thread_title(today: dt.date) -> str:
    """'🌎 *Country Metrics (June 2026)*' — globe icon, bold. The globe lives
    here (once per month), not on the weekly replies."""
    return f"🌎 *{month_key(today)}*"


def week_label(week: dt.date) -> str:
    """'WE 6.14' — the completed weekending (month.day, un-padded), the same
    week the sheet column was filled."""
    return f"WE {week.month}.{week.day}"


def _find_thread_ts(client, today: dt.date):
    """Return the ts of this month's Country Metrics parent, or None.

    Scans channel history back to the first of the publish month and matches on
    the stable month key (ignoring the title's bold/bullet/icon decoration)."""
    key = month_key(today)
    month_start = today.replace(day=1)
    oldest = dt.datetime.combine(month_start, dt.time.min).timestamp()
    resp = client.conversations_history(
        channel=CHANNEL_ID, oldest=str(oldest), limit=200
    )
    for msg in resp.get("messages", []):
        if key in (msg.get("text", "") or ""):
            return msg.get("thread_ts") or msg.get("ts")
    return None


def ensure_thread(client, today: dt.date) -> dict:
    """Find this month's thread or create it (parent = the decorated title; no
    tags on the title — the leads are tagged on the first weekly reply)."""
    ts = _find_thread_ts(client, today)
    if ts:
        return {"thread_ts": ts, "created": False}
    resp = client.chat_postMessage(channel=CHANNEL_ID, text=thread_title(today))
    return {"thread_ts": resp.get("ts"), "created": True}


def post_update(week: dt.date, today: dt.date, dry_run: bool = False) -> dict:
    """Reply in this month's Country Metrics thread that this week is completed.

    `week` is the just-completed weekending Sunday (drives the 'WE M.D' label);
    `today` is the publish date (drives which month's thread it lands in).
    Creates the monthly thread if it's the first run of the month; that first
    weekly reply tags the leads (Rafael + Maud). Returns a result dict and
    never raises."""
    key = month_key(today)
    base = f"{week_label(week)} completed ✅"
    tags = " ".join(f"<@{u}>" for u in TAG_USER_IDS)
    if dry_run:
        print(f"  [dry-run] thread '{thread_title(today)}' (create-if-missing)")
        print(f"  [dry-run] weekly reply to #level10-alphalete: {base!r}")
        print(f"  [dry-run] (if first reply of the month, append tags: {tags})")
        return {"dry_run": True, "thread_title": key, "text": base}
    try:
        client = _smp._client()
        thread = ensure_thread(client, today)
        text = f"{base} {tags}" if thread["created"] else base
        resp = client.chat_postMessage(
            channel=CHANNEL_ID, thread_ts=thread["thread_ts"], text=text
        )
        return {
            "ok": resp.get("ok"),
            "ts": resp.get("ts"),
            "thread_ts": thread["thread_ts"],
            "thread_title": key,
            "thread_created": thread["created"],
            "tagged": list(TAG_USER_IDS) if thread["created"] else [],
            "text": text,
        }
    except Exception as e:  # noqa: BLE001 — best-effort, never fail the run
        return {"ok": False, "error": str(e), "thread_title": key, "text": base}
