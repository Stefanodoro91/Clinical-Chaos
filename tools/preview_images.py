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

LAY_REEL_PROMPT = """Turn this short Instagram carousel into the script of a ~20-second reel for clinical researchers.
Use ONLY the content below: no new facts, numbers, studies or claims; never mention any study other than the paper itself.
- hook: max 9 words, built on the title (a question or a crisp claim), a complete sentence.
- beats: exactly 2. Each has a title (max 5 words) and a line (max 16 words): complete, precise sentences that name
  their subject (no "this", "it") and keep the carousel's qualifiers. Beat 1: the question or problem the paper addresses
  and what the paper is. Beat 2: what the paper found or argues, without overstating it.
- takeaway: the message, max 16 words, specific and faithful to the carousel's takeaway; not a repetition of the beats.
Never end any text with "..." or an unfinished phrase. No hashtags, no emojis.

Title: {title}
Carousel page 2: {heading}. {body}
Takeaway: {takeaway}"""
LAY_REEL_SCHEMA = {"type": "OBJECT", "properties": {
    "hook": {"type": "STRING"}, "takeaway": {"type": "STRING"},
    "beats": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "title": {"type": "STRING"}, "line": {"type": "STRING"}}, "required": ["title", "line"]}}},
    "required": ["hook", "beats", "takeaway"]}


def make_pre_render(kind):
    def pre(post, text):
        brief = ic.METHOD_BRIEF if kind == "ME" else ic.BRIEF
        prompt, _ = ic.chat(brief + text[:14000])
        best = None
        for attempt in range(3):
            data, ratio, cost = ic.image(ic.MODELS[0], prompt)
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
        images.COVER_CACHE[post["id"]] = Image.open(io.BytesIO(data)).convert("RGB")
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
    cfg = bot.CONFIG
    page2 = (post.get("slides") or [{}])[0]
    script = content.gemini_json([{"text": LAY_REEL_PROMPT.format(
        title=post["title"], heading=page2.get("heading", ""), body=page2.get("body", ""),
        takeaway=post.get("takeaway", ""))}], LAY_REEL_SCHEMA, 0.3, task="copione reel")
    print("Copione reel:", json.dumps(script, ensure_ascii=False))
    entry = {"kind": None, "category": post.get("category"), "rubric": "Clinical Insights" if kind == "LS" else None}
    kicker, accent = reels.rubric_tag(entry, cfg, "LATEST SCIENCE" if kind == "LS" else "METHODOLOGY", cfg["colors"]["accent"])
    beats = script["beats"][:2]
    slides = [{"type": "cover", "kicker": kicker, "title": script["hook"], "cover_image": str(COVER[kind][0])}]
    slides += [{"type": "point", "number": f"{i:02d}", "title": b["title"], "body": b["line"]} for i, b in enumerate(beats, 1)]
    slides.append({"type": "point", "number": "→", "title": "Remember", "body": script["takeaway"]})
    slides.append({"type": "closing", "title": "Full carousel with references on our profile", "body": "Save it for later"})
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
