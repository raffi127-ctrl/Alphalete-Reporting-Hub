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

def send_checkpoint(cfg, ds, *, channel="email", dry_run=False):
    subj = f"Reports {_d(ds)} — 7:30 checkpoint · {_tally(ds)}"
    html, text = _build_body(cfg, ds, checkpoint=True)
    _dispatch(cfg, subj, html, text, channel, dry_run, tag="checkpoint")


def send_final(cfg, ds, *, channel="email", dry_run=False):
    subj = f"Reports {_d(ds)} — FINAL · {_tally(ds)}"
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
    html = f"<div style='font-family:Arial,sans-serif;font-size:14px'>{_esc(text).replace(chr(10), '<br>')}</div>"
    _dispatch(cfg, subj, html, text, channel, dry_run, tag="session-alert")


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


def _log_tail_raw(report_id, date, n: int = 12) -> str:
    """Last N log lines, ORIGINAL case (for the paste-to-Claude error tail —
    _log_tail lowercases for signature matching, which mangles tracebacks)."""
    try:
        p = REPO_ROOT / "output" / "logs" / f"orch-{date}-{report_id}.log"
        return "\n".join(p.read_text(errors="replace").splitlines()[-n:]).strip()
    except Exception:
        return ""


def _claude_block(rs, reason, cfg, date) -> str:
    """Self-contained block to paste into Claude — same as the Hub glitch
    emails, so any 4am failure is one paste to fix (no back-and-forth)."""
    tail = _log_tail_raw(rs.report_id, date) or "(no log captured)"
    return (
        "===== PASTE THIS TO CLAUDE TO FIX =====\n"
        f"The report \"{rs.display_name or rs.report_id}\" (report_id: "
        f"{rs.report_id}) failed on the mini's automated run.\n"
        f"Re-run command: lucy rerun {rs.report_id}\n"
        f"Likely cause: {reason}\n"
        "Diagnose the root cause from the error below and fix it in the repo; "
        "if it's a transient Tableau/network blip, just `lucy rerun` it. "
        "Error tail:\n"
        f"{tail}\n"
        "===== END ====="
    )


def _diagnose(rs, cfg, date):
    """(human reason, needs_appstream_reseed, runnable re-run) for a failure."""
    rerun = f"lucy rerun {rs.report_id}"
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
            text.append(f"  (reply with subject  STOP {still[0].report_id}  to drop one from the loop)")
            html.append("<div style='font-size:13px;color:#777'>Reply with subject "
                        "<code>STOP &lt;report_id&gt;</code> to drop one from the loop.</div>")

    # 3) RAN CLEAN — compact one-liner, no per-report bullets.
    done = ds.by_status(st.DONE)
    if done:
        names = ", ".join(sorted(r.display_name or r.report_id for r in done))
        text.append("")
        text.append(f"✅ Ran clean ({len(done)}): {names}")
        html.append(f"<p style='font-size:13px;color:#555'>✅ <b>Ran clean ({len(done)}):</b> "
                    f"{_esc(names)}</p>")
        # Per-report clean-run detail — shown ONLY when the report attached a
        # note to its clean manifest (e.g. Financial records which workbooks it
        # pulled + how many tabs they filled). Reports without a note add
        # nothing, so the compact one-liner above stays compact for everything
        # else.
        _GENERIC = {"", "manifest clean", "simulated"}
        detailed = [r for r in done
                    if r.last_reason and r.last_reason not in _GENERIC
                    and not r.last_reason.startswith("ran; ")]
        for r in sorted(detailed, key=lambda x: (x.display_name or x.report_id)):
            nm = r.display_name or r.report_id
            text.append(f"   📄 {nm}: {r.last_reason}")
            html.append("<div style='font-size:12px;color:#777;margin-left:14px'>"
                        f"📄 <b>{_esc(nm)}</b>: {_esc(r.last_reason)}</div>")

    # 4) REMAINING — reports that run on their OWN job later today (e.g. the noon
    # brand audit). They never gate this email; we just note they're still coming.
    remaining = [(rid, r) for rid, r in (cfg.raw.get("reports", {}) or {}).items()
                 if not r.get("on_scheduler", False) and r.get("runs_at")]
    if remaining:
        text.append("")
        text.append(f"🕐 REMAINING ({len(remaining)}) — runs later today:")
        html.append("<h3 style='color:#8a6d3b'>🕐 Remaining — runs later today</h3>"
                    "<ul style='font-size:14px'>")
        for rid, r in remaining:
            name = r.get("display_name", rid)
            when = r.get("runs_at", "")
            text.append(f"  • {name} — scheduled to run at {when}")
            html.append(f"<li><b>{_esc(name)}</b> — scheduled to run at {_esc(when)}</li>")
        html.append("</ul>")

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
