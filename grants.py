"""Post sui bandi di ricerca: legge il report pubblico di GrantFinder e prepara un carosello per un bando."""

from datetime import date, datetime, timedelta

import json
import re
from html import unescape

import requests

import content

DEFAULT_URL = "https://raw.githubusercontent.com/Stefanodoro91/GrantFinder/main/dati/stato.json"
RELEVANCE_ORDER = {"Alta": 0, "Media": 1}
VERIFIED_FILE = "grants_verified.json"

VERIFY_PROMPT = """You check ONE research funding call against its OFFICIAL TEXT (below) for a public list of
open calls read by researchers. Use ONLY the official text; never guess.

Return:
- is_open_call: "yes" if the text describes a funding call that is open or opening for applications,
  "no" if it is closed, a news item, a list of funded projects or not a call, "unclear" otherwise.
- title: the official title of the call in English (translate if needed), max 120 characters.
- programme: the funding programme or scheme as named in the text (e.g. "Horizon Europe – Cluster 1:
  Health", "NIH HEAL Initiative", "Clinical Trial Award – Spinal Cord Injury Research Program").
  "" if not named.
- eligible_countries: where applicant organisations may be based, in a short phrase (e.g. "Any country",
  "United States only", "EU Member States and associated countries", "United Kingdom only",
  "Canada only"). "" if the text does not say.
- countries_evidence: the sentence from the text, copied word for word, that states it ("" if none).
- italy_eligible: "yes" only if the text explicitly allows organisations based in Italy, in any country,
  in non-US/foreign countries, or in a group of countries that includes Italy (e.g. EU Member States);
  "no" if it excludes foreign/non-domestic organisations or restricts applicants to other countries;
  "unclear" otherwise. "Foreign components" of US organisations or a bare list of applicant types are
  NOT enough for "yes".
- italy_evidence: the sentence, copied word for word, that justifies "yes" or "no" ("" if unclear).
- summary: 50-80 words in English, factual and neutral: aim of the call, what is funded, who can apply.

OFFICIAL TEXT ({source}):
{official}

CATALOGUE DATA (may be in Italian, less reliable):
{data}"""

VERIFY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "is_open_call": {"type": "STRING", "enum": ["yes", "no", "unclear"]},
        "title": {"type": "STRING"},
        "programme": {"type": "STRING"},
        "eligible_countries": {"type": "STRING"},
        "countries_evidence": {"type": "STRING"},
        "italy_eligible": {"type": "STRING", "enum": ["yes", "no", "unclear"]},
        "italy_evidence": {"type": "STRING"},
        "summary": {"type": "STRING"},
    },
    "required": ["is_open_call", "title", "programme", "eligible_countries", "countries_evidence",
                 "italy_eligible", "italy_evidence", "summary"],
}

