"""Genera con Pollinations.ai le illustrazioni AI per le slide con immagine."""

import hashlib
import io
import os
import time
from urllib.parse import quote

import requests
from PIL import Image

NEW_API = "https://gen.pollinations.ai/image/"
LEGACY_API = "https://image.pollinations.ai/prompt/"

# Stile comune: pochi colori, in accordo con il brand (blu notte + turchese) e un solo accento caldo.
STYLE = (
    "flat editorial vector illustration, minimal and clean, simple geometric shapes, "
    "deep navy blue background, teal and soft white elements, one small warm coral accent, "
    "limited color palette of four colors, soft light, plenty of empty space, "
    "no text, no letters, no words, no numbers, no labels, no logos, no watermark"
)


def build_prompt(slide):
    """Prompt visivo della slide: quello scritto da Gemini o, in mancanza, uno ricavato dal titolo."""
    subject = (slide.get("image_prompt") or "").strip()
    if not subject:
        subject = f"a visual metaphor for the clinical research concept: {slide['heading']}"
    return f"{subject}. {STYLE}"


def _seed(text):
    # stesso prompt → stesso seed, così l'anteprima e la pubblicazione mostrano la stessa immagine
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16) % 1_000_000


def generate(slide, cfg, width=1024, height=640):
    """Restituisce un'immagine PIL, oppure None se Pollinations non risponde (la slide resta solo testo)."""
    prompt = build_prompt(slide)
    params = {"width": width, "height": height, "seed": _seed(prompt), "nologo": "true"}
    model = cfg.get("image_model")
    if model:
        params["model"] = model
    key = os.environ.get("POLLINATIONS_API_KEY")
    if key:
        url, headers = NEW_API + quote(prompt, safe=""), {"Authorization": f"Bearer {key}"}
    else:
        url, headers = LEGACY_API + quote(prompt, safe=""), {}

    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=120)
            if r.ok and r.headers.get("content-type", "").startswith("image/"):
                return Image.open(io.BytesIO(r.content)).convert("RGB")
            print(f"  Pollinations: risposta {r.status_code} ({r.text[:150]!r})")
            if r.status_code in (401, 402, 403):
                break   # chiave mancante, errata o credito finito: inutile riprovare
            wait = int(r.headers.get("Retry-After", 0) or 0) or 15 * (attempt + 1)
        except requests.RequestException as e:
            print(f"  Pollinations non raggiungibile: {e}")
            wait = 15 * (attempt + 1)
        time.sleep(min(wait, 60))
    print(f"  Immagine non generata, la slide «{slide['heading']}» resta solo testo.")
    return None
