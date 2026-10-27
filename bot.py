#!/usr/bin/env python3
"""
Research methods bot
1) Legge i nuovi file nella cartella Drive "Materiale" e li trasforma in post (coda: queue.json).
2) Ogni giorno pubblica su Instagram il prossimo post della coda come carosello.
"""

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

import cards
import content
import grants
import positions

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
QUEUE_FILE = ROOT / "queue.json"
POSTED_FILE = ROOT / "posted_log.json"
SOURCES_FILE = ROOT / "sources_log.json"
IMAGES_DIR = ROOT / "published_images"
PREVIEW_DIR = ROOT / "preview"
PAGE_FILE = ROOT / "docs" / "calls.html"   # pagina dei bandi
HOME_FILE = ROOT / "docs" / "index.html"   # pagina iniziale del link in bio: due pulsanti, bandi e posizioni

GRAPH_VERSION = os.environ.get("GRAPH_API_VERSION") or "v23.0"
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
MAX_CAPTION_CHARS = 2200
MAX_HASHTAGS = 5          # limite di Instagram (dicembre 2025): oltre, meno portata


# ---------------------------------------------------------------- utilità
def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def git(*args):
    subprocess.run(["git", *args], cwd=ROOT, check=True)


content.THINKING = dict(CONFIG.get("gemini_thinking") or {})
content.CHECK_CAP = int(CONFIG.get("gemini_daily_cap_checks", 34))   # oltre: verifiche ferme, quota lasciata ai post
positions.TEXT_CHARS = int(CONFIG.get("positions_text_chars") or positions.TEXT_CHARS)

