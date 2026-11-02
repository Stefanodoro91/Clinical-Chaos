"""Anteprime su Drive: con i social in pausa (config «social_paused») ogni contenuto pronto si salva nella cartella
Drive «Anteprime», come se fosse uscito. Il bot sovrascrive file già creati dall'utente (config «preview_files»):
gli account di servizio non hanno spazio proprio su Drive e non possono crearne di nuovi."""

import io
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _cfg():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def paused(cfg=None):
    return bool((cfg or _cfg()).get("social_paused"))


def upload(path, key, mimetype, cfg=None):
    """Sovrascrive il file Drive di config «preview_files»[key] con il contenuto di `path`."""
    cfg = cfg or _cfg()
    fid = (cfg.get("preview_files") or {}).get(key)
    if not fid:
        print(f"::warning title=Anteprima::nessun file Drive per «{key}» in config preview_files")
        return False
    try:
        import music
        from googleapiclient.http import MediaFileUpload
        music._drive().files().update(fileId=fid, media_body=MediaFileUpload(str(path), mimetype=mimetype, resumable=True),
                                      supportsAllDrives=True).execute()
        print(f"::notice title=Anteprima su Drive::{key} aggiornata (Anteprime)")
        return True
    except Exception as e:
        print(f"::warning title=Anteprima non copiata su Drive::{key}: {str(e)[:200]}")
        return False


def carousel_pdf(slides, caption, out_path, extra_text=""):
    """PDF con le slide (una per pagina) e un'ultima pagina con didascalia e testi per gli altri social."""
    from PIL import Image, ImageDraw, ImageFont
    pages = [Image.open(io.BytesIO(b)).convert("RGB") if isinstance(b, (bytes, bytearray)) else Image.open(b).convert("RGB")
             for b in slides]
    W, H = pages[0].size if pages else (1080, 1350)
    font = ImageFont.truetype(str(ROOT / "fonts" / "Inter-Regular.ttf"), 30)
    bold = ImageFont.truetype(str(ROOT / "fonts" / "Inter-Bold.ttf"), 34)
    text = (caption or "") + (f"\n\n{extra_text}" if extra_text else "")
    sheet = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(sheet)
    d.text((70, 60), "Caption (preview, not published)", font=bold, fill="#15233A")
    y = 130
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            test = f"{line} {word}".strip()
            if d.textlength(test, font=font) > W - 140:
                d.text((70, y), line, font=font, fill="#222222")
                y += 40
                line = word
            else:
                line = test
        d.text((70, y), line, font=font, fill="#222222")
        y += 40
        if y > H - 60:
            break
    pages.append(sheet)
    pages[0].save(out_path, "PDF", save_all=True, append_images=pages[1:], resolution=150)
    return out_path
