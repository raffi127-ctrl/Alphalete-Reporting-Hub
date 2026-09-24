"""Car-Rides Cleanup — OwnerVille territory reconciliation (Lucy 2, weekdays 9:30am CT).

Port of Carlos's Cowork scheduled task to a fully-unattended Lucy 2 automation.
Job: make each car-ride LEADER's territory in OwnerVille / TeleMapper match the
"Stations" tab of the Vantura Master Sales Board, for BOTH campaigns.

Reuses the existing Lucy 2 routes (do NOT rebuild these):
  * Board read      -> automations.recruiting_report.fill.open_by_key (gspread;
                       replaces the Cowork version's gviz-in-browser hack — both
                       machines hold Google API auth, so we read the tab directly)
  * OwnerVille auth -> automations.shared.tableau_patchright
                       (_launch_persistent + _ensure_ownerville_logged_in): the
                       exported session that session_holder keeps warm on Lucy 2.
                       NO human, NO login form: if the session is missing/stale
                       this run FLAGS it and stops (never touches the Turnstile).

WHAT A RUN DOES:
  1. Read the Stations car-ride boxes (rows 5-25 AT&T, 28-38 BOX) -> leader ->
     [riders], locating the Leader / Rep #1-4 columns BY HEADER (not position).
  2. Open v2.ownerville.com Territory Assignment (index.cfm?p=158), campaign
     "B2B AT&T SBS" then "B2B-BOX-Energy".
  3. Enumerate every territory (all pages). Compute the reconciliation plan:
     adds / removes per leader territory, missing-territory flags, stale-leader
     territories to empty, one-rep-one-car-ride dedupes.
  4. --dry-run (DEFAULT): print the full plan, write state + report, change NOTHING.
     --live: apply the plan (select2 add/remove + Save, Escape-before-Save),
     re-read each edited territory to verify, retry a missed Save once.
  5. Persist state to output/car_rides/ (run-log.jsonl, open-flags.json,
     last-report.md) — open-flags feeds the 2-run stale rule next run.

RULES (unchanged from the Cowork task):
  * One rep, one car ride — remove a correctly-placed rep from other territories.
  * No territory for a leader -> FLAG "needs new team"; only Carlos creates.
  * Leave road trips ("RT ...", old date ranges) + location/zip-named territories
    + Unassigned/Open alone.
  * Stale leader (not in either sheet box) -> empty the territory's riders.
    Whole-territory Remove is deliberately FLAG-ONLY in this port (even when
    empty + previously flagged) — Carlos removes; the flag tells him it's ready.
  * NEVER: create territories, hard-delete, touch "Assign Clients", change
    sharing, enter credentials, post to Slack. When unsure -> flag.

  python -m automations.car_rides.run                # dry-run (default)
  python -m automations.car_rides.run --probe        # dump selector/DOM evidence
  python -m automations.car_rides.run --live         # apply the plan
  python -m automations.car_rides.run --campaign att # one campaign only
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

REPORT_ID = "car-rides"


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for anc in here.parents:
        if (anc / "automations" / "day_orchestrator").is_dir():
            return anc
    return here.parents[2]


REPO_ROOT = _find_repo_root()
STATE_DIR = REPO_ROOT / "output" / "car_rides"

# The id everything else already calls this report: the schedule_config key,
# the wrapper's publish_done, `lucy rerun car_rides`, and now its manifest.
REPORT_ID = "car_rides"

# --- Source of truth ---------------------------------------------------------
SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"   # Vantura Master Sales Board
STATIONS_GID = 1999003555
# The car-ride box is one "Territory Leader" column + the "Rep #1..4" columns.
# Header rows are 5 (AT&T) and 28 (BOX); everything past the rep columns is the
# station matrix and must stay out of the read.
# Columns are located BY HEADER, not by position — the box just has to be inside
# this range. 2026-08-12: a "Territory Status" column was inserted at A, pushing
# Territory Leader to B; the old positional read (A5:E25, "col A = leader") then
# read the STATUS as the leader, the real leader as Rep #1, and dropped Rep #4
# entirely. Widened through G so "Rep List" is visible to the header scan (and
# explicitly excluded — it is a spill formula, not a car-ride rider).
# Stations tab re-laid-out 2026-09-03 (Carlos): stations stacked UNDER the
# car rides, Rep #4 dropped, boxes tightened. Headers still found by name.
# Ride boxes sized leaders-minus-2 (Carlos 2026-09-03 pm): ATT 9 rows,
# BOX 11. Headers still found by name inside the range.
BOXES = {
    "att": {"range": "A5:E14",  "campaign": "B2B AT&T SBS"},
    "box": {"range": "A30:E41", "campaign": "B2B-BOX-Energy"},  # 9/4: BOX moved up 2 (daily A53 lineup-writer collision)
}
LEADER_HDR_RE = re.compile(r"leader", re.I)
# "Rep #1".."Rep #4" — the trailing digit is what keeps "Rep List" out.
RIDER_HDR_RE = re.compile(r"rep\s*#?\s*\d+", re.I)

OWNERVILLE_TERRITORY_URL = "https://v2.ownerville.com/index.cfm?p=158"

# --- Name matching -----------------------------------------------------------
# OwnerVille shows full legal names; the board uses short names. Match on FIRST
# name + alias groups, never exact string. Known aliases (from the Cowork task):
#   Didi ~ Ndifreke (leader); rider Nimo = "Warimu (Nimo) Mwangi";
#   Jayden Luna = Jayden Willingham ("Jayden W."); Melanie = Melanie Hernandez.
ALIAS_GROUPS = [
    {"didi", "ndifreke"},
    {"nimo", "warimu", "wairimu"},      # OwnerVille spells it Wairimu
    {"jayden", "luna", "willingham"},
    {"melanie", "hernandez"},
]

# Common nickname equivalences — OwnerVille shows legal first names + a last
# initial ("William B."), the board uses short names ("Will Bautista").
# Verified against the live p=158 list 2026-07-15 (Will/William B.,
# Nick/Nicholas S. were false mismatches before this).
NICKNAME_GROUPS = [
    {"will", "william", "willy", "bill", "billy"},
    {"nick", "nicholas", "nico", "nicky"},
    {"jake", "jacob"},
    {"greg", "gregory"},
    {"jon", "jonathan", "jonathon", "john", "johnny"},
    {"alex", "alexander", "alejandro"},
    {"gio", "giovanni"},
    {"dan", "daniel", "danny"},
    {"matt", "matthew"},
    {"mike", "michael"},
    {"chris", "christopher", "christian"},
    {"tony", "antonio", "anthony"},
    {"eric", "erik"},
    {"beca", "rebeca", "rebecca"},
]

# Territory names to leave alone: road trips, location/zip names, unassigned.
SKIP_NAME_PATTERNS = [
    r"^rt\b",                # "RT ..."
    r"\b\d{5}\b",            # zip code in the name ("02780 06/5 (840)")
    r"\d{1,2}/\d{1,2}",      # date-suffixed place names ("west warwick 04/13")
    r"\b\d{1,2}\.\d{1,2}\b", # dotted-date names ("Jonathon 4.28")
    r"^unassigned\b",
    r"^open\b",
]


def _log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}",
          flush=True)


def _norm(s: str) -> str:
    s = re.sub(r"\(([^)]*)\)", r" \1 ", s or "")      # keep "(Nimo)" as a token
    return re.sub(r"[^a-z ]+", " ", s.lower()).strip()


def _tokens(s: str) -> set[str]:
    return set(_norm(s).split())


def _tok_eq(a: str, b: str) -> bool:
    """One name token vs another. Single letters (last initials) NEVER match —
    they'd pair everyone with everyone. Beyond exact: alias/nickname groups,
    prefix (Luisa/Luis), and small-typo fuzz (Warimu/Wairimu)."""
    if len(a) < 2 or len(b) < 2:
        return False
    if a == b:
        return True
    for grp in ALIAS_GROUPS + NICKNAME_GROUPS:
        if a in grp and b in grp:
            return True
    if len(a) >= 4 and len(b) >= 4:
        if a.startswith(b) or b.startswith(a):
            return True
        import difflib
        if difflib.SequenceMatcher(None, a, b).ratio() >= 0.85:
            return True
    return False


def names_match(board_name: str, ov_name: str) -> bool:
    """Board short name ("Will Bautista") vs OwnerVille display name
    ("William B."): ANY strong token match (see _tok_eq)."""
    bt, ot = _tokens(board_name), _tokens(ov_name)
    return any(_tok_eq(a, b) for a in bt for b in ot)


def is_skip_territory(name: str) -> bool:
    low = (name or "").strip().lower()
    return any(re.search(p, low) for p in SKIP_NAME_PATTERNS)


# --- Step 1: read the Stations tab ------------------------------------------
def read_expected(log=_log) -> dict[str, dict[str, list[str]]]:
    """-> {"att": {leader: [riders]}, "box": {...}} from the live board."""
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(SHEET_ID)
    ws = next((w for w in sh.worksheets() if w.id == STATIONS_GID), None)
    if ws is None:
        ws = sh.worksheet("Stations")
    out: dict[str, dict[str, list[str]]] = {}
    for key, box in BOXES.items():
        rows = ws.get(box["range"]) or []
        if not rows:
            raise RuntimeError(f"Stations {box['range']} came back empty — "
                               "range/tab drift, refusing to reconcile.")
        header = [str(c).strip().lower() for c in rows[0]]
        # Find the columns by NAME. The old check only asked whether "leader"
        # appeared ANYWHERE in the header, which is exactly why the 2026-08-12
        # column insert sailed through it: 'Territory Leader' was still present,
        # just no longer in column 0.
        lead_i = next((i for i, h in enumerate(header) if LEADER_HDR_RE.search(h)),
                      None)
        rider_i = [i for i, h in enumerate(header) if RIDER_HDR_RE.search(h)]
        if lead_i is None or not rider_i:
            raise RuntimeError(
                f"Stations {box['range']} header row is {rows[0]!r} — expected a "
                "'Territory Leader' column and 'Rep #1..4' columns. Box moved; "
                "fix BOXES.")
        exp = {}
        for r in rows[1:]:
            # gspread trims trailing empties, so rows are ragged — index-check.
            leader = str(r[lead_i]).strip() if len(r) > lead_i else ""
            if not leader:
                continue
            riders = [str(r[i]).strip() for i in rider_i
                      if len(r) > i and str(r[i]).strip()]
            exp[leader] = riders
        out[key] = exp
        log(f"{key.upper()} box: {len(exp)} leaders — " +
            "; ".join(f"{l} +{len(rs)}" for l, rs in exp.items()))
    return out


# --- OwnerVille session (unattended, flag-don't-login) -----------------------
class SessionGone(RuntimeError):
    """OwnerVille session missing/stale on this machine — flag, never re-auth."""


def _open_ownerville(p, headless: bool, verbose: bool):
    """-> (ctx, page) logged into ownerville via the exported storage_state.
    Raises SessionGone when unattended auth is impossible (no form fallback)."""
    from automations.shared import tableau_patchright as tp
    tp.PROFILE_DIR.mkdir(exist_ok=True, parents=True)
    ctx = tp._launch_persistent(p, tp.PROFILE_DIR, headless=headless,
                                label="car_rides", verbose=verbose,
                                window_size=(1680, 1050))
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        tp._ensure_ownerville_logged_in(page, verbose=verbose,
                                        allow_form_login=False)
    except RuntimeError as e:
        ctx.close()
        raise SessionGone(str(e))
    return ctx, page


# --- Step 2: territory list extraction ---------------------------------------
# DOM facts pinned against the LIVE p=158 page 2026-07-15 (driven read-only via
# Carlos's Chrome): the left panel is DataTable #territoryTable (cols Name |
# Sales Rep(s) | Start/End Date | Locations); its DataTables API returns EVERY
# page's rows at once. The top-right campaign switcher is a dropdown of plain
# <a> links (B2B AT&T SBS / B2B-BOX-Energy / BASE Energy); picking one reloads
# with &invD2DClientId=<id> (BOX=16). p=158 itself needs the live rqst token in
# the URL or it bounces to Welcome (p=2) — mint it from v2 first.
_HARVEST_JS = r"""
() => {
  const row = tr => {
    const tds = [...tr.querySelectorAll('td')];
    return {name: (tds[0]?.innerText || '').trim(),
            reps: tds[1] ? tds[1].innerText.split('\n').map(s => s.trim()).filter(Boolean) : []};
  };
  try {
    if (window.$ && $.fn.dataTable && $('#territoryTable').length) {
      return {via: 'datatables-api',
              rows: $('#territoryTable').DataTable().rows().nodes().toArray().map(row)};
    }
  } catch (e) {}
  return {via: 'tbody',
          rows: [...document.querySelectorAll('#territoryTable tbody tr')].map(row)};
}
"""

_CAMPAIGN_RX = r"^(B2B AT&T SBS|B2B-BOX-Energy|BASE Energy)$"
_CURRENT_CAMPAIGN_JS = (
    "() => { const e = [...document.querySelectorAll('span,a')]"
    ".find(x => /" + _CAMPAIGN_RX.replace("/", r"\/") + r"/.test((x.innerText||'').trim())"
    " && x.offsetParent !== null); return e ? e.innerText.trim() : ''; }")


def goto_territory_assignment(page, log=_log) -> None:
    """v2 mints a fresh rqst from the login cookie; p=158 needs it in the URL
    (a bare p=158 bounces to the Welcome page)."""
    page.goto("https://v2.ownerville.com/index.cfm", wait_until="domcontentloaded")
    page.wait_for_timeout(6_000)
    m = re.search(r"rqst=([A-Za-z0-9_]+)", page.url or "")
    if not m:
        href = page.evaluate(
            "() => { const a=[...document.querySelectorAll('a')]"
            ".find(x=>/rqst=/.test(x.getAttribute('href')||'')); "
            "return a?a.getAttribute('href'):''; }")
        m = re.search(r"rqst=([A-Za-z0-9_]+)", href or "")
    if not m:
        raise RuntimeError("no rqst token on v2 — session not genuinely live")
    page.goto(f"https://v2.ownerville.com/index.cfm?p=158&rqst={m.group(1)}",
              wait_until="domcontentloaded")
    page.wait_for_timeout(10_000)


# Campaign -> the invD2DClientId the page reloads with when that campaign is
# picked (observed live 2026-07-15: default/no param = B2B AT&T SBS, BOX = 16).
# URL-param navigation is deterministic — no dropdown driving, which timed out
# under headless patchright on Lucy 2 (2026-07-16 run).
CAMPAIGN_URL_IDS = {"B2B AT&T SBS": None, "B2B-BOX-Energy": 16}


def _select_campaign(page, campaign: str, log=_log) -> bool:
    """Show `campaign` in Territory Assignment by URL parameter (primary),
    falling back to a JS click on the dropdown <a>. True when switched."""
    m = re.search(r"rqst=([A-Za-z0-9_]+)", page.url or "")
    cid = CAMPAIGN_URL_IDS.get(campaign)
    if m and campaign in CAMPAIGN_URL_IDS:
        url = f"https://v2.ownerville.com/index.cfm?p=158&rqst={m.group(1)}"
        if cid is not None:
            url += f"&invD2DClientId={cid}"
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(10_000)
            cur = page.evaluate(_CURRENT_CAMPAIGN_JS)
            if cur == campaign or cur == "":
                # '' = toolbar text not found headless; the URL param is the
                # source of truth, so proceed (rows are verified downstream).
                return True
            log(f"campaign via URL: toolbar shows {cur!r}, wanted {campaign!r}")
        except Exception as e:
            log(f"campaign via URL failed: {e!r}")
    # Fallback: JS-click the dropdown control, then the campaign <a>.
    try:
        opened = page.evaluate(
            "() => { const e=[...document.querySelectorAll('span,a,button')]"
            ".find(x=>/^(B2B AT&T SBS|B2B-BOX-Energy|BASE Energy)$/"
            ".test((x.innerText||'').trim())); if(!e) return false; "
            "e.click(); return true; }")
        page.wait_for_timeout(1_500)
        clicked = opened and page.evaluate(
            "(c) => { const a=[...document.querySelectorAll('a')]"
            ".find(x=>(x.innerText||'').trim()===c); if(!a) return false; "
            "a.click(); return true; }", campaign)
        page.wait_for_timeout(8_000)
        if clicked and page.evaluate(_CURRENT_CAMPAIGN_JS) in (campaign, ""):
            return True
        log(f"campaign switch fallback failed (opened={opened}, clicked={clicked})")
    except Exception as e:
        log(f"campaign switch to {campaign!r} failed: {e!r}")
    return False


def list_territories(page, log=_log) -> list[dict]:
    """All territories, every page at once, via the DataTables API."""
    info = page.evaluate(_HARVEST_JS)
    got = [r for r in info.get("rows", []) if r.get("name")]
    log(f"territory list: {len(got)} entries via {info.get('via')}")
    return got


# --- Step 3: the reconciliation plan -----------------------------------------
def plan_campaign(expected: dict[str, list[str]], territories: list[dict],
                  prev_flags: list[str], log=_log) -> dict:
    """Pure function: expected map + harvested territories -> plan dict."""
    plan = {"edits": [], "flags": [], "skipped": []}
    active = [t for t in territories if not is_skip_territory(t["name"])]
    for t in territories:
        if is_skip_territory(t["name"]):
            plan["skipped"].append(t["name"])

    def find_territory(leader: str):
        cands = [t for t in active
                 if names_match(leader, t["name"])
                 or any(names_match(leader, r) for r in t["reps"])]
        return cands[0] if len(cands) == 1 else (cands or None)

    # Resolve every leader FIRST. A territory that 2+ leaders resolve to means
    # the board's leadership moved (e.g. yesterday's leader is today's rider —
    # Diego/Sebastian/Luis, 2026-07-18): editing it from each leader's
    # perspective would thrash the same territory with conflicting add/removes.
    # Contested territories are FLAGGED for Carlos and never auto-edited.
    resolved = {leader: find_territory(leader) for leader in expected}
    territory_claims: dict[str, list[str]] = {}
    for leader, t in resolved.items():
        if isinstance(t, dict):
            territory_claims.setdefault(t["name"], []).append(leader)
    contested = {n for n, ls in territory_claims.items() if len(ls) > 1}
    for n in contested:
        plan["flags"].append(
            f"territory {n!r} matches multiple board leaders "
            f"({', '.join(territory_claims[n])}) — leadership changed; "
            "needs Carlos, no auto-edit")

    claimed: dict[str, str] = {}   # normalized rep -> leader who owns them
    for leader, riders in expected.items():
        t = resolved[leader]
        if t is None:
            plan["flags"].append(f"{leader}: no territory found — needs new "
                                 "team (Carlos to create)")
            continue
        if isinstance(t, list):
            plan["flags"].append(
                f"{leader}: {len(t)} candidate territories "
                f"({', '.join(x['name'] for x in t[:4])}) — ambiguous, skipped")
            continue
        want = [leader] + riders
        for w in want:
            claimed[_norm(w)] = leader
        if t["name"] in contested:
            continue                       # flagged above; never auto-edit
        adds = [w for w in want if not any(names_match(w, r) for r in t["reps"])]
        removes = [r for r in t["reps"]
                   if not any(names_match(w, r) for w in want)]
        if adds or removes:
            plan["edits"].append({"territory": t["name"], "leader": leader,
                                  "add": adds, "remove": removes})

    # One rep, one car ride + stale-leader territories.
    for t in active:
        if t["name"] in contested:
            continue                       # flagged above; never auto-edit
        owner = next((l for l in expected if names_match(l, t["name"])
                      or any(names_match(l, r) for r in t["reps"])), None)
        if owner:
            strays = [r for r in t["reps"]
                      for w, l in claimed.items()
                      if l != owner and names_match(w, r)
                      and not any(names_match(x, r)
                                  for x in [owner] + expected[owner])]
            for s in set(strays):
                plan["edits"].append({"territory": t["name"], "leader": owner,
                                      "add": [], "remove": [s],
                                      "why": "one-rep-one-car-ride"})
            continue
        # Leader not in either box -> stale: empty riders, flag (Remove is
        # flag-only in this port, even under the old 2-run rule). A rep the
        # board DOES want elsewhere is not removed here — they move via their
        # new leader's edit; removing first would strand them in no car ride
        # if that edit is contested/skipped (Eddy under giovanni, 2026-07-18).
        if t["reps"]:
            unwanted = [r for r in t["reps"]
                        if not any(names_match(w, r) for w in claimed)]
            kept = [r for r in t["reps"] if r not in unwanted]
            if unwanted:
                plan["edits"].append({"territory": t["name"], "leader": None,
                                      "add": [], "remove": unwanted,
                                      "why": "stale leader — empty the territory"})
            plan["flags"].append(
                f"stale territory {t['name']!r}: leader not on the board; "
                f"removing {unwanted or 'nothing'}"
                + (f"; leaving {kept} (wanted elsewhere on the board)"
                   if kept else ""))
        else:
            prior = any(t["name"] in f for f in prev_flags)
            plan["flags"].append(
                f"empty stale territory {t['name']!r} — "
                + ("flagged LAST run too; ready for Carlos to Remove"
                   if prior else "first sighting; will confirm next run"))
    return plan


# --- Step 3b: is this plan even plausible? ------------------------------------
# A bad board read doesn't fail loudly — it makes every real territory look
# leaderless, and the stale rule then strips the riders out of all of them.
# 2026-08-12: the inserted "Territory Status" column meant the run parsed 2 of 6
# leaders and planned to empty 17 live territories; the ONLY reason nothing was
# destroyed is that every Playwright edit happened to throw. So before applying
# anything, sanity-check the plan against the campaign as a whole. A genuine day
# retires a couple of car rides; it does not retire most of them at once.
STALE_ABORT_FRACTION = 0.5
STALE_ABORT_FLOOR = 3          # below this, "most of them" isn't meaningful


def stale_sanity(expected: dict, territories: list[dict], plan: dict) -> str | None:
    """None = safe to apply. A string = why live edits must be refused.

    Vetoes the WHOLE campaign, not just the stale edits: if the board read is
    wrong then the adds and one-rep-one-car-ride removes are equally suspect."""
    if not expected:
        return "board read returned 0 leaders"
    active = [t for t in territories if not is_skip_territory(t["name"])]
    if not active:
        return None
    stale = {e["territory"] for e in plan["edits"]
             if str(e.get("why", "")).startswith("stale leader")}
    limit = max(STALE_ABORT_FLOOR, int(len(active) * STALE_ABORT_FRACTION))
    if len(stale) >= limit:
        return (f"{len(stale)} of {len(active)} territories parsed as stale "
                f"(limit {limit}) from only {len(expected)} board leaders — "
                "that is a bad board read, not a real day")
    return None


# --- Step 4: apply (live only) ------------------------------------------------
def _modal_open(page) -> bool:
    """Is the Edit Layer modal currently covering the page?

    Clicking a territory row either opens that modal or merely zooms the map,
    which is why a second click existed. But the second click was UNCONDITIONAL,
    so on the normal path it landed on the row BEHIND the modal the first click
    had just opened, was intercepted, and timed out after 30s — throwing before
    a single chip was touched. 2026-08-12: 17 of 17 territories failed exactly
    this way ("element is visible, enabled and stable" + a modal intercepting
    pointer events), so the job had been reporting without ever applying."""
    try:
        return bool(page.evaluate(
            "() => [...document.querySelectorAll("
            "'.modal, [class*=modal], [id*=modal], [id*=Modal]')]"
            ".some(e => e.offsetParent !== null"
            " && e.getBoundingClientRect().height > 80)"))
    except Exception:  # noqa: BLE001 — a probe must never break the edit
        return False


# THE CONTROL WE EDIT, AND ONLY IT. The Edit Layer modal holds THREE multi-
# selects — "Assigned Sales Rep(s)" (.territoryAssignedUsers), "Car Ride Captain
# (Optional)" (.carRideCaptain) and "Guest Pass Rep(s) (Optional)"
# (.guestPassOtherOfficeUsers, disabled). Every locator below hangs off this one
# so a chip can never be removed from, or a rep added to, the wrong field —
# `.first` across the whole modal was one DOM re-order away from doing exactly
# that. select2 renders its UI as the immediate sibling of the original <select>.
ASSIGNED_REPS = ("#territoryModal select.territoryAssignedUsers "
                 "+ .select2-container")

# NO TAG PREFIX ON THE SEARCH BOX, AND THIS IS THE WHOLE BUG (2026-09-24).
# This module looked for `input.select2-search__field, .select2-search input`.
# OwnerVille runs select2 4.1, whose MULTI-select search box is a
# `<textarea class="select2-search__field">` — an <input> selector can never
# match it, so every `add` waited the full 30s and threw. Removes, which never
# touch this box, went through fine. That is the whole story of the run-log:
# 519 runs since 2026-07-16 and 46 edits applied, every one of them remove-only
# (stale-leader empties, one-rep-one-car-ride). The cleanup has never once added
# a rep to a territory. Matching on the CLASS alone works on both spellings and
# survives the next select2 bump.
SEARCH_FIELD = ".select2-search__field"

# Every modal dismiss control OwnerVille's Edit Layer offers, scoped INSIDE
# the modal so nothing on the page behind it can ever be clicked by mistake.
_MODAL_CLOSE = (".modal button.close, .modal [data-dismiss=modal], "
                ".modal [aria-label='Close'], .modal [aria-label='close']")


def _dismiss_modal(page, log=_log) -> bool:
    """True = nothing is covering the page any more.

    THE CASCADE THIS ENDS (2026-09-24). Both failure paths in apply_edit used to
    return False with the Edit Layer modal STILL OPEN, and the next territory's
    `row.click()` was then intercepted by it. So ONE bad edit failed every edit
    behind it: on the 10:30 pass, `rodolfo` timed out waiting for the select2
    search box and andrew / fernando / andrew / tara / joelle / nathaly / becky
    all died on "<div id=territoryModal> intercepts pointer events" — 8 flags,
    0 edits applied, and 4 minutes of the pass spent on 30-second timeouts that
    could never have succeeded.

    Escape twice on purpose: inside an open select2 the first press closes the
    DROPDOWN and the modal stays put. The close control is scoped to `.modal`
    (see _MODAL_CLOSE) so a miss can never land on the page behind it.

    Nothing here saves: dismissing is how a half-finished edit is ABANDONED,
    which is the behaviour the caller already wants when it flags instead of
    retrying blind."""
    if not _modal_open(page):
        return True
    for step in ("escape", "escape", "close", "escape"):
        try:
            if step == "escape":
                page.keyboard.press("Escape")
            else:
                # Every dismiss control in this modal reports shown:false while
                # the edit pane is up, so this click often just times out. It
                # costs 2s and sometimes works; the caller's reload is the
                # guarantee, not this.
                page.locator(_MODAL_CLOSE).first.click(timeout=2_000)
            page.wait_for_timeout(900)
        except Exception:  # noqa: BLE001 — try the next way out
            pass
        if not _modal_open(page):
            return True
    log("  a modal is still covering the page and will not close")
    return False


def _pick_option(rep: str, texts: list) -> list:
    """Which dropdown option IS this person? Indexes; 1 = go, anything else = flag.

    names_match alone is the WRONG instrument here and the first live run proved
    it (2026-09-24): it is deliberately loose — "ANY strong token match", built
    to find a TERRITORY from a leader's short name — so board "Michelle Flores"
    matched both "Michelle Flores" and "Kandice Michelle Flores" and the edit
    flagged rather than guess. Right call, wrong question: one of those two IS
    the exact person.

    So it asks in order of confidence and stops at the first rung that answers
    with exactly one name:
      1. the same name, normalised  ("Michelle Flores" -> "Michelle Flores")
      2. every token of the board name present in the option (a middle name or
         a "Jr" on OwnerVille's side, e.g. "Gavin Natividad" ->
         "Gavin Dimitri Natividad")
      3. names_match, which still buys nicknames, initials and small typos

    A rung that matches two people does NOT fall through to a looser one — it
    stops, because a tie at high confidence is a real ambiguity and the looser
    rung can only widen it."""
    exact = [i for i, t in enumerate(texts) if _norm(t) == _norm(rep)]
    if exact:
        return exact
    want = _tokens(rep)
    subset = [i for i, t in enumerate(texts) if want and want <= _tokens(t)]
    if subset:
        return subset
    return [i for i, t in enumerate(texts) if names_match(rep, t)]


def apply_edit(page, edit: dict, log=_log) -> bool:
    """Open one territory, add/remove chips, Escape, Save, verify. True=verified.
    Conservative: any element we can't confidently find -> False (caller flags)."""
    name = edit["territory"]
    # A modal left over from the edit BEFORE this one would intercept the row
    # click and burn 30s per territory. Fail in about two seconds instead.
    if not _dismiss_modal(page, log):
        log(f"  open {name!r}: an earlier modal is still covering the page")
        return False
    try:
        row = page.get_by_text(name, exact=False).first
        row.click()
        page.wait_for_timeout(2_500)
        if not _modal_open(page):
            row.click()                      # the first click only zoomed the map
            page.wait_for_timeout(2_500)
        if not _modal_open(page):
            # Fail in ~5s with a real reason instead of burning 30s on a click
            # the modal was always going to intercept.
            log(f"  open {name!r}: no Edit Layer modal after two clicks")
            return False
    except Exception as e:
        log(f"  open {name!r} failed: {e!r}")
        _dismiss_modal(page, log)
        return False
    ctr = page.locator(ASSIGNED_REPS)
    try:
        for rep in edit.get("remove", []):
            chip = ctr.locator(
                f"li.select2-selection__choice:has-text({json.dumps(rep.split()[0])})").first
            chip.locator("span.select2-selection__choice__remove, .remove, "
                         "[aria-label*=remove i]").first.click()
            page.wait_for_timeout(800)
            log(f"  removed chip {rep!r}")
        for rep in edit.get("add", []):
            # The box only exists to be typed in once the control is OPEN.
            ctr.locator(".select2-selection").first.click()
            page.wait_for_timeout(400)
            box = ctr.locator(SEARCH_FIELD).first
            box.fill(rep.split()[0])
            page.wait_for_timeout(1_500)
            # ONE MATCH OR NOTHING. The old code typed a FIRST NAME and clicked
            # `.first`, so two Andrews on the roster meant adding whichever the
            # list happened to put on top — to a car ride, silently. The filter
            # still uses the first name (that is what narrows the list); the
            # PICK is _pick_option's, and an ambiguous or empty result flags
            # instead of guessing. Scoped to the OPEN dropdown: select2 appends
            # it to <body>, not inside the modal.
            opts = page.locator(
                ".select2-container--open .select2-results__option")
            texts = [opts.nth(i).inner_text().strip()
                     for i in range(min(opts.count(), 20))]
            hits = _pick_option(rep, texts)
            if len(hits) != 1:
                raise RuntimeError(
                    "{!r} matched {} of {} option(s) in Assigned Sales Rep(s) "
                    "({}) — refusing to guess which person that is".format(
                        rep, len(hits), len(texts),
                        "; ".join(texts[:4]) or "no options"))
            opts.nth(hits[0]).click()
            page.keyboard.press("Escape")    # select2 gotcha: close BEFORE Save
            page.wait_for_timeout(500)
            log(f"  added {rep!r} as {texts[hits[0]]!r}")
        page.keyboard.press("Escape")
        page.get_by_role("button", name=re.compile(r"^save$", re.I)).first.click()
        page.wait_for_timeout(3_000)
        return True
    except Exception as e:
        log(f"  edit {name!r} failed mid-way: {e!r} — flagging, NOT retrying blind")
        _dismiss_modal(page, log)          # or it fails every edit behind it
        return False


