"""Read the 'Rep Count' column off every morning's Country Tracker image, per ICD
per day, so the headcount board can carry a DAILY breakdown.

WHY THE IMAGES (Eve, 2026-09-12). The trackers' `Rep Count` is a running number
for the week: it only ever shows TODAY's value, and Tableau keeps no per-day
history of it. The only record of what it said on Tuesday is the Tuesday post in
the channel, so the breakdown has to be rebuilt from the posted PNGs — "si el
tracker que subiste el lunes muestra que rafael tenía 15 personas, y al otro día
16, el desglose dice monday 15 tuesday 16 (también puede bajar)".

WHY THIS RUNS ON LUCY 1. The Windows token can't download Slack files (403 on
url_private); Lucy 1's token is the one owner_chat_texts already downloads these
exact PNGs with every morning. So this does the download AND the reading there,
and leaves plain text in output/logs where `lucy logtail` can reach it.

WHAT IT WRITES — nothing to any Sheet. One log per run,
output/logs/hc-tracker-readings-<start>_<end>.log, pipe-separated:
    F|day|tracker|file_id|reply_ts|rows_on_image|dates_printed_on_image
    R|day|tracker|board ICD|name as printed|rep count
    M|day|tracker|board ICD|NOT ON IMAGE
    X|day|tracker|reason the image could not be read
The same lines also land in the 'HC Tracker Readings' tab of the Mini Control
workbook, and every row read off every image in 'HC Tracker Raw' — `logtail`
returns 470 characters, which can't carry ~2,000 lines back to a laptop. Those
two tabs are this job's own scratch output; nothing else reads them.
The day is the POST date. Which week/day a reading belongs to is decided by the
caller from `dates_printed_on_image`, not guessed here: a Monday-morning board
can still be showing the week that just closed.

RE-POSTS. Tableau sometimes loads late and the board is re-posted the same day
(8/26 inside the thread, 8/29 as a second 'UPDATED' thread). Every thread of
the day is searched and each tracker takes its NEWEST matching reply, so the
corrected picture wins and a board the UPDATED thread left out (9/18: it only
re-posted Box) is still read from the morning thread.

TALL IMAGES ARE SLICED. The vision API downsizes anything over ~1568px on its
long edge, which turns a 60-row table into unreadable blur. Each PNG is cut into
overlapping horizontal bands sent in order in ONE request, so the header stays
in context and no band is shrunk.

    python -m automations.org_active_headcount.tracker_readings \
        --start 2026-07-13 --end 2026-09-12
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import io
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "output" / "_hc_trackers"
LOGS = REPO / "output" / "logs"

SHEET_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
BOARD_TAB = "Org Active Headcount"      # renamed from '... Test 2' 2026-09-13
BOARD_GID = 1529537631                  # opened by gid: survives the next rename

# tracker spec id (tableau_screenshots.pages) -> the board's 'Campaign' value
TRACKERS = {"att_country": "fiber", "nds": "nds",
            "b2b_att_country": "b2b", "b2b_box": "box"}

MODEL = "claude-opus-4-8"          # same model screenshot_roster reads images with
BAND = 1400                        # px per slice after scaling to MAX_W
OVERLAP = 140
MAX_W = 1568

# The column to read, per tracker. BOX carries BOTH 'Selling Rep Count' and
# 'Total Rep Count'; left to choose, the first run read one or the other day to
# day, and only the 'Total Rep Count' days matched the weekly history.
COLUMN = {"b2b_box": "Total Rep Count"}

# Trackers read as TWO COLUMN STRIPS at full resolution instead of whole bands.
# The Fiber board is wide: scaled down to fit, '17' read as '7' and '18' as '8'
# (checked against the weekly history, 2026-09-12). So a first call only LOCATES
# the name column and the count column, and the second reads just those two
# strips, cut from the original pixels and placed side by side on the same rows.
# NDS is not here: its whole-band reading matched the weekly history 100%.
STRIPS = {"att_country", "b2b_att_country"}

# BOX is read by VOTE. Its board is small and prints 'Selling Rep Count' and
# 'Total Rep Count' side by side; both the band and the strip method mixed them
# up (and the strip locator sometimes landed on a units column: 80, 94, 142 for
# owners with ~20 heads). So: upscale the small image, ask for BOTH columns by
# name in every row, read it BOX_VOTES times, and keep a Total only when a
# majority of the reads agree. No majority = null, never a guess.
BOX = "b2b_box"
BOX_VOTES = 3

# 3rd BOX attempt (2026-09-13) — WHY THE FIRST TWO FAILED, from Eve's own
# screenshots of the board: the 'Daily Tracker Metrics' table (where 'Total Rep
# Count' lives) has NO OWNER NAMES, only 'Rank'. Its owner is found in the
# 'Daily Tracker Sales' table next to it: a Rank's 'Sales ELE' + 'Sales Gas'
# equals that owner's 'Grand Total' (9/4: rank 1 = 126 = Roshan, rank 4 = 61 =
# Ryan, rank 5 = 37 = Carlos, rank 10 = 8 = Abel). Reading "by position" only
# works while both tables happen to be in the same order, which is exactly what
# breaks early in a week — so the two tables are read SEPARATELY and joined on
# that sum, in code, where the join can be checked.
_BOX_SCHEMA = {
    "type": "object",
    "properties": {
        "section_dates": {"type": "string", "description":
            "The day headers of the CURRENT-week section you read (e.g. "
            "'Mon (08-31) .. Fri (09-04)')."},
        "sales": {"type": "array", "description":
            "'Daily Tracker Sales' (current week): one item per owner row.",
            "items": {"type": "object", "properties": {
                "owner": {"type": "string"},
                "grand_total": {"type": ["integer", "null"]}},
                "required": ["owner", "grand_total"], "additionalProperties": False}},
        "metrics": {"type": "array", "description":
            "'Daily Tracker Metrics' (current week): one item per Rank row.",
            "items": {"type": "object", "properties": {
                "rank": {"type": ["integer", "null"]},
                "selling_rep_count": {"type": ["integer", "null"]},
                "total_rep_count": {"type": ["integer", "null"]},
                "sales_ele": {"type": ["integer", "null"]},
                "sales_gas": {"type": ["integer", "null"]}},
                "required": ["rank", "selling_rep_count", "total_rep_count",
                             "sales_ele", "sales_gas"],
                "additionalProperties": False}},
    },
    "required": ["section_dates", "sales", "metrics"],
    "additionalProperties": False,
}

_BOX_PROMPT = (
    "These {n} images are consecutive horizontal slices, top to bottom, of ONE "
    "screenshot of the 'Box Daily Tracker'. Read ONLY the CURRENT-week section "
    "at the top: the 'Daily Tracker Sales' table on the left and the 'Daily "
    "Tracker Metrics' table on the right. IGNORE 'Current vs Prior Weeks', "
    "'Previous Week Sales' and 'Previous Week Metrics'.\n"
    "1) sales: every owner row of 'Daily Tracker Sales' — the owner name exactly "
    "as printed and its 'Grand Total' (the last column). Skip the 'Grand Total' "
    "row itself.\n"
    "2) metrics: every row of 'Daily Tracker Metrics' — Rank, 'Selling Rep "
    "Count', 'Total Rep Count', 'Sales ELE', 'Sales Gas'. This table has NO "
    "names; do not invent any. Skip its 'Grand Total' row. A blank cell is null, "
    "and a column the table does not have is null in every row.\n"
    "Copy every number exactly as printed; never compute or reorder.")

_SCHEMA = {
    "type": "object",
    "properties": {
        "dates_printed": {"type": "string", "description":
            "Every date / week-ending / date-range text printed on the board "
            "(title, filters, column headers), copied exactly, joined with ' ; '. "
            "Empty string if none."},
        "rep_count_header": {"type": "string", "description":
            "The exact header text of the column you read the counts from."},
        "rows": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description":
                    "The owner / ICD name label of the row, exactly as printed."},
                "rep_count": {"type": ["integer", "null"], "description":
                    "The Rep Count cell of THAT SAME row. null if blank."},
            },
            "required": ["owner", "rep_count"],
            "additionalProperties": False}},
    },
    "required": ["dates_printed", "rep_count_header", "rows"],
    "additionalProperties": False,
}

_PROMPT = (
    "These {n} images are consecutive horizontal slices, top to bottom, of ONE "
    "tall screenshot of a sales tracker table (consecutive slices overlap a "
    "little, so a row may appear twice — list it once). The table has one row "
    "per owner (ICD) and a column headed '{col}'.\n\n"
    "Return every owner row with its '{col}' value, copying the numbers exactly — "
    "never compute or estimate. Read the count from the SAME horizontal row as "
    "the name; if the name and the counts sit in side-by-side tables, follow the "
    "row line across carefully. Skip grand-total / header rows. Also copy every "
    "date or date range printed anywhere on the board.")

_LOCATE_SCHEMA = {
    "type": "object",
    "properties": {
        "dates_printed": {"type": "string", "description":
            "Every date / week-ending / date-range text printed on the board, "
            "copied exactly, joined with ' ; '."},
        "count_header": {"type": "string", "description":
            "The exact header text of the count column you located."},
        "name_left": {"type": "number"}, "name_right": {"type": "number"},
        "count_left": {"type": "number"}, "count_right": {"type": "number"},
    },
    "required": ["dates_printed", "count_header", "name_left", "name_right",
                 "count_left", "count_right"],
    "additionalProperties": False,
}

_LOCATE_PROMPT = (
    "These {n} images are consecutive horizontal slices, top to bottom, of ONE "
    "tall screenshot of a sales tracker, all at the same width. Find the table "
    "that lists owners (ICDs) one per row and has a column headed exactly "
    "'{col}' (if several count columns look alike, it is the one with that exact "
    "header). Return the LEFT and RIGHT edges of (a) the column holding the owner "
    "names and (b) the '{col}' column, as FRACTIONS of the image width (0 = left "
    "edge, 1 = right edge). Also copy every date or date range printed anywhere "
    "on the board.")

_STRIP_PROMPT = (
    "These {n} images are consecutive horizontal slices, top to bottom, of ONE "
    "tall image made of two vertical strips cut from the same table and placed "
    "side by side: the LEFT strip is the owner (ICD) name column, the RIGHT strip "
    "is the '{col}' column. Both strips keep their original vertical positions, "
    "so a name and its count sit on the SAME horizontal line. Consecutive slices "
    "overlap a little — list each row once. Return every owner row with its "
    "'{col}' value, copying the numbers exactly; never compute or estimate. Skip "
    "header and total rows.")


def _slice(im) -> List[bytes]:
    if im.width > MAX_W:
        im = im.resize((MAX_W, round(im.height * MAX_W / im.width)))
    out, top = [], 0
    while True:
        box = im.crop((0, top, im.width, min(top + BAND, im.height)))
        buf = io.BytesIO()
        box.save(buf, format="PNG")
        out.append(buf.getvalue())
        if top + BAND >= im.height or len(out) >= 20:
            return out
        top += BAND - OVERLAP


def _bands(png: Path) -> List[bytes]:
    from PIL import Image
    with Image.open(png) as im:
        return _slice(im.convert("RGB"))


def _strip_bands(png: Path, loc: dict) -> List[bytes]:
    """The name column and the count column, cut from the ORIGINAL pixels and
    pasted side by side on the same rows, then sliced like any band."""
    from PIL import Image
    with Image.open(png) as im:
        im = im.convert("RGB")
        w, h = im.size
        pad = max(6, w // 200)

        def edges(left, right):
            a = max(0, round(float(left) * w) - pad)
            b = min(w, round(float(right) * w) + pad)
            if b - a < 10:
                raise ValueError(f"located column too narrow ({left}..{right})")
            return a, b
        nl, nr = edges(loc["name_left"], loc["name_right"])
        cl, cr = edges(loc["count_left"], loc["count_right"])
        names, counts = im.crop((nl, 0, nr, h)), im.crop((cl, 0, cr, h))
        gap = 16
        strip = Image.new("RGB", (names.width + gap + counts.width, h), "white")
        strip.paste(names, (0, 0))
        strip.paste(counts, (names.width + gap, 0))
        return _slice(strip)


def _ask(images: List[bytes], prompt: str, schema: dict, max_tokens: int = 8000) -> dict:
    import anthropic
    from automations.brand_audit import credentials
    content = [{"type": "image", "source": {
        "type": "base64", "media_type": "image/png",
        "data": base64.standard_b64encode(b).decode()}} for b in images]
    content.append({"type": "text", "text": prompt})
    client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    resp = client.messages.create(
        model=MODEL, max_tokens=max_tokens,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": content}])
    return json.loads(next((b.text for b in resp.content if b.type == "text"), "{}"))


def box_join(sales: List[dict], metrics: List[dict]) -> Dict[str, Optional[int]]:
    """{owner as printed: Total Rep Count, else Selling Rep Count} — pure, no I/O.

    SELLING WHEN THERE IS NO TOTAL (Eve 2026-09-18). From the 9/16 post on, the
    Box Daily Tracker prints only 'Selling Rep Count' — the 'Total Rep Count'
    column is gone from both the current- and previous-week metrics tables, so
    every owner read null and the tab got '-' for BOX (and Carlos) Tue-Thu.
    Eve: use Selling Rep Count. A board that still prints Total keeps Total.

    Each metrics row belongs to the owner whose sales 'Grand Total' equals that
    row's Sales ELE + Sales Gas. Owners sharing a Grand Total are handed out in
    the order the sales table lists them (both tables rank by the same sales),
    and a metrics row whose sum matches NO unused owner is dropped — its owner
    reads as unknown, never as someone else's number."""
    used = set()
    out: Dict[str, Optional[int]] = {}
    for m in sorted(metrics, key=lambda m: (m.get("rank") is None, m.get("rank") or 0)):
        target = (m.get("sales_ele") or 0) + (m.get("sales_gas") or 0)
        for i, s in enumerate(sales):
            if i not in used and s.get("grand_total") is not None \
                    and int(s["grand_total"]) == target:
                used.add(i)
                total = m.get("total_rep_count")
                out[s["owner"]] = total if total is not None else m.get("selling_rep_count")
                break
    return out


