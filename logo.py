"""Logo v4 (4/11/2026), dal canvas «Clinical Research Chaos – Logo» (artboard LogoKit / Symbol compatto):
simbolo a cubetti su sfera con riduzione graduale delle dimensioni, quadratini d'accento nel colore del tipo di post,
«CLINICAL RESEARCH» nel colore del tipo e «Chaos» con la «o» a sasso (anello inclinato di -35°) nel colore del tipo.
Su fondo chiaro scritta e cubetti principali sono neri (#0A0A0A). Disegnato in vettoriale, a qualsiasi dimensione:
niente file da tenere allineati."""

import colorsys
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "fonts"
INK_LIGHT, INK_DARK = "#FFFFFF", "#0A0A0A"         # scritta e cubetti principali: su fondo scuro / su fondo chiaro

# simbolo compatto, sfera a riduzione graduale (viewBox 23 23 154 154): (ruolo del colore, vertici)
SYMBOL = [('deep', [(27.61, 68.03), (41.55, 70.25), (39.34, 84.19), (25.4, 81.97)]), ('deep', [(26.68, 91.24), (41.51, 92.45), (40.3, 107.28), (25.47, 106.07)]), ('ink', [(48.3, 48.3), (64.0, 48.3), (64.0, 64.0), (48.3, 64.0)]), ('teal', [(45.72, 68.41), (63.52, 68.41), (63.52, 86.21), (45.72, 86.21)]), ('ink', [(44.83, 90.73), (63.38, 90.73), (63.38, 109.27), (44.83, 109.27)]), ('deep', [(48.3, 136.0), (64.0, 136.0), (64.0, 151.7), (48.3, 151.7)]), ('deep', [(72.66, 25.88), (85.82, 27.98), (83.71, 41.15), (70.55, 39.04)]), ('ink', [(68.41, 45.72), (86.21, 45.72), (86.21, 63.52), (68.41, 63.52)]), ('ink', [(66.48, 66.48), (86.58, 66.48), (86.58, 86.58), (66.48, 86.58)]), ('ink', [(76.27, 100.0), (76.27, 89.54), (86.72, 89.54), (86.72, 100.0), (86.72, 110.46), (76.27, 110.46), (65.81, 110.46), (65.81, 100.0)]), ('ink', [(66.48, 113.42), (86.58, 113.42), (86.58, 133.52), (66.48, 133.52)]), ('ink', [(68.41, 136.48), (86.21, 136.48), (86.21, 154.28), (68.41, 154.28)]), ('deep', [(73.14, 160.27), (87.04, 160.09), (87.23, 173.99), (73.33, 174.17)]), ('ink', [(92.98, 25.21), (107.58, 25.74), (107.06, 40.34), (92.46, 39.81)]), ('ink', [(90.73, 44.83), (109.27, 44.83), (109.27, 63.38), (90.73, 63.38)]), ('ink', [(89.54, 65.81), (110.46, 65.81), (110.46, 86.72), (89.54, 86.72)]), ('ink', [(89.12, 89.12), (110.88, 89.12), (110.88, 110.88), (89.12, 110.88)]), ('ink', [(89.54, 113.28), (100.0, 113.28), (110.46, 113.28), (110.46, 123.73), (100.0, 123.73), (100.0, 134.19), (89.54, 134.19), (89.54, 123.73)]), ('teal', [(90.73, 136.62), (109.27, 136.62), (109.27, 155.17), (90.73, 155.17)]), ('deep', [(114.87, 24.58), (128.92, 26.94), (126.56, 41.0), (112.51, 38.63)]), ('deep', [(113.79, 45.72), (131.59, 45.72), (131.59, 63.52), (113.79, 63.52)]), ('ink', [(113.42, 66.48), (123.47, 66.48), (123.47, 76.53), (133.52, 76.53), (133.52, 86.58), (123.47, 86.58), (113.42, 86.58), (113.42, 76.53)]), ('ink', [(113.28, 89.54), (134.19, 89.54), (134.19, 110.46), (113.28, 110.46)]), ('ink', [(113.42, 113.42), (133.52, 113.42), (133.52, 133.52), (113.42, 133.52)]), ('deep', [(112.75, 159.63), (126.59, 160.2), (126.02, 174.03), (112.19, 173.46)]), ('teal', [(136.48, 68.41), (154.28, 68.41), (154.28, 86.21), (136.48, 86.21)]), ('deep', [(136.48, 113.79), (154.28, 113.79), (154.28, 131.59), (136.48, 131.59)]), ('ink', [(136.0, 136.0), (151.7, 136.0), (151.7, 151.7), (136.0, 151.7)]), ('deep', [(160.44, 68.55), (174.28, 69.51), (173.32, 83.35), (159.48, 82.39)]), ('deep', [(160.36, 93.27), (174.6, 93.46), (174.41, 107.7), (160.17, 107.51)]), ('deep', [(160.4, 115.41), (173.17, 114.18), (174.4, 126.95), (161.63, 128.18)])]

VIEW = (23, 23, 154, 154)

# «o» a sasso: anello con contorno e foro a curve quadratiche (viewBox -70 -70 140 140), ruotato di -20°
PEBBLE_OUT = [(-45, -45), (0, -65), (45, -45), (65, 0), (45, 45), (0, 65), (-45, 45), (-65, 0), (-45, -45)]
PEBBLE_IN = [(-19, -31), (6, -45), (31, -31), (45, -6), (31, 19), (6, 33), (-19, 19), (-33, -6), (-19, -31)]


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def deep_of(accent):
    """Tinta scura dei cubetti secondari: stesso colore, più scuro e saturo (come #5B86E0 per #88B0F8)."""
    r, g, b = (v / 255 for v in _rgb(accent))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return "#%02x%02x%02x" % tuple(int(v * 255) for v in colorsys.hls_to_rgb(h, max(0.22, l * 0.80), min(1, s * 0.92)))


