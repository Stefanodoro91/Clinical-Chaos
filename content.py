"""Legge il materiale (PDF, slide, documenti, appunti) e chiede a Gemini di trasformarlo in post."""

import base64
import io
import json
import os
import re
import time
import unicodedata
from pathlib import Path

import requests

GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-flash-latest"
GEMINI_FALLBACK = os.environ.get("GEMINI_FALLBACK_MODEL") or "gemini-flash-lite-latest"
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
  each different from the others. Fewer excellent posts are better than many thin ones.
- Build each post as ONE argument: the slides follow a logical order (the problem or misconception → why it
  matters, with the mechanism, an example or a number from the material → how to do it right) and lead to the
  takeaway. No slide may be a loose fact that the reader cannot connect to the title. Plan the argument first, then
  write the title LAST, as the claim the slides actually demonstrate: the title and the hook must never promise more
  than the slides show, and no slide may contradict them.
- Keep the scope of the material. A simplified rule stays with its conditions ("for a binary outcome…", "when the
  sample is small…"); if the material names alternatives or exceptions (other models, other outcome types, other
  designs), mention them rather than turning one option into the only one. Never overstate: no "destroys",
  "always fails", "useless", "must" unless the material says so in those terms.
- SOURCE FIDELITY: every slide must derive directly from a specific point in the material. Never add an
  example, comparison, case or reference that is not explicitly present in the source document, even if it is
  accurate and contextually plausible. If the material gives no example, write no example. If the material cites
  no study for a statement, name no study. A generic example is allowed only when the material itself uses one,
  and only in the same field and framing the material uses ("imagine a trial of 120 patients with…"). Never
  import a study, trial, drug or clinical field that the material does not discuss, and never use a named study
  to illustrate a point the material does not attach to it.
- Every slide must teach something. Never a slide that only announces its topic or asks a question without the
  answer ("Who answers the questionnaire?", "Secondary outcomes measured", "Dual roles can be difficult"): the
  heading may ask, the body must give the content.
- A statement keeps the setting of the source that makes it: a finding on chronic disease in general is never
  presented as a finding "in neurological rehabilitation"; a rule for RCTs is never extended to observational
  studies unless the material does so.
- Direction words always say of what: "rate quality of life higher", "rate disability as more severe", never
  "rate patients higher". Two slides must never seem to point in opposite directions on the same comparison.
- No hype or absolute verdicts the material does not use: "massive", "huge", "dramatically", "completely",
  "illogical", "boosts", "destroys", "always", "never", "proves".
- Every sentence must be true and complete ON ITS OWN: name the subject (never "this", "it", "these patients",
  "the study", "the authors" without saying which), keep the condition under which a claim holds (population,
  design, threshold), keep the qualifiers of the material ("may", "in RCTs", "at least", "only"), and give numbers
  with their unit and comparison. Use exact methodological language: risk vs odds, association vs causation,
  statistical vs clinical significance, efficacy vs effectiveness; never "proves".
- title: a sharp hook, max 70 characters (e.g. a common misconception, a question, a crisp claim), in sentence
  case (only the first word and proper names capitalised, e.g. "Linear or logistic regression? Look at your outcome";
  also after a colon: "Parametric vs nonparametric: the cost of power").
  Slide headings are in sentence case too.
- slides: 3 to 5 slides (the carousel adds cover and a final takeaway slide: 5–7 slides in total), each with heading (max 55 characters), body (max 140 characters including spaces, COUNT THEM: a longer body is cut at the last full sentence; few words, large type,
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
- photo_query (per slide): 2-4 English keywords to search a real stock PHOTO that fits the slide
  (e.g. "physiotherapist knee rehabilitation", "researchers meeting whiteboard", "pills blister pack"),
  only for slides whose idea a real scene can show; "" when the idea is too abstract for a photo.
- Each slide carries ONE concept and must make sense on its own, even as a screenshot: never refer to the
  structure of the source ("step six", "section 3", "this guideline"); spell out every acronym the first time it
  appears in the carousel (e.g. "patient-reported outcome measures (PROMs)"). Write numbers as digits
  (0.955, 12%, 95% CI), never spelled out in words.
- highlight (per slide): the key idea of that slide, 2-6 words copied EXACTLY from its body (same
  words, same order); it is shown with a highlighter.
- source (per slide): short citation "Surname, Year" or "Surname et al., Year". When the material is itself a
  published paper, its own citation is the default source of every slide; cite another work only when the material
  explicitly attributes THAT specific statement to it, and that work must be in references. Otherwise "".
- title_highlight: 1-4 words copied EXACTLY from the title, the most important part of the hook.
- takeaway: the take-home message, max 130 characters: one specific, true statement that follows from the slides and
  that a researcher can act on (name the method, check, threshold or decision). Never "X is important", never a
  vague exhortation, never the title restated.
- takeaway_highlight: 2-5 words copied EXACTLY from the takeaway.
- references: in APA 7 style (Author, A. A., & Author, B. B. (Year). Title in sentence case. Journal Name,
  volume(issue), pages. https://doi.org/...). FIRST the material itself when it is a published paper (as printed on
  its first page). Then ONLY the works that the material cites for a statement used in this post's slides, so that
  every slide source is in this list; never list a work just because it is in the material's bibliography, and
  never a work whose role in the post the reader cannot see. Copy authors, year, title and journal from the
  material; if an element is missing, leave it out: NEVER invent authors, years, titles, journals or DOIs.
  Use plain characters ("&", not "&amp;"). Empty list if there is nothing to cite.
- hook: the FIRST line of the caption, max 120 characters (Instagram shows only about 125 characters
  before "more"). It must make a researcher stop scrolling: name a common mistake, a counter-intuitive
  consequence, or ask a sharp question that the post answers. Use only the material: no invented numbers,
  no clickbait, no hashtags, at most one emoji. Do not repeat the title word for word. Include the main
  searchable term of the topic (e.g. "PICO", "sample size", "blinding"): Instagram search reads the first line.
- caption: 3-6 short lines that come AFTER the hook and add context beyond the slides; end with a question
  that invites professionals to share their experience. Max 900 characters. No hashtags inside the caption.
- hashtags: 3 specific hashtags for the topic (e.g. #ClinicalTrials #Biostatistics #ResearchEthics); Instagram
  allows at most 5 per post and the bot adds #ClinicalResearch and #ResearchMethodology.
- category: one of {categories}.
- source_hint: where in the material this comes from (e.g. "slides 12-15"), for the owner's review.

Already published posts (do not repeat these topics): {published}

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
                                           "image_prompt": {"type": "STRING"}, "photo_query": {"type": "STRING"},
                                           "highlight": {"type": "STRING"}, "source": {"type": "STRING"}},
                            "required": ["heading", "body", "image_prompt", "photo_query", "highlight", "source"],
                        },
                    },
                    "title_highlight": {"type": "STRING"},
                    "takeaway": {"type": "STRING"},
                    "takeaway_highlight": {"type": "STRING"},
                    "references": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "hook": {"type": "STRING"},
                    "caption": {"type": "STRING"},
                    "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "source_hint": {"type": "STRING"},
                },
                "required": ["title", "title_highlight", "category", "slides", "takeaway",
                             "takeaway_highlight", "hook", "caption", "hashtags", "references"],
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


def pdf_abstract_text(data, max_chars=3000):
    """Estrae titolo, abstract e dati bibliografici da un PDF (prime 3 pagine).
    Per Groq/OpenRouter che non accettano PDF e hanno context window limitata.
    max_chars ridotto a 3000 per stare nei limiti di Groq GPT-OSS."""
    import re as _re2
    from pypdf import PdfReader
    pages = PdfReader(io.BytesIO(data)).pages
    text = "\n".join((p.extract_text() or "") for p in pages[:3])
    m = _re2.search(r'\b(Abstract|ABSTRACT|Summary|SUMMARY)\b', text)
    if m:
        snippet = text[max(0, m.start() - 300):m.start() + max_chars]
    else:
        snippet = text[:max_chars]
    end = _re2.search(r'\b(Introduction|INTRODUCTION|Background|Keywords|KEYWORDS)\b', snippet[400:])
    if end:
        snippet = snippet[:400 + end.start() + 200]
    return snippet.strip()


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


def material_text(part):
    """Testo semplice del materiale, per controllare che autori e anni delle reference ci siano davvero."""
    if "text" in part:
        return part["text"]
    try:
        from pypdf import PdfReader
        data = base64.b64decode(part["inline_data"]["data"])
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    except Exception:
        return ""


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
def _fit(text, n):
    """Testo di slide entro `n` caratteri senza frasi mozze: si ferma all'ultima frase intera che ci sta (se ne
    resta almeno metà); solo se non c'è un punto utile taglia alla parola con «…»."""
    text = " ".join((text or "").split())
    if len(text) <= n:
        return text
    cut = max(text.rfind(". ", 0, n), text.rfind("? ", 0, n), text.rfind("! ", 0, n), text.rfind("; ", 0, n))
    if cut >= n // 2:
        return text[:cut + 1].rstrip(";") + ("." if text[cut] == ";" else "")
    return _clip(text, n)


def _clip(text, n):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def _words(x):
    return [w for w in re.sub(r"[^\w]+", " ", str(x).lower()).split() if w]


def exact_phrase(phrase, text, max_words=6):
    """La frase da evidenziare, solo se compare parola per parola nel testo."""
    pw, tw = _words(phrase), _words(text)
    if not pw or len(pw) > max_words:
        return ""
    for i in range(len(tw) - len(pw) + 1):
        if tw[i:i + len(pw)] == pw:
            return " ".join(str(phrase).split())
    return ""


def _ref_key(ref):
    """(primo cognome, anno) di una reference APA, per verificarla nel materiale."""
    m = re.match(r"\s*([^\W\d_][\w'’\- ]*?),", ref)
    y = re.search(r"\((\d{4})[a-z]?[,)]", ref) or re.search(r"\b(19|20)\d{2}\b", ref)
    if not m or not y:
        return None
    year = y.group(1) if len(y.group(1)) == 4 else y.group(0)
    return m.group(1).strip().split()[-1].lower(), year


CROSSREF = "https://api.crossref.org/works"


def _ref_title(ref):
    """Titolo di una reference APA: il testo tra «(Anno). » e il punto successivo."""
    m = re.search(r"\(\d{4}[a-z]?\)\.\s*(.+?[.?!])(\s|$)", ref)
    return m.group(1).strip() if m else ""


def _simple(x):
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode().lower()).strip()


def _title_in_material(title, material, share=0.75):
    words = [w for w in _simple(title).split() if len(w) > 3]
    if len(words) < 2:
        return False
    low = _simple(material)
    return sum(1 for w in words if w in low) / len(words) >= share


def _apa_from_crossref(item):
    """Reference APA 7 costruita dai metadati ufficiali di Crossref."""
    authors = []
    for a in (item.get("author") or [])[:20]:
        fam = a.get("family") or a.get("name") or ""
        initials = " ".join(f"{p[0]}." for p in re.split(r"[\s-]+", a.get("given") or "") if p)
        authors.append(f"{fam}, {initials}".strip(", "))
    if len(authors) > 1:
        auth = ", ".join(authors[:-1]) + ", & " + authors[-1]
    else:
        auth = authors[0] if authors else ""
    year = ((item.get("issued") or {}).get("date-parts") or [[None]])[0][0]
    title = " ".join((item.get("title") or [""])[0].split()).rstrip(".")
    journal = (item.get("container-title") or [""])[0]
    vol, issue, pages = item.get("volume"), item.get("issue"), item.get("page")
    tail = journal
    if vol:
        tail += f", {vol}" + (f"({issue})" if issue else "")
    if pages:
        tail += f", {pages.replace('-', '–')}"
    ref = f"{auth} ({year}). {title}." + (f" {tail}." if tail else "")
    if item.get("DOI"):
        ref += f" https://doi.org/{item['DOI']}"
    return ref