def _read_box(png: Path) -> dict:
    """BOX: read both current-week tables BOX_VOTES times, join each read by
    ELE+Gas = Grand Total (box_join), keep an owner's Total Rep Count only when a
    majority of the joined reads agree. No majority = null (the fill writes '-').
    Its own cache name, so the two earlier attempts' readings are never reused."""
    # '.rank-sell' since 2026-09-18: the '.rank.json' reads cached before the
    # Selling fallback hold nulls for every day the board had no Total column.
    cached = png.with_name(png.stem + ".rank-sell.json")
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    bands = _bands(png)
    reads = [_ask(bands, _BOX_PROMPT.format(n=len(bands)), _BOX_SCHEMA)
             for _ in range(BOX_VOTES)]
    votes: Dict[str, List] = {}
    order: List[str] = []
    for rd in reads:
        for owner, total in box_join(rd.get("sales") or [], rd.get("metrics") or []).items():
            key = " ".join(_tokens(owner))
            if not key:
                continue
            if key not in votes:
                votes[key] = []
                order.append(owner)
            votes[key].append(total)
    rows = []
    for owner in order:
        vals = [v for v in votes[" ".join(_tokens(owner))] if v is not None]
        best = max(set(vals), key=vals.count) if vals else None
        ok = best is not None and vals.count(best) * 2 > BOX_VOTES
        rows.append({"owner": owner, "rep_count": best if ok else None,
                     "votes": votes[" ".join(_tokens(owner))]})
    data = {"dates_printed": reads[0].get("section_dates", ""),
            "rep_count_header": f"Total Rep Count, else Selling (rank-join vote x{BOX_VOTES})",
            "rows": rows}
    cached.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


