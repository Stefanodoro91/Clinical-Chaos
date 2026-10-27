"""Guardiano del calendario: GitHub a volte ritarda o salta i run pianificati (il 27/10 nessuno è partito).
Ogni mezz'ora controlla se un post o una storia di oggi doveva già essere uscito (da almeno 40 minuti) e non c'è
nel registro, e se oggi non è già partito un run per recuperarlo: in quel caso lancia il workflow a mano.
Mai più di un recupero per tipo al giorno; nessuna AI."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
ROME = ZoneInfo("Europe/Rome")
API = f"https://api.github.com/repos/{os.environ.get('GITHUB_REPOSITORY', 'Stefanodoro91/Clinical-Chaos')}/actions"
H = {"Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}", "Accept": "application/vnd.github+json"}
# (tipo, giorni 0=lun, ora, minuto): stesso calendario dei workflow, in ora italiana
CALENDAR = [("story", (0, 1, 2, 3, 4), 9, 31), ("grant", (0, 1, 3, 4), 12, 23), ("reel", (2,), 12, 23),
            ("positions", (0,), 18, 23), ("research", (1, 2, 3), 18, 47), ("research", (5,), 16, 47),
            ("reel", (6,), 17, 47)]


def load(name):
    try:
        return json.loads((ROOT / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def done_today(kind, day):
    """Il contenuto di oggi è già uscito? (data italiana dell'ora di pubblicazione)"""
    if kind == "story":
        log = load("stories_log.json")
        return any(e.get("date") == day.isoformat() for e in log)
    for p in load("posted_log.json"):
        t = p.get("time")
        if not t or (p.get("kind") or "research") != kind:
            continue
        if datetime.fromisoformat(t).astimezone(ROME).date() == day:
            return True
    return False


def runs_since(workflow, since, kind):
    """Run del workflow partiti dopo `since` che riguardano questo tipo (pianificati o lanciati a mano)."""
    r = requests.get(f"{API}/workflows/{workflow}/runs", headers=H, timeout=30,
                     params={"created": f">={since.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}", "per_page": 50})
    r.raise_for_status()
    out = []
    for run in r.json().get("workflow_runs", []):
        title = run.get("display_title") or ""
        if workflow == "stories.yml" or run["event"] == "schedule" or f"Post {kind}" in title:
            if "(prova)" not in title:
                out.append(run)
    return out


def dispatch(workflow, inputs):
    r = requests.post(f"{API}/workflows/{workflow}/dispatches", headers=H, timeout=30,
                      json={"ref": "main", "inputs": inputs})
    print(f"Lancio {workflow} {inputs}: {r.status_code} {r.text[:200]}")


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    now = datetime.now(ROME)
    for kind, days, hh, mm in CALENDAR:
        if now.weekday() not in days or (kind == "reel" and not cfg.get("reels_auto")):
            continue
        due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if not (due + timedelta(minutes=40) <= now <= due + timedelta(hours=5)):
            continue
        if done_today(kind, now.date()):
            continue
        workflow = "stories.yml" if kind == "story" else "daily-post.yml"
        started = runs_since(workflow, due - timedelta(minutes=5), kind)
        if started:
            print(f"{kind}: non ancora uscito, ma un run è già partito ({started[0]['html_url']}): aspetto.")
            continue
        print(f"::warning title=Recupero automatico::{kind} delle {hh:02d}:{mm:02d} non partito: lo lancio ora")
        dispatch(workflow, {"dry_run": "false", "kind": "auto"} if kind == "story"
                 else {"dry_run": "false", "post_type": kind})


if __name__ == "__main__":
    main()
