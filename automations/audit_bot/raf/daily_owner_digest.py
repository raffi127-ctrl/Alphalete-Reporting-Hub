#!/usr/bin/env python3
"""Daily per-owner scorecard digest (Raf's 2026-08-04 Loom ask).

Bundles ALL of a day's individual audit PDFs into ONE PDF per owner and DMs
each bundle to Rafael — "here's today's scorecards from <owner>". If an owner's
reps submitted five interviews, Raf gets one PDF with all five.

    venv/bin/python daily_owner_digest.py --dry-run        # build PDFs locally, DM nobody
    venv/bin/python daily_owner_digest.py                  # DM Rafael one PDF per owner
    venv/bin/python daily_owner_digest.py --date 2026-08-04
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RUNTIME = Path(__file__).parent.resolve()
sys.path.insert(0, str(RUNTIME))

from dotenv import load_dotenv
load_dotenv(RUNTIME / ".env")

import scorecards
from rosters import load_reps, owner_name

REPORTS_DIR = RUNTIME.parent / "reports"
OUT_DIR = RUNTIME / "owner_digests"
CT = ZoneInfo("America/Chicago")
UNASSIGNED = "__unassigned__"


def _resolve_pdf(rec: dict) -> Path | None:
    """Find the on-disk audit PDF for a completion record (paths can be stale
    after the folder move, so fall back to the reports/ dir by basename)."""
    cand = rec.get("report_pdf")
    if cand:
        p = Path(cand)
        if p.exists():
            return p
        alt = REPORTS_DIR / p.name
        if alt.exists():
            return alt
    md = rec.get("report_md")
    if md:
        stem = Path(md).stem
        alt = REPORTS_DIR / f"{stem}.pdf"
        if alt.exists():
            return alt
    return None


def _uploader_name(uid: str | None) -> str:
    if not uid:
        return "Unknown rep"
    try:
        from slack_watcher import _user_display
        return _user_display(uid)
    except Exception:
        return uid


def _score_for(rec: dict) -> str:
    md = rec.get("report_md")
    if not md:
        return "—"
    p = Path(md)
    if not p.exists():
        p = REPORTS_DIR / f"{Path(md).stem}.md"
    val = scorecards._extract_overall_score(p) if p.exists() else None
    return f"{val:g}/10" if val is not None else "—"


def group_by_owner(day: str) -> dict[str, list[dict]]:
    records = scorecards._enrich_with_slack_uploaders(scorecards._load_all_completions())
    reps = load_reps()
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        if (r.get("ts", "") or "")[:10] != day:
            continue
        uid = r.get("_uploader_user_id")
        owner_id = (reps.get(uid) or {}).get("owner_id") if uid else None
        groups[owner_id or UNASSIGNED].append(r)
    return groups


_MONTHS = ["", "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def _long_date(day: str) -> str:
    try:
        y, m, d = (int(x) for x in day.split("-"))
        return f"{_MONTHS[m]} {d}, {y}"
    except Exception:
        return day


def _cover_pdf(office: str, day: str, rows: list[tuple[str, str]], out_dir: Path) -> Path | None:
    """Render a cover page identifying the office/ICD + the day's submissions."""
    row_html = "".join(
        f'<div class="row"><span>{rep}</span><span class="sc">{score}</span></div>'
        for rep, score in rows
    ) or '<div class="row"><span>No readable scorecards</span><span></span></div>'
    n = len(rows)
    html = f"""<html><head><meta charset="utf-8"><style>
      @page {{ size: Letter; margin: 0; }}
      body {{ font-family: Georgia, 'Times New Roman', serif; margin: 0; color: #1a1a1a; }}
      .top {{ background: #111114; color: #E7B84B; padding: 64px 64px 44px; }}
      .brand {{ font-size: 13px; letter-spacing: 3px; text-transform: uppercase; color: #E7B84B; }}
      .label {{ font-size: 12px; letter-spacing: 2px; text-transform: uppercase; color: #B8862A; margin-top: 26px; }}
      .office {{ font-size: 46px; font-weight: bold; margin: 4px 0 6px; color: #ffffff; line-height: 1.05; }}
      .date {{ font-size: 17px; color: #CBB06A; }}
      .body {{ padding: 40px 64px; }}
      .h {{ font-size: 12px; letter-spacing: 2px; text-transform: uppercase; color: #8A6D1F;
            border-bottom: 2px solid #E7B84B; padding-bottom: 8px; margin-bottom: 8px; }}
      .row {{ display: flex; justify-content: space-between; padding: 13px 2px;
              border-bottom: 1px solid #eee; font-size: 18px; }}
      .sc {{ font-weight: bold; }}
      .count {{ font-size: 14px; color: #666; margin-top: 16px; }}
      .foot {{ position: fixed; bottom: 40px; left: 64px; right: 64px; font-size: 11px;
               color: #999; border-top: 1px solid #eee; padding-top: 12px; }}
    </style></head><body>
      <div class="top">
        <div class="brand">Lucy &middot; 2nd Round Interview Audits</div>
        <div class="label">Office / ICD</div>
        <div class="office">{office}</div>
        <div class="date">{_long_date(day)}</div>
      </div>
      <div class="body">
        <div class="h">Today's Submissions</div>
        {row_html}
        <div class="count">{n} interview{'s' if n != 1 else ''} audited &middot; full scorecards on the following pages</div>
      </div>
      <div class="foot">Generated by Lucy &middot; Alphalete Reporting Hub</div>
    </body></html>"""
    try:
        from weasyprint import HTML
        out_dir.mkdir(parents=True, exist_ok=True)
        cover = out_dir / f"_cover_{day}.pdf"
        HTML(string=html).write_pdf(str(cover))
        return cover
    except Exception as e:
        print(f"  ! cover render failed: {e}")
        return None


