"""Prova del piano immagini (visuals.plan) su alcuni post della coda e su un post clinico con le figure di un articolo
CC BY. Usa solo modelli leggeri; niente pubblicazione. Scrive le slide in probe_fig/ e il piano in probe.md."""
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bot        # noqa: E402
import cards      # noqa: E402
import polish     # noqa: E402
import sources    # noqa: E402
import visuals    # noqa: E402
from PIL import Image  # noqa: E402

out = Path("probe_fig")
out.mkdir(exist_ok=True)
cfg = dict(bot.CONFIG, source_slide=False, pixabay_photos=True)
lines = ["# Piano immagini", ""]
posts = [p for p in json.loads(Path("queue.json").read_text()) if p["id"] in
         ("40cb2ae7", "035742c6", "af630a09", "144c4de0", "09267e83")]
drive = bot.drive_service()
inbox = os.environ["GDRIVE_FOLDER_ID"]
pdf = next((f for f in bot.list_inbox(drive, inbox) if f["name"] == "Wearable exoskeleton.pdf"), None)
figures, credit = [], ""
if pdf:
    data = drive.files().get_media(fileId=pdf["id"], supportsAllDrives=True).execute()
    figures = visuals.paper_figures(data)
    credit = "Wearable exoskeleton review · CC BY 4.0"
clinical = {"id": "probe-clin", "title": "Exoskeleton gait training after stroke: what improves", "category": "Latest Science",
            "slides": [{"heading": "Which trials were pooled", "body": "Randomised trials of wearable exoskeleton gait training in stroke were screened and selected with PRISMA 2020.", "source": ""},
                       {"heading": "How trustworthy the trials were", "body": "Risk of bias was judged with Cochrane RoB 1 across the included randomised trials.", "source": ""},
                       {"heading": "Balance: small-study effects?", "body": "For the Berg Balance Scale, the funnel plot with Egger's test did not suggest small-study effects.", "source": ""},
                       {"heading": "What it means in the clinic", "body": "Exoskeleton gait training can be offered as an add-on to conventional rehabilitation, not a replacement.", "source": ""}],
            "takeaway": "Offer exoskeleton gait training as an add-on, not a replacement.", "takeaway_highlight": "an add-on",
            "caption": "x?", "hashtags": [], "references": []}
for post in posts + [clinical]:
    post = json.loads(json.dumps(post))
    polish.polish_post(post)
    visuals.plan(post, figures if post["id"] == "probe-clin" else [], credit)
    lines.append(f"## {post['title']}")
    for i, s in enumerate(post["slides"], 1):
        v = s.get("visual") or {}
        lines.append(f"- {i}. {s['heading']} → {v.get('type')} {v.get('kind') or v.get('figure') or s.get('photo_query', '') if v.get('type') == 'photo' else v.get('kind') or v.get('figure') or ''}")
    pages = cards.render_carousel(post, cfg)
    ims = [Image.open(io.BytesIO(b)).resize((432, 540)) for b in pages[1:1 + len(post["slides"])]]
    sheet = Image.new("RGB", (432 * len(ims), 540))
    for k, im in enumerate(ims):
        sheet.paste(im, (432 * k, 0))
    sheet.save(out / f"{post['id']}.jpg", quality=82)
    lines.append("")
Path("probe.md").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
