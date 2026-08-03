"""Standings email for the August Owner Showdown.

Cadence (Megan 2026-08-03): DAILY, 9:00am CST, Aug 1–31 — was Sundays-only.
The flyer rides along as a PDF attachment (and inline as a PNG preview), listing
EVERY competitor on BOTH sides: Personal Sales (28) and Rep Count Growth (30).

Data caveat kept from the original build: personal sales refresh daily, but rep
count is still polled SUNDAYS only (Raf blacked out the weekday columns), so the
rep-count board repeats Sunday's growth Mon–Sat.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Tuple

# Recipients (Megan 2026-08-03): the whole "Aug Owner Showdown" contact group —
# 48 people, competitors + observers + Raf — VISIBLE to each other, with Megan
# BCC'd so she sees every send without being on the reply-all path.
# Heads-up that comes with the visible list: a "nice work!" reply-all reaches all
# 48. Moving everyone to BCC is a one-line change if that gets old.
BCC_EMAILS = ["meganhidalgo1191@gmail.com"]     # Megan — hidden
TO_EMAIL = "raffi127@gmail.com"                 # fallback only (winner email)


def recipients() -> list:
    """The group expanded at SEND time, so Contacts is the source of truth and
    Megan can add/drop someone without a code change.

    Falls back to the committed seed list if the People API is unreachable (no
    contacts token on this machine, quota, outage) — a flyer going out to the
    seed is far better than no flyer, and the fallback is printed loudly."""
    from automations.owner_showdown import distro
    try:
        from automations.shared import contacts_auth
        emails, missing = contacts_auth.expand_groups([distro.GROUP_NAME])
        if missing:
            raise RuntimeError(f"contact group(s) not found: {missing}")
        if not emails:
            raise RuntimeError("group expanded to zero addresses")
        return emails
    except Exception as e:
        seed = distro.seed_emails()
        print(f"  ⚠ couldn't expand the {distro.GROUP_NAME!r} contact group "
              f"({type(e).__name__}: {e}) — falling back to the {len(seed)} "
              f"committed addresses in distro.py. Anyone added in Contacts "
              f"since the last deploy will NOT get this one.", flush=True)
        return seed
SHEET_URL = ("https://docs.google.com/spreadsheets/d/"
             "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit?gid=893154737")


def build_winner(sales_champ: Tuple[str, object],
                 rep_champ: Tuple[str, object]) -> Dict[str, str]:
    """Sept 1 champions email body (the champions flyer carries the visual)."""
    subject = "🏆 August Owner Showdown — the champions"
    sn, sv = sales_champ
    rn, rv = rep_champ
    rv_txt = f"+{rv}" if isinstance(rv, int) and rv >= 0 else str(rv)
    html = (
        f"<div style='font-family:Arial,sans-serif;max-width:560px'>"
        f"<h2 style='margin:0 0 12px'>🏆 August Owner Showdown — Champions</h2>"
        f"<p style='color:#333;line-height:1.5'>That's a wrap on August. "
        f"Congratulations to our two $5,000 winners:</p>"
        f"<p style='line-height:1.6'>💻 <b>Personal Sales</b> — {sn} "
        f"(<b>{sv}</b> new-internet sales)<br>"
        f"📈 <b>Rep Count Growth</b> — {rn} (<b>{rv_txt}</b> reps since Aug 2)</p>"
        # No sheet link here either — same reason as the standings email.
        f"<img src='cid:flyer' style='width:100%;max-width:560px;border-radius:12px'></div>")
    text = (f"August Owner Showdown — Champions\n\n"
            f"Personal Sales: {sn} ({sv} new-internet sales)\n"
            f"Rep Count Growth: {rn} ({rv_txt} reps since Aug 2)\n")
    return {"subject": subject, "html": html, "text": text}


PREVIEW_TO = ["meganhidalgo1191@gmail.com"]      # 8am preview — Megan ONLY


def build_preview(sales_rows, rep_rows, run_date: dt.date, changes,
                  notes) -> Dict[str, str]:
    """The 8am email to Megan ONLY (2026-08-03): the exact flyer the 9am run
    will send to all 48, plus what moved since the sheet's current numbers, so
    she has an hour to stop or correct it."""
    ds = f"{run_date:%b} {run_date.day}"
    subject = f"PREVIEW {ds} — Owner Showdown goes to 48 at 9am"

    if changes:
        rows = "".join(
            f"<tr><td style='padding:2px 10px 2px 0'>{n}</td>"
            f"<td style='padding:2px 10px;color:#888'>{o or '—'}</td>"
            f"<td style='padding:2px 0'><b>{v}</b></td></tr>" for n, o, v in changes)
        chg = (f"<p style='margin:14px 0 4px'><b>What changed since the sheet's "
               f"current numbers</b></p><table style='border-collapse:collapse;"
               f"font-size:14px'><tr><td style='color:#888'>owner</td>"
               f"<td style='color:#888;padding-left:10px'>was</td>"
               f"<td style='color:#888;padding-left:10px'>now</td></tr>{rows}</table>")
        chg_txt = "\n".join(f"  {n}: {o or '-'} -> {v}" for n, o, v in changes)
    else:
        chg = "<p style='margin:14px 0'><b>No changes</b> — same numbers as the sheet.</p>"
        chg_txt = "  (no changes)"

    note_html = "".join(f"<li>{n}</li>" for n in notes) or "<li>clean pull</li>"
    html = (
        f"<div style='font-family:Arial,sans-serif;max-width:600px'>"
        f"<h2 style='margin:0 0 2px'>Preview — {ds}</h2>"
        f"<div style='color:#666'>This is what goes to all 48 owners at 9:00am. "
        f"Nothing has been sent to them yet.</div>"
        f"{chg}"
        f"<p style='margin:14px 0 4px'><b>Pull</b></p>"
        f"<ul style='margin:0;padding-left:18px;color:#444'>{note_html}</ul>"
        f"<p style='margin:16px 0 6px;color:#7A4E06'><b>To stop the 9am send</b>, "
        f"tell Claude to stop the Owner Showdown, or run: "
        f"<code>lucy rerun disable_owner_showdown_agent</code></p>"
        f"<img src='cid:flyer' style='width:100%;max-width:600px;border-radius:12px;"
        f"margin-top:10px'></div>")
    text = (f"PREVIEW {ds} — goes to 48 owners at 9:00am. Not sent to them yet.\n\n"
            f"WHAT CHANGED:\n{chg_txt}\n\nPULL:\n" +
            "\n".join(f"  - {n}" for n in (notes or ["clean pull"])) +
            f"\n\nTo stop the 9am send: lucy rerun disable_owner_showdown_agent\n")
    return {"subject": subject, "html": html, "text": text}


def send_email(subject: str, html: str, text: str, png_path=None,
               pdf_path=None, dry_run: bool = False,
               tag: str = "owner-showdown", to_override=None) -> None:
    """Send To=Raf, CC=Megan, with the flyer PNG inline (cid:flyer) and the same
    flyer ATTACHED as a PDF (Megan 2026-08-03 — Raf wants the PDF daily).
    dry_run writes an .eml and does not send."""
    import smtplib, ssl, datetime as _dt
    from email.message import EmailMessage
    from pathlib import Path
    from automations.scheduled_6_days_out.email_send import (
        FROM_ADDR, SMTP_HOST, SMTP_PORT, app_password)

    # to_override = the 8am preview (Megan only). It must NEVER expand to the
    # group, so it bypasses recipients() entirely and gets no BCC.
    to_list = list(to_override) if to_override else recipients()
    bcc = [] if to_override else list(BCC_EMAILS)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(to_list)
    # NO Bcc header — a Bcc header would expose Megan to every recipient. The
    # blind copy happens by adding her to the envelope only, below.
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    if png_path:
        html_part = msg.get_payload()[-1]
        with open(png_path, "rb") as f:
            html_part.add_related(f.read(), maintype="image", subtype="png",
                                  cid="flyer")
    if pdf_path:
        # Attached AFTER the inline image so the body still previews the flyer
        # and the PDF rides along as a real downloadable attachment.
        with open(pdf_path, "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf",
                               filename=Path(pdf_path).name)
    # NOT named `recipients` — that is the module-level function above.
    envelope = list(to_list) + bcc
    if dry_run:
        out = Path(__file__).resolve().parents[2] / "output" / "logs"
        out.mkdir(parents=True, exist_ok=True)
        eml = out / f"{tag}-{_dt.datetime.now():%Y%m%d-%H%M%S}.eml"
        eml.write_bytes(bytes(msg))
        print(f"[owner-showdown] DRY-RUN wrote {eml} (would send to "
              f"{len(envelope)} recipients)", flush=True)
        return
    try:
        ctx = ssl.create_default_context(cafile=__import__("certifi").where())
    except Exception:
        ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
        s.login(FROM_ADDR, app_password())
        s.send_message(msg, to_addrs=envelope)
    print(f"[owner-showdown] sent '{subject}' to {len(to_list)} on the "
          f"list + {len(bcc)} bcc",
          flush=True)


def build(sales_rows: List[Tuple[int, str, object]],
          rep_rows: List[Tuple[int, str, object]],
          run_date: dt.date) -> Dict[str, str]:
    """sales_rows / rep_rows: [(rank, name, value)] already sorted high→low.
    Returns {subject, html, text}."""
    ds = f"{run_date:%b} {run_date.day}"   # e.g. "Aug 2" — no %-d (Windows-safe)
    subject = f"🏆 August Owner Showdown — standings ({ds})"

    html = (
        f"<div style='font-family:Arial,sans-serif;max-width:560px'>"
        f"<h2 style='margin:0 0 2px'>🏆 August Owner Showdown</h2>"
        f"<div style='color:#666;margin-bottom:16px'>Standings as of {ds} · "
        f"$5,000 to each winner</div>"
        f"<img src='cid:flyer' style='width:100%;max-width:560px;border-radius:12px;"
        f"margin-bottom:8px'>"
        # NO link to the KTS sheet (Megan 2026-08-03). This email goes to 48
        # outside owners — the flyer is the deliverable; the working sheet is
        # not for them. Do NOT reinstate SHEET_URL in anything that goes to
        # the group.
        f"</div>")

    def _txt(rows):
        # rep rows are 4-tuples (rank, name, delta, headcount); sales are 3.
        out = []
        for row in rows:
            if len(row) == 4:
                r, n, v, heads = row
                sign = f"+{v}" if isinstance(v, int) and v >= 0 else str(v)
                out.append(f"  {r}. {n} — {heads} heads ({sign} since Aug 2)")
            else:
                r, n, v = row
                out.append(f"  {r}. {n} — {v}")
        return "\n".join(out)
    text = (f"August Owner Showdown — standings as of {ds}\n\n"
            f"PERSONAL SALES (new-internet, MTD):\n{_txt(sales_rows)}\n\n"
            f"REP COUNT GROWTH (vs Aug 2):\n{_txt(rep_rows)}\n")
    return {"subject": subject, "html": html, "text": text}
