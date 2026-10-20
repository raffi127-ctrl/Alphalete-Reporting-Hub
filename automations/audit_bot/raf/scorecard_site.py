#!/usr/bin/env python3
"""Generate a self-contained HTML scorecard dashboard from the audit bot's data.

Page 1: Office Rankings + Rep Rankings (ranked by avg), each with a This-Week
column. Page 2: overall weekly submissions trend (last 8 weeks). Reuses
scorecards.build_aggregates() + the raw completions log (timestamps) + rosters.
Writes site/index.html — one page, no external assets, mobile-friendly, and
renders cleanly to a 2-page PDF (WeasyPrint). Run on Lucy 1:
    venv/bin/python scorecard_site.py
"""
from __future__ import annotations
import sys
import html
import datetime
from collections import Counter
from pathlib import Path

RUNTIME = Path(__file__).parent.resolve()
sys.path.insert(0, str(RUNTIME))

import scorecards                       # noqa: E402
from rosters import load_reps, owner_name  # noqa: E402

OUT = RUNTIME / "site" / "index.html"


def _score_class(avg: float) -> str:
    if avg >= 8:  return "good"
    if avg >= 6:  return "ok"
    if avg > 0:   return "low"
    return "none"


def _rep_name(uid: str, reps_data: dict) -> str:
    info = reps_data.get(uid, {}) or {}
    nm = (f"{info.get('first_name','')} {info.get('last_name','')}").strip()
    if len(nm.split()) >= 2:               # already a full first + last
        return nm
    # incomplete/nickname → prefer the Slack profile's real (full) name
    try:
        from slack_watcher import web
        real = (web.users_info(user=uid)["user"].get("profile", {}).get("real_name") or "").strip()
        if len(real.split()) >= 2:
            return real
    except Exception:
        pass
    return nm or "(inactive)"


def _stamp() -> str:
    now = datetime.datetime.now()
    hour = now.strftime("%I").lstrip("0") or "12"
    return f"{now.strftime('%b')} {now.day}, {now.year} · {hour}{now.strftime(':%M %p')}"


def _avgtxt(a: float) -> str:
    return f"{a:.1f}" if a > 0 else "—"


def _monday(d: datetime.date) -> datetime.date:
    return d - datetime.timedelta(days=d.weekday())


def _weekly(reps_data: dict):
    """Compute per-rep / per-office 'this week' + 'last week' counts and the
    overall last-8-weeks trend, from the raw (enriched) completion records."""
    recs = scorecards._enrich_with_slack_uploaders(scorecards._load_all_completions())
    today = datetime.date.today()
    this_wk, last_wk = _monday(today), _monday(today) - datetime.timedelta(weeks=1)
    rep_tw, rep_lw, off_tw, off_lw = Counter(), Counter(), Counter(), Counter()
    overall = Counter()
    for r in recs:
        ts = r.get("ts", "")
        try:
            wk = _monday(datetime.date.fromisoformat(ts[:10]))
        except Exception:
            continue
        overall[wk] += 1
        up = r.get("_uploader_user_id")
        if not up or (reps_data.get(up) or {}).get("terminated"):
            continue
        oid = (reps_data.get(up) or {}).get("owner_id")
        if wk == this_wk:
            rep_tw[up] += 1
            if oid: off_tw[oid] += 1
        elif wk == last_wk:
            rep_lw[up] += 1
            if oid: off_lw[oid] += 1
    return {"rep_tw": rep_tw, "off_tw": off_tw, "overall": overall,
            "latest": max(overall) if overall else this_wk}


def build_html() -> str:
    reps_data = load_reps()
    agg = scorecards.build_aggregates()
    per_owner = agg["per_owner"]
    per_rep = agg["per_rep"]
    wk = _weekly(reps_data)

    total_subs = sum(b["submissions"] for b in per_owner.values())
    total_reps = len(per_rep)
    total_owners = len(per_owner)

    # ---- office rows ----
    # map owner_id per owner name back for the this-week lookup
    off_tw = wk["off_tw"]
    offices = []
    for oid, b in per_owner.items():
        offices.append((oid, owner_name(oid), b["avg_score"], _score_class(b["avg_score"]),
                        b["submissions"], b["rep_count"]))
    offices.sort(key=lambda o: (-o[2], -o[4]))
    otable = "".join(
        f'<tr><td class="rk">{i}</td><td class="nm">{html.escape(o[1])}</td>'
        f'<td class="c"><span class="pill {o[3]}">{_avgtxt(o[2])}</span></td>'
        f'<td class="n tw">{off_tw.get(o[0],0)}</td><td class="n">{o[4]}</td><td class="n">{o[5]}</td></tr>'
        for i, o in enumerate(offices, 1)
    ) or '<tr><td colspan="6" class="empty">No submissions yet.</td></tr>'

    # ---- rep rows ----
    rep_tw = wk["rep_tw"]
    rrows = []
    for uid, b in per_rep.items():
        oid = (reps_data.get(uid) or {}).get("owner_id")
        rrows.append((uid, _rep_name(uid, reps_data), owner_name(oid) if oid else "—",
                      b["submissions"], b["avg_score"], _score_class(b["avg_score"])))
    rrows.sort(key=lambda r: (-r[4], -r[3]))
    rtable = "".join(
        f'<tr><td class="rk">{i}</td><td class="nm">{html.escape(r[1])}</td>'
        f'<td class="off">{html.escape(r[2])}</td>'
        f'<td class="c"><span class="pill {r[5]}">{_avgtxt(r[4])}</span></td>'
        f'<td class="n tw">{rep_tw.get(r[0],0)}</td><td class="n">{r[3]}</td></tr>'
        for i, r in enumerate(rrows, 1)
    ) or '<tr><td colspan="6" class="empty">No submissions yet.</td></tr>'

    # ---- overall weekly trend (last 8 weeks) ----
    latest = wk["latest"]
    weeks = [latest - datetime.timedelta(weeks=n) for n in range(0, 8)]  # current week on top → oldest on bottom
    counts = [wk["overall"].get(w, 0) for w in weeks]
    mx = max(counts) if counts else 1
    tw_c, lw_c = counts[0], counts[1]
    delta = tw_c - lw_c
    bars = "".join(
        f'<div class="twk"><span class="wl">{w.strftime("%b")} {w.day}</span>'
        f'<div class="bar"><span style="width:{int(round(c/(mx or 1)*100))}%"></span></div>'
        f'<span class="wc">{c}</span></div>'
        for w, c in zip(weeks, counts)
    )
    arrow = (f'<span class="up">▲ +{delta}</span>' if delta > 0
             else f'<span class="dn">▼ {delta}</span>' if delta < 0
             else '<span class="fl">no change</span>')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>2nd Round Interview Scorecards</title>