# --- state + report -----------------------------------------------------------
# Full report also goes to a tab on the control workbook — the queue's Result
# cell truncates (~470 chars), and this is the established rich-output channel
# (same pattern as RP Diag). Best-effort: a sheet hiccup never fails the run.
CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
REPORT_TAB = "Car Rides Report"


def _publish_report_tab(report: str, log=_log) -> bool:
    """True = the report tab on the control workbook now holds this run's report.

    Returns a verdict instead of nothing (2026-09-24) because that tab is one of
    the two things this report DELIVERS — it is where Carlos reads the flags —
    and the manifest cannot claim a delivery it did not check. Still best-effort:
    a sheet hiccup is recorded, never raised."""
    try:
        import gspread as _gs
        from automations.recruiting_report import fill as _fill
        sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
        try:
            ws = sh.worksheet(REPORT_TAB)
            ws.clear()
        except _gs.WorksheetNotFound:
            ws = sh.add_worksheet(title=REPORT_TAB, rows=200, cols=2)
        lines = report.splitlines() or [""]
        ws.update([[l] for l in lines], f"A1:A{len(lines)}",
                  value_input_option="RAW")
        log(f"report published to sheet tab {REPORT_TAB!r} ({len(lines)} lines)")
        return True
    except Exception as e:  # noqa: BLE001 — reporting must never fail the run
        log(f"report tab publish skipped: {e!r}")
        return False


