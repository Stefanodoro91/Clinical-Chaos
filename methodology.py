"""Archivio pubblico dei post di metodologia: una pagina con tutti i caroselli pubblicati, i punti chiave e le reference."""

import json
import re
from datetime import date
from html import escape
from pathlib import Path

from PIL import Image

import content
import grants

ROOT = Path(__file__).resolve().parent
ARCHIVE_FILE = ROOT / "methodology.json"
THUMBS = ROOT / "docs" / "methodology"


def load():
    try:
        return json.load(open(ARCHIVE_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(data):
    ARCHIVE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def record(post, day, images_dir):
    """Voce d'archivio da un post di metodologia appena pubblicato (o recuperato dalla coda)."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in post["id"])
    cover = Path(images_dir) / f"{day}-{safe}" / "slide-1.jpg"
    return {"id": post["id"], "date": day, "title": post.get("title", ""), "category": post.get("category", "Research methods"),
            "takeaway": post.get("takeaway", ""),
            "points": [{"heading": s.get("heading", ""), "body": s.get("body", ""), "source": s.get("source", "")}
                       for s in post.get("slides", []) if s.get("heading")],
            "references": post.get("references", []), "cover": cover.relative_to(ROOT).as_posix() if cover.exists() else ""}


def add(post, day, images_dir):
    data = load()
    data[post["id"]] = record(post, day, images_dir)
    save(data)
    return data


def _slug(t):
    return re.sub(r"[^a-z0-9]+", "-", (t or "").lower()).strip("-")


PAGE = """<!doctype html>
<html lang="en">
<head>
<!-- Google Analytics 4 -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-6ZCXVHNT2"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-6ZCXVHNT2');
</script>
<!-- End Google Analytics 4 -->
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Clinical research methodology library: study design, reporting &amp; appraisal · {brand}</title>
<meta name="description" content="Practical clinical research methodology in short carousels: study design, statistics, reporting guidelines and critical appraisal, with key points and references for every topic.">
{og}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
  :root {{ --bg: {bg}; --card: #15304A; --text: #FFFFFF; --muted: {muted}; --soft: {soft}; --accent: {teal}; --teal: {teal}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text); font-family: Inter, system-ui, sans-serif; line-height: 1.5; }}
  .bar {{ height: 6px; background: var(--accent); }}
  main {{ max-width: 760px; margin: 0 auto; padding: 28px 16px 48px; }}
  .switch {{ display: inline-block; color: var(--text); text-decoration: none; font-size: 14px; font-weight: 600;
            border: 1px solid var(--muted); border-radius: 999px; padding: 7px 14px; margin: 0 6px 18px 0; }}
  .badge {{ display: inline-block; background: var(--accent); color: var(--bg); font-weight: 800; font-size: 13px;
           letter-spacing: .06em; padding: 6px 14px; border-radius: 999px; }}
  h1 {{ font-size: 30px; font-weight: 800; margin: 14px 0 6px; line-height: 1.15; }}
  .intro {{ color: var(--soft); margin: 0 0 18px; font-size: 15px; }}
  section > h2 {{ font-size: 21px; font-weight: 800; margin: 30px 0 12px; color: var(--accent); }}
  .method {{ background: var(--card); border-radius: 18px; padding: 16px; margin-bottom: 14px; display: grid;
            grid-template-columns: 264px 1fr; gap: 18px; }}
  .slides {{ position: relative; }}
  .strip {{ display: flex; overflow-x: auto; scroll-snap-type: x mandatory; -webkit-overflow-scrolling: touch;
           border-radius: 10px; scrollbar-width: none; background: var(--bg); }}
  .strip::-webkit-scrollbar {{ display: none; }}
  .strip img {{ flex: 0 0 100%; width: 100%; height: auto; aspect-ratio: 4/5; object-fit: cover; scroll-snap-align: start; display: block; }}
  .nav {{ display: flex; justify-content: space-between; align-items: center; margin-top: 6px; font-size: 13px; color: var(--muted); font-weight: 600; }}
  .nav button {{ background: transparent; color: var(--text); border: 1px solid var(--muted); border-radius: 999px; width: 34px; height: 34px;
                font: 700 16px Inter, system-ui, sans-serif; cursor: pointer; }}
  .nav button:disabled {{ opacity: .35; cursor: default; }}
  .method h3 {{ font-size: 18px; margin: 0 0 6px; line-height: 1.3; }}
  .date {{ color: var(--muted); font-size: 13px; font-weight: 600; margin-bottom: 6px; }}
  .take {{ color: var(--soft); font-size: 15px; margin: 0 0 10px; }}
  details {{ font-size: 14px; color: var(--soft); }}
  details summary {{ cursor: pointer; color: var(--accent); font-weight: 700; }}
  details h4 {{ color: var(--text); font-size: 15px; margin: 12px 0 2px; }}
  details p {{ margin: 0 0 6px; }}
  .refs {{ border-top: 1px solid #2A4058; margin-top: 12px; padding-top: 8px; font-size: 13px; }}
  @media (max-width: 520px) {{ .method {{ grid-template-columns: 1fr; }} .slides {{ max-width: 420px; }} }}
  form.filters {{ background: var(--card); border-radius: 18px; padding: 16px; margin: 0 0 8px; display: grid; gap: 10px;
                 grid-template-columns: 2fr 1fr; }}
  form.filters label {{ display: grid; gap: 4px; font-size: 12px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
                       color: var(--muted); }}
  form.filters input, form.filters select {{ font: 500 15px Inter, system-ui, sans-serif; color: var(--text); background: var(--bg);
                       border: 1px solid var(--muted); border-radius: 10px; padding: 10px 12px; width: 100%; }}
  form.filters .status {{ grid-column: 1 / -1; display: flex; justify-content: space-between; align-items: center; gap: 10px;
                         font-size: 14px; color: var(--soft); }}
  form.filters button {{ background: transparent; color: var(--text); border: 1px solid var(--muted); border-radius: 999px;
                        padding: 6px 12px; font: 600 13px Inter, system-ui, sans-serif; cursor: pointer; }}
  @media (max-width: 520px) {{ form.filters {{ grid-template-columns: 1fr; }} }}
  .nomatch {{ color: var(--soft); background: var(--card); border-radius: 18px; padding: 18px 20px; font-size: 15px; }}
  .tools {{ margin: 6px 0 4px; }}
  .tools h2 {{ font-size: 21px; font-weight: 800; margin: 26px 0 4px; color: var(--accent); }}
  .tools .sub {{ color: var(--soft); font-size: 14px; margin: 0 0 12px; }}
  .tools .row {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
  .tools .tool {{ display: block; background: var(--card); border-radius: 16px; padding: 16px; color: var(--text); }}
  .tools ul {{ list-style: none; margin: 8px 0 0; padding: 0; }}
  .tools li a {{ display: flex; justify-content: space-between; gap: 8px; padding: 7px 0; border-top: 1px solid #2E2E2E;
                text-decoration: none; color: var(--text); font-size: 14px; }}
  .tools li a b {{ color: var(--accent); font-weight: 700; }}
  .tools li a span {{ color: var(--soft); font-size: 12px; text-align: right; }}
  .tools li a:hover b, .tools li a:focus-visible b {{ text-decoration: underline; }}
  .tools .k {{ font-size: 12px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: var(--accent); }}
  .tools .t {{ display: block; font-size: 17px; font-weight: 800; margin: 4px 0; line-height: 1.25; }}
  .tools .d {{ display: block; font-size: 13px; color: var(--soft); }}
  @media (max-width: 620px) {{ .tools .row {{ grid-template-columns: 1fr; }} }}
  [hidden] {{ display: none !important; }}
  footer {{ color: var(--muted); font-size: 13px; margin-top: 36px; }}
  footer a {{ color: var(--teal); }}
</style>
</head>
<body>
<div class="bar"></div>
<main>
  {lockup}
  <a class="switch" href="index.html">&larr; Home</a><a class="switch" href="calls.html">Funding calls &rarr;</a><a class="switch" href="positions.html">Academic positions &rarr;</a><a class="switch" href="trials.html">Find your trial &rarr;</a><a class="switch" href="science.html">Latest Science &rarr;</a><a class="switch" href="rss.html">RSS &rarr;</a><br>
  <span class="badge">DESIGN, REPORTING &amp; APPRAISAL</span>
  <h1>Clinical research methodology, made practical</h1>
  <p class="intro">Every methodology carousel we have published: swipe through the slides here, no Instagram account needed.
  Key points and references under each one. New topics every day.</p>
  <form class="filters" role="search" aria-label="Filter topics" data-noun="topics" onsubmit="return false">
    <label>Search<input type="search" name="q" placeholder="Keyword (e.g. blinding, p-value, regression)" autocomplete="off"></label>
    <label>Topic<select name="area"><option value="">All topics</option>{cat_opts}</select></label>
    <div class="status"><span class="count" aria-live="polite">{n} {topics_word}</span><button type="reset" hidden>Clear filters</button></div>
  </form>
{tools}
{sections}
  <footer>
    Educational content for researchers and health professionals; always refer to the original references.<br>
    Updated {updated} · <a href="https://www.instagram.com/{ig}/">{handle} on Instagram</a>
  </footer>
</main>
<script>
(function () {{
  var all = document.querySelectorAll(".slides");
  for (var i = 0; i < all.length; i++) (function (box) {{
    var strip = box.querySelector(".strip"), n = strip.children.length;
    var prev = box.querySelector(".prev"), next = box.querySelector(".next"), pos = box.querySelector(".pos");
    if (!prev || !next || !pos) return;
    function cur() {{ return Math.round(strip.scrollLeft / Math.max(1, strip.clientWidth)); }}
    function show() {{ var k = cur(); pos.textContent = (k + 1) + " / " + n; prev.disabled = k <= 0; next.disabled = k >= n - 1; }}
    function go(d) {{ strip.scrollTo ? strip.scrollTo({{ left: (cur() + d) * strip.clientWidth, behavior: "smooth" }}) : (strip.scrollLeft = (cur() + d) * strip.clientWidth); }}
    prev.onclick = function () {{ go(-1); }}; next.onclick = function () {{ go(1); }};
    strip.addEventListener("scroll", function () {{ window.requestAnimationFrame(show); }});
    show();
  }})(all[i]);
}})();
</script>
</body>
</html>
"""


TOOLS = [   # strumenti ufficiali per disegno di studio: (etichetta, titolo, [(disegno, strumento, url)])
    ("Protocol draft", "Draft your protocol", [
        ("Randomised trials", "SPIRIT", "https://www.spirit-statement.org/"),
        ("Systematic reviews", "PRISMA-P", "https://www.prisma-statement.org/protocols"),
        ("Review registration", "PROSPERO", "https://www.crd.york.ac.uk/prospero/"),
        ("Measurement properties", "COSMIN Study Design", "https://www.cosmin.nl/"),
        ("All designs", "EQUATOR library", "https://www.equator-network.org/library/")]),
    ("Reporting", "Reporting guidelines", [
        ("Randomised trials", "CONSORT", "https://www.consort-statement.org/"),
        ("Observational studies", "STROBE", "https://www.strobe-statement.org/"),
        ("Systematic reviews", "PRISMA", "https://www.prisma-statement.org/"),
        ("Case reports", "CARE", "https://www.care-statement.org/"),
        ("Measurement properties (PROMs)", "COSMIN", "https://pubmed.ncbi.nlm.nih.gov/33818733/"),
        ("Every design", "EQUATOR Network", "https://www.equator-network.org/")]),
    ("Critical appraisal", "Appraise the evidence", [
        ("Trials, cohorts, qualitative…", "CASP checklists", "https://casp-uk.net/casp-tools-checklists/"),
        ("All study types", "JBI tools", "https://jbi.global/critical-appraisal-tools"),
        ("Risk of bias (RCTs, NRSI)", "RoB 2 · ROBINS-I", "https://www.riskofbias.info/"),
        ("Systematic reviews", "AMSTAR 2", "https://amstar.ca/"),
        ("Measurement instruments", "COSMIN RoB", "https://doi.org/10.1007/s11136-017-1765-4")]),
]


PYRAMID_PART = Path(__file__).parent / "site_parts" / "evidence_pyramid.html"


def pyramid_block(cfg):
    """Piramide delle evidenze interattiva, sotto «Tools by study design». Esce solo con "evidence_pyramid": true in
    config.json (spenta finché Stefano non la approva). Il frammento è autonomo: CSS con prefisso .ep, script chiuso.
    Con "tools_table_v2" le schede dei livelli mostrano anche gli strumenti di ogni variante (design_tools.ROWS)."""
    if not cfg.get("evidence_pyramid") or not PYRAMID_PART.exists():
        return ""
    part = PYRAMID_PART.read_text(encoding="utf-8")
    if cfg.get("tools_table_v2"):
        import design_tools as dt
        data = {}
        for k, name, p, r, a in dt.ROWS:                       # livello → [[disegno, progetto, reporting, valutazione]]
            data.setdefault(k, []).append([name, p, r, a])
        blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
        part = part.replace("/*EP_TOOLS*/{}", blob, 1)
    return "\n" + part                                          # passato come valore a format(): graffe intatte


def _tool_cards():
    cards_ = []
    for kicker, title, links in TOOLS:
        rows = "".join(f'<li><a href="{escape(u, quote=True)}" rel="noopener" target="_blank"><b>{escape(n)}</b>'
                       f'<span>{escape(d)}</span></a></li>' for d, n, u in links)
        cards_.append(f'<div class="tool"><span class="k">{kicker}</span><span class="t">{title}</span><ul>{rows}</ul></div>')
    return "".join(cards_)


def tools_block(cfg):
    """Strumenti ufficiali per disegno di studio: protocollo, reporting, valutazione critica (link alle pagine ufficiali).
    Con "tools_table_v2": tabella ampliata per disegno, nell'ordine della piramide (computer e tablet), schede compatte
    di oggi sul telefono, tassonomia COSMIN sotto per tutti."""
    if not cfg.get("tools_block", True):
        return ""
    if not cfg.get("tools_table_v2"):
        return ('<section class="tools" id="tools"><h2>Tools by study design</h2>'
                '<p class="sub">Official tools to draft the protocol, report it properly and appraise the evidence, by study design.</p>'
                f'<div class="row">{_tool_cards()}</div></section>')
    return _tools_v2(cfg)


def _tlist(items):
    out = []
    for name, url in items:
        if url:
            out.append(f'<li><a href="{escape(url, quote=True)}" rel="noopener" target="_blank">{escape(name)}</a></li>')
        else:
            out.append(f'<li class="m">{escape(name)}</li>')
    return f'<ul>{"".join(out)}</ul>'


def _cosmin_html():
    import design_tools as dt
    c = dt.COSMIN

    def props(items):
        return "".join(f'<li><b>{escape(n)}</b>{f"<span>{escape(d)}</span>" if d else ""}</li>' for n, d in items)
    doms = []
    for name, items, group in c["domains"]:
        inner = f'<ul class="pr">{props(items)}</ul>'
        if group:
            inner += (f'<div class="cg"><span class="cgt">{escape(group[0])}</span>'
                      f'<ul class="pr">{props(group[1])}</ul></div>')
        doms.append(f'<div class="cd cd-{_slug(name)}"><h3>{escape(name)}</h3>{inner}</div>')
    tax_n, tax_u = c["taxonomy"]
    return ('<div class="cosmin" id="cosmin"><span class="k">Outside the pyramid · measurement instruments</span>'
            '<span class="t">COSMIN taxonomy: 9 measurement properties</span>'
            '<p class="cs">What to check before trusting a questionnaire, scale or test as an outcome measure.</p>'
            f'<div class="cds">{"".join(doms)}</div>'
            f'<p class="cr">Taxonomy: <a href="{escape(tax_u, quote=True)}" rel="noopener" target="_blank">{escape(tax_n)}</a>'
            ' · <a href="https://www.cosmin.nl/" rel="noopener" target="_blank">cosmin.nl</a></p></div>')


TOOLS_V2_CSS = """<style>
  h2.lib { font-size: 21px; font-weight: 800; margin: 36px 0 6px; color: var(--accent); border-bottom: 1px solid #2E2E2E; padding-bottom: 6px; }
  .tools .dt { display: none; margin-top: 4px; }
  .tools .sub .w { display: none; }
  @media (min-width: 700px) { .tools .dt { display: block; } .tools .tc, .tools .sub .n { display: none; } .tools .sub .w { display: inline; } }
  .tools .dt-f { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; }
  .tools .dt-f button { display: inline-flex; align-items: center; gap: 6px; background: transparent; color: var(--soft);
       border: 1px solid #2E2E2E; border-radius: 999px; padding: 4px 10px 4px 5px; font: 600 12px Inter, system-ui, sans-serif; cursor: pointer; }
  .tools .dt-f button[data-f=""] { padding-left: 10px; }
  .tools .dt-f button:hover { border-color: var(--muted); color: var(--text); }
  .tools .dt-f button[aria-pressed="true"] { border-color: var(--accent); color: var(--text); background: #161616; }
  .tools .ch { display: inline-grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; flex: none;
       font: 800 11px Inter, system-ui, sans-serif; font-variant-numeric: tabular-nums; }
  .tools .ch.cm { background: var(--accent); color: #0A0A0A; }
  .tools table { width: 100%; border-collapse: separate; border-spacing: 0; table-layout: fixed; font-size: 13.5px;
       background: #0F0F0F; border: 1px solid #2E2E2E; border-radius: 14px; }
  .tools col.c1 { width: 23%; } .tools col.c2 { width: 27%; } .tools col.c3, .tools col.c4 { width: 25%; }
  .tools thead th { position: sticky; top: 0; z-index: 2; background: #0F0F0F; text-align: left; padding: 12px 12px 8px;
       font: 800 11.5px Inter, system-ui, sans-serif; letter-spacing: .06em; text-transform: uppercase; color: var(--accent);
       border-bottom: 1px solid #2E2E2E; }
  .tools thead th:first-child { border-top-left-radius: 14px; } .tools thead th:last-child { border-top-right-radius: 14px; }
  .tools tbody th, .tools td { vertical-align: top; text-align: left; padding: 9px 12px; border-top: 1px solid #1F1F1F; }
  .tools tbody th[scope="row"] { font-weight: 700; color: var(--text); line-height: 1.35; }
  .tools tr.lh th { background: #141414; padding: 9px 12px; border-top: 1px solid #2E2E2E; font: 700 15px "Source Serif 4", Georgia, serif;
       color: var(--text); box-shadow: inset 4px 0 0 var(--lc); }
  .tools tr.lh th > span.ch { margin-right: 8px; vertical-align: 1px; }
  .tools tr.lh a.toep { float: right; font: 600 12px Inter, system-ui, sans-serif; color: var(--soft); text-decoration: none; margin-top: 2px; }
  .tools tr.lh a.toep:hover { color: var(--text); text-decoration: underline; }
  .tools td ul { list-style: none; margin: 0; padding: 0; }
  .tools td li { margin: 0 0 3px; line-height: 1.35; }
  .tools td li a { display: inline; padding: 0; border-top: 0; font-size: inherit; color: var(--accent); font-weight: 700; text-decoration: none; }
  .tools td li a:hover, .tools td li a:focus-visible { text-decoration: underline; }
  .tools td li.m { color: var(--soft); }
  .tools td li.m::before { content: "· "; color: var(--muted); }
  .tools tfoot th, .tools tfoot td { padding: 11px 12px; border-top: 1px solid #2E2E2E; text-align: left; vertical-align: top; }
  .tools tfoot td a { color: var(--accent); font-weight: 700; text-decoration: none; margin-right: 14px; }
  .tools tfoot td a:hover { text-decoration: underline; }
  .tools tbody[hidden] { display: none; }
  .tools .dt a:focus-visible, .tools .dt button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
  .tools .cosmin { margin-top: 14px; background: #0F0F0F; border: 1px solid #2E2E2E; border-radius: 14px; padding: 16px; }
  .tools .cosmin .cs { color: var(--soft); font-size: 14px; margin: 0 0 12px; }
  .tools .cds { display: grid; gap: 12px; grid-template-columns: 1fr; }
  @media (min-width: 700px) { .tools .cds { grid-template-columns: 1fr 1.55fr 1fr; align-items: start; } }
  .tools .cd { border: 1px solid #2E2E2E; border-radius: 12px; padding: 12px; background: #121212; }
  .tools .cd h3 { margin: 0 0 8px; font-size: 17px; color: var(--accent); }
  .tools .pr { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
  .tools .pr li { background: #1A1A1A; border-radius: 8px; padding: 6px 10px; font-size: 13.5px; line-height: 1.3; }
  .tools .pr li b { display: block; font-weight: 700; }
  .tools .pr li span { color: var(--soft); font-size: 12px; }
  .tools .cg { margin-top: 8px; border: 1px dashed #3A3A3A; border-radius: 10px; padding: 8px; }
  .tools .cgt { display: block; font: 800 11.5px Inter, system-ui, sans-serif; letter-spacing: .06em; text-transform: uppercase;
       color: var(--muted); margin: 0 0 6px 2px; }
  .tools .cosmin .cr { color: var(--muted); font-size: 12.5px; margin: 12px 0 0; }
  .tools .cosmin .cr a { color: var(--soft); }
</style>"""

TOOLS_V2_JS = """<script>
(function () {
  var box = document.getElementById("design-tools"); if (!box) return;
  var bodies = box.querySelectorAll("tbody[data-k]"), btns = box.querySelectorAll(".dt-f button");
  function show(f) {
    for (var i = 0; i < bodies.length; i++) bodies[i].hidden = f !== "" && bodies[i].getAttribute("data-k") !== f;
    for (var j = 0; j < btns.length; j++) btns[j].setAttribute("aria-pressed", String(btns[j].getAttribute("data-f") === f));
  }
  box.addEventListener("click", function (e) {
    var b = e.target.closest(".dt-f button"); if (b) { show(b.getAttribute("data-f")); return; }
    var a = e.target.closest("a.toep"); if (!a) return;
    if (a.hasAttribute("data-ep") && document.getElementById("evidence-pyramid")) {
      e.preventDefault();
      document.dispatchEvent(new CustomEvent("ep:show", { detail: +a.getAttribute("data-ep") }));
    }
  });
  document.addEventListener("ep:table", function (e) { show(String(e.detail)); });
})();
</script>"""


def _tools_v2(cfg):
    import design_tools as dt
    pyr = bool(cfg.get("evidence_pyramid"))
    chips = ['<button type="button" data-f="" aria-pressed="true">All designs</button>']
    for k, (name, col, txt) in enumerate(dt.LEVELS):
        if any(r[0] == k for r in dt.ROWS):
            chips.append(f'<button type="button" data-f="{k}" aria-pressed="false"><span class="ch" '
                         f'style="background:{col};color:{txt}">{k + 1}</span>{escape(dt.SHORT[k])}</button>')
    chips.append('<button type="button" data-f="cosmin" aria-pressed="false"><span class="ch cm">M</span>COSMIN</button>')
    groups = []
    for k, (name, col, txt) in enumerate(dt.LEVELS):
        rows = [r for r in dt.ROWS if r[0] == k]
        if not rows:
            continue
        link = (f'<a class="toep" href="#evidence-pyramid" data-ep="{k}">Notes in the pyramid &uarr;</a>' if pyr else "")
        body = [f'<tr class="lh"><th colspan="4" scope="rowgroup" style="--lc:{col}"><span class="ch" '
                f'style="background:{col};color:{txt}">{k + 1}</span>{escape(name)}{link}</th></tr>']
        for _, design, p, r, a in rows:
            body.append(f'<tr><th scope="row">{escape(design)}</th><td>{_tlist(p)}</td><td>{_tlist(r)}</td><td>{_tlist(a)}</td></tr>')
        groups.append(f'<tbody data-k="{k}">{"".join(body)}</tbody>')
    c = dt.COSMIN
    groups.append('<tbody data-k="cosmin"><tr class="lh"><th colspan="4" scope="rowgroup" style="--lc:var(--accent)">'
                  '<span class="ch cm">M</span>Outside the pyramid · measurement instruments (COSMIN)'
                  '<a class="toep" href="#cosmin">Taxonomy &darr;</a></th></tr>'
                  '<tr><th scope="row">Measurement properties study (PROMs and other outcome instruments)</th>'
                  f'<td>{_tlist(c["design"])}</td><td>{_tlist(c["report"])}</td><td>{_tlist(c["appraise"])}</td></tr></tbody>')
    every = " ".join(f'<a href="{escape(u, quote=True)}" rel="noopener" target="_blank">{escape(n)}</a>' for n, u in dt.EVERY)
    table = ('<div class="dt" id="design-tools">'
             f'<div class="dt-f" role="group" aria-label="Show one level of the pyramid">{"".join(chips)}</div>'
             '<table><caption hidden>Tools to design, report and appraise each study design</caption>'
             '<colgroup><col class="c1"><col class="c2"><col class="c3"><col class="c4"></colgroup>'
             '<thead><tr><th scope="col">Study design</th><th scope="col">Design &amp; protocol</th>'
             '<th scope="col">Reporting</th><th scope="col">Critical appraisal</th></tr></thead>'
             + "".join(groups) +
             f'<tfoot><tr><th scope="row">Every design</th><td colspan="3">{every}</td></tr></tfoot></table></div>')
    return ('<section class="tools" id="tools"><h2>Tools by study design</h2>'
            '<p class="sub"><span class="w">Official tools to plan, report and appraise each study design, in the order of '
            'the evidence pyramid. Linked names open the official page or paper; the others are methods to plan for.</span>'
            '<span class="n">Official tools to draft the protocol, report it properly and appraise the evidence. '
            'Each level of the pyramid above lists the tools for its designs.</span></p>'
            f'<div class="row tc">{_tool_cards()}</div>{table}{_cosmin_html()}{TOOLS_V2_CSS}{TOOLS_V2_JS}</section>')


# ---------------------------------------------------------------- percorso guidato: PICOT, fasi, TRL (interattivi)
BRAND5 = ["#88B0F8", "#8858F0", "#F8B048", "#3CC9B0", "#FFFFFF"]     # i colori del sito, uno per elemento

PICOT = [   # (lettera, nome, spiegazione, esempio, pezzo della domanda d'esempio)
    ("P", "Population", "Who exactly? Age range, diagnosis, setting and the key eligibility criteria.",
     "Adults with chronic low back pain (&gt;12 weeks), living in the community, no red flags.",
     "adults with chronic low back pain"),
    ("I", "Intervention", "What exposure, treatment, device or test is being evaluated? Include dose, frequency and duration.",
     "A 6-week robot-assisted gait-training programme, 3 sessions a week.",
     "a 6-week robot-assisted gait-training programme"),
    ("C", "Comparator", "Compared with what: placebo or sham, usual care, another active option, or nothing at all?",
     "Usual-care physiotherapy, matched for frequency and duration.",
     "usual-care physiotherapy"),
    ("O", "Outcome", "What is measured, and with which instrument? One primary outcome first, then the key secondary ones.",
     "Change in walking speed, measured with the 10-metre walk test.",
     "walking speed (10-metre walk test)"),
    ("T", "Time", "When is each outcome measured: baseline, end of treatment, longer-term follow-up?",
     "Baseline, 6 weeks (end of treatment) and 6-month follow-up.",
     "6 weeks and 6 months"),
]
PICOT_GLUE = ["In ", ", does ", ", compared with ", ", improve ", " at ", "?"]   # testo tra i pezzi della domanda

PICOT_DESIGN_NOTES = [   # come si riempiono C e T orienta verso il disegno di studio
    ("There is a comparator, and the team decides who gets it", "Randomised controlled trial"),
    ("There is a comparator, but allocation cannot be randomised", "Non-randomised trial or cohort study"),
    ("No comparator: one group followed over time", "Single-arm study or case series"),
    ("You start from the outcome and look back at exposures", "Case-control study"),
    ("One single point in time, no follow-up", "Cross-sectional study"),
]

# icone semplici (24x24, stroke=currentColor), una per fase: provetta, scudo, bersaglio, persone, globo
PHASE_ICONS = [
    '<path d="M9 2h6M10 2v6l-5 10a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-10V2" stroke-linecap="round" stroke-linejoin="round"/>',
    '<path d="M12 3l7 3v5c0 5-3.5 8-7 9-3.5-1-7-4-7-9V6l7-3z" stroke-linejoin="round"/>',
    '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r=".8" fill="currentColor"/>',
    '<circle cx="8" cy="9" r="2.6"/><circle cx="16" cy="9" r="2.6"/><path d="M3.5 19c.5-3 2.3-5 4.5-5s4 2 4.5 5M11.5 19c.5-3 '
    '2.3-5 4.5-5s4 2 4.5 5" stroke-linecap="round"/>',
    '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18" stroke-linecap="round"/>',
]

PHASES = [   # (numero, nome, scopo, colore, partecipanti, durata, descrizione, equivalente per i dispositivi)
    ("0", "Phase 0", "Exploratory", "#3CC9B0", "About 10&ndash;15 people", "Days",
     "Very small, sub-therapeutic doses show whether a drug reaches its target and behaves in the body as expected, "
     "before committing to a full programme. Optional, and not designed to show benefit.",
     "No real equivalent: devices go from bench and animal testing to a first-in-human study."),
    ("1", "Phase I", "Safety and dose", "#88B0F8", "20&ndash;100, often healthy volunteers", "Several months",
     "First-in-human testing of safety, tolerability and pharmacokinetics, usually with dose-escalation designs such as 3+3.",
     "Early feasibility (first-in-human) study in a handful of patients."),
    ("2", "Phase II", "Proof of concept", "#8858F0", "Up to a few hundred patients", "Months to about 2 years",
     "First test in the target population: is there a signal of efficacy, which dose or regimen works best, "
     "and what are the short-term adverse effects?",
     "Traditional feasibility (pilot) study with a near-final device."),
    ("3", "Phase III", "Confirmation", "#F8B048", "Several hundred to several thousand", "1&ndash;4 years",
     "Large, usually randomised trials that confirm efficacy against standard care or placebo and monitor adverse "
     "effects. The basis for marketing approval.",
     "Pivotal study supporting CE marking or FDA clearance/approval."),
    ("4", "Phase IV", "Real-world use", "#FFFFFF", "Thousands, in routine care", "Ongoing after approval",
     "After approval: long-term safety, rare adverse events and effectiveness in everyday practice and in groups "
     "the earlier trials left out.",
     "Post-market surveillance and clinical follow-up (PMCF)."),
]

TRL_LADDER = [   # i 9 livelli (scala UE/NASA), dal basso
    "Basic principles observed", "Technology concept formulated", "Experimental proof of concept",
    "Technology validated in the lab", "Technology validated in a relevant environment",
    "Technology demonstrated in a relevant environment", "System prototype demonstrated in an operational environment",
    "System complete and qualified", "Actual system proven in an operational environment",
]

TRL_STAGE = [   # per ogni TRL: (tappa clinica, cosa succede): mappa delle linee guida biomediche del DoD statunitense
    ("Basic research", "The underlying science is studied and reported; there is no device or candidate drug yet."),
    ("Concept", "A design concept or candidate is defined on paper: hypotheses, theoretical models, first algorithms."),
    ("Proof of concept", "Bench prototypes and in-vitro or small-animal experiments show the idea can work. No exposure in people."),
    ("Preclinical: laboratory validation", "An integrated prototype or candidate is tested in the laboratory and in animal "
     "models for safety and performance."),
    ("Preclinical to clinical transition", "Formal safety studies and a refined prototype; regulatory and ethics "
     "clearance is obtained for the first study in people."),
    ("Phase I / early feasibility", "First-in-human study in a small group: safety, tolerability and whether the device "
     "works as intended."),
    ("Phase II&ndash;III / pivotal", "Larger, usually multi-site trials of a near-final product in its intended "
     "setting, up to the pivotal evidence for approval."),
    ("Regulatory approval", "The evidence is submitted and the product obtains marketing authorisation, CE marking "
     "or FDA clearance."),
    ("Phase IV / post-market", "Routine clinical use, with post-market surveillance and real-world evidence."),
]
TRL_SOURCE = "https://cdmrp.health.mil/jwmrp/pdfs/Biomedical%20Product%20Guidelines.pdf"


def _mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02X%02X%02X" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _trl_color(i):
    """Colore del livello i (0-8): dal verde del sito al bianco, passando per azzurro e viola."""
    stops = [(0, "#3CC9B0"), (.38, "#88B0F8"), (.72, "#8858F0"), (1, "#FFFFFF")]
    t = i / 8
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            return _mix(c0, c1, (t - t0) / (t1 - t0))
    return stops[-1][1]


CHAPTERS = [   # (id della sezione, numero, titolo breve, titolo, cosa contiene)
    ("picot", "01", "Question", "Frame the question", "PICOT"),
    ("evidence-pyramid", "02", "Design", "Choose the design", "The evidence pyramid"),
    ("path", "03", "Stage", "Place it on the path", "Clinical phases and TRL"),
    ("tools", "04", "Tools", "Plan, report, appraise", "Official tools by design"),
    ("carousels", "05", "Library", "Go deeper", "The methodology carousels"),
]


def _chap(i):
    _, n, _, title, _ = CHAPTERS[i]
    return f'<p class="jx-chap"><b>{n}</b><span>{title}</span></p>'


def hero_block(cfg):
    """Apertura della pagina: il percorso in cinque passi, ognuno porta alla sua sezione."""
    steps = "".join(f'<a class="jx-step jx-glow" href="#{sid}"><b>{n}</b><span class="jx-st">{title}</span>'
                    f'<span class="jx-sd">{what}</span></a>' for sid, n, _, title, what in CHAPTERS)
    return ('<div class="jx-hero"><p class="jx-lead">From a clinical question to evidence you can trust, in five steps: '
            'frame the question, choose the design, see where the study sits on the path from idea to practice, '
            'pick the right tools, then go deeper with the carousels.</p>'
            f'<nav class="jx-steps" aria-label="On this page">{steps}</nav>'
            '<p class="jx-cue" aria-hidden="true"><i></i>Scroll to explore</p></div>')


def picot_block(cfg):
    """PICOT interattivo: la domanda d'esempio si colora pezzo per pezzo; ogni lettera apre la sua scheda."""
    if not cfg.get("frameworks"):
        return ""
    q = PICOT_GLUE[0]
    for i, (_, _, _, _, chunk) in enumerate(PICOT):
        q += (f'<span role="button" tabindex="0" class="jx-ch" data-i="{i}" style="--pc:{BRAND5[i]}">{chunk}</span>'
              + PICOT_GLUE[i + 1])
    tiles = "".join(f'<button type="button" class="jx-tile" data-i="{i}" style="--pc:{BRAND5[i]}">'
                    f'<b>{letter}</b><span>{escape(name)}</span></button>'
                    for i, (letter, name, _, _, _) in enumerate(PICOT))
    items = "".join(f'<div class="jx-it" data-i="{i}" style="--pc:{BRAND5[i]}"><p class="jx-in"><b>{letter}</b>{escape(name)}</p>'
                    f'<p class="jx-id">{desc}</p><p class="jx-ie"><span>Example</span>{ex}</p></div>'
                    for i, (letter, name, desc, ex, _) in enumerate(PICOT))
    notes = "".join(f'<li><a href="#evidence-pyramid"><span>{a}</span><b>&rarr; {b}</b></a></li>' for a, b in PICOT_DESIGN_NOTES)
    return ('<section class="jx-sec" id="picot">' + _chap(0) +
            '<h2>PICOT: frame your question</h2>'
            '<p class="jx-sub">A clear question names five things. Tap a letter, or a coloured part of the example, '
            'to see what belongs there.</p>'
            f'<div class="jx-box jx-picot"><p class="jx-q">{q}</p>'
            f'<div class="jx-tiles">{tiles}</div><div class="jx-items">{items}</div></div>'
            '<h3>From the question to the design</h3>'
            '<p class="jx-sub">How you fill in the comparator and the time points often tells you which design you need. '
            'Each line takes you to the pyramid in the next step.</p>'
            f'<ul class="jx-notes">{notes}</ul></section>')


def path_block(cfg):
    """Fasi cliniche 0-IV (passi cliccabili) e termometro TRL interattivo, incrociato con le fasi."""
    if not cfg.get("frameworks"):
        return ""
    nodes = "".join(f'<button type="button" class="jx-node" data-i="{i}" style="--pc:{color}" aria-label="{escape(name)}">'
                    f'<b>{tag}</b><span>{escape(name)}</span></button>'
                    for i, (tag, name, _, color, _, _, _, _) in enumerate(PHASES))
    ph_items = "".join(
        f'<div class="jx-it" data-i="{i}" style="--pc:{color}"><div class="jx-ph-h"><span class="jx-ico">'
        f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">{icon}</svg></span>'
        f'<p class="jx-in"><b>{escape(name)}</b>{goal}</p></div><p class="jx-id">{desc}</p>'
        f'<dl class="jx-facts"><div><dt>Participants</dt><dd>{n}</dd></div><div><dt>Duration</dt><dd>{dur}</dd></div>'
        f'<div><dt>For devices</dt><dd>{dev}</dd></div></dl></div>'
        for i, ((tag, name, goal, color, n, dur, desc, dev), icon) in enumerate(zip(PHASES, PHASE_ICONS)))
    bands = "".join(f'<button type="button" class="jx-band" data-i="{i}" style="--pc:{_trl_color(i)};--ink:{grants.on_color(_trl_color(i))}" '
                    f'aria-label="TRL {i + 1}: {TRL_LADDER[i]}">TRL {i + 1}</button>' for i in range(9))
    trl_items = "".join(f'<div class="jx-it" data-i="{i}" style="--pc:{_trl_color(i)}"><p class="jx-in"><b>TRL {i + 1}</b>{TRL_LADDER[i]}</p>'
                        f'<p class="jx-stage">{TRL_STAGE[i][0]}</p><p class="jx-id">{TRL_STAGE[i][1]}</p></div>' for i in range(9))
    return ('<section class="jx-sec" id="path">' + _chap(2) +
            '<h2>Phases of clinical research</h2>'
            '<p class="jx-sub">A new treatment moves through numbered phases, each answering a different question with '
            'more people. Select a phase to see what it is for.</p>'
            f'<div class="jx-box jx-phases"><div class="jx-track"><i class="jx-line"><i></i></i>{nodes}</div>'
            f'<div class="jx-items">{ph_items}</div>'
            '<div class="jx-pn"><button type="button" class="jx-prev" aria-label="Previous phase">&larr;</button>'
            '<button type="button" class="jx-next" aria-label="Next phase">&rarr;</button></div></div>'
            '<h3 id="trl">TRL: how ready is a technology?</h3>'
            '<p class="jx-sub">For devices and rehabilitation technology, the Technology Readiness Level (1&ndash;9) tracks '
            'maturity from first principles to routine use. Raise the level to see the matching clinical stage.</p>'
            f'<div class="jx-box jx-trl"><div class="jx-thermo"><div class="jx-tube">{bands}</div><span class="jx-bulb"></span></div>'
            f'<div class="jx-trl-r"><div class="jx-items">{trl_items}</div>'
            '<label class="jx-range"><span>Readiness level</span><input type="range" min="1" max="9" step="1" value="1" '
            'aria-label="Technology readiness level"></label></div></div>'
            '<p class="jx-src">Level names follow the EU scale. The match with clinical stages is approximate and follows the '
            f'<a href="{TRL_SOURCE}" rel="noopener" target="_blank">US Department of Defense biomedical TRL guidance</a>; '
            'other schemes shift it by a level.</p></section>')


def dock_block():
    """Barra di avanzamento in alto e indice fisso in basso: mostra il passo in cui ci si trova e porta agli altri."""
    links = "".join(f'<a href="#{sid}"><b>{n}</b><span>{short}</span></a>' for sid, n, short, _, _ in CHAPTERS)
    return (f'<div class="jx-prog" aria-hidden="true"><i></i></div><nav class="jx-dock" aria-label="Steps of this page">{links}</nav>'
            + JX_CSS + JX_JS)


JX_CSS = """<style id="jx-css">
  html { scroll-behavior: smooth; }
  .jx-sec, #evidence-pyramid, #tools, #carousels, #trl { scroll-margin-top: 28px; }
  .jx-sec { margin: 8px 0 4px; }
  .jx-sec > h2 { font-size: 26px; font-weight: 800; margin: 6px 0 8px; color: var(--accent); line-height: 1.15; }
  #evidence-pyramid > h2, #tools > h2, h2.lib { font-size: 26px !important; margin-top: 6px !important; }
  .jx-sec > h3 { font-size: 20px; font-weight: 800; margin: 34px 0 6px; color: var(--text); }
  .jx-sub { color: var(--soft); font-size: 15px; margin: 0 0 16px; max-width: 62ch; }
  .jx-src { color: var(--muted); font-size: 12.5px; margin: 10px 0 0; max-width: 70ch; }
  .jx-src a { color: var(--soft); }
  .jx-chap { display: flex; align-items: center; gap: 12px; margin: 64px 0 0; font: 800 11.5px/1 Inter, system-ui, sans-serif;
             letter-spacing: .12em; text-transform: uppercase; color: var(--soft); }
  .jx-chap b { color: var(--accent); font: 800 13px/1 Inter, system-ui, sans-serif; letter-spacing: .04em; }
  .jx-chap::after { content: ""; flex: 1; height: 1px; background: #2E2E2E; }
  .jx-box { position: relative; background: #0F0F0F; border: 1px solid #2E2E2E; border-radius: 20px; padding: 22px; }

  /* apertura */
  .jx-hero { margin: 4px 0 0; }
  .jx-lead { color: var(--soft); font-size: 17px; line-height: 1.5; margin: 0 0 22px; max-width: 60ch; }
  .jx-steps { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
  .jx-step { position: relative; display: flex; flex-direction: column; gap: 6px; min-height: 132px; padding: 14px;
             background: #0F0F0F; border: 1px solid #2E2E2E; border-radius: 16px; text-decoration: none; color: var(--text);
             overflow: hidden; transition: transform .35s cubic-bezier(.2,.7,.2,1), border-color .25s; }
  .jx-step b { font: 800 12px/1 Inter, system-ui, sans-serif; color: var(--accent); letter-spacing: .06em; }
  .jx-st { font: 800 15.5px/1.2 Inter, system-ui, sans-serif; margin-top: auto; }
  .jx-sd { font-size: 12.5px; color: var(--soft); line-height: 1.3; }
  .jx-step:hover, .jx-step:focus-visible { transform: translateY(-4px); border-color: var(--accent); }
  .jx-cue { display: flex; align-items: center; gap: 10px; margin: 22px 0 0; color: var(--muted);
            font: 700 11px/1 Inter, system-ui, sans-serif; letter-spacing: .12em; text-transform: uppercase; }
  .jx-cue i { width: 1px; height: 28px; background: linear-gradient(var(--accent), transparent); animation: jx-cue 1.8s ease-in-out infinite; transform-origin: top; }
  @keyframes jx-cue { 0% { transform: scaleY(0); } 50% { transform: scaleY(1); } 100% { transform: scaleY(1); opacity: 0; } }
  @media (max-width: 760px) {
    .jx-steps { grid-template-columns: 1fr; gap: 8px; }
    .jx-step { min-height: 0; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 2px 14px; padding: 13px 14px; align-items: center; }
    .jx-step b { grid-row: 1 / span 2; font-size: 13px; }
    .jx-st { margin: 0; }
  }

  /* luce che segue il puntatore sulle schede */
  .jx-glow::before { content: ""; position: absolute; inset: 0; border-radius: inherit; pointer-events: none; opacity: 0;
       background: radial-gradient(220px circle at var(--mx, 50%) var(--my, 50%), rgba(136, 176, 248, .16), transparent 70%);
       transition: opacity .3s; }
  .jx-glow:hover::before { opacity: 1; }

  /* schede a scelta (PICOT, fasi, TRL): senza script si vedono tutte, con lo script una alla volta */
  .jx-items { display: grid; gap: 12px; }
  .jx-it { border-left: 3px solid var(--pc); padding: 2px 0 2px 14px; }
  .jx-on .jx-items { display: block; }
  .jx-on .jx-it { display: none; }
  .jx-on .jx-it.on { display: block; animation: jx-in .45s cubic-bezier(.2,.7,.2,1) both; }
  @keyframes jx-in { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
  .jx-in { margin: 0 0 6px; font-size: 14px; color: var(--soft); display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
  .jx-in b { color: var(--pc); font: 800 19px/1.1 Inter, system-ui, sans-serif; }
  .jx-id { margin: 0 0 8px; font-size: 15.5px; line-height: 1.45; color: var(--text); max-width: 62ch; }
  .jx-ie { margin: 0; font-size: 14px; color: var(--soft); font-style: italic; }
  .jx-ie span { display: block; font: 800 10.5px/1.6 Inter, system-ui, sans-serif; letter-spacing: .08em; text-transform: uppercase;
                color: var(--muted); font-style: normal; }

  /* PICOT */
  .jx-q { font-size: clamp(19px, 3.1vw, 27px); line-height: 1.5; font-weight: 600; margin: 0 0 20px; color: var(--text); }
  .jx-ch { color: var(--text); padding: .05em .15em; cursor: pointer;
           border-radius: 6px; -webkit-box-decoration-break: clone; box-decoration-break: clone; box-shadow: inset 0 -3px 0 var(--pc); transition: background .25s, color .25s, box-shadow .25s; }
  .jx-ch:focus-visible { outline: 2px solid var(--pc); outline-offset: 2px; }
  .jx-ch:hover { box-shadow: inset 0 -8px 0 var(--pc); }
  .jx-ch.on { background: var(--pc); color: #0A0A0A; box-shadow: none; }
  .jx-tiles { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin: 0 0 18px; }
  .jx-tile { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 5px; min-height: 76px; padding: 10px 4px;
             background: transparent; color: var(--pc); border: 1.5px solid var(--pc); border-radius: 14px; cursor: pointer;
             transition: background .25s, color .25s, transform .3s cubic-bezier(.2,.7,.2,1); }
  .jx-tile b { font: 800 26px/1 Inter, system-ui, sans-serif; }
  .jx-tile span { font: 800 10px/1 Inter, system-ui, sans-serif; letter-spacing: .05em; text-transform: uppercase; }
  .jx-tile:hover { transform: translateY(-3px); }
  .jx-tile.on { background: var(--pc); color: #0A0A0A; }
  @media (max-width: 560px) { .jx-tiles { gap: 6px; } .jx-tile { min-height: 58px; } .jx-tile span { display: none; } .jx-box { padding: 16px; } }
  .jx-notes { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
  .jx-notes a { display: flex; justify-content: space-between; align-items: center; gap: 6px 16px; flex-wrap: wrap; padding: 12px 14px;
                background: #121212; border: 1px solid #2E2E2E; border-radius: 12px; text-decoration: none; font-size: 14.5px;
                transition: border-color .25s, transform .3s cubic-bezier(.2,.7,.2,1); }
  .jx-notes a span { color: var(--soft); } .jx-notes a b { color: var(--accent); font-weight: 700; }
  .jx-notes a:hover, .jx-notes a:focus-visible { border-color: var(--accent); transform: translateX(4px); }

  /* fasi */
  .jx-track { position: relative; display: flex; justify-content: space-between; margin: 0 0 22px; }
  .jx-line { position: absolute; left: 22px; right: 22px; top: 21px; height: 2px; background: #2E2E2E; }
  .jx-line i { display: block; height: 100%; width: 0; background: linear-gradient(90deg, #3CC9B0, #88B0F8, #8858F0, #F8B048, #FFFFFF);
               background-size: calc(100% / var(--f, 1)) 100%; transition: width .6s cubic-bezier(.2,.7,.2,1); }
  .jx-node { position: relative; display: flex; flex-direction: column; align-items: center; gap: 8px; background: none; border: 0; padding: 0;
             cursor: pointer; color: var(--soft); width: 44px; }
  .jx-node b { width: 44px; height: 44px; border-radius: 50%; display: grid; place-items: center; background: #0A0A0A;
               border: 2px solid #3A3A3A; color: var(--soft); font: 800 18px/1 Inter, system-ui, sans-serif;
               transition: border-color .3s, color .3s, background .3s, transform .3s cubic-bezier(.2,.7,.2,1); }
  .jx-node span { font: 800 10.5px/1 Inter, system-ui, sans-serif; letter-spacing: .04em; text-transform: uppercase; white-space: nowrap; }
  .jx-node.done b { border-color: var(--pc); color: var(--pc); }
  .jx-node.on b { background: var(--pc); border-color: var(--pc); color: #0A0A0A; transform: scale(1.12); }
  .jx-node.on span { color: var(--text); }
  .jx-node:hover b { border-color: var(--pc); }
  .jx-ph-h { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
  .jx-ph-h .jx-in { margin: 0; flex-direction: column; gap: 2px; align-items: flex-start; }
  .jx-ico { width: 44px; height: 44px; flex: none; border-radius: 50%; border: 2px solid var(--pc); color: var(--pc); display: grid; place-items: center; }
  .jx-ico svg { width: 22px; height: 22px; }
  .jx-facts { display: grid; grid-template-columns: 1fr 1fr 1.4fr; gap: 10px; margin: 12px 0 0; }
  .jx-facts div { background: #161616; border-radius: 12px; padding: 10px 12px; }
  .jx-facts dt { font: 800 10.5px/1.5 Inter, system-ui, sans-serif; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
  .jx-facts dd { margin: 2px 0 0; font-size: 14px; color: var(--text); line-height: 1.35; }
  @media (max-width: 640px) { .jx-facts { grid-template-columns: 1fr; } .jx-node span { font-size: 9px; } }
  .jx-pn { display: none; gap: 8px; justify-content: flex-end; margin-top: 14px; }
  .jx-on .jx-pn { display: flex; }
  .jx-pn button { width: 42px; height: 42px; border-radius: 50%; background: transparent; color: var(--text); border: 1px solid #3A3A3A;
                  font-size: 17px; cursor: pointer; transition: border-color .25s, background .25s; }
  .jx-pn button:hover:not(:disabled) { border-color: var(--accent); background: #161616; }
  .jx-pn button:disabled { opacity: .35; cursor: default; }

  /* termometro TRL */
  .jx-trl { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 26px; align-items: center; }
  .jx-thermo { display: flex; flex-direction: column; align-items: center; }
  .jx-tube { display: flex; flex-direction: column-reverse; width: 72px; border-radius: 36px 36px 0 0; overflow: hidden; background: #161616;
             border: 2px solid #2E2E2E; border-bottom: 0; }
  .jx-band { height: 38px; border: 0; border-top: 1px solid #0A0A0A; background: #161616; color: var(--muted); cursor: pointer;
             font: 800 12.5px/1 Inter, system-ui, sans-serif; transition: background .35s, color .35s; }
  .jx-band:last-child { height: 46px; padding-top: 8px; }
  .jx-band:first-child { height: 54px; padding-bottom: 16px; }
  .jx-band.fill { background: var(--pc); color: var(--ink); }
  .jx-band.on { box-shadow: inset 0 0 0 2px #0A0A0A, inset 0 0 0 4px var(--pc); }
  .jx-band:hover:not(.fill) { background: #222; color: var(--text); }
  .jx-bulb { width: 104px; height: 104px; border-radius: 50%; background: #3CC9B0; margin-top: -18px; border: 2px solid #2E2E2E;
             box-shadow: 0 0 40px rgba(60, 201, 176, .25); }
  .jx-trl .jx-in { flex-direction: column; gap: 4px; align-items: flex-start; font-size: 16px; color: var(--text); font-weight: 600; }
  .jx-trl .jx-in b { font-size: 34px; }
  .jx-stage { display: inline-block; margin: 6px 0 10px; padding: 6px 12px; border-radius: 999px; background: var(--pc); color: #0A0A0A;
              font: 800 11.5px/1.2 Inter, system-ui, sans-serif; letter-spacing: .04em; text-transform: uppercase; }
  .jx-trl .jx-it { border-left: 0; padding-left: 0; }
  .jx-on.jx-trl .jx-items { min-height: 215px; }
  .jx-range { display: none; margin-top: 12px; }
  .jx-on .jx-range { display: block; }
  .jx-range span { display: block; font: 800 10.5px/1.6 Inter, system-ui, sans-serif; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
  .jx-range input { width: 100%; max-width: 360px; accent-color: var(--accent); }
  @media (max-width: 560px) { .jx-trl { grid-template-columns: 64px minmax(0, 1fr); gap: 16px; align-items: start; }
       .jx-tube { width: 56px; } .jx-band { font-size: 10.5px; height: 34px; } .jx-band:first-child { height: 46px; padding-bottom: 12px; } .jx-bulb { width: 76px; height: 76px; margin-top: -12px; }
       .jx-trl .jx-in b { font-size: 28px; } .jx-on.jx-trl .jx-items { min-height: 290px; } }

  /* comparsa allo scorrimento */
  .jx-rv { opacity: 0; transform: translateY(26px); transition: opacity .7s cubic-bezier(.2,.7,.2,1), transform .7s cubic-bezier(.2,.7,.2,1); }
  .jx-rv.in { opacity: 1; transform: none; }

  /* avanzamento e indice fisso */
  .jx-prog { position: fixed; left: 0; right: 0; top: 0; height: 3px; z-index: 60; pointer-events: none; }
  .jx-prog i { display: block; height: 100%; background: linear-gradient(90deg, #3CC9B0, #88B0F8, #8858F0, #F8B048); transform: scaleX(0); transform-origin: left; }
  .jx-dock { position: fixed; left: 50%; bottom: calc(14px + env(safe-area-inset-bottom, 0px)); z-index: 55; display: flex; gap: 4px; padding: 5px;
             background: rgba(18, 18, 18, .82); -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px); border: 1px solid #2E2E2E;
             border-radius: 999px; transform: translate(-50%, 140%); opacity: 0; transition: transform .5s cubic-bezier(.2,.7,.2,1), opacity .4s;
             box-shadow: 0 10px 40px rgba(0, 0, 0, .5); max-width: calc(100vw - 20px); }
  .jx-dock.show { transform: translate(-50%, 0); opacity: 1; }
  .jx-dock a { display: flex; align-items: center; gap: 0; height: 38px; min-width: 38px; padding: 0 12px; border-radius: 999px; text-decoration: none;
               color: var(--soft); font: 800 12px/1 Inter, system-ui, sans-serif; justify-content: center;
               transition: background .3s, color .3s, padding .3s; }
  .jx-dock a b { font-weight: 800; letter-spacing: .04em; }
  .jx-dock a span { max-width: 0; overflow: hidden; white-space: nowrap; opacity: 0; transition: max-width .45s cubic-bezier(.2,.7,.2,1), opacity .3s, margin .3s; }
  .jx-dock a:hover { color: var(--text); background: #1F1F1F; }
  .jx-dock a.on { background: var(--accent); color: #0A0A0A; padding: 0 15px; }
  .jx-dock a.on span { max-width: 90px; opacity: 1; margin-left: 8px; }
  body.jx-has-dock footer { padding-bottom: 70px; }

  @media (prefers-reduced-motion: reduce) {
    html { scroll-behavior: auto; }
    .jx-rv { opacity: 1; transform: none; transition: none; }
    .jx-cue i, .jx-on .jx-it.on { animation: none; }
    .jx-step, .jx-tile, .jx-notes a, .jx-node b, .jx-line i, .jx-band, .jx-dock, .jx-dock a span { transition: none; }
  }
</style>"""

JX_JS = """<script>
(function () {
  var doc = document.documentElement, still = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  function all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  /* avanzamento e indice fisso */
  var bar = document.querySelector(".jx-prog i"), dock = document.querySelector(".jx-dock");
  if (bar && dock) {
    document.body.classList.add("jx-has-dock");
    var links = all("a", dock), secs = links.map(function (a) { return document.getElementById(a.getAttribute("href").slice(1)); });
    var tick = false;
    function onScroll() {
      tick = false;
      var h = doc.scrollHeight - window.innerHeight, y = window.pageYOffset, cur = -1;
      bar.style.transform = "scaleX(" + (h > 0 ? Math.min(1, y / h) : 0) + ")";
      for (var i = 0; i < secs.length; i++) if (secs[i] && secs[i].getBoundingClientRect().top < window.innerHeight * 0.45) cur = i;
      if (h > 0 && y >= h - 4) cur = secs.length - 1;
      links.forEach(function (a, i) { a.classList.toggle("on", i === cur); if (i === cur) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current"); });
      dock.classList.toggle("show", y > 260);
    }
    window.addEventListener("scroll", function () { if (!tick) { tick = true; window.requestAnimationFrame(onScroll); } }, { passive: true });
    window.addEventListener("resize", onScroll);
    onScroll();
  }

  /* luce che segue il puntatore */
  document.addEventListener("pointermove", function (e) {
    var c = e.target.closest && e.target.closest(".jx-glow");
    if (!c) return;
    var r = c.getBoundingClientRect();
    c.style.setProperty("--mx", (e.clientX - r.left) + "px");
    c.style.setProperty("--my", (e.clientY - r.top) + "px");
  }, { passive: true });

  /* schede a scelta: una alla volta */
  function chooser(box, triggers, onPick) {
    if (!box) return null;
    var items = all(".jx-it", box), cur = -1, touched = false;
    box.classList.add("jx-on");
    function pick(i, byUser) {
      if (byUser) touched = true;
      i = Math.max(0, Math.min(items.length - 1, i));
      if (i === cur) return;
      cur = i;
      items.forEach(function (el, k) { el.classList.toggle("on", k === i); });
      triggers.forEach(function (group) { group.forEach(function (el) {
        var on = +el.getAttribute("data-i") === i; el.classList.toggle("on", on); el.setAttribute("aria-pressed", on ? "true" : "false"); }); });
      if (onPick) onPick(i);
    }
    triggers.forEach(function (group) { group.forEach(function (el) {
      el.addEventListener("click", function () { pick(+el.getAttribute("data-i"), true); });
      if (el.tagName !== "BUTTON") el.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(+el.getAttribute("data-i"), true); } }); }); });
    return { pick: pick, cur: function () { return cur; }, n: items.length, touched: function () { return touched; } };
  }
  /* la prima volta che il riquadro entra nello schermo, scorre da solo le voci */
  function tour(box, ch, order, pause) {
    if (!box || !ch || still || !("IntersectionObserver" in window)) return;
    var io = new IntersectionObserver(function (es) {
      if (!es[0].isIntersecting) return;
      io.disconnect();
      var k = 0;
      (function step() { if (ch.touched() || k >= order.length) return; ch.pick(order[k++], false); setTimeout(step, pause); })();
    }, { threshold: 0.5 });
    io.observe(box);
  }

  var pBox = document.querySelector(".jx-picot");
  var picot = chooser(pBox, pBox ? [all(".jx-tile", pBox), all(".jx-ch", pBox)] : []);
  if (picot) { picot.pick(0, false); tour(pBox, picot, [0, 1, 2, 3, 4, 0], 1500); }

  var phBox = document.querySelector(".jx-phases");
  if (phBox) {
    var nodes = all(".jx-node", phBox), line = phBox.querySelector(".jx-line i"), prev = phBox.querySelector(".jx-prev"), next = phBox.querySelector(".jx-next");
    var phases = chooser(phBox, [nodes], function (i) {
      var f = i / (nodes.length - 1);
      line.style.setProperty("--f", f || 1); line.style.width = (f * 100) + "%";
      nodes.forEach(function (n, k) { n.classList.toggle("done", k < i); });
      prev.disabled = i === 0; next.disabled = i === nodes.length - 1;
    });
    prev.addEventListener("click", function () { phases.pick(phases.cur() - 1, true); });
    next.addEventListener("click", function () { phases.pick(phases.cur() + 1, true); });
    phBox.addEventListener("keydown", function (e) {
      if (e.key === "ArrowRight") phases.pick(phases.cur() + 1, true); else if (e.key === "ArrowLeft") phases.pick(phases.cur() - 1, true);
    });
    phases.pick(0, false); tour(phBox, phases, [0, 1, 2, 3, 4, 0], 1100);
  }

  var tBox = document.querySelector(".jx-trl");
  if (tBox) {
    var bands = all(".jx-band", tBox), range = tBox.querySelector("input[type=range]");
    var trl = chooser(tBox, [bands], function (i) {
      bands.forEach(function (b, k) { b.classList.toggle("fill", k <= i); });
      range.value = i + 1;
    });
    range.addEventListener("input", function () { trl.pick(+range.value - 1, true); });
    trl.pick(0, false); tour(tBox, trl, [0, 1, 2, 3, 4, 5], 420);
  }

  /* comparsa allo scorrimento */
  if (!still && "IntersectionObserver" in window) {
    var groups = [".jx-chap", ".jx-sec > h2", ".jx-sec > h3", ".jx-sub", ".jx-box", ".jx-notes li", ".jx-step", "#evidence-pyramid > h2",
                  "#evidence-pyramid .panel", "#tools > h2", "#tools .tool", "#tools .dt", "h2.lib", "article.method"];
    var seen = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); seen.unobserve(e.target); } });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });
    groups.forEach(function (sel) {
      all(sel).forEach(function (el) {
        var sib = el.parentNode ? Array.prototype.indexOf.call(el.parentNode.children, el) : 0;
        el.classList.add("jx-rv");
        if (/li|jx-step|tool/.test(sel)) el.style.transitionDelay = Math.min(sib, 5) * 70 + "ms";
        seen.observe(el);
      });
    });
    /* i filtri della libreria nascondono e mostrano le schede: quelle rese visibili dopo non devono restare trasparenti */
    setTimeout(function () { all(".jx-rv").forEach(function (el) { if (el.getBoundingClientRect().top < window.innerHeight) el.classList.add("in"); }); }, 60);
  }
})();
</script>"""


def build_page(data, cfg, today=None):
    today = today or date.today()
    THUMBS.mkdir(parents=True, exist_ok=True)
    cats = {}
    data = {k: e for k, e in data.items()
            if not e.get("duplicate_of") and e.get("category") != content.CLINICAL_CATEGORY}  # post ripetuti e
                                              # «Latest Science» fuori: hanno la loro pagina (science.py)
    for e in sorted(data.values(), key=lambda e: e.get("date", ""), reverse=True):
        cats.setdefault(e.get("category") or "Research methods", []).append(e)
    sections = []
    for cat in sorted(cats, key=lambda c: -len(cats[c])):
        parts = [f'  <section id="{_slug(cat)}">', f'    <h2>{escape(cat)}</h2>', '    <div class="grp">']
        for e in cats[cat]:
            thumb = ""
            if e.get("cover") and (ROOT / e["cover"]).exists():
                src_dir = (ROOT / e["cover"]).parent
                slides = sorted(src_dir.glob("slide-*.jpg"), key=lambda q: int(re.sub(r"\D", "", q.stem) or 0))
                out_dir = THUMBS / e["id"]
                out_dir.mkdir(parents=True, exist_ok=True)
                imgs = []
                for k, src in enumerate(slides, 1):
                    out = out_dir / f"{k}.jpg"
                    if not out.exists():
                        im = Image.open(src).convert("RGB")
                        im.thumbnail((720, 900))
                        im.save(out, quality=80, optimize=True, progressive=True)
                    alt = escape(e.get("title", "")) + f" – slide {k} of {len(slides)}"
                    imgs.append(f'<img src="methodology/{e["id"]}/{k}.jpg" alt="{alt}" width="720" height="900"'
                                + (' loading="lazy"' if k > 1 else "") + ">")
                nav = (f'<div class="nav"><button class="prev" type="button" aria-label="Previous slide">&lsaquo;</button>'
                       f'<span class="pos">{len(slides)} slides · swipe</span>'
                       f'<button class="next" type="button" aria-label="Next slide">&rsaquo;</button></div>') if len(slides) > 1 else ""
                thumb = f'<div class="slides"><div class="strip">{"".join(imgs)}</div>{nav}</div>'
            points = "".join(f'<h4>{escape(p["heading"])}</h4><p>{escape(p["body"])}</p>' for p in e.get("points", []))
            refs = "".join(f"<p>{escape(r)}</p>" for r in e.get("references", []))
            words = " ".join([e.get("title", ""), e.get("takeaway", ""), cat] + [p["heading"] + " " + p["body"] for p in e.get("points", [])]).lower()
            d = grants._date(e.get("date"))
            parts.append(f"""    <article class="method" id="m-{escape(e['id'])}" data-area="{_slug(cat)}" data-text="{escape(words, quote=True)}">
      {thumb or '<div></div>'}
      <div>
        <div class="date">{grants._fmt_date(d) if d else ""}</div>
        <h3>{escape(e.get("title", ""))}</h3>
        <p class="take">{escape(e.get("takeaway", ""))}</p>
        <details><summary>Key points and references</summary>{points}{f'<div class="refs"><b>References</b>{refs}</div>' if refs else ""}</details>
      </div>
    </article>""")
        parts += ["    </div>", "  </section>"]
        sections.append("\n".join(parts))
    c = grants.site_palette(cfg)
    cat_opts = "".join(f'<option value="{_slug(k)}">{escape(k)}</option>' for k in sorted(cats))
    top = pyramid_block(cfg)                       # percorso: domanda (PICOT), disegno (piramide), fasi e TRL, strumenti, caroselli
    if top:
        guided = bool(cfg.get("frameworks"))
        if guided:
            top = (hero_block(cfg) + "\n" + picot_block(cfg) + "\n" + _chap(1)
                   + top + "\n" + path_block(cfg) + "\n" + _chap(3) + tools_block(cfg) + "\n" + _chap(4))
        else:
            top += "\n" + tools_block(cfg)
    html = PAGE.format(brand=escape(cfg["brand_name"]), handle=escape(cfg["handle"]), ig=cfg["handle"].lstrip("@"),
                       bg=c["background"], muted=c["muted"], soft=c["muted_text"], teal=grants.site_accent(cfg, "methods") if cfg.get("site_v4") else c["accent"], cat_opts=cat_opts,
                       n=len(data), topics_word="topic" if len(data) == 1 else "topics", tools="" if top else tools_block(cfg), sections="\n".join(sections), updated=grants._fmt_date(today),
                       lockup=grants.page_lockup(cfg, "methods"),
                       og=grants.og_tags(cfg, f"Methodology library · {cfg['brand_name']}",
                                         "Practical clinical research methodology: study design, statistics, reporting guidelines and critical appraisal, with references.", "methodology"))
    if top:
        i, j = html.index('  <p class="intro">'), html.index('  <form class="filters"')
        html = (html[:i] + top + '\n  <h2 class="lib" id="carousels">Methodology carousels</h2>\n' + html[i:j] + html[j:])
        if cfg.get("frameworks"):
            html = html.replace("</body>", dock_block() + "\n</body>", 1)
            if not data:                             # libreria ancora vuota: niente filtri a vuoto, una riga che lo dice
                i, j = html.index('  <p class="intro">'), html.index("</form>", html.index('  <form class="filters"')) + 7
                html = (html[:i] + '  <p class="nomatch">The methodology carousels will be collected here as they are '
                        'published, each with its key points and references.</p>' + html[j:])
    return html
