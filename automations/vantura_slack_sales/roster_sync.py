"""Campaign roster sync — keep reps on the board their campaign says (Carlos 2026-09-06).

The D2D (Verizon) board is a separate TAB, so "assign someone Verizon" needs
an actual row move — the bound script never learned this (it predates the
tab). This runs alongside ensure_board_shape on every live fill pass:

  * main "Sales Board" rep whose Campaign (L) says Verizon  -> row MOVES to
    "D2D Sales Board" (name, last wk, this week's day cells, trainer, field
    status VALUE, team, leadership travel; the main row is blanked).
  * "D2D Sales Board" rep whose Campaign is NOT Verizon -> moves back the
    same way (into the first empty main-board row).
  * live-week Roll Call person with campaign Verizon, status Active or
    New Start, not on either board -> ADDED to the first empty D2D row
    (name + trainer + "1st Wk"), same spirit as the add-to-board rules.

Row hygiene: C keeps its =SUM(E:K) formula on both boards, and a cleared D2D
row gets its "Verizon" campaign prefill back. Never touches terminated rows,
never duplicates (skips if the name is already on the target board); a full
target board is logged loudly and skipped, never overwritten. Day values are
written USER_ENTERED so numbers stay numbers for the SUM/SUMIFS totals.
"""
from __future__ import annotations

D2D_TAB = "D2D Sales Board"
D2D_FIRST, D2D_LAST = 5, 34


def _norm(s):
    return " ".join(str(s or "").split()).lower()


def _cell(g, r, i):
    row = g[r - 1] if r <= len(g) else []
    return (row[i] if len(row) > i else "").strip()


def _main_block(g):
    out = []
    for r in range(5, len(g) + 1):
        b = _cell(g, r, 1)
        if b.replace(" ", "").upper().startswith("AT&T(B2B)"):
            break
        out.append(r)
    return out


def _grab(g, r):
    """(lastwk, days E:K, trainer, field, team, lead) as display VALUES."""
    return ([_cell(g, r, 3)] + [_cell(g, r, i) for i in range(4, 11)]
            + [_cell(g, r, i) for i in (12, 13, 14, 15)])


