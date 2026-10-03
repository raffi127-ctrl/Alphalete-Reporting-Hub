"""Each owner's ACTIVE reps, read inside their own OwnerVille office.

READ-ONLY. One ownerville session (rhidalgo), then for every office on the
Office Access list whose action reads "View" (= granted): impersonate it, ask
the same getRepList endpoint the Mobrium List uses (one POST, every active rep,
no 25-row DataTable page), and exit the impersonation. Offices still at "Send
Request" / "Request Sent" can't be read and are returned as such, so the
summary can say why an owner got no DM.

The rep's OwnerVille id (personpk) is kept: retiring a rep later needs it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from automations.owner_rep_audit import config as C

PROFILE_DIR = (Path(__file__).resolve().parents[1] / "uploaded"
               / ".browser_profile_owner_rep_audit")


@dataclass
class OfficeRoster:
    office: str              # OwnerVille account number
    owner: str
    company: str
    access: str              # "granted" | "pending" | "error"
    reps: List[dict] = field(default_factory=list)   # {id, name, email}
    note: str = ""


def granted(action: str) -> bool:
    a = (action or "").strip().lower()
    return bool(a) and "request" not in a


def _active_reps(page, rqst: str) -> List[dict]:
    from automations.mobrium_list import ownerville as OV
    data = OV._post(page, rqst, OV.ROSTERS["active"], 0, OV.PAGE_SIZE)
    rows = data.get("data") or []
    total = int(data.get("recordsTotal") or 0)
    if len(rows) < total:
        # A short roster would DM an owner half their people. Refuse.
        raise OV.OwnervilleError(f"only {len(rows)} of {total} active reps")
    out = []
    for d in rows:
        name = f"{OV._clean(d.get('fname'))} {OV._clean(d.get('lname'))}".strip()
        if name:
            out.append({"id": OV._clean(d.get("personpk")), "name": name,
                        "email": OV._clean(d.get("email")).lower()})
    return sorted(out, key=lambda r: r["name"].lower())


def _impersonate(page, office: str) -> Optional[str]:
    """On p=901: find the row by account number, confirmImpersonate, return
    the impersonated rqst (None if it didn't take)."""
    from automations.focus_office_att import run_all_owners as R
    R._wait_office_table_loaded(page)
    page.locator("#promotingOffices_filter input").first.fill(office)
    page.wait_for_timeout(900)
    row = None
    for tr in page.locator("table#promotingOffices tbody tr").all():
        cells = tr.locator("td").all()
        if cells and cells[0].inner_text().strip() == office:
            row = tr
            break
    if row is None:
        return None
    btn = row.locator("td").last.locator("button, a").first
    office_id = btn.get_attribute("data-officeid", timeout=4000) or ""
    rqst = R.page_rqst(page)
    if not (office_id and rqst):
        return None
    ok = page.evaluate(
        """({officeId, rqst}) => (async () => {
            const r = await fetch("components/promotions/promotions.cfc", {
              method: "POST", credentials: "same-origin",
              headers: {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "X-Requested-With": "XMLHttpRequest"},
              body: new URLSearchParams({rqst, officeid: officeId,
                                         method: "confirmImpersonate"}).toString()});
            try { const j = JSON.parse(await r.text());
                  return !!(j && j.data && j.data.success); } catch (e) { return false; }
        })()""", {"officeId": office_id, "rqst": rqst})
    if not ok:
        return None
    page.goto(f"https://v2.ownerville.com/index.cfm?p=2&rqst={rqst}",
              wait_until="domcontentloaded", timeout=20000)
    return R.page_rqst(page)


def read_all(only: Optional[List[str]] = None, logfn=print) -> List[OfficeRoster]:
    """Every office on the Office Access list (minus SKIP_OFFICES), with its
    active reps when access is granted. `only` = account numbers to limit to."""
    from automations.focus_office_att import run_all_owners as R
    from automations.knocks_access_watch import audit as A
    from automations.shared.tableau_patchright import ownerville_session

    out: List[OfficeRoster] = []
    with ownerville_session(verbose=True, profile_dir=PROFILE_DIR) as page:
        table = A.read_office_access(page)
        for r in table:
            office, company, owner = (r + ["", "", ""])[:3]
            office = office.strip()
            if office in C.SKIP_OFFICES or (only and office not in only):
                continue
            ro = OfficeRoster(office, owner.strip(), company.strip(),
                              "granted" if granted(r[-1]) else "pending")
            out.append(ro)
            if ro.access != "granted":
                ro.note = (r[-1] or "").strip()
                continue
            try:
                if not R._navigate_to_office_access(page):
                    raise RuntimeError("couldn't reach Office Access")
                rqst = _impersonate(page, office)
                if not rqst:
                    raise RuntimeError("impersonation didn't take")
                ro.reps = _active_reps(page, rqst)
                logfn(f"  {office} {ro.owner}: {len(ro.reps)} active reps")
            except Exception as e:  # noqa: BLE001 — one office never kills the rest
                ro.access, ro.note = "error", f"{type(e).__name__}: {e}"[:200]
                logfn(f"  ⚠ {office} {ro.owner}: {ro.note}")
            finally:
                R._exit_impersonation(page)
    return out


def dump(rosters: List[OfficeRoster], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([r.__dict__ for r in rosters], indent=1),
                    encoding="utf-8")
