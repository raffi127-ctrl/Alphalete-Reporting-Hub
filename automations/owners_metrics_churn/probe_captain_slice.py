"""READ-ONLY: can ONE all-team view replace the four per-captain churn views?

WHY (Megan 2026-09-04, after a day of this workbook's saved views dying):
"Why wouldn't you just use the view that has everyone? Then no one can be
missing?" She is right, and this is the last unknown before it can be done.

Everything about that design is already proven except one thing:

  * product slices from the URL — proven (`Product Type (Broken Out)`, in
    production since 2026-08-19 and again today for Jamis's three churn boards);
  * owner slices from the URL — proven (`Owner & Office`, every b2b_metrics
    office);
  * CAPTAIN slices from the URL — `b2b_views_probe` found the field is
    `Captain's Bonus Teams` (NOT the `B2B Captain's Teams (SFDC)` the dashboard
    displays) and reported "URL filter works = True" for Carlos and Luis — but
    only **1 owner** came back, where Carlos's captainship holds ~13 and Luis's
    ~9.

That 1-owner result is the whole reason this probe exists, and it is NOT
evidence the captain filter is broken. `b2b_views_probe` tested the BASE view,
and Eve's 2026-09-03 screenshot showed the base is pinned to
`Owner & Office = CODY LOWERY` — a saved single-owner filter that a captain
param does not clear. So the base view can never answer this question.

ALLTEAMWireless can: it is the view Megan opened, it carries Owner & Office =
(All), and `allteam_guid_probe` measured 93 owners in it today. If a captain
param narrows THAT to the captain's real roster, the cutover is safe and every
per-captain custom view can stop being a dependency — which is what stops this
class of failure recurring (it has now cost: Gary Whitaker II pinned on false
evidence, Cruz Venegas + Max Powell nearly pinned, and Jamis's three churn
boards blank).

WHAT IT DOES — nothing but look:
  1. downloads 'ICD Churn' off ALLTEAMWireless with NO captain filter (the
     baseline, expected ~93 owners);
  2. downloads it again per captain with `Captain's Bonus Teams=<team>`;
  3. reports each owner count and, decisively, compares the returned names
     against who is ALREADY on that captain's sheet tab — the roster the report
     actually has to fill. A slice that returns the right COUNT but the wrong
     PEOPLE would fill a tab with someone else's numbers, which is worse than
     the blank it replaces, so names are checked, not totals.

Writes NO Sheet, NO Slack, NO manifest — output/captain_slice_probe/ only.

MUST RUN ON LUCY 1 (Raf's Tableau session; the SSO rides ownerville, one session
per account, so a laptop run evicts the holder and pauses the box).

    lucy rerun captain_slice_probe --machine "Lucy 1"
"""
from __future__ import annotations

import json
import tempfile
import urllib.parse
from pathlib import Path

from automations.shared.tableau_patchright import (
    tableau_session, download_crosstab_patchright)
from automations.owners_metrics_churn import pull, fill

OUT = Path(__file__).resolve().parents[2] / "output" / "captain_slice_probe"

# The field b2b_views_probe proved bites, spelled as Tableau knows it — NOT the
# caption the dashboard prints.
CAPTAIN_FIELD = "Captain's Bonus Teams"

# captain key -> (team value, the sheet tab whose roster it must reproduce)
CAPTAINS = [
    ("carlos", "Carlos's Team", fill.open_ws_b2b_carlos),
    ("luis", "Luis's Team", fill.open_ws_b2b_luis),
    ("eveliz", "Eveliz's Team", fill.open_ws_b2b_eveliz),
]


def log(msg: str = "") -> None:
    print(msg, flush=True)


def _url(team: str = "") -> str:
    """ALLTEAMWireless (Owner & Office = All, 93 owners) + optional captain."""
    u = pull.B2B_ALLTEAM_URL
    if team:
        u += "&{}={}".format(urllib.parse.quote(CAPTAIN_FIELD),
                             urllib.parse.quote(team))
    return u


def _owners(url: str, tag: str, page) -> list:
    out = Path(tempfile.gettempdir()) / f"probe_captain_{tag}.csv"
    try:
        download_crosstab_patchright(url, pull.WORKSHEET, out, verbose=False,
                                     page=page)
    except Exception as e:  # noqa: BLE001
        log(f"      download failed: {type(e).__name__}: {str(e)[:160]}")
        return []
    try:
        parsed = pull.parse_b2b(out)
        (OUT / f"{tag}.csv").write_bytes(out.read_bytes())
        return sorted(parsed.get("reps", {}))
    except Exception as e:  # noqa: BLE001
        log(f"      parse failed: {type(e).__name__}: {e}")
        return []


