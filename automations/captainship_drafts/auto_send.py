"""Captainship Reports se mandan SOLOS — después de revisarlos como los revisa Eve.

Eve 2026-10-05: "a partir de mañana quiero que los captainship reports se envíen
solos sin gate", con tres condiciones:

  1. que no salga un reporte con una sección faltante (ese día a Tony no le
     salía el screenshot de Fiber Activations);
  2. que no salga si los trackers de Tableau están sin actualizar (la alerta de
     Megan "Country Trackers — board(s) held for stale"): si los trackers están
     viejos, los reportes de capitanes probablemente también;
  3. que lo que "carga bien" se mire de verdad, como ella lo mira con el gate:
     la columna del día más reciente, el formato de los números, la fuente, el
     estilo (ese mismo día la caja de Luke venía mal).

Y la regla de qué hacer con cada cosa: lo que se arregla re-corriendo, se
re-corre (y el link de revisión queda igual, ya re-sellado); lo que no depende
de nosotros (Tableau atrasado, una falla que sigue después de re-armar) frena a
ESE capitán y avisa — en el hilo de #revision-emails y en UN hilo diario de
#claudecorrections-and-requests, aunque fallen varios.

QUÉ NO CAMBIA. El link de revisión se sigue posteando a las 07:15 igual que
siempre (Eve: "igualmente mandame link de revisión para estar seguros"). Un ✅
humano sigue mandando, aunque el chequeo haya frenado al capitán. El guardián de
run.py --send-reviewed (nunca mandar una sección amarilla, nunca mandar un .eml
distinto del PDF sellado) sigue ahí abajo de todo esto.

FALLA CERRADO. Si la revisión visual no puede correr (sin llave de la API, sin
saldo, un error), el capitán NO sale solo: queda esperando el ✅ y se avisa que no
se pudo revisar. Un chequeo que no corrió no es un chequeo que pasó.

UN CAPITÁN NO FRENA A LOS OTROS. Cada capitán es su propio bloque desde 9/23;
se juzga y se manda por separado.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from automations.captainship_drafts import config
from automations.captainship_drafts import email_build

# Desde cuándo vale (Eve 2026-10-05: "a partir de mañana"). Antes de esta fecha el
# gate se comporta como siempre: ✅ de lunes a viernes, weekend_release sáb/dom.
ENABLED_FROM = dt.date(2026, 10, 6)
# Perilla de apagado: False = vuelve el gate manual (y weekend_release) sin tocar
# nada más. `review_gate --check --no-auto` hace lo mismo por una corrida.
ENABLED = True

# Cuántas veces por día se re-arma solo a un capitán por algo que "se arregla
# re-corriendo". Una: si después de re-armarlo sigue mal, no es pasajero y
# re-armarlo cada quince minutos sólo gasta Tableau y deja el hilo lleno.
MAX_REBUILDS = 1

# La revisión visual. Opus porque es la que tiene que ver lo que ve Eve: una caja
# con otra fuente, un 0.4285714 donde los demás dicen 43%.
MODEL = "claude-opus-5-5"

# Qué tracker de Tableau alimenta a cada tipo de capitanía. La caja de Rafael es
# fiber (ATT). Ver tableau_screenshots/freshness.EXTRACTS.
TRACKER_FOR_FLAVOR = {
    "rafael": "tableau:tracker_att",
    "fiber": "tableau:tracker_att",
    "b2b": "tableau:tracker_b2b",
    "nds": "tableau:tracker_nds",
}

AUTO_ID = "auto-check"
AUTO_WHO = "auto-check (no issues found)"

# Marcadores del hilo de #revision-emails. Llevan la clave del capitán (y la
# huella del motivo en el HELD) para decirse UNA vez: el chequeo corre cada 15'.
HELD_MARKER = "CAPTAINSHIP-AUTO-HELD"
REBUILT_MARKER = "CAPTAINSHIP-AUTO-REBUILT"

TABLEAU_CAUGHT_UP = ("Tableau updated after the draft was built — rebuilding it "
                     "with the new data")

_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"
STATE_DIR = _OUTPUT_DIR / "state" / "captainship_autosend"


def is_on(today: dt.date, *, enabled: bool = True) -> bool:
    return bool(enabled and ENABLED and today >= ENABLED_FROM)


def incident_key(today: dt.date) -> str:
    """UN hilo por día en #claudecorrections, fallen uno o seis (Eve: "si falla
    más de un reporte lo pongas todo dentro del mismo hilo diario")."""
    return f"captainship-autosend-{today.isoformat()}"


