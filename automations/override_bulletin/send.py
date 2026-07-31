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
# Soft-launch distro for --test: email only / no Slack, before flipping to the
# full org distro. Megan 2026-07-30 narrowed it to just Megan / Raf / Carlos
# (dropped Eve/alphaletereporting@) for the tomorrow review send.
TEST_TO = ["Meganhidalgo1191@gmail.com", "raffi127@gmail.com",
           "CarlosHidalgo349@gmail.com"]

STATE_DIR = Path.home() / ".config" / "recruiting-report"
STATE_PATH = STATE_DIR / "override_bulletin_last_sent.txt"
DD_STATE_PATH = STATE_DIR / "dd_bulletin_last_sent.txt"
# Separate state for the soft-launch test send, so a week of test emails never
# marks the real distro as "already sent".
DD_TEST_STATE_PATH = STATE_DIR / "dd_bulletin_test_last_sent.txt"


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
    # CENTRED, and sized to the render (Megan 2026-07-24: "I don't like all the
    # blank space on the right"). The page renders 1180 CSS px wide, so capping
    # at 1000 both shrank the figures AND left the bulletin pinned to the left of
    # a full-width black block — the dead space she saw. A centring <table> is
    # what actually works in Gmail/Outlook; `margin:0 auto` alone does not.
    imgs = "".join(
        '<img src="cid:{}" width="1180" style="width:100%;max-width:1180px;'
        'height:auto;display:block;border:0">'.format(c)
        for c in cids)
    html = ('<div style="font-family:Arial,Helvetica,sans-serif;background:#000;'
            'padding:0;margin:0">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'border="0" style="background:#000;border-collapse:collapse">'
            '<tr><td align="center" style="padding:0">'
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            'style="width:100%;max-width:1180px;border-collapse:collapse">'
            '<tr><td style="padding:0">{}</td></tr>'
            '</table></td></tr></table></div>'.format(imgs))
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


CORRECTIONS_CHANNEL = "#claudecorrections-and-requests"


def alert_corrections(text):
    """Post a data-gap heads-up to #claudecorrections-and-requests (Megan
    2026-07-30: look for all data each week; if something isn't there, notify us
    in Slack but still send). Best-effort — a failed alert never stops the send."""
    try:
        from automations.shared import slack_metrics_post as smp
        smp._client().chat_postMessage(channel=CORRECTIONS_CHANNEL, text=text)
        print("posted data-gap alert to {}".format(CORRECTIONS_CHANNEL))
        return True
    except Exception as e:  # noqa: BLE001
        print("⚠ could not post corrections alert ({}: {})".format(
            type(e).__name__, str(e)[:120]))
        return False


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