<style>
  :root {{ --bg:#0f1115; --card:#171a21; --line:#262b36; --text:#e7eaf0; --muted:#9aa3b2;
    --good:#2fbf71; --ok:#e0b93a; --low:#e5533c; --none:#4b5261; --accent:#6ea8fe; }}
  *{{box-sizing:border-box;}}
  body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}}
  .wrap{{max-width:760px;margin:0 auto;padding:20px 16px 60px;}}
  header.top{{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 14px;}}
  header.top h1{{font-size:1.35rem;margin:0;}}
  .updated{{color:var(--muted);font-size:.82rem;}}
  .totals{{color:var(--muted);font-size:.9rem;margin:2px 0 26px;}} .totals b{{color:var(--text);}}
  h2.sec{{font-size:1rem;margin:26px 0 8px;letter-spacing:.2px;}}
  table.board{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;}}
  .board th,.board td{{padding:9px 12px;text-align:left;}}
  .board thead th{{color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.5px;font-weight:600;background:#12151b;}}
  .board tbody tr{{border-top:1px solid var(--line);}}
  .board tbody tr:nth-child(odd){{background:rgba(255,255,255,.015);}}
  td.rk,th.rk{{width:38px;color:var(--muted);text-align:center;font-variant-numeric:tabular-nums;}}
  td.nm{{font-weight:600;}}
  td.off{{color:var(--muted);}}
  td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums;width:64px;}}
  td.tw,th.tw{{color:var(--accent);}}
  td.c,th.c{{text-align:center;width:60px;}}
  td.empty{{color:var(--muted);text-align:center;padding:16px;}}
  .board tbody tr:nth-child(1) td.rk,.board tbody tr:nth-child(2) td.rk,.board tbody tr:nth-child(3) td.rk{{color:var(--text);font-weight:800;}}
  .pill{{display:inline-block;min-width:34px;text-align:center;padding:2px 8px;border-radius:999px;font-weight:700;font-size:.82rem;color:#0d0f13;}}
  .pill.good{{background:var(--good);}} .pill.ok{{background:var(--ok);}}
  .pill.low{{background:var(--low);color:#fff;}} .pill.none{{background:var(--none);color:var(--muted);}}
  .page2{{break-before:page;}}
  .trend{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;}}
  .twk{{display:flex;align-items:center;gap:10px;padding:5px 0;}}
  .wl{{width:56px;color:var(--muted);font-size:.82rem;font-variant-numeric:tabular-nums;}}
  .bar{{flex:1;height:14px;background:#0e1116;border-radius:6px;overflow:hidden;}}
  .bar span{{display:block;height:100%;background:linear-gradient(90deg,#6ea8fe,#2fbf71);border-radius:6px;}}
  .wc{{width:34px;text-align:right;font-weight:700;font-variant-numeric:tabular-nums;}}
  .delta{{color:var(--muted);font-size:.9rem;margin-top:12px;}} .delta b{{color:var(--text);}}
  .delta .up{{color:var(--good);font-weight:700;}} .delta .dn{{color:var(--low);font-weight:700;}} .delta .fl{{color:var(--muted);}}
  footer{{color:var(--muted);font-size:.78rem;text-align:center;margin-top:28px;}}
</style></head>
<body><div class="wrap">
  <header class="top"><h1>🐺 2nd Round Interview Scorecards</h1><span class="updated">updated {_stamp()}</span></header>
  <p class="totals"><b>{total_subs}</b> audits · <b>{total_owners}</b> owners · <b>{total_reps}</b> reps · scores out of 10</p>
  <h2 class="sec">🏆 Office Rankings</h2>
  <table class="board"><thead><tr><th class="rk">#</th><th>Office</th><th class="c">Avg</th><th class="n tw">This wk</th><th class="n">Total</th><th class="n">Reps</th></tr></thead><tbody>{otable}</tbody></table>
  <h2 class="sec">📊 Rep Rankings</h2>
  <table class="board"><thead><tr><th class="rk">#</th><th>Rep</th><th>Office</th><th class="c">Avg</th><th class="n tw">This wk</th><th class="n">Total</th></tr></thead><tbody>{rtable}</tbody></table>
  <h2 class="sec page2">📈 Weekly Submissions <span style="color:var(--muted);font-weight:400;font-size:.8rem">(last 8 weeks, all offices)</span></h2>
  <div class="trend">{bars}</div>
  <p class="delta">This week <b>{tw_c}</b> &nbsp;·&nbsp; last week <b>{lw_c}</b> &nbsp;{arrow}</p>
  <footer>Auto-generated from the Interview Audit Bot · refreshes as new audits complete</footer>
</div></body></html>"""


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build_html(), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