def crossref_reference(ref):
    """Cerca la reference su Crossref; se autore, anno e titolo coincidono restituisce la versione ufficiale."""
    key, title = _ref_key(ref), _ref_title(ref)
    if not key or not title:
        return None
    try:
        r = requests.get(CROSSREF, params={"query.bibliographic": ref[:300], "rows": 3},
                         headers={"User-Agent": "ClinicalResearchChaosBot/1.0"}, timeout=20)
        r.raise_for_status()
        items = r.json().get("message", {}).get("items", [])
    except Exception:
        return None
    from difflib import SequenceMatcher
    for it in items:
        it_title = (it.get("title") or [""])[0]
        year = ((it.get("issued") or {}).get("date-parts") or [[None]])[0][0]
        fam = _simple(((it.get("author") or [{}])[0]).get("family", ""))
        if (str(year) == key[1] and fam and _simple(key[0]).endswith(fam.split()[-1])
                and SequenceMatcher(None, _simple(title), _simple(it_title)).ratio() >= 0.85):
            return _apa_from_crossref(it)
    return None


def _harvard_from_crossref(item):
    """Reference in stile Harvard (Cite Them Right) dai metadati di Crossref: fino a 3 autori, poi «et al.»."""
    names = []
    for a in (item.get("author") or []):
        fam = a.get("family") or a.get("name") or ""
        initials = "".join(f"{p[0]}." for p in re.split(r"[\s-]+", a.get("given") or "") if p)
        names.append(f"{fam}, {initials}".strip(", "))
    if len(names) > 3:
        auth = f"{names[0]} et al."
    elif len(names) > 1:
        auth = ", ".join(names[:-1]) + " and " + names[-1]
    else:
        auth = names[0] if names else ""
    year = ((item.get("issued") or {}).get("date-parts") or [[None]])[0][0]
    title = " ".join((item.get("title") or [""])[0].split()).rstrip(".")
    journal = (item.get("container-title") or [""])[0]
    vol, issue, pages = item.get("volume"), item.get("issue"), item.get("page")
    ref = f"{auth} ({year}) \u2018{title}\u2019, {journal}"
    if vol:
        ref += f", {vol}" + (f"({issue})" if issue else "")
    if pages:
        ref += f", pp. {pages.replace('-', '–')}"
    ref += "."
    if item.get("DOI"):
        ref += f" Available at: https://doi.org/{item['DOI']}"
    return ref


RX_APA = re.compile(r"^(?P<auth>.+?)\s*\((?P<year>\d{4}[a-z]?)\)\.\s*(?P<title>.+?[.?!])\s+(?P<tail>.+?)(?:\s+(?P<doi>https?://\S+))?\s*$")


def harvard_from_apa(ref):
    """Conversione di ripiego APA → Harvard quando Crossref non risponde: (titolo, reference) o ("", testo APA)."""
    m = RX_APA.match(" ".join((ref or "").split()))
    if not m:
        return "", ref or ""
    auth = m.group("auth").replace(", &", " and").replace(" & ", " and ")
    title = m.group("title").rstrip(".")
    tail = re.sub(r",\s*(\d+[–-]\d+)\.?$", r", pp. \1", m.group("tail").rstrip(". "))
    out = f"{auth} ({m.group('year')}) \u2018{title}\u2019, {tail}."
    if m.group("doi"):
        out += f" Available at: {m.group('doi')}"
    return title, out


def verified_references(refs, material):
    """Reference controllate in tre passi:
    1) primo autore e anno devono comparire nel materiale (niente reference inventate);
    2) se Crossref trova lo stesso articolo (autore, anno e titolo coincidono), si usa la sua versione ufficiale,
       completa di rivista, volume, pagine e DOI;
    3) altrimenti si tiene solo se anche il titolo si ritrova nel materiale, togliendo rivista e DOI
       quando non compaiono nel materiale (libri, linee guida, articoli non indicizzati)."""
    if not material:
        return []
    low = material.lower()
    out = []
    for r in refs or []:
        r = " ".join(str(r).split())
        key = _ref_key(r)
        if not key or key[0] not in low or key[1] not in material:
            continue
        official = crossref_reference(r)
        if official:
            ref = official
        else:
            title = _ref_title(r)
            if not _title_in_material(title, material):
                continue
            head = r[: r.find(title) + len(title)] if title in r else r
            rest = r[len(head):].strip()
            rest = re.sub(r"https?://doi\.org/\S+|doi:\s*\S+", "", rest).strip()
            journal = re.split(r",\s*\d", rest)[0].strip(" .")
            ref = head if not journal or not _title_in_material(journal, material, 0.6) else f"{head} {rest}".strip()
        if ref not in out:
            out.append(ref[:400])
        time.sleep(0.3)
    return out[:6]


def _source_ok(source, refs):
    """La citazione breve della slide deve corrispondere a una reference tenuta."""
    m = re.match(r"\s*([^\W\d_][\w'’\-]*)", source or "")
    y = re.search(r"(19|20)\d{2}", source or "")
    if not m or not y:
        return ""
    return source.strip() if any(_ref_key(r) == (m.group(1).lower(), y.group(0)) for r in refs) else ""


RX_TEX = re.compile(r"\$\\?([A-Za-z]{1,12})\$")


def _clean_post(p, material="", min_slides=2):
    refs = [RX_TEX.sub(r"\1", r) for r in verified_references(p.get("references"), material)]   # «$t$-Test» → «t-Test»
    slides = []
    for s in p.get("slides", []):
        if not (s.get("heading") and s.get("body")):
            continue
        body = _fit(s.get("body", ""), 320)
        slides.append({"heading": _clip(s.get("heading", ""), 70), "body": body,
                       "image_prompt": _clip(s.get("image_prompt", ""), 300),
                       "photo_query": _clip(s.get("photo_query", ""), 60),
                       "highlight": exact_phrase(s.get("highlight"), body),
                       "source": _source_ok(s.get("source"), refs)})
    slides = slides[:7]
    if len(slides) < min_slides or not p.get("title") or not p.get("takeaway"):
        return None
    tags = ["#" + t.lstrip("#").replace(" ", "") for t in p.get("hashtags", []) if t.strip("# ")]
    category = p.get("category") if p.get("category") in CATEGORIES else "Research methods"
    title, takeaway = _clip(p["title"], 90), _clip(p["takeaway"], 160)
    return {
        "title": title,
        "title_highlight": exact_phrase(p.get("title_highlight"), title, 4),
        "category": category,
        "slides": slides,
        "takeaway": takeaway,
        "takeaway_highlight": exact_phrase(p.get("takeaway_highlight"), takeaway, 5),
        "references": refs,
        "caption": with_hook(p.get("hook"), p.get("caption", ""), 1200),
        "hashtags": tags[:15],
        "source_hint": p.get("source_hint", ""),
    }


LAST_MODEL = ""       # modello che ha dato l'ultima risposta (per segnare le verifiche fatte con il ripiego)
NO_FALLBACK_TASKS = {"nuovi post da Drive", "post bando", "scelta immagini"}
THINKING = {}         # livello di ragionamento per attività (config «gemini_thinking»), es. {"verifica bandi": "low"}
USAGE = {}            # consumo di Gemini in questo giro: {(attività, modello): contatori}
_EXHAUSTED = set()    # modelli con la quota giornaliera finita: in questo giro non si riprovano
_MISSING = set()      # modelli che rispondono 404 (assenti o ritirati per questa chiave): in questo giro non si riprovano


def record_usage(task, model, data=None, status="ok"):
    u = USAGE.setdefault(f"{task}|{model}", {"richieste": 0, "ingresso": 0, "uscita": 0, "ragionamento": 0, "respinte": 0})
    if status != "ok":
        u["respinte"] += 1
        return
    meta = (data or {}).get("usageMetadata") or {}
    if (data or {}).get("modelVersion"):
        u["versione"] = data["modelVersion"]          # versione reale dietro l'alias «-latest»
    u["richieste"] += 1
    u["ingresso"] += int(meta.get("promptTokenCount") or 0)
    u["uscita"] += int(meta.get("candidatesTokenCount") or 0)
    u["ragionamento"] += int(meta.get("thoughtsTokenCount") or 0)


CHECK_CAP = 34       # richieste Gemini al giorno oltre le quali le verifiche si fermano (config «gemini_daily_cap_checks»)
NOT_FREE_TASKS = {"ricerca per Paese"}   # usano una chiave a pagamento separata: non pesano sulla quota gratuita


def quota_day():
    """Giorno della quota Gemini: si azzera a mezzanotte del Pacifico."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


_LEDGER = None        # {"day": giorno quota, "used": {modello: richieste riuscite}, "exhausted": set()} dei giri precedenti


def _ledger(folder=None):
    """Registro della quota di oggi letto UNA volta dai file usage/ di tutti i giri (post, bandi, posizioni, storie):
    richieste riuscite per modello e modelli già trovati esauriti. Così un giro non riprova un modello che un altro
    giro ha già finito, e non spende sulle verifiche la quota che serve ai post."""
    global _LEDGER
    day = quota_day()
    if _LEDGER is not None and _LEDGER["day"] == day and folder is None:
        return _LEDGER
    used, exhausted, spent = {}, set(), 0.0
    run = os.environ.get("GITHUB_RUN_ID") or "locale"
    for f in Path(folder or Path(__file__).resolve().parent / "usage").glob("*.json"):
        if f.stem.endswith(f"-{run}"):
            continue                               # il file di questo giro: i suoi conteggi sono già in USAGE
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("quota_day") != day:
            continue
        for k, c in data.get("consumo", {}).items():
            spent += float(c.get("costo_usd", 0) or 0)
            task, _, model = k.partition("|")
            if model.startswith(("gemini", "gemma")) and task.split(" [", 1)[0] not in NOT_FREE_TASKS:
                used[model] = used.get(model, 0) + int(c.get("richieste", 0))
        exhausted |= set(data.get("esauriti") or [])
    led = {"day": day, "used": used, "exhausted": exhausted, "spent": spent}
    if folder is None:
        _LEDGER = led
    return led


def model_used_today(model):
    """Richieste riuscite oggi su `model`: giri precedenti + questo giro."""
    here = sum(c.get("richieste", 0) for k, c in USAGE.items()
               if k.endswith(f"|{model}") and k.split("|", 1)[0].split(" [", 1)[0] not in NOT_FREE_TASKS)
    return _ledger()["used"].get(model, 0) + here


def model_left(model):
    """Richieste gratuite che restano oggi su `model` (stima: quota per modello meno le riuscite)."""
    if model in _EXHAUSTED or model in _ledger()["exhausted"] or model in _MISSING:
        return 0
    default = MODEL_RPD["default"] if is_strong(model) else MODEL_RPD.get("lite", 500)
    return max(0, MODEL_RPD.get(model, default) - model_used_today(model))


def gemini_used_today(folder=None):
    """Richieste Gemini riuscite oggi (giorno della quota): file usage/ dei giri precedenti + questo giro."""
    led = _ledger(folder)
    here = sum(c.get("richieste", 0) for k, c in USAGE.items()
               if "|gemini" in k and k.split("|", 1)[0].split(" [", 1)[0] not in NOT_FREE_TASKS)
    return sum(v for m, v in led["used"].items() if m.startswith("gemini")) + here


def checks_allowed():
    """Le verifiche di bandi e posizioni girano sui modelli leggeri (quota propria): si fermano solo quando anche
    quelli sono finiti o oltre il tetto di config, così i modelli forti restano ai post."""
    lite_used = sum(model_used_today(m) for m in lite_models())
    return lite_used < CHECK_CAP and any(model_left(m) > 0 for m in lite_models())


def save_usage(folder):
    """Scrive il consumo del giro in usage/AAAA-MM-GG-<giro>.json (un file per giro: nessun conflitto tra giri)."""
    if not USAGE and not _EXHAUSTED:
        return None
    from datetime import datetime, timezone
    folder = Path(folder)
    folder.mkdir(exist_ok=True)
    run = os.environ.get("GITHUB_RUN_ID") or "locale"
    out = folder / f"{datetime.now(timezone.utc):%Y-%m-%d}-{run}.json"
    out.write_text(json.dumps({"workflow": os.environ.get("GITHUB_WORKFLOW", ""), "quota_day": quota_day(), "consumo": USAGE,
                               "esauriti": sorted(_EXHAUSTED)},
                              indent=1, ensure_ascii=False), encoding="utf-8")
    return out


_LOGGED_429 = set()


def retry_delay(r):
    """Secondi suggeriti da Gemini prima di riprovare (RetryInfo), oppure None."""
    import re as _re
    m = _re.search(r'"retryDelay"\s*:\s*"(\d+)', r.text)
    return int(m.group(1)) if m else None


def quota_exhausted(r, model=""):
    """429 per quota GIORNALIERA finita. Un 429 per troppe richieste al minuto porta un retryDelay: si aspetta."""
    if r.status_code != 429:
        return False
    t = r.text
    import re as _re
    ids = _re.findall(r'"quotaId"\s*:\s*"([^"]+)"', t) + _re.findall(r'"quotaValue"\s*:\s*"([^"]+)"', t)
    key = (model, tuple(ids) or t[:80])
    if key not in _LOGGED_429:                    # nel log il primo rifiuto di ogni tipo PER MODELLO: si vede quale limite
        _LOGGED_429.add(key)
        print(f"::warning title=Gemini 429 {model}::{', '.join(ids) or t[:300]}")
    if "PerDay" in t or "per day" in t.lower():
        return True
    return retry_delay(r) is None and "PerMinute" not in t


def with_hook(hook, caption, limit):
    """Didascalia con l'hook in prima riga (la parte visibile prima di «altro» su Instagram)."""
    hook = " ".join(str(hook or "").split()).strip()
    caption = str(caption or "").strip()
    if len(hook) > 125:
        hook = hook[:124].rsplit(" ", 1)[0] + "…"
    if not hook or caption.lower().startswith(hook.lower()[:60]):
        return caption[:limit]
    return f"{hook}\n\n{caption}"[:limit]


