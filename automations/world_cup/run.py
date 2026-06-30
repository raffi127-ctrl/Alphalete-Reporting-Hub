"""AT&T World Cup 2026 — Bracket Flyers runner.

Each run:
  1. Opens the WorldCup2026 Tableau view, reads the Crosstab dialog's sheet
     list, and auto-detects the active round (smallest "Round of N" sheet with
     real rep data). A manual --round override is the fallback if it misdetects.
  2. Downloads that round's crosstab CSV (shared patchright Tableau driver).
  3. Builds two flyer HTMLs: Alphalete (Rafael's reps highlighted gold, filtered
     to his groups) + Public (all groups, no highlights).
  4. Renders both to PDF via patchright headless Chromium (page.pdf()).
  5. Posts both PDFs to #alphalete-sales + #alphalete-lvl1-chat under a single
     "🏆 World Cup 2026 — Round N" message per channel.

ROUND STRUCTURE: group_size / top_n / window per round live in
build_bracket.ROUND_CONFIGS. Smart Circle has changed group size mid-contest
(R1/R2 = groups of 6, R3 = groups of 4). If a run errors with "No config for
Round of N", open the round-start email from Chris Williford and add that
round's entry to ROUND_CONFIGS, then re-run.

Testing flags (no Slack post):
  --detect-only   List the dialog's sheets + which round it would pick. No build.
  --pull-only     Detect + download the CSV; print columns + Alphalete-match
                  check on the real owners. No build, no post.
  --no-slack      Full run (detect -> pull -> build -> 2 PDFs in output/) but
                  do NOT post; print what WOULD be posted.
  --round N       Force the round (skip detection). Combine with the above.
  --test-channel <id>
                  Post the FULL message (header + both PDFs) to a SINGLE
                  destination instead of the two real channels — for a safe
                  test. <id> can be a channel ID or a user ID (U…, resolved to
                  that user's DM). Uses the PDFs already in output/ (does NOT
                  re-pull Tableau). Real post, just to one place.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

# Windows consoles default to cp1252; printing the ✅/🏆/→ status lines would
# raise UnicodeEncodeError. Force UTF-8 (same guard as fiber_activations/run.py).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from automations.world_cup import build_bracket, pull, render, slack_post
from automations.shared.tableau_patchright import tableau_session

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"


def _pdf_paths(round_label: str) -> tuple[Path, Path]:
    """Match the handoff naming: 'World Cup 2026 - <label> Bracket(.pdf)' where
    <label> is 'Round N' for numbered rounds or 'Finals'."""
    alpha = OUTPUT_DIR / f"World Cup 2026 - {round_label} Bracket.pdf"
    public = OUTPUT_DIR / f"World Cup 2026 - {round_label} Bracket (Public).pdf"
    return alpha, public


def _find_existing_pdfs() -> tuple[str, Path, Path]:
    """Locate the most recent already-rendered (alpha, public) PDF pair in
    output/. Used by --test-channel so a test post reuses the PDFs from the
    last --no-slack run instead of re-pulling Tableau. Picks the newest complete
    pair by file mtime (round labels like 'Finals' don't sort numerically)."""
    pairs: dict[str, dict[str, Path]] = {}
    for pth in OUTPUT_DIR.glob("World Cup 2026 - * Bracket*.pdf"):
        m = re.match(r"World Cup 2026 - (.+?) Bracket( \(Public\))?\.pdf$", pth.name)
        if not m:
            continue
        slot = pairs.setdefault(m.group(1), {})
        slot["public" if m.group(2) else "alpha"] = pth
    complete = {lbl: s for lbl, s in pairs.items() if "alpha" in s and "public" in s}
    if not complete:
        raise SystemExit(
            "No existing World Cup PDF pair found in output/. Run "
            "`--no-slack` first to generate them, then retry --test-channel.")
    label = max(complete, key=lambda l: complete[l]["alpha"].stat().st_mtime)
    return label, complete[label]["alpha"], complete[label]["public"]


def _write_html(round_label: str, public: bool, html_str: str) -> Path:
    suffix = " (Public)" if public else ""
    out = OUTPUT_DIR / f"World Cup 2026 - {round_label} Bracket{suffix}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_str, encoding="utf-8")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="world_cup")
    p.add_argument("--detect-only", action="store_true",
                   help="List the Crosstab sheets + the round it would pick; stop.")
    p.add_argument("--pull-only", action="store_true",
                   help="Detect + download the CSV; print columns + Alphalete "
                        "match; don't build or post.")
    p.add_argument("--no-slack", "--dry-run", dest="no_slack",
                   action="store_true",
                   help="Full run + render 2 PDFs to output/, but don't post.")
    p.add_argument("--round", type=int, default=None,
                   help="Force the round size (e.g. 144). Skips auto-detection.")
    p.add_argument("--finals", action="store_true",
                   help="Pull the named 'Finals' sheet instead of a 'Round of N'. "
                        "The numeric auto-detection can't find the Finals (it's "
                        "not 'Round of N', and the still-populated Round-of-36 "
                        "sheet would win), so the Finals needs this flag.")
    p.add_argument("--test-channel", default=None,
                   help="Post the full message + both existing output/ PDFs to "
                        "this single destination (channel ID, or user ID U… -> "
                        "their DM) instead of the two real channels. No re-pull.")
    args = p.parse_args(argv)

    # ---- test-channel: post existing PDFs to ONE destination. No Tableau. ----
    if args.test_channel:
        round_label, alpha_pdf, public_pdf = _find_existing_pdfs()
        print(f"\n=== World Cup — TEST POST (single destination) ===")
        print(f"  Using existing PDFs for {round_label}:")
        print(f"    {alpha_pdf.name}")
        print(f"    {public_pdf.name}")
        print(f"  Destination: {args.test_channel}")
        result = slack_post.post_round(alpha_pdf, public_pdf, round_label,
                                       test_channel=args.test_channel)
        print(f"\n  message: {result['comment']}")
        for name, r in result["results"].items():
            status = "ok" if r["ok"] else "FAILED"
            print(f"  -> {r['target']} (posted to channel {r['channel']}): {status}")
        print("\n✅ Test post done (real channels untouched).")
        print("=== done ===")
        return 0

    # ---- detect-only: just list sheets + the naive pick. No downloads. ----
    if args.detect_only:
        print("\n=== World Cup — DETECT ONLY ===")
        with tableau_session(verbose=True) as page:
            sheets = pull.list_crosstab_sheets(page, verbose=True, full_scan=True)
        cands = pull.round_candidates(sheets)
        print(f"\nAll Crosstab sheets ({len(sheets)}):")
        for s in sheets:
            print(f"  - {s}")
        print(f"\n'Round of N' candidates (ascending): "
              f"{[f'Round of {n}' for n, _ in cands]}")
        if cands:
            print(f"-> Would start at the smallest: Round of {cands[0][0]} "
                  "(then fall forward if it has no data).")
        else:
            print("-> No 'Round of N' sheet found.")
        grid = pull.data_grid_sheet(sheets)
        print(f"-> Data-grid sheet: {grid!r}. --finals pins Contest View=Finals "
              f"and pulls this sheet."
              if grid else "-> No data-grid sheet found (--finals would error).")
        return 0

    # ---- detect + pull (shared by --pull-only, --no-slack, and full run) ----
    # SESSION-LEVEL retry: a fresh tableau_session per attempt. The per-dialog
    # retry inside list_crosstab_sheets/download_crosstab_patchright can't help
    # when the PAGE itself dies mid-pull (TargetClosedError) — e.g. a concurrent
    # ownerville pull bumps the one-session-per-account login. Reopening a fresh
    # session on failure rides out a closed page + transient session contention;
    # the backoff gives a competing run time to finish. A genuinely broken view
    # still fails all attempts and propagates.
    SESS_ATTEMPTS, SESS_BACKOFF_S = 3, 15
    _sess_err = None
    for _sess_try in range(1, SESS_ATTEMPTS + 1):
        try:
            with tableau_session(verbose=True) as page:
                if args.finals:
                    round_size, csv_path, sheets = pull.pull_finals(
                        page, OUTPUT_DIR, verbose=True)
                else:
                    round_size, csv_path, sheets = pull.detect_and_pull(
                        page, OUTPUT_DIR, override_round=args.round, verbose=True)
            _sess_err = None
            break
        except Exception as e:  # noqa: BLE001 — reopen a clean session + retry
            _sess_err = e
            if _sess_try < SESS_ATTEMPTS:
                print(f"  ⚠ Tableau session failed "
                      f"({str(e).splitlines()[0][:90]}) — fresh-session retry "
                      f"{_sess_try}/{SESS_ATTEMPTS - 1} after {SESS_BACKOFF_S}s…",
                      flush=True)
                time.sleep(SESS_BACKOFF_S)
    if _sess_err is not None:
        raise _sess_err

    # round_size is the int N for a numbered round or the sheet name str (Finals).
    round_desc = round_size if args.finals else f"Round of {round_size}"
    print(f"\nActive round: {round_desc}")
    print(f"CSV: {csv_path}")

    # ---- pull-only: inspect columns + Alphalete match, then stop. ----
    if args.pull_only:
        rsize, header, groups = build_bracket.read_groups(csv_path)
        owners = sorted({m["owner"] for ms in groups.values() for m in ms})
        alpha_owners = [o for o in owners if build_bracket.is_alphalete(o)]
        total_reps = sum(len(ms) for ms in groups.values())
        print("\n=== PULL-ONLY inspection ===")
        print(f"Header columns ({len(header)}): {header}")
        print(f"Groups: {len(groups)}   Reps: {total_reps}")
        print(f"\nDistinct owners ({len(owners)}):")
        for o in owners:
            mark = "  <-- ALPHALETE (gold)" if build_bracket.is_alphalete(o) else ""
            print(f"  {o!r}{mark}")
        print(f"\nAlphalete-matched owners: {len(alpha_owners)}")
        if not alpha_owners:
            print("  ⚠ NONE matched. The gold highlight keys on 'ALPHALETE' or "
                  "'RAFAEL HIDALGO' in the owner string — if Raf's reps show "
                  "under a different owner label here, the match needs updating "
                  "(build_bracket.is_alphalete).")
        return 0

    # ---- build both HTML versions ----
    alpha_html, alpha_stats = build_bracket.build_html(csv_path, public=False)
    public_html, public_stats = build_bracket.build_html(csv_path, public=True)
    round_label = alpha_stats["round_label"]

    alpha_html_path = _write_html(round_label, False, alpha_html)
    public_html_path = _write_html(round_label, True, public_html)

    # ---- render both PDFs ----
    alpha_pdf, public_pdf = _pdf_paths(round_label)
    print(f"\nRendering PDFs ({round_label} / {round_desc})…")
    render.render_pdfs([
        (alpha_html, alpha_pdf),
        (public_html, public_pdf),
    ], verbose=True)

    print("\n--- Standings (Alphalete) ---")
    print(f"  In play: {alpha_stats['alph_in_play']}  "
          f"In top {alpha_stats['top_n']}: "
          f"{alpha_stats['alph_top']}  Leading group: {alpha_stats['alph_leading']}")
    print(f"  Alphalete view: {alpha_stats['shown_groups']} of "
          f"{alpha_stats['total_groups']} groups   "
          f"Cut-line ties: {alpha_stats['cut_tie_groups']}   "
          f"Total Gig+ field: {alpha_stats['total_score']}")
    print(f"\n  Alpha PDF : {alpha_pdf}")
    print(f"  Public PDF: {public_pdf}")
    print(f"  (HTML: {alpha_html_path.name}, {public_html_path.name})")

    # ---- post (or show plan) ----
    if args.no_slack:
        plan = slack_post.post_round(alpha_pdf, public_pdf, round_label,
                                     dry_run=True)
        print("\n--- WOULD POST to Slack (--no-slack): ---")
        print(f"  message : {plan['comment']}")
        print(f"  channels: {plan['channels']}")
        print(f"  files   : {plan['files']}  (both PDFs to BOTH channels)")
        print("=== done (dry-run) ===")
        return 0

    print("\nPosting to Slack…")
    result = slack_post.post_round(alpha_pdf, public_pdf, round_label)
    for name, r in result["results"].items():
        status = "ok" if r["ok"] else "FAILED"
        print(f"  #{name} ({r['channel']}): {status}")
    print("\n✅ Done.")
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