def _head():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def commit_and_push(paths, message):
    if DRY_RUN:
        return None
    usage = content.save_usage(ROOT / "usage")      # consumo di Gemini del giro, nello stesso commit
    git("add", *paths, *([str(usage.relative_to(ROOT))] if usage else []))
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode != 0:
        git("commit", "-m", message)
        for attempt in range(3):         # se nel frattempo sono arrivati altri commit, li si integra e si riprova
            if subprocess.run(["git", "push"], cwd=ROOT).returncode == 0:
                break
            git("pull", "--rebase", "-X", "theirs")
        else:
            git("push")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def notify(title, body):
    """Apre una issue sul repository: GitHub invia un'email al proprietario."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if DRY_RUN or not token or not repo:
        print(f"[AVVISO] {title}: {body}")
        return
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    api = f"https://api.github.com/repos/{repo}/issues"
    try:
        existing = requests.get(api, headers=headers, params={"state": "open"}, timeout=30).json()
        if any(isinstance(i, dict) and i.get("title") == title for i in existing):
            return
        requests.post(api, headers=headers, json={"title": title, "body": body}, timeout=30)
    except requests.RequestException as e:
        print(f"Impossibile creare l'avviso: {e}")


# ---------------------------------------------------------------- Google Drive
def drive_service():
    info = json.loads(os.environ["GDRIVE_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_files(drive, folder_id):
    files, token = [], None
    while True:
        resp = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name, mimeType, createdTime)",
            orderBy="createdTime", pageSize=1000, pageToken=token,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        files += [f for f in resp.get("files", []) if f["mimeType"] != "application/vnd.google-apps.folder"]
        token = resp.get("nextPageToken")
        if not token:
            return files


def move(drive, file_id, src, dst):
    drive.files().update(fileId=file_id, addParents=dst, removeParents=src,
                         fields="id", supportsAllDrives=True).execute()


# ---------------------------------------------------------------- fase 1: lettura materiale
def ingest(drive, queue, limit=None):
    inbox, done_folder = os.environ["GDRIVE_FOLDER_ID"], os.environ["GDRIVE_DONE_FOLDER_ID"]
    sources = load(SOURCES_FILE, [])
    seen = {s["drive_id"] for s in sources}
    pending = [f for f in list_files(drive, inbox) if f["id"] not in seen]
    limit = int(limit or CONFIG.get("max_new_files_per_run", 1))

    for f in pending[:limit]:
        if not content.is_supported(f):
            print(f"Formato non supportato, ignoro: {f['name']}")
            sources.append({"drive_id": f["id"], "name": f["name"], "posts": 0, "note": "non supportato"})
            continue
        print(f"Leggo il materiale: {f['name']}")
        try:
            part = content.material_part(drive, f)
            published = [x["title"] for x in load(POSTED_FILE, [])] + [x["title"] for x in queue]
            posts = content.generate_posts(part, f["name"], CONFIG["brand_name"],
                                           int(CONFIG.get("max_posts_per_file", 12)), published)
        except Exception as e:
            print(f"Non sono riuscito a elaborare {f['name']} (riprovo al prossimo giro): {e}")
            continue
        for p in posts:
            p.update({"id": uuid.uuid4().hex[:8], "source": f["name"]})
        queue.extend(posts)
        sources.append({"drive_id": f["id"], "name": f["name"], "posts": len(posts),
                        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")})
        print(f"  → {len(posts)} post aggiunti alla coda")
        if posts == []:
            notify(f"Nessun post ricavato da {f['name']}",
                   "Il file non sembra contenere concetti di ricerca o metodologia utilizzabili.")
        if not DRY_RUN:
            save(QUEUE_FILE, queue)
            save(SOURCES_FILE, sources)
            commit_and_push([QUEUE_FILE.name, SOURCES_FILE.name], f"Nuovi post da {f['name']}")
            try:
                move(drive, f["id"], inbox, done_folder)
            except Exception as e:
                print(f"File elaborato ma non spostato in Drive (non verrà riletto): {e}")
    return len(pending) - min(len(pending), limit)


# ---------------------------------------------------------------- fase 2: pubblicazione
def _similar(a, b):
    from difflib import SequenceMatcher
    norm = lambda x: " ".join(w for w in "".join(ch.lower() if ch.isalnum() else " " for ch in x).split()
                              if w not in {"the", "a", "an", "in", "of", "your", "do", "does", "why", "is", "it", "and", "for", "to"})
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


DUP_SCHEMA = {"type": "OBJECT", "properties": {"duplicates": {"type": "ARRAY", "items": {"type": "OBJECT",
              "properties": {"index": {"type": "INTEGER"}, "same_as": {"type": "STRING"}},
              "required": ["index", "same_as"]}}}, "required": ["duplicates"]}


def drop_repeats(queue, posted, threshold=0.72):
    """Toglie dalla coda i post che ripetono un concetto già pubblicato (o già presente prima in coda):
    prima il confronto dei titoli, poi Gemini sul significato (titolo + messaggio chiave)."""
    seen = [p["title"] for p in posted if (p.get("kind") or "research") == "research"]
    kept = []
    for q in queue:
        twin = next((t for t in seen if _similar(q["title"], t) >= threshold), None)
        if twin:
            print(f"::notice title=Post doppione tolto::«{q['title']}» somiglia a «{twin}»")
            continue
        kept.append(q)
        seen.append(q["title"])
    published = [p["title"] for p in posted if (p.get("kind") or "research") == "research"]
    if not kept or not published:
        return kept
    lines = "\n".join(f"{i}: {q['title']} — {q.get('takeaway', '')}" for i, q in enumerate(kept))
    prompt = ("You curate an educational Instagram page on clinical research methodology. Below are the posts already "
              "published and the candidate posts in the queue. List the candidates that teach essentially the SAME "
              "concept as a published post or as an EARLIER candidate (same main idea, even if worded differently). "
              "Different aspects of the same broad topic are NOT duplicates.\n\nPublished:\n- "
              + "\n- ".join(published) + f"\n\nCandidates:\n{lines}")
    try:
        dups = content.groq_json(prompt, DUP_SCHEMA, 0.0, task="controllo doppioni").get("duplicates", [])
    except Exception as e:
        print(f"Controllo doppioni non riuscito ({e}): la coda resta com'è.")
        return kept
    drop = set()
    for d in dups:
        i = d.get("index")
        if isinstance(i, int) and 0 <= i < len(kept):
            drop.add(i)
            print(f"::notice title=Post doppione tolto::«{kept[i]['title']}» ripete «{d.get('same_as', '')}»")
    return [q for i, q in enumerate(kept) if i not in drop]


def pick_next(queue, posted):
    """Prende il primo post della coda, alternando le fonti quando possibile."""
    last_source = posted[-1]["source"] if posted else None
    for item in queue:
        if item.get("source") != last_source:
            return item
    return queue[0]


def build_caption(post):
    tags, seen = [], set()
    kind = post.get("kind")
    if kind == "grant":                      # bandi: #ResearchFunding e #ClinicalResearch, poi i 3 più specifici
        pool = ["#ResearchFunding", "#ClinicalResearch"] + [t for t in post.get("hashtags", []) if t.lower() != "#grantopportunity"]
    elif kind in ("positions", "announcement"):
        pool = post.get("hashtags", []) + CONFIG.get("fixed_hashtags", [])
    else:                                    # metodologia: i 2 fissi e i 3 specifici del tema
        pool = CONFIG.get("fixed_hashtags", []) + post.get("hashtags", [])
    for t in pool:
        if t.lower() not in seen:
            seen.add(t.lower())
            tags.append(t)
    refs = post.get("references") or []
    ref_block = ("\n\nReferences:\n" + "\n".join(f"• {r}" for r in refs)) if refs else ""
    tail = f"{ref_block}\n\n{' '.join(tags[:MAX_HASHTAGS])}"
    head = f"{post['title']}\n\n{post['caption']}"
    room = MAX_CAPTION_CHARS - len(tail)          # le reference e gli hashtag non vengono mai tagliati
    if len(head) > room:
        head = head[:max(0, room - 1)].rsplit(" ", 1)[0] + "…"
    return (head + tail).strip()


def ig(method, path, **params):
    params["access_token"] = os.environ["IG_ACCESS_TOKEN"]
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{path}"
    r = requests.post(url, data=params, timeout=60) if method == "POST" else requests.get(url, params=params, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Errore API Instagram {r.status_code}: {r.text}")
    return r.json()


def wait_ready(container_id):
    for _ in range(36):
        status = ig("GET", container_id, fields="status_code").get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram ha rifiutato il contenuto (stato {status})")
        time.sleep(5)
    raise RuntimeError("Instagram non ha elaborato il contenuto in tempo")


ALT_OK = {"instagram": True, "facebook": True}


def alt_texts(post, n):
    """Testo alternativo di ogni slide (ricerca di Instagram e accessibilità): titolo, poi i titoli delle slide."""
    title = post.get("title", "")
    heads = [f"{s.get('heading', '')}: {s.get('body', '')}" for s in post.get("slides", [])] + \
        [f"{j.get('type', '')}: {j.get('title', '')}, {j.get('institution', '')}" for j in post.get("jobs", [])]
    out = []
    for i in range(n):
        txt = title if i == 0 else (heads[i - 1] if i - 1 < len(heads) else f"{title} (slide {i + 1} of {n})")
        out.append(f"Clinical Research Chaos – {txt}"[:900])
    return out


def publish_carousel(image_urls, caption, alts=None):
    user = os.environ["IG_USER_ID"]
    children = []
    for i, url in enumerate(image_urls):
        params = {"image_url": url, "is_carousel_item": "true"}
        if alts and ALT_OK["instagram"]:
            try:
                cid = ig("POST", f"{user}/media", **params, alt_text=alts[i])["id"]
            except RuntimeError as e:            # campo non accettato: si continua senza, per tutto il giro
                ALT_OK["instagram"] = False
                print(f"::notice title=Testo alternativo::Instagram non lo accetta ({str(e)[:150]}): pubblico senza")
                cid = ig("POST", f"{user}/media", **params)["id"]
        else:
            cid = ig("POST", f"{user}/media", **params)["id"]
        wait_ready(cid)
        children.append(cid)
    carousel = ig("POST", f"{user}/media", media_type="CAROUSEL",
                  children=",".join(children), caption=caption)["id"]
    wait_ready(carousel)
    return ig("POST", f"{user}/media_publish", creation_id=carousel)["id"]


def facebook_caption(caption, kind=None):
    """Su Facebook i link sono cliccabili: «link in bio» diventa l'indirizzo della pagina dei bandi
    (o di quella delle posizioni accademiche)."""
    page = CONFIG.get("links_page_url")
    if page and kind == "positions":
        page = page.rstrip("/") + "/positions.html"
    if page:
        caption = (caption.replace("Clickable link in bio, with all open calls we have shared.", f"All open calls: {page}")
                          .replace("All open calls, grouped by programme: link in bio.", f"All open calls, grouped by region and programme: {page}")
                          .replace("link in bio", page))
    return caption


def publish_facebook(image_urls, caption, kind=None, alts=None):
    """Pubblica le stesse slide sulla Pagina Facebook come un unico post con più foto. Restituisce l'id del post."""
    page_id = os.environ.get("FB_PAGE_ID")
    token = os.environ.get("FB_PAGE_TOKEN") or os.environ["IG_ACCESS_TOKEN"]
    base = f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}"
    media = []
    for i, url in enumerate(image_urls):
        data = {"url": url, "published": "false", "access_token": token}
        if alts and ALT_OK["facebook"]:
            r = requests.post(f"{base}/photos", data={**data, "alt_text_custom": alts[i]}, timeout=90)
            if not r.ok:                     # campo non accettato: si riprova senza, per tutto il giro
                ALT_OK["facebook"] = False
                print(f"::notice title=Testo alternativo::Facebook non lo accetta ({r.text[:150]}): pubblico senza")
                r = requests.post(f"{base}/photos", data=data, timeout=90)
        else:
            r = requests.post(f"{base}/photos", data=data, timeout=90)
        if not r.ok:
            raise RuntimeError(f"Errore Facebook (foto) {r.status_code}: {r.text[:300]}")
        media.append(r.json()["id"])
    data = {"message": facebook_caption(caption, kind), "access_token": token}
    for i, mid in enumerate(media):
        data[f"attached_media[{i}]"] = json.dumps({"media_fbid": mid})
    r = requests.post(f"{base}/feed", data=data, timeout=90)
    if not r.ok:
        raise RuntimeError(f"Errore Facebook (post) {r.status_code}: {r.text[:300]}")
    return r.json().get("id")


def facebook_text(post, caption, kind=None, link=""):
    """Facebook: testo lungo. Metodologia: didascalia, punti chiave per esteso, messaggio da ricordare, fonti e link.
    Bandi, posizioni e annunci: la didascalia con i link cliccabili."""
    if kind not in (None, "research"):
        return facebook_caption(caption, kind)
    import re as _re
    tags = _re.findall(r"#\w+", caption)
    body = _re.sub(r"(\s*#\w+)+\s*$", "", caption).strip()
    body = body.replace("link in bio", link or CONFIG.get("links_page_url", ""))
    points = "\n".join(f"{i}. {s['heading']}: {s['body']}" for i, s in enumerate(post.get("slides", []), 1))
    refs = "\n".join(f"- {r}" for r in (post.get("references") or [])[:3])
    parts = [body, f"Key points:\n{points}" if points else "", f"Takeaway: {post['takeaway']}" if post.get("takeaway") else "",
             f"References:\n{refs}" if refs else "", f"All our methodology carousels, with references: {link}" if link else "",
             " ".join(tags[:5])]
    return "\n\n".join(x for x in parts if x)[:6000]


