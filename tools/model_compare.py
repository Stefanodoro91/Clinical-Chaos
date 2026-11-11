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
FAMILIES = ["deepseek/", "openai/gpt", "anthropic/claude", "qwen/", "moonshotai/", "z-ai/", "x-ai/", "mistralai/",
            "google/gemini", "meta-llama/", "nvidia/"]


def list_models():
    data = requests.get("https://openrouter.ai/api/v1/models", timeout=60).json()["data"]
    print("== GRATUITI ==")
    for m in sorted((m for m in data if m["id"].endswith(":free")), key=lambda m: -(m.get("created") or 0)):
        print(f"FREE {m['id']:62s} ctx {m.get('context_length')}  creato {time.strftime('%Y-%m-%d', time.gmtime(m.get('created') or 0))}")
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
FORCED = {"nuovi post da Drive", "takeaway clinico", "revisione slide", "verifica fatti"}
CURRENT = {"model": None}
WRITER = {}

_orig_route = content.route_for
_orig_call = content.call_model


def route(task):
    if task.split(" [", 1)[0] in FORCED and CURRENT["model"]:
        # «a>b»: catena di ripiego; «groq:modello» o «gemini:modello» per un altro fornitore (default openrouter)
        return [tuple(x.split(":", 1)) if x.split(":", 1)[0] in ("groq", "gemini", "openrouter") else ("openrouter", x)
                for x in CURRENT["model"].split(">")]
    return _orig_route(task)


def call(provider, model, parts, schema, temperature=0.3, task="altro", thinking=None):
    if provider != "gemini" and not all("text" in p for p in parts):
        # Non-Gemini: sostituisce i PDF con titolo+abstract+reference (max 6 k char).
        # Passare il testo completo causa 413 su Groq (contesto troppo corto).
        new_parts = []
        for p in parts:
            if "text" in p:
                new_parts.append(p)
            else:
                try:
                    import base64 as _b64
                    raw = _b64.b64decode(p["inline_data"]["data"])
                    new_parts.append({"text": content.pdf_abstract_text(raw)})
                except Exception:
                    new_parts.append({"text": content.material_text(p)})
        parts = [{"text": "\n\n".join(p["text"] for p in new_parts)}]
        parts = [{"text": "\n\n".join(p["text"] for p in parts)}]
    if provider == "openrouter":       # tetto ai token in uscita: senza, OpenRouter riserva il massimo del modello e chiede credito in più
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise content.ModelUnavailable("OPENROUTER_API_KEY mancante")
        return content._openai_compatible("https://openrouter.ai/api/v1/chat/completions", key, model, "openrouter",
                                          content._parts_to_text(parts), schema, temperature, task,
                                          extra={"max_tokens": 4000,
                                                 "response_format": {"type": "json_object"}},
                                          headers={"HTTP-Referer": "https://clinicalresearchchaos.com",
                                                   "X-Title": "Clinical Research Chaos"})
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
        if len(ok) >= N + 3:
            break
    return drive, ok, method[:N + 3]


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
        WRITER[key] = content.LAST_MODEL
        if not posts:
            return f"{key}: nessun messaggio clinico ({focus}) — {why[:120]}"
        for p in posts:
            p.update({"id": f"cmp-{idx}", "source": f["name"], "rubric": "Clinical Insights"})
        bot.save(bot.CLINICAL_QUEUE_FILE, posts)
        os.environ["PREVIEW_DATE"] = "2026-11-14"       # sabato: Latest Science
    else:
        posts = content.generate_posts(part, f["name"], brand, 1, [])
        WRITER[key] = content.LAST_MODEL
        if not posts:
            return f"{key}: nessun post dalla fonte"
        for p in posts:
            p.update({"id": f"cmp-{idx}", "source": f["name"]})
        bot.save(bot.QUEUE_FILE, posts)
        os.environ["PREVIEW_DATE"] = "2026-11-17"       # martedì: metodologia
    bot.save(bot.SOURCES_FILE, [{"drive_id": f["id"], "name": f["name"], "posts": 1}])
    os.environ["POST_TYPE"] = "research"
    try:
        bot.main()
    except SystemExit as e:
        return f"{key}: il bot non ha prodotto il post ({e})"
    pj = PREVIEW / "post.json"
    if not pj.exists():
        return f"{key}: post respinto dai controlli di qualità (vedi log)"
    title = json.loads(pj.read_text(encoding="utf-8")).get("title", "")
    pdf = pdf_of(f"{kind}{idx}-{model.replace('/', '_')}.pdf")
    saved = bool(fid and pdf and drive_preview.upload(pdf, None, "application/pdf", bot.CONFIG, file_id=fid))
    return f"{key}: ok in {int(time.time() - t0)} s, scritto da {WRITER.get(key)} «{title[:80]}»" + ("" if saved else " — NON salvato su Drive")


def main():
    OUT.mkdir(exist_ok=True)
    drive, clin, meth = sources()
    print("Fonti Latest Science:", [f["name"] for f in clin])
    print("Fonti Methodology:", [f["name"] for f in meth])
    report = []
    for model in MODELS:
        print(f"\n######## {model} ########", flush=True)
        for kind, files in (("LS", clin), ("ME", meth)):
            done = 0
            for f in files:                      # fonti di riserva: si va avanti finché ci sono N post riusciti
                if done >= N:
                    break
                try:
                    line = one(model, kind, done + 1, f, drive)
                except Exception as e:
                    traceback.print_exc()
                    line = f"{model}|{kind}|{done + 1}: errore {str(e)[:200]}"
                done += ": ok in" in line
                line += f"  [fonte: {f['name']}]"
                print(line, flush=True)
                report.append(line)
        u = {k: v.get("richieste") for k, v in content.USAGE.items() if k.split("|")[0] in FORCED}
        report.append(f"  consumo {model}: {json.dumps(u, ensure_ascii=False)}")
    print("\n===== RIEPILOGO =====\n" + "\n".join(report))
    (ROOT / "compare_report.txt").write_text("\n".join(report), encoding="utf-8")


if __name__ == "__main__":
    main()