def _load_prev_flags() -> list[str]:
    f = STATE_DIR / "open-flags.json"
    try:
        return list(json.loads(f.read_text()))
    except Exception:
        return []


def _persist(report: str, changes: dict[str, int], flags: list[str]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "run-log.jsonl").open("a") as fh:
        fh.write(json.dumps({"ts": dt.datetime.now().isoformat(timespec="seconds"),
                             "att_changes": changes.get("att", 0),
                             "box_changes": changes.get("box", 0),
                             "flags": flags}) + "\n")
    (STATE_DIR / "open-flags.json").write_text(json.dumps(flags, indent=1))
    (STATE_DIR / "last-report.md").write_text(report)


# --- delivery proof -----------------------------------------------------------
def _file_manifest(*, live: bool, failures: list[str], findings: list[str],
                   tab_ok: bool, changes: dict[str, int],
                   reconciled: list[str]) -> None:
    """Record what this pass actually DID, so a clean one can close its ticket.

    WHY (2026-09-24). `verify` was null and nothing here wrote a manifest, so
    delivery_check had no evidence at all and answered UNKNOWN on every clean
    pass: failure-car_rides sat open saying "ran clean, but nothing can confirm
    it DELIVERED". NOT `close_on: exit_zero` — what this delivers is the
    reconciled OwnerVille territories plus the 'Car Rides Report' tab anybody
    can open, so it gets checked like everything else.

    THE SPLIT THIS ENCODES. `flags` has always carried two different things and
    delivery only cares about one of them:

      * FAILURES — a stale OwnerVille session, a campaign selector that never
        loaded, 0 territories, a vetoed plan, an edit that threw, a report tab
        that would not publish. The pass did not reconcile. `failed` + kind
        'part' -> NOT_DELIVERED, and the ticket stays open. Today these exit 3,
        which the wrapper publishes as `success`, so a whole morning of "session
        missing/stale, reconciled nothing" was SILENT.

      * FINDINGS — plan flags: "no territory found — needs new team", "ambiguous,
        skipped", "empty stale territory ... first sighting". The pass did its
        whole job and is reporting what it SAW; a human fixes the BOARD and a
        re-run changes nothing. kind 'finding' -> DELIVERED with findings, an
        orange card, ticket closes. Same shape as vantura_board_audit.

    alert=False on the findings write, where vantura_board_audit alerts: that
    audit runs once a day, this runs nine passes a morning, and its routine
    flags include "first sighting; will confirm next run" — which is the rule
    working, not something to page a channel about. The findings still reach
    Carlos on the Hub card and in the report tab.

    A --dry-run writes NOTHING. It plans edits and applies none, so it has no
    delivery to prove, and a manifest from a rehearsal would later be read as
    proof by a real ticket."""
    from automations.shared import run_manifest

    if not live:
        _log("dry-run: no run-manifest written (a plan is not a delivery)")
        return
    if not tab_ok:
        failures = list(failures) + [
            "the {!r} tab on the control workbook".format(REPORT_TAB)]
    applied = sum(changes.values())
    where = ", ".join(reconciled) or "no campaign"
    note = "reconciled {}; {} edit(s) applied".format(where, applied)
    if failures:
        run_manifest.write_manifest(
            REPORT_ID, failed=failures, succeeded=list(reconciled),
            retry_args=[], kind="part", note=note,
            remediation=run_manifest.make_remediation(
                reason="the pass could not reconcile every car-ride territory",
                fix="check Lucy 2's warm OwnerVille session (session_holder) "
                    "and the Stations tab layout, then read the plan with "
                    "`lucy rerun car_rides --dry-run` before going live again."))
        return
    if findings:
        run_manifest.write_manifest(
            REPORT_ID, ok=False, kind="finding", failed=findings,
            retry_args=[], alert=False,
            note=note + "; {} board finding(s) for Carlos".format(len(findings)))
        return
    run_manifest.write_manifest(REPORT_ID, ok=True, kind="part", failed=[],
                                retry_args=[], note=note + "; no flags")