PROMPT = """You write an Instagram carousel for "{brand}", a page for researchers and health professionals
about clinical research and research methodology. The post informs followers about ONE research funding
call. Below is the OFFICIAL TEXT of the call and the facts already verified on it.

STRICT ACCURACY RULES:
- Use ONLY the official text. Translate and rephrase, but never add facts, numbers, dates, amounts,
  eligibility rules or requirements that are not in it.
- Do not write the deadline, amounts, the funder or the eligible countries in the slides: they are added
  separately from verified data.

Write IN ENGLISH:
- title: a clear hook for the cover, max 70 characters, mentioning the research area (no deadline).
- title_highlight: 1-4 words copied EXACTLY from the title.
- slides: exactly 2 slides. Slide 1 heading "What it funds": aim and kind of projects funded.
  Slide 2 heading "Who it is for": applicants and teams it targets. Each body max 220 characters.
  Each slide also has image_prompt: 15-35 words describing ONE simple illustration of the slide's idea
  (concrete scene with 2-4 recognizable elements; no text, letters, numbers, logos or real people),
  and highlight: its key idea, 2-6 words copied EXACTLY from its body.
- coverage: funding coverage in a few words (e.g. "Fully funded"), or "" if not stated.
- takeaway: one sentence on why this call is worth a look, max 120 characters.
- takeaway_highlight: 2-5 words copied EXACTLY from the takeaway.
- caption: 2-4 short lines with context; end with a question inviting researchers to share whether they
  plan to apply or know similar calls. Max 500 characters, no hashtags, no links.
- hashtags: 6-10 specific hashtags (e.g. #ResearchFunding #GrantOpportunity #Neurorehabilitation).

VERIFIED FACTS: programme: {programme}; eligible countries: {countries}

OFFICIAL TEXT ({source}):
{official}"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "title_highlight": {"type": "STRING"},
        "slides": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"heading": {"type": "STRING"}, "body": {"type": "STRING"},
                               "image_prompt": {"type": "STRING"}, "highlight": {"type": "STRING"}},
                "required": ["heading", "body", "image_prompt", "highlight"],
            },
        },
        "coverage": {"type": "STRING"},
        "takeaway": {"type": "STRING"},
        "takeaway_highlight": {"type": "STRING"},
        "caption": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["title", "title_highlight", "slides", "takeaway", "takeaway_highlight", "caption", "hashtags"],
}

FIELDS = ["titolo", "titolo_it", "ente", "programma", "sommario", "macrogruppi", "tipo_bando", "tipo_ricerca",
          "chi_puo", "paesi", "partenariato", "copertura", "durata"]


def _date(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def fetch(cfg):
    url = cfg.get("grantfinder_url") or DEFAULT_URL
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return list(r.json().get("bandi", {}).values())


def _norm_title(t):
    stop = {"the", "a", "an", "of", "in", "for", "and", "to", "on", "with", "call", "program", "programme", "award", "grant"}
    return " ".join(w for w in re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).split() if w not in stop)


def similar(a, b):
    from difflib import SequenceMatcher
    return SequenceMatcher(None, _norm_title(a), _norm_title(b)).ratio()


def candidates(grants, posted, verified, cfg, today=None):
    """Bandi da pubblicare: verificati sul testo ufficiale, call aperta, pertinenza Alta/Media,
    scadenza abbastanza lontana, mai pubblicati. Tutti i Paesi."""
    today = today or date.today()
    done = {p.get("grant_id") for p in posted if p.get("grant_id")}
    # largo anticipo: prima i bandi che scadono tra almeno «grant_min_days_left» giorni (45),
    # se non ce ne sono quelli con almeno «grant_fallback_days_left» (30)
    for min_days in (int(cfg.get("grant_min_days_left", 45)), int(cfg.get("grant_fallback_days_left", 30))):
        out = []
        for g in grants:
            v = verified.get(g.get("id"), {})
            deadline = _date(g.get("scadenza"))
            if (v.get("status") == "ok" and v.get("is_open_call") != "no" and not v.get("coming_soon")
                    and g.get("rilevanza") in RELEVANCE_ORDER
                    and deadline and deadline >= today + timedelta(days=min_days)
                    and g.get("id") not in done and g.get("url")):
                out.append(g)
        # mai doppioni: niente bandi con titolo simile a uno già pubblicato (es. call gemelle dello stesso programma)
        grant_posts = [p for p in posted if p.get("kind") == "grant"]
        posted_titles = [verified.get(p.get("grant_id"), {}).get("title") or p.get("grant_title") or p.get("title", "")
                         for p in grant_posts]
        out = [g for g in out if not any(similar(verified.get(g["id"], {}).get("title") or g.get("titolo", ""), t) >= 0.6
                                         for t in posted_titles if t)]
        # varietà: niente programmi usati negli ultimi 3 post bando (se resta almeno un bando), poi pertinenza e scadenza
        recent = [verified.get(p.get("grant_id"), {}).get("programme_family") for p in grant_posts][-3:]
        fam = lambda g: verified.get(g["id"], {}).get("programme_family") or programme_family(g)
        fresh = [g for g in out if fam(g) not in recent]
        out = fresh or out
        if out:
            return sorted(out, key=lambda g: (RELEVANCE_ORDER[g["rilevanza"]], g["scadenza"]))
    return []


def _money(value, currency):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v >= 1_000_000:
        txt = f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".") + " million"
    else:
        txt = f"{v:,.0f}"
    return f"{currency or ''} {txt}".strip()


def _fmt_date(d):
    return f"{d.day} {d.strftime('%b %Y')}"


FUNDER_EN = {"commissione europea": "European Commission", "ministero della salute": "Italian Ministry of Health",
             "ministero dell'università e della ricerca": "Italian Ministry of University and Research"}


def funder_line(g):
    """Ente (in inglese) e, se breve, il programma: es. «Horizon Europe · European Commission»."""
    ente = (g.get("ente") or "").strip()
    ente = FUNDER_EN.get(ente.lower(), ente)
    prog = (g.get("programma") or "").split(" – ")[0].strip()
    if prog and prog.lower() != ente.lower() and len(prog) <= 32:
        return f"{prog} · {ente}" if ente else prog
    return ente or prog


EU_PROGRAMMES = {"HORIZON": "Horizon Europe", "EU4H": "EU4Health", "DIGITAL": "Digital Europe",
                 "ERC": "European Research Council (ERC)", "MSCA": "Marie Skłodowska-Curie Actions",
                 "EIC": "European Innovation Council", "ERASMUS": "Erasmus+"}
HORIZON_CLUSTERS = {"HLTH": "Cluster 1: Health", "CL4": "Cluster 4: Digital, Industry and Space",
                    "EIC": "European Innovation Council"}


REGIONS = ["International & intercontinental", "Europe", "North America", "Latin America", "Asia", "Africa", "Oceania"]
CONTINENTE = {"internazionale": REGIONS[0], "europa": "Europe", "nord america": "North America",
              "america latina": "Latin America", "asia": "Asia", "africa": "Africa", "oceania": "Oceania"}
RX_ANY_COUNTRY = re.compile(r"any country|all countries|worldwide|world-wide|global|international|"
                            r"non-?us organi[sz]ations eligible|foreign organi[sz]ations (are )?eligible", re.I)
REGION_WORDS = {
    "Europe": r"\beu\b|europe|european|united kingdom|\buk\b|england|scotland|wales|ireland|germany|france|"
              r"netherlands|switzerland|austria|belgium|norway|sweden|denmark|finland|spain|portugal|poland|italy",
    "North America": r"united states|\bu\.?s\.?\b|\busa\b|canada|north america",
    "Latin America": r"brazil|argentina|chile|colombia|mexico|peru|latin america",
    "Asia": r"japan|china|india|singapore|korea|taiwan|hong kong|asia",
    "Africa": r"africa|nigeria|kenya|ghana|uganda|tanzania|ethiopia",
    "Oceania": r"australia|new zealand|oceania",
}
_sources_cache = {}


def funder_continents(cfg):
    """{nome fonte: continente} dal file fonti_web.csv di GrantFinder."""
    if "map" not in _sources_cache:
        import csv
        import io
        url = (cfg.get("grantfinder_url") or DEFAULT_URL).replace("dati/stato.json", "fonti_web.csv")
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            rows = csv.DictReader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";")
            _sources_cache["map"] = {x["nome"]: CONTINENTE.get((x.get("continente") or "").strip().lower())
                                     for x in rows}
        except Exception:
            _sources_cache["map"] = {}
    return _sources_cache["map"]


def region(g, v, cfg):
    """Continente della call: dai Paesi ammessi verificati; se non indicati, dalla sede del finanziatore."""
    ec = (v or {}).get("eligible_countries") or ""
    if (v or {}).get("countries_evidence"):
        if RX_ANY_COUNTRY.search(ec):
            return REGIONS[0]
        found = [r for r, rx in REGION_WORDS.items() if re.search(rx, ec, re.I)]
        if len(found) > 1:
            return REGIONS[0]                      # più continenti: collaborazione intercontinentale
        if found:
            return found[0]
    gid = g.get("id", "")
    if "EDCTP" in gid.upper():
        return REGIONS[0]
    if gid.startswith("EU-"):
        return "Europe"
    if gid.startswith("GG-") or g.get("fonte") == "Grants.gov":
        return "North America"
    return funder_continents(cfg).get(g.get("fonte") or "") or REGIONS[0]


EU_PARTNER_SEARCH = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/how-to-participate/partner-search"


def partner_search(g):
    """(link, ID del topic) per le call del portale UE, che hanno una ricerca partner ufficiale; altrimenti None."""
    gid = g.get("id", "")
    if gid.startswith("EU-") and "topic-details" in (g.get("url") or ""):
        return EU_PARTNER_SEARCH, gid[3:]
    return None


def programme_family(g):
    """Programma di finanziamento usato per raggruppare la pagina (deterministico, dai dati ufficiali)."""
    gid = g.get("id", "")
    if gid.startswith("EU-"):
        parts = gid[3:].split("-")
        fam = EU_PROGRAMMES.get(parts[0].upper(), parts[0])
        return fam
    ente = FUNDER_EN.get((g.get("ente") or "").strip().lower(), (g.get("ente") or "").strip())
    low = ente.lower()
    if "national institutes of health" in low or low == "nih":
        return "NIH – US National Institutes of Health"
    if "defense" in low or low.startswith(("dod", "dow")) or "cdmrp" in low:
        return "US Department of Defense – CDMRP"
    return ente or g.get("fonte") or "Other funders"


def programme_detail(g):
    """Programma più specifico quando i dati lo permettono (es. «Horizon Europe – Cluster 1: Health»)."""
    gid = g.get("id", "")
    if gid.startswith("EU-HORIZON-"):
        parts = gid[3:].split("-")
        cl = parts[1].upper() if len(parts) > 1 else ""
        return "Horizon Europe" + (f" – {HORIZON_CLUSTERS[cl]}" if cl in HORIZON_CLUSTERS else "")
    return programme_family(g)


# ---------------------------------------------------------------- testo ufficiale della call
NIH_GUIDE = "https://grants.nih.gov/grants/guide/{folder}/{number}.html"
NIH_NUMBER = re.compile(r"\b((?:RFA|PAR|PAS|PA|NOT|OTA)-(?:[A-Z]{2}-)?\d{2}-\d{3})\b", re.I)
NIH_FOREIGN = re.compile(
    r"non-?domestic\s*\(non-?u\.?s\.?\)\s*entities\s*\(foreign\s+(?:organi[sz]ations|institutions)\)\s*"
    r"(?:are|is)\s+(not\s+)?(?:eligible|allowed|permitted)[^.]*\.", re.I)
EU_SEARCH = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
GG_FETCH = "https://api.grants.gov/v1/api/fetchOpportunity"
# programmi UE in cui gli enti con sede in uno Stato membro (quindi anche in Italia) sono ammessi per regola
EU_MEMBER_STATE_PROGRAMMES = ("HORIZON-", "EU4H-", "DIGITAL-")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ClinicalResearchChaosBot/1.0)"}


def html_to_text(h):
    h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", h or "")
    h = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr)>", ". ", h)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def _get(url):
    r = requests.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    return r.text


def official_text(g):
    """(testo ufficiale, descrizione della fonte). Solleva un'eccezione se non si riesce a leggerlo."""
    gid = g.get("id", "")
    m = NIH_NUMBER.search(g.get("programma") or "") or NIH_NUMBER.search(gid)
    if m:
        number = m.group(1).upper()
        folder = {"RFA": "rfa-files", "NOT": "notice-files", "OTA": "notice-files"}.get(number.split("-")[0], "pa-files")
        url = NIH_GUIDE.format(folder=folder, number=number)
        try:
            return html_to_text(_get(url)), f"NIH Guide {number}", url
        except requests.HTTPError:
            pass   # call annunciata ma non ancora sul NIH Guide: si usa la scheda di Grants.gov
    if gid.startswith("EU-") and "topic-details" in (g.get("url") or ""):
        topic = gid[3:]
        files = {"languages": (None, json.dumps(["en"]), "application/json")}
        r = requests.post(EU_SEARCH, params={"apiKey": "SEDIA", "text": f'"{topic}"', "pageSize": 20},
                          files=files, headers=HEADERS, timeout=60)
        r.raise_for_status()
        for v in r.json().get("results") or []:
            meta = v.get("metadata") or {}
            if topic in (meta.get("identifier") or []):
                desc = (meta.get("descriptionByte") or [""])[0]
                return html_to_text(desc), f"EU Funding & Tenders Portal, topic {topic}", g["url"]
        raise RuntimeError(f"topic {topic} non trovato nel portale UE")
    m = re.search(r"grants\.gov/search-results-detail/(\d+)", g.get("url") or "")
    if m:   # bandi Grants.gov non NIH: scheda ufficiale dall'API di Grants.gov (la pagina web usa JavaScript)
        r = requests.post(GG_FETCH, json={"opportunityId": int(m.group(1))}, headers=HEADERS, timeout=60)
        r.raise_for_status()
        data = (r.json() or {}).get("data") or {}
        syn = data.get("synopsis") or data.get("forecast") or {}
        parts = [str(data.get("opportunityTitle") or "")]
        for k in ("synopsisDesc", "forecastDesc", "applicantEligibilityDesc", "additionalEligibilityInfo",
                  "agencyName", "fundingDescLinkDesc"):
            if syn.get(k):
                parts.append(f"{k}: {html_to_text(str(syn[k]))}")
        types = [t.get("description", "") for t in (syn.get("applicantTypes") or []) if isinstance(t, dict)]
        if types:
            parts.append("Eligible applicant types: " + "; ".join(types))
        parts += _gg_announcements(data)
        return ". ".join(p for p in parts if p), f"Grants.gov opportunity {m.group(1)}", g["url"]
    return html_to_text(_get(g["url"])), "official call page", g["url"]


