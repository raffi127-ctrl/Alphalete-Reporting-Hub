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
send goes to TEST_TO (Camila). Raf gets added only after Camila signs off.

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
REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "output" / "interviewers_retention"

# ONLY Camila while testing (Camila, 2026-11-11: "the email goes ONLY to me,
# never to Raf"). There is deliberately no production list and no --to flag.
TEST_TO = ["camilahornosk@gmail.com"]


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


def load_fixture(path: Path) -> Tuple[List[List[str]], Dict]:
    """A JSON stand-in for both reads, for tests and dry runs off-network:
    {"tab": [[...row...], ...],
     "daily": {"<owner>": {"2026-11-10": {"<interviewer>": [booked, showed]}}}}"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    daily = {}
    for owner, days in (data.get("daily") or {}).items():
        daily[owner] = {dt.date.fromisoformat(d): SimpleNamespace(by=by)
                        for d, by in days.items()}
    return data["tab"], daily


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
    from automations.shared import board_email_html as beh
    from automations.shared.report_email import FROM_ADDR
    from automations.scheduled_6_days_out.email_send import (
        PHOTO_EMBED_PX, PHOTO_IMG, _signature_html, _circular_photo_png,
        _SIGNATURE_TEXT)

    msg = EmailMessage()
    msg["From"] = FROM_ADDR
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
    cid_photo = make_msgid()[1:-1]
    rows.append(_text_row("Best,<br><br>" + _signature_html(f"<{cid_photo}>")))
    doc = ('<div style="font-family:Arial,Helvetica,sans-serif;color:#000">'
           '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
           f'width="100%" style="max-width:{render.MAX_W}px;border-collapse:collapse">'
           + "".join(rows) + "</table></div>")
    msg.set_content("\n".join([subject, "",
                               "Open the HTML version to see the podiums.", "",
                               _SIGNATURE_TEXT]))
    msg.add_alternative(doc, subtype="html")
    part = msg.get_payload()[-1]
    for cid, path in cids:
        # Inline (multipart/related), never attached. Our PNGs are 2x and at
        # most 1760px, under the inline cap, so the bytes pass through untouched.
        part.add_related(beh.inline_image_bytes(path), "image", "png", cid=f"<{cid}>")
    part.add_related(_circular_photo_png(PHOTO_IMG, PHOTO_EMBED_PX),
                     maintype="image", subtype="png", cid=f"<{cid_photo}>")
    return msg


# ---------------------------------------------------------------------- run
def run(*, week: Optional[str] = None, date: Optional[dt.date] = None,
        fixture: Optional[Path] = None, dry_run: bool = False, logfn=print) -> int:
    today = date or today_ct()
    yday = today - dt.timedelta(days=1)

    values, daily = load_fixture(fixture) if fixture else (read_tab(), None)
    weeks = build.parse_weeks(values, today)
    i = pick_week(weeks, week)
    wk = weeks[i]
    logfn(f"  {build.SOURCE_TAB}: {len(weeks)} week boxes; reporting {wk.label} "
          f"(row {wk.header_row}), {len(wk.rows)} interviewer rows")
    pod_int, pod_off = build.podiums(weeks, i)

    if daily is None:
        owners = sorted({r.owner for w in weeks[:2] for r in w.rows})
        daily = read_daily(owners, today, logfn=logfn)
    y_int, y_off, y_has = build.yesterday_boards(daily, yday)

    stamp = f"{today:%Y-%m-%d}"
    out = OUT_DIR / stamp
    boards = ([y_int, y_off] if y_has else []) + [pod_int, pod_off]
    paths = render.render_boards(boards, out, stem="interviewers-retention")
    named = dict(zip([b.title for b in boards], paths))

    images: List[Tuple[str, Path]] = []
    if y_has:
        images += [(y_int.title, named[y_int.title]), (y_off.title, named[y_off.title])]
    else:
        images.append((f"NOTE:<b>Yesterday ({yday:%A} {build.md(yday)}):</b> no 2nd rounds "
                       f"are recorded for that day on any ARS REPORT tab, so there is no "
                       f"yesterday table. (The weekly tab has no daily numbers, so nothing "
                       f"is estimated.)", Path()))
    images += [(pod_int.title, named[pod_int.title]), (pod_off.title, named[pod_off.title])]

    intro = (f"<b>Interviewers Retention</b> — 2nd rounds showed / booked. "
             f"Green = 50% or more, red = under 50%.<br>"
             f"Podiums: {html.escape(build.week_span(wk))}. "
             f"Yesterday: {yday:%A} {build.md(yday)}.")
    notes = [f"Sources: weekly = ARS Management 2.0 → '{build.SOURCE_TAB}' → week box "
             f"{html.escape(wk.label)} → columns 2nd R BOOKED / 2nd R SHOWED. "
             f"Yesterday = each owner's ARS REPORT tab → '2ND RD SHOWED RETENTION' → "
             f"{build.md(yday)} B / S."]
    subject = f"[TEST] Interviewers Retention — {build.week_span(wk).split(' (')[0]}"
    msg = build_message(subject=subject, to=TEST_TO, intro=intro,
                        images=images, notes=notes)
    out.mkdir(parents=True, exist_ok=True)
    eml = out / "interviewers-retention.eml"
    eml.write_bytes(bytes(msg))
    logfn(f"  boards: {', '.join(p.name for p in paths)} -> {out}")
    logfn(f"  yesterday {yday}: {'%d interviewers' % len(y_int.lines) if y_has else 'NO DATA'}")
    logfn(f"  podiums: {len(pod_int.lines)} interviewers "
          f"({pod_int.green} green / {pod_int.red} red), {len(pod_off.lines)} offices "
          f"({pod_off.green} green / {pod_off.red} red)")
    if dry_run:
        logfn(f"[dry run] nothing sent. Preview: {eml}")
        return 0
    from automations.shared.report_email import send_message
    send_message(msg)
    logfn(f"  sent to {', '.join(TEST_TO)} ({len(bytes(msg)) / 1024:.0f} KB)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="build + preview, send nothing")
    ap.add_argument("--week", help="week box label as the tab writes it, e.g. 11/2 (default: newest)")
    ap.add_argument("--date", help="run as if today were YYYY-MM-DD (yesterday = the day before)")
    ap.add_argument("--fixture", help="JSON stand-in for the Sheet reads (testing)")
    a = ap.parse_args(argv)
    return run(week=a.week, date=dt.date.fromisoformat(a.date) if a.date else None,
               fixture=Path(a.fixture) if a.fixture else None, dry_run=a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
