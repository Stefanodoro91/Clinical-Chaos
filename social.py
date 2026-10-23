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


def short_text(post, link, limit):
    """Titolo, una riga di contesto e il link al sito, entro `limit` caratteri."""
    title = post.get("title", "").strip()
    body = _strip_tags(post.get("caption", ""))
    first = next((l.strip() for l in body.splitlines() if l.strip() and l.strip() != title
                  and not l.lower().startswith(("programme:", "eligible", "deadline", "official call", "who can lead"))), "")
    tail = f"\n\n{link}"
    room = limit - len(title) - len(tail) - 2
    if room < 20:
        return (title[:limit - len(tail) - 1] + "…" + tail)
    if len(first) > room:
        first = first[:room - 1].rsplit(" ", 1)[0] + "…"
    return f"{title}\n\n{first}{tail}" if first else f"{title}{tail}"


# ---------------------------------------------------------------- Bluesky
def bluesky_enabled():
    return bool(os.environ.get("BLUESKY_HANDLE") and os.environ.get("BLUESKY_APP_PASSWORD"))


def publish_bluesky(image_paths, post, link):
    """Post con fino a 4 immagini (le prime slide) e link cliccabile. Restituisce l'URI del post."""
    s = requests.post(f"{BSKY}/com.atproto.server.createSession", timeout=30,
                      json={"identifier": os.environ["BLUESKY_HANDLE"], "password": os.environ["BLUESKY_APP_PASSWORD"]})
    s.raise_for_status()
    sess = s.json()
    auth = {"Authorization": f"Bearer {sess['accessJwt']}"}
    images = []
    for i, p in enumerate(list(image_paths)[:4]):
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
