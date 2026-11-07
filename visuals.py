"""Immagini specifiche per le slide dei post di metodologia e Latest Science, senza crediti per immagini.

1. Schemi disegnati dal bot: un modello leggero sceglie, slide per slide, lo schema che mostra il concetto
   (confronto, flusso, albero decisionale, barre, distribuzione, linea del tempo) e ne scrive le etichette con le
   parole e i numeri della slide; il bot lo disegna nello stile del brand (draw()). Un numero che non è nel testo
   della slide fa scartare lo schema: niente dati inventati (salvo la distribuzione, marcata «illustrative data»).
2. Figure dell'articolo (Latest Science): con licenza CC BY / CC BY-SA / CC0 il bot ritaglia dal PDF le figure con la
   loro didascalia (paper_figures()); il modello le assegna solo alla slide di cui mostrano il risultato. Sulla slide
   la figura compare intera, su fondo bianco, con «Figure N · Autore et al., anno · licenza».
3. Foto: solo per le slide in cui una scena reale rende il concetto (il modello lo decide e scrive la ricerca);
   altrimenti la slide resta di solo testo. Mai più foto generiche per riempire.

plan(post) scrive in ogni slide la chiave «visual»: {"type": "diagram"|"figure"|"photo"|"none", ...}; cards.py la usa
al posto della vecchia regola «immagine sulle slide pari»."""
import io
import re
import statistics

from PIL import Image, ImageDraw

import content

FIGURES = {}            # id del post → [{"n", "caption", "image", "credit"}]
MAX_VISUALS = 3
OK_LICENSES = ("/by/", "/by-sa/", "/zero/", "publicdomain")
RX_NUM = re.compile(r"(?<![\w.])[-−]?\d+(?:[.,]\d+)?")


# ---------------------------------------------------------------- 2. figure dell'articolo
def figure_license_ok(meta):
    lic = (meta or {}).get("license") or ""
    return any(x in lic for x in OK_LICENSES) and "/nd" not in lic and "-nd" not in lic


def paper_figures(pdf_bytes, max_figures=8, zoom=3):
    """Figure del PDF con la loro didascalia: [{"n": 2, "caption": "Figure 2. …", "image": PIL}]. Una figura è la zona
    grafica (immagini e disegni vettoriali) subito sopra una didascalia che comincia con «Figure N» o «Fig. N»."""
    import pymupdf
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    out, seen = [], set()
    for page in doc:
        blocks = [b for b in page.get_text("blocks") if b[6] == 0]
        caps = []
        for b in blocks:
            text = " ".join(b[4].split())
            m = re.match(r"^(?:Figure|Fig\.?)\s*(\d+)[.:|\s]", text, re.I)
            if m and int(m.group(1)) not in seen:
                caps.append((int(m.group(1)), pymupdf.Rect(b[:4]), text))
        if not caps:
            continue
        graphics = [pymupdf.Rect(i["bbox"]) for i in page.get_image_info() if i.get("bbox")]
        try:
            graphics += [pymupdf.Rect(r) for r in page.cluster_drawings()]
        except Exception:
            pass
        graphics = [g for g in graphics if g.width > 20 and g.height > 20 and g.width < page.rect.width * 1.01]
        cap_tops = [c.y0 for _, c, _ in caps]
        for n, cap, text in caps:
            # la parte grafica più vicina sopra la didascalia, senza un'altra didascalia in mezzo
            above = [g for g in graphics if cap.y0 - 260 <= g.y1 <= cap.y0 + 8
                     and min(g.x1, cap.x1 + 40) - max(g.x0, cap.x0 - 40) > 0
                     and not any(g.y1 <= t < cap.y0 - 1 for t in cap_tops)]
            if not above:
                continue
            region = pymupdf.Rect(max(above, key=lambda g: g.y1))
            grown = True                       # poi solo le parti che la toccano (pannelli, legende, assi)
            while grown:
                grown = False
                for g in graphics:
                    if g.y1 <= cap.y0 + 8 and not g in region and (g & (region + (-8, -8, 8, 8))) \
                            and not any(min(g.y0, region.y0) <= t < cap.y0 - 1 and t > g.y1 for t in cap_tops):
                        region |= g
                        grown = True
            region = (region + (-6, -6, 6, 4)) & page.rect
            if region.width < 140 or region.height < 90 or region.height > page.rect.height * 0.75:
                continue
            inside = [g for g in graphics if g in region + (-2, -2, 2, 2)]
            loose = [wd for wd in page.get_text("words", clip=region)            # testo corrente finito nel ritaglio
                     if not any(pymupdf.Rect(wd[:4]).intersects(g) for g in inside)]
            if len(loose) > 40:
                continue
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=region)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            seen.add(n)
            out.append({"n": n, "caption": text[:400], "image": img})
            if len(out) >= max_figures:
                return out
    return sorted(out, key=lambda f: f["n"])


