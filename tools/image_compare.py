"""Confronto di modelli di immagini (Gemini e ChatGPT via OpenRouter) a partire da un articolo su Drive.
Non pubblica niente: un PDF con il prompt e le due immagini va nel file segnaposto su Drive."""
import base64, io, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bot, content, drive_preview                      # noqa: E402
import requests                                          # noqa: E402
from PIL import Image, ImageDraw                         # noqa: E402

KEY = os.environ.get("OPENROUTER_API_KEY", "")
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
MODELS = [m for m in os.environ.get("IMAGE_MODELS", "openai/gpt-image-2").split(",") if m]
WRITER = os.environ.get("PROMPT_MODEL", "anthropic/claude-sonnet-5.5")
SOURCE = os.environ.get("SOURCE", "Smart exoskeleton")
SKIP = [x.strip().lower() for x in os.environ.get("SKIP", "").split("|") if x.strip()]
COUNT = int(os.environ.get("COUNT", "1"))
KIND = os.environ.get("KIND", "LS")
PDF_ID = os.environ.get("PDF_ID", "")
OUT = ROOT / "compare_out"
OUT.mkdir(exist_ok=True)

BRIEF = """Read the article below and write ONE prompt for an image generator. The image is the cover of an Instagram
carousel about this paper, for a clinical-research account.
First identify, from the article, its exact subject: the specific intervention, device, test or condition, the
population and the setting. The image MUST depict THAT subject, specific and unmistakable to a clinician, and nothing
generic or merely related. Do not invent features the paper does not describe.
The image MUST show the paper's actual subject, recognisable at a glance (for example the specific device or
intervention the paper is about, in a realistic clinical or rehabilitation setting). A patient and/or therapists may
appear, but never show a face: shoot from behind, from the side, cropped at the neck, or with the head out of frame.
Style: realistic editorial photograph, natural but moody lighting, deep black or very dark background with one
accent colour; portrait 4:5; the lower third calm and dark for a title overlay.
Forbidden: any text, letters, numbers, logos or watermarks; diagrams, charts, infographics or schematic anatomy;
visible faces; invented medical claims or results; devices that look implausible (wrong number of limbs, impossible joints).
Answer with the prompt only (max 100 words), in English.

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
    for ratio in ("4:5", "3:4", "2:3", "1:1"):
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


CHECK = """You are checking an AI-generated image meant as the cover of a carousel about the paper summarised below.
Answer in this exact format, nothing else:
SUBJECT: yes/no (does it show the paper's specific subject, recognisable to a clinician?)
FACES: none/visible (any recognisable or partly visible face?)
TEXT: none/present (any letters, numbers, logos?)
FLAWS: one line on anatomical or device implausibilities, or "none"
VERDICT: OK or REDO
REASON: one sentence; if REDO, say what the prompt should change.

PAPER (excerpt):
"""


def check(png, text):
    uri = "data:image/png;base64," + base64.b64encode(png).decode()
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=H, timeout=300,
                      json={"model": WRITER, "max_tokens": 300, "messages": [{"role": "user", "content": [
                          {"type": "text", "text": CHECK + text[:5000]},
                          {"type": "image_url", "image_url": {"url": uri}}]}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


METHOD_BRIEF = """Read the methods paper below and write ONE prompt for an image generator. The image is the cover of an Instagram
carousel about this paper, for a clinical-research methodology account.
Step 1: identify the paper's single main methodological concept (for example blinding, allocation concealment, sample
size, a reporting guideline, a bias) in one phrase.
Step 2: depict THAT concept with ONE concrete, realistic, photographable scene or object that a trial methodologist would
recognise as exactly that concept (for example: identical coded treatment vials and sealed opaque envelopes for
allocation concealment; a lab bench with indistinguishable pill containers for blinding). Not a generic clinic, not a
generic laptop or stethoscope. Do not invent content the paper does not cover.
Style: realistic editorial photograph, natural but moody lighting, deep black or very dark background with one accent
colour; portrait 4:5; the lower third calm and dark for a title overlay.
Forbidden: any text, letters, numbers, logos or watermarks (including on labels, envelopes and screens: keep them blank);
diagrams, charts, infographics, flowcharts; visible faces; implausible objects.
Answer with the prompt only (max 100 words), in English.

ARTICLE:
"""


def one(drive, f):
    text = content.material_text(content.material_part(drive, f))[:14000]
    BRIEF_ = METHOD_BRIEF if KIND == "ME" else BRIEF
    prompt, _ = chat(BRIEF_ + text)
    out = []
    for attempt in range(2):
        data, ratio, cost = image(MODELS[0], prompt)
        try:
            verdict = check(data, text)
        except Exception as e:
            verdict = f"controllo non riuscito: {str(e)[:150]}"
        print(f"{f['name']} [{attempt + 1}]: {ratio} {cost} $\n{verdict}", flush=True)
        out.append((prompt, data, ratio, cost, verdict))
        if "VERDICT: OK" in verdict or "VERDICT" not in verdict:
            break
        prompt, _ = chat(BRIEF_ + text + "\n\nPREVIOUS PROMPT:\n" + prompt + "\nA reviewer rejected the image: " + verdict
                         + "\nWrite an improved prompt that fixes this.")
    return out


def main():
    drive = bot.drive_service()
    inbox = os.environ["GDRIVE_FOLDER_ID"]
    allf = bot.list_inbox(drive, inbox)
    if KIND == "ME":
        files = [f for f in allf if f.get("parent") == inbox and content.is_supported(f)]
        files += [f for f in bot.list_files(drive, os.environ["GDRIVE_DONE_FOLDER_ID"]) if content.is_supported(f)]
    else:
        files = [f for f in allf if f.get("parent") != inbox and content.is_supported(f)]
    if COUNT == 1:
        chosen = [next((x for x in files if SOURCE.lower() in x["name"].lower()), files[0])]
    else:
        chosen = [x for x in files if not any(k in x["name"].lower() for k in SKIP)][:COUNT]
    pages = []
    for f in chosen:
        try:
            for i, (prompt, data, ratio, cost, verdict) in enumerate(one(drive, f), 1):
                (OUT / f"{f['name'][:30].replace(' ', '_')}-{i}.png").write_bytes(data)
                pages.append(page(f"{f['name']}  (prova {i})  {MODELS[0]}  {ratio}  {cost} $",
                                  wrap(prompt) + [""] + [l for v in verdict.splitlines() for l in wrap(v)], data))
        except Exception as e:
            print(f"{f['name']}: ERRORE {str(e)[:300]}", flush=True)
            pages.append(page(f"{f['name']}: errore", wrap(str(e))))
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


if __name__ == "__main__":
    main()
