"""Org Sales Board + Country Sales Board emails send THEMSELVES — after the
same battery of checks the Captainship Reports pass (captainship_drafts.auto_send).

Eve 2026-10-07: "quiero levantar el gate para org sales board y country sales
board con la misma batería de reglas que pusimos para los captainship drafts".
Plus two rules of her own:

  * "me gustaría que me notificara cuando aparece un owner nuevo para que no se
    vean fallas en los recortes de los screenshots". A new owner is the one
    thing that changes the SHAPE of the board (a row the crops have never had
    to fit), so on a weekday a new owner holds the email for her ✅ and names
    who it is. The visual check is told who is new and looks at their rows.
  * "los fines de semana todo se debe enviar solo sin gate bajo los mismos
    parámetros". Sat/Sun (and wr.NO_REVIEW_DAYS) the same checks run; a new
    owner only gets a heads-up in the thread and the email still goes. A real
    failure still holds it, every day.

THE CHECKS, in order (each one that fails says why, in the thread):

  1. the day's chain — wr.day_is_clean: a FAILED/INCOMPLETE job or a failure
     alert anywhere upstream of this email holds it.
  2. Tableau — a source that `shared/tableau_freshness` flagged stale today and
     that one of this email's jobs pulled does NOT hold it (Eve 2026-10-21,
     same rule as the captainships): before TABLEAU_DEADLINE it waits quietly;
     once the extract loads it is rebuilt from the board and goes; still behind
     at the cutoff, it is rebuilt once with what the board has and goes anyway.
     A pull whose export carries no date column judges itself instead — the
     org board's BOX crosstab (section_pull.note_lag, 2026-10-25) — and names
     its board section, so the visual check is told that section is late and
     its blank/zero days are never a blocker (excuse_late).
  3. the images — every image in the day's manifest exists, is not empty, and
     was built today. Fixable: rebuilt once.
  4. the visual check (claude, same model as captainship) — latest day column,
     number formats, font/style, copied numbers, and the new owners' rows.
     Fixable: rebuilt once, re-checked with the earlier findings in hand.
     A visual check that cannot run HOLDS (fail closed).

WHAT EVE SEES:
  * clean day           -> mailed, nothing posted (she gets the email anyway).
  * fixed by a rebuild  -> mailed; the link goes up with "rebuilt automatically".
  * new owner (weekday) -> link + who is new, tagging her; her ✅ sends it.
  * new owner (weekend) -> mailed; link + who is new, as a heads-up.
  * held                -> link + the reasons, tagging her, + ONE thread per
                           board per day in #claudecorrections. ✅ sends as is.

THE LOCK. A day that went out without a post has no thread to say "Sent" in,
so it is recorded in output/state/board_autosend/<board>/<date>.json — the
gate's `already_sent` reads that AND the thread. Everything runs on Lucy 1.

Off switch: ENABLED=False, or --no-auto on the gate (then weekdays wait for ✅
and weekends fall back to weekend_release, exactly as before).
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from automations.shared import weekend_release as wr

ENABLED_FROM = dt.date(2026, 10, 8)
ENABLED = True
MAX_REBUILDS = 1
# Same model and same answer shape as captainship_drafts.auto_send. Copied, not
# imported: importing that module drags in the whole captainship config (and
# with it Tableau/patchright), which the board gates must not need to load.
MODEL = "claude-opus-5-5"
_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "issues": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "image": {"type": "integer"},
                "section": {"type": "string"},
                "problem": {"type": "string"},
                "severity": {"type": "string", "enum": ["blocker", "minor"]},
            },
            "required": ["image", "section", "problem", "severity"],
            "additionalProperties": False}},
    },
    "required": ["ok", "issues"],
    "additionalProperties": False,
}


def _api_client():
    from automations.shared.pkg import ensure
    anthropic = ensure("anthropic")
    from automations.brand_audit import credentials
    return anthropic, anthropic.Anthropic(api_key=credentials.anthropic_api_key())


def _shrink(ctype: str, data: bytes) -> Tuple[str, bytes]:
    """The API takes ~5 MB per image; a big sheet crop can pass it."""
    if len(data) <= 3_500_000:
        return ctype, data
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.thumbnail((2400, 2400))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=88)
        return "image/jpeg", buf.getvalue()
    except Exception:  # noqa: BLE001 — no PIL: send as is, the API decides
        return ctype, data


def _issue_line(i: dict) -> str:
    sec = (i.get("section") or "").strip()
    return f"{sec + ': ' if sec else ''}{(i.get('problem') or '').strip()}"

AUTO_ID = "auto-check"
AUTO_WHO = "auto-check (no issues found)"
HELD_MARK = "Auto-send held"
NEW_OWNER_MARK = "New on the board"
REBUILT_MARK = "rebuilt automatically"
UPSTREAM_CLEARED = ("what held it earlier cleared — rebuilding the email from "
                    "the board as it is now")

# LATE TABLEAU WAITS, IT DOES NOT HOLD (Eve 2026-10-21: "no que me frenes todo y
# me hagas revisar manualmente"). The Just Energy "Daily Sales by ICD" view
# held these emails four days running (10/15-10/18), each one ending in a ✅ by
# hand. Copied from captainship_drafts.auto_send, not imported (see MODEL).
TABLEAU_DEADLINE = dt.time(12, 0)       # Central
TABLEAU_DEADLINE_REBUILD = ("Tableau still behind at 12:00 — rebuilt with the "
                            "latest numbers it had")


def _ct_now() -> dt.datetime:
    return dt.datetime.now(wr.CENTRAL).replace(tzinfo=None)


def past_tableau_deadline(day: dt.date) -> bool:
    """An older day (a rerun) is past the cutoff; today, from 12:00 CT."""
    now = _ct_now()
    return day < now.date() or (day == now.date()
                                and now.time() >= TABLEAU_DEADLINE)

_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"
STATE_DIR = _OUTPUT_DIR / "state" / "board_autosend"


def is_on(day: dt.date, *, enabled: bool = True) -> bool:
    return bool(enabled and ENABLED and day >= ENABLED_FROM)


# --------------------------------------------------------------------------
# what differs per board
# --------------------------------------------------------------------------
@dataclass
class Target:
    key: str                       # "org" / "country" — state folder + log
    name: str                      # "Org Sales Board" — Slack text
    report_id: str                 # scheduler id whose chain must be clean
    images: Callable[[dt.date], List[Tuple[str, Path]]]   # the manifest
    grid: Callable[[], List[List[str]]]                   # the live board tab
    # numbers in the captured images that must agree; [] = nothing to compare
    totals: Callable[[dt.date], List[str]] = lambda day: []
    # Org-board SECTIONS this email shows, for a late-source state that names
    # one (section_pull.note_lag: "BOX"). None = all of them (the Org email,
    # board + All Units); () = none — the Country board is Fiber only, so a
    # late Box must not keep it waiting until noon (2026-10-25).
    sections: Optional[Tuple[str, ...]] = None
    # A source worth waiting for before judging: returns why it is still
    # waiting, or None. Nobody uses it now: the Org email waited for Verizon
    # until 9:45 on 10/28, then Eve 2026-10-29 chose a day-behind Verizon (like
    # JE) over a late email — the 14:30 catch-up fills it in.
    wait_for: Optional[Callable[[dt.date], Optional[str]]] = None


def _org_images(run_day: dt.date) -> List[Tuple[str, Path]]:
    from automations.org_sales_board import screenshot_email as se
    return [(n, p) for n, p, _w in se.reviewed_images(run_day)]


def _org_grid() -> List[List[str]]:
    from automations.recruiting_report.fill import open_by_key
    from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB
    return open_by_key(SHEET_ID).worksheet(SANDBOX_TAB).get_all_values()


def _org_totals(run_day: dt.date) -> List[str]:
    """The Org board and its All Units section must show the same week total.
    2026-10-08 they went out 1886 vs 1841: the All Units tab was photographed
    before its post-BOX re-fill. A rebuild re-shoots both from the Sheet."""
    from automations.org_sales_board import screenshot_email as se
    t = se.captured_totals(run_day)
    # Can't read a total = can't vouch for it: hold (Eve 2026-10-08).
    if not t:
        return ["the board totals were not recorded at capture — can't check "
                "that All Units matches the Org board"]
    missing = [n for k, n in (("org", "Org board"), ("all_units", "All Units"))
               if t.get(k) is None]
    if missing:
        return [f"could not read the {' or '.join(missing)} grand total — "
                f"can't check that they match"]
    if t["org"] == t["all_units"]:
        return []
    return [f"All Units total ({t['all_units']}) doesn't match the Org board "
            f"total ({t['org']}) — the All Units tab was captured before it "
            f"caught up"]


def _country_images(run_day: dt.date) -> List[Tuple[str, Path]]:
    from automations.board_emails import boards as B
    from automations.board_emails import email_send as es
    return [(n, p) for n, p, *_ in es.reviewed_images(B.get("country"), run_day)]


def _country_grid() -> List[List[str]]:
    from automations.recruiting_report.fill import open_by_key
    from automations.country_sales_board.run import SHEET_ID
    from automations.country_sales_board import slack_post as sp
    return sp._find_ws(open_by_key(SHEET_ID), sp.TARGET_TAB).get_all_values()


def _num(v) -> Optional[int]:
    try:
        return int(float(str(v).replace(",", "").strip()))
    except ValueError:
        return None


def country_totals_issues(g: Sequence[Sequence[str]]) -> List[str]:
    """Every box on the Country board must show the same week total.
    2026-10-21 the delta box went out at 2165 against 2206 everywhere else: its
    totals row summed from one row below the first rep (Aaron Nimako, added at
    the top), and its 'Last week' cells were frozen literals (2610 vs 2427). The
    visual check passed it — a wrong total looks exactly like a right one.

    Found by labels, never by index: the Product Summary grand total, the
    leaderboard 'TOTALS' row (col C = the live week), the daily breakdown
    'Totals' row under 'RUNNING WEEK TOTALS', and the delta box's totals row
    ('Total this week' / 'Last week', the latter against 'Sales (Last Week)')."""
    from automations.org_sales_board import screenshot_email as se
    from automations.org_sales_board import rollover as org_ro

    def cell(r, c):
        return str(g[r][c]).strip() if r < len(g) and c < len(g[r]) else ""

    summary = se.grand_total(g, "Fiber - All Units")
    if summary is None:
        return ["could not read the Product Summary grand total — can't check "
                "that the boxes below match it"]
    got: List[Tuple[str, Optional[int]]] = []

    lb = next((r for r in range(len(g)) if cell(r, 0).upper() == "TOTALS"), None)
    got.append(("leaderboard TOTALS", _num(cell(lb, 2)) if lb is not None else None))

    daily = None
    for r in range(len(g)):
        rc = next((c for c in range(len(g[r]))
                   if cell(r, c).upper() == "RUNNING WEEK TOTALS"), None)
        if rc is None:
            continue
        tr = next((x for x in range(r + 1, len(g))
                   if cell(x, 0).lower() == "totals"), None)
        daily = _num(cell(tr, rc)) if tr is not None else None
        break
    got.append(("daily breakdown Totals", daily))

    tables = org_ro.find_delta_tables([list(map(str, row)) for row in g])
    tot = tables[0]["data_rows"][-1] if tables and tables[0]["data_rows"] else None
    # data_rows are 1-based, so the last rep's number is the totals row's index
    got.append(("delta box total", _num(cell(tot, 2)) if tot else None))

    out = []
    for name, v in got:
        if v is None:
            out.append(f"could not read the {name} — can't check it matches "
                       f"the Product Summary ({summary})")
        elif v != summary:
            out.append(f"{name} ({v}) doesn't match the Product Summary "
                       f"grand total ({summary})")

    last = se.grand_total(g, "Sales (Last Week)")
    lw = _num(cell(tot, 3)) if tot else None
    if last is not None and lw is not None and lw != last:
        out.append(f"delta box 'Last week' total ({lw}) doesn't match Sales "
                   f"(Last Week) ({last})")
    return out


def _country_totals(run_day: dt.date) -> List[str]:
    return country_totals_issues(_country_grid())


ORG = Target("org", "Org Sales Board", "org_sales_board_email",
             _org_images, _org_grid, _org_totals)
COUNTRY = Target("country", "Country Sales Board", "country-sales-board-email",
                 _country_images, _country_grid, _country_totals,
                 sections=())
TARGETS = {t.key: t for t in (ORG, COUNTRY)}


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------
def _state_path(t: Target, day: dt.date) -> Path:
    return STATE_DIR / t.key / f"{day.isoformat()}.json"


def load_state(t: Target, day: dt.date) -> dict:
    try:
        return json.loads(_state_path(t, day).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no file yet is the normal morning
        return {}


def save_state(t: Target, day: dt.date, state: dict) -> None:
    p = _state_path(t, day)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def local_sent(t: Target, day: dt.date) -> bool:
    return bool(load_state(t, day).get("sent"))


# --------------------------------------------------------------------------
# new owners
# --------------------------------------------------------------------------
def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def owner_names(grid: Sequence[Sequence[str]]) -> Set[str]:
    """Every name on a RANKED row of the board: col A a rank number, col B a
    name. That is the leaderboard and the day tables on both boards; header,
    Totals and WE-history rows have no rank, so a relabelled header can't read
    as a new person."""
    out = set()
    for row in grid:
        a = (row[0] if len(row) > 0 else "").strip()
        b = (row[1] if len(row) > 1 else "").strip()
        if a.isdigit() and b and not b.isdigit():
            out.add(_norm(b))
    return out


ROSTER_KEEP_DAYS = 14


def new_owners(t: Target, day: dt.date, names: Set[str]) -> List[str]:
    """Names on the board today that were not on it the last day we looked.

    The first day ever is the baseline — nobody is "new". The snapshot is kept
    per day, so re-checking the same day all afternoon keeps comparing against
    YESTERDAY, not against this morning's read of today."""
    p = STATE_DIR / t.key / "roster.json"
    try:
        days: Dict[str, List[str]] = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        days = {}
    prior = sorted(d for d in days if d < day.isoformat())
    days[day.isoformat()] = sorted(names)
    for d in sorted(days)[:-ROSTER_KEEP_DAYS]:
        days.pop(d, None)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(days, indent=1), encoding="utf-8")
    if not prior:
        return []
    return sorted(names - set(days[prior[-1]]))


