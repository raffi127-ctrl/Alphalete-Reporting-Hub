"""🏆 Tier Bonus Breakdown — sales away from the next Fiber tier (Raf Loom, 2026-11-16).

Raf: "for anybody that has Lucy Eco and they're on fiber … remaking a sales
board, but only for the tier bonus … another post saying tier bonus breakdown
… then tag the rep and say you're X away."

SOURCE (one download serves every office)
  Tableau → ATTTRACKER2_1-D2D → view 'New Fiber Internet Rep Breakdown'
  → filters Owner Name / Rep (All) / Time Frame (order date, mon-sun) 'This Week'
  → rows Owner Name | Rep Volume Bonus Tiers | Rep, columns Mon..Sun + Grand Total.
  Tiers as the view labels them (Raf's Loom, 2026-11-16):
    TIER 1 (0-4) · TIER 2 (5-7) · TIER 3 (8-10) · TIER 4 (11+) New Fiber.
  The view highlights reps 1 sale from the next tier; we show the exact gap.
  The tier ranges are read from the view's own captions when present, so a
  ladder change in Tableau flows through; DEFAULT_TIERS is only the fallback.

WHO GETS IT
  Every ACTIVE Lucy Eco office on the AT&T (Fiber) campaign
  (icd_alerts.offices, campaign 'att'). Posted in the office's metrics channel
  (office_metrics.offices), or its Eco channel when it has no metrics row.
  Its own thread, next to the Metrics one: '🏆 Tier Bonus Breakdown — <date>'
  → 1) the board image, 2) one line per group: "2 sales from Tier 3: Ana, Bill".

NO TAGS (Eve + Raf, 2026-11-16): the tagged per-rep list was ~100 lines.
  Names only, grouped; reps look at the post. match_rep/channel_people stay
  for if tags ever come back, but nothing calls them.

MONDAYS: 'This Week' restarts Monday, so a morning run would post an empty
board. Mondays are skipped (the run exits 0).

  python -m automations.fiber_tier_bonus.run                          (dry run: PNGs + text)
  python -m automations.fiber_tier_bonus.run --office raf --post-to D087ZGE2B0F   (test, no tags)
  python -m automations.fiber_tier_bonus.run --live                   (every office)
  python -m automations.fiber_tier_bonus.run --csv file.csv           (offline parse)

Python 3.9 on the Lucys — deferred annotations, no runtime `X | Y`.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import re
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "fiber_tier_bonus"
WORKBOOK = "ATTTRACKER2_1-D2D"
VIEW = "NewFiberInternetRepBreakdown"
VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            f"{WORKBOOK}/{VIEW}")
# The view's week picker, set through the URL for --last-week. Tableau takes a
# filter/parameter by its caption; if it ignores this, the export comes back on
# 'This Week' and the day headers in the log show it.
TIME_FRAME = "Time Frame (order date) (mon-sun)"


def view_url(last_week: bool = False) -> str:
    if not last_week:
        return VIEW_URL
    from urllib.parse import quote
    return f"{VIEW_URL}?{quote(TIME_FRAME)}={quote('Last Week')}&:iid=1"


# The Crosstab dialog's caption for the rep table. Unknown until the probe
# runs; empty = take the first sheet whose export has a 'Rep' column.
WORKSHEET = ""

TITLE = "🏆 Tier Bonus Breakdown"
EMOJI = "trophy"

# (tier number, min sales, max sales or None = no ceiling)
DEFAULT_TIERS: List[Tuple[int, int, Optional[int]]] = [
    (1, 0, 4), (2, 5, 7), (3, 8, 10), (4, 11, None)]

OWNER_COL = "Owner Name"
REP_COL = "Rep"
TOTAL_COL = "Grand Total"


# ---------------------------------------------------------------- parsing ---

class Rep(NamedTuple):
    name: str
    days: List[str]            # one cell per day column ('' = no sale row)
    total: int
    tier_caption: str          # what Tableau printed, e.g. 'TIER 2 (5-7_New_Fiber)'


def read_csv(path: Path) -> List[List[str]]:
    raw = path.read_bytes()
    text = ""
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    delim = "\t" if text.count("\t") > text.count(",") else ","
    return [[c.strip().lstrip("﻿") for c in r]
            for r in csv.reader(text.splitlines(), delimiter=delim)]


def _int(cell: str) -> int:
    try:
        return int(float((cell or "").replace(",", "").strip() or 0))
    except ValueError:
        return 0


_DAY_HDR = re.compile(r"^(mon|tue|wed|thu|fri|sat|sun)\w*\b", re.I)


def _is_sales_measure(v: str) -> bool:
    return "count" in (v or "").lower()


def _measure_col(header: List[str], body: List[List[str]], rep_i: int,
                 day_idx: List[int]) -> Optional[int]:
    """The 'Measure Names' column, when the view has more than one measure:
    a column (outside the day columns) whose cells name a sales COUNT on some
    rows and something else on others. None when every row is one measure."""
    for i in range(len(header)):
        if i == rep_i or i in day_idx or header[i] == TOTAL_COL:
            continue
        vals = {r[i] for r in body if i < len(r) and r[i]}
        if len(vals) >= 2 and any(_is_sales_measure(v) for v in vals):
            return i
    return None


def parse(rows: List[List[str]]) -> Tuple[List[str], Dict[str, List[Rep]]]:
    """Crosstab -> (day labels, {owner: [Rep, ...]}).

    Finds the header row by its 'Rep' cell (Tableau can put a caption row such
    as 'sp.Order Date (copy)' above it). Owner/tier cells left blank under a
    group carry down. The tier column is whichever header mentions 'tier'.
    Day columns = everything after Rep up to 'Grand Total'."""
    hi = next((i for i, r in enumerate(rows) if REP_COL in r), None)
    if hi is None:
        raise ValueError(f"no '{REP_COL}' column in the crosstab; first rows: {rows[:3]}")
    header = rows[hi]
    rep_i = header.index(REP_COL)
    owner_i = header.index(OWNER_COL) if OWNER_COL in header else None
    tier_i = next((i for i, h in enumerate(header) if "tier" in h.lower()), None)
    total_i = header.index(TOTAL_COL) if TOTAL_COL in header else None
    end = total_i if total_i is not None else len(header)
    # Day columns are the ones headed like a day ('Mon (11-09)'). The real
    # export (2026-11-16) also carries 'Rep Volume Bonus Tiers' and 'Reps that
    # need 1 more for next tier (copy)' between Rep and Monday — those are not days.
    day_idx = [i for i in range(rep_i + 1, end) if _DAY_HDR.match(header[i])]
    if not day_idx:
        day_idx = [i for i in range(rep_i + 1, end) if header[i]]
    days = [header[i] for i in day_idx]
    # The view has TWO measures, so the export repeats every rep on two rows:
    # 'Calculation1 (1)' (a 1.00 helper) and 'New Fiber Internet Count (Rep tier
    # bonus eligible)'. Reading both posted every rep twice, the helper as
    # "at 1" (Raf's post, 2026-11-16). Keep only the sales-count row.
    meas_i = _measure_col(header, rows[hi + 1:], rep_i, day_idx)

    out: Dict[str, List[Rep]] = {}
    owner = tier = ""
    for r in rows[hi + 1:]:
        r = list(r) + [""] * (len(header) - len(r))
        if owner_i is not None and r[owner_i]:
            owner = r[owner_i]
        if tier_i is not None and r[tier_i]:
            tier = r[tier_i]
        name = r[rep_i]
        if not name or name in ("Total", TOTAL_COL) or owner in ("Total", TOTAL_COL):
            continue
        if meas_i is not None and not _is_sales_measure(r[meas_i]):
            continue
        cells = [r[i] for i in day_idx]
        total = _int(r[total_i]) if total_i is not None else sum(_int(c) for c in cells)
        out.setdefault(owner or "(owner)", []).append(Rep(name, cells, total, tier))
    if not out:
        raise ValueError("no rep rows in the crosstab")
    return days, out


_CAPTION = re.compile(r"tier\s*(\d+)\s*\(\s*(\d+)\s*(?:-\s*(\d+)|\+)", re.I)


def tiers_from_captions(reps: Dict[str, List[Rep]]) -> List[Tuple[int, int, Optional[int]]]:
    """Read the ladder off Tableau's own captions ('TIER 2 (5-7_New_Fiber)',
    'TIER 4 (11+_New_Fiber)'). Falls back to DEFAULT_TIERS unless every tier
    1..N is found with no gaps."""
    found: Dict[int, Tuple[int, Optional[int]]] = {}
    for lst in reps.values():
        for rp in lst:
            m = _CAPTION.search(rp.tier_caption or "")
            if m:
                found[int(m.group(1))] = (int(m.group(2)),
                                          int(m.group(3)) if m.group(3) else None)
    nums = sorted(found)
    if not nums or nums != list(range(1, len(nums) + 1)) or len(nums) < len(DEFAULT_TIERS):
        return list(DEFAULT_TIERS)
    return [(n, found[n][0], found[n][1]) for n in nums]


def tier_of(total: int, tiers) -> int:
    t = tiers[0][0]
    for n, lo, _hi in tiers:
        if total >= lo:
            t = n
    return t


def away(total: int, tiers) -> Optional[Tuple[int, int]]:
    """(sales needed, next tier) or None at the top tier."""
    for n, lo, _hi in tiers:
        if lo > total:
            return lo - total, n
    return None


# ----------------------------------------------------------------- offices ---

class Dest(NamedTuple):
    key: str
    owner: str
    channel_id: str
    channel_name: str


def fiber_eco_offices(only: Optional[List[str]] = None, log=print) -> List[Dest]:
    """Active Lucy Eco offices on the AT&T (Fiber) campaign -> where to post."""
    from automations.icd_alerts import offices as eco
    from automations.office_metrics import offices as met
    out: List[Dest] = []
    for o in sorted(eco.active(), key=lambda o: o.key):
        if (o.campaign or "att").lower() != "att":
            continue
        if only and o.key not in only:
            continue
        m = met.OFFICES.get(o.key)
        if m is not None and not m.nds and not m.emails_only:
            if getattr(m, "slack_token_file", ""):
                log(f"  skip {o.key}: its channel is in another Slack workspace")
                continue
            out.append(Dest(o.key, o.owner, m.channel_id, m.channel_name))
        elif o.channels:
            ch = o.channels[0]
            cid = ch.id if hasattr(ch, "id") else str(ch)
            name = ch.name if hasattr(ch, "name") else cid
            out.append(Dest(o.key, o.owner, cid, name))
        else:
            log(f"  skip {o.key} ({o.owner}): no metrics or Eco channel on file")
    return out


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z ]+", " ", s).split())


def same_owner(a: str, b: str, aliases: Optional[dict] = None) -> bool:
    fa, fb = _fold(a), _fold(b)
    if fa == fb:
        return True
    for canon, alts in (aliases or {}).items():
        names = {_fold(canon)} | {_fold(x) for x in (alts or [])}
        if fa in names and fb in names:
            return True
    return False


def _load_aliases() -> dict:
    try:
        from automations.focus_office_att.aliases import load_aliases
        return load_aliases() or {}
    except Exception as e:  # noqa: BLE001 — exact names still match
        print(f"  aliases unavailable ({type(e).__name__}); exact names only", flush=True)
        return {}


# -------------------------------------------------------------------- tags ---

def channel_people(client, channel_id: str) -> List[Dict]:
    """[{id, names:[folded names]}] for the human members of one channel."""
    ids, cursor = [], None
    while True:
        r = client.conversations_members(channel=channel_id, limit=200, cursor=cursor)
        ids.extend(r.get("members", []))
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    people = []
    for uid in ids:
        try:
            u = client.users_info(user=uid).get("user") or {}
        except Exception:  # noqa: BLE001 — one unreadable member is not fatal
            continue
        if u.get("deleted") or u.get("is_bot") or uid == "USLACKBOT":
            continue
        p = u.get("profile") or {}
        names = {_fold(x) for x in (u.get("real_name"), p.get("real_name"),
                                    p.get("display_name"), u.get("name")) if x}
        people.append({"id": uid, "names": [n for n in names if n]})
    return people


def match_rep(rep: str, people: List[Dict]) -> str:
    """Slack id when exactly one member carries the rep's first AND last name."""
    toks = _fold(rep).split()
    if len(toks) < 2:
        return ""
    first, last = toks[0], toks[-1]
    hits = [p["id"] for p in people
            if any(first in n.split() and last in n.split() for n in p["names"])]
    return hits[0] if len(set(hits)) == 1 else ""


