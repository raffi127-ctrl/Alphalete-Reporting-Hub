"""Vantura Sales Board fill — counts BOX and AT&T sales from Slack.

Base RETIRED 2026-08-30 (Carlos) — the campaign ended; nothing looks for it.

Three of the four campaigns on Carlos's Sales Board are reported nowhere but
#alphalete-gp-sales, so the VA opens the channel every morning, sorts the reps
alphabetically and hand-counts yesterday (Loom 2026-07-22; Carlos confirmed
2026-07-23 that all of it comes from the channel). This replaces that pass.
Parsing rules, the two counting modes and the traps live in parse.py.

THE FILL ONLY EVER RAISES A NUMBER (Megan 2026-07-23). Some sales reach the
board by a route that is not this channel, and those stand — a rep is written
only when they post a HIGHER count than the board already has. So the day
climbs through the evening passes and can never regress, and re-running an old
day is safe by construction.

Reconciliation is built in, because the hand-count has been wrong both ways:
  * the office posts its own running tally through the day — "A&T - 21/16 /
    Box - 6/8" — and the last one is an independent check;
  * every rep's current board cell is shown next to ours before any write.
Both are REPORTED, never silently corrected.

  python -m automations.vantura_slack_sales.run                 # yesterday
  python -m automations.vantura_slack_sales.run --date 2026-07-22
  python -m automations.vantura_slack_sales.run --week          # Mon..yesterday
  python -m automations.vantura_slack_sales.run --fill          # plan the write
  python -m automations.vantura_slack_sales.run --fill --yes    # actually write
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import ssl
import sys
from pathlib import Path

from automations.vantura_slack_sales import parse as P
from automations.vantura_slack_sales.parse import TZ

CHANNEL = ("#alphalete-gp-sales", "C07J46MQNUX")
SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
TAB = "Sales Board"

# Before this hour a run is closing out YESTERDAY, not filling today — the
# office lines up ~10:45am and nobody sells before it.
OFFICE_DAY_START = 10

NAME_COL, CAMPAIGN_COL = 2, 12        # col B, col L

# BOX moves off Slack and onto the box order log Tue 2026-09-01 (Carlos
# 2026-08-30: "starting Tuesday morning, you can use the box order log
# instead of Slack"). From that date the default passes stop counting BOX
# posts — vantura_orderlog_sales' 05:02 close-out owns BOX. An explicit
# --campaign BOX still works for a manual catch-up.
BOX_TO_ORDERLOG = dt.date(2026, 9, 1)
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
    "U0BAM3S005T": "Ibukunoluwa Ogunlola",  # second account (Eve 2026-07-31);
    # his 7/13 Base sale landed on no row. The thread only calls him "EL TWIN",
    # which is why the id sat unnamed — he and Obade Ogunlola are brothers.
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
    "U0B8VSF1RBM": "Monica",               # second account, same rep — and the
    # one she actually posts from. Her sales read as an unnamed id and landed
    # on no row at all: 7/28 BOX 1 and 7/30 BOX 2, which Jolie caught by hand
    # (2026-07-31). Teammates tag EITHER id in the shout-out list, never both
    # in one post, which is the tell that they are one person; the thread on
    # each of those posts is "MONICA MONICA MONICA".
    "U0B4FJABKPF": "Esmeralda",            # BOX; thread hype "ESMEEEEEE"
    # BOX through 7/14, then nothing. She has NO row on the board — not even a
    # 'T' one, though every other terminated rep keeps theirs — and Roll Call
    # carries her as Terminated (wk 4.26 BOX, and a 4.12 B2B row stamped
    # "T Sat Jun 20 2026"). That conflicts with her still training new starts in
    # weeks 7.19 and 7.26 and selling on 7/10 and 7/14, so the record is stale
    # somewhere. Mapped anyway: if she posts again the log says her NAME.
    "U0ATA7VUVE0": "Melanie Hernandez",
    "U047D64M0RW": "Nico Murrugarra",
    # BOX new starts, added 2026-08-08. Every one of these posted real sales all
    # week that landed in the day TOTAL but on NO rep's row — 12 BOX sales in
    # five days, which is most of what Carlos means by "Box is off almost every
    # day". Named the way the file's own note says to: the thread replies on
    # their sale posts shout the rep's name, and each id's per-day counts then
    # match exactly one board row that the VA had been fixing up by hand.
    "U072BR0J0E5": "Sandy Samaniego",      # threads: "SANDYYYY", "Sandy !!"
    "U0BL53A3V1Q": "Samantha Rodriguez",   # thread: "ITS HER FIRST TIMEEEE SAMMMM"
    "U0BM813NQTZ": "Tara Lynn Ecklof",     # threads: "TARA ENERGY", "SHEEESHHH TARAAA"
    "U0BL716KWJV": "Kandice Michelle Flores",   # thread: "KANDICEEE"
    # The one id whose thread never says a name — the hype is "COLOMBIAA" /
    # "W CAR RIDE". Placed by its numbers instead: 1 on 8/5 and 2 on 8/6, and
    # Kyara's row is the only BOX row carrying exactly that pair on those two
    # days. Worth a second pair of eyes if her row ever looks off.
    "U0BMMCG2494": "Kyara Nayibe Mancilla Hurtado",
    # Added 2026-08-19. Both had been selling into the day TOTAL and onto no
    # row. Names confirmed off Slack's own "<@id|Display Name>" rendering in
    # teammates' shout-out lists, and the threads agree ("RUBBBYYYY",
    # "It's her first timeee !!!!" on her first sale, 8/17).
    "U0BMT31A54L": "Ruby Flores",
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
    "U0BJFCN6FM3": "Rafael Zapiain",   # posts as "falzapiain"; on the B2B board
    # B2B new starts, added 2026-08-08 — same story as the BOX block above.
    "U0BL7DT90FN": "Caleb Gregory Deleon",      # threads: "LETS GOOO CALEB"
    "U0BKXFE2SDR": "Francisco Javier Jimenez",  # threads: "FRANNNNNN", "Francisco !!!!"
    "U0BMX3TRTNK": "Emmanuel Nieto",            # thread: "El eman el og"
    # Added 2026-08-19 — same story, B2B side. Rodolfo posts under his own
    # name but the office only ever shouts "RUDYYYYYYYY"; Adabella posts as
    # "Adabella Amaya", two thirds of her board name, so first+last can't
    # bridge it on its own (hence the NAME_ALIASES line below).
    "U0BQ3GB6RA4": "Rodolfo Bazan",
    "U0BP752M3V4": "Adabella Amaya Gallegos",   # thread: "Bella!!!!"
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
    # Slack's OWN display names for two of the new BOX reps don't reach their
    # board row on their own: match_rep needs first+last, and Slack drops the
    # first name entirely for one of them. Harmless today (KNOWN_USERS already
    # carries the board spelling and wins), but these are what a live
    # users.info lookup returns, so they matter the moment the scope lands.
    "michelle flores": "Kandice Michelle Flores",
    "kyara": "Kyara Nayibe Mancilla Hurtado",
    "caleb deleon": "Caleb Gregory Deleon",
    "tara ecklof": "Tara Lynn Ecklof",
    "francisco jimenez": "Francisco Javier Jimenez",
    "adabella amaya": "Adabella Amaya Gallegos",
}

# The office's own running tally, e.g. "A&T - 21/16", "Box - 6/8", "Base -12/20".
TALLY_RE = {
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
# Resolved ids are remembered here so one successful lookup covers every later
# run, and so a rep keeps their name on a pass where Slack is unreachable.
# Per-machine, under the git-ignored config area (Windows-safe via Path.home()).
NAME_CACHE = Path.home() / ".config" / "recruiting-report" / "vantura-slack-users.json"

# What a human has to click if the token still can't read the directory. Printed
# once per run, and carried into the corrections alert.
SCOPE_FIX = (
    "Slack app config -> OAuth & Permissions -> User Token Scopes -> add "
    "`users:read` -> Reinstall to Workspace, then re-save the token on Lucy 2. "
    "Until that happens every NEW rep has to be added to KNOWN_USERS by hand."
)


def _load_cache() -> dict:
    try:
        return json.loads(NAME_CACHE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no cache yet is the normal first run
        return {}


def _save_cache(cache: dict) -> None:
    try:
        NAME_CACHE.parent.mkdir(parents=True, exist_ok=True)
        NAME_CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True),
                              encoding="utf-8")
    except Exception as e:  # noqa: BLE001 — bookkeeping must never fail a run
        _log(f"  (couldn't write the name cache: {type(e).__name__})")


def resolve_names(client, ids, log=_log) -> tuple[dict, bool]:
    """Ask Slack who these posters are. Returns ({id: name}, scope_ok).

    KNOWN_USERS is hand-kept only because the reporting token has no
    `users:read` (verified 2026-07-23, re-verified 2026-08-08 — still
    missing_scope). The moment that scope is added this starts working and the
    table degrades into a cache: a new rep is named on their first sale instead
    of landing on no row until someone notices. Nothing else has to change.

    A missing scope is NOT an error — it's the status quo. It logs the fix once
    and hands back what it has.
    """
    ids = [u for u in ids if u]
    if not ids:
        return {}, True
    cache = _load_cache()
    found = {u: cache[u] for u in ids if u in cache}
    todo = [u for u in ids if u not in cache]
    if not todo:
        return found, True
    scope_ok = True
    for uid in todo:
        try:
            u = client.users_info(user=uid)["user"]
        except Exception as e:  # noqa: BLE001 — Slack errors must not kill a fill
            err = getattr(getattr(e, "response", None), "data", {}) or {}
            if err.get("error") == "missing_scope":
                scope_ok = False
                break               # every other id would fail the same way
            log(f"  users.info({uid}) failed: {type(e).__name__} — skipped")
            continue
        name = (u.get("real_name")
                or u.get("profile", {}).get("real_name")
                or u.get("profile", {}).get("display_name") or "").strip()
        if name:
            found[uid] = cache[uid] = name
            log(f"  resolved {uid} -> {name} (from Slack)")
    if found:
        _save_cache(cache)
    if not scope_ok:
        log(f"  NOTE: the token still has no `users:read`. {SCOPE_FIX}")
    return found, scope_ok


def _client():
    import certifi
    from slack_sdk import WebClient
    from automations.shared.slack_metrics_post import _load_token

    return WebClient(token=_load_token(),
                     ssl=ssl.create_default_context(cafile=certifi.where()))


# Hype that names nobody — every thread is full of it, and a reply made only of
# these is noise. Kept deliberately small: the point is to drop the obvious
# filler, not to guess which replies contain a name.
_HYPE_ONLY = re.compile(
    r"^(?:[\W\d_]|:[a-z0-9_+-]+:|lets?\s*go+|vamos+|sheesh+|damn+|w+|yes+|"
    r"fire|dawg|goat|queen|king|big|money|congrats?|welcome|more|first|"
    r"time|her|his|it'?s|the|a|to|and|for|of|my|son|beast|animal|shesh+)*$",
    re.I)


def thread_hints(client, unknown_posts, per_id: int = 6, log=_log) -> dict:
    """Candidate NAMES for posters Slack won't name for us: {id: [reply, …]}.

    Without `users:read` an unnamed id is a dead end in code — but never in the
    channel. Teammates reply to a rep's sale post shouting their name:
    "SANDYYYY", "ITS HER FIRST TIMEEEE SAMMMM", "LETS GOOO CALEB", "KANDICEEE",
    "El eman el og". That is how all eight unnamed reps were identified by hand
    on 2026-08-08, and it needs no scope beyond the channel history we already
    read. So the alert carries the evidence instead of just an opaque `U0B…`,
    and naming a rep becomes a five-second read rather than a hunt.

    Best-effort by design: a thread that won't load costs nothing.
    """
    hints: dict[str, list[str]] = {}
    for uid, tss in unknown_posts.items():
        got: list[str] = []
        for ts in tss[:2]:                    # two threads is plenty
            try:
                msgs = client.conversations_replies(
                    channel=CHANNEL[1], ts=ts, limit=40)["messages"]
            except Exception as e:  # noqa: BLE001 — evidence is a bonus, never a failure
                log(f"  (couldn't read the thread on {ts}: {type(e).__name__})")
                continue
            for m in msgs[1:]:                # [0] is the sale post itself
                txt = " ".join(html.unescape(m.get("text", "")).split())
                if not txt or "<@" in txt or _HYPE_ONLY.match(txt):
                    continue
                if txt not in got:
                    got.append(txt[:70])
            if len(got) >= per_id:
                break
        if got:
            hints[uid] = got[:per_id]
    return hints


def fetch_posts(oldest: dt.datetime, latest: dt.datetime):
    """Every top-level message in the window, parsed, plus the user directory.

    Top-level only, on purpose: thread replies in this channel are hype
    ("SHEEESHHH", emoji) — checked across a full week, no sale has ever been
    reported in a reply. (They ARE read, separately, when a poster has no name:
    see thread_hints.)
    """
    client = _client()
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

    # Anyone still unnamed gets one shot at the Slack directory before their
    # sales go looking for a board row.
    unknown = {m.get("user") for m in raw if m.get("user")} - set(directory)
    resolved, scope_ok = resolve_names(client, sorted(unknown))
    directory.update(resolved)

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
    return posts, directory, scope_ok


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


def week_ok(g, day: dt.date):
    """(ok, shown, want) — is the board showing the week that CONTAINS `day`?

    The board holds ONE week at a time, chosen by the gold WE cell (B2). The
    day columns are just Monday..Sunday, so nothing in them says which week
    they belong to: writing while the selector is on another week would land
    today's sales on last week's Monday, on top of real numbers.

    This matters every Monday. The 5:00am pass is closing out SUNDAY, so it
    wants the week that just ended and the board is still correct; by the 4:00pm
    pass the target is Monday itself, which needs the NEW week — so the board
    has to have rolled in between. Same rule covers both: the WE cell must be
    the Sunday of the target day's week.

    Reuses sales_boards' expected_we so this and the 5:10am post can never
    disagree about which week is current — they gate on the same cell.
    We deliberately do NOT roll the board ourselves: only some day cells are
    formulas keyed on B2, the rest are hand-typed, so flipping the selector
    would repopulate a few and leave the others stale (see sales_boards.check_we).
    """
    from automations.sales_boards.run import WE_CELL, expected_we, we_matches
    r, c = WE_CELL
    shown = str(_cell(g, r, c)).strip()
    _, want = expected_we(day)
    # we_matches, not ==: the dropdown stores 8.30 as the number 8.3.
    return we_matches(shown, want), shown, want


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
        if same:
            delta = ""
        elif on_board.isdigit() and rec["count"] <= int(on_board):
            # The board is ahead of what was posted — kept, never lowered.
            delta = f"   <- board has {on_board}, KEPT (we only raise)"
        else:
            delta = f"   <- board has {on_board or '(blank)'}"
        log(f"  {_cell(g, row, NAME_COL):<28} {rec['count']:>2}"
            f"  ({len(rec['posts'])} post(s)){delta}")
        for f in dict.fromkeys(rec["flags"]):
            log(f"      ! {f}")
    for author, rec in unmatched:
        # Two very different problems, and telling them apart matters. A NAME
        # we can't place on the board is a board question. A raw "U0B8VSF1RBM"
        # is a hole in KNOWN_USERS — the rep is real, sold, and their row reads
        # 0. That is exactly how Monica Hernandez lost 7/28 and 7/30: the line
        # below said "NOT A BOX REP: U0B8VSF1RBM" and nobody can read an id.
        if any(p.author == p.author_id for p in rec["posts"]):
            log(f"  !! UNKNOWN SLACK USER {author} — {rec['count']} {campaign} "
                f"sale(s), IN THE TOTAL BUT ON NO REP'S ROW")
            log("      Slack gave no name for this id. Open one of the posts "
                "below in Slack: the thread replies shout the rep's name. Then "
                "add the id to KNOWN_USERS in this file.")
        else:
            log(f"  ! NOT A {campaign} REP ON THE BOARD: {author} — "
                f"{rec['count']}")
        for p in rec["posts"]:
            log(f"      {p.when.astimezone(TZ).strftime('%H:%M')}  {p.excerpt}")

    total = sum(r["count"] for r in matched.values()) \
        + sum(r["count"] for _, r in unmatched)
    log(f"  {'TOTAL':<28} {total:>2}   ({agree}/{len(matched)} reps already "
        f"agree with the board)")

    # The other direction: the board credits a rep who posted nothing. Sales do
    # reach the board by routes that are not this channel (Edgar Camunez,
    # Charley Perez, Giovanni Monreal all did) — EXPECTED, and they stand
    # (Megan 2026-07-23). Listed only so the day's numbers can be traced.
    if col:
        kept = [_cell(g, row, NAME_COL) for key, row in
                sorted(rows.items(), key=lambda kv: kv[1])
                if key not in matched
                and str(_cell(g, row, col)).strip().isdigit()
                and int(str(_cell(g, row, col)).strip()) > 0]
        if kept:
            log(f"  kept as-is (on the board, didn't post): {', '.join(kept)}")

    tal = office_tally(posts, day, campaign)
    if tal:
        log(f"  office's own tally post ({tal[1]}): {tal[0]} — "
            f"{'matches' if tal[0] == total else 'DIFFERS'}")

    return {"day": day, "campaign": campaign, "col": col, "rows": rows,
            "matched": matched, "unmatched": unmatched, "total": total}


def fill_plan(g, result):
    """(rep, a1, current, new, note) for every cell that would change.

    THE FILL ONLY EVER RAISES A NUMBER (Megan 2026-07-23). Some sales reach
    the board by a route that is not this channel — Edgar Camunez, Charley
    Perez and Giovanni Monreal all carried board numbers with no matching
    post — and those stand. A rep is overwritten only when they post a HIGHER
    count than the board already has. So the day climbs through the evening
    passes and can never regress: a deleted post, a rep who reposts with a
    lower counter, or a hand-entered figure we can't see are all safe.
    """
    from gspread.utils import rowcol_to_a1
    col = result["col"]
    if not col:
        return []
    plan = []
    for key, rec in result["matched"].items():
        row = result["rows"][key]
        cur = str(_cell(g, row, col)).strip()
        new = rec["count"]
        note = ""
        if cur.isdigit():
            if new <= int(cur):
                continue                      # never lower what's there
        elif cur:
            # A non-numeric marker (X = didn't work, T = terminated). They
            # posted a sale, so the number wins — but say so, because a
            # terminated rep posting is worth a human look.
            note = f"  (replaces marker {cur!r})"
        plan.append((_cell(g, row, NAME_COL), rowcol_to_a1(row, col),
                     cur or "(blank)", str(new), note))
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
    if not a.campaign and now.date() >= BOX_TO_ORDERLOG and "BOX" in campaigns:
        campaigns.remove("BOX")
        _log(f"BOX comes from the order log since {BOX_TO_ORDERLOG.isoformat()}"
             " (vantura_orderlog_sales) — not counted from Slack")
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
    posts, directory, scope_ok = fetch_posts(lo, hi)
    by_camp = {c: sum(1 for p in posts if p.campaign == c) for c in campaigns}
    _log(f"{len(posts)} messages, {directory and len(directory)} known users, "
         + ", ".join(f"{k} {v}" for k, v in by_camp.items()) + " sale posts")

    ws, g = board_grid()
    results = [run_campaign(posts, g, d, c) for d in days for c in campaigns]

    # A poster we can't name sells into the day TOTAL but onto NO rep's row, and
    # the 5:10am board post renders that hole. It used to be a log line nobody
    # reads (that is how Monica lost 7/28 and 7/30, and how five BOX reps lost a
    # whole week in August). Now it goes where every other report's problems go.
    unknown_sales = sorted({
        (author, res["campaign"], rec["count"])
        for res in results for author, rec in res["unmatched"]
        if any(p.author == p.author_id for p in rec["posts"])})
    if unknown_sales:
        # Pull the thread hype for each unnamed id so the alert can say WHO,
        # not just which id. Done here (not in the alert) because it needs the
        # Slack client and the posts, and so the log carries it too.
        unknown_posts = {}
        for res in results:
            for author, rec in res["unmatched"]:
                for p in rec["posts"]:
                    if p.author == p.author_id:
                        unknown_posts.setdefault(author, []).append(p.ts)
        hints = thread_hints(_client(), unknown_posts)
        for uid, lines in hints.items():
            _log(f"  thread on {uid}'s post says: " + " | ".join(lines))
        if a.fill and a.yes:
            from automations.vantura_slack_sales import alert
            alert.alert_unknown_posters(unknown_sales, scope_ok, hints=hints)
    elif a.fill and a.yes:
        # Every sale landed on a rep's row — close the unknown-poster thread if
        # one is open. It is closed HERE, not on the run's exit code: a run can
        # finish clean and still have an unnamed poster, so the two conditions
        # can't share a signal (Eve 2026-08-14).
        from automations.vantura_slack_sales import alert
        alert.resolve_unknown()

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
    held, held_days = False, set()
    for res in results:
        # GATE: never write into a week the board isn't showing.
        ok, shown, want = week_ok(g, res["day"])
        if not ok:
            held = True
            held_days.add(res["day"])
            _log(f"{res['campaign']} {_md(res['day'])}: WRONG WEEK — holding. "
                 f"The gold WE cell reads {shown!r} but {_md(res['day'])}'s "
                 f"sales belong to week {want!r}. Roll the board (set B2 to "
                 f"{want}) and re-run; writing now would overwrite the "
                 f"previous week's column.")
            continue
        if res["col"] is None:
            _log(f"{res['campaign']} {res['day']}: no column for that weekday "
                 "on the tab — nothing written")
            continue
        plan = fill_plan(g, res)
        _log(f"{res['campaign']} {_md(res['day'])} — {len(plan)} cell(s) "
             "would change:")
        for rep, a1, cur, new, note in plan:
            _log(f"  {a1}  {rep:<28} {cur} -> {new}{note}")
        if not a.yes:
            continue
        if plan:
            _retry(ws.batch_update,
                   [{"range": a1, "values": [[int(new)]]}
                    for _rep, a1, _cur, new, _note in plan])
            _log(f"  wrote {len(plan)} cell(s)")
    if not a.yes:
        _log("DRY RUN — re-run with --yes to write")

    # A held day that is ALREADY PAST is not self-healing, and the alert used to
    # promise the opposite ("the next hourly pass picks it up on its own"). The
    # 4-9pm passes only ever fill the day IN PROGRESS, and the 5:00am pass only
    # closes out the day before it — so nothing ever comes back for Tuesday once
    # Wednesday has started. Tue 8/18 was filled two days late for exactly this
    # reason (Eve 2026-08-19). Machine-readable so alert.py can carry it into
    # the Slack post.
    if held_days:
        _log("")
        for d in sorted(held_days):
            _log(f"HELD DAY: {d.isoformat()}")
        stale = [d for d in sorted(held_days) if d < today]
        if stale:
            _log("NOT SELF-HEALING — no later pass returns to a day that is "
                 "already past. Once the board is rolled, each of these needs "
                 "its own run:")
            for d in stale:
                _log(f"  lucy rerun vantura_slack_sales --date {d.isoformat()}"
                     f' --machine "Lucy 2"')

    # Monday heads-up, while there is still time to act. The 5:00am pass runs on
    # LAST week's board on purpose (it is closing out Sunday), but the 4:00pm
    # pass needs the NEW week up — and nothing in between says so. Without this
    # the first sign of a board that was never rolled (or rolled to the wrong
    # week: the picker list has 8.9 sitting right under 8.23, which is how
    # 2026-08-17 went wrong) is the 4:00pm HOLD, and every pass after it.
    if not a.date and today.weekday() == 0 and now.hour < OFFICE_DAY_START:
        from automations.sales_boards.run import WE_CELL, expected_we
        shown = str(_cell(g, *WE_CELL)).strip()
        _, new_we = expected_we(today)      # Sunday of the week starting today
        if shown != new_we:
            _log("")
            _log(f"ROLL DUE: the board reads WE {shown!r} — right for this "
                 f"pass, which is closing out Sunday. It has to read "
                 f"{new_we!r} (cell B2) before the 4:00pm pass fills "
                 f"{_md(today)}.")
            if a.fill and a.yes:
                from automations.vantura_slack_sales import alert
                alert.remind_roll(shown, new_we)

    # The afternoon wrote into a rolled board, so a Monday-morning ROLL DUE
    # reminder has been acted on. No-op when nothing is open.
    if a.fill and a.yes and not held and now.hour >= OFFICE_DAY_START:
        from automations.vantura_slack_sales import alert
        alert.resolve_roll()
    # 75 = EX_TEMPFAIL, the same hold code sales_boards uses for a wrong-week
    # board. The next pass retries; nothing was written.
    return 75 if held else 0


if __name__ == "__main__":
    sys.exit(main())
