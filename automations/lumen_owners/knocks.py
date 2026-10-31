"""Yesterday's Quantum Fiber knock boards for the Lumen Owners mail.

WHY (Eve, 2026-10-23): the mail now goes to Chan + the Quantum owners and
should look like a captainship mail, which carries knock boards. These are
the SAME boards Chan's captainship draft draws for his Quantum owners
(OwnerVille campaign 7): the owner list is captainship_drafts.config.
EXTRA_CAMPAIGN_KNOCK_OWNERS["chan"], so when Myles Neal / Angel Padilla give
Office Access and get uncommented there, both mails pick them up — one list.
LUMEN_EXTRA adds the Lumen owners who aren't Chan's (Christian, Lala, Nigel).

The boards go as PDFs attached to the mail, not as pictures in the body
(Eve, 2026-10-24) — the body only says they're attached. Like a captainship
mail: one PDF with every board + one per owner (Eve, 2026-10-25). A board that can't be
pulled becomes a note line; it never stops the mail.
"""
from __future__ import annotations

import datetime as dt
import html
from pathlib import Path
from typing import List, Tuple

CAPTAIN_KEY = "chan"

# Lumen owners with Quantum knocks who are NOT Chan's (Raf, 2026-10-25: "I
# thought we already had Christian, Lala & Nigel?"). Both already have
# OwnerVille access on campaign 7: Christian's picker (knocks_pull
# CAMPAIGN_OVERRIDES), Lala's nightly Quantum dispositions (gap_alerts
# LALA_QF). Nigel Marshall gave Office Access 2026-10-25 (office 20034, Eve).
LUMEN_EXTRA = (
    ("Christian Esposito", "7", "Quantum Fiber"),
    ("Lajahnik Valentine", "7", "Quantum Fiber"),
    ("Nigel Marshall", "7", "Quantum Fiber"),
    # Office 12737; probe_knocks campaign=7 for 10/24 came back with reps
    # (Eve, 2026-10-25: "agregalo si tenemos acceso").
    ("Aaron Nimako", "7", "Quantum Fiber"),
    # Replied to Chan's "reply with your ownerville code" on the 10/29 mail
    # (Eve, 2026-10-30): Isaiah 23639, Vaughn 23769.
    ("Isaiah Kellum", "7", "Quantum Fiber"),
    ("Vaughn Osterhouse", "7", "Quantum Fiber"),
)


# One set of attachments per OwnerVille campaign, Quantum first (the
# original), then AT&T (Aaron Nimako on the 10/31 mail: "can we have the at&t
# knocks attached too? Not just the quantum knocks?"). (campaign, tag, file
# suffix) — the suffix keeps an owner's AT&T files apart from their Quantum
# ones in the attachment strip; Quantum keeps the names Eve approved.
QUANTUM = ("7", "Quantum Fiber", "")
ATT = ("3", "AT&T", "ATT")   # 3 = RES AT&T, knocks_pull's default campaign
PROGRAMS = (QUANTUM, ATT)

# Not Lumen owners, but on the AT&T set only, after the Lumen owners (Isaiah
# Kellum on the 10/31 mail: "Can we get Chan & rafs numbers as well please?"
# — confirmed "just their knocks"). AT&T is what they knock; no Quantum.
# Raf is the OwnerVille master row (no impersonation, owner_cfgs).
ATT_ONLY = ("Chan Park", "Rafael Hidalgo")


def owner_boards(aliases_raw, logfn=print, program=QUANTUM
                 ) -> List[Tuple[str, dict]]:
    """[(label, cfg)] — one per Lumen owner with OwnerVille access: Chan's
    Quantum list first, then LUMEN_EXTRA, pinned to `program`'s campaign."""
    from automations.captainship_drafts import config as _cfg
    from automations.captainship_drafts.knock_dispo_images import (
        extra_campaign_pairs)
    campaign, tag, _suffix = program
    chan = tuple((getattr(_cfg, "EXTRA_CAMPAIGN_KNOCK_OWNERS", {}) or {}
                  ).get(CAPTAIN_KEY, ()))
    seen = {s[0] for s in chan}
    names = [s[0] for s in chan] + [s[0] for s in LUMEN_EXTRA
                                    if s[0] not in seen]
    if program == ATT:
        names += [n for n in ATT_ONLY if n not in names]
    specs = tuple((n, campaign, tag) for n in names)
    return extra_campaign_pairs(CAPTAIN_KEY, aliases_raw, logfn=logfn,
                                specs=specs)


