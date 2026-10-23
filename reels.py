"""Reel verticali (1080×1920) ricavati dai caroselli già pubblicati: ogni slide resta a schermo qualche secondo
con un leggero zoom, dissolvenza tra le slide e una musica di sottofondo originale generata qui (niente diritti)."""

import json
import math
import struct
import subprocess
import tempfile
import wave
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


def music(path, seconds, seed=0):
    """Sottofondo originale e tenue: accordi lenti (do–la–fa–sol) con inviluppo morbido, generati in Python."""
    rate = 44100
    roots = [261.63, 220.00, 174.61, 196.00]           # C, A, F, G
    chord = [1.0, 1.26, 1.5]                           # triade maggiore approssimata (ottava giusta)
    bar = 4.0
    n = int(seconds * rate)
    frames = bytearray()
    for i in range(n):
        t = i / rate
        k = int(t // bar) % len(roots)
        local = (t % bar) / bar
        env = min(1.0, local * 4) * min(1.0, (1 - local) * 4)        # attacco e rilascio morbidi in ogni battuta
        base = roots[(k + seed) % len(roots)]
        s = sum(math.sin(2 * math.pi * base * r * t) for r in chord) / len(chord)
        s += 0.35 * math.sin(2 * math.pi * base / 2 * t)             # basso un'ottava sotto
        fade = min(1.0, t / 1.5, (seconds - t) / 1.5)
        v = int(max(-1, min(1, s * env * fade * 0.22)) * 32767)
        frames += struct.pack("<hh", v, v)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def build_reel(slide_paths, out_path, cfg, accent=None, per_slide=4.6, edge=2.8, fade=0.5, with_music=True):
    """Video MP4 verticale (H.264 + AAC) dalle slide di un carosello: copertina e chiusura più brevi,
    slide di contenuto abbastanza lunghe da leggerle. Restituisce la durata in secondi."""
    accent = accent or cfg["colors"]["accent"]
    slide_paths = list(slide_paths)
    total = len(slide_paths)
    lengths = [edge if i in (0, total - 1) else per_slide for i in range(total)]
    duration = sum(lengths) - (total - 1) * fade
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        inputs, filters = [], []
        for i, sp in enumerate(slide_paths):
            p = tmp / f"f{i}.png"
            frame(sp, cfg, i, total, accent).save(p)
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
            music(wav, duration)
            cmd += ["-i", str(wav)]
        cmd += ["-filter_complex", graph, "-map", f"[{last}]"]
        if with_music:
            cmd += ["-map", f"{total}:a", "-c:a", "aac", "-b:a", "128k", "-ar", "44100"]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-r", str(FPS),
                "-movflags", "+faststart", "-t", f"{duration:.2f}", str(out_path)]
        subprocess.run(cmd, check=True)
    return round(duration, 1)


def reel_caption(post_entry, caption_text, cfg):
    """Didascalia breve del reel: titolo, una riga dal carosello, rimando al post completo, hashtag."""
    title = post_entry.get("title", "")
    first = next((l.strip() for l in caption_text.splitlines() if l.strip() and l.strip() != title), "")
    tags = " ".join(cfg.get("fixed_hashtags", []) + ["#Reels", "#ResearchTips"])
    return f"{title}\n\n{first[:300]}\n\nFull carousel with references on our profile.\n\n{tags}".strip()


if __name__ == "__main__":     # prova locale: python reels.py <cartella slide> <file.mp4>
    import sys
    cfg = json.load(open(ROOT / "config.json"))
    folder = Path(sys.argv[1])
    print(build_reel(sorted(folder.glob("slide-*.jpg"), key=lambda p: int(p.stem.split("-")[1])), sys.argv[2], cfg))
