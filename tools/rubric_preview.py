"""Anteprima di un carosello e di un reel per Funding (grant) e Positions, con la pipeline vera del bot in modalità
prova: niente viene pubblicato, i file vanno nei segnaposto Drive di PREVIEW_FILES
(JSON {"grant_pdf","grant_reel","positions_pdf","positions_reel"})."""
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ["DRY_RUN"] = "true"
os.environ["SKIP_INGEST"] = "1"
os.environ.pop("GITHUB_EVENT_NAME", None)
os.environ["COMPARE_MODE"] = "run"
os.environ.setdefault("FORCED_TASKS", "post bando,revisione slide,verifica fatti,arbitro,rifinitura")
WRITER = os.environ.get("WRITER", "")          # es. paid:anthropic/claude-sonnet-5.5: scrive e rivede i bandi

import model_compare as mc          # noqa: E402,F401  (instrada le attività forzate sul modello scelto)
import bot, drive_preview            # noqa: E402

if WRITER:
    mc.CURRENT["model"] = WRITER

PREVIEW = ROOT / "preview"
FILES = json.loads(os.environ.get("PREVIEW_FILES", "{}"))
OUT = ROOT / "compare_out"
OUT.mkdir(exist_ok=True)


def up(path, key, mime):
    import time
    fid = FILES.get(key)
    if not fid:
        return False
    for a in range(4):
        try:
            if drive_preview.upload(Path(path), None, mime, bot.CONFIG, file_id=fid):
                return True
        except Exception as e:
            print("Drive:", str(e)[:150])
        time.sleep(5 * (a + 1))
    return False


def main():
    report = []
    for kind in [k for k in (os.environ.get("KINDS") or "grant,positions").split(",") if k in ("grant", "positions")]:
        shutil.rmtree(PREVIEW, ignore_errors=True)
        PREVIEW.mkdir()
        os.environ["POST_TYPE"] = kind
        os.environ.pop("REEL_SOURCE", None)
        try:
            bot.main()
        except SystemExit as e:
            report.append(f"{kind}: saltato ({e})")
            continue
        pj = PREVIEW / "post.json"
        if not pj.exists():
            report.append(f"{kind}: nessun contenuto")
            continue
        post = json.loads(pj.read_text(encoding="utf-8"))
        slides = sorted(PREVIEW.glob("slide-*.jpg"), key=lambda p: int(p.stem.split("-")[1]))
        caption = (PREVIEW / "caption.txt").read_text(encoding="utf-8")
        pdf = OUT / f"carosello-{kind}.pdf"
        drive_preview.carousel_pdf([p.read_bytes() for p in slides], caption, pdf, "")
        report.append(f"{kind} carosello «{post['title'][:70]}» su Drive: {up(pdf, kind + '_pdf', 'application/pdf')}")
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in post["id"])
        folder = bot.IMAGES_DIR / f"{day}-{safe}"
        folder.mkdir(parents=True, exist_ok=True)
        for p in slides:
            shutil.copy(p, folder / p.name)
        entry = {"date": day, "time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "id": post["id"],
                 "title": post["title"], "source": post.get("source", ""), "kind": kind, "simulated": True}
        if kind == "grant":
            entry.update(grant_id=post.get("grant_id"), deadline=post.get("deadline_iso"))
        else:
            entry["position_ids"] = post.get("position_ids", [])
        posted = bot.load(bot.POSTED_FILE, [])
        posted.append(entry)
        bot.save(bot.POSTED_FILE, posted)
        os.environ["POST_TYPE"] = "reel"
        os.environ["REEL_SOURCE"] = kind
        try:
            bot.main()
        except SystemExit as e:
            report.append(f"{kind} reel: saltato ({e})")
            continue
        video = PREVIEW / "reel.mp4"
        if video.exists():
            shutil.copy(video, OUT / f"reel-{kind}.mp4")
            report.append(f"{kind} reel su Drive: {up(video, kind + '_reel', 'video/mp4')}")
        else:
            report.append(f"{kind} reel: non prodotto")
    print("\n===== RIEPILOGO =====\n" + "\n".join(report))


if __name__ == "__main__":
    main()