def read_image(png: Path, tid: str) -> dict:
    """{dates_printed, rep_count_header, rows:[{owner, rep_count}]} — cached
    next to the PNG so a re-run never pays for the same picture twice. The strip
    method caches under its own name, so the first run's whole-band readings of
    those trackers are never reused."""
    if tid == BOX:
        return _read_box(png)
    col = COLUMN.get(tid, "Rep Count")
    strips = tid in STRIPS
    cached = png.with_name(png.stem + (".strips.json" if strips else ".json"))
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    bands = _bands(png)
    if not strips:
        data = _ask(bands, _PROMPT.format(n=len(bands), col=col), _SCHEMA)
    else:
        loc = _ask(bands, _LOCATE_PROMPT.format(n=len(bands), col=col),
                   _LOCATE_SCHEMA, max_tokens=2000)
        cut = _strip_bands(png, loc)
        data = _ask(cut, _STRIP_PROMPT.format(n=len(cut), col=col), _SCHEMA)
        data["dates_printed"] = loc.get("dates_printed", "")
        data["rep_count_header"] = f"{loc.get('count_header', '')} (strips)"
    cached.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


def board_icds() -> Dict[str, List[str]]:
    """{campaign lowercase: [ICD as the board writes it]} from the tab's All
    Units block (col B + its 'Campaign' column), found by label."""
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(SHEET_ID)
    try:
        ws = sh.get_worksheet_by_id(BOARD_GID)
    except Exception:                                              # noqa: BLE001
        ws = next(w for w in sh.worksheets() if w.title.strip() == BOARD_TAB)
    g = ws.get_all_values()

    def c(r, k):
        row = g[r] if r < len(g) else []
        return row[k].strip() if k < len(row) else ""
    # By its 'RUNNING WEEK TOTALS' header, not the col-A title: 'All Units' was
    # renamed 'All Campaigns HC' on 2026-09-13 and this lookup died on it.
    hdr = next(i for i in range(len(g))
               if any(str(x).strip().lower().startswith("running week") for x in g[i]))
    camp_col = next(k for k in range(len(g[hdr])) if c(hdr, k).lower() == "campaign")
    out: Dict[str, List[str]] = {}
    r = hdr + 1
    while r < len(g) and not c(r, 1):
        r += 1
    while r < len(g) and c(r, 1):
        out.setdefault(c(r, camp_col).lower(), []).append(c(r, 1))
        r += 1
    return out


