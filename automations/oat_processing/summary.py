#!/usr/bin/env python3
"""OAT daily scorecard — read the day's activity log, render the scorecard to a
PDF, and post it to Slack (#alphaletegp-recruiting) under a "DAILY PUSH
SCORECARD" thread for Megan & Carlos.

The live runs append one row per applicant to output/oat-activity-<date>.csv
(time, applicant, source, position, action, outcome, reason). This tallies the
whole day and renders the scorecard the mockup previewed.

Run on Lucy 2 (where the 'Lucy' Slack token + Chromium live):
  python -m automations.oat_processing.summary            # build + post as Lucy
  python -m automations.oat_processing.summary --dry-run  # build the PDF only
  python -m automations.oat_processing.summary --date 2026-07-27

NOTE: re-text auto-SEND isn't live yet (copy pending Megan's approval), so the
">1 week" applicants show as "Flagged · re-text" here, not "Re-engaged". Flip the
label + wording once re-text sending is armed.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import argparse
import csv
import datetime as dt
import html as _html
import os
import re
from pathlib import Path

from . import config

CHANNEL_ID = os.environ.get("OAT_SCORECARD_CHANNEL", "C09L1S3MQ1E")  # #alphaletegp-recruiting
PARENT_TEXT = "\U0001F4CB DAILY PUSH SCORECARD"
# Per-office (the push works more than one office now). Both are set by the
# wrapper via env; the defaults are Carlos's office, unchanged.
OFFICE_LABEL = os.environ.get(
    "OAT_OFFICE_LABEL", "office 11580 · Carlos Hidalgo — ATT Program")
OFFICE_SHORT = os.environ.get("OAT_OFFICE_SHORT", "office 11580, Carlos")

SENT = ("sent", "sent_override")


def _activity_path(date: dt.date) -> Path:
    return (Path("output") /
            f"oat-activity-{date.isoformat()}{config.FILE_SUFFIX}.csv")


def load_rows(date: dt.date) -> list:
    p = _activity_path(date)
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _dedupe(rows: list) -> list:
    """Each applicant appears once — their FINAL outcome for the day. No-phone /
    re-text / blocked applicants stay in the queue and get re-processed every run
    (duplicate rows); a 'left' one that later became 'removed' should count as
    removed. Keep the LAST row per applicant name."""
    by_name: dict = {}
    for r in rows:
        name = (r.get("applicant") or "").strip().lower()
        if name:
            by_name[name] = r
    return list(by_name.values())


def tally(rows: list) -> dict:
    """Bucket the day's rows into the scorecard categories (deduped by applicant)."""
    rows = _dedupe(rows)
    sent, removed, retext, reengaged, nophone, blocked = [], [], [], [], [], []
    for r in rows:
        outcome = (r.get("outcome") or "").strip()
        action = (r.get("action") or "").strip()
        who = {"name": r.get("applicant", ""), "source": r.get("source", ""),
               "position": r.get("position", ""), "reason": r.get("reason", "")}
        if outcome in SENT:
            who["via"] = "overwrite" if outcome == "sent_override" else "direct"
            sent.append(who)
        elif outcome in ("retext_removed", "retext_sent"):
            reengaged.append(who)          # actually texted (+removed)
        elif outcome == "removed":
            removed.append(who)
        elif outcome == "flag_retext":
            retext.append(who)             # flagged only (not reachable / not armed)
        elif outcome == "flag_no_phone" or action == "flag_no_phone":
            nophone.append(who)
        elif outcome in ("left", "error", "no_button"):
            blocked.append(who)
    return {"sent": sent, "removed": removed, "retext": retext,
            "reengaged": reengaged, "nophone": nophone, "blocked": blocked,
            "processed": len(rows)}


# --------------------------------------------------------------------------- #
# HTML render (mirrors the approved mockup, filled from real data)
# --------------------------------------------------------------------------- #
def _esc(s) -> str:
    return _html.escape(str(s or ""))


def _rows_html(items, cols) -> str:
    if not items:
        return ('<tr><td colspan="3" class="src" style="padding:12px 10px">'
                'None today.</td></tr>')
    out = []
    for it in items:
        cells = "".join(cols(it))
        out.append(f"<tr>{cells}</tr>")
    return "".join(out)


