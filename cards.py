"""Disegna le slide del carosello (1080x1350, formato 4:5) a partire da un post in coda."""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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


def closing(post, cfg, total):
    c = cfg["colors"]
    img, d = canvas(cfg, total, total)
    d.text((MARGIN, 200), "KEY TAKEAWAY", font=font("Bold", 34), fill=c["accent"])
    fnt, lines, size = fit(d, post["takeaway"], "Bold", 68, 44, W - 2 * MARGIN, 560, 1.25)
    y = draw_lines(d, lines, fnt, size, MARGIN, 280, c["text"], 1.25)
    box_top = max(y + 80, H - 420)
    d.rounded_rectangle((MARGIN, box_top, W - MARGIN, box_top + 200), radius=28, outline=c["accent"], width=4)
    d.text((MARGIN + 50, box_top + 45), "Save this for your next protocol", font=font("SemiBold", 38), fill=c["text"])
    d.text((MARGIN + 50, box_top + 110), f"Follow {cfg['handle']} for more", font=font("Regular", 36), fill=c["muted_text"])
    return img


def render_carousel(post, cfg):
    total = len(post["slides"]) + 2
    images = [cover(post, cfg, total)]
    for i, slide in enumerate(post["slides"], start=1):
        images.append(content(slide, i, cfg, i + 1, total))
    images.append(closing(post, cfg, total))
    out = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=92, optimize=True)
        out.append(buf.getvalue())
    return out
