"""Pagina pubblica «Latest Science»: solo i post del sabato (rubrica Clinical Insights, categoria
content.CLINICAL_CATEGORY), un concetto clinico/paziente alla volta, mai metodologia pura. Stessa archiviazione
di methodology.py (methodology.json, miniature in docs/methodology/<id>/): qui si legge e si filtra soltanto,
nessun duplicato di dati."""

from datetime import date
from html import escape
from pathlib import Path

import content
import grants

ROOT = Path(__file__).resolve().parent

CLINICAL_CATEGORY = content.CLINICAL_CATEGORY


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Latest Science: one clinical concept a week · {brand}</title>
<meta name="description" content="One real paper, one clinical lesson every Saturday: what it means for the therapeutic approach and the patient, not for study design or reporting.">
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
  .intro {{ color: var(--soft); margin: 0 0 22px; font-size: 15px; }}
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
  .nomatch {{ color: var(--soft); background: var(--card); border-radius: 18px; padding: 18px 20px; font-size: 15px; }}
  footer {{ color: var(--muted); font-size: 13px; margin-top: 36px; }}
  footer a {{ color: var(--teal); }}
</style>
</head>
<body>
<div class="bar"></div>
<main>
  {lockup}
  <a class="switch" href="index.html">&larr; Home</a><a class="switch" href="methodology.html">Design, Reporting &amp; Appraisal &rarr;</a><br>
  <span class="badge">LATEST SCIENCE</span>
  <h1>One clinical concept a week, from a real paper</h1>
  <p class="intro">Every Saturday, one new clinical paper and one lesson for practice: what it means for the
  therapeutic approach and for the patient, never a lesson on study design or reporting. Swipe through the slides
  here, no Instagram account needed.</p>
{sections}
  <footer>
    Educational content for researchers and health professionals; not medical advice. Always check the original
    reference.<br>
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


def entries(data):
    """Solo i post «Latest Science»: categoria dedicata, mai design/reporting/appraisal, i più recenti prima."""
    data = {k: e for k, e in data.items() if not e.get("duplicate_of") and e.get("category") == CLINICAL_CATEGORY}
    return sorted(data.values(), key=lambda e: e.get("date", ""), reverse=True)


def build_page(data, cfg, today=None):
    """Pagina «Latest Science»: legge la stessa archiviazione di methodology.py (cover incluse, già generate lì)
    e mostra solo i post con categoria Clinical insight."""
    today = today or date.today()
    items = entries(data)
    if not items:
        sections = '  <p class="nomatch">No «Latest Science» post yet: check back next Saturday.</p>'
    else:
        parts = []
        for e in items:
            thumb = ""
            cover_dir = ROOT / "docs" / "methodology" / e["id"]
            if cover_dir.exists():
                imgs_n = len(list(cover_dir.glob("*.jpg")))
                if imgs_n:
                    imgs = "".join(f'<img src="methodology/{e["id"]}/{k}.jpg" alt="{escape(e.get("title", ""))} – slide {k} of {imgs_n}" '
                                   f'width="720" height="900"' + (' loading="lazy"' if k > 1 else "") + ">"
                                   for k in range(1, imgs_n + 1))
                    nav = (f'<div class="nav"><button class="prev" type="button" aria-label="Previous slide">&lsaquo;</button>'
                           f'<span class="pos">{imgs_n} slides · swipe</span>'
                           f'<button class="next" type="button" aria-label="Next slide">&rsaquo;</button></div>') if imgs_n > 1 else ""
                    thumb = f'<div class="slides"><div class="strip">{imgs}</div>{nav}</div>'
            points = "".join(f'<h4>{escape(p["heading"])}</h4><p>{escape(p["body"])}</p>' for p in e.get("points", []))
            refs = "".join(f"<p>{escape(r)}</p>" for r in e.get("references", []))
            d = grants._date(e.get("date"))
            parts.append(f"""  <article class="method" id="s-{escape(e['id'])}">
    {thumb or '<div></div>'}
    <div>
      <div class="date">{grants._fmt_date(d) if d else ""}</div>
      <h3>{escape(e.get("title", ""))}</h3>
      <p class="take">{escape(e.get("takeaway", ""))}</p>
      <details><summary>Key points and references</summary>{points}{f'<div class="refs"><b>References</b>{refs}</div>' if refs else ""}</details>
    </div>
  </article>""")
        sections = "\n".join(parts)
    c = grants.site_palette(cfg)
    return PAGE.format(brand=escape(cfg["brand_name"]), handle=escape(cfg["handle"]), ig=cfg["handle"].lstrip("@"),
                       bg=c["background"], muted=c["muted"], soft=c["muted_text"],
                       teal=grants.site_accent(cfg, "science") if cfg.get("site_v4") else c["accent"],
                       sections=sections, updated=grants._fmt_date(today), lockup=grants.page_lockup(cfg, "science"),
                       og=grants.og_tags(cfg, f"Latest Science · {cfg['brand_name']}",
                                         "One real paper, one clinical lesson every Saturday: what it means for "
                                         "the therapeutic approach and the patient.", "science"))
