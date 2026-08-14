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

SHAPE (2026-08-13): the CHANNEL message is the headline + the one-line fix only;
the list of what dropped goes in a threaded reply, chunked across replies if it's
long. The Vantura board audit's 13 findings used to land in the channel post and
filled the whole screen, burying every other report's alert — "this error is too
long in the slack channel, it should be in the reply on the thread" (Megan). Same
information, just not all of it at eye level. A 1-2 item drop still reads inline.

Thread per report (2026-08-14): the first drop opens a post; a drop on a LATER
day replies in that post's thread instead of adding another one, and the first
clean run closes it with a ✅ in the same thread (`resolved`, called from
run_manifest). See automations/shared/incident_thread.py.

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
#
# Each entry owns its WHOLE headline, not just a tail. 'dropped N X this run'
# was hard-coded into _compose, which meant a kind whose run didn't drop
# anything (see 'finding') could not be worded truthfully no matter what it put
# in the other fields.
#   what    unit label, pluralised with {s}
#   headline  first line; {report_id} {n} {what} {s} {tail}
#   label   the second line's prefix ('Missing', 'Findings')
#   bullets one item per line instead of a comma-joined run-on
#   fix     default *Fix:* line when the caller passes no remediation
#   tail    closing line: what the reader is left with
_KINDS = {
    "section": {
        "what": "section",
        "headline": "🚨 *{report_id}* dropped {n} {what}{s} this run — {tail}",
        "tail_headline": "it did NOT post.",
        "label": "Missing",
        "fix": "re-run only the missing {what}{s} for `{report_id}` — "
               "don't re-post the whole thread.",
        "tail": "The thread is live but incomplete.",
    },
    "day": {
        "what": "day of sales",
        "headline": "🚨 *{report_id}* dropped {n} {what}{s} this run — {tail}",
        "tail_headline": "the board filled, but SHORT.",
        "label": "Missing",
        "fix": "fix the frozen day-number cell to '=<prev cell>+1', then re-run "
               "`{report_id}` — the fill is idempotent.",
        "tail": "Every total on that board is undercounting until it's re-run.",
    },
    # A Tableau SOURCE that didn't download. The tab still fills from the other
    # sources, so nothing looks broken — the metrics fed by the missing pull are
    # simply blank. Added 2026-08-10: opt_retail's SARA Plus scrape had been
    # returning 0 offices since at least 7/20 and the only trace was an
    # `Errors: 1` buried in a log, so three weeks of Internet / New Lines /
    # Next Up % / Extra-Premium % went missing across every Retail tab unnoticed.
    "source": {
        "what": "Tableau source",
        "headline": "🚨 *{report_id}* dropped {n} {what}{s} this run — {tail}",
        "tail_headline": "those metrics are BLANK for this week.",
        "label": "Missing",
        "fix": "re-run `{report_id}` — the fill is idempotent. If it fails "
               "again, the Tableau view itself is the problem, not the run.",
        "tail": "The tabs filled, but every metric fed by that source is empty.",
    },
    # A CAPPED Tableau pull: the Contract ID / Account Id quick filters on the
    # BOX view re-pinned to a stale ID snapshot, so the export froze days behind
    # and the counts understate reality. The report REFUSED to send rather than
    # ship wrong numbers (window.should_block_send). Added 2026-08-12 after
    # Roshan's "accepted sales are wrong" — a bad viz load skipped the filter
    # release and the pull capped at 8/4. Nothing was delivered, so this alert
    # is the only trace: without it a suppressed run is silent.
    "capped": {
        "what": "Tableau pull",
        "headline": "🚨 *{report_id}* dropped {n} {what}{s} this run — {tail}",
        "tail_headline": "it capped to a stale ID list, so nothing was sent.",
        "label": "Missing",
        "fix": "re-run `{report_id}` once a clean pull lands — the Contract ID "
               "/ Account Id filters likely re-pinned (see box_order_log/"
               "window.py). The fill/merge is idempotent.",
        "tail": "No email/post went out — a gap beats numbers that undercount.",
    },
    # A data-quality AUDIT finding (kind='finding' — vantura_board_audit today).
    # NOTHING DROPPED. The audit ran end to end and did exactly the job it
    # exists to do: report a contradiction it found on the board. It posts no
    # thread, fills no cells, and re-running it changes nothing — a human fixes
    # the Sheet. So every clause of the 'section' fallback was false here.
    # 2026-08-14 one open termination (Samantha Rodriguez, Roll Call r41, Date
    # Gone 8/13 but still Active) went out as "dropped 1 section this run — it
    # did NOT post … re-run only the missing section … the thread is live but
    # incomplete", and the morning went to hunting a broken run instead of the
    # one Roll Call cell. The orchestrator already words findings correctly
    # (day_orchestrator/notify.py _post_findings_corrections); this alert was
    # the last place that didn't.
    # Bulleted: findings are full sentences, and comma-joining three of them
    # makes one unreadable line.
    "finding": {
        "what": "open board data-quality finding",
        "headline": "🔎 *{report_id}* found {n} {what}{s} — {tail}",
        "tail_headline": "the run itself was fine.",
        "label": "Findings",
        "bullets": True,
        "see_thread": "Listed in thread.",
        "detail_header": "*The {n} {what}{s}:*",
        # the audit's manifest note is a truncated re-listing of the same
        # findings already bulleted above — printing both says it twice.
        "skip_note": True,
        "fix": "fix it on the board itself (Roll Call status, Stations formula, "
               "…). Re-running `{report_id}` will NOT clear it — the audit only "
               "detects, it never edits the board. Findings are also logged to "
               "the board's 'Report an Issue' tab.",
        "tail": "Nothing to re-run and nothing is missing: the alert clears on "
                "the next run once the board is corrected.",
    },
}

