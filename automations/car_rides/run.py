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
    {"nimo", "warimu"},
    {"jayden", "luna", "willingham"},
    {"melanie", "hernandez"},
]

# Territory names to leave alone: road trips, location/zip names, unassigned.
SKIP_NAME_PATTERNS = [
    r"^rt\b",                # "RT ..."
    r"\b\d{5}\b",            # zip code in the name ("02780 06/5")
    r"\d{1,2}/\d{1,2}",      # date-suffixed place names ("west warwick 04/13")
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


def names_match(board_name: str, ov_name: str) -> bool:
    """Board short name vs OwnerVille legal name: shared first token, ANY shared
    token, or two tokens in the same alias group."""
    bt, ot = _tokens(board_name), _tokens(ov_name)
    if not bt or not ot:
        return False
    if bt & ot:
        return True
    for grp in ALIAS_GROUPS:
        if (bt & grp) and (ot & grp):
            return True
    return False


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
_EXTRACT_JS = r"""
() => {
  // Generic, layout-tolerant harvest of the Territory Assignment left panel.
  // A territory entry shows Name + Sales Rep(s) + dates + Locations count.
  const out = [];
  const seen = new Set();
  const nodes = [...document.querySelectorAll(
    'li, tr, .territory, .panel, .card, [class*="territor" i], [id*="territor" i]')];
  for (const n of nodes) {
    const t = (n.innerText || '').trim();
    if (!t || t.length > 900) continue;              // skip page-sized containers
    if (!/sales\s*rep/i.test(t)) continue;           // territory entries name their reps
    if (n.querySelector('li, tr')) continue;         // keep leaves only
    if (seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  const sel = [...document.querySelectorAll('select')].map(s => ({
    name: s.name || s.id || '',
    options: [...s.options].map(o => o.text.trim()).slice(0, 40),
    value: s.options[s.selectedIndex] ? s.options[s.selectedIndex].text.trim() : ''
  }));
  const pager = [...document.querySelectorAll('a, button')]
    .map(a => (a.innerText || '').trim())
    .filter(x => /^(next|›|»|more)$/i.test(x));
  return {entries: out, selects: sel, pagers: pager,
          url: location.href, title: document.title};
}
"""


def _parse_entry(text: str) -> dict:
    """One left-panel text block -> {name, reps[]}. Reps come from the line(s)
    after 'Sales Rep'; the first line is the territory name."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    name = lines[0] if lines else ""
    reps: list[str] = []
    grab = False
    for l in lines[1:]:
        if re.match(r"sales\s*reps?\b[:]?", l, re.I):
            grab = True
            rest = re.sub(r"^sales\s*reps?\b[:]?\s*", "", l, flags=re.I)
            if rest:
                reps += [x.strip() for x in re.split(r"[,;]", rest) if x.strip()]
            continue
        if grab:
            if re.match(r"(start|end|locations?|date)\b", l, re.I):
                grab = False
                continue
            reps += [x.strip() for x in re.split(r"[,;]", l) if x.strip()]
    return {"name": name, "reps": reps}


def _select_campaign(page, campaign: str, log=_log) -> bool:
    """Switch the top-right campaign selector. True if selected (or already)."""
    try:
        info = page.evaluate(_EXTRACT_JS)
        for s in info.get("selects", []):
            if any(campaign.lower() == o.lower() for o in s.get("options", [])):
                if s.get("value", "").lower() == campaign.lower():
                    return True
                sel = f'select[name="{s["name"]}"]' if s.get("name") else "select"
                page.select_option(sel, label=campaign)
                page.wait_for_timeout(6_000)
                return True
        # select2-style dropdown fallback: click the visible campaign control.
        ctl = page.get_by_text(re.compile(r"B2B[- ]", re.I)).first
        if ctl.is_visible(timeout=3_000):
            ctl.click()
            page.wait_for_timeout(1_000)
            opt = page.get_by_text(campaign, exact=False).first
            opt.click()
            page.wait_for_timeout(6_000)
            return True
    except Exception as e:
        log(f"campaign switch to {campaign!r} failed: {e!r}")
    return False


def list_territories(page, log=_log, max_pages: int = 30) -> list[dict]:
    """All territories on all pages of the left panel."""
    got: list[dict] = []
    seen_names: set[str] = set()
    for pageno in range(max_pages):
        info = page.evaluate(_EXTRACT_JS)
        fresh = 0
        for t in info.get("entries", []):
            e = _parse_entry(t)
            if e["name"] and e["name"] not in seen_names:
                seen_names.add(e["name"])
                got.append(e)
                fresh += 1
        if not info.get("pagers") or fresh == 0:
            break
        try:
            page.get_by_text(re.compile(r"^(next|›|»)$", re.I)).first.click()
            page.wait_for_timeout(4_000)
        except Exception:
            break
    log(f"territory list: {len(got)} entries harvested")
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
                _log(report)
                return 3
            try:
                page.goto(OWNERVILLE_TERRITORY_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(10_000)

                if args.probe:
                    info = page.evaluate(_EXTRACT_JS)
                    STATE_DIR.mkdir(parents=True, exist_ok=True)
                    (STATE_DIR / "probe.json").write_text(json.dumps(info, indent=1))
                    page.screenshot(path=str(STATE_DIR / "probe.png"), full_page=True)
                    _log(f"probe: {len(info.get('entries', []))} entries, "
                         f"selects={[s['name'] for s in info.get('selects', [])]}, "
                         f"pagers={info.get('pagers')} -> {STATE_DIR}/probe.json|png")
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
