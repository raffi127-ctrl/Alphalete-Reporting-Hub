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
from automations.pay_structure import catalog, icd_payout, offices, store  # noqa: E402
from automations.pay_structure.estimate import estimate_by_level  # noqa: E402

st.set_page_config(page_title="Pay Structure", page_icon="💵", layout="wide")

_SALE_COL = "Sale type"
_ICD_COL = "ICD gets"


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
    st.caption("Enter the access code for your office.")
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
def _gross_profit_simulator(office, campaigns=None) -> None:
    """Gross-profit calculator (Raf 7/26). Lists the office's AT&T Fiber products
    straight from the DD (NOT the order log) — energy + bonuses excluded — and for
    each shows, per unit: gross revenue, what you pay the rep ($ or %), the % that
    is of gross, the gross profit $ (after 12% payroll tax), and the gross profit %
    the office keeps. A manual # sales projects the total (× activation)."""
    from automations.pay_structure import gross_profit as gp
    st.divider()
    st.markdown("### 📊 Gross profit calculator")
    try:
        gr = store.load_gross_revenue(office.key) or {}
    except Exception:                    # noqa: BLE001
        gr = {}
    try:
        weeks = store.load_weekly(office.key) or {}
    except Exception:                    # noqa: BLE001
        weeks = {}

    def _pull_fiber(mapping):
        """{DD 'CAT | Desc': payout} -> {Description: payout}, dropping energy."""
        out = {}
        for key, payout in (mapping or {}).items():
            cat, _, desc = str(key).partition(" | ")
            if cat.strip().upper() == "ELE" or not desc:
                continue
            try:
                out[desc] = float(payout)
            except (TypeError, ValueError):
                continue
        return out

    # Raf's DD-week dropdown: pick a DD week ending → that week's sale types (they
    # accumulate from each pull). Fall back to the office's all-time DD products
    # until weekly data exists.
    import datetime as _dt

    def _wk_key(w):
        for f in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
            try:
                return _dt.datetime.strptime(w, f)
            except ValueError:
                continue
        return _dt.datetime.min

    week_opts = sorted(weeks.keys(), key=_wk_key, reverse=True)
    if week_opts:
        wk = st.selectbox("DD week ending (AT&T Residential)", week_opts, index=0,
                          key=f"gp_wk_{office.key}")
        fiber = _pull_fiber(weeks.get(wk))
        src_note = "DD week ending **{}**".format(wk)
    else:
        fiber = _pull_fiber(gr.get("raw"))
        src_note = "your DD (last pulled {})".format(gr.get("pulled", "—"))

    act_default = int(round((gr.get("activation") or 0.80) * 100))   # Raf: default 80%
    ctop = st.columns([2, 2])
    pct = ctop[0].radio("How do you pay the rep?",
                        ["$ per sale", "% of gross revenue"], horizontal=True,
                        key=f"gp_method_{office.key}") == "% of gross revenue"
    activation = ctop[1].slider("Office activation rate (%)", 50, 100, act_default,
                                key=f"gp_act_{office.key}") / 100.0
    if not fiber:
        st.caption("No AT&T Fiber DD products for your office yet — this fills in "
                   "after the next DD pull.")
        return
    st.caption("Your AT&T Fiber sale types from {} — **gross revenue** is what "
               "SCI/AT&T pays your office per activated sale (edit freely). Enter "
               "**# sales** to project the total.".format(src_note))

    tax = gp.PAYROLL_TAX
    ss = st.session_state.setdefault("gpsim_" + office.key, {})   # scratch inputs
    _PAY = "You pay rep ({})".format("%" if pct else "$")
    _TIER = "Tier bonus ($/sale)"
    data = []
    for name in sorted(fiber):
        cur = ss.get(name, {})
        gross = float(cur.get("gross", fiber[name]))
        pay = float(cur.get("pay", 50.0 if pct else float(round(gross * 0.35))))
        tier = float(cur.get("tier", 0.0))
        sales = int(cur.get("sales", 0))
        rep_d = (gross * pay / 100.0 if pct else pay) + tier   # base pay + volume tier bonus
        prof = gross - rep_d - tax * rep_d
        data.append({
            "Product": name,
            "Gross revenue": gross,
            _PAY: pay,
            _TIER: tier,
            "% payout to rep": "{}%".format(round(rep_d / gross * 100)) if gross else "—",
            "Gross profit $": "${:,.0f}".format(prof),
            "Gross profit % (office keeps)": "{}%".format(round(prof / gross * 100)) if gross else "—",
            "# sales": sales,
        })
    cols = ["Product", "Gross revenue", _PAY, _TIER, "% payout to rep", "Gross profit $",
            "Gross profit % (office keeps)", "# sales"]
    df = pd.DataFrame(data, columns=cols)
    cfg = {
        "Product": st.column_config.TextColumn("Product", width="medium", disabled=True),
        "Gross revenue": st.column_config.NumberColumn(
            "Gross revenue", min_value=0.0, step=5.0, format="$%.0f",
            help="What SCI/AT&T pays your office per activated sale"),
        _PAY: st.column_config.NumberColumn(
            _PAY, min_value=0.0, step=(1.0 if pct else 5.0),
            format=("%.0f%%" if pct else "$%.0f")),
        _TIER: st.column_config.NumberColumn(
            _TIER, min_value=0.0, step=5.0, format="$%.0f", width="small",
            help="Extra $/sale you pay the rep as a VOLUME tier bonus (your lever to "
                 "drive sales) — comes out of gross profit"),
        "% payout to rep": st.column_config.TextColumn("% payout to rep", width="small",
                                                       disabled=True),
        "Gross profit $": st.column_config.TextColumn("Gross profit $", width="small",
                                                      disabled=True),
        "Gross profit % (office keeps)": st.column_config.TextColumn(
            "Gross profit % (office keeps)", disabled=True),
        "# sales": st.column_config.NumberColumn("# sales", min_value=0, step=10,
                                                 format="%d", help="Project a volume"),
    }
    edited = st.data_editor(df, width="stretch", column_config=cfg, hide_index=True,
                            key=f"gpsim_ed_{office.key}")
    for _, r in edited.iterrows():            # persist edits so the auto columns recompute
        ss[str(r["Product"])] = {"gross": float(r["Gross revenue"] or 0),
                                 "pay": float(r[_PAY] or 0),
                                 "tier": float(r[_TIER] or 0),
                                 "sales": int(r["# sales"] or 0)}

    # OVERALL total across products (activation applied to # sales)
    t_rev = t_prof = 0.0
    for v in ss.values():
        g = v["gross"]
        rep_d = (g * v["pay"] / 100.0 if pct else v["pay"]) + v.get("tier", 0.0)
        activated = v["sales"] * activation
        t_rev += g * activated
        t_prof += (g - rep_d - tax * rep_d) * activated
    if t_rev:
        m = st.columns(3)
        m[0].metric("Total gross profit", "${:,.0f}".format(t_prof))
        m[1].metric("Gross profit % (office keeps)", "{:.0f}%".format(t_prof / t_rev * 100))
        m[2].metric("Total gross revenue", "${:,.0f}".format(t_rev))
        st.caption("Total at your # sales × {:.0f}% activation. Per-product columns "
                   "are per unit.".format(activation * 100))


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
            f"letter-spacing:.01em;margin-bottom:1px'>{display_name}</div>"
            f"<div style='font-size:1.02rem;color:#6B7280;font-weight:600;"
            f"margin-bottom:5px'>{office.owner}</div>"
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
    st.caption("Check the campaigns your office sells.")
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
        st.caption("Each row shows the **ICD payout** (what the company pays your "
                   "office per sale). Enter what a rep earns per ACTIVE line at each "
                   "level — the **keeps** column beside it shows what your office "
                   "keeps ($ · %). Fill every level so the estimate stays accurate.")

    # Accurate ICD payout per sale type, from the DD gross-revenue pull (office's
    # own auto-pay base, org-wide fallback). One Sheet read for the whole editor.
    try:
        pay_map = icd_payout.payouts_for_office(office.key, cat)
    except Exception:      # noqa: BLE001 — never let the payout lookup break pricing
        pay_map = {}

    new_rates = {}
    for ck in checked:
        camp = cat.get(ck)
        if camp is None:
            continue
        st.markdown(f"<div style='font-size:1.15rem;font-weight:700;"
                    f"color:{accent};margin-top:8px'>{camp.label}</div>",
                    unsafe_allow_html=True)
        pf = pay_map.get(ck, {})
        types = _campaign_types(grid, ck, camp)
        # Only list products that have a real DD payout (or that this office has
        # already priced) — hides catalog leftovers with no payout (unsold speeds,
        # Voice, …). Skip the filter if we have no payout data yet (don't blank the
        # table). A hidden product reappears automatically once the DD prices it.
        if pf:
            types = [t for t in types
                     if pf.get(t) or any(grid.rate(ck, t, lvl) for lvl in grid.levels)]
        # ONE combined table (wide layout gives the room): Sale type + ICD payout,
        # then each editable Level column immediately followed by its own "keeps"
        # column ($ · %). Keep columns recompute each rerun from the session-
        # persisted rates, so they update right after a pay cell is committed.
        _KEEP = {lvl: "{} keeps".format(lvl) for lvl in grid.levels}
        data = []
        for st_ in types:
            pay = pf.get(st_)
            row = {_SALE_COL: st_,
                   "ICD payout": "${:,.0f}".format(pay) if pay else "—"}
            for lvl in grid.levels:
                rep = grid.rate(ck, st_, lvl)
                row[lvl] = rep
                row[_KEEP[lvl]] = ("${:,.0f} ({}%)".format(pay - rep,
                                   round((pay - rep) / pay * 100)) if pay else "—")
            data.append(row)
        cols = [_SALE_COL, "ICD payout"]
        for lvl in grid.levels:               # Level 1, its keeps, Level 2, its keeps, …
            cols += [lvl, _KEEP[lvl]]
        df = pd.DataFrame(data, columns=cols)
        col_cfg = {
            _SALE_COL: st.column_config.TextColumn(_SALE_COL, width="medium",
                                                   disabled=True),
            "ICD payout": st.column_config.TextColumn(
                "ICD payout", width="small", disabled=True,
                help="What the company pays your office per sale"),
        }
        for lvl in grid.levels:
            col_cfg[lvl] = st.column_config.NumberColumn(lvl, min_value=0.0,
                                                         step=1.0, format="$%.0f",
                                                         width="small",
                                                         help="What you pay the rep")
            col_cfg[_KEEP[lvl]] = st.column_config.TextColumn(
                "{} keeps".format(lvl), width="small", disabled=True,
                help="What your office keeps at this level ($ and %)")
        edited = st.data_editor(df, width="stretch", column_config=col_cfg,
                                hide_index=True, key=f"rates_{office.key}_{ck}")
        bucket = {}
        for _, row in edited.iterrows():
            st_ = str(row.get(_SALE_COL, "") or "").strip()
            if st_:
                bucket[st_] = {lvl: float(row.get(lvl) or 0.0)
                               for lvl in grid.levels}
        new_rates[ck] = bucket
        if not pf:
            st.caption("💵 ICD payout + keep columns fill in once this campaign's "
                       "products have DD payout data.")

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

    _gross_profit_simulator(office, checked)


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
# Admin panel (?admin=1) — manage per-office passwords + see who's filled in.
# --------------------------------------------------------------------------
def _admin_gate() -> bool:
    code = st.secrets.get("pay_structure_admin_code") if hasattr(st, "secrets") else None
    try:
        code = st.secrets.get("pay_structure_admin_code")
    except Exception:
        code = None
    if not code:                         # not configured (local dev) — open
        return True
    if st.session_state.get("_admin_ok"):
        return True
    st.markdown("## 🔒 Pay Structure — Admin")
    st.text_input("Admin code", type="password", key="_admincode")
    if st.button("Enter", type="primary"):
        if st.session_state.get("_admincode") == code:
            st.session_state["_admin_ok"] = True
            st.rerun()
        else:
            st.error("Incorrect admin code.")
    return False


