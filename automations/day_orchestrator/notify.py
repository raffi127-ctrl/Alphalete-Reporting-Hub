"""Notifications — the 7:30 checkpoint email, the final completion email, and the
immediate session-stale alert.

Channel is configurable (email | slack | both); default email. Email reuses the
EXISTING send path from scheduled_6_days_out.email_send (Gmail SMTP_SSL + app
password, from alphaletereporting@gmail.com) — we only build our own
EmailMessage (status tables instead of an inline PNG).

In --dry-run nothing is sent: the email is written to a .eml under output/ for
inspection, and Slack is printed.
"""
from __future__ import annotations

import datetime as dt
import re
import smtplib
import ssl
import tempfile
from email.message import EmailMessage
from pathlib import Path
from typing import List

from automations.day_orchestrator import state as st

REPO_ROOT = Path(__file__).resolve().parents[2]
EML_DIR = REPO_ROOT / "output" / "orchestrator_emails"

# Status → (emoji, human label) for grouping in the email.
_LABELS = {
    st.DONE: ("✅", "Fully ran"),
    st.INCOMPLETE: ("⚠️", "Ran but incomplete"),
    st.FAILED: ("❌", "Didn't run / failed"),
    st.MISSED_NOT_READY: ("⚠️", "Missed / never became ready"),
    st.BLOCKED_SESSION: ("🔒", "Blocked — ownerville session stale"),
    st.HALTED_FOR_FIX: ("🛑", "Manually halted for fix"),
    st.MANUAL_PENDING_UPLOAD: ("📭", "Manual — pending upload"),
    st.STILL_TRYING: ("🟡", "Still trying"),
    st.PENDING: ("⏳", "Waiting"),
    st.SKIPPED: ("➖", "Not scheduled today"),
}


# ---------------- public API ----------------

def _machine_prefix() -> str:
    """Label secondary runners (e.g. Lucy 2) in the subject so their summary is
    clearly distinct from Lucy 1's. Empty for Lucy 1 (the primary) — its
    subjects stay exactly as before."""
    try:
        from automations.day_orchestrator import registry
        m = registry.this_machine()
        return f"[{m}] " if m and m != registry.DEFAULT_MACHINE else ""
    except Exception:
        return ""


def send_checkpoint(cfg, ds, *, channel="email", dry_run=False):
    # Megan 2026-07-23: the end-of-day summary is DROPPED in favour of per-report
    # Slack posts — when the corrections channel is on, the checkpoint doesn't send.
    if _corrections_channel(cfg):
        return
    subj = f"{_machine_prefix()}Reports {_d(ds)} — 7:30 checkpoint · {_tally(ds)}"
    html, text = _build_body(cfg, ds, checkpoint=True)
    _dispatch(cfg, subj, html, text, channel, dry_run, tag="checkpoint")


def send_final(cfg, ds, *, channel="email", dry_run=False):
    # Summary dropped when the corrections channel is on (see send_checkpoint).
    if _corrections_channel(cfg):
        return
    subj = f"{_machine_prefix()}Reports {_d(ds)} — FINAL · {_tally(ds)}"
    html, text = _build_body(cfg, ds, checkpoint=False)
    _dispatch(cfg, subj, html, text, channel, dry_run, tag="final")


def send_session_alert(cfg, ds, reason, *, channel="email", dry_run=False):
    # NAME THE MACHINE (Megan 2026-08-23). This alert used to say "re-seed the
    # mini" no matter which runner raised it. With three machines that sends
    # whoever reads it to the wrong box: on 8/23 the alert fired at 04:00 from
    # LUCY 3 — whose brand-new holder had never been seeded — and pointed at the
    # mini, which was fine. It also called every cause "stale", though the two
    # cases need different hands: a session that EXPIRED (re-seed it) vs one that
    # never existed because the machine has no holder at all (install it first —
    # see install_session_holder_agent). Both blocked every report on that box.
    try:
        from automations.day_orchestrator import registry
        machine = registry.this_machine() or "this machine"
    except Exception:  # noqa: BLE001 — an alert must never die labelling itself
        machine = "this machine"
    never_seeded = "missing" in (reason or "").lower()
    what = "NEVER SEEDED" if never_seeded else "went STALE"
    fix = ("That machine has no warm ownerville session at all. If it has no "
           "session-holder agent yet, install one (`lucy rerun "
           f"install_session_holder_agent --machine \"{machine}\"`), then a human "
           "seeds it once in the holder's window — Screen Sharing is fine."
           if never_seeded else
           f"Log back in on {machine}'s session-holder window to re-seed it.")
    subj = f"⚠️ ownerville session {what.lower()} on {machine} ({_d(ds)})"
    text = (
        f"The day orchestrator on {machine} has no usable ownerville session "
        f"({what}).\n\n"
        f"Reason: {reason}\n\n"
        f"EVERY report on {machine} is PAUSED — the session check is machine-wide, "
        "so this is not limited to reports that touch ownerville. Nothing is being "
        f"written with a dead session.\n\n{fix}\n"
        "The orchestrator auto-resumes within one 25-min pass.\n\n"
        "This is a one-time alert; the 7:30 checkpoint and final summary follow "
        "separately."
    )
    # When the corrections channel is configured, this per-event alert becomes its
    # own Slack post so it can be worked in-thread — and the redundant email is
    # skipped (Megan 2026-07-23: move problem notifications to Slack).
    if _corrections_channel(cfg):
        title = f":lock: *ownerville session {what.lower()} on {machine}* — {_d(ds)}"
        body = [
            f"*What happened:* {reason}",
            "",
            f"*EVERY report on {machine} is paused* — the session check is "
            "machine-wide, so this is not just the ownerville reports. I won't "
            "write anything with a dead session.",
            "",
            f"*Fix:* {fix}",
            "",
            "_Reply in this thread once it's sorted and I'll pick back up._",
        ]
        if _post_corrections(cfg, title, body, dry_run, tag="session-alert"):
            return
        # Slack post failed (e.g. Lucy not a member of the private channel) — fall
        # through to email so the alert is never silently lost.
    html = f"<div style='font-family:Arial,sans-serif;font-size:14px'>{_esc(text).replace(chr(10), '<br>')}</div>"
    _dispatch(cfg, subj, html, text, channel, dry_run, tag="session-alert")


