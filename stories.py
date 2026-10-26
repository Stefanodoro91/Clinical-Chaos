"""Storie video per Instagram e Facebook (1080×1920, 12 s, brano Pixabay dalla cartella Drive «Musica», o base generata), senza sticker:
- countdown: un bando verificato sul testo ufficiale che scade presto;
- weekly: le novità della settimana (call, posizioni, caroselli).
Testo solo nella zona sicura (niente nei primi 250 px e negli ultimi 340 px, coperti dall'app). Invito: «link in bio»."""
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw

import cards
import grants
import music
import positions

W, H, M, FPS, SECONDS = 1080, 1920, 90, 30, 12.0
font, fit = cards.font, cards.fit


def _hx(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


class _Painter:
    def __init__(self, cfg, accent):
        self.bg = _hx(cfg["colors"]["background"])
        self.soft = cfg["colors"]["muted_text"]
        self.accent = accent

    def mix(self, col, a):
        c = _hx(col)
        return tuple(int(self.bg[i] + (c[i] - self.bg[i]) * a) for i in range(3))


def _ease(t, start, dur=0.5):
    x = max(0.0, min(1.0, (t - start) / dur))
    return 1 - (1 - x) ** 3


def _cta(d, pt, y, text, a):
    f = font("ExtraBold", 46)
    w = d.textlength(text, font=f) + 110
    x = (W - w) / 2
    d.rounded_rectangle((x, y, x + w, y + 108), radius=54, fill=pt.mix(pt.accent, a))
    d.text((x + 55, y + 26), text, font=f, fill=pt.bg)


def countdown_frame(t, data, pt):
    img = Image.new("RGB", (W, H), pt.bg)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W * min(1, t / SECONDS), 14), fill=pt.accent)          # avanza con la storia
    y = 330
    a = _ease(t, 0.1)
    pulse = 0.55 + 0.45 * abs(((t * 1.6) % 2) - 1)
    d.ellipse((M, y + 12, M + 40, y + 52), fill=pt.mix("#FF5A4E", a * pulse))
    hf, hl, hs = fit(d, data["hook"].upper(), "Bold", 44, 32, W - 2 * M - 70, 120, 1.15)
    yy = y + (1 - a) * 30
    for ln in hl:
        d.text((M + 62, yy), ln, font=hf, fill=pt.mix("#FF5A4E", a))
        yy += hs * 1.15
    y = int(max(y + 90, yy + 20))
    n = int(round(data["days"] * _ease(t, 0.6, 1.4)))
    a = _ease(t, 0.6)
    big = font("ExtraBold", 250)
    d.text((M, y), str(n), font=big, fill=pt.mix(pt.accent, a))
    unit = "day" if data["days"] == 1 else "days"
    ux = M + d.textlength(str(data["days"]), font=big) + 40
    d.text((ux, y + 55), unit, font=font("ExtraBold", 100), fill=pt.mix("#FFFFFF", a))
    d.text((ux, y + 165), "left", font=font("ExtraBold", 100), fill=pt.mix("#FFFFFF", a))
    y += 330
    a = _ease(t, 2.2)
    pf, pl, ps = fit(d, data["programme"].upper(), "Bold", 34, 26, W - 2 * M, 90, 1.2)
    for ln in pl:
        d.text((M, y + (1 - a) * 30), ln, font=pf, fill=pt.mix(pt.accent, a))
        y += ps * 1.2
    a = _ease(t, 2.8)
    tf, tl, ts = fit(d, data["title"], "ExtraBold", 74, 46, W - 2 * M, 270, 1.12)
    yy = y + 24 + (1 - a) * 40
    for ln in tl:
        d.text((M, yy), ln, font=tf, fill=pt.mix("#FFFFFF", a))
        yy += ts * 1.12
    y = int(y + 24 + len(tl) * ts * 1.12 + 34)
    for i, (k, v) in enumerate(((data.get("deadline_label", "Deadline"), data["deadline"]), ("Open to", data["open_to"]))):
        a = _ease(t, 4.0 + i * 0.7)
        d.text((M, y + (1 - a) * 30), k.upper(), font=font("Bold", 36), fill=pt.mix(pt.soft, a))
        vf, vl, vs = fit(d, v, "ExtraBold", 62, 40, W - 2 * M, 150, 1.1)
        yv = y + 46 + (1 - a) * 30
        for ln in vl:
            d.text((M, yv), ln, font=vf, fill=pt.mix("#FFFFFF", a))
            yv += vs * 1.1
        y = int(yv + 30)
    a = _ease(t, 6.2)
    if a > 0:
        _cta(d, pt, min(y + 20, H - 340 - 190), "Official call: link in bio", a)
        d.text((M, min(y + 150, H - 340 - 60)), "Checked on the official call · clinicalresearchchaos.com",
               font=font("Regular", 30), fill=pt.mix(pt.soft, a))
    return img


