"""Confronto dei modelli che SCRIVONO i post di Latest Science e Methodology (via OpenRouter).

Stesse fonti per tutti i modelli (3 articoli clinici per Latest Science, 3 fonti di metodologia), stessi controlli di
qualità (revisione incrociata, arbitro, verifica sulla fonte restano quelli di sempre): cambia solo il modello che
scrive il testo («nuovi post da Drive», takeaway, revisione slide, verifica fatti). Niente viene pubblicato:
ogni carosello va in un PDF su Drive, nel file segnaposto di compare_files.json (chiave «<modello>|LS|1» …).

Modalità: COMPARE_MODE=list  → stampa i modelli OpenRouter disponibili per famiglia, con prezzi (nessun costo)
          COMPARE_MODE=run   → genera (MODELS = slug separati da virgola; N = post per rubrica, default 3)."""
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("DRY_RUN", "true")
os.environ["DRY_RUN"] = "true"
os.environ["SKIP_INGEST"] = "1"

import requests  # noqa: E402

MODE = os.environ.get("COMPARE_MODE", "run")
N = int(os.environ.get("N") or 3)
MAX_TRIES = int(os.environ.get("MAX_TRIES") or N)   # fonti da provare per rubrica finché non si hanno N post
FAMILIES = ["deepseek/", "openai/gpt", "anthropic/claude", "qwen/", "moonshotai/", "z-ai/", "x-ai/", "mistralai/",
            "google/gemini", "meta-llama/", "nvidia/"]


def list_models():
    data = requests.get("https://openrouter.ai/api/v1/models", timeout=60).json()["data"]
    for fam in FAMILIES:
        rows = sorted((m for m in data if m["id"].startswith(fam)), key=lambda m: -(m.get("created") or 0))[:8]
        for m in rows:
            p = m.get("pricing") or {}
            try:
                pin, pout = float(p.get("prompt", 0)) * 1e6, float(p.get("completion", 0)) * 1e6
            except ValueError:
                pin = pout = -1
            print(f"{m['id']:60s} in ${pin:6.2f}/M  out ${pout:6.2f}/M  ctx {m.get('context_length')}")
    return 0


if MODE == "list":
    sys.exit(list_models())

import bot  # noqa: E402
import content  # noqa: E402
import drive_preview  # noqa: E402

PREVIEW = ROOT / "preview"
OUT = ROOT / "compare_out"
FILES = json.loads((ROOT / "compare_files.json").read_text(encoding="utf-8"))
MODELS = [m.strip() for m in (os.environ.get("MODELS") or "").split(",") if m.strip()]
# attività «complesse» (comprensione e lettura critica): le fa il modello in prova. FORCED_TASKS le cambia.
FORCED = {t.strip() for t in (os.environ.get("FORCED_TASKS") or
                              "nuovi post da Drive,takeaway clinico,revisione slide,verifica fatti").split(",") if t.strip()}
# attività secondarie (revisore, verifiche, anti-copia…): con SECONDARY le fanno modelli open access, in questa
# catena; vuoto = catene normali del bot
SECONDARY = os.environ.get("SECONDARY") or ""
FULL_TEXT_CHARS = 200_000          # ai modelli a pagamento (contesto ampio) l'articolo intero, non solo l'abstract
CURRENT = {"model": None}
PRE_RENDER = None      # funzione(post, material_text) chiamata prima del carosello (es. immagine di copertina)

_orig_route = content.route_for
_orig_call = content.call_model


_KNOWN_PROVIDERS = {"gemini", "groq", "openrouter", "paid"}


def _expand_model_chain(model_str):
    """Espande 'provider:model>provider2:model2' in lista di (provider, model).
    Se il prefisso non è un provider noto (es. 'nvidia/...', 'openai/...') si usa 'openrouter'."""
    chain = []
    for segment in model_str.split(">"):
        segment = segment.strip()
        if ":" in segment:
            prov, mod = segment.split(":", 1)
            if prov not in _KNOWN_PROVIDERS:
                prov, mod = "openrouter", segment   # es. 'nvidia:...' → openrouter
        else:
            prov, mod = "openrouter", segment
        chain.append((prov, mod))
    return chain or [("openrouter", model_str)]


