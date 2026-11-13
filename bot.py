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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import meta_token
from google.oauth2 import service_account
from googleapiclient.discovery import build

import cards
import content
import grants
import linkedin
import polish
import positions
import rubrics

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
grants.SITE_MONO = bool(CONFIG.get("mono"))
grants.SITE_COLORS = grants.site_colors(CONFIG)     # solo sito (cascata laterale)
QUEUE_FILE = ROOT / "queue.json"
POSTED_FILE = ROOT / "posted_log.json"
SOURCES_FILE = ROOT / "sources_log.json"
IMAGES_DIR = ROOT / "published_images"
PREVIEW_DIR = ROOT / "preview"
LINKEDIN_DIR = ROOT / "linkedin_drafts"   # testo pronto da incollare a mano su LinkedIn, un file per post uscito
PAGE_FILE = ROOT / "docs" / "calls.html"   # pagina dei bandi
HOME_FILE = ROOT / "docs" / "index.html"   # pagina iniziale del link in bio: due pulsanti, bandi e posizioni

GRAPH_VERSION = os.environ.get("GRAPH_API_VERSION") or "v23.0"
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
SIM_NAME = "simulated_log.json"            # social in pausa: contenuti preparati ma non pubblicati (config social_paused)
LIVE_KINDS = set(CONFIG.get("social_live_kinds") or [])      # social in pausa tranne queste rubriche (es. grant, positions)
SIMULATE = (bool(CONFIG.get("social_paused")) and not DRY_RUN
            and (os.environ.get("POST_TYPE") or "research").strip().lower() not in LIVE_KINDS)
SIM_FILE = ROOT / SIM_NAME
MAX_CAPTION_CHARS = 2200
MAX_HASHTAGS = 5          # limite di Instagram (dicembre 2025): oltre, meno portata


# ---------------------------------------------------------------- utilità

def _social_guard():
    """Sicura: con i social in pausa (config «social_paused») nessuna pubblicazione può partire, da nessun percorso."""
    import json as _json
    from pathlib import Path as _P
    import os as _os
    cfg = _json.loads((_P(__file__).resolve().parent / "config.json").read_text(encoding="utf-8"))
    kind = (_os.environ.get("POST_TYPE") or "").strip().lower()       # rubriche riattivate: config «social_live_kinds»
    if cfg.get("social_paused") and kind not in (cfg.get("social_live_kinds") or []):
        raise RuntimeError("social in pausa (config social_paused): pubblicazione bloccata")

def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def git(*args):
    subprocess.run(["git", *args], cwd=ROOT, check=True)


content.THINKING = dict(CONFIG.get("gemini_thinking") or {})
content.ROUTE_OVERRIDES = dict(CONFIG.get("ai_routes") or {})
content.CHECK_CAP = int(CONFIG.get("gemini_daily_cap_checks", 60))   # richieste dei modelli leggeri oltre le quali le verifiche si fermano
content.MODEL_RPD.update(CONFIG.get("gemini_rpd") or {})
content.STRONG_RESERVE = int(CONFIG.get("gemini_strong_reserve", content.STRONG_RESERVE))
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