# --------------------------------------------------------------------------
# estado del día (local: todo el ciclo corre en Lucy 3)
# --------------------------------------------------------------------------
def _state_path(today: dt.date) -> Path:
    return STATE_DIR / f"{today.isoformat()}.json"


def load_state(today: dt.date) -> dict:
    try:
        return json.loads(_state_path(today).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — sin archivo = día nuevo
        return {}


def save_state(today: dt.date, state: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _state_path(today).write_text(json.dumps(state, indent=1),
                                      encoding="utf-8")
    except OSError:
        pass


def local_sent(today: dt.date) -> Set[str]:
    """Los capitanes que el envío automático YA mandó hoy. Es el candado de los
    que salieron sin link (y por lo tanto sin hilo donde anotarse)."""
    return set(load_state(today).get("sent") or [])


def mark_local_sent(today: dt.date, keys) -> None:
    if not keys:
        return
    state = load_state(today)
    state["sent"] = sorted(set(state.get("sent") or []) | set(keys))
    save_state(today, state)


def _eml(today: dt.date, key: str) -> Path:
    return _OUTPUT_DIR / f"captainship_draft_{key}_{today:%Y%m%d}.eml"


def eml_sha(today: dt.date, key: str) -> Optional[str]:
    p = _eml(today, key)
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


# --------------------------------------------------------------------------
# 1. el .eml: ¿está entero?
# --------------------------------------------------------------------------
def _parse(today: dt.date, key: str):
    from email import policy
    from email.parser import BytesParser
    p = _eml(today, key)
    return BytesParser(policy=policy.default).parsebytes(p.read_bytes())


def _html_and_images(msg) -> Tuple[str, Dict[str, Tuple[str, bytes]]]:
    html, imgs = "", {}
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "text/html" and not html:
            html = part.get_content()
        elif ctype.startswith("image/"):
            cid = (part.get("Content-ID") or "").strip()[1:-1]
            imgs[cid] = (ctype, part.get_payload(decode=True) or b"")
    return html, imgs


def pending_sections(html: str) -> List[str]:
    """Las secciones que el draft dice que no pudo capturar (la nota amarilla).
    Mismo regex que el guardián de run.py --send-reviewed."""
    mark = email_build.PENDING_MARK
    if mark not in html:
        return []
    found = re.findall(r"—\s*([^<>—]{1,80}?)\s*" + re.escape(mark), html)
    return list(dict.fromkeys(f.strip() for f in found)) or ["(sin nombre)"]


def structural_issues(today: dt.date, key: str) -> List[str]:
    """Lo que se ve sin mirar las imágenes: falta el draft, no tiene cuerpo, una
    imagen rota, una sección que dice "could not be captured". Todo esto se
    arregla re-armando (o no, y entonces frena)."""
    p = _eml(today, key)
    if not p.exists() or p.stat().st_size == 0:
        return ["the draft was never built"]
    try:
        html, imgs = _html_and_images(_parse(today, key))
    except Exception as e:  # noqa: BLE001 — un .eml ilegible ES el problema
        return [f"the draft cannot be read ({type(e).__name__})"]
    out = []
    if not html:
        return ["the draft has no body"]
    refs = re.findall(r'src="cid:([^"]+)"', html)
    if not imgs:
        out.append("the draft has no images")
    broken = [r for r in refs if r not in imgs]
    if broken:
        out.append(f"{len(broken)} broken image(s) in the email")
    empty = [c for c, (_t, b) in imgs.items() if len(b) < 200]
    if empty:
        out.append(f"{len(empty)} empty image(s)")
    for sec in pending_sections(html):
        out.append(f"missing section: {sec} (could not be captured)")
    return out


# --------------------------------------------------------------------------
# 2. Tableau: ¿los trackers están al día?
# --------------------------------------------------------------------------
def tableau_status(today: dt.date) -> Tuple[Dict[str, str], Dict[str, str],
                                            List[str]]:
    """({extract: por qué sigue atrasado}, {extract: se puso al día},
    [fuentes congeladas que pegó un pull de captainship hoy]).

    Los trackers: `_held_today.json` dice qué boards se retuvieron esta mañana
    por extract viejo (la alerta de Megan). Si después el catch-up los volvió a
    medir y dieron frescos, el extract figura READY en `_freshness.json` — eso es
    "se puso al día" y los drafts que se armaron antes hay que re-armarlos.

    Las fuentes: `shared/tableau_freshness` deja un archivo por fuente atrasada
    con los reportes que la usaron. Si uno es de captainship, el draft se armó
    con datos viejos y no hay re-corrida que lo arregle hasta que Tableau cargue.
    """
    stale: Dict[str, str] = {}
    recovered: Dict[str, str] = {}
    try:
        from automations.tableau_screenshots import freshness as fr
        held = fr.read_held(today)
        ready = fr._read_verdicts(today)
        for bid, why in held.items():
            eid = fr.extract_for_board(bid)
            if not eid:
                continue
            if eid in ready:
                recovered[eid] = ready[eid]
            else:
                stale.setdefault(eid, why)
    except Exception as e:  # noqa: BLE001
        print(f"  (trackers: no pude leer el estado — {type(e).__name__}: {e})",
              flush=True)
    sources: List[str] = []
    try:
        from automations.shared import tableau_freshness as tf
        for p in sorted(tf.STATE_DIR.glob(f"*-{today.isoformat()}.json")):
            try:
                st = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if not st.get("alerted"):
                continue
            if any("captainship" in str(r) for r in st.get("reports") or []):
                sources.append(f"{st.get('view') or p.stem} (data only "
                               f"through {st.get('newest') or '?'})")
    except Exception as e:  # noqa: BLE001
        print(f"  (fuentes Tableau: no pude leer el estado — "
              f"{type(e).__name__}: {e})", flush=True)
    return stale, recovered, sources


# --------------------------------------------------------------------------
# 3. la revisión visual — lo que hace Eve con el PDF
# --------------------------------------------------------------------------
_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "issues": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "image": {"type": "integer"},
                "section": {"type": "string"},
                "problem": {"type": "string"},
                "severity": {"type": "string", "enum": ["blocker", "minor"]},
            },
            "required": ["image", "section", "problem", "severity"],
            "additionalProperties": False}},
    },
    "required": ["ok", "issues"],
    "additionalProperties": False,
}

