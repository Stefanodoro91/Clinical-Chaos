"""Disegna le slide del carosello (1080x1350, formato 4:5) a partire da un post in coda."""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

import images

W, H = 1080, 1350
MARGIN = 100
FONTS = Path(__file__).resolve().parent / "fonts"
_font_cache = {}


def font(weight, size):
    key = (weight, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(str(FONTS / f"Inter-{weight}.ttf"), size)
    return _font_cache[key]


def wrap(draw, text, fnt, max_w):
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            test = f"{line} {word}".strip()
            if draw.textlength(test, font=fnt) <= max_w:
                line = test
            else:
                if line:
                    lines.append(line)
                line = word
        lines.append(line)
    return lines


def fit(draw, text, weight, start, minimum, max_w, max_h, spacing):
    """Riduce il corpo del testo finché non entra nello spazio disponibile."""
    size = start
    while True:
        fnt = font(weight, size)
        lines = wrap(draw, text, fnt, max_w)
        too_wide = any(draw.textlength(l, font=fnt) > max_w for l in lines)   # una parola lunga non deve uscire dal margine
        if (len(lines) * size * spacing <= max_h and not too_wide) or size <= minimum:
            return fnt, lines, size
        size -= 2


def draw_lines(draw, lines, fnt, size, x, y, color, spacing):
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=color)
        y += size * spacing
    return y


PAPER, INK_MUTED = "#F3F6F9", "#5B7186"          # copertina e chiusura «in negativo»
DARK_ACCENT = {"#3DD9C1": "#1C8C7B", "#FFB547": "#A86A12", "#A78BFA": "#6D4FD8", "#FF7A59": "#C2410C"}   # accento leggibile su fondo chiaro


def _norm_word(w):
    return "".join(ch for ch in w.lower() if ch.isalnum())


def _highlight_span(words, phrase):
    """Indici delle parole di `words` che formano `phrase` (confronto senza punteggiatura e maiuscole)."""
    target = [_norm_word(w) for w in (phrase or "").split() if _norm_word(w)]
    if not target:
        return set()
    norm = [_norm_word(w) for w in words]
    for i in range(len(norm) - len(target) + 1):
        if norm[i:i + len(target)] == target:
            return set(range(i, i + len(target)))
    return set()


def draw_rich(draw, text, phrase, fnt, size, x, y, max_w, color, spacing, mark, mark_text=None, half=False):
    """Scrive il testo a capo come draw_lines ed evidenzia `phrase` con un rettangolo colore `mark`.
    half=True: evidenziatore sulla metà bassa delle lettere (fondo chiaro); altrimenti a tutta altezza
    con il testo evidenziato in `mark_text` (fondo scuro, per il contrasto)."""
    words = text.split()
    marked = _highlight_span(words, phrase)
    lines, line = [], []
    for i, w in enumerate(words):
        test = " ".join(words[j] for j in line + [i])
        if line and draw.textlength(test, font=fnt) > max_w:
            lines.append(line)
            line = [i]
        else:
            line.append(i)
    if line:
        lines.append(line)
    space = draw.textlength(" ", font=fnt)
    for line in lines:
        xs, cx = {}, x
        for i in line:
            xs[i] = (cx, cx + draw.textlength(words[i], font=fnt))
            cx = xs[i][1] + space
        run = [i for i in line if i in marked]
        if run:
            x0, x1 = xs[run[0]][0] - 8, xs[run[-1]][1] + 8
            top, bottom = (y + size * .55, y + size * 1.1) if half else (y + size * .08, y + size * 1.16)
            draw.rectangle((x0, top, x1, bottom), fill=mark)
        for i in line:
            fill = mark_text if (i in marked and mark_text and not half) else color
            draw.text((xs[i][0], y), words[i], font=fnt, fill=fill)
        y += size * spacing
    return y


def source_line(draw, slide, cfg):
    """Citazione breve (es. «Bang et al., 2004») sopra il piè di pagina."""
    if slide.get("source"):
        f = font("Regular", 26)
        draw.text((MARGIN, H - 165), f"Source: {slide['source']}"[:80], font=f, fill=cfg["colors"]["muted"])


ASSETS = Path(__file__).resolve().parent / "assets"
_logo_cache = {}