GG_ATTACHMENT = "https://apply07.grants.gov/grantsws/rest/opportunity/att/download/{id}"
RX_ANNOUNCEMENT = re.compile(r"announcement|nofo|funding opportunity|program|solicitation|guidelines", re.I)


def _gg_announcements(data, limit=2):
    """Testo dei PDF allegati alla scheda Grants.gov (es. il Program Announcement dei bandi CDMRP),
    dove spesso si trovano le condizioni sugli enti esteri."""
    import io
    out = []
    atts = []
    for folder in data.get("synopsisAttachmentFolders") or []:
        for a in folder.get("synopsisAttachments") or []:
            name = f"{a.get('fileName', '')} {a.get('fileDescription', '')}"
            if str(a.get("mimeType", "")).endswith("pdf") or name.lower().strip().endswith(".pdf"):
                atts.append((0 if RX_ANNOUNCEMENT.search(name) else 1, a))
    for _, a in sorted(atts, key=lambda x: x[0])[:limit]:
        try:
            r = requests.get(GG_ATTACHMENT.format(id=a["id"]), headers=HEADERS, timeout=60)
            r.raise_for_status()
            from pypdf import PdfReader
            text = " ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(r.content)).pages[:40])
            out.append(f"Attachment {a.get('fileName', '')}: " + re.sub(r"\s+", " ", text)[:40000])
        except Exception as e:
            print(f"  Allegato Grants.gov non letto ({a.get('fileName')}): {e}")
    return out