def _tokens(s: str) -> List[str]:
    return [t for t in re.split(r"[^a-z]+", (s or "").lower()) if t]


def match(icd: str, rows: List[dict]) -> List[dict]:
    """Rows whose printed owner is this ICD: every word of the source name
    appears in the label (labels can carry an office suffix).

    A label the board CUT OFF ('ATEF CHOUDHU..', 'CARLOS HIDAL..') matches when
    the first name is exact and the cut last name is a prefix of 3+ letters —
    the B2B and BOX trackers truncate long names, and an exact-word test missed
    Atef, Carlos and Valeria on all 60 B2B images of the first run."""
    from automations.org_active_headcount import sources as src
    want = _tokens(src.source_name(icd))
    out = []
    for row in rows:
        label = (row.get("owner") or "").strip()
        got = _tokens(label)
        if label.endswith("..") and len(got) >= 2:
            ok = (got[0] == want[0] and len(got[-1]) >= 3
                  and want[-1].startswith(got[-1]))
        else:
            ok = all(t in got for t in want)
        if ok:
            out.append(row)
    return out


def _day_threads(client, channel: str, day: dt.date) -> List[str]:
    """Every tracker parent posted for `day`, newest first. A day can have TWO:
    a stale board is re-posted in a second 'UPDATED' thread that carries only
    the boards that were redone (9/18: Box alone)."""
    from automations.tableau_screenshots import slack_post as sp
    oldest = dt.datetime.combine(day, dt.time.min).timestamp()
    resp = client.conversations_history(channel=channel, oldest=str(oldest), limit=200)
    titles = (sp.header_title(day), sp._legacy_title(day))
    out: List[str] = []
    for msg in resp.get("messages", []):
        if any(t in (msg.get("text", "") or "") for t in titles):
            ts = msg.get("thread_ts") or msg.get("ts")
            if ts not in out:
                out.append(ts)
    return out


