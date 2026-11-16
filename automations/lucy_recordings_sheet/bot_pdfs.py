"""Runs INSIDE the 2nd-round audit bot's venv (it has pypdf + weasyprint; the
Hub's venv doesn't). Merges audit PDFs into one PDF per owner per day, with a
cover page listing who sent what.

    <bot venv python> bot_pdfs.py jobs.json

jobs.json = [{"out": path, "owner": "...", "day": "YYYY-MM-DD",
              "rows": [[rep, time, score], ...], "pdfs": [path, ...]}, ...]
Prints one JSON line: {"made": [out, ...], "failed": {out: reason}}.

Keep this file stdlib + pypdf/weasyprint only - it is NOT run with the Hub's venv.
"""
import datetime as dt
import html
import json
import sys
from pathlib import Path


def _cover(owner, day, rows, out):
    d = dt.date.fromisoformat(day)
    label = "%s, %s %d, %d" % (d.strftime("%A"), d.strftime("%B"), d.day, d.year)
    body = "".join(
        '<div class="row"><span>%s <i>%s</i></span><span class="sc">%s</span></div>'
        % (html.escape(rep), html.escape(t), html.escape(str(sc)))
        for rep, t, sc in rows)
    page = """<html><head><meta charset="utf-8"><style>
      @page { size: Letter; margin: 0; }
      body { font-family: Arial, sans-serif; margin: 0; color: #1a1a1a; }
      .top { background: #1F2A44; color: #fff; padding: 56px 60px 40px; }
      .brand { font-size: 13px; letter-spacing: 3px; text-transform: uppercase; color: #C9D3EA; }
      .owner { font-size: 40px; font-weight: bold; margin: 18px 0 6px; }
      .date { font-size: 18px; color: #F3E3A6; }
      .body { padding: 36px 60px; }
      .h { font-size: 12px; letter-spacing: 2px; text-transform: uppercase; color: #5B6478;
           border-bottom: 2px solid #1F2A44; padding-bottom: 8px; margin-bottom: 6px; }
      .row { display: flex; justify-content: space-between; padding: 11px 2px;
             border-bottom: 1px solid #eee; font-size: 17px; }
      .row i { color: #777; font-style: normal; font-size: 14px; margin-left: 8px; }
      .sc { font-weight: bold; }
      .count { font-size: 14px; color: #666; margin-top: 14px; }
    </style></head><body>
      <div class="top"><div class="brand">LUCY &middot; 2nd Round Scorecards</div>
        <div class="owner">%s</div><div class="date">%s</div></div>
      <div class="body"><div class="h">Scorecards in this file</div>%s
        <div class="count">%d scorecard%s &middot; full scorecards on the next pages</div></div>
    </body></html>""" % (html.escape(owner), label, body, len(rows), "" if len(rows) == 1 else "s")
    try:
        from weasyprint import HTML
        cover = out.with_name("_cover_" + out.name)
        HTML(string=page).write_pdf(str(cover))
        return cover
    except Exception as e:  # noqa: BLE001 - no cover is fine, the scorecards still go
        print("cover failed for %s: %s" % (out.name, e), file=sys.stderr)
        return None


def main():
    from pypdf import PdfWriter
    jobs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    made, failed = [], {}
    for j in jobs:
        out = Path(j["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        writer = PdfWriter()
        cover = _cover(j["owner"], j["day"], j["rows"], out)
        if cover:
            writer.append(str(cover))
        n = 0
        for p in j["pdfs"]:
            try:
                writer.append(p)
                n += 1
            except Exception as e:  # noqa: BLE001
                print("could not append %s: %s" % (p, e), file=sys.stderr)
        if n:
            with open(out, "wb") as fh:
                writer.write(fh)
            made.append(str(out))
        else:
            failed[str(out)] = "no readable scorecard PDF"
        if cover:
            try:
                cover.unlink()
            except OSError:
                pass
    print(json.dumps({"made": made, "failed": failed}))


if __name__ == "__main__":
    main()
