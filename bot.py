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

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
QUEUE_FILE = ROOT / "queue.json"
POSTED_FILE = ROOT / "posted_log.json"
SOURCES_FILE = ROOT / "sources_log.json"
IMAGES_DIR = ROOT / "published_images"
PREVIEW_DIR = ROOT / "preview"
PAGE_FILE = ROOT / "docs" / "index.html"   # pagina «link in bio» (GitHub Pages, cartella /docs)

GRAPH_VERSION = os.environ.get("GRAPH_API_VERSION") or "v23.0"
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
MAX_CAPTION_CHARS = 2200
MAX_HASHTAGS = 30


# ---------------------------------------------------------------- utilità
def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def git(*args):
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def commit_and_push(paths, message):
    if DRY_RUN:
        return None
    git("add", *paths)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode != 0:
        git("commit", "-m", message)
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
        dups = content.gemini_json([{"text": prompt}], DUP_SCHEMA, 0.0).get("duplicates", [])
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
    for t in CONFIG.get("fixed_hashtags", []) + post.get("hashtags", []):
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


def publish_carousel(image_urls, caption):
    user = os.environ["IG_USER_ID"]
    children = []
    for url in image_urls:
        cid = ig("POST", f"{user}/media", image_url=url, is_carousel_item="true")["id"]
        wait_ready(cid)
        children.append(cid)
    carousel = ig("POST", f"{user}/media", media_type="CAROUSEL",
                  children=",".join(children), caption=caption)["id"]
    wait_ready(carousel)
    return ig("POST", f"{user}/media_publish", creation_id=carousel)["id"]


def facebook_caption(caption):
    """Su Facebook i link sono cliccabili: «link in bio» diventa l'indirizzo della pagina dei bandi."""
    page = CONFIG.get("links_page_url")
    if page:
        caption = (caption.replace("Clickable link in bio, with all open calls we have shared.", f"All open calls: {page}")
                          .replace("All open calls, grouped by programme: link in bio.", f"All open calls, grouped by region and programme: {page}")
                          .replace("link in bio", page))
    return caption


def publish_facebook(image_urls, caption):
    """Pubblica le stesse slide sulla Pagina Facebook come un unico post con più foto. Restituisce l'id del post."""
    page_id = os.environ.get("FB_PAGE_ID")
    token = os.environ.get("FB_PAGE_TOKEN") or os.environ["IG_ACCESS_TOKEN"]
    base = f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}"
    media = []
    for url in image_urls:
        r = requests.post(f"{base}/photos", data={"url": url, "published": "false", "access_token": token}, timeout=90)
        if not r.ok:
            raise RuntimeError(f"Errore Facebook (foto) {r.status_code}: {r.text[:300]}")
        media.append(r.json()["id"])
    data = {"message": facebook_caption(caption), "access_token": token}
    for i, mid in enumerate(media):
        data[f"attached_media[{i}]"] = json.dumps({"media_fbid": mid})
    r = requests.post(f"{base}/feed", data=data, timeout=90)
    if not r.ok:
        raise RuntimeError(f"Errore Facebook (post) {r.status_code}: {r.text[:300]}")
    return r.json().get("id")


def wait_until_public(url):
    for _ in range(12):
        try:
            if requests.head(url, timeout=15).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(5)
    raise RuntimeError(f"Immagine non raggiungibile: {url}")


def main():
    drive = drive_service()
    queue = load(QUEUE_FILE, [])
    posted = load(POSTED_FILE, [])

    # Due post al giorno, in due run separati: un bando (POST_TYPE=grant) e un post di metodologia (research).
    post_type = (os.environ.get("POST_TYPE") or "research").strip().lower()
    kind = "grant" if post_type == "grant" else "research"
    # Il run pianificato salta se un post dello stesso tipo è uscito nelle ultime 12 ore (es. dopo un lancio manuale).
    same = [p for p in posted if (p.get("kind") or "research") == kind and p.get("time")]
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and same:
        hours = (datetime.now(timezone.utc) - datetime.fromisoformat(same[-1]["time"])).total_seconds() / 3600
        if hours < 12:
            print(f"Ultimo post di tipo {kind} pubblicato {hours:.1f} ore fa: salto.")
            return

    if kind == "grant":
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
    sha = commit_and_push(rel_paths, f"Slide del {today}")
    base = f"https://raw.githubusercontent.com/{os.environ['GITHUB_REPOSITORY']}/{sha}/"
    urls = [base + p for p in rel_paths]
    for u in urls:
        wait_until_public(u)

    media_id = publish_carousel(urls, caption)
    print(f"Pubblicato su Instagram! id={media_id}")

    fb_id = None
    if CONFIG.get("facebook", True) and os.environ.get("FB_PAGE_ID"):
        try:   # un errore su Facebook non blocca il post Instagram già uscito
            fb_id = publish_facebook(urls, caption)
            print(f"Pubblicato su Facebook! id={fb_id}")
        except Exception as e:
            print(f"::warning title=Facebook non pubblicato::{str(e)[:300]}")
            notify("Post non pubblicato su Facebook", f"Il post «{post['title']}» è uscito su Instagram ma non su Facebook: {e}")

    queue = [q for q in queue if q["id"] != post["id"]]
    posted.append({"date": today, "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "id": post["id"], "title": post["title"],
                   "source": post["source"], "media_id": media_id, "facebook_id": fb_id,
                   **({"kind": "grant", "grant_id": post["grant_id"], "url": post["url"],
                       "deadline": post["deadline_iso"], "funder": post.get("funder", ""),
                       "summary": post.get("summary", ""), "italy_evidence": post.get("italy_evidence", ""),
                       "official_source": post.get("official_source", "")}
                      if post.get("kind") == "grant" else {})})
    save(QUEUE_FILE, queue)
    save(POSTED_FILE, posted)
    # pagina «link in bio»: rigenerata a ogni post, così i bandi scaduti spariscono da soli
    PAGE_FILE.parent.mkdir(exist_ok=True)
    commit_and_push([QUEUE_FILE.name, POSTED_FILE.name], f"Post del {today}")
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


def update_grants(posted=None, verify_limit=None):
    """Verifica sul testo ufficiale i bandi nuovi di GrantFinder e rigenera la pagina «link in bio»."""
    posted = posted if posted is not None else load(POSTED_FILE, [])
    grants_list = grants.fetch(CONFIG)
    verified = grants.load_verified()
    if verify_limit != 0:
        grants.refresh_verified(grants_list, verified, CONFIG, limit=verify_limit)
        save(ROOT / grants.VERIFIED_FILE, verified)
    PAGE_FILE.parent.mkdir(exist_ok=True)
    PAGE_FILE.write_text(grants.build_page(grants_list, verified, posted, CONFIG), encoding="utf-8")
    entries = grants.page_entries(grants_list, verified)
    pending = sum(1 for g in grants_list if g["id"] not in verified)
    print(f"::notice title=Pagina bandi::{len(entries)} bandi in pagina, {pending} ancora da verificare")
    commit_and_push([grants.VERIFIED_FILE, PAGE_FILE.relative_to(ROOT).as_posix()], "Bandi verificati e pagina aggiornata")


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


if __name__ == "__main__":
    if "--status" in sys.argv:
        status()
    elif "--restart" in sys.argv:
        restart()
    elif "--rebuild" in sys.argv:
        rebuild()
    elif "--token" in sys.argv:
        check_token()
    elif "--grants" in sys.argv:
        update_grants(verify_limit=int(os.environ.get("GRANT_VERIFY_LIMIT") or 0) or None)
    else:
        main()