# ------------------------------------------------------------------- board ---

TIER_BG = {1: "#D9D9D9", 2: "#9FC5E8", 3: "#93C47D", 4: "#F1C232"}
NEAR_BG = "#FFFF00"        # 1 sale away — same yellow as the Tableau view


def _range(lo: int, hi: Optional[int]) -> str:
    return f"{lo}+" if hi is None else f"{lo}-{hi}"


_CSS = """<style>
 body{margin:0;font-family:'Helvetica Neue',Arial,sans-serif}
 .board{display:inline-block;padding:14px;background:#fff}
 .title{background:#0B3D91;color:#fff;text-align:center;font-weight:700;font-size:20px;padding:10px 18px}
 .sub{color:#555;text-align:center;font-weight:700;font-size:13px;padding:8px 0}
 table{border-collapse:collapse;font-size:14px}
 th{background:#222;color:#fff;padding:6px 10px;border:1px solid #999}
 td{padding:5px 10px;border:1px solid #bbb;text-align:center}
 td.rep{text-align:left;font-weight:600;white-space:nowrap}
 td.tier{font-weight:800;writing-mode:horizontal-tb;white-space:nowrap}
 td.tot{font-weight:800}
 td.away{font-weight:700;white-space:nowrap}
 .legend{font-size:12px;color:#333;padding-top:8px;text-align:center}
</style>"""