_SYSTEM = """You are the last check before a daily "Captainship Report" email \
goes out to a sales captain and their team. A person used to open every one of \
these and approve it by hand; you now do that review. Look at every image the \
way that careful reviewer would and decide if the email is fit to send.

The report covers REPORT_DAY (given below). Check:

1. MISSING DATA (blocker): a section that says it "could not be captured", a \
blank or nearly blank image, an image showing a login page / error / loading \
spinner / browser chrome, a table cut off mid-row or mid-column, a box with its \
header but no rows.

2. LATEST DAY (blocker): any table or chart laid out one column (or bar/point) \
per DAY must include REPORT_DAY as its newest day. Ending on an earlier day is a \
blocker. A REPORT_DAY column whose cells are ALL blank while the earlier days \
have numbers is a blocker. Weekly, week-to-date, monthly or cumulative tables do \
not need a day column; do not flag them for it. Dates may be written 10/4, \
10/4/26, Sun 10/4, Oct 4, etc.
SUNDAY EXCEPTION: when REPORT_DAY is a Sunday, a quiet day is normal — a blank \
or zero REPORT_DAY column is fine, and so is a Tableau table (the screenshots \
with dropdown filters on top) that simply has NO REPORT_DAY column: Tableau \
drops a day column when nobody has a row that day. Never treat that as a blocker \
on a Sunday; at most mention it as minor.
Do not compare SALES with ACTIVATIONS: sales tables (Product Summary, Captain \
Team units) and activation tables (Tableau "Captain Team Stats", activation \
weeks) count different things on different days; a sales number on REPORT_DAY \
says nothing about whether activations exist that day.

3. NUMBER FORMAT (blocker): inside one table, a column's numbers must share one \
format. Flag raw long decimals (0.4285714) where the rest show %, date serials \
(45934), "#REF!", "#N/A", "#DIV/0!", "#VALUE!", "#ERROR!", "Loading...", \
negative signs or currency where the rest have none, wildly different decimals.

4. STYLE (blocker): a table or box whose font, font size, colours, borders or \
alignment clearly differ from the other boxes of the same kind in this email \
(looks pasted in from somewhere else), overlapping or clipped text, unreadably \
small text, a header row that lost its colour band.

ACCEPTED, never an issue: grey notes saying "no data available" or "not \
available yet"; zero values that are formatted like their neighbours; a \
consistent house style you merely would have designed differently.

Report blockers (would refuse to send) and minors (would mention but still \
send). ok = true when there are no blockers. Refer to images by their number \
and name the section they sit under. Be concrete: "Cancel Rate box ends on \
10/3, no 10/4 column", not "dates look off". Write every section name and \
problem in English, short (one sentence each) — they are posted to Slack as is."""


