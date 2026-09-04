"""READ-ONLY: which ALLTEAMWireless view does Raf actually get, and who is in it?

WHY (2026-09-04). `owners_metrics_churn` flagged Cruz Venegas and Max Powell as
WENT DARK on `Churn - Luis Salazar (B2B)` — on the tab with recent history,
absent from Luis's pull, and absent from the org-wide backfill too. That last
part is what makes it look like they simply sell no wireless, which would be a
one-line roster pin (`captainship_pins.NOT_IN_SOURCE`), the same call Eve made
for Gary Whitaker II the day before.

Then Megan opened ALLTEAMWireless and saw BOTH of them in it — at

    .../CHURNRATES/16d47259-17b6-4ad0-8fd7-2de5081945b0/ALLTEAMWireless

while `pull.B2B_ALLTEAM_URL` has pulled

    .../CHURNRATES/f800acd5-c7aa-4600-9a8c-522cd61af026/ALLTEAMWireless

since 754b5b4 (2026-08-19). Same workbook, same view NAME, different saved
view. If the code is reading a narrower copy, nobody is missing from the source
at all and the pin would have hidden a real bug — permanently, and for whoever
goes dark next.

WHY THIS CANNOT BE SETTLED FROM A BROWSER OR A LAPTOP. Tableau custom views are
PER USER. Megan sees hers; `owners_metrics_churn` pulls on Lucy 1 as **Raf**. A
GUID that resolves for her may not resolve for him — that is exactly how the
four B2B captainship views died on 2026-09-03. So the question is not "is
16d47259 the better view", it is "what does RAF get when he asks for it", and
only Raf's own session can answer. Swapping the URL on the strength of someone
else's browser would risk all four B2B tabs to fix one.

WHAT IT DOES — nothing but look:
  1. loads each GUID as Raf and reports whether it resolves at all (and any
     "re-create the custom view" banner, which NAMES a dead view);
  2. downloads the 'ICD Churn' crosstab off each, exactly the way the real
     backfill does (same driver, same worksheet, same WIRELESS product param);
  3. says, per view, how many owners came back and whether CRUZ VENEGAS and
     MAX POWELL are among them — the actual question;
  4. diffs the two owner lists, so "narrower copy" is a fact rather than a
     theory.

Writes NO Sheet, posts NO Slack, writes NO manifest. Output is a verdict block
in the log plus raw CSVs under output/allteam_guid_probe/.

MUST RUN ON LUCY 1. The Tableau SSO rides ownerville, which allows ONE session
per account, so running it from a laptop evicts Lucy 1's session holder and
pauses every report on the box.

    lucy rerun allteam_guid_probe --machine "Lucy 1"
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from automations.shared.tableau_patchright import (
    tableau_session, download_crosstab_patchright)
from automations.owners_metrics_churn import pull

OUT = Path(__file__).resolve().parents[2] / "output" / "allteam_guid_probe"

_SITE = "https://us-east-1.online.tableau.com/#/site/sci/views/"
_WB = "ATTTRACKER-B2B/CHURNRATES"

# The two candidates, each with the SAME wireless product param the real pull
# appends — so any difference is the saved view, not the filter we send.
CODE_GUID = "f800acd5-c7aa-4600-9a8c-522cd61af026"
MEGAN_GUID = "16d47259-17b6-4ad0-8fd7-2de5081945b0"

CANDIDATES = [
    ("code", "what pull.B2B_ALLTEAM_URL uses today", CODE_GUID),
    ("megan", "the one Megan opened and saw both reps in", MEGAN_GUID),
]

# The two names the whole question is about, normalised for comparison.
LOOKING_FOR = ("cruz venegas", "max powell")


def _url(guid: str) -> str:
    return pull._wireless(f"{_SITE}{_WB}/{guid}/ALLTEAMWireless?:iid=1")


def log(msg: str = "") -> None:
    print(msg, flush=True)


def _loads(pg, url: str, tag: str) -> dict:
    """Does this view open for THIS user, and does Tableau complain about it?

    Deliberately does not download here — a failed Crosstab dialog stays open
    and hangs every later click, so looking and fetching stay separate (the
    lesson probe_b2b_views records)."""
    info: dict = {"tag": tag, "url": url, "opened": False, "toast": ""}
    try:
        pg.goto(url, wait_until="domcontentloaded")
    except Exception as e:  # noqa: BLE001
        info["error"] = f"goto: {type(e).__name__}: {e}"
        return info
    viz = pg.frame_locator('iframe[title="Data Visualization"]')
    try:
        viz.locator(
            '[data-tb-test-id="viz-viewer-toolbar-button-download"]'
        ).wait_for(state="visible", timeout=90_000)
        info["opened"] = True
    except Exception as e:  # noqa: BLE001
        info["error"] = f"toolbar never appeared: {type(e).__name__}"
    pg.wait_for_timeout(4_000)
    # The banner NAMES a broken custom view — the string production runs throw
    # away, and the one that tells a dead GUID from a healthy one.
    try:
        toast = viz.locator('[data-tb-test-id^="banner-error-toast"]')
        if toast.count():
            info["toast"] = " | ".join(
                " ".join((toast.nth(i).inner_text() or "").split())
                for i in range(min(toast.count(), 4)))
    except Exception:  # noqa: BLE001
        pass
    try:
        pg.screenshot(path=str(OUT / f"{tag}.png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass
    return info


def _fetch(url: str, tag: str, page) -> dict:
    """Download 'ICD Churn' the way the real backfill does and list its owners.

    `page` is NOT optional — see probe_b2b_views._try_download: without the
    shared page the driver opens its own session inside this sync context and
    dies with an asyncio error that reads exactly like Tableau refusing the
    URL."""
    tmp = Path(tempfile.gettempdir()) / f"probe_allteam_{tag}.csv"
    res: dict = {"tag": tag, "url": url, "downloaded": False}
    try:
        download_crosstab_patchright(url, pull.WORKSHEET, tmp, verbose=False,
                                     page=page)
        res["downloaded"] = True
    except Exception as e:  # noqa: BLE001
        res["error"] = " ".join(str(e).split())[:600]
        return res
    try:
        parsed = pull.parse_b2b(tmp)
        owners = sorted(parsed.get("reps", {}))
        res["owners"] = owners
        res["n_owners"] = len(owners)
        low = {o.lower(): o for o in owners}
        res["found"] = {name: low.get(name) for name in LOOKING_FOR}
        (OUT / f"{tag}.csv").write_bytes(tmp.read_bytes())
    except Exception as e:  # noqa: BLE001
        res["parse_error"] = f"{type(e).__name__}: {e}"
    return res


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"loads": [], "fetches": []}

    with tableau_session(verbose=False) as pg:
        log("=== 1. does each GUID resolve for THIS user (Raf on Lucy 1)? ===")
        for tag, why, guid in CANDIDATES:
            info = _loads(pg, _url(guid), tag)
            report["loads"].append(info)
            log(f"  [{tag}] {why}")
            log(f"      guid   : {guid}")
            log(f"      opened : {info['opened']}"
                + (f"  ({info['error']})" if info.get("error") else ""))
            if info.get("toast"):
                log(f"      BANNER : {info['toast'][:300]}")

        log("")
        log("=== 2. who comes back from each (same driver as the backfill) ===")
        for tag, _why, guid in CANDIDATES:
            res = _fetch(_url(guid), tag, pg)
            report["fetches"].append(res)
            if not res["downloaded"]:
                log(f"  [{tag}] DOWNLOAD FAILED — {res.get('error')}")
                continue
            if res.get("parse_error"):
                log(f"  [{tag}] parsed nothing — {res['parse_error']}")
                continue
            log(f"  [{tag}] {res['n_owners']} owner(s)")
            for name in LOOKING_FOR:
                hit = (res.get("found") or {}).get(name)
                log(f"      {name.title():<14}: "
                    + (f"PRESENT as {hit!r}" if hit else "ABSENT"))

    log("")
    log("=== 3. verdict ===")
    by = {f["tag"]: f for f in report["fetches"]}
    code, megan = by.get("code", {}), by.get("megan", {})

    def _has_both(f):
        return bool(f.get("found")) and all((f["found"] or {}).get(n)
                                            for n in LOOKING_FOR)

    if not megan.get("downloaded"):
        log("  Megan's GUID does NOT work for Raf — the swap is OFF the table. "
            "Custom views are per-user; hers is not his. The reps' absence "
            "from HIS source stands, so this is a roster call after all "
            "(captainship_pins.NOT_IN_SOURCE), or her view needs sharing.")
    elif _has_both(megan) and not _has_both(code):
        log("  SWAP IT. Megan's GUID resolves for Raf AND carries both reps; "
            "the code's does not. Nobody is missing from the source — the "
            "backfill has been reading a narrower copy. A pin here would have "
            "hidden a real bug for whoever goes dark next.")
    elif _has_both(megan) and _has_both(code):
        log("  BOTH carry them — the GUID is NOT the cause. Look again at the "
            "went-dark path itself (alias resolution, or the parse dropping "
            "rows with no pct).")
    else:
        log("  Neither view carries both reps for Raf. The GUID is a red "
            "herring and the roster pin is the right fix after all.")

    if code.get("downloaded") and megan.get("downloaded"):
        a, b = set(code.get("owners") or []), set(megan.get("owners") or [])
        log(f"  owners: code={len(a)}  megan={len(b)}")
        only_m, only_c = sorted(b - a), sorted(a - b)
        log(f"  in MEGAN's only ({len(only_m)}): {only_m[:12]}"
            + (" …" if len(only_m) > 12 else ""))
        log(f"  in CODE's only  ({len(only_c)}): {only_c[:12]}"
            + (" …" if len(only_c) > 12 else ""))

    (OUT / "probe.json").write_text(json.dumps(report, indent=2))
    log("")
    log(f"  raw: {OUT}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
