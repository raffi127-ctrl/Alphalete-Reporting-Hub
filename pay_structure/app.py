"""Pay Structure — the per-office self-serve editor.

An ICD opens the link, enters the code we sent THEM, and lands directly on
THEIR office's pay structure — nobody else's. They name their leader levels,
check the campaigns they run, and fill in what a rep earns per unit of each
sale type at each level. Save, and the next morning each report shows every rep
what they'd earn at each level from the lines they sold.

If an office never fills this in, the order log shows nothing extra — no error,
no blank block. It only appears once a structure is saved.

Run locally:   .venv/bin/streamlit run pay_structure/app.py
On the web:    deploy this repo to Streamlit Community Cloud with
               pay_structure/app.py as the entry point (see README.md).

Secrets (Streamlit Cloud, or .streamlit/secrets.toml locally):
  [pay_structure_codes]   office_key = "CODE"   # one per office; identifies them
  pay_structure_sheet_id  = "<sheet id>"        # where structures are stored
  [gcp_service_account] / [gcp_oauth]           # Google creds for that Sheet
Without the sheet id + creds it falls back to local JSON (fine for building).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automations.pay_structure import catalog, offices, store  # noqa: E402
from automations.pay_structure.estimate import estimate_by_level  # noqa: E402

st.set_page_config(page_title="Pay Structure", page_icon="💵", layout="centered")

_SALE_COL = "Sale type"


def _brand_css(accent: str) -> None:
    """Recolor the form's primary buttons + section rules to the office's brand
    accent, so the whole page feels like theirs — not a generic tool."""
    st.markdown(f"""
        <style>
        button[kind="primary"], [data-testid="stBaseButton-primary"] {{
            background-color: {accent} !important;
            border-color: {accent} !important;
        }}
        h3 {{
            position: relative !important;
            padding-left: 34px !important;
            border-left: none !important;
        }}
        h3::before {{
            content: ""; position: absolute; left: 0; top: 50%;
            transform: translateY(-50%);
            height: 1.05em; width: 5px; border-radius: 3px;
            background: {accent};
        }}
        [data-testid="stCheckbox"] svg {{ color: {accent}; }}
        </style>""", unsafe_allow_html=True)


def _process_logo(raw: bytes) -> str:
    """Resize an uploaded logo to a small thumbnail and return a base64 data URI
    (kept well under Google Sheets' 50k-char cell limit). PNG first; JPEG if the
    PNG is too big."""
    import base64
    import io
    from PIL import Image
    img = Image.open(io.BytesIO(raw))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    img.thumbnail((240, 240))
    for fmt, mime, kw in (("PNG", "image/png", {}),
                          ("JPEG", "image/jpeg", {"quality": 75})):
        buf = io.BytesIO()
        img.save(buf, fmt, **kw)
        b64 = base64.b64encode(buf.getvalue()).decode()
        if len(b64) < 46000:
            return f"data:{mime};base64,{b64}"
    return ""


# --------------------------------------------------------------------------
# Google client (only needed when a Sheet backend is configured).
# --------------------------------------------------------------------------
def _inject_gs_client() -> None:
    try:
        import gspread
    except Exception:
        return
    sa = st.secrets.get("gcp_service_account")
    if sa:
        store.set_client(gspread.service_account_from_dict(dict(sa)))
        return
    o = st.secrets.get("gcp_oauth")
    if not o:
        tok = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"
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
        store.set_client(gspread.authorize(creds))


# --------------------------------------------------------------------------
# Login — the code IS the office identity.
# --------------------------------------------------------------------------
def _login():
    office_key = st.session_state.get("office_key")
    if office_key and office_key in offices.OFFICES:
        return offices.get(office_key)

    st.markdown("## 💵 Pay Structure")
    st.caption("Enter the access code for your office. You'll only ever see your "
               "own office's pay structure.")
    st.text_input("Access code", type="password", key="_code")
    if st.button("Open my pay structure", type="primary"):
        office = offices.office_for_code(st.session_state.get("_code", ""))
        if office:
            st.session_state["office_key"] = office.key
            st.rerun()
        else:
            st.error("That code didn't match an office. Double-check it, or "
                     "reach out for a new one.")
    return None


# --------------------------------------------------------------------------
# Working grid — held in session so edits survive reruns until saved.
# --------------------------------------------------------------------------
def _working_grid(office) -> store.Grid:
    key = f"_grid_{office.key}"
    if key not in st.session_state:
        g = store.load(office.key) or store.blank_grid(office.key)
        # Overlay committed branding (logo/accent ship with the code, so the
        # live link is branded even though pay data comes from the Sheet).
        b = offices.branding(office.key)
        if not g.logo and b.get("logo"):
            g.logo = b["logo"]
        if not g.accent and b.get("accent"):
            g.accent = b["accent"]
        g.normalize()
        st.session_state[key] = g.to_dict()
    return store.Grid.from_dict(st.session_state[key])


def _store_working(office, grid: store.Grid) -> None:
    grid.normalize()
    st.session_state[f"_grid_{office.key}"] = grid.to_dict()


def _campaign_types(grid: store.Grid, ck: str, camp) -> "list":
    """Sale types to show for a campaign: the catalog's list, plus anything the
    office already has priced that isn't in the catalog (never drop a saved row)."""
    seen = {s.lower(): s for s in camp.sale_types}
    for s in grid.sale_types(ck):
        seen.setdefault(s.lower(), s)
    # catalog order first, then any extras
    ordered = list(camp.sale_types)
    extras = [grid.sale_types(ck)[i] for i, s in enumerate(grid.sale_types(ck))
              if s.lower() not in {t.lower() for t in camp.sale_types}]
    return ordered + extras


# --------------------------------------------------------------------------
# The editor
# --------------------------------------------------------------------------
def editor_view(office) -> None:
    grid = _working_grid(office)
    display_name = grid.office_name or office.business_name or office.label

    accent = grid.accent or "#334155"        # neutral slate until we have their brand color
    _brand_css(accent)

    head = st.columns([3, 1])
    with head[0]:
        logo_html = (f"<img src='{grid.logo}' style='height:64px;max-width:240px;"
                     f"object-fit:contain;display:block;margin-bottom:10px'/>"
                     if grid.logo else "💵 ")
        st.markdown(
            logo_html
            + f"<div style='font-size:1.35rem;color:#4B5563;font-weight:700;"
            f"letter-spacing:.01em;margin-bottom:2px'>{display_name}</div>"
            f"<div style='font-size:2.3rem;font-weight:800;color:{accent};"
            f"line-height:1.05'>Pay Structure</div>",
            unsafe_allow_html=True)
    with head[1]:
        if st.button("Log out"):
            for k in list(st.session_state):
                if k == "office_key" or k.startswith("_grid_"):
                    del st.session_state[k]
            st.rerun()

    st.write("Set what a rep earns per unit of each sale type, at each leader "
             "level. Reps see these estimates on their own tab of the daily "
             "order log — including what the next level up would pay.")

    grid.office_name = st.text_input(
        "Office / business name", value=display_name,
        help="What your office is called — shown to your reps on the order log.")

    # --- Step 1: levels ----------------------------------------------------
    st.divider()
    st.markdown("### 1. Your leader levels")
    st.caption("One per line, lowest first. Rename to match what your office "
               "calls them (e.g. Rep, Level 1, Level 2, Manager).")
    levels_text = st.text_area("Levels", value="\n".join(grid.levels), height=110,
                               label_visibility="collapsed",
                               key=f"levels_{office.key}")
    new_levels = [ln.strip() for ln in levels_text.splitlines() if ln.strip()]
    if st.button("Apply levels"):
        if not new_levels:
            st.error("Add at least one level.")
        elif len(new_levels) != len({l.lower() for l in new_levels}):
            st.error("Two levels have the same name — make each unique.")
        else:
            grid.levels = new_levels
            grid.normalize()
            _store_working(office, grid)
            st.rerun()

    # --- Step 2: campaigns you run ----------------------------------------
    st.divider()
    st.markdown("### 2. Which campaigns do you run?")
    st.caption("Check the campaigns your office sells. Only those show up below "
               "to price — you won't scroll past products you don't sell.")
    cat = catalog.campaigns()
    checked = []
    cols = st.columns(2)
    for i, (ck, camp) in enumerate(cat.items()):
        with cols[i % 2]:
            if st.checkbox(camp.label, value=(ck in grid.campaigns),
                           key=f"camp_{office.key}_{ck}"):
                checked.append(ck)
    st.markdown("<div style='margin-top:8px;font-style:italic;color:#6B7280'>"
                "Don't see a campaign you run? Send a Slack message to "
                "<b>Eve &amp; Megan</b> to have it added.</div>",
                unsafe_allow_html=True)

    # --- Step 3: price each sale type in each checked campaign -------------
    st.divider()
    st.markdown("### 3. Pay per unit")
    if not checked:
        st.info("Check at least one campaign above to start pricing.")
    else:
        st.caption("Dollars a rep earns for each ACTIVE line of that sale type. "
                   "Fill in every cell — even if the pay doesn't change by level, "
                   "enter it at each level so the estimate stays accurate.")

    new_rates = {}
    for ck in checked:
        camp = cat.get(ck)
        if camp is None:
            continue
        st.markdown(f"<div style='font-size:1.15rem;font-weight:700;"
                    f"color:{accent};margin-top:8px'>{camp.label}</div>",
                    unsafe_allow_html=True)
        types = _campaign_types(grid, ck, camp)
        df = pd.DataFrame(
            [[st_] + [grid.rate(ck, st_, lvl) for lvl in grid.levels]
             for st_ in types],
            columns=[_SALE_COL] + list(grid.levels))
        col_cfg = {_SALE_COL: st.column_config.TextColumn(_SALE_COL,
                                                          width="large",
                                                          disabled=True)}
        for lvl in grid.levels:
            col_cfg[lvl] = st.column_config.NumberColumn(lvl, min_value=0.0,
                                                         step=1.0, format="$%.2f")
        edited = st.data_editor(df, width="stretch", column_config=col_cfg,
                                hide_index=True, key=f"rates_{office.key}_{ck}")
        bucket = {}
        for _, row in edited.iterrows():
            st_ = str(row.get(_SALE_COL, "") or "").strip()
            if st_:
                bucket[st_] = {lvl: float(row.get(lvl) or 0.0)
                               for lvl in grid.levels}
        new_rates[ck] = bucket

    # Fold this run's edits into the working grid so nothing is lost on rerun.
    # Carry logo + accent forward (they're branding, not edited here) or the page
    # would revert to the default color after the first interaction.
    updated = store.Grid(office_key=office.key, levels=list(grid.levels),
                         campaigns=list(checked), rates=new_rates,
                         office_name=grid.office_name.strip(),
                         logo=grid.logo, accent=grid.accent,
                         updated_at=grid.updated_at)
    _store_working(office, updated)

    # --- Save --------------------------------------------------------------
    st.divider()
    if updated.updated_at:
        st.caption(f"Last saved {updated.updated_at}")
    if st.button("💾 Save pay structure", type="primary"):
        updated.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        try:
            store.save(updated)
        except Exception as e:               # noqa: BLE001
            st.error(f"Couldn't save: {e}")
        else:
            _store_working(office, updated)
            st.success("Saved. Reps will see the updated estimates on the next "
                       "morning's order log.")

    with st.expander("How reps see this"):
        _preview(updated, checked, cat)


def _preview(grid: store.Grid, checked, cat) -> None:
    if grid.is_empty() or not checked:
        st.caption("Pick campaigns and fill in some rates to see an example.")
        return
    ck = checked[0]
    counts = {st_: 1 for st_ in grid.sale_types(ck)}
    by_level, _ = estimate_by_level(ck, counts, grid)
    label = cat.get(ck).label if cat.get(ck) else ck
    st.caption(f"If a rep sold one active line of every {label} sale type, "
               f"their tab would show:")
    st.table(pd.DataFrame([{"Level": lvl, "Estimated pay": f"${amt:,.2f}"}
                           for lvl, amt in by_level.items()]))


# --------------------------------------------------------------------------
_inject_gs_client()
_office = _login()
if _office:
    editor_view(_office)
