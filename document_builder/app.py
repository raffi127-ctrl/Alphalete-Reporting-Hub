"""Alphalete Document Builder — public self-serve PDF generator.

Run locally:   .venv/bin/streamlit run document_builder/app.py
On the web:    deploy this repo to Streamlit Community Cloud with
               document_builder/app.py as the entry point (see README.md).

Two views:
  • Builder (default)  — an ICD opens the link, fills the form, downloads a
    branded PDF; a copy is emailed to them + alphaletereporting@, and the
    submission is logged to a Google Sheet.
  • Admin (?admin=1)   — behind a separate admin code: see who has generated
    each document and send them an "update" notice (what changed + regenerate
    link) so they can refresh their copy.

Secrets (Streamlit Cloud dashboard, or .streamlit/secrets.toml locally) turn on
the optional pieces; the app runs without them, just without gate/email/log.
See README.md for the full template.
"""
from __future__ import annotations

import json
import smtplib
import sys
import tempfile
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from document_builder import master  # noqa: E402
from document_builder.registry import (by_label, GENERATORS,  # noqa: E402
                                       SCHED_DEFAULTS, _DAYS)

st.set_page_config(page_title="Alphalete Document Builder", page_icon="🐺",
                   layout="centered")

TEAM_FALLBACK = "alphaletereporting@gmail.com"


# --------------------------------------------------------------------------
# Email + Sheet helpers (all no-ops until their secrets are set)
# --------------------------------------------------------------------------
def _smtp():
    return st.secrets.get("smtp")


def _team() -> str:
    return (_smtp() or {}).get("team", TEAM_FALLBACK)


def _doc_copy() -> str:
    """Who gets a BCC copy of each generated document. Set `doc_copy` under
    [smtp] in secrets; falls back to the team address."""
    return (_smtp() or {}).get("doc_copy") or _team()


def _app_url() -> str:
    return st.secrets.get("app_url", "")


def send_email(to_addrs, subject, body, attachment=None, bcc=None,
               cc=None) -> bool:
    """Send mail. `cc` recipients are visible in headers (so reply-all reaches
    them); `bcc` recipients receive it without appearing in headers."""
    s = _smtp()
    to = [a for a in dict.fromkeys(to_addrs or []) if a and "@" in a]
    cc = [a for a in dict.fromkeys(cc or []) if a and "@" in a and a not in to]
    bcc = [a for a in dict.fromkeys(bcc or [])
           if a and "@" in a and a not in to and a not in cc]
    pw = (s or {}).get("password", "")
    if not s or not (to or cc or bcc) or not pw or pw.startswith("PASTE"):
        return False
    msg = EmailMessage()
    msg["From"] = s.get("from", s["user"])
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment:
        fname, data = attachment
        msg.add_attachment(data, maintype="application", subtype="pdf",
                           filename=fname)
    with smtplib.SMTP(s["host"], int(s.get("port", 587)), timeout=60) as srv:
        srv.starttls()
        srv.login(s["user"], s["password"])
        srv.send_message(msg, to_addrs=to + cc + bcc)
    return True


LOG_HEADER = ["timestamp", "document", "company", "owner", "location",
              "primary", "accent", "email"]


def _gs_client():
    """A gspread client from whatever Google creds are available:
    a service account, an OAuth block in secrets, or (local dev) the Hub's
    OAuth token file."""
    import gspread
    sa = st.secrets.get("gcp_service_account")
    if sa:
        return gspread.service_account_from_dict(dict(sa))
    o = st.secrets.get("gcp_oauth")
    if not o:                                        # local dev fallback
        tok = Path.home() / ".config" / "recruiting-report" / \
            "oauth-token.json"
        if tok.exists():
            import json
            o = json.loads(tok.read_text())
    if o:
        from google.oauth2.credentials import Credentials
        creds = Credentials(
            token=o.get("token"), refresh_token=o.get("refresh_token"),
            token_uri=o.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=o.get("client_id"), client_secret=o.get("client_secret"),
            scopes=list(o.get("scopes") or
                        ["https://www.googleapis.com/auth/spreadsheets"]))
        return gspread.authorize(creds)
    return None


