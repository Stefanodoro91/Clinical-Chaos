"""Slide «fonte» dei post di metodologia: titolo, autori, rivista e anno dell'articolo da cui nasce il post, presi da
Crossref tramite il DOI scritto nella prima pagina del PDF caricato su Drive. L'immagine della prima pagina compare
solo se l'articolo è pubblicato con licenza Creative Commons (dato di Crossref), con la citazione della licenza;
altrimenti la slide mostra solo la citazione. Nessuna AI."""
import re

import requests

CROSSREF = "https://api.crossref.org/works/"
UA = {"User-Agent": "ClinicalResearchChaosBot/1.0 (mailto:noreply@clinicalresearchchaos.com)"}
RX_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)
META, THUMBS = {}, {}          # id del post → metadati / immagine della prima pagina (solo licenza CC)


def _pdf_bytes(drive, name):
    """Il file di origine in PDF (anche se su Drive non ha estensione o è un documento Google): None se non c'è."""
    import json
    from pathlib import Path
    log = json.loads((Path(__file__).resolve().parent / "sources_log.json").read_text(encoding="utf-8"))
    entry = next((s for s in reversed(log) if s.get("name") == name), None)
    if not entry:
        return None
    meta = drive.files().get(fileId=entry["drive_id"], fields="mimeType", supportsAllDrives=True).execute()
    mime = meta.get("mimeType", "")
    if mime == "application/pdf":
        return drive.files().get_media(fileId=entry["drive_id"], supportsAllDrives=True).execute()
    if mime.startswith("application/vnd.google-apps."):
        return drive.files().export(fileId=entry["drive_id"], mimeType="application/pdf").execute()
    return None


def _first_page(data):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(data)
    page = pdf[0]
    text = page.get_textpage().get_text_range()
    img = page.render(scale=2).to_pil().convert("RGB")
    return text, img


def _crossref(doi):
    r = requests.get(CROSSREF + doi.rstrip(".,;)"), headers=UA, timeout=20)
    r.raise_for_status()
    return r.json()["message"]


def _authors(item):
    names = [f"{a.get('given', '')} {a.get('family', '')}".strip() or a.get("name", "") for a in item.get("author") or []]
    names = [n for n in names if n]
    return ", ".join(names[:3]) + (" et al." if len(names) > 3 else "")


def _cc_license(item):
    """URL della licenza Creative Commons dell'articolo, oppure None."""
    for lic in item.get("license") or []:
        url = lic.get("URL", "")
        if "creativecommons.org" in url and (lic.get("content-version") in (None, "vor", "unspecified")):
            return url
    return None


def _cc_label(url):
    m = re.search(r"licenses/([a-z-]+)/(\d\.\d)", url)
    return f"CC {m.group(1).upper()} {m.group(2)}" if m else "Creative Commons"


def prepare(post, drive):
    """Prepara i dati della slide fonte (META[post id]) e, se la licenza lo permette, l'immagine (THUMBS)."""
    try:
        data = _pdf_bytes(drive, post.get("source", ""))
        if not data:
            return None
        text, img = _first_page(data)
        m = RX_DOI.search(text)
        doi = m.group(1) if m else None
        if not doi:                          # niente DOI in prima pagina: l'unica reference del post con un DOI
            dois = [d.group(1) for d in (RX_DOI.search(r) for r in post.get("references") or []) if d]
            doi = dois[0] if len(dois) == 1 else None
        if not doi:
            print(f"  Fonte: nessun DOI per {post.get('source')}: niente slide fonte")
            return None
        item = _crossref(doi)
        title = " ".join((item.get("title") or [""])[0].split())
        if not title:
            return None
        year = ((item.get("issued") or {}).get("date-parts") or [[None]])[0][0]
        meta = {"title": title, "authors": _authors(item), "journal": (item.get("container-title") or [""])[0],
                "year": year, "doi": item.get("DOI", ""), "license": _cc_license(item)}
        META[post["id"]] = meta
        if meta["license"]:
            THUMBS[post["id"]] = img
            meta["license_label"] = _cc_label(meta["license"])
        print(f"  Fonte: {meta['title'][:70]} ({meta['journal']}, {year}) – "
              + (f"prima pagina mostrata ({meta['license_label']})" if meta["license"] else "solo citazione"))
        return meta
    except Exception as e:
        print(f"  Fonte non preparata ({str(e)[:150]}): niente slide fonte")
        return None