def _simple(x):
    return re.sub(r"[^a-z0-9]+", " ", (x or "").lower()).strip()


def _quoted(ev, text, minimum=25):
    """La frase citata da Gemini, solo se compare davvero nel testo ufficiale."""
    ev = (ev or "").strip()
    return ev if len(ev) >= minimum and _simple(ev) in _simple(text) else ""


def _words_found(phrase, text, share=0.6):
    words = [w for w in _simple(phrase).split() if len(w) > 3]
    if not words:
        return False
    low = _simple(text)
    return sum(1 for w in words if w in low) / len(words) >= share


RX_LIST_EVIDENCE = re.compile(r"other eligible applicants|applicanteligibilitydesc|eligible applicant types|"
                              r"^\W*non-?domestic\s*\(non-?u\.?s\.?\)\s*entities\s*\(foreign\s+\w+\)\W*$", re.I)
RX_STATEMENT = re.compile(r"\b(eligible|eligibility|may apply|can apply|allowed|permitted|open to|must be|"
                          r"restricted|limited to|only|based in|established in)\b", re.I)


def is_nih(g):
    return "national institutes of health" in (g.get("ente") or "").lower() or (g.get("ente") or "").strip().upper() == "NIH"


def _statement(ev):
    """Una prova vale solo se è una frase su chi può candidarsi, non un elenco di tipi di ente."""
    if not ev or RX_LIST_EVIDENCE.search(ev) or not RX_STATEMENT.search(ev) or ev.count(";") >= 3:
        return ""
    return ev


def clean_programme(prog, g, text):
    """Nome del programma: scarta agenzie, uffici contratti e numeri della call; per il CDMRP cerca il «… Research Program»."""
    number = g.get("id", "").split("-", 1)[-1].lower()
    ente = (g.get("ente") or "").lower()
    low = (prog or "").lower()
    if (not low or number in low.replace(" ", "") or low == ente or "contracting activity" in low
            or low in ("national institutes of health", "nih")):
        prog = ""
    if not prog and programme_family(g).startswith("US Department of Defense"):
        m = re.search(r"\b((?:[A-Z][\w’'\-]*\s){1,6}Research Program)\b(?:\s*\(([A-Z]{2,8})\))?", text)
        if m:
            name = re.sub(r"^FY\s?\d{2,4}\s+", "", m.group(1))
            prog = f"CDMRP – {name}" + (f" ({m.group(2)})" if m.group(2) else "")
    return prog or programme_detail(g)