def weekly_frame(t, data, pt):
    img = Image.new("RGB", (W, H), pt.bg)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W * min(1, t / SECONDS), 14), fill=pt.accent)
    a = _ease(t, 0.1)
    if a > 0.3:
        cards.paste_logo(img, "logo-symbol-light", M, 320, height=110)
        cards.paste_logo(img, "logo-wordmark-light", M + 130, 330, height=84)
    y = 500
    hf, hl, hs = fit(d, data["hook"], "ExtraBold", 112, 70, W - 2 * M, 280, 1.05)
    a = _ease(t, 0.4)
    for ln in hl:
        d.text((M, y + (1 - a) * 30), ln, font=hf, fill=pt.mix("#FFFFFF", a))
        y += hs * 1.05
    y = int(y + 50)
    numf = font("ExtraBold", 128)
    lx = M + max(d.textlength(str(r[0]), font=numf) for r in data["rows"]) + 40
    for i, (num, label, col) in enumerate(data["rows"]):
        a = _ease(t, 1.6 + i * 0.8)
        shown = int(round(num * _ease(t, 1.6 + i * 0.8, 1.2)))
        d.text((M, y + (1 - a) * 30), str(shown), font=numf, fill=pt.mix(col, a))
        lf, ll, ls = fit(d, label, "Bold", 50, 34, W - M - lx, 120, 1.1)
        yl = y + 36 + (1 - a) * 30
        for ln in ll:
            d.text((lx, yl), ln, font=lf, fill=pt.mix("#FFFFFF", a))
            yl += ls * 1.1
        y += 180
    a = _ease(t, 4.6)
    if data.get("note") and y < H - 340 - 108 - 180:
        nf, nl, ns = fit(d, data["note"], "SemiBold", 44, 32, W - 2 * M, 110, 1.15)
        for ln in nl:
            d.text((M, y + 10 + (1 - a) * 30), ln, font=nf, fill=pt.mix(pt.soft, a))
            y += ns * 1.15
    a = _ease(t, 6.0)
    if a > 0:
        _cta(d, pt, min(int(y) + 50, H - 340 - 108), "All calls and positions: link in bio", a)
    return img


def render(kind, data, out_path, cfg, seed=0):
    """Scrive l'mp4 della storia e restituisce il percorso. kind = «countdown» oppure «weekly»."""
    accent = cfg.get("grant_accent", "#FFB547") if kind == "countdown" else cfg["colors"]["accent"]
    pt = _Painter(cfg, accent)
    draw = countdown_frame if kind == "countdown" else weekly_frame
    out_path = Path(out_path)
    silent = out_path.with_suffix(".silent.mp4")
    wav = out_path.with_suffix(".wav")
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "21",
                          "-preset", "medium", str(silent)], stdin=subprocess.PIPE)
    for k in range(int(SECONDS * FPS)):
        p.stdin.write(draw(k / FPS, data, pt).tobytes())
    p.stdin.close()
    p.wait()
    music.for_video(wav, SECONDS, seed)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(wav), "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(out_path)], check=True)
    silent.unlink(missing_ok=True)
    wav.unlink(missing_ok=True)
    draw(SECONDS - 0.1, data, pt).save(out_path.with_suffix(".jpg"), quality=88)
    return out_path


# ---------------------------------------------------------------- scelta dei contenuti (solo dati verificati)
ROOT = Path(__file__).resolve().parent
LOG_FILE = ROOT / "stories_log.json"
GRAPH_VERSION = os.environ.get("GRAPH_API_VERSION") or "v23.0"
HOOKS_SOON = ["Last call: closing soon", "Closing soon: save the date", "Final days to apply"]
HOOKS_LATER = ["Deadline alert", "Still time to apply", "Put this in your calendar"]