def send_standalone_alert(cfg, *, name, report_id, kind, status, when="", day="",
                          machine_label="Lucy 2", channel="email", dry_run=False):
    """Per-report problem alert for a STANDALONE report that isn't in the
    orchestrator loop (Lucy 2's launchd agents, summarized off the shared Hub
    Activity log by machine_digest) — so Lucy 2 gets the SAME per-problem Slack
    posts as Lucy 1 instead of a daily summary email (Megan 2026-07-25). No
    orchestrator ReportState / log tail here, so it carries what the Activity log
    knows (name, id, status, time) + a paste-to-Claude block. Same channel routing
    + email fallback as send_failure_alert. Returns True if delivered."""
    lbl = machine_label or "Lucy 2"
    if _corrections_channel(cfg):
        if kind == "MISSED":
            title = f":no_entry_sign: *{name}* — didn't run today on {lbl}"
            err = f"no run recorded today ({status})" + (f" · {when}" if when else "")
        elif kind == "NO_NEW":
            # Event-driven report with genuinely nothing to do — NOT a failure.
            # Megan 2026-08-01: say "no new emails", don't cry "didn't run".
            title = f":information_source: *{name}* — no new emails today on {lbl}"
            err = ("no new background-check emails came in, so there was nothing "
                   "to sync" + (f" · {when}" if when else ""))
        elif kind == "WAITING":
            # An approval-gated send phase: nothing is broken, the day's review
            # post just hasn't been ✅'d yet (Megan 2026-08-18).
            #
            # The phase is REGISTERED as "Captainship Reports — approved" (it is
            # the row the gate writes once approval lands), but a title reading
            # "— approved* — waiting for approval" says it was approved in the
            # same breath as saying it wasn't (Megan, same day). The gate's name
            # suffix comes off; the waiting clause is the whole story.
            shown = re.sub(r"\s*[—–-]+\s*approved\s*$", "", name,
                           flags=re.IGNORECASE).strip() or name
            title = f"*{shown}* — waiting for approval to send email"
            err = ("this phase runs itself the moment the day's review post "
                   "gets its approval checkmark — nothing to fix"
                   + (f" · {when}" if when else ""))
        elif kind == "INCOMPLETE":
            title = f":warning: *{name}* — ran partial on {lbl}"
            err = f"status \"{status}\"" + (f" · {when}" if when else "")
        elif kind == "STUCK":
            title = f":rotating_light: *{name}* — stuck, never finished on {lbl}"
            err = ("opened a live 'running' pill"
                   + (f" ({when})" if when else "")
                   + " and never closed — the run crashed, was killed, or hung "
                     "mid-run, so it produced no success/fail")
        else:
            title = f":x: *{name}* — didn't run clean on {lbl}"
            err = f"status \"{status}\"" + (f" · {when}" if when else "")
        parent = [f"{'*Status:*' if kind == 'NO_NEW' else '*Error:*'} {err}"]
        # The detail block is built FIRST (it used to be built after the parent
        # post) so the whole incident — parent, in-thread detail, and what a
        # repeat says — goes out in one incident_thread call.
        if kind == "MISSED":
            claude = (
                "===== PASTE THIS TO CLAUDE TO FIX =====\n"
                f"Report: \"{name}\" (report_id: {report_id})\n"
                f"Date: {day}\n"
                f"It NORMALLY runs today on {lbl} but produced NO run in the Hub "
                "Activity log. Check its LaunchAgent on that machine (loaded? "
                "last exit?), whether the machine was asleep, and its own log. "
                "Then re-run it from the Hub.\n"
                "===== END ====="
            )
            reply = [
                f"It usually runs on {lbl} but hasn't today.",
                "*To run it now:* open the report on the Hub and hit play (runs "
                f"from any machine), or trigger it its usual way on {lbl}.",
                "",
                "If it's stuck, paste this to Claude:",
                "```", claude, "```",
                "_Reply here and we'll sort it out in this thread._",
            ]
        elif kind == "NO_NEW":
            # Benign FYI — nothing broke, nothing to run. No paste-to-Claude.
            reply = [
                f"Nothing to sync today — no new background-check emails have "
                f"come in, so there's no update to write. This is normal on a "
                f"quiet day, not a miss.",
                "_If you were expecting results in and don't see them, reply "
                "here and we'll check._",
            ]
        elif kind == "WAITING":
            # Benign FYI — the gate is doing its job. No paste-to-Claude.
            # The APPROVER gets pinged (Megan 2026-08-18: "should also @eve
            # since she's the only one in the approval channel as of now") —
            # in the THREAD, so the channel line stays one plain line while the
            # mention still lights up her sidebar. The list comes from
            # review_gate.APPROVERS, the same dict that decides whose ✅ opens
            # the gate — one place to change when that ever stops being Eve.
            reply = [
                f"{_approver_mentions()} — this send is waiting on your "
                "approval checkmark on today's review post.",
                "The emails go out on their own as soon as it's approved — "
                "until then, holding is the correct behavior, not a miss.",
                "_If the approval WAS already given and this is still here an "
                "hour later, reply in this thread — then the checker itself "
                "needs a look._",
            ]
        else:
            claude = (
                "===== PASTE THIS TO CLAUDE TO FIX =====\n"
                f"Report: \"{name}\" (report_id: {report_id})\n"
                f"Date: {day}\n"
                f"Ran on: {lbl} (standalone launchd agent), status \"{status}\".\n"
                "This report runs on its OWN agent, not the day-orchestrator loop, "
                f"so its log is on {lbl} (not in output/logs on Lucy 1 unless {lbl} "
                "IS Lucy 1). Diagnose from that report's own log / last run and fix "
                "it in the repo; if it's a transient blip, just re-run it from the Hub.\n"
                "===== END ====="
            )
            reply = [
                f"This one runs standalone on {lbl} (not the 4am orchestrator flow).",
                "*To re-run it:* open the report on the Hub and hit play (runs from "
                f"any machine), or trigger it its usual way on {lbl}.",
                "",
                "If it keeps failing, paste this to Claude:",
                "```", claude, "```",
                "_Reply here and we'll correct it in this thread._",
            ]
        # NO_NEW is a benign FYI that recurs every quiet day; a real problem
        # recurs every day until it's fixed. Either way the repeat belongs in
        # the first message's thread, not as another channel post — but they're
        # SEPARATE incidents, so a quiet day never lands in the same thread as a
        # genuine miss (Eve 2026-08-14).
        key = (f"nonew-{report_id}" if kind == "NO_NEW"
               else f"standalone-{report_id}")
        # WAITING wears the purple circle — the same color the Hub's approval
        # pill uses (Megan 2026-08-18) — so the channel list reads at a glance:
        # purple = waiting on a human checkmark, :pending: = someone is on it,
        # ✅ = done. As a REACTION, never in the text.
        inc = _incident_post(cfg, key=key, title=title, body=parent,
                             details=reply, followup=[title] + parent,
                             label=f"*{name}* on {lbl}",
                             reaction=("large_purple_circle"
                                       if kind == "WAITING" else None),
                             dry_run=dry_run, tag=key)
        if inc:
            return True
        ts = _post_corrections(cfg, title, parent, dry_run,
                               tag=f"standalone-{report_id}")
        if ts:
            _post_corrections(cfg, "", reply, dry_run,
                              tag=f"standalone-{report_id}-details", thread_ts=ts)
            return True
        # fall through to email if the Slack post didn't land
    # Email fallback / non-Slack path.
    if kind == "NO_NEW":
        subj = f"ℹ️ [{lbl}] {name} — no new emails — {day}"
        text = (f"No new background-check emails came in on {lbl}, so there was "
                f"nothing to sync today.\n\nReport: {name} "
                f"(report_id: {report_id})\n"
                + (f"When: {when}\n" if when else ""))
    else:
        subj = f"⚠️ [{lbl}] {name} {kind} — {day}"
        text = (f"A {lbl} report didn't run clean.\n\nReport: {name} "
                f"(report_id: {report_id})\nStatus: {status}\n"
                + (f"When: {when}\n" if when else ""))
    html = ("<div style='font-family:Arial,sans-serif;font-size:14px'>"
            f"{_esc(text).replace(chr(10), '<br>')}</div>")
    _dispatch(cfg, subj, html, text, channel, dry_run, tag=f"standalone-{report_id}")
    return True


def send_failure_alert(cfg, ds, rs, *, channel="email", dry_run=False):
    """Fire the moment ONE report fails terminally — before the 7:30 checkpoint or
    the FINAL summary — so a broken report can be fixed while the batch is still
    running rather than discovered hours later (Megan 2026-07-20: #aeon-sales was
    short from 04:29 and nobody knew until she looked). Carries the SAME real-cause
    diagnosis + paste-to-Claude block the summary emails use, so it's actionable on
    its own. One per report per day (deduped by the caller via failure_alerts_sent).

    Returns {'ts', 'text'} for the Slack post it made (so the caller can later
    EDIT that same post into ✅ RESOLVED via resolve_failure_alert instead of
    posting a second message), or None when it fell back to email.
    """
    label = rs.display_name or rs.report_id
    if rs.status == "INCOMPLETE":
        kind = "INCOMPLETE"
    elif rs.status in ("MISSED_NOT_READY", "BLOCKED_SESSION"):
        kind = "MISSED"     # never ran / never became ready by the noon backstop
    else:
        kind = "FAILED"
    reason, needs_reseed, rerun = _diagnose(rs, cfg, _d(ds))
    subj = f"⚠️ {label} {kind} — {_d(ds)} (before the summary)"
    lines = [
        f"The day orchestrator recorded a {kind} report — flagging it now so it "
        "can be addressed before the 7:30 checkpoint and the final summary.",
        "",
        f"Report:  {label}  (report_id: {rs.report_id})",
        f"Status:  {kind}",
        f"Reason:  {reason}",
        f"Re-run:  {rerun}",
    ]
    if kind == "INCOMPLETE" and rs.missing:
        lines.append(f"Missing: {', '.join(rs.missing)}")
    if needs_reseed:
        lines += ["", "This one needs a one-time AppStream re-seed first:",
                  f"  {APPSTREAM_RESEED}"]
    lines += ["", _claude_block(rs, reason, cfg, _d(ds)), "",
              "The 7:30 checkpoint and final summary still follow separately; this "
              "is the early heads-up, not a replacement."]
    text = "\n".join(lines)
    # Corrections channel configured → this becomes its OWN Slack post (one per
    # problem report) so it can be worked in-thread, and the per-report email is
    # skipped to avoid double-notifying (Megan 2026-07-23). The daily summary is
    # unaffected — it still follows on its own channel.
    if _corrections_channel(cfg):
        post = _post_failure_corrections(cfg, ds, rs, kind, reason, needs_reseed,
                                         rerun, dry_run)
        if post:
            return post
        # Slack post failed (e.g. Lucy isn't a member of the private channel) — fall
        # through to email so a real problem is never silently lost.
    html = ("<div style='font-family:Arial,sans-serif;font-size:14px'>"
            f"{_esc(text).replace(chr(10), '<br>')}</div>")
    _dispatch(cfg, subj, html, text, channel, dry_run, tag=f"failure-{rs.report_id}")
    return None


