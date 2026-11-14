"""Anteprima di un carosello e di un reel (Latest Science e Methodology): testo e logiche scritti da Claude Sonnet 5.5,
immagine di copertina generata da ChatGPT (GPT Image 2) dal paper. Niente viene pubblicato: i file vanno su Drive,
nei segnaposto indicati (PREVIEW_FILES = JSON {"LS_pdf","ME_pdf","LS_reel","ME_reel"})."""
import io
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ["COMPARE_MODE"] = "run"
os.environ["LAY_STORY"] = "1"
os.environ.setdefault("FORCED_TASKS", "nuovi post da Drive,takeaway clinico,revisione slide,verifica fatti,arbitro,rifinitura,copione reel")

import model_compare as mc          # noqa: E402
import image_compare as ic          # noqa: E402
import bot, content, cards, images, reels, drive_preview   # noqa: E402
from PIL import Image               # noqa: E402

MODEL = os.environ.get("WRITER", "paid:anthropic/claude-sonnet-5.5")
TARGETS = {"LS": os.environ.get("LS_SOURCE", "Smart exoskeleton"), "ME": os.environ.get("ME_SOURCE", "Blinding")}
FILES = json.loads(os.environ.get("PREVIEW_FILES", "{}"))
OUT = ROOT / "compare_out"
OUT.mkdir(exist_ok=True)
COVER = {}                     # kind → (percorso PNG, prompt, verdetto)

STORY_REEL_PROMPT = """Turn this educational carousel into the on-screen script of a 35-second reel for clinical researchers.
Use ONLY the content below: no new facts, numbers, studies or claims; never mention any study other than the paper itself.
The reel has no voice-over: every text is read on screen, so each must be a complete, plain sentence.
- hook: max 12 words, built on the carousel title (a question or a crisp claim that makes people stop).
- highlight: 2-5 words copied EXACTLY from the hook (they will be marked in yellow).
- scene: max 18 words: what the paper is and what its authors set out to do.
- method: title (max 5 words) + line (max 24 words): how the work was done and how solid it is (type of work, who or
  what, how many only if the carousel says, comparison group), with the main limit of the design.
- data: title (max 5 words) + line (max 24 words): the real finding versus the headline, or the limit the authors declare.
- takeaway: max 22 words: what it means in practice; specific; not a repetition of the other texts.
Keep every qualifier of the carousel. Never use "..." or leave a sentence unfinished. Tone: an expert colleague, never
aggressive ("a useful first step, but..."). No hashtags, no emojis.

Title: {title}
Page 2 (context): {h1}. {b1}
Page 3 (lens): {h2}. {b2}
Page 4 (data): {h3}. {b3}
Page 5 (meaning): {takeaway}"""
STORY_REEL_SCHEMA = {"type": "OBJECT", "properties": {
    "hook": {"type": "STRING"}, "highlight": {"type": "STRING"}, "scene": {"type": "STRING"},
    "method": {"type": "OBJECT", "properties": {"title": {"type": "STRING"}, "line": {"type": "STRING"}},
               "required": ["title", "line"]},
    "data": {"type": "OBJECT", "properties": {"title": {"type": "STRING"}, "line": {"type": "STRING"}},
             "required": ["title", "line"]},
    "takeaway": {"type": "STRING"}}, "required": ["hook", "highlight", "scene", "method", "data", "takeaway"]}


def make_pre_render(kind):
    def pre(post, text):
        brief = (ic.METHOD_BRIEF if kind == "ME" else ic.BRIEF).replace(
            "portrait 4:5; the lower third calm and dark for a title overlay", "wide landscape 16:9; subject centred, calm dark margins")
        prompt, _ = ic.chat(brief + text[:14000])
        best = None
        for attempt in range(3):
            data, ratio, cost = ic.image(ic.MODELS[0], prompt, ("16:9", "3:2", "4:3", "1:1"))
            try:
                verdict = ic.check(data, text)
            except Exception as e:
                verdict = f"controllo non riuscito: {str(e)[:120]}"
            best = (data, prompt, verdict, ratio, cost)
            print(f"{kind} immagine [{attempt + 1}] {ratio} {cost} $\n{verdict}", flush=True)
            if "VERDICT: OK" in verdict or "VERDICT" not in verdict:
                break
            prompt, _ = ic.chat(brief + text[:14000] + "\n\nPREVIOUS PROMPT:\n" + prompt + "\nA reviewer rejected the image: "
                                + verdict + "\nWrite an improved prompt that fixes this.")
        data, prompt, verdict, ratio, cost = best
        path = OUT / f"cover-{kind}.png"
        path.write_bytes(data)
        images.SLIDE_CACHE[post["id"]] = Image.open(io.BytesIO(data)).convert("RGB")
        COVER[kind] = (path, prompt, verdict)
    return pre