def paste_logo(img, name, x, y, height=None, width=None):
    """Incolla assets/<name>.png (trasparente) alto `height` o largo `width`; restituisce (larghezza, altezza)."""
    path = ASSETS / f"{name}.png"
    if not path.exists():
        return None
    key = (name, height, width)
    if key not in _logo_cache:
        logo = Image.open(path).convert("RGBA")
        ratio = (height / logo.height) if height else (width / logo.width)
        _logo_cache[key] = logo.resize((round(logo.width * ratio), round(logo.height * ratio)), Image.LANCZOS)
    logo = _logo_cache[key]
    img.paste(logo, (int(x), int(y)), logo)
    return logo.size


def logo_lockup(img, d, x, y, cfg, light=False):
    """Simbolo e scritta affiancati (copertina). Senza i file del logo usa il monogramma provvisorio."""
    suffix = "-light" if light else ""
    size = paste_logo(img, f"logo-symbol{suffix}", x, y, height=170)
    if not size:
        logo_mark(img, d, x, y, 72, cfg["colors"]["background"], PAPER, cfg)
        return 72
    paste_logo(img, f"logo-wordmark{suffix}", x + size[0] + 24, y + 22, height=126)
    return 170


def logo_mark(img, d, x, y, size, fg, bg, cfg):
    """Logo in alto a sinistra: il file indicato in config «logo_path», altrimenti un monogramma provvisorio."""
    path = Path(__file__).resolve().parent / (cfg.get("logo_path") or "logo.png")
    if path.exists():
        logo = Image.open(path).convert("RGBA")
        logo.thumbnail((size, size), Image.LANCZOS)
        img.paste(logo, (x, y), logo)
        return
    d.ellipse((x, y, x + size, y + size), fill=fg)
    f = font("ExtraBold", int(size * 0.34))
    d.text((x + (size - d.textlength("CRC", font=f)) / 2, y + size * 0.3), "CRC", font=f, fill=bg)


def light_canvas(cfg, index, total):
    c = cfg["colors"]
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 14), fill=c["accent"])
    foot = font("SemiBold", 30)
    d.text((MARGIN, H - 110), cfg["handle"], font=foot, fill=INK_MUTED)
    page = f"{index}/{total}"
    d.text((W - MARGIN - d.textlength(page, font=foot), H - 110), page, font=foot, fill=INK_MUTED)
    return img, d


def canvas(cfg, index, total):
    c = cfg["colors"]
    img = Image.new("RGB", (W, H), c["background"])
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 14), fill=c["accent"])
    # piè di pagina: handle a sinistra, numero slide a destra
    foot = font("SemiBold", 30)
    d.text((MARGIN, H - 110), cfg["handle"], font=foot, fill=c["muted"])
    page = f"{index}/{total}"
    d.text((W - MARGIN - d.textlength(page, font=foot), H - 110), page, font=foot, fill=c["muted"])
    return img, d


def cover(post, cfg, total):
    """Copertina in negativo: fondo chiaro, logo, etichetta del tema, titolo con evidenziatore."""
    c = cfg["colors"]
    navy = c["background"]
    img, d = light_canvas(cfg, 1, total)
    logo_h = logo_lockup(img, d, MARGIN - 10, 80, cfg)
    pill_top = 80 + logo_h + 50
    pill_f = font("Bold", 30)
    label = post.get("category", "Research methods").upper()
    pw = d.textlength(label, font=pill_f) + 56
    d.rounded_rectangle((MARGIN, pill_top, MARGIN + pw, pill_top + 60), radius=30, outline=navy, width=3)
    d.text((MARGIN + 28, pill_top + 11), label, font=pill_f, fill=navy)
    title_top = pill_top + 110
    fnt, lines, size = fit(d, post["title"], "ExtraBold", 104, 60, W - 2 * MARGIN, H - 300 - title_top, 1.12)
    phrase = post.get("title_highlight") or (lines[-1] if lines else "")
    draw_rich(d, post["title"], phrase, fnt, size, MARGIN, title_top, W - 2 * MARGIN, navy, 1.12, c["accent"], half=True)
    d.text((MARGIN, H - 240), "Swipe  →", font=font("Bold", 40), fill=navy)
    return img


