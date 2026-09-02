"""Vantura B2B Revenue Board — daily image into the Vantura Production thread.

Carlos 2026-08-30: "Since you know how many sales they did for that week, you
should know what tier they're at and throw that into the total revenue ...
almost like a sales board — Monday, Tuesday, Wednesday, you update how much
revenue they did for that day, and on the far right the total they've
generated for the week. Monday through Sunday, sent in the Alphalete B2B
Slack, in the Vantura production thread that you send out at 5-ish."

What it does, every morning after the order-log data is fresh:
  1. Pulls the FULL 47-column ORDERLOG export for Monday-of-yesterday ->
     yesterday (captainship_boards.pull_orderlog — Carlos's Tableau session
     over the shared CDP Chrome; MUST RUN ON LUCY 2). On a Monday that is the
     whole completed Mon-Sun week.
  2. Prices every line on the office comp sheet eff 2026-08-24 with the
     add-ons (Auto Bill Pay, Next Up, Premium/Extra, internet/AIR ABP,
     baseline churn) — vantura_payout_estimate.price is the one pricer.
  3. Computes each rep's weekly Tiered Volume tier from their eligible count
     (ports/BYOD/new/AIR/internet; VoIP counts revenue but not tier) and adds
     the bonus (tier rate x payable units, IRU Air excluded) to the WEEK
     TOTAL column.
  4. Renders one board image — Rep | Mon..Sun | Tier | Week Total — and
     replies with it in the day's 'Vantura Production M/D/YYYY' thread in
     #a-players-b2b (A-Players ONLY to start — Carlos 2026-08-30).

TWO BOARDS, TWO CLOCKS. The agent runs 05:20 / 05:50 / 06:30 for the AT&T
board (it pulls its own export, so it only waits on the 05:10 thread) and
07:25 / 08:50 / 09:40 for the BOX board, which reads whatever csv
box_order_log left on disk at 7:00 / 8:30. Before 7:00 the BOX half is
SKIPPED, not held: the newest csv is yesterday's pull and can never carry the
target day, so holding there just published a `partial` run every morning.

HOLDS (exit 75, the LaunchAgent ladder retries): export has no rows for the
target day yet, the BOX csv has not reached the day yet (until 9:35, after
which an empty day is a real zero — and on a MONDAY the day it must reach is
SATURDAY, because BOX sells to businesses and they are shut on Sunday), or
the Vantura Production thread hasn't been posted yet. Not included anywhere:
MCOE, road trip (not in the log).

  python -m automations.vantura_revenue_board.run                # dry: render only
  python -m automations.vantura_revenue_board.run --post         # post to thread
  python -m automations.vantura_revenue_board.run --date 2026-08-29 \
      --csv output/captainship_boards/orderlog_2026-08-24_2026-08-30.csv
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import sys
import time
from pathlib import Path

from automations.vantura_payout_estimate.run import (
    _n, board_b2b_reps, norm_name, price,
)

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "vantura_revenue_board"
# A-PLAYERS ONLY to start (Carlos 2026-08-30: "It shouldn't go on the GP
# sales. I want it on the A players' Slack to start.") — the thread exists
# in both channels; we reply to the one in #a-players-b2b.
CHANNEL = ("#a-players-b2b", "C0AJQA8P716")
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

TIERS = ((12, "T5", 85), (9, "T4", 65), (7, "T3", 45), (5, "T2", 30),
         (4, "T1", 20), (0, "—", 0))

# BOX — New Compensation (B2B Vantura doc, 'Box Pay' tab, 2026-08-30).
# Payout per Electric sale = Base + Term + kWh + Volume bonus; Ancillary =
# Base + Term only. NO churn impact for now (Carlos 2026-08-30: "there is no
# churn tier impact at the moment").
BOX_BASE_ELECTRIC = {1: 300, 2: 275, 3: 210, 4: 190}
BOX_BASE_ANCILLARY = {1: 150, 2: 100, 3: 75, 4: 50}
BOX_KWH_BONUS = ((100_000, 450), (75_000, 400), (50_000, 350), (45_000, 300),
                 (40_000, 250), (35_000, 200), (30_000, 150), (25_000, 125),
                 (20_000, 100))
BOX_TIERS = ((13, "T4", 200), (10, "T3", 150), (7, "T2", 100), (4, "T1", 75),
             (0, "—", 0))


def box_tier_for(count: int):
    for floor, name, rate in BOX_TIERS:
        if count >= floor:
            return name, rate
    return "—", 0


def newest_box_csv():
    d = Path(__file__).resolve().parents[2] / "output"
    c = sorted(d.glob("box_order_log_*.csv"))
    return c[-1] if c else None


def board_box_reps():
    from automations.recruiting_report.fill import open_by_key
    from automations.vantura_payout_estimate.run import BOARD_ID
    g = open_by_key(BOARD_ID).worksheet("Sales Board").get_all_values()
    reps = set()
    for r in g[4:]:
        name = (r[1] if len(r) > 1 else "").strip()
        if name.startswith("AT&T"):
            break
        if name and (r[11] if len(r) > 11 else "").strip() == "BOX":
            reps.add(norm_name(name))
    return reps


def price_box(sale):
    """(amount, notes) per the BOX — New Compensation grid. Electric =
    10k+ kWh (no start-date column in the export, so 'starting within 24
    months' can't be checked — volume is the gate we have)."""
    f = sale.fields
    try:
        vol = float((f.get("Sales (All) kWH+Therms") or "0").replace(",", ""))
    except ValueError:
        vol = 0.0
    import re as _re
    m = _re.search(r"(\d)", f.get("BF Tier") or "")
    bf = int(m.group(1)) if m else 4
    bf = bf if bf in (1, 2, 3, 4) else 4
    electric = vol >= 10_000
    amt = (BOX_BASE_ELECTRIC if electric else BOX_BASE_ANCILLARY)[bf]
    notes = [f"BF{bf}", "elec" if electric else "anc"]
    m = _re.search(r"(\d+)", f.get("Term") or "")
    months = int(m.group(1)) if m else 0
    if months >= 36:
        amt += 200 if electric else 100
        notes.append("term36")
    elif months >= 24:
        amt += 50 if electric else 25
        notes.append("term24")
    if electric:
        for floor, b in BOX_KWH_BONUS:
            if vol >= floor:
                amt += b
                notes.append(f"kwh+{b}")
                break
    return amt, ",".join(notes)


# The OLD scale, for comparison only (Carlos 2026-08-30: "what would the
# payout have been for Box this week if they had used this payout scale?" —
# the TX Grid on the same Box Pay tab). 40k+ kWh: base 375/310/275/240,
# term 24mo +100 / 36+ +150; below 40k: base 325/275/210/190, term +50/+100;
# kWh bonus 40-45k 25 / 45-50k 50 / 50-55k 80 / 55-60k 120 / 60-80k 180 /
# 80-100k 250 / 100k+ 350; volume bonus 4-6 $100 / 7-9 $130 / 10-12 $165 /
# 13+ $210 per activation.
TX_BASE_40K = {1: 375, 2: 310, 3: 275, 4: 240}
TX_BASE_LOW = {1: 325, 2: 275, 3: 210, 4: 190}
TX_KWH = ((100_000, 350), (80_000, 250), (60_000, 180), (55_000, 120),
          (50_000, 80), (45_000, 50), (40_000, 25))
TX_TIERS = ((13, 210), (10, 165), (7, 130), (4, 100), (0, 0))


def price_box_tx(sale):
    import re as _re
    f = sale.fields
    try:
        vol = float((f.get("Sales (All) kWH+Therms") or "0").replace(",", ""))
    except ValueError:
        vol = 0.0
    m = _re.search(r"(\d)", f.get("BF Tier") or "")
    bf = int(m.group(1)) if m else 4
    bf = bf if bf in (1, 2, 3, 4) else 4
    big = vol >= 40_000
    amt = (TX_BASE_40K if big else TX_BASE_LOW)[bf]
    m = _re.search(r"(\d+)", f.get("Term") or "")
    months = int(m.group(1)) if m else 0
    if months >= 36:
        amt += 150 if big else 100
    elif months >= 24:
        amt += 100 if big else 50
    for floor, b in TX_KWH:
        if vol >= floor:
            amt += b
            break
    return amt


def box_scale_compare(csv_path: Path, monday: dt.date, upto: dt.date):
    """Both scales side by side, per rep — written to the Mini Control
    workbook tab 'Box Scale Compare'."""
    from automations.box_order_log import clean as bclean
    reps_ok = board_box_reps()
    agg = collections.defaultdict(lambda: {"n": 0, "tx": 0.0, "new": 0.0})
    sales, _ = bclean.load(csv_path)
    for s in sales:
        rep = _n(s.fields.get("Rep Name"))
        if not rep or norm_name(rep) not in reps_ok:
            continue
        if not s.sale_date or not (monday <= s.sale_date <= upto):
            continue
        if s.level in bclean.DEAD_LEVELS or not bclean._reached_tpv(s):
            continue
        a = agg[rep.title()]
        a["n"] += 1
        a["tx"] += price_box_tx(s)
        new_amt, _notes = price_box(s)
        a["new"] += new_amt
    lines = [["BOX — TX Grid vs New Compensation",
              f"week {monday} .. {upto}", str(csv_path.name)],
             ["REP", "SALES", "TX GRID (incl vol bonus)",
              "NEW COMP (incl vol bonus)", "DIFF new-tx"]]
    t_tx = t_new = 0.0
    for rep, a in sorted(agg.items(), key=lambda kv: -kv[1]["new"]):
        _tn, tx_rate = next(((n, r) for f, r in TX_TIERS
                             for n in [""] if a["n"] >= f), ("", 0))
        tx_rate = next(r for f, r in TX_TIERS if a["n"] >= f)
        _nm, new_rate = box_tier_for(a["n"])
        tx = a["tx"] + tx_rate * a["n"]
        new = a["new"] + new_rate * a["n"]
        t_tx += tx
        t_new += new
        lines.append([rep, a["n"], round(tx, 2), round(new, 2),
                      round(new - tx, 2)])
    lines.append(["OFFICE TOTAL", sum(a["n"] for a in agg.values()),
                  round(t_tx, 2), round(t_new, 2), round(t_new - t_tx, 2)])
    for row in lines:
        print("  " + "  |  ".join(str(c) for c in row))
    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.vantura_payout_estimate.run import CONTROL_ID
    sh = open_by_key(CONTROL_ID)
    try:
        ws = sh.worksheet("Box Scale Compare")
        ws.clear()
    except Exception:  # noqa: BLE001
        ws = sh.add_worksheet(title="Box Scale Compare", rows=40, cols=6)
    _retry(ws.update, values=lines, range_name="A1")
    print("written to 'Box Scale Compare' on the Mini Control workbook")


def load_box_priced(csv_path: Path, monday: dt.date, upto: dt.date):
    """-> per-rep {'days': {date: $}, 'elig': n, 'payable': n} for BOX. The
    count gate is the order-log one: reached TPV (or exempt) and not dead."""
    from automations.box_order_log import clean as bclean
    reps_ok = board_box_reps()
    out = collections.defaultdict(lambda: {"days": collections.defaultdict(float),
                                           "elig": 0.0, "payable": 0.0})
    sales, _stats = bclean.load(csv_path)
    for s in sales:
        rep = _n(s.fields.get("Rep Name"))
        if not rep or norm_name(rep) not in reps_ok:
            continue
        if not s.sale_date or not (monday <= s.sale_date <= upto):
            continue
        if s.level in bclean.DEAD_LEVELS or not bclean._reached_tpv(s):
            continue
        amt, _notes = price_box(s)
        rec = out[rep.title()]
        rec["days"][s.sale_date] += amt
        rec["elig"] += 1
        rec["payable"] += 1
    return out


def tier_for(count: int):
    for floor, name, rate in TIERS:
        if count >= floor:
            return name, rate
    return "—", 0


def week_of(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def load_priced(csv_path: Path, monday: dt.date, upto: dt.date):
    """-> per-rep {'days': {date: $}, 'elig': n, 'payable': n}, unpriced."""
    from automations.att_order_log import clean
    reps_ok = board_b2b_reps()
    out = collections.defaultdict(lambda: {"days": collections.defaultdict(float),
                                           "elig": 0.0, "payable": 0.0})
    unpriced = collections.Counter()
    for r in clean.load_rows(str(csv_path), owner_prefix=None):
        rep = _n(r.get("Rep"))
        if not rep or norm_name(rep) not in reps_ok:
            continue
        try:
            u = float(r.get("Unit Count") or 0)
        except (TypeError, ValueError):
            continue
        if not u:
            continue
        try:
            d = dt.datetime.strptime(_n(r.get("sp.Order Date (copy)")),
                                     "%m/%d/%Y").date()
        except ValueError:
            continue
        if not (monday <= d <= upto):
            continue
        amt, label, _notes = price(r)
        if amt is None:
            unpriced[label] += u
            continue
        rec = out[rep.title()]
        rec["days"][d] += amt * u
        prod = _n(r.get("Product Type (Broken Out)")).upper()
        cru = _n(r.get("CRU/IRU")).upper()
        if prod != "VOICE":
            rec["elig"] += u
            if not (prod == "AIR/AWB" and cru == "IRU"):
                rec["payable"] += u
    return out, unpriced


def build_rows(per_rep, monday: dt.date, upto: dt.date, tier_fn=tier_for):
    rows, office = [], {"days": collections.defaultdict(float), "bonus": 0.0}
    for rep, rec in per_rep.items():
        base = sum(rec["days"].values())
        tname, rate = tier_fn(int(rec["elig"]))
        bonus = rate * rec["payable"]
        row = {"rep": rep, "tier": tname, "total": base + bonus}
        for i, dcode in enumerate(DAYS):
            d = monday + dt.timedelta(days=i)
            v = rec["days"].get(d, 0.0)
            row[dcode] = v if d <= upto else None
            office["days"][dcode] += v
        office["bonus"] += bonus
        rows.append(row)
    rows.sort(key=lambda r: -r["total"])
    return rows, office


# ------------------------------------------------------------------ image --
def render(rows, office, monday: dt.date, upto: dt.date, dest: Path,
           board_name: str = "Vantura B2B Revenue") -> Path:
    from PIL import Image, ImageDraw
    from automations.box_order_log.png import _font

    S = 2
    pad, row_h, head_h, title_h = 12 * S, 22 * S, 24 * S, 30 * S
    f = _font(11 * S)
    fb = _font(11 * S, bold=True)
    ft = _font(14 * S, bold=True)

    # Week Total rides right after the name (Carlos, first preview).
    cols = ["Rep", "Week Total"] + list(DAYS) + ["Tier"]

    def cell(row, c):
        if c == "Rep":
            return row["rep"]
        if c == "Tier":
            return row["tier"]
        if c == "Week Total":
            return f"${row['total']:,.0f}"
        v = row.get(c)
        if v is None:
            return ""
        return f"${v:,.0f}" if v else "·"

    total_row = {"rep": "OFFICE", "tier": "",
                 "total": sum(r["total"] for r in rows)}
    for dcode in DAYS:
        vals = [r.get(dcode) for r in rows]
        total_row[dcode] = (sum(v or 0 for v in vals)
                            if any(v is not None for v in vals) else None)

    probe = Image.new("RGB", (10, 10))
    dr = ImageDraw.Draw(probe)
    widths = []
    for c in cols:
        w = dr.textlength(c, font=fb)
        for row in rows + [total_row]:
            w = max(w, dr.textlength(cell(row, c), font=fb))
        widths.append(int(w) + 14 * S)

    W = sum(widths) + pad * 2
    H = title_h + head_h + row_h * (len(rows) + 1) + pad * 3
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    title = (f"{board_name} — Week of {monday.month}/{monday.day}  "
             f"(through {upto.strftime('%a')} {upto.month}/{upto.day})")
    d.text((pad, pad), title, font=ft, fill=(20, 20, 20))

    y = pad + title_h
    x = pad
    for c, w in zip(cols, widths):
        d.rectangle([x, y, x + w, y + head_h], fill=(0, 87, 184))
        d.text((x + 7 * S, y + 5 * S), c, font=fb, fill=(255, 255, 255))
        x += w
    y += head_h
    for i, row in enumerate(rows + [total_row]):
        is_total = row["rep"] == "OFFICE"
        bg = ((217, 234, 211) if is_total
              else (243, 246, 251) if i % 2 else (255, 255, 255))
        d.rectangle([pad, y, W - pad, y + row_h], fill=bg)
        x = pad
        for c, w in zip(cols, widths):
            txt = cell(row, c)
            font = fb if (is_total or c in ("Rep", "Week Total")) else f
            tx = x + 7 * S if c == "Rep" else x + w - 7 * S - d.textlength(txt, font=font)
            d.text((tx, y + 4 * S), txt, font=font,
                   fill=(20, 20, 20) if txt != "·" else (170, 170, 170))
            x += w
        y += row_h

    dest.parent.mkdir(parents=True, exist_ok=True)
    img = img.resize((W // S, H // S), Image.LANCZOS)
    img.save(dest)
    return dest


# ------------------------------------------------------------------ slack --
def post(png: Path, plain: str, caption: str, kind: str,
         dm_user: str = "") -> int:
    """kind='b2b' -> the day's B2B Metrics thread (created if absent — the
    5:10 sales_boards pass normally already did); kind='box' -> the day's BOX
    Order Log thread (never created here; missing = hold 75). Both channels
    (#alphalete-gp-sales + #a-players-b2b), per the 2026-08-30 restructure —
    the standalone Vantura Production thread is retired."""
    from automations.sales_boards.run import (TARGETS, _already_replied,
                                              box_thread_ts,
                                              metrics_thread_ts)
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    today = dt.date.today()
    if dm_user:
        cid = client.conversations_open(users=dm_user)["channel"]["id"]
        client.files_upload_v2(channel=cid,
                               file_uploads=[{"file": str(png),
                                              "filename": f"{plain}.png"}],
                               initial_comment=caption)
        print(f"posted {plain!r} to DM {dm_user}")
        return 0
    held = False
    for name, cid, _wz in TARGETS:
        ts = (box_thread_ts(client, cid, today) if kind == "box"
              else metrics_thread_ts(client, cid, today))
        if ts is None:
            print(f"HOLD: no BOX Order Log thread in {name} yet "
                  "(box_order_log posts it at 7:00) — retrying later")
            held = True
            continue
        if _already_replied(client, cid, ts, plain):
            print(f"'{plain}' already in the {name} thread — nothing to do")
            continue
        client.files_upload_v2(channel=cid, thread_ts=ts,
                               file_uploads=[{"file": str(png),
                                              "filename": f"{plain}.png"}],
                               initial_comment=caption)
        print(f"posted {plain!r} into {name} thread {ts}")
    return 75 if held else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="target day YYYY-MM-DD (default yesterday)")
    ap.add_argument("--csv", help="price an existing ATT export instead of pulling")
    ap.add_argument("--box-csv", help="explicit BOX crosstab csv")
    ap.add_argument("--post", action="store_true",
                    help="post to the thread (default: render only)")
    ap.add_argument("--dm", metavar="USER_ID", help="post to a DM (test)")
    ap.add_argument("--no-post", action="store_true",
                    help="render only, even if --post was given (rerun always "
                         "appends the registry's --post; this is the override)")
    ap.add_argument("--only", choices=["att", "box"],
                    help="just one campaign's board")
    ap.add_argument("--tx-compare", action="store_true",
                    help="one-off: BOX week priced on the OLD TX Grid vs the "
                         "New Compensation, written to Mini Control; no post")
    a = ap.parse_args(argv)

    upto = (dt.date.fromisoformat(a.date) if a.date
            else dt.date.today() - dt.timedelta(days=1))
    monday = week_of(upto)
    now = dt.datetime.now()
    if a.tx_compare:
        box_csv = Path(a.box_csv) if a.box_csv else newest_box_csv()
        if not box_csv:
            print("no box csv on disk")
            return 1
        box_scale_compare(box_csv, monday, upto)
        return 0
    held = False
    boards = []          # (png, plain, caption)
    tag = f"{upto.month}.{upto.day}"

    # ---------------- AT&T ----------------
    if a.only != "box":
        if a.csv:
            src_csv = Path(a.csv)
        else:
            from automations.captainship_boards.run import pull_orderlog
            src_csv = OUT_DIR / f"orderlog_{monday}_{upto}.csv"
            if not (src_csv.exists()
                    and src_csv.stat().st_mtime > time.time() - 3600):
                pull_orderlog(monday, upto, src_csv)
        print(f"ATT: pricing {src_csv}")
        per_rep, unpriced = load_priced(src_csv, monday, upto)
        if not any(rec["days"].get(upto) for rec in per_rep.values()) and \
                (now.hour < 6 or (now.hour == 6 and now.minute < 25)):
            print(f"ATT HOLD: no rows for {upto} in the export yet")
            held = True
        else:
            rows, office = build_rows(per_rep, monday, upto)
            for r in rows:
                print(f"  {r['rep']:24} {r['tier']:>3} ${r['total']:>8,.0f}")
            print(f"  ATT OFFICE ${sum(r['total'] for r in rows):,.0f} "
                  f"(incl ${office['bonus']:,.0f} tier bonus)")
            if unpriced:
                print(f"  unpriced: {dict(unpriced)}")
            png = render(rows, office, monday, upto,
                         OUT_DIR / f"revenue_board_{upto}.png")
            boards.append((png, "b2b", f"Revenue Board {tag}",
                           f":moneybag: *Revenue Board {tag}* — per-day AT&T "
                           "revenue on the office comp sheet (incl. ABP / plan "
                           "add-ons; Week Total includes the Tiered Volume "
                           "bonus at the rep's current tier; baseline churn; "
                           "MCOE/road trip not included)"))

    # ---------------- BOX ----------------
    if a.only != "att":
        box_csv = Path(a.box_csv) if a.box_csv else newest_box_csv()
        # BOX data only reaches this machine when box_order_log writes its csv
        # at 7:00 / 8:30 (same repo, same machine). Before 7:00 the newest file
        # on disk is YESTERDAY's pull, which cannot carry `upto` no matter what
        # — so the 05:20 / 05:50 / 06:30 passes are not HELD, it simply is not
        # the BOX board's turn yet. Holding there published a `partial` run
        # every single morning and machine_digest's watcher alerted on it
        # (2026-08-31, first scheduled day). The AT&T board is the one those
        # early passes exist for; BOX rides the 07:25 / 08:50 / 09:40 rungs.
        if not (a.date or a.box_csv) and now.hour < 7:
            print("BOX: not its turn yet — box_order_log writes the csv at "
                  "7:00/8:30; this pass is the AT&T board's")
        elif not box_csv or not box_csv.exists():
            print("BOX HOLD: no box_order_log csv on disk yet")
            held = True
        else:
            print(f"BOX: pricing {box_csv}")
            per_box = load_box_priced(box_csv, monday, upto)
            # BOX sells ENERGY TO BUSINESSES, and businesses are shut on
            # Sunday: on a MONDAY the newest day this export can carry is
            # SATURDAY, five Mondays out of six (the same fact behind
            # tableau_freshness.SUNDAY_QUIET_MARKERS). Asking for Sunday held
            # every Monday pass until the 9:35 fail-open, so Monday's board
            # landed 2h15m late for a week with nothing wrong with it.
            box_needs = upto - dt.timedelta(days=1) if upto.weekday() == 6 else upto
            box_ready = any(rec["days"].get(box_needs) for rec in per_box.values())
            # The BOX extract refreshes ~7am and box_order_log writes the csv
            # at 7:00/8:30 — before ~9:35 an empty target day means "not
            # posted yet", after it it means a real zero.
            if not box_ready and (now.hour < 9 or
                                  (now.hour == 9 and now.minute < 35)):
                print(f"BOX HOLD: csv has no {box_needs} sales yet "
                      "(extract refreshes ~7am)")
                held = True
            elif per_box:
                rows_b, office_b = build_rows(per_box, monday, upto,
                                              tier_fn=box_tier_for)
                for r in rows_b:
                    print(f"  {r['rep']:24} {r['tier']:>3} ${r['total']:>8,.0f}")
                print(f"  BOX OFFICE ${sum(r['total'] for r in rows_b):,.0f} "
                      f"(incl ${office_b['bonus']:,.0f} volume bonus)")
                png_b = render(rows_b, office_b, monday, upto,
                               OUT_DIR / f"box_revenue_board_{upto}.png",
                               board_name="Vantura BOX Revenue")
                boards.append((png_b, "box", f"Box Revenue Board {tag}",
                               f":package: *Box Revenue Board {tag}* — per-day "
                               "BOX revenue on the New Compensation grid "
                               "(base by BF tier, Electric vs Ancillary + "
                               "term + kWh bonuses; Week Total includes the "
                               "Volume bonus at the rep's tier; no churn "
                               "impact for now)"))
            else:
                print("BOX: no counted sales this week — nothing to render")

    for png, _kind, _plain, _cap in boards:
        print(f"rendered {png}")
    if a.no_post:
        print("--no-post — not posting")
        return 75 if held else 0
    if a.post or a.dm:
        # The BOX SALES BOARD images ride this same pass (Carlos 2026-08-30:
        # they belong in the BOX Order Log thread, which exists from ~7:00 —
        # and by 7:25 the 7:15 order-log confirm has corrected the board, so
        # the images render right the first time). sales_boards routes
        # --program BOX there and dedups itself.
        if any(k == "box" for _p, k, _pl, _c in boards) and not a.dm:
            import subprocess
            r = subprocess.run(
                [sys.executable, "-m", "automations.sales_boards.run",
                 "--program", "BOX", "--post"],
                capture_output=True, text=True, timeout=900)
            for line in (r.stdout or "").splitlines()[-6:]:
                print(f"  sales_boards: {line}")
            held = held or r.returncode == 75
        for png, kind, plain, caption in boards:
            rc = post(png, plain, caption, kind, dm_user=a.dm or "")
            held = held or rc == 75
        return 75 if held else 0
    print("dry-run — --post to reply in the thread")
    return 75 if held else 0


if __name__ == "__main__":
    sys.exit(main())
