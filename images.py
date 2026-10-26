"""Immagini delle slide: illustrazioni AI generate con Pollinations.ai e, se c'è PIXABAY_API_KEY, foto vere da Pixabay
(API ufficiale; licenza Pixabay: uso commerciale senza attribuzione). Gemini sceglie la candidata migliore."""

import hashlib
import io
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image

NEW_API = "https://gen.pollinations.ai/image/"
LEGACY_API = "https://image.pollinations.ai/prompt/"
DEFAULT_MODEL = "flux"
MIN_GAP = 47          # piano gratuito: 1 immagine ogni 45 secondi per IP
_last_call = 0.0

# Lo stile va in testa al prompt (Flux dà più peso alle prime parole) e i divieti in coda.
STYLE_HEAD = "Flat 2D vector illustration, minimalist editorial style, clean simple shapes"
STYLE_TAIL = (
    "Solid deep navy blue background, teal and white shapes, one small coral accent, "
    "four-color palette, flat colors without gradients, centered composition with empty space around. "
    "Not 3D, not a render, not photorealistic, no perspective depth, "
    "no text, no letters, no numbers, no labels, no logos, no watermark"
)


def build_prompt(slide):
    """Prompt visivo della slide: quello scritto da Gemini o, in mancanza, uno ricavato dal titolo."""
    subject = (slide.get("image_prompt") or "").strip().rstrip(".")
    if not subject:
        subject = f"a simple visual metaphor for the clinical research concept: {slide['heading']}"
    return f"{STYLE_HEAD}: {subject}. {STYLE_TAIL}"


def _seed(text):
    # stesso prompt → stesso seed, così l'anteprima e la pubblicazione mostrano la stessa immagine
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16) % 1_000_000


def _retry_after(r, default):
    """Secondi da attendere: dall'header Retry-After o dal messaggio («Retry after 39s»)."""
    header = r.headers.get("Retry-After")
    if header and header.isdigit():
        return int(header) + 2
    m = re.search(r"[Rr]etry after (\d+)", r.text)
    return int(m.group(1)) + 2 if m else default


def _wait_turn():
    """Rispetta il limite gratuito lasciando almeno MIN_GAP secondi tra una richiesta e l'altra."""
    global _last_call
    gap = time.time() - _last_call
    if _last_call and gap < MIN_GAP:
        time.sleep(MIN_GAP - gap)
    _last_call = time.time()


_key_failed = False   # chiave senza credito o non valida: per il resto del run si usa il piano anonimo


def _request(url, params, headers, anonymous):
    """Fino a 4 tentativi. Restituisce (immagine, None) oppure (None, motivo del fallimento)."""
    for attempt in range(4):
        if anonymous:
            _wait_turn()
        try:
            r = requests.get(url, params=params, headers=headers, timeout=120)
            if r.ok and r.headers.get("content-type", "").startswith("image/"):
                return Image.open(io.BytesIO(r.content)).convert("RGB"), None
            print(f"  Pollinations: risposta {r.status_code} ({r.text[:150]!r})")
            limit = r.status_code == 429 or "FREE_LIMIT" in r.text or "limit" in r.text.lower()
            if r.status_code in (401, 403) or (r.status_code == 402 and not limit):
                return None, "key"   # chiave errata o credito finito: inutile riprovare
            wait = _retry_after(r, 30 * (attempt + 1))
        except requests.RequestException as e:
            print(f"  Pollinations non raggiungibile: {e}")
            wait = 30 * (attempt + 1)
        print(f"  Riprovo tra {min(wait, 90)} secondi…")
        time.sleep(min(wait, 90))
    return None, "down"


JUDGE_PROMPT = """You are the art director of an Instagram page for clinical researchers. Below is the text of
one carousel slide, followed by {n} candidate illustrations (Image 1 ... Image {n}).

Slide heading: {heading}
Slide text: {body}

For EACH image return:
- relevance: 1-10, how clearly a researcher would connect the image to the slide's idea at a glance
  (10 = the visual metaphor explains the concept; 1 = unrelated or generic decoration).
- has_text: true if the image contains any letters, words, numbers or fake writing.
- style_ok: for an ILLUSTRATION, true if it is a clean flat 2D vector illustration (no 3D render, no photorealism,
  no clutter), with dark navy background and teal/white elements. For a PHOTO, true if it is a sharp, natural,
  professional photo of a real scene, with no visible brand names or logos, no graphic or distressing medical
  content and no cheesy staged-stock look.
- problems: a few words on what is wrong ("" if nothing).
Prefer the image that best explains the slide: a photo only when it shows the idea better than an illustration."""

JUDGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"images": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "relevance": {"type": "INTEGER"}, "has_text": {"type": "BOOLEAN"}, "style_ok": {"type": "BOOLEAN"},
        "problems": {"type": "STRING"}}, "required": ["relevance", "has_text", "style_ok", "problems"]}}},
    "required": ["images"],
}


PIXABAY_API = "https://pixabay.com/api/"
USED_FILE = Path(__file__).resolve().parent / "pixabay_used.json"
LAST = {}