# The cache of a visual review is keyed by the draft AND the rules it was judged
# by: changing _SYSTEM must re-review today's drafts, not reuse the old verdict.
PROMPT_ID = hashlib.sha256(_SYSTEM.encode("utf-8")).hexdigest()[:8]


def _api_client():
    from automations.shared.pkg import ensure
    anthropic = ensure("anthropic")
    from automations.brand_audit import credentials
    return anthropic, anthropic.Anthropic(api_key=credentials.anthropic_api_key())


def _shrink(ctype: str, data: bytes) -> Tuple[str, bytes]:
    """La API acepta hasta ~5 MB y ~8000 px por imagen; una captura de sheet
    grande se pasa. Se achica a PNG que entre, sin tocar las que ya entran."""
    if len(data) <= 3_500_000:
        return ctype, data
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.thumbnail((2400, 2400))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=88)
        return "image/jpeg", buf.getvalue()
    except Exception:  # noqa: BLE001 — sin PIL, va como está y que la API decida
        return ctype, data


def _visual_content(today: dt.date, key: str) -> list:
    msg = _parse(today, key)
    html, imgs = _html_and_images(msg)
    order: List[str] = []

    def _slot(m):
        cid = m.group(1)
        if cid not in order:
            order.append(cid)
        return f" [IMAGE {order.index(cid) + 1}] "

    text = re.sub(r'<img[^>]*src="cid:([^"]+)"[^>]*>', _slot, html)
    text = re.sub(r"<(br|/p|/div|/li|/h\d|/tr)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    import html as _h
    text = _h.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()[:8000]

    rd = email_build.reported_date(today)
    cap = config.BY_KEY.get(key)
    content: list = [{"type": "text", "text": (
        f"REPORT_DAY: {rd:%A} {rd.month}/{rd.day}/{rd:%Y}\n"
        f"Captain: {cap.display_name if cap else key} "
        f"({cap.flavor if cap else '?'})\n\n"
        f"EMAIL TEXT (images shown as [IMAGE n]):\n{text}")}]
    for i, cid in enumerate(order, 1):
        ctype, data = imgs.get(cid, ("", b""))
        if not data:
            continue
        ctype, data = _shrink(ctype, data)
        content.append({"type": "text", "text": f"IMAGE {i}:"})
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": ctype,
            "data": base64.b64encode(data).decode("ascii")}})
    return content


def visual_review(today: dt.date, key: str, *, client=None) -> dict:
    """{'ok': bool, 'issues': [...]} — o una excepción si no se pudo revisar."""
    if client is None:
        anthropic, client = _api_client()
    else:
        anthropic = None
    body = {"output_config": {"effort": "high", "format": {
        "type": "json_schema", "schema": _SCHEMA}}}
    messages = [{"role": "user", "content": _visual_content(today, key)}]
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=8000, system=_SYSTEM, messages=messages,
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={**body, "fallbacks": "default"})
    except Exception as e:  # noqa: BLE001
        if anthropic is None or not isinstance(e, anthropic.BadRequestError):
            raise
        resp = client.messages.create(model=MODEL, max_tokens=8000,
                                      system=_SYSTEM, messages=messages,
                                      extra_body=body)
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"visual review did not finish ({resp.stop_reason})")
    text = "".join(b.text for b in resp.content
                   if getattr(b, "type", "") == "text")
    out = json.loads(text)
    out["ok"] = not [i for i in out.get("issues") or []
                     if i.get("severity") == "blocker"]
    return out


def _issue_line(i: dict) -> str:
    sec = (i.get("section") or "").strip()
    return f"{sec + ': ' if sec else ''}{(i.get('problem') or '').strip()}"


# --------------------------------------------------------------------------
# la decisión, por capitán
# --------------------------------------------------------------------------
class Verdict:
    """Qué se hace hoy con un capitán.

    send     — sale solo.
    fixable  — algo que re-armar arregla (sección faltante, imagen rota, lo que
               vio la revisión visual, Tableau que se puso al día después).
    blocked  — algo que re-armar NO arregla ahora (Tableau atrasado, no se pudo
               revisar, sigue mal después de re-armar). Espera ✅ o el arreglo.
    """

    def __init__(self, key: str):
        self.key = key
        self.fixable: List[str] = []
        self.blocked: List[str] = []
        self.minor: List[str] = []

    @property
    def send(self) -> bool:
        return not self.fixable and not self.blocked

    def reasons(self) -> List[str]:
        return self.blocked + self.fixable

    def __repr__(self):  # pragma: no cover — sólo para el log
        return (f"Verdict({self.key}, send={self.send}, fixable={self.fixable}, "
                f"blocked={self.blocked})")


