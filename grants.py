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
VERIFY_VERSION = 3          # 2 = scadenze dal testo ufficiale e requisiti del capofila; 3 = date NIH lette riga per riga


def checked(v):
    """Scadenze della voce affidabili con le regole attuali (le date NIH della versione 2 vanno rilette)."""
    ver = (v or {}).get("version", 1)
    if str((v or {}).get("model", "")).startswith(("groq", "openrouter")):
        return False                 # verificato con il ripiego (Gemini esaurito): si rifà con Gemini prima dei post
    return ver >= VERIFY_VERSION or (ver == 2 and not str(v.get("official_source", "")).startswith("NIH Guide"))

PROMPT = """You write an Instagram carousel for "{brand}", a page for researchers and health professionals
about clinical research and research methodology. The post informs followers about ONE research funding
call. Below is the OFFICIAL TEXT of the call and the facts already verified on it.

STRICT ACCURACY RULES:
- Use ONLY the official text. Translate and rephrase, but never add facts, numbers, dates, amounts,
  eligibility rules or requirements that are not in it.
- Do not write the deadline, amounts, the funder or the eligible countries in the slides: they are added
  separately from verified data.
- Keep every qualifier of the official text about who can apply and what is funded (career stage and how it is
  defined, mandatory partners, type of organisation, excluded activities): never make the call sound open to more
  people or projects than it is.
- Each sentence must make sense on its own, as a screenshot: name what is funded and for whom (never "it", "this
  programme", "the applicants" without saying who).

Write IN ENGLISH:
- title: the cover hook, max 70 characters: say who the call is for and what it funds, phrased so the right
  researcher stops scrolling (e.g. "Stroke rehab trial in mind? Grants for pilot studies" or "Early-career in
  rehab research? This call backs your first project"). Facts only from the official text; no deadline, amounts
  or funder. VARY the structure: never start with "Funding for", and never open with the same words as these
  recent titles: {recent}.
- title_highlight: 1-4 words copied EXACTLY from the title.
- slides: exactly 2 slides. Slide 1 heading "What it funds": aim and kind of projects funded.
  Slide 2 heading "Who it is for": applicants and teams it targets. Each body max 220 characters.
  Each slide also has image_prompt: 15-35 words describing ONE simple illustration of the slide's idea
  (concrete scene with 2-4 recognizable elements; no text, letters, numbers, logos or real people),
  photo_query: 2-4 English keywords to search a real stock photo of the research area or of the team it
  targets (e.g. "stroke rehabilitation therapy", "clinical trial nurse patient"),
  and highlight: its key idea, 2-6 words copied EXACTLY from its body.
- coverage: funding coverage in a few words (e.g. "Fully funded"), or "" if not stated.
- hook: the FIRST line of the caption, max 120 characters: tell the right researchers, in plain words, why
  this call is for them (e.g. "Running a pilot rehabilitation trial? This call funds exactly that.").
  Only from the official text; no deadline, amounts, funder or countries; no hashtags, at most one emoji.
  Include the research area as people would search it (e.g. "stroke rehabilitation", "rare diseases"):
  Instagram search reads the first line.
- caption: 2-4 short lines with context that come AFTER the hook; end with a question inviting researchers
  to share whether they plan to apply or know similar calls. Max 500 characters, no hashtags, no links.
- hashtags: 3 specific hashtags for the research area (e.g. #Neurorehabilitation #StrokeResearch #RareDiseases);
  Instagram allows at most 5 per post and the bot adds #ResearchFunding and #ClinicalResearch.

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
                               "image_prompt": {"type": "STRING"}, "photo_query": {"type": "STRING"},
                               "highlight": {"type": "STRING"}},
                "required": ["heading", "body", "image_prompt", "photo_query", "highlight"],
            },
        },
        "coverage": {"type": "STRING"},
        "hook": {"type": "STRING"},
        "caption": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["title", "title_highlight", "slides", "hook", "caption", "hashtags"],   # niente takeaway nei bandi (5/11)
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


def _non_italy_this_week(posted, verified, today):
    """Quanti bandi NON aperti all'Italia sono usciti negli ultimi 7 giorni (regola: al massimo uno)."""
    n = 0
    for p in posted:
        if p.get("kind") != "grant" or not p.get("time"):
            continue
        when = datetime.fromisoformat(p["time"]).date()
        if (today - when).days < 7 and verified.get(p.get("grant_id"), {}).get("italy") == "no":
            n += 1
    return n


def eligibility_flag(v):
    """Avviso per la copertina quando il bando non è aperto a chi lavora in Italia."""
    if v.get("italy") != "no":
        return ""
    return "US teams only" if "united states" in (v.get("eligible_countries") or "").lower() \
        else "Not open to Italy"


