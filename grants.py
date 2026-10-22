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
- deadline_type: "single" (one submission deadline), "several" (several due dates or cut-offs),
  "two_stage" (stage-1 proposal, then full proposal by invitation), "rolling" (applications accepted
  at any time), "not_stated".
- next_deadline: TODAY is {today}. The first date ON OR AFTER today by which a NEW application (for
  two-stage calls: the stage-1 proposal) must be SUBMITTED, as YYYY-MM-DD. Never the date the
  announcement EXPIRES (e.g. NIH "Expiration Date") nor a review or start date. "" if the text gives
  no such date.
- deadline_evidence: the sentence from the text, copied word for word, that contains that date ("" if none).
- later_deadlines: further submission dates for new applications after next_deadline, YYYY-MM-DD (max 4).
- loi_deadline: date of a letter of intent or pre-application, YYYY-MM-DD, "" if none.
- loi_required: "yes" if that letter of intent or pre-application is mandatory to apply, else "no".
- lead_eligibility: who can be the lead applicant / principal investigator (career stage, years since
  the doctorate, position, nationality or residence), max 160 characters in English; "" if not stated.
- lead_evidence: the sentence, copied word for word, that states it ("" if none).

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
        "deadline_type": {"type": "STRING", "enum": ["single", "several", "two_stage", "rolling", "not_stated"]},
        "next_deadline": {"type": "STRING"},
        "deadline_evidence": {"type": "STRING"},
        "later_deadlines": {"type": "ARRAY", "items": {"type": "STRING"}},
        "loi_deadline": {"type": "STRING"},
        "loi_required": {"type": "STRING", "enum": ["yes", "no"]},
        "lead_eligibility": {"type": "STRING"},
        "lead_evidence": {"type": "STRING"},
    },
    "required": ["is_open_call", "title", "programme", "eligible_countries", "countries_evidence",
                 "italy_eligible", "italy_evidence", "summary", "deadline_type", "next_deadline",
                 "deadline_evidence", "later_deadlines", "loi_deadline", "loi_required", "lead_eligibility",
                 "lead_evidence"],
}
VERIFY_VERSION = 2          # 2 = scadenze lette dal testo ufficiale (non la data di fine bando) e requisiti del capofila

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
            deadline = next_due(g, v, today)
            loi = _date(v.get("loi_deadline"))
            if loi and v.get("loi_required") == "yes" and loi < today + timedelta(days=14):
                continue                     # pre-domanda obbligatoria già chiusa o troppo vicina
            if (v.get("status") == "ok" and v.get("version", 1) >= VERIFY_VERSION
                    and v.get("is_open_call") != "no" and not v.get("coming_soon")
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
        if recent:                                   # mai lo stesso programma due giorni di fila (regola rigida)
            out = [g for g in out if fam(g) != recent[-1]]
        fresh = [g for g in out if fam(g) not in recent]
        out = fresh or out                           # possibilmente nessun programma degli ultimi 3 post
        if out:
            return sorted(out, key=lambda g: (RELEVANCE_ORDER[g["rilevanza"]], next_due(g, verified[g["id"]], today)))
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


_RAW = {}   # url -> html della pagina ufficiale (serve per leggere le tabelle delle date NIH)


def _get(url):
    r = requests.get(url, headers=HEADERS, timeout=45)
    r.raise_for_status()
    _RAW[url] = r.text
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
                dates = sorted({str(x)[:10] for x in (meta.get("deadlineDate") or []) if re.match(r"\d{4}-\d\d-\d\d", str(x))})
                model = " ".join(str(x) for x in (meta.get("deadlineModel") or []))
                head = (f"Deadline model: {model or 'not stated'}. Deadline dates: {', '.join(dates) or 'not stated'}. "
                        if dates or model else "")
                return head + html_to_text(desc), f"EU Funding & Tenders Portal, topic {topic}", g["url"]
        raise RuntimeError(f"topic {topic} non trovato nel portale UE")
    m = re.search(r"grants\.gov/search-results-detail/(\d+)", g.get("url") or "")
    if m:   # bandi Grants.gov non NIH: scheda ufficiale dall'API di Grants.gov (la pagina web usa JavaScript)
        r = requests.post(GG_FETCH, json={"opportunityId": int(m.group(1))}, headers=HEADERS, timeout=60)
        r.raise_for_status()
        data = (r.json() or {}).get("data") or {}
        syn = data.get("synopsis") or data.get("forecast") or {}
        parts = [str(data.get("opportunityTitle") or "")]
        for k in ("responseDate", "responseDateStr", "responseDateDesc", "synopsisDesc", "forecastDesc", "applicantEligibilityDesc",
                  "additionalEligibilityInfo", "agencyName", "fundingDescLinkDesc"):
            if syn.get(k):
                label = {"responseDate": "Grants.gov closing date for applications",
                         "responseDateStr": "Grants.gov closing date for applications",
                         "responseDateDesc": "Grants.gov explanation of the closing date"}.get(k, k)
                parts.append(f"{label}: {html_to_text(str(syn[k]))}")
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


# ---------------------------------------------------------------- scadenze (date utili per presentare domanda)
MONTHS = {m: i for i, ms in enumerate([("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
                                        ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
                                        ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
                                        ("dec", "december")], start=1) for m in ms}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
RX_MDY = re.compile(_MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", re.I)
RX_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MON + r",?\s+(\d{4})", re.I)
RX_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
RX_NUM = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")

# date standard NIH per codice di attività: (nuove domande, resubmission); fonte: grants.nih.gov, Standard Due Dates
NIH_STANDARD = [
    (r"R01|U01", ((2, 5), (6, 5), (10, 5)), ((3, 5), (7, 5), (11, 5))),
    (r"K\d\d", ((2, 12), (6, 12), (10, 12)), ((3, 12), (7, 12), (11, 12))),
    (r"R03|R21|R33|R34|R36|U34|UH2|UH3", ((2, 16), (6, 16), (10, 16)), ((3, 16), (7, 16), (11, 16))),
    (r"R15", ((2, 25), (6, 25), (10, 25)), None),
    (r"F\d\d", ((4, 8), (8, 8), (12, 8)), None),
    (r"R13|U13", ((4, 12), (8, 12), (12, 12)), None),
    (r"R4[1-4]|U4[34]|UT[12]|SB1|UB1", ((1, 5), (4, 5), (9, 5)), None),
    (r"P\d\d|T\d\d|D\d\d|R18|U18|R25|R24|U19|U24|U2C|U54|UG1|U10", ((1, 25), (5, 25), (9, 25)), None),
]


def dates_in(s):
    """Tutte le date scritte in un testo (mese in lettere in inglese, ISO, gg/mm/aaaa)."""
    out = []
    for m in RX_MDY.finditer(s or ""):
        out.append((int(m.group(3)), MONTHS.get(m.group(1).lower().rstrip(".")[:3] if m.group(1).lower()[:4] != "sept" else "sep"), int(m.group(2))))
    for m in RX_DMY.finditer(s or ""):
        out.append((int(m.group(3)), MONTHS.get(m.group(2).lower().rstrip(".")[:3] if m.group(2).lower()[:4] != "sept" else "sep"), int(m.group(1))))
    for m in RX_ISO.finditer(s or ""):
        out.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in RX_NUM.finditer(s or ""):
        out.append((int(m.group(3)), int(m.group(2)), int(m.group(1))))
    res = []
    for y, mo, d in out:
        try:
            res.append(date(y, mo, d))
        except (TypeError, ValueError):
            pass
    return res


def _nih_activity(g, text):
    for s in (g.get("titolo") or "", text[:3000]):
        m = re.search(r"\(([A-Z]\d{2}[A-Z]?)(?:/[A-Z]\d{2})?\b", s) or re.search(r"Activity Code\W+([A-Z]\d{2})", s)
        if m:
            return m.group(1)
    return ""


def nih_due_dates(g, text, html, today):
    """Date di presentazione dalle «Key Dates» del NIH Guide: tabella delle date, oppure «Standard dates apply»
    con il calendario standard NIH del codice di attività, limitato tra apertura e scadenza del bando."""
    def first(rx):
        m = re.search(rx, text, re.I)
        ds = dates_in(m.group(1)) if m else []
        return ds[0] if ds else None
    expires = first(r"Expiration Date\W{0,4}(.{0,40})")
    opens = first(r"Open Date \(Earliest Submission Date\)\W{0,4}(.{0,40})")
    loi_m = re.search(r"Letter of Intent Due Date\(s\)\W{0,4}(.{0,160})", text, re.I)
    loi = [d for d in dates_in(loi_m.group(1)) if d >= today] if loi_m else []
    new, resub, evidence = [], [], ""
    i = html.lower().find("application due date") if html else -1
    region_html = html[i:i + 20000] if i >= 0 else ""
    region_text = html_to_text(region_html)[:3000] if region_html else ""
    if region_html and not re.search(r"standard dates apply", region_text[:1500], re.I):
        table = re.search(r"(?is)<table.*?</table>", region_html)
        rows = re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", table.group(0)) if table else []
        col_new, col_res = 0, 1
        for row in rows:
            cells = [html_to_text(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", row)]
            low = [c.lower() for c in cells]
            if any(c.strip().startswith("new") for c in low):
                col_new = next(k for k, c in enumerate(low) if c.strip().startswith("new"))
                col_res = next((k for k, c in enumerate(low) if "resubmission" in c or "renewal" in c), -1)
                continue
            if len(cells) > col_new:
                new += dates_in(cells[col_new])
            if 0 <= col_res < len(cells):
                resub += dates_in(cells[col_res])
        if not rows:   # date scritte nel testo, senza tabella
            new = dates_in(region_text[:600])
        evidence = "NIH Guide, Key Dates: application due dates for new applications"
    elif region_text:
        code = _nih_activity(g, text)
        for rx, n_dates, r_dates in NIH_STANDARD:
            if code and re.fullmatch(rx, code):
                start, end = (opens or today), (expires or today + timedelta(days=3 * 365))
                for y in range(start.year, end.year + 1):
                    new += [date(y, mo, d) for mo, d in n_dates]
                    resub += [date(y, mo, d) for mo, d in (r_dates or n_dates)]
                new = [d for d in new if start <= d <= end]
                resub = [d for d in resub if start <= d <= end]
                evidence = f"NIH Guide: standard due dates apply ({code}); NIH standard calendar until the expiration date"
                break
    if expires:
        new = [d for d in new if d <= expires]
        resub = [d for d in resub if d <= expires]
    return {"due_dates": sorted({d.isoformat() for d in new}), "resubmission_dates": sorted({d.isoformat() for d in resub}),
            "expires": expires.isoformat() if expires else "", "loi_deadline": loi[0].isoformat() if loi else "",
            "loi_required": "no", "deadline_evidence": evidence,
            "deadline_type": "several" if len(set(new)) > 1 else ("single" if new else "not_stated"),
            "deadline_source": "nih_key_dates" if new else "none"}


def find_deadlines(g, text, source, source_url, out, today=None):
    """Date utili per presentare una nuova domanda, lette dal testo ufficiale (mai la data di fine bando).
    NIH e UE con regole fisse; per le altre fonti la data indicata da Gemini vale solo se compare nella frase
    citata e la frase compare nel testo ufficiale."""
    today = today or date.today()
    gid = g.get("id", "")
    if source.startswith("NIH Guide"):
        raw = _RAW.get(source_url, "")
        res = nih_due_dates(g, text, raw, today)
        if res["due_dates"] or res["deadline_source"] != "none":
            return res
        i = raw.lower().find("application due date")
        snippet = re.sub(r"\s+", " ", raw[i:i + 700]) if i >= 0 else "(sezione non trovata)"
        print(f"::warning title=Date NIH non lette::{gid} | {snippet[:600]}")
    base = {"due_dates": [], "resubmission_dates": [], "expires": "", "loi_deadline": "", "loi_required": "no",
            "deadline_evidence": "", "deadline_type": out.get("deadline_type") or "not_stated", "deadline_source": "none"}
    if gid.startswith("EU-"):
        m = re.search(r"Deadline model: ([^.]*)\. Deadline dates: ([^.]*)\.", text)
        if m:
            ds = sorted(d for d in dates_in(m.group(2)))
            two = "two" in m.group(1).lower()
            keep = ds[:1] if two else ds          # due fasi: conta la scadenza della fase 1
            base.update(due_dates=[d.isoformat() for d in keep], deadline_source="eu_portal",
                        deadline_type="two_stage" if two else ("several" if len(keep) > 1 else "single"),
                        deadline_evidence=f"EU Funding & Tenders Portal: {m.group(1).strip()}, deadline {', '.join(d.isoformat() for d in ds)}")
            return base
    all_dates = set(dates_in(text))
    nd = _date(out.get("next_deadline"))
    ev = _quoted(out.get("deadline_evidence"), text, 12)
    if ev and re.search(r"expir|archive|earliest start|merit review|council", ev, re.I):
        ev = ""                              # data di fine bando o di revisione: non è una scadenza per presentare
    if nd and nd >= today and ev and nd in dates_in(ev):
        later = sorted({d for d in (_date(x) for x in out.get("later_deadlines") or []) if d and d > nd and d in all_dates})
        base.update(due_dates=[nd.isoformat()] + [d.isoformat() for d in later[:4]], deadline_evidence=ev[:300],
                    deadline_source="official_text")
    else:
        cat = _date(g.get("scadenza"))      # data del catalogo: vale solo se compare nel testo ufficiale
        if cat and cat >= today and cat in all_dates and not is_nih(g):
            base.update(due_dates=[cat.isoformat()], deadline_source="catalogue_confirmed",
                        deadline_evidence="Date from the catalogue, found in the official text")
    loi = _date(out.get("loi_deadline"))
    if loi and loi in all_dates:
        base.update(loi_deadline=loi.isoformat(), loi_required=out.get("loi_required") or "no")
    if out.get("deadline_type") == "rolling" and not base["due_dates"]:
        base.update(deadline_type="rolling", deadline_source="official_text")
    return base


def next_due(g, v, today=None):
    """Prossima data utile per una nuova domanda; per le voci non ancora ricontrollate, la data del catalogo."""
    today = today or date.today()
    if (v or {}).get("version", 1) >= VERIFY_VERSION:
        ds = [d for d in (_date(x) for x in v.get("due_dates") or []) if d and d >= today]
        return min(ds) if ds else None
    return _date(g.get("scadenza"))


def later_dues(v, after):
    return [d for d in (_date(x) for x in (v or {}).get("due_dates") or []) if d and after and d > after]


def closed_for_new(v, today=None):
    """Bando ricontrollato con date trovate, ma tutte passate: chiuso per le nuove domande."""
    today = today or date.today()
    return ((v or {}).get("version", 1) >= VERIFY_VERSION and v.get("deadline_source") not in (None, "none")
            and v.get("deadline_type") != "rolling" and next_due({}, v, today) is None)


def lead_line(out, text):
    ev = _quoted(out.get("lead_evidence"), text, 20)
    lead = (out.get("lead_eligibility") or "").strip()
    return (lead[:160], ev[:300]) if lead and ev else ("", "")


def verify(g, cfg):
    """Legge la call ufficiale e restituisce i dati verificati del bando (per la pagina e per i post)."""
    text, source, source_url = official_text(g)
    if len(text) < 400:
        raise RuntimeError(f"testo ufficiale troppo breve ({len(text)} caratteri) da {source}")
    data = "\n".join(f"{k}: {g.get(k)}" for k in FIELDS if g.get(k))
    out = content.gemini_json([{"text": VERIFY_PROMPT.format(source=source, official=text[:60000], data=data,
                                                              today=date.today().isoformat())}],
                              VERIFY_SCHEMA, 0.1)
    dl = find_deadlines(g, text, source, source_url, out)
    lead, lead_ev = lead_line(out, text)
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
        "version": VERIFY_VERSION, **dl, "lead": lead, "lead_evidence": lead_ev,
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
        if v.get("status") == "ok" and v.get("version", 1) < VERIFY_VERSION:
            return True                     # verificato con le regole vecchie: si rilegge (scadenze, capofila)
        if v.get("coming_soon"):
            return (today - (_date(v.get("checked")) or today)).days >= 7
        if v.get("status") == "failed":
            last = _date(v.get("checked")) or today
            return v.get("attempts", 1) < 3 and (today - last).days >= 7
        return False
    todo = [g for g in grants if g.get("url") and (not _date(g.get("scadenza")) or _date(g["scadenza"]) >= today) and due(g)]
    soon = (today + timedelta(days=int(cfg.get("grant_fallback_days_left", 30)))).isoformat()
    # prima i bandi che potrebbero andare nei post (scadenza ad almeno 30 giorni), poi gli altri
    todo.sort(key=lambda g: ((g.get("scadenza") or "9999") < soon, g.get("scadenza") or "9999"))
    done = 0
    start, budget = time.time(), float(cfg.get("grant_verify_minutes", 13)) * 60
    for g in todo[:limit]:
        if time.time() - start > budget:     # resta nel tempo del job: il resto al prossimo run
            print(f"::notice title=Verifica a metà::tempo esaurito dopo {done} bandi, si riprende al prossimo run")
            break
        try:
            verified[g["id"]] = verify(g, cfg)
            v = verified[g["id"]]
            print(f"::notice title=Bando verificato::{g['id']} | {v['programme']} | {v['eligible_countries']} | Italia: {v['italy']}"
                  f" | date: {','.join(v.get('due_dates') or []) or '-'} ({v.get('deadline_source')}) | catalogo: {g.get('scadenza')}"
                  f" | capofila: {(v.get('lead') or '-')[:60]}")
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


def deadline_text(v, d):
    """(etichetta, nota) della scadenza mostrata: prossima di più date, fase 1, data del catalogo confermata."""
    t = (v or {}).get("deadline_type")
    if t == "two_stage":
        return "Stage 1 deadline", "two-stage call"
    if later_dues(v, d) or len((v or {}).get("due_dates") or []) > 1:
        return "Next deadline", "new applications"
    return "Deadline", ""


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

    deadline = next_due(g, v)
    if not deadline:
        raise RuntimeError(f"Nessuna data utile verificata per {g['id']}")
    title = clip(out["title"], 90)
    takeaway = clip(out.get("takeaway", ""), 160) or "Worth a look if this is your research area."
    dl_label, dl_note = deadline_text(v, deadline)
    facts = [("Programme", clip(v["programme"], 90)), ("Funder", clip(funder_line(g), 80)),
             (dl_label, _fmt_date(deadline) + (f" ({dl_note})" if dl_note else ""))]
    later = later_dues(v, deadline)
    if later:
        facts.append(("Later deadlines", ", ".join(_fmt_date(d) for d in later[:3])))
    loi = _date(v.get("loi_deadline"))
    if loi:
        facts.append(("Letter of intent" + (" (required)" if v.get("loi_required") == "yes" else ""), _fmt_date(loi)))
    per_project = _money(g.get("budget_progetto"), g.get("valuta"))
    total = _money(g.get("budget_totale"), g.get("valuta"))
    if per_project:
        facts.append(("Budget per project", per_project))
    elif total:
        facts.append(("Total budget", total))
    if (out.get("coverage") or "").strip():
        facts.append(("Coverage", clip(out["coverage"], 60)))
    facts.append(("Eligible countries", clip(v["eligible_countries"], 120)))
    if v.get("lead"):
        facts.append(("Who can lead", clip(v["lead"], 160)))

    countries_line = f"Eligible countries: {v['eligible_countries']}"
    if v.get("countries_evidence"):
        countries_line += f" (official call: \u201c{clip(v['countries_evidence'], 220)}\u201d)"
    caption = (f"{out.get('caption', '').strip()[:500]}\n\n"
               f"Programme: {v['programme']}\n"
               f"{countries_line}\n"
               + (f"Who can lead: {v['lead']}\n" if v.get("lead") else "")
               + f"{dl_label}: {_fmt_date(deadline)}" + (f" ({dl_note})" if dl_note else "")
               + (f"; later deadlines: {', '.join(_fmt_date(d) for d in later[:3])}" if later else "")
               + (f"; letter of intent{' (required)' if v.get('loi_required') == 'yes' else ''}: {_fmt_date(loi)}" if loi else "")
               + "\n"
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
{og}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
  :root {{ --bg: {bg}; --card: #15304A; --text: #FFFFFF; --muted: {muted}; --soft: {soft}; --accent: {accent}; --teal: {teal}; }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{ margin: 0; background: var(--bg); color: var(--text); font-family: Inter, system-ui, sans-serif; line-height: 1.45; }}
  .bar {{ height: 6px; background: var(--accent); }}
  main {{ max-width: 680px; margin: 0 auto; padding: 28px 16px 48px; }}
  .home {{ display: inline-block; color: var(--soft); font-size: 14px; text-decoration: none; margin-bottom: 10px; }}
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
  .dlnote {{ color: var(--muted); font-size: 12px; margin-left: 6px; }}
  .dates {{ color: var(--soft); font-size: 13px; margin: 10px 0 0; }}
  a.btn {{ background: var(--accent); color: var(--bg); text-decoration: none; font-weight: 800; font-size: 15px;
           padding: 11px 18px; border-radius: 12px; }}
  .call.other a.btn {{ background: var(--teal); }}
  a.btn:focus-visible, nav.jump a:focus-visible {{ outline: 3px solid var(--text); outline-offset: 2px; }}
  .empty {{ color: var(--soft); background: var(--card); border-radius: 18px; padding: 22px; }}
  form.filters {{ background: var(--card); border-radius: 18px; padding: 16px; margin: 0 0 8px; display: grid; gap: 10px;
                 grid-template-columns: 1fr 1fr; }}
  form.filters label {{ display: grid; gap: 4px; font-size: 12px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
                       color: var(--muted); }}
  form.filters label.wide {{ grid-column: 1 / -1; }}
  form.filters input, form.filters select {{ font: 500 15px Inter, system-ui, sans-serif; color: var(--text); background: var(--bg);
                       border: 1px solid var(--muted); border-radius: 10px; padding: 10px 12px; width: 100%; }}
  form.filters input:focus-visible, form.filters select:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
  form.filters .status {{ grid-column: 1 / -1; display: flex; justify-content: space-between; align-items: center; gap: 10px;
                         font-size: 14px; color: var(--soft); }}
  form.filters button {{ background: transparent; color: var(--text); border: 1px solid var(--muted); border-radius: 999px;
                        padding: 6px 12px; font: 600 13px Inter, system-ui, sans-serif; cursor: pointer; }}
  form.filters button[hidden] {{ display: none; }}
  @media (max-width: 520px) {{ form.filters {{ grid-template-columns: 1fr; }} }}
  .nomatch {{ color: var(--soft); background: var(--card); border-radius: 18px; padding: 18px 20px; font-size: 15px; }}
  [hidden] {{ display: none !important; }}
  footer {{ color: var(--muted); font-size: 13px; margin-top: 36px; }}
  footer a {{ color: var(--teal); }}
</style>
</head>
<body>
<div class="bar"></div>
<main>
  <a class="switch" href="positions.html">Academic positions &rarr;</a><br>
  <a class="home" href="index.html">&larr; Home</a>
  <span class="badge">OPEN CALLS</span>
  <h1>Research funding calls</h1>
  <p class="intro">All open calls for clinical and rehabilitation research found by our monitoring, from funders worldwide.
  Each call is checked against its official text; grouped by region and funding programme, sorted by deadline.
  Closed calls are removed automatically.</p>
  <nav class="jump">{nav}</nav>
{filters}
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
        d = next_due(g, v, today) if v.get("status") == "ok" else _date(g.get("scadenza"))
        if not (g.get("_attivo", True) and g.get("url")) or (d is not None and d < today):
            continue
        if v.get("status") == "ok" and closed_for_new(v, today):
            continue                         # date di presentazione tutte passate: chiuso alle nuove domande
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
            label, note = deadline_text(v, d) if v.get("version", 1) >= VERIFY_VERSION else ("Deadline", "")
            when = f"{label} <b>{_fmt_date(d)}</b>{soon}" + (f'<span class="dlnote">{escape(note)}</span>' if note else "")
        elif v.get("deadline_type") == "rolling":
            when = "Deadline <b>rolling, no fixed date</b>"
        else:
            when = "Deadline <b>see official call</b>"
        more = []
        later = later_dues(v, d) if v.get("version", 1) >= VERIFY_VERSION else []
        if later:
            more.append("Later deadlines: " + ", ".join(_fmt_date(x) for x in later[:3]))
        resub = [x for x in (_date(y) for y in v.get("resubmission_dates") or []) if x and x >= today]
        if resub:
            more.append(f"Resubmissions: next {_fmt_date(resub[0])}")
        loi = _date(v.get("loi_deadline"))
        if loi and loi >= today:
            more.append(f"Letter of intent{' (required)' if v.get('loi_required') == 'yes' else ''}: {_fmt_date(loi)}")
        exp = _date(v.get("expires"))
        if exp and later:
            more.append(f"Call expires {_fmt_date(exp)}")
        dates_html = f'<p class="dates">{escape(" · ".join(more))}</p>' if more else ""
        lead_html = (f'      <p class="countries"><b>Who can lead:</b> {escape(v["lead"])}</p>\n' if v.get("lead") else "")
        tag = '<span class="tag">ON INSTAGRAM</span>' if g["id"] in featured else ""
        ps = partner_search(g)
        partners = (f'<p class="partners">Looking for consortium partners? Search topic <code>{escape(ps[1])}</code> in the '
                    f'EU partner search, or see &ldquo;Partner search announcements&rdquo; on the call page.</p>') if ps else ""
        find = (f'<a class="btn ghost" href="{escape(ps[0], quote=True)}" target="_blank" rel="noopener">Find partners</a>'
                if ps else "")
        if v.get("coming_soon"):
            tag += '<span class="tag soon-tag">COMING SOON</span>'
        if v and v.get("version", 1) < VERIFY_VERSION:
            tag += '<span class="tag check-tag">DATES BEING CHECKED</span>'
        if not v:
            tag += '<span class="tag check-tag">BEING CHECKED</span>'
            body = '<p class="pending">Details are being checked against the official call.</p>'
        else:
            ev = v.get("countries_evidence") or v.get("italy_evidence")
            proof = (f'<details><summary>From the official call</summary><p>&ldquo;{escape(ev)}&rdquo;</p></details>'
                     if ev else "")
            body = (f'{f"<p class=\"summary\">{escape(v["summary"])}</p>" if v.get("summary") else ""}\n'
                    f'      <p class="countries"><b>Eligible countries:</b> {escape(v.get("eligible_countries") or "check the call")}</p>\n'
                    f'{lead_html}'
                    f'      {proof}')
        title = v.get("title") or g.get("titolo") or ""
        share = share_button(site_url(cfg, "calls#" + card_anchor(g["id"])),
                             f"Funding call: {title}" + (f" (deadline {_fmt_date(d)})" if d else ""))
        words = " ".join(x for x in (title, v.get("programme"), programme_detail(g), v.get("summary"),
                                     v.get("eligible_countries"), g.get("ente"), g.get("titolo")) if x).lower()
        attrs = (f'data-region="{escape(region(g, v, cfg), quote=True)}" data-italy="{"yes" if v.get("italy") == "yes" else "no"}" '
                 f'data-deadline="{d.isoformat() if d else ""}" data-text="{escape(words, quote=True)}"')
        return f"""    <article class="call {css}" id="{card_anchor(g["id"])}" {attrs}>
      <div class="funder">{escape(v.get("programme") or programme_detail(g))}{tag}</div>
      <h4>{escape(title)}</h4>
      {body}
      {partners}
      <div class="row">
        <div class="deadline">{when}</div>
        <div class="btns">{share}{find}<a class="btn" href="{escape(g["url"], quote=True)}" target="_blank" rel="noopener">Official call &rarr;</a></div>
      </div>
      {dates_html}
    </article>"""

    def programmes(items, css):
        parts = []
        for prog, group in _group(items):
            parts.append(f'    <div class="grp">\n    <h3 class="prog">{escape(prog)} <span>{len(group)}</span></h3>')
            parts += [card(g, v, d, css) for g, v, d in group]
            parts.append('    </div>')
        return "\n".join(parts)

    def slug(r):
        return re.sub(r"[^a-z]+", "-", r.lower()).strip("-")

    italy_html = programmes(italy, "") if italy else '    <p class="empty">No verified calls open to Italian institutions right now.</p>'
    other_parts = []
    for r in REGIONS:
        if by_region[r]:
            other_parts.append(f'    <div class="reg">\n    <h2 class="region" id="{slug(r)}">{escape(r)} <span>{len(by_region[r])}</span></h2>')
            other_parts.append(programmes(by_region[r], "other"))
            other_parts.append('    </div>')
    other_html = "\n".join(other_parts) or '    <p class="empty">No other calls right now.</p>'
    nav = [f'<a href="#italy">Open to Italy <b>{len(italy)}</b></a>']
    nav += [f'<a href="#{slug(r)}">{escape(r)} <b>{len(by_region[r])}</b></a>' for r in REGIONS if by_region[r]]
    c = cfg["colors"]
    return PAGE.format(brand=escape(cfg["brand_name"]), handle=escape(cfg["handle"]), ig=cfg["handle"].lstrip("@"),
                       bg=c["background"], muted=c["muted"], soft=c["muted_text"], teal=c["accent"],
                       accent=cfg.get("grant_accent", "#FFB547"), nav="".join(nav),
                       italy=italy_html, other=other_html, updated=_fmt_date(today), filters=filters_form(entries),
                       og=og_tags(cfg, f"Open research funding calls · {cfg['brand_name']}",
                                  "Open funding calls for clinical and rehabilitation research, checked on the official call text.",
                                  "calls"))


# ---------------------------------------------------------------- pagina iniziale (link in bio)
HOME = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{brand}</title>
<meta name="description" content="Open research funding calls and academic positions in clinical and rehabilitation research, checked on the official texts.">
{og}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
  :root {{ --bg: {bg}; --paper: #F3F6F9; --card: #15304A; --text: #FFFFFF; --soft: {soft}; --muted: {muted};
           --teal: {teal}; --amber: {amber}; --lilac: {lilac}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; min-height: 100vh; background: var(--bg); color: var(--text); font-family: Inter, system-ui, sans-serif; line-height: 1.45; }}
  .top {{ background: var(--paper); padding: 34px 16px 30px; text-align: center; border-top: 6px solid var(--teal); }}
  .top img {{ width: 340px; max-width: 100%; height: auto; display: block; margin: 0 auto 14px; }}
  .top p {{ color: #5B7186; margin: 0 auto; max-width: 420px; font-size: 15px; }}
  main {{ max-width: 520px; margin: 0 auto; padding: 26px 16px 40px; display: grid; gap: 16px; }}
  a.big {{ display: block; text-decoration: none; color: var(--bg); border-radius: 22px; padding: 22px 22px 20px; }}
  a.big.calls {{ background: var(--amber); }}
  a.big.jobs {{ background: var(--lilac); }}
  a.big .label {{ font-size: 13px; font-weight: 800; letter-spacing: .07em; text-transform: uppercase; opacity: .8; }}
  a.big .name {{ display: flex; justify-content: space-between; align-items: center; font-size: 27px; font-weight: 800; margin: 4px 0 6px; }}
  a.big .count {{ font-size: 15px; font-weight: 600; }}
  a.big:focus-visible {{ outline: 3px solid var(--text); outline-offset: 3px; }}
  a.big:hover {{ filter: brightness(1.05); }}
  .social {{ display: flex; justify-content: center; gap: 18px; margin-top: 8px; }}
  .social a {{ color: var(--soft); text-decoration: none; font-weight: 600; font-size: 14px; border: 1px solid var(--muted);
              border-radius: 999px; padding: 8px 14px; }}
  footer {{ color: var(--muted); font-size: 12px; text-align: center; padding: 0 16px 30px; max-width: 520px; margin: 0 auto; }}
</style>
</head>
<body>
<header class="top">
  <img src="logo-horizontal.png" alt="{brand}" width="340" height="128">
  <p>Clinical research methodology, made practical. Open funding calls and academic positions, checked on the official texts.</p>
</header>
<main>
  <a class="big calls" href="calls.html">
    <span class="label">Open calls</span>
    <span class="name">Funding calls <span aria-hidden="true">&rarr;</span></span>
    <span class="count">{calls_line}</span>
  </a>
  <a class="big jobs" href="positions.html">
    <span class="label">Open positions</span>
    <span class="name">Academic positions <span aria-hidden="true">&rarr;</span></span>
    <span class="count">{jobs_line}</span>
  </a>
  <div class="social">
    <a href="https://www.instagram.com/{ig}/">Instagram</a>
    <a href="https://www.facebook.com/{ig}">Facebook</a>
  </div>
</main>
<footer>Educational content for researchers and health professionals; not medical advice. Always check eligibility and deadlines in the official call or advertisement. Updated {updated}.</footer>
</body>
</html>
"""


def build_home(n_calls, n_italy, n_positions, cfg, today=None):
    from html import escape
    today = today or date.today()
    c = cfg["colors"]
    calls_line = f"{n_calls} open calls worldwide" + (f" · {n_italy} open to Italian institutions" if n_italy else "")
    jobs_line = f"{n_positions} open PhD, post-doc and faculty positions" if n_positions else "PhD, post-doc and faculty positions"
    return HOME.format(brand=escape(cfg["brand_name"]), ig=cfg["handle"].lstrip("@"), bg=c["background"],
                       soft=c["muted_text"], muted=c["muted"], teal=c["accent"],
                       amber=cfg.get("grant_accent", "#FFB547"), lilac=cfg.get("positions_accent", "#A78BFA"),
                       calls_line=escape(calls_line), jobs_line=escape(jobs_line), updated=_fmt_date(today),
                       og=og_tags(cfg, cfg["brand_name"], "Open research funding calls and academic positions in clinical "
                                  "and rehabilitation research, checked on the official texts.", ""))


def filters_form(entries):
    """Riquadro dei filtri della pagina bandi (parola chiave, area, scadenza): gratis per tutti, funziona nel browser."""
    from html import escape
    regions = "".join(f'<option value="{escape(r, quote=True)}">{escape(r)}</option>' for r in REGIONS)
    return f"""  <form class="filters" role="search" aria-label="Filter calls" onsubmit="return false">
    <label class="wide">Search<input type="search" name="q" placeholder="Keyword, funder, programme or country (e.g. stroke, NIH, Germany)" autocomplete="off"></label>
    <label>Applicants based in<select name="where"><option value="">Anywhere</option><option value="italy">Italy (open to Italian institutions)</option>{regions}</select></label>
    <label>Deadline<select name="time"><option value="">Any deadline</option><option value="lt30">Closing within 30 days</option>
      <option value="ge30">At least 30 days left</option><option value="ge60">At least 60 days left</option><option value="ge90">At least 90 days left</option></select></label>
    <div class="status"><span class="count" aria-live="polite">{len(entries)} open calls</span><button type="reset" hidden>Clear filters</button></div>
  </form>
"""


FILTER_SCRIPT = """
<script>
(function () {
  var form = document.querySelector("form.filters");
  if (!form) return;
  var cards = Array.prototype.slice.call(document.querySelectorAll("article.call"));
  var count = form.querySelector(".count"), reset = form.querySelector("button[type=reset]"), total = cards.length;
  var DAY = 86400000, today = new Date(); today.setHours(0, 0, 0, 0);
  function norm(t) { return (t || "").toLowerCase().normalize("NFD").replace(/[\\u0300-\\u036f]/g, ""); }
  cards.forEach(function (c) { c._text = norm(c.dataset.text); });
  function apply(save) {
    var q = norm(form.q.value).trim(), where = form.where.value, time = form.time.value, words = q ? q.split(/\\s+/) : [], shown = 0;
    cards.forEach(function (c) {
      var ok = words.every(function (w) { return c._text.indexOf(w) !== -1; });
      if (ok && where === "italy") ok = c.dataset.italy === "yes";
      else if (ok && where) ok = c.dataset.region === where || (where !== "International & intercontinental" && c.dataset.region === "International & intercontinental");
      if (ok && time) {
        var d = c.dataset.deadline ? (new Date(c.dataset.deadline + "T00:00:00") - today) / DAY : null;
        ok = d !== null && (time === "lt30" ? d < 30 : d >= parseInt(time.slice(2), 10));
      }
      c.hidden = !ok; if (ok) shown++;
    });
    document.querySelectorAll(".grp").forEach(function (g) { g.hidden = !g.querySelector("article.call:not([hidden])"); });
    document.querySelectorAll(".reg").forEach(function (g) { g.hidden = !g.querySelector("article.call:not([hidden])"); });
    document.querySelectorAll("section.macro").forEach(function (s) {
      var none = s.querySelector("article.call") && !s.querySelector("article.call:not([hidden])"), msg = s.querySelector(".nomatch");
      if (none && !msg) { msg = document.createElement("p"); msg.className = "nomatch"; msg.textContent = "No calls in this section match your filters."; s.appendChild(msg); }
      if (msg) msg.hidden = !none;
    });
    var active = !!(q || where || time);
    count.textContent = active ? "Showing " + shown + " of " + total + " open calls" : total + " open calls";
    reset.hidden = !active;
    if (save) {
      var p = new URLSearchParams();
      if (form.q.value.trim()) p.set("q", form.q.value.trim()); if (where) p.set("where", where); if (time) p.set("time", time);
      var qs = p.toString();
      history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
    }
  }
  var p = new URLSearchParams(location.search);
  if (p.get("q")) form.q.value = p.get("q");
  if (p.get("where")) form.where.value = p.get("where");
  if (p.get("time")) form.time.value = p.get("time");
  var timer;
  form.q.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(function () { apply(true); }, 150); });
  form.where.addEventListener("change", function () { apply(true); });
  form.time.addEventListener("change", function () { apply(true); });
  form.addEventListener("reset", function () { setTimeout(function () { apply(true); }, 0); });
  apply(false);
})();
</script>
"""


# ---------------------------------------------------------------- pulsante «Share» (bandi e posizioni)
SHARE = """
<div id="crc-share-menu" role="menu" hidden></div>
<style>
  button.share { display: inline-flex; align-items: center; gap: 6px; background: transparent; color: var(--text);
                 border: 1px solid var(--muted); border-radius: 12px; padding: 9px 14px; font: 700 14px Inter, system-ui, sans-serif;
                 cursor: pointer; }
  button.share svg { width: 16px; height: 16px; }
  button.share:hover { border-color: var(--text); }
  button.share:focus-visible { outline: 3px solid var(--text); outline-offset: 2px; }
  .call:target, .job:target { outline: 2px solid var(--accent); outline-offset: 3px; }
  #crc-share-menu { position: absolute; z-index: 50; background: #FFFFFF; color: #0E2233; border-radius: 14px; padding: 6px;
                    min-width: 190px; box-shadow: 0 12px 32px rgba(0,0,0,.35); font: 600 14px Inter, system-ui, sans-serif; }
  #crc-share-menu a, #crc-share-menu button { display: block; width: 100%; text-align: left; background: none; border: 0;
                    color: inherit; font: inherit; text-decoration: none; padding: 10px 12px; border-radius: 10px; cursor: pointer; }
  #crc-share-menu a:hover, #crc-share-menu button:hover, #crc-share-menu a:focus-visible, #crc-share-menu button:focus-visible {
                    background: #E7EEF4; outline: none; }
</style>
<script>
(function () {
  var menu = document.getElementById("crc-share-menu"), openFor = null;
  var coarse = window.matchMedia("(pointer: coarse)").matches;
  function close() { menu.hidden = true; openFor = null; }
  function item(label, href) {
    var a = document.createElement("a"); a.textContent = label; a.href = href; a.target = "_blank"; a.rel = "noopener";
    a.setAttribute("role", "menuitem"); a.addEventListener("click", close); return a;
  }
  function show(btn) {
    var url = btn.dataset.url, title = btn.dataset.title, text = title + " " + url, e = encodeURIComponent;
    menu.innerHTML = "";
    menu.appendChild(item("WhatsApp", "https://wa.me/?text=" + e(text)));
    menu.appendChild(item("LinkedIn", "https://www.linkedin.com/sharing/share-offsite/?url=" + e(url)));
    menu.appendChild(item("Facebook", "https://www.facebook.com/sharer/sharer.php?u=" + e(url)));
    menu.appendChild(item("X", "https://x.com/intent/post?text=" + e(title) + "&url=" + e(url)));
    menu.appendChild(item("Email", "mailto:?subject=" + e(title) + "&body=" + e(text)));
    var copy = document.createElement("button"); copy.type = "button"; copy.textContent = "Copy link"; copy.setAttribute("role", "menuitem");
    copy.addEventListener("click", function () {
      var done = function () { copy.textContent = "Link copied"; setTimeout(close, 900); };
      if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, function () { window.prompt("Copy this link", url); close(); });
      else { window.prompt("Copy this link", url); close(); }
    });
    menu.appendChild(copy);
    var r = btn.getBoundingClientRect();
    menu.hidden = false;
    var left = Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - menu.offsetWidth - 12);
    menu.style.left = Math.max(12, left) + "px";
    menu.style.top = (window.scrollY + r.bottom + 6) + "px";
    openFor = btn; menu.querySelector("a").focus();
  }
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest && ev.target.closest("button.share");
    if (btn) {
      ev.preventDefault();
      if (coarse && navigator.share) {
        navigator.share({ title: btn.dataset.title, text: btn.dataset.title, url: btn.dataset.url }).catch(function () {});
        return;
      }
      if (openFor === btn) close(); else show(btn);
    } else if (!menu.contains(ev.target)) close();
  });
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape" && openFor) { var b = openFor; close(); b.focus(); } });
})();
</script>
"""

SHARE_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
              'stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/>'
              '<circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/></svg>')


def share_button(url, title):
    from html import escape
    return (f'<button class="share" type="button" data-url="{escape(url, quote=True)}" data-title="{escape(title, quote=True)}" '
            f'aria-haspopup="menu">{SHARE_ICON}Share</button>')


def site_url(cfg, path=""):
    """Indirizzo pubblico di una pagina del sito (Cloudflare Pages serve le pagine senza «.html»)."""
    return cfg.get("links_page_url", "").rstrip("/") + "/" + path


def og_tags(cfg, title, description, path):
    from html import escape
    return (f'<link rel="canonical" href="{escape(site_url(cfg, path), quote=True)}">\n'
            f'<meta property="og:type" content="website">\n'
            f'<meta property="og:site_name" content="{escape(cfg["brand_name"], quote=True)}">\n'
            f'<meta property="og:title" content="{escape(title, quote=True)}">\n'
            f'<meta property="og:description" content="{escape(description, quote=True)}">\n'
            f'<meta property="og:url" content="{escape(site_url(cfg, path), quote=True)}">\n'
            f'<meta property="og:image" content="{escape(site_url(cfg, "og.png"), quote=True)}">\n'
            f'<meta name="twitter:card" content="summary_large_image">')


def card_anchor(grant_id):
    return "c-" + re.sub(r"[^A-Za-z0-9]+", "-", str(grant_id)).strip("-")


# ---------------------------------------------------------------- decorazione animata ai lati (solo schermi larghi)
DECOR = """
<div id="crc-rain" class="crc-side" aria-hidden="true"></div>
<div id="crc-rain-r" class="crc-side" aria-hidden="true"></div>
<style>
  .crc-side { position: fixed; top: 0; bottom: 0; width: calc((100vw - 740px) / 2); pointer-events: none; z-index: 0; display: none; }
  #crc-rain { left: 0; }
  #crc-rain-r { right: 0; }
  .crc-side canvas { display: block; width: 100%; height: 100%; }
  @media (min-width: 1180px) { .crc-side { display: block; } }
  main, header, footer, .bar { position: relative; z-index: 1; }
</style>
<script>
(function () {
  var wide = window.matchMedia("(min-width: 1180px)");
  var still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var started = false;
  function start() {
    if (started || !wide.matches) return;
    started = true;
    var COLORS = ["#3DD9C1", "#14A085", "#FFFFFF", "#7F96AB"];
    var SIZES = [4, 6, 8, 10, 12], SHAPES = [[], [], [[1, 0]], [[0, 1]], [[1, 0], [0, 1]], [[1, 0], [1, 1]]];
    function pick(a) { return a[Math.floor(Math.random() * a.length)]; }
    /* cascata lenta di quadratini ai due lati, singoli o a piccoli gruppi come nel logo */
    function side(id) {
      var el = document.getElementById(id), c = document.createElement("canvas"), ctx = c.getContext("2d");
      el.appendChild(c);
      var L = { ctx: ctx, drops: [], R: null };
      function drop(y) {
        return { x: Math.random() * L.R.width, y: (y === undefined ? -40 : y), s: pick(SIZES), v: 7 + Math.random() * 20,
                 c: pick(COLORS), a: 0.12 + Math.random() * 0.5, shape: pick(SHAPES) };
      }
      L.fit = function () {
        var r = el.getBoundingClientRect(), d = window.devicePixelRatio || 1;
        c.width = r.width * d; c.height = r.height * d; ctx.setTransform(d, 0, 0, d, 0, 0); L.R = r;
        L.drops = []; var n = Math.round(r.width * r.height / 7500);
        for (var i = 0; i < n; i++) L.drops.push(drop(Math.random() * r.height));
      };
      L.step = function (dt) {
        ctx.clearRect(0, 0, L.R.width, L.R.height);
        L.drops.forEach(function (d) {
          d.y += d.v * dt;
          if (d.y > L.R.height + 40) { var n = drop(); for (var k in n) d[k] = n[k]; }
          ctx.globalAlpha = d.a; ctx.fillStyle = d.c; ctx.fillRect(d.x, d.y, d.s, d.s);
          d.shape.forEach(function (o) { ctx.fillRect(d.x + o[0] * (d.s + 2), d.y + o[1] * (d.s + 2), d.s, d.s); });
        });
      };
      L.fit();
      return L;
    }
    var sides = [side("crc-rain"), side("crc-rain-r")];
    var last = performance.now();
    function frame(t) {
      var dt = Math.min(0.05, (t - last) / 1000); last = t;
      sides.forEach(function (L) { L.step(dt); });
      if (!still) requestAnimationFrame(frame);
    }
    window.addEventListener("resize", function () { sides.forEach(function (L) { L.fit(); }); if (still) frame(performance.now()); });
    requestAnimationFrame(frame);
  }
  start();
  if (wide.addEventListener) wide.addEventListener("change", start);
})();
</script>
"""


def add_decor(html):
    """Aggiunge prima di </body> la decorazione animata ai lati (cascata di quadratini) e, se la pagina ha
    pulsanti «Share», il menu di condivisione."""
    if "crc-rain" not in html:
        html = html.replace("</body>", DECOR + "</body>", 1)
    if 'class="share"' in html and "crc-share-menu" not in html:
        html = html.replace("</body>", SHARE + "</body>", 1)
    if 'class="filters"' in html and "form.filters\")" not in html:
        html = html.replace("</body>", FILTER_SCRIPT + "</body>", 1)
    return html