def ensure_campaign_rosters(sh, log=print) -> None:
    from automations.recruiting_report.fill import _retry
    try:
        main = sh.worksheet("Sales Board")
        d2d = sh.worksheet(D2D_TAB)
    except Exception:
        return                       # D2D tab absent -> nothing to sync
    gm = main.get_all_values()
    gd = d2d.get_all_values()
    main_rows = _main_block(gm)
    d2d_rows = list(range(D2D_FIRST, D2D_LAST + 1))
    d2d_names = {_norm(_cell(gd, r, 1)) for r in d2d_rows if _cell(gd, r, 1)}
    main_names = {_norm(_cell(gm, r, 1)) for r in main_rows if _cell(gm, r, 1)}
    d2d_empty = [r for r in d2d_rows if not _cell(gd, r, 1)]
    main_empty = [r for r in main_rows if not _cell(gm, r, 1)]

    def clear_row(ws, r, camp_after):
        _retry(ws.batch_update, [
            {"range": f"B{r}:K{r}",
             "values": [["", f"=SUM(E{r}:K{r})"] + [""] * 8]},
            {"range": f"L{r}:P{r}", "values": [[camp_after, "", "", "", ""]]},
        ], value_input_option="USER_ENTERED")

    def place(ws, r, name, camp, vals):
        lastwk, days, rest = vals[0], vals[1:8], vals[8:]
        _retry(ws.batch_update, [
            {"range": f"B{r}:K{r}",
             "values": [[name, f"=SUM(E{r}:K{r})", lastwk] + days]},
            {"range": f"L{r}:P{r}", "values": [[camp] + rest]},
        ], value_input_option="USER_ENTERED")

    # main -> D2D
    for r in main_rows:
        name, camp = _cell(gm, r, 1), _cell(gm, r, 11)
        if not name or camp != "Verizon" or _cell(gm, r, 15) == "Terminated":
            continue
        if _norm(name) in d2d_names:
            clear_row(main, r, "")
            log(f"roster sync: {name} already on D2D — main row {r} cleared")
            continue
        if not d2d_empty:
            log(f"roster sync: D2D BOARD FULL — cannot move {name} (main r{r})")
            continue
        tr = d2d_empty.pop(0)
        place(d2d, tr, name, "Verizon", _grab(gm, r))
        clear_row(main, r, "")
        d2d_names.add(_norm(name))
        log(f"roster sync: {name} moved Sales Board r{r} -> {D2D_TAB} r{tr}")

    # D2D -> main (flipped away from Verizon)
    for r in d2d_rows:
        name, camp = _cell(gd, r, 1), _cell(gd, r, 11)
        if not name or camp in ("", "Verizon") or _cell(gd, r, 15) == "Terminated":
            continue
        if _norm(name) in main_names:
            clear_row(d2d, r, "Verizon")
            log(f"roster sync: {name} already on main — D2D row {r} cleared")
            continue
        if not main_empty:
            log(f"roster sync: MAIN BOARD FULL — cannot move {name} (D2D r{r})")
            continue
        tr = main_empty.pop(0)
        place(main, tr, name, camp, _grab(gd, r))
        clear_row(d2d, r, "Verizon")
        main_names.add(_norm(name))
        log(f"roster sync: {name} moved {D2D_TAB} r{r} -> Sales Board r{tr}")

    # Roll Call live-week Verizon people on neither board -> add to D2D
    try:
        roll = sh.worksheet("Roll Call").get_all_values()
    except Exception:
        return
    week = _cell(gm, 2, 1)                       # board B2 label
    for rr in range(3, len(roll) + 1):
        we, status, camp, name = (_cell(roll, rr, 0), _cell(roll, rr, 1),
                                  _cell(roll, rr, 2), _cell(roll, rr, 3))
        trainer = _cell(roll, rr, 5)
        if (we != week or camp != "Verizon" or not name
                or status not in ("Active", "New Start")):
            continue
        if _norm(name) in d2d_names or _norm(name) in main_names:
            continue
        if not d2d_empty:
            log(f"roster sync: D2D BOARD FULL — cannot add {name} from roll")
            continue
        tr = d2d_empty.pop(0)
        _retry(d2d.batch_update, [
            {"range": f"B{tr}:C{tr}", "values": [[name, f"=SUM(E{tr}:K{tr})"]]},
            {"range": f"L{tr}:P{tr}",
             "values": [["Verizon", trainer, "1st Wk", "", "In Training"]]},
        ], value_input_option="USER_ENTERED")
        d2d_names.add(_norm(name))
        log(f"roster sync: {name} added to {D2D_TAB} r{tr} from Roll Call")


# ---------------------------------------------------------------- standalone
INC_FULL = "vantura-roster-board-full"
REPORT_NAME = "Vantura campaign roster sync"


def _alert_full(msgs) -> None:
    """A move is stuck on a full board — tell the corrections channel once."""
    import datetime as dt
    from pathlib import Path
    state = (Path(__file__).resolve().parents[2]
             / "output" / ".vroster_full_alert")
    key = dt.date.today().isoformat() + "|" + "|".join(sorted(msgs))
    try:
        if state.read_text().strip() == key:
            return
    except Exception:  # noqa: BLE001 — no state file yet is normal
        pass
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(key)
    except Exception:  # noqa: BLE001 — never block the alert on bookkeeping
        pass
    from automations.day_orchestrator import notify
    from automations.day_orchestrator.registry import load_config
    notify.post_alert(
        f":no_entry: *{REPORT_NAME}* — a campaign move is stuck",
        ["Someone's campaign changed but the target board has no empty rep "
         "row, so the move is held (nothing was overwritten):", ""]
        + [f"  • {m}" for m in sorted(msgs)]
        + ["", "Free a row on the named board (or extend it) and the next "
               "pass finishes the move on its own."],
        tag="vantura-roster-sync-full", cfg=load_config(), incident=INC_FULL)


def main(argv=None) -> int:
    from automations.recruiting_report.fill import open_by_key
    lines: list[str] = []

    def log(m):
        lines.append(str(m))
        print(m, flush=True)

    sh = open_by_key("1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY")
    ensure_campaign_rosters(sh, log=log)
    full = [m for m in lines if "BOARD FULL" in m]
    try:
        if full:
            _alert_full(full)
        else:
            from automations.shared import incident_thread as inc
            inc.resolve_if_open(
                INC_FULL,
                what=f"*{REPORT_NAME}* — held campaign moves have landed",
                detail="_No board-full holds this pass._")
    except Exception as e:  # noqa: BLE001 — alerting must not fail the sync
        print(f"[alert] bookkeeping failed: {e}", flush=True)
    if not lines:
        print("roster sync: everyone is on the board their campaign says",
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