def figure_panel(fig, credit, w, h):
    """La figura intera (mai tagliata) su fondo bianco, con la riga dei crediti sotto."""
    import cards
    panel = Image.new("RGB", (w, h), "#FFFFFF")
    d = ImageDraw.Draw(panel)
    f = cards.font("SemiBold", 24)
    line = f"Figure {fig['n']} · {credit}"
    while d.textlength(line, font=f) > w - 40 and len(line) > 20:
        line = line[:-2]
    pad, foot = 18, 44
    im = fig["image"].copy()
    im.thumbnail((w - 2 * pad, h - pad - foot), Image.LANCZOS)
    panel.paste(im, ((w - im.width) // 2, pad + (h - pad - foot - im.height) // 2))
    d.text((20, h - foot + 8), line, font=f, fill="#3A3A3A")
    return panel


# ---------------------------------------------------------------- 1. schemi disegnati
def _fonts():
    import cards
    return cards.font


def _wrap(d, text, fnt, max_w):
    words, lines, cur = str(text or "").split(), [], ""
    for w_ in words:
        t = f"{cur} {w_}".strip()
        if d.textlength(t, font=fnt) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines


def _fit(d, text, weight, start, minimum, max_w, max_h, spacing=1.2):
    font = _fonts()
    size = start
    while True:
        f = font(weight, size)
        lines = _wrap(d, text, f, max_w)
        if len(lines) * size * spacing <= max_h or size <= minimum:
            return f, lines, size
        size -= 2


def _text_block(d, text, weight, start, minimum, box, color, align="center", valign="middle", spacing=1.2):
    x0, y0, x1, y1 = box
    f, lines, size = _fit(d, text, weight, start, minimum, x1 - x0, y1 - y0, spacing)
    total = len(lines) * size * spacing
    y = y0 + ((y1 - y0 - total) / 2 if valign == "middle" else 0)
    for ln in lines:
        tw = d.textlength(ln, font=f)
        x = x0 + ((x1 - x0 - tw) / 2 if align == "center" else 0)
        d.text((x, y), ln, font=f, fill=color)
        y += size * spacing
    return y


def _box(d, box, outline, fill=None, width=3, r=22):
    d.rounded_rectangle(box, radius=r, outline=outline, fill=fill, width=width)


def _arrow(d, a, b, color, width=4, head=14):
    import math
    d.line([a, b], fill=color, width=width)
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    for s in (-1, 1):
        d.line([b, (b[0] - head * math.cos(ang + s * 0.45), b[1] - head * math.sin(ang + s * 0.45))], fill=color, width=width)


def _mix(c1, c2, k):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * k):02X}" for x, y in zip(a, b))