def candidates(grants, posted, verified, cfg, today=None):
    """Bandi da pubblicare: verificati sul testo ufficiale, call aperta, pertinenza Alta/Media, scadenza
    abbastanza lontana, mai pubblicati. L'idoneità per Paese deve essere chiara («yes» o «no» per l'Italia:
    mai bandi con idoneità sconosciuta o non ancora pubblicati); prima i bandi aperti all'Italia, e al massimo
    un bando non aperto all'Italia (es. solo USA) a settimana, segnalato in copertina."""
    today = today or date.today()
    done = {p.get("grant_id") for p in posted if p.get("grant_id")}
    non_italy_used = _non_italy_this_week(posted, verified, today)
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
            if (v.get("status") == "ok" and checked(v)
                    and v.get("is_open_call") != "no" and not v.get("coming_soon")
                    and v.get("italy") in ("yes", "no")              # idoneità chiara, mai «unclear»
                    and not (v.get("italy") == "no" and non_italy_used >= 1)
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
        # (29/10, approvato) solo la regola rigida: mai lo stesso programma due volte di fila; per il resto
        # si ordina per pertinenza e scadenza, senza escludere i programmi degli ultimi 3 bandi
        if out:
            return sorted(out, key=lambda g: (0 if verified[g["id"]].get("italy") == "yes" else 1,
                                              RELEVANCE_ORDER[g["rilevanza"]], next_due(g, verified[g["id"]], today)))
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
    "Latin America": r"brazil|argentina|chile|colombia|mexico|peru|uruguay|ecuador|bolivia|paraguay|venezuela|"
                     r"costa rica|panama|guatemala|cuba|latin america|ibero-?america",
    "Asia": r"japan|china|india|singapore|korea|taiwan|hong kong|thailand|vietnam|malaysia|philippines|indonesia|"
            r"pakistan|bangladesh|sri lanka|nepal|saudi|emirates|\buae\b|qatar|israel|turkey|t[uü]rkiye|iran|jordan|asia",
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


GUIDED_SEARCH = {"European national funders": "Europe", "Africa": "Africa", "Latin America": "Latin America", "Brazil": "Latin America", "Japan": "Asia", "South Korea": "Asia",
                 "China, Taiwan and Hong Kong": "Asia", "India": "Asia", "Southeast Asia": "Asia", "Middle East": "Asia",
                 "Australia and New Zealand": "Oceania", "Global South and international": REGIONS[0]}


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
    if gid.startswith("EU-") or (g.get("fonte") or "").startswith("ERA-LEARN"):
        return "Europe"
    if gid.startswith("GG-") or g.get("fonte") == "Grants.gov":
        return "North America"
    fonte = g.get("fonte") or ""
    if fonte.startswith("Ricerca web – "):                 # ricerca guidata di GrantFinder: zona della ricerca
        return GUIDED_SEARCH.get(fonte.split("– ", 1)[1], REGIONS[0])
    return funder_continents(cfg).get(fonte) or REGIONS[0]


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
        for k, val in syn.items():            # altre date di chiusura della scheda (i nomi dei campi variano)
            if (re.search(r"response|close|deadline", k, re.I) and not re.search(r"^est|desc$|^responseDate(Str)?$", k, re.I)
                    and isinstance(val, (str, int)) and str(val).strip()):
                parts.append(f"Grants.gov closing date for applications ({k}): {val}")
        datey = {k: str(v)[:40] for k, v in syn.items() if re.search(r"date", k, re.I) and isinstance(v, (str, int))}
        print(f"::notice title=Date Grants.gov::{g.get('id')} | {'synopsis' if data.get('synopsis') else 'forecast'} | {datey}")
        if data.get("forecast") and not data.get("synopsis"):
            parts.append("Note: this is a FORECAST on Grants.gov; dates are estimates, not deadlines.")
            if syn.get("estApplicationResponseDate"):
                parts.append(f"Grants.gov estimated application deadline (forecast): {syn['estApplicationResponseDate']}")
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
    for m in RX_NUM.finditer(s or ""):       # gg/mm/aaaa o mm/gg/aaaa (Grants.gov): se ambigua valgono entrambe
        out.append((int(m.group(3)), int(m.group(2)), int(m.group(1))))
        out.append((int(m.group(3)), int(m.group(1)), int(m.group(2))))
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
    src = html or text
    i = src.lower().find("application due date")
    region_text = (html_to_text(src[i:i + 30000]) if html else src[i:i + 6000]) if i >= 0 else ""
    cut = re.search(r"All applications are due by|Expiration Date|Due Dates for E\.O\.", region_text[25:])
    region_text = region_text[:cut.start() + 25] if cut else region_text[:4000]
    if region_text and not re.search(r"standard dates apply", region_text, re.I):
        # righe della tabella: date con il giorno (nuove, resubmission, AIDS) seguite da mesi senza giorno (revisione)
        first = RX_MDY.search(region_text)
        header = region_text[:first.start()] if first else region_text
        two_cols = bool(re.search(r"\bNew\s*(?:\||\s)\s*Renewal", header, re.I))
        tok = re.compile(r"(?P<d>" + RX_MDY.pattern + r")|(?P<m>" + _MON + r"\s+\d{4})|(?P<n>Not Applicable)", re.I)
        rows, row = [], []
        for m in tok.finditer(region_text[first.start():] if first else ""):
            if m.group("m"):
                if row:
                    rows.append(row)
                row = []
            else:
                row.append(dates_in(m.group("d"))[0] if m.group("d") else None)
        if row:
            rows.append(row)
        if len(rows) == 1 and not two_cols:      # date in fila, senza tabella: tutte per le nuove domande
            rows = [[d] for d in rows[0] if d]
        for r in rows:
            if r and r[0]:
                new.append(r[0])
            if two_cols and len(r) > 1 and r[1]:
                resub.append(r[1])
            elif not two_cols and r and r[0]:
                resub.append(r[0])
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
    if is_nih(g):
        # NIH: valgono solo le date del NIH Guide; la «closing date» di Grants.gov è la data di fine bando
        if not source.startswith("NIH Guide"):
            return base
        if re.search(r"closing date", out.get("deadline_evidence") or "", re.I):
            out = {**out, "deadline_evidence": ""}
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


def forecast_info(text):
    """Previsione di Grants.gov: la scadenza è solo stimata (si mostra come tale, mai nei post)."""
    if "this is a FORECAST on Grants.gov" not in text:
        return {}
    m = re.search(r"estimated application deadline \(forecast\): ([^.]{0,60})", text)
    ds = dates_in(m.group(1)) if m else []
    return {"forecast": True, "est_deadline": ds[0].isoformat() if ds else ""}


def next_due(g, v, today=None):
    """Prossima data utile per una nuova domanda; per le voci non ancora ricontrollate, la data del catalogo."""
    today = today or date.today()
    if checked(v):
        ds = [d for d in (_date(x) for x in v.get("due_dates") or []) if d and d >= today]
        return min(ds) if ds else None
    if is_nih(g):
        return None                          # per l'NIH la data del catalogo è la fine del bando: mai mostrarla
    return _date(g.get("scadenza"))


def later_dues(v, after):
    return [d for d in (_date(x) for x in (v or {}).get("due_dates") or []) if d and after and d > after]


def closed_for_new(v, today=None):
    """Bando ricontrollato con date trovate, ma tutte passate: chiuso per le nuove domande."""
    today = today or date.today()
    return (checked(v) and v.get("deadline_source") not in (None, "none")
            and v.get("deadline_type") != "rolling" and next_due({}, v, today) is None)


def lead_line(out, text):
    ev = _quoted(out.get("lead_evidence"), text, 20)
    lead = (out.get("lead_eligibility") or "").strip()
    return (lead[:160], ev[:300]) if lead and ev else ("", "")


def verify(g, cfg, task="verifica bandi"):
    """Legge la call ufficiale e restituisce i dati verificati del bando (per la pagina e per i post).
    `task` decide i modelli: «verifica bandi» = screening sui leggeri, «conferma bandi» = secondo parere dei forti."""
    text, source, source_url = official_text(g)
    if len(text) < 400:
        raise RuntimeError(f"testo ufficiale troppo breve ({len(text)} caratteri) da {source}")
    data = "\n".join(f"{k}: {g.get(k)}" for k in FIELDS if g.get(k))
    out = content.gemini_json([{"text": VERIFY_PROMPT.format(source=source, official=text[:60000], data=data,
                                                              today=date.today().isoformat())}],
                              VERIFY_SCHEMA, 0.1, task=task)
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
        "version": VERIFY_VERSION, "model": content.LAST_MODEL, **dl, "lead": lead, "lead_evidence": lead_ev,
        "deadline_raw": f"{out.get('next_deadline', '')} | {(out.get('deadline_evidence') or '')[:200]}",
        **forecast_info(text),
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
        if v.get("status") == "ok" and (not checked(v) or (
                v.get("deadline_source") == "none" and g.get("scadenza") and not is_nih(g)
                and v.get("dl_tries", 0) < 2)):
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
    # alternati: un bando che scade presto (perché non si chiuda prima della verifica) e uno che può andare in un post
    soon_l = sorted([g for g in todo if (g.get("scadenza") or "9999") < soon], key=lambda g: g.get("scadenza") or "9999")
    later_l = sorted([g for g in todo if (g.get("scadenza") or "9999") >= soon], key=lambda g: g.get("scadenza") or "9999")
    todo = [g for pair in zip(later_l, soon_l) for g in pair] + later_l[len(soon_l):] + soon_l[len(later_l):]
    done = 0
    start, budget = time.time(), float(cfg.get("grant_verify_minutes", 13)) * 60
    import content
    for g in todo[:limit]:
        if not content.checks_allowed():
            print(f"::notice title=Verifica bandi ferma::quota Gemini di oggi lasciata ai post ({content.gemini_used_today()} richieste usate)")
            break
        if time.time() - start > budget:     # resta nel tempo del job: il resto al prossimo run
            print(f"::notice title=Verifica a metà::tempo esaurito dopo {done} bandi, si riprende al prossimo run")
            break
        try:
            prev = verified.get(g["id"], {})
            verified[g["id"]] = verify(g, cfg)
            v = verified[g["id"]]
            if v.get("deadline_source") == "none":
                v["dl_tries"] = prev.get("dl_tries", 0) + 1
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


CONFIRM_FIELDS = ("is_open_call", "italy", "due_dates", "deadline_type", "eligible_countries", "loi_required")


def confirmed(v):
    return bool((v or {}).get("confirmed", {}).get("model"))


def confirm_candidates(grants, verified, posted, cfg, limit=None, today=None):
    """Secondo parere di un modello forte sui bandi ad ALTA PRIORITÀ: quelli che lo screening (modelli leggeri)
    rende pubblicabili, nell'ordine in cui andrebbero nei post. Il forte rilegge la call ufficiale con lo stesso
    prompt; se su un campo che conta (aperto, Italia, date, Paesi) non è d'accordo, vale il suo risultato e il
    disaccordo resta scritto in «confirmed.changed». Senza quota dei forti (oltre la riserva per i post) ci si
    ferma: i bandi restano col solo screening e si confermano al giro dopo."""
    import time
    limit = int(limit if limit is not None else cfg.get("grant_confirm_per_run", 6))
    done = 0
    for g in candidates(grants, posted, verified, cfg, today):
        if done >= limit:
            break
        lite = verified.get(g["id"], {})
        if confirmed(lite):
            continue
        try:
            strong = verify(g, cfg, task="conferma bandi")
        except Exception as e:
            if "non disponibile" in str(e):
                print(f"::notice title=Conferma bandi ferma::nessun modello forte libero oltre la riserva per i post ({done} confermati)")
                break
            print(f"::warning title=Conferma non riuscita::{g['id']} - {str(e)[:200]}")
            done += 1
            continue
        changed = [k for k in CONFIRM_FIELDS if (lite.get(k) or "") != (strong.get(k) or "")]
        strong["confirmed"] = {"model": strong.get("model", ""), "date": date.today().isoformat(), "changed": changed,
                               "screening_model": lite.get("model", "")}
        if lite.get("dl_tries"):
            strong["dl_tries"] = lite["dl_tries"]
        verified[g["id"]] = strong
        print(f"::notice title=Bando confermato::{g['id']} | {strong['confirmed']['model']} | "
              + (f"corretti: {', '.join(changed)}" if changed else "d'accordo con lo screening"))
        done += 1
        time.sleep(3)
    return done


def deadline_text(v, d):
    """(etichetta, nota) della scadenza mostrata: prossima di più date, fase 1, data del catalogo confermata."""
    t = (v or {}).get("deadline_type")
    if t == "two_stage":
        return "Stage 1 deadline", "two-stage call"
    if later_dues(v, d) or len((v or {}).get("due_dates") or []) > 1:
        return "Next deadline", "new applications"
    return "Deadline", ""


def fresh_title(title, recent):
    """Vero se il titolo non ricalca l'attacco dei titoli recenti (varietà senza AI)."""
    first2 = " ".join(_simple(title).split()[:2])
    return (not _simple(title).startswith("funding for")
            and sum(1 for t in recent if " ".join(_simple(t).split()[:2]) == first2) == 0)


def build_post(g, v, cfg, recent_titles=()):
    """Prepara il post di un bando già verificato (`v`): testo da Gemini sul testo ufficiale, fatti dai dati verificati."""
    text, source, _ = official_text(g)
    prompt = PROMPT.format(brand=cfg["brand_name"], programme=v["programme"], countries=v["eligible_countries"],
                           source=source, official=text[:60000],
                           recent="; ".join(f"\u201c{t}\u201d" for t in recent_titles) or "none")
    out = content.gemini_json([{"text": prompt}], SCHEMA, 0.2, task="post bando")
    if out.get("title") and not fresh_title(out["title"], recent_titles):
        print(f"  Titolo ripetitivo ({out['title']!r}): riprovo una volta")
        retry = prompt + ("\n\nIMPORTANT: your previous title was rejected for repeating a recent opening "
                          f"({out['title']!r}). Write a title with a clearly different structure.")
        try:
            out2 = content.gemini_json([{"text": retry}], SCHEMA, 0.4, task="post bando")
            if out2.get("title") and fresh_title(out2["title"], recent_titles) and len(out2.get("slides") or []) >= 2:
                out = out2
        except Exception as e:
            print(f"  Secondo tentativo non riuscito ({str(e)[:120]}): tengo il primo")
    clip = content._clip
    slides = []
    for sl in out.get("slides", []):
        if sl.get("heading") and sl.get("body"):
            body = clip(sl["body"], 320)
            slides.append({"heading": clip(sl["heading"], 70), "body": body,
                           "image_prompt": clip(sl.get("image_prompt", ""), 300),
                           "photo_query": clip(sl.get("photo_query", ""), 60),
                           "highlight": content.exact_phrase(sl.get("highlight"), body)})
    slides = slides[:2]
    if len(slides) < 2 or not out.get("title"):
        raise RuntimeError(f"Testo del bando incompleto per {g['id']}")
    review = None
    if cfg.get("cross_review", True):
        # revisione incrociata sul testo ufficiale: precisione su scopo e destinatari, frasi comprensibili da sole
        draft = {"title": content._clip(out["title"], 90), "title_highlight": out.get("title_highlight", ""),
                 "slides": slides, "hook": out.get("hook", ""), "caption": out.get("caption", "")}
        writer = "google" if not content.LAST_MODEL.startswith("openrouter") else content._family_of_last()
        review = content.cross_review(draft, text, kind="grant", writer_family=writer)
        if review.get("passed") is False:
            raise RuntimeError(f"Post del bando {g['id']} respinto dalla revisione: " + "; ".join(review.get("notes", [])[:3])[:300])
        out.update({k: draft[k] for k in ("title", "title_highlight", "hook", "caption")})
        slides = draft["slides"]

    deadline = next_due(g, v)
    if not deadline:
        raise RuntimeError(f"Nessuna data utile verificata per {g['id']}")
    title = clip(out["title"], 90)
    dl_label, dl_note = deadline_text(v, deadline)
    funder = funder_line(g)
    facts = [("Programme", clip(v["programme"], 90))]
    if funder and _simple(funder) not in _simple(v["programme"]) and _simple(v["programme"]) not in _simple(funder):
        facts.append(("Funder", clip(funder, 80)))       # solo se non ripete il programma
    facts.append((dl_label, _fmt_date(deadline) + (f" ({dl_note})" if dl_note else "")))
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
    caption = (f"{content.with_hook(out.get('hook'), out.get('caption', ''), 640)}\n\n"
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
        "takeaway": "", "takeaway_highlight": "",          # rubrica Funding calls: nessun key takeaway (5/11)
        "category": "Funding opportunity",
        "funder": clip(v["programme"], 110), "eligibility_flag": eligibility_flag(v),
        "deadline": _fmt_date(deadline), "deadline_iso": deadline.isoformat(),
        "url": g["url"], "slides": slides, "facts": [(k, val) for k, val in facts if val],
        "closing_cta": ("Check the official call before applying", "All open calls: link in bio"),
        "caption": caption, "hashtags": ["#ResearchFunding", "#GrantOpportunity"] + tags[:10],
        "summary": v.get("summary", ""), "italy_evidence": v.get("italy_evidence", ""), "official_title": v.get("title", ""),
        "official_source": v.get("official_source", ""), "source": "GrantFinder", "source_hint": g.get("fonte", ""),
        "review": {k: (review or {}).get(k) for k in ("passed", "scores", "critic", "arbiter", "fixed", "notes")} if review else None,
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
    import time
    for g in pool[:3]:
        for attempt in range(2):                 # un errore di rete momentaneo non fa saltare il post
            try:
                recent = [p.get("title", "") for p in posted if p.get("kind") == "grant" and p.get("title")][-6:]
                post = build_post(g, verified[g["id"]], cfg, recent)
                print(f"::notice title=Bando scelto::{g['id']} | {verified[g['id']]['programme']}")
                return post
            except Exception as e:
                transient = any(k in str(e) for k in ("Connection", "Timeout", "timed out", "RemoteDisconnected", " 503", " 500"))
                print(f"::warning title=Post del bando non generato::{g['id']} (tentativo {attempt + 1}) - {str(e)[:300]}")
                if not transient:
                    break
                time.sleep(30)
    return None


# ---------------------------------------------------------------- pagina «link in bio»
PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Open funding calls for clinical research &amp; rehabilitation · {brand}</title>
<meta name="description" content="{description}">
{og}
<link rel="alternate" type="application/rss+xml" title="Open funding calls" href="feed-calls.xml">
<link rel="alternate" type="application/rss+xml" title="Academic positions" href="feed-positions.xml">
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
  .call h4 a {{ color: inherit; text-decoration: none; }}
  .call h4 a:hover, .call h4 a:focus-visible {{ text-decoration: underline; text-decoration-color: var(--accent); }}
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
  form.filters .hint {{ grid-column: 1 / -1; margin: 0; font-size: 12px; color: var(--muted); }}
  form.filters .status {{ grid-column: 1 / -1; display: flex; justify-content: space-between; align-items: center; gap: 10px;
                         font-size: 14px; color: var(--soft); }}
  form.filters button {{ background: transparent; color: var(--text); border: 1px solid var(--muted); border-radius: 999px;
                        padding: 6px 12px; font: 600 13px Inter, system-ui, sans-serif; cursor: pointer; }}
  form.filters button[hidden] {{ display: none; }}
  @media (max-width: 520px) {{ form.filters {{ grid-template-columns: 1fr; }} }}
  .nomatch {{ color: var(--soft); background: var(--card); border-radius: 18px; padding: 18px 20px; font-size: 15px; }}
  .report {{ display: inline-block; margin-top: 10px; font-size: 12px; color: var(--muted); }}
  [hidden] {{ display: none !important; }}
  footer {{ color: var(--muted); font-size: 13px; margin-top: 36px; }}
  footer a {{ color: var(--teal); }}
</style>
</head>
<body>
<div class="bar"></div>
<main>
  {lockup}
  <a class="switch" href="index.html">&larr; Home</a><a class="switch" href="positions.html">Academic positions &rarr;</a><a class="switch" href="methodology.html">Design, Reporting &amp; Appraisal &rarr;</a><a class="switch" href="science.html">Latest Science &rarr;</a><br>
  <span class="badge">FUNDING CALLS</span>
  <h1>Research funding calls</h1>
  <p class="intro">All open calls for clinical research, clinical and biomedical engineering and rehabilitation found by our monitoring, from funders worldwide, including calls reserved for applicants in a single country: use the filters.
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
    Updated {updated} · <a href="https://www.instagram.com/{ig}/">{handle} on Instagram</a> · <a href="rss.html">RSS feed</a>
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


def when_html(v, d, today):
    """Riga della scadenza di un bando (scheda e pagina propria)."""
    from html import escape
    if d:
        label = deadline_text(v, d)[0] if checked(v) else "Deadline"
        return f"{label} <b>{_fmt_date(d)}</b>"
    if v.get("deadline_type") == "rolling":
        return "Deadline <b>rolling, no fixed date</b>"
    if v.get("forecast") and _date(v.get("est_deadline")):
        return f"Expected deadline <b>~{_fmt_date(_date(v['est_deadline']))}</b><span class=\"dlnote\">estimate, call not yet published</span>"
    return "Deadline <b>see official call</b>"


KF_CSS = """
  /* schede a «key facts» (bandi e posizioni): come la slide dei post, etichetta a colore e valore bianco */
  .kf h4 { font-size: 18px; margin: 0 0 8px; line-height: 1.3; }
  .kf .aim { color: var(--soft); font-size: 15px; line-height: 1.5; margin: 0 0 14px; }
  .kf .funder, .kf .inst { color: var(--soft); font-size: 13px; font-weight: 600; margin-bottom: 6px; }
  .facts { display: grid; grid-template-columns: 158px 1fr; margin: 0 0 16px; font-size: 14.5px; line-height: 1.45; }
  .facts dt, .facts dd { margin: 0; padding: 9px 0; border-top: 1px solid #2A2A2A; }
  .facts dt { color: var(--accent); font-size: 11.5px; font-weight: 800; letter-spacing: .07em; text-transform: uppercase;
              padding-top: 11px; padding-right: 12px; }
  .facts dd { color: var(--text); overflow-wrap: anywhere; }
  .facts dd b { font-size: 16px; font-weight: 800; }
  .kf .btns { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-start; }
  .kf a.btn, .call.other a.btn { background: var(--accent); color: #0A0A0A; }
  .kf a.btn.ghost, .call.other a.btn.ghost { background: transparent; color: var(--text); border: 2px solid var(--accent); }
  .kf .partners { margin-top: -4px; }
  .kf .report { display: block; width: max-content; margin-top: 12px; }
  @media (max-width: 520px) {
    .facts { grid-template-columns: 1fr; }
    .facts dd { border-top: 0; padding-top: 0; }
  }
"""


BAD_SUMMARY = re.compile(r"official text|cannot be (?:verified|confirmed)|binary|unparsed|not (?:provided|available) in the",
                         re.I)


def brief(text, limit=200):
    """Una frase sola (la prima), al massimo `limit` caratteri tagliati a parola intera: le schede del sito
    mostrano informazioni chiave, non paragrafi."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return ""
    m = re.match(r"(.+?[.!?])(?:\s+[A-Z(]|$)", text)
    first = m.group(1) if m else text
    if len(first) > limit:
        first = first[:limit].rsplit(" ", 1)[0].rstrip(",;:–-") + "…"
    return first


def call_facts(g, v, d, today):
    """Dati chiave di un bando per la scheda del sito, come la slide «Key facts» dei post: (etichetta, valore html)."""
    from html import escape
    facts = []
    if d:
        label = deadline_text(v, d)[0] if checked(v) else "Deadline"
        facts.append((label, f"<b>{_fmt_date(d)}</b>"))
    elif v.get("deadline_type") == "rolling":
        facts.append(("Deadline", "<b>Rolling, no fixed date</b>"))
    elif v.get("forecast") and _date(v.get("est_deadline")) and _date(v.get("est_deadline")) >= today:
        facts.append(("Expected deadline", f"<b>~{_fmt_date(_date(v['est_deadline']))}</b> (estimate)"))
    elif v.get("forecast"):
        facts.append(("Deadline", "<b>To be announced</b>"))           # stima superata, call non ancora uscita
    else:
        facts.append(("Deadline", "<b>See the official call</b>"))
    later = later_dues(v, d) if (d and checked(v)) else []
    if later:
        facts.append(("Later deadlines", " · ".join(_fmt_date(x) for x in later[:3])))
    resub = [x for x in (_date(y) for y in v.get("resubmission_dates") or []) if x and x >= today]
    if resub:
        facts.append(("Resubmissions", f"next {_fmt_date(resub[0])}"))
    loi = _date(v.get("loi_deadline"))
    if loi and loi >= today:
        facts.append(("Letter of intent", _fmt_date(loi) + (" (required)" if v.get("loi_required") == "yes" else "")))
    money = _money(g.get("budget_progetto"), g.get("valuta"))
    if money:
        facts.append(("Budget per project", escape(money)))
    elif _money(g.get("budget_totale"), g.get("valuta")):
        facts.append(("Total budget", escape(_money(g.get("budget_totale"), g.get("valuta")))))
    if v:
        facts.append(("Eligible countries", escape(brief(v.get("eligible_countries") or "Check the official call", 160))))
    if v.get("lead"):
        facts.append(("Who can lead", escape(brief(v["lead"], 170))))
    status = ("Being checked against the official call" if not v else
              "Forecast: the call is not published yet" if v.get("forecast") else
              "Opening soon" if v.get("coming_soon") else
              "Dates being checked" if not checked(v) else "")
    if status:
        facts.append(("Status", escape(status)))
    return facts


def facts_html(facts):
    return ('<dl class="facts">' + "".join(f"<dt>{k}</dt><dd>{val}</dd>" for k, val in facts) + "</dl>")


OFFICIAL_BTN = ('<a class="btn" href="{url}" target="_blank" rel="noopener" '
                'title="Opens the funder\'s official call page in a new tab">Read the official call &#8599;</a>')


def more_dates(v, d, today):
    """Scadenze successive, risottomissioni, lettera d'intenti e fine della call."""
    more = []
    later = later_dues(v, d) if checked(v) else []
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
    return more


def call_path(g, v):
    """Percorso della pagina propria di un bando verificato (es. «call/horizon-health-…-3fa9c1»), stabile per id."""
    import hashlib
    title = v.get("title") or g.get("titolo") or "funding call"
    words = re.sub(r"[^a-z0-9]+", "-", unescape(title).lower()).strip("-")[:60].rstrip("-") or "funding-call"
    return f"call/{words}-{hashlib.sha1(str(g['id']).encode()).hexdigest()[:6]}"


def call_jsonld(g, v, cfg, path, title, summary):
    """Dati strutturati: percorso di navigazione (BreadcrumbList, letto da Google) e bando (MonetaryGrant, schema.org)."""
    funder = funder_line(g) or v.get("programme") or ""
    crumbs = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": cfg["brand_name"], "item": site_url(cfg, "")},
        {"@type": "ListItem", "position": 2, "name": "Funding calls", "item": site_url(cfg, "calls")},
        {"@type": "ListItem", "position": 3, "name": title}]}
    grant = {"@context": "https://schema.org", "@type": "MonetaryGrant", "name": title, "url": site_url(cfg, path),
             "sameAs": g["url"]}
    if summary:
        grant["description"] = summary
    if funder:
        grant["funder"] = {"@type": "Organization", "name": funder}
    text = json.dumps([crumbs, grant], ensure_ascii=False, indent=1).replace("</", "<\\/")
    return f'<script type="application/ld+json">\n{text}\n</script>'