# A tier with more reps than this is split evenly across images (Eve 2026-11-16:
# Raf's Tier 1 ran past 20 and the single image was too long to read in Slack).
MAX_PER_IMAGE = 20


def pages(reps: List[Rep], tiers) -> List[List[Rep]]:
    """Reps -> one list per image, top tier first.

    Tiers of MAX_PER_IMAGE or fewer stay whole, and consecutive ones share an
    image. A bigger tier gets images of its own, split EVENLY (34 -> 17 + 17,
    not 20 + 14), best sellers first."""
    by_tier: Dict[int, List[Rep]] = {}
    for rp in reps:
        by_tier.setdefault(tier_of(rp.total, tiers), []).append(rp)
    out: List[List[Rep]] = []
    small: List[Rep] = []
    for n, _lo, _hi in sorted(tiers, key=lambda t: -t[0]):
        group = sorted(by_tier.get(n, []), key=lambda r: (-r.total, r.name.lower()))
        if len(group) <= MAX_PER_IMAGE:
            small.extend(group)
            continue
        if small:
            out.append(small)
            small = []
        k = -(-len(group) // MAX_PER_IMAGE)          # images this tier needs
        size = -(-len(group) // k)                   # even split, rounded up
        out.extend(group[i:i + size] for i in range(0, len(group), size))
    if small:
        out.append(small)
    return out or [[]]


def build_html(owner: str, week: str, days: List[str], reps: List[Rep], tiers,
               part: str = "") -> str:
    e = html.escape
    rows = []
    by_tier: Dict[int, List[Rep]] = {}
    for rp in reps:
        by_tier.setdefault(tier_of(rp.total, tiers), []).append(rp)
    for n, lo, hi in sorted(tiers, key=lambda t: -t[0]):
        group = sorted(by_tier.get(n, []), key=lambda r: (-r.total, r.name.lower()))
        for j, rp in enumerate(group):
            gap = away(rp.total, tiers)
            near = gap is not None and gap[0] == 1
            bg = f' style="background:{NEAR_BG}"' if near else ""
            tier_cell = (f'<td class="tier" rowspan="{len(group)}" style="background:{TIER_BG.get(n, "#eee")}">'
                         f'TIER {n}<br><span style="font-weight:400;font-size:12px">'
                         f'{_range(lo, hi)} sales</span></td>') if j == 0 else ""
            away_txt = "TOP TIER" if gap is None else f"{gap[0]} to Tier {gap[1]}"
            cells = "".join(f"<td{bg}>{e(c)}</td>" for c in rp.days)
            rows.append(f"<tr>{tier_cell}<td class='rep'{bg}>{e(rp.name)}</td>{cells}"
                        f"<td class='tot'{bg}>{rp.total}</td>"
                        f"<td class='away'{bg}>{away_txt}</td></tr>")
    head = "".join(f"<th>{e(d)}</th>" for d in days)
    ladder = " · ".join(f"Tier {n}: {_range(lo, hi)}" for n, lo, hi in tiers)
    return (f"<html><head><meta charset='utf-8'>{_CSS}</head><body><div class='board'>"
            f"<div class='title'>TIER BONUS BREAKDOWN — NEW FIBER INTERNET</div>"
            f"<div class='sub'>{e(owner)} · {e(week)}{' · ' + e(part) if part else ''}</div>"
            f"<table><tr><th>Tier</th><th>Rep</th>{head}<th>Total</th><th>Away</th></tr>"
            f"{''.join(rows)}</table>"
            f"<div class='legend'>{e(ladder)} new Fiber sales (Mon-Sun) · "
            f"<span style='background:{NEAR_BG}'>&nbsp;yellow&nbsp;</span> = 1 sale from the next tier</div>"
            f"</div></body></html>")


def away_lines(reps: List[Rep], tiers) -> List[str]:
    """One line per GROUP, not per rep, names only — NO tags (Eve + Raf
    2026-11-16: the per-rep tagged list was ~100 lines; "they can just look at
    the post"). Reps the same number of sales from the same tier share a line;
    top tier first, then closest to the next tier."""
    def who(name: str) -> str:
        return name
    top: List[Rep] = []
    groups: Dict[Tuple[int, int], List[Rep]] = {}
    for rp in reps:
        gap = away(rp.total, tiers)
        if gap is None:
            top.append(rp)
        else:
            groups.setdefault(gap, []).append(rp)
    out: List[str] = []
    if top:
        top.sort(key=lambda r: (-r.total, r.name.lower()))
        out.append("🔥 *Top tier — locked in:* "
                   + ", ".join(f"{who(r.name)} ({r.total})" for r in top))
    # closest first; same gap -> the higher tier first
    for (n, nxt) in sorted(groups, key=lambda g: (g[0], -g[1])):
        members = sorted(groups[(n, nxt)], key=lambda r: r.name.lower())
        s = "sale" if n == 1 else "sales"
        out.append(f"{'⚡ ' if n == 1 else ''}*{n} {s} from Tier {nxt}:* "
                   + ", ".join(who(r.name) for r in members))
    return out


_MD = re.compile(r"\((\d{1,2})-(\d{1,2})\)")


def monday_in_headers(days: List[str], near: dt.date) -> Optional[dt.date]:
    """The Monday the export's day columns start on ('Mon (11-02)'), with the
    year taken from the date closest to `near`. None if no column has a date."""
    for h in days:
        m = _MD.search(h)
        if not m:
            continue
        mo, d = int(m.group(1)), int(m.group(2))
        cands = []
        for y in (near.year - 1, near.year, near.year + 1):
            try:
                cands.append(dt.date(y, mo, d))
            except ValueError:
                pass
        if not cands:
            continue
        first = min(cands, key=lambda c: abs((c - near).days))
        return first - dt.timedelta(days=first.weekday())
    return None


def week_label(today: dt.date) -> str:
    mon = today - dt.timedelta(days=today.weekday())
    sun = mon + dt.timedelta(days=6)
    return f"Week of {mon.strftime('%b')} {mon.day} - {sun.strftime('%b')} {sun.day}"


# --------------------------------------------------------------------- run ---

def pull(day: dt.date, csv_path: Optional[str], last_week: bool = False) -> Path:
    if csv_path:
        return Path(csv_path)
    from automations.shared.tableau_patchright import (
        tableau_session, download_crosstab_patchright)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUT_DIR / f"tier_bonus_{day.isoformat()}{'_lw' if last_week else ''}.csv"
    url = view_url(last_week)
    with tableau_session(verbose=True) as page:
        sheets = [WORKSHEET] if WORKSHEET else []
        if not sheets:
            from automations.recruiting_report.opt_phase import list_crosstab_sheets
            sheets = list_crosstab_sheets(url, page=page, verbose=True)
            print(f"  crosstab sheets: {sheets}", flush=True)
        last = None
        for sh in sheets:
            try:
                p = download_crosstab_patchright(url, sh, dst, verbose=False, page=page)
                parse(read_csv(p))
                print(f"  using sheet {sh!r}", flush=True)
                return p
            except Exception as e:  # noqa: BLE001 — try the next sheet
                last = e
                print(f"  sheet {sh!r}: {type(e).__name__}: {str(e)[:160]}", flush=True)
    raise RuntimeError(f"no crosstab sheet had rep rows ({last})")


def run(args) -> int:
    day = (dt.date.fromisoformat(args.date) if args.date
           else dt.datetime.now(TZ).date())
    if day.weekday() == 0 and not (args.date or args.csv or args.last_week):
        print("Monday: 'This Week' just restarted — nothing to post.", flush=True)
        return 0
    mode = "LIVE" if args.live else ("TEST -> " + args.post_to if args.post_to else "dry run")
    print(f"{TITLE} — {day} — {mode}", flush=True)

    dests = fiber_eco_offices(args.office or None)
    print(f"  {len(dests)} Fiber Eco office(s): {[d.key for d in dests]}", flush=True)
    days, data = parse(read_csv(pull(day, args.csv, args.last_week)))
    tiers = tiers_from_captions(data)
    print(f"  {len(data)} owner(s) in the view · days {days} · tiers {tiers}", flush=True)
    aliases = _load_aliases()
    # The label comes from the export's own day columns, never from the
    # calendar. On 2026-11-16 'Last Week' came back as Nov 2-8 and was posted
    # to Raf titled 'Nov 9 - Nov 15'. A week other than the one asked for is
    # refused — a wrong week tagged to every rep is worse than no post.
    want = day - dt.timedelta(days=day.weekday() + (7 if args.last_week else 0))
    got = monday_in_headers(days, day)
    if got is None:
        print("  could not read dates off the day columns — posting nothing", flush=True)
        return 1
    week = week_label(got)
    if got != want and not args.csv:
        print(f"  WRONG WEEK: export is {week}, expected {week_label(want)} — "
              "posting nothing", flush=True)
        return 1

    shared = {}
    for d in dests:
        shared[d.channel_id] = shared.get(d.channel_id, 0) + 1

    ok = True
    for d in dests:
        owner_key = next((k for k in data if same_owner(k, d.owner, aliases)), None)
        if owner_key is None:
            print(f"\n[{d.key}] {d.owner}: not in the view this week — no post "
                  "(new spelling? add it to ICD Aliases)", flush=True)
            continue
        reps = data[owner_key]
        slug = "_".join(_fold(d.owner).split())
        chunks = pages(reps, tiers)
        imgs = [render(build_html(d.owner, week, days, chunk, tiers,
                                  part=(f"image {i} of {len(chunks)}" if len(chunks) > 1 else "")),
                       OUT_DIR / f"tier_bonus_{slug}_{day.isoformat()}_{i}.png")
                for i, chunk in enumerate(chunks, 1)]
        lines = away_lines(reps, tiers)
        title = TITLE + (f" — {d.owner}" if shared[d.channel_id] > 1 else "")
        text = "\n".join([f"*Sales away from the next tier bonus* ({week})", ""] + lines)
        print(f"\n[{d.key}] {d.owner} -> {d.channel_name}: {len(reps)} rep(s); "
              f"{len(imgs)} image(s) "
              f"{[len(c) for c in chunks]} reps each: {[str(i) for i in imgs]}", flush=True)
        print("   " + text.replace("\n", "\n   "), flush=True)
        if not (args.live or args.post_to):
            continue
        ok = post(d, title, day, imgs, text, post_to=args.post_to, week=week) and ok
    if not (args.live or args.post_to):
        print("\n(dry run) rendered only — nothing posted.", flush=True)
    return 0 if ok else 1


def render(page_html: str, out: Path) -> Path:
    from automations.nds_activation_rate.slack_board import render_png
    return render_png(page_html, out)


def post(d: Dest, title: str, day: dt.date, imgs: List[Path], text: str, *,
         post_to: str = "", week: str = "") -> bool:
    """Parent post, then every image in order, then the tagged list -- all in
    the thread. A TEST (--post-to) builds the same thread in that DM, so the
    sample looks like the real thing."""
    from automations.shared import slack_metrics_post as smp
    week = week or week_label(day)
    if post_to:
        c = smp._client()
        ch = smp._postable_channel(c, post_to)
        parent = c.chat_postMessage(
            channel=ch, text=f"*{title} — {d.owner}* (TEST, {week})")
        ts, chan, react, mirror = parent.get("ts"), ch, None, False
    else:
        th = smp.ensure_named_thread(title, day, channel_id=d.channel_id)
        ts, chan, react, mirror = th.get("thread_ts"), d.channel_id, EMOJI, True
    if not ts:
        print(f"   FAILED to open the thread in {post_to or d.channel_name}", flush=True)
        return False
    good = True
    for i, img in enumerate(imgs, 1):
        part = f" ({i}/{len(imgs)})" if len(imgs) > 1 else ""
        r = smp.post_reply_with_image(img, comment=f"{title} — {week}{part}",
                                      thread_ts=ts, channel_id=chan, wait_visible=True,
                                      mirror=mirror,
                                      react_emoji=react if i == len(imgs) else None)
        good = good and bool(r.get("ok"))
    if post_to:
        r2 = smp._client().chat_postMessage(channel=chan, thread_ts=ts, text=text)
    else:
        r2 = smp.post_reply_text_only(text, thread_ts=ts, channel_id=chan, today=day)
    good = good and bool(r2.get("ok"))
    print(f"   {post_to or d.channel_name}: {'Posted' if good else 'FAILED'}", flush=True)
    return good


def main(argv=None) -> int:
    # A Windows console (cp1252) dies on the 🏆 in the first print — the same
    # crash that took down the OPT phase. Replace, never raise.
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — not a reconfigurable stream
            pass
    ap = argparse.ArgumentParser(prog="fiber_tier_bonus.run", description=TITLE)
    ap.add_argument("--office", action="append", default=[],
                    help="only this Eco office key (repeatable), e.g. --office raf")
    ap.add_argument("--csv", default=None, help="parse this crosstab instead of pulling")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default today, CT)")
    ap.add_argument("--last-week", action="store_true",
                    help="the view's 'Last Week' (Mon-Sun just closed) instead of This Week")
    ap.add_argument("--no-tags", action="store_true", help="skip the Slack member lookup")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="(default) render + print, post nothing")
    g.add_argument("--post-to", default="", help="TEST: post top-level here, names without @")
    g.add_argument("--live", action="store_true", help="post the threads, with tags")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