def draw(spec, w, h, colors):
    """Disegna lo schema `spec` in un'immagine w×h con i colori della slide (fondo, testo, accento)."""
    bg, ink, acc = colors.get("background", "#0A0A0A"), colors.get("text", "#FFFFFF"), colors.get("accent", "#88B0F8")
    soft = colors.get("muted_text", _mix(ink, bg, 0.25))
    faint = _mix(ink, bg, 0.72)
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    kind = spec.get("kind")
    P = 34
    if kind == "compare":
        gap = 26
        cw = (w - 2 * P - gap) / 2
        for side, x in (("left", P), ("right", P + cw + gap)):
            good = side == "right"
            col = acc if good else soft
            _box(d, (x, P, x + cw, h - P), col, None, 4 if good else 2)
            mark = "✓" if good else "✗"
            title = spec.get(f"{side}_title", "")
            _text_block(d, f"{title}", "ExtraBold", 38, 24, (x + 24, P + 18, x + cw - 24, P + 96), col)
            items = [str(i) for i in (spec.get(f"{side}_items") or [])][:4]
            if items:
                rh = min(110, (h - 2 * P - 130) / len(items))
                for k, it in enumerate(items):
                    y0 = P + 120 + k * rh
                    d.text((x + 26, y0 + 4), mark, font=_fonts()("Bold", 30), fill=col)
                    _text_block(d, it, "Regular", 30, 20, (x + 70, y0, x + cw - 22, y0 + rh - 8), ink, "left", "top")
    elif kind == "flow":
        steps = (spec.get("steps") or [])[:5]
        n = max(1, len(steps))
        gap = 46
        bw = (w - 2 * P - gap * (n - 1)) / n
        for k, s in enumerate(steps):
            x = P + k * (bw + gap)
            last = k == n - 1
            _box(d, (x, P + 40, x + bw, h - P - 40), acc if last else soft, None, 4 if last else 2)
            label = s.get("label", "") if isinstance(s, dict) else str(s)
            note = s.get("note", "") if isinstance(s, dict) else ""
            yb = _text_block(d, label, "ExtraBold", 34, 20, (x + 14, P + 60, x + bw - 14, P + 60 + (h - 2 * P - 120) * (0.45 if note else 1)),
                             acc if last else ink)
            if note:
                _text_block(d, note, "Regular", 26, 18, (x + 14, yb + 10, x + bw - 14, h - P - 56), soft, valign="top")
            if not last:
                _arrow(d, (x + bw + 8, h / 2), (x + bw + gap - 8, h / 2), acc)
    elif kind == "tree":
        branches = (spec.get("branches") or [])[:4]
        n = max(1, len(branches))
        rw, rh = min(w * 0.62, 620), 120
        _box(d, ((w - rw) / 2, P, (w + rw) / 2, P + rh), ink, None, 3)
        _text_block(d, spec.get("root", ""), "ExtraBold", 34, 20, ((w - rw) / 2 + 18, P + 8, (w + rw) / 2 - 18, P + rh - 8), ink)
        gap = 22
        lw = (w - 2 * P - gap * (n - 1)) / n
        ly0 = h - P - 150
        for k, b in enumerate(branches):
            x = P + k * (lw + gap)
            cx = x + lw / 2
            d.line([(w / 2, P + rh), (w / 2, P + rh + 22), (cx, P + rh + 22), (cx, ly0 - 8)], fill=faint, width=3)
            d.polygon([(cx - 9, ly0 - 18), (cx + 9, ly0 - 18), (cx, ly0 - 4)], fill=acc)
            ef = _fonts()("SemiBold", 26)
            et = str(b.get("edge", ""))
            while d.textlength(et, font=ef) > lw - 12 and len(et) > 4:
                et = et[:-2].rstrip() + "…"
            tw_ = d.textlength(et, font=ef)
            my = (P + rh + 22 + ly0 - 18) / 2
            d.rectangle((cx - tw_ / 2 - 8, my - 18, cx + tw_ / 2 + 8, my + 18), fill=bg)
            d.text((cx, my), et, font=ef, fill=soft, anchor="mm")
            _box(d, (x, ly0, x + lw, h - P), acc, None, 4)
            _text_block(d, b.get("leaf", ""), "ExtraBold", 32, 18, (x + 12, ly0 + 8, x + lw - 12, h - P - 8), acc)
    elif kind == "bars":
        bars = [b for b in (spec.get("bars") or []) if _num(b.get("value")) is not None][:5]
        thr = spec.get("threshold") or {}
        tv = _num(thr.get("value"))
        vmax = max([_num(b["value"]) for b in bars] + ([tv] if tv is not None else []) + [1e-9])
        lab_w = int(w * 0.34)
        x0, x1 = P + lab_w + 16, w - P - 110
        top, bot = P + 20, h - P - (50 if tv is not None else 10)
        rh = (bot - top) / max(1, len(bars))
        unit = spec.get("unit", "")
        for k, b in enumerate(bars):
            y = top + k * rh
            _text_block(d, b.get("label", ""), "SemiBold", 30, 18, (P, y + 6, P + lab_w, y + rh - 6), ink, "left")
            v = _num(b["value"])
            bw = (x1 - x0) * max(0, v) / vmax
            d.rounded_rectangle((x0, y + rh * 0.22, x0 + max(bw, 6), y + rh * 0.78), radius=10, fill=acc)
            d.text((x0 + bw + 14, y + rh / 2 - 20), f"{b['value']}{(' ' + unit) if unit else ''}", font=_fonts()("ExtraBold", 34), fill=ink)
        if tv is not None:
            tx = x0 + (x1 - x0) * tv / vmax
            for yy in range(int(top), int(bot), 18):
                d.line([(tx, yy), (tx, yy + 10)], fill=soft, width=3)
            tl = f"{thr.get('label', 'threshold')}: {thr['value']}"
            tf = _fonts()("SemiBold", 26)
            lx = min(max(tx - d.textlength(tl, font=tf) / 2, P), w - P - d.textlength(tl, font=tf))
            d.text((lx, bot + 8), tl, font=tf, fill=soft)
    elif kind == "distribution":
        vals = [v for v in (_num(x) for x in (spec.get("values") or [])) if v is not None][:40]
        if len(vals) < 3:
            return None
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1
        x0, x1, base = P + 30, w - P - 30, h * 0.52
        X = lambda v: x0 + (x1 - x0) * (v - lo) / span
        d.line([(x0, base + 40), (x1, base + 40)], fill=faint, width=3)
        counts = {}
        for v in vals:
            px = round(X(v) / 22)
            counts[px] = counts.get(px, 0) + 1
            cy = base + 20 - (counts[px] - 1) * 30
            d.ellipse((X(v) - 12, cy - 12, X(v) + 12, cy + 12), fill=soft)
        mean, med = statistics.mean(vals), statistics.median(vals)
        lf = _fonts()("ExtraBold", 30)
        for j, (v, lab, col) in enumerate(((med, "median", ink), (mean, "mean", acc))):
            d.line([(X(v), base + 40), (X(v), base - 140)], fill=col, width=5)
            ly = P + 18 + j * 46                   # legenda in alto a destra: le etichette non si sovrappongono mai
            d.line([(w - P - 300, ly + 18), (w - P - 250, ly + 18)], fill=col, width=5)
            d.text((w - P - 236, ly + 18), f"{lab} {v:.3g}", font=lf, fill=col, anchor="lm")
        if spec.get("unit"):
            d.text((x1, base + 56), spec["unit"], font=_fonts()("Regular", 24), fill=soft, anchor="ra")
        d.text((x0, h - P), "illustrative data", font=_fonts()("Regular", 22), fill=faint, anchor="ld")
    elif kind == "timeline":
        pts = (spec.get("points") or [])[:5]
        n = max(1, len(pts))
        y = h * 0.42
        x0, x1 = P + 40, w - P - 40
        _arrow(d, (x0 - 20, y), (x1 + 24, y), soft, 4, 16)
        for k, p in enumerate(pts):
            x = x0 + (x1 - x0) * (k / (n - 1) if n > 1 else 0.5)
            d.ellipse((x - 14, y - 14, x + 14, y + 14), fill=acc)
            cw = min((x1 - x0) / max(1, n - 1) if n > 1 else w - 2 * P, 300)
            bx0 = min(max(x - cw / 2, P - 20), w - P + 20 - cw)        # dentro il riquadro anche ai due estremi
            al = "left" if k == 0 and n > 1 else "center"
            _text_block(d, p.get("label", ""), "ExtraBold", 32, 20, (bx0, y - 120, bx0 + cw, y - 28), ink, al)
            if p.get("note"):
                _text_block(d, p["note"], "Regular", 26, 18, (bx0, y + 30, bx0 + cw, h - P), soft, al, valign="top")
    else:
        return None
    return img