# Manifest kinds that mean "a fill lost part of its work" — they read correctly
# under the 'section' wording, so they fall back on purpose. Anything ELSE that
# isn't listed in _KINDS is a kind nobody has worded yet: say so in the log
# rather than shipping it as "it did NOT post" (that silent aliasing is exactly
# how 'finding' went out wrong for a week).
_FILL_SHAPED = {"part", "step", "phase", "report", "tracker", "week", "tab",
                "owner", "ICD", "captainship", "recruiter", "team", "title"}


# A drop with more items (or more text) than this doesn't belong in the channel —
# the list goes to the thread. Below it, a 1-2 item drop reads fine inline and a
# thread would just be an extra click (Megan 2026-08-13).
_INLINE_ITEMS = 2
_INLINE_CHARS = 220


def _compose(report_id: str, failed: Sequence[str],
             remediation: Optional[dict], note: str,
             kind: str = "section") -> str:
    """Back-compat single-blob text (used by the dry-run preview and tests)."""
    parent, detail = _compose_parts(report_id, failed, remediation, note, kind)
    return "\n".join(parent + detail)


def _compose_parts(report_id: str, failed: Sequence[str],
                   remediation: Optional[dict], note: str,
                   kind: str = "section"):
    """(parent_lines, detail_lines) — the channel post and its threaded detail.

    PARENT: what broke, how many, and the one-line fix. DETAIL: the actual list
    of missing items + the run's note. Same information as before, just not all
    of it on the channel's screen (Megan 2026-08-13: the 13-finding Vantura board
    audit alert filled the whole channel).

    Every phrase comes off the kind's spec (see _KINDS) — the wording used to be
    baked in here, which is why a kind whose run dropped NOTHING could not be
    described truthfully no matter what it declared.
    """
    spec = _KINDS.get(kind)
    if spec is None:
        if kind not in _FILL_SHAPED:
            print(f"  ⚠ section-drop alert: kind {kind!r} has no wording — "
                  "falling back to 'section' (\"it did NOT post\"), which may "
                  "be wrong. Add it to _KINDS.")
        spec = _KINDS["section"]
    what, n = spec["what"], len(failed)
    s = "s" if n != 1 else ""
    fmt = dict(report_id=report_id, n=n, what=what, s=s)

    body = [f"*{spec['label']}:* {', '.join(failed)}"]
    if note and not spec.get("skip_note"):
        body.append(f"_{note}_")
    # A bulleted kind ALWAYS threads: its items are full sentences, and even one
    # of them fills the channel — which is the whole point of the split.
    threaded = (bool(spec.get("bullets")) or n > _INLINE_ITEMS
                or sum(len(b) for b in body) > _INLINE_CHARS)

    headline = spec["headline"].format(tail=spec["tail_headline"], **fmt)
    if threaded:
        headline += "  " + spec.get("see_thread", "See thread for the list.")
    parent = [headline]
    if not threaded:
        parent += body
    fix = remediation.get("fix") if isinstance(remediation, dict) else None
    fix_line = f"*Fix:* {fix or spec['fix'].format(**fmt)}"
    # The fix goes wherever it can actually be read. A one-liner stays in the
    # channel — that's the whole value of the parent. But once an alert is
    # already threading its detail, a PARAGRAPH-length remediation is the same
    # wall of text this split exists to prevent, so it goes down with the rest.
    # The 'finding' fix is 240 chars on its own, which is what left the Vantura
    # audit's parent at 456 against this module's own 400-char contract
    # (test_alert_thread has been failing on main since 2026-08-13).
    fix_threaded = threaded and len(fix_line) > _INLINE_CHARS
    if not fix_threaded:
        parent.append(fix_line)
    parent.append(spec["tail"])
    if not threaded:
        return parent, []
    detail = [spec.get("detail_header",
                       "*The {n} {what}{s} that dropped:*").format(**fmt)]
    detail += [f"   • {f}" for f in failed]
    if note and not spec.get("skip_note"):
        detail += ["", f"_{note}_"]
    if fix_threaded:
        detail += ["", fix_line]
    return parent, detail