def _latest_files(client, channel: str, day: dt.date) -> Tuple[Optional[str], Dict[str, dict]]:
    """Newest image of each tracker ACROSS every thread of the day (2026-09-18:
    reading only the newest thread — the Box-only UPDATED one — left B2B unread,
    so Carlos (B2B + BOX) stayed empty)."""
    from automations.tableau_screenshots import pages as pages_mod
    from automations.tableau_screenshots import slack_post as sp
    threads = _day_threads(client, channel, day)
    if not threads:
        ts, _legacy = sp.find_thread_ts(client, channel, day)
        threads = [ts] if ts else []
    if not threads:
        return None, {}
    replies = [m for t in threads for m in sp._image_replies(client, channel, t)]
    got = {}
    for tid in TRACKERS:
        spec = pages_mod.by_id(tid)
        hits = sorted((m for m in replies if sp._reply_matches(m, spec, day)),
                      key=lambda m: float(m["ts"]))
        if hits:
            f = next((f for f in hits[-1].get("files") or [] if f.get("url_private")), None)
            if f:
                got[tid] = {"file": f, "reply_ts": hits[-1]["ts"]}
    return threads[0], got


def run(start: dt.date, end: dt.date, workers: int = 6,
        only: Optional[str] = None) -> Path:
    """`only` = one tracker id: read just that board, into its own tabs/log so
    the other trackers' last readings are left untouched."""
    from automations.shared import slack_metrics_post as smp
    from automations.tableau_screenshots.slack_post import ORG_CHANNELS
    from automations.owner_chat_texts.slack_fetch import _download

    client, token = smp._client(), smp._load_token()
    channel = ORG_CHANNELS["alphalete"][0]            # #alphalete-sales
    icds = board_icds()
    lines: List[str] = []
    raw: List[list] = []
    jobs = []
    day = start
    while day <= end:
        try:
            thread, files = _latest_files(client, channel, day)
        except Exception as e:                                     # noqa: BLE001
            thread, files = None, {}
            lines.append(f"X|{day}|*|thread read failed: {type(e).__name__}: {e}")
        if not thread:
            lines.append(f"X|{day}|*|no tracker thread that day")
        for tid in TRACKERS:
            if only and tid != only:
                continue
            if thread and tid not in files:
                lines.append(f"X|{day}|{tid}|no image reply for this tracker")
                continue
            if tid not in files:
                continue
            png = CACHE / day.isoformat() / f"{tid}.png"
            try:
                if not png.exists():
                    _download(files[tid]["file"]["url_private"], token, png)
                jobs.append((day, tid, png, files[tid]))
            except Exception as e:                                 # noqa: BLE001
                lines.append(f"X|{day}|{tid}|download failed: {type(e).__name__}: {e}")
        day += dt.timedelta(days=1)
    print(f"{len(jobs)} image(s) to read, {workers} at a time", flush=True)

    def work(job):
        d, tid, png, meta = job
        try:
            return job, read_image(png, tid), None
        except Exception as e:                                     # noqa: BLE001
            return job, None, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for (d, tid, png, meta), data, err in pool.map(work, jobs):
            if err:
                lines.append(f"X|{d}|{tid}|read failed: {err}")
                continue
            rows = data.get("rows") or []
            raw.extend([str(d), tid, r.get("owner") or "", r.get("rep_count")]
                       for r in rows)
            dates = (data.get("dates_printed") or "").replace("|", "/")
            lines.append(f"F|{d}|{tid}|{meta['file'].get('id')}|{meta['reply_ts']}|"
                         f"{len(rows)}|{dates}|header={data.get('rep_count_header')}")
            for icd in icds.get(TRACKERS[tid], []):
                hits = match(icd, rows)
                if not hits:
                    lines.append(f"M|{d}|{tid}|{icd}|NOT ON IMAGE")
                for h in hits:
                    lines.append(f"R|{d}|{tid}|{icd}|{h['owner']}|{h['rep_count']}")
            print(f"  {d} {tid:16s} {len(rows)} rows", flush=True)

    lines.sort(key=lambda s: (s.split("|")[1], s.split("|")[2], s[0]))
    LOGS.mkdir(parents=True, exist_ok=True)
    suffix = f"-{only}" if only else ""
    out = LOGS / f"hc-tracker-readings{suffix}-{start}_{end}.log"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    bad = sum(1 for s in lines if s[0] in "XM")
    print(f"wrote {out.name}: {len(lines)} line(s), {bad} gap/failure line(s)", flush=True)
    raw.sort(key=lambda r: (r[0], r[1]))
    tab_suffix = f" ({only})" if only else ""
    _to_sheet(READINGS_TAB + tab_suffix, [["kind", "day", "tracker", "a", "b", "c", "d", "e"]]
              + [s.split("|") for s in lines])
    _to_sheet(RAW_TAB + tab_suffix, [["day", "tracker", "owner as printed", "rep count"]] + raw)
    return out


