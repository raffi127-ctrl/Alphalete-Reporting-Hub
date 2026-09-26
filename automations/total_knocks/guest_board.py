"""The guest office's own knock board — built off the host's pull, delivered
to the guest's own people.

WHAT IT IS. `guests.split()` takes the reps who knock on somebody else's
ownerville off the host's board; this draws THEM, through the same renderer
every other knock board goes through (`render_knocks_boards`), so it arrives
with the columns Raf's board has, the teal CHAN PARK TOTAL comparison line —
Megan 2026-09-25: "format it to then include Chan's numbers and then the
totals for these reps" — and an OFFICE TOTAL row scoped to exactly those reps.

NO SECOND PULL AND NO SECOND LOGIN. Both `rows` and `extra_totals` are the
ones the host's run already has in hand: the guest's reps came out of the
host's grid, and Chan's rows were pulled for the host's own comparison line.
One ownerville session, two boards.

NOT BROKEN UP BY TEAM. The team split reads the Team column on the HOST's
sales board (weekly_knock_dispositions.teams), and these reps are not on it —
every one of them would land in the grey UNASSIGNED band, which is a band
saying nothing about a list that is already one team. The board draws flat,
ranked by knocks like every other one.

WHO SENDS IT. For Carlos — the only guest today — the send lives in
`gap_alerts`, on Lucy 1: the box that can text, and the one already holding
Raf's pull. `DESTINATIONS` here is for a guest whose host that job does not
cover; an empty entry means the board renders and the log says where the file
is, rather than anything going out quietly. `deliver()` defaults to dry_run
either way. Standing rule: ask before any send, verify the recipient.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

OUT_DIR_DEFAULT = Path("output") / "guest_knocks"


# guest office -> where their board goes, for a guest whose HOST is not
# covered by gap_alerts.
#
# CARLOS'S ROOMS ARE NOT HERE, AND THAT IS THE POINT. Only Lucy 1 can text
# (Megan 2026-09-25: "Lucy 1, those two groups are right"), and Lucy 1 is
# where `gap_alerts` runs — the job that already holds Raf's pull, already
# renders this board, already resolves iMessage groups by name and already
# owns the per-room cadence and anchor bookkeeping. So his two rooms live in
# ONE place, `gap_alerts.config.RAF["guests"]`, and this map stays empty
# rather than naming the same groups twice: two configs for one audience is
# how a room ends up getting the same board from two machines.
#
# The morning Total Knocks run and the intraday slots therefore RENDER the
# guest board and say where the file is; they do not send it. (Intraday runs
# on Lucy 3, which reaches only some phones anyway.)
#
#   text_groups: iMessage GROUP NAMES — never chat ids. A group's id is minted
#                fresh every time its membership changes, and a stale one
#                "sends" into a thread nobody reads;
#                b2b_dispositions.text_post resolves the name on every send.
#   channels:    Slack channel ids, posted as Lucy.
DESTINATIONS: dict = {}


def destinations(guest: str) -> dict:
    d = DESTINATIONS.get(guest) or {}
    return {"text_groups": list(d.get("text_groups") or []),
            "channels": list(d.get("channels") or [])}


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def build(day: dt.date, guest: str, rows, *, extra_totals=None,
          out_dir: Path = OUT_DIR_DEFAULT, date_text: str = "",
          end: "dt.date | None" = None, logfn=print):
    """Render `guest`'s board for `day`. Returns (png, shape), or (None, '')
    for a guest with no rows — a board nobody knocked for is not posted blank.
    """
    if not rows:
        logfn(f"[guests] {guest}: no rows for {day} — no board")
        return None, ""
    from automations.total_knocks import render as knocks_render

    pngs, shape = knocks_render.render_knocks_boards(
        day, rows=rows, out_dir=out_dir / _slug(guest),
        title_suffix=guest, end=end, date_text=date_text,
        extra_totals=list(extra_totals or []),
        # These reps are not on the host's sales board — see the module note.
        teams=None)
    logfn(f"[guests] {guest}: {len(rows)} rep(s) -> {pngs[0].name}")
    return pngs[0], shape


def deliver(png, guest: str, caption: str, *, dry_run: bool = True,
            logfn=print) -> dict:
    """Send `png` to every destination `guest` has. Returns
    {'sent': [...], 'failed': [(where, error)], 'skipped': bool}.

    dry_run is the DEFAULT on purpose — every caller has to say --send.
    """
    out = {"sent": [], "failed": [], "skipped": False}
    dest = destinations(guest)
    if not (dest["text_groups"] or dest["channels"]):
        out["skipped"] = True
        logfn(f"[guests] {guest}: no destination configured — board is at "
              f"{png} and nothing was sent")
        return out
    if png is None:
        out["skipped"] = True
        return out

    for group in dest["text_groups"]:
        if dry_run:
            logfn(f"[guests] would text {guest}'s board to '{group}'")
            out["sent"].append(group)
            continue
        try:
            from automations.b2b_dispositions import text_post
            text_post.send_to_group(group, caption, [Path(png)],
                                    dry_run=False)
            out["sent"].append(group)
            logfn(f"[guests] ✓ texted {guest}'s board to '{group}'")
        except Exception as e:                        # noqa: BLE001
            out["failed"].append((group, e))
            logfn(f"[guests] ❌ text to '{group}': {type(e).__name__}: {e}")

    for chan in dest["channels"]:
        if dry_run:
            logfn(f"[guests] would post {guest}'s board to {chan}")
            out["sent"].append(chan)
            continue
        try:
            from automations.shared import slack_metrics_post as smp
            smp.post_reply_with_image(
                Path(png), comment=caption, channel_id=chan,
                file_name=f"{guest} knocks {png.stem}.png",
                wait_visible=True, top_level=True)
            out["sent"].append(chan)
            logfn(f"[guests] ✓ posted {guest}'s board to {chan}")
        except Exception as e:                        # noqa: BLE001
            out["failed"].append((chan, e))
            logfn(f"[guests] ❌ post to {chan}: {type(e).__name__}: {e}")
    return out
