"""Combined New Internet ABP% run — Raf + Rashad in ONE Tableau session.

Both offices read the SAME workbook (ATT TRACKER 2.1 - D2D → Metrics),
so opening one ownerville→Tableau session and pulling both views saves a
second full SSO each morning (mirrors churn.run's shared-session pattern).

NO DATA IS EVER POOLED. Each office is keyed end-to-end by its own
(view → owner filter → sheet → channel); the only shared thing is the
browser page. An office that fails is logged and skipped — the other
still runs.

  python -m automations.new_internet_abp.run_all              # both, live + post
  python -m automations.new_internet_abp.run_all --dry-run    # pull, no write/post
  python -m automations.new_internet_abp.run_all --skip-slack # fill sheets, no post
  python -m automations.new_internet_abp.run_all --only raf   # one office
  python -m automations.new_internet_abp.run_all --skip-download

Run on the MINI (the ownerville→Tableau session lives there).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

from automations.new_internet_abp import pull, fill, render

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DEFAULT_CHANNEL = "C068PH3RFSM"   # #alphalete-sales (Raf)
ELEVATE_CHANNEL = "C0B3KTCCMT7"   # #elevate-sales (Rashad, private)
INDELIBLE_CHANNEL = "C0AA85Y3FPE" # #indelible-sales (Aya, private)

# Each office is fully self-contained — no globals, no crosstalk.
OFFICES = [
    {
        "key": "raf",
        "label": "Raf — New Internet ABP%",
        "view_url": ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                     "ATTTRACKER2_1-D2D/Metrics/"
                     "07afddc4-36b3-4ecc-98a8-28b9ef1648c1/RafLocalofficeINTABP?:iid=1"),
        "owner": "RAFAEL HIDALGO",
        "sheet_id": "1Xddk29xvB3LYp24KndVbijgTngUVSAuQ-r5tjh7uqO8",
        "channel": DEFAULT_CHANNEL,
        "subtitle": "Raf's Local Office",
    },
    {
        "key": "rashad",
        "label": "Rashad — New Internet ABP%",
        "view_url": ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                     "ATTTRACKER2_1-D2D/Metrics/"
                     "d932e0f6-72b4-4003-a5d1-4262137363de/RashadNLABP?:iid=1"),
        "owner": "RASHAD REED",
        "sheet_id": "11louWIU8IuSPrZLsMkRh8qEnO3wNqmeNwIOSKPpXzm8",   # Metrics Reports -Rashad Reed
        "channel": ELEVATE_CHANNEL,
        "subtitle": "Rashad's Local Office",
    },
    {
        "key": "aya",
        "label": "Aya — New Internet ABP%",
        "view_url": ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                     "ATTTRACKER2_1-D2D/Metrics/"
                     "c51fa7b7-f75d-4ca0-bb6a-f63c9a83eb32/AyaINTABP?:iid=1"),
        "owner": "AYA AL-KHAFAJI",
        "sheet_id": "10t16jDAFDtQNytFWU6O6gJtoOFlg0UHLwoArTW_sRNg",   # Metrics Reports -Aya
        "channel": INDELIBLE_CHANNEL,   # #indelible-sales
        "subtitle": "Aya's Local Office",
    },
]


def _csv_path(key: str) -> Path:
    # Distinct cache per office so --skip-download never crosses them.
    return Path(tempfile.gettempdir()) / f"new_internet_abp_{key}.csv"


def _fill_and_post(off: dict, today: dt.date, args) -> tuple[bool, str]:
    """Parse this office's CSV, fill its OWN sheet, post to its OWN channel.
    Returns (ok, note)."""
    csv_path = _csv_path(off["key"])
    parsed = pull.parse(csv_path, owner=off["owner"])   # owner keyed per office
    office = parsed["office_total"]
    reps = parsed["reps"]
    n_data = sum(1 for s in reps.values() if pull.has_pct(s))
    print(f"  [{off['key']}] office {office.get('pct','-')} "
          f"({pull.fmt_units(office) or '-'}); {n_data} data reps")
    if not office and n_data == 0:
        return False, "no ABP data parsed (skipped so the tab isn't blanked)"

    # Fill this office's OWN sheet (sheet_id keyed per office; TAB is shared).
    ws = fill.open_ws(sheet_id=off["sheet_id"])
    fill.fill_office(ws, today, parsed, force_insert=args.force_insert,
                     dry_run=args.dry_run, logfn=lambda m: print(f"    {m}"))

    if args.dry_run or args.skip_slack:
        return True, "sheet only" if args.skip_slack else "dry-run"

    # Post to this office's OWN channel. slack_metrics_post reads CHANNEL_ID
    # at import, so set it (and the module's live global) per office right
    # before posting — the same technique rashad_metrics.run uses.
    import automations.shared.slack_metrics_post as smp
    smp.CHANNEL_ID = off["channel"]
    out_dir = Path(tempfile.gettempdir()) / "abp_slack_post"
    png = render.render(ws, today, out_dir / f"{off['key']} ABP {today:%m-%d-%Y}.png",
                        subtitle=off.get("subtitle", render.SUBTITLE))
    try:
        result = smp.post_reply_with_file(
            png, comment="💳 New Internet ABP %",
            react_emoji="credit_card",
            file_name=f"New Internet ABP {today:%m-%d-%Y}.png")
        if not result.get("ok", True):
            return False, "Slack post returned ok=false"
        return True, f"posted → {off['channel']}"
    except smp.SlackPostError as e:
        return False, f"Slack post failed: {e}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="new_internet_abp.run_all")
    ap.add_argument("--date", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--force-insert", action="store_true")
    ap.add_argument("--skip-slack", action="store_true")
    ap.add_argument("--only", choices=[o["key"] for o in OFFICES], default=None)
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    offices = [o for o in OFFICES if args.only is None or o["key"] == args.only]
    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"=== New Internet ABP% — {mode} — {today.isoformat()} — "
          f"{[o['key'] for o in offices]} ===")

    # --- Phase 1: pull each office's view (ONE shared Tableau session) ---
    if args.skip_download:
        for o in offices:
            if not _csv_path(o["key"]).exists():
                print(f"  ⚠ --skip-download but no cached CSV for {o['key']} "
                      f"({_csv_path(o['key'])})")
                return 1
            print(f"  [{o['key']}] cached {_csv_path(o['key'])}")
    else:
        from automations.shared.tableau_patchright import tableau_session
        print("Phase 1: one Tableau session, one crosstab per office...")
        with tableau_session(verbose=False) as page:
            for o in offices:
                print(f"  → pulling {o['label']}...")
                pull.fetch_crosstab(out_path=_csv_path(o["key"]),
                                    view_url=o["view_url"], page=page)
                print(f"    ✓ {_csv_path(o['key'])}")

    # --- Phase 2/3: fill + post each office independently ---
    print("Phase 2: fill each office's own sheet + post to its own channel")
    results = []
    for o in offices:
        print(f"\n▶ {o['label']}")
        try:
            ok, note = _fill_and_post(o, today, args)
        except Exception as e:  # one office's failure must not sink the other
            ok, note = False, f"error: {e}"
        results.append((o["key"], ok, note))
        print(f"  {'✅' if ok else '❌'} {o['key']}: {note}")

    n_ok = sum(1 for _, ok, _ in results if ok)
    print(f"\n=== ABP summary: {n_ok}/{len(results)} ok ===")
    for key, ok, note in results:
        print(f"  {'✅' if ok else '❌'} {key}: {note}")
    if n_ok < len(results):
        return 1
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
