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


def _clip(text, n):
    return text if len(text) <= n else text[:n - 1].rsplit(" ", 1)[0] + "…"


def positions_text(post, link, limit):
    """Posizioni accademiche: una riga intera per posizione (tipo, titolo, Paese) finché ci stanno, mai un annuncio
    a metà; le altre si contano e si rimanda al sito, dove ci sono scadenze e link."""
    jobs = post["jobs"]
    many = len(jobs) > 1
    long_head = (f"{len(jobs)} new academic positions this week in clinical research, engineering and rehabilitation:"
                 if many else "New academic position this week in clinical research, engineering and rehabilitation:")
    short_head = f"{len(jobs)} new academic positions this week:" if many else "New academic position this week:"
    a, b = _positions_rows(jobs, link, limit, long_head), _positions_rows(jobs, link, limit, short_head)
    return a[1] if a[0] >= b[0] else b[1]


def _positions_rows(jobs, link, limit, head):
    """(righe incluse, testo) con l'intestazione data."""
    rows = []
    for j in jobs:
        country = (j.get("place") or "").split(", ")[-1]
        rows.append(f"• {j['type']} – {_clip(j['title'], 60)}" + (f" ({country})" if country else ""))
    for n in range(len(rows), -1, -1):
        rest = len(rows) - n
        tail = (f"\n\n+{rest} more, with deadlines and links: {link}" if rest
                else f"\n\nDeadlines and links: {link}") if link else (f"\n\n+{rest} more" if rest else "")
        text = head + ("\n\n" + "\n".join(rows[:n]) if n else "") + tail
        if len(text) <= limit:
            return n, text
    return 0, _clip(head, limit - len(tail)) + tail


def short_text(post, link, limit):
    """Testo breve per Bluesky e Threads: l'hook (prima riga della didascalia), poi il contesto che ci sta, poi il link.
    Senza didascalia: titolo e takeaway. Posizioni accademiche: elenco a righe intere (positions_text)."""
    if post.get("kind") == "positions" and post.get("jobs"):
        return positions_text(post, link, limit)
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
    paths = list(image_paths)[:max(1, min(4, max_images))]
    for i, p in enumerate(paths):
        data = Path(p).read_bytes()
        if len(data) > 950_000:
            continue                                  # limite di Bluesky: circa 1 MB per immagine
        r = requests.post(f"{BSKY}/com.atproto.repo.uploadBlob", data=data, timeout=60,
                          headers={**auth, "Content-Type": "image/jpeg"})
        r.raise_for_status()
        images.append({"alt": post.get('title', '') + (f" – slide {i + 1}" if len(paths) > 1 else ""), "image": r.json()["blob"],
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


# ---------------------------------------------------------------- reel (video) su Threads e Bluesky
def _clip_text(text, limit):
    text = " ".join(text.split()) if "\n" not in text else text
    return text if len(text) <= limit else text[:limit - 1].rsplit(" ", 1)[0] + "…"


def reel_text(title, caption, link, limit):
    """Testo breve del video: titolo, prima frase utile della didascalia, link (frasi intere, mai tagliate a metà)."""
    first = next((l.strip() for l in caption.splitlines() if l.strip() and l.strip() != title
                  and not l.strip().startswith("#")), "")
    tail = f"\n\n{link}" if link else ""
    out = f"{title}\n\n{first}" if first and len(title) + len(first) + 2 + len(tail) <= limit else title
    return _clip_text(out, limit - len(tail)) + tail


def publish_threads_video(video_url, text):
    """Video su Threads da un URL pubblico (mp4). Restituisce l'id del post."""
    user = os.environ["THREADS_USER_ID"]
    c = _threads("POST", f"{user}/threads", media_type="VIDEO", video_url=video_url, text=text)["id"]
    for _ in range(60):                       # i video richiedono qualche minuto di elaborazione
        st = _threads("GET", c, fields="status,error_message")
        if st.get("status") == "FINISHED":
            break
        if st.get("status") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Threads ha rifiutato il video ({st.get('error_message') or st.get('status')})")
        time.sleep(10)
    else:
        raise RuntimeError("Threads: video non pronto dopo 10 minuti")
    return _threads("POST", f"{user}/threads_publish", creation_id=c)["id"]


def publish_bluesky_video(video_path, text, link, alt=""):
    """Video su Bluesky con il servizio video ufficiale (app.bsky.video), poi il post con link cliccabile."""
    s = requests.post(f"{BSKY}/com.atproto.server.createSession", timeout=30,
                      json={"identifier": os.environ["BLUESKY_HANDLE"], "password": os.environ["BLUESKY_APP_PASSWORD"]})
    s.raise_for_status()
    sess = s.json()
    auth = {"Authorization": f"Bearer {sess['accessJwt']}"}
    pds = (sess.get("didDoc") or {}).get("service", [{}])[0].get("serviceEndpoint", "https://bsky.social")
    host = pds.split("://", 1)[-1].rstrip("/")
    t = requests.get(f"{BSKY}/com.atproto.server.getServiceAuth", headers=auth, timeout=30,
                     params={"aud": f"did:web:{host}", "lxm": "com.atproto.repo.uploadBlob",
                             "exp": int(time.time()) + 1800})
    t.raise_for_status()
    data = Path(video_path).read_bytes()
    up = requests.post("https://video.bsky.app/xrpc/app.bsky.video.uploadVideo", timeout=300,
                       params={"did": sess["did"], "name": Path(video_path).name},
                       headers={"Authorization": f"Bearer {t.json()['token']}", "Content-Type": "video/mp4"}, data=data)
    if not up.ok and "already_exists" not in up.text:
        raise RuntimeError(f"Bluesky: caricamento del video rifiutato {up.status_code}: {up.text[:200]}")
    job = up.json().get("jobId") or up.json().get("jobStatus", {}).get("jobId")
    blob = up.json().get("blob") or (up.json().get("jobStatus") or {}).get("blob")
    for _ in range(60):
        if blob:
            break
        st = requests.get("https://video.bsky.app/xrpc/app.bsky.video.getJobStatus", params={"jobId": job},
                          headers=auth, timeout=30).json().get("jobStatus", {})
        if st.get("state") == "JOB_STATE_FAILED":
            raise RuntimeError(f"Bluesky: elaborazione del video fallita ({st.get('error', '')})")
        blob = st.get("blob")
        if not blob:
            time.sleep(5)
    if not blob:
        raise RuntimeError("Bluesky: video non pronto dopo 5 minuti")
    start = text.encode("utf-8").find(link.encode("utf-8")) if link else -1
    record = {"$type": "app.bsky.feed.post", "text": text, "langs": ["en"],
              "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
              "embed": {"$type": "app.bsky.embed.video", "video": blob, "alt": alt[:1000],
                        "aspectRatio": {"width": 1080, "height": 1920}}}
    if start >= 0:
        record["facets"] = [{"index": {"byteStart": start, "byteEnd": start + len(link.encode("utf-8"))},
                             "features": [{"$type": "app.bsky.richtext.facet#link", "uri": link}]}]
    r = requests.post(f"{BSKY}/com.atproto.repo.createRecord", headers=auth, timeout=30,
                      json={"repo": sess["did"], "collection": "app.bsky.feed.post", "record": record})
    r.raise_for_status()
    return r.json().get("uri")
