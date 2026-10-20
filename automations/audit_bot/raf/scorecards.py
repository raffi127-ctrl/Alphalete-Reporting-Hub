"""
Two scorecards / leaderboards built from completions.jsonl + rosters.

A. Owner leaderboard — # submissions per owner
B. Rep leaderboard   — ranked by weighted score (submissions × avg score)
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from rosters import load_reps, load_owners, owner_name

RUNTIME_DIR = Path(__file__).parent.resolve()
COMPLETIONS_LOG = RUNTIME_DIR / "completions.jsonl"
REPORTS_DIR = RUNTIME_DIR.parent / "reports"


def _extract_overall_score(md_path: Path) -> float | None:
    """Pull the Overall X/10 score from a markdown audit report."""
    try:
        text = md_path.read_text(encoding="utf-8")
    except Exception:
        return None
    # The scores row has format: | X/5 | X/5 | X/7 | X/10 |
    # Overall is the 4th score cell. Look for the row with 4 score patterns.
    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        cells = [c for c in cells if c]
        if len(cells) == 4 and all(re.match(r"\d+(?:\.\d+)?/\d+", c) for c in cells):
            # Overall is the last cell
            m = re.match(r"(\d+(?:\.\d+)?)\s*/\s*(\d+)", cells[-1])
            if m:
                num = float(m.group(1))
                denom = float(m.group(2))
                if denom > 0:
                    return num  # raw X/10
    return None


def _slack_prefix_from_filename(audio_filename: str) -> str | None:
    """slack-{ts}_filename.m4a → user_id requires the slack_pending mapping.
    But the user_id was already cleared. Instead, we'll cross-reference Slack's
    files.list at scorecard-time to find the uploader."""
    m = re.match(r"^(slack-\d+_\d+)", audio_filename)
    return m.group(1) if m else None


def _load_all_completions() -> list[dict]:
    if not COMPLETIONS_LOG.exists():
        return []
    out = []
    with open(COMPLETIONS_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _enrich_with_slack_uploaders(records: list[dict]) -> list[dict]:
    """For Slack-originated records, look up the uploader_user_id via Slack
    files.list (one-time fetch + cache)."""
    try:
        from slack_watcher import web, _BOT_USER_ID
    except Exception:
        return records

    # Build a name → user_id index from Slack's files list
    file_user_index = {}  # filename → user_id
    try:
        page = 1
        while page <= 10:
            result = web.files_list(count=200, page=page, types="all")
            files = result.get("files", []) or []
            if not files:
                break
            for f in files:
                uid = f.get("user")
                if uid and uid != _BOT_USER_ID:
                    file_user_index[f.get("name", "")] = uid
            paging = result.get("paging", {})
            if page >= paging.get("pages", 1):
                break
            page += 1
    except Exception:
        return records

    for rec in records:
        audio = rec.get("audio_filename", "")
        if not audio.startswith("slack-"):
            continue
        # Strip the slack prefix to recover the original filename
        m = re.match(r"^slack-\d+_\d+_(.+)$", audio)
        if not m:
            continue
        orig_name = m.group(1).replace("_", " ").strip()
        # Try a few normalization variants
        candidates = {
            orig_name,
            orig_name.replace(" ", "_"),
            audio.split("_", 2)[-1] if "_" in audio else "",
        }
        for cand in candidates:
            if cand in file_user_index:
                rec["_uploader_user_id"] = file_user_index[cand]
                break
        # Fallback: any partial match
        if "_uploader_user_id" not in rec:
            for fn, uid in file_user_index.items():
                if fn and orig_name and (fn in orig_name or orig_name in fn):
                    rec["_uploader_user_id"] = uid
                    break

    return records


def build_aggregates() -> dict:
    """Combine completions + rosters to compute scores per rep + per owner."""
    records = _load_all_completions()
    records = _enrich_with_slack_uploaders(records)
    reps = load_reps()

    per_rep = defaultdict(lambda: {"submissions": 0, "scores": [], "files": []})
    per_owner = defaultdict(lambda: {"submissions": 0, "rep_count": set(), "scores": []})

    for rec in records:
        audio = rec.get("audio_filename", "")
        if not audio.startswith("slack-"):
            continue  # only count Slack-originated
        uploader = rec.get("_uploader_user_id")
        if not uploader:
            continue
        # Terminated (retired) reps drop off the scorecard + leaderboards.
        rep_meta = reps.get(uploader) or {}
        if rep_meta.get("terminated"):
            continue
        # Reset window: if a retired rep came back, only count submissions from
        # their reinstatement point forward (they start over at 1).
        cf = rep_meta.get("count_from")
        if cf and (rec.get("ts", "") or "") < cf:
            continue
        # Skip Rafael himself unless he wants to be counted
        # (we'll include him — he's also an "owner" + rep of his own)
        score = None
        md = rec.get("report_md")
        if md:
            mdp = Path(md)
            if not mdp.exists():
                # Historical records point at the old machine's path — resolve
                # the report by filename in the local reports/ dir (backfilled).
                alt = REPORTS_DIR / mdp.name
                if alt.exists():
                    mdp = alt
            score = _extract_overall_score(mdp)

        bucket = per_rep[uploader]
        bucket["submissions"] += 1
        if score is not None:
            bucket["scores"].append(score)
        bucket["files"].append(audio)

        owner_id = (reps.get(uploader) or {}).get("owner_id")
        if owner_id:
            ob = per_owner[owner_id]
            ob["submissions"] += 1
            ob["rep_count"].add(uploader)
            if score is not None:
                ob["scores"].append(score)

    # Convert sets to counts + add derived metrics
    for owner_id, b in per_owner.items():
        b["rep_count"] = len(b["rep_count"])
        b["avg_score"] = sum(b["scores"]) / len(b["scores"]) if b["scores"] else 0.0
    for uid, b in per_rep.items():
        b["avg_score"] = sum(b["scores"]) / len(b["scores"]) if b["scores"] else 0.0
        # Weighted: submissions × (avg_score / 10) — rewards quantity AND quality
        b["weighted"] = b["submissions"] * (b["avg_score"] / 10.0)

    return {"per_rep": dict(per_rep), "per_owner": dict(per_owner)}


# ---------- Formatters ----------

def owner_leaderboard_md() -> str:
    """Render the owner leaderboard as Slack-flavored markdown."""
    agg = build_aggregates()
    rows = []
    for owner_id, b in agg["per_owner"].items():
        name = owner_name(owner_id)
        rows.append((name, b["submissions"], b["rep_count"], b["avg_score"]))
    rows.sort(key=lambda r: (-r[1], -r[3]))  # sort by submissions desc, then avg score desc

    if not rows:
        return ":trophy: *Owner Leaderboard* — no submissions yet."

    out = [":trophy: *Owner Leaderboard* (by # of submissions)\n"]
    for i, (name, subs, reps, avg) in enumerate(rows, 1):
        medal = {1: ":first_place_medal:", 2: ":second_place_medal:", 3: ":third_place_medal:"}.get(i, f"  {i}.")
        out.append(f"{medal} *{name}* — {subs} submission(s) · {reps} rep(s) · avg score *{avg:.1f}/10*")
    return "\n".join(out)


def rep_leaderboard_md(top: int = 20) -> str:
    """Render the rep leaderboard (weighted: submissions × avg_score / 10)."""
    agg = build_aggregates()

    try:
        from slack_watcher import _user_display
    except Exception:
        def _user_display(uid): return f"<@{uid}>"

    reps_data = load_reps()
    rows = []
    for uid, b in agg["per_rep"].items():
        # Prefer the rep's stored first/last name; fall back to Slack display name
        info = reps_data.get(uid, {})
        first = info.get("first_name") or ""
        last = info.get("last_name") or ""
        name = (f"{first} {last}").strip() or _user_display(uid)
        owner_id = info.get("owner_id")
        owner_disp = owner_name(owner_id) if owner_id else "—"
        rows.append((name, owner_disp, b["submissions"], b["avg_score"], b["weighted"]))
    rows.sort(key=lambda r: (-r[4], -r[3]))  # weighted desc, then avg desc
    rows = rows[:top]

    if not rows:
        return ":bar_chart: *Rep Leaderboard* — no submissions yet."

    out = [":bar_chart: *Rep Leaderboard* (weighted: submissions × avg score)\n"]
    for i, (name, owner_disp, subs, avg, weighted) in enumerate(rows, 1):
        medal = {1: ":first_place_medal:", 2: ":second_place_medal:", 3: ":third_place_medal:"}.get(i, f"  {i}.")
        out.append(f"{medal} *{name}* (owner: {owner_disp}) — {subs} subs · avg *{avg:.1f}/10* · weighted *{weighted:.2f}*")
    return "\n".join(out)


def combined_leaderboard_md() -> str:
    return owner_leaderboard_md() + "\n\n" + rep_leaderboard_md()


# ---------- PDF generation ----------

_PDF_CSS = """
:root {
    --bg: #ffffff;
    --text: #111827;
    --muted: #6b7280;
    --border: #d1d5db;
    --soft-border: #e5e7eb;
    --gold: #f59e0b;
    --silver: #94a3b8;
    --bronze: #b45309;
    --good: #15803d;
    --mid: #b45309;
    --bad: #b91c1c;
}
* { box-sizing: border-box; }
body {
    margin: 0;
    background: #fff;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, system-ui, sans-serif;
    color: var(--text);
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
}
.poster { padding: 0; }
.brand-bar {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    color: #f8fafc;
    padding: 18px 44px;
    text-align: center;
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 4px;
    text-transform: uppercase;
}
.brand-bar .accent { color: #60a5fa; }
.body { padding: 36px 44px 44px; }
h1.title {
    font-size: 26px;
    font-weight: 700;
    margin: 0 0 4px;
    border-bottom: 2px solid var(--text);
    padding-bottom: 12px;
    margin-bottom: 18px;
}
h1.title .subtitle {
    display: block;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--muted);
    margin-bottom: 6px;
}
.date-line {
    font-size: 12px;
    color: var(--muted);
    margin-bottom: 24px;
}
section { margin: 22px 0; }
section h2 {
    font-size: 16px;
    font-weight: 700;
    color: var(--text);
    margin: 0 0 14px;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--soft-border);
}
table.leaderboard {
    width: 100%;
    border-collapse: collapse;
    font-size: 13.5px;
    border: 1px solid var(--border);
}
table.leaderboard th {
    background: #f3f4f6;
    padding: 10px 12px;
    text-align: left;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--muted);
    font-weight: 700;
    border-bottom: 1px solid var(--border);
}
table.leaderboard td {
    padding: 11px 12px;
    border-bottom: 1px solid var(--soft-border);
    vertical-align: middle;
}
table.leaderboard tr:last-child td { border-bottom: none; }
.rank { width: 50px; text-align: center; font-weight: 800; font-size: 16px; }
.rank.r1 { color: var(--gold); }
.rank.r2 { color: var(--silver); }
.rank.r3 { color: var(--bronze); }
.rank-medal { font-size: 18px; }
.name-cell { font-weight: 700; }
.owner-cell { color: var(--muted); font-size: 12px; }
.num-cell { text-align: right; font-variant-numeric: tabular-nums; }
.score-good { color: var(--good); font-weight: 700; }
.score-mid  { color: var(--mid); font-weight: 700; }
.score-bad  { color: var(--bad); font-weight: 700; }
.weighted-cell { font-weight: 800; }
@media print {
    body { background: #fff; padding: 0; }
}
"""


def _score_class(val: float, denom: float = 10.0) -> str:
    if denom <= 0:
        return ""
    pct = val / denom
    if pct >= 0.7: return "score-good"
    if pct >= 0.4: return "score-mid"
    return "score-bad"


def _rank_cell(i: int) -> str:
    if i == 1: return '<td class="rank r1">🥇</td>'
    if i == 2: return '<td class="rank r2">🥈</td>'
    if i == 3: return '<td class="rank r3">🥉</td>'
    return f'<td class="rank">{i}</td>'


def _build_leaderboard_html() -> str:
    agg = build_aggregates()
    try:
        from slack_watcher import _user_display
    except Exception:
        def _user_display(uid): return f"<@{uid}>"

    # Owner rows
    owner_rows = []
    for owner_id, b in agg["per_owner"].items():
        name = owner_name(owner_id)
        owner_rows.append((name, b["submissions"], b["rep_count"], b["avg_score"]))
    owner_rows.sort(key=lambda r: (-r[1], -r[3]))

    owner_table = '<table class="leaderboard">'
    owner_table += '<thead><tr><th></th><th>Owner</th><th class="num-cell">Submissions</th><th class="num-cell">Reps</th><th class="num-cell">Avg Score</th></tr></thead><tbody>'
    for i, (name, subs, reps, avg) in enumerate(owner_rows, 1):
        score_cls = _score_class(avg)
        owner_table += (
            f'<tr>{_rank_cell(i)}'
            f'<td class="name-cell">{name}</td>'
            f'<td class="num-cell">{subs}</td>'
            f'<td class="num-cell">{reps}</td>'
            f'<td class="num-cell {score_cls}">{avg:.1f}/10</td></tr>'
        )
    owner_table += '</tbody></table>'

    # Rep rows
    reps_data = load_reps()
    rep_rows = []
    for uid, b in agg["per_rep"].items():
        info = reps_data.get(uid, {})
        first = info.get("first_name") or ""
        last = info.get("last_name") or ""
        name = (f"{first} {last}").strip() or _user_display(uid)
        owner_id = info.get("owner_id")
        owner_disp = owner_name(owner_id) if owner_id else "—"
        rep_rows.append((name, owner_disp, b["submissions"], b["avg_score"], b["weighted"]))
    rep_rows.sort(key=lambda r: (-r[4], -r[3]))
    rep_rows = rep_rows[:30]

    rep_table = '<table class="leaderboard">'
    rep_table += '<thead><tr><th></th><th>Rep</th><th>Owner</th><th class="num-cell">Subs</th><th class="num-cell">Avg</th><th class="num-cell">Weighted</th></tr></thead><tbody>'
    for i, (name, owner_disp, subs, avg, weighted) in enumerate(rep_rows, 1):
        score_cls = _score_class(avg)
        rep_table += (
            f'<tr>{_rank_cell(i)}'
            f'<td class="name-cell">{name}</td>'
            f'<td class="owner-cell">{owner_disp}</td>'
            f'<td class="num-cell">{subs}</td>'
            f'<td class="num-cell {score_cls}">{avg:.1f}</td>'
            f'<td class="num-cell weighted-cell">{weighted:.2f}</td></tr>'
        )
    rep_table += '</tbody></table>'

    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Leaderboards</title>
<style>{_PDF_CSS}</style>
</head>
<body>
<div class="poster">
    <div class="brand-bar">Alphalete <span class="accent">Audits</span></div>
    <div class="body">
        <h1 class="title">
            <span class="subtitle">Leaderboards</span>
            Owner &amp; Rep Standings
        </h1>
        <div class="date-line">Generated: {now}</div>
        <section>
            <h2>🏆 Owner Leaderboard <span style="font-weight:400;font-size:12px;color:#6b7280;">(by # of submissions)</span></h2>
            {owner_table}
        </section>
        <section>
            <h2>📊 Rep Leaderboard <span style="font-weight:400;font-size:12px;color:#6b7280;">(weighted = submissions × avg/10)</span></h2>
            {rep_table}
        </section>
    </div>
</div>
</body>
</html>
"""
    return html


def write_leaderboard_pdf(out_path: Path | None = None) -> Path:
    """Render the leaderboard to a PDF. Returns the path."""
    # WeasyPrint needs Homebrew libs on macOS — must be set BEFORE import
    import os
    brew_lib = "/opt/homebrew/lib"
    if os.path.isdir(brew_lib):
        existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        if brew_lib not in existing.split(":"):
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
                f"{brew_lib}:{existing}" if existing else brew_lib
            )
    from weasyprint import HTML as WeasyHTML
    if out_path is None:
        out_path = Path("/tmp") / f"leaderboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    html = _build_leaderboard_html()
    WeasyHTML(string=html).write_pdf(str(out_path))
    return out_path


if __name__ == "__main__":
    print(combined_leaderboard_md())
