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


def generate(slide, cfg, width=1024, height=640):
    """Restituisce un'immagine PIL, oppure None se Pollinations non risponde (la slide resta solo testo)."""
    global _key_failed
    prompt = build_prompt(slide)
    params = {"width": width, "height": height, "seed": _seed(prompt), "nologo": "true",
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
