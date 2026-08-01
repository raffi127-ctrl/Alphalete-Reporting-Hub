"""A cache of the real Tableau "Owner & Office" values, so the B2B onboarding form
can offer a PICK LIST instead of a blind free-text field.

Why this exists: a B2B office's churn + activation slice on the exact "Owner &
Office" string Tableau uses (e.g. `JAMIS GARAY [atomic marketing, inc.]`). Typing
anything else — even the OwnerVille office name ("MIDSPIRE INC") — silently
returns EMPTY data with no error (bit us onboarding jamis, 2026-08-01). Free-text
is the trap; a pick list of the strings Tableau actually uses removes it.

The form runs on Streamlit Cloud with no Tableau session, so it can't read the
values live. Instead a Tableau machine (the mini, where the Box pull runs)
refreshes them into the "Tableau Owners" tab of the master onboarding Sheet, and
the form reads that tab. Best-effort both ways: no cache yet (or a read error) =
the form falls back to guided free-text, never a crash.

Source today: the Box ALLEXP order-log export (box_order_log), the one crosstab we
already pull daily that carries an "Owner & Office" column. It covers every owner
in that export; an owner not yet there uses the form's free-text fallback (with
click-by-click guidance on copying the exact string from Tableau).
"""
from __future__ import annotations

from typing import List

from automations.office_onboarding import store

TAB = "Tableau Owners"
_HEADER = ["Owner & Office", "rows", "source", "updated"]


def _ss():
    return store.get_client().open_by_key(store.MASTER_SHEET_ID)


def _tab(create: bool):
    ss = _ss()
    try:
        return ss.worksheet(TAB)
    except Exception:  # noqa: BLE001 — worksheet-not-found
        if not create:
            return None
        ws = ss.add_worksheet(title=TAB, rows=400, cols=len(_HEADER))
        ws.update("A1", [_HEADER])
        return ws


def known_owners() -> List[str]:
    """The distinct "Owner & Office" values the form offers as a pick list. []
    when the cache tab doesn't exist yet or can't be read — the caller then falls
    back to free-text. Never raises."""
    try:
        ws = _tab(create=False)
        if ws is None:
            return []
        col = ws.col_values(1)[1:]  # skip header
        seen, out = set(), []
        for v in col:
            v = (v or "").strip()
            if v and v not in seen:
                seen.add(v)
                out.append(v)
        return out
    except Exception:  # noqa: BLE001 — a cache read must never break the form
        return []


def refresh_from_box_export(csv_path=None, *, updated: str = "") -> int:
    """Rewrite the "Tableau Owners" tab from the Box ALLEXP export's distinct
    "Owner & Office" values (with row counts, most-common first). Returns the
    number of distinct owners written, or -1 on a handled failure. Best-effort:
    called opportunistically by the daily Box pull, so it must never raise into
    that run.

    `updated` is passed in (the caller stamps the date — this module has no clock)
    so it stays deterministic/testable.
    """
    import collections
    from pathlib import Path
    from automations.box_order_log import clean, per_office
    try:
        src = Path(csv_path) if csv_path else per_office._shared_team_file()
        if not src.exists():
            return -1
        rows = clean.read_rows(src)
        col = clean.OWNER_OFFICE_COL
        if not rows or col not in rows[0]:
            return -1
        counts = collections.Counter((r.get(col) or "").strip() for r in rows)
        counts.pop("", None)
        if not counts:
            return -1
        body = [[val, n, "box_allexp", updated] for val, n in counts.most_common()]
        ws = _tab(create=True)
        # Overwrite the value rows (this is a derived cache tab we own — never a
        # user-filled tab), leaving the header intact.
        ws.resize(rows=len(body) + 1, cols=len(_HEADER))
        ws.update("A1", [_HEADER] + body)
        return len(body)
    except Exception:  # noqa: BLE001 — cache refresh must never sink the Box run
        return -1