def _parts_to_text(parts):
    """Estrae solo le parti testuali da una lista di parts Gemini (scarta inline_data/file_data)."""
    return "\n\n".join(p["text"] for p in parts if "text" in p)


def _groq_json(prompt_text, schema, temperature=0.5, task="altro"):
    """Chiama Groq e restituisce JSON decodificato. Usato come riserva finale.
    Groq ritira i modelli senza preavviso (llama-3.3-70b-versatile è sparito a ottobre 2026):
    si prova il primo modello disponibile dell'elenco GROQ_MODELS."""
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    schema_str = json.dumps(schema, ensure_ascii=False)
    system = (
        "Rispondi SOLO con un oggetto JSON valido che rispetti esattamente questo schema JSON Schema: "
        + schema_str
        + "\nNessun testo prima o dopo il JSON."
    )
    for model in GROQ_MODELS:
        out = _groq_call(key, model, system, prompt_text, temperature, task)
        if out == "modello assente":
            print(f"  Groq: modello {model} non disponibile, provo il successivo")
            continue
        return out
    return None


GROQ_MODELS = [m.strip() for m in (os.environ.get("GROQ_MODELS") or "openai/gpt-oss-120b,qwen/qwen3.8-27b").split(",") if m.strip()]


def _groq_call(key, model, system, prompt_text, temperature, task):
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt_text}],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    for attempt in range(3):
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body, timeout=120,
            )
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(30 * (attempt + 1))
                continue
            if r.status_code in (400, 404) and ("model_not_found" in r.text or "decommissioned" in r.text):
                return "modello assente"
            if not r.ok:
                print(f"::warning title=Groq non disponibile::{model} {r.status_code}: {r.text[:200]}")
                return None
            text = r.json()["choices"][0]["message"]["content"]
            result = json.loads(text)
            record_usage(task, f"groq-{model.split('/')[-1]}", status="ok")
            globals()["LAST_GROQ"] = f"groq-{model.split('/')[-1]}"
            return result
        except Exception as e:
            print(f"  Groq eccezione: {e}")
            return None
    return None


# ---------------------------------------------------------------- instradamento dei modelli per attività
# Quota gratuita Gemini (piano gratuito, un solo progetto per tutti i workflow): ogni modello ha la SUA quota giornaliera
# (GenerateRequestsPerDayPerProjectPerModel-FreeTier, 20 per i Flash) e un limite al minuto. Fino al 5/11 tutte le
# verifiche (bandi 4 volte al giorno, posizioni alle 9:23, il confronto A/B scaduto alle 9:10) partivano dal Flash
# principale: la quota dei modelli forti finiva prima dei post, e ogni «troppe richieste» costava fino a 3 minuti
# di attese sullo stesso modello. Regole di adesso:
#   - SCRITTURA (testo che finisce nei post: post da Drive, post bando, arbitro, verifica fatti, takeaway clinico,
#     revisione slide): solo modelli forti, quello con più quota residua per primo; se sono tutti momentaneamente
#     occupati si aspetta il primo che si libera (max ~70 s) invece di ripiegare su un modello debole;
#   - VOLUME (verifiche di bandi e posizioni, arricchimento, anti-copia, copione reel, immagini, doppioni): modelli
#     leggeri, che hanno una quota propria (A/B 27/10–4/11: Flash-Lite uguale a Flash nel 96% dei campi, nessuna
#     differenza su scadenze e Italia); i forti solo se avanzano oltre la riserva per i post;
#   - «troppe richieste al minuto»: il modello va in pausa per il tempo indicato da Google e si passa subito al
#     successivo; quota del giorno finita: il modello è escluso per tutti i giri della giornata (file usage/);
#   - un piccolo intervallo tra due richieste allo stesso modello evita di superare il limite al minuto.
# «gemini:main» e «gemini:lite» seguono GEMINI_MODEL e GEMINI_FALLBACK. La config «ai_routes» sovrascrive le catene.
OR_STRONG = os.environ.get("OPENROUTER_STRONG") or "nvidia/nemotron-3-ultra-550b-a55b:free"
GEMMA = os.environ.get("GEMMA_MODEL") or "gemma-4-31b-it"
GROQ_STRONG = "openai/gpt-oss-120b"

# Pool del 7/11/2026 (pagina «Rate limit» di AI Studio del progetto): ogni modello ha una quota PROPRIA, quindi più
# modelli forti = più scrittura al giorno. Forti, 20 richieste al giorno ciascuno: 3.8 Flash, 3.6 Flash, 3 Flash,
# 2.5 Flash (3.5 Flash in fondo: rispondeva il 6/11 ma non compare nella pagina delle quote). Leggeri, 500 al giorno
# ciascuno: 3.5 Flash-Lite e 3.1 Flash-Lite. Gli alias «-latest» puntano a 3.8 Flash e 3.5 Flash-Lite: si usano i
# nomi espliciti, così il registro delle quote non conta due volte lo stesso modello sotto due nomi.
STRONG = ["main", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash-preview",
          "gemini-3.5-flash"]                # ordine di qualità a parità di quota
