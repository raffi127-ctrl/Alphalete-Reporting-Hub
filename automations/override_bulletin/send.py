"""Publish the Override Bulletin — Slack image post + inline-image email.

This is the LAST step of the Friday flow: `run.py` fills the week column,
`build.py` renders the bulletin, and this module puts it in front of people.

    python -m automations.override_bulletin.send                    # DRY RUN
    python -m automations.override_bulletin.send --preview          # email Megan only
    python -m automations.override_bulletin.send --send             # the real distro

NOTHING GOES OUT WITHOUT A FLAG. The default is a dry run: it builds, renders,
resolves the real recipients and prints exactly what would be sent where. That
is deliberate — this is an outward-facing post to the whole org, and the standing
rule is that Megan approves each send.

WHAT GETS SENT
  * Slack — the rendered PNG to #alphalete-sales and #rafs-office-recruiting,
    posted AS LUCY (channel posts use the xoxp USER token, per
    slack_metrics_post._client()).
  * Email — from alphaletereporting@gmail.com to the "Alphalete Org Owners" and
    "Bulletins" contact groups, subject "Alphalete Organization Override Bulletin
    WE m.d".

WHY THE EMAIL SENDS THE PNG, NOT THE BULLETIN HTML
  build_html embeds the logo and every headshot as `data:` URIs. That is right
  for a local file and for the Slack render, but Gmail STRIPS data: image URIs
  from received mail — the bulletin would arrive as a page of broken images. So
  the email carries the same rendered PNG as ONE inline `cid:` image (Megan:
  inline, not an attachment), which is also exactly what the Slack post shows.

IDEMPOTENCY
  launchd fires the Friday passes every 25 minutes. A send records the week it
  published; a later pass for the same week refuses to send again unless
  --force. Without that, a retry after a slow pass double-posts to the whole org.
"""
from __future__ import annotations

import argparse
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from automations.override_bulletin import build as B
from automations.override_bulletin import fill as F

# Slack targets — Lucy is a member of both (the VA posted the bulletin to both).
# Set OVERRIDE_BULLETIN_CHANNEL_ID to a scratch channel to test a real post
# safely; it replaces BOTH real channels (same knob as pnl_office).
CHANNELS = [
    ("#alphalete-sales",        "C068PH3RFSM"),
    ("#rafs-office-recruiting", "C06881A7WLV"),
]
# Preview recipient for --preview (Megan only, before the distro goes live).
PREVIEW_TO = ["Meganhidalgo1191@gmail.com"]

STATE_PATH = Path.home() / ".config" / "recruiting-report" / "override_bulletin_last_sent.txt"


def _channels():
    """Real channels, or a single scratch channel if the env override is set."""
    import os
    scratch = os.environ.get("OVERRIDE_BULLETIN_CHANNEL_ID")
    if scratch:
        return [("scratch ({})".format(scratch), scratch)]
    return CHANNELS


def already_sent(week_label):
    try:
        return STATE_PATH.read_text(encoding="utf-8").strip() == (week_label or "").strip()
    except OSError:
        return False


def mark_sent(week_label):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(week_label or "", encoding="utf-8")


def recipients(groups=None):
    """(emails, missing) for the distro contact groups.

    A group name that doesn't resolve is returned rather than skipped: silently
    emailing one of two groups looks exactly like a successful send."""
    from automations.shared.contacts_auth import expand_groups
    return expand_groups(list(groups or B.EMAIL_GROUPS))


def build_email(png_path, week_label, to_addrs):
    """The distro email: subject + one inline cid: image of the bulletin."""
    msg = EmailMessage()
    msg["From"] = B.EMAIL_FROM
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = B.email_subject(week_label)
    cid = make_msgid()[1:-1]
    html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;background:#000;'
        'padding:0;margin:0">'
        '<img src="cid:{}" style="max-width:1000px;width:100%;display:block">'
        "</div>".format(cid))
    msg.set_content(
        "Alphalete Organization Override Bulletin — week ending {}.\n"
        "This email is best viewed in an HTML email client.".format(week_label))
    msg.add_alternative(html, subtype="html")
    msg.get_payload()[-1].add_related(Path(png_path).read_bytes(), "image", "png",
                                      cid="<{}>".format(cid))
    return msg


def send_email(msg):
    from automations.scheduled_6_days_out.email_send import (
        FROM_ADDR, SMTP_HOST, SMTP_PORT, app_password)
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:                       # pragma: no cover - mini has certifi
        ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
        s.login(FROM_ADDR, app_password())
        s.send_message(msg)