# --------------------------------------------------------------------------
# 2. Tableau
# --------------------------------------------------------------------------
def _stale_why(st: dict) -> str:
    """Why the freshness gate flagged a source, in words. Only DATED exports
    carry 'newest'; a dateless crosstab is flagged by content ('frozen') or by
    a filter we could not confirm — printing 'data only through ?' for those
    (Org/Country board holds 10/16-10/18) read like a broken date read."""
    if st.get("newest"):
        return f"data only through {st['newest']}"
    kind = st.get("kind")
    if kind == "frozen":
        return "same numbers several days running — the pull is stuck"
    if kind == "unconfirmed-filter":
        return "a filter on the view could not be confirmed"
    return "flagged stale"


def day_behind_sections() -> List[str]:
    """Sections whose source publishes a day late (Retail JE, BOX, Verizon).
    The visual check has to know them too: 2026-10-28 it held the org email on
    Nico's blank Verizon Tuesday, a column the 9:31am PDF had not filled yet.
    ONE list, data_gate's, so a new lagging section can't be missed here."""
    from automations.org_sales_board.data_gate import LAGGING_SECTIONS
    return [" ".join(w.upper() if len(w) <= 3 else w.title() for w in s.split())
            for s in LAGGING_SECTIONS]


_SECTION_TAG = "[board section: "