# (7/11: 2.5 Flash compare nella pagina delle quote ma l'API risponde 404 «no longer available to new users»)
LITE = ["lite", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
ALIASES = {"gemini-flash-latest": "gemini-3.8-flash", "gemini-flash-lite-latest": "gemini-3.5-flash-lite"}
MODEL_RPD = {"default": 20, "lite": 500}   # richieste gratuite al giorno per modello (config «gemini_rpd»); i leggeri
                                           # hanno una quota molto più ampia: per loro conta il 429 «per day»
STRONG_RESERVE = 10                  # richieste per modello forte tenute per la scrittura (config «gemini_strong_reserve»)
MIN_GAP = {"strong": 13.0, "lite": 4.5}   # secondi minimi tra due richieste allo stesso modello (≈5 e ≈13 al minuto)
MAX_WAIT = 70                        # attesa massima di un modello forte in pausa per la scrittura

WRITING = {"nuovi post da Drive", "post bando", "arbitro", "verifica fatti", "takeaway clinico", "revisione slide"}

# Livello A PAGAMENTO su OpenRouter (config «ai_paid»): si usa SOLO in fondo alla catena, quando i modelli gratuiti
# sono finiti o assenti, e mai oltre il tetto di spesa del giorno («daily_budget_usd», giorno della quota Gemini).
#   writing → scrittura dei post e conferme; review → revisore indipendente («critica»); volume → verifiche di
#   bandi e posizioni (di solito vuoto: lì i gratuiti bastano). Spesa reale letta dalla risposta di OpenRouter.
def _load_paid():
    try:
        cfg = json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    p = cfg.get("ai_paid") or {}
    off = os.environ.get("AI_PAID", "").lower() in ("0", "off", "false", "no")
    return {"enabled": bool(p.get("enabled")) and not off,
            "writing": list(p.get("writing") or []), "review": list(p.get("review") or []),
            "volume": list(p.get("volume") or []), "daily_budget_usd": float(p.get("daily_budget_usd", 0.5))}


PAID = _load_paid()


def paid_chain(kind):
    return [f"paid:{m}" for m in PAID.get(kind, [])] if PAID["enabled"] else []


def paid_spent_today():
    """Dollari spesi oggi sui modelli a pagamento: giri precedenti (file usage/) + questo giro."""
    here = sum(float(c.get("costo_usd", 0)) for c in USAGE.values())
    return round(_ledger()["spent"] + here, 4)


def paid_allowed():
    return PAID["enabled"] and paid_spent_today() < PAID["daily_budget_usd"]

# modello forte preferito per alcune attività (se ha quota; altrimenti gli altri forti): 2.5 Flash ha una quota
# separata dai 3.x, così bandi e controllo dei fatti non tolgono richieste ai post scientifici
PREFERRED = {}       # es. {"post bando": ["gemini-3-flash-preview"]}: nessuna preferenza finché 2.5 Flash non è disponibile
# screening (bandi, posizioni): SOLO modelli leggeri e gratuiti esterni, mai i forti. Il secondo parere dei forti
# arriva con le attività «conferma …», solo per le voci ad alta priorità (quelle che possono finire in un post).
SCREENING = {"verifica bandi", "verifica posizioni", "schemi slide"}   # + piano delle immagini (visuals.py)
CONFIRM = {"conferma bandi", "conferma posizioni"}
FLASH_ALT = [f"gemini:{m}" for m in STRONG[1:]]      # compatibilità con strumenti che li leggono
LITE_ALT = [f"gemini:{m}" for m in LITE[1:]]
VERIFY_CHAIN = ["gemini:lite"] + LITE_ALT + [f"groq:{GROQ_STRONG}", f"openrouter:{OR_STRONG}"]

ROUTES = {
    # revisore indipendente (famiglia diversa da chi scrive)
    # (confronto del 2/11: Nemotron Ultra il più rigoroso ma lento; Qwen su Groq veloce e valido; gpt-oss spesso senza JSON)
    "critica": [f"openrouter:{OR_STRONG}", "groq:qwen/qwen3.8-27b", f"groq:{GROQ_STRONG}", f"gemini:{GEMMA}"],
    # copione dei reel: testo breve da un carosello già verificato
    "copione reel": ["gemini:lite"] + LITE_ALT + [f"groq:{GROQ_STRONG}"],
    # giudizio sulle immagini (serve un modello che vede)
    "scelta immagini": ["gemini:lite"] + LITE_ALT + [f"gemini:{GEMMA}"],
    # doppioni: confronto logico tra titoli
    "controllo doppioni": [f"groq:{GROQ_STRONG}", "gemini:lite"] + LITE_ALT,
}
DEFAULT_ROUTE = VERIFY_CHAIN          # verifiche di bandi e posizioni, arricchimento, anti-copia
WRITING_TASKS = WRITING


class ModelUnavailable(Exception):
    """Modello senza quota, assente o non adatto alla richiesta: si passa al successivo della catena."""


class ModelCooling(ModelUnavailable):
    """Modello in pausa per il limite al minuto: si libera fra `until` secondi (epoch)."""

    def __init__(self, msg, until):
        super().__init__(msg)
        self.until = until


_COOL = {}            # modello → istante (epoch) in cui torna disponibile dopo un «troppe richieste»
_LAST_CALL = {}       # modello → istante dell'ultima richiesta (intervallo minimo tra richieste)


_AVAILABLE = None     # modelli che la chiave vede davvero (elenco di Google, gratuito): None = elenco non letto


def available_models():
    """Nomi dei modelli Gemini con generateContent visibili alla chiave (una sola lettura per giro, non consuma
    quota). Se l'elenco non si legge, insieme vuoto: si provano tutti e un 404 esclude quello mancante."""
    global _AVAILABLE
    if _AVAILABLE is None:
        _AVAILABLE = set()
        key = os.environ.get("GEMINI_API_KEY")
        if key:
            try:
                url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000"
                r = requests.get(url, headers={"x-goog-api-key": key}, timeout=30)
                if r.ok:
                    _AVAILABLE = {m["name"].split("/")[-1] for m in r.json().get("models", [])
                                  if "generateContent" in m.get("supportedGenerationMethods", [])}
            except requests.RequestException:
                pass
    return _AVAILABLE


def _resolve(m):
    m = {"main": GEMINI_MODEL, "lite": GEMINI_FALLBACK}.get(m, m)
    return ALIASES.get(m, m)


def _usable(models):
    """Toglie i modelli che l'elenco di Google non ha (se l'elenco è stato letto) e i doppioni."""
    avail = available_models()
    models = list(dict.fromkeys(models))
    if not avail:
        return models
    back = {v: k for k, v in ALIASES.items()}
    out = []
    for m in models:
        if m in avail:
            out.append(m)
        elif back.get(m) in avail:                 # c'è solo l'alias «-latest»: si usa quello
            out.append(back[m])
    return list(dict.fromkeys(out))


def strong_models():
    return _usable(_resolve(m) for m in STRONG)


def lite_models():
    return [m for m in _usable(_resolve(m) for m in LITE) if m not in strong_models()]


def is_strong(model):
    return model in strong_models()


def _strong_by_quota():
    """Modelli forti con quota: chi ne ha di più per primo (a parità, l'ordine di qualità)."""
    ms = strong_models()
    return sorted([m for m in ms if model_left(m) > 0], key=lambda m: (-model_left(m), ms.index(m)))


def _strong_for(base):
    """Forti con quota per l'attività: prima i preferiti (PREFERRED), poi gli altri per quota residua."""
    ms = _strong_by_quota()
    first = [m for m in PREFERRED.get(base, []) if m in ms]
    return first + [m for m in ms if m not in first]


def route_for(task):
    base = task.split(" [", 1)[0]                  # «verifica bandi [A]» del confronto A/B → «verifica bandi»
    chain = ROUTE_OVERRIDES.get(base)
    if chain is None and base in WRITING:          # a pagamento prima del ripiego leggero: è un modello forte
        chain = ([f"gemini:{m}" for m in _strong_for(base)]
                 + ([f"openrouter:{OR_STRONG}"] if base != "nuovi post da Drive" else [])
                 + paid_chain("writing")
                 + [f"gemini:{m}" for m in lite_models()])
    elif chain is None and base in CONFIRM:        # secondo parere: solo forti, mai un ripiego leggero
        chain = [f"gemini:{m}" for m in _strong_for(base)] + paid_chain("writing")
    elif chain is None and base in SCREENING:      # screening: solo leggeri e gratuiti esterni, mai i forti
        chain = ([f"gemini:{m}" for m in lite_models()] + [f"groq:{GROQ_STRONG}", f"openrouter:{OR_STRONG}"]
                 + paid_chain("volume"))
    elif chain is None:
        chain = ((ROUTES.get(base) or DEFAULT_ROUTE) + [f"gemini:{m}" for m in _strong_by_quota()]
                 + paid_chain("review" if base == "critica" else "volume"))
    out = []
    for spec in chain:
        provider, model = spec.split(":", 1)
        out.append((provider, _resolve(model) if provider == "gemini" else model))
    return list(dict.fromkeys(out))


ROUTE_OVERRIDES = {}       # da config «ai_routes» (bot.py)


def _extract_json(text):
    """JSON da una risposta testuale (anche dentro ```json … ``` o preceduto da ragionamento)."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        return json.loads(m.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("risposta senza JSON")


def _schema_instruction(schema):
    return ("Reply ONLY with one valid JSON object that follows exactly this JSON Schema (types are written in capitals, "
            "e.g. OBJECT = object, STRING = string): " + json.dumps(schema, ensure_ascii=False)
            + "\nNo text before or after the JSON.")


def _pace(model):
    """Intervallo minimo tra due richieste allo stesso modello (limite al minuto del piano gratuito)."""
    gap = MIN_GAP["strong"] if is_strong(model) else MIN_GAP["lite"]
    wait = _LAST_CALL.get(model, 0) + gap - time.time()
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL[model] = time.time()


def _gemini_one(model, parts, schema, temperature, task, thinking):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ModelUnavailable("GEMINI_API_KEY mancante")
    if model in _EXHAUSTED or model in _ledger()["exhausted"]:
        raise ModelUnavailable(f"{model}: quota del giorno finita")
    if model in _MISSING:
        raise ModelUnavailable(f"{model}: non disponibile per questa chiave")
    if _COOL.get(model, 0) > time.time():
        raise ModelCooling(f"{model}: in pausa per il limite al minuto", _COOL[model])
    gemma = model.startswith("gemma")
    if gemma:                                      # Gemma: niente schema né modalità JSON, lo schema va nel testo
        config = {"temperature": temperature}
        parts = [{"text": _schema_instruction(schema)}] + list(parts)
    else:
        config = {"temperature": temperature, "responseMimeType": "application/json", "responseSchema": schema}
        thinking = thinking or THINKING.get(task)
        if thinking:
            config["thinkingConfig"] = {"thinkingLevel": thinking}
    body = {"contents": [{"parts": parts}], "generationConfig": config}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    for attempt in range(3):
        _pace(model)
        try:
            r = requests.post(url, headers={"x-goog-api-key": key}, json=body, timeout=300)
        except requests.RequestException as e:
            if attempt == 2:
                raise ModelUnavailable(f"{model}: {str(e)[:120]}")
            time.sleep(10)
            continue
        if r.status_code == 429:
            record_usage(task, model, status="respinta")
            if quota_exhausted(r, model):
                _EXHAUSTED.add(model)              # quota giornaliera finita: esclusa anche per i giri dopo (usage/)
                raise ModelUnavailable(f"{model}: quota del giorno finita")
            until = time.time() + min(90, (retry_delay(r) or 30) + 2)
            _COOL[model] = until                   # limite al minuto: pausa e si passa subito al modello successivo
            raise ModelCooling(f"{model}: troppe richieste", until)
        if r.status_code >= 500:
            record_usage(task, model, status="respinta")
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code == 404 or (r.status_code == 400 and ("not found" in r.text.lower() or "not supported" in r.text.lower())):
            _MISSING.add(model)                    # modello assente o ritirato per questa chiave: escluso per tutto il giro
            raise ModelUnavailable(f"{model} {r.status_code}: {r.text[:200]}")
        if not r.ok:
            raise RuntimeError(f"Errore Gemini {r.status_code}: {r.text[:500]}")
        data = r.json()
        record_usage(task, model, data)
        globals()["LAST_MODEL"] = data.get("modelVersion") or model
        text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"] if not p.get("thought"))
        return _extract_json(text) if gemma else json.loads(text)
    raise ModelUnavailable(f"{model}: server non disponibile")


def _openai_compatible(url, key, model, label, prompt_text, schema, temperature, task, extra=None, headers=None):
    """Chiamata in stile OpenAI (Groq, OpenRouter) con risposta JSON."""
    body = {"model": model, "temperature": temperature,
            "messages": [{"role": "system", "content": _schema_instruction(schema)},
                         {"role": "user", "content": prompt_text}],
            "response_format": {"type": "json_object"}, **(extra or {})}
    if _COOL.get(f"{label}:{model}", 0) > time.time():
        raise ModelCooling(f"{label} {model}: in pausa per il limite al minuto", _COOL[f"{label}:{model}"])
    for attempt in range(3):
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                            **(headers or {})}, json=body, timeout=240)
        except requests.RequestException as e:
            raise ModelUnavailable(f"{label} {model}: {str(e)[:120]}")
        if r.status_code == 400 and "response_format" in body and any(
                w in r.text for w in ("response_format", "json_validate_failed", "Failed to validate")):
            body.pop("response_format")            # alcuni modelli non hanno la modalità JSON: basta lo schema nel testo
            continue
        if r.status_code in (400, 404) and any(w in r.text for w in ("model_not_found", "decommissioned", "not a valid model",
                                                                       "No endpoints found", "does not exist")):
            raise ModelUnavailable(f"{label} {model}: modello assente")
        if r.status_code in (402, 413):
            raise ModelUnavailable(f"{label} {model} {r.status_code}: {r.text[:160]}")
        if r.status_code == 429:
            record_usage(task, f"{label}-{model.split('/')[-1]}", status="respinta")
            if "per day" in r.text.lower() or "free-models-per-day" in r.text or "tokens per day" in r.text.lower():
                raise ModelUnavailable(f"{label} {model}: quota finita")
            ra = r.headers.get("retry-after") if hasattr(r, "headers") else None
            until = time.time() + min(90, int(ra) if (ra or "").isdigit() else 30)
            _COOL[f"{label}:{model}"] = until      # limite al minuto: pausa, si passa subito al modello successivo
            raise ModelCooling(f"{label} {model}: troppe richieste", until)
        if r.status_code >= 500:
            time.sleep(15 * (attempt + 1))
            continue
        if not r.ok:
            raise ModelUnavailable(f"{label} {model} {r.status_code}: {r.text[:200]}")
        data = r.json()
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        result = _extract_json(msg.get("content") or "")
        u = USAGE.setdefault(f"{task}|{label}-{model.split('/')[-1]}",
                             {"richieste": 0, "ingresso": 0, "uscita": 0, "ragionamento": 0, "respinte": 0})
        usage = data.get("usage") or {}
        u["richieste"] += 1
        u["ingresso"] += int(usage.get("prompt_tokens") or 0)
        u["uscita"] += int(usage.get("completion_tokens") or 0)
        if usage.get("cost") is not None:          # OpenRouter: costo reale della richiesta in dollari
            u["costo_usd"] = round(float(u.get("costo_usd", 0)) + float(usage["cost"] or 0), 6)
        globals()["LAST_MODEL"] = f"{label}-{model.split('/')[-1]}"
        return result
    raise ModelUnavailable(f"{label} {model}: non risponde")


def call_model(provider, model, parts, schema, temperature=0.3, task="altro", thinking=None):
    """Una richiesta a un modello preciso. Solleva ModelUnavailable se va provato il successivo."""
    if provider == "gemini":
        return _gemini_one(model, parts, schema, temperature, task, thinking)
    if not all("text" in p for p in parts):
        raise ModelUnavailable(f"{provider} non legge PDF o immagini")
    text = _parts_to_text(parts)
    if provider == "groq":
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise ModelUnavailable("GROQ_API_KEY mancante")
        extra = {"reasoning_effort": GROQ_REASONING.get(task.split(" [", 1)[0], "medium")} if "gpt-oss" in model else None
        return _openai_compatible("https://api.groq.com/openai/v1/chat/completions", key, model, "groq", text, schema,
                                  temperature, task, extra)
    if provider == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise ModelUnavailable("OPENROUTER_API_KEY mancante")
        return _openai_compatible("https://openrouter.ai/api/v1/chat/completions", key, model, "openrouter", text, schema,
                                  temperature, task, headers={"HTTP-Referer": "https://clinicalresearchchaos.com",
                                                              "X-Title": "Clinical Research Chaos"})
    if provider == "paid":                         # OpenRouter a pagamento, entro il tetto di spesa del giorno
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise ModelUnavailable("OPENROUTER_API_KEY mancante")
        if not paid_allowed():
            raise ModelUnavailable(f"a pagamento: tetto di {PAID['daily_budget_usd']} $ raggiunto o livello spento")
        return _openai_compatible("https://openrouter.ai/api/v1/chat/completions", key, model, "paid", text, schema,
                                  temperature, task, extra={"usage": {"include": True}},
                                  headers={"HTTP-Referer": "https://clinicalresearchchaos.com",
                                           "X-Title": "Clinical Research Chaos"})
    raise ModelUnavailable(f"fornitore sconosciuto: {provider}")


GROQ_REASONING = {"critica": "high", "controllo doppioni": "low"}


def gemini_json(parts, schema, temperature=0.5, task="altro", thinking=None, exclude_family=None):
    """Risposta JSON conforme allo schema dal primo modello disponibile della catena dell'attività (route_for).
    `exclude_family` («google», «openai», «nvidia»…) salta i modelli di quella famiglia: il revisore non deve
    essere della stessa famiglia di chi ha scritto. Le attività di scrittura aspettano un modello forte in pausa
    (limite al minuto) prima di ripiegare su uno leggero; le attività di volume non toccano la riserva dei forti."""
    base = task.split(" [", 1)[0]
    writing = base in WRITING and base not in ROUTE_OVERRIDES
    errors = []
    for round_ in range(3):
        cooling = []
        for provider, model in route_for(task):
            if exclude_family and family(provider, model) == exclude_family:
                continue
            if provider == "gemini" and is_strong(model) and not writing and base not in ROUTE_OVERRIDES \
                    and model_left(model) <= STRONG_RESERVE:
                continue                           # verifica: la quota rimasta di questo Flash serve ai post
            if writing and cooling and round_ < 2 and (provider == "paid" or
                                                       (provider == "gemini" and not is_strong(model))):
                break                              # un forte gratuito si libera fra poco: meglio aspettarlo che pagare o ripiegare
            try:
                out = call_model(provider, model, parts, schema, temperature, task, thinking)
                if errors:
                    print(f"  «{task}»: risposto da {provider}:{model} (prima: {'; '.join(e[:70] for e in errors[-4:])})")
                return out
            except ModelCooling as e:
                cooling.append(e.until)
                errors.append(str(e))
            except ModelUnavailable as e:
                errors.append(str(e))
            except ValueError as e:                # JSON non valido: si prova il modello successivo
                errors.append(f"{model}: JSON non valido ({str(e)[:60]})")
        if not cooling:
            break
        wait = min(cooling) - time.time()
        if wait > MAX_WAIT:
            if not writing:
                break
            wait = MAX_WAIT
        print(f"  «{task}»: modelli in pausa per il limite al minuto, aspetto {max(0, int(wait))} s")
        time.sleep(max(0, wait) + 1)
    raise RuntimeError(f"Gemini non disponibile per «{task}»: {' | '.join(e[:150] for e in errors[-8:])}")


def family(provider, model):
    m = model.lower()
    if m.startswith("gemini") or m.startswith("gemma") or m.startswith("google/"):
        return "google"
    if "gpt-oss" in m or m.startswith("openai/"):
        return "openai"
    if "nemotron" in m or m.startswith("nvidia/"):
        return "nvidia"
    if "qwen" in m:
        return "alibaba"
    if "llama" in m:
        return "meta"
    if "deepseek" in m:
        return "deepseek"
    return m.split("/")[0]


def groq_json(prompt_text, schema, temperature=0.0, task="altro"):
    """Richiesta di solo testo per attività logiche veloci (es. controllo doppioni): segue la catena dell'attività."""
    return gemini_json([{"text": prompt_text}], schema, temperature, task)


CLINICAL_POST_PROMPT = """You are a senior clinical researcher. You write the weekly "Latest Science" post of "{brand}" about ONE
real paper, for clinical researchers and clinicians. The tone is that of an expert colleague who points out and
explains an interesting paper in lay-abstract mode: clear, plain and precise, never promotional, never academic.
The goal is to make the reader want to READ THE PAPER, not to replace it. Write everything IN ENGLISH, even if
these instructions or the paper use another language.

FIRST decide the clinical focus of the paper (field clinical_focus):
- "treatment": the paper reports what an intervention, therapy, device or rehabilitation programme does to patients;
- "patient_health": the paper describes patients' health status, recovery course, prognosis, symptoms, function or
  risk factors;
- "none": the paper is mainly about methodology, measurement scales, psychometrics, statistics, study design,
  reporting, or engineering without patient results. In that case return an EMPTY posts list.

Then write exactly ONE post (posts list with one item). The post has 4 pages, filled by these fields:

PAGE 1 — HOOK  →  field "title" (shown alone on the cover), max 90 characters, sentence case.
  One or two short sentences (or a sharp question) on the central topic of the paper. It may use one concrete
  element of the paper (the patients, the clinical problem, the intervention) to create curiosity or tension.
  It must NOT reveal the outcome or suggest that something works or does not work.
PAGE 2 — ABSTRACT POINTS  →  "slides": exactly ONE slide. heading max 55 characters (a short phrase that
  anchors the slide to the hook's question, e.g. "What the paper set out to answer", "The clinical question
  behind it"); body max 160 characters, 2-3 short sentences: the key points from the abstract — population,
  intervention or exposure, and primary aim — that directly address the hook's question. Stay strictly inside
  the abstract. No results, no design labels (e.g. "RCT", "cohort") unless the hook already named them.
PAGE 3 — TAKE-HOME MESSAGE  →  field "takeaway", max 150 characters, ONE sentence.
  Take it from the CONCLUSIONS of the paper (the authors' own conclusion section or last abstract sentence), not
  from the results section. Stay close to the authors' wording and keep every qualifier they use ("may", "in
  patients with...", "further trials are needed" when that is their point). It must say what a reader learns by
  reading this paper, useful to someone working in the clinic or in clinical research.
  CRITICAL — no repetition and no new concepts: the takeaway must NOT restate or paraphrase the slide body
  (page 2) with different words. It advances the thread: where the slide states the QUESTION or GAP, the
  takeaway states what the paper CONCLUDES. It must also introduce NO concept, finding or detail that was
  not already present in the title (page 1) or the slide (page 2); if a secondary outcome or mechanism
  appears only in the conclusions, omit it from the takeaway.
PAGE 4 — SOURCE  →  built automatically from the paper's metadata (title and Harvard reference). Put THIS paper,
  and only this paper, in "references" (APA 7, authors, year, title, journal, DOI exactly as printed).

GENERAL RULES (they apply to every field: title, slide, takeaway, hook, caption):
- No specific numerical data: no percentages, p-values, hazard/odds ratios, confidence intervals, NNT, effect
  sizes, sample sizes or scores.
- No names of groups or arms, centres, trial acronyms, devices' brand names or people from the paper.
- Do not reveal the results. If the primary outcome showed no difference, never build the post on a secondary
  outcome that did; never present a secondary or exploratory finding as the message of the paper.
- No causal claims or mechanisms the authors do not state as conclusions ("is attributed to", "because of the
  resistance component"): speculation from the discussion is not a conclusion.
- Short sentences, precise language. No promotional formulas: "researchers discovered", "groundbreaking",
  "revolutionary", "game-changer", "boosts", "massive", "proves", "breakthrough".
- Do not overuse technical terms: use one only where it is needed, never stack them; spell out an acronym the
  first time (or avoid it).
- The four pages read as ONE thread: hook (the topic) → gap (why the question is open) → take-home (what the paper
  concludes) → source. Each page must make sense on its own, even as a screenshot.
- NO repetition between consecutive pages: the takeaway must not repeat the slide body; each page adds
  something new to the thread. Read the four pages in order and check that no sentence appears twice.

OTHER FIELDS:
- title_highlight: 1-4 words copied EXACTLY from the title.
- takeaway_highlight: 2-5 words copied EXACTLY from the takeaway.
- highlight (the slide): 2-6 words copied EXACTLY from the slide body.
- image_prompt (the slide): 15-35 words, one simple illustration of the open question, no text, no numbers, no
  real people. photo_query (the slide): 2-4 English keywords for a real stock photo of the clinical setting of the
  paper (patients, therapy, clinicians), or "".
- source (the slide): "".
- hook: the first line of the caption, max 120 characters, different from the title, with the main searchable term
  of the topic; no results, no numbers.
- caption: 3-5 short lines after the hook, in the same lay-abstract tone: what the paper is about and why it is
  worth reading, never its results; end with a question that invites clinicians and researchers to share their
  experience. Max 700 characters, no hashtags, no numbers.
- hashtags: 3 specific hashtags for the clinical topic.
- category: "{category}".

Already published posts (do not repeat these topics): {published}

File name of the paper: {filename}"""

CLINICAL_POST_SCHEMA = {"type": "OBJECT", "properties": {
    "clinical_focus": {"type": "STRING", "enum": ["treatment", "patient_health", "none"]},
    "focus_reason": {"type": "STRING"},
    "posts": SCHEMA["properties"]["posts"]}, "required": ["clinical_focus", "focus_reason", "posts"]}


RX_LAY_NUMBERS = re.compile(r"\d+(?:[.,]\d+)?\s*%|\b[pP]\s*[<=>≤]\s*0?[.,]\d|\b(?:HR|OR|RR|NNT|CI)\b\s*[=:]?\s*\d|"
                            r"\b\d+(?:[.,]\d+)?\s*(?:vs\.?|versus)\s*\d")


def lay_abstract_problems(post):
    """Controllo senza AI del formato lay abstract di Latest Science: numeri dei risultati nelle parti visibili."""
    probs = []
    parts = [("titolo", post.get("title", "")), ("takeaway", post.get("takeaway", ""))]
    parts += [(f"slide {i + 1}", f"{s.get('heading', '')} {s.get('body', '')}") for i, s in enumerate(post.get("slides") or [])]
    parts.append(("didascalia", post.get("caption", "")))
    for label, text in parts:
        m = RX_LAY_NUMBERS.search(text or "")
        if m:
            probs.append(f"numeri dei risultati in {label} («{m.group(0)}»)")
    return probs


def _design_rules():
    """Regole di forma del prompt principale (slide, immagini, hook, didascalia), riusate per Latest Science."""
    start = PROMPT.index("- title: a sharp hook")
    end = PROMPT.index("- category: one of")
    bullets = ("\n" + PROMPT[start:end]).split("\n- ")[1:]
    skip = ("takeaway:", "references:", "source (per slide)")    # per Latest Science valgono le regole cliniche sopra
    keep = [b for b in bullets if not b.startswith(skip)]
    return "FORM RULES:\n- " + "\n- ".join(keep).replace("a researcher", "a clinician").rstrip()


def clinical_posts(part, filename, brand, published=(), max_posts=1):
    """Post «Latest Science» da un articolo clinico: 1-`max_posts` caroselli, ognuno con un messaggio clinico diverso
    sul trattamento o sullo stato di salute dei pazienti. Restituisce (post, focus, motivo); lista vuota se
    l'articolo non ha un messaggio clinico sui pazienti (scale, metodologia, ingegneria senza risultati)."""
    prompt = CLINICAL_POST_PROMPT.format(brand=brand, category=CLINICAL_CATEGORY, design=_design_rules(),
                                         max_posts=max_posts, filename=filename,
                                         published="; ".join(published) if published else "none")
    out = gemini_json([{"text": prompt}, part], CLINICAL_POST_SCHEMA, 0.4, task="nuovi post da Drive")
    focus, why = out.get("clinical_focus", "none"), out.get("focus_reason", "")
    if focus == "none":
        return [], focus, why
    posts = [c for c in (_clean_post(p, material_text(part), min_slides=1) for p in out.get("posts", [])) if c][:1]
    for post in posts:
        post["slides"] = post["slides"][:1]                # formato lay abstract: una sola slide (il gap)
        post["lay_abstract"] = True
        post["no_images"] = True                            # solo testo: niente immagini AI né foto Pixabay
        problems = lay_abstract_problems(post)
        if problems:
            print(f"  ::warning title=Latest Science da controllare::«{post['title']}»: {'; '.join(problems)}")
        post["category"] = CLINICAL_CATEGORY
        post["clinical_focus"] = focus
    return posts, focus, why


def generate_posts(part, filename, brand, max_posts=12, published=()):
    prompt = PROMPT.format(brand=brand, max_posts=max_posts, filename=filename,
                           categories=", ".join(CATEGORIES),
                           published="; ".join(published) if published else "none")
    posts = gemini_json([{"text": prompt}, part], SCHEMA, task="nuovi post da Drive").get("posts", [])
    material = material_text(part)
    cleaned = [c for c in (_clean_post(p, material) for p in posts) if c][:max_posts]
    # Formato breve (stesso di Latest Science): 1 sola slide, niente immagini
    for post in cleaned:
        post["slides"] = post["slides"][:1]
        post["lay_abstract"] = True
        post["no_images"] = True
    return cleaned


# ---------------------------------------------------------------- revisione delle slide prima della pubblicazione
REVIEW_PROMPT = """You review an Instagram carousel for clinical researchers before it is published. Each slide must
carry ONE clear concept and be understandable on its own, even as a screenshot, by someone who has not read the
source document.

Flag a slide if it: refers to the structure of the source (e.g. "step six", "steps six to eight", "the next
section", "this guideline", "the box above"); uses an acronym not spelled out anywhere in the carousel (e.g. PROM
without "patient-reported outcome measure"); depends on another slide to make sense; or mixes two concepts.
Well-known terms such as "Table 1", "P-value" or "RCT" are fine.

For each flagged slide write a new heading (max 55 characters) and body (max 160 characters) that keep exactly the
same facts in plain words, self-contained. NEVER add facts, numbers, names or claims that are not in the carousel.
If a slide is fine, do not return it.

Carousel title: {title}
Slides:
{slides}"""

REVIEW_SCHEMA = {"type": "OBJECT", "properties": {"fixes": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "index": {"type": "INTEGER"}, "problem": {"type": "STRING"}, "heading": {"type": "STRING"},
    "body": {"type": "STRING"}}, "required": ["index", "problem", "heading", "body"]}}}, "required": ["fixes"]}

