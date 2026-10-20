"""Post sui bandi di ricerca: legge il report pubblico di GrantFinder e prepara un carosello per un bando."""

from datetime import date, datetime, timedelta

import requests

import content

DEFAULT_URL = "https://raw.githubusercontent.com/Stefanodoro91/GrantFinder/main/dati/stato.json"
RELEVANCE_ORDER = {"Alta": 0, "Media": 1}

PROMPT = """You write an Instagram carousel for "{brand}", a page for researchers and health professionals
about clinical research and research methodology. The post informs followers about ONE open research
funding call. Below are the data collected automatically about the call (some fields are in Italian).

STRICT ACCURACY RULES:
- Use ONLY the information in the data. Translate and rephrase, but never add facts, numbers, dates,
  amounts, eligibility rules or requirements that are not in the data.
- Do not write the deadline, amounts or the funder's name in the slides: they are added separately.
- If a field is empty or says "not indicated", do not guess it.

Write IN ENGLISH:
- title: a clear hook for the cover, max 70 characters, mentioning the research area (no deadline).
- slides: exactly 2 slides. Slide 1 heading "What it funds": the aim and the kind of projects funded.
  Slide 2 heading "Who it is for": the applicants and teams it targets and why it matters for
  clinical/rehabilitation research. Each body max 220 characters.
  Each slide also has image_prompt: 15-35 words describing ONE simple illustration of the slide's idea
  (concrete scene with 2-4 recognizable elements; no text, letters, numbers, logos or real people).
- eligibility: who can apply, max 120 characters (from "chi_puo", "paesi", "partenariato").
- coverage: funding coverage in a few words (e.g. "Fully funded"), or "" if not indicated.
- takeaway: one sentence on why this call is worth a look, max 120 characters.
- caption: 2-4 short lines with context; end with a question inviting researchers to share whether they
  plan to apply or know similar calls. Max 600 characters, no hashtags, no links.
- hashtags: 6-10 specific hashtags (e.g. #ResearchFunding #GrantOpportunity #Neurorehabilitation).

Call data:
{data}"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "slides": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"heading": {"type": "STRING"}, "body": {"type": "STRING"},
                               "image_prompt": {"type": "STRING"}},
                "required": ["heading", "body", "image_prompt"],
            },
        },
        "eligibility": {"type": "STRING"},
        "coverage": {"type": "STRING"},
        "takeaway": {"type": "STRING"},
        "caption": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["title", "slides", "eligibility", "takeaway", "caption", "hashtags"],
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


def build_post(g, cfg):
    """Prepara il post (stesso formato dei post di metodologia, più i dati chiave) per un bando."""
    data = "\n".join(f"{k}: {g.get(k)}" for k in FIELDS if g.get(k))
    out = content.gemini_json([{"text": PROMPT.format(brand=cfg["brand_name"], data=data)}], SCHEMA, 0.3)
    clip = content._clip
    slides = [{"heading": clip(s.get("heading", ""), 70), "body": clip(s.get("body", ""), 320),
               "image_prompt": clip(s.get("image_prompt", ""), 300)}
              for s in out.get("slides", []) if s.get("heading") and s.get("body")][:2]
    if len(slides) < 2 or not out.get("title"):
        raise RuntimeError(f"Testo del bando incompleto per {g['id']}")

    deadline = _date(g["scadenza"])
    facts = [("Funder", clip(g.get("ente") or g.get("programma") or "", 80)),
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
               f"Official call: {g['url']}\n\n"
               "Details are compiled automatically: always check eligibility, amounts and dates in the official call.")
    tags = ["#" + t.lstrip("#").replace(" ", "") for t in out.get("hashtags", []) if t.strip("# ")]
    return {
        "id": f"grant-{g['id']}"[:60],
        "kind": "grant",
        "grant_id": g["id"],
        "title": clip(out["title"], 90),
        "category": "Funding opportunity",
        "slides": slides,
        "facts": [(k, v) for k, v in facts if v],
        "takeaway": clip(out.get("takeaway", ""), 160) or "Worth a look if this is your research area.",
        "closing_cta": ("Check the official call before applying", "Link in the caption"),
        "caption": caption,
        "hashtags": ["#ResearchFunding", "#GrantOpportunity"] + tags[:10],
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
    print(f"Bandi pubblicabili da GrantFinder: {len(pool)}")
    for g in pool[:3]:   # se Gemini fallisce su un bando prova il successivo
        try:
            return build_post(g, cfg)
        except Exception as e:
            print(f"Post del bando {g['id']} non generato: {e}")
    return None