def _used():
    import json
    try:
        return set(json.loads(USED_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def mark_used(pid):
    """Registra la foto Pixabay usata in un post pubblicato (mai la stessa foto due volte)."""
    import json
    ids = sorted(_used() | {int(pid)})
    USED_FILE.write_text(json.dumps(ids), encoding="utf-8")


def pixabay_photos(query, n=2, width=1024, height=640):
    """Fino a n foto orizzontali da Pixabay per la ricerca `query`, mai usate prima: [(immagine, id)]."""
    key = os.environ.get("PIXABAY_API_KEY")
    if not key or not query.strip():
        return []
    try:
        r = requests.get(PIXABAY_API, timeout=30, params={
            "key": key, "q": query.strip()[:100], "image_type": "photo", "orientation": "horizontal",
            "safesearch": "true", "min_width": width, "min_height": height, "per_page": 20, "order": "popular"})
        if not r.ok:
            print(f"  Pixabay non risponde ({r.status_code}): solo illustrazioni AI.")
            return []
        hits = r.json().get("hits", [])
    except Exception as e:
        print(f"  Pixabay non raggiungibile ({e}): solo illustrazioni AI.")
        return []
    used, out = _used(), []
    for h in hits:
        if h["id"] in used:
            continue
        try:
            img = Image.open(io.BytesIO(requests.get(h["largeImageURL"], timeout=60).content)).convert("RGB")
        except Exception:
            continue
        out.append((img, h["id"]))
        if len(out) == n:
            break
    print(f"  Pixabay «{query}»: {len(hits)} risultati, {len(out)} foto candidate")
    return out


def choose_best(slide, pictures, cfg, kinds=None):
    """Gemini guarda le candidate insieme al testo della slide e sceglie la migliore.
    Restituisce None se nessuna è pertinente, pulita e in stile (la slide resta solo testo)."""
    import base64
    import content
    kinds = kinds or ["illustration"] * len(pictures)
    parts = [{"text": JUDGE_PROMPT.format(n=len(pictures), heading=slide["heading"], body=slide["body"])}]
    for i, (pic, kind) in enumerate(zip(pictures, kinds), 1):
        buf = io.BytesIO()
        pic.convert("RGB").resize((512, 320)).save(buf, "JPEG", quality=85)
        parts += [{"text": f"Image {i} ({kind.upper()}):"},
                  {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}]
    try:
        scores = content.gemini_json(parts, JUDGE_SCHEMA, 0.0, task="scelta immagini").get("images", [])
    except Exception as e:
        print(f"  Valutazione delle immagini non riuscita ({e}): uso la prima candidata.")
        return pictures[0]
    minimum = int(cfg.get("image_min_relevance", 6))
    best, best_score = None, -1
    for i, (pic, sc) in enumerate(zip(pictures, scores), 1):
        ok = not sc.get("has_text") and sc.get("style_ok") and int(sc.get("relevance", 0)) >= minimum
        print(f"  Candidata {i} ({kinds[i - 1]}): pertinenza {sc.get('relevance')}, testo {sc.get('has_text')}, "
              f"stile {sc.get('style_ok')}{' – ' + sc['problems'] if sc.get('problems') else ''}")
        if ok and int(sc["relevance"]) > best_score:
            best, best_score = pic, int(sc["relevance"])
    LAST["kind"] = kinds[pictures.index(best)] if best is not None else None
    if best is None:
        print(f"  Nessuna candidata abbastanza buona: la slide «{slide['heading']}» resta solo testo.")
    return best


def generate(slide, cfg, width=1024, height=640):
    """Genera alcune candidate (config «image_candidates», default 3) e tiene la migliore secondo Gemini.
    Restituisce None se non ce n'è una adatta o se Pollinations non risponde (la slide resta solo testo)."""
    n = max(1, int(cfg.get("image_candidates", 3)))
    pictures, kinds, ids = [], [], []
    for i in range(n):
        pic = generate_one(slide, cfg, width, height, variant=i)
        if pic is not None:
            pictures.append(pic)
            kinds.append("illustration")
            ids.append(None)
    if cfg.get("pixabay_photos", True):
        for pic, pid in pixabay_photos(slide.get("photo_query", ""), int(cfg.get("pixabay_candidates", 2)), width, height):
            pictures.append(pic)
            kinds.append("photo")
            ids.append(pid)
    LAST.clear()
    if not pictures:
        return None
    if len(pictures) == 1 and not cfg.get("image_judge_single", True):
        best = pictures[0]
    else:
        best = choose_best(slide, pictures, cfg, kinds)
    if best is not None:
        k = pictures.index(best)
        LAST.update(kind=kinds[k], pixabay_id=ids[k])
        if ids[k]:
            slide["pixabay_id"] = ids[k]          # registrata in pixabay_used.json quando il post esce
            print(f"  Scelta la foto Pixabay {ids[k]}")
    return best


def generate_one(slide, cfg, width=1024, height=640, variant=0):
    """Una sola immagine da Pollinations (seed diverso per ogni variante), oppure None."""
    global _key_failed
    prompt = build_prompt(slide)
    params = {"width": width, "height": height, "seed": (_seed(prompt) + variant * 7919) % 1_000_000, "nologo": "true",
              "model": cfg.get("image_model") or DEFAULT_MODEL}
    key = os.environ.get("POLLINATIONS_API_KEY")

    if key and not _key_failed:
        img, why = _request(NEW_API + quote(prompt, safe=""), params,
                            {"Authorization": f"Bearer {key}"}, anonymous=False)
        if img is not None:
            return img
        if why == "key":
            _key_failed = True
            print("  La chiave Pollinations non funziona (credito finito?): passo al piano gratuito anonimo.")
        else:
            print(f"  Immagine non generata, la slide «{slide['heading']}» resta solo testo.")
            return None

    img, _ = _request(LEGACY_API + quote(prompt, safe=""), params, {}, anonymous=True)
    if img is None:
        print(f"  Immagine non generata, la slide «{slide['heading']}» resta solo testo.")
    return img
