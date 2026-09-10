"""READ-ONLY sweep: which offices actually knock MORE THAN ONE campaign.

WHY THIS EXISTS. `/knocks` asks which campaign only for the offices named in
`knocks_pull.MULTI_CAMPAIGN`, and that map was hand-written one office at a
time — Jay Turnage, then Carlos Hidalgo, each only after somebody noticed a
board that was half an office (Megan 2026-09-09: "I asked for Carlos' knocks
and it didn't ask me which campaign, even though he runs 2"). Every office not
in it is an assumption, not an observation, and the failure is silent: the
board renders clean, with one campaign's numbers under the office's name.

THE PICKER IS NOT THE ANSWER. Isaiah Revelle's picker offers three campaigns
(BASE Energy / RES AT&T / RES-ENERGYWELL) and he knocks exactly one — Megan
checked his ownerville on 2026-08-25. So "how many options does the dropdown
have" over-reports badly. What settles it is which campaigns come back holding
REPS: a campaign an office does not knock returns an empty grid.

Hence two passes, cheap one first:

  1. Every impersonable office, its picker options + their invD2DClientIds.
     One impersonation and one page read each. Narrows ~50 offices to the
     handful with more than one option.
  2. Only those: pin each id and read the Disposition grid — how many reps
     came back, and which shape. An office is MULTI-CAMPAIGN when two or more
     of its ids return reps.

NOTHING IS WRITTEN TO THE MAP. This prints a proposed MULTI_CAMPAIGN block and
parks the raw findings under output/. A campaign entry is a claim about an
office's real work; it gets read by a person before it ships, the same way
CAMPAIGN_OVERRIDES entries do.

IT TAKES THE MACHINE'S OWNERVILLE SESSION. Impersonation is a property of the
SERVER session and every process on the box shares it, so this refuses to start
while a scheduled report is using ownerville, and drops impersonation on the way
out.

    python -m automations.rashad_metrics.campaign_map --pass1-only
    python -m automations.rashad_metrics.campaign_map --office "Carlos Hidalgo"
    python -m automations.rashad_metrics.campaign_map --headed
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT_DIR = Path(__file__).resolve().parents[2] / "output"


def _log(msg: str) -> None:
    print(f"[campaign-map] {msg}", flush=True)


def _office_access_names(page) -> "list[str]":
    """Every office this login can impersonate, off the Office Access table.

    The roster sheets are the wrong source here: they list the offices we
    REPORT on, and the question is which offices ownerville will let us look
    at. An office we cannot impersonate cannot be probed at all.
    """
    from automations.focus_office_att.run_all_owners import (
        _wait_office_table_loaded,
    )
    _wait_office_table_loaded(page)
    try:
        # Clear the DataTables filter first — a leftover search from an earlier
        # impersonation would silently return a slice of the roster as though
        # it were all of it.
        page.locator("#promotingOffices_filter input").first.fill("")
        page.wait_for_timeout(800)
    except Exception:  # noqa: BLE001 — an unfilterable box is still readable
        pass
    try:
        return page.evaluate(
            "() => [...document.querySelectorAll("
            "'table#promotingOffices tbody tr')]"
            ".map(tr => (tr.querySelectorAll('td')[2]||{}).innerText||'')"
            ".map(s => s.trim()).filter(Boolean)") or []
    except Exception:  # noqa: BLE001
        return []


def _picker_options(page) -> "list[dict]":
    """[{label, id}] from the campaign dropdown, or [] when it has none."""
    from automations.b2b_dispositions import capture as cap
    out = []
    for o in cap.campaign_options(page) or []:
        label = str(o.get("label") or o.get("text") or "").strip()
        cid = str(o.get("id") or o.get("invD2DClientId") or "").strip()
        if label and cid:
            out.append({"label": label, "id": cid})
    # De-duplicated by id: the dropdown repeats an option when the toolbar is
    # rendered twice (narrow viewports do this), which would read as an office
    # running the same campaign twice.
    seen, uniq = set(), []
    for o in out:
        if o["id"] not in seen:
            seen.add(o["id"])
            uniq.append(o)
    return uniq


def _reps_for_campaign(page, rqst: str, cid: str, target: dt.date) -> dict:
    """{reps, shape, error} for one pinned campaign on one day.

    The DAY matters: a campaign an office genuinely knocks still returns an
    empty grid for a day nobody worked it, which reads exactly like a campaign
    it does not knock. The caller probes a spread of days for that reason.
    """
    from automations.rashad_metrics import knocks_pull as KP
    from automations.total_knocks import pull as knocks
    try:
        KP._pin_campaign(page, rqst, cid, verbose=False)
        knocks._navigate(page, rqst, target.strftime("%m/%d/%Y"))
        idx = knocks._header_index(page)
        shape = ("b2b_att" if KP._is_b2b_att_dispo(idx)
                 else "b2b_box" if KP._is_b2b_box_dispo(idx)
                 else "energywell" if KP._is_energywell_dispo(idx)
                 else "wireless" if KP._is_wireless_dispo(idx)
                 else "house")
        reps = page.evaluate(
            "() => document.querySelectorAll("
            "'#table-dispositions tbody tr').length") or 0
        # A DataTables "no matching records" placeholder is ONE row with one
        # cell — not a rep, and counting it would make every dead campaign
        # look alive.
        if reps == 1:
            cells = page.evaluate(
                "() => (document.querySelectorAll("
                "'#table-dispositions tbody tr')[0]||{})"
                ".querySelectorAll ? document.querySelectorAll("
                "'#table-dispositions tbody tr')[0]"
                ".querySelectorAll('td').length : 0") or 0
            if cells <= 1:
                reps = 0
        return {"reps": int(reps), "shape": shape, "error": ""}
    except Exception as e:  # noqa: BLE001 — a probe reports, it never raises
        return {"reps": 0, "shape": "", "error": f"{type(e).__name__}: {e}"}


def _probe_days(count: int) -> "list[dt.date]":
    """Recent FINISHED days, newest first. Two reasons not to start at today,
    which is what `default_target` means: a sweep run at 9am would read every
    campaign as empty and call the whole org single-campaign, and a campaign
    only worked some days looks dead if we ask about one quiet Tuesday."""
    from automations.knocks_request.service import default_target
    out, d = [], default_target() - dt.timedelta(days=1)
    while len(out) < count:
        if d.weekday() < 6:          # Sunday is nobody's knocking day
            out.append(d)
        d -= dt.timedelta(days=1)
    return out


def sweep(offices: "list[str]", *, headless: bool = True,
          pass1_only: bool = False, days: int = 3) -> dict:
    from automations.focus_office_att.aliases import load_aliases
    from automations.focus_office_att.run_all_owners import (
        _exit_impersonation, _find_owner_and_impersonate,
        _navigate_to_office_access,
    )
    from automations.shared.tableau_patchright import ownerville_session

    findings: dict = {}
    probe = _probe_days(days)
    aliases = load_aliases()
    with ownerville_session(headless=headless, verbose=False) as page:
        if not offices:
            _navigate_to_office_access(page)
            offices = _office_access_names(page)
            _log(f"office access lists {len(offices)} office(s)")

        for i, name in enumerate(offices, 1):
            _log(f"[{i}/{len(offices)}] {name}")
            rec: dict = {"options": [], "campaigns": {}, "note": ""}
            findings[name] = rec
            try:
                _exit_impersonation(page)
                _navigate_to_office_access(page)
                rqst, reason = _find_owner_and_impersonate(page, name, aliases)
            except Exception as e:  # noqa: BLE001
                rec["note"] = f"impersonation raised {type(e).__name__}: {e}"
                continue
            if not rqst:
                # ANSWERED, not failed — same rule probe_campaigns follows. An
                # office we cannot reach is a finding, and a non-zero exit here
                # would open an incident against reports that are running fine.
                rec["note"] = f"not reachable — {reason}"
                continue

            rec["options"] = _picker_options(page)
            _log(f"    picker: {[o['label'] for o in rec['options']] or 'none'}")
            if pass1_only or len(rec["options"]) < 2:
                continue

            # Pass 2 — only for an office with something to disambiguate.
            for opt in rec["options"]:
                best = {"reps": 0, "shape": "", "error": ""}
                for day in probe:
                    got = _reps_for_campaign(page, rqst, opt["id"], day)
                    if got["reps"] > best["reps"]:
                        best = dict(got, day=day.isoformat())
                    if got["reps"]:
                        break        # one worked day settles it
                    best["error"] = best["error"] or got["error"]
                rec["campaigns"][opt["id"]] = dict(best, label=opt["label"])
                _log(f"    {opt['label']} (id={opt['id']}): "
                     f"{best['reps']} rep(s) {best.get('shape') or ''}"
                     + (f" — {best['error']}" if best["error"] else ""))
        try:
            _exit_impersonation(page)
        except Exception:  # noqa: BLE001 — best effort on the way out
            pass
    return findings


def _proposed_map(findings: dict) -> "list[str]":
    """The MULTI_CAMPAIGN lines this sweep supports — offices where TWO OR MORE
    campaigns came back holding reps. Printed for a person to read and paste,
    never written: an entry here is a claim about an office's real work."""
    from automations.focus_office_att.aliases import _norm_name
    lines = []
    for name, rec in sorted(findings.items()):
        live = [(c["label"], cid) for cid, c in rec["campaigns"].items()
                if c.get("reps")]
        if len(live) < 2:
            continue
        opts = ", ".join(
            f'("{lbl}", "{cid}", "{_keyword(lbl)}")' for lbl, cid in live)
        lines.append(f'    "{_norm_name(name)}": [{opts}],')
    return lines