def list_inbox(drive, inbox):
    """File della cartella di input e delle sue sottocartelle «Clinica…» (es. «Clinica main», «Clinica ancillary»):
    materiale clinico per area. Le altre sottocartelle (Elaborati, Musica…) restano escluse. Ogni file porta
    la cartella in cui si trova, per poterlo spostare in «Elaborati» dopo la lettura."""
    files = [dict(f, parent=inbox) for f in list_files(drive, inbox)]
    resp = drive.files().list(q=f"'{inbox}' in parents and trashed = false and mimeType = 'application/vnd.google-apps.folder'",
                              fields="files(id, name)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    for sub in resp.get("files", []):
        if sub["name"].lower().startswith("clinica"):
            files += [dict(f, parent=sub["id"]) for f in list_files(drive, sub["id"])]
    return sorted(files, key=lambda f: f.get("createdTime", ""))


def move(drive, file_id, src, dst):
    drive.files().update(fileId=file_id, addParents=dst, removeParents=src,
                         fields="id", supportsAllDrives=True).execute()


# ---------------------------------------------------------------- fase 1: lettura materiale
def ingest(drive, queue, limit=None):
    inbox, done_folder = os.environ["GDRIVE_FOLDER_ID"], os.environ["GDRIVE_DONE_FOLDER_ID"]
    sources = load(SOURCES_FILE, [])
    seen = {s["drive_id"] for s in sources}
    # gli articoli delle sottocartelle «Clinica…» non vanno nella coda di metodologia: sono riservati a Latest Science
    pending = [f for f in list_inbox(drive, inbox) if f["id"] not in seen and f.get("parent") == inbox]
    limit = int(limit or CONFIG.get("max_new_files_per_run", 1))

    for f in pending[:limit]:
        if not content.is_supported(f):
            print(f"Formato non supportato, ignoro: {f['name']}")
            sources.append({"drive_id": f["id"], "name": f["name"], "posts": 0, "note": "non supportato"})
            continue
        print(f"Leggo il materiale: {f['name']}")
        try:
            part = content.material_part(drive, f)
            if f.get("parent") != inbox:         # materiale clinico («Clinica…»): solo articoli con licenza riutilizzabile
                status, label = content.license_status(content.material_text(part))
                if status != "ok":
                    why = label or "nessuna licenza dichiarata nel testo"
                    print(f"::warning title=Articolo ignorato per licenza::{f['name']}: {why}")
                    sources.append({"drive_id": f["id"], "name": f["name"], "posts": 0, "note": f"ignorato: {why}",
                                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")})
                    if not DRY_RUN:
                        save(SOURCES_FILE, sources)
                        commit_and_push([SOURCES_FILE.name], f"Articolo ignorato per licenza: {f['name']}")
                    continue
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
                move(drive, f["id"], f.get("parent", inbox), done_folder)
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


CLINICAL_QUEUE_FILE = ROOT / "clinical_queue.json"     # post Latest Science già scritti dagli articoli di «Clinica…»


def _clinical_review(post, material):
    """Controlli prima dell'uscita sul testo dell'articolo: anti-copia, revisione incrociata (o verifica dei fatti),
    reference. False se la revisione respinge il post."""
    content.rewrite_copied(post, material)
    if CONFIG.get("cross_review", True):
        rev = content.cross_review(post, material)
        post["review"] = {k: rev.get(k) for k in ("passed", "scores", "critic", "arbiter", "fixed", "removed", "notes")}
        if rev.get("passed") is False:
            print(f"::warning title=Latest Science respinto dalla revisione::{post['title'][:70]}: "
                  f"{'; '.join(rev.get('notes', [])[:2])[:250]}")
            return False
        if rev.get("passed") is None:
            content.verify_against_source(post, material)
    else:
        content.verify_against_source(post, material)
    content.fix_references(post)
    return True


def _new_clinical_posts(drive, posted, sources, cq):
    """Legge il prossimo articolo non ancora usato delle sottocartelle «Clinica…» e ne ricava 2-3 post clinici
    (messaggi diversi), che vanno nella coda clinica. Restituisce quanti post ha aggiunto."""
    inbox = os.environ["GDRIVE_FOLDER_ID"]
    reuse = os.environ.get("REUSE_CLINICAL_SINCE", "").strip()   # anteprime: articoli già usati di nuovo leggibili
    if reuse:                                                     # (tranne quelli riusati da questa data in poi)
        read = {x.get("name") for x in sources if x.get("clinical_skipped")
                or (x.get("clinical_used") and (x.get("date") or "") >= reuse)}
        read |= {q.get("source") for q in cq}
    else:
        read = {x.get("name") for x in sources if x.get("clinical_used") or x.get("clinical_skipped")}
        read |= {q.get("source") for q in cq} | {p.get("source") for p in posted if p.get("category") == content.CLINICAL_CATEGORY}
    files = [f for f in list_inbox(drive, inbox) if f.get("parent") != inbox and f["name"] not in read and content.is_supported(f)]
    print(f"Latest Science: {len(files)} articoli clinici non ancora letti nelle cartelle «Clinica…»")
    published = [x["title"] for x in posted if x.get("title")
                 and not (reuse and x.get("category") == content.CLINICAL_CATEGORY)] + [q["title"] for q in cq]
    for f in files[:int(CONFIG.get("latest_science_tries", 3))]:
        note = None
        try:
            part = content.material_part(drive, f)
            status_, label = content.license_status(content.material_text(part))
            if status_ != "ok":
                note = f"licenza: {label or 'non dichiarata nel testo'}"
            else:
                posts, focus, why = content.clinical_posts(part, f["name"], CONFIG["brand_name"], published,
                                                           int(CONFIG.get("latest_science_posts_per_paper", 3)))
                if not posts:
                    note = f"nessun messaggio clinico ({focus}): {why[:150]}"
        except Exception as e:
            print(f"::warning title=Articolo clinico non letto::{f['name']}: {str(e)[:200]}")
            continue
        if note:
            print(f"::notice title=Articolo clinico saltato::{f['name']}: {note}")
            sources.append({"drive_id": f["id"], "name": f["name"], "posts": 0, "clinical_skipped": note,
                            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")})
            save(SOURCES_FILE, sources)
            continue
        for p in posts:
            p.update({"id": uuid.uuid4().hex[:8], "source": f["name"], "rubric": "Clinical Insights"})
        cq.extend(posts)
        sources.append({"drive_id": f["id"], "name": f["name"], "posts": len(posts), "clinical_used": True,
                        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")})
        save(SOURCES_FILE, sources)    # subito su disco: source_material() rilegge l'articolo da qui per i controlli
        print(f"::notice title=Articolo clinico letto::{f['name']} ({focus}): {len(posts)} post per Latest Science")
        return len(posts)
    return 0


def latest_science_post(drive, posted):
    """Post del sabato «Latest Science»: SOLO dagli articoli delle sottocartelle Drive «Clinica…» (es. «Clinica main»),
    mai dalla coda di metodologia. Da ogni articolo escono 2-3 post (coda clinica, uno a sabato); finiti quelli si
    legge l'articolo successivo. Ogni post parla di un trattamento o dello stato di salute dei pazienti e passa i
    controlli sul testo dell'articolo prima di uscire. Nessun post adatto: None (il sabato salta, con avviso)."""
    sources = load(SOURCES_FILE, [])
    cq = load(CLINICAL_QUEUE_FILE, [])
    done = {p.get("id") for p in posted}
    cq = [q for q in cq if q.get("id") not in done
          and (q.get("lay_abstract") or not CONFIG.get("science_lay_abstract", True))]   # niente post del formato vecchio
    try:
        for _ in range(2):
            if not cq and not _new_clinical_posts(drive, posted, sources, cq):
                return None
            last = next((p.get("source") for p in reversed(posted) if p.get("category") == content.CLINICAL_CATEGORY), None)
            if cq and all(q.get("source") == last for q in cq):
                _new_clinical_posts(drive, posted, sources, cq)   # varietà: se c'è, un articolo nuovo prima del 3° post
            cq.sort(key=lambda q: q.get("source") == last)    # stabile: se c'è, un articolo diverso dalla settimana prima
            while cq:
                post = cq.pop(0)
                material = source_material(drive, post["source"])
                if not material:
                    print(f"  Articolo di «{post['title'][:60]}» non rileggibile: post scartato")
                    continue
                if _clinical_review(post, material):
                    print(f"Latest Science da «{post['source']}»: {post['title']}")
                    return post
        return None
    finally:
        save(CLINICAL_QUEUE_FILE, cq)
        save(SOURCES_FILE, sources)


METHOD_ONLY_CATEGORIES = {"Study design", "Reporting & publication", "Critical appraisal"}  # pura metodologia:
                                        # esclusa dalla scelta del sabato (Latest Science vuole un angolo clinico)


def pick_next(queue, posted, prefer_doi=False):
    """Il prossimo post della coda: mai una fonte già usata negli ultimi 7 giorni (al massimo un post per
    fonte a settimana) né quella dell'ultimo post, quando la coda lo permette. Con prefer_doi (rubrica
    Clinical Insights del sabato) sceglie possibilmente un post con articolo citabile (DOI nelle reference) e,
    tra questi, preferisce chi non è di pura metodologia (design, reporting, appraisal): Latest Science punta
    a un concetto clinico, non a una lezione di metodo. Così la slide «Based on» ha comunque la fonte."""
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent = {p.get("source") for p in posted
              if (p.get("kind") or "research") == "research" and p.get("time")
              and datetime.fromisoformat(p["time"]) >= week_ago}
    last_source = next((p.get("source") for p in reversed(posted) if (p.get("kind") or "research") == "research"), None)
    pools = ([i for i in queue if i.get("source") not in recent],
             [i for i in queue if i.get("source") != last_source], queue)
    for pool in pools:
        if not pool:
            continue
        if CONFIG.get("areas_posting"):
            pool = rubrics.area_balance(pool, posted)      # prima l'area meno uscita negli ultimi 30 giorni
        if prefer_doi:
            with_doi = [i for i in pool if any("doi" in str(r).lower() for r in i.get("references") or [])]
            if with_doi:
                clinical = [i for i in with_doi if i.get("category") not in METHOD_ONLY_CATEGORIES]
                return (clinical or with_doi)[0]
        return pool[0]
    return queue[0]


def source_material(drive, name):
    """Testo del materiale di origine di un post (dal registro delle fonti), per i controlli anti-copia."""
    try:
        entry = next((x for x in reversed(load(SOURCES_FILE, [])) if x.get("name") == name and x.get("drive_id")), None)
        if not entry:
            return ""
        meta = drive.files().get(fileId=entry["drive_id"], fields="id,name,mimeType", supportsAllDrives=True).execute()
        part = content.material_part(drive, meta)
        return content.material_text(part) if part else ""
    except Exception as e:
        print(f"  Materiale di origine non letto ({str(e)[:120]}): controllo anti-copia saltato")
        return ""


def quality_gate(post, drive, queue):
    """Controlli di qualità prima della pubblicazione di un post di metodologia: frasi copiate dalla fonte
    riscritte (rilevazione senza AI), revisione incrociata a due AI sulla fonte (content.cross_review: un revisore
    di un'altra famiglia critica ogni frase, Gemini fa da arbitro, il revisore ridà i voti), riferimenti dai
    metadati Crossref e post concreto. Un post respinto o generico viene saltato e si prova il successivo in coda
    (fino a 3). Se nessuno passa la revisione, oggi il post di metodologia non esce (None)."""
    rubric = post.get("rubric")
    best_generic = None
    for _ in range(3):
        material = source_material(drive, post.get("source", ""))
        rejected = False
        if material:
            content.rewrite_copied(post, material)
            rev = content.cross_review(post, material) if CONFIG.get("cross_review", True) else {"passed": None}
            post["review"] = {k: rev.get(k) for k in ("passed", "scores", "critic", "arbiter", "fixed", "removed", "notes")}
            if rev.get("passed") is None and CONFIG.get("verify_source", True):
                content.verify_against_source(post, material)      # nessun revisore indipendente: controllo di Gemini
            rejected = rev.get("passed") is False
        if not rejected:
            content.fix_references(post)
            missing = [] if post.get("lay_abstract") else content.concreteness(post)   # Latest Science: niente numeri per scelta
            if missing and material:
                print(f"  Post generico (manca: {', '.join(missing)}): provo ad arricchirlo dal materiale")
                if content.enrich(post, material):
                    missing = []
            if not missing:
                if rubric:
                    post["rubric"] = rubric
                return post
            best_generic = best_generic or post
            print(f"::warning title=Post generico saltato::«{post['title']}» senza numeri, esempi o azioni concrete")
        else:
            print(f"::warning title=Post respinto dalla revisione::«{post['title']}»: "
                  + "; ".join((post["review"].get("notes") or [])[:3])[:400])
        nxt = (next((q for q in queue if q is not post and q.get("source") != post.get("source")
                     and not (q.get("review") or {}).get("passed") is False), None)
               or next((q for q in queue if q is not post and not (q.get("review") or {}).get("passed") is False), None))
        if nxt is None:
            break
        post = nxt
    if best_generic is not None:
        print("::warning title=Post generico pubblicato::nessun post abbastanza concreto in coda: esce il migliore che ha passato la revisione")
        if rubric:
            best_generic["rubric"] = rubric
        return best_generic
    return None


def plan_visuals(post):
    """Immagini specifiche (visuals.py): le figure dell'articolo solo con licenza CC BY / BY-SA / CC0."""
    import sources
    import visuals
    figures, credit = [], ""
    meta = sources.META.get(post.get("id"))
    data = sources.PDF.get(post.get("id"))
    if meta and data and visuals.figure_license_ok(meta) and not post.get("lay_abstract"):   # lay abstract: le figure
                                                                                                # svelerebbero i risultati
        try:
            figures = visuals.paper_figures(data)
            credit = f"{polish._cite_of(meta.get('apa', ''))} · {meta.get('license_label', 'CC')}".strip(" ·")
            print(f"  Figure dell'articolo: {len(figures)}")
        except Exception as e:
            print(f"  Figure non estratte ({str(e)[:120]})")
    visuals.plan(post, figures, credit)


def build_caption(post):
    tags, seen = [], set()
    kind = post.get("kind")
    if kind == "grant":                      # bandi: #ResearchFunding e #ClinicalResearch, poi i 3 più specifici
        pool = ["#ResearchFunding", "#ClinicalResearch"] + [t for t in post.get("hashtags", []) if t.lower() != "#grantopportunity"]
    elif kind in ("positions", "announcement"):
        pool = post.get("hashtags", []) + CONFIG.get("fixed_hashtags", [])
    else:                                    # metodologia: i 2 fissi e i 3 specifici; Latest Science senza #ResearchMethodology
        pool = polish.hashtags(post, CONFIG.get("fixed_hashtags", []))
    for t in pool:
        if t.lower() not in seen:
            seen.add(t.lower())
            tags.append(t)
    refs = [polish.tidy_reference(r) for r in post.get("references") or []]
    ref_block = ("\n\nReferences:\n" + "\n".join(f"• {r}" for r in refs)) if refs else ""
    tail = f"{ref_block}\n\n{' '.join(tags[:MAX_HASHTAGS])}"
    head = f"{post['title']}\n\n{post['caption']}"
    room = MAX_CAPTION_CHARS - len(tail)          # le reference e gli hashtag non vengono mai tagliati
    if len(head) > room:
        head = head[:max(0, room - 1)].rsplit(" ", 1)[0] + "…"
    return (head + tail).strip()


def ig(method, path, _token=None, **params):
    params["access_token"] = _token or os.environ["IG_ACCESS_TOKEN"]
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
    _social_guard()
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
    _social_guard()
    page_id = os.environ.get("FB_PAGE_ID")
    token = meta_token.ensure_page_token()
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
    points = "\n".join(f"{i}. {polish.point(s['heading'], s['body'])}" for i, s in enumerate(post.get("slides", []), 1))
    refs = "\n".join(f"- {r}" for r in (post.get("references") or [])[:3])
    parts = [body, f"Key points:\n{points}" if points else "", f"Takeaway: {post['takeaway']}" if post.get("takeaway") else "",
             f"References:\n{refs}" if refs else "", f"All our methodology carousels, with references: {link}" if link else "",
             " ".join(tags[:5])]
    return "\n\n".join(x for x in parts if x)[:6000]


def publish_facebook_single(image_url, message):
    """Facebook: un'immagine con testo lungo (per il pubblico della Pagina rende più del carosello). Restituisce l'id del post."""
    _social_guard()
    page_id = os.environ.get("FB_PAGE_ID")
    token = meta_token.ensure_page_token()
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
    _social_guard()
    user, token = os.environ["IG_USER_ID"], meta_token.ensure_page_token()   # upload diretto: serve il token di Pagina
    c = ig("POST", f"{user}/media", _token=token, media_type="REELS", upload_type="resumable", caption=caption,
           share_to_feed="true")
    data = Path(video_path).read_bytes()
    r = requests.post(c.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{GRAPH_VERSION}/{c['id']}",
                      headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data))},
                      data=data, timeout=300)
    if not r.ok:                               # ripiego: Instagram scarica il video dal sito (come per Threads)
        print(f"::warning title=Reel::caricamento diretto rifiutato {r.status_code}: {r.text[:200]}; "
              "riprovo con l'indirizzo pubblico del video")
        url = public_video_url(video_path, f"reel-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}")
        c = ig("POST", f"{user}/media", _token=token, media_type="REELS", video_url=url, caption=caption,
               share_to_feed="true")
    for _ in range(60):                        # l'elaborazione dei video può richiedere qualche minuto
        status = ig("GET", c["id"], _token=token, fields="status_code").get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram ha rifiutato il video (stato {status})")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram non ha elaborato il video in tempo")
    return ig("POST", f"{user}/media_publish", _token=token, creation_id=c["id"])["id"]


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
    "announcement": {"music": "Cerimony|Ceremony|Aziendale|Speciale|Funky",
                     "text": "More on our profile and at the link in bio.",
                     "tags": ["#ResearchCommunity"]},
}


def reel_spec(kind, p, cfg=None):
    """Copione del reel per metodologia, bandi e posizioni (None: si usano le slide del carosello)."""
    import reels
    cfg = cfg or CONFIG
    try:
        if kind == "research":
            m = load(ROOT / "methodology.json", [])
            items = m if isinstance(m, list) else list(m.values())
            entry = next((x for x in items if x.get("id") == p.get("id")), None)
            if entry is None and p.get("points"):          # post simulato (social in pausa): i punti sono nel registro
                entry = p
            return reels.research_spec(entry, cfg) if entry and entry.get("points") else None
        if kind == "grant":
            import grants
            return reels.grant_spec(p, grants.load_verified().get(p.get("grant_id"), {}), cfg)
        if kind == "positions":
            import positions
            return reels.positions_spec(p, positions.load_archive(), cfg)
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
    target_id = (os.environ.get("REEL_OF") or "").strip()
    if source == "crosspost" and target_id:      # reel già uscito su Instagram: solo le piattaforme che mancano
        rid = f"reel-{target_id}"[:60]
        entry = next((p for p in posted if p.get("id") == rid and p.get("kind") == "reel"), None)
        video = ROOT / "kickoff_reels" / f"{target_id}.mp4"
        if not entry or not video.exists():
            print("::notice title=Reel::reel non ancora uscito o video mancante: niente da ripubblicare")
            return
        link = CONFIG.get("links_page_url") or grants.site_url(CONFIG, "")
        crosspost_reel(video, f"{entry['title']}\n\nMore on our profile and at the link in bio.", entry["title"], link, entry, rid)
        save(POSTED_FILE, posted)
        commit_and_push([POSTED_FILE.name], "Reel anche sulle piattaforme mancanti")
        return
    if source in ("announcement", "crosspost"):
        return reel_announcement_run(posted)
    force = {"special": "announcement"}.get(source, source) if source != "latest" else None
    target = (os.environ.get("REEL_OF") or "").strip()           # reel di un post preciso (lancio manuale, validato)
    live_reels = set(CONFIG.get("social_live_reels") or [])      # social in pausa: reel solo di queste rubriche
    done = {p.get("reel_of") for p in posted if p.get("kind") == "reel"}
    now = datetime.now(timezone.utc).timestamp()
    latest = {}                      # per ogni tipo, il carosello più recente non ancora trasformato in reel
    for p in reversed(posted):
        kind = p.get("kind") or "research"
        if kind not in REEL_KINDS or kind in latest or p.get("id") in done or not p.get("time") or force not in (None, kind):
            continue
        if target and p.get("id") != target:
            continue
        if CONFIG.get("social_paused") and not DRY_RUN and not target and kind not in live_reels:
            continue                 # reel di metodologia e altre linee scientifiche: restano in pausa
        if kind == "announcement" and force != "announcement":
            continue                 # gli annunci scritti a mano hanno numeri fissi (poi superati): reel solo su richiesta
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
    accent = {"grant": CONFIG.get("grant_accent", "#FFB547"),
              "positions": CONFIG.get("positions_accent", "#8B5CF6")}.get(kind) \
        or (cards.azure_for(p) if CONFIG.get("mono") else CONFIG["colors"]["accent"])
    rcfg = {**CONFIG, "colors": {**CONFIG["colors"], "accent": accent}}       # colore del tipo anche nel reel
    spec = None if target else reel_spec(kind, p, rcfg)
    ready = ROOT / "kickoff_reels" / f"{p['id']}.mp4"
    if target and ready.exists():    # video già approvato in anteprima: si pubblica così com'è
        import shutil, subprocess
        shutil.copy(ready, video)
        seconds = round(float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                                       "-of", "csv=p=0", str(video)]).decode().strip()))
    elif spec:                       # reel nativo e breve, scritto per il tipo di post (20–30 secondi)
        seconds = reels.build_story_reel(spec, video, rcfg, mood=style["music"])
    else:                            # post speciali: le slide del carosello, il tempo di leggerle (max 40 s)
        lengths = reels.reading_lengths(len(slides), reel_words(kind, p, len(slides)), cap=40.0)
        seconds = reels.build_reel(slides, video, rcfg, accent=accent, mood=style["music"], per_slide=lengths)
    caption = (f"{p['title']}\n\n" + style["text"].format(seconds=round(seconds)) + "\n\n"
               + " ".join(list(dict.fromkeys(style["tags"] + CONFIG.get("fixed_hashtags", [])))[:MAX_HASHTAGS]))
    print(f"Reel da: {p['title']} ({kind}, musica {style['music']}, {len(slides)} slide, {seconds} s)\n--- Didascalia ---\n{caption}")
    if DRY_RUN:
        (PREVIEW_DIR / "reel-caption.txt").write_text(caption, encoding="utf-8")
        (PREVIEW_DIR / "reel.json").write_text(json.dumps({"reel_of": p["id"], "title": p["title"], "kind": kind,
                                                           "music": style["music"], "seconds": seconds}), encoding="utf-8")
        print("Modalità prova: reel non pubblicato. Anteprima nell'artifact 'preview'.")
        return
    if SIMULATE:
        import drive_preview
        drive_preview.upload(video, "reel", "video/mp4", CONFIG)
        sims = load(SIM_FILE, [])
        sims.append({"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                     "time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "id": f"reel-{p['id']}"[:60],
                     "title": p["title"], "source": p.get("source", ""), "kind": "reel", "reel_of": p["id"],
                     "seconds": seconds, "simulated": True})
        save(SIM_FILE, sims)
        commit_and_push([SIM_NAME], f"Reel simulato (social in pausa): {p['title'][:60]}")
        print("::notice title=Reel simulato::salvato su Drive, non pubblicato")
        return
    try:
        media_id = publish_reel(video, caption)
    except Exception as e:
        msg = str(e)[:400]
        print(f"::error title=Reel non pubblicato::{msg}")
        notify("Reel non pubblicato su Instagram", f"Il reel di «{p['title']}» non è uscito: {msg}")
        sys.exit(1)
    print(f"::notice title=Reel pubblicato::{p['title']} | id {media_id}")
    entry = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
             "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "id": f"reel-{p['id']}"[:60], "title": p["title"], "source": p.get("source", ""),
             "kind": "reel", "reel_of": p["id"], "media_id": media_id, "seconds": seconds}
    posted.append(entry)
    save(POSTED_FILE, posted)
    link = CONFIG.get("links_page_url") or grants.site_url(CONFIG, "")
    crosspost_reel(video, caption, p["title"], link, entry, entry["id"])
    save(POSTED_FILE, posted)
    commit_and_push([POSTED_FILE.name], "Reel pubblicato")