def _sheet():
    """The 'Document Builder Log' tab in the configured Google Sheet
    (created if it doesn't exist yet)."""
    sid = st.secrets.get("log_sheet_id")
    if not sid:
        return None
    gc = _gs_client()
    if not gc:
        return None
    ss = gc.open_by_key(sid)
    tab = st.secrets.get("log_worksheet", "Document Builder Log")
    try:
        return ss.worksheet(tab)
    except Exception:                                # tab not there yet
        ws = ss.add_worksheet(title=tab, rows=2000, cols=len(LOG_HEADER))
        ws.append_row(LOG_HEADER)
        return ws


def log_submission(gen, inputs, email) -> None:
    row = [
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        gen.label, inputs.get("company", ""), inputs.get("owner", ""),
        inputs.get("location", ""), inputs.get("primary", ""),
        inputs.get("accent", ""), email or "",
    ]
    ws = _sheet()
    if ws:                                        # Google Sheet (durable)
        if not ws.get_all_values():
            ws.append_row(LOG_HEADER)
        ws.append_row(row)
        return
    # fallback: local CSV so there's always a record (used until the Sheet
    # secrets are set; ephemeral on Streamlit Cloud, durable when run locally)
    import csv
    p = Path(__file__).resolve().parents[1] / "output" / \
        "document_builder_submissions.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    with open(p, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_HEADER)
        w.writerow(row)


def read_log() -> list:
    ws = _sheet()
    return ws.get_all_values() if ws else []


def load_overrides() -> dict:
    """Admin-edited master content (JSON in cell A1 of the content tab)."""
    gc = _gs_client()
    sid = st.secrets.get("log_sheet_id")
    if not gc or not sid:
        return {}
    try:
        ws = gc.open_by_key(sid).worksheet(master.CONTENT_TAB)
        raw = ws.acell("A1").value
        return json.loads(raw) if raw else {}
    except Exception:                                # noqa: BLE001
        return {}


def save_overrides(data: dict) -> bool:
    gc = _gs_client()
    sid = st.secrets.get("log_sheet_id")
    if not gc or not sid:
        return False
    ss = gc.open_by_key(sid)
    try:
        ws = ss.worksheet(master.CONTENT_TAB)
    except Exception:                                # noqa: BLE001
        ws = ss.add_worksheet(master.CONTENT_TAB, rows=10, cols=2)
    ws.update_acell("A1", json.dumps(data))
    return True


@st.cache_data(ttl=120, show_spinner=False)
def _template_overrides() -> dict:
    """Admin master edits, cached briefly so the builder page doesn't re-read
    the Sheet on every rerun (new admin saves show up within ~2 minutes)."""
    return load_overrides()


def _gate(code_key: str, flag: str, title: str) -> bool:
    """Password gate. Returns True once the right code is entered."""
    code = st.secrets.get(code_key)
    if not code:
        return True
    if st.session_state.get(flag):
        return True
    st.markdown(f"### {title}")
    st.text_input("Access code", type="password", key=f"_{flag}")
    if st.button("Enter", type="primary"):
        if st.session_state.get(f"_{flag}") == code:
            st.session_state[flag] = True
            st.rerun()
        else:
            st.error("Incorrect code.")
    return False