def late_sections(late: Sequence[str]) -> List[str]:
    """The board sections named by stale_sources() lines ('BOX')."""
    out: List[str] = []
    for s in late:
        for m in re.finditer(re.escape(_SECTION_TAG) + r"([^\]]+)\]", s):
            name = m.group(1).strip()
            if name and name not in out:
                out.append(name)
    return out


# A blank / zero / missing-day finding — the shape a late source leaves.
_LATE_SHAPE = re.compile(
    r"blank|empty|zero|\b0s?\b|missing|no (?:data|numbers|values|sales)|"
    r"behind|not (?:filled|updated)", re.I)


def excuse_late(issues: Sequence[dict], sections: Sequence[str]) -> list:
    """Blockers that are only a LATE source's blank/zero days become minors.

    Eve 2026-10-21: late Tableau never holds an email. The prompt says so too
    (LATE_SOURCES), but the 10/25 hold was exactly this finding — "BOX:
    Saturday 10/24 column blank for every owner; Friday all zeros too" — so
    the rule does not rest on the model reading it. Only for a section named
    late today and only for a blank/zero/missing-day finding: anything else in
    that table (style, #REF!, a cut-off crop) still blocks."""
    if not sections:
        return list(issues)
    pats = [re.compile(r"\b" + re.escape(s) + r"\b", re.I) for s in sections]
    out = []
    for i in issues:
        txt = f"{i.get('section', '')} {i.get('problem', '')}"
        if (i.get("severity") == "blocker" and _LATE_SHAPE.search(txt)
                and any(p.search(txt) for p in pats)):
            i = dict(i, severity="minor",
                     problem=f"{i.get('problem', '')} (Tableau behind — "
                             f"sent anyway)")
        out.append(i)
    return out