def publish_facebook_reel(video_path, caption):
    """Reel sulla Pagina Facebook (API video_reels: avvio, caricamento diretto, pubblicazione)."""
    _social_guard()
    page = os.environ["FB_PAGE_ID"]
    token = meta_token.ensure_page_token()
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{page}/video_reels"
    r = requests.post(url, data={"upload_phase": "start", "access_token": token}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Reel Facebook: avvio rifiutato {r.status_code}: {r.text[:300]}")
    start = r.json()
    data = Path(video_path).read_bytes()
    up = requests.post(start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{GRAPH_VERSION}/{start['video_id']}",
                       headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data))},
                       data=data, timeout=300)
    if not up.ok:
        raise RuntimeError(f"Reel Facebook: caricamento rifiutato {up.status_code}: {up.text[:300]}")
    for _ in range(12):
        r = requests.post(url, timeout=60, data={"upload_phase": "finish", "video_id": start["video_id"],
                                                 "video_state": "PUBLISHED", "description": facebook_caption(caption),
                                                 "access_token": token})
        if r.ok:
            return start["video_id"]
        time.sleep(10)
    raise RuntimeError(f"Reel Facebook: pubblicazione rifiutata {r.status_code}: {r.text[:300]}")


def public_video_url(video_path, name):
    """Copia il video nel sito (docs/reels/) e lo rende pubblico: Threads vuole un indirizzo, non il file."""
    import shutil
    rel = Path("docs") / "reels" / f"{name}.mp4"
    (ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(video_path, ROOT / rel)
    sha = commit_and_push([rel.as_posix()], f"Video del reel {name}")
    trigger_deploy()
    site = grants.site_url(CONFIG, f"reels/{name}.mp4")
    for _ in range(36):                       # Cloudflare ripubblica il sito in 1–3 minuti
        try:
            h = requests.head(site, timeout=15)
            if h.status_code == 200 and "video" in h.headers.get("content-type", ""):
                return site
        except requests.RequestException:
            pass
        time.sleep(10)
    return f"https://raw.githubusercontent.com/{os.environ.get('GITHUB_REPOSITORY', '')}/{sha}/{rel.as_posix()}"


def crosspost_reel(video, caption, title, link, entry, name):
    """Lo stesso reel su Facebook, Threads e Bluesky (config reels_crosspost); gli errori non fermano il resto."""
    import social
    if not CONFIG.get("reels_crosspost", True):
        return entry
    if CONFIG.get("facebook", True) and os.environ.get("FB_PAGE_ID") and not entry.get("facebook_id"):
        try:
            entry["facebook_id"] = publish_facebook_reel(video, caption)
            print(f"::notice title=Reel su Facebook::{entry['facebook_id']}")
        except Exception as e:
            print(f"::warning title=Reel non pubblicato su Facebook::{str(e)[:300]}")
    if social.threads_enabled() and not entry.get("threads_id"):
        try:
            url = public_video_url(video, name)
            entry["threads_id"] = social.publish_threads_video(url, social.reel_text(title, caption, link, 500))
            print(f"::notice title=Reel su Threads::{entry['threads_id']}")
        except Exception as e:
            print(f"::warning title=Reel non pubblicato su Threads::{str(e)[:300]}")
    if social.bluesky_enabled() and not entry.get("bluesky_uri"):
        try:
            entry["bluesky_uri"] = social.publish_bluesky_video(video, social.reel_text(title, caption, link, 300), link,
                                                                alt=title)
            print(f"::notice title=Reel su Bluesky::{entry['bluesky_uri']}")
        except Exception as e:
            print(f"::warning title=Reel non pubblicato su Bluesky::{str(e)[:300]}")
    return entry


def simulate_post(post, kind, slides, caption):
    """Social in pausa: il carosello si prepara come per uscire (slide salvate, PDF con didascalia su Drive) e si
    registra in simulated_log.json, senza pubblicare e senza toccare coda, libreria e registro dei post."""
    import drive_preview
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in post["id"])
    folder = IMAGES_DIR / f"{today}-{safe}"
    folder.mkdir(parents=True, exist_ok=True)
    rel = []
    for i, img in enumerate(slides, start=1):          # servono ai reel simulati dei giorni dopo
        (folder / f"slide-{i}.jpg").write_bytes(img)
        rel.append((folder / f"slide-{i}.jpg").relative_to(ROOT).as_posix())
    PREVIEW_DIR.mkdir(exist_ok=True)
    pdf = PREVIEW_DIR / "carousel.pdf"
    drive_preview.carousel_pdf(slides, caption, pdf)
    drive_preview.upload(pdf, {"grant": "grant", "positions": "positions"}.get(kind, "research"), "application/pdf", CONFIG)
    kind_link = {"grant": f"calls#{grants.card_anchor(post.get('grant_id', ''))}", "positions": "positions",
                 "research": polish.page_anchor(post)}.get(kind or "research", "")
    li_link = grants.site_url(CONFIG, kind_link)
    LINKEDIN_DIR.mkdir(exist_ok=True)
    li_path = LINKEDIN_DIR / linkedin.filename(post, kind, today)
    li_path.write_text(linkedin.draft(post, caption, kind, li_link), encoding="utf-8")
    drive_preview.linkedin_doc(LINKEDIN_DIR, CONFIG)     # bozze LinkedIn anche su Drive (documento «Bozze LinkedIn»)
    rel.append(li_path.relative_to(ROOT).as_posix())
    entry = {"date": today, "time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "id": post["id"],
             "title": post["title"], "source": post.get("source", ""), "simulated": True,
             **({"kind": kind} if kind in ("grant", "positions") else {}),
             **({"grant_id": post.get("grant_id"), "deadline": post.get("deadline_iso")} if kind == "grant" else {}),
             **({"position_ids": post.get("position_ids", [])} if kind == "positions" else {}),
             **({"points": [{"heading": s.get("heading", ""), "body": s.get("body", "")} for s in post.get("slides", [])],
                 "takeaway": post.get("takeaway", ""), "category": post.get("category", "")} if kind == "research" else {})}
    sims = load(SIM_FILE, [])
    sims.append(entry)
    save(SIM_FILE, sims)
    extra = [CLINICAL_QUEUE_FILE.name, SOURCES_FILE.name] if CLINICAL_QUEUE_FILE.exists() else []
    commit_and_push(rel + [SIM_NAME] + extra, f"Post simulato (social in pausa): {post['title'][:60]}")
    print(f"::notice title=Post simulato::{post['title'][:80]} → Drive Anteprime, non pubblicato")


