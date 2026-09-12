"""Read every captainship ICD's street address out of ownerville, once.

THIS IS THE STEP THAT UNBLOCKS THE NIGHT SEND. `zones.ICD_TIMEZONES` knows
eleven offices; the captainships run ~44. Until the rest are harvested,
`schedule.due()` will not place them in any wave and they are simply not in
anybody's email — which is the safe failure, but it is still a failure.

WHERE THE ANSWER LIVES. Ownerville's session blob has a `timezoneFullName` and
it is a trap: it describes the LOGGED-IN ACCOUNT, not the office being viewed
(proven 2026-08-25 across 21 impersonations, all of which said "US/Central").
Company Information (index.cfm?p=767) under impersonation DOES carry the
office's own street address and it changes per office. That page is what this
reads.

RUNS ON LUCY 3, NOT ON WINDOWS. There is no ownerville session on a laptop
(the storage state only refreshes where the session holder runs), and this
opens ~44 impersonations in single file — budget ~40-50 minutes and remember
the mini queue is SERIAL, so it will hold everything behind it. It is read-only:
no Sheet, no Slack, no mail.

    python -m automations.captainship_night_knocks.harvest_zones
    python -m automations.captainship_night_knocks.harvest_zones --only rafael
    python -m automations.captainship_night_knocks.harvest_zones --icd "Aya Mohamed"

WHAT IT PRINTS is the point: paste-ready ICD_TIMEZONES lines for everything it
could resolve, and a separate list of everything it could not. The second list
is not a bug report — a split state with an unrecognised city lands there BY
DESIGN (see addresses.py), and the fix is somebody confirming that one city, not
loosening the rule. NOTHING IS WRITTEN TO zones.py AUTOMATICALLY: the table is
the record of what a person checked, and a scraper that edits it would erase
that distinction the first time a page renders oddly.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console, best effort
    pass

from automations.captainship_night_knocks import addresses

OUT_JSON = Path("output") / "icd_office_addresses.json"
# Raw HTML of any page we could not parse, so a DOM change costs ONE more run
# instead of one run per guess.
DEBUG_DIR = Path("output") / "icd_office_addresses_unparsed"

COMPANY_INFO = "https://v2.ownerville.com/index.cfm?p=767&rqst=%s"

# "Lubbock, TX 79424" — city can carry spaces, hyphens and periods
# (Wilkes-Barre, St. Louis). The ZIP is what makes this unambiguous in a page
# full of other prose, so it is required even though we do not use it.
ADDR_RE = re.compile(
    r"([A-Za-z][A-Za-z .'\-]{1,40}),\s*([A-Za-z]{2})\s+(\d{5})(?:-\d{4})?"
)


def parse_address(text: str) -> Optional[Dict[str, str]]:
    """First 'City, ST ZIP' in the page text, or None.

    Deliberately a text scrape rather than a CSS selector: the label markup on
    p=767 is the part most likely to be restyled, while an address in a page of
    company details is unmistakable.
    """
    m = ADDR_RE.search(text or "")
    if not m:
        return None
    return {"city": m.group(1).strip(), "state": m.group(2).upper(),
            "zip": m.group(3)}


INPUT_RE = re.compile(r"<input\b[^>]*>", re.I)
SELECT_RE = re.compile(r"<select\b[^>]*name=[\"']([^\"']+)[\"'][^>]*>(.*?)</select>",
                       re.I | re.S)
OPTION_RE = re.compile(r"<option\b[^>]*>", re.I)
ATTR_RE = re.compile(r"(\w[\w-]*)\s*=\s*[\"']([^\"']*)[\"']")


def form_fields(html: str) -> Dict[str, str]:
    """{field name: value} for every filled input and select on the page. Pure.

    THE PAGE IS A FORM, NOT PROSE — the thing the first live run got wrong.
    p=767 renders the office's address into `value=` attributes
    (`<input name="city" ... value="Lubbock">`), and `inner_text` cannot see an
    attribute, so a text scrape of that page finds no address at all while the
    page has loaded perfectly. Every office failed identically on 2026-09-11
    for exactly this reason.
    """
    out: Dict[str, str] = {}
    for tag in INPUT_RE.findall(html or ""):
        attrs = {k.lower(): v for k, v in ATTR_RE.findall(tag)}
        name = attrs.get("name") or attrs.get("id")
        val = (attrs.get("value") or "").strip()
        if name and val:
            out.setdefault(name.strip(), val)
    for name, body in SELECT_RE.findall(html or ""):
        # The selected option, whatever order its attributes come in —
        # `value="TX" selected` is as common as `selected value="TX"`, and a
        # regex that only knows one of them reads a filled dropdown as empty.
        for tag in OPTION_RE.findall(body or ""):
            if "selected" not in tag.lower():
                continue
            attrs = {k.lower(): v for k, v in ATTR_RE.findall(tag)}
            val = (attrs.get("value") or "").strip()
            if val:
                out.setdefault(name.strip(), val)
                break
    return out


def _pick(fields: Dict[str, str], *wanted: str) -> Optional[str]:
    """First field whose NAME contains one of `wanted` (case-insensitive)."""
    for want in wanted:
        for name, val in fields.items():
            if want in name.lower():
                return val
    return None


def parse_form(html: str) -> Optional[Dict[str, str]]:
    """City/state/ZIP out of the Company Information form, or None. Pure.

    THE STATE IS DERIVED FROM THE ZIP when the form has no state field — and on
    the page we actually got back it has none: no `name="state"`, no
    `value="TX"`, nothing, in 9,600 lines. A ZIP pins its state exactly
    (addresses.state_for_zip), so there is nothing to guess. A form field wins
    when it is there and says something two letters long.
    """
    fields = form_fields(html)
    city = _pick(fields, "city", "town")
    zip_code = _pick(fields, "zip", "postal")
    state = _pick(fields, "state", "province")
    if state and len(state.strip()) != 2:
        state = None          # "Texas" / a numeric id: let the ZIP answer
    if not state and zip_code:
        state = addresses.state_for_zip(zip_code)
    if not (city and state):
        return None
    return {"city": city.strip(), "state": state.strip().upper()[:2],
            "zip": (zip_code or "").strip()}


def captain_rosters(only: Optional[str] = None) -> Dict[str, List[str]]:
    """{captain_key: [ICD name, ...]} off the Org Sales Board — the roster is
    truth (the same lookup the knock boards use, so this can never drift from
    the people who actually get boards)."""
    from automations.captainship_drafts import config
    from automations.captainship_drafts import knock_dispo_images as KD

    out: Dict[str, List[str]] = {}
    grid = None
    for cap in config.CAPTAINS:
        if only and cap.key != only:
            continue
        try:
            names = KD.owner_names(cap.key, grid)
            if isinstance(names, tuple):   # (names, grid) in some versions
                names, grid = names
            out[cap.key] = list(names)
        except Exception as exc:  # noqa: BLE001 — one captain must not stop the rest
            print("[harvest] ! %s: roster lookup failed (%s: %s)"
                  % (cap.key, type(exc).__name__, exc), flush=True)
    return out


def _is_master(icd: str, aliases_raw) -> bool:
    """Is this ICD the account the session is already logged in as (Raf)?

    Resolved through the alias table against the wkd RAF row, exactly like
    `captainship_drafts.knock_dispo_images.owner_cfgs`, so a re-spelling on the
    Org Sales Board can never make the two reports disagree about who the
    master is.
    """
    try:
        from automations.focus_office_att.aliases import (
            alias_to_canonical, _norm_name)
        from automations.weekly_knock_dispositions.offices import RAF as _RAF
        return _norm_name(alias_to_canonical(icd, aliases_raw)) ==             _norm_name(_RAF["name"])
    except Exception:  # noqa: BLE001 — an unreadable alias sheet is not a master
        return False


def harvest(icds: List[str], *, logfn=print) -> Dict[str, dict]:
    """Impersonate each ICD, read its address. One failure never aborts the rest."""
    from automations.focus_office_att.aliases import load_aliases
    from automations.focus_office_att.run_all_owners import (
        _exit_impersonation, _find_owner_and_impersonate,
        _navigate_to_office_access,
    )
    from automations.focus_office_att.step5_fill_one_owner import page_rqst
    from automations.shared.tableau_patchright import ownerville_session

    aliases_raw = load_aliases()
    results: Dict[str, dict] = {}
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    with ownerville_session(verbose=True) as page:
        for i, icd in enumerate(icds, 1):
            logfn("[harvest] %d/%d %s" % (i, len(icds), icd))
            rec = {"icd": icd, "city": None, "state": None, "zip": None,
                   "zone": None, "confidence": "unknown", "note": ""}
            try:
                # THE MASTER IS NOT IMPERSONATED. The rhidalgo login IS Raf's
                # office, so searching Office Access for his own name finds
                # nothing and the ICD would land in the unresolved pile — with
                # the captain's own office missing from his own email. Same
                # master-vs-impersonate split knock_dispo_images.owner_cfgs
                # makes, and decided the same way so the two cannot disagree.
                master = _is_master(icd, aliases_raw)
                if not _navigate_to_office_access(page):
                    raise RuntimeError("could not reach Office Access (p=901)")
                if not master:
                    rqst, reason = _find_owner_and_impersonate(
                        page, icd, aliases_raw)
                    if not rqst:
                        # The same two shapes the knock boards already
                        # classify: a missing name is an alias problem, a
                        # denial is access.
                        raise RuntimeError(reason)
                # `rqst` is the SESSION token, not an office id — read it off
                # whatever page we are on now. Impersonated or not, p=767 then
                # describes the office the session is currently acting as.
                page.goto(COMPANY_INFO % page_rqst(page), timeout=60000)
                html = page.content()
                # The form first (that is where the address lives), then the
                # text scrape — some pages do print it as prose.
                addr = parse_form(html) or parse_address(page.inner_text("body"))
                if not addr:
                    dump = DEBUG_DIR / ("%s.html"
                                        % re.sub(r"\W+", "-", icd.lower()))
                    dump.write_text(html, encoding="utf-8")
                    # NAME THE FIELDS WE DID SEE. A dump nobody can read costs a
                    # whole round trip per guess; the names are the answer.
                    seen = ", ".join(sorted(form_fields(html))[:25]) or "none"
                    raise RuntimeError("no address on p=767 — raw HTML saved to "
                                       "%s · form fields seen: %s" % (dump, seen))
                rec.update(addr)
                r = addresses.resolve(addr["city"], addr["state"])
                rec.update(zone=r.zone, confidence=r.confidence, note=r.note)
                logfn("           %s, %s -> %s (%s)"
                      % (addr["city"], addr["state"], r.zone or "UNRESOLVED",
                         r.confidence))
            except Exception as exc:  # noqa: BLE001
                rec["note"] = "%s: %s" % (type(exc).__name__, exc)
                logfn("           ! %s" % rec["note"])
            finally:
                try:
                    _exit_impersonation(page)
                except Exception:  # noqa: BLE001 — never strand the session
                    pass
            results[icd] = rec
    return results


def report(results: Dict[str, dict], *, logfn=print) -> None:
    resolved = {k: v for k, v in results.items() if v.get("zone")}
    stuck = {k: v for k, v in results.items() if not v.get("zone")}

    logfn("")
    logfn("=== paste into zones.ICD_TIMEZONES (%d) ===" % len(resolved))
    width = max([len(k) for k in resolved] or [0]) + 4
    for icd in sorted(resolved):
        r = resolved[icd]
        key = '"%s":' % icd
        logfn("    %-*s %s,  # %s, %s"
              % (width, key, '"%s"' % r["zone"], r["city"], r["state"]))

    logfn("")
    logfn("=== NOT resolved (%d) — these stay OUT of the send ===" % len(stuck))
    for icd in sorted(stuck):
        logfn("    %s — %s" % (icd, stuck[icd]["note"]))

    from automations.captainship_night_knocks.zones import ZONE_LABEL
    waves: Dict[str, int] = {}
    for r in resolved.values():
        lab = ZONE_LABEL.get(r["zone"], r["zone"])
        waves[lab] = waves.get(lab, 0) + 1
    logfn("")
    logfn("=== wave sizes ===")
    for lab in ("Eastern", "Central", "Mountain", "Pacific"):
        logfn("    %-9s %d" % (lab, waves.get(lab, 0)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", help="one captain key (rafael, chan, ...)")
    ap.add_argument("--icd", action="append",
                    help="harvest just this ICD; repeatable")
    args = ap.parse_args(argv)

    if args.icd:
        icds = list(args.icd)
    else:
        rosters = captain_rosters(args.only)
        seen, icds = set(), []
        for cap in sorted(rosters):
            for icd in rosters[cap]:
                if icd.lower() not in seen:
                    seen.add(icd.lower())
                    icds.append(icd)
        print("[harvest] %d ICD(s) across %d captainship(s)"
              % (len(icds), len(rosters)), flush=True)

    if not icds:
        print("[harvest] nothing to do — empty roster", flush=True)
        return 1

    results = harvest(icds)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(results, indent=2, sort_keys=True),
                        encoding="utf-8")
    print("[harvest] wrote %s" % OUT_JSON, flush=True)
    report(results)
    return 0 if any(v.get("zone") for v in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