def resolve_failure_alert(cfg, post, *, rs, now=None, dry_run=False) -> bool:
    """Announce the fix in the alert's OWN thread and edit the parent to ✅ RESOLVED.

    Eve 2026-08-14: "por favor publicar dentro del mismo hilo cuando algo se
    resolvió". An edit is silent for everyone who already read the alert, so the
    resolution now goes out as a reply in the incident's thread (one message,
    only to the people following it) AND edits the parent, which also CLOSES the
    incident — the next occurrence opens a fresh post instead of reviving this one.

    WHY THE EDIT (Eve 2026-08-13): several reports are DESIGNED to heal themselves later —
    b2b_metrics defers its order-log sections until the ORDERLOG extract lands and
    posts them on the 8:30 floor pass; the auto-retry recovers a transient miss on
    the next pass. The alert that fired at 05:00 stayed in the channel reading like
    open work, so the morning's real state had to be re-derived by hand ("didn't
    this already get fixed?"). Editing the original message means the channel
    always shows the CURRENT truth and — crucially — NO second message: an edit
    doesn't re-notify, so a healed problem costs zero extra noise.

    `post` is the {'ts','text'} send_failure_alert returned. Returns True when the
    message was updated. Best-effort: never raises into the batch."""
    ch = _corrections_channel(cfg)
    ts = (post or {}).get("ts")
    if not ch or not ts:
        return False
    label = rs.display_name or rs.report_id
    hhmm = (now or dt.datetime.now()).strftime("%H:%M")
    was = (post or {}).get("text") or ""
    # Drop the incident marker before striking the old text through — resolve()
    # writes a fresh one, and a struck-through marker is unparseable afterwards.
    was = "\n".join(l for l in was.splitlines()
                    if not l.startswith("_incident · ")).strip()
    # No emoji in the channel's own text (Megan 2026-08-18) — the ✅ that marks a
    # closed ticket is the REACTION incident_thread puts on the parent.
    lines = [f"*{label}* — RESOLVED {hhmm}. Nothing to do."]
    if rs.missing:
        lines.append(f"*Landed since:* {', '.join(rs.missing)}")
    if rs.last_reason:
        lines.append(f"_{rs.last_reason}_")

    # Say it IN THE THREAD, not only by editing the parent (Eve 2026-08-14):
    # anyone who read the alert earlier never sees an edit, so they keep working
    # a problem that's already fixed. The edit still happens — resolve() does it
    # — but the reply is the part people actually get.
    key = (post or {}).get("key") or f"failure-{rs.report_id}"
    thread_lines = list(lines) + [
        "_Closing this one out — if it happens again it'll open a fresh post._"]
    try:
        from automations.shared import incident_thread as _inc
        # No parent_text: incident_thread re-badges the parent's OWN one-line
        # headline with "· *RESOLVED* <date>" and reacts ✅. Handing it a
        # replacement block is what used to put the whole alert — struck through,
        # emoji and all — back into the channel.
        if _inc.resolve(key=key, lines=thread_lines, channel=ch,
                        dry_run=dry_run):
            return True
        if key not in _inc.open_keys():
            # Already closed — by this report's own clean run through
            # hub_publish, or by a sibling witness. There is nothing left to
            # announce, and the fallback edit below would strip the `_incident ·
            # … · resolved_` marker every other machine scans for (the 2026-08-17
            # b2b_metrics case, from the other direction).
            return True
    except Exception as e:  # noqa: BLE001 — fall back to the edit-only path
        print(f"[notify] incident resolve failed ({rs.report_id}): {e}", flush=True)

    if was:
        # Keep the original wording visible (struck through) so the history of the
        # morning is still readable — this REPLACES the alert, it doesn't hide it.
        lines += ["", "~" + was.replace("\n", "~\n~") + "~"]
    text = "\n".join(lines)
    if dry_run:
        print(f"[notify] DRY-RUN — would edit corrections post {ts} → {ch}:\n"
              f"{text}\n", flush=True)
        return True
    try:
        from automations.shared.slack_metrics_post import _client
        client = _client()
        client.chat_update(channel=ch, ts=ts, text=text)
        # This path bypasses incident_thread.resolve(), so nothing has put the
        # parent's reaction layer straight: it would read RESOLVED in the text
        # while still wearing the ⏳ somebody's re-run left on it, and with no ✅
        # in the channel list at all (Megan 2026-08-20). Best-effort — the edit
        # already landed and is the part that matters.
        try:
            from automations.shared import incident_thread as _inc
            _inc._react_done(client, ch, ts)
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001 — a failed edit must never sink the batch
        print(f"[notify] corrections edit failed ({rs.report_id}): {e}", flush=True)
        return False
    print(f"[notify] corrections post {ts} edited to RESOLVED "
          f"({rs.report_id})", flush=True)
    return True


def _manifest_id(cfg, rs) -> str:
    """The id this report's manifest is FILED under, which is not always its
    config key: schedule_config's `verify: {type: manifest, report_id: …}` may
    name a different one. vantura_board_audit is keyed with an underscore in the
    config but writes 'vantura-board-audit' (run.py REPORT_ID).

    reconcile.verify() already resolves it this way; anything reading a manifest
    off `rs.report_id` alone silently reads NOTHING for those reports and takes
    whatever the not-found branch does. That is how the Vantura audit's findings
    post kept coming out as the generic "ran, but 1 didn't fill" with a re-run
    block attached (2026-08-14) — _is_findings_report looked up the underscore
    key, got None, and fell through to the fill-report path every single day."""
    try:
        r = cfg.reports.get(rs.report_id)
        vid = (getattr(r, "verify", None) or {}).get("report_id")
        return vid or rs.report_id
    except Exception:  # noqa: BLE001
        return rs.report_id


# Manifest kinds whose INCOMPLETE is a FINDING, not a broken fill: the run did
# its whole job and is reporting something it noticed. They share the concise
# parent + in-thread detail and skip the re-run / paste-to-Claude block, but
# each owns its own words — a board audit saying "the source is wrong" and a
# fill saying "one owner had no number" are not the same news, and one wording
# for both is how the audit's findings went out as "it did NOT post" for a week.
_FINDING_KINDS = {
    "finding": {
        "title": "{n} open data-quality finding(s)",
        "parent": "*Found:* {n} board data-quality issue(s) — details in "
                  "thread. Logged to the board's ‘Report an Issue’ tab.",
        "detail_header": "*Open findings:*",
        "footer": "_These are fixed on the board itself (Roll Call statuses, "
                  "Stations formulas, etc.), not by re-running this audit — "
                  "they'll clear from this alert once the board is corrected._",
        "icon": ":warning:",
    },
    # captainship_cancel_rate: every tab filled, one owner had no number. Megan
    # 2026-08-15 — the reader must see at a glance that this is fine, so the
    # parent names the owner(s) and says everything else filled. Detail (which
    # tab/section, what to check) goes in the thread.
    "unfilled_icd": {
        "title": "ran fine, {n} ICD{s} didn't fill",
        "parent": "*Filled everything except:* {items}. Every other ICD on "
                  "every tab filled — not a break, nothing to re-run.",
        "detail_header": "*Didn't fill this run:*",
        "footer": "_Usually nothing to do: an owner with no sales left inside "
                  "that window has no rate to compute, so a blank is the "
                  "correct answer (no data is not 0%). Only worth checking the "
                  "Tableau view filter / alias if the SAME ICD stays blank for "
                  "several days._",
        "icon": ":white_check_mark:",
    },
}


def _finding_spec(cfg, rs):
    """The _FINDING_KINDS entry for this report's last manifest, or None when it
    is an ordinary fill report. Best-effort: any read problem falls back to the
    normal fill-report path (which is always safe, just louder)."""
    try:
        from automations.shared import run_manifest
        m = run_manifest.read_manifest(_manifest_id(cfg, rs))
        return _FINDING_KINDS.get((m or {}).get("kind"))
    except Exception:  # noqa: BLE001
        return None


def _is_findings_report(cfg, rs) -> bool:
    """True when this report's INCOMPLETE is a FINDING rather than a broken
    fill — its last manifest carries one of _FINDING_KINDS (the Vantura board
    audit's 'finding', the cancel-rate 'unfilled_icd'). Those runs report what
    they noticed, not what they lost: the channel post stays a one-line summary
    and the detail goes in-thread, with no re-run / paste-to-Claude block."""
    return _finding_spec(cfg, rs) is not None


