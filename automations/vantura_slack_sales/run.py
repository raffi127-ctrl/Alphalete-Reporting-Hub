"""Vantura Sales Board fill — counts Base, BOX and AT&T sales from Slack.

Three of the four campaigns on Carlos's Sales Board are reported nowhere but
#alphalete-gp-sales, so the VA opens the channel every morning, sorts the reps
alphabetically and hand-counts yesterday (Loom 2026-07-22; Carlos confirmed
2026-07-23 that all of it comes from the channel). This replaces that pass.
Parsing rules, the two counting modes and the traps live in parse.py.

Reconciliation is built in, because the hand-count has been wrong both ways:
  * the office posts its own running tally through the day — "A&T - 21/16 /
    Box - 6/8 / Base - 12/20" — and the last one is an independent check;
  * every rep's current board cell is shown next to ours before any write.
Both are REPORTED, never silently corrected.

  python -m automations.vantura_slack_sales.run                 # yesterday
  python -m automations.vantura_slack_sales.run --date 2026-07-22
  python -m automations.vantura_slack_sales.run --week          # Mon..yesterday
  python -m automations.vantura_slack_sales.run --campaign Base
  python -m automations.vantura_slack_sales.run --fill          # plan the write
  python -m automations.vantura_slack_sales.run --fill --yes    # actually write
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import ssl
import sys

from automations.vantura_slack_sales import parse as P
from automations.vantura_slack_sales.parse import TZ

CHANNEL = ("#alphalete-gp-sales", "C07J46MQNUX")
SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
TAB = "Sales Board"

# Before this hour a run is closing out YESTERDAY, not filling today — the
# office lines up ~10:45am and nobody sells before it.
OFFICE_DAY_START = 10

NAME_COL, CAMPAIGN_COL = 2, 12        # col B, col L
DAY_HEADER_ROW = 4                    # row carrying Monday..Sunday
FIRST_DAY_COL, LAST_DAY_COL = 5, 11   # cols E..K

# WHY THIS TABLE EXISTS: the reporting token has no `users:read` scope, so
# users.info can't resolve a poster (verified 2026-07-23: missing_scope). The
# obvious workaround — harvesting Slack's own "<@U123|Display Name>" mention
# syntax out of the shout-out lists — does NOT work either: conversations.history
# returns mentions bare, as "<@U123>", with no name. So ids are mapped here.
# That is also the sturdier key: a rep renaming themselves in Slack can't break
# the match. A poster who isn't listed is REPORTED as unknown, never silently
# dropped — add them here, or get the scope added and this becomes a cache.
MENTION_RE = re.compile(r"<@(U[A-Z0-9]+)\|([^>]+)>")

KNOWN_USERS = {
    # Base (residential energy)
    "U0B4HKKSMQA": "Miguel Vargas",
    "U0ACMJ0HHPE": "Miguel Vargas",        # second account, same rep
    "U0AU0LFR8Q5": "Christian Villarreal Sr.",
    "U0A80F907N3": "Edgar Camunez",
    "U08S5388YKS": "Will Mills",
    "U0BDV1BV9A4": "ADRIAN ALONSO LEOS",
    "U0B3741MVQU": "Anthony Castro",
    "U0B958DGNHX": "Christopher Rivera",
    "U0AU21DH8RL": "Emmanuel Nieto",
    "U0AQN5YHV4G": "Ibukunoluwa Ogunlola",
    "U0BGA938M5E": "Juan Miranda",
    "U0BD56X1H40": "Charley Perez",
    "U0A64Q4KZM0": "Pablo Deleon",
    "U0ACBJS4WTD": "Eduardo Alvarez",
    "U0BC4HKP2QK": "Gabriel Rivera",
    "U0B8C7B4YRW": "Ivan Benitez",
    "U0ABP13LU91": "Richard Bautista",
    "U05UF0LQ22Y": "Obade Ogunlola",
    "U0BFHS9F3LH": "Josephe F",
    # BOX (business energy)
    "U0AU21B9DTQ": "Rebeca Juarez",
    "U0A0MPGHJ0G": "Jayden Luna",
    "U09U865JPDL": "Olivia Dittmer",
    "U0BC5NV6ENT": "Priscilla Maria Diaz",
    "U0BGWFQLVD3": "Amy Rodriguez",
    "U0BA8MEJMP1": "Arleth Rodriguez",
    "U0BASAE7LJD": "Citlaly Ramos",
    "U04GRP800Q4": "Cinthya Reyes",
    "U0BDTMHAZQV": "Joelle V. Barajas",
    "U0A9L3ZA6FQ": "Juliett Ortega",
    "U0BGWG9V1V3": "Kailany Solis",
    "U0BFJG4J8LB": "Nathaly Benitez",
    "U0BGJEEABK9": "Paloma Aquino",
    "U0BH1NR6933": "Valerie Salazar",
    "U0BGZS3BRPU": "Wendy Flores",
    "U09P15V7WUC": "Monica",
    "U047D64M0RW": "Nico Murrugarra",
    # B2B (AT&T lines and fiber)
    "U0ATXM9KYPM": "Jacob Ortega",
    "U07PU3WCN7P": "Nicholas Smedra",
    "U07R8Q3FTLM": "William Bautista",
    "U08TR2HSQV6": "Ndifreke Ikotidem",
    "U0BHVBG1J2U": "Andrew Munoz",
    "U0BHUUPD0TS": "Gregory Gonzalez",
    "U0B5WLHQ752": "Luis Adan Valenciano",
    "U0BBVDYCFB9": "Giovanni Monreal",
    "U0BGUBQ7G0K": "Emmanuel Mata",
    "U0BDY78FZ7C": "Jonathan Gonzalez Cortez",
    "U0A3XUYSB1U": "Eric Forsythe",
    "U0BC8RU30MC": "Aaron Tovar",
    "U0AUH09AHHP": "Diego Borres",
    "U0B35CK1U8Z": "Josue Lozoya",
    # Not reps, but they post here — named so a mis-parse points at a person.
    "U0BCG8F9B5Z": "Lucy Reporting",
    "U046G04P5LG": "Carlos Hidalgo",
    "U05LLCCSB2Q": "Sebastian Avellaneda",
    "U0919G4HW15": "Alphalete GP",
    "USLACKBOT": "Slackbot",
}

# Slack display name -> board REP name, where normalising can't bridge the two.
# Keep this list as short as it can be; everything else matches on name.
NAME_ALIASES = {
    "edgar camunez": "Edgar",
    "ibukunoluwa ogunlola": "IBK",
    "adrian alonso leos": "Adrian Leos",
    "juan miranda": "Juan Jose Miranda",
    "nicholas smedra": "Nick Smedra",
    "william bautista": "Will Bautista",
    "luis adan valenciano": "Luis Valenciano",
    "ndifreke ikotidem": "Didi",
    "jonathan gonzalez cortez": "Jonathan Gonzalez",
    "joelle v barajas": "Joelle Barajas",
    "monica": "Monica Hernandez",
    "josephe f": "Josephe Alessandro Figueredo",
}

# The office's own running tally, e.g. "A&T - 21/16", "Box - 6/8", "Base -12/20".
TALLY_RE = {
    "Base": re.compile(r"base\s*-?\s*(\d+)\s*/\s*\d+", re.I),
    "BOX": re.compile(r"box\s*-?\s*(\d+)\s*/\s*\d+", re.I),
    "B2B": re.compile(r"a\s*&?\s*t\s*-?\s*(\d+)\s*/\s*\d+", re.I),
}


def _log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}",
          flush=True)


def _md(d: dt.date) -> str:
    """'Wednesday 7/22' — built by hand because %-m is glibc-only and every
    report has to run on Windows too."""
    return f"{d.strftime('%A')} {d.month}/{d.day}"


def _norm(name: str) -> str:
    """Lowercase, drop punctuation and the Sr/Jr suffix — 'Christian
    Villarreal Sr.' and 'Christian Villarreal Sr' are one person."""
    n = re.sub(r"[^a-z ]", " ", str(name).lower())
    n = re.sub(r"\b(sr|jr|iii|ii)\b", " ", n)
    return " ".join(n.split())