def stale_sources(t: Target, day: dt.date) -> List[str]:
    """Tableau sources flagged stale today that one of THIS email's jobs read."""
    chain = set(wr.dependency_closure([t.report_id]))
    want = {c.replace("-", "_") for c in chain}
    out: List[str] = []
    try:
        from automations.shared import tableau_freshness as tf
        for p in sorted(tf.STATE_DIR.glob(f"*-{day.isoformat()}.json")):
            try:
                st = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if not st.get("alerted"):
                continue
            used = {str(r).replace("-", "_") for r in st.get("reports") or []}
            sec_name = str(st.get("section") or "")
            if sec_name and t.sections is not None and sec_name.lower() not in {
                    x.lower() for x in t.sections}:
                continue          # a section this email doesn't show
            if used & want:
                # `section` = the board section a pull that judged itself
                # (org_sales_board.section_pull.note_lag — BOX) says is short;
                # judge() reads it back for the visual check (2026-10-25).
                sec = (f" {_SECTION_TAG}{st['section']}]"
                       if st.get("section") else "")
                out.append(f"{st.get('view') or p.stem} ({_stale_why(st)})"
                           f"{sec}")
    except Exception as e:  # noqa: BLE001
        print(f"  (Tableau sources: could not read the state — "
              f"{type(e).__name__}: {e})", flush=True)
    return out