def _post_findings_corrections(cfg, rs, label, dry_run, day=None):
    """A finding → a CONCISE parent (name + what it found, 'details in thread')
    and a threaded reply with the list. No re-run/paste-to-Claude: these are
    fixed at the source — or not a problem at all — and re-running changes
    nothing (Megan 2026-08-02, 2026-08-15). Wording comes off _FINDING_KINDS."""
    spec = _finding_spec(cfg, rs) or _FINDING_KINDS["finding"]
    n = len(rs.missing)
    fmt = {"n": n or "some", "s": "" if n == 1 else "s",
           "items": ", ".join(rs.missing) or "—"}
    title = f"{spec['icon']} *{label}* — " + spec["title"].format(**fmt)
    parent = [spec["parent"].format(**fmt)]
    reply = [spec["detail_header"]]
    reply += [f"   • {f}" for f in rs.missing]
    reply += [
        "",
        spec["footer"],
        "_Reply here if you want a hand._",
    ]
    # An audit re-reports the SAME open findings every single day until someone
    # fixes the board, so the repeat carries the current list in-thread — one
    # message a day in a thread instead of one post a day in the channel.
    followup = [title] + parent + [""] + [f"   • {f}" for f in rs.missing]
    inc = _incident_post(cfg, key=f"finding-{rs.report_id}", title=title,
                         body=parent, details=reply, followup=followup,
                         day=day, dry_run=dry_run, tag=f"finding-{rs.report_id}")
    if inc:
        return {"ts": inc["ts"], "text": inc.get("text") or "\n".join([title] + parent),
                "key": f"finding-{rs.report_id}", "new": inc.get("new", True)}
    ts = _post_corrections(cfg, title, parent, dry_run,
                           tag=f"finding-{rs.report_id}")
    if not ts:
        return None
    _post_corrections(cfg, "", reply, dry_run,
                      tag=f"finding-{rs.report_id}-details", thread_ts=ts)
    return {"ts": ts, "text": "\n".join([title] + parent),
            "key": f"finding-{rs.report_id}"}


def _post_failure_corrections(cfg, ds, rs, kind, reason, needs_reseed, rerun, dry_run):
    """One problem report → a concise PARENT post (report name + the error) plus a
    threaded REPLY that carries the details (what to re-run, which ICDs were left
    out, that everything else ran, and the paste-to-Claude fix block). Megan
    2026-07-23: the post itself is the name + error; the how-to-fix and the extras
    live in the thread so the channel skims clean and each fix happens in-thread.

    Returns {'ts', 'text'} of the PARENT post (None if it didn't go out) —
    resolve_failure_alert edits that exact message when the report later goes
    clean, so a fixed problem never keeps sitting in the channel as an open one."""
    label = rs.display_name or rs.report_id

    # A data-quality AUDIT (kind='finding' manifest) is a special case: its
    # "missing" items are full-sentence findings, not fill targets, and there's
    # nothing to re-run — a human fixes the board. Dumping every finding into the
    # channel makes a wall of text (Megan 2026-08-02: the Vantura board audit "is
    # too long in the channel"). Keep the PARENT to a one-line count and push the
    # finding text into the thread; skip the re-run / paste-to-Claude boilerplate.
    if kind == "INCOMPLETE" and _is_findings_report(cfg, rs):
        return _post_findings_corrections(cfg, rs, label, dry_run,
                                          day=_as_date(_d(ds)))

    # Split the missing units into TERMINATED (on the terminated-ICD list — should
    # be REMOVED from the report, a re-run won't help) vs LIVE (actually failed —
    # worth re-running). Megan 2026-07-23: tell us when a missing ICD is terminated
    # and needs pulling from the report.
    term_hits, live_units = _terminated_split(rs.missing) if kind == "INCOMPLETE" else ([], [])

    # PARENT — report name, then the error. The error NAMES the specific ICDs /
    # items that didn't fill (Megan 2026-07-23: say WHICH ICDs, not just "timeout").
    # A long missing-list is the single biggest channel-flooder, so the parent
    # names the COUNT and the reason and the list itself moves in-thread
    # (Megan 2026-08-13). Short lists still read inline — no extra click for a
    # two-ICD miss.
    long_missing = []
    if kind == "INCOMPLETE":
        n = len(rs.missing)
        title = f":warning: *{label}* — ran, but {n or 'some'} didn't fill"
        if rs.missing:
            joined = ", ".join(rs.missing)
            if n > 4 or len(joined) > 200:
                long_missing = list(rs.missing)
                err = f"Didn't fill: {n} item(s) — see thread for the list"
            else:
                err = f"Didn't fill: {joined}"
            if reason and reason not in ("INCOMPLETE",) and not reason.lower().startswith(
                    ("completed", "ran; ", "manifest")):
                err += f" — {reason}"
        else:
            err = reason
    elif kind == "MISSED":
        title = f":no_entry_sign: *{label}* — didn't run today"
        err = reason
    else:
        title = f":x: *{label}* — didn't finish"
        err = reason
        if rs.missing:  # a hard fail that still knows which parts were owed
            err = f"Didn't fill: {', '.join(rs.missing)} — {reason}"
    parent = [f"*Error:* {err}"]
    # High-visibility on the PARENT: a terminated ICD is an action Megan can take
    # herself right now (remove it) — surface it top-level, not buried in-thread.
    if term_hits:
        parent.append(":no_entry: *Terminated — remove from this report:* "
                      + ", ".join(_term_label(h) for h in term_hits))
    # REPLY — the details + the fix, threaded under the parent. Built BEFORE the
    # post so the whole incident (parent + detail + what a repeat says) goes to
    # incident_thread in one call.
    reply = []
    if long_missing:
        reply.append(f"*Didn't fill ({len(long_missing)}):*")
        reply += [f"   • {m}" for m in long_missing]
        reply.append("")
    if term_hits:
        reply.append("*These ICDs are on the terminated list — remove them from this "
                     "report* (a re-run won't fill them):")
        for h in term_hits:
            reply.append(f"   • {_term_label(h)}"
                         + (f" — {h['notes']}" if h.get("notes") else ""))
        reply.append("")
    if kind == "INCOMPLETE" and live_units:
        reply.append("*Everything else in this report ran fine* — only the item(s) "
                     "above are missing.")
        reply.append("")
    if needs_reseed:
        reply.append("*First, a one-time re-seed* (someone at the mini clears the "
                     "login check): `lucy reseed_appstream`")
    # Re-run ONLY the live (non-terminated) units. If every missing unit is
    # terminated, there's nothing to re-run — the fix is to remove them.
    rerun_cmd = _rerun_for(rs, cfg, units=live_units) if kind == "INCOMPLETE" else rerun
    if rerun_cmd:
        reply.append(f"*To re-run it:* `{rerun_cmd}`")
    elif term_hits:
        reply.append("*Nothing to re-run* — just remove the terminated ICD(s) above "
                     "from this report.")
    else:
        reply.append(f"*To re-run it:* `{rerun}`")
    reply.append("")
    reply.append("If a re-run won't fix it, paste this to Claude and it'll diagnose "
                 "+ fix the code:")
    reply.append("```")
    reply.append(_claude_block(rs, reason, cfg, _d(ds)))
    reply.append("```")
    reply.append("_Reply here and we'll correct it in this thread._")

    # A REPEAT of the same problem says what's different today (the error, the
    # re-run) and nothing else — the paste-to-Claude block is already upthread,
    # and re-posting it every day is what made this channel unreadable.
    followup = [title] + parent
    if long_missing:
        followup.append(f"*Didn't fill ({len(long_missing)}):* "
                        + ", ".join(long_missing))
    if rerun_cmd or rerun:
        followup.append(f"*To re-run it:* `{rerun_cmd or rerun}`")

    inc = _incident_post(cfg, key=f"failure-{rs.report_id}", title=title,
                         body=parent, details=reply, followup=followup,
                         label=f"*{label}*",
                         day=_as_date(_d(ds)), dry_run=dry_run,
                         tag=f"failure-{rs.report_id}")
    if inc:
        return {"ts": inc["ts"], "text": inc.get("text") or "\n".join([title] + parent),
                "key": f"failure-{rs.report_id}", "new": inc.get("new", True)}

    # incident_thread unavailable → the original two-message path, unchanged.
    ts = _post_corrections(cfg, title, parent, dry_run,
                           tag=f"failure-{rs.report_id}")
    if not ts:
        # Parent post didn't go out — don't orphan a reply; signal the caller to
        # fall back to email so the alert isn't lost.
        return None
    _post_corrections(cfg, "", reply, dry_run,
                      tag=f"failure-{rs.report_id}-details", thread_ts=ts)
    return {"ts": ts, "text": "\n".join([title] + parent),
            "key": f"failure-{rs.report_id}"}


