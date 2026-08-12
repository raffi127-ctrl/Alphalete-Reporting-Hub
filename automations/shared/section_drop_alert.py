"""Loud Slack alert when a 4am-flow report silently drops a section.

WHY THIS EXISTS (2026-08-07): reports in the 4am flow (daily_metrics,
office_metrics, the captainship reports) deliberately exit 0 on a dropped
section — "ran with a note" — so the orchestrator won't retry and DOUBLE-POST
the whole thread (Megan 2026-07-11). The cost of that design: exit 0 reads as
SUCCESS, so the orchestrator's own failure alert never fires. A missing section
only turned the Hub card orange + wrote a manifest note — SILENT. That day the
ABP Tableau view collapsed and EVERY office quietly dropped its ABP card; nobody
knew until a rep flagged it hours later.

This fires a LOUD 🚨 alert into #claudecorrections-and-requests straight from
write_manifest — so any recorded failure is heard at 4am, not found at noon. It
is ADDITIVE: the exit-0 / no-double-post behavior is unchanged; this is the alarm
bolted on top. (No @-mention: Megan asked to stop being pinged on every drop,
2026-08-10 — the 🚨 + channel is enough to catch the eye without a notification.)

Dedup: one post per (report_id, date, failed-set). A morning re-run that drops
the SAME section again won't re-spam; a different drop still alerts. Posted as
Lucy (the xoxp user token every Slack post here uses). Always English — the whole
team reads this channel. [[reference_lucy_slack_tokens]] [[project_corrections_slack_channel]]
"""
from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Optional, Sequence

CHANNEL = "C0BK5PRG259"       # #claudecorrections-and-requests
MEGAN = "U04G5HJBGFN"         # Megan Hidalgo — no longer @-mentioned (2026-08-10)
_STATE_DIR = Path("output") / "section_drop_alerts"


def _dedup_path(report_id: str, day: dt.date, failed: Sequence[str]) -> Path:
    key = hashlib.sha1(",".join(sorted(failed)).encode("utf-8")).hexdigest()[:10]
    return _STATE_DIR / f"{report_id}-{day.isoformat()}-{key}.txt"


# What the report LOST, per kind — a fill that drops a day is not a thread that
# dropped a section, and telling Eve "it did NOT post" about a board that filled
# fine sends her looking in the wrong place (2026-08-09).
_KINDS = {
    "section": ("section", "it did NOT post.",
                "re-run only the missing {what}{s} for `{report_id}` — "
                "don't re-post the whole thread.",
                "The thread is live but incomplete."),
    "day": ("day of sales", "the board filled, but SHORT.",
            "fix the frozen day-number cell to '=<prev cell>+1', then re-run "
            "`{report_id}` — the fill is idempotent.",
            "Every total on that board is undercounting until it's re-run."),
    # A Tableau SOURCE that didn't download. The tab still fills from the other
    # sources, so nothing looks broken — the metrics fed by the missing pull are
    # simply blank. Added 2026-08-10: opt_retail's SARA Plus scrape had been
    # returning 0 offices since at least 7/20 and the only trace was an
    # `Errors: 1` buried in a log, so three weeks of Internet / New Lines /
    # Next Up % / Extra-Premium % went missing across every Retail tab unnoticed.
    "source": ("Tableau source", "those metrics are BLANK for this week.",
               "re-run `{report_id}` — the fill is idempotent. If it fails "
               "again, the Tableau view itself is the problem, not the run.",
               "The tabs filled, but every metric fed by that source is empty."),
    # A CAPPED Tableau pull: the Contract ID / Account Id quick filters on the
    # BOX view re-pinned to a stale ID snapshot, so the export froze days behind
    # and the counts understate reality. The report REFUSED to send rather than
    # ship wrong numbers (window.should_block_send). Added 2026-08-12 after
    # Roshan's "accepted sales are wrong" — a bad viz load skipped the filter
    # release and the pull capped at 8/4. Nothing was delivered, so this alert
    # is the only trace: without it a suppressed run is silent.
    "capped": ("Tableau pull", "it capped to a stale ID list, so nothing was "
               "sent.",
               "re-run `{report_id}` once a clean pull lands — the Contract ID "
               "/ Account Id filters likely re-pinned (see box_order_log/"
               "window.py). The fill/merge is idempotent.",
               "No email/post went out — a gap beats numbers that undercount."),
}


def _compose(report_id: str, failed: Sequence[str],
             remediation: Optional[dict], note: str,
             kind: str = "section") -> str:
    what, headline_tail, default_fix, tail = _KINDS.get(kind, _KINDS["section"])
    n = len(failed)
    s = "s" if n != 1 else ""
    lines = [
        f"🚨 *{report_id}* dropped {n} {what}{s} this run — "
        f"{headline_tail}",
        f"*Missing:* {', '.join(failed)}",
    ]
    if note:
        lines.append(f"_{note}_")
    fix = remediation.get("fix") if isinstance(remediation, dict) else None
    if fix:
        lines.append(f"*Fix:* {fix}")
    else:
        lines.append("*Fix:* " + default_fix.format(
            what=what, s=s, report_id=report_id))
    lines.append(tail)
    return "\n".join(lines)


def alert(*, report_id: str, failed: Sequence[str],
          remediation: Optional[dict] = None, note: str = "",
          day: Optional[dt.date] = None, dry_run: bool = False,
          kind: str = "section") -> bool:
    """Post a loud dropped-section ping. One post per (report, day, failed-set).
    Returns True if posted (or already posted today for this exact drop).
    `kind` picks the wording: 'section' (a thread that didn't post) or 'day' (a
    board that filled short — see _KINDS).
    NEVER raises — a failed alert must not fail the report it's warning about."""
    failed = [f for f in (failed or []) if f]
    if not failed:
        return False
    day = day or dt.date.today()
    path = _dedup_path(report_id, day, failed)
    try:
        if path.exists():
            return True
    except Exception:
        pass
    text = _compose(report_id, failed, remediation, note, kind)
    if dry_run:
        print("  --- section-drop alert (dry-run, not sent) ---")
        print("  " + text.replace("\n", "\n  "))
        return False
    try:
        from automations.shared import slack_metrics_post as smp
        smp._client().chat_postMessage(channel=CHANNEL, text=text)
    except Exception as e:  # noqa: BLE001 — alerting must never break the report
        print(f"  ⚠ section-drop alert didn't post "
              f"({type(e).__name__}: {str(e)[:120]})")
        return False
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text("sent", encoding="utf-8")
    except Exception:
        pass
    print(f"  🚨 section-drop alert posted for {report_id}: {failed}")
    return True
