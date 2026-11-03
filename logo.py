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
def wordmark(accent, ink=INK_LIGHT, height=160, label=None, o4_dark=None):
    """Scritta RGBA alta `height` px (come nel canvas: etichetta 19,2 px, «Chaos» 48 px, spazio 6 px).
    `o4_dark` (True/False) = «o» definitiva a quattro spicchi del logo v4, su fondo scuro o chiaro."""
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
    o_img = pebble(accent, int(o_size)) if o4_dark is None else o4(o4_dark, int(o_size))
    img.alpha_composite(o_img, (int(x), int(o_top)))
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



# ---------------------------------------------------------------- logo v4 (definitivo, 3/11/2026; config «brand_v4»)
# Indipendente dalla linea: i cubetti d'accento del simbolo sono divisi per quadrante nei quattro colori delle rubriche
# (alto-sx Design, Reporting & Appraisal; alto-dx Funding Calls; basso-sx Academic Positions; basso-dx Latest Science),
# «CLINICAL RESEARCH» e «Chaos» bianchi su scuro e neri su chiaro, la «o» a sasso del logo divisa in quattro spicchi.
# palette «Quadrante» (3/11): stessa luminosità e saturazione percepite (OKLCH), tinte distanziate
LINES_DARK = {"m": "#82BEFF", "c": "#ECAD59", "p": "#CDA6FB", "i": "#60D4A7"}
LINES_LIGHT = {"m": "#3475C4", "c": "#A56300", "p": "#885CB5", "i": "#008D5F"}
INK4_DARK = "#0A0A0A"
SYMBOL4 = [('m', [(30.08, 71.44), (38.15, 72.72), (36.87, 80.78), (28.8, 79.5)]), ('m', [(29.2, 94.21), (38.54, 94.97), (37.78, 104.31), (28.44, 103.55)]), ('ink', [(50.72, 50.72), (61.58, 50.72), (61.58, 61.58), (50.72, 61.58)]), ('m', [(47.52, 70.21), (61.72, 70.21), (61.72, 84.41), (47.52, 84.41)]), ('ink', [(46.36, 92.26), (61.84, 92.26), (61.84, 107.74), (46.36, 107.74)]), ('p', [(50.72, 138.42), (61.58, 138.42), (61.58, 149.28), (50.72, 149.28)]), ('m', [(74.98, 29.08), (82.61, 30.31), (81.39, 37.94), (73.76, 36.72)]), ('ink', [(70.21, 47.52), (84.41, 47.52), (84.41, 61.72), (70.21, 61.72)]), ('ink', [(67.34, 67.34), (85.72, 67.34), (85.72, 85.72), (67.34, 85.72)]), ('ink', [(76.27, 100.0), (76.27, 90.0), (86.27, 90.0), (86.27, 100.0), (86.27, 110.0), (76.27, 110.0), (66.26, 110.0), (66.26, 100.0)]), ('ink', [(67.34, 114.28), (85.72, 114.28), (85.72, 132.66), (67.34, 132.66)]), ('ink', [(70.21, 138.28), (84.41, 138.28), (84.41, 152.48), (70.21, 152.48)]), ('p', [(76.07, 163.13), (84.19, 163.02), (84.3, 171.14), (76.18, 171.25)]), ('ink', [(95.65, 28.08), (104.72, 28.4), (104.39, 37.47), (95.33, 37.15)]), ('ink', [(92.26, 46.36), (107.74, 46.36), (107.74, 61.84), (92.26, 61.84)]), ('ink', [(90.0, 66.26), (110.0, 66.26), (110.0, 86.27), (90.0, 86.27)]), ('ink', [(89.12, 89.12), (110.88, 89.12), (110.88, 110.88), (89.12, 110.88)]), ('ink', [(90.0, 113.73), (100.0, 113.73), (110.0, 113.73), (110.0, 123.73), (100.0, 123.73), (100.0, 133.74), (90.0, 133.74), (90.0, 123.73)]), ('i', [(92.26, 138.16), (107.74, 138.16), (107.74, 153.64), (92.26, 153.64)]), ('i', [(95.5, 162.35), (104.36, 161.57), (105.13, 170.43), (96.27, 171.21)]), ('c', [(117.31, 28.0), (125.5, 29.38), (124.12, 37.58), (115.93, 36.2)]), ('c', [(115.59, 47.52), (129.79, 47.52), (129.79, 61.72), (115.59, 61.72)]), ('ink', [(114.28, 67.34), (123.47, 67.34), (123.47, 76.53), (132.66, 76.53), (132.66, 85.72), (123.47, 85.72), (114.28, 85.72), (114.28, 76.53)]), ('ink', [(113.73, 90.0), (133.74, 90.0), (133.74, 110.0), (113.73, 110.0)]), ('ink', [(114.28, 114.28), (132.66, 114.28), (132.66, 132.66), (114.28, 132.66)]), ('i', [(115.49, 162.6), (123.62, 162.93), (123.29, 171.06), (115.15, 170.73)]), ('c', [(138.28, 70.21), (152.48, 70.21), (152.48, 84.41), (138.28, 84.41)]), ('i', [(138.28, 115.59), (152.48, 115.59), (152.48, 129.79), (138.28, 129.79)]), ('ink', [(138.42, 138.42), (149.28, 138.42), (149.28, 149.28), (138.42, 149.28)]), ('c', [(163.19, 71.71), (171.12, 72.26), (170.57, 80.19), (162.64, 79.64)]), ('i', [(163.05, 96.03), (171.83, 96.15), (171.71, 104.93), (162.93, 104.82)]), ('i', [(163.41, 117.9), (170.68, 117.2), (171.38, 124.47), (164.11, 125.17)])]