# ---------------- failure diagnosis (real reason + copy-paste fix) ----------------
# Megan 2026-06-25: a failure that only says "exit 1, see log" + a bare module
# path is a back-and-forth, not a fix. Read the log tail for the ACTUAL cause and
# emit the EXACT terminal commands to correct it — paste once, data flows.

APPSTREAM_RESEED = ("PYTHONPATH=. .venv/bin/python -m "
                    "automations.shared.tableau_patchright --appstream-login")


def _runnable(report_id, cfg) -> str:
    """The fully-runnable re-run command (not a guess off the id)."""
    r = cfg.reports.get(report_id)
    if r and r.command:
        parts = list(r.command) + list(r.base_args)
        rest = "" if len(parts) == 1 else " " + " ".join(parts[1:])
        return "PYTHONPATH=. .venv/bin/python -m " + parts[0] + rest
    return f"PYTHONPATH=. .venv/bin/python -m automations.{report_id}.run"


def _log_tail(report_id, date, n: int = 60) -> str:
    try:
        p = REPO_ROOT / "output" / "logs" / f"orch-{date}-{report_id}.log"
        return "\n".join(p.read_text(errors="replace").splitlines()[-n:]).lower()
    except Exception:
        return ""


def _log_tail_raw(report_id, date, n: int = 40) -> str:
    """Last N log lines, ORIGINAL case (for the paste-to-Claude error tail —
    _log_tail lowercases for signature matching, which mangles tracebacks). N is
    generous so Claude sees the actual traceback, not just the final line (Megan
    2026-07-23: give Claude full context so there's minimal back-and-forth)."""
    try:
        p = REPO_ROOT / "output" / "logs" / f"orch-{date}-{report_id}.log"
        return "\n".join(p.read_text(errors="replace").splitlines()[-n:]).strip()
    except Exception:
        return ""


def _verify_source(cfg, report_id) -> str:
    """The Sheet/tab (or manifest unit) the verifier checks, spelled out for the
    Claude block so it knows WHERE the blank cells are — 'sheet <key> → tab <name>
    → anchors <labels>'. Best-effort: '' when the report has no sheet verifier."""
    try:
        r = cfg.reports.get(report_id)
        v = getattr(r, "verify", None) if r is not None else None
        if not isinstance(v, dict):
            return ""
        bits = []
        if v.get("sheet"):
            bits.append(f"sheet {v['sheet']}")
        if v.get("tab"):
            bits.append(f"tab {v['tab']!r}")
        labels = v.get("anchor_labels") or ([v["anchor_label"]] if v.get("anchor_label") else [])
        if labels:
            bits.append(f"anchor rows: {', '.join(labels)}")
        return " → ".join(bits)
    except Exception:  # noqa: BLE001
        return ""


def _claude_block(rs, reason, cfg, date) -> str:
    """Self-contained, FULL-CONTEXT block to paste into Claude so a 4am failure is
    one paste to fix — no back-and-forth (Megan 2026-06-25, expanded 2026-07-23).
    Carries the status, the EXACT cells/ICDs that didn't fill, where they live,
    what it was waiting on, both the scoped `lucy rerun` and the local runnable
    command, and a generous log tail."""
    status = "INCOMPLETE (ran but left cells blank)" if rs.status == "INCOMPLETE" else "FAILED (did not complete)"
    tail = _log_tail_raw(rs.report_id, date) or "(no log captured)"
    term_hits, live_units = _terminated_split(rs.missing) if rs.status == "INCOMPLETE" else ([], [])
    lines = [
        "===== PASTE THIS TO CLAUDE TO FIX =====",
        f"Report: \"{rs.display_name or rs.report_id}\" (report_id: {rs.report_id})",
        f"Date: {date}",
        f"Status: {status}",
        f"Likely cause: {reason}",
    ]
    if rs.missing:
        lines.append("Exactly what did NOT fill: " + "; ".join(rs.missing))
    if term_hits:
        # Tell Claude these are TERMINATED — the fix is to remove them from the
        # report's roster/source, NOT to make them populate.
        lines.append("On the terminated-ICD list — REMOVE these from the report "
                     "(do NOT try to make them fill): "
                     + "; ".join(_term_label(h) for h in term_hits))
    src = _verify_source(cfg, rs.report_id)
    if src:
        lines.append(f"These cells live in: {src}")
    if rs.waiting_on:
        lines.append(f"Was waiting on: {rs.waiting_on}")
    if rs.attempts:
        lines.append(f"Attempts today: {rs.attempts}")
    # Re-run only the LIVE units for an INCOMPLETE (terminated ones excluded).
    rerun = _rerun_for(rs, cfg, units=live_units) if rs.status == "INCOMPLETE" else _rerun_for(rs, cfg)
    if rerun:
        lines.append(f"Re-run (queues to the mini): {rerun}")
    lines += [
        f"Run locally to reproduce the whole report: {_runnable(rs.report_id, cfg)}",
        "Diagnose the root cause from the log tail below and fix it in the repo so "
        "the (non-terminated) missing cells populate; if it's a transient "
        "Tableau/network blip, just `lucy rerun` it. Full log tail:",
        tail,
        "===== END =====",
    ]
    return "\n".join(lines)


def _clean_unit(name: str) -> str:
    """The bare unit name for a scoped re-run command — strips the verifier's
    trailing annotation ('Marcellus Butler (blank in target column)' → 'Marcellus
    Butler') and a leading 'ICD: ' / 'program: ' label if a manifest used one."""
    s = str(name).strip()
    i = s.rfind(" (")
    if i > 0 and s.endswith(")"):
        s = s[:i].strip()
    for pre in ("ICD:", "program:", "owner:"):
        if s.lower().startswith(pre.lower()):
            s = s[len(pre):].strip()
    return s


def _terminated_split(missing):
    """Split a report's missing units into (terminated_hits, live_unit_names).
    terminated_hits are the units on the terminated-ICD list — dicts with
    report_name / date / notes — which should be REMOVED from the report (a re-run
    won't fill them); live_unit_names are the rest, worth a scoped re-run.
    Best-effort: on ANY error every unit is treated as live, so the terminated
    check can never suppress a real re-run or crash the alert."""
    units = [_clean_unit(m) for m in (missing or [])]
    units = [u for u in units if u]
    if not units:
        return [], []
    try:
        from automations.shared import terminated_icds as ti
        hits = ti.terminated_among(units)
    except Exception:  # noqa: BLE001 — advisory check, never fail the alert
        return [], units
    term_names = {h.get("report_name") for h in hits}
    live = [u for u in units if u not in term_names]
    return hits, live


def _term_label(h) -> str:
    """'Marcellus Butler (terminated 6/12)' for a terminated-ICD hit."""
    when = f" (terminated {h['date']})" if h.get("date") else " (terminated)"
    return f"{h.get('report_name', '')}{when}"


def _rerun_for(rs, cfg, units=None):
    """The re-run command for a problem report, most-surgical first:
      1) `scoped_rerun_cmd "Unit A" "Unit B"` — when the report declares one and we
         know exactly which named units are missing (Megan 2026-07-23: re-run only
         the missing owners, not the whole report). `units`, when passed, is the
         EXACT list to scope to (already terminated-filtered by the caller) — an
         empty list means nothing live to re-run, so this returns None.
      2) `lucy rerun <id> <retry_args>` — the report handed up manifest retry_args
         that scope to the failed parts (e.g. daily_metrics --only churn).
      3) `lucy rerun <id>` — whole report, when nothing narrower is known.
    """
    # A post-watch pseudo-report posts OUTSIDE the orchestrator (its own
    # LaunchAgent), so `lucy rerun` doesn't apply — surface the wrapper command
    # the watch target carries instead.
    try:
        from automations.day_orchestrator import post_watch as _pw
        if rs.report_id.endswith(_pw.WATCH_SUFFIX):
            hint = _pw.rerun_hint_for(rs.report_id)
            if hint:
                return hint
    except Exception:  # noqa: BLE001 — fall through to the generic path
        pass
    r = cfg.reports.get(rs.report_id)
    # 1) named-unit scoped command
    scoped = getattr(r, "scoped_rerun_cmd", None) if r is not None else None
    if scoped and (units is not None or rs.missing):
        use = units if units is not None else [_clean_unit(m) for m in rs.missing]
        use = [u for u in use if u]
        if use:
            return scoped + " " + " ".join(f'"{u}"' for u in use)
        if units is not None:
            return None   # caller passed an explicit (empty) live-unit list
    # 2) manifest retry_args (the failed-parts flags the report wrote)
    try:
        from automations.shared import run_manifest as _rm
        _vid = None
        if r is not None:
            _v = getattr(r, "verify", None)
            _vid = (_v or {}).get("report_id") if isinstance(_v, dict) else None
        for _mid in filter(None, (_vid, rs.report_id)):
            _spec = _rm.retry_spec(_mid)
            if _spec and _spec.get("retry_args"):
                return f"lucy rerun {rs.report_id} " + " ".join(_spec["retry_args"])
    except Exception:  # noqa: BLE001 — a scoped rerun is a nicety, never fail here
        pass
    # 3) whole report
    return f"lucy rerun {rs.report_id}"