def load_log():
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def open_to(v):
    """Paesi ammessi solo se citati dal testo ufficiale (countries_evidence); altrimenti None."""
    ec = (v.get("eligible_countries") or "").strip()
    if not v.get("countries_evidence") or not ec or ec.lower().startswith("not stated"):
        return None
    if grants.RX_ANY_COUNTRY.search(ec):
        return "Any country"
    return grants.content._clip(re.sub(r"\s*\([^)]*\)", "", ec).strip(), 60)


def countdown_data(grants_list, verified, log, today=None):
    """Bando verificato (scadenza dal testo ufficiale) che chiude tra 7 e 30 giorni, mai usato in una storia.
    Prima «any country», poi la scadenza più vicina; mai lo stesso programma della storia precedente."""
    today = today or date.today()
    done = {e.get("grant_id") for e in log}
    last_fam = next((e.get("family") for e in reversed(log) if e.get("family")), None)
    pool = []
    for g in grants_list:
        v = verified.get(g.get("id"), {})
        if not (v.get("status") == "ok" and grants.checked(v) and v.get("is_open_call") != "no"
                and not v.get("coming_soon") and g.get("rilevanza") in grants.RELEVANCE_ORDER and g.get("url")
                and g.get("_attivo", True) and g["id"] not in done):
            continue
        d = grants.next_due(g, v, today)
        loi = grants._date(v.get("loi_deadline"))
        if not d or not (7 <= (d - today).days <= 30) or (loi and v.get("loi_required") == "yes" and loi < today):
            continue
        where = open_to(v)
        if not where:
            continue
        fam = v.get("programme_family") or grants.programme_family(g)
        us_only = bool(re.search(r"united states|\bu\.?s\.?\b", where, re.I))
        pool.append(((fam == last_fam, where != "Any country", us_only, grants.RELEVANCE_ORDER[g["rilevanza"]], d), g, v, d, where, fam))
    if not pool:
        return None
    _, g, v, d, where, fam = min(pool, key=lambda x: x[0])
    days = (d - today).days
    label, note = grants.deadline_text(v, d)
    title = v.get("title") if len(v.get("title") or "") >= 15 else g.get("titolo", "")
    rnd = random.Random(today.toordinal())
    return {"grant_id": g["id"], "family": fam, "url": g["url"],
            "hook": rnd.choice(HOOKS_SOON if days <= 12 else HOOKS_LATER), "days": days,
            "programme": grants.content._clip(v.get("programme") or grants.funder_line(g), 60),
            "title": grants.content._clip(title, 110), "deadline_label": label,
            "deadline": grants._fmt_date(d) + (f" ({note})" if note else ""), "open_to": where}


def weekly_data(grants_list, verified, archive, today=None):
    """Numeri della settimana, contati sugli stessi dati delle pagine del sito."""
    today = today or date.today()
    entries = [e for e in grants.page_entries(grants_list, verified, today) if e[1]]       # solo bandi verificati
    soon = [e for e in entries if e[2] and (e[2] - today).days <= 30]
    jobs = positions.active(archive, today)
    new_jobs = [j for j in jobs if (today - (grants._date(j[1].get("first_seen")) or today)).days <= 7]
    rows = [(len(entries), "funding calls open, checked on the official text", "#FFB547"),
            (len(soon), "calls closing in the next 30 days", "#FF8A65")]
    rows.append((len(new_jobs), "new academic positions this week", "#3DD9C1") if new_jobs
                else (len(jobs), "open academic positions", "#3DD9C1"))
    return {"hook": "Your research week in 12 seconds", "rows": [r for r in rows if r[0] > 0],
            "note": "Funding and jobs in clinical research, rehabilitation and biomedical engineering."}


