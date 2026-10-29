"""Put a tab back the way one of the fixer's backups saw it.

Every --apply saves the tab's values + formulas to output/sales_board_fixer/
before writing (run.backup). This writes that copy back over the tab -- only
the cells that differ, so an ARRAYFORMULA's spill that didn't change is never
typed over (a typed value inside a spill turns the formula into #REF!).

Without --restore-write it only compares and prints. With it, the tab as it
is NOW is backed up first, so the restore can be undone the same way.

Jairo's tab, 2026-10-29: someone pasted one row over 31 reps mid-morning;
Maud asked for Lucy's 06:43 copy back.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
from pathlib import Path

from automations.sales_board_fixer import checks as K


def _grid(rows, height: int, width: int) -> list:
    return [[str(r[c]) if c < len(r) else "" for c in range(width)]
            for r in (list(rows) + [[]] * height)[:height]]


def diff(old: list, now: list) -> list:
    """[(row, col, old_value)] 1-based, for every cell where the backup's
    formula/value differs from the tab's now, inside the backup's area."""
    h = len(old)
    w = max([len(r) for r in old] + [0])
    a, b = _grid(old, h, w), _grid(now, h, w)
    return [(r + 1, c + 1, a[r][c]) for r in range(h) for c in range(w)
            if a[r][c] != b[r][c]]


def same_rows(values, name_col: int) -> int:
    """How many named rows share the single most common set of numbers --
    the mark of one row pasted over the others."""
    keys = collections.Counter(
        tuple(r[name_col:]) for r in values
        if len(r) > name_col and r[name_col - 1].strip() and any(
            c.strip() not in ("", "0", "0.0") for c in r[name_col:]))
    return keys.most_common(1)[0][1] if keys else 0


def run(sh, backup_file: Path, write: bool, out_dir: Path) -> int:
    b = json.loads(backup_file.read_text(encoding="utf-8"))
    title = b["title"]
    ws = sh.worksheet(title)
    now_f = ws.get_all_values(value_render_option="FORMULA")
    now_v = ws.get_all_values()
    try:
        name_col = K.layout(b["values"]).name_col
    except Exception:  # noqa: BLE001 -- not a board layout: skip the check
        name_col = 2
    print("restore %r from %s" % (title, backup_file.name))
    print("  reps con los mismos números -- copia: %d · ahora: %d"
          % (same_rows(b["values"], name_col), same_rows(now_v, name_col)))
    cells = diff(b["formulas"], now_f)
    print("  celdas distintas: %d" % len(cells))
    for r, c, v in cells[:15]:
        now = now_f[r - 1][c - 1] if r <= len(now_f) and c <= len(now_f[r - 1]) else ""
        print("   %s: %r -> %r" % (K.a1(r, c), str(now)[:40], v[:40]))
    extra = [i + 1 for i, r in enumerate(now_v[len(b["formulas"]):], start=len(b["formulas"]))
             if any(x.strip() for x in r)]
    if extra:
        print("  OJO: %d filas con datos debajo de la copia (no se tocan)" % len(extra))
    if not write:
        print("  (solo comparar: --restore-write para escribir)")
        return 0
    if not cells:
        print("  nada que escribir")
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    keep = out_dir / ("backup_%s_before-restore_%s_%s.json"
                      % (stamp, sh.id[:8], "".join(ch if ch.isalnum() else "-" for ch in title)))
    keep.write_text(json.dumps({"title": title, "values": now_v, "formulas": now_f},
                               ensure_ascii=False), encoding="utf-8")
    print("  backup de ahora:", keep)
    data = [{"range": "'%s'!%s" % (title, K.a1(r, c)), "values": [[v]]} for r, c, v in cells]
    for i in range(0, len(data), 500):
        sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": data[i:i + 500]})
    print("  escritos: %d" % len(cells))
    after = ws.get_all_values()
    print("  reps con los mismos números después: %d" % same_rows(after, name_col))
    return 0