READINGS_TAB = "HC Tracker Readings"
RAW_TAB = "HC Tracker Raw"


def _to_sheet(title: str, rows: List[list]) -> None:
    """Replace this job's own scratch tab in the Mini Control workbook (the one
    a laptop can read). Best-effort: the log on disk is already written."""
    try:
        from automations.day_orchestrator.mini_control import CONTROL_SHEET_ID
        from automations.recruiting_report.fill import open_by_key
        width = max(len(r) for r in rows)
        rows = [[("" if v is None else v) for v in r] + [""] * (width - len(r))
                for r in rows]
        sh = open_by_key(CONTROL_SHEET_ID)
        ws = next((w for w in sh.worksheets() if w.title == title), None)
        if ws is None:
            ws = sh.add_worksheet(title=title, rows=len(rows) + 10, cols=width)
        else:
            ws.clear()
            ws.resize(rows=len(rows) + 10, cols=width)
        ws.update(range_name="A1", values=rows, value_input_option="RAW")
        print(f"  -> '{title}' tab: {len(rows) - 1} row(s)", flush=True)
    except Exception as e:                                         # noqa: BLE001
        print(f"  -> '{title}' tab NOT written: {type(e).__name__}: {e}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", required=True, type=dt.date.fromisoformat)
    ap.add_argument("--end", required=True, type=dt.date.fromisoformat)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only", choices=sorted(TRACKERS),
                    help="read just this tracker, into its own log and tabs")
    a = ap.parse_args(argv)
    run(a.start, a.end, a.workers, a.only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