# --------------------------------------------------------------------------
# 3. the images
# --------------------------------------------------------------------------
def structural_issues(t: Target, day: dt.date) -> List[str]:
    try:
        imgs = t.images(day)
    except Exception as e:  # noqa: BLE001 — no manifest IS the problem
        return [f"the email was not built ({str(e)[:120]})"]
    if not imgs:
        return ["the email has no images"]
    out = []
    empty = [n for n, p in imgs if not p.exists() or p.stat().st_size < 200]
    if empty:
        out.append(f"empty image(s): {', '.join(empty)}")
    old = [n for n, p in imgs if p.exists()
           and dt.date.fromtimestamp(p.stat().st_mtime) < day]
    if old:
        out.append(f"image(s) not built today: {', '.join(old)}")
    return out


def images_sha(t: Target, day: dt.date) -> str:
    h = hashlib.sha256()
    for n, p in t.images(day):
        h.update(n.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


# --------------------------------------------------------------------------
# 4. the visual check
# --------------------------------------------------------------------------
_SYSTEM = """You are the last check before a daily sales-board email goes out \
to the owners of a door-to-door sales organisation. A person used to open every \
one of these and approve it by hand; you now do that review. Each image is one \
screenshot cropped out of a Google Sheet. Decide if the email is fit to send.

The email reports REPORT_DAY (given below). Check:

1. MISSING DATA (blocker): a blank or nearly blank image, an image showing a \
login page / error / spinner, a table cut off mid-row or mid-column (a row or \
column sliced at the image edge, a table with no Totals row at its bottom), a \
box with its header but no rows.

2. LATEST DAY (blocker): a table laid out one column per DAY of the week must \
have numbers in the REPORT_DAY column. A REPORT_DAY column whose cells are ALL \
blank while the earlier days have numbers is a blocker. Days AFTER REPORT_DAY \
being blank or zero is normal (the week is not over). Weekly / leaderboard \
tables (one column per week, "WE m.d") do not need a day column.
KNOWN EXCEPTIONS, never blockers: a table for a section listed under \
DAY_BEHIND below, one day behind (its source publishes a day late, so its \
REPORT_DAY column is blank or zero, for every owner, new owners included); \
on a Sunday REPORT_DAY a quiet, all-zero day; on a \
Monday REPORT_DAY a new week whose only filled column is Monday; a table for \
a section listed under LATE_SOURCES below — its Tableau source is behind \
today, so its newest day columns being blank or all zero is expected (a minor \
at most).

3. NUMBER FORMAT (blocker): inside one column the numbers share one format. \
Flag raw long decimals (0.4285714) where the rest show %, date serials \
(45934), "#REF!", "#N/A", "#DIV/0!", "#VALUE!", "#ERROR!", "Loading...".

4. STYLE (blocker): a row or box whose font, font size, colours, borders or \
alignment clearly differ from the rest of its table (looks pasted in), \
overlapping or clipped text, a header that lost its colour band.

5. COPIED NUMBERS (blocker): two different tables or sections showing the same \
figures cell for cell where they measure different things.

6. NEW OWNERS (blocker): NEW_OWNERS below lists people added to the board \
today. For each, find their row in every table that lists owners and check it \
is complete: the name is not cut off, every day column up to REPORT_DAY has a \
value (0 counts as a value; in a DAY_BEHIND table only up to the day before \
REPORT_DAY), the week total and the LAST WEEK cells are filled \
(a new person's last week must read 0 or a number, never blank), and their row \
is inside the crop — not sliced at the bottom edge, not left outside the image \
while the Totals row is in it. Name each person in the problem you report.

ACCEPTED, never an issue: zero values formatted like their neighbours; grey \
"no data" notes; a consistent house style you would have designed differently.

Report blockers (would refuse to send) and minors (would mention but still \
send). Refer to images by number and name the table. Be concrete ("Daily \
Sales: 10/6 column empty for every owner"), keep each problem to ~12 words, \
in English — they are posted to Slack as is. Several columns with the same \
fault are ONE issue."""

PROMPT_ID = hashlib.sha256(_SYSTEM.encode("utf-8")).hexdigest()[:8]


def _visual_content(t: Target, day: dt.date, new: Sequence[str],
                    late: Sequence[str] = ()) -> list:
    rd = day - dt.timedelta(days=1)
    secs = late_sections(late)
    content: list = [{"type": "text", "text": (
        f"REPORT_DAY: {rd:%A} {rd.month}/{rd.day}/{rd:%Y}\n"
        f"Board: {t.name}\n"
        f"NEW_OWNERS: {', '.join(new) if new else '(none today)'}\n"
        f"LATE_SOURCES: {', '.join(secs) if secs else '(none today)'}\n"
        f"DAY_BEHIND: {', '.join(day_behind_sections())}")}]
    for i, (name, p) in enumerate(t.images(day), 1):
        ctype, data = _shrink("image/png", p.read_bytes())
        content.append({"type": "text", "text": f"IMAGE {i} ({name}):"})
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": ctype,
            "data": base64.b64encode(data).decode("ascii")}})
    return content


