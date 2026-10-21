"""Post sui bandi di ricerca: legge il report pubblico di GrantFinder e prepara un carosello per un bando."""

from datetime import date, datetime, timedelta

import json
import re
from html import unescape

import requests

import content

DEFAULT_URL = "https://raw.githubusercontent.com/Stefanodoro91/GrantFinder/main/dati/stato.json"
RELEVANCE_ORDER = {"Alta": 0, "Media": 1}

PROMPT = """You write an Instagram carousel for "{brand}", a page for researchers and health professionals
about clinical research and research methodology. The post informs followers about ONE research funding
call. Below is the OFFICIAL TEXT of the call, followed by a few catalogue data.

STRICT ACCURACY RULES:
- Use ONLY the official text. Translate and rephrase, but never add facts, numbers, dates, amounts,
  eligibility rules or requirements that are not in it.
- Do not write the deadline, amounts or the funder's name in the slides: they are added separately.

FIRST check eligibility for an organisation based in Italy:
- italy_eligible: "yes" only if the official text explicitly allows organisations from Italy, from any
  country, from non-US/foreign countries, or from a group of countries that includes Italy (e.g. EU
  Member States) to apply or receive funding as applicant/beneficiary. "no" if it excludes foreign or
  non-domestic organisations or restricts applicants to other countries. "unclear" otherwise.
  "Foreign components" of US organisations or a bare list of applicant types are NOT enough for "yes".
- italy_evidence: the sentence from the official text, copied word for word, that justifies the answer
  ("" if unclear).

Then write IN ENGLISH:
- summary: 50-80 words, factual and neutral: aim of the call, what is funded, who can apply. For a
  public web page listing calls; no hype.
- title: a clear hook for the cover, max 70 characters, mentioning the research area (no deadline).
- slides: exactly 2 slides. Slide 1 heading "What it funds": aim and kind of projects funded.
  Slide 2 heading "Who it is for": applicants and teams it targets. Each body max 220 characters.
  Each slide also has image_prompt: 15-35 words describing ONE simple illustration of the slide's idea
  (concrete scene with 2-4 recognizable elements; no text, letters, numbers, logos or real people).
  Each slide also has highlight: its key idea, 2-6 words copied EXACTLY from its body.
- title_highlight: 1-4 words copied EXACTLY from the title (the research area or the key benefit).
- eligibility: who can apply, max 120 characters.
- coverage: funding coverage in a few words (e.g. "Fully funded"), or "" if not stated.
- takeaway: one sentence on why this call is worth a look, max 120 characters.
- takeaway_highlight: 2-5 words copied EXACTLY from the takeaway.
- caption: 2-4 short lines with context; end with a question inviting researchers to share whether they
  plan to apply or know similar calls. Max 600 characters, no hashtags, no links.
- hashtags: 6-10 specific hashtags (e.g. #ResearchFunding #GrantOpportunity #Neurorehabilitation).

OFFICIAL TEXT ({source}):
{official}

CATALOGUE DATA (may be in Italian, less reliable than the official text):
{data}"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "italy_eligible": {"type": "STRING", "enum": ["yes", "no", "unclear"]},
        "italy_evidence": {"type": "STRING"},
        "summary": {"type": "STRING"},
        "title": {"type": "STRING"},
        "slides": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"heading": {"type": "STRING"}, "body": {"type": "STRING"},
                               "image_prompt": {"type": "STRING"}, "highlight": {"type": "STRING"}},
                "required": ["heading", "body", "image_prompt", "highlight"],
            },
        },
        "title_highlight": {"type": "STRING"},
        "takeaway_highlight": {"type": "STRING"},
        "eligibility": {"type": "STRING"},
        "coverage": {"type": "STRING"},
        "takeaway": {"type": "STRING"},
        "caption": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["italy_eligible", "italy_evidence", "summary", "title", "slides", "eligibility",
                 "takeaway", "caption", "hashtags"],
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


def candidates(grants, posted, cfg, today=None):
    """Bandi pubblicabili: Italia ammessa, pertinenza Alta/Media, scadenza abbastanza lontana, mai pubblicati."""
    today = today or date.today()
    min_days = int(cfg.get("grant_min_days_left", 14))
    done = {p.get("grant_id") for p in posted if p.get("grant_id")}
    out = []
    for g in grants:
        deadline = _date(g.get("scadenza"))
        if (g.get("_attivo", True) and g.get("italia") == "Sì" and g.get("rilevanza") in RELEVANCE_ORDER
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


# ---------------------------------------------------------------- testo ufficiale della call
NIH_GUIDE = "https://grants.nih.gov/grants/guide/{folder}/{number}.html"
NIH_NUMBER = re.compile(r"\b((?:RFA|PAR|PAS|PA|NOT|OTA)-(?:[A-Z]{2}-)?\d{2}-\d{3})\b", re.I)
NIH_FOREIGN = re.compile(
    r"non-?domestic\s*\(non-?u\.?s\.?\)\s*entities\s*\(foreign\s+(?:organi[sz]ations|institutions)\)\s*"
    r"(?:are|is)\s+(not\s+)?(?:eligible|allowed|permitted)[^.]*\.", re.I)
EU_SEARCH = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
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
    return html_to_text(_get(g["url"])), "official call page", g["url"]


def _simple(x):
    return re.sub(r"[^a-z0-9]+", " ", (x or "").lower()).strip()


def check_italy(g, text, out):
    """(True/False, frase di prova). Regole deterministiche prima, poi la frase citata da Gemini verificata nel testo."""
    m = NIH_FOREIGN.search(text)
    if m:                                    # la frase ufficiale NIH decide in ogni caso
        return (not m.group(1)), m.group(0).strip()
    gid = g.get("id", "")
    if gid.startswith("EU-") and gid[3:].upper().startswith(EU_MEMBER_STATE_PROGRAMMES):
        return True, "EU programme: legal entities established in EU Member States, including Italy, are eligible."
    ev = (out.get("italy_evidence") or "").strip()
    if out.get("italy_eligible") == "yes" and len(ev) >= 25 and _simple(ev) in _simple(text):
        return True, ev
    return False, ev


def build_post(g, cfg):
    """Prepara il post (stesso formato dei post di metodologia, più i dati chiave) per un bando."""
    text, source, source_url = official_text(g)
    if len(text) < 400:
        raise RuntimeError(f"testo ufficiale troppo breve ({len(text)} caratteri) da {source}")
    data = "\n".join(f"{k}: {g.get(k)}" for k in FIELDS if g.get(k))
    prompt = PROMPT.format(brand=cfg["brand_name"], data=data, source=source, official=text[:60000])
    out = content.gemini_json([{"text": prompt}], SCHEMA, 0.2)
    ok, evidence = check_italy(g, text, out)
    if not ok:
        raise RuntimeError(f"Italia non confermata dal testo ufficiale ({source}): {evidence[:200] or 'nessuna frase'}")
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
    facts = [("Funder", clip(funder_line(g), 80)),
             ("Deadline", _fmt_date(deadline))]
    per_project = _money(g.get("budget_progetto"), g.get("valuta"))
    total = _money(g.get("budget_totale"), g.get("valuta"))
    if per_project:
        facts.append(("Budget per project", per_project))
    elif total:
        facts.append(("Total budget", total))
    if g.get("progetti_finanziabili"):
        facts.append(("Projects funded", str(g["progetti_finanziabili"])))
    if (out.get("coverage") or "").strip():
        facts.append(("Coverage", clip(out["coverage"], 60)))
    facts.append(("Who can apply", clip(out.get("eligibility", ""), 140)))
    facts.append(("Italian institutions", "Eligible (verify in the call)"))

    caption = (f"{out.get('caption', '').strip()[:700]}\n\n"
               f"Deadline: {_fmt_date(deadline)}\n"
               f"Official call: {g['url']}\n"
               "Clickable link in bio, with all open calls we have shared.\n\n"
               "Details are compiled automatically: always check eligibility, amounts and dates in the official call.")
    tags = ["#" + t.lstrip("#").replace(" ", "") for t in out.get("hashtags", []) if t.strip("# ")]
    return {
        "id": f"grant-{g['id']}"[:60],
        "kind": "grant",
        "grant_id": g["id"],
        "title": clip(out["title"], 90),
        "title_highlight": content.exact_phrase(out.get("title_highlight"), clip(out["title"], 90), 4),
        "takeaway_highlight": content.exact_phrase(out.get("takeaway_highlight"), clip(out.get("takeaway", ""), 160), 5),
        "category": "Funding opportunity",
        "funder": clip(funder_line(g), 60),
        "deadline": _fmt_date(deadline),
        "deadline_iso": deadline.isoformat(),
        "url": g["url"],
        "slides": slides,
        "facts": [(k, v) for k, v in facts if v],
        "takeaway": clip(out.get("takeaway", ""), 160) or "Worth a look if this is your research area.",
        "closing_cta": ("Check the official call before applying", "Clickable link in bio"),
        "caption": caption,
        "hashtags": ["#ResearchFunding", "#GrantOpportunity"] + tags[:10],
        "summary": clip(out.get("summary", ""), 700),
        "italy_evidence": clip(evidence, 300),
        "official_source": source,
        "source": "GrantFinder",
        "source_hint": g.get("fonte", ""),
    }


def is_grant_day(cfg, now=None):
    """Giorni dei bandi in ora italiana (0 = lunedì). Default: mercoledì e sabato."""
    from zoneinfo import ZoneInfo
    now = now or datetime.now(ZoneInfo("Europe/Rome"))
    return now.weekday() in cfg.get("grant_weekdays", [2, 5])


def next_grant_post(posted, cfg):
    """Il post del prossimo bando disponibile, oppure None (nessun bando adatto o GrantFinder non raggiungibile)."""
    try:
        pool = candidates(fetch(cfg), posted, cfg)
    except Exception as e:
        print(f"GrantFinder non raggiungibile: {e}")
        return None
    print(f"Bandi candidati da GrantFinder: {len(pool)}")
    for g in pool[:5]:   # se un bando non supera la verifica si passa al successivo
        try:
            post = build_post(g, cfg)
            print(f"::notice title=Bando verificato::{g['id']} - {post['official_source']} - {post['italy_evidence'][:200]}")
            return post
        except Exception as e:
            print(f"::warning title=Bando scartato::{g['id']} - {str(e)[:300]}")
    return None


# ---------------------------------------------------------------- pagina «link in bio»
PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Open calls · {brand}</title>
<meta name="description" content="Open research funding calls shared by {handle}, with links to the official calls.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
  :root {{ --bg: {bg}; --card: #15304A; --text: #FFFFFF; --muted: {muted}; --soft: {soft}; --accent: {accent}; --teal: {teal}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text); font-family: Inter, system-ui, sans-serif; line-height: 1.45; }}
  .bar {{ height: 6px; background: var(--accent); }}
  main {{ max-width: 640px; margin: 0 auto; padding: 28px 16px 48px; }}
  .badge {{ display: inline-block; background: var(--accent); color: var(--bg); font-weight: 800; font-size: 13px;
           letter-spacing: .06em; padding: 6px 14px; border-radius: 999px; }}
  h1 {{ font-size: 30px; font-weight: 800; margin: 14px 0 6px; line-height: 1.15; }}
  .intro {{ color: var(--soft); margin: 0 0 26px; font-size: 15px; }}
  .call {{ background: var(--card); border-radius: 18px; padding: 20px; margin-bottom: 16px; border-left: 4px solid var(--accent); }}
  .funder {{ color: var(--soft); font-size: 13px; font-weight: 600; margin-bottom: 6px; }}
  .call h2 {{ font-size: 19px; margin: 0 0 14px; line-height: 1.3; }}
  .summary {{ color: var(--soft); font-size: 15px; margin: -4px 0 12px; }}
  .evidence {{ font-size: 13px; color: var(--soft); border-left: 2px solid var(--muted); padding-left: 10px; margin: 0 0 16px; font-style: italic; }}
  .evidence span {{ display: block; font-style: normal; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; font-size: 11px; margin-bottom: 2px; }}
  .row {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between; }}
  .deadline {{ font-size: 14px; color: var(--soft); }}
  .deadline b {{ color: var(--text); font-size: 16px; }}
  .soon {{ color: var(--accent); font-weight: 800; font-size: 12px; margin-left: 6px; }}
  a.btn {{ background: var(--accent); color: var(--bg); text-decoration: none; font-weight: 800; font-size: 15px;
           padding: 11px 18px; border-radius: 12px; }}
  a.btn:focus-visible {{ outline: 3px solid var(--text); outline-offset: 2px; }}
  .empty {{ color: var(--soft); background: var(--card); border-radius: 18px; padding: 22px; }}
  footer {{ color: var(--muted); font-size: 13px; margin-top: 30px; }}
  footer a {{ color: var(--teal); }}
</style>
</head>
<body>
<div class="bar"></div>
<main>
  <span class="badge">OPEN CALLS</span>
  <h1>Research funding calls</h1>
  <p class="intro">Calls featured on {handle}, sorted by deadline. Closed calls are removed automatically.</p>
{items}
  <footer>
    Details are compiled automatically: always check eligibility, amounts and dates in the official call.<br>
    Updated {updated} · <a href="https://www.instagram.com/{ig}/">{handle} on Instagram</a>
  </footer>
</main>
</body>
</html>
"""