# --------------------------------------------------------------- slack ---
def fetch_posts(oldest: dt.datetime, latest: dt.datetime):
    """Every top-level message in the window, parsed, plus the user directory.

    Top-level only, on purpose: thread replies in this channel are hype
    ("SHEEESHHH", emoji) — checked across a full week, no sale has ever been
    reported in a reply.
    """
    import certifi
    from slack_sdk import WebClient
    from automations.shared.slack_metrics_post import _load_token

    client = WebClient(token=_load_token(),
                       ssl=ssl.create_default_context(cafile=certifi.where()))
    raw, cursor = [], None
    while True:
        resp = client.conversations_history(
            channel=CHANNEL[1], oldest=str(oldest.timestamp()),
            latest=str(latest.timestamp()), limit=200, cursor=cursor)
        raw.extend(resp["messages"])
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    directory = dict(KNOWN_USERS)
    for m in raw:
        for uid, name in MENTION_RE.findall(m.get("text", "")):
            directory.setdefault(uid, name.strip())

    posts = []
    for m in raw:
        uid = m.get("user") or m.get("bot_id") or ""
        author = directory.get(uid) or m.get("username") or uid
        when = dt.datetime.fromtimestamp(float(m["ts"]), tz=dt.timezone.utc)
        # Slack escapes &, < and > in message text, so the office's own
        # "A&T - 21/16" tally arrives as "A&amp;T" and silently stops matching.
        posts.append(P.read_post(m["ts"], when, author, uid,
                                 html.unescape(m.get("text", ""))))
    posts.sort(key=lambda p: float(p.ts))
    return posts, directory