def publish_facebook_single(image_url, message):
    """Facebook: un'immagine con testo lungo (per il pubblico della Pagina rende più del carosello). Restituisce l'id del post."""
    page_id = os.environ.get("FB_PAGE_ID")
    token = os.environ.get("FB_PAGE_TOKEN") or os.environ["IG_ACCESS_TOKEN"]
    r = requests.post(f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}/photos",
                      data={"url": image_url, "caption": message, "published": "true", "access_token": token}, timeout=90)
    if not r.ok:
        raise RuntimeError(f"Errore Facebook (foto) {r.status_code}: {r.text[:300]}")
    j = r.json()
    return j.get("post_id") or j.get("id")


def wait_until_public(url):
    for _ in range(12):
        try:
            if requests.head(url, timeout=15).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(5)
    raise RuntimeError(f"Immagine non raggiungibile: {url}")


def publish_reel(video_path, caption):
    """Reel su Instagram con caricamento diretto del video (upload «resumable»): nessun hosting esterno."""
    user, token = os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"]
    c = ig("POST", f"{user}/media", media_type="REELS", upload_type="resumable", caption=caption, share_to_feed="true")
    data = Path(video_path).read_bytes()
    r = requests.post(c.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{GRAPH_VERSION}/{c['id']}",
                      headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data))},
                      data=data, timeout=300)
    if not r.ok:
        raise RuntimeError(f"Caricamento del video rifiutato {r.status_code}: {r.text[:300]}")
    for _ in range(60):                        # l'elaborazione dei video può richiedere qualche minuto
        status = ig("GET", c["id"], fields="status_code").get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram ha rifiutato il video (stato {status})")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram non ha elaborato il video in tempo")
    return ig("POST", f"{user}/media_publish", creation_id=c["id"])["id"]


REEL_KINDS = {   # tipo di carosello → musica (cartella Drive «Musica/…»), testo e hashtag del reel
    "research": {"music": "Classica",
                 "text": "The key points in about {seconds} seconds. The full carousel, with references, is on our profile: "
                         "save it for your next protocol.",
                 "tags": ["#ResearchTips", "#EvidenceBasedPractice"]},
    "grant": {"music": "Rock",
              "text": "A funding call worth knowing, in {seconds} seconds. Official call and all open calls, checked on the "
                      "official text: link in bio.",
              "tags": ["#ResearchFunding", "#GrantOpportunity"]},
    "positions": {"music": "Funky",
                  "text": "New academic positions in {seconds} seconds. All positions, with deadlines and links: link in bio.",
                  "tags": ["#AcademicJobs", "#Postdoc", "#PhDPosition"]},
    "announcement": {"music": "Aziendale|Speciale|Funky",
                     "text": "More on our profile and at the link in bio.",
                     "tags": ["#ResearchCommunity"]},
}


def reel_spec(kind, p):
    """Copione del reel per metodologia, bandi e posizioni (None: si usano le slide del carosello)."""
    import reels
    try:
        if kind == "research":
            m = load(ROOT / "methodology.json", [])
            items = m if isinstance(m, list) else list(m.values())
            entry = next((x for x in items if x.get("id") == p.get("id")), None)
            return reels.research_spec(entry, CONFIG) if entry and entry.get("points") else None
        if kind == "grant":
            import grants
            return reels.grant_spec(p, grants.load_verified().get(p.get("grant_id"), {}), CONFIG)
        if kind == "positions":
            import positions
            return reels.positions_spec(p, positions.load_archive(), CONFIG)
    except Exception as e:
        print(f"::warning title=Copione del reel::{kind}: {str(e)[:200]} (uso le slide del carosello)")
    return None


def reel_words(kind, p, total):
    """Parole da leggere in ogni slide interna del carosello (stima dai testi salvati), per dare a ogni slide
    del reel il tempo di lettura giusto."""
    n = max(1, total - 2)
    if kind == "research":
        try:
            m = load(ROOT / "methodology.json", [])
            items = m if isinstance(m, list) else list(m.values())
            entry = next((x for x in items if x.get("id") == p.get("id")), None)
        except Exception:
            entry = None
        if entry and entry.get("points"):
            counts = [len(f"{pt.get('heading', '')} {pt.get('body', '')}".split()) for pt in entry["points"]]
            avg = sum(counts) / len(counts)
            return [avg] * n                 # le slide extra (regola, invito) hanno meno testo: la media basta
        return [32] * n
    if kind == "positions":
        return [55] * n                      # scheda: tipo, titolo, ente, luogo, scadenza, sintesi
    if kind == "grant":
        return [45] * n                      # due slide di testo e la scheda con i dati del bando
    return [35] * n


def reel_run(posted):
    """Reel da un carosello già pubblicato e non ancora trasformato in reel: metodologia (ultimi 21 giorni), bando,
    posizioni o post speciale (ultimi 10 giorni), a rotazione tra i tipi. REEL_SOURCE: latest (rotazione),
    research, grant, positions, special (carosello speciale) oppure announcement (reel di reel_announcement.json)."""
    import reels
    source = (os.environ.get("REEL_SOURCE") or "latest").strip().lower()
    if source == "announcement":
        return reel_announcement_run(posted)
    force = {"special": "announcement"}.get(source, source) if source != "latest" else None
    done = {p.get("reel_of") for p in posted if p.get("kind") == "reel"}
    now = datetime.now(timezone.utc).timestamp()
    latest = {}                      # per ogni tipo, il carosello più recente non ancora trasformato in reel
    for p in reversed(posted):
        kind = p.get("kind") or "research"
        if kind not in REEL_KINDS or kind in latest or p.get("id") in done or not p.get("time") or force not in (None, kind):
            continue
        if datetime.fromisoformat(p["time"]).timestamp() < now - (21 if kind == "research" else 10) * 86400:
            continue                 # bandi, posizioni e speciali: solo se usciti negli ultimi 10 giorni
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in p["id"])
        folder = IMAGES_DIR / f"{p['date']}-{safe}"
        slides = sorted(folder.glob("slide-*.jpg"), key=lambda x: int(x.stem.split("-")[1]))
        if len(slides) >= 3:
            latest[kind] = (p, slides)
    if not latest:
        print("::notice title=Reel::nessun carosello recente da trasformare in reel")
        return
    # a rotazione: il tipo che non ha un reel da più tempo (a parità, prima la metodologia)
    last_reel = {}
    by_id = {p.get("id"): (p.get("kind") or "research") for p in posted}
    for r in posted:
        if r.get("kind") == "reel" and r.get("reel_of"):
            last_reel[by_id.get(r["reel_of"], "research")] = r.get("time", "")
    kind = min(latest, key=lambda k: (last_reel.get(k, ""), list(REEL_KINDS).index(k)))
    p, slides = latest[kind]
    style = REEL_KINDS[kind]
    PREVIEW_DIR.mkdir(exist_ok=True)
    video = PREVIEW_DIR / "reel.mp4"
    accent = CONFIG.get("grant_accent", "#FFB547") if kind == "grant" else CONFIG["colors"]["accent"]
    spec = reel_spec(kind, p)
    if spec:                         # reel nativo e breve, scritto per il tipo di post (20–30 secondi)
        seconds = reels.build_story_reel(spec, video, CONFIG, mood=style["music"])
    else:                            # post speciali: le slide del carosello, il tempo di leggerle (max 40 s)
        lengths = reels.reading_lengths(len(slides), reel_words(kind, p, len(slides)), cap=40.0)
        seconds = reels.build_reel(slides, video, CONFIG, accent=accent, mood=style["music"], per_slide=lengths)
    caption = (f"{p['title']}\n\n" + style["text"].format(seconds=round(seconds)) + "\n\n"
               + " ".join(list(dict.fromkeys(style["tags"] + CONFIG.get("fixed_hashtags", [])))[:MAX_HASHTAGS]))
    print(f"Reel da: {p['title']} ({kind}, musica {style['music']}, {len(slides)} slide, {seconds} s)\n--- Didascalia ---\n{caption}")
    if DRY_RUN:
        (PREVIEW_DIR / "reel-caption.txt").write_text(caption, encoding="utf-8")
        print("Modalità prova: reel non pubblicato. Anteprima nell'artifact 'preview'.")
        return
    try:
        media_id = publish_reel(video, caption)
    except Exception as e:
        msg = str(e)[:400]
        print(f"::error title=Reel non pubblicato::{msg}")
        notify("Reel non pubblicato su Instagram", f"Il reel di «{p['title']}» non è uscito: {msg}")
        sys.exit(1)
    print(f"::notice title=Reel pubblicato::{p['title']} | id {media_id}")
    posted.append({"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                   "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "id": f"reel-{p['id']}"[:60], "title": p["title"], "source": p.get("source", ""),
                   "kind": "reel", "reel_of": p["id"], "media_id": media_id, "seconds": seconds})
    save(POSTED_FILE, posted)
    commit_and_push([POSTED_FILE.name], "Reel pubblicato")