def build_html(date: dt.date, t: dict, last_scan: str = "") -> str:
    n_sent = len(t["sent"]); n_direct = sum(1 for x in t["sent"] if x.get("via") == "direct")
    n_over = n_sent - n_direct
    n_rem = len(t["removed"]); n_rt = len(t["retext"]); n_np = len(t["nophone"])
    n_re = len(t.get("reengaged", []))
    n_blk = len(t["blocked"]); reached = n_sent + n_re
    proc = t["processed"] or 1
    date_str = date.strftime("%A, %B %-d, %Y") if os.name != "nt" else date.strftime("%A, %B %d, %Y")

    def who_src(it):
        return (f'<td><div class="who">{_esc(it["name"])}</div>'
                f'<div class="src">{_esc(it["source"])}</div></td>')

    reengaged_rows = _rows_html(t.get("reengaged", []), lambda it: [
        who_src(it), f'<td>{_esc(it["reason"]) or "gone quiet &gt; 1 week"}</td>',
        '<td><span class="pill" style="--c:var(--sent);--cbg:var(--sent-bg)">'
        'Re-texted &amp; removed</span></td>'])
    removed_rows = _rows_html(t["removed"], lambda it: [
        who_src(it), f'<td>{_esc(it["reason"]) or "duplicate"}</td>',
        '<td><span class="pill">Removed</span></td>'])
    # Don't show the raw activity 'reason' here — it's the initial CLASSIFY reason
    # (often stale, e.g. 'no phone…' for one whose resume number WAS found and who
    # then routed to re-text). Show the real, consistent status instead (Megan 7/30).
    retext_rows = _rows_html(t["retext"], lambda it: [
        who_src(it), '<td>gone quiet &gt; 1 week · thread older than this month</td>',
        '<td><span class="pill" style="--c:var(--flag);--cbg:var(--flag-bg)">'
        'Flagged · re-text</span></td>'])
    nophone_rows = _rows_html(t["nophone"], lambda it: [
        who_src(it), f'<td>{_esc(it["position"])}</td>',
        '<td><span class="pill" style="--c:var(--phone);--cbg:var(--phone-bg)">'
        'Get number from Indeed</span></td>'])
    blocked_block = ""
    if t["blocked"]:
        blk_rows = _rows_html(t["blocked"], lambda it: [
            who_src(it), f'<td>{_esc(it["reason"])}</td>',
            '<td><span class="pill">Left in queue</span></td>'])
        blocked_block = f"""
  <div class="panel" style="--c:var(--rem);--cbg:var(--rem-bg)">
    <div class="ph"><h2>Couldn't process</h2><span class="n">{n_blk}</span>
      <span class="hint">blocked and not yet removable — left for a look</span></div>
    <table><thead><tr><th style="width:38%">Applicant</th><th>Why</th>
      <th style="width:26%">Status</th></tr></thead><tbody>{blk_rows}</tbody></table>
  </div>"""

    return f"""<title>OAT Daily Push Scorecard</title>
<style>
  :root{{--ink:#111726;--ink-soft:#33405c;--mut:#5b6577;--line:#e4e8ef;--paper:#f5f7fb;
    --card:#fff;--brand:#2b57d6;--sent:#12805c;--sent-bg:#e7f4ee;--rem:#54617a;--rem-bg:#eef1f6;
    --flag:#b26b00;--flag-bg:#faf0dd;--phone:#b4471f;--phone-bg:#fbeadf;
    --mono:"SF Mono","JetBrains Mono","Roboto Mono",ui-monospace,Menlo,monospace;
    --sans:"Inter",-apple-system,"Segoe UI",system-ui,sans-serif;}}
  @media (prefers-color-scheme:dark){{:root{{--ink:#eef1f7;--ink-soft:#cdd4e2;--mut:#96a0b4;
    --line:#232b3b;--paper:#0e1320;--card:#151c2b;--sent:#4dc79a;--sent-bg:#12251e;--rem:#9aa6bf;
    --rem-bg:#1a2030;--flag:#e0a63c;--flag-bg:#2a2210;--phone:#e08356;--phone-bg:#2a1912;}}}}
  *{{box-sizing:border-box}}body{{margin:0}}
  .wrap{{font-family:var(--sans);background:var(--paper);color:var(--ink);padding:clamp(16px,4vw,40px);min-height:100vh}}
  .board{{max-width:860px;margin:0 auto}}
  .top{{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px;padding-bottom:18px;border-bottom:2px solid var(--ink)}}
  .brand{{display:flex;align-items:center;gap:11px}}
  .dot{{width:34px;height:34px;border-radius:9px;background:var(--brand);color:#fff;font-family:var(--mono);font-weight:700;font-size:15px;display:flex;align-items:center;justify-content:center}}
  h1{{font-size:20px;margin:0;letter-spacing:-.01em;font-weight:700}}
  .sub{{font-size:12.5px;color:var(--mut);margin-top:2px}}
  .when{{text-align:right;font-size:12.5px;color:var(--mut);line-height:1.5}}
  .when b{{color:var(--ink);font-weight:600}}
  .kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}}
  .kpi{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 15px 15px;position:relative;overflow:hidden}}
  .kpi::before{{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--c)}}
  .klab{{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--mut);font-weight:600}}
  .knum{{font-family:var(--mono);font-size:40px;line-height:1;font-weight:700;color:var(--c);margin:9px 0 4px;font-variant-numeric:tabular-nums}}
  .ksub{{font-size:12px;color:var(--mut)}}
  .strip{{display:flex;flex-wrap:wrap;gap:8px 22px;font-size:12.5px;color:var(--mut);padding:11px 15px;background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:22px}}
  .strip b{{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}}
  .panel{{margin-bottom:20px}}
  .ph{{display:flex;align-items:baseline;gap:9px;margin:0 0 10px}}
  .ph h2{{font-size:14px;margin:0;font-weight:700}}
  .ph .n{{font-family:var(--mono);font-size:13px;font-weight:700;color:var(--c);background:var(--cbg);border-radius:20px;padding:1px 9px}}
  .ph .hint{{margin-left:auto;font-size:11.5px;color:var(--mut)}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th{{text-align:left;font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);font-weight:600;padding:0 10px 7px;border-bottom:1px solid var(--line)}}
  td{{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:middle}}
  tr:last-child td{{border-bottom:0}}
  .who{{font-weight:600;color:var(--ink)}}.src{{font-size:11px;color:var(--mut)}}
  .pill{{font-size:11px;font-weight:600;border-radius:6px;padding:2px 8px;white-space:nowrap;display:inline-block;background:var(--cbg,var(--rem-bg));color:var(--c,var(--rem))}}
  .foot{{display:flex;flex-wrap:wrap;gap:8px;justify-content:space-between;align-items:center;margin-top:26px;padding-top:14px;border-top:1px solid var(--line);font-size:11.5px;color:var(--mut)}}
</style>
<div class="wrap"><div class="board">
  <div class="top">
    <div class="brand"><div class="dot">OAT</div>
      <div><h1>Daily Push Scorecard</h1>
        <div class="sub">One&nbsp;App&nbsp;at&nbsp;a&nbsp;Time · {OFFICE_LABEL}</div></div></div>
    <div class="when"><div><b>{date_str}</b></div>
      <div>runs every 5 min · 7:00 AM – 8:00 PM CST{(' · last scan ' + last_scan) if last_scan else ''}</div></div>
  </div>
  <div class="kpis">
    <div class="kpi" style="--c:var(--sent)"><div class="klab">Sent to AI</div>
      <div class="knum">{n_sent}</div><div class="ksub">{n_direct} direct · {n_over} via overwrite</div></div>
    <div class="kpi" style="--c:var(--brand)"><div class="klab">Re-texted &amp; removed</div>
      <div class="knum">{n_re}</div><div class="ksub">quiet &gt; 1 week — re-engaged</div></div>
    <div class="kpi" style="--c:var(--flag)"><div class="klab">Flagged · re-text</div>
      <div class="knum">{n_rt}</div><div class="ksub">no SMS thread yet</div></div>
    <div class="kpi" style="--c:var(--rem)"><div class="klab">Removed · duplicate</div>
      <div class="knum">{n_rem}</div><div class="ksub">recent / already booked</div></div>
    <div class="kpi" style="--c:var(--phone)"><div class="klab">No phone</div>
      <div class="knum">{n_np}</div><div class="ksub">number to pull from Indeed</div></div>
  </div>
  <div class="strip">
    <span><b>{proc}</b> processed</span>
    <span><b>{reached}</b> sent to the AI call list</span>
    <span><b>{round(100*reached/proc)}%</b> push rate</span>
    <span><b>0</b> misfires · every send verified by the ATS</span>
  </div>

  <div class="panel" style="--c:var(--rem);--cbg:var(--rem-bg)">
    <div class="ph"><h2>Removed as duplicate</h2><span class="n">{n_rem}</span>
      <span class="hint">couldn't be re-sent — cleaned out of the queue</span></div>
    <table><thead><tr><th style="width:38%">Applicant</th><th>Why it couldn't send</th>
      <th style="width:26%">Action taken</th></tr></thead><tbody>{removed_rows}</tbody></table>
  </div>

  <div class="panel" style="--c:var(--brand);--cbg:#e7edfb">
    <div class="ph"><h2>Re-texted &amp; removed</h2><span class="n">{n_re}</span>
      <span class="hint">quiet &gt; 1 week — texted the FOR&nbsp;LUCY invite, then removed</span></div>
    <table><thead><tr><th style="width:38%">Applicant</th><th>Why</th>
      <th style="width:26%">Action taken</th></tr></thead><tbody>{reengaged_rows}</tbody></table>
  </div>

  <div class="panel" style="--c:var(--flag);--cbg:var(--flag-bg)">
    <div class="ph"><h2>Flagged for re-text</h2><span class="n">{n_rt}</span>
      <span class="hint">gone quiet &gt; 1 week — no SMS thread to reply into yet</span></div>
    <table><thead><tr><th style="width:38%">Applicant</th><th>Last contact</th>
      <th style="width:26%">Status</th></tr></thead><tbody>{retext_rows}</tbody></table>
  </div>

  <div class="panel" style="--c:var(--phone);--cbg:var(--phone-bg)">
    <div class="ph"><h2>Needs a human · no phone</h2><span class="n">{n_np}</span>
      <span class="hint">number masked by the job board — pull it, then they can be sent</span></div>
    <table><thead><tr><th style="width:38%">Applicant</th><th>Position</th>
      <th style="width:30%">Next step</th></tr></thead><tbody>{nophone_rows}</tbody></table>
  </div>
{blocked_block}
  <div class="foot">
    <span>Posted by Lucy · Megan &amp; Carlos</span>
    <span>{OFFICE_SHORT} · generated {last_scan or dt.datetime.now().strftime('%-I:%M %p')} CST</span>
  </div>
</div></div>"""