def note_html(failed: List[Tuple[str, str]]) -> str:
    """One orange line per board that could not be drawn. Pure."""
    return "".join(
        '<p style="color:#b35900;font-size:12px">Knocks for %s could not be '
        "pulled this run (%s).</p>" % (html.escape(label), html.escape(why))
        for label, why in failed)


PDF_LABEL = "Daily Knocks — Quantum Fiber"  # = daily_label(QUANTUM)
TITLE = "Lumen Owners"


def daily_label(program=QUANTUM) -> str:
    """'Daily Knocks — AT&T' — the body's "attached" line. Pure."""
    return "Daily Knocks — %s" % program[1]


def weekly_label(program=QUANTUM) -> str:
    return "Weekly Knocks — %s" % program[1]


def _with_suffix(who: str, program) -> str:
    return ("%s %s" % (who, program[2])) if program[2] else who


def owner_name(label: str) -> str:
    """'Nigel Marshall (Quantum Fiber)' -> 'Nigel Marshall'. Pure."""
    return label.split(" (", 1)[0].strip()


def pdf_files(blocks, day: dt.date, out_dir: Path, program=QUANTUM) -> list:
    """[(attachment label, pdf)] the captainship way (Eve, 2026-10-25): one
    PDF with every board, then one PDF per owner, named owner-first
    ('Nigel Marshall - Daily Knocks disposition - Oct 24, 2026') so each
    owner can pick out their own on a phone."""
    from automations.captainship_drafts.daily_pdf import attachment_name
    from automations.captainship_drafts.pdf_pages import compose
    label = lambda who: attachment_name(who, day)[:-len(".pdf")]
    out_dir = Path(out_dir)
    files = [(label(_with_suffix(TITLE, program)), compose(
        blocks, out_dir / ("knocks-%s.pdf" % day.isoformat())))]
    for lab, png in blocks:
        who = owner_name(lab)
        files.append((label(_with_suffix(who, program)), compose(
            [(who, png)], owner_dir(out_dir, lab) / "knocks.pdf")))
    return files


def owner_dir(out_dir: Path, label: str) -> Path:
    """out_dir/<label as a folder name>, created. Pure but for the mkdir."""
    d = Path(out_dir) / "".join(c if c.isalnum() else "_" for c in label)
    d.mkdir(parents=True, exist_ok=True)
    return d


WEEKLY_LABEL = "Weekly Knocks — Quantum Fiber"
# Kept under output/, not the day's folder: last week's PDF rides every day
# until next Sunday, and only the first run of the week pays the pull.
WEEKLY_DIR = (Path(__file__).resolve().parents[2] / "output" / "lumen_owners"
              / "weekly")


def weekly_window(today: dt.date) -> Tuple[dt.date, dt.date]:
    """(monday, saturday) of the week the last Sunday covered — the week a
    captainship mail's Weekly Knock Dispositions PDF carries every day
    (weekly_pdf.last_report_saturday). Pure."""
    from automations.captainship_drafts.weekly_pdf import last_report_saturday
    sat = last_report_saturday(today)
    return sat - dt.timedelta(days=5), sat


def weekly_pdf_path(saturday: dt.date, labels=()) -> Path:
    """The kept PDF for one week AND one owner list: an owner added mid-week
    (Aaron, 2026-10-25) gets a new file, so the week is pulled again with
    them instead of reusing the PDF that left them out. Pure."""
    import hashlib
    tag = hashlib.sha1("|".join(sorted(labels)).encode("utf-8")).hexdigest()[:8]
    return WEEKLY_DIR / ("lumen_weekly_knocks_%s_%s.pdf"
                         % (saturday.isoformat(), tag))