def grant_cover(post, cfg, total):
    """Copertina dei bandi in negativo: «OPEN CALL», ente, titolo evidenziato e scadenza."""
    c = cfg["colors"]
    navy = c["background"]
    img, d = light_canvas(cfg, 1, total)
    badge_f = font("ExtraBold", 36)
    bw = d.textlength("OPEN CALL", font=badge_f) + 64
    d.rounded_rectangle((MARGIN, 150, MARGIN + bw, 220), radius=35, fill=c["accent"])
    d.text((MARGIN + 32, 162), "OPEN CALL", font=badge_f, fill=navy)
    paste_logo(img, "logo-symbol", W - MARGIN - 120, 120, height=120)
    y = 260
    if post.get("funder"):
        ff, fl, fs = fit(d, post["funder"], "SemiBold", 38, 28, W - 2 * MARGIN, 100, 1.25)
        y = draw_lines(d, fl, ff, fs, MARGIN, y, INK_MUTED, 1.25) + 30
    box_top = H - 470
    fnt, lines, size = fit(d, post["title"], "ExtraBold", 88, 50, W - 2 * MARGIN, box_top - y - 60, 1.15)
    phrase = post.get("title_highlight") or (lines[-1] if lines else "")
    draw_rich(d, post["title"], phrase, fnt, size, MARGIN, y, W - 2 * MARGIN, navy, 1.15, c["accent"], half=True)
    if post.get("deadline"):
        d.rounded_rectangle((MARGIN, box_top, W - MARGIN, box_top + 190), radius=28, fill=navy)
        d.text((MARGIN + 50, box_top + 32), "DEADLINE", font=font("Bold", 30), fill=c["accent"])
        d.text((MARGIN + 50, box_top + 80), post["deadline"], font=font("ExtraBold", 70), fill="#FFFFFF")
    d.text((MARGIN, H - 220), "Swipe  →", font=font("Bold", 40), fill=navy)
    return img


def content(slide, number, cfg, index, total):
    c = cfg["colors"]
    img, d = canvas(cfg, index, total)
    hf, hl, hs = fit(d, slide["heading"], "Bold", 64, 42, W - 2 * MARGIN, 260, 1.2)
    head_h = len(hl) * hs * 1.2
    bf, bl, bs = fit(d, slide["body"], "Regular", 46, 30, W - 2 * MARGIN, H - 170 - 180 - head_h - 220, 1.45)
    block = 180 + head_h + 40 + len(bl) * bs * 1.45
    top = max(150, (H - block) / 2 - 50)   # blocco centrato in verticale
    d.text((MARGIN, top), f"{number:02d}", font=font("ExtraBold", 120), fill=c["accent"])
    y = draw_lines(d, hl, hf, hs, MARGIN, top + 180, c["text"], 1.2) + 40
    draw_rich(d, slide["body"], slide.get("highlight"), bf, bs, MARGIN, y, W - 2 * MARGIN,
              c["muted_text"], 1.45, c["accent"], c["background"])
    source_line(d, slide, cfg)
    return img


def _rounded(picture, w, h, radius):
    """Ritaglia l'immagine a w×h e ne arrotonda gli angoli."""
    pic = ImageOps.fit(picture, (w, h), Image.LANCZOS)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    return pic, mask


def illustrated(slide, number, cfg, index, total, picture):
    """Slide con testo e immagine: numero e titolo in alto, illustrazione al centro, spiegazione sotto."""
    c = cfg["colors"]
    img, d = canvas(cfg, index, total)
    text_w = W - 2 * MARGIN
    top, bottom = 90, H - (190 if slide.get("source") else 150)   # spazio utile sopra il piè di pagina

    d.text((MARGIN, top), f"{number:02d}", font=font("ExtraBold", 72), fill=c["accent"])
    hf, hl, hs = fit(d, slide["heading"], "Bold", 54, 38, text_w, 140, 1.2)
    y = draw_lines(d, hl, hf, hs, MARGIN, top + 100, c["text"], 1.2) + 30

    # il testo ha la precedenza: l'immagine occupa lo spazio che resta (tra 360 e 560 px di altezza)
    bf, bl, bs = fit(d, slide["body"], "Regular", 40, 28, text_w, bottom - y - 360 - 70, 1.4)
    body_h = len(bl) * bs * 1.4
    pic_h = int(max(360, min(560, bottom - y - 70 - body_h)))

    pic, mask = _rounded(picture, text_w, pic_h, 28)
    img.paste(pic, (MARGIN, int(y)), mask)
    d.rounded_rectangle((MARGIN, int(y), W - MARGIN, int(y) + pic_h), radius=28, outline=c["accent"], width=3)

    draw_rich(d, slide["body"], slide.get("highlight"), bf, bs, MARGIN, y + pic_h + 40, text_w,
              c["muted_text"], 1.4, c["accent"], c["background"])
    source_line(d, slide, cfg)
    return img