def _diagnose(rs, cfg, date):
    """(human reason, needs_appstream_reseed, runnable re-run) for a failure."""
    rerun = _rerun_for(rs, cfg)
    low = _log_tail(rs.report_id, date)
    if ("appstream session expired" in low or "no live token" in low
            or "0 rqst token" in low):
        return ("ApplicantStream session expired — Cloudflare timed it out; "
                "needs a one-time re-seed (log in as rcaptain, clear the check), "
                "then re-run.", True, rerun)
    if ("invalid_grant" in low or "token has been expired" in low
            or "refresherror" in low):
        return ("Google auth token expired — re-auth, then re-run.", False, rerun)
    if "turnstile" in low or "ownerville session is stale" in low:
        return ("Ownerville session stale — re-seed it in the session-holder "
                "window on the mini, then re-run.", False, rerun)
    return (rs.last_reason or rs.status or "failed — see the log.", False, rerun)


# ---------------- body builders ----------------

# Timed com.alphalete.* jobs that are NOT "a report running later today": the 4am
# batch itself, its 3am pre-batch AppStream warmup, and the schedule guard.
_REMAINING_SKIP = {"day-orchestrator", "appstream-morning", "orchestrator-schedule-guard"}
# Friendly names for the later-today jobs (fallback: the label, Title-Cased).
_REMAINING_NAMES = {
    "weather-6am": "Weather Alert",
    "frontier-sunday-6pm": "Frontier OPT Data Pull",
    "texas-de-brazil-745": "Texas de Brazil Competition",
    "brand-audit-noon": "Brand Health Audit",
    "social-scanner": "Alphalete Social Media Posting",
    "board-catchup": "Org Sales Board — catch-up re-pull",
    "retail-catchup": "Retail — catch-up re-pull",
    "je-sunday-catchup": "JE — Sunday catch-up",
    "je-opt-monday-catchup": "JE OPT — Monday catch-up",
    "leaders-call-mon": "Leader's Call",
    "carlos-captainship-headcount-mon": "Carlos Captainship Headcount",
    "carlos-captainship-bonus-tue": "Carlos Captainship Bonus",
    "raf-captainship-bonus-tue": "Raf Captainship Bonus",
}


def _fmt_ampm(h: int, m: int) -> str:
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'} CST"


def _remaining_today(now):
    """Every report that still runs LATER today on its OWN launchd job (not the 4am
    batch) — derived from the ACTUAL installed timed jobs so the list is COMPLETE
    and can't drift from a hand-maintained field (Megan 2026-07-09: it was only ever
    listing the one report that happened to carry a runs_at). Returns [(name, time),
    …] for jobs whose next fire is later today, soonest first. Empty off-mini (no
    launchctl) — best-effort, never raises into the email build."""
    try:
        from automations.day_orchestrator import schedule_guard
        jobs = schedule_guard._timed_jobs()   # (label, name, entries)
    except Exception:  # noqa: BLE001
        return []
    iso = now.isoweekday()   # Mon=1 … Sun=7
    hits = []
    for _label, name, entries in jobs:
        if name in _REMAINING_SKIP:
            continue
        best = None
        for e in entries:
            wd = e.get("Weekday")
            # launchd Weekday: 0 or 7 = Sunday, 1=Mon … 6=Sat. Skip a weekly job
            # whose day isn't today.
            if wd is not None and wd != iso and not (wd in (0, 7) and iso == 7):
                continue
            try:
                fire = now.replace(hour=int(e.get("Hour", 0)),
                                   minute=int(e.get("Minute", 0)),
                                   second=0, microsecond=0)
            except Exception:  # noqa: BLE001
                continue
            if fire > now and (best is None or fire < best):
                best = fire
        if best:
            pretty = _REMAINING_NAMES.get(name, name.replace("-", " ").title())
            hits.append((best, pretty, _fmt_ampm(best.hour, best.minute)))
    hits.sort(key=lambda x: x[0])
    return [(p, t) for _dt, p, t in hits]


def _board_compare_section(ds):
    """Org Sales Board copy-vs-VA comparison breakdown → (html_chart, text).
    Best-effort: only when the board ran; reads both Sheet tabs; returns
    ('','') on any error so the summary email is never blocked. (2026-07-09,
    Megan: 'we should get a comparison breakdown chart there'.)"""
    rs = ds.reports.get("org_sales_board")
    if not rs or rs.status not in (st.DONE, st.INCOMPLETE):
        return "", ""
    try:
        from automations.org_sales_board import compare as _cmp
        d = _cmp.breakdown()
        att = d.get("attention", 0)
        tl = ["📊 Copy vs VA — " + (f"{att} difference(s) need a look:" if att
              else "in sync (only the automation running ahead of the VA).")]
        names = {"copy_missing": "copy missing", "behind": "behind VA",
                 "conflict": "value conflict"}
        for k, lbl in names.items():
            for rec in d.get(k, []):
                nm, cell, cv, vv = rec[0], rec[1], rec[2], rec[3]
                col = rec[4] if len(rec) > 4 else ""
                where = col or cell
                tl.append(f"   {lbl}: {nm} — {where} "
                          f"copy={cv or '(blank)'} VA={vv or '(blank)'}")
        for s in d.get("only_va", []):
            tl.append(f"   row only on VA: {s}")
        for s in d.get("only_copy", []):
            tl.append(f"   row only on copy: {s}")
        return _cmp.format_breakdown_html(d), "\n".join(tl)
    except Exception as e:  # noqa: BLE001 — never block the email on the compare
        return (f"<div style='font-size:12px;color:#999'>📊 Copy-vs-VA breakdown "
                f"unavailable ({_esc(str(e)[:80])}).</div>", "")