def route(task):
    if task.split(" [", 1)[0] in FORCED and CURRENT["model"]:
        return _expand_model_chain(CURRENT["model"])
    if SECONDARY:
        return _expand_model_chain(SECONDARY)
    return _orig_route(task)


def call(provider, model, parts, schema, temperature=0.3, task="altro", thinking=None):
    if provider != "gemini" and not all("text" in p for p in parts):
        # Groq e OpenRouter non leggono PDF/immagini: converti tutto in testo estratto
        new_parts = []
        for p in parts:
            if "text" in p:
                new_parts.append(p)
            else:
                if provider == "paid":           # contesto ampio: testo completo della fonte
                    new_parts.append({"text": content.material_text(p)[:FULL_TEXT_CHARS]})
                    continue
                try:
                    import base64 as _b64
                    raw = _b64.b64decode(p["inline_data"]["data"])
                    new_parts.append({"text": content.pdf_abstract_text(raw)})
                except Exception:
                    new_parts.append({"text": content.material_text(p)})
        parts = [{"text": "\n\n".join(p["text"] for p in new_parts)}]
    return _orig_call(provider, model, parts, schema, temperature, task, thinking)


content.route_for = route
content.call_model = call


def sources():
    drive = bot.drive_service()
    inbox, done = os.environ["GDRIVE_FOLDER_ID"], os.environ["GDRIVE_DONE_FOLDER_ID"]
    allf = bot.list_inbox(drive, inbox)
    clinical = [f for f in allf if f.get("parent") != inbox and content.is_supported(f)]
    method = [f for f in allf if f.get("parent") == inbox and content.is_supported(f)]
    method += [f for f in bot.list_files(drive, done) if content.is_supported(f)]
    ok = []
    for f in clinical:
        part = content.material_part(drive, f)
        if part and content.license_status(content.material_text(part))[0] == "ok":
            ok.append(f)
        if len(ok) >= MAX_TRIES:
            break
    return drive, ok, method[:MAX_TRIES]


def pdf_of(name):
    slides = sorted(PREVIEW.glob("slide-*.jpg"), key=lambda p: int(p.stem.split("-")[1]))
    if not slides:
        return None
    caption = (PREVIEW / "caption.txt").read_text(encoding="utf-8") if (PREVIEW / "caption.txt").exists() else ""
    pdf = OUT / name
    drive_preview.carousel_pdf([p.read_bytes() for p in slides], caption, pdf, "")
    return pdf


def one(model, kind, idx, f, drive):
    key = f"{model}|{kind}|{idx}"
    fid = FILES.get(key)
    CURRENT["model"] = model
    shutil.rmtree(PREVIEW, ignore_errors=True)
    PREVIEW.mkdir()
    bot.save(bot.POSTED_FILE, [])
    bot.save(bot.QUEUE_FILE, [])
    bot.save(bot.CLINICAL_QUEUE_FILE, [])
    part = content.material_part(drive, f)
    t0 = time.time()
    brand = bot.CONFIG["brand_name"]
    if kind == "LS":
        posts, focus, why = content.clinical_posts(part, f["name"], brand, [], 1)
        if not posts:
            return f"{key}: nessun messaggio clinico ({focus}) — {why[:120]}"
        for p in posts:
            p.update({"id": f"cmp-{idx}", "source": f["name"], "rubric": "Clinical Insights"})
        bot.save(bot.CLINICAL_QUEUE_FILE, posts)
        os.environ["PREVIEW_DATE"] = "2026-11-14"       # sabato: Latest Science
    else:
        posts = content.generate_posts(part, f["name"], brand, 1, [])
        if not posts:
            return f"{key}: nessun post dalla fonte"
        for p in posts:
            p.update({"id": f"cmp-{idx}", "source": f["name"]})
        bot.save(bot.QUEUE_FILE, posts)
        os.environ["PREVIEW_DATE"] = "2026-11-17"       # martedì: metodologia
    bot.save(bot.SOURCES_FILE, [{"drive_id": f["id"], "name": f["name"], "posts": 1}])
    os.environ["POST_TYPE"] = "research"
    if PRE_RENDER:
        PRE_RENDER(posts[0], content.material_text(part))
    try:
        bot.main()
    except SystemExit as e:
        return f"{key}: il bot non ha prodotto il post ({e})"
    pj = PREVIEW / "post.json"
    if not pj.exists():
        return f"{key}: post respinto dai controlli di qualità (vedi log)"
    data = json.loads(pj.read_text(encoding="utf-8"))
    title, left = data.get("title", ""), data.get("lay_left") or []
    safe_model = model.replace('/', '_').replace(':', '-').replace('>', '_')
    pdf = pdf_of(f"{kind}{idx}-{safe_model}.pdf")
    if pdf:
        DONE.setdefault(model, []).append(pdf)
    saved = bool(fid and pdf and drive_preview.upload(pdf, None, "application/pdf", bot.CONFIG, file_id=fid))
    location = " ✓ Drive" if saved else (f" → {pdf.name}" if pdf else " — PDF non generato")
    return (f"{key}: ok in {int(time.time() - t0)} s «{title[:90]}»{location}"
            + (f" | difetti residui: {'; '.join(x[:60] for x in left)}" if left else " | nessun difetto residuo"))


