"""Verifica i link della tabella strumenti (methodology.TOOLS + design_tools): per i DOI chiede a Crossref titolo,
rivista e anno (così si vede che il DOI è proprio quell'articolo), per PubMed legge il titolo della pagina, per gli altri
siti stato HTTP, indirizzo finale e titolo. Stampa un report nel log (GitHub Actions, modalità «links»)."""
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import design_tools  # noqa: E402
import methodology  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "en"}
CR = {"User-Agent": "ClinicalResearchChaosBot/1.0 (mailto:noreply@clinicalresearchchaos.com)"}


def title_of(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.S | re.I)
    return " ".join(m.group(1).split())[:110] if m else ""


def check(name, url):
    try:
        if url.startswith("https://doi.org/"):
            doi = url[len("https://doi.org/"):]
            r = requests.get("https://api.crossref.org/works/" + doi, headers=CR, timeout=25)
            if r.status_code != 200:
                return "FAIL", f"Crossref {r.status_code}"
            m = r.json()["message"]
            year = ((m.get("issued") or {}).get("date-parts") or [[None]])[0][0]
            return "OK", f"{(m.get('title') or [''])[0][:95]} | {(m.get('container-title') or [''])[0][:40]} | {year}"
        r = requests.get(url, headers=UA, timeout=25, allow_redirects=True)
        final = r.url if r.url.rstrip("/") != url.rstrip("/") else ""
        status = "OK" if r.status_code < 400 else ("BLOCKED?" if r.status_code in (401, 403, 429, 503) else "FAIL")
        return status, f"{r.status_code} {title_of(r.text)}" + (f" → {final}" if final else "")
    except Exception as e:
        return "FAIL", str(e)[:120]


def main():
    links = [(n, u) for _, _, ls in methodology.TOOLS for _, n, u in ls] + design_tools.all_links()
    seen, rows = set(), []
    for n, u in links:
        if u in seen:
            continue
        seen.add(u)
        st, info = check(n, u)
        rows.append((st, n, u, info))
        print(f"[{st}] {n} — {u}\n        {info}", flush=True)
    bad = [r for r in rows if r[0] != "OK"]
    print(f"\n{len(rows)} link, {len(rows) - len(bad)} OK, {len(bad)} da controllare")
    for st, n, u, info in bad:
        print(f"  {st}: {n} — {u} ({info})")


if __name__ == "__main__":
    main()