RX_OUT_OF_CONTEXT = re.compile(r"\b(steps?\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b|"
                               r"as (mentioned|described|shown|discussed) (above|below|earlier|previously)|"
                               r"see (above|below)|in this (review|guideline|manual|chapter|section))", re.I)


def review_slides(post):
    """Ogni slide un concetto, comprensibile da sola: Gemini riscrive le slide fuori contesto (stessi fatti).
    Se Gemini non risponde, le slide con riferimenti evidenti al documento («step six») si tolgono, se ne restano
    almeno 3. Restituisce il numero di slide corrette o tolte."""
    slides = post.get("slides") or []
    if not slides:
        return 0
    listing = "\n".join(f"{i}. {s['heading']} — {s['body']}" for i, s in enumerate(slides))
    try:
        out = gemini_json([{"text": REVIEW_PROMPT.format(title=post.get("title", ""), slides=listing)}], REVIEW_SCHEMA,
                          0.2, task="revisione slide")
        fixed = 0
        for f in out.get("fixes", []):
            i = f.get("index")
            if not isinstance(i, int) or not (0 <= i < len(slides)) or not f.get("heading") or not f.get("body"):
                continue
            body = _fit(f["body"], 170)
            print(f"  Slide {i + 1} riscritta ({f.get('problem', '')[:80]}): {slides[i]['heading']} → {f['heading']}")
            slides[i] = {**slides[i], "heading": _clip(f["heading"], 70), "body": body,
                         "highlight": exact_phrase(slides[i].get("highlight"), body)}
            fixed += 1
        return fixed
    except Exception as e:
        bad = [i for i, s in enumerate(slides) if RX_OUT_OF_CONTEXT.search(f"{s['heading']} {s['body']}")]
        keep = [s for i, s in enumerate(slides) if i not in bad]
        if bad and len(keep) >= 3:
            post["slides"] = keep
            print(f"  Revisione non disponibile ({str(e)[:80]}): tolte {len(bad)} slide fuori contesto")
            return len(bad)
        return 0
