"""Pubblicazione degli stessi post su Bluesky e Threads. Si attiva da sola quando i secret ci sono:
BLUESKY_HANDLE + BLUESKY_APP_PASSWORD, THREADS_USER_ID + THREADS_ACCESS_TOKEN."""

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BSKY = "https://bsky.social/xrpc"
THREADS = "https://graph.threads.net/v1.0"


def _strip_tags(text):
    return re.sub(r"(\s#\w+)+\s*$", "", re.sub(r"\n#\w+(\s#\w+)*", "", text)).strip()


_LABELS = ("programme:", "eligible", "deadline", "official call", "who can lead", "all open calls", "details are compiled",
           "looking for consortium", "based on", "more methods", "always check")


def _paragraphs(post):
    body = _strip_tags(post.get("caption", ""))
    out = []
    for par in re.split(r"\n\s*\n", body):
        par = " ".join(par.split())
        if par and not par.lower().startswith(_LABELS) and "link in bio" not in par.lower():
            out.append(par)
    return out


def short_text(post, link, limit):
    """Testo breve per Bluesky e Threads: l'hook (prima riga della didascalia), poi il contesto che ci sta, poi il link.
    Senza didascalia: titolo e takeaway."""
    pars = _paragraphs(post) or [p for p in (post.get("title", "").strip(), post.get("takeaway", "").strip()) if p]
    tail = f"\n\n{link}" if link else ""
    room = limit - len(tail)
    out = ""
    for par in pars:
        cand = f"{out}\n\n{par}" if out else par
        if len(cand) <= room:
            out = cand
        elif not out:                       # nemmeno l'hook ci sta: si taglia a parola intera
            out = par[:room - 1].rsplit(" ", 1)[0] + "…"
            break
        else:                               # paragrafo troppo lungo: si aggiungono le frasi intere che ci stanno
            part = ""
            for sent in re.split(r"(?<=[.!?])\s+", par):
                if len(f"{out}\n\n{part} {sent}".rstrip()) > room:
                    break
                part = f"{part} {sent}".strip()
            if part:
                out = f"{out}\n\n{part}"
            break
    return out + tail


# ---------------------------------------------------------------- Bluesky
def bluesky_enabled():
    return bool(os.environ.get("BLUESKY_HANDLE") and os.environ.get("BLUESKY_APP_PASSWORD"))


def publish_bluesky(image_paths, post, link, max_images=1):
    """Post con la prima slide (o fino a 4 immagini) e link cliccabile alla pagina del sito. Restituisce l'URI.
    Su Bluesky i caroselli non esistono: la prima slide più il link al sito è il formato più efficace."""
    s = requests.post(f"{BSKY}/com.atproto.server.createSession", timeout=30,
                      json={"identifier": os.environ["BLUESKY_HANDLE"], "password": os.environ["BLUESKY_APP_PASSWORD"]})
    s.raise_for_status()
    sess = s.json()
    auth = {"Authorization": f"Bearer {sess['accessJwt']}"}
    images = []
    for i, p in enumerate(list(image_paths)[:max(1, min(4, max_images))]):
        data = Path(p).read_bytes()
        if len(data) > 950_000:
            continue                                  # limite di Bluesky: circa 1 MB per immagine
        r = requests.post(f"{BSKY}/com.atproto.repo.uploadBlob", data=data, timeout=60,
                          headers={**auth, "Content-Type": "image/jpeg"})
        r.raise_for_status()
        images.append({"alt": f"{post.get('title', '')} – slide {i + 1}", "image": r.json()["blob"],
                       "aspectRatio": {"width": 1080, "height": 1350}})
    text = short_text(post, link, 300)
    start = text.encode("utf-8").find(link.encode("utf-8"))
    record = {"$type": "app.bsky.feed.post", "text": text, "langs": ["en"],
              "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    if start >= 0:
        record["facets"] = [{"index": {"byteStart": start, "byteEnd": start + len(link.encode("utf-8"))},
                             "features": [{"$type": "app.bsky.richtext.facet#link", "uri": link}]}]
    if images:
        record["embed"] = {"$type": "app.bsky.embed.images", "images": images}
    r = requests.post(f"{BSKY}/com.atproto.repo.createRecord", headers=auth, timeout=30,
                      json={"repo": sess["did"], "collection": "app.bsky.feed.post", "record": record})
    r.raise_for_status()
    return r.json().get("uri")


# ---------------------------------------------------------------- Threads
def threads_enabled():
    return bool(os.environ.get("THREADS_USER_ID") and os.environ.get("THREADS_ACCESS_TOKEN"))


def _threads(method, path, **params):
    params["access_token"] = os.environ["THREADS_ACCESS_TOKEN"]
    url = f"{THREADS}/{path}"
    r = requests.post(url, data=params, timeout=60) if method == "POST" else requests.get(url, params=params, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Errore Threads {r.status_code}: {r.text[:300]}")
    return r.json()


def _threads_ready(cid):
    for _ in range(30):
        st = _threads("GET", cid, fields="status").get("status")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Threads ha rifiutato il contenuto ({st})")
        time.sleep(5)
    raise RuntimeError("Threads: contenuto non pronto dopo 150 s")


def publish_threads(image_urls, post, link):
    """Carosello su Threads con le stesse slide (URL pubblici) e testo breve. Restituisce l'id del post."""
    user = os.environ["THREADS_USER_ID"]
    children = []
    for u in list(image_urls)[:10]:
        cid = _threads("POST", f"{user}/threads", media_type="IMAGE", image_url=u, is_carousel_item="true")["id"]
        _threads_ready(cid)
        children.append(cid)
    text = short_text(post, link, 500)
    if len(children) >= 2:
        c = _threads("POST", f"{user}/threads", media_type="CAROUSEL", children=",".join(children), text=text)["id"]
    else:
        c = _threads("POST", f"{user}/threads", media_type="TEXT", text=text)["id"]
    _threads_ready(c)
    return _threads("POST", f"{user}/threads_publish", creation_id=c)["id"]
