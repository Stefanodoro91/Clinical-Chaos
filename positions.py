"""Posizioni accademiche (PhD, post-doc, faculty) in ricerca clinica riabilitativa:
raccolta dai portali di annunci, verifica sull'annuncio originale, pagina pubblica e post settimanale."""

import csv
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from html import escape, unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

import content
import grants

ROOT = Path(__file__).resolve().parent
SOURCES_FILE = ROOT / "positions_sources.csv"
ARCHIVE_FILE = "positions.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/rss+xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en,it;q=0.8"}
STATUS_FILE = "positions_sources_status.json"

# temi: clinica riabilitativa (inglese e italiano)
RX_REHAB = re.compile(
    r"rehabilit|riabilit|physiotherap|fisioterap|physical therap|occupational therap|terapia occupazionale|"
    r"speech (and language )?therap|logoped|stroke|ictus|neurorehab|spinal cord injur|brain injur|"
    r"parkinson|multiple sclerosis|sclerosi multipla|cerebral palsy|amputee|prosthet|orthot|exoskeleton|"
    r"motor (control|recovery|learning)|gait|mobility|disabilit|chronic pain|musculoskeletal|"
    r"sports? (medicine|physiotherapy)|cardiac rehab|pulmonary rehab|geriatric|frailty|falls? prevention|"
    # ricerca clinica e ingegneria clinica/biomedica (focus esteso)
    r"clinical (research|trials?|epidemiolog|science|academic|investigat)|trialist|biostatist|epidemiolog|"
    r"health (services|data|technolog|informatics)|digital health|implementation science|"
    r"biomedical engineer|bioengineer|clinical engineer|rehabilitation engineer|medical (devices?|imaging|physics|technolog)|"
    r"ricerca clinica|ingegneria (biomedica|clinica)", re.I)
# per la pertinenza «media»: termini riabilitativi clinici; «rehabilitation» da solo non basta
# (esclude riabilitazione di detenuti, animali, edifici)
RX_CLINICAL_REHAB = re.compile(
    r"clinical (research|trials?|epidemiolog|investigat)|trialist|biostatist|health services|implementation science|"
    r"biomedical engineer|bioengineer|clinical engineer|rehabilitation engineer|medical (devices?|imaging|physics)|"
    r"physiotherap|fisioterap|physical therap|occupational therap|terapia occupazionale|speech (and language )?therap|"
    r"logoped|neurorehab|neuroriabilit|stroke|ictus|spinal cord injur|brain injur|parkinson|multiple sclerosis|"
    r"sclerosi multipla|cerebral palsy|amputee|prosthet|orthot|exoskeleton|motor (control|recovery|learning)|"
    r"(physical|motor|neuro\w*|clinical|cardiac|pulmonary|musculoskeletal|stroke|geriatric|paediatric|pediatric) rehabilit", re.I)
# tipi di posizione scelti: PhD, post-doc e assegni, faculty
RX_POSITION = re.compile(
    r"\bph\.?d\b|doctoral|doctorate|dottorat|studentship|"
    r"post-?doc|postdoctoral|research fellow|assegn\w* di ricerca|"
    r"professor|lecturer|faculty|tenure|\brtd\b|\brtt\b|ricercat\w* a tempo determinato|professore|"
    r"assistant prof|associate prof|reader in|chair in|research (assistant|associate|scientist|officer)|"
    r"clinical academic|clinical research fellow|clinical fellowship|fellowship|borsa di ricerca|tecnologo", re.I)
TYPES = {"phd": "PhD", "postdoc": "Post-doc", "research": "Research assistant / associate",
         "clinical": "Clinical academic & fellowship", "faculty": "Faculty"}