CALL_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_tag}</title>
<meta name="description" content="{description}">
{og}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
{jsonld}
<style>
  :root {{ --bg: {bg}; --card: #15304A; --text: #FFFFFF; --muted: {muted}; --soft: {soft}; --accent: {accent}; --teal: {teal}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text); font-family: Inter, system-ui, sans-serif; line-height: 1.5; }}
  .bar {{ height: 6px; background: var(--accent); }}
  main {{ max-width: 680px; margin: 0 auto; padding: 28px 16px 48px; }}
  .switch {{ display: inline-block; color: var(--text); text-decoration: none; font-size: 14px; font-weight: 600;
            border: 1px solid var(--muted); border-radius: 999px; padding: 7px 14px; margin: 0 6px 18px 0; }}
  .badge {{ display: inline-block; background: var(--accent); color: var(--bg); font-weight: 800; font-size: 13px;
           letter-spacing: .06em; padding: 6px 14px; border-radius: 999px; text-transform: uppercase; }}
  .badge.it {{ background: var(--teal); margin-left: 6px; }}
  h1 {{ font-size: 28px; font-weight: 800; margin: 14px 0 8px; line-height: 1.2; overflow-wrap: anywhere; }}
  .inst {{ color: var(--soft); font-size: 15px; font-weight: 600; margin: 0 0 20px; }}
  .call {{ background: var(--card); border-radius: 18px; padding: 20px; border-left: 4px solid var(--accent); }}
  dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; margin: 0 0 16px; font-size: 15px; }}
  dt {{ color: var(--muted); font-weight: 600; }}
  dd {{ margin: 0; overflow-wrap: anywhere; }}
  .summary {{ color: var(--soft); font-size: 15px; margin: 0 0 18px; }}
  .soon {{ color: var(--accent); font-weight: 800; font-size: 12px; margin-left: 6px; }}
  .dlnote {{ display: block; color: var(--muted); font-size: 13px; }}
  .dates {{ color: var(--soft); font-size: 14px; margin: 0 0 16px; }}
  blockquote {{ font-size: 14px; color: var(--soft); border-left: 2px solid var(--muted); padding-left: 12px; margin: 0 0 18px; font-style: italic; }}
  .btns {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  a.btn {{ background: var(--accent); color: var(--bg); text-decoration: none; font-weight: 800; font-size: 15px;
           padding: 11px 18px; border-radius: 12px; }}
  a.btn.ghost {{ background: transparent; color: var(--text); border: 1px solid var(--muted); }}
  a.btn:focus-visible, .switch:focus-visible {{ outline: 3px solid var(--text); outline-offset: 2px; }}
  footer {{ color: var(--muted); font-size: 13px; margin-top: 30px; }}
  footer a {{ color: var(--teal); }}
  @media (max-width: 480px) {{ dl {{ grid-template-columns: 1fr; gap: 2px; }} dd {{ margin-bottom: 8px; }} h1 {{ font-size: 24px; }} }}
</style>
</head>
<body>
<div class="bar"></div>
<main>
  <a class="switch" href="../calls.html#{anchor}">&larr; All funding calls</a><a class="switch" href="../positions.html">Academic positions &rarr;</a><a class="switch" href="../methodology.html">Design, Reporting &amp; Appraisal &rarr;</a><a class="switch" href="../science.html">Latest Science &rarr;</a><br>
  <span class="badge">Funding call</span>{italy_badge}
  <h1>{title}</h1>
  <p class="inst">{funder}</p>
  <article class="call">
    <dl>
      <dt>Programme</dt><dd>{programme}</dd>
      <dt>Eligible countries</dt><dd>{countries}</dd>
      <dt>Open to Italy</dt><dd>{italy}</dd>
      {lead}<dt>Deadline</dt><dd>{when}</dd>
    </dl>
    {dates}
    {summary}
    {proof}
    <div class="btns">{share}{cal}{find}<a class="btn" href="{url}" target="_blank" rel="noopener" title="Opens the funder's official call page in a new tab">Read the official call &#8599;</a></div>
  </article>
  <footer>
    Checked automatically against the official call text on {checked}: always read the full call before applying;
    the funder's page is the only official source. <a href="../feedback.html?topic=Report%20an%20error&amp;ref={anchor}">Report an error</a><br>
    <a href="../index.html">{brand}</a> · <a href="https://www.instagram.com/{ig}/">{handle} on Instagram</a>
  </footer>
</main>
</body>
</html>
"""


def call_pages(grants_list, verified, cfg, today=None):
    """{percorso del file: html} con una pagina per ogni bando verificato in pagina (es. «call/….html»)."""
    from html import escape
    today = today or date.today()
    c = site_palette(cfg)
    italy_words = {"yes": "Yes, organisations based in Italy are eligible", "no": "No",
                   "unclear": "Not stated in the official text: check the call"}
    out = {}
    for g, v, d in page_entries(grants_list, verified, today):
        if not v:
            continue
        path = call_path(g, v)
        title = v.get("title") or g.get("titolo") or "Funding call"
        programme = v.get("programme") or programme_detail(g)
        summary = v.get("summary") or ""
        funder = funder_line(g) or programme
        dl = f", deadline {_fmt_date(d)}" if d else ""
        it = " Open to Italian institutions." if v.get("italy") == "yes" else ""
        base = f"{programme}: {summary}" if summary else f"Funding call from {funder}{dl}."
        desc = base if len(base) <= 150 - len(it) else base[:150 - len(it)].rsplit(" ", 1)[0] + "…"
        desc += it
        ev = v.get("countries_evidence") or v.get("italy_evidence")
        ps = partner_search(g)
        more = more_dates(v, d, today)
        out[path + ".html"] = CALL_PAGE.format(
            title_tag=escape(f"{title} – funding call{dl} · {cfg['brand_name']}"), description=escape(desc, quote=True),
            og=og_tags(cfg, f"Funding call: {title}", desc, path), jsonld=call_jsonld(g, v, cfg, path, title, summary),
            bg=c["background"], muted=c["muted"], soft=c["muted_text"], teal=c["accent"], accent=site_accent(cfg, "grant"),
            anchor=card_anchor(g["id"]), title=escape(title), funder=escape(funder),
            italy_badge='<span class="badge it">Open to Italy</span>' if v.get("italy") == "yes" else "",
            programme=escape(programme), countries=escape(v.get("eligible_countries") or "check the call"),
            italy=escape(italy_words.get(v.get("italy"), italy_words["unclear"])),
            lead=f'<dt>Who can lead</dt><dd>{escape(v["lead"])}</dd>\n      ' if v.get("lead") else "",
            when=when_html(v, d, today).removeprefix("Deadline "), dates=f'<p class="dates">{escape(" · ".join(more))}</p>' if more else "",
            summary=f'<p class="summary">{escape(summary)}</p>' if summary else "",
            proof=f'<blockquote>From the official call: &ldquo;{escape(ev)}&rdquo;</blockquote>' if ev else "",
            share=share_button(site_url(cfg, path), f"Funding call: {title}" + (f" (deadline {_fmt_date(d)})" if d else "")),
            cal=calendar_button(d, title, g["url"], programme or ""),
            find=(f'<a class="btn ghost" href="{escape(ps[0], quote=True)}" target="_blank" rel="noopener">Find partners</a>'
                  if ps else ""),
            url=escape(g["url"], quote=True), checked=_fmt_date(_date(v.get("checked")) or today),
            brand=escape(cfg["brand_name"]), ig=cfg["handle"].lstrip("@"), handle=escape(cfg["handle"]))
    return out


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
        ps = partner_search(g)
        partners = (f'<p class="partners">Looking for consortium partners? Search topic <code>{escape(ps[1])}</code> in the '
                    f'EU partner search, or see &ldquo;Partner search announcements&rdquo; on the call page.</p>') if ps else ""
        find = (f'<a class="btn ghost" href="{escape(ps[0], quote=True)}" target="_blank" rel="noopener">Find partners</a>'
                if ps else "")
        summary = v.get("summary") or ""
        aim = "" if (not summary or BAD_SUMMARY.search(summary)) else brief(summary, 220)
        title = v.get("title") or g.get("titolo") or ""
        own = call_path(g, v) if v else ""       # pagina propria (solo bandi verificati)
        share = share_button(site_url(cfg, own or "calls#" + card_anchor(g["id"])),
                             f"Funding call: {title}" + (f" (deadline {_fmt_date(d)})" if d else ""))
        h4 = f'<a href="{own}.html">{escape(title)}</a>' if own else escape(title)
        words = " ".join(x for x in (title, v.get("programme"), programme_detail(g), v.get("summary"),
                                     v.get("eligible_countries"), g.get("ente"), g.get("titolo")) if x).lower()
        attrs = (f'data-region="{escape(region(g, v, cfg), quote=True)}" data-italy="{"yes" if v.get("italy") == "yes" else "no"}" '
                 f'data-deadline="{d.isoformat() if d else ""}" data-area="{" ".join(areas(g))}" '
                 f'data-text="{escape(words, quote=True)}"')
        return f"""    <article class="call kf" id="{card_anchor(g["id"])}" {attrs}>
      <div class="funder">{escape(v.get("programme") or programme_detail(g))}</div>
      <h4>{h4}</h4>
      {f'<p class="aim">{escape(aim)}</p>' if aim else ""}
      {facts_html(call_facts(g, v, d, today))}
      {partners}
      <div class="btns">{share}{calendar_button(d, title, g["url"], v.get("programme") or "")}{find}{OFFICIAL_BTN.format(url=escape(g["url"], quote=True))}</div>
      <a class="report" href="feedback.html?topic=Report%20an%20error&amp;ref={card_anchor(g["id"])}">Report an error</a>
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
    c = site_palette(cfg)
    desc = (f"{len(entries)} open research grants and funding calls for clinical research, rehabilitation, clinical "
            f"engineering and health research, {len(italy)} open to Italian institutions. Checked on the official call text, updated daily.")
    return PAGE.format(brand=escape(cfg["brand_name"]), handle=escape(cfg["handle"]), ig=cfg["handle"].lstrip("@"),
                       bg=c["background"], muted=c["muted"], soft=c["muted_text"], teal=c["accent"],
                       accent=site_accent(cfg, "grant"), nav="".join(nav), description=escape(desc, quote=True),
                       lockup=page_lockup(cfg, "grant"),
                       italy=italy_html, other=other_html, updated=_fmt_date(today), filters=filters_form(entries),
                       og=og_tags(cfg, f"Open research funding calls · {cfg['brand_name']}", desc, "calls")
                       ).replace("</style>", KF_CSS + "</style>", 1)


# ---------------------------------------------------------------- pagina iniziale (link in bio)
HOME = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{brand} – Funding calls &amp; academic positions in clinical research</title>
<meta name="google-site-verification" content="CmqA15pmnid3j9D4hdy5u6P45Dly32YcaeAil7P-6tM">
<meta name="description" content="Open research funding calls and academic positions in clinical research, clinical engineering and rehabilitation, checked on the official texts.">
{og}
<link rel="alternate" type="application/rss+xml" title="Open funding calls" href="feed-calls.xml">
<link rel="alternate" type="application/rss+xml" title="Academic positions" href="feed-positions.xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
  :root {{ --bg: {bg}; --paper: #F3F6F9; --card: #15304A; --text: #FFFFFF; --soft: {soft}; --muted: {muted};
           --teal: {teal}; --amber: {amber}; --lilac: {lilac}; --sci: {sci}; --meth: {meth}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; min-height: 100vh; background: var(--bg); color: var(--text); font-family: Inter, system-ui, sans-serif; line-height: 1.45; }}
  .top {{ background: var(--bg); padding: 34px 16px 36px; text-align: center; border-top: 4px solid var(--teal); }}
  .top img {{ width: 340px; max-width: 100%; height: auto; display: block; margin: 0 auto 14px; }}
  .top p {{ color: var(--text); margin: 0 auto; max-width: 460px; font: 600 17px/1.45 Inter, system-ui, sans-serif; }}
  .pills {{ display: flex; flex-direction: column; align-items: center; gap: 17px; margin: 0 auto 22px; max-width: 520px; }}
  .pills a {{ display: flex; flex-direction: column; align-items: center; gap: 7px; text-decoration: none; }}
  .pills .tag {{ background: var(--c); color: var(--on); border-radius: 999px; padding: 9px 17px; letter-spacing: .045em;
                font: 800 12.5px/1 Inter, system-ui, sans-serif; }}
  .pills .met {{ color: var(--soft); font-size: 14px; line-height: 1.35; }}
  .pills a:hover .tag, .pills a:focus-visible .tag {{ filter: brightness(1.08); }}
  .pills a:hover .met {{ color: var(--text); }}
  main {{ max-width: 520px; margin: 0 auto; padding: 0 16px 40px; display: grid; gap: 16px; }}
  .social {{ display: flex; justify-content: center; gap: 10px; margin-top: 0; flex-wrap: wrap; }}
  .noig a {{ color: var(--teal); font-weight: 600; }}
  .noig {{ color: var(--soft); font-size: 14px; text-align: center; max-width: 440px; margin: 16px auto 0; line-height: 1.5; }}
  .social a {{ color: var(--soft); text-decoration: none; font-weight: 600; font-size: 14px; border: 1px solid var(--muted);
              border-radius: 999px; padding: 8px 14px; display: inline-flex; align-items: center; gap: 8px; }}
  .social a svg {{ width: 18px; height: 18px; flex: none; }}
  .social a:hover {{ color: #FFFFFF; border-color: var(--soft); }}
  footer {{ color: var(--muted); font-size: 12px; text-align: center; padding: 0 16px 30px; max-width: 520px; margin: 0 auto; }}
</style>
</head>
<body>
<header class="top">
  {logo_block}
  <nav class="pills" aria-label="Sections">{pills}</nav>
  <p>Pieces of clinical research. In one place.</p>
</header>
<main>
  <div class="social">
{social}
  </div>
  <p class="noig">No Instagram account? You don't need one: every call, position and methodology carousel is on this site.
  Bookmark it or add it to your home screen, and share any card with the Share button.</p>
  <p class="noig"><a href="feedback.html">Feedback, a call to suggest or an error to report? Write to us</a></p>
</main>
<footer>Educational content for researchers and health professionals; not medical advice. Always check eligibility and deadlines in the official call or advertisement. Updated {updated}.</footer>
</body>
</html>
"""


# simbolo definitivo per l'intestazione della home (fondo chiaro): (colore, vertici) nel viewBox 26 26 148 148

HEADER_LOGO = """<{tag} class="crc-logo crc-o" {attrs}>
<img class="crc-word" src="{word}" alt="" width="1142" height="360">
<svg class="crc-sym" viewBox="26 26 148 148" aria-hidden="true"><defs>{defs}</defs>{glow}{cubes}</svg>
</{tag}>
<style>
  /* il simbolo è la «o» di «Chaos»: stesso centro e stessa misura della «o» disegnata */
  .crc-o {{ position: relative; display: block; width: max-content; max-width: 100%; text-decoration: none; }}
  .crc-o .crc-word {{ height: {height}; width: auto; max-width: 100%; display: block; margin: 0; }}
  .crc-o .crc-sym {{ position: absolute; overflow: visible; left: {left:.3f}%; top: {top:.3f}%; width: {size:.3f}%;
                    aspect-ratio: 1; height: auto; }}
  .top .crc-o {{ margin: 6px auto 36px; }}
</style>
<script>
/* col puntatore sul logo (solo lì) il simbolo si scompone in frammenti che seguono linee di campo, si
   ricompongono nella «o» verde e restano in orbita lungo l'anello finché il puntatore non se ne va */
(function () {{
  var svg = document.querySelector(".crc-sym"), box = document.querySelector(".crc-logo");
  if (!svg || !box || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  var RING = {ring}, PER = RING[0].length, ROWS = RING.length;
  function rgb(h) {{ return [parseInt(h.substr(1, 2), 16), parseInt(h.substr(3, 2), 16), parseInt(h.substr(5, 2), 16)]; }}
  function spline(a, f) {{                                 /* Catmull-Rom: il percorso non fa spigoli */
    var i = Math.floor(f), t = f - i, k = function (d) {{ return a[((((i + d) % PER) + PER) % PER)]; }};
    var p0 = k(-1), p1 = k(0), p2 = k(1), p3 = k(2), t2 = t * t, t3 = t2 * t, out = [0, 0];
    for (var c = 0; c < 2; c++) {{
      out[c] = 0.5 * (2 * p1[c] + (-p0[c] + p2[c]) * t + (2 * p0[c] - 5 * p1[c] + 4 * p2[c] - p3[c]) * t2 +
                      (-p0[c] + 3 * p1[c] - 3 * p2[c] + p3[c]) * t3);
    }}
    return out;
  }}
  function at(rowF, f) {{                                  /* morbido anche fra un giro e l'altro */
    var r0 = Math.max(0, Math.min(ROWS - 1, Math.floor(rowF))), r1 = Math.min(ROWS - 1, r0 + 1), rt = rowF - r0;
    var p = spline(RING[r0], f), q = spline(RING[r1], f);
    return [p[0] + (q[0] - p[0]) * rt, p[1] + (q[1] - p[1]) * rt];
  }}
  var halo = svg.querySelectorAll(".crc-glow");
  var frags = [].map.call(svg.querySelectorAll("#crcFrags > g"), function (g, i) {{
    var p = g.firstChild, row = +g.dataset.row, w = +p.getAttribute("width"), h = +p.getAttribute("height");
    var j = ((i * 2654435761) % 1000) / 1000;             /* un numero suo, stabile: niente moto all'unisono */
    return {{ g: g, p: p, x: +g.dataset.x, y: +g.dataset.y, row: row, i0: +g.dataset.i,
             bx: +g.dataset.cx, by: +g.dataset.cy, a: rgb(p.getAttribute("fill")), b: rgb(g.dataset.c1),
             spd: 52 + 10 * row + 14 * j,                 /* ognuno la sua andatura: la corsa non è meccanica */
             w1: 0.9 + 2.6 * j, w2: 0.37 + 0.7 * j, w3: 1.7 + 3.1 * j,
             ph1: 6.3 * j, ph2: 4.1 * j + row, ph3: 2.2 * j + row,
             tail: 1 - 0.17 * row, rmax: Math.min(w, h) * 0.5, lag: 0.72 + 0.28 * j, shown: -1, dim: -1 }};
  }});
  var near = 0, target = 0, phase = 0, last = performance.now(), running = false;
  function wake() {{ if (!running) {{ running = true; last = performance.now(); requestAnimationFrame(step); }} }}
  function step(t) {{
    var dt = Math.min(0.05, (t - last) / 1000); last = t;
    near += (target - near) * Math.min(1, dt * (target > near ? 3.4 : 7));   /* fluisce piano, si ricompone svelto */
    phase += dt * near;                                     /* l'orbita gira solo mentre il flusso è acceso */
    var still = near < 0.004 && target === 0;
    var lum = near * near;                                  /* la luce sale più tardi del moto: prima si sfalda, poi si accende */
    for (var k = 0; k < halo.length; k++) {{
      halo[k].style.display = lum < 0.01 ? "none" : "";      /* a riposo il filtro non costa nulla */
      halo[k].setAttribute("opacity", (lum * (k ? 0.95 : 0.75)).toFixed(2));
    }}
    for (var i = 0; i < frags.length; i++) {{
      var f = frags[i], e = Math.max(0, Math.min(1, (near - (1 - f.lag) * 0.45) / f.lag));
      e = e * e * (3 - 2 * e);                              /* partenza e arrivo morbidi */
      var idx = f.i0 + phase * f.spd + 1.6 * Math.sin(phase * f.w1 * 0.5 + f.ph1)  /* avanza a ondate larghe, non a passo fisso */
                + 0.6 * Math.sin(phase * f.w3 * 0.3 + f.ph3);                      /* due onde lente e sfasate: traiettoria mai uguale */
      var rowF = f.row + 0.35 * Math.sin(phase * f.w2 * 0.55 + f.ph2)               /* e intanto va e viene fra i giri */
                 + 0.1 * Math.sin(phase * f.w3 * 0.22 + f.ph1);
      var pos = at(rowF, idx), u = 1 - e;
      var px = u * u * f.x + 2 * u * e * f.bx + e * e * pos[0];    /* curva quadratica: la linea di campo */
      var py = u * u * f.y + 2 * u * e * f.by + e * e * pos[1];
      var nx = at(rowF, idx + 0.5);                                /* tangente: il frammento si stira nel verso del moto */
      var ang = Math.atan2(nx[1] - pos[1], nx[0] - pos[0]) * 180 / Math.PI;
      var dep = Math.max(-1, Math.min(1, (pos[1] - 100) / 70));    /* 3D: sotto è il davanti, sopra il dietro */
      var s = (1 - 0.34 * e) * (1 + 0.3 * dep * e);
      var sx = s * (1 + 1.5 * f.tail * e), sy = s * (1 - 0.25 * e);   /* scie lunghe fuori, corte dentro: una scia
                                                                         tangente al giro interno lo squadrerebbe */
      f.g.setAttribute("transform", "translate(" + (px - f.x).toFixed(2) + " " + (py - f.y).toFixed(2) + ") " +
                       "translate(" + f.x + " " + f.y + ") rotate(" + ang.toFixed(1) + ") scale(" + sx.toFixed(3) + " " +
                       sy.toFixed(3) + ") rotate(" + (-ang).toFixed(1) + ") translate(" + (-f.x) + " " + (-f.y) + ")");
      var q = Math.round(e * 10);                           /* colore e raggio a scatti impercettibili: meno lavoro */
      if (q !== f.shown) {{
        f.shown = q;
        var k = q / 10;
        f.p.setAttribute("fill", "rgb(" + Math.round(f.a[0] + (f.b[0] - f.a[0]) * k) + "," +
                         Math.round(f.a[1] + (f.b[1] - f.a[1]) * k) + "," +
                         Math.round(f.a[2] + (f.b[2] - f.a[2]) * k) + ")");
        f.p.setAttribute("rx", (f.rmax * k).toFixed(2));    /* da spigoli vivi a capsule: code senza angoli */
      }}
      var d2 = Math.round((0.6 + 0.4 * (dep + 1) / 2) * e * 12);   /* dietro più velato, davanti pieno */
      if (d2 !== f.dim) {{ f.dim = d2; f.g.setAttribute("opacity", (1 - e + d2 / 12).toFixed(2)); }}
    }}
    if (still) {{
      frags.forEach(function (f) {{ f.g.removeAttribute("transform"); f.g.removeAttribute("opacity"); }});
      running = false; return;
    }}
    requestAnimationFrame(step);
  }}
  box.addEventListener("pointerenter", function () {{ target = 1; wake(); }});
  box.addEventListener("pointerleave", function () {{ target = 0; wake(); }});
  window.addEventListener("blur", function () {{ target = 0; wake(); }});
}})();
</script>"""


def _in_poly(x, y, pts):
    inside, j = False, len(pts) - 1
    for i, (xi, yi) in enumerate(pts):
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _fragments():
    """Il simbolo spezzato in tanti pezzi rettangolari irregolari: i tagli cadono a caso (seme fisso, così
    l'HTML non cambia a ogni build) e i pezzi si sovrappongono di un filo, perché a riposo non si veda
    nessuna cucitura fra l'uno e l'altro: il simbolo fermo resta il logo di sempre. Anche i cubetti a elle
    vengono decomposti, così ogni pezzo è un rettangolo e può arrotondarsi mentre scorre."""
    import logo as logo_v3
    out, seed = [], 7

    def rnd(lo, hi):                                # generatore ripetibile: stesso HTML a ogni build
        nonlocal seed
        seed = (seed * 1103515245 + 12345) % 2147483648
        return lo + (hi - lo) * (seed / 2147483648)

    def cuts(a, b, n):                              # n tagli scentrati a caso fra a e b
        return [a] + [a + (b - a) * ((k + 1) / (n + 1) + rnd(-0.12, 0.12)) for k in range(n)] + [b]

    import math
    o = 1.2                                         # sovrapposizione fra pezzi vicini: niente righine. Può
                                                    # essere generosa: i pezzi crescono solo l'uno dentro
                                                    # l'altro, quindi la sagoma del cubetto non cambia di un pelo
    for role, pts in logo_v3.SYMBOL:
        if any(abs(a[0] - b[0]) > 0.01 and abs(a[1] - b[1]) > 0.01
               for a, b in zip(pts, pts[1:] + pts[:1])):   # cubetto inclinato: resta storto com'è nel logo,
            cx = sum(p[0] for p in pts) / len(pts)         # raddrizzarlo darebbe al simbolo un'aria a reticolo
            cy = sum(p[1] for p in pts) / len(pts)
            dx, dy = pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]
            side = math.hypot(dx, dy)
            out.append((role, cx - side / 2, cy - side / 2, side, side, math.degrees(math.atan2(dy, dx))))
            continue
        xs, ys = sorted({p[0] for p in pts}), sorted({p[1] for p in pts})
        if len(xs) == 2 and len(ys) == 2:           # cubetto pieno: lo spezzo secondo quanto è grande
            w = xs[1] - xs[0]
            nx, ny = ((2, 1) if rnd(0, 1) < 0.5 else (1, 2)) if w >= 15 else ((1, 0) if rnd(0, 1) < 0.5 else (0, 1)) if w >= 8.5 else (0, 0)
            gx, gy = cuts(xs[0], xs[1], nx), cuts(ys[0], ys[1], ny)
        else:                                       # cubetto a elle o a croce: lo divido dove si piega
            gx, gy = xs, ys
        inside = {(i, j): _in_poly((gx[i] + gx[i + 1]) / 2, (gy[j] + gy[j + 1]) / 2, pts)
                  for i in range(len(gx) - 1) for j in range(len(gy) - 1)}
        for (i, j), yes in inside.items():
            if not yes:
                continue                            # il pezzo si allarga solo verso un altro pezzo, mai verso
            a = o if inside.get((i - 1, j)) else 0   # fuori: così il bordo del cubetto resta quello di sempre
            b = o if inside.get((i, j - 1)) else 0
            c = o if inside.get((i + 1, j)) else 0
            d = o if inside.get((i, j + 1)) else 0
            out.append((role, gx[i] - a, gy[j] - b, gx[i + 1] - gx[i] + a + c, gy[j + 1] - gy[j] + b + d, 0.0))
    return out


WORD_O = {"home": "wordmark-o-home.png", "grant": "wordmark-o-calls.png", "positions": "wordmark-o-positions.png",
          "methods": "wordmark-o-methods.png", "science": "wordmark-o-science.png"}
O_CENTER = (736.5, 250.5)   # centro delle minuscole fra «a» e «s» nella scritta 1142×360 (logo.wordmark_blank_o)
O_SIDE = 157.0              # lato del simbolo: alto quanto le minuscole (più un filo), come una «o» vera


def header_logo(cfg, accent=None, ink="#FFFFFF", kind="home", href=None, height="clamp(56px, 24vw, 104px)"):
    """Logo dell'intestazione della home: con «site_v4» il simbolo definitivo in SVG (cubetti animati) e la scritta;
    altrimenti l'immagine di prima. Su fondo scuro i cubetti principali sono bianchi e quelli d'accento nel colore
    indicato (verde del sito per la home, colore della rubrica per le pagine di sezione)."""
    from html import escape
    import logo as logo_v3
    brand = escape(cfg["brand_name"], quote=True)
    if not cfg.get("site_v4"):
        return f'<img src="logo-horizontal.png" alt="{brand}" width="340" height="128">'
    import json
    import math
    acc = accent or SITE_GREEN
    deep = logo_v3.deep_of(acc)
    cols = {"ink": ink, "teal": acc, "deep": deep}

    def lighten(hexa, k):                               # verso il bianco: il nucleo acceso del tubo luminoso
        r, g, b = (int(hexa.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        return "#%02x%02x%02x" % tuple(round(v + (255 - v) * k) for v in (r, g, b))

    core, core_in = lighten(acc, 0.68), lighten(acc, 0.42)
    frags = _fragments()
    centres = [(x + w / 2, y + h / 2) for _, x, y, w, h, _r in frags]
    per, rows = 96, 4                                   # l'orbita: 4 giri concentrici da 96 posizioni
    ring = logo_v3.ring_rows(per, rows, scale=1.32, roundness=1, oval=0.14)
    mx = sum(p[0] for r in ring for p in r) / (per * rows)       # anello centrato sul simbolo: la «o» gira al
    my = sum(p[1] for r in ring for p in r) / (per * rows)       # centro delle minuscole, non di sbieco
    ring = [[(x - mx + 100, y - my + 100) for x, y in r] for r in ring]   # cerchio pieno poi stirato: ovale senza un angolo
    ang = lambda p: math.atan2(p[1] - 100, p[0] - 100)
    order = sorted(range(len(frags)), key=lambda i: ang(centres[i]))      # per angolo: i frammenti non si incrociano
    step = per / max(1, -(-len(frags) // rows))
    cubes = [""] * len(frags)
    for slot, i in enumerate(order):
        (role, x, y, w, h, rot), (cx, cy) = frags[i], centres[i]
        row, idx = slot % rows, (slot // rows) * step
        tx, ty = ring[row][int(idx) % per]
        bend = 0.55 * math.hypot(tx - cx, ty - cy) * math.cos(ang((tx, ty)))   # linea di campo: piega al contrario sui due lati
        mx, my = (cx + tx) / 2, (cy + ty) / 2
        nx, ny = -(ty - cy), (tx - cx)
        nrm = math.hypot(nx, ny) or 1
        cubes[i] = (f'<g data-x="{cx:.1f}" data-y="{cy:.1f}" data-row="{row}" data-i="{idx:.2f}" '
                    f'data-cx="{mx + nx / nrm * bend:.1f}" data-cy="{my + ny / nrm * bend:.1f}" '
                    f'data-c1="{core_in if row >= rows - 2 else core}">'  # nucleo acceso, quasi bianco; il verde sta nell'alone
                    f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="0" fill="{cols[role]}"'
                    + (f' transform="rotate({rot:.1f} {cx:.2f} {cy:.2f})"' if rot else "") + "/></g>")
    # luminescenza: due aloni verdi sfocati dietro i frammenti (una copia sola, non il doppio dei nodi)
    defs = (f'<filter id="crcGlowA" x="-45%" y="-45%" width="190%" height="190%">'
            f'<feGaussianBlur in="SourceAlpha" stdDeviation="2.4" result="b"/>'
            f'<feFlood flood-color="{acc}" flood-opacity="0.95"/><feComposite in2="b" operator="in"/></filter>'
            f'<filter id="crcGlowB" x="-70%" y="-70%" width="240%" height="240%">'
            f'<feGaussianBlur in="SourceAlpha" stdDeviation="6.5" result="b"/>'
            f'<feFlood flood-color="{acc}" flood-opacity="0.8"/><feComposite in2="b" operator="in"/></filter>')
    glow = ('<use class="crc-glow" href="#crcFrags" filter="url(#crcGlowB)" opacity="0" style="display:none"/>'
            '<use class="crc-glow" href="#crcFrags" filter="url(#crcGlowA)" opacity="0" style="display:none"/>')
    ring_js = json.dumps([[[round(x, 1), round(y, 1)] for x, y in r] for r in ring], separators=(",", ":"))
    (cx0, cy0), side = O_CENTER, O_SIDE
    attrs = (f'href="{href}" aria-label="{brand}, home"' if href else f'role="img" aria-label="{brand}"')
    return HEADER_LOGO.format(brand=brand, cubes=f'<g id="crcFrags">{"".join(cubes)}</g>',
                              defs=defs, glow=glow, ring=ring_js, word=WORD_O[kind], tag="a" if href else "div",
                              attrs=attrs, height=height, left=(cx0 - side / 2) / 1142 * 100,
                              top=(cy0 - side / 2) / 360 * 100, size=side / 1142 * 100)


ICONS_DIR = __import__("pathlib").Path(__file__).resolve().parent / "icons"


def icon(name):
    """Icona SVG in linea (Simple Icons, CC0): prende il colore del testo."""
    try:
        return (ICONS_DIR / f"{name}.svg").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def social_links(cfg):
    """Pulsanti dei profili: Bluesky e Threads compaiono quando il loro indirizzo è in config.json."""
    ig = cfg["handle"].lstrip("@")
    links = [("instagram", "Instagram", f"https://www.instagram.com/{ig}/"),
             ("facebook", "Facebook", f"https://www.facebook.com/{ig}")]
    if cfg.get("bluesky_handle"):
        links.append(("bluesky", "Bluesky", f"https://bsky.app/profile/{cfg['bluesky_handle'].lstrip('@')}"))
    if cfg.get("threads_handle"):
        links.append(("threads", "Threads", f"https://www.threads.com/@{cfg['threads_handle'].lstrip('@')}"))
    if cfg.get("linkedin_url"):
        links.append(("linkedin", "LinkedIn", cfg["linkedin_url"]))
    links.append(("rss", "RSS", "rss.html"))            # pagina che spiega come iscriversi (il feed grezzo è XML)
    return "\n".join(f'    <a href="{url}" rel="me">{icon(name)}<span>{label}</span></a>' for name, label, url in links)


def build_home(n_calls, n_italy, n_positions, cfg, today=None, n_methods=0, n_science=0):
    from html import escape
    today = today or date.today()
    c = site_palette(cfg)
    metrics = {       # la metrica di ogni rubrica, sotto la sua pillola
        "grant": f"{n_calls} open calls worldwide" + (f" · {n_italy} open to Italian institutions" if n_italy else ""),
        "positions": f"{n_positions} open PhD, post-doc and faculty positions" if n_positions
                     else "PhD, post-doc and faculty positions",
        "methods": f"{n_methods} carousel{'s' if n_methods != 1 else ''}, with key points and references" if n_methods
                   else "Practical topics with key points and references",
        "science": f"{n_science} clinical lesson{'s' if n_science != 1 else ''}, one new every Saturday" if n_science
                   else "One clinical paper, one lesson for practice: every Saturday"}
    return HOME.format(brand=escape(cfg["brand_name"]), ig=cfg["handle"].lstrip("@"), bg=c["background"], social=social_links(cfg),
                       soft=c["muted_text"], muted=c["muted"], teal=c["accent"],
                       amber=site_accent(cfg, "grant"), lilac=site_accent(cfg, "positions"), sci=site_accent(cfg, "science"), meth=site_accent(cfg, "methods"),
                       updated=_fmt_date(today),
                       logo_block=header_logo(cfg), pills=section_pills(cfg, metrics),
                       og=og_tags(cfg, cfg["brand_name"], "Open research funding calls and academic positions in clinical "
                                  "engineering and rehabilitation, checked on the official texts.", "") + org_jsonld(cfg))


def org_jsonld(cfg):
    """Dati strutturati dell'organizzazione (schema.org): collegano il sito ai profili social per Google."""
    ig = cfg["handle"].lstrip("@")
    same = [f"https://www.instagram.com/{ig}/", f"https://www.facebook.com/{ig}"]
    if cfg.get("bluesky_handle"):
        same.append(f"https://bsky.app/profile/{cfg['bluesky_handle'].lstrip('@')}")
    if cfg.get("linkedin_url"):
        same.append(cfg["linkedin_url"])
    data = {"@context": "https://schema.org", "@type": "Organization", "name": cfg["brand_name"],
            "url": site_url(cfg, ""), "logo": site_url(cfg, "og.png"), "sameAs": same}
    return '\n<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False) + "</script>"


def filters_form(entries):
    """Riquadro dei filtri della pagina bandi (parola chiave, area, scadenza): gratis per tutti, funziona nel browser."""
    from html import escape
    regions = "".join(f'<option value="{escape(r, quote=True)}">{escape(r)}</option>' for r in REGIONS)
    area_opts = "".join(f'<option value="{k}">{escape(v)}</option>' for k, v in AREA_LABELS.items())
    return f"""  <form class="filters" role="search" aria-label="Filter calls" onsubmit="return false">
    <label class="wide">Search<input type="search" name="q" placeholder="Keyword, funder, programme or country (e.g. stroke, NIH, Germany)" autocomplete="off"></label>
    <label>Applicants based in<select name="where"><option value="">Anywhere</option><option value="italy">Italy (open to Italian institutions)</option>{regions}</select></label>
    <label>Area<select name="area"><option value="">All areas</option>{area_opts}</select></label>
    <label>Deadline<select name="time"><option value="">Any deadline</option><option value="lt30">Closing within 30 days</option>
      <option value="ge30">At least 30 days left</option><option value="ge60">At least 60 days left</option><option value="ge90">At least 90 days left</option></select></label>
    <p class="hint">International calls are included under every region; a call can belong to up to three areas.</p>
    <div class="status"><span class="count" aria-live="polite">{len(entries)} open calls</span><button type="reset" hidden>Clear filters</button></div>
  </form>
"""


FILTER_SCRIPT = """
<script>
(function () {
  var form = document.querySelector("form.filters");
  if (!form) return;
  var cards = Array.prototype.slice.call(document.querySelectorAll("article.call, article.job, article.method"));
  var noun = form.dataset.noun || "open calls";
  var count = form.querySelector(".count"), reset = form.querySelector("button[type=reset]"), total = cards.length;
  var DAY = 86400000, today = new Date(); today.setHours(0, 0, 0, 0);
  function norm(t) { return (t || "").toLowerCase().normalize("NFD").replace(/[\\u0300-\\u036f]/g, ""); }
  cards.forEach(function (c) { c._text = norm(c.dataset.text); });
  function inRegion(c, where) {
    if (!where) return true;
    if (where === "italy") return c.dataset.italy === "yes";
    return c.dataset.region === where || (where !== "International & intercontinental" && c.dataset.region === "International & intercontinental");
  }
  function inArea(c, area) { return !area || (" " + c.dataset.area + " ").indexOf(" " + area + " ") !== -1; }
  ["where", "area"].forEach(function (n) {
    if (!form[n]) return;
    Array.prototype.forEach.call(form[n].options, function (o) {
      if (!o.value) return;
      var k = cards.filter(function (c) { return n === "where" ? inRegion(c, o.value) : inArea(c, o.value); }).length;
      o.textContent += " (" + k + ")";
      if (!k) o.disabled = true;
    });
  });
  function apply(save) {
    var val = function (n) { return form[n] ? form[n].value : ""; };
    var q = norm(form.q.value).trim(), where = val("where"), time = val("time"), area = val("area"),
        words = q ? q.split(/\\s+/) : [], shown = 0;
    cards.forEach(function (c) {
      var ok = words.every(function (w) { return c._text.indexOf(w) !== -1; });
      if (ok) ok = inRegion(c, where) && inArea(c, area);
      if (ok && time) {
        var d = c.dataset.deadline ? (new Date(c.dataset.deadline + "T00:00:00") - today) / DAY : null;
        ok = d !== null && (time === "lt30" ? d < 30 : d >= parseInt(time.slice(2), 10));
      }
      c.hidden = !ok; if (ok) shown++;
    });
    document.querySelectorAll(".grp").forEach(function (g) { g.hidden = !g.querySelector("article:not([hidden])"); });
    document.querySelectorAll(".reg").forEach(function (g) { g.hidden = !g.querySelector("article:not([hidden])"); });
    document.querySelectorAll("section").forEach(function (s) {
      var none = s.querySelector("article") && !s.querySelector("article:not([hidden])"), msg = s.querySelector(".nomatch");
      if (none && !msg) { msg = document.createElement("p"); msg.className = "nomatch"; msg.textContent = "Nothing in this section matches your filters."; s.appendChild(msg); }
      if (msg) msg.hidden = !none;
    });
    var active = !!(q || where || time || area);
    count.textContent = active ? "Showing " + shown + " of " + total + " " + noun : total + " " + noun;
    reset.hidden = !active;
    if (save) {
      var p = new URLSearchParams();
      if (form.q.value.trim()) p.set("q", form.q.value.trim()); if (where) p.set("where", where); if (time) p.set("time", time);
      if (area) p.set("area", area);
      var qs = p.toString();
      history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
    }
  }
  var p = new URLSearchParams(location.search);
  if (p.get("q")) form.q.value = p.get("q");
  ["where", "time", "area"].forEach(function (n) { if (p.get(n) && form[n]) form[n].value = p.get(n); });
  var timer;
  form.q.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(function () { apply(true); }, 150); });
  ["where", "time", "area"].forEach(function (n) { if (form[n]) form[n].addEventListener("change", function () { apply(true); }); });
  form.addEventListener("reset", function () { setTimeout(function () { apply(true); }, 0); });
  apply(false);
})();
</script>
"""


# ---------------------------------------------------------------- feed RSS (bandi e posizioni)
FEED_LINKS = ('<link rel="alternate" type="application/rss+xml" title="Open funding calls" href="feed-calls.xml">\n'
              '<link rel="alternate" type="application/rss+xml" title="Academic positions" href="feed-positions.xml">')


def rss(cfg, title, description, path, items):
    """Feed RSS 2.0; items = [(titolo, link, descrizione, data, guid)], dai più recenti."""
    from xml.sax.saxutils import escape as x
    from email.utils import format_datetime
    def when(d):
        d = d or date.today()
        return format_datetime(datetime(d.year, d.month, d.day, 8, 0, tzinfo=__import__("datetime").timezone.utc))
    body = "".join(
        f"  <item>\n    <title>{x(t)}</title>\n    <link>{x(l)}</link>\n    <guid isPermaLink=\"false\">{x(g)}</guid>\n"
        f"    <pubDate>{when(d)}</pubDate>\n    <description>{x(desc)}</description>\n  </item>\n"
        for t, l, desc, d, g in items)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>\n'
            f'  <title>{x(title)}</title>\n  <link>{x(site_url(cfg, ""))}</link>\n  <description>{x(description)}</description>\n'
            f'  <language>en</language>\n  <atom:link href="{x(site_url(cfg, path))}" rel="self" type="application/rss+xml"/>\n'
            f'{body}</channel>\n</rss>\n')


def calls_feed(grants_list, verified, cfg, today=None):
    """Feed dei bandi verificati in pagina, dai controllati più di recente."""
    today = today or date.today()
    items = []
    for g, v, d in page_entries(grants_list, verified, today):
        if not v:
            continue
        title = v.get("title") or g.get("titolo") or ""
        label, note = deadline_text(v, d) if d else ("Deadline", "")
        desc = " ".join(x for x in (
            v.get("summary"), f"Programme: {v.get('programme')}." if v.get("programme") else "",
            f"Eligible countries: {v.get('eligible_countries')}." if v.get("eligible_countries") else "",
            f"Who can lead: {v.get('lead')}." if v.get("lead") else "",
            f"{label}: {_fmt_date(d)}" + (f" ({note})." if note else ".") if d else "Deadline: see the official call.",
            f"Official call: {g['url']}") if x)
        items.append((title, site_url(cfg, call_path(g, v)), desc, _date(v.get("checked")), g["id"]))
    items.sort(key=lambda it: it[3] or date.min, reverse=True)
    return rss(cfg, f"{cfg['brand_name']} – open funding calls",
               "Open funding calls in clinical research, clinical engineering and rehabilitation, checked on the official text.",
               "feed-calls.xml", items[:100])


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


AREA_LABELS = {"rehab": "Rehabilitation", "engineering": "Clinical & biomedical engineering",
               "neuro": "Neurology", "neuropsych": "Neuropsychology", "msk": "Physiatry & orthopaedics",
               "rheum": "Rheumatology", "paeds": "Paediatrics", "radiology": "Radiology & imaging", "ageing": "Ageing & geriatrics",
               "onco": "Oncology & haematology", "genetics": "Clinical genetics & rare diseases", "open": "Open topic"}


def areas(g):
    """Aree del bando (per il filtro): dai macrogruppi assegnati da GrantFinder."""
    mg = set(g.get("macrogruppi") or [])
    out = []
    if mg & {"Ictus", "Parkinson", "Invecchiamento", "Tecnologie riabilitazione", "Altre malattie e riabilitazione"}:
        out.append("rehab")
    for group, key in (("Neurologia", "neuro"), ("Ictus", "neuro"), ("Parkinson", "neuro"), ("Fisiatria e ortopedia", "msk"),
                       ("Neuropsicologia", "neuropsych"), ("Reumatologia", "rheum"), ("Pediatria", "paeds"),
                       ("Radiologia e imaging", "radiology"), ("Invecchiamento", "ageing"), ("Oncologia ed ematologia", "onco"),
                       ("Genetica clinica e malattie rare", "genetics")):
        if group in mg and key not in out:
            out.append(key)
    if mg & {"Ingegneria clinica", "Tecnologie riabilitazione"}:
        out.append("engineering")
    if "Ricerca sanitaria a tema libero" in mg and not out:
        out.append("open")
    # al massimo 3 aree (le prime sono le più specifiche); senza area riconosciuta: tema libero, mai «riabilitazione»
    return out[:3] or ["open"]


def card_anchor(grant_id):
    return "c-" + re.sub(r"[^A-Za-z0-9]+", "-", str(grant_id)).strip("-")


# ---------------------------------------------------------------- «Add to calendar» (bandi e posizioni)
CAL_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/>'
            '<path d="M16 3v4M8 3v4M3 10h18"/></svg>')


def calendar_button(d, title, url, details=""):
    """Pulsante che apre il menu calendario (Google Calendar o file .ics con promemoria 30 e 7 giorni prima)."""
    from html import escape
    if not d:
        return ""
    return (f'<button class="share cal" type="button" data-date="{d.isoformat()}" data-title="{escape(title, quote=True)}" '
            f'data-url="{escape(url, quote=True)}" data-details="{escape(details, quote=True)}" aria-haspopup="menu">'
            f'{CAL_ICON}Calendar</button>')


CAL = """
<div id="crc-cal-menu" role="menu" hidden></div>
<style>
  #crc-cal-menu { position: absolute; z-index: 50; background: #FFFFFF; color: #0E2233; border-radius: 14px; padding: 6px;
                  min-width: 210px; box-shadow: 0 12px 32px rgba(0,0,0,.35); font: 600 14px Inter, system-ui, sans-serif; }
  #crc-cal-menu a, #crc-cal-menu button { display: block; width: 100%; text-align: left; background: none; border: 0;
                  color: inherit; font: inherit; text-decoration: none; padding: 10px 12px; border-radius: 10px; cursor: pointer; }
  #crc-cal-menu a:hover, #crc-cal-menu button:hover, #crc-cal-menu a:focus-visible, #crc-cal-menu button:focus-visible {
                  background: #E7EEF4; outline: none; }
  #crc-cal-menu small { display: block; color: #5B7186; font-weight: 500; padding: 4px 12px 8px; }
</style>
<script>
(function () {
  var menu = document.getElementById("crc-cal-menu"), openFor = null;
  function ymd(s) { return s.replace(/-/g, ""); }
  function next(s) { var d = new Date(s + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + 1); return d.toISOString().slice(0, 10); }
  function esc(t) { return (t || "").replace(/[\\\\;,]/g, function (c) { return "\\\\" + c; }); }
  function ics(b) {
    var uid = "crc-" + ymd(b.dataset.date) + "-" + Math.abs(b.dataset.url.split("").reduce(function (h, c) { return (h * 31 + c.charCodeAt(0)) | 0; }, 7));
    var stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";
    var lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Clinical Research Chaos//Deadlines//EN", "BEGIN:VEVENT",
      "UID:" + uid, "DTSTAMP:" + stamp, "DTSTART;VALUE=DATE:" + ymd(b.dataset.date), "DTEND;VALUE=DATE:" + ymd(next(b.dataset.date)),
      "SUMMARY:" + esc("Deadline: " + b.dataset.title), "DESCRIPTION:" + esc(b.dataset.details + " " + b.dataset.url), "URL:" + b.dataset.url,
      "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + esc("30 days to the deadline: " + b.dataset.title), "TRIGGER:-P30D", "END:VALARM",
      "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + esc("7 days to the deadline: " + b.dataset.title), "TRIGGER:-P7D", "END:VALARM",
      "END:VEVENT", "END:VCALENDAR"];
    return lines.join("\\r\\n");
  }
  function close() { menu.hidden = true; openFor = null; }
  function show(b) {
    var e = encodeURIComponent, d = ymd(b.dataset.date);
    menu.innerHTML = "";
    var g = document.createElement("a");
    g.href = "https://calendar.google.com/calendar/render?action=TEMPLATE&text=" + e("Deadline: " + b.dataset.title) +
      "&dates=" + d + "/" + ymd(next(b.dataset.date)) + "&details=" + e((b.dataset.details ? b.dataset.details + "\\n" : "") + b.dataset.url);
    g.target = "_blank"; g.rel = "noopener"; g.textContent = "Google Calendar"; g.setAttribute("role", "menuitem");
    g.addEventListener("click", close); menu.appendChild(g);
    var f = document.createElement("button"); f.type = "button"; f.textContent = "Apple / Outlook (.ics)"; f.setAttribute("role", "menuitem");
    f.addEventListener("click", function () {
      var url = URL.createObjectURL(new Blob([ics(b)], { type: "text/calendar" }));
      var a = document.createElement("a"); a.href = url; a.download = "deadline-" + d + ".ics"; document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 500); close();
    });
    menu.appendChild(f);
    var note = document.createElement("small"); note.textContent = "The .ics file reminds you 30 and 7 days before."; menu.appendChild(note);
    var r = b.getBoundingClientRect(); menu.hidden = false;
    var left = Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - menu.offsetWidth - 12);
    menu.style.left = Math.max(12, left) + "px"; menu.style.top = (window.scrollY + r.bottom + 6) + "px";
    openFor = b; g.focus();
  }
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest && ev.target.closest("button.cal");
    if (b) { ev.preventDefault(); ev.stopImmediatePropagation(); if (openFor === b) close(); else show(b); }
    else if (!menu.contains(ev.target)) close();
  }, true);
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape" && openFor) { var b = openFor; close(); b.focus(); } });
})();
</script>
"""


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
  .crc-side.over { z-index: 2; }
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
    var GREYS = ["#0A0A0A", "#2E2E2E", "#5A5A5A", "#8A8A8A"];
    var SIZES = [4, 6, 8, 10, 12], SHAPES = [[], [], [[1, 0]], [[0, 1]], [[1, 0], [0, 1]], [[1, 0], [1, 1]]];
    function pick(a) { return a[Math.floor(Math.random() * a.length)]; }
    /* zone chiare della pagina (intestazione bianca): lì cubetti e pulviscolo cadono in nero e grigi,
       poi entrando nella parte scura prendono colore */
    var light = [];
    function lum(c) { var m = c.match(/\\d+(\\.\\d+)?/g); if (!m || (m.length > 3 && +m[3] === 0)) return -1;
      return (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255; }
    function zones() {
      light = [];
      document.querySelectorAll("body > header, body > .top, body > section, body > div:not(.crc-side), [data-light]").forEach(function (e) {
        var bg = getComputedStyle(e).backgroundColor;
        if (lum(bg) > 0.6) { var r = e.getBoundingClientRect(); if (r.bottom > 0 && r.height > 0) light.push([r.top, r.bottom]); }
      });
    }
    function mixIn(y) {       /* 0 = su chiaro (grigi), 1 = su scuro (colori); passaggio graduale di 40 px */
      for (var i = 0; i < light.length; i++) {
        var z = light[i];
        if (y >= z[0] - 4 && y < z[1]) return 0;
        if (y >= z[1] && y < z[1] + 40) return (y - z[1]) / 40;
      }
      return 1;
    }
    function side(id) {
      var el = document.getElementById(id), c = document.createElement("canvas"), ctx = c.getContext("2d");
      el.classList.add("over");
      el.appendChild(c);
      var L = { ctx: ctx, drops: [], dust: [], R: null };
      function drop(y) {
        return { x: Math.random() * L.R.width, y: (y === undefined ? -40 : y), s: pick(SIZES), v: 7 + Math.random() * 20,
                 c: pick(COLORS), g: pick(GREYS), a: 0.12 + Math.random() * 0.5, shape: pick(SHAPES) };
      }
      function mote(y) {
        var glow = Math.random() < 0.16;
        return { x: Math.random() * L.R.width, y: (y === undefined ? -20 : y), r: glow ? 5 + Math.random() * 10 : 0.6 + Math.random() * 1.4,
                 v: 4 + Math.random() * 10, w: Math.random() * 6.28, glow: glow, c: pick(COLORS), g: pick(GREYS.slice(1)),
                 a: glow ? 0.06 + Math.random() * 0.12 : 0.25 + Math.random() * 0.55 };
      }
      L.fit = function () {
        var r = el.getBoundingClientRect(), d = window.devicePixelRatio || 1;
        c.width = r.width * d; c.height = r.height * d; ctx.setTransform(d, 0, 0, d, 0, 0); L.R = r;
        L.drops = []; var n = Math.round(r.width * r.height / 7500);
        for (var i = 0; i < n; i++) L.drops.push(drop(Math.random() * r.height));
        L.dust = []; var m = Math.round(r.width * r.height / 2600);
        for (var j = 0; j < m; j++) L.dust.push(mote(Math.random() * r.height));
      };
      function paint(col, alpha, x, y, s) { if (alpha <= 0.003) return; ctx.globalAlpha = alpha; ctx.fillStyle = col; ctx.fillRect(x, y, s, s); }
      L.step = function (dt, t) {
        ctx.clearRect(0, 0, L.R.width, L.R.height);
        L.dust.forEach(function (p) {
          p.y += p.v * dt; p.x += Math.sin(t / 1800 + p.w) * 4 * dt;
          if (p.y > L.R.height + 20) { var n = mote(); for (var k in n) p[k] = n[k]; }
          var k2 = mixIn(p.y);
          [[p.g, (1 - k2) * 0.7], [p.c, k2]].forEach(function (v) {
            if (v[1] <= 0.003) return;
            ctx.globalAlpha = p.a * v[1];
            if (p.glow) {
              var gr = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r);
              gr.addColorStop(0, v[0]); gr.addColorStop(1, "rgba(0,0,0,0)");
              ctx.fillStyle = gr; ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.2832); ctx.fill();
            } else { ctx.fillStyle = v[0]; ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.2832); ctx.fill(); }
          });
        });
        L.drops.forEach(function (d) {
          d.y += d.v * dt;
          if (d.y > L.R.height + 40) { var n = drop(); for (var k in n) d[k] = n[k]; }
          [[0, 0]].concat(d.shape).forEach(function (o) {
            var x = d.x + o[0] * (d.s + 2), y = d.y + o[1] * (d.s + 2), k3 = mixIn(y + d.s / 2);
            paint(d.g, d.a * (1 - k3) * 1.25, x, y, d.s);
            paint(d.c, d.a * k3, x, y, d.s);
          });
        });
      };
      L.fit();
      return L;
    }
    zones();
    var sides = [side("crc-rain"), side("crc-rain-r")];
    var last = performance.now();
    function frame(t) {
      var dt = Math.min(0.05, (t - last) / 1000); last = t;
      sides.forEach(function (L) { L.step(dt, t); });
      if (!still) requestAnimationFrame(frame);
    }
    window.addEventListener("scroll", zones, { passive: true });
    window.addEventListener("resize", function () { zones(); sides.forEach(function (L) { L.fit(); }); if (still) frame(performance.now()); });
    requestAnimationFrame(frame);
  }
  start();
  if (wide.addEventListener) wide.addEventListener("change", start);
})();
</script>
"""


SITE_MONO = False      # impostato da bot.py (config «mono»): sito in nero con azzurrino per metodologia


def site_palette(cfg):
    """Colori del sito: quelli del config, oppure (config «mono») nero e grigi con azzurrino come colore base."""
    c = cfg["colors"]
    if cfg.get("mono"):
        return {**c, "background": "#0A0A0A", "muted": "#8A8A8A", "muted_text": "#CFCFCF", "accent": SITE_GREEN if cfg.get("site_v4") else site_accent(cfg, "methods")}
    return c


SITE_V4 = {"grant": "#F8B048", "positions": "#8858F0", "methods": "#88B0F8", "science": "#FFFFFF"}   # rubriche (colori del logo v3)
SITE_GREEN = "#3CC9B0"   # colore del sito (logo verde)


def site_accent(cfg, kind):
    """Colore di una sezione del sito: con config «site_v4» quello fisso della rubrica (come nel logo definitivo),
    altrimenti quello di prima. Solo sito: i post del bot non cambiano."""
    if cfg.get("site_v4"):
        return SITE_V4[kind]
    return {"grant": cfg.get("grant_accent", "#FFB547"), "positions": cfg.get("positions_accent", "#A78BFA"),
            "methods": "#6EC1FF", "science": "#6EC1FF"}[kind]


SECTIONS = [("methods", "methodology.html", "Design, Reporting &amp; Appraisal"),
            ("science", "science.html", "Latest Science"),
            ("grant", "calls.html", "Funding calls"),
            ("positions", "positions.html", "Academic positions")]


def on_color(hexa):
    """Nero o bianco, quello che si legge meglio sul colore dato."""
    r, g, b = (int(hexa.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#0A0A0A" if lum > 0.55 else "#FFFFFF"


def section_pills(cfg, metrics=None, current=None):
    """Le quattro rubriche in colonna: pillola nel colore della rubrica e, sotto, la sua metrica."""
    from html import escape as esc
    out = []
    for kind, href, label in SECTIONS:
        col = site_accent(cfg, kind)
        here = ' aria-current="page"' if kind == current else ""
        met = (metrics or {}).get(kind, "")
        out.append(f'<a href="{href}" style="--c:{col};--on:{on_color(col)}"{here}>'
                   f'<span class="tag">{label.upper()}</span>'
                   + (f'<span class="met">{esc(met)}</span>' if met else "") + "</a>")
    return "\n".join(out)


LOCKUP_SRC = {"methods": "lockup-methods.png", "science": "lockup-science.png",
              "grant": "lockup-calls.png", "positions": "lockup-positions.png"}


def page_lockup(cfg, kind):
    """Logo in cima a una pagina di sezione, nel colore della rubrica (bandi giallo, posizioni violetto,
    metodologia azzurro, Latest Science bianco), collegato alla home: la «o» di «Chaos» è il simbolo a cubetti,
    che col puntatore sopra si scompone e gira lungo l'anello della «o», come in home."""
    if not cfg.get("site_v4"):
        return ""
    return ('<div class="crc-top">' + header_logo(cfg, accent=site_accent(cfg, kind), kind=kind, href="index.html",
                                                  height="52px") +
            '</div><style>.crc-top { margin: 0 0 18px; }</style>')