def reel_announcement_run(posted):
    """Reel speciale scritto a mano in reel_announcement.json, pubblicato una sola volta."""
    import reels
    spec = load(ROOT / "reel_announcement.json", None)
    if not spec or any(p.get("id") == spec.get("id") for p in posted):
        print("::notice title=Reel::nessun reel speciale nuovo da pubblicare")
        return
    PREVIEW_DIR.mkdir(exist_ok=True)
    video = PREVIEW_DIR / "reel.mp4"
    seconds = reels.build_story_reel(spec, video, CONFIG)       # musica: Musica/Aziendale (poi Speciale, Funky)
    caption = f"{spec['caption']}\n\n{' '.join(spec.get('hashtags', []))}".strip()
    print(f"Reel speciale: {spec['id']} ({seconds} s)\n--- Didascalia ---\n{caption}")
    if DRY_RUN:
        (PREVIEW_DIR / "reel-caption.txt").write_text(caption, encoding="utf-8")
        print("Modalità prova: reel non pubblicato. Anteprima nell'artifact 'preview'.")
        return
    try:
        media_id = publish_reel(video, caption)
    except Exception as e:
        msg = str(e)[:400]
        print(f"::error title=Reel non pubblicato::{msg}")
        notify("Reel non pubblicato su Instagram", f"Il reel speciale {spec['id']} non è uscito: {msg}")
        sys.exit(1)
    print(f"::notice title=Reel pubblicato::{spec['id']} | id {media_id}")
    posted.append({"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                   "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "id": spec["id"], "title": spec["slides"][0].get("title", ""), "source": "reel_announcement.json",
                   "kind": "reel", "media_id": media_id, "seconds": seconds})
    save(POSTED_FILE, posted)
    commit_and_push([POSTED_FILE.name], "Reel speciale pubblicato")


