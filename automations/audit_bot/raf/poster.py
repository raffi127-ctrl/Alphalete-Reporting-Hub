"""
Turn a Gemini-generated markdown audit report into a styled HTML poster.

The poster is saved alongside the markdown report in reports/ with the same
basename + .html extension. Open in browser, print, save as PDF, or screenshot.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# WeasyPrint needs Homebrew libs visible to the dynamic linker on macOS.
# Set this BEFORE importing weasyprint.
_BREW_LIB = "/opt/homebrew/lib"
if os.path.isdir(_BREW_LIB):
    existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if _BREW_LIB not in existing.split(":"):
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
            f"{_BREW_LIB}:{existing}" if existing else _BREW_LIB
        )

import markdown

try:
    from weasyprint import HTML as WeasyHTML
    _PDF_AVAILABLE = True
except Exception as e:  # pragma: no cover
    print(f"WeasyPrint unavailable, PDF generation disabled: {e}")
    WeasyHTML = None  # type: ignore
    _PDF_AVAILABLE = False


# Inline CSS — clean, print-friendly, table-focused (mirrors the chat-style layout)
CSS = """
:root {
    --bg: #ffffff;
    --text: #111827;
    --muted: #6b7280;
    --border: #d1d5db;
    --soft-border: #e5e7eb;
    --hit-bg: #dcfce7;
    --hit-fg: #14532d;
    --partial-bg: #fef3c7;
    --partial-fg: #78350f;
    --miss-bg: #fee2e2;
    --miss-fg: #7f1d1d;
    --red-flag-bg: #fef2f2;
    --red-flag-border: #dc2626;
    --green-flag-bg: #f0fdf4;
    --green-flag-border: #16a34a;
}

* { box-sizing: border-box; }

body {
    margin: 0;
    padding: 32px 24px;
    background: #f3f4f6;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, system-ui, sans-serif;
    color: var(--text);
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
}

.poster {
    max-width: 920px;
    margin: 0 auto;
    background: var(--bg);
    border: 1px solid var(--border);
    padding: 0;
    overflow: hidden;
}

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

.poster-body {
    padding: 36px 44px 44px;
}