def upload_preview(path, name):
    """Copia l'anteprima su Drive sovrascrivendo «reel-anteprima.mp4» nella cartella «Anteprime»: il file è
    dell'utente (gli account di servizio non hanno spazio proprio), il bot ne cambia solo il contenuto."""
    try:
        import music
        from googleapiclient.http import MediaFileUpload
        drive = music._drive()
        fid = CONFIG.get("preview_file_id")
        if not fid:
            print("::warning title=Anteprima::preview_file_id mancante in config")
            return
        drive.files().update(fileId=fid, media_body=MediaFileUpload(str(path), mimetype="video/mp4", resumable=True),
                             supportsAllDrives=True).execute()
        print(f"::notice title=Anteprima su Drive::{name} → Anteprime/reel-anteprima.mp4")
    except Exception as e:
        print(f"::warning title=Anteprima non copiata su Drive::{str(e)[:200]}")


def reel_announcement_run(posted):
    """Reel speciale scritto a mano in reel_announcement.json, pubblicato una sola volta."""
    import reels
    spec = load(ROOT / "reel_announcement.json", None)
    crosspost_only = (os.environ.get("REEL_SOURCE") or "").strip().lower() == "crosspost"
    done = next((p for p in posted if spec and p.get("id") == spec.get("id")), None)
    if not spec or (done and not crosspost_only):
        print("::notice title=Reel::nessun reel speciale nuovo da pubblicare")
        return
    if crosspost_only and not done:
        print("::notice title=Reel::il reel speciale non è ancora uscito su Instagram: niente da ripubblicare")
        return
    if SIMULATE and not crosspost_only:
        print("::notice title=Reel speciale::social in pausa: solo anteprima su Drive")
    PREVIEW_DIR.mkdir(exist_ok=True)
    video = PREVIEW_DIR / "reel.mp4"
    if spec.get("animated"):                  # scritte animate, brano scelto nella libreria (es. Funky)
        seconds = reels.animated_reel(spec, video, CONFIG, mood=spec.get("mood") or "Funky", track=spec.get("music_track"))
    else:
        seconds = reels.build_story_reel(spec, video, CONFIG)       # musica: Musica/Aziendale (poi Speciale, Funky)
    caption = f"{spec['caption']}\n\n{' '.join(spec.get('hashtags', []))}".strip()
    print(f"Reel speciale: {spec['id']} ({seconds} s)\n--- Didascalia ---\n{caption}")
    if DRY_RUN or SIMULATE:
        (PREVIEW_DIR / "reel-caption.txt").write_text(caption, encoding="utf-8")
        upload_preview(video, f"{spec['id']}.mp4")
        print("Modalità prova: reel non pubblicato. Anteprima nell'artifact 'preview' e in Drive «Anteprime».")
        return
    title = spec["slides"][0].get("title", "")
    link = CONFIG.get("links_page_url") or grants.site_url(CONFIG, "")
    if crosspost_only:                        # già su Instagram: solo Facebook, Threads e Bluesky
        crosspost_reel(video, caption, title, link, done, spec["id"])
        save(POSTED_FILE, posted)
        commit_and_push([POSTED_FILE.name], "Reel speciale anche su Facebook, Threads e Bluesky")
        return
    try:
        media_id = publish_reel(video, caption)
    except Exception as e:
        msg = str(e)[:400]
        print(f"::error title=Reel non pubblicato::{msg}")
        notify("Reel non pubblicato su Instagram", f"Il reel speciale {spec['id']} non è uscito: {msg}")
        sys.exit(1)
    print(f"::notice title=Reel pubblicato::{spec['id']} | id {media_id}")
    entry = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
             "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "id": spec["id"], "title": title, "source": "reel_announcement.json",
             "kind": "reel", "media_id": media_id, "seconds": seconds}
    posted.append(entry)
    save(POSTED_FILE, posted)
    crosspost_reel(video, caption, title, link, entry, spec["id"])
    save(POSTED_FILE, posted)
    commit_and_push([POSTED_FILE.name], "Reel speciale pubblicato")