def check_eligibility(g, text, out):
    """Paesi ammessi e ammissibilità dell'Italia, con la frase che lo prova.
    Prima le regole deterministiche (frase ufficiale NIH, regole dei programmi UE), poi le frasi citate
    da Gemini e ritrovate nel testo. Senza prova: «Not stated» e Italia «unclear»."""
    m = NIH_FOREIGN.search(text)
    if m:
        ok = not m.group(1)
        countries = ("Any country (non-US organisations eligible)" if ok
                     else "United States only (foreign organisations not eligible)")
        return {"eligible_countries": countries, "countries_evidence": m.group(0).strip(),
                "italy": "yes" if ok else "no", "italy_evidence": m.group(0).strip()}
    gid = g.get("id", "")
    if gid.startswith("EU-") and gid[3:].upper().startswith(EU_MEMBER_STATE_PROGRAMMES):
        rule = "EU programme rules: legal entities established in EU Member States (including Italy) and associated countries are eligible."
        return {"eligible_countries": "EU Member States and associated countries", "countries_evidence": rule,
                "italy": "yes", "italy_evidence": rule}
    c_ev = _statement(_quoted(out.get("countries_evidence"), text, 15))
    countries = (out.get("eligible_countries") or "").strip() if c_ev else ""
    i_ev = _statement(_quoted(out.get("italy_evidence"), text))
    italy = out.get("italy_eligible") if (i_ev and out.get("italy_eligible") in ("yes", "no")) else "unclear"
    if is_nih(g) and italy == "yes":
        # per il NIH vale solo la frase ufficiale della call completa (sopra); la scheda Grants.gov non basta
        italy, i_ev = "unclear", ""
        if c_ev and re.search(r"non-?domestic|foreign", c_ev, re.I):
            countries, c_ev = "", ""
    if italy == "unclear" and c_ev and RX_ANY_COUNTRY.search(countries) and not (
            is_nih(g) and re.search(r"non-?domestic|foreign", c_ev, re.I)):
        italy, i_ev = "yes", c_ev          # «any country» provato dalla call vale anche per l'Italia
    return {"eligible_countries": countries[:120] or "Not stated in the official text: check the call",
            "countries_evidence": c_ev[:400], "italy": italy, "italy_evidence": i_ev[:400]}


def verify(g, cfg):
    """Legge la call ufficiale e restituisce i dati verificati del bando (per la pagina e per i post)."""
    text, source, source_url = official_text(g)
    if len(text) < 400:
        raise RuntimeError(f"testo ufficiale troppo breve ({len(text)} caratteri) da {source}")
    data = "\n".join(f"{k}: {g.get(k)}" for k in FIELDS if g.get(k))
    out = content.gemini_json([{"text": VERIFY_PROMPT.format(source=source, official=text[:60000], data=data)}],
                              VERIFY_SCHEMA, 0.1)
    elig = check_eligibility(g, text, out)
    coming_soon = is_nih(g) and not source.startswith("NIH Guide") and not NIH_FOREIGN.search(text)
    if coming_soon:
        elig.update({"eligible_countries": "Coming soon: published with the full call", "countries_evidence": "",
                     "italy": "unclear", "italy_evidence": ""})
    programme = (out.get("programme") or "").strip()
    if not (programme and _words_found(programme, text)):
        programme = ""
    programme = clean_programme(programme, g, text)
    return {
        "status": "ok", "checked": date.today().isoformat(), "official_source": source, "official_url": source_url,
        "is_open_call": out.get("is_open_call", "unclear"),
        "title": content._clip(out.get("title") or g.get("titolo") or "", 140),
        "programme": content._clip(programme, 120), "programme_family": programme_family(g),
        "summary": content._clip(out.get("summary", ""), 700), "coming_soon": coming_soon, **elig,
    }


