"""Confronto di modelli di immagini (Gemini e ChatGPT via OpenRouter) a partire da un articolo su Drive.
Non pubblica niente: un PDF con il prompt e le due immagini va nel file segnaposto su Drive."""
import base64, io, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bot, content, drive_preview                      # noqa: E402
import requests                                          # noqa: E402
from PIL import Image, ImageDraw                         # noqa: E402

KEY = os.environ["OPENROUTER_API_KEY"]
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
MODELS = [m for m in os.environ.get("IMAGE_MODELS", "google/gemini-3.1-flash-image,openai/gpt-image-2").split(",") if m]
WRITER = os.environ.get("PROMPT_MODEL", "anthropic/claude-sonnet-5.5")
SOURCE = os.environ.get("SOURCE", "Smart exoskeleton")
PDF_ID = os.environ["PDF_ID"]
OUT = ROOT / "compare_out"
OUT.mkdir(exist_ok=True)

BRIEF = """Read the article below and write ONE prompt for an image generator. The image is the cover of an Instagram
carousel about this paper, for a clinical-research account.
Rules for the image: portrait 4:5; deep black background (#0A0A0A) with one accent colour; editorial, photographic or
abstract, one clear subject that suggests the paper's topic; NO text, letters, numbers, logos or watermarks; NO diagrams,
charts, infographics or schematic anatomy; NO recognisable faces; nothing that states a result or implies a clinical claim;
leave the lower third calm and dark for a title overlay.
Answer with the prompt only (max 90 words), in English.

ARTICLE:
"""


def chat(prompt):
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=H, timeout=300,
                      json={"model": WRITER, "messages": [{"role": "user", "content": prompt}], "max_tokens": 400})
    r.raise_for_status()
    j = r.json()
    return j["choices"][0]["message"]["content"].strip(), (j.get("usage") or {}).get("cost", 0) or 0


def image(model, prompt):
    last = None
    for ratio in ("4:5", "1:1"):
        for attempt in range(2):
            try:
                r = requests.post("https://openrouter.ai/api/v1/images", headers=H, timeout=600,
                                  json={"model": model, "prompt": prompt, "aspect_ratio": ratio})
                if r.status_code >= 400:
                    last = f"{r.status_code} {r.text[:300]}"
                    break
                j = r.json()
                d = j["data"][0]
                return base64.b64decode(d["b64_json"]), ratio, (j.get("usage") or {}).get("cost")
            except Exception as e:
                last = str(e)[:300]
                time.sleep(5)
    raise RuntimeError(last)


def page(title, lines, img=None):
    pg = Image.new("RGB", (1080, 1500), "#0A0A0A")
    d = ImageDraw.Draw(pg)
    d.text((50, 40), title, fill="#FFFFFF")
    y = 90
    for ln in lines:
        d.text((50, y), ln, fill="#BBBBBB")
        y += 22
    if img:
        im = Image.open(io.BytesIO(img)).convert("RGB")
        im.thumbnail((980, 1300))
        pg.paste(im, ((1080 - im.width) // 2, 170))
    return pg


def wrap(t, n=110):
    out, cur = [], ""
    for w in t.split():
        if len(cur) + len(w) > n:
            out.append(cur)
            cur = ""
        cur += w + " "
    return out + [cur]


def main():
    drive = bot.drive_service()
    inbox, done = os.environ["GDRIVE_FOLDER_ID"], os.environ["GDRIVE_DONE_FOLDER_ID"]
    files = [f for f in bot.list_inbox(drive, inbox) if f.get("parent") != inbox and content.is_supported(f)]
    f = next((x for x in files if SOURCE.lower() in x["name"].lower()), files[0])
    text = content.material_text(content.material_part(drive, f))[:14000]
    prompt, c0 = chat(BRIEF + text)
    print("FONTE:", f["name"], "\nPROMPT:", prompt, flush=True)
    pages = [page(f"Fonte: {f['name']}", ["Prompt scritto da " + WRITER + " (" + f"{c0:.3f} $)", ""] + wrap(prompt))]
    for m in MODELS:
        try:
            data, ratio, cost = image(m, prompt)
            (OUT / (m.replace("/", "_") + ".png")).write_bytes(data)
            pages.append(page(f"{m}   formato {ratio}   costo {cost} $", [], data))
            print(f"{m}: ok, {ratio}, {cost} $", flush=True)
        except Exception as e:
            pages.append(page(f"{m}: errore", wrap(str(e))))
            print(f"{m}: ERRORE {str(e)[:300]}", flush=True)
    pdf = OUT / "confronto-immagini.pdf"
    pages[0].save(pdf, save_all=True, append_images=pages[1:])
    ok = False
    for a in range(4):
        try:
            ok = bool(drive_preview.upload(pdf, None, "application/pdf", bot.CONFIG, file_id=PDF_ID))
        except Exception as e:
            print("Drive:", str(e)[:150])
        if ok:
            break
        time.sleep(5 * (a + 1))
    print("PDF su Drive" if ok else "PDF solo locale")


main()