def _num(x):
    try:
        return float(str(x).replace(",", ".").replace("−", "-").strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def _labels(spec):
    """Tutto il testo che lo schema mostra (per controllare i numeri)."""
    out = []
    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k not in ("values", "slide", "type", "why", "figure", "photo_query"):
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif v is not None and not isinstance(v, bool):
            out.append(str(v))
    walk(spec)
    return " ".join(out)


def numbers_ok(spec, text):
    """Ogni numero dello schema (tranne i valori illustrativi della distribuzione) deve comparire nel testo."""
    have = {n.replace(",", ".").replace("−", "-").lstrip("-") for n in RX_NUM.findall(text or "")}
    for n in RX_NUM.findall(_labels(spec)):
        k = n.replace(",", ".").replace("−", "-").lstrip("-")
        if k not in have and k.rstrip("0").rstrip(".") not in {h.rstrip("0").rstrip(".") for h in have}:
            return False
    return True


# ---------------------------------------------------------------- piano delle immagini (un modello leggero)
PLAN_PROMPT = """You choose the visual for each slide of an Instagram carousel for clinical researchers. A visual is
worth adding ONLY when it makes the slide's own idea clearer at a glance. At most {max_visuals} visuals in the whole
carousel; most slides stay text-only ("none").

For each slide choose one:
- "diagram": a simple schematic drawn by our software. Pick the kind that shows the slide's idea:
  "compare" (two columns, e.g. vague vs well-defined, wrong vs right: left_title, left_items, right_title,
  right_items; the right column is the good one), "flow" (2-5 steps in order: steps [{{label, note}}]),
  "tree" (a decision: root question, 2-4 branches [{{edge, leaf}}]), "bars" (2-5 values to compare, with unit and an
  optional threshold {{label, value}}: ONLY numbers written in the slide), "distribution" (a strip of 8-25 illustrative
  values showing skew or an outlier, with unit: only for slides about distributions, means, medians, outliers),
  "timeline" (2-5 time points [{{label, note}}]).
  Labels: 1-6 words each, in English, taken from the slide's words. Never a number that is not in the slide text.
- "figure": a figure of the source paper (listed below with its caption) that shows EXACTLY the result the slide
  states. Give its number. Never for a slide whose message the figure does not show.
- "photo": a real stock photo, only when a real scene (patients, therapy, clinicians, devices) shows the slide's
  concept better than words; give photo_query (2-4 English keywords). Never for abstract or statistical ideas.
- "none".
Prefer "figure" when one fits, then "diagram", then "photo".

CAROUSEL: {title}
{slides}

PAPER FIGURES: {figures}"""

PLAN_SCHEMA = {"type": "OBJECT", "properties": {"slides": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "slide": {"type": "INTEGER"}, "type": {"type": "STRING", "enum": ["diagram", "figure", "photo", "none"]},
    "kind": {"type": "STRING"}, "figure": {"type": "INTEGER"}, "photo_query": {"type": "STRING"},
    "left_title": {"type": "STRING"}, "left_items": {"type": "ARRAY", "items": {"type": "STRING"}},
    "right_title": {"type": "STRING"}, "right_items": {"type": "ARRAY", "items": {"type": "STRING"}},
    "steps": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"label": {"type": "STRING"}, "note": {"type": "STRING"}}}},
    "root": {"type": "STRING"},
    "branches": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"edge": {"type": "STRING"}, "leaf": {"type": "STRING"}}}},
    "bars": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"label": {"type": "STRING"}, "value": {"type": "STRING"}}}},
    "unit": {"type": "STRING"},
    "threshold": {"type": "OBJECT", "properties": {"label": {"type": "STRING"}, "value": {"type": "STRING"}}},
    "values": {"type": "ARRAY", "items": {"type": "NUMBER"}},
    "points": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"label": {"type": "STRING"}, "note": {"type": "STRING"}}}},
    "why": {"type": "STRING"}}, "required": ["slide", "type"]}}}, "required": ["slides"]}