def schedule_delay_hours():
    """Ore di ritardo di un run pianificato rispetto al suo orario (GitHub a volte parte con ore di ritardo).
    None se il run non è pianificato o l'orario non si legge."""
    cron = (os.environ.get("SCHEDULE") or "").split()
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule" or len(cron) < 2:
        return None
    try:
        now = datetime.now(timezone.utc)
        slot = now.replace(hour=int(cron[1]), minute=int(cron[0]), second=0, microsecond=0)
    except ValueError:
        return None
    if slot > now:                     # orario di ieri, partito dopo la mezzanotte UTC
        slot -= timedelta(days=1)
    return (now - slot).total_seconds() / 3600


def main():
    posted = load(POSTED_FILE, [])
    posted_real = posted
    if SIMULATE and not CONFIG.get("simulate_paused_kinds", True):
        print("::notice title=Rubrica chiusa::metodologia e Latest Science in pausa: niente post e niente anteprime "
              "(le anteprime su Drive si chiedono a parte, con week-preview)")
        return
    if SIMULATE:                       # social in pausa: i contenuti già simulati contano come usciti (niente doppioni)
        posted = posted + load(SIM_FILE, [])
        print("::notice title=Social in pausa::contenuti preparati e salvati su Drive (Anteprime), niente pubblicazione")
    late = schedule_delay_hours()
    if late is not None and late > 3:
        # un post fuori orario rende poco: il recupero entro 3 ore lo fa il guardiano (tools/watchdog.py)
        print(f"::notice title=Run pianificato in ritardo::GitHub è partito con {late:.1f} ore di ritardo: salto.")
        return
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
    rome_now = datetime.now(ZoneInfo("Europe/Rome"))
    if DRY_RUN and os.environ.get("PREVIEW_DATE"):         # anteprima di un giorno futuro (solo in prova)
        d = datetime.fromisoformat(os.environ["PREVIEW_DATE"])
        rome_now = rome_now.replace(year=d.year, month=d.month, day=d.day)
    rubrics_on = CONFIG.get("rubrics", True)
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
        if rubrics_on and rome_now.weekday() == 0 and rome_now.day <= 7:
            rubrics.career_path(post)              # rubrica del primo lunedì del mese
            print("Rubrica Career Path: glossario dei ruoli in coda al carosello")
    elif kind == "grant":
        files_waiting = 1                      # il run dei bandi non legge Drive e non avvisa sulla coda
        post = grants.next_grant_post(posted, CONFIG)
        if post is None:
            print("::notice title=Nessun bando oggi::Nessun bando verificato con abbastanza anticipo: oggi niente post bando.")
            return
        if rubrics_on and rome_now.weekday() == 4 and rome_now.isocalendar().week % 2 == 0:
            rubrics.apply_tips(post)               # rubrica quindicinale: consigli di candidatura
            print("Rubrica Before you apply: consigli di candidatura in coda al carosello")
    else:
        files_waiting = 0 if os.environ.get("SKIP_INGEST") else ingest(drive, queue)
        before = len(queue)
        queue[:] = drop_repeats(queue, posted_real)
        if len(queue) != before and not DRY_RUN:
            save(QUEUE_FILE, queue)
            commit_and_push([QUEUE_FILE.name], "Coda: tolti i post doppioni")
        post = rubrics.checklist_post(posted) if rubrics_on and rome_now.weekday() == 3 else None
        if post is not None:                       # giovedì: rubrica Checklist (senza AI, fuori dalla coda)
            print(f"Rubrica Checklist: {post['source_hint']}")
        elif rubrics_on and rome_now.weekday() == 5:
            post = latest_science_post(drive, posted)          # sabato: solo articoli clinici di «Clinica…»
            if post is None:
                notify("Latest Science saltato: nessun articolo clinico adatto",
                       "Nelle cartelle Drive «Clinica…» non c'è un articolo nuovo con licenza riutilizzabile e un "
                       "messaggio clinico sui pazienti (trattamento o stato di salute). Il post del sabato non esce: "
                       "carica un articolo in «Clinica main».")
                print("::warning title=Latest Science saltato::nessun articolo clinico adatto in «Clinica…»")
                return
        else:
            if not queue:
                notify("Coda vuota: il bot è in pausa",
                       "Non ci sono post da pubblicare. Aggiungi nuovo materiale nella cartella Drive.")
                print("Coda vuota.")
                sys.exit(1)
            sim_ids = {p.get("id") for p in posted} if SIMULATE else set()
            post = pick_next([q for q in queue if q["id"] not in sim_ids] or queue, posted)
            post = quality_gate(post, drive, queue)
            if post is None:
                notify("Nessun post di metodologia oggi",
                       "Tre post della coda sono stati respinti dalla revisione incrociata (fonte, contesto, take home "
                       "message). Controlla il log del run: i motivi sono elencati per ogni post.")
                print("::warning title=Nessun post di metodologia::nessun post ha passato la revisione incrociata")
                return
            if post.get("rubric") == "Clinical Insights":
                post["category"] = content.CLINICAL_CATEGORY   # «Latest Science»: mai design/reporting/appraisal
                if not post.get("lay_abstract"):         # formato lay abstract: il take home viene dalle conclusioni
                    content.clinical_takeaway(post)        # takeaway in chiave clinica/paziente, non di metodo
    if kind == "research" and CONFIG.get("areas_posting") and not post.get("area"):
        area = rubrics.area_of(post)
        if area:
            post["area"] = area
            post["area_label"] = rubrics.AREA_NAMES[area]
            post["caption"] += f"\n\nOpen calls in this area: {grants.site_url(CONFIG, 'calls')}?area={area}"
    if (kind == "research" and CONFIG.get("review_slides", True) and post.get("rubric") != "Checklist"
            and not (post.get("review") or {}).get("passed")):
        content.review_slides(post)              # ogni slide un concetto, comprensibile da sola
    apa = ""
    if kind == "research" and CONFIG.get("source_slide"):
        import sources
        meta = sources.prepare(post, drive)      # slide «fonte»: articolo di origine (prima pagina solo se CC)
        apa = (meta or {}).get("apa", "")
    if kind == "research":
        polish.polish_post(post, apa)            # sentence case, reference coerenti con la slide «Based on», fonti
    if kind == "research" and CONFIG.get("visual_plan"):
        plan_visuals(post)                       # schema, figura dell'articolo, foto o niente: slide per slide
    slides = cards.render_carousel(post, CONFIG)
    caption = build_caption(post)
    print(f"\nPost scelto: {post['title']}  (fonte: {post['source']}, {post.get('source_hint', '')})")
    print(f"--- Didascalia ---\n{caption}\n")

    if DRY_RUN:
        PREVIEW_DIR.mkdir(exist_ok=True)
        for i, img in enumerate(slides, start=1):
            (PREVIEW_DIR / f"slide-{i}.jpg").write_bytes(img)
        (PREVIEW_DIR / "caption.txt").write_text(caption, encoding="utf-8")
        (PREVIEW_DIR / "post.json").write_text(json.dumps({k: v for k, v in post.items() if k != "slides"} |
                                                          {"slides": [{"heading": s.get("heading", ""), "body": s.get("body", "")}
                                                                      for s in post.get("slides", [])]},
                                                          ensure_ascii=False, default=str), encoding="utf-8")
        # anteprima dei formati per social: Facebook (immagine singola + testo lungo), Bluesky e Threads (testo breve)
        import social
        plink = grants.site_url(CONFIG, {"grant": f"calls#{grants.card_anchor(post.get('grant_id', ''))}", "positions": "positions",
                                         "research": polish.page_anchor(post)}.get(post.get("kind") or "research", ""))
        if kind == "research":
            (PREVIEW_DIR / "facebook.jpg").write_bytes(cards.facebook_single(post, CONFIG))
        (PREVIEW_DIR / "bluesky.jpg").write_bytes(cards.single_cover(post, CONFIG))
        (PREVIEW_DIR / "facebook.txt").write_text(facebook_text(post, caption, post.get("kind"), plink), encoding="utf-8")
        (PREVIEW_DIR / "linkedin.txt").write_text(linkedin.draft(post, caption, post.get("kind"), plink), encoding="utf-8")
        (PREVIEW_DIR / "bluesky.txt").write_text(social.short_text({**post, "caption": caption}, plink, 300), encoding="utf-8")
        (PREVIEW_DIR / "threads.txt").write_text(social.short_text({**post, "caption": caption}, plink, 500), encoding="utf-8")
        (PREVIEW_DIR / "queue.json").write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")
        print("Modalità prova: niente pubblicato. Anteprima nell'artifact 'preview'.")
        return
    if SIMULATE:
        return simulate_post(post, kind, slides, caption)

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
                 "research": polish.page_anchor(post)}.get(post.get("kind") or "research", "")
    link = grants.site_url(CONFIG, kind_link)
    LINKEDIN_DIR.mkdir(exist_ok=True)
    li_path = LINKEDIN_DIR / linkedin.filename(post, kind, today)
    li_path.write_text(linkedin.draft(post, caption, kind, link), encoding="utf-8")
    import drive_preview
    drive_preview.linkedin_doc(LINKEDIN_DIR, CONFIG)     # testi LinkedIn su Drive (cartella LinkedIn)
    drive_preview.linkedin_pdf(kind, slides, CONFIG)     # e il carosello in PDF da allegare
    commit_and_push([li_path.relative_to(ROOT).as_posix()], "Draft LinkedIn")
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
                   **({"area": post["area"]} if post.get("area") else {}),
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
    commit_and_push([QUEUE_FILE.name, POSTED_FILE.name, "methodology.json"] + (["pixabay_used.json"] if photos else [])
                    + ([CLINICAL_QUEUE_FILE.name, SOURCES_FILE.name] if CLINICAL_QUEUE_FILE.exists() else []),
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
            page, fb_token = os.environ["FB_PAGE_ID"], meta_token.ensure_page_token()
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
    check_other_socials()


def check_other_socials():
    """Threads e Bluesky: una lettura del profilo (nessuna pubblicazione). Token invalidato → avviso via issue."""
    if os.environ.get("THREADS_ACCESS_TOKEN"):
        r = requests.get("https://graph.threads.net/v1.0/me", timeout=30,
                         params={"fields": "id,username", "access_token": os.environ["THREADS_ACCESS_TOKEN"]})
        if r.ok:
            same = r.json().get("id") == os.environ.get("THREADS_USER_ID", r.json().get("id"))
            print(f"::notice title=Threads::token valido (@{r.json().get('username')})"
                  + ("" if same else " ma THREADS_USER_ID non corrisponde"))
        else:
            print(f"::error title=Threads::token non valido {r.status_code}: {r.text[:200]}")
            notify("Token Threads non valido", "Threads rifiuta il token (THREADS_ACCESS_TOKEN): i post non escono su "
                   "Threads. Generane uno nuovo dal pannello dell'app Meta (Threads API → User Token Generator).")
    if os.environ.get("BLUESKY_HANDLE") and os.environ.get("BLUESKY_APP_PASSWORD"):
        r = requests.post("https://bsky.social/xrpc/com.atproto.server.createSession", timeout=30,
                          json={"identifier": os.environ["BLUESKY_HANDLE"], "password": os.environ["BLUESKY_APP_PASSWORD"]})
        print(f"::notice title=Bluesky::accesso riuscito" if r.ok else
              f"::error title=Bluesky::accesso rifiutato {r.status_code}: {r.text[:150]}")


POSITIONS_PAGE = ROOT / "docs" / "positions.html"


def update_positions(posted=None, verify_limit=None):
    """Raccoglie e verifica le posizioni accademiche nuove e rigenera la pagina «Academic positions»."""
    posted = posted if posted is not None else load(POSTED_FILE, [])
    archive = positions.load_archive()
    if verify_limit != 0:
        positions.refresh(archive, limit=int(verify_limit or CONFIG.get("positions_verify_per_run", 25)))
        save(ROOT / positions.ARCHIVE_FILE, archive)
    if os.environ.get("CONFIRM_STRONG", "1") != "0":      # secondo parere dei forti sulle posizioni ad alta priorità
        if positions.confirm_candidates(archive, posted, CONFIG):
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


CALLS_DIR = ROOT / "docs" / "call"


def write_call_pages(grants_list, verified):
    """Una pagina per ogni bando verificato in pagina; le pagine dei bandi non piu' in pagina si cancellano."""
    pages = grants.call_pages(grants_list, verified, CONFIG)
    CALLS_DIR.mkdir(parents=True, exist_ok=True)
    names = {Path(k).name for k in pages}
    for f in CALLS_DIR.glob("*.html"):
        if f.name not in names:
            f.unlink()
    for path, html in pages.items():
        (ROOT / "docs" / path).write_text(grants.add_decor(html), encoding="utf-8")


CHANGED_URLS = {"updated": [], "deleted": []}     # pagine cambiate in questo giro: avvisi a IndexNow e Google dopo il deploy


def _changed_docs():
    """{file in docs/: stato} dei file del sito diversi dall'ultimo commit: «M» cambiato o nuovo, «D» cancellato."""
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", "docs"], cwd=ROOT,
                             capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return None
    changed = {}
    for line in out.splitlines():
        st, path = line[:2], line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ")[-1]
        changed[path] = "D" if "D" in st else "M"
    return changed


def _page_path(file):
    """docs/jobs/x.html -> «jobs/x»; docs/index.html -> «» (indirizzi senza .html, come li serve Cloudflare)."""
    rel = Path(file).relative_to("docs").with_suffix("").as_posix()
    return "" if rel == "index" else rel


def write_sitemap():
    """sitemap.xml e robots.txt, perche' Google trovi tutte le pagine (anche quelle di singole posizioni e bandi).
    lastmod: la data dell'ultima modifica reale di ogni pagina (oggi solo se il contenuto e' cambiato), cosi'
    Google sa quali pagine ricontrollare."""
    import re as _re
    from xml.sax.saxutils import escape as xesc
    today = datetime.now().date().isoformat()
    sm = ROOT / "docs" / "sitemap.xml"
    old = sm.read_text(encoding="utf-8") if sm.exists() else ""
    prev = dict(_re.findall(r"<loc>([^<]+)</loc><lastmod>([^<]+)</lastmod>", old))
    changed = _changed_docs()
    files = (["docs/index.html"] + [f"docs/{p}.html" for p in ("calls", "positions", "methodology", "science", "feedback", "rss")]
             + sorted(f.relative_to(ROOT).as_posix() for f in JOBS_DIR.glob("*.html"))
             + sorted(f.relative_to(ROOT).as_posix() for f in CALLS_DIR.glob("*.html")))
    urls = []
    for f in files:
        loc = xesc(grants.site_url(CONFIG, _page_path(f)))
        fresh = changed is None or f in changed or loc not in prev
        urls.append(f"  <url><loc>{loc}</loc><lastmod>{today if fresh else prev[loc]}</lastmod></url>\n")
    sm.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                  f'{"".join(urls)}</urlset>\n', encoding="utf-8")
    (ROOT / "docs" / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {grants.site_url(CONFIG, 'sitemap.xml')}\n",
                                              encoding="utf-8")
    key = CONFIG.get("indexnow_key")
    if key:                                   # file di verifica di IndexNow (Bing, Yandex, Seznam, Naver...)
        (ROOT / "docs" / f"{key}.txt").write_text(key, encoding="utf-8")
    if changed:
        pages = {f: st for f, st in changed.items() if f.endswith(".html")}
        CHANGED_URLS["updated"] = sorted(grants.site_url(CONFIG, _page_path(f)) for f, st in pages.items() if st == "M")
        CHANGED_URLS["deleted"] = sorted(grants.site_url(CONFIG, _page_path(f)) for f, st in pages.items() if st == "D")