def _keyword(label: str) -> str:
    """The word someone would type for this campaign in a DM ("box", "att").
    A suggestion for the human reading the proposal, not a decision."""
    low = label.lower()
    for word in ("box", "energywell", "energy well", "att", "at&t", "primo",
                 "water", "base"):
        if word in low:
            return word.replace(" ", "").replace("&", "")
    return "".join(ch for ch in low if ch.isalnum())[:12]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="READ-ONLY: find the offices that knock more than one "
                    "campaign. Writes nothing but a report under output/.")
    ap.add_argument("--office", action="append", default=[],
                    help="probe only this office (repeatable). Default: every "
                         "office this login can impersonate.")
    ap.add_argument("--pass1-only", action="store_true",
                    help="read pickers only — no per-campaign grid reads. "
                         "Much faster, and over-reports (Isaiah's picker "
                         "offers three campaigns; he knocks one).")
    ap.add_argument("--days", type=int, default=3,
                    help="how many recent days to try before calling a "
                         "campaign empty (default 3)")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument("--force", action="store_true",
                    help="run even while a scheduled report holds ownerville")
    a = ap.parse_args()

    # ONE OWNERVILLE SESSION PER MACHINE, and this sweep impersonates ~50
    # offices in a row. Started next to the 4am batch it would retarget every
    # office those reports are mid-pull on.
    from automations.knocks_request import service
    busy = service.ownerville_busy()
    if busy and not a.force:
        _log(f"REFUSING: ownerville is in use by {', '.join(busy)}. This "
             "sweep impersonates office after office and every process on "
             "this machine shares the one server session — it would retarget "
             "theirs mid-pull. Re-run when they're done, or --force if you "
             "know they're not really running.")
        return 0

    findings = sweep(a.office, headless=not a.headed,
                     pass1_only=a.pass1_only, days=a.days)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"campaign-map-{dt.date.today().isoformat()}.json"
    out.write_text(json.dumps(findings, indent=2), encoding="utf-8")
    _log(f"findings -> {out}")

    many = [n for n, r in findings.items() if len(r["options"]) > 1]
    unreachable = [n for n, r in findings.items() if r["note"]]
    _log(f"{len(findings)} office(s) probed; {len(many)} offer more than one "
         f"campaign; {len(unreachable)} unreachable")
    if unreachable:
        _log("unreachable (needs an alias, or Office Access): "
             + ", ".join(unreachable))

    if a.pass1_only:
        _log("pass 1 only — a picker with two options is a CANDIDATE, not a "
             "multi-campaign office. Re-run without --pass1-only on: "
             + (", ".join(many) or "nothing"))
        return 0

    lines = _proposed_map(findings)
    if lines:
        _log("PROPOSED knocks_pull.MULTI_CAMPAIGN entries — read them, then "
             "paste the ones that match what these offices actually run:")
        print("\n".join(lines))
    else:
        _log("no office had two campaigns come back with reps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