def _build_body(cfg, ds, *, checkpoint: bool):
    """Concise summary: what NEEDS ATTENTION (+ the fix) first, then one line of
    what ran clean. No verbose done-list / 'not scheduled' noise (Megan 2026-06-24)."""
    text: List[str] = []
    html: List[str] = ["<div style='font-family:Arial,sans-serif;color:#000'>"]

    head = "7:30 CHECKPOINT" if checkpoint else "FINAL SUMMARY"
    text.append(f"{head} — {ds.date}")
    text.append(_tally(ds))
    html.append(f"<h2>{head} — {ds.date}</h2>"
                f"<p style='color:#555'>{_tally(ds)}</p>")

    # 1) NEEDS ATTENTION — reports that FAILED (didn't run) + the exact re-run
    # command. INCOMPLETE reports actually RAN; they're shown separately below as
    # a note (not a failure), and kept OUT of the fix block — re-running won't
    # change a known exclusion like an owner who isn't in ownerville (Megan
    # 2026-06-26: "the daily rep breakdown 'fail' should be a note of a
    # successful report that left something out, and why").
    attention = [rs for s in (st.FAILED, st.MISSED_NOT_READY,
                              st.BLOCKED_SESSION) for rs in ds.by_status(s)]
    noted = ds.by_status(st.INCOMPLETE)
    if attention:
        text.append("")
        text.append(f"❌ NEEDS ATTENTION ({len(attention)}):")
        html.append(f"<h3 style='color:#c0392b'>❌ Needs attention ({len(attention)})</h3>"
                    "<ol style='font-size:14px;line-height:1.6'>")
        reruns, need_reseed, claude_blocks = [], False, []
        for rs in attention:
            name = rs.display_name or rs.report_id
            reason, reseed, rerun = _diagnose(rs, cfg, ds.date)
            if rs.missing:
                reason += " — missing: " + "; ".join(rs.missing)
            need_reseed = need_reseed or reseed
            reruns.append(rerun)
            claude_blocks.append(_claude_block(rs, reason, cfg, ds.date))
            text.append(f"  • {name} — {reason}")
            html.append(f"<li><b>{_esc(name)}</b> — {_esc(reason)}</li>")
        html.append("</ol>")
        # ONE copy-paste fix block: re-seed once if a session expired, then re-run
        # every failed report. Paste it in Terminal on the mini and it's corrected
        # — no log-digging, no back-and-forth (Megan 2026-06-25).
        # Copy-paste fix: one `lucy rerun <id>` per failed report. Runs from ANY
        # terminal — the `lucy` command queues it to the mini, which runs it
        # within ~2 min (check with `lucy status`). A session re-seed is the one
        # exception: it still needs a human AT the mini to clear the check.
        fix = []
        if need_reseed:
            fix.append("lucy reseed_appstream   # needs someone at the mini to clear the check")
        fix += reruns
        text.append("")
        text.append("FIX — paste in your Terminal:")
        for line in fix:
            text.append(f"    {line}")
        html.append("<div style='margin:8px 0 2px'><b>Fix — paste in your "
                    "Terminal:</b></div>"
                    "<pre style='background:#f4f4f4;padding:10px;border-radius:5px;"
                    "font-size:13px;white-space:pre-wrap;line-height:1.5'>"
                    f"{_esc(chr(10).join(fix))}</pre>")
        # If a re-run won't fix it (a real bug, not a transient), paste one of
        # these into Claude — same self-contained block as the Hub glitch emails.
        for blk in claude_blocks:
            text.append("")
            text.append(blk)
            html.append("<pre style='background:#f7f7f7;padding:10px;border-radius:5px;"
                        "font-size:12px;white-space:pre-wrap;line-height:1.45;"
                        "margin:8px 0'>" + _esc(blk) + "</pre>")
    # 1b) RAN — WITH A NOTE: INCOMPLETE reports completed successfully but left
    # something out for a known reason (e.g. an owner not in ownerville). NOT a
    # failure — no fix command; the note just says what was left out + why.
    if noted:
        text.append("")
        text.append(f"📝 RAN — WITH A NOTE ({len(noted)}):")
        html.append(f"<h3 style='color:#8a6d00'>📝 Ran — with a note ({len(noted)})</h3>"
                    "<ul style='font-size:14px;line-height:1.6'>")
        for rs in noted:
            nm = rs.display_name or rs.report_id
            why = rs.last_reason or "completed; some items left out"
            # Name the exact part(s) left out, not just the count. rs.missing is
            # the manifest's failed[] list (e.g. "program: Frontier") — the same
            # detail the ❌ attention block already appends. Without this the note
            # only said "1 part(s) missing this run." with no way to know which.
            if rs.missing:
                why += " — missing: " + "; ".join(rs.missing)
            text.append(f"  • {nm} — ran ✓; {why}")
            html.append(f"<li><b>{_esc(nm)}</b> — ran ✓; {_esc(why)}</li>")
        html.append("</ul>")
        text.append("   (no action needed — these ran; the note explains what was left out and why.)")
        html.append("<div style='font-size:13px;color:#777'>No action needed — these ran; "
                    "the note explains what was left out and why.</div>")

    if not attention and not noted and not checkpoint:
        text.append("")
        text.append("✅ Everything ran clean — nothing to do.")
        html.append("<h3 style='color:#1e7e34'>✅ Everything ran clean — nothing to do.</h3>")

    # 2) STILL TRYING (checkpoint only) + how to stop one.
    if checkpoint:
        still = ds.by_status(st.STILL_TRYING)
        if still:
            text.append("")
            text.append(f"🟡 STILL TRYING ({len(still)}):")
            html.append("<h3>🟡 Still trying</h3><ul style='font-size:14px'>")
            for rs in still:
                wait = rs.waiting_on or "data not ready"
                text.append(f"  • {rs.display_name or rs.report_id} — waiting on {wait}")
                html.append(f"<li><b>{_esc(rs.display_name or rs.report_id)}</b> — "
                            f"waiting on {_esc(wait)}</li>")
            html.append("</ul>")

    # 3) RAN CLEAN — one bullet per report, with its clean-run note (if any) inline
    # on the SAME line (Megan 2026-07-09: bulleted for readability + the detail on
    # the bullet, not a comma-list followed by a redundant per-report block).
    done = ds.by_status(st.DONE)
    if done:
        _GENERIC = {"", "manifest clean", "simulated"}
        text.append("")
        text.append(f"✅ Ran clean ({len(done)}):")
        html.append(f"<h3 style='color:#1e7e34'>✅ Ran clean ({len(done)})</h3>"
                    "<ul style='font-size:14px;line-height:1.6'>")
        for r in sorted(done, key=lambda x: (x.display_name or x.report_id)):
            nm = r.display_name or r.report_id
            note = r.last_reason if (r.last_reason and r.last_reason not in _GENERIC
                                     and not r.last_reason.startswith("ran; ")) else ""
            if note:
                text.append(f"  • {nm} — {note}")
                html.append(f"<li><b>{_esc(nm)}</b> — {_esc(note)}</li>")
            else:
                text.append(f"  • {nm}")
                html.append(f"<li><b>{_esc(nm)}</b></li>")
        html.append("</ul>")

    # 4) REMAINING — every report that still runs LATER today on its OWN launchd job
    # (derived from the installed timed jobs so the list is COMPLETE, not just the
    # one report that happened to carry a runs_at field — Megan 2026-07-09).
    remaining = _remaining_today(dt.datetime.now())
    if remaining:
        text.append("")
        text.append(f"🕐 REMAINING ({len(remaining)}) — runs later today:")
        html.append("<h3 style='color:#8a6d3b'>🕐 Remaining — runs later today</h3>"
                    "<ul style='font-size:14px'>")
        for name, when in remaining:
            text.append(f"  • {name} — {when}")
            html.append(f"<li><b>{_esc(name)}</b> — {_esc(when)}</li>")
        html.append("</ul>")

    # 5) ORG SALES BOARD — copy-vs-VA comparison breakdown: RETIRED 2026-07-21
    # (Megan). The VA tab is no longer being hand-filled and Eve now verifies the
    # automation directly, so this section only produced false "missed pull"
    # rows off the bottom leaderboard/history tables. _board_compare_section is
    # left defined but no longer called.

    html.append("</div>")
    return "".join(html), "\n".join(text)


def _rerun_cmd(report_id, cfg):
    """The REAL re-run command from the registry (module + args) — not a guess
    off the report id (which often isn't the module path)."""
    r = cfg.reports.get(report_id)
    if r and r.command:
        parts = list(r.command) + list(r.base_args)
        rest = "" if len(parts) == 1 else " " + " ".join(parts[1:])
        return "python -m " + parts[0] + rest
    return f"python -m automations.{report_id}.run"


# ---------------- corrections Slack channel (per-report problem posts) ----------------
# Megan 2026-07-23: instead of ONE end-of-day summary email, post each problem
# report as its OWN top-level message in #claudecorrections-and-requests so the
# team — and Megan, who is non-technical — can reply in-thread and work the fix.
# Posts go out AS Lucy (the automated-reports identity added to the channel).
# Gated entirely by the `corrections_slack_channel` setting: unset = behaviour is
# exactly as before (per-report failure EMAILS), so nothing changes until it's on.

# Sidecar cache for the resolved numeric channel id. Posting by "#name" works for
# the first send (the user token is a member), and chat.postMessage returns the
# real id — we cache it here so later posts don't depend on name resolution (a
# private channel needs the id). Kept out of schedule_config.json to avoid racing
# the running orchestrator on that 160KB file.
_CHANNEL_ID_CACHE = REPO_ROOT / "output" / ".corrections_channel_id"


def _corrections_channel(cfg):
    """The corrections channel to post problem reports to — the cached numeric id
    if we've resolved one, else the configured id/'#name'. None when unset, in
    which case corrections posting is skipped and the old email path is used."""
    try:
        cached = _CHANNEL_ID_CACHE.read_text().strip()
        if cached:
            return cached
    except Exception:  # noqa: BLE001 — no cache yet is normal
        pass
    return (cfg.settings.get("corrections_slack_channel") or "").strip() or None


def _as_date(value):
    """ds.date ('2026-08-14') as a date, or None. The incident stamp should say
    the day the RUN is for, not the day the process happens to be running (a
    backfill or a post-midnight pass would otherwise mislabel itself)."""
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except Exception:  # noqa: BLE001
        return None


def _approver_mentions() -> str:
    """Real <@id> mentions for whoever's checkmark opens the approval gates.

    Canonical list = captainship_drafts.review_gate.APPROVERS — the dict whose
    ✅ actually releases the send, so pinging and permission can't drift apart.
    Best-effort import with Eve pinned as the fallback: as of 2026-08-18 she is
    the only approver in the channel (Megan), and a WAITING alert that pings
    nobody just sits there."""
    try:
        from automations.captainship_drafts.review_gate import _mentions
        return _mentions() or "<@U088E2KJEV8>"
    except Exception:  # noqa: BLE001
        return "<@U088E2KJEV8>"