def visual_review(t: Target, day: dt.date, new: Sequence[str] = (), *,
                  prior: Sequence[str] = (), late: Sequence[str] = (),
                  client=None) -> dict:
    """{'ok': bool, 'issues': [...]} — or raises when it could not run."""
    if client is None:
        anthropic, client = _api_client()
    else:
        anthropic = None
    body = {"output_config": {"effort": "high", "format": {
        "type": "json_schema", "schema": _SCHEMA}}}
    content = _visual_content(t, day, new, late)
    if prior:
        content.insert(1, {"type": "text", "text": (
            "AN EARLIER REVIEW OF THIS EMAIL TODAY FOUND THESE BLOCKERS. It was "
            "rebuilt since, but a rebuild re-reads the same board and often "
            "fixes nothing. Check each one again; if it is still there, report "
            "it again as a blocker:\n- " + "\n- ".join(prior))})
    messages = [{"role": "user", "content": content}]
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=8000, system=_SYSTEM, messages=messages,
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={**body, "fallbacks": "default"})
    except Exception as e:  # noqa: BLE001
        if anthropic is None or not isinstance(e, anthropic.BadRequestError):
            raise
        resp = client.messages.create(model=MODEL, max_tokens=8000,
                                      system=_SYSTEM, messages=messages,
                                      extra_body=body)
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"visual review did not finish ({resp.stop_reason})")
    out = json.loads("".join(b.text for b in resp.content
                             if getattr(b, "type", "") == "text"))
    out["ok"] = not [i for i in out.get("issues") or []
                     if i.get("severity") == "blocker"]
    return out


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------
@dataclass
class Verdict:
    fixable: List[str] = field(default_factory=list)
    blocked: List[str] = field(default_factory=list)
    minor: List[str] = field(default_factory=list)
    new: List[str] = field(default_factory=list)
    waiting: bool = False            # not built yet / Tableau still loading

    @property
    def send(self) -> bool:
        return not self.fixable and not self.blocked and not self.waiting

    def reasons(self) -> List[str]:
        return self.blocked + self.fixable


def judge(t: Target, day: dt.date, state: dict, *,
          clean=None, tableau=None, names=None, visual=None,
          verbose: bool = True) -> Verdict:
    clean = clean or (lambda: wr.day_is_clean([t.report_id], day))
    tableau = tableau or (lambda: stale_sources(t, day))
    names = names or (lambda: owner_names(t.grid()))
    late: List[str] = []    # filled below; the default visual reads it then
    visual = visual or (lambda new, prior: visual_review(t, day, new,
                                                         prior=prior,
                                                         late=late))
    v = Verdict()
    rebuilds = state.get("rebuilds", 0)

    # not built yet: the morning chain posts the board first; just wait.
    try:
        t.images(day)
    except Exception:  # noqa: BLE001
        v.waiting = True
        if verbose:
            print(f"  auto-check {t.key}: not built yet, waiting", flush=True)
        return v

    ok, why = clean()
    if not ok:
        v.blocked.append(f"the day's run is not clean: {why}")
    late[:] = [f"Tableau not updated: {s}" for s in tableau()]

    try:
        v.new = new_owners(t, day, names())
    except Exception as e:  # noqa: BLE001 — can't tell who is new: hold
        v.blocked.append(f"could not read the board's owner list "
                         f"({type(e).__name__}: {str(e)[:100]})")
    if v.blocked:
        state["held_upstream"] = True
        return _log(t, v, verbose)
    why_wait = t.wait_for(day) if t.wait_for else None
    if why_wait:
        # Same as a late Tableau: wait quietly, then rebuild once from the
        # board once it is in (held_upstream -> UPSTREAM_CLEARED below).
        state["held_upstream"] = True
        v.waiting = True
        if verbose:
            print(f"  auto-check {t.key}: waiting — {why_wait}", flush=True)
        return v
    if late:
        # Waits instead of holding: no link, no tag. `held_upstream` makes the
        # pass after Tableau loads rebuild from the fresh board (below).
        state["held_upstream"] = True
        if not past_tableau_deadline(day):
            v.waiting = True
            if verbose:
                print(f"  auto-check {t.key}: waiting for Tableau (until "
                      f"{TABLEAU_DEADLINE:%H:%M} CT) — {'; '.join(late)}",
                      flush=True)
            return v
        if not state.get("upstream_rebuilt"):
            v.fixable.append(TABLEAU_DEADLINE_REBUILD)
            return _log(t, v, verbose)
        # rebuilt at the cutoff with the latest: judged as it is from here
    elif state.get("held_upstream") and not state.get("upstream_rebuilt"):
        # Held earlier for the chain or Tableau, clear now: the email was built
        # from the board as it was THEN. Rebuild it once from today's board.
        v.fixable.append(UPSTREAM_CLEARED)
        return _log(t, v, verbose)

    struct = structural_issues(t, day)
    if not struct:
        try:
            struct = t.totals(day)
        except Exception as e:  # noqa: BLE001 — can't compare: say so, hold
            struct = [f"could not compare the board totals "
                      f"({type(e).__name__}: {str(e)[:100]})"]
    if struct:
        (v.blocked if rebuilds >= MAX_REBUILDS else v.fixable).extend(struct)
        return _log(t, v, verbose)

    sha = images_sha(t, day)
    cache = state.get("visual") or {}
    secs = late_sections(late)
    key = f"{sha}:{PROMPT_ID}:{','.join(v.new)}"
    if secs:   # told a section is late = a different question: ask again
        key += f":late={','.join(secs)}"
    res = cache.get("result") if cache.get("key") == key else None
    if res is None:
        try:
            res = visual(v.new, state.get("visual_flagged") or [])
            state["visual"] = {"key": key, "result": res,
                               "at": dt.datetime.now().isoformat(
                                   timespec="minutes")}
        except Exception as e:  # noqa: BLE001 — fail closed
            v.blocked.append(f"could not run the visual check "
                             f"({type(e).__name__}: {str(e)[:120]})")
            return _log(t, v, verbose)
    # 2026-10-25: a late section's blank/zero days are never a blocker.
    issues = excuse_late(res.get("issues") or [], secs)
    v.minor = [_issue_line(i) for i in issues if i.get("severity") != "blocker"]
    bad = [_issue_line(i) for i in issues if i.get("severity") == "blocker"]
    if bad:
        (v.blocked if rebuilds >= MAX_REBUILDS else v.fixable).extend(bad)
        state["visual_flagged"] = list(dict.fromkeys(
            (state.get("visual_flagged") or []) + bad))
    return _log(t, v, verbose)


