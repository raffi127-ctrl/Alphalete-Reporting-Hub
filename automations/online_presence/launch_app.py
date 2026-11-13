"""Launch Studio: launch an office live, on the install call (Megan
2026-11-12: "this can be a live interactive launch so no need for slack").

    .venv/bin/streamlit run automations/online_presence/launch_app.py

Runs on Megan's Mac (or Lucy 3): it needs the Cloudflare key and the browser
the logos are drawn with, so it is NOT the public sign-up page. Top to bottom:

  1. company name (+ Alphalete org -> shield logos) and the basics
  2. 6 logo options -> click one; the site takes its colors + look
  3. their story, links and apply link
  4. drop in 10-15 photos
  5. preview the real site (a hidden link to show them on the call)
  6. domain bought in Cloudflare? -> Go live (domain + www + https)
  7. paste Google Workspace's code -> company email records

Nothing is bought here and no accounts are made: buying the domain and making
the Workspace inbox stay with a person. Every step can be redone.
"""
from __future__ import annotations

import io
import json
import sys
from dataclasses import replace
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from automations.online_presence import (launch as L, logo_maker as LM, offices,  # noqa: E402
                                         signup, site_builder as SB, site_deploy as D)

st.set_page_config(page_title="Launch Studio", page_icon="🚀", layout="wide")
st.title("🚀 Launch Studio")
st.caption("Launch an office's logo, website and company email, live on the call.")


def _site_json(p) -> dict:
    return SB.extras(p)


def _write_site_json(p, x: dict) -> None:
    f = p.path("site.json")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(x, indent=1))


# ---- 1. company name + basics ------------------------------------------------
st.header("1 · The company")
rows = offices.load()
choice = st.selectbox("Office", ["New office"] + sorted(rows), format_func=lambda k: k if k == "New office"
                      else f"{rows[k].business_name} ({k})")
base = rows.get(choice)
c1, c2 = st.columns(2)
name = c1.text_input("Company name (exactly as it should read)", value=base.business_name if base else "")
org = c2.checkbox("In the Alphalete org (shield logos)", value=True)
address = c1.text_input("Office address", value=base.address if base else "",
                        placeholder="100 Main St, Suite 200, Dallas, TX 75201")
phone = c2.text_input("Company phone", value=base.phone if base else "")
camp_label = c1.selectbox("What they sell", list(signup.CAMPAIGNS),
                          index=list(signup.CAMPAIGNS.values()).index(base.campaign)
                          if base and base.campaign in signup.CAMPAIGNS.values() else 0)
google_link = c2.text_input("Google listing link (if they have one)", value=base.google_link if base else "")

if st.button("Save the company", type="primary", disabled=not name.strip()):
    key = base.key if base else LM.slug(name).replace("-", "")[:20]
    p = replace(base, business_name=name.strip(), address=address.strip(), phone=signup.tidy({"Phone": phone})["Phone"],
                google_link=google_link.strip(), campaign=signup.CAMPAIGNS[camp_label]) if base else \
        offices.Presence(key=key, business_name=name.strip(), slack_channel="", address=address.strip(),
                         phone=signup.tidy({"Phone": phone})["Phone"], google_link=google_link.strip(),
                         campaign=signup.CAMPAIGNS[camp_label])
    offices.save(p)
    st.session_state["key"] = p.key
    st.success(f"Saved {p.business_name} as office **{p.key}** (dry, nothing posts until it's switched on).")
    st.rerun()

key = st.session_state.get("key") or (base.key if base else None)
if not key:
    st.stop()
p = offices.load()[key]

# ---- 2. logo -------------------------------------------------------------------
st.header("2 · Pick a logo")
opts_dir = p.path("logo_options")
own_tab, make_tab = st.tabs(["They have a logo", "Make them one"])
with own_tab:
    from automations.online_presence import logo_upload as LU
    upl = st.file_uploader("Upload their logo (PNG, JPG or SVG; the original file is best)",
                           type=["png", "jpg", "jpeg", "svg", "webp", "heic"], key="own_logo")
    if upl:
        v = LU.check(upl.getvalue(), upl.name)
        {"GOOD": st.success, "WEB": st.warning, "REDO": st.error}[v["verdict"]](
            {"GOOD": "✅ Good to use. ", "WEB": "⚠️ OK for the website, not for print. ",
             "REDO": "❌ Not good enough. "}[v["verdict"]] + " ".join(v["why"]))
        if v["verdict"] in ("GOOD", "WEB") and st.button("Use their logo (make every format)", type="primary"):
            import shutil
            brand = p.path("brand")
            if brand.exists():
                shutil.rmtree(brand)
            LU.make_files(upl.getvalue(), upl.name, brand)
            x0 = _site_json(p)
            x0.update({"logo": str(brand / "icon.png"), "logo_full": str(brand / "logo.png"),
                       "colors": {**(x0.get("colors") or {}), "accent": LU.main_color(brand / "logo.png")}})
            _write_site_json(p, x0)
            stt = L._state(p)
            stt["logo"] = "own"
            L._save_state(p, stt)
            st.rerun()