def _lines(on_dark):
    return LINES_DARK if on_dark else LINES_LIGHT


@lru_cache(maxsize=32)
def symbol4(on_dark=True, height=240):
    """Simbolo definitivo RGBA alto `height` px (su fondo scuro: cubetti bianchi; su chiaro: neri)."""
    k = 4
    S = height * k
    vx, vy, vw, vh = VIEW
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cols = {r: _rgb(c) + (255,) for r, c in _lines(on_dark).items()}
    cols["ink"] = _rgb(INK_LIGHT if on_dark else INK4_DARK) + (255,)
    for role, pts in SYMBOL4:
        d.polygon([((x - vx) / vw * S, (y - vy) / vh * S) for x, y in pts], fill=cols[role])
    return img.resize((height, height), Image.LANCZOS)


def _o4_polys():
    """Quattro spicchi della «o» (viewBox -70 -70 140 140): superellisse inclinata verso ore 2, tratto pesante verso
    ore 8 e sottile verso ore 2, estremità arrotondate. Ordine: alto-sx, alto-dx, basso-sx, basso-dx."""
    ax = math.radians(-30)
    P = dict(a=47, b=43, k=0.08, n=2.3, t0=22, dt=11, side=0)

    def sp(v, n):
        return math.copysign(abs(v) ** (2 / n), v)

    def center(t):
        x = P["a"] * sp(math.cos(t), P["n"]); y = P["b"] * sp(math.sin(t), P["n"]) * (1 - P["k"] * math.cos(t))
        return (x * math.cos(ax) - y * math.sin(ax), x * math.sin(ax) + y * math.cos(ax))
    pts = []
    N = 1440
    for j in range(N):
        t = 2 * math.pi * j / N
        p, q = center(t), center(t + 1e-4)
        tx, ty = q[0] - p[0], q[1] - p[1]; L = math.hypot(tx, ty); tx, ty = tx / L, ty / L
        nx, ny = ty, -tx
        if nx * p[0] + ny * p[1] < 0:
            nx, ny = -nx, -ny
        pts.append((math.degrees(math.atan2(p[1], p[0])) % 360, p, (nx, ny), P["t0"] - P["dt"] * math.cos(t)))
    polys = []
    for a0, a1 in ((180, 270), (270, 360), (90, 180), (0, 90)):
        seg = sorted([q for q in pts if a0 <= q[0] < a1], key=lambda q: q[0])
        d0 = math.degrees((-0.5 + seg[0][3] / 2) / math.hypot(*seg[0][1]))
        d1 = math.degrees((-0.5 + seg[-1][3] / 2) / math.hypot(*seg[-1][1]))
        seg = [q for q in seg if a0 + d0 <= q[0] <= a1 - d1][::3]
        outer = [(p[0] + n[0] * w / 2, p[1] + n[1] * w / 2) for _, p, n, w in seg]
        inner = [(p[0] - n[0] * w / 2, p[1] - n[1] * w / 2) for _, p, n, w in seg]

        def cap(q, q2, forward):
            _, p, n, w = q
            tv = (q2[1][0] - p[0], q2[1][1] - p[1]); L = math.hypot(*tv); tv = (tv[0] / L, tv[1] / L)
            sgn = 1 if forward else -1
            return [(p[0] + (sgn * math.cos(f) * n[0] - math.sin(f) * tv[0]) * w / 2,
                     p[1] + (sgn * math.cos(f) * n[1] - math.sin(f) * tv[1]) * w / 2)
                    for f in (math.pi * j / 16 for j in range(1, 16))]
        polys.append(outer + cap(seg[-1], seg[-2], True) + inner[::-1] + cap(seg[0], seg[1], False))
    xs = [x for pl in polys for x, _ in pl]; ys = [y for pl in polys for _, y in pl]
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    sc = min(110 / (max(xs) - min(xs)), 112 / (max(ys) - min(ys)))
    return [[((x - cx) * sc, (y - cy) * sc) for x, y in pl] for pl in polys]


