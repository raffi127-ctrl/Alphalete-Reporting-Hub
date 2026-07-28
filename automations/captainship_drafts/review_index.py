"""Build output/REVISAR-informes-capitanes.html — one page listing today's 12
reports so Eve opens ONE file instead of hunting for twelve among older dates.

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
INDEX_NAME = "REVISAR-informes-capitanes.html"


def build_index(today: dt.date | None = None, *, logfn=print) -> Path:
    today = today or dt.date.today()
    reported = today - dt.timedelta(days=1)
    rows = []
    for captain in config.CAPTAINS:
        f = _OUTPUT_DIR / (
            f"captainship_draft_{captain.key}_{today:%Y%m%d}.html")
        n_to = len([a for a in captain.to.split(",") if a.strip()])
        if f.exists():
            rows.append(
                f'<tr><td><a href="{f.name}" target="_blank">'
                f'{captain.display_name}</a></td>'
                f'<td>{n_to} personas</td>'
                f'<td class="ok">listo</td></tr>')
        else:
            rows.append(
                f'<tr><td>{captain.display_name}</td>'
                f'<td>{n_to} personas</td>'
                f'<td class="no">NO se generó</td></tr>')

    html = f"""<!doctype html>
<meta charset="utf-8">
<title>Revisar informes de capitanes</title>
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
 .box{{background:#fff8e1;border:1px solid #f0d271;border-radius:6px;
       padding:12px 14px;margin:22px 0;font-size:14px}}
</style>
<h1>Informes de capitanes — {reported.day}/{reported.month}</h1>
<p class="sub">Abre cada uno y revisa los números. Nada se ha enviado
todavía.</p>
<table>
<tr><th>Capitán</th><th>Se enviará a</th><th>Estado</th></tr>
{"".join(rows)}
</table>
<div class="box">
<b>¿Están bien?</b> Vuelve al Hub y pulsa
<b>&laquo;2. Send the reviewed reports&raquo;</b>. Se enviarán exactamente
estos archivos.<br><br>
<b>¿Hay un número mal?</b> Corrígelo en el Sales Board, pulsa
<b>&laquo;1. Build + review the 12&raquo;</b> otra vez y vuelve a mirar.
Nadie recibe nada hasta que pulses enviar.
</div>
"""
    out = _OUTPUT_DIR / INDEX_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    logfn(f"  ✓ índice de revisión: {out}")
    return out


if __name__ == "__main__":
    d = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None
    build_index(d)