def weekly_attachment_label(saturday: dt.date, program=QUANTUM) -> str:
    """'Weekly Knock Dispositions - Lumen Owners - Oct 19-24, 2026' (AT&T:
    '... - Lumen Owners ATT - ...'). Pure."""
    from automations.captainship_drafts.weekly_pdf import attachment_name
    return attachment_name(_with_suffix(TITLE, program),
                           saturday)[:-len(".pdf")]


def _weekly_board(page, label, cfg, aliases_raw, monday, saturday, out_dir):
    """One owner's Mon–Sat Knock Dispositions board (the captainship weekly
    board, no apps column). None when the week has no knocks."""
    from automations.weekly_knock_dispositions import board as B
    from automations.weekly_knock_dispositions import pull as P
    ov_rows, dispo_cols = P.pull_office_week(page, cfg, aliases_raw, monday,
                                             saturday, verbose=False)
    if not ov_rows:
        return None
    rows = B.compute_rows(ov_rows, None, dispo_cols)
    return B.render(label, monday, saturday, rows,
                    owner_dir(out_dir, label), dispo_cols,
                    gaps_only=B.is_gaps_only(ov_rows), n_totals=1,
                    no_apps=True)


def _pull_program(page, pairs, aliases_raw, target, monday, saturday,
                  have_weekly, out_dir, logfn):
    """One campaign's boards on the open OwnerVille page: (daily blocks,
    daily failures, weekly blocks, weekly failures). One owner failing is a
    note, never the mail."""
    from automations.captainship_drafts import knock_dispo_images as K
    blocks, failed, weekly, weekly_failed = [], [], [], []
    for label, cfg in pairs:
        try:
            rows = K._daily_rows_for_owner(page, cfg, aliases_raw, target)
            if not rows:
                failed.append((label, "no knocks in OwnerVille for %s"
                               % target.strftime("%m/%d")))
                continue
            # One folder per owner: the board's file name is only the date,
            # so a shared folder left every page the LAST owner's board (4x
            # Nigel, 2026-10-25).
            png = K.render_owner_daily_board(
                target, rows, rows, owner_dir(out_dir, label), label)
            blocks.append((label, png))
            logfn("[lumen] knocks %s: %d rep(s)" % (label, len(rows)))
        except Exception as e:  # noqa: BLE001 — one owner, not the mail
            failed.append((label, type(e).__name__))
            logfn("[lumen] knocks %s FAILED: %s: %s"
                  % (label, type(e).__name__, e))
    if not have_weekly:
        for label, cfg in pairs:
            try:
                png = _weekly_board(page, label, cfg, aliases_raw, monday,
                                    saturday, out_dir / "weekly")
                if png is None:
                    logfn("[lumen] weekly %s: no knocks" % label)
                    continue
                weekly.append((label, png))
                logfn("[lumen] weekly %s: ok" % label)
            except Exception as e:  # noqa: BLE001 — one owner
                weekly_failed.append((label, type(e).__name__))
                logfn("[lumen] weekly %s FAILED: %s: %s"
                      % (label, type(e).__name__, e))
    return blocks, failed, weekly, weekly_failed


def program_dir(out_dir: Path, program) -> Path:
    """<out>/knocks for Quantum (as before), <out>/knocks/ATT for AT&T — the
    combined PDF is named by date only, so each campaign needs its own
    folder. Pure."""
    d = Path(out_dir) / "knocks"
    return d / program[2] if program[2] else d