def upload(path, key, mime):
    fid = FILES.get(key)
    if not fid:
        print(f"nessun segnaposto per {key}")
        return False
    import time
    for a in range(4):
        try:
            if drive_preview.upload(Path(path), None, mime, bot.CONFIG, file_id=fid):
                return True
        except Exception as e:
            print("Drive:", str(e)[:150])
        time.sleep(5 * (a + 1))
    return False


def reel(kind, post):
    import re
    import sources
    cfg = bot.CONFIG
    sl = post["slides"]
    script = content.gemini_json([{"text": STORY_REEL_PROMPT.format(
        title=post["title"], h1=sl[0]["heading"], b1=sl[0]["body"], h2=sl[1]["heading"], b2=sl[1]["body"],
        h3=sl[2]["heading"], b3=sl[2]["body"], takeaway=post.get("takeaway", ""))}], STORY_REEL_SCHEMA, 0.3,
        task="copione reel")
    print("Copione reel:", json.dumps(script, ensure_ascii=False))
    entry = {"kind": None, "category": post.get("category"), "rubric": "Clinical Insights" if kind == "LS" else None}
    kicker, accent = reels.rubric_tag(entry, cfg, "LATEST SCIENCE" if kind == "LS" else "METHODOLOGY", cfg["colors"]["accent"])
    ref = sources.lay_reference(post) or {}
    doi = re.search(r"10\.\d{4,9}/\S+", " ".join(post.get("references") or []))
    source_line = ("Source: " + (ref.get("title") or "") + (f" · doi.org/{doi.group(0).rstrip('.')}" if doi else "")).strip()
    hook = " ".join(script["hook"].split())
    slides = [
        {"type": "cover", "kicker": kicker, "title": hook, "highlight": content.exact_phrase(script.get("highlight"), hook, 5),
         "mark": "#FFD84D", "source_line": source_line},
        {"type": "scene", "kicker": "THE PAPER", "title": script["scene"], "cover_image": str(COVER[kind][0])},
        {"type": "point", "number": "01", "title": script["method"]["title"], "body": script["method"]["line"]},
        {"type": "point", "number": "02", "title": script["data"]["title"], "body": script["data"]["line"]},
        {"type": "point", "number": "→", "title": "What it means", "body": script["takeaway"]},
        {"type": "closing", "title": "Funding and positions in rigorous labs", "body": "Link in bio"},
    ]
    spec = {"accent": accent, "mood": "Classica", "slides": slides}
    rcfg = {**cfg, "colors": {**cfg["colors"], "accent": accent}}
    video = OUT / f"reel-{kind}.mp4"
    seconds = reels.build_story_reel(spec, video, rcfg, mood=bot.REEL_KINDS["research"]["music"])
    return video, seconds, spec


def main():
    mc.MODELS = [MODEL]
    report = []
    drive = bot.drive_service()
    inbox = os.environ["GDRIVE_FOLDER_ID"]
    allf = bot.list_inbox(drive, inbox)
    for kind in ("LS", "ME"):
        if kind == "LS":
            pool = [f for f in allf if f.get("parent") != inbox and content.is_supported(f)]
        else:
            pool = [f for f in allf if f.get("parent") == inbox and content.is_supported(f)]
            pool += [f for f in bot.list_files(drive, os.environ["GDRIVE_DONE_FOLDER_ID"]) if content.is_supported(f)]
        f = next((x for x in pool if TARGETS[kind].lower() in x["name"].lower()), None)
        if not f:
            report.append(f"{kind}: fonte «{TARGETS[kind]}» non trovata")
            continue
        mc.PRE_RENDER = make_pre_render(kind)
        line = mc.one(MODEL, kind, 1, f, drive)
        report.append(line)
        print(line, flush=True)
        pj = mc.PREVIEW / "post.json"
        if not pj.exists():
            continue
        post = json.loads(pj.read_text(encoding="utf-8"))
        safe = MODEL.replace("/", "_").replace(":", "-")
        pdf = OUT / f"{kind}1-{safe}.pdf"
        if pdf.exists():
            shutil.copy(pdf, OUT / f"carosello-{kind}.pdf")
            report.append(f"{kind} carosello su Drive: {upload(OUT / f'carosello-{kind}.pdf', kind + '_pdf', 'application/pdf')}")
        try:
            video, seconds, spec = reel(kind, post)
            report.append(f"{kind} reel {seconds} s su Drive: {upload(video, kind + '_reel', 'video/mp4')}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            report.append(f"{kind} reel: errore {str(e)[:200]}")
        report.append(f"{kind} immagine: {COVER.get(kind, ('', '', ''))[2][:300]}")
    print("\n===== RIEPILOGO =====\n" + "\n".join(report))
    print("spesa:", json.dumps({k: v.get("costo_usd", 0) for k, v in content.USAGE.items() if v.get("costo_usd")}))


if __name__ == "__main__":
    main()