# ---------------------------------------------------------------- qualità: anti-copia, concretezza, riferimenti
RX_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)


def _crossref_by_doi(doi):
    try:
        r = requests.get(f"{CROSSREF}/{doi.rstrip('.,;)')}",
                         headers={"User-Agent": "ClinicalResearchChaosBot/1.0"}, timeout=20)
        r.raise_for_status()
        return _apa_from_crossref(r.json()["message"])
    except Exception:
        return None


def fix_references(post):
    """Riferimenti riscritti dai metadati ufficiali di Crossref, non dall'AI: prima per DOI (esatto), altrimenti
    per ricerca bibliografica (solo se autore, anno e titolo coincidono). Senza riscontro il testo resta com'è.
    Nessuna AI; restituisce quanti riferimenti ha sistemato."""
    fixed, out = 0, []
    for r in post.get("references") or []:
        m = RX_DOI.search(r)
        official = (_crossref_by_doi(m.group(1)) if m else None) or crossref_reference(r)
        if official and official != r:
            print(f"  Riferimento da Crossref: {official[:90]}")
            fixed += 1
        out.append(official or r)
        time.sleep(0.2)
    post["references"] = out
    return fixed


def _texts_of(post):
    """(etichetta, testo) di tutte le parti scritte del post."""
    yield "takeaway", post.get("takeaway", "")
    yield "caption", post.get("caption", "")
    for i, sl in enumerate(post.get("slides") or []):
        yield f"slide {i + 1}", sl.get("body", "")


def copied_from(text, source_low, n=7):
    """La sequenza più lunga di parole consecutive del testo presente identica nel materiale (minimo `n`),
    oppure None. Rilevazione senza AI; le frasi corte e i termini tecnici brevi non scattano."""
    words = _simple(text).split()
    best = None
    i = 0
    while i + n <= len(words):
        j = i + n
        if " ".join(words[i:j]) in source_low:
            while j < len(words) and " ".join(words[i:j + 1]) in source_low:
                j += 1
            if best is None or j - i > len(best.split()):
                best = " ".join(words[i:j])
            i = j
        else:
            i += 1
    return best


REWRITE_PROMPT = """You rewrite parts of an Instagram carousel for clinical researchers because they copy the
source material almost word for word. Rewrite each flagged text in your own words: same facts, same meaning,
same length limit, plainer and more direct. NEVER add facts, numbers or claims. Keep any acronym expansions.
Keep every number as digits exactly as in the original (0.955, 12%, 95% CI): never write numbers out in words.

Carousel title: {title}
Flagged texts (each copies the quoted passage from the source):
{flagged}"""

REWRITE_SCHEMA = {"type": "OBJECT", "properties": {"rewrites": {"type": "ARRAY", "items": {"type": "OBJECT",
                  "properties": {"label": {"type": "STRING"}, "text": {"type": "STRING"}},
                  "required": ["label", "text"]}}}, "required": ["rewrites"]}


def rewrite_copied(post, material):
    """Trova le frasi copiate quasi parola per parola dal materiale (senza AI) e le fa riscrivere a Gemini
    (stessi fatti, parole nuove). Restituisce il numero di parti riscritte."""
    if not material:
        return 0
    low = " ".join(_simple(material).split())
    flagged = [(label, text, hit) for label, text in _texts_of(post)
               if text and not (label == "takeaway" and post.get("lay_abstract"))   # Latest Science: il take home
               and (hit := copied_from(text, low))]                               # riprende le conclusioni (CC)
    if not flagged:
        return 0
    for label, _, hit in flagged:
        print(f"  Copia dalla fonte in {label}: \u201c{hit[:90]}\u201d")
    listing = "\n".join(f"- {label} (max {320 if label.startswith('slide') else 900} chars): {text}\n"
                        f"  copied passage: \u201c{hit[:200]}\u201d" for label, text, hit in flagged)
    try:
        out = gemini_json([{"text": REWRITE_PROMPT.format(title=post.get("title", ""), slides="", flagged=listing)}],
                          REWRITE_SCHEMA, 0.4, task="riscrittura anti-copia")
    except Exception as e:
        print(f"  Riscrittura non disponibile ({str(e)[:100]}): il post esce com'è, da rivedere")
        return 0
    done = 0
    news = {r.get("label", ""): r.get("text", "") for r in out.get("rewrites", [])}
    for label, text, hit in flagged:
        new = " ".join((news.get(label) or "").split())
        if not new or copied_from(new, low):
            continue
        if label == "takeaway":
            post["takeaway"] = _clip(new, 160)
            post["takeaway_highlight"] = exact_phrase(post.get("takeaway_highlight"), post["takeaway"], 5)
        elif label == "caption":
            post["caption"] = _clip(new, 1200)
        else:
            i = int(label.split()[1]) - 1
            body = _clip(new, 320)
            post["slides"][i] = {**post["slides"][i], "body": body,
                                 "highlight": exact_phrase(post["slides"][i].get("highlight"), body)}
        done += 1
    return done


RX_NUMBER = re.compile(r"\d")
RX_EXAMPLE = re.compile(r"\b(e\.g\.|for example|for instance|such as|like the|say,|imagine)\b", re.I)
RX_ACTION = re.compile(r"\b(check|use|report|ask|avoid|define|state|prespecify|pre-register|register|calculate|"
                       r"measure|compare|choose|pick|plan|test|confirm|write|read|look|verify|run|add|include|"
                       r"never|always|start|stop)\b", re.I)


def concreteness(post):
    """Cosa manca perché il post sia concreto: deve avere almeno un numero, un esempio o un'azione pratica
    da qualche parte (slide, takeaway o didascalia). Senza AI."""
    whole = " ".join(t for _, t in _texts_of(post))
    missing = [name for name, rx in (("a number", RX_NUMBER), ("an example", RX_EXAMPLE), ("an action", RX_ACTION))
               if not rx.search(whole)]
    return missing if len(missing) == 3 else []


ENRICH_PROMPT = """This Instagram carousel for clinical researchers is too generic: it has no numbers, no concrete
example and no practical action. Using ONLY the source material below, rewrite 1-2 slide bodies so the carousel
gains at least one of: a real number from the material, a concrete example, or a practical action the reader can
take. Same length limits (body max 160 characters). NEVER invent numbers or facts: only what is in the material.
If the material truly offers nothing concrete for this topic, return an empty list.

Carousel title: {title}
Slides:
{slides}

SOURCE MATERIAL (excerpt):
{material}"""


def enrich(post, material):
    """Un giro di arricchimento per i post troppo generici; vero se dopo il giro il post è concreto."""
    listing = "\n".join(f"{i}. {s['heading']} \u2014 {s['body']}" for i, s in enumerate(post.get("slides") or []))
    try:
        out = gemini_json([{"text": ENRICH_PROMPT.format(title=post.get("title", ""), slides=listing,
                                                         material=(material or "")[:30000])}],
                          REVIEW_SCHEMA, 0.3, task="arricchimento post")
    except Exception as e:
        print(f"  Arricchimento non disponibile ({str(e)[:100]})")
        return not concreteness(post)
    for f in out.get("fixes", []):
        i = f.get("index")
        if isinstance(i, int) and 0 <= i < len(post["slides"]) and f.get("heading") and f.get("body"):
            body = _fit(f["body"], 170)
            print(f"  Slide {i + 1} resa concreta: {f['body'][:90]}")
            post["slides"][i] = {**post["slides"][i], "heading": _clip(f["heading"], 70), "body": body,
                                 "highlight": exact_phrase(post["slides"][i].get("highlight"), body)}
    return not concreteness(post)


CLINICAL_CATEGORY = "Clinical insight"   # categoria dedicata al post del sabato (Latest Science): si esclude a
                                          # mano dalla libreria di metodologia, mai assegnata dal prompt principale

CLINICAL_TAKEAWAY_PROMPT = """This Instagram carousel is about to go out under "Latest Science": a weekly feature
that gives one clinical, practice-facing lesson from a real paper, for clinicians and researchers who treat
patients. Its takeaway line currently reads like a methodology lesson (about study design, reporting or
statistics). Rewrite ONLY the takeaway so it reads as a clinical concept: what this means for the therapeutic
approach or for the patient in front of the clinician, not for how the study was run or reported.

STRICT RULES:
- Use ONLY facts already present in the slides below. Do not add any number, result or claim that is not there.
- Do not mention study design, sample size, bias, blinding, statistics, reporting guidelines or "this study/paper".
- Write it as a clinical takeaway: what to do differently, watch for, or understand about the patient/condition.
- Max 130 characters. Plain English, no hashtags.
- If the slides truly contain nothing with a clinical/patient angle (pure methodology, no clinical content at all),
  return the original takeaway unchanged.

Title: {title}
Slides:
{slides}

Current takeaway: {takeaway}"""

CLINICAL_SCHEMA = {"type": "OBJECT", "properties": {"takeaway": {"type": "STRING"},
                   "takeaway_highlight": {"type": "STRING"}}, "required": ["takeaway"]}