def judge(today: dt.date, keys: Sequence[str], *, state: dict,
          upstream_held: Optional[Dict[str, str]] = None,
          visual=visual_review, tableau=tableau_status,
          verbose: bool = True) -> Dict[str, Verdict]:
    """Revisa a cada capitán de `keys` y devuelve su veredicto.

    La revisión visual se guarda por huella del .eml en `state['visual']`: el
    chequeo corre cada 15 minutos y el mismo draft no se vuelve a mandar a la API.
    Un draft re-armado cambia de huella y se revisa de nuevo."""
    stale, recovered, sources = tableau(today)
    vis_cache = state.setdefault("visual", {})
    rebuilt = state.setdefault("rebuilds", {})
    tableau_rebuilt = set(state.setdefault("tableau_rebuilt", []))
    out: Dict[str, Verdict] = {}
    to_look: List[str] = []
    for key in keys:
        v = Verdict(key)
        out[key] = v
        cap = config.BY_KEY.get(key)
        eid = TRACKER_FOR_FLAVOR.get(cap.flavor if cap else "", "")

        # --- Tableau -------------------------------------------------------
        if eid in stale:
            v.blocked.append(f"Tableau not updated: the "
                             f"`{eid.split(':')[-1]}` tracker is still behind "
                             f"({stale[eid][:120]})")
        elif eid in recovered and key not in tableau_rebuilt:
            # El tracker se puso al día DESPUÉS de la mañana: el draft se armó
            # con el dato viejo. Se re-arma una vez con el nuevo.
            v.fixable.append(TABLEAU_CAUGHT_UP)
        for s in sources:
            v.blocked.append(f"Tableau not updated: {s}")
        if upstream_held and key in upstream_held:
            v.blocked.append(upstream_held[key])
        if v.blocked:
            continue          # no tiene sentido mirarlo: no puede salir igual

        # --- el .eml -------------------------------------------------------
        struct = structural_issues(today, key)
        if struct:
            (v.blocked if rebuilt.get(key, 0) >= MAX_REBUILDS
             else v.fixable).extend(struct)
            continue
        if v.fixable:
            continue          # se va a re-armar igual; mirar ahora es gastar

        to_look.append(key)

    # --- la revision visual, en paralelo ---------------------------------------
    # Quince capitanes de a uno son ~15 minutos de API; de a cuatro, ~4. Lo que
    # ya se miro con la misma huella sale del cache sin llamar a nadie.
    shas = {k: eml_sha(today, k) for k in to_look}
    need = [k for k in to_look
            if not ((vis_cache.get(k) or {}).get("sha") == shas[k]
                    and (vis_cache.get(k) or {}).get("prompt") == PROMPT_ID
                    and "result" in (vis_cache.get(k) or {}))]
    results: Dict[str, object] = {}
    if need:
        from concurrent.futures import ThreadPoolExecutor

        def _one(k):
            try:
                return k, visual(today, k)
            except Exception as e:  # noqa: BLE001 - falla cerrado
                return k, e
        with ThreadPoolExecutor(max_workers=min(4, len(need))) as pool:
            for k, res in pool.map(_one, need):
                results[k] = res
                if not isinstance(res, Exception):
                    vis_cache[k] = {"sha": shas[k], "prompt": PROMPT_ID,
                                    "result": res,
                                    "at": dt.datetime.now().isoformat(
                                        timespec="minutes")}
    for key in to_look:
        v = out[key]
        res = results.get(key, (vis_cache.get(key) or {}).get("result"))
        if isinstance(res, Exception) or not isinstance(res, dict):
            v.blocked.append(f"could not run the visual check "
                             f"({type(res).__name__}: {str(res)[:120]})")
            continue
        issues = res.get("issues") or []
        v.minor = [_issue_line(i) for i in issues if i.get("severity") != "blocker"]
        bad = [_issue_line(i) for i in issues if i.get("severity") == "blocker"]
        if bad:
            (v.blocked if rebuilt.get(key, 0) >= MAX_REBUILDS
             else v.fixable).extend(bad)
    if verbose:
        for k, v in out.items():
            print(f"  auto-check {k}: "
                  + ("OK" if v.send else
                     f"{'RE-ARMAR' if v.fixable and not v.blocked else 'FRENADO'}"
                     f" — {'; '.join(v.reasons())}"), flush=True)
    return out