def _tab_roster(opener) -> set:
    """REP names on that captain's churn tab — what the fill must cover.

    The skip list has to be exact or the verdict lies. The first run (2026-09-04)
    reported carlos "missing" `Rep` and `CARLOS HIDALGO (B2B)` — a column header
    and the captainship-total label, neither of them people. That turned a clean
    result into a fake shortfall, which is the same species of bug this probe
    exists to catch, pointed at the probe itself."""
    try:
        col_a = [(r[0] if r else "").strip() for r in opener().get_all_values()]
    except Exception as e:  # noqa: BLE001
        log(f"      tab read failed: {type(e).__name__}: {e}")
        return set()
    out = set()
    for a in col_a:
        low = a.lower()
        if not a or low in ("rep", "name", "icd", "owner"):
            continue                      # column headers
        if any(s in low for s in ("churn", "captainship avg", "grand total",
                                  "national average", "office avg")):
            continue                      # section headers + total rows
        if low.endswith("(b2b)"):
            continue                      # "CARLOS HIDALGO (B2B)" — the tab's
                                          # own captainship label, not a rep row
        out.add(a)
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"field": CAPTAIN_FIELD, "captains": {}}

    with tableau_session(verbose=False) as pg:
        log("=== baseline: ALLTEAMWireless, no captain filter ===")
        base = _owners(_url(), "baseline", pg)
        report["baseline_owners"] = len(base)
        log(f"  {len(base)} owner(s)"
            + ("  ← expected ~93; a small number here means THIS view has "
               "narrowed too and nothing below is trustworthy"
               if len(base) < 50 else ""))

        for key, team, opener in CAPTAINS:
            log("")
            log(f"=== {key}: {CAPTAIN_FIELD} = {team!r} ===")
            got = _owners(_url(team), key, pg)
            roster = _tab_roster(opener)
            low = {g.lower() for g in got}
            missing = sorted(n for n in roster if n.lower() not in low)
            extra = sorted(g for g in got
                           if g.lower() not in {r.lower() for r in roster})
            report["captains"][key] = {
                "team": team, "returned": len(got), "tab_roster": len(roster),
                "missing_from_slice": missing, "not_on_tab": extra}
            log(f"  returned {len(got)} owner(s) · the tab carries {len(roster)}")
            log(f"  on the tab but NOT in the slice ({len(missing)}): "
                f"{missing[:10]}" + (" …" if len(missing) > 10 else ""))
            log(f"  in the slice but not on the tab ({len(extra)}): "
                f"{extra[:10]}" + (" …" if len(extra) > 10 else ""))

    log("")
    log("=== verdict ===")
    if report.get("baseline_owners", 0) < 50:
        log("  INCONCLUSIVE — the all-team view itself came back narrow, so the "
            "captain results below mean nothing. Re-check the GUID first "
            "(`lucy rerun allteam_guid_probe`).")
    else:
        base_n = report["baseline_owners"]
        # THREE outcomes, not two. The first run collapsed the first into the
        # third and reported "Short: carlos, luis, eveliz" when every slice had
        # in fact returned ALL 93 owners — the opposite problem, and the wrong
        # thing to go fix. Say which one it is.
        ignored = [k for k, v in report["captains"].items()
                   if v["returned"] == base_n]
        short = [k for k, v in report["captains"].items()
                 if v["returned"] != base_n and v["missing_from_slice"]]
        clean = [k for k, v in report["captains"].items()
                 if v["returned"] and v["returned"] != base_n
                 and not v["missing_from_slice"]]
        if ignored:
            log(f"  FILTER IGNORED — not 'short'. {ignored} each returned all "
                f"{base_n} owners, i.e. the captain param changed NOTHING. The "
                f"likely cause is the pinned-categorical trap this workbook is "
                f"already known for (att_churn's remediation): a saved view "
                f"holding a filter at (All) does not accept a URL override — it "
                f"has to be released in Tableau with focus+Space, not a click. "
                f"b2b_views_probe saw the mirror image on the BASE view, where "
                f"a pinned SINGLE owner survived the same param.")
            log("  => the per-captain cutover is OFF on this evidence. Per-OFFICE "
                "slicing (Owner & Office) is unaffected and works — that is what "
                "b2b_metrics uses.")
        elif clean and not short:
            log("  CUT OVER. Every captain's slice returned their whole tab "
                "roster off the ONE all-team view — the per-captain custom "
                "views can stop being a dependency, and no future republish "
                "can narrow a captainship into looking empty.")
        else:
            log(f"  NOT YET. Clean: {clean or 'none'}. Short: {short}. A slice "
                f"that misses people would fill a tab with an incomplete "
                f"roster, which is worse than the blank it replaces — see "
                f"missing_from_slice per captain above before changing pull.py.")

    (OUT / "probe.json").write_text(json.dumps(report, indent=2))
    log("")
    log(f"  raw: {OUT}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
