"""Has Atef's captainship shown up on the NDS side of Tableau yet? -> DM Eve once.

WHY: Cesar Castillo, 2026-10-05: "we have switched campaigns for NDS for Atef
officially ... switch all those B2B trackers to NDS". Eve: the whole captainship
moves (Atef Choudhury, Sabrina Alicea, Dhyey Patel). But that same day the NDS
workbook had none of the three, and no "Atef's Team" in NDS Captain Teams —
SmartCircle moves an owner between programs on its own clock (same as Noah
Dubale, see memory project_noah-dubale-is-nds-not-b2b). Switching our reports
before that blanks every one of them. So this waits, and tells Eve the day they
appear, so the switch happens all at once.

WHAT IT READS (both HTTP .csv, the same views opt_nds / pull_nds already pull):
  NDS-SNRES-ATT-OOFWorkbook/NDSWeeklyMetricsRep   'Owner & Office' column
  NDS-SNRES-ATT-OOFWorkbook/CaptainsTeam          'NDS Captain Teams' + 'Owner Name'

A BLANK READ IS NOT "NOT THERE YET": if the weekly metrics don't carry a known
NDS owner (Colten Wright) the read is broken, and it exits 1 instead of quietly
saying "nothing yet" forever.

TWO DMs AT MOST. State lives in output/atef_nds_watch/announced.json.
  1. first sighting ("sent") — the first pass that sees ANY of them. Says "not
     yet": on 2026-10-07 only Atef showed up (no Sabrina/Dhyey/team), and
     switching then would blank the captainship reports.
  2. complete ("complete_sent") — all three people AND "Atef's Team". THIS is
     the "go switch now" DM.
Later passes only log. `--again` re-sends the current stage on purpose.

WHERE IT RUNS: a Lucy (the Windows machine shuts down at night, and its Slack
token is a person, not Lucy). From Windows it prints and refuses to send.

  python -m automations.atef_nds_watch.run --dry-run    # read Tableau, send nothing
  python -m automations.atef_nds_watch.run --post       # the scheduled pass
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import platform
import re
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "atef_nds_watch"
STATE_PATH = OUT_DIR / "announced.json"

EVE_USER_ID = "U088E2KJEV8"          # Evelyn Sobrino

WORKBOOK = "NDS-SNRES-ATT-OOFWorkbook"
VIEW_OWNERS = "NDSWeeklyMetricsRep"
VIEW_TEAMS = "CaptainsTeam"

# Tableau spells him "Choudhury" and Dhey as "Dhyey" — match loosely.
PEOPLE = {
    "Atef Choudhury": re.compile(r"\batef\b|choudh?u?ry|domin8", re.I),
    "Sabrina Alicea": re.compile(r"sabrina\s+alicea|\balicea\b", re.I),
    "Dhyey Patel": re.compile(r"\bdh(y)?ey\s+patel\b", re.I),
}
TEAM = re.compile(r"atef'?s\s+team", re.I)
CONTROL = re.compile(r"colten\s+wright", re.I)


# --------------------------------------------------------------------------
# parsing (pure — tested)
# --------------------------------------------------------------------------

def _decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("ISO-8859-1")


def _column(text: str, *names: str) -> List[str]:
    """Distinct values of the first header matching any of `names`
    (case/space-insensitive — Tableau leaves a trailing space on
    'Owner & Office ')."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    want = {" ".join(n.lower().split()) for n in names}
    head = [" ".join(h.lower().split()) for h in rows[0]]
    idx = next((i for i, h in enumerate(head) if h in want), None)
    if idx is None:
        return []
    seen: List[str] = []
    for r in rows[1:]:
        if idx < len(r):
            v = " ".join(r[idx].split())
            if v and v not in seen:
                seen.append(v)
    return seen


def find(owners_csv: str, teams_csv: str) -> Dict[str, object]:
    """What the two views say. Raises ValueError on a read that can't be
    trusted (no control owner) — "not there" must never come from a blank."""
    owners = _column(owners_csv, "Owner & Office", "Owner")
    if not any(CONTROL.search(o) for o in owners):
        raise ValueError(
            f"{VIEW_OWNERS} read looks broken: {len(owners)} owners and no "
            "Colten Wright — not trusting it as 'not there yet'")
    team_owners = _column(teams_csv, "Owner Name")
    teams = _column(teams_csv, "NDS Captain Teams")
    people = {}
    for name, rx in PEOPLE.items():
        hits = [o for o in owners + team_owners if rx.search(o)]
        if hits:
            people[name] = sorted(set(hits))
    return {
        "people": people,
        "team": [t for t in teams if TEAM.search(t)],
        "teams_seen": teams,
        "owner_count": len(owners),
    }


