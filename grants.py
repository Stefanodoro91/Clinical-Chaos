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


def candidates(grants, posted, verified, cfg, today=None):
    """Bandi da pubblicare: verificati sul testo ufficiale, call aperta, pertinenza Alta/Media,
    scadenza abbastanza lontana, mai pubblicati. Tutti i Paesi."""
    today = today or date.today()
    min_days = int(cfg.get("grant_min_days_left", 14))
    done = {p.get("grant_id") for p in posted if p.get("grant_id")}
    out = []
    for g in grants:
        v = verified.get(g.get("id"), {})
        deadline = _date(g.get("scadenza"))
        if (v.get("status") == "ok" and v.get("is_open_call") != "no" and g.get("rilevanza") in RELEVANCE_ORDER
                and deadline and deadline >= today + timedelta(days=min_days)
                and g.get("id") not in done and g.get("url")):
            out.append(g)
    # prima la pertinenza alla riabilitazione, poi la scadenza più vicina
    return sorted(out, key=lambda g: (RELEVANCE_ORDER[g["rilevanza"]], g["scadenza"]))


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
        return html_to_text(_get(url)), f"NIH Guide {number}", url
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
        return ". ".join(p for p in parts if p), f"Grants.gov opportunity {m.group(1)}", g["url"]
    return html_to_text(_get(g["url"])), "official call page", g["url"]


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
    c_ev = _quoted(out.get("countries_evidence"), text, 15)
    countries = (out.get("eligible_countries") or "").strip() if c_ev else ""
    i_ev = _quoted(out.get("italy_evidence"), text)
    italy = out.get("italy_eligible") if (i_ev and out.get("italy_eligible") in ("yes", "no")) else "unclear"
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
    programme = (out.get("programme") or "").strip()
    if not (programme and _words_found(programme, text)):
        programme = programme_detail(g)
    return {
        "status": "ok", "checked": date.today().isoformat(), "official_source": source, "official_url": source_url,
        "is_open_call": out.get("is_open_call", "unclear"),
        "title": content._clip(out.get("title") or g.get("titolo") or "", 140),
        "programme": content._clip(programme, 120), "programme_family": programme_family(g),
        "summary": content._clip(out.get("summary", ""), 700), **elig,
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
               "All open calls, grouped by programme: link in bio.\n\n"
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
        "summary": v.get("summary", ""), "italy_evidence": v.get("italy_evidence", ""),
        "official_source": v.get("official_source", ""), "source": "GrantFinder", "source_hint": g.get("fonte", ""),
    }