DONE = {}          # modello → PDF dei post riusciti, uniti alla fine in un solo PDF (chiave «<modello>|ALL»)


def merge_and_upload(model):
    from pypdf import PdfWriter
    pdfs = DONE.get(model) or []
    if not pdfs:
        return "nessun PDF da unire"
    out = OUT / f"ALL-{model.replace('/', '_').replace(':', '-').replace('>', '_')}.pdf"
    w = PdfWriter()
    for p in pdfs:
        w.append(str(p))
    with open(out, "wb") as fh:
        w.write(fh)
    fid = FILES.get(f"{model}|ALL")
    ok = False
    for attempt in range(4):                       # connessione caduta (Broken pipe): si riprova
        try:
            ok = bool(fid and drive_preview.upload(out, None, "application/pdf", bot.CONFIG, file_id=fid))
        except Exception as e:
            print(f"  caricamento su Drive, tentativo {attempt + 1}: {str(e)[:120]}")
        if ok:
            break
        time.sleep(5 * (attempt + 1))
    return f"PDF unico ({len(pdfs)} post) " + ("✓ Drive" if ok else f"locale {out.name}")


def main():
    OUT.mkdir(exist_ok=True)
    drive, clin, meth = sources()
    print("Fonti Latest Science:", [f["name"] for f in clin])
    print("Fonti Methodology:", [f["name"] for f in meth])
    report = []
    for model in MODELS:
        print(f"\n######## {model} ########", flush=True)
        for kind, files in (("LS", clin), ("ME", meth)):
            i = 1
            for f in files:
                if i > N:
                    break
                try:
                    line = one(model, kind, i, f, drive)
                except Exception as e:
                    traceback.print_exc()
                    line = f"{model}|{kind}|{i}: errore {str(e)[:200]}"
                line += f"  [fonte: {f['name'][:70]}]"
                print(line, flush=True)
                report.append(line)
                if ": ok in " in line:
                    i += 1                         # il segnaposto successivo solo dopo un post riuscito
        report.append(f"  {merge_and_upload(model)}")
        spent = sum(float(v.get("costo_usd", 0)) for v in content.USAGE.values())
        report.append(f"  spesa a pagamento: {spent:.4f} $")
        report.append("  consumo per attività/modello: " + json.dumps(
            {k: {kk: vv for kk, vv in v.items() if kk in ("richieste", "costo_usd", "respinte")}
             for k, v in content.USAGE.items()}, ensure_ascii=False))
    print("\n===== RIEPILOGO =====\n" + "\n".join(report))
    (ROOT / "compare_report.txt").write_text("\n".join(report), encoding="utf-8")


if __name__ == "__main__":
    main()