def main():
    posted = load(POSTED_FILE, [])
    if (os.environ.get("POST_TYPE") or "").strip().lower() == "reel":
        if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and not CONFIG.get("reels_auto", False):
            print("Reel automatici disattivati (config: reels_auto = false): salto.")
            return
        same = [p for p in posted if p.get("kind") == "reel" and p.get("time")]
        if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and same and (
                datetime.now(timezone.utc) - datetime.fromisoformat(same[-1]["time"])).total_seconds() < 48 * 3600:
            print("Ultimo reel pubblicato da meno di 48 ore: salto.")
            return
        return reel_run(posted)
    drive = drive_service()
    queue = load(QUEUE_FILE, [])

    # Due post al giorno, in due run separati: un bando (POST_TYPE=grant) e un post di metodologia (research).
    post_type = (os.environ.get("POST_TYPE") or "research").strip().lower()
    kind = post_type if post_type in ("grant", "positions", "announcement") else "research"
    # Il run pianificato salta se un post dello stesso tipo è uscito nelle ultime 12 ore (es. dopo un lancio manuale).
    same = [p for p in posted if (p.get("kind") or "research") == kind and p.get("time")]
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and same:
        hours = (datetime.now(timezone.utc) - datetime.fromisoformat(same[-1]["time"])).total_seconds() / 3600
        if hours < (72 if kind == "positions" else 12):
            print(f"Ultimo post di tipo {kind} pubblicato {hours:.1f} ore fa: salto.")
            return

    if kind == "announcement":
        # post scritto a mano in announcement.json, pubblicato una sola volta
        post = load(ROOT / "announcement.json", None)
        if not post or any(p.get("id") == post.get("id") for p in posted):
            print("::notice title=Annuncio::nessun annuncio nuovo da pubblicare")
            return
        post["closing_cta"] = tuple(post.get("closing_cta") or ())
        files_waiting = 1
    elif kind == "positions":
        files_waiting = 1
        n = os.environ.get("POSITIONS_PER_POST")
        cfg = {**CONFIG, "positions_per_post": int(n), "positions_min_per_post": 1} if n else CONFIG
        post = positions.weekly_post(positions.load_archive(), posted, cfg)
        if post is None:
            print("::notice title=Nessuna raccolta di posizioni::Meno di 3 posizioni nuove verificate: questa settimana niente post.")
            return
    elif kind == "grant":
        files_waiting = 1                      # il run dei bandi non legge Drive e non avvisa sulla coda
        post = grants.next_grant_post(posted, CONFIG)
        if post is None:
            print("::notice title=Nessun bando oggi::Nessun bando verificato con abbastanza anticipo: oggi niente post bando.")
            return
    else:
        files_waiting = ingest(drive, queue)
        before = len(queue)
        queue[:] = drop_repeats(queue, posted)
        if len(queue) != before and not DRY_RUN:
            save(QUEUE_FILE, queue)
            commit_and_push([QUEUE_FILE.name], "Coda: tolti i post doppioni")
        if not queue:
            notify("Coda vuota: il bot è in pausa",
                   "Non ci sono post da pubblicare. Aggiungi nuovo materiale nella cartella Drive.")
            print("Coda vuota.")
            sys.exit(1)
        post = pick_next(queue, posted)
    slides = cards.render_carousel(post, CONFIG)
    caption = build_caption(post)
    print(f"\nPost scelto: {post['title']}  (fonte: {post['source']}, {post.get('source_hint', '')})")
    print(f"--- Didascalia ---\n{caption}\n")

    if DRY_RUN:
        PREVIEW_DIR.mkdir(exist_ok=True)
        for i, img in enumerate(slides, start=1):
            (PREVIEW_DIR / f"slide-{i}.jpg").write_bytes(img)
        (PREVIEW_DIR / "caption.txt").write_text(caption, encoding="utf-8")
        # anteprima dei formati per social: Facebook (immagine singola + testo lungo), Bluesky e Threads (testo breve)
        import social
        plink = grants.site_url(CONFIG, {"grant": f"calls#{grants.card_anchor(post.get('grant_id', ''))}", "positions": "positions",
                                         "research": f"methodology#m-{post.get('id', '')}"}.get(post.get("kind") or "research", ""))
        if kind == "research":
            (PREVIEW_DIR / "facebook.jpg").write_bytes(cards.facebook_single(post, CONFIG))
        (PREVIEW_DIR / "bluesky.jpg").write_bytes(cards.single_cover(post, CONFIG))
        (PREVIEW_DIR / "facebook.txt").write_text(facebook_text(post, caption, post.get("kind"), plink), encoding="utf-8")
        (PREVIEW_DIR / "bluesky.txt").write_text(social.short_text({**post, "caption": caption}, plink, 300), encoding="utf-8")
        (PREVIEW_DIR / "threads.txt").write_text(social.short_text({**post, "caption": caption}, plink, 500), encoding="utf-8")
        (PREVIEW_DIR / "queue.json").write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
        print("Modalità prova: niente pubblicato. Anteprima nell'artifact 'preview'.")
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in post["id"])
    folder = IMAGES_DIR / f"{today}-{safe_id}"
    folder.mkdir(parents=True, exist_ok=True)
    rel_paths = []
    for i, img in enumerate(slides, start=1):
        path = folder / f"slide-{i}.jpg"
        path.write_bytes(img)
        rel_paths.append(path.relative_to(ROOT).as_posix())
    fb_single = CONFIG.get("facebook_format", "single") == "single"
    fb_rel = None
    if fb_single and kind == "research":          # metodologia: immagine riassuntiva; bandi e posizioni: la copertina
        fb_path = folder / "facebook.jpg"
        fb_path.write_bytes(cards.facebook_single(post, CONFIG))
        fb_rel = fb_path.relative_to(ROOT).as_posix()
    # immagine singola (Bluesky e Facebook a foto singola): la copertina senza «Swipe» e senza numero di pagina
    single_path = folder / "cover-single.jpg"
    single_path.write_bytes(cards.single_cover(post, CONFIG))
    single_rel = single_path.relative_to(ROOT).as_posix()
    if fb_single and not fb_rel:
        fb_rel = single_rel
    sha = commit_and_push(rel_paths + list(dict.fromkeys([single_rel] + ([fb_rel] if fb_rel else []))), f"Slide del {today}")
    base = f"https://raw.githubusercontent.com/{os.environ['GITHUB_REPOSITORY']}/{sha}/"
    urls = [base + p for p in rel_paths]
    fb_url = base + fb_rel if fb_rel else urls[0]
    try:
        for u in urls:
            wait_until_public(u)
    except RuntimeError as e:
        print(f"::error title=Slide non raggiungibili::{e}")
        sys.exit(1)

    try:
        media_id = publish_carousel(urls, caption, alt_texts(post, len(urls)))
    except Exception as e:
        msg = str(e)[:400]
        print(f"::error title=Instagram non pubblicato::{msg}")
        notify("Post non pubblicato su Instagram", f"Il post «{post['title']}» non è uscito: {msg}")
        sys.exit(1)
    print(f"Pubblicato su Instagram! id={media_id}")

    import social
    kind_link = {"grant": f"calls#{grants.card_anchor(post.get('grant_id', ''))}", "positions": "positions",
                 "research": f"methodology#m-{post['id']}"}.get(post.get("kind") or "research", "")
    link = grants.site_url(CONFIG, kind_link)
    fb_id = None
    if CONFIG.get("facebook", True) and os.environ.get("FB_PAGE_ID"):
        try:   # un errore su Facebook non blocca il post Instagram già uscito
            if fb_single and post.get("kind") != "announcement":
                fb_id = publish_facebook_single(fb_url, facebook_text(post, caption, post.get("kind"), link))
            else:
                fb_id = publish_facebook(urls, caption, post.get("kind"), alt_texts(post, len(urls)))
            print(f"Pubblicato su Facebook! id={fb_id}")
        except Exception as e:
            print(f"::warning title=Facebook non pubblicato::{str(e)[:300]}")
            notify("Post non pubblicato su Facebook", f"Il post «{post['title']}» è uscito su Instagram ma non su Facebook: {e}")

    # Bluesky (prima slide + link) e Threads (carosello + testo breve), se i secret ci sono: un errore non blocca nulla
    bsky_uri = threads_id = None
    if social.bluesky_enabled():
        try:
            n_bsky = int(CONFIG.get("bluesky_images", 1))
            bsky_imgs = [single_path] if n_bsky == 1 else [ROOT / p for p in rel_paths]
            bsky_uri = social.publish_bluesky(bsky_imgs, {**post, "caption": caption}, link, max_images=n_bsky)
            print(f"::notice title=Bluesky::pubblicato {bsky_uri}")
        except Exception as e:
            print(f"::warning title=Bluesky non pubblicato::{str(e)[:300]}")
    if social.threads_enabled():
        try:
            threads_id = social.publish_threads(urls, {**post, "caption": caption}, link)
            print(f"::notice title=Threads::pubblicato {threads_id}")
        except Exception as e:
            print(f"::warning title=Threads non pubblicato::{str(e)[:300]}")

    queue = [q for q in queue if q["id"] != post["id"]]
    posted.append({"date": today, "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "id": post["id"], "title": post["title"],
                   "source": post["source"], "media_id": media_id, "facebook_id": fb_id,
                   **({"bluesky_uri": bsky_uri} if bsky_uri else {}), **({"threads_id": threads_id} if threads_id else {}),
                   **({"kind": "positions", "position_ids": post["position_ids"]} if post.get("kind") == "positions" else {}),
                   **({"kind": "announcement"} if post.get("kind") == "announcement" else {}),
                   **({"kind": "grant", "grant_id": post["grant_id"], "url": post["url"],
                       "deadline": post["deadline_iso"], "funder": post.get("funder", ""),
                       "summary": post.get("summary", ""), "italy_evidence": post.get("italy_evidence", ""),
                       "official_source": post.get("official_source", ""), "grant_title": post.get("official_title", "")}
                      if post.get("kind") == "grant" else {})})
    save(QUEUE_FILE, queue)
    save(POSTED_FILE, posted)
    photos = [sl["pixabay_id"] for sl in post.get("slides", []) if sl.get("pixabay_id")] + \
        ([post["cover_pixabay_id"]] if post.get("cover_pixabay_id") else [])
    import images
    for pid in photos:                       # foto Pixabay usate: mai più riproposte
        images.mark_used(pid)
    if kind == "research":
        import methodology
        methodology.add(post, today, IMAGES_DIR)
    # pagina «link in bio»: rigenerata a ogni post, così i bandi scaduti spariscono da soli
    PAGE_FILE.parent.mkdir(exist_ok=True)
    commit_and_push([QUEUE_FILE.name, POSTED_FILE.name, "methodology.json"] + (["pixabay_used.json"] if photos else []),
                    f"Post del {today}")
    if post.get("kind") == "positions":
        try:
            update_positions(posted, verify_limit=0)
        except Exception as e:
            print(f"::warning title=Pagina posizioni non aggiornata::{e}")
    try:
        update_grants(posted, verify_limit=0)      # la pagina segna subito il bando come «on Instagram»
    except Exception as e:
        print(f"::warning title=Pagina bandi non aggiornata::{e}")

    if len(queue) <= int(CONFIG.get("low_queue_warning", 5)) and files_waiting == 0:
        notify("Post in esaurimento",
               f"Restano {len(queue)} post in coda. Aggiungi nuovo materiale nella cartella Drive.")