def complete(found: Dict[str, object]) -> bool:
    """Everything the switch needs: all three people and the captain team."""
    return bool(found["team"]) and all(n in found["people"] for n in PEOPLE)


def message(found: Dict[str, object], today: dt.date) -> str:
    people = found["people"]
    title = ("Capitania de Atef COMPLETA en Tableau NDS" if complete(found)
             else "Atef ya aparece en Tableau NDS")
    lines = [f"*{title}* ({today.isoformat()})", ""]
    for name in PEOPLE:
        lines.append(f"- {name}: {'SI' if name in people else 'todavia no'}")
    lines.append(f"- \"Atef's Team\" en NDS Captain Teams: "
                 f"{'SI' if found['team'] else 'todavia no'}")
    lines += ["",
              "Fuente: Tableau > NDS-SNRES-ATT-OOFWorkbook > NDSWeeklyMetricsRep "
              "(Owner & Office) y CaptainsTeam.",
              ""]
    if complete(found):
        lines += ["Ya se puede pasar la capitania de B2B a NDS (lista en memoria: "
                  "project_atef-switch-to-nds-pending). Pedile a Claude que lo haga.",
                  "Despues avisale a Cesar Castillo: mientras tanto el postea los "
                  "trackers NDS a mano y pidio que le avisemos (10/5)."]
    else:
        lines += ["Todavia NO pases la capitania: sin el equipo completo los "
                  "reportes quedan vacios. Te aviso de nuevo cuando esten todos."]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Tableau + Slack
# --------------------------------------------------------------------------

def pull() -> Dict[str, str]:
    from automations.alphalete_org_report import tableau_http
    from automations.shared.tableau_patchright import (
        requests_session_from_page, tableau_session,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    with tableau_session(verbose=False) as page:
        s = requests_session_from_page(page)
        for view in (VIEW_OWNERS, VIEW_TEAMS):
            p = tableau_http.download_view_csv(WORKBOOK, view,
                                               OUT_DIR / f"{view}.csv",
                                               session=s)
            out[view] = _decode(p.read_bytes())
    return out


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no file = nothing sent yet
        return {}


def save_state(state: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1, sort_keys=True),
                          encoding="utf-8")


def send(text: str) -> bool:
    """DM Eve as Lucy. Refuses from Windows / a non-Lucy token, the same guard
    terminated_notice uses."""
    if platform.system() == "Windows":
        print("! not sending from Windows (token here is a person, not Lucy). "
              "Run it on a Lucy: lucy rerun atef_nds_watch")
        return False
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    who = ""
    try:
        who = client.auth_test().get("user", "")
    except Exception:  # noqa: BLE001
        pass
    if who and "lucy" not in who.lower():
        print(f"! this machine posts as {who}, not Lucy - not sending.")
        return False
    ch = client.conversations_open(users=EVE_USER_ID)["channel"]["id"]
    client.chat_postMessage(channel=ch, text=text)
    print("  sent DM to Eve")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--post", action="store_true",
                    help="DM Eve when they appear (the scheduled pass)")
    ap.add_argument("--dry-run", action="store_true",
                    help="read Tableau, print, send nothing, save no state")
    ap.add_argument("--again", action="store_true",
                    help="re-send the DM even if it already went out")
    a = ap.parse_args(argv)
    dry = a.dry_run or not a.post

    views = pull()
    try:
        found = find(views[VIEW_OWNERS], views[VIEW_TEAMS])
    except ValueError as e:
        print(f"! {e}")
        return 1

    print(f"NDS owners read: {found['owner_count']}")
    print(f"NDS captain teams: {' | '.join(found['teams_seen']) or '(none)'}")
    for name in PEOPLE:
        hits = found["people"].get(name)
        print(f"  {name}: {'; '.join(hits) if hits else 'not on NDS yet'}")
    print(f"  Atef's Team: {'yes' if found['team'] else 'not yet'}")

    if not found["people"] and not found["team"]:
        print("nothing yet - no DM")
        return 0

    state = load_state()
    key = "complete_sent" if complete(found) else "sent"
    if state.get(key) and not a.again:
        print(f"already told Eve ({key}) on {state.get(key)} - no DM")
        return 0

    text = message(found, dt.date.today())
    if dry:
        print("\n--- would DM Eve ---\n" + text)
        return 0
    if send(text):
        state.update({key: dt.date.today().isoformat(),
                      "people": found["people"], "team": found["team"]})
        save_state(state)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
