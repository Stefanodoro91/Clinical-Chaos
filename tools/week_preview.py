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


KEEP = ROOT / "preview_week"           # copia di ogni uscita: artifact del run, anche se Drive non riceve il file


def keep(path, name):
    KEEP.mkdir(exist_ok=True)
    shutil.copy(path, KEEP / name.replace("/", "-"))


def add_posted(entry):
    posted = bot.load(bot.POSTED_FILE, [])
    posted.append(entry)
    bot.save(bot.POSTED_FILE, posted)


HISTORY = ROOT / "preview_history.json"       # anteprime delle settimane già fatte (piano a più settimane): si somma tra i giri


def load_history():
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"weeks_done": [], "posted": [], "stories": [], "grants": {}, "positions": {}}


def pick_plan(hist):
    """Settimana da preparare: WEEK (1, 2, 3…) se indicata, altrimenti la prima di preview_weeks.json non ancora fatta.
    Senza preview_weeks.json resta il vecchio week_preview.json (una settimana)."""
    multi = ROOT / "preview_weeks.json"
    if not multi.exists():
        return None, json.loads((ROOT / "week_preview.json").read_text(encoding="utf-8"))
    weeks = json.loads(multi.read_text(encoding="utf-8"))["weeks"]
    want = os.environ.get("WEEK", "").strip() or (os.environ.get("ONLY", "").split(":")[0].strip()
                                                    if ":" in os.environ.get("ONLY", "") else "")
    idx = int(want) - 1 if want else next((i for i in range(len(weeks)) if i not in hist["weeks_done"]), None)
    if idx is None:
        raise SystemExit("Tutte le settimane del piano sono già pronte (preview_history.json)")
    return idx, weeks[idx]


def apply_history(hist):
    """Le uscite simulate delle settimane già preparate contano come pubblicate (niente bandi, posizioni o post
    ripetuti) e i bandi/posizioni già confermati dai forti non si riconfermano."""
    if hist["posted"]:
        posted = bot.load(bot.POSTED_FILE, [])
        seen = {(p.get("id"), p.get("date")) for p in posted}
        posted += [p for p in hist["posted"] if (p.get("id"), p.get("date")) not in seen]
        bot.save(bot.POSTED_FILE, posted)
        done = {p.get("id") for p in hist["posted"] if not p.get("kind")}
        queue = [q for q in bot.load(bot.QUEUE_FILE, []) if q.get("id") not in done]
        bot.save(bot.QUEUE_FILE, queue)
    if hist["stories"]:
        log = stories.load_log() + hist["stories"]
        stories.LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    if "clinical_queue" in hist:                     # post Latest Science già scritti e articoli clinici già letti
        bot.save(bot.CLINICAL_QUEUE_FILE, hist["clinical_queue"])
    if hist.get("clinical_sources"):
        src = bot.load(bot.SOURCES_FILE, [])
        have = {x.get("drive_id") for x in src}
        bot.save(bot.SOURCES_FILE, src + [x for x in hist["clinical_sources"] if x.get("drive_id") not in have])
    import grants, positions
    verified = grants.load_verified()
    for gid, v in hist.get("grants", {}).items():
        if not grants.confirmed(verified.get(gid)):
            verified[gid] = v
    bot.save(ROOT / grants.VERIFIED_FILE, verified)
    archive = positions.load_archive()
    for k, v in hist.get("positions", {}).items():
        if k in archive and not (archive[k].get("confirmed") or {}).get("model"):
            archive[k] = v
    bot.save(ROOT / positions.ARCHIVE_FILE, archive)


def screening():
    """Screening prima delle anteprime: bandi nuovi sui modelli leggeri, poi il secondo parere dei forti sui bandi e
    sulle posizioni ad alta priorità. La raccolta delle posizioni dai portali la fa già ogni mattina il giro di main."""
    import grants, positions
    posted = bot.load(bot.POSTED_FILE, [])
    grants_list, verified = grants.fetch(cfg), grants.load_verified()
    n = grants.refresh_verified(grants_list, verified, cfg)
    c = grants.confirm_candidates(grants_list, verified, posted, cfg)
    bot.save(ROOT / grants.VERIFIED_FILE, verified)
    archive = positions.load_archive()
    p = positions.confirm_candidates(archive, posted, cfg)
    bot.save(ROOT / positions.ARCHIVE_FILE, archive)
    print(f"::notice title=Screening::{n} bandi verificati (leggeri), {c} bandi e {p} posizioni confermati (forti)")
    return f"Screening: {n} bandi nuovi verificati sui modelli leggeri; secondo parere dei forti su {c} bandi e {p} posizioni"