VERIFY_PROMPT = """You check ONE academic job advertisement for a public list of open positions in clinical
research, clinical and biomedical engineering and rehabilitation. Use ONLY the text of the advertisement
below; never guess.

Return:
- is_open_position: "yes" if it is an open academic position you can apply for, "no" if it is closed,
  expired, a news item, a course, a list of jobs or not a position, "unclear" otherwise.
- position_type: "phd" (PhD, doctoral studentship, dottorato), "postdoc" (post-doctoral position,
  research fellow, assegno di ricerca), "research" (research assistant, research associate, research
  scientist or officer, borsa di ricerca, tecnologo), "clinical" (clinical academic post, clinical research
  fellowship or training fellowship for clinicians and therapists), "faculty" (assistant/associate/full
  professor, lecturer, reader, tenure-track, RTD/RTT), or "other".
- relevance: "high" if the position is about rehabilitation research (rehabilitation, physiotherapy,
  occupational or speech therapy, neurorehabilitation, stroke, spinal cord or brain injury, Parkinson, MS,
  prosthetics, rehabilitation engineering, disability, motor recovery); "medium" if it is clinical research
  in any medical field (clinical trials, studies with patients, clinical epidemiology, biostatistics for
  clinical studies, health services or implementation research) or clinical/biomedical engineering applied
  to patients or health care (medical devices, imaging, digital health), or if rehabilitation is one
  clearly stated part of the role; "low" for basic or preclinical science without patients and for
  non-health roles.
- area: "rehabilitation", "clinical" (clinical research in another medical field) or "engineering"
  (clinical or biomedical engineering), the main one.
- title: the official job title, in English (translate if needed), max 120 characters.
- institution: the university or institute, as named in the text.
- country: the country of the position, in English.
- city: the city, or "".
- deadline: application deadline as YYYY-MM-DD, or "" if not stated.
- deadline_evidence: the sentence or phrase of the text, copied word for word, that states the deadline
  ("" if none).
- summary: 35-60 words in English: research topic, main tasks, key requirements. Factual, no hype.

ADVERTISEMENT ({url}):
{text}"""

VERIFY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "is_open_position": {"type": "STRING", "enum": ["yes", "no", "unclear"]},
        "position_type": {"type": "STRING", "enum": ["phd", "postdoc", "research", "clinical", "faculty", "other"]},
        "relevance": {"type": "STRING", "enum": ["high", "medium", "low"]},
        "area": {"type": "STRING", "enum": ["rehabilitation", "clinical", "engineering"]},
        "title": {"type": "STRING"}, "institution": {"type": "STRING"}, "country": {"type": "STRING"},
        "city": {"type": "STRING"}, "deadline": {"type": "STRING"}, "deadline_evidence": {"type": "STRING"},
        "summary": {"type": "STRING"},
    },
    "required": ["is_open_position", "position_type", "relevance", "area", "title", "institution", "country", "city",
                 "deadline", "deadline_evidence", "summary"],
}


