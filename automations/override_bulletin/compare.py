"""READ-ONLY: Eve's hand-kept override tab vs the one the bot fills. Writes NOTHING.

WHY THIS EXISTS
---------------
The bulletin renders OUR fill (the sandbox copy), while Eve keeps the live tab by
hand. They are supposed to agree; when they don't, the bulletin quietly publishes
the wrong money. Before this module the check was re-improvised by hand every
Friday, and getting it wrong is easy — see the three traps below, each of which
cost a bad measurement on 2026-08-07.

    lucy rerun override_compare              # last 5 weeks (the backtrack window)
    lucy rerun override_compare --weeks 31   # all of 2026
    lucy rerun override_compare --slack      # also post the verdict to Slack

    Sources, in full:
      workbook  1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E
                ("ORG / Captainship" — Org Overrides + DD reports)
      Eve       tab 'Org Overrides Ongoing Report'         (filled BY HAND)
      the bot   tab 'Copy of Org Overrides Ongoing Report' (override_bulletin.run)
      cells     row 1 = week headers (m.d.yy), col A = the person's label

THE THREE TRAPS — this module exists mostly to keep them fixed:

  1. READ RAW CELLS. `build.read_data` DISCARDS every row containing "credico"
     and recomputes the totals, so a comparison built on it eats exactly the
     difference: on 2026-08-07 a real $5,368.82 gap measured as ~$1,088 because
     the credico row it lived in was filtered out before the subtraction.
  2. CROSS BY NAME, NEVER BY ROW INDEX. The two tabs hold the same people in a
     DIFFERENT ORDER. Comparing row N to row N mixes people up and produces
     nonsense like "Rafael −$2.2M".
  3. THE NAME ALONE IS NOT A KEY, TWICE OVER. "Captain Override" / "Special
     Override" appear once under every leader in section 2, so each is keyed as
     "<leader> | <label>". And the seven leaders appear in BOTH sections — once
     in ALL ORG and again as a section-2 total — so the key carries its section
     too. Without that the section-2 entry overwrites the section-1 one and the
     ORG row of the seven biggest earners is never compared at all (61 rows
     collapse to 55, silently).

Name spellings go through the shared ICD Aliases table (CLAUDE.md: spelling
mismatches belong there, never in a per-report patch), so one person written two
ways still compares as one person instead of showing up as a row missing from
each tab.

Runs anywhere — it only reads Sheets, no Tableau and no browser.
"""
from __future__ import annotations

import argparse
import re
import sys

from automations.override_bulletin import fill as F

# Rounding noise. The two tabs round independently, so cents drift constantly —
# and a Total row, being a sum of ~14 independently rounded cells, drifts by a
# few cents on its own. More to the point, THE BULLETIN PUBLISHES WHOLE DOLLARS
# (build._fmt is "${n:,.0f}"), so a sub-dollar difference cannot change a single
# character of what goes out. Reporting it only buries the differences that can.
# Nothing is dropped silently — the count of skipped cells is always printed, and
# --tolerance 0 shows every last cent.
DEFAULT_TOLERANCE = 1.00

_WEEK_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$")
_SUB_LABELS = ("captain override", "special override", "special overrides")
_SHEET_URL = "https://docs.google.com/spreadsheets/d/{}/edit"


def _default_weeks() -> int:
    """The backtrack window, so 'what we re-read' and 'what we check' are the
    same span by construction. Imported late — backtrack imports run, which
    would make this a cycle at module level."""
    from automations.override_bulletin import backtrack as BT
    return BT.DEFAULT_WEEKS


def _money(raw):
    """'$78,595.49' -> 78595.49 ; '(423.20)' -> -423.20 ; blank/text -> None."""
    if raw is None:
        return None
    s = str(raw).replace("$", "").replace(",", "").strip()
    if s in ("", "-", "—", "–"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1].strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _week_cols(header):
    """(index, label) for the CONTIGUOUS run of dated columns — the 2026 block.

    Not a blanket regex over the row: the tab is ~192 columns wide and carries a
    large historical weekly block far to the right, which a global scan would
    pull in. Stop at the first non-week header, exactly as build._week_cols does."""
    cols, started = [], False
    for i, h in enumerate(header):
        if _WEEK_RE.match((h or "").strip()):
            cols.append((i, (h or "").strip()))
            started = True
        elif started:
            break
    return cols


