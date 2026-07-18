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
  1. Read Stations A5:E25 (AT&T box) and A28:E38 (BOX box) -> leader -> [riders].
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

# --- Source of truth ---------------------------------------------------------
SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"   # Vantura Master Sales Board
STATIONS_GID = 1999003555
# Read ONLY cols A-E: col A = Territory Leader, B-E = Rep #1-4 riders. Header
# rows are 5 (AT&T) and 28 (BOX). Everything right of E is the station matrix.
BOXES = {
    "att": {"range": "A5:E25",  "campaign": "B2B AT&T SBS"},
    "box": {"range": "A28:E38", "campaign": "B2B-BOX-Energy"},
}

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
        if not any("leader" in h for h in header):
            raise RuntimeError(
                f"Stations {box['range']} header row is {rows[0]!r} — expected "
                "'Territory Leader | Rep #1..4'. Box rows moved; fix BOXES.")
        exp = {}
        for r in rows[1:]:
            leader = str(r[0]).strip() if r else ""
            if not leader:
                continue
            riders = [str(c).strip() for c in r[1:5] if str(c).strip()]
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

    claimed: dict[str, str] = {}   # normalized rep -> leader who owns them
    for leader, riders in expected.items():
        t = find_territory(leader)
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
        adds = [w for w in want if not any(names_match(w, r) for r in t["reps"])]
        removes = [r for r in t["reps"]
                   if not any(names_match(w, r) for w in want)]
        if adds or removes:
            plan["edits"].append({"territory": t["name"], "leader": leader,
                                  "add": adds, "remove": removes})

    # One rep, one car ride + stale-leader territories.
    for t in active:
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
        # flag-only in this port, even under the old 2-run rule).
        if t["reps"]:
            plan["edits"].append({"territory": t["name"], "leader": None,
                                  "add": [], "remove": list(t["reps"]),
                                  "why": "stale leader — empty the territory"})
            plan["flags"].append(f"stale territory {t['name']!r}: leader not on "
                                 "the board; emptying riders")
        else:
            prior = any(t["name"] in f for f in prev_flags)
            plan["flags"].append(
                f"empty stale territory {t['name']!r} — "
                + ("flagged LAST run too; ready for Carlos to Remove"
                   if prior else "first sighting; will confirm next run"))
    return plan


# --- Step 4: apply (live only) ------------------------------------------------
def apply_edit(page, edit: dict, log=_log) -> bool:
    """Open one territory, add/remove chips, Escape, Save, verify. True=verified.
    Conservative: any element we can't confidently find -> False (caller flags)."""
    name = edit["territory"]
    try:
        row = page.get_by_text(name, exact=False).first
        row.click()
        page.wait_for_timeout(2_500)
        row.click()                          # second click if the first only zoomed
        page.wait_for_timeout(2_500)
    except Exception as e:
        log(f"  open {name!r} failed: {e!r}")
        return False
    try:
        for rep in edit.get("remove", []):
            chip = page.locator(
                f"li.select2-selection__choice:has-text({json.dumps(rep.split()[0])})").first
            chip.locator("span.select2-selection__choice__remove, .remove, "
                         "[aria-label*=remove i]").first.click()
            page.wait_for_timeout(800)
            log(f"  removed chip {rep!r}")
        for rep in edit.get("add", []):
            box = page.locator(
                "input.select2-search__field, .select2-search input").first
            box.click()
            box.fill(rep.split()[0])
            page.wait_for_timeout(1_500)
            opt = page.locator(
                f".select2-results__option:has-text({json.dumps(rep.split()[0])})").first
            opt.click()
            page.keyboard.press("Escape")    # select2 gotcha: close BEFORE Save
            page.wait_for_timeout(500)
            log(f"  added {rep!r}")
        page.keyboard.press("Escape")
        page.get_by_role("button", name=re.compile(r"^save$", re.I)).first.click()
        page.wait_for_timeout(3_000)
        return True
    except Exception as e:
        log(f"  edit {name!r} failed mid-way: {e!r} — flagging, NOT retrying blind")
        return False


# --- state + report -----------------------------------------------------------
# Full report also goes to a tab on the control workbook — the queue's Result
# cell truncates (~470 chars), and this is the established rich-output channel
# (same pattern as RP Diag). Best-effort: a sheet hiccup never fails the run.
CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
REPORT_TAB = "Car Rides Report"


def _publish_report_tab(report: str, log=_log) -> None:
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
    except Exception as e:  # noqa: BLE001 — reporting must never fail the run
        log(f"report tab publish skipped: {e!r}")


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
    changes = {k: 0 for k in BOXES}
    lines: list[str] = []

    # 1) Source of truth first — cheap, and fails loud before any browser work.
    try:
        expected = read_expected()
    except Exception as e:
        _log(f"STOP: Stations read failed: {e}")
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
                flags.append(f"OwnerVille session missing/stale on this machine "
                             f"— no unattended re-auth (by design). {e}")
                report = _report(expected, {}, flags, changes, live)
                _persist(report, changes, flags)
                _publish_report_tab(report)
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
                        flags.append(f"{camp}: campaign selector not found — "
                                     "skipped (run --probe on Lucy 2)")
                        continue
                    terrs = list_territories(page)
                    if not terrs:
                        flags.append(f"{camp}: 0 territories loaded — skipped, "
                                     "not re-authing (per rules)")
                        continue
                    plan = plan_campaign(expected[key], terrs, prev_flags)
                    flags += [f"{camp}: {f}" for f in plan["flags"]]
                    lines.append(f"\n### {camp}")
                    for e in plan["edits"]:
                        why = f" ({e['why']})" if e.get("why") else ""
                        lines.append(f"- {e['territory']}: +{e['add'] or '—'} "
                                     f"-{e['remove'] or '—'}{why}")
                        if live:
                            ok = apply_edit(page, e)
                            if ok:
                                changes[key] += 1
                            else:
                                flags.append(f"{camp}: edit failed on "
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
        flags.append(f"unexpected browser failure: {e!r}")
        _log(f"browser phase failed: {e!r}")

    report = _report(expected, lines, flags, changes, live)
    _persist(report, changes, flags)
    _publish_report_tab(report)
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