h1.title {
    font-size: 24px;
    font-weight: 700;
    margin: 0 0 4px;
    letter-spacing: -0.3px;
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

table.metadata {
    width: 100%;
    border-collapse: collapse;
    margin: 0 0 22px;
    font-size: 14px;
    border: 1px solid var(--border);
}

table.metadata th {
    background: #f9fafb;
    color: var(--muted);
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    padding: 8px 10px;
    text-align: center;
    border-bottom: 1px solid var(--border);
    border-right: 1px solid var(--soft-border);
}

table.metadata th:last-child { border-right: none; }

table.metadata td {
    padding: 12px 10px;
    text-align: center;
    font-weight: 600;
    font-size: 15px;
    border-right: 1px solid var(--soft-border);
}

table.metadata td:last-child { border-right: none; }

table.metadata td.score-cell { font-size: 22px; font-weight: 800; }
table.metadata td.score-good { color: #15803d; background: #f0fdf4; }
table.metadata td.score-mid  { color: #b45309; background: #fffbeb; }
table.metadata td.score-bad  { color: #b91c1c; background: #fef2f2; }

table.metadata.scores { margin-top: 12px; }
table.metadata.scores th { background: #eef2ff; color: #312e81; }

/* 11-frame scorecard grid */
.frame-grid-header {
    margin-top: 18px;
    margin-bottom: 8px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--muted);
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--soft-border);
    padding-bottom: 8px;
}

.frame-grid-header .legend {
    font-size: 9.5px;
    letter-spacing: 0.5px;
    font-weight: 600;
    color: #71717a;
    display: inline-flex;
    gap: 12px;
    align-items: center;
}

.legend-dot {
    display: inline-block;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    margin-right: 4px;
    vertical-align: middle;
}

.legend-dot.frame-good { background: #15803d; }
.legend-dot.frame-mid { background: #b45309; }
.legend-dot.frame-bad { background: #b91c1c; }

.frame-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6px;
    margin-bottom: 18px;
}

.frame-cell {
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 8px 6px;
    text-align: center;
    background: #fafafa;
}

.frame-cell .frame-num {
    font-size: 9px;
    font-weight: 700;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 1px;
}

.frame-cell .frame-name {
    font-size: 11px;
    font-weight: 600;
    margin: 2px 0 4px;
    color: var(--text);
    line-height: 1.2;
}

.frame-cell .frame-score {
    font-size: 18px;
    font-weight: 800;
}

.frame-cell.frame-good {
    background: #f0fdf4;
    border-color: #16a34a;
}
.frame-cell.frame-good .frame-score { color: #15803d; }

.frame-cell.frame-mid {
    background: #fffbeb;
    border-color: #d97706;
}
.frame-cell.frame-mid .frame-score { color: #b45309; }

.frame-cell.frame-bad {
    background: #fef2f2;
    border-color: #dc2626;
}
.frame-cell.frame-bad .frame-score { color: #b91c1c; }

.date-line {
    font-size: 12px;
    color: var(--muted);
    margin-bottom: 24px;
}

section {
    margin: 22px 0;
}

section h2 {
    font-size: 13px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--muted);
    margin: 0 0 10px;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--soft-border);
}

section p { margin: 0 0 8px; }
section ul, section ol { padding-left: 22px; margin: 0; }
section li { margin-bottom: 6px; }

.headline-text {
    font-size: 16px;
    font-weight: 600;
    color: var(--text);
    line-height: 1.45;
}

.red-flags {
    background: var(--red-flag-bg);
    border: 1px solid var(--red-flag-border);
    border-left: 5px solid var(--red-flag-border);
    padding: 16px 20px;
    border-radius: 4px;
}

.red-flags h2 {
    color: var(--red-flag-border);
    border-bottom: none;
    margin-bottom: 6px;
    padding-bottom: 0;
}

.red-flags.clean {
    background: var(--green-flag-bg);
    border-color: var(--green-flag-border);
    border-left-color: var(--green-flag-border);
}

.red-flags.clean h2 {
    color: #15803d;
}

table.scorecard {
    width: 100%;
    border-collapse: collapse;
    font-size: 13.5px;
    border: 1px solid var(--border);
}

table.scorecard th {
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

table.scorecard td {
    padding: 12px;
    border-bottom: 1px solid var(--soft-border);
    vertical-align: top;
}

table.scorecard tr:last-child td { border-bottom: none; }

table.scorecard .num-col,
table.scorecard td.frame-num {
    width: 32px;
    text-align: center;
    color: var(--muted);
    font-weight: 600;
}

table.scorecard .score-col,
table.scorecard td.score {
    width: 48px;
    text-align: center;
    font-size: 18px;
}

table.scorecard .frame-col { width: 160px; font-weight: 600; }
table.scorecard td.frame-name { font-weight: 600; }

/* Feedback column gets the lion's share of the width per Rafael 2026-05-29 */
table.scorecard td:nth-child(4) {
    min-width: 280px;
    line-height: 1.55;
}
table.scorecard td:nth-child(5) {
    width: 200px;
    font-size: 12.5px;
}

.row-hit     { background: var(--hit-bg); }
.row-partial { background: var(--partial-bg); }
.row-miss    { background: var(--miss-bg); }

td em {
    font-style: italic;
    font-size: 12.5px;
    color: var(--miss-fg);
}
.row-hit td em     { color: var(--hit-fg); }
.row-partial td em { color: var(--partial-fg); }

details {
    background: #f9fafb;
    border: 1px solid var(--soft-border);
    border-radius: 4px;
    padding: 12px 16px;
    margin-top: 14px;
}

summary {
    cursor: pointer;
    font-size: 12px;
    color: var(--muted);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
}

details[open] summary { margin-bottom: 12px; }

details p, details pre {
    font-size: 12.5px;
    line-height: 1.6;
    white-space: pre-wrap;
}

@media print {
    body { background: #fff; padding: 0; }
    .poster { border: none; max-width: none; padding: 24px; }
    section { break-inside: avoid; }
    table.scorecard tr { break-inside: avoid; }
}
"""


def _name_from_filename(md_path: Path | None) -> str | None:
    """Extract a rep name from the markdown filename stem. e.g.
    'Jordan_2026-05-28.md' → 'Jordan'. Returns None if it's a placeholder
    or unrecognizable."""
    if md_path is None:
        return None
    stem = md_path.stem
    # Strip trailing date pattern: _YYYY-MM-DD or _YYYY-MM-DD_N
    name_part = re.sub(r"_\d{4}-\d{2}-\d{2}(?:_\d+)?$", "", stem)
    name_part = name_part.replace("_", " ").strip()
    if not name_part:
        return None
    if name_part.lower() in _PLACEHOLDER_REP_NAMES:
        return None
    # Reject filenames that obviously aren't a rep name
    obviously_not_a_name = (
        "image from ios", "new recording", "voice memo", "audio",
        "interview", "2nd rd", "recording",
    )
    if any(s in name_part.lower() for s in obviously_not_a_name):
        return None
    return name_part


def _parse_you_counter(md_text: str) -> str:
    """Extract the You counter total from the markdown.
    Returns "N" if found, or "—" if not."""
    m = re.search(r"Total\s+\"?you\"?\s+instances[^:]*:\s*\*?\*?(\d+)", md_text, re.IGNORECASE)
    if m:
        return m.group(1)
    return "—"


def _parse_frame_scores(md_text: str) -> list[dict]:
    """Extract the 11 frame scores from the scorecard table.
    Returns list of dicts: [{'num': '1', 'name': 'Intro / Posture', 'score': '✅'}, ...]
    """
    # Find the scorecard table — first table that has "Score" and "Frame" headers
    frames = []
    # Match rows like "| 1  | Intro / Posture | ✅ | ... | ... |"
    for m in re.finditer(
        r"^\|\s*(\d{1,2})\s*\|\s*([^|]+?)\s*\|\s*(✅|⚠️|❌)\s*\|",
        md_text,
        re.MULTILINE,
    ):
        frames.append({
            "num": m.group(1),
            "name": m.group(2).strip(),
            "score": m.group(3),
        })
    return frames


_FRAME_SCORE_MAP = {"✅": 3, "⚠️": 2, "❌": 0}


def _parse_metadata(md_text: str) -> dict:
    """Pull metadata out of the report.

    New format has TWO tables stacked at the top:
      Row A: | Interviewer | Applicant | Format | Length |
      Row B: | Tonality | D2D Framing | Pay Explanation | Overall |

    Falls back to older single-table or title-line formats for legacy reports.
    """
    md = {
        "interviewer": "Unknown",
        "applicant": "Unknown",
        "format": "—",
        "length": "—",
        "posture": "—",  # was "tonality" — renamed 2026-05-29
        "d2d": "—",
        "pay": "—",
        "overall": "—",
        "you_count": "—",
        "date": "—",
        "frames": [],
    }

    # Look at all pipe-delimited rows
    rows = re.findall(r"^\|(.+)\|$", md_text, flags=re.MULTILINE)
    for row in rows:
        cells = [c.strip() for c in row.split("|")]
        if not cells or cells[0].startswith("---") or cells[0].startswith(":"):
            continue
        lower = [c.lower() for c in cells]

        # New format Row A: 4-col Interviewer/Applicant/Format/Length value row
        if len(cells) == 4 and "📹" in row + "👥" or (len(cells) == 4 and any(
            x in lower[2] for x in ("zoom", "in-person", "in person")
        )):
            # Skip if this row is the header
            if any("interviewer" in c for c in lower):
                continue
            if md["interviewer"] == "Unknown":
                md["interviewer"] = cells[0]
                md["applicant"] = cells[1]
                md["format"] = cells[2]
                md["length"] = cells[3]
            continue

        # New format Row B: 4-col scores row (e.g. "3/10 | 2/5 | 1/5 | 0/10")
        if len(cells) == 4 and all(re.match(r"\d+(?:\.\d+)?/\d+", c) for c in cells):
            md["posture"] = cells[0]
            md["d2d"] = cells[1]
            md["pay"] = cells[2]
            md["overall"] = cells[3]
            continue

        # Old format: single 6-col metadata table (Interviewer/Applicant/Format/Length/Tonality/Overall)
        if len(cells) == 6 and not any("interviewer" in c for c in lower):
            if md["interviewer"] == "Unknown":
                md["interviewer"] = cells[0]
                md["applicant"] = cells[1]
                md["format"] = cells[2]
                md["length"] = cells[3]
                md["posture"] = cells[4]
                md["overall"] = cells[5]

    # Fallback: extract from old-format title line "# Audit — Rep × Applicant"
    if md["interviewer"] == "Unknown":
        title_match = re.search(
            r"^#\s+Audit\s+[—–-]\s+(.+?)\s+[×x]\s+(.+?)\s*$",
            md_text,
            flags=re.MULTILINE,
        )
        if title_match:
            md["interviewer"] = title_match.group(1).strip()
            md["applicant"] = title_match.group(2).strip()

    # Fallback: Recording length
    if md["length"] == "—":
        length_match = re.search(r"\*\*Recording length:\*\*\s*([0-9:]+)", md_text)
        if length_match:
            md["length"] = length_match.group(1)

    # Fallback: Posture grade (was "Tonality grade")
    if md["posture"] == "—":
        ton_match = re.search(
            r"(?:\*\*(?:Posture|Tonality) grade:\*\*|(?:Posture|Tonality)\s*/\s*delivery\s*grade:)\s*(\d+(?:\.\d+)?/10)",
            md_text,
            flags=re.IGNORECASE,
        )
        if ton_match:
            md["posture"] = ton_match.group(1)

    # Date audited
    date_match = re.search(r"\*\*Date audited:\*\*\s*(\S+)", md_text)
    if date_match:
        md["date"] = date_match.group(1)

    # You counter
    md["you_count"] = _parse_you_counter(md_text)

    # 11 frame scores
    md["frames"] = _parse_frame_scores(md_text)

    return md


def _score_class(score_str: str) -> str:
    """Return a CSS class hint based on a 'X/Y' score (handles /10 and /5)."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+)", score_str)
    if not m:
        return ""
    val = float(m.group(1))
    denom = float(m.group(2))
    if denom <= 0:
        return ""
    pct = val / denom
    if pct >= 0.70:
        return "score-good"
    if pct >= 0.40:
        return "score-mid"
    return "score-bad"


def _colorize_scorecard(html: str) -> str:
    """Add row-hit / row-partial / row-miss classes to scorecard table rows
    based on which emoji is in the row."""
    def add_class(match):
        row = match.group(0)
        if "✅" in row:
            cls = "row-hit"
        elif "⚠️" in row:
            cls = "row-partial"
        elif "❌" in row:
            cls = "row-miss"
        else:
            return row
        return row.replace("<tr>", f'<tr class="{cls}">', 1)

    return re.sub(r"<tr>\s*<td[^>]*>\s*\d+\s*</td>.*?</tr>", add_class, html, flags=re.DOTALL)


def _classify_table_cells(html: str) -> str:
    """Mark the scorecard table with class, then classify its cells."""
    def in_scorecard(table_html: str) -> bool:
        return "Score" in table_html and "Frame" in table_html

    def process_table(m):
        table_html = m.group(0)
        if not in_scorecard(table_html):
            return table_html

        # Tag the table itself so CSS targets it
        table_html = table_html.replace("<table>", '<table class="scorecard">', 1)

        # Header columns
        table_html = re.sub(r"<th>\s*#\s*</th>", '<th class="num-col">#</th>', table_html)
        table_html = re.sub(r"<th>\s*Frame\s*</th>", '<th class="frame-col">Frame</th>', table_html)
        table_html = re.sub(r"<th>\s*Score\s*</th>", '<th class="score-col">Score</th>', table_html)

        # Body rows
        def row(row_match):
            row_html = row_match.group(0)
            row_html = re.sub(r"<td>(\s*\d+\s*)</td>", r'<td class="frame-num">\1</td>', row_html, count=1)
            # Frame name cell (next td after frame-num)
            row_html = re.sub(r"<td>([^<]+)</td>", r'<td class="frame-name">\1</td>', row_html, count=1)
            row_html = re.sub(r"<td>\s*(✅|⚠️|❌)\s*</td>", r'<td class="score">\1</td>', row_html, count=1)
            return row_html

        table_html = re.sub(r"<tr>.*?</tr>", row, table_html, flags=re.DOTALL)
        return table_html

    return re.sub(r"<table>.*?</table>", process_table, html, flags=re.DOTALL)


def _wrap_sections(html: str) -> str:
    """Wrap each <h2>...</h2> + following content into a <section> tag."""
    # Split on h2 tags and rebuild
    parts = re.split(r"(<h2[^>]*>.*?</h2>)", html, flags=re.DOTALL)
    if len(parts) <= 1:
        return html

    out = [parts[0]]  # anything before the first h2
    i = 1
    while i < len(parts):
        h2 = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        out.append(f"<section>{h2}{body}</section>")
        i += 2
    return "".join(out)


def _stylize_headline(html: str) -> str:
    """Make the first paragraph after the Headline h2 visually prominent."""
    pattern = re.compile(
        r"(<h2[^>]*>\s*Headline\s*</h2>)\s*<p>(.*?)</p>",
        re.DOTALL,
    )
    return pattern.sub(r'\1<p class="headline-text">\2</p>', html)


def _strip_scorecard_blurb(html: str) -> str:
    """Remove the 'Use these emoji exactly...' explainer paragraph before the
    scorecard table — it's instruction for Gemini, not useful in the poster."""
    pattern = re.compile(
        r"(<h2[^>]*>Frame-by-frame scorecard</h2>)\s*"
        r"(?:<p>[^<]*emoji[^<]*</p>\s*)?"
        r"(?:<ul>.*?</ul>\s*)?"
        r"(?:<p>.*?Feedback.*?</p>\s*)?"
        r"(?:<p>.*?Quote.*?</p>\s*)?",
        re.DOTALL | re.IGNORECASE,
    )
    return pattern.sub(r"\1", html)


def _wrap_red_flags(html: str) -> str:
    """Wrap the Red flags <section> in a callout-style class."""
    pattern = re.compile(
        r"<section>(<h2[^>]*>🚩[^<]*Red flags fired[^<]*</h2>)(.*?)</section>",
        re.DOTALL,
    )

    def wrap(m):
        h2 = m.group(1)
        body = m.group(2).strip()
        clean_class = " clean" if "None" in body and "clean" in body.lower() else ""
        return f'<section class="red-flags{clean_class}">{h2}{body}</section>'

    return pattern.sub(wrap, html)


def _wrap_transcript(html: str) -> str:
    """Collapse the Full transcript section into a <details> element."""
    pattern = re.compile(
        r"<h2[^>]*>Full transcript</h2>(.*?)$",
        re.DOTALL,
    )

    def wrap(m):
        body = m.group(1).strip()
        return (
            f'<details><summary>Full transcript (click to expand)</summary>'
            f'<div>{body}</div></details>'
        )

    return pattern.sub(wrap, html)


_PLACEHOLDER_REP_NAMES = {
    "", "unknown", "unknown rep", "rep", "rep name", "the rep",
    "interviewer", "name", "[name]", "[rep name]",
    "applicant", "applicant name", "[applicant]", "[applicant name]",
    "unknown applicant", "the applicant",
    "name not stated", "not stated", "[name not stated]",
    "n/a", "none", "[n/a]",
}


def _display_name(name: str) -> str:
    """Show 'Unidentified' instead of literal placeholders like '[Rep Name]'
    or '[Applicant Name]'. Also catches anything wrapped entirely in brackets."""
    if not name:
        return "Unidentified"
    s = name.strip()
    if s.lower() in _PLACEHOLDER_REP_NAMES:
        return "Unidentified"
    # Catch anything wrapped in brackets like "[Some Name]" — that's almost
    # always a template placeholder Gemini didn't fill in.
    if s.startswith("[") and s.endswith("]"):
        return "Unidentified"
    return name


def _you_count_class(count_str: str) -> str:
    """Color the You counter: 0-2 green, 3-5 yellow, 6+ red."""
    try:
        n = int(count_str)
    except (ValueError, TypeError):
        return ""
    if n <= 2:
        return "score-good"
    if n <= 5:
        return "score-mid"
    return "score-bad"


def _build_metadata_table(meta: dict) -> str:
    """Render the metadata header as THREE stacked tables:
    identity (Interviewer/Applicant/Format/Length),
    scores (Posture/D2D/Pay/Overall + 'You' counter),
    frame scorecard grid (11 frames each /3).
    """
    pos_class = _score_class(meta["posture"])
    d2d_class = _score_class(meta["d2d"])
    pay_class = _score_class(meta["pay"])
    over_class = _score_class(meta["overall"])
    you_class = _you_count_class(meta["you_count"])
    interviewer_display = _display_name(meta["interviewer"])
    applicant_display = _display_name(meta["applicant"])

    # Build the 11-frame grid HTML
    frame_grid_html = ""
    if meta["frames"]:
        cells = []
        for f in meta["frames"]:
            score_val = _FRAME_SCORE_MAP.get(f["score"], 0)
            cls = (
                "frame-good" if score_val == 3
                else "frame-mid" if score_val == 2
                else "frame-bad"
            )
            # Shorter name for display
            short_name = f["name"]
            # Strip parenthetical timeframes like "(Entry / 3-5 wks)"
            short_name = re.sub(r"\s*\([^)]*\)\s*", "", short_name).strip()
            cells.append(
                f'<div class="frame-cell {cls}">'
                f'<div class="frame-num">#{f["num"]}</div>'
                f'<div class="frame-name">{short_name}</div>'
                f'<div class="frame-score">{score_val}/3</div>'
                f'</div>'
            )
        frame_grid_html = (
            '<div class="frame-grid-header">11-Frame Scorecard '
            '<span class="legend">'
            '<span class="legend-dot frame-good"></span> 3/3 hit  '
            '<span class="legend-dot frame-mid"></span> 2/3 partial  '
            '<span class="legend-dot frame-bad"></span> 0/3 miss'
            '</span></div>'
            '<div class="frame-grid">' + "".join(cells) + "</div>"
        )

    return f"""
<table class="metadata">
  <thead>
    <tr>
      <th>Interviewer</th>
      <th>Applicant</th>
      <th>Format</th>
      <th>Length</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>{interviewer_display}</td>
      <td>{applicant_display}</td>
      <td>{meta["format"]}</td>
      <td>{meta["length"]}</td>
    </tr>
  </tbody>
</table>

<table class="metadata scores">
  <thead>
    <tr>
      <th>Posture</th>
      <th>D2D Framing</th>
      <th>Pay Explanation</th>
      <th>Overall</th>
      <th>"You" Count</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td class="score-cell {pos_class}">{meta["posture"]}</td>
      <td class="score-cell {d2d_class}">{meta["d2d"]}</td>
      <td class="score-cell {pay_class}">{meta["pay"]}</td>
      <td class="score-cell {over_class}">{meta["overall"]}</td>
      <td class="score-cell {you_class}">{meta["you_count"]}</td>
    </tr>
  </tbody>
</table>

{frame_grid_html}
"""


def markdown_to_poster_html(md_text: str, md_path: Path | None = None) -> str:
    """Convert an audit markdown report into a styled HTML poster.
    md_path lets us fall back to the filename for the rep name when Gemini
    couldn't ID one (e.g., 'Jordan_2026-05-28.md' → 'Jordan')."""

    # 1. Extract metadata
    meta = _parse_metadata(md_text)

    # 1b. Filename-based name fallback (per Rafael 2026-05-29):
    # If parser says interviewer is a placeholder but the filename has a
    # recognizable name, use that. This makes the PDF title match the file.
    interviewer_disp_check = _display_name(meta["interviewer"])
    if interviewer_disp_check == "Unidentified":
        filename_name = _name_from_filename(md_path)
        if filename_name:
            meta["interviewer"] = filename_name

    # 2. Strip the top header + metadata tables from the markdown so we don't
    #    render them again (we'll inject our own styled header).
    body_md = md_text
    # Remove the top-level # heading
    body_md = re.sub(r"^#\s+[^\n]+\n+", "", body_md, count=1)
    # Remove up to TWO consecutive metadata tables (identity row + scores row).
    # Each table = header row + separator row + values row + optional blank lines.
    for _ in range(2):
        body_md = re.sub(
            r"^\|[^\n]+\|\n\|[-:\s|]+\|\n\|[^\n]+\|\n+",
            "",
            body_md,
            count=1,
        )
    # Remove the "Date audited:" line
    body_md = re.sub(r"^\*\*Date audited:\*\*[^\n]*\n+", "", body_md, count=1)
    # Remove leading "---" if present
    body_md = re.sub(r"^---\s*\n+", "", body_md, count=1)

    # 3. Convert remaining markdown to HTML
    body_html = markdown.markdown(
        body_md,
        extensions=["tables", "fenced_code", "nl2br"],
    )

    # 4. Apply structural enhancements (order matters)
    body_html = _strip_scorecard_blurb(body_html)
    body_html = _colorize_scorecard(body_html)
    body_html = _classify_table_cells(body_html)
    body_html = _wrap_transcript(body_html)
    body_html = _stylize_headline(body_html)
    body_html = _wrap_sections(body_html)
    body_html = _wrap_red_flags(body_html)

    interviewer_disp = _display_name(meta["interviewer"])
    applicant_disp = _display_name(meta["applicant"])
    title = f"Audit — {interviewer_disp} × {applicant_disp}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>{CSS}</style>
</head>
<body>
    <div class="poster">
        <div class="brand-bar">Alphalete <span class="accent">Audits</span></div>
        <div class="poster-body">
            <h1 class="title">
                <span class="subtitle">2nd Round Audit</span>
                {interviewer_disp} × {applicant_disp}
            </h1>
            {_build_metadata_table(meta)}
            <div class="date-line">Date audited: {meta['date']}</div>
            {body_html}
        </div>
    </div>
</body>
</html>
"""
    return html


def write_pdf_from_html(html_text: str, pdf_path: Path) -> Path:
    """Render HTML to PDF using WeasyPrint."""
    if not _PDF_AVAILABLE:
        raise RuntimeError("WeasyPrint not available — install dependencies")
    WeasyHTML(string=html_text).write_pdf(str(pdf_path))
    return pdf_path


def write_poster(md_path: Path, *, also_pdf: bool = True, keep_html: bool = False) -> Path:
    """Read a markdown report, render to HTML, then convert to PDF.

    Returns the path to the PDF (if generated), otherwise the HTML path.
    By default we DO NOT keep the HTML on disk — Rafael only wants the PDF.
    Set keep_html=True for debugging.
    """
    md_text = md_path.read_text(encoding="utf-8")
    html = markdown_to_poster_html(md_text, md_path=md_path)

    pdf_path = md_path.with_suffix(".pdf")
    html_path = md_path.with_suffix(".html")

    if also_pdf and _PDF_AVAILABLE:
        try:
            write_pdf_from_html(html, pdf_path)
            if keep_html:
                html_path.write_text(html, encoding="utf-8")
            return pdf_path
        except Exception as e:
            # Fall back to HTML if PDF gen fails
            print(f"PDF generation failed: {e}; falling back to HTML")
            html_path.write_text(html, encoding="utf-8")
            return html_path

    # PDF not available — write HTML
    html_path.write_text(html, encoding="utf-8")
    return html_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python poster.py <path-to-report.md>")
        sys.exit(1)
    md = Path(sys.argv[1]).resolve()
    out = write_poster(md)
    print(f"Wrote {out}")
