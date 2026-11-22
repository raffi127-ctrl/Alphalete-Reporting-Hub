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
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))  # the bot's .runtime: poster.py lives there


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


def with_interviewer(md_text, name):
    """The report with `name` in the Interviewer cell (and the old-style title).
    The value row is the first table row after the header that names
    'Interviewer' - the same row poster._parse_metadata reads."""
    lines = md_text.split("\n")
    header = None
    for i, ln in enumerate(lines):
        if not ln.startswith("|"):
            continue
        cells = ln.strip().strip("|").split("|")
        if header is None:
            if cells and cells[0].strip().lower() == "interviewer":
                header = i
            continue
        if re.fullmatch(r"[\s|:-]+", ln):
            continue
        cells[0] = " %s " % name
        lines[i] = "|" + "|".join(cells) + "|"
        break
    out = "\n".join(lines)
    return re.sub(r"^(#\s+Audit\s+[—–-]\s+).+?(\s+[×x]\s+)", lambda m: m.group(1) + name + m.group(2),
                  out, count=1, flags=re.MULTILINE)


def _sender_pdf(item, out):
    """The scorecard re-drawn with the sender as interviewer, or None (then the
    bot's own PDF goes in as before)."""
    name, md = (item.get("name") or "").strip(), item.get("md") or ""
    if not name or not md or not Path(md).is_file():
        return None
    try:
        import poster
        text = with_interviewer(Path(md).read_text(encoding="utf-8"), name)
        tmp = out.with_name("_sender_%s_%s.pdf" % (out.stem, Path(md).stem))
        poster.write_pdf_from_html(poster.markdown_to_poster_html(text, md_path=Path(md)), tmp)
        return tmp
    except Exception as e:  # noqa: BLE001
        print("sender redraw failed for %s: %s" % (md, e), file=sys.stderr)
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
        n, temps = 0, []
        items = j.get("senders") or [{"pdf": p} for p in j["pdfs"]]
        for it in items:
            p = it["pdf"]
            redrawn = _sender_pdf(it, out)
            if redrawn:
                temps.append(redrawn)
            try:
                writer.append(str(redrawn or p))
                n += 1
            except Exception as e:  # noqa: BLE001
                print("could not append %s: %s" % (p, e), file=sys.stderr)
        if n:
            with open(out, "wb") as fh:
                writer.write(fh)
            made.append(str(out))
        else:
            failed[str(out)] = "no readable scorecard PDF"
        for t in ([cover] if cover else []) + temps:
            try:
                t.unlink()
            except OSError:
                pass
    print(json.dumps({"made": made, "failed": failed}))


if __name__ == "__main__":
    main()
