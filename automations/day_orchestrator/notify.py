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
    html, text = _build_body(ds, checkpoint=True)
    _dispatch(cfg, subj, html, text, channel, dry_run, tag="checkpoint")


def send_final(cfg, ds, *, channel="email", dry_run=False):
    subj = f"Reports {_d(ds)} — FINAL · {_tally(ds)}"
    html, text = _build_body(ds, checkpoint=False)
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


# ---------------- body builders ----------------

def _build_body(ds, *, checkpoint: bool):
    groups_order = ([st.DONE, st.FAILED, st.MISSED_NOT_READY, st.BLOCKED_SESSION,
                     st.INCOMPLETE, st.STILL_TRYING, st.HALTED_FOR_FIX,
                     st.MANUAL_PENDING_UPLOAD, st.PENDING, st.SKIPPED])
    by_status = {s: [] for s in groups_order}
    for rs in ds.reports.values():
        by_status.setdefault(rs.status, []).append(rs)

    text_lines: List[str] = []
    html_parts: List[str] = []

    head = "7:30 CHECKPOINT" if checkpoint else "FINAL SUMMARY"
    text_lines.append(f"{head} — {ds.date} ({_tally(ds)})")
    html_parts.append(f"<h2 style='font-family:Arial,sans-serif'>{head} — {ds.date}</h2>"
                      f"<p style='font-family:Arial,sans-serif;color:#555'>{_tally(ds)}</p>")

    for status in groups_order:
        items = by_status.get(status) or []
        if not items:
            continue
        emoji, label = _LABELS.get(status, ("•", status))
        text_lines.append(f"\n{emoji} {label} ({len(items)})")
        html_parts.append(f"<h3 style='font-family:Arial,sans-serif'>{emoji} {label} "
                          f"<span style='color:#888;font-weight:normal'>({len(items)})</span></h3><ul style='font-family:Arial,sans-serif;font-size:14px'>")
        for rs in sorted(items, key=lambda x: x.report_id):
            line, h = _item_lines(rs, status)
            text_lines.append("  " + line)
            html_parts.append(f"<li>{h}</li>")
        html_parts.append("</ul>")

    # Still-trying call-to-action (checkpoint) / manual action list (final).
    still = by_status.get(st.STILL_TRYING) or []
    if checkpoint and still:
        ids = ", ".join(sorted(r.report_id for r in still))
        cta = (
            "\n🛑 To STOP one and fix the data yourself: reply to this email with "
            "subject  STOP <report_id>  (e.g. STOP country_metrics). It drops from "
            "the retry loop and is marked 'manually halted for fix'. "
            "Still trying until noon: " + ids)
        text_lines.append(cta)
        html_parts.append(
            "<div style='font-family:Arial,sans-serif;font-size:14px;background:#fff8e1;"
            "border:1px solid #ffe082;padding:10px;border-radius:6px'>"
            "<b>🛑 To stop one and fix it yourself:</b> reply to this email with subject "
            "<code>STOP &lt;report_id&gt;</code> (e.g. <code>STOP country_metrics</code>). "
            "It drops from the retry loop and is marked “manually halted for fix.”<br>"
            f"<span style='color:#777'>Still trying until noon: {_esc(ids)}</span></div>")

    actionable = ([rs for s in (st.INCOMPLETE, st.FAILED, st.MISSED_NOT_READY,
                                 st.BLOCKED_SESSION)
                   for rs in (by_status.get(s) or [])])
    if not checkpoint and actionable:
        text_lines.append("\n🔁 Manual action list:")
        html_parts.append("<h3 style='font-family:Arial,sans-serif'>🔁 Manual action list</h3>"
                          "<ol style='font-family:Arial,sans-serif;font-size:14px'>")
        for rs in actionable:
            cmd = _rerun_cmd(rs)
            miss = (" — missing: " + "; ".join(rs.missing)) if rs.missing else ""
            text_lines.append(f"  {rs.report_id}: {cmd}{miss}")
            html_parts.append(f"<li><b>{_esc(rs.display_name or rs.report_id)}</b>"
                              f"{_esc(miss)}<br><code>{_esc(cmd)}</code></li>")
        html_parts.append("</ol>")

    html = ("<div style='font-family:Arial,sans-serif;color:#000'>"
            + "".join(html_parts) + "</div>")
    return html, "\n".join(text_lines)


def _item_lines(rs, status):
    base = rs.display_name or rs.report_id
    extra = ""
    if status == st.STILL_TRYING and rs.waiting_on:
        extra = f" — waiting on {rs.waiting_on}"
    elif status == st.INCOMPLETE and rs.missing:
        extra = f" — missing: {'; '.join(rs.missing)}"
    elif rs.last_reason and status in (st.FAILED, st.MISSED_NOT_READY, st.BLOCKED_SESSION):
        extra = f" — {rs.last_reason}"
    text = f"{base} [{rs.report_id}]{extra}"
    html = f"<b>{_esc(base)}</b> <span style='color:#999'>[{_esc(rs.report_id)}]</span>{_esc(extra)}"
    return text, html


def _rerun_cmd(rs):
    # Best-effort re-run hint; the orchestrator stores only the id, so point at
    # the module form the wrappers use.
    return f"python -m automations.{rs.report_id}.run   # (or the report's Hub card)"


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
        parts.append(f"{inc} incomplete")
    if fail:
        parts.append(f"{fail} failed")
    if missed:
        parts.append(f"{missed} missed")
    if trying:
        parts.append(f"{trying} still trying")
    return " · ".join(parts)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
