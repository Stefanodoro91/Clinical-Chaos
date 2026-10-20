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
def ingest(drive, queue):
    inbox, done_folder = os.environ["GDRIVE_FOLDER_ID"], os.environ["GDRIVE_DONE_FOLDER_ID"]
    sources = load(SOURCES_FILE, [])
    seen = {s["drive_id"] for s in sources}
    pending = [f for f in list_files(drive, inbox) if f["id"] not in seen]
    limit = int(CONFIG.get("max_new_files_per_run", 1))

    for f in pending[:limit]:
        if not content.is_supported(f):
            print(f"Formato non supportato, ignoro: {f['name']}")
            sources.append({"drive_id": f["id"], "name": f["name"], "posts": 0, "note": "non supportato"})
            continue
        print(f"Leggo il materiale: {f['name']}")
        try:
            part = content.material_part(drive, f)
            posts = content.generate_posts(part, f["name"], CONFIG["brand_name"],
                                           int(CONFIG.get("max_posts_per_file", 12)))
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
    text = f"{post['title']}\n\n{post['caption']}\n\n{' '.join(tags[:MAX_HASHTAGS])}"
    return text[:MAX_CAPTION_CHARS].strip()


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

    # Il run pianificato salta se un post è già uscito nelle ultime 20 ore (es. dopo un lancio manuale).
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and posted and posted[-1].get("time"):
        hours = (datetime.now(timezone.utc) - datetime.fromisoformat(posted[-1]["time"])).total_seconds() / 3600
        if hours < 20:
            print(f"Ultimo post pubblicato {hours:.1f} ore fa: oggi salto.")
            return

    files_waiting = ingest(drive, queue)

    # Mercoledì e sabato (configurabili) un bando da GrantFinder; se non ce ne sono, un post di metodologia.
    post_type = (os.environ.get("POST_TYPE") or "auto").strip().lower()
    post = None
    wants_grant = post_type == "grant" or (
        post_type == "auto" and CONFIG.get("grant_posts", True) and (grants.is_grant_day(CONFIG) or not queue))
    if wants_grant:
        post = grants.next_grant_post(posted, CONFIG)
        if post is None:
            print("Nessun bando pubblicabile oggi: passo alla metodologia.")

    if post is None:
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

    queue = [q for q in queue if q["id"] != post["id"]]
    posted.append({"date": today, "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "id": post["id"], "title": post["title"],
                   "source": post["source"], "media_id": media_id,
                   **({"kind": "grant", "grant_id": post["grant_id"]} if post.get("kind") == "grant" else {})})
    save(QUEUE_FILE, queue)
    save(POSTED_FILE, posted)
    commit_and_push([QUEUE_FILE.name, POSTED_FILE.name], f"Post del {today}")

    if len(queue) <= int(CONFIG.get("low_queue_warning", 5)) and files_waiting == 0:
        notify("Post in esaurimento",
               f"Restano {len(queue)} post in coda. Aggiungi nuovo materiale nella cartella Drive.")


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
    status() if "--status" in sys.argv else main()