def extract_colors(raw: bytes):
    """Pick two brand-y colors (primary, accent) from a logo's pixels."""
    try:
        import colorsys
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img).convert("RGB")
        img.thumbnail((160, 160))
        q = img.quantize(colors=16)
        pal = q.getpalette()
        cand = []
        for cnt, idx in (q.getcolors() or []):
            r, g, b = pal[idx * 3:idx * 3 + 3]
            h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            if s > 0.15 and 0.10 < l < 0.90:        # skip near-white/black/grey
                cand.append((cnt, (r, g, b), h))
        cand.sort(key=lambda x: -x[0])
        if not cand:
            return None
        hx = lambda rgb: "#%02X%02X%02X" % rgb      # noqa: E731

        def lum(rgb):
            return (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255

        p_rgb = cand[0][1]
        # a genuinely different second color, if the logo has one
        acc = next((c[1] for c in cand[1:]
                    if abs(c[2] - cand[0][2]) > 0.06), None)
        # The accent fills headers/bands with dark text, so it must stay
        # light-ish. If there's no good 2nd color (or it's too dark), use the
        # packet's gold — it complements any single brand color.
        if acc is None or lum(acc) < 0.42:
            hh, ll, _ = colorsys.rgb_to_hls(*[v / 255 for v in p_rgb])
            acc = (120, 92, 48) if (0.08 < hh < 0.17 and ll > 0.45) \
                else (184, 150, 90)     # deep bronze if brand is gold, else gold
        return hx(p_rgb), hx(acc)
    except Exception:                                # noqa: BLE001
        return None


_DAYNAMES = {"MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday",
             "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday",
             "SUN": "Sunday"}


def _schedule_grid(f, inputs):
    """A per-day Office/Field hours grid; blank or 'OFF' marks a day off."""
    st.divider()
    st.markdown(f"**{f.label}**")
    if f.image:
        try:
            st.image(f.image, caption="Example — set your own hours below",
                     width='stretch')
        except Exception:                            # noqa: BLE001
            pass
    if f.help:
        st.caption(f.help)
    head = st.columns([1.1, 2, 2])
    head[1].caption("Office hours")
    head[2].caption("Field hours")
    for d in _DAYS:
        row = st.columns([1.1, 2, 2])
        row[0].markdown(f"**{_DAYNAMES[d]}**")
        inputs[f"office_{d.lower()}"] = row[1].text_input(
            f"office_{d}", value=SCHED_DEFAULTS["office"][d],
            key=f"office_{d}", label_visibility="collapsed")
        inputs[f"field_{d.lower()}"] = row[2].text_input(
            f"field_{d}", value=SCHED_DEFAULTS["field"][d],
            key=f"field_{d}", label_visibility="collapsed")


def _advanced_options(tmpl_over: dict) -> dict:
    """One-off edits that apply to THIS packet only (not the shared master).
    Surfaces every commission chart (pages 9 + 10) as an editable grid. Returns
    a dict of master-block overrides to layer on top of the template for this
    single generation."""
    import pandas as pd
    import re
    per = {}
    base = master.defaults()
    comm = [b for b in master.BLOCKS if b.get("group") == "commission"]
    with st.expander("⚙️ Advanced Options — Commission Structures"):
        for blk in comm:
            cur = tmpl_over.get(blk["id"], base[blk["id"]])
            name = re.sub(r"\s*\(page \d+\)$", "", blk["label"])
            name = name.replace("Commission — ", "")
            st.markdown(f"**{name}**")
            df = pd.DataFrame(cur, columns=blk["columns"])
            ed = st.data_editor(df, num_rows="dynamic", width="stretch",
                                key=f"adv_{blk['id']}")
            rows = [[("" if v is None else str(v)) for v in r]
                    for r in ed.fillna("").values.tolist()]
            if rows != cur:
                per[blk["id"]] = rows
    return per


# --------------------------------------------------------------------------
# Builder view (ICD-facing)
# --------------------------------------------------------------------------
def builder_view():
    if not _gate("access_code", "authed", "🐺 Alphalete Document Builder"):
        return

    st.markdown("## 🐺 Document Builder")
    st.caption("Fill in your details, upload your logo, and download your "
               "branded PDF. A copy is emailed to you automatically.")

    labels = by_label()
    if len(GENERATORS) == 1:
        gen = GENERATORS[0]
        st.markdown(
            f"<span style='color:#9E1B2E;font-size:1.9rem;font-weight:800'>"
            f"{gen.label}</span>"
            f"<span style='color:#1F9D57;font-style:italic;font-size:1rem;"
            f"font-weight:600;margin-left:34px'>"
            f"More buildable documents coming soon!</span>",
            unsafe_allow_html=True)
    else:
        gen = labels[st.selectbox("Which document?", list(labels))]
    st.write(gen.description)
    st.divider()

    email = st.text_input("Admin or ICD email",
                          help="Who the finished PDF will be emailed to — the "
                               "ICD receiving the packet (or yourself).")

    inputs, logo_path = {}, None
    for f in gen.fields:
        lbl = f.label + ("" if f.required else " (optional)")
        if f.kind == "section":
            st.divider()
            st.markdown(f"**{f.label}**")
            if f.image:
                try:
                    st.image(f.image, width='stretch')
                except Exception:                    # noqa: BLE001
                    pass
            if f.help:
                st.caption(f.help)
        elif f.kind == "text":
            inputs[f.key] = st.text_input(lbl, value=f.default,
                                          help=f.help or None)
        elif f.kind == "checkbox":
            inputs[f.key] = st.checkbox(f.label, value=bool(f.default),
                                        help=f.help or None)
        elif f.kind == "select":
            opts = list(f.options)
            idx = opts.index(f.default) if f.default in opts else 0
            inputs[f.key] = st.selectbox(f.label, opts, index=idx,
                                         help=f.help or None)
        elif f.kind == "color":
            inputs[f.key] = st.color_picker(
                f.label, value=st.session_state.get(f.key, f.default or
                                                    "#000000"),
                key=f.key, help=f.help or None)
        elif f.kind == "schedule":
            _schedule_grid(f, inputs)
        elif f.kind == "logo":
            up = st.file_uploader(lbl, type=["png", "jpg", "jpeg", "webp"],
                                  help=f.help or None)
            if up is not None:
                raw = up.getvalue()
                # normalize any upload (incl. WebP) to a PNG reportlab can read
                try:
                    import io
                    from PIL import Image
                    img = Image.open(io.BytesIO(raw))
                    img = (img.convert("RGBA")
                           if img.mode in ("RGBA", "LA", "P")
                           else img.convert("RGB"))
                    tmp = tempfile.NamedTemporaryFile(delete=False,
                                                      suffix=".png")
                    img.save(tmp.name, "PNG")
                    logo_path = tmp.name
                except Exception as e:               # noqa: BLE001
                    st.error(f"Couldn't read that image ({e}). Try a PNG or "
                             f"JPG.")
                # on a NEW logo, auto-pick primary + accent from its colors
                sig = hash(raw)
                if sig != st.session_state.get("_logo_sig"):
                    cols = extract_colors(raw)
                    if cols:
                        st.session_state["primary"] = cols[0]
                        st.session_state["accent"] = cols[1]
                        st.session_state["_autocolor"] = True
                    st.session_state["_logo_sig"] = sig
                if st.session_state.get("_autocolor"):
                    st.caption("🎨 Primary + accent colors auto-picked from "
                               "your logo — adjust them below if needed.")

    st.divider()
    tmpl_over = _template_overrides()                 # shared master edits
    per_office = _advanced_options(tmpl_over)          # this-packet-only edits

    if st.button("Generate PDF", type="primary"):
        missing = [f.label for f in gen.fields
                   if f.required and f.kind == "text" and not inputs.get(f.key)]
        if any(f.kind == "logo" and f.required for f in gen.fields) \
                and not logo_path:
            missing.append("Company logo")
        if not email or "@" not in email:
            missing.append("Admin or ICD email")
        if missing:
            st.error("Please fill in: " + ", ".join(missing))
        else:
            inputs["logo_path"] = logo_path
            # shared master edits, then this-office-only advanced edits on top
            inputs["_overrides"] = {**tmpl_over, **per_office}
            fname = gen.filename(inputs)
            out = Path(tempfile.gettempdir()) / fname
            with st.spinner("Building your document…"):
                try:
                    gen.build(inputs, str(out))
                    data = out.read_bytes()
                except Exception as e:               # noqa: BLE001
                    st.error(f"Something went wrong building the PDF: {e}")
                    data = None
            if data:
                preview = None
                try:
                    import fitz
                    preview = fitz.open(str(out))[0].get_pixmap(
                        matrix=fitz.Matrix(1.3, 1.3)).tobytes("png")
                except Exception:                    # noqa: BLE001
                    pass
                # email + log ONCE, here (not on every rerun)
                try:
                    sent = send_email(
                        [email],
                        subject=f"Your {gen.label} — "
                                f"{inputs.get('company', '')}".strip(),
                        body=f"Attached is your branded {gen.label}.\n\n"
                             f"Want to customize or restyle it yourself? You "
                             f"can turn it into a fully editable Canva design "
                             f"in about a minute:\n"
                             f"  1. Create a free Canva account (or log in): "
                             f"https://www.canva.com/signup\n"
                             f"  2. In Canva click \"Create a design,\" then "
                             f"\"Upload,\" and upload the PDF attached to this "
                             f"email.\n"
                             f"  3. Canva turns it into a fully editable "
                             f"design — change the wording, colors, layout, "
                             f"anything.\n\n— Alphalete Marketing",
                        attachment=(fname, data), cc=[_doc_copy()])
                    email_err = None if sent else (
                        "email isn't configured (missing [smtp] secrets)")
                except Exception as e:               # noqa: BLE001
                    sent = False
                    email_err = f"{type(e).__name__}: {e}"
                try:
                    log_submission(gen, inputs, email)
                except Exception:                    # noqa: BLE001
                    pass
                st.session_state["result"] = {
                    "data": data, "fname": fname, "preview": preview,
                    "emailed": bool(sent), "email": email,
                    "email_err": email_err,
                }

    # render the result (persists across the download-button rerun)
    res = st.session_state.get("result")
    if res:
        st.success("Your document is ready!")
        if res.get("preview"):
            st.image(res["preview"], caption="Page 1 preview")
        st.download_button("⬇️  Download PDF", res["data"],
                           file_name=res["fname"], mime="application/pdf",
                           type="primary")
        if res["emailed"]:
            st.info(f"📧 Emailed to {res['email']} (copy to {_doc_copy()}).")
        elif res.get("email_err"):
            st.warning(f"⚠️ Your PDF is ready to download above, but we "
                       f"couldn't email a copy. Reason: {res['email_err']}")
        st.markdown("---")
        st.markdown(
            "### 🎨 Want to customize or restyle your packet?\n"
            "Turn it into a **fully editable Canva design** in about a "
            "minute:\n\n"
            "1. **Create a free Canva account** (or log in) → "
            "[canva.com/signup](https://www.canva.com/signup)\n"
            "2. Click **Create a design → Upload**, and upload the **PDF you "
            "just downloaded** above.\n"
            "3. Canva converts it into a fully editable design — change the "
            "wording, colors, layout, anything. ✨")


# --------------------------------------------------------------------------
# Admin view (?admin=1) — notify past ICDs of a master update
# --------------------------------------------------------------------------
def admin_view():
    if not _gate("admin_code", "admin_authed", "🔒 Document Builder — Admin"):
        return

    st.markdown("## 🔒 Admin")
    st.caption("See who has generated each document, and notify them when the "
               "master has been updated.")

    rows = read_log()
    if rows and rows[0] and rows[0][0] == "timestamp":
        body_rows = rows[1:]
    else:
        body_rows = rows
    emails = sorted({r[7] for r in body_rows
                     if len(r) > 7 and r[7] and "@" in r[7]})

    st.subheader("Generation log")
    if body_rows:
        import pandas as pd
        ncol = len(LOG_HEADER)
        norm = [(list(r) + [""] * ncol)[:ncol] for r in body_rows]
        heads = ["Generated", "Document", "Company", "ICD Name", "Location",
                 "Primary color", "Accent color", "Email"]
        df = pd.DataFrame(norm, columns=heads)
        st.dataframe(df, width='stretch', hide_index=True)
    else:
        st.info("No submissions logged yet (or Sheet logging isn't configured "
                "in secrets).")
    st.write(f"**{len(emails)}** ICD email(s) on file.")

    st.divider()
    st.subheader("Notify ICDs of an update")
    doc = st.selectbox("Which document was updated?",
                       [g.label for g in GENERATORS])
    only_doc = st.checkbox("Only people who generated this document", value=True)
    # candidate ICDs (optionally filtered to this document); pick who to notify
    by_email = {}
    for r in body_rows:
        if len(r) > 7 and r[7] and "@" in r[7] and (not only_doc or r[1] == doc):
            by_email[r[7]] = r[3] or ""          # latest owner name wins
    cand_emails = sorted(by_email)

    def _fmt(e):
        nm = by_email.get(e)
        return f"{nm} — {e}" if nm else e

    st.markdown("**Who to notify** — everyone's checked; uncheck anyone you "
                "don't want to email.")
    picked = []
    if cand_emails:
        cols = st.columns(2)
        for i, e in enumerate(cand_emails):
            with cols[i % 2]:
                if st.checkbox(_fmt(e), value=True, key=f"notify_{e}"):
                    picked.append(e)
    else:
        st.caption("No ICDs have generated this document yet.")
    note = st.text_area("What changed? (goes in the email)",
                        placeholder="e.g. Updated the commission rate card and "
                                    "added a seasonal recommendations page.")
    st.write(f"Will notify **{len(picked)}** ICD(s) + {_team()}.")
    if st.button("Send update notice", type="primary"):
        if not note.strip():
            st.error("Add a short note describing what changed.")
            return
        if not picked:
            st.error("Pick at least one ICD to notify.")
            return
        link = _app_url()
        body = (f"Heads up — the {doc} has been updated.\n\n"
                f"What changed:\n{note.strip()}\n\n"
                + (f"Want your copy refreshed? Regenerate it here:\n{link}\n\n"
                   if link else "")
                + "— Alphalete Marketing")
        try:
            ok = send_email([_team()], subject=f"Update to your {doc}",
                            body=body, bcc=picked)
        except Exception as e:                       # noqa: BLE001
            st.error(f"Couldn't send: {e}")
            return
        if ok:
            st.success(f"Update notice sent to {len(picked)} ICD(s) + "
                       f"{_team()}.")
        else:
            st.error("Email isn't configured — add the [smtp] secrets first.")

    _master_editor()


def _master_editor():
    """Edit the shared master content; saved edits apply to every new packet."""
    st.divider()
    st.subheader("Edit master content")
    st.caption("Change the shared wording/numbers used in every generated "
               "packet. Edits save to the AUTOMATION MASTER sheet and apply "
               "to all future generations. Branding (name, colors, logo, "
               "schedule, upline) is set per-ICD on the form, not here.")

    overrides = load_overrides()
    base = master.defaults()
    edits = {}

    for b in master.BLOCKS:
        cur = overrides.get(b["id"], base[b["id"]])
        with st.expander(b["label"]):
            kind = b["kind"]
            if kind == "paragraphs":
                txt = st.text_area("One paragraph per block (blank line "
                                   "between)", value="\n\n".join(cur),
                                   height=220, key=f"ed_{b['id']}")
                edits[b["id"]] = [p.strip() for p in txt.split("\n\n")
                                  if p.strip()]
            elif kind == "lines":
                txt = st.text_area("One item per line",
                                   value="\n".join(cur), height=180,
                                   key=f"ed_{b['id']}")
                edits[b["id"]] = [ln.strip() for ln in txt.splitlines()
                                  if ln.strip()]
            elif kind == "steps":
                rows = []
                for i, (title, bullets) in enumerate(cur):
                    t = st.text_input("Step", value=title,
                                      key=f"ed_{b['id']}_t{i}")
                    bl = st.text_area("Bullets (indent a line with 2 spaces "
                                      "to make it a sub-bullet)", value=bullets,
                                      height=130, key=f"ed_{b['id']}_b{i}")
                    rows.append([t, bl])
                edits[b["id"]] = rows
            else:                                    # table
                import pandas as pd
                df = pd.DataFrame(cur, columns=b["columns"])
                ed = st.data_editor(df, num_rows="dynamic", width="stretch",
                                    key=f"ed_{b['id']}")
                edits[b["id"]] = [[("" if v is None else str(v)) for v in r]
                                  for r in ed.fillna("").values.tolist()]

    if st.button("Save master content", type="primary"):
        # store only blocks that differ from the base, so future base updates
        # still flow through for untouched blocks
        new_over = {k: v for k, v in edits.items() if v != base[k]}
        if save_overrides(new_over):
            st.success(f"Saved. {len(new_over)} block(s) overridden; applies "
                       f"to new packets from now on.")
        else:
            st.error("Couldn't save — the Sheet/creds aren't configured.")


# --------------------------------------------------------------------------
if st.query_params.get("admin"):
    admin_view()
else:
    builder_view()
