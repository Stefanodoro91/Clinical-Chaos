"""Diagnostica: per ogni URL stampa stato, tipo, dimensione, titolo e un estratto dei link (solo GET normali)."""
import json, re, sys
import requests
OUT = open("probe_results.txt", "w", encoding="utf-8")
def log(x):
    print(x); OUT.write(x + "\n"); OUT.flush()
H = {"User-Agent": "Mozilla/5.0 (compatible; ClinicalResearchChaosBot/1.0; +https://clinical-chaos-dsv.pages.dev)"}
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    method, url, *body = line.split(" ", 2)
    try:
        if method == "POST":
            r = requests.post(url, json=json.loads(body[0]) if body else {}, headers={**H, "Content-Type": "application/json"}, timeout=40)
        else:
            r = requests.get(url, headers=H, timeout=40)
        t = r.text
        title = re.search(r"<title[^>]*>(.*?)</title>", t, re.S | re.I)
        links = re.findall(r'<a\s[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', t, re.S | re.I)
        txt = [re.sub(r"<[^>]+>|\s+", " ", x[1]).strip() for x in links]
        hits = [x for x in txt if re.search(r"ricercat|rtt|rtd|assegn|dottorat|professor|bando|concors|call|convocator|chamada|grant|fund|proposal|公募|공모", x, re.I)]
        log(f"PROBE {r.status_code}::{url} | {r.headers.get('content-type','')[:40]} | {len(t)} B | {(title.group(1).strip() if title else '')[:80]} | link {len(links)} | esempi: {' || '.join(h[:90] for h in hits[:6])}")
        if "json" in r.headers.get("content-type", ""):
            log(f"JSON {url} | {t[:6000]}")
    except Exception as e:
        log(f"PROBE ERR::{url} | {str(e)[:200]}")