with make_tab:
    ideas = st.text_area("Their ideas (optional)", placeholder="e.g. red fire and a wolf · a crown · mountains, navy and gold",
                         help="Lucy draws 3 logos from this, plus 3 from our shield set.")
    if st.button("Make logo options" if not (opts_dir / "options.png").exists() else "Make new logo options"):
        with st.spinner("Drawing 6 logos… (about a minute)"):
            L.make_logos(p, shields=org, ideas=ideas)
        st.rerun()
if L._state(p).get("logo") == "own":
    brand = p.path("brand")
    st.success("Using their own logo. Files: " + ", ".join(sorted(f.name for f in brand.iterdir())))
    st.image(str(brand / "logo.png"), width=360)
    for f in sorted(brand.iterdir()):
        st.download_button(f"⬇ {f.name}", f.read_bytes(), file_name=f"{p.key}-{f.name}", key=f"dlo{f.name}")
elif (opts_dir / "options.png").exists():
    sj_ = opts_dir / "styles.json"
    styles = json.loads(sj_.read_text()) if sj_.exists() else LM.styles_for(L._state(p).get("logo_shields", org))
    picked = L._state(p).get("logo")
    cols = st.columns(3)
    for n, stl in enumerate(styles, 1):
        with cols[(n - 1) % 3]:
            st.image(str(opts_dir / f"option-{n}" / "logo.png"), width="stretch")
            st.caption(f"{n} · {stl['label']}")
            if st.button("✅ Picked" if picked == n else f"Pick {n}", key=f"pick{n}", disabled=picked == n):
                L.pick_logo(p, n)
                st.rerun()
    if picked:
        brand = p.path("brand")
        st.success(f"Logo {picked} kept. Files: " + ", ".join(sorted(f.name for f in brand.iterdir())))
        for f in sorted(brand.iterdir()):
            st.download_button(f"⬇ {f.name}", f.read_bytes(), file_name=f"{p.key}-{f.name}", key=f"dl{f.name}")

# ---- 3. story + links ----------------------------------------------------------
st.header("3 · Their story and links")
x = _site_json(p)
ans = x.get("answers") or {}
c1, c2 = st.columns(2)
started = c1.text_area("How did the office start?", value=ans.get("started", ""))
different = c2.text_area("What makes the team different?", value=ans.get("different", ""))
culture = c1.text_area("What's the culture like?", value=ans.get("culture", ""))
areas = c2.text_input("Cities they work in", value=", ".join(x.get("areas") or []))
apply_url = c2.text_input("Job application link (optional)", value=x.get("apply_url", ""))
links = {}
lc = st.columns(5)
for i, (field, hosts, page) in enumerate([f for f in signup.SOCIAL_FIELDS if f[2] != "YouTube"]):
    links[page.lower()] = lc[i].text_input(page, value=getattr(p, f"{page.lower()}_url", ""))
if st.button("Save story + links"):
    x["answers"] = {k: v.strip() for k, v in (("started", started), ("different", different),
                                              ("culture", culture)) if v.strip()}
    x["areas"] = [a.strip() for a in areas.split(",") if a.strip()]
    x["apply_url"] = apply_url.strip()
    _write_site_json(p, x)
    fixed = signup.tidy({f"{k.title() if k != 'x' else 'X'} Link": v for k, v in links.items()})
    offices.save(replace(p, **{f"{k}_url": fixed.get(f"{k.title() if k != 'x' else 'X'} Link", "")
                               for k in links}))
    st.success("Saved.")
    st.rerun()

# ---- 4. photos -----------------------------------------------------------------
st.header("4 · Launch photos (10–15)")
have = [ph for ph in (x.get("photos") or []) if Path(ph).exists()]
st.write(f"**{len(have)}** saved." + ("" if len(have) >= 10 else " Aim for 10–15: team, office, wins, team nights."))
if have:
    st.image(have[:15], width=140)