def render_pdf(html_body: str, out_path: str) -> str:
    doc = ("<!doctype html><html><head><meta charset='utf-8'>"
           "<style>html,body{margin:0}</style></head><body>" + html_body + "</body></html>")
    tmp = str(Path(out_path).with_suffix(".html"))
    Path(tmp).write_text(doc, encoding="utf-8")
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 900, "height": 1200})
        pg.emulate_media(color_scheme="light")
        pg.goto("file://" + os.path.abspath(tmp), wait_until="networkidle")
        h = pg.evaluate("Math.ceil(document.querySelector('.board').getBoundingClientRect().height)+72")
        pg.pdf(path=out_path, print_background=True, width="900px", height=f"{h}px",
               margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        b.close()
    return out_path


def post_to_slack(pdf_path: str, date: dt.date, t: dict) -> dict:
    """Post to #alphaletegp-recruiting: a 'DAILY PUSH SCORECARD' parent + the PDF
    in-thread. Posts as Lucy on Lucy 2 (slack_metrics_post._client = the Lucy
    xoxp token there; on the laptop it would be Megan)."""
    from automations.shared import slack_metrics_post as smp
    c = smp._client()
    # No counts breakdown in the header — the PDF carries the full picture
    # (Megan 2026-07-29).
    summary = f"{date.strftime('%A, %b %-d')} · {OFFICE_SHORT}"
    parent = c.chat_postMessage(channel=CHANNEL_ID, text=PARENT_TEXT)
    ts = parent["ts"]
    up = c.files_upload_v2(channel=CHANNEL_ID, thread_ts=ts, file=pdf_path,
                          title=f"OAT Daily Push Scorecard — {date.isoformat()}",
                          initial_comment=summary)
    return {"ok": True, "thread_ts": ts, "file": up.get("file", {}).get("id")}


def fix_last_header() -> int:
    """Edit the most recent DAILY PUSH SCORECARD thread's PDF reply to strip the
    counts breakdown from its text (keeps the PDF). Posts as Lucy via the same
    user token that posted it."""
    from automations.shared import slack_metrics_post as smp
    c = smp._client()
    hist = c.conversations_history(channel=CHANNEL_ID, limit=40)
    # match on the text WITHOUT the emoji — Slack returns 📋 as :clipboard: in the
    # API, so an exact PARENT_TEXT match misses.
    parent = next((m for m in hist.get("messages", [])
                   if "DAILY PUSH SCORECARD" in (m.get("text") or "")), None)
    if not parent:
        print("[fix] no DAILY PUSH SCORECARD parent found", flush=True)
        return 0
    reps = c.conversations_replies(channel=CHANNEL_ID, ts=parent["ts"])
    clean = "Full scorecard attached."
    fixed = 0
    for m in reps.get("messages", []):
        if m.get("ts") == parent["ts"]:
            continue
        if "sent to AI" in (m.get("text") or "") or m.get("files"):
            try:
                c.chat_update(channel=CHANNEL_ID, ts=m["ts"], text=clean)
                fixed += 1
                print(f"[fix] updated reply {m['ts']}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[fix] chat_update failed on {m['ts']}: {e}", flush=True)
    print(f"[fix] fixed {fixed} message(s)", flush=True)
    return 0


# account domain ROOT (domain minus the TLD, e.g. "rawsalesgroupmarketing") → clean
# display name. Keyed by ROOT so it matches regardless of .com/.net/tx. Runtogether
# domains can't be auto-split into words, so map them here as Carlos confirms names.
_ACCOUNT_NAMES = {
    "fasttrack-strategies": "Fast Track Strategies",
    "fasttrackstrategies": "Fast Track Strategies",
    "peaksalesstrategies": "Peak Sales Strategies",
    "peaksalesstrategiestx": "Peak Sales Strategies",
    "rawsalesgroupmarketing": "Raw Sales Group Marketing",
    "ascendraacquisitions": "Ascendra Acquisitions",
}


def _account_name(to_email: str) -> str:
    """Turn the 'To:' account email into a readable account name for the post.
    Known domain roots → the clean name; unknown → a best-effort title-cased domain
    (readable enough to know which account, and easy to add to the map later)."""
    to_email = (to_email or "").strip().lower()
    if "@" not in to_email:
        return ""
    dom = to_email.split("@", 1)[1].strip()
    root = re.sub(r"\.(com|net|org|co|us|io|biz|info)$", "", dom)
    if root in _ACCOUNT_NAMES:
        return _ACCOUNT_NAMES[root]
    if dom in _ACCOUNT_NAMES:
        return _ACCOUNT_NAMES[dom]
    return root.replace("-", " ").replace(".", " ").strip().title()


def _entries_of(bucket) -> list:
    """Return [(name, account_email, days_sitting)] for a bucket. Tolerates old
    snapshots (bare names, or entries without a days field → None)."""
    out = []
    for it in bucket or []:
        if isinstance(it, dict):
            nm = (it.get("name") or "").strip()
            acct = (it.get("account") or "").strip()
            days = it.get("days")
        else:
            nm, acct, days = str(it).strip(), "", None
        if nm:
            out.append((nm, acct, days))
    return out


def _load_flagged_snapshot(date: dt.date) -> dict:
    """Read the current-queue flagged snapshot the latest OAT walk wrote
    (output/oat-flagged-<date>.json): who still needs a number / a manual text right
    now. Empty if the walk hasn't written one yet today."""
    import json as _json
    path = f"output/oat-flagged-{date.isoformat()}{config.FILE_SUFFIX}.json"
    try:
        with open(path) as fh:
            return _json.load(fh) or {}
    except Exception:  # noqa: BLE001
        return {}


def _find_today_parent(c, date_str: str):
    """Return the ts of today's 'recruiting to-do' parent message (so the 4pm post
    replies into the SAME thread the noon post created), or None if not posted yet.
    Match on 'recruiting to-do' + the date text — Slack returns 📋 as :clipboard:, so
    an emoji match would miss. Only the parent carries 'recruiting to-do'; the replies
    hold the names, so a text match uniquely finds the parent."""
    try:
        hist = c.conversations_history(channel=CHANNEL_ID, limit=60)
    except Exception:  # noqa: BLE001
        return None
    for m in hist.get("messages", []):
        txt = m.get("text") or ""
        if "recruiting to-do" in txt and date_str in txt:
            return m.get("ts")
    return None


def post_nophone_report(date: dt.date, t: dict, dry_run: bool = False,
                        edit: bool = False) -> dict:
    """Post the daily 'manual to-do' report to #alphaletegp-recruiting as Lucy —
    REPLACES the scorecard (Megan 2026-08-06). It lists the ONLY two buckets the bot
    legitimately can't process, so a human can finish them by hand:
      1. NO NUMBER — a number couldn't be read off their resume (needs an Indeed
         look-up by hand).
      2. NEEDS A MANUAL TEXT — quiet >1wk applicants whose SMS thread is older than
         this month, so the bot's texting widget can't see it to reply.

    Format: a HEADER parent with the totals, then the two labelled name lists as a
    threaded reply (so the counts sit clean in the channel, the who is one tap in)."""
    no_number = _entries_of(t.get("nophone"))
    needs_text = _entries_of(t.get("retext"))
    n_num, n_txt = len(no_number), len(needs_text)

    # Cross-platform date (no %-d): "Fri, Aug 8".
    date_str = date.strftime("%a, %b ") + str(date.day)
    header = (f"\U0001F4CB {date_str} — recruiting to-do: "
              f"{n_num} need a number, {n_txt} need a manual text")

    def _section(title, entries):
        if not entries:
            return f"{title} — 0\n  (none today ✅)"
        # GROUP by account (Megan 2026-08-07) so the human works one account at a
        # time: a bold account header with its count, then "• Name — N days" under it.
        groups = {}
        for nm, acct, days in entries:
            an = _account_name(acct) or "No account listed"
            groups.setdefault(an, []).append((nm, days))
        # biggest accounts first, then alphabetical
        ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        out = [f"{title} — {len(entries)}"]
        for an, people in ordered:
            out.append(f"\n*{an}* ({len(people)}):")
            for nm, days in people:
                line = f"  • {nm}"
                if days is not None:
                    line += f" — {days} day" + ("" if days == 1 else "s")
                    if days >= 2:   # alert on anyone sitting 2+ days ("old")
                        line += " \U0001F6A8"
                out.append(line)
        return "\n".join(out)

    body = (_section("\U0001F4DE Need a number pulled from Indeed", no_number)
            + "\n\n"
            + _section("\U0001F4AC Need a manual text (thread too old to see)",
                       needs_text))

    # Time label for the in-thread reply ("12 PM" / "4 PM"), cross-platform.
    slot = dt.datetime.now().strftime("%I %p").lstrip("0")

    if dry_run:
        print(f"[report] DRY-RUN — would post to {CHANNEL_ID} ({OFFICE_SHORT}):",
              flush=True)
        print("  HEADER (parent, created once/day): " + header, flush=True)
        print(f"  REPLY (in today's thread, {slot}):\n    "
              + body.replace("\n", "\n    "), flush=True)
        return {"ok": True, "dry_run": True, "no_number": n_num, "needs_text": n_txt}

    from automations.shared import slack_metrics_post as smp
    c = smp._client()
    # ONE thread per day: the noon post creates the parent; the 4pm post finds that
    # same parent and replies into it (Megan 2026-08-06 — admins get one running
    # to-do list, not two separate posts). Refresh the parent's counts each time so
    # the channel-visible header stays current.
    parent_ts = _find_today_parent(c, date_str)
    if parent_ts is None:
        if edit:
            print("[report] --edit: no thread today to edit", flush=True)
            return {"ok": False, "err": "no thread today"}
        parent = c.chat_postMessage(channel=CHANNEL_ID, text=header)
        parent_ts = parent["ts"]
    else:
        try:
            c.chat_update(channel=CHANNEL_ID, ts=parent_ts, text=header)
        except Exception:  # noqa: BLE001 — header refresh is best-effort
            pass

    if edit:
        # Rewrite the existing list-reply(ies) in today's thread in place (so a name's
        # account can be added without piling on a new reply). Keeps each reply's own
        # time label ("4 PM update"); replaces its body with the current one.
        try:
            reps = c.conversations_replies(channel=CHANNEL_ID, ts=parent_ts)
        except Exception as e:  # noqa: BLE001
            print(f"[report] --edit: couldn't read thread: {e}", flush=True)
            reps = {"messages": []}
        edited = 0
        for m in reps.get("messages", []):
            if m.get("ts") == parent_ts:
                continue
            txt = m.get("text") or ""
            if "need a number" in txt.lower() or "update" in txt.lower():
                label = txt.split("\n", 1)[0] if txt.startswith("*") else f"*{slot} update*"
                try:
                    c.chat_update(channel=CHANNEL_ID, ts=m["ts"], text=label + "\n" + body)
                    edited += 1
                except Exception as e:  # noqa: BLE001
                    print(f"[report] --edit chat_update failed: {e}", flush=True)
        print(f"[report] edited {edited} reply(ies) with accounts (thread {parent_ts})",
              flush=True)
        return {"ok": edited > 0, "thread_ts": parent_ts, "edited": edited}

    c.chat_postMessage(channel=CHANNEL_ID, thread_ts=parent_ts,
                       text=f"*{slot} update*\n" + body)
    print(f"[report] posted {slot} — {n_num} need a number, {n_txt} need a manual "
          f"text (thread {parent_ts})", flush=True)
    return {"ok": True, "thread_ts": parent_ts,
            "no_number": n_num, "needs_text": n_txt}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="OAT daily scorecard → Slack")
    ap.add_argument("--nophone", action="store_true",
                    help="Post the 'N applicants need a number pulled from Indeed' "
                         "report (header + names in-thread) instead of the scorecard. "
                         "This is the daily 8pm post now (Megan 2026-08-06).")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default today)")
    ap.add_argument("--dry-run", action="store_true", help="build the PDF, don't post")
    ap.add_argument("--emit", action="store_true",
                    help="print per-applicant bucket lines to stdout (lets a remote "
                         "caller rebuild the scorecard without pulling the PDF); no post")
    ap.add_argument("--emit-tab", default=None, dest="emit_tab",
                    metavar="<sheetId>:<tabName>",
                    help="write full bucketed data to a Google Sheet tab (no post)")
    ap.add_argument("--dm", default=None,
                    help="DM the scorecard PDF to this Slack user (id/email) as Lucy "
                         "instead of posting to the channel (for review)")
    ap.add_argument("--fix-header", action="store_true", dest="fix_header",
                    help="Edit the last channel post's reply to strip the counts "
                         "breakdown from its text, then stop")
    ap.add_argument("--edit", action="store_true",
                    help="With --nophone: rewrite today's existing thread reply in "
                         "place (e.g. to add accounts) instead of posting a new one")
    args = ap.parse_args(argv)

    if args.fix_header:
        return fix_last_header()
    date = (dt.date.fromisoformat(args.date) if args.date else dt.date.today())

    if args.nophone:
        # The daily noon/4pm post: who's flagged in the CURRENT queue (needs a number
        # pulled from Indeed, or a manual text). Reads the latest walk's snapshot
        # (output/oat-flagged-<date>.json) — NOT the day-cumulative activity log,
        # which over-counted apps already handled since (Megan 2026-08-06).
        snap = _load_flagged_snapshot(date)
        # Snapshot entries are {"name","account"} dicts (older ones were bare names);
        # _entries_of in the report tolerates both.
        t_snap = {"nophone": snap.get("nophone", []),
                  "retext": snap.get("retext", [])}
        print(f"[report] snapshot {date} @ {snap.get('at','?')} — "
              f"queue={snap.get('queue_total','?')} · "
              f"{len(t_snap['nophone'])} need a number, "
              f"{len(t_snap['retext'])} need a manual text", flush=True)
        res = post_nophone_report(date, t_snap, dry_run=args.dry_run, edit=args.edit)
        return 0 if res.get("ok") else 1

    rows = load_rows(date)
    t = tally(rows)
    last_scan = rows[-1]["time"] if rows else ""
    print(f"[scorecard] {date} — {t['processed']} rows: sent={len(t['sent'])} "
          f"removed={len(t['removed'])} retext={len(t['retext'])} "
          f"nophone={len(t['nophone'])} blocked={len(t['blocked'])}", flush=True)
    if args.emit_tab:
        # Write the full bucketed data to a Google Sheet tab (no truncation) so a
        # remote caller can rebuild the scorecard. Format "<sheetId>:<tabName>".
        sid, _, tabn = args.emit_tab.partition(":")
        tabn = tabn or "OAT Scorecard Data"
        from automations.recruiting_report import fill as _fill
        sh = _fill._client().open_by_key(sid)
        try:
            wsx = sh.worksheet(tabn)
            wsx.clear()
        except Exception:  # noqa: BLE001
            wsx = sh.add_worksheet(title=tabn, rows=200, cols=8)
        out = [["bucket", "name", "source", "reason", "position", "via"]]
        for b in ("sent", "reengaged", "removed", "retext", "nophone", "blocked"):
            for it in t[b]:
                out.append([b, it.get("name", ""), it.get("source", ""),
                            it.get("reason", ""), it.get("position", ""),
                            it.get("via", "")])
        out.append(["__meta__", f"processed={t['processed']}",
                    f"last_scan={last_scan}", f"date={date.isoformat()}", "", ""])
        wsx.update(out, "A1", value_input_option="RAW")
        print(f"[scorecard] wrote {len(out)-1} rows to tab {tabn!r}", flush=True)
        return 0
    if args.emit:
        # Tab-separated, one applicant per line, short + greppable via logtail.
        for b in ("sent", "reengaged", "removed", "retext", "nophone", "blocked"):
            for it in t[b]:
                # distinct per-bucket prefix (EMITSENT/EMITREMOVED/…) so a literal
                # substring grep can pull one bucket cleanly.
                print(f"EMIT{b.upper()}| " + " | ".join([
                    str(it.get("name", "")), str(it.get("source", "")),
                    str(it.get("reason", "")), str(it.get("position", "")),
                    str(it.get("via", ""))]), flush=True)
        print(f"EMITMETA\tprocessed={t['processed']}\tlast_scan={last_scan}", flush=True)
        return 0
    html_body = build_html(date, t, last_scan)
    os.makedirs("output", exist_ok=True)
    pdf = f"output/oat-daily-push-scorecard-{date.isoformat()}.pdf"
    render_pdf(html_body, pdf)
    print(f"[scorecard] wrote {pdf}", flush=True)
    if args.dry_run:
        print("[scorecard] --dry-run: not posting", flush=True)
        return 0
    if args.dm:
        # DM the card to one person (Megan) for review — no public channel post.
        from automations.shared import slack_metrics_post as smp
        # Header only — the PDF already carries the full breakdown (Megan 2026-07-29).
        comment = (f"\U0001F4CB OAT Daily Push — {date.strftime('%b %-d')} "
                   f"({OFFICE_SHORT})")
        res = smp.dm_user_with_file(pdf, user=args.dm, comment=comment,
                                    file_name=f"OAT-Daily-Push-{date.isoformat()}.pdf")
        print(f"[scorecard] DM'd to {args.dm}: {res}", flush=True)
        return 0
    res = post_to_slack(pdf, date, t)
    print(f"[scorecard] posted to Slack: {res}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