def read_tab(ws, aliases):
    """(week_labels, {(section, key): row_dict}) straight off the cells — nothing
    filtered.

    key is the canonical name for a person, or '<leader> | captain override' for
    a section-2 sub-row, and it is paired with its section because the leaders
    appear in both (trap 3). row_dict carries the label as typed and the 1-based
    row number so a difference can be pointed at in the Sheet."""
    vals = ws.get_all_values()
    if not vals:
        return [], {}
    wcols = _week_cols(vals[0])
    out, section, leader = {}, "org", None
    for ri, r in enumerate(vals[1:], start=2):
        label = (r[0] if r else "").strip()
        low = label.lower()
        if not label:
            continue
        if "captain/special" in low:          # section-2 header
            section, leader = "cap", None
            continue
        if low in _SUB_LABELS:
            if leader is None:                # a sub-row with no leader above it
                continue
            key = f"{leader} | {low}"
        else:
            key = F.canon(label, aliases)
            if section == "cap":
                leader = key
        out[(section, key)] = {
            "section": section,
            "label": label,
            "row": ri,
            "cells": {lbl: (_money(r[i]) if i < len(r) else None)
                      for i, lbl in wcols},
        }
    return [lbl for _i, lbl in wcols], out


def compare(*, weeks=None, tolerance=DEFAULT_TOLERANCE, verbose=True):
    """Diff the two tabs over the newest `weeks` week columns.

    Returns {"weeks": [...], "diffs": [...], "only_eve": [...], "only_bot": [...],
    "skipped": int} — `diffs` are the cells that differ by at least `tolerance`."""
    from automations.recruiting_report import fill as _fill

    weeks = weeks or _default_weeks()
    aliases = F.load_alias_map()
    wb = _fill._client().open_by_key(F.WORKBOOK_ID)
    eve_weeks, eve = read_tab(wb.worksheet(F.LIVE_TAB), aliases)
    bot_weeks, bot = read_tab(wb.worksheet(F.SANDBOX_TAB), aliases)

    if verbose:
        print(f"Workbook: {_SHEET_URL.format(F.WORKBOOK_ID)}")
        print(f"  Eve (a mano) : {F.LIVE_TAB!r} — {len(eve)} filas")
        print(f"  El bot       : {F.SANDBOX_TAB!r} — {len(bot)} filas")

    # The newest week is the leftmost header on EVE's tab; if the bot has not
    # rolled/filled it yet that is the single most important thing to say, so it
    # is said first and loudly rather than showing up as "everyone differs".
    if eve_weeks[:1] != bot_weeks[:1] and verbose:
        print(f"\n  !! La semana más nueva NO coincide — Eve: "
              f"{eve_weeks[0] if eve_weeks else '(ninguna)'} / bot: "
              f"{bot_weeks[0] if bot_weeks else '(ninguna)'}")

    want = [w for w in eve_weeks[:weeks] if w in bot_weeks]
    shared = set(eve) & set(bot)
    only_eve = sorted(_display(eve[k]) for k in set(eve) - shared)
    only_bot = sorted(_display(bot[k]) for k in set(bot) - shared)

    diffs, skipped = [], 0
    for w in want:
        for key in sorted(shared):
            a, b = eve[key]["cells"].get(w), bot[key]["cells"].get(w)
            if a is None and b is None:
                continue
            d = round((a or 0) - (b or 0), 2)
            if abs(d) < tolerance:
                skipped += 1 if d else 0
                continue
            diffs.append({"week": w, "key": key, "label": _display(eve[key]),
                          "eve": a, "bot": b, "delta": d,
                          "eve_row": eve[key]["row"], "bot_row": bot[key]["row"]})

    result = {"weeks": want, "diffs": diffs, "only_eve": only_eve,
              "only_bot": only_bot, "skipped": skipped,
              "tolerance": tolerance}
    if verbose:
        _print(result)
    return result