def office_tally(posts, day: dt.date, campaign: str):
    """The last '<campaign> - N/goal' the office posted that day."""
    rx = TALLY_RE[campaign]
    best = None
    for p in posts:
        if p.author in P.BOT_AUTHORS or p.sales_day != day:
            continue
        m = rx.search(p.text)
        if m:
            best = (int(m.group(1)), p.when.astimezone(TZ).strftime("%H:%M"))
    return best


# --------------------------------------------------------------- sheet ---
def board_grid():
    from automations.recruiting_report.fill import open_by_key
    ws = open_by_key(SHEET_ID).worksheet(TAB)
    return ws, ws.get("A1:N110")


def _cell(g, r, c):
    return g[r - 1][c - 1] if r - 1 < len(g) and c - 1 < len(g[r - 1]) else ""


# The per-campaign TOTAL rows at the bottom of the rep list carry the SAME
# campaign label in col L as the reps do, so they have to be cut off by the
# start of the totals block — same anchor sales_boards/render.py uses.
TOTALS_TOP = "AT&T (B2B)"


def totals_row(g) -> int:
    for r in range(DAY_HEADER_ROW + 1, len(g) + 1):
        if _cell(g, r, NAME_COL).strip() == TOTALS_TOP:
            return r
    raise SystemExit(f"totals block ({TOTALS_TOP!r}) not found on the tab")


def campaign_rows(g, campaign: str) -> dict[str, int]:
    """{normalised rep name: row} for one campaign.

    Found by the campaign label in col L, never by row number — reps are added
    and removed weekly and the tab is sorted globally. Stops at the totals
    block, whose rows are formula-driven and must never be written.
    """
    out = {}
    for r in range(DAY_HEADER_ROW + 1, totals_row(g)):
        name = _cell(g, r, NAME_COL).strip()
        if name and _cell(g, r, CAMPAIGN_COL).strip() == campaign:
            out[_norm(name)] = r
    return out


def day_column(g, day: dt.date):
    """Column for a weekday, found by its header text (Monday..Sunday)."""
    want = day.strftime("%A").lower()
    for c in range(FIRST_DAY_COL, LAST_DAY_COL + 1):
        if _cell(g, DAY_HEADER_ROW, c).strip().lower() == want:
            return c
    return None


def match_rep(author: str, rows: dict[str, int]):
    """Slack author -> board row key. Alias, then exact, then first+last."""
    key = _norm(author)
    if key in NAME_ALIASES:
        key = _norm(NAME_ALIASES[key])
    if key in rows:
        return key
    parts = key.split()
    if len(parts) >= 2:
        for cand in rows:
            cp = cand.split()
            if cp and cp[0] == parts[0] and cp[-1] == parts[-1]:
                return cand
    return None


# --------------------------------------------------------------- report --
def run_campaign(posts, g, day: dt.date, campaign: str, log=_log) -> dict:
    rows = campaign_rows(g, campaign)
    counts = P.tally(posts, day, campaign)
    col = day_column(g, day)

    matched, unmatched = {}, []
    for author, rec in sorted(counts.items()):
        key = match_rep(author, rows)
        if key:
            matched[key] = {"author": author, **rec}
        else:
            unmatched.append((author, rec))

    log("")
    log(f"--- {campaign} — {_md(day)} ---")
    if not counts:
        log("  no posts")
    agree = 0
    for key, rec in sorted(matched.items(), key=lambda kv: -kv[1]["count"]):
        row = rows[key]
        on_board = str(_cell(g, row, col)).strip() if col else ""
        same = on_board == str(rec["count"])
        agree += same
        log(f"  {_cell(g, row, NAME_COL):<28} {rec['count']:>2}"
            f"  ({len(rec['posts'])} post(s))"
            f"{'' if same else f'   <- board has {on_board or chr(39)*2!r}'}")
        for f in dict.fromkeys(rec["flags"]):
            log(f"      ! {f}")
    for author, rec in unmatched:
        log(f"  ! NOT A {campaign} REP ON THE BOARD: {author} — {rec['count']}")
        for p in rec["posts"]:
            log(f"      {p.when.astimezone(TZ).strftime('%H:%M')}  {p.excerpt}")

    total = sum(r["count"] for r in matched.values()) \
        + sum(r["count"] for _, r in unmatched)
    log(f"  {'TOTAL':<28} {total:>2}   ({agree}/{len(matched)} reps already "
        f"agree with the board)")

    # The other direction: the board credits a rep who posted nothing. That is
    # how Edgar's Monday 5 and Giovanni's Monday 1 showed up — sales reaching
    # the board by some route that is not this channel. The fill never touches
    # these rows (only reps who posted are written), but they must be visible.
    if col:
        for key, row in sorted(rows.items(), key=lambda kv: kv[1]):
            if key in matched:
                continue
            on_board = str(_cell(g, row, col)).strip()
            if on_board.isdigit() and int(on_board) > 0:
                log(f"  ? board credits {_cell(g, row, NAME_COL)} with "
                    f"{on_board}, but they posted nothing — left untouched")

    tal = office_tally(posts, day, campaign)
    if tal:
        log(f"  office's own tally post ({tal[1]}): {tal[0]} — "
            f"{'matches' if tal[0] == total else 'DIFFERS'}")

    return {"day": day, "campaign": campaign, "col": col, "rows": rows,
            "matched": matched, "unmatched": unmatched, "total": total}


