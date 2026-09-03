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

Dedup: per (report_id, date, failed-set), on a 45-minute COOLDOWN — not once a
day. A re-run that drops the same section again does report back, as a reply in
the same thread; it just won't narrate a retry loop tick by tick, and a different
drop still alerts immediately (Eve 2026-08-17). Posted as
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


# A repeat of the SAME drop stays quiet this long, then reports again — in the
# thread, not as a new post. It used to be silent for the whole day, which meant
# a re-run that dropped the same section again told nobody (Eve 2026-08-17: "si
# por una re-corrida volviera a fallar, que la reincidencia caiga dentro del
# thread"). What it reports back is one EDITED status line in that thread, not a
# new message — incident_thread folds a same-day repeat into it — so this only
# bounds how often we call in, never how much the thread grows.
_REALERT_AFTER_S = 45 * 60


def _dedup_path(report_id: str, day: dt.date, failed: Sequence[str]) -> Path:
    key = hashlib.sha1(",".join(sorted(failed)).encode("utf-8")).hexdigest()[:10]
    return _STATE_DIR / f"{report_id}-{day.isoformat()}-{key}.txt"


def _muted(path: Path) -> bool:
    """True while this exact drop is inside its cooldown. A DIFFERENT set of
    dropped sections has its own path, so it is never muted by this one."""
    import time
    try:
        return (path.exists()
                and (time.time() - path.stat().st_mtime) < _REALERT_AFTER_S)
    except Exception:  # noqa: BLE001 — unreadable stamp = say it again
        return False


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
    # THE WHOLE THREAD IS MISSING — not a section of a live thread, the entire
    # post. 'section' was wrong for this: its closing line reads "The thread is
    # live but incomplete", which sends the reader looking for a thread that was
    # never created. Added 2026-08-15 for box_order_log's last-pass-failed alert
    # (deploy/box_order_log.sh), where a crash before the post means both of its
    # channels have nothing at all.
    "no_post": {
        "what": "daily thread",
        "headline": "🚨 *{report_id}* dropped {n} {what}{s} this run — {tail}",
        "tail_headline": "nothing posted at all.",
        "label": "Missing",
        "fix": "read the run's log, fix the cause, then re-post `{report_id}`.",
        "tail": "There is NO thread in the channel today — not a short one, none.",
    },
    # AN OWNER'S EMAIL never went out. 'no_post' is nearly right — the whole
    # delivery is missing, not a piece of it — but every word of it says thread
    # and channel, and these owners have neither: they read their BOX Order Log
    # in their inbox. On 2026-08-19 Roshan's 7:00 email died on a wedged browser
    # profile and nothing in the channel said so; wording that sent the reader
    # hunting a Slack thread would have cost more of the morning. Added
    # 2026-08-19 for deploy/box_order_log_owners.sh.
    "no_email": {
        "what": "owner email",
        "headline": "🚨 *{report_id}* dropped {n} {what}{s} this run — {tail}",
        "tail_headline": "their inbox got nothing at all.",
        "label": "Never emailed",
        "fix": "read the run's log, fix the cause, then re-send `{report_id}`.",
        "tail": "There is NO email today — not a short one, none. They have no "
                "way to notice it's missing; they just don't get it.",
    },
    "section": {
        "what": "section",
        "headline": "🚨 *{report_id}* dropped {n} {what}{s} this run — {tail}",
        "tail_headline": "it did NOT post.",
        "label": "Missing",
        "fix": "re-run only the missing {what}{s} for `{report_id}` — "
               "don't re-post the whole thread.",
        "tail": "The thread is live but incomplete.",
    },
    # One OFFICE's post missing from a thread that carries several offices
    # (other_office_knocks: one Total Knocks image per office in a shared
    # thread). 'section' is nearly right — the thread IS live but incomplete —
    # but "dropped 1 section" doesn't say WHAT is missing, and the fix here is
    # office-scoped: re-running the whole report re-posts the office that
    # already landed, because there's no already-posted guard. Added
    # 2026-08-18.
    "office": {
        "what": "office",
        "headline": "🚨 *{report_id}* dropped {n} {what}{s} this run — {tail}",
        "tail_headline": "that office is MISSING from the thread.",
        "label": "Missing",
        "fix": "re-run only the missing {what}{s} for `{report_id}` — a whole "
               "re-run RE-POSTS the {what}{s} that already landed.",
        "tail": "The thread is live, but it's short one office.",
    },
    # The country trackers' own kind (tableau_screenshots writes kind="channel").
    # Its `failed` list is deliberately MIXED — a channel label that missed the
    # thread, `tracker:<id>` for a board that didn't capture, `stale:<id>` for a
    # board the freshness gate HELD — so no single noun fits, and the 'section'
    # fallback described all three as sections that "did NOT post" of a thread
    # that is "live but incomplete". On 2026-08-26 that went out over five
    # `stale:` holds from a one-channel run: the org-wide thread had posted
    # cleanly at 04:17 in all 15 channels, and the alert read as if it hadn't.
    # A held board needs NO action (the ~7am catch-up posts it), which is why
    # the fix line points at the manifest's scoped retry rather than a re-post.
    "channel": {
        "what": "piece",
        "headline": "🚨 *{report_id}* — {n} {what}{s} of today's tracker thread "
                    "didn't land — {tail}",
        "tail_headline": "part of it is missing.",
        "label": "Didn't land",
        "fix": "re-run `{report_id}` with the manifest's retry args (already "
               "scoped to what missed) — don't re-post the whole thread.",
        "tail": "A `stale:` line is a board HELD because its Tableau extract "
                "hadn't refreshed — the ~7am catch-up posts it, nothing to do. "
                "A channel or `tracker:` line is a real miss.",
    },
    "day": {
        "what": "day of sales",
        "headline": "🚨 *{report_id}* dropped {n} {what}{s} this run — {tail}",
        "tail_headline": "the board filled, but SHORT.",
        "label": "Missing",
        "fix": "the day-number row does not match real dates — run `python -m "
               "automations.org_sales_board.daynum_repair --apply` (both "
               "boards), then re-run `{report_id}`; the fill is idempotent.",
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
    # A multi-PHASE run that collapsed at one of its phases — daily_rep_breakdown
    # today (Phase 2 ownerville scrape / Phase 3 Tableau pull, focus_office_att/
    # daily.py::_daily_manifest_fail). That report has no Slack thread at all: it
    # fills ~28 Sheet tabs. Under the 'section' fallback its Phase-2 drop went out
    # on 2026-08-17 as "it did NOT post … The thread is live but incomplete …
    # re-run only the missing section — don't re-post the whole thread", which is
    # wrong three times over: there is no post, there is no thread to be live, and
    # a phase carries NO scoped retry (daily.py takes no CLI args) so the only
    # real fix is re-running the WHOLE report — which is cheap, because Phase 2
    # resumes from its own checkpoint and doesn't re-scrape finished owners. Same
    # lesson as 'day' / 'source' / 'finding' above: a fill is not a thread.
    "phase": {
        "what": "phase",
        "headline": "🚨 *{report_id}* stopped at {n} {what}{s} this run — {tail}",
        "tail_headline": "the run did NOT finish.",
        "label": "Stopped at",
        "fix": "re-run `{report_id}` WHOLE — it resumes from its own "
               "checkpoint, so the work that already finished isn't redone. "
               "There's no way to re-run just the {what} on its own.",
        "tail": "No post and no thread are involved — the Sheet simply wasn't "
                "updated past that {what}.",
    },
    # A CAPPED Tableau pull: the export's newest sale sits days short of today, so
    # the counts understate reality and the report REFUSED to send rather than
    # ship wrong numbers (window.should_block_send). Added 2026-08-12 after
    # Roshan's "accepted sales are wrong" — a bad viz load skipped the filter
    # release and the pull capped at 8/4. Nothing was delivered, so this alert
    # is the only trace: without it a suppressed run is silent.
    #
    # POINT AT THE ONE CHECK THAT SETTLES IT (Eve 2026-08-17). The dates alone
    # CANNOT tell a re-pinned filter from a stalled source: a Contract ID include
    # list frozen on day X starves every owner from day X onward, which looks
    # exactly like the feed stopping. I claimed the opposite here for a few hours
    # ("all owners on the same day = the source") and it was flatly wrong — Eve
    # opened the view and found Contract ID reading "Multiple values" while sales
    # from 8/14 were sitting right there.
    #
    # And "the control isn't on the view" is not proof either: on 8/13 our probe
    # found zero nodes carrying the field name and we concluded SCI had deleted
    # the filter, when it had only changed to a dropdown that renders its items
    # lazily. Hidden ≠ absent. So the only honest instruction is: go LOOK at the
    # filter.
    "capped": {
        "what": "Tableau pull",
        "headline": "🚨 *{report_id}* dropped {n} {what}{s} this run — {tail}",
        "tail_headline": "the export stopped short of today, so nothing was sent.",
        "label": "Missing",
        "fix": "check the *Contract ID* and *Account Id* filters on the view "
               "FIRST — they must read `(All)`. `Multiple values` means they're "
               "re-pinned to a stale ID snapshot, and then no sale newer than "
               "that snapshot enters the export no matter what date window we "
               "type; that is the usual cause and it looks identical to a dead "
               "feed from the dates alone. Probe it with `lucy rerun "
               "box_order_log_roshan --probe-filters`. Only if they really do "
               "read `(All)` is the source itself behind. Re-run `{report_id}` "
               "once a clean pull lands — the fill/merge is idempotent.",
        "tail": "No email/post went out — a gap beats numbers that undercount.",
        # The three BOX order logs share one incident key on purpose, so a reply
        # in this thread is usually a DIFFERENT OFFICE in the same run, not the
        # same one failing twice. The default ":repeat: Happened again · 2nd
        # time" said the wrong thing about it (Eve 2026-08-14). Each reply names
        # its own office, so the line above it only has to say "this one didn't
        # send either".
        "followup_stamp": ":heavy_plus_sign: *Also didn't send*",
    },
    # A STALE SOURCE (tableau_freshness) — NOT a report, and NOTHING DROPPED.
    # The freshness gate hangs off the shared crosstab download and never blocks
    # a run ("NEVER BREAKS A RUN" — its own docstring), so the report that
    # tripped it pulled, filled and sent exactly as usual; the only news is that
    # the data underneath is older than it should be.
    #
    # It borrowed 'capped' until 2026-08-19, and that wording was false in three
    # places at once (Eve, on the DirectDeposit/DDDETAIL thread): "so nothing was
    # sent" (it was sent), "check the Contract ID and Account Id filters … probe
    # with box_order_log_roshan --probe-filters" (that is the BOX view; a stale
    # source here can be any of ~120), and "re-run {report_id}" — the id names
    # the SOURCE, so no such command exists. Three dead ends before the reader
    # could find out nothing was broken.
    #
    # 'capped' still says all of that, correctly, where it belongs: a BOX pull
    # that really did refuse to send, and alert_unconfirmed_filter's pinned
    # filters.
    "stale_source": {
        "what": "Tableau source",
        "headline": "⚠️ *{report_id}* is serving data older than it should "
                    "be — {tail}",
        "tail_headline": "the report that pulled it ran and sent normally: "
                         "nothing dropped, nothing to re-run.",
        "label": "Source",
        "fix": "open the view in Tableau and see whether the day or week it's "
               "missing is actually there. If the view looks right, the feed "
               "behind it is genuinely behind and there is nothing on our side "
               "to change. Do not re-run `{report_id}` — that id is the SOURCE, "
               "not a report; the next pull takes whatever the view has by "
               "then.",
        "tail": "Anything already built on this pull is as old as the data was.",
        # ALWAYS thread. The channel line has to read as the small note it is;
        # the source path, the dates and a five-line fix underneath it turn a
        # "nothing is broken" alert into the biggest post of the morning.
        "thread_always": True,
        "see_thread": "Detail in the thread.",
        # Not "that dropped" — nothing dropped. That default header was the
        # fourth false sentence in the same alert.
        "detail_header": "*The {n} {what}{s} running behind:*",
        "fix_in_thread": True,
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
    # ONE ICD with no value on a run that filled EVERYTHING ELSE (kind
    # 'unfilled_icd' — captainship_cancel_rate today). Nothing dropped, nothing
    # is broken: every tab filled, every other owner filled, and one owner
    # simply had no number in the view. Most often that's honest no-data (the
    # owner has no sales left inside the rolling window, so there is no rate to
    # compute — a blank is the CORRECT answer, since no data != 0%); sometimes
    # it's a Tableau filter/alias worth a look.
    #
    # Megan 2026-08-15: "the alert on Melik just needs to say his is the only
    # one not filled so we know that's not a big deal / fail." Under the
    # 'section' fallback this went out as "🚨 dropped 1 section this run — it
    # did NOT post … re-run only the missing section … the thread is live but
    # incomplete" — incident language for a run that did its whole job, which is
    # exactly what sent the morning hunting a break that wasn't there. Same
    # lesson as 'finding' above, different shape: a finding says the SOURCE is
    # wrong; this says the source is fine and one cell is empty.
    #
    # The channel line is ONE line and names the owner(s) (thread_always +
    # {items}) — the reader should be able to close the tab without opening the
    # thread. Which tab/section and what to check live in the reply.
    "unfilled_icd": {
        "what": "ICD",
        "headline": "✅ *{report_id}* ran fine — every tab filled. "
                    "{n} {what}{s} didn't fill: {items}.",
        "tail_headline": "",          # unused: this headline carries itself
        "label": "Didn't fill",
        "thread_always": True,        # keep the channel to one skimmable line
        "fix_in_thread": True,        # ...and the what-to-check with it
        "see_thread": "Detail in thread.",
        "detail_header": "*The {n} {what}{s} that didn't fill:*",
        "fix": "usually nothing. An owner with no sales left inside the "
               "window has no rate to fill, so a blank is the right answer. If "
               "the same ICD stays blank for several days, check they're still "
               "on the view's filter, or add an alias if they were renamed "
               "(automations.focus_office_att.aliases.save_alias).",
        "tail": "Not a break and nothing to re-run — just worth an eye on the "
                "{what}{s} above.",
    },
}

# Manifest kinds that mean "a fill lost part of its work" — they read correctly
# under the 'section' wording, so they fall back on purpose. Anything ELSE that
# isn't listed in _KINDS is a kind nobody has worded yet: say so in the log
# rather than shipping it as "it did NOT post" (that silent aliasing is exactly
# how 'finding' went out wrong for a week).
# ('phase' used to be listed here as reading-fine-under-'section'. It didn't —
# see the 'phase' entry above — so it now owns its own wording.)
_FILL_SHAPED = {"part", "step", "report", "tracker", "week", "tab",
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
    # `items` lets a kind NAME what didn't land right in the headline, instead of
    # only counting it. A one-line "1 ICD didn't fill: Melik El Jaiez" is
    # readable without opening the thread, which is the whole point of a low-key
    # alert (Megan 2026-08-15). Kinds that don't use {items} are unaffected —
    # str.format ignores unused keys.
    fmt = dict(report_id=report_id, n=n, what=what, s=s,
               items=", ".join(failed))

    body = [f"*{spec['label']}:* {', '.join(failed)}"]
    if note and not spec.get("skip_note"):
        body.append(f"_{note}_")
    # A bulleted kind ALWAYS threads: its items are full sentences, and even one
    # of them fills the channel — which is the whole point of the split.
    # `thread_always` does the same for a kind whose headline already names the
    # items: repeating them inline underneath would just be the same line twice.
    threaded = (bool(spec.get("bullets")) or bool(spec.get("thread_always"))
                or n > _INLINE_ITEMS
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
    # `fix_in_thread` is the same call made up front by a kind that wants its
    # channel line to stay one line no matter how short the fix is.
    fix_threaded = threaded and (bool(spec.get("fix_in_thread"))
                                 or len(fix_line) > _INLINE_CHARS)
    if not fix_threaded:
        parent.append(fix_line)
    parent.append(spec["tail"].format(**fmt))
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


def _channel_line(report_id: str, failed, kind: str):
    """The one-line channel post: NAME what didn't land, don't count it.

    Megan 2026-08-18, looking at "*tableau-screenshots* — dropped 1 section this
    run": "alerts like this should just state what channel they didn't post in
    for the short explanation in the header — this one would just say precision
    management." The count is the least useful fact on the line; the reader's
    next question is always WHICH one, and for these kinds `failed` already
    holds the answer (a channel, an office, an ICD, a Tableau source).

    None → the caller falls back to alert_thread.headline's normal trimming:
    a bulleted kind's items are full sentences (never a label), and a list too
    long for one short line goes back to being a count."""
    spec = _KINDS.get(kind) or {}
    if spec.get("bullets"):
        return None
    items = ", ".join(failed)
    from automations.shared import alert_thread
    items = alert_thread.strip_emoji(items)
    if not items or len(items) > alert_thread.REASON_CHARS:
        return None
    return "*{}* — {}".format(report_id, items)


def _incident_key(report_id: str, kind: str) -> str:
    """Which incident thread this alert belongs to.

    A `finding` is NOT a drop: nothing failed, an audit merely found something.
    Filing it under `drop-` gave it an outage-family key, and the orchestrator's
    own finding post (`finding-<id>`) could never see it — on 2026-08-18 the
    vantura board audit posted the same two Stations findings twice in one
    morning, once from each layer. Same prefix + subject()'s finding namespace =
    one thread, whichever layer gets there first, and whichever id spelling it
    uses (this side has the dashed manifest id, notify.py the underscore
    registry one; subject() canonicalises both).

    `unfilled_icd` is the same shape one kind over — the run FILLED, one owner
    had no number — and notify.py reports those very ICDs as `finding-<id>`
    too. Keyed as `drop-` it sat in the outage namespace and 2026-08-21 the
    captainship cancel rate said "2 ICDs didn't fill" twice in one minute,
    once from each layer. Both nothing-failed kinds belong to the finding
    family."""
    return "{}-{}".format(
        "finding" if kind in ("finding", "unfilled_icd") else "drop", report_id)


def resolved(report_id: str, *, dry_run: bool = False) -> bool:
    """This report just ran CLEAN — say so in its open alert thread and close it.

    Called from run_manifest.write_manifest on any successful run, so a drop that
    fixes itself stops looking open the moment it's fixed instead of sitting in
    the channel until somebody asks (Eve 2026-08-14). Silent and free when there
    is no open incident: it reads a local index, not Slack. Never raises."""
    try:
        from automations.shared import incident_thread as _inc
        open_now = _inc.open_keys()
        # Whichever family this report's alert landed in — see _incident_key().
        key = next((k for k in (_incident_key(report_id, "finding"),
                                "drop-{}".format(report_id)) if k in open_now),
                   None)
        if key is None:
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
    if _muted(path):
        return True
    parent_lines, detail = _compose_parts(report_id, failed, remediation,
                                          note, kind)
    from automations.shared import alert_thread
    channel_line = _channel_line(report_id, failed, kind)
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
            posted = _inc.open_or_followup(key=_incident_key(report_id, kind),
                                           title=parent_lines[0],
                                           body=parent_lines[1:],
                                           channel_line=channel_line,
                                           details=detail, channel=CHANNEL,
                                           stamp=(_KINDS.get(kind) or {}).get(
                                               "followup_stamp"),
                                           label="*{}*".format(report_id),
                                           day=day, client=client)
        except Exception as e:  # noqa: BLE001
            print("  ⚠ incident thread unavailable ({}: {}) — posting "
                  "standalone".format(type(e).__name__, str(e)[:80]))
        if not posted:
            # Same shape as the incident path even when it's unavailable: one
            # emoji-free line in the channel, the whole alert in the thread
            # (Megan 2026-08-18).
            head = channel_line or alert_thread.headline(parent_lines[0],
                                                         parent_lines[1:])
            resp = client.chat_postMessage(channel=CHANNEL, text=head)
            ts = resp.get("ts")
            body = [] if alert_thread.same_story(head, parent_lines) \
                else list(parent_lines)
            replies = alert_thread.chunk(body + ([""] if body and detail else [])
                                         + list(detail))
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