def save_history(hist, idx, added_posted, added_stories):
    import grants, positions
    if idx is not None:
        hist["weeks_done"] = sorted(set(hist["weeks_done"]) | {idx})
    hist["posted"] += added_posted
    hist["stories"] += added_stories
    hist["clinical_queue"] = bot.load(bot.CLINICAL_QUEUE_FILE, [])
    hist["clinical_sources"] = [x for x in bot.load(bot.SOURCES_FILE, []) if x.get("clinical_used") or x.get("clinical_skipped")]
    hist["grants"] = {k: v for k, v in grants.load_verified().items() if grants.confirmed(v)}
    hist["positions"] = {k: v for k, v in positions.load_archive().items() if (v.get("confirmed") or {}).get("model")}
    HISTORY.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    hist = load_history()
    idx, plan = pick_plan(hist)
    if idx is not None:
        print(f"Settimana {idx + 1} del piano")
    only_raw = os.environ.get("ONLY") or ""
    only = {x.strip() for x in only_raw.split(":")[-1].split(",") if x.strip()}   # «1:16» = settimana 1, uscita 16
    if only:          # uscite rifatte: la versione precedente non conta più come pubblicata
        redo = {(sl["date"], iso(sl["date"], sl["time"])) for i, sl in enumerate(plan["slots"], 1) if str(i) in only}
        hist["posted"] = [p for p in hist["posted"] if (p.get("date"), p.get("time")) not in redo]
        hist["stories"] = [e for e in hist["stories"] if (e.get("date"), e.get("time")) not in redo]
    apply_history(hist)
    n_posted, n_stories = len(bot.load(bot.POSTED_FILE, [])), len(stories.load_log())
    report = []
    if os.environ.get("SCREENING", "1") != "0":
        try:
            report.append(screening())
        except Exception as e:
            report.append(f"Screening: errore {str(e)[:200]}")
            print(f"::warning title=Screening::{str(e)[:300]}")
    if plan.get("folder"):
        print(f"Cartella Drive di questa prova: {plan['folder']['name']} (https://drive.google.com/drive/folders/{plan['folder']['id']})")
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
                keep(out, slot["name"])
                saved = drive_preview.upload(out, None, "video/mp4", cfg, file_id=slot["file_id"])
                log = stories.load_log()
                e = {"date": day, "time": iso(day, slot["time"]), "kind": skind, "simulated": True}
                for k in ("grant_id", "family"):
                    if data.get(k):
                        e[k] = data[k]
                log.append(e)
                stories.LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
                report.append(f"{slot['name']}: ok ({skind})" + ("" if saved else " — NON salvato su Drive"))
            elif kind == "reel":
                os.environ["POST_TYPE"] = "reel"
                os.environ["REEL_SOURCE"] = "latest"
                bot.main()
                video, meta = PREVIEW / "reel.mp4", PREVIEW / "reel.json"
                if not video.exists():
                    report.append(f"{slot['name']}: nessun carosello da trasformare in reel")
                    continue
                m = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
                keep(video, slot["name"])
                saved = drive_preview.upload(video, None, "video/mp4", cfg, file_id=slot["file_id"])
                add_posted({"date": day, "time": iso(day, slot["time"]), "id": f"reel-{m.get('reel_of', i)}",
                            "title": m.get("title", ""), "kind": "reel", "reel_of": m.get("reel_of"), "simulated": True})
                report.append(f"{slot['name']}: ok (da «{m.get('title', '')[:60]}», musica {m.get('music', '')})"
                              + ("" if saved else " — NON salvato su Drive"))
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
                li = PREVIEW / "linkedin.txt"             # bozza LinkedIn nelle ultime pagine del PDF
                extra = ("LINKEDIN\n" + li.read_text(encoding="utf-8")) if li.exists() else ""
                drive_preview.carousel_pdf([p.read_bytes() for p in slides], caption, pdf, extra)
                keep(pdf, slot["name"])
                saved = drive_preview.upload(pdf, None, "application/pdf", cfg, file_id=slot["file_id"])
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
                report.append(f"{slot['name']}: ok («{post['title'][:70]}»)" + ("" if saved else " — NON salvato su Drive"))
        except SystemExit as e:
            report.append(f"{slot['name']}: saltato ({e})")
        except Exception as e:
            report.append(f"{slot['name']}: errore {str(e)[:200]}")
            print(f"::warning title=Settimana di prova::{slot['name']}: {str(e)[:300]}")
    if idx is not None:
        added_posted = [p for p in bot.load(bot.POSTED_FILE, [])[n_posted:] if p.get("simulated")]
        added_stories = [e for e in stories.load_log()[n_stories:] if e.get("simulated")]
        save_history(hist, idx if not only else None, added_posted, added_stories)
    import content
    content.save_usage(ROOT / "usage")              # consumo dei modelli del giro (il workflow lo salva sul ramo)
    print("\n===== RIEPILOGO =====\n" + "\n".join(report))
    (ROOT / "week_report.txt").write_text("\n".join(report), encoding="utf-8")


if __name__ == "__main__":
    main()