up = st.file_uploader("Drop photos here", type=["jpg", "jpeg", "png", "heic", "webp"], accept_multiple_files=True)
if up and st.button(f"Save {len(up)} photo(s)"):
    from PIL import Image, ImageOps
    from automations.brand_audit import photo_edit  # noqa: F401  (registers iPhone HEIC)
    folder = p.path("site_photos")
    folder.mkdir(parents=True, exist_ok=True)
    for f in up:
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(f.getvalue()))).convert("RGB")
        im.thumbnail((2000, 2000))
        dest = folder / f"{Path(f.name).stem}.jpg"
        im.save(dest, "JPEG", quality=88)
        if str(dest) not in have:
            have.append(str(dest))
    x["photos"] = have
    _write_site_json(p, x)
    st.rerun()

# ---- 5. preview ------------------------------------------------------------------
st.header("5 · Preview the site")
project = f"{p.key}-site".replace("_", "-").lower()
looks = list(SB.THEMES)
cur = SB.pick_theme(p, SB.extras(p))
c1, c2 = st.columns([1, 2])
look = c1.selectbox("Site layout (10 to pick from)", looks, index=looks.index(cur),
                    format_func=lambda k: f"{SB.THEMES[k]['label']} · {'dark' if SB.THEMES[k]['dark'] else 'light'}, "
                                          f"{SB.THEMES[k]['hero']} photo")
with c2.expander("✏️ Change the words"):
    from automations.online_presence import site_copy as SC
    xx = SB.extras(p)
    try:
        written = json.loads(p.path("site_copy.json").read_text())["copy"]
    except Exception:
        written = {}
    edits = dict(xx.get("copy_edits") or {})
    for k in ("hero_h1", "hero_sub", "what_title", "what_body", "why_title", "why_body",
              "about_title", "about_story", "apply_title", "apply_sub"):
        val = edits.get(k) or written.get(k, "")
        new = st.text_area(k.replace("_", " ").title(), value=val, key=f"ed_{k}", height=80)
        if new.strip() and new != written.get(k, ""):
            edits[k] = new
    if st.button("Save my changes"):
        xx["copy_edits"] = edits
        _write_site_json(p, xx)
        st.success("Saved. Build the preview again to see them.")
if look != cur:
    xx = SB.extras(p)
    xx["theme"] = look
    _write_site_json(p, xx)
if st.button("Build the preview"):
    with st.spinner("Writing their words and building the site…"):
        out = SB.build(p, extra={**SB.extras(p), "noindex": True})
        url = D.deploy(out, project)
    st.session_state["preview"] = url
if st.session_state.get("preview"):
    st.markdown(f"Hidden preview (Google can't see it): **{st.session_state['preview']}**")
    st.components.v1.iframe(st.session_state["preview"], height=640, scrolling=True)

# ---- 6. domain + go live -----------------------------------------------------------
st.header("6 · Domain + go live")
domain = st.text_input("Their domain", value=L._state(p).get("live_domain", ""), placeholder="theircompany.com")
if domain:
    try:
        L._zone(domain.strip().lower())
        st.success(f"{domain} is in the Alphalete Cloudflare account.")
        if st.button("🚀 Go live", type="primary"):
            with st.spinner("Putting it live…"):
                r = L.go(p, domain)
            for s_ in r["steps"]:
                st.write("· " + s_)
            st.success(f"Live: {r['url']} (https turns on within a few minutes)")
    except SystemExit:
        st.warning(f"{domain} isn't in the Alphalete Cloudflare account yet. Buy it there "
                   "(Domain Registration → Register Domains), then come back to this step.")

# ---- 7. company email ------------------------------------------------------------------
st.header("7 · Company email")
st.caption("Add the domain to Lucy's Google Workspace, then paste the verification code Google shows.")
code = st.text_input("Google's verification code", placeholder="google-site-verification=…")
if code and domain and st.button("Add the email settings"):
    for s_ in L.google_mail(domain.strip().lower(), code):
        st.write("· " + s_)
    stt = L._state(p)
    stt["google_mail"] = domain.strip().lower()
    L._save_state(p, stt)

with st.sidebar:
    st.subheader(f"{p.business_name}")
    for line in L.status(p):
        st.write(line)
