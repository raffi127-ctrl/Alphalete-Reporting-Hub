"""This office's Facebook reviews, read and answered from THIS computer
(Megan 2026-11-15: "yes build the facebook part on the office computer").

The key is for THIS office's page only: made on Megan's Mac when the page is
connected (it was shared with Alphalete's Meta business on the set-up call)
and sent here sealed (sealed.py), so the jobs sheet never holds it readable.
Alphalete's own Meta key never comes here.

Jobs (ride social_check / social_post with payload["do"], like Google's):
  fb_hello    -- make a one-time lock; answer with its public half
  fb_key      -- open the sealed page key, prove it reads the page, keep it
  fb_reviews  -- the page's reviews nobody has answered yet
  fb_reply    -- post one approved reply under a review

Standard library only.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List

from automations.icd_alerts import config as C
from automations.icd_alerts import sealed

GRAPH = "https://graph.facebook.com/v23.0"
KEY_PATH = C.APP_DIR / "facebook-page.json"
LOCK_PATH = C.APP_DIR / "facebook-lock.json"
READ_MAX = 25


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _graph(method: str, path: str, params: Dict) -> Dict:
    data = None
    url = "%s/%s" % (GRAPH, path)
    if method == "GET":
        url += "?" + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=40, context=_ctx()) as r:
            out = json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            out = json.loads(e.read().decode("utf-8", "ignore"))
        except ValueError:
            out = {"error": {"message": "HTTP %s" % e.code}}
    if "error" in out:
        err = out["error"] if isinstance(out["error"], dict) else {"message": str(out["error"])}
        if err.get("code") == 190:
            raise RuntimeError("signed_out")
        raise RuntimeError(_err_text(err))
    return out


def _err_text(err: Dict) -> str:
    """Everything Graph said, not just its headline.

    WHY (2026-11-16): raf's page logged `fb_reply_error · Permissions error`
    70 times in one day with ZERO successful replies, and that message alone
    cannot tell the two causes apart -- a page token missing
    pages_manage_engagement (every reply fails, it is a connection problem) or
    Graph refusing a comment on one particular recommendation story (that one
    review is a dead end). The fields that DO tell them apart are code,
    error_subcode and error_user_msg, and this function used to drop all three
    on the floor, keeping only err['message']. Same mistake as the knocks
    alert truncating its own 'Headers seen:' list: the failure was reported
    and its evidence was not. fbtrace_id is kept because it is what Meta
    support asks for."""
    msg = str(err.get("message") or "Graph error")
    bits = []
    code, sub = err.get("code"), err.get("error_subcode")
    if code is not None:
        bits.append("code %s" % code)
    if sub:
        bits.append("subcode %s" % sub)
    etype = err.get("type")
    if etype:
        bits.append(str(etype))
    trace = err.get("fbtrace_id")
    if trace:
        bits.append("fbtrace %s" % trace)
    out_msg = msg if not bits else "%s [%s]" % (msg, ", ".join(bits))
    user = err.get("error_user_msg") or err.get("error_user_title")
    if user:
        out_msg = "%s — %s" % (out_msg, user)
    return out_msg[:400]


def _secure_write(path, data: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _key() -> Dict:
    try:
        return json.loads(KEY_PATH.read_text())
    except Exception:  # noqa: BLE001
        return {}


# ---- connecting ----------------------------------------------------------------
def hello(payload: Dict, log=print) -> Dict:
    priv, pub = sealed.keypair()
    _secure_write(LOCK_PATH, {"priv": priv})
    return {"status": "ready", "public": pub}


def install_key(payload: Dict, log=print) -> Dict:
    try:
        priv = json.loads(LOCK_PATH.read_text())["priv"]
    except Exception:  # noqa: BLE001
        return {"status": "error", "error": "no lock on this computer (send fb_hello first)"}
    page_id = str(payload.get("page_id") or "")
    try:
        token = sealed.unseal(str(payload.get("box") or ""), priv)
        page = _graph("GET", page_id, {"access_token": token, "fields": "id,name"})
    except (ValueError, RuntimeError) as e:
        return {"status": "error", "error": str(e)[:200]}
    _secure_write(KEY_PATH, {"page_id": page_id, "token": token})
    try:
        LOCK_PATH.unlink()                       # one use only
    except OSError:
        pass
    return {"status": "connected", "page": page.get("name", ""), "page_id": page_id}


# ---- read + reply ----------------------------------------------------------------
def _answered(story: str, page_id: str, token: str) -> bool:
    r = _graph("GET", "%s/comments" % story, {"access_token": token, "fields": "from{id}", "limit": 50})
    return any((c.get("from") or {}).get("id") == page_id for c in r.get("data") or [])


def read_job(payload: Dict, log=print) -> Dict:
    k = _key()
    if not k.get("token"):
        return {"status": "signed_out", "error": "no Facebook page key on this computer"}
    skip = set(payload.get("skip") or [])
    out: List[Dict] = []
    try:
        path, params, seen = "%s/ratings" % k["page_id"], {
            "access_token": k["token"], "limit": 50,
            "fields": "created_time,recommendation_type,review_text,open_graph_story{id}"}, 0
        while path and seen < 300:
            r = _graph("GET", path, params)
            for x in r.get("data") or []:
                seen += 1
                story = (x.get("open_graph_story") or {}).get("id")
                if not story or story in skip or _answered(story, k["page_id"], k["token"]):
                    continue
                out.append({"story": story, "recommendation_type": x.get("recommendation_type", ""),
                            "review_text": (x.get("review_text") or "")[:2000],
                            "created_time": x.get("created_time", "")})
                if len(out) >= READ_MAX:
                    return {"status": "ok", "reviews": out, "more": True}
            nxt = (r.get("paging") or {}).get("next") or ""
            if not nxt:
                break
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(nxt).query))
            path, params = "%s/ratings" % k["page_id"], dict(q, access_token=k["token"])
    except RuntimeError as e:
        return {"status": "signed_out" if str(e) == "signed_out" else "error", "error": str(e)[:200]}
    return {"status": "ok", "reviews": out, "more": False}


def reply_job(payload: Dict, live: bool, log=print) -> Dict:
    story, text = str(payload.get("story") or ""), str(payload.get("comment") or "").strip()
    if not story or not text:
        return {"status": "error", "error": "job had no review or no reply"}
    if not live:
        return {"status": "dry_run", "story": story}
    k = _key()
    if not k.get("token"):
        return {"status": "signed_out", "error": "no Facebook page key", "story": story}
    try:
        if _answered(story, k["page_id"], k["token"]):
            return {"status": "replied", "story": story, "note": "already answered"}
        _graph("POST", "%s/comments" % story, {"access_token": k["token"], "message": text})
    except RuntimeError as e:
        # 400, not 200: _err_text now carries code/subcode/user message, and a
        # 200-char cut would land in the middle of exactly those -- the whole
        # point of keeping them (2026-11-16).
        return {"status": "signed_out" if str(e) == "signed_out" else "error", "error": str(e)[:400],
                "story": story}
    return {"status": "replied", "story": story}