def _quad(points, steps=16):
    """Contorno di curve quadratiche M p0 Q p1 p2 Q p3 p4 … → poligono."""
    out = [points[0]]
    for i in range(1, len(points) - 1, 2):
        p0, c, p1 = points[i - 1], points[i], points[i + 1]
        for k in range(1, steps + 1):
            t = k / steps
            out.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p1[0],
                        (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p1[1]))
    return out


@lru_cache(maxsize=64)
def symbol(accent, ink=INK_LIGHT, height=240):
    """Simbolo RGBA alto `height` px: cubetti principali in `ink`, d'accento in `accent` e nella sua tinta scura."""
    k = 4
    S = height * k
    vx, vy, vw, vh = VIEW
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cols = {"ink": _rgb(ink) + (255,), "teal": _rgb(accent) + (255,), "deep": _rgb(deep_of(accent)) + (255,)}
    for role, pts in SYMBOL:
        d.polygon([((x - vx) / vw * S, (y - vy) / vh * S) for x, y in pts], fill=cols[role])
    return img.resize((height, height), Image.LANCZOS)


def pebble(color, size):
    """La «o» del logo, RGBA quadrata di lato `size`."""
    k = 4
    S = size * k
    mask = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(mask)
    a = math.radians(-35)

    def tr(pts):
        return [((x * math.cos(a) - y * math.sin(a)) / 140 * S + S / 2, (x * math.sin(a) + y * math.cos(a)) / 140 * S + S / 2)
                for x, y in pts]
    d.polygon(tr(_quad(PEBBLE_OUT)), fill=255)
    d.polygon(tr(_quad(PEBBLE_IN)), fill=0)
    img = Image.new("RGBA", (S, S), _rgb(color) + (0,))
    img.putalpha(mask)
    return img.resize((size, size), Image.LANCZOS)


@lru_cache(maxsize=64)
def wordmark(accent, ink=INK_LIGHT, height=160, label=None):
    """Scritta RGBA alta `height` px (come nel canvas: etichetta 19,2 px, «Chaos» 48 px, spazio 6 px)."""
    k = 4
    unit = height * k / (19.2 + 6 + 48 * 0.9)          # px del canvas → px qui
    f_top = ImageFont.truetype(str(FONTS / "Inter-Bold.ttf"), round(19.2 * unit))
    f_main = ImageFont.truetype(str(FONTS / "Inter-ExtraBold.ttf"), round(48 * unit))
    em = 48 * unit
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    top_track = 0.06 * 19.2 * unit
    main_track = -0.04 * em
    label_txt = "CLINICAL RESEARCH"
    top_w = sum(probe.textlength(ch, font=f_top) + top_track for ch in label_txt)

    def run_w(txt):
        return sum(probe.textlength(ch, font=f_main) + main_track for ch in txt)
    o_size = 0.764 * em
    cha_w, s_w = run_w("Cha"), run_w("s")
    main_w = cha_w - 0.0366 * em + o_size - 0.0517 * em + s_w
    Wd = int(max(top_w, main_w) + 8 * k)
    Hd = int(height * k)
    img = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    acc, inkc = _rgb(label or accent) + (255,), _rgb(ink) + (255,)
    x = unit                                           # margin-left: 1px
    asc_top = f_top.getbbox("C")[1]
    for ch in label_txt:
        d.text((x, -asc_top), ch, font=f_top, fill=acc)
        x += probe.textlength(ch, font=f_top) + top_track
    # riga «Chaos»: linea di base comune; la «o» scende di 0,109 em rispetto al suo riquadro
    cap = f_main.getbbox("C")
    main_top = (19.2 + 6) * unit
    base_y = main_top - cap[1]
    x = 0
    for ch in "Cha":
        d.text((x, base_y), ch, font=f_main, fill=inkc)
        x += probe.textlength(ch, font=f_main) + main_track
    x -= 0.0366 * em
    asc, desc = f_main.getmetrics()
    baseline = base_y + asc
    o_top = baseline - o_size + 0.109 * em - 0.02 * em
    img.alpha_composite(pebble(accent, int(o_size)), (int(x), int(o_top)))
    x += o_size - 0.0517 * em
    d.text((x, base_y), "s", font=f_main, fill=inkc)
    bbox = img.getbbox()
    img = img.crop((0, 0, min(Wd, bbox[2] + 2 * k), Hd))
    return img.resize((round(img.width / k), height), Image.LANCZOS)


def lockup(accent, ink=INK_LIGHT, height=170):
    """Simbolo e scritta affiancati, come nel canvas (simbolo 70, spazio 13, scritta alta ~68)."""
    s = symbol(accent, ink, height)
    wh = round(height * (19.2 + 6 + 48 * 0.9) / 70)
    w = wordmark(accent, ink, wh)
    gap = round(height * 13 / 70)
    out = Image.new("RGBA", (s.width + gap + w.width, max(height, wh)), (0, 0, 0, 0))
    out.alpha_composite(s, (0, (out.height - height) // 2))
    out.alpha_composite(w, (s.width + gap, (out.height - wh) // 2))
    return out