def is_grant_day(cfg, now=None):
    """Giorni dei bandi in ora italiana (0 = lunedì). Default: mercoledì e sabato."""
    from zoneinfo import ZoneInfo
    now = now or datetime.now(ZoneInfo("Europe/Rome"))
    return now.weekday() in cfg.get("grant_weekdays", [2, 5])


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
  h3.prog {{ font-size: 15px; letter-spacing: .04em; text-transform: uppercase; color: var(--accent);
            margin: 28px 0 10px; display: flex; justify-content: space-between; gap: 10px; }}
  h3.prog span {{ color: var(--muted); font-weight: 600; }}
  .call {{ background: var(--card); border-radius: 18px; padding: 20px; margin-bottom: 14px; border-left: 4px solid var(--accent); }}
  .call.other {{ border-left-color: var(--teal); }}
  .funder {{ color: var(--soft); font-size: 13px; font-weight: 600; margin-bottom: 6px; }}
  .tag {{ display: inline-block; background: var(--teal); color: var(--bg); font-size: 11px; font-weight: 800;
         letter-spacing: .05em; padding: 2px 8px; border-radius: 999px; margin-left: 6px; vertical-align: 1px; }}
  .call h4 {{ font-size: 18px; margin: 0 0 10px; line-height: 1.3; }}
  .summary {{ color: var(--soft); font-size: 15px; margin: 0 0 12px; }}
  .countries {{ font-size: 14px; margin: 0 0 4px; }}
  .countries b {{ color: var(--soft); font-weight: 600; }}
  details {{ font-size: 13px; color: var(--soft); margin: 0 0 14px; }}
  details summary {{ cursor: pointer; color: var(--muted); }}
  details p {{ border-left: 2px solid var(--muted); padding-left: 10px; margin: 8px 0 0; font-style: italic; }}
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
  <span class="badge">OPEN CALLS</span>
  <h1>Research funding calls</h1>
  <p class="intro">Open calls for clinical and rehabilitation research, each checked against the official call text.
  Grouped by funding programme and sorted by deadline. Closed calls are removed automatically.</p>
  <nav class="jump"><a href="#italy">Open to Italian institutions <b>{n_italy}</b></a><a href="#other">Other calls <b>{n_other}</b></a></nav>
  <section class="macro" id="italy">
    <h2>Open to Italian institutions</h2>
    <p>The official call explicitly allows organisations based in Italy (directly, as EU Member State, or as any country).</p>
{italy}
  </section>
  <section class="macro" id="other">
    <h2>Other calls</h2>
    <p>Calls restricted to other countries, or where the official text does not state whether Italian organisations can apply.</p>
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
    """Bandi da mostrare: attivi in GrantFinder, verificati sul testo ufficiale, non chiusi, scadenza futura o non indicata."""
    today = today or date.today()
    out = []
    for g in grants_list:
        v = verified.get(g.get("id"), {})
        d = _date(g.get("scadenza"))
        if (g.get("_attivo", True) and g.get("url") and v.get("status") == "ok" and v.get("is_open_call") != "no"
                and (d is None or d >= today)):
            out.append((g, v, d))
    return out


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
    other = [e for e in entries if e[1].get("italy") != "yes"]

    def card(g, v, d, css):
        if d:
            soon = '<span class="soon">CLOSING SOON</span>' if (d - today).days <= 21 else ""
            when = f"Deadline <b>{_fmt_date(d)}</b>{soon}"
        else:
            when = "Deadline <b>see official call</b>"
        tag = '<span class="tag">ON INSTAGRAM</span>' if g["id"] in featured else ""
        ev = v.get("countries_evidence") or v.get("italy_evidence")
        proof = (f'<details><summary>From the official call</summary><p>&ldquo;{escape(ev)}&rdquo;</p></details>'
                 if ev else "")
        return f"""    <article class="call {css}">
      <div class="funder">{escape(v.get("programme") or programme_detail(g))}{tag}</div>
      <h4>{escape(v.get("title") or g.get("titolo") or "")}</h4>
      {f'<p class="summary">{escape(v["summary"])}</p>' if v.get("summary") else ""}
      <p class="countries"><b>Eligible countries:</b> {escape(v.get("eligible_countries") or "check the call")}</p>
      {proof}
      <div class="row">
        <div class="deadline">{when}</div>
        <a class="btn" href="{escape(g["url"], quote=True)}" target="_blank" rel="noopener">Official call &rarr;</a>
      </div>
    </article>"""

    def section(items, css, empty):
        if not items:
            return f'    <p class="empty">{empty}</p>'
        html_parts = []
        for prog, group in _group(items):
            html_parts.append(f'    <h3 class="prog">{escape(prog)} <span>{len(group)}</span></h3>')
            html_parts += [card(g, v, d, css) for g, v, d in group]
        return "\n".join(html_parts)

    c = cfg["colors"]
    return PAGE.format(brand=escape(cfg["brand_name"]), handle=escape(cfg["handle"]), ig=cfg["handle"].lstrip("@"),
                       bg=c["background"], muted=c["muted"], soft=c["muted_text"], teal=c["accent"],
                       accent=cfg.get("grant_accent", "#FFB547"), n_italy=len(italy), n_other=len(other),
                       italy=section(italy, "", "No verified calls open to Italian institutions right now."),
                       other=section(other, "other", "No other verified calls right now."),
                       updated=_fmt_date(today))