_O4 = None


def o4(on_dark, size):
    """La «o» definitiva: la «o» a sasso del logo (anello inclinato di -20°) divisa in quattro spicchi, uno per rubrica,
    con un filo di separazione. RGBA quadrata di lato `size`."""
    k = 4
    S = size * k
    ring = pebble("#000000", S).getchannel("A")                  # stessa forma della «o» del logo v3
    d = ImageDraw.Draw(ring)
    gap = S * 2.2 / 140                                            # filo tra gli spicchi
    d.rectangle((S / 2 - gap / 2, 0, S / 2 + gap / 2, S), fill=0)
    d.rectangle((0, S / 2 - gap / 2, S, S / 2 + gap / 2), fill=0)
    L = _lines(on_dark)
    col = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cd = ImageDraw.Draw(col)
    for (x0, y0), role in zip(((0, 0), (S / 2, 0), (0, S / 2), (S / 2, S / 2)), ("m", "c", "p", "i")):
        cd.rectangle((x0, y0, x0 + S / 2, y0 + S / 2), fill=_rgb(L[role]) + (255,))
    col.putalpha(ring)
    return col.resize((size, size), Image.LANCZOS)


@lru_cache(maxsize=32)
def wordmark4(on_dark=True, height=160):
    """Scritta definitiva: «CLINICAL RESEARCH» e «Chaos» nell'inchiostro del fondo, «o» a quattro spicchi."""
    ink = INK_LIGHT if on_dark else INK4_DARK
    return wordmark("#000000", ink, height, label=ink, o4_dark=on_dark)


def lockup4(on_dark=True, height=170):
    """Simbolo e scritta definitivi affiancati (stesse proporzioni di lockup)."""
    s = symbol4(on_dark, height)
    wh = round(height * (19.2 + 6 + 48 * 0.9) / 70)
    w = wordmark4(on_dark, wh)
    gap = round(height * 13 / 70)
    out = Image.new("RGBA", (s.width + gap + w.width, max(height, wh)), (0, 0, 0, 0))
    out.alpha_composite(s, (0, (out.height - height) // 2))
    out.alpha_composite(w, (s.width + gap, (out.height - wh) // 2))
    return out
