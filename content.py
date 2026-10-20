"""Legge il materiale (PDF, slide, documenti, appunti) e chiede a Gemini di trasformarlo in post."""

import base64
import io
import json
import os
import time
from pathlib import Path

import requests

GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-flash-latest"
MAX_INLINE_BYTES = 15 * 1024 * 1024
MAX_TEXT_CHARS = 300_000

GOOGLE_DOC = "application/vnd.google-apps.document"
GOOGLE_SLIDES = "application/vnd.google-apps.presentation"
PDF = "application/pdf"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

SUPPORTED = {GOOGLE_DOC, GOOGLE_SLIDES, PDF, PPTX, DOCX}
TEXT_EXT = {".txt", ".md", ".markdown"}

CATEGORIES = [
    "Study design", "Bias & confounding", "Randomization & blinding", "Sample size & power",
    "Endpoints & outcomes", "Statistics", "Research ethics", "Informed consent", "GCP & regulation",
    "Data management", "Reporting & publication", "Critical appraisal", "Research methods",
]

PROMPT = """You create Instagram carousel posts for "{brand}", a page for researchers and health
professionals about clinical research on human subjects and research methodology.

You are given teaching material written by the page owner (slides, notes or a document; it may be in
Italian or another language). Turn it into self-contained educational posts IN ENGLISH.

STRICT ACCURACY RULES (this audience will notice mistakes):
- Use ONLY content that is in the material. You may rephrase and clarify, and you may define a
  standard methodological term in a widely accepted way, but do NOT add new facts.
- Never invent numbers, statistics, study results, guideline versions, regulations, author names or
  references. Mention a guideline, study or reference only if the material names it.
- No medical or clinical treatment advice. If the material has nothing about research or methodology,
  return an empty list.
- Skip slides that are only titles, agendas, logistics or thanks.

POST DESIGN:
- One clear concept per post; produce as many posts as the material genuinely supports (0-{max_posts}),
  each different from the others.
- title: a sharp hook, max 70 characters (e.g. a common misconception, a question, a crisp claim).
- slides: 3 to 5 slides, each with heading (max 55 characters), body (max 220 characters,
  plain language for professionals, concrete, no fluff) and image_prompt.
- image_prompt: in English, 15-35 words describing ONE simple illustration that a researcher would
  connect to the slide's idea at a glance. Describe a concrete scene with 2-4 recognizable elements
  (people, pills, envelopes, blindfolds, scales, magnifying glass, documents, arrows, groups of figures)
  and what they are doing; the scene must show the CONCEPT, not just the setting (never just a
  hospital bed, a lab or a generic doctor). Good examples:
  "a patient and a doctor both wearing blindfolds, seated at a table with two identical pill bottles";
  "a crowd of simple figures split by a large coin into two equal groups, each walking toward a pill bottle";
  "a magnifying glass revealing a hidden crack in a perfect-looking bridge".
  No text, letters, numbers, labeled charts, logos or recognizable real people.
- takeaway: the single sentence to remember, max 130 characters.
- caption: 3-6 short lines that add context beyond the slides, end with a question that invites
  professionals to share their experience. Max 900 characters. No hashtags inside the caption.
- hashtags: 8-12 specific hashtags (e.g. #ClinicalTrials #Biostatistics #ResearchEthics).
- category: one of {categories}.
- source_hint: where in the material this comes from (e.g. "slides 12-15"), for the owner's review.

File name of the material: {filename}"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "posts": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "category": {"type": "STRING"},
                    "slides": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {"heading": {"type": "STRING"}, "body": {"type": "STRING"},
                                           "image_prompt": {"type": "STRING"}},
                            "required": ["heading", "body", "image_prompt"],
                        },
                    },
                    "takeaway": {"type": "STRING"},
                    "caption": {"type": "STRING"},
                    "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "source_hint": {"type": "STRING"},
                },
                "required": ["title", "category", "slides", "takeaway", "caption", "hashtags"],
            },
        }
    },
    "required": ["posts"],
}


# ---------------------------------------------------------------- lettura materiale
def _download(drive, file_id):
    from googleapiclient.http import MediaIoBaseDownload
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, drive.files().get_media(fileId=file_id, supportsAllDrives=True))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue()


def _export(drive, file_id, mime):
    return drive.files().export(fileId=file_id, mimeType=mime).execute()


def _pdf_part(data):
    if len(data) <= MAX_INLINE_BYTES:
        return {"inline_data": {"mime_type": PDF, "data": base64.b64encode(data).decode()}}
    from pypdf import PdfReader  # PDF troppo grande: si invia solo il testo
    text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    return {"text": text[:MAX_TEXT_CHARS]}


def _pptx_text(data):
    from pptx import Presentation
    out = []
    for n, slide in enumerate(Presentation(io.BytesIO(data)).slides, start=1):
        texts = [s.text_frame.text for s in slide.shapes if s.has_text_frame and s.text_frame.text.strip()]
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            texts.append("Speaker notes: " + slide.notes_slide.notes_text_frame.text)
        if texts:
            out.append(f"--- Slide {n} ---\n" + "\n".join(texts))
    return "\n\n".join(out)


def _docx_text(data):
    from docx import Document
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts)


def is_supported(f):
    return f["mimeType"] in SUPPORTED or Path(f["name"]).suffix.lower() in TEXT_EXT | {".pdf", ".pptx", ".docx"}


def material_part(drive, f):
    """Restituisce il materiale nel formato richiesto da Gemini, o None se non leggibile."""
    mime, ext = f["mimeType"], Path(f["name"]).suffix.lower()
    if mime == GOOGLE_DOC:
        return {"text": _export(drive, f["id"], "text/plain").decode("utf-8", "ignore")[:MAX_TEXT_CHARS]}
    if mime == GOOGLE_SLIDES:
        return _pdf_part(_export(drive, f["id"], PDF))
    data = _download(drive, f["id"])
    if mime == PDF or ext == ".pdf":
        return _pdf_part(data)
    if mime == PPTX or ext == ".pptx":
        return {"text": _pptx_text(data)[:MAX_TEXT_CHARS]}
    if mime == DOCX or ext == ".docx":
        return {"text": _docx_text(data)[:MAX_TEXT_CHARS]}
    if ext in TEXT_EXT:
        return {"text": data.decode("utf-8", "ignore")[:MAX_TEXT_CHARS]}
    return None


# ---------------------------------------------------------------- Gemini
def _clip(text, n):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def _clean_post(p):
    slides = [
        {"heading": _clip(s.get("heading", ""), 70), "body": _clip(s.get("body", ""), 320),
         "image_prompt": _clip(s.get("image_prompt", ""), 300)}
        for s in p.get("slides", []) if s.get("heading") and s.get("body")
    ][:5]
    if len(slides) < 2 or not p.get("title") or not p.get("takeaway"):
        return None
    tags = ["#" + t.lstrip("#").replace(" ", "") for t in p.get("hashtags", []) if t.strip("# ")]
    category = p.get("category") if p.get("category") in CATEGORIES else "Research methods"
    return {
        "title": _clip(p["title"], 90),
        "category": category,
        "slides": slides,
        "takeaway": _clip(p["takeaway"], 160),
        "caption": p.get("caption", "").strip()[:1200],
        "hashtags": tags[:15],
        "source_hint": p.get("source_hint", ""),
    }


def gemini_json(parts, schema, temperature=0.5):
    """Chiede a Gemini una risposta JSON conforme allo schema e la restituisce già decodificata."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY mancante")
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    last_error = None
    for attempt in range(3):
        r = requests.post(url, headers={"x-goog-api-key": key}, json=body, timeout=300)
        if r.status_code == 429 or r.status_code >= 500:
            last_error = f"{r.status_code}: {r.text[:300]}"
            time.sleep(30 * (attempt + 1))
            continue
        if not r.ok:
            raise RuntimeError(f"Errore Gemini {r.status_code}: {r.text[:500]}")
        text = "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
        return json.loads(text)
    raise RuntimeError(f"Gemini non disponibile: {last_error}")


def generate_posts(part, filename, brand, max_posts=12):
    prompt = PROMPT.format(brand=brand, max_posts=max_posts, filename=filename,
                           categories=", ".join(CATEGORIES))
    posts = gemini_json([{"text": prompt}, part], SCHEMA).get("posts", [])
    return [c for c in (_clean_post(p) for p in posts) if c][:max_posts]
