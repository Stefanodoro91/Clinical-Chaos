"""Reel verticali (1080×1920) ricavati dai caroselli già pubblicati: ogni slide resta a schermo qualche secondo
con un leggero zoom, dissolvenza tra le slide e una musica di sottofondo originale generata qui (niente diritti)."""

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

import cards

ROOT = Path(__file__).resolve().parent
W, H = 1080, 1920
FPS = 30


def _cubes(img, seed, accent, dark, cfg, keep_out=(), density=0.8):
    """Cubetti del brand sul fotogramma (il colore del tipo nel bianco e nero): si adatta l'altezza di cards."""
    old = (cards.MONO, cards.HL, cards.H, cards.CUBE_V2)
    cards.MONO, cards.HL, cards.H, cards.CUBE_V2 = bool(cfg.get("mono")), accent, H, True   # v2: evita il testo dai pixel
    try:
        cards.cube_texture(img, seed, accent, dark, keep_out=list(keep_out), density=density)
    finally:
        cards.MONO, cards.HL, cards.H, cards.CUBE_V2 = old
    return img


def frame(slide_path, cfg, index, total, accent):
    """Una slide del carosello dentro il formato verticale: testata editoriale, slide su scheda arrotondata
    con contorno nel colore del tipo, cubetti nelle fasce libere, avanzamento e invito al carosello completo."""
    v3 = bool(cfg.get("design_v3"))
    mono = bool(cfg.get("mono"))
    if mono:
        cfg = {**cfg, "colors": {**cfg["colors"], "background": "#0A0A0A", "muted": "#8A8A8A"}}
        if not v3:
            cfg = {**cfg, "colors": {**cfg["colors"], "accent": "#F2F2F2"}}
            accent = "#F2F2F2"
    c = cfg["colors"]
    img = Image.new("RGB", (W, H), c["background"])
    d = ImageDraw.Draw(img)
    cards.EDITORIAL = v3
    sw, sh = 960, 1200                     # margini laterali: lo zoom non taglia mai il testo della slide
    slide = Image.open(slide_path).convert("RGB").resize((sw, sh), Image.LANCZOS)
    top = (H - sh) // 2 - 20
    sx = (W - sw) // 2
    # fascia alta: filetto e marchio (testata da rivista nello stile editoriale)
    d.rectangle([0, 0, W, 10], fill=accent)
    f_small = cards.font("Bold", 30)
    brand = cfg.get("brand_name", "").upper()
    tw = d.textlength(brand, font=f_small)
    d.text(((W - tw) / 2, 112), brand, font=f_small, fill=accent if v3 else c["accent"])
    if v3:
        rule = "#2E2E2E" if mono else "#2A4058"
        d.line((sx, 190, (W - tw) / 2 - 36, 190), fill=rule, width=2)
        d.line(((W + tw) / 2 + 36, 190, sx + sw, 190), fill=rule, width=2)
    # la slide su scheda arrotondata
    if v3:
        pic = slide.copy()
        mask = Image.new("L", (sw, sh), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, sw - 1, sh - 1), radius=36, fill=255)
        img.paste(pic, (sx, top), mask)
        d.rounded_rectangle((sx, top, sx + sw, top + sh), radius=36, outline=accent, width=4)
    else:
        img.paste(slide, (sx, top))
    # fascia bassa: avanzamento e invito al carosello completo
    y = top + sh + 60
    seg = (W - 160 - (total - 1) * 12) / total
    for i in range(total):
        x0 = 80 + i * (seg + 12)
        d.rounded_rectangle([x0, y, x0 + seg, y + 8], radius=4, fill=accent if i <= index else ("#2E2E2E" if mono else "#2A4058"))
    msg = "Full carousel on our profile"
    f_msg = cards.font("SerifItalic" if v3 else "SemiBold", 38 if v3 else 34)
    tw = d.textlength(msg, font=f_msg)
    d.text(((W - tw) / 2, y + 40), msg, font=f_msg, fill="#FFFFFF")
    handle = cfg.get("handle", "")
    f_h = cards.font("Regular", 30)
    tw = d.textlength(handle, font=f_h)
    d.text(((W - tw) / 2, y + 96), handle, font=f_h, fill=c["muted_text"])
    if v3:                                 # cubetti nelle fasce libere, mai sopra la slide o le scritte
        _cubes(img, f"reel-{index}-{total}", accent, True, cfg,
               keep_out=[(sx - 20, top - 20, sx + sw + 20, top + sh + 20), (60, y - 20, W - 60, y + 150),
                         ((W - 700) / 2, 90, (W + 700) / 2, 210)], density=0.7)
    return img


def music(path, seconds, seed=None, mood="Classica", track=None):
    """Musica del reel: un brano della libreria su Drive (diverso ogni giorno), o la base generata in music.py."""
    import music as _music
    from datetime import date
    if seed is None:                                      # rotazione quotidiana dei brani (anche nelle anteprime future)
        import os
        seed = (date.fromisoformat(os.environ["PREVIEW_DATE"]) if os.environ.get("PREVIEW_DATE") else date.today()).toordinal()
    return _music.for_video(path, seconds, seed, mood=mood, track=track)


