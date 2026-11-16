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
  → 1) the board image, 2) one line per rep, tagged: "you're X away from Tier N".

TAGS
  A rep is tagged only when exactly ONE member of that channel matches their
  first AND last name. Anything else (no match, two matches) prints the name
  without the @ — a wrong tag is worse than no tag.

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
    day_idx = [i for i in range(rep_i + 1, end) if header[i]]
    days = [header[i] for i in day_idx]

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


def build_html(owner: str, week: str, days: List[str], reps: List[Rep], tiers) -> str:
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
            f"<div class='sub'>{e(owner)} · {e(week)}</div>"
            f"<table><tr><th>Tier</th><th>Rep</th>{head}<th>Total</th><th>Away</th></tr>"
            f"{''.join(rows)}</table>"
            f"<div class='legend'>{e(ladder)} new Fiber sales (Mon-Sun) · "
            f"<span style='background:{NEAR_BG}'>&nbsp;yellow&nbsp;</span> = 1 sale from the next tier</div>"
            f"</div></body></html>")


def away_lines(reps: List[Rep], tiers, ids: Dict[str, str], *, tag: bool) -> List[str]:
    """One line per rep, closest to the next tier first; top tier last."""
    def who(name: str) -> str:
        uid = ids.get(name, "")
        return f"<@{uid}>" if (tag and uid) else f"*{name}*"
    climbing, top = [], []
    for rp in reps:
        gap = away(rp.total, tiers)
        if gap is None:
            top.append(f"🔥 {who(rp.name)} — Tier {tier_of(rp.total, tiers)} locked in ({rp.total} sales). Top tier!")
        else:
            n, nxt = gap
            s = "sale" if n == 1 else "sales"
            climbing.append((n, rp.name.lower(),
                             f"{'⚡ ' if n == 1 else ''}{who(rp.name)} — you're *{n} {s} away* "
                             f"from Tier {nxt} (at {rp.total})"))
    return top + [t for _, _, t in sorted(climbing)]


def week_label(today: dt.date) -> str:
    mon = today - dt.timedelta(days=today.weekday())
    sun = mon + dt.timedelta(days=6)
    return f"Week of {mon.strftime('%b')} {mon.day} - {sun.strftime('%b')} {sun.day}"


# --------------------------------------------------------------------- run ---

def pull(day: dt.date, csv_path: Optional[str]) -> Path:
    if csv_path:
        return Path(csv_path)
    from automations.shared.tableau_patchright import (
        tableau_session, download_crosstab_patchright)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUT_DIR / f"tier_bonus_{day.isoformat()}.csv"
    with tableau_session(verbose=True) as page:
        sheets = [WORKSHEET] if WORKSHEET else []
        if not sheets:
            from automations.recruiting_report.opt_phase import list_crosstab_sheets
            sheets = list_crosstab_sheets(VIEW_URL, page=page, verbose=True)
            print(f"  crosstab sheets: {sheets}", flush=True)
        last = None
        for sh in sheets:
            try:
                p = download_crosstab_patchright(VIEW_URL, sh, dst, verbose=False, page=page)
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
    if day.weekday() == 0 and not args.date and not args.csv:
        print("Monday: 'This Week' just restarted — nothing to post.", flush=True)
        return 0
    mode = "LIVE" if args.live else ("TEST -> " + args.post_to if args.post_to else "dry run")
    print(f"{TITLE} — {day} — {mode}", flush=True)

    dests = fiber_eco_offices(args.office or None)
    print(f"  {len(dests)} Fiber Eco office(s): {[d.key for d in dests]}", flush=True)
    days, data = parse(read_csv(pull(day, args.csv)))
    tiers = tiers_from_captions(data)
    print(f"  {len(data)} owner(s) in the view · days {days} · tiers {tiers}", flush=True)
    aliases = _load_aliases()
    week = week_label(day)

    client = None
    if not args.no_tags:
        try:
            from automations.shared import slack_metrics_post as smp
            client = smp._client()
        except Exception as e:  # noqa: BLE001 — no tags, still a board
            print(f"  Slack client unavailable ({e}); names without @", flush=True)

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
        ids: Dict[str, str] = {}
        if client is not None:
            try:
                people = channel_people(client, d.channel_id)
                ids = {r.name: match_rep(r.name, people) for r in reps}
            except Exception as e:  # noqa: BLE001
                print(f"  [{d.key}] could not read {d.channel_name} members ({e})", flush=True)
        tagged = sum(1 for v in ids.values() if v)
        slug = "_".join(_fold(d.owner).split())
        img = render(build_html(d.owner, week, days, reps, tiers),
                     OUT_DIR / f"tier_bonus_{slug}_{day.isoformat()}.png")
        lines = away_lines(reps, tiers, ids, tag=bool(args.live))
        title = TITLE + (f" — {d.owner}" if shared[d.channel_id] > 1 else "")
        text = "\n".join([f"*Sales away from the next tier bonus* ({week})", ""] + lines)
        print(f"\n[{d.key}] {d.owner} -> {d.channel_name}: {len(reps)} rep(s), "
              f"{tagged} matched in Slack; image {img}", flush=True)
        for r in reps:
            if not ids.get(r.name):
                print(f"     no @ for {r.name!r}", flush=True)
        print("   " + text.replace("\n", "\n   "), flush=True)
        if not (args.live or args.post_to):
            continue
        ok = post(d, title, day, img, text, post_to=args.post_to) and ok
    if not (args.live or args.post_to):
        print("\n(dry run) rendered only — nothing posted.", flush=True)
    return 0 if ok else 1


def render(page_html: str, out: Path) -> Path:
    from automations.nds_activation_rate.slack_board import render_png
    return render_png(page_html, out)


def post(d: Dest, title: str, day: dt.date, img: Path, text: str, *, post_to: str = "") -> bool:
    from automations.shared import slack_metrics_post as smp
    if post_to:
        r1 = smp.post_reply_with_image(img, comment=f"{title} — {d.owner} (TEST)",
                                       channel_id=post_to, top_level=True, mirror=False,
                                       wait_visible=True)
        r2 = smp._client().chat_postMessage(channel=post_to, text=text)
        good = bool(r1.get("ok")) and bool(r2.get("ok"))
        print(f"   TEST post: {'OK' if good else 'FAILED'}", flush=True)
        return good
    th = smp.ensure_named_thread(title, day, channel_id=d.channel_id)
    ts = th.get("thread_ts")
    if not ts:
        print(f"   FAILED to open the thread in {d.channel_name}: {th}", flush=True)
        return False
    r1 = smp.post_reply_with_image(img, comment=f"{title} — {week_label(day)}",
                                   thread_ts=ts, channel_id=d.channel_id,
                                   wait_visible=True, react_emoji=EMOJI)
    r2 = smp.post_reply_text_only(text, thread_ts=ts, channel_id=d.channel_id, today=day)
    good = bool(r1.get("ok")) and bool(r2.get("ok"))
    print(f"   {d.channel_name}: {'Posted' if good else 'FAILED ' + str((r1, r2))[:300]}", flush=True)
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
    ap.add_argument("--no-tags", action="store_true", help="skip the Slack member lookup")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="(default) render + print, post nothing")
    g.add_argument("--post-to", default="", help="TEST: post top-level here, names without @")
    g.add_argument("--live", action="store_true", help="post the threads, with tags")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