def load_verified():
    try:
        return json.load(open(VERIFIED_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def refresh_verified(grants, verified, cfg, limit=None, today=None):
    """Verifica i bandi attivi non ancora controllati (dalla scadenza più vicina), al massimo `limit` per run.
    I tentativi falliti si ritentano dopo 7 giorni, fino a 3 volte."""
    import time
    today = today or date.today()
    limit = int(limit or cfg.get("grant_verify_per_run", 8))
    def due(g):
        v = verified.get(g["id"])
        if not v:
            return True
        if v.get("coming_soon"):
            return (today - (_date(v.get("checked")) or today)).days >= 7
        if v.get("status") == "failed":
            last = _date(v.get("checked")) or today
            return v.get("attempts", 1) < 3 and (today - last).days >= 7
        return False
    todo = [g for g in grants if g.get("url") and (not _date(g.get("scadenza")) or _date(g["scadenza"]) >= today) and due(g)]
    todo.sort(key=lambda g: g.get("scadenza") or "9999")
    done = 0
    for g in todo[:limit]:
        try:
            verified[g["id"]] = verify(g, cfg)
            v = verified[g["id"]]
            print(f"::notice title=Bando verificato::{g['id']} | {v['programme']} | {v['eligible_countries']} | Italia: {v['italy']}")
        except Exception as e:
            if "Gemini non disponibile" in str(e) or "429" in str(e):
                print(f"::warning title=Quota Gemini esaurita::verifica sospesa, riprende al prossimo run ({done} bandi verificati)")
                break
            prev = verified.get(g["id"], {})
            verified[g["id"]] = {"status": "failed", "checked": today.isoformat(),
                                 "attempts": prev.get("attempts", 0) + 1, "error": str(e)[:300]}
            print(f"::warning title=Bando non verificato::{g['id']} - {str(e)[:250]}")
        done += 1
        time.sleep(7)   # resta sotto il limite di richieste al minuto di Gemini
    return done


def build_post(g, v, cfg):
    """Prepara il post di un bando già verificato (`v`): testo da Gemini sul testo ufficiale, fatti dai dati verificati."""
    text, source, _ = official_text(g)
    prompt = PROMPT.format(brand=cfg["brand_name"], programme=v["programme"], countries=v["eligible_countries"],
                           source=source, official=text[:60000])
    out = content.gemini_json([{"text": prompt}], SCHEMA, 0.2)
    clip = content._clip
    slides = []
    for sl in out.get("slides", []):
        if sl.get("heading") and sl.get("body"):
            body = clip(sl["body"], 320)
            slides.append({"heading": clip(sl["heading"], 70), "body": body,
                           "image_prompt": clip(sl.get("image_prompt", ""), 300),
                           "highlight": content.exact_phrase(sl.get("highlight"), body)})
    slides = slides[:2]
    if len(slides) < 2 or not out.get("title"):
        raise RuntimeError(f"Testo del bando incompleto per {g['id']}")

    deadline = _date(g["scadenza"])
    title = clip(out["title"], 90)
    takeaway = clip(out.get("takeaway", ""), 160) or "Worth a look if this is your research area."
    facts = [("Programme", clip(v["programme"], 90)), ("Funder", clip(funder_line(g), 80)),
             ("Deadline", _fmt_date(deadline))]
    per_project = _money(g.get("budget_progetto"), g.get("valuta"))
    total = _money(g.get("budget_totale"), g.get("valuta"))
    if per_project:
        facts.append(("Budget per project", per_project))
    elif total:
        facts.append(("Total budget", total))
    if (out.get("coverage") or "").strip():
        facts.append(("Coverage", clip(out["coverage"], 60)))
    facts.append(("Eligible countries", clip(v["eligible_countries"], 120)))

    countries_line = f"Eligible countries: {v['eligible_countries']}"
    if v.get("countries_evidence"):
        countries_line += f" (official call: \u201c{clip(v['countries_evidence'], 220)}\u201d)"
    caption = (f"{out.get('caption', '').strip()[:500]}\n\n"
               f"Programme: {v['programme']}\n"
               f"{countries_line}\n"
               f"Deadline: {_fmt_date(deadline)}\n"
               f"Official call: {g['url']}\n"
               + (f"Looking for consortium partners? EU partner search: {partner_search(g)[0]} (topic ID: {partner_search(g)[1]})\n"
                  if partner_search(g) else "")
               + "All open calls, grouped by programme: link in bio.\n\n"
               "Details are compiled automatically from the official call: always check eligibility, amounts and dates before applying.")
    tags = ["#" + t.lstrip("#").replace(" ", "") for t in out.get("hashtags", []) if t.strip("# ")]
    return {
        "id": f"grant-{g['id']}"[:60], "kind": "grant", "grant_id": g["id"],
        "title": title, "title_highlight": content.exact_phrase(out.get("title_highlight"), title, 4),
        "takeaway": takeaway, "takeaway_highlight": content.exact_phrase(out.get("takeaway_highlight"), takeaway, 5),
        "category": "Funding opportunity",
        "funder": clip(v["programme"], 110), "deadline": _fmt_date(deadline), "deadline_iso": deadline.isoformat(),
        "url": g["url"], "slides": slides, "facts": [(k, val) for k, val in facts if val],
        "closing_cta": ("Check the official call before applying", "All open calls: link in bio"),
        "caption": caption, "hashtags": ["#ResearchFunding", "#GrantOpportunity"] + tags[:10],
        "summary": v.get("summary", ""), "italy_evidence": v.get("italy_evidence", ""), "official_title": v.get("title", ""),
        "official_source": v.get("official_source", ""), "source": "GrantFinder", "source_hint": g.get("fonte", ""),
    }


def next_grant_post(posted, cfg, grants_list=None, verified=None):
    """Il post del prossimo bando verificato, oppure None (nessun bando adatto o GrantFinder non raggiungibile)."""
    try:
        grants_list = grants_list if grants_list is not None else fetch(cfg)
    except Exception as e:
        print(f"GrantFinder non raggiungibile: {e}")
        return None
    verified = verified if verified is not None else load_verified()
    pool = candidates(grants_list, posted, verified, cfg)
    print(f"Bandi verificati pubblicabili: {len(pool)}")
    for g in pool[:3]:
        try:
            post = build_post(g, verified[g["id"]], cfg)
            print(f"::notice title=Bando scelto::{g['id']} | {verified[g['id']]['programme']}")
            return post
        except Exception as e:
            print(f"::warning title=Post del bando non generato::{g['id']} - {str(e)[:300]}")
    return None


# ---------------------------------------------------------------- pagina «link in bio»
PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Open calls · {brand}</title>
<meta name="description" content="Open research funding calls checked against the official call text, grouped by funding programme.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
  :root {{ --bg: {bg}; --card: #15304A; --text: #FFFFFF; --muted: {muted}; --soft: {soft}; --accent: {accent}; --teal: {teal}; }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{ margin: 0; background: var(--bg); color: var(--text); font-family: Inter, system-ui, sans-serif; line-height: 1.45; }}
  .bar {{ height: 6px; background: var(--accent); }}
  main {{ max-width: 680px; margin: 0 auto; padding: 28px 16px 48px; }}
  .switch {{ display: inline-block; color: var(--text); text-decoration: none; font-size: 14px; font-weight: 600;
            border: 1px solid var(--muted); border-radius: 999px; padding: 7px 14px; margin-bottom: 18px; }}
  .badge {{ display: inline-block; background: var(--accent); color: var(--bg); font-weight: 800; font-size: 13px;
           letter-spacing: .06em; padding: 6px 14px; border-radius: 999px; }}
  h1 {{ font-size: 30px; font-weight: 800; margin: 14px 0 6px; line-height: 1.15; }}
  .intro {{ color: var(--soft); margin: 0 0 18px; font-size: 15px; }}
  nav.jump {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 30px; }}
  nav.jump a {{ color: var(--text); text-decoration: none; border: 1px solid var(--muted); border-radius: 999px;
               padding: 8px 14px; font-size: 14px; font-weight: 600; }}
  nav.jump a b {{ color: var(--accent); }}
  section.macro {{ margin-top: 34px; }}
  section.macro > h2 {{ font-size: 23px; font-weight: 800; margin: 0 0 4px; }}
  section.macro > p {{ color: var(--soft); font-size: 14px; margin: 0 0 18px; }}
  h2.region {{ font-size: 19px; font-weight: 800; margin: 34px 0 2px; padding-top: 14px; border-top: 1px solid var(--muted);
              display: flex; justify-content: space-between; gap: 10px; }}
  h2.region span {{ color: var(--muted); font-weight: 600; }}
  .tag.check-tag {{ background: var(--muted); }}
  .pending {{ color: var(--soft); font-size: 14px; font-style: italic; margin: 0 0 12px; }}
  h3.prog {{ font-size: 15px; letter-spacing: .04em; text-transform: uppercase; color: var(--accent);
            margin: 28px 0 10px; display: flex; justify-content: space-between; gap: 10px; }}
  h3.prog span {{ color: var(--muted); font-weight: 600; }}
  .call {{ background: var(--card); border-radius: 18px; padding: 20px; margin-bottom: 14px; border-left: 4px solid var(--accent); }}
  .call.other {{ border-left-color: var(--teal); }}
  .funder {{ color: var(--soft); font-size: 13px; font-weight: 600; margin-bottom: 6px; }}
  .tag {{ display: inline-block; background: var(--teal); color: var(--bg); font-size: 11px; font-weight: 800;
         letter-spacing: .05em; padding: 2px 8px; border-radius: 999px; margin-left: 6px; vertical-align: 1px; }}
  .tag.soon-tag {{ background: var(--accent); }}
  .call h4 {{ font-size: 18px; margin: 0 0 10px; line-height: 1.3; }}
  .summary {{ color: var(--soft); font-size: 15px; margin: 0 0 12px; }}
  .countries {{ font-size: 14px; margin: 0 0 4px; }}
  .countries b {{ color: var(--soft); font-weight: 600; }}
  details {{ font-size: 13px; color: var(--soft); margin: 0 0 14px; }}
  details summary {{ cursor: pointer; color: var(--muted); }}
  details p {{ border-left: 2px solid var(--muted); padding-left: 10px; margin: 8px 0 0; font-style: italic; }}
  .partners {{ font-size: 13px; color: var(--soft); margin: 0 0 14px; }}
  .partners code {{ font-size: 12px; background: rgba(255,255,255,.08); padding: 1px 6px; border-radius: 6px; word-break: break-all; }}
  .btns {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  a.btn.ghost {{ background: transparent; color: var(--text); border: 2px solid var(--accent); padding: 9px 16px; }}
  .call.other a.btn.ghost {{ background: transparent; border-color: var(--teal); }}
  .row {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between; }}
  .deadline {{ font-size: 14px; color: var(--soft); }}
  .deadline b {{ color: var(--text); font-size: 16px; }}
  .soon {{ color: var(--accent); font-weight: 800; font-size: 12px; margin-left: 6px; }}
  a.btn {{ background: var(--accent); color: var(--bg); text-decoration: none; font-weight: 800; font-size: 15px;
           padding: 11px 18px; border-radius: 12px; }}
  .call.other a.btn {{ background: var(--teal); }}
  a.btn:focus-visible, nav.jump a:focus-visible {{ outline: 3px solid var(--text); outline-offset: 2px; }}
  .empty {{ color: var(--soft); background: var(--card); border-radius: 18px; padding: 22px; }}
  footer {{ color: var(--muted); font-size: 13px; margin-top: 36px; }}
  footer a {{ color: var(--teal); }}
</style>
</head>
<body>
<div class="bar"></div>
<main>
  <a class="switch" href="positions.html">Academic positions &rarr;</a><br>
  <span class="badge">OPEN CALLS</span>
  <h1>Research funding calls</h1>
  <p class="intro">All open calls for clinical and rehabilitation research found by our monitoring, from funders worldwide.
  Each call is checked against its official text; grouped by region and funding programme, sorted by deadline.
  Closed calls are removed automatically.</p>
  <nav class="jump">{nav}</nav>
  <section class="macro" id="italy">
    <h2>Open to Italian institutions</h2>
    <p>The official call explicitly allows organisations based in Italy (directly, as EU Member State, or as any country).</p>
{italy}
  </section>
  <section class="macro" id="other">
    <h2>All other calls, by region</h2>
    <p>Grouped by where applicants can be based: international and intercontinental calls first, then each continent.
    Calls whose official text does not say where applicants can be based are listed under the funder's region.</p>
{other}
  </section>
  <footer>
    Calls collected by our monitoring and checked automatically against the official text: always verify eligibility,
    amounts and dates in the official call before applying.<br>
    Updated {updated} · <a href="https://www.instagram.com/{ig}/">{handle} on Instagram</a>
  </footer>
</main>
</body>
</html>
"""


def page_entries(grants_list, verified, today=None):
    """Bandi da mostrare: attivi in GrantFinder, non chiusi, scadenza futura o non indicata.
    Verificati sul testo ufficiale, oppure non ancora verificati ma con una scadenza futura nota (in verifica)."""
    today = today or date.today()
    out = []
    for g in grants_list:
        v = verified.get(g.get("id"), {})
        d = _date(g.get("scadenza"))
        if not (g.get("_attivo", True) and g.get("url")) or (d is not None and d < today):
            continue
        if v.get("status") == "ok":
            if v.get("is_open_call") != "no":
                out.append((g, v, d))
        elif d is not None:                     # in attesa di verifica (o verifica non riuscita): resta visibile
            out.append((g, {}, d))
    unique = []
    for e in sorted(out, key=lambda e: not e[1]):          # prima le voci verificate
        t = e[1].get("title") or e[0].get("titolo") or ""
        if not any(u[2] == e[2] and similar(t, u[1].get("title") or u[0].get("titolo") or "") >= 0.92 for u in unique):
            unique.append(e)
    return unique


def _group(entries):
    """{programma: [voci]} con le voci dalla scadenza più vicina (senza data in fondo); programmi dal più urgente."""
    groups = {}
    for e in entries:
        groups.setdefault(e[1].get("programme_family") or programme_family(e[0]), []).append(e)
    key = lambda e: (e[2] is None, e[2] or date.max)
    for items in groups.values():
        items.sort(key=key)
    return sorted(groups.items(), key=lambda kv: key(kv[1][0]))


def build_page(grants_list, verified, posted, cfg, today=None):
    from html import escape
    today = today or date.today()
    featured = {p.get("grant_id") for p in posted if p.get("kind") == "grant" and not p.get("withdrawn")}
    entries = page_entries(grants_list, verified, today)
    italy = [e for e in entries if e[1].get("italy") == "yes"]
    by_region = {r: [] for r in REGIONS}
    for e in entries:
        if e[1].get("italy") != "yes":
            by_region[region(e[0], e[1], cfg)].append(e)

    def card(g, v, d, css):
        if d:
            soon = '<span class="soon">CLOSING SOON</span>' if (d - today).days <= 21 else ""
            when = f"Deadline <b>{_fmt_date(d)}</b>{soon}"
        else:
            when = "Deadline <b>see official call</b>"
        tag = '<span class="tag">ON INSTAGRAM</span>' if g["id"] in featured else ""
        ps = partner_search(g)
        partners = (f'<p class="partners">Looking for consortium partners? Search topic <code>{escape(ps[1])}</code> in the '
                    f'EU partner search, or see &ldquo;Partner search announcements&rdquo; on the call page.</p>') if ps else ""
        find = (f'<a class="btn ghost" href="{escape(ps[0], quote=True)}" target="_blank" rel="noopener">Find partners</a>'
                if ps else "")
        if v.get("coming_soon"):
            tag += '<span class="tag soon-tag">COMING SOON</span>'
        if not v:
            tag += '<span class="tag check-tag">BEING CHECKED</span>'
            body = '<p class="pending">Details are being checked against the official call.</p>'
        else:
            ev = v.get("countries_evidence") or v.get("italy_evidence")
            proof = (f'<details><summary>From the official call</summary><p>&ldquo;{escape(ev)}&rdquo;</p></details>'
                     if ev else "")
            body = (f'{f"<p class=\"summary\">{escape(v["summary"])}</p>" if v.get("summary") else ""}\n'
                    f'      <p class="countries"><b>Eligible countries:</b> {escape(v.get("eligible_countries") or "check the call")}</p>\n'
                    f'      {proof}')
        return f"""    <article class="call {css}">
      <div class="funder">{escape(v.get("programme") or programme_detail(g))}{tag}</div>
      <h4>{escape(v.get("title") or g.get("titolo") or "")}</h4>
      {body}
      {partners}
      <div class="row">
        <div class="deadline">{when}</div>
        <div class="btns">{find}<a class="btn" href="{escape(g["url"], quote=True)}" target="_blank" rel="noopener">Official call &rarr;</a></div>
      </div>
    </article>"""

    def programmes(items, css):
        parts = []
        for prog, group in _group(items):
            parts.append(f'    <h3 class="prog">{escape(prog)} <span>{len(group)}</span></h3>')
            parts += [card(g, v, d, css) for g, v, d in group]
        return "\n".join(parts)

    def slug(r):
        return re.sub(r"[^a-z]+", "-", r.lower()).strip("-")

    italy_html = programmes(italy, "") if italy else '    <p class="empty">No verified calls open to Italian institutions right now.</p>'
    other_parts = []
    for r in REGIONS:
        if by_region[r]:
            other_parts.append(f'    <h2 class="region" id="{slug(r)}">{escape(r)} <span>{len(by_region[r])}</span></h2>')
            other_parts.append(programmes(by_region[r], "other"))
    other_html = "\n".join(other_parts) or '    <p class="empty">No other calls right now.</p>'
    nav = [f'<a href="#italy">Open to Italy <b>{len(italy)}</b></a>']
    nav += [f'<a href="#{slug(r)}">{escape(r)} <b>{len(by_region[r])}</b></a>' for r in REGIONS if by_region[r]]
    c = cfg["colors"]
    return PAGE.format(brand=escape(cfg["brand_name"]), handle=escape(cfg["handle"]), ig=cfg["handle"].lstrip("@"),
                       bg=c["background"], muted=c["muted"], soft=c["muted_text"], teal=c["accent"],
                       accent=cfg.get("grant_accent", "#FFB547"), nav="".join(nav),
                       italy=italy_html, other=other_html, updated=_fmt_date(today))
