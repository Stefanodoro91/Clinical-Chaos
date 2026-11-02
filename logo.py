"""Logo v3 (2/11/2026): simbolo a cubetti con l'anello di quadratini nel colore del tipo di post, scritta
«CLINICAL RESEARCH» nel colore del tipo e «Chaos» con la «o» a sasso (anello inclinato) nel colore del tipo.
Disegnato qui in vettoriale, a qualsiasi dimensione e in qualsiasi colore: niente file da tenere allineati."""

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "fonts"
INK_LIGHT, INK_DARK = "#FFFFFF", "#15233A"         # scritta e cubetti principali: su fondo scuro / su fondo chiaro

# anello ordinato di quadratini nel colore del tipo (coordinate del simbolo originale, 233×235 px)
RING = [(89, 34), (145, 34), (30, 90), (207, 90), (30, 118), (207, 118), (207, 147), (89, 203), (117, 203), (145, 203)]
RING_SIZE = 9


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


@lru_cache(maxsize=1)
def _core():
    """Cubetti centrali del simbolo originale: [(maschera, x, y, è_bianco)], senza la nuvola di puntini."""
    from scipy import ndimage
    a = np.asarray(Image.open(ROOT / "assets" / "logo-symbol-light.png").convert("RGBA")).astype(int)
    mask = a[..., 3] > 128
    lab, _ = ndimage.label(mask)
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        m = lab[sl] == i
        if m.sum() < 60:
            continue
        x, y = sl[1].start, sl[0].start
        if (x, y) in ((30, 112), (197, 114), (113, 196)):   # puntini dell'anello vecchio
            continue
        col = a[sl][m][:, :3].mean(axis=0)
        out.append((m, x, y, col.sum() > 600))
    return out


@lru_cache(maxsize=64)
def symbol(accent, ink=INK_LIGHT, height=240):
    """Simbolo RGBA alto `height` px: cubetti principali in `ink`, quelli d'accento e l'anello in `accent`."""
    x0, y0, x1, y1 = 24, 24, 220, 216                  # riquadro del simbolo nelle coordinate originali
    k = 8
    big = Image.new("RGBA", ((x1 - x0) * k, (y1 - y0) * k), (0, 0, 0, 0))
    arr = np.zeros((big.height, big.width, 4), dtype=np.uint8)
    ink_c, acc_c = _rgb(ink) + (255,), _rgb(accent) + (255,)
    for m, x, y, white in _core():
        up = np.kron(m, np.ones((k, k), dtype=bool))
        yy, xx = (y - y0) * k, (x - x0) * k
        region = arr[yy:yy + up.shape[0], xx:xx + up.shape[1]]
        region[up[:region.shape[0], :region.shape[1]]] = ink_c if white else acc_c
    big = Image.fromarray(arr, "RGBA")
    d = ImageDraw.Draw(big)
    for cx, cy in RING:
        s = RING_SIZE * k / 2
        d.rectangle(((cx - x0) * k - s, (cy - y0) * k - s, (cx - x0) * k + s, (cy - y0) * k + s), fill=acc_c)
    w = round(big.width * height / big.height)
    return big.resize((w, height), Image.LANCZOS)


def _pebble(d, cx, cy, r, color, k):
    """La «o» del logo: un sasso arrotondato inclinato con il foro leggermente spostato in alto a destra."""
    import math
    pts = []
    for i in range(240):
        t = 2 * math.pi * i / 240
        c, s = math.cos(t), math.sin(t)
        n = 3.2                                        # superellisse: quadrato molto arrotondato
        x = r * math.copysign(abs(c) ** (2 / n), c) * (1.06 if c > 0 else 0.98)
        y = r * math.copysign(abs(s) ** (2 / n), s) * (1.0 if s < 0 else 1.04)
        a = math.radians(-14)
        pts.append((cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)))
    d.polygon(pts, fill=color)
    hr = r * 0.50
    hx, hy = cx + r * 0.10, cy - r * 0.08
    d.ellipse((hx - hr, hy - hr * 1.05, hx + hr, hy + hr * 1.05), fill=(0, 0, 0, 0))


@lru_cache(maxsize=64)
def wordmark(accent, ink=INK_LIGHT, height=160):
    """Scritta RGBA alta `height` px: «CLINICAL RESEARCH» in `accent`, «Chaos» in `ink` con la «o» in `accent`."""
    k = 4
    H = height * k
    top_size = round(H * 0.20)
    main_size = round(H * 0.56)
    f_top = ImageFont.truetype(str(FONTS / "Inter-Bold.ttf"), top_size)
    f_main = ImageFont.truetype(str(FONTS / "Inter-ExtraBold.ttf"), main_size)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    track = top_size * 0.09
    top_w = sum(probe.textlength(ch, font=f_top) for ch in "CLINICAL RESEARCH") + track * 16
    cha_w = probe.textlength("Cha", font=f_main)
    s_w = probe.textlength("s", font=f_main)
    o_w = main_size * 0.78
    main_w = cha_w + o_w + s_w + main_size * 0.04
    Wd = int(max(top_w, main_w) + k * 4)
    img = Image.new("RGBA", (Wd, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    acc, inkc = _rgb(accent) + (255,), _rgb(ink) + (255,)
    x = 0
    for ch in "CLINICAL RESEARCH":                     # maiuscoletto spaziato
        d.text((x, 0), ch, font=f_top, fill=acc)
        x += probe.textlength(ch, font=f_top) + track
    base_y = round(H * 0.30)
    d.text((0, base_y), "Cha", font=f_main, fill=inkc)
    asc = f_main.getbbox("a")                          # altezza della «x»: la «o» le somiglia
    xh_top, xh_bot = base_y + asc[1], base_y + asc[3]
    r = (xh_bot - xh_top) * 0.66
    ox = cha_w + main_size * 0.02 + o_w / 2
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    _pebble(ImageDraw.Draw(layer), ox, (xh_top + xh_bot) / 2 + r * 0.02, r, acc, k)
    img.alpha_composite(layer)
    d.text((cha_w + o_w + main_size * 0.04, base_y), "s", font=f_main, fill=inkc)
    bbox = img.getbbox()
    img = img.crop((0, 0, bbox[2] + k, H))
    return img.resize((round(img.width / k), height), Image.LANCZOS)


def lockup(accent, ink=INK_LIGHT, height=170):
    """Simbolo e scritta affiancati (alto `height`)."""
    s = symbol(accent, ink, height)
    w = wordmark(accent, ink, round(height * 0.74))
    gap = round(height * 0.14)
    out = Image.new("RGBA", (s.width + gap + w.width, height), (0, 0, 0, 0))
    out.alpha_composite(s, (0, 0))
    out.alpha_composite(w, (s.width + gap, round(height * 0.12)))
    return out