def _display(row) -> str:
    """The label as a person reads it. The seven leaders sit in both sections, so
    a bare name would be ambiguous about WHICH of their two rows moved."""
    return (f"{row['label']} [captains]" if row["section"] == "cap"
            else row["label"])


def _fmt(v):
    return "(vacío)" if v is None else f"{v:,.2f}"


def _print(res):
    if res["only_eve"] or res["only_bot"]:
        print("\nFILAS QUE ESTÁN EN UNA SOLA PESTAÑA")
        for n in res["only_eve"]:
            print(f"  solo en la de Eve : {n}")
        for n in res["only_bot"]:
            print(f"  solo en la del bot: {n}")

    print(f"\nSEMANAS COMPARADAS ({len(res['weeks'])}): "
          f"{', '.join(res['weeks']) or '(ninguna en común)'}")
    for w in res["weeks"]:
        rows = [d for d in res["diffs"] if d["week"] == w]
        if not rows:
            print(f"\n  {w}  — IGUALES")
            continue
        net = round(sum(d["delta"] for d in rows), 2)
        print(f"\n  {w}  — {len(rows)} celda(s) distinta(s), neto Eve − bot = {net:+,.2f}")
        for d in sorted(rows, key=lambda x: -abs(x["delta"])):
            print(f"      {d['label']:<32} Eve {_fmt(d['eve']):>14} (fila {d['eve_row']})"
                  f"   bot {_fmt(d['bot']):>14} (fila {d['bot_row']})"
                  f"   {d['delta']:+,.2f}")

    if res["skipped"]:
        print(f"\n  ({res['skipped']} celda(s) difieren por menos de "
              f"${res['tolerance']:.2f} — redondeo, no se listan)")
    print("\n" + verdict(res))


def verdict(res) -> str:
    """One line a person can act on. Also what --slack posts."""
    if res["only_eve"] or res["only_bot"]:
        extra = (f"  ADEMÁS hay filas en una sola pestaña "
                 f"({len(res['only_eve'])} solo de Eve, "
                 f"{len(res['only_bot'])} solo del bot).")
    else:
        extra = ""
    if not res["diffs"]:
        return (f"✅ IGUALES — nada que corregir en las {len(res['weeks'])} "
                f"semana(s) revisadas.{extra}")
    net = round(sum(d["delta"] for d in res["diffs"]), 2)
    weeks = sorted({d["week"] for d in res["diffs"]})
    return (f"⚠ {len(res['diffs'])} celda(s) distinta(s) en {len(weeks)} semana(s) "
            f"({', '.join(weeks)}), neto Eve − bot = {net:+,.2f}.{extra}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Compara la pestaña de overrides que llena Eve a mano contra "
                    "la que llena el bot. No escribe nada.")
    ap.add_argument("--weeks", type=int, default=None,
                    help="cuántas semanas revisar, de la más nueva hacia atrás "
                         "(default: la misma ventana que el backtrack, 5)")
    ap.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                    help=f"diferencia mínima en dólares para listarla (default "
                         f"${DEFAULT_TOLERANCE:.0f} — el bulletin publica dólares "
                         f"enteros, así que menos que eso no cambia nada; usá 0 "
                         f"para ver hasta el último centavo)")
    ap.add_argument("--slack", action="store_true",
                    help="además, postear el veredicto en "
                         "#claudecorrections-and-requests")
    a = ap.parse_args(argv)

    res = compare(weeks=a.weeks, tolerance=a.tolerance)

    if a.slack:
        try:
            from automations.shared import slack_metrics_post as smp
            smp._client().chat_postMessage(
                channel="#claudecorrections-and-requests",
                text=f"*Override Bulletin — Eve a mano vs el bot*\n{verdict(res)}")
            print("posteado en #claudecorrections-and-requests")
        except Exception as e:  # noqa: BLE001 — avisar nunca puede voltear el chequeo
            print(f"⚠ no se pudo postear en Slack ({type(e).__name__}: "
                  f"{str(e)[:120]})")
    # Exit 0 even when the tabs differ: a difference is INFORMATION, not a failed
    # run, and a non-zero code would paint the Hub card red for a check that did
    # exactly its job.
    return 0


if __name__ == "__main__":
    sys.exit(main())
