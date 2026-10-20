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
        if len(lines) * size * spacing <= max_h or size <= minimum:
            return fnt, lines, size
        size -= 2


def draw_lines(draw, lines, fnt, size, x, y, color, spacing):
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=color)
        y += size * spacing
    return y


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
    c = cfg["colors"]
    img, d = canvas(cfg, 1, total)
    label = post.get("category", "Research methods").upper()
    d.text((MARGIN, 190), label, font=font("Bold", 34), fill=c["accent"])
    fnt, lines, size = fit(d, post["title"], "ExtraBold", 96, 56, W - 2 * MARGIN, 700, 1.15)
    y = draw_lines(d, lines, fnt, size, MARGIN, 270, c["text"], 1.15)
    d.rectangle((MARGIN, y + 40, MARGIN + 140, y + 50), fill=c["accent"])
    d.text((MARGIN, H - 240), "Swipe  →", font=font("SemiBold", 40), fill=c["text"])
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
    draw_lines(d, bl, bf, bs, MARGIN, y, c["muted_text"], 1.45)
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
    top, bottom = 90, H - 150          # spazio utile tra la barra in alto e il piè di pagina

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

    draw_lines(d, bl, bf, bs, MARGIN, y + pic_h + 40, c["muted_text"], 1.4)
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


def closing(post, cfg, total):
    c = cfg["colors"]
    img, d = canvas(cfg, total, total)
    d.text((MARGIN, 200), "KEY TAKEAWAY", font=font("Bold", 34), fill=c["accent"])
    fnt, lines, size = fit(d, post["takeaway"], "Bold", 68, 44, W - 2 * MARGIN, 560, 1.25)
    y = draw_lines(d, lines, fnt, size, MARGIN, 280, c["text"], 1.25)
    box_top = max(y + 80, H - 420)
    line1, line2 = post.get("closing_cta") or ("Save this for your next protocol", None)
    line2 = line2 or f"Follow {cfg['handle']} for more"
    d.rounded_rectangle((MARGIN, box_top, W - MARGIN, box_top + 200), radius=28, outline=c["accent"], width=4)
    f1, l1, s1 = fit(d, line1, "SemiBold", 38, 28, W - 2 * MARGIN - 100, 50, 1.2)
    d.text((MARGIN + 50, box_top + 45), l1[0], font=f1, fill=c["text"])
    d.text((MARGIN + 50, box_top + 110), line2, font=font("Regular", 36), fill=c["muted_text"])
    return img


def render_carousel(post, cfg):
    """Copertina, slide di contenuto, chiusura. Le slide in posizione pari (2, 4, 6…) hanno anche un'immagine AI."""
    has_facts = bool(post.get("facts"))
    total = len(post["slides"]) + 2 + has_facts
    use_images = cfg.get("ai_images", True)
    pages = [cover(post, cfg, total)]
    for i, slide in enumerate(post["slides"], start=1):
        index = i + 1
        picture = None
        if use_images and index % 2 == 0:
            print(f"Genero l'immagine per la slide {index}: {slide['heading']}")
            picture = images.generate(slide, cfg)
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