def facts_slide(post, cfg, index, total):
    """Slide dei dati chiave (bandi): etichetta in turchese, valore in bianco, una voce sotto l'altra."""
    c = cfg["colors"]
    img, d = canvas(cfg, index, total)
    d.text((MARGIN, 150), "KEY FACTS", font=font("Bold", 34), fill=c["accent"])
    facts = post["facts"]
    text_w = W - 2 * MARGIN
    space = H - 150 - 260          # tra il titolo e il piè di pagina
    for size in range(42, 25, -2):
        label_f, value_f = font("SemiBold", max(22, size - 14)), font("SemiBold", size)
        blocks = [(k, wrap(d, v, value_f, text_w)) for k, v in facts]
        need = sum(size - 14 + 14 + len(ls) * size * 1.3 + 34 for _, ls in blocks)
        if need <= space:
            break
    y = 240
    for k, lines in blocks:
        d.text((MARGIN, y), k.upper(), font=label_f, fill=c["muted"])
        y += size - 14 + 14
        y = draw_lines(d, lines, value_f, size, MARGIN, y, c["text"], 1.3) + 34
    return img


def _bookmark(d, x, y, c, s=46):
    d.polygon([(x, y), (x + s * .7, y), (x + s * .7, y + s), (x + s * .35, y + s * .72), (x, y + s)], outline=c, width=5)


def _plane(d, x, y, c, s=48):
    d.polygon([(x, y + s * .45), (x + s, y), (x + s * .62, y + s), (x + s * .45, y + s * .58)], outline=c, width=5)
    d.line([(x + s * .45, y + s * .58), (x + s, y)], fill=c, width=5)


def _person_plus(d, x, y, c, s=48):
    d.ellipse((x + s * .12, y, x + s * .52, y + s * .4), outline=c, width=5)
    d.arc((x - s * .05, y + s * .45, x + s * .7, y + s * 1.15), 180, 360, fill=c, width=5)
    d.line([(x + s * .78, y + s * .3), (x + s * 1.1, y + s * .3)], fill=c, width=5)
    d.line([(x + s * .94, y + s * .14), (x + s * .94, y + s * .46)], fill=c, width=5)


def _instagram_glyph(d, x, y, c, s=44):
    d.rounded_rectangle((x, y, x + s, y + s), radius=int(s * .28), outline=c, width=4)
    d.ellipse((x + s * .27, y + s * .27, x + s * .73, y + s * .73), outline=c, width=4)
    d.ellipse((x + s * .72, y + s * .16, x + s * .84, y + s * .28), fill=c)


def _facebook_glyph(d, x, y, c, bg, s=44):
    d.ellipse((x, y, x + s, y + s), fill=c)
    f = font("ExtraBold", int(s * .78))
    d.text((x + s * .5 - d.textlength("f", font=f) / 2 + 2, y + s * .2), "f", font=f, fill=bg)


