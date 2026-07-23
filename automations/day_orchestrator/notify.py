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
    subj = f"⚠️ ownerville session stale — re-seed the mini ({_d(ds)})"
    text = (
        "The day orchestrator detected a STALE ownerville session.\n\n"
        f"Reason: {reason}\n\n"
        "Today's Tableau reports are PAUSED (fail-closed — nothing is being written "
        "with a dead session). Log back in on the mini's session-holder window to "
        "re-seed; the orchestrator auto-resumes within one 25-min pass.\n\n"
        "This is a one-time alert; the 7:30 checkpoint and final summary follow "
        "separately."
    )
    # When the corrections channel is configured, this per-event alert becomes its
    # own Slack post so it can be worked in-thread — and the redundant email is
    # skipped (Megan 2026-07-23: move problem notifications to Slack).
    if _corrections_channel(cfg):
        title = f":lock: *ownerville session went stale* — {_d(ds)}"
        body = [
            f"*What happened:* {reason}",
            "",
            "Today's Tableau reports are *paused* on purpose — I won't write anything "
            "with a dead session. Someone at the mini logs back in on the "
            "session-holder window to re-seed it, and I auto-resume within one pass.",
            "",
            "_Reply in this thread once it's re-seeded and I'll pick back up._",
        ]
        _post_corrections(cfg, title, body, dry_run, tag="session-alert")
        return
    html = f"<div style='font-family:Arial,sans-serif;font-size:14px'>{_esc(text).replace(chr(10), '<br>')}</div>"
    _dispatch(cfg, subj, html, text, channel, dry_run, tag="session-alert")


def send_failure_alert(cfg, ds, rs, *, channel="email", dry_run=False):
    """Fire the moment ONE report fails terminally — before the 7:30 checkpoint or
    the FINAL summary — so a broken report can be fixed while the batch is still
    running rather than discovered hours later (Megan 2026-07-20: #aeon-sales was
    short from 04:29 and nobody knew until she looked). Carries the SAME real-cause
    diagnosis + paste-to-Claude block the summary emails use, so it's actionable on
    its own. One per report per day (deduped by the caller via failure_alerts_sent).
    """
    label = rs.display_name or rs.report_id
    kind = "INCOMPLETE" if rs.status == "INCOMPLETE" else "FAILED"
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
        _post_failure_corrections(cfg, ds, rs, kind, reason, needs_reseed, rerun, dry_run)
        return
    html = ("<div style='font-family:Arial,sans-serif;font-size:14px'>"
            f"{_esc(text).replace(chr(10), '<br>')}</div>")
    _dispatch(cfg, subj, html, text, channel, dry_run, tag=f"failure-{rs.report_id}")


def _post_failure_corrections(cfg, ds, rs, kind, reason, needs_reseed, rerun, dry_run):
    """One problem report → a concise PARENT post (report name + the error) plus a
    threaded REPLY that carries the details (what to re-run, which ICDs were left
    out, that everything else ran, and the paste-to-Claude fix block). Megan
    2026-07-23: the post itself is the name + error; the how-to-fix and the extras
    live in the thread so the channel skims clean and each fix happens in-thread."""
    label = rs.display_name or rs.report_id
    # Split the missing units into TERMINATED (on the terminated-ICD list — should
    # be REMOVED from the report, a re-run won't help) vs LIVE (actually failed —
    # worth re-running). Megan 2026-07-23: tell us when a missing ICD is terminated
    # and needs pulling from the report.
    term_hits, live_units = _terminated_split(rs.missing) if kind == "INCOMPLETE" else ([], [])

    # PARENT — report name, then the error. The error NAMES the specific ICDs /
    # items that didn't fill (Megan 2026-07-23: say WHICH ICDs, not just "timeout").
    if kind == "INCOMPLETE":
        n = len(rs.missing)
        title = f":warning: *{label}* — ran, but {n or 'some'} didn't fill"
        if rs.missing:
            err = f"Didn't fill: {', '.join(rs.missing)}"
            if reason and reason not in ("INCOMPLETE",) and not reason.lower().startswith(
                    ("completed", "ran; ", "manifest")):
                err += f" — {reason}"
        else:
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
    ts = _post_corrections(cfg, title, parent, dry_run,
                           tag=f"failure-{rs.report_id}")

    # REPLY — the details + the fix, threaded under the parent.
    reply = []
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
    _post_corrections(cfg, "", reply, dry_run,
                      tag=f"failure-{rs.report_id}-details", thread_ts=ts)


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


def _post_corrections(cfg, title, body_lines, dry_run, *, tag, thread_ts=None):
    """Post ONE message to the corrections channel and return its ts (so a caller
    can thread replies under it). thread_ts posts as a reply instead of a new
    top-level message. Best-effort: a Slack failure is logged, never raised into
    the batch; returns None on skip/failure."""
    ch = _corrections_channel(cfg)
    if not ch:
        return None
    text = "\n".join(([title] if title else []) + list(body_lines))
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