def clinical_takeaway(post):
    """Riscrive il takeaway del post «Clinical Insights» (sabato) in chiave clinica/paziente invece che
    metodologica, usando solo i fatti già nelle slide. Se Gemini non risponde o non trova un angolo clinico,
    lascia il takeaway originale: nessun errore bloccante, il post esce comunque."""
    listing = "\n".join(f"{i+1}. {s.get('heading', '')} — {s.get('body', '')}" for i, s in enumerate(post.get("slides") or []))
    try:
        out = gemini_json([{"text": CLINICAL_TAKEAWAY_PROMPT.format(title=post.get("title", ""), slides=listing,
                                                                     takeaway=post.get("takeaway", ""))}],
                          CLINICAL_SCHEMA, 0.3, task="takeaway clinico")
    except Exception as e:
        print(f"  Takeaway clinico non disponibile ({str(e)[:100]}): resta il takeaway originale")
        return post
    new_take = (out.get("takeaway") or "").strip()
    if new_take and new_take.lower() != (post.get("takeaway") or "").strip().lower():
        post["takeaway"] = _clip(new_take, 130)
        hl = out.get("takeaway_highlight") or ""
        post["takeaway_highlight"] = exact_phrase(hl, post["takeaway"]) if hl else ""
        print(f"  Takeaway clinico: {post['takeaway']}")
    return post


def license_status(text):
    """Licenza di un articolo, letta dal testo (senza AI): («ok», etichetta) se riutilizzabile con attribuzione
    (CC BY, CC BY-SA, CC0, pubblico dominio); («blocked», etichetta) se vieta le opere derivate o l'uso
    commerciale (NC, ND); («unknown», "") se il testo non dichiara nessuna licenza."""
    import re
    t = re.sub(r"\s+", " ", (text or "").lower())
    if re.search(r"non-?commercial|noncommercial|by-nc|cc by-nc|\bnc-nd\b|noderiv|no derivativ|by-nd|cc by-nd", t):
        return "blocked", "CC con vincolo NC/ND"
    if re.search(r"creative commons attribution(?! non)|\bcc[- ]by\b|cc by 4\.0|cc0|public domain|creativecommons\.org/licenses/by/", t):
        return "ok", "CC BY"
    if re.search(r"all rights reserved|©\s*\d{4}\s+elsevier|reproduction.{0,40}prohibited", t):
        return "blocked", "tutti i diritti riservati"
    return "unknown", ""


# ---------------------------------------------------------------- coerenza con la fonte (interna ed esterna)
VERIFY_PROMPT = """You fact-check an educational carousel against the SOURCE text it was built from.
Check every slide, the title and the key takeaway:
1. EXTERNAL consistency: each claim, number, name, year and citation must be supported by the SOURCE.
   - "contradiction": the post says the opposite of the SOURCE or states a wrong number, year, name or direction of effect;
   - "unsupported": a factual claim that is not in the SOURCE (invented statistic, study or author);
   - "misattributed": a finding credited to the wrong study, author or population.
   Clearly framed teaching examples ("imagine a trial of 120 patients...") are fine: do not flag them.
2. INTERNAL consistency: slides must not contradict each other, and the title and takeaway must match the slides.
For each problem give the slide index (0-based; -1 for title/takeaway) and, when possible, a corrected heading and body
(max 12 words heading, max 160 characters body) that stays faithful to the SOURCE. Return no issue if everything is sound.

TITLE: {title}
TAKEAWAY: {takeaway}
SLIDES:
{slides}

SOURCE (excerpt):
{source}"""

VERIFY_SCHEMA = {"type": "OBJECT", "properties": {"issues": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "index": {"type": "INTEGER"}, "kind": {"type": "STRING", "enum": ["contradiction", "unsupported", "misattributed", "internal"]},
    "problem": {"type": "STRING"}, "heading": {"type": "STRING"}, "body": {"type": "STRING"}},
    "required": ["index", "kind", "problem"]}}}, "required": ["issues"]}


def verify_against_source(post, material):
    """Controllo di fatti e coerenza: Gemini confronta il post con il testo della fonte. Le slide con un errore
    vengono corrette (se Gemini propone un testo fedele) o tolte (se restano almeno 3 slide).
    Restituisce il numero di problemi trovati, oppure None se il controllo non è stato possibile."""
    slides = post.get("slides") or []
    if not slides or not material:
        return None
    listing = "\n".join(f"{i}. {s['heading']} — {s['body']}" for i, s in enumerate(slides))
    try:
        out = gemini_json([{"text": VERIFY_PROMPT.format(title=post.get("title", ""), takeaway=post.get("takeaway", ""),
                                                         slides=listing, source=material[:30000])}],
                          VERIFY_SCHEMA, 0.1, task="verifica fatti")
    except Exception as e:
        print(f"  Verifica sulla fonte non disponibile ({str(e)[:100]}): il post esce senza questo controllo")
        return None
    issues = [x for x in out.get("issues", []) if isinstance(x.get("index"), int)]
    drop = set()
    for x in issues:
        i = x["index"]
        print(f"  Verifica fonte, {x['kind']} (slide {i + 1 if i >= 0 else 'titolo'}): {x['problem'][:140]}")
        if not (0 <= i < len(slides)):
            continue
        if x.get("heading") and x.get("body") and x["kind"] != "unsupported":
            body = _fit(x["body"], 170)
            slides[i] = {**slides[i], "heading": _clip(x["heading"], 70), "body": body,
                         "highlight": exact_phrase(slides[i].get("highlight"), body)}
        else:
            drop.add(i)
    if drop and len(slides) - len(drop) >= 3:
        post["slides"] = [s for i, s in enumerate(slides) if i not in drop]
    return len(issues)


# ---------------------------------------------------------------- revisione incrociata tra due AI
# 1. un revisore di un'altra famiglia (non quella che ha scritto) critica ogni frase rispetto alla fonte:
#    fuori contesto, imprecisa, non supportata, vuota; e giudica filo logico e take home message;
# 2. Gemini fa da arbitro: rilegge la fonte e accetta, corregge o respinge ogni correzione proposta;
# 3. il revisore ridà i voti al post corretto: sotto soglia il post non esce (si passa al successivo).
_STOP = set("the a an and or of to in on for with by at from as is are be was were it this that these those your you "
            "can not no but if than then into over under more most less what which who how why when where".split())


def relevant_excerpt(material, post, max_chars=14000):
    """I brani della fonte che parlano di ciò che dice il post (non solo l'inizio del documento): paragrafi
    ordinati per parole in comune con il post, rimessi nell'ordine originale."""
    material = material or ""
    if len(material) <= max_chars:
        return material
    words = {w for w in _simple(" ".join(t for _, t in _texts_of(post)) + " " + post.get("title", "")).split()
             if len(w) > 3 and w not in _STOP}
    # blocchi di ~800 caratteri tagliati a fine frase (i PDF spesso non hanno righe vuote tra i paragrafi)
    sentences = re.split(r"(?<=[.!?;:])\s+|\n\s*\n", material)
    chunks, buf = [], ""
    for sent in sentences:
        while len(sent) > 1200:                    # frase lunghissima (tabelle, testo senza punteggiatura)
            chunks.append(sent[:1200])
            sent = sent[1200:]
        buf = f"{buf} {sent}".strip()
        if len(buf) >= 800:
            chunks.append(buf)
            buf = ""
    if buf:
        chunks.append(buf)
    scored = sorted(range(len(chunks)), key=lambda i: -len(words & set(_simple(chunks[i]).split())))
    keep, size = set(), 0
    for i in scored:
        if size + len(chunks[i]) > max_chars:
            continue
        keep.add(i)
        size += len(chunks[i])
    return "\n[…]\n".join(chunks[i] for i in sorted(keep))


CRITIC_PROMPT = """You are a senior clinical research methodologist and science editor. You did NOT write this {kind}:
your job is to stop anything imprecise or out of context from reaching an audience of researchers and health
professionals, who will notice every mistake.

Read the SOURCE excerpts and the whole post first, then judge every sentence.

Flag a sentence when it is:
- "out_of_context": it only makes sense inside the source or next to another slide: a dangling reference ("this",
  "these patients", "the trial", "step 3", "the authors", "the guideline"), a claim stripped of the condition,
  population or design under which it holds, a detail cut off from the reasoning that gives it meaning, or a number
  without unit, group or comparison.
- "imprecise": loose or wrong technical wording (risk vs odds, statistical vs clinical significance, association vs
  causation, "proves", "always", "never"), a finding generalised beyond its population or design, a qualifier of the
  source dropped ("may", "in adults", "in RCTs", "only", "at least"), or a definition that is not the accepted one.
- "unsupported": a factual claim that is neither in the SOURCE nor a standard textbook definition (invented numbers,
  studies, authors, rules, dates).
- "empty": generic filler a researcher cannot use ("X is crucial", "plan carefully", "it matters").
- "overclaim": the title, hook or takeaway promises more than the slides show, uses a verdict the SOURCE does not
  use ("destroys", "fails", "useless", "must", "only"), turns one option into the only one when the SOURCE names
  alternatives, or is contradicted by a slide. Classify it as "imprecise".
- "misused example": a study, trial, number or example used for a point the SOURCE does not attach to it, an example
  imported from outside the SOURCE, or a slide "Source" that is not the paper the statement comes from. Classify it
  as "out_of_context".
- direction and scale words ("higher", "lower", "better", "worse", "more", "less") when the SOURCE does not say whether
  they mean higher or lower function/risk/score: never choose a reading; keep the SOURCE's own wording, or flag the
  sentence as "imprecise" and propose a fix that avoids the ambiguous word.
{extra_rules}
Then judge the post as a whole:
- thread: it must teach ONE idea, with slides in a logical order (e.g. problem → why it matters → how to do it right)
  that leads to the takeaway. Flag a slide that is off the thread, repeats another, or contradicts another or the
  title; flag a title that the slides do not demonstrate (fix the title, not the facts).
- takeaway: it must be a real take-home message: true according to the SOURCE, following from the slides, specific
  (names the method, decision, threshold or check) and useful to a researcher tomorrow. "X is important", a vague
  exhortation or a restated title is NOT a take-home message.

Scores 1-5 (5 = publishable as is): accuracy, context, coherence, takeaway.
For each problem give: where ("title", "hook", "caption", "takeaway" or "slide N" as numbered below), kind (one of the
four above, or "thread"/"takeaway"), quote (the exact sentence), why (one line), and the fix: replacement text for that
whole field, faithful to the SOURCE, with no new facts, within the limits (title ≤ 70 characters, slide heading ≤ 55,
slide body ≤ 160, takeaway ≤ 130, hook ≤ 120, caption ≤ 600). For a slide give heading and body. If the only honest
fix is to remove a slide, leave heading and body empty and say so in why.
Do not flag style preferences, and do not flag clearly framed teaching examples ("imagine a trial of 120 patients").
verdict: "publish" (all scores ≥ 4 and no accuracy problem), "fix" (real problems that your fixes solve) or "reject"
(the post cannot be made accurate and useful from this SOURCE).

POST
{post}

SOURCE ({source_label}):
{source}"""

CRITIC_SCHEMA = {"type": "OBJECT", "properties": {
    "scores": {"type": "OBJECT", "properties": {"accuracy": {"type": "INTEGER"}, "context": {"type": "INTEGER"},
                                                "coherence": {"type": "INTEGER"}, "takeaway": {"type": "INTEGER"}},
               "required": ["accuracy", "context", "coherence", "takeaway"]},
    "issues": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "where": {"type": "STRING"}, "kind": {"type": "STRING"}, "quote": {"type": "STRING"}, "why": {"type": "STRING"},
        "heading": {"type": "STRING"}, "body": {"type": "STRING"}, "text": {"type": "STRING"}},
        "required": ["where", "kind", "why"]}},
    "verdict": {"type": "STRING", "enum": ["publish", "fix", "reject"]}},
    "required": ["scores", "issues", "verdict"]}