def build_reel(slide_paths, out_path, cfg, accent=None, per_slide=4.6, edge=2.8, fade=0.5, with_music=True, images=None,
               mood="Classica", track=None):
    """Video MP4 verticale (H.264 + AAC) dalle slide di un carosello: copertina e chiusura più brevi,
    slide di contenuto abbastanza lunghe da leggerle. Restituisce la durata in secondi."""
    accent = accent or cfg["colors"]["accent"]
    slide_paths = list(slide_paths) if images is None else list(range(len(images)))
    total = len(slide_paths)
    if isinstance(per_slide, (list, tuple)):                   # durate già calcolate slide per slide
        lengths = [float(x) for x in per_slide][:total] + [edge] * max(0, total - len(per_slide))
    else:
        lengths = [edge if i in (0, total - 1) else per_slide for i in range(total)]
    duration = sum(lengths) - (total - 1) * fade
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        inputs, filters = [], []
        for i, sp in enumerate(slide_paths):
            p = tmp / f"f{i}.png"
            (images[i] if images is not None else frame(sp, cfg, i, total, accent)).save(p)
            inputs += ["-loop", "1", "-t", f"{lengths[i]}", "-i", str(p)]
            frames = int(lengths[i] * FPS)
            # zoom lento dal 100% al 103% verso il centro
            filters.append(f"[{i}:v]scale={W * 2}:{H * 2},zoompan=z='1+0.03*on/{frames}':x='iw/2-(iw/zoom/2)':"
                           f"y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},setsar=1[v{i}]")
        chain, last, off = [], "v0", 0.0
        for i in range(1, total):
            off += lengths[i - 1] - fade
            chain.append(f"[{last}][v{i}]xfade=transition=fade:duration={fade}:offset={off:.2f}[x{i}]")
            last = f"x{i}"
        graph = ";".join(filters + chain)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs]
        if with_music:
            wav = tmp / "music.wav"
            music(wav, duration, mood=mood, track=track)
            cmd += ["-i", str(wav)]
        cmd += ["-filter_complex", graph, "-map", f"[{last}]"]
        if with_music:
            cmd += ["-map", f"{total}:a", "-c:a", "aac", "-b:a", "160k", "-ar", "44100"]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-r", str(FPS),
                "-movflags", "+faststart", "-t", f"{duration:.2f}", str(out_path)]
        subprocess.run(cmd, check=True)
    return round(duration, 1)


WPM = 180            # lettura su telefono, testo in inglese per non madrelingua: più lenta della media (≈ 230)


def reading_lengths(total, words_per_slide, edge=3.5, minimum=5.0, maximum=11.0, cap=88.0):
    """Durata di ogni slide in base alle parole da leggere: copertina e chiusura `edge` secondi, le altre
    1,5 s per orientarsi + il tempo di lettura, tra `minimum` e `maximum`; reel entro `cap` secondi."""
    words = list(words_per_slide) + [words_per_slide[-1] if words_per_slide else 30] * total
    inner = [max(minimum, min(maximum, 1.5 + words[i] * 60 / WPM)) for i in range(total - 2)]
    room = cap - 2 * edge
    if sum(inner) > room:                                   # troppo lungo: si accorcia in proporzione
        k = room / sum(inner)
        inner = [max(minimum * 0.9, x * k) for x in inner]
    return [edge] + [round(x, 1) for x in inner] + [edge]


def reel_caption(post_entry, caption_text, cfg):
    """Didascalia breve del reel: titolo, una riga dal carosello, rimando al post completo, hashtag."""
    title = post_entry.get("title", "")
    first = next((l.strip() for l in caption_text.splitlines() if l.strip() and l.strip() != title), "")
    tags = " ".join(cfg.get("fixed_hashtags", []) + ["#Reels", "#ResearchTips"])
    return f"{title}\n\n{first[:300]}\n\nFull carousel with references on our profile.\n\n{tags}".strip()


# ---------------------------------------------------------------- reel speciali (annunci) in formato verticale nativo
LIGHT_BG, DARK_TEXT = "#F3F6F9", "#0E2233"


def _wrap(d, text, fnt, max_w):
    return cards.wrap(d, text, fnt, max_w)


_PHOTOS = {}


def _photo(query):
    """Prima foto Pixabay per la ricerca (in memoria: la stessa schermata si disegna più volte nei reel animati)."""
    if not query:
        return None
    if query not in _PHOTOS:
        try:
            import images
            found = images.pixabay_photos(query, 1, 900, 500)
            _PHOTOS[query] = found[0][0] if found else None
            if found and len(found[0]) > 1:
                print(f"Foto per «{query}»: {found[0][1:]}")
        except Exception as e:
            print(f"::warning title=Foto del reel::{query}: {str(e)[:160]}")
            _PHOTOS[query] = None
    return _PHOTOS[query]


