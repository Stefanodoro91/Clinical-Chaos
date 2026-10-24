"""Archivio pubblico dei post di metodologia: una pagina con tutti i caroselli pubblicati, i punti chiave e le reference."""

import json
import re
from datetime import date
from html import escape
from pathlib import Path

from PIL import Image

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
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Methodology library · {brand}</title>
<meta name="description" content="Practical clinical research methodology in short carousels: key points and references for every topic we have covered.">
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
  [hidden] {{ display: none !important; }}
  footer {{ color: var(--muted); font-size: 13px; margin-top: 36px; }}
  footer a {{ color: var(--teal); }}
</style>
</head>
<body>
<div class="bar"></div>
<main>
  <a class="switch" href="index.html">&larr; Home</a><a class="switch" href="calls.html">Funding calls &rarr;</a><a class="switch" href="positions.html">Academic positions &rarr;</a><br>
  <span class="badge">METHODOLOGY LIBRARY</span>
  <h1>Clinical research methodology, made practical</h1>
  <p class="intro">Every methodology carousel we have published: swipe through the slides here, no Instagram account needed.
  Key points and references under each one. New topics every day.</p>
  <form class="filters" role="search" aria-label="Filter topics" data-noun="topics" onsubmit="return false">
    <label>Search<input type="search" name="q" placeholder="Keyword (e.g. blinding, p-value, regression)" autocomplete="off"></label>
    <label>Topic<select name="area"><option value="">All topics</option>{cat_opts}</select></label>
    <div class="status"><span class="count" aria-live="polite">{n} topics</span><button type="reset" hidden>Clear filters</button></div>
  </form>
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


def build_page(data, cfg, today=None):
    today = today or date.today()
    THUMBS.mkdir(parents=True, exist_ok=True)
    cats = {}
    data = {k: e for k, e in data.items() if not e.get("duplicate_of")}      # post ripetuti: una sola voce
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
    c = cfg["colors"]
    cat_opts = "".join(f'<option value="{_slug(k)}">{escape(k)}</option>' for k in sorted(cats))
    return PAGE.format(brand=escape(cfg["brand_name"]), handle=escape(cfg["handle"]), ig=cfg["handle"].lstrip("@"),
                       bg=c["background"], muted=c["muted"], soft=c["muted_text"], teal=c["accent"], cat_opts=cat_opts,
                       n=len(data), sections="\n".join(sections), updated=grants._fmt_date(today),
                       og=grants.og_tags(cfg, f"Methodology library · {cfg['brand_name']}",
                                         "Practical clinical research methodology: key points and references.", "methodology"))