def resolved(report_id: str, *, dry_run: bool = False) -> bool:
    """This report just ran CLEAN — say so in its open alert thread and close it.

    Called from run_manifest.write_manifest on any successful run, so a drop that
    fixes itself stops looking open the moment it's fixed instead of sitting in
    the channel until somebody asks (Eve 2026-08-14). Silent and free when there
    is no open incident: it reads a local index, not Slack. Never raises."""
    try:
        from automations.shared import incident_thread as _inc
        key = "drop-{}".format(report_id)
        if key not in _inc.open_keys():
            return False
        return _inc.resolve(
            key=key,
            lines=["✅ *{}* — RESOLVED. It just ran clean, nothing "
                   "dropped.".format(report_id),
                   "_Closed. A new drop opens a fresh post, not this thread._"],
            channel=CHANNEL, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001 — closing must never break a good run
        print("  ⚠ couldn't close the drop alert for {} ({}: {})".format(
            report_id, type(e).__name__, str(e)[:80]))
        return False


def alert(*, report_id: str, failed: Sequence[str],
          remediation: Optional[dict] = None, note: str = "",
          day: Optional[dt.date] = None, dry_run: bool = False,
          kind: str = "section") -> bool:
    """Post a loud dropped-section ping. One post per (report, day, failed-set).
    Returns True if posted (or already posted today for this exact drop).
    `kind` picks the wording: 'section' (a thread that didn't post), 'day' (a
    board that filled short), 'source'/'capped' (a Tableau pull) or 'finding'
    (a data-quality audit that found something — nothing dropped). See _KINDS.
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
    parent_lines, detail = _compose_parts(report_id, failed, remediation,
                                          note, kind)
    from automations.shared import alert_thread
    parent = "\n".join(parent_lines)
    replies = alert_thread.chunk(detail) if detail else []
    if dry_run:
        print("  --- section-drop alert (dry-run, not sent) ---")
        print("  [channel post]")
        print("  " + parent.replace("\n", "\n  "))
        for i, r in enumerate(replies, 1):
            print(f"  [thread reply {i}/{len(replies)}]")
            print("  " + r.replace("\n", "\n  "))
        return False
    try:
        from automations.shared import slack_metrics_post as smp
        client = smp._client()
        # One THREAD per report, not one post per day: a drop that keeps
        # happening replies under the first alert instead of adding another
        # near-identical message to the channel (Eve 2026-08-14). The incident
        # closes itself on the first clean run (see `resolved`, called from
        # run_manifest), so the next drop opens a fresh post. Falls back to the
        # plain post if anything about it fails.
        posted = None
        try:
            from automations.shared import incident_thread as _inc
            posted = _inc.open_or_followup(key="drop-{}".format(report_id),
                                           title=parent_lines[0],
                                           body=parent_lines[1:],
                                           details=detail, channel=CHANNEL,
                                           day=day, client=client)
        except Exception as e:  # noqa: BLE001
            print("  ⚠ incident thread unavailable ({}: {}) — posting "
                  "standalone".format(type(e).__name__, str(e)[:80]))
        if not posted:
            resp = client.chat_postMessage(channel=CHANNEL, text=parent)
            ts = resp.get("ts")
            # Detail goes UNDER the parent. If the parent's ts came back empty we
            # still post the detail (as its own message) — a lost finding is worse
            # than an unthreaded one.
            for r in replies:
                kw = {"channel": CHANNEL, "text": r}
                if ts:
                    kw["thread_ts"] = ts
                client.chat_postMessage(**kw)
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