def site_colors(cfg):
    """Colori della cascata laterale in home: le rubriche del sito (con «site_v4» anche Latest Science)."""
    keys = ("grant", "positions", "methods", "science") if cfg.get("site_v4") else ("grant", "positions", "methods")
    return {k: site_accent(cfg, k) for k in keys}


EDITORIAL_SITE = """<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:ital,wght@0,400;0,700;0,800;1,400&display=swap" rel="stylesheet">
<style id="crc-editorial">
  /* stile editoriale dei post (design_v3): titoli serif, testata da rivista, schede con filetto, etichette piene */
  h1, h2, h3, .t, .big .name, .num {font-family: "Source Serif 4", Georgia, serif !important; letter-spacing: -.01em;}
  h1 {font-weight: 800; font-size: clamp(30px, 6vw, 40px); line-height: 1.1;}
  .bar {height: 10px !important;}
  main::before {content: attr(data-brand); display: block;}
  .badge {border-radius: 999px; letter-spacing: .08em;}
  section > h2, .tools h2 {border-bottom: 1px solid #2E2E2E; padding-bottom: 6px;}
  article.method, .job, .call, form.filters, .nomatch, .tools .tool {background: #0F0F0F !important; border: 1px solid #2E2E2E !important;
      border-radius: 14px !important; box-shadow: none !important;}
  article.method, .job, .call {border-left-color: var(--accent) !important;}
    .take, .intro {font-family: "Source Serif 4", Georgia, serif; font-size: 17px !important; line-height: 1.5;}
  details summary, .k {letter-spacing: .04em;}
  .refs {border-top-color: #2E2E2E !important;}
  footer {border-top: 1px solid #2E2E2E; padding-top: 14px;}
  footer, .date {font-family: "Source Serif 4", Georgia, serif; font-style: italic;}
  mark, .hl {background: var(--accent); color: #0A0A0A; padding: 0 .15em;}
</style>
"""