def rebuild(today: dt.date, keys: Sequence[str]) -> int:
    """Re-arma esos capitanes. run.py --dry-run re-sella solo el PDF de revisión
    (refresh_stale_blocks), así que el link que ya está en el hilo muestra la
    versión nueva y el envío no se niega por huella distinta."""
    cmd = [sys.executable, "-u", "-m", "automations.captainship_drafts.run",
           "--dry-run", "--only", ",".join(keys), "--date", today.isoformat()]
    print(f"→ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd)


# --------------------------------------------------------------------------
# avisos
# --------------------------------------------------------------------------
def _short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def hold_text(heading: str, reasons: Sequence[str], mentions: str,
              rebuilt: bool) -> str:
    tail = ("It was already rebuilt once automatically and it is still "
            "wrong, so it is not a one-off." if rebuilt else "")
    return (f"{mentions} ⚠️ *{heading}* — NOT sent automatically:\n"
            + "\n".join(f"• {r}" for r in reasons)
            + (f"\n{tail}" if tail else "")
            + "\nIf it looks fine to you, ✅ its link and it goes out as is. "
              "Otherwise fix the source and rebuild it (same link) — the next "
              "check reviews it again and sends it if it comes out clean.")


def alert_corrections(today: dt.date, held: Dict[str, Tuple[str, List[str], bool]],
                      *, dry_run: bool = False) -> None:
    """El mismo aviso, en #claudecorrections-and-requests, en UN hilo por día.

    `held` = {clave: (encabezado, motivos, necesita_persona)}. El primer aviso
    del día abre el hilo con todos los que fallaron en esa pasada; los que caen
    después se suman al MISMO hilo (incident_thread nombra los `subjects` que
    todavía no nombró) — nunca un post nuevo por capitán."""
    if not held:
        return
    try:
        from automations.shared import incident_thread as it
        d = email_build.reported_date(today)
        lines = []
        for _k, (heading, reasons, _nh) in held.items():
            lines.append(f"• *{heading}* — " + "; ".join(reasons))
        lines += [
            "",
            "*What this means:* these captains' reports were NOT sent "
            "automatically; every other captain's was. Each one's link is in "
            "today's thread in #revision-emails — a ✅ there sends it as is.",
            "*To fix it, ON LUCY 3:* `lucy rerun captainship_drafts --only "
            "<captain> --dry-run` (rebuilds and re-seals the same link); the "
            "15-minute check reviews it again and sends it if it comes out "
            "clean. If it is Tableau being behind, there is nothing to re-run "
            "until the extract loads — it rebuilds on its own once it does.",
        ]
        subjects = [f"{h}: {'; '.join(r)[:140]}" for h, r, _nh in held.values()]
        it.open_or_followup(
            key=incident_key(today),
            title=(f"✉️ *Captainship Reports {d.month}/{d.day}* — "
                   f"{len(held)} not sent automatically"),
            body=lines, subjects=subjects, day=today,
            label="Captainship Reports (auto-send)",
            needs_human=any(nh for _h, _r, nh in held.values()),
            dry_run=dry_run)
        _mark_alerted(today)
    except Exception as e:  # noqa: BLE001 — un aviso nunca tumba el chequeo
        print(f"  (aviso a corrections salteado: {e})", flush=True)


def _alerted_marker(today: dt.date) -> Path:
    return STATE_DIR / f"{today.isoformat()}.alerted"


def _mark_alerted(today: dt.date) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _alerted_marker(today).write_text(dt.datetime.now().isoformat(),
                                          encoding="utf-8")
    except OSError:
        pass


def close_incident(today: dt.date) -> None:
    """Todos salieron (solos o con ✅): cerrar el hilo del día en corrections.
    Sólo pregunta a Slack si esta máquina abrió uno hoy."""
    marker = _alerted_marker(today)
    if not marker.exists():
        return
    try:
        from automations.shared import incident_thread as it
        if it.ensure_closed(incident_key(today),
                            what="*Captainship Reports* — every captain is out",
                            detail="_The held reports went out._"):
            marker.unlink()
    except Exception as e:  # noqa: BLE001
        print(f"  (no pude cerrar el hilo de corrections: {e})", flush=True)