def admin_view() -> None:
    if not _admin_gate():
        return
    st.markdown("## 🔒 Pay Structure — Admin")
    st.caption("Manage each office's password and see who has filled in their "
               "pay structure. Onboarding a new office: add it to the registry, "
               "set its website for branding, then set a password here and send "
               "them the link + code.")

    # --- who's filled in ---------------------------------------------------
    st.divider()
    st.subheader("Who's filled in")
    try:
        _structs = store.list_structures()
    except Exception:                    # noqa: BLE001 — never crash the panel
        _structs = []
    done = {r["office"].lower(): r for r in _structs}
    rows = []
    for k in offices.ORDER:
        o = offices.get(k)
        r = done.get(k.lower())
        rows.append({"Office": o.business_name or o.label, "Owner": o.owner,
                     "Filled in?": "✅ " + (r["updated"] or "") if r else "—",
                     "Campaigns": r["campaigns"] if r else ""})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.write("**{}/{}** offices have filled in their pay structure."
             .format(len(done), len(offices.ORDER)))

    # --- passwords ---------------------------------------------------------
    st.divider()
    st.subheader("Access codes (passwords)")
    st.caption("Each office logs in with its code. Edit a code and Save; changes "
               "take effect immediately (no redeploy). Saves to the 'Pay "
               "Structure Codes' tab in the master sheet.")
    try:
        cur = store.load_codes()
    except Exception:                    # noqa: BLE001
        cur = {}
    df = pd.DataFrame([{"Office": offices.get(k).business_name or k,
                        "office_key": k,
                        "Access code": cur.get(k) or offices.access_code(k)}
                       for k in offices.ORDER])
    edited = st.data_editor(
        df, width="stretch", hide_index=True,
        column_config={"Office": st.column_config.TextColumn(disabled=True),
                       "office_key": None,
                       "Access code": st.column_config.TextColumn(required=True)},
        key="_codes_editor")
    _bcols = st.columns([1, 1])
    with _bcols[0]:
        save_codes = st.button("💾 Save codes", type="primary")
    with _bcols[1]:
        pull = st.button("↻ Pull codes from Cloud secrets",
                         help="Overwrite the table + sheet with the "
                              "[pay_structure_codes] in this app's secrets.")

    business = {k: offices.get(k).business_name for k in offices.ORDER}
    if save_codes:
        mapping = {row["office_key"]: str(row["Access code"]).strip()
                   for _, row in edited.iterrows()
                   if str(row.get("Access code", "")).strip()}
        try:
            store.save_codes(mapping, business, list(offices.ORDER))
            offices.set_codes(store.load_codes())
        except Exception as e:           # noqa: BLE001
            st.error("Couldn't save: {}".format(e))
        else:
            st.success("Saved. New codes are live.")
    if pull:
        try:
            sec = dict(st.secrets.get("pay_structure_codes", {}))
        except Exception:
            sec = {}
        sec = {k: str(v).strip() for k, v in sec.items() if str(v).strip()}
        if not sec:
            st.info("No [pay_structure_codes] found in this app's secrets.")
        else:
            try:
                store.save_codes(sec, business, list(offices.ORDER))
                offices.set_codes(store.load_codes())
            except Exception as e:       # noqa: BLE001
                st.error("Couldn't save: {}".format(e))
            else:
                st.success("Pulled {} codes from secrets into the sheet — "
                           "they're live now.".format(len(sec)))
                st.rerun()


# --------------------------------------------------------------------------
_inject_gs_client()
try:
    offices.set_codes(store.load_codes())     # sheet-managed codes win
except Exception:
    pass

if st.query_params.get("admin"):
    admin_view()
else:
    _office = _login()
    if _office:
        editor_view(_office)