def closing(post, cfg, total):
    """Chiusura in negativo: messaggio da ricordare evidenziato, scheda profilo con Follow / Save / Share."""
    c = cfg["colors"]
    navy = c["background"]
    img, d = light_canvas(cfg, total, total)
    d.text((MARGIN, 170), "KEY TAKEAWAY", font=font("Bold", 34), fill=DARK_ACCENT.get(c["accent"], navy))
    card_top = H - 660
    fnt, lines, size = fit(d, post["takeaway"], "ExtraBold", 72, 44, W - 2 * MARGIN, card_top - 240 - 50, 1.2)
    draw_rich(d, post["takeaway"], post.get("takeaway_highlight"), fnt, size, MARGIN, 240, W - 2 * MARGIN,
              navy, 1.2, c["accent"], half=True)
    d.rounded_rectangle((MARGIN, card_top, W - MARGIN, card_top + 500), radius=32, fill=navy)
    sym = paste_logo(img, "logo-symbol-light", MARGIN + 30, card_top + 22, height=140)
    if sym:
        wx = MARGIN + 30 + sym[0] + 18
        paste_logo(img, "logo-wordmark-light", wx, card_top + 30, height=100)
    else:
        logo_mark(img, d, MARGIN + 50, card_top + 46, 90, c["accent"], navy, cfg)
        d.text((MARGIN + 165, card_top + 52), cfg["brand_name"], font=font("Bold", 38), fill="#FFFFFF")
        d.text((MARGIN + 165, card_top + 102), cfg.get("tagline", "Methodology made practical"),
               font=font("Regular", 30), fill=c["muted_text"])
    x, ay = MARGIN + 50, card_top + 200
    for icon, label in ((_person_plus, "Follow"), (_bookmark, "Save"), (_plane, "Share")):
        icon(d, x, ay, c["accent"])
        d.text((x, ay + 74), label, font=font("SemiBold", 30), fill="#FFFFFF")
        x += 270
    cta1, cta2 = post.get("closing_cta") or ("Save it for your next protocol", None)
    cta = cta1 + (f" · {cta2}" if cta2 else "")
    cf, cl, cs = fit(d, cta, "Regular", 28, 22, W - 2 * MARGIN - 100, 40, 1.2)
    d.text((MARGIN + 50, card_top + 345), cl[0], font=cf, fill=c["muted_text"])
    # dove trovarci: Instagram e Facebook con lo stesso nome
    d.line((MARGIN + 50, card_top + 400, W - MARGIN - 50, card_top + 400), fill="#2A4560", width=2)
    sy = card_top + 425
    _instagram_glyph(d, MARGIN + 50, sy, "#FFFFFF")
    _facebook_glyph(d, MARGIN + 116, sy, "#FFFFFF", navy)
    d.text((MARGIN + 186, sy + 4), cfg["handle"], font=font("SemiBold", 32), fill="#FFFFFF")
    return img


def positions_cover(post, cfg, total):
    """Copertina della raccolta settimanale di posizioni accademiche (in negativo, accento proprio)."""
    c = cfg["colors"]
    navy = c["background"]
    img, d = light_canvas(cfg, 1, total)
    logo_lockup(img, d, MARGIN - 10, 80, cfg)
    badge_f = font("ExtraBold", 34)
    label = "ACADEMIC POSITIONS"
    bw = d.textlength(label, font=badge_f) + 60
    d.rounded_rectangle((MARGIN, 300, MARGIN + bw, 366), radius=33, fill=c["accent"])
    d.text((MARGIN + 30, 312), label, font=badge_f, fill=navy)
    d.text((MARGIN, 396), f"Week of {post.get('week', '')}", font=font("SemiBold", 36), fill=INK_MUTED)
    fnt, lines, size = fit(d, post["title"], "ExtraBold", 100, 60, W - 2 * MARGIN, 420, 1.12)
    draw_rich(d, post["title"], post.get("title_highlight"), fnt, size, MARGIN, 470, W - 2 * MARGIN, navy, 1.12,
              c["accent"], half=True)
    counts = {}
    for j in post.get("jobs", []):
        counts[j["type"]] = counts.get(j["type"], 0) + 1
    x, y = MARGIN, H - 330
    for t, n in counts.items():
        chip = f"{n} {t}"
        cw = d.textlength(chip, font=font("Bold", 32)) + 44
        d.rounded_rectangle((x, y, x + cw, y + 60), radius=30, outline=navy, width=3)
        d.text((x + 22, y + 11), chip, font=font("Bold", 32), fill=navy)
        x += cw + 16
    d.text((MARGIN, H - 220), "Swipe  →", font=font("Bold", 40), fill=navy)
    return img