# ---------------------------------------------------------------- archivio
def load_archive():
    try:
        return json.load(open(ROOT / ARCHIVE_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _id(url):
    return "POS-" + hashlib.sha1(url.split("#")[0].encode()).hexdigest()[:12]


def _date(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- raccolta
def read_sources():
    with SOURCES_FILE.open(encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f, delimiter=";") if (r.get("url") or "").startswith("http")]


def _rss_items(xml_text):
    root = ET.fromstring(xml_text.encode() if isinstance(xml_text, str) else xml_text)
    out = []
    for it in root.iter():
        if it.tag.split("}")[-1] not in ("item", "entry"):
            continue
        get = lambda name: next((c for c in it if c.tag.split("}")[-1] == name), None)
        t, l, d = get("title"), get("link"), get("description") or get("summary")
        link = (l.text or l.get("href") or "").strip() if l is not None else ""
        out.append({"title": unescape((t.text or "").strip()) if t is not None else "", "url": link,
                    "snippet": grants.html_to_text(d.text or "")[:600] if d is not None else ""})
    return out


def _html_items(html, base):
    """Link degli annunci in una pagina di risultati: il testo del link deve sembrare una posizione."""
    out, seen = [], set()
    host = urlparse(base).netloc
    for m in re.finditer(r'<a\s[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', html, re.I | re.S):
        href, text = m.group(1), grants.html_to_text(m.group(2))
        url = urljoin(base, unescape(href))
        if (len(text) < 12 or len(text) > 220 or url in seen or urlparse(url).netloc != host
                or not RX_POSITION.search(text)):
            continue
        seen.add(url)
        out.append({"title": text, "url": url, "snippet": ""})
    return out[:80]


def collect(sources=None):
    """Annunci candidati da tutte le fonti: titolo con un tipo di posizione e un tema di riabilitazione
    (nel titolo o nell'estratto). Restituisce (candidati, diagnostica per fonte)."""
    from urllib.parse import unquote
    found, report = {}, []
    for src in sources or read_sources():
        try:
            r = requests.get(src["url"], headers=HEADERS, timeout=45)
            r.raise_for_status()
            text = r.text
            head = text.lstrip()[:500].lower()
            if head.startswith("<?xml") or "<rss" in head or "<feed" in head:
                items = _rss_items(text)
            else:   # anche le fonti «rss» che rispondono con una pagina HTML
                items = _html_items(text, src["url"])
            # se la fonte è già una ricerca per tema (es. «rehabilitation»), basta che sia una posizione:
            # la pertinenza la controlla poi Gemini sull'annuncio
            topic_search = bool(RX_REHAB.search(unquote(src["url"])))
            kept = 0
            for it in items:
                blob = f"{it['title']} {it['snippet']}"
                if it["url"] and RX_POSITION.search(blob) and (topic_search or RX_REHAB.search(blob)):
                    found.setdefault(_id(it["url"]), dict(it, source=src["nome"]))
                    kept += 1
            report.append((src["nome"], len(items), kept, ""))
        except Exception as e:
            report.append((src["nome"], 0, 0, str(e)[:120]))
        time.sleep(1)
    return found, report


# ---------------------------------------------------------------- verifica
def verify(item):
    r = requests.get(item["url"], headers=HEADERS, timeout=45)
    r.raise_for_status()
    text = grants.html_to_text(r.text)
    if len(text) < 300:
        raise RuntimeError(f"annuncio troppo breve ({len(text)} caratteri)")
    out = content.gemini_json([{"text": VERIFY_PROMPT.format(url=item["url"], text=text[:40000])}], VERIFY_SCHEMA, 0.1)
    ev = (out.get("deadline_evidence") or "").strip()
    deadline = out.get("deadline") if (_date(out.get("deadline")) and ev and grants._simple(ev) in grants._simple(text)) else ""
    return {
        "status": "ok", "checked": date.today().isoformat(), "first_seen": date.today().isoformat(),
        "url": item["url"], "source": item.get("source", ""),
        "is_open": out.get("is_open_position", "unclear"), "type": out.get("position_type", "other"),
        "relevance": out.get("relevance", "low"), "area": out.get("area", "rehabilitation"),
        "title": content._clip(out.get("title") or item["title"], 140),
        "institution": content._clip(out.get("institution", ""), 120),
        "country": content._clip(out.get("country", ""), 60), "city": content._clip(out.get("city", ""), 60),
        "deadline": deadline, "deadline_evidence": content._clip(ev, 200) if deadline else "",
        "summary": content._clip(out.get("summary", ""), 500),
    }


def refresh(archive, limit=25, today=None):
    """Raccoglie gli annunci nuovi e ne verifica fino a `limit`. Restituisce la diagnostica delle fonti."""
    today = today or date.today()
    found, report = collect()
    status = {name: {"letti": n, "pertinenti": kept, "errore": err, "data": today.isoformat()} for name, n, kept, err in report}
    json.dump(status, open(ROOT / STATUS_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    ok = sum(1 for x in status.values() if not x["errore"])
    print(f"::notice title=Fonti posizioni::{ok} fonti su {len(status)} rispondono; {len(found)} annunci candidati (dettagli in {STATUS_FILE})")
    todo = [(k, v) for k, v in found.items() if k not in archive]
    done = 0
    for k, item in todo[:limit]:
        try:
            archive[k] = verify(item)
            v = archive[k]
            print(f"::notice title=Posizione verificata::{v['type']} | {v['relevance']} | {v['title'][:70]} | {v['country']} | {v['deadline'] or 'scadenza non indicata'}")
        except Exception as e:
            if "Gemini non disponibile" in str(e):
                print("::warning title=Quota Gemini esaurita::verifica delle posizioni sospesa fino al prossimo run")
                break
            archive[k] = {"status": "failed", "checked": today.isoformat(), "url": item["url"],
                          "source": item.get("source", ""), "error": str(e)[:200]}
        done += 1
        time.sleep(7)
    # pulizia: via le posizioni scadute da più di 30 giorni e gli errori vecchi
    for k in list(archive):
        v = archive[k]
        d = _date(v.get("deadline"))
        old = _date(v.get("first_seen") or v.get("checked")) or today
        if (d and d < today - timedelta(days=30)) or (v.get("status") == "failed" and (today - old).days > 30):
            del archive[k]
    return report


def active(archive, today=None):
    """Posizioni da mostrare: verificate, aperte, pertinenti, tipo scelto; scadenza futura,
    oppure non indicata e annuncio visto da meno di 45 giorni."""
    today = today or date.today()
    out = []
    for k, v in archive.items():
        if v.get("status") != "ok" or v.get("is_open") == "no" or v.get("relevance") not in ("high", "medium") \
                or v.get("type") not in TYPES:
            continue
        # pertinenza «media» solo se un termine riabilitativo compare davvero nel titolo o nella descrizione
        if (v.get("relevance") == "medium" and v.get("area") not in ("clinical", "engineering")
                and not RX_CLINICAL_REHAB.search(f"{v.get('title', '')} {v.get('summary', '')}")):
            continue
        d = _date(v.get("deadline"))
        seen = _date(v.get("first_seen")) or today
        if (d and d >= today) or (not d and (today - seen).days <= 45):
            out.append((k, v, d))
    # la stessa posizione può arrivare da più siti: si tiene una sola voce (stesso ente e titolo quasi uguale)
    unique = []
    for e in sorted(out, key=lambda e: (e[1].get("relevance") != "high", e[0])):
        if not any(_same_job(e[1], u[1]) for u in unique):
            unique.append(e)
    return unique


def _same_job(a, b):
    from difflib import SequenceMatcher
    norm = lambda x: " ".join(re.sub(r"[^a-z0-9]+", " ", (x or "").lower()).split())
    same_place = norm(a.get("institution")) == norm(b.get("institution")) or norm(a.get("country")) == norm(b.get("country"))
    return same_place and SequenceMatcher(None, norm(a.get("title")), norm(b.get("title"))).ratio() >= 0.85


def region_of(v):
    country = v.get("country") or ""
    for r, rx in grants.REGION_WORDS.items():
        if re.search(rx, country, re.I):
            return r
    return grants.REGIONS[0] if not country else "Other countries"


# ---------------------------------------------------------------- pagina
PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Academic positions · {brand}</title>
<meta name="description" content="Open PhD, post-doc and faculty positions in clinical research, clinical engineering and rehabilitation worldwide, checked against the original advertisement.">
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
  .switch {{ display: inline-block; color: var(--text); text-decoration: none; font-size: 14px; font-weight: 600;
            border: 1px solid var(--muted); border-radius: 999px; padding: 7px 14px; margin-bottom: 18px; }}
  .badge {{ display: inline-block; background: var(--accent); color: var(--bg); font-weight: 800; font-size: 13px;
           letter-spacing: .06em; padding: 6px 14px; border-radius: 999px; }}
  h1 {{ font-size: 30px; font-weight: 800; margin: 14px 0 6px; line-height: 1.15; }}
  .intro {{ color: var(--soft); margin: 0 0 18px; font-size: 15px; }}
  nav.jump {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 26px; }}
  nav.jump a {{ color: var(--text); text-decoration: none; border: 1px solid var(--muted); border-radius: 999px;
               padding: 8px 14px; font-size: 14px; font-weight: 600; }}
  nav.jump a b {{ color: var(--accent); }}
  section > h2 {{ font-size: 23px; font-weight: 800; margin: 34px 0 4px; }}
  h3.region {{ font-size: 15px; letter-spacing: .04em; text-transform: uppercase; color: var(--accent);
              margin: 24px 0 10px; display: flex; justify-content: space-between; }}
  h3.region span {{ color: var(--muted); font-weight: 600; }}
  .job {{ background: var(--card); border-radius: 18px; padding: 18px 20px; margin-bottom: 12px; border-left: 4px solid var(--accent); }}
  .inst {{ color: var(--soft); font-size: 13px; font-weight: 600; margin-bottom: 6px; }}
  .tag {{ display: inline-block; background: var(--teal); color: var(--bg); font-size: 11px; font-weight: 800;
         letter-spacing: .05em; padding: 2px 8px; border-radius: 999px; margin-left: 6px; vertical-align: 1px; }}
  .job h4 {{ font-size: 17px; margin: 0 0 8px; line-height: 1.3; }}
  .job h4 a {{ color: inherit; text-decoration: none; }}
  .job h4 a:hover {{ text-decoration: underline; }}
  .btns {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .summary {{ color: var(--soft); font-size: 14px; margin: 0 0 12px; }}
  .row {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between; }}
  .deadline {{ font-size: 14px; color: var(--soft); }}
  .deadline b {{ color: var(--text); font-size: 15px; }}
  .soon {{ color: var(--accent); font-weight: 800; font-size: 12px; margin-left: 6px; }}
  a.btn {{ background: var(--accent); color: var(--bg); text-decoration: none; font-weight: 800; font-size: 14px;
           padding: 10px 16px; border-radius: 12px; }}
  a.btn:focus-visible, nav.jump a:focus-visible, .switch:focus-visible {{ outline: 3px solid var(--text); outline-offset: 2px; }}
  .empty {{ color: var(--soft); background: var(--card); border-radius: 18px; padding: 22px; }}
  form.filters {{ background: var(--card); border-radius: 18px; padding: 16px; margin: 0 0 8px; display: grid; gap: 10px;
                 grid-template-columns: 1fr 1fr 1fr; }}
  form.filters label {{ display: grid; gap: 4px; font-size: 12px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
                       color: var(--muted); }}
  form.filters label.wide {{ grid-column: 1 / -1; }}
  form.filters input, form.filters select {{ font: 500 15px Inter, system-ui, sans-serif; color: var(--text); background: var(--bg);
                       border: 1px solid var(--muted); border-radius: 10px; padding: 10px 12px; width: 100%; }}
  form.filters .status {{ grid-column: 1 / -1; display: flex; justify-content: space-between; align-items: center; gap: 10px;
                         font-size: 14px; color: var(--soft); }}
  form.filters button {{ background: transparent; color: var(--text); border: 1px solid var(--muted); border-radius: 999px;
                        padding: 6px 12px; font: 600 13px Inter, system-ui, sans-serif; cursor: pointer; }}
  @media (max-width: 560px) {{ form.filters {{ grid-template-columns: 1fr; }} }}
  .nomatch {{ color: var(--soft); background: var(--card); border-radius: 18px; padding: 18px 20px; font-size: 15px; }}
  [hidden] {{ display: none !important; }}
  footer {{ color: var(--muted); font-size: 13px; margin-top: 36px; }}
  footer a {{ color: var(--teal); }}
</style>
</head>
<body>
<div class="bar"></div>
<main>
  <a class="switch" href="index.html">&larr; Home</a> &nbsp; <a class="switch" href="calls.html">Research funding calls &rarr;</a><br>
  <span class="badge">ACADEMIC POSITIONS</span>
  <h1>Positions in clinical research, engineering and rehabilitation</h1>
  <p class="intro">Open PhD, post-doc and faculty positions in clinical research, clinical and biomedical engineering and
  rehabilitation, from universities and research institutes worldwide, checked against the original advertisement.
  Grouped by position and region, sorted by deadline: use the filters.</p>
  <nav class="jump">{nav}</nav>
{filters}
{sections}
  <footer>
    Positions collected from academic job portals and checked automatically: always read the full advertisement
    before applying.<br>
    Updated {updated} · <a href="https://www.instagram.com/{ig}/">{handle} on Instagram</a>
  </footer>
</main>
</body>
</html>
"""


def _fmt(d):
    return f"{d.day} {d.strftime('%b %Y')}"


def filters_form(n):
    """Filtri della pagina posizioni (parola chiave, dove, area, scadenza): stesso script della pagina bandi."""
    regions = "".join(f'<option value="{escape(r, quote=True)}">{escape(r)}</option>'
                      for r in grants.REGIONS[1:] + ["Other countries"])
    areas = "".join(f'<option value="{k}">{v}</option>' for k, v in
                    (("rehabilitation", "Rehabilitation"), ("clinical", "Clinical research"),
                     ("engineering", "Clinical &amp; biomedical engineering")))
    return f"""  <form class="filters" role="search" aria-label="Filter positions" data-noun="open positions" onsubmit="return false">
    <label class="wide">Search<input type="search" name="q" placeholder="Keyword, institution, city or country (e.g. stroke, trials, Japan)" autocomplete="off"></label>
    <label>Location<select name="where"><option value="">Anywhere</option><option value="italy">Italy</option>{regions}</select></label>
    <label>Area<select name="area"><option value="">All areas</option>{areas}</select></label>
    <label>Deadline<select name="time"><option value="">Any deadline</option><option value="lt30">Closing within 30 days</option>
      <option value="ge30">At least 30 days left</option></select></label>
    <div class="status"><span class="count" aria-live="polite">{n} open positions</span><button type="reset" hidden>Clear filters</button></div>
  </form>"""


def build_page(archive, posted, cfg, today=None):
    today = today or date.today()
    featured = {pid for p in posted if p.get("kind") == "positions" for pid in p.get("position_ids", [])}
    entries = active(archive, today)
    key = lambda e: (e[2] is None, e[2] or date.max)
    nav, sections = [], []
    for t, label in TYPES.items():
        items = sorted([e for e in entries if e[1]["type"] == t], key=key)
        nav.append(f'<a href="#{t}">{label} <b>{len(items)}</b></a>')
        parts = [f'  <section id="{t}">', f'    <h2>{label} positions</h2>']
        if not items:
            parts.append('    <p class="empty">No open positions of this type right now.</p>')
        regions = {}
        for e in items:
            regions.setdefault(region_of(e[1]), []).append(e)
        order = grants.REGIONS + ["Other countries"]
        for r in sorted(regions, key=lambda r: order.index(r) if r in order else 99):
            parts.append(f'    <div class="grp">\n    <h3 class="region">{escape(r)} <span>{len(regions[r])}</span></h3>')
            for k, v, d in regions[r]:
                if d:
                    soon = '<span class="soon">CLOSING SOON</span>' if (d - today).days <= 14 else ""
                    when = f"Deadline <b>{_fmt(d)}</b>{soon}"
                else:
                    when = "Deadline <b>see advertisement</b>"
                place = ", ".join(x for x in (v.get("institution"), v.get("city"), v.get("country")) if x)
                tag = '<span class="tag">ON INSTAGRAM</span>' if k in featured else ""
                page = job_slug(k, v)
                share = grants.share_button(grants.site_url(cfg, "jobs/" + page),
                                            f"{v['title']} – {v.get('institution') or 'academic position'}"
                                            + (f" (deadline {_fmt(d)})" if d else ""))
                words = " ".join(x for x in (v.get("title"), place, v.get("summary"), TYPES.get(v.get("type"))) if x).lower()
                attrs = (f'data-region="{escape(r, quote=True)}" data-italy="{"yes" if (v.get("country") or "").lower() == "italy" else "no"}" '
                         f'data-area="{escape(v.get("area") or "rehabilitation", quote=True)}" data-deadline="{d.isoformat() if d else ""}" '
                         f'data-text="{escape(words, quote=True)}"')
                parts.append(f"""    <article class="job" id="{k}" {attrs}>
      <div class="inst">{escape(place)}{tag}</div>
      <h4><a href="jobs/{page}.html">{escape(v["title"])}</a></h4>
      {f'<p class="summary">{escape(v["summary"])}</p>' if v.get("summary") else ""}
      <div class="row">
        <div class="deadline">{when}</div>
        <div class="btns">{share}<a class="btn" href="{escape(v["url"], quote=True)}" target="_blank" rel="noopener">Advertisement &rarr;</a></div>
      </div>
    </article>""")
            parts.append("    </div>")
        parts.append("  </section>")
        sections.append("\n".join(parts))
    c = cfg["colors"]
    return PAGE.format(brand=escape(cfg["brand_name"]), handle=escape(cfg["handle"]), ig=cfg["handle"].lstrip("@"),
                       bg=c["background"], muted=c["muted"], soft=c["muted_text"], teal=c["accent"],
                       accent=cfg.get("positions_accent", "#A78BFA"), nav="".join(nav),
                       sections="\n".join(sections), updated=_fmt(today), filters=filters_form(len(entries)),
                       og=grants.og_tags(cfg, f"Academic positions in clinical research, engineering and rehabilitation · {cfg['brand_name']}",
                                         "Open PhD, post-doc and faculty positions in clinical research, clinical engineering and rehabilitation, "
                                         "checked against the original advertisement.", "positions"))


# ---------------------------------------------------------------- una pagina per posizione (Google Jobs)
JOB_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · {place_short} · {brand}</title>
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
  h1 {{ font-size: 28px; font-weight: 800; margin: 14px 0 8px; line-height: 1.2; }}
  .inst {{ color: var(--soft); font-size: 15px; font-weight: 600; margin: 0 0 20px; }}
  .job {{ background: var(--card); border-radius: 18px; padding: 20px; border-left: 4px solid var(--accent); }}
  dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; margin: 0 0 16px; font-size: 15px; }}
  dt {{ color: var(--muted); font-weight: 600; }}
  dd {{ margin: 0; }}
  .summary {{ color: var(--soft); font-size: 15px; margin: 0 0 18px; }}
  .soon {{ color: var(--accent); font-weight: 800; font-size: 12px; margin-left: 6px; }}
  .btns {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  a.btn {{ background: var(--accent); color: var(--bg); text-decoration: none; font-weight: 800; font-size: 15px;
           padding: 11px 18px; border-radius: 12px; }}
  a.btn:focus-visible, .switch:focus-visible {{ outline: 3px solid var(--text); outline-offset: 2px; }}
  footer {{ color: var(--muted); font-size: 13px; margin-top: 30px; }}
  footer a {{ color: var(--teal); }}
</style>
</head>
<body>
<div class="bar"></div>
<main>
  <a class="switch" href="../positions.html">&larr; All academic positions</a><a class="switch" href="../calls.html">Funding calls &rarr;</a><br>
  <span class="badge">{type_label}</span>
  <h1>{title}</h1>
  <p class="inst">{place}</p>
  <article class="job">
    <dl>
      <dt>Position</dt><dd>{type_label}</dd>
      <dt>Institution</dt><dd>{institution}</dd>
      <dt>Location</dt><dd>{location}</dd>
      <dt>Deadline</dt><dd>{deadline}</dd>
    </dl>
    {summary}
    <div class="btns">{share}<a class="btn" href="{url}" target="_blank" rel="noopener">Read the advertisement and apply &rarr;</a></div>
  </article>
  <footer>
    Found on {source} and checked automatically against the original advertisement on {checked}: always read the full
    advertisement before applying; the employer's page is the only official source.<br>
    <a href="../index.html">{brand}</a> · <a href="https://www.instagram.com/{ig}/">{handle} on Instagram</a>
  </footer>
</main>
</body>
</html>
"""


def job_slug(k, v):
    words = re.sub(r"[^a-z0-9]+", "-", unescape(v.get("title") or "position").lower()).strip("-")
    return f"{words[:60].rstrip('-')}-{k.split('-')[-1][:8]}"


def job_jsonld(k, v, d):
    """Dati strutturati JobPosting (schema.org) letti da Google per Google Jobs; None se mancano i campi obbligatori."""
    if not (v.get("title") and v.get("institution") and v.get("country") and v.get("summary")):
        return None
    address = {"@type": "PostalAddress", "addressCountry": v["country"]}
    if v.get("city"):
        address["addressLocality"] = v["city"]
    data = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": v["title"],
        "description": f"<p>{escape(v['summary'])}</p><p>Position type: {escape(TYPES.get(v.get('type'), 'Academic position'))}.</p>"
                       f"<p>Read the full advertisement and apply at: {escape(v['url'])}</p>",
        "datePosted": v.get("first_seen") or v.get("checked"),
        "employmentType": "OTHER" if v.get("type") == "phd" else "FULL_TIME",
        "hiringOrganization": {"@type": "Organization", "name": v["institution"]},
        "jobLocation": {"@type": "Place", "address": address},
        "identifier": {"@type": "PropertyValue", "name": v["institution"], "value": k},
        "directApply": False,
    }
    if d:
        data["validThrough"] = f"{d.isoformat()}T23:59:59"
    if v.get("type") == "phd":
        data["educationRequirements"] = {"@type": "EducationalOccupationalCredential", "credentialCategory": "postgraduate degree"}
    text = json.dumps(data, ensure_ascii=False, indent=1).replace("</", "<\\/")
    return f'<script type="application/ld+json">\n{text}\n</script>'


def job_pages(archive, cfg, today=None):
    """{nome file: html} con una pagina per ogni posizione aperta in pagina."""
    today = today or date.today()
    c = cfg["colors"]
    out = {}
    for k, v, d in active(archive, today):
        slug = job_slug(k, v)
        title = v["title"]
        loc = ", ".join(x for x in (v.get("city"), v.get("country")) if x) or "see advertisement"
        place = ", ".join(x for x in (v.get("institution"), loc if loc != "see advertisement" else "") if x)
        if d:
            soon = '<span class="soon">CLOSING SOON</span>' if (d - today).days <= 14 else ""
            deadline = f"{_fmt(d)}{soon}"
        else:
            deadline = "see advertisement"
        summary = v.get("summary") or ""
        desc = (summary[:150].rsplit(" ", 1)[0] + "…") if len(summary) > 155 else summary or f"{title} at {place}"
        share_title = f"{title} – {v.get('institution') or 'academic position'}" + (f" (deadline {_fmt(d)})" if d else "")
        out[slug + ".html"] = JOB_PAGE.format(
            title=escape(title), place_short=escape(v.get("institution") or loc), brand=escape(cfg["brand_name"]),
            description=escape(desc, quote=True),
            og=grants.og_tags(cfg, f"{title} · {v.get('institution') or loc}", desc, "jobs/" + slug),
            jsonld=job_jsonld(k, v, d) or "", bg=c["background"], muted=c["muted"], soft=c["muted_text"], teal=c["accent"],
            accent=cfg.get("positions_accent", "#A78BFA"), type_label=escape(TYPES.get(v.get("type"), "Academic position")),
            place=escape(place), institution=escape(v.get("institution") or "see advertisement"), location=escape(loc),
            deadline=deadline, summary=f'<p class="summary">{escape(summary)}</p>' if summary else "",
            share=grants.share_button(grants.site_url(cfg, "jobs/" + slug), share_title),
            url=escape(v["url"], quote=True), source=escape(re.sub(r"\s+[–-]\s+.*$", "", v.get("source") or "an academic job portal")),
            checked=_fmt(_date(v.get("checked")) or today), ig=cfg["handle"].lstrip("@"), handle=escape(cfg["handle"]))
    return out


# ---------------------------------------------------------------- post settimanale
def weekly_post(archive, posted, cfg, today=None):
    """Carosello con 4-6 posizioni mai pubblicate, varie per tipo e Paese, con almeno 10 giorni prima della scadenza."""
    today = today or date.today()
    done = {pid for p in posted if p.get("kind") == "positions" for pid in p.get("position_ids", [])}
    done_jobs = [archive[pid] for pid in done if pid in archive]
    pool = [(k, v, d) for k, v, d in active(archive, today)
            if k not in done and not any(_same_job(v, j) for j in done_jobs)       # mai la stessa posizione due volte
            and (d is None or d >= today + timedelta(days=int(cfg.get("positions_min_days_left", 10))))]
    rel = {"high": 0, "medium": 1}
    pool.sort(key=lambda e: (rel[e[1]["relevance"]], e[2] is None, e[2] or date.max))
    picked, used_types, used_countries = [], {}, {}
    for e in pool:   # varietà: al massimo 3 per tipo e 2 per Paese
        t, ctry = e[1]["type"], e[1].get("country", "")
        if used_types.get(t, 0) >= 3 or used_countries.get(ctry, 0) >= 2:
            continue
        picked.append(e)
        used_types[t] = used_types.get(t, 0) + 1
        used_countries[ctry] = used_countries.get(ctry, 0) + 1
        if len(picked) == int(cfg.get("positions_per_post", 6)):
            break
    if len(picked) < int(cfg.get("positions_min_per_post", 3)):
        return None
    week = f"{today.day} {today.strftime('%b %Y')}"
    jobs = [{"type": TYPES[v["type"]], "title": v["title"], "institution": v.get("institution", ""),
             "place": ", ".join(x for x in (v.get("city"), v.get("country")) if x),
             "deadline": _fmt(d) if d else "See advertisement", "summary": v.get("summary", ""), "url": v["url"]}
            for k, v, d in picked]
    lines = "\n".join(f"• {j['type']} – {j['title']} ({j['institution']}{', ' + j['place'] if j['place'] else ''}). "
                      f"Deadline: {j['deadline']}. {j['url']}" for j in jobs)
    caption = (f"New academic positions in clinical research, engineering and rehabilitation – week of {week}.\n\n{lines}\n\n"
               "All open positions, by type and region: link in bio.\n"
               "Positions are collected and checked automatically: always read the full advertisement before applying.\n"
               "Know someone who should apply? Share this post with them.")
    return {
        "id": f"positions-{today.isoformat()}", "kind": "positions",
        "position_ids": [k for k, v, d in picked],
        "title": (f"{len(jobs)} open academic positions this week" if len(jobs) > 1
                  else "Open academic position this week"),
        "title_highlight": "academic positions" if len(jobs) > 1 else "academic position",
        "category": "Academic positions", "week": week, "jobs": jobs, "slides": [],
        "takeaway": "New PhD, post-doc and faculty positions every week.",
        "takeaway_highlight": "every week",
        "closing_cta": ("Read the full advertisement before applying", "All positions: link in bio"),
        "caption": caption, "hashtags": ["#AcademicJobs", "#PhDPosition", "#Postdoc", "#FacultyJobs",
                                         "#RehabilitationResearch", "#Physiotherapy", "#Neurorehabilitation"],
        "source": "Academic positions",
    }
