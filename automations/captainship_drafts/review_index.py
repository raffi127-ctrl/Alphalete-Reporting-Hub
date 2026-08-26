"""Build output/REVIEW-captainship-reports.html — one page listing today's 12
reports so the reviewer opens ONE file instead of hunting for twelve among
older dates.

Called automatically at the end of a --dry-run, and standalone:

    .venv\\Scripts\\python.exe automations/captainship_drafts/review_index.py
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from automations.captainship_drafts import config  # noqa: E402

_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"
INDEX_NAME = "REVIEW-captainship-reports.html"


def build_index(today: dt.date | None = None, *, logfn=print) -> Path:
    today = today or dt.date.today()
    reported = today - dt.timedelta(days=1)
    # Grouped by BLOCK, in block order (Eve 2026-08-26). A block is what gets
    # one link, one checkmark and one send, so the page people review has to
    # show the same groups the Slack thread does — otherwise "approve Fiber 2"
    # means reading a flat list and remembering who is in it.
    rows = []
    for block in config.BLOCKS:
        rows.append(f'<tr class="blk"><td colspan="3">{block.label} — '
                    f'{block.who}</td></tr>')
        for captain in block.members:
            f = _OUTPUT_DIR / (
                f"captainship_draft_{captain.key}_{today:%Y%m%d}.html")
            n_to = len([a for a in captain.to.split(",") if a.strip()])
            if f.exists():
                rows.append(
                    f'<tr><td><a href="{f.name}" target="_blank">'
                    f'{captain.display_name}</a></td>'
                    f'<td>{n_to} people</td>'
                    f'<td class="ok">ready</td></tr>')
            else:
                rows.append(
                    f'<tr><td>{captain.display_name}</td>'
                    f'<td>{n_to} people</td>'
                    f'<td class="no">NOT built</td></tr>')

    html = f"""<!doctype html>
<meta charset="utf-8">
<title>Review captainship reports</title>
<style>
 body{{font-family:Arial,Helvetica,sans-serif;max-width:760px;margin:32px auto;
      padding:0 16px;color:#111}}
 h1{{font-size:22px;margin:0 0 4px}}
 .sub{{color:#555;margin:0 0 20px}}
 table{{border-collapse:collapse;width:100%}}
 td,th{{border-bottom:1px solid #e3e3e3;padding:10px 8px;text-align:left}}
 th{{font-size:12px;text-transform:uppercase;color:#666}}
 a{{color:#1a56c4;font-weight:bold;text-decoration:none}}
 a:hover{{text-decoration:underline}}
 .ok{{color:#137333}} .no{{color:#b3261e;font-weight:bold}}
 .blk td{{background:#f3f0fa;font-weight:bold;font-size:13px;
          text-transform:uppercase;letter-spacing:.4px;color:#4a3d6b;
          padding-top:16px}}
 .box{{background:#fff8e1;border:1px solid #f0d271;border-radius:6px;
       padding:12px 14px;margin:22px 0;font-size:14px}}
</style>
<h1>Captainship reports — {reported.month}/{reported.day}</h1>
<p class="sub">Open each one and check the numbers. Nothing has been sent
yet. They go out <b>one block at a time</b> — each block gets its own link in
Slack and its own ✅.</p>
<table>
<tr><th>Captain</th><th>Will go to</th><th>Status</th></tr>
{"".join(rows)}
</table>
<div class="box">
<b>Look right?</b> Back on the Hub, press
<b>&laquo;2. Post to Slack for approval&raquo;</b>. Each block gets its own
link inside the day's <i>Captainship Reports</i> thread in #revision-emails,
and a ✅ on a block sends <i>that</i> block &mdash; you don't have to wait for
the rest, and nobody gets anything until then.<br><br>
<b>A number is wrong?</b> Fix it on the Sales Board, rebuild (the whole set, or
just that block), and re-check here. If a block's link is already in Slack,
re-run <code>review_gate.py --refresh --block &lt;block&gt;</code> so the link
people already have shows the corrected PDF.
</div>
"""
    out = _OUTPUT_DIR / INDEX_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    logfn(f"  ✓ review index: {out}")
    return out


if __name__ == "__main__":
    d = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None
    build_index(d)