def position_slide(job, number, cfg, index, total):
    """Una posizione per slide: tipo, titolo, ente e luogo, scadenza, breve descrizione."""
    c = cfg["colors"]
    img, d = canvas(cfg, index, total)
    tf = font("ExtraBold", 32)
    tw = d.textlength(job["type"].upper(), font=tf) + 48
    d.rounded_rectangle((MARGIN, 130, MARGIN + tw, 190), radius=30, fill=c["accent"])
    d.text((MARGIN + 24, 141), job["type"].upper(), font=tf, fill=c["background"])
    d.text((W - MARGIN - d.textlength(f"{number:02d}", font=font("ExtraBold", 72)), 118), f"{number:02d}",
           font=font("ExtraBold", 72), fill=c["accent"])
    hf, hl, hs = fit(d, job["title"], "Bold", 58, 38, W - 2 * MARGIN, 300, 1.18)
    y = draw_lines(d, hl, hf, hs, MARGIN, 240, c["text"], 1.18) + 26
    inst = job["institution"] + (f" · {job['place']}" if job.get("place") else "")
    nf, nl, ns = fit(d, inst, "SemiBold", 36, 28, W - 2 * MARGIN, 130, 1.25)
    y = draw_lines(d, nl, nf, ns, MARGIN, y, c["muted_text"], 1.25) + 34
    d.rounded_rectangle((MARGIN, y, W - MARGIN, y + 130), radius=24, outline=c["accent"], width=3)
    d.text((MARGIN + 36, y + 22), "DEADLINE", font=font("Bold", 26), fill=c["accent"])
    d.text((MARGIN + 36, y + 58), job["deadline"], font=font("ExtraBold", 48), fill=c["text"])
    y += 170
    if job.get("summary"):
        bf, bl, bs = fit(d, job["summary"], "Regular", 36, 26, W - 2 * MARGIN, H - 190 - y, 1.4)
        draw_lines(d, bl, bf, bs, MARGIN, y, c["muted_text"], 1.4)
    return img


def render_carousel(post, cfg):
    """Copertina, slide di contenuto, chiusura. Le slide in posizione pari (2, 4, 6…) hanno anche un'immagine AI."""
    if post.get("kind") == "grant":   # i bandi hanno un colore d'accento proprio, per riconoscerli a colpo d'occhio
        cfg = {**cfg, "colors": {**cfg["colors"], "accent": cfg.get("grant_accent", "#FFB547")}}
    if post.get("accent"):   # post speciali (annunci): colore d'accento proprio
        cfg = {**cfg, "colors": {**cfg["colors"], "accent": post["accent"]}}
    if post.get("kind") == "positions":   # raccolta settimanale di posizioni: senza illustrazioni AI
        cfg = {**cfg, "colors": {**cfg["colors"], "accent": cfg.get("positions_accent", "#A78BFA")}}
        jobs = post.get("jobs", [])
        total = len(jobs) + 2
        pages = [positions_cover(post, cfg, total)]
        pages += [position_slide(j, i, cfg, i + 1, total) for i, j in enumerate(jobs, start=1)]
        pages.append(closing(post, cfg, total))
        out = []
        for img in pages:
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=92, optimize=True)
            out.append(buf.getvalue())
        return out
    has_facts = bool(post.get("facts"))
    total = len(post["slides"]) + 2 + has_facts
    use_images = cfg.get("ai_images", True) and not post.get("no_images")
    max_images = int(cfg.get("max_images_per_post", 2))
    used = 0
    pages = [grant_cover(post, cfg, total) if post.get("kind") == "grant" else cover(post, cfg, total)]
    for i, slide in enumerate(post["slides"], start=1):
        index = i + 1
        picture = None
        if use_images and index % 2 == 0 and used < max_images:
            print(f"Genero l'immagine per la slide {index}: {slide['heading']}")
            picture = images.generate(slide, cfg)
            used += 1
        if picture is not None:
            pages.append(illustrated(slide, i, cfg, index, total, picture))
        else:
            pages.append(content(slide, i, cfg, index, total))
    if has_facts:
        pages.append(facts_slide(post, cfg, len(pages) + 1, total))
    pages.append(closing(post, cfg, total))
    out = []
    for img in pages:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=92, optimize=True)
        out.append(buf.getvalue())
    return out