def _log(t: Target, v: Verdict, verbose: bool) -> Verdict:
    if verbose:
        tag = ("OK" if v.send else
               "REBUILD" if v.fixable and not v.blocked else "HELD")
        extra = f" — new: {', '.join(v.new)}" if v.new else ""
        print(f"  auto-check {t.key}: {tag}"
              + (f" — {'; '.join(v.reasons())}" if v.reasons() else "")
              + extra, flush=True)
    return v


# --------------------------------------------------------------------------
# acting on it — the gate hands in its own Slack/send functions
# --------------------------------------------------------------------------
@dataclass
class Hooks:
    has_post: Callable[[], bool]          # today's review post exists?
    post_link: Callable[[bool], None]     # upload PDF + post link (True = FYI,
                                          # it is already going out)
    reply: Callable[[str, str], bool]     # (text, once-marker) -> posted?
    rebuild: Callable[[], None]           # preview + PDF again (same link)
    send: Callable[[], int]               # the reviewed send; rc
    confirm: Callable[[str], None]        # "Sent — approved by <who>"
    record: Callable[[Tuple[str, str]], None]   # Hub approval pill
    mentions: str


def _bullets(reasons: Sequence[str]) -> str:
    return "\n".join(f"• {r}" for r in reasons)


def run(t: Target, day: dt.date, hooks: Hooks, *, send: bool = True,
        verbose: bool = True, **judge_kw) -> int:
    """One pass of the auto-send. 0 = sent (or nothing left to do),
    1 = still waiting (not built / held / waiting for a ✅)."""
    state = load_state(t, day)
    if state.get("sent"):
        return 0
    v = judge(t, day, state, verbose=verbose, **judge_kw)
    save_state(t, day, state)
    if v.waiting:
        return 1

    if v.fixable and not v.blocked:
        if not send:
            return 1
        if set(v.fixable) <= {UPSTREAM_CLEARED, TABLEAU_DEADLINE_REBUILD}:
            state["upstream_rebuilt"] = True     # its own one rebuild
        else:
            state["rebuilds"] = state.get("rebuilds", 0) + 1
            state["rebuilt_for"] = v.fixable
        save_state(t, day, state)
        print(f"  auto-check {t.key}: rebuilding once — "
              f"{'; '.join(v.fixable)}", flush=True)
        hooks.rebuild()
        return 1          # the next pass judges the rebuilt email

    auto_day = wr.is_auto_send_day(day)
    if not v.send:
        if send:
            if not hooks.has_post():
                hooks.post_link(False)
            # One note per distinct set of reasons: the check runs every 15
            # minutes and must not repeat itself, but a NEW reason is news.
            ref = hashlib.sha256("|".join(v.reasons()).encode()).hexdigest()[:6]
            again = "Rebuilt once, still wrong. " if state.get("rebuilds") else ""
            hooks.reply(f"{hooks.mentions} ⚠️ *{HELD_MARK}* — not sent:\n"
                        f"{_bullets(v.reasons())}\n_{again}✅ the link to send "
                        f"it as is, or fix the board + `--refresh` (same "
                        f"link)._ (ref {ref})", f"(ref {ref})")
            _alert(t, day, v.reasons())
        return 1

    if v.new and not auto_day:
        # Eve 2026-10-07: a new owner is the day the crops can go wrong.
        if send:
            if not hooks.has_post():
                hooks.post_link(False)
            hooks.reply(f"{hooks.mentions} 🆕 *{NEW_OWNER_MARK}:* "
                        f"{', '.join(v.new)} — the auto-check passed, but "
                        f"check their rows in the screenshots. ✅ to send.",
                        NEW_OWNER_MARK)
        return 1

    if not send:
        return 0
    rebuilt = bool(state.get("rebuilds"))
    if (rebuilt or v.new) and not hooks.has_post():
        hooks.post_link(True)
    if v.new:
        hooks.reply(f"{hooks.mentions} 🆕 *{NEW_OWNER_MARK}:* "
                    f"{', '.join(v.new)} — {wr.day_label(day)}, so it went "
                    f"out on its own after the auto-check. Have a look at "
                    f"their rows.", NEW_OWNER_MARK)
    if rebuilt:
        hooks.reply(f"🔧 {REBUILT_MARK}: "
                    f"{'; '.join(state.get('rebuilt_for') or [])}",
                    REBUILT_MARK)
    who = (AUTO_ID, AUTO_WHO)
    hooks.record(who)
    rc = hooks.send()
    if rc == 0:
        state["sent"] = dt.datetime.now().isoformat(timespec="minutes")
        save_state(t, day, state)
        if hooks.has_post():
            hooks.confirm(who[1])
        _close(t, day)
    return rc