def notify_search_engines():
    """Dopo il deploy: IndexNow per tutte le pagine cambiate e, se attivo, Indexing API di Google per le posizioni
    (Google la ammette solo per le offerte di lavoro). Un errore qui non blocca nulla."""
    urls = CHANGED_URLS["updated"] + CHANGED_URLS["deleted"]
    if not urls or DRY_RUN:
        return
    key = CONFIG.get("indexnow_key")
    if key or CONFIG.get("google_indexing"):
        time.sleep(int(CONFIG.get("indexnow_wait_seconds", 120)))       # il tempo che Cloudflare pubblichi il sito
    if key:
        host = grants.site_url(CONFIG, "").split("/")[2]
        try:
            r = requests.post("https://api.indexnow.org/indexnow", timeout=60, json={
                "host": host, "key": key, "keyLocation": grants.site_url(CONFIG, f"{key}.txt"), "urlList": urls[:10000]})
            print(f"::notice title=IndexNow::{len(urls)} pagine segnalate ({r.status_code})")
        except requests.RequestException as e:
            print(f"::warning title=IndexNow::non raggiungibile: {e}")
    if CONFIG.get("google_indexing") and os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON"):
        jobs = [(u, "URL_UPDATED") for u in CHANGED_URLS["updated"] if "/jobs/" in u]
        jobs += [(u, "URL_DELETED") for u in CHANGED_URLS["deleted"] if "/jobs/" in u]
        try:
            from google.auth.transport.requests import AuthorizedSession
            creds = service_account.Credentials.from_service_account_info(
                json.loads(os.environ["GDRIVE_SERVICE_ACCOUNT_JSON"]), scopes=["https://www.googleapis.com/auth/indexing"])
            session, ok = AuthorizedSession(creds), 0
            for u, kind in jobs[:int(CONFIG.get("google_indexing_per_run", 100))]:      # quota Google: 200 al giorno
                r = session.post("https://indexing.googleapis.com/v3/urlNotifications:publish",
                                 json={"url": u, "type": kind}, timeout=30)
                ok += r.ok
                if not r.ok:
                    print(f"::warning title=Google Indexing API::{r.status_code} {r.text[:200]}")
                    break
            print(f"::notice title=Google Indexing API::{ok} di {len(jobs)} pagine di posizioni segnalate")
        except Exception as e:
            print(f"::warning title=Google Indexing API::{str(e)[:300]}")
    CHANGED_URLS["updated"], CHANGED_URLS["deleted"] = [], []


