"""Reel verticali (1080×1920) ricavati dai caroselli già pubblicati: ogni slide resta a schermo qualche secondo
con un leggero zoom, dissolvenza tra le slide e una musica di sottofondo originale generata qui (niente diritti)."""

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

import cards

ROOT = Path(__file__).resolve().parent
W, H = 1080, 1920
FPS = 30


def frame(slide_path, cfg, index, total, accent):
    """Una slide del carosello dentro il formato verticale: fascia alta con il marchio, fascia bassa con l'invito."""
    c = cfg["colors"]
    img = Image.new("RGB", (W, H), c["background"])
    d = ImageDraw.Draw(img)
    sw, sh = 960, 1200                     # margini laterali: lo zoom non taglia mai il testo della slide
    slide = Image.open(slide_path).convert("RGB").resize((sw, sh), Image.LANCZOS)
    top = (H - sh) // 2 - 20
    img.paste(slide, ((W - sw) // 2, top))
    # fascia alta: marchio
    d.rectangle([0, 0, W, 10], fill=accent)
    f_small = cards.font("Bold", 30)
    brand = cfg.get("brand_name", "").upper()
    tw = d.textlength(brand, font=f_small)
    d.text(((W - tw) / 2, 120), brand, font=f_small, fill=c["accent"])
    # fascia bassa: avanzamento e invito al carosello completo
    y = top + sh + 60
    seg = (W - 160 - (total - 1) * 12) / total
    for i in range(total):
        x0 = 80 + i * (seg + 12)
        d.rounded_rectangle([x0, y, x0 + seg, y + 8], radius=4, fill=accent if i <= index else "#2A4058")
    msg = "Full carousel on our profile"
    f_msg = cards.font("SemiBold", 34)
    tw = d.textlength(msg, font=f_msg)
    d.text(((W - tw) / 2, y + 40), msg, font=f_msg, fill="#FFFFFF")
    handle = cfg.get("handle", "")
    f_h = cards.font("Regular", 30)
    tw = d.textlength(handle, font=f_h)
    d.text(((W - tw) / 2, y + 92), handle, font=f_h, fill=c["muted_text"])
    return img


def music(path, seconds, seed=0, mood="Classica"):
    """Base strumentale originale (lo-fi con batteria, basso, accordi e melodia): vedi music.py."""
    import music as _music
    return _music.for_video(path, seconds, seed, mood=mood)


def build_reel(slide_paths, out_path, cfg, accent=None, per_slide=4.6, edge=2.8, fade=0.5, with_music=True, images=None,
               mood="Classica"):
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
            music(wav, duration, mood=mood)
            cmd += ["-i", str(wav)]
        cmd += ["-filter_complex", graph, "-map", f"[{last}]"]
        if with_music:
            cmd += ["-map", f"{total}:a", "-c:a", "aac", "-b:a", "128k", "-ar", "44100"]
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


def story_frame(slide, cfg, index, total, accent):
    """Slide 1080×1920 per i reel di annuncio: copertina chiara, punti numerati scuri, chiusura con il logo."""
    c = cfg["colors"]
    kind = slide.get("type", "point")
    light = kind == "cover"
    bg, fg = (LIGHT_BG, DARK_TEXT) if light else (c["background"], "#FFFFFF")
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    M = 96
    d.rectangle([0, 0, W, 14], fill=accent)
    if kind == "cover":
        logo = Image.open(ROOT / "docs" / "logo-horizontal.png").convert("RGBA")
        lw = 560
        logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
        img.paste(logo, (M - 10, 260), logo)
        y = 260 + logo.height + 200
        kick = slide.get("kicker", "")
        if kick:
            f = cards.font("Bold", 34)
            tw = d.textlength(kick, font=f)
            d.rounded_rectangle([M, y, M + tw + 48, y + 66], radius=33, outline=DARK_TEXT, width=3)
            d.text((M + 24, y + 13), kick, font=f, fill=DARK_TEXT)
            y += 130
        fnt, lines, size = cards.fit(d, slide["title"], "ExtraBold", 112, 70, W - 2 * M, 620, 1.12)
        y = cards.draw_rich(d, " ".join(lines), slide.get("highlight", ""), fnt, size, M, y, W - 2 * M, DARK_TEXT,
                            1.12, accent, half=True)
        if slide.get("body"):
            fb = cards.font("Regular", 44)
            y += 50
            for line in _wrap(d, slide["body"], fb, W - 2 * M):
                d.text((M, y), line, font=fb, fill="#3D5266")
                y += 62
    elif kind == "image":
        # schermata con immagini (schermate del sito in un telefono, oppure copertine affiancate)
        f_lab = cards.font("Bold", 30)
        d.text((M, 170), (slide.get("kicker") or cfg.get("brand_name", "")).upper(), font=f_lab, fill=accent)
        fnt, lines, size = cards.fit(d, slide["title"], "ExtraBold", 84, 56, W - 2 * M, 230, 1.1)
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
        sym = Image.open(ROOT / "assets" / "logo-symbol-light.png").convert("RGBA").resize((300, 302), Image.LANCZOS)
        img.paste(sym, ((W - 300) // 2, 380), sym)
        word = Image.open(ROOT / "assets" / "logo-wordmark-light.png").convert("RGBA")
        ww = 520
        word = word.resize((ww, int(word.height * ww / word.width)), Image.LANCZOS)
        img.paste(word, ((W - ww) // 2, 740), word)
        y = 740 + word.height + 120
        for text, f, col in ((slide.get("title", ""), cards.font("ExtraBold", 66), "#FFFFFF"),
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
        d.text((M, 150), brand, font=f_lab, fill=c["accent"])
        fnt, lines, size = cards.fit(d, slide["title"], "ExtraBold", 92, 60, W - 2 * M, 420, 1.12)
        fb = cards.font("Regular", 50)
        body_lines = _wrap(d, slide.get("body", ""), fb, W - 2 * M)
        block = 190 + len(lines) * size * 1.12 + 60 + len(body_lines) * 50 * 1.42
        top = max(300, int((H - block) / 2) - 60)          # contenuto centrato in verticale
        d.text((M, top), slide.get("number", ""), font=cards.font("ExtraBold", 150), fill=accent)
        y = top + 210
        for line in lines:
            d.text((M, y), line, font=fnt, fill=fg)
            y += int(size * 1.12)
        y += 60
        cards.draw_rich(d, slide.get("body", ""), slide.get("highlight", ""), fb, 50, M, y, W - 2 * M, c["muted_text"],
                        1.42, accent, mark_text=c["background"])
    # avanzamento in basso
    yb = H - 190
    seg = (W - 2 * M - (total - 1) * 12) / total
    for i in range(total):
        x0 = M + i * (seg + 12)
        d.rounded_rectangle([x0, yb, x0 + seg, yb + 8], radius=4,
                            fill=accent if i <= index else ("#C9D6DF" if light else "#2A4058"))
    if kind != "closing":
        f_h = cards.font("SemiBold", 32)
        d.text((M, yb + 40), cfg.get("handle", ""), font=f_h, fill="#5B7186" if light else c["muted_text"])
    return img


def frame_seconds(slide):
    """Tempo a schermo di una schermata del reel: copertina e chiusura brevi, le altre secondo le parole
    (circa 200 al minuto, più un secondo per orientarsi), tra 3 e 6 secondi."""
    if slide.get("type") in ("cover", "closing"):
        return 3.0 if slide.get("type") == "cover" else 3.5
    if slide.get("type") == "image":
        return 4.5
    words = len(f"{slide.get('title', '')} {slide.get('body', '')}".split())
    return round(max(3.0, min(6.0, 1.0 + words / 3.4)), 1)


def build_story_reel(spec, out_path, cfg, mood="Aziendale|Speciale|Funky"):
    """Reel nativo verticale da una lista di schermate (spec): copertina, punti brevi, chiusura. 20–30 secondi."""
    accent = spec.get("accent") or cfg.get("announcement_accent", "#FF7A59")
    slides = spec["slides"]
    imgs = [story_frame(s, cfg, i, len(slides), accent) for i, s in enumerate(slides)]
    return build_reel([], out_path, cfg, accent=accent, per_slide=[frame_seconds(s) for s in slides], images=imgs,
                      mood=spec.get("mood") or mood)


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
- beats: exactly 3, the most useful points, each with title (max 6 words) and line (max 14 words, plain language).
- takeaway: the message to remember, max 14 words.

Title: {title}
Points:
{points}
Takeaway: {takeaway}"""

REEL_SCRIPT_SCHEMA = {"type": "OBJECT", "properties": {
    "hook": {"type": "STRING"}, "takeaway": {"type": "STRING"},
    "beats": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "title": {"type": "STRING"}, "line": {"type": "STRING"}}, "required": ["title", "line"]}}},
    "required": ["hook", "beats", "takeaway"]}


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
    slides = [{"type": "cover", "kicker": (entry.get("category") or "Research methods").upper(), "title": hook}]
    slides += [{"type": "point", "number": f"{i:02d}", "title": t, "body": b} for i, (t, b) in enumerate(beats, 1)]
    if takeaway:
        slides.append({"type": "point", "number": "→", "title": "Remember", "body": takeaway})
    slides.append({"type": "closing", "title": "Full carousel with references on our profile", "body": "Save it for later"})
    return {"accent": cfg["colors"]["accent"], "mood": "Classica", "slides": slides}


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
    slides = [{"type": "cover", "kicker": "FUNDING CALL", "title": p["title"],
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
    return {"accent": cfg.get("grant_accent", "#FFB547"), "mood": "Rock", "slides": slides}


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
    slides = [{"type": "cover", "kicker": "ACADEMIC POSITIONS", "title": f"{len(jobs)} open positions this week",
               "body": "Clinical research, biomedical engineering and rehabilitation."}]
    for i, (v, d) in enumerate(jobs[:max_jobs], 1):
        bits = [positions.TYPES.get(v.get("type"), ""), _clip_words(v.get("institution", ""), 6), v.get("country", ""),
                f"deadline {grants._fmt_date(d)}" if d else ""]
        slides.append({"type": "point", "number": f"{i:02d}", "title": _clip_words(v.get("title", ""), 9),
                       "body": " · ".join(b for b in bits if b)})
    more = len(jobs) - max_jobs
    slides.append({"type": "closing", "title": (f"+{more} more, " if more > 0 else "") + "all with deadlines and links",
                   "body": "Link in bio"})
    return {"accent": cfg["colors"]["accent"], "mood": "Funky", "slides": slides}


if __name__ == "__main__":     # prova locale: python reels.py <cartella slide> <file.mp4>
    import sys
    cfg = json.load(open(ROOT / "config.json"))
    folder = Path(sys.argv[1])
    print(build_reel(sorted(folder.glob("slide-*.jpg"), key=lambda p: int(p.stem.split("-")[1])), sys.argv[2], cfg))
