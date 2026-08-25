"""Read-only audit: which captainship ICDs are in the reporting account's
ownerville Office Access list, and which are not.

No impersonation, no Sheet write, no Slack, no mail. It reads two things:

  * each captainship's roster off the Org Sales Board (the same
    discover_captainships / find_captainship path the drafts use, so the audit
    can never disagree with the report about who is on a captainship), and
  * the Office Access table on `index.cfm?p=901` of the account the reports log
    in as (`rhidalgo` — automations.shared.creds).

Grown out of output/knocks_access_audit.py, the one-off that produced the
2026-08-24 list for Eve's boss. Same reads, same matching; what is new is that
it RETURNS a structure instead of printing, so run.py can diff two days and say
what changed.

ONE WARNING, and it is the reason run.py waits before calling any of this:
ownerville allows ONE session per account, and navigating to the site root to
mint a fresh `rqst` RE-ESTABLISHES that session in master mode. Do that while
the knocks capture is impersonating an office and you pull the floor out from
under it — the capture's next scrape silently reads the master office instead.
Never call read_office_access() from a scheduled job without going through
run.py's wait.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# The captainships whose reports carry knock sections. rafael first on purpose:
# his access is complete, so he is the control — if HIS row shows gaps, the
# audit is broken (stale session, renamed table), not the access list.
CAPTAINS = ("rafael", "wayne", "starr", "chan", "tony", "sahil")

OFFICE_ACCESS_URL = "https://v2.ownerville.com/index.cfm?p=901"
_ROOT_URL = "https://v2.ownerville.com/"
_TABLE = "table#promotingOffices"

# What an owner row can say.
OK = "ok"              # listed and granted — the report can pull this office
PENDING = "pending"    # listed, but the row's action still reads "request"
MISSING = "missing"    # not on the list under any spelling we can search for


def rosters(grid=None) -> Dict[str, Tuple[Optional[str], List[str]]]:
    """{captain key: (block title, [owner display names])} off the Org Sales
    Board, in board order.

    Names keep the BOARD's spelling — the same string the email sub-headings
    and the knock boards show, so a diff of this audit lines up with what Eve
    sees in the report rather than with a canonical she never reads."""
    from automations.captainship_drafts import sales_board as sb
    from automations.org_sales_board import captainship as cap
    from automations.icd_sales_board.board_read import clean_name
    if grid is None:
        grid = sb._values()
    out: Dict[str, Tuple[Optional[str], List[str]]] = {}
    for key in CAPTAINS:
        token = sb.CAPTAIN_TOKEN[key]
        title = next((t for t, _h in cap.discover_captainships(grid)
                      if token in cap._cap_key(t).lower()), None)
        if title is None:
            out[key] = (None, [])
            continue
        anchor = cap.find_captainship(grid, title)
        names: List[str] = []
        seen = set()
        for _row, raw in list(anchor.leaderboard) + list(anchor.daily):
            name, _tags = clean_name(raw)
            k = " ".join(name.lower().split())
            if not name or k in seen:
                continue
            seen.add(k)
            names.append(name)
        out[key] = (title, names)
    return out


def read_office_access(page) -> List[List[str]]:
    """Every row of the Office Access table, as lists of cell text.

    `page` is an ALREADY-OPEN ownerville page: the caller owns the session, and
    owns having waited for it.

    The DataTable paginates at 25 rows and the account is well past that, so the
    length selector is pushed to its maximum first. A read that skipped it would
    report two thirds of the captainships as unreachable — indistinguishable
    from access being revoked overnight, which is why a suspiciously short read
    raises instead of returning."""
    page.goto(_ROOT_URL, wait_until="domcontentloaded", timeout=30000)
    m = re.search(r"rqst=([A-Fa-f0-9_]+)", page.url)
    if not m:
        raise RuntimeError(f"no rqst after root nav: {page.url}")
    page.goto(f"{OFFICE_ACCESS_URL}&rqst={m.group(1)}",
              wait_until="domcontentloaded", timeout=30000)
    if "p=901" not in page.url:
        raise RuntimeError(f"bounced off p=901 -> {page.url}")
    page.locator(_TABLE).wait_for(state="visible", timeout=20000)
    page.wait_for_function(
        "() => {const r=document.querySelectorAll("
        "'table#promotingOffices tbody tr');"
        "return r.length>1 && !(r[0].textContent||'')"
        ".toLowerCase().includes('loading');}",
        timeout=45000)
    try:
        sel = page.locator("#promotingOffices_length select").first
        vals = [o.get_attribute("value") for o in sel.locator("option").all()]
        pick = "-1" if "-1" in vals else max(vals, key=lambda v: int(v or 0))
        sel.select_option(pick)
        page.wait_for_timeout(2500)
    except Exception:  # noqa: BLE001 — the short-read guard below catches it
        pass
    rows: List[List[str]] = []
    for tr in page.locator(f"{_TABLE} tbody tr").all():
        cells = tr.locator("td").all()
        if len(cells) < 3:
            continue
        rows.append([c.inner_text().strip() for c in cells])
    if len(rows) <= 25:
        raise RuntimeError(
            f"Office Access read came back with only {len(rows)} row(s) — 25 is "
            "the table's default page size, so this is a half-loaded table, not "
            "the access list. Refusing to report it as one")
    return rows


def classify(rosters_map, office_rows, aliases=None) -> dict:
    """{captain key: {"title": …, "owners": [{display, canonical, status, …}]}}

    Matching goes through the ICD Aliases sheet's own candidate list
    (get_search_candidates) — the same one the ownerville impersonation search
    uses. So "listed" here means "the report's own lookup would find this
    office", not "some string matched somewhere". An office present under a
    spelling the report cannot search for is NOT reachable and must not read as
    ok, or the watcher would announce an access that the build then fails on.

    An unmatched owner carries `near`: rows whose company/owner text contains
    their surname. That is what turns "not listed" into an actionable line —
    the 2026-08-24 audit is how we learned ownerville calls Wayne Rude "Floyd
    Rude" and Andre Burton "Andre Burton Jr"."""
    from automations.focus_office_att.aliases import (
        load_aliases, alias_to_canonical, get_search_candidates)
    aliases = load_aliases() if aliases is None else aliases
    listed = {" ".join((r[2] or "").lower().split()): r for r in office_rows}

    def find(display):
        for cand in get_search_candidates(display, aliases):
            row = listed.get(" ".join(cand.lower().split()))
            if row is not None:
                return cand, row
        return None, None

    report = {}
    for key, (title, names) in rosters_map.items():
        owners = []
        for display in names:
            try:
                canonical = alias_to_canonical(display, aliases)
            except Exception:  # noqa: BLE001 — a broken alias sheet ≠ no audit
                canonical = display
            cand, row = find(display)
            if row is None:
                surname = (display.split() or [""])[-1].lower()
                near = [r[2] for r in office_rows
                        if len(surname) > 2 and surname in (r[2] or "").lower()]
                owners.append({"display": display, "canonical": canonical,
                               "status": MISSING, "near": near[:4]})
                continue
            action = (row[-1] or "").strip()
            owners.append({
                "display": display, "canonical": canonical,
                "status": PENDING if re.search(r"request", action, re.I) else OK,
                "matched": cand,
                "office": row[0] if len(row) > 0 else "",
                "company": row[1] if len(row) > 1 else "",
                "action": action,
            })
        report[key] = {"title": title, "owners": owners}
    return report


def statuses(report) -> Dict[str, str]:
    """Flat {"<captain>/<owner display>": status} — the shape run.py snapshots
    and diffs. Keyed by captain AND name because an owner can sit on two
    captainships, and losing access on one of them is still news."""
    return {f"{key}/{o['display']}": o["status"]
            for key, block in sorted(report.items())
            for o in block["owners"]}


def counts(report) -> Dict[str, Tuple[int, int]]:
    """{captain key: (reachable, roster size)} — what the report's summary
    boards will be able to cover."""
    return {key: (sum(1 for o in block["owners"] if o["status"] == OK),
                  len(block["owners"]))
            for key, block in report.items()}


def audit(page, grid=None) -> dict:
    """The whole read, on an already-open ownerville page."""
    rmap = rosters(grid)
    rows = read_office_access(page)
    return {"offices": rows, "report": classify(rmap, rows)}