def post_slack(png_path, caption, filename):
    """Upload the PNG to each target channel as Lucy."""
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    out = []
    for name, cid in _channels():
        resp = client.files_upload_v2(channel=cid, file=str(png_path),
                                      filename=filename, initial_comment=caption)
        out.append({"channel": name, "id": cid, "ok": resp.get("ok"),
                    "file": (resp.get("file") or {}).get("id")})
    return out


def caption_for(week_label):
    md = ".".join((week_label or "").split(".")[:2])
    return "🏆 Alphalete Organization Override Bulletin — WE {}".format(md)


def send(*, tab=None, do_send=False, preview=False, force=False, out_dir=None):
    """Build → render → (optionally) publish. Returns a summary dict.

    do_send=False and preview=False is a DRY RUN: everything is built and every
    recipient resolved, but nothing leaves the machine."""
    tab = tab or F.LIVE_TAB
    out_dir = Path(out_dir) if out_dir else B.OUT_DIR

    # One read of the tab, not two — build() would re-read it for the same rows.
    week_labels, section1, section2 = B.read_data(tab)
    week_label = week_labels[0] if week_labels else ""
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "override-bulletin.html"
    html_path.write_text(B.build_html(week_labels, section1, section2),
                         encoding="utf-8")
    print("built {} (week {!r}; ALL ORG {} rows, CAPTAIN/SPECIAL {} rows)".format(
        html_path, week_label, len(section1), len(section2)))
    png_name = "Override-Bulletin-WE-{}.png".format(
        ".".join(week_label.split(".")[:2]) or "unknown")
    png_path = B.render_png(html_path, out_dir / png_name)

    # The bulletin must reflect a FILLED week. Publishing a rolled-but-empty
    # column would send the whole org a bulletin of blanks.
    from automations.recruiting_report import fill as _fill
    ws = _fill._client().open_by_key(F.WORKBOOK_ID).worksheet(tab)
    if week_label and not F.week_is_filled(ws, week_label):
        print("REFUSING: {} is not filled on {!r} — nothing to publish".format(
            week_label, tab))
        return {"published": False, "reason": "week not filled", "week": week_label}

    subject = B.email_subject(week_label)
    caption = caption_for(week_label)
    if preview:
        to_addrs, missing = list(PREVIEW_TO), []
    else:
        to_addrs, missing = recipients()

    print("\nweek        : {}".format(week_label))
    print("source tab  : {!r}".format(tab))
    print("image       : {}".format(png_path))
    print("subject     : {}".format(subject))
    print("slack       : {}".format(
        ", ".join("{} ({})".format(n, c) for n, c in _channels())))
    print("email to    : {} address(es)".format(len(to_addrs)))
    for a in to_addrs:
        print("    • {}".format(a))
    if missing:
        print("⚠ contact group(s) NOT FOUND: {} — the distro is INCOMPLETE".format(
            ", ".join(missing)))

    if not (do_send or preview):
        print("\nDRY RUN — nothing posted, nothing emailed. "
              "Re-run with --preview (email Megan only) or --send (real distro).")
        return {"published": False, "dry_run": True, "week": week_label,
                "png": str(png_path), "to": to_addrs, "missing": missing}
    if missing and do_send:
        raise SystemExit("refusing to send: contact group(s) missing: {}. Fix the "
                         "group name(s) in alphaletereporting@gmail.com's contacts "
                         "or pass the groups explicitly.".format(", ".join(missing)))
    if do_send and already_sent(week_label) and not force:
        print("\nALREADY SENT for {} — not sending again (pass --force to "
              "override).".format(week_label))
        return {"published": False, "reason": "already sent", "week": week_label}

    result = {"week": week_label, "png": str(png_path), "to": to_addrs}
    if do_send:
        result["slack"] = post_slack(png_path, caption, png_name)
        for r in result["slack"]:
            print("posted to {} ok={}".format(r["channel"], r.get("ok")))
    else:
        print("\n(preview: Slack post skipped — email only)")

    send_email(build_email(png_path, week_label, to_addrs))
    print("emailed {} recipient(s): {}".format(len(to_addrs), subject))
    if do_send:
        mark_sent(week_label)
    result["published"] = True
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Publish the Override Bulletin (dry run unless --send/--preview)")
    ap.add_argument("--tab", default=F.LIVE_TAB,
                    help="source tab to build the bulletin from (default: the "
                         "live tab; use the sandbox copy while testing)")
    ap.add_argument("--send", action="store_true",
                    help="REALLY publish: Slack both channels + email both groups")
    ap.add_argument("--preview", action="store_true",
                    help="email Megan only, post nothing to Slack")
    ap.add_argument("--force", action="store_true",
                    help="send again even though this week was already sent")
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args(argv)
    if a.send and a.preview:
        raise SystemExit("--send and --preview are mutually exclusive")
    send(tab=a.tab, do_send=a.send, preview=a.preview, force=a.force,
         out_dir=a.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
