"""Genera con Pollinations.ai le illustrazioni AI per le slide con immagine."""

import hashlib
import io
import os
import re
import time
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
- style_ok: true if it is a clean flat 2D vector illustration (no 3D render, no photorealism, no clutter),
  with dark navy background and teal/white elements.
- problems: a few words on what is wrong ("" if nothing)."""

JUDGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"images": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "relevance": {"type": "INTEGER"}, "has_text": {"type": "BOOLEAN"}, "style_ok": {"type": "BOOLEAN"},
        "problems": {"type": "STRING"}}, "required": ["relevance", "has_text", "style_ok", "problems"]}}},
    "required": ["images"],
}


def choose_best(slide, pictures, cfg):
    """Gemini guarda le candidate insieme al testo della slide e sceglie la migliore.
    Restituisce None se nessuna è pertinente, pulita e in stile (la slide resta solo testo)."""
    import base64
    import content
    parts = [{"text": JUDGE_PROMPT.format(n=len(pictures), heading=slide["heading"], body=slide["body"])}]
    for i, pic in enumerate(pictures, 1):
        buf = io.BytesIO()
        pic.convert("RGB").resize((512, 320)).save(buf, "JPEG", quality=85)
        parts += [{"text": f"Image {i}:"},
                  {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}]
    try:
        scores = content.gemini_json(parts, JUDGE_SCHEMA, 0.0).get("images", [])
    except Exception as e:
        print(f"  Valutazione delle immagini non riuscita ({e}): uso la prima candidata.")
        return pictures[0]
    minimum = int(cfg.get("image_min_relevance", 6))
    best, best_score = None, -1
    for i, (pic, sc) in enumerate(zip(pictures, scores), 1):
        ok = not sc.get("has_text") and sc.get("style_ok") and int(sc.get("relevance", 0)) >= minimum
        print(f"  Candidata {i}: pertinenza {sc.get('relevance')}, testo {sc.get('has_text')}, "
              f"stile {sc.get('style_ok')}{' – ' + sc['problems'] if sc.get('problems') else ''}")
        if ok and int(sc["relevance"]) > best_score:
            best, best_score = pic, int(sc["relevance"])
    if best is None:
        print(f"  Nessuna candidata abbastanza buona: la slide «{slide['heading']}» resta solo testo.")
    return best


def generate(slide, cfg, width=1024, height=640):
    """Genera alcune candidate (config «image_candidates», default 3) e tiene la migliore secondo Gemini.
    Restituisce None se non ce n'è una adatta o se Pollinations non risponde (la slide resta solo testo)."""
    n = max(1, int(cfg.get("image_candidates", 3)))
    pictures = []
    for i in range(n):
        pic = generate_one(slide, cfg, width, height, variant=i)
        if pic is not None:
            pictures.append(pic)
    if not pictures:
        return None
    return choose_best(slide, pictures, cfg) if len(pictures) > 1 or cfg.get("image_judge_single", True) else pictures[0]


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