def write_home():
    """Pagina iniziale con i conteggi letti dalle due pagine (bandi e posizioni)."""
    import re as _re
    calls = PAGE_FILE.read_text(encoding="utf-8") if PAGE_FILE.exists() else ""
    jobs = POSITIONS_PAGE.read_text(encoding="utf-8") if POSITIONS_PAGE.exists() else ""
    n_calls = calls.count('class="call kf"') or calls.count("Official call &rarr;")
    m = _re.search(r'Open to Italy <b>(\d+)</b>', calls)
    n_positions = jobs.count('class="job kf"') or jobs.count("Advertisement &rarr;")
    import methodology
    methods = methodology.load()
    (ROOT / "docs" / "methodology.html").write_text(grants.add_decor(methodology.build_page(methods, CONFIG)), encoding="utf-8")
    import science
    (ROOT / "docs" / "science.html").write_text(grants.add_decor(science.build_page(methods, CONFIG)), encoding="utf-8")
    import feedback
    (ROOT / "docs" / "feedback.html").write_text(grants.add_decor(feedback.build_page(CONFIG)), encoding="utf-8")
    (ROOT / "docs" / "rss.html").write_text(grants.add_decor(feedback.build_feeds_page(CONFIG)), encoding="utf-8")
    HOME_FILE.write_text(grants.add_decor(grants.build_home(n_calls, int(m.group(1)) if m else 0, n_positions, CONFIG,
                                                            n_methods=sum(1 for e in methods.values() if not e.get("duplicate_of")
                                                                         and e.get("category") != content.CLINICAL_CATEGORY),
                                                            n_science=len(science.entries(methods)))),
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
        if r.ok:
            notify_search_engines()
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
    if os.environ.get("CONFIRM_STRONG", "1") != "0":      # secondo parere dei forti sui bandi ad alta priorità
        if grants.confirm_candidates(grants_list, verified, posted, CONFIG):
            save(ROOT / grants.VERIFIED_FILE, verified)
    PAGE_FILE.parent.mkdir(exist_ok=True)
    PAGE_FILE.write_text(grants.add_decor(grants.build_page(grants_list, verified, posted, CONFIG)), encoding="utf-8")
    (ROOT / "docs" / "feed-calls.xml").write_text(grants.calls_feed(grants_list, verified, CONFIG), encoding="utf-8")
    write_call_pages(grants_list, verified)
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
    inbox = [f for f in list_inbox(drive, os.environ["GDRIVE_FOLDER_ID"]) if f["id"] not in seen]
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
    if SIMULATE:
        print("::notice title=Rettifiche::social in pausa: nessun commento pubblicato")
        return
    items = load(CORRECTIONS_FILE, [])
    posted = {p.get("id"): p for p in load(POSTED_FILE, [])}
    token = os.environ["IG_ACCESS_TOKEN"]
    fb_token = meta_token.ensure_page_token()
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
    if SIMULATE:
        print("::notice title=Arretrati social::social in pausa: niente ripubblicazioni")
        return
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
            link = grants.site_url(CONFIG, polish.page_anchor({"id": p["id"], "category": m.get("category")}))
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


def repost_social():
    """Ripubblica su Facebook e Bluesky (con la grafica nuova) post già usciti: REPOST_IDS = id separati da virgola.
    Le immagini singole si ricreano dai dati salvati (libreria metodologia, registro dei bandi) e si salvano accanto alle slide."""
    import social, methodology
    ids = [i.strip() for i in (os.environ.get("REPOST_IDS") or "").split(",") if i.strip()]
    posted = load(POSTED_FILE, [])
    methods = methodology.load()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    for p in posted:
        if p["id"] not in ids:
            continue
        if p.get("kind") == "grant":
            d = grants._date(p.get("deadline"))
            post = {"kind": "grant", "id": p["id"], "grant_id": p.get("grant_id", ""), "title": p["title"], "funder": p.get("funder", ""),
                    "deadline": grants._fmt_date(d) if d else "", "slides": [], "takeaway": ""}
            caption = f"{p['title']}\n\nNext deadline: {grants._fmt_date(d) if d else ''}.\n\n{p.get('summary', '')}"
            link = grants.site_url(CONFIG, "calls#" + grants.card_anchor(p.get("grant_id", "")))
            kind = "grant"
        else:
            m = methods.get(p["id"])
            if not m:
                print(f"::warning title=Ripubblicazione::{p['id']} non è nella libreria metodologia: salto")
                continue
            post = {"id": p["id"], "title": m["title"], "category": m.get("category", "Research methods"),
                    "slides": [{"heading": x["heading"], "body": x["body"]} for x in m.get("points", [])],
                    "takeaway": m.get("takeaway", ""), "references": m.get("references", [])}
            heads = " · ".join(x["heading"] for x in m.get("points", []))
            caption = f"{m['title']}\n\n{m.get('takeaway', '')}\n\nKey points: {heads}"
            link = grants.site_url(CONFIG, polish.page_anchor({"id": p["id"], "category": m.get("category")}))
            kind = "research"
        os.environ["POST_TYPE"] = kind            # la sicura dei social riconosce le rubriche attive (es. grant)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in p["id"])
        folder = IMAGES_DIR / f"{p['date']}-{safe}"
        folder.mkdir(parents=True, exist_ok=True)
        single = folder / "cover-single.jpg"
        single.write_bytes(cards.single_cover(post, CONFIG))
        rels = [single.relative_to(ROOT).as_posix()]
        fb_path = None
        if kind == "research":
            fb_path = folder / "facebook.jpg"
            fb_path.write_bytes(cards.facebook_single(post, CONFIG))
            rels.append(fb_path.relative_to(ROOT).as_posix())
        sha = commit_and_push(rels, f"Immagini social nel nuovo design: {p['title'][:50]}")
        base = f"https://raw.githubusercontent.com/{os.environ['GITHUB_REPOSITORY']}/{sha}/"
        fb_url = base + (rels[-1])
        wait_until_public(fb_url)
        if CONFIG.get("facebook", True) and os.environ.get("FB_PAGE_ID") and not p.get("facebook_id"):
            try:
                p["facebook_id"] = publish_facebook_single(fb_url, facebook_text({**post, "caption": caption}, caption, None if kind == "research" else kind, link))
                print(f"::notice title=Facebook (nuovo design)::{p['title'][:60]} → {p['facebook_id']}")
            except Exception as e:
                print(f"::warning title=Facebook non ripubblicato::{str(e)[:300]}")
        if social.bluesky_enabled() and not p.get("bluesky_uri"):      # già uscito lì: niente doppione
            try:
                p["bluesky_uri"] = social.publish_bluesky([single], {**post, "caption": caption}, link, max_images=1)
                print(f"::notice title=Bluesky (nuovo design)::{p['title'][:60]} → {p['bluesky_uri']}")
            except Exception as e:
                print(f"::warning title=Bluesky non ripubblicato::{str(e)[:300]}")
        p["reposted"] = datetime.now(timezone.utc).date().isoformat()
        save(POSTED_FILE, posted)
        commit_and_push([POSTED_FILE.name], f"Ripubblicato nel nuovo design: {p['title'][:60]}")
        time.sleep(30)


if __name__ == "__main__":
    if "--repost" in sys.argv:
        repost_social()
    elif "--status" in sys.argv:
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
