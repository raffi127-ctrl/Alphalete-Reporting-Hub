"""Publish a bulletin — Slack image post + inline-image email.

Two bulletins ship through this one module, because they are the same act with
different artwork and different rooms:

  OVERRIDE (Friday) — `run.py` fills the week column, `build.py` renders it.
  DD / ORGANIZATION (Thursday, --dd) — `dd_data.py` reads the week off
  `Org DDs Ongoing Report`, `dd_build.py` renders TWO pages (the leaders page
  and the by-ICD breakdown), and both go out together.

    python -m automations.override_bulletin.send                    # DRY RUN
    python -m automations.override_bulletin.send --preview          # email Megan only
    python -m automations.override_bulletin.send --send             # the real distro
    python -m automations.override_bulletin.send --dd               # DD bulletin, dry
    python -m automations.override_bulletin.send --dd --preview     # DD to Megan only

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
  the email carries the same rendered PNG as an inline `cid:` image (Megan:
  inline, not an attachment), which is also exactly what the Slack post shows.
  The DD bulletin carries two of them, one per page, in the same message.

WHAT STOPS A DD SEND
  `dd_data.load()` returns `blocking` — the problems that mean a number on the
  page is WRONG rather than merely incomplete (a leader off its published figure,
  a podium list that fails its cross-check, Credico not folded in). --send
  refuses while any of those stand. A dry run and --preview still build and show
  the pages, because looking at a broken one is how it gets fixed. --force sends
  anyway, and says so.

IDEMPOTENCY
  launchd fires the weekly passes every 25 minutes. A send records the week it
  published; a later pass for the same week refuses to send again unless
  --force. Without that, a retry after a slow pass double-posts to the whole org.
  The two bulletins keep SEPARATE state files, so sending one never marks the
  other as done.
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
# DD bulletin rooms — DD_SOURCES.md: the VA posted it to #alphalete-sales and
# #alphalete-lvl1-chat, and Megan also lists #rafs-office-recruiting. Every id
# was resolved against the workspace on 2026-07-24, not copied from a doc.
DD_CHANNELS = [
    ("#alphalete-sales",        "C068PH3RFSM"),
    ("#alphalete-lvl1-chat",    "C09JG28CD27"),
    ("#rafs-office-recruiting", "C06881A7WLV"),
]
# Preview recipient for --preview (Megan only, before the distro goes live).
PREVIEW_TO = ["Meganhidalgo1191@gmail.com"]

STATE_DIR = Path.home() / ".config" / "recruiting-report"
STATE_PATH = STATE_DIR / "override_bulletin_last_sent.txt"
DD_STATE_PATH = STATE_DIR / "dd_bulletin_last_sent.txt"


def _channels(dd=False):
    """Real channels, or a single scratch channel if the env override is set."""
    import os
    scratch = os.environ.get(
        "DD_BULLETIN_CHANNEL_ID" if dd else "OVERRIDE_BULLETIN_CHANNEL_ID")
    if scratch:
        return [("scratch ({})".format(scratch), scratch)]
    return DD_CHANNELS if dd else CHANNELS


def already_sent(week_label, state_path=None):
    try:
        return (state_path or STATE_PATH).read_text(
            encoding="utf-8").strip() == (week_label or "").strip()
    except OSError:
        return False


def mark_sent(week_label, state_path=None):
    p = state_path or STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(week_label or "", encoding="utf-8")


def recipients(groups=None):
    """(emails, missing) for the distro contact groups.

    A group name that doesn't resolve is returned rather than skipped: silently
    emailing one of two groups looks exactly like a successful send."""
    from automations.shared.contacts_auth import expand_groups
    return expand_groups(list(groups or B.EMAIL_GROUPS))


def build_email(png_paths, week_label, to_addrs, subject=None, title=None):
    """The distro email: subject + one inline cid: image PER PAGE.

    `png_paths` takes a single path or a list — the override bulletin is one
    page, the DD bulletin is two, and both arrive as inline images in one
    message rather than as attachments (Megan) or as data: URIs (Gmail strips
    those, which is the whole reason this renders to PNG at all)."""
    if isinstance(png_paths, (str, Path)):
        png_paths = [png_paths]
    subject = subject or B.email_subject(week_label)
    title = title or "Alphalete Organization Override Bulletin"
    msg = EmailMessage()
    msg["From"] = B.EMAIL_FROM
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    cids = [make_msgid()[1:-1] for _ in png_paths]
    imgs = "".join(
        '<img src="cid:{}" style="max-width:1000px;width:100%;display:block">'.format(c)
        for c in cids)
    html = ('<div style="font-family:Arial,Helvetica,sans-serif;background:#000;'
            'padding:0;margin:0">{}</div>'.format(imgs))
    msg.set_content(
        "{} — week ending {}.\n"
        "This email is best viewed in an HTML email client.".format(title, week_label))
    msg.add_alternative(html, subtype="html")
    part = msg.get_payload()[-1]
    for cid, p in zip(cids, png_paths):
        part.add_related(Path(p).read_bytes(), "image", "png",
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


def post_slack(png_paths, caption, filenames, channels=None):
    """Upload the page(s) to each target channel as Lucy, one message each.

    Multi-page bulletins go up as a single message per channel (`file_uploads`),
    not one message per page — two posts in a row read as two bulletins."""
    from automations.shared import slack_metrics_post as smp
    if isinstance(png_paths, (str, Path)):
        png_paths, filenames = [png_paths], [filenames]
    ups = [{"file": str(p), "filename": f} for p, f in zip(png_paths, filenames)]
    client = smp._client()
    out = []
    for name, cid in (channels if channels is not None else _channels()):
        resp = client.files_upload_v2(channel=cid, file_uploads=ups,
                                      initial_comment=caption)
        out.append({"channel": name, "id": cid, "ok": resp.get("ok")})
    return out


def caption_for(week_label):
    md = ".".join((week_label or "").split(".")[:2])
    return "🏆 Alphalete Organization Override Bulletin — WE {}".format(md)


def dd_subject(week_label):
    """The DD bulletin's subject, matching the VA's real send verified against
    alphaletereporting@gmail.com on 2026-07-23: 'Alphalete Organization Bulletin
    WE 7.19' — no year, same WE m.d shape as the override subject."""
    md = ".".join((week_label or "").split(".")[:2])
    return "Alphalete Organization Bulletin WE {}".format(md)