def _clear_for_next_edit(page, camp: str, log=_log) -> bool:
    """Leave the page able to open the NEXT territory. True = go ahead.

    WHY A RELOAD AND NOT JUST ESCAPE (2026-09-24, from the first live run that
    ever applied an add). Escape closes a freshly-opened modal reliably — that
    was probed. What it does NOT reliably close is the modal left behind by a
    SAVE: 'rodolfo' saved four reps at 12:27:47 and andrew / fernando / andrew
    all died at 12:27:55-12:28:01 on "an earlier modal is still covering the
    page". One saved edit still cost the three behind it.

    So dismissal is the fast path and re-opening the territory list is the
    guarantee: it is a fresh page, so there is no modal state left to argue
    with. It costs ~10s and only runs when the modal actually stuck, which is
    cheap next to the 30s-per-territory timeouts this replaces.

    Returns False only when the page cannot be brought back at all — the caller
    stops that campaign there rather than walking down a list of territories it
    can no longer open."""
    if _dismiss_modal(page, log):
        return True
    log(f"  {camp}: modal stuck — reloading the territory list to clear it")
    try:
        goto_territory_assignment(page)
        if not _select_campaign(page, camp):
            log(f"  {camp}: campaign not found after the reload")
            return False
        return _dismiss_modal(page, log)
    except Exception as e:  # noqa: BLE001
        log(f"  {camp}: reload failed: {e!r}")
        return False


