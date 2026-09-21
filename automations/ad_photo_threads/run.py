"""Ad Photo Threads — preview a day's screenshots grouped by ad.

    # what today would post, as a page you can open (downloads the shots):
    python -m automations.ad_photo_threads.run --dry-run

    # a past day, text summary only (fast, no downloads):
    python -m automations.ad_photo_threads.run --dry-run --date 2026-09-18 --no-images

Posting is NOT built yet: the thread layout (one thread per ad vs one per day)
is waiting on Raf. Until then the only mode is --dry-run.

Python 3.9-safe (runs on the mini): no runtime `X | Y`, no 3.10+ syntax.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import sys
from pathlib import Path

from automations.ad_photo_threads import collect

REPO = Path(__file__).resolve().parents[2]


def summary(rep: collect.DayReport) -> str:
    lines = [f"Ad photo threads — {rep.day:%a %m/%d/%Y}"]
    total = len(rep.candidates)
    shot = sum(1 for c in rep.candidates if c.images)
    lines.append(f"  {total} candidates on the sheet, {shot} with a screenshot, "
                 f"{len(rep.unpaired)} replies to check by hand")
    for label in rep.missing_tabs:
        lines.append(f"  !! '{label}' has no tab on the interviewers sheet yet — skipped")
    for label in rep.missing_threads:
        lines.append(f"  !! no '{label}' 1st-rounds thread found in Slack")
    groups = rep.by_ad()
    order = sorted((k for k in groups if k), key=lambda k: -len(groups[k]))
    for key in order + ([None] if None in groups else []):
        cs = groups[key]
        name = rep.book.display(key) if key else "?? Title not recognised"
        n_img = sum(len(c.images) for c in cs)
        lines.append(f"\n  {name}  ({len(cs)} people, {n_img} photos)")
        for c in cs:
            mark = "✅" if c.qualify.lower().startswith("qualif") else "❌"
            extra = "" if key else f"   sheet title: {c.title_raw!r}"
            lines.append(f"    {mark} {c.name:<28} {c.stars or '':<7} "
                         f"{len(c.images)} photo(s){' (group)' if c.shared else ''}  [{c.interviewer}]{extra}")
    for u in rep.unpaired:
        lines.append(f"\n  CHECK BY HAND ({u['source']}): {len(u['images'])} photos, "
                     f"names in reply: {', '.join(u['names']) or '(none on sheet)'}")
    return "\n".join(lines)


def _save_image(f: dict, out_dir: Path) -> str:
    from automations.sara_down.run import _download_image
    data, subtype = _download_image(f)
    name = f"{f.get('id', 'img')}.{subtype or 'png'}"
    (out_dir / name).write_bytes(data)
    return name


def preview_html(rep: collect.DayReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    e = html.escape
    parts = [f"<!doctype html><meta charset=utf-8><title>Ad photos {rep.day}</title>",
             "<style>body{font:15px system-ui;margin:24px;background:#fff;color:#111}"
             "h2{margin:28px 0 6px}.c{display:inline-block;width:300px;margin:6px;"
             "vertical-align:top}.c img{width:300px;border:1px solid #ccc}"
             ".x{color:#b00}</style>",
             f"<h1>Ad photo threads — {rep.day:%A %m/%d/%Y}</h1>"]
    groups = rep.by_ad()
    order = sorted((k for k in groups if k), key=lambda k: -len(groups[k]))
    for key in order + ([None] if None in groups else []):
        cs = groups[key]
        title = rep.book.display(key) if key else "Title not recognised"
        parts.append(f"<h2>{e(title)} <small>({len(cs)})</small></h2>")
        for c in cs:
            ok = c.qualify.lower().startswith("qualif")
            imgs = "".join(f"<img src='{e(_save_image(f, out_dir))}'>" for f in c.images) \
                or "<i>no screenshot</i>"
            parts.append(f"<div class=c><b>{'✅' if ok else '❌'} {e(c.name)}</b> "
                         f"{e(c.stars)}<br><small>{e(c.interviewer)}"
                         f"{'' if key else ' · sheet: ' + e(c.title_raw)}</small>"
                         f"<br>{imgs}</div>")
    if rep.unpaired:
        parts.append("<h2 class=x>Check by hand</h2>")
        for u in rep.unpaired:
            imgs = "".join(f"<img src='{e(_save_image(f, out_dir))}'>" for f in u["images"])
            parts.append(f"<div class=c><small>{e(u['text'][:300])}</small><br>{imgs}</div>")
    page = out_dir / "index.html"
    page.write_text("\n".join(parts), encoding="utf-8")
    return page


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, Central)")
    ap.add_argument("--dry-run", action="store_true", required=True,
                    help="Preview only. Posting isn't built yet.")
    ap.add_argument("--no-images", action="store_true",
                    help="Text summary only; skip downloading the screenshots.")
    a = ap.parse_args(argv)
    day = dt.date.fromisoformat(a.date) if a.date else collect.central_today()

    rep = collect.build(day)
    print(summary(rep))
    if not a.no_images:
        page = preview_html(rep, REPO / "output" / "ad_photo_threads" / day.isoformat())
        print(f"\nPreview: {page}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