def check_token():
    """Scadenza e permessi del token Instagram (senza mostrarlo). Avvisa via issue se scade entro 14 giorni."""
    token = os.environ["IG_ACCESS_TOKEN"]
    r = requests.get(f"https://graph.facebook.com/{GRAPH_VERSION}/debug_token",
                     params={"input_token": token, "access_token": token}, timeout=30)
    data = r.json().get("data", {}) if r.ok else {}
    if not data:
        print(f"::error title=Token Instagram::Controllo non riuscito ({r.status_code}): {r.text[:200]}")
        notify("Token Instagram non valido", "Il controllo del token non è riuscito: probabilmente è scaduto o revocato.")
        sys.exit(1)
    def when(ts):
        return "mai" if not ts else datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
    exp, access = data.get("expires_at", 0), data.get("data_access_expires_at", 0)
    scopes = ", ".join(sorted(data.get("scopes", [])))
    print(f"::notice title=Token Instagram::valido: {data.get('is_valid')} | tipo: {data.get('type')} | "
          f"scade: {when(exp)} | accesso ai dati fino al: {when(access)} | permessi: {scopes}")
    if os.environ.get("FB_PAGE_ID"):
        missing = [p for p in ("pages_manage_posts", "pages_read_engagement") if p not in data.get("scopes", [])]
        print(f"::notice title=Pagina Facebook::ID impostato; permessi mancanti: {', '.join(missing) or 'nessuno'}")
        if os.environ.get("FB_TEST") == "true":
            # prova reale: carica una slide già pubblicata come foto NON pubblicata e la cancella subito
            page, fb_token = os.environ["FB_PAGE_ID"], os.environ.get("FB_PAGE_TOKEN") or token
            sample = next(IMAGES_DIR.glob("*/slide-1.jpg"), None)
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
            url = f"https://raw.githubusercontent.com/{os.environ['GITHUB_REPOSITORY']}/{sha}/{sample.relative_to(ROOT).as_posix()}"
            r = requests.post(f"https://graph.facebook.com/{GRAPH_VERSION}/{page}/photos",
                              data={"url": url, "published": "false", "access_token": fb_token}, timeout=90)
            if r.ok:
                pid = r.json()["id"]
                d = requests.delete(f"https://graph.facebook.com/{GRAPH_VERSION}/{pid}", params={"access_token": fb_token}, timeout=30)
                print(f"::notice title=Prova Facebook::foto caricata (non pubblicata) e {'cancellata' if d.ok else 'NON cancellata: ' + d.text[:120]}")
            else:
                print(f"::error title=Prova Facebook::caricamento rifiutato {r.status_code}: {r.text[:250]}")
    days = [(t - time.time()) / 86400 for t in (exp, access) if t]
    if not data.get("is_valid") or (days and min(days) < 14):
        notify("Il token Instagram sta per scadere",
               f"Scadenza: {when(exp)}; accesso ai dati fino al {when(access)}. Genera un nuovo token e aggiorna il secret IG_ACCESS_TOKEN.")


POSITIONS_PAGE = ROOT / "docs" / "positions.html"


def update_positions(posted=None, verify_limit=None):
    """Raccoglie e verifica le posizioni accademiche nuove e rigenera la pagina «Academic positions»."""
    posted = posted if posted is not None else load(POSTED_FILE, [])
    archive = positions.load_archive()
    if verify_limit != 0:
        positions.refresh(archive, limit=int(verify_limit or CONFIG.get("positions_verify_per_run", 25)))
        save(ROOT / positions.ARCHIVE_FILE, archive)
    POSITIONS_PAGE.parent.mkdir(exist_ok=True)
    POSITIONS_PAGE.write_text(grants.add_decor(positions.build_page(archive, posted, CONFIG)), encoding="utf-8")
    write_job_pages(archive)
    (ROOT / "docs" / "feed-positions.xml").write_text(positions.positions_feed(archive, CONFIG), encoding="utf-8")
    n = len(positions.active(archive))
    print(f"::notice title=Pagina posizioni::{n} posizioni aperte in pagina")
    write_home()
    before = _head()
    if commit_and_push([positions.ARCHIVE_FILE, positions.STATUS_FILE, "docs"],
                       "Posizioni accademiche verificate e pagina aggiornata") != before:
        trigger_deploy()                 # solo se qualcosa è cambiato: le build di Cloudflare sono limitate


JOBS_DIR = ROOT / "docs" / "jobs"


def write_job_pages(archive):
    """Una pagina per ogni posizione aperta (con i dati per Google Jobs); le pagine delle posizioni chiuse si cancellano."""
    pages = positions.job_pages(archive, CONFIG)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    for f in JOBS_DIR.glob("*.html"):
        if f.name not in pages:
            f.unlink()
    for name, html in pages.items():
        (JOBS_DIR / name).write_text(grants.add_decor(html), encoding="utf-8")


def write_sitemap():
    """sitemap.xml e robots.txt, perché Google trovi tutte le pagine (anche quelle delle singole posizioni)."""
    from xml.sax.saxutils import escape as xesc
    today = datetime.now().date().isoformat()
    paths = ["", "calls", "positions", "methodology", "feedback", "rss"] + sorted("jobs/" + f.stem for f in JOBS_DIR.glob("*.html"))
    urls = "".join(f"  <url><loc>{xesc(grants.site_url(CONFIG, p))}</loc><lastmod>{today}</lastmod></url>\n" for p in paths)
    (ROOT / "docs" / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n',
        encoding="utf-8")
    (ROOT / "docs" / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {grants.site_url(CONFIG, 'sitemap.xml')}\n",
                                              encoding="utf-8")


def write_home():
    """Pagina iniziale con i conteggi letti dalle due pagine (bandi e posizioni)."""
    import re as _re
    calls = PAGE_FILE.read_text(encoding="utf-8") if PAGE_FILE.exists() else ""
    jobs = POSITIONS_PAGE.read_text(encoding="utf-8") if POSITIONS_PAGE.exists() else ""
    n_calls = calls.count("Official call &rarr;")
    m = _re.search(r'Open to Italy <b>(\d+)</b>', calls)
    n_positions = jobs.count("Advertisement &rarr;")
    import methodology
    methods = methodology.load()
    (ROOT / "docs" / "methodology.html").write_text(grants.add_decor(methodology.build_page(methods, CONFIG)), encoding="utf-8")
    import feedback
    (ROOT / "docs" / "feedback.html").write_text(grants.add_decor(feedback.build_page(CONFIG)), encoding="utf-8")
    (ROOT / "docs" / "rss.html").write_text(grants.add_decor(feedback.build_feeds_page(CONFIG)), encoding="utf-8")
    HOME_FILE.write_text(grants.add_decor(grants.build_home(n_calls, int(m.group(1)) if m else 0, n_positions, CONFIG,
                                                            n_methods=sum(1 for e in methods.values() if not e.get("duplicate_of")))),
                         encoding="utf-8")
    write_sitemap()
    return HOME_FILE.relative_to(ROOT).as_posix()


def trigger_deploy():
    """Chiede a Cloudflare Pages di ripubblicare il sito (deploy hook nel secret CF_DEPLOY_HOOK)."""
    hook = os.environ.get("CF_DEPLOY_HOOK")
    if not hook or DRY_RUN:
        return
    try:
        r = requests.post(hook, timeout=30)
        print(f"::notice title=Sito::ripubblicazione richiesta a Cloudflare ({r.status_code})")
    except requests.RequestException as e:
        print(f"::warning title=Sito::deploy hook non raggiungibile: {e}")


