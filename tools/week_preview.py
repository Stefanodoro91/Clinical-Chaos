"""Anteprima di una settimana intera di pubblicazioni, come se il bot andasse (social in pausa): per ogni uscita del
calendario (week_preview.json) prepara storia, carosello o reel in modalità prova, alla data simulata, e lo salva
nel file Drive corrispondente (cartella Anteprime/Settimana …). Le uscite dei giorni prima contano come pubblicate
(solo in memoria del run: niente commit), così i giorni dopo non si ripetono e i reel nascono dai caroselli della
settimana. Uso: python tools/week_preview.py (in GitHub Actions, con i secret)."""

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["DRY_RUN"] = "true"
os.environ["SKIP_INGEST"] = "1"                 # i PDF nuovi li legge il bot nei giri normali
os.environ.pop("GITHUB_EVENT_NAME", None)       # niente salti «già uscito oggi» dei run pianificati

import bot                                      # noqa: E402
import drive_preview                            # noqa: E402
import stories                                  # noqa: E402

PREVIEW = ROOT / "preview"
cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def iso(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime.fromisoformat(day).replace(hour=h, minute=m, tzinfo=ZoneInfo("Europe/Rome")).astimezone(
        ZoneInfo("UTC")).isoformat(timespec="seconds")


def clean():
    shutil.rmtree(PREVIEW, ignore_errors=True)
    PREVIEW.mkdir()


def add_posted(entry):
    posted = bot.load(bot.POSTED_FILE, [])
    posted.append(entry)
    bot.save(bot.POSTED_FILE, posted)


def main():
    plan = json.loads((ROOT / "week_preview.json").read_text(encoding="utf-8"))
    only = {s.strip() for s in (os.environ.get("ONLY") or "").split(",") if s.strip()}
    report = []
    for i, slot in enumerate(plan["slots"], 1):
        if only and str(i) not in only:
            continue
        day, kind = slot["date"], slot["kind"]
        os.environ["PREVIEW_DATE"] = day
        print(f"\n===== {slot['name']} =====", flush=True)
        clean()
        try:
            if kind == "story":
                os.environ["STORY_KIND"] = slot.get("story_kind") or "auto"
                res = stories.main()
                if not res:
                    report.append(f"{slot['name']}: nessuna storia (dati insufficienti)")
                    continue
                out, skind, data = res
                drive_preview.upload(out, None, "video/mp4", cfg, file_id=slot["file_id"])
                log = stories.load_log()
                e = {"date": day, "time": iso(day, slot["time"]), "kind": skind, "simulated": True}
                for k in ("grant_id", "family"):
                    if data.get(k):
                        e[k] = data[k]
                log.append(e)
                stories.LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
                report.append(f"{slot['name']}: ok ({skind})")
            elif kind == "reel":
                os.environ["POST_TYPE"] = "reel"
                os.environ["REEL_SOURCE"] = "latest"
                bot.main()
                video, meta = PREVIEW / "reel.mp4", PREVIEW / "reel.json"
                if not video.exists():
                    report.append(f"{slot['name']}: nessun carosello da trasformare in reel")
                    continue
                m = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
                drive_preview.upload(video, None, "video/mp4", cfg, file_id=slot["file_id"])
                add_posted({"date": day, "time": iso(day, slot["time"]), "id": f"reel-{m.get('reel_of', i)}",
                            "title": m.get("title", ""), "kind": "reel", "reel_of": m.get("reel_of"), "simulated": True})
                report.append(f"{slot['name']}: ok (da «{m.get('title', '')[:60]}», musica {m.get('music', '')})")
            else:
                os.environ["POST_TYPE"] = kind
                bot.main()
                pj = PREVIEW / "post.json"
                if not pj.exists():
                    report.append(f"{slot['name']}: nessun contenuto per questo giorno")
                    continue
                post = json.loads(pj.read_text(encoding="utf-8"))
                slides = sorted(PREVIEW.glob("slide-*.jpg"), key=lambda p: int(p.stem.split("-")[1]))
                caption = (PREVIEW / "caption.txt").read_text(encoding="utf-8")
                pdf = PREVIEW / "carousel.pdf"
                drive_preview.carousel_pdf([p.read_bytes() for p in slides], caption, pdf)
                drive_preview.upload(pdf, None, "application/pdf", cfg, file_id=slot["file_id"])
                safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in post["id"])
                folder = bot.IMAGES_DIR / f"{day}-{safe}"   # per i reel dei giorni dopo (solo nel run, niente commit)
                folder.mkdir(parents=True, exist_ok=True)
                for p in slides:
                    shutil.copy(p, folder / p.name)
                entry = {"date": day, "time": iso(day, slot["time"]), "id": post["id"], "title": post["title"],
                         "source": post.get("source", ""), "simulated": True}
                if kind in ("grant", "positions"):
                    entry["kind"] = kind
                if kind == "grant":
                    entry.update(grant_id=post.get("grant_id"), deadline=post.get("deadline_iso"))
                if kind == "positions":
                    entry["position_ids"] = post.get("position_ids", [])
                if kind == "research":
                    entry.update(points=post.get("slides", []), takeaway=post.get("takeaway", ""),
                                 category=post.get("category", ""))
                    queue = [q for q in bot.load(bot.QUEUE_FILE, []) if q.get("id") != post["id"]]
                    bot.save(bot.QUEUE_FILE, queue)
                add_posted(entry)
                report.append(f"{slot['name']}: ok («{post['title'][:70]}»)")
        except SystemExit as e:
            report.append(f"{slot['name']}: saltato ({e})")
        except Exception as e:
            report.append(f"{slot['name']}: errore {str(e)[:200]}")
            print(f"::warning title=Settimana di prova::{slot['name']}: {str(e)[:300]}")
    print("\n===== RIEPILOGO =====\n" + "\n".join(report))
    (ROOT / "week_report.txt").write_text("\n".join(report), encoding="utf-8")


if __name__ == "__main__":
    main()