def _merge(office: str, day: str, records: list[dict], out_path: Path) -> tuple[int, list[str]]:
    from pypdf import PdfWriter
    # First pass: resolve each audit's PDF + score, in chronological order.
    items, rows, lines = [], [], []
    for r in sorted(records, key=lambda x: x.get("ts", "")):
        name = _uploader_name(r.get("_uploader_user_id"))
        score = _score_for(r)
        pdf = _resolve_pdf(r)
        if pdf:
            items.append(pdf)
            rows.append((name, score))
            lines.append(f"• {name} — {score}")
        else:
            lines.append(f"• {name} — (PDF not found)")
    if not items:
        return 0, lines
    writer = PdfWriter()
    cover = _cover_pdf(office, day, rows, out_path.parent)
    if cover:
        writer.append(str(cover))
    for pdf in items:
        try:
            writer.append(str(pdf))
        except Exception as e:
            print(f"  ! could not append {pdf.name}: {e}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)
    if cover:
        try:
            cover.unlink()
        except Exception:
            pass
    return len(items), lines


def run(day: str, dry_run: bool) -> None:
    groups = group_by_owner(day)
    if not groups:
        print(f"No submissions for {day}.")
        return

    # Named owners first (alpha), Unassigned last.
    def sort_key(k):
        return (k == UNASSIGNED, ("Unassigned" if k == UNASSIGNED else owner_name(k)).lower())

    for key in sorted(groups, key=sort_key):
        recs = groups[key]
        name = "Unassigned" if key == UNASSIGNED else owner_name(key)
        safe = "unassigned" if key == UNASSIGNED else key
        out = OUT_DIR / f"scorecards_{day}_{safe}.pdf"
        n, lines = _merge(name, day, recs, out)
        header = f":clipboard: *Today's scorecards — {name}*  ({n} submission{'s' if n != 1 else ''})"
        body = header + "\n" + "\n".join(lines)
        print(f"\n=== {name}: {n} PDF(s) -> {out if n else '(none)'}")
        print(body)
        if not dry_run and n:
            from slack_watcher import web
            ch = os.getenv("RAFAEL_DM_CHANNEL")
            if not ch:
                print("  ! RAFAEL_DM_CHANNEL not set — skipping DM")
                continue
            web.files_upload_v2(channel=ch, file=str(out), filename=out.name,
                                initial_comment=body)
            print("  -> DM'd Rafael")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(CT).date().isoformat(),
                    help="YYYY-MM-DD (default: today, Central)")
    ap.add_argument("--dry-run", action="store_true", help="build PDFs, DM nobody")
    args = ap.parse_args()
    run(args.date, args.dry_run)