GRANT_RULES = """- this funding-call carousel has NO takeaway on purpose: never flag or propose one, and give the takeaway score 5.
- for a funding call, also "imprecise": eligibility, scope or requirements that lose a qualifier of the official
  text (who can apply, career-stage definitions, mandatory partners or countries, what is NOT funded), or a slide that
  lets someone believe they are eligible when the text restricts it. Deadlines, amounts and countries are NOT in the
  slides on purpose: do not ask for them.
"""

ARBITER_PROMPT = """You wrote this {kind} for researchers and health professionals. An independent reviewer (a different
AI) flagged the problems below and proposed fixes. Check every proposed fix against the SOURCE and decide:
- "accept": the problem is real and the fix is faithful to the SOURCE;
- "edit": the problem is real but the fix is wrong, adds a fact or loses meaning: write your own corrected text;
- "reject": the original is correct according to the SOURCE (say why in one line).
- for a slide the reviewer wants removed: "accept" removes it, "reject" keeps it.
Rules for any text you write: no fact that is not in the SOURCE; never flip or resolve the direction of an effect or scale
("higher" → "less disabled") unless the SOURCE states it explicitly: when the SOURCE is ambiguous, keep its wording; same length limits (title ≤ 70 characters, slide
heading ≤ 55, slide body ≤ 160, takeaway ≤ 130, hook ≤ 120, caption ≤ 600); every slide makes sense on its own, as a
screenshot, without referring to other slides or to the source; spell out acronyms the first time.
Finally write the takeaway of the post as fixed: one sentence (≤ 130 characters), the real take-home message, specific,
true according to the SOURCE, useful to a researcher; and takeaway_highlight: 2-5 words copied exactly from it.
A funding-call carousel has no takeaway: for it, return takeaway and takeaway_highlight as empty strings.

POST
{post}

REVIEWER'S ISSUES
{issues}

SOURCE ({source_label}):
{source}"""

ARBITER_SCHEMA = {"type": "OBJECT", "properties": {
    "decisions": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "id": {"type": "INTEGER"}, "decision": {"type": "STRING", "enum": ["accept", "edit", "reject"]},
        "heading": {"type": "STRING"}, "body": {"type": "STRING"}, "text": {"type": "STRING"},
        "reason": {"type": "STRING"}}, "required": ["id", "decision"]}},
    "takeaway": {"type": "STRING"}, "takeaway_highlight": {"type": "STRING"}},
    "required": ["decisions", "takeaway"]}

REVIEW_THRESHOLDS = {"accuracy": 4, "context": 4, "coherence": 3, "takeaway": 3}
REVIEW_CHARS = 14000        # brani della fonte dati al revisore (Groq gratuito: pochi token al minuto)
ARBITER_CHARS = 40000       # Gemini legge molto di più


def _post_listing(post):
    lines = [f"Title: {post.get('title', '')}", "Slides:"]
    lines += [f"{i + 1}. {s.get('heading', '')} — {s.get('body', '')}" for i, s in enumerate(post.get("slides") or [])]
    if post.get("takeaway"):                      # i bandi non hanno takeaway (5/11)
        lines.append(f"Takeaway: {post['takeaway']}")
    if post.get("hook"):
        lines.append(f"Hook (first caption line): {post['hook']}")
    if post.get("caption"):
        lines.append(f"Caption: {post['caption']}")
    return "\n".join(lines)


def _family_of_last():
    m = LAST_MODEL.lower()
    if m.startswith("groq-"):
        return family("groq", m[5:])
    if m.startswith("openrouter-"):
        return family("openrouter", m[11:])
    return family("gemini", m)


LAY_RULES = """This post is a "Latest Science" LAY ABSTRACT with a fixed 4-page format, and these rules replace the
thread and takeaway rules below:
- page 1 is the title (the hook on the topic), page 2 is ONE slide with the open question in the literature (the
  gap), page 3 is the takeaway, page 4 is the reference. Do not ask for more slides, and do not flag the post as
  vague or generic because it gives no numbers, results or details: that is intended, the post must make the
  reader want to read the paper.
- flag as "imprecise" any specific number (percentages, p-values, ratios, intervals, sample sizes, scores), any
  name of arms, groups, centres or trial acronyms, and any sentence that reveals or anticipates the results.
- flag as "imprecise" a post built on a secondary or exploratory outcome, a causal claim or mechanism that the
  SOURCE's conclusions do not state, and promotional words ("boosts", "breakthrough", "massive").
- the takeaway must be ONE sentence faithful to the CONCLUSIONS of the SOURCE (not to its results), with the
  authors' qualifiers; staying close to the authors' wording is correct, do not flag it. Your fixes must respect
  these rules too: never add a number or a result.
"""


def _critique(post, source, kind, label, writer_family):
    extra = GRANT_RULES if kind == "funding-call carousel" else (LAY_RULES if post.get("lay_abstract") else "")
    prompt = CRITIC_PROMPT.format(kind=kind, extra_rules=extra,
                                  post=_post_listing(post), source_label=label,
                                  source=relevant_excerpt(source, post, REVIEW_CHARS))
    if kind == "funding-call carousel":           # le slide dei bandi sono più lunghe (fino a 220 caratteri)
        prompt = prompt.replace("slide body ≤ 160", "slide body ≤ 220")
    out = gemini_json([{"text": prompt}], CRITIC_SCHEMA, 0.1, task="critica", exclude_family=writer_family)
    return out, LAST_MODEL, _family_of_last()


def _passes(scores, verdict, kind="research"):
    """Soglie della revisione; per i bandi il takeaway non conta (non esiste più, decisione del 5/11)."""
    need = {k: v for k, v in REVIEW_THRESHOLDS.items() if not (kind == "grant" and k == "takeaway")}
    return verdict != "reject" and all(int((scores or {}).get(k) or 0) >= v for k, v in need.items())


def _where(where, post):
    """(«slide», indice) | («title», None) | …, oppure None se il campo non esiste."""
    w = (where or "").strip().lower()
    m = re.match(r"slide\s*(\d+)", w)
    if m:
        i = int(m.group(1)) - 1
        return ("slide", i) if 0 <= i < len(post.get("slides") or []) else None
    for f in ("title", "takeaway", "hook", "caption"):
        if w.startswith(f):
            if f == "takeaway" and post.get("kind_review") == "grant":
                return None                        # bando: nessun takeaway da correggere
            return (f, None) if f in post or f in ("title", "takeaway") else None
    return None


def _apply(post, field, idx, heading, body, text, removals, body_limit=170):
    if field == "slide":
        if not (heading or body):
            removals.add(idx)
            return
        sl = post["slides"][idx]
        body = _fit(body or sl.get("body", ""), body_limit)   # bandi: 240 (prima tagliava a 170 con «…» a metà frase)
        post["slides"][idx] = {**sl, "heading": _clip(heading or sl.get("heading", ""), 70), "body": body,
                               "highlight": exact_phrase(sl.get("highlight"), body)}
    elif text:
        limit = {"title": 90, "takeaway": 160, "hook": 125, "caption": 1200}[field]
        post[field] = _clip(text, limit)
        if field == "title":
            post["title_highlight"] = exact_phrase(post.get("title_highlight"), post["title"], 4)
        if field == "takeaway":
            post["takeaway_highlight"] = exact_phrase(post.get("takeaway_highlight"), post["takeaway"], 5)


def cross_review(post, source, kind="research", writer_family="google"):
    """Revisione a due AI (vedi sopra). Corregge il post sul posto e restituisce un riepilogo:
    {"passed": bool|None, "scores": {...}, "critic": modello, "arbiter": modello, "fixed": n, "removed": n, "notes": [...]}.
    passed = None se nessun revisore indipendente era disponibile (il bot ricade sui controlli di Gemini)."""
    label = "official text of the call" if kind == "grant" else "teaching material the post was built from"
    kname = "funding-call carousel" if kind == "grant" else "educational carousel"
    report = {"passed": None, "scores": {}, "critic": "", "arbiter": "", "fixed": 0, "removed": 0, "notes": []}
    if kind == "grant":
        post["kind_review"] = "grant"
    if not source or not post.get("slides"):
        return report
    try:
        crit, critic_model, critic_family = _critique(post, source, kname, label, writer_family)
    except Exception as e:
        print(f"  Revisore indipendente non disponibile ({str(e)[:160]})")
        return report
    report.update(critic=critic_model, scores=crit.get("scores") or {})
    issues = [x for x in crit.get("issues") or [] if _where(x.get("where"), post)]
    print(f"  Revisione ({critic_model}): {crit.get('verdict')} {report['scores']}, {len(issues)} problemi")
    for x in issues:
        print(f"    - {x.get('where')} [{x.get('kind')}]: {(x.get('why') or '')[:150]}")
        report["notes"].append(f"{x.get('where')} [{x.get('kind')}]: {(x.get('why') or '')[:200]}")
    if crit.get("verdict") == "publish" and not issues and _passes(report["scores"], "publish", kind):
        report["passed"] = True
        return report
    if crit.get("verdict") == "reject":
        report["passed"] = False
        return report
    if issues:
        listing = "\n".join(
            f"[{n}] {x['where']} ({x.get('kind')}): “{(x.get('quote') or '')[:240]}” — {x.get('why', '')[:240]}\n"
            f"    proposed fix: " + (f"heading: {x.get('heading', '')} | body: {x.get('body', '')}"
                                     if _where(x["where"], post)[0] == "slide" else (x.get("text") or x.get("body") or ""))
            + ("" if (x.get("heading") or x.get("body") or x.get("text")) else " (remove)")
            for n, x in enumerate(issues))
        prompt = ARBITER_PROMPT.format(kind=kname, post=_post_listing(post), issues=listing, source_label=label,
                                       source=relevant_excerpt(source, post, ARBITER_CHARS))
        if kind == "grant":
            prompt = prompt.replace("slide body ≤ 160", "slide body ≤ 220")
        try:
            arb = gemini_json([{"text": prompt}], ARBITER_SCHEMA, 0.2, task="arbitro", exclude_family=critic_family)
            report["arbiter"] = LAST_MODEL
        except Exception as e:
            print(f"  Arbitro non disponibile ({str(e)[:160]}): il post non esce senza una seconda verifica")
            report["passed"] = False
            report["notes"].append("arbitro non disponibile")
            return report
        removals = set()
        for d in arb.get("decisions") or []:
            n = d.get("id")
            if not isinstance(n, int) or not (0 <= n < len(issues)) or d.get("decision") == "reject":
                continue
            field, idx = _where(issues[n]["where"], post)
            x = issues[n] if d["decision"] == "accept" else d
            _apply(post, field, idx, x.get("heading"), x.get("body"), x.get("text") or x.get("body"), removals,
                   240 if kind == "grant" else 170)
            report["fixed"] += 1
            print(f"    ✓ {issues[n]['where']}: {d['decision']}" + (f" ({d.get('reason', '')[:90]})" if d.get("reason") else ""))
        if removals and len(post["slides"]) - len(removals) >= (2 if kind == "grant" else 3):
            post["slides"] = [s for i, s in enumerate(post["slides"]) if i not in removals]
            report["removed"] = len(removals)
        if arb.get("takeaway") and kind != "grant":
            post["takeaway"] = _clip(arb["takeaway"], 160)
            post["takeaway_highlight"] = exact_phrase(arb.get("takeaway_highlight"), post["takeaway"], 5)
    # controllo finale del revisore sul post corretto
    try:
        final, _, _ = _critique(post, source, kname, label, writer_family)
    except Exception as e:
        print(f"  Controllo finale non disponibile ({str(e)[:120]}): vale il primo giudizio")
        report["passed"] = _passes(report["scores"], crit.get("verdict"), kind) and report["fixed"] > 0
        return report
    report["scores"] = final.get("scores") or {}
    report["passed"] = _passes(report["scores"], final.get("verdict"), kind)
    left = [x for x in final.get("issues") or [] if x.get("kind") in ("unsupported", "imprecise", "out_of_context")]
    print(f"  Controllo finale: {final.get('verdict')} {report['scores']}, {len(left)} problemi residui → "
          f"{'esce' if report['passed'] else 'NON esce'}")
    for x in left:
        report["notes"].append(f"residuo {x.get('where')} [{x.get('kind')}]: {(x.get('why') or '')[:200]}")
    return report