# --- main ----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Car-rides cleanup (OwnerVille vs Stations tab).")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="plan + report only, change nothing (DEFAULT)")
    mode.add_argument("--live", action="store_true", help="apply the plan")
    mode.add_argument("--probe", action="store_true",
                      help="dump campaign selector + panel DOM evidence and exit")
    ap.add_argument("--campaign", choices=list(BOXES), help="only this campaign")
    ap.add_argument("--headed", action="store_true", help="visible browser (debug)")
    args = ap.parse_args(argv)
    live = bool(args.live)

    _log(f"car-rides cleanup — mode={'LIVE' if live else ('PROBE' if args.probe else 'DRY-RUN')}")
    prev_flags = _load_prev_flags()
    flags: list[str] = []
    # The same flags, split by what they mean for DELIVERY (see _file_manifest):
    # `failures` = this pass could not reconcile; `findings` = it reconciled and
    # is reporting what it saw, which only Carlos can fix on the board.
    failures: list[str] = []
    findings: list[str] = []
    reconciled: list[str] = []
    changes = {k: 0 for k in BOXES}
    lines: list[str] = []

    def _fail(msg: str) -> None:
        flags.append(msg)
        failures.append(msg)

    # 1) Source of truth first — cheap, and fails loud before any browser work.
    try:
        expected = read_expected()
    except Exception as e:
        _log(f"STOP: Stations read failed: {e}")
        _fail(f"Stations tab read failed — nothing could be reconciled: {e}")
        _file_manifest(live=live, failures=failures, findings=findings,
                       tab_ok=True, changes=changes, reconciled=reconciled)
        return 4

    keys = [args.campaign] if args.campaign else list(BOXES)

    # 2) OwnerVille.
    from patchright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            try:
                ctx, page = _open_ownerville(p, headless=not args.headed,
                                             verbose=True)
            except SessionGone as e:
                _fail(f"OwnerVille session missing/stale on this machine "
                      f"— no unattended re-auth (by design). {e}")
                report = _report(expected, {}, flags, changes, live)
                _persist(report, changes, flags)
                tab_ok = _publish_report_tab(report)
                _file_manifest(live=live, failures=failures, findings=findings,
                               tab_ok=tab_ok, changes=changes,
                               reconciled=reconciled)
                _log(report)
                return 3
            try:
                goto_territory_assignment(page)

                if args.probe:
                    info = page.evaluate(_HARVEST_JS)
                    info["campaign"] = page.evaluate(_CURRENT_CAMPAIGN_JS)
                    info["url"] = page.url
                    STATE_DIR.mkdir(parents=True, exist_ok=True)
                    (STATE_DIR / "probe.json").write_text(json.dumps(info, indent=1))
                    page.screenshot(path=str(STATE_DIR / "probe.png"), full_page=True)
                    _log(f"probe: campaign={info['campaign']!r}, "
                         f"{len(info.get('rows', []))} rows via {info.get('via')} "
                         f"-> {STATE_DIR}/probe.json|png")
                    return 0

                for key in keys:
                    camp = BOXES[key]["campaign"]
                    _log(f"— campaign {camp} —")
                    if not _select_campaign(page, camp):
                        _fail(f"{camp}: campaign selector not found — "
                              "skipped (run --probe on Lucy 2)")
                        continue
                    terrs = list_territories(page)
                    if not terrs:
                        _fail(f"{camp}: 0 territories loaded — skipped, "
                              "not re-authing (per rules)")
                        continue
                    reconciled.append(camp)
                    plan = plan_campaign(expected[key], terrs, prev_flags)
                    found = [f"{camp}: {f}" for f in plan["flags"]]
                    flags += found
                    findings += found
                    lines.append(f"\n### {camp}")
                    veto = stale_sanity(expected[key], terrs, plan)
                    if veto:
                        msg = f"LIVE EDITS ABORTED — {veto}"
                        _fail(f"{camp}: {msg}. Plan is reported below; "
                              "NOTHING was changed. Check the Stations "
                              "tab layout before re-running --live.")
                        lines.append(f"- ⚠️ {msg}; plan shown, not applied")
                        _log(f"!! {camp}: {msg}")
                    for e in plan["edits"]:
                        why = f" ({e['why']})" if e.get("why") else ""
                        lines.append(f"- {e['territory']}: +{e['add'] or '—'} "
                                     f"-{e['remove'] or '—'}{why}")
                        if live and not veto:
                            if not _clear_for_next_edit(page, camp):
                                _fail(f"{camp}: a modal stayed stuck and the "
                                      "territory list would not reload — "
                                      "stopped after this point, nothing was "
                                      "left half-applied")
                                break
                            ok = apply_edit(page, e)
                            if ok:
                                changes[key] += 1
                            else:
                                _fail(f"{camp}: edit failed on "
                                      f"{e['territory']!r} — left as-is")
                    if not plan["edits"]:
                        lines.append("- nothing to change")
                    if not live and plan["edits"]:
                        lines.append(f"  (dry-run: {len(plan['edits'])} edit(s) "
                                     "NOT applied)")
            finally:
                ctx.close()
    except SessionGone:
        raise  # already handled above; belt-and-suspenders
    except Exception as e:
        _fail(f"unexpected browser failure: {e!r}")
        _log(f"browser phase failed: {e!r}")

    report = _report(expected, lines, flags, changes, live)
    _persist(report, changes, flags)
    tab_ok = _publish_report_tab(report)
    _file_manifest(live=live, failures=failures, findings=findings,
                   tab_ok=tab_ok, changes=changes, reconciled=reconciled)
    _log(report)
    _log("done.")
    return 0 if not flags else 3


def _report(expected, lines, flags, changes, live) -> str:
    out = [f"# Car-rides cleanup — {dt.datetime.now():%Y-%m-%d %H:%M} "
           f"({'LIVE' if live else 'DRY-RUN'})",
           f"Board: AT&T {len(expected.get('att', {}))} leaders, "
           f"BOX {len(expected.get('box', {}))} leaders.",
           f"Changes applied: att={changes.get('att', 0)} box={changes.get('box', 0)}"]
    out += list(lines) if lines else ["(no campaign was reconciled)"]
    out.append("\n## FLAGS for Carlos")
    out += [f"- {f}" for f in flags] or ["- none"]
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
