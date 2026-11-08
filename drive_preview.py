"""Anteprime su Drive: con i social in pausa (config «social_paused») ogni contenuto pronto si salva nella cartella
Drive «Anteprime», come se fosse uscito. Il bot sovrascrive file già creati dall'utente (config «preview_files»):
gli account di servizio non hanno spazio proprio su Drive e non possono crearne di nuovi. Per questo ogni nuova
settimana di prova ha una cartella NUOVA con segnaposto creati con l'account di Stefano (week_preview.json «folder»):
mai riscrivere le cartelle vecchie. Un file di destinazione nel cestino non si riscrive (il 5/11 le anteprime
erano finite in file cestinati e non si vedevano): si segnala e lo slot risulta non salvato."""

import io
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _cfg():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def paused(cfg=None):
    return bool((cfg or _cfg()).get("social_paused"))


def upload(path, key, mimetype, cfg=None, file_id=None):
    """Sovrascrive il file Drive di config «preview_files»[key] (o `file_id`) con il contenuto di `path`."""
    cfg = cfg or _cfg()
    fid = file_id or (cfg.get("preview_files") or {}).get(key)
    if not fid:
        print(f"::warning title=Anteprima::nessun file Drive per «{key}» in config preview_files")
        return False
    try:
        import music
        from googleapiclient.http import MediaFileUpload
        meta = music._drive().files().get(fileId=fid, fields="trashed,name", supportsAllDrives=True).execute()
        if meta.get("trashed"):
            print(f"::error title=Anteprima non salvata::«{meta.get('name')}» è nel cestino di Drive: serve una cartella nuova")
            return False
        music._drive().files().update(fileId=fid, media_body=MediaFileUpload(str(path), mimetype=mimetype, resumable=True),
                                      supportsAllDrives=True).execute()
        print(f"::notice title=Anteprima su Drive::{key or fid} aggiornata (Anteprime)")
        return True
    except Exception as e:
        print(f"::warning title=Anteprima non copiata su Drive::{key}: {str(e)[:200]}")
        return False


def linkedin_doc(drafts_dir, cfg=None, keep=20):
    """Riscrive il Google Doc «Bozze LinkedIn» (config «linkedin_doc_id», creato con l'account di Stefano) con le
    ultime `keep` bozze di linkedin_drafts/, dalla più recente: testo pronto da incollare, niente pubblicazione."""
    cfg = cfg or _cfg()
    doc = cfg.get("linkedin_doc_id")
    files = sorted(Path(drafts_dir).glob("*.txt"), reverse=True)[:keep]
    if not doc or not files or not os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON"):
        return False
    parts = ["Bozze LinkedIn di Clinical Research Chaos: le ultime uscite, dalla più recente. Copia, incolla, pubblica a mano.",
             "Le uscite segnate (prova) vengono dai giorni con i social in pausa."]
    for f in files:
        date, rest = f.stem[:10], f.stem[11:]          # nome: AAAA-MM-GG-<tipo>-<id>.txt
        kind = rest.split("-", 1)[0]
        label = {"grant": "Funding calls", "positions": "Academic positions", "research": "Design, Reporting & Appraisal / Latest Science"}.get(kind, kind)
        parts.append("\n" + "═" * 40 + f"\n{date} · {label}" + (" (prova)" if cfg.get("social_paused") else "") + "\n" + "═" * 40)
        parts.append(f.read_text(encoding="utf-8").strip())
    text = "\n\n".join(parts)
    try:
        import music
        from googleapiclient.http import MediaInMemoryUpload
        music._drive().files().update(fileId=doc, media_body=MediaInMemoryUpload(text.encode("utf-8"), mimetype="text/plain"),
                                      supportsAllDrives=True).execute()
        print(f"::notice title=Bozze LinkedIn su Drive::{len(files)} bozze nel documento «Bozze LinkedIn»")
        return True
    except Exception as e:
        print(f"::warning title=Bozze LinkedIn non copiate su Drive::{str(e)[:200]}")
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
    def new_sheet(title):
        sh = Image.new("RGB", (W, H), "white")
        dd = ImageDraw.Draw(sh)
        dd.text((70, 60), title, font=bold, fill="#15233A")
        pages.append(sh)
        return dd, 130
    d, y = new_sheet("Caption (preview, not published)")
    for para in text.split("\n"):              # testo su più pagine se serve (prima si tagliava a fine pagina)
        if para.startswith("LINKEDIN"):
            d, y = new_sheet("LinkedIn draft (copy and paste)")
            continue
        words, line = para.split(), ""
        for word in words + [None]:
            test = f"{line} {word}".strip() if word else line
            if word is None or d.textlength(test, font=font) > W - 140:
                if y > H - 70:
                    d, y = new_sheet("(continued)")
                d.text((70, y), line, font=font, fill="#222222")
                y += 40
                line = word or ""
            else:
                line = test
        if not words:
            y += 20
    pages[0].save(out_path, "PDF", save_all=True, append_images=pages[1:], resolution=150)
    return out_path