def _incident_post(cfg, *, key, title, body, details=None, followup=None,
                   day=None, dry_run=False, tag="", label="", reaction=None):
    """Post a problem as an INCIDENT: the first time it opens a top-level message,
    every repeat replies in that message's thread instead of adding another post
    (Eve 2026-08-14 — the channel had a new near-identical message per report per
    day and had stopped being readable). Length/chunking is handled inside
    incident_thread by the same alert_thread helpers _post_corrections uses.

    Returns the incident dict ({'ts','new',...}) or None, in which case the caller
    posts the old way — a de-noising feature must never cost us an alert."""
    ch = _corrections_channel(cfg)
    if not ch:
        return None
    try:
        from automations.shared import incident_thread as _inc
        return _inc.open_or_followup(key=key, title=title, body=body,
                                     details=details, followup=followup,
                                     label=label, channel=ch, day=day,
                                     reaction=reaction, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001 — fall back to a plain post
        print(f"[notify] incident post failed ({tag or key}): {e}", flush=True)
        return None


def _post_one(ch, text, dry_run, *, tag, thread_ts=None):
    """Send exactly one message (or print it on a dry run) and return its ts."""
    if dry_run:
        where = f"reply→{thread_ts}" if thread_ts else "NEW POST"
        print(f"[notify] DRY-RUN — corrections {where} ({tag}) → {ch}:\n{text}\n",
              flush=True)
        return "dry-run-ts"
    try:
        from automations.shared.slack_metrics_post import _client
        kw = dict(channel=ch, text=text, unfurl_links=False, unfurl_media=False)
        if thread_ts:
            kw["thread_ts"] = thread_ts
        resp = _client().chat_postMessage(**kw)
        # Persist the resolved numeric id the first time we post by name.
        cid = resp.get("channel")
        if cid and cid != ch:
            try:
                _CHANNEL_ID_CACHE.parent.mkdir(parents=True, exist_ok=True)
                _CHANNEL_ID_CACHE.write_text(cid)
            except Exception:  # noqa: BLE001
                pass
        print(f"[notify] posted corrections ({tag}) to {resp.get('channel')}"
              f"{' (reply)' if thread_ts else ''}", flush=True)
        return resp.get("ts")
    except Exception as e:  # noqa: BLE001 — an alert that sinks the batch is worse
        print(f"[notify] corrections post failed ({tag}): {e}", flush=True)
        return None


def _post_corrections(cfg, title, body_lines, dry_run, *, tag, thread_ts=None):
    """Post to the corrections channel and return the ts of the message a caller
    can thread under. thread_ts posts as a reply instead of a new top-level
    message. Best-effort: a Slack failure is logged, never raised into the batch;
    returns None on skip/failure.

    LENGTH IS HANDLED HERE so no caller has to think about it (Megan 2026-08-13:
    "this error is too long in the slack channel — it should be in the reply on
    the thread"; 2026-08-18: "three to five words of why it failed, and the rest
    in the response to the thread"). A new top-level post is ONE emoji-free line
    — what broke and a few words on why — and everything else goes to threaded
    replies, chunked under Slack's per-message limit rather than truncated: the
    whole alert still arrives, it just stops owning the channel."""
    ch = _corrections_channel(cfg)
    if not ch:
        return None
    from automations.shared import alert_thread
    lines = ([title] if title else []) + list(body_lines)

    # Already a reply: nothing to split off, only chunk if it's over the limit.
    if thread_ts:
        first = None
        for msg in alert_thread.chunk(lines) or [""]:
            ts = _post_one(ch, msg, dry_run, tag=tag, thread_ts=thread_ts)
            first = first or ts
        return first

    # ONE PLAIN LINE IN THE CHANNEL (Megan 2026-08-18) — the same rule
    # incident_thread applies, so an alert reads the same however it got posted:
    # `*What broke* — a few words on why`, no emoji, and the whole text (headline
    # included) in the thread. The emoji people SEE on these posts are the ✅ and
    # :pending: reactions they triage with; text emoji drown those out.
    head = alert_thread.headline(lines[0], lines[1:])
    detail = [] if alert_thread.same_story(head, lines) else list(lines)
    ts = _post_one(ch, head, dry_run, tag=tag)
    if ts and detail:
        for msg in alert_thread.chunk(detail):
            _post_one(ch, msg, dry_run, tag=f"{tag}-detail", thread_ts=ts)
    elif detail and not ts:
        # Parent never landed — don't silently drop the body; the caller falls
        # back to email on a None return, which carries the full text.
        print(f"[notify] corrections detail not posted ({tag}): no parent ts",
              flush=True)
    return ts


def post_alert(title, body_lines, *, tag, dry_run=False, cfg=None,
               incident=None, label=""):
    """Public one-shot alert into #claudecorrections-and-requests, for a REPORT
    module that hits a problem the orchestrator can't see from the outside — e.g.
    the country trackers holding a board because its Tableau extract is stale.
    Megan's standing rule: every fail / glitch / missed part goes to that channel
    in real time, not into a log nobody reads.

    Loads the orchestrator config itself so a caller doesn't have to. Silent
    no-op when the corrections channel isn't configured, and best-effort like
    every other post here — an alert must never sink the run it is describing.

    `incident` opts into thread-per-problem: pass a stable key (e.g.
    "country-extract-stale") and the SAME problem tomorrow replies under today's
    post instead of adding another one. Close it with
    incident_thread.resolve(key=…) when the condition clears. Omit it and the
    behaviour is exactly as before — a fresh post every time.

    `label` is the human name of what's failing ("BOX Order Log — Roshan"): it's
    what the reply says when this alert joins a thread another witness (or another
    office of the same report) already opened."""
    if cfg is None:
        try:
            from automations.day_orchestrator import registry
            cfg = registry.load_config()
        except Exception as e:  # noqa: BLE001 — no config, no alert; never raise
            print(f"[notify] alert skipped ({tag}): cannot load config ({e})",
                  flush=True)
            return None
    if incident:
        inc = _incident_post(cfg, key=incident, title=title, body=body_lines,
                             dry_run=dry_run, tag=tag, label=label)
        if inc:
            return inc.get("ts")
    return _post_corrections(cfg, title, body_lines, dry_run, tag=tag)


# ---------------- dispatch ----------------

def _dispatch(cfg, subject, html, text, channel, dry_run, *, tag):
    recipients = cfg.settings.get("recipients", [])
    if channel in ("email", "both"):
        _send_email(subject, html, text, recipients, dry_run, tag)
    if channel in ("slack", "both"):
        _send_slack(subject, text, dry_run)


def _send_email(subject, html, text, recipients, dry_run, tag):
    from automations.scheduled_6_days_out.email_send import (
        FROM_ADDR, SMTP_HOST, SMTP_PORT, app_password)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(recipients)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    if dry_run:
        EML_DIR.mkdir(parents=True, exist_ok=True)
        eml = EML_DIR / f"{tag}-{dt.date.today().isoformat()}.eml"
        eml.write_bytes(bytes(msg))
        print(f"[notify] DRY-RUN — {tag} email written to {eml} "
              f"(would send to {', '.join(recipients)})", flush=True)
        return
    pw = app_password()
    # Use certifi's CA bundle so TLS verification works even on Python.org
    # builds that can't see the system root certs (verified failure mode on a
    # 3.14 install 2026-06-23 — the mini may be the same).
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
        s.login(FROM_ADDR, pw)
        s.send_message(msg)
    print(f"[notify] sent {tag} email to {', '.join(recipients)}", flush=True)


def _send_slack(subject, text, dry_run):
    body = f"*{subject}*\n```{text}```"
    if dry_run:
        print(f"[notify] DRY-RUN — would Slack-post:\n{body}", flush=True)
        return
    try:
        from automations.shared.slack_metrics_post import _client, CHANNEL_ID
        _client().chat_postMessage(channel=CHANNEL_ID, text=body)
        print("[notify] posted summary to Slack", flush=True)
    except Exception as e:
        print(f"[notify] Slack post failed: {e}", flush=True)


# ---------------- helpers ----------------

def _d(ds):
    return ds.date


def _tally(ds):
    done = len(ds.by_status(st.DONE))
    inc = len(ds.by_status(st.INCOMPLETE))
    fail = len(ds.by_status(st.FAILED))
    missed = len(ds.by_status(st.MISSED_NOT_READY, st.BLOCKED_SESSION))
    trying = len(ds.by_status(st.STILL_TRYING, st.PENDING))
    parts = [f"{done} done"]
    if inc:
        parts.append(f"{inc} with a note")
    if fail:
        parts.append(f"{fail} failed")
    if missed:
        parts.append(f"{missed} missed")
    if trying:
        parts.append(f"{trying} still trying")
    return " · ".join(parts)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