def update_grants(posted=None, verify_limit=None):
    """Verifica sul testo ufficiale i bandi nuovi di GrantFinder e rigenera la pagina «link in bio»."""
    posted = posted if posted is not None else load(POSTED_FILE, [])
    grants_list = grants.fetch(CONFIG)
    verified = grants.load_verified()
    if verify_limit != 0:
        grants.refresh_verified(grants_list, verified, CONFIG, limit=verify_limit)
        save(ROOT / grants.VERIFIED_FILE, verified)
    PAGE_FILE.parent.mkdir(exist_ok=True)
    PAGE_FILE.write_text(grants.add_decor(grants.build_page(grants_list, verified, posted, CONFIG)), encoding="utf-8")
    (ROOT / "docs" / "feed-calls.xml").write_text(grants.calls_feed(grants_list, verified, CONFIG), encoding="utf-8")
    entries = grants.page_entries(grants_list, verified)
    pending = sum(1 for g in grants_list if g["id"] not in verified)
    print(f"::notice title=Pagina bandi::{len(entries)} bandi in pagina, {pending} ancora da verificare")
    write_home()
    before = _head()
    if commit_and_push([grants.VERIFIED_FILE, "docs"], "Bandi verificati e pagina aggiornata") != before:
        trigger_deploy()                 # solo se qualcosa è cambiato: le build di Cloudflare sono limitate


def recheck_references(drive, queue, skip=()):
    """Ricontrolla le reference dei post in coda con le regole attuali (materiale + Crossref), senza Gemini."""
    sources = {x["name"]: x for x in load(SOURCES_FILE, [])}
    for name in {p["source"] for p in queue if p.get("references") and p["source"] not in skip}:
        src = sources.get(name)
        if not src:
            continue
        try:
            f = drive.files().get(fileId=src["drive_id"], fields="id, name, mimeType", supportsAllDrives=True).execute()
            material = content.material_text(content.material_part(drive, f))
        except Exception as e:
            print(f"::warning title=Reference non ricontrollate::{name}: {str(e)[:200]}")
            continue
        before = after = 0
        for p in queue:
            if p["source"] != name or not p.get("references"):
                continue
            before += len(p["references"])
            p["references"] = content.verified_references(p["references"], material)
            after += len(p["references"])
            for sl in p["slides"]:
                sl["source"] = content._source_ok(sl.get("source"), p["references"])
        print(f"::notice title=Reference ricontrollate::{name}: {after} su {before} confermate")
    return queue


def restart():
    """Riparte da capo: svuota la coda e il registro dei file letti e rilegge subito tutti i documenti
    della cartella Drive (spostandoli poi negli elaborati). Il registro dei post pubblicati resta, così
    Gemini non ripete argomenti già usciti."""
    drive = drive_service()
    save(QUEUE_FILE, [])
    save(SOURCES_FILE, [])
    queue = []
    ingest(drive, queue, limit=1000)
    refs = sum(1 for p in queue if p.get("references"))
    print(f"::notice title=Ripartenza::{len(queue)} post in coda ({refs} con reference) da {len(load(SOURCES_FILE, []))} documenti")
    save(QUEUE_FILE, queue)
    commit_and_push([QUEUE_FILE.name, SOURCES_FILE.name], f"Ripartenza: {len(queue)} post in coda")


def rebuild():
    """Rigenera la coda rileggendo i file già elaborati (con evidenziazioni e reference),
    senza ripetere gli argomenti già pubblicati. Non pubblica niente."""
    drive = drive_service()
    posted = load(POSTED_FILE, [])
    published = [x["title"] for x in posted]
    old_queue = load(QUEUE_FILE, [])
    # si rifanno solo i file con post ancora nel vecchio formato (senza «references»)
    todo = {p["source"] for p in old_queue if "references" not in p}
    new_queue = [p for p in old_queue if p["source"] not in todo]
    for src in load(SOURCES_FILE, []):
        if not src.get("posts") or src["name"] not in todo:
            continue
        try:
            f = drive.files().get(fileId=src["drive_id"], fields="id, name, mimeType",
                                  supportsAllDrives=True).execute()
            part = content.material_part(drive, f)
            posts = content.generate_posts(part, f["name"], CONFIG["brand_name"],
                                           int(CONFIG.get("max_posts_per_file", 12)),
                                           published + [x["title"] for x in new_queue])
        except Exception as e:
            print(f"::warning title=File non rigenerato::{src['name']}: {str(e)[:300]}")
            new_queue += [p for p in old_queue if p["source"] == src["name"]]   # restano i post vecchi
            continue
        refs = sum(1 for p in posts if p.get("references"))
        print(f"::notice title=Coda rigenerata::{src['name']}: {len(posts)} post, {refs} con reference")
        for p in posts:
            p.update({"id": uuid.uuid4().hex[:8], "source": f["name"]})
        new_queue += posts
    if todo and not new_queue:
        print("Nessun post rigenerato: la coda resta com'è.")
        sys.exit(1)
    new_queue = recheck_references(drive, new_queue, skip=todo)
    save(QUEUE_FILE, new_queue)
    commit_and_push([QUEUE_FILE.name], f"Coda rigenerata: {len(new_queue)} post con evidenziazioni e reference")


def status():
    """Solo lettura: elenca i file in attesa e quelli già elaborati nelle cartelle Drive, e lo stato della coda."""
    drive = drive_service()
    seen = {s["drive_id"] for s in load(SOURCES_FILE, [])}
    inbox = [f for f in list_files(drive, os.environ["GDRIVE_FOLDER_ID"]) if f["id"] not in seen]
    done = list_files(drive, os.environ["GDRIVE_DONE_FOLDER_ID"])
    queue = load(QUEUE_FILE, [])
    lines = [f"File in attesa nella cartella Materiale: {len(inbox)}"]
    lines += [f"  - {f['name']}" + ("" if content.is_supported(f) else "  (formato non supportato)") for f in inbox]
    lines += [f"File già elaborati: {len(done)}"] + [f"  - {f['name']}" for f in done]
    lines += [f"Post in coda: {len(queue)}"] + [f"  - {q['title']}  ({q['source']})" for q in queue]
    print("\n".join(lines))
    # anche come annotazione del run, leggibile dalla pagina del run e dall'API di GitHub
    print("::notice title=Stato Drive e coda::" + "%0A".join(l.replace("%", "%25") for l in lines))


CORRECTIONS_FILE = ROOT / "corrections.json"


