r"""Interviewers Retention -- the two podiums, by email (Camila, 2026-11-11).

Camila's weekly report (her 'Interviewers Retention' dashboard) rebuilt as a Hub
module, with the three changes Raf asked for:

  1. every podium row ends in 4 columns: that interviewer's / office's 2nd-round
     % for each of the 4 weeks BEFORE the week shown, oldest to newest, in the
     same green (>= 50%) / red (< 50%);
  2. at the top, YESTERDAY's 2nd rounds (booked / showed / %) by interviewer and
     by office -- from the ARS REPORT daily blocks, the only source with daily
     numbers. If no ARS REPORT tab has anything for yesterday, the mail SAYS so;
     it never fills the gap with a weekly number;
  3. each picture is cropped to the board itself (no grey frame, no side
     margins), at most ~880px wide, big type, inline in the email body.

The email body, top to bottom:
    Yesterday by interviewer   Yesterday by office
    Podium by interviewer      Podium by office       (the newest week box)

TESTING ONLY: there is no production recipient in this file on purpose. Every
hand run goes to TEST_TO (Camila only). --production sends to PROD_TO
(Raf, Perla, Camila); the daily 6 PM CENTRAL send is deploy/interviewers_retention.sh
via the com.alphalete.interviewers-retention LaunchAgent on Camila's Mac
(her Gmail app password lives there):
    python -m automations.day_orchestrator.install_agent interviewers-retention

    python -m automations.interviewers_retention.run --dry-run   # build + preview, send nothing
    python -m automations.interviewers_retention.run             # send to Camila only
    python -m automations.interviewers_retention.run --week 11/2 --date 2026-11-10
    python -m automations.interviewers_retention.run --fixture f.json --dry-run   # no Google

Sources (see build.py for the details):
    ARS Management 2.0 (1l4Q0SreuddKZrgXwb9MytF-EdPZH-H1hLsa69epq-n8)
        -> 'Interviewers Retention (Interviewer)' -> each week box
        -> columns '2nd R BOOKED' / '2nd R SHOWED' (found by header text)
    ARS REPORT workbooks (Camila's Drive) -> each owner's tab
        -> block '2ND RD SHOWED RETENTION' -> that day's B / S per interviewer
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import sys
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Sequence, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                   # noqa: BLE001
    pass

from automations.interviewers_retention import build, render

SHEET_ID = "1l4Q0SreuddKZrgXwb9MytF-EdPZH-H1hLsa69epq-n8"   # ARS Management 2.0
# AppStream 2nd rounds per office per day, written hourly by a Lucy
# (automations/second_round_retention) -- same sheet that module writes.
DATOS_SHEET_ID = "1JF1M-SYYbRnrp0dFr-IKxPiXMPdHPvGomyP6r4aSFZw"
REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "output" / "interviewers_retention"

# ONLY Camila while testing (Camila, 2026-11-11: "the email goes ONLY to me,
# never to Raf"). There is deliberately no production list and no --to flag.
TEST_TO = ["camilahornosk@gmail.com"]
# LIVE list (Camila, 2026-11-11): every day at 6 PM Central.
PROD_TO = ["raffi127@gmail.com",                  # Raf
           "perlafalabella@gmail.com",            # Perla
           "camilahornosk@gmail.com"]             # Camila
SEND_HOUR_CT = 18

# SENT FROM CAMILA'S OWN GMAIL (Camila, 2026-11-11), not the shared
# alphaletereporting@gmail.com robot. Gmail only lets a script in with an App
# Password (Google account -> Security -> 2-Step Verification -> App passwords),
# kept OUT of the repo in this file on the machine that sends (or in the env var).
# Signed as Camila, so Eve's robot signature and photo are not used here.
SENDER = "camilahornosk@gmail.com"
SENDER_NAME = "Camila Hornos Kraschinsky"
SENDER_PW_FILE = Path.home() / ".config" / "recruiting-report" / "camila-gmail-app-password"
SENDER_PW_ENV = "CAMILA_GMAIL_APP_PASSWORD"


def today_ct() -> dt.date:
    from zoneinfo import ZoneInfo
    return dt.datetime.now(ZoneInfo("America/Chicago")).date()


# ------------------------------------------------------------------ reading
def read_tab() -> List[List[str]]:
    from automations.recruiting_report import fill
    sh = fill.open_by_key(SHEET_ID)
    return fill.worksheet_ci(sh, build.SOURCE_TAB).get_all_values()


def read_daily(owners: List[str], today: dt.date, logfn=print):
    """{owner: {date: SecondRounds}} from the ARS REPORT 2nd-round blocks.

    Same blocks and same parser as call_list_to_2nd.read_second_rounds, but it
    first asks each workbook which tabs EXIST TODAY instead of trusting the
    cached owner-tab-index.json. That cache can still name a tab someone has
    since renamed or deleted (2026-11-11: 'Steve McElwee'), and one stale name
    in a batch read makes Google refuse the whole workbook (400 "Unable to parse
    range"). Here a missing tab costs only that owner, and the run says which.
    The shared cache file is never rewritten from this report."""
    from automations.recruiting_report import fill
    from automations.first_to_second_below_mark import ars_reports as ars
    from automations.call_list_to_2nd.run import (
        SECOND_BANNER, _col_letter, parse_second_block)

    # The tabs that really exist, per workbook (one call each).
    live: Dict[str, Tuple[object, List[str]]] = {}
    index: Dict[str, Tuple[str, str]] = {}
    for book, key in ars.ARS_WORKBOOKS.items():
        try:
            sh = fill.open_by_key(key)
            titles = [ws.title for ws in sh.worksheets()]
        except Exception as e:                       # noqa: BLE001
            logfn(f"  note: could not open {book!r}: {e}")
            continue
        live[book] = (sh, titles)
        for t in titles:
            if ars.TEMPLATE_TAB.lower() not in t.lower():
                index.setdefault(ars._key(t), (book, t))
    aliases = ars.load_aliases()

    by_book: Dict[str, List[Tuple[str, str]]] = {}
    for owner in owners:
        hit = ars.find_tab(owner, index, aliases)
        if hit is None:
            logfn(f"  note: {owner}: no ARS REPORT tab found (no yesterday numbers for this office)")
            continue
        by_book.setdefault(hit[0], []).append((owner, hit[1]))

    out: Dict[str, Dict[dt.date, object]] = {}
    for book, pairs in by_book.items():
        sh = live[book][0]
        q = lambda t: t.replace("'", "''")          # a quote in a tab name doubles in A1
        try:
            heads = sh.values_batch_get([f"'{q(tab)}'!1:1" for _, tab in pairs]).get("valueRanges", [])
        except Exception as e:                       # noqa: BLE001
            logfn(f"  note: {book}: could not read ({e}); its offices get no yesterday numbers")
            continue
        wanted, ranges = [], []
        for (owner, tab), vr in zip(pairs, heads):
            row1 = (vr.get("values") or [[]])[0]
            c = next((j for j, v in enumerate(row1) if SECOND_BANNER in str(v).upper()), None)
            if c is None:
                logfn(f"  note: {owner} ({book} / {tab}): no '{SECOND_BANNER}' block")
                continue
            nxt = next((j for j in range(c + 1, len(row1)) if str(row1[j]).strip()), c + 60)
            wanted.append(owner)
            ranges.append(f"'{q(tab)}'!{_col_letter(c)}1:{_col_letter(nxt - 1)}")
        if not ranges:
            continue
        try:
            blocks = sh.values_batch_get(ranges).get("valueRanges", [])
        except Exception as e:                       # noqa: BLE001
            logfn(f"  note: {book}: could not read the 2nd-round blocks ({e})")
            continue
        for owner, vr in zip(wanted, blocks):
            out[owner] = parse_second_block(vr.get("values", []), today)
    logfn(f"  ARS REPORT 2nd-round blocks: {len(out)} of {len(owners)} offices read")
    return out


def load_fixture(path: Path):
    """A JSON stand-in for the three reads, for tests and dry runs off-network:
    {"tab": [[...row...], ...],
     "daily": {"<owner>": {"2026-11-10": {"<interviewer>": [booked, showed]}}},
     "datos": [[header...], [row...], ...]}            (optional)"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    daily = {}
    for owner, days in (data.get("daily") or {}).items():
        daily[owner] = {dt.date.fromisoformat(d): SimpleNamespace(by=by)
                        for d, by in days.items()}
    datos = build.parse_datos(data["datos"]) if data.get("datos") else None
    return data["tab"], daily, datos


def pick_week(weeks: List[build.Week], label: Optional[str]) -> int:
    if not weeks:
        raise SystemExit(f"no week boxes found on {build.SOURCE_TAB!r}")
    if label:
        want = build.norm(label)
        for i, w in enumerate(weeks):
            if build.norm(w.label) == want:
                return i
        raise SystemExit(f"week {label!r} not on the tab. Newest: "
                         + ", ".join(w.label for w in weeks[:6]))
    # The newest box, unless it was just inserted and has no 2nd rounds yet.
    return next((i for i, w in enumerate(weeks) if w.has_second_rounds), 0)


# -------------------------------------------------------------------- email
def _img_row(cid: str, alt: str, css_w: int) -> str:
    # Painted at the picture's own width and never wider (max-width), shrunk to
    # the screen on a phone (width:100%). No border, no frame: Raf's crop.
    return ('<tr><td style="padding:0 0 22px">'
            f'<img src="cid:{cid}" alt="{html.escape(alt)}" width="{css_w}" '
            f'style="display:block;width:100%;max-width:{css_w}px;height:auto">'
            '</td></tr>')


def _text_row(inner: str) -> str:
    return ('<tr><td style="padding:0 0 14px;font-family:Arial,Helvetica,sans-serif;'
            f'font-size:14px;color:#000">{inner}</td></tr>')


def build_message(*, subject: str, to: Sequence[str], intro: str,
                  images: List[Tuple[str, Path]], notes: List[str]) -> EmailMessage:
    from email.utils import formataddr
    from automations.shared import board_email_html as beh

    msg = EmailMessage()
    msg["From"] = formataddr((SENDER_NAME, SENDER))
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    rows = [_text_row(intro)]
    cids: List[Tuple[str, Path]] = []
    for label, path in images:
        if label.startswith("NOTE:"):
            rows.append(_text_row(f'<div style="padding:10px 12px;border:1px solid #d9ddd6;'
                                  f'background:#fafafa">{label[5:]}</div>'))
            continue
        cid = make_msgid()[1:-1]
        cids.append((cid, path))
        rows.append(_img_row(cid, label, render.css_width(path)))
    for n in notes:
        rows.append(_text_row(f'<span style="color:#5f6a63;font-size:12px">{n}</span>'))
    rows.append(_text_row(f"Best,<br><br><b>{SENDER_NAME}</b>"))
    doc = ('<div style="font-family:Arial,Helvetica,sans-serif;color:#000">'
           '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
           f'width="100%" style="max-width:{render.MAX_W}px;border-collapse:collapse">'
           + "".join(rows) + "</table></div>")
    msg.set_content("\n".join([subject, "",
                               "Open the HTML version to see the podiums.", "",
                               "Best,", SENDER_NAME]))
    msg.add_alternative(doc, subtype="html")
    part = msg.get_payload()[-1]
    for cid, path in cids:
        # Inline (multipart/related), never attached. Our PNGs are 2x and at
        # most 1760px, under the inline cap, so the bytes pass through untouched.
        part.add_related(beh.inline_image_bytes(path), "image", "png", cid=f"<{cid}>")
    return msg


def sender_password() -> str:
    import os
    raw = os.environ.get(SENDER_PW_ENV, "")
    if not raw and SENDER_PW_FILE.exists():
        raw = SENDER_PW_FILE.read_text(encoding="utf-8-sig")
    pw = "".join(raw.split())          # Google shows it in 4 groups with spaces
    if not pw:
        raise SystemExit(
            f"No Gmail app password for {SENDER}. Create one (Google account -> "
            f"Security -> 2-Step Verification -> App passwords) and save it, one line, "
            f"to {SENDER_PW_FILE} -- or set {SENDER_PW_ENV}. Never commit it.")
    return pw


def send(msg: EmailMessage) -> None:
    import smtplib
    import ssl
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(SENDER, sender_password())
        s.send_message(msg)


# ---------------------------------------------------------------------- run
def read_datos(logfn=print) -> Optional[List[build.DayRow]]:
    """AppStream's per-office, per-day 2nd rounds (tab 'Datos', refreshed hourly
    by a Lucy). None when it can't be read: the run then falls back to the
    weekly tab for offices and says so."""
    from automations.recruiting_report import fill
    try:
        sh = fill.open_by_key(DATOS_SHEET_ID)
        rows = build.parse_datos(fill.worksheet_ci(sh, build.DATOS_TAB).get_all_values())
    except Exception as e:                           # noqa: BLE001
        logfn(f"  note: could not read AppStream sheet ({e}); offices fall back to the weekly tab")
        return None
    weeks = sorted({r.week for r in rows})
    logfn(f"  AppStream '{build.DATOS_TAB}': {len(rows)} office-days, weeks "
          + ", ".join(build.md(w) for w in weeks[-6:]))
    return rows


def scheduled_gate(now_ct: dt.datetime, sent_flag: Path) -> Optional[str]:
    """Why a --scheduled pass should NOT send, or None to go ahead.

    launchd fires every hour on the Mac's own clock (Argentina, which moves
    against Central twice a year); only the fire in the 18:00 Central hour
    sends, and only once a day -- a Mac waking from sleep can deliver two
    missed fires at once, and nobody wants the email twice."""
    if now_ct.hour != SEND_HOUR_CT:
        return f"{now_ct:%H:%M} Central is not the {SEND_HOUR_CT}:00 send hour"
    if sent_flag.exists():
        return f"already sent today ({sent_flag.name})"
    return None


def run(*, week: Optional[str] = None, date: Optional[dt.date] = None,
        fixture: Optional[Path] = None, dry_run: bool = False,
        production: bool = False, scheduled: bool = False, logfn=print) -> int:
    from zoneinfo import ZoneInfo
    now_ct = dt.datetime.now(ZoneInfo("America/Chicago"))
    sent_flag = OUT_DIR / f"sent-{now_ct:%Y-%m-%d}.txt"
    if scheduled:
        why = scheduled_gate(now_ct, sent_flag)
        if why:
            logfn(f"  scheduled pass: not sending -- {why}")
            return 0
    to = PROD_TO if production else TEST_TO
    today = date or today_ct()
    yday = today - dt.timedelta(days=1)

    if fixture:
        values, daily, datos = load_fixture(fixture)
    else:
        values, daily, datos = read_tab(), None, read_datos(logfn=logfn)

    # ---- interviewers: the weekly tab
    weeks = build.parse_weeks(values, today)
    for w in weeks[:8]:
        logfn(f"    box {w.label:>6} (row {w.header_row}): {len(w.rows)} rows, "
              f"2nd R booked {sum(r.booked for r in w.rows)}")
    for label, why in build.SKIPPED:
        logfn(f"    SKIPPED box {label}: {why}")
    i = pick_week(weeks, week)
    wk = weeks[i]
    logfn(f"  {build.SOURCE_TAB}: {len(weeks)} week boxes; interviewers on {wk.label} "
          f"(row {wk.header_row}), {len(wk.rows)} interviewer rows")
    pod_int, pod_off = build.podiums(weeks, i)

    if daily is None:
        owners = sorted({r.owner for w in weeks[:2] for r in w.rows})
        daily = read_daily(owners, today, logfn=logfn)
    y_int, y_off, _ = build.yesterday_boards(daily, yday)

    # ---- offices: AppStream (Camila 11/11), the weekly tab only as a fallback
    off_src = "weekly tab"
    off_week_txt = build.week_span(wk)
    if datos:
        # Camila's offices = the owners on the newest week box of her tab.
        roster = sorted({r.owner for r in weeks[0].rows})
        datos, missing = build.match_offices(datos, roster)
        logfn(f"  AppStream offices matched to the roster: {len({r.office_id for r in datos})} "
              f"(roster: {len(roster)} owners)")
        if missing:
            logfn(f"  note: no AppStream office for: {', '.join(missing)}")
    if datos:
        have = sorted({r.week for r in datos})
        ow = build.last_full_week(today)
        if ow not in have:
            ow = have[-1]
        pod_off = build.office_podium_datos(datos, ow)
        y_off = build.yesterday_office_datos(datos, yday)
        off_src = "AppStream"
        off_week_txt = pod_off.subtitle.split(" · ")[0]
        logfn(f"  offices from AppStream: week of {build.md(ow)}, "
              f"4 weeks {', '.join(pod_off.history_labels)}")

    stamp = f"{today:%Y-%m-%d}"
    out = OUT_DIR / stamp
    boards = [b for b in (y_int, y_off) if b.lines] + [pod_int, pod_off]
    paths = render.render_boards(boards, out, stem="interviewers-retention")
    named = {id(b): p for b, p in zip(boards, paths)}

    def no_data(what: str, where: str) -> Tuple[str, Path]:
        return (f"NOTE:<b>{what} ({yday:%A} {build.md(yday)}):</b> no 2nd rounds are "
                f"recorded for that day in {where}, so there is no table. Nothing is "
                f"estimated.", Path())

    images: List[Tuple[str, Path]] = []
    images.append((y_int.title, named[id(y_int)]) if y_int.lines
                  else no_data("Yesterday by interviewer", "the ARS REPORT tabs"))
    images.append((y_off.title, named[id(y_off)]) if y_off.lines
                  else no_data("Yesterday by office", off_src))
    images += [(pod_int.title, named[id(pod_int)]), (pod_off.title, named[id(pod_off)])]

    intro = (f"<b>Interviewers Retention</b> — 2nd rounds showed / booked. "
             f"Green = 50% or more, red = under 50%.<br>"
             f"Yesterday: {yday:%A} {build.md(yday)}. "
             f"Podium by interviewer: {html.escape(build.week_span(wk))}. "
             f"Podium by office: {html.escape(off_week_txt)}.")
    notes = [f"Sources: interviewers = ARS Management 2.0 → '{build.SOURCE_TAB}' → week box "
             f"{html.escape(wk.label)} → 2nd R BOOKED / 2nd R SHOWED; yesterday by interviewer = "
             f"each owner's ARS REPORT tab → '2ND RD SHOWED RETENTION' → {build.md(yday)} B / S. "
             + (f"Offices = AppStream → Retention - Details (new), per office per day "
                f"(sheet {DATOS_SHEET_ID} → '{build.DATOS_TAB}', updated hourly by a Lucy)."
                if off_src == "AppStream" else
                "Offices = the same weekly tab (AppStream sheet could not be read).")]
    # The send time in the TEST subject, so Gmail doesn't fold each test into
    # the previous one's conversation (they all looked like "no new mail").
    subject = (f"Interviewers Retention — {today:%A} {build.md(today)}" if production else
               f"[TEST] Interviewers Retention — {today:%A} {build.md(today)} "
               f"({dt.datetime.now():%H:%M})")
    msg = build_message(subject=subject, to=to, intro=intro,
                        images=images, notes=notes)
    out.mkdir(parents=True, exist_ok=True)
    eml = out / "interviewers-retention.eml"
    eml.write_bytes(bytes(msg))
    logfn(f"  boards: {', '.join(p.name for p in paths)} -> {out}")
    logfn(f"  yesterday {yday}: {len(y_int.lines)} interviewers, {len(y_off.lines)} offices")
    logfn(f"  podiums: {len(pod_int.lines)} interviewers "
          f"({pod_int.green} green / {pod_int.red} red), {len(pod_off.lines)} offices "
          f"({pod_off.green} green / {pod_off.red} red, {off_src})")
    if dry_run:
        logfn(f"[dry run] nothing sent. Preview: {eml}")
        return 0
    send(msg)
    logfn(f"  sent from {SENDER} to {', '.join(to)} ({len(bytes(msg)) / 1024:.0f} KB)")
    if production:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        sent_flag.write_text(f"{dt.datetime.now().isoformat()} -> {', '.join(to)}\n", encoding="utf-8")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="build + preview, send nothing")
    ap.add_argument("--week", help="week box label as the tab writes it, e.g. 11/2 (default: newest)")
    ap.add_argument("--date", help="run as if today were YYYY-MM-DD (yesterday = the day before)")
    ap.add_argument("--fixture", help="JSON stand-in for the Sheet reads (testing)")
    ap.add_argument("--production", action="store_true",
                    help="send to Raf, Perla and Camila (default: Camila only)")
    ap.add_argument("--scheduled", action="store_true",
                    help="the LaunchAgent's pass: send only at 6 PM Central, once a day")
    a = ap.parse_args(argv)
    return run(week=a.week, date=dt.date.fromisoformat(a.date) if a.date else None,
               fixture=Path(a.fixture) if a.fixture else None, dry_run=a.dry_run,
               production=a.production, scheduled=a.scheduled)


if __name__ == "__main__":
    sys.exit(main())