KINDS = {"compare", "flow", "tree", "bars", "distribution", "timeline"}


def _valid_diagram(spec):
    k = spec.get("kind")
    if k not in KINDS:
        return False
    need = {"compare": lambda s: s.get("left_items") and s.get("right_items"),
            "flow": lambda s: 2 <= len(s.get("steps") or []) <= 5,
            "tree": lambda s: s.get("root") and 2 <= len(s.get("branches") or []) <= 4,
            "bars": lambda s: 2 <= len([b for b in s.get("bars") or [] if _num(b.get("value")) is not None]) <= 5,
            "distribution": lambda s: len([v for v in s.get("values") or [] if _num(v) is not None]) >= 5,
            "timeline": lambda s: 2 <= len(s.get("points") or []) <= 5}
    return bool(need[k](spec))


def plan(post, figures=None, credit=""):
    """Sceglie l'immagine di ogni slide e la scrive in slide["visual"]. Senza modello disponibile: tutte «none»
    (la slide resta di solo testo, come oggi quando un'immagine non è adatta)."""
    slides = post.get("slides") or []
    figures = [f for f in figures or [] if f["image"].height <= f["image"].width * 1.25]   # leggibili sul telefono
    if figures:
        FIGURES[post.get("id")] = [dict(f, credit=credit) for f in figures]
    listing = "\n".join(f"{i}. {s.get('heading', '')} — {s.get('body', '')}" for i, s in enumerate(slides, 1))
    figs = "; ".join(f"[{f['n']}] {f['caption'][:240]}" for f in figures) or "none"
    try:
        out = content.gemini_json([{"text": PLAN_PROMPT.format(max_visuals=MAX_VISUALS, title=post.get("title", ""),
                                                               slides=listing, figures=figs)}],
                                  PLAN_SCHEMA, 0.2, task="schemi slide")
    except Exception as e:
        print(f"  Piano immagini non disponibile ({str(e)[:120]}): slide di solo testo")
        out = {"slides": []}
    used, fig_ids = 0, {f["n"] for f in figures}
    for s in slides:
        s["visual"] = {"type": "none"}
    for v in out.get("slides") or []:
        i = (v.get("slide") or 0) - 1
        if not (0 <= i < len(slides)) or used >= MAX_VISUALS:
            continue
        s, t = slides[i], v.get("type")
        text = f"{s.get('heading', '')} {s.get('body', '')}"
        if t == "figure" and v.get("figure") in fig_ids:
            s["visual"] = {"type": "figure", "figure": v["figure"]}
        elif t == "diagram" and _valid_diagram(v) and numbers_ok(v, text):
            s["visual"] = {"type": "diagram", **{k: x for k, x in v.items() if k not in ("slide", "type", "why")}}
        elif t == "photo" and (v.get("photo_query") or "").strip():
            s["visual"] = {"type": "photo"}
            s["photo_query"] = v["photo_query"].strip()
        else:
            continue
        used += 1
        print(f"  Slide {i + 1}: {s['visual']['type']}" + (f" ({s['visual'].get('kind') or s['visual'].get('figure')})"
                                                          if s["visual"]["type"] in ("diagram", "figure") else ""))
    post["visuals_planned"] = True
    return post


def picture_for(post, slide, colors):
    """Funzione (w, h) → immagine per la slide, oppure None se la slide resta di solo testo."""
    v = slide.get("visual") or {}
    if v.get("type") == "diagram":
        return lambda w, h: draw(v, w, h, colors)
    if v.get("type") == "figure":
        fig = next((f for f in FIGURES.get(post.get("id"), []) if f["n"] == v.get("figure")), None)
        if fig:
            return lambda w, h: figure_panel(fig, fig.get("credit", ""), w, h)
    return None