def send_dd(*, do_send=False, preview=False, test=False, force=False,
            notify=False, to=None, out_dir=None, credico="auto"):
    """Build → render → (optionally) publish the DD / Organization bulletin.

    Two pages: the leaders page and the by-ICD breakdown. Dry run by default —
    do_send=False and preview=False builds everything, resolves every recipient
    and prints what would go where, but nothing leaves the machine.

    `test` is the soft-launch mode: recipients are the 4-person TEST_TO group and
    NOTHING posts to Slack (email only). Combine with --send to actually email
    them; the scheduled Thursday send runs `--dd --test --send` for the first
    week before the full distro is turned on."""
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
    if to:                                 # explicit recipient override (a one-off
        to_addrs, missing = list(to), []   # small-audience send, e.g. tomorrow's
    elif preview:                          # Raf/Carlos/Megan run)
        to_addrs, missing = list(PREVIEW_TO), []
    elif test:
        to_addrs, missing = list(TEST_TO), []
    else:
        to_addrs, missing = recipients()
    # A custom `to` is a small-audience email, so keep Slack off unless it's a
    # real full-distro send.
    slack_on = do_send and not test and not to

    print("\nweek        : {}".format(week_label))
    print("headline    : ${:,.2f} across {} active ICDs".format(
        d["headline"] or 0.0, d["org_count"]))
    print("leaders     : {}".format(", ".join(
        "{} ${:,.0f}".format(p["name"].split()[0], p["week"]) for p in d["podium"])))
    print("pages       : {}".format(", ".join(str(p) for p in png_paths)))
    print("subject     : {}".format(subject))
    print("mode        : {}".format("TEST (email only, no Slack)" if test
                                    else "preview" if preview else "full distro"))
    print("slack       : {}".format("(none — test/preview)" if not slack_on else
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
              "Re-run with --dd --preview (email Megan only), --dd --test --send "
              "(email the 4-person soft-launch group), or --dd --send.")
        return {"published": False, "dry_run": True, "week": week_label,
                "png": [str(p) for p in png_paths], "to": to_addrs,
                "missing": missing, "blocking": blocking}

    # Data-gap alert (Megan 2026-07-30): look for all data each week; if a source
    # isn't in yet (Credico pending, a missing DD row, a stale week), post a
    # heads-up to #claudecorrections-and-requests — but STILL send. Credico's own
    # timing is unpredictable, so it must never hold the whole org bulletin.
    gaps = list(blocking)
    if d.get("credico_pending"):
        gaps.append("Credico not available this week — bulletin sent without it, "
                    "re-send to fold it in once it posts")
    if do_send and notify and gaps:
        alert_corrections("⚠ DD Bulletin WE {} sent with data gap(s):\n• {}".format(
            week_label, "\n• ".join(gaps[:10])))

    # A blocking problem means a figure ON THE PAGE is wrong, not just short.
    # In NOTIFY (go-live) mode we alert and send anyway (above); otherwise the
    # org does not see it until it is fixed or someone overrides with --force.
    if blocking and do_send and not force and not notify:
        print("\nREFUSING TO SEND — {} blocking problem(s) above. Fix them, pass "
              "--force, or use --notify to alert-and-send.".format(len(blocking)))
        return {"published": False, "reason": "blocking problems",
                "week": week_label, "blocking": blocking}
    if blocking and do_send and (force or notify):
        print("\n⚠ publishing with {} blocking problem(s) — alerted to {}.".format(
            len(blocking), CORRECTIONS_CHANNEL))
    if missing and do_send:
        raise SystemExit("refusing to send: contact group(s) missing: {}. Fix the "
                         "group name(s) in alphaletereporting@gmail.com's contacts "
                         "or pass the groups explicitly.".format(", ".join(missing)))
    state_path = DD_TEST_STATE_PATH if test else DD_STATE_PATH
    if do_send and already_sent(week_label, state_path) and not force:
        print("\nALREADY SENT for {} ({}) — not sending again (pass --force to "
              "override).".format(week_label, "test" if test else "full"))
        return {"published": False, "reason": "already sent", "week": week_label}

    result = {"week": week_label, "png": [str(p) for p in png_paths],
              "to": to_addrs, "blocking": blocking, "test": test}
    if slack_on:
        result["slack"] = post_slack(png_paths, caption, names,
                                     channels=_channels(dd=True))
        for r in result["slack"]:
            print("posted to {} ok={}".format(r["channel"], r.get("ok")))
    else:
        print("\n({} — Slack post skipped, email only)".format(
            "test" if test else "preview"))

    send_email(build_email(png_paths, week_label, to_addrs, subject=subject,
                           title="Alphalete Organization Bulletin"))
    print("emailed {} recipient(s): {}".format(len(to_addrs), subject))
    if do_send and not to:                 # a custom `to` is a one-off — don't
        mark_sent(week_label, state_path)  # burn the week's send-state on it
    result["published"] = True
    return result


def send(*, tab=None, do_send=False, preview=False, test=False, force=False,
         out_dir=None):
    """Build → render → (optionally) publish. Returns a summary dict.

    do_send=False and preview=False is a DRY RUN: everything is built and every
    recipient resolved, but nothing leaves the machine.

    `test` is the soft-launch mode (Megan 2026-07-25): email the 4-person TEST_TO
    group (Megan, Eve, Carlos, Raf) and post NOTHING to Slack — a week of preview
    to the leaders before the full-org distro. Combine with do_send to email.

    The bulletin renders OUR OWN fill — the SANDBOX copy tab that
    override_bulletin.run fills from the real sources — NOT the VA's live tab.
    Her tab is a REFERENCE for comparison, not a data source; rendering it would
    just re-publish her work (Megan 2026-07-25). Pass tab=F.LIVE_TAB only once we
    have actually taken the live tab over."""
    tab = tab or F.SANDBOX_TAB
    out_dir = Path(out_dir) if out_dir else B.OUT_DIR

    # One read of the tab, not two — build() would re-read it for the same rows.
    week_labels, combined, regular, captainship, program = B.read_data(tab)
    week_label = week_labels[0] if week_labels else ""
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "override-bulletin.html"
    html_path.write_text(
        B.build_html(week_labels, combined, regular, captainship, program),
        encoding="utf-8")
    print("built {} (week {!r}; combined {}, captainship {}, program {})".format(
        html_path, week_label, len(combined), len(captainship), len(program)))
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

    # week_is_filled only asks whether the column has SOME data — a week can sail
    # through it while an entire COMPONENT is missing. That is not hypothetical:
    # on Fri 2026-07-24 the live 7.19 column was filled with regular overrides
    # while all five DD-sourced captain bonuses and Raf's special were blank,
    # because the Tableau views feeding them were down. The bulletin then read
    # "$57,749 this week" against $147,901, with five captains at $0 and steep
    # fake declines on every card. Blank sub-rows now surface as series=None
    # (see build.read_data), so we can refuse to publish that to the org.
    unsourced = [r["name"] for r in (captainship + program) if r.get("week") is None]
    if unsourced:
        print("\n⚠ CAPTAINSHIP/PROGRAM not sourced for {} ({}): {}".format(
            week_label, len(unsourced), ", ".join(unsourced)))
        print("  Their weekly cells are BLANK, so every total above is short by "
              "their captain/special money.")

    subject = B.email_subject(week_label)
    caption = caption_for(week_label)
    slack_on = do_send and not test and not preview   # test/preview = email-only
    if preview:
        to_addrs, missing = list(PREVIEW_TO), []
    elif test:
        to_addrs, missing = list(TEST_TO), []
    else:
        to_addrs, missing = recipients()

    print("\nweek        : {}".format(week_label))
    print("source tab  : {!r}".format(tab))
    print("image       : {}".format(png_path))
    print("subject     : {}".format(subject))
    print("mode        : {}".format(
        "test (4-person soft launch, email only)" if test
        else "preview (Megan only)" if preview else "FULL distro + Slack"))
    print("slack       : {}".format(
        ", ".join("{} ({})".format(n, c) for n, c in _channels())
        if slack_on else "(none — {})".format("test" if test else "preview/dry")))
    print("email to    : {} address(es)".format(len(to_addrs)))
    for a in to_addrs:
        print("    • {}".format(a))
    if missing:
        print("⚠ contact group(s) NOT FOUND: {} — the distro is INCOMPLETE".format(
            ", ".join(missing)))

    print("captain/spec: {}".format(
        "all sourced" if not unsourced
        else "{} still $0 — will send anyway (matches the VA)".format(len(unsourced))))

    if not (do_send or preview):
        print("\nDRY RUN — nothing posted, nothing emailed. Re-run with --preview "
              "(email Megan only), --test --send (email the 4-person soft-launch "
              "group), or --send (full distro + Slack).")
        return {"published": False, "dry_run": True, "week": week_label,
                "png": str(png_path), "to": to_addrs, "missing": missing,
                "unsourced": unsourced}
    # Missing captain/special rows are a WARNING, not a blocker. The VA sends the
    # bulletin on schedule whether or not the captain bonuses have posted yet —
    # the numbers fill in over the following days — and Megan's rule (2026-07-24)
    # is to match her: "if the VA sent it out without the info then we would also
    # send it." Every send is still Megan-triggered (dry-run default), so this is
    # a heads-up, not a gate. It's the same $0-captain state she reviewed and
    # signed off on.
    if unsourced and do_send:
        print("\n⚠ publishing with {} captain/special row(s) still $0 (not yet "
              "posted): {}. Matches the VA, who sends on schedule regardless; "
              "the numbers update as they land.".format(
                  len(unsourced), ", ".join(unsourced)))
    if missing and do_send:
        raise SystemExit("refusing to send: contact group(s) missing: {}. Fix the "
                         "group name(s) in alphaletereporting@gmail.com's contacts "
                         "or pass the groups explicitly.".format(", ".join(missing)))
    if do_send and already_sent(week_label) and not force:
        print("\nALREADY SENT for {} — not sending again (pass --force to "
              "override).".format(week_label))
        return {"published": False, "reason": "already sent", "week": week_label}

    result = {"week": week_label, "png": str(png_path), "to": to_addrs, "test": test}
    if slack_on:
        result["slack"] = post_slack(png_path, caption, png_name)
        for r in result["slack"]:
            print("posted to {} ok={}".format(r["channel"], r.get("ok")))
    else:
        print("\n(email only — no Slack)")

    send_email(build_email(png_path, week_label, to_addrs))
    print("emailed {} recipient(s): {}".format(len(to_addrs), subject))
    # FLAG GAPS (Megan 2026-07-30 "send fast, flag gaps"): we send with whatever's
    # in — like the VA — but post a heads-up to #claudecorrections-and-requests
    # listing any captain/program numbers that hadn't posted yet, so someone can
    # re-send with --force once they land. Best-effort; a failed alert never
    # affects the send that already went.
    if unsourced and do_send:
        try:
            from automations.shared import slack_metrics_post as smp
            smp._client().chat_postMessage(
                channel="#claudecorrections-and-requests",
                text=("⚠ Override Bulletin WE {} sent (to {}) with {} captain/"
                      "program number(s) not yet posted: {}. Re-send with --force "
                      "once they land to fold them in.".format(
                          week_label, "test group" if test else "full distro",
                          len(unsourced), ", ".join(unsourced))))
            print("posted gap heads-up to #claudecorrections-and-requests")
        except Exception as e:  # noqa: BLE001
            print("⚠ gap alert failed ({}: {})".format(type(e).__name__, str(e)[:120]))
    if do_send:                                   # test or full — record the week
        mark_sent(week_label)
    result["published"] = True
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Publish a bulletin (dry run unless --send/--preview)")
    ap.add_argument("--dd", action="store_true",
                    help="publish the DD / Organization bulletin (two pages) "
                         "instead of the Override Bulletin")
    ap.add_argument("--tab", default=F.SANDBOX_TAB,
                    help="tab to build the bulletin from. Default is the SANDBOX "
                         "copy tab — OUR fill from the real sources. The VA's live "
                         "tab is a reference, not a source; pass it explicitly only "
                         "after we take the live tab over. Override bulletin only.")
    ap.add_argument("--send", action="store_true",
                    help="REALLY publish: Slack every channel + email both groups")
    ap.add_argument("--preview", action="store_true",
                    help="email Megan only, post nothing to Slack")
    ap.add_argument("--test", action="store_true",
                    help="soft launch: email the 4-person TEST_TO group "
                         "(Megan, Eve, Carlos, Raf), no Slack. Combine with "
                         "--send to actually email them. Works for both bulletins.")
    ap.add_argument("--force", action="store_true",
                    help="send again even though this week was already sent — "
                         "and, for --dd, publish despite blocking problems")
    ap.add_argument("--no-credico", action="store_true",
                    help="--dd: read the DD tab as it stands, without folding "
                         "Credico in (diagnostic; never for a real send)")
    ap.add_argument("--notify", action="store_true",
                    help="--dd go-live: alert #claudecorrections on any data gap "
                         "(Credico pending / missing row / stale week) and send "
                         "anyway, instead of refusing")
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args(argv)
    if a.send and a.preview:
        raise SystemExit("--send and --preview are mutually exclusive")
    if a.no_credico and not a.dd:
        raise SystemExit("--no-credico only applies to --dd")
    if a.test and a.preview:
        raise SystemExit("--test and --preview are mutually exclusive")
    if a.dd:
        send_dd(do_send=a.send, preview=a.preview, test=a.test, force=a.force,
                notify=a.notify, out_dir=a.out_dir,
                credico=False if a.no_credico else "auto")
        return 0
    send(tab=a.tab, do_send=a.send, preview=a.preview, test=a.test, force=a.force,
         out_dir=a.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