# ---------------------------------------------------------------- pubblicazione (video caricato direttamente)
def publish_instagram(video_path):
    user, token = os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"]
    base = f"https://graph.facebook.com/{GRAPH_VERSION}"
    r = requests.post(f"{base}/{user}/media", data={"media_type": "STORIES", "upload_type": "resumable",
                                                    "access_token": token}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Storia Instagram: contenitore rifiutato {r.status_code}: {r.text[:300]}")
    c = r.json()
    data = Path(video_path).read_bytes()
    r = requests.post(c.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{GRAPH_VERSION}/{c['id']}",
                      headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data))},
                      data=data, timeout=300)
    if not r.ok:
        raise RuntimeError(f"Storia Instagram: caricamento rifiutato {r.status_code}: {r.text[:300]}")
    for _ in range(60):
        s = requests.get(f"{base}/{c['id']}", params={"fields": "status_code", "access_token": token}, timeout=60).json()
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Storia Instagram: video rifiutato (stato {s.get('status_code')})")
        time.sleep(10)
    else:
        raise RuntimeError("Storia Instagram: video non elaborato in tempo")
    r = requests.post(f"{base}/{user}/media_publish", data={"creation_id": c["id"], "access_token": token}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Storia Instagram: pubblicazione rifiutata {r.status_code}: {r.text[:300]}")
    return r.json()["id"]


def publish_facebook(video_path):
    page = os.environ["FB_PAGE_ID"]
    token = os.environ.get("FB_PAGE_TOKEN") or os.environ["IG_ACCESS_TOKEN"]
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{page}/video_stories"
    r = requests.post(url, data={"upload_phase": "start", "access_token": token}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Storia Facebook: avvio rifiutato {r.status_code}: {r.text[:300]}")
    start = r.json()
    data = Path(video_path).read_bytes()
    r = requests.post(start["upload_url"], headers={"Authorization": f"OAuth {token}", "offset": "0",
                                                    "file_size": str(len(data))}, data=data, timeout=300)
    if not r.ok:
        raise RuntimeError(f"Storia Facebook: caricamento rifiutato {r.status_code}: {r.text[:300]}")
    for _ in range(12):
        r = requests.post(url, data={"upload_phase": "finish", "video_id": start["video_id"], "access_token": token},
                          timeout=60)
        if r.ok:
            return r.json().get("post_id") or start["video_id"]
        time.sleep(10)                           # il video può essere ancora in elaborazione
    raise RuntimeError(f"Storia Facebook: chiusura rifiutata {r.status_code}: {r.text[:300]}")


def main():
    dry = os.environ.get("DRY_RUN", "true").lower() != "false"
    kind = os.environ.get("STORY_KIND") or "auto"
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    today = date.today()
    log = load_log()
    if not dry and os.environ.get("GITHUB_EVENT_NAME") == "schedule" and any(e.get("date") == today.isoformat() for e in log):
        print("Storia di oggi già pubblicata: salto.")
        return
    if kind == "auto":
        kind = "weekly" if today.weekday() == 0 else "countdown"
    grants_list = grants.fetch(cfg)
    verified = grants.load_verified()
    if kind == "weekly":
        data = weekly_data(grants_list, verified, positions.load_archive(), today)
        if len(data["rows"]) < 2:
            print("::notice title=Storia::numeri della settimana insufficienti: nessuna storia")
            return
    else:
        data = countdown_data(grants_list, verified, log, today)
        if not data:
            print("::notice title=Storia::nessun bando verificato in scadenza tra 7 e 30 giorni: nessuna storia oggi")
            return
    out = ROOT / "preview" / f"story-{kind}-{today.isoformat()}.mp4"
    out.parent.mkdir(exist_ok=True)
    render(kind, data, out, cfg, seed=today.toordinal())
    print(f"::notice title=Storia pronta::{kind} | {json.dumps({k: v for k, v in data.items() if k != 'rows'}, ensure_ascii=False)[:400]}")
    if dry:
        print("Modalità prova: storia non pubblicata (anteprima negli artifact).")
        return
    entry = {"date": today.isoformat(), "time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind}
    entry["music"] = music.LAST_TRACK.get("name", "")
    for key in ("grant_id", "family"):
        if data.get(key):
            entry[key] = data[key]
    errors = []
    try:
        entry["instagram_id"] = publish_instagram(out)
    except Exception as e:
        errors.append(str(e))
    if cfg.get("facebook", True) and os.environ.get("FB_PAGE_ID"):
        try:
            entry["facebook_id"] = publish_facebook(out)
        except Exception as e:
            errors.append(str(e))
    for e in errors:
        print(f"::warning title=Storia non pubblicata::{e[:300]}")
    if "instagram_id" in entry or "facebook_id" in entry:
        log.append(entry)
        LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"::notice title=Storia pubblicata::{', '.join(k for k in ('instagram_id', 'facebook_id') if k in entry)}")
    elif errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