def build(today: dt.date, out_dir: Path, aliases_raw, logfn=print,
          programs=PROGRAMS) -> Tuple[list, list]:
    """(email blocks, files to attach). Per campaign (Quantum, then AT&T —
    Aaron, 2026-10-31): one DAILY TOTAL KNOCKS board per owner for yesterday
    (one PDF with all + one per owner), then last week's Knock Dispositions
    as one PDF (Eve, 2026-10-25) — pulled once a week, then reused from
    WEEKLY_DIR. The body gets an "attached" line per kind, then the notes for
    any board that failed. ([], []) when nobody is configured. One
    OwnerVille session for every campaign."""
    from automations.captainship_drafts import knock_dispo_images as K
    from automations.shared.tableau_patchright import ownerville_session

    work = []
    for program in programs:
        pairs = owner_boards(aliases_raw, logfn=logfn, program=program)
        if pairs:
            work.append((program, pairs))
    if not work:
        return [], []
    target = K.daily_target(today)
    monday, saturday = weekly_window(today)
    plan = []
    for program, pairs in work:
        pdir = program_dir(out_dir, program)
        pdir.mkdir(parents=True, exist_ok=True)
        kept = weekly_pdf_path(saturday, [l for l, _c in pairs])
        plan.append({"program": program, "pairs": pairs, "dir": pdir,
                     "kept": kept,
                     "have_weekly": kept.exists() and kept.stat().st_size > 0,
                     "res": ([], [], [], [])})
    # The box pictures (board.render_boxes) leave sheet_render's shared sync
    # playwright running, and a second sync playwright in the same thread dies
    # with "using Playwright Sync API inside the asyncio loop" — the first
    # test send, 2026-10-23. Same medicine as the captainship knocks.
    try:
        from automations.captainship_drafts import sheet_render
        sheet_render.close_renderer()
    except Exception:  # noqa: BLE001
        pass
    try:
        with ownerville_session(verbose=False, profile_dir=K.PROFILE_DIR) as page:
            for p in plan:
                p["res"] = _pull_program(page, p["pairs"], aliases_raw, target,
                                         monday, saturday, p["have_weekly"],
                                         p["dir"], logfn)
    except Exception as e:  # noqa: BLE001 — no OwnerVille, still a mail
        logfn("[lumen] OwnerVille session FAILED: %s: %s" % (type(e).__name__, e))
        for p in plan:
            p["res"] = ([], [(l, "OwnerVille login failed")
                             for l, _c in p["pairs"]], [], [])
    files, out, notes = [], [], []
    for p in plan:
        f, o, n = _assemble(p, target, saturday, logfn)
        files += f
        out += o
        notes += n
    return out + notes, files


def _assemble(p, target, saturday, logfn):
    """(files, "attached" blocks, note blocks) for one campaign's pull."""
    program, kept, pdir = p["program"], p["kept"], p["dir"]
    blocks, failed, weekly, weekly_failed = p["res"]
    failed = list(failed)
    files, out, notes = [], [], []
    if blocks:
        try:
            files = pdf_files(blocks, target, pdir, program)
            out = [(daily_label(program), None, None, "attached")]
        except Exception as e:  # noqa: BLE001 — a note, not a dead mail
            logfn("[lumen] knocks PDF FAILED: %s: %s" % (type(e).__name__, e))
            failed += [(l, "PDF failed") for l, _p in blocks]
    weekly_pdf = kept if p["have_weekly"] else None
    if weekly:
        from automations.captainship_drafts.pdf_pages import compose
        try:
            # Kept for the rest of the week only when every owner came
            # through; a short one is mailed today and pulled again tomorrow.
            dest = kept if not weekly_failed else pdir / "weekly" / kept.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            weekly_pdf = compose(weekly, dest)
        except Exception as e:  # noqa: BLE001 — a note, not a dead mail
            logfn("[lumen] weekly PDF FAILED: %s: %s" % (type(e).__name__, e))
    if weekly_pdf is not None:
        files.append((weekly_attachment_label(saturday, program), weekly_pdf))
        out.append((weekly_label(program), None, None, "attached"))
    if failed:
        notes.append((note_html(failed), None, None, "note"))
    if weekly_failed:
        notes.append((note_html([(l + " — last week", w)
                                 for l, w in weekly_failed]), None, None, "note"))
    return files, out, notes