SITE_COLORS = {"grant": "#FFB547", "positions": "#8B5CF6", "methods": "#6EC1FF"}   # aggiornati da bot.py dal config


def _shade(hexc, f):
    r, g, b = (int(hexc.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02X%02X%02X" % (int(r * f + 10 * (1 - f)), int(g * f + 10 * (1 - f)), int(b * f + 10 * (1 - f)))


def page_cubes(html):
    """Cubetti della cascata laterale nel colore della pagina, come i cubetti dei post: giallo i bandi, violetto le
    posizioni, azzurrino la metodologia (e le altre pagine); in home i tre colori insieme."""
    import json as _json
    import re as _re
    home = _re.search(r'rel="canonical" href="https?://[^/"]+/"', html)
    if home:
        cols = []
        for c in SITE_COLORS.values():
            cols += [c, _shade(c, .55)]
    else:
        m = _re.search(r"--accent:\s*(#[0-9A-Fa-f]{6})", html)
        acc = m.group(1) if m else SITE_COLORS["methods"]
        if acc.upper() == "#A78BFA":                   # vecchio violetto delle pagine posizioni
            acc = SITE_COLORS["positions"]
            html = html.replace("#A78BFA", acc)
        cols = [acc, acc, _shade(acc, .55), _shade(acc, .3)]
    return _re.sub(r"var COLORS = \[[^\]]*\];", "var COLORS = " + _json.dumps(cols) + ";", html)


def fit_decor(html):
    """Larghezza delle cascate laterali adattata alla colonna della pagina: i cubetti si fermano alla stessa distanza
    dal contenuto su tutte le pagine (6 px, come Latest Science), qualunque sia la max-width di <main>."""
    import re as _re
    m = _re.search(r"main\s*\{[^}]*?max-width:\s*(\d+)px", html)
    w = int(m.group(1)) - 20 if m else 740
    return _re.sub(r"(\.crc-side \{ position: fixed; top: 0; bottom: 0; width: calc\(\(100vw - )\d+(px\) / 2\))",
                   lambda x: f"{x.group(1)}{w}{x.group(2)}", html, count=1)


def add_decor(html):
    """Aggiunge prima di </body> la decorazione animata ai lati (cascata di quadratini) e, se la pagina ha
    pulsanti «Share», il menu di condivisione."""
    if SITE_MONO:
        html = html.replace("#15304A", "#161616").replace("#2A4058", "#2E2E2E")
        if "crc-editorial" not in html:
            html = html.replace("</head>", EDITORIAL_SITE + "</head>", 1)
    if "crc-rain" not in html:
        html = html.replace("</body>", DECOR + "</body>", 1)
    html = fit_decor(html)
    if 'class="share"' in html and "crc-share-menu" not in html:
        html = html.replace("</body>", SHARE + "</body>", 1)
    if 'class="share cal"' in html and "crc-cal-menu" not in html:
        html = html.replace("</body>", CAL + "</body>", 1)
    if SITE_MONO:
        html = page_cubes(html)
    if 'class="filters"' in html and "form.filters\")" not in html:
        html = html.replace("</body>", FILTER_SCRIPT + "</body>", 1)
    return html