def incident_key(t: Target, day: dt.date) -> str:
    return f"board-autosend-{t.key}-{day.isoformat()}"


def _alert(t: Target, day: dt.date, reasons: Sequence[str]) -> None:
    try:
        from automations.shared import incident_thread as it
        rd = day - dt.timedelta(days=1)
        it.open_or_followup(
            key=incident_key(t, day),
            title=f"✉️ *{t.name} Email {rd.month}/{rd.day}* — not sent "
                  f"automatically",
            body=[_bullets(reasons), "",
                  "*What this means:* the email was held by the auto-check. "
                  "Its link is in today's thread in #revision-emails — a ✅ "
                  "there sends it as is.",
                  "*To fix it, ON LUCY 1:* correct the board, then "
                  "`review_gate --refresh` (same link); the 15-minute check "
                  "reviews it again. If it is Tableau being behind, wait for "
                  "the extract."],
            subjects=[f"{t.name}: {'; '.join(reasons)[:140]}"], day=day,
            label=f"{t.name} Email (auto-send)", needs_human=True)
        (STATE_DIR / t.key).mkdir(parents=True, exist_ok=True)
        (STATE_DIR / t.key / f"{day.isoformat()}.alerted").write_text(
            dt.datetime.now().isoformat(), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 — an alert never kills the check
        print(f"  (corrections alert skipped: {e})", flush=True)


def _close(t: Target, day: dt.date) -> None:
    """Close today's held-email thread AND any earlier day's still left open.

    An earlier day's hold used to close only if THAT day's email was sent. Once
    a newer email goes out, the old one is never sent (it would be stale), so
    its thread sat on "Needs one of you" for days after the cause was fixed —
    10/17 and 10/18 were still open on 10/19 after a clean send (Megan
    2026-10-19). A clean send today is the proof the hold is over."""
    try:
        from automations.shared import incident_thread as it
    except Exception as e:  # noqa: BLE001
        print(f"  (could not close the corrections thread: {e})", flush=True)
        return
    for marker in sorted((STATE_DIR / t.key).glob("*.alerted")):
        try:
            mday = dt.date.fromisoformat(marker.stem)
        except ValueError:
            continue
        if mday > day:
            continue
        detail = ("_The held email went out._" if mday == day else
                  f"_Superseded: the {day.month}/{day.day} email went out "
                  "clean. This older held copy was not re-sent — it would be "
                  "stale._")
        try:
            if it.ensure_closed(incident_key(t, mday),
                                what=f"*{t.name} Email* — sent",
                                detail=detail):
                marker.unlink()
        except Exception as e:  # noqa: BLE001
            print(f"  (could not close the corrections thread: {e})", flush=True)