def dd_caption(week_label):
    md = ".".join((week_label or "").split(".")[:2])
    return "🏆 Alphalete Organization Bulletin — WE {}".format(md)


def send_dd(*, do_send=False, preview=False, force=False, out_dir=None,
            credico="auto"):
    """Build → render → (optionally) publish the DD / Organization bulletin.

    Two pages: the leaders page and the by-ICD breakdown. Dry run by default —
    do_send=False and preview=False builds everything, resolves every recipient
    and prints what would go where, but nothing leaves the machine."""
    from automations.override_bulletin import dd_build as DB
    from automations.override_bulletin import dd_data as D

    d = D.load(credico=credico)
    out = Path(out_dir) if out_dir else DB.OUT_DIR
    week_label = d["weeks"][0] if d["weeks"] else ""
    md = ".".join(week_label.split(".")[:2]) or "unknown"
    html_paths = DB.build(out_dir=out, data=d)
    png_paths = DB.render_png(html_paths, out_dir=out,
                              stem="Organization-Bulletin-WE-{}".format(md))
    names = [p.name for p in png_paths]

    subject, caption = dd_subject(week_label), dd_caption(week_label)
    to_addrs, missing = (list(PREVIEW_TO), []) if preview else recipients()

    print("\nweek        : {}".format(week_label))
    print("headline    : ${:,.2f} across {} active ICDs".format(
        d["headline"] or 0.0, d["org_count"]))
    print("leaders     : {}".format(", ".join(
        "{} ${:,.0f}".format(p["name"].split()[0], p["week"]) for p in d["podium"])))
    print("pages       : {}".format(", ".join(str(p) for p in png_paths)))
    print("subject     : {}".format(subject))
    print("slack       : {}".format(
        ", ".join("{} ({})".format(n, c) for n, c in _channels(dd=True))))
    print("email to    : {} address(es)".format(len(to_addrs)))
    for a in to_addrs:
        print("    • {}".format(a))
    if missing:
        print("⚠ contact group(s) NOT FOUND: {} — the distro is INCOMPLETE".format(
            ", ".join(missing)))

    # build() already listed every problem above, ✗ for blocking and · for the
    # rest — repeating them here would just push the recipient list off screen.
    blocking = d.get("blocking") or []
    print("blocking    : {}".format(
        "none" if not blocking else "{} ✗ above — --send is refused".format(
            len(blocking))))

    if not (do_send or preview):
        print("\nDRY RUN — nothing posted, nothing emailed. "
              "Re-run with --dd --preview (email Megan only) or --dd --send.")
        return {"published": False, "dry_run": True, "week": week_label,
                "png": [str(p) for p in png_paths], "to": to_addrs,
                "missing": missing, "blocking": blocking}

    # A blocking problem means a figure ON THE PAGE is wrong, not just short.
    # Preview still goes out — that is how a broken one gets looked at — but the
    # org does not see it until the problem is gone or someone overrides on purpose.
    if blocking and do_send and not force:
        print("\nREFUSING TO SEND — {} blocking problem(s) above. Fix them, or "
              "pass --force to publish anyway.".format(len(blocking)))
        return {"published": False, "reason": "blocking problems",
                "week": week_label, "blocking": blocking}
    if blocking and do_send and force:
        print("\n⚠ --force: publishing with {} blocking problem(s) "
              "UNRESOLVED.".format(len(blocking)))
    if missing and do_send:
        raise SystemExit("refusing to send: contact group(s) missing: {}. Fix the "
                         "group name(s) in alphaletereporting@gmail.com's contacts "
                         "or pass the groups explicitly.".format(", ".join(missing)))
    if do_send and already_sent(week_label, DD_STATE_PATH) and not force:
        print("\nALREADY SENT for {} — not sending again (pass --force to "
              "override).".format(week_label))
        return {"published": False, "reason": "already sent", "week": week_label}

    result = {"week": week_label, "png": [str(p) for p in png_paths],
              "to": to_addrs, "blocking": blocking}
    if do_send:
        result["slack"] = post_slack(png_paths, caption, names,
                                     channels=_channels(dd=True))
        for r in result["slack"]:
            print("posted to {} ok={}".format(r["channel"], r.get("ok")))
    else:
        print("\n(preview: Slack post skipped — email only)")

    send_email(build_email(png_paths, week_label, to_addrs, subject=subject,
                           title="Alphalete Organization Bulletin"))
    print("emailed {} recipient(s): {}".format(len(to_addrs), subject))
    if do_send:
        mark_sent(week_label, DD_STATE_PATH)
    result["published"] = True
    return result


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
        description="Publish a bulletin (dry run unless --send/--preview)")
    ap.add_argument("--dd", action="store_true",
                    help="publish the DD / Organization bulletin (two pages) "
                         "instead of the Override Bulletin")
    ap.add_argument("--tab", default=F.LIVE_TAB,
                    help="source tab to build the bulletin from (default: the "
                         "live tab; use the sandbox copy while testing). "
                         "Override bulletin only.")
    ap.add_argument("--send", action="store_true",
                    help="REALLY publish: Slack every channel + email both groups")
    ap.add_argument("--preview", action="store_true",
                    help="email Megan only, post nothing to Slack")
    ap.add_argument("--force", action="store_true",
                    help="send again even though this week was already sent — "
                         "and, for --dd, publish despite blocking problems")
    ap.add_argument("--no-credico", action="store_true",
                    help="--dd: read the DD tab as it stands, without folding "
                         "Credico in (diagnostic; never for a real send)")
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args(argv)
    if a.send and a.preview:
        raise SystemExit("--send and --preview are mutually exclusive")
    if a.no_credico and not a.dd:
        raise SystemExit("--no-credico only applies to --dd")
    if a.dd:
        send_dd(do_send=a.send, preview=a.preview, force=a.force,
                out_dir=a.out_dir, credico=False if a.no_credico else "auto")
        return 0
    send(tab=a.tab, do_send=a.send, preview=a.preview, force=a.force,
         out_dir=a.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