def corrections():
    """Rettifiche dei post già pubblicati (corrections.json): un commento sotto il post Instagram e una riga
    di correzione in testa al post Facebook. Ogni rettifica si fa una volta sola (campo «done»)."""
    items = load(CORRECTIONS_FILE, [])
    posted = {p.get("id"): p for p in load(POSTED_FILE, [])}
    token = os.environ["IG_ACCESS_TOKEN"]
    fb_token = os.environ.get("FB_PAGE_TOKEN") or token
    changed = False
    for c in items:
        if c.get("done"):
            continue
        post = posted.get(c["post_id"])
        if not post:
            print(f"::warning title=Rettifica::post {c['post_id']} non trovato nel registro")
            continue
        res = {}
        if post.get("media_id") and not c.get("ig_comment_id"):
            r = requests.post(f"https://graph.facebook.com/{GRAPH_VERSION}/{post['media_id']}/comments",
                              data={"message": c["text"], "access_token": token}, timeout=60)
            res["instagram"] = r.status_code
            if r.ok:
                c["ig_comment_id"] = r.json().get("id")
            else:
                print(f"::warning title=Rettifica Instagram non riuscita::{c['post_id']} {r.status_code}: {r.text[:250]}")
        if post.get("facebook_id") and not c.get("fb_edited"):
            g = requests.get(f"https://graph.facebook.com/{GRAPH_VERSION}/{post['facebook_id']}",
                             params={"fields": "message", "access_token": fb_token}, timeout=60)
            old = (g.json() or {}).get("message", "") if g.ok else ""
            if old and not old.startswith("CORRECTION"):
                r = requests.post(f"https://graph.facebook.com/{GRAPH_VERSION}/{post['facebook_id']}",
                                  data={"message": f"CORRECTION: {c['text']}\n\n{old}", "access_token": fb_token}, timeout=60)
                res["facebook"] = r.status_code
                if r.ok:
                    c["fb_edited"] = True
                else:
                    print(f"::warning title=Rettifica Facebook non riuscita::{c['post_id']} {r.status_code}: {r.text[:250]}")
            elif not g.ok:
                print(f"::warning title=Rettifica Facebook::post non letto {g.status_code}: {g.text[:200]}")
        c["done"] = bool(c.get("ig_comment_id")) and (c.get("fb_edited") or not post.get("facebook_id"))
        c["date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        changed = True
        print(f"::notice title=Rettifica::{c['post_id']} | {res} | completata: {c['done']}")
    if changed:
        save(CORRECTIONS_FILE, items)
        commit_and_push([CORRECTIONS_FILE.name], "Rettifiche dei post pubblicate")


def weekly_digest():
    """Lunedì: messaggio per il canale WhatsApp e resoconto settimanale, in una issue (email) chiusa subito."""
    import weekly
    posted, queue = load(POSTED_FILE, []), load(QUEUE_FILE, [])
    grants_list, verified = grants.fetch(CONFIG), grants.load_verified()
    archive = positions.load_archive()
    msg, n_calls, n_jobs = weekly.whatsapp_message(grants_list, verified, archive, posted, CONFIG)
    rep_md = weekly.report(grants_list, verified, archive, posted, queue, CONFIG)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    folder = ROOT / "weekly"
    folder.mkdir(exist_ok=True)
    (folder / f"whatsapp-{today}.txt").write_text(msg, encoding="utf-8")
    (folder / f"report-{today}.md").write_text(rep_md, encoding="utf-8")
    body = (f"### Messaggio per il canale WhatsApp\n\nCopia e incolla ({n_calls} bandi e {n_jobs} posizioni nuove):\n\n"
            f"```\n{msg}\n```\n\n{rep_md}")
    print(body)
    if DRY_RUN:
        return
    for f in (ROOT / "usage").glob("*.json"):             # registro dei consumi: si tengono 35 giorni
        d = grants._date(f.name[:10])
        if d and (datetime.now(timezone.utc).date() - d).days > 35:
            f.unlink()
    commit_and_push(["weekly", "usage"] if (ROOT / "usage").exists() else ["weekly"], f"Resoconto settimanale {today}")
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if token and repo:
        h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        r = requests.post(f"https://api.github.com/repos/{repo}/issues", headers=h, timeout=30,
                          json={"title": f"Settimana del {today}: messaggio WhatsApp e resoconto", "body": body[:60000]})
        if r.ok:   # chiusa subito: l'email arriva comunque, la lista delle issue resta pulita
            requests.patch(r.json()["url"], headers=h, json={"state": "closed"}, timeout=30)


def backfill_social():
    """Ripubblica su Bluesky e Threads i post usciti su Instagram e Facebook prima che i due profili esistessero,
    con il formato di ciascuno (Bluesky: prima slide + link; Threads: carosello + testo breve). Pochi per giro,
    per non inondare i profili; i post di metodologia sempre, i bandi solo se mancano almeno 14 giorni alla scadenza."""
    import social, methodology
    posted = load(POSTED_FILE, [])
    methods = methodology.load()
    corrected = {c.get("post_id") for c in load(ROOT / "corrections.json", [])}      # post rettificati: non si ripubblicano
    today = datetime.now(timezone.utc).date()
    per_run = int(os.environ.get("BACKFILL_PER_RUN") or CONFIG.get("backfill_per_run", 1))
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    base = f"https://raw.githubusercontent.com/{os.environ.get('GITHUB_REPOSITORY', '')}/{sha}/"
    done = 0
    for p in posted:
        if done >= per_run:
            break
        need_b = social.bluesky_enabled() and not p.get("bluesky_uri")
        need_t = social.threads_enabled() and not p.get("threads_id")
        if not (need_b or need_t) or p.get("kind") in ("positions", "announcement") or p["id"] in corrected:
            continue
        if p.get("kind") == "grant":
            d = grants._date(p.get("deadline"))
            if not d or (d - today).days < 14:
                continue
            title = p.get("grant_title") or p.get("title", "")
            pseudo = {"title": title, "caption": f"{title}\n\nNext deadline: {grants._fmt_date(d)}.\n\n{p.get('summary', '')}"}
            link = grants.site_url(CONFIG, "calls#" + grants.card_anchor(p.get("grant_id", "")))
        else:
            m = methods.get(p["id"])
            if not m or m.get("duplicate_of"):
                continue
            heads = " · ".join(x["heading"] for x in m.get("points", []))
            pseudo = {"title": m["title"], "caption": f"{m['title']}\n\n{m.get('takeaway', '')}\n\nKey points: {heads}"}
            link = grants.site_url(CONFIG, f"methodology#m-{p['id']}")
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in p["id"])
        folder = IMAGES_DIR / f"{p['date']}-{safe}"
        slides = sorted(folder.glob("slide-*.jpg"), key=lambda q: int(q.stem.split("-")[1]))
        if not slides:
            continue
        if need_b:
            try:
                p["bluesky_uri"] = social.publish_bluesky(slides[:1], pseudo, link, max_images=1)
                print(f"::notice title=Bluesky (arretrati)::{p['title'][:60]} → {p['bluesky_uri']}")
            except Exception as e:
                print(f"::warning title=Bluesky (arretrati)::{str(e)[:200]}")
        if need_t:
            try:
                urls = [base + q.relative_to(ROOT).as_posix() for q in slides[:10]]
                p["threads_id"] = social.publish_threads(urls, pseudo, link)
                print(f"::notice title=Threads (arretrati)::{p['title'][:60]} → {p['threads_id']}")
            except Exception as e:
                print(f"::warning title=Threads (arretrati)::{str(e)[:200]}")
        p["backfill"] = today.isoformat()
        done += 1
        save(POSTED_FILE, posted)            # salvato dopo ogni post: se il giro si interrompe, niente doppioni
        commit_and_push([POSTED_FILE.name], f"Arretrati social: {p['title'][:60]}")
        if done < per_run:
            time.sleep(45)                   # qualche secondo tra un post e l'altro: niente raffiche
    if not done:
        print("::notice title=Arretrati social::nessun post da ripubblicare")


if __name__ == "__main__":
    if "--status" in sys.argv:
        status()
    elif "--restart" in sys.argv:
        restart()
    elif "--rebuild" in sys.argv:
        rebuild()
    elif "--token" in sys.argv:
        check_token()
    elif "--weekly" in sys.argv:
        weekly_digest()
    elif "--backfill" in sys.argv:
        backfill_social()
    elif "--corrections" in sys.argv:
        corrections()
    elif "--positions" in sys.argv:
        update_positions(verify_limit=int(os.environ.get("POSITIONS_VERIFY_LIMIT") or 0) or None)
    elif "--grants" in sys.argv:
        update_grants(verify_limit=int(os.environ.get("GRANT_VERIFY_LIMIT") or 0) or None)
    else:
        main()
