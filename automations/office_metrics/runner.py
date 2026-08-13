"""Generic single-office daily-metrics runner.

  python -m automations.office_metrics.runner --office rashad            # plan
  python -m automations.office_metrics.runner --office rashad --dry-run  # pull, no post
  python -m automations.office_metrics.runner --office rashad --live     # post as Lucy
  python -m automations.office_metrics.runner --office rashad --only churn
  python -m automations.office_metrics.runner --office aya --check       # validate table

One office's config lives in offices.py; this file is the same for every office.
It replaces the hand-copied rashad_metrics/aya_metrics runners (which now shim in
here) so the eight-metric logic can't drift between offices. The eight metrics:
FOUR pull an org-wide view and filter to --owner (order_log, sales_6plus, cancels,
disconnects — need only the owner name), THREE pull the office's own ICD-scoped
Tableau views (ongoing_cancel, churn, abp), ONE scrapes ownerville (knocks).

Continue-on-failure: any metric that crashes/times-out is skipped, the rest run;
a partial run exits 0 (so the orchestrator doesn't retry the whole --live run and
double-post) but records the misses in the manifest, which flips the Hub pill to
orange and scopes an --only retry.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from automations.office_metrics import offices as _off
from automations.office_metrics.offices import Office

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
PER_METRIC_TIMEOUT_S = 20 * 60

# Per-office ✅/❌ results for TODAY, read by the ONE Hub card's checklist
# (dashboard._channel_status). Mirrors the Tableau trackers' _posted_today.json:
# one card covering many destinations is only safe if the card shows which
# office missed — a single red light would hide a lone office failing.
OFFICE_STATUS_FILE = REPO_ROOT / "output" / "office_metrics" / "_posted_today.json"

# The main #alphalete-sales report is the SAME 11 metrics for Raf's LOCAL
# OFFICE, but it predates this runner and still lives in its own module with its
# own CLI (live by default, --only takes a comma list). Megan 2026-07-16 wants it
# on the ONE shared card as the first office, so --all runs it too and it gets a
# checklist row. Its internals are NOT migrated into offices.py: its knocks
# module doesn't impersonate an office and its views differ, so folding it in
# properly is a separate proof-gated job — not worth risking the main report to
# save a button.
MAIN_OFFICE_LABEL = "Raf's Local Office"
MAIN_OFFICE_CHANNEL = "#alphalete-sales"
MAIN_OFFICE_MODULE = "automations.daily_metrics.run"


def status_label(label: str, channel_name: str) -> str:
    """The one true checklist-row key for an office (also used by the main
    report's module, so its row lands in the same place)."""
    return f"{label} — {channel_name}"


def _status_order() -> dict:
    """Checklist order: the main office first, then the registry's order — so
    the card reads as a stable roster, not finish order."""
    order = {status_label(MAIN_OFFICE_LABEL, MAIN_OFFICE_CHANNEL): 0}
    for i, k in enumerate(_off.ORDER):
        o = _off.OFFICES[k]
        order[status_label(o.label, o.channel_name)] = i + 1
    return order


def record_status(label: str, channel_name: str, *, ok: bool,
                  error: str = "") -> None:
    """Record ONE office's outcome in the shared per-office status file.

    Read-modify-write keyed by the office's label, so each office's run (4am
    orchestrator OR a manual card button) updates only its own row and the card
    shows the whole roster. Resets when the file is from an earlier day, so a
    stale checklist can never read as today's. Best-effort — a status-file
    hiccup must never fail an otherwise-good run."""
    try:
        OFFICE_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        today = dt.date.today().isoformat()
        data = {}
        if OFFICE_STATUS_FILE.exists():
            try:
                data = json.loads(OFFICE_STATUS_FILE.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                data = {}
        if data.get("date") != today:
            data = {"date": today, "channels": []}
        key = status_label(label, channel_name)
        rows = [r for r in (data.get("channels") or []) if r.get("label") != key]
        rows.append({"label": key, "ok": bool(ok), "error": (error or "")[:200]})
        order = _status_order()
        rows.sort(key=lambda r: order.get(r.get("label", ""), 99))
        data["channels"] = rows
        OFFICE_STATUS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 — never fail the run over the checklist
        pass


def _record_office_status(o: Office, *, ok: bool, error: str = "") -> None:
    """record_status for a registry Office."""
    record_status(o.label, o.channel_name, ok=ok, error=error)


# Harvest-once CANARY for the Order Log ALLREPS pull — office keys whose order_log
# metric reads the primed cache instead of scraping. The ALLREPS "A.Order Log"
# crosstab is byte-identical across all 8 offices (proof_order_log VERDICT
# IDENTICAL, 2026-07-29) and harvest_prime warms it before these run, so serving
# it from cache is safe. Rolling out ONE office first (mirrors the churn canary
# that flipped daily_metrics only): this set reads cache; the other 7 stay live
# until a morning is watched. Widen by adding keys; EMPTY set = full rollback to
# live. Fail-safe regardless: a cache miss / stale / any error → live scrape.
_HARVEST_ORDER_LOG_OFFICES = {"rashad"}


def _nds_metrics(o: Office) -> list[dict]:
    """Boards for an NDS owner — sourced from the NDS-SN (RES-ATT-OOF) workbook,
    NOT the ATT-D2D one the standard boards pull (an NDS owner isn't in that book,
    so those come back blank). Built incrementally; a board not yet wired is simply
    absent from the thread. Same dict shape as metrics_for so build_destinations /
    _run_one treat them identically. SECTION_OVERRIDES still gates which post."""
    return [
        # 🕐 Time Gaps — knocks_run renders gaps-only when the Disposition is empty
        # (every NDS owner: no door-knock campaign). Skips the blank Total Knocks.
        dict(slug="knocks_gaps", label="🕐 Time Gaps",
             module="automations.rashad_metrics.knocks_run", owner_args=[],
             env={"KNOCKS_OFFICE": o.knocks_office},
             retry_on_fail=1, dry_flag="--dry-run", post_flag="--live"),
        # 📊 Wireless Churn — per-rep, day-over-day. nds_churn slices the shared
        # ChurnALlExp view to this owner + fills THIS office's own churn tab, so
        # CHURN_SHEET_ID must be the office's sheet (else it defaults to Isaiah's).
        dict(slug="churn", label="📊 Wireless Churn",
             module="automations.office_metrics.nds_churn",
             owner_args=["--owner", o.owner],
             env={"CHURN_SHEET_ID": o.sheet_id},
             dry_flag="--dry-run", post_flag="--live"),
        # 🆕 Rep Activations — the house two-week Posted/Pending/Total/Canceled
        # summary (rep_activations pipeline), built from the NDS ORDER LOG current
        # window. slug 'rep_activations' (NOT 'activations') dodges the
        # OWNER_KEY_TO_SLUG activations->order_log override mapping.
        dict(slug="rep_activations", label="🆕 Rep Activations",
             module="automations.office_metrics.nds_orderlog",
             owner_args=["--owner", o.owner, "--board", "rep_summary"], env={},
             dry_flag="--dry-run", post_flag="--live"),
        # 📋 Order Log — the raw wireless order list (kept SEPARATE from Rep
        # Activations per Megan 2026-08-07; every office shows both). Same current
        # window pull.
        dict(slug="order_log", label="📋 Order Log",
             module="automations.office_metrics.nds_orderlog",
             owner_args=["--owner", o.owner, "--board", "order_log"], env={},
             dry_flag="--dry-run", post_flag="--live"),
        dict(slug="cancels", label="🚫 Canceled Orders",
             module="automations.office_metrics.nds_orderlog",
             owner_args=["--owner", o.owner, "--board", "cancels"], env={},
             dry_flag="--dry-run", post_flag="--live"),
        # ❎ Disconnected Orders — wireless (Raf's list). Same ORDER LOG pull,
        # status='Disconnected'. Skips when empty. (6+ days dropped: wireless ships
        # immediately, no scheduled-out installs.)
        dict(slug="disconnects", label="❎ Disconnected Orders",
             module="automations.office_metrics.nds_orderlog",
             owner_args=["--owner", o.owner, "--board", "disconnects"], env={},
             dry_flag="--dry-run", post_flag="--live"),
    ]


def metrics_for(o: Office) -> list[dict]:
    """The eight metrics for one office, built from its config. Shape is identical
    across offices — only the env values (views/sheet/owner) come from `o`."""
    if o.nds:                       # NDS owners get a distinct NDS-sourced set
        return _nds_metrics(o)
    return [
        dict(slug="order_log", label="📋 Order Log / 🆕 Rep Activations",
             module="automations.uploaded.order_log",
             owner_args=["--owner", o.owner],
             # HARVEST_VERBOSE so tomorrow's log shows "served from cache" and we
             # can confirm the canary actually read cache (not just ran clean).
             env=({"HARVEST_MODE": "on", "HARVEST_VERBOSE": "1"}
                  if o.key in _HARVEST_ORDER_LOG_OFFICES else {}),
             dry_flag="--no-slack", post_flag=None),
        dict(slug="sales_6plus", label="📅 Sales Scheduled 6+ Days Out",
             module="automations.scheduled_6_days_out.run",
             owner_args=["--owner", o.owner], env={},
             dry_flag="--dry-run", post_flag="--post-slack"),
        dict(slug="cancels", label="🚫 Canceled Orders",
             module="automations.canceled_orders.run",
             owner_args=["--owner", o.owner], env={},
             dry_flag="--dry-run", post_flag=None),
        dict(slug="ongoing_cancel", label="🔁 Ongoing Cancel",
             module="automations.ongoing_cancel.run", owner_args=[],
             # Once proven, pulls the shared ALL-OFFICE cancel view and slices to
             # this office's owner (recompute rate from summed counts) — no
             # per-office cancel view needed. Else the office's own view.
             env=({"ONGOING_CANCEL_VIEW_URL": _off.ALL_OFFICE_CANCEL_VIEW,
                   "ONGOING_CANCEL_SLICE_OWNER": o.owner}
                  if _off.CANCEL_USE_ALL_OFFICE else
                  {"ONGOING_CANCEL_VIEW_URL": o.view_ongoing_cancel}),
             dry_flag="--dry-run", post_flag=None),
        dict(slug="disconnects", label="❎ Disconnected New Internets",
             module="automations.disconnects.run",
             owner_args=["--owner", o.owner], env={},
             dry_flag="--dry-run", post_flag=None),
        dict(slug="churn", label="🌐 New Internet + 📊 Wireless Churn",
             module="automations.churn.run", owner_args=[],
             # Once proven, churn pulls the two shared ALL-OFFICE views and slices
             # to this office's owner (CHURN_SLICE_OWNER) — no per-office churn
             # views needed. Else the office's own INT<Office>/Wireless<Office>.
             # CHURN_NI_TAB/_WL_TAB: the office's own tab labels when its sheet
             # uses the "Lucy ..." template; empty for the "Local Office - ..."
             # offices, where the fill falls back to its default name.
             env=({"CHURN_NI_VIEW_URL": _off.ALL_OFFICE_CHURN_NI,
                   "CHURN_WL_VIEW_URL": _off.ALL_OFFICE_CHURN_WL,
                   "CHURN_SLICE_OWNER": o.owner,
                   "CHURN_SHEET_ID": o.sheet_id,
                   "CHURN_NI_TAB": o.churn_ni_tab, "CHURN_WL_TAB": o.churn_wl_tab}
                  if _off.CHURN_USE_ALL_OFFICE else
                  {"CHURN_NI_VIEW_URL": o.view_churn_ni,
                   "CHURN_WL_VIEW_URL": o.view_churn_wl,
                   "CHURN_SHEET_ID": o.sheet_id,
                   "CHURN_NI_TAB": o.churn_ni_tab, "CHURN_WL_TAB": o.churn_wl_tab}),
             dry_flag="--dry-run", post_flag=None),
        dict(slug="knocks_gaps", label="🚪 Total Knocks + 🕐 Time Gaps",
             module="automations.rashad_metrics.knocks_run", owner_args=[],
             # knocks_pull reads KNOCKS_OFFICE first (office-agnostic), then the
             # legacy RASHAD_KNOCKS_OFFICE. Use the agnostic one for every office.
             env={"KNOCKS_OFFICE": o.knocks_office},
             # This is the ONLY metric that scrapes ownerville (impersonate →
             # Disposition + Time Tracker). That scrape intermittently times out
             # and, being one subprocess, drops BOTH Knocks + Time Gaps at once
             # with no auto-retry (2026-07-21: 4/7 offices lost both). Give it one
             # fresh-subprocess re-attempt in-run so a first-pass flake self-heals
             # before the thread is finalized. SAFE to retry: knocks_run exits
             # non-zero ONLY when the pull raises — which is before any Slack post
             # — so a re-attempt can't double-post an image that already landed.
             retry_on_fail=1,
             dry_flag="--dry-run", post_flag="--live"),
        dict(slug="abp", label="💳 New Internet ABP %",
             module="automations.new_internet_abp.run", owner_args=[],
             # ABP filters by owner, so once proven it pulls ONE shared all-office
             # view (deduped across offices) instead of a per-office view.
             env={"ABP_NI_VIEW_URL": (_off.ALL_OFFICE_ABP_VIEW
                                      if _off.ABP_USE_ALL_OFFICE else o.view_abp),
                  "ABP_SHEET_ID": o.sheet_id,
                  "ABP_OWNER": o.owner.upper(), "ABP_SUBTITLE": o.label,
                  # office's own ABP tab label ("Lucy ..." template); empty →
                  # the fill's default "Local Office - New Internet ABP%".
                  "ABP_TAB": o.abp_tab},
             dry_flag="--dry-run", post_flag=None),
        dict(slug="tableau_shot", label="📸 Tableau Metrics",
             module="automations.office_metrics.metrics_shot",
             # Screenshot of the ATT TRACKER 2.1 Metrics view SCOPED to this
             # office's owner (Raf 2026-07-16; filter proven on Rashad). Posts
             # into the office thread via the same METRICS_CHANNEL_ID/HEADER_LABEL
             # env every metric inherits, so no per-office wiring.
             owner_args=["--owner", o.owner], env={},
             dry_flag="--dry-run", post_flag="--live"),
    ]


def _metric_cmd(m: dict, *, live: bool) -> list[str]:
    cmd = [sys.executable, "-u", "-m", m["module"], *m["owner_args"]]
    flag = m.get("post_flag") if live else m.get("dry_flag")
    if flag:
        cmd.append(flag)
    return cmd


# Owner-facing ReportKind keys → this runner's metric slugs. Several runner
# metrics BUNDLE two owner concepts into one post — Order Log carries Rep
# Activations, and one Churn post carries both New-Internet and Wireless — so
# multiple keys map to one slug. A channel that asks for EITHER half gets the whole
# combined post (the metrics can't be split; they're one subprocess/one message).
# Keys already equal to a runner slug (and raw slugs) pass through unchanged.
OWNER_KEY_TO_SLUG = {
    "knocks": "knocks_gaps",
    "activations": "order_log",
    "churn_ni": "churn",
    "churn_wl": "churn",
}


def _plan_slugs(plan) -> set:
    """Translate a plan's owner ReportKind keys (or raw runner slugs) to the runner
    slugs used by metrics_for. Unknown values pass through as-is."""
    out = set()
    for k in (plan.get("slugs") or plan.get("report_keys") or []):
        out.add(OWNER_KEY_TO_SLUG.get(k, k))
    return out


def build_destinations(o, wired, target_chan, to_named, *, manual_channel):
    """Where this office's metrics post. Returns (destinations, skipped).

    Default (no channel_plans, or a manual --channel override): ONE destination —
    the office's channel with EVERY wired metric (byte-identical to the old path).
    With channel_plans and no manual override: one destination PER plan, each
    carrying only the wired metrics whose slug is in that plan (the fan-out).

    Each destination: {"channel_id","channel_name","header_label","metrics"}.
    `skipped` is [(channel_name, sorted_slugs)] for plans that matched no wired
    metric (e.g. an --only retry filtered them all out) — the caller logs them.
    Pure (no I/O) so it unit-tests without a Slack/Tableau session.
    """
    plans = tuple(getattr(o, "channel_plans", ()) or ())
    if plans and not manual_channel:
        destinations, skipped = [], []
        for p in plans:
            slugs = _plan_slugs(p)
            subset = [m for m in wired if m["slug"] in slugs]
            if not subset:
                skipped.append((p.get("channel_name") or p.get("channel_id"),
                                sorted(slugs)))
                continue
            destinations.append({
                "channel_id": p["channel_id"],
                "channel_name": p.get("channel_name") or p["channel_id"],
                "header_label": p.get("header_label") or o.header_label,
                "metrics": subset})
        return destinations, skipped
    return [{
        "channel_id": target_chan,
        "channel_name": (o.channel_name if to_named else f"DM/{target_chan}"),
        "header_label": o.header_label,
        "metrics": wired}], []


def _run_one(label: str, cmd: list[str], env: dict) -> tuple[bool, str]:
    print(f"\n{'='*70}\n▶  {label}\n   {' '.join(cmd)}\n{'='*70}", flush=True)
    started = time.monotonic()
    try:
        result = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env,
                                timeout=PER_METRIC_TIMEOUT_S)
        elapsed = time.monotonic() - started
        if result.returncode == 0:
            return True, f"{elapsed:5.0f}s"
        return False, f"exit {result.returncode} after {elapsed:.0f}s"
    except subprocess.TimeoutExpired:
        return False, f"TIMED OUT after {PER_METRIC_TIMEOUT_S//60}m"
    except Exception as e:                      # noqa: BLE001
        return False, f"launch error: {e}"


def _prove_abp(office_key: str, *, headless: bool = False) -> int:
    """Pull the office's per-office ABP view AND the shared all-office view under
    one session, filter BOTH to the office's owner, and diff. The all-office
    slice must byte-match the per-office pull before we trust it. No post."""
    import tempfile
    from pathlib import Path
    from automations.shared.tableau_patchright import tableau_session
    from automations.new_internet_abp import pull as abp_pull

    o = _off.get(office_key)
    d = Path(tempfile.gettempdir())
    print(f"=== ABP all-office proof — office={office_key} owner={o.owner!r} ===",
          flush=True)
    print(f"  per-office view: {o.view_abp}", flush=True)
    print(f"  all-office view: {_off.ALL_OFFICE_ABP_VIEW}", flush=True)
    with tableau_session(headless=headless, allow_form_login=False,
                         verbose=True) as page:
        per_csv = abp_pull.fetch_crosstab(d / f"abp_per_{office_key}.csv",
                                          view_url=o.view_abp, page=page)
        all_csv = abp_pull.fetch_crosstab(d / f"abp_all_{office_key}.csv",
                                          view_url=_off.ALL_OFFICE_ABP_VIEW, page=page)
    per = abp_pull.parse(per_csv, owner=o.owner)
    allo = abp_pull.parse(all_csv, owner=o.owner)

    same_total = per["office_total"] == allo["office_total"]
    all_reps = sorted(set(per["reps"]) | set(allo["reps"]))
    diffs = [r for r in all_reps if per["reps"].get(r) != allo["reps"].get(r)]
    print(f"\n  office_total  per-office: {per['office_total']}", flush=True)
    print(f"  office_total  all-office: {allo['office_total']}", flush=True)
    print(f"  reps: per-office={len(per['reps'])}  all-office(sliced)={len(allo['reps'])}",
          flush=True)
    for r in diffs[:12]:
        print(f"    ⚠ {r!r}: per={per['reps'].get(r)}  all={allo['reps'].get(r)}",
              flush=True)
    ok = same_total and not diffs
    print(f"\n  VERDICT [{office_key}]: "
          + ("IDENTICAL ✅ — safe to flip ABP to all-office"
             if ok else f"MISMATCH ❌ ({'' if same_total else 'office_total; '}"
                        f"{len(diffs)} rep diff) — do NOT flip"), flush=True)
    return 0 if ok else 1


def _inspect_cancel(office_key: str, view_override: str | None = None) -> int:
    """Read-only: pull the office's ongoing-cancel view and report its distinct
    owners + which owners carry a per-owner 'Total' subtotal row. If the office's
    view already shows MANY owners with per-owner Total rows, ongoing-cancel is
    sliceable (read the office's Total row, like ABP). If it shows one owner +
    only a Grand Total, the view is office-scoped and can't be sliced as-is."""
    import csv
    import tempfile
    from pathlib import Path
    from automations.ongoing_cancel import pull as oc_pull

    o = _off.get(office_key)
    oc_pull.VIEW_URL = view_override or o.view_ongoing_cancel
    print(f"=== inspect cancel view [{office_key}] ===\n  {oc_pull.VIEW_URL}",
          flush=True)
    out = Path(tempfile.gettempdir()) / f"oc_inspect_{office_key}.csv"
    oc_pull.fetch_crosstab(out, verbose=True)
    with open(out, "r", encoding="utf-16-le") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    header = [h.lstrip("﻿").strip() for h in rows[0]]
    oi, ri = header.index("Owner Name"), header.index("Rep")
    owners: dict = {}
    total_owners: set = set()          # owner has a subtotal row (rep blank/Total)
    target = o.owner
    target_reps: dict = {}             # rep-value -> count, under the run office
    for r in rows[1:]:
        if len(r) <= ri:
            continue
        own = (r[oi] or "").strip()
        rep = (r[ri] or "").strip()
        if not own:
            continue
        owners[own] = owners.get(own, 0) + 1
        if rep in ("", "Total"):       # a subtotal-shaped row (blank OR 'Total')
            total_owners.add(own)
        if own.upper() == target.upper():
            target_reps[rep or "(blank)"] = target_reps.get(rep or "(blank)", 0) + 1
    print(f"\n  distinct owners: {len(owners)}", flush=True)
    for own, c in sorted(owners.items()):
        mark = "  [has subtotal row]" if own in total_owners else ""
        print(f"    {own!r}: {c} rows{mark}", flush=True)
    print(f"\n  rep values under {target!r} (the run office):", flush=True)
    for rep, c in sorted(target_reps.items()):
        flag = "  <<< SUBTOTAL row" if rep in ("(blank)", "Total") else ""
        print(f"    rep={rep!r}: {c}{flag}", flush=True)
    real = [x for x in owners if x != "Grand Total"]
    tgt_has = target in total_owners or target.upper() in {t.upper() for t in total_owners}
    print(f"\n  VERDICT: {'MULTI-OFFICE' if len(real) > 1 else 'SINGLE-OFFICE'}; "
          f"{len(total_owners)} owner(s) have a subtotal row; "
          f"{target} subtotal row: {'YES ✅' if tgt_has else 'NO ❌'}", flush=True)

    # Do the cells carry counts (cancels/orders) we can sum per office? Dump the
    # header + a couple raw rows under the run office so we can see the schema.
    print(f"\n  === HEADER ({len(header)} cols) ===", flush=True)
    for i, h in enumerate(header):
        print(f"    [{i}] {h!r}", flush=True)
    # Distinct MEASURE names (the column just after the color column) — this tells
    # us whether cancel/order COUNTS exist as summable measures (so we could
    # recompute the office rate like churn), or only the rate does.
    color_i = next((i for i, h in enumerate(header)
                    if h.startswith("Internet Cancel Color")), 2)
    mi = color_i + 1
    measures: dict = {}
    for r in rows[1:]:
        if len(r) > mi:
            measures[(r[mi] or "").strip()] = measures.get((r[mi] or "").strip(), 0) + 1
    print(f"\n  === distinct MEASURES (col [{mi}]) ===", flush=True)
    for m, c in sorted(measures.items()):
        print(f"    {m!r}: {c} rows", flush=True)
    # Dump EVERY measure row for one rep under the target that has non-blank data,
    # so we can see if counts are present + summable.
    print(f"\n  === all measure rows for one active rep under {target!r} ===",
          flush=True)
    picked = None
    for r in rows[1:]:
        if len(r) > mi and (r[oi] or "").strip().upper() == target.upper():
            rep = (r[ri] or "").strip()
            if rep and rep not in ("Total",) and any(c.strip() for c in r[mi+1:mi+4]):
                picked = rep
                break
    if picked:
        for r in rows[1:]:
            if (len(r) > mi and (r[oi] or "").strip().upper() == target.upper()
                    and (r[ri] or "").strip() == picked):
                print(f"    measure={r[mi]!r}  vals={r[mi+1:mi+5]}", flush=True)
    return 0


def _prove_churn(office_key: str) -> int:
    """For each churn view (NI + WL): pull the office's per-office view AND the
    shared all-office view sliced to the office's owner, parse both, and diff
    office_total + every rep. The slice must byte-match before we trust it."""
    import tempfile
    from pathlib import Path
    from automations.shared.tableau_patchright import tableau_session
    from automations.new_internet_churn import pull as ni_pull
    from automations.wireless_churn import pull as wl_pull

    o = _off.get(office_key)
    d = Path(tempfile.gettempdir())
    plan = [("New Internet", ni_pull, o.view_churn_ni, _off.ALL_OFFICE_CHURN_NI),
            ("Wireless", wl_pull, o.view_churn_wl, _off.ALL_OFFICE_CHURN_WL)]
    print(f"=== churn all-office proof — office={office_key} owner={o.owner!r} ===",
          flush=True)
    all_ok = True
    with tableau_session(allow_form_login=False, verbose=True) as page:
        for label, mod, per_view, all_view in plan:
            os.environ.pop("CHURN_SLICE_OWNER", None)     # per-office = no slice
            mod.VIEW_URL = per_view
            per_csv = mod.fetch_crosstab(d / f"churn_per_{label[:2]}_{office_key}.csv",
                                         page=page)
            per = mod.parse(per_csv)
            os.environ["CHURN_SLICE_OWNER"] = o.owner      # all-office = slice
            mod.VIEW_URL = all_view
            all_csv = mod.fetch_crosstab(d / f"churn_all_{label[:2]}_{office_key}.csv",
                                         page=page)
            allo = mod.parse(all_csv)
            os.environ.pop("CHURN_SLICE_OWNER", None)

            ot_same = per["office_total"] == allo["office_total"]
            rep_keys = sorted(set(per["reps"]) | set(allo["reps"]))
            rep_diffs = [k for k in rep_keys if per["reps"].get(k) != allo["reps"].get(k)]
            ok = ot_same and not rep_diffs
            all_ok &= ok
            print(f"\n  [{label}] office_total match: {ot_same}  "
                  f"reps per={len(per['reps'])} all={len(allo['reps'])}  "
                  f"rep diffs: {len(rep_diffs)}", flush=True)
            if not ot_same:
                print(f"     per office_total: {per['office_total']}", flush=True)
                print(f"     all office_total: {allo['office_total']}", flush=True)
            for k in rep_diffs[:6]:
                print(f"     ⚠ rep {k!r}: per={per['reps'].get(k)} all={allo['reps'].get(k)}",
                      flush=True)
            print(f"  VERDICT [{label}]: {'IDENTICAL ✅' if ok else 'MISMATCH ❌'}",
                  flush=True)
    print(f"\n=== CHURN PROOF [{office_key}]: "
          f"{'ALL IDENTICAL ✅ — safe to flip' if all_ok else 'MISMATCH ❌ — do NOT flip'} ===",
          flush=True)
    return 0 if all_ok else 1


def _prove_cancel(office_key: str) -> int:
    """Pull the office's per-office ongoing-cancel view AND the shared all-office
    view sliced to the office, parse both, and diff the reps + the recomputed
    office total. The slice must match the per-office view before we trust it."""
    import tempfile
    from pathlib import Path
    from automations.ongoing_cancel import pull as oc_pull

    o = _off.get(office_key)
    d = Path(tempfile.gettempdir())
    print(f"=== ongoing-cancel all-office proof — office={office_key} "
          f"owner={o.owner!r} ===", flush=True)
    os.environ.pop("ONGOING_CANCEL_SLICE_OWNER", None)      # per-office = no slice
    oc_pull.VIEW_URL = o.view_ongoing_cancel
    per = oc_pull.parse(oc_pull.fetch_crosstab(d / f"oc_per_{office_key}.csv"))
    os.environ["ONGOING_CANCEL_SLICE_OWNER"] = o.owner       # all-office = slice
    oc_pull.VIEW_URL = _off.ALL_OFFICE_CANCEL_VIEW
    allo = oc_pull.parse(oc_pull.fetch_crosstab(d / f"oc_all_{office_key}.csv"))
    os.environ.pop("ONGOING_CANCEL_SLICE_OWNER", None)

    # The two views may show different date WINDOWS (custom-view date filters), so
    # compare only the days they share — a window shift is benign, a value diff
    # on a shared day is a real slice error.
    print(f"\n  per-office days: {per['days']}", flush=True)
    print(f"  all-office days: {allo['days']}", flush=True)
    shared = [d for d in per["days"] if d in set(allo["days"])]
    print(f"  shared days: {shared}", flush=True)
    per_rows = {r["rep"]: r["per_day"] for r in per["rows"]}
    all_rows = {r["rep"]: r["per_day"] for r in allo["rows"]}

    def _on_shared(pd):
        return {d: pd[d] for d in shared if d in pd}
    gt_same = ({d: per["grand_total_per_day"].get(d) for d in shared}
               == {d: allo["grand_total_per_day"].get(d) for d in shared})
    keys = sorted(set(per_rows) | set(all_rows))
    row_diffs = [k for k in keys if _on_shared(per_rows.get(k, {}))
                 != _on_shared(all_rows.get(k, {}))]
    ok = bool(shared) and gt_same and not row_diffs
    print(f"\n  office total match (shared days): {gt_same}  reps per={len(per_rows)} "
          f"all={len(all_rows)}  rep diffs: {len(row_diffs)}", flush=True)
    if not gt_same:
        print(f"    per office total: "
              f"{ {d: per['grand_total_per_day'].get(d) for d in shared} }", flush=True)
        print(f"    all office total: "
              f"{ {d: allo['grand_total_per_day'].get(d) for d in shared} }", flush=True)
    for k in row_diffs[:6]:
        print(f"    ⚠ rep {k!r}: per={_on_shared(per_rows.get(k, {}))} "
              f"all={_on_shared(all_rows.get(k, {}))}", flush=True)
    print(f"\n=== CANCEL PROOF [{office_key}]: "
          f"{'IDENTICAL ✅ — safe to flip' if ok else 'MISMATCH ❌ — do NOT flip'} ===",
          flush=True)
    return 0 if ok else 1


def _inspect_churn(view_url: str) -> int:
    """Read-only: pull a churn view and dump its distinct ICD Owner Name (rep)
    values, so we can confirm it's genuinely all-office (contains Rashad, Aya,
    and the rest) before slicing it."""
    import csv
    import tempfile
    from pathlib import Path
    from automations.new_internet_churn import pull as ni_pull

    ni_pull.VIEW_URL = view_url
    print(f"=== inspect churn view ===\n  {view_url}", flush=True)
    out = Path(tempfile.gettempdir()) / "churn_inspect.csv"
    ni_pull.fetch_crosstab(out, verbose=True)
    with open(out, "r", encoding="utf-16-le") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    header = [h.lstrip("﻿").strip() for h in rows[0]]
    oi = header.index("ICD Owner Name (rep)")
    ri = header.index("Rep Name")
    owners: dict = {}
    total_owners: set = set()          # owners with a per-office Rep Name=='Total' row
    for r in rows[1:]:
        if len(r) <= max(oi, ri):
            continue
        own = (r[oi] or "").strip()
        rep = (r[ri] or "").strip()
        if own:
            owners[own] = owners.get(own, 0) + 1
            if rep == "Total":
                total_owners.add(own)
    real = [o for o in owners if o not in ("Grand Total",)]
    print(f"\n  distinct ICD owners: {len(owners)}", flush=True)
    for who in ("Rashad Reed", "Aya Al-Khafaji", "Cyrus Wade", "Hammad Haque",
                "Muhammad UI Haque", "Kash Rai", "Akashdeep Rai",
                "Salik Mallick", "Muhammad Waqar"):
        present = any(o.upper() == who.upper() for o in owners)
        print(f"  {who}: {'PRESENT ✅' if present else 'absent'}", flush=True)
    # show the tail of the owner list — if truncated, later-alphabet names drop
    print(f"  owner sample (last 6): {sorted(owners)[-6:]}", flush=True)
    print(f"\n  owners with a per-office Total row: {len(total_owners)} "
          f"(of {len(real)} offices)", flush=True)
    print(f"  VERDICT: {'ALL-OFFICE' if len(real) > 1 else 'SINGLE-OFFICE'} "
          f"({len(real)} offices); "
          f"{'per-office Totals present → read directly' if len(total_owners) > 1 else 'no per-office Totals → recompute from reps'}",
          flush=True)
    return 0


def main(argv=None, *, office_key: str | None = None) -> int:
    ap = argparse.ArgumentParser(prog="office_metrics")
    ap.add_argument("--office", default=office_key,
                    help="office key (see offices.py). Required unless a shim "
                         "passed it in, or --all.")
    ap.add_argument("--all", action="store_true", dest="all_offices",
                    help="run EVERY office in offices.ORDER, in order, "
                         "continuing past one that fails. Powers the Hub card's "
                         "'Run All Offices' button. Each office still posts to "
                         "its OWN channel and writes its own manifest.")
    ap.add_argument("--live", action="store_true",
                    help="pull + POST to the office's channel as Lucy.")
    ap.add_argument("--dry-run", action="store_true",
                    help="pull + render, DO NOT post. Real Tableau pulls — run "
                         "on the mini.")
    ap.add_argument("--only", default=None, help="run a single metric by slug.")
    ap.add_argument("--channel", default=None,
                    help="override the destination (channel/DM id, or a comma-"
                         "separated list of user ids for a review group-DM).")
    ap.add_argument("--check", action="store_true",
                    help="validate the whole office table and exit (no pull, no "
                         "post).")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore the shared crosstab cache and re-pull every view "
                         "live (use if a cached org-wide pull went bad).")
    ap.add_argument("--prove-abp", action="store_true",
                    help="cell-for-cell proof that the shared all-office ABP view, "
                         "sliced to this office's owner, matches the office's "
                         "current per-office ABP view. No post. Run before "
                         "flipping ABP_USE_ALL_OFFICE on.")
    ap.add_argument("--inspect-cancel", action="store_true",
                    help="read-only: pull the ongoing-cancel view and dump its "
                         "distinct owners + which have a per-owner 'Total' "
                         "subtotal row (decides whether it's sliceable).")
    ap.add_argument("--cancel-view", default=None,
                    help="with --inspect-cancel: inspect THIS view URL instead of "
                         "the office's per-office view (e.g. an all-office "
                         "candidate).")
    ap.add_argument("--inspect-churn", default=None, metavar="VIEW_URL",
                    help="read-only: pull this churn view and dump its distinct "
                         "ICD Owner Name (rep) values (is it all-office?).")
    ap.add_argument("--prove-churn", action="store_true",
                    help="cell-for-cell proof that the all-office churn views "
                         "(NI + WL) sliced to this office match its per-office "
                         "views. No post. Run before flipping CHURN_USE_ALL_OFFICE.")
    ap.add_argument("--prove-cancel", action="store_true",
                    help="cell-for-cell proof that the all-office ongoing-cancel "
                         "view sliced to this office matches its per-office view. "
                         "No post. Run before flipping CANCEL_USE_ALL_OFFICE.")
    args = ap.parse_args(argv)

    # Structural guard FIRST — a duplicated channel or view URL (the copy-paste
    # mistake that cross-posts one office's numbers) aborts before anything runs.
    problems = _off.validate()
    if args.check:
        if problems:
            print("✗ office table INVALID:")
            for p in problems:
                print(f"   - {p}")
            return 1
        print(f"✓ office table OK — {len(_off.OFFICES)} office(s): "
              + ", ".join(f"{o.channel_name} ({k})"
                          for k, o in _off.OFFICES.items()))
        return 0
    if problems:
        print("✗ REFUSING to run — office table is inconsistent:")
        for p in problems:
            print(f"   - {p}")
        return 2

    # --all: run every office, in registry order, continue-on-failure. Each
    # office is a FRESH main() call so it gets its own env/pull/manifest exactly
    # as the orchestrator runs it — no special-cased second code path to drift.
    if args.all_offices:
        if args.only:
            print("--all cannot be combined with --only (re-run one office's "
                  "metric from its own card button instead).")
            return 2
        mode_arg = ["--live"] if args.live else ["--dry-run"]
        passthru = (["--fresh"] if args.fresh else [])
        results: list[tuple[str, int]] = []

        # The main #alphalete-sales report first — it's Raf's local office, just
        # on its own older module (see MAIN_OFFICE_*). Run it exactly the way its
        # own card always did: live by default, --dry-run to opt out.
        print(f"\n{'=' * 62}\n=== raf — {MAIN_OFFICE_LABEL} → {MAIN_OFFICE_CHANNEL}"
              f"\n{'=' * 62}")
        try:
            main_args = [] if args.live else ["--dry-run"]
            rc = subprocess.run(
                [sys.executable, "-u", "-m", MAIN_OFFICE_MODULE] + main_args,
                cwd=str(REPO_ROOT), env=os.environ.copy()).returncode
        except Exception as e:  # noqa: BLE001 — must not kill the other offices
            print(f"✗ raf errored: {type(e).__name__}: {e}")
            rc = 1
        results.append(("raf", rc))
        if args.live:
            record_status(MAIN_OFFICE_LABEL, MAIN_OFFICE_CHANNEL, ok=(rc == 0),
                          error="" if rc == 0 else "see the run log")

        for key in _off.ORDER:
            o = _off.OFFICES[key]
            print(f"\n{'=' * 62}\n=== {key} — {o.label} → {o.channel_name}\n{'=' * 62}")
            try:
                rc = main(["--office", key] + mode_arg + passthru)
            except Exception as e:  # noqa: BLE001 — one office must not kill the rest
                print(f"✗ {key} errored: {type(e).__name__}: {e}")
                rc = 1
            results.append((key, rc))
        bad = [k for k, rc in results if rc != 0]
        print(f"\n=== ALL OFFICES: {len(results) - len(bad)}/{len(results)} clean ===")
        for k, rc in results:
            print(f"  {'✅' if rc == 0 else '❌'}  {k}")
        if bad:
            print(f"\n{len(bad)} office(s) had a miss: {', '.join(bad)}. Re-run "
                  f"just those from the card's per-office buttons.")
        print("=== done ===")
        return 1 if bad else 0

    if not args.office:
        print(f"--office is required (one of: {', '.join(_off.ORDER)}), or --all")
        return 2

    if args.prove_abp:
        return _prove_abp(args.office)
    if args.inspect_cancel:
        return _inspect_cancel(args.office, view_override=args.cancel_view)
    if args.inspect_churn:
        return _inspect_churn(args.inspect_churn)
    if args.prove_churn:
        return _prove_churn(args.office)
    if args.prove_cancel:
        return _prove_cancel(args.office)

    # Before a LIVE post, refresh thread_plans.json from the shared Thread Builder
    # sheet so today's thread matches the admin's latest edit. Best-effort — a
    # sheet hiccup leaves the committed plans in place and the report continues.
    if args.live:
        try:
            from automations.thread_builder import sync as _tb_sync
            _tb_sync.sync(verbose=False)
        except Exception:  # noqa: BLE001 — sync must never break the report
            pass

    o = _off.get(args.office)
    _full = metrics_for(o)          # every board this office CAN post (pre-override)
    # Per-office section control. A committed SECTION_OVERRIDES entry pins exactly
    # which boards this office posts and WINS over enrollment; an EMPTY entry means
    # the office posts NO metrics thread at all (the report doesn't fit it). Else an
    # office may enroll a SUBSET at onboarding (ONBOARDED_EXTRA enrolled_reports).
    # Absent from both — every hardcoded office, and any office enrolled in
    # everything — => all metrics, byte-identical to before this change. Keys are
    # owner ReportKind keys or runner slugs; both resolve through OWNER_KEY_TO_SLUG.
    enrolled = _off.ONBOARDED_EXTRA.get(o.key, {}).get("enrolled_reports") or []
    if o.key in _off.SECTION_OVERRIDES:
        want = {OWNER_KEY_TO_SLUG.get(k, k) for k in _off.SECTION_OVERRIDES[o.key]}
        default = [m for m in _full if m["slug"] in want]   # empty => posts nothing
    elif enrolled:
        enrolled_slugs = {OWNER_KEY_TO_SLUG.get(k, k) for k in enrolled}
        default = [m for m in _full if m["slug"] in enrolled_slugs] or _full
    else:
        default = _full
    # Thread Builder: reorder / subset per this office's saved plan (thread_plans.json,
    # per-machine). No plan -> `default` order unchanged (exact no-op).
    from automations.shared import thread_plans as _tp
    metrics = _tp.resolve_sections("d2d", args.office, _full, default,
                                   id_key="slug")
    target_chan = args.channel or o.channel_id

    # dry-run WINS if both are passed: `lucy rerun <id> --dry-run` appends
    # --dry-run onto the schedule's base --live, and dry-run is the safe default.
    mode = "dry-run" if args.dry_run else ("live" if args.live else "plan")

    wired = metrics
    # An office pinned to an empty SECTION_OVERRIDES posts NOTHING — no header, no
    # boards. A wireless-only office whose every board is N/A or blank should not
    # post an all-empty thread; its reporting lives elsewhere (its trackers).
    if not wired and not args.only:
        print(f"{o.label}: no metrics configured for this office — posting nothing.")
        return 0
    if args.only:
        # COMMA LIST. Selects from the FULL board list (`_full`), NOT the
        # override-filtered set — so a board can be dry-run for TESTING while the
        # office's committed override stays () (its live 4am run posts nothing).
        # This is what makes an empty-override office safe to build against: the
        # scheduled --live run (no --only) skips via the guard above; only an
        # explicit --only run touches a board. Retries also use --only (re-post
        # ONLY the missed metrics) — safe since they name boards already in-thread.
        wanted = [s.strip() for s in args.only.split(",") if s.strip()]
        wired = [m for m in _full if m["slug"] in wanted]
        unknown = [s for s in wanted if s not in {m["slug"] for m in _full}]
        if unknown or not wired:
            print(f"--only {args.only!r}: unknown slug(s) {unknown or wanted} "
                  f"(all: {[m['slug'] for m in _full]})")
            return 2

    to_named = (target_chan == o.channel_id)
    _dest = o.channel_name if to_named else f"DM/{target_chan}"
    print(f"=== {o.label} daily metrics — owner={o.owner!r} → {_dest} "
          f"({target_chan}) — {mode.upper()} ===")
    for m in wired:
        print(f"   • {m['label']}  ({m['module']})")

    if mode == "plan":
        print(f"\n(plan only — nothing executed; {len(wired)} metric(s) ready)")
        print("\nRun --dry-run to pull (no post) on the mini, or --live to post "
              "as Lucy.")
        return 0

    # Share the org-wide crosstab pulls across offices: the FIRST office to pull a
    # given view (Order Log, Cancels, Disconnects, Scheduled-6+) downloads it; the
    # next office the same morning reads the dated cache and skips the browser. So
    # the org-wide pulls cost the same whether there are 2 offices or 20. Only the
    # 3 per-office ICD views (churn/ongoing_cancel/abp) still pull per office (each
    # is a distinct URL → its own cache key, no false sharing). --fresh forces a
    # live re-pull. See tableau_patchright._xtab_cache_*.
    # Cross-workspace posting: an office whose Slack channel lives in a DIFFERENT
    # workspace than AO (e.g. trang -> FRESH SUCCESS) posts with its OWN bot token,
    # kept in a file under ~/.config/recruiting-report/. Setting SLACK_USER_TOKEN
    # routes BOTH the in-process ensure_metrics_thread/auth-test below AND every
    # metric subprocess (they inherit base_env) through that token. Normal offices
    # unset it so they fall back to the machine's default AO 'Lucy' token file.
    if o.slack_token_file:
        _tok_path = (Path.home() / ".config" / "recruiting-report"
                     / o.slack_token_file)
        if _tok_path.exists():
            os.environ["SLACK_USER_TOKEN"] = _tok_path.read_text(
                encoding="utf-8-sig").strip()
        elif mode == "live":
            print(f"\n✗ --live can't post — {o.label} posts to {o.channel_name} "
                  f"in another Slack workspace and needs its bot token at "
                  f"{_tok_path}, which isn't on this machine. Install it and retry.")
            return 2
    else:
        os.environ.pop("SLACK_USER_TOKEN", None)

    base_env = dict(os.environ)
    if not args.fresh:
        base_env["METRICS_XTAB_CACHE"] = str(
            REPO_ROOT / "output" / "metrics_xtab_cache")

    if mode == "live":
        from automations.shared import slack_metrics_post as smp
        try:
            tok = smp._load_token()
        except smp.SlackPostError as e:
            print(f"\n✗ --live can't post — no Slack token resolves: {e}")
            return 2
        try:
            import certifi, ssl
            from slack_sdk import WebClient
            client = WebClient(
                token=tok, ssl=ssl.create_default_context(cafile=certifi.where()))
            who = client.auth_test()
            print(f"  posting as: {who.get('user')} (team={who.get('team')})")
        except Exception as e:                  # noqa: BLE001
            print(f"✗ Slack token failed auth: {type(e).__name__}: {str(e)[:140]}")
            return 2

        # --channel as a comma-list of user ids → open a review group-DM.
        if "," in target_chan:
            users = [u.strip() for u in target_chan.split(",") if u.strip()]
            try:
                conv = client.conversations_open(users=",".join(users))
                target_chan = conv["channel"]["id"]
                print(f"  group DM opened for {len(users)} user(s) → {target_chan}")
            except Exception as e:              # noqa: BLE001
                print(f"✗ couldn't open group DM for {users}: "
                      f"{type(e).__name__}: {str(e)[:140]}")
                return 2

    # ---- Destinations: normally ONE (the office's channel, all wired metrics).
    # An office with channel_plans FANS OUT — each plan is its own channel with
    # only that plan's metric slugs (e.g. cancels-only to a leaders channel).
    # Skipped when --channel forces a manual override (a review DM wants the whole
    # thread in one place). Empty channel_plans = exact prior single-channel path.
    destinations, skipped = build_destinations(
        o, wired, target_chan, to_named, manual_channel=bool(args.channel))
    for cname, slugs in skipped:
        print(f"  (channel {cname}: no wired metrics match {slugs} — skipped)")
    if not destinations:
        print("\nno channel-plan destinations match the wired metrics; nothing "
              "posted.")
        return 0

    if len(destinations) > 1:
        print(f"\n  fan-out → {len(destinations)} channels:")
        for d in destinations:
            print(f"    • {d['channel_name']} ({d['channel_id']}): "
                  f"{', '.join(m['slug'] for m in d['metrics'])}")

    if mode == "dry-run":
        print("\n⚠ --dry-run PULLS real Tableau data (no Slack post). Requires "
              "the ownerville/Tableau session (run on the mini).")

    # Post each destination: its own header thread (live) + only its metrics. Each
    # metric subprocess reads METRICS_CHANNEL_ID/METRICS_HEADER_LABEL from its env,
    # so it finds THAT channel's daily thread. results carry the channel for the
    # summary; a slug that fails in ANY channel counts as failed (for the retry).
    results: list[tuple[str, str, str, bool, str]] = []  # (chan, slug, label, ok, note)
    overall_start = time.monotonic()
    for dest in destinations:
        chan = dest["channel_id"]
        hdr = dest["header_label"] or ""
        child_env = dict(base_env, METRICS_CHANNEL_ID=chan)
        if hdr:
            child_env["METRICS_HEADER_LABEL"] = hdr
        else:
            child_env.pop("METRICS_HEADER_LABEL", None)

        if mode == "live":
            # slack_metrics_post read CHANNEL_ID + HEADER_LABEL at import — rebind
            # both so the header thread + replies land in THIS destination's channel
            # (and under its labelled thread when a channel is shared).
            smp.CHANNEL_ID = chan
            smp.HEADER_LABEL = hdr
            if not args.only:
                os.environ["METRICS_CHANNEL_ID"] = chan
                if hdr:
                    os.environ["METRICS_HEADER_LABEL"] = hdr
                else:
                    os.environ.pop("METRICS_HEADER_LABEL", None)
                try:
                    # NDS offices post a DIFFERENT board set, so the header must
                    # list THEIR boards, not the internet template's 12. Non-NDS
                    # => sections=None => default 12 (byte-identical).
                    _sections = ([m["label"] for m in dest["metrics"]]
                                 if o.nds else None)
                    res = smp.ensure_metrics_thread(sections=_sections)
                    print(f"  [{dest['channel_name']}] header thread: "
                          f"{'existed' if res.get('existed') else 'posted'} "
                          f"({res.get('thread_ts')})")
                except Exception as e:          # noqa: BLE001
                    print(f"  ⚠ [{dest['channel_name']}] could not ensure header "
                          f"thread: {e}")

        if len(destinations) > 1:
            print(f"\n--- {dest['channel_name']} ({chan}) — "
                  f"{len(dest['metrics'])} metric(s) ---")
        for m in dest["metrics"]:
            cmd = _metric_cmd(m, live=(mode == "live"))
            m_env = dict(child_env, **m.get("env", {}))
            ok, note = _run_one(m["label"], cmd, m_env)
            # In-run self-heal: a metric flagged retryable (knocks_gaps — its
            # ownerville scrape intermittently times out and drops BOTH its
            # metrics) gets one or more FRESH-subprocess re-attempts (new
            # ownerville session) before the thread is finalized, so a first-pass
            # flake doesn't sit until a human notices and triggers a rerun. Retry
            # is safe because knocks_run only exits non-zero when the pull raises
            # (pre-post) — see metrics_for.
            retries = m.get("retry_on_fail", 0)
            attempt = 0
            while not ok and attempt < retries:
                attempt += 1
                print(f"\n↻ in-run retry {attempt}/{retries} for {m['label']} "
                      f"(previous attempt: {note})", flush=True)
                ok, note = _run_one(m["label"], cmd, m_env)
                if ok:
                    note = f"{note} (recovered on retry {attempt})"
            results.append((dest["channel_name"], m["slug"], m["label"], ok, note))

    total = time.monotonic() - overall_start
    n_ok = sum(1 for *_x, ok, _ in results if ok)
    print(f"\n{'='*70}\n=== {o.label} metrics summary "
          f"({n_ok}/{len(results)} ok, {total/60:.0f}m, {mode}) ===")
    for chan_name, _slug, label, ok, note in results:
        _pfx = f"[{chan_name}] " if len(destinations) > 1 else ""
        print(f"  {'✅' if ok else '❌'}  {_pfx}{label}  ({note})")
    # A slug is FAILED if it missed in any channel; retry re-posts it to its
    # channel(s). Dedup so a metric posted to 2 channels lists once.
    failed_slugs = list(dict.fromkeys(
        slug for _c, slug, _l, ok, _ in results if not ok))
    failed_labels = list(dict.fromkeys(
        label for _c, _s, label, ok, _ in results if not ok))
    ok_labels = list(dict.fromkeys(
        label for _c, _s, label, ok, _ in results
        if ok and label not in set(l for _c2, _s2, l, o2, _n2 in results if not o2)))

    # Manifest for the orchestrator's completeness verify — full LIVE run only.
    # `succeeded` lets the Hub pill show ORANGE (partial) instead of green when
    # some metrics land and some miss.
    if mode == "live" and not args.only:
        from automations.shared import run_manifest as _rm
        # Retry ONLY the metrics that missed — any number of them. A bare
        # ["--live"] here would re-run the whole office and re-post every metric
        # that already landed (no dedup on posting), which is exactly what the
        # orchestrator's auto-retry would then execute unattended.
        #
        # SELF-CONTAINED: must carry --office. The orchestrator's auto-retry
        # passes retry_args INSTEAD OF base_args (which is where --office
        # normally lives), so omitting it here made the retry run with no office
        # and die on "--office is required" (Megan 2026-07-16).
        retry = ["--office", o.key, "--live"]
        if failed_slugs:
            retry += ["--only", ",".join(failed_slugs)]
        _dest_desc = (f"{len(destinations)} channels" if len(destinations) > 1
                      else o.channel_name)
        _rm.write_manifest(
            o.report_id, failed=failed_labels, succeeded=ok_labels,
            retry_args=retry, kind="metric",
            note=(f"{n_ok}/{len(results)} metrics posted to {_dest_desc}"
                  + (f"; failed: {', '.join(failed_slugs)}" if failed_slugs else "")))
        # Feed the ONE Hub card's per-office ✅/❌ checklist. Only a FULL live run
        # speaks for the whole office (an --only re-run covers a single metric,
        # so it must not overwrite the office's row with a partial verdict).
        _record_office_status(
            o, ok=not failed_slugs,
            error=("; ".join(failed_labels) if failed_labels else ""))

    if failed_slugs:
        print(f"\n{len(failed_slugs)} metric(s) didn't post — run COMPLETE with a "
              f"note. Re-run just those: --only <slug>. Missing: {failed_labels}")
    else:
        print("\nAll wired metrics ok ✓")
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
