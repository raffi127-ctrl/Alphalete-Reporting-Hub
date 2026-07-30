"""Build output/REVISAR-correos-boards.html — one page listing the day's board
emails, so opening them is one click and not a hunt through dated folders.

Same idea (and the same look) as the captainship drafts' own index. Written
automatically at the end of every --dry-run build; also runnable on its own:

    .venv\\Scripts\\python.exe -m automations.board_emails.review_index
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

from automations.board_emails import boards as B
from automations.board_emails import email_send as es

_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"
INDEX_NAME = "REVISAR-correos-boards.html"


def build_index(run_day: dt.date | None = None, *, logfn=print) -> Path:
    run_day = run_day or es.today_central()
    reported = es.reported_day(run_day)
    rows = []
    for board in B.BOARDS:
        preview = es.out_dir_for(board, run_day) / "preview.html"
        who = ", ".join(board.to)
        if preview.exists():
            # Relative to output/ so the links work from the index's own folder
            # wherever the repo lives.
            href = preview.relative_to(_OUTPUT_DIR).as_posix()
            rows.append(
                f'<tr><td><a href="{href}" target="_blank">{board.name}</a></td>'
                f'<td>{who}</td><td class="ok">listo</td></tr>')
        else:
            rows.append(
                f'<tr><td>{board.name}</td><td>{who}</td>'
                f'<td class="no">NO se generó</td></tr>')

    html = f"""<!doctype html><meta charset="utf-8">
<title>Correos de boards — {reported.month}/{reported.day}</title>
<style>
 body{{font-family:Arial,Helvetica,sans-serif;margin:32px;color:#111}}
 h1{{font-size:20px;margin:0 0 4px}}
 p.sub{{color:#666;margin:0 0 20px;font-size:13px}}
 table{{border-collapse:collapse;min-width:620px}}
 td,th{{border:1px solid #ddd;padding:8px 12px;font-size:14px;text-align:left}}
 th{{background:#f4f4f4}}
 a{{color:#0b57d0;text-decoration:none}} a:hover{{text-decoration:underline}}
 .ok{{color:#137333;font-weight:bold}} .no{{color:#b3261e;font-weight:bold}}
 .note{{margin-top:18px;font-size:12px;color:#666;max-width:620px;line-height:1.5}}
</style>
<h1>Correos de boards — {reported.month}/{reported.day}</h1>
<p class="sub">Datos del {reported.month}/{reported.day}, generados el
 {run_day.isoformat()}.</p>
<table>
 <tr><th>Correo</th><th>Va a</th><th>Estado</th></tr>
 {''.join(rows)}
</table>
<p class="note">Estos son PREVIEWS: no se ha enviado nada. El envío lo libera
un ✅ de Evelyn o Jolie sobre el post del día en #revision-emails, y sale la
imagen ya capturada — lo que se aprobó es lo que se manda.</p>
"""

    out = _OUTPUT_DIR / INDEX_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    logfn(f"  ✓ índice de revisión: {out}")
    return out


if __name__ == "__main__":
    sys.exit(0 if build_index() else 1)