def build_page(posted, cfg, today=None):
    """HTML della pagina con i bandi pubblicati e ancora aperti, dalla scadenza più vicina."""
    from html import escape
    today = today or date.today()
    calls, seen = [], set()
    for p in posted:
        d = _date(p.get("deadline"))
        if (p.get("kind") == "grant" and p.get("url") and d and d >= today and p["grant_id"] not in seen
                and not p.get("withdrawn")):
            seen.add(p["grant_id"])
            calls.append((d, p))
    calls.sort(key=lambda x: x[0])
    items = []
    for d, p in calls:
        soon = '<span class="soon">CLOSING SOON</span>' if (d - today).days <= 21 else ""
        items.append(f"""  <article class="call">
    <div class="funder">{escape(p.get("funder", ""))}</div>
    <h2>{escape(p["title"])}</h2>
    {f'<p class="summary">{escape(p["summary"])}</p>' if p.get("summary") else ""}
    {f'<p class="evidence"><span>Eligibility check</span> &ldquo;{escape(p["italy_evidence"])}&rdquo;</p>' if p.get("italy_evidence") else ""}
    <div class="row">
      <div class="deadline">Deadline <b>{_fmt_date(d)}</b>{soon}</div>
      <a class="btn" href="{escape(p["url"], quote=True)}" target="_blank" rel="noopener">Official call &rarr;</a>
    </div>
  </article>""")
    if not items:
        items = ['  <p class="empty">No open calls right now. New calls are shared every Wednesday and Saturday.</p>']
    c = cfg["colors"]
    return PAGE.format(brand=escape(cfg["brand_name"]), handle=escape(cfg["handle"]), ig=cfg["handle"].lstrip("@"),
                       bg=c["background"], muted=c["muted"], soft=c["muted_text"], teal=c["accent"],
                       accent=cfg.get("grant_accent", "#FFB547"), items="\n".join(items),
                       updated=_fmt_date(today))