def fill_plan(g, result):
    """(rep, a1, current, new) for every cell that would change."""
    from gspread.utils import rowcol_to_a1
    col = result["col"]
    if not col:
        return []
    plan = []
    for key, rec in result["matched"].items():
        row = result["rows"][key]
        cur = str(_cell(g, row, col)).strip()
        new = str(rec["count"])
        if cur != new:
            plan.append((_cell(g, row, NAME_COL), rowcol_to_a1(row, col),
                         cur or "(blank)", new))
    return plan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="sales day (YYYY-MM-DD); default yesterday")
    ap.add_argument("--week", action="store_true",
                    help="every day from Monday through the target day")
    ap.add_argument("--campaign", choices=[c.name for c in P.CAMPAIGNS],
                    action="append",
                    help="limit to one campaign (repeatable); default all")
    ap.add_argument("--fill", action="store_true",
                    help="plan the board write (dry-run without --yes)")
    ap.add_argument("--yes", action="store_true", help="actually write")
    a = ap.parse_args(argv)

    campaigns = a.campaign or [c.name for c in P.CAMPAIGNS]
    now = dt.datetime.now(TZ)
    today = now.date()
    if a.date:
        end = dt.date.fromisoformat(a.date)
    else:
        # Which day the run is FOR, from the clock. The evening passes
        # (4-9pm) keep the day in progress current; the 5am pass closes out
        # the day before, sweeping up sales posted after the last evening run.
        # Reps start posting ~10:45am ("LINE UP"), so anything earlier than
        # OFFICE_DAY_START is finishing yesterday, not starting today.
        end = today if now.hour >= OFFICE_DAY_START else today - dt.timedelta(days=1)
        _log(f"no --date given; at {now.strftime('%H:%M')} that means "
             f"{_md(end)}")
    days = [end]
    if a.week:
        monday = end - dt.timedelta(days=end.weekday())
        days = [monday + dt.timedelta(days=i)
                for i in range((end - monday).days + 1)]

    # Pull a day either side so late posts and YESTERDAY tags land right.
    lo = dt.datetime.combine(days[0] - dt.timedelta(days=1), dt.time(0), tzinfo=TZ)
    hi = dt.datetime.combine(days[-1] + dt.timedelta(days=1), dt.time(12), tzinfo=TZ)
    _log(f"reading {CHANNEL[0]} {lo.date()} .. {hi.date()}")
    posts, directory = fetch_posts(lo, hi)
    by_camp = {c: sum(1 for p in posts if p.campaign == c) for c in campaigns}
    _log(f"{len(posts)} messages, {directory and len(directory)} known users, "
         + ", ".join(f"{k} {v}" for k, v in by_camp.items()) + " sale posts")

    ws, g = board_grid()
    results = [run_campaign(posts, g, d, c) for d in days for c in campaigns]

    skipped = [p for p in posts if p.skipped and p.sales_day in days]
    if skipped:
        _log("")
        _log("not counted (looked like a sale, read as chatter):")
        for p in skipped:
            _log(f"  {p.author} {p.when.astimezone(TZ).strftime('%m/%d %H:%M')}"
                 f" — {p.excerpt}")

    if not a.fill:
        return 0

    from automations.recruiting_report.fill import _retry
    _log("")
    for res in results:
        if res["col"] is None:
            _log(f"{res['campaign']} {res['day']}: the board is not on that "
                 "week — nothing written")
            continue
        plan = fill_plan(g, res)
        _log(f"{res['campaign']} {_md(res['day'])} — {len(plan)} cell(s) "
             "would change:")
        for rep, a1, cur, new in plan:
            _log(f"  {a1}  {rep:<28} {cur} -> {new}")
        if not a.yes:
            continue
        if plan:
            _retry(ws.batch_update,
                   [{"range": a1, "values": [[int(new)]]}
                    for _rep, a1, _cur, new in plan])
            _log(f"  wrote {len(plan)} cell(s)")
    if not a.yes:
        _log("DRY RUN — re-run with --yes to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
