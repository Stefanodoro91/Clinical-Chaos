"""Guardiano del calendario: GitHub a volte ritarda di ore o salta i run pianificati (27-28/10: storie partite
con 6-9 ore di ritardo, guardiano stesso quasi mai partito). Il guardiano viene svegliato ogni 10 minuti da un
orologio esterno affidabile (Cloudflare Worker, vedi tools/clock-worker.js) e, come riserva, dal suo cron su GitHub.

Per ogni contenuto di oggi già scaduto da almeno 15 minuti (e non più di 3 ore: dopo, un post fuori orario rende
poco e si salta) che non risulta nel registro:
  - se un run di quel tipo è in coda o in corso, aspetta;
  - se un run di quel tipo è finito bene dopo l'orario (es. «nessun bando oggi»), non fa niente;
  - altrimenti lo lancia a mano: al massimo 2 tentativi al giorno per tipo, poi apre un avviso (email).
Nessuna AI."""
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
ROME = ZoneInfo("Europe/Rome")
REPO = os.environ.get("GITHUB_REPOSITORY", "Stefanodoro91/Clinical-Chaos")
API = f"https://api.github.com/repos/{REPO}"
H = {"Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}", "Accept": "application/vnd.github+json"}
# (tipo, giorni 0=lun, ora, minuto): stesso calendario dei workflow, in ora italiana
CALENDAR = [("story", (0, 1, 2, 3, 4), 9, 31), ("grant", (0, 1, 3, 4), 12, 23), ("reel", (2,), 12, 23),
            ("positions", (0,), 18, 23), ("research", (1, 2, 3), 18, 47), ("research", (5,), 16, 47),
            ("reel", (6,), 17, 47)]
GRACE = timedelta(minutes=15)       # GitHub parte spesso con qualche minuto di ritardo: lo si aspetta un po'
LIMIT = timedelta(hours=3)          # oltre, il contenuto si salta (e un run pianificato tardivo salta da solo)
MAX_TRIES = 2


def load(name):
    try:
        return json.loads((ROOT / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def done_today(kind, day):
    """Il contenuto di oggi è già uscito? (data italiana dell'ora di pubblicazione)"""
    if kind == "story":
        return any(e.get("date") == day.isoformat() for e in load("stories_log.json"))
    for p in load("posted_log.json"):
        t = p.get("time")
        if t and (p.get("kind") or "research") == kind and datetime.fromisoformat(t).astimezone(ROME).date() == day:
            return True
    return False


def runs_since(workflow, since, kind):
    """Run reali (non prove) di questo tipo partiti dopo `since`. Il nome del run contiene il tipo anche per i
    run pianificati («Post research (pianificato)»), così un reel in ritardo non viene scambiato per il post di
    metodologia."""
    r = requests.get(f"{API}/actions/workflows/{workflow}/runs", headers=H, timeout=30,
                     params={"created": f">={since.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
                             "per_page": 50})
    r.raise_for_status()
    out = []
    for run in r.json().get("workflow_runs", []):
        title = run.get("display_title") or ""
        if "(prova)" in title:
            continue
        if workflow == "stories.yml" or title.startswith(f"Post {kind}"):
            out.append(run)
    return out


def dispatch(workflow, inputs):
    r = requests.post(f"{API}/actions/workflows/{workflow}/dispatches", headers=H, timeout=30,
                      json={"ref": "main", "inputs": inputs})
    print(f"Lancio {workflow} {inputs}: {r.status_code} {r.text[:200]}")
    time.sleep(8)       # il run compare nell'elenco dopo qualche secondo: il prossimo controllo lo deve vedere
    return r.status_code < 300


def alert(title, body):
    """Avviso via issue (GitHub manda l'email), una sola volta per titolo."""
    r = requests.get(f"{API}/issues", headers=H, timeout=30, params={"state": "open", "labels": "watchdog"})
    if r.ok and any(i.get("title") == title for i in r.json()):
        return
    requests.post(f"{API}/issues", headers=H, timeout=30, json={"title": title, "body": body, "labels": ["watchdog"]})


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    now = datetime.now(ROME)
    print(f"Controllo delle {now:%H:%M} (avvio: {os.environ.get('GITHUB_EVENT_NAME', '?')})")
    for kind, days, hh, mm in CALENDAR:
        if now.weekday() not in days or (kind == "reel" and not cfg.get("reels_auto")):
            continue
        due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if not (due + GRACE <= now <= due + LIMIT):
            continue
        if done_today(kind, now.date()):
            print(f"{kind}: già uscito.")
            continue
        workflow = "stories.yml" if kind == "story" else "daily-post.yml"
        runs = runs_since(workflow, due - timedelta(minutes=10), kind)
        if any(r["status"] != "completed" for r in runs):
            print(f"{kind}: un run è in coda o in corso: aspetto.")
            continue
        if any(r["conclusion"] == "success" for r in runs):
            print(f"{kind}: un run è finito bene senza pubblicare (es. niente da pubblicare oggi): non rilancio.")
            continue
        tries = [r for r in runs if r["event"] == "workflow_dispatch"]
        if len(tries) >= MAX_TRIES:
            alert(f"Recupero fallito: {kind} del {now:%d/%m}",
                  f"Il contenuto «{kind}» delle {hh:02d}:{mm:02d} non è uscito dopo {len(tries)} tentativi "
                  f"automatici. Ultimo run: {tries[0]['html_url']}")
            print(f"::error title=Recupero fallito::{kind}: {len(tries)} tentativi falliti, avviso aperto")
            continue
        print(f"::warning title=Recupero automatico::{kind} delle {hh:02d}:{mm:02d} non uscito: lo lancio ora")
        dispatch(workflow, {"dry_run": "false", "kind": "auto"} if kind == "story"
                 else {"dry_run": "false", "post_type": kind})


if __name__ == "__main__":
    main()
