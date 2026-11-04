"""Logo v3 (2/11/2026), dal canvas «Clinical Research Chaos – Logo» (artboard SocialCategories / Symbol compatto):
simbolo a cubetti con i quadratini d'accento nel colore del tipo di post, «CLINICAL RESEARCH» nel colore del tipo
e «Chaos» con la «o» a sasso (anello inclinato di -20°) nel colore del tipo. Disegnato in vettoriale, a qualsiasi
dimensione: niente file da tenere allineati."""

import colorsys
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "fonts"
INK_LIGHT, INK_DARK = "#FFFFFF", "#15233A"         # scritta e cubetti principali: su fondo scuro / su fondo chiaro

# simbolo compatto (viewBox 26 26 148 148): (ruolo del colore, vertici)
SYMBOL = [('deep', [(30.08, 71.44), (38.15, 72.72), (36.87, 80.78), (28.8, 79.5)]), ('deep', [(29.2, 94.21), (38.54, 94.97), (37.78, 104.31), (28.44, 103.55)]), ('ink', [(50.72, 50.72), (61.58, 50.72), (61.58, 61.58), (50.72, 61.58)]), ('teal', [(47.52, 70.21), (61.72, 70.21), (61.72, 84.41), (47.52, 84.41)]), ('ink', [(46.36, 92.26), (61.84, 92.26), (61.84, 107.74), (46.36, 107.74)]), ('deep', [(50.72, 138.42), (61.58, 138.42), (61.58, 149.28), (50.72, 149.28)]), ('deep', [(74.98, 29.08), (82.61, 30.31), (81.39, 37.94), (73.76, 36.72)]), ('ink', [(70.21, 47.52), (84.41, 47.52), (84.41, 61.72), (70.21, 61.72)]), ('ink', [(67.34, 67.34), (85.72, 67.34), (85.72, 85.72), (67.34, 85.72)]), ('ink', [(76.27, 100.0), (76.27, 90.0), (86.27, 90.0), (86.27, 100.0), (86.27, 110.0), (76.27, 110.0), (66.26, 110.0), (66.26, 100.0)]), ('ink', [(67.34, 114.28), (85.72, 114.28), (85.72, 132.66), (67.34, 132.66)]), ('ink', [(70.21, 138.28), (84.41, 138.28), (84.41, 152.48), (70.21, 152.48)]), ('deep', [(76.07, 163.13), (84.19, 163.02), (84.3, 171.14), (76.18, 171.25)]), ('ink', [(95.65, 28.08), (104.72, 28.4), (104.39, 37.47), (95.33, 37.15)]), ('ink', [(92.26, 46.36), (107.74, 46.36), (107.74, 61.84), (92.26, 61.84)]), ('ink', [(90.0, 66.26), (110.0, 66.26), (110.0, 86.27), (90.0, 86.27)]), ('ink', [(89.12, 89.12), (110.88, 89.12), (110.88, 110.88), (89.12, 110.88)]), ('ink', [(90.0, 113.73), (100.0, 113.73), (110.0, 113.73), (110.0, 123.73), (100.0, 123.73), (100.0, 133.74), (90.0, 133.74), (90.0, 123.73)]), ('teal', [(92.26, 138.16), (107.74, 138.16), (107.74, 153.64), (92.26, 153.64)]), ('deep', [(95.5, 162.35), (104.36, 161.57), (105.13, 170.43), (96.27, 171.21)]), ('deep', [(117.31, 28.0), (125.5, 29.38), (124.12, 37.58), (115.93, 36.2)]), ('deep', [(115.59, 47.52), (129.79, 47.52), (129.79, 61.72), (115.59, 61.72)]), ('ink', [(114.28, 67.34), (123.47, 67.34), (123.47, 76.53), (132.66, 76.53), (132.66, 85.72), (123.47, 85.72), (114.28, 85.72), (114.28, 76.53)]), ('ink', [(113.73, 90.0), (133.74, 90.0), (133.74, 110.0), (113.73, 110.0)]), ('ink', [(114.28, 114.28), (132.66, 114.28), (132.66, 132.66), (114.28, 132.66)]), ('deep', [(115.49, 162.6), (123.62, 162.93), (123.29, 171.06), (115.15, 170.73)]), ('teal', [(138.28, 70.21), (152.48, 70.21), (152.48, 84.41), (138.28, 84.41)]), ('deep', [(138.28, 115.59), (152.48, 115.59), (152.48, 129.79), (138.28, 129.79)]), ('ink', [(138.42, 138.42), (149.28, 138.42), (149.28, 149.28), (138.42, 149.28)]), ('deep', [(163.19, 71.71), (171.12, 72.26), (170.57, 80.19), (162.64, 79.64)]), ('deep', [(163.05, 96.03), (171.83, 96.15), (171.71, 104.93), (162.93, 104.82)]), ('deep', [(163.41, 117.9), (170.68, 117.2), (171.38, 124.47), (164.11, 125.17)])]

VIEW = (26, 26, 148, 148)

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
    a = math.radians(-20)

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


def ring_rows(per=60, rows=3, center=(100.0, 100.0), scale=0.95, roundness=0.55):
    """`rows` giri concentrici dell'anello della «o», ognuno campionato in `per` punti ordinati lungo il
    percorso, nel sistema del simbolo (viewBox 26 26 148 148). Il sito li usa come orbita dei frammenti.
    `roundness` tira il percorso verso il cerchio (0 = la «o» tale e quale, 1 = cerchio): smussa gli angoli
    del sasso, che in movimento si leggerebbero come spigoli."""
    a = math.radians(-20)

    def resample(pts, m):
        acc = [0.0]
        for i in range(1, len(pts)):
            acc.append(acc[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
        tot, out, j = acc[-1], [], 1
        for k in range(m):
            d = tot * k / m
            while j < len(acc) - 1 and acc[j] < d:
                j += 1
            t = (d - acc[j - 1]) / max(1e-6, acc[j] - acc[j - 1])
            out.append((pts[j - 1][0] + (pts[j][0] - pts[j - 1][0]) * t,
                        pts[j - 1][1] + (pts[j][1] - pts[j - 1][1]) * t))
        return out

    outer, inner = resample(_quad(PEBBLE_OUT, 20), per), resample(_quad(PEBBLE_IN, 20), per)
    out = []
    for r in range(rows):
        f = (r + 1) / (rows + 1)                      # dal bordo esterno a quello interno
        row = []
        for k in range(per):
            x = outer[k][0] + (inner[k][0] - outer[k][0]) * f
            y = outer[k][1] + (inner[k][1] - outer[k][1]) * f
            row.append(((x * math.cos(a) - y * math.sin(a)) * scale + center[0],
                        (x * math.sin(a) + y * math.cos(a)) * scale + center[1]))
        if roundness:                              # verso il cerchio: stesso raggio medio, angoli smussati
            cx = sum(p[0] for p in row) / len(row)
            cy = sum(p[1] for p in row) / len(row)
            rad = sum(math.hypot(p[0] - cx, p[1] - cy) for p in row) / len(row)
            soft = []
            for x, y in row:
                d = math.hypot(x - cx, y - cy) or 1
                soft.append((x + (cx + (x - cx) / d * rad - x) * roundness,
                             y + (cy + (y - cy) / d * rad - y) * roundness))
            row = soft
        out.append(row)
    return out


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