def story_frame(slide, cfg, index, total, accent, cubes=True):
    """Slide 1080×1920 per i reel di annuncio: copertina chiara, punti numerati scuri, chiusura con il logo."""
    cards.EDITORIAL = bool(cfg.get("design_v3"))
    mono = bool(cfg.get("mono"))
    if mono:
        cfg = {**cfg, "colors": {**cfg["colors"], "background": "#0A0A0A"}}
    c = cfg["colors"]
    kind = slide.get("type", "point")
    accent = slide.get("accent") or accent
    cards.LOGO_ACCENT = accent
    bg = slide.get("bg") or ("#0A0A0A" if mono else (LIGHT_BG if kind == "cover" else c["background"]))
    rgb = tuple(int(bg.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    light = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255 > 0.55       # fondo chiaro: testo scuro
    fg = ("#0A0A0A" if mono else DARK_TEXT) if light else "#FFFFFF"
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    M = 96
    bar = "#F2F2F2" if mono else accent          # barre in grigio nel bianco e nero: il colore resta solo al testo
    d.rectangle([0, 0, W, 14], fill=bar)
    if kind == "stat":
        # numero grande su fondo colorato (es. bandi in giallo, posizioni in lilla), con foto facoltativa
        kcol = accent if cards.EDITORIAL else fg             # etichetta e numero nel colore del tipo
        if cards.EDITORIAL:                                    # numero grande centrato meglio in verticale
            y0 = 420
        else:
            y0 = 170
        d.text((M, y0), (slide.get("kicker") or "").upper(), font=cards.font("Bold", 34), fill=kcol)
        y = y0 + 70
        big = cards.font(cards.H_("ExtraBold"), 230)
        d.text((M, y), slide.get("number", ""), font=big, fill=kcol)
        y += 280
        fnt, lines, size = cards.fit(d, slide["title"], cards.H_("ExtraBold"), 92, 60, W - 2 * M, 220, 1.08)
        for line in lines:
            d.text((M, y), line, font=fnt, fill=fg)
            y += int(size * 1.08)
        if slide.get("body"):
            fb = cards.font("SemiBold", 46)
            y += 24
            for line in _wrap(d, slide["body"], fb, W - 2 * M)[:3]:
                d.text((M, y), line, font=fb, fill=fg)
                y += 62
        photo = _photo(slide.get("photo_query"))
        if photo is not None:
            y += 50
            ph = min(H - 260 - y, 640)
            if ph > 250:
                pic = ImageOps.fit(photo.convert("RGB"), (W - 2 * M, ph), Image.LANCZOS)
                mask = Image.new("L", pic.size, 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, pic.width - 1, pic.height - 1), radius=32, fill=255)
                img.paste(pic, (M, y), mask)
                if cards.EDITORIAL:
                    d.rounded_rectangle((M, y, W - M, y + ph), radius=32, outline=accent, width=4)
    elif kind == "cover" and slide.get("cover_image"):
        # copertina con immagine a tutta larghezza: sfuma nel nero e il titolo sta sotto, come le copertine foto dei caroselli
        pic = ImageOps.fit(Image.open(slide["cover_image"]).convert("RGB"), (W, 1250), Image.LANCZOS, centering=(0.5, 0.42))
        img.paste(pic, (0, 14))
        fade_h = 520
        mask = Image.new("L", (W, fade_h))
        mask.putdata([int(255 * (y / (fade_h - 1)) ** 1.4) for y in range(fade_h) for _ in range(W)])
        img.paste(Image.new("RGB", (W, fade_h), bg), (0, 14 + 1250 - fade_h), mask)
        d.rounded_rectangle((M - 30, 90, M + 650, 260), radius=28, fill="#0A0A0A")
        sz = cards.paste_logo(img, "logo-symbol-light", M - 14, 106, height=138)
        cards.paste_logo(img, "logo-wordmark-light", M - 14 + sz[0] + 24, 124, height=102)
        y = 1100
        kick = slide.get("kicker", "")
        if kick:
            f = cards.font("Bold", 34)
            tw = d.textlength(kick, font=f)
            a_rgb = tuple(int(accent.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
            a_ink = "#0A0A0A" if (0.299 * a_rgb[0] + 0.587 * a_rgb[1] + 0.114 * a_rgb[2]) / 255 > 0.55 else "#FFFFFF"
            d.rounded_rectangle([M, y, M + tw + 48, y + 66], radius=33, fill=accent)
            d.text((M + 24, y + 13), kick, font=f, fill=a_ink)
            y += 112
        fnt, lines, size = cards.fit(d, slide["title"], cards.H_("ExtraBold"), 96, 58, W - 2 * M, 1920 - 190 - 110 - y, 1.12)
        cards.draw_rich(d, " ".join(lines), slide.get("highlight", ""), fnt, size, M, y, W - 2 * M, "#FFFFFF",
                        1.12, slide.get("mark") or accent, half=True)
    elif kind == "cover":
        inkc = ("#FFFFFF" if not light else "#0A0A0A") if mono else DARK_TEXT
        if cards.EDITORIAL:                          # logo v3 nel colore del tipo
            sz = cards.paste_logo(img, "logo-symbol" if light else "logo-symbol-light", M - 10, 260, height=170)
            cards.paste_logo(img, "logo-wordmark" if light else "logo-wordmark-light", M - 10 + sz[0] + 28, 278, height=126)
            y = 260 + 170 + 200
        else:
            logo = Image.open(ROOT / "docs" / "logo-horizontal.png").convert("RGBA")
            lw = 560
            logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
            img.paste(logo, (M - 10, 260), logo)
            y = 260 + logo.height + 200
        kick = slide.get("kicker", "")
        if kick:
            f = cards.font("Bold", 34)
            tw = d.textlength(kick, font=f)
            if cards.EDITORIAL:                      # etichetta piena nel colore del tipo, come nei caroselli
                a_rgb = tuple(int(accent.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
                a_ink = "#0A0A0A" if (0.299 * a_rgb[0] + 0.587 * a_rgb[1] + 0.114 * a_rgb[2]) / 255 > 0.55 else "#FFFFFF"
                pill = accent
                if light and max(a_rgb) - min(a_rgb) < 30 and min(a_rgb) > 200:   # bianco su fondo chiaro (Latest
                    pill, a_ink = "#0A0A0A", "#FFFFFF"                            # Science): etichetta nera, testo bianco
                d.rounded_rectangle([M, y, M + tw + 48, y + 66], radius=33, fill=pill)
                d.text((M + 24, y + 13), kick, font=f, fill=a_ink)
            else:
                d.rounded_rectangle([M, y, M + tw + 48, y + 66], radius=33, outline=inkc, width=3)
                d.text((M + 24, y + 13), kick, font=f, fill=inkc)
            y += 130
        fnt, lines, size = cards.fit(d, slide["title"], cards.H_("ExtraBold"), 112, 70, W - 2 * M, 620, 1.12)
        y = cards.draw_rich(d, " ".join(lines), slide.get("highlight", ""), fnt, size, M, y, W - 2 * M, inkc,
                            1.12, slide.get("mark") or accent, half=True)
        if slide.get("body"):
            fb = cards.font("Regular", 44)
            y += 50
            for line in _wrap(d, slide["body"], fb, W - 2 * M):
                d.text((M, y), line, font=fb, fill=(("#BDBDBD" if not light else "#3A3A3A") if mono else "#3D5266") if not slide.get("bg") else inkc)
                y += 62
    elif kind == "image":
        # schermata con immagini (schermate del sito in un telefono, oppure copertine affiancate)
        f_lab = cards.font("Bold", 30)
        d.text((M, 170), (slide.get("kicker") or cfg.get("brand_name", "")).upper(), font=f_lab, fill=accent)
        fnt, lines, size = cards.fit(d, slide["title"], cards.H_("ExtraBold"), 84, 56, W - 2 * M, 230, 1.1)
        y = 230
        for line in lines:
            d.text((M, y), line, font=fnt, fill=fg)
            y += int(size * 1.1)
        if slide.get("body"):
            fb = cards.font("Regular", 40)
            for line in _wrap(d, slide["body"], fb, W - 2 * M)[:2]:
                d.text((M, y + 14), line, font=fb, fill=c["muted_text"])
                y += 54
        y += 60
        paths = [ROOT / p if not Path(p).is_absolute() else Path(p) for p in slide.get("images", [])]
        pics = [Image.open(p).convert("RGB") for p in paths if p.exists()]
        bottom = H - 250
        if pics and slide.get("frame", "phone") == "phone":
            n = len(pics)
            gap = 50
            pw = min(560, (W - 2 * M - gap * (n - 1)) // n)
            for i, pic in enumerate(pics):
                ph = min(bottom - y - 30, int(pw * pic.height / pic.width))
                x0 = (W - (pw * n + gap * (n - 1))) // 2 + i * (pw + gap)
                crop = pic.crop((0, 0, pic.width, int(pic.width * ph / pw)))
                shot = crop.resize((pw, ph), Image.LANCZOS)
                d.rounded_rectangle((x0 - 16, y - 16, x0 + pw + 16, y + ph + 16), radius=48, fill="#05121C",
                                    outline="#2A4058", width=4)
                mask = Image.new("L", (pw, ph), 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw - 1, ph - 1), radius=34, fill=255)
                img.paste(shot, (x0, y), mask)
        elif pics and slide.get("frame") == "card":           # immagine intera su scheda arrotondata
            pic = ImageOps.contain(pics[0], (W - 2 * M, bottom - y - 20), Image.LANCZOS)
            x0 = (W - pic.width) // 2
            mask = Image.new("L", pic.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, pic.width - 1, pic.height - 1), radius=32, fill=255)
            d.rounded_rectangle((x0 - 10, y - 10, x0 + pic.width + 10, y + pic.height + 10), radius=40, fill="#05121C")
            img.paste(pic, (x0, y), mask)
        elif pics:                                            # copertine a cascata, grandi e sovrapposte
            n = len(pics)
            cw = 560
            step_x = (W - 2 * M - cw) // max(1, n - 1)
            step_y = min(240, (bottom - y - int(cw * 1.25)) // max(1, n - 1))
            for i, pic in enumerate(pics):
                ch = int(cw * pic.height / pic.width)
                cov = pic.resize((cw, ch), Image.LANCZOS)
                x0, yy = M + i * step_x, y + i * step_y
                d.rounded_rectangle((x0 - 8, yy - 8, x0 + cw + 8, yy + ch + 8), radius=20, fill="#05121C")
                img.paste(cov, (x0, yy))
    elif kind == "closing":
        if cards.EDITORIAL:                          # logo v3 nel colore del tipo, centrato
            sym = cards.logo_v3("logo-symbol-light", 300)
            img.paste(sym, ((W - sym.width) // 2, 380), sym)
            word = cards.logo_v3("logo-wordmark-light", 210)
            img.paste(word, ((W - word.width) // 2, 740), word)
        else:
            sym = Image.open(ROOT / "assets" / "logo-symbol-light.png").convert("RGBA").resize((300, 302), Image.LANCZOS)
            img.paste(sym, ((W - 300) // 2, 380), sym)
            word = Image.open(ROOT / "assets" / "logo-wordmark-light.png").convert("RGBA")
            ww = 520
            word = word.resize((ww, int(word.height * ww / word.width)), Image.LANCZOS)
            img.paste(word, ((W - ww) // 2, 740), word)
        y = 740 + word.height + 120
        for text, f, col in ((slide.get("title", ""), cards.font(cards.H_("ExtraBold"), 66), "#FFFFFF"),
                             (slide.get("body", ""), cards.font("SemiBold", 46), accent),
                             (cfg.get("handle", ""), cards.font("Regular", 40), c["muted_text"])):
            for line in _wrap(d, text, f, W - 2 * M):
                tw = d.textlength(line, font=f)
                d.text(((W - tw) / 2, y), line, font=f, fill=col)
                y += int(f.size * 1.3)
            y += 26
    else:
        f_lab = cards.font("Bold", 30)
        brand = cfg.get("brand_name", "").upper()
        d.text((M, 150), brand, font=f_lab, fill=accent if cards.EDITORIAL else c["accent"])
        fnt, lines, size = cards.fit(d, slide["title"], cards.H_("ExtraBold"), 92, 60, W - 2 * M, 420, 1.12)
        fb = cards.font("Regular", 50)
        body_lines = _wrap(d, slide.get("body", ""), fb, W - 2 * M)
        photo = _photo(slide.get("photo_query"))
        ph = 560 if photo is not None else 0
        block = 190 + len(lines) * size * 1.12 + 60 + len(body_lines) * 50 * 1.42 + (ph + 60 if ph else 0)
        top = max(260, int((H - block) / 2) - 60)          # contenuto centrato in verticale
        num = slide.get("number", "")
        if num == "→":                       # il serif non ha la freccia: si disegna nel colore del tipo
            ay = top + 95
            d.line((M + 4, ay, M + 140, ay), fill=accent, width=16)
            d.polygon([(M + 140, ay - 36), (M + 206, ay), (M + 140, ay + 36)], fill=accent)
        else:
            d.text((M, top), num, font=cards.font(cards.H_("ExtraBold"), 150), fill=accent)
        y = top + 210
        for line in lines:
            d.text((M, y), line, font=fnt, fill=fg)
            y += int(size * 1.12)
        y += 60
        y = cards.draw_rich(d, slide.get("body", ""), slide.get("highlight", ""), fb, 50, M, y, W - 2 * M, c["muted_text"],
                            1.42, accent, mark_text=c["background"])
        if photo is not None:                  # foto pertinente sotto il testo, con contorno nel colore del tipo
            y = int(y) + 60
            ph = min(ph, H - 260 - y)
            if ph > 250:
                pic = ImageOps.fit(photo.convert("RGB"), (W - 2 * M, ph), Image.LANCZOS)
                mask = Image.new("L", pic.size, 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, pic.width - 1, pic.height - 1), radius=32, fill=255)
                img.paste(pic, (M, y), mask)
                d.rounded_rectangle((M, y, W - M, y + ph), radius=32, outline=accent, width=4)
    # avanzamento in basso, nel colore del tipo
    yb = H - 190
    seg = (W - 2 * M - (total - 1) * 12) / total
    done_c = accent if cards.EDITORIAL else bar
    for i in range(total):
        x0 = M + i * (seg + 12)
        d.rounded_rectangle([x0, yb, x0 + seg, yb + 8], radius=4,
                            fill=done_c if i <= index else (("#CFCFCF" if light else "#2E2E2E") if mono else ("#C9D6DF" if light else "#2A4058")))
    if kind != "closing":
        f_h = cards.font("SemiBold", 32)
        d.text((M, yb + 40), cfg.get("handle", ""), font=f_h, fill="#5B7186" if light else c["muted_text"])
    if cubes and cards.EDITORIAL and kind != "image" and not slide.get("cover_image"):    # cubetti negli spazi liberi (i pixel già disegnati si evitano da soli)
        _cubes(img, f"{kind}-{index}-{slide.get('title', '')[:24]}", accent, not light, cfg,
               keep_out=[(0, yb - 30, W, H), (0, 0, W, 30)], density=0.8 if kind in ("cover", "closing") else 0.55)
    return img


def frame_seconds(slide):
    """Tempo a schermo di una schermata del reel: copertina e chiusura brevi, le altre secondo le parole
    (circa 200 al minuto, più un secondo per orientarsi), tra 3 e 6 secondi."""
    if slide.get("type") in ("cover", "closing"):
        return 3.0 if slide.get("type") == "cover" else 3.5
    if slide.get("type") == "image":
        return 4.5
    if slide.get("type") == "stat":
        return 4.5
    words = len(f"{slide.get('title', '')} {slide.get('body', '')}".split())
    return round(max(3.0, min(6.0, 1.0 + words / 3.4)), 1)


def build_story_reel(spec, out_path, cfg, mood="Cerimony|Ceremony|Aziendale|Speciale|Funky"):
    """Reel nativo verticale da una lista di schermate (spec): copertina, punti brevi, chiusura. 20–30 secondi.
    Con spec «rain» (o config reel_rain) i cubetti scendono ai lati come sul sito."""
    accent = spec.get("accent") or cfg.get("announcement_accent", "#FF7A59")
    slides = spec["slides"]
    imgs = [story_frame(s, cfg, i, len(slides), accent) for i, s in enumerate(slides)]
    lengths = [frame_seconds(s) for s in slides]
    if spec.get("rain", cfg.get("reel_rain", False)):
        return rain_reel(imgs, lengths, out_path, cfg, accent, mood=spec.get("mood") or mood,
                         track=spec.get("music_track"))
    return build_reel([], out_path, cfg, accent=accent, per_slide=lengths, images=imgs,
                      mood=spec.get("mood") or mood, track=spec.get("music_track"))


# ---------------------------------------------------------------- reel animato: scritte con effetti, musica da file
def _bands(mask, gap=8, min_h=6):
    """Righe di testo (y0, y1, x0, x1) da una maschera di pixel: gruppi di righe separati da almeno `gap` px vuoti."""
    import numpy as np
    rows = np.where(mask.any(axis=1))[0]
    out, start, prev = [], None, None
    for y in rows:
        if start is None:
            start = prev = y
        elif y - prev > gap:
            out.append((start, prev + 1))
            start = y
        prev = y
    if start is not None:
        out.append((start, prev + 1))
    bands = []
    for y0, y1 in out:
        if y1 - y0 < min_h:
            continue
        cols = np.where(mask[y0:y1].any(axis=0))[0]
        bands.append((int(y0), int(y1), int(cols.min()), int(cols.max()) + 1))
    return bands


def _ease_out(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _back_out(x):
    x = max(0.0, min(1.0, x))
    c = 1.70158
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def _slide_layers(slide, cfg, index, total, accent):
    """Fondo (cornice, logo), righe di testo animabili e strato dei cubetti di una schermata."""
    import numpy as np
    blank = {k: v for k, v in slide.items() if k in ("type", "accent", "bg", "images", "frame", "photo_query", "cover_image")}
    blank.update(title="", body="", kicker="", number="")
    base = story_frame(blank, cfg, index, total, accent, cubes=False)
    text = story_frame(slide, cfg, index, total, accent, cubes=False)
    full = story_frame(slide, cfg, index, total, accent, cubes=True)
    a, b, c = (np.asarray(x, dtype=np.int16) for x in (base, text, full))
    tmask = np.abs(b - a).sum(axis=2) > 24
    cmask = np.abs(c - b).sum(axis=2) > 0
    return base, text, full, tmask, cmask, _bands(tmask)


def animated_frames(slides, cfg, accent, fps=FPS, trans=0.35):
    """Fotogrammi del reel animato: ogni riga entra con un effetto diverso (etichette in dissolvenza, numeri grandi
    che «saltano», titoli che si scrivono da sinistra, testi che salgono), cubetti in dissolvenza, cambio di
    schermata a spinta laterale. Restituisce (generatore di fotogrammi, durata)."""
    import numpy as np
    total = len(slides)
    layers = [_slide_layers(s, cfg, i, total, s.get("accent") or accent) for i, s in enumerate(slides)]
    lengths = [frame_seconds(s) + 0.5 for s in slides]
    starts = np.cumsum([0] + lengths[:-1]).tolist()
    duration = sum(lengths)

    def render(i, t):
        base, text, full, tmask, cmask, bands = layers[i]
        out = np.asarray(base, dtype=np.float32).copy()
        tx = np.asarray(text, dtype=np.float32)
        fl = np.asarray(full, dtype=np.float32)
        fade = _ease_out((t - 0.2) / 0.8)                      # cubetti
        out[cmask] = out[cmask] * (1 - fade) + fl[cmask] * fade
        for k, (y0, y1, x0, x1) in enumerate(bands):
            t0 = 0.15 + k * 0.14
            p = (t - t0) / 0.45
            if p <= 0:
                continue
            h = y1 - y0
            src = tx[y0:y1]
            m = tmask[y0:y1].astype(np.float32)[..., None]
            if h > 150:                                        # numero grande: entra con un rimbalzo
                sc = 0.6 + 0.4 * _back_out(p)
                al = _ease_out(p * 1.6)
                crop = Image.fromarray(src.astype(np.uint8)).crop((x0, 0, x1, h))
                mk = Image.fromarray((m[..., 0] * 255).astype(np.uint8)).crop((x0, 0, x1, h))
                w2, h2 = max(1, int((x1 - x0) * sc)), max(1, int(h * sc))
                crop, mk = crop.resize((w2, h2)), mk.resize((w2, h2))
                cy = y0 + (h - h2) // 2
                region = out[cy:cy + h2, x0:x0 + w2]
                mm = np.asarray(mk, dtype=np.float32)[..., None] / 255 * al
                region[:] = region * (1 - mm) + np.asarray(crop, dtype=np.float32)[:region.shape[0], :region.shape[1]] * mm
            elif h > 55:                                       # titolo: si scrive da sinistra a destra
                q = _ease_out(p)
                edge = x0 + int((x1 - x0 + 40) * q)
                cols = np.arange(out.shape[1])
                wipe = np.clip((edge - cols) / 40.0, 0, 1)[None, :, None]
                mm = m * wipe
                out[y0:y1] = out[y0:y1] * (1 - mm) + src * mm
            else:                                              # testo ed etichette: salgono e compaiono
                q = _ease_out(p)
                dy = int((1 - q) * 36)
                al = q
                ya, yb = y0 + dy, min(out.shape[0], y1 + dy)
                mm = m[:yb - ya] * al
                out[ya:yb] = out[ya:yb] * (1 - mm) + src[:yb - ya] * mm
        return out

    def gen():
        for f in range(int(duration * fps)):
            tt = f / fps
            i = max(j for j in range(total) if starts[j] <= tt)
            t = tt - starts[i]
            cur = render(i, t)
            if i > 0 and t < trans:                            # cambio di schermata: spinta da destra
                q = _ease_out(t / trans)
                prev = render(i - 1, lengths[i - 1])
                shift = int(W * q)
                frame = np.empty_like(cur)
                frame[:, :W - shift] = prev[:, shift:]
                frame[:, W - shift:] = cur[:, :shift]
                cur = frame
            yield cur.astype(np.uint8)
    return gen, round(duration, 1)


def animated_reel(spec, out_path, cfg, music_file=None, mood="Funky", track=None):
    """Reel con scritte animate (vedi animated_frames). Musica: `music_file` (estratto sul ritornello) oppure la
    libreria su Drive del genere `mood`. Restituisce la durata in secondi."""
    import music as _music
    accent = spec.get("accent") or cfg["colors"]["accent"]
    gen, duration = animated_frames(spec["slides"], cfg, accent)
    out_path = Path(out_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        silent, wav = tmp / "v.mp4", tmp / "m.wav"
        p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                              "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                              "-preset", "veryfast", str(silent)], stdin=subprocess.PIPE)
        for fr in gen():
            p.stdin.write(fr.tobytes())
        p.stdin.close()
        p.wait()
        if music_file:
            start = _music.best_start(music_file, duration)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-i", str(music_file),
                            "-t", f"{duration:.2f}", "-af", f"afade=t=in:d=0.3,afade=t=out:st={duration - 1.5:.2f}:d=1.5,"
                            "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "2", str(wav)], check=True)
        else:
            music(wav, duration, mood=mood, track=track)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(wav), "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-shortest", "-movflags", "+faststart",
                        str(out_path)], check=True)
    return duration


RAIN_COLORS = [(61, 217, 193), (20, 160, 133), (255, 255, 255), (127, 150, 171)]   # stessi colori del sito


def _rain(seed, accent):
    """Particelle come la cascata del sito: cubetti singoli o in gruppi da 2–3, lenti (40–110 px/s su 1080 px,
    cioè la velocità del sito su uno schermo da telefono), semitrasparenti."""
    import random
    rnd = random.Random(seed)
    shapes = [[(0, 0)], [(0, 0)], [(0, 0), (1, 0)], [(0, 0), (0, 1)], [(0, 0), (1, 0), (0, 1)], [(0, 0), (1, 0), (1, 1)]]
    out = []
    for _ in range(40):
        side = rnd.random() < 0.5
        s = rnd.choice([8, 12, 16, 20, 24])
        span = 2 * s + 4                       # i cubetti restano nei margini, mai sopra il testo (M = 96)
        x = rnd.randint(4, max(5, 90 - span)) if side else rnd.randint(W - 90, max(W - 89, W - 4 - span))
        out.append({"x": x, "s": s, "shape": rnd.choice(shapes), "speed": rnd.uniform(40, 110),
                    "off": rnd.uniform(0, H + 300), "col": rnd.choice(RAIN_COLORS),
                    "alpha": int(255 * (0.12 + rnd.random() * 0.5))})
    return out


def rain_reel(imgs, lengths, out_path, cfg, accent, fade=0.5, mood="Cerimony", track=None):
    """Come build_reel, ma i fotogrammi si disegnano in Python per far scendere i cubetti; dissolvenze tra le
    schermate. Restituisce la durata in secondi."""
    starts, t = [], 0.0
    for i, ln in enumerate(lengths):
        starts.append(t)
        t += ln - (fade if i < len(lengths) - 1 else 0)
    duration = t
    parts = _rain(len(imgs), accent)
    out_path = Path(out_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        silent, wav = tmp / "v.mp4", tmp / "m.wav"
        p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                              "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "21",
                              "-preset", "medium", str(silent)], stdin=subprocess.PIPE)
        for k in range(int(duration * FPS)):
            tt = k / FPS
            i = max(j for j in range(len(imgs)) if starts[j] <= tt)
            if i > 0 and tt < starts[i] + fade:          # dissolvenza dalla schermata precedente
                frame = Image.blend(imgs[i - 1], imgs[i], (tt - starts[i]) / fade)
            else:
                frame = imgs[i]
            frame = frame.convert("RGBA")
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            for q in parts:
                y = (q["off"] + tt * q["speed"]) % (H + 300) - 150
                for dx, dy in q["shape"]:
                    x0, y0 = q["x"] + dx * (q["s"] + 4), y + dy * (q["s"] + 4)
                    d.rectangle((x0, y0, x0 + q["s"], y0 + q["s"]), fill=q["col"] + (q["alpha"],))
            p.stdin.write(Image.alpha_composite(frame, layer).convert("RGB").tobytes())
        p.stdin.close()
        p.wait()
        music(wav, duration, mood=mood, track=track)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(wav), "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-shortest", "-movflags", "+faststart",
                        str(out_path)], check=True)
    return round(duration, 1)


# ---------------------------------------------------------------- copioni dei reel, diversi per tipo di post
def _clip_words(text, n):
    words = (text or "").split()
    return " ".join(words) if len(words) <= n else " ".join(words[:n]).rstrip(",;:") + "…"


def _short_sentence(text, n):
    """Prima frase intera se non supera n parole, altrimenti niente (mai frasi tagliate a metà)."""
    import re
    first = re.split(r"(?<=[.!?])\s+", (text or "").strip())[0]
    return first if 0 < len(first.split()) <= n else ""


def _what_it_funds(summary):
    """«This funding opportunity from X aims to pilot…» → «Pilot…»: la frase sui progetti finanziati, intera."""
    import re
    for sent in re.split(r"(?<=[.!?])\s+", (summary or "").strip())[:2]:
        core = re.sub(r"^(this|the) (funding opportunity|funding call|call|programme|program|grant|award|scheme|"
                      r"initiative|notice of funding opportunity)( from [^,]+?| by [^,]+?)?,? "
                      r"(aims to|seeks to|is intended to|will|supports|funds|provides funding for|invites applications to)\s+",
                      "", sent, flags=re.I)
        core = core[:1].upper() + core[1:]
        if 0 < len(core.split()) <= 24:
            return core
    return ""


REEL_SCRIPT_PROMPT = """Turn this Instagram carousel about research methodology into the script of a ~25-second reel
for clinical researchers. Use ONLY the content below: no new facts, numbers, studies or claims.
- hook: max 8 words, a curiosity hook built on the title (a question or a crisp claim).
- beats: exactly 3, the most useful points in the carousel's logical order, each with title (max 6 words) and line
  (max 14 words, plain language). Each line must be a complete, precise statement on its own: name the subject (no
  "this", "it"), keep the qualifiers of the carousel, never shorten a claim into something stronger or wrong.
- takeaway: the take-home message, max 14 words, specific and faithful to the carousel's takeaway.

Title: {title}
Points:
{points}
Takeaway: {takeaway}"""

REEL_SCRIPT_SCHEMA = {"type": "OBJECT", "properties": {
    "hook": {"type": "STRING"}, "takeaway": {"type": "STRING"},
    "beats": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "title": {"type": "STRING"}, "line": {"type": "STRING"}}, "required": ["title", "line"]}}},
    "required": ["hook", "beats", "takeaway"]}


def rubric_tag(entry, cfg, default_label, default_accent):
    """(etichetta, colore) della copertina del reel: nel brand v4 nome e colore della rubrica, una sola etichetta.
    Un post di ricerca con categoria «Clinical insight» (sabato) è Latest Science, gli altri Design, Reporting & Appraisal."""
    if not cards.BRAND_V4:
        return default_label, default_accent
    import content
    kind = entry.get("kind")
    if kind in ("grant", "positions"):
        line = kind
    else:
        science = entry.get("category") == content.CLINICAL_CATEGORY or entry.get("rubric") == "Clinical Insights"
        line = "science" if science else "methods"
    return cards.V4_RUBRIC[line][0], cards.V4_ACCENT[line]


def research_spec(entry, cfg):
    """Metodologia: gancio, 3 punti essenziali (riscritti brevi da Gemini, solo dal carosello), messaggio finale."""
    points = entry.get("points") or []
    script = None
    try:
        import content
        txt = "\n".join(f"- {p['heading']}: {p['body']}" for p in points)
        script = content.gemini_json([{"text": REEL_SCRIPT_PROMPT.format(title=entry["title"], points=txt,
                                                                          takeaway=entry.get("takeaway", ""))}],
                                     REEL_SCRIPT_SCHEMA, 0.3, task="copione reel")
    except Exception as e:
        print(f"  Copione del reel non scritto da Gemini ({str(e)[:120]}): uso i titoli del carosello.")
    if script and len(script.get("beats", [])) >= 2:
        hook = _clip_words(script["hook"], 9)
        beats = [(_clip_words(b["title"], 7), _clip_words(b["line"], 16)) for b in script["beats"][:3]]
        takeaway = _clip_words(script["takeaway"], 16)
    else:
        hook = entry["title"]
        beats = [(p["heading"], _short_sentence(p["body"], 20)) for p in points[:3]]
        takeaway = _clip_words(entry.get("takeaway", ""), 16)
    kicker, accent = rubric_tag(entry, cfg, (entry.get("category") or "Research methods").upper(), cfg["colors"]["accent"])
    slides = [{"type": "cover", "kicker": kicker, "title": hook}]
    slides += [{"type": "point", "number": f"{i:02d}", "title": t, "body": b} for i, (t, b) in enumerate(beats, 1)]
    if takeaway:
        slides.append({"type": "point", "number": "→", "title": "Remember", "body": takeaway})
    slides.append({"type": "closing", "title": "Full carousel with references on our profile", "body": "Save it for later"})
    return {"accent": accent, "mood": "Classica", "slides": slides}


def grant_spec(p, v, cfg, today=None):
    """Bando: solo dati verificati sul testo ufficiale (scadenza, Paesi ammessi, cosa finanzia). None se scaduto."""
    from datetime import date
    import grants
    import stories
    today = today or date.today()
    deadline = grants._date(p.get("deadline"))
    if not deadline or (deadline - today).days < 7:
        return None
    days = (deadline - today).days
    kicker, accent = rubric_tag({"kind": "grant"}, cfg, "FUNDING CALL", cfg.get("grant_accent", "#FFB547"))
    slides = [{"type": "cover", "kicker": kicker, "title": p["title"],
               "body": _clip_words(v.get("programme") or p.get("funder", ""), 14)},
              {"type": "point", "number": "01", "title": "Deadline",
               "body": f"{grants._fmt_date(deadline)}: {days} days left to apply."}]
    where = stories.open_to(v) if v else None
    if where:
        slides.append({"type": "point", "number": "02", "title": "Who can apply", "body": f"Open to: {where}."})
    what = _what_it_funds(v.get("summary") or p.get("summary", ""))
    if what:
        slides.append({"type": "point", "number": f"{len(slides):02d}", "title": "What it funds", "body": what})
    slides.append({"type": "closing", "title": "Official call and all open calls", "body": "Link in bio"})
    return {"accent": accent, "mood": "Rock", "slides": slides}


def positions_spec(p, archive, cfg, today=None, max_jobs=4):
    """Posizioni: fino a 4 annunci ancora aperti (tipo, titolo, ente, Paese, scadenza); gli altri si contano."""
    from datetime import date
    import grants
    import positions
    today = today or date.today()
    jobs = []
    for pid in p.get("position_ids", []):
        v = archive.get(pid) or {}
        d = grants._date(v.get("deadline"))
        if v.get("status") == "ok" and (not d or d >= today):
            jobs.append((v, d))
    if len(jobs) < 2:
        return None
    kicker, accent = rubric_tag({"kind": "positions"}, cfg, "ACADEMIC POSITIONS", cfg["colors"]["accent"])
    slides = [{"type": "cover", "kicker": kicker, "title": "Academic positions for clinical researchers",
               "body": f"{len(jobs)} open positions this week"}]
    for i, (v, d) in enumerate(jobs[:max_jobs], 1):
        bits = [positions.TYPES.get(v.get("type"), ""), _clip_words(v.get("institution", ""), 6), v.get("country", ""),
                f"deadline {grants._fmt_date(d)}" if d else ""]
        slides.append({"type": "point", "number": f"{i:02d}", "title": _clip_words(v.get("title", ""), 9),
                       "body": " · ".join(b for b in bits if b)})
    more = len(jobs) - max_jobs
    slides.append({"type": "closing", "title": (f"+{more} more, " if more > 0 else "") + "all with deadlines and links",
                   "body": "Link in bio"})
    return {"accent": accent, "mood": "Funky", "slides": slides}


if __name__ == "__main__":     # prova locale: python reels.py <cartella slide> <file.mp4>
    import sys
    cfg = json.load(open(ROOT / "config.json"))
    folder = Path(sys.argv[1])
    print(build_reel(sorted(folder.glob("slide-*.jpg"), key=lambda p: int(p.stem.split("-")[1])), sys.argv[2], cfg))
