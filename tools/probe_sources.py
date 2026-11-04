"""Prova delle fonti nuove (branch fonti-ampliate): quanti annunci si leggono e quanti passano i filtri,
senza Gemini e senza scrivere nulla. Per le fonti a zero mostra i link della pagina per tarare i filtri."""
import csv, json, os, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import positions, grants

N_OLD = int(os.environ.get("N_OLD", "64"))
out = ["## Posizioni: fonti nuove", "", "| fonte | letti | pertinenti | errore |", "|---|---|---|---|"]
diag = []
for src in positions.read_sources()[N_OLD:]:
    _, rep = positions.collect([src], guided=False)
    name, n, kept, err = rep[0]
    out.append(f"| {name} | {n} | {kept} | {err[:80]} |")
    print(name, n, kept, err[:120], flush=True)
    if kept == 0 and not src["tipo"].startswith("inpa"):
        try:
            r = requests.get(src["url"], headers=positions.HEADERS, timeout=45)
            host = urlparse(src["url"]).netloc
            links = []
            for m in re.finditer(r'<a\s[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', r.text, re.I | re.S):
                t = grants.html_to_text(m.group(2))[:70]
                u = urljoin(src["url"], m.group(1))
                if len(t) >= 12 and urlparse(u).netloc == host:
                    links.append(f"{t} -> {urlparse(u).path[:90]}")
            diag.append(f"### {name}\nHTTP {r.status_code}, {len(r.text)} caratteri, {len(links)} link interni\n" +
                        "\n".join("- " + l for l in links[40:70]))
        except Exception as e:
            diag.append(f"### {name}\nerrore: {e}")
out += ["", "## Diagnostica fonti a zero", ""] + diag

gf = os.environ.get("GRANTFINDER")
if gf:
    sys.path.insert(0, gf)
    import neurogrant as ng
    http = ng.Http()
    out += ["", "## Bandi: fonti nuove (GrantFinder)", "", "| fonte | pagine | candidati | errore | esempi |", "|---|---|---|---|---|"]
    with open(ROOT / "tools/probe_grant_sources.csv", encoding="utf-8") as f:
        for fonte in csv.DictReader(f, delimiter=";"):
            try:
                recs, n, err = ng.esplora_fonte(http, fonte, 8)
            except Exception as e:
                recs, n, err = [], 0, str(e)
            ex = "; ".join((r.get("titolo") or r.get("title") or "")[:60] for r in recs[:3])
            out.append(f"| {fonte['nome']} | {n} | {len(recs)} | {(err or '')[:70]} | {ex} |")
            print(fonte["nome"], n, len(recs), err, flush=True)
open(os.environ.get("GITHUB_STEP_SUMMARY", "/dev/stdout"), "a").write("\n".join(out) + "\n")
Path("probe_report.md").write_text("\n".join(out))
